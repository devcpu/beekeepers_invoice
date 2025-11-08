"""
Migrationsskript für Lieferscheine und Kommissionslager
Erstellt die Tabellen: delivery_notes, delivery_note_items, consignment_stock
"""

from sqlalchemy import text

from app import create_app
from models import db


def migrate():
    """Führt die Migration aus"""
    app = create_app()

    with app.app_context():
        try:
            # SQL für alle drei Tabellen
            sql = text(
                """
            -- Tabelle für Lieferscheine
            CREATE TABLE IF NOT EXISTS delivery_notes (
                id SERIAL PRIMARY KEY,
                delivery_note_number VARCHAR(50) UNIQUE NOT NULL,
                customer_id INTEGER NOT NULL REFERENCES customers(id),
                delivery_date DATE DEFAULT CURRENT_DATE NOT NULL,
                status VARCHAR(20) DEFAULT 'delivered',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Tabelle für Lieferschein-Positionen
            CREATE TABLE IF NOT EXISTS delivery_note_items (
                id SERIAL PRIMARY KEY,
                delivery_note_id INTEGER NOT NULL REFERENCES delivery_notes(id),
                product_id INTEGER NOT NULL REFERENCES products(id),
                description VARCHAR(500) NOT NULL,
                quantity NUMERIC(10, 2) NOT NULL DEFAULT 1.00,
                unit_price NUMERIC(10, 2) NOT NULL,
                total NUMERIC(10, 2) NOT NULL,
                position INTEGER DEFAULT 0
            );

            -- Tabelle für Kommissionslager beim Reseller
            CREATE TABLE IF NOT EXISTS consignment_stock (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER NOT NULL REFERENCES customers(id),
                product_id INTEGER NOT NULL REFERENCES products(id),
                quantity INTEGER DEFAULT 0 NOT NULL,
                unit_price NUMERIC(10, 2) NOT NULL,
                last_delivery_note_id INTEGER REFERENCES delivery_notes(id),
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT unique_customer_product UNIQUE (customer_id, product_id)
            );

            -- Indizes für bessere Performance
            CREATE INDEX IF NOT EXISTS idx_delivery_notes_number ON delivery_notes(delivery_note_number);
            CREATE INDEX IF NOT EXISTS idx_delivery_notes_customer ON delivery_notes(customer_id);
            CREATE INDEX IF NOT EXISTS idx_delivery_notes_date ON delivery_notes(delivery_date);

            CREATE INDEX IF NOT EXISTS idx_delivery_note_items_dn ON delivery_note_items(delivery_note_id);
            CREATE INDEX IF NOT EXISTS idx_delivery_note_items_product ON delivery_note_items(product_id);

            CREATE INDEX IF NOT EXISTS idx_consignment_stock_customer ON consignment_stock(customer_id);
            CREATE INDEX IF NOT EXISTS idx_consignment_stock_product ON consignment_stock(product_id);
            """
            )

            db.session.execute(sql)
            db.session.commit()

            print("✅ Migration erfolgreich abgeschlossen!")
            print("\nErstellte Tabellen:")
            print("   - delivery_notes (Lieferscheine)")
            print("   - delivery_note_items (Lieferschein-Positionen)")
            print("   - consignment_stock (Kommissionslager)")
            print("\nErstellte Indizes:")
            print("   - idx_delivery_notes_number, customer, date")
            print("   - idx_delivery_note_items_dn, product")
            print("   - idx_consignment_stock_customer, product")

        except Exception as e:
            db.session.rollback()
            print(f"❌ Fehler bei der Migration: {str(e)}")
            return False

        return True


if __name__ == "__main__":
    print("=" * 60)
    print("Migration: Lieferscheine & Kommissionslager")
    print("=" * 60)
    print("\nStarte Migration...")
    print()

    success = migrate()

    if success:
        print("\n" + "=" * 60)
        print("✅ Migration erfolgreich abgeschlossen!")
        print("=" * 60)
        print("\nSie können jetzt:")
        print("  - Lieferscheine erstellen (/delivery-notes/new)")
        print("  - Kommissionslager verwalten (/consignment/<customer_id>)")
        print("  - Rechnungen aus Kommissionslager generieren")
    else:
        print("\n" + "=" * 60)
        print("❌ Migration fehlgeschlagen!")
        print("=" * 60)
