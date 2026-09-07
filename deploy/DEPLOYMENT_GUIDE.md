# Trader-N: 24/7 Private Online Deployment & Continuous Analytics Guide

This guide provides instructions for deploying **Trader-N** to run **24/7 continuously and privately** on cloud infrastructure with zero-trust access control, automatic recovery, persistent memory, and continuous performance analytics.

---

## 1. Hosting Architecture Options

| Option | Best For | Cost | Setup Time | Security |
|---|---|---|---|---|
| **Option A: Cloud VPS + Systemd** *(Recommended)* | Maximum speed, 100% control, permanent SQLite volume | $3.50 – $6 / mo | 2 minutes | High (HTTP Auth + Firewall) |
| **Option B: Cloudflare Tunnel** | Access from mobile/desktop without opening public ports | Free | 3 minutes | Maximum (Zero open ports, HTTPS, Zero Trust) |
| **Option C: Docker & Compose** | Containerized server, easy porting | Same as VPS | 2 minutes | High (Container isolation) |

---

## 2. Option A: 1-Click Cloud VPS Deployment (Recommended)

### Step 1: Spin up any cheap Linux VPS
Recommended providers:
- **Hetzner Cloud**: CAX11 (ARM64) or CX22 (~€3.50 / month) — *Lowest latency & cost*
- **DigitalOcean**: Basic Droplet 1GB RAM ($4 – $6 / month)
- **AWS Lightsail**: 1GB RAM ($3.50 / month)
- **Linode / Akamai**: Nanode 1GB ($5 / month)

*Choose **Ubuntu 22.04 LTS** or **Ubuntu 24.04 LTS** as the Operating System.*

### Step 2: Upload or Clone the Code to the VPS
Connect to your VPS via SSH:
```bash
ssh root@<YOUR_SERVER_IP>
```

Upload your Trader-N folder or clone from Git:
```bash
# Clone repository
git clone https://github.com/<your-username>/Trader-N.git /home/trader/Trader-N
cd /home/trader/Trader-N
```

### Step 3: Run the Automated Setup Script
```bash
chmod +x deploy/setup_vps.sh
./deploy/setup_vps.sh
```

**What the script automatically does:**
1. Installs Python 3, pip, venv, and system packages.
2. Creates an isolated Python virtual environment (`.venv`) and installs dependencies.
3. Generates a random, secure authentication password in `.env` (`TRADER_AUTH_PASS`).
4. Installs and registers the `trader-n.service` systemd service.
5. Enables `Restart=always` so the bot restarts automatically if the server reboots or crashes.
6. Opens port 8080 in UFW firewall and starts the service.

### Step 4: Access Your Dashboard
Open your browser and navigate to:
```
http://<YOUR_SERVER_IP>:8080
```
Enter the username `admin` and the password printed by `setup_vps.sh`.

---

## 3. Option B: Secure Remote Access with Cloudflare Tunnel (Zero Open Ports)

If you want **HTTPS encryption**, a custom domain (e.g. `https://trader.yourdomain.com`), and want to **close port 8080 to the public internet**, use a Cloudflare Tunnel:

### Step 1: Install `cloudflared` on the VPS
```bash
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
```

### Step 2: Create Tunnel
```bash
# Authenticate with your Cloudflare account
cloudflared tunnel login

# Create a tunnel named trader-n
cloudflared tunnel create trader-n
```

### Step 3: Configure Tunnel Routing
Create `~/.cloudflared/config.yml`:
```yaml
tunnel: <TUNNEL_ID>
credentials-file: /root/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: trader.yourdomain.com
    service: http://localhost:8080
  - service: http_status:404
```

Route your domain DNS to the tunnel:
```bash
cloudflared tunnel route dns trader-n trader.yourdomain.com
```

Install and start cloudflared as a system service:
```bash
sudo cloudflared service install
sudo systemctl start cloudflared
sudo systemctl enable cloudflared
```

### Step 4: Close Public Port 8080 (Maximum Security)
Now that traffic flows securely through Cloudflare's encrypted edge:
```bash
sudo ufw delete allow 8080/tcp
```
Only your Cloudflare Tunnel can communicate with port 8080 locally!

---

## 4. Option C: Docker & Docker Compose Deployment

If you prefer Docker containers:

```bash
cd /path/to/Trader-N

# 1. Edit docker-compose.yml to set your desired password:
nano docker-compose.yml

# 2. Build and launch in detached background mode:
docker compose up -d --build

# 3. View live logs:
docker compose logs -f

# 4. Stop:
docker compose down
```

The database and memory graphs persist in the `./data_store` directory on the host machine.

---

## 5. Day-to-Day Operations & Service Management

### Check Service Status
```bash
sudo systemctl status trader-n
```

### View Live Streaming Logs in Real Time
```bash
sudo journalctl -u trader-n -f -n 100
```

### Restart Service (e.g., after pulling updates)
```bash
sudo systemctl restart trader-n
```

### Stop Service
```bash
sudo systemctl stop trader-n
```

---

## 6. How to Analyze Trades & Machine Learnings Over Time

Trader-N features dedicated tools to continuously evaluate performance and improve the model over weeks and months:

### 1. Interactive Analytics & Long-Term Performance Tab
In the web dashboard (`http://<SERVER_IP>:8080`):
- Click the **"Analytics & Long-Term Performance"** tab.
- **Cumulative Equity Progression Curve**: Visualizes whether capital is compounding up and where drawdowns occurred.
- **Profit Factor & Win Rate**: Tracks efficiency ratio ($GrossProfit / GrossLoss$).
- **Exit Triggers & Attribution**: Shows which exit rules generated the most profit (e.g. `MOONBAG_RUNNER_EXIT`, `TAKE_PROFIT`) vs prevented losses (`EMERGENCY_DEV_DUMP`, `STOP_LOSS`).
- **Historical Closed Positions Ledger**: Searchable, filterable table of every past trade.

### 2. Exporting Data for Deep Quantitative & AI Analysis
You can download full datasets with 1 click in the dashboard or via curl/scripts:

- **Download All Closed Trades (CSV)**:
  ```bash
  curl -u admin:<YOUR_PASSWORD> http://<SERVER_IP>:8080/api/analytics/export/trades.csv -o trades.csv
  ```
  *Contains: symbol, mint, entry/exit timestamps, entry price, exit price, hold duration, PnL SOL, PnL %, trigger wallet, and confidence score.*

- **Download Full Cognitive Memory Dossier (JSON)**:
  ```bash
  curl -u admin:<YOUR_PASSWORD> http://<SERVER_IP>:8080/api/analytics/export/learnings.json -o learnings.json
  ```
  *Contains: all episodic failure autopsies, counterfactual shadow tracking outcomes (dodged rugs vs missed runners), discovered hypotheses with statistical lift, and mapped Sybil clusters.*

- **Fetch Real-Time Analytics Summary (JSON)**:
  ```bash
  curl -u admin:<YOUR_PASSWORD> http://<SERVER_IP>:8080/api/analytics/summary
  ```

---

## 7. Backups & Disaster Recovery

All persistent state (wallet graphs, token lifecycle memory, trade history, and Bayesian parameter models) is stored in the SQLite database:
```
data_store/trader.db
```

### To create an atomic online backup without stopping the bot:
```bash
sqlite3 data_store/trader.db ".backup data_store/backup_$(date +%Y%m%d).db"
```

To automate daily backups, add to crontab (`crontab -e`):
```bash
0 3 * * * sqlite3 /home/trader/Trader-N/data_store/trader.db ".backup /home/trader/Trader-N/data_store/backup_\$(date +\%Y\%m\%d).db"
```
