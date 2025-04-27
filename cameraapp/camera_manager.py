# camera_manager.py

import cv2
import threading
import time
import os

class CameraManager:
    def __init__(self, source=0, retry_delay=2.0, max_retries=5):
        self.source = source
        self.retry_delay = retry_delay
        self.max_retries = max_retries

        self.cap = None
        self.lock = threading.Lock()
        self.running = True
        self.frame = None

        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def _open_camera(self):
        cap = cv2.VideoCapture(self.source, cv2.CAP_V4L2)
        if cap.isOpened():
            print("[CameraManager] Camera opened")
            return cap
        else:
            print("[CameraManager] Failed to open camera")
            return None

    def _restart_camera(self):
        print("[CameraManager] Restarting camera")
        if self.cap:
            self.cap.release()
            time.sleep(1)

        attempts = 0
        while attempts < self.max_retries:
            cap = self._open_camera()
            if cap:
                self.cap = cap
                return True
            attempts += 1
            print(f"[CameraManager] Retry {attempts}/{self.max_retries} failed...")
            time.sleep(self.retry_delay)

        print("[CameraManager] Camera not available after retries")
        return False

    def _capture_loop(self):
        fail_count = 0
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                fail_count += 1
                if fail_count > 5:
                    print("[CameraManager] Too many failures, restarting camera.")
                    self._restart_camera()
                    fail_count = 0
                time.sleep(0.5)
                continue
            fail_count = 0
            with self.lock:
                self.frame = frame

    def get_frame(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        print("[CameraManager] Stopping camera")
        self.running = False
        if self.cap and self.cap.isOpened():
            self.cap.release()
