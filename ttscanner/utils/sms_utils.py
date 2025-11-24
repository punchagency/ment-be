import os
from django.conf import settings
from twilio.rest import Client

def send_alert_sms(to, message):
    if os.getenv("ENVIRONMENT") == "development":
        print("----- SMS (DEV MODE) -----")
        print(f"To: {to}")
        print(f"Message: {message}")
        print("--------------------------")
        return True
    
    try:
        client = Client(
            os.getenv("TWILIO_SID"),
            os.getenv("TWILIO_AUTH_TOKEN")
        )
        client.messages.create(
            body=message,
            from_=os.getenv("TWILIO_FROM_NUMBER"),
            to=to
        )
        return True
    except Exception as e:
        print("SMS ERROR:", e)
        return False
