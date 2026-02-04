import asyncio
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.citizens.models import Citizen
from app.api.coupon_codes.models import CouponCode
from app.api.groups.models import Group, GroupLeader
from app.api.popup_city.models import PopUpCity
from app.api.webhooks.dependencies import get_webhook_cache
from app.core.config import Environment, settings
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.core.utils import current_time
from main import app


@pytest.fixture(scope='session', autouse=True)
def check_test_environment():
    if settings.ENVIRONMENT != Environment.TEST:
        raise RuntimeError(
            f'Tests can only be executed in test environment. Current environment: {settings.ENVIRONMENT}'
        )


@pytest.fixture(scope='session', autouse=True)
def setup_test_api_keys():
    """Set default API keys for testing to avoid None values in headers"""
    # Save original values
    original_coupon_key = settings.COUPON_API_KEY
    original_groups_key = settings.GROUPS_API_KEY
    original_check_in_key = settings.CHECK_IN_API_KEY

    # Set test values
    settings.COUPON_API_KEY = 'test_coupon_api_key'
    settings.GROUPS_API_KEY = 'test_groups_api_key'
    settings.CHECK_IN_API_KEY = 'test_check_in_api_key'

    yield

    # Restore original values after tests
    settings.COUPON_API_KEY = original_coupon_key
    settings.GROUPS_API_KEY = original_groups_key
    settings.CHECK_IN_API_KEY = original_check_in_key


@pytest.fixture(scope='session')
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope='session')
def test_db_engine():
    engine = create_engine(
        settings.SQLALCHEMY_TEST_DATABASE_URL,
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope='function')
def db_session(test_db_engine):
    """Create a fresh database session for each test"""
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_db_engine
    )

    # Drop and recreate all tables before each test
    Base.metadata.drop_all(bind=test_db_engine)
    Base.metadata.create_all(bind=test_db_engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        # Optionally, drop all tables after each test
        # Base.metadata.drop_all(bind=test_db_engine)


@pytest.fixture(scope='function')
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def get_auth_headers_for_citizen(citizen_id: int) -> dict:
    """Generate auth headers for a specific citizen ID"""
    user_data = {
        'citizen_id': citizen_id,
        'email': f'test{citizen_id}@example.com',
    }
    access_token = create_access_token(data=user_data)
    return {'Authorization': f'Bearer {access_token}'}


@pytest.fixture(scope='function')
def create_test_citizen(db_session):
    """Factory fixture to create test citizens"""

    def _create_citizen(citizen_id: int):
        citizen = Citizen(
            # id=citizen_id,
            primary_email=f'test{citizen_id}@example.com',
            first_name=f'Test{citizen_id}',
            last_name='User',
            email_validated=True,
        )
        db_session.add(citizen)
        db_session.commit()
        return citizen

    yield _create_citizen


@pytest.fixture(scope='function')
def test_citizen(create_test_citizen):
    """Creates a default test citizen with ID 1"""
    return create_test_citizen(1)


@pytest.fixture(scope='function')
def auth_headers(test_citizen):
    """Creates auth headers for the default test citizen"""
    return get_auth_headers_for_citizen(test_citizen.id)


@pytest.fixture(scope='function')
def test_popup_city(db_session):
    popup = PopUpCity(
        id=1,
        name='Test City',
        slug='test-city',
        prefix='TC',
        location='Test Location',
        visible_in_portal=True,
        clickable_in_portal=True,
        requires_approval=True,
        simplefi_api_key='test_api_key',
    )
    db_session.add(popup)
    db_session.commit()
    return popup


@pytest.fixture
def test_application(test_citizen, test_popup_city):
    """Creates a test application data dictionary"""
    return {
        'first_name': 'Test',
        'last_name': 'User',
        'citizen_id': test_citizen.id,
        'popup_city_id': test_popup_city.id,
    }


@pytest.fixture
def test_products(db_session):
    from app.api.products.models import Product

    product1 = Product(
        id=1,
        name='Test Product',
        slug='test-product',
        description='Test Description',
        price=100.0,
        category='ticket',
        popup_city_id=1,
        is_active=True,
    )
    product2 = Product(
        id=2,
        name='Test Product 2',
        slug='test-product-2',
        description='Test Description 2',
        price=200.0,
        category='ticket',
        popup_city_id=1,
        is_active=True,
    )
    db_session.add(product1)
    db_session.add(product2)
    db_session.commit()
    return product1, product2


@pytest.fixture
def test_application_with_attendee(db_session, test_citizen, test_popup_city):
    """Create a test application with the test citizen"""
    from app.api.applications.models import Application
    from app.api.applications.schemas import ApplicationStatus

    application = Application(
        id=1,
        first_name='Test',
        last_name='User',
        email=test_citizen.primary_email,
        citizen_id=test_citizen.id,
        popup_city_id=test_popup_city.id,
        _status=ApplicationStatus.ACCEPTED.value,
    )
    db_session.add(application)
    db_session.commit()
    return application


@pytest.fixture
def test_attendee(db_session, test_application_with_attendee):
    """Create a test attendee with check-in code"""
    from app.api.attendees.models import Attendee

    attendee = Attendee(
        id=1,
        application_id=test_application_with_attendee.id,
        name='Test Attendee',
        category='main',
        email='test-attendee@example.com',
        check_in_code='TEST123',
    )
    db_session.add(attendee)
    db_session.commit()
    return attendee


@pytest.fixture
def test_attendee_product(db_session, test_attendee, test_products):
    """Link a product to the test attendee"""
    from app.api.attendees.models import AttendeeProduct

    product = test_products[0]
    attendee_product = AttendeeProduct(
        attendee_id=test_attendee.id,
        product_id=product.id,
    )
    db_session.add(attendee_product)
    db_session.commit()
    return attendee_product


@pytest.fixture
def test_coupon_code(db_session, test_popup_city):
    coupon_code = CouponCode(
        code='TEST10',
        popup_city_id=test_popup_city.id,
        discount_value=10.0,
        max_uses=100,
        current_uses=0,
        is_active=True,
        start_date=current_time() - timedelta(days=1),
        end_date=current_time() + timedelta(days=1),
    )
    db_session.add(coupon_code)
    db_session.commit()
    return coupon_code


@pytest.fixture
def test_group(db_session, test_popup_city, test_citizen):
    """Create a test group with the test citizen as leader"""
    group = Group(
        name='Test Group',
        slug='test-group',
        description='Test Description',
        discount_percentage=10.0,
        popup_city_id=test_popup_city.id,
        max_members=5,
    )
    db_session.add(group)
    db_session.flush()

    group_leader = GroupLeader(citizen_id=test_citizen.id, group_id=group.id)
    db_session.add(group_leader)
    db_session.commit()
    return group


@pytest.fixture
def mock_webhook_cache():
    mock_cache = Mock()
    mock_cache.add.return_value = True  # Always treat webhooks as new
    app.dependency_overrides[get_webhook_cache] = lambda: mock_cache
    yield mock_cache
    app.dependency_overrides.clear()


@pytest.fixture
def mock_email_template(monkeypatch):
    """Mock the get_email_template method on PopUpCity to avoid template lookup errors"""
    from app.api.popup_city.models import PopUpCity

    def mock_get_template(self, event, *args, **kwargs):
        return event

    monkeypatch.setattr(PopUpCity, 'get_email_template', mock_get_template)
    return mock_get_template


@pytest.fixture
def mock_create_payment(mock_simplefi_response):
    with patch('app.core.simplefi.create_payment') as mock:
        mock.return_value = mock_simplefi_response
        yield mock


@pytest.fixture
def mock_simplefi_response():
    return {
        'id': 'test_payment_id',
        'status': 'pending',
        'checkout_url': 'https://test.checkout.url',
    }


@pytest.fixture(scope='function', autouse=True)
def mock_poap_refresh_lock():
    """Mock the POAP refresh lock for tests since SQLite doesn't support pg_advisory_lock"""
    from contextlib import contextmanager

    from app.api.citizens.crud import POAP_REFRESH_LOCK

    @contextmanager
    def mock_acquire(db, timeout_seconds=None):
        yield

    with patch.object(POAP_REFRESH_LOCK, 'acquire', mock_acquire):
        yield


@pytest.fixture(scope='function', autouse=True)
def mock_poap_api():
    """Mock POAP API calls for tests"""

    def mock_response_factory(*args, **kwargs):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()

        url = args[0] if args else kwargs.get('url', '')
        if 'auth.accounts.poap.xyz/oauth/token' in url:
            mock_response.json.return_value = {
                'access_token': 'test_access_token',
                'expires_in': 3600,
            }
        else:
            mock_response.json.return_value = {
                'claimed': False,
                'is_active': True,
                'event': {
                    'name': 'Test POAP',
                    'description': 'Test POAP Description',
                    'image_url': 'https://test.poap.image',
                },
            }
        return mock_response

    with (
        patch('requests.get', side_effect=mock_response_factory),
        patch('requests.post', side_effect=mock_response_factory),
    ):
        yield
