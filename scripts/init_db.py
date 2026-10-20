"""Create the database tables, optionally with demo data.

    python scripts/init_db.py          create any missing tables
    python scripts/init_db.py --seed   also add demo areas, users and records

Uses DATABASE_URL if set, otherwise instance/food_waste.sqlite3.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_settings  # noqa: E402
from app.database.connection import create_database_engine, init_db, make_session_factory  # noqa: E402
from app.database.seed import seed_demo_data  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", action="store_true", help="Add synthetic development data.")
    args = parser.parse_args()

    engine = create_database_engine(load_settings()["DATABASE_URL"])
    init_db(engine)
    print("Database schema ready.")
    if args.seed:
        with make_session_factory(engine)() as session:
            credentials = seed_demo_data(session)
        print("Synthetic demo data added. Save these one-time passwords:")
        for username, password in credentials.items():
            print(f"  {username}: {password}")


if __name__ == "__main__":
    main()
