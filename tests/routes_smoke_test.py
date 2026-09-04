"""Route-Tests gegen URLs (nicht gegen Funktionsnamen), damit sie einen
spaeteren Blueprint-Split ueberleben. Deckt Login-Flow, Autorisierung
pro Rolle, und je Domaene mindestens Liste/Create-Formular/Create-POST/
Detail ab.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from conftest import login, make_customer, make_invoice, make_line_item, make_product
from models import Customer, Invoice, Product, db


# ---------------------------------------------------------------------------
# Login-Flow
# ---------------------------------------------------------------------------


def test_login_page_accessible_without_auth(client):
    response = client.get("/login")
    assert response.status_code == 200


def test_login_with_correct_credentials_redirects_to_index(client, admin_user):
    response = login(client, "admin")
    assert response.status_code == 200
    assert response.request.path == "/"


def test_login_with_wrong_password_shows_error(client, admin_user):
    response = client.post("/login", data={"username": "admin", "password": "falsch"}, follow_redirects=True)
    assert response.status_code == 200
    assert "Ungültiger Benutzername oder Passwort" in response.get_data(as_text=True)


def test_login_with_unknown_user_shows_error(client):
    response = client.post("/login", data={"username": "gibtsnicht", "password": "egal"}, follow_redirects=True)
    assert "Ungültiger Benutzername oder Passwort" in response.get_data(as_text=True)


def test_protected_route_without_login_redirects_to_login(client):
    response = client.get("/invoices", follow_redirects=False)
    assert response.status_code in (301, 302)
    assert "/login" in response.headers["Location"]


def test_logout_clears_session(client, admin_user):
    login(client, "admin")
    response = client.get("/logout", follow_redirects=True)
    assert response.status_code == 200

    # Nach Logout ist eine geschuetzte Route wieder gesperrt
    response = client.get("/invoices", follow_redirects=False)
    assert response.status_code in (301, 302)


# ---------------------------------------------------------------------------
# Oeffentliche Routen ohne @login_required (AGENTS.md-Liste)
# ---------------------------------------------------------------------------


def test_health_endpoint_public(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "healthy"


def test_offline_page_public(client):
    response = client.get("/offline")
    assert response.status_code == 200


def test_forgot_password_page_public(client):
    response = client.get("/forgot-password")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Rollen-Autorisierung (role_required redirected mit Flash, kein 403)
# ---------------------------------------------------------------------------


def test_admin_only_route_rejects_cashier(client, cashier_user):
    login(client, "cashier")
    response = client.get("/settings/users", follow_redirects=True)
    assert response.status_code == 200
    assert "keine Berechtigung" in response.get_data(as_text=True)


def test_admin_only_route_rejects_reseller(client, reseller_user):
    login(client, "reseller")
    response = client.get("/settings/users", follow_redirects=True)
    assert "keine Berechtigung" in response.get_data(as_text=True)


def test_admin_only_route_allows_admin(client, admin_user):
    login(client, "admin")
    response = client.get("/settings/users")
    assert response.status_code == 200


def test_pos_complete_sale_rejects_reseller(client, reseller_user):
    login(client, "reseller")
    response = client.post("/pos/complete-sale", json={}, follow_redirects=True)
    assert "keine Berechtigung" in response.get_data(as_text=True)


def test_pos_complete_sale_allows_cashier_role_check(client, cashier_user):
    """Nur der role_required-Check wird geprueft, nicht der volle
    Verkaufs-Flow (der braucht Warenkorb-Payload) -- ein leerer Body darf
    NICHT an der Rollenpruefung scheitern (kein 'keine Berechtigung')."""
    login(client, "cashier")
    response = client.post("/pos/complete-sale", json={}, follow_redirects=True)
    assert "keine Berechtigung" not in response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------


def test_list_invoices_requires_login_and_returns_200(client, admin_user):
    login(client, "admin")
    response = client.get("/invoices")
    assert response.status_code == 200


def test_create_invoice_form_accessible(client, admin_user):
    login(client, "admin")
    response = client.get("/invoices/new")
    assert response.status_code == 200


def test_create_invoice_post_currently_fails_with_type_error(client, admin_user, db_session):
    """KRITISCHER BUG (siehe AGENTS.md / TODO.md, live gegen MariaDB
    verifiziert): create_invoice() konstruiert LineItem mit rohen
    float-Werten (app.py:850-851). Invoice.calculate_totals() rechnet
    damit `float * Decimal` und wirft TypeError -- das manuelle
    Rechnungsformular kann aktuell KEINE Rechnung erfolgreich anlegen.
    Dieser Test haelt den Ist-Zustand fest (Fehler-Flash, kein Invoice
    in der DB) und MUSS nach dem Fix (TODO.md) durch einen
    Erfolgs-Assert ersetzt werden -- dann darf `invoice is not None`
    und `invoice.verify_hash() is True` gelten."""
    login(client, "admin")

    response = client.post(
        "/invoices/new",
        data={
            "customer_email": "neu@example.test",
            "first_name": "Erika",
            "last_name": "Musterfrau",
            "company_name": "",
            "phone": "",
            "address": "",
            "tax_id": "",
            "invoice_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=14)).isoformat(),
            "tax_model": "standard",
            "customer_type": "endkunde",
            "notes": "",
            "payment_method": "",
            "description[]": ["Testartikel"],
            "quantity[]": ["2"],
            "unit_price[]": ["15.00"],
            "product_id[]": [""],
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Fehler beim Erstellen der Rechnung" in response.get_data(as_text=True)
    assert "unsupported operand type" in response.get_data(as_text=True)
    # Kein Invoice wurde angelegt (Rollback bei Fehler)
    assert Invoice.query.first() is None


def test_view_invoice_detail(client, admin_user, db_session, customer):
    invoice = make_invoice(customer)
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice.calculate_totals()
    invoice.generate_hash()
    db_session.add(invoice)
    db_session.commit()

    login(client, "admin")
    response = client.get(f"/invoices/{invoice.id}")
    assert response.status_code == 200


def test_view_invoice_detail_404_for_unknown_id(client, admin_user):
    login(client, "admin")
    response = client.get("/invoices/999999")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------


def test_list_customers_returns_200(client, admin_user):
    login(client, "admin")
    response = client.get("/customers")
    assert response.status_code == 200


def test_view_customer_detail(client, admin_user, customer):
    login(client, "admin")
    response = client.get(f"/customers/{customer.id}")
    assert response.status_code == 200


def test_edit_customer_post_updates_fields(client, admin_user, customer, db_session):
    login(client, "admin")
    response = client.post(
        f"/customers/{customer.id}/edit",
        data={
            "company_name": "Neuer Firmenname",
            "first_name": customer.first_name,
            "last_name": customer.last_name,
            "email": customer.email,
            "phone": "",
            "address": "",
            "tax_id": "",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    db_session.refresh(customer)
    assert customer.company_name == "Neuer Firmenname"


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


def test_list_products_returns_200(client, admin_user):
    login(client, "admin")
    response = client.get("/products")
    assert response.status_code == 200


def test_create_product_form_accessible(client, admin_user):
    login(client, "admin")
    response = client.get("/products/new")
    assert response.status_code == 200


def test_create_product_post_creates_product(client, admin_user, db_session):
    login(client, "admin")
    response = client.post(
        "/products/new",
        data={
            "name": "Neuer Honig",
            "number": "50",
            "quantity": "500g",
            "price": "9.90",
            "reseller_price": "",
            "tax_rate": "7.80",
            "lot_number": "",
            "active": "on",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    product = Product.query.filter_by(name="Neuer Honig").first()
    assert product is not None
    assert product.number == 50


def test_view_product_detail(client, admin_user, product):
    login(client, "admin")
    response = client.get(f"/products/{product.id}")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# POS
# ---------------------------------------------------------------------------


def test_pos_page_accessible_to_cashier(client, cashier_user):
    login(client, "cashier")
    response = client.get("/pos")
    assert response.status_code == 200


def test_pos_page_rejects_reseller(client, reseller_user):
    """/pos hat @role_required("cashier", "admin") -- reseller wird
    wie /pos/complete-sale abgewiesen (Redirect + Flash, kein 403)."""
    login(client, "reseller")
    response = client.get("/pos", follow_redirects=True)
    assert "keine Berechtigung" in response.get_data(as_text=True)
