from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view
from .tasks import send_announcement_sms_task
from django.contrib.auth import logout
from django.views.decorators.csrf import csrf_exempt
from .models import Announcement, MENTUser
import uuid


@api_view(["POST"])
def send_announcement(request):
    message = request.data.get("message", "").strip()

    if not message:
        return Response({"error": "Message cannot be empty"}, status=400)

    ann_type = request.data.get("type", "SMS")
    task = send_announcement_sms_task.delay(message)
    Announcement.objects.create(message=message, type=ann_type)

    return Response({
        "status": "queued",
        "task_id": task.id,
        "message": "Success! Your message is now being sent to all recipients."
    }, status=status.HTTP_200_OK)


@api_view(["GET"])
def announcement_log(request):
    logs = Announcement.objects.all().order_by("-created_at")
    data = [
        {
            "id": a.id,
            "message": a.message,
            "type": a.type,
            "created_at": a.created_at.strftime("%Y-%m-%d %H:%M")
        } 
        for a in logs
    ]

    return Response(data)


@api_view(["POST"])
def login(request):
    username = request.data.get("username")
    password = request.data.get("password")

    if not username or not password:
        return Response(
            {"detail": "Username and password required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        user = MENTUser.objects.get(username=username)
    except MENTUser.DoesNotExist:
        return Response(
            {"detail": "Invalid credentials"},
            status=status.HTTP_401_UNAUTHORIZED
        )

    if not user.check_password(password):
        return Response(
            {"detail": "Invalid credentials"},
            status=status.HTTP_401_UNAUTHORIZED
        )

    return Response({
        "token": str(uuid.uuid4()),  
        "user": {
            "id": user.id,
            "username": user.username,
            "external_user_id": user.external_user_id,
            "role": user.role,
            "email": user.email,
        }
    }, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(["POST"])
def logout_view(request):
    logout(request)
    return Response({"detail": "Logged out successfully"}, status=status.HTTP_200_OK)

