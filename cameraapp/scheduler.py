# cameraapp/scheduler.py
import os
import time
import cv2
from datetime import datetime
from django.conf import settings
from django.apps import apps
from django.db import connections
from .globals import latest_frame, latest_frame_lock
from .camera_core import apply_cv_settings, get_camera_settings
import numpy as np

# Ensure photo directory exists
PHOTO_DIR = os.path.join(settings.MEDIA_ROOT, "photos")
os.makedirs(PHOTO_DIR, exist_ok=True)

def get_camera_settings():
    """Safely loads camera settings."""
    CameraSettings = apps.get_model("cameraapp", "CameraSettings")
    return CameraSettings.objects.first()

def take_photo():
    """Captures photo from shared live frame, or opens camera if not available."""
    frame = None

    # Try shared frame first
    with latest_frame_lock:
        if latest_frame is not None:
            frame = latest_frame.copy()

    if frame is not None:
        print("[PHOTO] Using shared live frame.")
    else:
        print("[PHOTO] No shared frame. Attempting direct capture.")
        camera_url_raw = os.getenv("CAMERA_URL", "0")
        camera_url = int(camera_url_raw) if camera_url_raw.isdigit() else camera_url_raw
        cap = cv2.VideoCapture(camera_url)
        if not cap.isOpened():
            print("[PHOTO] Failed to open camera.")
            return False

        settings = get_camera_settings()
        apply_cv_settings(cap, settings, mode="photo")

        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            print("[PHOTO] Failed to capture image from camera.")
            return False

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(PHOTO_DIR, f"photo_{timestamp}.jpg")
    success = cv2.imwrite(filepath, frame)

    if success:
        print(f"[PHOTO] Saved: {filepath}")
    else:
        print("[PHOTO] Failed to save image.")

    return success

def wait_for_table(table_name, db_alias="default", timeout=30):
    """Waits until the specified table is available (e.g., after migrations)."""
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
    """Infinite loop for time-based photo captures (timelapse)."""
    print("[SCHEDULER] Starting timelapse scheduler...")
    wait_for_table("cameraapp_camerasettings")

    while True:
        settings_obj = get_camera_settings()
        if settings_obj and settings_obj.timelapse_enabled:
            take_photo()
            interval_min = settings_obj.photo_interval_min
        else:
            interval_min = 15  # Default: every 15 minutes
        time.sleep(interval_min * 60)
