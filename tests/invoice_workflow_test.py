"""GoBD-kritische End-to-End-Pfade: Rechnungs-Lebenszyklus, Storno-Flow,
Kommissionsbestand-Rueckbuchung, POS-Verkauf, PDF-Archivierung,
Mahnwesen. Hoechstes Schadenspotenzial, daher eigene Datei mit breiter
Abdeckung (siehe Plan-Datei joyful-swinging-forest.md, Teil A4).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from conftest import login, make_invoice, make_line_item
from models import ConsignmentStock, Invoice, InvoicePdfArchive, InvoiceStatusLog, Reminder


# ---------------------------------------------------------------------------
# Vollstaendiger Rechnungs-Lebenszyklus: draft -> sent -> paid
# ---------------------------------------------------------------------------


def test_invoice_lifecycle_draft_to_sent_to_paid(client, admin_user, db_session, customer):
    invoice = make_invoice(customer, invoice_number="RE-LIFECYCLE-0001")
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice.calculate_totals()
    invoice.generate_hash()
    db_session.add(invoice)
    db_session.commit()
    assert invoice.status == "draft"

    login(client, "admin")

    # draft -> sent
    client.get(f"/invoices/{invoice.id}/status/sent", follow_redirects=True)
    db_session.refresh(invoice)
    assert invoice.status == "sent"

    log_sent = InvoiceStatusLog.query.filter_by(invoice_id=invoice.id, new_status="sent").first()
    assert log_sent is not None
    assert log_sent.old_status == "draft"
    assert log_sent.changed_by == "admin"

    # sent -> paid
    client.get(f"/invoices/{invoice.id}/status/paid", follow_redirects=True)
    db_session.refresh(invoice)
    assert invoice.status == "paid"

    log_paid = InvoiceStatusLog.query.filter_by(invoice_id=invoice.id, new_status="paid").first()
    assert log_paid is not None
    assert log_paid.old_status == "sent"
    assert log_paid.changed_by == "admin"


# ---------------------------------------------------------------------------
# Verbotene Status-Uebergaenge (GoBD)
# ---------------------------------------------------------------------------


def test_sent_to_draft_is_rejected(client, admin_user, db_session, customer):
    invoice = make_invoice(customer, invoice_number="RE-FORBIDDEN-0001")
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice.calculate_totals()
    invoice.generate_hash()
    invoice.status = "sent"
    db_session.add(invoice)
    db_session.commit()

    login(client, "admin")
    response = client.get(f"/invoices/{invoice.id}/status/draft", follow_redirects=True)

    assert "können nicht zurück in Entwurf gesetzt werden" in response.get_data(as_text=True)
    db_session.refresh(invoice)
    assert invoice.status == "sent"


def test_paid_to_sent_is_rejected(client, admin_user, db_session, customer):
    invoice = make_invoice(customer, invoice_number="RE-FORBIDDEN-0002")
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice.calculate_totals()
    invoice.generate_hash()
    invoice.status = "paid"
    db_session.add(invoice)
    db_session.commit()

    login(client, "admin")
    response = client.get(f"/invoices/{invoice.id}/status/sent", follow_redirects=True)

    assert "können nur storniert werden" in response.get_data(as_text=True)
    db_session.refresh(invoice)
    assert invoice.status == "paid"


def test_delete_sent_invoice_is_rejected(client, admin_user, db_session, customer):
    invoice = make_invoice(customer, invoice_number="RE-FORBIDDEN-0003")
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice.calculate_totals()
    invoice.generate_hash()
    invoice.status = "sent"
    db_session.add(invoice)
    db_session.commit()
    invoice_id = invoice.id

    login(client, "admin")
    response = client.post(f"/invoices/{invoice_id}/delete", follow_redirects=True)

    assert "müssen storniert werden" in response.get_data(as_text=True)
    assert Invoice.query.get(invoice_id) is not None


def test_delete_draft_invoice_succeeds_and_rebooks_stock(client, admin_user, db_session, customer, product):
    product.number = 50
    db_session.commit()

    invoice = make_invoice(customer, invoice_number="RE-DELETE-DRAFT-0001")
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("3.00"), product_id=product.id)]
    invoice.calculate_totals()
    invoice.generate_hash()
    db_session.add(invoice)
    db_session.commit()
    invoice_id = invoice.id

    login(client, "admin")
    response = client.post(f"/invoices/{invoice_id}/delete", follow_redirects=True)

    assert "wurde gelöscht" in response.get_data(as_text=True)
    assert Invoice.query.get(invoice_id) is None
    db_session.refresh(product)
    assert product.number == 53  # 50 + 3 zurueckgebucht


# ---------------------------------------------------------------------------
# Storno-Flow
# ---------------------------------------------------------------------------


def test_storno_creates_negative_cancellation_invoice_and_rebooks_stock(client, admin_user, db_session, customer, product):
    product.number = 50
    db_session.commit()

    invoice = make_invoice(customer, invoice_number="RE-STORNO-SRC-0001", tax_model="standard", tax_rate=Decimal("19.00"))
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("2.00"), product_id=product.id, tax_rate=Decimal("19.00"))]
    invoice.calculate_totals()
    invoice.generate_hash()
    invoice.status = "sent"
    db_session.add(invoice)
    db_session.commit()
    invoice_id = invoice.id

    login(client, "admin")
    response = client.post(
        f"/invoices/{invoice_id}/create-cancellation",
        data={"reason": "Testgrund"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    db_session.refresh(invoice)
    assert invoice.status == "cancelled"

    cancellation = Invoice.query.filter(Invoice.invoice_number.like("STORNO-%")).first()
    assert cancellation is not None
    assert cancellation.subtotal == -invoice.subtotal
    assert cancellation.total == -invoice.total
    assert cancellation.status == "sent"

    db_session.refresh(product)
    assert product.number == 52  # 50 + 2 zurueckgebucht


def test_storno_of_paid_invoice_logs_correct_old_status(client, admin_user, db_session, customer):
    """Regressionstest: der Audit-Trail (InvoiceStatusLog.old_status) fuer
    die stornierte Original-Rechnung MUSS den tatsaechlichen Ist-Status
    vor der Stornierung zeigen ('paid'), nicht faelschlich 'sent'.
    GoBD-relevant: ein falscher Audit-Trail-Eintrag untergraebt die
    Nachvollziehbarkeit."""
    invoice = make_invoice(customer, invoice_number="RE-STORNO-PAID-0001")
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice.calculate_totals()
    invoice.generate_hash()
    invoice.status = "paid"
    db_session.add(invoice)
    db_session.commit()
    invoice_id = invoice.id

    login(client, "admin")
    client.post(f"/invoices/{invoice_id}/create-cancellation", data={"reason": "Testgrund"}, follow_redirects=True)

    log_entry = InvoiceStatusLog.query.filter_by(invoice_id=invoice_id, new_status="cancelled").first()
    assert log_entry is not None
    assert log_entry.old_status == "paid"


def test_storno_already_cancelled_invoice_is_rejected(client, admin_user, db_session, customer):
    invoice = make_invoice(customer, invoice_number="RE-STORNO-TWICE-0001")
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice.calculate_totals()
    invoice.generate_hash()
    invoice.status = "cancelled"
    db_session.add(invoice)
    db_session.commit()

    login(client, "admin")
    response = client.get(f"/invoices/{invoice.id}/create-cancellation", follow_redirects=True)

    # Ist-Verhalten: der erste Guard (status not in ["sent", "paid"])
    # greift bereits fuer status="cancelled", der zweite, spezifischere
    # Guard ("bereits storniert", app.py:1037-1039) ist dadurch toter
    # Code und wird nie erreicht (siehe AGENTS.md).
    assert "Nur versendete oder bezahlte Rechnungen können storniert werden" in response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Reseller-/Kommissionsbestand: Lieferschein -> Abrechnung -> Storno
# ---------------------------------------------------------------------------


def test_consignment_stock_rebooked_on_storno_of_reseller_invoice(client, admin_user, db_session, customer, product):
    """Ueber create_invoice_from_consignment() entsteht real eine Invoice
    mit customer_type='reseller' -- Storno muss Haupt- UND
    Kommissionsbestand zurueckbuchen (siehe AGENTS.md
    "Reseller-/Kommissionslager-Fluss")."""
    product.number = 100
    db_session.commit()

    consignment = ConsignmentStock(customer_id=customer.id, product_id=product.id, quantity=20, quantity_sold=0, unit_price=Decimal("8.00"))
    db_session.add(consignment)
    db_session.commit()

    login(client, "admin")
    response = client.post(
        f"/consignment/{customer.id}/create-invoice",
        data={
            "product_id[]": [str(product.id)],
            "sold_quantity[]": ["5"],
            "show_tax": "on",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    invoice = Invoice.query.filter_by(customer_type="reseller").first()
    assert invoice is not None

    db_session.refresh(consignment)
    stock_after_sale = consignment.quantity

    invoice.status = "sent"
    db_session.commit()

    client.post(f"/invoices/{invoice.id}/create-cancellation", data={"reason": "Testgrund"}, follow_redirects=True)

    db_session.refresh(consignment)
    db_session.refresh(product)

    assert consignment.quantity == stock_after_sale + 5
    assert product.number == 100 + 5


# ---------------------------------------------------------------------------
# POS-/Barverkauf-Flow
# ---------------------------------------------------------------------------


def test_pos_sale_creates_paid_bar_invoice_and_reduces_stock(client, cashier_user, db_session, product):
    product.number = 50
    db_session.commit()

    login(client, "cashier")
    response = client.post(
        "/pos/complete-sale",
        json={"items": {str(product.id): 3}},
        follow_redirects=True,
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["receipt_number"].startswith("BAR-")

    invoice = Invoice.query.filter_by(invoice_number=data["receipt_number"]).first()
    assert invoice is not None
    assert invoice.status == "paid"
    assert invoice.payment_method == "Barzahlung"

    db_session.refresh(product)
    assert product.number == 47

    status_log = InvoiceStatusLog.query.filter_by(invoice_id=invoice.id).first()
    assert status_log is not None
    assert status_log.new_status == "paid"
    assert status_log.old_status is None


def test_pos_sale_insufficient_stock_rejected_no_partial_sale(client, cashier_user, db_session, product):
    product.number = 2
    db_session.commit()

    login(client, "cashier")
    response = client.post(
        "/pos/complete-sale",
        json={"items": {str(product.id): 10}},
        follow_redirects=True,
    )

    assert response.status_code == 400
    data = response.get_json()
    assert data["success"] is False

    db_session.refresh(product)
    assert product.number == 2  # unveraendert, kein Teilverkauf
    assert Invoice.query.count() == 0


# ---------------------------------------------------------------------------
# PDF-Archivierung
# ---------------------------------------------------------------------------


def test_pdf_download_archives_hash_only_once_for_sent_invoice(client, admin_user, db_session, customer, tmp_path, app):
    app.config["PDF_FOLDER"] = str(tmp_path)

    invoice = make_invoice(customer, invoice_number="RE-PDF-0001")
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice.calculate_totals()
    invoice.generate_hash()
    invoice.status = "sent"
    db_session.add(invoice)
    db_session.commit()
    invoice_id = invoice.id

    login(client, "admin")

    response1 = client.get(f"/invoices/{invoice_id}/pdf")
    assert response1.status_code == 200
    archives_after_first = InvoicePdfArchive.query.filter_by(invoice_id=invoice_id).count()
    assert archives_after_first == 1

    response2 = client.get(f"/invoices/{invoice_id}/pdf")
    assert response2.status_code == 200
    archives_after_second = InvoicePdfArchive.query.filter_by(invoice_id=invoice_id).count()
    assert archives_after_second == 1  # kein zweiter Archiv-Eintrag


def test_pdf_download_does_not_archive_draft_invoice(client, admin_user, db_session, customer, tmp_path, app):
    app.config["PDF_FOLDER"] = str(tmp_path)

    invoice = make_invoice(customer, invoice_number="RE-PDF-DRAFT-0001")
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice.calculate_totals()
    invoice.generate_hash()
    db_session.add(invoice)
    db_session.commit()

    login(client, "admin")
    response = client.get(f"/invoices/{invoice.id}/pdf")

    assert response.status_code == 200
    assert InvoicePdfArchive.query.filter_by(invoice_id=invoice.id).count() == 0


# ---------------------------------------------------------------------------
# Mahnwesen
# ---------------------------------------------------------------------------


def test_reminder_requires_sent_status(client, admin_user, db_session, customer):
    invoice = make_invoice(customer, invoice_number="RE-REMINDER-DRAFT-0001")
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice.calculate_totals()
    invoice.generate_hash()
    db_session.add(invoice)
    db_session.commit()

    login(client, "admin")
    response = client.post(f"/invoices/{invoice.id}/reminder", data={"action": "download"}, follow_redirects=True)

    assert "können nur für versendete" in response.get_data(as_text=True)
    assert Reminder.query.filter_by(invoice_id=invoice.id).count() == 0


def test_reminder_level_increases_on_repeated_reminder(client, admin_user, db_session, customer):
    invoice = make_invoice(customer, invoice_number="RE-REMINDER-0001")
    invoice.due_date = date.today() - timedelta(days=20)
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice.calculate_totals()
    invoice.generate_hash()
    invoice.status = "sent"
    db_session.add(invoice)
    db_session.commit()

    login(client, "admin")

    response1 = client.post(f"/invoices/{invoice.id}/reminder", data={"action": "download"}, follow_redirects=True)
    assert response1.status_code == 200
    first_reminder = Reminder.query.filter_by(invoice_id=invoice.id).order_by(Reminder.reminder_level.desc()).first()
    assert first_reminder.reminder_level == 1
    assert first_reminder.reminder_fee == pytest.approx(5.00)

    response2 = client.post(f"/invoices/{invoice.id}/reminder", data={"action": "download"}, follow_redirects=True)
    assert response2.status_code == 200
    second_reminder = Reminder.query.filter_by(invoice_id=invoice.id).order_by(Reminder.reminder_level.desc()).first()
    assert second_reminder.reminder_level == 2
    assert second_reminder.reminder_fee == pytest.approx(10.00)
