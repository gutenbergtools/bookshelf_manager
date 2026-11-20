"""Read/search layer over libgutenberg models."""

from contextlib import contextmanager

from django.conf import settings
from sqlalchemy import and_, exists, func, or_, select

from .clean import like_pattern

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


session = _session
_m = _models


def _rows(session, stmt):
    return [dict(row) for row in session.execute(stmt).mappings()]


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
    if str(query).isdigit():
        return cat.c.pk == int(query)
    return cat.c.tsvec.op("@@")(func.websearch_to_tsquery("english", query))



def _books_stmt(cond):
    cat = _models().t_v_appserver_books_4
    return select(cat.c.pk, cat.c.title, cat.c.author, cat.c.downloads).where(cond).order_by(cat.c.filing)


def _book_order(sort):
    cat = _models().t_v_appserver_books_4
    return {
        "newest": cat.c.pk.desc(),
        "oldest": cat.c.pk.asc(),
        "downloads": cat.c.downloads.desc(),
        "title": cat.c.filing,
    }.get(sort)



def _search_books(query, page=1, size=None, sort=""):
    if not query:
        return [], 0
    cat = _models().t_v_appserver_books_4
    order = _book_order(sort)
    stmt = _books_stmt(_book_query(query)).order_by(None).order_by(order if order is not None else cat.c.downloads.desc())
    with _session() as s:
        rows, total = _paginate(stmt, s, page, size)
    return _titles(rows), total


def recent_books(page=1, sort="newest"):
    """Default Books listing: newest ebook numbers first."""
    cat = _models().t_v_appserver_books_4
    order = _book_order(sort)
    stmt = _books_stmt(True).order_by(None).order_by(order if order is not None else cat.c.pk.desc())
    with _session() as s:
        rows, total = _paginate(stmt, s, page)
    return _titles(rows), total


def lookups():
    m = _models()
    with session() as s:

        def opts(pk, label, fmt, order=None, where=None):
            stmt = select(pk, label) if where is None else select(pk, label).where(where)
            return [(a, fmt(a, b)) for a, b in s.execute(stmt.order_by(label if order is None else order)).all()]

        roles = opts(m.Role.pk, m.Role.role, lambda a, b: "%s (%s)" % (b, a))
        langs = opts(m.Lang.id, m.Lang.language, lambda a, b: "%s (%s)" % (b, a))
        loccs = opts(m.Locc.id, m.Locc.locc, lambda a, b: "%s — %s" % (a, b), m.Locc.id)
        cats = opts(m.Category.pk, m.Category.category, lambda a, b: b)
        attribs = opts(
            m.Attriblist.pk,
            m.Attriblist.name,
            lambda a, b: "%s (%s)" % (b, a),
            order=m.Attriblist.pk,
            where=m.Attriblist.type == "unc",
        )
    return {"roles": roles, "langs": langs, "loccs": loccs, "categories": cats, "attribs": attribs}


def exists_book(s, pk):
    return s.get(_m().Book, int(pk)) is not None


def exists_author(s, pk):
    return s.get(_m().Author, int(pk)) is not None


def exists_subject(s, pk):
    return s.get(_m().Subject, int(pk)) is not None


def book_row(session, pk):
    book = session.get(_m().Book, int(pk))
    if book is None:
        return None
    return {
        "pk": book.pk,
        "release_date": book.release_date.isoformat() if book.release_date else "",
        "copyrighted": int(book.copyrighted or 0),
        "updatemode": int(book.updatemode or 0),
        "gutindex": book.gutindex or "",
        "downloads": book.downloads,
        "title": (book.title or "Untitled").split("\n")[0],
    }


def author_row(session, pk):
    author = session.get(_m().Author, int(pk))
    if author is None:
        return None
    return {
        "pk": author.id,
        "author": author.name,
        "born_floor": author.birthdate,
        "born_ceil": author.birthdate2,
        "died_floor": author.deathdate,
        "died_ceil": author.deathdate2,
        "note": author.note or "",
    }


def search_authors(query, page=1, size=None, sort=""):
    m = _m()
    stmt = select(
        m.Author.id.label("pk"),
        m.Author.name.label("author"),
        m.Author.birthdate,
        m.Author.deathdate,
        m.Author.downloads,
    )
    if query:
        q = "%" + like_pattern(query) + "%"
        stmt = (
            stmt.where(m.Author.id == int(query))
            if str(query).isdigit()
            else stmt.where(
                or_(
                    m.Author.name.ilike(q, escape="\\"),
                    exists().where(and_(m.Alias.fk_authors == m.Author.id, m.Alias.alias.ilike(q, escape="\\"))),
                )
            )
        )
    order = {"newest": m.Author.id.desc(), "downloads": m.Author.downloads.desc()}.get(sort)
    if order is None:
        order = m.Author.name
    with session() as s:
        return _paginate(stmt.order_by(order), s, page, size)


def search_books(query, page=1, size=None, sort=""):
    rows, total = _search_books(query, page, size, sort=sort)
    if str(query).isdigit():
        pk = int(query)
        if not any(row["pk"] == pk for row in rows):
            with session() as s:
                book = book_row(s, pk)
            if book:
                rows = [{"pk": pk, "title": book["title"], "authors": "", "downloads": book.get("downloads") or 0}] + rows
                total += 1
    return rows, total


_MN = {
    "subjects": ("t_mn_books_subjects", "Subject", "fk_subjects", "id", "subject", "subject", "label"),
    "langs": ("t_mn_books_langs", "Lang", "fk_langs", "id", "language", "lang", "label"),
    "loccs": ("t_mn_books_loccs", "Locc", "fk_loccs", "id", "locc", "locc", "id"),
    "categories": ("t_mn_books_categories", "Category", "fk_categories", "pk", "category", "category", "label"),
}


def _mn(session, pk, kind):
    table_name, model, fk, pkcol, label, alias, order = _MN[kind]
    m = _m()
    table, col = getattr(m, table_name), getattr(m, model)
    field, key = getattr(col, pkcol), getattr(col, label)
    return _rows(
        session,
        select(field.label("pk"), key.label(alias))
        .join(table, getattr(table.c, fk) == field)
        .where(table.c.fk_books == pk)
        .order_by(field if order == "id" else key),
    )


def book_authors(session, pk):
    m = _m()
    stmt = (
        select(
            m.Author.id.label("pk"),
            m.Author.name.label("author"),
            m.BookAuthor.fk_roles,
            m.Role.role,
            m.BookAuthor.heading,
            m.Author.birthdate,
            m.Author.deathdate,
        )
        .join(m.BookAuthor, m.BookAuthor.fk_authors == m.Author.id)
        .join(m.Role, m.Role.pk == m.BookAuthor.fk_roles)
        .where(m.BookAuthor.fk_books == pk)
        .order_by(m.Author.name, m.BookAuthor.fk_roles)
    )
    return _rows(session, stmt)


def book_attributes(session, pk):
    m = _m()
    stmt = (
        select(
            m.Attribute.pk,
            m.Attribute.fk_attriblist,
            m.Attriblist.name,
            m.Attribute.text,
            m.Attribute.nonfiling,
            m.Attribute.indicators,
            m.Attribute.fk_langs,
        )
        .join(m.Attriblist, m.Attriblist.pk == m.Attribute.fk_attriblist)
        .where(m.Attribute.fk_books == pk)
        .order_by(m.Attriblist.name, m.Attribute.pk)
    )
    return _rows(session, stmt)


def author_aliases(session, pk):
    m = _m()
    return _rows(session, select(m.Alias.pk, m.Alias.alias, m.Alias.heading).where(m.Alias.fk_authors == pk).order_by(m.Alias.pk))



def author_books(session, pk):
    m = _m()
    stmt = (
        select(m.Book.pk, m.Book.title, m.BookAuthor.fk_roles, m.BookAuthor.heading, m.Role.role)
        .join(m.BookAuthor, m.BookAuthor.fk_books == m.Book.pk)
        .join(m.Role, m.Role.pk == m.BookAuthor.fk_roles)
        .where(m.BookAuthor.fk_authors == pk)
        .order_by(m.Book.pk)
    )
    return _titles(_rows(session, stmt))


def author_book_count(session, pk):
    m = _m()
    return session.scalar(select(func.count()).select_from(m.BookAuthor).where(m.BookAuthor.fk_authors == int(pk))) or 0


def linked(session, table, book_pk, other_field, other_pk, extras=None):
    cond = [table.c.fk_books == int(book_pk), getattr(table.c, other_field) == other_pk] + [
        getattr(table.c, key) == value for key, value in (extras or {}).items()
    ]
    return session.execute(select(table).where(and_(*cond))).mappings().first()



def attribute_row(session, pk):
    row = session.get(_m().Attribute, int(pk))
    if row is None:
        return None
    return {
        "pk": row.pk,
        "fk_books": row.fk_books,
        "fk_attriblist": row.fk_attriblist,
        "text": row.text,
        "nonfiling": row.nonfiling,
        "indicators": row.indicators or "  ",
        "fk_langs": row.fk_langs,
    }


def alias_row(session, pk):
    row = session.get(_m().Alias, int(pk))
    if row is None:
        return None
    return {"pk": row.pk, "fk_authors": row.fk_authors, "alias": row.alias, "heading": int(row.heading or 0)}



def book_page(pk):
    with session() as s:
        book = book_row(s, pk)
        if book is None:
            return None
        attrs = book_attributes(s, pk)
        sub = ""
        for r in attrs:
            if str(r["fk_attriblist"]) == "245":
                p = (r["text"] or "").replace("\r", "\n").split("\n", 1)
                sub = " ".join(p[1].split()) if len(p) > 1 else ""
                break
        return {
            "book": book,
            "subtitle": sub,
            "authors": book_authors(s, pk),
            "attributes": attrs,
            "subjects": _mn(s, pk, "subjects"),
            "langs": _mn(s, pk, "langs"),
            "loccs": _mn(s, pk, "loccs"),
            "categories": _mn(s, pk, "categories"),
        }


def author_page(pk):
    with session() as s:
        author = author_row(s, pk)
        if author is None:
            return None
        return {
            "author": author,
            "aliases": author_aliases(s, pk),
            "books": author_books(s, pk),
            "nbooks": author_book_count(s, pk),
        }


