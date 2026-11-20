"""Claim and run jobs from the jobs table."""

import time

from django.core.management.base import BaseCommand

from catalog import jobs


class Command(BaseCommand):
    help = "Claim and run jobs from the jobs table."

    def add_arguments(self, parser):
        parser.add_argument("--id", default="worker")
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--sleep", type=float, default=1.0)

    def handle(self, *args, **options):
        worker = options["id"]
        while True:
            job = jobs.claim(worker)
            if job is None:
                if options["once"]:
                    self.stdout.write("no jobs")
                    return
                time.sleep(options["sleep"])
                continue
            self.stdout.write("claimed #%s %s" % (job.id, job.job_type))
            try:
                jobs.run_job(job)
            except Exception as exc:
                self.stderr.write("failed #%s: %s" % (job.id, exc))
                jobs.fail(job, exc)
            else:
                jobs.complete(job)
                self.stdout.write("done #%s" % job.id)
