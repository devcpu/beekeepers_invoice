"""Generierung eindeutiger Rechnungsnummern (siehe AGENTS.md, Abschnitt "Rechnungsnummern-Schema")."""

from datetime import datetime

from models import Invoice


def generate_invoice_number():
    """Generiert eine eindeutige Rechnungsnummer im Format RE-YYYYMMDD-XXXX"""
    date_part = datetime.now().strftime("%Y%m%d")
    today_invoices = Invoice.query.filter(Invoice.invoice_number.like(f"RE-{date_part}-%")).count()
    counter = today_invoices + 1
    return f"RE-{date_part}-{counter:04d}"
