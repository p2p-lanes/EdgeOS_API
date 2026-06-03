import secrets
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.account_clusters.crud import get_linked_citizen_ids
from app.api.citizens.models import Citizen

from . import models

# Length (in bytes) of the random subscription token. 32 bytes of entropy is plenty
# for a bearer secret and matches the existing attendee-ticket key generation.
_TOKEN_BYTES = 32


def _generate_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def get_by_citizen_id(
    db: Session, citizen_id: int
) -> Optional[models.CalendarSubscription]:
    return (
        db.query(models.CalendarSubscription)
        .filter(models.CalendarSubscription.citizen_id == citizen_id)
        .first()
    )


def get_by_token(db: Session, token: str) -> Optional[models.CalendarSubscription]:
    if not token:
        return None
    return (
        db.query(models.CalendarSubscription)
        .filter(models.CalendarSubscription.token == token)
        .first()
    )


def get_or_create(db: Session, citizen_id: int) -> models.CalendarSubscription:
    """Return the citizen's subscription, creating one on first access."""
    subscription = get_by_citizen_id(db, citizen_id)
    if subscription:
        return subscription

    subscription = models.CalendarSubscription(
        citizen_id=citizen_id, token=_generate_token()
    )
    db.add(subscription)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request already created the row; fall back to it.
        db.rollback()
        return get_by_citizen_id(db, citizen_id)
    db.refresh(subscription)
    return subscription


def regenerate(db: Session, citizen_id: int) -> models.CalendarSubscription:
    """Rotate the token, invalidating any previously shared URL."""
    subscription = get_or_create(db, citizen_id)
    subscription.token = _generate_token()
    db.commit()
    db.refresh(subscription)
    return subscription


def revoke(db: Session, citizen_id: int) -> bool:
    """Delete the citizen's subscription. Returns False if there was nothing to revoke."""
    subscription = get_by_citizen_id(db, citizen_id)
    if not subscription:
        return False
    db.delete(subscription)
    db.commit()
    return True


def get_linked_emails(db: Session, citizen_id: int) -> List[str]:
    """All emails (primary + secondary, across linked accounts) for a citizen.

    Mirrors how the profile aggregates events from Hasura so a user's RSVP feed
    covers every email they may have used to RSVP in the Social Layer.
    """
    linked_ids = get_linked_citizen_ids(db, citizen_id)
    citizens = db.query(Citizen).filter(Citizen.id.in_(linked_ids)).all()

    # The Social Layer `_in` filter matches profile.email exactly, so we must pass
    # emails in their stored case (matching the existing event-count path). Dedupe
    # case-insensitively but keep the first-seen original form.
    by_lower: dict[str, str] = {}
    for citizen in citizens:
        for email in (citizen.primary_email, citizen.secondary_email):
            if email and email.lower() not in by_lower:
                by_lower[email.lower()] = email
    return sorted(by_lower.values())
