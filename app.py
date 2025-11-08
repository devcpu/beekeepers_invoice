from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from config import config
from models import db, Customer, Invoice, LineItem, Product, PaymentCheck, Reminder, DeliveryNote, DeliveryNoteItem, ConsignmentStock, InvoiceStatusLog, InvoicePdfArchive, User
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
                    flash('Ihr Account wurde deaktiviert.', 'danger')
                    return redirect(url_for('login'))
                
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
    
    # ========== HAUPTSEITEN-ROUTEN ==========
    
    # Routes
    @app.route('/')
    @login_required
    def index():
        """Startseite mit Übersicht"""
        recent_invoices = Invoice.query.order_by(Invoice.created_at.desc()).limit(10).all()
        stats = {
            'total_invoices': Invoice.query.count(),
            'draft_invoices': Invoice.query.filter_by(status='draft').count(),
            'sent_invoices': Invoice.query.filter_by(status='sent').count(),
            'paid_invoices': Invoice.query.filter_by(status='paid').count(),
            'cancelled_invoices': Invoice.query.filter_by(status='cancelled').count(),
            'total_customers': Customer.query.count()
        }
        return render_template('index.html', invoices=recent_invoices, stats=stats)
    
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
            changed_by='System',  # TODO: User-Login implementieren
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
                    changed_by='System',
                    reason=f"Storniert durch {cancellation_number}: {reason}"
                ))
                
                db.session.add(InvoiceStatusLog(
                    invoice_id=cancellation_invoice.id,
                    old_status=None,
                    new_status='sent',
                    changed_by='System',
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
                    archived_by='System'
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
                
                db.session.commit()
                flash('Kundendaten erfolgreich aktualisiert!', 'success')
                return redirect(url_for('view_customer', customer_id=customer.id))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Fehler beim Aktualisieren: {str(e)}', 'error')
        
        return render_template('customers/edit.html', customer=customer)
    
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
        products = Product.query.filter_by(active=True).order_by(Product.name).all()
        return render_template('pos.html', products=products)
    
    @app.route('/pos/complete-sale', methods=['POST'])
    @login_required
    @role_required('cashier', 'admin')
    def complete_pos_sale():
        """Verkauf abschließen - Bestand reduzieren und GoBD-konform dokumentieren"""
        try:
            data = request.get_json()
            items = data.get('items', {})
            
            if not items:
                return jsonify({'success': False, 'message': 'Warenkorb ist leer'}), 400
            
            # Generiere Belegnummer (GoBD-konform)
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
            
            # Berechne Summen
            subtotal = Decimal('0.00')
            line_items_data = []
            
            for product_id, quantity in items.items():
                product = Product.query.get(int(product_id))
                if not product:
                    return jsonify({'success': False, 'message': f'Produkt {product_id} nicht gefunden'}), 404
                
                if product.number < quantity:
                    return jsonify({
                        'success': False, 
                        'message': f'Nicht genug Bestand für {product.name}. Verfügbar: {product.number}, Benötigt: {quantity}'
                    }), 400
                
                line_total = Decimal(str(product.price)) * Decimal(str(quantity))
                subtotal += line_total
                
                line_items_data.append({
                    'product': product,
                    'quantity': quantity,
                    'unit_price': product.price,
                    'tax_rate': product.tax_rate,
                    'total': line_total
                })
                
                # Bestand reduzieren
                product.number -= quantity
            
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
                changed_by='POS-System',
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
        
        # GET: Formular anzeigen
        customers = Customer.query.order_by(Customer.company_name, Customer.last_name).all()
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
    
    # API Endpoints
    @app.route('/api/invoices/<int:invoice_id>')
    @login_required
    def api_get_invoice(invoice_id):
        """API Endpoint für Rechnungsdetails"""
        invoice = Invoice.query.get_or_404(invoice_id)
        return jsonify(invoice.to_dict())
    
    @app.route('/api/invoices/<int:invoice_id>/verify')
    @login_required
    def api_verify_invoice(invoice_id):
        """API Endpoint zur Überprüfung der Rechnungsintegrität"""
        invoice = Invoice.query.get_or_404(invoice_id)
        is_valid = invoice.verify_hash()
        return jsonify({
            'invoice_id': invoice_id,
            'invoice_number': invoice.invoice_number,
            'is_valid': is_valid,
            'data_hash': invoice.data_hash
        })
    
    @app.route('/api/payments/check', methods=['POST'])
    @login_required
    def api_check_payment():
        """API Endpoint für automatischen Zahlungsabgleich"""
        try:
            data = request.get_json()
            invoice_number = data.get('invoice_number', '').strip()
            amount_received = Decimal(str(data.get('amount', 0)))
            
            if not invoice_number:
                return jsonify({'success': False, 'error': 'Rechnungsnummer fehlt'}), 400
            
            if amount_received <= 0:
                return jsonify({'success': False, 'error': 'Betrag muss größer als 0 sein'}), 400
            
            # Rechnung suchen
            invoice = Invoice.query.filter_by(invoice_number=invoice_number).first()
            
            if not invoice:
                # Rechnung nicht gefunden
                payment_check = PaymentCheck(
                    invoice_number=invoice_number,
                    invoice_id=None,
                    amount_received=amount_received,
                    status='not_found',
                    expected_amount=None,
                    difference=None,
                    notes=f'Rechnung {invoice_number} nicht in Datenbank gefunden'
                )
                db.session.add(payment_check)
                db.session.commit()
                
                return jsonify({
                    'success': False,
                    'status': 'not_found',
                    'message': f'Rechnung {invoice_number} nicht gefunden',
                    'check_id': payment_check.id,
                    'requires_review': True
                }), 404
            
            # Prüfen ob bereits bezahlt (mögliche Doppelzahlung)
            if invoice.status == 'paid':
                existing_checks = PaymentCheck.query.filter_by(
                    invoice_id=invoice.id,
                    status='matched'
                ).count()
                
                if existing_checks > 0:
                    # Doppelzahlung erkannt
                    payment_check = PaymentCheck(
                        invoice_number=invoice_number,
                        invoice_id=invoice.id,
                        amount_received=amount_received,
                        status='duplicate',
                        expected_amount=invoice.total,
                        difference=amount_received - invoice.total,
                        notes=f'Rechnung bereits als bezahlt markiert (Status: {invoice.status})'
                    )
                    db.session.add(payment_check)
                    db.session.commit()
                    
                    return jsonify({
                        'success': False,
                        'status': 'duplicate',
                        'message': 'Rechnung bereits bezahlt - mögliche Doppelzahlung',
                        'invoice_id': invoice.id,
                        'expected_amount': float(invoice.total),
                        'amount_received': float(amount_received),
                        'check_id': payment_check.id,
                        'requires_review': True
                    }), 409
            
            # Beträge vergleichen
            expected_amount = invoice.total
            difference = amount_received - expected_amount
            
            # Toleranz für Rundungsdifferenzen (0.01 €)
            tolerance = Decimal('0.01')
            
            if abs(difference) <= tolerance:
                # Betrag stimmt - Rechnung als bezahlt markieren
                invoice.status = 'paid'
                
                payment_check = PaymentCheck(
                    invoice_number=invoice_number,
                    invoice_id=invoice.id,
                    amount_received=amount_received,
                    status='matched',
                    expected_amount=expected_amount,
                    difference=difference,
                    notes='Zahlung erfolgreich zugeordnet, Rechnung als bezahlt markiert'
                )
                db.session.add(payment_check)
                db.session.commit()
                
                return jsonify({
                    'success': True,
                    'status': 'matched',
                    'message': f'Zahlung für {invoice_number} erfolgreich verbucht',
                    'invoice_id': invoice.id,
                    'expected_amount': float(expected_amount),
                    'amount_received': float(amount_received),
                    'difference': float(difference),
                    'check_id': payment_check.id,
                    'requires_review': False
                }), 200
            
            else:
                # Betragsdifferenz - manuelle Prüfung erforderlich
                payment_check = PaymentCheck(
                    invoice_number=invoice_number,
                    invoice_id=invoice.id,
                    amount_received=amount_received,
                    status='mismatch',
                    expected_amount=expected_amount,
                    difference=difference,
                    notes=f'Betragsdifferenz: {float(difference):.2f} € (erwartet: {float(expected_amount):.2f} €, erhalten: {float(amount_received):.2f} €)'
                )
                db.session.add(payment_check)
                db.session.commit()
                
                return jsonify({
                    'success': False,
                    'status': 'mismatch',
                    'message': 'Betragsdifferenz festgestellt - manuelle Prüfung erforderlich',
                    'invoice_id': invoice.id,
                    'expected_amount': float(expected_amount),
                    'amount_received': float(amount_received),
                    'difference': float(difference),
                    'check_id': payment_check.id,
                    'requires_review': True
                }), 200
            
        except ValueError as e:
            return jsonify({'success': False, 'error': f'Ungültiger Betrag: {str(e)}'}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500
    
    # CLI Commands
    @app.cli.command()
    def init_db():
        """Datenbank initialisieren"""
        db.create_all()
        print("Datenbank erfolgreich initialisiert!")
    
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
