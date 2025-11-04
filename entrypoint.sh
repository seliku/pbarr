#!/bin/bash
set -e

echo "🔍 DEBUG: entrypoint.sh startup"
echo "DATABASE_URL = $DATABASE_URL"
echo ""

python3 << 'PYEOF'
import os
import subprocess
import sys
import time
from urllib.parse import urlparse

db_url = os.environ.get('DATABASE_URL', 'postgresql://pbuser:pbpass@postgres:5432/pbarr')

print(f"[1] Raw DATABASE_URL from env: {db_url}")

try:
    parsed = urlparse(db_url)
    db_user = parsed.username or 'pbuser'
    db_pass = parsed.password or ''
    db_host = parsed.hostname or 'postgres'
    db_port = parsed.port or 5432
    db_name = parsed.path.lstrip('/') or 'pbarr'
    
    print(f"[2] Parsed values:")
    print(f"    db_user = {db_user}")
    print(f"    db_pass = {db_pass}")
    print(f"    db_host = {db_host}")
    print(f"    db_port = {db_port}")
    print(f"    db_name = {db_name}")
    
except Exception as e:
    print(f"[ERROR] Parsing failed: {e}")
    sys.exit(1)

print(f"[3] Connecting to: {db_host}:{db_port}/{db_name} (user={db_user})")

# Jetzt hier ALLE Connection-Versuche loggen
import psycopg2

try:
    print(f"[4] Attempting psycopg2.connect with:")
    print(f"    host={db_host}")
    print(f"    port={db_port}")
    print(f"    database={db_name}")
    print(f"    user={db_user}")
    
    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        database=db_name,
        user=db_user,
        password=db_pass
    )
    print(f"[5] ✅ Connection successful!")
    conn.close()
    
except psycopg2.OperationalError as e:
    print(f"[ERROR] Connection failed: {e}")
    # Hier sehen wir GENAU, welche DB es versucht
    sys.exit(1)

PYEOF

echo ""
echo "✅ Debug completed"
exit 0
