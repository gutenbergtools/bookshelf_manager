"""Postgres-backed job queue for cross-host triggers.

PGLAF (or a git hook) POSTs a job; the worker on ibiblio claims rows with
SELECT ... FOR UPDATE SKIP LOCKED, runs them, and marks done/failed.
"""

import secrets
import time
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Job

JOB_TYPES = ("git_pull", "workflow_ingest", "rebuild")


def token_ok(request):
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else request.headers.get("X-Api-Token", "")
    expected = getattr(settings, "JOBS_API_TOKEN", "")
    return bool(expected) and secrets.compare_digest(token or "", expected)


def enqueue(job_type, payload=None, key=None):
    key = (key or "").strip() or uuid.uuid4().hex
    return Job.objects.get_or_create(
        idempotency_key=key,
        defaults={"job_type": job_type, "payload": payload or {}},
    )


def claim(worker):
    with transaction.atomic(using="gutenberg"):
        job = (
            Job.objects.using("gutenberg")
            .select_for_update(skip_locked=True)
            .filter(status=Job.PENDING)
            .order_by("created_at", "id")
            .first()
        )
        if job is None:
            return None
        job.status = Job.CLAIMED
        job.claimed_at = timezone.now()
        job.claimed_by = worker
        job.attempts += 1
        job.save(using="gutenberg")
        return job


def complete(job, note=""):
    job.status = Job.DONE
    job.error = note[:2000]
    job.save(using="gutenberg")


def fail(job, error):
    job.status = Job.FAILED
    job.error = str(error)[:2000]
    job.save(using="gutenberg")


def run_job(job):
    handler = HANDLERS.get(job.job_type)
    if handler is None:
        raise ValueError("unknown job_type: %s" % job.job_type)
    handler(job.payload)


# Placeholders. Replace these with calls into puller.py / the workflow code.
def _git_pull(payload):
    time.sleep(1)


def _workflow_ingest(payload):
    time.sleep(1)


def _rebuild(payload):
    time.sleep(1)


HANDLERS = {
    "git_pull": _git_pull,
    "workflow_ingest": _workflow_ingest,
    "rebuild": _rebuild,
}
