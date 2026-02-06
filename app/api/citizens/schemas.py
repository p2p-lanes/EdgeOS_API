from datetime import datetime
from typing import List, Optional
from urllib.parse import unquote

from pydantic import (
    BaseModel,
    ConfigDict,
    field_validator,
    model_validator,
    validate_email,
)


class Authenticate(BaseModel):
    email: Optional[str] = None
    popup_slug: Optional[str] = None
    use_code: Optional[bool] = False
    signature: Optional[str] = None
    world_address: Optional[str] = None
    verified_upon_login: Optional[str] = None
    world_redirect: bool = False
    source: Optional[str] = None
    model_config = ConfigDict(
        str_strip_whitespace=True,
        str_to_lower=True,
    )

    @field_validator('email')
    @classmethod
    def decode_email(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        _, email = validate_email(unquote(value))
        return email

    @field_validator('world_address')
    @classmethod
    def decode_world_address(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return value.lower()

    @model_validator(mode='after')
    def validate_email_requirement(self):
        # If source is 'app', email is optional (can use world_address instead)
        if self.source == 'app':
            if not self.email and not self.world_address:
                raise ValueError(
                    'Either email or world_address must be provided when source is app'
                )
        else:
            # For other sources, email is required
            if not self.email:
                raise ValueError('Email is required when source is not app')
        return self


class AuthenticateThirdParty(BaseModel):
    email: str

    model_config = ConfigDict(
        str_strip_whitespace=True,
        str_to_lower=True,
    )

    @field_validator('email')
    @classmethod
    def decode_email(cls, value: str) -> str:
        if not value:
            raise ValueError('Email cannot be empty')
        _, email = validate_email(unquote(value))
        return email


class CitizenBase(BaseModel):
    primary_email: str
    secondary_email: Optional[str] = None
    email_validated: Optional[bool] = False
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    x_user: Optional[str] = None
    telegram: Optional[str] = None
    gender: Optional[str] = None
    role: Optional[str] = None
    organization: Optional[str] = None
    picture_url: Optional[str] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator('primary_email')
    @classmethod
    def decode_primary_email(cls, value: str) -> str:
        return unquote(value)

    @field_validator('secondary_email')
    @classmethod
    def decode_secondary_email(cls, value: Optional[str]) -> Optional[str]:
        return unquote(value) if value else None

    model_config = ConfigDict(str_strip_whitespace=True)


class CitizenCreate(CitizenBase):
    primary_email: str

    @field_validator('primary_email')
    @classmethod
    def validate_primary_email(cls, value: str) -> str:
        _, email = validate_email(unquote(value))
        return email


class InternalCitizenCreate(CitizenCreate):
    spice: Optional[str] = None
    code: Optional[int] = None
    code_expiration: Optional[datetime] = None
    world_address: Optional[str] = None


class CitizenUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    x_user: Optional[str] = None
    telegram: Optional[str] = None
    gender: Optional[str] = None
    role: Optional[str] = None
    organization: Optional[str] = None
    picture_url: Optional[str] = None

    model_config = ConfigDict(str_strip_whitespace=True)


class Citizen(CitizenBase):
    id: int
    edge_mapped_sent: bool = False

    model_config = ConfigDict(
        from_attributes=True,
    )


class ApplicationData(BaseModel):
    id: int
    residence: Optional[str] = None
    personal_goals: Optional[str] = None


class CitizenPopupData(BaseModel):
    id: int
    popup_name: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    total_days: int
    location: Optional[str] = None
    image_url: Optional[str] = None
    application: Optional[ApplicationData] = None


class CitizenProfile(Citizen):
    linked_emails: List[str]
    popups: List[CitizenPopupData]
    total_days: int
    referral_count: int


class CitizenFilter(BaseModel):
    id: Optional[int] = None
    primary_email: Optional[str] = None

    @field_validator('primary_email')
    @classmethod
    def decode_primary_email(cls, value: Optional[str]) -> Optional[str]:
        return unquote(value) if value else None


class PoapClaim(BaseModel):
    attendee_id: int
    attendee_name: str
    attendee_email: Optional[str] = None
    attendee_category: str
    poap_url: str
    poap_name: str
    poap_description: str
    poap_image_url: str
    poap_claimed: bool
    poap_is_active: bool


class CitizenPoapsByPopup(BaseModel):
    popup_id: int
    popup_name: str
    poaps: List[PoapClaim]


class CitizenPoaps(BaseModel):
    emails: List[str]
    results: List[CitizenPoapsByPopup]
