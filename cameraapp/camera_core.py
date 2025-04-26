# cameraapp/camera_core.py

import os
import cv2
import time
from django.apps import apps
from cameraapp.models import CameraSettings
from dotenv import load_dotenv
load_dotenv()

CAMERA_URL_RAW = os.getenv("CAMERA_URL", "0")
CAMERA_URL = int(CAMERA_URL_RAW) if CAMERA_URL_RAW.isdigit() else CAMERA_URL_RAW

camera_instance = None


def try_open_camera(source, retries=3, delay=1.5):
    cap = None
    for i in range(retries):
        print(f"[CAMERA] Trying to open camera (attempt {i + 1})...")
        cap = cv2.VideoCapture(source)
        time.sleep(0.5)  # Give driver a moment
        if cap.isOpened():
            print("[CAMERA] Successfully opened.")
            return cap
        cap.release()
        time.sleep(delay)
    print("[CAMERA] Failed to open camera after retries.")
    return None

def init_camera():
    """Initialisiert die globale Kamera-Instanz mit gespeicherten Video-Settings."""
    global camera_instance

    print(f"[CAMERA_CORE] Init requested. CAMERA_URL_RAW='{CAMERA_URL_RAW}', resolved='{CAMERA_URL}'")

    if camera_instance:
        print("[CAMERA_CORE] Releasing previous camera instance.")
        camera_instance.release()

    print(f"[CAMERA_CORE] Attempting to open camera from source: {CAMERA_URL}")
    camera_instance = try_open_camera(CAMERA_URL, retries=3, delay=2.0)

    if not camera_instance or not camera_instance.isOpened():
        print("[CAMERA_CORE] Failed to open camera after retries.")
        return

    print("[CAMERA_CORE] Camera opened successfully.")

    try:
        CameraSettings = apps.get_model("cameraapp", "CameraSettings")
        settings = CameraSettings.objects.first()
        if not settings:
            print("[CAMERA_CORE] No CameraSettings in DB.")
            return

        # Set automatic or manual exposure mode
        if hasattr(settings, "video_exposure_mode") and settings.video_exposure_mode == "auto":
            print("[CAMERA_CORE] Setting exposure mode to AUTO.")
            # Je nach Kamera und Backend: 0.75 = auto, 0.25 = manual (V4L2)
            camera_instance.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
        else:
            print("[CAMERA_CORE] Setting exposure mode to MANUAL.")
            camera_instance.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)

        # Apply all remaining settings
        apply_cv_settings(camera_instance, settings, mode="video")

    except Exception as e:
        print(f"[CAMERA_CORE] Exception while applying settings: {e}")



def enable_auto_exposure(cap):
    # 0 = auto, 1 = manual (bei vielen V4L2-Backends)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)  # oder 0.25 je nach Backend


def apply_cv_settings(cap, settings, mode="video"):
    """
    Wendet OpenCV-Settings für Video- oder Foto-Modus an.
    - cap: cv2.VideoCapture
    - settings: CameraSettings-Objekt
    - mode: "video" oder "photo"
    """
    if not settings or not cap or not cap.isOpened():
        return

    prefix = "video_" if mode == "video" else "photo_"

    def apply_param(cap, name):
        value = getattr(settings, f"{prefix}{name}", -1)
        cap_prop = getattr(cv2, f"CAP_PROP_{name.upper()}")
        ok = cap.set(cap_prop, value)
        actual = cap.get(cap_prop)
        print(f"[CAMERA_CORE] {mode.upper()} Set {name} to {value} → {'OK' if ok else 'FAIL'}, actual={actual}")


    for param in ["brightness", "contrast", "saturation", "exposure", "gain"]:
        apply_param(cap, param)



def apply_camera_settings(cap, brightness=None, contrast=None):
    """Direkte Einstellung einzelner Parameter ohne Settings-Modell."""
    if cap and cap.isOpened():
        if brightness is not None:
            cap.set(cv2.CAP_PROP_BRIGHTNESS, brightness)
        if contrast is not None:
            cap.set(cv2.CAP_PROP_CONTRAST, contrast)

def apply_video_settings(capture):
    settings = CameraSettings.objects.first()
    if settings:
        for param in ["brightness", "contrast", "saturation", "exposure", "gain"]:
            value = getattr(settings, f"video_{param}", -1)
            if value >= 0:
                ok = capture.set(getattr(cv2, f"CAP_PROP_{param.upper()}"), value)
                actual = capture.get(getattr(cv2, f"CAP_PROP_{param.upper()}"))
                print(f"[VIDEO] Set {param} = {value} → {'OK' if ok else 'FAIL'}, actual={actual}")


def apply_auto_settings(settings):
    """
    Setzt pauschale Auto-Settings für Fotos.
    Hinweis: Diese Werte sind erfahrungsbasiert und sollten ggf. angepasst werden.
    """
    settings.photo_brightness = -1  # OpenCV: -1 = auto (je nach Treiber)
    settings.photo_contrast = -1
    settings.photo_saturation = -1
    settings.photo_exposure = -1
    settings.photo_gain = -1
    settings.save()
    print("[CAMERA_CORE] Auto photo settings applied (static defaults)")


def auto_adjust_from_frame(frame, settings):
    """
    Analysiert Helligkeit des Bildes und passt Einstellungen dynamisch an.
    - frame: aktuelles Kamera-Frame (BGR)
    - settings: CameraSettings-Objekt
    """
    if frame is None or settings is None:
        print("[CAMERA_CORE] Cannot auto-adjust: invalid input.")
        return

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    avg = gray.mean()
    print(f"[CAMERA_CORE] Frame average brightness: {avg:.2f}")

    # Beispiel-Logik (optimierbar je nach Kamera)
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
    if value >= 0:
        cap.set(prop, value)

def apply_photo_settings(camera, settings):
    set_cv_param(camera, cv2.CAP_PROP_BRIGHTNESS, settings.photo_brightness)
    set_cv_param(camera, cv2.CAP_PROP_CONTRAST, settings.photo_contrast)
    set_cv_param(camera, cv2.CAP_PROP_SATURATION, settings.photo_saturation)
    set_cv_param(camera, cv2.CAP_PROP_EXPOSURE, settings.photo_exposure)
    set_cv_param(camera, cv2.CAP_PROP_GAIN, settings.photo_gain)
