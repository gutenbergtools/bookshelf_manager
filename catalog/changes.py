"""Apply catalog edits immediately and append them to the event log."""

import logging

from django.core.exceptions import PermissionDenied
from django.utils import timezone
from sqlalchemy import func

from . import catalog as c
from . import gutenberg as g
from . import ops as registry
from .clean import Bad, jsonable
from .models import Change, EventLog, actor_name, can_use_op

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
    _audit(who, row)
    return row


def _audit(who, row, note=""):
    return EventLog.objects.create(
        actor=who,
        change=row.pk,
        op=row.op,
        action=row.action,
        target=row.target,
        before=row.before,
        after=row.after,
        note=note[:200],
    )


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
