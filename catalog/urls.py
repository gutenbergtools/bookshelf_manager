from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth
from django.http import HttpResponse
from django.urls import path, reverse_lazy
from django_ratelimit.decorators import ratelimit

from . import views

throttle_login = ratelimit(key="ip", rate=settings.RATE_LOGIN, method="POST", block=True)
admin.site.login = throttle_login(admin.site.login)
urlpatterns = [
    path("", views.home, name="home"),
    path("books/", views.books, name="books"),
    path("book/<int:pk>/", views.book_detail, name="book"),
    path("authors/", views.authors, name="authors"),
    path("author/<int:pk>/", views.author_detail, name="author"),
    path("change/propose/", views.change_propose, name="change_propose"),
    path(
        "password/",
        auth.PasswordChangeView.as_view(
            template_name="registration/password.html", success_url=reverse_lazy("password_done")
        ),
        name="password",
    ),
    path(
        "password/done/",
        auth.PasswordChangeDoneView.as_view(template_name="registration/password_done.html"),
        name="password_done",
    ),
    path("login/", throttle_login(views.AllowedLoginView.as_view()), name="login"),
    path("logout/", auth.LogoutView.as_view(), name="logout"),
    path("robots.txt", lambda request: HttpResponse("User-agent: *\nDisallow: /\n", content_type="text/plain")),
    path("%s/" % settings.ADMIN_URL, admin.site.urls),
]
