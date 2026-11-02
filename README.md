# Senario — backend

REST API for Senario, a clothing webshop: products with per-size stock, cart,
guest and account checkout paid through Viva Wallet, order emails with a PDF
receipt, and staff endpoints that run the shop's content.

- Shop: https://www.snr-project.gr (static frontend, separate repo)
- API: https://snr.arsenidis.dev/api/

## Stack

- Python 3.12, Django 5.2, Django REST Framework, Simple JWT (rotating refresh tokens)
- PostgreSQL 16, Redis 7 (cache, sessions, rate-limit counters)
- Viva Wallet Smart Checkout for payments (OAuth client + webhook)
- Resend via django-anymail for email; ReportLab for PDF receipts; Pillow for image processing
- gunicorn behind nginx, Docker Compose, Let's Encrypt TLS
- GitHub Actions deploy to a DigitalOcean droplet

## Architecture

`docker-compose.yml` runs four services:

| Service | Image | Role |
|---|---|---|
| `db` | postgres:16-alpine | Database (volume `postgres_data`, healthcheck) |
| `redis` | redis:7-alpine | Cache, sessions, throttle counters |
| `web` | built from `Dockerfile` | Django under gunicorn (3 workers), runs as a non-root user |
| `nginx` | nginx:alpine | TLS termination, proxies `/api/` and `/admin/`, serves `/static/` and `/media/` |

Only nginx publishes ports (80/443); Postgres and Redis are reachable only
inside the Compose network. Every service has `restart: unless-stopped`.

Django apps (under `app/`):

| App | Endpoints under | Purpose |
|---|---|---|
| `users` | `/api/auth/` | Register with email verification, JWT login/refresh/logout, profile, password reset and change |
| `products` | `/api/products/` | Catalogue, categories, per-size stock; staff CRUD and ordering |
| `cart` | `/api/cart/` | Account cart and a server-side price quote |
| `payments` | `/api/payments/` | Account and guest checkout, checkout status, Viva webhook |
| `orders` | `/api/orders/` | Order history, guest order lookup, shipping rule, staff order management |
| `moodboard`, `posts`, `content` | `/api/moodboard/`, `/api/posts/`, `/api/content/` | Editable site content and images for staff |

An order is only created once the Viva webhook's transaction has been
re-fetched from Viva and checked (status, order code, amount); stock is
decremented in the same database transaction.

**Deploys:** a push to `main` runs `.github/workflows/deploy.yml`, which SSHes
to the droplet, pulls, builds `web`, runs migrations in a one-off container,
recreates only `web`, and fails the run if the API doesn't answer afterwards.
Changes to nginx, Compose, Postgres or Redis config need a manual recreate on
the server. `scripts/backup.sh` (run daily from cron) dumps the database and
media with 14-day retention.

Scheduled management commands (cron on the server): `delete_old_checkouts`
(hourly), `cleanup_pending_registrations`.

## Running locally

Requires Docker. Create a `.env` file in the repo root (never commit it).
Variables read by `app/senario/settings.py` and `docker-compose.yml`:

Required:
`SECRET_KEY`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`

Optional (have defaults):
`DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `CORS_ALLOWED_ORIGINS`,
`DB_HOST`, `DB_PORT`, `REDIS_URL`,
`BRAND_NAME`, `FRONTEND_URL`, `EMAIL_VERIFICATION_TIMEOUT_DAYS`,
`EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `SUPPORT_EMAIL`, `ORDER_ALERT_EMAIL`, `ADMINS`, `RESEND_API_KEY`,
`BUSINESS_DETAILS`, `VAT_RATE_PERCENT`, `SHIPPING_FEE`, `FREE_SHIPPING_OVER`,
`VIVA_ENV` (defaults to `demo`), `VIVA_CLIENT_ID`, `VIVA_CLIENT_SECRET`, `VIVA_SOURCE_CODE`, `VIVA_WEBHOOK_VERIFICATION_KEY`

With `DEBUG=True`, email goes to the console instead of Resend.

The `nginx` service expects Let's Encrypt certificates for the production
domain, so locally run only `db`, `redis` and `web`:

```sh
docker compose up -d db redis
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser
docker compose run --rm -p 8000:8000 web python manage.py runserver 0.0.0.0:8000
```

The API is then at http://localhost:8000/api/ and the Django admin at
http://localhost:8000/admin/.

## Tests

```sh
docker compose run --rm web python manage.py test
```

184 test methods across all apps (Django `APITestCase`), including
authorization checks, rate-limit checks, payment-webhook verification, refund
and stock edge cases, and a sweep that sends junk input to every endpoint and
asserts it never returns a 500. Viva API calls are mocked. Tests use their own
Postgres test database and Redis database 15, so they never touch real data.
