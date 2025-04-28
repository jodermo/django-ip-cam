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
    Captures a photo from the camera.
    Temporarily stops the livestream if running, captures a frame, then resumes if needed.
    Returns the file path on success, None on failure.
    """
    logger.debug("[PHOTO] take_photo called")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(PHOTO_DIR, f"photo_{timestamp}.jpg")

    # Check if livestream is running and stop it temporarily
    livestream_was_running = (
        app_globals.livestream_job 
        and app_globals.livestream_job.running
    )
    if livestream_was_running:
        try:
            logger.info("[PHOTO] Pausing livestream for photo capture...")
            app_globals.livestream_job.stop()
            app_globals.livestream_job.join(timeout=2.0)
            app_globals.livestream_job = None
        except Exception as e:
            logger.warning(f"[PHOTO] Failed to stop livestream: {e}")

    with app_globals.camera_lock:
        if not app_globals.camera or not app_globals.camera.cap or not app_globals.camera.cap.isOpened():
            logger.warning("[PHOTO] Camera not ready. Attempting reinit.")
            try:
                init_camera(skip_stream=True)
                time.sleep(1.0)
            except Exception as e:
                logger.error(f"[PHOTO] Camera reinit failed: {e}")
                return None

        # Ensure camera is usable
        for i in range(5):
            if app_globals.camera and app_globals.camera.cap.isOpened():
                ret, _ = app_globals.camera.cap.read()
                if ret:
                    break
            logger.info(f"[PHOTO] Waiting for camera to stabilize ({i+1}/5)")
            time.sleep(1.0)
        else:
            logger.error("[PHOTO] Camera did not become ready.")
            return None

        # Apply settings
        settings = get_camera_settings()
        if settings:
            try:
                apply_cv_settings(app_globals.camera, settings, mode="photo")
            except Exception as e:
                logger.warning(f"[PHOTO] Failed to apply settings: {e}")

        # Capture the frame
        frame = app_globals.camera.get_frame()
        if frame is None:
            logger.warning("[PHOTO] Frame is None. Forcing camera reinit...")
            init_camera(skip_stream=True)
            time.sleep(1.0)
            frame = app_globals.camera.get_frame()
            if frame is None:
                logger.error("[PHOTO] Still failed to capture frame.")
                return None


        if not cv2.imwrite(filepath, frame):
            logger.error("[PHOTO] Failed to write photo.")
            return None

        logger.info(f"[PHOTO] Photo saved: {filepath}")

    # Restart livestream if it was running before
    if livestream_was_running:
        try:
            logger.info("[PHOTO] Restarting livestream after photo...")
            force_restart_livestream()
        except Exception as e:
            logger.error(f"[PHOTO] Failed to restart livestream: {e}")

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

    # Main loop
    while True:
        try:
            settings_obj = get_camera_settings()
            interval_min = 2  # default fallback

            if settings_obj:
                interval_min = max(1, min(getattr(settings_obj, "photo_interval_min", 2), 60))

                if settings_obj.timelapse_enabled:
                    logger.info(f"[SCHEDULER] Timelapse active → capturing photo @ {datetime.now()}")
                    result = take_photo()

                    if result is None:
                        logger.warning("[SCHEDULER] Photo capture failed. Retrying after reinit...")
                        try:
                            init_camera(skip_stream=True)
                            time.sleep(1.0)
                            result = take_photo()
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





