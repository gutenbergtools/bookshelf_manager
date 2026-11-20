from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from . import ops as registry
from .clean import (
    LOCC_RE,
    YEAR_MAX,
    AttrForm,
    AuthorForm,
    BAForm,
    Bad,
    BookForm,
    CodeField,
    FlagField,
    HttpsURLField,
    LangForm,
    TextField,
    cleaned,
    entity_form,
)
from .models import can_manage_infra
from .views import _etexts


class _Num(forms.Form):
    n = forms.IntegerField(min_value=1)


class _Year(forms.Form):
    born = forms.IntegerField(min_value=-4000, max_value=YEAR_MAX, required=False)


class CleanTests(SimpleTestCase):
    def test_integer(self):
        self.assertEqual(cleaned(_Num, {"n": "12"})["n"], 12)
        self.assertRaises(Bad, cleaned, _Num, {"n": "x"})
        self.assertRaises(Bad, cleaned, _Num, {"n": "0"})

    def test_text_and_year(self):
        self.assertEqual(TextField(max_length=240).clean("  Brontë  "), "Brontë")
        self.assertEqual(cleaned(_Year, {"born": ""})["born"], None)
        self.assertRaises(Bad, cleaned, _Year, {"born": "3000"})

    def test_book_release_date_optional(self):
        data = cleaned(BookForm, {"pk": "12345", "copyrighted": "", "updatemode": ""})
        self.assertIsNone(data["release_date"])
        self.assertEqual(data["copyrighted"], 0)
        self.assertEqual(data["updatemode"], 0)

    def test_etext_list(self):
        self.assertEqual(_etexts("12345, 12346 12345"), [12345, 12346])
        self.assertEqual(_etexts(""), [])

    def test_flag_date_lang(self):
        regex = r"[a-z]{2,3}(-[a-z0-9]{2,8})?"
        self.assertEqual(FlagField().clean("on"), 1)
        self.assertEqual(FlagField().clean(""), 0)
        self.assertEqual(CodeField(regex).clean("EN"), "en")
        self.assertRaises(ValidationError, CodeField(regex).clean, "english")

    def test_https_url(self):
        self.assertTrue(HttpsURLField().clean("https://www.gutenberg.org/ebooks/1"))
        self.assertRaises(ValidationError, HttpsURLField().clean, "http://example.org")
        self.assertRaises(ValidationError, HttpsURLField().clean, "https://localhost/x")


class AdminTests(TestCase):
    def test_infra_gate(self):
        allowed = User.objects.create(username="ok", email="neo@localhost", is_staff=True, is_superuser=True)
        denied = User.objects.create(username="no", email="other@localhost", is_staff=True)
        self.assertTrue(can_manage_infra(allowed))
        self.assertFalse(can_manage_infra(denied))


class _ExistsSession:
    """Fake SQLAlchemy session: every pk exists, roles are cr/aut."""

    def get(self, model, pk):
        return object()

    def scalars(self, stmt):
        return self

    def all(self):
        return ["cr", "aut"]


class GuardTests(SimpleTestCase):
    """Duplicate links and duplicate entities must be denied, like the original catalog admin."""

    def test_duplicate_links_denied(self):
        session = _ExistsSession()
        for name, payload in (
            ("book_subject", {"fk_books": "58890", "fk_subjects": "61"}),
            ("book_lang", {"fk_books": "58890", "fk_langs": "en"}),
            ("book_locc", {"fk_books": "58890", "fk_loccs": "PR"}),
            ("book_category", {"fk_books": "58890", "fk_categories": "9"}),
        ):
            with self.assertRaises(Bad):
                registry.get(name).validate(session, "link", payload, payload)
        with self.assertRaises(Bad):
            registry.get("book_author").validate(
                session,
                "link",
                {"fk_books": "58890", "fk_authors": "30", "fk_roles": "cr", "heading": "1"},
                {"fk_books": 58890, "fk_authors": 30, "fk_roles": "cr", "heading": 1},
            )

    def test_duplicate_entities_denied(self):
        session = _ExistsSession()
        for name, payload in (
            ("subject", {"pk": "61", "subject": "Fantasy fiction"}),
            ("category", {"pk": "9", "category": "Drama"}),
            ("lang", {"pk": "en", "lang": "English"}),
            ("locc", {"pk": "PR", "locc": "English literature"}),
            ("author", {"pk": "30", "author": "Carroll, Lewis", "note": ""}),
        ):
            with self.assertRaises(Bad):
                registry.get(name).validate(session, "create", payload, {"pk": payload["pk"]})


class _MutableRow:
    pass


class _ScalarResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _RecordingSession:
    """Captures executed SQL; session.get() returns a settable row or None."""

    def __init__(self, exists=True, scalar_values=(240, 245, 246), rowcount=1, scalar_value=0, missing=()):
        self.executed = []
        self.added = []
        self.exists = exists
        self.scalar_values = list(scalar_values)
        self.rowcount = rowcount
        self.scalar_value = scalar_value
        self.missing = set(missing)

    def execute(self, stmt, *args, **kwargs):
        self.executed.append(str(stmt))
        return self

    def add(self, obj):
        self.added.append(obj)

    def get(self, model, pk):
        if model.__name__ in self.missing:
            return None
        return _MutableRow() if self.exists else None

    def flush(self):
        pass

    def scalar(self, stmt):
        return self.scalar_value

    def scalars(self, stmt):
        return _ScalarResult(self.scalar_values)


class ApplyTests(SimpleTestCase):
    """Apply functions must emit the SQL that actually changes the catalog."""

    def _sql(self, session):
        return "\n".join(session.executed)

    def test_book_title_update_writes_marc_245_and_refreshes(self):
        s = _RecordingSession()
        before = {"pk": 1342, "title": "Old"}
        after = {"pk": 1342, "title": "New", "release_date": "1813-01-28", "copyrighted": 0, "updatemode": 0}
        registry._book_apply(s, "update", before, after)
        sql = self._sql(s)
        self.assertIn("update attributes set text", sql)
        self.assertIn("update books set title", sql)

    def test_book_title_unchanged_skips_marc_write(self):
        s = _RecordingSession()
        before = {"pk": 1342, "title": "Same"}
        after = {"pk": 1342, "title": "Same", "release_date": "1813-01-28", "copyrighted": 0, "updatemode": 0}
        registry._book_apply(s, "update", before, after)
        self.assertNotIn("update attributes set text", self._sql(s))

    def test_attribute_245_update_refreshes_title(self):
        s = _RecordingSession()
        after = {"pk": 9, "fk_books": 1342, "fk_attriblist": 245, "text": "New", "nonfiling": 0, "indicators": "  ", "fk_langs": None}
        registry._attr_apply(s, "update", None, after)
        self.assertIn("update books set title", self._sql(s))

    def test_link_apply_inserts_and_deletes(self):
        table = registry._m().t_mn_books_langs
        insert_s = _RecordingSession()
        registry.link_apply(insert_s, table, True, {"fk_books": 1, "fk_langs": "en"})
        self.assertIn("INSERT", insert_s.executed[0].upper())
        delete_s = _RecordingSession()
        registry.link_apply(delete_s, table, False, {"fk_books": 1, "fk_langs": "en"})
        self.assertIn("DELETE", delete_s.executed[0].upper())

    def test_author_transfer_updates_links(self):
        s = _RecordingSession()
        registry._xfer_apply(s, "update", None, {"fk_authors_from": 30, "fk_authors_to": 40, "fk_roles": "same"})
        self.assertIn("UPDATE", self._sql(s).upper())

    def test_author_delete_removes_children(self):
        s = _RecordingSession()
        registry._author_apply(s, "delete", None, {"pk": 30})
        self.assertEqual(self._sql(s).count("DELETE"), 3)


class ValidationTests(SimpleTestCase):
    def test_book_requires_title(self):
        s = _RecordingSession()
        data = {"pk": "1342", "title": "", "release_date": "1813-01-28", "copyrighted": "0", "updatemode": "0"}
        with self.assertRaises(Bad):
            registry.get("book").validate(s, "update", data, {"pk": 1342, "title": "Old"})

    def test_transfer_requires_different_author(self):
        s = _RecordingSession()
        data = {"fk_authors_from": "30", "fk_authors_to": "30", "fk_roles": "same"}
        with self.assertRaises(Bad):
            registry.get("author_transfer").validate(s, "update", data, {"links": [{"fk_books": 1}]})


class BadDataTests(SimpleTestCase):
    """Malformed input the catalog must reject: dates, codes, years, indicators."""

    def test_bad_release_date(self):
        with self.assertRaises(Bad):
            cleaned(BookForm, {"pk": "1342", "title": "X", "release_date": "not-a-date"})

    def test_bad_language_code(self):
        with self.assertRaises(Bad):
            cleaned(LangForm, {"pk": "English", "lang": "English"})

    def test_bad_role_code(self):
        with self.assertRaises(Bad):
            cleaned(BAForm, {"fk_books": "1", "fk_authors": "1", "fk_roles": "author"})

    def test_bad_locc_code(self):
        form = entity_form("locc", str_pk=True, regex=LOCC_RE, case="upper")
        with self.assertRaises(Bad):
            cleaned(form, {"pk": "english literature", "locc": "x"})

    def test_indicators_must_be_two_chars(self):
        with self.assertRaises(Bad):
            cleaned(AttrForm, {"fk_books": "1", "fk_attriblist": "245", "text": "x", "indicators": "A"})

    def test_author_year_out_of_range(self):
        with self.assertRaises(Bad):
            cleaned(AuthorForm, {"pk": "1", "author": "X", "born_floor": "5000"})

    def test_empty_author_name(self):
        with self.assertRaises(Bad):
            cleaned(AuthorForm, {"pk": "1", "author": ""})

    def test_nonfiling_longer_than_text(self):
        s = _RecordingSession()
        data = {"pk": "1", "fk_books": "1342", "fk_attriblist": "245", "text": "Hi", "nonfiling": "5", "indicators": "  "}
        with self.assertRaises(Bad):
            registry.get("attribute").validate(s, "update", data, {"pk": 1, "fk_books": 1342, "fk_attriblist": 245})

    def test_birth_after_death(self):
        with self.assertRaises(Bad):
            cleaned(AuthorForm, {"pk": "1", "author": "X", "born_floor": "1900", "died_floor": "1800"})

    def test_born_floor_after_ceil(self):
        with self.assertRaises(Bad):
            cleaned(AuthorForm, {"pk": "1", "author": "X", "born_floor": "1900", "born_ceil": "1800"})

    def test_null_byte_in_text(self):
        with self.assertRaises(Bad):
            cleaned(AuthorForm, {"pk": "1", "author": "Bad\x00Name"})

    def test_book_delete_forbidden(self):
        with self.assertRaises(Bad):
            registry.get("book").validate(_RecordingSession(), "delete", {"pk": "1342"}, {"pk": 1342})

    def test_link_missing_book(self):
        with self.assertRaises(Bad):
            registry.get("book_subject").validate(_RecordingSession(exists=False), "link", {"fk_books": "1", "fk_subjects": "61"}, None)

    def test_link_missing_subject(self):
        with self.assertRaises(Bad):
            registry.get("book_subject").validate(_RecordingSession(missing=("Subject",)), "link", {"fk_books": "1", "fk_subjects": "61"}, None)

    def test_book_author_unknown_role(self):
        s = _RecordingSession(scalar_values=("aut", "edt"))
        with self.assertRaises(Bad):
            registry.get("book_author").validate(s, "link", {"fk_books": "1", "fk_authors": "30", "fk_roles": "zz", "heading": "1"}, None)

    def test_author_delete_with_books(self):
        with self.assertRaises(Bad):
            registry.get("author").validate(_RecordingSession(scalar_value=3), "delete", {"pk": "30"}, {"pk": 30})

    def test_unknown_op(self):
        with self.assertRaises(Bad):
            registry.get("does_not_exist")

    def test_commit_unknown_op(self):
        from . import changes as ch

        with self.assertRaises(Bad):
            ch.commit(None, "not-an-op", "update", {})

    def test_commit_unknown_action(self):
        from . import changes as ch

        with self.assertRaises(Bad):
            ch.commit(None, "book", "not-an-action", {})


class HeaderTests(SimpleTestCase):
    """Every response carries the CSP and Permissions-Policy headers (OWASP baseline)."""

    def test_security_headers(self):
        response = self.client.get("/login/")
        csp = response["Content-Security-Policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("base-uri 'self'", csp)
        self.assertIn("form-action 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(response["Permissions-Policy"], "camera=(), microphone=(), geolocation=()")
