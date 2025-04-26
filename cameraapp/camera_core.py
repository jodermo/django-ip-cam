# cameraapp/camera_core.py

import cv2
import os
from dotenv import load_dotenv

load_dotenv()

CAMERA_URL_RAW = os.getenv("CAMERA_URL", "0")
CAMERA_URL = int(CAMERA_URL_RAW) if CAMERA_URL_RAW.isdigit() else CAMERA_URL_RAW

camera_instance = None

def init_camera():
    global camera_instance
    if camera_instance:
        camera_instance.release()
    camera_instance = cv2.VideoCapture(CAMERA_URL)
    print(f"[CAMERA_CORE] Camera initialized from: {CAMERA_URL}")
    if not camera_instance.isOpened():
        print("[CAMERA_CORE] Failed to open camera.")
        camera_instance = None
