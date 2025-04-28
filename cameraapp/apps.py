from django.apps import AppConfig
import os
import threading

class CameraAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cameraapp"

    def ready(self):
        if os.environ.get("RUN_MAIN") != "true":
            print("[CAMERA_APP] Skipping startup logic (not RUN_MAIN).")
            return

        print("[CAMERA_APP] App ready. Starting scheduler and watchdog...")

        try:
            from .camera_utils import start_camera_watchdog
            start_camera_watchdog()
            print("[CAMERA_APP] Watchdog gestartet.")
        except Exception as e:
            print(f"[CAMERA_APP] Fehler beim Start des Watchdogs: {e}")

        try:
            from .scheduler import start_photo_scheduler
            import cameraapp.globals as app_globals

            thread = threading.Thread(target=start_photo_scheduler, daemon=True)
            thread.start()
            app_globals.app_globals.photo_scheduler_thread = thread
            print("[CAMERA_APP] Timelapse-Scheduler gestartet.")
        except Exception as e:
            print(f"[CAMERA_APP] Fehler beim Start des Timelapse-Schedulers: {e}")
