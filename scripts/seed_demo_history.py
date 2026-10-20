"""Seed script to populate historical records with demo data.

This script inserts fake historical consumption records into the existing 
`waste_records` SQLite database so that the Historical Prediction Accuracy 
charts can be tested on the Meal Forecast page.

It marks records as demo data within the `notes` JSON payload and safely 
removes any existing demo records before inserting, preventing duplicates.

    python scripts/seed_demo_history.py            add the demo records
    python scripts/seed_demo_history.py --remove   remove them again

It changes the app's real database (instance/food_waste.sqlite3).
"""

import json
import random
import sys
import sqlite3
import datetime
from pathlib import Path

# The app's database, found from this file so the script works from any folder.
DAYS = 30   # days of history per food item

DB_PATH = Path(__file__).resolve().parent.parent / "instance" / "food_waste.sqlite3"

# Define the 5 food items and appropriate meal types for them
ITEMS = [
    {"food_item": "Fried rice", "meal_types": ["Breakfast", "Lunch", "Dinner"], "portion_per_guest": 0.25},
    {"food_item": "Chicken curry", "meal_types": ["Breakfast", "Lunch", "Dinner"], "portion_per_guest": 0.15},
    {"food_item": "Steamed rice", "meal_types": ["Breakfast", "Lunch", "Dinner"], "portion_per_guest": 0.20},
    {"food_item": "Vegetable curry", "meal_types": ["Breakfast", "Lunch", "Dinner"], "portion_per_guest": 0.12},
    {"food_item": "Noodles", "meal_types": ["Breakfast", "Lunch", "Dinner"], "portion_per_guest": 0.22},
]

def remove_demo_data():
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}")
        return
    conn = sqlite3.connect(DB_PATH)
    removed = conn.execute("DELETE FROM waste_records WHERE notes LIKE '%\"is_demo_history\": true%'").rowcount
    conn.commit()
    conn.close()
    print(f"Removed {removed} demo records.")


def generate_demo_data():
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Delete existing demo records to prevent duplicates
    # We identify them by checking if "is_demo_history" is true in the notes.
    cursor.execute("DELETE FROM waste_records WHERE notes LIKE '%\"is_demo_history\": true%'")
    deleted_count = cursor.rowcount
    print(f"Cleared {deleted_count} old demo records.")

    # We need valid area_id, category_id, reason_id, user_id from the DB
    try:
        area_id = cursor.execute("SELECT id FROM areas LIMIT 1").fetchone()[0]
        category_id = cursor.execute("SELECT id FROM categories LIMIT 1").fetchone()[0]
        reason_id = cursor.execute("SELECT id FROM reasons LIMIT 1").fetchone()[0]
        user_id = cursor.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
    except Exception as e:
        print("Error: Required foreign keys (area, category, reason, user) not found. Have you seeded the database?")
        return

    base_date = datetime.date.today() - datetime.timedelta(days=DAYS)
    records_inserted = 0

    # 2. Insert one historical record per day for each of the 5 food items
    for item in ITEMS:
        for i in range(DAYS):
            # Advance date by 1 day per record
            record_date = base_date + datetime.timedelta(days=i)
            # Create a realistic timestamp
            event_at = f"{record_date.isoformat()}T12:00:00Z"
            
            meal_type = random.choice(item["meal_types"])
            guest_count = random.randint(80, 200)
            
            # Create realistic consumed quantity + a small random variance
            variance = random.uniform(0.9, 1.1)
            consumed_quantity = round(guest_count * item["portion_per_guest"] * variance, 2)
            
            # Store payload in notes
            notes_payload = {
                "meal_type": meal_type,
                "food_item": item["food_item"],
                "guest_count": guest_count,
                "consumed_quantity": consumed_quantity,
                "is_demo_history": True,
                "description": "Demo historical record for testing UI"
            }
            notes_json = json.dumps(notes_payload)
            
            # quantity_kg here represents waste, which the forecast API ignores, so we just set 1.0
            waste_qty = 1.0
            
            cursor.execute(
                """
                INSERT INTO waste_records 
                (event_at, area_id, category_id, reason_id, quantity_kg, user_id, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event_at, area_id, category_id, reason_id, waste_qty, user_id, notes_json)
            )
            records_inserted += 1

    conn.commit()
    conn.close()

    print(f"Successfully inserted {records_inserted} demo records.")
    print("Food items seeded:")
    for item in ITEMS:
        print(f" - {item['food_item']} ({DAYS} records)")

if __name__ == "__main__":
    if "--remove" in sys.argv[1:]:
        remove_demo_data()
    else:
        generate_demo_data()
