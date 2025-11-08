#!/usr/bin/env python3
"""
Migration: Fügt product_id und tax_rate Spalten zur line_items Tabelle hinzu
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
    print("🔄 Füge product_id Spalte zu line_items Tabelle hinzu...")
    
    # Prüfen ob Spalte bereits existiert
    cursor.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='line_items' AND column_name='product_id';
    """)
    
    if cursor.fetchone():
        print("⚠️  Spalte product_id existiert bereits in line_items")
    else:
        cursor.execute("""
            ALTER TABLE line_items 
            ADD COLUMN product_id INTEGER REFERENCES products(id);
        """)
        print("✅ Spalte product_id erfolgreich hinzugefügt")
    
    print("\n🔄 Füge tax_rate Spalte zu line_items Tabelle hinzu...")
    
    # Prüfen ob Spalte bereits existiert
    cursor.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='line_items' AND column_name='tax_rate';
    """)
    
    if cursor.fetchone():
        print("⚠️  Spalte tax_rate existiert bereits in line_items")
    else:
        cursor.execute("""
            ALTER TABLE line_items 
            ADD COLUMN tax_rate NUMERIC(5, 2);
        """)
        print("✅ Spalte tax_rate erfolgreich hinzugefügt")
    
    conn.commit()
    print("\n✅ Migration erfolgreich abgeschlossen!")
    
except Exception as e:
    conn.rollback()
    print(f"\n❌ Fehler bei der Migration: {e}")
    raise

finally:
    cursor.close()
    conn.close()
