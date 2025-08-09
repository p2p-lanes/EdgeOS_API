from sqlalchemy.orm import Session

from app.api.applications.models import Application
from app.api.attendees.models import Attendee
from app.api.email_logs.crud import email_log
from app.api.email_logs.models import EmailLog
from app.core import models
from app.core.database import SessionLocal

EDGE_ESMERALDA_2025_ID = 4


def get_attendees(db: Session, email_sent: list[int]):
    query = (
        db.query(Attendee)
        .join(Attendee.application)
        .filter(
            Application.popup_city_id == EDGE_ESMERALDA_2025_ID,
            Attendee.poap_url.is_not(None),
            Attendee.poap_url != '',
            Attendee.email.is_not(None),
            Attendee.email != '',
            Attendee.id.notin_(email_sent),
        )
    )
    return query.all()


def get_email_sent(db: Session, event: str, entity_type: str = 'attendee'):
    """Return distinct entity_id values for emails that have been sent."""
    query = (
        db.query(EmailLog.entity_id)
        .filter(
            EmailLog.entity_type == entity_type,
            EmailLog.event == event,
            EmailLog.entity_id.is_not(None),
            EmailLog.status == 'success',
        )
        .distinct()
    )
    return [result[0] for result in query.all()]


def main():
    with SessionLocal() as db:
        event = 'digital-collectible'
        email_sent = get_email_sent(db, event)
        print(f'{len(email_sent)} emails have been sent')
        attendees = get_attendees(db, email_sent)
        print(f'Sending emails to {len(attendees)} attendees')
        for attendee in attendees:
            print('name:', attendee.name)
            print('email:', attendee.email)
            print('poap_url:', attendee.poap_url)
            if not attendee.poap_url.strip() or not attendee.email.strip():
                print('skipping attendee\n')
                continue
            email_log.send_mail(
                receiver_mail=attendee.email,
                event=event,
                params={
                    'first_name': attendee.name,
                    'poap_link': attendee.poap_url,
                },
                popup_city=attendee.application.popup_city,
                entity_type='attendee',
                entity_id=attendee.id,
                citizen_id=attendee.application.citizen_id,
            )
            print()


if __name__ == '__main__':
    main()
