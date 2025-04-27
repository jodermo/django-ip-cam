# cameraapp/admin.py

from django.contrib import admin
from .models import Camera, CameraSettings

@admin.register(Camera)
class CameraAdmin(admin.ModelAdmin):
    list_display = ("name", "stream_url", "active")
    list_filter = ("active",)

@admin.register(CameraSettings)
class CameraSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not CameraSettings.objects.exists()