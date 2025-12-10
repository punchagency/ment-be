from rest_framework.response import Response
from rest_framework.generics import ListAPIView
from django.shortcuts import get_object_or_404
from rest_framework import status
from django.utils import timezone
from rest_framework import generics
from .models import FileAssociation, GlobalAlertRule, Algo, Group, Interval, MainData, MENTUser
from ttscanner.utils.algo_detector import assign_detected_algo, UnknownAlgoError
from .serializers import (
    CSVUploadSerializer, 
    FileAssociationCreateSerializer, FileAssociationUpdateSerializer,
    FileAssociationUpdateSerializer, GlobalAlertCreateSerializer,
    FileAssociationListSerializer, AlgoSerializer,
    GroupSerializer, IntervalSerializer,
    GlobalAlertListSerializer, GlobalAlertUpdateSerializer,
    UserRoleSerializer
)
from .permissions import IsTTAdmin
from rest_framework.decorators import api_view
from .tasks import send_sms_notifications
from rest_framework.permissions import IsAuthenticated
from .utils.csv_utils import (
    read_uploaded_file_bytes,
    is_file_changed, store_csv_data,
    fetch_ftp_bytes
)

#ALGO VIEWS
class AlgoListView(ListAPIView):
    serializer_class = AlgoSerializer
    queryset = Algo.objects.all()

class AlgoCreateView(generics.CreateAPIView):
    queryset = Algo.objects.all()
    serializer_class = AlgoSerializer
  #  permission_classes = [IsAuthenticated, IsTTAdmin]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class AlgoUpdateView(generics.UpdateAPIView):
    queryset = Algo.objects.all()
    serializer_class = AlgoSerializer
  #  permission_classes = [IsAuthenticated, IsTTAdmin]
    lookup_field = "pk"

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class AlgoDeleteView(generics.DestroyAPIView):
    queryset = Algo.objects.all()
    serializer_class = AlgoSerializer
  #  permission_classes = [IsAuthenticated, IsTTAdmin]
    lookup_field = "pk"

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance_id = instance.id
        instance.delete()
        return Response({"details": f"Successfuly Deleted Algo ID #{instance_id}" }, 
        status=status.HTTP_200_OK)


#GROUP VIEWS
class GroupListView(ListAPIView):
    serializer_class = GroupSerializer
    queryset = Group.objects.all()

class GroupCreateView(generics.CreateAPIView):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer
  #  permission_classes = [IsAuthenticated, IsTTAdmin]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class GroupUpdateView(generics.UpdateAPIView):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer
  #  permission_classes = [IsAuthenticated, IsTTAdmin]
    lookup_field = "pk"

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class GroupDeleteView(generics.DestroyAPIView):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer
  #  permission_classes = [IsAuthenticated, IsTTAdmin]
    lookup_field = "pk"

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance_id = instance.id
        instance.delete()
        return Response({"details": f"Successfuly Deleted Algo ID #{instance_id}" }, 
        status=status.HTTP_200_OK)


#INTERVAL VIEWS
class IntervalListView(ListAPIView):
    serializer_class = IntervalSerializer
    queryset = Interval.objects.all()


class IntervalCreateView(generics.CreateAPIView):
    queryset = Interval.objects.all()
    serializer_class = IntervalSerializer
  #  permission_classes = [IsAuthenticated, IsTTAdmin]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class IntervalUpdateView(generics.UpdateAPIView):
    queryset = Interval.objects.all()
    serializer_class = IntervalSerializer
  #  permission_classes = [IsAuthenticated, IsTTAdmin]
    lookup_field = "pk"

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class IntervalDeleteView(generics.DestroyAPIView):
    queryset = Interval.objects.all()
    serializer_class = IntervalSerializer
  #  permission_classes = [IsAuthenticated, IsTTAdmin]
    lookup_field = "pk"

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance_id = instance.id
        instance.delete()
        return Response({"details": f"Successfuly Deleted Algo ID #{instance_id}" }, 
        status=status.HTTP_200_OK)
    

class FileAssociationCreateView(generics.CreateAPIView):
   # permission_classes = [IsAuthenticated, IsTTAdmin]
    serializer_class = FileAssociationCreateSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
                fa = serializer.save()
                return Response({
                    "id": fa.id,
                    "file_name": fa.file_name,
                }, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



class FileAssociationUpdateView(generics.UpdateAPIView):
    queryset = FileAssociation.objects.all()
    serializer_class = FileAssociationUpdateSerializer

    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        list_serializer = FileAssociationListSerializer(instance)
        return Response(list_serializer.data, status=status.HTTP_200_OK)

# class FileAssociationUpdateView(generics.UpdateAPIView):
#     queryset = FileAssociation.objects.all()
#     serializer_class = FileAssociationUpdateSerializer

#     def patch(self, request, *args, **kwargs):
#         instance = self.get_object()


#         old_ftp_path = instance.file_path
#         old_file_name = instance.file_name

#         # Perform update
#         serializer = self.get_serializer(instance, data=request.data, partial=True)
#         serializer.is_valid(raise_exception=True)
#         updated_instance = serializer.save()

#         response_data = {
#             "updated": True,
#             "file_reparsed": False,   # default unless change detected
#         }

#         # Detect if a file source changed
#         source_changed = (
#             updated_instance.file_path != old_ftp_path
#             or updated_instance.file_name != old_file_name
#         )

#         if source_changed:
#             try:
#                 # Fetch file bytes (FTP or uploaded file)
#                 if updated_instance.file_path:
#                     content_bytes = fetch_ftp_bytes(updated_instance.file_path)
#                 elif updated_instance.file_name: 
#                     # If needed, fetch from stored file (optional depending on design)
#                     content_bytes = read_uploaded_file_bytes(updated_instance.file_name)
#                 else:
#                     return Response({"detail": "No valid file source found after update."}, status=400)

#                 # Detect algorithm
#                 detected_algo = assign_detected_algo(updated_instance, content_bytes)

#                 # Check file change using hashing
#                 changed, new_hash = is_file_changed(updated_instance, content_bytes)

#                 if changed:
#                     # Parse + update stored dataset
#                     rows_count = store_csv_data(updated_instance, content_bytes, new_hash, url=updated_instance.file_path)

#                     response_data.update({
#                         "file_reparsed": True,
#                         "rows": rows_count,
#                         "algo_detected": detected_algo,
#                         "detail": "Source changed → CSV reprocessed"
#                     })
#                 else:
#                     updated_instance.last_fetched_at = timezone.now()
#                     updated_instance.save(update_fields=['last_fetched_at'])

#                     response_data.update({
#                         "file_reparsed": False,
#                         "algo_detected": detected_algo,
#                         "detail": "Source changed but file contents unchanged"
#                     })

#             except Exception as e:
#                 return Response({"detail": f"File reprocessing failed: {str(e)}"}, status=400)

#         list_serializer = FileAssociationListSerializer(updated_instance)
#         response_data["record"] = list_serializer.data

#         return Response(response_data, status=status.HTTP_200_OK)




class FileAssociationDeleteView(generics.DestroyAPIView):
   # permission_classes = [IsAuthenticated, IsTTAdmin]
    queryset = FileAssociation.objects.all()

    def delete(self, request, pk):
        try:
            instance = FileAssociation.objects.get(id = pk)
        except FileAssociation.DoesNotExist:
            return Response({"detail": "File Association not found."}, status=404)

        instance_id = instance.id
        instance.delete()
        return Response(
            {"detail": f"File Association {instance_id} deleted successfully."},
            status=status.HTTP_204_NO_CONTENT
        )


class FileAssociationListView(ListAPIView):
    serializer_class = FileAssociationListSerializer
    queryset = FileAssociation.objects.all()


class CSVUploadView(generics.GenericAPIView):
   # permission_classes = [IsAuthenticated, IsTTAdmin]
    serializer_class = CSVUploadSerializer

    def post(self, request, pk):
        fa = FileAssociation.objects.filter(id=pk).first()
        if not fa:
            return Response({"detail": "File Association not found."}, status=404)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        file_obj = serializer.validated_data.get('file')
        ftp_path = serializer.validated_data.get('ftp_path')

        try:
            if file_obj:
                content_bytes = read_uploaded_file_bytes(file_obj)
            elif ftp_path:
                content_bytes = fetch_ftp_bytes(ftp_path)
            else:
                return Response({"detail": "No file source provided."}, status=400)
        except Exception as e:
            return Response({"detail": f"Could not fetch file: {str(e)}"}, status=400)

        try:
            detected_algo = assign_detected_algo(fa, content_bytes)
        except UnknownAlgoError as e:
            return Response({"detail": str(e)}, status=400)

        changed, new_hash = is_file_changed(fa, content_bytes)
        if not changed:
            fa.last_fetched_at = timezone.now()
            fa.save(update_fields=['last_fetched_at'])
            return Response({"changed": False, "algo": detected_algo, "detail": "No changes detected."}, status=200)

        try:
            rows_count = store_csv_data(fa, content_bytes, new_hash, url=ftp_path)
        except Exception as e:
            return Response({"detail": f"CSV parse error: {str(e)}"}, status=400)

        return Response({"changed": True, "rows": rows_count, "algo": detected_algo}, status=201)


class GlobalAlertCreateView(generics.CreateAPIView):
    serializer_class = GlobalAlertCreateSerializer

    def post(self, request, *args, **kwargs):
        pk = self.kwargs.get("pk")
        if not pk:
            return Response({"detail": "fa_id is required in URL."}, status=400)

        fa = get_object_or_404(FileAssociation, pk=pk)
        serializer = self.get_serializer(data=request.data, context={'file_association': fa})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        print(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED)



class GlobalAlertUpdateView(generics.UpdateAPIView):
    serializer_class = GlobalAlertUpdateSerializer
    queryset = GlobalAlertRule.objects.all()

    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save() 
        return Response(serializer.data, status=status.HTTP_200_OK)

    

class GlobalAlertDeleteView(generics.DestroyAPIView):
    # permission_classes = [IsAuthenticated, IsTTAdmin]
    queryset = GlobalAlertRule.objects.all()

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance_id = instance.id
        instance.delete()
        return Response({"details": f"Successfuly Deleted Global Alert ID #{instance_id}" }, 
        status=status.HTTP_200_OK)


class GlobalAlertListView(generics.ListAPIView):
    serializer_class = GlobalAlertListSerializer
    queryset = GlobalAlertRule.objects.all()


class SymIntListView(generics.ListAPIView):
    queryset = MainData.objects.all()

    def find_sym_int_column(self, headers):
        for h in headers:
            normalized = (
                str(h).lower()
                .replace(" ", "")
                .replace("_", "")
                .replace("-", "")
                .replace("/", "")
            )
            if "sym" in normalized and "int" in normalized:
                return h
        return None
    
    def get(self, request, pk):
        try:
            fa = FileAssociation.objects.get(id = pk)
        except FileAssociation.DoesNotExist:
            return Response({"detail": "File Association Does Not Exist"},status=status.HTTP_404_NOT_FOUND)
        main_data = MainData.objects.filter(file_association=fa).first()

        if not main_data:
            return Response({"detail": "MainData not found for this FileAssociation"}, status=404)
        
        sym_int_key = self.find_sym_int_column(fa.headers)
        print(sym_int_key)
        if not sym_int_key:
            return Response({"details ":'Could not detect Symbol/Interval column'}, status=status.HTTP_400_BAD_REQUEST)
        
        all_rows = main_data.data_json.get("rows", [])
        valid_sym_int_values = {
            str(row.get(sym_int_key, ""))
            for row in all_rows if sym_int_key in row
        }
        print(valid_sym_int_values)

        return Response(valid_sym_int_values, status=200)



@api_view(["POST"])
def send_announcement(request):
    message = request.data.get("message", "").strip()

    if not message:
        return Response({"error": "Message cannot be empty"}, status=400)

    task = send_sms_notifications.delay(message)

    return Response({
        "status": "queued",
        "task_id": task.id,
        "message": "Success! Your message is now being sent to all recipients."
    }, status=status.HTTP_200_OK)


class UserRoleView(generics.ListAPIView):
    serializer_class = UserRoleSerializer

    def get(self, request):
        user = MENTUser.objects.first()

        if not user:
            return Response({"error": "No test user found"}, status=404)

        serializer = self.get_serializer(user)
        return Response(serializer.data)