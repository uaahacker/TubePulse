import logging
import secrets
import time
import uuid
from datetime import timedelta
from pathlib import Path

import requests
import httplib2
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from core.models import VideoProject

from .models import PublishingChannel, ScheduledPublication

YOUTUBE_SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)
OAUTH_SESSION_KEY = "publishing.youtube_oauth_state"
logger = logging.getLogger(__name__)


class PublishingError(Exception):
    """A user-safe publishing failure."""


class YouTubeConfigurationError(PublishingError):
    """YouTube OAuth is not configured for this deployment."""


class OAuthStateError(PublishingError):
    """An OAuth callback could not be verified."""


class ChannelCredentialsError(PublishingError):
    """Stored credentials are absent, expired, or invalid."""


def simulation_mode_enabled():
    return bool(getattr(settings, "PUBLISHING_SIMULATION_MODE", False))


def _oauth_client_config():
    client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise YouTubeConfigurationError(
            "YouTube OAuth is not configured. Add the Google OAuth client ID and secret."
        )
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [],
        }
    }


def _redirect_uri(request):
    configured_uri = getattr(settings, "YOUTUBE_OAUTH_REDIRECT_URI", "").strip()
    return configured_uri or request.build_absolute_uri(
        reverse("publishing:youtube_callback")
    )


def _new_flow(request, *, state=None):
    client_secrets_file = getattr(settings, "YOUTUBE_CLIENT_SECRETS_FILE", "").strip()
    if client_secrets_file:
        secrets_path = Path(client_secrets_file).expanduser()
        if not secrets_path.is_file():
            raise YouTubeConfigurationError(
                "The configured Google OAuth client secrets file was not found."
            )
        try:
            flow = Flow.from_client_secrets_file(
                str(secrets_path),
                scopes=YOUTUBE_SCOPES,
                state=state,
            )
        except (OSError, ValueError) as exc:
            raise YouTubeConfigurationError(
                "The Google OAuth client secrets file is invalid."
            ) from exc
    else:
        flow = Flow.from_client_config(
            _oauth_client_config(),
            scopes=YOUTUBE_SCOPES,
            state=state,
        )
    flow.redirect_uri = _redirect_uri(request)
    return flow


def begin_youtube_oauth(request):
    state = secrets.token_urlsafe(32)
    request.session[OAUTH_SESSION_KEY] = {
        "value": state,
        "issued_at": int(time.time()),
    }
    request.session.modified = True
    flow = _new_flow(request, state=state)
    try:
        authorization_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return authorization_url
    finally:
        _close_oauth_flow(flow)


def _validate_oauth_state(request):
    expected = request.session.pop(OAUTH_SESSION_KEY, None)
    request.session.modified = True
    received = request.GET.get("state", "")
    if not expected or not received:
        raise OAuthStateError("The YouTube connection request expired. Please try again.")
    expected_value = str(expected.get("value", ""))
    issued_at = int(expected.get("issued_at", 0))
    max_age = int(getattr(settings, "YOUTUBE_OAUTH_STATE_MAX_AGE", 600))
    if not secrets.compare_digest(expected_value, received):
        raise OAuthStateError("The YouTube connection could not be verified.")
    if issued_at <= 0 or time.time() - issued_at > max_age:
        raise OAuthStateError("The YouTube connection request expired. Please try again.")
    return received


def credentials_to_payload(credentials):
    return {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes or YOUTUBE_SCOPES),
        "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
    }


def credentials_from_payload(payload):
    credentials = Credentials(
        token=payload.get("token"),
        refresh_token=payload.get("refresh_token"),
        token_uri=payload.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=payload.get("client_id"),
        client_secret=payload.get("client_secret"),
        scopes=payload.get("scopes") or list(YOUTUBE_SCOPES),
    )
    if payload.get("expiry"):
        credentials.expiry = parse_datetime(payload["expiry"])
    return credentials


def _youtube_client(credentials):
    timeout = int(getattr(settings, "TUBEPULSE_HTTP_TIMEOUT", 20))
    http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=timeout))
    return build("youtube", "v3", http=http, cache_discovery=False)


def _close_youtube_client(client):
    if client is None:
        return
    try:
        client.close()
    except Exception:
        logger.warning("Could not close a YouTube API client cleanly.", exc_info=True)


def _close_oauth_flow(flow):
    session = getattr(flow, "oauth2session", None)
    close = getattr(session, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            logger.warning("Could not close an OAuth session cleanly.", exc_info=True)


def complete_youtube_oauth(request):
    state = _validate_oauth_state(request)
    if request.GET.get("error"):
        raise PublishingError("YouTube authorization was declined or cancelled.")

    flow = _new_flow(request, state=state)
    youtube = None
    try:
        flow.fetch_token(
            authorization_response=request.build_absolute_uri(),
            timeout=int(getattr(settings, "TUBEPULSE_HTTP_TIMEOUT", 20)),
        )
        credentials = flow.credentials
        youtube = _youtube_client(credentials)
        response = youtube.channels().list(part="snippet", mine=True, maxResults=1).execute()
    except Exception as exc:
        raise PublishingError("YouTube authorization could not be completed.") from exc
    finally:
        _close_youtube_client(youtube)
        _close_oauth_flow(flow)

    items = response.get("items", [])
    if not items:
        raise PublishingError("No YouTube channel is available for this Google account.")
    item = items[0]
    snippet = item.get("snippet", {})
    thumbnails = snippet.get("thumbnails", {})
    thumbnail = (
        thumbnails.get("default", {}).get("url")
        or thumbnails.get("medium", {}).get("url")
        or ""
    )

    channel, _ = PublishingChannel.objects.get_or_create(
        user=request.user,
        provider=PublishingChannel.Provider.YOUTUBE,
        channel_id=item["id"],
        defaults={"channel_title": snippet.get("title") or "YouTube channel"},
    )
    payload = credentials_to_payload(credentials)
    if not payload.get("refresh_token") and channel.credentials_blob:
        try:
            previous_payload = channel.get_credentials() or {}
        except ValidationError:
            previous_payload = {}
        payload["refresh_token"] = previous_payload.get("refresh_token")
    channel.channel_title = snippet.get("title") or channel.channel_title
    channel.channel_thumbnail_url = thumbnail
    channel.is_active = True
    channel.last_connected_at = timezone.now()
    channel.set_credentials(payload)
    channel.save()
    return channel


def connect_simulated_channel(user):
    channel, _ = PublishingChannel.objects.get_or_create(
        user=user,
        provider=PublishingChannel.Provider.YOUTUBE,
        channel_id=f"simulation-{user.pk}",
        defaults={"channel_title": "YouTube Sandbox"},
    )
    channel.channel_title = "YouTube Sandbox"
    channel.is_active = True
    channel.last_connected_at = timezone.now()
    channel.clear_credentials()
    channel.save()
    return channel


def credentials_for_channel(channel):
    try:
        payload = channel.get_credentials()
    except ValidationError as exc:
        raise ChannelCredentialsError(str(exc)) from exc
    if not payload:
        raise ChannelCredentialsError("Reconnect this YouTube channel before publishing.")
    credentials = credentials_from_payload(payload)
    if credentials.expired or not credentials.valid:
        if not credentials.refresh_token:
            raise ChannelCredentialsError("YouTube access expired. Reconnect the channel.")
        try:
            with requests.Session() as session:
                credentials.refresh(GoogleAuthRequest(session=session))
        except Exception as exc:
            raise ChannelCredentialsError(
                "YouTube access could not be refreshed. Reconnect the channel."
            ) from exc
        channel.set_credentials(credentials_to_payload(credentials))
        channel.save(
            update_fields=(
                "credentials_blob",
                "token_expiry",
                "scopes",
                "updated_at",
            )
        )
    return credentials


def revoke_channel_access(channel):
    if simulation_mode_enabled() or not channel.credentials_blob:
        return True
    try:
        credentials = credentials_from_payload(channel.get_credentials())
        token = credentials.refresh_token or credentials.token
        if not token:
            return True
        with requests.post(
            "https://oauth2.googleapis.com/revoke",
            data={"token": token},
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=int(getattr(settings, "TUBEPULSE_HTTP_TIMEOUT", 20)),
        ) as response:
            return response.status_code in {200, 400}
    except (requests.RequestException, ValidationError, ValueError):
        return False


def _project_video_path(project):
    video_file = project.video_file
    if not video_file:
        raise PublishingError("This project does not have a rendered video yet.")
    try:
        path = Path(video_file.path)
    except (NotImplementedError, ValueError) as exc:
        raise PublishingError("The rendered video is not available on local storage.") from exc
    if not path.is_file() or path.stat().st_size == 0:
        raise PublishingError("The rendered video file is missing or empty.")
    return path


def _upload_youtube_video(publication, credentials, video_path):
    youtube = _youtube_client(credentials)
    media = None
    try:
        body = {
            "snippet": {
                "title": publication.title,
                "description": publication.description,
                "tags": publication.tags,
                "categoryId": str(getattr(settings, "YOUTUBE_CATEGORY_ID", "22")),
            },
            "status": {
                "privacyStatus": publication.privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }
        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            chunksize=int(
                getattr(settings, "YOUTUBE_UPLOAD_CHUNK_SIZE", 8 * 1024 * 1024)
            ),
            resumable=True,
        )
        insert_request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
            notifySubscribers=False,
        )
        response = None
        chunk_count = 0
        max_chunks = int(getattr(settings, "YOUTUBE_UPLOAD_MAX_CHUNKS", 10000))
        while response is None:
            _, response = insert_request.next_chunk(num_retries=3)
            chunk_count += 1
            if chunk_count > max_chunks:
                raise PublishingError("YouTube upload exceeded its safe chunk limit.")
        video_id = response.get("id")
        if not video_id:
            raise PublishingError("YouTube did not return a video ID after upload.")
        return video_id
    except HttpError as exc:
        status = getattr(exc.resp, "status", "unknown")
        raise PublishingError(f"YouTube rejected the upload (HTTP {status}).") from exc
    finally:
        file_handle = getattr(media, "_fd", None) if media is not None else None
        if file_handle is not None and not file_handle.closed:
            file_handle.close()
        _close_youtube_client(youtube)


def _claim_publication(publication_id, *, force=False):
    now = timezone.now()
    queryset = ScheduledPublication.objects.filter(
        pk=publication_id,
        status__in=[ScheduledPublication.Status.PENDING, ScheduledPublication.Status.RETRY],
    )
    if not force:
        queryset = queryset.filter(scheduled_for__lte=now).filter(
            Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)
        )
    claimed = queryset.update(
        status=ScheduledPublication.Status.PROCESSING,
        error_message="",
        attempt_count=F("attempt_count") + 1,
        updated_at=now,
    )
    if not claimed:
        raise PublishingError("This publication is not ready to be processed.")
    return ScheduledPublication.objects.select_related("project", "channel").get(
        pk=publication_id
    )


def _record_failure(publication, exc):
    max_attempts = int(getattr(settings, "PUBLISHING_MAX_ATTEMPTS", 3))
    now = timezone.now()
    if publication.attempt_count < max_attempts:
        status = ScheduledPublication.Status.RETRY
        delay = min(15 * (2 ** max(publication.attempt_count - 1, 0)), 240)
        next_attempt = now + timedelta(minutes=delay)
    else:
        status = ScheduledPublication.Status.FAILED
        next_attempt = None
    ScheduledPublication.objects.filter(pk=publication.pk).update(
        status=status,
        error_message=str(exc)[:2000],
        next_attempt_at=next_attempt,
        updated_at=now,
    )


def publish_scheduled_publication(publication, *, force=False):
    claimed = _claim_publication(publication.pk, force=force)
    try:
        video_path = _project_video_path(claimed.project)
        if simulation_mode_enabled():
            video_id = f"sim-{uuid.uuid4().hex[:16]}"
            publication_url = f"https://www.youtube.com/watch?v={video_id}"
        else:
            if not claimed.channel.is_active:
                raise ChannelCredentialsError("Reconnect this channel before publishing.")
            credentials = credentials_for_channel(claimed.channel)
            video_id = _upload_youtube_video(claimed, credentials, video_path)
            publication_url = f"https://www.youtube.com/watch?v={video_id}"

        now = timezone.now()
        ScheduledPublication.objects.filter(pk=claimed.pk).update(
            status=ScheduledPublication.Status.PUBLISHED,
            youtube_video_id=video_id,
            publication_url=publication_url,
            error_message="",
            next_attempt_at=None,
            published_at=now,
            updated_at=now,
        )
        project_updates = {
            "publication_url": publication_url,
            "published_at": now,
            "updated_at": now,
        }
        published_status = getattr(getattr(VideoProject, "Status", None), "PUBLISHED", None)
        if published_status:
            project_updates["status"] = published_status
        VideoProject.objects.filter(pk=claimed.project_id).update(**project_updates)
        claimed.refresh_from_db()
        return claimed
    except Exception as exc:
        error = exc if isinstance(exc, PublishingError) else PublishingError(
            "The publishing provider returned an unexpected error."
        )
        _record_failure(claimed, error)
        raise error from exc


def due_publication_ids(limit=25):
    now = timezone.now()
    return list(
        ScheduledPublication.objects.filter(scheduled_for__lte=now)
        .filter(
            Q(status=ScheduledPublication.Status.PENDING)
            | Q(
                status=ScheduledPublication.Status.RETRY,
                next_attempt_at__lte=now,
            )
        )
        .order_by("scheduled_for", "pk")
        .values_list("pk", flat=True)[:limit]
    )


def recover_stale_publications():
    stale_after = int(getattr(settings, "PUBLISHING_STALE_MINUTES", 90))
    cutoff = timezone.now() - timedelta(minutes=stale_after)
    return ScheduledPublication.objects.filter(
        status=ScheduledPublication.Status.PROCESSING,
        updated_at__lt=cutoff,
    ).update(
        status=ScheduledPublication.Status.RETRY,
        next_attempt_at=timezone.now(),
        error_message="A stalled upload was recovered and queued for retry.",
        updated_at=timezone.now(),
    )
