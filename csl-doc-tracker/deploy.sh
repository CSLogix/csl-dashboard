#!/bin/bash
# CSL Doc Tracker — One-command VPS deployment script
# Run: bash deploy.sh

set -e

echo "=== CSL Doc Tracker Deployment ==="
echo ""

DEPLOY_DIR="/root/csl-doc-tracker"

# 1. Create deploy directory
mkdir -p "$DEPLOY_DIR"
cp -r "$(dirname "$0")"/* "$DEPLOY_DIR"/
cp "$(dirname "$0")"/.env "$DEPLOY_DIR"/ 2>/dev/null || true
cd "$DEPLOY_DIR"

# 2. Install PostgreSQL if needed
if ! command -v psql &>/dev/null; then
    echo "[1/6] Installing PostgreSQL..."
    apt update -qq && apt install -y -qq postgresql postgresql-contrib
else
    echo "[1/6] PostgreSQL already installed."
fi

# 3. Start PostgreSQL (detect installed version)
echo "[2/6] Starting PostgreSQL..."
PG_VER=$(pg_lsclusters -h 2>/dev/null | head -1 | awk '{print $1}')
PG_VER=${PG_VER:-17}
pg_ctlcluster "$PG_VER" main start 2>/dev/null || true

# Enable TCP listening
PG_CONF="/etc/postgresql/${PG_VER}/main/postgresql.conf"
if [ -f "$PG_CONF" ]; then
    sed -i "s/^#listen_addresses = 'localhost'/listen_addresses = 'localhost'/" "$PG_CONF" 2>/dev/null || true
    pg_ctlcluster "$PG_VER" main restart 2>/dev/null || true
fi

# 4. Create database and user
echo "[3/6] Setting up database..."
su - postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='csl_admin'\" | grep -q 1 || psql -c \"CREATE ROLE csl_admin WITH LOGIN PASSWORD 'changeme';\"" 2>/dev/null
su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='csl_doc_tracker'\" | grep -q 1 || createdb csl_doc_tracker -O csl_admin" 2>/dev/null
su - postgres -c "psql -d csl_doc_tracker -f $DEPLOY_DIR/setup_db.sql" 2>/dev/null

# 5. Install Python dependencies
echo "[4/6] Installing Python dependencies..."
pip install -q -r requirements.txt
pip install -q cffi cryptography 2>/dev/null || pip install -q --ignore-installed cffi cryptography

# 6. Create document storage
echo "[5/6] Creating document storage..."
mkdir -p /opt/csl-docs/files

# 7. Create .env if it doesn't exist
if [ ! -f "$DEPLOY_DIR/.env" ]; then
    echo "[6/6] Creating .env file..."
    cat > "$DEPLOY_DIR/.env" << 'ENVEOF'
# CSL Document Tracker — Environment Configuration

# --- Gmail API ---
GMAIL_CREDENTIALS_PATH=credentials.json
GMAIL_TOKEN_PATH=token.json
GMAIL_MONITORED_ACCOUNT=${GMAIL_MONITORED_ACCOUNT:-""}  # Set in .env

# --- Google Sheets ---
GOOGLE_SHEETS_ID=19MB5HmmWwsVXY_nADCYYLJL-zWXYt8yWrfeRBSfB2S0
GOOGLE_SHEETS_CREDENTIALS_PATH=/root/csl-credentials.json
SHEET_TAB_NAME=Active Loads
SHEET_SYNC_INTERVAL_MINUTES=5

# --- PostgreSQL ---
DB_HOST=localhost
DB_PORT=5432
DB_NAME=csl_doc_tracker
DB_USER=csl_admin
DB_PASSWORD=changeme

# --- Document Storage ---
DOCUMENT_STORAGE_PATH=/opt/csl-docs/files

# --- Dashboard ---
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8080

# --- Polling ---
SCAN_INTERVAL_SECONDS=120

# --- Logging ---
LOG_LEVEL=INFO
LOG_FILE=csl_doc_tracker.log
ENVEOF
else
    echo "[6/6] .env already exists, skipping."
fi

echo ""
echo "=== Deployment complete! ==="
echo ""
echo "Next steps:"
echo "  1. Place credentials.json in $DEPLOY_DIR/"
echo "  2. Run: cd $DEPLOY_DIR && python3 gmail_monitor.py"
echo "     (This starts the OAuth flow — follow the URL in your browser)"
echo "  3. After auth completes, start all services:"
echo "     cd $DEPLOY_DIR && bash start.sh"
echo ""
echo "Dashboard will be at: http://$(hostname -I | awk '{print $1}'):8080"
