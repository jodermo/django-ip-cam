# cameraapp/livestream_job.py

import threading
import time
import logging
from typing import Callable, Optional, Union

from .globals import livestream_lock

logger = logging.getLogger(__name__)

class LiveStreamJob:
    """
    Manages a live camera stream on a background thread.

    Attributes:
        camera_source: index or URL of the camera
        frame_callback: optional function to receive each frame
        shared_capture: optionally reuse an existing VideoCapture
    """
    def __init__(
        self,
        camera_source: Union[int, str],
        frame_callback: Optional[Callable[[any], None]] = None,
        shared_capture=None
    ):
        self.camera_source = camera_source
        self.frame_callback = frame_callback
        self.shared_capture = shared_capture
        self.capture = shared_capture
        self.latest_frame = None
        self.running = False
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Begin streaming in a daemon thread."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(
            target=self._run,
            name="LiveStreamJob",
            daemon=True
        )
        self.thread.start()
        logger.info("[LIVE] LiveStreamJob started")

    def stop(self) -> None:
        """Stop streaming and release capture if not shared."""
        with livestream_lock:
            self.running = False
            if self.capture and not self.shared_capture:
                try:
                    self.capture.release()
                    logger.info("[LIVE] Camera capture released")
                except Exception as e:
                    logger.warning(f"[LIVE] Error releasing capture: {e}")
                finally:
                    self.capture = None
        logger.info("[LIVE] LiveStreamJob stop called")

    def restart(self) -> None:
        """Stop and then restart the streaming thread."""
        logger.info("[LIVE] Restarting LiveStreamJob")
        self.stop()
        time.sleep(1.0)
        self.start()

    def recover(self) -> None:
        """Attempt recovery by stopping, joining, then restarting."""
        logger.info("[LIVE] Recovering LiveStreamJob")
        self.stop()
        self.join(timeout=2.0)
        time.sleep(1.0)
        self.start()

    def join(self, timeout: Optional[float] = None) -> None:
        """Wait for the streaming thread to finish."""
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout)
            logger.info("[LIVE] LiveStreamJob thread joined")

    def _run(self) -> None:
        """Internal loop: open camera, read frames, and invoke callbacks."""
        def reconnect() -> Optional[any]:
            if self.shared_capture:
                logger.debug("[LIVE] Using shared capture")
                return self.shared_capture

            from .camera_utils import try_open_camera, apply_cv_settings, get_camera_settings

            logger.info(f"[LIVE] Opening camera source: {self.camera_source}")
            cap = try_open_camera(self.camera_source, retries=5, delay=2.0)
            if cap and cap.isOpened():
                settings = get_camera_settings()
                apply_cv_settings(cap, settings, mode="video")
                logger.info("[LIVE] Camera opened successfully")
                return cap

            logger.error("[LIVE] Failed to open camera after retries")
            return None

        self.capture = reconnect()
        if not self.capture:
            self.running = False
            return

        logger.info("[LIVE] Streaming loop entering")
        while self.running:
            try:
                ret, frame = self.capture.read()
                if not ret or frame is None:
                    logger.debug("[LIVE] Frame read failed, retrying...")
                    time.sleep(0.2)
                    continue

                if self.frame_callback:
                    try:
                        self.frame_callback(frame)
                    except Exception as cb_err:
                        logger.warning(f"[LIVE] Frame callback error: {cb_err}")

                with livestream_lock:
                    self.latest_frame = frame.copy()

                time.sleep(0.03)
            except Exception as run_err:
                logger.error(f"[LIVE] Exception in streaming loop: {run_err}")
                break

        # Clean up capture if not shared
        if self.capture and not self.shared_capture:
            try:
                self.capture.release()
            except Exception as e:
                logger.warning(f"[LIVE] Error releasing capture on exit: {e}")
            finally:
                self.capture = None

        logger.info("[LIVE] Streaming loop exited")

    def get_frame(self) -> Optional[any]:
        """Retrieve the last captured frame, if any."""
        with livestream_lock:
            if self.latest_frame is not None:
                return self.latest_frame.copy()
        return None