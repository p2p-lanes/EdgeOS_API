from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class InternalCheckInCreate(BaseModel):
    code: str
    attendee_id: int
    arrival_date: Optional[datetime] = None
    departure_date: Optional[datetime] = None
    virtual_check_in: bool = False
    qr_check_in: bool = False
    qr_scan_timestamp: Optional[datetime] = None
    virtual_check_in_timestamp: Optional[datetime] = None


class NewCheckIn(BaseModel):
    code: str

    @field_validator('code')
    def validate_code(cls, v):
        if not v:
            raise ValueError('Code is required')
        return v


class NewQRCheckIn(NewCheckIn):
    pass


class NewVirtualCheckIn(NewCheckIn):
    application_id: int
    arrival_date: datetime
    departure_date: datetime


class CheckInResponse(BaseModel):
    success: bool
    first_check_in: bool
    name: Optional[str] = None
    scan_time: Optional[datetime] = None
