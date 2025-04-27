# cameraapp/camera_utils.py
import logging
import time
import threading
import os
import gc
import subprocess
import cv2

from django.apps import apps
from .globals import livestream_job, camera_lock, latest_frame
from cameraapp.camera_manager import CameraManager
from cameraapp.livestream_job import LiveStreamJob

logger = logging.getLogger(__name__)

def get_camera_settings():
    CameraSettings = apps.get_model("cameraapp", "CameraSettings")
    return CameraSettings.objects.first()


def get_camera_settings_safe(connection=None):
    """
    Safe wrapper around get_camera_settings; included for backward compatibility.
    """
    return get_camera_settings()


def apply_cv_settings(manager, settings, mode="video"):
    if not settings:
        logger.warning("No camera settings provided")
        return

    cap = manager.cap
    if not cap or not cap.isOpened():
        logger.error("Camera is not opened")
        return

    prefix = "video_" if mode == "video" else "photo_"
    exposure_mode = getattr(settings, f"{prefix}exposure_mode", "manual").lower()

    if exposure_mode == "auto":
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
    else:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)

    def apply_param(name, min_val, max_val, skip_if_auto=False):
        raw_value = getattr(settings, f"{prefix}{name}", None)
        if raw_value is None:
            return
        try:
            value = float(raw_value)
        except (ValueError, TypeError):
            logger.warning(f"Invalid value for {name}: {raw_value}")
            return

        if skip_if_auto and exposure_mode == "auto":
            return
        if not (min_val <= value <= max_val):
            logger.warning(f"{name} value {value} out of range")
            return

        prop_id = getattr(cv2, f"CAP_PROP_{name.upper()}", None)
        if prop_id is None:
            logger.warning(f"Unknown property: {name}")
            return

        cap.set(prop_id, value)
        actual = cap.get(prop_id)
        logger.info(f"Set {name} = {value}, actual = {actual}")

    apply_param("brightness", 0.0, 255.0)
    apply_param("contrast", 0.0, 255.0)
    apply_param("saturation", 0.0, 255.0)
    apply_param("gain", 0.0, 10.0)
    apply_param("exposure", -13.0, -1.0, skip_if_auto=True)


def try_open_camera(source, backend=cv2.CAP_V4L2):
    """
    Attempt to open a camera device; returns a VideoCapture or None.
    """
    try:
        cap = cv2.VideoCapture(source, backend)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                logger.info(f"Opened camera source {source} successfully")
                return cap
        cap.release()
    except Exception as e:
        logger.error(f"try_open_camera failed for {source}: {e}")
    return None


def try_open_camera_safe(source):
    """Safe wrapper for try_open_camera; included for backward compatibility."""
    return try_open_camera(source)


def safe_restart_camera_stream(frame_callback, camera_source=None):
    """
    Restart the livestream job using the *single* CameraManager instance.
    Returns the new LiveStreamJob, or None on failure.
    """
    global livestream_job, camera

    with camera_lock:
        # 1) Stop existing livestream
        if livestream_job and livestream_job.running:
            try:
                livestream_job.stop()
                livestream_job.join(timeout=2.0)
                logger.info("Stopped previous livestream job")
            except Exception as e:
                logger.warning(f"Error stopping livestream_job: {e}")
            livestream_job = None

        # 2) Ensure camera is alive (reopen if needed)
        if camera_source and (not camera or not camera.is_available()):
            logger.info(f"CameraManager is being reinitialized with source: {camera_source}")
            try:
                camera = CameraManager(source=camera_source)
                if not camera.is_available():
                    logger.error("Newly initialized CameraManager is not available")
                    return None
            except Exception as e:
                logger.error(f"Failed to reinitialize CameraManager: {e}")
                return None


        # 3) Re-apply user settings
        settings = get_camera_settings()
        if settings:
            try:
                from .camera_utils import apply_cv_settings
                apply_cv_settings(camera, settings, mode="video")
                logger.info("Re-applied CV settings")
            except Exception as e:
                logger.warning(f"Failed to apply camera settings: {e}")

        # 4) Start a fresh LiveStreamJob on the shared capture
        try:
            new_job = LiveStreamJob(
                camera_source=None,        # unused when shared_capture is given
                frame_callback=frame_callback,
                shared_capture=camera.cap
            )
            new_job.start()

            time.sleep(0.5)
            if not new_job.running:
                raise RuntimeError("Livestream job did not start")
            livestream_job = new_job
            logger.info("Livestream restarted successfully")
            return new_job

        except Exception as e:
            logger.error(f"Failed to start new livestream: {e}")
            return None

def force_restart_livestream():
    """
    Alias for backward compatibility: restart the livestream with default parameters.
    """
    logger.info("force_restart_livestream called")
    # Uses environment or existing globals to restart
    from .globals import latest_frame_lock, latest_frame
    from .globals import camera_lock, livestream_job
    return safe_restart_camera_stream(
        camera_source=os.getenv("CAMERA_URL", 0),
        frame_callback=lambda f: setattr(__import__('cameraapp.globals', fromlist=['']), 'latest_frame', f.copy())
    )


def release_and_reset_camera():
    global livestream_job
    try:
        if livestream_job and livestream_job.capture:
            livestream_job.capture.release()
            livestream_job.capture = None
        if livestream_job:
            livestream_job.stop()
            livestream_job.join(timeout=2)
            livestream_job = None
        force_restart_livestream()
        gc.collect()
        time.sleep(1)
    except Exception as e:
        logger.error(f"Error during camera release/reset: {e}")


def update_livestream_job(new_job):
    global livestream_job
    livestream_job = new_job
    globals()["livestream_job"] = new_job
