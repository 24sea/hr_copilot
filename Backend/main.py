# main.py
from datetime import date
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from db import employee_collection, leave_collection

app = FastAPI(title="HR Copilot Backend")

# -----------------------------
# Helpers
# -----------------------------
def _normalize_leave_balance(lb) -> dict:
    """
    Accept either int (legacy) or dict; always return dict with 'casual' and 'sick'.
    """
    if isinstance(lb, dict):
        return {
            "casual": int(lb.get("casual", 0)),
            "sick": int(lb.get("sick", 0)),
        }
    total = int(lb or 0)  # legacy number -> treat as casual-only
    return {"casual": total, "sick": 0}


def _ensure_normalized_in_db(emp_id: str, balances: dict) -> None:
    """
    Persist normalized balances using $set on subfields only.
    (Avoids MongoDB parent/child update path conflicts.)
    """
    employee_collection.update_one(
        {"emp_id": emp_id},
        {
            "$set": {
                "leave_balance.casual": balances["casual"],
                "leave_balance.sick": balances["sick"],
            }
        }
    )

# -----------------------------
# Pydantic Models
# -----------------------------
class ApplyLeaveRequest(BaseModel):
    emp_id: str = Field(..., description="Employee ID, e.g., 10001")
    leave_type: str = Field(..., description="One of: casual, sick")
    from_date: date
    to_date: date
    reason: str = Field(..., min_length=1)

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

@app.get("/employee/{emp_id}")
def get_employee(emp_id: str):
    emp = employee_collection.find_one({"emp_id": emp_id}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return emp

@app.get("/leave-balance/{emp_id}")
def get_leave_balance(emp_id: str):
    emp = employee_collection.find_one({"emp_id": emp_id}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Normalize and persist using subfield $set (safe, no parent/child conflict)
    lb = _normalize_leave_balance(emp.get("leave_balance", {}))
    _ensure_normalized_in_db(emp_id, lb)

    return {"emp_id": emp["emp_id"], "leave_balance": lb}

@app.post("/apply-leave")
def apply_leave(req: ApplyLeaveRequest):
    # Validate employee
    emp = employee_collection.find_one({"emp_id": req.emp_id})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Validate leave type
    if req.leave_type not in ("casual", "sick"):
        raise HTTPException(status_code=400, detail="Invalid leave_type. Use 'casual' or 'sick'.")

    # Validate dates
    if req.from_date > req.to_date:
        raise HTTPException(status_code=400, detail="Invalid leave dates: from_date > to_date")

    # Number of calendar days requested (inclusive)
    days_requested = (req.to_date - req.from_date).days + 1
    if days_requested <= 0:
        raise HTTPException(status_code=400, detail="Invalid leave duration")

    # Normalize balances (handles legacy int or missing keys)
    balances = _normalize_leave_balance(emp.get("leave_balance", {}))
    current_balance = balances.get(req.leave_type, 0)

    if current_balance < days_requested:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough {req.leave_type} leave. Needed {days_requested}, available {current_balance}",
        )

    # 1) Persist normalization safely via subfield $set (no parent/child conflict)
    _ensure_normalized_in_db(req.emp_id, balances)

    # 2) Deduct only the requested bucket in a separate update
    employee_collection.update_one(
        {"emp_id": req.emp_id},
        {"$inc": {f"leave_balance.{req.leave_type}": -days_requested}},
    )

    # Record leave
    leave_doc = {
        "emp_id": req.emp_id,
        "leave_type": req.leave_type,
        "from_date": str(req.from_date),
        "to_date": str(req.to_date),
        "days": days_requested,
        "reason": req.reason,
    }
    leave_collection.insert_one(leave_doc)

    new_balance = current_balance - days_requested
    return {
        "message": "Leave applied successfully",
        "new_balance": {req.leave_type: new_balance},
        "leave": leave_doc,
    }

@app.get("/leave-history/{emp_id}")
def leave_history(emp_id: str):
    leaves = list(
        leave_collection.find({"emp_id": emp_id}, {"_id": 0}).sort("from_date", 1)
    )
    # Return empty list instead of 404 so UI can show a friendly state
    return {"emp_id": emp_id, "history": leaves}
