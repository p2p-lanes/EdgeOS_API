import random
import string
from datetime import datetime
from typing import List, Optional, Union

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.applications.crud import application as applications_crud
from app.api.applications.models import Application as ApplicationModel
from app.api.applications.schemas import ApplicationCreate, ApplicationStatus
from app.api.base_crud import CRUDBase
from app.api.citizens.crud import citizen as citizens_crud
from app.api.citizens.schemas import CitizenCreate
from app.api.groups import models, schemas
from app.core.logger import logger
from app.core.security import SYSTEM_TOKEN, TokenData
from app.core.utils import current_time


def generate_random_string(length: int = 4) -> str:
    return ''.join(random.choices(string.ascii_lowercase, k=length))


class CRUDGroup(CRUDBase[models.Group, schemas.GroupBase, schemas.GroupUpdate]):
    def _check_permission(self, db_obj: models.Group, user: TokenData) -> bool:
        """Verifies if user has permission to access this group. Returns True if allowed."""
        if not user:
            return False
        if user == SYSTEM_TOKEN:
            return True

        return any(leader.id == user.citizen_id for leader in db_obj.leaders)

    def find(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[BaseModel] = None,
        user: Optional[TokenData] = None,
        sort_by: str = 'created_at',
        sort_order: str = 'desc',
    ) -> List[models.Group]:
        """Only return groups where the user is a leader"""
        if not user:
            return []

        query = db.query(self.model)
        query = query.join(
            models.GroupLeader, models.GroupLeader.group_id == self.model.id
        ).filter(models.GroupLeader.citizen_id == user.citizen_id)

        query = self._apply_filters(query, filters)

        if not hasattr(self.model, sort_by):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f'Invalid sort field: {sort_by}',
            )

        order_by = getattr(self.model, sort_by)
        if sort_order == 'desc':
            order_by = order_by.desc()

        query = query.order_by(order_by)
        return query.offset(skip).limit(limit).all()

    def update(
        self,
        db: Session,
        id: int,
        obj: schemas.GroupUpdate,
        user: TokenData,
    ) -> models.Group:
        group = self.get(db, id, user)
        if not self._check_permission(group, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='You are not allowed to update this group',
            )
        group.description = obj.description
        group.welcome_message = obj.welcome_message
        db.commit()
        db.refresh(group)
        return group

    def _validate_member_addition(
        self,
        group: models.Group,
        citizen_id: int,
        update_existing: bool = False,
    ) -> None:
        """Validate if a citizen can be added to a group"""
        members_ids = [member.id for member in group.members]
        is_member = citizen_id in members_ids
        if is_member:
            if not update_existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail='Citizen is already a member',
                )
            else:
                return

        # leaders_ids = [leader.id for leader in group.leaders]
        # if citizen_id in leaders_ids:
        #     raise HTTPException(
        #         status_code=status.HTTP_400_BAD_REQUEST,
        #         detail='Citizen is a leader',
        #     )

        if group.max_members is not None and len(group.members) >= group.max_members:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Group is full',
            )

        # if application and application.group_id:
        #     err_msg = (
        #         'Citizen already has an application in this group'
        #         if application.group_id == group.id
        #         else 'Citizen already has an application in another group'
        #     )
        #     raise HTTPException(
        #         status_code=status.HTTP_400_BAD_REQUEST,
        #         detail=err_msg,
        #     )

    def get_by_slug(self, db: Session, slug: str) -> models.Group:
        group = db.query(self.model).filter(self.model.slug == slug).first()
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Group not found',
            )
        return group

    def get_with_members(
        self, db: Session, id: int, user: TokenData
    ) -> schemas.GroupWithMembers:
        group = super().get(db, id, user)
        members = []
        for application in group.applications:
            products = []
            for attendee in application.attendees:
                products.extend(attendee.products)

            group_member = schemas.MemberWithProducts(
                id=application.citizen_id,
                first_name=application.first_name,
                last_name=application.last_name,
                email=application.email,
                telegram=application.telegram,
                organization=application.organization,
                role=application.role,
                gender=application.gender,
                local_resident=application.local_resident,
                products=products,
            )
            d = application.accepted_at or application.submitted_at or datetime.min
            members.append((group_member, d))

        members.sort(key=lambda x: x[1], reverse=True)
        members = [m[0] for m in members]
        return schemas.GroupWithMembers(
            **schemas.Group.model_validate(group).model_dump(),
            members=members,
        )

    def add_member(
        self,
        db: Session,
        group_id: Union[int, str],
        member: schemas.GroupMember,
        user: TokenData,
        update_existing: bool = False,
    ) -> ApplicationModel:
        try:
            group_id = int(group_id)
            group = self.get(db, group_id, user)
        except ValueError:
            group = self.get_by_slug(db, group_id)

        citizen = citizens_crud.get_or_create(
            db,
            CitizenCreate(
                primary_email=member.email,
                first_name=member.first_name,
                last_name=member.last_name,
                gender=member.gender,
                role=member.role,
                telegram=member.telegram,
            ),
        )

        application = citizen.get_application(group.popup_city_id)

        self._validate_member_addition(
            group=group, citizen_id=citizen.id, update_existing=update_existing
        )

        if not application:
            new_application = ApplicationCreate(
                citizen_id=citizen.id,
                popup_city_id=group.popup_city_id,
                group_id=group.id,
                first_name=member.first_name,
                last_name=member.last_name,
                role=member.role,
                organization=member.organization,
                gender=member.gender,
                telegram=member.telegram,
                local_resident=member.local_resident,
            )
            logger.info('Application not found, creating: %s', new_application)
            application = applications_crud.create(db, new_application, SYSTEM_TOKEN)
        else:
            logger.info('Application found, updating: %s', application.id)
            application.group_id = group.id
            application.status = ApplicationStatus.ACCEPTED
            application.first_name = member.first_name
            application.last_name = member.last_name
            application.role = member.role
            application.organization = member.organization
            application.gender = member.gender
            application.telegram = member.telegram
            application.local_resident = member.local_resident
            application.submitted_at = current_time()
            applications_crud.update_citizen_profile(db, application)

        if citizen.id not in [m.id for m in group.members]:
            group.members.append(citizen)
            logger.info('Citizen added to group: %s', citizen.id)

        db.commit()
        db.refresh(group)
        db.refresh(application)
        return application

    def create_member(
        self,
        db: Session,
        group_id: int,
        member: schemas.GroupMember,
        user: TokenData,
        update_existing: bool = False,
    ) -> schemas.MemberWithProducts:
        application = self.add_member(db, group_id, member, user, update_existing)
        return schemas.MemberWithProducts(
            id=application.citizen_id,
            products=application.get_products(),
            first_name=application.first_name,
            last_name=application.last_name,
            email=application.email,
            telegram=application.telegram,
            organization=application.organization,
            role=application.role,
            gender=application.gender,
            local_resident=application.local_resident,
        )

    def create_members_batch(
        self,
        db: Session,
        group_id: int,
        members: List[schemas.GroupMember],
        user: TokenData,
        update_existing: bool = False,
    ) -> List[schemas.MemberBatchResult]:
        """Create multiple members in a group at once, handling partial success"""
        results = []

        for member in members:
            try:
                created_member = self.create_member(
                    db, group_id, member, user, update_existing
                )
                # Convert MemberWithProducts to MemberBatchResult
                result = schemas.MemberBatchResult(
                    **created_member.model_dump(), success=True, err_msg=None
                )
                results.append(result)
                db.commit()
            except HTTPException as e:
                if e.status_code == status.HTTP_403_FORBIDDEN:
                    logger.warning(
                        'User %s does not have permission to add member %s to group %s',
                        user.citizen_id,
                        member.email,
                        group_id,
                    )
                    db.rollback()
                    raise e

                # Create error result for this member
                result = schemas.MemberBatchResult(
                    id=0,  # Use 0 as a placeholder for failed creation
                    products=[],
                    success=False,
                    err_msg=str(e.detail),
                    **member.model_dump(),
                )
                results.append(result)
                db.rollback()  # Rollback only this member's transaction
            except Exception as e:
                db.rollback()  # Rollback only this member's transaction
                logger.error(
                    'Error creating member %s: %s',
                    member.email,
                    str(e),
                    exc_info=True,
                )
                raise e

        return results

    def _validate_member_exists(
        self,
        group: models.Group,
        citizen_id: int,
    ) -> None:
        """Validate that a citizen is a member of the group"""
        if citizen_id not in [m.id for m in group.members]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Member not found in group',
            )

    def update_member(
        self,
        db: Session,
        group_id: int,
        citizen_id: int,
        member: schemas.GroupMember,
        user: TokenData,
    ) -> schemas.MemberWithProducts:
        """Update a member's information in a group"""
        group = self.get(db, group_id, user)

        self._validate_member_exists(group, citizen_id)

        citizen = citizens_crud.get(db, citizen_id, SYSTEM_TOKEN)
        citizen.first_name = member.first_name
        citizen.last_name = member.last_name
        citizen.primary_email = member.email

        application = citizen.get_application(group.popup_city_id)

        if not application:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Application not found',
            )

        application.first_name = member.first_name
        application.last_name = member.last_name
        application.email = member.email
        application.role = member.role
        application.organization = member.organization
        application.gender = member.gender
        application.telegram = member.telegram
        application.local_resident = member.local_resident
        application.submitted_at = current_time()

        db.commit()
        db.refresh(citizen)
        db.refresh(application)

        return schemas.MemberWithProducts(
            id=citizen.id,
            products=application.get_products(),
            first_name=application.first_name,
            last_name=application.last_name,
            email=application.email,
            local_resident=application.local_resident,
        )

    def remove_member(
        self,
        db: Session,
        group_id: int,
        citizen_id: int,
        user: TokenData,
    ):
        group = self.get(db, group_id, user)

        self._validate_member_exists(group, citizen_id)
        citizen = citizens_crud.get(db, citizen_id, SYSTEM_TOKEN)

        application = citizen.get_application(group.popup_city_id)
        if application:
            if application.get_products():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail='Cannot remove member with products',
                )
            if application.created_by_leader:
                applications_crud.delete(db, application.id, user)
            else:
                application.group_id = None
                db.commit()
                db.refresh(application)

        group.members.remove(citizen)
        db.commit()
        db.refresh(group)
        return group

    def set_products(
        self,
        db: Session,
        group_id: int,
        products: List[int],
        user: TokenData,
    ):
        group = self.get(db, group_id, user)
        group.products = products
        db.commit()
        db.refresh(group)
        return group

    def create_ambassador_group(
        self, db: Session, application: ApplicationModel
    ) -> Optional[models.Group]:
        popup_city = application.popup_city
        if popup_city.slug != 'edge-patagonia':
            logger.info('Ambassador group not available for this popup city')
            return None

        existing_group = (
            db.query(self.model)
            .filter(
                self.model.popup_city_id == popup_city.id,
                self.model.ambassador_id == application.citizen_id,
            )
            .first()
        )
        if existing_group:
            logger.info('Ambassador group already exists for %s', application.email)
            return existing_group

        slug = f'{popup_city.prefix}-{generate_random_string(length=4)}'
        while db.query(self.model).filter(self.model.slug == slug).first():
            logger.info('Ambassador group slug already exists: %s', slug)
            slug = f'{popup_city.prefix}-{generate_random_string(length=4)}'

        description = 'You\'re invited to skip the application process and proceed directly to checkout. Provide your information below to secure your ticket(s) to <a href="https://www.edgecity.live/patagonia" target="_blank" style="color: #3366FF;">Edge Patagonia 2025</a>!'
        welcome_message = f'This is a personal invite link from {application.first_name} {application.last_name}.'

        group = self.create(
            db,
            schemas.GroupBase(
                name=f'{application.first_name} {application.last_name} Invite List',
                slug=slug,
                description=description,
                discount_percentage=0,
                popup_city_id=application.popup_city_id,
                max_members=None,
                welcome_message=welcome_message,
                is_ambassador_group=True,
                ambassador_id=application.citizen_id,
                ambassador_email=application.email,
            ),
            user=SYSTEM_TOKEN,
        )
        logger.info('Ambassador group created: %s %s', group.id, group.slug)
        group.leaders.append(application.citizen)
        return group


group = CRUDGroup(models.Group)
