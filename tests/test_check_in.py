from datetime import datetime

from app.api.check_in.models import CheckIn


def test_qr_check_in_success(client, test_attendee, test_attendee_product, db_session):
    """Test successful QR check-in"""
    response = client.post(
        '/check-in/qr',
        json={'code': test_attendee.check_in_code},
        headers={'x-api-key': 'test_check_in_api_key'},
    )

    assert response.status_code == 200
    assert response.json()['success'] is True
    assert response.json()['first_check_in'] is True

    # Test subsequent check-in
    response = client.post(
        '/check-in/qr',
        json={'code': test_attendee.check_in_code},
        headers={'x-api-key': 'test_check_in_api_key'},
    )

    assert response.status_code == 200
    assert response.json()['success'] is True
    assert response.json()['first_check_in'] is False

    # Search for check-in record
    check_in = db_session.query(CheckIn).filter_by(attendee_id=test_attendee.id).first()
    assert check_in is not None
    assert check_in.qr_check_in is True
    assert check_in.qr_scan_timestamp is not None
    assert check_in.arrival_date is None
    assert check_in.departure_date is None
    assert check_in.virtual_check_in is False


def test_qr_check_in_invalid_api_key(client, test_attendee):
    """Test QR check-in with invalid API key"""
    response = client.post(
        '/check-in/qr',
        json={'code': test_attendee.check_in_code},
        headers={'x-api-key': 'invalid_api_key'},
    )

    assert response.status_code == 403
    assert 'Invalid API key' in response.json()['detail']


def test_qr_check_in_invalid_code(client, test_attendee):
    """Test QR check-in with invalid check-in code"""
    response = client.post(
        '/check-in/qr',
        json={'code': 'WRONG_CODE'},
        headers={'x-api-key': 'test_check_in_api_key'},
    )

    assert response.status_code == 200
    assert response.json()['success'] is False


def test_qr_check_in_no_products(client, test_attendee):
    """Test QR check-in with an attendee that has no products"""
    response = client.post(
        '/check-in/qr',
        json={'code': test_attendee.check_in_code},
        headers={'x-api-key': 'test_check_in_api_key'},
    )

    assert response.status_code == 200
    assert response.json()['success'] is False


def test_virtual_check_in_success(
    client, test_attendee, test_attendee_product, db_session
):
    """Test successful virtual check-in"""
    arrival_date = datetime(2025, 7, 1)
    departure_date = datetime(2025, 7, 5)

    response = client.post(
        '/check-in/virtual',
        json={
            'application_id': test_attendee.application_id,
            'code': test_attendee.check_in_code,
            'arrival_date': arrival_date.isoformat(),
            'departure_date': departure_date.isoformat(),
        },
        headers={'x-api-key': 'test_check_in_api_key'},
    )

    assert response.status_code == 200
    assert response.json()['success'] is True
    assert response.json()['first_check_in'] is True

    # Verify check-in record
    check_in = db_session.query(CheckIn).filter_by(attendee_id=test_attendee.id).first()
    assert check_in is not None
    assert check_in.virtual_check_in is True
    assert check_in.arrival_date.date() == arrival_date.date()
    assert check_in.departure_date.date() == departure_date.date()
    assert check_in.qr_check_in is False
    assert check_in.qr_scan_timestamp is None
    assert check_in.virtual_check_in_timestamp is not None
    assert check_in.code == test_attendee.check_in_code
    assert check_in.attendee_id == test_attendee.id


def test_virtual_check_in_subsequent(
    client, test_attendee, test_attendee_product, db_session
):
    """Test subsequent virtual check-in with updated dates"""
    # First check-in
    arrival_date = datetime(2025, 7, 1)
    departure_date = datetime(2025, 7, 5)
    response = client.post(
        '/check-in/virtual',
        json={
            'application_id': test_attendee.application_id,
            'code': test_attendee.check_in_code,
            'arrival_date': arrival_date.isoformat(),
            'departure_date': departure_date.isoformat(),
        },
        headers={'x-api-key': 'test_check_in_api_key'},
    )
    assert response.status_code == 200
    assert response.json()['success'] is True
    assert response.json()['first_check_in'] is True

    # Update check-in dates
    response = client.post(
        '/check-in/virtual',
        json={
            'application_id': test_attendee.application_id,
            'code': test_attendee.check_in_code,
            'arrival_date': arrival_date.isoformat(),
            'departure_date': departure_date.isoformat(),
        },
        headers={'x-api-key': 'test_check_in_api_key'},
    )

    assert response.status_code == 200
    assert response.json()['success'] is True
    assert response.json()['first_check_in'] is False

    # Verify updated check-in record
    check_in = db_session.query(CheckIn).filter_by(attendee_id=test_attendee.id).first()
    assert check_in is not None
    assert check_in.arrival_date.date() == arrival_date.date()
    assert check_in.departure_date.date() == departure_date.date()


def test_virtual_check_in_invalid_api_key(client, test_attendee):
    """Test virtual check-in with invalid API key"""
    response = client.post(
        '/check-in/virtual',
        json={
            'application_id': test_attendee.application_id,
            'code': test_attendee.check_in_code,
            'arrival_date': datetime(2025, 7, 1).isoformat(),
            'departure_date': datetime(2025, 7, 5).isoformat(),
        },
        headers={'x-api-key': 'invalid_api_key'},
    )

    assert response.status_code == 403
    assert 'Invalid API key' in response.json()['detail']


def test_virtual_check_in_invalid_code(client, test_attendee):
    """Test virtual check-in with invalid check-in code"""
    response = client.post(
        '/check-in/virtual',
        json={
            'application_id': test_attendee.application_id,
            'code': 'WRONG_CODE',
            'arrival_date': datetime(2025, 7, 1).isoformat(),
            'departure_date': datetime(2025, 7, 5).isoformat(),
        },
        headers={'x-api-key': 'test_check_in_api_key'},
    )

    assert response.status_code == 200
    assert response.json()['success'] is False
