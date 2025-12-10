from django.db import models
import re
from django.core.exceptions import ValidationError
import hashlib

class MENTUser(models.Model):
    external_user_id = models.IntegerField(unique=True)
    role = models.CharField(max_length=10, choices=[('admin', 'Admin'), ('regular','Regular')])
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=30, null=True, blank=True)


class Algo(models.Model):
    algo_name = models.CharField(max_length=255, unique=True)
    supports_targets = models.BooleanField(default=True)
    supports_direction = models.BooleanField(default=True)
    supports_volume_alerts = models.BooleanField(default=False)
    price_field_key = models.CharField(max_length=100, default="last price")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.algo_name

    class Meta:
        db_table = 'algos'



class Group(models.Model):
    group_name = models.CharField(max_length=255, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.group_name

    class Meta:
        db_table = 'groups'



class Interval(models.Model):
    interval_name = models.CharField(max_length=20, unique=True)
    interval_minutes = models.PositiveIntegerField(editable=False)
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
    algo = models.ForeignKey(Algo, on_delete=models.SET_NULL, null=True)
    group = models.ForeignKey(Group, on_delete=models.SET_NULL, null=True, blank=True)
    interval = models.ForeignKey(Interval, on_delete=models.SET_NULL, null=True)
    
    algo_name_copy = models.CharField(max_length=255, blank=True)
    group_name_copy = models.CharField(max_length=255, blank=True, null=True)
    interval_name_copy = models.CharField(max_length=255, blank=True)

    status = models.CharField(
        max_length=50,
        choices=[
            ("active", "Active"),
            ("unknown", "Unknown Algo")
        ],
        default="active"
    )
    headers = models.JSONField(null=True, blank=True)
    file_name = models.CharField(max_length=255, unique=True, editable=False)
    file_path = models.CharField(max_length=1024, blank=True, null=True)
    last_hash = models.CharField(max_length=128, blank=True, null=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'file_associations'
        unique_together = ('algo', 'group', 'interval')

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
    file_association = models.ForeignKey(FileAssociation, on_delete=models.CASCADE, related_name='maindata')
    data_json = models.JSONField(default=dict)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'main_data'


class GlobalAlertRule(models.Model):
    file_association = models.ForeignKey(FileAssociation, on_delete=models.CASCADE, related_name='global_alerts')
    symbol_interval = models.CharField(max_length=50)
    field_name = models.CharField(max_length=255)
    target_1_hit_at = models.DateTimeField(null=True, blank=True)
    target_2_hit_at = models.DateTimeField(null=True, blank=True)
    condition_type = models.CharField(max_length=50, choices=[
        ('change', 'Any Change'),
        ('increase', 'Increased'),
        ('decrease', 'Decreased'),
        ('equals', 'Equals Specific Value'),
        ('threshold_cross', 'Crossed Threshold'),
    ])
    compare_value = models.CharField(max_length=255, null=True, blank=True)
    last_value = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self): 
        return f"Global Alert on {self.file_association.file_name}: {self.symbol_interval} {self.field_name} {self.condition_type}"

    class Meta:
        db_table = 'global_alert_rules'

    def save(self, *args, **kwargs):
        if self.field_name:
            self.field_name = self.field_name.strip().lower()
        super().save(*args, **kwargs)




class CustomAlert(models.Model):
    user = models.ForeignKey(MENTUser, on_delete=models.CASCADE)
    file_association = models.ForeignKey(FileAssociation, on_delete=models.CASCADE, related_name='custom_alerts')
    symbol_interval = models.CharField(max_length=50, null=True, blank=True)
    field_name = models.CharField(max_length=255)
    target_1_hit_at = models.DateTimeField(null=True, blank=True)
    target_2_hit_at = models.DateTimeField(null=True, blank=True)
    field_type = models.CharField(max_length=50, choices=[
        ('numeric', 'Numeric'),
        ('text', 'Text')
    ])
    condition_type = models.CharField(max_length=50, choices=[
        ('change', 'Any Change'),
        ('increase', 'Increased'),
        ('decrease', 'Decreased'),
        ('equals', 'Equals Specific Value'),
        ('threshold_cross', 'Crossed Threshold'),
    ])
    compare_value = models.CharField(max_length=255, null=True, blank=True)
    last_value = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Custom Alert on :{self.file_association.file_name}: {self.symbol_interval} {self.field_name} {self.condition_type}"

    class Meta:
        db_table = 'custom_alerts'

    def save(self, *args, **kwargs):
        if self.field_name:
            self.field_name = self.field_name.strip().lower()
        super().save(*args, **kwargs)


class TriggeredAlert(models.Model):
    file_association = models.ForeignKey(FileAssociation, on_delete=models.CASCADE)
    global_alert = models.ForeignKey(
        GlobalAlertRule,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    custom_alert = models.ForeignKey(
        CustomAlert,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    triggered_at = models.DateTimeField(auto_now_add=True)  
    acknowledged = models.BooleanField(default=False)  
    message = models.TextField()  

    def __str__(self):
        return f"{self.file_association} - {self.message[:50]}"

    class Meta: 
        ordering = ['-triggered_at']


class SymbolState(models.Model):
    file_association = models.ForeignKey(
        "ttscanner.FileAssociation",
        on_delete=models.CASCADE,
        related_name="symbol_states"
    )
    symbol = models.CharField(max_length=100)
    last_row_data = models.JSONField(default=dict)      
    last_price = models.FloatField(null=True, blank=True)
    last_direction = models.CharField(max_length=100, null=True, blank=True)
    target1_hit = models.BooleanField(default=False)
    target2_hit = models.BooleanField(default=False)
    last_zone = models.CharField(max_length=100, null=True, blank=True)
    last_alerts = models.JSONField(default=dict)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("file_association", "symbol")
        db_table = "symbol_states"

    def __str__(self):
        return f"{self.symbol} ({self.file_association.file_name})"




class FavoriteRow(models.Model):
    user = models.ForeignKey(MENTUser, on_delete=models.CASCADE)
    file_association = models.ForeignKey(FileAssociation, on_delete=models.CASCADE)
    row_data = models.JSONField(default=dict)
    row_hash = models.CharField(max_length=64, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'file_association', 'row_hash')

    def save(self, *args, **kwargs):
        if not self.row_hash:
            self.row_hash = hashlib.sha256(str(self.row_data).encode()).hexdigest()
        super().save(*args, **kwargs)


class UserSettings(models.Model):
    DELIVERY_CHOICES = ['dashboard', 'email', 'sms']

    user = models.OneToOneField(MENTUser, on_delete=models.CASCADE, related_name='settings')
    theme = models.CharField(max_length=10, choices=[('light', 'Light'), ('dark', 'Dark')], default='dark')
    alerts_enabled = models.BooleanField(default=True)
    delivery_methods = models.JSONField(default=list, blank=True)
    alert_email = models.EmailField(null=True, blank=True)
    alert_phone = models.CharField(max_length=30, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
