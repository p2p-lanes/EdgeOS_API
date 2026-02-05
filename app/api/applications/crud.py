import csv
import io
import random
import string
from typing import List, Optional, Tuple, Union

from fastapi import BackgroundTasks, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, case, desc, exists, not_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.applications import models, schemas
from app.api.attendees import schemas as attendees_schemas
from app.api.attendees.crud import attendee as attendees_crud
from app.api.attendees.models import Attendee, AttendeeProduct
from app.api.base_crud import CRUDBase
from app.api.citizens.models import Citizen as CitizenModel
from app.api.email_logs.crud import email_log
from app.api.email_logs.schemas import EmailEvent
from app.api.organizations.crud import organization as organization_crud
from app.api.popup_city.models import PopUpCity
from app.api.products.models import Product
from app.core.ai_scoring import review_application
from app.core.logger import logger
from app.core.security import SYSTEM_TOKEN, TokenData
from app.core.utils import current_time


def _generate_attendees_directory_csv(attendees: list[dict]) -> str:
    """Generate CSV content from attendees directory data."""
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(
        [
            'First Name',
            'Last Name',
            'Email',
            'Telegram',
            'Brings Kids',
            'Role',
            'Organization',
            'Participation',
        ]
    )

    for attendee in attendees:
        participation_str = ''
        if attendee['participation'] != '*' and attendee['participation']:
            _products = [str(product.name) for product in attendee['participation']]
            participation_str = ', '.join(_products)

        writer.writerow(
            [
                attendee['first_name'],
                attendee['last_name'],
                attendee['email'],
                attendee['telegram'],
                str(attendee['brings_kids'])
                if attendee['brings_kids'] != '*'
                else attendee['brings_kids'],
                attendee['role'],
                attendee['organization'],
                participation_str,
            ]
        )

    return output.getvalue()


def _requested_a_discount(
    application: Union[
        models.Application, schemas.Application, schemas.InternalApplicationCreate
    ],
    popup_city: PopUpCity,
) -> bool:
    """
    Determines if a discount has been requested based on the application state.
    Works with both database models (`models.Application`) and schemas (`schemas.Application`).
    """
    if popup_city.requires_approval:
        return application.scholarship_request or False

    return (application.is_renter or False) or (
        application.scholarship_request or False
    )


def calculate_status(
    application: Union[
        models.Application, schemas.Application, schemas.InternalApplicationCreate
    ],
    popup_city: PopUpCity,
    reviews_status: Optional[schemas.ApplicationStatus] = None,
) -> Tuple[schemas.ApplicationStatus, bool]:
    submitted_at = application.submitted_at
    requested_a_discount = _requested_a_discount(application, popup_city)

    if reviews_status in [
        schemas.ApplicationStatus.REJECTED,
        schemas.ApplicationStatus.WITHDRAWN,
    ]:
        return reviews_status, requested_a_discount

    discount_assigned = getattr(application, 'discount_assigned', None)
    missing_discount = requested_a_discount and discount_assigned is None
    if not popup_city.requires_approval and not requested_a_discount:
        return schemas.ApplicationStatus.ACCEPTED, requested_a_discount

    if not reviews_status or missing_discount:
        return (
            schemas.ApplicationStatus.IN_REVIEW
            if submitted_at
            else schemas.ApplicationStatus.DRAFT
        ), requested_a_discount

    return reviews_status, requested_a_discount


def _send_application_received_mail(application: models.Application):
    email_log.send_mail(
        receiver_mail=application.email,
        event=EmailEvent.APPLICATION_RECEIVED.value,
        popup_city=application.popup_city,
        entity_type='application',
        entity_id=application.id,
    )


def _run_ai_review_background(application_id: int):
    """Background task to run AI review and update the application."""
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        application = db.query(models.Application).get(application_id)
        if application:
            application.ai_review = review_application(application)
            db.commit()


class CRUDApplication(
    CRUDBase[models.Application, schemas.ApplicationCreate, schemas.ApplicationUpdate]
):
    def update_citizen_profile(self, db: Session, application: models.Application):
        citizen = application.citizen

        citizen.first_name = application.first_name
        citizen.last_name = application.last_name
        citizen.telegram = application.telegram
        citizen.role = application.role
        citizen.residence = application.residence
        citizen.social_media = application.social_media
        citizen.age = application.age
        citizen.gender = application.gender
        citizen.eth_address = application.eth_address
        citizen.referral = application.referral

        if application.organization:
            org = organization_crud.get_or_create(db, application.organization)
            application.organization_id = org.id
            if org not in citizen.organizations:
                citizen.organizations.append(org)

        db.commit()
        db.refresh(citizen)

        return citizen

    def _check_permission(self, db_obj: models.Application, user: TokenData) -> bool:
        user_id = user.citizen_id
        is_leader = db_obj.group.is_leader(user_id) if db_obj.group else False
        return user == SYSTEM_TOKEN or db_obj.citizen_id == user_id or is_leader

    def create(
        self,
        db: Session,
        obj: schemas.ApplicationCreate,
        user: Optional[TokenData] = None,
    ) -> models.Application:
        from app.api.groups.crud import group as groups_crud

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail='Authentication required to create applications',
            )

        logger.info('Creating application: %s', obj)
        citizen_id = obj.citizen_id
        citizen = db.query(CitizenModel).filter(CitizenModel.id == citizen_id).first()
        if not citizen:
            raise HTTPException(status_code=404, detail='Citizen not found')

        group = None
        created_by_leader = False
        initial_status: Optional[schemas.ApplicationStatus] = None
        if obj.group_id:
            group = groups_crud.get(db, obj.group_id, user)
            created_by_leader = group.is_leader(user.citizen_id)
            if user != SYSTEM_TOKEN and not created_by_leader:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail='Not authorized to create application for another citizen',
                )
            initial_status = schemas.ApplicationStatus.ACCEPTED
        elif obj.citizen_id != user.citizen_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='Not authorized to create application for another citizen',
            )

        logger.info('Citizen found: %s %s', citizen.id, citizen.primary_email)
        email = citizen.primary_email

        # Use initial_status if set (for group applications), otherwise use obj.status
        effective_status = initial_status or obj.status
        submitted_at = None
        if effective_status in [
            schemas.ApplicationStatus.IN_REVIEW,
            schemas.ApplicationStatus.ACCEPTED,
        ]:
            submitted_at = current_time()

        obj_data = obj.model_dump()
        if initial_status is not None:
            obj_data['status'] = initial_status
        internal_obj = schemas.InternalApplicationCreate(
            **obj_data,
            email=email,
            submitted_at=submitted_at,
            created_by_leader=created_by_leader,
        )

        if internal_obj.status != schemas.ApplicationStatus.DRAFT and not group:
            popup_city_id = internal_obj.popup_city_id
            popup = db.query(PopUpCity).filter(PopUpCity.id == popup_city_id).first()
            if not popup:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail='Popup city not found',
                )

            internal_obj.status, internal_obj.requested_discount = calculate_status(
                internal_obj, popup_city=popup
            )

        application = super().create(db, internal_obj)  # type: ignore[arg-type]

        attendee = attendees_schemas.AttendeeCreate(
            name=f'{internal_obj.first_name} {internal_obj.last_name}'.strip(),
            category='main',
            email=email,
            group_id=group.id if group else None,
        )
        self.create_attendee(db, application.id, attendee, user)

        if application.status == schemas.ApplicationStatus.IN_REVIEW:
            _send_application_received_mail(application)
            # Review the application using AI
            application.ai_review = review_application(application)
            db.add(application)
            db.commit()
            db.refresh(application)

        self.update_citizen_profile(db, application)
        return application

    def update(
        self,
        db: Session,
        id: int,
        obj: schemas.ApplicationUpdate,
        user: TokenData,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> models.Application:
        application = super().update(db, id, obj, user)
        popup_city = application.popup_city

        if obj.status == schemas.ApplicationStatus.IN_REVIEW:
            if application.submitted_at is None:
                application.submitted_at = current_time()

            application.clean_reviews()
            application.status, application.requested_discount = calculate_status(
                application, popup_city=popup_city
            )
            if application.status == schemas.ApplicationStatus.IN_REVIEW:
                _send_application_received_mail(application)
                # Schedule AI review in background if background_tasks provided
                if background_tasks:
                    background_tasks.add_task(_run_ai_review_background, application.id)
        else:
            requested_discount = _requested_a_discount(application, popup_city)
            application.requested_discount = requested_discount

        self.update_citizen_profile(db, application)

        db.add(application)
        db.commit()
        db.refresh(application)
        return application

    def find(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[BaseModel] = None,
        user: Optional[TokenData] = None,
        sort_by: str = 'created_at',
        sort_order: str = 'desc',
    ) -> List[models.Application]:
        if user:
            if filters is None or not isinstance(filters, schemas.ApplicationFilter):
                filters = schemas.ApplicationFilter()
            filters.citizen_id = user.citizen_id
        return super().find(db, skip, limit, filters, user, sort_by, sort_order)

    def create_attendee(
        self,
        db: Session,
        application_id: int,
        attendee: attendees_schemas.AttendeeCreate,
        user: TokenData,
    ) -> models.Application:
        application = self.get(db, application_id, user)
        existing_categories = {a.category for a in application.attendees}
        if (
            attendee.category in ['main', 'spouse']
            and attendee.category in existing_categories
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f'Attendee {attendee.category} already exists',
            )
        existing_emails = [a.email for a in application.attendees if a.email]
        if attendee.email and attendee.email in existing_emails:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f'Attendee {attendee.email} already exists',
            )

        code = ''.join(random.choices(string.ascii_uppercase, k=4))
        check_in_code = application.popup_city.prefix + code
        attendee = attendees_schemas.InternalAttendeeCreate(
            **attendee.model_dump(),
            application_id=application_id,
            check_in_code=check_in_code,
        )
        attendee = attendees_crud.create(db, attendee, user)
        return application

    def update_attendee(
        self,
        db: Session,
        application_id: int,
        attendee_id: int,
        attendee: attendees_schemas.AttendeeUpdate,
        user: TokenData,
    ) -> models.Application:
        application = self.get(db, application_id, user)
        existing_emails = [
            a.email for a in application.attendees if a.email and a.id != attendee_id
        ]
        if attendee.email and attendee.email in existing_emails:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f'Attendee {attendee.email} already exists',
            )
        _ = attendees_crud.update(db, attendee_id, attendee, user)
        return application

    def delete_attendee(
        self,
        db: Session,
        application_id: int,
        attendee_id: int,
        user: TokenData,
    ) -> models.Application:
        application = self.get(db, application_id, user)
        if attendee_id not in [a.id for a in application.attendees]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Attendee not found',
            )
        attendee = attendees_crud.get(db, attendee_id, user)
        if attendee.category == 'main':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Cannot delete main attendee',
            )
        attendees_crud.delete(db, attendee_id, user)
        return application

    def get_attendees_directory(
        self,
        db: Session,
        popup_city_id: int,
        filters: Optional[schemas.AttendeesDirectoryFilter],
        skip: Optional[int],
        limit: Optional[int],
        user: TokenData,
    ) -> Tuple[List[dict], int]:
        # Create the ordering expressions
        info_not_shared_order = case(
            (models.Application._info_not_shared.is_(None), 0),
            (models.Application._info_not_shared.like('%brings_kids%'), 1),
            else_=0,
        ).label('info_not_shared_order')

        # Handle nulls explicitly in the brings_kids ordering
        brings_kids_order = case(
            (models.Application.brings_kids.is_(None), 0),
            (models.Application.brings_kids.is_(True), 2),
            (models.Application.brings_kids.is_(False), 1),
        ).label('brings_kids_order')

        # Query applications with main attendees that have products
        base_query = (
            db.query(
                models.Application,
                info_not_shared_order,
                brings_kids_order,
                CitizenModel.picture_url,
                CitizenModel.first_name,
                CitizenModel.last_name,
            )
            .join(models.Application.attendees.and_(Attendee.category == 'main'))
            .join(CitizenModel, CitizenModel.id == models.Application.citizen_id)
            .options(selectinload(models.Application.attendees))
            .filter(
                models.Application.popup_city_id == popup_city_id,
                # Check if the attendee has any products using EXISTS
                exists()
                .where(AttendeeProduct.attendee_id == Attendee.id)
                .correlate(Attendee),
            )
            .order_by(
                info_not_shared_order,
                desc(brings_kids_order),
                models.Application.created_at,
                models.Application.id,
            )
        )

        if filters:
            ins = models.Application._info_not_shared
            if filters.q:
                search_term = f'%{filters.q}%'
                base_query = base_query.filter(
                    or_(
                        and_(
                            or_(ins.is_(None), not_(ins.ilike('%first_name%'))),
                            models.Application.first_name.ilike(search_term),
                        ),
                        and_(
                            or_(ins.is_(None), not_(ins.ilike('%last_name%'))),
                            models.Application.last_name.ilike(search_term),
                        ),
                        and_(
                            or_(ins.is_(None), not_(ins.ilike('%email%'))),
                            models.Application.email.ilike(search_term),
                        ),
                        and_(
                            or_(ins.is_(None), not_(ins.ilike('%telegram%'))),
                            models.Application.telegram.ilike(search_term),
                        ),
                        and_(
                            or_(ins.is_(None), not_(ins.ilike('%role%'))),
                            models.Application.role.ilike(search_term),
                        ),
                        and_(
                            or_(ins.is_(None), not_(ins.ilike('%organization%'))),
                            models.Application.organization.ilike(search_term),
                        ),
                    )
                )
            if filters.email is not None:
                base_query = base_query.filter(
                    and_(
                        or_(ins.is_(None), not_(ins.ilike('%email%'))),
                        models.Application.email.ilike(filters.email),
                    )
                )
            if filters.brings_kids is not None:
                base_query = base_query.filter(
                    and_(
                        or_(ins.is_(None), not_(ins.ilike('%brings_kids%'))),
                        models.Application.brings_kids.is_(filters.brings_kids),
                    )
                )
            if filters.participation:
                products_conditions = [Product.slug.like('%month%')]
                for week_num in filters.participation:
                    products_conditions.append(Product.slug.like(f'week{week_num}%'))

                base_query = base_query.filter(
                    and_(
                        or_(ins.is_(None), not_(ins.ilike('%participation%'))),
                        exists()
                        .where(AttendeeProduct.attendee_id == Attendee.id)
                        .where(AttendeeProduct.product_id == Product.id)
                        .where(or_(*products_conditions)),
                    )
                )

        total = base_query.count()
        if skip is not None:
            base_query = base_query.offset(skip)
        if limit is not None:
            base_query = base_query.limit(limit)
        query_results = base_query.all()

        attendees = []
        for result in query_results:
            # Unpack the query results for clarity
            (
                application,
                info_not_shared_order,
                brings_kids_order,
                picture_url,
                first_name,
                last_name,
            ) = result
            main_attendee = application.get_main_attendee()

            check_in, check_out = None, None
            for p in main_attendee.products:
                if not check_in or (p.start_date and p.start_date < check_in):
                    check_in = p.start_date
                if not check_out or (p.end_date and p.end_date > check_out):
                    check_out = p.end_date

            associated_attendees = [
                {
                    'name': attendee.name,
                    'category': attendee.category,
                    'gender': attendee.gender,
                    'email': attendee.email,
                }
                for attendee in application.attendees
                if attendee.category != 'main'
            ]

            a = {
                'id': application.id,
                'citizen_id': application.citizen_id,
                'first_name': first_name,
                'last_name': last_name,
                'email': application.email,
                'telegram': application.telegram,
                'brings_kids': application.brings_kids,
                'role': application.role,
                'organization': application.organization,
                'personal_goals': application.personal_goals,
                'residence': application.residence,
                'age': application.age,
                'gender': application.gender,
                'social_media': application.social_media,
                'builder_boolean': application.builder_boolean,
                'builder_description': application.builder_description,
                'residencies_interested_in': application.residencies_interested_in,
                'residencies_text': application.residencies_text,
                'associated_attendees': associated_attendees,
                'participation': main_attendee.products,
                'check_in': check_in,
                'check_out': check_out,
                'picture_url': picture_url,
            }

            if application.info_not_shared:
                for f in application.info_not_shared:
                    a[f] = schemas.HIDDEN_VALUE

            attendees.append(a)

        return attendees, total

    def get_attendees_directory_csv(
        self,
        db: Session,
        popup_city_id: int,
        filters: Optional[schemas.AttendeesDirectoryFilter],
        user: TokenData,
    ) -> str:
        attendees, _ = self.get_attendees_directory(
            db,
            popup_city_id,
            filters,
            skip=None,
            limit=None,
            user=user,
        )
        return _generate_attendees_directory_csv(attendees)

    def delete(self, db: Session, id: int, user: TokenData) -> models.Application:
        """Delete a record."""
        try:
            application = self.get(db, id, user)  # This will raise 404 if not found

            # Check if any attendees have associated payments
            for attendee in application.attendees:
                if attendee.payment_products:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail='Cannot delete application because it has attendees with payment history',
                    )

            # First delete all AttendeeProduct records
            for attendee in application.attendees:
                db.query(AttendeeProduct).filter(
                    AttendeeProduct.attendee_id == attendee.id
                ).delete(synchronize_session=False)

            db.delete(application)
            db.commit()
            return application

        except IntegrityError as e:
            db.rollback()
            logger.error('IntegrityError in delete: %s', e)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail='Cannot delete this application because it is referenced by other records',
            )

    def get_distinct_emails_no_products(
        self, db: Session, popup_city_id: int, exclude_emails: List[str] = []
    ) -> list[models.Application]:
        rows = (
            db.query(models.Application)
            .join(Attendee, Attendee.application_id == models.Application.id)
            .outerjoin(AttendeeProduct, AttendeeProduct.attendee_id == Attendee.id)
            .filter(
                models.Application.email.notin_(exclude_emails),
                models.Application.popup_city_id == popup_city_id,
                models.Application.status == schemas.ApplicationStatus.ACCEPTED.value,
                AttendeeProduct.attendee_id.is_(None),
            )
            .distinct()
            .all()
        )
        return rows


application = CRUDApplication(models.Application)
