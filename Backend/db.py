# Backend/db.py
from os import getenv
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING
from pymongo.errors import OperationFailure
from .config import settings  # new import but behavior preserved

# Load .env as before (keeps prior behavior)
load_dotenv()

# Use settings.MONGODB_URI (falls back to same default)
MONGODB_URI = settings.MONGODB_URI

client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)

db = client["hr_copilot"]
employee_collection = db["employees"]
leave_collection = db["leaves"]

def safe_create_index(collection, keys, **kwargs):
    try:
        return collection.create_index(keys, **kwargs)
    except OperationFailure as e:
        print(f"⚠️ Skipping index {kwargs.get('name')}: {e}")
        return None

safe_create_index(
    employee_collection,
    [("emp_id", ASCENDING)],
    unique=True,
    name="emp_id_unique",
)

safe_create_index(
    leave_collection,
    [("emp_id", ASCENDING), ("from_date", ASCENDING)],
    name="emp_fromdate",
)

# Lightweight migration (unchanged)
employee_collection.update_many(
    {"leave_balance": {"$type": "number"}},
    [
        {
            "$set": {
                "leave_balance": {
                    "casual": "$leave_balance",
                    "sick": 0,
                }
            }
        }
    ],
)

# Seed sample data (keeps original documents & logic)
if employee_collection.count_documents({}) == 0:
    employees = [
        {
            "emp_id": "10001",
            "name": "Sonal Sharma",
            "project": "Evernorth UIM",
            "leave_balance": {"casual": 12, "sick": 8},
        },
        {
            "emp_id": "10002",
            "name": "Amit Kumar",
            "project": "Newton Fines & Tolls",
            "leave_balance": {"casual": 10, "sick": 6},
        },
        {
            "emp_id": "10003",
            "name": "Aashi Jain",
            "project": "Healthcare Insights",
            "leave_balance": {"casual": 15, "sick": 5},
        },
        {
            "emp_id": "10004",
            "name": "Rohit Verma",
            "project": "Insurance Automation",
            "leave_balance": {"casual": 8, "sick": 12},
        },
    ]
    employee_collection.insert_many(employees)
    print("✅ Employees seeded successfully!")

if getenv("CLEAR_LEAVES_ON_START", "false").lower() in {"1", "true", "yes"}:
    leave_collection.delete_many({})
    print("✅ Leaves collection cleared!")
