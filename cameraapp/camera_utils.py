# cameraapp/camera_utils.py

import time
import cv2
from django.apps import apps

def get_camera_settings():
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