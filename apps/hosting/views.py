"""Hosting REST views under /hosting/v1/."""

from __future__ import annotations

import logging

from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.parsers import BaseParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authapi.permissions import IsAuthenticatedPrincipal, IsStaffOrCompanyOwner

from .models import Deployment
from .serializers import (
    AccessSerializer,
    AccessUpdateSerializer,
    AppCreateSerializer,
    AppSerializer,
    DeploymentCreateSerializer,
    DeploymentSerializer,
    ErrorSerializer,
    HealthSerializer,
    PreviewPrepareResponseSerializer,
    PreviewPrepareSerializer,
)
from .services import (
    HostingError,
    create_app,
    create_deployment,
    finalize_deployment,
    get_access,
    request_access,
    prepare_preview_deploy,
    renew_app_expiry,
    require_company_id,
    resolve_app_ref,
    rollback_deployment,
    delete_app,
    serialize_access,
    serialize_app,
    serialize_deployment,
    update_access,
    upload_deployment_artifact,
)
from .stats import build_hosting_stats

logger = logging.getLogger(__name__)

_SCHEMA_ERRORS = {
    400: ErrorSerializer,
    401: ErrorSerializer,
    403: ErrorSerializer,
    404: ErrorSerializer,
    409: ErrorSerializer,
}


class OctetStreamParser(BaseParser):
    media_type = 'application/octet-stream'

    def parse(self, stream, media_type=None, parser_context=None):
        return stream


class GzipParser(BaseParser):
    media_type = 'application/gzip'

    def parse(self, stream, media_type=None, parser_context=None):
        return stream


def _error(exc: HostingError) -> Response:
    if exc.status >= 500:
        logger.error('Hosting error %s (%s): %s', exc.status, exc.code, exc)
    return Response(
        {'statusCode': str(exc.status), 'error': exc.code, 'message': str(exc)},
        status=exc.status,
    )


def _error_message(message: str, *, status_code: int = 400, code: str = 'Error') -> Response:
    return Response(
        {'statusCode': str(status_code), 'error': code, 'message': message},
        status=status_code,
    )


class HealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(tags=['health'], responses={200: HealthSerializer})
    def get(self, request):
        return Response(
            {
                'status': 'ok',
                'version': settings.VERSION,
                'hosting_backend': settings.HOSTING_BACKEND,
                'identity_jwks_source': settings.IDENTITY_JWKS_SOURCE or 'url',
                'identity_jwks_url': settings.IDENTITY_JWKS_URL,
            }
        )


@extend_schema_view(
    get=extend_schema(
        tags=['access'],
        summary='Get company hosting access status',
        responses={200: AccessSerializer, **_SCHEMA_ERRORS},
    ),
    post=extend_schema(
        tags=['access'],
        summary='Update company hosting access (staff or company owner)',
        request=AccessUpdateSerializer,
        responses={200: AccessSerializer, **_SCHEMA_ERRORS},
    ),
)
class AccessView(APIView):
    permission_classes = [IsAuthenticatedPrincipal, IsStaffOrCompanyOwner]

    def get(self, request):
        try:
            company_id = require_company_id(request.user)
        except HostingError as exc:
            return _error(exc)
        record = get_access(company_id)
        return Response(serialize_access(record, company_id=company_id))

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        target_company = data.get('company_id')
        if request.user.is_staff and target_company not in (None, ''):
            company_id = int(target_company)
        else:
            try:
                company_id = require_company_id(request.user)
            except HostingError as exc:
                return _error(exc)
            if not request.user.is_staff and not request.user.is_company_owner:
                return _error_message('Forbidden', status_code=403, code='forbidden')
        try:
            record = update_access(
                company_id=company_id,
                status=str(data.get('status') or '').strip(),
                reviewer_id=request.user.user_id,
                notes=str(data.get('notes') or ''),
            )
        except HostingError as exc:
            return _error(exc)
        return Response(serialize_access(record, company_id=company_id))


class AccessRequestView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    @extend_schema(
        tags=['access'],
        summary='Request hosting access for your company',
        request=None,
        responses={201: AccessSerializer, **_SCHEMA_ERRORS},
    )
    def post(self, request):
        try:
            company_id = require_company_id(request.user)
            record = request_access(company_id=company_id, user_id=request.user.user_id)
        except HostingError as exc:
            return _error(exc)
        return Response(serialize_access(record, company_id=company_id), status=status.HTTP_201_CREATED)


class PreviewPrepareView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    @extend_schema(
        tags=['preview'],
        summary='Prepare a preview deploy (new slug or redeploy to an owned slug)',
        request=PreviewPrepareSerializer,
        responses={201: PreviewPrepareResponseSerializer, **_SCHEMA_ERRORS},
    )
    def post(self, request):
        try:
            company_id = require_company_id(request.user)
            data = request.data if isinstance(request.data, dict) else {}
            app, deployment = prepare_preview_deploy(
                company_id=company_id,
                user_id=request.user.user_id,
                slug=str(data.get('slug') or '').strip() or None,
                display_name=str(data.get('display_name') or ''),
                app_version=str(data.get('app_version') or ''),
                shellui_version=str(data.get('shellui_version') or ''),
            )
        except HostingError as exc:
            return _error(exc)
        except ValueError as exc:
            return _error_message(str(exc))

        app_payload = serialize_app(app)
        deployment_payload = serialize_deployment(deployment, app_slug=app.slug)
        urls = app_payload.get('urls') or deployment_payload.get('urls') or {}
        return Response(
            {
                'app': app_payload,
                'deployment': deployment_payload,
                'slug': app.slug,
                'expires_at': app_payload.get('expires_at'),
                'urls': urls,
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    get=extend_schema(
        tags=['apps'],
        summary='List hosted apps for your company',
        responses={200: AppSerializer(many=True), **_SCHEMA_ERRORS},
    ),
    post=extend_schema(
        tags=['apps'],
        summary='Create a hosted app',
        request=AppCreateSerializer,
        responses={201: AppSerializer, **_SCHEMA_ERRORS},
    ),
)
class AppListCreateView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    def get(self, request):
        try:
            company_id = require_company_id(request.user)
        except HostingError as exc:
            return _error(exc)
        from .models import App

        apps = App.objects.filter(company_id=company_id).order_by('name')
        return Response([serialize_app(app) for app in apps])

    def post(self, request):
        try:
            company_id = require_company_id(request.user)
            data = request.data if isinstance(request.data, dict) else {}
            app = create_app(
                company_id=company_id,
                name=str(data.get('name') or data.get('slug') or ''),
                display_name=str(data.get('display_name') or ''),
            )
        except HostingError as exc:
            return _error(exc)
        except ValueError as exc:
            return _error_message(str(exc))
        return Response(serialize_app(app), status=status.HTTP_201_CREATED)


class AppDetailView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    @extend_schema(
        tags=['apps'],
        summary='Get app by name or UUID',
        responses={200: AppSerializer, **_SCHEMA_ERRORS},
    )
    def get(self, request, app_ref):
        try:
            company_id = require_company_id(request.user)
            app = resolve_app_ref(app_ref, company_id=company_id)
        except HostingError as exc:
            return _error(exc)
        return Response(serialize_app(app))

    @extend_schema(
        tags=['apps'],
        summary='Delete a hosted app and its deployments',
        responses={204: None, **_SCHEMA_ERRORS},
    )
    def delete(self, request, app_ref):
        try:
            company_id = require_company_id(request.user)
            app = resolve_app_ref(app_ref, company_id=company_id)
            delete_app(app)
        except HostingError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AppRenewExpiryView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    @extend_schema(
        tags=['apps'],
        summary='Reset preview site expiry (extends TTL by HOSTING_PREVIEW_TTL_DAYS)',
        request=None,
        responses={200: AppSerializer, **_SCHEMA_ERRORS},
    )
    def post(self, request, app_ref):
        try:
            company_id = require_company_id(request.user)
            app = resolve_app_ref(app_ref, company_id=company_id)
            app = renew_app_expiry(app)
        except HostingError as exc:
            return _error(exc)
        return Response(serialize_app(app))


@extend_schema_view(
    get=extend_schema(
        tags=['deployments'],
        summary='List deployments for an app',
        responses={200: DeploymentSerializer(many=True), **_SCHEMA_ERRORS},
    ),
    post=extend_schema(
        tags=['deployments'],
        summary='Create a draft deployment',
        request=DeploymentCreateSerializer,
        responses={201: DeploymentSerializer, **_SCHEMA_ERRORS},
    ),
)
class DeploymentListCreateView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    def get(self, request, app_ref):
        try:
            company_id = require_company_id(request.user)
            app = resolve_app_ref(app_ref, company_id=company_id)
        except HostingError as exc:
            return _error(exc)
        deployments = app.deployments.all()
        return Response([serialize_deployment(d) for d in deployments])

    def post(self, request, app_ref):
        try:
            company_id = require_company_id(request.user)
            app = resolve_app_ref(app_ref, company_id=company_id)
            data = request.data if isinstance(request.data, dict) else {}
            deployment = create_deployment(
                app=app,
                app_version=str(data.get('app_version') or ''),
                shellui_version=str(data.get('shellui_version') or ''),
                deployed_by_id=request.user.user_id,
                pinned=bool(data.get('pinned', False)),
            )
        except HostingError as exc:
            return _error(exc)
        except ValueError as exc:
            return _error_message(str(exc))
        return Response(serialize_deployment(deployment), status=status.HTTP_201_CREATED)


class DeploymentUploadView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]
    parser_classes = [MultiPartParser, OctetStreamParser, GzipParser]

    @extend_schema(
        tags=['deployments'],
        summary='Upload deployment artifact (tar.gz)',
        request={'application/gzip': {'type': 'string', 'format': 'binary'}},
        responses={200: DeploymentSerializer, **_SCHEMA_ERRORS},
    )
    def put(self, request, app_ref, deployment_id):
        try:
            company_id = require_company_id(request.user)
            app = resolve_app_ref(app_ref, company_id=company_id)
            deployment = Deployment.objects.get(id=deployment_id, app=app)
        except Deployment.DoesNotExist:
            return _error_message('Deployment not found.', status_code=404, code='deployment_not_found')
        except HostingError as exc:
            return _error(exc)

        fileobj = None
        if request.FILES:
            fileobj = request.FILES.get('file') or next(iter(request.FILES.values()), None)
        if fileobj is None:
            if hasattr(request.data, 'read'):
                fileobj = request.data
            else:
                from io import BytesIO

                fileobj = BytesIO(request.body)

        content_length = getattr(fileobj, 'size', None) or len(getattr(request, 'body', b'') or b'')
        try:
            deployment = upload_deployment_artifact(
                deployment=deployment,
                fileobj=fileobj,
                content_length=content_length,
            )
        except HostingError as exc:
            return _error(exc)
        except ValueError as exc:
            return _error_message(str(exc))
        return Response(serialize_deployment(deployment))


class DeploymentFinalizeView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    @extend_schema(
        tags=['deployments'],
        summary='Finalize and activate a deployment',
        request=None,
        responses={200: DeploymentSerializer, **_SCHEMA_ERRORS},
    )
    def post(self, request, app_ref, deployment_id):
        try:
            company_id = require_company_id(request.user)
            app = resolve_app_ref(app_ref, company_id=company_id)
            deployment = Deployment.objects.get(id=deployment_id, app=app)
            deployment = finalize_deployment(deployment=deployment)
            deployment.refresh_from_db()
            deployment.app.refresh_from_db()
        except Deployment.DoesNotExist:
            return _error_message('Deployment not found.', status_code=404, code='deployment_not_found')
        except HostingError as exc:
            return _error(exc)
        return Response(serialize_deployment(deployment))


class DeploymentRollbackView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    @extend_schema(
        tags=['deployments'],
        summary='Rollback to a previous deployment',
        request=None,
        responses={200: DeploymentSerializer, **_SCHEMA_ERRORS},
    )
    def post(self, request, app_ref, deployment_id):
        try:
            company_id = require_company_id(request.user)
            app = resolve_app_ref(app_ref, company_id=company_id)
            deployment = Deployment.objects.get(id=deployment_id, app=app)
            deployment = rollback_deployment(deployment=deployment)
        except Deployment.DoesNotExist:
            return _error_message('Deployment not found.', status_code=404, code='deployment_not_found')
        except HostingError as exc:
            return _error(exc)
        return Response(serialize_deployment(deployment))


class StatsView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    @extend_schema(tags=['stats'], responses={200: OpenApiTypes.OBJECT, **_SCHEMA_ERRORS})
    def get(self, request):
        company_id = None
        if not getattr(request.user, 'is_staff', False):
            try:
                company_id = require_company_id(request.user)
            except HostingError as exc:
                return _error(exc)
        return Response(build_hosting_stats(company_id=company_id))
