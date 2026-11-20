"""Catalog operations: forms, validation and persistence for every edit."""

from datetime import date

from django import forms
from django.utils.dateparse import parse_date
from sqlalchemy import and_, delete, select, text
from sqlalchemy.dialects.postgresql import insert

from . import catalog as c
from .clean import (
    LANG_RE,
    LOCC_RE,
    ROLE_RE,
    AliasForm,
    AttrForm,
    AuthorForm,
    Bad,
    BAForm,
    BookForm,
    CodeField,
    F,
    LangForm,
    ShelfForm,
    UrlForm,
    XferForm,
    cleaned,
    entity_form,
    jsonable,
)

OPS = {}
ACTIONS = ("create", "update", "delete", "link", "unlink")


def get(name):
    op = OPS.get(name)
    if not op:
        raise Bad("Unknown change type.")
    return op


class Op:
    def __init__(
        self,
        name,
        form=None,
        domain="catalog",
        snapshot=None,
        validate=None,
        apply=None,
        compat_sql=None,
        keep=None,
        optional_pk=True,
    ):
        self.name, self.domain, self.form = name, domain, form
        self.fields = tuple(form.base_fields) if form else ()
        self.keep, self.optional_pk = keep, optional_pk
        self._snap, self._val, self._apply = snapshot, validate, apply
        self._sql = compat_sql
        OPS[name] = self

    def parse(self, post):
        return dict((f, post.get(f, "")) for f in self.fields)

    def snapshot(self, session, data):
        return self._snap(session, data) if self._snap else None

    def validate(self, session, action, data, before):
        return (
            jsonable(
                self._val(
                    session,
                    action,
                    cleaned(self.form, data, action, keep=self.keep, optional_pk=self.optional_pk),
                    before,
                )
            )
            if self.form
            else jsonable(self._val(session, action, data, before))
        )

    def apply(self, session, action, before, after):
        return self._apply(session, action, before, after)

    def compat_sql(self, action, before, after):
        return self._sql(action, before, after) if self._sql else None


_m = c._models


def _ids(session, column, where=None):
    return set(session.scalars(select(column) if where is None else select(column).where(where)).all())


def _pick(row, keys):
    return None if row is None else {key: row[key] for key in keys}


def _need(before, kind):
    if not before:
        raise Bad("No such %s." % kind)


def apply_row(session, model, action, after, values, pk_attr="pk"):
    if action == "delete":
        session.execute(delete(model).where(getattr(model, pk_attr) == after["pk"]))
        return after
    if action == "create":
        kwargs = dict(values)
        if after.get("pk") is not None:
            kwargs[pk_attr] = after["pk"]
        row = model(**kwargs)
        session.add(row)
        session.flush()
        after["pk"] = getattr(row, pk_attr)
        return after
    row = session.get(model, after["pk"])
    for key, value in values.items():
        setattr(row, key, value)
    return after


def link_apply(session, table, linking, keys, values=None):
    """Insert a link row (idempotent) or delete it by its key columns."""
    if linking:
        session.execute(insert(table).values(**keys, **(values or {})).on_conflict_do_nothing())
    else:
        session.execute(delete(table).where(and_(*(getattr(table.c, key) == value for key, value in keys.items()))))


def snap_pk(getter):
    def snapshot(session, data):
        raw = str(data.get("pk") or "").strip()
        if not raw:
            return None
        try:
            pk = int(raw)
        except ValueError:
            pk = raw
        return getter(session, pk)

    return snapshot


def exists_state(action, before, kind):
    if action in ("create", "link") and before:
        raise Bad("Already linked." if action == "link" else "That %s already exists." % kind)
    if action in ("update", "unlink", "delete") and not before:
        raise Bad("Not linked." if action == "unlink" else "No such %s." % kind)


def _shelf_val(session, action, data, before):
    if c.shelf(data["shelf_pk"]) is None:
        raise Bad("No such bookshelf.")
    if c.book_title(data["book_pk"]) is None:
        raise Bad("No ebook #%s exists in the catalog." % data["book_pk"])
    want = {"link": 1, "unlink": 0}.get(action, data.get("want") or 0)
    if want and before and before.get("on"):
        raise Bad("That book is already on this shelf.")
    if not want and before and not before.get("on"):
        raise Bad("That book is not on this shelf.")
    return {"shelf_pk": data["shelf_pk"], "book_pk": data["book_pk"], "on": want}


def _shelf_apply(session, action, before, after):
    keys = dict(fk_books=after["book_pk"], fk_bookshelves=after["shelf_pk"])
    link_apply(session, _m().t_mn_books_bookshelves, after["on"], keys)
    return after


Op(
    "shelf_member",
    form=ShelfForm,
    domain="shelves",
    snapshot=lambda s, d: {
        "shelf_pk": int(d["shelf_pk"]),
        "book_pk": int(d["book_pk"]),
        "on": int(c.on_shelf(int(d["shelf_pk"]), int(d["book_pk"]))),
    },
    validate=_shelf_val,
    apply=_shelf_apply,
)


def _book_val(session, action, data, before):
    if action == "delete":
        raise Bad("Books cannot be deleted here.")
    exists_state(action, before, "ebook")
    data["release_date"] = data.get("release_date") or date.today().isoformat()
    data["copyrighted"] = data.get("copyrighted") or 0
    data["updatemode"] = data.get("updatemode") or 0
    if not (data.get("title") or "").strip():
        raise Bad("Enter a title.")
    return data


def refresh_book_title(session, book_pk):
    """Recompute books.title/nonfiling from MARC 240/245/246.

    The catalogue database derives books.title with a trigger, so touching the
    row is how a changed MARC title becomes visible.
    """
    session.execute(text("update books set title = title where pk = :pk"), {"pk": book_pk})


def _book_apply(session, action, before, after):
    parsed = parse_date(str(after.get("release_date") or date.today().isoformat())[:10])
    if parsed is None:
        raise Bad("Enter the official release date.")
    row = apply_row(
        session,
        _m().Book,
        action,
        after,
        {
            "release_date": parsed,
            "title": after.get("title") or "",
            "copyrighted": after.get("copyrighted") or 0,
            "updatemode": after.get("updatemode") or 0,
        },
    )
    if action == "create" or (action == "update" and (before or {}).get("title") != after.get("title")):
        # books.title is only a cache of the MARC 245 value, so edit the source
        # field too or the trigger would immediately restore the old title.
        result = session.execute(
            text(
                "update attributes set text = :t "
                "where fk_books = :b and fk_attriblist = 245"
            ),
            {"t": after.get("title") or "", "b": after["pk"]},
        )
        if not result.rowcount:
            session.execute(
                text(
                    "insert into attributes (fk_books, fk_attriblist, text, nonfiling) "
                    "values (:b, 245, :t, :n)"
                ),
                {"b": after["pk"], "t": after.get("title") or "", "n": after.get("nonfiling") or 0},
            )
        refresh_book_title(session, after["pk"])
    return row


def _sql_str(value):
    return str(value or "").replace("'", "''")


def _book_sql(action, before, after):
    if action == "create":
        return "insert into books (pk, release_date, title, copyrighted, updatemode) values (%s, '%s', '%s', %s, %s)" % (
            after["pk"],
            after["release_date"],
            _sql_str(after.get("title")),
            after["copyrighted"],
            after["updatemode"],
        )
    if action == "update":
        return "update books set release_date = '%s', title = '%s', copyrighted = %s, updatemode = %s where pk = %s" % (
            after["release_date"],
            _sql_str(after.get("title")),
            after["copyrighted"],
            after["updatemode"],
            after["pk"],
        )
    return None


Op(
    "book",
    form=BookForm,
    optional_pk=False,
    snapshot=snap_pk(lambda s, pk: _pick(c.book_row(s, pk), ("pk", "release_date", "title", "copyrighted", "updatemode"))),
    validate=_book_val,
    apply=_book_apply,
    compat_sql=_book_sql,
)


def _author_val(session, action, data, before):
    if action == "delete":
        _need(before, "author")
        if c.author_book_count(session, data["pk"]):
            raise Bad("Unlink this author from every book before deleting.")
        return {"pk": data["pk"]}
    exists_state(action, before, "author")
    return data


def _author_apply(session, action, before, after):
    m = _m()
    if action == "delete":
        session.execute(delete(m.Alias).where(m.Alias.fk_authors == after["pk"]))
        session.execute(delete(m.AuthorUrl).where(m.AuthorUrl.fk_authors == after["pk"]))
        session.execute(delete(m.Author).where(m.Author.id == after["pk"]))
        return after
    return apply_row(
        session,
        m.Author,
        action,
        after,
        {
            "name": after["author"],
            "birthdate": after["born_floor"],
            "birthdate2": after["born_ceil"],
            "deathdate": after["died_floor"],
            "deathdate2": after["died_ceil"],
            "note": after["note"] or None,
        },
        "id",
    )


Op(
    "author",
    form=AuthorForm,
    snapshot=snap_pk(c.author_row),
    validate=_author_val,
    apply=_author_apply,
)


def _child_val(session, action, data, before, kind, fk, fk_name, exists):
    if not exists(session, data[fk]):
        raise Bad("No such %s." % fk_name)
    if action == "delete":
        _need(before, kind)
        return {"pk": data["pk"], fk: data[fk]}
    return data


Op(
    "alias",
    form=AliasForm,
    snapshot=snap_pk(c.alias_row),
    validate=lambda s, a, d, b: _child_val(s, a, d, b, "alias", "fk_authors", "author", c.exists_author),
    apply=lambda s, a, b, f: apply_row(
        s,
        _m().Alias,
        a,
        f,
        {"fk_authors": f["fk_authors"], "alias": f.get("alias"), "heading": f.get("heading")} if a != "delete" else {},
    ),
)
Op(
    "author_url",
    form=UrlForm,
    snapshot=snap_pk(c.url_row),
    validate=lambda s, a, d, b: _child_val(s, a, d, b, "URL", "fk_authors", "author", c.exists_author),
    apply=lambda s, a, b, f: apply_row(
        s,
        _m().AuthorUrl,
        a,
        f,
        {
            "fk_authors": f["fk_authors"],
            "description": f.get("description") or None,
            "url": f.get("url"),
        }
        if a != "delete"
        else {},
    ),
)


def add_link(name, table_fn, field, other_name, exists, other_field=None):
    form = F(
        **{
            "fk_books": forms.IntegerField(min_value=1),
            field: other_field or forms.IntegerField(min_value=1),
        }
    )

    def snapshot(session, data):
        book, other = data.get("fk_books"), data.get(field)
        if book in (None, "") or other in (None, ""):
            return None
        bound = cleaned(form, data)
        row = c.linked(session, table_fn(), bound["fk_books"], field, bound[field])
        return None if row is None else {"fk_books": bound["fk_books"], field: bound[field]}

    def validate(session, action, data, before):
        if not c.exists_book(session, data["fk_books"]):
            raise Bad("No such ebook.")
        if not exists(session, data[field]):
            raise Bad("That %s is not in the catalog." % other_name)
        exists_state(action, before, other_name)
        return {"fk_books": data["fk_books"], field: data[field]}

    def apply(session, action, before, after):
        link_apply(session, table_fn(), action == "link", {"fk_books": after["fk_books"], field: after[field]})
        return after

    Op(
        name,
        form=form,
        snapshot=snapshot,
        validate=validate,
        apply=apply,
    )


add_link("book_subject", lambda: _m().t_mn_books_subjects, "fk_subjects", "subject", c.exists_subject)
add_link(
    "book_lang",
    lambda: _m().t_mn_books_langs,
    "fk_langs",
    "language",
    lambda s, v: s.get(_m().Lang, v) is not None,
    CodeField(LANG_RE),
)
add_link(
    "book_locc",
    lambda: _m().t_mn_books_loccs,
    "fk_loccs",
    "LoC class",
    lambda s, v: s.get(_m().Locc, v) is not None,
    CodeField(LOCC_RE, case="upper"),
)
add_link(
    "book_category",
    lambda: _m().t_mn_books_categories,
    "fk_categories",
    "category",
    lambda s, v: s.get(_m().Category, int(v)) is not None,
)


def _ba_snap(session, data):
    data = dict(data)
    data["fk_roles"] = data.get("fk_roles") or "cr"
    bound = cleaned(BAForm, data)
    role = bound.get("was_roles") or bound["fk_roles"]
    row = c.linked(
        session,
        _m().BookAuthor.__table__,
        bound["fk_books"],
        "fk_authors",
        bound["fk_authors"],
        {"fk_roles": role},
    )
    return (
        None
        if row is None
        else {
            "fk_books": bound["fk_books"],
            "fk_authors": bound["fk_authors"],
            "fk_roles": row["fk_roles"],
            "heading": row.get("heading"),
        }
    )


def _ba_val(session, action, data, before):
    if not c.exists_book(session, data["fk_books"]):
        raise Bad("No such ebook.")
    if not c.exists_author(session, data["fk_authors"]):
        raise Bad("That author is not in the catalog.")
    role = data.get("fk_roles") or (before or {}).get("fk_roles") or "cr"
    if role not in _ids(session, _m().Role.pk):
        raise Bad("That author role is not in the catalog.")
    if action == "link" and before:
        raise Bad("Already linked.")
    if action in ("unlink", "update") and not before:
        raise Bad("Not linked.")
    return {
        "fk_books": data["fk_books"],
        "fk_authors": data["fk_authors"],
        "fk_roles": role,
        "heading": data.get("heading") if data.get("heading") is not None else 1,
    }


def _ba_apply(session, action, before, after):
    table = _m().BookAuthor.__table__
    keys = {"fk_books": after["fk_books"], "fk_authors": after["fk_authors"], "fk_roles": after["fk_roles"]}
    if action == "update":
        where = and_(
            table.c.fk_books == after["fk_books"],
            table.c.fk_authors == after["fk_authors"],
            table.c.fk_roles == (before or after)["fk_roles"],
        )
        session.execute(table.update().where(where).values(fk_roles=after["fk_roles"], heading=after["heading"]))
    else:
        link_apply(session, table, action == "link", keys, {"heading": after["heading"]})
    return after


def _ba_sql(action, before, after):
    book = after["fk_books"]
    if action == "link":
        return "insert into mn_books_authors (fk_books, fk_authors, fk_roles, heading) values (%s, %s, '%s', %s)" % (
            book,
            after["fk_authors"],
            after["fk_roles"],
            after["heading"],
        )
    if action == "update":
        return "update mn_books_authors set fk_roles = '%s', heading = %s where fk_books = %s and fk_authors = %s" % (
            after["fk_roles"],
            after["heading"],
            book,
            after["fk_authors"],
        )
    return "delete from mn_books_authors where fk_books = %s and fk_authors = %s and fk_roles = '%s'" % (
        book,
        after["fk_authors"],
        after["fk_roles"],
    )


Op(
    "book_author",
    form=BAForm,
    snapshot=_ba_snap,
    validate=_ba_val,
    apply=_ba_apply,
    compat_sql=_ba_sql,
)


def _attr_val(session, action, data, before):
    after = _child_val(session, action, data, before, "attribute", "fk_books", "ebook", c.exists_book)
    if action == "delete":
        return after
    tags = _m().Attriblist
    where = tags.type == "unc" if action == "create" else None
    if after["fk_attriblist"] not in _ids(session, tags.pk, where):
        raise Bad("Choose a MARC tag from the list.")
    after["nonfiling"] = after.get("nonfiling") or 0
    if after["nonfiling"] > len(after["text"]):
        raise Bad("Nonfiling characters cannot be longer than the text.")
    lang = after.get("fk_langs") or None
    if lang in ("", "undefined"):
        lang = None
    if lang and session.get(_m().Lang, lang) is None:
        raise Bad("That language is not in the catalog.")
    after["fk_langs"] = lang
    return after


def _attr_apply(session, action, before, after):
    row = apply_row(
        session,
        _m().Attribute,
        action,
        after,
        dict((k, after[k]) for k in ("fk_books", "fk_attriblist", "text", "nonfiling", "indicators", "fk_langs"))
        if action != "delete"
        else {},
    )
    tag = after.get("fk_attriblist") if action != "delete" else (before or {}).get("fk_attriblist")
    book = after.get("fk_books") or (before or {}).get("fk_books")
    if book and tag in (240, 245, 246):
        refresh_book_title(session, book)
    return row


Op(
    "attribute",
    form=AttrForm,
    snapshot=snap_pk(c.attribute_row),
    validate=_attr_val,
    apply=_attr_apply,
    compat_sql=lambda a, b, f: (
        None
        if a == "delete" or f.get("fk_attriblist") != 245
        else 'update attributes set  "fk_attriblist" = 245 where pk = %s' % f["pk"]
    ),
)


def add_entity(name, model, pk_name, label_field, form, str_pk=False):
    def snapshot(session, data):
        raw = data.get("pk")
        if raw in (None, ""):
            return None
        bound = cleaned(form, {"pk": raw}, action="delete")
        row = session.get(getattr(_m(), model), bound["pk"])
        return None if row is None else {"pk": getattr(row, pk_name), label_field: getattr(row, label_field)}

    def validate(session, action, data, before):
        if action == "delete":
            _need(before, name)
            return {"pk": data["pk"]}
        exists_state(action, before, name)
        return {"pk": data["pk"], label_field: data.get(label_field) or data.get(name)}

    def apply(session, action, before, after):
        return apply_row(
            session,
            getattr(_m(), model),
            action,
            after,
            {label_field: after[label_field]} if action != "delete" else {},
            pk_name,
        )

    Op(
        name,
        form=form,
        optional_pk=not str_pk,
        snapshot=snapshot,
        validate=validate,
        apply=apply,
    )


add_entity("subject", "Subject", "id", "subject", entity_form("subject"))
add_entity("category", "Category", "pk", "category", entity_form("category"))
add_entity("lang", "Lang", "id", "language", LangForm, str_pk=True)
add_entity(
    "locc",
    "Locc",
    "id",
    "locc",
    entity_form("locc", str_pk=True, regex=LOCC_RE, case="upper"),
    str_pk=True,
)


def _xfer_val(session, action, data, before):
    src, dst, role = data["fk_authors_from"], data["fk_authors_to"], data.get("fk_roles") or "same"
    if src == dst and role in ("", "same"):
        raise Bad("Choose a different author, or a new role.")
    if not c.exists_author(session, src) or not c.exists_author(session, dst):
        raise Bad("Both authors must exist.")
    if not before or not before.get("links"):
        raise Bad("That author has no books to transfer.")
    if role != "same":
        bound = CodeField(ROLE_RE).clean(role)
        if bound not in _ids(session, _m().Role.pk):
            raise Bad("That author role is not in the catalog.")
        role = bound
    return {
        "fk_authors_from": src,
        "fk_authors_to": dst,
        "fk_roles": role,
        "links": before["links"],
    }


def _xfer_apply(session, action, before, after):
    table = _m().BookAuthor.__table__
    values = {"fk_authors": after["fk_authors_to"]}
    if after["fk_roles"] != "same":
        values["fk_roles"] = after["fk_roles"]
    session.execute(table.update().where(table.c.fk_authors == after["fk_authors_from"]).values(**values))
    return after


Op(
    "author_transfer",
    form=XferForm,
    snapshot=lambda s, d: {
        "links": c.author_links(s, int(d["fk_authors_from"])),
        "fk_authors_from": int(d["fk_authors_from"]),
    },
    validate=_xfer_val,
    apply=_xfer_apply,
)
