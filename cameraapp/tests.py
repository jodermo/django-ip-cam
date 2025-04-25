from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

class CameraStreamTests(TestCase):

    def setUp(self):
        # Erstelle Testbenutzer
        self.username = "testuser"
        self.password = "testpass123"
        self.user = User.objects.create_user(username=self.username, password=self.password)
        self.client = Client()

    def test_login_required_for_stream_page(self):
        response = self.client.get(reverse("stream_page"))
        self.assertRedirects(response, f"/accounts/login/?next=/")

    def test_login_required_for_video_feed(self):
        response = self.client.get(reverse("video_feed"))
        self.assertRedirects(response, f"/accounts/login/?next=/video_feed/")

    def test_authenticated_access_stream_page(self):
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(reverse("stream_page"))
        self.assertEqual(response.status_code, 200)

    def test_authenticated_access_video_feed(self):
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(reverse("video_feed"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'multipart/x-mixed-replace; boundary=frame')
