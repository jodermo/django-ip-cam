import threading
import time
from .camera_utils import try_open_camera, apply_cv_settings, get_camera_settings

class LiveStreamJob:
    def __init__(self, camera_source, frame_callback=None, shared_capture=None):
        self.camera_source = camera_source
        self.frame_callback = frame_callback
        self.lock = threading.Lock()
        self.running = False
        self.latest_frame = None
        self.thread = None
        self.capture = shared_capture or None
        self.shared_capture = shared_capture

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        with self.lock:
            self.running = False
            if self.capture and not self.shared_capture:
                self.capture.release()
                self.capture = None

    def restart(self):
        self.stop()
        time.sleep(1.0)
        self.start()

    def recover(self):
        print("[LIVE_STREAM_JOB] Attempting recovery...")
        self.stop()
        self.join(timeout=2.0)
        time.sleep(1.0)
        self.start()

    def join(self, timeout=None):
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout)

    def _run(self):
        def reconnect():
            if self.shared_capture:
                print("[LIVE_STREAM_JOB] Shared capture provided — skipping reconnect.")
                return self.shared_capture
            print("[LIVE_STREAM_JOB] Attempting to open camera...")
            cap = try_open_camera(self.camera_source, retries=5, delay=2.0)
            if cap and cap.isOpened():
                settings = get_camera_settings()
                apply_cv_settings(cap, settings, mode="video")
                print("[LIVE_STREAM_JOB] Camera opened successfully.")
                return cap
            print("[LIVE_STREAM_JOB] Failed to open camera.")
            return None

        self.capture = reconnect()
        if not self.capture or not self.capture.isOpened():
            self.running = False
            return

        print("[LIVE_STREAM_JOB] Streaming started.")
        while self.running:
            ret, frame = self.capture.read()
            if not ret or frame is None:
                print("[LIVE_STREAM_JOB] Frame read failed.")
                time.sleep(0.2)
                continue

            if self.frame_callback:
                self.frame_callback(frame)

            with self.lock:
                self.latest_frame = frame.copy()

            time.sleep(0.03)

        if self.capture and not self.shared_capture:
            self.capture.release()
            self.capture = None

        print("[LIVE_STREAM_JOB] Stopped.")

    def get_frame(self):
        with self.lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None
