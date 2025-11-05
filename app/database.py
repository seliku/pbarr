from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import OperationalError, ProgrammingError
import os
import logging


logger = logging.getLogger(__name__)


DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL environment variable not set!")

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


# Import ALL Models - WICHTIG für create_all()
from app.models.config import Config
from app.models.module_state import ModuleState
from app.models.show import Show
from app.models.episode import Episode
from app.models.tvdb_cache import TVDBCache
from app.models.matcher_config import MatcherConfig
from app.models.version import AppVersion, UpdateCheck
from app.models.watch_list import WatchList
from app.models.mediathek_cache import MediathekCache


def ensure_database_exists():
    """Stellt sicher dass die Datenbank existiert (nur falls nötig)"""
    if "sqlite" in DATABASE_URL:
        return  # SQLite braucht das nicht
    
    try:
        # Versuche normale Verbindung
        with engine.connect() as conn:
            logger.info("✓ Database connection successful")
            return
    except (OperationalError, ProgrammingError) as e:
        # DB existiert nicht - erstelle sie
        if "does not exist" in str(e) or "Unknown database" in str(e):
            logger.info(f"Database does not exist, creating it...")
            
            try:
                from sqlalchemy.engine.url import make_url
                url = make_url(DATABASE_URL)
                db_name = url.database
                db_user = url.username
                
                # Verbinde OHNE Database - zur 'postgres' default-DB
                admin_url = url.set(database='postgres')
                admin_engine = create_engine(
                    str(admin_url),
                    isolation_level='AUTOCOMMIT'
                )
                
                with admin_engine.connect() as conn:
                    conn.execute(text(f"CREATE DATABASE {db_name} OWNER {db_user}"))
                    logger.info(f"✓ Database {db_name} created successfully")
                
                admin_engine.dispose()
            except Exception as create_error:
                logger.error(f"✗ Failed to create database: {create_error}")
                raise
        else:
            # Andere Connection-Fehler
            raise


def init_db():
    """Erstellt Datenbank und alle Tabellen"""
    import time

    # Retry database connection up to 60 times (60 seconds)
    for attempt in range(60):
        try:
            ensure_database_exists()
            Base.metadata.create_all(bind=engine)
            logger.info("✓ All database tables initialized")
            return
        except Exception as e:
            if attempt < 59:  # Don't log on last attempt
                logger.info(f"Database not ready (attempt {attempt + 1}/60), waiting for PostgreSQL...")
                time.sleep(1)
            else:
                logger.error(f"Database initialization failed after 60 attempts: {e}")
                raise


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
