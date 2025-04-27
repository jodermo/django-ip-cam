import threading
import time
from .camera_core import try_open_camera, apply_cv_settings, get_camera_settings

class LiveStreamJob:
    def __init__(self, camera_source, frame_callback=None):
        self.camera_source = camera_source
        self.frame_callback = frame_callback
        self.lock = threading.Lock()
        self.running = False
        self.latest_frame = None
        self.thread = None
        self.capture = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        with self.lock:
            self.running = False
            if self.capture:
                self.capture.release()
                self.capture = None

    def join(self, timeout=None):
