# cameraapp/admin.py
from django.contrib import admin
from .models import Camera

@admin.register(Camera)
class CameraAdmin(admin.ModelAdmin):
    list_display = ("name", "stream_url", "active")
    list_filter = ("active",)
