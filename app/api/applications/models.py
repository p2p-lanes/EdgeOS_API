from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Union

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, relationship, synonym

from app.api.applications.schemas import ApplicationStatus, TicketCategory
from app.core.database import Base

if TYPE_CHECKING:
    from app.api.applications.attendees.models import Attendee
    from app.api.citizens.models import Citizen
    from app.api.payments.models import Payment


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

    # Builder information
    builder_boolean = Column(Boolean)
    builder_description = Column(String)

    # Scholarship information
    scholarship_request = Column(Boolean)
    scholarship_details = Column(String)
    scholarship_video_url = Column(String)

    _sent_mails = Column('sent_mails', String, nullable=False, default='')

    _status = Column('status', String)
    ticket_category = Column(String)  # standard, discounted
    _discount_assigned = Column('discount_assigned', String)

    payments: Mapped[List['Payment']] = relationship(
        'Payment', back_populates='application'
    )
    attendees: Mapped[List['Attendee']] = relationship(
        'Attendee', back_populates='application'
    )

    citizen_id = Column(Integer, ForeignKey('citizens.id'), nullable=False)
    citizen: Mapped['Citizen'] = relationship(
        'Citizen', back_populates='applications', lazy='joined'
    )
    popup_city_id = Column(Integer, ForeignKey('popups.id'), nullable=False)
    popup_city = relationship('PopUpCity', lazy='noload')

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String)
    updated_by = Column(String)

    __mapper_args__ = {'exclude_properties': ['citizen', 'popup_city']}

    @property
    def sent_mails(self) -> list[str]:
        if not self._sent_mails:
            return []
        return [i.strip() for i in self._sent_mails.split(',') if i.strip()]

    @sent_mails.setter
    def sent_mails(self, value: Optional[Union[str, list[str]]]) -> None:
        self._sent_mails = ','.join(value) if isinstance(value, list) else value

    @property
    def info_not_shared(self) -> Optional[list[str]]:
        if not self._info_not_shared:
            return None
        return [i.strip() for i in self._info_not_shared.split(',') if i.strip()]

    @info_not_shared.setter
    def info_not_shared(self, value: Optional[Union[str, list[str]]]) -> None:
        self._info_not_shared = ','.join(value) if isinstance(value, list) else value

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

        if not self.ticket_category:
            return ApplicationStatus.IN_REVIEW.value

        if (
            self.ticket_category == TicketCategory.DISCOUNTED.value
            and not self.discount_assigned
        ):
            return ApplicationStatus.IN_REVIEW.value

        return ApplicationStatus.ACCEPTED.value

    def set_status(self, value: Optional[str]) -> None:
        """Set the raw status value"""
        self._status = value

    status = synonym('_status', descriptor=property(get_status, set_status))
