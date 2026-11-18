import inspect
from unittest.mock import patch

from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from . import changes as ch
from .admin import ChangeAdmin
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
from .models import Change, can_manage_infra, can_rollback
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


class ChangeLogTests(TestCase):
    def _row(self, **kwargs):
        data = dict(
            op="book",
            action="create",
            target="book:1",
            before=None,
            after={"pk": 1},
            status=Change.APPLIED,
            actor="neo@localhost",
            applied_by="neo@localhost",
            processed_at=timezone.now(),
        )
        data.update(kwargs)
        row = Change.objects.create(**data)
        row.digest = ch._digest(ch._last_digest(row.id), row)
        row.save(update_fields=["digest"])
        return row

    def test_no_postgres_ddl(self):
        self.assertNotIn("CREATE TABLE", inspect.getsource(ch))

    def test_hmac_digest(self):
        row = self._row()
        self.assertTrue(ch._verify(row))
        row.after = {"pk": 99}
        self.assertFalse(ch._verify(row))

    def test_restore_many_stops(self):
        seen = []

        def fake(_user, pk):
            seen.append(pk)
            if pk == 2:
                raise Bad("mismatch")

        with patch.object(ch, "restore", fake):
            done, failed, err = ch.restore_many(object(), ["1", "2", "3"])
        self.assertEqual((seen, done, failed, err), ([3, 2], [3], 2, "mismatch"))

    def test_restore_toggles_in_place(self):
        from contextlib import contextmanager

        row = self._row(before={"v": 1}, after={"v": 2}, target="thing:1")
        fake = type(
            "Op",
            (),
            {
                "domain": "catalog",
                "name": "thing",
                "live": {"v": 2},
                "snapshot": lambda self, s, d: self.live,
                "live_matches": lambda self, live, want: live == want,
                "invert_change": lambda self, action, before, after: ("update", before),
                "validate": lambda self, s, action, data, before: data,
                "apply": lambda self, s, action, before, after: after,
                "compat_sql": lambda self, action, before, after: None,
            },
        )()
        user = User.objects.create(is_superuser=True, username="undo")

        @contextmanager
        def session():
            yield type("S", (), {"commit": lambda self: None})()

        with (
            patch.object(ch.registry, "get", lambda name: fake),
            patch.object(ch, "can_use_op", lambda u, o: True),
            patch.object(ch.c, "session", session),
        ):
            result, _ = ch.restore(user, row.id)
            self.assertEqual(result, "restored")
            row.refresh_from_db()
            self.assertEqual(row.status, "rolled_back")
            self.assertEqual(row.rolled_back_by, "undo")
            count = Change.objects.count()
            fake.live = {"v": 1}
            result, _ = ch.restore(user, row.id)
            self.assertEqual(result, "reapplied")
            row.refresh_from_db()
            self.assertEqual(row.status, "applied")
            self.assertEqual(Change.objects.count(), count)

    def test_admin_rollback_gated(self):
        from django.contrib import admin as djadmin
        from django.test import RequestFactory

        ma = ChangeAdmin(Change, djadmin.site)
        allowed = User.objects.create(username="ok", email="neo@localhost", is_staff=True, is_superuser=True)
        denied = User.objects.create(username="no", email="other@localhost", is_staff=True)
        self.assertTrue(can_rollback(allowed))
        self.assertFalse(can_rollback(denied))
        self.assertTrue(can_manage_infra(allowed))
        self.assertFalse(can_manage_infra(denied))
        req = RequestFactory().get("/admin/catalog/change/")
        req.user = allowed
        self.assertIn("rollback", ma.get_actions(req))
        req.user = denied
        self.assertNotIn("rollback", ma.get_actions(req))
        self.assertFalse(ma.has_change_permission(req))
