from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Union

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

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

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    first_name: Mapped[str] = mapped_column(index=True)
    last_name: Mapped[str] = mapped_column(index=True)
    email: Mapped[str] = mapped_column(index=True)
    telegram: Mapped[str | None]
    organization: Mapped[str | None]
    role: Mapped[str | None]
    gender: Mapped[str | None]
    age: Mapped[str | None]
    social_media: Mapped[str | None]
    residence: Mapped[str | None]
    local_resident: Mapped[bool | None]
    eth_address: Mapped[str | None]
    duration: Mapped[str | None]
    video_url: Mapped[str | None]
    payment_capacity: Mapped[str | None]
    github_profile: Mapped[str | None]
    minting_link: Mapped[str | None]

    area_of_expertise: Mapped[str | None]
    preferred_dates: Mapped[str | None]
    hackathon_interest: Mapped[bool | None]
    host_session: Mapped[str | None]
    personal_goals: Mapped[str | None]
    referral: Mapped[str | None]
    _info_not_shared: Mapped[str | None] = mapped_column('info_not_shared', String)
    investor: Mapped[bool | None]

    # Family information
    brings_spouse: Mapped[bool | None]
    spouse_info: Mapped[str | None]
    spouse_email: Mapped[str | None]
    brings_kids: Mapped[bool | None]
    kids_info: Mapped[str | None]
    interested_in_child_led_projects: Mapped[bool | None]

    # Renter information
    is_renter: Mapped[bool] = mapped_column(default=False)
    booking_confirmation: Mapped[str | None]

    # Builder information
    builder_boolean: Mapped[bool] = mapped_column(default=False)
    builder_description: Mapped[str | None]

    # Scholarship information
    scholarship_request: Mapped[bool] = mapped_column(default=False)
    scholarship_details: Mapped[str | None]
    scholarship_video_url: Mapped[str | None]

    total_days: Mapped[int | None]

    _residencies_interested_in: Mapped[str | None] = mapped_column(
        'residencies_interested_in', String
    )
    residencies_text: Mapped[str | None]

    send_note_to_applicant: Mapped[str | None]

    timour_review: Mapped[str | None]
    janine_review: Mapped[str | None]
    tela_review: Mapped[str | None]
    steph_review: Mapped[str | None]
    devon_review: Mapped[str | None]
    lina_review: Mapped[str | None]

    auto_approved: Mapped[bool] = mapped_column(default=False)
    not_attending: Mapped[bool] = mapped_column(default=False)

    ai_review: Mapped[str | None]

    credit: Mapped[float] = mapped_column(default=0)

    submitted_at: Mapped[datetime | None]
    accepted_at: Mapped[datetime | None]

    requested_discount: Mapped[bool] = mapped_column(default=False)
    _status: Mapped[str | None] = mapped_column('status', String)
    _discount_assigned: Mapped[str | None] = mapped_column('discount_assigned', String)

    payments: Mapped[List['Payment']] = relationship(
        'Payment', back_populates='application'
    )
    attendees: Mapped[List['Attendee']] = relationship(
        'Attendee', back_populates='application', cascade='all, delete-orphan'
    )

    citizen_id: Mapped[int] = mapped_column(ForeignKey('humans.id'))
    citizen: Mapped['Citizen'] = relationship(
        'Citizen', back_populates='applications', lazy='joined'
    )
    popup_city_id: Mapped[int] = mapped_column(ForeignKey('popups.id'))
    popup_city: Mapped['PopUpCity'] = relationship('PopUpCity', lazy='joined')

    organization_id: Mapped[int | None] = mapped_column(ForeignKey('organizations.id'))
    organization_rel: Mapped[Optional['Organization']] = relationship(
        'Organization', lazy='joined'
    )

    group_id: Mapped[int | None] = mapped_column(ForeignKey('groups.id'))
    group = None

    created_by_leader: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
    updated_at: Mapped[datetime | None] = mapped_column(
        default=current_time, onupdate=current_time
    )
    created_by: Mapped[str | None]
    updated_by: Mapped[str | None]

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

    def get_main_attendee(self) -> Optional['Attendee']:
        for attendee in self.attendees:
            if attendee.category == 'main':
                return attendee
        return None

    @property
    def red_flag(self) -> bool:
        return bool(self.citizen.red_flag) if self.citizen else False


def setup_relationships():
    if not hasattr(Application, 'group') or Application.group is None:
        Application.group = relationship('Group', lazy='joined')
