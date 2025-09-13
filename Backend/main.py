# Backend/main.py
from datetime import date
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

# Use package-qualified import so uvicorn package import works reliably
from Backend.db import employee_collection, leave_collection

# Needed for atomic find_one_and_update return document constant
from pymongo import ReturnDocument

# config + logging (non-breaking)
from .config import settings
from .logging_config import setup_logging
import logging

# init logging for clearer output (no behavior change)
setup_logging()
logger = logging.getLogger("hr_copilot")

app = FastAPI(title="HR Copilot Backend")

# -----------------------------
# Helpers (unchanged logic)
# -----------------------------
def _normalize_leave_balance(lb) -> dict:
    if isinstance(lb, dict):
        return {
            "casual": int(lb.get("casual", 0)),
            "sick": int(lb.get("sick", 0)),
        }
    total = int(lb or 0)
    return {"casual": total, "sick": 0}


def _ensure_normalized_in_db(emp_id: str, balances: dict) -> None:
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
# Pydantic Models (unchanged fields)
# -----------------------------
class ApplyLeaveRequest(BaseModel):
    emp_id: str = Field(..., description="Employee ID, e.g., 10001")
    leave_type: str = Field(..., description="One of: casual, sick")
    from_date: date
    to_date: date
    reason: str = Field(..., min_length=1)

# -----------------------------
# Endpoints (identical semantics and return shapes)
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

    lb = _normalize_leave_balance(emp.get("leave_balance", {}))
    _ensure_normalized_in_db(emp_id, lb)

    return {"emp_id": emp["emp_id"], "leave_balance": lb}


@app.post("/apply-leave")
def apply_leave(req: ApplyLeaveRequest):
    emp = employee_collection.find_one({"emp_id": req.emp_id})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    if req.leave_type not in ("casual", "sick"):
        raise HTTPException(status_code=400, detail="Invalid leave_type. Use 'casual' or 'sick'.")

    if req.from_date > req.to_date:
        raise HTTPException(status_code=400, detail="Invalid leave dates: from_date > to_date")

    days_requested = (req.to_date - req.from_date).days + 1
    if days_requested <= 0:
        raise HTTPException(status_code=400, detail="Invalid leave duration")

    balances = _normalize_leave_balance(emp.get("leave_balance", {}))
    _ensure_normalized_in_db(req.emp_id, balances)

    filter_query = {
        "emp_id": req.emp_id,
        f"leave_balance.{req.leave_type}": {"$gte": days_requested}
    }
    update = {"$inc": {f"leave_balance.{req.leave_type}": -days_requested}}

    updated = employee_collection.find_one_and_update(
        filter_query,
        update,
        return_document=ReturnDocument.AFTER,
        projection={f"leave_balance.{req.leave_type}": 1, "_id": 0}
    )

    if updated is None:
        latest = employee_collection.find_one({"emp_id": req.emp_id}, {"_id": 0})
        cur_bal = 0
        if latest:
            lb_latest = _normalize_leave_balance(latest.get("leave_balance", {}))
            cur_bal = lb_latest.get(req.leave_type, 0)
        raise HTTPException(
            status_code=400,
            detail=f"Not enough {req.leave_type} leave. Needed {days_requested}, available {cur_bal}"
        )

    leave_doc = {
        "emp_id": req.emp_id,
        "leave_type": req.leave_type,
        "from_date": str(req.from_date),
        "to_date": str(req.to_date),
        "days": days_requested,
        "reason": req.reason,
    }
    try:
        leave_collection.insert_one(leave_doc)
    except Exception as e:
        # same behavior as before: surface error (deduction already done)
        raise HTTPException(status_code=500, detail=f"Failed to record leave: {e}")

    new_balance_val = updated.get("leave_balance", {}).get(req.leave_type)
    return {
        "message": "Leave applied successfully",
        "new_balance": {req.leave_type: int(new_balance_val) if new_balance_val is not None else None},
        "leave": leave_doc,
    }


@app.get("/leave-history/{emp_id}")
def leave_history(emp_id: str):
    leaves = list(
        leave_collection.find({"emp_id": emp_id}, {"_id": 0}).sort("from_date", 1)
    )
    return {"emp_id": emp_id, "history": leaves}


