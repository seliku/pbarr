-- PBArr Database Initialization Script
-- This script runs automatically when PostgreSQL initializes for the first time

-- Ensure the pbarr database exists and pbuser has access
-- (This is redundant with POSTGRES_DB, but explicit is better)

-- Grant permissions to pbuser on the pbarr database
GRANT ALL PRIVILEGES ON DATABASE pbarr TO pbuser;

-- Connect to pbarr database and set up basic permissions
\c pbarr;

-- Ensure pbuser has all privileges on the pbarr database
GRANT ALL ON SCHEMA public TO pbuser;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO pbuser;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO pbuser;

-- Set default privileges for future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO pbuser;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO pbuser;

-- Create a simple test to verify the database is working
CREATE TABLE IF NOT EXISTS db_init_test (
    id SERIAL PRIMARY KEY,
    initialized_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    version TEXT DEFAULT '1.0'
);

INSERT INTO db_init_test (version) VALUES ('1.0') ON CONFLICT DO NOTHING;
