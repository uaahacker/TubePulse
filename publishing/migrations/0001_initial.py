import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('core', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PublishingChannel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(choices=[('youtube', 'YouTube')], default='youtube', max_length=24)),
                ('channel_id', models.CharField(max_length=128)),
                ('channel_title', models.CharField(max_length=255)),
                ('channel_thumbnail_url', models.URLField(blank=True)),
                ('credentials_blob', models.TextField(blank=True, help_text='Encrypted OAuth credentials; never exposed in forms or admin.')),
                ('scopes', models.JSONField(blank=True, default=list)),
                ('token_expiry', models.DateTimeField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('last_connected_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publishing_channels', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('channel_title',),
            },
        ),
        migrations.CreateModel(
            name='ScheduledPublication',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=100)),
                ('description', models.TextField(blank=True, max_length=5000)),
                ('tags', models.JSONField(blank=True, default=list)),
                ('privacy_status', models.CharField(choices=[('public', 'Public'), ('unlisted', 'Unlisted'), ('private', 'Private')], default='public', max_length=12)),
                ('scheduled_for', models.DateTimeField(db_index=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('processing', 'Uploading'), ('retry', 'Retry scheduled'), ('published', 'Published'), ('failed', 'Failed'), ('cancelled', 'Cancelled')], db_index=True, default='pending', max_length=16)),
                ('youtube_video_id', models.CharField(blank=True, max_length=32)),
                ('publication_url', models.URLField(blank=True)),
                ('error_message', models.TextField(blank=True)),
                ('attempt_count', models.PositiveSmallIntegerField(default=0)),
                ('next_attempt_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('published_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('channel', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publications', to='publishing.publishingchannel')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publications', to='core.videoproject')),
            ],
            options={
                'ordering': ('scheduled_for', 'pk'),
            },
        ),
        migrations.AddConstraint(
            model_name='publishingchannel',
            constraint=models.UniqueConstraint(fields=('user', 'provider', 'channel_id'), name='unique_user_publishing_channel'),
        ),
        migrations.AddIndex(
            model_name='scheduledpublication',
            index=models.Index(fields=['status', 'scheduled_for'], name='publication_due_idx'),
        ),
    ]
