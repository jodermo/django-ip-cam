# cameraapp/camera_utils.py
import logging
import time
import os
import gc
import cv2
import subprocess
import threading
from django.apps import apps
from cameraapp.camera_manager import CameraManager
from cameraapp.livestream_job import LiveStreamJob
from .globals import app_globals


logger = logging.getLogger(__name__)

def get_camera_settings():
    CameraSettings = apps.get_model("cameraapp", "CameraSettings")
    return CameraSettings.objects.first()

def is_camera_device_available(device="/dev/video0"):
    return os.path.exists(device) and os.access(device, os.R_OK | os.W_OK)

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

def safe_restart_camera_stream(frame_callback=None, camera_source=None):
    """
    Restart the livestream job using the *single* CameraManager instance.
    Returns the new LiveStreamJob, or None on failure.
    """
    global app_globals

    # Fallback für frame_callback → aktualisiert globalen latest_frame
    if frame_callback is None:
        def default_callback(frame):
            with app_globals.latest_frame_lock:
                app_globals.latest_frame = frame.copy()
        frame_callback = default_callback


    # Debug zur Kamera
    if not app_globals.camera:
        logger.error("camera is None after initialization")
    elif not app_globals.camera.cap:
        logger.error("CameraManager.cap is None after initialization")
    elif not app_globals.camera.cap.isOpened():
        logger.error("CameraManager.cap is not opened")
    else:
        logger.info("CameraManager.cap is valid and opened")

    # Kamera exklusiv sperren
    with app_globals.camera_lock:
        # 1) Vorherigen Stream stoppen
        if app_globals.livestream_job and app_globals.livestream_job.running:
            try:
                app_globals.livestream_job.stop()
                app_globals.livestream_job.join(timeout=2.0)
                logger.info("Stopped previous livestream job")
            except Exception as e:
                logger.warning(f"Error stopping livestream_job: {e}")
            app_globals.livestream_job = None

        # 2) Kamera ggf. reinitialisieren
        if camera_source and (not app_globals.camera or not app_globals.camera.is_available()):
            logger.info(f"CameraManager is being reinitialized with source: {camera_source}")
            try:
                app_globals.camera = CameraManager(source=camera_source)
                if not app_globals.camera.is_available():
                    logger.error("Newly initialized CameraManager is not available")
                    return None
            except Exception as e:
                logger.error(f"Failed to reinitialize CameraManager: {e}")
                return None

        # 3) CV-Einstellungen neu anwenden
        settings = get_camera_settings()
        if settings:
            try:
                apply_cv_settings(app_globals.camera, settings, mode="video")
                logger.info("Re-applied CV settings")
            except Exception as e:
                logger.warning(f"Failed to apply camera settings: {e}")

        # 4) Neuen LiveStreamJob starten
        try:
            new_job = LiveStreamJob(
                camera_source=None,  # wird ignoriert, da shared_capture gesetzt
                frame_callback=frame_callback,
                shared_capture=(app_globals.camera.cap if app_globals.camera else None)
            )
            new_job.start()
            time.sleep(0.5)

            if not new_job.running:
                raise RuntimeError("Livestream job did not start")
            
            app_globals.livestream_job = new_job
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
    return safe_restart_camera_stream(
        camera_source=os.getenv("CAMERA_URL", 0),
        frame_callback=update_latest_frame
    )


def release_and_reset_camera():
    global app_globals
    try:
        app_globals.camera.release() 
        if app_globals.livestream_job and app_globals.livestream_job.capture:
            app_globals.livestream_job.capture.release()
            app_globals.livestream_job.capture = None
        if app_globals.livestream_job:
            app_globals.livestream_job.stop()
            app_globals.livestream_job.join(timeout=2)
            app_globals.livestream_job = None
        force_restart_livestream()
        gc.collect()
        time.sleep(1)
    except Exception as e:
        logger.error(f"Error during camera release/reset: {e}")


def update_livestream_job(new_job):
    global app_globals
    app_globals.livestream_job = new_job


def update_latest_frame(frame):
    global app_globals
    with app_globals.latest_frame_lock:
        app_globals.latest_frame = frame.copy()



def force_device_reset(device_path="/dev/video0"):
    """
    Forcibly resets a USB camera by unbinding and rebinding the USB device.
    Works only on Linux and requires root privileges.
    """


    # Get the USB bus/device path for the video device
    try:
        # Example: /dev/video0 -> 1-3 (bus-port)
        result = subprocess.check_output(f"udevadm info --name={device_path} --query=all", shell=True)
        for line in result.decode().splitlines():
            if "ID_PATH=" in line:
                path = line.strip().split("ID_PATH=")[-1]
                usb_bus = path.split(":")[0]  # e.g. "pci-0000:00:14.0-usb-0:3"
                usb_dev = usb_bus.split("-")[-1]
                if usb_dev:
                    unbind_path = f"/sys/bus/usb/drivers/usb/unbind"
                    bind_path = f"/sys/bus/usb/drivers/usb/bind"
                    logger.warning(f"Forcing USB reset of device {usb_dev}")
                    with open(unbind_path, "w") as f:
                        f.write(usb_dev)
                    time.sleep(1)
                    with open(bind_path, "w") as f:
                        f.write(usb_dev)
                    return
        logger.error("Could not determine USB device ID from udevadm output")
    except Exception as e:
        logger.error(f"force_device_reset failed: {e}")


def start_camera_watchdog(interval_sec=10):
    """
    Prüft regelmäßig, ob Kamera und Livestream aktiv sind.
    Wenn nicht, wird ein Neustart versucht.
    """
    def loop():
        while True:
            try:
                cam = app_globals.camera
                if not cam or not cam.cap or not cam.cap.isOpened():
                    logger.warning("[WATCHDOG] Camera not available. Trying to restart...")
                    from .camera_core import init_camera
                    init_camera()
                elif app_globals.livestream_job and not app_globals.livestream_job.running:
                    logger.warning("[WATCHDOG] Livestream not running. Restarting...")
                    from .camera_utils import force_restart_livestream
                    force_restart_livestream()
            except Exception as e:
                logger.error(f"[WATCHDOG] Exception: {e}")
            time.sleep(interval_sec)

    threading.Thread(target=loop, daemon=True).start()
    logger.info("[WATCHDOG] Started camera watchdog thread.")



