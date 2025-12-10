import logging
from twilio.rest import Client
from django.conf import settings
import os

logger = logging.getLogger(__name__)

def send_alert_sms(to, message, force_send=False):
    if isinstance(to, str):
        phones = [to]
    elif isinstance(to, (list, tuple)):
        phones = list(to)
    else:
        raise ValueError("`to` must be a string or list/tuple of phone numbers")

    sent, failed = 0, 0

    if not force_send and getattr(settings, "ENVIRONMENT", "development") != "production":
        logger.warning("----- SMS (DEV MODE) -----")
        logger.warning(f"To: {phones}")
        logger.warning(f"Message: {message}")
        logger.warning("--------------------------")
        return len(phones), 0

    # try:
    #     client = Client(
    #         settings.TWILIO_ACCOUNT_SID,
    #         settings.TWILIO_AUTH_TOKEN
    #     )
    # except Exception as e:
    #     logger.error(f"Twilio client initialization failed: {e}")
    #     return 0, len(phones)

    # for phone in phones:
    #     print(phone)
    #     try:
    #         client.messages.create(
    #             body=message,
    #             from_=settings.TWILIO_PHONE_NUMBER,
    #             to=phone
    #         )
    #         sent += 1
    #     except Exception as e:
    #         logger.error(f"Failed to send SMS to {phone}: {e}")
    #         failed += 1

    return sent, failed
