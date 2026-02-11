import time
from datetime import timedelta
from typing import List

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from app.api.email_logs.crud import email_log as email_log_crud
from app.api.email_logs.schemas import EmailEvent
from app.core import models
from app.core.database import SessionLocal
from app.core.logger import logger
from app.core.utils import current_time


def _format_price(price):
    return f'${price:,.2f}'.rstrip('0').rstrip('.')


def get_to_exclude_emails(db: Session) -> List[str]:
    """Get list of emails that have received an abandoned cart email in the past week.

    These emails should be excluded from receiving another abandoned cart email
    to avoid spamming users.
    """
    one_week_ago = current_time() - timedelta(days=7)
    return list(
        db.scalars(
            select(models.EmailLog.receiver_email).where(
                models.EmailLog.event == EmailEvent.ABANDONED_CART.value,
                models.EmailLog.created_at >= one_week_ago,
            )
        ).all()
    )


def process_abandoned_cart(db: Session, to_exclude_emails: List[str]):
    five_hours_ago = current_time() - timedelta(hours=5)
    one_hours_ago = current_time() - timedelta(hours=1)
    # Subquery: latest payment OVERALL per application in popup_city_id=2
    latest_per_app = (
        select(
            models.Payment.application_id,
            models.Payment.status,
            models.Payment.created_at,
            models.Payment.id,
        )
        .join(
            models.Application,
            models.Application.id == models.Payment.application_id,
        )
        .where(
            models.Application.popup_city_id == 2,
            models.Application.email.notin_(to_exclude_emails)
            if to_exclude_emails
            else true(),
            models.Payment.edit_passes.is_(False),
        )
        .distinct(models.Payment.application_id)  # DISTINCT ON (application_id)
        .order_by(
            models.Payment.application_id,
            models.Payment.created_at.desc().nulls_last(),
            models.Payment.id.desc(),
        )
    ).subquery('latest_per_app')

    # Return the actual Payment rows that are those "latest" rows
    stmt = (
        select(models.Payment)
        .join(latest_per_app, models.Payment.id == latest_per_app.c.id)
        .where(
            latest_per_app.c.status != 'approved',
            latest_per_app.c.created_at >= five_hours_ago,
            latest_per_app.c.created_at <= one_hours_ago,
        )
    )

    payments = db.scalars(stmt).all()
    logger.info('Found %s payments', len(payments))
    for p in payments:
        logger.info('Processing payment %s %s', p.id, p.application.email)

        lines = []
        total = 0
        for ps in p.products_snapshot:
            lines.extend(
                [
                    f'<strong>Name:</strong> {ps.attendee.name}',
                    f'<strong>Ticket:</strong> {ps.product_name}',
                ]
            )
            product_price = ps.product_price or 0.0
            if p.discount_value:
                amount = round(product_price * (1 - p.discount_value / 100), 2)
            else:
                amount = product_price

            total += amount
            lines.append(f'<strong>Price:</strong> {_format_price(amount)}<br>')

        assert p.amount == total
        if len(p.products_snapshot) > 1:
            lines.append(f'<strong>Total:</strong> {_format_price(p.amount)}')

        purchase_details = '<br>'.join(lines)
        logger.info('Purchase details: %s', purchase_details)

        params = {
            'first_name': p.application.first_name,
            'purchase_details': purchase_details,
            'ticketing_url': p.checkout_url,
        }

        email_log_crud.send_mail(
            receiver_mail=p.application.email,
            event=EmailEvent.ABANDONED_CART.value,
            popup_city=p.application.popup_city,
            params=params,
            entity_type='payment',
            entity_id=p.id,
            citizen_id=p.application.citizen_id,
            popup_slug=p.application.popup_city.slug,
        )

        logger.info('-' * 100)


def main():
    with SessionLocal() as db:
        to_exclude = get_to_exclude_emails(db)
        logger.info('To exclude emails: %s', to_exclude)
        process_abandoned_cart(db, to_exclude)


if __name__ == '__main__':
    while True:
        try:
            main()
        except Exception as e:
            logger.error('Error in abandoned cart process: %s', e)
        time.sleep(120)
