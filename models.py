from datetime import datetime
from decimal import Decimal
import hashlib
import json
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """Benutzermodell für Authentifizierung und Autorisierung"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    
    # Rollen: admin, cashier, reseller
    role = db.Column(db.String(20), nullable=False, default='cashier')
    
    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    # 2FA (Two-Factor Authentication)
    totp_secret = db.Column(db.String(32), nullable=True)  # Base32-encoded secret für TOTP
    totp_enabled = db.Column(db.Boolean, default=False)
    backup_codes = db.Column(db.Text, nullable=True)  # JSON-Array mit Backup-Codes (gehashed)
    
    # API-Token für PWA
    api_token = db.Column(db.String(255), nullable=True, unique=True)
    api_token_expires = db.Column(db.DateTime, nullable=True)
    
    # Passwort-Reset
    reset_token = db.Column(db.String(255), nullable=True, unique=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)
    
    # Reseller-spezifisch (nur wenn role='reseller')
    reseller_customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True)
    reseller_customer = db.relationship('Customer', backref='reseller_user')
    
    # Reseller-Typ (bestimmt POS-Verhalten)
    # none: Kein Reseller
    # type1_ust_extern: USt.-pflichtig mit eigenem Kassensystem (nur Kommissionsware)
    # type2_non_ust_extern: Nicht USt.-pflichtig ohne PWA (nur Kommissionsware)
    # type3_non_ust_pwa: Nicht USt.-pflichtig mit PWA (Bestandsumbuchung, keine Rechnung)
    # type4_owner_market: Owner auf Markt (Bestandsumbuchung + BAR-Rechnung)
    reseller_type = db.Column(
        db.Enum('none', 'type1_ust_extern', 'type2_non_ust_extern', 'type3_non_ust_pwa', 'type4_owner_market', 
                name='reseller_type_enum', native_enum=False),
        default='none',
        nullable=False
    )
    
    # Tracking
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)
    last_login_ip = db.Column(db.String(45), nullable=True)  # IPv6-ready
    
    def __repr__(self):
        return f'<User {self.username} ({self.role})>'
    
    def set_password(self, password):
        """Setzt ein neues Passwort (mit Hashing)"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Überprüft ein Passwort"""
        return check_password_hash(self.password_hash, password)
    
    def has_role(self, role):
        """Prüft ob User eine bestimmte Rolle hat"""
        if role == 'admin':
            return self.role == 'admin'
        elif role == 'cashier':
            return self.role in ['admin', 'cashier']
        elif role == 'reseller':
            return self.role in ['admin', 'reseller']
        return False
    
    def generate_totp_secret(self):
        """Generiert ein neues TOTP-Secret (für 2FA Setup)"""
        import pyotp
        self.totp_secret = pyotp.random_base32()
        return self.totp_secret
    
    def get_totp_uri(self, app_name='Rechnungssystem'):
        """Generiert TOTP-URI für QR-Code"""
        import pyotp
        if not self.totp_secret:
            return None
        totp = pyotp.TOTP(self.totp_secret)
        return totp.provisioning_uri(name=self.email, issuer_name=app_name)
    
    def verify_totp(self, token):
        """Verifiziert TOTP-Token"""
        import pyotp
        if not self.totp_secret or not self.totp_enabled:
            return False
        totp = pyotp.TOTP(self.totp_secret)
        return totp.verify(token, valid_window=1)  # 30 Sekunden vor/nach akzeptieren
    
    def generate_backup_codes(self, count=10):
        """Generiert Backup-Codes für 2FA-Notfälle"""
        import secrets
        codes = [secrets.token_hex(4).upper() for _ in range(count)]  # 8-stellige Hex-Codes
        # Hashe die Codes bevor sie gespeichert werden
        hashed_codes = [generate_password_hash(code) for code in codes]
        self.backup_codes = json.dumps(hashed_codes)
        return codes  # Klartext-Codes zurückgeben (nur einmal anzeigen!)
    
    def verify_backup_code(self, code):
        """Verifiziert und verbraucht einen Backup-Code"""
        if not self.backup_codes:
            return False
        codes = json.loads(self.backup_codes)
        for i, hashed_code in enumerate(codes):
            if check_password_hash(hashed_code, code.upper()):
                # Code wurde verwendet, entfernen
                codes.pop(i)
                self.backup_codes = json.dumps(codes)
                return True
        return False
    
    def generate_api_token(self, expires_in_days=30):
        """Generiert API-Token für PWA"""
        import secrets
        from datetime import timedelta
        self.api_token = secrets.token_urlsafe(32)
        self.api_token_expires = datetime.utcnow() + timedelta(days=expires_in_days)
        return self.api_token
    
    def verify_api_token(self, token):
        """Verifiziert API-Token"""
        if not self.api_token or not self.api_token_expires:
            return False
        if datetime.utcnow() > self.api_token_expires:
            return False  # Token abgelaufen
        return self.api_token == token
    
    def to_dict(self, include_sensitive=False):
        data = {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role,
            'is_active': self.is_active,
            'totp_enabled': self.totp_enabled,
            'created_at': self.created_at.isoformat(),
            'last_login': self.last_login.isoformat() if self.last_login else None
        }
        if include_sensitive:
            data['api_token'] = self.api_token
            data['api_token_expires'] = self.api_token_expires.isoformat() if self.api_token_expires else None
        return data


class Product(db.Model):
    """Produktmodell für Artikelverwaltung"""
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    number = db.Column(db.Integer, default=0)  # Anzahl vorhandener Items
    quantity = db.Column(db.String(50))  # z.B. "250g", "500g", "20ml"
    price = db.Column(db.Numeric(10, 2), nullable=False)  # Endkundenpreis
    reseller_price = db.Column(db.Numeric(10, 2))  # Wiederverkäuferpreis
    tax_rate = db.Column(db.Numeric(5, 2), default=7.80)  # MwSt-Satz für dieses Produkt (z.B. 7.80 für landw. Urproduktion)
    lot_number = db.Column(db.String(100))  # Chargennummer
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Product {self.name} ({self.quantity})>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'number': self.number,
            'quantity': self.quantity,
            'price': float(self.price),
            'reseller_price': float(self.reseller_price) if self.reseller_price else None,
            'tax_rate': float(self.tax_rate) if self.tax_rate else 7.80,
            'lot_number': self.lot_number,
            'active': self.active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def reduce_stock(self, amount):
        """Reduziert den Lagerbestand"""
        if self.number >= amount:
            self.number -= amount
            return True
        return False
    
    def increase_stock(self, amount):
        """Erhöht den Lagerbestand"""
        self.number += amount

class Customer(db.Model):
    """Kundenmodell"""
    __tablename__ = 'customers'
    
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200))
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    email = db.Column(db.String(120), unique=True, nullable=True)
    phone = db.Column(db.String(50))
    address = db.Column(db.Text)
    tax_id = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Beziehungen
    invoices = db.relationship('Invoice', backref='customer', lazy=True)
    
    def __repr__(self):
        return f'<Customer {self.email or self.full_name}>'
    
    @property
    def full_name(self):
        """Gibt den vollen Namen zurück"""
        return f"{self.first_name} {self.last_name}".strip()
    
    @property
    def display_name(self):
        """Gibt den Anzeigenamen zurück (Firma oder Name)"""
        if self.company_name:
            return self.company_name
        return self.full_name
    
    def to_dict(self):
        return {
            'id': self.id,
            'company_name': self.company_name,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
            'phone': self.phone,
            'address': self.address,
            'tax_id': self.tax_id
        }


class Invoice(db.Model):
    """Rechnungsmodell mit Manipulationssicherheit"""
    __tablename__ = 'invoices'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    
    # Rechnungsdaten
    invoice_date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    due_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='draft')  # draft, sent, paid, cancelled
    
    # Finanzielle Informationen
    subtotal = db.Column(db.Numeric(10, 2), default=0.00)
    tax_rate = db.Column(db.Numeric(5, 2), default=19.00)  # Standard: 19%
    tax_amount = db.Column(db.Numeric(10, 2), default=0.00)
    total = db.Column(db.Numeric(10, 2), default=0.00)
    
    # Steuermodell: 'standard', 'kleinunternehmer', 'landwirtschaft'
    tax_model = db.Column(db.String(20), default='standard')
    
    # Kundentyp: 'endkunde' oder 'wiederverkaeufer'
    customer_type = db.Column(db.String(20), default='endkunde')
    
    # Zusätzliche Informationen
    notes = db.Column(db.Text)
    payment_method = db.Column(db.String(50))
    
    # Manipulationssicherheit
    data_hash = db.Column(db.String(64), nullable=False)  # SHA-256 Hash
    
    # Zeitstempel
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Beziehungen
    line_items = db.relationship('LineItem', backref='invoice', lazy=True)
    
    def __repr__(self):
        return f'<Invoice {self.invoice_number}>'
    
    def calculate_totals(self):
        """Berechnet Subtotal, Steuern und Gesamtbetrag"""
        self.subtotal = sum(item.total for item in self.line_items)
        
        if self.tax_model == 'kleinunternehmer':
            # Keine MwSt., Brutto = Netto
            self.tax_amount = Decimal('0.00')
            self.total = self.subtotal
            
        elif self.tax_model == 'landwirtschaft':
            # Durchschnittssatz §24 UStG: Brutto = Netto, aber MwSt. wird aus Endsumme berechnet
            self.total = self.subtotal
            # Rückrechnung: Aus Bruttopreis die enthaltene MwSt berechnen
            # Formel: MwSt = Brutto * (Steuersatz / (100 + Steuersatz))
            
            # WICHTIG: Verwende produktspezifische tax_rate aus den LineItems!
            self.tax_amount = Decimal('0.00')
            for item in self.line_items:
                # Tax Rate aus LineItem (falls vorhanden) oder Invoice-Default
                item_tax_rate = item.tax_rate if item.tax_rate is not None else self.tax_rate
                # Rückrechnung für jedes Item einzeln
                item_tax = item.total * (Decimal(str(item_tax_rate)) / (Decimal('100') + Decimal(str(item_tax_rate))))
                self.tax_amount += item_tax
            
        else:
            # Standard: MwSt. wird auf Netto aufgeschlagen
            # WICHTIG: Verwende produktspezifische tax_rate aus den LineItems!
            self.tax_amount = Decimal('0.00')
            for item in self.line_items:
                # Tax Rate aus LineItem (falls vorhanden) oder Invoice-Default
                item_tax_rate = item.tax_rate if item.tax_rate is not None else self.tax_rate
                item_tax = item.total * (Decimal(str(item_tax_rate)) / Decimal('100'))
                self.tax_amount += item_tax
            
            self.total = self.subtotal + self.tax_amount
    
    def generate_hash(self):
        """Generiert einen SHA-256 Hash der Rechnungsdaten für Manipulationssicherheit"""
        # Relevante Daten für den Hash zusammenstellen
        hash_data = {
            'invoice_number': self.invoice_number,
            'customer_id': self.customer_id,
            'invoice_date': self.invoice_date.isoformat() if self.invoice_date else None,
            'subtotal': f"{float(self.subtotal):.2f}",
            'tax_rate': f"{float(self.tax_rate):.2f}",
            'tax_amount': f"{float(self.tax_amount):.2f}",
            'total': f"{float(self.total):.2f}",
            'tax_model': self.tax_model,
            'customer_type': self.customer_type,
            'line_items': [
                {
                    'description': item.description,
                    'quantity': f"{float(item.quantity):.2f}",
                    'unit_price': f"{float(item.unit_price):.2f}",
                    'total': f"{float(item.total):.2f}",
                    'product_id': item.product_id,
                    'tax_rate': f"{float(item.tax_rate):.2f}" if item.tax_rate else None
                }
                for item in self.line_items
            ]
        }
        
        # JSON String erstellen und hashen
        hash_string = json.dumps(hash_data, sort_keys=True)
        self.data_hash = hashlib.sha256(hash_string.encode()).hexdigest()
        return self.data_hash
    
    def calculate_hash(self):
        """Berechnet den Hash ohne ihn zu speichern (für Verifikation)"""
        hash_data = {
            'invoice_number': self.invoice_number,
            'customer_id': self.customer_id,
            'invoice_date': self.invoice_date.isoformat() if self.invoice_date else None,
            'subtotal': f"{float(self.subtotal):.2f}",
            'tax_rate': f"{float(self.tax_rate):.2f}",
            'tax_amount': f"{float(self.tax_amount):.2f}",
            'total': f"{float(self.total):.2f}",
            'tax_model': self.tax_model,
            'customer_type': self.customer_type,
            'line_items': [
                {
                    'description': item.description,
                    'quantity': f"{float(item.quantity):.2f}",
                    'unit_price': f"{float(item.unit_price):.2f}",
                    'total': f"{float(item.total):.2f}",
                    'product_id': item.product_id,
                    'tax_rate': f"{float(item.tax_rate):.2f}" if item.tax_rate else None
                }
                for item in self.line_items
            ]
        }
        
        hash_string = json.dumps(hash_data, sort_keys=True)
        return hashlib.sha256(hash_string.encode()).hexdigest()
    
    def verify_hash(self):
        """Überprüft die Integrität der Rechnung"""
        calculated_hash = self.calculate_hash()
        return self.data_hash == calculated_hash
    
    def to_dict(self):
        return {
            'id': self.id,
            'invoice_number': self.invoice_number,
            'customer': self.customer.to_dict() if self.customer else None,
            'invoice_date': self.invoice_date.isoformat() if self.invoice_date else None,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'status': self.status,
            'subtotal': float(self.subtotal),
            'tax_rate': float(self.tax_rate),
            'tax_amount': float(self.tax_amount),
            'total': float(self.total),
            'notes': self.notes,
            'payment_method': self.payment_method,
            'line_items': [item.to_dict() for item in self.line_items],
            'data_hash': self.data_hash,
            'is_valid': self.verify_hash()
        }


class LineItem(db.Model):
    """Rechnungsposten"""
    __tablename__ = 'line_items'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)  # Optional: Referenz zum Produkt
    
    description = db.Column(db.String(500), nullable=False)
    quantity = db.Column(db.Numeric(10, 2), nullable=False, default=1.00)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    total = db.Column(db.Numeric(10, 2), nullable=False)
    tax_rate = db.Column(db.Numeric(5, 2), nullable=True)  # Produktspezifischer MwSt-Satz
    
    position = db.Column(db.Integer, default=0)  # Reihenfolge der Positionen
    
    # Relationship zu Product
    product = db.relationship('Product', backref='line_items', foreign_keys=[product_id])
    
    def __repr__(self):
        return f'<LineItem {self.description}>'
    
    def calculate_total(self):
        """Berechnet den Gesamtpreis der Position"""
        self.total = self.quantity * self.unit_price
        return self.total
    
    def to_dict(self):
        return {
            'id': self.id,
            'description': self.description,
            'quantity': float(self.quantity),
            'unit_price': float(self.unit_price),
            'total': float(self.total),
            'tax_rate': float(self.tax_rate) if self.tax_rate else None,
            'position': self.position
        }


class PaymentCheck(db.Model):
    """Protokoll für automatische Zahlungsprüfungen"""
    __tablename__ = 'payment_checks'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50), nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=True)  # NULL wenn nicht gefunden
    
    # Erhaltene Zahlungsinformation
    amount_received = db.Column(db.Numeric(10, 2), nullable=False)
    check_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Status: 'matched' (passt), 'mismatch' (Differenz), 'not_found' (RE nicht gefunden), 'duplicate' (doppelt)
    status = db.Column(db.String(20), nullable=False, index=True)
    
    # Berechnete Werte
    expected_amount = db.Column(db.Numeric(10, 2))  # Erwarteter Betrag aus Rechnung
    difference = db.Column(db.Numeric(10, 2))  # Differenz (received - expected)
    
    # Zusätzliche Informationen
    notes = db.Column(db.Text)  # Fehlermeldungen, Hinweise
    resolved = db.Column(db.Boolean, default=False)  # Wurde manuell geprüft/gelöst
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.String(100))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<PaymentCheck {self.invoice_number} - {self.status}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'invoice_number': self.invoice_number,
            'invoice_id': self.invoice_id,
            'amount_received': float(self.amount_received),
            'expected_amount': float(self.expected_amount) if self.expected_amount else None,
            'difference': float(self.difference) if self.difference else None,
            'check_date': self.check_date.isoformat() if self.check_date else None,
            'status': self.status,
            'notes': self.notes,
            'resolved': self.resolved,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'resolved_by': self.resolved_by
        }


class Reminder(db.Model):
    """Mahnungen für überfällige Rechnungen"""
    __tablename__ = 'reminders'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    invoice = db.relationship('Invoice', backref='reminders')
    
    reminder_level = db.Column(db.Integer, default=1)  # 1 = erste Mahnung, 2 = zweite, etc.
    reminder_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    sent_date = db.Column(db.DateTime)  # Wann wurde sie tatsächlich versendet
    sent_via = db.Column(db.String(20))  # 'email', 'pdf', 'print'
    
    reminder_fee = db.Column(db.Numeric(10, 2), default=5.00)  # Mahngebühr
    notes = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Reminder {self.invoice_id} Level {self.reminder_level}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'invoice_id': self.invoice_id,
            'reminder_level': self.reminder_level,
            'reminder_date': self.reminder_date.isoformat() if self.reminder_date else None,
            'sent_date': self.sent_date.isoformat() if self.sent_date else None,
            'sent_via': self.sent_via,
            'reminder_fee': float(self.reminder_fee) if self.reminder_fee else 0.0,
            'notes': self.notes
        }


class DeliveryNote(db.Model):
    """Lieferscheine für Kommissionsware an Reseller"""
    __tablename__ = 'delivery_notes'
    
    id = db.Column(db.Integer, primary_key=True)
    delivery_note_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    
    # Reseller (Kunde vom Typ Wiederverkäufer)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    customer = db.relationship('Customer', backref='delivery_notes')
    
    delivery_date = db.Column(db.Date, default=datetime.utcnow, nullable=False)
    
    # Status: 'delivered' (ausgeliefert), 'partially_billed' (teilweise abgerechnet), 'billed' (komplett abgerechnet)
    status = db.Column(db.String(20), default='delivered')
    
    # MwSt ausweisen (für Freie Berufe / steuerbefreite Reseller)
    show_tax = db.Column(db.Boolean, default=False)
    
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Beziehung zu Positionen
    items = db.relationship('DeliveryNoteItem', backref='delivery_note', lazy=True)
    
    def __repr__(self):
        return f'<DeliveryNote {self.delivery_note_number}>'
    
    def calculate_total(self):
        """Berechnet Gesamtwert (mit Reseller-Preisen)"""
        return sum(float(item.total) for item in self.items)
    
    def to_dict(self):
        return {
            'id': self.id,
            'delivery_note_number': self.delivery_note_number,
            'customer_id': self.customer_id,
            'delivery_date': self.delivery_date.isoformat() if self.delivery_date else None,
            'status': self.status,
            'notes': self.notes,
            'total': self.calculate_total(),
            'items': [item.to_dict() for item in self.items]
        }


class DeliveryNoteItem(db.Model):
    """Einzelne Position auf einem Lieferschein"""
    __tablename__ = 'delivery_note_items'
    
    id = db.Column(db.Integer, primary_key=True)
    delivery_note_id = db.Column(db.Integer, db.ForeignKey('delivery_notes.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    product = db.relationship('Product')
    
    description = db.Column(db.String(500), nullable=False)
    quantity = db.Column(db.Numeric(10, 2), nullable=False, default=1.00)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)  # Reseller-Preis
    total = db.Column(db.Numeric(10, 2), nullable=False)
    
    position = db.Column(db.Integer, default=0)
    
    def __repr__(self):
        return f'<DeliveryNoteItem {self.description}>'
    
    def calculate_total(self):
        """Berechnet Gesamtpreis der Position"""
        self.total = self.quantity * self.unit_price
        return self.total
    
    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'description': self.description,
            'quantity': float(self.quantity),
            'unit_price': float(self.unit_price),
            'total': float(self.total),
            'position': self.position
        }


class ConsignmentStock(db.Model):
    """Kommissionslager beim Reseller - welche Produkte hat der Reseller aktuell"""
    __tablename__ = 'consignment_stock'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Reseller
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    customer = db.relationship('Customer', backref='consignment_stock')
    
    # Produkt
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    product = db.relationship('Product')
    
    # Bestand beim Reseller
    quantity = db.Column(db.Integer, default=0, nullable=False)
    
    # Verkaufsstatistik (für Marktbestand/Reseller)
    quantity_sold = db.Column(db.Integer, default=0, nullable=False)
    
    # Reseller-Preis (kann sich über Zeit ändern, daher hier gespeichert)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Tracking
    last_delivery_note_id = db.Column(db.Integer, db.ForeignKey('delivery_notes.id'))
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Unique constraint: Ein Produkt kann nur einmal pro Reseller im Lager sein
    __table_args__ = (
        db.UniqueConstraint('customer_id', 'product_id', name='unique_customer_product'),
    )
    
    def __repr__(self):
        return f'<ConsignmentStock Customer:{self.customer_id} Product:{self.product_id} Qty:{self.quantity}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'product_id': self.product_id,
            'product_name': self.product.name if self.product else None,
            'quantity': self.quantity,
            'unit_price': float(self.unit_price),
            'total_value': float(self.quantity * self.unit_price),
            'last_updated': self.last_updated.isoformat() if self.last_updated else None
        }


class InvoiceStatusLog(db.Model):
    """Audit Trail für Rechnungsstatus-Änderungen (GoBD-konform)"""
    __tablename__ = 'invoice_status_log'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    old_status = db.Column(db.String(50), nullable=True)
    new_status = db.Column(db.String(50), nullable=False)
    changed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    changed_by = db.Column(db.String(100), default='System')  # Später: User-Login
    reason = db.Column(db.Text, nullable=True)  # Optional: Begründung für Änderung
    
    # Relationship
    invoice = db.relationship('Invoice', backref='status_history')
    
    def __repr__(self):
        return f'<InvoiceStatusLog Invoice#{self.invoice_id}: {self.old_status}→{self.new_status}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'invoice_id': self.invoice_id,
            'old_status': self.old_status,
            'new_status': self.new_status,
            'changed_at': self.changed_at.isoformat(),
            'changed_by': self.changed_by,
            'reason': self.reason
        }


class InvoicePdfArchive(db.Model):
    """Revisionssichere PDF-Archivierung mit Hash (GoBD-konform)"""
    __tablename__ = 'invoice_pdf_archive'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    pdf_filename = db.Column(db.String(255), nullable=False)
    pdf_hash = db.Column(db.String(64), nullable=False)  # SHA-256
    file_size = db.Column(db.Integer, nullable=False)  # Bytes
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    archived_by = db.Column(db.String(100), default='System')
    
    # Relationship
    invoice = db.relationship('Invoice', backref='pdf_archives')
    
    def __repr__(self):
        return f'<InvoicePdfArchive {self.pdf_filename}>'
    
    def verify_pdf(self, pdf_path):
        """Verifiziert ob das PDF unverändert ist"""
        try:
            with open(pdf_path, 'rb') as f:
                pdf_data = f.read()
                calculated_hash = hashlib.sha256(pdf_data).hexdigest()
                return calculated_hash == self.pdf_hash
        except Exception as e:
            return False
    
    def to_dict(self):
        return {
            'id': self.id,
            'invoice_id': self.invoice_id,
            'pdf_filename': self.pdf_filename,
            'pdf_hash': self.pdf_hash,
            'file_size': self.file_size,
            'created_at': self.created_at.isoformat(),
            'archived_by': self.archived_by
        }



class StockAdjustment(db.Model):
    """Bestandsanpassungen (Eigenentnahme, Inventur, etc.) - GoBD-konform dokumentiert"""
    __tablename__ = 'stock_adjustments'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Produkt
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    product = db.relationship('Product', backref='stock_adjustments')
    
    # Anpassung
    quantity = db.Column(db.Integer, nullable=False)  # Positiv = Zugang, Negativ = Abgang
    old_stock = db.Column(db.Integer, nullable=False)  # Bestand vor Anpassung
    new_stock = db.Column(db.Integer, nullable=False)  # Bestand nach Anpassung
    
    # Typ der Anpassung
    adjustment_type = db.Column(
        db.Enum('eigenentnahme', 'geschenk', 'verderb', 'bruch', 'inventur_plus', 'inventur_minus', 'korrektur', 'sonstiges', 
                name='adjustment_type_enum', native_enum=False),
        nullable=False
    )
    
    # Dokumentation
    reason = db.Column(db.Text, nullable=False)  # Pflichtfeld für GoBD
    
    # Tracking
    adjusted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    adjusted_by_user = db.relationship('User', backref='stock_adjustments')
    adjusted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Optional: Beleg-Nummer für Eigenentnahme (für Finanzamt)
    document_number = db.Column(db.String(50), unique=True, nullable=True)
    
    def __repr__(self):
        return f'<StockAdjustment Product:{self.product_id} Qty:{self.quantity} Type:{self.adjustment_type}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'product_name': self.product.name if self.product else None,
            'quantity': self.quantity,
            'old_stock': self.old_stock,
            'new_stock': self.new_stock,
            'adjustment_type': self.adjustment_type,
            'reason': self.reason,
            'adjusted_by': self.adjusted_by,
            'adjusted_by_username': self.adjusted_by_user.username if self.adjusted_by_user else None,
            'adjusted_at': self.adjusted_at.isoformat() if self.adjusted_at else None,
            'document_number': self.document_number
        }
