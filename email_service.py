"""
E-Mail Service für den Versand von Rechnungen
"""

import os

from flask import current_app
from flask_mail import Mail, Message

mail = Mail()


def send_invoice_email(invoice, pdf_path, recipient_email=None, cc_emails=None):
    """
    Sendet eine Rechnung per E-Mail.

    Args:
        invoice: Invoice-Objekt aus der Datenbank
        pdf_path: Pfad zur PDF-Datei
        recipient_email: Optional - überschreibt die Kunden-E-Mail
        cc_emails: Optional - Liste von CC-Empfängern

    Returns:
        True bei Erfolg, False bei Fehler
    """
    try:
        # Empfänger
        to_email = recipient_email or invoice.customer.email

        # Betreff
        subject = f"Rechnung {invoice.invoice_number} von {current_app.config.get('COMPANY_NAME', 'Ihrer Firma')}"

        # E-Mail-Text (Plain)
        customer_name = invoice.customer.company_name or f"{invoice.customer.first_name} {invoice.customer.last_name}"

        body_text = f"""
Guten Tag {customer_name},

anbei erhalten Sie die Rechnung {invoice.invoice_number} vom {invoice.invoice_date.strftime('%d.%m.%Y')}.

Rechnungsbetrag: {invoice.total:.2f} €
"""

        if invoice.due_date:
            body_text += f"Fällig am: {invoice.due_date.strftime('%d.%m.%Y')}\n"

        body_text += f"""
Bitte überweisen Sie den Betrag auf folgendes Konto:

{current_app.config.get('BANK_NAME', 'Bank')}
IBAN: {current_app.config.get('BANK_IBAN', '')}
BIC: {current_app.config.get('BANK_BIC', '')}
Verwendungszweck: {invoice.invoice_number}
"""

        # PayPal falls vorhanden
        paypal = current_app.config.get("PAYPAL", "")
        if paypal:
            body_text += f"\nAlternativ können Sie auch per PayPal an {paypal} bezahlen.\n"

        body_text += f"""
Bei Fragen stehen wir Ihnen gerne zur Verfügung.

Mit freundlichen Grüßen
{current_app.config.get('COMPANY_HOLDER', current_app.config.get('COMPANY_NAME', 'Ihr Team'))}

---
{current_app.config.get('COMPANY_NAME', '')}
{current_app.config.get('COMPANY_STREET', '')}
{current_app.config.get('COMPANY_ZIP', '')} {current_app.config.get('COMPANY_CITY', '')}

Tel: {current_app.config.get('COMPANY_PHONE', '')}
E-Mail: {current_app.config.get('COMPANY_EMAIL', '')}
Web: {current_app.config.get('COMPANY_WEBSITE', '')}
"""

        # E-Mail erstellen
        msg = Message(subject=subject, recipients=[to_email], body=body_text)

        # CC hinzufügen
        if cc_emails:
            msg.cc = cc_emails if isinstance(cc_emails, list) else [cc_emails]

        # PDF anhängen
        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as pdf_file:
                msg.attach(
                    filename=f"Rechnung_{invoice.invoice_number}.pdf",
                    content_type="application/pdf",
                    data=pdf_file.read(),
                )

        # E-Mail senden
        mail.send(msg)

        return True

    except Exception as e:
        current_app.logger.error(f"Fehler beim E-Mail-Versand: {str(e)}")
        return False


def send_email(to, subject, body, attachment_path=None, cc_emails=None):
    """
    Sendet eine generische E-Mail mit optionalem Anhang.

    Args:
        to: Empfänger-E-Mail (String)
        subject: Betreff
        body: E-Mail-Text
        attachment_path: Optional - Pfad zum Anhang
        cc_emails: Optional - Liste von CC-Empfängern

    Returns:
        True bei Erfolg, False bei Fehler
    """
    try:
        # E-Mail erstellen
        msg = Message(subject=subject, recipients=[to] if isinstance(to, str) else to, body=body)

        # CC hinzufügen
        if cc_emails:
            msg.cc = cc_emails if isinstance(cc_emails, list) else [cc_emails]

        # Anhang hinzufügen
        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as file:
                filename = os.path.basename(attachment_path)
                msg.attach(filename=filename, content_type="application/pdf", data=file.read())

        # E-Mail senden
        mail.send(msg)

        return True

    except Exception as e:
        current_app.logger.error(f"Fehler beim E-Mail-Versand: {str(e)}")
        return False
