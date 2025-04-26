import threading
import time
import cv2
from cameraapp.models import CameraSettings

def apply_video_settings(capture):
    settings = CameraSettings.objects.first()
    if settings:
        for param in ["brightness", "contrast", "saturation", "exposure", "gain"]:
            value = getattr(settings, f"video_{param}", -1)
            if value >= 0:
                capture.set(getattr(cv2, f"CAP_PROP_{param.upper()}"), value)
                print(f"[VIDEO] Set {param} = {value}")


class LiveStreamJob:
    def __init__(self, camera_source, frame_callback=None):
        self.camera_source = camera_source
        self.frame_callback = frame_callback  # optional hook
        self.lock = threading.Lock()
        self.running = False
        self.latest_frame = None
        self.thread = None
        self.capture = None


    def start(self):
        if self.running:
            return
        self.capture = cv2.VideoCapture(self.camera_source)
        if not self.capture.isOpened():
            print("[LIVE_STREAM_JOB] Error: Unable to open camera.")
            self.capture.release()
            self.capture = None
            self.running = False
            return  # <--- notwendig
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()


    def stop(self):
        with self.lock:
            self.running = False
            if self.capture:
                self.capture.release()
                self.capture = None

    def _run(self):
        self.capture = cv2.VideoCapture(self.camera_source)
        apply_video_settings(self.capture)
        if not self.capture.isOpened():
            print("[LIVE_STREAM_JOB] Error: Unable to open camera.")
            self.running = False
            return

        print("[LIVE_STREAM_JOB] Camera streaming started.")
        while self.running:
            ret, frame = self.capture.read()
            if not ret:
                time.sleep(0.1)
                continue

            if self.frame_callback:
                self.frame_callback(frame)

            with self.lock:
                self.latest_frame = frame.copy()

            time.sleep(0.03)  # ca. 30 fps

        if self.capture:
            self.capture.release()
            self.capture = None
        print("[LIVE_STREAM_JOB] Stopped.")

    def get_frame(self):
        with self.lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

