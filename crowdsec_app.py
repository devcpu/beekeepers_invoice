# CrowdSec Flask Integration
# Middleware für automatisches Reporting von Security-Events an CrowdSec

import logging
from datetime import datetime

from flask import g, request


class CrowdSecApp:
    """
    CrowdSec Flask Integration

    Loggt Security-relevante Events für CrowdSec Parser
    """

    def __init__(self, app=None, logger_name="crowdsec"):
        self.app = app
        self.logger = logging.getLogger(logger_name)

        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Flask App initialisieren"""
        self.app = app

        # Logs-Verzeichnis erstellen
        import os

        os.makedirs("logs", exist_ok=True)

        # Security Logger konfigurieren
        if not self.logger.handlers:
            handler = logging.FileHandler("logs/security.log")
            handler.setLevel(logging.WARNING)
            formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.WARNING)

        # Before/After Request Hooks
        app.before_request(self._before_request)
        app.after_request(self._after_request)

    def _before_request(self):
        """Request Start Time speichern"""
        g.start_time = datetime.utcnow()
        g.ip = request.remote_addr or request.environ.get("HTTP_X_REAL_IP", "unknown")

    def _after_request(self, response):
        """Nach jedem Request - Security Checks"""
        # 4xx und 5xx Responses loggen
        if response.status_code >= 400:
            self._log_error_response(response)

        return response

    def _log_error_response(self, response):
        """Fehlerhafte Responses loggen"""
        ip = getattr(g, "ip", "unknown")
        method = request.method
        path = request.path
        status = response.status_code

        # User-Agent
        user_agent = request.headers.get("User-Agent", "unknown")

        # Referrer
        referrer = request.headers.get("Referer", "-")

        self.logger.warning(f'{ip} - "{method} {path}" {status} - UA:"{user_agent}" Ref:"{referrer}"')

    def log_failed_login(self, username, ip=None, reason="invalid_credentials"):
        """
        Failed Login loggen (für CrowdSec Bruteforce Detection)

        Args:
            username: Versuchter Benutzername
            ip: IP-Adresse (optional, wird automatisch erkannt)
            reason: Grund (invalid_credentials, account_disabled, 2fa_failed)
        """
        ip = ip or getattr(g, "ip", request.remote_addr or "unknown")

        self.logger.warning(
            f"FAILED_LOGIN ip={ip} user={username} reason={reason} " f"path={request.path} method={request.method}"
        )

    def log_suspicious_activity(self, activity_type, details="", ip=None):
        """
        Verdächtige Aktivität loggen

        Args:
            activity_type: Art der Aktivität (sql_injection, xss_attempt, path_traversal, etc.)
            details: Zusätzliche Details
            ip: IP-Adresse (optional)
        """
        ip = ip or getattr(g, "ip", request.remote_addr or "unknown")

        self.logger.error(
            f"SUSPICIOUS_ACTIVITY type={activity_type} ip={ip} "
            f'path={request.path} method={request.method} details="{details}"'
        )

    def log_rate_limit_exceeded(self, endpoint, ip=None):
        """
        Rate Limit Überschreitung loggen

        Args:
            endpoint: Betroffener Endpoint
            ip: IP-Adresse (optional)
        """
        ip = ip or getattr(g, "ip", request.remote_addr or "unknown")

        self.logger.warning(f"RATE_LIMIT_EXCEEDED endpoint={endpoint} ip={ip}")

    def log_unauthorized_access(self, resource, required_role="", ip=None):
        """
        Unberechtigter Zugriff loggen

        Args:
            resource: Versuchter Zugriff auf Resource
            required_role: Erforderliche Rolle
            ip: IP-Adresse (optional)
        """
        ip = ip or getattr(g, "ip", request.remote_addr or "unknown")

        self.logger.warning(
            f"UNAUTHORIZED_ACCESS resource={resource} required_role={required_role} " f"ip={ip} path={request.path}"
        )


# Singleton Instance
crowdsec_app = CrowdSecApp()
