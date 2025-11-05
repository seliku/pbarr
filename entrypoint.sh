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

# 2. Check SOCKS5 config from database
print("📖 Checking SOCKS5 configuration...")

import psycopg2

SOCKS5_ENABLED = False
SOCKS5_HOST = ''
SOCKS5_PORT = '1080'
SOCKS5_USER = ''
SOCKS5_PASS = ''

try:
    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        database=db_name,
        user=db_user,
        password=db_pass
    )
    
    cursor = conn.cursor()
    
    # Check if config table exists
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'config'
        )
    """)
    table_exists = cursor.fetchone()[0]
    
    if table_exists:
        # Read SOCKS5 config
        cursor.execute("""
            SELECT key, value FROM config 
            WHERE key LIKE 'socks5_%'
        """)
        results = cursor.fetchall()
        
        config = {key: value for key, value in results}
        
        SOCKS5_ENABLED = config.get('socks5_enabled', 'false').lower() == 'true'
        SOCKS5_HOST = config.get('socks5_host', '')
        SOCKS5_PORT = config.get('socks5_port', '1080')
        SOCKS5_USER = config.get('socks5_user', '')
        SOCKS5_PASS = config.get('socks5_pass', '')
        
        if SOCKS5_ENABLED and SOCKS5_HOST:
            print("✅ SOCKS5 config loaded from database")
        else:
            print("ℹ️ SOCKS5 not configured in database")
    else:
        print("⚠️ Config table doesn't exist yet (fresh deployment)")
    
    cursor.close()
    conn.close()

except Exception as e:
    print(f"⚠️ Database check failed: {e}")
    SOCKS5_ENABLED = False

PYEOF

# Export for use in bash
export SOCKS5_ENABLED
export SOCKS5_HOST
export SOCKS5_PORT
export SOCKS5_USER
export SOCKS5_PASS

# Ensure log file exists
mkdir -p /app/app
touch /app/app/pbarr.log

log_message() {
    echo "$1"
    mkdir -p /app/app
    echo "$(date '+%Y-%m-%d %H:%M:%S') - root - INFO - $1" >> /app/app/pbarr.log
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 PBArr Container Startup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log_message "🚀 PBArr Container Startup"
log_message "📍 SOCKS5 Status: $SOCKS5_ENABLED"

if [ "$SOCKS5_ENABLED" = "true" ]; then
    if [ -z "$SOCKS5_HOST" ] || [ -z "$SOCKS5_USER" ] || [ -z "$SOCKS5_PASS" ]; then
        log_message "❌ ERROR: SOCKS5 enabled but credentials missing!"
        exit 1
    fi
    
    log_message "🔐 Configuring SOCKS5 routing..."
    log_message "   Host: $SOCKS5_HOST:$SOCKS5_PORT"
    log_message "   User: $SOCKS5_USER"
    
    mkdir -p /etc
    cat > /etc/redsocks.conf << EOF
base {
    log_debug = off;
    log_info = on;
    log = "file:/var/log/redsocks.log";
    daemon = off;
    redirector = iptables;
}

redsocks {
    local_ip = 0.0.0.0;
    local_port = 12345;
    ip = $SOCKS5_HOST;
    port = $SOCKS5_PORT;
    type = socks5;
    login = "$SOCKS5_USER";
    password = "$SOCKS5_PASS";
}
EOF
    
    /usr/sbin/redsocks -c /etc/redsocks.conf &
    REDSOCKS_PID=$!
    sleep 2
    
    if ! kill -0 $REDSOCKS_PID 2>/dev/null; then
        log_message "❌ Failed to start redsocks daemon"
        exit 1
    fi
    
    log_message "✅ redsocks started (PID: $REDSOCKS_PID)"
    
    iptables -t nat -N REDSOCKS 2>/dev/null || iptables -t nat -F REDSOCKS
    iptables -t nat -A REDSOCKS -d 0.0.0.0/8 -j RETURN
    iptables -t nat -A REDSOCKS -d 127.0.0.1/8 -j RETURN
    iptables -t nat -A REDSOCKS -d 169.254.0.0/16 -j RETURN
    iptables -t nat -A REDSOCKS -d 192.168.0.0/16 -j RETURN
    iptables -t nat -A REDSOCKS -d 172.16.0.0/12 -j RETURN
    iptables -t nat -A REDSOCKS -d 10.0.0.0/8 -j RETURN
    
    SOCKS5_IP=$(getent hosts $SOCKS5_HOST 2>/dev/null | awk '{print $1; exit}')
    if [ -n "$SOCKS5_IP" ]; then
        log_message "✓ Excluding proxy IP $SOCKS5_IP"
        iptables -t nat -A REDSOCKS -d $SOCKS5_IP -j RETURN
    fi
    
    iptables -t nat -A REDSOCKS -p tcp -j REDIRECT --to-ports 12345
    iptables -t nat -I PREROUTING -p tcp -j REDSOCKS
    iptables -t nat -I OUTPUT -p tcp ! -d 127.0.0.1 -j REDSOCKS
    
    log_message "✅ iptables configured"
else
    log_message "⏭️ SOCKS5 not configured"
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎯 Starting PBArr Application"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
