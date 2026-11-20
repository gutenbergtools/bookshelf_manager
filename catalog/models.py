from django.conf import settings
from django.db import models


def _emails(*names):
    return {email.lower() for name in names for email in getattr(settings, name, []) if email}


def actor_name(user):
    return (getattr(user, "email", None) or user.get_username() or "")[:80]


def _email(user):
    return (getattr(user, "email", None) or "").lower()


def _listed(user, *names):
    if not getattr(user, "is_authenticated", False):
        return False
    if _email(user) in _emails(*names):
        return True
    return bool(settings.DEBUG and getattr(user, "is_superuser", False))


def is_shelf_user(user):
    return _listed(user, "CATALOG_SHELF_USERS", "BSM_SHELF_USERS")


def is_cataloger(user):
    return _listed(user, "CATALOG_CATALOGERS", "BSM_CATALOGERS", "CATALOG_REVIEWERS", "BSM_REVIEWERS")


def can_manage_infra(user):
    """Mirrors / robot blocks in Django admin (separate from day-to-day cataloging)."""
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    emails = _emails("CATALOG_INFRA_ADMINS", "BSM_INFRA_ADMINS")
    return _email(user) in emails if emails else is_cataloger(user)


def can_use_app(user):
    return is_shelf_user(user) if settings.CATALOG_APP == "shelves" else is_cataloger(user)


def can_use_op(user, op):
    if not can_use_app(user):
        return False
    return op.domain == "shelves" if settings.CATALOG_APP == "shelves" else True


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
