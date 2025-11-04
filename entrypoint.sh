#!/bin/bash
set -e

# Ensure log file exists early
mkdir -p /app/app
touch /app/app/pbarr.log

# Read SOCKS5 configuration from PostgreSQL database
read_from_db() {
python3 << 'PYEOF'
import os
import psycopg2

try:
    # Get database URL from environment (standard PBArr setup)
    db_url = os.environ.get('DATABASE_URL', 'postgresql://user:password@localhost/pbarr')

    # Parse database URL
    # Format: postgresql://user:password@host:port/database
    if 'postgresql://' in db_url:
        parts = db_url.replace('postgresql://', '').split('@')
        user_pass = parts[0].split(':')
        host_port_db = parts[1].split('/')
        host_port = host_port_db[0].split(':')

        db_user = user_pass[0]
        db_pass = user_pass[1] if len(user_pass) > 1 else ''
        db_host = host_port[0]
        db_port = host_port[1] if len(host_port) > 1 else '5432'
        db_name = host_port_db[1]
    else:
        # Fallback
        db_user = 'user'
        db_pass = 'password'
        db_host = 'localhost'
        db_port = '5432'
        db_name = 'pbarr'

    # Connect to database
    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        database=db_name,
        user=db_user,
        password=db_pass
    )

    cursor = conn.cursor()

    # ✅ FIRST: Check if config table exists
    cursor.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'config')")
    table_exists = cursor.fetchone()[0]

    if not table_exists:
        # Config table doesn't exist yet (fresh deployment)
        cursor.close()
        conn.close()
        print(f"false|||||")
        exit(0)

    # Query configs
    cursor.execute("SELECT key, value FROM config WHERE key LIKE 'socks5_%'")
    results = cursor.fetchall()

    # Create dict from results
    config = {}
    for key, value in results:
        config[key] = value

    cursor.close()
    conn.close()

    # Return values (true/false, then credentials)
    enabled = config.get('socks5_enabled', 'false').lower() == 'true'
    host = config.get('socks5_host', '')
    port = config.get('socks5_port', '1080')
    user = config.get('socks5_user', '')
    password = config.get('socks5_pass', '')

    # Only print the result, no debug output
    print(f"{str(enabled).lower()}|{host}|{port}|{user}|{password}")
except Exception as e:
    print(f"false|||||")
PYEOF
}

# Wait for database to be ready
echo "⏳ Waiting for database connection..."
sleep 3

# Try to read SOCKS5 config from database (only if config table exists)
echo "📖 Checking SOCKS5 configuration..."

# Check if database is ready and migrated (config table exists)
if python3 -c "
import os
import psycopg2
import sys

try:
    db_url = os.environ.get('DATABASE_URL', 'postgresql://user:password@localhost/pbarr')
    if 'postgresql://' in db_url:
        parts = db_url.replace('postgresql://', '').split('@')
        user_pass = parts[0].split(':')
        host_port_db = parts[1].split('/')
        host_port = host_port_db[0].split(':')

        db_user = user_pass[0]
        db_pass = user_pass[1] if len(user_pass) > 1 else ''
        db_host = host_port[0]
        db_port = host_port[1] if len(host_port) > 1 else '5432'
        db_name = host_port_db[1]

    conn = psycopg2.connect(host=db_host, port=db_port, database=db_name, user=db_user, password=db_pass)
    cursor = conn.cursor()
    cursor.execute(\"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'config')\")
    table_exists = cursor.fetchone()[0]
    cursor.close()
    conn.close()

    if table_exists:
        print('ready')
        sys.exit(0)
    else:
        print('not_ready')
        sys.exit(1)
except Exception as e:
    print('error')
    sys.exit(1)
" 2>/dev/null; then

    # Read DB config
    DB_CONFIG=$(read_from_db)
    echo "DEBUG: DB_CONFIG='$DB_CONFIG'" > /tmp/debug.log
    SOCKS5_ENABLED=$(echo "$DB_CONFIG" | cut -d'|' -f1)
    SOCKS5_HOST=$(echo "$DB_CONFIG" | cut -d'|' -f2)
    SOCKS5_PORT=$(echo "$DB_CONFIG" | cut -d'|' -f3)
    SOCKS5_USER=$(echo "$DB_CONFIG" | cut -d'|' -f4)
    SOCKS5_PASS=$(echo "$DB_CONFIG" | cut -d'|' -f5)

    if [ "$SOCKS5_ENABLED" = "true" ] && [ -n "$SOCKS5_HOST" ]; then
        echo "✅ SOCKS5 config loaded from database"
    else
        echo "ℹ️ SOCKS5 not configured in database, skipping proxy setup"
        SOCKS5_ENABLED="false"
    fi
else
    echo "⚠️ Database not ready or not migrated yet, skipping SOCKS5 setup"
    SOCKS5_ENABLED="false"
fi

echo "DEBUG: Final SOCKS5_ENABLED='$SOCKS5_ENABLED'" >> /tmp/debug.log

# Function to log both to console and file
log_message() {
    echo "$1"
    # Ensure log directory exists
    mkdir -p /app/app
    echo "$(date '+%Y-%m-%d %H:%M:%S') - root - INFO - $1" >> /app/app/pbarr.log
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 PBArr Container Startup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log_message "🚀 PBArr Container Startup"
log_message "📍 SOCKS5 Status: $SOCKS5_ENABLED"
log_message "   Reading config from: PostgreSQL Database"

if [ "$SOCKS5_ENABLED" = "true" ]; then
    # Validate credentials
    if [ -z "$SOCKS5_HOST" ] || [ -z "$SOCKS5_USER" ] || [ -z "$SOCKS5_PASS" ]; then
        log_message "❌ ERROR: SOCKS5 enabled but credentials missing in database!"
        log_message "   Configure SOCKS5 in Admin Panel first"
        exit 1
    fi

    log_message ""
    log_message "🔐 Configuring system-level SOCKS5 routing..."
    log_message "   Host: $SOCKS5_HOST:$SOCKS5_PORT"
    log_message "   User: $SOCKS5_USER"

    # 1. Generate redsocks configuration
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

    log_message "   ✅ redsocks config generated"

    # 2. Start redsocks daemon in background
    /usr/sbin/redsocks -c /etc/redsocks.conf &
    REDSOCKS_PID=$!
    sleep 2

    if ! kill -0 $REDSOCKS_PID 2>/dev/null; then
        log_message "❌ Failed to start redsocks daemon"
        cat /var/log/redsocks.log 2>/dev/null || echo "   No logs available"
        exit 1
    fi

    log_message "   ✅ redsocks daemon started (PID: $REDSOCKS_PID)"

    # 3. Configure iptables rules
    log_message "   📊 Configuring iptables routing..."

    # Create REDSOCKS chain
    iptables -t nat -N REDSOCKS 2>/dev/null || iptables -t nat -F REDSOCKS

    # Traffic to bypass proxy (local/private networks)
    iptables -t nat -A REDSOCKS -d 0.0.0.0/8 -j RETURN
    iptables -t nat -A REDSOCKS -d 127.0.0.1/8 -j RETURN
    iptables -t nat -A REDSOCKS -d 169.254.0.0/16 -j RETURN
    iptables -t nat -A REDSOCKS -d 192.168.0.0/16 -j RETURN    # Local network (Sonarr!)
    iptables -t nat -A REDSOCKS -d 172.16.0.0/12 -j RETURN     # Docker networks
    iptables -t nat -A REDSOCKS -d 10.0.0.0/8 -j RETURN        # Private networks

    # ✅ WICHTIG: Proxy-IP selbst ausschließen (verhindert Rekursion!)
    # Resolve proxy hostname to IP
    SOCKS5_IP=$(getent hosts $SOCKS5_HOST 2>/dev/null | awk '{print $1; exit}')
    if [ -n "$SOCKS5_IP" ]; then
        log_message "   ✓ Excluding proxy IP $SOCKS5_IP from routing"
        iptables -t nat -A REDSOCKS -d $SOCKS5_IP -j RETURN
    else
        log_message "   ⚠ Warning: Could not resolve proxy IP for $SOCKS5_HOST"
    fi

    iptables -t nat -A REDSOCKS -p tcp -j REDIRECT --to-ports 12345

    # ✅ PREROUTING: Intercept ALL TCP traffic BEFORE routing
    iptables -t nat -I PREROUTING -p tcp -j REDSOCKS

    # Optional: Also handle locally-generated traffic (e.g., curl inside container)
    iptables -t nat -I OUTPUT -p tcp ! -d 127.0.0.1 -j REDSOCKS

    log_message "   ✅ iptables rules configured (PREROUTING + OUTPUT)"
    log_message ""
    log_message "🌐 All TCP traffic will be routed through SOCKS5 proxy"
    log_message "   Exceptions: Local network, Docker networks, Sonarr (192.168.x.x)"
else
    log_message " ⏭️ SOCKS5 not configured - using direct connection"
    log_message "   Configure SOCKS5 in Admin Panel if needed"
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎯 Starting PBArr Application"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Start Python application
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
