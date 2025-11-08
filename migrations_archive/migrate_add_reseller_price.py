#!/usr/bin/env python3
"""
Migration: Fügt reseller_price zur products Tabelle und customer_type zur invoices Tabelle hinzu
"""
import os

from sqlalchemy import text

from app import create_app
from models import db


def migrate():
    app = create_app(os.getenv("FLASK_ENV", "development"))

    with app.app_context():
        try:
            # Spalte reseller_price zu products hinzufügen
            print("Füge reseller_price Spalte zu products hinzu...")
            db.session.execute(
                text(
                    """
                ALTER TABLE products
                ADD COLUMN IF NOT EXISTS reseller_price NUMERIC(10, 2)
            """
                )
            )

            # Spalte customer_type zu invoices hinzufügen
            print("Füge customer_type Spalte zu invoices hinzu...")
            db.session.execute(
                text(
                    """
                ALTER TABLE invoices
                ADD COLUMN IF NOT EXISTS customer_type VARCHAR(20) DEFAULT 'endkunde'
            """
                )
            )

            db.session.commit()
            print("✅ Migration erfolgreich abgeschlossen!")
            print("   - reseller_price Spalte zu products hinzugefügt")
            print("   - customer_type Spalte zu invoices hinzugefügt")

        except Exception as e:
            db.session.rollback()
            print(f"❌ Fehler bei Migration: {e}")
            raise


if __name__ == "__main__":
    migrate()
