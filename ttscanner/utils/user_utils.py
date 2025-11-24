from ..models import MENTUser

def get_or_create_ment_user(user):
    ment_user, _ = MENTUser.objects.get_or_create(
        external_user_id=user.id,
        defaults={'role': 'regular'}
    )
    return ment_user
