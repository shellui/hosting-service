from django.contrib import admin

from .models import App, CompanyHostingAccess, Deployment
from .services import delete_app

admin.site.register(CompanyHostingAccess)
admin.site.register(Deployment)


@admin.register(App)
class AppAdmin(admin.ModelAdmin):
    # Same path as the REST API: removes stored artifacts and emits hosting.app.deleted.
    def delete_model(self, request, obj):
        delete_app(obj)

    def delete_queryset(self, request, queryset):
        for app in queryset:
            delete_app(app)
