#!/usr/bin/env python
"""
Migration Script: Fügt tax_model Spalte zur invoices Tabelle hinzu
"""
import os

os.environ.setdefault("FLASK_ENV", "development")

from app import create_app
from models import db

app = create_app()

with app.app_context():
    # SQL für Migration
    try:
        db.session.execute(
            db.text(
                """
            ALTER TABLE invoices
            ADD COLUMN IF NOT EXISTS tax_model VARCHAR(20) DEFAULT 'standard'
        """
            )
        )
        db.session.commit()
        print("✅ Migration erfolgreich: tax_model Spalte hinzugefügt")
    except Exception as e:
        print(f"⚠️  Migration bereits durchgeführt oder Fehler: {e}")
        db.session.rollback()
