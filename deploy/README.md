# Deploying SpendLatch to a public domain

This directory contains everything needed to run the public demo on a
single Linux VPS. The live deployment is
`https://spendlatch.owain32380.cn`.

- `spendlatch-web.service` — the FastAPI app (`python -m agent.backend`),
  which serves the web UI, the static assets, and the chat API.
- `spendlatch-mcp.service` — the self-hosted MCP server
  (`python -m mcp_server.server`, Streamable HTTP).
- `nginx-spendlatch.conf` — an nginx TLS+proxy variant, kept for
  deployments that do not use Caddy (see below).

Both processes bind to loopback only; the reverse proxy is the only
public face. No credentials exist anywhere in the stack: every provider
is a simulated adapter and all data is synthetic.

## Ports

- The web app defaults to `8200`, but the production host runs it on
  **8201** (`SPENDLATCH_WEB_PORT=8201`) because another service already
  occupies 8200 there.
- The MCP server listens on **8101** (`/mcp`, Streamable HTTP) in every
  environment. Keep the trailing-slash-less path: the endpoint is
  `/mcp`, not `/mcp/`.

## 1. Server prerequisites

Ubuntu/TencentOS with Python >= 3.11:

```bash
sudo useradd --system --home /opt/spendlatch --shell /usr/sbin/nologin spendlatch
sudo mkdir -p /opt/spendlatch
# Get the code onto the box (see section 4 for the two channels), then:
cd /opt/spendlatch
sudo python3 -m venv .venv
sudo .venv/bin/pip install -i https://mirrors.cloud.tencent.com/pypi/simple .
sudo mkdir -p data && sudo chown -R spendlatch:spendlatch /opt/spendlatch
```

Note: generic `pypi.org` and `github.com` were unreachable/slow from
this VPS; the Tencent Cloud mirror worked. The Tsinghua mirror returns
HTTP 403 to this host.

## 2. systemd services

```bash
sudo cp deploy/spendlatch-web.service deploy/spendlatch-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now spendlatch-web spendlatch-mcp
systemctl status spendlatch-web spendlatch-mcp --no-pager
```

Smoke-check from the box itself:

```bash
curl -fsS http://127.0.0.1:8201/api/health      # {"status":"ok"}
curl -fsS http://127.0.0.1:8201/ | head -5      # web UI
```

## 3. Reverse proxy and TLS (Caddy, as deployed)

This VPS serves 80/443 with **Caddy**, which handles certificate
issuance and renewal automatically. The Caddyfile block:

```caddyfile
spendlatch.owain32380.cn {
	import security_headers
	import csp_inline
	handle /mcp* {
		reverse_proxy 127.0.0.1:8101 {
			flush_interval -1
		}
	}
	handle {
		reverse_proxy 127.0.0.1:8201
	}
}
```

Apply it (the Caddyfile has `admin off`, so `reload` cannot push config
and a **restart** is required — a sub-second blip for other sites):

```bash
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date +%F)
# ... append the block ...
caddy validate --config /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

`nginx-spendlatch.conf` in this directory is the equivalent nginx
configuration (with certbot for certificates) if you do not run Caddy.

## 4. Getting code onto the box

- Preferred: `git clone` / `git pull` from GitHub.
- This VPS currently cannot reach `github.com` directly, so the actual
  channel is a byte-identical export of the pushed commit:

```bash
git archive HEAD | ssh <host> "tar -x -C /opt/spendlatch"
```

Then reinstall if dependencies changed and restart both services.

## 5. DNS

Add an A record for the subdomain pointing at the VPS public IP, and
wait for it to resolve before requesting certificates.

## 6. Public smoke checks

```bash
curl -fsS https://spendlatch.owain32380.cn/api/health   # {"status":"ok"}
curl -fsS -o /dev/null -w '%{http_code}\n' https://spendlatch.owain32380.cn/
curl -sS -X POST https://spendlatch.owain32380.cn/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'
# expect 200, text/event-stream, protocolVersion 2025-11-25
```

## 7. Operational notes (honest boundaries)

- **Shared demo state** — one shared instance; every visitor sees the
  same synthetic ledger (`data/state.json`). A daily
  `systemctl restart spendlatch-web spendlatch-mcp` resets the story.
- **No auth by design** — there is nothing to steal: simulated adapters,
  synthetic data, no outbound calls to real providers.
- **DNS-rebinding protection stays ON** — the MCP server keeps the
  SDK's transport security enabled with an explicit allowlist
  (the demo domain plus loopback) in `mcp_server/server.py`.
