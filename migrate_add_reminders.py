"""
Migrationsskript für die Reminders-Tabelle
Führt das SQL aus, um die Tabelle für Mahnungen zu erstellen
"""

from app import create_app
from models import db
from sqlalchemy import text

def migrate():
    """Führt die Migration aus"""
    app = create_app()
    
    with app.app_context():
        try:
            # SQL für Reminders-Tabelle
            sql = text("""
            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                invoice_id INTEGER NOT NULL,
                reminder_level INTEGER DEFAULT 1,
                reminder_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_date TIMESTAMP,
                sent_via VARCHAR(20),
                reminder_fee NUMERIC(10, 2) DEFAULT 5.00,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (invoice_id) REFERENCES invoices(id)
            );
            
            -- Index für schnellere Abfragen
            CREATE INDEX IF NOT EXISTS idx_reminders_invoice_id ON reminders(invoice_id);
            CREATE INDEX IF NOT EXISTS idx_reminders_reminder_level ON reminders(reminder_level);
            """)
            
            db.session.execute(sql)
            db.session.commit()
            
            print("✅ Migration erfolgreich: Reminders-Tabelle erstellt")
            print("   - Tabelle 'reminders' mit allen Feldern")
            print("   - Indizes auf invoice_id und reminder_level")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Fehler bei der Migration: {str(e)}")
            return False
        
        return True

if __name__ == '__main__':
    print("Starte Migration für Reminders-Tabelle...")
    success = migrate()
    
    if success:
        print("\n✅ Migration abgeschlossen!")
    else:
        print("\n❌ Migration fehlgeschlagen!")
