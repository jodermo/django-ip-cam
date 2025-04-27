from django.apps import AppConfig
import os
import threading

class CameraAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cameraapp"

    def ready(self):
        run_timelapse = os.environ.get("RUN_TIMELAPSE", "1") == "1"
        print(f"[CAMERA_APP] App ready. RUN_TIMELAPSE = {run_timelapse}")

        try:
            from .scheduler import start_photo_scheduler
            from .camera_utils import start_camera_watchdog

            if run_timelapse:
                print("[CAMERA_APP] Starting timelapse scheduler thread...")
                threading.Thread(target=start_photo_scheduler, daemon=True).start()

            print("[CAMERA_APP] Starting camera watchdog...")
            start_camera_watchdog()
        except Exception as e:
            print(f"[CAMERA_APP] Failed to start scheduler/watchdog: {e}")


