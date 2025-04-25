from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Admin interface
    path("admin/", admin.site.urls),

    # Camera app routes
    path("", include("cameraapp.urls")),

    # Authentication (login/logout)
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
]

# Serve media files (e.g. saved photos/videos) during development
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
