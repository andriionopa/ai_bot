# Telegram AI Combine

Stage 1 implementation based on [plan.md](./plan.md) and aligned with the Django-first architecture derived from [proj.md](./proj.md).

## Implemented in Stage 1

- Django 5.2 project with DRF, Channels, Celery, Redis-ready config
- Custom `User` model with Telegram and Google auth identifiers
- Telegram Login Widget signature verification endpoint
- Google OAuth login URL + callback flow skeleton
- Internal JWT issuance with Simple JWT
- Proxy CRUD API and Telegram account model scaffold
- Proxy ping task with latency tracking
- WebSocket log stream at `ws/logs/`
- Redis pub/sub to Channels bridge via `run_log_bridge`
- Dedicated auth page at `/auth/`
- Protected dashboard at `/dashboard/` and `/webapp/`
- Farm management inside the dashboard: attach `.session`, credentials auth, 2FA completion, bulk detach, proxy add
- Docker Compose for local network deployment

## Local Run

1. Copy `.env.example` to `.env`
   Add real values for `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, and `TELEGRAM_BOT_USERNAME` if you want SSO on `/auth/`.
2. Create the Python 3.12 virtualenv if needed:

```bash
python3.12 -m venv .venv312
.venv312/bin/pip install -r requirements.txt
```

3. Run migrations:

```bash
.venv312/bin/python manage.py migrate
```

4. Create a local user for session login:

```bash
.venv312/bin/python manage.py shell -c "from django.contrib.auth import get_user_model; get_user_model().objects.create_user(email='owner@example.com', password='change-me-now')"
```

5. Start Django:

```bash
.venv312/bin/python manage.py runserver 0.0.0.0:8000
```

6. In another terminal, start Celery and log bridge:

```bash
.venv312/bin/celery -A config worker -l info
.venv312/bin/python manage.py run_log_bridge
```

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

## Main Web Routes

- `/auth/`
- `/dashboard/`
- `/webapp/`

## Main API Endpoints

- `POST /api/v1/auth/telegram/`
- `GET /api/v1/auth/google/login/`
- `GET /api/v1/auth/google/callback/`
- `GET /api/v1/auth/me/`
- `POST /api/v1/auth/token/refresh/`
- `GET /api/v1/accounts/overview/`
- `POST /api/v1/accounts/add/`
- `POST /api/v1/accounts/detach/`
- `POST /api/v1/accounts/{id}/complete-auth/`
- `GET /api/v1/accounts/{id}/health/`
- `POST /api/v1/accounts/{id}/runtime-events/`
- `POST /api/v1/accounts/proxies/add/`
- `GET /api/v1/accounts/proxies/{id}/test/`
- `GET|POST /api/v1/accounts/proxies/`
- `POST /api/v1/accounts/proxies/{id}/ping/`
- `WS /ws/logs/`

## Notes

- The Google OAuth callback is implemented, but it needs valid Google credentials in `.env`.
- The proxy checker currently validates transport reachability and latency. Full MTProto session-aware checks belong to the next runtime iteration when session upload and worker orchestration are added.
