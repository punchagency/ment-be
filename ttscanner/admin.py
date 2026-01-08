from django.contrib import admin
from .models import (
    MENTUser,
    Algo,
    Group,
    Interval,
    FileAssociation,
    MainData,
    GlobalAlertRule,
    CustomAlert,
    TriggeredAlert,
    FavoriteRow,
    UserSettings,
    SymbolState,
    Announcement
)

@admin.register(MENTUser)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('external_user_id', 'role', 'email', 'phone')
    search_fields = ('external_user_id', 'email', 'phone')  


@admin.register(Algo)
class AlgoAdmin(admin.ModelAdmin):
    list_display = ('algo_name', 'created_at')
    search_fields = ('algo_name',)

@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('group_name', 'created_at')
    search_fields = ('group_name',)

@admin.register(Interval)
class IntervalAdmin(admin.ModelAdmin):
    list_display = ('interval_name', 'interval_minutes', 'created_at')
    search_fields = ('interval_name',)

@admin.register(FileAssociation)
class FileAssociationAdmin(admin.ModelAdmin):
    list_display = ('file_name', 'algo', 'group', 'interval', 'file_path', 'created_at')
    search_fields = ('file_name',)
    list_filter = ('algo', 'group', 'interval')

@admin.register(MainData)
class MainDataAdmin(admin.ModelAdmin):
    list_display = ('file_association', 'last_updated', 'data_json')
    search_fields = ('file_association__file_name',)

@admin.register(FavoriteRow)
class FavoriteRowAdmin(admin.ModelAdmin):
    list_display = ('user', 'file_association', 'row_hash')
    search_fields = ('user__external_user_id', 'file_association__file_name')

@admin.register(GlobalAlertRule)
class GlobalAlertRuleAdmin(admin.ModelAdmin):
    list_display = ('field_name', 'symbol_interval', 'condition_type' ,'is_active', 'created_at')
    search_fields = ('field_name',)
    list_filter = ('is_active', 'condition_type', 'symbol_interval')

@admin.register(CustomAlert)
class CustomAlertAdmin(admin.ModelAdmin):
    list_display = ('user', 'file_association', 'field_name', 'condition_type', 'is_active', 'created_at')
    search_fields = ('user__external_user_id', 'field_name', 'file_association__file_name')  # CHANGED
    list_filter = ('is_active', 'condition_type')

@admin.register(TriggeredAlert)
class TriggeredAlertAdmin(admin.ModelAdmin):
    list_display = ('file_association', 'global_alert', 'custom_alert', 'triggered_at')
    search_fields = ('file_association', 'global_alert', 'custom_alert')

@admin.register(UserSettings)
class UserSettingsAdmin(admin.ModelAdmin):
    list_display = ('user', 'theme', 'alerts_enabled', 'delivery_methods', 'alert_email', 'alert_phone')
    search_fields = ('user__email', 'user__phone','user__external_user_id')

@admin.register(SymbolState)
class SymbolStateAdmin(admin.ModelAdmin):
    list_display = ('file_association', 'symbol', 'last_row_data', 'last_price', 'last_direction', 'target1_hit' , 'target2_hit', 'last_zone',
                    'last_alerts', 'updated_at')
    
@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('message', 'type', 'created_at')