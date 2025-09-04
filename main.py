from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import date
from db import employee_collection, leave_collection
from bson import ObjectId

app = FastAPI(title="HR Copilot Backend")

# -----------------------------
# Pydantic Models
# -----------------------------
class ApplyLeaveRequest(BaseModel):
    emp_id: str
    leave_type: str  # e.g., "casual" or "sick"
    from_date: date
    to_date: date
    reason: str


# -----------------------------
# Endpoints
# -----------------------------
@app.get("/")
def health_check():
    return {"status": "ok", "message": "HR Copilot backend is running 🚀"}


@app.get("/employees")
def list_employees():
    employees = list(employee_collection.find({}, {"_id": 0}))
    return {"employees": employees}


@app.get("/leave-balance/{emp_id}")
def get_leave_balance(emp_id: str):
    emp = employee_collection.find_one({"emp_id": emp_id}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {"emp_id": emp["emp_id"], "leave_balance": emp["leave_balance"]}


@app.post("/apply-leave")
def apply_leave(req: ApplyLeaveRequest):
    emp = employee_collection.find_one({"emp_id": req.emp_id})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Days applied
    days_requested = (req.to_date - req.from_date).days + 1
    if days_requested <= 0:
        raise HTTPException(status_code=400, detail="Invalid leave dates")

    if emp["leave_balance"] < days_requested:
        raise HTTPException(status_code=400, detail="Not enough leave balance")

    # Deduct balance
    employee_collection.update_one(
        {"emp_id": req.emp_id},
        {"$inc": {"leave_balance": -days_requested}}
    )

    # Save leave record
    leave_doc = {
        "emp_id": req.emp_id,
        "leave_type": req.leave_type,
        "from_date": str(req.from_date),
        "to_date": str(req.to_date),
        "days": days_requested,
        "reason": req.reason
    }
    leave_collection.insert_one(leave_doc)

    return {"message": "Leave applied successfully", "leave": leave_doc}


@app.get("/leave-history/{emp_id}")
def leave_history(emp_id: str):
    leaves = list(
        leave_collection.find({"emp_id": emp_id}, {"_id": 0}).sort("from_date", 1)
    )
    if not leaves:
        raise HTTPException(status_code=404, detail="No leave history found")
    return {"emp_id": emp_id, "history": leaves}
