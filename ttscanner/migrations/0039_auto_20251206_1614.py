from django.db import migrations

def create_default_algos(apps, schema_editor):
    Algo = apps.get_model('ttscanner', 'Algo')

    default_algos = [
        {"algo_name": "FSOptions", "supports_targets": True, "supports_direction": True, "supports_volume_alerts": False, "price_field_key": "Last"},
        {"algo_name": "TTScanner", "supports_targets": False, "supports_direction": True, "supports_volume_alerts": True, "price_field_key": "Price"},
        {"algo_name": "MENT Fibonacci", "supports_targets": True, "supports_direction": True, "supports_volume_alerts": False, "price_field_key": "Close"},
        {"algo_name": "Auto-Detect", "supports_targets": False, "supports_direction": False, "supports_volume_alerts": False, "price_field_key": "value"},
    ]

    for algo in default_algos:
        Algo.objects.get_or_create(algo_name=algo["algo_name"], defaults=algo)

def reverse_func(apps, schema_editor):
    Algo = apps.get_model('ttscanner', 'Algo')
    Algo.objects.filter(algo_name__in=["FSOptions", "TTScanner", "MENT Fibonacci", "Auto-Detect"]).delete()

class Migration(migrations.Migration):

    dependencies = [
        ('ttscanner', '0038_algo_price_field_key_algo_supports_direction_and_more'),
    ]

    operations = [
        migrations.RunPython(create_default_algos, reverse_func),
    ]
