import urllib.parse
from datetime import timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from app.api.applications.crud import application as application_crud
from app.api.base_crud import CRUDBase
from app.api.email_logs.crud import email_log as email_log_crud
from app.api.email_logs.schemas import EmailEvent
from app.api.popup_city import models, schemas
from app.core.config import settings
from app.core.logger import logger
from app.core.security import SYSTEM_TOKEN
from app.core.utils import current_time


class CRUDPopUpCity(
    CRUDBase[models.PopUpCity, schemas.PopUpCityCreate, schemas.PopUpCityCreate]
):
    def get_by_name(self, db: Session, name: str) -> Optional[models.PopUpCity]:
        return db.query(self.model).filter(self.model.name == name).first()

    def get_reminder_templates(self, db: Session) -> List[models.EmailTemplate]:
        week_from_now = current_time() + timedelta(days=7)
        return (
            db.query(models.EmailTemplate)
            .join(models.PopUpCity)
            .filter(
                models.EmailTemplate.frequency.isnot(None),
                models.EmailTemplate.frequency != '',
                models.PopUpCity.end_date.isnot(None),
                models.PopUpCity.end_date > week_from_now,
                models.PopUpCity.visible_in_portal,
            )
            .all()
        )

    def send_reminder_emails(self, db: Session, popup_city_id: int) -> None:
        popup = self.get(db=db, id=popup_city_id, user=SYSTEM_TOKEN)
        if not popup:
            raise ValueError(f'Popup city {popup_city_id} not found')

        email_logs = email_log_crud.get_email_logs(
            db,
            EmailEvent.INCREASE_REMINDER,
            timedelta(days=4),
        )
        to_exclude = list({email_log.receiver_email for email_log in email_logs})
        logger.info('Excluding %s emails', len(to_exclude))

        results = application_crud.get_distinct_emails_no_products(
            db,
            popup_city_id,
            exclude_emails=to_exclude,
        )
        logger.info('Found %s emails to send reminder emails to', len(results))
        ticketing_url = urllib.parse.urljoin(
            settings.FRONTEND_URL, f'/portal/{popup.slug}/passes'
        )
        for application in results:
            logger.info('Sending increase reminder email to %s', application.email)
            try:
                email_log_crud.send_mail(
                    receiver_mail=application.email,
                    event=EmailEvent.INCREASE_REMINDER,
                    popup_city=popup,
                    params={
                        'first_name': application.first_name,
                        'ticketing_url': ticketing_url,
                    },
                    entity_type='application',
                    entity_id=application.id,
                )
            except Exception as e:
                logger.error(
                    'Failed to send increase reminder email to %s: %s',
                    application.email,
                    str(e),
                )

        logger.info('Sent %s increase reminder emails', len(results))


popup_city = CRUDPopUpCity(models.PopUpCity)
