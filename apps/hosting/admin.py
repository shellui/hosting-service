from django.contrib import admin

from .models import App, CompanyHostingAccess, Deployment

admin.site.register(CompanyHostingAccess)
admin.site.register(App)
admin.site.register(Deployment)
