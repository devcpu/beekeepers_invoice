#!/usr/bin/env python3
"""
Migration: Erstellt die payment_checks Tabelle für automatischen Zahlungsabgleich
"""
from app import create_app
from models import db
from sqlalchemy import text
import os

def migrate():
    app = create_app(os.getenv('FLASK_ENV', 'development'))
    
    with app.app_context():
        try:
            print("Erstelle payment_checks Tabelle...")
            
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS payment_checks (
                    id SERIAL PRIMARY KEY,
                    invoice_number VARCHAR(50) NOT NULL,
                    invoice_id INTEGER REFERENCES invoices(id),
                    amount_received NUMERIC(10, 2) NOT NULL,
                    check_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    status VARCHAR(20) NOT NULL,
                    expected_amount NUMERIC(10, 2),
                    difference NUMERIC(10, 2),
                    notes TEXT,
                    resolved BOOLEAN DEFAULT FALSE,
                    resolved_at TIMESTAMP,
                    resolved_by VARCHAR(100),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX IF NOT EXISTS idx_payment_checks_invoice_number 
                ON payment_checks(invoice_number);
                
                CREATE INDEX IF NOT EXISTS idx_payment_checks_status 
                ON payment_checks(status);
                
                CREATE INDEX IF NOT EXISTS idx_payment_checks_resolved 
                ON payment_checks(resolved);
            """))
            
            db.session.commit()
            
            print("✅ Migration erfolgreich abgeschlossen!")
            print("   - Tabelle payment_checks erstellt")
            print("   - Indices für invoice_number, status und resolved erstellt")
            print("\nAPI-Endpoint verfügbar unter: POST /api/payments/check")
            print("UI verfügbar unter: /payments/review")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Fehler bei Migration: {e}")
            raise

if __name__ == '__main__':
    migrate()
