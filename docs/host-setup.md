# Mac Mini host setup

**Before this file:** finish [hardware-and-network.md](hardware-and-network.md) (physical box, Ethernet, no port forwards, accounts). This file is Homebrew, Ollama.app, LaunchAgents, and the tunnel daemon.

Run on the **M4 Mini**, not a laptop. Work top to bottom; the gates near the top exist because skipping them fails much later and much less obviously.

## 0. Architecture gate — run this first

```bash
uname -m                                    # must print: arm64
file "$(which brew)"                        # arm64
```

If either says `x86_64`, your Terminal or Homebrew is running under Rosetta. Stop and fix that before installing anything. `pyobjc-framework-Vision` and `mlx` are the reason this project is on Apple Silicon; under translation they either fail to install or run on the CPU, and the failure mode later on is "OCR is mysteriously broken" rather than an honest error.

To check a Terminal: right-click Terminal.app → Get Info → **Open using Rosetta must be unchecked**.

## 1. Energy, boot policy, and FileVault

System Settings → Energy / Battery (desktop):

- Prevent automatic sleeping when display is off
- Wake for network access
- Start up automatically after a power failure
- Display can sleep; **computer must not**

System Settings → General → Date & Time → **Set time and date automatically** must be on. Artifact URL signatures expire against this clock; a drifting clock produces 404s on valid links.

### FileVault vs unattended reboot — read before enabling either

With FileVault on, a cold boot stops at the **pre-boot unlock screen**. No user is logged in, so:

- no LaunchAgent in `gui/$UID` runs,
- Ollama.app (a GUI application) does not start,
- "start up automatically after a power failure" gets you to a locked screen and nothing more.

`docs/licenses.md` assumes FileVault is on because the Mini holds CRM data. `PLAN.md` §22 promises the appliance comes back after a reboot. Both are true only for a reboot where a human is present, or where you used:

```bash
sudo fdesetup authrestart      # unlocks the disk for exactly the NEXT boot; planned reboots only
```

Choose a policy in `docs/operator-checklist.md` §6 and write it down. Then, regardless:

```bash
# Automatic login for the appliance account — without a GUI session, nothing in this file runs.
# System Settings > Users & Groups > Automatic login
```

Verify the whole thing once, deliberately: reboot the Mini and time how long until `/v1/health` is green. That number is your recovery time, and if it is "never, until someone types a password", you need to know that now rather than during an outage.

## 2. Base packages

```bash
xcode-select --install
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"

brew install python@3.11 uv node@22 ffmpeg graphviz zbar poppler cloudflared git
```

**Do not `brew install ollama`.** Check and remove it if it is there:

```bash
brew list | grep -i ollama        # must print nothing
brew uninstall ollama 2>/dev/null
```

Two Ollama installs fight over `127.0.0.1:11434`. The loser logs "address already in use"; worse, if the brew service wins it runs **without** the LaunchAgent environment, so `OLLAMA_MAX_LOADED_MODELS` is unset and the entire 24 GB discipline in `PLAN.md` §4 silently stops applying.

Then install the official app: `open https://ollama.com/download/mac`

Python 3.11, arm64:

```bash
export PATH="/opt/homebrew/opt/python@3.11/bin:/opt/homebrew/opt/node@22/bin:$PATH"
python3.11 --version
python3.11 -c "import platform; print(platform.machine())"   # must print: arm64
file "$(which python3.11)"                                   # must say arm64
uv python install 3.11
uv python pin 3.11                                           # writes .python-version, commit it
```

If `pyobjc-framework-Vision` imports but fails at runtime with a framework-build complaint, build the venv against Homebrew's framework Python instead:

```bash
uv venv --python /opt/homebrew/opt/python@3.11/bin/python3.11
```

## 3. Spotlight and Time Machine exclusions

Weight caches are tens of gigabytes of rarely-changing, incompressible files. Time Machine will copy them on every backup; `mdworker` will index them. Both produce disk and memory churn at unpredictable moments — including in the middle of a generation.

```bash
mkdir -p ~/Cloudiator/{artifacts,logs,models}

tmutil addexclusion ~/.ollama
tmutil addexclusion ~/.cache/huggingface
tmutil addexclusion ~/Cloudiator/artifacts
tmutil addexclusion ~/Cloudiator/models
tmutil addexclusion ~/Cloudiator/logs

# Spotlight: add the same paths under System Settings > Siri & Spotlight > Spotlight Privacy,
# or drop a .metadata_never_index marker in each:
touch ~/.ollama/.metadata_never_index
touch ~/Cloudiator/artifacts/.metadata_never_index
touch ~/Cloudiator/models/.metadata_never_index

tmutil isexcluded ~/.ollama          # [Excluded]
```

## 4. macOS Sequoia Local Network permission

On Sequoia, a process **first launched by `launchd`** can be denied local network access with no prompt that anyone will ever see. `cloudflared` and the worker then behave exactly as if the other end is down, and you will debug the tunnel for an hour.

Run each binary **once interactively in Terminal**, approve the prompt if it appears, then check:

System Settings → Privacy & Security → **Local Network** — `cloudflared` and your Terminal/Python should be listed and enabled.

Only after that, bootstrap the LaunchAgents.

## 5. Ollama

After installing the .app, confirm `which ollama`, then:

```bash
ollama pull qwen3.5:9b          # verify the tag first — see PLAN.md section 7, Phase A step 0
ollama show qwen3.5:9b          # confirm tools support; note whether it supports vision
ollama pull nomic-embed-text
# gpt-oss:20b belongs to Phase E, not now. It is ~14GB.
```

Set the environment on the Ollama app (its settings pane if it persists env) or via a LaunchAgent wrapper. Documented macOS env: https://docs.ollama.com/faq

Required:

```
OLLAMA_HOST=127.0.0.1:11434
OLLAMA_MAX_LOADED_MODELS=2     # slot 1 = one generative model, slot 2 = nomic-embed-text ONLY
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_QUEUE=32
OLLAMA_FLASH_ATTENTION=1
OLLAMA_KEEP_ALIVE=30m          # safety net only; the worker always sends explicit keep_alive
```

`MAX_LOADED_MODELS=2` is deliberate and is explained in `PLAN.md` §4: with `1`, every embeddings call evicts the chat model and the next chat pays a 5–15s cold load. The "one Metal-heavy model" rule is enforced by the worker's scheduler, not by this number. Do **not** raise it to 4.

Verify the running server actually has the env:

```bash
curl -s http://127.0.0.1:11434/api/tags | jq '.models[].name'
ollama ps                                  # after a chat: one generative model, plus nomic-embed-text
```

## 6. Worker LaunchAgent

Phase A creates `~/Library/LaunchAgents/ai.cloudiator.worker.plist`. **Substitute your real username for `REPLACE` before loading** — a plist with literal `REPLACE` paths loads "successfully" and then fails to exec, which looks like a working install.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ai.cloudiator.worker</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/REPLACE/Cloudiator/run-worker.sh</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/REPLACE/cldM4/apps/worker</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>MPLBACKEND</key><string>Agg</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>/Users/REPLACE/Cloudiator/logs/worker.log</string>
  <key>StandardErrorPath</key><string>/Users/REPLACE/Cloudiator/logs/worker.err</string>
</dict>
</plist>
```

A wrapper script is easier than an env dict, because the `.env` file is the single source of truth:

```bash
#!/bin/zsh
# /Users/REPLACE/Cloudiator/run-worker.sh   (chmod +x)
set -a
source /Users/REPLACE/Cloudiator/.env
set +a
export MPLBACKEND=Agg
cd /Users/REPLACE/cldM4/apps/worker
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1
```

`--workers 1` is mandatory, not a default to rely on. `metal_lock` is an in-process `asyncio.Lock`; two workers means two schedulers that each think they own Metal, and the first concurrent FLUX + 20B pair asks a 24 GB machine for ~25 GB. No `--reload` here either — the reloader forks.

Load it with the modern subcommands. `launchctl load` is deprecated, silently no-ops in several situations, and tells you nothing when it fails:

```bash
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/ai.cloudiator.worker.plist
launchctl enable  gui/$UID/ai.cloudiator.worker
launchctl kickstart -k gui/$UID/ai.cloudiator.worker
launchctl print   gui/$UID/ai.cloudiator.worker | head -20     # state = running, last exit status = 0

# and verify it is actually serving, not just "running":
lsof -nP -iTCP:8080 -sTCP:LISTEN        # 127.0.0.1:8080, never *:8080
curl -s http://127.0.0.1:8080/v1/health | jq
pgrep -fc "uvicorn app.main:app"        # exactly 1

# to remove:
launchctl bootout gui/$UID/ai.cloudiator.worker
```

LaunchAgents in `gui/$UID` require a **logged-in GUI session** — see §1 on FileVault and automatic login.

## 7. Log rotation

`KeepAlive=true` plus an unrotated `StandardOutPath` is an unbounded file, and a full SSD takes down Ollama, the worker, and the tunnel simultaneously.

`/etc/newsyslog.d/cloudiator.conf` (needs sudo):

```
# logfilename                                  [owner:group]  mode count size(KB) when  flags
/Users/REPLACE/Cloudiator/logs/worker.log      REPLACE:staff  644  7     10240    *     GJ
/Users/REPLACE/Cloudiator/logs/worker.err      REPLACE:staff  644  7     10240    *     GJ
```

```bash
sudo newsyslog -nvv        # dry run: confirm it parses and picks up the files
```

## 8. cloudflared

Fill in `docs/operator-checklist.md` §§1–2 first. The Cloudflare zone must show **Active**.

```bash
cloudflared tunnel login
cloudflared tunnel create cloudiator-mini
```

`~/.cloudflared/config.yml`:

```yaml
tunnel: TUNNEL_UUID
credentials-file: /Users/REPLACE/.cloudflared/TUNNEL_UUID.json
no-autoupdate: true          # a self-update restarts the tunnel mid-job
protocol: quic               # use http2 on Wi-Fi-only installs, or if ISP/router breaks QUIC/UDP
ingress:
  - hostname: api.YOURDOMAIN
    service: http://127.0.0.1:8080
    originRequest:
      connectTimeout: 10s
      disableChunkedEncoding: false
  - service: http_status:404
```

```bash
cloudflared tunnel route dns cloudiator-mini api.YOURDOMAIN
cloudflared tunnel run cloudiator-mini        # run interactively ONCE (Local Network prompt, section 4)
# then install as a service or a LaunchAgent using the same bootstrap pattern as section 6
```

**Named tunnel only.** Quick `cloudflared tunnel --url http://localhost:8080` is not production: random hostname, streaming issues.

Verify the one thing that must never be wrong:

```bash
grep -c 11434 ~/.cloudflared/config.yml       # must be 0
grep -n "service:" ~/.cloudflared/config.yml  # exactly one port, and it is 8080
```

If `11434` was ever exposed, the Ollama API was on the public internet with no authentication. Rotate every API key and assume the models were used by strangers.

## 9. Cloudflare zone settings (Salesforce will not work without these)

Apex callouts are not browsers: no JavaScript, no cookies, no challenge solving. Any Cloudflare feature that replies with an interstitial turns a Salesforce callout into an HTML body that `JSON.deserialize` chokes on, and the Apex-side error says nothing about security.

On `api.<domain>`:

- **Bot Fight Mode: OFF** (Security → Bots). Super Bot Fight Mode: off, or "Allow" for definitely-automated.
- **Security Level: Essentially Off** (a Configuration Rule scoped to the hostname is tidier than changing the zone).
- **Browser Integrity Check: OFF.**
- **No Turnstile, no managed challenge.**
- **Never "I'm Under Attack" mode** while orgs depend on this endpoint.

WAF custom rule, action **Skip**, above all other custom rules:

```
(http.host eq "api.<domain>" and starts_with(http.request.headers["authorization"][0], "Bearer sk-cld-"))
```

Skip: all managed rules, Super Bot Fight Mode, rate limiting rules, Browser Integrity Check.

Rate limiting: key the rule on the **Authorization header**, not the IP. Salesforce egress IPs are shared across orgs, so an IP-keyed limit lets one tenant throttle another.

Cloudflare Access on `app.<domain>` and `api.<domain>/v1/admin*`. Record the team domain and application **AUD** — the worker validates the Access JWT against them.

## 10. Health ping

Every 2 minutes:

```bash
curl -sf http://127.0.0.1:8080/v1/health || curl -sS -X POST "$SLACK_WEBHOOK_URL" -d '{"text":"Cloudiator Mini health failed"}'
```

`/v1/health` is deliberately local-only and does **not** touch Neon (`PLAN.md` §10). If you "improve" it with a `SELECT 1`, a suspended Neon compute will page you at 3am about a perfectly healthy Mini.

Test the alert by stopping the worker. An appliance with untested alerting is an appliance whose outages you hear about from a Salesforce user.

## Do not

- Docker Desktop for Ollama/MLX
- `brew install ollama` alongside Ollama.app
- `OLLAMA_HOST=0.0.0.0` on a home LAN without a firewall
- `OLLAMA_MAX_LOADED_MODELS` above 2
- `uvicorn --workers` above 1, or `--reload` in a LaunchAgent
- `launchctl load` (use `bootstrap`)
- Tunnel `http://localhost:11434`
- Leave literal `REPLACE` in a plist or config file
