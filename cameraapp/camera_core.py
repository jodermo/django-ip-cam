# cameraapp/camera_core.py

import cv2
import os
from django.apps import apps
from dotenv import load_dotenv

load_dotenv()

CAMERA_URL_RAW = os.getenv("CAMERA_URL", "0")
CAMERA_URL = int(CAMERA_URL_RAW) if CAMERA_URL_RAW.isdigit() else CAMERA_URL_RAW

camera_instance = None


def init_camera():
    global camera_instance
    print(f"[CAMERA_CORE] Init requested. CAMERA_URL_RAW='{CAMERA_URL_RAW}', resolved='{CAMERA_URL}'")

    if camera_instance:
        print("[CAMERA_CORE] Releasing previous camera instance.")
        camera_instance.release()

    print(f"[CAMERA_CORE] Attempting to open camera from source: {CAMERA_URL}")
    camera_instance = cv2.VideoCapture(CAMERA_URL)

    if not camera_instance or not camera_instance.isOpened():
        print("[CAMERA_CORE] Failed to open camera.")
        return

    print("[CAMERA_CORE] Camera opened successfully.")
    try:
        CameraSettings = apps.get_model("cameraapp", "CameraSettings")
        settings = CameraSettings.objects.first()
        if not settings:
            print("[CAMERA_CORE] No CameraSettings in DB.")
            return

        def apply_param(prop_id, value, label):
            if value >= 0:
                ok = camera_instance.set(prop_id, value)
                print(f"[CAMERA_CORE] Set {label} to {value} → {'OK' if ok else 'FAIL'}")

        apply_param(cv2.CAP_PROP_BRIGHTNESS, settings.brightness, "Brightness")
        apply_param(cv2.CAP_PROP_CONTRAST, settings.contrast, "Contrast")
        apply_param(cv2.CAP_PROP_SATURATION, settings.saturation, "Saturation")
        apply_param(cv2.CAP_PROP_EXPOSURE, settings.exposure, "Exposure")
        apply_param(cv2.CAP_PROP_GAIN, settings.gain, "Gain")

    except Exception as e:
        print(f"[CAMERA_CORE] Exception while applying settings: {e}")

def apply_camera_settings(cap, brightness=None, contrast=None):
    if brightness is not None:
        cap.set(cv2.CAP_PROP_BRIGHTNESS, brightness)
    if contrast is not None:
        cap.set(cv2.CAP_PROP_CONTRAST, contrast)
