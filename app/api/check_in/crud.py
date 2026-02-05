from typing import List

from sqlalchemy.orm import Session

from app.api.applications.crud import application as application_crud
from app.api.attendees.crud import attendee as attendee_crud
from app.api.attendees.models import AttendeeProduct
from app.api.base_crud import CRUDBase
from app.core.logger import logger
from app.core.security import SYSTEM_TOKEN
from app.core.utils import current_time

from . import models, schemas


class CRUDCheckIn(
    CRUDBase[
        models.CheckIn, schemas.InternalCheckInCreate, schemas.InternalCheckInCreate
    ]
):
    def _validate_attendee(self, db: Session, attendee_id: int, code: str) -> bool:
        attendee = attendee_crud.get(db, attendee_id, user=SYSTEM_TOKEN)
        return bool(attendee.products) and attendee.check_in_code == code

    def get_check_in_by_attendee_id(
        self,
        db: Session,
        attendee_id: int,
    ) -> models.CheckIn:
        return (
            db.query(models.CheckIn)
            .filter(models.CheckIn.attendee_id == attendee_id)
            .first()
        )

    def get_products_names(self, attendee_products: List[AttendeeProduct]) -> str:
        def _get_product_name(product: AttendeeProduct) -> str:
            if product.quantity == 1:
                return product.product.name
            return f'{product.product.name} x{product.quantity}'

        return ', '.join([_get_product_name(p) for p in attendee_products])

    def new_qr_check_in(
        self,
        db: Session,
        code: str,
    ) -> schemas.CheckInResponse:
        if code.startswith('ECP25'):
            code = code.replace('ECP25', 'EP25')
        if code.startswith('EE25'):
            code = code.replace('EE25', 'EP25')

        attendee = attendee_crud.get_by_code(db, code)
        logger.info('Attendee with code %s found: %s', code, attendee is not None)
        if not attendee or not attendee.products:
            logger.error('Attendee with code %s not found or has no products', code)
            return schemas.CheckInResponse(success=False, first_check_in=False)

        products = self.get_products_names(attendee.attendee_products)
        name = f'{attendee.name} ({products})'
        existing_check_in = self.get_check_in_by_attendee_id(db, attendee.id)
        if existing_check_in:
            logger.info('Existing check-in for attendee %s', attendee.id)
            first_check_in = not existing_check_in.qr_check_in
            existing_check_in.code = code
            existing_check_in.qr_check_in = True
            if not existing_check_in.qr_scan_timestamp:
                existing_check_in.qr_scan_timestamp = current_time()

            db.commit()

            return schemas.CheckInResponse(
                success=True,
                first_check_in=first_check_in,
                name=name,
                scan_time=existing_check_in.qr_scan_timestamp,
            )

        logger.info('Creating new check-in for attendee %s', attendee.id)
        new_check_in = schemas.InternalCheckInCreate(
            code=code,
            attendee_id=attendee.id,
            qr_check_in=True,
            qr_scan_timestamp=current_time(),
        )
        super().create(db, new_check_in, SYSTEM_TOKEN)
        return schemas.CheckInResponse(
            success=True,
            first_check_in=True,
            name=name,
            scan_time=new_check_in.qr_scan_timestamp,
        )

    def new_virtual_check_in(
        self,
        db: Session,
        obj: schemas.NewVirtualCheckIn,
    ) -> schemas.CheckInResponse:
        logger.info('New virtual check-in for application %s', obj.application_id)
        application = application_crud.get(db, obj.application_id, user=SYSTEM_TOKEN)
        if not application:
            logger.error('Application %s not found', obj.application_id)
            return schemas.CheckInResponse(success=False, first_check_in=False)

        main_attendee = next(
            attendee
            for attendee in application.attendees
            if attendee.category == 'main'
        )
        if main_attendee.check_in_code != obj.code:
            logger.error('Invalid code for application %s', obj.application_id)
            return schemas.CheckInResponse(success=False, first_check_in=False)

        for attendee in application.attendees:
            if not attendee.products:
                continue

            existing_check_in = self.get_check_in_by_attendee_id(db, attendee.id)
            if existing_check_in:
                logger.info('Existing check-in for attendee %s', attendee.id)
                existing_check_in.code = obj.code
                existing_check_in.virtual_check_in = True
                if not existing_check_in.virtual_check_in_timestamp:
                    existing_check_in.virtual_check_in_timestamp = current_time()

                existing_check_in.arrival_date = obj.arrival_date
                existing_check_in.departure_date = obj.departure_date
            else:
                logger.info('Creating new check-in for attendee %s', attendee.id)
                new_check_in = schemas.InternalCheckInCreate(
                    code=obj.code,
                    attendee_id=attendee.id,
                    arrival_date=obj.arrival_date,
                    departure_date=obj.departure_date,
                    virtual_check_in=True,
                    virtual_check_in_timestamp=current_time(),
                )
                super().create(db, new_check_in, SYSTEM_TOKEN)

        return schemas.CheckInResponse(success=True, first_check_in=True)


check_in = CRUDCheckIn(models.CheckIn)
