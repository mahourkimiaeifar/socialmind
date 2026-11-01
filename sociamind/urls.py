from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "مدیریت Socia Mind"
admin.site.site_title = "Socia Mind"
admin.site.index_title = "داشبورد مدیریت"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
]

handler404 = "core.views.not_found"
handler500 = "core.views.server_error"
