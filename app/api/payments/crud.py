from typing import List, Optional

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Query, Session

from app.api.applications.models import Application
from app.api.attendees.models import Attendee, AttendeeProduct
from app.api.base_crud import CRUDBase
from app.api.coupon_codes.crud import coupon_code as coupon_code_crud
from app.api.email_logs.crud import email_log
from app.api.email_logs.schemas import EmailAttachment, EmailEvent
from app.api.payments import schemas
from app.api.payments.schemas import PaymentSource
from app.api.products.models import Product
from app.core import models, payments_utils
from app.core.invoice import generate_invoice_pdf
from app.core.logger import logger
from app.core.security import TokenData


class CRUDPayment(
    CRUDBase[models.Payment, schemas.PaymentCreate, schemas.PaymentUpdate]
):
    def _check_permission(self, db_obj: models.Payment, user: TokenData) -> bool:
        return db_obj.application.citizen_id == user.citizen_id

    def _apply_filters(
        self, query: Query, filters: Optional[schemas.BaseModel] = None
    ) -> Query:
        query = super()._apply_filters(query, filters)

        if not filters:
            return query

        filter_data = filters.model_dump(exclude_none=True)

        if 'citizen_id' in filter_data:
            citizen_id = filter_data.pop('citizen_id')
            query = query.join(models.Payment.application).filter(
                Application.citizen_id == citizen_id
            )
        return query

    def find(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[BaseModel] = None,
        user: Optional[TokenData] = None,
        sort_by: str = 'created_at',
        sort_order: str = 'desc',
    ) -> List[models.Payment]:
        if user:
            if filters is None or not isinstance(filters, schemas.PaymentFilter):
                filters = schemas.PaymentFilter()
            filters.citizen_id = user.citizen_id
        return super().find(db, skip, limit, filters, user, sort_by, sort_order)

    def preview(
        self,
        db: Session,
        obj: schemas.PaymentCreate,
        user: Optional[TokenData] = None,
    ) -> schemas.PaymentPreview:
        return payments_utils.preview_payment(db, obj, user)

    def create(
        self,
        db: Session,
        obj: schemas.PaymentCreate,
        user: Optional[TokenData] = None,
    ) -> models.Payment:
        payment_data, insurance_per_item = payments_utils.create_payment(db, obj, user)

        payment_dict = payment_data.model_dump(
            exclude={
                'products',
                'original_amount',
                'insurance',
                'insurance_amount',
                'variable_amount',
            }
        )
        payment_dict['edit_passes'] = obj.edit_passes
        db_payment = self.model(**payment_dict)

        # First save the payment to get its ID
        db.add(db_payment)
        db.flush()  # This assigns an ID to db_payment without committing

        if obj.products:
            # validate that the attendees correspond to the application
            attendees_ids = {p.attendee_id for p in obj.products}
            attendees = db.query(Attendee).filter(Attendee.id.in_(attendees_ids)).all()
            if len(attendees) != len(attendees_ids):
                raise HTTPException(status_code=400, detail='Invalid attendees')
            for attendee in attendees:
                if attendee.application_id != obj.application_id:
                    raise HTTPException(status_code=400, detail='Invalid attendees')

            product_ids = [p.product_id for p in obj.products]
            products_data = {
                p.id: p
                for p in db.query(Product).filter(Product.id.in_(product_ids)).all()
            }

            for product in obj.products:
                product_id = product.product_id
                product_data = products_data[product_id]
                item_key = (product_id, product.attendee_id)

                if product_data.min_price is not None:
                    snapshot_price = product.custom_amount
                else:
                    snapshot_price = product_data.price

                has_insurance = (
                    obj.insurance and product_data.insurance_percentage is not None
                )
                payment_product = models.PaymentProduct(
                    payment_id=db_payment.id,
                    product_id=product_id,
                    attendee_id=product.attendee_id,
                    quantity=product.quantity,
                    product_name=product_data.name,
                    product_description=product_data.description,
                    product_price=snapshot_price,
                    product_category=product_data.category,
                    insurance_applied=has_insurance,
                    insurance_price=insurance_per_item.get(item_key),
                )
                db.add(payment_product)

            db.flush()
            db.refresh(db_payment)

        if db_payment.status == 'approved':
            if db_payment.edit_passes:
                self._clear_application_products(db, db_payment)

            if db_payment.coupon_code_id is not None:
                coupon_code_crud.use_coupon_code(db, db_payment.coupon_code_id)

            self._add_products_to_attendees(db_payment)
            group = self._create_ambassador_group(db, db_payment)
            if not db_payment.is_installment_plan:
                self._send_payment_confirmed_email(db_payment, group)

        db.commit()
        db.refresh(db_payment)
        return db_payment

    def _add_products_to_attendees(self, payment: models.Payment) -> None:
        if not payment.products_snapshot:
            return

        logger.info('Adding products to attendees')
        for product_snapshot in payment.products_snapshot:
            attendee = product_snapshot.attendee
            product_id = product_snapshot.product_id
            if product_id not in [p.id for p in attendee.products]:
                attendee.attendee_products.append(
                    AttendeeProduct(
                        attendee_id=attendee.id,
                        product_id=product_id,
                        quantity=product_snapshot.quantity,
                        insurance_applied=product_snapshot.insurance_applied,
                        insurance_price=product_snapshot.insurance_price,
                    )
                )

    def _remove_products_from_attendees(
        self, db: Session, payment: models.Payment
    ) -> None:
        """Remove products from attendees that were added by this payment."""
        if not payment.products_snapshot:
            return

        logger.info('Removing products from attendees for payment %s', payment.id)
        for product_snapshot in payment.products_snapshot:
            # Find and remove the AttendeeProduct record matching this payment's snapshot
            attendee_product = (
                db.query(AttendeeProduct)
                .filter(
                    AttendeeProduct.attendee_id == product_snapshot.attendee.id,
                    AttendeeProduct.product_id == product_snapshot.product_id,
                    AttendeeProduct.quantity == product_snapshot.quantity,
                )
                .first()
            )
            if attendee_product:
                db.delete(attendee_product)

    def _clear_application_products(self, db: Session, payment: models.Payment) -> None:
        logger.info('Removing products from attendees')
        application = payment.application
        attendees_ids = {a.id for a in application.attendees}
        query = AttendeeProduct.attendee_id.in_(attendees_ids)
        db.query(AttendeeProduct).filter(query).delete(synchronize_session=False)

    def _send_payment_confirmed_email(
        self, payment: models.Payment, group: Optional[models.Group]
    ) -> None:
        logger.info('Sending payment confirmed email for payment %s', payment.id)
        ticket_list = []
        if payment.products_snapshot:
            for product_snapshot in payment.products_snapshot:
                attendee = product_snapshot.attendee
                ticket_list.append(f'{product_snapshot.product_name} ({attendee.name})')

        checkout_url = group.express_checkout_url() if group else ''
        first_name = payment.application.first_name
        params = {
            'ticket_list': ', '.join(ticket_list),
            'first_name': first_name,
            'checkout_url': checkout_url,
        }
        event = EmailEvent.PAYMENT_CONFIRMED.value
        if payment.edit_passes and payment.amount == 0:
            event = EmailEvent.EDIT_PASSES_CONFIRMED.value

        client_name = f'{first_name} {payment.application.last_name}'
        attachments = None
        if payment.amount > 0:
            encoded_pdf = generate_invoice_pdf(
                payment,
                client_name,
                payment.discount_value,
                payment.application.popup_city.image_url,
            )
            attachments = [
                EmailAttachment(
                    name=f'invoice_{payment.id}.pdf',
                    content_id='invoice',
                    content=encoded_pdf,
                    content_type='application/pdf',
                )
            ]

        email_log.send_mail(
            receiver_mail=payment.application.citizen.primary_email,
            event=event,
            params=params,
            popup_city=payment.application.popup_city,
            entity_type='payment',
            entity_id=payment.id,
            attachments=attachments,
        )

    def _create_ambassador_group(
        self, db: Session, payment: models.Payment
    ) -> Optional[models.Group]:
        from app.api.groups.crud import group as group_crud

        return group_crud.create_ambassador_group(db, payment.application)

    def approve_payment(
        self,
        db: Session,
        payment: models.Payment,
        *,
        user: TokenData,
        currency: Optional[str] = None,
        rate: Optional[float] = None,
    ) -> models.Payment:
        """Handle payment approval and related operations."""
        if payment.status == 'approved':
            logger.info('Payment %s already approved', payment.id)
            return payment

        source = PaymentSource.STRIPE if currency == 'USD' else PaymentSource.SIMPLEFI
        payment_update = schemas.PaymentUpdate(
            status='approved',
            currency=currency,
            rate=rate,
            source=source,
        )
        updated_payment = self.update(db, payment.id, payment_update, user)

        if payment.edit_passes:
            self._clear_application_products(db, payment)
            payment.application.credit = 0
            db.flush()
            db.refresh(payment.application)

        if payment.coupon_code_id is not None:
            coupon_code_crud.use_coupon_code(db, payment.coupon_code_id)

        self._add_products_to_attendees(payment)
        group = self._create_ambassador_group(db, payment)
        if not payment.is_installment_plan:
            self._send_payment_confirmed_email(payment, group)

        logger.info('Payment %s approved', payment.id)
        db.commit()
        return updated_payment


payment = CRUDPayment(models.Payment)
