# db.py
from os import getenv
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING

# Load environment variables from .env (if present)
load_dotenv()

# --- MongoDB connection ---
MONGODB_URI = getenv("MONGODB_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)

# Database & collections
db = client["hr_copilot"]
employee_collection = db["employees"]
leave_collection = db["leaves"]

# --- Indexes ---
# Unique employee id for quick lookups
employee_collection.create_index(
    [("emp_id", ASCENDING)],
    unique=True,
    name="emp_id_unique",
)

# Match the actual field stored in leave docs ("from_date"), not "from"
leave_collection.create_index(
    [("emp_id", ASCENDING), ("from_date", ASCENDING)],
    name="emp_fromdate",
)

# --- One-time lightweight migration: normalize legacy leave_balance ints to dict ---
# If any employee doc has leave_balance as a number, convert -> {"casual": <number>, "sick": 0}
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

# --- Seed Sample Data (idempotent) ---
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

# Optional: only clear leaves if you explicitly opt in via env
# Set CLEAR_LEAVES_ON_START=true in .env if you want a clean slate for demos
if getenv("CLEAR_LEAVES_ON_START", "false").lower() in {"1", "true", "yes"}:
    leave_collection.delete_many({})
    print("✅ Leaves collection cleared!")
