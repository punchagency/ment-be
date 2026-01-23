from rest_framework.response import Response
from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.decorators import api_view
from .tasks import send_announcement_sms_task
from django.contrib.auth import logout
from django.views.decorators.csrf import csrf_exempt
from .models import Announcement, MENTUser, TriggeredAlert, FileAssociation, GlobalAlertRule
import uuid, json, time
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


@api_view(["GET"])
def triggered_alerts_count(request):
    count = TriggeredAlert.objects.filter(
        alert_source__in=['global', 'system']
    ).count()
    return Response({"totalTriggeredAlerts": count})


@api_view(["GET"])
def file_associations_count(request):
    count = FileAssociation.objects.count()
    return Response({"totalFiles": count})



@api_view(["GET"])
def global_alerts_count(request):
    count = GlobalAlertRule.objects.count()
    return Response({"totalAlerts": count})


@csrf_exempt
@api_view(["POST"])
def logout_view(request):
    logout(request)
    return Response({"detail": "Logged out successfully"}, status=status.HTTP_200_OK)


def sse_user_alerts(request, external_user_id):

    def event_stream():
        last_snapshot = None
        error_count = 0

        while True:
            time.sleep(2)

            try:
                current_snapshot = cache.get(
                    f"user_alerts_{external_user_id}",
                    default=None
                )

            except Exception as e:
                print("Redis error in SSE:", e)
                error_count += 1

                if error_count >= 3:
                    yield "data: {\"error\": \"Live updates unavailable\"}\n\n"
                    break

                continue

            if current_snapshot is None:
                continue

            if current_snapshot != last_snapshot:
                last_snapshot = current_snapshot
                yield f"data: {json.dumps(current_snapshot)}\n\n"
                error_count = 0

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def sse_file_updates(request, pk):

    def event_stream():
        last_version = None
        error_count = 0

        while True:
            time.sleep(2)

            try:
                version = cache.get(f"fa_version_{pk}", default=None)
            except Exception as e:
                print("Redis error in file SSE:", e)
                error_count += 1

                if error_count >= 3:
                    yield "data: {\"error\": \"Live updates unavailable\"}\n\n"
                    break

                continue

            if version is None:
                continue

            if version != last_version:
                payload = cache.get(f"fa_data_{pk}")
                if payload:
                    last_version = version
                    yield f"data: {json.dumps(payload)}\n\n"
                    error_count = 0

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
