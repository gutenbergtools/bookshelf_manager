from django.conf import settings


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


def is_cataloger(user):
    return _listed(user, "CATALOG_CATALOGERS", "BSM_CATALOGERS", "CATALOG_REVIEWERS", "BSM_REVIEWERS")


def can_use_app(user):
    return is_cataloger(user)


def can_use_op(user, op):
    return can_use_app(user)
