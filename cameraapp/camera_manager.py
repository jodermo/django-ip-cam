# cameraapp/camera_manager.py

import cv2
import threading
import time
import os
import atexit
from .globals import app_globals


if globals().get("camera") is not None:
    print("[CameraManager] Warning: Existing camera instance found. Replacing it.")
    globals()["camera"].stop()
    globals()["camera"] = None

def cleanup_camera():
    if globals().get("camera"):
        globals()["camera"].stop()

atexit.register(cleanup_camera)

class CameraManager:
    def __init__(self, source=0, retry_delay=2.0, max_retries=5):
        self.source = source
        self.retry_delay = retry_delay
        self.max_retries = max_retries

        self.cap = None
        self.lock = threading.Lock()
        self.running = True
        self.frame = None
        # Öffne Kamera direkt bei Initialisierung
        if not self._restart_camera():
            self.running = False
            print("[CameraManager] Failed to start camera thread due to unavailable camera.")
            return

        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        globals()["camera"] = self

        app_globals.camera = self
        

    def _open_camera(self):
        cap = cv2.VideoCapture(self.source, cv2.CAP_V4L2)
        if cap.isOpened():
            # Testlesung
            ret, _ = cap.read()
            if ret:
                print("[CameraManager] Camera opened and first frame read successfully")
                return cap
            else:
                print("[CameraManager] Camera opened but failed to read frame")
                cap.release()
        else:
            print("[CameraManager] Failed to open camera")
        return None


    def _restart_camera(self):
        print("[CameraManager] Restarting camera")
        if self.cap:
            self.cap.release()
            self.cap = None
            self._wait_for_device_release()

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
        if not self.cap:
            print("[CameraManager] No initial camera instance. Capture loop exiting.")
            return

        fail_count = 0

        while self.running:
            if not self.cap:
                print("[CameraManager] cap is None. Attempting to restart camera...")
                if not self._restart_camera():
                    time.sleep(self.retry_delay)
                    continue

            ret, frame = self.cap.read()

            if not ret or frame is None:
                fail_count += 1
                print(f"[CameraManager] Frame read failed ({fail_count}/5)")

                if fail_count > 5:
                    print("[CameraManager] Too many failures, restarting camera...")
                    if not self._restart_camera():
                        time.sleep(self.retry_delay)
                    fail_count = 0
                else:
                    time.sleep(0.3)
                continue

            fail_count = 0
            with self.lock:
                self.frame = frame

            time.sleep(0.01)  # Minimaler Delay, entlastet CPU

    def is_available(self):
        with self.lock:
            return self.cap is not None and self.cap.isOpened()


    def get_frame(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        print("[CameraManager] Stopping camera")
        self.running = False
        if self.cap:
            self.cap.release()
            self.cap = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        globals()["camera"] = None




    def frame_provider(self):
        return self.get_frame()


    def _wait_for_device_release(self, timeout=5.0):
        start = time.time()
        while time.time() - start < timeout:
            if not os.path.exists("/dev/video0"):
                print("[CameraManager] /dev/video0 not found, waiting...")
            else:
                cap = cv2.VideoCapture(self.source, cv2.CAP_V4L2)
                if cap.isOpened():
                    cap.release()
                    print("[CameraManager] Device available again.")
                    return True
            time.sleep(0.5)
        print("[CameraManager] Timeout waiting for device to become available")
        return False



    def restart(self) -> bool:
        """
        Try to reopen/releases and reopen the same capture device.
        Returns True on success.
        """
        with self.lock:
            return self._restart_camera()