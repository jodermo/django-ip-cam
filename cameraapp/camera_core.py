# cameraapp/camera_core.py

import os
import cv2
import time
import threading
from cameraapp.models import CameraSettings
from .camera_utils import get_camera_settings, apply_cv_settings, try_open_camera, force_restart_livestream, get_camera_settings_safe, try_open_camera_safe
from .globals import camera_lock, camera_capture

from dotenv import load_dotenv
load_dotenv()

CAMERA_URL_RAW = os.getenv("CAMERA_URL", "0")
CAMERA_URL = int(CAMERA_URL_RAW) if CAMERA_URL_RAW.isdigit() else CAMERA_URL_RAW


def init_camera():
    global camera_capture

    with camera_lock:
        print(f"[CAMERA_CORE] Init requested. CAMERA_URL_RAW='{CAMERA_URL_RAW}', resolved='{CAMERA_URL}'")

        if camera_capture:
            print("[CAMERA_CORE] Releasing previous camera instance.")
            camera_capture.release()
            time.sleep(1.0)

        print(f"[CAMERA_CORE] Attempting to open camera from source: {CAMERA_URL}")
        camera_capture = try_open_camera(CAMERA_URL, retries=3, delay=2.0)

        if not camera_capture or not camera_capture.isOpened():
            print("[CAMERA_CORE] Failed to open camera after retries.")
            return

        print("[CAMERA_CORE] Camera opened successfully.")

        settings = get_camera_settings_safe()  
        if not settings:
            print("[CAMERA_CORE] No CameraSettings found in DB.")
            return

        apply_cv_settings(
            camera_capture,
            settings,
            mode="video",
            reopen_callback=lambda: try_open_camera(CAMERA_URL)
        )



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





def apply_camera_settings(cap, brightness=None, contrast=None):
    if cap and cap.isOpened():
        if brightness is not None:
            cap.set(cv2.CAP_PROP_BRIGHTNESS, brightness)
        if contrast is not None:
            cap.set(cv2.CAP_PROP_CONTRAST, contrast)

def apply_video_settings(cap):
    from cameraapp.models import CameraSettings
    settings = CameraSettings.objects.first()
    if not cap or not settings or not cap.isOpened():
        return

    if settings.video_exposure_mode == "auto":
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
    else:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)


    for param in ["brightness", "contrast", "saturation", "exposure", "gain"]:
        value = getattr(settings, f"video_{param}", -1)
        if value >= 0:
            ok = cap.set(getattr(cv2, f"CAP_PROP_{param.upper()}"), value)
            actual = cap.get(getattr(cv2, f"CAP_PROP_{param.upper()}"))
            print(f"[VIDEO] Set {param} = {value} → {'OK' if ok else 'FAIL'}, actual={actual}")


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


def get_shared_camera():
    global camera_capture
    with camera_lock:
        if camera_capture is None or not camera_capture.isOpened():
            camera_capture = cv2.VideoCapture(0)
        return camera_capture


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

def apply_photo_settings(camera, settings):
    set_cv_param(camera, cv2.CAP_PROP_BRIGHTNESS, settings.photo_brightness)
    set_cv_param(camera, cv2.CAP_PROP_CONTRAST, settings.photo_contrast)
    set_cv_param(camera, cv2.CAP_PROP_SATURATION, settings.photo_saturation)
    set_cv_param(camera, cv2.CAP_PROP_EXPOSURE, settings.photo_exposure)
    set_cv_param(camera, cv2.CAP_PROP_GAIN, settings.photo_gain)
    if getattr(settings, "photo_exposure_mode", "manual") == "auto":
        camera.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
    else:
        camera.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)

def enable_auto_exposure(cap):
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)

