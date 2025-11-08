import email
import imaplib
import re
from datetime import datetime
from email.header import decode_header

from models import Customer, Invoice, LineItem, db


class EmailInvoiceParser:
    """
    Parser für E-Mail-basierte Rechnungsdaten aus Online-Shops.
    Kann erweitert werden für verschiedene Shop-Systeme.
    """

    def __init__(self, mail_server, mail_port, username, password, use_ssl=True):
        self.mail_server = mail_server
        self.mail_port = mail_port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.connection = None

    def connect(self):
        """Verbindung zum E-Mail-Server herstellen"""
        try:
            if self.use_ssl:
                self.connection = imaplib.IMAP4_SSL(self.mail_server, self.mail_port)
            else:
                self.connection = imaplib.IMAP4(self.mail_server, self.mail_port)

            self.connection.login(self.username, self.password)
            return True
        except Exception as e:
            print(f"Fehler beim Verbinden: {e}")
            return False

    def disconnect(self):
        """Verbindung trennen"""
        if self.connection:
            try:
                self.connection.logout()
            except:
                pass

    def fetch_unread_emails(self, folder="INBOX"):
        """Ungelesene E-Mails abrufen"""
        if not self.connection:
            return []

        try:
            self.connection.select(folder)
            status, messages = self.connection.search(None, "UNSEEN")

            if status != "OK":
                return []

            email_ids = messages[0].split()
            emails = []

            for email_id in email_ids:
                status, msg_data = self.connection.fetch(email_id, "(RFC822)")

                if status == "OK":
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            emails.append(msg)

            return emails
        except Exception as e:
            print(f"Fehler beim Abrufen der E-Mails: {e}")
            return []

    def parse_email_to_invoice_data(self, email_message):
        """
        Parst eine E-Mail und extrahiert Rechnungsdaten.
        Diese Funktion muss für verschiedene Shop-Systeme angepasst werden.
        """
        # Betreff decodieren
        subject = self.decode_subject(email_message["Subject"])

        # Absender
        from_email = email.utils.parseaddr(email_message["From"])[1]

        # E-Mail-Body extrahieren
        body = self.get_email_body(email_message)

        # Hier würde die shopspezifische Logik kommen
        # Beispiel für ein generisches Format:
        invoice_data = self.parse_generic_shop_email(body, from_email, subject)

        return invoice_data

    def decode_subject(self, subject):
        """Decodiert den E-Mail-Betreff"""
        if not subject:
            return ""

        decoded_parts = decode_header(subject)
        decoded_subject = ""

        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                decoded_subject += part.decode(encoding or "utf-8")
            else:
                decoded_subject += part

        return decoded_subject

    def get_email_body(self, email_message):
        """Extrahiert den E-Mail-Body"""
        body = ""

        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        body = part.get_payload(decode=True).decode()
                        break
                    except:
                        pass
        else:
            try:
                body = email_message.get_payload(decode=True).decode()
            except:
                pass

        return body

    def parse_generic_shop_email(self, body, from_email, subject):
        """
        Generischer Parser für Shop-E-Mails.
        Sucht nach typischen Mustern in Bestätigungs-E-Mails.
        """
        invoice_data = {"customer": {}, "line_items": [], "notes": f"Importiert aus E-Mail: {subject}"}

        # Kundendaten extrahieren
        # E-Mail-Adresse
        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", body)
        if email_match:
            invoice_data["customer"]["email"] = email_match.group(0)
        else:
            invoice_data["customer"]["email"] = from_email

        # Name extrahieren (verschiedene Muster)
        name_patterns = [r"Name:\s*([^\n]+)", r"Kunde:\s*([^\n]+)", r"Customer:\s*([^\n]+)", r"Rechnung an:\s*([^\n]+)"]

        for pattern in name_patterns:
            name_match = re.search(pattern, body, re.IGNORECASE)
            if name_match:
                name = name_match.group(1).strip()
                name_parts = name.split(" ", 1)
                invoice_data["customer"]["first_name"] = name_parts[0]
                invoice_data["customer"]["last_name"] = name_parts[1] if len(name_parts) > 1 else ""
                break

        # Adresse extrahieren
        address_pattern = r"Adresse:[\s\n]*(.+?)(?=\n\n|\Z)"
        address_match = re.search(address_pattern, body, re.DOTALL | re.IGNORECASE)
        if address_match:
            invoice_data["customer"]["address"] = address_match.group(1).strip()

        # Positionen extrahieren (vereinfachtes Beispiel)
        # Format: "Artikel: Beschreibung - Menge x Preis €"
        item_pattern = r"(\d+)x?\s+(.+?)\s+(\d+[,\.]\d{2})\s*€"
        items = re.findall(item_pattern, body)

        for qty, description, price in items:
            price_clean = float(price.replace(",", "."))
            invoice_data["line_items"].append({"description": description.strip(), "quantity": float(qty), "unit_price": price_clean})

        # Gesamtbetrag extrahieren
        total_pattern = r"Gesamt(?:betrag)?:\s*(\d+[,\.]\d{2})\s*€"
        total_match = re.search(total_pattern, body, re.IGNORECASE)
        if total_match:
            invoice_data["total"] = float(total_match.group(1).replace(",", "."))

        return invoice_data

    def create_invoice_from_email_data(self, invoice_data):
        """
        Erstellt eine Invoice in der Datenbank aus den geparsten E-Mail-Daten.
        """
        try:
            # Kunde suchen oder erstellen
            customer_email = invoice_data["customer"].get("email")
            if not customer_email:
                raise ValueError("Keine E-Mail-Adresse gefunden")

            customer = Customer.query.filter_by(email=customer_email).first()

            if not customer:
                customer = Customer(
                    email=customer_email,
                    first_name=invoice_data["customer"].get("first_name", ""),
                    last_name=invoice_data["customer"].get("last_name", ""),
                    company_name=invoice_data["customer"].get("company_name", ""),
                    address=invoice_data["customer"].get("address", ""),
                    phone=invoice_data["customer"].get("phone", ""),
                )
                db.session.add(customer)
                db.session.flush()

            # Rechnungsnummer generieren
            from app import generate_invoice_number

            invoice_number = generate_invoice_number()

            # Rechnung erstellen
            invoice = Invoice(
                invoice_number=invoice_number,
                customer_id=customer.id,
                invoice_date=datetime.now().date(),
                status="draft",  # Als Entwurf markieren zur Überprüfung
                notes=invoice_data.get("notes", "Aus E-Mail importiert"),
            )

            # Positionen hinzufügen
            for idx, item_data in enumerate(invoice_data.get("line_items", [])):
                line_item = LineItem(
                    description=item_data["description"],
                    quantity=item_data["quantity"],
                    unit_price=item_data["unit_price"],
                    position=idx,
                )
                line_item.calculate_total()
                invoice.line_items.append(line_item)

            # Summen berechnen und Hash generieren
            invoice.calculate_totals()
            invoice.generate_hash()

            db.session.add(invoice)
            db.session.commit()

            return invoice

        except Exception as e:
            db.session.rollback()
            raise Exception(f"Fehler beim Erstellen der Rechnung: {e}")


def process_incoming_emails(config):
    """
    Hauptfunktion zum Verarbeiten eingehender E-Mails.
    Kann als Cronjob oder manuell aufgerufen werden.
    """
    parser = EmailInvoiceParser(
        mail_server=config["MAIL_SERVER"],
        mail_port=config["MAIL_PORT"],
        username=config["MAIL_USERNAME"],
        password=config["MAIL_PASSWORD"],
        use_ssl=config["MAIL_USE_SSL"],
    )

    if not parser.connect():
        return {"success": False, "message": "Verbindung fehlgeschlagen"}

    try:
        emails = parser.fetch_unread_emails()
        processed = 0
        errors = []

        for email_msg in emails:
            try:
                invoice_data = parser.parse_email_to_invoice_data(email_msg)

                # Nur E-Mails mit erkannten Daten verarbeiten
                if invoice_data.get("line_items"):
                    invoice = parser.create_invoice_from_email_data(invoice_data)
                    processed += 1
                    print(f"Rechnung {invoice.invoice_number} erstellt")

            except Exception as e:
                errors.append(str(e))
                print(f"Fehler beim Verarbeiten einer E-Mail: {e}")

        return {"success": True, "processed": processed, "errors": errors}

    finally:
        parser.disconnect()


# Beispiel für shopspezifische Parser (können erweitert werden)


class WooCommerceEmailParser(EmailInvoiceParser):
    """Spezialisierter Parser für WooCommerce-Shop E-Mails"""

    def parse_email_to_invoice_data(self, email_message):
        body = self.get_email_body(email_message)
        # WooCommerce-spezifische Parsing-Logik hier
        return super().parse_generic_shop_email(body, "", "")


class ShopifyEmailParser(EmailInvoiceParser):
    """Spezialisierter Parser für Shopify-Shop E-Mails"""

    def parse_email_to_invoice_data(self, email_message):
        body = self.get_email_body(email_message)
        # Shopify-spezifische Parsing-Logik hier
        return super().parse_generic_shop_email(body, "", "")
