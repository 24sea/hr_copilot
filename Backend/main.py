# Backend/main.py
from datetime import date, datetime, timedelta
from typing import List, Optional
import csv
import io
import logging
import tempfile
import os
import asyncio

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field, ValidationError

# package-qualified imports so uvicorn Backend.main:app works
from Backend.db import employee_collection, leave_collection
from pymongo import ReturnDocument, UpdateOne

from .config import settings
from .logging_config import setup_logging

# optional audio libs detection (attempt import here to provide helpful error early)
try:
    import speech_recognition as sr  # pip install SpeechRecognition
    from pydub import AudioSegment    # pip install pydub (requires ffmpeg)
    AUDIO_LIBS_AVAILABLE = True
except Exception:
    AUDIO_LIBS_AVAILABLE = False

# init logging
setup_logging()
logger = logging.getLogger("hr_copilot")

app = FastAPI(title="HR Copilot Backend")

# -----------------------------
# Helpers
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


def count_business_days(start_date: date, end_date: date, holidays_map: Optional[dict] = None) -> int:
    """Count Mon-Fri days excluding holidays_map if provided. holidays_map format: { '2025': ['2025-01-26', ...], ... }"""
    holidays_map = holidays_map or {}
    d = start_date
    cnt = 0
    while d <= end_date:
        if d.weekday() < 5 and not _is_holiday(d, holidays_map):
            cnt += 1
        d += timedelta(days=1)
    return cnt


def _is_holiday(d: date, holidays_map: dict) -> bool:
    year = str(d.year)
    return str(d) in holidays_map.get(year, [])


# -----------------------------
# Pydantic Models
# -----------------------------
class ApplyLeaveRequest(BaseModel):
    emp_id: str = Field(..., description="Employee ID, e.g., 10001")
    leave_type: str = Field(..., description="One of: casual, sick")
    from_date: date
    to_date: date
    reason: str = Field(..., min_length=1)


class EmployeeIn(BaseModel):
    emp_id: str
    name: str
    project: str
    leave_balance: dict = {"casual": 0, "sick": 0}
    hire_date: Optional[date]


# -----------------------------
# Endpoints
# -----------------------------
@app.get("/")
def health_check():
    return {"status": "ok", "message": "HR Copilot backend is running 🚀"}


# Pagination + safe cap for listing employees
MAX_LIMIT = getattr(settings, "MAX_EMPLOYEES_PAGE", 1000)


@app.get("/employees")
def list_employees(skip: int = 0, limit: int = 50):
    """
    Paginated employees list.
    skip: number of documents to skip
    limit: page size (capped by MAX_LIMIT)
    """
    limit = min(int(limit), MAX_LIMIT)
    skip = max(int(skip), 0)
    cursor = employee_collection.find({}, {"_id": 0}).skip(skip).limit(limit)
    employees = list(cursor)
    total = employee_collection.count_documents({})
    return {"total": total, "skip": skip, "limit": limit, "employees": employees}


@app.post("/employee")
def create_employee(emp: EmployeeIn):
    doc = emp.dict()
    # Ensure leave_balance is normalized dict
    doc["leave_balance"] = _normalize_leave_balance(doc.get("leave_balance", {}))

    # 🔹 Convert hire_date to string before saving
    if doc.get("hire_date"):
        doc["hire_date"] = str(doc["hire_date"])

    res = employee_collection.update_one({"emp_id": doc["emp_id"]}, {"$set": doc}, upsert=True)
    return {
        "message": "Employee created/updated",
        "matched_count": res.matched_count,
        "upserted_id": str(res.upserted_id) if res.upserted_id else None
    }


@app.post("/employees/import")
async def import_employees_csv(file: UploadFile = File(...), batch_size: int = Form(1000)):
    batch_size = max(1, min(int(batch_size), 5000))

    content = await file.read()
    try:
        s = content.decode("utf-8")
    except Exception:
        s = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(s))
    to_upsert = []
    updated = 0
    skipped = []
    row_index = 0

    for row in reader:
        row_index += 1
        raw_emp_id = (row.get("emp_id") or row.get("employee_id") or "").strip()
        raw_name = (row.get("name") or "").strip()
        raw_project = (row.get("project") or "").strip()
        raw_casual = (row.get("casual") or "").strip()
        raw_sick = (row.get("sick") or "").strip()
        raw_hire_date = (row.get("hire_date") or "").strip()

        try:
            casual = int(raw_casual) if raw_casual != "" else 0
        except Exception:
            casual = 0
        try:
            sick = int(raw_sick) if raw_sick != "" else 0
        except Exception:
            sick = 0

        candidate = {
            "emp_id": raw_emp_id,
            "name": raw_name,
            "project": raw_project,
            "leave_balance": {"casual": casual, "sick": sick},
        }
        if raw_hire_date:
            candidate["hire_date"] = raw_hire_date

        try:
            emp_obj = EmployeeIn.parse_obj(candidate)
        except ValidationError as ve:
            errs = "; ".join([f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in ve.errors()])
            skipped.append({"row": row_index, "data": row, "reason": errs})
            logger.warning(f"Skipping CSV row {row_index} due to validation error: {errs}")
            continue

        doc = emp_obj.dict()
        doc["leave_balance"] = _normalize_leave_balance(doc.get("leave_balance", {}))

        # 🔹 Convert hire_date to string before saving
        if doc.get("hire_date"):
            doc["hire_date"] = str(doc["hire_date"])

        to_upsert.append(doc)
        if len(to_upsert) >= batch_size:
            ops = [UpdateOne({"emp_id": d["emp_id"]}, {"$set": d}, upsert=True) for d in to_upsert]
            res = employee_collection.bulk_write(ops, ordered=False)
            updated += res.modified_count or 0
            to_upsert = []

    if to_upsert:
        ops = [UpdateOne({"emp_id": d["emp_id"]}, {"$set": d}, upsert=True) for d in to_upsert]
        res = employee_collection.bulk_write(ops, ordered=False)
        updated += res.modified_count or 0

    total = employee_collection.count_documents({})
    return {
        "message": "Import completed",
        "total_in_db": total,
        "updated_approx": updated,
        "skipped_count": len(skipped),
        "skipped_rows_preview": skipped[:50]
    }


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

    if getattr(settings, "EXCLUDE_WEEKENDS_FROM_LEAVE", False):
        holidays_map = getattr(settings, "HOLIDAYS_MAP", {})
        effective_days = count_business_days(req.from_date, req.to_date, holidays_map)
        if effective_days <= 0:
            raise HTTPException(status_code=400, detail="Requested dates are holidays/weekends only")
        days_to_deduct = effective_days
    else:
        days_to_deduct = days_requested

    balances = _normalize_leave_balance(emp.get("leave_balance", {}))
    _ensure_normalized_in_db(req.emp_id, balances)

    overlap_exists = leave_collection.find_one({
        "emp_id": req.emp_id,
        "$or": [
            {"from_date": {"$lte": str(req.to_date)}, "to_date": {"$gte": str(req.from_date)}}
        ],
    })
    if overlap_exists:
        raise HTTPException(status_code=400, detail="Leave overlaps with an existing leave request.")

    filter_query = {
        "emp_id": req.emp_id,
        f"leave_balance.{req.leave_type}": {"$gte": days_to_deduct}
    }
    update = {"$inc": {f"leave_balance.{req.leave_type}": -days_to_deduct}}

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
            detail=f"Not enough {req.leave_type} leave. Needed {days_to_deduct}, available {cur_bal}"
        )

    leave_doc = {
        "emp_id": req.emp_id,
        "leave_type": req.leave_type,
        "from_date": str(req.from_date),
        "to_date": str(req.to_date),
        "days": days_to_deduct,
        "reason": req.reason,
        "status": "applied",
        "created_at": datetime.utcnow(),
    }
    try:
        leave_collection.insert_one(leave_doc)
    except Exception as e:
        logger.exception("Failed to insert leave record after deduction")
        raise HTTPException(status_code=500, detail=f"Failed to record leave: {e}")

    new_balance_val = updated.get("leave_balance", {}).get(req.leave_type)
    return {
        "message": "Leave applied successfully",
        "new_balance": {req.leave_type: int(new_balance_val) if new_balance_val is not None else None},
        "leave": leave_doc,
    }


@app.get("/leave-history/{emp_id}")
def leave_history(emp_id: str, skip: int = 0, limit: int = 100):
    skip = max(int(skip), 0)
    limit = min(int(limit), 1000)
    cursor = leave_collection.find({"emp_id": emp_id}, {"_id": 0}).sort("from_date", 1).skip(skip).limit(limit)
    leaves = list(cursor)
    return {"emp_id": emp_id, "skip": skip, "limit": limit, "history": leaves}


# -----------------------------
# Audio transcription endpoint (async-safe)
# -----------------------------

# Max accepted audio upload size (bytes)
MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB


async def _sync_transcribe_audio(contents: bytes, suffix: str) -> str:
    """
    Blocking helper to be executed in a thread:
    - converts input bytes to WAV using pydub
    - uses SpeechRecognition (Google Web Speech) to transcribe
    Returns transcribed text (possibly empty string).
    """
    # local imports inside thread to avoid import issues in async context
    try:
        import speech_recognition as sr
        from pydub import AudioSegment
    except Exception as e:
        raise RuntimeError("Audio libraries not available in worker: " + str(e))

    in_path = None
    out_wav = None
    try:
        # write input bytes to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
            tf.write(contents)
            in_path = tf.name

        # convert to WAV using pydub (ffmpeg must be installed)
        audio = AudioSegment.from_file(in_path)
        out_wav = in_path + ".wav"
        audio.export(out_wav, format="wav")

        # transcribe using SpeechRecognition
        recognizer = sr.Recognizer()
        with sr.AudioFile(out_wav) as source:
            audio_data = recognizer.record(source)

        try:
            text = recognizer.recognize_google(audio_data)
        except sr.UnknownValueError:
            text = ""
        except sr.RequestError as e:
            # wrap network/provider errors
            raise RuntimeError(f"Speech recognition request failed: {e}")

        return text
    finally:
        # best-effort cleanup
        try:
            if in_path and os.path.exists(in_path):
                os.remove(in_path)
        except Exception:
            pass
        try:
            if out_wav and os.path.exists(out_wav):
                os.remove(out_wav)
        except Exception:
            pass


@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """
    Async-safe audio transcription endpoint:
    - enforces size limit
    - offloads blocking conversion+recognition to a thread via asyncio.to_thread
    - returns {"text": "<transcribed text>"}
    """
    if not AUDIO_LIBS_AVAILABLE:
        raise HTTPException(
            status_code=500,
            detail="Server audio libs not available. Install 'SpeechRecognition' and 'pydub' and ensure ffmpeg is installed."
        )

    # read uploaded bytes
    try:
        contents = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {e}")

    if not contents:
        raise HTTPException(status_code=400, detail="Empty audio file uploaded.")

    if len(contents) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail=f"Audio file too large (max {MAX_AUDIO_BYTES // (1024*1024)} MB).")

    # choose suffix from original filename (fallback to .wav)
    orig_suffix = os.path.splitext(file.filename or "")[1].lower() or ".wav"

    try:
        # run blocking work in threadpool to avoid blocking event loop
        text = await asyncio.to_thread(_sync_transcribe_audio, contents, orig_suffix)
    except RuntimeError as e:
        # wrapper for SpeechRecognition RequestError or local import problems
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audio conversion/transcription failed: {e}")

    return {"text": text}
