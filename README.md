# Telegram Ops Console

Telegram Ops Console is a Django and Next.js control panel for managing Telegram account operations, parsing public Telegram data, scheduling warmup activity, running reactions, generating account profiles, and evaluating account quality with AI-assisted scoring.

The backend exposes a REST API, WebSocket log streaming, Celery workers, Redis-backed realtime delivery, and PostgreSQL-ready persistence. The frontend is a Next.js application that provides the operational dashboard.

## Features

- Authentication with session login, JWT refresh tokens, Telegram Login Widget verification, and Google OAuth hooks.
- Telegram account management with session upload, credential-based login, two-factor completion, proxy assignment, detach flows, health tracking, and runtime event handling.
- Proxy CRUD and latency checks.
- Profile generation with separate text and image provider configuration.
- Warmup policies, scheduled actions, account health recalculation, quarantine release, and realtime logs.
- Channel, message, and comment parser modules with saved templates, history views, and result management.
- Mass reactions with account rotation, source normalization, smart emoji support, and history cleanup.
- Neuro-commenting jobs with prompt management, blacklist handling, account rotation, Telegram folder-link support, and protection modes.
- GGR account quality analysis with live Telegram account signals, device consistency checks, SpamBot status checks, historical ratings, and frontend score breakdowns.
- Realtime log bridge over Django Channels and Redis pub/sub.

## Architecture

- Backend: Django 5.2, Django REST Framework, Channels, Celery, Simple JWT, Pyrogram.
- Frontend: Next.js 16 and React 19.
- Runtime services: PostgreSQL, Redis, Celery worker, Django ASGI/WSGI app, realtime log bridge.
- Test stack: pytest with `config.settings.test`.

Important directories:

- `apps/` contains Django domain apps.
- `config/` contains Django, Celery, ASGI, URL, and middleware configuration.
- `frontend/` contains the Next.js dashboard.
- `workers/telegram_runtime/` contains Telegram runtime client utilities.
- `tests/` contains backend regression tests.

## Requirements

- Python 3.12
- Node.js 20 or newer
- PostgreSQL 16 for production-like deployments
- Redis 7
- Telegram API credentials from `my.telegram.org`
- Docker and Docker Compose for containerized local runs

SQLite can be used for quick local backend checks, but PostgreSQL is the expected database for integrated development and production-like environments.

## Configuration

Create a `.env` file in the repository root. The settings loader reads it automatically before Django starts.

Core backend variables:

| Variable | Required | Description |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | Production | Django signing key. Required when `DJANGO_DEBUG=False`. |
| `DJANGO_DEBUG` | Production | Set to `False` in production. |
| `DJANGO_ALLOWED_HOSTS` | Production | Comma-separated hostnames allowed by Django. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Production | Comma-separated trusted origins including scheme. |
| `DJANGO_CORS_ALLOWED_ORIGINS` | Production | Comma-separated frontend origins allowed to call the API. |
| `DATABASE_URL` | Recommended | `postgresql://user:password@host:5432/database` or `sqlite:////absolute/path/db.sqlite3`. |
| `REDIS_URL` | Yes | Redis database used by app-level runtime helpers. |
| `CHANNEL_REDIS_URL` | Yes | Redis database used by Django Channels. |
| `CELERY_BROKER_URL` | Yes | Celery broker URL. |
| `CELERY_RESULT_BACKEND` | Yes | Celery result backend URL. |
| `BACKEND_URL` | Yes | Public backend base URL. |
| `FRONTEND_URL` | Yes | Public frontend base URL. |

Telegram and auth variables:

| Variable | Required | Description |
| --- | --- | --- |
| `TELEGRAM_API_ID` | Yes | Telegram API ID for Pyrogram sessions. |
| `TELEGRAM_API_HASH` | Yes | Telegram API hash for Pyrogram sessions. |
| `TELEGRAM_BOT_TOKEN` | Optional | Bot token used by Telegram auth flows when enabled. |
| `TELEGRAM_BOT_USERNAME` | Optional | Bot username for Telegram Login Widget integration. |
| `GOOGLE_OAUTH_CLIENT_ID` | Optional | Google OAuth client ID. |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Optional | Google OAuth client secret. |
| `GOOGLE_OAUTH_REDIRECT_URI` | Optional | Google OAuth callback URL. |

AI provider variables:

| Variable | Required | Description |
| --- | --- | --- |
| `PROFILE_TEXT_BASE_URL` | Optional | OpenAI-compatible text provider base URL. |
| `PROFILE_TEXT_API_KEY` | Optional | API key for profile text generation. |
| `PROFILE_TEXT_MODEL` | Optional | Text model name, default `gpt-4o-mini`. |
| `PROFILE_IMAGE_BASE_URL` | Optional | Image provider base URL. |
| `PROFILE_IMAGE_API_KEY` | Optional | API key for profile image generation. |
| `PROFILE_IMAGE_MODEL` | Optional | Image model name, default `dall-e-3`. |
| `PROFILE_IMAGE_SIZE` | Optional | Generated image size, default `1024x1024`. |

Operational limits:

| Variable | Default | Description |
| --- | --- | --- |
| `PROFILE_PROVIDER_TIMEOUT_SECONDS` | `60` | Timeout for external profile providers. |
| `PROFILE_IMAGE_UPLOAD_MAX_BYTES` | `8388608` | Maximum uploaded profile image size. |
| `TELEGRAM_SESSION_UPLOAD_MAX_BYTES` | `20971520` | Maximum uploaded Telegram session size. |
| `RUNTIME_METADATA_MAX_BYTES` | `4096` | Maximum metadata payload size for runtime events. |
| `REALTIME_LOG_MESSAGE_MAX_LENGTH` | `1000` | Maximum realtime log message length. |

## Local Development

Install backend dependencies:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Install frontend dependencies:

```bash
cd frontend
npm install
```

Run database migrations:

```bash
python manage.py migrate
```

Create a local user:

```bash
python manage.py shell -c "from django.contrib.auth import get_user_model; get_user_model().objects.create_user(email='owner@example.com', password='change-me-now')"
```

Start the backend:

```bash
python manage.py runserver 0.0.0.0:8000
```

Start Celery and the realtime bridge in separate terminals:

```bash
celery -A config worker -l info
python manage.py run_log_bridge
```

Start the frontend:

```bash
cd frontend
npm run dev
```

Default local URLs:

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:3001`
- Auth page: `http://127.0.0.1:3001/auth`
- Dashboard: `http://127.0.0.1:3001/dashboard`

## Docker Compose

Docker Compose starts Django, Celery, the realtime bridge, PostgreSQL, and Redis:

```bash
docker compose up --build
```

The compose file does not start the Next.js frontend. Run it separately from `frontend/`:

```bash
npm install
npm run dev
```

## Production Deployment

Use PostgreSQL and Redis as managed or separately supervised services. Run the Django app with an ASGI server so HTTP and WebSocket traffic are served by the same application entrypoint:

```bash
daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

Run Celery workers:

```bash
celery -A config worker -l info
```

Run Celery Beat if scheduled health, quarantine, and warmup tasks should execute automatically:

```bash
celery -A config beat -l info
```

Run the realtime log bridge:

```bash
python manage.py run_log_bridge
```

Build and run the frontend:

```bash
cd frontend
npm run build
npm run start
```

Before exposing the service publicly:

- Set `DJANGO_DEBUG=False`.
- Set a long random `DJANGO_SECRET_KEY`.
- Configure `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, and `DJANGO_CORS_ALLOWED_ORIGINS`.
- Use HTTPS at the reverse proxy.
- Keep `.env`, Telegram sessions, database backups, and provider API keys out of git.
- Run `python manage.py collectstatic` if serving Django static files outside the development server.

## API Surface

Main REST route groups:

- `api/v1/auth/`
- `api/v1/accounts/`
- `api/v1/profiles/`
- `api/v1/warmup/`
- `api/v1/parser/channels/`
- `api/v1/parser/messages/`
- `api/v1/parser/comments/`
- `api/v1/reactions/`
- `api/v1/neuro-commenting/`
- `api/v1/realtime/`
- `api/v1/auth/token/refresh/`

WebSocket route group:

- `ws/logs/`

Main frontend routes:

- `/auth`
- `/dashboard`
- `/dashboard/accounts`
- `/dashboard/warmup`
- `/parser/channels`
- `/parser/messages`
- `/parser/comments`
- `/parser/history`
- `/reactions`
- `/neuro-commenting`
- `/ggr`

## Testing

Run backend tests:

```bash
pytest
```

Run frontend production build checks:

```bash
cd frontend
npm run build
```

## Repository Hygiene

Do not commit `.env`, uploaded Telegram session files, generated media, local SQLite databases, or provider credentials. Rotate any credential immediately if it was ever committed or shared outside the deployment environment.
