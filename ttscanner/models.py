from django.db import models
import re, json, uuid, hashlib
from django.db import transaction
from django.core.exceptions import ValidationError
from django.contrib.auth.hashers import make_password, check_password

class MENTUser(models.Model):
    external_user_id = models.IntegerField(unique=True, db_index=True)  # ⚡ INDEX
    username = models.CharField(max_length=50, unique=True, null=True, blank=True, db_index=True)  # ⚡ INDEX
    password = models.CharField(max_length=128, null=True, blank=True)
    role = models.CharField(
        max_length=10,
        choices=[('admin', 'Admin'), ('regular', 'Regular')],
        db_index=True  # ⚡ INDEX
    )
    email = models.EmailField(null=True, blank=True, db_index=True)  # ⚡ INDEX
    phone = models.CharField(max_length=30, null=True, blank=True)

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)
    
    class Meta:
        db_table = 'ttscanner_mentuser'


class Algo(models.Model):
    algo_name = models.CharField(max_length=255, unique=True, db_index=True)  # ⚡ INDEX
    supports_targets = models.BooleanField(default=True, db_index=True)  # ⚡ INDEX
    supports_direction = models.BooleanField(default=True)
    supports_volume_alerts = models.BooleanField(default=False)
    price_field_key = models.CharField(max_length=100, default="last price")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)  # ⚡ INDEX

    def __str__(self):
        return self.algo_name

    class Meta:
        db_table = 'algos'
        indexes = [
            models.Index(fields=['-created_at']),  # For latest first
        ]


class Group(models.Model):
    group_name = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True)  # ⚡ INDEX
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)  # ⚡ INDEX
    
    def __str__(self):
        return self.group_name
    
    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

    class Meta:
        db_table = 'groups'
        indexes = [
            models.Index(fields=['-created_at']),
        ]


class Interval(models.Model):
    interval_name = models.CharField(max_length=20, unique=True, db_index=True)  # ⚡ INDEX
    interval_minutes = models.PositiveIntegerField(editable=False, db_index=True)  # ⚡ INDEX
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        name = self.interval_name.strip().lower()

        if name == "daily":
            self.interval_minutes = 1440
        else:
            match = re.match(r"(\d+)(min|h)$", name)
            value, unit = match.groups()
            value = int(value)
            if unit == "min":
                self.interval_minutes = value
            elif unit == "h":
                self.interval_minutes = value * 60

        super().save(*args, **kwargs)

    def __str__(self):
        return self.interval_name

    class Meta:
        db_table = 'intervals'


class FileAssociation(models.Model):
    algo = models.ForeignKey(Algo, on_delete=models.SET_NULL, null=True, db_index=True)  # ⚡ INDEX
    group = models.ForeignKey(Group, on_delete=models.SET_NULL, null=True, blank=True, db_index=True)  # ⚡ INDEX
    interval = models.ForeignKey(Interval, on_delete=models.SET_NULL, null=True, db_index=True)  # ⚡ INDEX
    
    algo_name_copy = models.CharField(max_length=255, blank=True, db_index=True)  # ⚡ INDEX
    group_name_copy = models.CharField(max_length=255, blank=True, null=True, db_index=True)  # ⚡ INDEX
    interval_name_copy = models.CharField(max_length=255, blank=True, db_index=True)  # ⚡ INDEX

    status = models.CharField(
        max_length=50,
        choices=[
            ("active", "Active"),
            ("unknown", "Unknown Algo")
        ],
        default="active",
        db_index=True  # ⚡ INDEX
    )
    headers = models.JSONField(null=True, blank=True)
    file_name = models.CharField(max_length=255, unique=True, editable=False, db_index=True)  # ⚡ INDEX
    file_path = models.CharField(max_length=1024, blank=True, null=True)
    last_hash = models.CharField(max_length=128, blank=True, null=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True, db_index=True)  # ⚡ INDEX
    data_version = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)  # ⚡ INDEX

    class Meta:
        db_table = 'file_associations'
        unique_together = ('algo', 'group', 'interval')
        indexes = [
            models.Index(fields=['-created_at']),  # For latest first
            models.Index(fields=['status', 'created_at']),  # Filter by status + date
            models.Index(fields=['algo', 'interval']),  # Common filter combination
            models.Index(fields=['file_name', 'status']),  # Search by file name
        ]

    def save(self, *args, **kwargs):
        if self.algo:
            self.algo_name_copy = self.algo.algo_name

        if self.group:
            self.group_name_copy = self.group.group_name
        else:
            self.group_name_copy = None 

        if self.interval:
            self.interval_name_copy = self.interval.interval_name

        algo_part = self.algo_name_copy.replace(" ", "")
        interval_part = self.interval_name_copy.replace(" ", "")

        if self.group_name_copy is None:
            self.file_name = f"{algo_part}{interval_part}.csv"
        else:
            group_part = self.group_name_copy.replace(" ", "")
            self.file_name = f"{algo_part}{group_part}{interval_part}.csv"

        super().save(*args, **kwargs)


class MainData(models.Model):
    file_association = models.ForeignKey(FileAssociation, on_delete=models.CASCADE, related_name='maindata', db_index=True)  # ⚡ INDEX
    data_json = models.JSONField(default=dict)
    last_updated = models.DateTimeField(auto_now=True, db_index=True)  # ⚡ INDEX

    def save(self, *args, **kwargs):
        if self.data_json.get("rows"):
            for row in self.data_json["rows"]:
                if "_row_id" not in row:
                    row["_row_id"] = str(uuid.uuid4())
                row["_row_hash"] = self.compute_row_hash(row)

        super().save(*args, **kwargs)

        with transaction.atomic():
            for row in self.data_json.get("rows", []):
                if "_row_id" in row and "_row_hash" in row:
                    FavoriteRow.objects.filter(
                        file_association=self.file_association,
                        row_id=row["_row_id"]
                    ).update(row_hash=row["_row_hash"])

    @staticmethod
    def compute_row_hash(row: dict) -> str:
        normalized_row = {str(k).strip(): v for k, v in row.items() if k != "_row_hash"}
        json_str = json.dumps(normalized_row, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()
    
    class Meta:
        db_table = 'main_data'
        indexes = [
            models.Index(fields=['file_association', '-last_updated']),  # Latest data per file
        ]


class FavoriteRow(models.Model):
    user = models.ForeignKey(MENTUser, on_delete=models.CASCADE, related_name='user', db_index=True)  # ⚡ INDEX
    file_association = models.ForeignKey(FileAssociation, on_delete=models.CASCADE, db_index=True)  # ⚡ INDEX
    row_id = models.CharField(max_length=36, null=True, blank=True, db_index=True)  # ⚡ INDEX
    row_hash = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)  # ⚡ INDEX

    class Meta:
        db_table = 'ttscanner_favoriterow'
        unique_together = ('user', 'row_id', 'file_association')
        indexes = [
            models.Index(fields=['user', '-created_at']),  # User's latest favorites
            models.Index(fields=['file_association', 'user']),  # Find user's favs in file
        ]


class GlobalAlertRule(models.Model):
    file_association = models.ForeignKey(FileAssociation, on_delete=models.CASCADE, related_name='global_alerts', db_index=True)  # ⚡ INDEX
    symbol_interval = models.CharField(max_length=50, db_index=True)  # ⚡ INDEX
    field_name = models.CharField(max_length=255, db_index=True)  # ⚡ INDEX
    target_1_hit_at = models.DateTimeField(null=True, blank=True)
    target_2_hit_at = models.DateTimeField(null=True, blank=True)
    condition_type = models.CharField(max_length=50, choices=[
        ('change', 'Any Change'),
        ('increase', 'Increased'),
        ('decrease', 'Decreased'),
        ('equals', 'Equals Specific Value'),
        ('threshold_cross', 'Crossed Threshold'),
    ], db_index=True)  # ⚡ INDEX
    compare_value = models.CharField(max_length=255, null=True, blank=True)
    last_value = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)  # ⚡ INDEX
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)  # ⚡ INDEX

    def __str__(self): 
        return f"Global Alert on {self.file_association.file_name}: {self.symbol_interval} {self.field_name} {self.condition_type}"

    class Meta:
        db_table = 'global_alert_rules'
        indexes = [
            models.Index(fields=['file_association', 'is_active', '-created_at']),  # Active alerts per file
            models.Index(fields=['symbol_interval', 'field_name']),  # Common filter
            models.Index(fields=['is_active', '-created_at']),  # All active alerts
        ]

    def save(self, *args, **kwargs):
        if self.field_name:
            self.field_name = self.field_name.strip().lower()
        super().save(*args, **kwargs)


class CustomAlert(models.Model):
    user = models.ForeignKey(MENTUser, on_delete=models.CASCADE, db_index=True)  # ⚡ INDEX
    file_association = models.ForeignKey(FileAssociation, on_delete=models.CASCADE, related_name='custom_alerts', db_index=True)  # ⚡ INDEX
    symbol_interval = models.CharField(max_length=50, null=True, blank=True, db_index=True)  # ⚡ INDEX
    field_name = models.CharField(max_length=255, db_index=True)  # ⚡ INDEX
    target_1_hit_at = models.DateTimeField(null=True, blank=True)
    target_2_hit_at = models.DateTimeField(null=True, blank=True)
    condition_type = models.CharField(max_length=50, choices=[
        ('change', 'Any Change'),
        ('increase', 'Increased'),
        ('decrease', 'Decreased'),
        ('equals', 'Equals Specific Value'),
        ('threshold_cross', 'Crossed Threshold'),
    ], db_index=True)  # ⚡ INDEX
    compare_value = models.CharField(max_length=255, null=True, blank=True)
    last_value = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)  # ⚡ INDEX
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)  # ⚡ INDEX

    def __str__(self):
        return f"Custom Alert on :{self.file_association.file_name}: {self.symbol_interval} {self.field_name} {self.condition_type}"

    class Meta:
        db_table = 'custom_alerts'
        indexes = [
            models.Index(fields=['user', 'is_active', '-created_at']),  # User's active alerts
            models.Index(fields=['file_association', 'user', 'is_active']),  # User alerts per file
            models.Index(fields=['symbol_interval', 'field_name', 'user']),  # Common filter
        ]

    def save(self, *args, **kwargs):
        if self.field_name:
            self.field_name = self.field_name.strip().lower()
        super().save(*args, **kwargs)


class TriggeredAlert(models.Model):
    ALERT_SOURCE_CHOICES = [
        ("system", "System"),
        ("global", "Global"),
        ("custom", "Custom"),
    ]

    file_association = models.ForeignKey(FileAssociation, on_delete=models.CASCADE, db_index=True)  # ⚡ INDEX
    symbol = models.CharField(max_length=100, blank=True, null=True, db_index=True)  # ⚡ INDEX

    alert_source = models.CharField(
        max_length=10,
        choices=ALERT_SOURCE_CHOICES,
        db_index=True  # ⚡ INDEX
    )

    global_alert = models.ForeignKey(
        GlobalAlertRule,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        db_index=True  # ⚡ INDEX
    )
    custom_alert = models.ForeignKey(
        CustomAlert,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        db_index=True  # ⚡ INDEX
    )

    triggered_at = models.DateTimeField(auto_now_add=True, db_index=True)  # ⚡ INDEX
    acknowledged = models.BooleanField(default=False, db_index=True)  # ⚡ INDEX
    message = models.TextField()

    class Meta:
        db_table = 'ttscanner_triggeredalert'
        ordering = ["-triggered_at"]
        indexes = [
            models.Index(fields=['-triggered_at', 'acknowledged']),  # Latest unacknowledged
            models.Index(fields=['file_association', '-triggered_at']),  # Alerts per file
            models.Index(fields=['acknowledged', 'triggered_at']),  # Unacknowledged alerts
        ]


class SymbolState(models.Model):
    file_association = models.ForeignKey(
        "ttscanner.FileAssociation",
        on_delete=models.CASCADE,
        related_name="symbol_states",
        db_index=True  # ⚡ INDEX
    )
    symbol = models.CharField(max_length=100, db_index=True)  # ⚡ INDEX
    last_row_data = models.JSONField(default=dict)
    last_price = models.FloatField(null=True, blank=True, db_index=True)  # ⚡ INDEX
    last_direction = models.CharField(max_length=100, null=True, blank=True, db_index=True)  # ⚡ INDEX
    target1_hit = models.BooleanField(default=False, db_index=True)  # ⚡ INDEX
    target2_hit = models.BooleanField(default=False, db_index=True)  # ⚡ INDEX
    last_zone = models.CharField(max_length=100, null=True, blank=True)
    last_alerts = models.JSONField(default=dict)

    updated_at = models.DateTimeField(auto_now=True, db_index=True)  # ⚡ INDEX

    class Meta:
        unique_together = ("file_association", "symbol")
        db_table = "symbol_states"
        indexes = [
            models.Index(fields=['file_association', '-updated_at']),  # Latest states per file
            models.Index(fields=['symbol', 'file_association']),  # Find symbol across files
            models.Index(fields=['last_price']),  # For price-based queries
        ]

    def __str__(self):
        return f"{self.symbol} ({self.file_association.file_name})"


class UserSettings(models.Model):
    DELIVERY_CHOICES = ['dashboard', 'email', 'sms']

    user = models.OneToOneField(MENTUser, on_delete=models.CASCADE, related_name='settings', db_index=True)  # ⚡ INDEX
    theme = models.CharField(max_length=10, choices=[('light', 'Light'), ('dark', 'Dark')], default='dark')
    alerts_enabled = models.BooleanField(default=True, db_index=True)  # ⚡ INDEX
    delivery_methods = models.JSONField(default=list, blank=True)
    alert_email = models.EmailField(null=True, blank=True, db_index=True)  # ⚡ INDEX
    alert_phone = models.CharField(max_length=30, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)  # ⚡ INDEX

    class Meta:
        db_table = 'ttscanner_usersettings'


class Announcement(models.Model):
    message = models.TextField()
    type = models.CharField(max_length=20, choices=[
        ("Email", "Email"),
        ("SMS", "SMS"),
        ("Email & SMS", "Email & SMS")
    ], db_index=True)  # ⚡ INDEX
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)  # ⚡ INDEX

    def __str__(self):
        return f"{self.type} Announcement at {self.created_at.strftime('%Y-%m-%d %H:%M')}"
    
    class Meta:
        db_table = 'ttscanner_announcement'
        indexes = [
            models.Index(fields=['-created_at']), 
        ]