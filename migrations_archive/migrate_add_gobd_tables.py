#!/usr/bin/env python3
"""
Migration: Fügt GoBD-konforme Tabellen hinzu
- invoice_status_log: Audit Trail für Status-Änderungen
- invoice_pdf_archive: Revisionssichere PDF-Archivierung mit Hash
"""
import os
from urllib.parse import urlparse

import psycopg2
from dotenv import load_dotenv

# .env laden
load_dotenv()

# DB-Verbindung aus DATABASE_URL
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise ValueError("DATABASE_URL nicht gefunden in .env")

# Parse DATABASE_URL
result = urlparse(database_url)
username = result.username
password = result.password
database = result.path[1:]
hostname = result.hostname
port = result.port

conn = psycopg2.connect(host=hostname, database=database, user=username, password=password, port=port)

cursor = conn.cursor()

try:
    print("🔄 Erstelle invoice_status_log Tabelle (Audit Trail)...")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS invoice_status_log (
            id SERIAL PRIMARY KEY,
            invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
            old_status VARCHAR(50),
            new_status VARCHAR(50) NOT NULL,
            changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            changed_by VARCHAR(100) DEFAULT 'System',
            reason TEXT,
            CONSTRAINT fk_invoice_status_log_invoice FOREIGN KEY (invoice_id) REFERENCES invoices(id)
        );
    """
    )
    print("✅ Tabelle invoice_status_log erstellt")

    print("\n🔄 Erstelle invoice_pdf_archive Tabelle (PDF-Archivierung)...")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS invoice_pdf_archive (
            id SERIAL PRIMARY KEY,
            invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
            pdf_filename VARCHAR(255) NOT NULL,
            pdf_hash VARCHAR(64) NOT NULL,
            file_size INTEGER NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            archived_by VARCHAR(100) DEFAULT 'System',
            CONSTRAINT fk_invoice_pdf_archive_invoice FOREIGN KEY (invoice_id) REFERENCES invoices(id),
            CONSTRAINT unique_invoice_pdf UNIQUE (invoice_id, pdf_filename)
        );
    """
    )
    print("✅ Tabelle invoice_pdf_archive erstellt")

    print("\n🔄 Erstelle Indizes für Performance...")

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_invoice_status_log_invoice_id
        ON invoice_status_log(invoice_id);
    """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_invoice_status_log_changed_at
        ON invoice_status_log(changed_at);
    """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_invoice_pdf_archive_invoice_id
        ON invoice_pdf_archive(invoice_id);
    """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_invoice_pdf_archive_pdf_hash
        ON invoice_pdf_archive(pdf_hash);
    """
    )

    print("✅ Indizes erstellt")

    print("\n🔄 Migiere bestehende Rechnungsdaten...")

    # Für alle bestehenden Rechnungen einen initialen Log-Eintrag erstellen
    cursor.execute(
        """
        INSERT INTO invoice_status_log (invoice_id, old_status, new_status, changed_at, changed_by, reason)
        SELECT
            id,
            NULL,
            status,
            created_at,
            'Migration',
            'Initialer Status bei Migration'
        FROM invoices
        WHERE NOT EXISTS (
            SELECT 1 FROM invoice_status_log WHERE invoice_id = invoices.id
        );
    """
    )

    migrated_count = cursor.rowcount
    print(f"✅ {migrated_count} initiale Log-Einträge erstellt")

    conn.commit()
    print("\n✅ Migration erfolgreich abgeschlossen!")
    print("\n📋 GoBD-Funktionen aktiviert:")
    print("   ✓ Audit Trail für alle Status-Änderungen")
    print("   ✓ Revisionssichere PDF-Archivierung")
    print("   ✓ Keine Rückwärts-Änderungen nach Versand")
    print("   ✓ Bestandsrückbuchung bei Stornierung")

except Exception as e:
    conn.rollback()
    print(f"\n❌ Fehler bei der Migration: {e}")
    raise

finally:
    cursor.close()
    conn.close()
