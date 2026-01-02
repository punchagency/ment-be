import logging
from twilio.rest import Client
from django.conf import settings
from ttscanner.utils.text_utils import html_to_plain_text

logger = logging.getLogger(__name__)

def send_alert_sms(to, message, force_send=False):
    if isinstance(to, str):
        phones = [to]
    elif isinstance(to, (list, tuple)):
        phones = list(to)
    else:
        raise ValueError("`to` must be a string or list/tuple of phone numbers")

    sent, failed = 0, 0

    plain_message = html_to_plain_text(message)

    if not force_send and getattr(settings, "ENVIRONMENT", "development") != "production":
        logger.warning("----- SMS (DEV MODE) -----")
        logger.warning(f"To: {phones}")
        logger.warning(f"Message (PLAIN TEXT):\n{plain_message}")
        logger.warning("--------------------------")
        return len(phones), 0

    try:
        account_sid = settings.TWILIO_ACCOUNT_SID
        auth_token = getattr(settings, "TWILIO_AUTH_TOKEN", None)
        api_key_secret = getattr(settings, "TWILIO_API_KEY_SECRET", None)

        if api_key_secret:
            client = Client(account_sid, api_key_secret)
        elif auth_token:
            client = Client(account_sid, auth_token)
        else:
            raise ValueError("Twilio credentials not found in settings")

    except Exception as e:
        logger.error(f"Twilio client initialization failed: {e}")
        return 0, len(phones)

    # Send SMS
    for phone in phones:
        try:
            client.messages.create(
                body=plain_message,
                from_=settings.TWILIO_PHONE_NUMBER,
                to=phone
            )
            sent += 1
            logger.info(f"[SMS SENT] {phone}")
        except Exception as e:
            logger.error(f"Failed to send SMS to {phone}: {e}")
            failed += 1

    logger.info(f"SMS Summary → Sent: {sent}, Failed: {failed}, Total: {len(phones)}")
    return sent, failed