# Import all models here to ensure SQLAlchemy can set up relationships correctly
from app.api.applications.models import Application
from app.api.attendees.models import Attendee
from app.api.citizens.models import Citizen
from app.api.email_logs.models import EmailLog
from app.api.groups.models import Group
from app.api.organizations.models import Organization
from app.api.payments.models import Payment, PaymentInstallment, PaymentProduct
from app.api.popup_city.models import PopUpCity
from app.api.products.models import Product

# Re-export all models
__all__ = [
    'Application',
    'Attendee',
    'Citizen',
    'EmailLog',
    'Group',
    'Organization',
    'Payment',
    'PaymentInstallment',
    'PaymentProduct',
    'PopUpCity',
    'Product',
]
