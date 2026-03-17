from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.account_clusters.routes import router as account_clusters_router
from app.api.achievements.routes import router as achievements_router
from app.api.applications.routes import router as applications_router
from app.api.attendees.routes import router as attendees_router
from app.api.check_in.routes import router as check_in_router
from app.api.citizens.routes import router as citizens_router
from app.api.coupon_codes.routes import router as coupon_codes_router
from app.api.groups.routes import router as groups_router
from app.api.organizations.routes import router as organizations_router
from app.api.payments.routes import router as payments_router
from app.api.popup_city.routes import router as popup_cities_router
from app.api.products.routes import router as products_router
from app.api.webhooks.routes import router as webhooks_router
from app.api.agent.routes import router as agent_router
from app.api.world_builders.routes import router as world_builders_router
from app.core.config import Environment, settings
from app.core.database import create_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ENVIRONMENT != Environment.TEST:
        create_db()
    yield


app = FastAPI(lifespan=lifespan, version='0.1.1')

# Include routers
app.include_router(
    account_clusters_router, prefix='/account-clusters', tags=['Account Clusters']
)
app.include_router(achievements_router, prefix='/achievements', tags=['Achievements'])
app.include_router(applications_router, prefix='/applications', tags=['Applications'])
app.include_router(attendees_router, prefix='/attendees', tags=['Attendees'])
app.include_router(check_in_router, prefix='/check-in', tags=['Check In'])
app.include_router(citizens_router, prefix='/citizens', tags=['Citizens'])
app.include_router(coupon_codes_router, prefix='/coupon-codes', tags=['Coupon Codes'])
app.include_router(groups_router, prefix='/groups', tags=['Groups'])
app.include_router(payments_router, prefix='/payments', tags=['Payments'])
app.include_router(popup_cities_router, prefix='/popups', tags=['Popups'])
app.include_router(
    organizations_router, prefix='/organizations', tags=['Organizations']
)
app.include_router(products_router, prefix='/products', tags=['Products'])
app.include_router(webhooks_router, prefix='/webhooks', tags=['Webhooks'])
app.include_router(
    world_builders_router, prefix='/world-builders', tags=['World Builders']
)
app.include_router(agent_router, prefix='/agent', tags=['Agent'])

origins = ['*']
app.add_middleware(
    CORSMiddleware,  # type: ignore[invalid-argument-type]
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
    expose_headers=['PAYMENT-REQUIRED', 'PAYMENT-RESPONSE'],
)


@app.get('/', include_in_schema=False)
def ping():
    return Response(status_code=200)


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000)
