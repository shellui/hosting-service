"""Serve deployed static sites from extracted artifacts."""

from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath

from django.http import FileResponse, Http404
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


def _pick_file(deployment, path: str) -> str:
    """
    Resolve a request path to an extracted file.

    Order:
    1. Exact file
    2. ``{path}/index.html`` (directory-style routes from the shellui build)
    3. ``404.html`` then ``index.html`` for SPA client-side routing refreshes
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
        if open_extracted_file(deployment, candidate) is not None:
            return candidate
    raise Http404('File not found')


def _file_response(deployment, relative_path: str) -> FileResponse:
    handle = open_extracted_file(deployment, relative_path)
    if handle is None:
        raise Http404('File not found')
    content_type, _ = mimetypes.guess_type(relative_path)
    response = FileResponse(handle, content_type=content_type or 'application/octet-stream')
    if relative_path.endswith('.html'):
        response['Cache-Control'] = 'no-cache'
    else:
        response['Cache-Control'] = 'public, max-age=3600'
    # Shellui Settings (and other shells) embed hosted apps in iframes.
    response.xframe_options_exempt = True
    response.headers.pop('X-Frame-Options', None)
    return response


@method_decorator(xframe_options_exempt, name='dispatch')
class AppServeView(View):
    """Serve hosted apps on any domain: {slug}.{any-domain}/"""

    def get(self, request, path=''):
        slug = slug_from_host(request.get_host())
        if not slug:
            raise Http404('Unknown host')
        app = App.objects.filter(slug=slug).first()
        if app is None:
            raise Http404('App not found')
        if is_preview_expired(app):
            raise Http404('Preview site expired')
        deployment = _resolve_deployment(app)
        if deployment is None or not extracted_index_exists(deployment):
            raise Http404('No active deployment')
        rel = _pick_file(deployment, path)
        return _file_response(deployment, rel)
