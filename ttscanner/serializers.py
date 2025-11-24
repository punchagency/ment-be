from rest_framework import serializers
from .models import (
    Algo, Group, Interval, 
    FileAssociation, GlobalAlertRule, 
    FavoriteRow, CustomAlert,
    UserSettings, MENTUser
)

class FileAssociationCreateSerializer(serializers.Serializer):
    algo_name = serializers.CharField(max_length=255)
    group_name = serializers.CharField(max_length=255,required=False, allow_blank=True)
    interval_name = serializers.CharField(max_length=255)

    def create(self, validated_data):        
        algo_name = validated_data['algo_name'].strip()
        group_name = validated_data.get('group_name', '').strip()
        interval_name = validated_data['interval_name'].strip()

        algo, _ = Algo.objects.get_or_create(algo_name=algo_name)
        group, _ = Group.objects.get_or_create(group_name=group_name)
        interval, _ = Interval.objects.get_or_create(interval_name=interval_name)


        fa, created = FileAssociation.objects.get_or_create(
            algo=algo, group=group, interval=interval
        )
        return fa


class CSVUploadSerializer(serializers.Serializer):
    # file = serializers.FileField(required=False, allow_null=True)
    ftp_path = serializers.CharField(required=False)

    def validate(self, data):
        if not data.get('file') and not data.get('ftp_path'):
            raise serializers.ValidationError("Provide either 'file' or 'url'.")
        return data
    

class FileAssociationUpdateSerializer(serializers.ModelSerializer):
    def update(self, instance, validated_data):
        instance.file_name = validated_data.get("file_name", instance.file_name)
        instance.file_path = validated_data.get("file_path", instance.file_path)
        instance.save()
        return instance
    class Meta:
        model = FileAssociation
        fields = ["algo", "group", "interval", "file_name", "file_path"]
        read_only_fields = ["last_hash", "created_at"]


class GlobalAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = GlobalAlertRule
        fields = '__all__'

    field_name = serializers.CharField()
    def validate(self, data):
        if self.instance: 
            fa = self.instance.file_association
        else:
            pk = self.context["view"].kwargs.get("pk")
            if not pk:
                raise serializers.ValidationError("fa_id is required in URL.")
            fa = FileAssociation.objects.filter(pk=pk).first()
            if not fa:
                raise serializers.ValidationError("File Association does not exist")
            
        headers = fa.headers or []
        global_alerts = fa.global_alerts.all()
        if data['field_name'].lower() not in (h.lower() for h in headers):
            raise serializers.ValidationError(
                f"'{data['field_name']}' is not a valid column. Available: {headers}"
            )
        if data['field_name'].lower() in (g.field_name.lower() for g in global_alerts):
            raise serializers.ValidationError(
                f"{data['field_name']} condition already exists"
            )
        return data


class FavoriteRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = FavoriteRow
        fields = ['row_data', 'row_hash']


class CustomAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomAlert
        fields = ['field_name', 'field_type', 'condition_type', 'compare_value']

    field_name = serializers.CharField()

    def validate(self, data):
        user = getattr(self.context["view"], "ment_user", None)
        if not user:
            raise serializers.ValidationError("User does not exist.")
        fa = getattr(self.context["view"], "file_association", None)
        if not fa:
            raise serializers.ValidationError("File Association missing.")
        headers = fa.headers or []
        if data['field_name'].lower() not in (h.lower() for h in headers):
            raise serializers.ValidationError(
                f"'{data['field_name']}' is not a valid column. Available: {headers}"
            )

        if CustomAlert.objects.filter(file_association=fa, user=user, field_name__iexact=data['field_name']).exists():
            raise serializers.ValidationError(
                f"You already created an alert for '{data['field_name']}'."
            )

        return data




class CustomAlertUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomAlert
        fields = ['field_name', 'field_type', 'condition_type', 'compare_value']

class UserSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSettings
        fields = ['theme', 'alerts_enabled', 'delivery_methods', 'alert_email', 'alert_phone']
