# cameraapp/camera_core.py

import os
import cv2
import glob
import time
from dotenv import load_dotenv
from cameraapp.models import CameraSettings
from .camera_utils import safe_restart_camera_stream, update_latest_frame, get_camera_settings, apply_cv_settings, try_open_camera, release_and_reset_camera, force_restart_livestream, get_camera_settings_safe, try_open_camera_safe, update_livestream_job
from .globals import app_globals
from .camera_manager import CameraManager

load_dotenv()


def find_working_camera_device():
    candidates = sorted(glob.glob("/dev/video*"))
    for device in candidates:
        cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        if cap.isOpened():
            ret, _ = cap.read()
            cap.release()
            if ret:
                return device
    return None



CAMERA_URL_RAW = os.getenv("CAMERA_URL", "0")

if CAMERA_URL_RAW == "0" and not os.path.exists("/dev/video0"):
    fallback_device = find_working_camera_device()
    CAMERA_URL = fallback_device if fallback_device else 0
    print(f"[CAMERA_CORE] CAMERA_URL fallback resolved to: {CAMERA_URL}")
else:
    CAMERA_URL = int(CAMERA_URL_RAW) if CAMERA_URL_RAW.isdigit() else CAMERA_URL_RAW


def resolve_camera_source():
    if CAMERA_URL == "0" and not os.path.exists("/dev/video0"):
        fallback = find_working_camera_device()
        return fallback if fallback else "/dev/video0"
    return CAMERA_URL


def init_camera(skip_stream=False):
    if app_globals.camera and app_globals.camera.is_available():
        print("[CAMERA_CORE] Camera already initialized")
        return

    print("[CAMERA_CORE] Initializing new CameraManager...")

    try:
        source = resolve_camera_source()

        # Neue CameraManager-Instanz erzeugen
        new_camera = CameraManager(source=source, force_backend=cv2.CAP_V4L2)

        # Warten, bis Gerät verfügbar ist (max 5 Sekunden)
        for attempt in range(5):
            if new_camera.is_available() and new_camera.cap and new_camera.cap.isOpened():
                break
            print(f"[CAMERA_CORE] Waiting for camera... attempt {attempt + 1}/5")
            time.sleep(1.0)
        else:
            print("[CAMERA_CORE] Camera device did not become available in time.")
            return

        app_globals.camera = new_camera
        print("[CAMERA_CORE] CameraManager initialized and running.")

        if not skip_stream and (not app_globals.livestream_job or not app_globals.livestream_job.running):
            print("[CAMERA_CORE] Starting livestream job...")
            from .livestream_job import LiveStreamJob
            job = LiveStreamJob(
                camera_source=source,
                frame_callback=lambda f: update_latest_frame(f),
                shared_capture=new_camera.cap
            )
            job.start()
            app_globals.livestream_job = job
            update_livestream_job(job)

        print(f"[DEBUG] camera is {app_globals.camera}")
        print(f"[DEBUG] livestream_job is {app_globals.livestream_job}")

    except Exception as e:
        print(f"[CAMERA_CORE] Exception during camera init: {e}")

def reset_to_default():
    settings = CameraSettings.objects.first()
    if not settings:
        print("[RESET] Keine CameraSettings gefunden. Abbruch.")
        return

    settings.photo_exposure_mode = "manual"
    settings.photo_brightness = 128.0
    settings.photo_contrast = 32.0
    settings.photo_saturation = 64.0
    settings.photo_exposure = -6.0
    settings.photo_gain = 4.0

    settings.video_exposure_mode = "auto"
    settings.video_brightness = 128.0
    settings.video_contrast = 32.0
    settings.video_saturation = 64.0
    settings.video_exposure = -6.0
    settings.video_gain = 4.0

    settings.save()
    print("[RESET] CameraSettings auf Default zurückgesetzt.")


def apply_auto_settings(settings, mode="photo"):
    if mode == "photo":
        settings.photo_exposure_mode = "auto"
        settings.photo_brightness = 128.0
        settings.photo_contrast = 32.0
        settings.photo_saturation = 64.0
        settings.photo_exposure = -1
        settings.photo_gain = -1
    elif mode == "video":
        settings.video_exposure_mode = "auto"
        settings.video_brightness = 128.0
        settings.video_contrast = 32.0
        settings.video_saturation = 64.0
        settings.video_exposure = -1
        settings.video_gain = -1
    else:
        print(f"[CAMERA_CORE] Unknown mode for auto settings: {mode}")
        return

    settings.save()
    print(f"[CAMERA_CORE] Auto {mode} settings applied.")


def auto_adjust_from_frame(frame, settings):
    if frame is None or settings is None:
        print("[CAMERA_CORE] Cannot auto-adjust: invalid input.")
        return

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    avg = gray.mean()
    print(f"[CAMERA_CORE] Frame average brightness: {avg:.2f}")

    if avg < 60:
        settings.photo_brightness = 0.7
        settings.photo_gain = 0.5
        settings.photo_exposure = -4
    elif avg > 180:
        settings.photo_brightness = 0.3
        settings.photo_gain = 0.0
        settings.photo_exposure = -8
    else:
        settings.photo_brightness = 0.5
        settings.photo_gain = 0.2
        settings.photo_exposure = -6

    settings.save()
    print("[CAMERA_CORE] Auto-adjusted settings saved based on frame analysis.")


def set_cv_param(cap, prop, value):
    if value is not None and value >= 0:
        cap.set(prop, value)
