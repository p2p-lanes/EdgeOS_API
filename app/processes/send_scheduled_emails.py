import time

from app.api.email_logs.crud import email_log
from app.core import models  # noqa: F401
from app.core.database import SessionLocal
from app.core.logger import logger


def send_scheduled_emails():
    logger.info('Sending scheduled emails')
    with SessionLocal() as db:
        email_log.send_scheduled_mails(db)
    logger.info('Scheduled emails sent successfully')


if __name__ == '__main__':
    while True:
        try:
            send_scheduled_emails()
        except Exception as e:
            logger.error('Error sending scheduled emails: %s', e)
        time.sleep(60)
