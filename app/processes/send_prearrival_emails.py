import time
from datetime import timedelta
from typing import List

from sqlalchemy.orm import Session

from app.api.applications.models import Application
from app.api.attendees.models import Attendee
from app.api.check_in.models import CheckIn
from app.api.email_logs.crud import email_log as email_log_crud
from app.api.email_logs.models import EmailLog
from app.api.email_logs.schemas import EmailAttachment, EmailEvent
from app.api.popup_city.models import PopUpCity
from app.core import models  # noqa: F401
from app.core.config import Environment, settings
from app.core.database import SessionLocal
from app.core.logger import logger
from app.core.qr_generator import generate_plain_qr_code_base64, generate_qr_code_base64
from app.core.utils import current_time

POPUP_CITY_SLUG = 'edge-patagonia'
DAYS_BEFORE_START_5DAY = 5
DAYS_BEFORE_START_24H = 1


def generate_qr_attachment(check_in_code: str, attendee_name: str):
    """Generate a modern, styled QR code attachment for an attendee."""
    logger.info('Generating QR code for %s %s', check_in_code, attendee_name)
    filename = f'{attendee_name}.png'.replace(' ', '_')
    return EmailAttachment(
        name=filename,
        content_id=f'cid:{filename}',
        content=generate_qr_code_base64(check_in_code, attendee_name),
        content_type='image/png',
    )


def generate_qr_attachments(attendees: List[Attendee]):
    """Generate QR code attachments for all attendees with products."""
    attachments = []
    for attendee in attendees:
        if attendee.products:
            qr = generate_qr_attachment(attendee.check_in_code, attendee.name)
            attachments.append(qr)
    return attachments


def generate_checkin_codes_html(attendees: List[Attendee]) -> str:
    """Generate HTML formatted string with all attendees' check-in codes and products."""
    html_parts = []
    for attendee in attendees:
        if attendee.category == 'main':
            continue
        if attendee.products:
            html_parts.append(
                f'<li><strong>{attendee.name}</strong>: {attendee.check_in_code}</li>'
            )

    if not html_parts:
        return ''

    return f"<p>Here are the access codes for your guests:</p><ul>{''.join(html_parts)}</ul><p>You'll find their QR codes attached.</p>"


def get_earliest_start_date(application: Application):
    """
    Get the earliest start date from all products across all attendees.
    Fallback to popup city start date if no product has a start date.
    """
    earliest_date = None
    for attendee in application.attendees:
        for product in attendee.products:
            if product.start_date:
                if not earliest_date or product.start_date < earliest_date:
                    earliest_date = product.start_date

    if not earliest_date:
        # Fallback to popup city start date
        earliest_date = application.popup_city.start_date

    return earliest_date


def has_any_attendee_checked_in(application: Application, db: Session) -> bool:
    """
    Check if any attendee in the application has already checked in via QR code.
    Returns True if any attendee has qr_check_in=True, False otherwise.
    """
    attendee_ids = [attendee.id for attendee in application.attendees]

    if not attendee_ids:
        return False

    # Check if any attendee has a check-in record with qr_check_in=True
    checked_in_count = (
        db.query(CheckIn)
        .filter(
            CheckIn.attendee_id.in_(attendee_ids),
            CheckIn.qr_check_in == True,  # noqa: E712
        )
        .count()
    )

    return checked_in_count > 0


def get_sent_prearrival_emails(db: Session, event: str) -> List[str]:
    """Get list of application emails that have already received pre-arrival emails for a specific event."""
    logs = (
        db.query(EmailLog.receiver_email.distinct())
        .filter(EmailLog.event == event)
        .all()
    )
    return [log[0] for log in logs]


def get_applications_for_prearrival(db: Session):
    """
    Get applications that need to receive pre-arrival emails.

    Criteria:
    - From Edge Patagonia (popup_city slug == 'edge-patagonia')
    - Has attendees with products
    - Earliest product start date is 5 days or less away
    - Haven't received pre-arrival email yet (deduplication handled by exclusion list)
    """
    excluded_emails = get_sent_prearrival_emails(db, EmailEvent.PRE_ARRIVAL.value)
    logger.info('Excluded application emails: %s', excluded_emails)

    today = current_time()
    target_date = today + timedelta(days=DAYS_BEFORE_START_5DAY)

    # Get all applications from Edge Patagonia with attendees that have products
    applications = (
        db.query(Application)
        .join(Application.popup_city)
        .join(Application.attendees)
        .join(Attendee.products)
        .filter(
            PopUpCity.slug == POPUP_CITY_SLUG,
            Application.email.notin_(excluded_emails),
        )
        .distinct()
        .all()
    )

    logger.info('Applications before filter: %s', len(applications))

    # Filter to only include applications where the earliest start date
    # is 5 days or less away
    filtered_applications = []
    for application in applications:
        earliest_date = get_earliest_start_date(application)
        logger.info(
            'Earliest date for application %s %s: %s',
            application.id,
            application.email,
            earliest_date.strftime('%Y-%m-%d'),
        )
        if not earliest_date:
            logger.error('No earliest date for application %s', application.id)
            continue

        # Check if earliest start date is at most 5 days away
        if earliest_date <= target_date:
            logger.info('Application %s is 5 days or less away', application.id)
            filtered_applications.append(application)

    logger.info('Total applications found: %s', len(filtered_applications))
    logger.info('Emails: %s', [a.email for a in filtered_applications])
    logger.info(
        'Applications ids to process: %s', [a.id for a in filtered_applications]
    )

    return filtered_applications


def get_applications_for_24h_prearrival(db: Session):
    """
    Get applications that need to receive 24-hour pre-arrival emails.

    Criteria:
    - From Edge Patagonia (popup_city slug == 'edge-patagonia')
    - Has attendees with products
    - Earliest product start date is 1 day or less away
    - No attendees have checked in yet (qr_check_in=False)
    - Haven't received 24-hour pre-arrival email yet (deduplication handled by exclusion list)
    """
    excluded_emails = get_sent_prearrival_emails(db, EmailEvent.PRE_ARRIVAL_24H.value)
    logger.info('Excluded 24h application emails: %s', excluded_emails)

    today = current_time()
    target_date = today + timedelta(days=DAYS_BEFORE_START_24H)

    # Get all applications from Edge Patagonia with attendees that have products
    applications = (
        db.query(Application)
        .join(Application.popup_city)
        .join(Application.attendees)
        .join(Attendee.products)
        .filter(
            PopUpCity.slug == POPUP_CITY_SLUG,
            Application.email.notin_(excluded_emails),
        )
        .distinct()
        .all()
    )

    logger.info('Applications before filter (24h): %s', len(applications))

    # Filter to only include applications where the earliest start date
    # is 1 day or less away
    filtered_applications = []
    for application in applications:
        earliest_date = get_earliest_start_date(application)
        logger.info(
            'Earliest date for application %s %s (24h check): %s',
            application.id,
            application.email,
            earliest_date.strftime('%Y-%m-%d'),
        )
        if not earliest_date:
            logger.error('No earliest date for application %s', application.id)
            continue

        # Check if earliest start date is at most 1 day away
        if earliest_date <= target_date:
            logger.info('Application %s is 1 day or less away', application.id)

            # Check if any attendee has already checked in
            if has_any_attendee_checked_in(application, db):
                logger.info(
                    'Skipping application %s %s - at least one attendee has already checked in',
                    application.id,
                    application.email,
                )
                continue

            filtered_applications.append(application)

    logger.info('Total 24h applications found: %s', len(filtered_applications))
    logger.info('24h Emails: %s', [a.email for a in filtered_applications])
    logger.info(
        '24h Applications ids to process: %s', [a.id for a in filtered_applications]
    )

    return filtered_applications


def process_application_for_prearrival(application: Application):
    """Send pre-arrival email to application with QR codes for all attendees."""
    logger.info('Processing application %s %s', application.id, application.email)

    attachments = generate_qr_attachments(application.attendees)

    params = {'first_name': application.first_name}
    logger.info('Sending pre-arrival email to %s', application.email)
    email_log_crud.send_mail(
        receiver_mail=application.email,
        event=EmailEvent.PRE_ARRIVAL.value,
        popup_city=application.popup_city,
        params=params,
        entity_type='application',
        entity_id=application.id,
        attachments=attachments,
    )


def process_application_for_24h_prearrival(application: Application):
    """Send 24-hour pre-arrival email to application with check-in codes details and QR codes."""
    logger.info('Processing 24h application %s %s', application.id, application.email)

    main_attendee = application.get_main_attendee()

    if not main_attendee:
        logger.warning('No attendees with products for application %s', application.id)
        return

    # Generate QR code attachments for all attendees
    attachments = generate_qr_attachments(application.attendees)

    # Add main attendee QR code as main.png (plain black and white version)
    main_qr = EmailAttachment(
        name='main.png',
        content_id='cid:main.png',
        content=generate_plain_qr_code_base64(main_attendee.check_in_code),
        content_type='image/png',
    )
    attachments.append(main_qr)

    # Generate HTML with all attendees' check-in codes
    checkin_codes_html = generate_checkin_codes_html(application.attendees)

    params = {
        'first_name': application.first_name,
        'checkin_code': main_attendee.check_in_code,
        'checkin_codes_details': checkin_codes_html,
    }

    logger.info('Params: %s', params)
    logger.info('Sending 24h pre-arrival email to %s', application.email)
    email_log_crud.send_mail(
        receiver_mail=application.email,
        event=EmailEvent.PRE_ARRIVAL_24H.value,
        popup_city=application.popup_city,
        params=params,
        entity_type='application',
        entity_id=application.id,
        attachments=attachments,
    )


def send_prearrival_emails(db: Session):
    """Main function to process and send pre-arrival emails (both 5-day and 24-hour)."""
    logger.info('Starting pre-arrival email process')

    # Process 5-day pre-arrival emails
    logger.info('Processing 5-day pre-arrival emails')
    applications_5day = get_applications_for_prearrival(db)
    logger.info('Total 5-day applications to process: %s', len(applications_5day))

    for application in applications_5day:
        try:
            process_application_for_prearrival(application)
        except Exception as e:
            logger.error(
                'Error processing 5-day application %s: %s', application.id, str(e)
            )
            continue

    # Process 24-hour pre-arrival emails
    logger.info('Processing 24-hour pre-arrival emails')
    applications_24h = get_applications_for_24h_prearrival(db)
    logger.info('Total 24-hour applications to process: %s', len(applications_24h))

    for application in applications_24h:
        try:
            process_application_for_24h_prearrival(application)
        except Exception as e:
            logger.error(
                'Error processing 24h application %s: %s', application.id, str(e)
            )
            continue

    logger.info('Finished pre-arrival email process')


def main():
    if settings.ENVIRONMENT != Environment.PRODUCTION:
        logger.info(
            'Not running pre-arrival email process in %s environment',
            settings.ENVIRONMENT,
        )
        return

    with SessionLocal() as db:
        send_prearrival_emails(db)
    logger.info('Pre-arrival email process completed')


if __name__ == '__main__':
    while True:
        try:
            main()
        except Exception as e:
            logger.error('Error in pre-arrival email process: %s', e)
        time.sleep(10 * 60 * 60)
