"""Apply catalog edits immediately; log them in Django/SQLite for rollback."""

import logging

from django.core.exceptions import PermissionDenied
from django.utils import timezone
from sqlalchemy import func

from . import catalog as c
from . import gutenberg as g
from . import ops as registry
from .clean import Bad, jsonable
from .models import AuditEvent, Change, actor_name, can_rollback, can_use_op

log = logging.getLogger(__name__)


def _compat(session, who, sql):
    if not sql:
        return
    session.execute(
        g._models().t_changelog.insert().values(time=func.now(), login=(who or "")[:80], sql=sql[:10000], script="bsm")
    )


def _record(op, action, before, after, who):
    row = Change.objects.create(
        op=op.name,
        action=action,
        target=op.target(after, before),
        before=jsonable(before),
        after=jsonable(after),
        status=Change.APPLIED,
        actor=who,
        applied_by=who,
        processed_at=timezone.now(),
    )
    _audit(AuditEvent.APPLY, who, row)
    return row


def _audit(kind, who, row, note=""):
    return AuditEvent.objects.create(
        kind=kind,
        actor=who,
        change=row.pk,
        op=row.op,
        action=row.action,
        target=row.target,
        before=row.before,
        after=row.after,
        note=note[:200],
    )


def _pk(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise Bad("That change is not in the log.")


def commit(user, op_name, action, post):
    if action not in registry.ACTIONS:
        raise Bad("That is not a valid action.")
    op = registry.get(op_name)
    if not can_use_op(user, op):
        raise PermissionDenied
    data = op.parse(post)
    with c.session() as session:
        before = op.snapshot(session, data)
        after = op.validate(session, action, data, before)
        if action == "update" and before is not None and jsonable(before) == jsonable(after):
            return "same", None
        after = op.apply(session, action, before, dict(after))
        who = actor_name(user)
        _compat(session, who, op.compat_sql(action, before, after))
        session.commit()
    row = _record(op, action, before, after, who)
    log.info("Applied %s %s %s as %s by %s.", row.id, action, row.target, op.name, who)
    return "applied", row


def restore(user, pk):
    """Toggle one change between applied and rolled back, without creating new rows."""
    row = Change.objects.filter(pk=_pk(pk)).first()
    if row is None or row.restores_id:
        raise Bad("That change is not in the log.")
    op = registry.get(row.op)
    if not can_use_op(user, op):
        raise PermissionDenied
    if not can_rollback(user):
        raise PermissionDenied
    undo = row.status == Change.APPLIED
    expected = row.after if undo else row.before
    with c.session() as session:
        live = op.snapshot(session, expected or {})
        matched = live is None if undo and row.action in ("delete", "unlink") else op.live_matches(live, expected)
        if not matched:
            raise Bad("The catalog no longer matches this change, so it cannot be safely undone.")
        action, payload = op.invert_change(row.action, row.before, row.after) if undo else (row.action, row.after or {})
        after = op.apply(session, action, live, op.validate(session, action, payload or {}, live))
        who = actor_name(user)
        _compat(session, who, op.compat_sql(action, live, after))
        session.commit()
    row.status = Change.ROLLED_BACK if undo else Change.APPLIED
    row.rolled_back_by = who if undo else ""
    row.rolled_back_at = timezone.now() if undo else None
    row.save(update_fields=["status", "rolled_back_by", "rolled_back_at"])
    _audit(AuditEvent.ROLLBACK if undo else AuditEvent.REAPPLY, who, row)
    log.info("%s change %s (%s) by %s.", "Rolled back" if undo else "Reapplied", row.id, op.name, who)
    return ("restored" if undo else "reapplied"), row


def restore_many(user, ids):
    ordered = sorted({_pk(value) for value in ids}, reverse=True)
    if not ordered:
        raise Bad("Select at least one change.")
    done = []
    for pk in ordered:
        try:
            restore(user, pk)
        except Bad as exc:
            return done, pk, str(exc)
        done.append(pk)
    return done, None, None
