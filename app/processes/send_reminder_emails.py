import json
import time
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy.orm import Session

from app.api.applications.crud import application as application_crud
from app.api.applications.models import Application
from app.api.applications.schemas import ApplicationFilter, ApplicationStatus
from app.api.email_logs.crud import email_log as email_log_crud
from app.api.email_logs.models import EmailLog
from app.api.email_logs.schemas import EmailStatus
from app.api.popup_city.crud import popup_city as popup_city_crud
from app.api.popup_city.models import EmailTemplate
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logger import logger
from app.core.utils import current_time


class ReminderEvent(str, Enum):
    PURCHASE_REMINDER = 'purchase-reminder'
    APPLICATION_IN_DRAFT = 'application-in-draft'


def _send_reminder_email(
    application: Application,
    email_template: EmailTemplate,
    freq: str,
):
    params = {
        'first_name': application.first_name,
        'ticketing_url': settings.FRONTEND_URL,
        'freq': freq,
    }

    email_log_crud.send_mail(
        application.email,
        event=email_template.event,
        popup_city=application.popup_city,
        params=params,
        entity_type='application',
        entity_id=application.id,
        spice=application.citizen.spice,
        citizen_id=application.citizen_id,
        popup_slug=application.popup_city.slug,
    )


def _get_frequency_timedelta(f: str) -> timedelta:
    if f.endswith('m'):
        return timedelta(minutes=int(f[:-1]))
    elif f.endswith('h'):
        return timedelta(hours=int(f[:-1]))
    elif f.endswith('d'):
        return timedelta(days=int(f[:-1]))
    elif f.endswith('w'):
        return timedelta(weeks=int(f[:-1]))
    raise ValueError(f'Invalid frequency: {f}')


def process_application_reminders(
    db: Session,
    application: Application,
    email_template: EmailTemplate,
) -> None:
    used_frequencies = get_used_frequencies(db, application.id, email_template.template)
    from_date = get_reminder_start_date(application, email_template.event)
    if email_template.event == ReminderEvent.PURCHASE_REMINDER:
        if any(payment.status == 'approved' for payment in application.payments):
            logger.info('Application %s has a paid payment', application.id)
            return

    logger.info(
        'Sending reminder emails for application %s, frequency %s',
        application.id,
        email_template.frequency,
    )
    for frequency in email_template.frequency.split(','):
        freq_delta = _get_frequency_timedelta(frequency)
        if freq_delta in used_frequencies:
            logger.info('Email already sent for frequency: %s', frequency)
            continue

        if is_reminder_due(from_date, freq_delta):
            _send_reminder_email(application, email_template, frequency)


def get_used_frequencies(
    db: Session, application_id: int, template_name: str
) -> list[timedelta]:
    """Get list of frequencies for which emails have already been sent."""
    email_logs = (
        db.query(EmailLog)
        .filter(
            EmailLog.entity_id == application_id,
            EmailLog.entity_type == 'application',
            EmailLog.template == template_name,
            EmailLog.status == EmailStatus.SUCCESS,
        )
        .all()
    )

    return [
        _get_frequency_timedelta(params['freq'])
        for log in email_logs
        if log.params and (params := json.loads(log.params)).get('freq')
    ]


def get_reminder_start_date(
    application: Application,
    event: ReminderEvent,
) -> datetime:
    """Determine the start date for reminder calculations."""
    base_date = datetime(2025, 1, 29, 0, 0)
    if event == ReminderEvent.PURCHASE_REMINDER:
        if not application.accepted_at:
            return base_date
        return max(base_date, application.accepted_at)
    if event == ReminderEvent.APPLICATION_IN_DRAFT:
        if not application.created_at:
            return base_date
        return max(base_date, application.created_at)
    raise ValueError(f'Invalid event: {event}')


def get_application_status(event: ReminderEvent) -> ApplicationStatus:
    if event == ReminderEvent.PURCHASE_REMINDER:
        return ApplicationStatus.ACCEPTED
    if event == ReminderEvent.APPLICATION_IN_DRAFT:
        return ApplicationStatus.DRAFT
    raise ValueError(f'Invalid event: {event}')


def is_reminder_due(from_date: datetime, frequency: timedelta) -> bool:
    """Check if a reminder is due within the next 24 hours."""
    _current_time = current_time()
    reminder_time = from_date + frequency
    return _current_time - timedelta(hours=1) < reminder_time < _current_time


def send_reminder_email(db: Session, email_template: EmailTemplate):
    popup_city_id = email_template.popup_city_id
    skip = 0
    limit = 1000
    while True:
        applications = application_crud.find(
            db,
            filters=ApplicationFilter(
                popup_city_id=popup_city_id,
                status=get_application_status(email_template.event),
            ),
            skip=skip,
            limit=limit,
        )
        logger.info(
            f'Found {len(applications)} applications for popup city {popup_city_id}'
        )
        for application in applications:
            process_application_reminders(db, application, email_template)
        skip += limit
        if len(applications) < limit:
            break


def main():
    with SessionLocal() as db:
        templates = popup_city_crud.get_reminder_templates(db)
        logger.info(f'Found {len(templates)} reminder templates')
        for template in templates:
            logger.info(
                'Sending reminder email for popup city %s',
                template.popup_city_id,
            )
            send_reminder_email(db, template)


if __name__ == '__main__':
    logger.info('Starting reminder email process')
    main()
    logger.info('Reminder email process completed')
    time.sleep(5 * 60)
