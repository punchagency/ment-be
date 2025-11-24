from django.db import models
import hashlib

class MENTUser(models.Model):
    external_user_id = models.IntegerField(unique=True)
    role = models.CharField(max_length=10, choices=[('admin', 'Admin'), ('regular','Regular')])
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=30, null=True, blank=True)


class Algo(models.Model):
    algo_name = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.algo_name

    class Meta:
        db_table = 'algos'


class Group(models.Model):
    group_name = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.group_name

    class Meta:
        db_table = 'groups'


class Interval(models.Model):
    INTERVAL_CHOICES = [
        ("1min", 1),
        ("2min", 2),
        ("5min", 5),
        ("10min", 10),
        ("15min", 15),
        ("30min", 30),
        ("60min", 60),
        ("daily", 1440),
    ]
    interval_name = models.CharField(
        max_length=10,
        choices=[(v,v) for v,_ in INTERVAL_CHOICES],
        unique=True)
    interval_minutes = models.PositiveIntegerField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        mapping = dict(self.INTERVAL_CHOICES)
        self.interval_minutes = mapping[self.interval_name]
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.interval_name

    class Meta:
        db_table = 'intervals'



class FileAssociation(models.Model):
    algo = models.ForeignKey(Algo, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, null=True, blank=True)
    interval = models.ForeignKey(Interval, on_delete=models.CASCADE)
    headers = models.JSONField(null=True, blank=True)
    file_name = models.CharField(max_length=255, unique=True, editable=False) 
    file_path = models.CharField(max_length=1024, blank=True, null=True)  
    last_hash = models.CharField(max_length=128, blank=True, null=True)   
    last_fetched_at = models.DateTimeField(null=True, blank=True)  
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('algo', 'group', 'interval')
        db_table = 'file_associations'

    def save(self, *args, **kwargs):
        algo_part = self.algo.algo_name.replace(' ', '')
        group_part = self.group.group_name.replace(' ', '')
        interval_part = self.interval.interval_name.replace(' ', '')
        self.file_name = f"{algo_part}{group_part}{interval_part}.csv"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.file_name


class MainData(models.Model):
    file_association = models.ForeignKey(FileAssociation, on_delete=models.CASCADE, related_name='maindata')
    data_json = models.JSONField(default=dict)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'main_data'


class GlobalAlertRule(models.Model):
    file_association = models.ForeignKey(FileAssociation, on_delete=models.CASCADE, related_name='global_alerts')
    field_name = models.CharField(max_length=255)
    field_type = models.CharField(max_length=50, choices=[('numeric','Numeric'),('text','Text')])
    condition_type = models.CharField(max_length=50, choices=[
        ('change','Any Change'),
        ('increase','Increased'),
        ('decrease','Decreased'),
        ('equals','Equals Specific Value'),
        ('threshold_cross','Crossed Threshold'),
    ])
    compare_value = models.CharField(max_length=255, null=True, blank=True)
    last_value = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Global Alert on {self.file_association.file_name}: {self.field_name} {self.condition_type}"


    class Meta:
        db_table = 'global_alert_rules'


class CustomAlert(models.Model):
    user = models.ForeignKey(MENTUser, on_delete=models.CASCADE)
    file_association = models.ForeignKey(FileAssociation, on_delete=models.CASCADE, related_name='custom_alerts')
    field_name = models.CharField(max_length=255)
    field_type = models.CharField(max_length=50, choices=[('numeric','Numeric'),('text','Text')], default='numeric')
    condition_type = models.CharField(max_length=50, choices=[
        ('change','Any Change'),
        ('increase','Increased'),
        ('decrease','Decreased'),
        ('equals','Equals Specific Value'),
        ('threshold_cross','Crossed Threshold'),
    ])
    compare_value = models.CharField(max_length=255, null=True, blank=True)
    last_value = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - {self.file_association}: {self.field_name} {self.condition_type}"

    class Meta:
        db_table = 'custom_alerts'


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

    class Meta: 
        ordering = ['-triggered_at']


class FavoriteRow(models.Model):
    user = models.ForeignKey(MENTUser, on_delete=models.CASCADE)
    file_association = models.ForeignKey(FileAssociation, on_delete=models.CASCADE)
    row_data = models.JSONField(default=dict)
    row_hash = models.CharField(max_length=64, editable=False, default='temp_hash')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'file_association')

    def save(self, *args, **kwargs):
        self.row_data = hashlib.sha256(str(self.row_data).encode()).hexdigest()
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
