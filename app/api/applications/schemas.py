from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, field_validator

from app.api.attendees.schemas import Attendee
from app.api.products.schemas import Product
from app.core.security import Token


class Residency(str, Enum):
    CRYPTO_BUILDER = 'Crypto Builder'
    CRYPTO_RESEARCHER = 'Crypto Researcher'
    GENERAL_ENGINEERING = 'General Engineering'
    RESEARCHER = 'Researcher'
    NETWORK_STATE = 'Network State Residency'
    BIOTECH = 'Biotech / Longevity / Biohacking'
    FOUNDER = 'Founder / Startup Residency'


class ApplicationStatus(str, Enum):
    DRAFT = 'draft'
    IN_REVIEW = 'in review'
    REJECTED = 'rejected'
    ACCEPTED = 'accepted'
    WITHDRAWN = 'withdrawn'


class UserSettableStatus(str, Enum):
    DRAFT = ApplicationStatus.DRAFT.value
    IN_REVIEW = ApplicationStatus.IN_REVIEW.value


class ApplicationFilter(BaseModel):
    email: Optional[str] = None
    citizen_id: Optional[int] = None
    popup_city_id: Optional[int] = None
    status: Optional[ApplicationStatus] = None


class ApplicationBaseCommon(BaseModel):
    first_name: str
    last_name: str
    telegram: Optional[str] = None
    organization: Optional[str] = None
    role: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[str] = None
    social_media: Optional[str] = None
    residence: Optional[str] = None
    local_resident: Optional[bool] = None
    eth_address: Optional[str] = None
    duration: Optional[str] = None
    video_url: Optional[str] = None
    payment_capacity: Optional[str] = None
    github_profile: Optional[str] = None
    minting_link: Optional[str] = None

    area_of_expertise: Optional[str] = None
    preferred_dates: Optional[str] = None
    hackathon_interest: Optional[bool] = None
    host_session: Optional[str] = None
    personal_goals: Optional[str] = None
    referral: Optional[str] = None
    info_not_shared: Optional[list[str]] = None
    investor: Optional[bool] = None

    # Renter information
    is_renter: Optional[bool] = None
    booking_confirmation: Optional[str] = None

    # Family information
    brings_spouse: Optional[bool] = None
    spouse_info: Optional[str] = None
    spouse_email: Optional[str] = None
    brings_kids: Optional[bool] = None
    kids_info: Optional[str] = None

    # Builder information
    builder_boolean: Optional[bool] = None
    builder_description: Optional[str] = None

    # Scholarship information
    scholarship_request: Optional[bool] = None
    scholarship_details: Optional[str] = None
    scholarship_video_url: Optional[str] = None

    residencies_interested_in: Optional[list[Residency]] = None
    residencies_text: Optional[str] = None

    requested_discount: Optional[bool] = None
    status: Optional[ApplicationStatus] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(
        str_strip_whitespace=True,
    )


class ApplicationBase(ApplicationBaseCommon):
    citizen_id: int
    popup_city_id: int
    group_id: Optional[int] = None


class ApplicationCreate(ApplicationBase):
    status: Optional[UserSettableStatus] = None


class ApplicationUpdate(ApplicationBaseCommon):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    status: Optional[UserSettableStatus] = None


class InternalApplicationCreate(ApplicationBase):
    email: str
    submitted_at: Optional[datetime] = None
    created_by_leader: Optional[bool] = None
    auto_approved: Optional[bool] = None

    @field_validator('email')
    @classmethod
    def clean_email(cls, value: str) -> str:
        return value.lower()


class Application(InternalApplicationCreate):
    id: int
    attendees: Optional[list[Attendee]] = None
    discount_assigned: Optional[int] = None
    products: Optional[list[Product]] = None
    credit: Optional[float] = None
    red_flag: Optional[bool] = None

    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
    )


class ApplicationWithPopupCity(Application):
    popup_city_name: Optional[str] = None


class ApplicationWithAuth(Application):
    authorization: Token


HIDDEN_VALUE = '*'


class AttendeeInfo(BaseModel):
    name: str
    category: str
    gender: Optional[str] = None
    email: Optional[str] = None


class AttendeesDirectory(BaseModel):
    id: int
    citizen_id: int
    first_name: Union[Optional[str], Literal['*']]
    last_name: Union[Optional[str], Literal['*']]
    email: Union[Optional[str], Literal['*']]
    telegram: Union[Optional[str], Literal['*']]
    brings_kids: Union[Optional[bool], Literal['*']]
    role: Union[Optional[str], Literal['*']]
    organization: Union[Optional[str], Literal['*']]
    personal_goals: Union[Optional[str], Literal['*']]
    residence: Union[Optional[str], Literal['*']]
    age: Union[Optional[str], Literal['*']]
    gender: Union[Optional[str], Literal['*']]
    social_media: Union[Optional[str], Literal['*']]
    builder_boolean: Union[Optional[bool], Literal['*']]
    builder_description: Union[Optional[str], Literal['*']]
    residencies_interested_in: Union[Optional[List[str]], Literal['*']]
    residencies_text: Union[Optional[str], Literal['*']]
    participation: Union[Optional[list[Product]], Literal['*']]
    associated_attendees: Union[Optional[list[AttendeeInfo]], Literal['*']]
    picture_url: Union[Optional[str], Literal['*']]

    model_config = ConfigDict(
        str_strip_whitespace=True,
    )


class AttendeesDirectoryFilter(BaseModel):
    # q is a general query that searches in first_name, last_name, email, telegram, role, organization
    q: Optional[str] = None
    email: Optional[str] = None
    brings_kids: Optional[bool] = None
    participation: Optional[str] = None  # Week numbers comma separated. Example: '2,3'

    model_config = ConfigDict(
        str_strip_whitespace=True,
    )

    @field_validator('participation')
    @classmethod
    def parse_participation(cls, v):
        if not isinstance(v, str):
            return v

        try:
            return [int(week.strip()) for week in v.split(',') if week.strip()]
        except ValueError:
            raise ValueError('participation must be integers (e.g., "1,2")')
