# pylint: disable=too-many-lines
import os
from datetime import datetime, timedelta

from flask import Flask
from flask_login import LoginManager

from blueprints.api import api_bp
from blueprints.auth import auth_bp
from blueprints.customers import customers_bp
from blueprints.delivery_notes import delivery_notes_bp
from blueprints.invoices import invoices_bp
from blueprints.main import main_bp
from blueprints.pos import pos_bp
from blueprints.production import production_bp
from blueprints.products import products_bp
from blueprints.reports import reports_bp
from blueprints.users import users_bp
from config import config
from email_service import mail
from invoice_numbering import generate_invoice_number
from models import Customer, Invoice, LineItem, User, db


def create_app(config_name="default"):
    """Flask App Factory"""
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Datenbank initialisieren
    db.init_app(app)

    # E-Mail initialisieren
    mail.init_app(app)

    # Flask-Login initialisieren
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Bitte melden Sie sich an, um auf diese Seite zuzugreifen."
    login_manager.login_message_category = "info"

    # CrowdSec Integration
    from crowdsec_app import crowdsec_app

    crowdsec_app.init_app(app)

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(pos_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(delivery_notes_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(production_bp)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Ordner erstellen falls nicht vorhanden
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["PDF_FOLDER"], exist_ok=True)

    # Context Processor für Templates
    @app.context_processor
    def utility_processor():
        # Version aus .version-Datei laden
        version = "0.0.0"
        try:
            with open(".version", "r", encoding="utf-8") as f:
                version = f.read().strip()
        except FileNotFoundError:
            pass
        return dict(now=datetime.now, app_version=version)

    # ========== HAUPTSEITEN-ROUTEN ==========

    # Health Check (für Docker/Kubernetes)
    @app.route("/health")
    def health_check():
        """Health Check Endpoint"""
        try:
            # DB Connection testen
            from sqlalchemy import text

            db.session.execute(text("SELECT 1"))
            return {"status": "healthy", "database": "ok"}, 200
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}, 503

    # CLI Commands
    @app.cli.command()
    def init_db():
        """Datenbank initialisieren"""
        from werkzeug.security import generate_password_hash

        db.create_all()

        # Standard-Admin-User erstellen, falls nicht vorhanden
        admin = User.query.filter_by(username="admin").first()
        if not admin:
            admin = User(
                username="admin",
                email="admin@example.com",
                password_hash=generate_password_hash("admin"),
                role="admin",
                is_active=True,
            )
            db.session.add(admin)
            db.session.commit()
            print("✅ Admin-User erstellt (Username: admin, Passwort: admin)")

        # Marktstand-Customer für Marktbestand erstellen
        marktstand = Customer.query.filter_by(email="marktstand@system.local").first()
        if not marktstand:
            marktstand = Customer(
                company_name="Marktstand",
                first_name="Markt",
                last_name="Bestand",
                email="marktstand@system.local",
                address="Interner Bestand für Marktverkäufe",
            )
            db.session.add(marktstand)
            db.session.commit()
            print("✅ Marktstand-Customer erstellt (für Marktbestand)")

        print("✅ Datenbank erfolgreich initialisiert!")

    @app.cli.command()
    def seed_db():
        """Testdaten in die Datenbank einfügen"""
        # Testkunde
        customer = Customer(
            company_name="Beispiel GmbH",
            first_name="Max",
            last_name="Mustermann",
            email="max@beispiel.de",
            phone="+49 123 456789",
            address="Musterstraße 1\n12345 Musterstadt",
            tax_id="DE123456789",
        )
        db.session.add(customer)
        db.session.flush()

        # Testrechnung
        invoice = Invoice(
            invoice_number=generate_invoice_number(),
            customer_id=customer.id,
            invoice_date=datetime.now().date(),
            due_date=(datetime.now() + timedelta(days=14)).date(),
            tax_rate=19.0,
            notes="Dies ist eine Testrechnung.",
        )

        # Testpositionen
        items = [
            LineItem(description="Webdesign", quantity=10, unit_price=80.00, position=0),
            LineItem(description="Hosting (12 Monate)", quantity=1, unit_price=120.00, position=1),
        ]

        for item in items:
            item.calculate_total()
            invoice.line_items.append(item)

        invoice.calculate_totals()
        invoice.generate_hash()

        db.session.add(invoice)
        db.session.commit()

        print("Testdaten erfolgreich eingefügt!")

    return app


if __name__ == "__main__":
    import sys

    # Port aus Kommandozeile oder Standard 5000
    port = 5000
    if "--port" in sys.argv:
        try:
            port_index = sys.argv.index("--port")
            port = int(sys.argv[port_index + 1])
        except (IndexError, ValueError):
            print("Verwendung: python app.py --port 5001")
            sys.exit(1)

    app = create_app(os.getenv("FLASK_ENV", "development"))
    print(f"\n🚀 Starte Flask-App auf http://localhost:{port}\n")
    app.run(debug=True, port=port)
