"""Serve deployed static sites from extracted artifacts."""

from __future__ import annotations

import mimetypes
import re
import threading
import time
from pathlib import PurePosixPath

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.clickjacking import xframe_options_exempt

from .hosts import slug_from_host
from .models import App, Deployment, DeploymentStatus
from .services import is_preview_expired
from .storage import extracted_index_exists, open_extracted_file

# Missing assets with these extensions stay hard 404s (do not SPA-fallback to HTML).
_ASSET_EXTENSIONS = frozenset(
    {
        'js',
        'mjs',
        'cjs',
        'css',
        'map',
        'json',
        'svg',
        'png',
        'jpg',
        'jpeg',
        'gif',
        'webp',
        'ico',
        'woff',
        'woff2',
        'ttf',
        'otf',
        'eot',
        'txt',
        'xml',
        'wasm',
        'mp4',
        'webm',
        'mp3',
        'wav',
    }
)

# Vite/Rollup-style content hashes: main-D9ih21to.js, chunk-a1b2c3d4.css
_HASHED_FILENAME = re.compile(r'^.+-[A-Za-z0-9]{6,}\.[A-Za-z0-9]+$')

_SITE_MESSAGES = {
    'not_found': (
        'This site is unavailable',
        'No hosted app exists for this address. It may have been deleted, or the link may be incorrect.',
    ),
    'expired': (
        'This site has expired',
        'The preview for this address has expired and is no longer available. Deploy again to create a new site.',
    ),
    'unavailable': (
        'This site is unavailable',
        'Nothing is published at this address yet, or the deployment is no longer available.',
    ),
}

# In-process slug → App cache (no Redis). TTL 0 disables. Cleared on deploy finalize.
_serve_cache_lock = threading.Lock()
_serve_cache: dict[str, tuple[float, App]] = {}  # slug → (expires_monotonic, app)


def _serve_cache_ttl() -> float:
    try:
        return float(getattr(settings, 'HOSTING_SERVE_CACHE_TTL_SECONDS', 45) or 0)
    except (TypeError, ValueError):
        return 45.0


def invalidate_serve_cache(slug: str | None = None) -> None:
    """Drop cached serve lookups. Called after deploy finalize (and for tests)."""
    with _serve_cache_lock:
        if slug is None:
            _serve_cache.clear()
            return
        _serve_cache.pop(slug, None)


def _cache_get_app(slug: str) -> App | None:
    ttl = _serve_cache_ttl()
    if ttl <= 0:
        return None
    now = time.monotonic()
    with _serve_cache_lock:
        hit = _serve_cache.get(slug)
        if not hit:
            return None
        expires, app = hit
        if expires <= now:
            _serve_cache.pop(slug, None)
            return None
        return app


def _cache_set_app(slug: str, app: App) -> None:
    ttl = _serve_cache_ttl()
    if ttl <= 0:
        return
    with _serve_cache_lock:
        _serve_cache[slug] = (time.monotonic() + ttl, app)


def _load_app(slug: str) -> App | None:
    cached = _cache_get_app(slug)
    if cached is not None:
        return cached
    app = App.objects.select_related('current_deployment').filter(slug=slug).first()
    if app is not None:
        _cache_set_app(slug, app)
    return app


def _resolve_deployment(app: App) -> Deployment | None:
    deployment = app.current_deployment
    if deployment and deployment.status in {
        DeploymentStatus.ACTIVE,
        DeploymentStatus.READY,
        DeploymentStatus.SUPERSEDED,
    }:
        return deployment
    return None


def _looks_like_static_asset(relative_path: str) -> bool:
    name = PurePosixPath(relative_path).name
    if '.' not in name:
        return False
    ext = name.rsplit('.', 1)[-1].lower()
    return ext in _ASSET_EXTENSIONS


def _is_immutable_asset(relative_path: str) -> bool:
    """True for content-hashed static filenames (safe for long-lived cache)."""
    if not _looks_like_static_asset(relative_path):
        return False
    name = PurePosixPath(relative_path).name
    return bool(_HASHED_FILENAME.match(name))


def _cache_control_for(relative_path: str) -> str:
    if relative_path.endswith('.html'):
        return 'no-cache'
    if _is_immutable_asset(relative_path):
        return 'public, max-age=31536000, immutable'
    # Non-hashed static (favicon.svg, etc.): day-scale is enough and stays simple.
    return 'public, max-age=86400'


def _pick_file(deployment, path: str) -> tuple[str, object]:
    """
    Resolve a request path to an extracted file handle.

    Order:
    1. Exact file
    2. ``{path}/index.html`` (directory-style routes from the shellui build)
    3. ``404.html`` then ``index.html`` for SPA client-side routing refreshes

    Opens each candidate once (no exists-before-open). Returns ``(rel, handle)``.
    """
    rel = (path or '').lstrip('/')
    candidates: list[str] = []

    if not rel or rel.endswith('/'):
        candidates.append(f'{rel}index.html' if rel else 'index.html')
    else:
        candidates.append(rel)
        if not _looks_like_static_asset(rel):
            candidates.append(f'{rel.rstrip("/")}/index.html')

    if not (rel and _looks_like_static_asset(rel)):
        candidates.extend(['404.html', 'index.html'])

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        handle = open_extracted_file(deployment, candidate)
        if handle is not None:
            return candidate, handle
    raise Http404('File not found')


def _file_response(relative_path: str, handle) -> FileResponse:
    content_type, _ = mimetypes.guess_type(relative_path)
    response = FileResponse(handle, content_type=content_type or 'application/octet-stream')
    response['Cache-Control'] = _cache_control_for(relative_path)
    # Shellui Settings (and other shells) embed hosted apps in iframes.
    response.xframe_options_exempt = True
    response.headers.pop('X-Frame-Options', None)
    return response


def site_unavailable_response(request, *, reason: str = 'not_found'):
    """Friendly HTML 404 when a subdomain has no publishable site."""
    headline, message = _SITE_MESSAGES.get(reason, _SITE_MESSAGES['not_found'])
    host = (request.get_host() or '').split(':', 1)[0]
    response = render(
        request,
        'hosting/site_unavailable.html',
        {
            'headline': headline,
            'message': message,
            'host': host,
            'reason': reason,
        },
        status=404,
    )
    response['Cache-Control'] = 'no-cache'
    response.xframe_options_exempt = True
    response.headers.pop('X-Frame-Options', None)
    return response


@method_decorator(xframe_options_exempt, name='dispatch')
class AppServeView(View):
    """Serve hosted apps on any domain: {slug}.{any-domain}/"""

    def get(self, request, path=''):
        slug = slug_from_host(request.get_host())
        if not slug:
            return site_unavailable_response(request, reason='not_found')
        app = _load_app(slug)
        if app is None:
            return site_unavailable_response(request, reason='not_found')
        if is_preview_expired(app):
            return site_unavailable_response(request, reason='expired')
        deployment = _resolve_deployment(app)
        if deployment is None:
            return site_unavailable_response(request, reason='unavailable')

        rel_path = (path or '').lstrip('/')
        # Static assets: skip S3 HEAD on index.html; missing file stays hard 404.
        if rel_path and _looks_like_static_asset(rel_path):
            handle = open_extracted_file(deployment, rel_path)
            if handle is None:
                raise Http404('File not found')
            return _file_response(rel_path, handle)

        # HTML / SPA routes: ensure the deployment actually has an index once.
        if not extracted_index_exists(deployment):
            return site_unavailable_response(request, reason='unavailable')

        rel, handle = _pick_file(deployment, path)
        return _file_response(rel, handle)
