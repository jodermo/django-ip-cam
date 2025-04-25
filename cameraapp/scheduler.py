import os
import time
import cv2
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

CAMERA_URL_RAW = os.getenv("CAMERA_URL")
CAMERA_URL = int(CAMERA_URL_RAW) if CAMERA_URL_RAW.isdigit() else CAMERA_URL_RAW

PHOTO_DIR = os.path.join("media", "photos")
os.makedirs(PHOTO_DIR, exist_ok=True)

def take_photo():
    cap = cv2.VideoCapture(CAMERA_URL)
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
        take_photo()
        time.sleep(15 * 60)  # alle 15 Minuten
