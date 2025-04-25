# scheduler.py
import os
import time
import cv2
from datetime import datetime
from .models import CameraSettings
from django.conf import settings

PHOTO_DIR = os.path.join(settings.MEDIA_ROOT, "photos")
os.makedirs(PHOTO_DIR, exist_ok=True)

def take_photo():
    settings_obj = CameraSettings.objects.first()
    url = settings_obj.default_camera_url if settings_obj else "0"
    camera_url = int(url) if url.isdigit() else url

    cap = cv2.VideoCapture(camera_url)
    if not cap.isOpened():
        print("[PHOTO] Camera not available.")
        return
    ret, frame = cap.read()
    if ret:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(PHOTO_DIR, f"photo_{timestamp}.jpg")
        cv2.imwrite(path, frame)
        print(f"[PHOTO] Saved: {path}")
    else:
        print("[PHOTO] Failed to capture.")
    cap.release()

def start_photo_scheduler():
    while True:
        settings_obj = CameraSettings.objects.first()
        if settings_obj and settings_obj.timelapse_enabled:
            take_photo()
            interval = settings_obj.photo_interval_min
        else:
            interval = 15  # fallback
        time.sleep(interval * 60)