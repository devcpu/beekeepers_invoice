#!/usr/bin/env python3
"""
Migration: Regeneriert alle Invoice-Hashes mit korrektem Format
"""
from app import create_app
from models import db, Invoice
from sqlalchemy import text
import os

def regenerate_hashes():
    app = create_app(os.getenv('FLASK_ENV', 'development'))
    
    with app.app_context():
        invoices = Invoice.query.all()
        
        if not invoices:
            print("❌ Keine Rechnungen gefunden")
            return
        
        print(f"Regeneriere Hashes für {len(invoices)} Rechnungen...\n")
        
        # Trigger temporär deaktivieren
        print("🔓 Deaktiviere Hash-Schutz-Trigger...")
        db.session.execute(text("DROP TRIGGER IF EXISTS trigger_protect_invoice_hash ON invoices;"))
        db.session.commit()
        
        try:
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
            
        finally:
            # Trigger wieder aktivieren
            print("\n🔒 Aktiviere Hash-Schutz-Trigger wieder...")
            db.session.execute(text("""
                CREATE TRIGGER trigger_protect_invoice_hash
                BEFORE UPDATE ON invoices
                FOR EACH ROW
                EXECUTE FUNCTION protect_invoice_hash();
            """))
            db.session.commit()
            print("✅ Trigger wieder aktiv!")

if __name__ == '__main__':
    regenerate_hashes()
