# Backend/main.py
from datetime import date, datetime
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Request, Body
from pydantic import BaseModel, Field
# Use package-qualified import so uvicorn package import works reliably
from Backend.db import employee_collection, leave_collection
# Needed for atomic find_one_and_update return document constant
from pymongo import ReturnDocument
# config + logging (non-breaking)
from .config import settings
from .logging_config import setup_logging
import logging
import re

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
# Chat/parse helpers (new, small & local)
# -----------------------------
DATE_RE = re.compile(r"(\d{4}[/-]\d{2}[/-]\d{2})")

def _parse_iso_like(s: str) -> Optional[date]:
    """
    Parse strings like '2025-09-17' or '2025/09/17' into date object.
    Returns None if invalid.
    """
    if not s:
        return None
    try:
        iso = s.replace("/", "-")
        # datetime.fromisoformat handles YYYY-MM-DD
        return date.fromisoformat(iso)
    except Exception:
        return None

def parse_leave_request(user_input: str) -> Dict[str, Any]:
    """
    Minimal natural-language parsing for leave details.
    Returns a dict with possible keys:
      - 'leave_type'  (defaults to 'casual')
      - 'from_date' (date or None)
      - 'to_date'   (date or None)
      - 'reason'    (cleaned string)
    """
    text = (user_input or "").strip()
    # find date tokens
    matches = DATE_RE.findall(text)
    parsed_dates = [_parse_iso_like(m) for m in matches if _parse_iso_like(m) is not None]

    from_date = None
    to_date = None

    if len(parsed_dates) >= 2:
        # treat first and last as range
        parsed_dates.sort()
        from_date = parsed_dates[0]
        to_date = parsed_dates[-1]
    elif len(parsed_dates) == 1:
        # single date => one-day leave
        from_date = to_date = parsed_dates[0]

    # basic leave type inference
    leave_type = "casual"
    lowered = text.lower()
    if "sick" in lowered:
        leave_type = "sick"
    elif "casual" in lowered or "personal" in lowered or "one day" in lowered:
        leave_type = "casual"

    # reason: remove date substrings from text
    reason = text
    for token in matches:
        reason = reason.replace(token, "")
    reason = reason.strip(" ,.-")

    # If reason becomes empty and user said something like "I want leave for 2025/09/17"
    if not reason:
        reason = ""

    return {
        "leave_type": leave_type,
        "from_date": from_date,
        "to_date": to_date,
        "reason": reason,
    }

def open_leave_form(leave_details: Dict[str, Any], emp_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Prepare the prefill payload for the apply-leave widget / frontend.
    Dates will be returned as ISO strings or None.
    """
    prefill = {
        "emp_id": emp_id,
        "leave_type": leave_details.get("leave_type", "casual"),
        "from_date": (leave_details["from_date"].isoformat() if leave_details.get("from_date") else None),
        "to_date": (leave_details["to_date"].isoformat() if leave_details.get("to_date") else None),
        "reason": leave_details.get("reason", ""),
    }
    return prefill


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

    # --- Minimal fix: if reason looks like a single date (e.g., "2025/09/17"), treat it as one-day leave ---
    reason_date = None
    try:
        # support formats like "2025-09-17" and "2025/09/17"
        candidate = req.reason.strip()
        if candidate:
            candidate_iso = candidate.replace("/", "-")
            # date.fromisoformat will raise if not a valid ISO-like date
            parsed = date.fromisoformat(candidate_iso)
            reason_date = parsed
    except Exception:
        reason_date = None

    # If reason contained a single valid date and the provided from/to are inconsistent,
    # prefer using the reason date as a one-day leave.
    if reason_date is not None:
        logger.info(
            "apply_leave: reason parsed as date for emp_id=%s — using as one-day leave (%s)",
            req.emp_id, reason_date
        )
        req_from = reason_date
        req_to = reason_date
    else:
        # No usable date in reason — keep existing behavior but auto-correct swapped dates.
        if req.from_date > req.to_date:
            logger.info(
                "apply_leave: swapped dates detected for emp_id=%s — auto-correcting (from=%s to=%s)",
                req.emp_id, req.from_date, req.to_date
            )
            req_from = req.to_date
            req_to = req.from_date
        else:
            req_from = req.from_date
            req_to = req.to_date
    # ------------------------------------------------------------------------------

    days_requested = (req_to - req_from).days + 1
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
        "from_date": str(req_from),
        "to_date": str(req_to),
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


# -----------------------------
# Chat endpoint to support Pixie flow
# -----------------------------
@app.post("/chat/apply-leave")
def chat_apply_leave(payload: Dict[str, Any] = Body(...)):
    """
    Payload: {
      "user_input": "<user phrase>",
      "session_state": {"emp_id": "E102", ...}   # session_state optional
    }

    Behavior:
      - If session_state.emp_id missing -> return need_emp_id: True and a prefill object
        (frontend should ask user for emp id and then call apply-leave UI with the prefill data).
      - If emp_id present and valid -> return open_form: True and the prefilled form payload.
    """
    user_input = payload.get("user_input", "") or ""
    session_state = payload.get("session_state", {}) or {}
    emp_id = session_state.get("emp_id")

    parsed = parse_leave_request(user_input)
    prefill = open_leave_form(parsed, emp_id=None)  # prefill without emp_id for now

    if not emp_id:
        # Ask frontend to request emp id but keep the parsed date so UI can prefill after emp id is provided
        logger.info("chat_apply_leave: emp_id missing; asking user to provide it. parsed=%s", parsed)
        return {
            "need_emp_id": True,
            "message": "Please provide your Employee ID before applying for leave so I can fetch your details.",
            "prefill": prefill
        }

    # emp_id present: validate and prepare form for opening
    emp = employee_collection.find_one({"emp_id": emp_id}, {"_id": 0})
    if not emp:
        logger.info("chat_apply_leave: provided emp_id not found: %s", emp_id)
        return {
            "need_emp_id": True,
            "message": f"Employee ID '{emp_id}' not found. Please provide a valid Employee ID.",
            "prefill": prefill
        }

    # include emp details and prefill form values
    prefill_with_emp = prefill.copy()
    prefill_with_emp["emp_id"] = emp_id
    # Optionally include employee name/project so front-end can display them
    prefill_with_emp["employee"] = {
        "emp_id": emp.get("emp_id"),
        "name": emp.get("name"),
        "project": emp.get("project"),
    }

    logger.info("chat_apply_leave: prepared prefill for emp_id=%s parsed=%s", emp_id, parsed)
    return {
        "open_form": True,
        "form_prefill": prefill_with_emp
    }
