from rest_framework import permissions
from .utils.user_utils import get_or_create_ment_user


class IsTTAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        ment_user = get_or_create_ment_user(request.user)
        return ment_user.role == 'admin'
