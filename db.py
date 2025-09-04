from pymongo import MongoClient, ASCENDING
from os import getenv
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# MongoDB connection
MONGODB_URI = getenv("MONGODB_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGODB_URI)

# Database + collections
db = client["hr_copilot"]
leave_collection = db["leaves"]
employee_collection = db["employees"]

# Create indexes for fast lookup
employee_collection.create_index([("emp_id", ASCENDING)], unique=True)
leave_collection.create_index([("emp_id", ASCENDING), ("from", ASCENDING)])

# --- Seed Sample Data ---
if employee_collection.count_documents({}) == 0:
    employees = [
        {
            "emp_id": "10001",
            "name": "Sonal Sharma",
            "project": "Evernorth UIM",
            "leave_balance": {"casual": 12, "sick": 8}
        },
        {
            "emp_id": "10002",
            "name": "Amit Kumar",
            "project": "Newton Fines & Tolls",
            "leave_balance": {"casual": 10, "sick": 6}
        },
        {
            "emp_id": "10003",
            "name": "Aashi Jain",
            "project": "Healthcare Insights",
            "leave_balance": {"casual": 15, "sick": 5}
        },
        {
            "emp_id": "10004",
            "name": "Rohit Verma",
            "project": "Insurance Automation",
            "leave_balance": {"casual": 8, "sick": 12}
        }
    ]
    employee_collection.insert_many(employees)
    print("✅ Employees seeded successfully!")

# Always start fresh with empty leaves collection
leave_collection.delete_many({})
print("✅ Leaves collection cleared!")
