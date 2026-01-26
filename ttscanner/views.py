from rest_framework.response import Response
from rest_framework.generics import ListAPIView
from django.shortcuts import get_object_or_404
from rest_framework import status
from django.utils import timezone
from rest_framework import generics
from .models import (
    FileAssociation, GlobalAlertRule, Algo, 
    Group, Interval, TriggeredAlert
)
from ttscanner.utils.algo_detector import assign_detected_algo, UnknownAlgoError
from .serializers import (
    CSVUploadSerializer, 
    FileAssociationCreateSerializer, FileAssociationUpdateSerializer,
    FileAssociationUpdateSerializer, GlobalAlertCreateSerializer,
    FileAssociationListSerializer, AlgoSerializer,
    GroupSerializer, IntervalSerializer,
    GlobalAlertListSerializer, GlobalAlertUpdateSerializer,
    TriggeredAlertSerializer
)
from .permissions import IsTTAdmin
from rest_framework.permissions import IsAuthenticated
from .utils.csv_utils import (
    read_uploaded_file_bytes,
    is_file_changed, store_csv_data,
    fetch_ftp_bytes
)

#ALGO VIEWS
class AlgoListView(ListAPIView):
    serializer_class = AlgoSerializer
    
    def get_queryset(self):
        return Algo.objects.only('id', 'algo_name', 'supports_targets', 'supports_direction')
    

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
    def get_queryset(self):
        return Group.objects.only('id', 'group_name')

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
    def get_queryset(self):
        return Interval.objects.only('id', 'interval_name', 'interval_minutes')


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
                print(f"ID: {fa.id}, algo_id: {fa.algo_id}")
                print(f"File Association created with ID: {fa.id}, File Name: {fa.file_name}, Algo: {fa.algo.algo_name}")
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

        ftp_path_before = instance.file_path
        ftp_path_after = request.data.get("file_path", ftp_path_before)

        if ftp_path_after != ftp_path_before:
            instance.data_version = 0
            try:
                content_bytes = fetch_ftp_bytes(ftp_path_after)
            except Exception as e:
                return Response(
                    {"detail": f"Could not fetch file from new FTP path: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                changed, new_hash = is_file_changed(instance, content_bytes)
                if changed:
                    rows_count = store_csv_data(instance, content_bytes, new_hash, url=ftp_path_after)
                    instance.last_fetched_at = timezone.now()
                    print(f"[UPDATE] CSV updated for {instance.file_name} with {rows_count} rows.")
            except Exception as e:
                return Response(
                    {"detail": f"CSV parse error: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        serializer.save()
        list_serializer = FileAssociationListSerializer(instance)
        return Response(list_serializer.data, status=status.HTTP_200_OK)



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

    def get_queryset(self):
        return FileAssociation.objects.select_related('algo', 'group', 'interval')\
            .only(
                'id',
                'file_name',
                'file_path',
                'algo__algo_name',
                'group__group_name',
                'interval__interval_name',
                'algo_name_copy',
                'group_name_copy',
                'interval_name_copy',
            ).order_by('-created_at')




class CSVUploadView(generics.GenericAPIView):
    serializer_class = CSVUploadSerializer

    def post(self, request, pk):
        fa = FileAssociation.objects.get(id=pk)
        
        # Store original algo BEFORE any processing
        original_algo_id = fa.algo_id
        print(f"Original algo_id: {original_algo_id}")
        
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
        
        changed, new_hash = is_file_changed(fa, content_bytes)
        if not changed:
            fa.algo_id = original_algo_id
            fa.last_fetched_at = timezone.now()
            fa.save()  
            return Response({
                "changed": False, 
                "detail": "No changes detected.",
                "algo": fa.algo.algo_name if fa.algo else "Unknown"
            }, status=200)

        try:
            fa.algo_id = original_algo_id
            rows_count = store_csv_data(fa, content_bytes, new_hash, url=ftp_path)
        except Exception as e:
            return Response({"detail": f"CSV parse error: {str(e)}"}, status=400)

        return Response({
            "changed": True, 
            "rows": rows_count,
            "algo": fa.algo.algo_name if fa.algo else "Unknown"
        }, status=201)
    
    

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
    
    def get_queryset(self):
        return GlobalAlertRule.objects.select_related(
            'file_association'
        ).only(
            'id', 'symbol_interval', 'field_name', 'condition_type',
            'compare_value', 'last_value', 'is_active', 'created_at',
            'file_association_id'
        )



class TriggeredAlertsAdminView(generics.ListAPIView):
    serializer_class = TriggeredAlertSerializer
    
    def get_queryset(self):
        return TriggeredAlert.objects.filter(
            alert_source__in=['global', 'system']
        ).select_related(
            'global_alert', 'file_association'
        ).only(
            'id', 'alert_source', 'symbol', 'triggered_at',
            'acknowledged', 'message', 'global_alert_id',
            'file_association_id'
        ).order_by('-triggered_at')

