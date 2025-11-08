"""
Migrationsscript zum Hinzufügen der Products-Tabelle
"""

from sqlalchemy import text

from app import create_app
from models import db

app = create_app()

with app.app_context():
    # Products-Tabelle erstellen
    db.session.execute(
        text(
            """
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            number INTEGER DEFAULT 0,
            quantity VARCHAR(50),
            price NUMERIC(10, 2) NOT NULL,
            lot_number VARCHAR(100),
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """
        )
    )
    db.session.commit()

    print("✓ Products-Tabelle erfolgreich erstellt!")
