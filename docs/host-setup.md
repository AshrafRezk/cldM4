# Mac Mini host setup

Run on the **M4 Mini**, not a laptop.

## Energy

System Settings → Energy / Battery (desktop):

- Prevent automatic sleeping when display is off
- Wake for network access
- Start up automatically after a power failure
- Display can sleep; **computer must not**

## Base packages

```bash
xcode-select --install
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"

brew install python@3.11 uv node@22 ffmpeg graphviz zbar poppler cloudflared git
# Official Ollama: download .dmg
open https://ollama.com/download/mac
```

Python 3.11:

```bash
export PATH="/opt/homebrew/opt/python@3.11/bin:/opt/homebrew/opt/node@22/bin:$PATH"
python3.11 --version
```

## Ollama

After installing the .app, confirm `which ollama` and:

```bash
ollama pull qwen3.5:9b
ollama pull nomic-embed-text
# Phase E later: gpt-oss:20b
```

Create `~/Library/LaunchAgents/com.cloudiator.ollama.env.plist` **or** set env in the Ollama app settings if the GUI supports it. Prefer a LaunchAgent wrapper only if the .app does not persist env. Documented Ollama macOS env: https://docs.ollama.com/faq

Required:

```
OLLAMA_HOST=127.0.0.1:11434
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_QUEUE=32
OLLAMA_FLASH_ATTENTION=1
OLLAMA_KEEP_ALIVE=30m
```

Verify: `curl -s http://127.0.0.1:11434/api/tags`

## Worker LaunchAgent

Phase A creates `~/Library/LaunchAgents/ai.cloudiator.worker.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ai.cloudiator.worker</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/REPLACE/cldM4/apps/worker/.venv/bin/uvicorn</string>
    <string>app.main:app</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>8080</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/REPLACE/cldM4/apps/worker</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>MPLBACKEND</key><string>Agg</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/REPLACE/Cloudiator/logs/worker.log</string>
  <key>StandardErrorPath</key><string>/Users/REPLACE/Cloudiator/logs/worker.err</string>
</dict>
</plist>
```

Load env from a file in the real unit (plist env dict or `EnvironmentFiles` if you use a wrapper script). Wrapper script is easier:

```bash
#!/bin/zsh
set -a
source /Users/REPLACE/Cloudiator/.env
set +a
export MPLBACKEND=Agg
cd /Users/REPLACE/cldM4/apps/worker
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080
```

```bash
launchctl load ~/Library/LaunchAgents/ai.cloudiator.worker.plist
```

## cloudflared LaunchAgent

```bash
cloudflared tunnel login
cloudflared tunnel create cloudiator-mini
```

`~/.cloudflared/config.yml`:

```yaml
tunnel: TUNNEL_UUID
credentials-file: /Users/REPLACE/.cloudflared/TUNNEL_UUID.json
ingress:
  - hostname: api.YOURDOMAIN
    service: http://127.0.0.1:8080
  - service: http_status:404
```

```bash
cloudflared tunnel route dns cloudiator-mini api.YOURDOMAIN
sudo cloudflared service install
# or LaunchAgent: cloudflared tunnel run cloudiator-mini
```

**Named tunnel only.** Quick `cloudflared tunnel --url http://localhost:8080` is not production (random hostname, streaming issues).

## Health ping

cron every 2 minutes: `curl -sf http://127.0.0.1:8080/v1/health || curl -sS -X POST $SLACK_WEBHOOK_URL -d '{"text":"Cloudiator Mini health failed"}'`

## Do not

- Docker Desktop for Ollama/MLX
- `OLLAMA_HOST=0.0.0.0` on a home LAN without a firewall
- Tunnel `http://localhost:11434`
