# cameraapp/sheduler.py

import os
import time
import cv2
from datetime import datetime
import numpy as np
from django.conf import settings
from django.db import connections
import logging
from .camera_core import init_camera 
from .camera_utils import apply_cv_settings, get_camera_settings, force_restart_livestream
from .globals import app_globals

logger = logging.getLogger(__name__)

PHOTO_DIR = os.path.join(settings.MEDIA_ROOT, "photos")
os.makedirs(PHOTO_DIR, exist_ok=True)



def take_photo():
    """
    Capture a photo from the livestream, or fallback directly from CameraManager.
    Returns file path on success, None on failure.
    """
    print("[DEBUG] take_photo called")
    global app_globals
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(PHOTO_DIR, f"photo_{timestamp}.jpg")

    # === [1] Livestream: Aktuellen Frame verwenden ===
    if app_globals.livestream_job and app_globals.livestream_job.running:
        with app_globals.latest_frame_lock:
            if app_globals.latest_frame is not None:
                frame = app_globals.latest_frame.copy()
                if cv2.imwrite(filepath, frame):
                    logger.info(f"[PHOTO] Saved from stream: {filepath}")
                    return filepath
                else:
                    logger.error("[PHOTO] Failed to save frame from stream.")
                    return None
            else:
                logger.warning("[PHOTO] No frame available from stream.")

    logger.info("[PHOTO] Livestream not available. Trying fallback using CameraManager...")

    # === [2] Kamera-Fallback ===
    with app_globals.camera_lock:
        if not app_globals.camera or not app_globals.camera.cap or not app_globals.camera.cap.isOpened():
            logger.warning("[PHOTO] CameraManager not ready or cap not opened. Attempting reinitialization.")
            try:
                init_camera()
            except Exception as e:
                logger.error(f"[PHOTO] init_camera() failed: {e}")
                return None

        # Testweise Frame lesen, um Kamera zu stabilisieren
        max_attempts = 5
        for i in range(max_attempts):
            if app_globals.camera and app_globals.camera.cap and app_globals.camera.cap.isOpened():
                ret, test_frame = app_globals.camera.cap.read()
                if ret and test_frame is not None:
                    logger.info(f"[PHOTO] Camera is ready (attempt {i+1})")
                    break
            logger.info(f"[PHOTO] Waiting for camera to stabilize... ({i+1}/{max_attempts})")
            time.sleep(1.0)
        else:
            logger.error("[PHOTO] Camera not usable after wait.")
            return None

        # Einstellungen anwenden
        settings = get_camera_settings()
        if settings:
            try:
                apply_cv_settings(app_globals.camera, settings, mode="photo")
            except Exception as e:
                logger.warning(f"[PHOTO] Failed to apply photo settings: {e}")

        # Frame abholen
        frame = app_globals.camera.get_frame()
        if frame is None:
            logger.error("[PHOTO] Failed to capture frame from fallback.")
            return None

        if not cv2.imwrite(filepath, frame):
            logger.error("[PHOTO] Failed to write fallback photo.")
            return None

        logger.info(f"[PHOTO] Saved from fallback capture: {filepath}")

    # === [3] Livestream neu starten ===
    logger.info("[PHOTO] Restarting livestream after fallback...")
    force_restart_livestream()

    return filepath



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
    logger.error(f"[ERROR] Timeout: Table '{table_name}' not found after {timeout} seconds.")


def start_photo_scheduler():
    """
    Starts the periodic photo capture loop based on configured intervals.
    """
    logger.info("[SCHEDULER] Starting photo scheduler...")
    wait_for_table("cameraapp_camerasettings")

    while True:
        try:
            settings_obj = get_camera_settings()
            if settings_obj and settings_obj.timelapse_enabled:
                logger.info(f"[SCHEDULER] Timelapse active. Taking photo at {datetime.now()}")
                take_photo()
                interval_min = settings_obj.photo_interval_min
            else:
                interval_min = 15
                logger.info(f"[SCHEDULER] Timelapse disabled. Sleeping {interval_min} minutes.")
        except Exception as e:
            logger.error(f"[SCHEDULER] Error during scheduler cycle: {e}")
            interval_min = 5

        time.sleep(interval_min * 60)
