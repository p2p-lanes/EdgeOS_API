from datetime import datetime
from typing import List, Optional
from enum import Enum

from pydantic import BaseModel, ConfigDict

from app.api.citizens.schemas import Citizen


class BadgeCode(str, Enum):
    PHYSICAL_SESSIONS = 'UGh5c2ljYWwgU2Vzc2lvbnMC'
    MINDFULLNESS_SESSIONS = 'TWluZGZ1bGxuZXNzIFNlc3Npb25z'
    LAKE_PLUGIN = 'TGFrZSBwbHVnaW4C'
    SAUNA = 'U2F1bmEC'


class AchievementBase(BaseModel):
    sender_id: Optional[int] = None
    receiver_id: int
    achievement_type: str
    badge_type: Optional[str] = None
    sent_at: datetime
    message: Optional[str] = None
    model_config = ConfigDict(
        str_strip_whitespace=True,
    )


class AchievementCreate(BaseModel):
    receiver_id: int
    achievement_type: str
    badge_type: Optional[str] = None
    message: Optional[str] = None
    privacy: Optional[bool] = False


class Achievement(AchievementBase):
    id: int

    model_config = ConfigDict(
        from_attributes=True,
    )


class AchievementFilter(BaseModel):
    id: Optional[int] = None
    id_in: Optional[List[int]] = None
    sender_id: Optional[int] = None
    receiver_id: Optional[int] = None
    achievement_type: Optional[str] = None
    message: Optional[str] = None
    sent_at_from: Optional[datetime] = None
    sent_at_to: Optional[datetime] = None


class AchievementWithCitizen(BaseModel):
    achievement: Achievement
    citizen: Optional[Citizen] = None


class AchievementResponse(BaseModel):
    sent_achievements: List[AchievementWithCitizen]
    received_achievements: List[AchievementWithCitizen]
