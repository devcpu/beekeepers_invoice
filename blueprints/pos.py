"""Point of Sale (Kassenseite) fuer Direktverkauf."""

from datetime import datetime
from decimal import Decimal

from flask import Blueprint, jsonify, render_template, request, session
from flask_login import current_user, login_required

from auth_utils import role_required
from models import ConsignmentStock, Customer, Invoice, InvoiceStatusLog, LineItem, Product, db

pos_bp = Blueprint("pos", __name__)


@pos_bp.route("/pos")
@login_required
@role_required("cashier", "admin")
def pos():
    """Kassenseite für schnellen Direktverkauf"""
    stock_source = session.get("stock_source", "main")

    if stock_source == "market" and current_user.reseller_customer_id:
        consignment_items = ConsignmentStock.query.filter_by(customer_id=current_user.reseller_customer_id).filter(ConsignmentStock.quantity > 0).all()

        products = []
        for item in consignment_items:
            product = item.product
            product_data = {
                "id": product.id,
                "name": product.name,
                "price": float(item.unit_price),
                "number": item.quantity,
                "tax_rate": product.tax_rate,
                "is_market_stock": True,
                "consignment_stock_id": item.id,
            }
            products.append(type("obj", (object,), product_data))
    else:
        products = Product.query.filter_by(active=True).filter(Product.number > 0).order_by(Product.name).all()
        for p in products:
            p.is_market_stock = False

    return render_template("pos.html", products=products, stock_source=stock_source)


@pos_bp.route("/pos/complete-sale", methods=["POST"])
@login_required
@role_required("cashier", "admin")
def complete_pos_sale():
    """Verkauf abschließen - Bestand reduzieren und GoBD-konform dokumentieren"""
    try:
        data = request.get_json()
        items = data.get("items", {})
        stock_source = session.get("stock_source", "main")

        if not items:
            return jsonify({"success": False, "message": "Warenkorb ist leer"}), 400

        create_invoice = True
        if current_user.reseller_type == "type3_non_ust_pwa":
            create_invoice = False

        subtotal = Decimal("0.00")
        line_items_data = []

        for product_id, quantity in items.items():
            product = Product.query.get(int(product_id))
            if not product:
                return jsonify({"success": False, "message": f"Produkt {product_id} nicht gefunden"}), 404

            if stock_source == "market" and current_user.reseller_customer_id:
                consignment = ConsignmentStock.query.filter_by(customer_id=current_user.reseller_customer_id, product_id=product.id).first()

                if not consignment or consignment.quantity < quantity:
                    available = consignment.quantity if consignment else 0
                    return (
                        jsonify(
                            {
                                "success": False,
                                "message": f"Nicht genug Marktbestand für {product.name}. Verfügbar: {available}, Benötigt: {quantity}",
                            }
                        ),
                        400,
                    )

                consignment.quantity -= quantity
                consignment.quantity_sold += quantity

                line_total = Decimal(str(consignment.unit_price)) * Decimal(str(quantity))
                unit_price = consignment.unit_price
            else:
                if product.number < quantity:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "message": f"Nicht genug Bestand für {product.name}. Verfügbar: {product.number}, Benötigt: {quantity}",
                            }
                        ),
                        400,
                    )

                product.number -= quantity
                line_total = Decimal(str(product.price)) * Decimal(str(quantity))
                unit_price = product.price

            subtotal += line_total

            if create_invoice:
                line_items_data.append(
                    {
                        "product": product,
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "tax_rate": product.tax_rate,
                        "total": line_total,
                    }
                )

        if not create_invoice:
            db.session.commit()
            return jsonify(
                {
                    "success": True,
                    "message": "Verkauf erfolgreich (nur Bestandsumbuchung, keine Rechnung)",
                    "receipt_number": None,
                    "total": float(subtotal),
                }
            )

        today = datetime.now().date()
        prefix = f"BAR-{today.strftime('%Y%m%d')}"

        last_receipt = Invoice.query.filter(Invoice.invoice_number.like(f"{prefix}%")).order_by(Invoice.invoice_number.desc()).first()

        if last_receipt:
            last_num = int(last_receipt.invoice_number.split("-")[-1])
            next_num = last_num + 1
        else:
            next_num = 1

        receipt_number = f"{prefix}-{next_num:04d}"

        bar_customer = Customer.query.filter_by(email="barverkauf@system.local").first()
        if not bar_customer:
            bar_customer = Customer(
                company_name="Barverkauf",
                first_name="Bar",
                last_name="Verkauf",
                email="barverkauf@system.local",
                address="Direktverkauf ohne Rechnungsadresse",
            )
            db.session.add(bar_customer)
            db.session.flush()

        tax_rate = Decimal("7.80")
        tax_amount = subtotal * (tax_rate / Decimal("100"))
        total = subtotal

        invoice = Invoice(
            invoice_number=receipt_number,
            customer_id=bar_customer.id,
            invoice_date=today,
            due_date=today,
            status="paid",
            customer_type="endkunde",
            tax_model="landwirtschaft",
            tax_rate=tax_rate,
            subtotal=subtotal,
            tax_amount=tax_amount,
            total=total,
            payment_method="Barzahlung",
            notes="Barverkauf / Direktverkauf\nKasse: POS-System",
        )

        line_items_list = []
        for idx, item_data in enumerate(line_items_data):
            line_item = LineItem(
                product_id=item_data["product"].id,
                description=item_data["product"].name,
                quantity=Decimal(str(item_data["quantity"])),
                unit_price=item_data["unit_price"],
                tax_rate=item_data["tax_rate"],
                total=item_data["total"],
                position=idx,
            )
            line_items_list.append(line_item)

        invoice.line_items = line_items_list

        invoice.generate_hash()

        db.session.add(invoice)
        db.session.flush()

        status_log = InvoiceStatusLog(
            invoice_id=invoice.id,
            old_status=None,
            new_status="paid",
            changed_by=current_user.username,
            reason="Barverkauf - automatisch als bezahlt markiert",
        )
        db.session.add(status_log)

        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": "Verkauf erfolgreich abgeschlossen",
                "receipt_number": receipt_number,
                "total": float(total),
            }
        )

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
