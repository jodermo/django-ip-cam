# cameraapp/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path("", views.stream_page, name="stream_page"),
    path("update_settings/", views.update_camera_settings, name="update_camera_settings"),
    path("update_photo_settings/", views.update_photo_settings, name="update_photo_settings"),
    path("auto_photo_settings/", views.auto_photo_settings, name="auto_photo_settings"),
    path("photo/settings/", views.photo_settings_page, name="photo_settings_page"),
    path("photo/auto-adjust/", views.auto_photo_adjust, name="auto_photo_adjust"),
    path("reset_camera/", views.reset_camera_settings, name="reset_camera"),
    path("photo/manual/", views.take_photo_now, name="take_photo_now"), 
    path("video_feed/", views.video_feed, name="video_feed"),
    path("start_recording/", views.start_recording, name="start_recording"),
    path("stop_recording/", views.stop_recording, name="stop_recording"),
    path("is-recording/", views.is_recording, name="is_recording"),
    path("record_video/", views.record_video, name="record_video"),
    path("timelaps_view/", views.timelaps_view, name="timelaps_view"),
    path("gallery_view/", views.photo_gallery, name="gallery_view"),
    path("settings/", views.settings_view, name="settings_view"),
    path("accounts/logout/", views.logout_view, name="logout"),
    path("reboot/", views.reboot_pi, name="reboot_pi"),
    path("media-browser/", views.media_browser, name="media_browser"),
    path("manual_restart_camera/", views.manual_restart_camera, name="manual_restart_camera"),
    path("camera_status/", views.camera_status, name="camera_status"),
    path("frame/", views.single_frame, name="single_frame"),
    path("media/delete/", views.delete_media_file, name="delete_media_file"),
    path("media/delete_all_images/", views.delete_all_images, name="delete_all_images"),
    path("media/delete_all_videos/", views.delete_all_videos, name="delete_all_videos"),
]
