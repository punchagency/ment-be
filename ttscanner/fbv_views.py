from rest_framework.response import Response
# from django.db import close_old_connections
# import signal
from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.decorators import api_view
from .tasks import send_announcement_sms_task
from django.contrib.auth import logout
from django.views.decorators.csrf import csrf_exempt
from .models import Announcement, CustomAlert, FileAssociation, MENTUser, MainData
import uuid, json, time, re
from django.core.cache import cache


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


def sse_user_alerts(request, external_user_id):
    """
    SSE stream for user alerts.
    Sends updates only when cache changes to avoid DB polling every request.
    """
    def event_stream():
        last_snapshot = None
        error_count = 0

        while True:
            try:
                time.sleep(2)
                current_snapshot = cache.get(f"user_alerts_{external_user_id}")

                if current_snapshot is None:
                    continue

                if current_snapshot != last_snapshot:
                    last_snapshot = current_snapshot
                    yield f"data: {json.dumps(current_snapshot)}\n\n"
                    error_count = 0  

            except GeneratorExit:
                # Client disconnected
                break
            except Exception as e:
                error_count += 1
                print(f"SSE User Alerts Error ({error_count}): {e}")
                if error_count >= 3:
                    yield f"data: {json.dumps({'error': 'Connection lost, please refresh'})}\n\n"
                    break
                time.sleep(5)

    response = StreamingHttpResponse(
        event_stream(),
        content_type="text/event-stream"
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response



def sse_file_updates(request, pk):
    def event_stream():
        last_version = None

        while True:
            time.sleep(2)

            version = cache.get(f"fa_version_{pk}")
            if version is None:
                continue  

            if version != last_version:
                payload = cache.get(f"fa_data_{pk}")
                if payload:
                    yield f"data: {json.dumps(payload)}\n\n"
                    last_version = version

    response = StreamingHttpResponse(
        event_stream(),
        content_type="text/event-stream"
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
