# Setup Guide: Integrierte Variante mit gemeinsamer Infrastruktur

Für Umgebungen mit bereits vorhandenen Diensten (Traefik, CrowdSec, PostgreSQL,
Redis).

## Voraussetzungen

Folgende Netzwerke müssen bereits existieren:

```bash
docker network ls | grep -E "traefik-proxy|crowdsec|intern-service"
```

Falls nicht vorhanden, erstelle sie:

```bash
docker network create traefik-proxy
docker network create crowdsec
docker network create intern-service
```

## Datenbank-Setup (Shared PostgreSQL)

### Option A: Gemeinsamer PostgreSQL-Container (Empfohlen ✅)

**Vorteile:**

- RAM-effizient (~50MB pro DB statt 200MB pro Container)
- Zentrales Backup
- Einfachere Wartung

**Sicherheit durch DB-Isolation:**

```bash
# In deinem PostgreSQL-Container
docker exec -it postgres psql -U postgres

# SQL ausführen:
CREATE DATABASE rechnungen;
CREATE USER rechnungen_user WITH ENCRYPTED PASSWORD 'sehr_sicheres_passwort';
GRANT ALL PRIVILEGES ON DATABASE rechnungen TO rechnungen_user;

-- Sicherstellen dass User nur seine DB sieht
REVOKE ALL ON DATABASE andere_app_db FROM rechnungen_user;

-- PostgreSQL 15+ benötigt zusätzlich:
\c rechnungen
GRANT ALL ON SCHEMA public TO rechnungen_user;

\q
```

**In .env eintragen:**

```env
# Hostname ist der Container-Name im intern-service Netzwerk
DATABASE_URL=postgresql://rechnungen_user:sehr_sicheres_passwort@postgres:5432/rechnungen
```

### Option B: Separater DB-Container (nur wenn nötig)

Nutze die `docker-compose.yml` (Standalone-Variante) wenn:

- Verschiedene PostgreSQL-Versionen benötigt werden
- Compliance-Anforderungen separate Instanzen fordern
- Hohe Last isoliert werden muss (>10.000 Requests/min)

## Redis-Setup (Optional)

> **Achtung:** `flask-session` ist aktuell nicht in requirements.txt
> enthalten und wird im Code nicht importiert. Die `SESSION_TYPE`/
> `SESSION_REDIS`-Variablen unten haben ohne diesen zusätzlichen
> Einbau **keine Wirkung** -- die App nutzt tatsächlich Standard-
> Client-Cookie-Sessions, unabhängig vom gesetzten Wert (Details:
> AGENTS.md, Abschnitt "Gesetzt, aber wirkungslos"). Wer Redis-Sessions
> tatsächlich nutzen will, muss `flask-session` zuerst in
> requirements.txt aufnehmen und in app.py per `Session(app)`
> initialisieren.

### Wann Redis nutzen?

**File-based Sessions (Standard):**

- ✅ \<1000 gleichzeitige User
- ✅ Single-Server Setup
- ✅ Begrenzter RAM (Sessions ~1KB/User)

**Redis Sessions:**

- ✅ >1000 gleichzeitige User
- ✅ Horizontales Scaling (mehrere App-Container)
- ✅ Session-Sharing zwischen Servern
- ✅ Schnellere Performance bei vielen Sessions

### Redis aktivieren

```bash
# In deinem Redis-Container (falls vorhanden)
docker exec -it redis redis-cli

# DB auswählen (z.B. DB 5 für Rechnungen)
SELECT 5
INFO keyspace
```

**In .env:**

```env
SESSION_TYPE=redis
REDIS_URL=redis://redis:6379/5
```

**In docker-compose.integrated.yml auskommentieren:**

```yaml
# SESSION_TYPE: redis
# SESSION_REDIS: ${REDIS_URL:-redis://redis:6379/0}
```

## Traefik-Konfiguration

Stelle sicher, dass dein Traefik folgendes konfiguriert hat:

**traefik.yml:**

```yaml
providers:
  docker:
    network: traefik-proxy  # Wichtig!
    exposedByDefault: false

entryPoints:
  websecure:
    address: ":443"
    http:
      tls:
        certResolver: letsencrypt
```

**Optional: CrowdSec Bouncer als Middleware:**

```yaml
# dynamic/crowdsec.yml
http:
  middlewares:
    crowdsec-bouncer:
      plugin:
        bouncer:
          enabled: true
          crowdsecLapiKey: ${CROWDSEC_LAPI_KEY}
```

## CrowdSec-Konfiguration

### Logs in CrowdSec einbinden

**In deinem CrowdSec-Container:**

1. **acquis.yaml erweitern:**

```bash
docker exec -it crowdsec vi /etc/crowdsec/acquis.d/rechnungen.yaml
```

```yaml
filenames:
  - /var/log/rechnungen/security.log
labels:
  type: flask
---
filenames:
  - /var/log/rechnungen/app.log
labels:
  type: syslog
```

2. **Log-Verzeichnis mounten:**

In deinem CrowdSec docker-compose.yml:

```yaml
crowdsec:
  volumes:
    # Bestehende Volumes...
    - /path/to/rechnungen/logs:/var/log/rechnungen:ro
```

3. **Flask-Parser installieren:**

```bash
docker exec crowdsec cscli parsers install crowdsecurity/flask-logs
docker restart crowdsec
```

## Deployment

### 1. Environment-Variablen

Erstelle `.env` basierend auf `.env.example`:

```bash
cp .env.example .env
nano .env
```

**Wichtige Variablen:**

```env
# Datenbank (Shared PostgreSQL)
DATABASE_URL=postgresql://rechnungen_user:passwort@postgres:5432/rechnungen

# Session (File-based oder Redis)
SESSION_TYPE=filesystem
# SESSION_REDIS=redis://redis:6379/5

# Secrets (generiere neue!)
SECRET_KEY=<generiere mit: openssl rand -hex 32>
# JWT_SECRET_KEY wird gesetzt, aber jwt_api.py signiert/verifiziert
# Tokens tatsächlich mit SECRET_KEY (siehe AGENTS.md) -- eine separate
# JWT_SECRET_KEY hat aktuell keine Wirkung.

# Domain
DOMAIN=rechnungen.deine-domain.de

# ... Rest siehe .env.example
```

### 2. App starten

```bash
# Integrierte Variante
docker-compose -f docker-compose.integrated.yml up -d

# Logs prüfen
docker-compose -f docker-compose.integrated.yml logs -f app
```

### 3. Datenbank initialisieren

```bash
# Tabellen erstellen + Standard-Admin (admin/admin) + Marktstand-Kunde
docker-compose -f docker-compose.integrated.yml exec app flask init-db

# Alembic-Migrationen anwenden (siehe MIGRATIONS.md)
docker-compose -f docker-compose.integrated.yml exec app alembic upgrade head
```

**Hinweis:** Die einzelnen `migrate_add_*.py`-Skripte existieren nicht mehr als
eigenständig lauffähige Migrationen -- sie liegen archiviert in
`migrations_archive/` (siehe MIGRATIONS.md). Schema-Änderungen laufen
ausschließlich über Alembic. Nach dem ersten Login mit `admin`/`admin`
sofort das Passwort ändern.

### 4. Testen

```bash
# App erreichbar?
curl -I https://rechnungen.deine-domain.de

# Datenbank-Verbindung?
docker-compose -f docker-compose.integrated.yml exec app python -c "
from app import create_app
app = create_app()
with app.app_context():
    from models import User
    print(f'Users: {User.query.count()}')
"
```

## Backup-Strategie

### Datenbank (Shared PostgreSQL)

**Tägliches Backup:**

```bash
# MySQL/MariaDB Backup (in deinem Backup-Script ergänzen):
docker exec mysql mariadb-dump -u rechnungen_user -p${DB_PASSWORD} rechnungen | gzip > /backups/rechnungen_$(date +\%Y\%m\%d).sql.gz

# Alternativ: PostgreSQL Backup
# docker exec postgres pg_dump -U rechnungen_user rechnungen | gzip > /backups/rechnungen_$(date +\%Y\%m\%d).sql.gz

# 10 Jahre aufbewahren (GoBD-konform)
find /backups/rechnungen_*.sql.gz -mtime +3650 -delete
```

**Point-in-Time Recovery (MySQL/MariaDB):**

```bash
# Binary Logging aktivieren (in deinem MySQL/MariaDB-Container)
# /etc/mysql/my.cnf:
[mysqld]
log_bin = /var/log/mysql/mysql-bin.log
binlog_expire_logs_seconds = 864000  # 10 Tage
server_id = 1
```

**Point-in-Time Recovery (PostgreSQL):**

```bash
# WAL-Archivierung aktivieren (in deinem PostgreSQL-Container)
# postgresql.conf:
archive_mode = on
archive_command = 'cp %p /archive/%f'
wal_level = replica
```

### Dateien

```bash
# PDFs und Uploads
tar -czf rechnungen_files_$(date +%Y%m%d).tar.gz \
    invoices/ \
    uploads/ \
    logs/

# Auf Backup-Server kopieren
rsync -avz rechnungen_files_*.tar.gz backup-server:/backups/
```

## Monitoring

### Ressourcen-Überwachung

```bash
# App-Container
docker stats rechnungen-app

# PostgreSQL-Queries
docker exec postgres psql -U rechnungen_user rechnungen -c "
SELECT pid, usename, application_name, state, query
FROM pg_stat_activity
WHERE datname = 'rechnungen';
"
```

### CrowdSec-Entscheidungen

```bash
# Geblockte IPs anzeigen
docker exec crowdsec cscli decisions list

# Metriken
docker exec crowdsec cscli metrics

# Alert-Verhalten
docker exec crowdsec cscli alerts list --origin rechnungen
```

## Skalierung

### Horizontales Scaling (mehrere App-Container)

**Voraussetzung:** Redis für Session-Sharing -- setzt voraus, dass
`flask-session` zuerst tatsächlich eingebaut wird (siehe Warnhinweis im
Redis-Abschnitt oben). Ohne diesen Einbau laufen mehrere Replicas mit
inkonsistenten Client-Cookie-Sessions.

```yaml
# docker-compose.integrated.yml erweitern:
services:
  app:
    deploy:
      replicas: 3
    environment:
      SESSION_TYPE: redis
      REDIS_URL: redis://redis:6379/5
```

**Traefik übernimmt automatisch Load-Balancing.**

### Vertikales Scaling

```yaml
# Ressourcen-Limits setzen
services:
  app:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 1G
        reservations:
          cpus: '0.5'
          memory: 512M
```

## Troubleshooting

### App kann nicht auf DB zugreifen

```bash
# Prüfe Netzwerk-Verbindung
docker exec rechnungen-app ping -c 3 postgres

# Prüfe DB-User
docker exec postgres psql -U postgres -c "\du"

# Teste Connection-String
docker exec rechnungen-app python -c "
import os
from sqlalchemy import create_engine
engine = create_engine(os.getenv('DATABASE_URL'))
conn = engine.connect()
print('✓ DB Connection OK')
"
```

### CrowdSec blockiert legitime IPs

```bash
# IP entfernen
docker exec crowdsec cscli decisions delete --ip 192.168.1.100

# Whitelist hinzufügen
docker exec crowdsec cscli decisions add --ip 192.168.1.100 --type allow
```

### Sessions gehen verloren

```bash
# File-based: Prüfe Permissions
docker exec rechnungen-app ls -la /app/flask_session

# Redis: Prüfe Verbindung
docker exec rechnungen-app python -c "
import redis
r = redis.from_url('redis://redis:6379/5')
print(r.ping())
"
```

## Updates

```bash
# App aktualisieren
git pull
docker-compose -f docker-compose.integrated.yml build --no-cache
docker-compose -f docker-compose.integrated.yml up -d

# Migrationen prüfen
docker-compose -f docker-compose.integrated.yml exec app python -c "
from app import create_app
app = create_app()
# Führe Migrationen aus falls nötig
"
```

## Sicherheits-Checkliste

- [ ] PostgreSQL-User hat nur Zugriff auf eigene DB
- [ ] `.env` nicht in Git committed (`*.env` in `.gitignore`)
- [ ] Secrets mit `openssl rand -hex 32` generiert
- [ ] CrowdSec parst `logs/security.log`
- [ ] Traefik-Middleware für Rate-Limiting aktiv
- [ ] Backups laufen täglich (10 Jahre Aufbewahrung)
- [ ] HTTPS mit Let's Encrypt aktiv
- [ ] Admin-Passwort geändert (nicht Standard!)
- [ ] 2FA für Admin-Account aktiviert

## Ressourcen-Verbrauch

**Shared-Setup (Empfohlen):**

- App: ~200MB RAM
- Anteil an shared PostgreSQL: ~50MB
- Anteil an shared Redis: ~20MB (optional)
- **Gesamt: ~250MB pro App**

**Standalone-Setup:**

- App: ~200MB
- PostgreSQL: ~200MB
- Redis: ~50MB (optional)
- **Gesamt: ~450MB pro App**

**Bei 5 Apps:**

- Shared: ~1.25GB + 200MB (PostgreSQL) + 100MB (Redis) = **~1.5GB**
- Standalone: ~2.25GB = **~2.25GB**

**Ersparnis: ~750MB RAM** 🎉
