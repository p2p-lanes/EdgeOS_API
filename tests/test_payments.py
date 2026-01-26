import pytest
from fastapi import status

from app.api.applications.schemas import ApplicationStatus
from app.api.payments.models import Payment
from app.api.payments.schemas import PaymentSource
from tests.conftest import get_auth_headers_for_citizen


@pytest.fixture
def test_payment_data(test_application, client, auth_headers):
    # First create an application
    response = client.post(
        '/applications/', json=test_application, headers=auth_headers
    )
    assert response.status_code == status.HTTP_201_CREATED
    application = response.json()
    application_id = application['id']

    # Create an attendee
    attendee_data = {
        'name': 'Test Attendee',
        'category': 'spouse',
        'email': 'spouse@example.com',
    }
    response = client.post(
        f'/applications/{application_id}/attendees',
        json=attendee_data,
        headers=auth_headers,
    )
    assert response.status_code == status.HTTP_200_OK
    attendee = response.json()['attendees'][1]  # Index 1 is the spouse

    return {
        'application_id': application_id,
        'products': [
            {
                'product_id': 1,
                'attendee_id': attendee['id'],
                'quantity': 1,
            }
        ],
    }


def test_create_payment_unauthorized(client, test_payment_data):
    response = client.post('/payments/', json=test_payment_data)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_create_payment_success(
    client,
    auth_headers,
    test_payment_data,
    test_products,
    db_session,
    mock_create_payment,
):
    from app.api.applications.models import Application

    application = db_session.get(Application, test_payment_data['application_id'])
    application.status = ApplicationStatus.ACCEPTED.value
    application.scholarship_request = False
    application.discount_assigned = None
    db_session.commit()

    response = client.post('/payments/', json=test_payment_data, headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data['application_id'] == test_payment_data['application_id']
    assert data['amount'] > 0
    assert data['currency'] == 'USD'
    assert data['status'] == 'pending'
    assert data['external_id'] is not None
    assert data['checkout_url'] is not None

    # Verify simplefi.create_payment was called with correct arguments
    mock_create_payment.assert_called_once()
    call_args = mock_create_payment.call_args
    assert call_args.args[0] == data['amount']
    assert 'reference' in call_args.kwargs


def test_create_payment_with_group_success(
    client,
    auth_headers,
    test_payment_data,
    test_application,
    test_group,
    test_products,
    db_session,
    mock_create_payment,
    mock_email_template,
):
    from app.api.applications.models import Application

    application = db_session.get(Application, test_payment_data['application_id'])
    application.status = ApplicationStatus.ACCEPTED.value
    application.scholarship_request = False
    application.discount_assigned = 100
    application.group_id = test_group.id
    db_session.commit()

    response = client.post('/payments/', json=test_payment_data, headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data['application_id'] == test_payment_data['application_id']
    assert data['amount'] == 0
    assert data['currency'] == 'USD'
    assert data['status'] == 'approved'

    payment = db_session.get(Payment, data['id'])
    assert payment.group_id == test_group.id


def test_create_payment_application_not_accepted(
    client, auth_headers, test_payment_data
):
    response = client.post('/payments/', json=test_payment_data, headers=auth_headers)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['detail'] == 'Application is not accepted'


def test_get_payments(
    client,
    auth_headers,
    test_payment_data,
    test_products,
    mock_create_payment,
    db_session,
):
    # First create a payment
    from app.api.applications.models import Application

    application = db_session.get(Application, test_payment_data['application_id'])
    application.status = ApplicationStatus.ACCEPTED.value
    application.scholarship_request = False
    application.discount_assigned = None
    db_session.commit()

    create_response = client.post(
        '/payments/', json=test_payment_data, headers=auth_headers
    )
    assert create_response.status_code == status.HTTP_200_OK

    # Now get all payments
    response = client.get('/payments/', headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 1
    assert data[0]['application_id'] == test_payment_data['application_id']


def test_get_payment_by_id(
    client,
    auth_headers,
    test_payment_data,
    test_products,
    mock_create_payment,
    db_session,
):
    # First create a payment
    from app.api.applications.models import Application

    application = db_session.get(Application, test_payment_data['application_id'])
    application.status = ApplicationStatus.ACCEPTED.value
    application.scholarship_request = False
    application.discount_assigned = None
    db_session.commit()

    create_response = client.post(
        '/payments/', json=test_payment_data, headers=auth_headers
    )
    payment_id = create_response.json()['id']

    response = client.get(f'/payments/{payment_id}', headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data['id'] == payment_id


def test_get_payment_other_citizen(
    client,
    auth_headers,
    test_payment_data,
    test_products,
    mock_create_payment,
    db_session,
):
    # First create a payment
    from app.api.applications.models import Application

    application = db_session.get(Application, test_payment_data['application_id'])
    application.status = ApplicationStatus.ACCEPTED.value
    application.scholarship_request = False
    application.discount_assigned = None
    db_session.commit()

    create_response = client.post(
        '/payments/', json=test_payment_data, headers=auth_headers
    )
    payment_id = create_response.json()['id']

    # Try to get payment with different citizen
    other_headers = get_auth_headers_for_citizen(999)
    response = client.get(f'/payments/{payment_id}', headers=other_headers)
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_create_payment_two_kids_same_ticket(
    client,
    auth_headers,
    test_application,  # Using the base application fixture
    test_products,
    db_session,
    mock_create_payment,
):
    """Test creating a payment with the same ticket for two different kids."""
    from app.api.applications.models import Application
    from app.api.products.models import Product

    # --- 1. Create and Accept Application ---
    response = client.post(
        '/applications/', json=test_application, headers=auth_headers
    )
    assert response.status_code == status.HTTP_201_CREATED
    application_data = response.json()
    application_id = application_data['id']

    # Mark application as accepted
    application = db_session.get(Application, application_id)
    assert application is not None
    application.status = ApplicationStatus.ACCEPTED.value
    application.scholarship_request = False
    application.discount_assigned = None
    db_session.commit()
    db_session.refresh(application)

    # --- 2. Add Two Kid Attendees ---
    kid1_data = {'name': 'Kid One', 'category': 'kid', 'age': 10}
    response = client.post(
        f'/applications/{application_id}/attendees',
        json=kid1_data,
        headers=auth_headers,
    )
    assert response.status_code == status.HTTP_200_OK
    updated_application = response.json()
    kid1_id = next(
        att['id']
        for att in updated_application['attendees']
        if att['name'] == 'Kid One'
    )

    kid2_data = {'name': 'Kid Two', 'category': 'kid', 'age': 12}
    response = client.post(
        f'/applications/{application_id}/attendees',
        json=kid2_data,
        headers=auth_headers,
    )
    assert response.status_code == status.HTTP_200_OK
    updated_application = response.json()
    kid2_id = next(
        att['id']
        for att in updated_application['attendees']
        if att['name'] == 'Kid Two'
    )

    # --- 3. Define Payment Payload ---
    kid_product_id = 2  # Assuming product ID 2 is for kids
    payment_data = {
        'application_id': application_id,
        'products': [
            {'product_id': kid_product_id, 'attendee_id': kid1_id, 'quantity': 1},
            {'product_id': kid_product_id, 'attendee_id': kid2_id, 'quantity': 1},
        ],
    }

    # --- 4. Create Payment ---
    response = client.post('/payments/', json=payment_data, headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK

    # --- 5. Assertions ---
    data = response.json()
    assert data['application_id'] == application_id
    assert data['status'] == 'pending'
    assert data['external_id'] is not None
    assert data['checkout_url'] is not None

    # Verify amount (assumes product ID 2 exists and has a price)
    kid_product = db_session.get(Product, kid_product_id)
    assert kid_product is not None, f'Product with ID {kid_product_id} not found in DB.'
    expected_amount = kid_product.price * 2
    assert data['amount'] == expected_amount

    # Verify simplefi.create_payment mock call
    mock_create_payment.assert_called_once()
    call_args = mock_create_payment.call_args
    assert call_args.args[0] == expected_amount
    assert 'reference' in call_args.kwargs


def test_simplefi_webhook_payment_approval(
    client,
    auth_headers,
    test_payment_data,
    test_products,
    mock_create_payment,
    mock_simplefi_response,
    mock_webhook_cache,
    mock_email_template,
    db_session,
):
    # First create a payment
    from app.api.applications.models import Application

    application = db_session.get(Application, test_payment_data['application_id'])
    application.status = ApplicationStatus.ACCEPTED.value
    application.scholarship_request = False
    application.discount_assigned = None
    db_session.commit()

    create_response = client.post(
        '/payments/', json=test_payment_data, headers=auth_headers
    )
    payment = create_response.json()

    webhook_data = {
        'id': 'test_id',
        'event_type': 'new_payment',
        'entity_type': 'payment_request',
        'entity_id': payment['external_id'],
        'data': {
            'payment_request': {
                'id': mock_simplefi_response['id'],
                'order_id': 1,
                'amount': 100.0,
                'amount_paid': 100.0,
                'currency': 'USD',
                'reference': {},
                'status': 'approved',
                'status_detail': 'correct',
                'transactions': [],
                'card_payment': None,
                'payments': [],
            },
            'new_payment': {
                'coin': 'ETH',
                'hash': 'test_hash',
                'amount': payment['amount'],
                'paid_at': '2024-01-01T00:00:00Z',
            },
        },
    }

    response = client.post('/webhooks/simplefi', json=webhook_data)
    assert response.status_code == status.HTTP_200_OK

    # Verify payment was approved
    payment_response = client.get(f'/payments/{payment["id"]}', headers=auth_headers)
    assert payment_response.json()['status'] == 'approved'
    assert payment_response.json()['source'] == PaymentSource.SIMPLEFI.value


def test_simplefi_webhook_payment_expired(
    client,
    auth_headers,
    test_payment_data,
    test_products,
    mock_create_payment,
    mock_simplefi_response,
    mock_webhook_cache,
    db_session,
):
    # First create a payment
    from app.api.applications.models import Application

    application = db_session.get(Application, test_payment_data['application_id'])
    application.status = ApplicationStatus.ACCEPTED.value
    application.scholarship_request = False
    application.discount_assigned = None
    db_session.commit()

    create_response = client.post(
        '/payments/', json=test_payment_data, headers=auth_headers
    )
    assert create_response.status_code == status.HTTP_200_OK
    payment = create_response.json()

    webhook_data = {
        'id': 'test_id',
        'event_type': 'new_payment',
        'entity_type': 'payment_request',
        'entity_id': payment['external_id'],
        'data': {
            'payment_request': {
                'id': mock_simplefi_response['id'],
                'order_id': 1,
                'amount': 100.0,
                'amount_paid': 100.0,
                'currency': 'USD',
                'reference': {},
                'status': 'expired',
                'status_detail': 'not_paid',
                'transactions': [],
                'card_payment': None,
                'payments': [],
            },
            'new_payment': {
                'coin': 'USD',
                'hash': 'test_hash',
                'amount': payment['amount'],
                'paid_at': '2024-01-01T00:00:00Z',
            },
        },
    }

    response = client.post('/webhooks/simplefi', json=webhook_data)
    assert response.status_code == status.HTTP_200_OK

    # Verify payment was expired
    payment_response = client.get(f'/payments/{payment["id"]}', headers=auth_headers)
    assert payment_response.json()['status'] == 'expired'


def test_simplefi_webhook_invalid_event_type(
    client,
    mock_simplefi_response,
    mock_webhook_cache,
):
    webhook_data = {
        'id': 'test_id',
        'event_type': 'invalid_event_type',
        'entity_type': 'payment_request',
        'entity_id': '123',
        'data': {
            'payment_request': {
                'id': mock_simplefi_response['id'],
                'order_id': 1,
                'amount': 100.0,
                'amount_paid': 100.0,
                'currency': 'USD',
                'reference': {},
                'status': 'expired',
                'status_detail': 'not_paid',
                'transactions': [],
                'card_payment': None,
                'payments': [],
            },
            'new_payment': {
                'coin': 'USD',
                'hash': 'test_hash',
                'amount': 100.0,
                'paid_at': '2024-01-01T00:00:00Z',
            },
        },
    }

    response = client.post('/webhooks/simplefi', json=webhook_data)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    err_msg = 'Event type is not new_payment or new_card_payment'
    assert response.json()['detail'] == err_msg


def test_use_coupon_code(
    client,
    auth_headers,
    test_coupon_code,
    test_payment_data,
    test_products,
    mock_create_payment,
    mock_email_template,
    db_session,
):
    test_coupon_code.current_uses = 0
    test_coupon_code.max_uses = 1
    test_coupon_code.discount_value = 100
    db_session.commit()

    # First create a payment
    from app.api.applications.models import Application

    application = db_session.get(Application, test_payment_data['application_id'])
    application.status = ApplicationStatus.ACCEPTED.value
    application.scholarship_request = False
    application.discount_assigned = None
    db_session.commit()

    assert application.popup_city_id == test_coupon_code.popup_city_id
    test_payment_data['coupon_code'] = test_coupon_code.code

    response = client.post('/payments/', json=test_payment_data, headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()['status'] == 'approved'

    # Verify discount code was used
    assert test_coupon_code.current_uses == 1


def _approve_payment(client, payment, mock_simplefi_response):
    webhook_data = {
        'id': 'test_id',
        'event_type': 'new_payment',
        'entity_type': 'payment_request',
        'entity_id': payment['external_id'],
        'data': {
            'payment_request': {
                'id': mock_simplefi_response['id'],
                'order_id': 1,
                'amount': 100.0,
                'amount_paid': 100.0,
                'currency': 'USD',
                'reference': {},
                'status': 'approved',
                'status_detail': 'correct',
                'transactions': [],
                'card_payment': None,
                'payments': [],
            },
            'new_payment': {
                'coin': 'ETH',
                'hash': 'test_hash',
                'amount': payment['amount'],
                'paid_at': '2024-01-01T00:00:00Z',
            },
        },
    }

    response = client.post('/webhooks/simplefi', json=webhook_data)
    assert response.status_code == status.HTTP_200_OK


def test_edit_passes_payment(
    client,
    auth_headers,
    test_payment_data,
    test_application,
    test_products,
    mock_create_payment,
    mock_webhook_cache,
    mock_email_template,
    db_session,
):
    from app.api.applications.models import Application

    application = db_session.get(Application, test_payment_data['application_id'])
    application.status = ApplicationStatus.ACCEPTED.value
    application.scholarship_request = False
    application.discount_assigned = None
    application.credit = 0

    mock_response = {
        'id': 'sf1',
        'status': 'pending',
        'checkout_url': 'https://test.checkout.url',
    }
    mock_create_payment.return_value = mock_response

    # Create initial payment
    response = client.post('/payments/', json=test_payment_data, headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK

    _approve_payment(client, response.json(), mock_response)

    mock_response['id'] = 'sf2'

    # Create edit passes payment
    edit_payment_data = test_payment_data.copy()
    edit_payment_data['edit_passes'] = True
    edit_payment_data['products'] = [
        {
            'product_id': 2,
            'attendee_id': 1,
            'quantity': 1,
        }
    ]
    response = client.post('/payments/', json=edit_payment_data, headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()['status'] == 'pending'

    _approve_payment(client, response.json(), mock_response)

    payment = client.get(f'/payments/{response.json()["id"]}', headers=auth_headers)
    assert payment.json()['status'] == 'approved'
    # Verify application state
    db_session.refresh(application)
    assert application.credit == 0
    for attendee in application.attendees:
        if attendee.id == 1:
            assert len(attendee.attendee_products) == 1
            assert attendee.attendee_products[0].product_id == 2
            assert attendee.attendee_products[0].quantity == 1
        else:
            assert len(attendee.attendee_products) == 0


def test_edit_passes_payment_cheaper_product(
    client,
    auth_headers,
    test_payment_data,
    test_application,
    test_products,
    mock_create_payment,
    mock_webhook_cache,
    mock_email_template,
    db_session,
):
    from app.api.applications.models import Application

    application = db_session.get(Application, test_payment_data['application_id'])
    application.status = ApplicationStatus.ACCEPTED.value
    application.scholarship_request = False
    application.discount_assigned = None
    initial_credit = 10
    application.credit = initial_credit

    mock_response = {
        'id': 'sf1',
        'status': 'pending',
        'checkout_url': 'https://test.checkout.url',
    }
    mock_create_payment.return_value = mock_response

    product_1 = test_products[0]
    product_2 = test_products[1]
    test_payment_data['products'] = [
        {
            'product_id': product_1.id,
            'attendee_id': 1,
            'quantity': 1,
        },
        {
            'product_id': product_2.id,
            'attendee_id': 1,
            'quantity': 1,
        },
    ]

    # Create initial payment
    response = client.post('/payments/', json=test_payment_data, headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()['status'] == 'pending'
    _approve_payment(client, response.json(), mock_response)

    mock_response['id'] = 'sf2'

    # Create edit passes payment
    edit_payment_data = test_payment_data.copy()
    edit_payment_data['edit_passes'] = True
    edit_payment_data['products'] = [
        {
            'product_id': product_1.id,
            'attendee_id': 1,
            'quantity': 1,
        }
    ]
    response = client.post('/payments/', json=edit_payment_data, headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    payment = response.json()

    assert payment['status'] == 'approved'
    # Verify application state
    db_session.refresh(application)
    assert application.credit == initial_credit + product_2.price
    for attendee in application.attendees:
        if attendee.id == 1:
            assert len(attendee.attendee_products) == 1
            assert attendee.attendee_products[0].product_id == product_1.id
            assert attendee.attendee_products[0].quantity == 1
        else:
            assert len(attendee.attendee_products) == 0


def test_simplefi_installment_plan_completed_webhook(
    client,
    auth_headers,
    test_payment_data,
    test_products,
    mock_create_payment,
    mock_webhook_cache,
    mock_email_template,
    db_session,
):
    """Test that installment_plan_completed webhook approves payment."""
    from app.api.applications.models import Application

    application = db_session.get(Application, test_payment_data['application_id'])
    application.status = ApplicationStatus.ACCEPTED.value
    application.scholarship_request = False
    application.discount_assigned = None
    db_session.commit()

    # Create a payment with installments
    mock_response = {
        'id': 'installment_plan_123',
        'status': 'pending',
        'checkout_url': 'https://test.checkout.url',
    }
    mock_create_payment.return_value = mock_response

    test_payment_data['installments'] = 3
    response = client.post('/payments/', json=test_payment_data, headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    payment = response.json()

    # Mark as installment plan in DB
    db_payment = db_session.get(Payment, payment['id'])
    db_payment.is_installment_plan = True
    db_payment.installments_total = 3
    db_session.commit()

    # Send installment_plan_completed webhook
    webhook_data = {
        'id': 'webhook_123',
        'event_type': 'installment_plan_completed',
        'entity_type': 'installment_plan',
        'entity_id': 'installment_plan_123',
        'merchant_id': 'merchant_abc',
        'data': {
            'installment_plan': {
                'id': 'installment_plan_123',
                'status': 'completed',
                'paid_installments_count': 3,
                'number_of_installments': 3,
                'user_email': 'test@example.com',
                'payment_method': 'card',
            }
        },
    }

    response = client.post('/webhooks/simplefi', json=webhook_data)
    assert response.status_code == status.HTTP_200_OK
    assert (
        response.json()['message'] == 'Installment plan payment approved successfully'
    )

    # Verify payment was approved
    payment_response = client.get(f'/payments/{payment["id"]}', headers=auth_headers)
    assert payment_response.json()['status'] == 'approved'
    assert payment_response.json()['installments_paid'] == 3


def test_simplefi_installment_webhook_duplicate(
    client,
    auth_headers,
    test_payment_data,
    test_products,
    mock_create_payment,
    mock_email_template,
    db_session,
):
    """Test that duplicate installment webhooks are rejected."""
    from app.api.applications.models import Application

    application = db_session.get(Application, test_payment_data['application_id'])
    application.status = ApplicationStatus.ACCEPTED.value
    application.scholarship_request = False
    application.discount_assigned = None
    db_session.commit()

    mock_response = {
        'id': 'installment_plan_456',
        'status': 'pending',
        'checkout_url': 'https://test.checkout.url',
    }
    mock_create_payment.return_value = mock_response

    response = client.post('/payments/', json=test_payment_data, headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    payment = response.json()

    db_payment = db_session.get(Payment, payment['id'])
    db_payment.is_installment_plan = True
    db_payment.installments_total = 3
    db_session.commit()

    webhook_data = {
        'id': 'webhook_456',
        'event_type': 'installment_plan_completed',
        'entity_type': 'installment_plan',
        'entity_id': 'installment_plan_456',
        'data': {
            'installment_plan': {
                'id': 'installment_plan_456',
                'status': 'completed',
                'paid_installments_count': 3,
                'number_of_installments': 3,
                'user_email': 'test@example.com',
                'payment_method': 'card',
            }
        },
    }

    # First webhook should succeed
    response = client.post('/webhooks/simplefi', json=webhook_data)
    assert response.status_code == status.HTTP_200_OK

    # Second webhook should be marked as duplicate
    response = client.post('/webhooks/simplefi', json=webhook_data)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()['message'] == 'Webhook already processed'


def test_simplefi_installment_webhook_payment_not_found(
    client,
    mock_webhook_cache,
):
    """Test that 404 is returned when payment is not found."""
    webhook_data = {
        'id': 'webhook_789',
        'event_type': 'installment_plan_completed',
        'entity_type': 'installment_plan',
        'entity_id': 'nonexistent_plan_id',
        'data': {
            'installment_plan': {
                'id': 'nonexistent_plan_id',
                'status': 'completed',
                'paid_installments_count': 3,
                'number_of_installments': 3,
                'user_email': 'test@example.com',
                'payment_method': 'card',
            }
        },
    }

    response = client.post('/webhooks/simplefi', json=webhook_data)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()['detail'] == 'Payment not found'


def test_simplefi_installment_webhook_already_approved(
    client,
    auth_headers,
    test_payment_data,
    test_products,
    mock_create_payment,
    mock_webhook_cache,
    mock_email_template,
    db_session,
):
    """Test that already approved payments return 200 (idempotent)."""
    from app.api.applications.models import Application

    application = db_session.get(Application, test_payment_data['application_id'])
    application.status = ApplicationStatus.ACCEPTED.value
    application.scholarship_request = False
    application.discount_assigned = None
    db_session.commit()

    mock_response = {
        'id': 'installment_plan_approved',
        'status': 'pending',
        'checkout_url': 'https://test.checkout.url',
    }
    mock_create_payment.return_value = mock_response

    response = client.post('/payments/', json=test_payment_data, headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    payment = response.json()

    # Mark payment as already approved
    db_payment = db_session.get(Payment, payment['id'])
    db_payment.is_installment_plan = True
    db_payment.installments_total = 3
    db_payment.status = 'approved'
    db_session.commit()

    webhook_data = {
        'id': 'webhook_approved',
        'event_type': 'installment_plan_completed',
        'entity_type': 'installment_plan',
        'entity_id': 'installment_plan_approved',
        'data': {
            'installment_plan': {
                'id': 'installment_plan_approved',
                'status': 'completed',
                'paid_installments_count': 3,
                'number_of_installments': 3,
                'user_email': 'test@example.com',
                'payment_method': 'card',
            }
        },
    }

    response = client.post('/webhooks/simplefi', json=webhook_data)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()['message'] == 'Payment already approved'
