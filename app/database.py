from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import OperationalError, ProgrammingError
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
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=3600
    )


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ZENTRALE Base Definition
Base = declarative_base()


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
                    # KEIN timeout in connect_args!
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
    ensure_database_exists()
    Base.metadata.create_all(bind=engine)
    logger.info("✓ All database tables initialized")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
