import core.models
import django.contrib.auth.models
import django.contrib.auth.validators
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='User',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('username', models.CharField(error_messages={'unique': 'A user with that username already exists.'}, help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.', max_length=150, unique=True, validators=[django.contrib.auth.validators.UnicodeUsernameValidator()], verbose_name='username')),
                ('first_name', models.CharField(blank=True, max_length=150, verbose_name='first name')),
                ('last_name', models.CharField(blank=True, max_length=150, verbose_name='last name')),
                ('email', models.EmailField(blank=True, max_length=254, verbose_name='email address')),
                ('is_staff', models.BooleanField(default=False, help_text='Designates whether the user can log into this admin site.', verbose_name='staff status')),
                ('is_active', models.BooleanField(default=True, help_text='Designates whether this user should be treated as active. Unselect this instead of deleting accounts.', verbose_name='active')),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined')),
                ('display_name', models.CharField(blank=True, max_length=120)),
                ('timezone', models.CharField(default='UTC', max_length=64)),
                ('avatar_url', models.URLField(blank=True)),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),
            ],
            options={
                'verbose_name': 'user',
                'verbose_name_plural': 'users',
                'abstract': False,
            },
            managers=[
                ('objects', django.contrib.auth.models.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name='Trend',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('niche', models.CharField(db_index=True, max_length=100)),
                ('title', models.CharField(max_length=300)),
                ('keywords', models.JSONField(blank=True, default=list)),
                ('source', models.CharField(db_index=True, max_length=80)),
                ('source_url', models.URLField(blank=True, max_length=1000)),
                ('score', models.PositiveSmallIntegerField(db_index=True, default=50, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)])),
                ('discovered_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('raw_payload', models.JSONField(blank=True, default=dict)),
                ('fingerprint', models.CharField(db_index=True, max_length=64, unique=True)),
                ('status', models.CharField(choices=[('new', 'New'), ('reviewed', 'Reviewed'), ('queued', 'Queued'), ('archived', 'Archived')], db_index=True, default='new', max_length=16)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(blank=True, help_text='Null means the trend is visible to all users.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='trends', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-score', '-discovered_at'],
            },
        ),
        migrations.CreateModel(
            name='VideoProject',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('title', models.CharField(max_length=200)),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('scripting', 'Generating script'), ('ready', 'Ready to render'), ('rendering', 'Rendering'), ('rendered', 'Rendered'), ('scheduled', 'Scheduled'), ('publishing', 'Publishing'), ('published', 'Published'), ('failed', 'Failed')], db_index=True, default='draft', max_length=20)),
                ('progress', models.PositiveSmallIntegerField(default=0, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)])),
                ('provider', models.CharField(choices=[('openai', 'OpenAI'), ('anthropic', 'Anthropic'), ('openrouter', 'OpenRouter')], default='openai', max_length=32)),
                ('script', models.TextField(blank=True)),
                ('voiceover_prompt', models.TextField(blank=True)),
                ('audio_file', models.FileField(blank=True, upload_to=core.models.audio_upload_path)),
                ('source_assets', models.JSONField(blank=True, default=list)),
                ('video_file', models.FileField(blank=True, upload_to=core.models.video_upload_path)),
                ('thumbnail', models.ImageField(blank=True, upload_to=core.models.thumbnail_upload_path)),
                ('scheduled_for', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('published_at', models.DateTimeField(blank=True, null=True)),
                ('publication_url', models.URLField(blank=True, max_length=1000)),
                ('error_message', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('trend', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='video_projects', to='core.trend')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='video_projects', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='APIKeyStore',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(choices=[('openai', 'OpenAI'), ('anthropic', 'Anthropic'), ('openrouter', 'OpenRouter'), ('pexels', 'Pexels')], max_length=32)),
                ('encrypted_key', models.TextField()),
                ('key_hint', models.CharField(blank=True, editable=False, max_length=12)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='api_keys', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['provider'],
                'constraints': [models.UniqueConstraint(fields=('user', 'provider'), name='unique_provider_key_per_user')],
            },
        ),
        migrations.AddIndex(
            model_name='trend',
            index=models.Index(fields=['niche', '-discovered_at'], name='core_trend_niche_996fb4_idx'),
        ),
        migrations.AddIndex(
            model_name='videoproject',
            index=models.Index(fields=['user', 'status', '-created_at'], name='core_videop_user_id_f46901_idx'),
        ),
    ]
