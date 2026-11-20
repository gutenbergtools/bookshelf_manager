from sqlalchemy import and_, exists, func, or_, select

from . import gutenberg as g
from .clean import like_pattern

session = g._session
_m = g._models


def _rows(session, stmt):
    return [dict(row) for row in session.execute(stmt).mappings()]


def lookups():
    m = _m()
    with session() as s:

        def opts(pk, label, fmt, order=None, where=None):
            return [
                (a, fmt(a, b))
                for a, b in s.execute(
                    (select(pk, label).where(where) if where is not None else select(pk, label)).order_by(
                        label if order is None else order
                    )
                ).all()
            ]

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
    return (
        None
        if book is None
        else {
            "pk": book.pk,
            "release_date": book.release_date.isoformat() if book.release_date else "",
            "copyrighted": int(book.copyrighted or 0),
            "updatemode": int(book.updatemode or 0),
            "gutindex": book.gutindex or "",
            "downloads": book.downloads,
            "title": (book.title or "Untitled").split("\n")[0],
        }
    )


def author_row(session, pk):
    author = session.get(_m().Author, int(pk))
    return (
        None
        if author is None
        else {
            "pk": author.id,
            "author": author.name,
            "born_floor": author.birthdate,
            "born_ceil": author.birthdate2,
            "died_floor": author.deathdate,
            "died_ceil": author.deathdate2,
            "note": author.note or "",
        }
    )


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
    order = {
        "newest": m.Author.id.desc(),
        "downloads": m.Author.downloads.desc(),
    }.get(sort)
    if order is None:
        order = m.Author.name
    with session() as s:
        return g._paginate(stmt.order_by(order), s, page, size)


def search_books(query, page=1, size=None, sort=""):
    rows, total = g.search_books(query, page, size, sort=sort)
    if str(query).isdigit():
        pk = int(query)
        if not any(row["pk"] == pk for row in rows):
            with session() as s:
                book = book_row(s, pk)
            if book:
                rows = [
                    {
                        "pk": pk,
                        "title": book["title"],
                        "authors": "",
                        "downloads": book.get("downloads") or 0,
                    }
                ] + rows
                total += 1
    return rows, total


_MN = {
    "subjects": (
        "t_mn_books_subjects",
        "Subject",
        "fk_subjects",
        "id",
        "subject",
        "subject",
        "label",
    ),
    "langs": ("t_mn_books_langs", "Lang", "fk_langs", "id", "language", "lang", "label"),
    "loccs": ("t_mn_books_loccs", "Locc", "fk_loccs", "id", "locc", "locc", "id"),
    "categories": (
        "t_mn_books_categories",
        "Category",
        "fk_categories",
        "pk",
        "category",
        "category",
        "label",
    ),
}


def _mn(session, pk, spec):
    table_name, model, fk, pkcol, label, alias, order = spec
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


def book_subjects(s, pk):
    return _mn(s, pk, _MN["subjects"])


def book_langs(s, pk):
    return _mn(s, pk, _MN["langs"])


def book_loccs(s, pk):
    return _mn(s, pk, _MN["loccs"])


def book_categories(s, pk):
    return _mn(s, pk, _MN["categories"])


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
    return _rows(
        session,
        select(m.Alias.pk, m.Alias.alias, m.Alias.heading).where(m.Alias.fk_authors == pk).order_by(m.Alias.pk),
    )


def author_urls(session, pk):
    m = _m()
    return _rows(
        session,
        select(m.AuthorUrl.pk, m.AuthorUrl.description, m.AuthorUrl.url)
        .where(m.AuthorUrl.fk_authors == pk)
        .order_by(m.AuthorUrl.pk),
    )


def author_books(session, pk):
    m = _m()
    stmt = (
        select(m.Book.pk, m.Book.title, m.BookAuthor.fk_roles, m.BookAuthor.heading, m.Role.role)
        .join(m.BookAuthor, m.BookAuthor.fk_books == m.Book.pk)
        .join(m.Role, m.Role.pk == m.BookAuthor.fk_roles)
        .where(m.BookAuthor.fk_authors == pk)
        .order_by(m.Book.pk)
    )
    return g._titles(_rows(session, stmt))


def author_book_count(session, pk):
    m = _m()
    return session.scalar(select(func.count()).select_from(m.BookAuthor).where(m.BookAuthor.fk_authors == int(pk))) or 0


def author_links(session, pk):
    m = _m()
    return _rows(
        session,
        select(
            m.BookAuthor.fk_books,
            m.BookAuthor.fk_authors,
            m.BookAuthor.fk_roles,
            m.BookAuthor.heading,
        ).where(m.BookAuthor.fk_authors == int(pk)),
    )


def linked(session, table, book_pk, other_field, other_pk, extras=None):
    cond = [table.c.fk_books == int(book_pk), getattr(table.c, other_field) == other_pk] + [
        getattr(table.c, key) == value for key, value in (extras or {}).items()
    ]
    return session.execute(select(table).where(and_(*cond))).mappings().first()


def list_simple(model, pk_attr, label_attr, query, page, pk_is_str=False, size=None, sort="", count_table=None, count_field=None):
    pkcol, label = getattr(model, pk_attr), getattr(model, label_attr)
    stmt = select(pkcol.label("pk"), label.label("name"))
    if query:
        pattern = "%" + like_pattern(query) + "%"
        if not pk_is_str and str(query).isdigit():
            stmt = stmt.where(pkcol == int(query))
        elif pk_is_str:
            stmt = stmt.where(pkcol.ilike(query) | label.ilike(pattern, escape="\\"))
        else:
            stmt = stmt.where(label.ilike(pattern, escape="\\"))
    order = label
    if sort == "books" and count_table is not None:
        order = (
            select(func.count())
            .select_from(count_table)
            .where(count_table.c[count_field] == pkcol)
            .scalar_subquery()
            .desc()
        )
    elif sort == "code":
        order = pkcol
    elif sort == "newest":
        order = pkcol.desc()
    with session() as s:
        return g._paginate(stmt.order_by(order), s, page, size)


def search_categories(q, p=1, sort=""):
    return list_simple(
        _m().Category, "pk", "category", q, p,
        sort=sort, count_table=_m().t_mn_books_categories, count_field="fk_categories",
    )


def search_langs(q, p=1, sort=""):
    return list_simple(
        _m().Lang, "id", "language", q, p, True,
        sort=sort, count_table=_m().t_mn_books_langs, count_field="fk_langs",
    )


def search_loccs(q, p=1, sort=""):
    return list_simple(
        _m().Locc, "id", "locc", q, p, True,
        sort=sort, count_table=_m().t_mn_books_loccs, count_field="fk_loccs",
    )


def search_subjects(q, p=1, size=None, sort=""):
    return list_simple(
        _m().Subject, "id", "subject", q, p, size=size,
        sort=sort, count_table=_m().t_mn_books_subjects, count_field="fk_subjects",
    )


def simple_entity(model, pk_attr, label_attr, pk, str_pk=False):
    with session() as s:
        row = s.get(getattr(_m(), model), pk if str_pk else int(pk))
        return None if row is None else {"pk": getattr(row, pk_attr), "name": getattr(row, label_attr)}


def attribute_row(session, pk):
    row = session.get(_m().Attribute, int(pk))
    return (
        None
        if row is None
        else {
            "pk": row.pk,
            "fk_books": row.fk_books,
            "fk_attriblist": row.fk_attriblist,
            "text": row.text,
            "nonfiling": row.nonfiling,
            "indicators": row.indicators or "  ",
            "fk_langs": row.fk_langs,
        }
    )


def alias_row(session, pk):
    row = session.get(_m().Alias, int(pk))
    return (
        None
        if row is None
        else {
            "pk": row.pk,
            "fk_authors": row.fk_authors,
            "alias": row.alias,
            "heading": int(row.heading or 0),
        }
    )


def url_row(session, pk):
    row = session.get(_m().AuthorUrl, int(pk))
    return (
        None
        if row is None
        else {
            "pk": row.pk,
            "fk_authors": row.fk_authors,
            "description": row.description or "",
            "url": row.url,
        }
    )


def book_page(pk):
    with session() as s:
        book = book_row(s, pk)
        if book is None:
            return None
        langs, loccs, cats = book_langs(s, pk), book_loccs(s, pk), book_categories(s, pk)
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
            "subjects": book_subjects(s, pk),
            "langs": langs,
            "loccs": loccs,
            "categories": cats,
        }


def author_page(pk):
    with session() as s:
        author = author_row(s, pk)
        return (
            None
            if author is None
            else {
                "author": author,
                "aliases": author_aliases(s, pk),
                "urls": author_urls(s, pk),
                "books": author_books(s, pk),
                "nbooks": author_book_count(s, pk),
            }
        )


def empty_authors(page=1):
    m = _m()
    stmt = (
        select(
            m.Author.id.label("pk"),
            m.Author.name.label("author"),
            m.Author.birthdate,
            m.Author.deathdate,
        )
        .outerjoin(m.BookAuthor, m.BookAuthor.fk_authors == m.Author.id)
        .where(m.BookAuthor.fk_books.is_(None))
        .order_by(m.Author.name, m.Author.id)
    )
    with session() as s:
        return g._paginate(stmt, s, page)


def lacking_subject_locc(page=1, days=0):
    m = _m()
    attr, sub, locc, ba, auth, book = (
        m.Attribute,
        m.t_mn_books_subjects,
        m.t_mn_books_loccs,
        m.BookAuthor,
        m.Author,
        m.Book,
    )
    stmt = (
        select(
            attr.fk_books.label("pk"),
            attr.text.label("title"),
            auth.name.label("author"),
            sub.c.fk_subjects.label("fk_subjects"),
            locc.c.fk_loccs.label("fk_loccs"),
        )
        .select_from(attr)
        .outerjoin(sub, sub.c.fk_books == attr.fk_books)
        .outerjoin(locc, locc.c.fk_books == attr.fk_books)
        .join(ba, ba.fk_books == attr.fk_books)
        .join(auth, auth.id == ba.fk_authors)
        .where(attr.fk_attriblist == 245)
        .where(or_(sub.c.fk_subjects.is_(None), locc.c.fk_loccs.is_(None)))
        .distinct(attr.fk_books)
        .order_by(attr.fk_books, attr.text, auth.name)
    )
    if days:
        stmt = stmt.join(book, book.pk == attr.fk_books).where(book.release_date >= func.current_date() - int(days))
    with session() as s:
        return g._paginate(stmt, s, page)


def attrib_usage():
    m = _m()
    stmt = (
        select(m.Attriblist.pk, m.Attriblist.name, func.count(m.Attribute.pk).label("cnt"))
        .outerjoin(m.Attribute, m.Attribute.fk_attriblist == m.Attriblist.pk)
        .group_by(m.Attriblist.pk, m.Attriblist.name)
        .order_by(m.Attriblist.pk)
    )
    with session() as s:
        return _rows(s, stmt)


def attrib_uses(pk, page=1):
    m = _m()
    stmt = (
        select(m.Attribute.fk_books.label("pk"), m.Attribute.text)
        .where(m.Attribute.fk_attriblist == int(pk))
        .order_by(m.Attribute.fk_books, m.Attribute.pk)
    )
    with session() as s:
        return g._paginate(stmt, s, page)


def attrib_name(pk):
    with session() as s:
        row = s.get(_m().Attriblist, int(pk))
        return None if row is None else row.name
