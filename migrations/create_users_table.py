#!/usr/bin/env python3
"""
Migration: Erstellt users Tabelle für Authentifizierung und Autorisierung

Führt aus:
    python migrations/create_users_table.py
"""

import os
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from models import User, db


def create_users_table():
    """Erstellt die users Tabelle"""
    app = create_app()
    with app.app_context():
        print("=" * 60)
        print("Creating users table...")
        print("=" * 60)

        # Tabelle erstellen
        db.create_all()
        print("✓ users table created successfully")

        # Standard-Admin erstellen (falls noch keiner existiert)
        admin = User.query.filter_by(username="admin").first()
        if not admin:
            print("\nCreating default admin user...")
            admin = User(username="admin", email="admin@example.com", role="admin", is_active=True)
            admin.set_password("admin123")  # WICHTIG: Später ändern!
            db.session.add(admin)
            db.session.commit()
            print(f"✓ Admin user created: username='admin', password='admin123'")
            print("  ⚠️  WICHTIG: Bitte Passwort nach erstem Login ändern!")
        else:
            print(f"\n✓ Admin user already exists: {admin.username}")

        print("\n" + "=" * 60)
        print("Migration completed successfully!")
        print("=" * 60)


if __name__ == "__main__":
    create_users_table()
