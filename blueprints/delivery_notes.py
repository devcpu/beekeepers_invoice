"""Lieferscheine, Kommissionslager und Zahlungsabgleich fuer Reseller."""

from datetime import datetime, timedelta
from decimal import Decimal

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import login_required

from models import ConsignmentStock, Customer, DeliveryNote, DeliveryNoteItem, Invoice, LineItem, PaymentCheck, Product, db

delivery_notes_bp = Blueprint("delivery_notes", __name__)


@delivery_notes_bp.route("/payments/review")
@login_required
def payment_review():
    """Manuelle Prüfung von Zahlungseingängen"""
    pending_checks = (
        PaymentCheck.query.filter_by(resolved=False)
        .filter(PaymentCheck.status.in_(["mismatch", "not_found", "duplicate"]))
        .order_by(PaymentCheck.check_date.desc())
        .all()
    )

    return render_template("payments/review.html", checks=pending_checks)


@delivery_notes_bp.route("/delivery-notes")
@login_required
def list_delivery_notes():
    """Liste aller Lieferscheine"""
    delivery_notes = DeliveryNote.query.order_by(DeliveryNote.delivery_date.desc()).all()
    return render_template("delivery_notes/list.html", delivery_notes=delivery_notes)


@delivery_notes_bp.route("/delivery-notes/new", methods=["GET", "POST"])
@login_required
def create_delivery_note():
    """Neuen Lieferschein erstellen"""
    if request.method == "POST":
        try:
            customer_id = request.form.get("customer_id")
            Customer.query.get_or_404(customer_id)

            today = datetime.now().date()
            prefix = f"LS-{today.strftime('%Y-%m-%d')}"

            last_dn = (
                DeliveryNote.query.filter(DeliveryNote.delivery_note_number.like(f"{prefix}%")).order_by(DeliveryNote.delivery_note_number.desc()).first()
            )

            if last_dn:
                last_num = int(last_dn.delivery_note_number.split("-")[-1])
                next_num = last_num + 1
            else:
                next_num = 1

            delivery_note_number = f"{prefix}-{next_num:04d}"

            delivery_note = DeliveryNote(
                delivery_note_number=delivery_note_number,
                customer_id=customer_id,
                delivery_date=datetime.strptime(request.form.get("delivery_date"), "%Y-%m-%d").date(),
                show_tax=request.form.get("show_tax") == "on",
                notes=request.form.get("notes"),
            )

            db.session.add(delivery_note)
            db.session.flush()

            product_ids = request.form.getlist("product_id[]")
            quantities = request.form.getlist("quantity[]")

            for idx, product_id in enumerate(product_ids):
                if not product_id:
                    continue

                product = Product.query.get(product_id)
                quantity = Decimal(quantities[idx])

                if product.number < int(quantity):
                    raise Exception(f"Nicht genug Bestand für {product.name}! Verfügbar: {product.number}, benötigt: {int(quantity)}")

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

                product.number -= int(quantity)

            db.session.commit()

            flash(f"Lieferschein {delivery_note_number} erfolgreich erstellt!", "success")
            return redirect(url_for("delivery_notes.view_delivery_note", delivery_note_id=delivery_note.id))

        except Exception as e:
            db.session.rollback()
            flash(f"Fehler beim Erstellen des Lieferscheins: {str(e)}", "error")

    customers = Customer.query.filter_by(reseller=True).order_by(Customer.company_name, Customer.last_name).all()
    products = Product.query.filter_by(active=True).order_by(Product.name).all()

    return render_template("delivery_notes/create.html", customers=customers, products=products)


@delivery_notes_bp.route("/delivery-notes/<int:delivery_note_id>")
@login_required
def view_delivery_note(delivery_note_id):
    """Lieferschein anzeigen"""
    delivery_note = DeliveryNote.query.get_or_404(delivery_note_id)
    return render_template("delivery_notes/view.html", delivery_note=delivery_note)


@delivery_notes_bp.route("/delivery-notes/<int:delivery_note_id>/pdf")
@login_required
def download_delivery_note_pdf(delivery_note_id):
    """Lieferschein als PDF herunterladen"""
    from delivery_note_service import generate_delivery_note_pdf

    delivery_note = DeliveryNote.query.get_or_404(delivery_note_id)
    pdf_path = generate_delivery_note_pdf(delivery_note, current_app.config["PDF_FOLDER"], current_app.config)

    return send_file(pdf_path, as_attachment=True, download_name=f"Lieferschein_{delivery_note.delivery_note_number}.pdf")


@delivery_notes_bp.route("/consignment/<int:customer_id>")
@login_required
def consignment_stock_overview(customer_id):
    """Kommissionslager-Übersicht für einen Reseller"""
    customer = Customer.query.get_or_404(customer_id)
    stock_items = ConsignmentStock.query.filter_by(customer_id=customer_id).all()

    return render_template("consignment/overview.html", customer=customer, stock_items=stock_items)


@delivery_notes_bp.route("/consignment/<int:customer_id>/update", methods=["POST"])
@login_required
def update_consignment_stock(customer_id):
    """Bestand im Kommissionslager korrigieren"""
    try:
        stock_id = request.form.get("stock_id")
        new_quantity = int(request.form.get("quantity"))

        stock = ConsignmentStock.query.get_or_404(stock_id)

        if stock.customer_id != customer_id:
            flash("Ungültiger Zugriff", "error")
            return redirect(url_for("delivery_notes.consignment_stock_overview", customer_id=customer_id))

        old_quantity = stock.quantity
        stock.quantity = new_quantity
        stock.last_updated = datetime.utcnow()

        db.session.commit()

        flash(f"Bestand aktualisiert: {old_quantity} → {new_quantity}", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Fehler beim Aktualisieren: {str(e)}", "error")

    return redirect(url_for("delivery_notes.consignment_stock_overview", customer_id=customer_id))


@delivery_notes_bp.route("/consignment/<int:customer_id>/create-invoice", methods=["POST"])
@login_required
def create_invoice_from_consignment(customer_id):
    """Rechnung aus Kommissionslager erstellen"""
    try:
        Customer.query.get_or_404(customer_id)

        product_ids = request.form.getlist("product_id[]")
        quantities = request.form.getlist("sold_quantity[]")
        show_tax = request.form.get("show_tax") == "on"

        if not product_ids or not any(q for q in quantities if q and int(q) > 0):
            flash("Keine Artikel zum Abrechnen ausgewählt", "warning")
            return redirect(url_for("delivery_notes.consignment_stock_overview", customer_id=customer_id))

        today = datetime.now().date()
        prefix = f"RE-{today.strftime('%Y-%m-%d')}"

        last_invoice = Invoice.query.filter(Invoice.invoice_number.like(f"{prefix}%")).order_by(Invoice.invoice_number.desc()).first()

        if last_invoice:
            last_num = int(last_invoice.invoice_number.split("-")[-1])
            next_num = last_num + 1
        else:
            next_num = 1

        invoice_number = f"{prefix}-{next_num:04d}"

        due_date = today + timedelta(days=14)

        if show_tax:
            tax_model = "landwirtschaft"
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
            tax_rate=Decimal("7.80") if show_tax else Decimal("0.00"),
            subtotal=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            total=Decimal("0.00"),
        )

        invoice.generate_hash()

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

            product = Product.query.get(product_id)
            line_item = LineItem(
                product_id=product.id,
                description=f"{product.name} ({product.quantity})" if product.quantity else product.name,
                quantity=Decimal(sold_qty),
                unit_price=stock.unit_price,
                tax_rate=product.tax_rate if product.tax_rate else Decimal("7.80"),
                position=idx,
            )
            line_item.calculate_total()
            line_items.append(line_item)

            stock.quantity -= sold_qty
            stock.last_updated = datetime.utcnow()

        db.session.add(invoice)
        db.session.flush()

        for line_item in line_items:
            line_item.invoice_id = invoice.id
            db.session.add(line_item)

        db.session.flush()
        invoice.calculate_totals()

        db.session.commit()

        flash(f"Rechnung {invoice_number} erfolgreich erstellt!", "success")
        return redirect(url_for("invoices.view_invoice", invoice_id=invoice.id))

    except Exception as e:
        db.session.rollback()
        flash(f"Fehler beim Erstellen der Rechnung: {str(e)}", "error")
        return redirect(url_for("delivery_notes.consignment_stock_overview", customer_id=customer_id))


@delivery_notes_bp.route("/payments/<int:check_id>/resolve", methods=["POST"])
@login_required
def resolve_payment_check(check_id):
    """Markiert eine Zahlungsprüfung als gelöst"""
    check = PaymentCheck.query.get_or_404(check_id)

    action = request.form.get("action")

    if action == "mark_paid":
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
        check.resolved = True
        check.resolved_at = datetime.utcnow()
        check.notes = (check.notes or "") + " | Ignoriert/Bereits behandelt"
        db.session.commit()
        flash("Prüfung als erledigt markiert", "success")

    return redirect(url_for("delivery_notes.payment_review"))
