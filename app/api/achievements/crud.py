from datetime import datetime, time
from typing import List, Optional

import requests
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.api.achievements.schemas import BadgeCode

from app.api.achievements import models, schemas
from app.api.base_crud import CRUDBase
from app.api.citizens import models as citizen_models
from app.core.config import settings
from app.core.logger import logger
from app.core.security import SYSTEM_TOKEN, TokenData
from app.core.utils import current_time

MAX_ACHIEVEMENTS_PER_DAY = 3


class CRUDAchievement(
    CRUDBase[models.Achievement, schemas.AchievementCreate, schemas.AchievementCreate]
):
    def create(
        self,
        db: Session,
        obj: schemas.AchievementCreate,
        user: Optional[TokenData] = None,
    ) -> models.Achievement:
        """Create a new achievement with automatic sent_at timestamp"""
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail='Authentication required to create achievements',
            )
        # Add the sent_at timestamp and sender_id from user token
        obj_data = obj.model_dump()
        obj_data['sent_at'] = current_time()
        obj_data['sender_id'] = user.citizen_id
        if obj_data['message'] and len(obj_data['message']) > 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Message must be less than 100 characters',
            )

        today_start = datetime.combine(obj_data['sent_at'].date(), time.min)
        today_end = datetime.combine(obj_data['sent_at'].date(), time.max)

        daily_count = self._count_daily_achievements(
            db=db,
            sender_id=obj_data['sender_id'],
            start=today_start,
            end=today_end,
        )

        if daily_count >= MAX_ACHIEVEMENTS_PER_DAY:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='You have reached the maximum number of achievements per day',
            )

        # Use the base class create method with AchievementBase schema
        achievement = super().create(db=db, obj=schemas.AchievementBase(**obj_data))  # type: ignore[arg-type]

        receiver_id = int(obj_data['receiver_id'])
        sender_id = int(obj_data['sender_id'])
        receiver_citizen = (
            db.query(citizen_models.Citizen)
            .filter(citizen_models.Citizen.id == receiver_id)
            .first()
        )
        sender_citizen = (
            db.query(citizen_models.Citizen)
            .filter(citizen_models.Citizen.id == sender_id)
            .first()
        )

        if receiver_citizen and receiver_citizen.world_address:
            self.send_world_app_notification(
                db=db,
                reciever_adress=receiver_citizen.world_address,
                receiver=receiver_citizen,
                sender=sender_citizen,
                achievement_type=obj_data['achievement_type'],
            )
        else:
            logger.info('No citizen found or no world_address')

        self.send_telegram_notification(
            receiver=receiver_citizen,
            sender=sender_citizen,
            obj_data=obj_data,
        )

        return achievement

    def create_badge(
        self, db: Session, obj: schemas.AchievementCreate, user: TokenData
    ) -> models.Achievement:
        """Create a new badge achievement"""
        # Validate badge_type is provided and valid
        if obj.badge_type is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='badge_type is required when achievement_type is "badge"',
            )

        if obj.badge_type not in [code.value for code in BadgeCode]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Invalid badge_type. Must be one of the valid badge codes.',
            )
        else:
            obj.badge_type = BadgeCode(obj.badge_type).name

        obj_data = obj.model_dump()
        obj_data['sent_at'] = current_time()

        logger.info(obj_data)
        return super().create(db=db, obj=schemas.AchievementBase(**obj_data))  # type: ignore[arg-type]

    def _check_permission(self, db_obj: models.Achievement, user: TokenData) -> bool:
        """Check if user can access this achievement"""
        return user == SYSTEM_TOKEN

    def _count_daily_achievements(
        self,
        db: Session,
        sender_id: int,
        start: datetime,
        end: datetime,
    ) -> int:
        """Count achievements sent by a user within a date range."""
        return (
            db.query(self.model)
            .filter(
                self.model.sender_id == sender_id,
                self.model.sent_at >= start,
                self.model.sent_at <= end,
            )
            .count()
        )

    def get_user_achievements(
        self,
        db: Session,
        user: TokenData,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[schemas.AchievementFilter] = None,
        sort_by: str = 'sent_at',
        sort_order: str = 'desc',
    ) -> schemas.AchievementResponse:
        """Get achievements sent and received by a user."""
        citizen_id = user.citizen_id

        # Get sent achievements with receiver citizen data
        sent_achievements_with_citizens = (
            db.query(self.model, citizen_models.Citizen)
            .join(
                citizen_models.Citizen,
                self.model.receiver_id == citizen_models.Citizen.id,
            )
            .filter(self.model.sender_id == citizen_id)
            .offset(skip)
            .limit(limit)
            .all()
        )

        # Get received achievements with sender citizen data (using LEFT JOIN to include NULL sender_id)
        received_achievements_with_citizens = (
            db.query(self.model, citizen_models.Citizen)
            .outerjoin(
                citizen_models.Citizen,
                self.model.sender_id == citizen_models.Citizen.id,
            )
            .filter(self.model.receiver_id == citizen_id)
            .offset(skip)
            .limit(limit)
            .all()
        )

        # Structure the sent achievements data to include receiver info
        sent_achievements = []
        for achievement, citizen in sent_achievements_with_citizens:
            achievement_dict = {
                'achievement': achievement,
                'citizen': {
                    'id': citizen.id,
                    'first_name': citizen.first_name,
                    'last_name': citizen.last_name,
                    'primary_email': citizen.primary_email,
                    'world_address': citizen.world_address,
                },
            }
            sent_achievements.append(achievement_dict)

        # Structure the received achievements data to include sender info
        received_achievements = []
        for achievement, citizen in received_achievements_with_citizens:
            if citizen is not None:
                # Achievement has a sender
                achievement_dict = {
                    'achievement': achievement,
                    'citizen': {
                        'id': citizen.id,
                        'first_name': citizen.first_name,
                        'last_name': citizen.last_name,
                        'primary_email': citizen.primary_email,
                        'world_address': citizen.world_address,
                    },
                }
            else:
                # Achievement has no sender (sender_id is NULL)
                achievement_dict = {
                    'achievement': achievement,
                    'citizen': None,
                }
            received_achievements.append(achievement_dict)

        return schemas.AchievementResponse(
            sent_achievements=sent_achievements,
            received_achievements=received_achievements,
        )

    def get_by_receiver(
        self, db: Session, receiver_id: int, user: Optional[TokenData] = None
    ) -> List[models.Achievement]:
        """Get all achievements for a specific receiver application"""
        query = db.query(self.model).filter(self.model.receiver_id == receiver_id)
        return query.order_by(self.model.sent_at.desc()).all()

    def get_by_sender(
        self, db: Session, sender_id: int, user: Optional[TokenData] = None
    ) -> List[models.Achievement]:
        """Get all achievements sent by a specific application"""
        query = db.query(self.model).filter(self.model.sender_id == sender_id)
        return query.order_by(self.model.sent_at.desc()).all()

    def send_world_app_notification(
        self,
        db: Session,
        reciever_adress: str,
        receiver: citizen_models.Citizen,
        sender: citizen_models.Citizen,
        achievement_type: str,
    ) -> bool:
        """Send a notification to the world app"""
        logger.info('Sending notification to %s', reciever_adress)
        # Send a notification to the world app
        url = 'https://developer.worldcoin.org/api/v2/minikit/send-notification'
        headers = {
            'Authorization': f'Bearer {settings.WORLD_EDGE_APP_TOKEN}',
            'Content-Type': 'application/json',
        }
        message = f'{sender.first_name} {sender.last_name} has sent you {"an" if achievement_type == "achievement" else "a"} {achievement_type}!'
        print(message)
        data = {
            'app_id': settings.WORLD_EDGE_APP_ID,
            'wallet_addresses': [reciever_adress],
            'mini_app_path': f'worldapp://mini-app?app_id={settings.WORLD_EDGE_APP_ID}',
            'localisations': [
                {
                    'language': 'en',
                    'title': f'{sender.first_name} sent you a star',
                    'message': message,
                }
            ],
        }
        response = requests.post(url, headers=headers, json=data)
        logger.info('Notification sent to %s', response.json())
        return response.json()

    def send_telegram_notification(
        self,
        receiver: citizen_models.Citizen,
        sender: citizen_models.Citizen,
        obj_data: Optional[dict] = None,
    ) -> dict:
        """Send a notification via Telegram"""
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
            logger.warning('Telegram bot token or chat ID not configured')
            return {'status': 'error', 'message': 'Telegram not configured'}

        # Get privacy from obj_data, default to "public"
        privacy = obj_data.get('privacy') if obj_data else None

        # Build the message
        if privacy:
            # ✅ hides both sender and receiver
            notification_text = 'Someone sent gratitude (privately) ⭐️'
        else:
            # ✅ public
            # Use "Anonymous" only if both first_name and last_name are None
            if sender and (sender.first_name or sender.last_name):
                name_parts = []
                if sender.first_name:
                    name_parts.append(sender.first_name)
                if sender.last_name:
                    name_parts.append(sender.last_name)
                sender_name = ' '.join(name_parts)
            else:
                sender_name = 'Anonymous'

            if receiver and (receiver.first_name or receiver.last_name):
                name_parts = []
                if receiver.first_name:
                    name_parts.append(receiver.first_name)
                if receiver.last_name:
                    name_parts.append(receiver.last_name)
                receiver_name = ' '.join(name_parts)
            else:
                receiver_name = 'Anonymous'

            notification_text = f'{sender_name} sent gratitude to {receiver_name} ⭐️'

        logger.info(
            'Sending Telegram notification for achievement from %s to %s',
            sender.first_name if sender else 'Unknown',
            receiver.first_name if receiver else 'Unknown',
        )

        # Send the message via Telegram Bot API
        url = f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage'
        data = {
            'chat_id': settings.TELEGRAM_CHAT_ID,
            'message_thread_id': settings.TELEGRAM_MESSAGE_THREAD_ID,
            'text': notification_text,
        }

        try:
            response = requests.post(url, json=data, timeout=10)
            response.raise_for_status()
            logger.info('Telegram notification sent successfully: %s', response.json())
            return {'status': 'success', 'response': response.json()}
        except requests.exceptions.HTTPError as e:
            error_detail = 'Unknown error'
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    logger.error(
                        'Failed to send Telegram notification. Status: %s, Response: %s',
                        e.response.status_code,
                        error_detail,
                    )
                except:
                    error_detail = e.response.text
                    logger.error(
                        'Failed to send Telegram notification. Status: %s, Response: %s',
                        e.response.status_code,
                        error_detail,
                    )
            else:
                logger.error('Failed to send Telegram notification: %s', str(e))
            return {'status': 'error', 'message': str(e), 'detail': error_detail}
        except requests.exceptions.RequestException as e:
            logger.error('Failed to send Telegram notification: %s', str(e))
            return {'status': 'error', 'message': str(e)}


achievement = CRUDAchievement(models.Achievement)
