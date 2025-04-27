# cameraapp/camera_utils.py
import logging
import time
import threading
import cv2
from django.apps import apps
from .globals import camera_lock, latest_frame, latest_frame_lock, livestream_resume_lock, livestream_job, taking_foto, camera_capture, active_stream_viewers, last_disconnect_time, recording_timeout


logger = logging.getLogger(__name__)


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
            print("[CAMERA_CORE] No reopen_callback defined – aborting.")
            return

    prefix = "video_" if mode == "video" else "photo_"

    # Set auto-exposure
    exposure_mode = getattr(settings, f"{prefix}exposure_mode", "manual")
    if exposure_mode == "auto":
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
        print(f"[CAMERA_CORE] {mode.upper()} exposure_mode = AUTO")
    else:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
        print(f"[CAMERA_CORE] {mode.upper()} exposure_mode = MANUAL")
        time.sleep(0.1)  # some cameras require this pause after switching mode

    def apply_param(name, min_valid=-1.0, max_valid=100.0):
        try:
            raw = getattr(settings, f"{prefix}{name}", None)
            if raw is None:
                return
            try:
                value = float(raw)
            except (TypeError, ValueError):
                print(f"[WARNING] Invalid value for {prefix}{name}: {raw}")
                return
        except (TypeError, ValueError):
            print(f"[WARNING] Invalid value for {prefix}{name}")
            return

        if value < 0:
            print(f"[CAMERA_CORE] {name} disabled (value={value})")
            return
        if name == "exposure" and exposure_mode == "auto":
            print("[SKIP] Exposure ignored in auto mode.")
            return
        cap_prop = getattr(cv2, f"CAP_PROP_{name.upper()}", None)
        if cap_prop is None:
            print(f"[WARNING] Unknown OpenCV property: {name}")
            return

        if not (min_valid <= value <= max_valid):
            print(f"[WARNING] {name} out of valid range ({value}) – ignored.")
            return

        ok = cap.set(cap_prop, value)
        actual = cap.get(cap_prop)
        print(f"[CAMERA_CORE] {mode.upper()} Set {name} = {value} → {'OK' if ok else 'FAIL'}, actual={actual}")

    # Apply camera parameters
    apply_param("brightness", 0.0, 255.0)
    apply_param("contrast", 0.0, 255.0)
    apply_param("saturation", 0.0, 255.0)
    apply_param("gain", 0.0, 10.0)

    if exposure_mode == "manual":
        # Valid exposure range only applied when in manual mode
        apply_param("exposure", -13.0, -1.0)
    else:
        print("[SKIP] Exposure setting ignored in auto exposure mode.")




def try_open_camera(camera_source, retries=3, delay=1.0):
    print(f"[DEBUG] try_open_camera: source={camera_source}, retries={retries}, delay={delay}")
    for i in range(retries):
        print(f"[DEBUG] Attempt {i + 1} to open camera...")
        cap = cv2.VideoCapture(camera_source)
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
    Safely restart the livestream:
    1. Stop and join any existing job
    2. Reopen the camera with retries
    3. Apply stored camera settings
    4. Launch and return a new LiveStreamJob

    Returns:
        LiveStreamJob or None on failure
    """
    from .livestream_job import LiveStreamJob

    with camera_lock:
        # 1) Stop existing livestream
        if livestream_job_ref and getattr(livestream_job_ref, 'running', False):
            logger.info("[RESTART] Stopping existing livestream job...")
            try:
                livestream_job_ref.stop()
                livestream_job_ref.join(timeout=2.0)
            except Exception as e:
                logger.warning(f"[RESTART] Error stopping previous job: {e}")

        # 2) Attempt to open camera
        cap = try_open_camera(camera_url, retries=retries, delay=delay)
        if not cap or not cap.isOpened():
            logger.error(f"[RESTART] Camera not available after {retries} attempts.")
            return None

        # 3) Apply settings if present
        settings = get_camera_settings()
        if settings:
            try:
                apply_cv_settings(cap, settings, mode="video")
                logger.debug("[RESTART] Camera settings applied.")
            except Exception as e:
                logger.warning(f"[RESTART] Failed to apply settings: {e}")
        else:
            logger.warning("[RESTART] No CameraSettings found; using defaults.")

        # 4) Create and start new livestream job
        try:
            job = LiveStreamJob(
                camera_source=camera_url,
                frame_callback=frame_callback,
                shared_capture=cap
            )
            job.start()
            logger.info("[RESTART] Livestream job started successfully.")
            return job
        except Exception as e:
            logger.error(f"[RESTART] Failed to start livestream job: {e}")
            cap.release()
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
    """
    Überwacht kontinuierlich, ob die Kamera noch funktioniert.
    Startet oder repariert die Verbindung bei Ausfall.
    """
    def watchdog_loop():
        print("[WATCHDOG] Kamera-Watchdog gestartet.")
        while True:
            time.sleep(interval_sec)

            if not livestream_job or not livestream_job.running:
                print("[WATCHDOG] Livestream nicht aktiv. Starte neu...")
                force_restart_livestream()
                continue

            frame = livestream_job.get_frame()
            if frame is None:
                print("[WATCHDOG] Kein Frame erkannt. Erzwinge Neustart.")
                force_restart_livestream()

    threading.Thread(target=watchdog_loop, daemon=True).start()


def try_open_camera_safe(source, retries=3, delay=1.0):
    import gc
    for attempt in range(retries):
        cap = cv2.VideoCapture(source)
        if cap.isOpened():
            return cap
        cap.release()
        gc.collect()
        print(f"[SAFE_CAMERA] Retry {attempt+1} failed. Waiting {delay}s.")
        time.sleep(delay)
    return None
