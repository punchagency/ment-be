from itertools import chain
from django.forms import ValidationError
from rest_framework.response import Response
from django.http import StreamingHttpResponse
from rest_framework.views import APIView
from rest_framework import status
from .models import (
    FileAssociation, MainData, FavoriteRow, 
    MENTUser, CustomAlert, TriggeredAlert, UserSettings,  
    Algo, Group, Interval
)
from django.shortcuts import get_object_or_404
from .serializers import (
    FavoriteRowSerializer, CustomAlertCreateSerializer, 
    CustomAlertUpdateSerializer, UserSettingsSerializer, AlgoSerializer, 
    GroupSerializer, IntervalSerializer, FileAssociationListSerializer,
    TriggeredAlertSerializer
)
from  rest_framework import status
from rest_framework import generics
from .utils.csv_utils import fetch_ftp_bytes, parse_csv_bytes_to_dicts
import time, json, hashlib, re



class CSVListView(generics.GenericAPIView):
    def get(self, request, pk):
        try:
            fa = FileAssociation.objects.get(id = pk)
        except FileAssociation.DoesNotExist:
            return Response({"detail": "File Association Does Not Exist"},status=status.HTTP_404_NOT_FOUND)
        
        content_bytes = fetch_ftp_bytes(fa.file_path)        
        headers, rows = parse_csv_bytes_to_dicts(content_bytes, fa=fa)            
        return Response({"data_version": fa.data_version,"headers": headers, "rows": rows[1:]}, status=200)


# class CSVTargetHitView(generics.GenericAPIView):
#     def get(self, request, pk):
#         try:
#             fa = FileAssociation.objects.get(id=pk)
#         except FileAssociation.DoesNotExist:
#             return Response({"detail": "File Association Does Not Exist"}, status=404)

#         # Fetch bytes from FTP
#         content_bytes = fetch_ftp_bytes(fa.file_path)
#         headers, rows = parse_csv_bytes_to_dicts(content_bytes, fa=fa)

#         # Normalize headers
#         headers = [h.strip() for h in headers]

#         # Identify target columns
#         target_cols = [h for h in headers if "target" in h.lower() and "hit" not in h.lower()]

#         # Normalize row keys and values
#         normalized_rows = []
#         for row in rows:
#             row = {k.strip(): (v.strip() if v else "") for k, v in row.items()}
            
#             # Compute hit flags
#             for target_col in target_cols:
#                 datetime_col = f"{target_col} DateTime"
#                 dt_val = row.get(datetime_col, "")
#                 # Consider non-empty, non-dash values as hit
#                 row[f"{target_col} Hit"] = bool(dt_val and dt_val != "-")
            
#             normalized_rows.append(row)

#         # Apply filters from query params
#         query = request.query_params
#         target_filters = {}
#         for i, tc in enumerate(target_cols, start=1):
#             val = query.get(f"target{i}")
#             if val is not None:
#                 target_filters[tc] = str(val).lower() in ("1", "true", "t", "yes")

#         # Check if a row matches the filters
#         def row_matches(r):
#             for tc, desired in target_filters.items():
#                 if bool(r.get(f"{tc} Hit")) != desired:
#                     return False
#             return True

#         filtered_rows = [r for r in normalized_rows if row_matches(r)]

#         return Response({"data_version": fa.data_version, "headers": headers, "rows": filtered_rows}, status=200)


class FilterCSVView(generics.ListAPIView):
    def get(self, request, pk):
        field = request.GET.get("field")
        value = request.GET.get("value")

        if not field:
            return Response({"error": "field is required"}, status=400)
        if not value:
            return Response({"error": "value is required"}, status=400)

        try:
            main_data = MainData.objects.get(file_association_id=pk)
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
    def get(self,request, pk):
        try:
            fa = FileAssociation.objects.get(id = pk)

            print(fa.file_name)
        except FileAssociation.DoesNotExist:
            return Response({"detail": "File Association Does Not Exist"},status=status.HTTP_404_NOT_FOUND)
        
        if 'ttscanner' in fa.file_name.lower():
            headers = [
                header
                for header in fa.headers[1: ]
                if 'datetime' not in header.lower()
                if 'color' not in header.lower()
            ]
        else:
            headers = fa.headers[1: ]
        # print(f"Headers [1: ]: {headers[1:]}")
        # print(f"\n Headers: {headers}")
        return Response(headers, status=status.HTTP_200_OK)



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


class SortCSVView(generics.GenericAPIView):
    def convert_for_sort(self, value, direction):
        if value is None or value == "":
            return float('inf') if direction == "asc" else float('-inf')
        try:
            return float(value)
        except ValueError:
            return str(value).lower()

    def get(self, request, pk):
        field = request.GET.get('field')
        direction = request.GET.get('direction', 'asc').lower()

        if not field:
            return Response({"error": "field is required"}, status=400)

        try:
            main_data = MainData.objects.get(file_association_id=pk)
        except MainData.DoesNotExist:
            return Response({"error": "Data Table not found"}, status=404)

        data = main_data.data_json
        headers = data.get("headers", [])
        rows = data.get("rows", [])

        if field not in headers:
            return Response({"error": f"Field '{field}' not found in headers"}, status=400)

        try:
            sorted_rows = sorted(
                rows,
                key=lambda row: self.convert_for_sort(row.get(field, ""), direction),
                reverse=(direction == "desc")
            )
        except Exception as e:
            return Response({"error": f"Sorting failed: {str(e)}"}, status=400)

        final_sorted_rows = [
            {header: row.get(header, "") for header in headers}
            for row in sorted_rows
        ]

        return Response({
            "headers": headers,
            "sorted": final_sorted_rows
        })


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

        matching_row = None
        sym_int_value = str(sym_int_value).lower().strip()

        pattern = re.compile(r"sym.*int|symbol.*interval")

        for row in main_data.data_json.get("rows", []):
            for key, value in row.items():
                if value is None:
                    continue
                key_normalized = re.sub(r"[ _/]", "", key.lower())

                if pattern.search(key_normalized):
                    if str(value).lower().strip() == sym_int_value:
                        matching_row = row
                        break
            if matching_row:
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


class FavoriteRowListView(APIView):
    def get(self, request, external_user_id):
        try:
            user = MENTUser.objects.get(external_user_id=external_user_id)
        except MENTUser.DoesNotExist:
            return Response(
                {"detail": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        favorites = FavoriteRow.objects.filter(user=user).select_related("file_association")
        print(favorites)

        if not favorites.exists():
            return Response([], status=200)

        grouped = {}

        for fav in favorites:
            fa = fav.file_association
            main_data = MainData.objects.filter(file_association=fa).first()
            if not main_data:
                continue

            matching_row = None
            for row in main_data.data_json.get("rows", []):
                if row.get("_row_id") == fav.row_id:
                    matching_row = row
                    break

            if not matching_row:
                continue

            if fa.id not in grouped:
                grouped[fa.id] = {
                    "file_association_id": fa.id,
                    "file_association_name": f"{fa.algo_name_copy} {fa.group_name_copy} {fa.interval_name_copy}",
                    "headers": fa.headers,
                    "rows": []
                }

            row_data = {h: matching_row.get(h) for h in fa.headers if not h.startswith("_")}
            row_data["favorite_id"] = fav.id
            row_data["row_id"] = fav.row_id
            row_data["row_hash"] = matching_row.get("_row_hash")

            grouped[fa.id]["rows"].append(row_data)

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
        user = MENTUser.objects.get(external_user_id=external_user_id)

        global_alerts = TriggeredAlert.objects.filter(
            alert_source="global"
        )

        custom_alerts = TriggeredAlert.objects.filter(
            alert_source="custom",
            custom_alert__user=user
        )

        system_alerts = TriggeredAlert.objects.filter(
            alert_source="system"
        )

        alerts = list(chain(system_alerts, global_alerts, custom_alerts))
        alerts.sort(key=lambda a: a.triggered_at, reverse=True)

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
            algo = Algo.objects.get(pk=algo_pk)
        except Algo.DoesNotExist:
            return Response({"detail": "Algo not found."}, status=status.HTTP_404_NOT_FOUND)

        fas = FileAssociation.objects.filter(algo=algo).select_related('group')
        group_qs = Group.objects.filter(id__in=fas.values_list('group_id', flat=True).distinct())
        serializer = GroupSerializer(group_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AlgoGroupIntervalsView(APIView):
    def get(self, request, algo_pk, group_pk):
        try:
            algo = Algo.objects.get(pk=algo_pk)
        except Algo.DoesNotExist:
            return Response({"detail": "Algo not found."}, status=status.HTTP_404_NOT_FOUND)

        if group_pk in ("none", "null", "0", "", None):
            group = None
            fas = FileAssociation.objects.filter(algo=algo, group__isnull=True)
        else:
            try:
                group = Group.objects.get(pk=group_pk)
            except Group.DoesNotExist:
                return Response({"detail": "Group not found."}, status=status.HTTP_404_NOT_FOUND)
            fas = FileAssociation.objects.filter(algo=algo, group=group)

        interval_qs = Interval.objects.filter(id__in=fas.values_list('interval_id', flat=True).distinct())
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

        algo = get_object_or_404(Algo, pk=algo_id)
        interval = get_object_or_404(Interval, pk=interval_id)

        if group_id in (None, "", "null", "none"):
            fa = FileAssociation.objects.filter(
                algo=algo,
                interval=interval,
                group__isnull=True
            ).first()
        else:
            group = get_object_or_404(Group, pk=group_id)
            fa = FileAssociation.objects.filter(
                algo=algo,
                interval=interval,
                group=group
            ).first()

        if not fa:
            return Response(
                {"detail": "No file association for the provided combination."},
                status=status.HTTP_404_NOT_FOUND
            )

        main_data = MainData.objects.filter(file_association=fa).first()
        if not main_data:
            return Response(
                {"detail": "No data found for this FileAssociation."},
                status=status.HTTP_404_NOT_FOUND
            )

        headers = main_data.data_json.get("headers", [])
        rows = main_data.data_json.get("rows", [])

        cleaned_rows = []
        for row in rows:
            safe_row = {}

            for h in headers:
                if not h.startswith("_"):
                    safe_row[h] = row.get(h)

            safe_row["_row_hash"] = row.get("_row_hash")

            cleaned_rows.append(safe_row)

        return Response(
            {
                "file_association_id": fa.id,
                "data_version": fa.data_version,
                "headers": headers,
                "rows": cleaned_rows
            },
            status=200
        )



def sse_user_alerts(request, external_user_id):
    def event_stream():
        try:
            user = MENTUser.objects.get(external_user_id=external_user_id)
        except MENTUser.DoesNotExist:
            yield f"data: {json.dumps({'error': 'User not found'})}\n\n"
            return

        def get_alert_snapshot():
            alerts = CustomAlert.objects.filter(user=user).order_by("id")
            return [
                (a.id, a.last_value, a.is_active)
                for a in alerts
            ]

        last_snapshot = get_alert_snapshot()

        while True:
            current_snapshot = get_alert_snapshot()

            if current_snapshot != last_snapshot:
                last_snapshot = current_snapshot

                payload = [
                    {
                        "alert_id": a.id,
                        "last_value": a.last_value,
                        "is_active": a.is_active,
                    }
                    for a in CustomAlert.objects.filter(user=user)
                ]

                yield f"data: {json.dumps(payload)}\n\n"

            time.sleep(0.1)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    return response



# def sse_file_updates(request, pk):
#     def event_stream():
#         try:
#             fa = FileAssociation.objects.get(id=pk)
#             last_version = fa.data_version
#         except FileAssociation.DoesNotExist:
#             yield f"data: {json.dumps({'error': 'File not found'})}\n\n"
#             return

#         while True:
#             try:
#                 fa.refresh_from_db()
#                 if fa.data_version != last_version:
#                     last_version = fa.data_version

#                     main_data = MainData.objects.filter(file_association=fa).first()
#                     if not main_data:
#                         yield f"data: {json.dumps({'error': 'No data found'})}\n\n"
#                         time.sleep(1)
#                         continue

#                     headers = main_data.data_json.get("headers", [])
#                     rows = main_data.data_json.get("rows", [])
#                     cleaned_rows = [{h: row[h] for h in headers if not h.startswith("_")} for row in rows]

#                     payload = {
#                         "file_association_id": fa.id,
#                         "data_version": last_version,
#                         "headers": headers,
#                         "rows": cleaned_rows,
#                     }
#                     yield f"data: {json.dumps(payload)}\n\n"
#             finally:
#                 connection.close()

#             time.sleep(1)

#     response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
#     response['Cache-Control'] = 'no-cache'
#     return response


def sse_file_updates(request, pk):
    """SSE endpoint to push updates when data_version changes."""

    def event_stream():
        try:
            fa = FileAssociation.objects.get(id=pk)
            last_version = fa.data_version
        except FileAssociation.DoesNotExist:
            yield f"data: {json.dumps({'error': 'File not found'})}\n\n"
            return

        while True:
            fa.refresh_from_db()
            if fa.data_version != last_version:
                last_version = fa.data_version

                main_data = MainData.objects.filter(file_association=fa).first()
                if not main_data:
                    payload = {"error": "No data found for this FileAssociation."}
                    yield f"data: {json.dumps(payload)}\n\n"
                    time.sleep(0.1)
                    continue

                headers = main_data.data_json.get("headers", [])
                rows = main_data.data_json.get("rows", [])

                cleaned_rows = [
                    {h: row[h] for h in headers if not h.startswith("_")}
                    for row in rows
                ]

                payload = {
                    "file_association_id": fa.id,
                    "data_version": last_version,
                    "headers": headers,
                    "rows": cleaned_rows[1: ],
                }

                yield f"data: {json.dumps(payload)}\n\n"

            time.sleep(1)

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    return response




