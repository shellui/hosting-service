"""Tests for preview deploy flow and expiry."""

import io
import tarfile

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.hosting.models import AccessStatus, App, CompanyHostingAccess
from apps.hosting.services import (
    create_deployment,
    create_preview_app,
    delete_app,
    finalize_deployment,
    is_preview_expired,
    prepare_preview_deploy,
    renew_app_expiry,
    renew_preview_expiry,
    resolve_preview_app,
    upload_deployment_artifact,
)


def _make_site_tarball(html: str = '<html><body>preview</body></html>') -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        data = html.encode('utf-8')
        info = tarfile.TarInfo(name='index.html')
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@override_settings(
    HOSTING_DEBUG_OPEN=True,
    HOSTING_PREVIEW_TTL_DAYS=7,
    IDENTITY_SERVICE_URL='',
)
class PreviewDeployTests(TestCase):
    def setUp(self):
        CompanyHostingAccess.objects.create(company_id=1, status=AccessStatus.APPROVED)

    def test_create_preview_app_assigns_owner(self):
        app = create_preview_app(company_id=1, user_id=42, display_name='Demo')
        self.assertEqual(app.created_by_id, 42)
        self.assertTrue(app.slug)
        self.assertEqual(app.name, app.slug)

    def test_prepare_without_slug_creates_new_site(self):
        app1, _ = prepare_preview_deploy(
            company_id=1,
            user_id=10,
            slug=None,
            display_name='One',
            app_version='1.0.0',
            shellui_version='0.5.0',
        )
        app2, _ = prepare_preview_deploy(
            company_id=1,
            user_id=10,
            slug=None,
            display_name='Two',
            app_version='1.0.0',
            shellui_version='0.5.0',
        )
        self.assertNotEqual(app1.slug, app2.slug)

    def test_prepare_with_slug_reuses_site(self):
        app, _ = prepare_preview_deploy(
            company_id=1,
            user_id=10,
            slug=None,
            display_name='Reuse',
            app_version='1.0.0',
            shellui_version='0.5.0',
        )
        reused, _ = prepare_preview_deploy(
            company_id=1,
            user_id=10,
            slug=app.slug,
            display_name='Reuse',
            app_version='1.0.1',
            shellui_version='0.5.0',
        )
        self.assertEqual(reused.id, app.id)

    def test_resolve_preview_rejects_other_user(self):
        app = create_preview_app(company_id=1, user_id=10, display_name='Mine')
        with self.assertRaises(Exception):
            resolve_preview_app(slug=app.slug, company_id=1, user_id=99)

    def test_finalize_resets_expiry(self):
        app = create_preview_app(company_id=1, user_id=10, display_name='TTL')
        deployment = create_deployment(
            app=app,
            app_version='1.0.0',
            shellui_version='0.5.0',
            deployed_by_id=10,
        )
        tarball = _make_site_tarball()
        upload_deployment_artifact(
            deployment=deployment,
            fileobj=io.BytesIO(tarball),
            content_length=len(tarball),
        )
        app.expires_at = timezone.now() - timezone.timedelta(days=1)
        app.save(update_fields=['expires_at'])
        self.assertTrue(is_preview_expired(app))
        finalize_deployment(deployment=deployment)
        app.refresh_from_db()
        self.assertFalse(is_preview_expired(app))
        self.assertIsNotNone(app.expires_at)

    def test_renew_preview_expiry_extends_window(self):
        app = create_preview_app(company_id=1, user_id=10, display_name='Renew')
        app.expires_at = timezone.now() + timezone.timedelta(days=1)
        app.save(update_fields=['expires_at'])
        old = app.expires_at
        renew_preview_expiry(app)
        app.refresh_from_db()
        self.assertGreater(app.expires_at, old)

    def test_renew_app_expiry_rejects_expired_preview(self):
        app = create_preview_app(company_id=1, user_id=10, display_name='Manual')
        app.expires_at = timezone.now() - timezone.timedelta(days=1)
        app.save(update_fields=['expires_at'])
        self.assertTrue(is_preview_expired(app))
        with self.assertRaises(Exception):
            renew_app_expiry(app)

    def test_renew_app_expiry_extends_active_preview(self):
        app = create_preview_app(company_id=1, user_id=10, display_name='Manual')
        app.expires_at = timezone.now() + timezone.timedelta(days=1)
        app.save(update_fields=['expires_at'])
        old = app.expires_at
        renew_app_expiry(app)
        app.refresh_from_db()
        self.assertGreater(app.expires_at, old)

    def test_renew_app_expiry_rejects_non_preview(self):
        app = create_preview_app(company_id=1, user_id=10, display_name='Legacy')
        app.created_by_id = None
        app.expires_at = None
        app.save(update_fields=['created_by_id', 'expires_at'])
        with self.assertRaises(Exception):
            renew_app_expiry(app)

    def test_delete_app_removes_record(self):
        app = create_preview_app(company_id=1, user_id=10, display_name='Gone')
        app_id = app.id
        delete_app(app)
        self.assertFalse(App.objects.filter(id=app_id).exists())
