from datetime import timedelta

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.applications.crud import calculate_status
from app.api.applications.models import Application
from app.api.applications.schemas import ApplicationStatus
from app.api.email_logs.crud import email_log
from app.api.email_logs.models import EmailLog
from app.api.email_logs.schemas import EmailEvent, EmailStatus
from app.api.payments.crud import payment as payment_crud
from app.api.payments.models import PaymentInstallment
from app.api.payments.schemas import PaymentFilter, PaymentUpdate
from app.api.webhooks import schemas
from app.api.webhooks.dependencies import get_webhook_cache
from app.core import ai_scoring
from app.core.cache import WebhookCache
from app.core.config import settings
from app.core.database import get_db
from app.core.logger import logger
from app.core.security import TokenData
from app.core.utils import current_time

router = APIRouter()


@router.post('/update_status', status_code=status.HTTP_200_OK)
async def update_status_webhook(
    webhook_payload: schemas.WebhookPayload,
    secret: str = Header(..., description='Secret'),
    db: Session = Depends(get_db),
    webhook_cache: WebhookCache = Depends(get_webhook_cache),
):
    logger.info('POST /update_status')
    fingerprint = f'update_status:{webhook_payload.data.table_id}:{webhook_payload.id}'
    logger.info('Fingerprint: %s', fingerprint)
    if not webhook_cache.add(fingerprint):
        logger.info('Webhook already processed. Skipping...')
        return {'message': 'Webhook already processed'}

    if secret != settings.NOCODB_WEBHOOK_SECRET:
        logger.info('Secret is not valid. Skipping...')
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Secret is not valid',
        )

    if webhook_payload.data.table_name != 'applications':
        logger.info('Table name is not applications. Skipping...')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Table name is not applications',
        )

    table_id = webhook_payload.data.table_id
    url = f'{settings.NOCODB_URL}/api/v2/tables/{table_id}/records'
    headers = {
        'accept': 'application/json',
        'xc-token': settings.NOCODB_TOKEN,
        'Content-Type': 'application/json',
    }
    for row in webhook_payload.data.rows:
        application = db.get(Application, row.id)
        email = application.email
        logger.info('Processing webhook for application %s %s', row.id, email)

        row_dict = row.model_dump()
        reviews_status = row_dict.get('calculated_status')
        current_status = row_dict.get('status')

        if application.group:
            logger.info(
                'Application is in group %s. Skipping...', application.group.slug
            )
            calculated_status = ApplicationStatus.ACCEPTED
            if reviews_status == ApplicationStatus.WITHDRAWN.value:
                calculated_status = ApplicationStatus.WITHDRAWN
            requested_discount = False
        else:
            calculated_status, requested_discount = calculate_status(
                application,
                popup_city=application.popup_city,
                reviews_status=reviews_status,
            )

        if (
            calculated_status == ApplicationStatus.IN_REVIEW
            and not application.ai_review
        ):
            ai_review = ai_scoring.review_application(application)
            if ai_review:
                application.ai_review = ai_review
                db.add(application)
                db.commit()
                db.refresh(application)

        if current_status == calculated_status:
            logger.info(
                'Status is the same as calculated status (%s). ID: %s, Email: %s. Skipping...',
                calculated_status,
                row.id,
                email,
            )
            continue

        email_log.cancel_scheduled_emails(
            db,
            entity_type='application',
            entity_id=row.id,
        )

        data = {
            'id': row.id,
            'status': calculated_status,
            'requested_discount': requested_discount,
        }
        if (
            calculated_status == ApplicationStatus.ACCEPTED
            and application.accepted_at is None
        ):
            data['accepted_at'] = current_time().isoformat()

        logger.info('update_status data: %s', data)
        response = requests.patch(url, headers=headers, json=data)
        logger.info('update_status status code: %s', response.status_code)
        logger.info('update_status response: %s', response.json())

    logger.info('update_status finished')
    return {'message': 'Status updated successfully'}


@router.post('/send_email', status_code=status.HTTP_200_OK)
async def send_email_webhook(
    webhook_payload: schemas.WebhookPayload,
    event: str = Query(..., description='Email event'),
    fields: str = Query(..., description='Template fields'),
    unique: bool = Query(True, description='Verify if the email is unique'),
    delay: int = Query(0, description='Delay in minutes'),
    db: Session = Depends(get_db),
):
    if not webhook_payload.data.rows:
        logger.info('No rows to send email')
        return {'message': 'No rows to send email'}

    fields = [f.strip() for f in fields.split(',')]
    processed_ids = []

    logger.info('Sending email %s to %s rows', event, len(webhook_payload.data.rows))
    logger.info('Fields: %s', fields)
    send_at = current_time() + timedelta(minutes=delay) if delay else None

    for row in webhook_payload.data.rows:
        row = row.model_dump()
        if not row.get('email'):
            logger.info('No email to send email. Skipping...')
            continue

        params = {k: v for k, v in row.items() if k in fields}
        if 'ticketing_url' not in params:
            params['ticketing_url'] = settings.FRONTEND_URL

        application = db.get(Application, row['id'])

        if unique:
            exists_email_log = (
                db.query(EmailLog)
                .filter(
                    EmailLog.entity_id == application.id,
                    EmailLog.entity_type == 'application',
                    EmailLog.event == event,
                    EmailLog.status == EmailStatus.SUCCESS,
                )
                .first()
            )
            if exists_email_log:
                logger.info('Email already sent')
                continue

        if send_at:
            # Cancel any existing scheduled emails since only one can be active per application
            logger.info('Cancelling scheduled emails')
            email_log.cancel_scheduled_emails(
                db,
                entity_type='application',
                entity_id=application.id,
            )

        params['ticketing_url'] = email_log.generate_authenticate_url(db, application)
        params['first_name'] = application.first_name
        email_log.send_mail(
            receiver_mail=row['email'],
            event=event,
            popup_city=application.popup_city,
            params=params,
            send_at=send_at,
            entity_type='application',
            entity_id=application.id,
        )

        processed_ids.append(row['id'])

        is_approved_event = event in [
            EmailEvent.APPLICATION_APPROVED.value,
            EmailEvent.APPLICATION_APPROVED_SCHOLARSHIP.value,
            EmailEvent.APPLICATION_APPROVED_NON_SCHOLARSHIP.value,
        ]
        is_patagonia = application.popup_city.slug == 'edge-patagonia'

        if is_approved_event and is_patagonia and application.brings_kids:
            email_log.send_mail(
                receiver_mail=row['email'],
                event=EmailEvent.WELCOME_FAMILIES.value,
                popup_city=application.popup_city,
                params=params,
                send_at=send_at,
                entity_type='application',
                entity_id=application.id,
            )

    return {'message': 'Email sent successfully'}


@router.post('/simplefi', status_code=status.HTTP_200_OK)
async def simplefi_webhook(
    request: Request,
    db: Session = Depends(get_db),
    webhook_cache: WebhookCache = Depends(get_webhook_cache),
):
    raw_body = await request.json()
    event_type = raw_body.get('event_type')

    if event_type == 'installment_plan_completed':
        return await _handle_installment_plan_completed(raw_body, db, webhook_cache)

    if event_type == 'installment_plan_activated':
        return await _handle_installment_plan_activated(raw_body, db, webhook_cache)

    if event_type == 'installment_plan_cancelled':
        return await _handle_installment_plan_cancelled(raw_body, db, webhook_cache)

    # Handle payment-related events (new_payment, new_card_payment)
    webhook_payload = schemas.SimplefiWebhookPayload(**raw_body)

    # Check if this is an installment payment
    installment_plan_id = webhook_payload.data.payment_request.installment_plan_id
    if installment_plan_id:
        return await _handle_installment_payment(webhook_payload, db, webhook_cache)

    # Otherwise continue with regular payment flow
    return await _handle_regular_payment(webhook_payload, db, webhook_cache)


async def _handle_regular_payment(
    webhook_payload: schemas.SimplefiWebhookPayload,
    db: Session,
    webhook_cache: WebhookCache,
):
    """Handle new_payment/new_card_payment for regular (non-installment) payments."""
    event_type = webhook_payload.event_type
    payment_request_id = webhook_payload.data.payment_request.id

    fingerprint = f'simplefi:{payment_request_id}:{event_type}'
    if not webhook_cache.add(fingerprint):
        logger.info('Webhook already processed. Skipping...')
        return {'message': 'Webhook already processed'}

    logger.info(
        'Payment request id: %s, event type: %s', payment_request_id, event_type
    )
    if event_type not in ['new_payment', 'new_card_payment']:
        logger.info('Event type is not new_payment or new_card_payment. Skipping...')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Event type is not new_payment or new_card_payment',
        )

    payments = payment_crud.find(
        db, filters=PaymentFilter(external_id=payment_request_id)
    )
    if not payments:
        logger.info('Payment not found')
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Payment not found',
        )

    payment = payments[0]
    payment_request_status = webhook_payload.data.payment_request.status

    if payment.status == payment_request_status:
        logger.info('Payment status is the same as payment request status. Skipping...')
        return {'message': 'Payment status is the same as payment request status'}

    currency = 'USD'
    rate = 1
    if webhook_payload.data.new_payment:
        currency = webhook_payload.data.new_payment.coin
        for t in webhook_payload.data.payment_request.transactions:
            if t.coin == currency:
                rate = t.price_details.rate
                break

    user = TokenData(citizen_id=payment.application.citizen_id, email='')

    if payment_request_status == 'approved':
        payment_crud.approve_payment(
            db, payment, currency=currency, rate=rate, user=user
        )
    else:
        payment_crud.update(db, payment.id, PaymentUpdate(status='expired'), user)

    return {'message': 'Payment status updated successfully'}


async def _handle_installment_payment(
    webhook_payload: schemas.SimplefiWebhookPayload,
    db: Session,
    webhook_cache: WebhookCache,
):
    """Handle new_payment/new_card_payment for installment plans."""
    payment_request = webhook_payload.data.payment_request
    installment_plan_id = payment_request.installment_plan_id
    new_payment = webhook_payload.data.new_payment
    payment_request_id = payment_request.id  # Unique per installment

    # Idempotency: use payment_request.id (unique per installment)
    fingerprint = f'simplefi:installment:{installment_plan_id}:{payment_request_id}'
    if not webhook_cache.add(fingerprint):
        logger.info('Webhook already processed. Skipping...')
        return {'message': 'Webhook already processed'}

    logger.info(
        'Installment payment: plan_id=%s, payment_request_id=%s',
        installment_plan_id,
        payment_request_id,
    )

    # Look up Payment by installment_plan_id (stored in external_id)
    payments = payment_crud.find(
        db, filters=PaymentFilter(external_id=installment_plan_id)
    )
    if not payments:
        logger.info('Payment not found for installment plan %s', installment_plan_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Payment not found',
        )

    payment = payments[0]

    # Extract payment details
    if isinstance(new_payment, schemas.PaymentInfo):
        amount = new_payment.amount
        currency = new_payment.coin
        paid_at = new_payment.paid_at
    else:
        amount = payment_request.amount_paid
        currency = new_payment.coin if new_payment else 'USD'
        paid_at = current_time()

    # Create PaymentInstallment record
    installment_number = len(payment.installments) + 1
    installment = PaymentInstallment(
        payment_id=payment.id,
        external_payment_id=payment_request_id,
        installment_number=installment_number,
        amount=amount,
        currency=currency,
        paid_at=paid_at,
    )
    db.add(installment)

    # Check if this is the first installment - approve payment to assign products
    is_first_installment = (payment.installments_paid or 0) == 0
    if is_first_installment and payment.status != 'approved':
        user = TokenData(citizen_id=payment.application.citizen_id, email='')
        payment_crud.approve_payment(db, payment, currency=currency, rate=1, user=user)
        logger.info('First installment received - payment %s approved', payment.id)

    # Increment installments_paid
    payment.installments_paid = (payment.installments_paid or 0) + 1
    db.commit()

    logger.info(
        'Installment %s recorded for payment %s (paid: %s/%s)',
        installment_number,
        payment.id,
        payment.installments_paid,
        payment.installments_total,
    )

    return {'message': 'Installment payment recorded'}


async def _handle_installment_plan_completed(
    raw_body: dict,
    db: Session,
    webhook_cache: WebhookCache,
):
    """Handle the installment_plan_completed webhook event."""
    webhook_payload = schemas.InstallmentPlanCompletedPayload(**raw_body)
    entity_id = webhook_payload.entity_id
    event_type = webhook_payload.event_type

    fingerprint = f'simplefi:installment:{entity_id}:{event_type}'
    if not webhook_cache.add(fingerprint):
        logger.info('Webhook already processed. Skipping...')
        return {'message': 'Webhook already processed'}

    logger.info('Installment plan id: %s, event type: %s', entity_id, event_type)

    # Find payment by external_id matching the installment plan ID
    payments = payment_crud.find(db, filters=PaymentFilter(external_id=entity_id))
    if not payments:
        logger.info('Payment not found for installment plan %s', entity_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Payment not found',
        )

    payment = payments[0]

    # Log warning if payment is not marked as an installment plan
    if not payment.is_installment_plan:
        logger.warning(
            'Payment %s is not marked as an installment plan but received '
            'installment_plan_completed webhook',
            payment.id,
        )

    # Idempotent: if already approved, just sync installments_paid and send email
    if payment.status == 'approved':
        logger.info(
            'Payment %s already approved, syncing installments_paid', payment.id
        )
        installment_plan = webhook_payload.data.installment_plan
        payment.installments_paid = installment_plan.paid_installments_count
        group = payment_crud._create_ambassador_group(db, payment)
        payment_crud._send_payment_confirmed_email(payment, group)
        db.commit()
        return {'message': 'Installment plan completed - count synced'}

    # Edge case: plan completed but payment not approved (shouldn't happen normally)
    logger.warning(
        'Payment %s not approved when installment_plan_completed received',
        payment.id,
    )
    installment_plan = webhook_payload.data.installment_plan
    payment.installments_paid = installment_plan.paid_installments_count

    user = TokenData(citizen_id=payment.application.citizen_id, email='')
    payment_crud.approve_payment(db, payment, currency='USD', rate=1, user=user)
    group = payment_crud._create_ambassador_group(db, payment)
    payment_crud._send_payment_confirmed_email(payment, group)

    return {'message': 'Installment plan payment approved successfully'}


async def _handle_installment_plan_activated(
    raw_body: dict,
    db: Session,
    webhook_cache: WebhookCache,
):
    """Handle the installment_plan_activated webhook event."""
    webhook_payload = schemas.InstallmentPlanActivatedPayload(**raw_body)
    entity_id = webhook_payload.entity_id
    event_type = webhook_payload.event_type

    fingerprint = f'simplefi:installment:{entity_id}:{event_type}'
    if not webhook_cache.add(fingerprint):
        logger.info('Webhook already processed. Skipping...')
        return {'message': 'Webhook already processed'}

    logger.info('Installment plan activated: %s', entity_id)

    # Find payment by external_id matching the installment plan ID
    payments = payment_crud.find(db, filters=PaymentFilter(external_id=entity_id))
    if not payments:
        logger.info('Payment not found for installment plan %s', entity_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Payment not found',
        )

    payment = payments[0]
    installment_plan = webhook_payload.data.installment_plan

    # Update installments_total with actual number chosen by user
    payment.installments_total = installment_plan.number_of_installments
    db.commit()

    logger.info(
        'Payment %s: installments_total updated to %s',
        payment.id,
        installment_plan.number_of_installments,
    )

    return {'message': 'Installment plan activated successfully'}


async def _handle_installment_plan_cancelled(
    raw_body: dict,
    db: Session,
    webhook_cache: WebhookCache,
):
    """Handle the installment_plan_cancelled webhook event."""
    webhook_payload = schemas.InstallmentPlanCancelledPayload(**raw_body)
    entity_id = webhook_payload.entity_id
    event_type = webhook_payload.event_type

    fingerprint = f'simplefi:installment:{entity_id}:{event_type}'
    if not webhook_cache.add(fingerprint):
        logger.info('Webhook already processed. Skipping...')
        return {'message': 'Webhook already processed'}

    logger.info('Installment plan cancelled: %s', entity_id)

    # Find payment by external_id matching the installment plan ID
    payments = payment_crud.find(db, filters=PaymentFilter(external_id=entity_id))
    if not payments:
        logger.info('Payment not found for installment plan %s', entity_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Payment not found',
        )

    payment = payments[0]

    # Idempotent: skip if already cancelled
    if payment.status == 'cancelled':
        logger.info('Payment %s already cancelled. Skipping...', payment.id)
        return {'message': 'Payment already cancelled'}

    # If payment was approved, revoke products
    if payment.status == 'approved':
        logger.info('Revoking products for cancelled payment %s', payment.id)
        payment_crud._remove_products_from_attendees(db, payment)

    # Update status to cancelled
    payment.status = 'cancelled'
    db.commit()

    logger.info('Payment %s cancelled', payment.id)
    return {'message': 'Installment plan cancelled successfully'}
