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

    def _run(self):
        from .camera_core import try_open_camera, apply_video_settings

        retry_limit = 5
        retry_delay = 2.0

        def reconnect():
            print("[LIVE_STREAM_JOB] Attempting to reconnect camera...")
            cap = try_open_camera(self.camera_source, retries=retry_limit, delay=retry_delay)
            if cap and cap.isOpened():
                settings = get_camera_settings()
                apply_cv_settings(cap, settings, mode="video")
                print("[LIVE_STREAM_JOB] Reconnection successful.")
                return cap
            print("[LIVE_STREAM_JOB] Reconnection failed.")
            return None

        self.capture = reconnect()
        if not self.capture:
            self.running = False
            return

        print("[LIVE_STREAM_JOB] Camera streaming started.")

        while self.running:
            ret, frame = self.capture.read()
            if not ret:
                print("[LIVE_STREAM_JOB] Frame read failed, releasing and retrying...")
                self.capture.release()
                self.capture = reconnect()
                if not self.capture:
                    print("[LIVE_STREAM_JOB] Giving up after retries.")
                    self.running = False
                    break
                continue

            if self.frame_callback:
                self.frame_callback(frame)

            with self.lock:
                self.latest_frame = frame.copy()

            time.sleep(0.03)  # ~30 FPS

        if self.capture:
            self.capture.release()
            self.capture = None

        print("[LIVE_STREAM_JOB] Stopped.")

        self.capture = try_open_camera(self.camera_source, retries=5, delay=2.0)
        if not self.capture or not self.capture.isOpened():
            print("[LIVE_STREAM_JOB] Error: Unable to open camera.")
            self.running = False
            return
        from .camera_core import apply_video_settings
        apply_video_settings(self.capture)
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
            if self.latest_frame is None:
                print("[LIVE_STREAM_JOB] Keine Frames vorhanden.")
            return self.latest_frame.copy() if self.latest_frame is not None else None


