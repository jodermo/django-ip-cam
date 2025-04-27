# cameraapp/sheduler.py

import os
import time
import cv2
from datetime import datetime
import numpy as np
from django.conf import settings
from django.db import connections

from .camera_utils import try_open_camera, apply_cv_settings, get_camera_settings
from .livestream_job import LiveStreamJob
from .globals import latest_frame_lock, latest_frame

PHOTO_DIR = os.path.join(settings.MEDIA_ROOT, "photos")
os.makedirs(PHOTO_DIR, exist_ok=True)


def take_photo():
    """
    Capture a photo from the shared livestream frame.
    If unavailable, skip instead of opening a new capture.
    """
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

    print("[PHOTO] No live frame available, skipping fallback.")
    return False


def wait_for_table(table_name, db_alias="default", timeout=30):
    """
    Block until the specified table exists in the database or timeout is reached.
    """
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
    """
    Main loop for triggering timelapse photos based on settings.
    """
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
