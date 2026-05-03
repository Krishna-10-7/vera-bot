# Vera Bot — Linux VM Deployment & Diagnostics Checklist

## Critical Issues & Fixes

The judge reported that endpoints were **sometimes unreachable** during testing. This checklist identifies and resolves root causes.

### Fixes Already Pushed to GitHub:
✅ **Azure OpenAI Strict JSON Schema** — Guarantees 100% output format compliance  
✅ **Async Semaphore (5 concurrent)** — Prevents burst rate-limit hits on your 105k TPM limit

---

## Phase 1: Verify Network Binding & Firewall

### 1.1 Check bot is listening on all interfaces

SSH into your VM and verify the bot is bound to `0.0.0.0` (all interfaces):

```bash
sudo netstat -tlnp | grep 8080
# OR
ss -tlnp | grep 8080
```

**Expected output:**
```
LISTEN 0.0.0.0:8080 ...
```

**If you see `127.0.0.1:8080`:** The bot is only accessible locally.  
**FIX:** Ensure startup command uses `--host 0.0.0.0` not `--host 127.0.0.1`

### 1.2 Check Azure VM firewall rules

On your Azure subscription, verify the VM's **Network Security Group (NSG)** allows inbound traffic:

```
Required Inbound Rules:
- Port 22 (SSH) ✅
- Port 80 (HTTP) ✅ [used by Nginx]
- Port 8080 (Optional) ✅ [direct bot access]
```

If missing, add via Azure Portal or Azure CLI. Contact your cloud admin if needed.

### 1.3 Verify Nginx is proxying correctly

Test locally on the VM:

```bash
curl -v http://127.0.0.1/v1/healthz
curl -v http://127.0.0.1/v1/metadata
```

**Expected:** 200 OK with JSON response

**If 404 Not Found:**
- Check Nginx config: `sudo cat /etc/nginx/sites-enabled/vera`
- Verify `server_name _;` is set (wildcard match)
- Verify Nginx is running: `sudo systemctl status nginx`
- Reload: `sudo systemctl reload nginx`

### 1.4 Test from outside the VM

From your local machine (replace IP with your actual public IP):

```bash
curl -v http://<your-vm-ip>/v1/healthz
curl -v http://<your-vm-ip>/v1/metadata
```

**If fails:**
1. Check Azure NSG port 80 is open
2. Verify bot is running: `ps aux | grep uvicorn`
3. Check Nginx logs: `sudo tail -20 /var/log/nginx/error.log`
4. Check system logs: `sudo journalctl -xe`

---

## Phase 2: Pull Latest Code & Restart

Critical improvements have been pushed to fix structured outputs and burst protection:

```bash
cd ~/vera-bot
git pull origin main
```

**Stop the old bot and restart:**

```bash
# Kill the running process
kill %1
# OR use pkill
pkill -f "uvicorn bot:app"
sleep 2

# Re-export your Azure credentials (from your saved setup)
# Do NOT hardcode these — use environment variables or config file
export AZURE_OPENAI_API_KEY="<paste-your-key-here>"
export AZURE_OPENAI_ENDPOINT="<paste-your-endpoint-here>"
export AZURE_OPENAI_DEPLOYMENT_NAME="<paste-your-deployment-name>"
export AZURE_OPENAI_API_VERSION="2024-12-01-preview"

# Start bot with new code
python -m uvicorn bot:app --host 0.0.0.0 --port 8080 &
```

**Verify startup:**
```bash
# Should see:
# [VERA] Bot starting - LLM: azure_openai (...)
# Application startup complete
sleep 2
curl http://127.0.0.1:8080/v1/healthz
```

---

## Phase 3: Comprehensive Testing

### 3.1 Health & Metadata Endpoints

```bash
# From VM
curl http://127.0.0.1:8080/v1/healthz
curl http://127.0.0.1:8080/v1/metadata

# From external
curl http://<your-vm-ip>/v1/healthz
curl http://<your-vm-ip>/v1/metadata
```

**Expected:** 200 OK with JSON containing:
- `"status": "ok"`
- `"llm_provider": "azure_openai (...)"`

### 3.2 Context Ingestion

```bash
curl -X POST http://127.0.0.1:8080/v1/context \
  -H "Content-Type: application/json" \
  -d '{
    "scope": "category",
    "context_id": "test_cat_001",
    "version": 1,
    "payload": {"name": "Test Category", "slug": "test"}
  }'
```

**Expected:** 200 with `"accepted": true`

### 3.3 Tick Endpoint (Composition)

```bash
curl -X POST http://127.0.0.1:8080/v1/tick \
  -H "Content-Type: application/json" \
  -d '{
    "now": "2026-05-03T12:00:00Z",
    "available_triggers": []
  }'
```

**Expected:** 200 with `{"actions": []}`

---

## Phase 4: Monitoring & Long-term Stability

### 4.1 Current Setup (tmux in background)

Verify bot is running:

```bash
tmux list-sessions
tmux capture-pane -t vera -p
```

This keeps bot alive while terminal is detached, but does NOT survive VM reboot.

### 4.2 Recommended: Switch to Systemd (auto-restart on crash/reboot)

Create `/etc/systemd/system/vera-bot.service`:

```bash
sudo nano /etc/systemd/system/vera-bot.service
```

Paste (substitute your username if not `azureuser`):

```ini
[Unit]
Description=Vera Bot FastAPI Service
After=network.target

[Service]
Type=simple
User=azureuser
WorkingDirectory=/home/azureuser/vera-bot
# Store credentials in environment file, NOT in this file
EnvironmentFile=/home/azureuser/.vera-bot.env
ExecStart=/home/azureuser/vera-bot/.venv/bin/python -m uvicorn bot:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Create credential file (ONE TIME):

```bash
cat > ~/.vera-bot.env << 'EOF'
AZURE_OPENAI_API_KEY=<paste-your-key>
AZURE_OPENAI_ENDPOINT=<paste-your-endpoint>
AZURE_OPENAI_DEPLOYMENT_NAME=<paste-your-deployment>
AZURE_OPENAI_API_VERSION=2024-12-01-preview
EOF

chmod 600 ~/.vera-bot.env  # Secure: readable only by you
```

Enable service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable vera-bot
sudo systemctl start vera-bot
sudo systemctl status vera-bot
```

View logs:

```bash
sudo journalctl -u vera-bot -f
```

---

## Phase 5: Judge Simulator Compliance

The official judge will test these phases:

### Warmup Phase (30s)
- Calls `/v1/healthz` every 10s
- Calls `/v1/metadata` once
- **3 consecutive failures = disqualification**

**Your bot must:**
- ✅ Return 200 OK
- ✅ Include `"llm_provider"` field
- ✅ Include all endpoints in response

### Context Loading Phase (60s)
- POSTs 30+ merchant contexts with varying versions
- Some will be stale (version < current)

**Your bot must:**
- ✅ Accept new versions
- ✅ Return HTTP 409 Conflict on stale versions
- ✅ Include current version in response

### Tick Phase (10s timeout)
- POSTs up to 20 triggers
- Expects < 9s latency

**Your bot must:**
- ✅ Compose all messages in < 9s
- ✅ Return valid JSON actions
- ✅ Use new semaphore to prevent burst limits

### Reply Phase (multi-turn)
- POSTs customer messages
- Tests auto-reply detection

**Your bot must:**
- ✅ Detect auto-replies by turn 3
- ✅ Transition to ENDED state
- ✅ Avoid score penalties from repetition

---

## Troubleshooting Reference

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| 404 from external IP | Azure NSG blocking port 80 | Add inbound rule in portal |
| 404 from Nginx | Wrong `server_name` config | Set `server_name _;` |
| Bot only localhost | Bot bound to 127.0.0.1 | Use `--host 0.0.0.0` |
| 503 Service Unavailable | Bot crashed | Restart process or check systemd |
| Timeout on /v1/tick | Compose too slow | Check LLM latency, verify semaphore active |
| 429 Rate Limited | Too many concurrent LLM calls | Semaphore should limit to 5 |
| 409 Conflict not working | Version check broken | Verify `context_store.py` logic |

---

## Next Steps

1. **Now:** SSH into VM and run Phase 1 diagnostics
2. **Then:** `git pull` and restart bot with new code
3. **Verify:** Run Phase 3 endpoint tests
4. **Stabilize:** Switch to systemd service (recommended)
5. **Monitor:** Check logs regularly with `journalctl -u vera-bot -f`

**When all phases pass locally, you're ready for the judge simulator.** 🚀
