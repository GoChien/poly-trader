import os
import asyncio
import datetime as dt
from typing import Optional, Tuple, Dict
from urllib.parse import urlsplit
from dataclasses import dataclass

import google.auth
from google.auth import impersonated_credentials
from google.auth.transport.requests import Request
from google.oauth2 import id_token as oauth2_id_token

# Refresh a bit early to avoid clock skew / in-flight requests using an expiring token.
_REFRESH_SKEW = dt.timedelta(minutes=2)

def _cloud_run_audience(url: str) -> str:
    """
    Cloud Run expects the audience to be the service hostname (scheme + netloc).
    Example: https://my-svc-abc-uc.a.run.app/
    """
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"Expected a full URL like https://..., got: {url!r}")
    return f"{parts.scheme}://{parts.netloc}/"

def _expiry_as_utc(expiry: Optional[dt.datetime]) -> Optional[dt.datetime]:
    if expiry is None:
        return None
    if expiry.tzinfo is None:
        return expiry.replace(tzinfo=dt.timezone.utc)
    return expiry.astimezone(dt.timezone.utc)


def _build_id_token_credentials(audience: str, impersonate_sa: Optional[str]):
    """
    Returns a Credentials object that can mint ID tokens for the given audience.
    - On Cloud Run (and other GCP runtimes), this uses the metadata server.
    - Locally, if metadata isn't available, it can impersonate a service account.
    """
    # 1) Preferred: environment-based (Cloud Run metadata server or SA key file).
    try:
        return oauth2_id_token.fetch_id_token_credentials(audience)
    except Exception:
        if not impersonate_sa:
            raise

    # 2) Local fallback: impersonate the target service account.
    source_creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )

    target_creds = impersonated_credentials.Credentials(
        source_credentials=source_creds,
        target_principal=impersonate_sa,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        lifetime=3600,
    )

    return impersonated_credentials.IDTokenCredentials(
        target_credentials=target_creds,
        target_audience=audience,
        include_email=True,
    )


@dataclass
class _CredEntry:
    creds: object
    lock: asyncio.Lock


# Cache is per (audience, impersonate_sa) because ID tokens are audience-bound.
_ID_TOKEN_CACHE: Dict[Tuple[str, Optional[str]], _CredEntry] = {}


async def get_id_token_cached(service_url: str) -> str:
    audience = _cloud_run_audience(service_url)
    impersonate_sa = os.getenv("CLOUD_RUN_INVOKER_SA")  # set locally; usually unset on Cloud Run
    key = (audience, impersonate_sa)

    entry = _ID_TOKEN_CACHE.get(key)
    if entry is None:
        entry = _CredEntry(
            creds=_build_id_token_credentials(audience, impersonate_sa),
            lock=asyncio.Lock(),
        )
        _ID_TOKEN_CACHE[key] = entry

    async with entry.lock:
        now = dt.datetime.now(dt.timezone.utc)

        token = getattr(entry.creds, "token", None)
        expiry = _expiry_as_utc(getattr(entry.creds, "expiry", None))

        # If we already have a token that isn't close to expiring, reuse it.
        if token and expiry and (expiry - now) > _REFRESH_SKEW:
            return token

        # Otherwise, refresh (blocking I/O -> run in a thread).
        await asyncio.to_thread(entry.creds.refresh, Request())
        return entry.creds.token

