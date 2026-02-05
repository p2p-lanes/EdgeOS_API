import pytest
from fastapi import status

from app.api.applications.models import Application
from app.api.applications.schemas import ApplicationStatus
from app.api.attendees.models import Attendee
from tests.conftest import get_auth_headers_for_citizen


def test_signup_success(client):
    response = client.post(
        '/citizens/signup',
        json={
            'primary_email': 'test@example.com',
            'first_name': 'Test',
            'last_name': 'User',
        },
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data['primary_email'] == 'test@example.com'
    assert data['id'] is not None


def test_signup_duplicate_email(client):
    # First signup
    client.post(
        '/citizens/signup',
        json={
            'primary_email': 'test@example.com',
            'first_name': 'Test',
            'last_name': 'User',
        },
    )

    # Duplicate signup
    response = client.post(
        '/citizens/signup',
        json={
            'primary_email': 'test@example.com',
            'first_name': 'Test',
            'last_name': 'User',
        },
    )
    assert response.status_code == status.HTTP_409_CONFLICT


@pytest.mark.asyncio
async def test_authenticate_success(client):
    response = client.post('/citizens/authenticate', json={'email': 'test@example.com'})
    assert response.status_code == status.HTTP_200_OK
    assert response.json()['message'] == 'Mail sent successfully'


def test_login_success(client, db_session):
    # First create a citizen with known spice
    from app.api.citizens.crud import citizen as citizen_crud
    from app.api.citizens.schemas import CitizenCreate

    new_citizen = CitizenCreate(primary_email='test@example.com')
    citizen = citizen_crud.create(db_session, new_citizen)

    response = client.post(
        '/citizens/login',
        params={'email': 'test@example.com', 'spice': citizen.spice},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data['access_token'] is not None
    assert data['token_type'] == 'Bearer'


def test_login_failure(client, db_session):
    # First create a citizen with known spice
    from app.api.citizens.crud import citizen as citizen_crud
    from app.api.citizens.schemas import CitizenCreate

    new_citizen = CitizenCreate(primary_email='test@example.com')
    citizen = citizen_crud.create(db_session, new_citizen)
    valid_spice = citizen.spice
    invalid_spice = 'invalidspice123'
    assert valid_spice != invalid_spice

    response = client.post(
        '/citizens/login',
        params={'email': citizen.primary_email, 'spice': invalid_spice},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()['detail'] == 'Invalid spice'

    # Invalid email
    response = client.post(
        '/citizens/login',
        params={'email': 'invalid@example.com', 'spice': valid_spice},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()['detail'] == 'Citizen not found'


def test_get_citizens_success(client, auth_headers):
    response = client.get('/citizens', headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 1
    assert data[0]['id'] == 1

    headers = get_auth_headers_for_citizen(999)

    response = client.get('/citizens', headers=headers)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 0


def test_get_my_poaps_success(client, test_citizen, test_popup_city, db_session):
    # Create an application for the citizen
    application = Application(
        citizen_id=test_citizen.id,
        popup_city_id=test_popup_city.id,
        first_name=test_citizen.first_name,
        last_name=test_citizen.last_name,
        email=test_citizen.primary_email,
        status=ApplicationStatus.ACCEPTED,
    )
    db_session.add(application)
    db_session.flush()

    # Create an attendee with a POAP URL
    attendee1 = Attendee(
        application_id=application.id,
        name=f'{test_citizen.first_name} {test_citizen.last_name}',
        category='main',
        email=test_citizen.primary_email,
        check_in_code='TCABCD',
        poap_url='https://example.com/poap/123',
    )
    db_session.add(attendee1)

    # Create an attendee without a POAP URL
    attendee2 = Attendee(
        application_id=application.id,
        name=f'{test_citizen.first_name} {test_citizen.last_name}',
        category='kid',
        email=test_citizen.primary_email,
        check_in_code='TCEFGH',
        poap_url=None,
    )
    db_session.add(attendee2)

    # Create an attendee with a POAP URL for a different application
    attendee3 = Attendee(
        application_id=application.id,
        name=f'{test_citizen.first_name} {test_citizen.last_name}',
        category='spouse',
        email=test_citizen.primary_email,
        check_in_code='TCIJKL',
        poap_url='https://example.com/poap/456',
    )
    db_session.add(attendee3)

    db_session.commit()

    # Get auth headers for the citizen
    headers = get_auth_headers_for_citizen(test_citizen.id)

    # Call the endpoint
    response = client.get('/citizens/my-poaps', headers=headers)

    # Assert the response
    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    # Check the structure of the response
    assert 'results' in data
    assert len(data['results']) == 1

    # Check the popup details
    popup_data = data['results'][0]
    assert popup_data['popup_id'] == test_popup_city.id
    assert popup_data['popup_name'] == test_popup_city.name

    # Check the POAP details
    assert len(popup_data['poaps']) == 2
    poap1 = popup_data['poaps'][0]
    assert poap1['attendee_id'] == attendee1.id
    assert poap1['attendee_name'] == attendee1.name
    assert poap1['attendee_email'] == attendee1.email
    assert poap1['attendee_category'] == attendee1.category
    assert poap1['poap_url'] == attendee1.poap_url

    poap2 = popup_data['poaps'][1]
    assert poap2['attendee_id'] == attendee3.id
    assert poap2['attendee_name'] == attendee3.name
    assert poap2['attendee_email'] == attendee3.email
    assert poap2['attendee_category'] == attendee3.category
    assert poap2['poap_url'] == attendee3.poap_url


def test_get_my_poaps_no_poaps(client, test_citizen, test_popup_city, db_session):
    # Create an application for the citizen
    application = Application(
        citizen_id=test_citizen.id,
        popup_city_id=test_popup_city.id,
        first_name=test_citizen.first_name,
        last_name=test_citizen.last_name,
        email=test_citizen.primary_email,
        status=ApplicationStatus.ACCEPTED,
    )
    db_session.add(application)
    db_session.flush()

    # Create an attendee WITHOUT a POAP URL
    attendee = Attendee(
        application_id=application.id,
        name=f'{test_citizen.first_name} {test_citizen.last_name}',
        category='main',
        email=test_citizen.primary_email,
        check_in_code='TCABCD',
        poap_url=None,  # No POAP URL
    )
    db_session.add(attendee)
    db_session.commit()

    # Get auth headers for the citizen
    headers = get_auth_headers_for_citizen(test_citizen.id)

    # Call the endpoint
    response = client.get('/citizens/my-poaps', headers=headers)

    # Assert the response
    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    # Check that there are no results since no POAPs are available
    assert 'results' in data
    assert len(data['results']) == 0
