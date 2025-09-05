# demo_seed.py
"""
Run: python demo_seed.py
Seeds the demo DB with sample employees and a sample leave.
"""
from Backend.db import get_db
from Backend.config import settings
import pprint
import datetime

def seed():
    db = get_db()
    # sample employees collection
    employees = [
        {"employee_id": "10001", "name": "Alice", "department": "Engineering"},
        {"employee_id": "10002", "name": "Bob", "department": "HR"},
    ]
    db.employees.delete_many({})
    db.employees.insert_many(employees)

    # sample leaves
    db.leaves.delete_many({})
    res = db.leaves.insert_one({
        "employee_id": "10001",
        "start_date": datetime.datetime.utcnow(),
        "end_date": datetime.datetime.utcnow(),
        "reason": "Demo",
        "status": "approved",
        "created_at": datetime.datetime.utcnow()
    })
    print("Inserted sample leave id:", res.inserted_id)
    print("DB seeded for", settings.DB_NAME)

if __name__ == "__main__":
    seed()
