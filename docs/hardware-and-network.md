# Hardware and internet runbook

**Read this on the Mac Mini before writing code.** Software in `PLAN.md` assumes this box is powered, awake, on the LAN, and reachable from the public internet **only** through Cloudflare Tunnel. Ethernet is preferred; **this Mini is Wi-Fi-only** (operator exception, §3a). If this page is wrong, every later phase looks like an application bug.

Operator blanks (domain, accounts): [operator-checklist.md](operator-checklist.md).  
Software install after this page is green: [host-setup.md](host-setup.md).

---

## 0. Confirm you have the right machine

On the Mini: Apple menu → About This Mac.

| Must be | Why |
| --- | --- |
| **Mac mini** (2024), chip **M4** | Metal / MLX / Vision |
| Memory **24 GB** (unified) | Plan RAM table. 16 GB is a different product; do not follow this repo on 16 GB |
| Storage **512 GB+ comfortable**; 256 GB is tight | Models + FLUX weights + artifacts. Need **≥ 120 GB free** before pulls (`df -h /`) |
| `uname -m` prints **`arm64`** | Not a VM, not UTM, not Rosetta Terminal |

Write it down:

```
Chip: Apple M4   Memory: 24 GB   Disk: 494 GB (443 GB free, 2026-09-19)   Serial: F47YLJF2M
Name: Ashraf's Mac mini (2024)   Local hostname: cloudiator.local   LAN: 192.168.100.51 (Wi-Fi)
```

Recorded from About This Mac + Storage + Sharing screenshots, 2026-09-19. This **is** the right SKU. If this is an M4 **Pro** 24 GB, the plan still applies (same memory ceiling). If it is 16 GB or Intel, stop.

---

## 1. Physical setup (30–45 min)

### Desk and cooling

- Sit the Mini **on a hard, open surface**. Not in a closed cabinet, not under a monitor sandwich, not on carpet.
- Leave the rear vents and the bottom clear. M4 active cooling holds 9B chat indefinitely; FLUX bursts raise fan noise. A closed box causes thermal throttle then swap-like slowness.
- Ambient: normal office. Do not put it next to a heater.

### Cables (minimum)

The 2024 Mac mini M4 has **HDMI, USB-C, Gigabit Ethernet** (10 GbE is a configure-to-order option), 3.5 mm, power.

Plug in, in this order:

1. **Power brick into a wall outlet or a UPS.** Not a cheap USB-C hub “power passthrough.”
2. **Ethernet** from Mini Ethernet port → router LAN port. Prefer this over Wi-Fi for the tunnel and for 20–50 GB model downloads. **Operator exception (2026-09-19): Ethernet is not feasible. Wi-Fi-only is accepted — see §3a. Do not turn Wi-Fi off.**
3. **Display** (HDMI or USB-C) + keyboard + mouse for first boot, FileVault unlock, and Local Network permission prompts. A screen-only desk plus LAN Screen Sharing is enough for day-to-day; keep a **keyboard in the room** for FileVault unlock after a power cut (Screen Sharing cannot type at the pre-boot lock screen). After auto-login works you can leave the display dark.
4. Optional: USB-C Ethernet adapter only if you must use a dongle; onboard Ethernet is better.

**UPS (strongly recommended):** FileVault + a power cut means the Mini sits at the disk-unlock screen and **does not run Ollama or the tunnel** until a human types a password. A small UPS covering 10–30 minutes of outages is the difference between “Salesforce works” and “mystery 503s.” Record the UPS choice in operator-checklist §6.

**HDMI dummy plug:** usually **not** required on Apple Silicon. If after going headless you see Metal/Ollama GPU errors, plug a display back in or use a cheap HDMI dummy. Do not start there.

### What not to attach

- External GPU: Mini M4 has no eGPU path that helps Ollama.
- A spinning USB disk for model weights: slow and will swap. Keep `~/.ollama` on the **internal SSD**.
- A second heavy Metal app (DaVinci, games, another LLM UI) on this machine while it is the appliance.

### First macOS session

1. Complete macOS Setup Assistant. Use a dedicated **appliance user** (example name: `cloudiator`). Create a **separate admin** user for software updates.
2. Sign in with an Apple ID that you control (Find My is useful if the box is stolen; FileVault recovery key goes in the password manager).
3. System Settings → General → **Software Update** — install everything, reboot, then freeze casual updates during Phase A–B (an Ollama.app + macOS update mid-pull is painful). Resume updates weekly once production.
4. System Settings → General → Sharing → **Local hostname**: `cloudiator-mini` (so `cloudiator-mini.local` works on the LAN).
5. Enable **Screen Sharing** and/or **SSH** for *the LAN only* (Sharing → Screen Sharing / Remote Login). You will debug from a laptop on the same Wi-Fi. Do **not** expose 22 or 5900 on the router.

Energy (System Settings → Energy):

- Prevent sleep when display is off
- Wake for network access
- Start up after power failure
- Display may sleep; **computer must not**

Date & Time: **Set time automatically**. Signed artifact URLs use this clock.

FileVault: pick policy A/B/C in operator-checklist §6 **today**, then Automatic login for the appliance user (required or LaunchAgents never start).

---

## 2. What is on the internet vs what must stay private

```text
Salesforce / websites  --HTTPS-->  Cloudflare edge  --Tunnel (outbound from Mini)-->  127.0.0.1:8080 worker
                                                                              \-> 127.0.0.1:11434 Ollama   NEVER public
Admin browser          --HTTPS-->  app.<domain> (Netlify) --> Neon
Mini worker            --outbound HTTPS-->  Neon, Nominatim, Overpass, OSRM, Hugging Face, GitHub
```

| Place | Public? | Notes |
| --- | --- | --- |
| `https://api.<domain>` | **Yes** (Cloudflare) | Only path Salesforce uses. TLS at Cloudflare. Auth = `Bearer sk-cld-` on the worker |
| `https://app.<domain>` | **Yes** (Netlify + Cloudflare Access) | Dashboard. No inference |
| `127.0.0.1:8080` | **No** | Worker. Tunnel is the only ingress |
| `127.0.0.1:11434` | **No** | Ollama. If this is ever on WAN, rotate every key |
| Mini LAN IP `:22` / Screen Sharing | LAN only | Router must **not** port-forward these |
| Neon / Netlify / Hugging Face | Vendor SaaS | Mini **calls out**; nothing inbound required |

**Failure if skipped:** do not “help” by opening router ports 8080, 11434, 443, or 22 to WAN. Home ISPs often sit on **CGNAT** anyway, so port forwarding silently does nothing — that is why the plan uses a **named Cloudflare Tunnel** (outbound UDP/HTTPS). If you port-forward on a real public IP, you skip Cloudflare WAF and put Ollama on the internet.

---

## 3. Home / office network

### Ethernet first

1. Connect Ethernet. In System Settings → Network, Ethernet should be **Connected** with an IPv4 like `192.168.x.x` or `10.x.x.x`.
2. Turn **Wi-Fi off** on the Mini once Ethernet works. Two interfaces cause flaky tunnel reconnects.
3. In the **router** admin UI, add a **DHCP reservation** for the Mini’s Ethernet MAC → a fixed LAN IP (example `192.168.1.50`). You will SSH to that IP from a laptop. MAC is on the Mini Network pane or `ifconfig en0`.

### 3a. Wi-Fi-only exception (this Mini)

Ethernet is **not** required to start Phase A. This appliance is on **Wi-Fi only** by operator decision (2026-09-19). Cloudflare Tunnel still works: it dials **out**. What you give up is stability and download speed, not the architecture.

Rules while Ethernet is out:

- **Do not turn Wi-Fi off.** The “Ethernet then disable Wi-Fi” step above does not apply.
- Use the **main** SSID, 5 GHz if you have it. Not guest Wi-Fi, not AP isolation (Screen Sharing to `192.168.100.51` would die).
- In the router, DHCP-reserve the Mini’s **Wi-Fi** MAC so `192.168.100.51` stays put.
- First `ollama pull` (~7 GB for 9B + embed) will be slower. Overnight is fine. Disk is not the bottleneck (443 GB free).
- If the named tunnel later flaps every few minutes, set `protocol: http2` in `~/.cloudflared/config.yml` (some Wi-Fi routers break QUIC UDP 7844).
- Still **no WAN port forwards**. Screen Sharing stays LAN-only (already true: Administrators only, VNC-with-password off).

This exception can be reversed later by plugging Ethernet and then turning Wi-Fi off. Until then, treat random 502s as a network symptom before an application bug.

### 3b. How to reserve `192.168.100.51` and check port forwarding (this Mini)

These clicks happen on the **router**, not on the Mac. Open a browser **on a phone or laptop that is already on `Ash & Mimi`**.

This Mini right now:

| | |
| --- | --- |
| Router admin | `http://192.168.100.1` (the “Router” IP from the Mini’s Wi-Fi TCP/IP pane) |
| Mini LAN IP | `192.168.100.51` |
| Mini Wi-Fi MAC | `d0:11:e5:94:6b:23` |
| SSID | Ash & Mimi |

On this Mini the router is a WE / Huawei **HG8145V5** at `http://192.168.100.1`. The reservation page is **LAN → DHCP Static IP** (not the “DHCP Server” pool page). A row `d0:11:e5:94:6b:23` → `192.168.100.51` is the correct binding; click **Apply** if you just added it. Port forwarding is **Forward Rules** in the same left nav.

#### A. DHCP reservation (keep the Mini at .51)

The Mini is already at `.51` **today** via a normal DHCP lease. A reservation tells the router: “this MAC always gets .51,” so Screen Sharing does not break in a week when the lease expires.

1. In the router UI, look for one of these names: **DHCP reservation**, **Address reservation**, **Static lease**, **Bind IP to MAC**, **LAN → DHCP**.
2. Add (or “reserve existing client”):
   - MAC: `d0:11:e5:94:6b:23` (colons or dashes; routers accept either)
   - IP: `192.168.100.51`
   - Name: `cloudiator-mini` (optional)
3. Save. You do **not** need to restart the Mini if it already has that IP.

If you cannot find the screen: skip it for Phase A. `.51` will likely last days. Come back before you rely on Screen Sharing from another room after a power cut.

Do **not** set a manual IP on the Mac itself (avoid “Configure IPv4: Manually”). Leave the Mini on DHCP and pin it in the router.

#### B. Port forwarding (look, then do nothing)

You are checking that the internet **cannot** open 22 / 5900 / 8080 / 11434 on your house. Salesforce will reach the Mini later through Cloudflare Tunnel (outbound), not through these ports.

1. In the router UI, look for **Port forwarding**, **Virtual servers**, **NAT forwarding**, or **WAN applications**.
2. If the list is **empty**, you are done. Do not add anything.
3. If a row exists for 22, 5900, 8080, or 11434, **delete it**.
4. Also turn **UPnP** off for this box if you see a toggle and you are not using it for a game console (optional but cleaner). **DMZ** must not point at `192.168.100.51`.

You never need to “open a port for Cloudiator.” Opening 11434 would put Ollama on the public internet.

**Not a Phase A blocker.** Install Ollama and run `scripts/mac-setup.sh` even if the router UI is confusing. Finish this the first time you can log into `192.168.100.1`.

### Router / firewall — allow outbound, deny inbound

The Mini only needs **outbound** access:

| Destination | Typical | Purpose |
| --- | --- | --- |
| HTTPS `443/tcp` | required | GitHub, Neon, Hugging Face, Nominatim, Ollama pulls, Cloudflare |
| DNS `53` or DoH | required | Name resolution |
| Cloudflare Tunnel | required | Named tunnel: **UDP 7844** (QUIC) or fallback **TCP 443** (`http2` in `cloudflared` config) |
| NTP | required | Time (or Apple time) |

**Inbound WAN:** none. No DMZ. No UPnP for the Mini.

If corporate firewall: allow `*.cloudflare.com`, `*.cftunnel.com` / `*.cfargotunnel.com`, `api.github.com`, `github.com`, `huggingface.co`, `*.neon.tech`, `nominatim.openstreetmap.org`, `overpass-api.de`, `router.project-osrm.org`, `registry.ollama.ai` / `ollama.com`.

### CGNAT and “I have no public IP”

Many home fiber/mobile ISPs put you behind **CGNAT** (`100.64.0.0/10`). Test:

```bash
# On the Mini
curl -4 -s https://ifconfig.me && echo
# Compare to the WAN IPv4 shown in the router status page.
# If they differ, or WAN is 100.64.x.x, you are on CGNAT.
```

**CGNAT is OK.** Cloudflare Tunnel still works (it dials out). Port forwarding would not. Do not buy a “static IP” just for this project unless you want inbound SSH from the internet (you should not).

### Hairpin NAT

Testing `https://api.<domain>` **from a laptop on the same Wi-Fi as the Mini** can fail or look fine while the rest of the world fails. **Always prove the API from a phone on cellular**, not on the house Wi-Fi.

### Guest Wi-Fi

Do not put the Mini on **guest / AP isolation** Wi-Fi. The laptop would not reach Screen Sharing, and some guest networks block outbound UDP (tunnel).

### ISP quality

- First week downloads: **~20–80 GB** (9B + embed + later FLUX ~7–34 GB first run + optional 20B). On this Mini that is Wi-Fi; overnight pulls are fine. Disk headroom is not the issue (443 GB free).
- Watch **data caps**.
- Unstable Wi-Fi + QUIC = random 502s. If tunnel flaps, set `protocol: http2` in `~/.cloudflared/config.yml` (see host-setup.md).

---

## 4. Accounts that must exist (create from any laptop, store in a password manager)

Do **not** put passwords in git.

| Account | Used for | When |
| --- | --- | --- |
| GitHub (`AshrafRezk/cldM4`) | Clone the plan / later code | Day 0 |
| Cursor **Pro Plus** | Agent on the Mini | Day 0 |
| Apple ID | Mini, FileVault recovery | Day 0 |
| [Cloudflare](https://dash.cloudflare.com) | Domain, Tunnel, WAF, Access | Before Phase B |
| A domain whose **nameservers are Cloudflare** (zone **Active**) | `api.` and `app.` | Before Phase B |
| [Neon](https://neon.tech) Postgres | Keys + usage | Before Phase B |
| [Netlify](https://www.netlify.com) | Dashboard only | Phase C |
| Hugging Face | Optional; FLUX schnell is Apache | Phase E |
| Slack (or similar) incoming webhook | Mini down alerts | Before production |
| Google Maps key | Optional `tools.google_places` | Only if scoped |

Fill the actual IDs into [operator-checklist.md](operator-checklist.md) §§1–5. Phase B cannot pass with those blank.

---

## 5. Day-0 sequence (do in order)

Print this. Tick as you go.

1. [x] Physical: power + display + **keyboard in the room**. Ethernet **n/a** (Wi-Fi-only, §3a). **No UPS** (operator will not buy one).
2. [x] macOS setup: hostname `cloudiator.local`, users `Cloudiator` + `Ashraf` (both Admin). Software Update: freeze casual updates during Phase A–B.
3. [x] Energy: prevent sleep when display off, wake for network, start up after power failure. Automatic time on (Apple `time.apple.com`).
4. [x] Automatic login as `Cloudiator`. [x] FileVault **Off** = policy **C** (cannot enable FileVault while auto-login is on).
5. [x] Disk: **443 GB free** of 494 GB (About This Mac → Storage, 2026-09-19). Comfortable for full v1.
6. [x] `uname -m` → `arm64` (`ashrafrezk@cloudiator`, 2026-09-19). Terminal is not Rosetta.
7. [x] Wi-Fi-only: SSID **Ash & Mimi**, `192.168.100.51`, MAC `d0:11:e5:94:6b:23`, proxies off. [x] DHCP Static IP on WE HG8145V5. [x] Forward Rules empty (no IPv4 port mapping, port trigger, IP mapping, or DMZ).
8. [x] Screen Sharing **LAN only** at `vnc://192.168.100.51/` / “Ashraf's Mac mini”, Administrators only, VNC-password viewers off.
9. [ ] Internet: `curl -I https://github.com` and `curl -I https://ollama.com` return success.
10. [ ] Note public IPv4 (`curl -4 -s https://ifconfig.me`) vs router WAN (CGNAT or not).
11. [ ] Create/login Cloudflare, Neon, GitHub. Domain zone **Active**.
12. [ ] Clone:

    ```bash
    cd ~
    git clone https://github.com/AshrafRezk/cldM4.git
    cd cldM4
    git log -1 --oneline    # expect 9bf4d91 or newer on main
    ```

13. [ ] Install **Cursor**, open **this folder**, Pro Plus, [cursor-settings.md](cursor-settings.md) (Privacy Mode, Auto off, Opus 5).
14. [ ] Continue [host-setup.md](host-setup.md) §0 (Rosetta gate) then Homebrew / Ollama **.app** (not brew ollama).
15. [ ] Phase A in a new Agent chat. Do not skip to tunnel until loopback chat works.

---

## 6. Prove the network (copy-paste)

Run on the Mini (Wi-Fi-only is fine):

```bash
uname -m
df -h /
networksetup -getinfo Wi-Fi
curl -4 -sS https://ifconfig.me; echo
curl -sS -o /dev/null -w "%{http_code}\n" https://github.com
curl -sS -o /dev/null -w "%{http_code}\n" https://ollama.com
ping -c 3 1.1.1.1
```

After Phase B (tunnel live), run **on a phone using cellular**:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://api.YOURDOMAIN/v1/health
# 200 JSON. If you get HTML or 403, Bot Fight Mode or Access is eating Apex. See host-setup.md §9.
```

From the **laptop on LAN** (not a substitute for the phone test):

```bash
curl -sS http://127.0.0.1:8080/v1/health     # only works ON the Mini
ssh user@MINI_LAN_IP 'curl -s http://127.0.0.1:8080/v1/health'
```

Confirm **closed** from WAN (should time out). Use a phone cellular `nc` or a port-scan site against the Mini’s public IP for ports 22, 8080, 11434 — all closed. If 11434 is open, you are already in incident mode: close the router rule, `grep 11434 ~/.cloudflared/config.yml` must be 0, rotate every `sk-cld-` key.

---

## 7. Internet-related failure modes

| What you see | Likely cause | What to do |
| --- | --- | --- |
| Tunnel connected, `api.` NXDOMAIN | Cloudflare zone not **Active**, or CNAME missing | Checklist §1–2 |
| 522 / 502 from Cloudflare | Mini asleep, worker down, or `cloudflared` not running | Energy settings; `launchctl print`; host-setup health ping |
| Tunnel flaps every few minutes | UDP/QUIC blocked; Wi-Fi | Ethernet; `protocol: http2` in cloudflared config |
| Works on house Wi-Fi, fails on LTE | Hairpin NAT or split DNS | Always test on cellular |
| Apex 403 with HTML body | Bot Fight / challenge on `api.` | host-setup §9; skip rule on `Bearer sk-cld-` |
| Slow `ollama pull` then disk full | Wi-Fi + 256 GB disk | Ethernet; `df -h`; skip 20B/FLUX until 120 GB free |
| Nominatim 403 | Bad User-Agent or >1 rps from home IP | Checklist §5; process-wide 1 rps |
| Neon connect timeout | ISP blocking 5432 | Use Neon **pooled** URL + SSL; some networks need the Neon serverless/pooler host |
| Hugging Face 401 on FLUX | Gated model | Schnell is Apache; you likely hit the wrong repo. See PLAN.md §7 |
| SSH from café to Mini fails | **Good.** Nothing is forwarded | Use Screen Sharing on LAN or a separate admin tunnel you designed, not port 22 WAN |

---

## 8. Security physical

- Mini is an always-on CRM-adjacent appliance. Lock the room if you can.
- FileVault recovery key + Apple ID + Cloudflare + GitHub + Neon all in a password manager, not a sticky note on the Mini.
- Anyone with Screen Sharing on the LAN can see prompts if `log_prompts` were ever true (default false for Salesforce keys).
- Theft: FileVault (policy A/B) + Find My. Rotate all `sk-cld-` keys if the disk leaves the building unlocked (policy C).

---

## 9. Sign-off before cloning is not enough

Hardware/network is green when:

- [x] 24 GB M4 Mini, arm64, ≥ 120 GB free (443 GB)
- [x] Wi-Fi-only exception accepted (§3a). SSID Ash & Mimi, MAC `d0:11:e5:94:6b:23`, IP `192.168.100.51`. [x] DHCP Static IP on HG8145V5
- [x] No WAN port forwards for 22/8080/11434 (Forward Rules / IPv4 Port Mapping / Port Trigger / DMZ all empty, 2026-09-19)
- [ ] No WAN port forwards for 22/8080/11434 (Screen Sharing is LAN-only already)
- [ ] Phone-on-cellular test of `api.` is possible after Phase B (you already own the domain)
- [x] No UPS (accepted). [x] Automatic login for `Cloudiator`. [x] FileVault policy **C** (Off)
- [ ] Cursor Pro Plus on this machine, repo cloned, next file is host-setup.md

Operator: ____________________  Date: ____________
