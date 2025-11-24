from django.core.mail import send_mail

def send_alert_email(to_email, subject, message):
    send_mail(
        subject=subject,
        message=message,
        from_email=None, 
        recipient_list=[to_email],
        fail_silently=False,
    )
