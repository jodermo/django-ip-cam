import threading
from .globals import app_globals
from .camera_core import init_camera

class CameraInitMiddleware:
    _init_lock = threading.Lock()
    _initialized = False

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not CameraInitMiddleware._initialized:
            with CameraInitMiddleware._init_lock:
                if not CameraInitMiddleware._initialized:
                    print("[CAMERA_INIT] First request → initializing camera and scheduler")
                    try:
                        init_camera()

                        from .camera_utils import start_camera_watchdog
                        start_camera_watchdog()
                        print("[CAMERA_INIT] Watchdog gestartet.")

                        from .scheduler import start_photo_scheduler
                        thread = threading.Thread(target=start_photo_scheduler, daemon=True)
                        thread.start()
                        app_globals.photo_scheduler_thread = thread
                        print("[CAMERA_INIT] Timelapse gestartet.")
                    except Exception as e:
                        print(f"[CAMERA_INIT] Fehler bei Init: {e}")

                    CameraInitMiddleware._initialized = True

        return self.get_response(request)
