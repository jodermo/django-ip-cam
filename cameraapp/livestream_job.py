import threading
import time
import logging
from typing import Callable, Optional, Union
from .camera_utils import try_open_camera, apply_cv_settings, get_camera_settings, force_device_reset
from .globals import livestream_lock

logger = logging.getLogger(__name__)

class LiveStreamJob:
    """
    Background thread to continuously capture frames from a camera source.

    Features:
    - Auto-reconnect with exponential backoff
    - Configurable retry counts and delays
    - Safe start/stop/restart methods
    - Thread-safe latest frame access
    """
    def __init__(
        self,
        camera_source: Union[int, str],
        frame_callback: Optional[Callable[[any], None]] = None,
        shared_capture=None,
        max_retries: int = 5,
        base_delay: float = 2.0
    ):
        self.camera_source = camera_source
        self.frame_callback = frame_callback
        self.shared_capture = shared_capture
        self.capture = shared_capture
        self.latest_frame = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.max_retries = max_retries
        self.base_delay = base_delay

    def start(self) -> None:
        """Starts the streaming thread if not already running."""
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
        """Stops streaming; releases the capture if it was internally opened."""
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
        """Performs a stop then start cycle."""
        logger.info("[LIVE] Restarting LiveStreamJob")
        self.stop()
        time.sleep(1.0)
        self.start()

    def join(self, timeout: Optional[float] = None) -> None:
        """Blocks until the streaming thread terminates or timeout expires."""
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout)
            logger.info("[LIVE] LiveStreamJob thread joined")

    def _run(self) -> None:
        """Main loop: connects, reads frames, handles reconnects, and invokes callbacks."""
        self.capture = self._connect_with_retries()
        if not self.capture:
            self.running = False
            return

        logger.info("[LIVE] Entering capture loop")
        while self.running:
            try:
                ret, frame = self.capture.read()
                if not ret or frame is None:
                    logger.debug("[LIVE] Frame read failed; attempting reconnect")
                    self.capture = self._connect_with_retries()
                    if not self.capture:
                        break
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

        self._cleanup()
        logger.info("[LIVE] Streaming loop exited")

    def _connect_with_retries(self):
        """Attempts to open the camera with exponential backoff."""
        delay = self.base_delay
        for attempt in range(1, self.max_retries + 1):
            logger.info(f"[LIVE] Connecting to {self.camera_source}, attempt {attempt}")
            cap = try_open_camera(self.camera_source, retries=1, delay=0)
            if cap and cap.isOpened():
                settings = get_camera_settings()
                apply_cv_settings(cap, settings, mode="video")
                logger.info("[LIVE] Camera opened successfully")
                return cap

            logger.warning(f"[LIVE] Connection failed, retrying in {delay}s")
            time.sleep(delay)
            delay *= 2

        logger.error(f"[LIVE] Could not open camera after {self.max_retries} attempts")

        try:
            logger.warning("[LIVE] Performing fallback: force_device_reset")
            force_device_reset("/dev/video0")
            time.sleep(1.5)
        except Exception as e:
            logger.error(f"[LIVE] force_device_reset failed: {e}")

        return None

    def _cleanup(self) -> None:
        """Releases capture handle if internally owned."""
        if self.capture and not self.shared_capture:
            try:
                self.capture.release()
            except Exception as e:
                logger.warning(f"[LIVE] Error releasing capture on exit: {e}")
            finally:
                self.capture = None

    def get_frame(self) -> Optional[any]:
        """Returns a copy of the latest frame, or None if unavailable."""
        with livestream_lock:
            if self.latest_frame is not None:
                return self.latest_frame.copy()
        return None
