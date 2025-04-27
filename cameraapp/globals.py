# cameraapp/globals.py


import threading

camera_lock = threading.Lock()
latest_frame = None
latest_frame_lock = threading.Lock()
livestream_resume_lock = threading.Lock()
livestream_lock = threading.Lock()
livestream_job = None
taking_foto = False
recording_job = None
camera_capture = None
camera_instance = None
active_stream_viewers = 0
last_disconnect_time = None
recording_timeout = 30
