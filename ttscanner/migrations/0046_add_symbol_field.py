# ttscanner/migrations/0046_add_symbol_field.py
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('ttscanner', '0045_announcement'),
    ]

    operations = [
        migrations.AddField(
            model_name='triggeredalert',
            name='symbol',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]