from functools import cache
from celery import shared_task
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
import logging, re
from django.conf import settings
from ttscanner.models import (
    FileAssociation, MENTUser, UserSettings, 
    TriggeredAlert, MainData, CustomAlert
)
from ttscanner.utils.csv_utils import fetch_ftp_bytes, is_file_changed, store_csv_data
from ttscanner.engine.evaluator import lookup_any, process_row_for_alerts
from ttscanner.utils.email_utils import send_alert_email
from ttscanner.utils.sms_utils import send_alert_sms
from ttscanner.utils.text_utils import html_to_plain_text

logger = logging.getLogger(__name__)

def update_user_alert_cache(user_external_id):
    """
    Refresh the cache snapshot for a specific user.
    This will be used by SSE to send updates only when things change.
    """
    alerts = CustomAlert.objects.filter(user__external_user_id=user_external_id).only(
        'id', 'last_value', 'is_active'
    ).order_by('id')

    snapshot = [
        {
            "alert_id": a.id,
            "last_value": a.last_value,
            "is_active": a.is_active,
        }
        for a in alerts
    ]

    cache.set(f"user_alerts_{user_external_id}", snapshot, timeout=None)



@shared_task
def import_file_association(file_id):
    """Fetch CSV, store if changed, then update cache for SSE."""
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
        else:
            print(f"[IMPORT] No changes detected for {fa.file_name}")

        # Update timestamps
        fa.last_fetched_at = timezone.now()
        update_fields = ['last_fetched_at']

        if changed:
            update_fields.append('data_version')
            main_data = MainData.objects.filter(
                file_association=fa.id
            ).first()

            if main_data:
                payload = {
                    "file_association_id": fa.id,
                    "data_version": fa.data_version,
                    "headers": main_data.data_json.get("headers", []),
                    "rows": main_data.data_json.get("rows", []),
                }
                cache.set(f"fa_version_{fa.id}", fa.data_version, timeout=None)
                cache.set(f"fa_data_{fa.id}", payload, timeout=None)

        fa.save(update_fields=update_fields)
        check_triggered_alerts.delay(fa.id)

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
    """Send SMS notifications for triggered alerts."""
    for ta in triggered_alerts:
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

            if phone and ("sms" in methods or "all" in methods):
                try:
                    send_alert_sms(phone, message)
                except Exception as e:
                    logger.error(f"Failed to send SMS to {phone}: {e}")



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
    triggered = []

    if getattr(fa, "data_version", 0) == 0:
        print(f"[GC ALERTS] Skipping alerts for {fa.file_name} → data_version = 0")
        return []

    try:
        all_alerts = list(fa.global_alerts.all()) + list(fa.custom_alerts.all())
    except AttributeError:
        all_alerts = []

    if not rows or not all_alerts:
        print(f"[GC ALERTS] No rows or alerts to evaluate for {fa.file_name}")
        return []

    possible_symbol_keys = ["Symbol/Interval", "Symbol", "sym/int", "sym", "Ticker", "symbol"]
    
    for row in rows:
        normalized_keys = {re.sub(r"[\/_\-\s]", "", k.lower()): k for k in row.keys() if k}
        symbol_key = next(
            (v for k, v in normalized_keys.items() if k in [re.sub(r"[\/_\-\s]", "", s.lower()) for s in possible_symbol_keys]),
            None
        )
        if not symbol_key:
            continue

        row_sym = str(row.get(symbol_key, "")).strip().upper()
        if not row_sym:
            continue

        alerts_to_update = []

        for alert in all_alerts:
            row_value = row.get(alert.field_name)
            if row_value is None:
                continue

            expected_symbol = getattr(alert, "symbol_interval", None)
            if expected_symbol and row_sym != expected_symbol.strip().upper():
                continue

            if should_trigger(alert, row_value):
                msg = f"{'GLOBAL' if getattr(alert, 'is_global', False) else 'CUSTOM'} alert for {row_sym} → {alert.field_name}: {row_value}"
                triggered.append(
                    TriggeredAlert(
                        file_association=fa,
                        alert_source="global" if getattr(alert, "is_global", False) else "custom",
                        global_alert=alert if getattr(alert, "is_global", False) else None,
                        custom_alert=alert if getattr(alert, "is_custom", False) else None,
                        message=msg
                    )
                )

                alert.last_value = row_value
                alert.is_active = False
                alerts_to_update.append(alert)

        if alerts_to_update:
            type(alerts_to_update[0]).objects.bulk_update(alerts_to_update, ["last_value", "is_active"])

            for alert in alerts_to_update:
                if hasattr(alert, 'user') and alert.user:
                    update_user_alert_cache(alert.user.external_user_id)

    if triggered:
        TriggeredAlert.objects.bulk_create(triggered)
        print(f"[GC ALERTS] {len(triggered)} alerts triggered for {fa.file_name}")

        for ta in triggered:
            user_id = ta.custom_alert.user.external_user_id if ta.custom_alert and ta.custom_alert.user else None
            if user_id:
                update_user_alert_cache(user_id)
    else:
        print(f"[GC ALERTS] No alerts triggered for {fa.file_name}")

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
    rows = []

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
    """Send announcement SMS to all users with phones."""

    if getattr(settings, "ENVIRONMENT", "development") != "production":
        print(f"[DEV MODE] SMS not sent. Message preview:\n{message}")
        return {"sent": 0, "failed": 0, "total": 0}
    
    users = MENTUser.objects.exclude(phone__isnull=True).exclude(phone__exact="")
    phones = [user.phone for user in users]

    if not phones:
        logger.warning("No users with phone numbers found for announcement SMS.")
        return {"sent": 0, "failed": 0, "total": 0}

    try:
        plain_message = html_to_plain_text(message)
        logger.warning(f"Plain Message being sent:\n{plain_message}")

        sent_count, failed_count = send_alert_sms(
            phones,
            plain_message,
            force_send=False 
        )

        logger.info(
            f"Announcement SMS sent: {sent_count}, failed: {failed_count}, total: {len(phones)}"
        )

        return {
            "sent": sent_count,
            "failed": failed_count,
            "total": len(phones)
        }

    except Exception as e:
        logger.error(f"Bulk SMS sending failed: {e}")
        return {
            "sent": 0,
            "failed": len(phones),
            "total": len(phones)
        }




