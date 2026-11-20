"""Django admin: priv-gated mirrors / robot blocks."""

from django.conf import settings
from django.contrib import admin
from django.utils import timezone

from .models import Job, Mirror, RobotBlock, can_manage_infra, can_use_app

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


@admin.register(Job)
class JobAdmin(_ReadOnly):
    list_display = ("id", "created_at", "job_type", "status", "attempts", "claimed_by", "updated_at", "error")
    list_filter = ("status", "job_type")
    search_fields = ("job_type", "claimed_by", "error")
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
