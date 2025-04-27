# cameraapp/camera_utils.py

import logging
import time
import threading
import subprocess
import cv2
import fcntl
import os
import gc
from django.apps import apps
from .globals import camera_lock, camera_instance, latest_frame, latest_frame_lock, livestream_resume_lock, livestream_job, taking_foto, camera_capture, active_stream_viewers, last_disconnect_time, recording_timeout

logger = logging.getLogger(__name__)

open_camera_lock = threading.Lock()

def get_camera_settings():
    CameraSettings = apps.get_model("cameraapp", "CameraSettings")
    return CameraSettings.objects.first()

def get_camera_settings_safe(connection):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM cameraapp_camerasettings LIMIT 1")
    except Exception:
        return None
    CameraSettings = apps.get_model("cameraapp", "CameraSettings")
    return CameraSettings.objects.first()


def apply_cv_settings(cap, settings, mode="video", reopen_callback=None):
    import time
    import cv2
    from .globals import camera_instance

    if not settings:
        print("[CAMERA_CORE] No settings provided.")
        return

    if not cap or not cap.isOpened():
        print("[CAMERA_CORE] Camera not opened. Attempting restart...")

        if reopen_callback:
            new_cap = reopen_callback()
            if new_cap and new_cap.isOpened():
                cap = new_cap
                camera_instance = cap
                print("[CAMERA_CORE] Camera reopened successfully.")
            else:
                print("[CAMERA_CORE] Camera reopen failed.")
                return
        else:
            print("[CAMERA_CORE] No reopen_callback defined – aborting.")
            return

    prefix = "video_" if mode == "video" else "photo_"

    # Set auto-exposure mode
    exposure_mode = getattr(settings, f"{prefix}exposure_mode", "manual").lower()
    if exposure_mode == "auto":
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
        time.sleep(0.5)
        print(f"[CAMERA_CORE] {mode.upper()} exposure_mode = AUTO")
    else:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
        print(f"[CAMERA_CORE] {mode.upper()} exposure_mode = MANUAL")
        time.sleep(0.5)

    def apply_param(name, min_valid=-1.0, max_valid=100.0, skip_if_auto=False):
        try:
            raw = getattr(settings, f"{prefix}{name}", None)
            if raw is None:
                return
            try:
                value = float(raw)
            except (TypeError, ValueError):
                print(f"[WARNING] Invalid value for {prefix}{name}: {raw}")
                return
        except Exception:
            print(f"[WARNING] Error accessing {prefix}{name}")
            return

        if skip_if_auto and exposure_mode == "auto":
            print(f"[SKIP] {name} ignored in auto mode.")
            return

        if value < 0:
            print(f"[CAMERA_CORE] {name} disabled (value={value})")
            return

        cap_prop = getattr(cv2, f"CAP_PROP_{name.upper()}", None)
        if cap_prop is None:
            print(f"[WARNING] Unknown OpenCV property: {name}")
            return

        if not (min_valid <= value <= max_valid):
            print(f"[WARNING] {name} out of valid range ({value}) – ignored.")
            return

        print(f"[DEBUG] Setting {name} = {value} on CAP_PROP_{name.upper()}")
        ok = cap.set(cap_prop, value)
        actual = cap.get(cap_prop)
        print(f"[CAMERA_CORE] {mode.upper()} Set {name} = {value} → {'OK' if ok else 'FAIL'}, actual={actual}")
        if name == "exposure" and exposure_mode == "manual" and (not ok or actual > 0):
            print(f"[ERROR] Exposure setting likely failed (actual={actual})")

    # Apply all non-exposure parameters first
    apply_param("brightness", 0.0, 255.0)
    apply_param("contrast", 0.0, 255.0)
    apply_param("saturation", 0.0, 255.0)
    apply_param("gain", 0.0, 10.0)

    # Exposure is sensitive → apply last
    apply_param("exposure", -13.0, -1.0, skip_if_auto=True)



def try_open_camera(camera_source, retries=3, delay=1.0):

    with open_camera_lock:
        device_path = f"/dev/video{camera_source}" if isinstance(camera_source, int) else str(camera_source)

        print(f"[DEBUG] try_open_camera: source={camera_source}, retries={retries}, delay={delay}")
        for i in range(retries):
            print(f"[DEBUG] Attempt {i + 1} to open camera...")

            if isinstance(camera_source, int) and not os.path.exists(device_path):
                print(f"[DEBUG] /dev/video{camera_source} does not exist.")
                time.sleep(delay)
                continue

            cap = cv2.VideoCapture(camera_source, cv2.CAP_V4L2)
            if cap.isOpened():
                print("[DEBUG] Camera opened successfully.")
                return cap
            else:
                print("[DEBUG] Camera not opened, retrying...")
            cap.release()
            time.sleep(delay)

        print("[DEBUG] All attempts failed. Returning None.")
        return None


def safe_restart_camera_stream(livestream_job_ref, camera_url, frame_callback, retries: int = 3, delay: float = 2.0):
    """
    Safely restart the livestream.
    """
    from .globals import camera_instance
    from cameraapp.livestream_job import LiveStreamJob
    import gc

    logger = logging.getLogger(__name__)
    logger.info("[RESTART] Starting safe_restart_camera_stream...")

    def wait_until_camera_available(device_index=0, max_attempts=6, delay=1.0):
        for attempt in range(max_attempts):
            cap = cv2.VideoCapture(device_index)
            if cap.isOpened():
                cap.release()
                time.sleep(1.5)
                logger.info(f"[RESTART] /dev/video{device_index} ist wieder verfügbar.")
                return True
            logger.info(f"[RESTART] Warten auf /dev/video{device_index} – Versuch {attempt + 1}/{max_attempts}")
            time.sleep(delay)
        return False

    with camera_lock:
        if camera_instance and camera_instance.isOpened():
            camera_instance.release()
            camera_instance = None  # <<< wichtig!
            logger.info("[RESTART] Camera released.")

            try:
                force_device_reset("/dev/video0")
            except Exception as e:
                logger.warning(f"[RESTART] Device reset failed: {e}")

            gc.collect()
            time.sleep(1.5)

        if livestream_job_ref and getattr(livestream_job_ref, 'running', False):
            try:
                livestream_job_ref.stop()
                livestream_job_ref.join(timeout=2.0)
                logger.info("[RESTART] Livestream job stopped.")
            except Exception as e:
                logger.warning(f"[RESTART] Error stopping previous job: {e}")

        gc.collect()
        time.sleep(1.0)

        if not wait_until_camera_available(device_index=0, max_attempts=6, delay=1.0):
            logger.error("[RESTART] Camera did not become available. Aborting.")
            return None

        logger.info("[RESTART] Attempting to open camera...")
        cap = try_open_camera(camera_url, retries=retries, delay=delay)
        if not cap or not cap.isOpened():
            logger.error("[RESTART] Camera not available after retries. Aborting restart.")
            return None

        logger.info("[RESTART] Camera opened successfully.")

        settings = get_camera_settings()
        if settings:
            try:
                apply_cv_settings(cap, settings, mode="video")
                logger.info("[RESTART] Camera settings applied successfully.")
            except Exception as e:
                logger.warning(f"[RESTART] Failed to apply camera settings: {e}")
        else:
            logger.warning("[RESTART] No camera settings found.")

        try:
            job = LiveStreamJob(
                camera_source=camera_url,
                frame_callback=frame_callback,
                shared_capture=cap
            )
            job.start()
            time.sleep(0.5)

            if not job.running:
                logger.error("[RESTART] LiveStreamJob failed to start.")
                cap.release()
                time.sleep(1.5)
                return None

            logger.info("[RESTART] LiveStreamJob started successfully.")
            return job
        except Exception as e:
            logger.error(f"[RESTART] Failed to start livestream job: {e}")
            cap.release()
            time.sleep(1.5)
            return None




def force_restart_livestream():
    """
    Ensure livestream is stopped and restarted cleanly.
    """
    global livestream_job
    time.sleep(0.5)
    with camera_lock:
        if livestream_job and livestream_job.running:
            print("[LIVE] Stopping livestream for restart...")
            livestream_job.stop()
            livestream_job.join(timeout=2.0)
            time.sleep(1.0)

        cap = try_open_camera(0, retries=3, delay=1.0)
        if not cap or not cap.isOpened():
            print("[LIVE] Could not reopen camera.")
            return False

        settings = get_camera_settings()
        apply_cv_settings(cap, settings, mode="video")
        from cameraapp.livestream_job import LiveStreamJob
        livestream_job = LiveStreamJob(
            camera_source=0,
            frame_callback=lambda f: setattr(globals(), 'latest_frame', f.copy()),
            shared_capture=cap
        )
        globals()["livestream_job"] = livestream_job
        livestream_job.start()
        print("[LIVE] Livestream restarted.")
        return True
    



def start_camera_watchdog(interval_sec=10):
    return  # Deaktiviert für Stabilitätstests

def try_open_camera_safe(source, retries=3, delay=1.0):
    import gc
    for attempt in range(retries):
        cap = cv2.VideoCapture(source)
        if cap.isOpened():
            return cap
        cap.release()
        time.sleep(1.5)
        gc.collect()
        print(f"[SAFE_CAMERA] Retry {attempt+1} failed. Waiting {delay}s.")
        time.sleep(delay)
    return None


def force_device_reset(device="/dev/video0"):
    try:
        # Suche den zugehörigen USB-Port (z. B. 1-2.4) heraus
        video_dev = os.path.realpath(device)
        usb_path = os.readlink(f"/sys/class/video4linux/{os.path.basename(video_dev)}/device")
        usb_bus = os.path.join("/sys/class/video4linux", os.path.basename(video_dev), "device", "authorized")

        print(f"[RESET] Resetting USB device: {usb_bus}")

        print("[CHECK] /dev/video0 exists:", os.path.exists("/dev/video0"))
        print("[CHECK] Accessible:", os.access("/dev/video0", os.R_OK | os.W_OK))
        print("[CHECK] lsof -t /dev/video0:", subprocess.getoutput("lsof -t /dev/video0"))

        with open(usb_bus, "w") as f:
            f.write("0")
        time.sleep(1.0)
        with open(usb_bus, "w") as f:
            f.write("1")
        print("[RESET] USB device re-enabled.")
    except Exception as e:
        print(f"[RESET] USB reset failed: {e}")


def release_and_reset_camera():
    from .globals import camera_instance, camera_capture, livestream_job
    try:
        if livestream_job and livestream_job.capture:
            livestream_job.capture.release()
            livestream_job.capture = None
            print("[RELEASE] livestream_job.capture released")

        if camera_instance and camera_instance.isOpened():
            camera_instance.release()
            logger.info("[RESTART] Camera released.")

        # Device reset UNBEDINGT immer versuchen, auch wenn vorher schon .release() aufgerufen wurde!
        try:
            force_device_reset("/dev/video0")
        except Exception as e:
            logger.warning(f"[RESTART] Device reset failed: {e}")

        time.sleep(1.0)

        camera_instance = None
        camera_capture = None

    except Exception as e:
        print(f"[RELEASE] Error during full camera release: {e}")
    wait_for_camera_device()


def wait_for_camera_device(device_path="/dev/video0", timeout=5.0):
    start = time.time()
    while time.time() - start < timeout:
        if os.path.exists(device_path) and os.access(device_path, os.R_OK):
            return True
        time.sleep(0.2)
    return False
