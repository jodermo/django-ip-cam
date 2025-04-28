# cameraapp/middleware.py

from .camera_core import init_camera

class CameraInitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.initialized = False

    def __call__(self, request):
        if not self.initialized:
            print("[CAMERA_INIT] First request → initializing camera")
            try:
                init_camera()
                print("[CAMERA_INIT] Kamera init erfolgreich.")
            except Exception as e:
                print(f"[CAMERA_INIT] Fehler bei Kamera-Init: {e}")
            self.initialized = True

        return self.get_response(request)
