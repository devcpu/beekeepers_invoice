import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Basis-Konfiguration für die Anwendung"""

    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "postgresql://localhost/rechnungen")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # File uploads
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads")
    PDF_FOLDER = os.getenv("PDF_FOLDER", "pdfs")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

    # Email (Flask-Mail Configuration für SMTP)
    MAIL_SERVER = os.getenv("MAIL_SERVER", "localhost")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "False").lower() == "true"
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "True").lower() == "true"
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", os.getenv("MAIL_USERNAME", ""))

    # IMAP Configuration (für Mail-Schnittstelle / Rechnungsimport)
    IMAP_SERVER = os.getenv("IMAP_SERVER", "localhost")
    IMAP_PORT = int(os.getenv("IMAP_PORT", 993))
    IMAP_USERNAME = os.getenv("IMAP_USERNAME", os.getenv("MAIL_USERNAME", ""))
    IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", os.getenv("MAIL_PASSWORD", ""))
    IMAP_USE_SSL = os.getenv("IMAP_USE_SSL", "True").lower() == "true"

    # Sicherheit
    HASH_ALGORITHM = "sha256"

    # Authentifizierung & Token-Verwaltung
    SESSION_COOKIE_SECURE = False  # In Produktion auf True setzen (HTTPS)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 3600  # Session-Lebensdauer in Sekunden (1 Stunde)

    # API Token Gültigkeit (in Tagen) - konfigurierbar
    API_TOKEN_EXPIRY_DAYS = int(os.getenv("API_TOKEN_EXPIRY_DAYS", "30"))

    # 2FA
    TOTP_ISSUER_NAME = os.getenv("TOTP_ISSUER_NAME", "Rechnungssystem")

    # Firmendaten (für Rechnungen und PDFs)
    COMPANY_NAME = os.getenv("COMPANY_NAME", "Ihre Firma GmbH")
    COMPANY_HOLDER = os.getenv("COMPANY_HOLDER", "")
    COMPANY_STREET = os.getenv("COMPANY_STREET", "Musterstraße 123")
    COMPANY_ZIP = os.getenv("COMPANY_ZIP", "12345")
    COMPANY_CITY = os.getenv("COMPANY_CITY", "Musterstadt")
    COMPANY_COUNTRY = os.getenv("COMPANY_COUNTRY", "Deutschland")
    COMPANY_EMAIL = os.getenv("COMPANY_EMAIL", "info@ihre-firma.de")
    COMPANY_PHONE = os.getenv("COMPANY_PHONE", "+49 123 456789")
    COMPANY_TAX_ID = os.getenv("COMPANY_TAX_ID", "DE123456789")
    COMPANY_WEBSITE = os.getenv("COMPANY_WEBSITE", "www.ihre-firma.de")

    # Bankverbindung
    BANK_NAME = os.getenv("BANK_NAME", "Ihre Bank")
    BANK_IBAN = os.getenv("BANK_IBAN", "DE00 0000 0000 0000 0000 00")
    BANK_BIC = os.getenv("BANK_BIC", "BANKDEFF")

    # PayPal
    PAYPAL = os.getenv("PAYPAL", "")

    # Standard-Steuersatz für neue Rechnungen (in %)
    DEFAULT_TAX_RATE = float(os.getenv("DEFAULT_TAX_RATE", "19.00"))

    # Durchschnittssatz Landwirtschaft nach §24 UStG (in %)
    LANDWIRTSCHAFTLICHE_URPRODUKTION_TAX_RATE = float(os.getenv("LANDWIRTSCHAFTLICHE_URPRODUKTION_TAX_RATE", "7.80"))


class DevelopmentConfig(Config):
    """Entwicklungs-Konfiguration"""

    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Produktions-Konfiguration"""

    DEBUG = False
    TESTING = False


class TestingConfig(Config):
    """Test-Konfiguration"""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = "postgresql://localhost/rechnungen_test"


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
