import os
import cv2
import time
# camera_core.py
import cv2
import threading
from django.apps import apps
from .globals import camera_lock, latest_frame, latest_frame_lock
from cameraapp.models import CameraSettings
from dotenv import load_dotenv
load_dotenv()

CAMERA_URL_RAW = os.getenv("CAMERA_URL", "0")
CAMERA_URL = int(CAMERA_URL_RAW) if CAMERA_URL_RAW.isdigit() else CAMERA_URL_RAW

camera_instance = None
camera_capture = None
camera_lock = threading.Lock()

def try_open_camera(camera_source, retries=3, delay=1.0):
    import cv2
    import time
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



def get_camera_settings():
    return CameraSettings.objects.first()


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

        settings = get_camera_settings()
        if not settings:
            print("[CAMERA_CORE] No CameraSettings found in DB.")
            return

        exposure_mode = getattr(settings, "video_exposure_mode", "manual")
        if exposure_mode == "auto":
            print("[CAMERA_CORE] Setting exposure mode to AUTO.")
            camera_capture.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
        else:
            print("[CAMERA_CORE] Setting exposure mode to MANUAL.")
            camera_capture.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)

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

    def delayed_reinit():
        time.sleep(1.0)
        init_camera()

    threading.Thread(target=delayed_reinit).start()

def reset_to_default():
    settings = CameraSettings.objects.first()
    if not settings:
        print("[RESET] No CameraSettings found. Aborting.")
        return

    # Reset photo mode
    settings.photo_exposure_mode = "auto"
    settings.photo_brightness = -1
    settings.photo_contrast = -1
    settings.photo_saturation = -1
    settings.photo_exposure = -1
    settings.photo_gain = -1

    # Reset video mode
    settings.video_exposure_mode = "auto"
    settings.video_brightness = -1
    settings.video_contrast = -1
    settings.video_saturation = -1
    settings.video_exposure = -1
    settings.video_gain = -1

    settings.save()
    print("[RESET] CameraSettings reset to default (auto mode, no values set).")

    def delayed_reinit():
        time.sleep(1.0)
        init_camera()

    threading.Thread(target=delayed_reinit).start()


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
        # For many cameras: valid range is -1 to -13 (lower = darker)
        apply_param("exposure", -13.0, -1.0)


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
    settings.photo_exposure_mode = "auto"
    settings.photo_brightness = -1
    settings.photo_contrast = -1
    settings.photo_saturation = -1
    settings.photo_exposure = -1
    settings.photo_gain = -1
    settings.save()
    print("[CAMERA_CORE] Auto photo settings applied (mode=auto, all = -1)")



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
