# cameraapp/camera_manager.py

import cv2
import threading
import time
import os
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

class CameraManager:
    """
    Singleton camera manager for Raspberry Pi USB webcam
    Ensures sharing of camera resources between streaming, photos and recording
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(CameraManager, cls).__new__(cls)
                # Initialize properties
                cls._instance.camera = None
                cls._instance.camera_lock = threading.Lock()
                cls._instance.is_initialized = False
                cls._instance.device_id = 0  # Default webcam
                cls._instance.is_recording = False
                cls._instance.recording_thread = None
                cls._instance.recording_output = None
                cls._instance.frame_thread = None
                cls._instance.running = False
                cls._instance.last_frame = None
                cls._instance.last_frame_time = 0
                cls._instance.frame_buffer = []
                
                # Camera settings
                cls._instance.settings = {
                    'brightness': 50,
                    'contrast': 50,
                    'saturation': 50,
                    'exposure': -1,  # Auto
                    'width': 640,
                    'height': 480,
                    'fps': 30,
                    'auto_focus': True,
                    'focus': 0,
                    'zoom': 100,
                    'resolution_index': 1  # Default medium resolution
                }
                
                # Photo settings
                cls._instance.photo_settings = {
                    'quality': 95,
                    'resolution_index': 2,  # Higher resolution for photos
                    'photo_width': 1280,
                    'photo_height': 720
                }
                
                # Status tracking
                cls._instance.camera_status = {
                    'is_running': False,
                    'last_error': None,
                    'frame_count': 0,
                    'fps': 0,
                    'last_fps_check': time.time(),
                }
        return cls._instance
    
    def initialize(self, device_id=0):
        """Initialize the camera with specified device ID"""
        with self._lock:
            self.device_id = device_id
            try:
                self._connect_camera()
                
                # Start background thread for continuous frame capture
                if not self.running:
                    self.running = True
                    self.frame_thread = threading.Thread(target=self._frame_capture_loop)
                    self.frame_thread.daemon = True
                    self.frame_thread.start()
                    
                self.is_initialized = True
                self.camera_status['is_running'] = True
                self.camera_status['last_error'] = None
                logger.info(f"USB Camera initialized with device ID: {device_id}")
                return True
            except Exception as e:
                self.camera_status['is_running'] = False
                self.camera_status['last_error'] = str(e)
                logger.error(f"Camera initialization error: {str(e)}")
                return False
    
    def _connect_camera(self):
        """Connect to the camera and apply settings"""
        if self.camera is not None:
            with self.camera_lock:
                self.camera.release()
        
        # Connect to camera
        self.camera = cv2.VideoCapture(self.device_id)
        
        # Check if camera opened successfully
        if not self.camera.isOpened():
            logger.error(f"Failed to open USB camera at device ID {self.device_id}")
            raise Exception(f"Failed to open USB camera at device ID {self.device_id}")
        
        # Apply current settings
        self._apply_camera_settings()
    
    def _apply_camera_settings(self):
        """Apply current settings to the camera"""
        with self.camera_lock:
            if not self.camera or not self.camera.isOpened():
                return False
                
            # Apply resolution settings
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.settings['width'])
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.settings['height'])
            
            # Apply other settings if supported by camera
            try:
                self.camera.set(cv2.CAP_PROP_FPS, self.settings['fps'])
                self.camera.set(cv2.CAP_PROP_BRIGHTNESS, self.settings['brightness'] / 100)
                self.camera.set(cv2.CAP_PROP_CONTRAST, self.settings['contrast'] / 100)
                self.camera.set(cv2.CAP_PROP_SATURATION, self.settings['saturation'] / 100)
                
                # Handle exposure - negative value for auto exposure
                if self.settings['exposure'] < 0:
                    self.camera.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)  # Auto exposure
                else:
                    self.camera.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0)  # Manual exposure
                    self.camera.set(cv2.CAP_PROP_EXPOSURE, self.settings['exposure'] / 100)
                
                # Handle focus if supported
                if self.settings['auto_focus']:
                    self.camera.set(cv2.CAP_PROP_AUTOFOCUS, 1)
                else:
                    self.camera.set(cv2.CAP_PROP_AUTOFOCUS, 0)
                    self.camera.set(cv2.CAP_PROP_FOCUS, self.settings['focus'] / 100)
                
                # Buffer size (1 for realtime)
                self.camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception as e:
                logger.warning(f"Some camera settings may not be supported: {str(e)}")
            
            return True
    
    def update_settings(self, new_settings):
        """Update camera settings and reapply them"""
        with self._lock:
            # Update settings
            for key, value in new_settings.items():
                if key in self.settings:
                    self.settings[key] = value
            
            # Update resolution based on index if provided
            if 'resolution_index' in new_settings:
                index = new_settings['resolution_index']
                resolutions = [
                    (320, 240),    # Low
                    (640, 480),    # Medium
                    (1280, 720),   # HD
                    (1920, 1080),  # Full HD
                ]
                if 0 <= index < len(resolutions):
                    self.settings['width'], self.settings['height'] = resolutions[index]
            
            # Apply settings
            result = self._apply_camera_settings()
            return result
    
    def update_photo_settings(self, new_settings):
        """Update photo-specific settings"""
        with self._lock:
            for key, value in new_settings.items():
                if key in self.photo_settings:
                    self.photo_settings[key] = value
            
            # Update photo resolution based on index
            if 'resolution_index' in new_settings:
                index = new_settings['resolution_index']
                resolutions = [
                    (640, 480),     # Low
                    (1280, 720),    # HD
                    (1920, 1080),   # Full HD
                    (2560, 1440),   # 2K (if supported)
                ]
                if 0 <= index < len(resolutions):
                    self.photo_settings['photo_width'], self.photo_settings['photo_height'] = resolutions[index]
            
            return True
    
    def auto_adjust_settings(self):
        """Auto-adjust camera settings based on current lighting conditions"""
        if not self.is_initialized:
            return False
            
        # Get current frame to analyze
        ret, frame = self.get_frame()
        if not ret:
            return False
            
        try:
            # Convert to grayscale for analysis
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Calculate average brightness and contrast
            brightness = gray.mean()
            contrast = gray.std()
            
            # Adjust settings based on analysis
            new_settings = {}
            
            # Adjust brightness
            if brightness < 50:
                new_settings['brightness'] = min(self.settings['brightness'] + 10, 100)
            elif brightness > 200:
                new_settings['brightness'] = max(self.settings['brightness'] - 10, 0)
                
            # Adjust contrast
            if contrast < 30:
                new_settings['contrast'] = min(self.settings['contrast'] + 10, 100)
            elif contrast > 80:
                new_settings['contrast'] = max(self.settings['contrast'] - 10, 0)
                
            # Apply auto exposure
            new_settings['exposure'] = -1  # Auto
            
            # Apply the adjustments
            if new_settings:
                return self.update_settings(new_settings)
                
            return True
        except Exception as e:
            logger.error(f"Auto adjustment error: {str(e)}")
            return False
    
    def _frame_capture_loop(self):
        """Background thread that continuously captures frames"""
        fps_counter = 0
        fps_timer = time.time()
        
        while self.running:
            with self.camera_lock:
                if self.camera and self.camera.isOpened():
                    ret, frame = self.camera.read()
                    if ret:
                        # Update status metrics
                        self.camera_status['frame_count'] += 1
                        fps_counter += 1
                        
                        # Calculate FPS every second
                        if time.time() - fps_timer >= 1.0:
                            self.camera_status['fps'] = fps_counter
                            fps_counter = 0
                            fps_timer = time.time()
                        
                        # Keep a buffer of recent frames
                        self.last_frame = frame.copy()
                        self.last_frame_time = time.time()
                        
                        # Buffer for smoother streaming
                        self.frame_buffer.append(frame.copy())
                        if len(self.frame_buffer) > 3:  # Keep last 3 frames
                            self.frame_buffer.pop(0)
                        
                        # Handle recording if active
                        if self.is_recording and self.recording_output is not None:
                            self.recording_output.write(frame)
                    else:
                        # Camera read failed
                        logger.warning("Failed to read frame, attempting to reconnect camera")
                        self.camera_status['last_error'] = "Frame read failure"
                        try:
                            self._connect_camera()
                        except Exception as e:
                            logger.error(f"Reconnection failed: {str(e)}")
                            time.sleep(1)  # Wait before trying again
                else:
                    # Camera not available
                    self.camera_status['is_running'] = False
                    self.camera_status['last_error'] = "Camera not available"
                    try:
                        self._connect_camera()
                        self.camera_status['is_running'] = True
                    except Exception:
                        time.sleep(2)  # Wait longer before retry
            
            # Control loop speed
            time.sleep(1/30)  # Target ~30fps internal processing
    
    def get_frame(self):
        """Get the most recent frame - non-blocking, returns from buffer"""
        if not self.is_initialized:
            self.initialize()
            
        if self.last_frame is not None:
            return True, self.last_frame.copy()
        return False, None
    
    def get_camera_status(self):
        """Get current camera status information"""
        return self.camera_status.copy()
    
    def capture_photo(self, auto_adjust=False):
        """Capture a single high-quality photo"""
        if not self.is_initialized:
            if not self.initialize():
                return False, None
        
        # Save original settings to restore after photo
        original_settings = {
            'width': self.settings['width'], 
            'height': self.settings['height']
        }
        
        try:
            with self.camera_lock:
                # Apply photo-specific settings
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.photo_settings['photo_width'])
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.photo_settings['photo_height'])
                
                if auto_adjust:
                    # Get and analyze a test frame
                    for _ in range(3):  # Discard a few frames
                        self.camera.read()
                        
                    ret, test_frame = self.camera.read()
                    if ret:
                        gray = cv2.cvtColor(test_frame, cv2.COLOR_BGR2GRAY)
                        brightness = gray.mean()
                        
                        # Adjust exposure based on brightness
                        if brightness < 80:
                            self.camera.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0)
                            self.camera.set(cv2.CAP_PROP_EXPOSURE, 0.5)  # Higher exposure
                        elif brightness > 200:
                            self.camera.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0)
                            self.camera.set(cv2.CAP_PROP_EXPOSURE, 0.1)  # Lower exposure
                
                # Take multiple frames to adjust
                for _ in range(5):  # Discard a few frames to let camera adjust
                    self.camera.read()
                
                # Capture the actual photo
                ret, frame = self.camera.read()
                
                # Restore original settings
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, original_settings['width'])
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, original_settings['height'])
                self._apply_camera_settings()  # Restore other settings
                
                return ret, frame if ret else None
        except Exception as e:
            logger.error(f"Photo capture error: {str(e)}")
            # Restore settings on error
            try:
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, original_settings['width'])
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, original_settings['height'])
                self._apply_camera_settings()
            except:
                pass
            return False, None
    
    def save_photo(self, frame, filename=None):
        """Save photo to disk"""
        if frame is None:
            return None
            
        try:
            # Create directory if it doesn't exist
            photos_dir = os.path.join(settings.MEDIA_ROOT, 'photos')
            os.makedirs(photos_dir, exist_ok=True)
            
            # Generate filename if not provided
            if filename is None:
                filename = f'photo_{int(time.time())}.jpg'
                
            file_path = os.path.join(photos_dir, filename)
            
            # Save with specified quality
            quality = self.photo_settings['quality']
            cv2.imwrite(file_path, frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            
            # Return relative URL
            return os.path.join(settings.MEDIA_URL, 'photos', filename)
        except Exception as e:
            logger.error(f"Error saving photo: {str(e)}")
            return None
    
    def take_photo(self, auto_adjust=False):
        """Capture and save a photo"""
        ret, frame = self.capture_photo(auto_adjust)
        if ret:
            return self.save_photo(frame)
        return None
    
    def start_recording(self, filename=None):
        """Start video recording"""
        if self.is_recording:
            return False, "Already recording"
            
        if not self.is_initialized:
            if not self.initialize():
                return False, "Camera not initialized"
        
        try:
            # Create directory if needed
            videos_dir = os.path.join(settings.MEDIA_ROOT, 'videos')
            os.makedirs(videos_dir, exist_ok=True)
            
            # Generate filename if not provided
            if filename is None:
                filename = f'video_{int(time.time())}.mp4'
                
            file_path = os.path.join(videos_dir, filename)
            
            # Get frame to determine dimensions
            ret, frame = self.get_frame()
            if not ret:
                return False, "Failed to get frame dimensions"
                
            height, width = frame.shape[:2]
            
            # Initialize video writer
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # or 'avc1', 'XVID'
            
            with self.camera_lock:
                self.recording_output = cv2.VideoWriter(
                    file_path, fourcc, self.settings['fps'], (width, height)
                )
                
                if not self.recording_output.isOpened():
                    return False, "Failed to create video writer"
                    
                self.is_recording = True
            
            # Return the relative URL
            return True, os.path.join(settings.MEDIA_URL, 'videos', filename)
            
        except Exception as e:
            logger.error(f"Start recording error: {str(e)}")
            return False, str(e)
    
    def stop_recording(self):
        """Stop current recording"""
        if not self.is_recording:
            return False, "Not recording"
            
        try:
            with self.camera_lock:
                if self.recording_output:
                    self.recording_output.release()
                    self.recording_output = None
                self.is_recording = False
            return True, "Recording stopped"
        except Exception as e:
            logger.error(f"Stop recording error: {str(e)}")
            self.is_recording = False
            self.recording_output = None
            return False, str(e)
    
    def record_video_for_duration(self, duration, filename=None):
        """Record video for specific duration in seconds"""
        success, result = self.start_recording(filename)
        if not success:
            return False, result
            
        # Start a timer to stop recording
        def stop_after_duration():
            time.sleep(duration)
            self.stop_recording()
            
        timer_thread = threading.Thread(target=stop_after_duration)
        timer_thread.daemon = True
        timer_thread.start()
        
        return True, result
    
    def reset_settings(self):
        """Reset camera to default settings"""
        default_settings = {
            'brightness': 50,
            'contrast': 50,
            'saturation': 50,
            'exposure': -1,  # Auto
            'width': 640,
            'height': 480,
            'fps': 30,
            'auto_focus': True,
            'focus': 0,
            'zoom': 100,
            'resolution_index': 1
        }
        
        return self.update_settings(default_settings)
    
    def restart_camera(self):
        """Completely restart the camera connection"""
        with self._lock:
            # Stop recording if active
            if self.is_recording:
                self.stop_recording()
                
            # Stop frame thread
            was_running = self.running
            self.running = False
            
            if self.frame_thread and self.frame_thread.is_alive():
                self.frame_thread.join(timeout=1.0)
            
            # Release camera
            with self.camera_lock:
                if self.camera:
                    self.camera.release()
                    self.camera = None
            
            self.is_initialized = False
            
            # Restart if it was running
            if was_running:
                result = self.initialize(self.device_id)
                return result
            return True
    
    def release(self):
        """Release all camera resources"""
        with self._lock:
            # Stop recording if active
            if self.is_recording:
                self.stop_recording()
                
            # Stop frame thread
            self.running = False
            
            if self.frame_thread and self.frame_thread.is_alive():
                self.frame_thread.join(timeout=1.0)
            
            # Release camera
            with self.camera_lock:
                if self.camera:
                    self.camera.release()
                    self.camera = None
            
            self.is_initialized = False
            self.camera_status['is_running'] = False
            logger.info("Camera resources released")
