from celery import shared_task
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
import logging

from ttscanner.models import FileAssociation, MENTUser, UserSettings, TriggeredAlert
from ttscanner.utils.csv_utils import fetch_ftp_bytes, is_file_changed, store_csv_data
from ttscanner.engine.evaluator import lookup_any, process_row_for_alerts
from ttscanner.utils.email_utils import send_alert_email
from ttscanner.utils.sms_utils import send_alert_sms

logger = logging.getLogger(__name__)


@shared_task
def import_file_association(file_id):
    """Fetch CSV, store if changed, then evaluate alerts."""
    try:
        fa = FileAssociation.objects.get(id=file_id)
    except ObjectDoesNotExist:
        print(f"[IMPORT] FileAssociation id={file_id} not found. Skipping.")
        return

    try:
        print(f"[IMPORT] Fetching CSV from: {fa.file_path}")
        csv_bytes = fetch_ftp_bytes(fa.file_path)
        print(f"[IMPORT] Fetched {len(csv_bytes)} bytes for {fa.file_name}")

        changed, new_hash = is_file_changed(fa, csv_bytes)
        if changed:
            store_csv_data(fa, csv_bytes, new_hash)
            fa.data_version += 1
            print(f"[IMPORT] Data Version Incremented → {fa.data_version}")
            print(f"[IMPORT] Changes detected → CSV stored for {fa.file_name}")
        else:
            print(f"[IMPORT] No changes detected for {fa.file_name}")

        fa.last_fetched_at = timezone.now()
        update_fields = ['last_fetched_at']
        if changed:
            update_fields.append('data_version')
        fa.save(update_fields=update_fields)

    except Exception as e:
        print(f"[IMPORT] Error fetching/storing CSV for {fa.file_name}: {e}")


@shared_task
def check_and_import_files():
    """Periodic task to fetch and evaluate files based on interval."""
    now = timezone.now()
    files = FileAssociation.objects.all()

    for fa in files:
        interval_seconds = fa.interval.interval_minutes * 60 if fa.interval else 300
        should_import = False
        reason = ""
        if not fa.last_fetched_at:
            reason = "never imported before"
            should_import = True
        elif (now - fa.last_fetched_at).total_seconds() >= interval_seconds:
            reason = f"interval passed ({fa.interval.interval_minutes} min)"
            should_import = True
        else:
            reason = f"interval not passed yet ({fa.interval.interval_minutes} min)"

        if should_import:
            print(f"[IMPORT] Triggering import for {fa.file_name} → {reason}")
            import_file_association.delay(fa.id)
        else:
            print(f"[SKIP] {fa.file_name} → {reason}")

    print("[CHECK] check_and_import_files finished.")


def send_alert_emails(triggered_alerts):
    """Send email notifications for triggered alerts, including system-generated alerts."""
    for ta in triggered_alerts:
        fa = ta.file_association
        alert_obj = ta.global_alert or ta.custom_alert
        if alert_obj:
            subject = f"Alert Triggered: {getattr(alert_obj, 'field_name', 'System Alert')}"
        else:
            subject = f"Alert Triggered: System Alert"
        message = ta.message
        print(f"[EMAIL] Preparing email for {fa.file_name}: {subject}")

        if ta.custom_alert and ta.custom_alert.user and ta.custom_alert.user.email:
            try:
                send_alert_email(ta.custom_alert.user.email, subject, message)
                print(f"[EMAIL] Sent to {ta.custom_alert.user.email}")
            except Exception as e:
                print(f"[EMAIL] Failed to send to {ta.custom_alert.user.email}: {e}")

        for user in MENTUser.objects.all():
            try:
                methods = getattr(user.settings, "delivery_methods", [])
            except UserSettings.DoesNotExist:
                methods = []
            if user.email and ('email' in methods or 'all' in methods):
                try:
                    send_alert_email(user.email, subject, message)
                    print(f"[EMAIL] Sent to {user.email}")
                except Exception as e:
                    print(f"[EMAIL] Failed to send to {user.email}: {e}")


def send_sms_notifications(triggered_alerts):
    """Send SMS notifications for triggered alerts, including system-generated alerts."""
    for ta in triggered_alerts:
        fa = ta.file_association
        message = ta.message
        recipients = []

        if ta.custom_alert and ta.custom_alert.user:
            recipients.append(ta.custom_alert.user)
        else:
            recipients.extend(MENTUser.objects.all())

        for user in recipients:
            try:
                phone = getattr(user.settings, "alert_phone", None) or user.phone
                methods = getattr(user.settings, "delivery_methods", [])
            except UserSettings.DoesNotExist:
                phone = user.phone
                methods = []

            if phone and ('sms' in methods or 'all' in methods):
                try:
                    send_alert_sms(phone, message)
                    print(f"[SMS] Sent to {phone}")
                except Exception as e:
                    print(f"[SMS] Failed to send to {phone}: {e}")



def should_trigger(alert, raw_value):
    """Check if a global/custom alert should trigger based on its condition."""
    def safe_str(val):
        return str(val).strip().upper() if val is not None else None

    current_val = raw_value
    compare_val = getattr(alert, 'compare_value', None)
    prev_val = getattr(alert, 'last_value', None)

    v_str = safe_str(current_val)
    c_str = safe_str(compare_val)
    prev_str = safe_str(prev_val)

    cond = getattr(alert, "condition_type", "change").lower()
    if cond == "equals":
        if current_val is not None and compare_val is not None:
            return current_val == compare_val and prev_val != current_val
        return v_str == c_str and prev_str != v_str
    elif cond in ["threshold_cross", "increase"]:
        if current_val is None or compare_val is None:
            return False
        return prev_val is None or prev_val <= compare_val and current_val > compare_val
    elif cond == "decrease":
        if current_val is None or compare_val is None:
            return False
        return prev_val is None or prev_val >= compare_val and current_val < compare_val
    elif cond == "change":
        if prev_val is None:
            return False
        return current_val != prev_val
    return v_str != prev_str


def evaluate_global_custom_alerts(fa, rows):
    """Return list of TriggeredAlert objects for global/custom alerts."""
    triggered = []

    try:
        all_alerts = list(fa.global_alerts.all()) + list(fa.custom_alerts.all())
    except AttributeError:
        all_alerts = []

    if not rows or not all_alerts:
        return []

    first_row = rows[0]
    symbol_key = lookup_any(first_row, ["Symbol/Interval", "Symbol", "sym/int", "sym", "Ticker", "symbol"])

    if not symbol_key:
        print("[GC ALERTS] No valid symbol column found. Skipping evaluation.")
        return []

    for row in rows:
        row_sym = str(row.get(symbol_key, "")).strip().upper()
        if not row_sym:
            continue

        for alert in all_alerts:

            row_value = row.get(alert.field_name)
            if row_value is None:
                continue

            expected_symbol = getattr(alert, "symbol_interval", None)
            if expected_symbol and row_sym != expected_symbol.strip().upper():
                continue

            if should_trigger(alert, row_value):

                msg = f"{'GLOBAL' if hasattr(alert, 'is_global') else 'CUSTOM'} alert for {row_sym} → {alert.field_name}: {row_value}"

                triggered.append(
                    TriggeredAlert(
                        file_association=fa,
                        global_alert=alert if getattr(alert, "is_global", False) else None,
                        custom_alert=alert if getattr(alert, "is_custom", False) else None,
                        message=msg
                    )
                )

                alert.last_value = row_value
                alert.is_active = False
                alert.save(update_fields=['last_value', 'is_active'])

    if triggered:
        TriggeredAlert.objects.bulk_create(triggered)

    return triggered


@shared_task
def check_triggered_alerts(file_id):
    """Evaluate system, global, and custom alerts and send notifications."""
    try:
        fa = FileAssociation.objects.get(id=file_id)
    except FileAssociation.DoesNotExist:
        print(f"[ALERT] FileAssociation id={file_id} not found.")
        return

    print(f"[ALERT] Evaluating alerts for {fa.file_name}")

    triggered_list = []

    if getattr(fa, "algo", None):
        main_data = fa.maindata.first()
        rows = main_data.data_json.get("rows", []) if main_data else []
        if rows:
            for row in rows:
                system_alerts = process_row_for_alerts(fa, fa.algo, row)
                for alert in system_alerts:
                    alert.save()
                    triggered_list.append(alert)
                    print(f"[SYSTEM ALERT] {alert.message}")

    if rows:
        gc_alerts = evaluate_global_custom_alerts(fa, rows)
        triggered_list.extend(gc_alerts)
        for ta in gc_alerts:
            print(f"[GC ALERT] {ta.message}")

    if triggered_list:
        print(f"[ALERT] Total {len(triggered_list)} alerts triggered for {fa.file_name}")
        send_alert_emails(triggered_list)
        send_sms_notifications(triggered_list)
        print(f"[ALERT] Notifications sent for {fa.file_name}")
    else:
        print(f"[ALERT] No alerts triggered for {fa.file_name}")



@shared_task
def send_announcement_sms_task(message):
    users = MENTUser.objects.exclude(phone__isnull=True).exclude(phone__exact="")
    phones = [user.phone for user in users]

    if not phones:
        logger.warning("No users with phone numbers found for announcement SMS.")
        return {"sent": 0, "failed": 0, "total": 0}


    try:
        sent_count, failed_count = send_alert_sms(phones, message)
    except Exception as e:
        logger.error(f"Bulk SMS sending failed: {e}")
        sent_count = 0
        failed_count = 0
        for phone in phones:
            try:
                s, f = send_alert_sms(phone, message, force_send=False)
                sent_count += s
                failed_count += f
            except Exception as ex:
                logger.error(f"Failed to send SMS to {phone}: {ex}")
                failed_count += 1

    logger.info(f"Announcement SMS sent: {sent_count}, failed: {failed_count}, total: {len(phones)}")

    return {
        "sent": sent_count,
        "failed": failed_count,
        "total": len(phones)
    }

































# @shared_task
# def check_triggered_alerts(file_id):
#     """Evaluate alerts for a FileAssociation and store + send notifications."""
#     try:
#         fa = FileAssociation.objects.get(id=file_id)
#     except FileAssociation.DoesNotExist:
#         print(f"[ALERT] FileAssociation id={file_id} not found.")
#         return

#     print(f"[ALERT] Evaluating alerts for {fa.file_name}")

#     algos = [fa.algo] if getattr(fa, "algo", None) else []
#     triggered_list = []

#     for algo in algos:
#         main_data = fa.maindata.first()
#         rows = main_data.data_json.get("rows", []) if main_data else []
#         if not rows:
#             print(f"[ALERT] No data rows found for {fa.file_name}")
#             continue

#         for row in rows:
#             alerts = process_row_for_alerts(fa, algo, row)
#             for alert in alerts:
#                 alert.save()  
#                 triggered_list.append(alert)
#                 print(f"[ALERT] Triggered: {alert.message}")

#     if triggered_list:
#         print(f"[ALERT] Total {len(triggered_list)} alerts triggered for {fa.file_name}")
#         send_alert_emails(triggered_list)
#         send_sms_notifications(triggered_list)
#         print(f"[ALERT] Notifications sent for {fa.file_name}")
#     else:
#         print(f"[ALERT] No alerts triggered for {fa.file_name}")

# @shared_task
# def check_triggered_alerts(file_id):
#     try:
#         fa = FileAssociation.objects.get(id=file_id)
#     except FileAssociation.DoesNotExist:
#         logger.warning(f"FileAssociation id={file_id} not found.")
#         return

#     main_data = fa.maindata.first()
#     if not main_data:
#         logger.info(f"No data for FileAssociation {fa.file_name}")
#         return

#     rows = main_data.data_json.get("rows", [])
#     if not rows:
#         return

#     # Skip header row if not numeric
#     if any(not str(v).replace('.', '', 1).isdigit() for v in rows[0].values()):
#         rows = rows[1:]

#     triggered_list = get_triggered_alerts(fa, rows)
#     if triggered_list:
#         ta_objects = create_triggered_alerts(fa, triggered_list)
#         send_alert_emails(ta_objects)
#         send_sms_notifications(ta_objects)
#     else:
#         logger.info(f"No alerts triggered for FileAssociation {fa.file_name}")









# from celery import shared_task
# from django.core.exceptions import ObjectDoesNotExist
# from django.utils import timezone
# import datetime
# import logging
# from .utils.email_utils import send_alert_email
# from .utils.sms_utils import send_alert_sms
# from ttscanner.models import (
#     FileAssociation, TriggeredAlert, 
#     MENTUser, CustomAlert, GlobalAlertRule, 
#     UserSettings
# )
# from ttscanner.utils.csv_utils import fetch_ftp_bytes, is_file_changed, store_csv_data

# logger = logging.getLogger(__name__)


# @shared_task
# def import_file_association(file_id):
#     try:
#         fa = FileAssociation.objects.get(id=file_id)
#     except ObjectDoesNotExist:
#         print(f"FileAssociation with id={file_id} does not exist. Skipping task.")
#         return

#     try:
#         csv_bytes = fetch_ftp_bytes(fa.file_path) 
#         logger.info(f"[{datetime.datetime.now()}] Starting import for {fa.file_name}")
#         changed, new_hash = is_file_changed(fa, csv_bytes)
#         if changed:
#             store_csv_data(fa, csv_bytes, new_hash)
#             print(f"{fa.file_name} imported successfully. Data updated.")
#             check_triggered_alerts.delay(fa.id)
#         else:
#             fa.last_fetched_at = timezone.now()
#             fa.save(update_fields=['last_fetched_at'])
#             print(f"{fa.file_name}: No changes detected.")
#         check_triggered_alerts.delay(fa.id)
#     except Exception as e:
#         print(f"Error importing {fa.file_name}: {e}")


# @shared_task
# def check_and_import_files():
#     now = timezone.now()
#     files = FileAssociation.objects.all()

#     for fa in files:
#         interval_seconds = fa.interval.interval_minutes * 60
#         if not fa.last_fetched_at:
#             reason = "never imported before"
#             should_import = True
#         elif (now - fa.last_fetched_at).total_seconds() >= interval_seconds:
#             reason = f"interval passed ({fa.interval.interval_minutes} min)"
#             should_import = True
#         else:
#             reason = f"interval not passed yet ({fa.interval.interval_minutes} min)"
#             should_import = False

#         if should_import:
#             import_file_association.delay(fa.id)
#             print(f"[IMPORT] {fa.file_name}: {reason}")
#         else:
#             print(f"[SKIP]   {fa.file_name}: {reason}")

#     print("check_and_import_files finished.")


# def to_float_safe(value):
#     try:
#         return float(value)
#     except (ValueError, TypeError):
#         return None


# def get_last_row_value(rows, field_name):
#     if not rows:
#         return None
#     return to_float_safe(rows[-1].get(field_name)) or rows[-1].get(field_name)


# def should_trigger(alert, raw_value):
#     current_num = to_float_safe(raw_value)
#     compare_num = to_float_safe(alert.compare_value)
#     prev_value = to_float_safe(alert.last_value)

#     v_str = str(raw_value).strip().upper() if raw_value is not None else None
#     c_str = str(alert.compare_value).strip().upper() if alert.compare_value is not None else None
#     prev_str = str(alert.last_value).strip().upper() if alert.last_value is not None else None

#     if alert.field_name.lower() in ["target #1", "target #2", "target price"]:
#         if is_target_hit(alert, prev_value, current_num, compare_num):
#             return True
#         return False

#     if alert.condition_type == "equals":
#         if current_num is not None and compare_num is not None:
#             return current_num == compare_num and prev_value != current_num
#         return v_str == c_str and prev_str != v_str

#     elif alert.condition_type == "threshold_cross":
#         if current_num is None or compare_num is None:
#             return False
#         return prev_value is None or (prev_value <= compare_num and current_num > compare_num)

#     elif alert.condition_type == "increase":
#         if current_num is None:
#             return False

#         if compare_num is not None:
#             return (prev_value is None or prev_value <= compare_num) and current_num > compare_num

#         return prev_value is None or current_num > prev_value

#     elif alert.condition_type == "decrease":
#         if current_num is None:
#             return False

#         if compare_num is not None:
#             return (prev_value is None or prev_value >= compare_num) and current_num < compare_num

#         return prev_value is None or current_num < prev_value

#     elif alert.condition_type == "change":
#         if prev_value is None:
#             return False

#         if current_num is not None and prev_value is not None:
#            return current_num != prev_value

#     return v_str != prev_str


# def find_column(headers, alternatives):
#     for h in headers:
#         normalized = str(h).lower().replace(" ", "").replace("_", "").replace("-", "").replace("/", "")
#         for alt in alternatives:
#             if normalized == alt.lower():
#                 return h 
#     return None



# def is_target_hit(alert, prev_value, current_value, target_value, row=None):
#     if current_value is None or target_value is None:
#         return False

#     prev_value = prev_value or current_value 
#     direction = str(getattr(alert, "direction", "")).lower()
#     hit = False

#     if direction == "long":
#         hit = prev_value < target_value <= current_value
#     elif direction == "short":
#         hit = prev_value > target_value >= current_value
#     elif direction == "flat":
#         hit = current_value == target_value

#     if hit:
#         now = timezone.now()
#         if alert.field_name.lower() == "target #1":
#             alert.target_1_hit_at = now
#         elif alert.field_name.lower() == "target #2":
#             alert.target_2_hit_at = now

#         if row is not None:
#             now_str = now.strftime("%Y-%m-%d %H:%M:%S")
#             if alert.field_name.lower() == "target #1":
#                 row["Target #1 DateTime"] = now_str
#             elif alert.field_name.lower() == "target #2":
#                 row["Target #2 DateTime"] = now_str

#         alert.save(update_fields=['target_1_hit_at', 'target_2_hit_at'])

#     return hit



# def get_triggered_alerts(fa, rows):
#     triggered_alerts = []

#     try:
#         all_alerts = list(fa.global_alerts.all()) + list(fa.custom_alerts.all())
#     except AttributeError:
#         all_alerts = []

#     headers = rows[0].keys() if rows else []
#     sym_int_col = "Symbol/Interval"
#     direction_col = "Direction"
#     target_fields = ["Target #1", "Target #2"]

#     for row in rows:
#         for target_field in target_fields:
#             if target_field in row:
#                 virtual_alert = type('VirtualAlert', (), {})()
#                 virtual_alert.field_name = target_field
#                 virtual_alert.last_value = None
#                 virtual_alert.compare_value = row[target_field]
#                 virtual_alert.symbol_interval = row[sym_int_col]
#                 virtual_alert.direction = row.get(direction_col, "flat").lower()
#                 virtual_alert.is_global = True
#                 virtual_alert.is_custom = False
#                 virtual_alert.condition_type = "target_hit"

#                 all_alerts.append(virtual_alert)

#     for alert in all_alerts:
#         alert.is_global = isinstance(alert, GlobalAlertRule)
#         alert.is_custom = isinstance(alert, CustomAlert)

#         triggered_value = next(
#             (row.get(alert.field_name) for row in rows if should_trigger(alert, row.get(alert.field_name))),
#             None
#         )

#         if triggered_value is not None and alert.last_value != triggered_value:
#             triggered_alerts.append((alert, triggered_value))
#             alert.last_value = triggered_value
#             alert.is_active = False
#         else:
#             alert.last_value = get_last_row_value(rows, alert.field_name)
#         alert.save(update_fields=['is_active', 'last_value'])

#         filtered_rows = [
#             row for row in rows
#             if row[sym_int_col].strip().upper() == alert.symbol_interval.strip().upper()
#         ]
#         for row in filtered_rows:
#             triggered_value = row.get(alert.field_name)
#             if triggered_value is not None:
#                 triggered_alerts.append((alert, triggered_value))
#                 alert.last_value = triggered_value

#     return triggered_alerts


# def create_triggered_alerts(fa, triggered_list):
#     ta_objects = [
#         TriggeredAlert(
#             file_association=fa,
#             global_alert=alert if getattr(alert, 'is_global', False) else None,
#             custom_alert=alert if getattr(alert, 'is_custom', False) else None
#         )
#         for alert, _ in triggered_list
#     ]
#     for alert, _ in triggered_list:
#         alert.is_active = False
#         alert.save(update_fields=['is_active'])

#     TriggeredAlert.objects.bulk_create(ta_objects)
#     return ta_objects



# def send_alert_emails(triggered_alerts):
#     for ta in triggered_alerts:
#         fa = ta.file_association
#         table_link = "Table Link"
#         alert_obj = ta.global_alert if ta.global_alert else ta.custom_alert

#         hit_time = None
#         if alert_obj.field_name.lower() == "target #1":
#             hit_time = alert_obj.target_1_hit_at
#         elif alert_obj.field_name.lower() == "target #2":
#             hit_time = alert_obj.target_2_hit_at
#         hit_time_str = hit_time.strftime("%Y-%m-%d %H:%M:%S") if hit_time else "N/A"

#         price_info = f"Target Price: ${alert_obj.last_value}\n" if alert_obj.field_name in ["Target #1", "Target #2"] else ""
#         subject = f"Alert Triggered: {alert_obj.field_name}"
#         message = (
#             f"Hello,\n\n"
#             f"An alert has been triggered in your monitored file: {fa.file_name}\n"
#             f"Alert Type: {'Default' if ta.global_alert else 'Custom'}\n"
#             f"Triggered Field: {alert_obj.field_name}\n"
#             f"{price_info}"
#             f"Target Hit Time: {hit_time_str}\n"
#             f"Alert Condition: {alert_obj.condition_type} {alert_obj.compare_value}\n"
#             f"Current Value: {alert_obj.last_value}\n"
#             f"View Table: {table_link}\n\n"
#             f"Regards,\nMENT Monitoring System"
#         )

#         if ta.custom_alert and ta.custom_alert.user.email:
#             user = ta.custom_alert.user
#             settings = getattr(user, "settings", None)
#             if settings and ("email" in settings.delivery_methods or "all" in settings.delivery_methods):
#                 send_alert_email(user.email, subject, message)

#         if ta.global_alert:
#             for user in MENTUser.objects.all():
#                 if not user.email:
#                     continue
#                 settings = getattr(user, "settings", None)
#                 if not settings:
#                     continue
#                 if "email" in settings.delivery_methods or "all" in settings.delivery_methods:
#                     send_alert_email(user.email, subject, message)



# def send_sms_notifications(triggered_alerts):
#     for ta in triggered_alerts:
#         alert_obj = ta.global_alert if ta.global_alert else ta.custom_alert
#         fa = ta.file_association

#         hit_time = None
#         if alert_obj.field_name.lower() == "target #1":
#             hit_time = alert_obj.target_1_hit_at
#         elif alert_obj.field_name.lower() == "target #2":
#             hit_time = alert_obj.target_2_hit_at
#         hit_time_str = hit_time.strftime("%Y-%m-%d %H:%M:%S") if hit_time else "N/A"

#         price_info = f"Target Price: ${alert_obj.last_value}\n" if alert_obj.field_name in ["Target #1", "Target #2"] else ""
#         message = (
#             f"Alert Triggered!\n"
#             f"File: {fa.file_name}\n"
#             f"Field: {alert_obj.field_name}\n"
#             f"{price_info}"
#             f"Target Hit Time: {hit_time_str}\n"
#             f"Current Value: {alert_obj.last_value}\n"
#             f"Condition: {alert_obj.condition_type} {alert_obj.compare_value}"
#         )

#         recipients = []
#         if ta.custom_alert and ta.custom_alert.user:
#             recipients.append(ta.custom_alert.user)
        
#         if ta.global_alert:
#             recipients.extend(MENTUser.objects.all())
        
#         for user in recipients:
#             try:
#                 settings = user.settings
#                 methods = settings.delivery_methods
#                 phone = settings.alert_phone or user.phone
#             except UserSettings.DoesNotExist:
#                 methods = []
#                 phone = user.phone

#             if 'sms' in methods or 'all' in methods:
#                 if phone:
#                     send_alert_sms(phone, message)



# @shared_task
# def check_triggered_alerts(file_id):
#     try:
#         fa = FileAssociation.objects.get(id=file_id)
#     except FileAssociation.DoesNotExist:
#         print(f"[DEBUG] FileAssociation id={file_id} does not exist")
#         return

#     main_data = fa.maindata.first()
#     if not main_data:
#         print(f"[DEBUG] No main data for FileAssociation id={file_id}")
#         return

#     rows = main_data.data_json.get("rows", [])
#     if not rows:
#         print(f"[DEBUG] No rows found in main data for FileAssociation id={file_id}")
#         return
#     if rows and any(not str(v).replace('.', '', 1).isdigit() for v in rows[0].values()):
#         rows = rows[1:]

#     triggered_list = get_triggered_alerts(fa, rows)
#     if triggered_list:
#         ta_objects = create_triggered_alerts(fa, triggered_list)
#         send_alert_emails(ta_objects)
#         send_sms_notifications(ta_objects)
#     else:
#         print(f"[DEBUG] No alerts triggered for FileAssociation id={file_id}")




# @shared_task
# def send_announcement_sms_task(message):
#     users = MENTUser.objects.exclude(phone__isnull=True).exclude(phone__exact="")
#     phones = [user.phone for user in users]

#     if not phones:
#         logger.warning("No users with phone numbers found for announcement SMS.")
#         return {"sent": 0, "failed": 0, "total": 0}


#     try:
#         sent_count, failed_count = send_alert_sms(phones, message)
#     except Exception as e:
#         logger.error(f"Bulk SMS sending failed: {e}")
#         sent_count = 0
#         failed_count = 0
#         for phone in phones:
#             try:
#                 s, f = send_alert_sms(phone, message, force_send=False)
#                 sent_count += s
#                 failed_count += f
#             except Exception as ex:
#                 logger.error(f"Failed to send SMS to {phone}: {ex}")
#                 failed_count += 1

#     logger.info(f"Announcement SMS sent: {sent_count}, failed: {failed_count}, total: {len(phones)}")

#     return {
#         "sent": sent_count,
#         "failed": failed_count,
#         "total": len(phones)
#     }
