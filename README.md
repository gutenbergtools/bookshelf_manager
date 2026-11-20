# Catalog Manager

Catalog Manager is the web UI for cataloging Project Gutenberg books: the record itself, plus authors, subjects, categories, languages, LoC classes and MARC fields. It replaces the PHP `/catalog/admin/` that used to run on the public site.

One codebase serves two deployments, kept apart by `CATALOG_APP`:

| Mode | `CATALOG_APP` | Who signs in | What they get |
|------|---------------|--------------|----------------|
| **Catalog** | `catalog` | Catalogers | Books, authors, subjects, categories, languages, LoC classes, reports; Django admin for jobs (read-only), mirrors, and robot blocks |
| **Shelves** | `shelves` | Volunteers | Bookshelves only (`/shelves/`, `/shelf/<id>/`); catalog URLs 404 |

Each mode runs as its own process on its own hostname, for example `catalog.example.org` on `:8000` and `shelves.example.org` on `:8001`. Cookie names are per mode (`catalog_cat*` on the catalog host, `catalog_shelf*` on the shelves host), so a session from one host cannot be replayed on the other.

Catalog edits are validated on the server, then applied immediately to Postgres. Each apply also appends a row to `public.changelog` so AutoRebuild can pick up author/title changes, that table is not shown in Django admin.
Separately, PGLAF can POST to `/api/jobs/` to queue cross-host work (git pull, workflow ingest, rebuild). Those rows live in the `jobs` table; Django admin has a read-only Jobs view so you can see pending/failed items.

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

- `catalog_manager.service` — catalog (`CATALOG_APP=catalog`, bind `:8000`, env `.env`)
- `catalog_manager_shelves.service` — shelves (`CATALOG_APP=shelves`, bind `:8001`, env `.env.shelves`)

```bash
sudo cp catalog_manager.service catalog_manager_shelves.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now catalog_manager catalog_manager_shelves
```

Point the reverse proxy: catalog vhost → `127.0.0.1:8000`, shelves vhost → `127.0.0.1:8001`. Set `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS` per env file to that hostname only.
