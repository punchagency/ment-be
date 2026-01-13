from django.db.models import Q
from django.forms import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from .models import (
    FileAssociation, MainData, FavoriteRow, 
    MENTUser, CustomAlert, TriggeredAlert, UserSettings,  
    Algo, Group, Interval
)
from django.shortcuts import get_object_or_404
from .serializers import (
    CustomAlertCreateSerializer, CustomAlertUpdateSerializer, 
    UserSettingsSerializer,GroupSerializer, IntervalSerializer,
    TriggeredAlertSerializer
)
from  rest_framework import status
from rest_framework import generics
from .utils.csv_utils import fetch_ftp_bytes, parse_csv_bytes_to_dicts
import re
from django.core.cache import cache



class CSVListView(generics.GenericAPIView):
    def get(self, request, pk):
        cache_key = f"csv_data_{pk}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return Response(cached_data, status=200)
        
        try:
            fa = FileAssociation.objects.only(
                'id', 'file_path', 'data_version'
            ).get(id=pk)
        except FileAssociation.DoesNotExist:
            return Response(
                {"detail": "File Association Does Not Exist"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        content_bytes = fetch_ftp_bytes(fa.file_path)        
        headers, rows = parse_csv_bytes_to_dicts(content_bytes, fa=fa)
        
        response_data = {
            "data_version": fa.data_version,
            "headers": headers,
            "rows": rows[1:]
        }
        
        cache.set(cache_key, response_data, timeout=30)
        
        return Response(response_data, status=200)


class CSVHeaderView(generics.GenericAPIView):
    def get(self, request, pk):
        cache_key = f"csv_headers_{pk}"
        cached_headers = cache.get(cache_key)
        
        if cached_headers is not None:
            return Response(cached_headers, status=200)
        
        try:
            fa = FileAssociation.objects.only('file_name', 'headers').get(id=pk)
        except FileAssociation.DoesNotExist:
            return Response({"detail": "File Association Does Not Exist"}, status=404)
        
        if 'ttscanner' in fa.file_name.lower():
            headers = [
                header
                for header in fa.headers[1:]
                if 'datetime' not in header.lower()
                if 'color' not in header.lower()
            ]
        else:
            headers = fa.headers[1:]
        cache.set(cache_key, headers, timeout=300)
        
        return Response(headers, status=200)



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
        cache_key = f"sym_int_values_{pk}"
        cached_values = cache.get(cache_key)
        
        if cached_values is not None:
            return Response(cached_values, status=200)
        
        try:
            fa = FileAssociation.objects.only('headers').get(id=pk)
        except FileAssociation.DoesNotExist:
            return Response({"detail": "File Association Does Not Exist"}, status=404)
        
        main_data = MainData.objects.filter(
            file_association=fa
        ).only('data_json').first()

        if not main_data:
            return Response({"detail": "MainData not found"}, status=404)
        
        sym_int_key = self.find_sym_int_column(fa.headers)
        if not sym_int_key:
            return Response({"details": 'Could not detect Symbol/Interval column'}, status=400)
        all_rows = main_data.data_json.get("rows", [])
        valid_sym_int_values = set()
        
        for row in all_rows:
            if sym_int_key in row:
                value = str(row[sym_int_key])
                if value: 
                    valid_sym_int_values.add(value)
        
        values_list = list(valid_sym_int_values)
        cache.set(cache_key, values_list, timeout=300)
        
        return Response(values_list, status=200)


class FavoriteRowView(APIView):
    def post(self, request, pk):
        external_user_id = request.data.get("external_user_id")
        sym_int_value = request.data.get("sym_int")

        if not external_user_id or not sym_int_value:
            return Response(
                {"detail": "Missing external_user_id or Sym/Int"},
                status=status.HTTP_400_BAD_REQUEST
            )

        fa = get_object_or_404(FileAssociation, id=pk)
        main_data = get_object_or_404(MainData, file_association=fa)
        user = get_object_or_404(MENTUser, external_user_id=external_user_id)

        sym_int_value = str(sym_int_value).lower().strip()
        pattern = re.compile(r"sym.*int|symbol.*interval", re.IGNORECASE)
        headers = main_data.data_json.get("headers", [])
        
        sym_int_key = None
        for header in headers:
            normalized = re.sub(r"[ _/]", "", header.lower())
            if pattern.search(normalized):
                sym_int_key = header
                break
        
        if not sym_int_key:
            return Response(
                {"detail": "Sym/Int column not found in data"},
                status=status.HTTP_400_BAD_REQUEST
            )

        matching_row = None
        for row in main_data.data_json.get("rows", []):
            value = row.get(sym_int_key)
            if value and str(value).lower().strip() == sym_int_value:
                matching_row = row
                break

        if not matching_row:
            return Response(
                {"detail": "Row not found in MainData"},
                status=status.HTTP_404_NOT_FOUND
            )

        favorite, created = FavoriteRow.objects.get_or_create(
            user=user,
            file_association=fa,
            row_id=matching_row["_row_id"],
            defaults={"row_hash": matching_row["_row_hash"]}
        )

        return Response(
            {
                "favorite_id": favorite.id,
                "row_id": matching_row["_row_id"],
                "row_hash": matching_row["_row_hash"],
                "created": created
            },
            status=status.HTTP_201_CREATED
        )
    


class DeleteFavoriteView(generics.DestroyAPIView):
    queryset = FavoriteRow.objects.all()
    lookup_field = 'pk'

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance_id = instance.id
        instance.delete()
        return Response(
            {"details": f"Successfully deleted Favorite Row ID #{instance_id}"},
            status=status.HTTP_200_OK
        )


from django.db.models import Prefetch

class FavoriteRowListView(APIView):
    def get(self, request, external_user_id):
        try:
            user = MENTUser.objects.only('id').get(external_user_id=external_user_id)
        except MENTUser.DoesNotExist:
            return Response(
                {"detail": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        favorites = FavoriteRow.objects.filter(user=user).select_related(
            'file_association'
        ).only(
            'id', 'row_id', 'row_hash', 
            'file_association__id',
            'file_association__algo_name_copy',
            'file_association__group_name_copy',
            'file_association__interval_name_copy',
            'file_association__headers'
        )
        
        if not favorites.exists():
            return Response([], status=200)

        file_association_ids = [fav.file_association_id for fav in favorites]

        main_data_list = MainData.objects.filter(
            file_association_id__in=file_association_ids
        ).only('file_association_id', 'data_json')

        main_data_dict = {}
        for md in main_data_list:
            main_data_dict[md.file_association_id] = md.data_json
        grouped = {}
        
        for fav in favorites:
            fa = fav.file_association
            fa_id = fa.id
            data_json = main_data_dict.get(fa_id)
            if not data_json:
                continue
            if fa_id not in grouped:
                grouped[fa_id] = {
                    "file_association_id": fa_id,
                    "file_association_name": f"{fa.algo_name_copy} {fa.group_name_copy} {fa.interval_name_copy}",
                    "headers": fa.headers,
                    "rows": []
                }
                rows_dict = {}
                for row in data_json.get("rows", []):
                    row_id = row.get("_row_id")
                    if row_id:
                        rows_dict[row_id] = row
                
                grouped[fa_id]['_rows_dict'] = rows_dict
            rows_dict = grouped[fa_id]['_rows_dict']
            matching_row = rows_dict.get(fav.row_id)
            
            if not matching_row:
                continue

            headers_to_include = [h for h in fa.headers if not h.startswith("_")]
            row_data = {h: matching_row.get(h) for h in headers_to_include}

            row_data.update({
                "favorite_id": fav.id,
                "row_id": fav.row_id,
                "row_hash": matching_row.get("_row_hash")
            })
            
            grouped[fa_id]["rows"].append(row_data)

        for fa_id in grouped:
            if '_rows_dict' in grouped[fa_id]:
                del grouped[fa_id]['_rows_dict']
        
        return Response(list(grouped.values()), status=200)



class CustomAlertView(generics.ListAPIView):
    serializer_class = CustomAlertCreateSerializer

    def get_queryset(self):
        external_user_id = self.kwargs.get("external_user_id")
        user = get_object_or_404(MENTUser, external_user_id=external_user_id)
        return CustomAlert.objects.filter(user=user)



class CustomAlertCreateView(generics.CreateAPIView):
    serializer_class = CustomAlertCreateSerializer

    def post(self, request, *args, **kwargs):
        external_user_id = self.kwargs.get("external_user_id")
        user = get_object_or_404(MENTUser, external_user_id=external_user_id)
        fa_id = request.data.get("file_association")
        fa = get_object_or_404(FileAssociation, pk=fa_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        save_alert = serializer.save(user=user, file_association=fa)

        return Response(
            {
                "detail": f"Custom alert created for column '{serializer.validated_data['field_name']}'.",
                "alert": save_alert.id,
            },
            status=201
        )



class CustomAlertUpdateView(generics.UpdateAPIView):
    serializer_class = CustomAlertUpdateSerializer
    queryset = CustomAlert.objects.all()
    lookup_field = 'pk'

    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data = request.data, partial = True)
        serializer.is_valid(raise_exception = True)
        updated_alert = serializer.save()
        return Response(serializer.data, status=status.HTTP_205_RESET_CONTENT)


class CustomAlertDeleteView(generics.DestroyAPIView):
    queryset = CustomAlert.objects.all()
    lookup_field = 'pk'

    def delete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance_id = instance.id
        instance.delete()
        return Response({"details": f"Successfuly Deleted Custom Alert ID #{instance_id}" }, 
        status=status.HTTP_200_OK)

 

class UserTriggeredAlertsView(APIView):
    def get(self, request, *args, **kwargs):
        external_user_id = self.kwargs.get("external_user_id")
        
        try:
            user = MENTUser.objects.only('id').get(external_user_id=external_user_id)
        except MENTUser.DoesNotExist:
            return Response(
                {"detail": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        alerts = TriggeredAlert.objects.filter(
            Q(alert_source="global") |
            Q(alert_source="system") |
            Q(alert_source="custom", custom_alert__user=user)
        ).select_related(
            'custom_alert',  
            'global_alert',  
            'file_association'  
        ).only(
            'id', 'alert_source', 'symbol', 'triggered_at', 
            'acknowledged', 'message', 'custom_alert_id', 'global_alert_id',
            'file_association_id'
        ).order_by('-triggered_at')  
        
        serializer = TriggeredAlertSerializer(alerts, many=True)
        return Response(serializer.data)


class UserSettingsCreateView(generics.CreateAPIView):
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

    def get_object(self):
        external_user_id = self.kwargs.get("pk")

        if not external_user_id:
            raise ValidationError("External user ID is required")

        user, _ = MENTUser.objects.get_or_create(
            external_user_id=external_user_id
        )
        print(user)

        settings, _ = UserSettings.objects.get_or_create(
            user=user,
            defaults={
                "alerts_enabled": False,
                "delivery_methods": [],
                "alert_email": None,
                "alert_phone": None,
            }
        )
        print(settings)

        return settings

    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserSettingsView(generics.ListAPIView):
    serializer_class = UserSettingsSerializer

    def get(self, request, external_user_id):
        try:
            user = MENTUser.objects.get(external_user_id=external_user_id)
        except MENTUser.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        user_settings = UserSettings.objects.filter(user=user)
        serializer = self.get_serializer(user_settings, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AlgoGroupsView(APIView):
    def get(self, request, algo_pk):
        try:
            Algo.objects.only('id').get(pk=algo_pk)
        except Algo.DoesNotExist:
            return Response({"detail": "Algo not found."}, status=status.HTTP_404_NOT_FOUND)

        group_qs = Group.objects.filter(
            fileassociation__algo_id=algo_pk
        ).distinct().only(
            'id', 'group_name' 
        ).order_by('group_name')
        
        serializer = GroupSerializer(group_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AlgoGroupIntervalsView(APIView):
    def get(self, request, algo_pk, group_pk):
        try:
            Algo.objects.only('id').get(pk=algo_pk)
        except Algo.DoesNotExist:
            return Response({"detail": "Algo not found."}, status=status.HTTP_404_NOT_FOUND)
            
        filter_kwargs = {'fileassociation__algo_id': algo_pk}
        
        if group_pk in ("none", "null", "0", "", None):
            filter_kwargs['fileassociation__group__isnull'] = True
        else:
            try:
                Group.objects.only('id').get(pk=group_pk)
                filter_kwargs['fileassociation__group_id'] = group_pk
            except Group.DoesNotExist:
                return Response({"detail": "Group not found."}, status=status.HTTP_404_NOT_FOUND)

        interval_qs = Interval.objects.filter(
            **filter_kwargs
        ).distinct().only(
            'id', 'interval_name'  
        ).order_by('interval_minutes')  
        
        serializer = IntervalSerializer(interval_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    

class FileAssociationLookupView(APIView):
    def get(self, request):
        algo_id = request.query_params.get("algo")
        group_id = request.query_params.get("group")
        interval_id = request.query_params.get("interval")

        if not algo_id or not interval_id:
            return Response(
                {"detail": "Query params 'algo' and 'interval' are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if group_id in (None, "", "null", "none"):
            fa = FileAssociation.objects.filter(
                algo_id=algo_id,  
                interval_id=interval_id,
                group__isnull=True
            ).select_related(
                'algo', 'interval'
            ).only(
                'id', 'data_version', 'algo__algo_name', 'interval__interval_name'
            ).first()
        else:
            fa = FileAssociation.objects.filter(
                algo_id=algo_id,
                interval_id=interval_id,
                group_id=group_id
            ).select_related(
                'algo', 'interval', 'group'
            ).only(
                'id', 'data_version', 'algo__algo_name', 
                'interval__interval_name', 'group__group_name'
            ).first()

        if not fa:
            return Response(
                {"detail": "No file association for the provided combination."},
                status=status.HTTP_404_NOT_FOUND
            )

        main_data = MainData.objects.filter(
            file_association=fa
        ).only('data_json').first()
        
        if not main_data:
            return Response(
                {"detail": "No data found for this FileAssociation."},
                status=status.HTTP_404_NOT_FOUND
            )

        headers = main_data.data_json.get("headers", [])
        rows = main_data.data_json.get("rows", [])
        headers_to_include = [h for h in headers if not h.startswith("_")]
        cleaned_rows = [
            {
                **{h: row.get(h) for h in headers_to_include},
                "_row_hash": row.get("_row_hash")
            }
            for row in rows
        ]

        return Response(
            {
                "file_association_id": fa.id,
                "data_version": fa.data_version,
                "headers": headers,
                "rows": cleaned_rows
            },
            status=200
        )
    

