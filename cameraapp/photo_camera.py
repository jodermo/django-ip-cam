# cameraapp/photo_camera.py

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
def take_photo(mode="manual"):
    """
    Captures a photo from the current camera stream.
    Reuses the shared capture without stopping the livestream.
    Falls back to cap.read() only if no valid frame is buffered.
    Returns the file path on success, None on failure.
    """
    logger.debug("[PHOTO] take_photo called")

    subfolder = "timelapse" if mode == "timelapse" else "manual"
    save_dir = os.path.join(PHOTO_DIR, subfolder)
    os.makedirs(save_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(save_dir, f"photo_{timestamp}.jpg")

    # Ensure camera is initialized before taking a photo
    with app_globals.camera_lock:
        cap = app_globals.camera.cap if app_globals.camera else None
        if not cap or not cap.isOpened():
            logger.warning("[PHOTO] Camera not ready. Attempting reinit.")
            try:
                init_camera(skip_stream=False)
                time.sleep(1.0)
                cap = app_globals.camera.cap
            except Exception as e:
                logger.error(f"[PHOTO] Camera reinit failed: {e}")
                return None

        # Apply photo-specific settings
        settings = get_camera_settings()
        if settings:
            try:
                apply_cv_settings(app_globals.camera, settings, mode="photo")
            except Exception as e:
                logger.warning(f"[PHOTO] Failed to apply photo settings: {e}")

        # Try to use the latest buffered frame first
        frame = None
        with app_globals.latest_frame_lock:
            if app_globals.latest_frame is not None:
                frame = app_globals.latest_frame.copy()

        # If no buffered frame available, read from cap
        if frame is None:
            logger.info("[PHOTO] No buffered frame available. Reading directly from camera...")
            for attempt in range(5):  # Increased retry attempts for stability
                ret, temp = cap.read()
                if ret and temp is not None:
                    frame = temp
                    break
                logger.warning(f"[PHOTO] Camera read failed (attempt {attempt + 1})")
                time.sleep(0.5)

            if frame is None:
                logger.error("[PHOTO] Failed to capture a valid frame after multiple retries.")
                return None

    # Save image
    if not cv2.imwrite(filepath, frame):
        logger.error("[PHOTO] Failed to write photo.")
        return None

    logger.info(f"[PHOTO] Photo saved: {filepath}")
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
    Starts the background photo scheduler loop.
    Periodically captures photos based on user-configured interval.
    Ensures camera is initialized and stable before each capture.
    """
    logger.info("[SCHEDULER] Starting photo scheduler...")

    # Wait for the CameraSettings table to be ready
    wait_for_table("cameraapp_camerasettings")

    # Initial camera setup
    try:
        logger.info("[SCHEDULER] Performing initial camera setup...")
        init_camera(skip_stream=True)
        time.sleep(2.0)  # allow hardware to stabilize
        if not app_globals.camera or not app_globals.camera.is_available():
            logger.warning("[SCHEDULER] Camera not ready after init → forcing stream restart")
            from .camera_utils import force_restart_livestream
            force_restart_livestream()
            time.sleep(2.0)
    except Exception as e:
        logger.error(f"[SCHEDULER] Initial camera setup failed: {e}")
        return  # If the setup fails, exit early

    # Main loop
    while True:
        try:
            settings_obj = get_camera_settings()
            interval_min = 2  # default fallback

            if settings_obj:
                interval_min = max(1, min(getattr(settings_obj, "photo_interval_min", 2), 60))

                if settings_obj.timelapse_enabled:
                    logger.info(f"[SCHEDULER] Timelapse active → capturing photo @ {datetime.now()}")
                    result = take_photo(mode="timelapse")

                    if result is None:
                        logger.warning("[SCHEDULER] Photo capture failed. Retrying after reinit...")
                        try:
                            init_camera(skip_stream=True)
                            time.sleep(1.0)
                            result = take_photo(mode="timelapse")
                        except Exception as e:
                            logger.error(f"[SCHEDULER] Retry failed: {e}")
                else:
                    logger.info(f"[SCHEDULER] Timelapse disabled. Sleeping for {interval_min} minutes.")
            else:
                logger.warning("[SCHEDULER] No CameraSettings found. Sleeping with default interval.")

        except Exception as e:
            logger.error(f"[SCHEDULER] Unexpected error in scheduler loop: {e}")
            interval_min = 2

        logger.debug(f"[SCHEDULER] Sleeping for {interval_min} minutes...")
        time.sleep(interval_min * 60)
