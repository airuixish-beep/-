from django.contrib import admin

from .models import SiteConfig

admin.site.site_header = "XUANOR 后台管理"
admin.site.site_title = "XUANOR 管理后台"
admin.site.index_title = "后台首页"


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    list_display = ("site_name", "contact_email", "updated_at")
