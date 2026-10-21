# Deployment

Three pieces, three homes:

| Piece | Where | Why |
| --- | --- | --- |
| Portfolio (`frontend/`) | **Vercel** (free) | Static HTML/CSS/JS - Vercel's core strength |
| Scanner API + Admin console (`backend/`) | **Render / Railway / Fly.io** (paid) | torch + easyocr need ~2 GB RAM and a disk; Vercel's 250 MB Lambda limit cannot hold them |

The portfolio and the API are one repo, deployed independently, wired together
with environment variables.

---

## 1. Portfolio -> Vercel

```bash
npx vercel login
npx vercel --prod
```

`vercel.json` runs `node scripts/build-portfolio.mjs`, which copies `frontend/`
into `dist/` and rewrites the local URLs to the hosted ones. Configure these
project environment variables in Vercel (Settings -> Environment Variables):

| Variable | Example |
| --- | --- |
| `SCANNER_URL` | `https://complianceai-api.onrender.com` |
| `SCANNER_API` | `https://complianceai-api.onrender.com` |
| `ADMIN_URL` | `https://complianceai-api.onrender.com/admin` |
| `SITE_URL` | `https://your-site.vercel.app` |

Without them the site still deploys, but the buttons point at `localhost`.

---

## 2. API -> Render (or any Docker host)

### One click

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/afzzzal028/complianceai)

Type one admin password, Render builds the image and starts the service. The
public URL is `https://complianceai-api.onrender.com`.

### Manual

The repo contains `render.yaml`, so Render can deploy it as a blueprint:
**New -> Blueprint -> select the repo -> fill in the prompted values.**

| Variable | Required | Notes |
| --- | --- | --- |
| `ADMIN_PASSWORD` | yes | Strong password for `/admin` |
| `SECRET_KEY` | auto | `generateValue: true` - keeps sessions alive across restarts |
| `CORS_ORIGINS` | yes | The portfolio origin, e.g. `https://your-site.vercel.app` |
| `PUBLIC_API_URL` | yes | Public URL of the API |
| `PUBLIC_ADMIN_URL` | yes | Same URL + `/admin` |
| `PORTFOLIO_URL` | yes | The Vercel URL |
| `DB_PATH` | auto | `/data/compliance.db` on the persistent disk |
| `TRUST_PROXY` | auto | On behind Render/Railway/nginx, so rate limiting sees the real client IP |

Railway / Fly.io equivalent: build from `backend/Dockerfile` (context = repo
root), expose port `5000`, mount a volume at `/data`, and set the same
environment variables.

### Routes served by the container

| Path | Serves |
| --- | --- |
| `/` | Scanner UI |
| `/api/*` | Scanner API |
| `/admin` | Admin console |
| `/api/admin/*` | Admin API |

`backend/wsgi.py` splits the traffic between the two Flask apps in one process,
so there is a single port, a single SQLite file and no cross-process locking.

### First boot

`database.init_db()` runs on import and seeds the 12 legal rules and the
20-product reference catalog, so a fresh volume is immediately usable.
The database file itself is git-ignored and never committed.

---

## 3. Local development

```bash
python run.py          # scanner :5000, admin :5001, portfolio :5500
```

`run.py` is the local equivalent of the container: three processes, tagged
output, one Ctrl+C to stop everything.

---

## Security notes

- The scan endpoint is public on purpose (it is the demo) and already rate
  limited to 60 requests/minute per IP.
- The admin console requires `ADMIN_PASSWORD`; eight failed logins from one IP
  trigger a five minute lockout. The default `admin123` is refused in
  production (`config.py` raises if `SECRET_KEY` is missing in production).
- `CORS_ORIGINS` should list only the portfolio domain. It defaults to `*` for
  local development.
- `cert.pem` / `key.pem` and `compliance.db` are git-ignored.
