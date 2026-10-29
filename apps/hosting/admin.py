from django.contrib import admin

from .models import App, CompanyHostingAccess, DeployToken, Deployment
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


@admin.register(DeployToken)
class DeployTokenAdmin(admin.ModelAdmin):
    list_display = ('name', 'prefix', 'app', 'company_id', 'created_at', 'last_used_at', 'expires_at', 'revoked_at')
    readonly_fields = ('prefix', 'token_hash', 'created_at', 'last_used_at')
