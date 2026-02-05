from typing import Optional

import requests

from app.api.email_logs.schemas import EmailAttachment, EmailStatus
from app.core.config import Environment, settings
from app.core.logger import logger


def send_mail(
    receiver_mail: str,
    *,
    template: str,
    params: dict,
    attachments: Optional[list[EmailAttachment]] = None,
):
    logger.info('sending %s email to %s', template, receiver_mail)
    url = 'https://api.postmarkapp.com/email/withTemplate'
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'X-Postmark-Server-Token': settings.POSTMARK_API_TOKEN,
    }
    data = {
        'From': f'{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM_ADDRESS}>',
        'To': receiver_mail,
        'TemplateAlias': template,
        'TemplateModel': params,
    }
    if settings.EMAIL_REPLY_TO:
        data['ReplyTo'] = settings.EMAIL_REPLY_TO

    if attachments:
        data['Attachments'] = [a.model_dump(by_alias=True) for a in attachments]

    if settings.ENVIRONMENT == Environment.TEST:
        return {'status': EmailStatus.SUCCESS}

    response = requests.post(url, json=data, headers=headers)
    response.raise_for_status()

    return {'status': EmailStatus.SUCCESS, 'response': response.json()}
