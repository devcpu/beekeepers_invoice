"""
Migrationsscript: E-Mail-Feld in Customers auf optional setzen
"""
from app import create_app
from models import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    # E-Mail-Feld auf nullable setzen und unique constraint entfernen/neu setzen
    db.session.execute(text("""
        -- Unique Constraint entfernen falls vorhanden
        ALTER TABLE customers DROP CONSTRAINT IF EXISTS customers_email_key;
        
        -- Spalte auf nullable setzen
        ALTER TABLE customers ALTER COLUMN email DROP NOT NULL;
        
        -- Unique Constraint nur für nicht-null Werte wieder hinzufügen
        CREATE UNIQUE INDEX customers_email_unique ON customers (email) WHERE email IS NOT NULL;
    """))
    db.session.commit()
    
    print("✓ E-Mail-Feld erfolgreich auf optional gesetzt!")
    print("  - NOT NULL Constraint entfernt")
    print("  - Unique Index für nicht-null Werte erstellt")
