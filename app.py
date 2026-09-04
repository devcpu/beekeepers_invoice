# pylint: disable=too-many-lines
import os
from datetime import datetime, timedelta
from decimal import Decimal

from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from flask_login import LoginManager, current_user, login_required

from auth_utils import role_required
from blueprints.api import api_bp
from blueprints.auth import auth_bp
from blueprints.main import main_bp
from blueprints.customers import customers_bp
from blueprints.pos import pos_bp
from blueprints.products import products_bp
from blueprints.reports import reports_bp
from config import config
from email_service import mail
from invoice_numbering import generate_invoice_number
from models import (
    ConsignmentStock,
    Customer,
    DeliveryNote,
    DeliveryNoteItem,
    Invoice,
    InvoicePdfArchive,
    InvoiceStatusLog,
    LineItem,
    PaymentCheck,
    Product,
    Reminder,
    StockAdjustment,
    User,
    db,
)


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

    # ========== HAUPTSEITEN-ROUTEN ==========

    # Routes
    @app.route("/invoices")
    @login_required
    def list_invoices():
        """Liste aller Rechnungen"""
        from datetime import datetime, timedelta

        status_filter = request.args.get("status", None)
        custom_filter = request.args.get("filter", None)
        query = Invoice.query

        if status_filter:
            query = query.filter_by(status=status_filter)
        elif custom_filter == "storno":
            # Nur Stornorechnungen (beginnen mit STORNO-)
            query = query.filter(Invoice.invoice_number.like("STORNO-%"))
        elif custom_filter == "open":
            # Versendet aber nicht bezahlt
            query = query.filter_by(status="sent")
        elif custom_filter == "overdue":
            # Fälligkeitsdatum mehr als 10 Tage überschritten
            overdue_date = datetime.now().date() - timedelta(days=10)
            query = query.filter(Invoice.status == "sent", Invoice.due_date.isnot(None), Invoice.due_date < overdue_date)

        invoices = query.order_by(Invoice.invoice_date.desc()).all()
        return render_template("invoices/list.html", invoices=invoices, status_filter=status_filter)

    @app.route("/invoices/new", methods=["GET", "POST"])
    @login_required
    def create_invoice():
        """Neue Rechnung erstellen"""
        if request.method == "POST":
            try:
                # Kunde suchen oder erstellen
                customer_email = request.form.get("customer_email")
                customer = Customer.query.filter_by(email=customer_email).first()

                if not customer:
                    customer = Customer(
                        company_name=request.form.get("company_name"),
                        first_name=request.form.get("first_name"),
                        last_name=request.form.get("last_name"),
                        email=customer_email,
                        phone=request.form.get("phone"),
                        address=request.form.get("address"),
                        tax_id=request.form.get("tax_id"),
                    )
                    db.session.add(customer)
                    db.session.flush()  # Um die customer.id zu bekommen

                # Rechnung erstellen
                invoice_number = generate_invoice_number()

                # Steuermodell bestimmen
                tax_model = request.form.get("tax_model", "landwirtschaft")

                # Kundentyp (Endkunde oder Wiederverkäufer)
                customer_type = request.form.get("customer_type", "endkunde")

                # Steuersatz je nach Modell
                if tax_model == "standard":
                    tax_rate = Decimal(str(request.form.get("tax_rate", app.config.get("DEFAULT_TAX_RATE", 19.0))))
                elif tax_model == "landwirtschaft":
                    tax_rate = Decimal(str(app.config.get("LANDWIRTSCHAFTLICHE_URPRODUKTION_TAX_RATE", 7.8)))
                else:  # kleinunternehmer
                    tax_rate = Decimal("0.0")

                invoice = Invoice(
                    invoice_number=invoice_number,
                    customer_id=customer.id,
                    invoice_date=datetime.strptime(request.form.get("invoice_date"), "%Y-%m-%d").date(),
                    due_date=(datetime.strptime(request.form.get("due_date"), "%Y-%m-%d").date() if request.form.get("due_date") else None),
                    tax_rate=tax_rate,
                    tax_model=tax_model,
                    customer_type=customer_type,
                    notes=request.form.get("notes"),
                    payment_method=request.form.get("payment_method"),
                )

                # Positionen hinzufügen
                descriptions = request.form.getlist("description[]")
                quantities = request.form.getlist("quantity[]")
                unit_prices = request.form.getlist("unit_price[]")
                product_ids = request.form.getlist("product_id[]")

                for idx, (desc, qty, price, prod_id) in enumerate(zip(descriptions, quantities, unit_prices, product_ids)):
                    if desc and qty and price:
                        # Tax Rate aus Produkt holen (falls vorhanden)
                        tax_rate_for_item = None
                        if prod_id and prod_id.strip():
                            product = Product.query.get(int(prod_id))
                            if product and product.tax_rate:
                                tax_rate_for_item = product.tax_rate

                        line_item = LineItem(
                            product_id=int(prod_id) if prod_id and prod_id.strip() else None,
                            description=desc,
                            quantity=Decimal(qty),
                            unit_price=Decimal(price),
                            tax_rate=tax_rate_for_item,
                            position=idx,
                        )
                        line_item.calculate_total()
                        invoice.line_items.append(line_item)

                # Summen berechnen und Hash generieren
                invoice.calculate_totals()
                invoice.generate_hash()

                db.session.add(invoice)
                db.session.commit()

                flash(f"Rechnung {invoice_number} erfolgreich erstellt!", "success")
                return redirect(url_for("view_invoice", invoice_id=invoice.id))

            except Exception as e:
                db.session.rollback()
                flash(f"Fehler beim Erstellen der Rechnung: {str(e)}", "error")
                return redirect(url_for("create_invoice"))

        # GET: Formular anzeigen
        customers = Customer.query.order_by(Customer.company_name, Customer.last_name).all()
        today = datetime.now().date()
        due_date_default = today + timedelta(days=14)
        default_tax_rate = app.config.get("DEFAULT_TAX_RATE", 19.00)
        landw_tax_rate = app.config.get("LANDWIRTSCHAFTLICHE_URPRODUKTION_TAX_RATE", 7.80)

        return render_template(
            "invoices/create.html",
            customers=customers,
            today=today,
            due_date_default=due_date_default,
            default_tax_rate=default_tax_rate,
            landw_tax_rate=landw_tax_rate,
        )

    @app.route("/invoices/<int:invoice_id>")
    @login_required
    def view_invoice(invoice_id):
        """Einzelne Rechnung anzeigen"""
        invoice = Invoice.query.get_or_404(invoice_id)
        is_valid = invoice.verify_hash()
        return render_template("invoices/view.html", invoice=invoice, is_valid=is_valid)

    @app.route("/invoices/<int:invoice_id>/status/<status>")
    @login_required
    def update_invoice_status(invoice_id, status):
        """Status einer Rechnung ändern (GoBD-konform mit Audit Trail)"""
        invoice = Invoice.query.get_or_404(invoice_id)

        # Erlaubte Status
        allowed_statuses = ["draft", "sent", "paid", "cancelled"]
        if status not in allowed_statuses:
            flash(f"Ungültiger Status: {status}", "error")
            return redirect(url_for("view_invoice", invoice_id=invoice_id))

        old_status = invoice.status

        # GoBD: Keine Änderungen nach "sent" außer paid/cancelled
        if old_status == "sent" and status == "draft":
            flash(
                "Fehler: Versendete Rechnungen können nicht zurück in Entwurf gesetzt werden (GoBD-Konformität).",
                "error",
            )
            return redirect(url_for("view_invoice", invoice_id=invoice_id))

        if old_status == "paid" and status != "cancelled":
            flash("Fehler: Bezahlte Rechnungen können nur storniert werden.", "error")
            return redirect(url_for("view_invoice", invoice_id=invoice_id))

        # Bei Stornierung: Bestand zurückbuchen
        if status == "cancelled" and old_status != "cancelled":
            try:
                for line_item in invoice.line_items:
                    if line_item.product_id:
                        product = Product.query.get(line_item.product_id)
                        if product:
                            # Menge zurück ins Lager
                            product.number += int(line_item.quantity)

                            # Bei Reseller: Auch Kommissionslager korrigieren
                            if invoice.customer_type == "reseller":
                                stock = ConsignmentStock.query.filter_by(customer_id=invoice.customer_id, product_id=line_item.product_id).first()
                                if stock:
                                    # Menge zurück ins Kommissionslager
                                    stock.quantity += int(line_item.quantity)

                flash("Bestand wurde zurückgebucht.", "info")
            except Exception as e:
                db.session.rollback()
                flash(f"Fehler bei Bestandsrückbuchung: {str(e)}", "error")
                return redirect(url_for("view_invoice", invoice_id=invoice_id))

        invoice.status = status

        # GoBD: Audit Trail - Status-Änderung protokollieren
        status_log = InvoiceStatusLog(
            invoice_id=invoice.id,
            old_status=old_status,
            new_status=status,
            changed_by=current_user.username,
            reason=request.args.get("reason", None),  # Optional: Begründung aus URL
        )
        db.session.add(status_log)

        try:
            db.session.commit()

            status_names = {"draft": "Entwurf", "sent": "Versendet", "paid": "Bezahlt", "cancelled": "Storniert"}

            flash(
                f'Status von "{status_names.get(old_status, old_status)}" zu "{status_names.get(status, status)}" geändert.',
                "success",
            )
        except Exception as e:
            db.session.rollback()
            flash(f"Fehler beim Ändern des Status: {str(e)}", "error")

        return redirect(url_for("view_invoice", invoice_id=invoice_id))

    @app.route("/invoices/<int:invoice_id>/delete", methods=["POST"])
    @login_required
    def delete_invoice(invoice_id):
        """Rechnung löschen (nur bei Status 'draft' erlaubt - GoBD-konform)"""
        invoice = Invoice.query.get_or_404(invoice_id)

        # GoBD: Nur Entwürfe dürfen gelöscht werden
        if invoice.status != "draft":
            flash(
                "Fehler: Nur Entwürfe können gelöscht werden. Versendete Rechnungen müssen storniert werden (GoBD-Konformität).",
                "error",
            )
            return redirect(url_for("view_invoice", invoice_id=invoice_id))

        try:
            invoice_number = invoice.invoice_number

            # Bestand zurückbuchen (da beim Erstellen abgezogen)
            for line_item in invoice.line_items:
                if line_item.product_id:
                    product = Product.query.get(line_item.product_id)
                    if product:
                        # Menge zurück ins Lager
                        product.number += int(line_item.quantity)

                        # Bei Reseller: Auch Kommissionslager korrigieren
                        if invoice.customer_type == "reseller":
                            stock = ConsignmentStock.query.filter_by(customer_id=invoice.customer_id, product_id=line_item.product_id).first()
                            if stock:
                                # Menge zurück ins Kommissionslager
                                stock.quantity += int(line_item.quantity)

            # Alle LineItems löschen (CASCADE sollte das eigentlich automatisch machen)
            for line_item in invoice.line_items:
                db.session.delete(line_item)

            # Status-Log-Einträge löschen (CASCADE)
            for log in invoice.status_history:
                db.session.delete(log)

            # Rechnung löschen
            db.session.delete(invoice)
            db.session.commit()

            flash(f'Entwurf "{invoice_number}" wurde gelöscht und Bestand zurückgebucht.', "success")
            return redirect(url_for("list_invoices"))

        except Exception as e:
            db.session.rollback()
            flash(f"Fehler beim Löschen: {str(e)}", "error")
            return redirect(url_for("view_invoice", invoice_id=invoice_id))

    @app.route("/invoices/<int:invoice_id>/create-cancellation", methods=["GET", "POST"])
    @login_required
    def create_cancellation_invoice(invoice_id):
        """Erstellt eine Stornorechnung (GoBD-konform)"""
        original_invoice = Invoice.query.get_or_404(invoice_id)

        # Nur versendete oder bezahlte Rechnungen können storniert werden
        if original_invoice.status not in ["sent", "paid"]:
            flash("Nur versendete oder bezahlte Rechnungen können storniert werden.", "error")
            return redirect(url_for("view_invoice", invoice_id=invoice_id))

        # Prüfen ob bereits storniert
        if original_invoice.status == "cancelled":
            flash("Diese Rechnung wurde bereits storniert.", "error")
            return redirect(url_for("view_invoice", invoice_id=invoice_id))

        if request.method == "POST":
            try:
                reason = request.form.get("reason", "Stornierung auf Kundenwunsch")

                # Neue Rechnungsnummer mit STORNO-Präfix generieren
                today = datetime.now().date()
                prefix = f"STORNO-{today.strftime('%Y-%m-%d')}"

                last_invoice = Invoice.query.filter(Invoice.invoice_number.like(f"{prefix}%")).order_by(Invoice.invoice_number.desc()).first()

                if last_invoice:
                    last_num = int(last_invoice.invoice_number.split("-")[-1])
                    next_num = last_num + 1
                else:
                    next_num = 1

                cancellation_number = f"{prefix}-{next_num:04d}"

                # Stornorechnung erstellen (Kopie mit negativen Beträgen)
                cancellation_invoice = Invoice(
                    invoice_number=cancellation_number,
                    customer_id=original_invoice.customer_id,
                    invoice_date=today,
                    due_date=today,  # Stornorechnungen sofort fällig
                    status="sent",  # Stornorechnung ist automatisch versendet
                    customer_type=original_invoice.customer_type,
                    tax_model=original_invoice.tax_model,
                    tax_rate=original_invoice.tax_rate,
                    subtotal=-original_invoice.subtotal,  # Negativ!
                    tax_amount=-original_invoice.tax_amount,  # Negativ!
                    total=-original_invoice.total,  # Negativ!
                    notes=f"Stornierung von Rechnung {original_invoice.invoice_number}\nGrund: {reason}",
                )

                # LineItems ERST erstellen, BEVOR wir zur Session hinzufügen
                line_items_list = []
                for orig_item in original_invoice.line_items:
                    cancellation_item = LineItem(
                        product_id=orig_item.product_id,
                        description=f"STORNO: {orig_item.description}",
                        quantity=-orig_item.quantity,  # Negativ!
                        unit_price=orig_item.unit_price,
                        tax_rate=orig_item.tax_rate,
                        total=-orig_item.total,  # Negativ!
                        position=orig_item.position,
                    )
                    line_items_list.append(cancellation_item)

                # LineItems zur Rechnung hinzufügen (ohne DB-Flush)
                cancellation_invoice.line_items = line_items_list

                # JETZT Hash generieren (mit LineItems im Objekt, aber noch nicht in DB)
                cancellation_invoice.generate_hash()

                # Jetzt alles zur Session hinzufügen
                db.session.add(cancellation_invoice)

                # Bestand zurückbuchen
                for orig_item in original_invoice.line_items:
                    if orig_item.product_id:
                        product = Product.query.get(orig_item.product_id)
                        if product:
                            product.number += int(orig_item.quantity)

                            # Bei Reseller: Kommissionslager anpassen
                            if original_invoice.customer_type == "reseller":
                                stock = ConsignmentStock.query.filter_by(customer_id=original_invoice.customer_id, product_id=orig_item.product_id).first()
                                if stock:
                                    stock.quantity += int(orig_item.quantity)

                # JETZT flush - mit korrektem Hash
                db.session.flush()

                # Ist-Status VOR der Mutation festhalten (fuer korrekten Audit-Trail)
                original_status = original_invoice.status

                # Original-Rechnung auf storniert setzen
                original_invoice.status = "cancelled"
                original_invoice.notes = (original_invoice.notes or "") + f"\n\nStorniert durch {cancellation_number} am {today.strftime('%d.%m.%Y')}"

                # Status-Log für beide Rechnungen
                db.session.add(
                    InvoiceStatusLog(
                        invoice_id=original_invoice.id,
                        old_status=original_status,
                        new_status="cancelled",
                        changed_by=current_user.username,
                        reason=f"Storniert durch {cancellation_number}: {reason}",
                    )
                )

                db.session.add(
                    InvoiceStatusLog(
                        invoice_id=cancellation_invoice.id,
                        old_status=None,
                        new_status="sent",
                        changed_by=current_user.username,
                        reason=f"Stornorechnung für {original_invoice.invoice_number}",
                    )
                )

                db.session.commit()

                flash(
                    f"Stornorechnung {cancellation_number} erfolgreich erstellt. Bestand wurde zurückgebucht.",
                    "success",
                )
                return redirect(url_for("view_invoice", invoice_id=cancellation_invoice.id))

            except Exception as e:
                db.session.rollback()
                flash(f"Fehler beim Erstellen der Stornorechnung: {str(e)}", "error")
                return redirect(url_for("view_invoice", invoice_id=invoice_id))

        # GET: Formular anzeigen
        return render_template("invoices/create_cancellation.html", invoice=original_invoice)

    @app.route("/invoices/<int:invoice_id>/pdf")
    @login_required
    def download_invoice_pdf(invoice_id):
        """Rechnung als PDF herunterladen (GoBD-konform mit PDF-Archivierung)"""
        import hashlib

        from pdf_service import generate_invoice_pdf

        invoice = Invoice.query.get_or_404(invoice_id)
        pdf_path = generate_invoice_pdf(invoice, app.config["PDF_FOLDER"], app.config)

        # GoBD: PDF archivieren und hashen (nur bei erstmaligem Versand)
        if invoice.status == "sent":
            # Prüfen ob schon archiviert
            existing_archive = InvoicePdfArchive.query.filter_by(invoice_id=invoice.id, pdf_filename=os.path.basename(pdf_path)).first()

            if not existing_archive:
                # PDF hashen
                with open(pdf_path, "rb") as f:
                    pdf_data = f.read()
                    pdf_hash = hashlib.sha256(pdf_data).hexdigest()
                    file_size = len(pdf_data)

                # In Archiv speichern
                archive = InvoicePdfArchive(
                    invoice_id=invoice.id,
                    pdf_filename=os.path.basename(pdf_path),
                    pdf_hash=pdf_hash,
                    file_size=file_size,
                    archived_by=current_user.username,
                )
                db.session.add(archive)

                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    # Fehler beim Archivieren nicht kritisch - PDF trotzdem ausliefern
                    app.logger.error("PDF-Archivierung fehlgeschlagen: %s", str(e))

        return send_file(pdf_path, as_attachment=True, download_name=f"Rechnung_{invoice.invoice_number}.pdf")

    @app.route("/invoices/<int:invoice_id>/send-email", methods=["GET", "POST"])
    @login_required
    def send_invoice_email(invoice_id):
        """Rechnung per E-Mail versenden"""
        from email_service import send_invoice_email as send_email
        from pdf_service import generate_invoice_pdf

        invoice = Invoice.query.get_or_404(invoice_id)

        if request.method == "POST":
            # E-Mail-Adresse aus Formular oder Kunden-E-Mail verwenden
            recipient_email = request.form.get("recipient_email") or invoice.customer.email
            cc_emails = request.form.get("cc_emails", "").strip()
            cc_list = [email.strip() for email in cc_emails.split(",") if email.strip()] if cc_emails else None

            # PDF generieren
            pdf_path = generate_invoice_pdf(invoice, app.config["PDF_FOLDER"], app.config)

            # E-Mail senden
            success = send_email(invoice, pdf_path, recipient_email, cc_list)

            if success:
                # Status auf "versendet" setzen, falls noch Entwurf
                if invoice.status == "draft":
                    invoice.status = "sent"
                    db.session.commit()

                flash(f"Rechnung erfolgreich an {recipient_email} versendet!", "success")
                return redirect(url_for("view_invoice", invoice_id=invoice_id))
            else:
                flash("Fehler beim Versenden der E-Mail. Bitte überprüfen Sie die E-Mail-Konfiguration.", "error")

        # GET: Formular anzeigen
        return render_template("invoices/send_email.html", invoice=invoice)

    @app.route("/invoices/<int:invoice_id>/reminder", methods=["GET", "POST"])
    @login_required
    def create_reminder(invoice_id):
        """Mahnung erstellen und versenden"""
        from email_service import send_email
        from reminder_service import generate_reminder_pdf

        invoice = Invoice.query.get_or_404(invoice_id)

        # Prüfen ob Rechnung überhaupt überfällig ist
        if invoice.status != "sent":
            flash("Mahnungen können nur für versendete, unbezahlte Rechnungen erstellt werden.", "error")
            return redirect(url_for("view_invoice", invoice_id=invoice_id))

        if request.method == "POST":
            action = request.form.get("action")  # 'download' oder 'send_email'

            # Mahnstufe ermitteln (nächste Stufe)
            existing_reminders = Reminder.query.filter_by(invoice_id=invoice_id).order_by(Reminder.reminder_level.desc()).first()
            reminder_level = 1 if not existing_reminders else existing_reminders.reminder_level + 1

            # Mahnung erstellen
            reminder = Reminder(
                invoice_id=invoice_id,
                reminder_level=reminder_level,
                reminder_date=datetime.utcnow(),
                reminder_fee=5.00 if reminder_level == 1 else 10.00,  # Erste Mahnung 5€, weitere 10€
            )
            db.session.add(reminder)
            db.session.commit()

            # PDF generieren
            pdf_path = generate_reminder_pdf(invoice, reminder, app.config["PDF_FOLDER"], app.config)

            if action == "download":
                # Als PDF herunterladen
                reminder.sent_via = "pdf"
                reminder.sent_date = datetime.utcnow()
                db.session.commit()

                return send_file(pdf_path, as_attachment=True, download_name=f"Mahnung_{reminder_level}_{invoice.invoice_number}.pdf")

            elif action == "send_email":
                # Per E-Mail versenden
                if not invoice.customer.email:
                    flash("Kunde hat keine E-Mail-Adresse hinterlegt.", "error")
                    return redirect(url_for("view_invoice", invoice_id=invoice_id))

                # E-Mail-Betreff und Text
                subject = f"{reminder_level}. Mahnung - Rechnung {invoice.invoice_number}"

                if reminder_level == 1:
                    body = f"""Sehr geehrte Damen und Herren,

leider haben wir bisher keinen Zahlungseingang für die Rechnung {invoice.invoice_number} feststellen können.

Bitte begleichen Sie den ausstehenden Betrag von {float(invoice.total + reminder.reminder_fee):.2f} €
(inkl. {float(reminder.reminder_fee):.2f} € Mahngebühr) innerhalb der nächsten 7 Tage.

Die Mahnung finden Sie im Anhang.

Mit freundlichen Grüßen
{app.config.get('COMPANY_NAME', '')}"""
                else:
                    body = f"""Sehr geehrte Damen und Herren,

trotz unserer bisherigen Mahnungen haben wir noch keinen Zahlungseingang für die Rechnung {invoice.invoice_number} feststellen können.

Wir fordern Sie auf, den ausstehenden Betrag von {float(invoice.total + reminder.reminder_fee):.2f} €
(inkl. {float(reminder.reminder_fee):.2f} € Mahngebühr) umgehend zu begleichen.

Die Mahnung finden Sie im Anhang.

Mit freundlichen Grüßen
{app.config.get('COMPANY_NAME', '')}"""

                # E-Mail senden
                success = send_email(to=invoice.customer.email, subject=subject, body=body, attachment_path=pdf_path)

                if success:
                    reminder.sent_via = "email"
                    reminder.sent_date = datetime.utcnow()
                    db.session.commit()
                    flash(f"Mahnung erfolgreich per E-Mail an {invoice.customer.email} versendet!", "success")
                else:
                    flash("Fehler beim Versenden der E-Mail.", "error")

                return redirect(url_for("view_invoice", invoice_id=invoice_id))

        # GET: Formular anzeigen
        existing_reminders = Reminder.query.filter_by(invoice_id=invoice_id).order_by(Reminder.reminder_date.desc()).all()
        next_level = 1 if not existing_reminders else existing_reminders[0].reminder_level + 1

        return render_template(
            "invoices/create_reminder.html",
            invoice=invoice,
            existing_reminders=existing_reminders,
            next_level=next_level,
        )

    # ============================================================================
    # Stock Adjustments - Bestandsanpassungen (Eigenentnahme, Inventur, etc.)
    # ============================================================================

    @app.route("/stock-adjustments")
    @login_required
    def list_stock_adjustments():
        """Liste aller Bestandsanpassungen"""
        adjustments = StockAdjustment.query.order_by(StockAdjustment.adjusted_at.desc()).limit(100).all()
        return render_template("stock_adjustments/list.html", adjustments=adjustments)

    @app.route("/stock-adjustments/export-pdf")
    @login_required
    def export_stock_adjustments_pdf():
        """Exportiere alle Bestandsanpassungen als PDF (GoBD-konform)"""
        from io import BytesIO

        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        # Filter-Parameter
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        adjustment_type = request.args.get("adjustment_type")

        query = StockAdjustment.query

        if start_date:
            from datetime import datetime

            query = query.filter(StockAdjustment.adjusted_at >= datetime.strptime(start_date, "%Y-%m-%d"))
        if end_date:
            from datetime import datetime

            query = query.filter(StockAdjustment.adjusted_at <= datetime.strptime(end_date, "%Y-%m-%d"))
        if adjustment_type:
            query = query.filter(StockAdjustment.adjustment_type == adjustment_type)

        adjustments = query.order_by(StockAdjustment.adjusted_at.desc()).all()

        # PDF erstellen
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
        elements = []

        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("CustomTitle", parent=styles["Heading1"], fontSize=16, spaceAfter=30)

        # Titel
        title = Paragraph("Bestandsanpassungen - Übersicht (GoBD-konform)", title_style)
        elements.append(title)

        # Zeitraum
        if start_date or end_date:
            period = f"Zeitraum: {start_date or 'Anfang'} bis {end_date or 'Heute'}"
            elements.append(Paragraph(period, styles["Normal"]))
            elements.append(Spacer(1, 0.5 * cm))

        # Tabelle
        data = [["Datum", "Produkt", "Typ", "Menge", "Alt → Neu", "Grund", "Benutzer", "Beleg-Nr."]]

        type_labels = {
            "eigenentnahme": "Eigenentnahme",
            "geschenk": "Geschenk",
            "verderb": "Verderb",
            "bruch": "Bruch",
            "inventur_plus": "Inventur +",
            "inventur_minus": "Inventur -",
            "korrektur": "Korrektur",
            "sonstiges": "Sonstiges",
        }

        for adj in adjustments:
            data.append(
                [
                    adj.adjusted_at.strftime("%d.%m.%Y %H:%M"),
                    adj.product.name if adj.product else "N/A",
                    type_labels.get(adj.adjustment_type, adj.adjustment_type),
                    f"{adj.quantity:+d}",
                    f"{adj.old_stock} → {adj.new_stock}",
                    adj.reason[:30] + "..." if len(adj.reason) > 30 else adj.reason,
                    adj.adjusted_by_user.username if adj.adjusted_by_user else "N/A",
                    adj.document_number or "-",
                ]
            )

        table = Table(data, colWidths=[3 * cm, 4 * cm, 2.5 * cm, 1.5 * cm, 2 * cm, 5 * cm, 2 * cm, 3 * cm])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                    ("FONTSIZE", (0, 1), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )

        elements.append(table)

        # Fußnote
        elements.append(Spacer(1, 1 * cm))
        footer_text = f"Erstellt am: {datetime.now().strftime('%d.%m.%Y %H:%M')} | Anzahl Einträge: {len(adjustments)}"
        elements.append(Paragraph(footer_text, styles["Normal"]))

        doc.build(elements)
        buffer.seek(0)

        filename = f"Bestandsanpassungen_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")

    @app.route("/stock-adjustments/create", methods=["GET", "POST"])
    @login_required
    def create_stock_adjustment():
        """Neue Bestandsanpassung erstellen"""
        if request.method == "POST":
            try:
                product_id = request.form.get("product_id")
                quantity = int(request.form.get("quantity"))
                adjustment_type = request.form.get("adjustment_type")
                reason = request.form.get("reason")

                if not all([product_id, quantity, adjustment_type, reason]):
                    flash("Alle Felder müssen ausgefüllt werden.", "error")
                    return redirect(url_for("create_stock_adjustment"))

                product = Product.query.get(int(product_id))
                if not product:
                    flash("Produkt nicht gefunden.", "error")
                    return redirect(url_for("create_stock_adjustment"))

                old_stock = product.number
                new_stock = old_stock + quantity

                if new_stock < 0:
                    flash(f"Fehler: Bestand würde negativ werden! Aktuell: {old_stock}, Änderung: {quantity}", "error")
                    return redirect(url_for("create_stock_adjustment"))

                # Generiere Belegnummer für Eigenentnahmen
                document_number = None
                if adjustment_type in ["eigenentnahme", "geschenk"]:
                    today = datetime.now().date()
                    prefix = f"ENT-{today.strftime('%Y%m%d')}"
                    last_doc = (
                        StockAdjustment.query.filter(StockAdjustment.document_number.like(f"{prefix}%"))
                        .order_by(StockAdjustment.document_number.desc())
                        .first()
                    )

                    if last_doc:
                        last_num = int(last_doc.document_number.split("-")[-1])
                        next_num = last_num + 1
                    else:
                        next_num = 1

                    document_number = f"{prefix}-{next_num:04d}"

                # Erstelle Anpassung
                adjustment = StockAdjustment(
                    product_id=product.id,
                    quantity=quantity,
                    old_stock=old_stock,
                    new_stock=new_stock,
                    adjustment_type=adjustment_type,
                    reason=reason,
                    adjusted_by=current_user.id,
                    document_number=document_number,
                )

                # Bestand aktualisieren
                product.number = new_stock

                db.session.add(adjustment)
                db.session.commit()

                flash(f"✅ Bestandsanpassung erfolgreich erstellt! Neuer Bestand: {new_stock}", "success")
                return redirect(url_for("list_stock_adjustments"))

            except Exception as e:
                db.session.rollback()
                flash(f"Fehler beim Erstellen: {str(e)}", "error")

        products = Product.query.filter_by(active=True).order_by(Product.name).all()
        return render_template("stock_adjustments/create.html", products=products)

    # ============================================================================
    # Einstellungen
    # ============================================================================

    @app.route("/settings")
    @login_required
    @role_required("admin")
    def settings():
        """Einstellungen - Firmendaten anzeigen"""
        company_data = {
            "name": app.config.get("COMPANY_NAME"),
            "holder": app.config.get("COMPANY_HOLDER"),
            "street": app.config.get("COMPANY_STREET"),
            "zip": app.config.get("COMPANY_ZIP"),
            "city": app.config.get("COMPANY_CITY"),
            "country": app.config.get("COMPANY_COUNTRY"),
            "email": app.config.get("COMPANY_EMAIL"),
            "phone": app.config.get("COMPANY_PHONE"),
            "tax_id": app.config.get("COMPANY_TAX_ID"),
            "website": app.config.get("COMPANY_WEBSITE"),
        }
        bank_data = {
            "name": app.config.get("BANK_NAME"),
            "iban": app.config.get("BANK_IBAN"),
            "bic": app.config.get("BANK_BIC"),
        }
        return render_template("settings.html", company=company_data, bank=bank_data, config=app.config)

    @app.route("/settings/users")
    @login_required
    @role_required("admin")
    def list_users():
        """User-Verwaltung - Liste aller Benutzer"""
        users = User.query.order_by(User.created_at.desc()).all()
        return render_template("users/list.html", users=users)

    @app.route("/settings/users/new", methods=["GET", "POST"])
    @login_required
    @role_required("admin")
    def create_user():
        """Neuen Benutzer erstellen"""
        if request.method == "POST":
            try:
                username = request.form.get("username")
                email = request.form.get("email")
                password = request.form.get("password")
                role = request.form.get("role", "cashier")

                # Validierung
                if User.query.filter_by(username=username).first():
                    flash("Benutzername bereits vergeben.", "danger")
                    return render_template("users/create.html")

                if User.query.filter_by(email=email).first():
                    flash("E-Mail-Adresse bereits vergeben.", "danger")
                    return render_template("users/create.html")

                # Benutzer erstellen
                user = User(username=username, email=email, role=role, is_active=True)
                user.set_password(password)

                # Optional: Reseller-Verknüpfung
                if role == "reseller":
                    customer_id = request.form.get("reseller_customer_id")
                    if customer_id:
                        user.reseller_customer_id = int(customer_id)

                db.session.add(user)
                db.session.commit()

                flash(f'Benutzer "{username}" wurde erfolgreich erstellt.', "success")
                return redirect(url_for("list_users"))

            except Exception as e:
                db.session.rollback()
                flash(f"Fehler beim Erstellen des Benutzers: {str(e)}", "danger")

        # GET: Formular anzeigen
        customers = Customer.query.order_by(Customer.company_name).all()
        return render_template("users/create.html", customers=customers)

    @app.route("/settings/users/<int:user_id>/edit", methods=["GET", "POST"])
    @login_required
    @role_required("admin")
    def edit_user(user_id):
        """Benutzer bearbeiten"""
        user = User.query.get_or_404(user_id)

        if request.method == "POST":
            try:
                # E-Mail aktualisieren
                new_email = request.form.get("email")
                if new_email != user.email:
                    if User.query.filter_by(email=new_email).first():
                        flash("E-Mail-Adresse bereits vergeben.", "danger")
                        return render_template("users/edit.html", user=user, customers=Customer.query.all())
                    user.email = new_email

                # Rolle aktualisieren
                user.role = request.form.get("role", user.role)

                # Reseller-Verknüpfung
                if user.role == "reseller":
                    customer_id = request.form.get("reseller_customer_id")
                    user.reseller_customer_id = int(customer_id) if customer_id else None
                else:
                    user.reseller_customer_id = None

                # Aktiv-Status
                user.is_active = request.form.get("is_active") == "on"

                # 2FA-Pflicht
                user.totp_required = request.form.get("totp_required") == "on"

                # Passwort ändern (optional)
                new_password = request.form.get("new_password")
                if new_password:
                    user.set_password(new_password)

                db.session.commit()
                flash(f'Benutzer "{user.username}" wurde aktualisiert.', "success")
                return redirect(url_for("list_users"))

            except Exception as e:
                db.session.rollback()
                flash(f"Fehler beim Aktualisieren des Benutzers: {str(e)}", "danger")

        customers = Customer.query.order_by(Customer.company_name).all()
        return render_template("users/edit.html", user=user, customers=customers)

    @app.route("/settings/users/<int:user_id>/toggle-active", methods=["POST"])
    @login_required
    @role_required("admin")
    def toggle_user_active(user_id):
        """Benutzer aktivieren/deaktivieren"""
        user = User.query.get_or_404(user_id)

        if user.id == current_user.id:
            flash("Sie können sich nicht selbst deaktivieren.", "danger")
            return redirect(url_for("list_users"))

        user.is_active = not user.is_active
        db.session.commit()

        status = "aktiviert" if user.is_active else "deaktiviert"
        flash(f'Benutzer "{user.username}" wurde {status}.', "success")
        return redirect(url_for("list_users"))

    @app.route("/settings/users/<int:user_id>/reset-2fa", methods=["POST"])
    @login_required
    @role_required("admin")
    def reset_user_2fa(user_id):
        """2FA für Benutzer zurücksetzen"""
        user = User.query.get_or_404(user_id)

        user.totp_enabled = False
        user.totp_secret = None
        user.backup_codes = None
        db.session.commit()

        flash(f'2FA für "{user.username}" wurde zurückgesetzt.', "warning")
        return redirect(url_for("list_users"))

    @app.route("/settings/users/<int:user_id>/toggle-2fa-required", methods=["POST"])
    @login_required
    @role_required("admin")
    def toggle_user_2fa_required(user_id):
        """2FA-Pflicht für Benutzer umschalten"""
        user = User.query.get_or_404(user_id)

        user.totp_required = not user.totp_required
        db.session.commit()

        if user.totp_required:
            flash(
                f'2FA ist jetzt Pflicht für "{user.username}". Der Benutzer muss 2FA beim nächsten Login einrichten.',
                "success",
            )
        else:
            flash(f'2FA-Pflicht für "{user.username}" wurde aufgehoben.', "info")

        return redirect(url_for("list_users"))

    @app.route("/settings/users/<int:user_id>/delete", methods=["POST"])
    @login_required
    @role_required("admin")
    def delete_user(user_id):
        """Benutzer löschen"""
        user = User.query.get_or_404(user_id)

        if user.id == current_user.id:
            flash("Sie können sich nicht selbst löschen.", "danger")
            return redirect(url_for("list_users"))

        username = user.username
        db.session.delete(user)
        db.session.commit()

        flash(f'Benutzer "{username}" wurde gelöscht.', "success")
        return redirect(url_for("list_users"))

    @app.route("/payments/review")
    @login_required
    def payment_review():
        """Manuelle Prüfung von Zahlungseingängen"""
        # Nur ungelöste Probleme anzeigen
        pending_checks = (
            PaymentCheck.query.filter_by(resolved=False)
            .filter(PaymentCheck.status.in_(["mismatch", "not_found", "duplicate"]))
            .order_by(PaymentCheck.check_date.desc())
            .all()
        )

        return render_template("payments/review.html", checks=pending_checks)

    # ===== LIEFERSCHEINE & KOMMISSIONSLAGER =====

    @app.route("/delivery-notes")
    @login_required
    def list_delivery_notes():
        """Liste aller Lieferscheine"""
        delivery_notes = DeliveryNote.query.order_by(DeliveryNote.delivery_date.desc()).all()
        return render_template("delivery_notes/list.html", delivery_notes=delivery_notes)

    @app.route("/delivery-notes/new", methods=["GET", "POST"])
    @login_required
    def create_delivery_note():
        """Neuen Lieferschein erstellen"""
        if request.method == "POST":
            try:
                # Reseller auswählen
                customer_id = request.form.get("customer_id")
                Customer.query.get_or_404(customer_id)  # Validate customer exists

                # Lieferscheinnummer generieren
                today = datetime.now().date()
                prefix = f"LS-{today.strftime('%Y-%m-%d')}"

                # Höchste Nummer des Tages finden
                last_dn = (
                    DeliveryNote.query.filter(DeliveryNote.delivery_note_number.like(f"{prefix}%")).order_by(DeliveryNote.delivery_note_number.desc()).first()
                )

                if last_dn:
                    last_num = int(last_dn.delivery_note_number.split("-")[-1])
                    next_num = last_num + 1
                else:
                    next_num = 1

                delivery_note_number = f"{prefix}-{next_num:04d}"

                # Lieferschein erstellen
                delivery_note = DeliveryNote(
                    delivery_note_number=delivery_note_number,
                    customer_id=customer_id,
                    delivery_date=datetime.strptime(request.form.get("delivery_date"), "%Y-%m-%d").date(),
                    show_tax=request.form.get("show_tax") == "on",
                    notes=request.form.get("notes"),
                )

                db.session.add(delivery_note)
                db.session.flush()  # Um ID zu bekommen

                # Positionen hinzufügen
                product_ids = request.form.getlist("product_id[]")
                quantities = request.form.getlist("quantity[]")

                for idx, product_id in enumerate(product_ids):
                    if not product_id:
                        continue

                    product = Product.query.get(product_id)
                    quantity = Decimal(quantities[idx])

                    # BESTANDSPRÜFUNG: Prüfen ob genug auf Lager
                    if product.number < int(quantity):
                        raise Exception(f"Nicht genug Bestand für {product.name}! Verfügbar: {product.number}, benötigt: {int(quantity)}")

                    # Reseller-Preis verwenden
                    unit_price = product.reseller_price if product.reseller_price else product.price

                    item = DeliveryNoteItem(
                        delivery_note_id=delivery_note.id,
                        product_id=product_id,
                        description=f"{product.name} ({product.quantity})" if product.quantity else product.name,
                        quantity=quantity,
                        unit_price=unit_price,
                        position=idx,
                    )
                    item.calculate_total()
                    db.session.add(item)

                    # Bestand beim Reseller aktualisieren/erstellen
                    stock = ConsignmentStock.query.filter_by(customer_id=customer_id, product_id=product_id).first()

                    if stock:
                        stock.quantity += int(quantity)
                        stock.unit_price = unit_price
                        stock.last_delivery_note_id = delivery_note.id
                        stock.last_updated = datetime.utcnow()
                    else:
                        stock = ConsignmentStock(
                            customer_id=customer_id,
                            product_id=product_id,
                            quantity=int(quantity),
                            unit_price=unit_price,
                            last_delivery_note_id=delivery_note.id,
                        )
                        db.session.add(stock)

                    # Hauptbestand reduzieren
                    product.number -= int(quantity)

                db.session.commit()

                flash(f"Lieferschein {delivery_note_number} erfolgreich erstellt!", "success")
                return redirect(url_for("view_delivery_note", delivery_note_id=delivery_note.id))

            except Exception as e:
                db.session.rollback()
                flash(f"Fehler beim Erstellen des Lieferscheins: {str(e)}", "error")

        # GET: Formular anzeigen - NUR Reseller anzeigen
        customers = Customer.query.filter_by(reseller=True).order_by(Customer.company_name, Customer.last_name).all()
        products = Product.query.filter_by(active=True).order_by(Product.name).all()

        return render_template("delivery_notes/create.html", customers=customers, products=products)

    @app.route("/delivery-notes/<int:delivery_note_id>")
    @login_required
    def view_delivery_note(delivery_note_id):
        """Lieferschein anzeigen"""
        delivery_note = DeliveryNote.query.get_or_404(delivery_note_id)
        return render_template("delivery_notes/view.html", delivery_note=delivery_note)

    @app.route("/delivery-notes/<int:delivery_note_id>/pdf")
    @login_required
    def download_delivery_note_pdf(delivery_note_id):
        """Lieferschein als PDF herunterladen"""
        from delivery_note_service import generate_delivery_note_pdf

        delivery_note = DeliveryNote.query.get_or_404(delivery_note_id)
        pdf_path = generate_delivery_note_pdf(delivery_note, app.config["PDF_FOLDER"], app.config)

        return send_file(pdf_path, as_attachment=True, download_name=f"Lieferschein_{delivery_note.delivery_note_number}.pdf")

    @app.route("/consignment/<int:customer_id>")
    @login_required
    def consignment_stock_overview(customer_id):
        """Kommissionslager-Übersicht für einen Reseller"""
        customer = Customer.query.get_or_404(customer_id)
        stock_items = ConsignmentStock.query.filter_by(customer_id=customer_id).all()

        return render_template("consignment/overview.html", customer=customer, stock_items=stock_items)

    @app.route("/consignment/<int:customer_id>/update", methods=["POST"])
    @login_required
    def update_consignment_stock(customer_id):
        """Bestand im Kommissionslager korrigieren"""
        try:
            stock_id = request.form.get("stock_id")
            new_quantity = int(request.form.get("quantity"))

            stock = ConsignmentStock.query.get_or_404(stock_id)

            if stock.customer_id != customer_id:
                flash("Ungültiger Zugriff", "error")
                return redirect(url_for("consignment_stock_overview", customer_id=customer_id))

            old_quantity = stock.quantity
            stock.quantity = new_quantity
            stock.last_updated = datetime.utcnow()

            db.session.commit()

            flash(f"Bestand aktualisiert: {old_quantity} → {new_quantity}", "success")

        except Exception as e:
            db.session.rollback()
            flash(f"Fehler beim Aktualisieren: {str(e)}", "error")

        return redirect(url_for("consignment_stock_overview", customer_id=customer_id))

    @app.route("/consignment/<int:customer_id>/create-invoice", methods=["POST"])
    @login_required
    def create_invoice_from_consignment(customer_id):
        """Rechnung aus Kommissionslager erstellen"""
        try:
            Customer.query.get_or_404(customer_id)  # Validate customer exists

            # Alle markierten/verkauften Artikel
            product_ids = request.form.getlist("product_id[]")
            quantities = request.form.getlist("sold_quantity[]")
            show_tax = request.form.get("show_tax") == "on"

            if not product_ids or not any(q for q in quantities if q and int(q) > 0):
                flash("Keine Artikel zum Abrechnen ausgewählt", "warning")
                return redirect(url_for("consignment_stock_overview", customer_id=customer_id))

            # Rechnungsnummer generieren
            today = datetime.now().date()
            prefix = f"RE-{today.strftime('%Y-%m-%d')}"

            last_invoice = Invoice.query.filter(Invoice.invoice_number.like(f"{prefix}%")).order_by(Invoice.invoice_number.desc()).first()

            if last_invoice:
                last_num = int(last_invoice.invoice_number.split("-")[-1])
                next_num = last_num + 1
            else:
                next_num = 1

            invoice_number = f"{prefix}-{next_num:04d}"

            # Rechnung erstellen (OHNE sofort zur DB hinzuzufügen)
            due_date = today + timedelta(days=14)

            # Steuermodell basierend auf Checkbox
            # Wichtig: Bei Reseller-Preisen ist MwSt bereits im Preis enthalten (wie bei Landwirtschaft)
            if show_tax:
                tax_model = "landwirtschaft"  # Durchschnittssatzbesteuerung: Brutto = Netto, MwSt aus Summe berechnen
            else:
                tax_model = "kleinunternehmer"

            invoice = Invoice(
                invoice_number=invoice_number,
                customer_id=customer_id,
                invoice_date=today,
                due_date=due_date,
                status="draft",
                customer_type="reseller",
                tax_model=tax_model,
                tax_rate=Decimal("7.80") if show_tax else Decimal("0.00"),  # 7.80% ist Standard für landw. Urproduktion
                subtotal=Decimal("0.00"),
                tax_amount=Decimal("0.00"),
                total=Decimal("0.00"),
            )

            # WICHTIG: Hash SOFORT generieren bevor Invoice zur DB hinzugefügt wird
            invoice.generate_hash()

            # Positionen vorbereiten und Kommissionslager reduzieren
            line_items = []
            for idx, product_id in enumerate(product_ids):
                if not product_id or not quantities[idx]:
                    continue

                sold_qty = int(quantities[idx])
                if sold_qty <= 0:
                    continue

                stock = ConsignmentStock.query.filter_by(customer_id=customer_id, product_id=product_id).first()

                if not stock or stock.quantity < sold_qty:
                    raise Exception(f"Nicht genügend Bestand für Produkt ID {product_id}")

                # Rechnungsposition vorbereiten
                product = Product.query.get(product_id)
                line_item = LineItem(
                    product_id=product.id,
                    description=f"{product.name} ({product.quantity})" if product.quantity else product.name,
                    quantity=Decimal(sold_qty),
                    unit_price=stock.unit_price,  # Reseller-Preis
                    tax_rate=product.tax_rate if product.tax_rate else Decimal("7.80"),
                    position=idx,
                )
                line_item.calculate_total()
                line_items.append(line_item)

                # Kommissionslager reduzieren
                stock.quantity -= sold_qty
                stock.last_updated = datetime.utcnow()

            # Invoice zur Session hinzufügen und ID bekommen
            db.session.add(invoice)
            db.session.flush()

            # Jetzt Line Items mit invoice_id hinzufügen
            for line_item in line_items:
                line_item.invoice_id = invoice.id
                db.session.add(line_item)

            # Flush und Summen neu berechnen
            db.session.flush()
            invoice.calculate_totals()

            db.session.commit()

            flash(f"Rechnung {invoice_number} erfolgreich erstellt!", "success")
            return redirect(url_for("view_invoice", invoice_id=invoice.id))

        except Exception as e:
            db.session.rollback()
            flash(f"Fehler beim Erstellen der Rechnung: {str(e)}", "error")
            return redirect(url_for("consignment_stock_overview", customer_id=customer_id))

    @app.route("/payments/<int:check_id>/resolve", methods=["POST"])
    @login_required
    def resolve_payment_check(check_id):
        """Markiert eine Zahlungsprüfung als gelöst"""
        check = PaymentCheck.query.get_or_404(check_id)

        action = request.form.get("action")

        if action == "mark_paid":
            # Rechnung als bezahlt markieren
            if check.invoice_id:
                invoice = Invoice.query.get(check.invoice_id)
                invoice.status = "paid"
                check.resolved = True
                check.resolved_at = datetime.utcnow()
                check.notes = (check.notes or "") + " | Manuell als bezahlt markiert"
                db.session.commit()
                flash("Rechnung als bezahlt markiert", "success")
            else:
                flash("Keine Rechnung zugeordnet", "error")

        elif action == "ignore":
            # Als gelöst markieren ohne weitere Aktion
            check.resolved = True
            check.resolved_at = datetime.utcnow()
            check.notes = (check.notes or "") + " | Ignoriert/Bereits behandelt"
            db.session.commit()
            flash("Prüfung als erledigt markiert", "success")

        return redirect(url_for("payment_review"))

    @app.route("/settings/test-email", methods=["POST"])
    @login_required
    @role_required("admin")
    def test_email_settings():
        """E-Mail-Einstellungen (SMTP und IMAP) testen"""
        import imaplib
        import smtplib
        import socket

        results = {"smtp": {"success": False, "message": ""}, "imap": {"success": False, "message": ""}}

        # SMTP Test
        try:
            smtp_server = app.config.get("MAIL_SERVER")
            smtp_port = app.config.get("MAIL_PORT")
            smtp_username = app.config.get("MAIL_USERNAME")
            smtp_password = app.config.get("MAIL_PASSWORD")
            smtp_use_ssl = app.config.get("MAIL_USE_SSL")

            if not smtp_server or not smtp_username or not smtp_password:
                results["smtp"]["message"] = "SMTP-Konfiguration unvollständig (Server, Username oder Passwort fehlt)"
            else:
                # Verbindung aufbauen
                if smtp_use_ssl:
                    server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=10)
                else:
                    server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
                    if app.config.get("MAIL_USE_TLS"):
                        server.starttls()

                # Login versuchen
                server.login(smtp_username, smtp_password)
                server.quit()

                results["smtp"]["success"] = True
                results["smtp"]["message"] = f"Verbindung erfolgreich zu {smtp_server}:{smtp_port}"

        except smtplib.SMTPAuthenticationError:
            results["smtp"]["message"] = "Authentifizierung fehlgeschlagen - Benutzername oder Passwort falsch"
        except smtplib.SMTPException as e:
            results["smtp"]["message"] = f"SMTP-Fehler: {str(e)}"
        except socket.gaierror:
            results["smtp"]["message"] = f"Server {smtp_server} nicht erreichbar - DNS-Fehler"
        except socket.timeout:
            results["smtp"]["message"] = f"Zeitüberschreitung bei Verbindung zu {smtp_server}:{smtp_port}"
        except Exception as e:
            results["smtp"]["message"] = f"Unerwarteter Fehler: {str(e)}"

        # IMAP Test
        try:
            imap_server = app.config.get("IMAP_SERVER")
            imap_port = app.config.get("IMAP_PORT")
            imap_username = app.config.get("IMAP_USERNAME")
            imap_password = app.config.get("IMAP_PASSWORD")
            imap_use_ssl = app.config.get("IMAP_USE_SSL")

            if not imap_server or not imap_username or not imap_password:
                results["imap"]["message"] = "IMAP-Konfiguration unvollständig (Server, Username oder Passwort fehlt)"
            else:
                # Verbindung aufbauen
                if imap_use_ssl:
                    mail = imaplib.IMAP4_SSL(imap_server, imap_port)
                else:
                    mail = imaplib.IMAP4(imap_server, imap_port)

                # Login versuchen
                mail.login(imap_username, imap_password)

                # Mailboxen auflisten
                status, folders = mail.list()  # pylint: disable=unused-variable
                folder_count = len(folders) if folders else 0

                mail.logout()

                results["imap"]["success"] = True
                results["imap"]["message"] = f"Verbindung erfolgreich zu {imap_server}:{imap_port} ({folder_count} Ordner gefunden)"

        except imaplib.IMAP4.error as e:
            error_msg = str(e)
            if "authentication failed" in error_msg.lower():
                results["imap"]["message"] = "Authentifizierung fehlgeschlagen - Benutzername oder Passwort falsch"
            else:
                results["imap"]["message"] = f"IMAP-Fehler: {error_msg}"
        except socket.gaierror:
            results["imap"]["message"] = f"Server {imap_server} nicht erreichbar - DNS-Fehler"
        except socket.timeout:
            results["imap"]["message"] = f"Zeitüberschreitung bei Verbindung zu {imap_server}:{imap_port}"
        except Exception as e:
            results["imap"]["message"] = f"Unerwarteter Fehler: {str(e)}"

        # Flash-Nachrichten erstellen
        if results["smtp"]["success"]:
            flash(f'✓ SMTP: {results["smtp"]["message"]}', "success")
        else:
            flash(f'✗ SMTP: {results["smtp"]["message"]}', "error")

        if results["imap"]["success"]:
            flash(f'✓ IMAP: {results["imap"]["message"]}', "success")
        else:
            flash(f'✗ IMAP: {results["imap"]["message"]}', "error")

        return redirect(url_for("settings"))

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
