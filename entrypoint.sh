#!/bin/bash
set -e

DB_URL="${DATABASE_URL:-postgresql://pbuser:pbpass@postgres:5432/pbarr}"
export DATABASE_URL="$DB_URL"

echo "📍 DATABASE_URL: $DATABASE_URL"

python3 << 'PYEOF'
import os
import subprocess
import sys
import time
from urllib.parse import urlparse

# Parse DATABASE_URL
db_url = os.environ.get('DATABASE_URL', 'postgresql://pbuser:pbpass@postgres:5432/pbarr')

try:
    parsed = urlparse(db_url)
    db_user = parsed.username or 'pbuser'
    db_pass = parsed.password or ''
    db_host = parsed.hostname or 'postgres'
    db_port = parsed.port or 5432
    db_name = parsed.path.lstrip('/') or 'pbarr'
except Exception as e:
    print(f"❌ Error parsing DATABASE_URL: {e}")
    sys.exit(1)

print(f"📍 Using: User={db_user}, Host={db_host}, DB={db_name}")

# 1. Wait for PostgreSQL
print("⏳ Waiting for PostgreSQL to be ready...")
for i in range(60):
    try:
        result = subprocess.run(
            ['pg_isready', '-h', db_host, '-p', str(db_port), '-U', db_user],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"✅ PostgreSQL is ready")
            break
    except:
        pass
    
    print(f"   ... waiting ({i+1}s) ...")
    time.sleep(1)
else:
    print("❌ PostgreSQL not ready after 60 seconds")
    sys.exit(1)

time.sleep(3)

PYEOF

# Ensure log file exists
mkdir -p /app/app
touch /app/app/pbarr.log

# Create symlink for direct download to library
ln -sf /app/library /tmp/pbarr_downloads

log_message() {
    echo "$1"
    mkdir -p /app/app
    echo "$(date '+%Y-%m-%d %H:%M:%S') - root - INFO - $1" >> /app/app/pbarr.log
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 PBArr Container Startup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log_message "🚀 PBArr Container Startup"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎯 Starting PBArr Application"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
