from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.calendar import crud, ics, schemas
from app.core.config import settings
from app.core.database import get_db
from app.core.security import TokenData, get_current_user

router = APIRouter()


def _feed_urls(token: str) -> tuple[str, str]:
    """Return the (https, webcal) RSVP feed URLs for a token."""
    base = settings.BACKEND_URL.rstrip('/')
    https_url = f'{base}/calendar/{token}/rsvp.ics'

    webcal_url = https_url
    for scheme in ('https://', 'http://'):
        if base.startswith(scheme):
            webcal_url = 'webcal://' + https_url[len(scheme) :]
            break
    return https_url, webcal_url


def _serialize(subscription) -> schemas.CalendarSubscriptionResponse:
    https_url, webcal_url = _feed_urls(subscription.token)
    return schemas.CalendarSubscriptionResponse(
        token=subscription.token,
        rsvp_ics_url=https_url,
        rsvp_webcal_url=webcal_url,
    )


# ---------------------------------------------------------------------------
# Token management (authenticated with the citizen's JWT)
# ---------------------------------------------------------------------------


@router.get('/subscription', response_model=schemas.CalendarSubscriptionResponse)
def get_subscription(
    user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the current citizen's subscription token + feed URLs (creating it once)."""
    return _serialize(crud.get_or_create(db, user.citizen_id))


@router.post('/subscription', response_model=schemas.CalendarSubscriptionResponse)
def create_subscription(
    user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Idempotently create (or return) the citizen's subscription token."""
    return _serialize(crud.get_or_create(db, user.citizen_id))


@router.post(
    '/subscription/regenerate',
    response_model=schemas.CalendarSubscriptionResponse,
)
def regenerate_subscription(
    user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rotate the token; any previously shared URL stops working immediately."""
    return _serialize(crud.regenerate(db, user.citizen_id))


@router.delete('/subscription', status_code=status.HTTP_204_NO_CONTENT)
def revoke_subscription(
    user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke (delete) the citizen's subscription token."""
    crud.revoke(db, user.citizen_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Public feed (authenticated by the bearer token in the URL, not a JWT)
# ---------------------------------------------------------------------------


@router.get('/{token}/rsvp.ics')
def rsvp_feed(token: str, db: Session = Depends(get_db)):
    """Emit the token owner's RSVP'd Social Layer events as an iCalendar feed."""
    subscription = crud.get_by_token(db, token)
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Invalid or revoked calendar token',
        )

    emails = crud.get_linked_emails(db, subscription.citizen_id)
    events = ics.fetch_rsvp_events(emails)
    body = ics.build_calendar(events, calendar_name="Edge — My RSVP'd Events")

    return Response(
        content=body,
        media_type='text/calendar; charset=utf-8',
        headers={
            'Content-Disposition': 'inline; filename="rsvp.ics"',
            'Cache-Control': 'public, max-age=3600',
        },
    )
