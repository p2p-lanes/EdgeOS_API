import csv
import json
import os
from datetime import datetime

from sqlalchemy.orm import Session

from app.api.applications import crud as application_crud
from app.api.applications import schemas as app_schemas
from app.api.citizens import crud as citizen_crud
from app.api.citizens import schemas as citizen_schemas
from app.api.citizens.models import Citizen
from app.api.popup_city import crud as popup_crud
from app.api.popup_city import schemas as popup_schemas
from app.api.popup_city.models import EmailTemplate, PopUpCity
from app.api.products import crud as product_crud
from app.api.products import schemas as product_schemas
from app.core.config import settings
from app.core.database import SessionLocal, create_db
from app.core.security import SYSTEM_TOKEN, TokenData


def load_popup_city_json(json_path: str):
    with open(json_path, 'r') as f:
        data = json.load(f)
    # Parse date strings to datetime objects
    data['start_date'] = datetime.fromisoformat(data['start_date'])
    data['end_date'] = datetime.fromisoformat(data['end_date'])
    return data


def create_popup_city(db: Session, popup_data: dict):
    print('Creating PopUpCity...')
    popup_schema = popup_schemas.PopUpCityCreate(**popup_data)
    popup_city = popup_crud.popup_city.get_by_name(db, popup_schema.name)
    if not popup_city:
        popup_city = popup_crud.popup_city.create(db, popup_schema, SYSTEM_TOKEN)
    print(f'PopUpCity created: {popup_city.id} - {popup_city.name}')
    return popup_city


def populate_email_templates(db: Session, popup_city: PopUpCity):
    print('Populating email templates...')
    csv_path = os.path.join(os.path.dirname(__file__), 'email_templates.csv')
    with open(csv_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            event = row['event']
            template = row['template']
            frequency = row.get('frequency')
            exists = (
                db.query(EmailTemplate)
                .filter_by(popup_city_id=popup_city.id, event=event)
                .first()
            )
            if not exists:
                email_template = EmailTemplate(
                    popup_city_id=popup_city.id,
                    event=event,
                    template=template,
                    frequency=frequency,
                )
                db.add(email_template)
                print(f'Added email template: {event} -> {template}')
            else:
                print(f'Email template already exists for event: {event}')
        db.commit()


def read_citizen_applications_csv(csv_path: str):
    """Read combined citizen and application data from CSV."""
    with open(csv_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        return list(reader)


def get_or_create_citizen(db: Session, row: dict):
    """Create a citizen if not exists, return the citizen object."""
    primary_email = row['primary_email'].lower().strip()
    citizen = citizen_crud.citizen.get_by_email(db, primary_email)
    if citizen:
        print(f'Citizen already exists: {citizen.primary_email}')
        return citizen

    citizen_data = citizen_schemas.CitizenCreate(
        primary_email=primary_email,
        first_name=row['first_name'],
        last_name=row['last_name'],
        telegram=row['telegram'],
        gender=row['gender'],
        role=row['role'],
    )
    citizen = citizen_crud.citizen.create(db, citizen_data, SYSTEM_TOKEN)
    print(f'Citizen created: {citizen.id} - {citizen.primary_email}')
    return citizen


def create_application_for_citizen(
    db: Session, row: dict, citizen: Citizen, popup_city: PopUpCity
):
    """Create an application for the citizen with status DRAFT."""
    existing = (
        db.query(application_crud.models.Application)
        .filter_by(citizen_id=citizen.id, popup_city_id=popup_city.id)
        .first()
    )
    if existing:
        print(f'Application already exists for {citizen.primary_email}')
        return

    app_data = app_schemas.ApplicationCreate(
        first_name=citizen.first_name,
        last_name=citizen.last_name,
        telegram=citizen.telegram,
        organization=row['organization'],
        role=row['app_role'],
        gender=row['app_gender'],
        age=row['age'],
        residence=row['residence'],
        local_resident=row['local_resident'].lower() == 'true',
        area_of_expertise=row['area_of_expertise'],
        status=app_schemas.ApplicationStatus.DRAFT,
        popup_city_id=popup_city.id,
        citizen_id=citizen.id,
    )
    token = TokenData(citizen_id=citizen.id, email=citizen.primary_email)
    application = application_crud.application.create(db, app_data, token)
    print(f'Application created: {application.id} for {citizen.primary_email}')


def process_citizens_and_applications(
    db: Session, popup_city: PopUpCity, csv_path: str
):
    rows = read_citizen_applications_csv(csv_path)
    for row in rows:
        citizen = get_or_create_citizen(db, row)
        create_application_for_citizen(db, row, citizen, popup_city)


def read_products_csv(csv_path: str):
    with open(csv_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        return list(reader)


def parse_bool(val):
    if isinstance(val, bool):
        return val
    if val is None or val == '':
        return False
    return str(val).strip().lower() == 'true'


def parse_float(val):
    try:
        return float(val) if val not in (None, '', 'None') else None
    except Exception:
        return None


def parse_datetime(val):
    if not val or val.strip() == '':
        return None
    try:
        # Try ISO first
        return datetime.fromisoformat(val)
    except Exception:
        # Try common format
        try:
            return datetime.strptime(val, '%Y-%m-%d %H:%M:%S')
        except Exception:
            return None


def populate_products(db: Session, popup_city: PopUpCity):
    print('Populating products...')
    csv_path = os.path.join(os.path.dirname(__file__), 'products.csv')
    rows = read_products_csv(csv_path)
    for row in rows:
        # Check if product already exists by slug and popup_city_id
        exists = (
            db.query(product_crud.models.Product)
            .filter_by(slug=row['slug'], popup_city_id=popup_city.id)
            .first()
        )
        if exists:
            print(f'Product already exists: {row["slug"]} ({popup_city.id})')
            continue
        product_data = product_schemas.ProductCreate(
            name=row.get('name'),
            slug=row.get('slug'),
            price=parse_float(row.get('price')),
            compare_price=parse_float(row.get('compare_price')),
            popup_city_id=popup_city.id,
            description=row.get('description') or None,
            category=row.get('category') or None,
            attendee_category=row.get('attendee_category') or None,
            start_date=parse_datetime(row.get('start_date')),
            end_date=parse_datetime(row.get('end_date')),
            is_active=parse_bool(row.get('is_active')),
            exclusive=parse_bool(row.get('exclusive')),
        )
        product_crud.product.create(db, product_data, SYSTEM_TOKEN)
        print(f'Added product: {row.get("name")} ({row.get("slug")})')
    db.commit()


def main():
    create_db()
    db = SessionLocal()
    try:
        print('\nDatabase Connection Information:')
        print('Database Type: PostgreSQL')
        print(f'Host: {settings.DB_HOST}')
        print(f'Port: {settings.DB_PORT}')
        print(f'Database Name: {settings.DB_NAME}')
        print(f'Username: {settings.DB_USERNAME}')

        print('\nThis script will create demo data in the database:')
        print('1. A PopUpCity from popup_city.json')
        print('2. Citizens and Applications from citizen_applications.csv')

        confirm = input('Do you want to proceed? (y/N): ')
        if confirm.lower() != 'y':
            print('Operation cancelled')
            return

        json_path = os.path.join(os.path.dirname(__file__), 'popup_city.json')
        popup_data = load_popup_city_json(json_path)
        popup_city = create_popup_city(db, popup_data)
        populate_email_templates(db, popup_city)
        populate_products(db, popup_city)
        csv_path = os.path.join(os.path.dirname(__file__), 'citizen_applications.csv')
        process_citizens_and_applications(db, popup_city, csv_path)
    finally:
        db.close()


if __name__ == '__main__':
    main()
