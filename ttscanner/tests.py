from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from .models import MENTUser

class MENTPermissionsTest(TestCase):
    def setUp(self):
        self.admin_django_user = User.objects.create(username="admin_user")
        self.regular_django_user = User.objects.create(username="regular_user")

        MENTUser.objects.create(external_user_id=self.admin_django_user.id, role="admin")
        MENTUser.objects.create(external_user_id=self.regular_django_user.id, role="regular")

        self.client = APIClient()

    def test_admin_access(self):
        """Admin should have access creating file association"""
        self.client.force_authenticate(user=self.admin_django_user)
        response = self.client.post('/ttscanner/file-associations/create/', {
            "algo_name": "TTScanner",
            "group_name": "SPDR",
            "interval_name": "5min"
        }, format='json')
        print("Admin status code:", response.status_code)
        self.assertEqual(response.status_code, 201) 

    def test_regular_access(self):
        """Regular user should be forbidden from creating file association"""
        self.client.force_authenticate(user=self.regular_django_user)
        response = self.client.post('/ttscanner/file-associations/create/', {
            "algo_name": "TTScanner",
            "group_name": "SPDR",
            "interval_name": "5min"
        }, format='json')
        print("Regular user status code:", response.status_code)
        self.assertEqual(response.status_code, 403) 
