# cameraapp/middleware.py

import threading
from .camera_core import init_camera
from .globals import app_globals

camera_init_lock = threading.Lock()

class CameraInitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Nur ein Thread darf initialisieren
        if not app_globals.camera or not app_globals.camera.is_available():
            with camera_init_lock:
                if not app_globals.camera or not app_globals.camera.is_available():
                    try:
                        print("[CAMERA_INIT_MIDDLEWARE] Initializing camera globally...")
                        init_camera()
                    except Exception as e:
                        print(f"[CAMERA_INIT_MIDDLEWARE] Failed to initialize camera: {e}")

        return self.get_response(request)
