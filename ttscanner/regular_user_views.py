from rest_framework.response import Response
from .models import FileAssociation, MainData, FavoriteRow, MENTUser, CustomAlert, UserSettings
from django.shortcuts import get_object_or_404
from .serializers import (
    FavoriteRowSerializer, CustomAlertSerializer, 
    CustomAlertUpdateSerializer, UserSettingsSerializer
)
from rest_framework.views import APIView
from  rest_framework import status
from rest_framework import generics
from .utils.csv_utils import fetch_ftp_bytes, parse_csv_bytes_to_dicts
from .utils.email_utils import send_alert_email

class CSVListView(generics.GenericAPIView):
    def get(self, request, fa_id):
        try:
            fa = FileAssociation.objects.get(id = fa_id)
        except FileAssociation.DoesNotExist:
            return Response({"detail": "File Association Does Not Exist"},status=status.HTTP_404_NOT_FOUND)
        
        content_bytes = fetch_ftp_bytes(fa.file_path)        
        headers, rows = parse_csv_bytes_to_dicts(content_bytes, fa=fa)            
        return Response({"headers": headers, "rows": rows}, status=200)


class FilterCSVView(generics.ListAPIView):
    def get(self, request, fa_id):
        field = request.GET.get("field")
        value = request.GET.get("value")

        if not field:
            return Response({"error": "field is required"}, status=400)
        if not value:
            return Response({"error": "value is required"}, status=400)

        try:
            main_data = MainData.objects.get(file_association_id=fa_id)
        except MainData.DoesNotExist:
            return Response({"error": "Data Table not found"}, status=404)

        rows = main_data.data_json.get("rows", [])
        filtered_rows = []
        is_numeric_search = False
        value_lower = str(value).lower()
        try:
            numeric_value = float(value)
            is_numeric_search = True
        except ValueError:
            pass
        closest_row = None
        closest_diff = float('inf')
        for row in rows:
            if field not in row:
                continue
            row_value = row[field]
            if is_numeric_search and isinstance(row_value, (int, float)):
                diff = abs(numeric_value - row_value)
                if numeric_value == row_value:
                    filtered_rows.append(row) 
                elif diff < closest_diff:
                    closest_diff = diff
                    closest_row = row
            else: 
                row_value_str = str(row_value).strip()
                typed_value_str = str(value).strip()

                if row_value_str == typed_value_str:
                    filtered_rows.append(row)
                elif len(typed_value_str) < len(row_value_str) and row_value_str.startswith(typed_value_str):
                    filtered_rows.append(row)

        if is_numeric_search and not filtered_rows and closest_row:
            filtered_rows.append(closest_row)

        return Response({
            "filtered_count": len(filtered_rows),
            "filtered_rows": filtered_rows
        })


class CSVHeaderView(generics.GenericAPIView):
    def get(self,request, fa_id):
        try:
            fa = FileAssociation.objects.get(id = fa_id)
        except FileAssociation.DoesNotExist:
            return Response({"detail": "File Association Does Not Exist"},status=status.HTTP_404_NOT_FOUND)

        headers = fa.headers
        return Response({"Headers": headers}, status=status.HTTP_200_OK)

                    
class SortCSVView(generics.GenericAPIView):
    def get(self, request, fa_id):

        field = request.GET.get('field')
        direction = request.GET.get('direction')

        if not field:
            return Response({"error": "field is required"}, status=400)

        try:
            main_data = MainData.objects.get(file_association_id=fa_id)
        except MainData.DoesNotExist:
            return Response({"error": "Data Table not found"}, status=404)

        data = main_data.data_json
        headers = data.get("headers", [])
        rows = data.get("rows", [])[1:]  

        if field not in headers:
            return Response({"error": f"Field '{field}' not found in headers"}, status=400)

        try:
            sorted_rows = sorted(
                rows,
                key=lambda row: row.get(field) if row.get(field) is not None else "",
                reverse=(direction == "asc")
            )
        except Exception as e:
            return Response({"error": f"Sorting failed: {str(e)}"}, status=400)
        
        final_sorted_rows = [
            {header: row.get(header) for header in headers}
            for row in sorted_rows
        ]

        return Response({
            "headers": headers,
            "sorted": final_sorted_rows
        })


class FavoriteRowView(generics.CreateAPIView):
    serializer_class = FavoriteRowSerializer

    def post(self, request, fa_id):
        fa = get_object_or_404(FileAssociation, id=fa_id)
        external_user_id = request.data.get('external_user_id')
        user = get_object_or_404(MENTUser, external_user_id=external_user_id)
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=user, file_association=fa)
        return Response({'details': 'Row added in Favorite Page'}, status=status.HTTP_201_CREATED)


class CustomAlertCreateView(generics.CreateAPIView):
    serializer_class = CustomAlertSerializer

    def post(self, request, *args, **kwargs):
        pk = self.kwargs.get("pk")
        if not pk:
            return Response(
                {"detail": "User ID must be provided."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = get_object_or_404(MENTUser, pk=pk)
        self.ment_user = user
        fa_id = request.data.get("file_association")
        if not fa_id:
            return Response(
                {"detail": "file_association must be provided in payload."},
                status=status.HTTP_400_BAD_REQUEST
            )
        fa = get_object_or_404(FileAssociation, pk=fa_id)
        self.file_association = fa
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        column = serializer.validated_data["field_name"]
        serializer.save(user=user, file_association=fa)

        return Response(
            {
                "detail": f"Custom alert created for column '{column}'.",
                "alert": custom_alert.id,
            },
            status=201
        )


class CustomAlertUpdateView(generics.UpdateAPIView):
    serializer_class = CustomAlertUpdateSerializer
    queryset = CustomAlert.objects.all()
    lookup_field = 'id'

    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data = request.data, partial = True)
        serializer.is_valid(raise_exception = True)
        updated_alert = serializer.save()
        return Response({
            "fa_id": updated_alert.id,
            "user": updated_alert.id,
            "field_name": updated_alert.field_name,
            "field_type": updated_alert.field_type,
            "condition_type": updated_alert.condition_type,
            "compare_value": updated_alert.compare_value,
            "file_association": updated_alert.file_association.id,
        }, status=status.HTTP_205_RESET_CONTENT)


class CustomAlertDeleteView(generics.DestroyAPIView):
    queryset = CustomAlert.objects.all()
    lookup_field = 'id'

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance_id = instance.id
        instance.delete()
        return Response({"details": f"Successfuly Deleted Custom Alert ID #{instance_id}" }, 
        status=status.HTTP_200_OK)


class UserSettingsView(generics.CreateAPIView):
    serializer_class = UserSettingsSerializer

    def post(self, request, *args, **kwargs):
        pk = self.kwargs.get("pk")
        if not pk:
            return Response({'details': 'User ID must be provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        user = MENTUser.objects.filter(id=pk).first()
        if not user:
            return Response({'details': 'User Not Found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=user)
        return Response({'details': 'Settings Saved'}, status=status.HTTP_200_OK)


class UpdateUserSettingsView(generics.UpdateAPIView):
    serializer_class = UserSettingsSerializer
    queryset = UserSettings.objects.all()
    lookup_field = 'pk'

    def patch(self, request, *args, **kwargs):
        pk = self.kwargs.get("pk")
        if not pk:
            return Response({'detail': 'User ID must be provided'}, status=status.HTTP_400_BAD_REQUEST)

        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_settings = serializer.save()

        return Response({
            "theme": updated_settings.theme,
            "alerts_enabled": updated_settings.alerts_enabled,
            "delivery_methods": updated_settings.delivery_methods,
            "alert_email": updated_settings.alert_email,
            "alert_phone": updated_settings.alert_phone
        }, status=status.HTTP_200_OK)
        

# class TestEmail(APIView):
#     def get(self, request):
#         send_alert_email(
#             to_email="test@example.com",
#             subject="Test Alert",
#             message="Your alert system is working!"
#         )
#         return Response({"message": "Email sent successfully"})
