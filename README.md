# Catalog Manager

Web UI for cataloging Project Gutenberg books: the record, authors, subjects, categories, languages, LoC classes and MARC fields. Edits are validated server-side, then applied to Postgres; each apply also writes a `public.changelog` row for AutoRebuild.

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
CATALOG_CATALOGERS=you@example.org .venv/bin/python manage.py runserver 127.0.0.1:8000
```

Postgres via `PGHOST`/`PGDATABASE`/`PGUSER`. In `DEBUG=1` a superuser can sign in without being on the allowlist; set `CATALOG_CATALOGERS` for production. Reverse proxy → `127.0.0.1:8000`, with `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS` pinned to the hostname.
