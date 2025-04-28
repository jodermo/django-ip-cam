# cameraapp/apps.py

from django.apps import AppConfig
import os

class CameraAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cameraapp"

    def ready(self):
        if os.environ.get("RUN_MAIN") != "true":
            print("[CAMERA_APP] Skipping startup logic (not RUN_MAIN).")
        else:
            print("[CAMERA_APP] App ready. CameraInitMiddleware will handle init.")
