"""Send email over SMTP. The password is never logged or shown in an error."""

from email.message import EmailMessage
from email.utils import formataddr
import logging
import smtplib
import ssl


logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 20


class MailError(Exception):
    """The email could not be sent; the message is safe to show to a manager."""


def mail_ready(settings) -> bool:
    return bool(settings.get("SMTP_HOST") and settings.get("ADMIN_EMAIL"))


def missing_settings(settings) -> list[str]:
    return [name for name in ("ADMIN_EMAIL", "SMTP_HOST") if not settings.get(name)]


def build_message(settings, to: str, subject: str, text: str, html: str | None) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr(("Wastewise", settings["ADMIN_EMAIL"]))
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def send_each(settings, recipients: list[str], subject: str, text: str, html: str | None = None) -> list[str]:
    """Send the message to each address on its own, so nobody sees the others. Returns the addresses it reached.

    Raises MailError if the server cannot be reached or refuses the login or every recipient.
    """
    if not mail_ready(settings):
        raise MailError("Email is not set up: set " + " and ".join(missing_settings(settings)) + ".")
    reached = []
    try:
        if settings["SMTP_SECURITY"] == "ssl":
            server = smtplib.SMTP_SSL(settings["SMTP_HOST"], settings["SMTP_PORT"], timeout=TIMEOUT_SECONDS,
                                      context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(settings["SMTP_HOST"], settings["SMTP_PORT"], timeout=TIMEOUT_SECONDS)
        with server:
            if settings["SMTP_SECURITY"] == "starttls":
                server.starttls(context=ssl.create_default_context())
            if settings["SMTP_PASSWORD"]:
                server.login(settings["SMTP_USER"], settings["SMTP_PASSWORD"])
            for address in recipients:
                try:
                    server.send_message(build_message(settings, address, subject, text, html))
                    reached.append(address)
                except smtplib.SMTPRecipientsRefused:
                    logger.warning("The mail server refused a report recipient.")
    except smtplib.SMTPAuthenticationError:
        raise MailError("The mail server did not accept the login. Check SMTP_USER and SMTP_PASSWORD "
                        "(Gmail needs an app password).") from None
    except (smtplib.SMTPException, OSError) as error:
        logger.warning("Sending the report failed: %s", type(error).__name__)
        raise MailError(f"Could not reach the mail server ({type(error).__name__}). Check SMTP_HOST, SMTP_PORT and SMTP_SECURITY.") from None
    if not reached:
        raise MailError("The mail server refused every address.")
    return reached
