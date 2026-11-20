"""Create the jobs table in the gutenberg Postgres database (idempotent)."""

from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connections

SQL_FILE = Path(__file__).resolve().parents[2] / "sql" / "jobs.sql"


class Command(BaseCommand):
    help = "Create the jobs table in the gutenberg database."

    def handle(self, *args, **options):
        sql = SQL_FILE.read_text()
        with connections["gutenberg"].cursor() as cursor:
            for statement in sql.split(";"):
                if statement.strip():
                    cursor.execute(statement)
        self.stdout.write("jobs table ready")
