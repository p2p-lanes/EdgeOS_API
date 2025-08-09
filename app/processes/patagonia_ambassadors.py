import random
import string
import urllib.parse

from sqlalchemy.orm import joinedload

from app.api.applications.models import Application
from app.api.attendees.models import Attendee, AttendeeProduct
from app.api.coupon_codes.models import CouponCode
from app.api.email_logs.crud import email_log as email_log_crud
from app.api.email_logs.models import EmailLog
from app.api.email_logs.schemas import EmailStatus
from app.api.groups.models import Group
from app.core import models
from app.core.config import settings
from app.core.database import SessionLocal

PATAGONIA_POPUP_CITY_ID = 2
IMPORTED_POPUPS = [1, 5]
DISCOUNT_PERCENTAGE = 20

EMAIL_DOMAINS = [
    '@simplefi.tech',
    '@muvinai.com',
    '@edgecity.live',
]
EMAILS = [
    'timour.kosters@gmail.com',
    'jwmares@gmail.com',
    't@timour.xyz',
    'justin@monaverse.com',
    'timour.kosters@gmail.com',
]


def generate_random_string(length=8):
    return ''.join(random.choices(string.ascii_lowercase, k=length))


def main():
    print('Starting process...')
    with SessionLocal() as session:
        print('Querying applications...')
        # Find emails that have already received the ambassador email successfully
        sent_rows = (
            session.query(EmailLog.receiver_email)
            .filter(EmailLog.event == 'ambassador-program-patagonia')
            .all()
        )
        already_sent_emails = {row[0] for row in sent_rows}
        print(f'Found {len(already_sent_emails)} emails already sent for this template')

        # Find existing ambassador groups slugs
        ambassador_groups = (
            session.query(Group.slug)
            .filter(
                Group.is_ambassador_group.is_(True),
                Group.popup_city_id == PATAGONIA_POPUP_CITY_ID,
            )
            .all()
        )
        ambassador_groups_slugs = {group[0] for group in ambassador_groups}
        print(f'Found {len(ambassador_groups_slugs)} ambassador groups')

        # Query 1: Applications that have attendees with products
        applications_with_products = (
            session.query(Application)
            .join(Application.attendees)
            .join(Attendee.attendee_products)
            .join(AttendeeProduct.product)
            .options(
                joinedload(Application.attendees)
                .joinedload(Attendee.attendee_products)
                .joinedload(AttendeeProduct.product)
            )
            .filter(Application.email.notin_(already_sent_emails))
            .distinct()
        )

        # Query 2: Applications from imported popups (regardless of products)
        applications_from_imported_popups = (
            session.query(Application)
            .filter(
                Application.popup_city_id.in_(IMPORTED_POPUPS),
                Application.email.notin_(already_sent_emails),
            )
            .distinct()
        )

        # Combine both queries using union
        applications = applications_with_products.union(
            applications_from_imported_popups
        ).all()

        print(f'Found {len(applications)} applications:\n')

        ambassadors = {}

        for application in applications:
            if (
                any(application.email.endswith(domain) for domain in EMAIL_DOMAINS)
                or application.email in EMAILS
                or application.email in already_sent_emails
            ):
                continue

            print(application.email)

            ambassadors[application.citizen_id] = {
                'first_name': application.first_name,
                'last_name': application.last_name,
                'email': application.email,
            }

        print('Total ambassadors:', len(ambassadors))

        for citizen_id, data in ambassadors.items():
            first_name = data['first_name']
            last_name = data['last_name']
            email = data['email']

            print(f'Processing {email}')

            # Create group with name and description
            slug = 'ecp25-' + generate_random_string(length=4)
            while slug in ambassador_groups_slugs:
                print(f'Slug {slug} already exists, generating new one')
                slug = 'ecp25-' + generate_random_string(length=4)

            ambassador_groups_slugs.add(slug)

            invite_link = urllib.parse.urljoin(
                settings.FRONTEND_URL, f'/edge-patagonia/invite/{slug}'
            )
            print(f'Invite link: {invite_link}')
            group = Group(
                name=f'{first_name} {last_name} Invite List',
                slug=slug,
                description='You\'re invited to skip the application process and proceed directly to checkout. Provide your information below to secure your ticket(s) to <a href="https://www.edgecity.live/patagonia" target="_blank" style="color: #3366FF;">Edge Patagonia 2025</a>!',
                discount_percentage=DISCOUNT_PERCENTAGE,
                popup_city_id=PATAGONIA_POPUP_CITY_ID,
                max_members=None,
                is_ambassador_group=True,
                welcome_message=f'This is a personal invite link from {first_name} {last_name}.',
            )
            session.add(group)
            session.commit()

            # Create coupon code
            coupon_code = CouponCode(
                code=slug.upper(),
                popup_city_id=PATAGONIA_POPUP_CITY_ID,
                discount_value=DISCOUNT_PERCENTAGE,
                is_active=True,
                description=email,
            )
            session.add(coupon_code)
            session.commit()

            try:
                email_log_crud.send_mail(
                    receiver_mail=email,
                    event='ambassador-program-patagonia',
                    params={
                        'first_name': first_name,
                        'invite_link': invite_link,
                    },
                    entity_type='citizen',
                    entity_id=citizen_id,
                    citizen_id=citizen_id,
                )
            except Exception as e:
                print(f'Error sending email: {e}')


if __name__ == '__main__':
    main()
