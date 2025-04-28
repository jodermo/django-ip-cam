# cameraapp/apps.py

import os
import threading
from django.apps import AppConfig
from .globals import app_globals

class CameraAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cameraapp"

    def ready(self):
        if os.environ.get("RUN_MAIN") != "true":
            print("[CAMERA_APP] Skipping startup logic (not RUN_MAIN).")
            return

        print("[CAMERA_APP] App ready. CameraInitMiddleware will handle init.")

        # Starte Watchdog sofort
        try:
            from .camera_utils import start_camera_watchdog
            start_camera_watchdog()
            print("[CAMERA_APP] Watchdog gestartet.")
        except Exception as e:
            print(f"[CAMERA_APP] Watchdog Fehler: {e}")

        # Starte Timelapse sofort
        if os.environ.get("RUN_TIMELAPSE", "1") == "1":
            try:
                from .scheduler import start_photo_scheduler
                thread = threading.Thread(target=start_photo_scheduler, daemon=True)
                thread.start()
                app_globals.photo_scheduler_thread = thread
                print("[CAMERA_APP] Timelapse-Scheduler gestartet.")
            except Exception as e:
                print(f"[CAMERA_APP] Timelapse Fehler: {e}")
