import base64
import json

from app.core import x402


def _encode(payload: dict) -> str:
    return base64.b64encode(json.dumps(payload).encode()).decode()


def _make_payment_body(application_id, attendee_id, product_id):
    return {
        'application_id': application_id,
        'products': [
            {
                'product_id': product_id,
                'attendee_id': attendee_id,
                'quantity': 1,
            }
        ],
    }


MOCK_PAYMENT_SIGNATURE = _encode({'type': 'x402-payment', 'tx': '0xtest'})
MOCK_TX_HASH = '0xabc123'
AGENT_BUY_URL = 'http://testserver/agent/buy-ticket'


class TestAgentBuyTicketAuth:
    """Test authentication requirements."""

    def test_no_jwt_returns_401(self, client):
        response = client.post(
            '/agent/buy-ticket', json={'application_id': 1, 'products': []}
        )
        assert response.status_code == 401

    def test_no_payment_header_returns_402(
        self,
        client,
        auth_headers,
        test_attendee,
        test_products,
        mock_email_template,
    ):
        body = _make_payment_body(
            test_attendee.application_id, test_attendee.id, test_products[0].id
        )
        response = client.post('/agent/buy-ticket', json=body, headers=auth_headers)
        assert response.status_code == 402

        # Check PAYMENT-REQUIRED header exists
        assert 'PAYMENT-REQUIRED' in response.headers

        # Decode and verify the 402 header
        decoded = x402.decode_header(response.headers['PAYMENT-REQUIRED'])
        assert decoded['x402Version'] == 2
        assert 'accepts' in decoded
        assert len(decoded['accepts']) > 0
        assert 'extensions' in decoded
        assert 'agentkit' in decoded['extensions']

        # Verify agentkit extension has correct structure per AgentKit spec
        ak_ext = decoded['extensions']['agentkit']
        assert 'info' in ak_ext
        assert 'supportedChains' in ak_ext
        assert 'schema' in ak_ext
        assert ak_ext['info']['version'] == '1'
        assert 'nonce' in ak_ext['info']
        assert 'issuedAt' in ak_ext['info']
        assert len(ak_ext['supportedChains']) > 0
        assert 'mode' in ak_ext
        assert ak_ext['mode']['type'] == 'discount'
        assert ak_ext['mode']['percent'] == 10

        # Verify requirements use v2 field names
        req = decoded['accepts'][0]
        assert 'amount' in req
        assert 'maxAmountRequired' not in req
        assert req['extra']['assetTransferMethod'] == 'eip3009'

        # Verify the JSON body has top-level resource (v2 spec)
        body = response.json()
        assert body['x402Version'] == 2
        assert 'resource' in body
        assert 'url' in body['resource']
        assert 'description' in body['resource']
        assert 'mimeType' in body['resource']


class TestAgentBuyTicketValidation:
    """Test request validation."""

    def test_application_not_accepted_returns_400(
        self,
        client,
        db_session,
        test_citizen,
        test_popup_city,
        test_products,
        auth_headers,
        mock_email_template,
    ):
        from app.api.applications.models import Application

        app_obj = Application(
            first_name='Test',
            last_name='User',
            email=test_citizen.primary_email,
            citizen_id=test_citizen.id,
            popup_city_id=test_popup_city.id,
            _status='pending',
        )
        db_session.add(app_obj)
        db_session.commit()

        from app.api.attendees.models import Attendee

        attendee = Attendee(
            application_id=app_obj.id,
            name='Test',
            category='main',
            email='test@example.com',
            check_in_code='CODE1',
        )
        db_session.add(attendee)
        db_session.commit()

        body = _make_payment_body(app_obj.id, attendee.id, test_products[0].id)
        response = client.post(
            '/agent/buy-ticket',
            json=body,
            headers={**auth_headers, 'PAYMENT-SIGNATURE': MOCK_PAYMENT_SIGNATURE},
        )
        assert response.status_code == 400
        assert 'not accepted' in response.json()['detail'].lower()

    def test_invalid_products_returns_400(
        self,
        client,
        auth_headers,
        test_attendee,
        test_products,
        mock_email_template,
    ):
        body = _make_payment_body(test_attendee.application_id, test_attendee.id, 99999)
        response = client.post(
            '/agent/buy-ticket',
            json=body,
            headers={**auth_headers, 'PAYMENT-SIGNATURE': MOCK_PAYMENT_SIGNATURE},
        )
        assert response.status_code == 400


class TestAgentBuyTicketSuccess:
    """Test successful payment flows."""

    def test_successful_payment_no_agentkit(
        self,
        client,
        db_session,
        auth_headers,
        test_attendee,
        test_products,
        mock_email_template,
        monkeypatch,
    ):
        monkeypatch.setattr(
            'app.core.x402.verify_payment',
            lambda p, r: {'isValid': True},
        )
        monkeypatch.setattr(
            'app.core.x402.settle_payment',
            lambda p, r: {
                'success': True,
                'transaction': MOCK_TX_HASH,
                'network': 'eip155:84532',
            },
        )

        body = _make_payment_body(
            test_attendee.application_id, test_attendee.id, test_products[0].id
        )
        response = client.post(
            '/agent/buy-ticket',
            json=body,
            headers={**auth_headers, 'PAYMENT-SIGNATURE': MOCK_PAYMENT_SIGNATURE},
        )

        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'approved'
        assert data['source'] == 'x402'
        assert data['currency'] == 'USDC'
        assert data['external_id'] == MOCK_TX_HASH
        assert len(data['products_snapshot']) == 1
        assert data['products_snapshot'][0]['product_name'] == test_products[0].name

        # Verify PAYMENT-RESPONSE header
        assert 'PAYMENT-RESPONSE' in response.headers

        # Verify AttendeeProduct records created
        from app.api.attendees.models import AttendeeProduct

        ap = (
            db_session.query(AttendeeProduct)
            .filter(
                AttendeeProduct.attendee_id == test_attendee.id,
                AttendeeProduct.product_id == test_products[0].id,
            )
            .first()
        )
        assert ap is not None

    def test_successful_payment_with_agentkit_discount(
        self,
        client,
        db_session,
        auth_headers,
        test_attendee,
        test_products,
        mock_email_template,
        monkeypatch,
    ):
        monkeypatch.setattr(
            'app.core.x402.verify_payment',
            lambda p, r: {'isValid': True},
        )
        tx_hash_ak = '0xagentkit_tx'
        monkeypatch.setattr(
            'app.core.x402.settle_payment',
            lambda p, r: {
                'success': True,
                'transaction': tx_hash_ak,
                'network': 'eip155:84532',
            },
        )
        monkeypatch.setattr(
            'app.core.agentkit.verify_agentkit_signature',
            lambda p: '0xTestWallet',
        )
        monkeypatch.setattr(
            'app.core.agentkit.lookup_human',
            lambda addr: '0x1234',
        )

        agentkit_payload = _encode(_make_agentkit_payload())

        body = _make_payment_body(
            test_attendee.application_id, test_attendee.id, test_products[0].id
        )
        response = client.post(
            '/agent/buy-ticket',
            json=body,
            headers={
                **auth_headers,
                'PAYMENT-SIGNATURE': MOCK_PAYMENT_SIGNATURE,
                'AGENTKIT': agentkit_payload,
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Price should be 10% less than 100.0 (product price)
        assert data['amount'] == 90.0

    def test_unverified_agent_pays_full_price(
        self,
        client,
        db_session,
        auth_headers,
        test_attendee,
        test_products,
        mock_email_template,
        monkeypatch,
    ):
        tx_hash_uv = '0xunverified_tx'
        monkeypatch.setattr(
            'app.core.x402.verify_payment',
            lambda p, r: {'isValid': True},
        )
        monkeypatch.setattr(
            'app.core.x402.settle_payment',
            lambda p, r: {
                'success': True,
                'transaction': tx_hash_uv,
                'network': 'eip155:84532',
            },
        )
        monkeypatch.setattr(
            'app.core.agentkit.verify_agentkit_signature',
            lambda p: '0xUnverifiedWallet',
        )
        monkeypatch.setattr(
            'app.core.agentkit.lookup_human',
            lambda addr: None,
        )

        agentkit_payload = _encode(_make_agentkit_payload())

        body = _make_payment_body(
            test_attendee.application_id, test_attendee.id, test_products[0].id
        )
        response = client.post(
            '/agent/buy-ticket',
            json=body,
            headers={
                **auth_headers,
                'PAYMENT-SIGNATURE': MOCK_PAYMENT_SIGNATURE,
                'AGENTKIT': agentkit_payload,
            },
        )

        assert response.status_code == 200
        data = response.json()
        # Full price — agent not verified
        assert data['amount'] == 100.0


class TestAgentBuyTicketErrors:
    """Test error conditions."""

    def test_verify_fails_returns_402(
        self,
        client,
        auth_headers,
        test_attendee,
        test_products,
        mock_email_template,
        monkeypatch,
    ):
        monkeypatch.setattr(
            'app.core.x402.verify_payment',
            lambda p, r: {'isValid': False, 'invalidReason': 'Insufficient funds'},
        )

        body = _make_payment_body(
            test_attendee.application_id, test_attendee.id, test_products[0].id
        )
        response = client.post(
            '/agent/buy-ticket',
            json=body,
            headers={**auth_headers, 'PAYMENT-SIGNATURE': MOCK_PAYMENT_SIGNATURE},
        )
        assert response.status_code == 402
        assert 'Insufficient funds' in response.json()['detail']

    def test_settle_fails_returns_500_no_db_records(
        self,
        client,
        db_session,
        auth_headers,
        test_attendee,
        test_products,
        mock_email_template,
        monkeypatch,
    ):
        monkeypatch.setattr(
            'app.core.x402.verify_payment',
            lambda p, r: {'isValid': True},
        )
        monkeypatch.setattr(
            'app.core.x402.settle_payment',
            lambda p, r: {'success': False},
        )

        body = _make_payment_body(
            test_attendee.application_id, test_attendee.id, test_products[0].id
        )
        response = client.post(
            '/agent/buy-ticket',
            json=body,
            headers={**auth_headers, 'PAYMENT-SIGNATURE': MOCK_PAYMENT_SIGNATURE},
        )
        assert response.status_code == 500

        # No payment records should exist
        from app.api.payments.models import Payment

        payments = db_session.query(Payment).all()
        assert len(payments) == 0

    def test_idempotency_duplicate_tx_hash(
        self,
        client,
        db_session,
        auth_headers,
        test_attendee,
        test_products,
        mock_email_template,
        monkeypatch,
    ):
        tx_hash_dup = '0xdup_tx'
        monkeypatch.setattr(
            'app.core.x402.verify_payment',
            lambda p, r: {'isValid': True},
        )
        monkeypatch.setattr(
            'app.core.x402.settle_payment',
            lambda p, r: {
                'success': True,
                'transaction': tx_hash_dup,
                'network': 'eip155:84532',
            },
        )

        body = _make_payment_body(
            test_attendee.application_id, test_attendee.id, test_products[0].id
        )
        headers = {**auth_headers, 'PAYMENT-SIGNATURE': MOCK_PAYMENT_SIGNATURE}

        # First request
        r1 = client.post('/agent/buy-ticket', json=body, headers=headers)
        assert r1.status_code == 200

        # Second request with same tx hash
        r2 = client.post('/agent/buy-ticket', json=body, headers=headers)
        assert r2.status_code == 200
        assert r2.json()['id'] == r1.json()['id']


class TestAgentBuyTicketCoupon:
    """Test coupon code integration."""

    def test_coupon_code_discount(
        self,
        client,
        db_session,
        auth_headers,
        test_attendee,
        test_products,
        test_coupon_code,
        mock_email_template,
        monkeypatch,
    ):
        tx_hash_coupon = '0xcoupon_tx'
        monkeypatch.setattr(
            'app.core.x402.verify_payment',
            lambda p, r: {'isValid': True},
        )
        monkeypatch.setattr(
            'app.core.x402.settle_payment',
            lambda p, r: {
                'success': True,
                'transaction': tx_hash_coupon,
                'network': 'eip155:84532',
            },
        )

        body = _make_payment_body(
            test_attendee.application_id, test_attendee.id, test_products[0].id
        )
        body['coupon_code'] = 'TEST10'

        response = client.post(
            '/agent/buy-ticket',
            json=body,
            headers={**auth_headers, 'PAYMENT-SIGNATURE': MOCK_PAYMENT_SIGNATURE},
        )
        assert response.status_code == 200
        data = response.json()
        # 10% discount on 100.0 = 90.0
        assert data['amount'] == 90.0


class TestAgentBuyTicketEmail:
    """Test confirmation email is sent."""

    def test_confirmation_email_sent(
        self,
        client,
        db_session,
        auth_headers,
        test_attendee,
        test_products,
        mock_email_template,
        monkeypatch,
    ):
        tx_hash_email = '0xemail_tx'
        monkeypatch.setattr(
            'app.core.x402.verify_payment',
            lambda p, r: {'isValid': True},
        )
        monkeypatch.setattr(
            'app.core.x402.settle_payment',
            lambda p, r: {
                'success': True,
                'transaction': tx_hash_email,
                'network': 'eip155:84532',
            },
        )

        email_sent = []

        def mock_send_mail(**kwargs):
            email_sent.append(kwargs)

        monkeypatch.setattr(
            'app.api.email_logs.crud.email_log.send_mail',
            mock_send_mail,
        )

        body = _make_payment_body(
            test_attendee.application_id, test_attendee.id, test_products[0].id
        )
        response = client.post(
            '/agent/buy-ticket',
            json=body,
            headers={**auth_headers, 'PAYMENT-SIGNATURE': MOCK_PAYMENT_SIGNATURE},
        )
        assert response.status_code == 200
        assert len(email_sent) == 1
        assert email_sent[0]['entity_type'] == 'payment'


def _make_agentkit_payload() -> dict:
    """Create a valid AgentKit payload with all required fields for tests."""
    import os
    from datetime import datetime, timezone

    return {
        'domain': 'testserver',
        'address': '0xTestWallet',
        'uri': AGENT_BUY_URL,
        'version': '1',
        'chainId': 'eip155:84532',
        'type': 'eip191',
        'nonce': os.urandom(16).hex(),
        'issuedAt': datetime.now(timezone.utc).isoformat(),
        'signature': '0xsig',
    }
