from celery import shared_task
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from django.utils import timezone
from .utils.email_utils import send_alert_email
from .utils.sms_utils import send_alert_sms
from ttscanner.models import (
    FileAssociation, TriggeredAlert, 
    MENTUser, CustomAlert, GlobalAlertRule, 
    UserSettings
)
from ttscanner.utils.csv_utils import fetch_ftp_bytes, is_file_changed, store_csv_data

@shared_task
def import_file_association(file_id):
    try:
        fa = FileAssociation.objects.get(id=file_id)
    except ObjectDoesNotExist:
        print(f"FileAssociation with id={file_id} does not exist. Skipping task.")
        return

    try:
        csv_bytes = fetch_ftp_bytes(fa.file_path) 
        changed, new_hash = is_file_changed(fa, csv_bytes)
        if changed:
            store_csv_data(fa, csv_bytes, new_hash)
            print(f"{fa.file_name} imported successfully. Data updated.")
            check_triggered_alerts.delay(fa.id)
        else:
            fa.last_fetched_at = timezone.now()
            fa.save(update_fields=['last_fetched_at'])
            print(f"{fa.file_name}: No changes detected.")
    except Exception as e:
        print(f"Error importing {fa.file_name}: {e}")


@shared_task
def check_and_import_files():
    now = timezone.now()
    files = FileAssociation.objects.all()

    for fa in files:
        interval_seconds = fa.interval.interval_minutes * 60
        if not fa.last_fetched_at:
            reason = "never imported before"
            should_import = True
        elif (now - fa.last_fetched_at).total_seconds() >= interval_seconds:
            reason = f"interval passed ({fa.interval.interval_minutes} min)"
            should_import = True
        else:
            reason = f"interval not passed yet ({fa.interval.interval_minutes} min)"
            should_import = False

        if should_import:
            import_file_association.delay(fa.id)
            print(f"[IMPORT] {fa.file_name}: {reason}")
        else:
            print(f"[SKIP]   {fa.file_name}: {reason}")

    print("check_and_import_files finished.")


def to_float_safe(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def should_trigger(alert, raw_value):
    current_num = to_float_safe(raw_value)
    compare_num = to_float_safe(alert.compare_value)
    prev_value = alert.last_value

    if current_num is not None and compare_num is not None:
        v, c = current_num, compare_num
    else:
        v, c = str(raw_value), str(alert.compare_value)

    if alert.condition_type == "equals":
        return v == c and prev_value != v
    elif alert.condition_type == "threshold_cross":
        return current_num is not None and current_num > compare_num
    elif alert.condition_type == "increase":
        return prev_value is not None and current_num is not None and current_num > prev_value
    elif alert.condition_type == "decrease":
        return prev_value is not None and current_num is not None and current_num < prev_value
    elif alert.condition_type == "change":
        if prev_value is None:
            return False
        return (current_num != prev_value) if current_num is not None else str(raw_value) != str(prev_value)
    return False


def get_last_row_value(rows, field_name):
    if not rows:
        return None
    return to_float_safe(rows[-1].get(field_name)) or rows[-1].get(field_name)


def get_triggered_alerts(fa, rows):
    triggered_alerts = []
    active_alerts = list(fa.global_alerts.all()) + list(fa.custom_alerts.all())
    if not active_alerts:
        return []

    for alert in active_alerts:
        alert.is_global = isinstance(alert, GlobalAlertRule)
        alert.is_custom = isinstance(alert, CustomAlert)

        triggered_value = next(
            (row.get(alert.field_name) for row in rows if should_trigger(alert, row.get(alert.field_name))),
            None
        )

        if triggered_value is not None and alert.last_value != triggered_value:
            triggered_alerts.append((alert, triggered_value))
            alert.last_value = triggered_value
            alert.is_active = False
        else:
            alert.last_value = get_last_row_value(rows, alert.field_name)
        alert.save(update_fields=['is_active', 'last_value'])

    return triggered_alerts



def create_triggered_alerts(fa, triggered_list):
    ta_objects = [
        TriggeredAlert(
            file_association=fa,
            global_alert=alert if hasattr(alert, 'is_global') and alert.is_global else None,
            custom_alert=alert if hasattr(alert, 'is_custom') and alert.is_custom else None
        )
        for alert, _ in triggered_list
    ]
    TriggeredAlert.objects.bulk_create(ta_objects)
    return ta_objects


def send_alert_emails(triggered_alerts):
    for ta in triggered_alerts:
        fa = ta.file_association
        table_link = "Table Link"
        timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        alert_obj = ta.global_alert if ta.global_alert else ta.custom_alert
        price_info = f"Target Price: ${alert_obj.last_value}\n" if alert_obj.field_name in ["Target #1", "Target #2"] else ""
        subject = f"Alert Triggered: {alert_obj.field_name}"
        message = (
            f"Hello,\n\n"
            f"An alert has been triggered in your monitored file: {fa.file_name}\n"
            f"Alert Type: {'Default' if ta.global_alert else 'Custom'}\n"
            f"Triggered Field: {alert_obj.field_name} ${price_info}\n"
            f"Alert Condition: {alert_obj.condition_type} {alert_obj.compare_value}"
            f"Current Value: {alert_obj.last_value}"
            f"Triggered At: {timestamp}"
            f"View Table: {table_link}\n\n"
            f"Regards,\nMENT Monitoring System"
        )
        if ta.custom_alert and ta.custom_alert.user.email:
            user = ta.custom_alert.user
            settings = getattr(user, "settings", None)
            if settings and ("email" in settings.delivery_methods or "all" in settings.delivery_methods):
                send_alert_email(user.email, subject, message)

        if ta.global_alert:
            for user in MENTUser.objects.all():
                if not user.email:
                    continue
                settings = getattr(user, "settings", None)
                if not settings:
                    continue
                if "email" in settings.delivery_methods or "all" in settings.delivery_methods:
                    send_alert_email(user.email, subject, message)


def send_sms_notifications(triggered_alerts):
    for ta in triggered_alerts:
        alert_obj = ta.global_alert if ta.global_alert else ta.custom_alert
        timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        price_info = f"Target Price: ${alert_obj.last_value}\n" if alert_obj.field_name in ["Target #1", "Target #2"] else ""
        fa = ta.file_association
        message = (
            f"Alert Triggered!\n"
            f"File: {fa.file_name}\n"
            f"Field: {alert_obj.field_name} ${price_info}\n"
            f"Current Value: {alert_obj.last_value}\n"
            f"Condition: {alert_obj.condition_type} {alert_obj.compare_value}\n"
            f"Triggered At: {timestamp}"
        )

        recipients = []
        if ta.custom_alert and ta.custom_alert.user:
            recipients.append(ta.custom_alert.user)
        
        if ta.global_alert:
            recipients.extend(MENTUser.objects.all())
        
        for user in recipients:
            try:
                settings = user.settings
                methods = settings.delivery_methods
                phone = settings.alert_phone or user.phone
            except UserSettings.DoesNotExist:
                methods = []
                phone = user.phone

            if 'sms' in methods or 'all' in methods:
                if phone:
                    send_alert_sms(phone, message)



@shared_task
def check_triggered_alerts(file_id):
    try:
        fa = FileAssociation.objects.get(id=file_id)
    except FileAssociation.DoesNotExist:
        return

    main_data = fa.maindata.first()
    if not main_data:
        return

    rows = main_data.data_json.get("rows", [])
    if not rows:
        return

    if rows and any(not str(v).replace('.', '', 1).isdigit() for v in rows[0].values()):
        rows = rows[1:]

    triggered_list = get_triggered_alerts(fa, rows)
    if triggered_list:
        ta_objects = create_triggered_alerts(fa, triggered_list)
        send_alert_emails(ta_objects)
        send_sms_notifications(ta_objects)
    
    all_alerts = list(fa.global_alerts.all()) + list(fa.custom_alerts.all())
    for alert in all_alerts:
        alert.save(update_fields=['is_active', 'last_value'])
