from contextlib import contextmanager

from django.conf import settings
from sqlalchemy import and_, func, or_, select

_base = None
_lib = None


def _models():
    global _base, _lib
    if _lib is None:
        from libgutenberg import Models
        from libgutenberg.GutenbergDatabase import Objectbase

        _base, _lib = Objectbase(False), Models
    return _lib


@contextmanager
def _session():
    _models()
    session = _base.get_session()
    try:
        yield session
    finally:
        session.close()


def _paginate(stmt, session, page, size=None):
    page = max(1, int(page or 1))
    size = max(1, int(size or settings.PAGE_SIZE))
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = session.execute(stmt.limit(size).offset((page - 1) * size)).mappings().all()
    return [dict(row) for row in rows], total


def _titles(rows):
    for row in rows:
        lines = [part.strip() for part in (row.get("title") or "").split("\n") if part.strip()]
        row["title"] = lines[0] if lines else "Untitled"
        row["subtitle"] = "; ".join(lines[1:])
        author = row.get("author") or []
        row["authors"] = "; ".join(author) if isinstance(author, (list, tuple)) else author
    return rows


def _book_query(query):
    cat = _models().t_v_appserver_books_4
    return (
        cat.c.pk == int(query)
        if str(query).isdigit()
        else cat.c.tsvec.op("@@")(func.websearch_to_tsquery("english", query))
    )


def _shelf_stmt():
    m = _models()
    shelf, mem = m.Bookshelf, m.t_mn_books_bookshelves
    stmt = (
        select(
            shelf.id.label("pk"),
            shelf.bookshelf,
            shelf.downloads,
            func.count(mem.c.fk_books).label("books"),
        )
        .outerjoin(mem, mem.c.fk_bookshelves == shelf.id)
        .group_by(shelf.id, shelf.bookshelf, shelf.downloads)
    )
    return shelf, stmt


def shelves(query="", page=1):
    shelf, stmt = _shelf_stmt()
    stmt = stmt.order_by(shelf.bookshelf)
    if query:
        stmt = stmt.where(
            shelf.id == int(query)
            if query.isdigit()
            else shelf.tsvec.op("@@")(func.websearch_to_tsquery("english", query))
        )
    with _session() as session:
        return _paginate(stmt, session, page)


def shelf(pk):
    _shelf, stmt = _shelf_stmt()
    with _session() as session:
        row = session.execute(stmt.where(_shelf.id == pk)).mappings().first()
    return dict(row) if row else None


def shelf_names(pks):
    pks = list(dict.fromkeys(pk for pk in pks if pk))
    if not pks:
        return {}
    shelf = _models().Bookshelf
    with _session() as session:
        return {
            pk: name for pk, name in session.execute(select(shelf.id, shelf.bookshelf).where(shelf.id.in_(pks))).all()
        }


def members(shelf_pk, book_pks):
    book_pks = list(book_pks)
    if not book_pks:
        return set()
    mem = _models().t_mn_books_bookshelves
    with _session() as session:
        return {
            row[0]
            for row in session.execute(
                select(mem.c.fk_books).where(mem.c.fk_bookshelves == shelf_pk, mem.c.fk_books.in_(book_pks))
            ).all()
        }


def on_shelf(shelf_pk, book_pk):
    return book_pk in members(shelf_pk, [book_pk])


def titles(pks):
    pks = list(dict.fromkeys(pk for pk in pks if pk))
    if not pks:
        return {}
    cat = _models().t_v_appserver_books_4
    with _session() as session:
        rows = _titles(
            [dict(row) for row in session.execute(select(cat.c.pk, cat.c.title).where(cat.c.pk.in_(pks))).mappings()]
        )
    return {row["pk"]: row["title"] for row in rows}


def book_title(pk):
    return titles([pk]).get(pk)


def _books_stmt(cond):
    cat = _models().t_v_appserver_books_4
    return select(cat.c.pk, cat.c.title, cat.c.author, cat.c.downloads).where(cond).order_by(cat.c.filing)


def shelf_books(shelf_pk, query="", page=1, also=()):
    m = _models()
    cat, mem = m.t_v_appserver_books_4, m.t_mn_books_bookshelves
    cond = cat.c.pk.in_(select(mem.c.fk_books).where(mem.c.fk_bookshelves == shelf_pk))
    extra = [pk for pk in also if pk]
    if extra:
        cond = or_(cond, cat.c.pk.in_(extra))
    if query:
        cond = and_(cond, _book_query(query))
    with _session() as session:
        rows, total = _paginate(_books_stmt(cond), session, page)
    return _titles(rows), total


def search_books(query, page=1, size=None):
    if not query:
        return [], 0
    cat = _models().t_v_appserver_books_4
    match = _book_query(query)
    with _session() as session:
        rows, total = _paginate(_books_stmt(match).order_by(cat.c.downloads.desc()), session, page, size)
    return _titles(rows), total


def recent_books(page=1):
    """Default Books listing: newest ebook numbers first."""
    cat = _models().t_v_appserver_books_4
    with _session() as session:
        rows, total = _paginate(_books_stmt(True).order_by(cat.c.pk.desc()), session, page)
    return _titles(rows), total
