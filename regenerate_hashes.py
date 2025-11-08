#!/usr/bin/env python3
"""
Migration: Regeneriert alle Invoice-Hashes mit korrektem Format
"""
import os

from sqlalchemy import text

from app import create_app
from models import Invoice, db


def regenerate_hashes():
    app = create_app(os.getenv('FLASK_ENV', 'development'))

    with app.app_context():
        invoices = Invoice.query.all()

        if not invoices:
            print("❌ Keine Rechnungen gefunden")
            return

        print(f"Regeneriere Hashes für {len(invoices)} Rechnungen...\n")

        for invoice in invoices:
                old_hash = invoice.data_hash
                invoice.generate_hash()
                new_hash = invoice.data_hash

                print(f"Rechnung {invoice.invoice_number}:")
                print(f"  Alt: {old_hash}")
                print(f"  Neu: {new_hash}")
                print(f"  {'✅ Gleich' if old_hash == new_hash else '🔄 Geändert'}\n")

            db.session.commit()
            print(f"\n✅ {len(invoices)} Rechnungs-Hashes aktualisiert!")

if __name__ == '__main__':
    regenerate_hashes()
