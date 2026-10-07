import logging

from django.utils import timezone

from . import gutenberg as g
from .models import Change, is_reviewer

log = logging.getLogger(__name__)


def _open(shelf_pk=None):
    rows = Change.objects.filter(status__in=(Change.PENDING, Change.ACCEPTED))
    if shelf_pk is not None:
        rows = rows.filter(shelf_pk=shelf_pk)
    return rows


def sets(shelf_pk):
    adds, rems, accepted = set(), set(), set()
    for kind, book_pk, status in _open(shelf_pk).values_list('kind', 'book_pk', 'status'):
        (adds if kind == Change.ADD else rems).add(book_pk)
        if status == Change.ACCEPTED:
            accepted.add(book_pk)
    return adds, rems, accepted


def queue(shelf_pk, book_pk, want):
    """Queue an add or a remove. Returns queued, cleared, or same."""
    row = _open(shelf_pk).filter(book_pk=book_pk).first()
    kind = Change.ADD if want else Change.REMOVE
    if row and row.kind != kind:
        row.delete()
        return 'cleared'
    if row or want == g.on_shelf(shelf_pk, book_pk):
        return 'same'
    Change.objects.create(kind=kind, shelf_pk=shelf_pk, book_pk=book_pk)
    return 'queued'


def decide(change, user, vote):
    """Apply a reviewer vote. On approve, write the catalog then mark processed."""
    if not is_reviewer(user) or change.status == Change.PROCESSED:
        return
    if vote == 'approve' and change.status in (Change.PENDING, Change.ACCEPTED):
        want = change.kind == Change.ADD
        try:
            ok = g.set_membership(change.shelf_pk, change.book_pk, want)
        except Exception:
            log.exception(
                'Failed to %s book %s %s shelf %s, change %s.',
                'add' if want else 'remove', change.book_pk,
                'to' if want else 'from', change.shelf_pk, change.id)
            return 'failed'
        if not ok:
            log.error(
                'Failed to %s book %s %s shelf %s, change %s.',
                'add' if want else 'remove', change.book_pk,
                'to' if want else 'from', change.shelf_pk, change.id)
            return 'failed'
        change.status = Change.PROCESSED
        change.processed_at = timezone.now()
        change.save(update_fields=['status', 'processed_at'])
        log.info(
            '%s book %s %s shelf %s, change %s, by %s.',
            'Added' if want else 'Removed', change.book_pk,
            'to' if want else 'from', change.shelf_pk, change.id,
            user.email or user.get_username(),
        )
        return 'processed'
    if vote == 'unapprove' and change.status == Change.ACCEPTED:
        change.status = Change.PENDING
        change.save(update_fields=['status'])
        log.info('Unapproved change %s, by %s.', change.id,
                 user.email or user.get_username())
        return 'unapproved'
    if vote == 'drop':
        log.info(
            'Dropped %s book %s %s shelf %s, change %s, by %s.',
            'add' if change.kind == Change.ADD else 'remove',
            change.book_pk,
            'to' if change.kind == Change.ADD else 'from',
            change.shelf_pk, change.id,
            user.email or user.get_username(),
        )
        change.delete()
        return 'dropped'


def rows():
    items = list(Change.objects.exclude(status=Change.PROCESSED))
    titles = g.titles(item.book_pk for item in items)
    names = g.shelf_names(item.shelf_pk for item in items)
    for item in items:
        verb = 'Add' if item.kind == Change.ADD else 'Remove'
        prep = 'to' if item.kind == Change.ADD else 'from'
        item.label = '%s #%s %s %s “%s”' % (
            verb, item.book_pk, titles.get(item.book_pk) or 'Untitled', prep,
            names.get(item.shelf_pk) or '#%s' % item.shelf_pk)
    return items
