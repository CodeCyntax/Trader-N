#!/usr/bin/env bash
# ==============================================================================
# Trader-N: 1-Click Automated Cloud VPS Deployment Script
# Supports: Ubuntu 22.04 / 24.04 LTS, Debian 12
# Sets up 24/7 self-healing systemd service, Python virtualenv, and private auth.
# ==============================================================================

set -euo pipefail

echo "======================================================================"
echo " 🚀 Trader-N 24/7 Private Cloud Deployment Initializing..."
echo "======================================================================"

# 1. Detect environment and user
CURRENT_USER=$(whoami)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$CURRENT_USER" = "root" ]; then
    echo "⚠️  Running as root. Creating dedicated system user 'trader'..."
    if ! id -u trader >/dev/null 2>&1; then
        useradd -m -s /bin/bash trader
    fi
    TARGET_USER="trader"
    TARGET_HOME="/home/trader"
else
    TARGET_USER="$CURRENT_USER"
    TARGET_HOME="$HOME"
fi

echo "📦 Target User: $TARGET_USER"
echo "📁 Project Directory: $PROJECT_DIR"

# 2. Install base system dependencies
echo "🔄 Updating system packages..."
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y python3 python3-pip python3-venv curl git ufw
fi

# 3. Setup Python Virtual Environment
echo "🐍 Setting up Python virtual environment in $PROJECT_DIR/.venv..."
cd "$PROJECT_DIR"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# 4. Generate Private Security Credentials in .env
ENV_FILE="$PROJECT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "🔐 Generating random high-entropy credentials for private dashboard..."
    RAND_PASS=$(openssl rand -hex 12)
    cat <<EOF > "$ENV_FILE"
# Trader-N Private Production Environment
PYTHONUNBUFFERED=1
TRADER_AUTH_ENABLED=true
TRADER_AUTH_USER=admin
TRADER_AUTH_PASS=$RAND_PASS
EOF
    chmod 600 "$ENV_FILE"
    echo "✅ Created $ENV_FILE with secure credentials."
else
    echo "ℹ️  Found existing .env file. Keeping current credentials."
fi

# 5. Ensure data storage directory exists
mkdir -p "$PROJECT_DIR/data_store"
chmod 750 "$PROJECT_DIR/data_store"

# 6. Install Systemd Service Unit
echo "⚙️  Configuring 24/7 systemd supervisor service..."
SERVICE_FILE="/etc/systemd/system/trader-n.service"

sudo bash -c "cat <<EOF > $SERVICE_FILE
[Unit]
Description=Trader-N Autonomous Solana Trading Agent & Cognitive Organism
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$TARGET_USER
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=-$ENV_FILE
ExecStart=$PROJECT_DIR/.venv/bin/python main.py --port 8080
Restart=always
RestartSec=5s

# Security & Limits
LimitNOFILE=65535
TimeoutStopSec=20
KillMode=mixed

# Journald logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=trader-n

[Install]
WantedBy=multi-user.target
EOF"

sudo systemctl daemon-reload
sudo systemctl enable trader-n
sudo systemctl restart trader-n

# 7. Configure Firewall (UFW)
if command -v ufw >/dev/null 2>&1; then
    echo "🛡️  Configuring UFW firewall rules..."
    sudo ufw allow 22/tcp || true
    sudo ufw allow 8080/tcp || true
fi

# 8. Print Output & Access Credentials
AUTH_USER=$(grep TRADER_AUTH_USER "$ENV_FILE" | cut -d '=' -f2)
AUTH_PASS=$(grep TRADER_AUTH_PASS "$ENV_FILE" | cut -d '=' -f2)
PUBLIC_IP=$(curl -s https://api.ipify.org || echo "YOUR_SERVER_IP")

echo ""
echo "======================================================================"
echo " 🎉 Trader-N is now DEPLOYED and running 24/7 as a background service!"
echo "======================================================================"
echo ""
echo " 🌐 Dashboard URL:    http://$PUBLIC_IP:8080"
echo " 👤 Username:         $AUTH_USER"
echo " 🔑 Password:         $AUTH_PASS"
echo ""
echo " 📊 Service Status:   sudo systemctl status trader-n"
echo " 📜 Live Logs:        sudo journalctl -u trader-n -f"
echo " 🔄 Restart Service:  sudo systemctl restart trader-n"
echo " 🛑 Stop Service:     sudo systemctl stop trader-n"
echo ""
echo " 💾 All databases and learned models persist in: $PROJECT_DIR/data_store"
echo "======================================================================"
