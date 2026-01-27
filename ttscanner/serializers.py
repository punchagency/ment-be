import re
from django.db import IntegrityError
from rest_framework import serializers
from .models import (
    Algo, Group, Interval, 
    FileAssociation, GlobalAlertRule, 
    FavoriteRow, CustomAlert,
    UserSettings, MENTUser,
    TriggeredAlert
)

class AlgoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Algo
        fields = ['id', 'algo_name']
        

class GroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ['id', 'group_name']


class IntervalSerializer(serializers.ModelSerializer):
    interval_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Interval
        fields = ['id', 'interval_name', 'interval_minutes']
        read_only_fields = ['interval_minutes']

    def validate_interval_name(self, value):
        value = value.strip().lower()

        if value == "daily":
            return value

        match = re.match(r"^(\d+)(min|h)$", value)
        if not match:
            raise serializers.ValidationError(
                "Invalid format. Use Positive number + unit (e.g., 5min, 1h) or 'daily'."
            )

        number, unit = match.groups()
        number = int(number)
        if number <= 0:
            raise serializers.ValidationError("Number must be positive.")

        return value

    def create(self, validated_data):
        interval_name = validated_data['interval_name'].lower()
        if interval_name == "daily":
            interval_minutes = 1440
        else:
            match = re.match(r"^(\d+)(min|h)$", interval_name)
            number, unit = match.groups()
            number = int(number)
            interval_minutes = number * 60 if unit == 'h' else number

        interval = Interval.objects.create(
            interval_name=interval_name,
            interval_minutes=interval_minutes
        )
        return interval

    def update(self, instance, validated_data):
        interval_name = validated_data.get('interval_name', instance.interval_name).lower()
        if interval_name == "daily":
            interval_minutes = 1440
        else:
            match = re.match(r"^(\d+)(min|h)$", interval_name)
            number, unit = match.groups()
            number = int(number)
            interval_minutes = number * 60 if unit == 'h' else number

        instance.interval_name = interval_name
        instance.interval_minutes = interval_minutes
        instance.save()
        return instance



class FileAssociationCreateSerializer(serializers.Serializer):
    algo_name = serializers.CharField(max_length=255)
    group_name = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    interval_name = serializers.CharField(max_length=255)

    def validate(self, data):
        algo_name = data['algo_name'].strip()
        group_name = data.get('group_name', '').strip()
        interval_name = data['interval_name'].strip()

        algo, _ = Algo.objects.get_or_create(algo_name=algo_name)

        group = None
        if group_name:
            group, _ = Group.objects.get_or_create(group_name=group_name)

        interval, _ = Interval.objects.get_or_create(interval_name=interval_name)

        data['algo'] = algo
        data['group'] = group
        data['interval'] = interval

        return data

    def create(self, validated_data):
        try:
            return FileAssociation.objects.create(
                algo=validated_data['algo'],
                group=validated_data['group'],
                interval=validated_data['interval']
            )
        except IntegrityError:
            algo_name = validated_data['algo'].algo_name
            group_obj = validated_data['group']
            interval_name = validated_data['interval'].interval_name
            group_display = group_obj.group_name if group_obj else "No Group"

            raise serializers.ValidationError({
                "non_field_errors": [
                    f"File association already exists for {algo_name}, {group_display}, {interval_name}"
                ]
            })



class CSVUploadSerializer(serializers.Serializer):
    # file = serializers.FileField(required=False, allow_null=True)
    ftp_path = serializers.CharField(required=False)

    def validate(self, data):
        if not data.get('file') and not data.get('ftp_path'):
            raise serializers.ValidationError("Provide either 'file' or 'url'.")
        return data
    
 

class FileAssociationUpdateSerializer(serializers.ModelSerializer):
    algo_name = serializers.CharField(write_only=True, required=False)
    group_name = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True)
    interval_name = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = FileAssociation
        fields = [
            "algo", "group", "interval", "file_name", "file_path",
            "algo_name", "group_name", "interval_name"
        ]
        read_only_fields = ["file_name", "last_hash", "created_at"]

    def validate(self, data):
        instance = getattr(self, 'instance', None)
        if 'algo_name' in data:
            algo_name = data.pop('algo_name')
            try:
                algo_obj = Algo.objects.get(algo_name=algo_name)
                data['algo'] = algo_obj
                data['algo_name_copy'] = algo_obj.algo_name 
            except Algo.DoesNotExist:
                raise serializers.ValidationError({"algo_name": "Algo with this name does not exist."})
            
        if 'group_name' in data:
            group_name = data.pop('group_name')
            cleaned_name = group_name.strip(" -") if group_name else ""

            if not cleaned_name or cleaned_name.lower() == "no group":
                data['group'] = None
                data['group_name_copy'] = None
            else:
                try:
                    group_obj = Group.objects.get(group_name=group_name) 
                    data['group'] = group_obj
                    data['group_name_copy'] = group_obj.group_name  
                except Group.DoesNotExist:
                    raise serializers.ValidationError({"group_name": "Group with this name does not exist."})


        if 'interval_name' in data:
            interval_name = data.pop('interval_name')
            try:
                interval_obj = Interval.objects.get(interval_name=interval_name)
                data['interval'] = interval_obj
                data['interval_name_copy'] = interval_obj.interval_name  
            except Interval.DoesNotExist:
                raise serializers.ValidationError({"interval_name": "Interval does not exist."})
        algo = data.get('algo', instance.algo if instance else None)
        group = data.get('group', instance.group if instance else None)
        interval = data.get('interval', instance.interval if instance else None)

        if FileAssociation.objects.filter(algo=algo, group=group, interval=interval).exclude(pk=instance.pk).exists():
            raise serializers.ValidationError(
                "A file association with this Algo, Group, and Interval already exists."
            )

        return data


class FileAssociationListSerializer(serializers.ModelSerializer):
    algo_name = serializers.SerializerMethodField()
    group_name = serializers.SerializerMethodField()
    interval_name = serializers.SerializerMethodField()

    class Meta:
        model = FileAssociation
        fields = [
            'id',
            'algo_name',
            'group_name',
            'interval_name',
            'file_name',
            'file_path'
        ]

    def get_algo_name(self, obj):
        return obj.algo.algo_name if obj.algo else obj.algo_name_copy

    def get_group_name(self, obj):
        return obj.group.group_name if obj.group else (obj.group_name_copy or "-- No Group --")

    def get_interval_name(self, obj):
        return obj.interval.interval_name if obj.interval else obj.interval_name_copy



class GlobalAlertCreateSerializer(serializers.ModelSerializer):
    compare_value = serializers.CharField(
        allow_blank=True,  
        required=False,    
        allow_null=True   
    )
    class Meta:
        model = GlobalAlertRule
        fields = ['file_association', 'symbol_interval', 'field_name', 
                  'condition_type', 'compare_value', 'last_value', 'is_active']
        read_only_fields = ["file_association", "created_at"]

    def validate(self, data):
        fa = self.context.get("file_association")
        if not fa:
            raise serializers.ValidationError("File Association does not exist.")

        headers = fa.headers or []

        field_name = data.get("field_name")
        symbol_interval = data.get("symbol_interval")
        compare_value = data.get("compare_value")
        condition_type = data.get("condition_type")

        if field_name.lower() not in (h.lower() for h in headers):
            raise serializers.ValidationError(
                f"'{field_name}' is not a valid column. Available: {headers}"
            )
        
        if condition_type == "change":
            data['compare_value'] = None
            compare_value = None

        all_rows = fa.maindata.first().data_json.get("rows", [])

        field_entries = [
            row.get(field_name)
            for row in all_rows
            if row.get(field_name) not in (None, "")
        ]

        def is_numeric(v):
            try:
                float(v)
                return True
            except:
                return False

        is_numeric_field = len(field_entries) > 0 and any(is_numeric(v) for v in field_entries)

        if compare_value not in (None, ""):
            if is_numeric_field and not is_numeric(compare_value):
                raise serializers.ValidationError(
                    { "compare_value": f"'{field_name}' is numeric — compare value must be a number." }
                )
            if not is_numeric_field and is_numeric(compare_value):
                raise serializers.ValidationError(
                    { "compare_value": f"'{field_name}' is text — compare value cannot be numeric." }
                )

        existing_alerts = fa.global_alerts.all()

        if any(
            a.field_name.lower() == field_name.lower() and
            (a.symbol_interval or "").lower() == (symbol_interval or "").lower()
            for a in existing_alerts
        ):
            raise serializers.ValidationError(
                f"Alert for '{symbol_interval}' → '{field_name}' already exists."
            )

        return data

    def create(self, validated_data):
        fa = self.context.get("file_association")
        return GlobalAlertRule.objects.create(file_association=fa, **validated_data)




class GlobalAlertUpdateSerializer(serializers.ModelSerializer):
    compare_value = serializers.CharField(
        allow_blank=True,  
        required=False,    
        allow_null=True   
    )
    class Meta:
        model = GlobalAlertRule
        fields = ['file_association', 'symbol_interval', 'field_name', 
                'condition_type', 'compare_value', 'last_value', 'is_active']
        read_only_fields = ["created_at"]  

    def validate(self, data):
        fa = data.get("file_association")
        if not fa:
            raise serializers.ValidationError("File Association must be provided.")

        headers = fa.headers or []
        field_name = data.get("field_name")
        symbol_interval = data.get("symbol_interval")
        compare_value = data.get("compare_value")
        condition_type = data.get("condition_type")

        if field_name.lower() not in (h.lower() for h in headers):
            raise serializers.ValidationError(
                f"'{field_name}' is not a valid column. Available columns: {headers}"
            )
        
        if condition_type == "change":
            data['compare_value'] = None
            compare_value = None

        all_rows = fa.maindata.first().data_json.get("rows", [])

        field_entries = [
            row.get(field_name, "") for row in all_rows if field_name in row
        ]

        def is_numeric(v):
            try:
                float(v)
                return True
            except:
                return False

        is_numeric_field = len(field_entries) > 0 and any(is_numeric(v) for v in field_entries)
        if compare_value not in (None, ""):

            if is_numeric_field and not is_numeric(compare_value):
                raise serializers.ValidationError({
                    "compare_value": f"'{field_name}' is numeric — compare value must be a number."
                })

            if not is_numeric_field and is_numeric(compare_value):
                raise serializers.ValidationError({
                    "compare_value": f"'{field_name}' is text — compare value cannot be numeric."
                })

        existing_alerts = fa.global_alerts.all()

        if any(
            a.field_name.lower() == field_name.lower()
            and (a.symbol_interval or "").lower() == (symbol_interval or "").lower()
            for a in existing_alerts
        ):
            raise serializers.ValidationError(
                f"Alert for '{symbol_interval}' → '{field_name}' already exists."
            )

        return data




class GlobalAlertListSerializer(serializers.ModelSerializer):
    file_name = serializers.CharField(source='file_association.file_name', read_only=True)
    algo_name = serializers.CharField(source='file_association.algo.algo_name', read_only=True)
    group_name = serializers.CharField(source='file_association.group.group_name', read_only=True)
    interval_name = serializers.CharField(source='file_association.interval.interval_name', read_only=True)

    class Meta:
        model = GlobalAlertRule
        fields = [
            "id",
            "file_name",
            "algo_name",
            "group_name",
            "interval_name",
            "symbol_interval",
            "field_name",
            "condition_type",
            "compare_value",
            "last_value",
            "is_active"
        ]



class FavoriteRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = FavoriteRow
        fields = ['row_data', 'row_hash']


class TriggeredAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = TriggeredAlert
        fields = '__all__'



class CustomAlertCreateSerializer(serializers.ModelSerializer):
    compare_value = serializers.CharField(
        allow_blank=True,
        required=False,
        allow_null=True
    )
    user = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = CustomAlert
        fields = '__all__'
        read_only_fields = ["created_at"]

    def validate(self, data):
        fa = data.get("file_association")
        if not fa:
            raise serializers.ValidationError("File Association must be provided.")

        field_name = data.get("field_name")
        symbol_interval = data.get("symbol_interval")
        compare_value = data.get("compare_value")
        condition_type = data.get("condition_type")

        # Check duplicates
        if CustomAlert.objects.filter(
            file_association=fa,
            field_name__iexact=field_name,
            symbol_interval__iexact=symbol_interval
        ).exists():
            raise serializers.ValidationError(
                f"Alert for '{symbol_interval}' → '{field_name}' already exists."
            )

        if condition_type == "change":
            data['compare_value'] = None
            compare_value = None

        all_rows = fa.maindata.first().data_json.get("rows", [])
        field_entries = [row.get(field_name) for row in all_rows if row.get(field_name) not in (None, "")]

        def is_numeric(v):
            try:
                float(v)
                return True
            except:
                return False

        is_numeric_field = len(field_entries) > 0 and any(is_numeric(v) for v in field_entries)

        if compare_value not in (None, ""):
            if is_numeric_field and not is_numeric(compare_value):
                raise serializers.ValidationError({
                    "compare_value": f"'{field_name}' is numeric — compare value must be a number."
                })
            # if not is_numeric_field and is_numeric(compare_value):
            #     raise serializers.ValidationError({
            #         "compare_value": f"'{field_name}' is text — compare value cannot be numeric."
            #     })

        return data

    def create(self, validated_data):
        return CustomAlert.objects.create(**validated_data)



class CustomAlertUpdateSerializer(serializers.ModelSerializer):
    compare_value = serializers.CharField(
        allow_blank=True,
        required=False,
        allow_null=True
    )
    user = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = CustomAlert
        fields = ['field_name', 'condition_type', 'compare_value', 'symbol_interval', 'user']
    
    def validate(self, data):
        field_name = data.get("field_name")
        symbol_interval = data.get("symbol_interval")
        compare_value = data.get("compare_value")
        condition_type = data.get("condition_type")
        fa = self.instance.file_association

        if condition_type == "change":
            data['compare_value'] = None
            compare_value = None

        all_rows = fa.maindata.first().data_json.get("rows", [])
        field_entries = [row.get(field_name) for row in all_rows if row.get(field_name) not in (None, "")]

        def is_numeric(v):
            try:
                float(v)
                return True
            except:
                return False

        is_numeric_field = len(field_entries) > 0 and any(is_numeric(v) for v in field_entries)

        if compare_value not in (None, ""):
            if is_numeric_field and not is_numeric(compare_value):
                raise serializers.ValidationError({
                    "compare_value": f"'{field_name}' is numeric — compare value must be a number."
                })
            # if not is_numeric_field and is_numeric(compare_value):
            #     raise serializers.ValidationError({
            #         "compare_value": f"'{field_name}' is text — compare value cannot be numeric."
            #     })

        if CustomAlert.objects.filter(
            file_association=fa,
            field_name__iexact=field_name,
            symbol_interval__iexact=symbol_interval
        ).exclude(id=self.instance.id).exists():
            raise serializers.ValidationError(
                f"Alert for '{symbol_interval}' → '{field_name}' already exists."
            )

        return data


class UserSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSettings
        fields = ['theme', 'alerts_enabled', 'delivery_methods', 'alert_email', 'alert_phone']

class UserRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = MENTUser
        fields = ['external_user_id', 'role', 'email']
