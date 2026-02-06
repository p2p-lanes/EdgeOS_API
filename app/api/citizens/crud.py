import base64
import random
from datetime import timedelta
from typing import List, Optional, Union

import requests
from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.access_tokens import schemas as access_token_schemas
from app.api.access_tokens.crud import access_token as access_token_crud
from app.api.account_clusters.crud import get_linked_citizen_ids
from app.api.applications.models import Application
from app.api.base_crud import CRUDBase
from app.api.citizens import models, schemas
from app.api.citizens.schemas import CitizenPoaps, CitizenPoapsByPopup, PoapClaim
from app.api.email_logs.crud import email_log
from app.api.email_logs.schemas import EmailAttachment, EmailEvent
from app.core.cache import TTLCache
from app.core.config import settings
from app.core.edge_mapped import generate_edge_mapped
from app.core.locks import DistributedLock
from app.core.logger import logger
from app.core.security import SYSTEM_TOKEN, TokenData
from app.core.utils import create_spice, current_time
from app.core.world import verify_safe_signature

POAP_TOKEN_ID = 'poap'
POAP_REFRESH_LOCK = DistributedLock('poap_token_refresh')
PROFILE_CACHE = TTLCache(expiry=timedelta(minutes=10))


def _refresh_poap_token():
    url = 'https://auth.accounts.poap.xyz/oauth/token'
    headers = {'Content-Type': 'application/json'}
    data = {
        'audience': 'https://api.poap.tech',
        'grant_type': 'client_credentials',
        'client_id': settings.POAP_CLIENT_ID,
        'client_secret': settings.POAP_CLIENT_SECRET,
    }

    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    access_token = response.json()['access_token']
    expires_in = response.json()['expires_in']
    logger.info('POAP token refreshed. Expires in: %s', expires_in)
    expires_at = current_time() + timedelta(seconds=expires_in)
    return access_token, expires_at


def _get_poap_token(db: Session) -> str:
    poap_token = access_token_crud.get_by_name(db, POAP_TOKEN_ID)
    if not poap_token:
        # If token doesn't exist, acquire lock and create it
        with POAP_REFRESH_LOCK.acquire(db):
            # Check again after acquiring lock in case another process created it
            poap_token = access_token_crud.get_by_name(db, POAP_TOKEN_ID)
            if poap_token and poap_token.value:
                return poap_token.value
            logger.info('POAP token not found, creating new one')
            token, expires_at = _refresh_poap_token()
            update_obj = access_token_schemas.AccessTokenCreate(
                name=POAP_TOKEN_ID, value=token, expires_at=expires_at
            )
            poap_token = access_token_crud.create(db, update_obj)
            logger.info('POAP token created. Expires at: %s', poap_token.expires_at)
    elif poap_token.expires_at and poap_token.expires_at < current_time() + timedelta(
        minutes=10
    ):
        # If token is about to expire, acquire lock and refresh it
        with POAP_REFRESH_LOCK.acquire(db):
            # Check expiration again after acquiring lock in case another process refreshed it
            poap_token = access_token_crud.get_by_name(db, POAP_TOKEN_ID)
            if (
                poap_token
                and poap_token.expires_at
                and poap_token.expires_at >= current_time() + timedelta(minutes=10)
            ):
                return poap_token.value or ''
            if poap_token:
                logger.info(
                    'Refreshing POAP token. Expires at: %s', poap_token.expires_at
                )
            token, expires_at = _refresh_poap_token()
            update_obj = access_token_schemas.AccessTokenUpdate(
                value=token, expires_at=expires_at
            )
            poap_token = access_token_crud.update_by_name(db, POAP_TOKEN_ID, update_obj)
            if poap_token:
                logger.info('POAP token updated. Expires at: %s', poap_token.expires_at)
    return poap_token.value if poap_token and poap_token.value else ''


def _get_poap_qr(qr_hash: str, db: Session):
    poap_token = _get_poap_token(db)
    url = f'https://api.poap.tech/actions/claim-qr?qr_hash={qr_hash}'
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {poap_token}',
        'X-API-Key': settings.POAP_API_KEY,
    }
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        logger.error(
            'Failed to get POAP QR: %s %s', response.status_code, response.text
        )
        return None

    return {
        'claimed': response.json()['claimed'],
        'is_active': response.json()['is_active'],
        'name': response.json()['event']['name'],
        'description': response.json()['event']['description'],
        'image_url': response.json()['event']['image_url'],
    }


class CRUDCitizen(
    CRUDBase[models.Citizen, schemas.CitizenCreate, schemas.CitizenUpdate]
):
    def _check_permission(self, db_obj: models.Citizen, user: TokenData) -> bool:
        return user == SYSTEM_TOKEN or db_obj.id == user.citizen_id

    def find(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[BaseModel] = None,
        user: Optional[TokenData] = None,
        sort_by: str = 'created_at',
        sort_order: str = 'desc',
    ) -> List[models.Citizen]:
        if user:
            if filters is None or not isinstance(filters, schemas.CitizenFilter):
                filters = schemas.CitizenFilter()
            filters.id = user.citizen_id
        return super().find(db, skip, limit, filters, user, sort_by, sort_order)

    def get_by_email(self, db: Session, email: str) -> Optional[models.Citizen]:
        return db.query(self.model).filter(self.model.primary_email == email).first()

    def get_by_world_address(
        self, db: Session, world_address: str
    ) -> Optional[models.Citizen]:
        return (
            db.query(self.model)
            .filter(self.model.world_address == world_address)
            .first()
        )

    def get_or_create(
        self, db: Session, citizen: schemas.CitizenCreate
    ) -> models.Citizen:
        existing_citizen = self.get_by_email(db, citizen.primary_email)
        if existing_citizen:
            return existing_citizen
        logger.info('Citizen not found, creating: %s', citizen)
        return self.create(db, citizen)

    def create(
        self,
        db: Session,
        obj: Union[schemas.CitizenCreate, schemas.InternalCitizenCreate],
        user: Optional[TokenData] = None,
    ) -> models.Citizen:
        to_create = schemas.InternalCitizenCreate(**obj.model_dump())
        to_create.spice = create_spice()
        citizen = super().create(db, to_create)
        return citizen

    def signup(self, db: Session, *, obj: schemas.CitizenCreate) -> models.Citizen:
        citizen = self.create(db, obj)
        email_log.send_login_mail(citizen.primary_email, citizen.spice, citizen.id)
        return citizen

    def authenticate(
        self,
        db: Session,
        *,
        data: schemas.Authenticate,
    ) -> dict:
        email = data.email
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Email is required',
            )

        citizen = self.get_by_email(db, email)

        code = random.randint(100000, 999999) if data.use_code else None
        code_expiration = (
            current_time() + timedelta(minutes=5) if data.use_code else None
        )

        if data.signature and data.world_address:
            if not verify_safe_signature(data.world_address, data.signature):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail='Invalid signature',
                )
            data.world_redirect = True
        else:
            data.world_address = None

        if not citizen:
            if data.source == 'app':
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail='Citizen not found',
                )
            to_create = schemas.InternalCitizenCreate(
                primary_email=email,
                code=code,
                code_expiration=code_expiration,
            )
            citizen = self.create(db, to_create)
        else:
            citizen.spice = create_spice()
            if code:
                citizen.code = code
                citizen.code_expiration = code_expiration
                citizen.third_party_app = None

            db.commit()
            db.refresh(citizen)

        if code:
            # Choose email event based on source
            if data.source == 'app':
                event = EmailEvent.AUTH_CITIZEN_APP.value
            else:
                event = EmailEvent.AUTH_CITIZEN_BY_CODE.value

            email_log.send_mail(
                email,
                event=event,
                popup_slug=data.popup_slug,
                params={'code': code, 'email': email},
                spice=citizen.spice,
                entity_type='citizen',
                entity_id=citizen.id,
                citizen_id=citizen.id,
            )
        else:
            email_log.send_login_mail(
                email,
                citizen.spice,
                citizen.id,
                data.popup_slug,
                data.world_redirect,
                source=data.source,
            )

        return {'message': 'Mail sent successfully'}

    def authenticate_third_party(
        self,
        db: Session,
        *,
        email: str,
        app_name: str,
    ) -> dict:
        logger.info('Authenticate third-party request: %s %s', email, app_name)
        citizen = self.get_by_email(db, email)
        if not citizen:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Citizen not found',
            )

        citizen.code = random.randint(100000, 999999)
        citizen.code_expiration = current_time() + timedelta(minutes=5)
        citizen.third_party_app = app_name
        db.commit()
        db.refresh(citizen)

        params = {
            'code': citizen.code,
            'email': email,
            'app_name': app_name,
        }
        email_log.send_mail(
            email,
            event=EmailEvent.AUTH_CITIZEN_THIRD_PARTY.value,
            params=params,
            entity_type='citizen',
            entity_id=citizen.id,
            citizen_id=citizen.id,
        )

        return {'message': 'Mail sent successfully'}

    def logout(
        self,
        db: Session,
        *,
        user: TokenData,
    ) -> dict:
        # Get the citizen using the authenticated user's ID
        logger.info('Logging out citizen: %s', user)
        citizen = self.get(db, user.citizen_id, user)
        logger.info('Logging out citizen: %s', citizen.primary_email)
        if citizen.world_address:
            logger.info('Clearing world address for citizen: %s', citizen.world_address)
            citizen.world_address = None
            db.commit()
            db.refresh(citizen)

        return {'message': 'Logged out successfully'}

    def login(
        self,
        db: Session,
        *,
        email: str,
        spice: Optional[str] = None,
        world_address: Optional[str] = None,
        verified_upon_login: Optional[str] = None,
        code: Optional[int] = None,
    ) -> models.Citizen:
        if not spice and not code:
            raise HTTPException(
                status_code=400, detail='Either spice or code must be provided'
            )

        citizen = self.get_by_email(db, email)
        if not citizen:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Citizen not found',
            )
        if spice and citizen.spice != spice:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail='Invalid spice',
            )
        if code:
            if citizen.code != code:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail='Invalid code',
                )
            if (
                citizen.code_expiration is None
                or citizen.code_expiration < current_time()
            ):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail='Code expired',
                )
        if world_address:
            citizen.world_address = world_address
        if verified_upon_login:
            citizen.verified_upon_login = verified_upon_login
        citizen.email_validated = True
        db.commit()
        db.refresh(citizen)
        return citizen

    def get_poaps_from_citizen(self, db: Session, user: TokenData) -> CitizenPoaps:
        citizen: models.Citizen = self.get(db, user.citizen_id, user)

        linked_citizen_ids = get_linked_citizen_ids(db, citizen.id)
        logger.info('Getting POAPs from citizens: %s', linked_citizen_ids)

        # Aggregate applications from ALL linked citizens
        from app.api.applications.models import Application

        all_applications = (
            db.query(Application)
            .filter(Application.citizen_id.in_(linked_citizen_ids))
            .all()
        )

        if len(linked_citizen_ids) == 1:
            emails = [citizen.primary_email] if citizen.primary_email else []
        else:
            emails = [
                c.primary_email
                for c in db.query(models.Citizen)
                .filter(models.Citizen.id.in_(linked_citizen_ids))
                .all()
                if c.primary_email is not None
            ]

        response = CitizenPoaps(emails=emails, results=[])
        processed_poaps = set()
        for application in all_applications:
            poaps = []
            for attendee in application.attendees:
                if attendee.poap_url:
                    qr_hash = attendee.poap_url.split('/')[-1]
                    poap_data = _get_poap_qr(qr_hash, db)
                    if not poap_data:
                        continue
                    key = (
                        attendee.category,
                        attendee.email,
                        application.popup_city_id,
                    )
                    if key in processed_poaps:
                        continue
                    processed_poaps.add(key)
                    poaps.append(
                        PoapClaim(
                            attendee_id=attendee.id,
                            attendee_name=attendee.name,
                            attendee_email=attendee.email,
                            attendee_category=attendee.category,
                            poap_url=attendee.poap_url,
                            poap_name=poap_data['name'],
                            poap_description=poap_data['description'],
                            poap_image_url=poap_data['image_url'],
                            poap_claimed=poap_data['claimed'],
                            poap_is_active=poap_data['is_active'],
                        )
                    )
            if poaps:
                response.results.append(
                    CitizenPoapsByPopup(
                        popup_id=application.popup_city_id,
                        popup_name=application.popup_city.name,
                        poaps=poaps,
                    )
                )

        return response

    def _get_popup_data(self, application: Application) -> Optional[dict]:
        main_attendee = application.get_main_attendee()
        popup = application.popup_city
        if not main_attendee:
            if not application.total_days:
                return None
            return {
                'id': popup.id,
                'popup_name': popup.name,
                'start_date': popup.start_date,
                'end_date': popup.end_date,
                'total_days': application.total_days,
                'location': popup.location,
                'image_url': popup.image_url,
            }

        if not main_attendee.products:
            if not application.total_days:
                return None
            return {
                'id': popup.id,
                'popup_name': popup.name,
                'start_date': popup.start_date,
                'end_date': popup.end_date,
                'total_days': application.total_days,
                'location': popup.location,
                'image_url': popup.image_url,
            }

        total_days = 0
        for product in main_attendee.products:
            if (
                product.start_date
                and product.end_date
                and product.start_date < current_time()
            ):
                end_date = min(product.end_date, current_time())
                total_days += (end_date - product.start_date).days + 1

        return {
            'id': popup.id,
            'popup_name': popup.name,
            'start_date': popup.start_date,
            'end_date': popup.end_date,
            'total_days': min(total_days, (popup.end_date - popup.start_date).days + 1)
            if popup.end_date and popup.start_date
            else total_days,
            'location': application.popup_city.location,
            'image_url': application.popup_city.image_url,
        }

    def invalidate_profile_cache(self, citizen_id: int) -> None:
        """Invalidate the cached profile for a citizen."""
        cache_key = f'citizen_profile:{citizen_id}'
        PROFILE_CACHE.delete(cache_key)
        logger.info('Invalidated profile cache for citizen: %s', citizen_id)

    def get_profile(
        self, db: Session, user: TokenData
    ) -> tuple[models.Citizen, schemas.CitizenProfile]:
        logger.info('Getting profile for citizen: %s', user.citizen_id)
        citizen: models.Citizen = self.get(db, user.citizen_id, user)

        linked_citizen_ids = get_linked_citizen_ids(db, user.citizen_id)
        logger.info('Profile aggregating data from citizens: %s', linked_citizen_ids)

        # Check cache first
        cache_key = f'citizen_profile:{user.citizen_id}'
        cached_p: Optional[schemas.CitizenProfile] = PROFILE_CACHE.get(cache_key)
        if cached_p and len(cached_p.linked_emails) == len(linked_citizen_ids):
            logger.info('Returning cached profile for citizen: %s', user.citizen_id)
            cached_p.edge_mapped_sent = citizen.edge_mapped_sent
            return citizen, cached_p

        # Aggregate applications from ALL linked citizens
        from app.api.applications.models import Application

        all_applications = (
            db.query(Application)
            .filter(Application.citizen_id.in_(linked_citizen_ids))
            .all()
        )

        popups_data = {}
        for application in all_applications:
            logger.info('Getting popup data for application: %s', application.id)
            _popup_data = self._get_popup_data(application)
            if not _popup_data:
                continue
            if (
                _popup_data['id'] in popups_data
                and popups_data[_popup_data['id']]['total_days']
                > _popup_data['total_days']
            ):
                continue
            _popup_data['application'] = {
                'id': application.id,
                'residence': application.residence,
                'personal_goals': application.personal_goals,
            }
            popups_data[_popup_data['id']] = _popup_data

        popups_data = list(popups_data.values())
        total_days = sum(popup['total_days'] for popup in popups_data)

        # Count the amount of attendees with a payment for the ambassador group
        # Aggregate from ALL linked citizens
        all_linked_citizens = (
            db.query(models.Citizen)
            .filter(models.Citizen.id.in_(linked_citizen_ids))
            .all()
        )

        linked_emails = list({citizen.primary_email for citizen in all_linked_citizens})

        attendee_ids = set()
        for linked_citizen in all_linked_citizens:
            for group in linked_citizen.groups_as_ambassador:
                for application in group.applications:
                    # Skip if the application belongs to any of the linked citizens
                    if application.citizen_id in linked_citizen_ids:
                        continue
                    for payment in application.payments:
                        if payment.group_id != group.id or payment.status != 'approved':
                            continue
                        for product in payment.products_snapshot:
                            attendee_ids.add(product.attendee_id)

        referral_count = len(attendee_ids)
        citizen_data = schemas.Citizen.model_validate(citizen).model_dump()
        profile = schemas.CitizenProfile(
            **citizen_data,
            linked_emails=linked_emails,
            popups=popups_data,
            total_days=total_days,
            referral_count=referral_count,
        )

        # Cache the profile
        PROFILE_CACHE.set(cache_key, profile)
        logger.info('Cached profile for citizen: %s', user.citizen_id)

        return citizen, profile

    def _get_events_count(self, linked_emails: List[str]) -> int:
        """Get the count of events attended by a citizen based on their linked emails.

        Args:
            linked_emails: List of email addresses associated with the citizen

        Returns:
            Number of events attended, or 0 if query fails
        """
        if not linked_emails:
            return 0

        query = """
        query Events($where: events_bool_exp) {
            events(where: $where) {
                id
            }
        }
        """

        variables = {
            'where': {'participants': {'profile': {'email': {'_in': linked_emails}}}}
        }

        try:
            response = requests.post(
                settings.HASURA_URL,
                headers={'Content-Type': 'application/json'},
                json={'query': query, 'variables': variables},
                timeout=10,
            )
            response.raise_for_status()
            result = response.json()

            if 'errors' in result:
                logger.error('Hasura GraphQL error: %s', result['errors'])
                return 0

            events = result.get('data', {}).get('events', [])
            return len(events)

        except requests.RequestException as e:
            logger.error('Failed to fetch events count from Hasura: %s', e)
            return 0
        except Exception as e:
            logger.error('Unexpected error fetching events count: %s', e)
            return 0

    def get_edge_mapped(self, db: Session, user: TokenData) -> str:
        citizen, profile = self.get_profile(db, user)
        popups = [p.popup_name for p in profile.popups]

        events_count = self._get_events_count(profile.linked_emails)

        image_path = generate_edge_mapped(
            popups,
            profile.total_days,
            events_count,
        )
        if not citizen.edge_mapped_sent:
            with open(image_path, 'rb') as image_file:
                image_b64 = base64.b64encode(image_file.read()).decode('utf-8')

            email_log.send_mail(
                citizen.primary_email,
                event=EmailEvent.EDGE_MAPPED_SENT.value,
                params={'first_name': citizen.first_name},
                entity_type='citizen',
                entity_id=citizen.id,
                citizen_id=citizen.id,
                attachments=[
                    EmailAttachment(
                        name='island.png',
                        content_id='cid:island.png',
                        content=image_b64,
                        content_type='image/png',
                    )
                ],
            )
            citizen.edge_mapped_sent = True
            db.commit()
            db.refresh(citizen)

        return image_path


citizen = CRUDCitizen(models.Citizen)
