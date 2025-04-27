# cameraapp/livestream_job.py

import threading
import time
import logging
from typing import Callable, Optional, Union, Any

from . import globals as app_globals

logger = logging.getLogger(__name__)


def lazy_imports():
    global apply_cv_settings, get_camera_settings, force_device_reset
    from .camera_utils import apply_cv_settings, get_camera_settings, force_device_reset


class LiveStreamJob:
    """
    Background thread for capturing frames from CameraManager.

    Features:
    - Auto reconnect with exponential backoff
    - Optional frame callback
    - Thread-safe access to the latest frame
    """
    def __init__(
        self,
        camera_source: Union[int, str],
        frame_callback: Optional[Callable[[Any], None]] = None,
        shared_capture=None,
        max_retries: int = 5,
        base_delay: float = 2.0
    ):
        global app_globals

        self.camera_source = camera_source
        self.frame_callback = frame_callback
        self.shared_capture = shared_capture
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.max_retries = max_retries
        self.base_delay = base_delay

        if shared_capture is not None:
            self.capture = shared_capture
        elif app_globals.camera and getattr(app_globals.camera, "cap", None) and app_globals.camera.cap.isOpened():
            self.capture = app_globals.camera.cap
        else:
            logger.error("LiveStreamJob initialized without valid capture source.")
            self.capture = None


    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, name="LiveStreamJob", daemon=True)
        self.thread.start()
        logger.info("LiveStreamJob started")

    def stop(self) -> None:
        global app_globals
        with app_globals.livestream_lock:
            self.running = False
            if self.capture and not self.shared_capture:
                try:
                    self.capture.release()
                    logger.info("Camera capture released")
                except Exception as e:
                    logger.warning(f"Error releasing capture: {e}")
                finally:
                    self.capture = None

    def restart(self) -> None:
        logger.info("Restarting LiveStreamJob")
        self.stop()
        time.sleep(1.0)
        self.start()

    def join(self, timeout: Optional[float] = None) -> None:
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout)
            logger.info("LiveStreamJob thread joined")

    def _run(self) -> None:
        lazy_imports()
        self.capture = self._connect_with_retries()
        if not self.capture:
            self.running = False
            logger.error("LiveStreamJob could not connect to camera. Exiting thread.")
            return

        logger.info("LiveStreamJob capture loop started")
        while self.running:
            try:
                ret, frame = self.capture.read()
                if not ret or frame is None:
                    logger.warning("Frame read failed, attempting reconnect")
                    self.capture = self._connect_with_retries()
                    if not self.capture:
                        break
                    continue

                if self.frame_callback:
                    try:
                        self.frame_callback(frame)
                    except Exception as cb_err:
                        logger.warning(f"Frame callback error: {cb_err}")

                time.sleep(0.03)

            except Exception as err:
                logger.error(f"Exception in LiveStreamJob loop: {err}")
                break

        self._cleanup()
        logger.info("LiveStreamJob capture loop exited")

    def _connect_with_retries(self):
        lazy_imports()
        delay = self.base_delay
        for attempt in range(1, self.max_retries + 1):
            logger.info(f"Attempt {attempt} to connect to camera")
            if self.is_camera_ready():
                settings = get_camera_settings()
                if settings:
                    try:
                        apply_cv_settings(app_globals.camera.cap, settings, mode="video")
                        logger.info("Camera settings applied successfully")
                    except Exception as e:
                        logger.warning(f"Failed to apply camera settings: {e}")
                return app_globals.camera.cap

            logger.warning(f"Camera not ready, retrying in {delay} seconds")
            time.sleep(delay)
            delay *= 2

        logger.error("Exceeded maximum retry attempts. Trying forced reset.")
        try:
            device_path = str(self.camera_source) if isinstance(self.camera_source, str) else "/dev/video0"
            logger.warning(f"Attempting forced reset of device: {device_path}")
            force_device_reset(device_path)
            time.sleep(3)
        except Exception as e:
            logger.error(f"force_device_reset failed: {e}")

        if self.is_camera_ready():
            return app_globals.camera.cap
        return None


    def _cleanup(self) -> None:
        if self.capture and not self.shared_capture:
            try:
                self.capture.release()
            except Exception as e:
                logger.warning(f"Error releasing capture on cleanup: {e}")
            finally:
                self.capture = None

    def get_frame(self) -> Optional[Any]:
        global app_globals
        with app_globals.latest_frame_lock:
            return app_globals.latest_frame.copy() if app_globals.latest_frame is not None else None

        
    def is_camera_ready(self) -> bool:
        global app_globals
        return hasattr(app_globals.camera, "cap") and app_globals.camera.cap and app_globals.camera.cap.isOpened()

