"""Kundenverwaltung inkl. DSGVO-Anonymisierung."""

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import Customer, Invoice, db

customers_bp = Blueprint("customers", __name__)


@customers_bp.route("/customers")
@login_required
def list_customers():
    """Liste aller Kunden mit Suchfunktion"""
    search_query = request.args.get("search", "").strip()

    if search_query:
        search_pattern = f"%{search_query}%"
        customers = (
            Customer.query.filter(
                db.or_(
                    Customer.company_name.ilike(search_pattern),
                    Customer.first_name.ilike(search_pattern),
                    Customer.last_name.ilike(search_pattern),
                    Customer.email.ilike(search_pattern),
                )
            )
            .order_by(Customer.company_name, Customer.last_name)
            .all()
        )
    else:
        customers = Customer.query.order_by(Customer.company_name, Customer.last_name).all()

    return render_template("customers/list.html", customers=customers, search_query=search_query)


@customers_bp.route("/customers/<int:customer_id>")
@login_required
def view_customer(customer_id):
    """Kundendetails anzeigen"""
    customer = Customer.query.get_or_404(customer_id)
    return render_template("customers/view.html", customer=customer)


@customers_bp.route("/customers/<int:customer_id>/edit", methods=["GET", "POST"])
@login_required
def edit_customer(customer_id):
    """Kunde bearbeiten"""
    customer = Customer.query.get_or_404(customer_id)

    if request.method == "POST":
        try:
            customer.company_name = request.form.get("company_name")
            customer.first_name = request.form.get("first_name")
            customer.last_name = request.form.get("last_name")
            customer.email = request.form.get("email")
            customer.phone = request.form.get("phone")
            customer.address = request.form.get("address")
            customer.tax_id = request.form.get("tax_id")
            customer.reseller = request.form.get("reseller") == "1"

            db.session.commit()
            flash("Kundendaten erfolgreich aktualisiert!", "success")
            return redirect(url_for("customers.view_customer", customer_id=customer.id))

        except Exception as e:
            db.session.rollback()
            flash(f"Fehler beim Aktualisieren: {str(e)}", "error")

    return render_template("customers/edit.html", customer=customer)


@customers_bp.route("/customers/<int:customer_id>/anonymize", methods=["POST"])
@login_required
def anonymize_customer(customer_id):
    """
    DSGVO-konforme Anonymisierung von Kundendaten.

    Anonymisiert nur die Kundenstammdaten. Bestehende Rechnungen bleiben
    aus steuerrechtlichen Gründen (§147 AO, GoBD) unverändert und zeigen
    weiterhin die Originaldaten. Dies ist DSGVO-konform gemäß Art. 17 Abs. 3 b.
    """
    customer = Customer.query.get_or_404(customer_id)

    if customer.is_anonymized:
        flash("Dieser Kunde wurde bereits anonymisiert.", "warning")
        return redirect(url_for("customers.list_customers"))

    invoice_count = Invoice.query.filter_by(customer_id=customer_id).count()

    original_email = customer.email
    original_name = customer.display_name

    try:
        customer.anonymize_gdpr()
        db.session.commit()

        current_app.logger.info(
            "DSGVO-Anonymisierung durchgeführt | "
            "Kunde ID: %s | "
            "Original: %s (%s) | "
            "Benutzer: %s | "
            "Verknüpfte Rechnungen: %s (bleiben unverändert gemäß §147 AO)",
            customer_id,
            original_name,
            original_email,
            current_user.username,
            invoice_count,
        )

        if invoice_count > 0:
            flash(
                f"Kunde erfolgreich anonymisiert. "
                f"{invoice_count} bestehende Rechnung(en) bleiben aus steuerrechtlichen Gründen "
                f"(§147 AO - 10 Jahre Aufbewahrungspflicht) unverändert und zeigen weiterhin die Originaldaten. "
                f"Dies ist DSGVO-konform gemäß Art. 17 Abs. 3 Buchstabe b.",
                "success",
            )
        else:
            flash("Kunde erfolgreich anonymisiert.", "success")

        return redirect(url_for("customers.list_customers"))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error("Fehler bei DSGVO-Anonymisierung Kunde #%s: %s", customer_id, str(e))
        flash(f"Fehler bei der Anonymisierung: {str(e)}", "error")
        return redirect(url_for("customers.view_customer", customer_id=customer_id))
