"""Django admin: changelog (rollback) plus priv-gated mirrors / robot blocks."""

from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from . import changes as ch
from .models import AuditEvent, Change, Mirror, RobotBlock, can_manage_infra, can_rollback, can_use_app

admin.site.site_header = "Catalog Manager"
admin.site.site_title = admin.site.site_header
admin.site.index_title = admin.site.site_header


class _ReadOnly(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)


class _InfraAdmin(admin.ModelAdmin):
    """Mirrors / robots: catalog deployment only, gated by can_manage_infra."""

    def has_module_permission(self, request):
        return settings.CATALOG_APP == "catalog" and can_manage_infra(request.user)

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request)


@admin.register(Change)
class ChangeAdmin(_ReadOnly):
    list_display = ("id", "processed_at", "actor", "op", "action", "target", "status")
    list_filter = ("status", "op", "action", "actor")
    search_fields = ("target", "actor")
    date_hierarchy = "processed_at"
    ordering = ("-id",)
    actions = ("rollback", "reapply")

    def has_change_permission(self, request, obj=None):
        return can_rollback(request.user)

    def has_view_permission(self, request, obj=None):
        return can_use_app(request.user)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not can_rollback(request.user):
            for name in ("rollback", "reapply"):
                actions.pop(name, None)
        return actions

    def _run(self, request, queryset, kind):
        if not can_rollback(request.user):
            raise PermissionDenied
        ids = list(
            queryset.filter(status=Change.APPLIED if kind == "rollback" else Change.ROLLED_BACK).values_list(
                "id", flat=True
            )
        )
        if not ids:
            self.message_user(request, "Nothing to %s." % kind, messages.WARNING)
            return
        done, failed, err = ch.restore_many(request.user, ids)
        if failed is None:
            self.message_user(
                request,
                "%s %s change%s."
                % (
                    "Rolled back" if kind == "rollback" else "Reapplied",
                    len(done),
                    "" if len(done) == 1 else "s",
                ),
                messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                "Changed %s, then stopped at #%s: %s" % (len(done), failed, err),
                messages.ERROR,
            )

    @admin.action(description="Roll back selected changes")
    def rollback(self, request, queryset):
        self._run(request, queryset, "rollback")

    @admin.action(description="Reapply selected changes")
    def reapply(self, request, queryset):
        self._run(request, queryset, "reapply")


@admin.register(AuditEvent)
class AuditEventAdmin(_ReadOnly):
    list_display = ("id", "created_at", "kind", "actor", "op", "action", "target", "change")
    list_filter = ("kind", "op", "actor")
    search_fields = ("target", "actor", "note")
    date_hierarchy = "created_at"
    ordering = ("-id",)

    def has_view_permission(self, request, obj=None):
        return can_use_app(request.user)


@admin.register(Mirror)
class MirrorAdmin(_InfraAdmin):
    list_display = ("id", "provider", "continent", "nation", "location", "url")
    list_filter = ("continent", "nation")
    search_fields = ("provider", "url", "location", "note")
    ordering = ("provider", "id")


@admin.register(RobotBlock)
class RobotBlockAdmin(_InfraAdmin):
    list_display = ("ip", "is_blocked", "is_whitelisted", "country", "org", "expires", "hits", "created")
    list_filter = ("is_blocked", "is_whitelisted", "country")
    search_fields = ("ip", "host", "org", "note", "asn")
    readonly_fields = ("created", "hits", "count")
    fields = (
        "ip",
        "host",
        "is_blocked",
        "is_whitelisted",
        "has_info",
        "expires",
        "org",
        "country",
        "asn",
        "note",
        "created",
        "count",
        "hits",
    )

    def save_model(self, request, obj, form, change):
        if not change and obj.created is None:
            obj.created = timezone.now().replace(tzinfo=None)
        super().save_model(request, obj, form, change)
