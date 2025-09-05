# Backend/schemas.py
from pydantic import BaseModel, Field
from typing import Optional
from datetime import date

class HealthResponse(BaseModel):
    status: str = "ok"

class LeaveRequest(BaseModel):
    employee_id: str = Field(..., example="10001")
    start_date: date
    end_date: date
    reason: Optional[str] = None

class LeaveResponse(BaseModel):
    id: str
    status: str
    requested_by: str
