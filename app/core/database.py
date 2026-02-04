from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy_utils import create_database, database_exists

from .config import settings
from .logger import logger

Base = declarative_base()

_engine_kwargs = {}
if not settings.DATABASE_URL.startswith('sqlite'):
    _engine_kwargs.update(
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=3600,  # Recycle connections every hour
        pool_pre_ping=True,  # Validate connections before use
    )

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)

# Create a configured "Session" class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Create the database tables
def create_db():
    engine = create_engine(settings.DATABASE_URL)
    if not database_exists(engine.url):
        logger.info('Database does not exist. Creating...')
        create_database(engine.url)
        logger.info('Database created successfully!')

    Base.metadata.create_all(bind=engine)


# Dependency for getting the database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
