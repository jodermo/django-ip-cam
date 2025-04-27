# cameraapp/apps.py

from django.apps import AppConfig
import os
import threading

class CameraAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cameraapp"

    def ready(self):
        if os.environ.get("RUN_MAIN") != "true":
            return
        from .scheduler import start_photo_scheduler
        from .camera_utils import start_camera_watchdog

        # nur Webcontainer → Starte Watchdog & Scheduler
        if os.environ.get("RUN_TIMELAPSE") == "1":
            threading.Thread(target=start_photo_scheduler, daemon=True).start()
            start_camera_watchdog()
