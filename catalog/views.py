import re
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from . import catalog as c
from . import changes as ch
from .clean import Bad
from .models import can_use_app


def _num(raw, default):
    return int(raw) if re.fullmatch(r"[+-]?\d+", str(raw).strip()) else default


def _page_number(request, key="page"):
    return max(1, _num(request.GET.get(key) or 1, 1))


def _pager_context(total, page, size=None, qs="", param="page"):
    size = size or settings.PAGE_SIZE
    pages = max(1, -(-total // size))
    page = min(max(1, page), pages)
    return {
        "page": page,
        "pages": pages,
        "total": total,
        "previous": page - 1,
        "next": page + 1,
        "has_previous": page > 1,
        "has_next": page < pages,
        "qs": qs,
        "param": param,
    }


def _qs(request, *drop):
    query = request.GET.copy()
    for key in drop:
        query.pop(key, None)
    return query.urlencode()


def _paged_rows(fetch, page, qs="", param="page", size=None):
    rows, total = fetch(page)
    pager = _pager_context(total, page, size=size, qs=qs, param=param)
    if pager["page"] != page:
        rows, total = fetch(pager["page"])
        pager = _pager_context(total, pager["page"], size=size, qs=qs, param=param)
    return rows, pager


def _hits(request, fetch, term, key, size):
    """Search result block: an empty term yields no rows and an empty pager."""
    qs = _qs(request, key)
    if not term:
        return [], _pager_context(0, 1, size=size, qs=qs, param=key)
    return _paged_rows(lambda p: fetch(term, p, size), _page_number(request, key), qs, key, size=size)


def _back(request, fallback):
    target = request.POST.get("next") or request.GET.get("next") or ""
    return (
        target
        if target and url_has_allowed_host_and_scheme(target, {request.get_host()}, request.is_secure())
        else fallback
    )


def _or404(value, message):
    if value is None:
        raise Http404(message)
    return value


def catalog_guard(request):
    if settings.CATALOG_APP != "catalog":
        raise Http404()


def _cat(view):
    def guarded(request, *args, **kwargs):
        catalog_guard(request)
        # Login already checks this, but an old session must not keep read
        # access after the user is removed from the cataloger list.
        if not can_use_app(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return login_required(guarded)


def _shelf(pk):
    return _or404(c.shelf(pk), "No such bookshelf.")


BOOK_SORTS = [
    ("newest", "Newest ebook"),
    ("oldest", "Oldest ebook"),
    ("downloads", "Most downloaded"),
    ("title", "Title A–Z"),
]
AUTHOR_SORTS = [
    ("name", "Name A–Z"),
    ("newest", "Newest added"),
    ("downloads", "Most downloaded"),
]
SHELF_SORTS = [
    ("name", "Name A–Z"),
    ("newest", "Newest added"),
    ("books", "Most books"),
    ("downloads", "Most downloads"),
]
ENTITY_SORTS = {
    "subject": [("name", "Name A–Z"), ("newest", "Newest added"), ("books", "Most books")],
    "category": [("name", "Name A–Z"), ("newest", "Newest added"), ("books", "Most books")],
    "lang": [("name", "Language A–Z"), ("code", "Code A–Z"), ("books", "Most books")],
    "locc": [("name", "Class name A–Z"), ("code", "Code A–Z"), ("books", "Most books")],
}


def _listing(request, fetch, template, key, extra=None, sorts=None):
    query = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "").strip()
    rows, pager = _paged_rows(lambda p: fetch(query, p, sort), _page_number(request), _qs(request, "page"))
    context = {key: rows, "q": query, "sort": sort, "sorts": sorts or [], "pager": pager}
    context.update(extra or {})
    return render(request, template, context)


class AllowedLoginView(auth.LoginView):
    template_name = "registration/login.html"
    form_valid = lambda self, form: (
        auth.LoginView.form_valid(self, form)
        if can_use_app(form.get_user())
        else (form.add_error(None, "This account cannot use this site."), self.form_invalid(form))[1]
    )


def home(request):
    return redirect("books") if settings.CATALOG_APP == "catalog" else shelf_list(request)


def shelf_list(request):
    return _listing(request, lambda q, p, sort: c.shelves(q, p, sort=sort), "shelves.html", "shelves", sorts=SHELF_SORTS)


def shelf_detail(request, pk):
    shelf = _shelf(pk)
    query = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "").strip()
    books, pager = _paged_rows(lambda p: c.shelf_books(pk, query, p, sort=sort), _page_number(request), _qs(request, "page"))
    aq = request.GET.get("aq", "").strip()
    candidates, apager = (
        _paged_rows(lambda p: c.search_books(aq, p), _page_number(request, "apage"), _qs(request, "apage"), "apage")
        if aq
        else ([], _pager_context(0, 1, qs=_qs(request, "apage"), param="apage"))
    )
    live = c.members(pk, [book["pk"] for book in candidates]) if aq else set()
    for book in candidates:
        book["on_shelf"] = book["pk"] in live
    return render(
        request,
        "shelf.html",
        {
            "shelf": shelf,
            "books": books,
            "q": query,
            "sort": sort,
            "sorts": BOOK_SORTS,
            "pager": pager,
            "aq": aq,
            "apage": apager["page"],
            "candidates": candidates,
            "apager": apager,
        },
    )


_MESSAGES = {"applied": "Saved.", "same": "Nothing to change."}


def _flash(request, result):
    (messages.info if result == "same" else messages.success)(request, _MESSAGES[result])


def change_propose(request):
    fallback = _back(request, reverse("home"))
    op_name = request.POST.get("op", "")
    action = request.POST.get("action", "")
    try:
        result, after = ch.commit(request.user, op_name, action, request.POST)
        pk = after.get("pk") if result == "applied" and op_name == "book" and action == "create" else None
        fallback = reverse("book", args=[pk]) if pk else fallback
        _flash(request, result)
    except Bad as exc:
        messages.error(request, str(exc))
    return redirect(fallback)


def books(request):
    return _listing(
        request,
        lambda q, p, sort: c.search_books(q, p, sort=sort) if q else c.recent_books(p, sort=sort),
        "books.html",
        "books",
        sorts=BOOK_SORTS,
    )


def book_detail(request, pk):
    data = _or404(c.book_page(pk), "No such ebook.")
    aq, sq = request.GET.get("aq", "").strip(), request.GET.get("sq", "").strip()
    hit = getattr(settings, "HIT_PAGE_SIZE", 8)
    author_hits, apager = _hits(request, c.search_authors, aq, "apage", hit)
    subject_hits, spager = _hits(request, c.search_subjects, sq, "spage", hit)
    data.update(
        lookups=c.lookups(),
        aq=aq,
        sq=sq,
        author_hits=author_hits,
        subject_hits=subject_hits,
        apager=apager,
        spager=spager,
        clear_author_qs=_qs(request, "aq", "apage"),
        clear_subject_qs=_qs(request, "sq", "spage"),
    )
    return render(request, "book.html", data)


def authors(request):
    return _listing(
        request,
        lambda q, p, sort: c.search_authors(q, p, sort=sort),
        "authors.html",
        "authors",
        sorts=AUTHOR_SORTS,
    )


def _etexts(*values):
    return list(dict.fromkeys(int(part) for raw in values for part in re.findall(r"\d+", str(raw or "")) if int(part)))


def _commit_many(request, op, action, payloads):
    applied, errors = 0, []
    for payload in payloads:
        try:
            result, _after = ch.commit(request.user, op, action, payload)
            applied += result == "applied"
        except Bad as exc:
            errors.append(str(exc))
    if applied:
        messages.success(request, "Saved." if applied == 1 else "Saved %s changes." % applied)
    elif not errors:
        messages.info(request, _MESSAGES["same"])
    for err in errors[:8]:
        messages.error(request, err)
    return applied, errors


def author_detail(request, pk):
    data = _or404(c.author_page(pk), "No such author.")
    tq = request.GET.get("tq", "").strip()
    bq = request.GET.get("bq", "").strip()
    hit = getattr(settings, "HIT_PAGE_SIZE", 8)
    book_hits, bpager = _hits(request, c.search_books, bq, "bpage", hit)
    rows, tpager = _hits(request, c.search_authors, tq, "tpage", hit)
    targets = [row for row in rows if row["pk"] != pk]
    data.update(
        lookups=c.lookups(),
        tq=tq,
        bq=bq,
        targets=targets,
        book_hits=book_hits,
        bpager=bpager,
        tpager=tpager,
    )
    return render(request, "author.html", data)


def author_books_change(request, pk):
    fallback = reverse("author", args=[pk])
    action = request.POST.get("action")
    if action not in ("link", "unlink"):
        messages.error(request, "That is not a valid action.")
        return redirect(fallback)
    if action == "unlink":
        payloads = [
            {"fk_books": book, "fk_authors": str(pk), "fk_roles": role}
            for item in request.POST.getlist("link")
            if ":" in item
            for book, role in [item.rsplit(":", 1)]
        ]
    else:
        ids = _etexts(request.POST.get("book_pks", ""), *request.POST.getlist("fk_books"))
        role = request.POST.get("fk_roles") or "cr"
        heading = request.POST.get("heading") or "1"
        payloads = [
            {"fk_books": str(book), "fk_authors": str(pk), "fk_roles": role, "heading": heading} for book in ids
        ]
    if not payloads:
        messages.error(request, "Enter at least one ebook number.")
        return redirect(fallback)
    _commit_many(request, "book_author", action, payloads)
    return redirect(fallback)


_ENTITY = {
    "subject": {
        "title": "Subjects",
        "kind": "Subject",
        "model": "Subject",
        "key": "subject",
        "pk_attr": "id",
        "label_attr": "subject",
        "search": c.search_subjects,
        "fields": [("subject", "Subject", "text", 240)],
        "list_name": "subjects",
        "detail_name": "subject",
        "list_path": "/subjects/",
    },
    "category": {
        "title": "Categories",
        "kind": "Category",
        "model": "Category",
        "key": "category",
        "pk_attr": "pk",
        "label_attr": "category",
        "search": c.search_categories,
        "fields": [("category", "Category", "text", 240)],
        "list_name": "categories",
        "detail_name": "category",
        "list_path": "/categories/",
    },
    "lang": {
        "title": "Languages",
        "kind": "Language",
        "model": "Lang",
        "key": "language",
        "pk_attr": "id",
        "label_attr": "language",
        "search": c.search_langs,
        "str_pk": True,
        "fields": [("pk", "Code", "text", 10), ("lang", "Language", "text", 80)],
        "list_name": "langs",
        "detail_name": "lang",
        "list_path": "/languages/",
    },
    "locc": {
        "title": "LoC Classes",
        "kind": "LoC Class",
        "model": "Locc",
        "key": "locc",
        "pk_attr": "id",
        "label_attr": "locc",
        "search": c.search_loccs,
        "str_pk": True,
        "fields": [("pk", "Code", "text", 10), ("locc", "Class name", "text", 240)],
        "list_name": "loccs",
        "detail_name": "locc",
        "list_path": "/loccs/",
    },
}


def entity(request, name, pk=None):
    meta = _ENTITY[name]
    context = {
        "title": meta["title"],
        "op": name,
        "kind": meta["kind"],
        "fields": meta["fields"],
        "detail": meta["detail_name"],
        "list_url": meta["list_name"],
        "list_path": meta["list_path"],
        "str_pk": meta.get("str_pk", False),
    }
    if pk is None:
        return _listing(
            request,
            lambda q, p, sort: meta["search"](q, p, sort=sort),
            "entities.html",
            "rows",
            context,
            sorts=ENTITY_SORTS[name],
        )
    context.update(
        kind=meta["kind"],
        row=_or404(
            c.simple_entity(meta["model"], meta["pk_attr"], meta["label_attr"], pk, meta.get("str_pk", False)),
            "No such %s." % meta["kind"].lower(),
        ),
    )
    return render(request, "entity.html", context)


def reports(request):
    show = request.GET.get("show", "lacking")
    show = show if show in ("lacking", "empty", "marc") else "lacking"
    days = max(0, min(_num(request.GET.get("days") or 0, 0), 3650))
    attribute = request.GET.get("attribute", "").strip()
    context = {
        "show": show,
        "days": days,
        "attribute": attribute,
        "uses": [],
        "usage": [],
        "rows": [],
        "pager": _pager_context(0, 1),
        "marc_name": "",
    }
    if show == "empty":
        qs = urlencode({"show": "empty"})
        context["rows"], context["pager"] = _paged_rows(lambda p: c.empty_authors(p), _page_number(request), qs)
    elif show == "marc":
        context["usage"] = c.attrib_usage()
        if attribute.isdigit():
            context["marc_name"] = c.attrib_name(int(attribute)) or ""
        if context["marc_name"]:
            qs = urlencode({"show": "marc", "attribute": attribute})
            context["uses"], context["pager"] = _paged_rows(lambda p: c.attrib_uses(int(attribute), p), _page_number(request), qs)
    else:
        qs = urlencode({"show": "lacking", "days": days})
        context["rows"], context["pager"] = _paged_rows(lambda p: c.lacking_subject_locc(p, days), _page_number(request), qs)
    return render(request, "reports.html", context)


home = login_required(home)
shelf_list = login_required(shelf_list)
shelf_detail = login_required(shelf_detail)
_throttled = lambda f: _cat(require_POST(ratelimit(key="user", rate=settings.RATE_POST, method="POST", block=True)(f)))
change_propose = login_required(
    require_POST(ratelimit(key="user", rate=settings.RATE_POST, method="POST", block=True)(change_propose))
)
author_books_change = _throttled(author_books_change)
books, book_detail, authors, author_detail, entity, reports = map(
    _cat, (books, book_detail, authors, author_detail, entity, reports)
)
