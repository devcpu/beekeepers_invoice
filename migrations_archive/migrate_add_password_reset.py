#!/usr/bin/env python
"""
Migration: Passwort-Reset Felder zur User-Tabelle hinzufügen

Fügt folgende Felder hinzu:
- reset_token (String 255, unique, nullable)
- reset_token_expires (DateTime, nullable)

Verwendung:
    python migrate_add_password_reset.py
"""

from sqlalchemy import text

from app import create_app, db


def migrate():
    """Führe Migration aus"""
    app = create_app()

    with app.app_context():
        try:
            # Prüfen ob Felder bereits existieren
            result = db.session.execute(
                text(
                    """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='users' AND column_name='reset_token'
            """
                )
            )

            if result.fetchone():
                print("⚠️  Migration bereits durchgeführt - reset_token existiert bereits")
                return

            # Felder hinzufügen
            print("📝 Füge reset_token Feld hinzu...")
            db.session.execute(
                text(
                    """
                ALTER TABLE users
                ADD COLUMN reset_token VARCHAR(255) UNIQUE
            """
                )
            )

            print("📝 Füge reset_token_expires Feld hinzu...")
            db.session.execute(
                text(
                    """
                ALTER TABLE users
                ADD COLUMN reset_token_expires TIMESTAMP
            """
                )
            )

            # Index erstellen für schnellere Token-Suche
            print("📝 Erstelle Index für reset_token...")
            db.session.execute(
                text(
                    """
                CREATE INDEX idx_users_reset_token
                ON users(reset_token)
                WHERE reset_token IS NOT NULL
            """
                )
            )

            db.session.commit()
            print("✅ Migration erfolgreich durchgeführt!")
            print("")
            print("Hinzugefügte Felder:")
            print("  - users.reset_token (VARCHAR 255, UNIQUE)")
            print("  - users.reset_token_expires (TIMESTAMP)")
            print("  - Index: idx_users_reset_token")

        except Exception as e:
            db.session.rollback()
            print(f"❌ Fehler bei Migration: {str(e)}")
            raise


def rollback():
    """Migration rückgängig machen"""
    app = create_app()

    with app.app_context():
        try:
            print("🔄 Entferne reset_token Felder...")

            db.session.execute(text("DROP INDEX IF EXISTS idx_users_reset_token"))
            db.session.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS reset_token"))
            db.session.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS reset_token_expires"))

            db.session.commit()
            print("✅ Rollback erfolgreich durchgeführt!")

        except Exception as e:
            db.session.rollback()
            print(f"❌ Fehler bei Rollback: {str(e)}")
            raise


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        print("🔄 Rollback der Migration...")
        rollback()
    else:
        print("🚀 Starte Migration...")
        migrate()
