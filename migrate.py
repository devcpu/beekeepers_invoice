#!/usr/bin/env python3
"""
Intelligentes Migrations-Tool
Liest automatisch DB-Credentials aus .env und führt Migrationen aus
"""
import os
import sys
import subprocess
from pathlib import Path
from urllib.parse import urlparse

def load_env():
    """Liest .env Datei und gibt DATABASE_URL zurück"""
    env_path = Path(__file__).parent / '.env'
    if not env_path.exists():
        print("❌ .env Datei nicht gefunden!")
        sys.exit(1)
    
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith('DATABASE_URL='):
                return line.split('=', 1)[1]
    
    print("❌ DATABASE_URL nicht in .env gefunden!")
    sys.exit(1)

def parse_db_url(url):
    """Parst DATABASE_URL und gibt Komponenten zurück"""
    parsed = urlparse(url)
    return {
        'user': parsed.username,
        'password': parsed.password,
        'host': parsed.hostname or 'localhost',
        'port': parsed.port or 5432,
        'database': parsed.path.lstrip('/')
    }

def run_sql(db_config, sql, description="SQL ausführen"):
    """Führt SQL-Befehl aus"""
    env = os.environ.copy()
    env['PGPASSWORD'] = db_config['password']
    
    cmd = [
        'psql',
        '-U', db_config['user'],
        '-d', db_config['database'],
        '-h', db_config['host'],
        '-p', str(db_config['port']),
        '-c', sql
    ]
    
    print(f"🔄 {description}...")
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"❌ Fehler: {result.stderr}")
        return False
    
    print(f"✓ {description} erfolgreich")
    if result.stdout.strip():
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                print(f"  {line}")
    return True

def verify_column(db_config, table, column):
    """Verifiziert, dass eine Spalte existiert"""
    env = os.environ.copy()
    env['PGPASSWORD'] = db_config['password']
    
    cmd = [
        'psql',
        '-U', db_config['user'],
        '-d', db_config['database'],
        '-h', db_config['host'],
        '-p', str(db_config['port']),
        '-t',  # Nur Daten, keine Header
        '-c', f"SELECT column_name, data_type, column_default FROM information_schema.columns WHERE table_name='{table}' AND column_name='{column}';"
    ]
    
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    
    if result.returncode == 0 and result.stdout.strip():
        print(f"✓ Spalte {table}.{column} verifiziert:")
        print(f"  {result.stdout.strip()}")
        return True
    else:
        print(f"❌ Spalte {table}.{column} nicht gefunden!")
        return False

def add_totp_required():
    """Migration: Fügt totp_required Spalte hinzu"""
    print("\n=== Migration: totp_required Spalte ===\n")
    
    db_url = load_env()
    db_config = parse_db_url(db_url)
    
    print(f"📊 Verbinde mit: {db_config['database']}@{db_config['host']}\n")
    
    # Migration ausführen
    sql = "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_required BOOLEAN DEFAULT FALSE;"
    if not run_sql(db_config, sql, "totp_required Spalte hinzufügen"):
        sys.exit(1)
    
    # Verifizieren
    print()
    if not verify_column(db_config, 'users', 'totp_required'):
        sys.exit(1)
    
    print("\n✅ Migration erfolgreich abgeschlossen!\n")

def add_customer_reseller():
    """Migration: Fügt reseller Spalte zur customers Tabelle hinzu"""
    print("\n=== Migration: customer reseller Flag ===\n")
    
    db_url = load_env()
    db_config = parse_db_url(db_url)
    
    print(f"📊 Verbinde mit: {db_config['database']}@{db_config['host']}\n")
    
    # Migration ausführen
    sql = "ALTER TABLE customers ADD COLUMN IF NOT EXISTS reseller BOOLEAN DEFAULT FALSE;"
    if not run_sql(db_config, sql, "reseller Spalte hinzufügen"):
        sys.exit(1)
    
    # Verifizieren
    print()
    if not verify_column(db_config, 'customers', 'reseller'):
        sys.exit(1)
    
    print("\n✅ Migration erfolgreich abgeschlossen!\n")

def show_usage():
    """Zeigt Hilfe an"""
    print("""
Verwendung: python migrate.py [migration]

Verfügbare Migrationen:
  totp_required      - Fügt totp_required Spalte zu users Tabelle hinzu
  customer_reseller  - Fügt reseller Spalte zu customers Tabelle hinzu

Beispiel:
  python migrate.py customer_reseller
    """)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        show_usage()
        sys.exit(1)
    
    migration = sys.argv[1]
    
    if migration == 'totp_required':
        add_totp_required()
    elif migration == 'customer_reseller':
        add_customer_reseller()
    else:
        print(f"❌ Unbekannte Migration: {migration}")
        show_usage()
        sys.exit(1)
