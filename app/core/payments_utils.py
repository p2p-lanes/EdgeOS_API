from datetime import datetime
from typing import List, Tuple

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.applications.crud import application as application_crud
from app.api.applications.models import Application
from app.api.applications.schemas import ApplicationStatus
from app.api.coupon_codes.crud import coupon_code as coupon_code_crud
from app.api.payments import schemas
from app.api.payments.schemas import PaymentPreview
from app.api.products.crud import product as product_crud
from app.api.products.models import Product
from app.api.products.schemas import ProductFilter
from app.core import simplefi
from app.core.logger import logger
from app.core.security import TokenData


def _get_discounted_price(price: float, discount_value: float) -> float:
    return round(price * (1 - discount_value / 100), 2)


def _get_credit(application: Application, discount_value: float) -> float:
    total = 0
    for a in application.attendees:
        patreon = False
        subtotal = 0
        for p in a.attendee_products:
            if p.product.category == 'patreon':
                patreon = True
                subtotal = 0
            elif not patreon:
                subtotal += p.product.price * p.quantity
        if not patreon:
            total += subtotal

    return _get_discounted_price(total, discount_value) + application.credit


def _calculate_amounts(
    db: Session,
    requested_products: List[schemas.PaymentProduct],
    already_patreon: bool,
) -> Tuple[float, float, float]:
    product_ids = list(set(rp.product_id for rp in requested_products))
    product_models = {
        p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()
    }

    attendees = {}
    for req_prod in requested_products:
        product_model = product_models.get(req_prod.product_id)
        if not product_model:
            logger.error(f'Product model not found for ID: {req_prod.product_id}')
            continue

        quantity = req_prod.quantity
        attendee_id = req_prod.attendee_id
        if attendee_id not in attendees:
            attendees[attendee_id] = {'standard': 0, 'supporter': 0, 'patreon': 0}

        if attendees[attendee_id]['patreon'] > 0:
            continue

        if product_model.category == 'patreon':
            attendees[attendee_id]['patreon'] = (
                product_model.price * quantity if not already_patreon else 0
            )
            attendees[attendee_id]['standard'] = 0
            attendees[attendee_id]['supporter'] = 0
        elif product_model.category == 'supporter':
            attendees[attendee_id]['supporter'] += product_model.price * quantity
        else:
            attendees[attendee_id]['standard'] += product_model.price * quantity

    standard_amount = sum(a['standard'] for a in attendees.values())
    supporter_amount = sum(a['supporter'] for a in attendees.values())
    patreon_amount = sum(a['patreon'] for a in attendees.values())
    logger.info('Standard amount: %s', standard_amount)
    logger.info('Supporter amount: %s', supporter_amount)
    logger.info('Patreon amount: %s', patreon_amount)

    return standard_amount, supporter_amount, patreon_amount


def _calculate_price(
    standard_amount: float,
    supporter_amount: float,
    patreon_amount: float,
    discount_value: float,
    application: Application,
    edit_passes: bool,
) -> float:
    credit = _get_credit(application, discount_value) if edit_passes else 0
    logger.info('Credit: %s', credit)

    if standard_amount > 0:
        standard_amount = _get_discounted_price(standard_amount, discount_value)
    standard_amount = standard_amount - credit

    return standard_amount + supporter_amount + patreon_amount


def _validate_application(application: Application):
    if application.status != ApplicationStatus.ACCEPTED.value:
        logger.error(
            'Application %s from %s is not accepted', application.id, application.email
        )
        raise HTTPException(status_code=400, detail='Application is not accepted')


def _get_simplefi_api_key(application: Application):
    if not (simplefi_api_key := application.popup_city.simplefi_api_key):
        logger.error(
            'Popup city %s does not have a Simplefi API key. %s',
            application.popup_city_id,
            application.email,
        )
        raise HTTPException(
            status_code=400, detail='Popup city does not have a Simplefi API key'
        )

    return simplefi_api_key


def _validate_products(
    db: Session,
    requested_product_ids: List[int],
    application: Application,
    user: TokenData,
) -> List[Product]:
    valid_products = product_crud.find(
        db=db,
        filters=ProductFilter(
            id_in=requested_product_ids,
            popup_city_id=application.popup_city_id,
            is_active=True,
        ),
        user=user,
    )
    if set(p.id for p in valid_products) != set(requested_product_ids):
        err_msg = 'Some products are not available or inactive.'
        logger.error(
            '%s User: %s, Requested products: %s',
            err_msg,
            user.email,
            requested_product_ids,
        )
        raise HTTPException(status_code=400, detail=err_msg)

    return valid_products


def _check_patreon_status(
    application: Application,
    valid_products: List[Product],
    requested_product_ids: List[int],
    edit_passes: bool,
):
    application_products = [p for a in application.attendees for p in a.products]
    already_patreon = any(p.category == 'patreon' for p in application_products)
    is_buying_patreon = any(
        p.category == 'patreon' for p in valid_products if p.id in requested_product_ids
    )

    if edit_passes and is_buying_patreon and not already_patreon:
        logger.error('Cannot edit passes for Patreon products. %s', application.email)
        raise HTTPException(
            status_code=400,
            detail='Cannot edit passes for Patreon products',
        )

    return already_patreon


def _apply_discounts(
    db: Session,
    obj: schemas.PaymentCreate,
    application: Application,
    already_patreon: bool,
) -> PaymentPreview:
    discount_assigned = application.discount_assigned or 0

    response = PaymentPreview(
        products=obj.products,
        application_id=application.id,
        currency='USD',
        edit_passes=obj.edit_passes,
        discount_value=discount_assigned,
    )

    standard_amount, supporter_amount, patreon_amount = _calculate_amounts(
        db,
        obj.products,
        already_patreon,
    )

    response.original_amount = standard_amount + supporter_amount + patreon_amount
    response.amount = _calculate_price(
        standard_amount=standard_amount,
        supporter_amount=supporter_amount,
        patreon_amount=patreon_amount,
        discount_value=discount_assigned,
        application=application,
        edit_passes=obj.edit_passes,
    )

    if application.group:
        response.group_id = application.group.id
        discount_value = application.group.discount_percentage
        discounted_amount = _calculate_price(
            standard_amount=standard_amount,
            supporter_amount=supporter_amount,
            patreon_amount=patreon_amount,
            discount_value=discount_value,
            application=application,
            edit_passes=obj.edit_passes,
        )
        if discounted_amount < response.amount:
            response.amount = discounted_amount
            response.discount_value = discount_value

    if obj.coupon_code:
        coupon_code = coupon_code_crud.get_by_code(
            db,
            code=obj.coupon_code,
            popup_city_id=application.popup_city_id,
        )
        discounted_amount = _calculate_price(
            standard_amount=standard_amount,
            supporter_amount=supporter_amount,
            patreon_amount=patreon_amount,
            discount_value=coupon_code.discount_value,
            application=application,
            edit_passes=obj.edit_passes,
        )
        if discounted_amount < response.amount:
            response.amount = discounted_amount
            response.coupon_code_id = coupon_code.id
            response.coupon_code = coupon_code.code
            response.discount_value = coupon_code.discount_value

    return response


def _prepare_payment_response(
    db: Session,
    obj: schemas.PaymentCreate,
    user: TokenData,
) -> Tuple[schemas.PaymentPreview, Application, List[Product]]:
    application = application_crud.get(db, obj.application_id, user)
    _validate_application(application)

    requested_product_ids = [p.product_id for p in obj.products]
    valid_products = _validate_products(db, requested_product_ids, application, user)

    already_patreon = _check_patreon_status(
        application,
        valid_products,
        requested_product_ids,
        obj.edit_passes,
    )

    response = _apply_discounts(
        db,
        obj,
        application,
        already_patreon,
    )

    return response, application, valid_products


def _calculate_max_installments(start_date: datetime) -> int:
    today = datetime.now()
    delta = relativedelta(start_date, today)
    months = delta.years * 12 + delta.months
    return max(1, months)


def preview_payment(
    db: Session,
    obj: schemas.PaymentCreate,
    user: TokenData,
) -> schemas.PaymentPreview:
    response, _, _ = _prepare_payment_response(db, obj, user)
    return response


def create_payment(
    db: Session,
    obj: schemas.PaymentCreate,
    user: TokenData,
) -> PaymentPreview:
    response, application, valid_products = _prepare_payment_response(db, obj, user)
    simplefi_api_key = _get_simplefi_api_key(application)

    if response.amount <= 0:
        response.status = 'approved'
        if response.amount < 0:
            application.credit = -response.amount
            response.amount = 0
        else:
            application.credit = 0
        db.commit()
        db.refresh(application)

        return response

    # --- Create a lookup for product names --- #
    valid_products_names = {p.id: p.name for p in valid_products}

    start_date = application.popup_city.start_date
    max_installments = _calculate_max_installments(start_date) if start_date is not None else None

    reference = {
        'email': application.email,
        'application_id': application.id,
        'products': [
            {
                'product_id': req_prod.product_id,
                'name': valid_products_names[req_prod.product_id],
                'quantity': req_prod.quantity,
                'attendee_id': req_prod.attendee_id,
            }
            for req_prod in obj.products
        ],
    }

    logger.info('Creating payment request. Email: %s, Amount: %s, Max Installments: %s', user.email, response.amount, max_installments)
    payment_request = simplefi.create_payment(
        response.amount,
        reference=reference,
        max_installments=max_installments,
        name='Eclipse Passes',
        simplefi_api_key=simplefi_api_key,
    )

    response.external_id = payment_request['id']
    response.status = payment_request['status']
    response.checkout_url = payment_request['checkout_url']

    return response
