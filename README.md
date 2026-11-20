# Catalog Manager

Catalog Manager is the web UI for cataloging Project Gutenberg books: the record itself, plus authors, subjects, categories, languages, LoC classes and MARC fields. It replaces the PHP `/catalog/admin/` that used to run on the public site.

One codebase serves two deployments, kept apart by `CATALOG_APP` (legacy alias: `BSM_APP`):

| Mode | `CATALOG_APP` | Who signs in | What they get |
|------|---------------|--------------|----------------|
| **Catalog** | `catalog` | Catalogers | Books, authors, subjects, categories, languages, LoC classes, reports; Django admin for jobs (read-only), mirrors, and robot blocks |
| **Shelves** | `shelves` | Volunteers | Bookshelves only (`/shelves/`, `/shelf/<id>/`); catalog URLs 404 |

Each mode runs as its own process on its own hostname, for example `catalog.example.org` on `:8000` and `shelves.example.org` on `:8001`. Cookie names are per mode (`catalog_cat*` on the catalog host, `catalog_shelf*` on the shelves host), so a session from one host cannot be replayed on the other.

Edits go through propose/apply with validated values. AutoRebuild still reads the Postgres `public.changelog` SQL for author/title rebuilds; that changelog is not exposed in Django admin (kept out on purpose — too much UI for little gain). Cross-host triggers use the `jobs` table instead; a read-only Jobs view in admin is enough to watch pending/failed work.

Do **not** leave the old PHP `/catalog/admin/` on the public site after cutover.

**Languages** and **LoC Classes** are first-class catalog entities, as in the original PHP catalog admin: they live under `/languages/` and `/loccs/`, and appear as link dropdowns on the book page.

**Mirrors** and **robot blocks** are not part of the day-to-day catalog UI. They live in the Django admin next to jobs, gated by `CATALOG_INFRA_ADMINS` (falls back to catalogers if unset).

## Security

Accounts are Django auth: PBKDF2 hashing, a 10-character minimum, and an in-app password change page. Valid credentials are not enough on their own; the account must also be on the host's allowlist (`CATALOG_CATALOGERS`, or `CATALOG_SHELF_USERS` on the shelves host) to sign in at all. In `DEBUG=1` a superuser bypasses the allowlists, so never point a DEBUG build at anything shared.

The two deployments stay isolated: separate processes and hostnames, per-mode cookies, and the other surface 404s, so a session leaked from one host is useless on the other.

Traffic is throttled: login by real client IP (`CATALOG_TRUSTED_PROXIES` unwraps the proxy so the limit hits the visitor, not the proxy), every changing POST by user (`CATALOG_RATE_LOGIN`, `CATALOG_RATE_POST`), and `/api/jobs/` by API token (`CATALOG_RATE_JOBS`). All forms carry CSRF tokens, the post-save redirect target is validated against the host, and POST bodies are capped at 1 MB.

Browser and transport hardening: with `DJANGO_SECURE_COOKIES=1`, Secure cookies, an HTTPS redirect and a year of HSTS. Always: HttpOnly, SameSite=Lax session and CSRF cookies, a 12-hour session age (`DJANGO_SESSION_AGE`), CSP (`default-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`), a Permissions-Policy that turns off camera, microphone and geolocation, `X-Frame-Options: DENY`, nosniff, same-origin referrer and opener policy. `DEBUG=0` refuses to start with the development secret key; hosts and origins are pinned per env file. robots.txt plus `noindex` keep it out of search engines.

Integrity: edits apply only after server-side validation. Jobs admin is read-only; mirrors and robot blocks need `CATALOG_INFRA_ADMINS` (else catalogers).

## Run locally

Python 3.12; Postgres catalog via `PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER` (same as the other Gutenberg tools).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
CATALOG_APP=catalog CATALOG_CATALOGERS=you@example.org .venv/bin/python manage.py runserver 127.0.0.1:8000
# separate shell / host:
CATALOG_APP=shelves CATALOG_SHELF_USERS=you@example.org .venv/bin/python manage.py runserver 127.0.0.1:8001
```

In `DEBUG=1`, a superuser can sign in without being on the allowlists; set the account email to match `CATALOG_CATALOGERS` or `CATALOG_SHELF_USERS` for production. Copy `catalog/settings/local_settings.example.py` to `local_settings.py` to override Django settings.

## systemd

Two units for isolation:

- `catalog_manager.service` — catalog (`CATALOG_APP=catalog`, bind `:8000`, env `.env`)
- `catalog_manager_shelves.service` — shelves (`CATALOG_APP=shelves`, bind `:8001`, env `.env.shelves`)

```bash
sudo cp catalog_manager.service catalog_manager_shelves.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now catalog_manager catalog_manager_shelves
```

Point the reverse proxy: catalog vhost → `127.0.0.1:8000`, shelves vhost → `127.0.0.1:8001`. Set `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS` per env file to that hostname only.
