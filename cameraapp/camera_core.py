# cameraapp/camera_core.py

import os
import cv2
import time
import threading
import glob
from cameraapp.models import CameraSettings
from .camera_utils import safe_restart_camera_stream, get_camera_settings, apply_cv_settings, try_open_camera, release_and_reset_camera, force_restart_livestream, get_camera_settings_safe, try_open_camera_safe, update_livestream_job
from .globals import camera_lock, camera, latest_frame_lock, latest_frame
from .camera_manager import CameraManager

from dotenv import load_dotenv
load_dotenv()



def find_working_camera_device():
    candidates = sorted(glob.glob("/dev/video*"))
    print(f"[CAMERA_CORE] Scanning for available video devices: {candidates}")
    for device in candidates:
        try:
            cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
            if cap.isOpened():
                ret, _ = cap.read()
                cap.release()
                if ret:
                    print(f"[CAMERA_CORE] Found working camera: {device}")
                    return device
        except Exception as e:
            print(f"[CAMERA_CORE] Error testing {device}: {e}")
    print("[CAMERA_CORE] No working camera found.")
    return None



CAMERA_URL_RAW = os.getenv("CAMERA_URL", "0")

if CAMERA_URL_RAW == "0" and not os.path.exists("/dev/video0"):
    fallback_device = find_working_camera_device()
    CAMERA_URL = fallback_device if fallback_device else 0
    print(f"[CAMERA_CORE] CAMERA_URL fallback resolved to: {CAMERA_URL}")
else:
    CAMERA_URL = int(CAMERA_URL_RAW) if CAMERA_URL_RAW.isdigit() else CAMERA_URL_RAW

def init_camera():
    global camera, livestream_job, update_latest_frame, latest_frame

    if camera and camera.is_available():
        print("[CAMERA_CORE] Camera already initialized")
        return

    print("[CAMERA_CORE] Initializing new CameraManager...")

    try:
        source = CAMERA_URL
        if source == "0" and not os.path.exists("/dev/video0"):
            fallback = find_working_camera_device()
            source = fallback if fallback else 0

        new_camera = CameraManager(source=source)

        if new_camera.is_available():
            camera = new_camera
            print("[CAMERA_CORE] CameraManager initialized and running.")

            # Starte Livestream nur wenn nicht aktiv
            if not livestream_job or not livestream_job.running:
                job = safe_restart_camera_stream(
                    camera_source=CAMERA_URL,
                    frame_callback=lambda f: update_latest_frame(f)
                )
                if job:
                    livestream_job = job
                    update_livestream_job(livestream_job)
                else:
                    print("[CAMERA_CORE] Failed to start livestream job.")
        else:
            print("[CAMERA_CORE] Camera could not be initialized.")

    except Exception as e:
        print(f"[CAMERA_CORE] Exception during camera init: {e}")



def reset_to_default():
    settings = CameraSettings.objects.first()
    if not settings:
        print("[RESET] Keine CameraSettings gefunden. Abbruch.")
        return

    # Foto-Modus
    settings.photo_exposure_mode = "manual"
    settings.photo_brightness = 128.0
    settings.photo_contrast = 32.0
    settings.photo_saturation = 64.0
    settings.photo_exposure = -6.0
    settings.photo_gain = 4.0

    # Video-Modus
    settings.video_exposure_mode = "auto"
    settings.video_brightness = 128.0
    settings.video_contrast = 32.0
    settings.video_saturation = 64.0
    settings.video_exposure = -6.0
    settings.video_gain = 4.0

    settings.save()
    print("[RESET] CameraSettings auf Default zurückgesetzt (Auto-Modus, keine Werte gesetzt).")




def apply_auto_settings(settings, mode="photo"):
    if mode == "photo":
        settings.photo_exposure_mode = "auto"
        settings.photo_brightness = 128.0
        settings.photo_contrast = 32.0
        settings.photo_saturation = 64.0
        settings.photo_exposure = -1   # ignoriert bei auto
        settings.photo_gain = -1       # ignoriert bei auto
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

