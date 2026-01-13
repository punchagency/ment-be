from rest_framework.response import Response
from django.db import close_old_connections
import signal
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
    def event_stream():
        from django.db import close_old_connections
        
        user_cache_key = f"user_exists_{external_user_id}"
        user_exists = cache.get(user_cache_key)
        
        if user_exists is None:
            try:
                close_old_connections()
                MENTUser.objects.only('id').get(external_user_id=external_user_id)
                cache.set(user_cache_key, True, timeout=300)
                user_exists = True
            except MENTUser.DoesNotExist:
                cache.set(user_cache_key, False, timeout=300)
                yield f"data: {json.dumps({'error': 'User not found'})}\n\n"
                return
        
        if not user_exists:
            yield f"data: {json.dumps({'error': 'User not found'})}\n\n"
            return

        last_snapshot = []
        error_count = 0
        
        while True:
            try:
                time.sleep(2)
                close_old_connections()  # Fresh connection
                
                cache_key = f"user_alerts_{external_user_id}"
                current_snapshot = cache.get(cache_key)
                
                if current_snapshot is None:
                    alerts = CustomAlert.objects.filter(
                        user__external_user_id=external_user_id
                    ).only('id', 'last_value', 'is_active').order_by("id")
                    
                    current_snapshot = [
                        {
                            "alert_id": a.id,
                            "last_value": a.last_value,
                            "is_active": a.is_active,
                        }
                        for a in alerts
                    ]
                    cache.set(cache_key, current_snapshot, timeout=30)
                
                if current_snapshot != last_snapshot:
                    last_snapshot = current_snapshot
                    yield f"data: {json.dumps(current_snapshot)}\n\n"
                    error_count = 0
                    
            except Exception as e:
                error_count += 1
                print(f"SSE User Alerts Error ({error_count}): {e}")
                
                if error_count >= 3:
                    yield f"data: {json.dumps({'error': 'Connection lost, please refresh'})}\n\n"
                    break
                
                time.sleep(5)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response



def sse_file_updates(request, pk):
    def event_stream():
        from django.db import close_old_connections
        
        try:
            close_old_connections()
            fa = FileAssociation.objects.get(id=pk)
            last_version = fa.data_version
        except FileAssociation.DoesNotExist:
            yield f"data: {json.dumps({'error': 'File not found'})}\n\n"
            return

        error_count = 0
        
        while True:
            try:
                time.sleep(2) 
                close_old_connections()
                
                cache_key = f"fa_version_{pk}"
                current_version = cache.get(cache_key)
                
                if current_version is None:
                    fa_obj = FileAssociation.objects.filter(id=pk).only('data_version').first()
                    if fa_obj:
                        current_version = fa_obj.data_version
                        cache.set(cache_key, current_version, timeout=5)
                    else:
                        yield f"data: {json.dumps({'error': 'File association deleted'})}\n\n"
                        break
                
                if current_version != last_version:
                    last_version = current_version
                    data_cache_key = f"fa_data_{pk}"
                    main_data = cache.get(data_cache_key)
                    
                    if main_data is None:
                        close_old_connections() 
                        main_data = MainData.objects.filter(
                            file_association_id=pk
                        ).only('data_json').first()
                        if main_data:
                            cache.set(data_cache_key, main_data, timeout=5)
                    
                    if not main_data:
                        payload = {"error": "No data found"}
                        yield f"data: {json.dumps(payload)}\n\n"
                        continue

                    headers = main_data.data_json.get("headers", [])
                    rows = main_data.data_json.get("rows", [])

                    cleaned_rows = [
                        {h: row[h] for h in headers if not h.startswith("_")}
                        for row in rows
                    ]

                    payload = {
                        "file_association_id": pk,
                        "data_version": last_version,
                        "headers": headers,
                        "rows": cleaned_rows[1:],
                    }

                    yield f"data: {json.dumps(payload)}\n\n"
                    error_count = 0  # Reset error count
                    
            except Exception as e:
                error_count += 1
                print(f"SSE File Updates Error ({error_count}): {e}")
                
                if error_count >= 3:
                    yield f"data: {json.dumps({'error': 'Connection lost, please refresh'})}\n\n"
                    break
                
                time.sleep(5)  # Wait longer before retry

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response