"""Report recipients, the on/off switch and the send log. The tables are created when first needed."""

from datetime import datetime, timezone
import re

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.database.tables import ReportLogRow, ReportRecipientRow, ReportSettingRow


EMAIL = re.compile(r"[^@\s,;<>]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+")
MAX_RECIPIENTS = 20
_TABLES = (ReportRecipientRow, ReportSettingRow, ReportLogRow)


def now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ensure_tables(db: Session) -> None:
    bind = db.get_bind()
    have = inspect(bind)
    for table in _TABLES:
        if not have.has_table(table.__tablename__):
            table.__table__.create(bind, checkfirst=True)


def valid_email(address: str) -> bool:
    return len(address) <= 254 and EMAIL.fullmatch(address) is not None


# ---- recipients ----------------------------------------------------------------------------------

def list_recipients(db: Session) -> list[ReportRecipientRow]:
    ensure_tables(db)
    return list(db.scalars(select(ReportRecipientRow).order_by(ReportRecipientRow.email)))


def add_recipient(db: Session, address: str) -> str:
    """Add an address. Returns "" when added, otherwise what is wrong with it."""
    ensure_tables(db)
    address = address.strip().lower()
    if not valid_email(address):
        return "Enter a full email address, such as manager@hotel.com."
    if db.scalar(select(ReportRecipientRow).where(ReportRecipientRow.email == address)) is not None:
        return f"{address} already gets the report."
    if len(list_recipients(db)) >= MAX_RECIPIENTS:
        return f"A report can go to at most {MAX_RECIPIENTS} addresses."
    db.add(ReportRecipientRow(email=address, added_at=now_text()))
    db.commit()
    return ""


def remove_recipient(db: Session, recipient_id: int) -> None:
    ensure_tables(db)
    row = db.get(ReportRecipientRow, recipient_id)
    if row is not None:
        db.delete(row)
        db.commit()


# ---- the switch ----------------------------------------------------------------------------------

def _get(db: Session, key: str) -> str | None:
    row = db.get(ReportSettingRow, key)
    return row.value if row else None


def _set(db: Session, key: str, value: str) -> None:
    row = db.get(ReportSettingRow, key)
    if row is None:
        db.add(ReportSettingRow(key=key, value=value))
    else:
        row.value = value


def is_enabled(db: Session) -> bool:
    ensure_tables(db)
    return _get(db, "enabled") != "0"


def enabled_since(db: Session) -> str:
    """When the weekly report was last turned on (UTC text). Reports due before this are never sent late."""
    ensure_tables(db)
    since = _get(db, "enabled_at")
    if since is None:
        since = now_text()
        _set(db, "enabled_at", since)
        db.commit()
    return since


def set_enabled(db: Session, enabled: bool) -> None:
    ensure_tables(db)
    _set(db, "enabled", "1" if enabled else "0")
    if enabled:
        _set(db, "enabled_at", now_text())
    db.commit()


# ---- the log -------------------------------------------------------------------------------------

def log_attempt(db: Session, *, kind: str, period_end: str, ok: bool, sent_to: int = 0, error: str = "") -> None:
    ensure_tables(db)
    db.add(ReportLogRow(kind=kind, period_end=period_end, status="sent" if ok else "failed", sent_to=sent_to,
                        error=error[:500], created_at=now_text()))
    db.commit()


def last_attempt(db: Session) -> ReportLogRow | None:
    ensure_tables(db)
    return db.scalar(select(ReportLogRow).order_by(ReportLogRow.id.desc()).limit(1))


def already_sent(db: Session, period_end: str) -> bool:
    ensure_tables(db)
    return db.scalar(select(ReportLogRow.id).where(ReportLogRow.kind == "weekly", ReportLogRow.status == "sent",
                                                   ReportLogRow.period_end == period_end)) is not None
