from django import forms
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .clean import YEAR_MAX, Bad, BookForm, CodeField, FlagField, TextField, cleaned


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

    def test_flag_and_code(self):
        self.assertEqual(FlagField().clean("on"), 1)
        self.assertEqual(FlagField().clean(""), 0)
        self.assertEqual(CodeField(r"[a-z]{2,3}").clean("EN"), "en")
        self.assertRaises(ValidationError, CodeField(r"[a-z]{2,3}").clean, "english")


class HeaderTests(SimpleTestCase):
    def test_security_headers(self):
        response = self.client.get("/login/")
        csp = response["Content-Security-Policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(response["Permissions-Policy"], "camera=(), microphone=(), geolocation=()")
