from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('record', '0015_alter_trades_timeframe'),
    ]

    operations = [
        migrations.AddField(
            model_name='trades',
            name='current_stop_loss',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
