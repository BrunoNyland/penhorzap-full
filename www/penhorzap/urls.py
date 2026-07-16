from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

admin.site.login_template = "admin/login_penhorzap.html"
admin.site.site_header = "penhorzap"

urlpatterns = [
    path("", RedirectView.as_view(url="/painel/", permanent=False)),
    path("admin/", admin.site.urls),
    path("", include("whatsapp.urls")),
    path("api/", include("api.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
