"""Startseite/Dashboard."""

from datetime import datetime, timedelta

from flask import Blueprint, redirect, render_template, session, url_for
from flask_login import current_user, login_required

from models import ConsignmentStock, Customer, Invoice, Product

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def index():
    """Startseite mit Übersicht"""
    if current_user.reseller_customer_id and "stock_source" not in session:
        has_stock = ConsignmentStock.query.filter_by(customer_id=current_user.reseller_customer_id).first() is not None

        if has_stock:
            return redirect(url_for("auth.select_stock_source"))

    recent_invoices = Invoice.query.order_by(Invoice.created_at.desc()).limit(10).all()
    stats = {
        "total_invoices": Invoice.query.count(),
        "draft_invoices": Invoice.query.filter_by(status="draft").count(),
        "sent_invoices": Invoice.query.filter_by(status="sent").count(),
        "paid_invoices": Invoice.query.filter_by(status="paid").count(),
        "cancelled_invoices": Invoice.query.filter_by(status="cancelled").count(),
        "total_customers": Customer.query.count(),
    }

    low_stock_products = Product.query.filter(Product.active.is_(True), Product.number < 25).order_by(Product.number.asc()).all()

    overdue_date = datetime.now().date() - timedelta(days=10)
    overdue_invoices = (
        Invoice.query.filter(Invoice.status == "sent", Invoice.due_date.isnot(None), Invoice.due_date < overdue_date).order_by(Invoice.due_date.asc()).all()
    )

    return render_template(
        "index.html",
        invoices=recent_invoices,
        stats=stats,
        low_stock_products=low_stock_products,
        overdue_invoices=overdue_invoices,
    )
