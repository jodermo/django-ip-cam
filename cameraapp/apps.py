import os
import threading
from django.apps import AppConfig

class CameraAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cameraapp"

    def ready(self):
        if os.environ.get("RUN_MAIN") != "true":
            print("[CAMERA_APP] Skipping startup logic (not RUN_MAIN).")
            return

        run_timelapse = os.environ.get("RUN_TIMELAPSE", "1") == "1"
        print(f"[CAMERA_APP] App ready. RUN_TIMELAPSE = {run_timelapse}")

        try:
            from .camera_core import init_camera
            from .camera_utils import start_camera_watchdog
            print("[CAMERA_APP] Initializing camera...")
            init_camera()
            print("[CAMERA_APP] Camera init done.")
        except Exception as e:
            print(f"[CAMERA_APP] Error during initial camera init: {e}")

        try:
            print("[CAMERA_APP] Starting camera watchdog...")
            from .camera_utils import start_camera_watchdog
            start_camera_watchdog()
        except Exception as e:
            print(f"[CAMERA_APP] Failed to start camera watchdog: {e}")

        if run_timelapse:
            try:
                from .scheduler import start_photo_scheduler
                print("[CAMERA_APP] Starting timelapse scheduler thread...")
                threading.Thread(target=start_photo_scheduler, daemon=True).start()
            except Exception as e:
                print(f"[CAMERA_APP] Failed to start photo scheduler: {e}")

