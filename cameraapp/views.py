
from django.http import StreamingHttpResponse, JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from .camera_manager import CameraManager
import time
import os
import json
import subprocess
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
import shutil

# Initialize camera manager
camera_manager = CameraManager()

@login_required
def stream_page(request):
    """Main streaming page"""
    return render(request, 'cameraapp/stream.html')

def video_feed(request):
    """Handle the video feed stream"""
    def generate_frames():
        while True:
            ret, frame = camera_manager.get_frame()
            if not ret:
                time.sleep(0.1)
                continue
                
            # Encode frame as JPEG
            ret, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            frame_bytes = jpeg.tobytes()
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n\r\n')
            
            # Control frame rate for streaming
            time.sleep(0.033)  # ~30fps
    
    return StreamingHttpResponse(generate_frames(),
                                content_type='multipart/x-mixed-replace; boundary=frame')

@csrf_exempt
def update_camera_settings(request):
    """Update camera settings"""
    if request.method == 'POST':
        try:
            settings_data = json.loads(request.body)
            result = camera_manager.update_settings(settings_data)
            return JsonResponse({'success': result})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@csrf_exempt
def update_photo_settings(request):
    """Update photo settings"""
    if request.method == 'POST':
        try:
            settings_data = json.loads(request.body)
            result = camera_manager.update_photo_settings(settings_data)
            return JsonResponse({'success': result})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@csrf_exempt
def auto_photo_settings(request):
    """Auto-adjust photo settings"""
    try:
        result = camera_manager.auto_adjust_settings()
        return JsonResponse({'success': result})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def photo_settings_page(request):
    """Photo settings page"""
    return render(request, 'cameraapp/photo_settings.html')

@csrf_exempt
def auto_photo_adjust(request):
    """Auto-adjust before taking photo"""
    try:
        photo_url = camera_manager.take_photo(auto_adjust=True)
        if photo_url:
            return JsonResponse({'success': True, 'photo_url': photo_url})
        return JsonResponse({'success': False, 'error': 'Failed to capture photo'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
def reset_camera_settings(request):
    """Reset camera to default settings"""
    try:
        result = camera_manager.reset_settings()
        return JsonResponse({'success': result})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
def take_photo_now(request):
    """Take photo manually"""
    try:
        photo_url = camera_manager.take_photo()
        if photo_url:
            return JsonResponse({'success': True, 'photo_url': photo_url})
        return JsonResponse({'success': False, 'error': 'Failed to capture photo'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
def start_recording(request):
    """Start video recording"""
    try:
        success, result = camera_manager.start_recording()
        if success:
            return JsonResponse({'success': True, 'video_url': result})
        return JsonResponse({'success': False, 'error': result})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
def stop_recording(request):
    """Stop video recording"""
    try:
        success, message = camera_manager.stop_recording()
        return JsonResponse({'success': success, 'message': message})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
def is_recording(request):
    """Check if recording is in progress"""
    return JsonResponse({'recording': camera_manager.is_recording})

@csrf_exempt
def record_video(request):
    """Record for specific duration"""
    try:
        duration = int(request.GET.get('duration', 30))
        success, result = camera_manager.record_video_for_duration(duration)
        if success:
            return JsonResponse({'success': True, 'video_url': result})
        return JsonResponse({'success': False, 'error': result})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def timelaps_view(request):
    """Timelapse view page"""
    return render(request, 'cameraapp/timelaps.html')

@login_required
def photo_view(request):
    """Photo view page"""
    return render(request, 'cameraapp/photo_view.html')

@login_required
def settings_view(request):
    """Settings page"""
    return render(request, 'cameraapp/settings.html')

@login_required
def logout_view(request):
    """Logout user"""
    logout(request)
    return redirect('stream_page')

@csrf_exempt
def reboot_pi(request):
    """Reboot the Raspberry Pi"""
    try:
        # Execute reboot command
        subprocess.Popen(['sudo', 'reboot'])
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def media_browser(request):
    """Media browser page"""
    return render(request, 'cameraapp/media_browser.html')

@csrf_exempt
def manual_restart_camera(request):
    """Manually restart camera connection"""
    try:
        result = camera_manager.restart_camera()
        return JsonResponse({'success': result})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
def camera_status(request):
    """Get current camera status"""
    try:
        status = camera_manager.get_camera_status()
        return JsonResponse(status)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
def single_frame(request):
    """Get a single frame as JPEG"""
    try:
        ret, frame = camera_manager.get_frame()
        if not ret:
            return HttpResponse(status=503)
            
        # Encode frame as JPEG
        ret, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        frame_bytes = jpeg.tobytes()
        
        return HttpResponse(frame_bytes, content_type='image/jpeg')
    except Exception as e:
        return HttpResponse(str(e), status=500)

@csrf_exempt
def delete_media_file(request):
    """Delete media file"""
    if request.method == 'POST':
        try:
            file_path = request.POST.get('file_path')
            if not file_path:
                return JsonResponse({'success': False, 'error': 'No file specified'})
                
            # Security check - ensure path is within media directory
            full_path = os.path.join(settings.MEDIA_ROOT, os.path.relpath(file_path, settings.MEDIA_URL))
            if not os.path.normpath(full_path).startswith(os.path.normpath(settings.MEDIA_ROOT)):
                return JsonResponse({'success': False, 'error': 'Invalid file path'})
                
            if os.path.exists(full_path) and os.path.isfile(full_path):
                os.remove(full_path)
                return JsonResponse({'success': True})
            return JsonResponse({'success': False, 'error': 'File not found'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@csrf_exempt
def delete_all_images(request):
    """Delete all image files"""
    if request.method == 'POST':
        try:
            photos_dir = os.path.join(settings.MEDIA_ROOT, 'photos')
            if os.path.exists(photos_dir):
                # Remove and recreate directory
                shutil.rmtree(photos_dir)
                os.makedirs(photos_dir, exist_ok=True)
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@csrf_exempt
def delete_all_videos(request):
    """Delete all video files"""
    if request.method == 'POST':
        try:
            videos_dir = os.path.join(settings.MEDIA_ROOT, 'videos')
            if os.path.exists(videos_dir):
                # Remove and recreate directory
                shutil.rmtree(videos_dir)
                os.makedirs(videos_dir, exist_ok=True)
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request method'})