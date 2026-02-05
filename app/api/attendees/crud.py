from typing import List, Optional

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.base_crud import CRUDBase
from app.core.security import SYSTEM_TOKEN, TokenData

from . import models, schemas


class CRUDAttendees(
    CRUDBase[models.Attendee, schemas.InternalAttendeeCreate, schemas.AttendeeUpdate]
):
    def _check_permission(self, db_obj: models.Attendee, user: TokenData) -> bool:
        return db_obj.application.citizen_id == user.citizen_id or user == SYSTEM_TOKEN

    def get_by_email(self, db: Session, email: str) -> List[models.Attendee]:
        return db.query(self.model).filter(self.model.email == email).all()

    def get_by_code(self, db: Session, code: str) -> models.Attendee:
        """Get a single record by code with permission check."""
        return db.query(self.model).filter(self.model.check_in_code == code).first()

    def find(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[BaseModel] = None,
        user: Optional[TokenData] = None,
        sort_by: str = 'created_at',
        sort_order: str = 'desc',
    ) -> List[models.Attendee]:
        if user:
            if filters is None or not isinstance(filters, schemas.AttendeeFilter):
                filters = schemas.AttendeeFilter()
            filters.citizen_id = user.citizen_id
        return super().find(db, skip, limit, filters, user, sort_by, sort_order)

    def update(
        self,
        db: Session,
        id: int,
        obj: schemas.AttendeeUpdate,
        user: TokenData,
    ) -> models.Attendee:
        attendee = self.get(db, id, user)
        if attendee.products:
            # if attendee has products, we cannot change the category
            obj.category = attendee.category

        return super().update(db, id, obj, user)

    def delete(self, db: Session, id: int, user: TokenData) -> models.Attendee:
        """Delete an attendee and its related payment products."""
        try:
            attendee = self.get(db, id, user)  # This will raise 404 if not found

            if attendee.products:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail='Attendee has products',
                )

            if attendee.payment_products:
                for payment_product in attendee.payment_products:
                    db.delete(payment_product)

            db.delete(attendee)
            db.commit()
            return attendee
        except Exception as e:
            db.rollback()
            raise e


class CRUDTicketApiKey(
    CRUDBase[
        models.AttendeeTicketApiKey,
        schemas.TicketApiKeyCreate,
        schemas.TicketApiKeyCreate,
    ]
):
    """CRUD helpers for AttendeeTicketApiKey model"""

    def get_by_key(
        self, db: Session, key: str
    ) -> Optional[models.AttendeeTicketApiKey]:
        return db.query(self.model).filter(self.model.key == key).first()

    def get_by_email(self, db: Session, email: str):
        return db.query(self.model).filter(self.model.email == email).all()


attendee = CRUDAttendees(models.Attendee)
ticket_api_key_crud = CRUDTicketApiKey(models.AttendeeTicketApiKey)
