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
from django.db.models import Q


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


from django.db.models import Q

MAX_ALERTS_PER_LOOP = 10  # just an example

import asyncio
from django.db import connections

async def sse_user_alerts(request, external_user_id):
    async def event_stream():
        print(f"--- SSE Connection Opened for External ID: {external_user_id} ---")
        try:
            while True:
                alerts_queryset = TriggeredAlert.objects.filter(
                    Q(alert_source__in=["system", "global"]) |
                    Q(alert_source="custom", custom_alert__user__external_user_id=external_user_id),
                    sent_to_ui=False
                ).order_by("triggered_at")[:MAX_ALERTS_PER_LOOP]

                # Process alerts asynchronously
                async for alert in alerts_queryset.aiter():
                    payload = {
                        "id": alert.id,
                        "message": alert.message,
                        "symbol": alert.symbol or "N/A",
                        "triggered_at": alert.triggered_at.isoformat(),
                        "source": alert.alert_source
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

                    # Mark as sent
                    alert.sent_to_ui = True
                    # Use a_save() for async saving
                    await alert.asave(update_fields=["sent_to_ui"])

                yield ": heartbeat\n\n"
                await asyncio.sleep(2)
                
        except Exception as e:
            print(f"SSE Error: {e}")
        finally:
            # Force close DB connections when user disconnects to prevent "Too many connections"
            for conn in connections.all():
                conn.close()

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response

async def sse_file_updates(request, pk):
    async def event_stream():
        last_version = None
        error_count = 0

        while True:
            await asyncio.sleep(2)

            try:
                version = cache.get(f"fa_version_{pk}", default=None)
                
                if version is not None and version != last_version:
                    payload = cache.get(f"fa_data_{pk}")
                    if payload:
                        last_version = version
                        yield f"data: {json.dumps(payload)}\n\n"
                        error_count = 0
                
            except Exception as e:
                print("Redis error in file SSE:", e)
                error_count += 1
                if error_count >= 3:
                    yield "data: {\"error\": \"Live updates unavailable\"}\n\n"
                    break
                    
    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response