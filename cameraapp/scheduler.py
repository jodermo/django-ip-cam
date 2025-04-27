import os
import time
import cv2
from datetime import datetime
import numpy as np
from django.conf import settings
from django.db import connections

from .camera_utils import try_open_camera, apply_cv_settings, get_camera_settings
from .livestream_job import LiveStreamJob
from .globals import latest_frame, latest_frame_lock


PHOTO_DIR = os.path.join(settings.MEDIA_ROOT, "photos")
os.makedirs(PHOTO_DIR, exist_ok=True)


def take_photo():
    # Try saving a shared live frame
    with latest_frame_lock:
        if latest_frame is not None:
            frame = latest_frame.copy()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(PHOTO_DIR, f"photo_{timestamp}.jpg")
            if cv2.imwrite(filepath, frame):
                print(f"[PHOTO] Saved from stream: {filepath}")
                return True
            else:
                print("[PHOTO] Failed to save shared frame.")
                return False

    # Fallback: capture a fresh photo
    try:
        cap = cv2.VideoCapture(int(os.getenv("CAMERA_URL", "0")))
        if not cap.isOpened():
            print("[PHOTO] Fallback camera not available.")
            return False

        settings = get_camera_settings()
        apply_cv_settings(cap, settings, mode="photo")

        ret, frame = cap.read()
        cap.release()

        if ret and frame is not None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(PHOTO_DIR, f"photo_{timestamp}.jpg")
            if cv2.imwrite(filepath, frame):
                print(f"[PHOTO] Saved from fallback: {filepath}")

                # Restart livestream if it was running
                if livestream_job and livestream_job.running:
                    livestream_job.stop()
                    livestream_job.join(timeout=2.0)

                time.sleep(1.0)
                new_cap = try_open_camera(int(os.getenv("CAMERA_URL", "0")), retries=3, delay=1.0)
                if new_cap and new_cap.isOpened():
                    apply_cv_settings(new_cap, settings, mode="video")
                    new_job = LiveStreamJob(
                        int(os.getenv("CAMERA_URL", "0")),
                        frame_callback=lambda f: setattr(app_globals, "latest_frame", f.copy()),
                        shared_capture=new_cap
                    )
                    new_job.start()
                    livestream_job = new_job
                    print("[PHOTO] Livestream restarted successfully.")
                else:
                    print("[PHOTO] Livestream restart failed.")
                return True

    except Exception as e:
        print(f"[PHOTO] Exception: {e}")
    return False


def wait_for_table(table_name, db_alias="default", timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with connections[db_alias].cursor() as cursor:
                cursor.execute(f"SELECT 1 FROM {table_name} LIMIT 1")
            return
        except Exception:
            time.sleep(1)
    print(f"[ERROR] Timeout: Table '{table_name}' not found after {timeout}s.")


def start_photo_scheduler():
    print("[SCHEDULER] Starting timelapse scheduler...")
    wait_for_table("cameraapp_camerasettings")

    while True:
        settings_obj = get_camera_settings()
        if settings_obj and settings_obj.timelapse_enabled:
            take_photo()
            interval_min = settings_obj.photo_interval_min
        else:
            interval_min = 15
        time.sleep(interval_min * 60)
