"""Django form fields for catalog input. Raise Bad with a user-facing message."""

import re
from datetime import date, datetime
from urllib.parse import urlparse

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

YEAR_MIN, YEAR_MAX = -4000, 2100


class Bad(ValueError):
    pass


class TextField(forms.CharField):
    def validate(self, value):
        super().validate(value)
        if value and "\x00" in value:
            raise ValidationError("Contains invalid characters.")


class FlagField(forms.Field):
    def to_python(self, value):
        if value in (True, 1):
            return 1
        if value in (False, 0, None):
            return 0
        raw = str(value).strip().lower()
        if raw in ("1", "true", "on", "yes"):
            return 1
        if raw in ("0", "false", "off", "no", ""):
            return 0
        raise ValidationError("Must be yes or no.")


class HttpsURLField(forms.URLField):
    default_validators = [URLValidator(schemes=["https"])]

    def clean(self, value):
        value = super().clean(value)
        if not value:
            return ""
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if parsed.username or parsed.password or host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
            raise ValidationError("URL cannot point at a local address.")
        return value


class CodeField(forms.RegexField):
    def __init__(self, regex, case="lower", **kwargs):
        self.case = case
        kwargs.setdefault("max_length", 10)
        if isinstance(regex, str) and not regex.startswith("\\A"):
            regex = r"\A(?:%s)\Z" % regex
        super().__init__(regex, **kwargs)

    def to_python(self, value):
        value = super().to_python(value)
        if not value:
            return value
        return value.upper() if self.case == "upper" else value.lower()


class IndicatorsField(forms.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("max_length", 2)
        super().__init__(**kwargs)

    def clean(self, value):
        raw = "" if value is None else str(value)
        if not raw.strip():
            return "  "
        if not re.fullmatch(r"[0-9a-zA-Z #]{2}", raw):
            raise ValidationError("MARC indicators must be exactly two characters.")
        return raw


LANG_RE = r"[a-z]{2,3}(-[a-z0-9]{2,8})?"
LOCC_RE = r"[A-Z]{1,3}[0-9]{0,4}[A-Z]{0,3}"
ROLE_RE = r"[a-z]{2,3}"


def F(**fields):
    return type("F", (forms.Form,), fields)


ShelfForm = F(
    shelf_pk=forms.IntegerField(min_value=1),
    book_pk=forms.IntegerField(min_value=1),
    want=FlagField(required=False),
)
BookForm = F(
    pk=forms.IntegerField(min_value=1, max_value=99999999),
    title=TextField(max_length=500, required=False),
    release_date=forms.DateField(input_formats=["%Y-%m-%d"], required=False),
    copyrighted=FlagField(required=False),
    updatemode=FlagField(required=False),
)
AliasForm = F(
    pk=forms.IntegerField(min_value=1, required=False),
    fk_authors=forms.IntegerField(min_value=1),
    alias=TextField(max_length=240),
    heading=FlagField(required=False),
)
UrlForm = F(
    pk=forms.IntegerField(min_value=1, required=False),
    fk_authors=forms.IntegerField(min_value=1),
    description=TextField(max_length=240, required=False),
    url=HttpsURLField(max_length=240),
)
AttrForm = F(
    pk=forms.IntegerField(min_value=1, required=False),
    fk_books=forms.IntegerField(min_value=1),
    fk_attriblist=forms.IntegerField(min_value=1),
    text=TextField(max_length=20000),
    nonfiling=forms.IntegerField(min_value=0, max_value=40, required=False),
    indicators=IndicatorsField(),
    fk_langs=CodeField(LANG_RE, required=False),
)
XferForm = F(
    fk_authors_from=forms.IntegerField(min_value=1),
    fk_authors_to=forms.IntegerField(min_value=1),
    fk_roles=TextField(max_length=10, required=False),
)


class AuthorForm(forms.Form):
    pk = forms.IntegerField(min_value=1, required=False)
    author = TextField(max_length=240)
    born_floor = forms.IntegerField(min_value=YEAR_MIN, max_value=YEAR_MAX, required=False)
    born_ceil = forms.IntegerField(min_value=YEAR_MIN, max_value=YEAR_MAX, required=False)
    died_floor = forms.IntegerField(min_value=YEAR_MIN, max_value=YEAR_MAX, required=False)
    died_ceil = forms.IntegerField(min_value=YEAR_MIN, max_value=YEAR_MAX, required=False)
    note = TextField(max_length=10000, required=False)

    def clean(self):
        data = super().clean()
        born = [y for y in (data.get("born_floor"), data.get("born_ceil")) if y is not None]
        died = [y for y in (data.get("died_floor"), data.get("died_ceil")) if y is not None]
        if len(born) == 2 and born[0] > born[1]:
            raise ValidationError("Earliest birth year cannot be after latest birth year.")
        if len(died) == 2 and died[0] > died[1]:
            raise ValidationError("Earliest death year cannot be after latest death year.")
        if born and died and max(born) > min(died):
            raise ValidationError("Birth year cannot be after death year.")
        return data


class BAForm(forms.Form):
    fk_books = forms.IntegerField(min_value=1)
    fk_authors = forms.IntegerField(min_value=1)
    fk_roles = CodeField(ROLE_RE, required=False)
    was_roles = CodeField(ROLE_RE, required=False)
    heading = FlagField(required=False)

    def clean_heading(self):
        raw = self.data.get("heading")
        return 1 if raw in (None, "") else FlagField().clean(raw)

    def clean_fk_roles(self):
        return self.cleaned_data.get("fk_roles") or "cr"


class LangForm(forms.Form):
    pk = CodeField(LANG_RE)
    lang = TextField(max_length=80)

    def clean(self):
        data = super().clean()
        data["language"] = data.get("lang")
        return data


def entity_form(label, max_len=240, str_pk=False, regex=None, case="lower"):
    return F(
        pk=CodeField(regex, case=case) if str_pk else forms.IntegerField(min_value=1),
        **{label: TextField(max_length=max_len)},
    )


def cleaned(form_cls, data, action=None, keep=None, optional_pk=True):
    form = form_cls(data)
    if action == "delete":
        keep = keep or ("pk",)
        for name, field in form.fields.items():
            field.required = name in keep
    elif action == "create" and optional_pk and "pk" in form.fields:
        form.fields["pk"].required = False
    elif action == "update" and "pk" in form.fields:
        form.fields["pk"].required = True
    if not form.is_valid():
        raise Bad(next(err for errs in form.errors.values() for err in errs))
    return form.cleaned_data


def like_pattern(query):
    return str(query or "").strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value
