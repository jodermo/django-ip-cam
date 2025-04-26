from django.urls import path
from . import views


urlpatterns = [
    path("", views.stream_page, name="stream_page"),
    path("update-settings/", views.update_camera_settings, name="update_camera_settings"),
    path("video_feed/", views.video_feed, name="video_feed"),
    path("start_recording/", views.start_recording, name="start_recording"),
    path("stop_recording/", views.stop_recording, name="stop_recording"),
    path("is-recording/", views.is_recording, name="is_recording"),
    path("record_video/", views.record_video, name="record_video"),
    path("gallery/", views.photo_gallery, name="photo_gallery"),
    path("settings/", views.settings_view, name="settings_view"),
    path("accounts/logout/", views.logout_view, name="logout"),
    path("reboot/", views.reboot_pi, name="reboot_pi"),
    path("media-browser/", views.media_browser, name="media_browser"),
]
