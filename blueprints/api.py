"""JWT-API fuer die PWA (/api/auth/*, /api/invoices, /api/customers, /api/pos/complete-sale)
sowie Web-UI-Hilfsendpoints unter /api/* (Autocomplete, Bestandsaenderung -- @login_required
statt @token_required, historisch mit unter /api/ gelandet)."""

from datetime import datetime
from decimal import Decimal

from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required

from invoice_numbering import generate_invoice_number
from jwt_api import generate_jwt_token, role_required_api, token_required
from models import Customer, DeviceToken, Invoice, InvoiceStatusLog, LineItem, Product, User, db

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/auth/login", methods=["POST"])
def api_login():
    """API Login - gibt JWT Token zurück"""
    data = request.get_json()

    if not data or not data.get("username") or not data.get("password"):
        return jsonify({"error": "Username and password required"}), 400

    username = data.get("username")
    password = data.get("password")

    user = User.query.filter_by(username=username).first()

    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid credentials"}), 401

    if not user.is_active:
        return jsonify({"error": "Account deactivated"}), 401

    if user.totp_enabled:
        token_2fa = data.get("totp_token")

        if not token_2fa:
            return jsonify({"error": "2FA required", "requires_2fa": True}), 401

        if not user.verify_totp(token_2fa) and not user.verify_backup_code(token_2fa):
            return jsonify({"error": "Invalid 2FA code"}), 401

        if user.verify_backup_code(token_2fa):
            db.session.commit()

    token = generate_jwt_token(user.id)

    user.last_login = datetime.utcnow()
    user.last_login_ip = request.remote_addr
    db.session.commit()

    return (
        jsonify(
            {
                "token": token,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "role": user.role,
                    "totp_enabled": user.totp_enabled,
                },
            }
        ),
        200,
    )


@api_bp.route("/auth/verify", methods=["GET"])
@token_required
def api_verify_token(current_user):
    """Token verifizieren und User-Daten zurückgeben"""
    return (
        jsonify(
            {
                "valid": True,
                "user": {
                    "id": current_user.id,
                    "username": current_user.username,
                    "email": current_user.email,
                    "role": current_user.role,
                    "totp_enabled": current_user.totp_enabled,
                },
            }
        ),
        200,
    )


@api_bp.route("/auth/refresh", methods=["POST"])
@token_required
def api_refresh_token(current_user):
    """Token erneuern"""
    token = generate_jwt_token(current_user.id)
    return jsonify({"token": token}), 200


@api_bp.route("/auth/device", methods=["POST"])
def api_device_login():
    """Tauscht ein widerrufbares Geraete-Token (siehe /settings/device-tokens)
    gegen ein kurzlebiges JWT -- fuer Android-App o.ae., ohne dass sich das
    Geraet mit Benutzername/Passwort einloggen muss."""
    from crowdsec_app import crowdsec_app

    data = request.get_json()
    token = data.get("token") if data else None

    if not token:
        return jsonify({"error": "token required"}), 400

    token_row = DeviceToken.query.filter_by(token=token).first()

    if not token_row or not token_row.user.is_active:
        crowdsec_app.log_failed_login("device-token", reason="invalid_device_token")
        return jsonify({"error": "invalid or revoked token"}), 401

    token_row.last_used_at = datetime.utcnow()
    token_row.last_used_ip = request.remote_addr
    db.session.commit()

    user = token_row.user
    jwt_token = generate_jwt_token(user.id)

    return (
        jsonify(
            {
                "token": jwt_token,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "role": user.role,
                    "totp_enabled": user.totp_enabled,
                },
            }
        ),
        200,
    )


@api_bp.route("/invoices", methods=["GET"])
@token_required
def api_list_invoices(current_user):  # pylint: disable=unused-argument
    """API: Liste aller Rechnungen"""
    status = request.args.get("status")
    limit = request.args.get("limit", 50, type=int)

    query = Invoice.query

    if status:
        query = query.filter_by(status=status)

    invoices = query.order_by(Invoice.created_at.desc()).limit(limit).all()

    return (
        jsonify(
            {
                "invoices": [
                    {
                        "id": inv.id,
                        "invoice_number": inv.invoice_number,
                        "customer": {
                            "id": inv.customer.id,
                            "name": inv.customer.company_name or f"{inv.customer.first_name} {inv.customer.last_name}",
                        },
                        "invoice_date": inv.invoice_date.isoformat(),
                        "due_date": inv.due_date.isoformat() if inv.due_date else None,
                        "total": float(inv.total),
                        "status": inv.status,
                        "created_at": inv.created_at.isoformat(),
                    }
                    for inv in invoices
                ]
            }
        ),
        200,
    )


@api_bp.route("/invoices/<int:invoice_id>", methods=["GET"])
@token_required
def api_get_invoice(current_user, invoice_id):  # pylint: disable=unused-argument
    """API: Einzelne Rechnung abrufen"""
    invoice = Invoice.query.get_or_404(invoice_id)

    return (
        jsonify(
            {
                "id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "customer": {
                    "id": invoice.customer.id,
                    "company_name": invoice.customer.company_name,
                    "first_name": invoice.customer.first_name,
                    "last_name": invoice.customer.last_name,
                    "email": invoice.customer.email,
                    "address": invoice.customer.address,
                },
                "invoice_date": invoice.invoice_date.isoformat(),
                "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
                "line_items": [
                    {
                        "description": item.description,
                        "quantity": float(item.quantity),
                        "unit_price": float(item.unit_price),
                        "total": float(item.total),
                        "tax_rate": float(item.tax_rate),
                    }
                    for item in invoice.line_items
                ],
                "subtotal": float(invoice.subtotal),
                "tax_amount": float(invoice.tax_amount),
                "total": float(invoice.total),
                "status": invoice.status,
                "notes": invoice.notes,
                "payment_method": invoice.payment_method,
                "created_at": invoice.created_at.isoformat(),
            }
        ),
        200,
    )


@api_bp.route("/customers", methods=["GET"])
@token_required
def api_list_customers(current_user):  # pylint: disable=unused-argument
    """API: Liste aller Kunden"""
    limit = request.args.get("limit", 100, type=int)
    search = request.args.get("q")

    query = Customer.query

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Customer.company_name.ilike(search_term))
            | (Customer.first_name.ilike(search_term))
            | (Customer.last_name.ilike(search_term))
            | (Customer.email.ilike(search_term))
        )

    customers = query.order_by(Customer.company_name).limit(limit).all()

    return (
        jsonify(
            {
                "customers": [
                    {
                        "id": c.id,
                        "company_name": c.company_name,
                        "first_name": c.first_name,
                        "last_name": c.last_name,
                        "email": c.email,
                        "phone": c.phone,
                        "address": c.address,
                    }
                    for c in customers
                ]
            }
        ),
        200,
    )


@api_bp.route("/pos/complete-sale", methods=["POST"])
@token_required
@role_required_api("cashier", "admin")
def api_pos_complete_sale(current_user):
    """API: POS Verkauf abschließen"""
    data = request.get_json()

    if not data or not data.get("items"):
        return jsonify({"error": "Items required"}), 400

    try:
        customer = Customer(
            first_name="Barkunde",
            last_name=f"POS-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            email=f"pos-{datetime.now().strftime('%Y%m%d%H%M%S')}@local.internal",
        )
        db.session.add(customer)
        db.session.flush()

        invoice_number = generate_invoice_number()
        invoice = Invoice(
            invoice_number=invoice_number,
            customer_id=customer.id,
            invoice_date=datetime.now().date(),
            tax_rate=float(data.get("tax_rate", current_app.config.get("DEFAULT_TAX_RATE", 19.0))),
            payment_method="bar",
            status="paid",
        )
        db.session.add(invoice)
        db.session.flush()

        total = Decimal("0")

        for item_data in data["items"]:
            product = Product.query.get(item_data["product_id"])
            if not product:
                raise ValueError(f"Product {item_data['product_id']} not found")

            quantity = Decimal(str(item_data["quantity"]))

            if product.number < quantity:
                raise ValueError(f"Not enough stock for {product.name}")

            product.number -= int(quantity)

            line_total = quantity * product.price

            line_item = LineItem(
                invoice_id=invoice.id,
                description=product.name,
                quantity=quantity,
                unit_price=product.price,
                total=line_total,
                tax_rate=invoice.tax_rate,
                product_id=product.id,
            )
            db.session.add(line_item)
            total += line_total

        invoice.subtotal = total
        invoice.tax_amount = total * (invoice.tax_rate / Decimal("100"))
        invoice.total = invoice.subtotal + invoice.tax_amount

        status_log = InvoiceStatusLog(
            invoice_id=invoice.id,
            old_status=None,
            new_status="paid",
            changed_by=current_user.username,
            reason="POS sale via API",
        )
        db.session.add(status_log)

        db.session.commit()

        return (
            jsonify(
                {
                    "success": True,
                    "invoice_id": invoice.id,
                    "invoice_number": invoice_number,
                    "total": float(invoice.total),
                }
            ),
            201,
        )

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400


@api_bp.route("/customers/search")
@login_required
def api_search_customers():
    """API Endpoint für Kundensuche (Autocomplete)"""
    query = request.args.get("q", "").strip()

    if len(query) < 3:
        return jsonify([])

    search_pattern = f"%{query}%"
    customers = (
        Customer.query.filter(
            db.or_(
                Customer.company_name.ilike(search_pattern),
                Customer.first_name.ilike(search_pattern),
                Customer.last_name.ilike(search_pattern),
                Customer.email.ilike(search_pattern),
            )
        )
        .limit(10)
        .all()
    )

    results = []
    for customer in customers:
        results.append(
            {
                "id": customer.id,
                "company_name": customer.company_name or "",
                "first_name": customer.first_name or "",
                "last_name": customer.last_name or "",
                "email": customer.email or "",
                "phone": customer.phone or "",
                "address": customer.address or "",
                "tax_id": customer.tax_id or "",
                "display_name": customer.display_name,
            }
        )

    return jsonify(results)


@api_bp.route("/products/search")
@login_required
def api_search_products():
    """API Endpoint für Produktsuche (Autocomplete)"""
    query = request.args.get("q", "").strip()

    if len(query) < 2:
        return jsonify([])

    search_pattern = f"%{query}%"
    products = (
        Product.query.filter(
            Product.active.is_(True),
            db.or_(
                Product.name.ilike(search_pattern),
                Product.lot_number.ilike(search_pattern),
                Product.quantity.ilike(search_pattern),
            ),
        )
        .limit(10)
        .all()
    )

    results = []
    for product in products:
        results.append(
            {
                "id": product.id,
                "name": product.name,
                "quantity": product.quantity or "",
                "price": float(product.price),
                "reseller_price": float(product.reseller_price) if product.reseller_price else None,
                "number": product.number,
                "lot_number": product.lot_number or "",
                "display_name": f"{product.name} {product.quantity}" if product.quantity else product.name,
            }
        )

    return jsonify(results)


@api_bp.route("/products/lot/<lot_number>/stock/add", methods=["POST"])
@login_required
def api_add_stock_by_lot(lot_number):
    """API Endpoint zum Hinzufügen von Bestand via lot_number"""
    try:
        data = request.get_json() or {}
        amount = int(data.get("amount", 0))

        if amount <= 0:
            return jsonify({"success": False, "error": "Menge muss größer als 0 sein"}), 400

        product = Product.query.filter_by(lot_number=lot_number).first()

        if product:
            product.increase_stock(amount)
            db.session.commit()

            return jsonify(
                {
                    "success": True,
                    "message": f"{amount} Stück zu Charge {lot_number} hinzugefügt",
                    "product_id": product.id,
                    "product_name": product.name,
                    "lot_number": product.lot_number,
                    "new_stock": product.number,
                }
            )
        else:
            new_product = Product(
                name=f"Produkt {lot_number}",
                lot_number=lot_number,
                number=amount,
                price=0.0,
                active=False,
            )
            db.session.add(new_product)
            db.session.commit()

            return (
                jsonify(
                    {
                        "success": True,
                        "message": f"Neues Produkt mit Charge {lot_number} angelegt ({amount} Stück)",
                        "product_id": new_product.id,
                        "product_name": new_product.name,
                        "lot_number": new_product.lot_number,
                        "new_stock": new_product.number,
                        "new_product": True,
                    }
                ),
                201,
            )

    except ValueError:
        return jsonify({"success": False, "error": "Ungültige Menge"}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route("/products/lot/<lot_number>/stock/reduce", methods=["POST"])
@login_required
def api_reduce_stock_by_lot(lot_number):
    """API Endpoint zum Reduzieren von Bestand via lot_number"""
    try:
        data = request.get_json() or {}
        amount = int(data.get("amount", 0))

        if amount <= 0:
            return jsonify({"success": False, "error": "Menge muss größer als 0 sein"}), 400

        product = Product.query.filter_by(lot_number=lot_number).first()

        if not product:
            return jsonify({"success": False, "error": f"Kein Produkt mit Charge {lot_number} gefunden"}), 404

        if product.number < amount:
            return (
                jsonify({"success": False, "error": f"Nicht genug Bestand vorhanden (aktuell: {product.number})"}),
                400,
            )

        product.reduce_stock(amount)
        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": f"{amount} Stück von Charge {lot_number} abgezogen",
                "product_id": product.id,
                "product_name": product.name,
                "lot_number": product.lot_number,
                "new_stock": product.number,
            }
        )

    except ValueError:
        return jsonify({"success": False, "error": "Ungültige Menge"}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route("/products/<int:product_id>/stock/add", methods=["POST"])
@login_required
def api_add_stock(product_id):
    """API Endpoint zum Hinzufügen von Bestand (legacy, für Web-UI)"""
    try:
        data = request.get_json()
        lot_number = data.get("lot_number", "").strip()
        amount = int(data.get("amount", 0))

        if amount <= 0:
            return jsonify({"success": False, "error": "Menge muss größer als 0 sein"}), 400

        if lot_number:
            existing = Product.query.filter_by(name=Product.query.get(product_id).name, lot_number=lot_number).first()

            if existing and existing.id != product_id:
                existing.increase_stock(amount)
                db.session.commit()

                return jsonify(
                    {
                        "success": True,
                        "message": f"{amount} Stück zu existierender Charge {lot_number} hinzugefügt",
                        "product_id": existing.id,
                        "new_stock": existing.number,
                    }
                )

        product = Product.query.get_or_404(product_id)

        if lot_number:
            product.lot_number = lot_number

        product.increase_stock(amount)
        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": f"{amount} Stück hinzugefügt",
                "product_id": product.id,
                "new_stock": product.number,
                "lot_number": product.lot_number,
            }
        )

    except ValueError:
        return jsonify({"success": False, "error": "Ungültige Menge"}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route("/products/<int:product_id>/stock/reduce", methods=["POST"])
@login_required
def api_reduce_stock(product_id):
    """API Endpoint zum Reduzieren von Bestand (legacy, für Web-UI)"""
    try:
        data = request.get_json()
        lot_number = data.get("lot_number", "").strip()
        amount = int(data.get("amount", 0))

        if amount <= 0:
            return jsonify({"success": False, "error": "Menge muss größer als 0 sein"}), 400

        product = Product.query.get_or_404(product_id)

        if product.number < amount:
            return (
                jsonify({"success": False, "error": f"Nicht genug Bestand vorhanden (aktuell: {product.number})"}),
                400,
            )

        if lot_number:
            product.lot_number = lot_number

        product.reduce_stock(amount)
        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": f"{amount} Stück abgezogen",
                "product_id": product.id,
                "new_stock": product.number,
                "lot_number": product.lot_number,
            }
        )

    except ValueError:
        return jsonify({"success": False, "error": "Ungültige Menge"}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
