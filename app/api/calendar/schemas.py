from pydantic import BaseModel


class CalendarSubscriptionResponse(BaseModel):
    """Subscription token plus the URLs a user pastes into their calendar app."""

    token: str
    rsvp_ics_url: str
    rsvp_webcal_url: str
