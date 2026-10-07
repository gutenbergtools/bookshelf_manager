# Bookshelf Manager

Allows volunteers to propose adds and removals on Project Gutenberg bookshelves.
Once a reviewer accepts a change, the app updates the catalog and logs it;
view with `journalctl -u bookshelf_manager -f` or in the Django admin panel.

## Run locally

Python 3.12. Postgres catalog via `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`
(same as the other Gutenberg tools). The app needs write access to
`mn_books_bookshelves`.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
BSM_REVIEWERS=you@example.org .venv/bin/python manage.py runserver
```

The reviewer account email must match `BSM_REVIEWERS`.

* http://127.0.0.1:8000/
* http://127.0.0.1:8000/review/

## systemd

`bookshelf_manager.service` matches the autocat layout: app under
`/var/lib/bookshelf_manager`, venv next to it, env in `.env`.

```bash
sudo cp bookshelf_manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bookshelf_manager
```
