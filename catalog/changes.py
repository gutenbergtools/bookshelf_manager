"""Apply catalog edits immediately and write the Postgres changelog SQL."""

import logging

from django.core.exceptions import PermissionDenied
from sqlalchemy import func

from . import catalog as c
from . import ops as registry
from .clean import Bad, jsonable
from .models import actor_name, can_use_op

log = logging.getLogger(__name__)


def _compat(session, who, sql):
    if not sql:
        return
    session.execute(
        c._models().t_changelog.insert().values(time=func.now(), login=(who or "")[:80], sql=sql[:10000], script="bsm")
    )


def commit(user, op_name, action, post):
    if action not in registry.ACTIONS:
        raise Bad("That is not a valid action.")
    op = registry.get(op_name)
    if not can_use_op(user, op):
        raise PermissionDenied
    data = op.parse(post)
    who = actor_name(user)
    with c.session() as session:
        before = op.snapshot(session, data)
        after = op.validate(session, action, data, before)
        if action == "update" and before is not None and jsonable(before) == jsonable(after):
            return "same", None
        after = op.apply(session, action, before, dict(after))
        _compat(session, who, op.compat_sql(action, before, after))
        session.commit()
    log.info("Applied %s %s as %s.", action, op_name, who)
    return "applied", after
