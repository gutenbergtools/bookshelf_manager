from django.contrib import admin

from .models import Change


@admin.register(Change)
class BookshelfChangeAdmin(admin.ModelAdmin):
    list_display = ('id', 'kind', 'book_pk', 'shelf_pk', 'status',
                    'created_at', 'processed_at')
    list_filter = ('status', 'kind')
    search_fields = ('book_pk', 'shelf_pk')
    ordering = ('-id',)
    readonly_fields = ('kind', 'shelf_pk', 'book_pk', 'status',
                       'created_at', 'processed_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
