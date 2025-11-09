# 🐳 Docker Deployment Guide

## Voraussetzungen

- Docker & Docker Compose
- Domain mit DNS (A-Record auf Server-IP)
- Cloudflare Account (für DNS Challenge)
- Server mit mindestens 2GB RAM

## 🚀 Schnellstart

### 1. Repository klonen

```bash
git clone <repository-url>
cd rechnungen
```

### 2. Environment konfigurieren

```bash
# .env.docker kopieren und anpassen
cp .env.docker .env

# Wichtige Werte ändern:
nano .env
```

**Pflichtfelder:**

- `DOMAIN` - Deine Domain (z.B. rechnungen.example.com)
- `SECRET_KEY` - Generiere mit:
  `python -c "import secrets; print(secrets.token_hex(32))"`
- `DB_PASSWORD` - Sicheres Datenbank-Passwort
- `CF_API_EMAIL` - Cloudflare E-Mail
- `CF_API_KEY` - Cloudflare Global API Key

### 3. Traefik konfigurieren

```bash
# traefik.yml anpassen
nano traefik/traefik.yml

# Ändere:
# - main: "yourdomain.com" → deine Domain
# - email: "your-email@example.com" → deine E-Mail
```

### 4. Admin-Passwort für Traefik Dashboard generieren

```bash
# htpasswd installieren (falls nicht vorhanden)
sudo apt-get install apache2-utils

# Passwort generieren
echo $(htpasswd -nB admin) | sed -e s/\\$/\\$\\$/g

# Ergebnis in traefik/dynamic/middlewares.yml einfügen
```

### 5. Container starten

```bash
# Build & Start
docker-compose up -d

# Logs verfolgen
docker-compose logs -f app

# Status prüfen
docker-compose ps
```

### 6. Datenbank initialisieren

```bash
# Migrations ausführen
docker-compose exec app flask db upgrade

# Default Admin-User erstellen
docker-compose exec app python -c "
from app import create_app, db
from models import User

app = create_app()
with app.app_context():
    admin = User(username='admin', email='admin@example.com', role='admin', is_active=True)
    admin.set_password('admin123')
    db.session.add(admin)
    db.session.commit()
    print('✓ Admin-User erstellt: admin / admin123')
"
```

### 7. Zugriff testen

```bash
# App
https://your-domain.com

# Traefik Dashboard
https://traefik.your-domain.com
```

## 📦 Services

| Service | Port | Beschreibung | |---------|------|--------------| | app | 8000
| Flask Anwendung | | db | 5432 | PostgreSQL Datenbank | | redis | 6379 |
Session Store | | traefik | 80/443 | Reverse Proxy + TLS | | crowdsec | 8080 |
Security Engine |

## 🔒 Security

### CrowdSec Setup

1. **API Key generieren:**

```bash
docker-compose exec crowdsec cscli bouncers add traefik-bouncer

# Key kopieren und in traefik/dynamic/middlewares.yml einfügen
```

2. **Collections installieren:**

```bash
docker-compose exec crowdsec cscli collections install crowdsecurity/traefik
docker-compose exec crowdsec cscli collections install crowdsecurity/http-cve
docker-compose exec crowdsec cscli collections install crowdsecurity/linux
```

3. **Traefik neu starten:**

```bash
docker-compose restart traefik
```

### Firewall (UFW)

```bash
# Nur SSH, HTTP und HTTPS erlauben
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## 🔄 Updates

### App Update

```bash
# Code aktualisieren
git pull

# Container neu bauen
docker-compose build app

# Neu starten
docker-compose up -d app

# Migrations ausführen (falls nötig)
docker-compose exec app flask db upgrade
```

### System Updates

```bash
# Alle Container stoppen
docker-compose down

# Images aktualisieren
docker-compose pull

# Neu starten
docker-compose up -d
```

## 💾 Backups

### Automatisches Backup-Script

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/backups"
DATE=$(date +%Y%m%d_%H%M%S)

# Datenbank Backup (MySQL/MariaDB)
docker-compose exec -T db mariadb-dump -u rechnungen_user -p${DB_PASSWORD} rechnungen | gzip > "$BACKUP_DIR/db_$DATE.sql.gz"

# Alternativ: PostgreSQL Backup (wenn PostgreSQL-Service aktiv)
# docker-compose exec -T db pg_dump -U rechnungen_user rechnungen | gzip > "$BACKUP_DIR/db_$DATE.sql.gz"

# Files Backup
tar -czf "$BACKUP_DIR/files_$DATE.tar.gz" invoices/ uploads/

# Alte Backups löschen (älter als 30 Tage)
find "$BACKUP_DIR" -name "*.gz" -mtime +30 -delete

echo "✓ Backup erstellt: $DATE"
```

### Cronjob einrichten

```bash
# Crontab bearbeiten
crontab -e

# Täglich um 2 Uhr morgens
0 2 * * * /path/to/backup.sh >> /var/log/rechnungen-backup.log 2>&1
```

### Restore

```bash
# Datenbank wiederherstellen (MySQL/MariaDB)
gunzip -c backup_file.sql.gz | docker-compose exec -T db mariadb -u rechnungen_user -p${DB_PASSWORD} rechnungen

# Alternativ: PostgreSQL Restore
# gunzip -c backup_file.sql.gz | docker-compose exec -T db psql -U rechnungen_user rechnungen

# Files wiederherstellen
tar -xzf files_backup.tar.gz
```

## 🔍 Monitoring

### Container Logs

```bash
# Alle Logs
docker-compose logs -f

# Nur App
docker-compose logs -f app

# Nur Errors
docker-compose logs --tail=100 app | grep ERROR
```

### Resource Usage

```bash
# Container Stats
docker stats

# Disk Usage
docker system df
```

### Health Checks

```bash
# Alle Services prüfen
docker-compose ps

# App Health Check
curl -f https://your-domain.com/health || echo "Health Check failed"
```

## 🐛 Troubleshooting

### Container startet nicht

```bash
# Logs prüfen
docker-compose logs app

# Environment Variablen prüfen
docker-compose exec app env | grep DATABASE_URL
```

### Datenbank-Verbindung fehlgeschlagen

```bash
# DB Status prüfen
docker-compose exec db pg_isready -U rechnungen_user

# Connection String testen
docker-compose exec app python -c "
from sqlalchemy import create_engine
import os
engine = create_engine(os.getenv('DATABASE_URL'))
with engine.connect() as conn:
    print('✓ DB Connection OK')
"
```

### TLS Zertifikat-Fehler

```bash
# Traefik Logs prüfen
docker-compose logs traefik | grep acme

# Zertifikate neu generieren (Vorsicht: Rate Limits!)
rm traefik_certs/acme.json
docker-compose restart traefik
```

### CrowdSec Fehler

```bash
# CrowdSec Status
docker-compose exec crowdsec cscli metrics

# Banned IPs anzeigen
docker-compose exec crowdsec cscli decisions list

# IP entsperren
docker-compose exec crowdsec cscli decisions delete -i 1.2.3.4
```

## 📊 Performance Tuning

### Gunicorn Workers

```dockerfile
# In Dockerfile anpassen:
CMD ["gunicorn", "--workers", "4", ...]

# Formel: (2 x CPU Cores) + 1
# Bei 4 Cores: --workers 9
```

### PostgreSQL Tuning

```yaml
# In docker-compose.yml:
services:
  db:
    command:
      - "postgres"
      - "-c"
      - "max_connections=100"
      - "-c"
      - "shared_buffers=256MB"
      - "-c"
      - "effective_cache_size=1GB"
```

### Redis Memory Limit

```yaml
services:
  redis:
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
```

## 🔐 Sicherheits-Checkliste

- [ ] `.env` mit sicheren Passwörtern
- [ ] SECRET_KEY mindestens 32 Zeichen
- [ ] Traefik Dashboard-Passwort geändert
- [ ] CrowdSec Bouncer eingerichtet
- [ ] Firewall (UFW) aktiviert
- [ ] Backups eingerichtet
- [ ] TLS Zertifikate funktionieren
- [ ] Admin-Passwort geändert (admin/admin123)
- [ ] 2FA für Admin aktiviert

## 📚 Weitere Ressourcen

- [Traefik 3 Docs](https://doc.traefik.io/traefik/)
- [CrowdSec Docs](https://docs.crowdsec.net/)
- [Docker Compose Docs](https://docs.docker.com/compose/)
- [PostgreSQL Performance](https://wiki.postgresql.org/wiki/Performance_Optimization)

## 🆘 Support

Bei Problemen:

1. Logs prüfen: `docker-compose logs`
1. GitHub Issues erstellen
1. [Your Support Contact]
