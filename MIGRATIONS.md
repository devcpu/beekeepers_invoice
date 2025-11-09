# Datenbank-Migrationen mit Alembic

Dieses Projekt verwendet **Alembic** für datenbank-agnostische
Schema-Migrationen.

## Warum Alembic?

✅ **Datenbank-agnostisch**: Unterstützt PostgreSQL, MySQL, SQLite, MariaDB, etc.
✅ **Versionierung**: Jede Schema-Änderung wird versioniert und kann
zurückgerollt werden ✅ **Automatische Generierung**: Migrationen werden aus
Models automatisch erstellt ✅ **Team-fähig**: Migrations-Historie im Git für
alle Entwickler ✅ **Production-safe**: Migrationen können sicher auf Produktion
angewendet werden

## Unterstützte Datenbanken

| Datenbank | Connection String Beispiel |
|-----------|----------------------------| | **PostgreSQL** |
`postgresql://user:pass@localhost:5432/dbname` | | **MySQL** |
`mysql+pymysql://user:pass@localhost:3306/dbname` | | **MariaDB** |
`mysql+pymysql://user:pass@localhost:3306/dbname` | | **SQLite** |
`sqlite:///path/to/database.db` |

**Hinweis:** Für MySQL/MariaDB muss `pymysql` installiert sein (bereits in
`requirements.txt`).

______________________________________________________________________

## Erste Einrichtung

### Neue Installation (leere Datenbank)

```bash
# 1. Datenbank erstellen (falls noch nicht vorhanden)
# PostgreSQL:
sudo -u postgres psql -c "CREATE DATABASE rechnungen;"

# MySQL:
mysql -u root -p -e "CREATE DATABASE rechnungen CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 2. DATABASE_URL in .env setzen
# PostgreSQL:
DATABASE_URL=postgresql://user:pass@localhost:5432/rechnungen

# MySQL:
DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/rechnungen

# 3. Migrationen anwenden
alembic upgrade head
```

### Migration von altem System (mit flask init-db)

Wenn du bereits eine Datenbank mit `flask init-db` erstellt hast:

```bash
# Option 1: Alembic "vortäuschen", dass Migrationen bereits angewendet wurden
alembic stamp head

# Option 2: Datenbank neu aufsetzen
flask init-db  # Oder Backup einspielen
alembic stamp head
```

______________________________________________________________________

## Tägliche Verwendung

### Neue Migration erstellen

Wenn du `models.py` änderst (neue Felder, Tabellen, etc.):

```bash
# 1. Automatisch Migration aus Model-Änderungen generieren
alembic revision --autogenerate -m "Beschreibung der Änderung"

# Beispiele:
alembic revision --autogenerate -m "Add customer birthday field"
alembic revision --autogenerate -m "Create notifications table"
alembic revision --autogenerate -m "Add index on invoice_number"

# 2. Migration auf Datenbank anwenden
alembic upgrade head
```

**Wichtig:** Prüfe die generierte Migration in `alembic/versions/` - Alembic ist
sehr gut, aber nicht perfekt!

### Migration rückgängig machen

```bash
# Eine Version zurück
alembic downgrade -1

# Zu spezifischer Version
alembic downgrade <revision_id>

# Alles zurücksetzen (VORSICHT!)
alembic downgrade base
```

### Migrations-Historie anzeigen

```bash
# Aktuelle Version
alembic current

# Alle Migrationen
alembic history

# Detaillierte Ansicht
alembic history --verbose
```

______________________________________________________________________

## Beispiele

### Beispiel 1: Neues Feld hinzufügen

```python
# In models.py
class Customer(db.Model):
    # ... existing fields ...
    birthday = db.Column(db.Date, nullable=True)  # NEU
```

```bash
# Migration generieren und anwenden
alembic revision --autogenerate -m "Add customer birthday field"
alembic upgrade head
```

### Beispiel 2: Index erstellen

```python
# In models.py
class Invoice(db.Model):
    # ... existing fields ...
    invoice_number = db.Column(db.String(50), unique=True, nullable=False, index=True)  # index=True hinzugefügt
```

```bash
alembic revision --autogenerate -m "Add index on invoice_number"
alembic upgrade head
```

### Beispiel 3: Neue Tabelle

```python
# In models.py
class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

```bash
alembic revision --autogenerate -m "Create notifications table"
alembic upgrade head
```

______________________________________________________________________

## Datenbank wechseln (PostgreSQL → MySQL)

### Schritt 1: MySQL vorbereiten

```bash
# Datenbank erstellen
mysql -u root -p -e "CREATE DATABASE rechnungen CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# User erstellen
mysql -u root -p -e "CREATE USER 'rechnungen_user'@'localhost' IDENTIFIED BY 'sicheres_passwort';"
mysql -u root -p -e "GRANT ALL PRIVILEGES ON rechnungen.* TO 'rechnungen_user'@'localhost';"
```

### Schritt 2: .env anpassen

```env
# Alt (PostgreSQL):
DATABASE_URL=postgresql://user:pass@localhost:5432/rechnungen

# Neu (MySQL):
DATABASE_URL=mysql+pymysql://rechnungen_user:sicheres_passwort@localhost:3306/rechnungen
```

### Schritt 3: Schema auf MySQL anwenden

```bash
# Migrationen auf neue Datenbank anwenden
alembic upgrade head
```

### Schritt 4: Daten migrieren (optional)

```bash
# PostgreSQL Export
pg_dump -U user -d rechnungen --data-only --inserts > data.sql

# Daten anpassen (PostgreSQL → MySQL Syntax)
sed -i 's/public\.//g' data.sql
sed -i 's/::.*//g' data.sql

# In MySQL importieren
mysql -u rechnungen_user -p rechnungen < data.sql
```

**Tipp:** Für große Datenmengen Tools wie `pgloader` verwenden:

```bash
pgloader postgresql://user:pass@localhost/rechnungen mysql://user:pass@localhost/rechnungen
```

______________________________________________________________________

## Troubleshooting

### "Target database is not up to date"

```bash
# Aktuellen Stand prüfen
alembic current

# Auf neueste Version aktualisieren
alembic upgrade head
```

### "Can't locate revision identified by ..."

```bash
# Migrations-Historie neu synchronisieren
alembic stamp head
```

### "ENUM type not found" (MySQL)

ENUMs wurden mit `native_enum=False` konfiguriert und verwenden VARCHAR statt
native ENUMs. Das funktioniert auf allen Datenbanken.

### Migration schlägt fehl

```bash
# Migration-Datei in alembic/versions/ manuell anpassen
# Dann erneut versuchen:
alembic upgrade head

# Oder Migration überspringen (wenn bereits manuell angewendet):
alembic stamp head
```

______________________________________________________________________

## Migration von alten migrate\_\*.py Scripts

Die alten Migrations-Scripts in `migrations_archive/` sind **archiviert** aber
nicht gelöscht:

```bash
# Alte Migrationen (manuell, nicht mehr verwendet):
migrations_archive/
├── migrate_add_products.py
├── migrate_add_consignment.py
├── migrate_add_gobd_tables.py
├── migrate_add_reminders.py
├── migrate_add_payment_checks.py
└── ...

# Neue Migrationen (Alembic, ab sofort):
alembic/
└── versions/
    └── 352cafa6cd86_initial_schema_from_models.py
```

**Warum archiviert?**

- Git-Historie bleibt erhalten
- Referenz für manuelle Anpassungen
- Dokumentation der Schema-Evolution

**Neue Änderungen:** Nur noch mit Alembic (`alembic revision --autogenerate`)

______________________________________________________________________

## Best Practices

1. **Immer prüfen**: Generierte Migrationen vor dem Anwenden prüfen
1. **Sinnvolle Namen**: `alembic revision -m "Was ändert sich"`
1. **Kleine Schritte**: Lieber mehrere kleine Migrationen als eine große
1. **Testen**: Migration erst auf Dev/Staging testen, dann Produktion
1. **Backup**: Vor Produktion-Migrationen immer Backup erstellen
1. **Nie manuell ändern**: Schema-Änderungen nur über Alembic, nie direkt in DB
1. **Git commit**: Migrations-Dateien immer committen

______________________________________________________________________

## Produktions-Deployment

```bash
# 1. Backup erstellen
pg_dump -U user rechnungen > backup_$(date +%Y%m%d_%H%M%S).sql

# 2. Neue Version deployen (Code + Migrations)
git pull origin main

# 3. Abhängigkeiten aktualisieren
pip install -r requirements.txt

# 4. Migrationen anwenden
alembic upgrade head

# 5. Anwendung neu starten
systemctl restart rechnungen
# Oder: docker-compose restart app
```

**Mit Docker:**

```bash
docker-compose exec app alembic upgrade head
docker-compose restart app
```

______________________________________________________________________

## Referenzen

- **Alembic Dokumentation**: https://alembic.sqlalchemy.org/
- **SQLAlchemy Typen**: https://docs.sqlalchemy.org/en/20/core/type_basics.html
- **Migration Patterns**: https://alembic.sqlalchemy.org/en/latest/cookbook.html
