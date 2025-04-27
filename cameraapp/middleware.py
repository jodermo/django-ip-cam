# cameraapp/middleware.py

from .camera_core import init_camera

class CameraInitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.initialized = False

    def __call__(self, request):
        if not self.initialized:
            try:
                init_camera()
                self.initialized = True
            except Exception as e:
                print(f"[CAMERA_INIT_MIDDLEWARE] Failed to initialize camera: {e}")
        return self.get_response(request)
