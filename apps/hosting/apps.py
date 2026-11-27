from django.apps import AppConfig


class HostingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.hosting'
    verbose_name = 'Hosting'

    def ready(self):
        from . import checks  # noqa: F401

        self._log_cookie_parent_check()

    def _log_cookie_parent_check(self):
        import logging
        import sys

        if not _is_long_running_server_process(sys.argv):
            return
        from .checks import shared_cookie_parent_error

        logger = logging.getLogger(__name__)
        for error in shared_cookie_parent_error(None):
            logger.error('%s Hint: %s', error.msg, error.hint)


def _is_long_running_server_process(argv: list[str]) -> bool:
    """Log the cookie-parent check when serving HTTP, not for one-off commands."""
    if not argv:
        return False
    prog = argv[0].replace('\\', '/')
    if 'gunicorn' in prog or 'uwsgi' in prog:
        return True
    if prog.endswith('manage.py') and len(argv) >= 2:
        return argv[1] == 'runserver' or argv[1].startswith('runserver')
    return False
