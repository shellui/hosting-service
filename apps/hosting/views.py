"""Hosting REST views under /hosting/v1/."""

from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.parsers import BaseParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authapi.mcp_openapi import mcp_tool
from apps.authapi.permissions import IsAuthenticatedPrincipal, IsStaffOrCompanyOwner
from apps.hosting.openapi_admin import (
    ADMIN_API_ERRORS,
    APP_REF_PATH,
    DEPLOYMENT_ID_PATH,
    DOMAIN_ID_PATH,
    ENV_KEY_PATH,
    TOKEN_ID_PATH,
    admin_description,
    mcp_openapi_fields,
    EXAMPLE_APP,
)
from config.throttling import HostingScopeThrottle

from . import metrics as hosting_metrics
from .models import AccessStatus, Deployment
from .renderers import PrometheusTextRenderer
from .serializers import (
    AccessSerializer,
    AccessUpdateSerializer,
    AppCreateSerializer,
    AppSerializer,
    ArtifactUploadUrlResponseSerializer,
    DeploymentCreateSerializer,
    DeploymentSerializer,
    DeployTokenCreateResponseSerializer,
    DeployTokenSerializer,
    ErrorSerializer,
    HealthSerializer,
    PreviewPrepareResponseSerializer,
    PreviewPrepareSerializer,
    CustomDomainSerializer,
    CustomDomainCreateSerializer,
    EnvVariableListSerializer,
    EnvVariableUpsertSerializer,
    EnvVariableValueSerializer,
    EnvVariableKeySerializer,
    RequestLogListResponseSerializer,
    RuntimeLogResponseSerializer,
)
from .deploy_tokens import create_deploy_token, revoke_deploy_token, serialize_deploy_token
from .models import DeployToken
from .services import (
    HostingError,
    assert_deploy_token_preview,
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
    confirm_deployment_artifact_upload,
    upload_deployment_artifact,
)
from .stats import build_hosting_stats
from .storage import ArtifactTooLarge, build_artifact_upload_target
from .operational import (
    add_custom_domain,
    delete_env_variable,
    get_custom_domain,
    get_env_variable,
    list_app_request_logs,
    list_app_runtime_logs,
    list_custom_domains,
    list_env_variables,
    refresh_custom_domain,
    remove_custom_domain,
    set_env_variable,
)

logger = logging.getLogger(__name__)

_API_ERRORS = ADMIN_API_ERRORS


class OctetStreamParser(BaseParser):
    media_type = 'application/octet-stream'

    def parse(self, stream, media_type=None, parser_context=None):
        return stream


class GzipParser(BaseParser):
    media_type = 'application/gzip'

    def parse(self, stream, media_type=None, parser_context=None):
        return stream


class EmptyBodyParser(BaseParser):
    """Accept MCP ``tools/call`` POST bodies that use ``application/octet-stream`` with no payload."""

    media_type = '*/*'

    def parse(self, stream, media_type=None, parser_context=None):
        return {}


def _error(exc: HostingError) -> Response:
    if exc.status >= 500:
        logger.error('Hosting error %s (%s): %s', exc.status, exc.code, exc)
    return Response(
        {'statusCode': str(exc.status), 'error': exc.code, 'message': str(exc)},
        status=exc.status,
    )


def _mb(size: int) -> str:
    return f'{size / 1024**2:.1f}'.rstrip('0').rstrip('.')


def _too_large(size: int | None, max_bytes: int) -> Response:
    limit = _mb(max_bytes)
    detail = f'Artifact is {_mb(size)} MB, the limit is {limit} MB.' if size else f'Artifact is over the {limit} MB limit.'
    return Response(
        {'statusCode': '413', 'error': 'upload_too_large', 'message': detail, 'detail': detail, 'limit_bytes': max_bytes},
        status=413,
    )


def _oauth_redirect_api(record) -> dict:
    sync = getattr(record, 'oauth_redirect_sync', None)
    if sync is None or not hasattr(sync, 'as_api'):
        return {}
    return sync.as_api()


def _scoped_app(request, app_ref):
    """Resolve an app in the caller's company; deploy tokens only reach preview sites."""
    app = resolve_app_ref(app_ref, company_id=require_company_id(request.user))
    assert_deploy_token_preview(request.user, app)
    return app


def _owner_app(request, app_ref):
    """Company-scoped app for owner routes. Deploy tokens cannot call operational APIs."""
    if getattr(request.user, 'deploy_token_id', None):
        return None, _error_message('Operational APIs require a user or agent JWT.', status_code=403, code='forbidden')
    try:
        company_id = require_company_id(request.user)
        app = resolve_app_ref(app_ref, company_id=company_id)
    except HostingError as exc:
        return None, _error(exc)
    return app, None


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
        operation_id='hosting_v1_access_retrieve',
        summary='Read company hosting access status',
        description=admin_description(
            lead='Returns waitlist status (`pending`, `approved`, or `denied`) for the target company.',
            side_effects='Read-only.',
        ),
        responses={200: AccessSerializer, **_API_ERRORS},
    ),
    post=extend_schema(
        tags=['access'],
        operation_id='hosting_v1_access_create',
        summary='Update hosting access (staff approve or deny)',
        description=admin_description(
            lead='Staff set `approved` or `denied`. Company owners may update notes only; they cannot self-approve.',
            side_effects='Updates hosting access row and reviewer metadata.',
            notes='Pass `company_id` in the body when staff act on another company.',
        ),
        request=AccessUpdateSerializer,
        responses={200: AccessSerializer, **_API_ERRORS},
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
        status_value = str(data.get('status') or '').strip()
        if status_value in {AccessStatus.APPROVED, AccessStatus.DENIED} and not request.user.is_staff:
            return _error_message(
                'Only staff can approve or deny hosting access.',
                status_code=403,
                code='forbidden',
            )
        try:
            record = update_access(
                company_id=company_id,
                status=status_value,
                reviewer_id=request.user.user_id,
                notes=str(data.get('notes') or ''),
            )
        except HostingError as exc:
            return _error(exc)
        return Response(serialize_access(record, company_id=company_id))


class AccessRequestView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]
    rate_limit_scope = 'access_request'
    throttle_classes = [HostingScopeThrottle]

    @extend_schema(
        tags=['access'],
        operation_id='hosting_v1_access_request_create',
        request=None,
        responses={201: AccessSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_access_request_create'),
        **mcp_tool(operation_id='hosting_v1_access_request_create', read_only=False),
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
    deploy_token_methods = ('POST',)
    rate_limit_scope = 'deploy'
    throttle_classes = [HostingScopeThrottle]

    @extend_schema(
        tags=['previews'],
        operation_id='hosting_v1_preview_create',
        request=PreviewPrepareSerializer,
        responses={201: PreviewPrepareResponseSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_preview_create'),
        **mcp_tool(operation_id='hosting_v1_preview_create', read_only=False),
    )
    def post(self, request):
        try:
            company_id = require_company_id(request.user)
            data = request.data if isinstance(request.data, dict) else {}
            access_token = request.auth if isinstance(request.auth, str) else None
            app, deployment = prepare_preview_deploy(
                company_id=company_id,
                user_id=request.user.user_id,
                slug=str(data.get('slug') or '').strip() or None,
                display_name=str(data.get('display_name') or ''),
                app_version=str(data.get('app_version') or ''),
                shellui_version=str(data.get('shellui_version') or ''),
                access_token=access_token,
                actor_email=request.user.email,
                any_user=bool(request.user.deploy_token_id),
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
                **_oauth_redirect_api(app),
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    get=extend_schema(
        tags=['sites'],
        operation_id='hosting_v1_apps_list',
        responses={200: AppSerializer(many=True), **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_list'),
        **mcp_tool(operation_id='hosting_v1_apps_list', read_only=True),
    ),
    post=extend_schema(
        tags=['sites'],
        operation_id='hosting_v1_apps_create',
        request=AppCreateSerializer,
        responses={201: AppSerializer, **_API_ERRORS},
        examples=[EXAMPLE_APP],
        **mcp_openapi_fields('hosting_v1_apps_create'),
        **mcp_tool(operation_id='hosting_v1_apps_create', read_only=False),
    ),
)
class AppListCreateView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]
    rate_limit_scope = 'deploy'

    def get_throttles(self):
        if self.request.method == 'POST':
            return [HostingScopeThrottle()]
        return []

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
            access_token = request.auth if isinstance(request.auth, str) else None
            app = create_app(
                company_id=company_id,
                name=str(data.get('name') or data.get('slug') or ''),
                display_name=str(data.get('display_name') or ''),
                access_token=access_token,
                user_id=request.user.user_id,
                actor_email=request.user.email,
            )
        except HostingError as exc:
            return _error(exc)
        except ValueError as exc:
            return _error_message(str(exc))
        return Response(serialize_app(app), status=status.HTTP_201_CREATED)


class AppDetailView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]
    rate_limit_scope = 'destructive'

    def get_throttles(self):
        if self.request.method == 'DELETE':
            return [HostingScopeThrottle()]
        return []

    @extend_schema(
        tags=['sites'],
        operation_id='hosting_v1_apps_retrieve',
        parameters=[APP_REF_PATH],
        responses={200: AppSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_retrieve'),
        **mcp_tool(operation_id='hosting_v1_apps_retrieve', read_only=True),
    )
    def get(self, request, app_ref):
        try:
            company_id = require_company_id(request.user)
            app = resolve_app_ref(app_ref, company_id=company_id)
        except HostingError as exc:
            return _error(exc)
        return Response(serialize_app(app))

    @extend_schema(
        tags=['sites'],
        operation_id='hosting_v1_apps_destroy',
        parameters=[APP_REF_PATH],
        responses={204: None, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_destroy'),
        **mcp_tool(operation_id='hosting_v1_apps_destroy', read_only=False, destructive=True),
    )
    def delete(self, request, app_ref):
        try:
            company_id = require_company_id(request.user)
            app = resolve_app_ref(app_ref, company_id=company_id)
            access_token = request.auth if isinstance(request.auth, str) else None
            delete_app(
                app,
                access_token=access_token,
                user_id=request.user.user_id,
                actor_email=request.user.email,
            )
        except HostingError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AppRenewExpiryView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    @extend_schema(
        tags=['previews'],
        operation_id='hosting_v1_apps_renew_expiry_create',
        parameters=[APP_REF_PATH],
        request=None,
        responses={200: AppSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_renew_expiry_create'),
        **mcp_tool(operation_id='hosting_v1_apps_renew_expiry_create', read_only=False),
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
        operation_id='hosting_v1_apps_deployments_list',
        parameters=[APP_REF_PATH],
        responses={200: DeploymentSerializer(many=True), **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_deployments_list'),
        **mcp_tool(operation_id='hosting_v1_apps_deployments_list', read_only=True),
    ),
    post=extend_schema(
        tags=['deployments'],
        operation_id='hosting_v1_apps_deployments_create',
        parameters=[APP_REF_PATH],
        request=DeploymentCreateSerializer,
        responses={201: DeploymentSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_deployments_create'),
        **mcp_tool(operation_id='hosting_v1_apps_deployments_create', read_only=False),
    ),
)
class DeploymentListCreateView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]
    rate_limit_scope = 'deploy'

    def get_throttles(self):
        if self.request.method == 'POST':
            return [HostingScopeThrottle()]
        return []

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
            app = _scoped_app(request, app_ref)
            data = request.data if isinstance(request.data, dict) else {}
            deployment = create_deployment(
                app=app,
                app_version=str(data.get('app_version') or ''),
                shellui_version=str(data.get('shellui_version') or ''),
                deployed_by_id=request.user.user_id,
                pinned=bool(data.get('pinned', False)),
                actor_email=request.user.email,
            )
        except HostingError as exc:
            return _error(exc)
        except ValueError as exc:
            return _error_message(str(exc))
        return Response(serialize_deployment(deployment), status=status.HTTP_201_CREATED)


class DeploymentUploadView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]
    deploy_token_methods = ('PUT', 'POST')
    rate_limit_scope = 'upload'
    throttle_classes = [HostingScopeThrottle]
    parser_classes = [MultiPartParser, OctetStreamParser, GzipParser]

    @extend_schema(
        tags=['deployments'],
        operation_id='hosting_v1_apps_deployments_upload_update',
        summary='Upload deployment artifact',
        description=admin_description(
            lead=(
                'Upload a `.tar.gz` static site archive for a draft deployment. '
                'Send `Content-Type: application/gzip` with the raw body, or `multipart/form-data` with a `file` field.'
            ),
            side_effects='Stores artifact bytes and updates deployment metadata.',
            notes='Not exposed as a Shellui MCP tool. Deploy tokens may upload for preview sites only.',
        ),
        parameters=[APP_REF_PATH, DEPLOYMENT_ID_PATH],
        request={'application/gzip': {'type': 'string', 'format': 'binary'}},
        responses={200: DeploymentSerializer, 413: ErrorSerializer, **_API_ERRORS},
    )
    def put(self, request, app_ref, deployment_id):
        try:
            app = _scoped_app(request, app_ref)
            deployment = Deployment.objects.get(id=deployment_id, app=app)
        except Deployment.DoesNotExist:
            return _error_message('Deployment not found.', status_code=404, code='deployment_not_found')
        except HostingError as exc:
            return _error(exc)

        max_bytes = settings.HOSTING_MAX_UPLOAD_BYTES
        try:
            declared = int(request.META.get('CONTENT_LENGTH') or 0)
        except ValueError:
            declared = 0
        if declared > max_bytes:
            return _too_large(declared, max_bytes)

        # Never touch request.body: it is capped by DATA_UPLOAD_MAX_MEMORY_SIZE.
        fileobj = None
        content_type = request.content_type or ''
        if content_type.startswith('multipart/') and request.FILES:
            fileobj = request.FILES.get('file') or next(iter(request.FILES.values()), None)
        if fileobj is None:
            fileobj = request.stream
        if fileobj is None:
            return _error_message('Upload body is empty.', code='empty_upload')

        content_length = getattr(fileobj, 'size', None) or declared or None
        try:
            deployment = upload_deployment_artifact(
                deployment=deployment,
                fileobj=fileobj,
                content_length=content_length,
            )
        except HostingError as exc:
            if exc.code == 'upload_too_large':
                return _too_large(content_length, max_bytes)
            return _error(exc)
        except ArtifactTooLarge:
            return _too_large(None, max_bytes)
        except ValueError as exc:
            return _error_message(str(exc))
        return Response(serialize_deployment(deployment))

    def handle_exception(self, exc):
        if isinstance(exc, RequestDataTooBig):
            return _too_large(None, settings.HOSTING_MAX_UPLOAD_BYTES)
        return super().handle_exception(exc)


class DeploymentArtifactUploadUrlView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]
    deploy_token_methods = ('POST',)
    rate_limit_scope = 'upload'
    throttle_classes = [HostingScopeThrottle]
    parser_classes = [EmptyBodyParser]

    @extend_schema(
        tags=['deployments'],
        operation_id='hosting_v1_apps_deployments_artifact_upload_url_create',
        parameters=[
            APP_REF_PATH,
            DEPLOYMENT_ID_PATH,
            OpenApiParameter(
                name='expires_in',
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Seconds until the upload URL expires (60 to server default).',
            ),
        ],
        request=None,
        responses={200: ArtifactUploadUrlResponseSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_deployments_artifact_upload_url_create'),
        **mcp_tool(
            operation_id='hosting_v1_apps_deployments_artifact_upload_url_create',
            read_only=False,
        ),
    )
    def post(self, request, app_ref, deployment_id):
        try:
            app = _scoped_app(request, app_ref)
            deployment = Deployment.objects.get(id=deployment_id, app=app)
        except Deployment.DoesNotExist:
            return _error_message('Deployment not found.', status_code=404, code='deployment_not_found')
        except HostingError as exc:
            return _error(exc)

        data = request.data if isinstance(request.data, dict) else {}
        default_expires = settings.HOSTING_ARTIFACT_UPLOAD_URL_EXPIRES
        raw_expires = request.query_params.get('expires_in') or data.get('expires_in')
        try:
            expires_in = int(raw_expires) if raw_expires not in (None, '') else default_expires
        except (TypeError, ValueError):
            return _error_message('expires_in must be an integer.', code='invalid_expires_in')
        expires_in = max(60, min(expires_in, default_expires))

        try:
            payload = build_artifact_upload_target(deployment, request=request, expires_in=expires_in)
        except RuntimeError as exc:
            logger.exception('artifact upload url failed')
            return _error_message(str(exc), status_code=500, code='upload_url_failed')
        return Response(payload)


class DeploymentArtifactUploadCompleteView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]
    deploy_token_methods = ('POST',)
    rate_limit_scope = 'upload'
    throttle_classes = [HostingScopeThrottle]
    parser_classes = [EmptyBodyParser]

    @extend_schema(
        tags=['deployments'],
        operation_id='hosting_v1_apps_deployments_artifact_upload_complete_create',
        parameters=[APP_REF_PATH, DEPLOYMENT_ID_PATH],
        request=None,
        responses={200: DeploymentSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_deployments_artifact_upload_complete_create'),
        **mcp_tool(operation_id='hosting_v1_apps_deployments_artifact_upload_complete_create', read_only=False),
    )
    def post(self, request, app_ref, deployment_id):
        try:
            app = _scoped_app(request, app_ref)
            deployment = Deployment.objects.get(id=deployment_id, app=app)
            deployment = confirm_deployment_artifact_upload(deployment=deployment)
        except Deployment.DoesNotExist:
            return _error_message('Deployment not found.', status_code=404, code='deployment_not_found')
        except HostingError as exc:
            return _error(exc)
        return Response(serialize_deployment(deployment))


class DeploymentFinalizeView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]
    deploy_token_methods = ('POST',)
    rate_limit_scope = 'deploy'
    throttle_classes = [HostingScopeThrottle]

    @extend_schema(
        tags=['deployments'],
        operation_id='hosting_v1_apps_deployments_finalize_create',
        parameters=[APP_REF_PATH, DEPLOYMENT_ID_PATH],
        request=None,
        responses={200: DeploymentSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_deployments_finalize_create'),
        **mcp_tool(operation_id='hosting_v1_apps_deployments_finalize_create', read_only=False, destructive=True),
    )
    def post(self, request, app_ref, deployment_id):
        try:
            app = _scoped_app(request, app_ref)
            deployment = Deployment.objects.get(id=deployment_id, app=app)
            access_token = request.auth if isinstance(request.auth, str) else None
            deployment = finalize_deployment(
                deployment=deployment,
                user_id=request.user.user_id,
                actor_email=request.user.email,
                access_token=access_token,
            )
            redirect_sync = _oauth_redirect_api(deployment)
            deployment.refresh_from_db()
            deployment.app.refresh_from_db()
        except Deployment.DoesNotExist:
            return _error_message('Deployment not found.', status_code=404, code='deployment_not_found')
        except HostingError as exc:
            return _error(exc)
        payload = serialize_deployment(deployment)
        payload.update(redirect_sync)
        return Response(payload)


class DeploymentRollbackView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]
    rate_limit_scope = 'deploy'
    throttle_classes = [HostingScopeThrottle]

    @extend_schema(
        tags=['deployments'],
        operation_id='hosting_v1_apps_deployments_rollback_create',
        parameters=[APP_REF_PATH, DEPLOYMENT_ID_PATH],
        request=None,
        responses={200: DeploymentSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_deployments_rollback_create'),
        **mcp_tool(operation_id='hosting_v1_apps_deployments_rollback_create', read_only=False, destructive=True),
    )
    def post(self, request, app_ref, deployment_id):
        try:
            app = _scoped_app(request, app_ref)
            deployment = Deployment.objects.get(id=deployment_id, app=app)
            deployment = rollback_deployment(deployment=deployment)
        except Deployment.DoesNotExist:
            return _error_message('Deployment not found.', status_code=404, code='deployment_not_found')
        except HostingError as exc:
            return _error(exc)
        return Response(serialize_deployment(deployment))


class AppCustomDomainListCreateView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    @extend_schema(
        tags=['operations'],
        operation_id='hosting_v1_apps_domains_list',
        parameters=[APP_REF_PATH],
        responses={200: CustomDomainSerializer(many=True), **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_domains_list'),
        **mcp_tool(operation_id='hosting_v1_apps_domains_list', read_only=True),
    )
    def get(self, request, app_ref):
        app, err = _owner_app(request, app_ref)
        if err:
            return err
        try:
            payload = list_custom_domains(app=app)
        except HostingError as exc:
            return _error(exc)
        return Response(payload)

    @extend_schema(
        tags=['operations'],
        operation_id='hosting_v1_apps_domains_create',
        parameters=[APP_REF_PATH],
        request=CustomDomainCreateSerializer,
        responses={201: CustomDomainSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_domains_create'),
        **mcp_tool(operation_id='hosting_v1_apps_domains_create', read_only=False, destructive=True),
    )
    def post(self, request, app_ref):
        app, err = _owner_app(request, app_ref)
        if err:
            return err
        data = request.data if isinstance(request.data, dict) else {}
        try:
            payload = add_custom_domain(
                app=app,
                hostname=str(data.get('hostname') or ''),
                user_id=request.user.user_id,
                actor_email=request.user.email,
            )
        except HostingError as exc:
            return _error(exc)
        return Response(payload, status=status.HTTP_201_CREATED)


class AppCustomDomainDetailView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    @extend_schema(
        tags=['operations'],
        operation_id='hosting_v1_apps_domains_retrieve',
        parameters=[APP_REF_PATH, DOMAIN_ID_PATH],
        responses={200: CustomDomainSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_domains_retrieve'),
        **mcp_tool(operation_id='hosting_v1_apps_domains_retrieve', read_only=True),
    )
    def get(self, request, app_ref, domain_id):
        app, err = _owner_app(request, app_ref)
        if err:
            return err
        try:
            domain_uuid = uuid.UUID(str(domain_id))
            payload = get_custom_domain(app=app, domain_id=domain_uuid)
        except ValueError:
            return _error_message('Invalid domain id.', status_code=400, code='invalid_domain_id')
        except HostingError as exc:
            return _error(exc)
        return Response(payload)

    @extend_schema(
        tags=['operations'],
        operation_id='hosting_v1_apps_domains_destroy',
        parameters=[APP_REF_PATH, DOMAIN_ID_PATH],
        responses={204: None, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_domains_destroy'),
        **mcp_tool(operation_id='hosting_v1_apps_domains_destroy', read_only=False, destructive=True),
    )
    def delete(self, request, app_ref, domain_id):
        app, err = _owner_app(request, app_ref)
        if err:
            return err
        try:
            domain_uuid = uuid.UUID(str(domain_id))
            remove_custom_domain(
                app=app,
                domain_id=domain_uuid,
                user_id=request.user.user_id,
                actor_email=request.user.email,
            )
        except ValueError:
            return _error_message('Invalid domain id.', status_code=400, code='invalid_domain_id')
        except HostingError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AppCustomDomainRefreshView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    @extend_schema(
        tags=['operations'],
        operation_id='hosting_v1_apps_domains_refresh_create',
        parameters=[APP_REF_PATH, DOMAIN_ID_PATH],
        request=None,
        responses={200: CustomDomainSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_domains_refresh_create'),
        **mcp_tool(operation_id='hosting_v1_apps_domains_refresh_create', read_only=False, destructive=True),
    )
    def post(self, request, app_ref, domain_id):
        app, err = _owner_app(request, app_ref)
        if err:
            return err
        try:
            domain_uuid = uuid.UUID(str(domain_id))
            payload = refresh_custom_domain(app=app, domain_id=domain_uuid)
        except ValueError:
            return _error_message('Invalid domain id.', status_code=400, code='invalid_domain_id')
        except HostingError as exc:
            return _error(exc)
        return Response(payload)


class AppEnvironmentListCreateView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    @extend_schema(
        tags=['operations'],
        operation_id='hosting_v1_apps_environment_list',
        parameters=[APP_REF_PATH],
        responses={200: EnvVariableListSerializer(many=True), **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_environment_list'),
        **mcp_tool(operation_id='hosting_v1_apps_environment_list', read_only=True, sensitive=True),
    )
    def get(self, request, app_ref):
        app, err = _owner_app(request, app_ref)
        if err:
            return err
        try:
            payload = list_env_variables(app=app)
        except HostingError as exc:
            return _error(exc)
        return Response(payload)

    @extend_schema(
        tags=['operations'],
        operation_id='hosting_v1_apps_environment_create',
        parameters=[APP_REF_PATH],
        request=EnvVariableUpsertSerializer,
        responses={200: EnvVariableListSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_environment_create'),
        **mcp_tool(operation_id='hosting_v1_apps_environment_create', read_only=False, destructive=True, sensitive=True),
    )
    def post(self, request, app_ref):
        app, err = _owner_app(request, app_ref)
        if err:
            return err
        data = request.data if isinstance(request.data, dict) else {}
        try:
            payload = set_env_variable(
                app=app,
                key=str(data.get('key') or ''),
                value=str(data.get('value') if data.get('value') is not None else ''),
                user_id=request.user.user_id,
                actor_email=request.user.email,
            )
        except HostingError as exc:
            return _error(exc)
        return Response(payload, status=status.HTTP_200_OK)


class AppEnvironmentKeyView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    @extend_schema(
        tags=['operations'],
        operation_id='hosting_v1_apps_environment_retrieve',
        parameters=[APP_REF_PATH, ENV_KEY_PATH],
        responses={200: EnvVariableListSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_environment_retrieve'),
        **mcp_tool(operation_id='hosting_v1_apps_environment_retrieve', read_only=True, sensitive=True),
    )
    def get(self, request, app_ref, key):
        app, err = _owner_app(request, app_ref)
        if err:
            return err
        try:
            payload = get_env_variable(app=app, key=str(key))
        except HostingError as exc:
            return _error(exc)
        return Response(payload)

    @extend_schema(
        tags=['operations'],
        operation_id='hosting_v1_apps_environment_update',
        parameters=[APP_REF_PATH, ENV_KEY_PATH],
        request=EnvVariableValueSerializer,
        responses={200: EnvVariableListSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_environment_update'),
        **mcp_tool(operation_id='hosting_v1_apps_environment_update', read_only=False, destructive=True, sensitive=True),
    )
    def put(self, request, app_ref, key):
        app, err = _owner_app(request, app_ref)
        if err:
            return err
        data = request.data if isinstance(request.data, dict) else {}
        try:
            payload = set_env_variable(
                app=app,
                key=str(key),
                value=str(data.get('value') if data.get('value') is not None else ''),
                user_id=request.user.user_id,
                actor_email=request.user.email,
            )
        except HostingError as exc:
            return _error(exc)
        return Response(payload)

    @extend_schema(
        tags=['operations'],
        operation_id='hosting_v1_apps_environment_destroy',
        parameters=[APP_REF_PATH, ENV_KEY_PATH],
        responses={204: None, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_environment_destroy'),
        **mcp_tool(operation_id='hosting_v1_apps_environment_destroy', read_only=False, destructive=True, sensitive=True),
    )
    def delete(self, request, app_ref, key):
        app, err = _owner_app(request, app_ref)
        if err:
            return err
        try:
            delete_env_variable(app=app, key=str(key), user_id=request.user.user_id, actor_email=request.user.email)
        except HostingError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AppRuntimeLogsView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    @extend_schema(
        tags=['operations'],
        operation_id='hosting_v1_apps_runtime_logs_list',
        parameters=[
            APP_REF_PATH,
            OpenApiParameter(
                name='limit',
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Max lines to return (capped by the server).',
            ),
        ],
        responses={200: RuntimeLogResponseSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_runtime_logs_list'),
        **mcp_tool(operation_id='hosting_v1_apps_runtime_logs_list', read_only=True),
    )
    def get(self, request, app_ref):
        app, err = _owner_app(request, app_ref)
        if err:
            return err
        raw_limit = request.query_params.get('limit')
        try:
            limit = int(raw_limit) if raw_limit not in (None, '') else 100
        except ValueError:
            return _error_message('limit must be an integer.', code='invalid_limit')
        try:
            payload = list_app_runtime_logs(app=app, limit=limit)
        except HostingError as exc:
            return _error(exc)
        return Response(payload)


class AppRequestLogsView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    @extend_schema(
        tags=['operations'],
        operation_id='hosting_v1_apps_request_logs_list',
        parameters=[
            APP_REF_PATH,
            OpenApiParameter(
                name='limit',
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Page size (default 50, capped by the server).',
            ),
            OpenApiParameter(
                name='cursor',
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Opaque pagination cursor from a previous response (`next_cursor`).',
            ),
            OpenApiParameter(
                name='status_min',
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Include responses with status_code greater than or equal to this value.',
            ),
            OpenApiParameter(
                name='status_max',
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Include responses with status_code less than or equal to this value.',
            ),
        ],
        responses={200: RequestLogListResponseSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_apps_request_logs_list'),
        **mcp_tool(operation_id='hosting_v1_apps_request_logs_list', read_only=True),
    )
    def get(self, request, app_ref):
        app, err = _owner_app(request, app_ref)
        if err:
            return err
        raw_limit = request.query_params.get('limit')
        raw_cursor = request.query_params.get('cursor')
        raw_min = request.query_params.get('status_min')
        raw_max = request.query_params.get('status_max')
        try:
            limit = int(raw_limit) if raw_limit not in (None, '') else 50
        except ValueError:
            return _error_message('limit must be an integer.', code='invalid_limit')
        status_min = int(raw_min) if raw_min not in (None, '') else None
        status_max = int(raw_max) if raw_max not in (None, '') else None
        cursor = str(raw_cursor).strip() or None if raw_cursor is not None else None
        try:
            payload = list_app_request_logs(
                app=app,
                limit=limit,
                cursor=cursor,
                status_min=status_min,
                status_max=status_max,
            )
        except HostingError as exc:
            return _error(exc)
        return Response(payload)


class DeployTokenListCreateView(APIView):
    permission_classes = [IsAuthenticatedPrincipal, IsStaffOrCompanyOwner]

    @extend_schema(
        tags=['deploy-tokens'],
        operation_id='hosting_v1_deploy_tokens_retrieve',
        responses={200: DeployTokenSerializer(many=True), **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_deploy_tokens_retrieve'),
        **mcp_tool(operation_id='hosting_v1_deploy_tokens_retrieve', read_only=True, sensitive=True),
    )
    def get(self, request):
        try:
            company_id = require_company_id(request.user)
        except HostingError as exc:
            return _error(exc)
        return Response([serialize_deploy_token(t) for t in DeployToken.objects.filter(company_id=company_id)])

    @extend_schema(
        tags=['deploy-tokens'],
        operation_id='hosting_v1_deploy_tokens_create',
        summary='Create a deploy token for preview CI',
        description=admin_description(
            lead=(
                'Returns the plaintext token once in `token`. It is stored hashed and cannot be read again. '
                'Optional body fields: `name`, `expires_in_days`.'
            ),
            side_effects='Inserts a deploy token row.',
            notes='Not a Shellui MCP tool. Agent access tokens receive `403 forbidden`.',
        ),
        request=OpenApiTypes.OBJECT,
        responses={201: DeployTokenCreateResponseSerializer, **_API_ERRORS},
    )
    def post(self, request):
        if getattr(request.user, 'agent_id', None):
            return _error_message(
                'Deploy tokens cannot be created with an agent access token. Use admin or a user session.',
                status_code=403,
                code='forbidden',
            )
        data = request.data if isinstance(request.data, dict) else {}
        raw_days = data.get('expires_in_days')
        try:
            company_id = require_company_id(request.user)
            days = int(raw_days) if raw_days not in (None, '') else None
            token, raw = create_deploy_token(
                company_id=company_id,
                name=str(data.get('name') or ''),
                created_by_id=request.user.user_id,
                expires_in_days=days,
            )
        except HostingError as exc:
            return _error(exc)
        except (TypeError, ValueError) as exc:
            return _error_message(str(exc))
        payload = serialize_deploy_token(token)
        payload['token'] = raw
        return Response(payload, status=status.HTTP_201_CREATED, headers={'Cache-Control': 'no-store'})


class DeployTokenRevokeView(APIView):
    permission_classes = [IsAuthenticatedPrincipal, IsStaffOrCompanyOwner]

    @extend_schema(
        tags=['deploy-tokens'],
        operation_id='hosting_v1_deploy_tokens_revoke_create',
        parameters=[TOKEN_ID_PATH],
        request=None,
        responses={200: DeployTokenSerializer, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_deploy_tokens_revoke_create'),
        **mcp_tool(operation_id='hosting_v1_deploy_tokens_revoke_create', read_only=False, destructive=True),
    )
    def post(self, request, token_id):
        try:
            token = DeployToken.objects.get(id=token_id, company_id=require_company_id(request.user))
        except DeployToken.DoesNotExist:
            return _error_message('Deploy token not found.', status_code=404, code='deploy_token_not_found')
        except HostingError as exc:
            return _error(exc)
        return Response(serialize_deploy_token(revoke_deploy_token(token)))


class StatsView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]

    @extend_schema(
        tags=['stats'],
        operation_id='hosting_v1_stats_retrieve',
        responses={200: OpenApiTypes.OBJECT, **_API_ERRORS},
        **mcp_openapi_fields('hosting_v1_stats_retrieve'),
        **mcp_tool(operation_id='hosting_v1_stats_retrieve', read_only=True),
    )
    def get(self, request):
        company_id = None
        if not getattr(request.user, 'is_staff', False):
            try:
                company_id = require_company_id(request.user)
            except HostingError as exc:
                return _error(exc)
        return Response(build_hosting_stats(company_id=company_id))


def _metrics_company_from_token(request):
    """Company scope comes only from the Bearer token (no query override)."""
    if (request.GET.get('company_id') or '').strip():
        return None, Response(
            {
                'error': (
                    'Remove company_id from the query string; '
                    'company scope comes from the access token only.'
                ),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    company_id = getattr(request.user, 'company_id', None)
    if company_id is None:
        return None, Response(
            {'error': 'Missing company_id in access token.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return int(company_id), None


@extend_schema_view(
    get=extend_schema(
        tags=['platform-metrics'],
        summary='Prometheus metrics (staff or company owner)',
        description=(
            'Prometheus text exposition for the company in the Bearer token '
            '(JWT or PAT must include a `company_id` claim). Do not send `company_id` as a query parameter.'
        ),
        responses={
            200: OpenApiResponse(description='text/plain Prometheus exposition'),
            400: OpenApiResponse(
                description='Missing company_id in token, or company_id was sent in the query string'
            ),
            401: OpenApiResponse(description='Missing or invalid Bearer token'),
            403: OpenApiResponse(description='Forbidden'),
        },
    ),
)
class HostingMetricsView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]
    renderer_classes = [PrometheusTextRenderer]

    def get(self, request):
        user = request.user
        if not (getattr(user, 'is_staff', False) or getattr(user, 'is_company_owner', False)):
            return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        company_id, err = _metrics_company_from_token(request)
        if err:
            return err
        return HttpResponse(
            hosting_metrics.metrics_http_body(company_id=company_id),
            content_type=hosting_metrics.METRICS_CONTENT_TYPE,
        )


@extend_schema_view(
    get=extend_schema(
        tags=['platform-metrics'],
        summary='Prometheus metrics for all companies (staff)',
        description=(
            'Global Prometheus text exposition across all companies. Requires a Django staff user '
            'or a PAT created by staff with `access_global_metrics` (JWT claim `pat_agm`).'
        ),
        responses={
            200: OpenApiResponse(description='text/plain Prometheus exposition'),
            401: OpenApiResponse(description='Missing or invalid Bearer token'),
            403: OpenApiResponse(description='Forbidden (not staff and no global-metrics PAT)'),
        },
    ),
)
class HostingGlobalMetricsView(APIView):
    permission_classes = [IsAuthenticatedPrincipal]
    renderer_classes = [PrometheusTextRenderer]

    def get(self, request):
        user = request.user
        if getattr(user, 'is_staff', False) or getattr(user, 'access_global_metrics', False):
            return HttpResponse(
                hosting_metrics.metrics_http_body(),
                content_type=hosting_metrics.METRICS_CONTENT_TYPE,
            )
        return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
