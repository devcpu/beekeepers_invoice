from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from config import config
from models import db, Customer, Invoice, LineItem, Product, PaymentCheck, Reminder, DeliveryNote, DeliveryNoteItem, ConsignmentStock, InvoiceStatusLog, InvoicePdfArchive, User, StockAdjustment
from email_service import mail
from datetime import datetime, timedelta
from decimal import Decimal
from functools import wraps
import os
import json

def create_app(config_name='default'):
    """Flask App Factory"""
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    # Datenbank initialisieren
    db.init_app(app)
    
    # E-Mail initialisieren
    mail.init_app(app)
    
    # Flask-Login initialisieren
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = 'Bitte melden Sie sich an, um auf diese Seite zuzugreifen.'
    login_manager.login_message_category = 'info'
    
    # CrowdSec Integration
    from crowdsec_app import crowdsec_app
    crowdsec_app.init_app(app)
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # Custom Decorator für Rollen-basierte Zugriffskontrolle
    def role_required(*roles):
        """Decorator für Rollen-basierte Zugriffskontrolle"""
        def decorator(f):
            @wraps(f)
            @login_required
            def decorated_function(*args, **kwargs):
                if not any(current_user.has_role(role) for role in roles):
                    flash('Sie haben keine Berechtigung für diese Aktion.', 'danger')
                    return redirect(url_for('index'))
                return f(*args, **kwargs)
            return decorated_function
        return decorator
    
    # Ordner erstellen falls nicht vorhanden
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['PDF_FOLDER'], exist_ok=True)
    
    # Context Processor für Templates
    @app.context_processor
    def utility_processor():
        return dict(now=datetime.now())
    
    # ========== AUTHENTIFIZIERUNGS-ROUTEN ==========
    
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """Login-Seite"""
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            remember = request.form.get('remember', False) == 'on'
            
            user = User.query.filter_by(username=username).first()
            
            if user and user.check_password(password):
                if not user.is_active:
                    # CrowdSec: Account deaktiviert
                    crowdsec_app.log_failed_login(username, reason='account_disabled')
                    flash('Ihr Account wurde deaktiviert.', 'danger')
                    return redirect(url_for('login'))
                
                # Prüfe 2FA-Pflicht
                if user.totp_required and not user.totp_enabled:
                    # 2FA ist Pflicht, aber noch nicht aktiviert
                    login_user(user, remember=remember)
                    user.last_login = datetime.utcnow()
                    user.last_login_ip = request.remote_addr
                    db.session.commit()
                    
                    flash('Ihr Administrator hat 2FA für Ihren Account verpflichtend gemacht. Bitte richten Sie 2FA jetzt ein.', 'warning')
                    return redirect(url_for('setup_2fa'))
                
                # 2FA Check (wenn aktiviert)
                if user.totp_enabled:
                    # 2FA-Token erforderlich
                    session['pending_user_id'] = user.id
                    session['remember_me'] = remember
                    return redirect(url_for('verify_2fa'))
                
                # Login ohne 2FA
                login_user(user, remember=remember)
                user.last_login = datetime.utcnow()
                user.last_login_ip = request.remote_addr
                db.session.commit()
                
                flash(f'Willkommen zurück, {user.username}!', 'success')
                next_page = request.args.get('next')
                return redirect(next_page) if next_page else redirect(url_for('index'))
            else:
                # CrowdSec: Failed Login
                crowdsec_app.log_failed_login(username or 'unknown', reason='invalid_credentials')
                flash('Ungültiger Benutzername oder Passwort.', 'danger')
        
        return render_template('auth/login.html')
    
    @app.route('/verify-2fa', methods=['GET', 'POST'])
    def verify_2fa():
        """2FA-Verifizierung"""
        if 'pending_user_id' not in session:
            return redirect(url_for('login'))
        
        user = User.query.get(session['pending_user_id'])
        if not user:
            session.pop('pending_user_id', None)
            return redirect(url_for('login'))
        
        if request.method == 'POST':
            token = request.form.get('token', '').replace(' ', '')
            
            # Versuche TOTP
            if user.verify_totp(token):
                login_user(user, remember=session.get('remember_me', False))
                user.last_login = datetime.utcnow()
                user.last_login_ip = request.remote_addr
                db.session.commit()
                
                session.pop('pending_user_id', None)
                session.pop('remember_me', None)
                
                flash(f'Willkommen zurück, {user.username}!', 'success')
                return redirect(url_for('index'))
            
            # Versuche Backup-Code
            elif user.verify_backup_code(token):
                db.session.commit()  # Backup-Code wird verbraucht
                
                login_user(user, remember=session.get('remember_me', False))
                user.last_login = datetime.utcnow()
                user.last_login_ip = request.remote_addr
                db.session.commit()
                
                session.pop('pending_user_id', None)
                session.pop('remember_me', None)
                
                flash(f'Login mit Backup-Code erfolgreich. Noch {len(json.loads(user.backup_codes)) if user.backup_codes else 0} Backup-Codes verfügbar.', 'warning')
                return redirect(url_for('index'))
            else:
                flash('Ungültiger 2FA-Code.', 'danger')
        
        return render_template('auth/verify_2fa.html', user=user)
    
    @app.route('/logout')
    @login_required
    def logout():
        """Logout"""
        logout_user()
        flash('Sie wurden erfolgreich abgemeldet.', 'success')
        return redirect(url_for('login'))
    
    @app.route('/select-stock-source', methods=['GET', 'POST'])
    @login_required
    def select_stock_source():
        """Bestandsquelle auswählen (Hauptbestand oder Marktbestand)"""
        if request.method == 'POST':
            stock_source = request.form.get('stock_source')
            if stock_source in ['main', 'market']:
                session['stock_source'] = stock_source
                flash(f'Bestandsquelle gewählt: {"Hauptbestand (Zuhause)" if stock_source == "main" else "Marktbestand (Markt)"}', 'success')
                return redirect(url_for('index'))
            else:
                flash('Ungültige Auswahl.', 'error')
        
        # Prüfe ob Marktbestand existiert
        has_market_stock = False
        if current_user.reseller_customer_id:
            has_market_stock = ConsignmentStock.query.filter_by(
                customer_id=current_user.reseller_customer_id
            ).first() is not None
        
        return render_template('select_stock_source.html', has_market_stock=has_market_stock)
    
    @app.route('/offline')
    def offline():
        """PWA Offline-Fallback Seite"""
        return render_template('offline.html')
    
    @app.route('/forgot-password', methods=['GET', 'POST'])
    def forgot_password():
        """Passwort vergessen - E-Mail-Anfrage"""
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        
        if request.method == 'POST':
            email = request.form.get('email')
            user = User.query.filter_by(email=email).first()
            
            if user and user.is_active:
                from password_reset import PasswordResetToken, send_password_reset_email
                from email_service import mail
                
                token = PasswordResetToken.create_reset_token(user)
                
                try:
                    send_password_reset_email(user, token, mail)
                    flash('Eine E-Mail mit Anweisungen zum Zurücksetzen des Passworts wurde gesendet.', 'success')
                except Exception as e:
                    app.logger.error(f'Fehler beim Senden der Reset-E-Mail: {str(e)}')
                    flash('Fehler beim Senden der E-Mail. Bitte kontaktieren Sie den Administrator.', 'danger')
            else:
                # Security: Immer gleiche Meldung, auch wenn E-Mail nicht existiert
                flash('Eine E-Mail mit Anweisungen zum Zurücksetzen des Passworts wurde gesendet.', 'success')
            
            return redirect(url_for('login'))
        
        return render_template('auth/forgot_password.html')
    
    @app.route('/reset-password/<token>', methods=['GET', 'POST'])
    def reset_password(token):
        """Passwort zurücksetzen mit Token"""
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        
        from password_reset import PasswordResetToken
        
        user = PasswordResetToken.verify_token(token)
        
        if not user:
            flash('Ungültiger oder abgelaufener Reset-Link.', 'danger')
            return redirect(url_for('login'))
        
        if request.method == 'POST':
            password = request.form.get('password')
            password_confirm = request.form.get('password_confirm')
            
            if password != password_confirm:
                flash('Die Passwörter stimmen nicht überein.', 'danger')
                return render_template('auth/reset_password.html', token=token)
            
            if len(password) < 8:
                flash('Das Passwort muss mindestens 8 Zeichen lang sein.', 'danger')
                return render_template('auth/reset_password.html', token=token)
            
            # Passwort setzen
            user.set_password(password)
            PasswordResetToken.invalidate_token(user)
            
            flash('Ihr Passwort wurde erfolgreich zurückgesetzt. Sie können sich jetzt anmelden.', 'success')
            return redirect(url_for('login'))
        
        return render_template('auth/reset_password.html', token=token)
    
    @app.route('/settings/2fa-setup', methods=['GET', 'POST'])
    @login_required
    def setup_2fa():
        """2FA aktivieren"""
        if current_user.totp_enabled:
            flash('2FA ist bereits aktiviert.', 'info')
            return redirect(url_for('settings'))
        
        if request.method == 'POST':
            token = request.form.get('token', '').replace(' ', '')
            
            # Verifiziere den eingegebenen Code
            if current_user.verify_totp(token):
                # Aktiviere 2FA
                current_user.totp_enabled = True
                
                # Generiere Backup-Codes
                backup_codes = current_user.generate_backup_codes()
                db.session.commit()
                
                flash('2FA wurde erfolgreich aktiviert! Bewahren Sie Ihre Backup-Codes sicher auf.', 'success')
                return render_template('auth/2fa_backup_codes.html', backup_codes=backup_codes)
            else:
                flash('Ungültiger Code. Bitte versuchen Sie es erneut.', 'danger')
        
        # Generiere TOTP-Secret (falls noch nicht vorhanden)
        if not current_user.totp_secret:
            current_user.generate_totp_secret()
            db.session.commit()
        
        # QR-Code generieren
        import qrcode
        import io
        import base64
        
        totp_uri = current_user.get_totp_uri()
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(totp_uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        qr_code_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        return render_template('auth/2fa_setup.html', 
                             qr_code=qr_code_base64, 
                             totp_secret=current_user.totp_secret)
    
    @app.route('/settings/2fa-disable', methods=['POST'])
    @login_required
    def disable_2fa():
        """2FA deaktivieren"""
        # Prüfe ob 2FA Pflicht ist
        if current_user.totp_required:
            flash('2FA ist für Ihren Account verpflichtend und kann nicht deaktiviert werden.', 'danger')
            return redirect(url_for('settings'))
        
        password = request.form.get('password')
        
        if not current_user.check_password(password):
            flash('Falsches Passwort.', 'danger')
            return redirect(url_for('settings'))
        
        current_user.totp_enabled = False
        current_user.totp_secret = None
        current_user.backup_codes = None
        db.session.commit()
        
        flash('2FA wurde deaktiviert.', 'warning')
        return redirect(url_for('settings'))
    
    @app.route('/settings/2fa-regenerate-codes', methods=['POST'])
    @login_required
    def regenerate_backup_codes():
        """Backup-Codes neu generieren"""
        if not current_user.totp_enabled:
            flash('2FA ist nicht aktiviert.', 'danger')
            return redirect(url_for('settings'))
        
        password = request.form.get('password')
        if not current_user.check_password(password):
            flash('Falsches Passwort.', 'danger')
            return redirect(url_for('settings'))
        
        backup_codes = current_user.generate_backup_codes()
        db.session.commit()
        
        flash('Neue Backup-Codes wurden generiert. Die alten Codes sind ungültig.', 'warning')
        return render_template('auth/2fa_backup_codes.html', backup_codes=backup_codes)
    
    # ========== HAUPTSEITEN-ROUTEN ==========
    
    # Health Check (für Docker/Kubernetes)
    @app.route('/health')
    def health_check():
        """Health Check Endpoint"""
        try:
            # DB Connection testen
            db.session.execute('SELECT 1')
            return {'status': 'healthy', 'database': 'ok'}, 200
        except Exception as e:
            return {'status': 'unhealthy', 'error': str(e)}, 503
    
    # ========== JWT API FÜR PWA ==========
    
    from jwt_api import generate_jwt_token, token_required, role_required_api
    
    @app.route('/api/auth/login', methods=['POST'])
    def api_login():
        """API Login - gibt JWT Token zurück"""
        data = request.get_json()
        
        if not data or not data.get('username') or not data.get('password'):
            return jsonify({'error': 'Username and password required'}), 400
        
        username = data.get('username')
        password = data.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if not user or not user.check_password(password):
            return jsonify({'error': 'Invalid credentials'}), 401
        
        if not user.is_active:
            return jsonify({'error': 'Account deactivated'}), 401
        
        # 2FA Check
        if user.totp_enabled:
            token_2fa = data.get('totp_token')
            
            if not token_2fa:
                return jsonify({
                    'error': '2FA required',
                    'requires_2fa': True
                }), 401
            
            if not user.verify_totp(token_2fa) and not user.verify_backup_code(token_2fa):
                return jsonify({'error': 'Invalid 2FA code'}), 401
            
            if user.verify_backup_code(token_2fa):
                db.session.commit()  # Backup-Code verbrauchen
        
        # JWT Token generieren
        token = generate_jwt_token(user.id)
        
        # Login-Timestamp aktualisieren
        user.last_login = datetime.utcnow()
        user.last_login_ip = request.remote_addr
        db.session.commit()
        
        return jsonify({
            'token': token,
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': user.role,
                'totp_enabled': user.totp_enabled
            }
        }), 200
    
    @app.route('/api/auth/verify', methods=['GET'])
    @token_required
    def api_verify_token(current_user):
        """Token verifizieren und User-Daten zurückgeben"""
        return jsonify({
            'valid': True,
            'user': {
                'id': current_user.id,
                'username': current_user.username,
                'email': current_user.email,
                'role': current_user.role,
                'totp_enabled': current_user.totp_enabled
            }
        }), 200
    
    @app.route('/api/auth/refresh', methods=['POST'])
    @token_required
    def api_refresh_token(current_user):
        """Token erneuern"""
        token = generate_jwt_token(current_user.id)
        return jsonify({'token': token}), 200
    
    @app.route('/api/invoices', methods=['GET'])
    @token_required
    def api_list_invoices(current_user):
        """API: Liste aller Rechnungen"""
        status = request.args.get('status')
        limit = request.args.get('limit', 50, type=int)
        
        query = Invoice.query
        
        if status:
            query = query.filter_by(status=status)
        
        invoices = query.order_by(Invoice.created_at.desc()).limit(limit).all()
        
        return jsonify({
            'invoices': [{
                'id': inv.id,
                'invoice_number': inv.invoice_number,
                'customer': {
                    'id': inv.customer.id,
                    'name': inv.customer.company_name or f"{inv.customer.first_name} {inv.customer.last_name}"
                },
                'invoice_date': inv.invoice_date.isoformat(),
                'due_date': inv.due_date.isoformat() if inv.due_date else None,
                'total': float(inv.total),
                'status': inv.status,
                'created_at': inv.created_at.isoformat()
            } for inv in invoices]
        }), 200
    
    @app.route('/api/invoices/<int:invoice_id>', methods=['GET'])
    @token_required
    def api_get_invoice(current_user, invoice_id):
        """API: Einzelne Rechnung abrufen"""
        invoice = Invoice.query.get_or_404(invoice_id)
        
        return jsonify({
            'id': invoice.id,
            'invoice_number': invoice.invoice_number,
            'customer': {
                'id': invoice.customer.id,
                'company_name': invoice.customer.company_name,
                'first_name': invoice.customer.first_name,
                'last_name': invoice.customer.last_name,
                'email': invoice.customer.email,
                'address': invoice.customer.address
            },
            'invoice_date': invoice.invoice_date.isoformat(),
            'due_date': invoice.due_date.isoformat() if invoice.due_date else None,
            'line_items': [{
                'description': item.description,
                'quantity': float(item.quantity),
                'unit_price': float(item.unit_price),
                'total': float(item.total),
                'tax_rate': float(item.tax_rate)
            } for item in invoice.line_items],
            'subtotal': float(invoice.subtotal),
            'tax_amount': float(invoice.tax_amount),
            'total': float(invoice.total),
            'status': invoice.status,
            'notes': invoice.notes,
            'payment_method': invoice.payment_method,
            'created_at': invoice.created_at.isoformat()
        }), 200
    
    @app.route('/api/customers', methods=['GET'])
    @token_required
    def api_list_customers(current_user):
        """API: Liste aller Kunden"""
        limit = request.args.get('limit', 100, type=int)
        search = request.args.get('q')
        
        query = Customer.query
        
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                (Customer.company_name.ilike(search_term)) |
                (Customer.first_name.ilike(search_term)) |
                (Customer.last_name.ilike(search_term)) |
                (Customer.email.ilike(search_term))
            )
        
        customers = query.order_by(Customer.company_name).limit(limit).all()
        
        return jsonify({
            'customers': [{
                'id': c.id,
                'company_name': c.company_name,
                'first_name': c.first_name,
                'last_name': c.last_name,
                'email': c.email,
                'phone': c.phone,
                'address': c.address
            } for c in customers]
        }), 200
    
    @app.route('/api/pos/complete-sale', methods=['POST'])
    @token_required
    @role_required_api('cashier', 'admin')
    def api_pos_complete_sale(current_user):
        """API: POS Verkauf abschließen"""
        data = request.get_json()
        
        if not data or not data.get('items'):
            return jsonify({'error': 'Items required'}), 400
        
        try:
            # Kunde erstellen (Barverkauf)
            customer = Customer(
                first_name='Barkunde',
                last_name=f"POS-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                email=f"pos-{datetime.now().strftime('%Y%m%d%H%M%S')}@local.internal"
            )
            db.session.add(customer)
            db.session.flush()
            
            # Rechnung erstellen
            invoice_number = generate_invoice_number()
            invoice = Invoice(
                invoice_number=invoice_number,
                customer_id=customer.id,
                invoice_date=datetime.now().date(),
                tax_rate=float(data.get('tax_rate', app.config.get('DEFAULT_TAX_RATE', 19.0))),
                payment_method='bar',
                status='paid'
            )
            db.session.add(invoice)
            db.session.flush()
            
            total = Decimal('0')
            
            # Positionen hinzufügen
            for item_data in data['items']:
                product = Product.query.get(item_data['product_id'])
                if not product:
                    raise ValueError(f"Product {item_data['product_id']} not found")
                
                quantity = Decimal(str(item_data['quantity']))
                
                # Bestand prüfen
                if product.number < quantity:
                    raise ValueError(f"Not enough stock for {product.name}")
                
                # Bestand reduzieren
                product.number -= int(quantity)
                
                line_total = quantity * product.price
                
                line_item = LineItem(
                    invoice_id=invoice.id,
                    description=product.name,
                    quantity=quantity,
                    unit_price=product.price,
                    total=line_total,
                    tax_rate=invoice.tax_rate,
                    product_id=product.id
                )
                db.session.add(line_item)
                total += line_total
            
            invoice.subtotal = total
            invoice.tax_amount = total * (invoice.tax_rate / Decimal('100'))
            invoice.total = invoice.subtotal + invoice.tax_amount
            
            # Status-Log
            status_log = InvoiceStatusLog(
                invoice_id=invoice.id,
                old_status=None,
                new_status='paid',
                changed_by=current_user.username,
                reason='POS sale via API'
            )
            db.session.add(status_log)
            
            db.session.commit()
            
            return jsonify({
                'success': True,
                'invoice_id': invoice.id,
                'invoice_number': invoice_number,
                'total': float(invoice.total)
            }), 201
            
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400
    
    # ========== HAUPTSEITEN-ROUTEN ==========
    
    # Routes
    @app.route('/')
    @login_required
    def index():
        """Startseite mit Übersicht"""
        from datetime import datetime, timedelta
        
        # Prüfe ob Bestandsauswahl nötig ist
        if current_user.reseller_customer_id and 'stock_source' not in session:
            # Prüfe ob ConsignmentStock existiert
            has_stock = ConsignmentStock.query.filter_by(
                customer_id=current_user.reseller_customer_id
            ).first() is not None
            
            if has_stock:
                return redirect(url_for('select_stock_source'))
        
        recent_invoices = Invoice.query.order_by(Invoice.created_at.desc()).limit(10).all()
        stats = {
            'total_invoices': Invoice.query.count(),
            'draft_invoices': Invoice.query.filter_by(status='draft').count(),
            'sent_invoices': Invoice.query.filter_by(status='sent').count(),
            'paid_invoices': Invoice.query.filter_by(status='paid').count(),
            'cancelled_invoices': Invoice.query.filter_by(status='cancelled').count(),
            'total_customers': Customer.query.count()
        }
        
        # Produkte mit niedrigem Bestand (aktiv und < 25)
        low_stock_products = Product.query.filter(
            Product.active == True,
            Product.number < 25
        ).order_by(Product.number.asc()).all()
        
        # Überfällige Rechnungen (mehr als 10 Tage überfällig)
        overdue_date = datetime.now().date() - timedelta(days=10)
        overdue_invoices = Invoice.query.filter(
            Invoice.status == 'sent',
            Invoice.due_date.isnot(None),
            Invoice.due_date < overdue_date
        ).order_by(Invoice.due_date.asc()).all()
        
        return render_template('index.html', 
                             invoices=recent_invoices, 
                             stats=stats,
                             low_stock_products=low_stock_products,
                             overdue_invoices=overdue_invoices)
    
    @app.route('/invoices')
    @login_required
    def list_invoices():
        """Liste aller Rechnungen"""
        from datetime import datetime, timedelta
        
        status_filter = request.args.get('status', None)
        custom_filter = request.args.get('filter', None)
        query = Invoice.query
        
        if status_filter:
            query = query.filter_by(status=status_filter)
        elif custom_filter == 'storno':
            # Nur Stornorechnungen (beginnen mit STORNO-)
            query = query.filter(Invoice.invoice_number.like('STORNO-%'))
        elif custom_filter == 'open':
            # Versendet aber nicht bezahlt
            query = query.filter_by(status='sent')
        elif custom_filter == 'overdue':
            # Fälligkeitsdatum mehr als 10 Tage überschritten
            overdue_date = datetime.now().date() - timedelta(days=10)
            query = query.filter(
                Invoice.status == 'sent',
                Invoice.due_date.isnot(None),
                Invoice.due_date < overdue_date
            )
        
        invoices = query.order_by(Invoice.invoice_date.desc()).all()
        return render_template('invoices/list.html', invoices=invoices, status_filter=status_filter)
    
    @app.route('/invoices/new', methods=['GET', 'POST'])
    @login_required
    def create_invoice():
        """Neue Rechnung erstellen"""
        if request.method == 'POST':
            try:
                # Kunde suchen oder erstellen
                customer_email = request.form.get('customer_email')
                customer = Customer.query.filter_by(email=customer_email).first()
                
                if not customer:
                    customer = Customer(
                        company_name=request.form.get('company_name'),
                        first_name=request.form.get('first_name'),
                        last_name=request.form.get('last_name'),
                        email=customer_email,
                        phone=request.form.get('phone'),
                        address=request.form.get('address'),
                        tax_id=request.form.get('tax_id')
                    )
                    db.session.add(customer)
                    db.session.flush()  # Um die customer.id zu bekommen
                
                # Rechnung erstellen
                invoice_number = generate_invoice_number()
                
                # Steuermodell bestimmen
                tax_model = request.form.get('tax_model', 'landwirtschaft')
                
                # Kundentyp (Endkunde oder Wiederverkäufer)
                customer_type = request.form.get('customer_type', 'endkunde')
                
                # Steuersatz je nach Modell
                if tax_model == 'standard':
                    tax_rate = float(request.form.get('tax_rate', app.config.get('DEFAULT_TAX_RATE', 19.0)))
                elif tax_model == 'landwirtschaft':
                    tax_rate = float(app.config.get('LANDWIRTSCHAFTLICHE_URPRODUKTION_TAX_RATE', 7.8))
                else:  # kleinunternehmer
                    tax_rate = 0.0
                
                invoice = Invoice(
                    invoice_number=invoice_number,
                    customer_id=customer.id,
                    invoice_date=datetime.strptime(request.form.get('invoice_date'), '%Y-%m-%d').date(),
                    due_date=datetime.strptime(request.form.get('due_date'), '%Y-%m-%d').date() if request.form.get('due_date') else None,
                    tax_rate=tax_rate,
                    tax_model=tax_model,
                    customer_type=customer_type,
                    notes=request.form.get('notes'),
                    payment_method=request.form.get('payment_method')
                )
                
                # Positionen hinzufügen
                descriptions = request.form.getlist('description[]')
                quantities = request.form.getlist('quantity[]')
                unit_prices = request.form.getlist('unit_price[]')
                product_ids = request.form.getlist('product_id[]')
                
                for idx, (desc, qty, price, prod_id) in enumerate(zip(descriptions, quantities, unit_prices, product_ids)):
                    if desc and qty and price:
                        # Tax Rate aus Produkt holen (falls vorhanden)
                        tax_rate_for_item = None
                        if prod_id and prod_id.strip():
                            product = Product.query.get(int(prod_id))
                            if product and product.tax_rate:
                                tax_rate_for_item = product.tax_rate
                        
                        line_item = LineItem(
                            product_id=int(prod_id) if prod_id and prod_id.strip() else None,
                            description=desc,
                            quantity=float(qty),
                            unit_price=float(price),
                            tax_rate=tax_rate_for_item,
                            position=idx
                        )
                        line_item.calculate_total()
                        invoice.line_items.append(line_item)
                
                # Summen berechnen und Hash generieren
                invoice.calculate_totals()
                invoice.generate_hash()
                
                db.session.add(invoice)
                db.session.commit()
                
                flash(f'Rechnung {invoice_number} erfolgreich erstellt!', 'success')
                return redirect(url_for('view_invoice', invoice_id=invoice.id))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Fehler beim Erstellen der Rechnung: {str(e)}', 'error')
                return redirect(url_for('create_invoice'))
        
        # GET: Formular anzeigen
        customers = Customer.query.order_by(Customer.company_name, Customer.last_name).all()
        today = datetime.now().date()
        due_date_default = today + timedelta(days=14)
        default_tax_rate = app.config.get('DEFAULT_TAX_RATE', 19.00)
        landw_tax_rate = app.config.get('LANDWIRTSCHAFTLICHE_URPRODUKTION_TAX_RATE', 7.80)
        
        return render_template('invoices/create.html', 
                             customers=customers,
                             today=today,
                             due_date_default=due_date_default,
                             default_tax_rate=default_tax_rate,
                             landw_tax_rate=landw_tax_rate)
    
    @app.route('/invoices/<int:invoice_id>')
    @login_required
    def view_invoice(invoice_id):
        """Einzelne Rechnung anzeigen"""
        invoice = Invoice.query.get_or_404(invoice_id)
        is_valid = invoice.verify_hash()
        return render_template('invoices/view.html', invoice=invoice, is_valid=is_valid)
    
    @app.route('/invoices/<int:invoice_id>/status/<status>')
    @login_required
    def update_invoice_status(invoice_id, status):
        """Status einer Rechnung ändern (GoBD-konform mit Audit Trail)"""
        invoice = Invoice.query.get_or_404(invoice_id)
        
        # Erlaubte Status
        allowed_statuses = ['draft', 'sent', 'paid', 'cancelled']
        if status not in allowed_statuses:
            flash(f'Ungültiger Status: {status}', 'error')
            return redirect(url_for('view_invoice', invoice_id=invoice_id))
        
        old_status = invoice.status
        
        # GoBD: Keine Änderungen nach "sent" außer paid/cancelled
        if old_status == 'sent' and status == 'draft':
            flash('Fehler: Versendete Rechnungen können nicht zurück in Entwurf gesetzt werden (GoBD-Konformität).', 'error')
            return redirect(url_for('view_invoice', invoice_id=invoice_id))
        
        if old_status == 'paid' and status != 'cancelled':
            flash('Fehler: Bezahlte Rechnungen können nur storniert werden.', 'error')
            return redirect(url_for('view_invoice', invoice_id=invoice_id))
        
        # Bei Stornierung: Bestand zurückbuchen
        if status == 'cancelled' and old_status != 'cancelled':
            try:
                for line_item in invoice.line_items:
                    if line_item.product_id:
                        product = Product.query.get(line_item.product_id)
                        if product:
                            # Menge zurück ins Lager
                            product.number += int(line_item.quantity)
                            
                            # Bei Reseller: Auch Kommissionslager korrigieren
                            if invoice.customer_type == 'reseller':
                                stock = ConsignmentStock.query.filter_by(
                                    customer_id=invoice.customer_id,
                                    product_id=line_item.product_id
                                ).first()
                                if stock:
                                    # Menge zurück ins Kommissionslager
                                    stock.quantity += int(line_item.quantity)
                
                flash('Bestand wurde zurückgebucht.', 'info')
            except Exception as e:
                db.session.rollback()
                flash(f'Fehler bei Bestandsrückbuchung: {str(e)}', 'error')
                return redirect(url_for('view_invoice', invoice_id=invoice_id))
        
        invoice.status = status
        
        # GoBD: Audit Trail - Status-Änderung protokollieren
        status_log = InvoiceStatusLog(
            invoice_id=invoice.id,
            old_status=old_status,
            new_status=status,
            changed_by=current_user.username,
            reason=request.args.get('reason', None)  # Optional: Begründung aus URL
        )
        db.session.add(status_log)
        
        try:
            db.session.commit()
            
            status_names = {
                'draft': 'Entwurf',
                'sent': 'Versendet',
                'paid': 'Bezahlt',
                'cancelled': 'Storniert'
            }
            
            flash(f'Status von "{status_names.get(old_status, old_status)}" zu "{status_names.get(status, status)}" geändert.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Ändern des Status: {str(e)}', 'error')
        
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    @app.route('/invoices/<int:invoice_id>/delete', methods=['POST'])
    @login_required
    def delete_invoice(invoice_id):
        """Rechnung löschen (nur bei Status 'draft' erlaubt - GoBD-konform)"""
        invoice = Invoice.query.get_or_404(invoice_id)
        
        # GoBD: Nur Entwürfe dürfen gelöscht werden
        if invoice.status != 'draft':
            flash('Fehler: Nur Entwürfe können gelöscht werden. Versendete Rechnungen müssen storniert werden (GoBD-Konformität).', 'error')
            return redirect(url_for('view_invoice', invoice_id=invoice_id))
        
        try:
            invoice_number = invoice.invoice_number
            
            # Bestand zurückbuchen (da beim Erstellen abgezogen)
            for line_item in invoice.line_items:
                if line_item.product_id:
                    product = Product.query.get(line_item.product_id)
                    if product:
                        # Menge zurück ins Lager
                        product.number += int(line_item.quantity)
                        
                        # Bei Reseller: Auch Kommissionslager korrigieren
                        if invoice.customer_type == 'reseller':
                            stock = ConsignmentStock.query.filter_by(
                                customer_id=invoice.customer_id,
                                product_id=line_item.product_id
                            ).first()
                            if stock:
                                # Menge zurück ins Kommissionslager
                                stock.quantity_remaining += int(line_item.quantity)
            
            # Alle LineItems löschen (CASCADE sollte das eigentlich automatisch machen)
            for line_item in invoice.line_items:
                db.session.delete(line_item)
            
            # Status-Log-Einträge löschen (CASCADE)
            for log in invoice.status_history:
                db.session.delete(log)
            
            # Rechnung löschen
            db.session.delete(invoice)
            db.session.commit()
            
            flash(f'Entwurf "{invoice_number}" wurde gelöscht und Bestand zurückgebucht.', 'success')
            return redirect(url_for('list_invoices'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Löschen: {str(e)}', 'error')
            return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    @app.route('/invoices/<int:invoice_id>/create-cancellation', methods=['GET', 'POST'])
    @login_required
    def create_cancellation_invoice(invoice_id):
        """Erstellt eine Stornorechnung (GoBD-konform)"""
        original_invoice = Invoice.query.get_or_404(invoice_id)
        
        # Nur versendete oder bezahlte Rechnungen können storniert werden
        if original_invoice.status not in ['sent', 'paid']:
            flash('Nur versendete oder bezahlte Rechnungen können storniert werden.', 'error')
            return redirect(url_for('view_invoice', invoice_id=invoice_id))
        
        # Prüfen ob bereits storniert
        if original_invoice.status == 'cancelled':
            flash('Diese Rechnung wurde bereits storniert.', 'error')
            return redirect(url_for('view_invoice', invoice_id=invoice_id))
        
        if request.method == 'POST':
            try:
                reason = request.form.get('reason', 'Stornierung auf Kundenwunsch')
                
                # Neue Rechnungsnummer mit STORNO-Präfix generieren
                today = datetime.now().date()
                prefix = f"STORNO-{today.strftime('%Y-%m-%d')}"
                
                last_invoice = Invoice.query.filter(
                    Invoice.invoice_number.like(f"{prefix}%")
                ).order_by(Invoice.invoice_number.desc()).first()
                
                if last_invoice:
                    last_num = int(last_invoice.invoice_number.split('-')[-1])
                    next_num = last_num + 1
                else:
                    next_num = 1
                
                cancellation_number = f"{prefix}-{next_num:04d}"
                
                # Stornorechnung erstellen (Kopie mit negativen Beträgen)
                cancellation_invoice = Invoice(
                    invoice_number=cancellation_number,
                    customer_id=original_invoice.customer_id,
                    invoice_date=today,
                    due_date=today,  # Stornorechnungen sofort fällig
                    status='sent',  # Stornorechnung ist automatisch versendet
                    customer_type=original_invoice.customer_type,
                    tax_model=original_invoice.tax_model,
                    tax_rate=original_invoice.tax_rate,
                    subtotal=-original_invoice.subtotal,  # Negativ!
                    tax_amount=-original_invoice.tax_amount,  # Negativ!
                    total=-original_invoice.total,  # Negativ!
                    notes=f"Stornierung von Rechnung {original_invoice.invoice_number}\nGrund: {reason}"
                )
                
                # LineItems ERST erstellen, BEVOR wir zur Session hinzufügen
                line_items_list = []
                for orig_item in original_invoice.line_items:
                    cancellation_item = LineItem(
                        product_id=orig_item.product_id,
                        description=f"STORNO: {orig_item.description}",
                        quantity=-orig_item.quantity,  # Negativ!
                        unit_price=orig_item.unit_price,
                        tax_rate=orig_item.tax_rate,
                        total=-orig_item.total,  # Negativ!
                        position=orig_item.position
                    )
                    line_items_list.append(cancellation_item)
                
                # LineItems zur Rechnung hinzufügen (ohne DB-Flush)
                cancellation_invoice.line_items = line_items_list
                
                # JETZT Hash generieren (mit LineItems im Objekt, aber noch nicht in DB)
                cancellation_invoice.generate_hash()
                
                # Jetzt alles zur Session hinzufügen
                db.session.add(cancellation_invoice)
                
                # Bestand zurückbuchen
                for orig_item in original_invoice.line_items:
                    if orig_item.product_id:
                        product = Product.query.get(orig_item.product_id)
                        if product:
                            product.number += int(orig_item.quantity)
                            
                            # Bei Reseller: Kommissionslager anpassen
                            if original_invoice.customer_type == 'reseller':
                                stock = ConsignmentStock.query.filter_by(
                                    customer_id=original_invoice.customer_id,
                                    product_id=orig_item.product_id
                                ).first()
                                if stock:
                                    stock.quantity += int(orig_item.quantity)
                
                # JETZT flush - mit korrektem Hash
                db.session.flush()
                
                # Original-Rechnung auf storniert setzen
                original_invoice.status = 'cancelled'
                original_invoice.notes = (original_invoice.notes or '') + f"\n\nStorniert durch {cancellation_number} am {today.strftime('%d.%m.%Y')}"
                
                # Status-Log für beide Rechnungen
                db.session.add(InvoiceStatusLog(
                    invoice_id=original_invoice.id,
                    old_status='sent' if original_invoice.status != 'paid' else 'paid',
                    new_status='cancelled',
                    changed_by=current_user.username,
                    reason=f"Storniert durch {cancellation_number}: {reason}"
                ))
                
                db.session.add(InvoiceStatusLog(
                    invoice_id=cancellation_invoice.id,
                    old_status=None,
                    new_status='sent',
                    changed_by=current_user.username,
                    reason=f"Stornorechnung für {original_invoice.invoice_number}"
                ))
                
                db.session.commit()
                
                flash(f'Stornorechnung {cancellation_number} erfolgreich erstellt. Bestand wurde zurückgebucht.', 'success')
                return redirect(url_for('view_invoice', invoice_id=cancellation_invoice.id))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Fehler beim Erstellen der Stornorechnung: {str(e)}', 'error')
                return redirect(url_for('view_invoice', invoice_id=invoice_id))
        
        # GET: Formular anzeigen
        return render_template('invoices/create_cancellation.html', invoice=original_invoice)
    
    @app.route('/invoices/<int:invoice_id>/pdf')
    @login_required
    def download_invoice_pdf(invoice_id):
        """Rechnung als PDF herunterladen (GoBD-konform mit PDF-Archivierung)"""
        import hashlib
        from pdf_service import generate_invoice_pdf
        
        invoice = Invoice.query.get_or_404(invoice_id)
        pdf_path = generate_invoice_pdf(invoice, app.config['PDF_FOLDER'], app.config)
        
        # GoBD: PDF archivieren und hashen (nur bei erstmaligem Versand)
        if invoice.status == 'sent':
            # Prüfen ob schon archiviert
            existing_archive = InvoicePdfArchive.query.filter_by(
                invoice_id=invoice.id,
                pdf_filename=os.path.basename(pdf_path)
            ).first()
            
            if not existing_archive:
                # PDF hashen
                with open(pdf_path, 'rb') as f:
                    pdf_data = f.read()
                    pdf_hash = hashlib.sha256(pdf_data).hexdigest()
                    file_size = len(pdf_data)
                
                # In Archiv speichern
                archive = InvoicePdfArchive(
                    invoice_id=invoice.id,
                    pdf_filename=os.path.basename(pdf_path),
                    pdf_hash=pdf_hash,
                    file_size=file_size,
                    archived_by=current_user.username
                )
                db.session.add(archive)
                
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    # Fehler beim Archivieren nicht kritisch - PDF trotzdem ausliefern
                    app.logger.error(f'PDF-Archivierung fehlgeschlagen: {str(e)}')
        
        return send_file(pdf_path, as_attachment=True, download_name=f'Rechnung_{invoice.invoice_number}.pdf')
    
    @app.route('/invoices/<int:invoice_id>/send-email', methods=['GET', 'POST'])
    @login_required
    def send_invoice_email(invoice_id):
        """Rechnung per E-Mail versenden"""
        from pdf_service import generate_invoice_pdf
        from email_service import send_invoice_email as send_email
        
        invoice = Invoice.query.get_or_404(invoice_id)
        
        if request.method == 'POST':
            # E-Mail-Adresse aus Formular oder Kunden-E-Mail verwenden
            recipient_email = request.form.get('recipient_email') or invoice.customer.email
            cc_emails = request.form.get('cc_emails', '').strip()
            cc_list = [email.strip() for email in cc_emails.split(',') if email.strip()] if cc_emails else None
            
            # PDF generieren
            pdf_path = generate_invoice_pdf(invoice, app.config['PDF_FOLDER'], app.config)
            
            # E-Mail senden
            success = send_email(invoice, pdf_path, recipient_email, cc_list)
            
            if success:
                # Status auf "versendet" setzen, falls noch Entwurf
                if invoice.status == 'draft':
                    invoice.status = 'sent'
                    db.session.commit()
                
                flash(f'Rechnung erfolgreich an {recipient_email} versendet!', 'success')
                return redirect(url_for('view_invoice', invoice_id=invoice_id))
            else:
                flash('Fehler beim Versenden der E-Mail. Bitte überprüfen Sie die E-Mail-Konfiguration.', 'error')
        
        # GET: Formular anzeigen
        return render_template('invoices/send_email.html', invoice=invoice)
    
    @app.route('/invoices/<int:invoice_id>/reminder', methods=['GET', 'POST'])
    @login_required
    def create_reminder(invoice_id):
        """Mahnung erstellen und versenden"""
        from reminder_service import generate_reminder_pdf
        from email_service import send_email
        
        invoice = Invoice.query.get_or_404(invoice_id)
        
        # Prüfen ob Rechnung überhaupt überfällig ist
        if invoice.status != 'sent':
            flash('Mahnungen können nur für versendete, unbezahlte Rechnungen erstellt werden.', 'error')
            return redirect(url_for('view_invoice', invoice_id=invoice_id))
        
        if request.method == 'POST':
            action = request.form.get('action')  # 'download' oder 'send_email'
            
            # Mahnstufe ermitteln (nächste Stufe)
            existing_reminders = Reminder.query.filter_by(invoice_id=invoice_id).order_by(Reminder.reminder_level.desc()).first()
            reminder_level = 1 if not existing_reminders else existing_reminders.reminder_level + 1
            
            # Mahnung erstellen
            reminder = Reminder(
                invoice_id=invoice_id,
                reminder_level=reminder_level,
                reminder_date=datetime.utcnow(),
                reminder_fee=5.00 if reminder_level == 1 else 10.00  # Erste Mahnung 5€, weitere 10€
            )
            db.session.add(reminder)
            db.session.commit()
            
            # PDF generieren
            pdf_path = generate_reminder_pdf(invoice, reminder, app.config['PDF_FOLDER'], app.config)
            
            if action == 'download':
                # Als PDF herunterladen
                reminder.sent_via = 'pdf'
                reminder.sent_date = datetime.utcnow()
                db.session.commit()
                
                return send_file(pdf_path, as_attachment=True, 
                               download_name=f'Mahnung_{reminder_level}_{invoice.invoice_number}.pdf')
            
            elif action == 'send_email':
                # Per E-Mail versenden
                if not invoice.customer.email:
                    flash('Kunde hat keine E-Mail-Adresse hinterlegt.', 'error')
                    return redirect(url_for('view_invoice', invoice_id=invoice_id))
                
                # E-Mail-Betreff und Text
                subject = f"{reminder_level}. Mahnung - Rechnung {invoice.invoice_number}"
                
                if reminder_level == 1:
                    body = f"""Sehr geehrte Damen und Herren,

leider haben wir bisher keinen Zahlungseingang für die Rechnung {invoice.invoice_number} feststellen können.

Bitte begleichen Sie den ausstehenden Betrag von {float(invoice.total + reminder.reminder_fee):.2f} € 
(inkl. {float(reminder.reminder_fee):.2f} € Mahngebühr) innerhalb der nächsten 7 Tage.

Die Mahnung finden Sie im Anhang.

Mit freundlichen Grüßen
{app.config.get('COMPANY_NAME', '')}"""
                else:
                    body = f"""Sehr geehrte Damen und Herren,

trotz unserer bisherigen Mahnungen haben wir noch keinen Zahlungseingang für die Rechnung {invoice.invoice_number} feststellen können.

Wir fordern Sie auf, den ausstehenden Betrag von {float(invoice.total + reminder.reminder_fee):.2f} € 
(inkl. {float(reminder.reminder_fee):.2f} € Mahngebühr) umgehend zu begleichen.

Die Mahnung finden Sie im Anhang.

Mit freundlichen Grüßen
{app.config.get('COMPANY_NAME', '')}"""
                
                # E-Mail senden
                success = send_email(
                    to=invoice.customer.email,
                    subject=subject,
                    body=body,
                    attachment_path=pdf_path
                )
                
                if success:
                    reminder.sent_via = 'email'
                    reminder.sent_date = datetime.utcnow()
                    db.session.commit()
                    flash(f'Mahnung erfolgreich per E-Mail an {invoice.customer.email} versendet!', 'success')
                else:
                    flash('Fehler beim Versenden der E-Mail.', 'error')
                
                return redirect(url_for('view_invoice', invoice_id=invoice_id))
        
        # GET: Formular anzeigen
        existing_reminders = Reminder.query.filter_by(invoice_id=invoice_id).order_by(Reminder.reminder_date.desc()).all()
        next_level = 1 if not existing_reminders else existing_reminders[0].reminder_level + 1
        
        return render_template('invoices/create_reminder.html', 
                             invoice=invoice, 
                             existing_reminders=existing_reminders,
                             next_level=next_level)
    
    @app.route('/customers')
    @login_required
    def list_customers():
        """Liste aller Kunden mit Suchfunktion"""
        search_query = request.args.get('search', '').strip()
        
        if search_query:
            # Suche nach Firma, Vorname, Nachname oder E-Mail
            search_pattern = f"%{search_query}%"
            customers = Customer.query.filter(
                db.or_(
                    Customer.company_name.ilike(search_pattern),
                    Customer.first_name.ilike(search_pattern),
                    Customer.last_name.ilike(search_pattern),
                    Customer.email.ilike(search_pattern)
                )
            ).order_by(Customer.company_name, Customer.last_name).all()
        else:
            customers = Customer.query.order_by(Customer.company_name, Customer.last_name).all()
        
        return render_template('customers/list.html', customers=customers, search_query=search_query)
    
    @app.route('/customers/<int:customer_id>')
    @login_required
    def view_customer(customer_id):
        """Kundendetails anzeigen"""
        customer = Customer.query.get_or_404(customer_id)
        return render_template('customers/view.html', customer=customer)
    
    @app.route('/customers/<int:customer_id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_customer(customer_id):
        """Kunde bearbeiten"""
        customer = Customer.query.get_or_404(customer_id)
        
        if request.method == 'POST':
            try:
                customer.company_name = request.form.get('company_name')
                customer.first_name = request.form.get('first_name')
                customer.last_name = request.form.get('last_name')
                customer.email = request.form.get('email')
                customer.phone = request.form.get('phone')
                customer.address = request.form.get('address')
                customer.tax_id = request.form.get('tax_id')
                customer.reseller = request.form.get('reseller') == '1'
                
                db.session.commit()
                flash('Kundendaten erfolgreich aktualisiert!', 'success')
                return redirect(url_for('view_customer', customer_id=customer.id))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Fehler beim Aktualisieren: {str(e)}', 'error')
        
        return render_template('customers/edit.html', customer=customer)
    
    @app.route('/customers/<int:customer_id>/anonymize', methods=['POST'])
    @login_required
    def anonymize_customer(customer_id):
        """
        DSGVO-konforme Anonymisierung von Kundendaten.
        
        Anonymisiert nur die Kundenstammdaten. Bestehende Rechnungen bleiben
        aus steuerrechtlichen Gründen (§147 AO, GoBD) unverändert und zeigen
        weiterhin die Originaldaten. Dies ist DSGVO-konform gemäß Art. 17 Abs. 3 b.
        """
        customer = Customer.query.get_or_404(customer_id)
        
        # Prüfung: Bereits anonymisiert?
        if customer.is_anonymized:
            flash('Dieser Kunde wurde bereits anonymisiert.', 'warning')
            return redirect(url_for('list_customers'))
        
        # Anzahl verknüpfter Rechnungen ermitteln
        invoice_count = Invoice.query.filter_by(customer_id=customer_id).count()
        
        # Original-Daten für Audit-Log
        original_email = customer.email
        original_name = customer.display_name
        
        try:
            # DSGVO-Anonymisierung durchführen
            customer.anonymize_gdpr()
            db.session.commit()
            
            # Audit-Protokollierung
            app.logger.info(
                f"DSGVO-Anonymisierung durchgeführt | "
                f"Kunde ID: {customer_id} | "
                f"Original: {original_name} ({original_email}) | "
                f"Benutzer: {current_user.username} | "
                f"Verknüpfte Rechnungen: {invoice_count} (bleiben unverändert gemäß §147 AO)"
            )
            
            if invoice_count > 0:
                flash(
                    f'Kunde erfolgreich anonymisiert. '
                    f'{invoice_count} bestehende Rechnung(en) bleiben aus steuerrechtlichen Gründen '
                    f'(§147 AO - 10 Jahre Aufbewahrungspflicht) unverändert und zeigen weiterhin die Originaldaten. '
                    f'Dies ist DSGVO-konform gemäß Art. 17 Abs. 3 Buchstabe b.',
                    'success'
                )
            else:
                flash('Kunde erfolgreich anonymisiert.', 'success')
            
            return redirect(url_for('list_customers'))
            
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Fehler bei DSGVO-Anonymisierung Kunde #{customer_id}: {str(e)}")
            flash(f'Fehler bei der Anonymisierung: {str(e)}', 'error')
            return redirect(url_for('view_customer', customer_id=customer_id))
    
    # ============================================================================
    # Stock Adjustments - Bestandsanpassungen (Eigenentnahme, Inventur, etc.)
    # ============================================================================
    
    @app.route('/stock-adjustments')
    @login_required
    def list_stock_adjustments():
        """Liste aller Bestandsanpassungen"""
        adjustments = StockAdjustment.query.order_by(StockAdjustment.adjusted_at.desc()).limit(100).all()
        return render_template('stock_adjustments/list.html', adjustments=adjustments)
    
    @app.route('/stock-adjustments/export-pdf')
    @login_required
    def export_stock_adjustments_pdf():
        """Exportiere alle Bestandsanpassungen als PDF (GoBD-konform)"""
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from io import BytesIO
        
        # Filter-Parameter
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        adjustment_type = request.args.get('adjustment_type')
        
        query = StockAdjustment.query
        
        if start_date:
            from datetime import datetime
            query = query.filter(StockAdjustment.adjusted_at >= datetime.strptime(start_date, '%Y-%m-%d'))
        if end_date:
            from datetime import datetime
            query = query.filter(StockAdjustment.adjusted_at <= datetime.strptime(end_date, '%Y-%m-%d'))
        if adjustment_type:
            query = query.filter(StockAdjustment.adjustment_type == adjustment_type)
        
        adjustments = query.order_by(StockAdjustment.adjusted_at.desc()).all()
        
        # PDF erstellen
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
        elements = []
        
        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=30
        )
        
        # Titel
        title = Paragraph("Bestandsanpassungen - Übersicht (GoBD-konform)", title_style)
        elements.append(title)
        
        # Zeitraum
        if start_date or end_date:
            period = f"Zeitraum: {start_date or 'Anfang'} bis {end_date or 'Heute'}"
            elements.append(Paragraph(period, styles['Normal']))
            elements.append(Spacer(1, 0.5*cm))
        
        # Tabelle
        data = [['Datum', 'Produkt', 'Typ', 'Menge', 'Alt → Neu', 'Grund', 'Benutzer', 'Beleg-Nr.']]
        
        type_labels = {
            'eigenentnahme': 'Eigenentnahme',
            'geschenk': 'Geschenk',
            'verderb': 'Verderb',
            'bruch': 'Bruch',
            'inventur_plus': 'Inventur +',
            'inventur_minus': 'Inventur -',
            'korrektur': 'Korrektur',
            'sonstiges': 'Sonstiges'
        }
        
        for adj in adjustments:
            data.append([
                adj.adjusted_at.strftime('%d.%m.%Y %H:%M'),
                adj.product.name if adj.product else 'N/A',
                type_labels.get(adj.adjustment_type, adj.adjustment_type),
                f"{adj.quantity:+d}",
                f"{adj.old_stock} → {adj.new_stock}",
                adj.reason[:30] + '...' if len(adj.reason) > 30 else adj.reason,
                adj.adjusted_by_user.username if adj.adjusted_by_user else 'N/A',
                adj.document_number or '-'
            ])
        
        table = Table(data, colWidths=[3*cm, 4*cm, 2.5*cm, 1.5*cm, 2*cm, 5*cm, 2*cm, 3*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        
        elements.append(table)
        
        # Fußnote
        elements.append(Spacer(1, 1*cm))
        footer_text = f"Erstellt am: {datetime.now().strftime('%d.%m.%Y %H:%M')} | Anzahl Einträge: {len(adjustments)}"
        elements.append(Paragraph(footer_text, styles['Normal']))
        
        doc.build(elements)
        buffer.seek(0)
        
        filename = f"Bestandsanpassungen_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')
    
    @app.route('/stock-adjustments/create', methods=['GET', 'POST'])
    @login_required
    def create_stock_adjustment():
        """Neue Bestandsanpassung erstellen"""
        if request.method == 'POST':
            try:
                product_id = request.form.get('product_id')
                quantity = int(request.form.get('quantity'))
                adjustment_type = request.form.get('adjustment_type')
                reason = request.form.get('reason')
                
                if not all([product_id, quantity, adjustment_type, reason]):
                    flash('Alle Felder müssen ausgefüllt werden.', 'error')
                    return redirect(url_for('create_stock_adjustment'))
                
                product = Product.query.get(int(product_id))
                if not product:
                    flash('Produkt nicht gefunden.', 'error')
                    return redirect(url_for('create_stock_adjustment'))
                
                old_stock = product.number
                new_stock = old_stock + quantity
                
                if new_stock < 0:
                    flash(f'Fehler: Bestand würde negativ werden! Aktuell: {old_stock}, Änderung: {quantity}', 'error')
                    return redirect(url_for('create_stock_adjustment'))
                
                # Generiere Belegnummer für Eigenentnahmen
                document_number = None
                if adjustment_type in ['eigenentnahme', 'geschenk']:
                    today = datetime.now().date()
                    prefix = f"ENT-{today.strftime('%Y%m%d')}"
                    last_doc = StockAdjustment.query.filter(
                        StockAdjustment.document_number.like(f"{prefix}%")
                    ).order_by(StockAdjustment.document_number.desc()).first()
                    
                    if last_doc:
                        last_num = int(last_doc.document_number.split('-')[-1])
                        next_num = last_num + 1
                    else:
                        next_num = 1
                    
                    document_number = f"{prefix}-{next_num:04d}"
                
                # Erstelle Anpassung
                adjustment = StockAdjustment(
                    product_id=product.id,
                    quantity=quantity,
                    old_stock=old_stock,
                    new_stock=new_stock,
                    adjustment_type=adjustment_type,
                    reason=reason,
                    adjusted_by=current_user.id,
                    document_number=document_number
                )
                
                # Bestand aktualisieren
                product.number = new_stock
                
                db.session.add(adjustment)
                db.session.commit()
                
                flash(f'✅ Bestandsanpassung erfolgreich erstellt! Neuer Bestand: {new_stock}', 'success')
                return redirect(url_for('list_stock_adjustments'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Fehler beim Erstellen: {str(e)}', 'error')
        
        products = Product.query.filter_by(active=True).order_by(Product.name).all()
        return render_template('stock_adjustments/create.html', products=products)
    
    @app.route('/products')
    @login_required
    def list_products():
        """Liste aller Produkte"""
        show_inactive = request.args.get('show_inactive', 'false') == 'true'
        
        if show_inactive:
            products = Product.query.order_by(Product.name).all()
        else:
            products = Product.query.filter_by(active=True).order_by(Product.name).all()
        
        return render_template('products/list.html', products=products, show_inactive=show_inactive)
    
    @app.route('/products/new', methods=['GET', 'POST'])
    @login_required
    def create_product():
        """Neues Produkt erstellen"""
        if request.method == 'POST':
            try:
                reseller_price = request.form.get('reseller_price')
                tax_rate = request.form.get('tax_rate')
                product = Product(
                    name=request.form.get('name'),
                    number=int(request.form.get('number', 0)),
                    quantity=request.form.get('quantity'),
                    price=float(request.form.get('price')),
                    reseller_price=float(reseller_price) if reseller_price else None,
                    tax_rate=float(tax_rate) if tax_rate else 7.80,
                    lot_number=request.form.get('lot_number'),
                    active=request.form.get('active') == 'on'
                )
                
                db.session.add(product)
                db.session.commit()
                
                flash(f'Produkt "{product.name}" erfolgreich erstellt!', 'success')
                return redirect(url_for('list_products'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Fehler beim Erstellen: {str(e)}', 'error')
        
        return render_template('products/create.html')
    
    @app.route('/products/<int:product_id>')
    @login_required
    def view_product(product_id):
        """Produktdetails anzeigen"""
        product = Product.query.get_or_404(product_id)
        return render_template('products/view.html', product=product)
    
    @app.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_product(product_id):
        """Produkt bearbeiten"""
        product = Product.query.get_or_404(product_id)
        
        if request.method == 'POST':
            try:
                reseller_price = request.form.get('reseller_price')
                tax_rate = request.form.get('tax_rate')
                product.name = request.form.get('name')
                product.number = int(request.form.get('number', 0))
                product.quantity = request.form.get('quantity')
                product.price = float(request.form.get('price'))
                product.reseller_price = float(reseller_price) if reseller_price else None
                product.tax_rate = float(tax_rate) if tax_rate else 7.80
                product.lot_number = request.form.get('lot_number')
                product.active = request.form.get('active') == 'on'
                
                db.session.commit()
                flash('Produkt erfolgreich aktualisiert!', 'success')
                return redirect(url_for('view_product', product_id=product.id))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Fehler beim Aktualisieren: {str(e)}', 'error')
        
        return render_template('products/edit.html', product=product)
    
    @app.route('/products/<int:product_id>/delete', methods=['POST'])
    @login_required
    def delete_product(product_id):
        """Produkt löschen - DEAKTIVIERT aus Sicherheitsgründen"""
        flash('Das Löschen von Produkten ist aus Sicherheitsgründen deaktiviert. Bitte deaktivieren Sie das Produkt stattdessen.', 'error')
        return redirect(url_for('view_product', product_id=product_id))
    
    # ============================================================================
    # POS (Point of Sale) - Kassenseite für Direktverkauf
    # ============================================================================
    
    @app.route('/pos')
    @login_required
    @role_required('cashier', 'admin')
    def pos():
        """Kassenseite für schnellen Direktverkauf"""
        stock_source = session.get('stock_source', 'main')
        
        if stock_source == 'market' and current_user.reseller_customer_id:
            # Marktbestand: Lade ConsignmentStock
            consignment_items = ConsignmentStock.query.filter_by(
                customer_id=current_user.reseller_customer_id
            ).filter(ConsignmentStock.quantity > 0).all()
            
            # Konvertiere zu Product-ähnlicher Struktur für Template
            products = []
            for item in consignment_items:
                product = item.product
                # Erstelle Product-Kopie mit Marktbestand und Reseller-Preis
                product_data = {
                    'id': product.id,
                    'name': product.name,
                    'price': float(item.unit_price),  # Reseller-Preis!
                    'number': item.quantity,  # Marktbestand
                    'tax_rate': product.tax_rate,
                    'is_market_stock': True,
                    'consignment_stock_id': item.id
                }
                products.append(type('obj', (object,), product_data))
        else:
            # Hauptbestand: Lade normale Produkte
            products = Product.query.filter_by(active=True).filter(Product.number > 0).order_by(Product.name).all()
            for p in products:
                p.is_market_stock = False
        
        return render_template('pos.html', products=products, stock_source=stock_source)
    
    @app.route('/pos/complete-sale', methods=['POST'])
    @login_required
    @role_required('cashier', 'admin')
    def complete_pos_sale():
        """Verkauf abschließen - Bestand reduzieren und GoBD-konform dokumentieren"""
        try:
            data = request.get_json()
            items = data.get('items', {})
            stock_source = session.get('stock_source', 'main')
            
            if not items:
                return jsonify({'success': False, 'message': 'Warenkorb ist leer'}), 400
            
            # Prüfe ob Rechnung erstellt werden soll (abhängig vom reseller_type)
            create_invoice = True
            if current_user.reseller_type == 'type3_non_ust_pwa':
                create_invoice = False
            
            # Berechne Summen und reduziere Bestand
            subtotal = Decimal('0.00')
            line_items_data = []
            
            for product_id, quantity in items.items():
                product = Product.query.get(int(product_id))
                if not product:
                    return jsonify({'success': False, 'message': f'Produkt {product_id} nicht gefunden'}), 404
                
                if stock_source == 'market' and current_user.reseller_customer_id:
                    # Marktbestand: ConsignmentStock reduzieren
                    consignment = ConsignmentStock.query.filter_by(
                        customer_id=current_user.reseller_customer_id,
                        product_id=product.id
                    ).first()
                    
                    if not consignment or consignment.quantity < quantity:
                        available = consignment.quantity if consignment else 0
                        return jsonify({
                            'success': False,
                            'message': f'Nicht genug Marktbestand für {product.name}. Verfügbar: {available}, Benötigt: {quantity}'
                        }), 400
                    
                    # Bestand umbuchen
                    consignment.quantity -= quantity
                    consignment.quantity_sold += quantity
                    
                    line_total = Decimal(str(consignment.unit_price)) * Decimal(str(quantity))
                    unit_price = consignment.unit_price
                else:
                    # Hauptbestand: Product.number reduzieren
                    if product.number < quantity:
                        return jsonify({
                            'success': False,
                            'message': f'Nicht genug Bestand für {product.name}. Verfügbar: {product.number}, Benötigt: {quantity}'
                        }), 400
                    
                    product.number -= quantity
                    line_total = Decimal(str(product.price)) * Decimal(str(quantity))
                    unit_price = product.price
                
                subtotal += line_total
                
                if create_invoice:
                    line_items_data.append({
                        'product': product,
                        'quantity': quantity,
                        'unit_price': unit_price,
                        'tax_rate': product.tax_rate,
                        'total': line_total
                    })
            
            # Falls keine Rechnung erstellt werden soll (Typ 3)
            if not create_invoice:
                db.session.commit()
                return jsonify({
                    'success': True,
                    'message': 'Verkauf erfolgreich (nur Bestandsumbuchung, keine Rechnung)',
                    'receipt_number': None,
                    'total': float(subtotal)
                })
            
            # Ab hier: Rechnung erstellen (Typ 4 / normale Kasse)
            today = datetime.now().date()
            prefix = f"BAR-{today.strftime('%Y%m%d')}"
            
            last_receipt = Invoice.query.filter(
                Invoice.invoice_number.like(f"{prefix}%")
            ).order_by(Invoice.invoice_number.desc()).first()
            
            if last_receipt:
                last_num = int(last_receipt.invoice_number.split('-')[-1])
                next_num = last_num + 1
            else:
                next_num = 1
            
            receipt_number = f"{prefix}-{next_num:04d}"
            
            # Erstelle "Kunde" für Barverkauf (falls nicht vorhanden)
            bar_customer = Customer.query.filter_by(email='barverkauf@system.local').first()
            if not bar_customer:
                bar_customer = Customer(
                    company_name='Barverkauf',
                    first_name='Bar',
                    last_name='Verkauf',
                    email='barverkauf@system.local',
                    address='Direktverkauf ohne Rechnungsadresse'
                )
                db.session.add(bar_customer)
                db.session.flush()
            
            # Berechne Steuer (durchschnittlich 7.80% für Honig)
            tax_rate = Decimal('7.80')
            tax_amount = subtotal * (tax_rate / Decimal('100'))
            total = subtotal  # Preis ist bereits Bruttopreis
            
            # Erstelle Rechnung (GoBD-konform dokumentiert)
            invoice = Invoice(
                invoice_number=receipt_number,
                customer_id=bar_customer.id,
                invoice_date=today,
                due_date=today,
                status='paid',  # Barverkauf ist sofort bezahlt
                customer_type='endkunde',
                tax_model='landwirtschaft',  # §24 UStG für Honig
                tax_rate=tax_rate,
                subtotal=subtotal,
                tax_amount=tax_amount,
                total=total,
                payment_method='Barzahlung',
                notes=f'Barverkauf / Direktverkauf\nKasse: POS-System'
            )
            
            # LineItems ZUERST erstellen (ohne invoice_id, wird später gesetzt)
            line_items_list = []
            for idx, item_data in enumerate(line_items_data):
                line_item = LineItem(
                    product_id=item_data['product'].id,
                    description=item_data['product'].name,
                    quantity=Decimal(str(item_data['quantity'])),
                    unit_price=item_data['unit_price'],
                    tax_rate=item_data['tax_rate'],
                    total=item_data['total'],
                    position=idx
                )
                line_items_list.append(line_item)
            
            # LineItems zur Invoice hinzufügen (noch nicht in DB)
            invoice.line_items = line_items_list
            
            # JETZT Hash generieren (mit LineItems im Objekt, aber noch nicht in DB)
            invoice.generate_hash()
            
            # Jetzt zur Session hinzufügen (mit korrektem Hash)
            db.session.add(invoice)
            db.session.flush()  # ID generieren
            
            # Status-Log erstellen (GoBD Audit Trail)
            status_log = InvoiceStatusLog(
                invoice_id=invoice.id,
                old_status=None,
                new_status='paid',
                changed_by=current_user.username,
                reason='Barverkauf - automatisch als bezahlt markiert'
            )
            db.session.add(status_log)
            
            db.session.commit()
            
            return jsonify({
                'success': True, 
                'message': 'Verkauf erfolgreich abgeschlossen',
                'receipt_number': receipt_number,
                'total': float(total)
            })
            
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': str(e)}), 500
    
    # ============================================================================
    # Berichte / Statistiken
    # ============================================================================
    
    @app.route('/reports/annual-revenue')
    @login_required
    def annual_revenue_report():
        """Jahresübersicht Einnahmen nach Kundentyp"""
        from sqlalchemy import extract, func
        from decimal import Decimal
        
        # Jahr aus Query-Parameter (Standard: aktuelles Jahr)
        year = request.args.get('year', datetime.now().year, type=int)
        
        # Alle bezahlten Rechnungen des Jahres
        invoices = Invoice.query.filter(
            extract('year', Invoice.invoice_date) == year,
            Invoice.status == 'paid'  # Nur bezahlte Rechnungen zählen steuerlich
        ).all()
        
        # Initialisiere Statistiken
        stats = {
            'year': year,
            'total_revenue': Decimal('0.00'),
            'total_invoices': 0,
            'by_type': {
                'endkunde': {'revenue': Decimal('0.00'), 'count': 0, 'label': 'Endkunden (direkt)'},
                'type1_ust_extern': {'revenue': Decimal('0.00'), 'count': 0, 'label': 'Typ 1: USt.-pflichtig extern'},
                'type2_non_ust_extern': {'revenue': Decimal('0.00'), 'count': 0, 'label': 'Typ 2: Nicht USt.-pflichtig extern'},
                'type3_non_ust_pwa': {'revenue': Decimal('0.00'), 'count': 0, 'label': 'Typ 3: Nicht USt.-pflichtig PWA'},
                'type4_owner_market': {'revenue': Decimal('0.00'), 'count': 0, 'label': 'Typ 4: Owner Markt (BAR)'},
                'bar': {'revenue': Decimal('0.00'), 'count': 0, 'label': 'BAR-Verkäufe (Kasse)'},
                'other': {'revenue': Decimal('0.00'), 'count': 0, 'label': 'Sonstige'}
            },
            'by_month': {}
        }
        
        # Initialisiere Monatsstatistik
        month_names = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 
                       'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember']
        for month in range(1, 13):
            stats['by_month'][month] = {
                'revenue': Decimal('0.00'),
                'count': 0,
                'label': month_names[month - 1]
            }
        
        # Verarbeite Rechnungen
        for invoice in invoices:
            total = invoice.total or Decimal('0.00')
            stats['total_revenue'] += total
            stats['total_invoices'] += 1
            
            # Nach Monat
            month = invoice.invoice_date.month
            stats['by_month'][month]['revenue'] += total
            stats['by_month'][month]['count'] += 1
            
            # Nach Kundentyp bestimmen
            customer_type = 'other'
            
            # BAR-Rechnungen
            if invoice.invoice_number and invoice.invoice_number.startswith('BAR-'):
                customer_type = 'bar'
            # Reseller-Typ ermitteln (wenn Customer mit reseller_user verknüpft)
            elif invoice.customer and invoice.customer.reseller_user:
                for user in invoice.customer.reseller_user:
                    if user.reseller_type != 'none':
                        customer_type = user.reseller_type
                        break
            # Normale Endkunden
            elif invoice.customer_type == 'endkunde' or (invoice.customer and not invoice.customer.reseller_user):
                customer_type = 'endkunde'
            
            if customer_type in stats['by_type']:
                stats['by_type'][customer_type]['revenue'] += total
                stats['by_type'][customer_type]['count'] += 1
        
        # Maximalen Monatsumsatz für Diagramme berechnen
        stats['max_month_revenue'] = max(
            [stats['by_month'][m]['revenue'] for m in range(1, 13)],
            default=Decimal('0.00')
        )
        
        # Verfügbare Jahre ermitteln
        available_years_query = db.session.query(
            extract('year', Invoice.invoice_date).label('year')
        ).distinct().order_by(extract('year', Invoice.invoice_date).desc()).all()
        
        available_years = [int(y[0]) for y in available_years_query if y[0]]
        
        return render_template('reports/annual_revenue.html', stats=stats, available_years=available_years)
    
    @app.route('/reports/annual-revenue/pdf')
    @login_required
    def annual_revenue_report_pdf():
        """PDF-Export der Jahresübersicht"""
        from sqlalchemy import extract, func
        from decimal import Decimal
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from io import BytesIO
        
        # Jahr aus Query-Parameter
        year = request.args.get('year', datetime.now().year, type=int)
        
        # Alle bezahlten Rechnungen des Jahres
        invoices = Invoice.query.filter(
            extract('year', Invoice.invoice_date) == year,
            Invoice.status == 'paid'
        ).all()
        
        # Statistiken berechnen (gleiche Logik wie Webansicht)
        stats = {
            'year': year,
            'total_revenue': Decimal('0.00'),
            'total_invoices': 0,
            'by_type': {
                'endkunde': {'revenue': Decimal('0.00'), 'count': 0, 'label': 'Endkunden (direkt)'},
                'type1_ust_extern': {'revenue': Decimal('0.00'), 'count': 0, 'label': 'Typ 1: USt.-pflichtig extern'},
                'type2_non_ust_extern': {'revenue': Decimal('0.00'), 'count': 0, 'label': 'Typ 2: Nicht USt.-pflichtig extern'},
                'type3_non_ust_pwa': {'revenue': Decimal('0.00'), 'count': 0, 'label': 'Typ 3: Nicht USt.-pflichtig PWA'},
                'type4_owner_market': {'revenue': Decimal('0.00'), 'count': 0, 'label': 'Typ 4: Owner Markt (BAR)'},
                'bar': {'revenue': Decimal('0.00'), 'count': 0, 'label': 'BAR-Verkäufe (Kasse)'},
                'other': {'revenue': Decimal('0.00'), 'count': 0, 'label': 'Sonstige'}
            },
            'by_month': {}
        }
        
        month_names = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 
                       'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember']
        for month in range(1, 13):
            stats['by_month'][month] = {
                'revenue': Decimal('0.00'),
                'count': 0,
                'label': month_names[month - 1]
            }
        
        # Verarbeite Rechnungen
        for invoice in invoices:
            total = invoice.total or Decimal('0.00')
            stats['total_revenue'] += total
            stats['total_invoices'] += 1
            
            month = invoice.invoice_date.month
            stats['by_month'][month]['revenue'] += total
            stats['by_month'][month]['count'] += 1
            
            customer_type = 'other'
            if invoice.invoice_number and invoice.invoice_number.startswith('BAR-'):
                customer_type = 'bar'
            elif invoice.customer and invoice.customer.reseller_user:
                for user in invoice.customer.reseller_user:
                    if user.reseller_type != 'none':
                        customer_type = user.reseller_type
                        break
            elif invoice.customer_type == 'endkunde' or (invoice.customer and not invoice.customer.reseller_user):
                customer_type = 'endkunde'
            
            if customer_type in stats['by_type']:
                stats['by_type'][customer_type]['revenue'] += total
                stats['by_type'][customer_type]['count'] += 1
        
        # PDF erstellen
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                               rightMargin=2*cm, leftMargin=2*cm,
                               topMargin=2*cm, bottomMargin=2*cm)
        
        elements = []
        styles = getSampleStyleSheet()
        
        # Titel
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=30,
            alignment=1  # Center
        )
        elements.append(Paragraph(f'Jahresübersicht Einnahmen {year}', title_style))
        elements.append(Spacer(1, 0.5*cm))
        
        # Zusammenfassung
        summary_data = [
            ['Gesamtumsatz:', f'{float(stats["total_revenue"]):.2f} €'],
            ['Anzahl Rechnungen:', str(stats['total_invoices'])],
            ['Durchschnitt pro Rechnung:', 
             f'{float(stats["total_revenue"] / stats["total_invoices"]):.2f} €' if stats['total_invoices'] > 0 else '0,00 €']
        ]
        
        summary_table = Table(summary_data, colWidths=[8*cm, 8*cm])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e8f4f8')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#2c3e50')),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 1*cm))
        
        # Aufschlüsselung nach Kundentyp
        elements.append(Paragraph('Aufschlüsselung nach Kundentyp', styles['Heading2']))
        elements.append(Spacer(1, 0.3*cm))
        
        type_data = [['Kundentyp', 'Umsatz', 'Anzahl', 'Anteil']]
        for type_key, type_info in stats['by_type'].items():
            if type_info['count'] > 0:
                percentage = (type_info['revenue'] / stats['total_revenue'] * 100) if stats['total_revenue'] > 0 else 0
                type_data.append([
                    type_info['label'],
                    f'{float(type_info["revenue"]):.2f} €',
                    str(type_info['count']),
                    f'{float(percentage):.1f}%'
                ])
        
        type_table = Table(type_data, colWidths=[10*cm, 4*cm, 3*cm, 3*cm])
        type_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(type_table)
        elements.append(Spacer(1, 1*cm))
        
        # Monatliche Aufschlüsselung
        elements.append(Paragraph('Monatliche Aufschlüsselung', styles['Heading2']))
        elements.append(Spacer(1, 0.3*cm))
        
        month_data = [['Monat', 'Umsatz', 'Anzahl']]
        for month in range(1, 13):
            month_info = stats['by_month'][month]
            month_data.append([
                month_info['label'],
                f'{float(month_info["revenue"]):.2f} €',
                str(month_info['count'])
            ])
        
        month_table = Table(month_data, colWidths=[8*cm, 6*cm, 6*cm])
        month_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27ae60')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(month_table)
        elements.append(Spacer(1, 1*cm))
        
        # Fußnote
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.grey
        )
        elements.append(Paragraph(
            f'Erstellt am: {datetime.now().strftime("%d.%m.%Y %H:%M")} | '
            f'Berücksichtigt: Alle bezahlten Rechnungen des Jahres {year}',
            footer_style
        ))
        
        # PDF generieren
        doc.build(elements)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f'Jahresuebersicht_{year}.pdf',
            mimetype='application/pdf'
        )
    
    # ============================================================================
    # Einstellungen
    # ============================================================================
    
    @app.route('/settings')
    @login_required
    @role_required('admin')
    def settings():
        """Einstellungen - Firmendaten anzeigen"""
        company_data = {
            'name': app.config.get('COMPANY_NAME'),
            'holder': app.config.get('COMPANY_HOLDER'),
            'street': app.config.get('COMPANY_STREET'),
            'zip': app.config.get('COMPANY_ZIP'),
            'city': app.config.get('COMPANY_CITY'),
            'country': app.config.get('COMPANY_COUNTRY'),
            'email': app.config.get('COMPANY_EMAIL'),
            'phone': app.config.get('COMPANY_PHONE'),
            'tax_id': app.config.get('COMPANY_TAX_ID'),
            'website': app.config.get('COMPANY_WEBSITE'),
        }
        bank_data = {
            'name': app.config.get('BANK_NAME'),
            'iban': app.config.get('BANK_IBAN'),
            'bic': app.config.get('BANK_BIC'),
        }
        return render_template('settings.html', company=company_data, bank=bank_data, config=app.config)
    
    @app.route('/settings/users')
    @login_required
    @role_required('admin')
    def list_users():
        """User-Verwaltung - Liste aller Benutzer"""
        users = User.query.order_by(User.created_at.desc()).all()
        return render_template('users/list.html', users=users)
    
    @app.route('/settings/users/new', methods=['GET', 'POST'])
    @login_required
    @role_required('admin')
    def create_user():
        """Neuen Benutzer erstellen"""
        if request.method == 'POST':
            try:
                username = request.form.get('username')
                email = request.form.get('email')
                password = request.form.get('password')
                role = request.form.get('role', 'cashier')
                
                # Validierung
                if User.query.filter_by(username=username).first():
                    flash('Benutzername bereits vergeben.', 'danger')
                    return render_template('users/create.html')
                
                if User.query.filter_by(email=email).first():
                    flash('E-Mail-Adresse bereits vergeben.', 'danger')
                    return render_template('users/create.html')
                
                # Benutzer erstellen
                user = User(
                    username=username,
                    email=email,
                    role=role,
                    is_active=True
                )
                user.set_password(password)
                
                # Optional: Reseller-Verknüpfung
                if role == 'reseller':
                    customer_id = request.form.get('reseller_customer_id')
                    if customer_id:
                        user.reseller_customer_id = int(customer_id)
                
                db.session.add(user)
                db.session.commit()
                
                flash(f'Benutzer "{username}" wurde erfolgreich erstellt.', 'success')
                return redirect(url_for('list_users'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Fehler beim Erstellen des Benutzers: {str(e)}', 'danger')
        
        # GET: Formular anzeigen
        customers = Customer.query.order_by(Customer.company_name).all()
        return render_template('users/create.html', customers=customers)
    
    @app.route('/settings/users/<int:user_id>/edit', methods=['GET', 'POST'])
    @login_required
    @role_required('admin')
    def edit_user(user_id):
        """Benutzer bearbeiten"""
        user = User.query.get_or_404(user_id)
        
        if request.method == 'POST':
            try:
                # E-Mail aktualisieren
                new_email = request.form.get('email')
                if new_email != user.email:
                    if User.query.filter_by(email=new_email).first():
                        flash('E-Mail-Adresse bereits vergeben.', 'danger')
                        return render_template('users/edit.html', user=user, customers=Customer.query.all())
                    user.email = new_email
                
                # Rolle aktualisieren
                user.role = request.form.get('role', user.role)
                
                # Reseller-Verknüpfung
                if user.role == 'reseller':
                    customer_id = request.form.get('reseller_customer_id')
                    user.reseller_customer_id = int(customer_id) if customer_id else None
                else:
                    user.reseller_customer_id = None
                
                # Aktiv-Status
                user.is_active = request.form.get('is_active') == 'on'
                
                # 2FA-Pflicht
                user.totp_required = request.form.get('totp_required') == 'on'
                
                # Passwort ändern (optional)
                new_password = request.form.get('new_password')
                if new_password:
                    user.set_password(new_password)
                
                db.session.commit()
                flash(f'Benutzer "{user.username}" wurde aktualisiert.', 'success')
                return redirect(url_for('list_users'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Fehler beim Aktualisieren des Benutzers: {str(e)}', 'danger')
        
        customers = Customer.query.order_by(Customer.company_name).all()
        return render_template('users/edit.html', user=user, customers=customers)
    
    @app.route('/settings/users/<int:user_id>/toggle-active', methods=['POST'])
    @login_required
    @role_required('admin')
    def toggle_user_active(user_id):
        """Benutzer aktivieren/deaktivieren"""
        user = User.query.get_or_404(user_id)
        
        if user.id == current_user.id:
            flash('Sie können sich nicht selbst deaktivieren.', 'danger')
            return redirect(url_for('list_users'))
        
        user.is_active = not user.is_active
        db.session.commit()
        
        status = 'aktiviert' if user.is_active else 'deaktiviert'
        flash(f'Benutzer "{user.username}" wurde {status}.', 'success')
        return redirect(url_for('list_users'))
    
    @app.route('/settings/users/<int:user_id>/reset-2fa', methods=['POST'])
    @login_required
    @role_required('admin')
    def reset_user_2fa(user_id):
        """2FA für Benutzer zurücksetzen"""
        user = User.query.get_or_404(user_id)
        
        user.totp_enabled = False
        user.totp_secret = None
        user.backup_codes = None
        db.session.commit()
        
        flash(f'2FA für "{user.username}" wurde zurückgesetzt.', 'warning')
        return redirect(url_for('list_users'))
    
    @app.route('/settings/users/<int:user_id>/toggle-2fa-required', methods=['POST'])
    @login_required
    @role_required('admin')
    def toggle_user_2fa_required(user_id):
        """2FA-Pflicht für Benutzer umschalten"""
        user = User.query.get_or_404(user_id)
        
        user.totp_required = not user.totp_required
        db.session.commit()
        
        if user.totp_required:
            flash(f'2FA ist jetzt Pflicht für "{user.username}". Der Benutzer muss 2FA beim nächsten Login einrichten.', 'success')
        else:
            flash(f'2FA-Pflicht für "{user.username}" wurde aufgehoben.', 'info')
        
        return redirect(url_for('list_users'))
    
    @app.route('/settings/users/<int:user_id>/delete', methods=['POST'])
    @login_required
    @role_required('admin')
    def delete_user(user_id):
        """Benutzer löschen"""
        user = User.query.get_or_404(user_id)
        
        if user.id == current_user.id:
            flash('Sie können sich nicht selbst löschen.', 'danger')
            return redirect(url_for('list_users'))
        
        username = user.username
        db.session.delete(user)
        db.session.commit()
        
        flash(f'Benutzer "{username}" wurde gelöscht.', 'success')
        return redirect(url_for('list_users'))
    
    @app.route('/payments/review')
    @login_required
    def payment_review():
        """Manuelle Prüfung von Zahlungseingängen"""
        # Nur ungelöste Probleme anzeigen
        pending_checks = PaymentCheck.query.filter_by(resolved=False).filter(
            PaymentCheck.status.in_(['mismatch', 'not_found', 'duplicate'])
        ).order_by(PaymentCheck.check_date.desc()).all()
        
        return render_template('payments/review.html', checks=pending_checks)
    
    @app.route('/stock')
    @login_required
    def stock_management():
        """Bestandsverwaltung mit Produktauswahl"""
        return render_template('stock_management.html')
    
    # ===== LIEFERSCHEINE & KOMMISSIONSLAGER =====
    
    @app.route('/delivery-notes')
    @login_required
    def list_delivery_notes():
        """Liste aller Lieferscheine"""
        delivery_notes = DeliveryNote.query.order_by(DeliveryNote.delivery_date.desc()).all()
        return render_template('delivery_notes/list.html', delivery_notes=delivery_notes)
    
    @app.route('/delivery-notes/new', methods=['GET', 'POST'])
    @login_required
    def create_delivery_note():
        """Neuen Lieferschein erstellen"""
        if request.method == 'POST':
            try:
                # Reseller auswählen
                customer_id = request.form.get('customer_id')
                customer = Customer.query.get_or_404(customer_id)
                
                # Lieferscheinnummer generieren
                today = datetime.now().date()
                prefix = f"LS-{today.strftime('%Y-%m-%d')}"
                
                # Höchste Nummer des Tages finden
                last_dn = DeliveryNote.query.filter(
                    DeliveryNote.delivery_note_number.like(f"{prefix}%")
                ).order_by(DeliveryNote.delivery_note_number.desc()).first()
                
                if last_dn:
                    last_num = int(last_dn.delivery_note_number.split('-')[-1])
                    next_num = last_num + 1
                else:
                    next_num = 1
                
                delivery_note_number = f"{prefix}-{next_num:04d}"
                
                # Lieferschein erstellen
                delivery_note = DeliveryNote(
                    delivery_note_number=delivery_note_number,
                    customer_id=customer_id,
                    delivery_date=datetime.strptime(request.form.get('delivery_date'), '%Y-%m-%d').date(),
                    show_tax=request.form.get('show_tax') == 'on',
                    notes=request.form.get('notes')
                )
                
                db.session.add(delivery_note)
                db.session.flush()  # Um ID zu bekommen
                
                # Positionen hinzufügen
                product_ids = request.form.getlist('product_id[]')
                quantities = request.form.getlist('quantity[]')
                
                for idx, product_id in enumerate(product_ids):
                    if not product_id:
                        continue
                    
                    product = Product.query.get(product_id)
                    quantity = Decimal(quantities[idx])
                    
                    # BESTANDSPRÜFUNG: Prüfen ob genug auf Lager
                    if product.number < int(quantity):
                        raise Exception(f"Nicht genug Bestand für {product.name}! Verfügbar: {product.number}, benötigt: {int(quantity)}")
                    
                    # Reseller-Preis verwenden
                    unit_price = product.reseller_price if product.reseller_price else product.price
                    
                    item = DeliveryNoteItem(
                        delivery_note_id=delivery_note.id,
                        product_id=product_id,
                        description=f"{product.name} ({product.quantity})" if product.quantity else product.name,
                        quantity=quantity,
                        unit_price=unit_price,
                        position=idx
                    )
                    item.calculate_total()
                    db.session.add(item)
                    
                    # Bestand beim Reseller aktualisieren/erstellen
                    stock = ConsignmentStock.query.filter_by(
                        customer_id=customer_id,
                        product_id=product_id
                    ).first()
                    
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
                            last_delivery_note_id=delivery_note.id
                        )
                        db.session.add(stock)
                    
                    # Hauptbestand reduzieren
                    product.number -= int(quantity)
                
                db.session.commit()
                
                flash(f'Lieferschein {delivery_note_number} erfolgreich erstellt!', 'success')
                return redirect(url_for('view_delivery_note', delivery_note_id=delivery_note.id))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Fehler beim Erstellen des Lieferscheins: {str(e)}', 'error')
        
        # GET: Formular anzeigen - NUR Reseller anzeigen
        customers = Customer.query.filter_by(reseller=True).order_by(Customer.company_name, Customer.last_name).all()
        products = Product.query.filter_by(active=True).order_by(Product.name).all()
        
        return render_template('delivery_notes/create.html', customers=customers, products=products)
    
    @app.route('/delivery-notes/<int:delivery_note_id>')
    @login_required
    def view_delivery_note(delivery_note_id):
        """Lieferschein anzeigen"""
        delivery_note = DeliveryNote.query.get_or_404(delivery_note_id)
        return render_template('delivery_notes/view.html', delivery_note=delivery_note)
    
    @app.route('/delivery-notes/<int:delivery_note_id>/pdf')
    @login_required
    def download_delivery_note_pdf(delivery_note_id):
        """Lieferschein als PDF herunterladen"""
        from delivery_note_service import generate_delivery_note_pdf
        
        delivery_note = DeliveryNote.query.get_or_404(delivery_note_id)
        pdf_path = generate_delivery_note_pdf(delivery_note, app.config['PDF_FOLDER'], app.config)
        
        return send_file(pdf_path, as_attachment=True, 
                        download_name=f'Lieferschein_{delivery_note.delivery_note_number}.pdf')
    
    @app.route('/consignment/<int:customer_id>')
    @login_required
    def consignment_stock_overview(customer_id):
        """Kommissionslager-Übersicht für einen Reseller"""
        customer = Customer.query.get_or_404(customer_id)
        stock_items = ConsignmentStock.query.filter_by(customer_id=customer_id).all()
        
        return render_template('consignment/overview.html', customer=customer, stock_items=stock_items)
    
    @app.route('/consignment/<int:customer_id>/update', methods=['POST'])
    @login_required
    def update_consignment_stock(customer_id):
        """Bestand im Kommissionslager korrigieren"""
        try:
            stock_id = request.form.get('stock_id')
            new_quantity = int(request.form.get('quantity'))
            
            stock = ConsignmentStock.query.get_or_404(stock_id)
            
            if stock.customer_id != customer_id:
                flash('Ungültiger Zugriff', 'error')
                return redirect(url_for('consignment_stock_overview', customer_id=customer_id))
            
            old_quantity = stock.quantity
            stock.quantity = new_quantity
            stock.last_updated = datetime.utcnow()
            
            db.session.commit()
            
            flash(f'Bestand aktualisiert: {old_quantity} → {new_quantity}', 'success')
            
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Aktualisieren: {str(e)}', 'error')
        
        return redirect(url_for('consignment_stock_overview', customer_id=customer_id))
    
    @app.route('/consignment/<int:customer_id>/create-invoice', methods=['POST'])
    @login_required
    def create_invoice_from_consignment(customer_id):
        """Rechnung aus Kommissionslager erstellen"""
        try:
            customer = Customer.query.get_or_404(customer_id)
            
            # Alle markierten/verkauften Artikel
            product_ids = request.form.getlist('product_id[]')
            quantities = request.form.getlist('sold_quantity[]')
            show_tax = request.form.get('show_tax') == 'on'
            
            if not product_ids or not any(q for q in quantities if q and int(q) > 0):
                flash('Keine Artikel zum Abrechnen ausgewählt', 'warning')
                return redirect(url_for('consignment_stock_overview', customer_id=customer_id))
            
            # Rechnungsnummer generieren
            today = datetime.now().date()
            prefix = f"RE-{today.strftime('%Y-%m-%d')}"
            
            last_invoice = Invoice.query.filter(
                Invoice.invoice_number.like(f"{prefix}%")
            ).order_by(Invoice.invoice_number.desc()).first()
            
            if last_invoice:
                last_num = int(last_invoice.invoice_number.split('-')[-1])
                next_num = last_num + 1
            else:
                next_num = 1
            
            invoice_number = f"{prefix}-{next_num:04d}"
            
            # Rechnung erstellen (OHNE sofort zur DB hinzuzufügen)
            due_date = today + timedelta(days=14)
            
            # Steuermodell basierend auf Checkbox
            # Wichtig: Bei Reseller-Preisen ist MwSt bereits im Preis enthalten (wie bei Landwirtschaft)
            if show_tax:
                tax_model = 'landwirtschaft'  # Durchschnittssatzbesteuerung: Brutto = Netto, MwSt aus Summe berechnen
            else:
                tax_model = 'kleinunternehmer'
            
            invoice = Invoice(
                invoice_number=invoice_number,
                customer_id=customer_id,
                invoice_date=today,
                due_date=due_date,
                status='draft',
                customer_type='reseller',
                tax_model=tax_model,
                tax_rate=Decimal('7.80') if show_tax else Decimal('0.00'),  # 7.80% ist Standard für landw. Urproduktion
                subtotal=Decimal('0.00'),
                tax_amount=Decimal('0.00'),
                total=Decimal('0.00')
            )
            
            # WICHTIG: Hash SOFORT generieren bevor Invoice zur DB hinzugefügt wird
            invoice.generate_hash()
            
            # Positionen vorbereiten und Kommissionslager reduzieren
            line_items = []
            for idx, product_id in enumerate(product_ids):
                if not product_id or not quantities[idx]:
                    continue
                
                sold_qty = int(quantities[idx])
                if sold_qty <= 0:
                    continue
                
                stock = ConsignmentStock.query.filter_by(
                    customer_id=customer_id,
                    product_id=product_id
                ).first()
                
                if not stock or stock.quantity < sold_qty:
                    raise Exception(f"Nicht genügend Bestand für Produkt ID {product_id}")
                
                # Rechnungsposition vorbereiten
                product = Product.query.get(product_id)
                line_item = LineItem(
                    product_id=product.id,
                    description=f"{product.name} ({product.quantity})" if product.quantity else product.name,
                    quantity=Decimal(sold_qty),
                    unit_price=stock.unit_price,  # Reseller-Preis
                    tax_rate=product.tax_rate if product.tax_rate else Decimal('7.80'),
                    position=idx
                )
                line_item.calculate_total()
                line_items.append(line_item)
                
                # Kommissionslager reduzieren
                stock.quantity -= sold_qty
                stock.last_updated = datetime.utcnow()
            
            # Invoice zur Session hinzufügen und ID bekommen
            db.session.add(invoice)
            db.session.flush()
            
            # Jetzt Line Items mit invoice_id hinzufügen
            for line_item in line_items:
                line_item.invoice_id = invoice.id
                db.session.add(line_item)
            
            # Flush und Summen neu berechnen
            db.session.flush()
            invoice.calculate_totals()
            
            db.session.commit()
            
            flash(f'Rechnung {invoice_number} erfolgreich erstellt!', 'success')
            return redirect(url_for('view_invoice', invoice_id=invoice.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Erstellen der Rechnung: {str(e)}', 'error')
            return redirect(url_for('consignment_stock_overview', customer_id=customer_id))
    
    @app.route('/payments/<int:check_id>/resolve', methods=['POST'])
    @login_required
    def resolve_payment_check(check_id):
        """Markiert eine Zahlungsprüfung als gelöst"""
        check = PaymentCheck.query.get_or_404(check_id)
        
        action = request.form.get('action')
        
        if action == 'mark_paid':
            # Rechnung als bezahlt markieren
            if check.invoice_id:
                invoice = Invoice.query.get(check.invoice_id)
                invoice.status = 'paid'
                check.resolved = True
                check.resolved_at = datetime.utcnow()
                check.notes = (check.notes or '') + ' | Manuell als bezahlt markiert'
                db.session.commit()
                flash('Rechnung als bezahlt markiert', 'success')
            else:
                flash('Keine Rechnung zugeordnet', 'error')
        
        elif action == 'ignore':
            # Als gelöst markieren ohne weitere Aktion
            check.resolved = True
            check.resolved_at = datetime.utcnow()
            check.notes = (check.notes or '') + ' | Ignoriert/Bereits behandelt'
            db.session.commit()
            flash('Prüfung als erledigt markiert', 'success')
        
        return redirect(url_for('payment_review'))
    
    @app.route('/settings/test-email', methods=['POST'])
    @login_required
    @role_required('admin')
    def test_email_settings():
        """E-Mail-Einstellungen (SMTP und IMAP) testen"""
        import smtplib
        import imaplib
        import socket
        
        results = {
            'smtp': {'success': False, 'message': ''},
            'imap': {'success': False, 'message': ''}
        }
        
        # SMTP Test
        try:
            smtp_server = app.config.get('MAIL_SERVER')
            smtp_port = app.config.get('MAIL_PORT')
            smtp_username = app.config.get('MAIL_USERNAME')
            smtp_password = app.config.get('MAIL_PASSWORD')
            smtp_use_ssl = app.config.get('MAIL_USE_SSL')
            
            if not smtp_server or not smtp_username or not smtp_password:
                results['smtp']['message'] = 'SMTP-Konfiguration unvollständig (Server, Username oder Passwort fehlt)'
            else:
                # Verbindung aufbauen
                if smtp_use_ssl:
                    server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=10)
                else:
                    server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
                    if app.config.get('MAIL_USE_TLS'):
                        server.starttls()
                
                # Login versuchen
                server.login(smtp_username, smtp_password)
                server.quit()
                
                results['smtp']['success'] = True
                results['smtp']['message'] = f'Verbindung erfolgreich zu {smtp_server}:{smtp_port}'
                
        except smtplib.SMTPAuthenticationError:
            results['smtp']['message'] = 'Authentifizierung fehlgeschlagen - Benutzername oder Passwort falsch'
        except smtplib.SMTPException as e:
            results['smtp']['message'] = f'SMTP-Fehler: {str(e)}'
        except socket.gaierror:
            results['smtp']['message'] = f'Server {smtp_server} nicht erreichbar - DNS-Fehler'
        except socket.timeout:
            results['smtp']['message'] = f'Zeitüberschreitung bei Verbindung zu {smtp_server}:{smtp_port}'
        except Exception as e:
            results['smtp']['message'] = f'Unerwarteter Fehler: {str(e)}'
        
        # IMAP Test
        try:
            imap_server = app.config.get('IMAP_SERVER')
            imap_port = app.config.get('IMAP_PORT')
            imap_username = app.config.get('IMAP_USERNAME')
            imap_password = app.config.get('IMAP_PASSWORD')
            imap_use_ssl = app.config.get('IMAP_USE_SSL')
            
            if not imap_server or not imap_username or not imap_password:
                results['imap']['message'] = 'IMAP-Konfiguration unvollständig (Server, Username oder Passwort fehlt)'
            else:
                # Verbindung aufbauen
                if imap_use_ssl:
                    mail = imaplib.IMAP4_SSL(imap_server, imap_port)
                else:
                    mail = imaplib.IMAP4(imap_server, imap_port)
                
                # Login versuchen
                mail.login(imap_username, imap_password)
                
                # Mailboxen auflisten
                status, folders = mail.list()
                folder_count = len(folders) if folders else 0
                
                mail.logout()
                
                results['imap']['success'] = True
                results['imap']['message'] = f'Verbindung erfolgreich zu {imap_server}:{imap_port} ({folder_count} Ordner gefunden)'
                
        except imaplib.IMAP4.error as e:
            error_msg = str(e)
            if 'authentication failed' in error_msg.lower():
                results['imap']['message'] = 'Authentifizierung fehlgeschlagen - Benutzername oder Passwort falsch'
            else:
                results['imap']['message'] = f'IMAP-Fehler: {error_msg}'
        except socket.gaierror:
            results['imap']['message'] = f'Server {imap_server} nicht erreichbar - DNS-Fehler'
        except socket.timeout:
            results['imap']['message'] = f'Zeitüberschreitung bei Verbindung zu {imap_server}:{imap_port}'
        except Exception as e:
            results['imap']['message'] = f'Unerwarteter Fehler: {str(e)}'
        
        # Flash-Nachrichten erstellen
        if results['smtp']['success']:
            flash(f'✓ SMTP: {results["smtp"]["message"]}', 'success')
        else:
            flash(f'✗ SMTP: {results["smtp"]["message"]}', 'error')
        
        if results['imap']['success']:
            flash(f'✓ IMAP: {results["imap"]["message"]}', 'success')
        else:
            flash(f'✗ IMAP: {results["imap"]["message"]}', 'error')
        
        return redirect(url_for('settings'))
    
    # API Endpoints
    @app.route('/api/customers/search')
    @login_required
    def api_search_customers():
        """API Endpoint für Kundensuche (Autocomplete)"""
        query = request.args.get('q', '').strip()
        
        if len(query) < 3:
            return jsonify([])
        
        search_pattern = f"%{query}%"
        customers = Customer.query.filter(
            db.or_(
                Customer.company_name.ilike(search_pattern),
                Customer.first_name.ilike(search_pattern),
                Customer.last_name.ilike(search_pattern),
                Customer.email.ilike(search_pattern)
            )
        ).limit(10).all()
        
        results = []
        for customer in customers:
            results.append({
                'id': customer.id,
                'company_name': customer.company_name or '',
                'first_name': customer.first_name or '',
                'last_name': customer.last_name or '',
                'email': customer.email or '',
                'phone': customer.phone or '',
                'address': customer.address or '',
                'tax_id': customer.tax_id or '',
                'display_name': customer.display_name
            })
        
        return jsonify(results)
    
    @app.route('/api/products/search')
    @login_required
    def api_search_products():
        """API Endpoint für Produktsuche (Autocomplete)"""
        query = request.args.get('q', '').strip()
        
        if len(query) < 2:
            return jsonify([])
        
        search_pattern = f"%{query}%"
        products = Product.query.filter(
            Product.active == True,
            db.or_(
                Product.name.ilike(search_pattern),
                Product.lot_number.ilike(search_pattern),
                Product.quantity.ilike(search_pattern)
            )
        ).limit(10).all()
        
        results = []
        for product in products:
            results.append({
                'id': product.id,
                'name': product.name,
                'quantity': product.quantity or '',
                'price': float(product.price),
                'reseller_price': float(product.reseller_price) if product.reseller_price else None,
                'number': product.number,
                'lot_number': product.lot_number or '',
                'display_name': f"{product.name} {product.quantity}" if product.quantity else product.name
            })
        
        return jsonify(results)
    
    @app.route('/api/products/lot/<lot_number>/stock/add', methods=['POST'])
    @login_required
    def api_add_stock_by_lot(lot_number):
        """API Endpoint zum Hinzufügen von Bestand via lot_number"""
        try:
            data = request.get_json() or {}
            amount = int(data.get('amount', 0))
            
            if amount <= 0:
                return jsonify({'success': False, 'error': 'Menge muss größer als 0 sein'}), 400
            
            # Produkt mit dieser lot_number suchen
            product = Product.query.filter_by(lot_number=lot_number).first()
            
            if product:
                # Bestand zu existierendem Produkt hinzufügen
                product.increase_stock(amount)
                db.session.commit()
                
                return jsonify({
                    'success': True,
                    'message': f'{amount} Stück zu Charge {lot_number} hinzugefügt',
                    'product_id': product.id,
                    'product_name': product.name,
                    'lot_number': product.lot_number,
                    'new_stock': product.number
                })
            else:
                # Neues Produkt mit dieser lot_number anlegen
                # Name wird später ergänzt, daher Platzhalter
                new_product = Product(
                    name=f'Produkt {lot_number}',
                    lot_number=lot_number,
                    number=amount,
                    price=0.0,
                    active=False  # Inaktiv bis vollständige Daten vorhanden
                )
                db.session.add(new_product)
                db.session.commit()
                
                return jsonify({
                    'success': True,
                    'message': f'Neues Produkt mit Charge {lot_number} angelegt ({amount} Stück)',
                    'product_id': new_product.id,
                    'product_name': new_product.name,
                    'lot_number': new_product.lot_number,
                    'new_stock': new_product.number,
                    'new_product': True
                }), 201
            
        except ValueError as e:
            return jsonify({'success': False, 'error': 'Ungültige Menge'}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/products/lot/<lot_number>/stock/reduce', methods=['POST'])
    @login_required
    def api_reduce_stock_by_lot(lot_number):
        """API Endpoint zum Reduzieren von Bestand via lot_number"""
        try:
            data = request.get_json() or {}
            amount = int(data.get('amount', 0))
            
            if amount <= 0:
                return jsonify({'success': False, 'error': 'Menge muss größer als 0 sein'}), 400
            
            # Produkt mit dieser lot_number suchen
            product = Product.query.filter_by(lot_number=lot_number).first()
            
            if not product:
                return jsonify({
                    'success': False, 
                    'error': f'Kein Produkt mit Charge {lot_number} gefunden'
                }), 404
            
            # Prüfen ob genug Bestand vorhanden
            if product.number < amount:
                return jsonify({
                    'success': False, 
                    'error': f'Nicht genug Bestand vorhanden (aktuell: {product.number})'
                }), 400
            
            product.reduce_stock(amount)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': f'{amount} Stück von Charge {lot_number} abgezogen',
                'product_id': product.id,
                'product_name': product.name,
                'lot_number': product.lot_number,
                'new_stock': product.number
            })
            
        except ValueError as e:
            return jsonify({'success': False, 'error': 'Ungültige Menge'}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/products/<int:product_id>/stock/add', methods=['POST'])
    @login_required
    def api_add_stock(product_id):
        """API Endpoint zum Hinzufügen von Bestand (legacy, für Web-UI)"""
        try:
            data = request.get_json()
            lot_number = data.get('lot_number', '').strip()
            amount = int(data.get('amount', 0))
            
            if amount <= 0:
                return jsonify({'success': False, 'error': 'Menge muss größer als 0 sein'}), 400
            
            # Prüfen ob Produkt mit dieser lot_number bereits existiert
            if lot_number:
                existing = Product.query.filter_by(
                    name=Product.query.get(product_id).name,
                    lot_number=lot_number
                ).first()
                
                if existing and existing.id != product_id:
                    # Bestand zu existierendem Produkt hinzufügen
                    existing.increase_stock(amount)
                    db.session.commit()
                    
                    return jsonify({
                        'success': True,
                        'message': f'{amount} Stück zu existierender Charge {lot_number} hinzugefügt',
                        'product_id': existing.id,
                        'new_stock': existing.number
                    })
            
            # Ansonsten zum aktuellen Produkt hinzufügen
            product = Product.query.get_or_404(product_id)
            
            # lot_number aktualisieren falls angegeben
            if lot_number:
                product.lot_number = lot_number
            
            product.increase_stock(amount)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': f'{amount} Stück hinzugefügt',
                'product_id': product.id,
                'new_stock': product.number,
                'lot_number': product.lot_number
            })
            
        except ValueError as e:
            return jsonify({'success': False, 'error': 'Ungültige Menge'}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/products/<int:product_id>/stock/reduce', methods=['POST'])
    @login_required
    def api_reduce_stock(product_id):
        """API Endpoint zum Reduzieren von Bestand (legacy, für Web-UI)"""
        try:
            data = request.get_json()
            lot_number = data.get('lot_number', '').strip()
            amount = int(data.get('amount', 0))
            
            if amount <= 0:
                return jsonify({'success': False, 'error': 'Menge muss größer als 0 sein'}), 400
            
            product = Product.query.get_or_404(product_id)
            
            # Prüfen ob genug Bestand vorhanden
            if product.number < amount:
                return jsonify({
                    'success': False, 
                    'error': f'Nicht genug Bestand vorhanden (aktuell: {product.number})'
                }), 400
            
            # lot_number aktualisieren falls angegeben
            if lot_number:
                product.lot_number = lot_number
            
            product.reduce_stock(amount)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': f'{amount} Stück abgezogen',
                'product_id': product.id,
                'new_stock': product.number,
                'lot_number': product.lot_number
            })
            
        except ValueError as e:
            return jsonify({'success': False, 'error': 'Ungültige Menge'}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500
    
    # CLI Commands
    @app.cli.command()
    def init_db():
        """Datenbank initialisieren"""
        from werkzeug.security import generate_password_hash
        
        db.create_all()
        
        # Standard-Admin-User erstellen, falls nicht vorhanden
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                email='admin@example.com',
                password_hash=generate_password_hash('admin'),
                role='admin',
                is_active=True
            )
            db.session.add(admin)
            db.session.commit()
            print("✅ Admin-User erstellt (Username: admin, Passwort: admin)")
        
        # Marktstand-Customer für Marktbestand erstellen
        marktstand = Customer.query.filter_by(email='marktstand@system.local').first()
        if not marktstand:
            marktstand = Customer(
                company_name='Marktstand',
                first_name='Markt',
                last_name='Bestand',
                email='marktstand@system.local',
                address='Interner Bestand für Marktverkäufe'
            )
            db.session.add(marktstand)
            db.session.commit()
            print("✅ Marktstand-Customer erstellt (für Marktbestand)")
        
        print("✅ Datenbank erfolgreich initialisiert!")
    
    @app.cli.command()
    def seed_db():
        """Testdaten in die Datenbank einfügen"""
        # Testkunde
        customer = Customer(
            company_name="Beispiel GmbH",
            first_name="Max",
            last_name="Mustermann",
            email="max@beispiel.de",
            phone="+49 123 456789",
            address="Musterstraße 1\n12345 Musterstadt",
            tax_id="DE123456789"
        )
        db.session.add(customer)
        db.session.flush()
        
        # Testrechnung
        invoice = Invoice(
            invoice_number=generate_invoice_number(),
            customer_id=customer.id,
            invoice_date=datetime.now().date(),
            due_date=(datetime.now() + timedelta(days=14)).date(),
            tax_rate=19.0,
            notes="Dies ist eine Testrechnung."
        )
        
        # Testpositionen
        items = [
            LineItem(description="Webdesign", quantity=10, unit_price=80.00, position=0),
            LineItem(description="Hosting (12 Monate)", quantity=1, unit_price=120.00, position=1),
        ]
        
        for item in items:
            item.calculate_total()
            invoice.line_items.append(item)
        
        invoice.calculate_totals()
        invoice.generate_hash()
        
        db.session.add(invoice)
        db.session.commit()
        
        print("Testdaten erfolgreich eingefügt!")
    
    return app


def generate_invoice_number():
    """Generiert eine eindeutige Rechnungsnummer"""
    from datetime import datetime
    
    # Format: RE-YYYYMMDD-XXXX
    date_part = datetime.now().strftime('%Y%m%d')
    
    # Zähler für heute
    today_invoices = Invoice.query.filter(
        Invoice.invoice_number.like(f'RE-{date_part}-%')
    ).count()
    
    counter = today_invoices + 1
    return f'RE-{date_part}-{counter:04d}'


if __name__ == '__main__':
    import sys
    
    # Port aus Kommandozeile oder Standard 5000
    port = 5000
    if '--port' in sys.argv:
        try:
            port_index = sys.argv.index('--port')
            port = int(sys.argv[port_index + 1])
        except (IndexError, ValueError):
            print("Verwendung: python app.py --port 5001")
            sys.exit(1)
    
    app = create_app(os.getenv('FLASK_ENV', 'development'))
    print(f"\n🚀 Starte Flask-App auf http://localhost:{port}\n")
    app.run(debug=True, port=port)
