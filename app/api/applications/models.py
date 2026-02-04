from typing import TYPE_CHECKING, List, Optional, Union

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, relationship, synonym

from app.api.applications.schemas import ApplicationStatus
from app.core.database import Base
from app.core.utils import current_time

if TYPE_CHECKING:
    from app.api.attendees.models import Attendee
    from app.api.citizens.models import Citizen
    from app.api.organizations.models import Organization
    from app.api.payments.models import Payment
    from app.api.popup_city.models import PopUpCity
    from app.api.products.models import Product


class Application(Base):
    __tablename__ = 'applications'

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
        unique=True,
        index=True,
    )
    first_name = Column(String, index=True, nullable=False)
    last_name = Column(String, index=True, nullable=False)
    email = Column(String, index=True, nullable=False)
    telegram = Column(String)
    organization = Column(String)
    role = Column(String)
    gender = Column(String, nullable=True)
    age = Column(String, nullable=True)
    social_media = Column(String)
    residence = Column(String)
    local_resident = Column(Boolean)
    eth_address = Column(String)
    duration = Column(String)
    video_url = Column(String)
    payment_capacity = Column(String)
    github_profile = Column(String)
    minting_link = Column(String)

    area_of_expertise = Column(String)
    preferred_dates = Column(String)
    hackathon_interest = Column(Boolean)
    host_session = Column(String)
    personal_goals = Column(String)
    referral = Column(String)
    _info_not_shared = Column('info_not_shared', String, nullable=True)
    investor = Column(Boolean)

    # Family information
    brings_spouse = Column(Boolean)
    spouse_info = Column(String)
    spouse_email = Column(String)
    brings_kids = Column(Boolean)
    kids_info = Column(String)

    # Renter information
    is_renter = Column(Boolean, nullable=False, default=False)
    booking_confirmation = Column(String)

    # Builder information
    builder_boolean = Column(Boolean, nullable=False, default=False)
    builder_description = Column(String)

    # Scholarship information
    scholarship_request = Column(Boolean, nullable=False, default=False)
    scholarship_details = Column(String)
    scholarship_video_url = Column(String)

    total_days = Column(Integer, nullable=True)

    _residencies_interested_in = Column('residencies_interested_in', String)
    residencies_text = Column(String)

    send_note_to_applicant = Column(String)

    timour_review = Column(String)
    janine_review = Column(String)
    tela_review = Column(String)
    steph_review = Column(String)
    devon_review = Column(String)
    lina_review = Column(String)

    auto_approved = Column(Boolean, nullable=False, default=False)
    not_attending = Column(Boolean, nullable=False, default=False)

    ai_review = Column(String, nullable=True)

    credit = Column(Float, default=0, nullable=False)

    submitted_at = Column(DateTime, nullable=True)
    accepted_at = Column(DateTime, nullable=True)

    requested_discount = Column(Boolean, nullable=False, default=False)
    _status = Column('status', String)
    _discount_assigned = Column('discount_assigned', String)

    payments: Mapped[List['Payment']] = relationship(
        'Payment', back_populates='application'
    )
    attendees: Mapped[List['Attendee']] = relationship(
        'Attendee', back_populates='application', cascade='all, delete-orphan'
    )

    citizen_id = Column(Integer, ForeignKey('humans.id'), nullable=False)
    citizen: Mapped['Citizen'] = relationship(
        'Citizen', back_populates='applications', lazy='joined'
    )
    popup_city_id = Column(Integer, ForeignKey('popups.id'), nullable=False)
    popup_city: Mapped['PopUpCity'] = relationship('PopUpCity', lazy='joined')

    organization_id = Column(Integer, ForeignKey('organizations.id'), nullable=True)
    organization_rel: Mapped[Optional['Organization']] = relationship(
        'Organization', lazy='joined'
    )

    group_id = Column(Integer, ForeignKey('groups.id'), nullable=True)
    group = None

    created_by_leader = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=current_time)
    updated_at = Column(DateTime, default=current_time, onupdate=current_time)
    created_by = Column(String)
    updated_by = Column(String)

    __mapper_args__ = {'exclude_properties': ['citizen', 'popup_city']}

    __table_args__ = (
        UniqueConstraint('citizen_id', 'popup_city_id', name='uix_citizen_popup'),
    )

    @property
    def info_not_shared(self) -> Optional[list[str]]:
        if not self._info_not_shared:
            return None
        return [i.strip() for i in self._info_not_shared.split(',') if i.strip()]

    @info_not_shared.setter
    def info_not_shared(self, value: Optional[Union[str, list[str]]]) -> None:
        self._info_not_shared = ','.join(value) if isinstance(value, list) else value

    @property
    def residencies_interested_in(self) -> Optional[list[str]]:
        if not self._residencies_interested_in:
            return []
        return [
            i.strip() for i in self._residencies_interested_in.split(',') if i.strip()
        ]

    @residencies_interested_in.setter
    def residencies_interested_in(self, value: Optional[Union[str, list[str]]]) -> None:
        self._residencies_interested_in = (
            ','.join(value) if isinstance(value, list) else value
        )

    @property
    def discount_assigned(self) -> Optional[int]:
        if not self._discount_assigned:
            return None
        return int(self._discount_assigned)

    @discount_assigned.setter
    def discount_assigned(self, value: Optional[int]) -> None:
        self._discount_assigned = str(value) if value is not None else None

    def get_status(self) -> Optional[str]:
        """Compute the effective status based on validation rules"""
        if not self._status or self._status != ApplicationStatus.ACCEPTED.value:
            return self._status

        if self.group_id is not None:
            return ApplicationStatus.ACCEPTED.value

        if self.requested_discount and self.discount_assigned is None:
            return ApplicationStatus.IN_REVIEW.value

        return ApplicationStatus.ACCEPTED.value

    def set_status(self, value: Optional[str]) -> None:
        """Set the raw status value"""
        self._status = value

    status = synonym('_status', descriptor=property(get_status, set_status))

    def clean_reviews(self) -> None:
        self.timour_review = None
        self.janine_review = None
        self.tela_review = None
        self.steph_review = None
        self.devon_review = None
        self.lina_review = None

    def get_products(self) -> List['Product']:
        return [product for attendee in self.attendees for product in attendee.products]

    def get_main_attendee(self) -> 'Attendee':
        for attendee in self.attendees:
            if attendee.category == 'main':
                return attendee

    @property
    def red_flag(self) -> bool:
        return self.citizen.red_flag


def setup_relationships():
    from app.api.groups.models import Group

    if not hasattr(Application, 'group') or Application.group is None:
        Application.group = relationship('Group', lazy='joined')
