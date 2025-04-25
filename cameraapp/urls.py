from django.urls import path
from .views import record_video

urlpatterns = [
    path("", views.stream_page, name="stream_page"),
    path("video_feed/", views.video_feed, name="video_feed"),
    path("record_video/", record_video, name="record_video"),
]
