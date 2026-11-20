from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from . import ops as registry
from .clean import (
    YEAR_MAX,
    Bad,
    BookForm,
    CodeField,
    FlagField,
    HttpsURLField,
    TextField,
    cleaned,
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


class AdminLogTests(TestCase):
    def test_only_event_log_is_registered(self):
        from django.contrib import admin as djadmin

        from .models import Change, EventLog

        self.assertIn(EventLog, djadmin.site._registry)
        self.assertNotIn(Change, djadmin.site._registry)

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
