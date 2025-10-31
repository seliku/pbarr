from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool
import os
import logging


logger = logging.getLogger(__name__)


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pbuser:pbpass@localhost:5432/pbarr")


# In-Memory SQLite für Tests
if "sqlite" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ZENTRALE Base Definition
Base = declarative_base()


def ensure_database_exists():
    """Stellt sicher dass die Datenbank existiert (ohne Schema zu erstellen)"""
    if "sqlite" in DATABASE_URL:
        return  # SQLite braucht das nicht
    
    try:
        from sqlalchemy.engine.url import make_url
        url = make_url(DATABASE_URL)
        db_name = url.database
        db_user = url.username
        
        # Verbinde ohne spezifische DB (default 'postgres')
        admin_url = url.set(database='postgres')
        admin_engine = create_engine(str(admin_url), isolation_level='AUTOCOMMIT')
        
        with admin_engine.connect() as conn:
            # Check ob DB existiert
            result = conn.execute(text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"))
            if not result.fetchone():
                logger.info(f"Creating database: {db_name}")
                conn.execute(text(f"CREATE DATABASE {db_name} OWNER {db_user}"))
                logger.info(f"Database {db_name} created successfully")
            else:
                logger.info(f"Database {db_name} already exists")
        
        admin_engine.dispose()
    except Exception as e:
        logger.warning(f"Could not ensure database exists: {e}")
        # Non-fatal - Tabellen-Creation wird trotzdem versucht


def init_db():
    """Erstellt Datenbank und alle Tabellen"""
    ensure_database_exists()
    Base.metadata.create_all(bind=engine)
    logger.info("✓ All database tables initialized")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
