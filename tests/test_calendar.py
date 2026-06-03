from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from app.api.calendar import crud, ics
from app.core.config import settings
from tests.conftest import get_auth_headers_for_citizen

ICS_MODULE = 'app.api.calendar.ics'


# ---------------------------------------------------------------------------
# Token management endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def backend_url():
    """Pin BACKEND_URL so feed URLs (incl. webcal://) are deterministic."""
    original = settings.BACKEND_URL
    settings.BACKEND_URL = 'https://api.edgeos.test'
    yield settings.BACKEND_URL
    settings.BACKEND_URL = original


def test_get_subscription_creates_and_is_idempotent(
    client, test_citizen, auth_headers, backend_url
):
    first = client.get('/calendar/subscription', headers=auth_headers)
    assert first.status_code == 200
    body = first.json()
    token = body['token']

    assert token
    assert body['rsvp_ics_url'] == f'{backend_url}/calendar/{token}/rsvp.ics'
    assert body['rsvp_webcal_url'] == (
        f'webcal://api.edgeos.test/calendar/{token}/rsvp.ics'
    )

    # A second call returns the same token (get-or-create, not a new one each time).
    second = client.get('/calendar/subscription', headers=auth_headers)
    assert second.json()['token'] == token


def test_regenerate_rotates_token(client, test_citizen, auth_headers, backend_url):
    original = client.post('/calendar/subscription', headers=auth_headers).json()[
        'token'
    ]
    rotated = client.post(
        '/calendar/subscription/regenerate', headers=auth_headers
    ).json()['token']

    assert rotated != original
    # The rotated token resolves; the old one no longer does.
    assert client.get(f'/calendar/{rotated}/rsvp.ics').status_code == 200
    assert client.get(f'/calendar/{original}/rsvp.ics').status_code == 404


def test_revoke_deletes_token(client, test_citizen, auth_headers):
    token = client.post('/calendar/subscription', headers=auth_headers).json()['token']
    assert client.get(f'/calendar/{token}/rsvp.ics').status_code == 200

    deleted = client.delete('/calendar/subscription', headers=auth_headers)
    assert deleted.status_code == 204
    assert client.get(f'/calendar/{token}/rsvp.ics').status_code == 404


def test_subscription_requires_auth(client):
    assert client.get('/calendar/subscription').status_code == 401


def test_tokens_are_isolated_per_citizen(client, create_test_citizen, backend_url):
    citizen_a = create_test_citizen(1)
    citizen_b = create_test_citizen(2)

    token_a = client.post(
        '/calendar/subscription', headers=get_auth_headers_for_citizen(citizen_a.id)
    ).json()['token']
    token_b = client.post(
        '/calendar/subscription', headers=get_auth_headers_for_citizen(citizen_b.id)
    ).json()['token']

    assert token_a != token_b


# ---------------------------------------------------------------------------
# Feed endpoint
# ---------------------------------------------------------------------------

SAMPLE_EVENTS = [
    {
        'id': 'evt-1',
        'title': 'Qi Gong',
        'start_time': '2026-06-03T08:00:00+00:00',
        'end_time': '2026-06-03T08:45:00+00:00',
        'location': 'The Hub - Wellness Space',
        'event_type': 'Exercise',
        'tags': ['wellness'],
        'content': 'A moving meditation.',
    }
]


def test_feed_invalid_token_returns_404(client):
    assert client.get('/calendar/not-a-real-token/rsvp.ics').status_code == 404


def test_feed_renders_rsvp_events(client, test_citizen, auth_headers):
    token = client.post('/calendar/subscription', headers=auth_headers).json()['token']

    with patch(f'{ICS_MODULE}.fetch_rsvp_events', return_value=SAMPLE_EVENTS) as mocked:
        response = client.get(f'/calendar/{token}/rsvp.ics')

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/calendar')
    body = response.text
    assert body.startswith('BEGIN:VCALENDAR')
    assert body.strip().endswith('END:VCALENDAR')
    assert 'BEGIN:VEVENT' in body
    assert 'SUMMARY:Qi Gong' in body
    assert 'DTSTART:20260603T080000Z' in body
    assert 'DTEND:20260603T084500Z' in body

    # The feed resolves the token to the citizen and queries by their linked email.
    called_emails = mocked.call_args.args[0]
    assert test_citizen.primary_email.lower() in called_emails


def test_feed_with_no_events_is_valid_empty_calendar(client, auth_headers):
    token = client.post('/calendar/subscription', headers=auth_headers).json()['token']

    with patch(f'{ICS_MODULE}.fetch_rsvp_events', return_value=[]):
        response = client.get(f'/calendar/{token}/rsvp.ics')

    assert response.status_code == 200
    assert 'BEGIN:VCALENDAR' in response.text
    assert 'BEGIN:VEVENT' not in response.text


def test_feed_is_not_publicly_cacheable(client, auth_headers):
    """The token is a bearer secret, so shared caches must not store the feed
    (otherwise a revoked token's old response could still be served)."""
    token = client.post('/calendar/subscription', headers=auth_headers).json()['token']

    with patch(f'{ICS_MODULE}.fetch_rsvp_events', return_value=[]):
        response = client.get(f'/calendar/{token}/rsvp.ics')

    cache_control = response.headers.get('cache-control', '')
    assert 'public' not in cache_control
    assert 'no-store' in cache_control


# ---------------------------------------------------------------------------
# Linked-email resolution
# ---------------------------------------------------------------------------


def test_get_linked_emails_preserves_stored_case(db_session, create_test_citizen):
    """Social Layer matches profile.email exactly, so stored case must be kept
    (mirrors the existing event-count path) rather than lowercased."""
    citizen = create_test_citizen(1)
    citizen.primary_email = 'Mixed.Case@Example.com'
    citizen.secondary_email = 'Second@Example.COM'
    db_session.commit()

    emails = crud.get_linked_emails(db_session, citizen.id)

    assert 'Mixed.Case@Example.com' in emails
    assert 'Second@Example.COM' in emails
    assert 'mixed.case@example.com' not in emails  # not lowercased


# ---------------------------------------------------------------------------
# Social Layer fetch
# ---------------------------------------------------------------------------


def test_fetch_returns_empty_without_emails():
    assert ics.fetch_rsvp_events([]) == []


def test_fetch_returns_empty_without_hasura_url(monkeypatch):
    monkeypatch.setattr(settings, 'HASURA_URL', '')
    assert ics.fetch_rsvp_events(['a@example.com']) == []


def _mock_response(payload):
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = payload
    return response


def test_fetch_falls_back_to_minimal_fields_on_graphql_error(monkeypatch):
    monkeypatch.setattr(settings, 'HASURA_URL', 'https://hasura.test/graphql')
    responses = [
        _mock_response({'errors': [{'message': "field 'content' not found"}]}),
        _mock_response({'data': {'events': SAMPLE_EVENTS}}),
    ]
    with patch(f'{ICS_MODULE}.requests.post', side_effect=responses) as post:
        events = ics.fetch_rsvp_events(['a@example.com'])

    assert events == SAMPLE_EVENTS
    assert post.call_count == 2  # rich query failed, minimal query succeeded


def test_fetch_swallows_network_errors(monkeypatch):
    import requests

    monkeypatch.setattr(settings, 'HASURA_URL', 'https://hasura.test/graphql')
    with patch(
        f'{ICS_MODULE}.requests.post', side_effect=requests.RequestException('boom')
    ):
        assert ics.fetch_rsvp_events(['a@example.com']) == []


# ---------------------------------------------------------------------------
# ICS serializer
# ---------------------------------------------------------------------------


def test_build_calendar_skips_events_without_start():
    body = ics.build_calendar([{'id': 'x', 'title': 'No start'}], 'Test')
    assert 'BEGIN:VEVENT' not in body


def test_build_calendar_defaults_missing_end_to_one_hour():
    body = ics.build_calendar(
        [{'id': 'x', 'title': 'T', 'start_time': '2026-06-03T08:00:00+00:00'}], 'Test'
    )
    assert 'DTSTART:20260603T080000Z' in body
    assert 'DTEND:20260603T090000Z' in body


def test_build_calendar_escapes_text():
    body = ics.build_calendar(
        [
            {
                'id': 'x',
                'title': 'Talk: A, B; C',
                'start_time': '2026-06-03T08:00:00+00:00',
                'content': 'line one\nline two',
            }
        ],
        'Test',
    )
    assert 'SUMMARY:Talk: A\\, B\\; C' in body
    assert 'DESCRIPTION:line one\\nline two' in body


def test_naive_time_uses_event_timezone():
    body = ics.build_calendar(
        [
            {
                'id': 'x',
                'title': 'T',
                'start_time': '2026-06-03T08:00:00',
                'timezone': 'America/Los_Angeles',
            }
        ],
        'Test',
    )
    # 08:00 PDT (UTC-7 in June) == 15:00 UTC
    assert 'DTSTART:20260603T150000Z' in body


def test_all_lines_respect_75_octet_fold_limit():
    long_title = 'A very long event title ' * 10  # > 75 octets
    body = ics.build_calendar(
        [{'id': 'x', 'title': long_title, 'start_time': '2026-06-03T08:00:00+00:00'}],
        'Test',
    )
    for line in body.split('\r\n'):
        assert len(line.encode('utf-8')) <= 75


def test_uses_crlf_line_endings():
    body = ics.build_calendar(SAMPLE_EVENTS, 'Test')
    assert '\r\n' in body
    # No bare LF that isn't part of a CRLF pair.
    assert '\n' not in body.replace('\r\n', '')


def test_output_parses_with_icalendar_when_available():
    """Spec-compliance check using a real parser when one is installed."""
    icalendar = pytest.importorskip('icalendar')
    body = ics.build_calendar(SAMPLE_EVENTS, "Edge — My RSVP'd Events")
    cal = icalendar.Calendar.from_ical(body)
    events = [c for c in cal.walk() if c.name == 'VEVENT']
    assert len(events) == 1
    assert str(events[0]['SUMMARY']) == 'Qi Gong'
    assert events[0]['DTSTART'].dt == datetime(2026, 6, 3, 8, 0, tzinfo=timezone.utc)
