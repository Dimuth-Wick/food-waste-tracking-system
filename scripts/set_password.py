"""Set a user's password, or create a manager or administrator who can sign in.

    python scripts/set_password.py demo_manager                 ask for a new password
    python scripts/set_password.py demo_manager --generate      make one up and print it once
    python scripts/set_password.py anna --create --name "Anna Perera" --role manager

Uses DATABASE_URL if set, otherwise instance/food_waste.sqlite3. Anyone signed in as that user is signed out.
"""

import argparse
import getpass
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.config import load_settings  # noqa: E402
from app.database.connection import create_database_engine, init_db, make_session_factory  # noqa: E402
from app.database.queries import create_user, set_user_password  # noqa: E402
from app.database.tables import UserRow  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("username")
    parser.add_argument("--generate", action="store_true", help="Make up a strong password and print it once.")
    parser.add_argument("--create", action="store_true", help="Create the user if they do not exist.")
    parser.add_argument("--name", help="Full name, with --create.")
    parser.add_argument("--role", choices=["manager", "admin"], default="manager", help="Role, with --create.")
    args = parser.parse_args()

    engine = create_database_engine(load_settings()["DATABASE_URL"])
    init_db(engine)
    with make_session_factory(engine)() as db:
        row = db.scalar(select(UserRow).where(UserRow.username == args.username))
        if row is None and not args.create:
            sys.exit(f'There is no user "{args.username}". Add --create --name "Full Name" to make one.')
        if row is not None and args.create:
            sys.exit(f'"{args.username}" already exists. Leave out --create to change their password.')

        if args.generate:
            password = secrets.token_urlsafe(12)
        else:
            password = getpass.getpass("New password (at least 8 characters): ")
            if password != getpass.getpass("Type it again: "):
                sys.exit("The two passwords are not the same. Nothing was changed.")
        if len(password) < 8:
            sys.exit("The password must have at least 8 characters. Nothing was changed.")
        try:
            if row is None:
                if not args.name:
                    sys.exit("--create needs --name.")
                create_user(db, name=args.name, username=args.username, password=password, role=args.role)
                print(f'Created {args.role} "{args.username}".')
            else:
                set_user_password(db, row.id, password)
                print(f'Changed the password for "{args.username}" ({row.role}).')
        except ValueError as error:
            sys.exit(str(error))
    if args.generate:
        print(f"Password: {password}")
        print("It is not stored anywhere else. Write it down now.")


if __name__ == "__main__":
    main()
