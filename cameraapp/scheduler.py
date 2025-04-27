# cameraapp/sheduler.py

import os
import time
import cv2
from datetime import datetime
import numpy as np
from django.conf import settings
from django.db import connections

from .camera_utils import try_open_camera, apply_cv_settings, get_camera_settings, force_restart_livestream
from .globals import latest_frame_lock, latest_frame, livestream_job, camera_lock

PHOTO_DIR = os.path.join(settings.MEDIA_ROOT, "photos")
os.makedirs(PHOTO_DIR, exist_ok=True)




def take_photo():
    """
    Capture a photo from livestream or fallback directly from webcam.
    """
    used_fallback = False

    if livestream_job and livestream_job.running:
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

    print("[PHOTO] Livestream not running or no frame available. Trying direct capture...")
    with camera_lock:
        settings = get_camera_settings()
        cap = try_open_camera(0, retries=3, delay=1.0)
        if not cap or not cap.isOpened():
            print("[PHOTO] Camera not available for fallback.")
            return False

        apply_cv_settings(cap, settings, mode="photo")
        time.sleep(0.3)

        ret, frame = cap.read()

        # Sehr wichtig: Kamera *richtig* schließen und Delay einbauen
        cap.release()
        time.sleep(0.5)

        if not ret or frame is None:
            print("[PHOTO] Failed to capture fallback frame.")
            return False

        used_fallback = True
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(PHOTO_DIR, f"photo_{timestamp}.jpg")
        if cv2.imwrite(filepath, frame):
            print(f"[PHOTO] Saved from fallback: {filepath}")
        else:
            print("[PHOTO] Failed to save fallback frame.")
            return False

    if used_fallback:
        print("[PHOTO] Restarting livestream after fallback photo.")
        # Wiederum Delay, um sicherzustellen, dass das Device wirklich frei ist
        time.sleep(0.5)
        force_restart_livestream()

    return True




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
