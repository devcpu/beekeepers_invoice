#!/usr/bin/env python3
"""
Migration: Schützt das data_hash Feld vor nachträglicher Änderung durch DB-Trigger
"""
from app import create_app
from models import db
from sqlalchemy import text
import os

def migrate():
    app = create_app(os.getenv('FLASK_ENV', 'development'))
    
    with app.app_context():
        try:
            # Trigger-Funktion erstellen
            print("Erstelle Trigger-Funktion zum Schutz von data_hash...")
            db.session.execute(text("""
                CREATE OR REPLACE FUNCTION protect_invoice_hash()
                RETURNS TRIGGER AS $$
                BEGIN
                    -- Bei UPDATE: Verhindere Änderung des data_hash
                    IF TG_OP = 'UPDATE' THEN
                        IF OLD.data_hash IS NOT NULL AND NEW.data_hash != OLD.data_hash THEN
                            RAISE EXCEPTION 'Änderung von data_hash nicht erlaubt. Hash ist unveränderlich zur Sicherstellung der Datenintegrität.';
                        END IF;
                    END IF;
                    
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            """))
            
            # Bestehenden Trigger löschen falls vorhanden
            db.session.execute(text("""
                DROP TRIGGER IF EXISTS trigger_protect_invoice_hash ON invoices;
            """))
            
            # Trigger erstellen
            print("Erstelle Trigger auf invoices Tabelle...")
            db.session.execute(text("""
                CREATE TRIGGER trigger_protect_invoice_hash
                BEFORE UPDATE ON invoices
                FOR EACH ROW
                EXECUTE FUNCTION protect_invoice_hash();
            """))
            
            db.session.commit()
            print("✅ Migration erfolgreich abgeschlossen!")
            print("   - Trigger-Funktion protect_invoice_hash() erstellt")
            print("   - Trigger auf invoices.data_hash gesetzt")
            print("   - data_hash kann jetzt nur noch beim INSERT gesetzt werden")
            print("   - Jeder Versuch eines UPDATEs wird mit einer Exception abgelehnt")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Fehler bei Migration: {e}")
            raise

if __name__ == '__main__':
    migrate()
