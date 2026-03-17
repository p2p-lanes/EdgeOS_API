from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.coupon_codes.crud import coupon_code as coupon_code_crud
from app.api.payments.crud import payment as payment_crud
from app.api.payments.models import Payment, PaymentProduct
from app.api.payments import schemas as payment_schemas
from app.api.payments.schemas import PaymentCreate, PaymentSource
from app.api.products.models import Product
from app.core import agentkit, x402
from app.core.config import settings
from app.core.database import get_db
from app.core.logger import logger
from app.core.payments_utils import _prepare_payment_response
from app.core.security import TokenData, get_current_user

router = APIRouter()


@router.post('/buy-ticket', response_model=payment_schemas.Payment)
def buy_ticket(
    body: PaymentCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    payment_signature: str | None = Header(None, alias='PAYMENT-SIGNATURE'),
):
    # Force edit_passes off for agent purchases
    body.edit_passes = False

    # Step 1: Validate & calculate price using existing payment logic
    payment_preview, application, valid_products, insurance_per_item = (
        _prepare_payment_response(db, body, current_user)
    )

    price_usd = payment_preview.amount if payment_preview.amount is not None else 0.0
    resource_url = str(request.url)
    domain = (
        urlparse(settings.BACKEND_URL or str(request.base_url)).hostname or 'localhost'
    )

    # Step 2: No payment header → return 402 with discount info
    if not payment_signature:
        agentkit_ext = agentkit.build_agentkit_challenge(domain, resource_url)
        ak_info = agentkit_ext['info']
        logger.info(
            '402 challenge: nonce=%s issuedAt=%s domain=%s',
            ak_info['nonce'],
            ak_info['issuedAt'],
            ak_info['domain'],
        )
        payment_required_body = x402.build_payment_required_response(
            price_usd=price_usd,
            resource_url=resource_url,
            description=f'Ticket purchase for {application.popup_city.name}',
            agentkit_ext=agentkit_ext,
        )
        payment_required_header = x402.encode_header(payment_required_body)
        return JSONResponse(
            status_code=402,
            content=payment_required_body,
            headers={'PAYMENT-REQUIRED': payment_required_header},
        )

    # Step 3: Decode payment payload
    try:
        payment_payload = x402.decode_header(payment_signature)
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid PAYMENT-SIGNATURE header')

    # Step 4: Check agentkit header (optional).
    # If verified, apply discount BEFORE verify/settle so the agent pays less.
    agentkit_header = request.headers.get('AGENTKIT')
    if agentkit_header:
        try:
            agentkit_payload = agentkit.parse_agentkit_header(agentkit_header)
            logger.info(
                'AgentKit header: address=%s domain=%s nonce=%s chainId=%s type=%s',
                agentkit_payload.get('address'),
                agentkit_payload.get('domain'),
                agentkit_payload.get('nonce'),
                agentkit_payload.get('chainId'),
                agentkit_payload.get('type'),
            )
            if agentkit.validate_agentkit_message(
                agentkit_payload, domain, resource_url
            ):
                signer = agentkit.verify_agentkit_signature(agentkit_payload)
                if signer:
                    human_id = agentkit.lookup_human(signer)
                    if agentkit.is_verified_agent(human_id):
                        discount_pct = settings.AGENTKIT_DISCOUNT_PERCENT
                        price_usd = round(price_usd * (1 - discount_pct / 100), 2)
                        logger.info(
                            'AgentKit verified agent %s, %d%% discount applied, price: %s',
                            signer,
                            discount_pct,
                            price_usd,
                        )
        except Exception as e:
            logger.warning('AgentKit header processing failed: %s', e)

    # Step 5: Verify payment against the (possibly discounted) price
    requirements = x402.build_payment_requirements(price_usd)
    try:
        verify_result = x402.verify_payment(payment_payload, requirements)
    except Exception as e:
        logger.error('x402 verify failed: %s', e)
        raise HTTPException(status_code=402, detail='Payment verification failed')

    if not verify_result.get('isValid'):
        raise HTTPException(
            status_code=402,
            detail=verify_result.get('invalidReason', 'Payment invalid'),
        )

    # Step 6: Settle payment at the (possibly discounted) price
    try:
        settle_result = x402.settle_payment(payment_payload, requirements)
    except Exception as e:
        logger.error('x402 settle failed: %s', e)
        raise HTTPException(status_code=500, detail='Payment settlement failed')

    logger.info('x402 settle result: %s', settle_result)
    if not settle_result.get('success'):
        raise HTTPException(status_code=500, detail='Payment settlement unsuccessful')

    tx_hash = settle_result.get('transaction', '')
    network = settle_result.get('network', settings.X402_NETWORK)

    # Step 7: Idempotency check
    existing = db.query(Payment).filter(Payment.external_id == tx_hash).first()
    if existing:
        return existing

    # Step 8: Create DB records (mirrors CRUDPayment.create)
    db_payment = Payment(
        application_id=body.application_id,
        external_id=tx_hash,
        status='approved',
        amount=price_usd,
        currency='USDC',
        source=PaymentSource.X402.value,
        edit_passes=False,
        coupon_code_id=payment_preview.coupon_code_id,
        coupon_code=payment_preview.coupon_code,
        discount_value=payment_preview.discount_value,
    )
    db.add(db_payment)
    db.flush()

    # Create PaymentProduct snapshots
    if body.products:
        product_ids = [p.product_id for p in body.products]
        products_data = {
            p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()
        }

        for product in body.products:
            product_data = products_data[product.product_id]
            item_key = (product.product_id, product.attendee_id)

            if product_data.min_price is not None:
                snapshot_price = product.custom_amount
            else:
                snapshot_price = product_data.price

            has_insurance = (
                body.insurance and product_data.insurance_percentage is not None
            )
            pp = PaymentProduct(
                payment_id=db_payment.id,
                product_id=product.product_id,
                attendee_id=product.attendee_id,
                quantity=product.quantity,
                product_name=product_data.name,
                product_description=product_data.description,
                product_price=snapshot_price,
                product_category=product_data.category,
                insurance_applied=has_insurance,
                insurance_price=insurance_per_item.get(item_key),
            )
            db.add(pp)

        db.flush()
        db.refresh(db_payment)

    # Add products to attendees
    payment_crud._add_products_to_attendees(db_payment)

    # Use coupon if provided
    if db_payment.coupon_code_id is not None:
        coupon_code_crud.use_coupon_code(db, db_payment.coupon_code_id)

    # Create ambassador group
    group = payment_crud._create_ambassador_group(db, db_payment)

    db.commit()
    db.refresh(db_payment)

    # Send confirmation email
    payment_crud._send_payment_confirmed_email(db_payment, group)

    # Step 9: Return 200 with payment response header + payment data
    response.headers['PAYMENT-RESPONSE'] = x402.encode_header(
        {
            'success': True,
            'transaction': tx_hash,
            'network': network,
        }
    )
    return db_payment
