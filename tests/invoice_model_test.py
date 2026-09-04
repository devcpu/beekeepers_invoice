"""Charakterisierungstests fuer die Kernmodell-Logik: Steuerberechnung,
Hash-Generierung, Bestandsverwaltung, DSGVO-Anonymisierung.

Diese Tests schreiben das AKTUELLE Verhalten fest (Characterization
Tests), nicht Wunschverhalten. Ein rot laufender Test bedeutet ein
falsches Verstaendnis des Ist-Zustands, nicht automatisch einen Bug.
"""

from decimal import Decimal

import pytest

from conftest import make_customer, make_invoice, make_line_item, make_product, make_user
from models import Customer, Invoice, Product, User


# ---------------------------------------------------------------------------
# Invoice.calculate_totals() -- Steuermodell "standard"
# ---------------------------------------------------------------------------


def test_calculate_totals_standard_single_item(db_session, customer):
    invoice = make_invoice(customer, tax_model="standard", tax_rate=Decimal("19.00"))
    invoice.line_items = [make_line_item(unit_price=Decimal("100.00"), quantity=Decimal("1.00"))]

    invoice.calculate_totals()

    assert invoice.subtotal == Decimal("100.00")
    assert invoice.tax_amount == Decimal("19.00")
    assert invoice.total == Decimal("119.00")


def test_calculate_totals_standard_multiple_items(db_session, customer):
    invoice = make_invoice(customer, tax_model="standard", tax_rate=Decimal("19.00"))
    invoice.line_items = [
        make_line_item(unit_price=Decimal("50.00"), quantity=Decimal("2.00")),
        make_line_item(unit_price=Decimal("30.00"), quantity=Decimal("1.00")),
    ]

    invoice.calculate_totals()

    assert invoice.subtotal == Decimal("130.00")
    assert invoice.tax_amount == Decimal("24.70")
    assert invoice.total == Decimal("154.70")


def test_calculate_totals_standard_empty_line_items(db_session, customer):
    invoice = make_invoice(customer, tax_model="standard")
    invoice.line_items = []

    invoice.calculate_totals()

    assert invoice.subtotal == 0
    assert invoice.tax_amount == Decimal("0.00")
    assert invoice.total == 0


def test_calculate_totals_standard_uses_line_item_tax_rate_over_invoice_default(db_session, customer):
    # Invoice-Default 19%, aber LineItem hat eigenen Satz 7.80% (z.B. Honig)
    invoice = make_invoice(customer, tax_model="standard", tax_rate=Decimal("19.00"))
    invoice.line_items = [make_line_item(unit_price=Decimal("100.00"), quantity=Decimal("1.00"), tax_rate=Decimal("7.80"))]

    invoice.calculate_totals()

    assert invoice.tax_amount == Decimal("7.80")
    assert invoice.total == Decimal("107.80")


def test_calculate_totals_standard_falls_back_to_invoice_tax_rate_when_item_rate_none(db_session, customer):
    invoice = make_invoice(customer, tax_model="standard", tax_rate=Decimal("19.00"))
    invoice.line_items = [make_line_item(unit_price=Decimal("100.00"), quantity=Decimal("1.00"), tax_rate=None)]

    invoice.calculate_totals()

    assert invoice.tax_amount == Decimal("19.00")


# ---------------------------------------------------------------------------
# Invoice.calculate_totals() -- Steuermodell "kleinunternehmer"
# ---------------------------------------------------------------------------


def test_calculate_totals_kleinunternehmer_no_tax(db_session, customer):
    invoice = make_invoice(customer, tax_model="kleinunternehmer", tax_rate=Decimal("19.00"))
    invoice.line_items = [make_line_item(unit_price=Decimal("100.00"), quantity=Decimal("1.00"))]

    invoice.calculate_totals()

    assert invoice.subtotal == Decimal("100.00")
    assert invoice.tax_amount == Decimal("0.00")
    assert invoice.total == Decimal("100.00")


# ---------------------------------------------------------------------------
# Invoice.calculate_totals() -- Steuermodell "landwirtschaft" (§24 UStG)
# ---------------------------------------------------------------------------


def test_calculate_totals_landwirtschaft_brutto_equals_netto(db_session, customer):
    invoice = make_invoice(customer, tax_model="landwirtschaft", tax_rate=Decimal("7.80"))
    invoice.line_items = [make_line_item(unit_price=Decimal("107.80"), quantity=Decimal("1.00"), tax_rate=Decimal("7.80"))]

    invoice.calculate_totals()

    # Brutto = Netto: total bleibt gleich subtotal, MwSt wird nur intern ausgewiesen
    assert invoice.subtotal == Decimal("107.80")
    assert invoice.total == Decimal("107.80")
    # Rueckrechnung: 107.80 * (7.80 / 107.80) = 7.80 (Decimal-Division liefert
    # volle Praezision, daher Vergleich mit Tolueranz statt exaktem Decimal)
    assert invoice.tax_amount == pytest.approx(Decimal("7.80"), abs=Decimal("0.0001"))


def test_calculate_totals_landwirtschaft_mixed_cart_uses_per_item_tax_rate(db_session, customer):
    """Gemischter Warenkorb: unterschiedliche LineItem.tax_rate-Werte muessen
    einzeln zurueckgerechnet werden, nicht pauschal mit Invoice.tax_rate."""
    invoice = make_invoice(customer, tax_model="landwirtschaft", tax_rate=Decimal("7.80"))
    invoice.line_items = [
        make_line_item(unit_price=Decimal("107.80"), quantity=Decimal("1.00"), tax_rate=Decimal("7.80")),
        make_line_item(unit_price=Decimal("119.00"), quantity=Decimal("1.00"), tax_rate=Decimal("19.00")),
    ]

    invoice.calculate_totals()

    expected_tax_item1 = Decimal("107.80") * (Decimal("7.80") / Decimal("107.80"))
    expected_tax_item2 = Decimal("119.00") * (Decimal("19.00") / Decimal("119.00"))

    assert invoice.subtotal == Decimal("226.80")
    assert invoice.total == Decimal("226.80")
    assert invoice.tax_amount == pytest.approx(expected_tax_item1 + expected_tax_item2, abs=Decimal("0.01"))


def test_calculate_totals_landwirtschaft_falls_back_to_invoice_tax_rate(db_session, customer):
    invoice = make_invoice(customer, tax_model="landwirtschaft", tax_rate=Decimal("7.80"))
    invoice.line_items = [make_line_item(unit_price=Decimal("107.80"), quantity=Decimal("1.00"), tax_rate=None)]

    invoice.calculate_totals()

    assert invoice.tax_amount == pytest.approx(Decimal("7.80"), abs=Decimal("0.0001"))


# ---------------------------------------------------------------------------
# Invoice.generate_hash() / verify_hash()
# ---------------------------------------------------------------------------


def test_generate_hash_deterministic_for_same_data(db_session, customer):
    invoice1 = make_invoice(customer, invoice_number="RE-TEST-0001")
    invoice1.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice1.calculate_totals()
    hash1 = invoice1.generate_hash()

    invoice2 = make_invoice(customer, invoice_number="RE-TEST-0001")
    invoice2.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice2.calculate_totals()
    hash2 = invoice2.generate_hash()

    assert hash1 == hash2


@pytest.mark.parametrize(
    "mutate",
    [
        lambda inv: setattr(inv, "subtotal", Decimal("999.00")),
        lambda inv: setattr(inv, "tax_amount", Decimal("999.00")),
        lambda inv: setattr(inv, "total", Decimal("999.00")),
        lambda inv: setattr(inv, "tax_model", "kleinunternehmer"),
        lambda inv: setattr(inv, "customer_type", "wiederverkaeufer"),
    ],
)
def test_generate_hash_changes_when_invoice_field_changes(db_session, customer, mutate):
    invoice = make_invoice(customer)
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice.calculate_totals()
    original_hash = invoice.generate_hash()

    mutate(invoice)
    new_hash = invoice.generate_hash()

    assert new_hash != original_hash


@pytest.mark.parametrize(
    "mutate_item",
    [
        lambda item: setattr(item, "description", "Geaendert"),
        lambda item: setattr(item, "quantity", Decimal("99.00")),
        lambda item: setattr(item, "unit_price", Decimal("999.00")),
        lambda item: setattr(item, "total", Decimal("999.00")),
        lambda item: setattr(item, "tax_rate", Decimal("7.80")),
    ],
)
def test_generate_hash_changes_when_line_item_field_changes(db_session, customer, mutate_item):
    invoice = make_invoice(customer)
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"), tax_rate=Decimal("19.00"))]
    invoice.calculate_totals()
    original_hash = invoice.generate_hash()

    mutate_item(invoice.line_items[0])
    new_hash = invoice.generate_hash()

    assert new_hash != original_hash


def test_verify_hash_detects_tampering(db_session, customer):
    invoice = make_invoice(customer)
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice.calculate_totals()
    invoice.generate_hash()

    assert invoice.verify_hash() is True

    # Manipulation nach Hash-Erstellung: total wird veraendert, Hash bleibt alt
    invoice.total = Decimal("9999.00")

    assert invoice.verify_hash() is False


def test_generate_hash_before_calculate_totals_raises(db_session, customer):
    """Ist-Verhalten: generate_hash() vor calculate_totals() schlaegt fehl,
    weil subtotal/tax_amount/total am frischen (nicht committeten) Objekt
    None statt 0.00 sind (Spalten-Defaults greifen erst bei DB-Flush) und
    generate_hash() sie ungeprueft in float() umwandelt. Das erzwingt
    faktisch die in AGENTS.md dokumentierte Reihenfolge:
    line_items zuweisen -> calculate_totals() -> generate_hash()."""
    invoice = make_invoice(customer)

    with pytest.raises(TypeError):
        invoice.generate_hash()


def test_generate_hash_requires_line_items_assigned_first(db_session, customer):
    """Reihenfolge-Pattern aus AGENTS.md: line_items zuweisen, dann
    calculate_totals(), dann generate_hash()."""
    invoice = make_invoice(customer)
    invoice.line_items = []
    invoice.calculate_totals()
    hash_without_items = invoice.generate_hash()

    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice.calculate_totals()
    hash_with_items = invoice.generate_hash()

    assert hash_without_items != hash_with_items


# ---------------------------------------------------------------------------
# Product.reduce_stock() / increase_stock()
# ---------------------------------------------------------------------------


def test_reduce_stock_normal_case(db_session, product):
    product.number = 100

    result = product.reduce_stock(30)

    assert result is True
    assert product.number == 70


def test_reduce_stock_exact_amount_available(db_session, product):
    product.number = 10

    result = product.reduce_stock(10)

    assert result is True
    assert product.number == 0


def test_reduce_stock_insufficient_stock(db_session, product):
    product.number = 5

    result = product.reduce_stock(10)

    assert result is False
    assert product.number == 5  # unveraendert


def test_increase_stock_normal_case(db_session, product):
    product.number = 50

    product.increase_stock(20)

    assert product.number == 70


def test_reduce_stock_negative_amount_is_not_rejected(db_session, product):
    """Ist-Verhalten: reduce_stock() validiert das Vorzeichen von amount
    NICHT. Ein negativer amount erhoeht faktisch den Bestand, da nur
    `self.number >= amount` geprueft wird. Festgehalten als bekanntes
    Verhalten, nicht als gewuenschtes."""
    product.number = 50

    result = product.reduce_stock(-10)

    assert result is True
    assert product.number == 60


# ---------------------------------------------------------------------------
# Customer.anonymize_gdpr()
# ---------------------------------------------------------------------------


def test_anonymize_gdpr_clears_personal_fields(db_session):
    cust = make_customer(company_name="Firma Original", email="original@example.test")
    cust.phone = "+49 123 456"
    cust.address = "Strasse 1"
    cust.tax_id = "DE123456789"
    db_session.add(cust)
    db_session.commit()

    cust.anonymize_gdpr()

    assert cust.first_name == "Anonymisiert"
    assert cust.last_name == f"Kunde #{cust.id}"
    assert cust.email == f"deleted_{cust.id}@anonymized.local"
    assert cust.phone is None
    assert cust.address is None
    assert cust.tax_id is None
    assert cust.company_name == f"Gelöschter Kunde #{cust.id}"
    assert cust.is_anonymized is True


def test_anonymize_gdpr_does_not_touch_existing_invoices(db_session, customer):
    invoice = make_invoice(customer, invoice_number="RE-TEST-ANON-0001")
    invoice.line_items = [make_line_item(unit_price=Decimal("10.00"), quantity=Decimal("1.00"))]
    invoice.calculate_totals()
    invoice.generate_hash()
    db_session.add(invoice)
    db_session.commit()

    original_hash = invoice.data_hash
    original_total = invoice.total

    customer.anonymize_gdpr()
    db_session.commit()

    assert invoice.data_hash == original_hash
    assert invoice.total == original_total
    assert invoice.verify_hash() is True


# ---------------------------------------------------------------------------
# User: Passwort-Hashing und Backup-Codes
# ---------------------------------------------------------------------------


def test_user_check_password_correct_and_incorrect(db_session):
    user = make_user(username="pwtest", password="korrektesPasswort123")
    db_session.add(user)
    db_session.commit()

    assert user.check_password("korrektesPasswort123") is True
    assert user.check_password("falschesPasswort") is False


def test_user_backup_codes_single_use(db_session):
    user = make_user(username="totptest")
    codes = user.generate_backup_codes(count=3)
    db_session.add(user)
    db_session.commit()

    first_code = codes[0]

    assert user.verify_backup_code(first_code) is True
    # Derselbe Code darf kein zweites Mal funktionieren
    assert user.verify_backup_code(first_code) is False
    # Ein anderer, noch nicht verwendeter Code funktioniert weiterhin
    assert user.verify_backup_code(codes[1]) is True


def test_user_has_role_hierarchy(db_session):
    admin = make_user(username="roletest_admin", role="admin")
    cashier = make_user(username="roletest_cashier", role="cashier")
    reseller = make_user(username="roletest_reseller", role="reseller")

    # admin hat implizit auch cashier- und reseller-Rechte (has_role-Logik)
    assert admin.has_role("admin") is True
    assert admin.has_role("cashier") is True
    assert admin.has_role("reseller") is True

    assert cashier.has_role("admin") is False
    assert cashier.has_role("cashier") is True
    assert cashier.has_role("reseller") is False

    assert reseller.has_role("admin") is False
    assert reseller.has_role("cashier") is False
    assert reseller.has_role("reseller") is True
