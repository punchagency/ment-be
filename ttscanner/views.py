from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from rest_framework import status
from django.utils import timezone
from rest_framework import generics
from .models import FileAssociation, GlobalAlertRule
from .serializers import (
    CSVUploadSerializer, 
    FileAssociationCreateSerializer, FileAssociationUpdateSerializer,
    GlobalAlertSerializer
)
from .permissions import IsTTAdmin
from rest_framework.permissions import IsAuthenticated
from .utils.csv_utils import (
    read_uploaded_file_bytes,
    is_file_changed, store_csv_data,
    fetch_ftp_bytes
)


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
   # permission_classes = [IsAuthenticated, IsTTAdmin]
    serializer_class = FileAssociationUpdateSerializer
    queryset = FileAssociation.objects.all()

    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data = request.data, partial = True)
        serializer.is_valid(raise_exception = True)
        fa = serializer.save()
        return Response({
            "id": fa.id,
            "file_name": fa.file_name,
        }, status=status.HTTP_205_RESET_CONTENT)


class FileAssociationDeleteView(generics.DestroyAPIView):
   # permission_classes = [IsAuthenticated, IsTTAdmin]
    queryset = FileAssociation.objects.all()

    def delete(self, request, fa_id):
        try:
            instance = FileAssociation.objects.get(id = fa_id)
        except FileAssociation.DoesNotExist:
            return Response({"detail": "File Association not found."}, status=404)

        instance_id = instance.id
        instance.delete()
        return Response(
            {"detail": f"File Association {instance_id} deleted successfully."},
            status=status.HTTP_204_NO_CONTENT
        )


class CSVUploadView(generics.GenericAPIView):
  #  permission_classes = [IsAuthenticated, IsTTAdmin]
    serializer_class = CSVUploadSerializer

    def post(self, request, fa_id):
        try:
            fa = FileAssociation.objects.get(id=fa_id)
        except FileAssociation.DoesNotExist:
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
        
        changed, new_hash = is_file_changed(fa, content_bytes)
        if not changed:
            fa.last_fetched_at = timezone.now()
            fa.save(update_fields=['last_fetched_at'])
            return Response({"changed": False, "detail": "No changes detected."}, status=200)
        
        try:
            rows_count = store_csv_data(fa, content_bytes, new_hash, url=ftp_path)
        except Exception as e:
            return Response({"detail": f"CSV parse error: {str(e)}"}, status=400)

        return Response({"changed": True, "rows": rows_count}, status=201)


class GlobalAlertCreateView(generics.CreateAPIView):
   # permission_classes = [IsAuthenticated, IsTTAdmin]
    serializer_class = GlobalAlertSerializer

    def post(self, request, *args, **kwargs):
        pk = self.kwargs.get("pk")
        if not pk:
            return Response({"detail": "fa_id is required in URL."}, status=status.HTTP_400_BAD_REQUEST)

        fa = get_object_or_404(FileAssociation, pk = pk)
        serializer = self.get_serializer(data = request.data)
        serializer.is_valid(raise_exception=True)
        column = serializer.validated_data['field_name']

        global_alert = GlobalAlertRule.objects.create(
            file_association=fa,
            field_name=column,
            field_type=serializer.validated_data['field_type'],
            condition_type=serializer.validated_data['condition_type'],
            compare_value=serializer.validated_data['compare_value']
        )

        return Response(
            {
                "detail": f"Global alert created for column '{column}'",
                "alert": global_alert.id,
            }, 
            status=201
        )


class GlobalAlertUpdateView(generics.UpdateAPIView):
    # permission_classes = [IsAuthenticated, IsTTAdmin]
    serializer_class = GlobalAlertSerializer
    queryset = GlobalAlertRule.objects.all()

    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data = request.data, partial = True)
        serializer.is_valid(raise_exception = True)
        updated_alert = serializer.save()
        return Response({
            "id": updated_alert.id,
            "field_name": updated_alert.field_name,
            "field_type": updated_alert.field_type,
            "condition_type": updated_alert.condition_type,
            "compare_value": updated_alert.compare_value,
            "file_association": updated_alert.file_association.id,
        }, status=status.HTTP_205_RESET_CONTENT)
    

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
    serializer_class = GlobalAlertSerializer
    queryset = GlobalAlertRule.objects.all()
    
