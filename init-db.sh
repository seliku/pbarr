#!/bin/bash
# PBArr Database Initialization Script
# This script runs automatically when PostgreSQL initializes

set -e

# Wait for PostgreSQL to be ready
until pg_isready -U pbuser -d pbarr; do
  echo "Waiting for PostgreSQL to be ready..."
  sleep 2
done

echo "PostgreSQL is ready, running initialization..."

# Run SQL commands to ensure proper permissions
psql -U pbuser -d pbarr -c "
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
"

echo "Database initialization completed successfully"
