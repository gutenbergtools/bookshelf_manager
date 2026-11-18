from django.conf import settings
from django.db import models


def _emails(*names):
    return {email.lower() for name in names for email in getattr(settings, name, []) if email}


def actor_name(user):
    return (getattr(user, "email", None) or user.get_username() or "")[:80]


def _listed(user, *names):
    if not getattr(user, "is_authenticated", False):
        return False
    email = (getattr(user, "email", None) or "").lower()
    if email and email in _emails(*names):
        return True
    return bool(settings.DEBUG and getattr(user, "is_superuser", False))


def is_shelf_user(user):
    return _listed(user, "CATALOG_SHELF_USERS", "BSM_SHELF_USERS")


def is_cataloger(user):
    return _listed(user, "CATALOG_CATALOGERS", "BSM_CATALOGERS", "CATALOG_REVIEWERS", "BSM_REVIEWERS")


def can_rollback(user):
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    emails = _emails("CATALOG_ROLLBACKERS", "BSM_ROLLBACKERS")
    return (getattr(user, "email", None) or "").lower() in emails if emails else is_cataloger(user)


def can_manage_infra(user):
    """Mirrors / robot blocks in Django admin (separate from day-to-day cataloging)."""
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    emails = _emails("CATALOG_INFRA_ADMINS", "BSM_INFRA_ADMINS")
    return (getattr(user, "email", None) or "").lower() in emails if emails else is_cataloger(user)


def can_use_app(user):
    return is_shelf_user(user) if settings.CATALOG_APP == "shelves" else is_cataloger(user)


def can_use_op(user, op):
    if not can_use_app(user):
        return False
    return op.domain == "shelves" if settings.CATALOG_APP == "shelves" else True


class Change(models.Model):
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"
    op = models.CharField(max_length=40)
    action = models.CharField(max_length=16)
    target = models.CharField(max_length=240, db_index=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=16, default=APPLIED, db_index=True)
    actor = models.CharField(max_length=80)
    applied_by = models.CharField(max_length=80, blank=True, default="")
    restores_id = models.BigIntegerField(null=True, blank=True)
    rolled_back_by = models.CharField(max_length=80, blank=True, default="")
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]


class AuditEvent(models.Model):
    """Append-only trail: every apply, rollback and reapply, with the data needed to rebuild."""

    APPLY = "apply"
    ROLLBACK = "rollback"
    REAPPLY = "reapply"
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    kind = models.CharField(max_length=16, db_index=True)
    actor = models.CharField(max_length=80)
    change = models.BigIntegerField(null=True, blank=True, db_index=True)
    op = models.CharField(max_length=40)
    action = models.CharField(max_length=16)
    target = models.CharField(max_length=240)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return "%s %s #%s %s" % (self.kind, self.op, self.change, self.actor)


class Mirror(models.Model):
    """Gutenberg public.mirrors — edited only via Django admin (infra priv)."""

    id = models.AutoField(primary_key=True, db_column="pk")
    continent = models.CharField(max_length=80, blank=True, null=True)
    nation = models.CharField(max_length=80, blank=True, null=True)
    location = models.CharField(max_length=80, blank=True, null=True)
    provider = models.CharField(max_length=240)
    url = models.CharField(max_length=240)
    note = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "mirrors"
        ordering = ["provider", "id"]
        verbose_name = "mirror"
        verbose_name_plural = "mirrors"

    def __str__(self):
        return "%s (%s)" % (self.provider, self.id)


class RobotBlock(models.Model):
    """Gutenberg robots.blocks — scalar fields only; array columns stay untouched in SQL."""

    ip = models.CharField("IP / CIDR", primary_key=True, max_length=64)
    host = models.TextField(blank=True, null=True)
    has_info = models.BooleanField(default=False)
    is_blocked = models.BooleanField(default=True)
    is_whitelisted = models.BooleanField(default=False)
    created = models.DateTimeField(null=True, blank=True)
    expires = models.DateTimeField(null=True, blank=True)
    org = models.TextField(blank=True, null=True)
    country = models.TextField(blank=True, null=True)
    note = models.TextField(blank=True, null=True)
    count = models.IntegerField(default=1)
    hits = models.IntegerField(default=0)
    asn = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'robots"."blocks'
        ordering = ["-created"]
        verbose_name = "robot block"
        verbose_name_plural = "robot blocks"

    def __str__(self):
        return str(self.ip)
