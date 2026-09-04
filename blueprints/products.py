"""Produktverwaltung und Bestandsuebersicht."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from models import Product, db

products_bp = Blueprint("products", __name__)


@products_bp.route("/products")
@login_required
def list_products():
    """Liste aller Produkte"""
    show_inactive = request.args.get("show_inactive", "false") == "true"

    if show_inactive:
        products = Product.query.order_by(Product.name).all()
    else:
        products = Product.query.filter_by(active=True).order_by(Product.name).all()

    return render_template("products/list.html", products=products, show_inactive=show_inactive)


@products_bp.route("/products/new", methods=["GET", "POST"])
@login_required
def create_product():
    """Neues Produkt erstellen"""
    if request.method == "POST":
        try:
            reseller_price = request.form.get("reseller_price")
            tax_rate = request.form.get("tax_rate")
            product = Product(
                name=request.form.get("name"),
                number=int(request.form.get("number", 0)),
                quantity=request.form.get("quantity"),
                price=float(request.form.get("price")),
                reseller_price=float(reseller_price) if reseller_price else None,
                tax_rate=float(tax_rate) if tax_rate else 7.80,
                lot_number=request.form.get("lot_number"),
                active=request.form.get("active") == "on",
            )

            db.session.add(product)
            db.session.commit()

            flash(f'Produkt "{product.name}" erfolgreich erstellt!', "success")
            return redirect(url_for("products.list_products"))

        except Exception as e:
            db.session.rollback()
            flash(f"Fehler beim Erstellen: {str(e)}", "error")

    return render_template("products/create.html")


@products_bp.route("/products/<int:product_id>")
@login_required
def view_product(product_id):
    """Produktdetails anzeigen"""
    product = Product.query.get_or_404(product_id)
    return render_template("products/view.html", product=product)


@products_bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    """Produkt bearbeiten"""
    product = Product.query.get_or_404(product_id)

    if request.method == "POST":
        try:
            reseller_price = request.form.get("reseller_price")
            tax_rate = request.form.get("tax_rate")
            product.name = request.form.get("name")
            product.number = int(request.form.get("number", 0))
            product.quantity = request.form.get("quantity")
            product.price = float(request.form.get("price"))
            product.reseller_price = float(reseller_price) if reseller_price else None
            product.tax_rate = float(tax_rate) if tax_rate else 7.80
            product.lot_number = request.form.get("lot_number")
            product.active = request.form.get("active") == "on"

            db.session.commit()
            flash("Produkt erfolgreich aktualisiert!", "success")
            return redirect(url_for("products.view_product", product_id=product.id))

        except Exception as e:
            db.session.rollback()
            flash(f"Fehler beim Aktualisieren: {str(e)}", "error")

    return render_template("products/edit.html", product=product)


@products_bp.route("/products/<int:product_id>/delete", methods=["POST"])
@login_required
def delete_product(product_id):
    """Produkt löschen - DEAKTIVIERT aus Sicherheitsgründen"""
    flash(
        "Das Löschen von Produkten ist aus Sicherheitsgründen deaktiviert. Bitte deaktivieren Sie das Produkt stattdessen.",
        "error",
    )
    return redirect(url_for("products.view_product", product_id=product_id))


@products_bp.route("/stock")
@login_required
def stock_management():
    """Bestandsverwaltung mit Produktauswahl"""
    return render_template("stock_management.html")
