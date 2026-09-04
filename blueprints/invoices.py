"""Rechnungsverwaltung (CRUD, Storno, PDF, E-Mail, Mahnwesen) und
Bestandsanpassungen (Eigenentnahme, Inventur, Verderb, Bruch -- GoBD-dokumentiert)."""

from datetime import datetime, timedelta
from decimal import Decimal

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from invoice_numbering import generate_invoice_number
from models import ConsignmentStock, Customer, Invoice, InvoicePdfArchive, InvoiceStatusLog, LineItem, Product, Reminder, StockAdjustment, db

invoices_bp = Blueprint("invoices", __name__)


@invoices_bp.route("/invoices")
@login_required
def list_invoices():
    """Liste aller Rechnungen"""
    status_filter = request.args.get("status", None)
    custom_filter = request.args.get("filter", None)
    query = Invoice.query

    if status_filter:
        query = query.filter_by(status=status_filter)
    elif custom_filter == "storno":
        query = query.filter(Invoice.invoice_number.like("STORNO-%"))
    elif custom_filter == "open":
        query = query.filter_by(status="sent")
    elif custom_filter == "overdue":
        overdue_date = datetime.now().date() - timedelta(days=10)
        query = query.filter(Invoice.status == "sent", Invoice.due_date.isnot(None), Invoice.due_date < overdue_date)

    invoices = query.order_by(Invoice.invoice_date.desc()).all()
    return render_template("invoices/list.html", invoices=invoices, status_filter=status_filter)


@invoices_bp.route("/invoices/new", methods=["GET", "POST"])
@login_required
def create_invoice():
    """Neue Rechnung erstellen"""
    if request.method == "POST":
        try:
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
                db.session.flush()

            invoice_number = generate_invoice_number()

            tax_model = request.form.get("tax_model", "landwirtschaft")

            customer_type = request.form.get("customer_type", "endkunde")

            if tax_model == "standard":
                tax_rate = Decimal(str(request.form.get("tax_rate", current_app.config.get("DEFAULT_TAX_RATE", 19.0))))
            elif tax_model == "landwirtschaft":
                tax_rate = Decimal(str(current_app.config.get("LANDWIRTSCHAFTLICHE_URPRODUKTION_TAX_RATE", 7.8)))
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

            descriptions = request.form.getlist("description[]")
            quantities = request.form.getlist("quantity[]")
            unit_prices = request.form.getlist("unit_price[]")
            product_ids = request.form.getlist("product_id[]")

            for idx, (desc, qty, price, prod_id) in enumerate(zip(descriptions, quantities, unit_prices, product_ids)):
                if desc and qty and price:
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

            invoice.calculate_totals()
            invoice.generate_hash()

            db.session.add(invoice)
            db.session.commit()

            flash(f"Rechnung {invoice_number} erfolgreich erstellt!", "success")
            return redirect(url_for("invoices.view_invoice", invoice_id=invoice.id))

        except Exception as e:
            db.session.rollback()
            flash(f"Fehler beim Erstellen der Rechnung: {str(e)}", "error")
            return redirect(url_for("invoices.create_invoice"))

    customers = Customer.query.order_by(Customer.company_name, Customer.last_name).all()
    today = datetime.now().date()
    due_date_default = today + timedelta(days=14)
    default_tax_rate = current_app.config.get("DEFAULT_TAX_RATE", 19.00)
    landw_tax_rate = current_app.config.get("LANDWIRTSCHAFTLICHE_URPRODUKTION_TAX_RATE", 7.80)

    return render_template(
        "invoices/create.html",
        customers=customers,
        today=today,
        due_date_default=due_date_default,
        default_tax_rate=default_tax_rate,
        landw_tax_rate=landw_tax_rate,
    )


@invoices_bp.route("/invoices/<int:invoice_id>")
@login_required
def view_invoice(invoice_id):
    """Einzelne Rechnung anzeigen"""
    invoice = Invoice.query.get_or_404(invoice_id)
    is_valid = invoice.verify_hash()
    return render_template("invoices/view.html", invoice=invoice, is_valid=is_valid)


@invoices_bp.route("/invoices/<int:invoice_id>/status/<status>")
@login_required
def update_invoice_status(invoice_id, status):
    """Status einer Rechnung ändern (GoBD-konform mit Audit Trail)"""
    invoice = Invoice.query.get_or_404(invoice_id)

    allowed_statuses = ["draft", "sent", "paid", "cancelled"]
    if status not in allowed_statuses:
        flash(f"Ungültiger Status: {status}", "error")
        return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))

    old_status = invoice.status

    if old_status == "sent" and status == "draft":
        flash(
            "Fehler: Versendete Rechnungen können nicht zurück in Entwurf gesetzt werden (GoBD-Konformität).",
            "error",
        )
        return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))

    if old_status == "paid" and status != "cancelled":
        flash("Fehler: Bezahlte Rechnungen können nur storniert werden.", "error")
        return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))

    if status == "cancelled" and old_status != "cancelled":
        try:
            for line_item in invoice.line_items:
                if line_item.product_id:
                    product = Product.query.get(line_item.product_id)
                    if product:
                        product.number += int(line_item.quantity)

                        if invoice.customer_type == "reseller":
                            stock = ConsignmentStock.query.filter_by(customer_id=invoice.customer_id, product_id=line_item.product_id).first()
                            if stock:
                                stock.quantity += int(line_item.quantity)

            flash("Bestand wurde zurückgebucht.", "info")
        except Exception as e:
            db.session.rollback()
            flash(f"Fehler bei Bestandsrückbuchung: {str(e)}", "error")
            return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))

    invoice.status = status

    status_log = InvoiceStatusLog(
        invoice_id=invoice.id,
        old_status=old_status,
        new_status=status,
        changed_by=current_user.username,
        reason=request.args.get("reason", None),
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

    return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))


@invoices_bp.route("/invoices/<int:invoice_id>/delete", methods=["POST"])
@login_required
def delete_invoice(invoice_id):
    """Rechnung löschen (nur bei Status 'draft' erlaubt - GoBD-konform)"""
    invoice = Invoice.query.get_or_404(invoice_id)

    if invoice.status != "draft":
        flash(
            "Fehler: Nur Entwürfe können gelöscht werden. Versendete Rechnungen müssen storniert werden (GoBD-Konformität).",
            "error",
        )
        return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))

    try:
        invoice_number = invoice.invoice_number

        for line_item in invoice.line_items:
            if line_item.product_id:
                product = Product.query.get(line_item.product_id)
                if product:
                    product.number += int(line_item.quantity)

                    if invoice.customer_type == "reseller":
                        stock = ConsignmentStock.query.filter_by(customer_id=invoice.customer_id, product_id=line_item.product_id).first()
                        if stock:
                            stock.quantity += int(line_item.quantity)

        for line_item in invoice.line_items:
            db.session.delete(line_item)

        for log in invoice.status_history:
            db.session.delete(log)

        db.session.delete(invoice)
        db.session.commit()

        flash(f'Entwurf "{invoice_number}" wurde gelöscht und Bestand zurückgebucht.', "success")
        return redirect(url_for("invoices.list_invoices"))

    except Exception as e:
        db.session.rollback()
        flash(f"Fehler beim Löschen: {str(e)}", "error")
        return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))


@invoices_bp.route("/invoices/<int:invoice_id>/create-cancellation", methods=["GET", "POST"])
@login_required
def create_cancellation_invoice(invoice_id):
    """Erstellt eine Stornorechnung (GoBD-konform)"""
    original_invoice = Invoice.query.get_or_404(invoice_id)

    if original_invoice.status not in ["sent", "paid"]:
        flash("Nur versendete oder bezahlte Rechnungen können storniert werden.", "error")
        return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))

    if original_invoice.status == "cancelled":
        flash("Diese Rechnung wurde bereits storniert.", "error")
        return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))

    if request.method == "POST":
        try:
            reason = request.form.get("reason", "Stornierung auf Kundenwunsch")

            today = datetime.now().date()
            prefix = f"STORNO-{today.strftime('%Y-%m-%d')}"

            last_invoice = Invoice.query.filter(Invoice.invoice_number.like(f"{prefix}%")).order_by(Invoice.invoice_number.desc()).first()

            if last_invoice:
                last_num = int(last_invoice.invoice_number.split("-")[-1])
                next_num = last_num + 1
            else:
                next_num = 1

            cancellation_number = f"{prefix}-{next_num:04d}"

            cancellation_invoice = Invoice(
                invoice_number=cancellation_number,
                customer_id=original_invoice.customer_id,
                invoice_date=today,
                due_date=today,
                status="sent",
                customer_type=original_invoice.customer_type,
                tax_model=original_invoice.tax_model,
                tax_rate=original_invoice.tax_rate,
                subtotal=-original_invoice.subtotal,
                tax_amount=-original_invoice.tax_amount,
                total=-original_invoice.total,
                notes=f"Stornierung von Rechnung {original_invoice.invoice_number}\nGrund: {reason}",
            )

            line_items_list = []
            for orig_item in original_invoice.line_items:
                cancellation_item = LineItem(
                    product_id=orig_item.product_id,
                    description=f"STORNO: {orig_item.description}",
                    quantity=-orig_item.quantity,
                    unit_price=orig_item.unit_price,
                    tax_rate=orig_item.tax_rate,
                    total=-orig_item.total,
                    position=orig_item.position,
                )
                line_items_list.append(cancellation_item)

            cancellation_invoice.line_items = line_items_list

            cancellation_invoice.generate_hash()

            db.session.add(cancellation_invoice)

            for orig_item in original_invoice.line_items:
                if orig_item.product_id:
                    product = Product.query.get(orig_item.product_id)
                    if product:
                        product.number += int(orig_item.quantity)

                        if original_invoice.customer_type == "reseller":
                            stock = ConsignmentStock.query.filter_by(customer_id=original_invoice.customer_id, product_id=orig_item.product_id).first()
                            if stock:
                                stock.quantity += int(orig_item.quantity)

            db.session.flush()

            original_status = original_invoice.status

            original_invoice.status = "cancelled"
            original_invoice.notes = (original_invoice.notes or "") + f"\n\nStorniert durch {cancellation_number} am {today.strftime('%d.%m.%Y')}"

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
            return redirect(url_for("invoices.view_invoice", invoice_id=cancellation_invoice.id))

        except Exception as e:
            db.session.rollback()
            flash(f"Fehler beim Erstellen der Stornorechnung: {str(e)}", "error")
            return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))

    return render_template("invoices/create_cancellation.html", invoice=original_invoice)


@invoices_bp.route("/invoices/<int:invoice_id>/pdf")
@login_required
def download_invoice_pdf(invoice_id):
    """Rechnung als PDF herunterladen (GoBD-konform mit PDF-Archivierung)"""
    import hashlib
    import os

    from pdf_service import generate_invoice_pdf

    invoice = Invoice.query.get_or_404(invoice_id)
    pdf_path = generate_invoice_pdf(invoice, current_app.config["PDF_FOLDER"], current_app.config)

    if invoice.status == "sent":
        existing_archive = InvoicePdfArchive.query.filter_by(invoice_id=invoice.id, pdf_filename=os.path.basename(pdf_path)).first()

        if not existing_archive:
            with open(pdf_path, "rb") as f:
                pdf_data = f.read()
                pdf_hash = hashlib.sha256(pdf_data).hexdigest()
                file_size = len(pdf_data)

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
                current_app.logger.error("PDF-Archivierung fehlgeschlagen: %s", str(e))

    return send_file(pdf_path, as_attachment=True, download_name=f"Rechnung_{invoice.invoice_number}.pdf")


@invoices_bp.route("/invoices/<int:invoice_id>/send-email", methods=["GET", "POST"])
@login_required
def send_invoice_email(invoice_id):
    """Rechnung per E-Mail versenden"""
    from email_service import send_invoice_email as send_email
    from pdf_service import generate_invoice_pdf

    invoice = Invoice.query.get_or_404(invoice_id)

    if request.method == "POST":
        recipient_email = request.form.get("recipient_email") or invoice.customer.email
        cc_emails = request.form.get("cc_emails", "").strip()
        cc_list = [email.strip() for email in cc_emails.split(",") if email.strip()] if cc_emails else None

        pdf_path = generate_invoice_pdf(invoice, current_app.config["PDF_FOLDER"], current_app.config)

        success = send_email(invoice, pdf_path, recipient_email, cc_list)

        if success:
            if invoice.status == "draft":
                invoice.status = "sent"
                db.session.commit()

            flash(f"Rechnung erfolgreich an {recipient_email} versendet!", "success")
            return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))
        else:
            flash("Fehler beim Versenden der E-Mail. Bitte überprüfen Sie die E-Mail-Konfiguration.", "error")

    return render_template("invoices/send_email.html", invoice=invoice)


@invoices_bp.route("/invoices/<int:invoice_id>/reminder", methods=["GET", "POST"])
@login_required
def create_reminder(invoice_id):
    """Mahnung erstellen und versenden"""
    from email_service import send_email
    from reminder_service import generate_reminder_pdf

    invoice = Invoice.query.get_or_404(invoice_id)

    if invoice.status != "sent":
        flash("Mahnungen können nur für versendete, unbezahlte Rechnungen erstellt werden.", "error")
        return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))

    if request.method == "POST":
        action = request.form.get("action")

        existing_reminders = Reminder.query.filter_by(invoice_id=invoice_id).order_by(Reminder.reminder_level.desc()).first()
        reminder_level = 1 if not existing_reminders else existing_reminders.reminder_level + 1

        reminder = Reminder(
            invoice_id=invoice_id,
            reminder_level=reminder_level,
            reminder_date=datetime.utcnow(),
            reminder_fee=5.00 if reminder_level == 1 else 10.00,
        )
        db.session.add(reminder)
        db.session.commit()

        pdf_path = generate_reminder_pdf(invoice, reminder, current_app.config["PDF_FOLDER"], current_app.config)

        if action == "download":
            reminder.sent_via = "pdf"
            reminder.sent_date = datetime.utcnow()
            db.session.commit()

            return send_file(pdf_path, as_attachment=True, download_name=f"Mahnung_{reminder_level}_{invoice.invoice_number}.pdf")

        elif action == "send_email":
            if not invoice.customer.email:
                flash("Kunde hat keine E-Mail-Adresse hinterlegt.", "error")
                return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))

            subject = f"{reminder_level}. Mahnung - Rechnung {invoice.invoice_number}"

            if reminder_level == 1:
                body = f"""Sehr geehrte Damen und Herren,

leider haben wir bisher keinen Zahlungseingang für die Rechnung {invoice.invoice_number} feststellen können.

Bitte begleichen Sie den ausstehenden Betrag von {float(invoice.total + reminder.reminder_fee):.2f} €
(inkl. {float(reminder.reminder_fee):.2f} € Mahngebühr) innerhalb der nächsten 7 Tage.

Die Mahnung finden Sie im Anhang.

Mit freundlichen Grüßen
{current_app.config.get('COMPANY_NAME', '')}"""
            else:
                body = f"""Sehr geehrte Damen und Herren,

trotz unserer bisherigen Mahnungen haben wir noch keinen Zahlungseingang für die Rechnung {invoice.invoice_number} feststellen können.

Wir fordern Sie auf, den ausstehenden Betrag von {float(invoice.total + reminder.reminder_fee):.2f} €
(inkl. {float(reminder.reminder_fee):.2f} € Mahngebühr) umgehend zu begleichen.

Die Mahnung finden Sie im Anhang.

Mit freundlichen Grüßen
{current_app.config.get('COMPANY_NAME', '')}"""

            success = send_email(to=invoice.customer.email, subject=subject, body=body, attachment_path=pdf_path)

            if success:
                reminder.sent_via = "email"
                reminder.sent_date = datetime.utcnow()
                db.session.commit()
                flash(f"Mahnung erfolgreich per E-Mail an {invoice.customer.email} versendet!", "success")
            else:
                flash("Fehler beim Versenden der E-Mail.", "error")

            return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))

    existing_reminders = Reminder.query.filter_by(invoice_id=invoice_id).order_by(Reminder.reminder_date.desc()).all()
    next_level = 1 if not existing_reminders else existing_reminders[0].reminder_level + 1

    return render_template(
        "invoices/create_reminder.html",
        invoice=invoice,
        existing_reminders=existing_reminders,
        next_level=next_level,
    )


@invoices_bp.route("/stock-adjustments")
@login_required
def list_stock_adjustments():
    """Liste aller Bestandsanpassungen"""
    adjustments = StockAdjustment.query.order_by(StockAdjustment.adjusted_at.desc()).limit(100).all()
    return render_template("stock_adjustments/list.html", adjustments=adjustments)


@invoices_bp.route("/stock-adjustments/export-pdf")
@login_required
def export_stock_adjustments_pdf():
    """Exportiere alle Bestandsanpassungen als PDF (GoBD-konform)"""
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    adjustment_type = request.args.get("adjustment_type")

    query = StockAdjustment.query

    if start_date:
        query = query.filter(StockAdjustment.adjusted_at >= datetime.strptime(start_date, "%Y-%m-%d"))
    if end_date:
        query = query.filter(StockAdjustment.adjusted_at <= datetime.strptime(end_date, "%Y-%m-%d"))
    if adjustment_type:
        query = query.filter(StockAdjustment.adjustment_type == adjustment_type)

    adjustments = query.order_by(StockAdjustment.adjusted_at.desc()).all()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
    elements = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("CustomTitle", parent=styles["Heading1"], fontSize=16, spaceAfter=30)

    title = Paragraph("Bestandsanpassungen - Übersicht (GoBD-konform)", title_style)
    elements.append(title)

    if start_date or end_date:
        period = f"Zeitraum: {start_date or 'Anfang'} bis {end_date or 'Heute'}"
        elements.append(Paragraph(period, styles["Normal"]))
        elements.append(Spacer(1, 0.5 * cm))

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

    elements.append(Spacer(1, 1 * cm))
    footer_text = f"Erstellt am: {datetime.now().strftime('%d.%m.%Y %H:%M')} | Anzahl Einträge: {len(adjustments)}"
    elements.append(Paragraph(footer_text, styles["Normal"]))

    doc.build(elements)
    buffer.seek(0)

    filename = f"Bestandsanpassungen_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")


@invoices_bp.route("/stock-adjustments/create", methods=["GET", "POST"])
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
                return redirect(url_for("invoices.create_stock_adjustment"))

            product = Product.query.get(int(product_id))
            if not product:
                flash("Produkt nicht gefunden.", "error")
                return redirect(url_for("invoices.create_stock_adjustment"))

            old_stock = product.number
            new_stock = old_stock + quantity

            if new_stock < 0:
                flash(f"Fehler: Bestand würde negativ werden! Aktuell: {old_stock}, Änderung: {quantity}", "error")
                return redirect(url_for("invoices.create_stock_adjustment"))

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

            product.number = new_stock

            db.session.add(adjustment)
            db.session.commit()

            flash(f"✅ Bestandsanpassung erfolgreich erstellt! Neuer Bestand: {new_stock}", "success")
            return redirect(url_for("invoices.list_stock_adjustments"))

        except Exception as e:
            db.session.rollback()
            flash(f"Fehler beim Erstellen: {str(e)}", "error")

    products = Product.query.filter_by(active=True).order_by(Product.name).all()
    return render_template("stock_adjustments/create.html", products=products)
