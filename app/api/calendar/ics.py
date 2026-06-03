"""Fetch a citizen's RSVP'd events from the Social Layer and render an iCalendar feed.

Individual events (talks, sessions, activities) are not stored in this backend; they
live in the external Social Layer (Hasura GraphQL). "RSVP'd" means the citizen is a
participant of the event, which is exactly the filter the profile/event-count code
already uses. Recurring events come back from the Social Layer as one row per
occurrence, so each RSVP'd occurrence is emitted as its own VEVENT (no RRULE needed).
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

from app.core.config import settings
from app.core.logger import logger
from app.core.utils import current_time

PRODID = '-//EdgeOS//Calendar Subscription//EN'
# Hint to calendar clients on how often to re-poll the feed.
REFRESH_INTERVAL = 'PT1H'
_HTTP_TIMEOUT = 10

# Preferred field set. If the Social Layer schema lacks one of the richer fields the
# request errors out as a whole, so we retry with a minimal, known-safe projection.
_EVENT_FIELDS_FULL = (
    'id title start_time end_time timezone location event_type status tags content'
)
_EVENT_FIELDS_MIN = 'id title start_time end_time location'

_QUERY_TEMPLATE = """
query RsvpEvents($where: events_bool_exp) {{
    events(where: $where) {{
        {fields}
    }}
}}
"""


def fetch_rsvp_events(emails: List[str]) -> List[dict]:
    """Return Social Layer events the given emails are participants of.

    Never raises: on any error (network, GraphQL, misconfiguration) it logs and
    returns an empty list so the feed stays a valid, empty calendar.
    """
    if not emails or not settings.HASURA_URL:
        return []

    where = {'participants': {'profile': {'email': {'_in': emails}}}}

    for fields in (_EVENT_FIELDS_FULL, _EVENT_FIELDS_MIN):
        query = _QUERY_TEMPLATE.format(fields=fields)
        try:
            response = requests.post(
                settings.HASURA_URL,
                headers={'Content-Type': 'application/json'},
                json={'query': query, 'variables': {'where': where}},
                timeout=_HTTP_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as e:
            logger.error('Failed to fetch RSVP events from Hasura: %s', e)
            return []
        except Exception as e:  # noqa: BLE001 - never let the feed 500
            logger.error('Unexpected error fetching RSVP events: %s', e)
            return []

        if result.get('errors'):
            # Likely an unknown field in the richer projection; try the minimal one.
            logger.warning(
                'Hasura GraphQL error (fields=%s): %s', fields, result['errors']
            )
            continue

        return result.get('data', {}).get('events', []) or []

    return []


def build_calendar(events: List[dict], calendar_name: str) -> str:
    """Render events as an RFC 5545 VCALENDAR string."""
    now = _format_utc(current_time())

    lines: List[str] = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        f'PRODID:{PRODID}',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        f'NAME:{_escape(calendar_name)}',
        f'X-WR-CALNAME:{_escape(calendar_name)}',
        f'REFRESH-INTERVAL;VALUE=DURATION:{REFRESH_INTERVAL}',
        f'X-PUBLISHED-TTL:{REFRESH_INTERVAL}',
    ]

    for event in events:
        lines.extend(_build_vevent(event, dtstamp=now))

    lines.append('END:VCALENDAR')
    return '\r\n'.join(_fold(line) for line in lines) + '\r\n'


def _build_vevent(event: dict, dtstamp: str) -> List[str]:
    start = _parse_dt(event.get('start_time'), event.get('timezone'))
    if start is None:
        # Without a start there is no valid VEVENT; skip it.
        return []

    end = _parse_dt(event.get('end_time'), event.get('timezone'))
    if end is None or end <= start:
        end = start + timedelta(hours=1)

    uid = f'{event.get("id", _format_utc(start))}@sociallayer.edgeos'

    block: List[str] = [
        'BEGIN:VEVENT',
        f'UID:{uid}',
        f'DTSTAMP:{dtstamp}',
        f'DTSTART:{_format_utc(start)}',
        f'DTEND:{_format_utc(end)}',
        f'SUMMARY:{_escape(event.get("title") or "Untitled event")}',
        'STATUS:CONFIRMED',
    ]

    location = event.get('location')
    if location:
        block.append(f'LOCATION:{_escape(location)}')

    description = event.get('content')
    if description:
        block.append(f'DESCRIPTION:{_escape(description)}')

    categories = _categories(event)
    if categories:
        block.append(f'CATEGORIES:{categories}')

    url = event.get('url')
    if url:
        block.append(f'URL:{_escape(url)}')

    block.append('END:VEVENT')
    return block


def _categories(event: dict) -> str:
    values: List[str] = []
    event_type = event.get('event_type')
    if event_type:
        values.append(str(event_type))
    tags = event.get('tags')
    if isinstance(tags, list):
        values.extend(str(t) for t in tags if t)
    # CATEGORIES is a comma-separated TEXT list; escape each value.
    return ','.join(_escape(v) for v in values)


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------


def _parse_dt(value: Optional[str], tz_name: Optional[str]) -> Optional[datetime]:
    """Parse a Social Layer timestamp into an aware UTC datetime.

    Social Layer timestamps are normally tz-aware (e.g. `2026-06-03T08:00:00+00:00`).
    If a naive value comes back, fall back to the event's `timezone`, then to UTC.
    """
    if not value or not isinstance(value, str):
        return None

    normalized = value.strip().replace(' ', 'T')
    if normalized.endswith('Z'):
        normalized = normalized[:-1] + '+00:00'

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        logger.warning('Could not parse Social Layer timestamp: %s', value)
        return None

    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc)

    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            return parsed.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc)
        except Exception:  # noqa: BLE001 - unknown tz / missing tzdata -> assume UTC
            logger.warning('Unknown timezone %s; treating time as UTC', tz_name)

    return parsed.replace(tzinfo=timezone.utc)


def _format_utc(value: datetime) -> str:
    """Format an (aware or naive-UTC) datetime as an iCalendar UTC stamp."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.strftime('%Y%m%dT%H%M%SZ')


# ---------------------------------------------------------------------------
# Text helpers (RFC 5545 §3.1, §3.3.11)
# ---------------------------------------------------------------------------


def _escape(text: str) -> str:
    """Escape a TEXT value: backslash, semicolon, comma, and newlines."""
    return (
        str(text)
        .replace('\\', '\\\\')
        .replace(';', '\\;')
        .replace(',', '\\,')
        .replace('\r\n', '\\n')
        .replace('\r', '\\n')
        .replace('\n', '\\n')
    )


def _fold(line: str) -> str:
    """Fold a content line to <=75 octets using CRLF + space continuations.

    Folds on UTF-8 byte boundaries without splitting a multibyte character.
    """
    data = line.encode('utf-8')
    if len(data) <= 75:
        return line

    chunks: List[bytes] = []
    index = 0
    # Conservative limit so a continuation (leading space + content) stays <= 75 octets.
    limit = 73
    while index < len(data):
        end = min(index + limit, len(data))
        # Back off so we never cut in the middle of a multibyte sequence.
        while end < len(data) and (data[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(data[index:end])
        index = end
    return '\r\n '.join(chunk.decode('utf-8') for chunk in chunks)
