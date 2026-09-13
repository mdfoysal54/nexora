# Deploy Nexora without errors

Nexora is a full retail OS (POS, stock, purchase, accounts, কিস্তি, warranty). It ships hardened Django 5.2 settings. Follow this exactly.

## 1. Local (prove it first)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# put a long random DJANGO_SECRET_KEY in .env
python manage.py migrate
python manage.py seed_demo
python manage.py test
python manage.py check --deploy   # with DJANGO_DEBUG=False and a real secret
python manage.py runserver
```

Demo: `alice` / `DemoPass123!`  ·  admin: `admin` / `admin`

## 2. Production (Render / Railway / any Linux host)

Set these environment variables **before** the first request:

| Variable | Production value |
|---|---|
| `DJANGO_DEBUG` | `False` |
| `DJANGO_SECRET_KEY` | 50+ random chars |
| `DJANGO_ALLOWED_HOSTS` | your hostname, e.g. `nexora.example.com` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://nexora.example.com` |
| `DJANGO_SECURE_SSL_REDIRECT` | `True` |
| `DJANGO_COOKIE_SECURE` | `True` |
| `DJANGO_HSTS` | `True` |
| `DJANGO_BEHIND_PROXY` | `True` if TLS terminates at a proxy |

Then:

```bash
pip install -r requirements.txt gunicorn
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py seed_demo --force   # optional demo data
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT
```

Docker: `docker build -t nexora . && docker run -p 8000:8000 -e DJANGO_SECRET_KEY=... nexora`

`render.yaml` is included for one-click Render.

## 3. What will *not* break deploy

- No secrets in git (only `.env.example`)
- WhiteNoise serves static files
- SQLite works out of the box; switch `DATABASES` to PostgreSQL when you are ready
- `python manage.py check --deploy` is clean when the env vars above are set
