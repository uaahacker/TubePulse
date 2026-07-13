# TubePulse

> AI-powered, local-first Django CRM for turning live trend signals into scripted, rendered, scheduled, and published vertical videos.

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue?logo=python)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.x-green?logo=django)](https://www.djangoproject.com/)
[![Docker](https://img.shields.io/badge/Docker%20Compose-ready-blue?logo=docker)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

TubePulse is a local-first Django production system for creators, brands, and agencies who want to move from trend discovery to a published YouTube Short in one workflow. It uses SQLite, Django HTML templates, Bootstrap 5, public RSS sources, pluggable AI providers, MoviePy/FFmpeg, and the YouTube Data API.

**Key features:**

- Trend ingestion from Google Trends RSS and Google News RSS.
- Provider-neutral AI adapters for OpenAI, Anthropic, and OpenRouter.
- Encrypted per-user API keys and OAuth credentials at rest.
- 1080×1920 vertical video rendering with subtitles, narration, and stock assets.
- Responsive Bootstrap dashboard for trends, queue, calendar, and settings.
- Google OAuth 2.0, resumable YouTube uploads, scheduled publishing, and simulation mode.
- Three-service Docker runtime (web + renderer + scheduler) with shared SQLite and media volumes.

## What is included

- Public trend ingestion from Google Trends RSS and niche-focused YouTube/Shorts coverage through public Google News RSS, with normalization, scoring, tenant-aware deduplication, and source provenance.
- A provider-neutral AI interface with current connectors for OpenAI (`gpt-5.6-sol`), Anthropic (`claude-sonnet-4-6`), and OpenRouter (`openai/gpt-5.6-sol`).
- Per-user provider keys encrypted at rest. Plaintext keys are decrypted only when a provider request is created.
- A vertical 1080×1920 MoviePy/FFmpeg renderer with safe local/remote asset handling, optional free Pexels discovery, narration audio, Pillow-rendered timed subtitles, bounded duration/downloads, and deterministic clip cleanup.
- A responsive dark Bootstrap dashboard for overview metrics, active trends, script/video queue, provider settings, publishing channels, and a content calendar.
- Google OAuth 2.0 channel connection, resumable YouTube uploads, direct publish, scheduled publish, retry/backoff, stale-job recovery, and a clearly labeled offline simulation mode.
- A three-service Docker runtime: the web application, video renderer, and publication scheduler sharing persistent SQLite and media volumes.

## Architecture

| Area | Module | Responsibility |
| --- | --- | --- |
| Domain | `core/` | Custom user, trends, encrypted API keys, video projects |
| Ingestion | `trends/` | RSS adapters, normalization, scoring, persistence, AI dispatch |
| AI + video | `ai_studio/` | Provider adapters, content generation, stock assets, subtitles, rendering |
| CRM UI | `dashboard/` | Authenticated Bootstrap views, filters, queue, settings, calendar |
| Publishing | `publishing/` | OAuth, channels, schedules, YouTube upload, retry worker |
| Runtime | `tubepulse/`, `docker/` | Django settings/URLs, health check, startup, and containers |
| AI and video | `ai_studio/` | Provider adapters, content generation, stock assets, subtitles, rendering |
| CRM UI | `dashboard/` | Authenticated Bootstrap views, filters, queue, settings, calendar |
| Publishing | `publishing/` | OAuth, channels, schedules, YouTube upload, retry worker |
| Runtime | `tubepulse/`, `docker/` | Django settings/URLs, health check, startup and containers |

The canonical foreign-key graph is explicit:

- `Trend.user -> core.User` (nullable only for globally visible trends)
- `VideoProject.user -> core.User`
- `VideoProject.trend -> core.Trend` (`SET_NULL` preserves projects if a trend is removed)
- `APIKeyStore.user -> core.User`
- `PublishingChannel.user -> core.User`
- `ScheduledPublication.project -> core.VideoProject`
- `ScheduledPublication.channel -> publishing.PublishingChannel`

## Local setup

| Requirement | Version |
|-------------|---------|
| Python | 3.11+ (3.12 recommended) |
| FFmpeg | On `PATH` (system install recommended for production) |
| Docker + Compose | Optional, for containerized runtime |

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) and sign in with the superuser. The health endpoint is [http://127.0.0.1:8000/health/](http://127.0.0.1:8000/health/).

The `.env` file is loaded for local commands. Generate stable encryption keys before storing real credentials:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put that value in `TUBEPULSE_ENCRYPTION_KEY`. You can use a separate value for `PUBLISHING_CREDENTIAL_KEY`. Keep these values stable and backed up: changing them makes previously stored provider/OAuth credentials unreadable.

## Docker setup

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose exec web python manage.py createsuperuser
```

Then open [http://localhost:8000/](http://localhost:8000/). The `web` container serves Django through Gunicorn, `renderer` processes queued projects with bounded FFmpeg resources, and `scheduler` polls due publications every 30 seconds. Both workers shut down cleanly on `SIGTERM`/`SIGINT`. SQLite data and generated media live in named volumes.

For any deployment reachable by other machines, set `DJANGO_DEBUG=0`, a long random `DJANGO_SECRET_KEY`, correct `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`, secure cookie flags, and stable Fernet keys. Do not expose the development defaults publicly.

## Operating the workflow

### 1. Discover trends

Use **Active Trends → Scan niches**, or run:

```powershell
python manage.py ingest_trends --niche "AI tools" --niche "creator economy" --geo US --limit 20
```

To hand newly stored trends directly to the configured abstract AI pipeline, first save an AI key in **Settings → API Keys**, then associate the ingestion with that user:

```powershell
python manage.py ingest_trends --niche "AI tools" --geo US --user YOUR_USERNAME --dispatch-ai
```

The command reports source failures without discarding successful results. RSS calls use bounded connect/read timeouts and mocked-source tests do not require the internet.

### 2. Generate scripts

In **Active Trends**, choose **Create video**, select OpenAI, Anthropic, or OpenRouter, and submit. TubePulse creates a `VideoProject`, retrieves only that user's encrypted provider key, generates the narration and voice direction, then advances the project from `SCRIPTING` to `READY`. Missing, disabled, invalid, rate-limited, or unreachable provider credentials become safe queue errors instead of server crashes.

Pexels is an optional provider on the same settings screen. Its free API key allows the renderer to discover attributable portrait stock video/images. You can also use explicit local media files or validated public HTTPS asset URLs.

### 3. Render vertical video

The renderer accepts narration audio plus local/remote/Pexels assets, crops every background to exact 9:16, loops or trims clips to the narration duration, creates time-weighted subtitle cues from the script (or accepts explicit timings), and writes H.264/AAC MP4 with fast-start metadata. Use **Generation Queue → Queue render** to supply optional narration audio, background files, or public asset URLs. When no background is supplied, the worker uses the saved Pexels key and project title for stock discovery.

For a one-off CLI render, run:

```powershell
python manage.py render_video_project PROJECT_ID --audio narration.mp3 --asset background.mp4
```

For local operation without Docker, run the renderer in a second terminal:

```powershell
python manage.py process_video_queue --loop --interval 5 --batch-size 2
```

Rendering is atomic: output is built in a temporary directory, moved into media storage only after FFmpeg succeeds, and every MoviePy clip/reader is closed in reverse order on success or failure.

### 4. Connect and publish

Development defaults to explicit simulation mode. **Channels → Connect YouTube Sandbox** creates a local-only channel; it never contacts YouTube.

For real YouTube publishing:

1. Enable **YouTube Data API v3** in a Google Cloud project.
2. Create an OAuth 2.0 **Web application** client.
3. Add `http://localhost:8000/publishing/youtube/callback/` as an authorized redirect URI (or your HTTPS production URI).
4. Set `PUBLISHING_SIMULATION_MODE=0` and either:
   - set `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`, or
   - mount a client-secrets JSON file and set `YOUTUBE_CLIENT_SECRETS_FILE`.
5. Set `YOUTUBE_OAUTH_REDIRECT_URI` when the externally visible callback differs from Django's request URL.
6. Restart the services, open **Channels**, and complete Google consent.

Render a project, choose **Publish**, then publish immediately or select a future time. For local operation without Docker, run the scheduler in a second terminal:

```powershell
python manage.py process_scheduled_publications --loop --interval 30
```

For cron or Task Scheduler, omit `--loop`; one invocation processes one bounded batch.

## Validation

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test -v 2
python -m compileall -q .
```

Tests cover encrypted credentials, provider payload/error normalization, trend parsing and deduplication, tenant isolation, AI generation, URL/view behavior, lightweight FFmpeg rendering and cleanup, OAuth state replay defense, schedule ownership, simulation publishing, and bounded failures.

## Security and operational notes

- API keys and OAuth credential JSON are Fernet-encrypted; admin pages never expose ciphertext fields for editing.
- Every private query is scoped to the authenticated user. Only trends with `user=NULL` are globally visible.
- OAuth state is random, session-bound, time-limited, constant-time compared, and single-use.
- Remote stock URLs reject local/private/reserved IP ranges, validate every redirect, stream to size-limited temporary files, and close responses.
- Provider, RSS, Pexels, OAuth, revoke, and upload operations have finite timeouts/retry limits. Upload and scheduler loops are bounded or signal-stoppable.
- SQLite is configured with foreign keys, WAL mode, a busy timeout, and short transactions. It is suitable for this requested local/single-host deployment; do not run many independent web/scheduler replicas against the same SQLite file.
- Review stock licenses/attribution and factual claims before publication. TubePulse stores Pexels attribution metadata but cannot make editorial or legal approval decisions for you.

## Contributing

Contributions are welcome. Please open an issue first to discuss larger changes, and make sure tests pass before submitting a PR.

## License

This project is licensed under the MIT License — see [`LICENSE`](LICENSE) for details.

## Acknowledgments

Built with Django, MoviePy, FFmpeg, Bootstrap, and Pexels. AI provider integrations are independent of the respective providers and are not endorsed by them.
