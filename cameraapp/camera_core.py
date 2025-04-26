import os
import cv2
import time
from django.apps import apps
from .globals import camera_lock, latest_frame, latest_frame_lock
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
        time.sleep(0.5)
        if cap.isOpened():
            print("[CAMERA] Successfully opened.")
            return cap
        cap.release()
        time.sleep(delay)
    print("[CAMERA] Failed to open camera after retries.")
    return None


def init_camera():
    global camera_instance
    from cameraapp.models import CameraSettings

    with camera_lock:
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
            settings = CameraSettings.objects.first()
            if not settings:
                print("[CAMERA_CORE] No CameraSettings in DB.")
                return

            if getattr(settings, "video_exposure_mode", "manual") == "auto":
                print("[CAMERA_CORE] Setting exposure mode to AUTO.")
                camera_instance.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
            else:
                print("[CAMERA_CORE] Setting exposure mode to MANUAL.")
                camera_instance.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)

            apply_cv_settings(
                camera_instance,
                settings,
                mode="video",
                reopen_callback=lambda: try_open_camera(CAMERA_URL)
            )

        except Exception as e:
            print(f"[CAMERA_CORE] Exception while applying settings: {e}")

def reset_to_default():
    settings = CameraSettings.objects.first()
    if not settings:
        print("[RESET] Keine CameraSettings gefunden. Abbruch.")
        return

    # Reset für Foto-Modus
    settings.photo_exposure_mode = "auto"
    settings.photo_brightness = -1
    settings.photo_contrast = -1
    settings.photo_saturation = -1
    settings.photo_exposure = -1
    settings.photo_gain = -1

    # Reset für Video-Modus
    settings.video_exposure_mode = "auto"
    settings.video_brightness = -1
    settings.video_contrast = -1
    settings.video_saturation = -1
    settings.video_exposure = -1
    settings.video_gain = -1

    settings.save()
    print("[RESET] CameraSettings auf Default zurückgesetzt (Auto-Modus, keine Werte gesetzt).")


def apply_cv_settings(cap, settings, mode="video", reopen_callback=None):

    if not settings:
        print("[CAMERA_CORE] Keine Einstellungen übergeben.")
        return

    if not cap or not cap.isOpened():
        print("[CAMERA_CORE] Kamera nicht geöffnet. Versuche Neustart...")

        if reopen_callback:
            cap = reopen_callback()
            if not cap or not cap.isOpened():
                print("[CAMERA_CORE] Kamera-Neustart fehlgeschlagen.")
                return
            else:
                print("[CAMERA_CORE] Kamera erfolgreich neu geöffnet.")
        else:
            print("[CAMERA_CORE] Kein reopen_callback definiert – Abbruch.")
            return

    prefix = "video_" if mode == "video" else "photo_"

    # ---- AUTO EXPOSURE ----
    exposure_mode = getattr(settings, f"{prefix}exposure_mode", "manual")
    if exposure_mode == "auto":
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)  # Auto-Modus
        print(f"[CAMERA_CORE] {mode.upper()} exposure_mode = AUTO")
    else:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # Manuell
        print(f"[CAMERA_CORE] {mode.upper()} exposure_mode = MANUAL")

    def apply_param(cap, name):
        try:
            value = float(getattr(settings, f"{prefix}{name}", None))
            if value < 0:
                print(f"[CAMERA_CORE] {name} deaktiviert (value={value})")
                return
        except (TypeError, ValueError):
            print(f"[WARNING] Ungültiger Wert für {prefix}{name}")
            return

        cap_prop = getattr(cv2, f"CAP_PROP_{name.upper()}", None)
        if cap_prop is None:
            print(f"[WARNING] Unbekannte OpenCV-Eigenschaft: {name}")
            return

        ok = cap.set(cap_prop, value)
        actual = cap.get(cap_prop)
        print(f"[CAMERA_CORE] {mode.upper()} Set {name} = {value} → {'OK' if ok else 'FAIL'}, actual={actual}")


    for param in ["brightness", "contrast", "saturation", "exposure", "gain"]:
        apply_param(cap, param)


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


def apply_auto_settings(settings):
    settings.photo_brightness = -1
    settings.photo_contrast = -1
    settings.photo_saturation = -1
    settings.photo_exposure = -1
    settings.photo_gain = -1
    settings.save()
    print("[CAMERA_CORE] Auto photo settings applied (static defaults)")

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
