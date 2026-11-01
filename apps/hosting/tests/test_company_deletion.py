"""A deleted company's apps, deployments and artifacts are removed."""

import io
import tarfile

from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from apps.actions.company_deletion import purge_company
from apps.hosting.models import AccessStatus, App, CompanyHostingAccess, Deployment
from apps.hosting.services import create_app, create_deployment, upload_deployment_artifact
from apps.hosting.storage import artifact_key


def _tarball() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        info = tarfile.TarInfo(name='index.html')
        info.size = 2
        tar.addfile(info, io.BytesIO(b'ok'))
    return buf.getvalue()


@override_settings(HOSTING_DEBUG_OPEN=True)
class HostingCompanyDeletionTests(TestCase):
    def _deploy(self, company_id, name):
        CompanyHostingAccess.objects.get_or_create(company_id=company_id, defaults={'status': AccessStatus.APPROVED})
        app = create_app(company_id=company_id, name=name, display_name=name)
        deployment = create_deployment(app=app, app_version='1.0.0', shellui_version='0.7.0', deployed_by_id=1)
        data = _tarball()
        upload_deployment_artifact(deployment=deployment, fileobj=io.BytesIO(data), content_length=len(data))
        return deployment

    def test_purge_removes_artifacts_and_rows(self):
        gone = self._deploy(7, 'gone-app')
        kept = self._deploy(8, 'kept-app')
        self.assertTrue(default_storage.exists(artifact_key(gone)))
        purge_company(7)
        self.assertFalse(default_storage.exists(artifact_key(gone)))
        self.assertFalse(App.objects.filter(company_id=7).exists())
        self.assertFalse(Deployment.objects.filter(app__company_id=7).exists())
        self.assertFalse(CompanyHostingAccess.objects.filter(company_id=7).exists())
        self.assertTrue(default_storage.exists(artifact_key(kept)))
        purge_company(7)
