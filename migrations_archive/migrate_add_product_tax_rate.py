#!/usr/bin/env python3
"""
Migration: Fügt tax_rate Spalte zur products Tabelle hinzu und show_tax zu delivery_notes
"""
import os
from dotenv import load_dotenv
import psycopg2
from urllib.parse import urlparse

# .env laden
load_dotenv()

# DB-Verbindung aus DATABASE_URL
database_url = os.getenv('DATABASE_URL')
if not database_url:
    raise ValueError("DATABASE_URL nicht gefunden in .env")

# Parse DATABASE_URL
result = urlparse(database_url)
username = result.username
password = result.password
database = result.path[1:]
hostname = result.hostname
port = result.port

conn = psycopg2.connect(
    host=hostname,
    database=database,
    user=username,
    password=password,
    port=port
)

cursor = conn.cursor()

try:
    print("🔄 Füge tax_rate Spalte zu products Tabelle hinzu...")
    
    # Prüfen ob Spalte bereits existiert
    cursor.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='products' AND column_name='tax_rate';
    """)
    
    if cursor.fetchone():
        print("⚠️  Spalte tax_rate existiert bereits in products")
    else:
        cursor.execute("""
            ALTER TABLE products 
            ADD COLUMN tax_rate NUMERIC(5, 2) DEFAULT 7.80;
        """)
        print("✅ Spalte tax_rate erfolgreich hinzugefügt (Standard: 7.80%)")
    
    print("\n🔄 Füge show_tax Spalte zu delivery_notes Tabelle hinzu...")
    
    # Prüfen ob Spalte bereits existiert
    cursor.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='delivery_notes' AND column_name='show_tax';
    """)
    
    if cursor.fetchone():
        print("⚠️  Spalte show_tax existiert bereits in delivery_notes")
    else:
        cursor.execute("""
            ALTER TABLE delivery_notes 
            ADD COLUMN show_tax BOOLEAN DEFAULT FALSE;
        """)
        print("✅ Spalte show_tax erfolgreich hinzugefügt (Standard: FALSE)")
    
    conn.commit()
    print("\n✅ Migration erfolgreich abgeschlossen!")
    
except Exception as e:
    conn.rollback()
    print(f"\n❌ Fehler bei der Migration: {e}")
    raise

finally:
    cursor.close()
    conn.close()
