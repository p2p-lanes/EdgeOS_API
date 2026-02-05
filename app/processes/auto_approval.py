import time
from datetime import timedelta

import requests
from sqlalchemy.orm import Session

from app.api.applications.models import Application
from app.api.applications.schemas import ApplicationStatus
from app.api.popup_city.models import PopUpCity
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logger import logger
from app.core.utils import current_time


def process_popup_city(db: Session, popup_city: PopUpCity):
    auto_approval_time = popup_city.auto_approval_time
    if not auto_approval_time:
        return

    applications = (
        db.query(Application)
        .filter(Application.popup_city_id == popup_city.id)
        .filter(Application.status == ApplicationStatus.IN_REVIEW)
        .filter(
            Application.submitted_at
            < current_time() - timedelta(minutes=auto_approval_time)
        )
        .all()
    )

    for application in applications:
        logger.info('Approving application %s %s', application.id, application.email)
        data = {
            'id': application.id,
            'auto_approved': True,
        }
        url = f'{settings.NOCODB_URL}/api/v2/tables/{settings.APPLICATIONS_TABLE_ID}/records'
        headers = {
            'accept': 'application/json',
            'xc-token': settings.NOCODB_TOKEN,
            'Content-Type': 'application/json',
        }
        response = requests.patch(url, headers=headers, json=data)
        if response.status_code != 200:
            logger.error(
                'Error approving application %s %s', application.id, application.email
            )
            logger.error(response.json())


def main():
    with SessionLocal() as db:
        popup_cities = (
            db.query(PopUpCity).filter(PopUpCity.auto_approval_time.isnot(None)).all()
        )
        for popup_city in popup_cities:
            logger.info(
                'Processing popup city %s with auto approval time %s',
                popup_city.name,
                popup_city.auto_approval_time,
            )
            process_popup_city(db, popup_city)


if __name__ == '__main__':
    logger.info('Starting auto approval process...')
    main()
    logger.info('Auto approval process completed. Sleeping for 60 seconds...')
    time.sleep(60)
