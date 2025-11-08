# Rechnungsverwaltung mit Flask

Eine webbasierte Rechnungsverwaltung mit manipulationssicherer Datenspeicherung, PDF-Export und E-Mail-Integration.

## Features

✅ **Manipulationssichere Datenspeicherung**
- Alle Rechnungen werden mit SHA-256 Hash gesichert
- Integritätsprüfung bei jedem Abruf
- Warnung bei manipulierten Daten

✅ **Vollständige Rechnungsverwaltung**
- Kunden- und Rechnungsdatenbank
- Übersichtliches Dashboard
- Statusverwaltung (Entwurf, Versendet, Bezahlt, Storniert)

✅ **PDF-Export**
- Professionelle PDF-Rechnungen
- Automatische Berechnung von MwSt.
- Integritätshash im PDF enthalten

✅ **E-Mail-Schnittstelle**
- Import von Bestellungen aus E-Mails
- Erweiterbar für verschiedene Shop-Systeme
- Automatische Kundenerkennung

✅ **JWT-API für PWA/Mobile Apps**
- Token-basierte Authentifizierung
- 30 Tage Gültigkeit
- 2FA-Support
- REST API für Rechnungen, Kunden, POS

✅ **Passwort-Reset per E-Mail**
- Sichere Token-Generierung
- 1 Stunde Gültigkeit
- HTML/Text E-Mails

✅ **CrowdSec Integration**
- Automatische Sicherheitslogging
- Bruteforce-Schutz
- SQL-Injection/XSS-Erkennung
- Rate-Limiting

✅ **Alembic Migrationen**
- Datenbank-agnostisch (PostgreSQL, MySQL, SQLite)
- Automatische Schema-Generierung aus Models
- Versionierung und Rollback
- Team-fähig

## Technologie-Stack

- **Backend:** Flask 3.0, SQLAlchemy, Flask-Login, PyJWT
- **Datenbank:** PostgreSQL, MySQL, MariaDB, SQLite (via Alembic)
- **Migrationen:** Alembic 1.13
- **PDF-Generierung:** ReportLab
- **E-Mail:** Python IMAP, Flask-Mail
- **Security:** CrowdSec, 2FA (TOTP)
- **Deployment:** Docker, Traefik 3, Gunicorn

## Installation

### Variante 1: Docker-Deployment (Standalone)

Komplette Infrastruktur mit einem Befehl - alle Dienste inkludiert:

```bash
# Repository klonen
cd /home/janusz/git/privat/rechnungen

# .env Datei konfigurieren
cp .env.example .env
nano .env

# Container starten
docker-compose up -d

# Datenbank initialisieren
docker-compose exec app flask init-db

# Optional: Testdaten
docker-compose exec app flask seed-db
```

**Enthaltene Services:**
- **app**: Flask-Anwendung mit Gunicorn + Gevent
- **db**: PostgreSQL 15
- **traefik**: Reverse Proxy mit automatischem TLS (Let's Encrypt)
- **crowdsec**: Security Engine für Bruteforce-Schutz
- **redis** (optional): Session-Store für horizontales Scaling (>1000 Nutzer)

**Standard-Konfiguration:**
- File-based Sessions (ausreichend für <1000 Nutzer)
- Redis auskommentiert (kann aktiviert werden bei Bedarf)
- Traefik lauscht auf Port 80/443
- CrowdSec-Log-Parsing für automatische IP-Sperren

**Erste Schritte:**
1. Domain in `.env` setzen: `DOMAIN=ihr-server.de`
2. E-Mail für Let's Encrypt: `ACME_EMAIL=admin@ihr-server.de`
3. `docker-compose up -d`
4. App läuft unter: `https://ihr-server.de`

**Redis aktivieren (bei Bedarf):**
```yaml
# In docker-compose.yml auskommentieren:
redis:
  image: redis:7-alpine
  # ...

# In app service ändern:
SESSION_TYPE: redis
REDIS_URL: redis://redis:6379
```

---

### Variante 2: Integrierte Variante (Shared Infrastructure)

Für Umgebungen mit **bereits vorhandenen Diensten** (Traefik, CrowdSec, PostgreSQL, Redis):

```bash
# Repository klonen
cd /home/janusz/git/privat/rechnungen

# .env für integrierte Variante
cp .env.integrated.example .env
nano .env

# Datenbank im shared PostgreSQL anlegen
docker exec postgres psql -U postgres -c "
CREATE DATABASE rechnungen;
CREATE USER rechnungen_user WITH PASSWORD 'sicheres_passwort';
GRANT ALL PRIVILEGES ON DATABASE rechnungen TO rechnungen_user;
"

# Container starten (nutzt externe Netzwerke)
docker-compose -f docker-compose.integrated.yml up -d

# Datenbank initialisieren
docker-compose -f docker-compose.integrated.yml exec app flask init-db
```

**Voraussetzungen:**
- Externe Netzwerke: `traefik-proxy`, `crowdsec`, `intern-service`
- Shared PostgreSQL im `intern-service` Netzwerk
- Traefik mit Let's Encrypt läuft bereits
- CrowdSec konfiguriert (optional)

**Vorteile:**
- ✅ **RAM-effizient**: ~750MB Ersparnis bei 5 Apps (shared DB statt 5x separate DBs)
- ✅ **Zentrales Backup**: Ein PostgreSQL-Dump für alle DBs
- ✅ **Einfachere Wartung**: Updates nur 1x durchführen
- ✅ **Sicherheit**: DB-Isolation via separate Datenbanken + User

**Shared vs. Dedicated DB:**

| Aspekt | Shared PostgreSQL ✅ | Dedicated DB |
|--------|---------------------|--------------|
| RAM-Verbrauch | ~50MB/App | ~200MB/App |
| Sicherheit | DB-Level Isolation | Container-Level |
| Backup | Zentral, einfach | Pro App separat |
| Skalierung | Bis ~10k Req/min | Unbegrenzt |
| Empfohlen für | <5 Apps, begrenzter RAM | High-Traffic, Compliance |

**Detaillierte Anleitung:** Siehe [SETUP_INTEGRATED.md](SETUP_INTEGRATED.md)

---

### Variante 3: Manuelle Installation

Für Entwicklung oder kleine Deployments ohne Docker:

#### 1. Voraussetzungen

- Python 3.9+
- PostgreSQL 12+
- pip und virtualenv
- (Optional) CrowdSec für Security-Logging

#### 2. Repository klonen und einrichten

```bash
cd /home/janusz/git/privat/rechnungen

# Virtuelle Umgebung erstellen
python3 -m venv venv
source venv/bin/activate

# Abhängigkeiten installieren
pip install -r requirements.txt
```

### 3. Datenbank erstellen

#### PostgreSQL

```bash
# Als postgres-User
sudo -u postgres psql

# In der PostgreSQL-Konsole:
CREATE DATABASE rechnungen;
CREATE USER rechnungen_user WITH PASSWORD 'sicheres_passwort';
GRANT ALL PRIVILEGES ON DATABASE rechnungen TO rechnungen_user;
\q
```

#### MySQL

```bash
# Als root-User anmelden
sudo mysql

# Oder mit Passwort:
mysql -u root -p

# In der MySQL-Konsole:
CREATE DATABASE rechnungen CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'rechnungen_user'@'localhost' IDENTIFIED BY 'sicheres_passwort';
GRANT ALL PRIVILEGES ON rechnungen.* TO 'rechnungen_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

#### MariaDB

```bash
# Als root-User anmelden
sudo mariadb

# Oder mit Passwort:
mariadb -u root -p

# In der MariaDB-Konsole:
CREATE DATABASE rechnungen CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'rechnungen_user'@'localhost' IDENTIFIED BY 'sicheres_passwort';
GRANT ALL PRIVILEGES ON rechnungen.* TO 'rechnungen_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

**Hinweis:** MySQL/MariaDB verwenden `utf8mb4` für vollständige Unicode-Unterstützung (inkl. Emojis).

### 4. Umgebungsvariablen konfigurieren

```bash
cp .env.example .env
nano .env
```

**Wichtig:** Tragen Sie hier Ihre eigenen Daten ein!

```env
# Geheimer Schlüssel (generieren Sie einen neuen!)
SECRET_KEY=ihr-sehr-sicherer-geheimer-schluessel

# Datenbank
DATABASE_URL=postgresql://rechnungen_user:sicheres_passwort@localhost:5432/rechnungen

# Ihre Firmendaten (erscheinen auf Rechnungen)
COMPANY_NAME=Ihre Firma GmbH
COMPANY_STREET=Ihre Straße 123
COMPANY_ZIP=12345
COMPANY_CITY=Ihre Stadt
COMPANY_COUNTRY=Deutschland
COMPANY_EMAIL=info@ihre-firma.de
COMPANY_PHONE=+49 123 456789
COMPANY_TAX_ID=DE123456789
COMPANY_WEBSITE=www.ihre-firma.de

# Ihre Bankverbindung (erscheint auf Rechnungen)
BANK_NAME=Ihre Bank
BANK_IBAN=DE00 0000 0000 0000 0000 00
BANK_BIC=BANKDEFF

# Optional: E-Mail-Konfiguration für Shop-Integration
MAIL_SERVER=imap.ihre-domain.de
MAIL_PORT=993
MAIL_USERNAME=shop@ihre-domain.de
MAIL_PASSWORD=email-passwort

# Optional: SMTP für Passwort-Reset E-Mails
SMTP_SERVER=smtp.ihre-domain.de
SMTP_PORT=587
SMTP_USERNAME=noreply@ihre-domain.de
SMTP_PASSWORD=smtp-passwort
SMTP_USE_TLS=True

# Optional: JWT Token Secret (für API-Authentifizierung)
JWT_SECRET_KEY=ein-anderer-sehr-sicherer-schluessel
```

**Tipp:** Ihre aktuellen Einstellungen können Sie jederzeit in der Web-UI unter "⚙️ Einstellungen" einsehen.

### 5. Datenbank initialisieren

```bash
# Virtuelle Umgebung aktivieren (falls nicht aktiv)
source venv/bin/activate

# Datenbank-Schema mit Alembic erstellen
alembic upgrade head

# ODER: Alt (flask init-db funktioniert noch, aber Alembic ist empfohlen)
# flask init-db

# Optional: Testdaten einfügen
flask seed-db
```

**Datenbankwechsel:**

Um die Datenbank zu wechseln (z.B. von PostgreSQL zu MySQL), ändern Sie einfach die `DATABASE_URL` in `.env`:

```bash
# PostgreSQL (Standard)
DATABASE_URL=postgresql://user:pass@localhost:5432/rechnungen

# MySQL/MariaDB
DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/rechnungen

# SQLite (für Tests)
DATABASE_URL=sqlite:///rechnungen.db
```

Dann Migration anwenden:
```bash
alembic upgrade head
```

**Wichtige Alembic-Befehle:**

```bash
# Migration erstellen (nach Änderungen in models.py)
alembic revision --autogenerate -m "Beschreibung der Änderung"

# Migration anwenden
alembic upgrade head

# Migration rückgängig machen (1 Schritt zurück)
alembic downgrade -1

# Aktuelle Version anzeigen
alembic current

# Migrations-Historie anzeigen
alembic history

# Bestehende DB als migriert markieren (bei erster Alembic-Nutzung)
alembic stamp head
```

**Siehe auch:** [MIGRATIONS.md](MIGRATIONS.md) für ausführliche Dokumentation

### 6. Anwendung starten

```bash
# Entwicklungsserver (Standard Port 5000)
python app.py

# Oder mit Flask CLI
flask run

# Falls Port 5000 belegt ist (z.B. durch Docker Registry):
flask run --port 5001
# oder
python app.py --port 5001
```

Die Anwendung ist standardmäßig unter http://localhost:5000 erreichbar (oder dem von Ihnen gewählten Port).

## Verwendung

### Manuelle Rechnungserstellung

1. Navigieren Sie zu "Neue Rechnung"
2. Geben Sie Kundendaten ein (oder wählen Sie einen bestehenden Kunden)
3. Fügen Sie Rechnungspositionen hinzu
4. Speichern Sie die Rechnung
5. Laden Sie das PDF herunter

### E-Mail-Import (Optional)

Die E-Mail-Integration kann genutzt werden, um Bestellungen aus einem Online-Shop automatisch zu importieren:

```python
# In der Python-Shell oder als Skript
from email_parser import process_incoming_emails
from config import config
from app import create_app

app = create_app()
with app.app_context():
    result = process_incoming_emails(app.config)
    print(f"Verarbeitet: {result['processed']} E-Mails")
```

**Hinweis:** Der E-Mail-Parser muss für Ihr spezifisches Shop-System angepasst werden. Siehe `email_parser.py` für Beispiele.

## Projektstruktur

```
rechnungen/
├── app.py                    # Hauptanwendung und Routes
├── models.py                 # Datenbankmodelle
├── config.py                 # Konfiguration
├── pdf_service.py            # PDF-Generierung
├── email_parser.py           # E-Mail-Import
├── requirements.txt          # Python-Abhängigkeiten
├── .env                      # Umgebungsvariablen (nicht im Git)
├── .env.example             # Beispiel-Konfiguration
├── templates/               # HTML-Templates
│   ├── base.html
│   ├── index.html
│   ├── invoices/
│   │   ├── create.html
│   │   ├── list.html
│   │   └── view.html
│   └── customers/
│       ├── list.html
│       └── view.html
├── uploads/                 # Upload-Ordner
└── pdfs/                    # Generierte PDFs
```

## Sicherheitshinweise

### Manipulationssicherheit

Jede Rechnung wird beim Speichern mit einem SHA-256 Hash versehen:
- Der Hash umfasst alle relevanten Rechnungsdaten
- Bei jedem Abruf wird die Integrität geprüft
- Manipulierte Rechnungen werden markiert

### Produktiv-Betrieb

Für den Produktivbetrieb beachten Sie:

1. **Sicheren SECRET_KEY verwenden:**
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. **HTTPS verwenden** (z.B. mit nginx und Let's Encrypt)

3. **Umgebung auf 'production' setzen:**
   ```env
   FLASK_ENV=production
   ```

4. **Gunicorn oder uWSGI verwenden:**
   ```bash
   pip install gunicorn
   gunicorn -w 4 -b 0.0.0.0:8000 'app:create_app()'
   ```

5. **Regelmäßige Backups der PostgreSQL-Datenbank**

6. **Firewall-Regeln konfigurieren**

---

## JWT-API für PWA/Mobile Apps

Die Anwendung bietet eine vollständige REST API mit JWT-Authentifizierung für Progressive Web Apps und Mobile Anwendungen.

### Authentifizierung

#### Login & JWT Token erhalten

```http
POST /api/auth/login
Content-Type: application/json

{
  "username": "ihr-benutzername",
  "password": "ihr-passwort",
  "totp_token": "123456"  // Optional, nur wenn 2FA aktiviert
}
```

**Antwort (Erfolg):**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": 1,
    "username": "admin",
    "email": "admin@example.com",
    "role": "admin"
  },
  "expires_in": 2592000
}
```

**Antwort (2FA erforderlich):**
```json
{
  "error": "2FA token required",
  "requires_2fa": true
}
```

**Token-Gültigkeit:** 30 Tage

---

#### Token validieren

```http
GET /api/auth/verify
Authorization: Bearer <token>
```

**Antwort:**
```json
{
  "valid": true,
  "user": {
    "id": 1,
    "username": "admin",
    "email": "admin@example.com",
    "role": "admin"
  }
}
```

---

#### Token erneuern

```http
POST /api/auth/refresh
Authorization: Bearer <token>
```

**Antwort:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires_in": 2592000
}
```

---

### API-Endpunkte (JWT-geschützt)

Alle folgenden Endpoints erfordern einen gültigen JWT-Token im Authorization-Header:

```
Authorization: Bearer <token>
```

#### Rechnungen auflisten

```http
GET /api/invoices?page=1&per_page=20&status=sent
Authorization: Bearer <token>
```

**Query-Parameter:**
- `page` - Seitennummer (Standard: 1)
- `per_page` - Einträge pro Seite (Standard: 20, max: 100)
- `status` - Filter nach Status: draft, sent, paid, cancelled

**Antwort:**
```json
{
  "invoices": [
    {
      "id": 1,
      "invoice_number": "RE-2024-11-07-0001",
      "customer_id": 5,
      "customer_name": "Müller GmbH",
      "total": 555.00,
      "status": "sent",
      "created_at": "2024-11-07T10:30:00",
      "due_date": "2024-11-21"
    }
  ],
  "total": 150,
  "page": 1,
  "per_page": 20,
  "pages": 8
}
```

---

#### Rechnungsdetails abrufen

```http
GET /api/invoices/<invoice_id>
Authorization: Bearer <token>
```

**Antwort:**
```json
{
  "id": 1,
  "invoice_number": "RE-2024-11-07-0001",
  "customer": {
    "id": 5,
    "company_name": "Müller GmbH",
    "email": "info@mueller.de"
  },
  "items": [
    {
      "product_name": "Honig Lindenhonig",
      "quantity": 10,
      "unit_price": 50.00,
      "total": 500.00
    }
  ],
  "subtotal": 500.00,
  "tax_rate": 19.0,
  "tax_amount": 95.00,
  "total": 595.00,
  "status": "sent",
  "created_at": "2024-11-07T10:30:00",
  "due_date": "2024-11-21",
  "notes": "Bitte Rechnungsnummer bei Überweisung angeben",
  "data_hash": "abc123...",
  "is_valid": true
}
```

---

#### Kunden durchsuchen

```http
GET /api/customers?search=müller&page=1&per_page=20
Authorization: Bearer <token>
```

**Query-Parameter:**
- `search` - Suchbegriff (durchsucht Firma, Name, E-Mail)
- `page` - Seitennummer
- `per_page` - Einträge pro Seite

**Antwort:**
```json
{
  "customers": [
    {
      "id": 5,
      "company_name": "Müller GmbH",
      "first_name": "Hans",
      "last_name": "Müller",
      "email": "info@mueller.de",
      "phone": "+49 123 456789",
      "address": "Musterstraße 1\n12345 Stadt",
      "tax_id": "DE123456789"
    }
  ],
  "total": 1,
  "page": 1,
  "per_page": 20
}
```

---

#### POS-Verkauf abschließen

```http
POST /api/pos/complete-sale
Authorization: Bearer <token>
Content-Type: application/json

{
  "customer_id": 5,
  "items": [
    {
      "product_id": 10,
      "quantity": 2,
      "unit_price": 8.50
    }
  ],
  "payment_method": "cash",
  "notes": "Barzahlung"
}
```

**Antwort:**
```json
{
  "success": true,
  "invoice_id": 42,
  "invoice_number": "RE-2024-11-07-0042",
  "total": 17.00,
  "pdf_url": "/invoices/42/download"
}
```

---

### Beispiel: JavaScript Fetch API

```javascript
// Login
const response = await fetch('https://ihr-server.de/api/auth/login', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    username: 'admin',
    password: 'passwort'
  })
});

const { token } = await response.json();

// Token speichern
localStorage.setItem('jwt_token', token);

// API-Aufruf mit Token
const invoicesResponse = await fetch('https://ihr-server.de/api/invoices', {
  headers: {
    'Authorization': `Bearer ${token}`
  }
});

const invoices = await invoicesResponse.json();
```

---

### Beispiel: Python Requests

```python
import requests

# Login
response = requests.post('https://ihr-server.de/api/auth/login', json={
    'username': 'admin',
    'password': 'passwort'
})

token = response.json()['token']

# API-Aufruf mit Token
headers = {'Authorization': f'Bearer {token}'}
invoices = requests.get('https://ihr-server.de/api/invoices', headers=headers).json()

for invoice in invoices['invoices']:
    print(f"{invoice['invoice_number']}: {invoice['total']} €")
```

---

### Rollenbasierte Zugriffskontrolle

Die JWT-API respektiert die Benutzerrollen:

- **admin**: Voller Zugriff auf alle Endpoints
- **manager**: Rechnungen, Kunden, Produkte (keine User-Verwaltung)
- **employee**: Rechnungen erstellen/ansehen (keine Kunden bearbeiten)
- **viewer**: Nur Lesezugriff

Beispiel für fehlende Berechtigung:
```json
{
  "error": "Insufficient permissions",
  "required_role": "admin",
  "your_role": "employee"
}
```

---

## Passwort-Reset per E-Mail

Benutzer können ihr Passwort über einen E-Mail-Link zurücksetzen.

### Funktionsweise

1. **Passwort vergessen?** Link auf Login-Seite
2. Benutzer gibt E-Mail-Adresse ein
3. System sendet E-Mail mit Reset-Link (1 Stunde gültig)
4. Benutzer klickt Link und setzt neues Passwort
5. Alter Token wird ungültig

### E-Mail-Konfiguration

In `.env` SMTP-Daten eintragen:

```env
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=ihre-email@gmail.com
SMTP_PASSWORD=ihr-app-passwort
SMTP_USE_TLS=True
```

**Für Gmail:**
1. 2-Faktor-Authentifizierung aktivieren
2. App-Passwort erstellen: https://myaccount.google.com/apppasswords
3. App-Passwort in `.env` eintragen

### Routes

```
GET  /forgot-password          → E-Mail-Eingabe
POST /forgot-password          → Reset-Link senden
GET  /reset-password/<token>   → Neues Passwort eingeben
POST /reset-password/<token>   → Passwort speichern
```

### Sicherheit

- Token: 32 Byte zufällig, URL-safe
- Gültigkeit: 1 Stunde
- Einmalverwendung (wird nach Verwendung gelöscht)
- Rate-Limiting: Max. 3 Versuche/15 Min (via CrowdSec)

---

## CrowdSec Integration

CrowdSec ist eine moderne Security-Engine, die automatisch Angriffe erkennt und IP-Adressen sperrt.

### Was wird geloggt?

Die Flask-App schreibt strukturierte Logs nach `logs/security.log`, die CrowdSec auswertet:

**1. Failed Logins (Bruteforce-Schutz)**
```json
{
  "timestamp": "2024-11-07T15:30:00",
  "level": "WARNING",
  "event": "failed_login",
  "username": "admin",
  "ip": "203.0.113.42",
  "user_agent": "Mozilla/5.0..."
}
```

**2. Suspicious Activity (SQL-Injection, XSS)**
```json
{
  "timestamp": "2024-11-07T15:31:00",
  "level": "WARNING",
  "event": "suspicious_activity",
  "ip": "203.0.113.42",
  "path": "/search?q=<script>alert(1)</script>",
  "reason": "XSS attempt detected"
}
```

**3. Rate Limit Exceeded**
```json
{
  "timestamp": "2024-11-07T15:32:00",
  "level": "WARNING",
  "event": "rate_limit_exceeded",
  "ip": "203.0.113.42",
  "endpoint": "/api/invoices"
}
```

**4. Unauthorized Access**
```json
{
  "timestamp": "2024-11-07T15:33:00",
  "level": "WARNING",
  "event": "unauthorized_access",
  "ip": "203.0.113.42",
  "path": "/admin/users",
  "user": "employee",
  "required_role": "admin"
}
```

### CrowdSec-Konfiguration

Im Docker-Setup ist CrowdSec bereits vorkonfiguriert. Für manuelle Installation:

```bash
# CrowdSec installieren
curl -s https://packagecloud.io/install/repositories/crowdsec/crowdsec/script.deb.sh | sudo bash
sudo apt install crowdsec

# Flask-Parser installieren
sudo cscli parsers install crowdsecurity/flask-logs

# Scenario aktivieren
sudo cscli scenarios install crowdsecurity/http-bruteforce
sudo cscli scenarios install crowdsecurity/http-scan

# Log-Datei konfigurieren
sudo nano /etc/crowdsec/acquis.yaml
```

**acquis.yaml:**
```yaml
filenames:
  - /home/janusz/git/privat/rechnungen/logs/security.log
labels:
  type: flask
```

```bash
# CrowdSec neu starten
sudo systemctl restart crowdsec

# Status prüfen
sudo cscli metrics
sudo cscli decisions list
```

### Automatische IP-Sperren

CrowdSec sperrt IPs automatisch bei:
- **5 fehlgeschlagene Logins** in 5 Minuten → 4 Stunden Sperre
- **10 XSS/SQLi-Versuche** in 5 Minuten → 24 Stunden Sperre
- **50 Requests/Minute** an API → 1 Stunde Sperre
- **Scan-Versuche** (/.env, /admin, etc.) → 12 Stunden Sperre

### Web-Dashboard (Optional)

```bash
# Metabase installieren (Web-UI)
sudo cscli dashboard setup

# URL anzeigen
sudo cscli dashboard show-password
```

Zugriff: `http://localhost:3000` (Standard-Credentials siehe Terminal)

---

## API-Endpunkte

Die Anwendung stellt verschiedene API-Endpunkte für interne und externe Nutzung bereit:

### Kundensuche (Autocomplete)

```http
GET /api/customers/search?q=<query>
```

**Parameter:**
- `q` - Suchbegriff (min. 3 Zeichen)

**Suchfelder:** Firma, Vorname, Nachname, E-Mail

**Beispiel:**
```bash
curl "http://localhost:5000/api/customers/search?q=Mül"
```

**Antwort:**
```json
[
  {
    "id": 1,
    "company_name": "Müller GmbH",
    "first_name": "Hans",
    "last_name": "Müller",
    "email": "hans@mueller.de",
    "phone": "+49 123 456789",
    "address": "Musterstraße 1\n12345 Stadt",
    "tax_id": "DE123456789",
    "display_name": "Müller GmbH"
  }
]
```

---

### Produktsuche (Autocomplete)

```http
GET /api/products/search?q=<query>
```

**Parameter:**
- `q` - Suchbegriff (min. 2 Zeichen)

**Suchfelder:** Name, Chargennummer, Menge

**Hinweis:** Liefert nur aktive Produkte

**Beispiel:**
```bash
curl "http://localhost:5000/api/products/search?q=Honig"
```

**Antwort:**
```json
[
  {
    "id": 5,
    "name": "Honig Lindenhonig",
    "quantity": "250g",
    "price": 8.50,
    "reseller_price": 6.00,
    "number": 150,
    "lot_number": "L0101",
    "display_name": "Honig Lindenhonig 250g"
  }
]
```

---

### Bestandsverwaltung (per Chargennummer)

**Wichtig:** Diese API-Endpunkte sind für **normale Produktionsprozesse** (Abfüllen, Verpacken) gedacht und erstellen **keine GoBD-Dokumentation**. Für steuerrelevante Abgänge (Eigenentnahme, Verderb, Geschenke) verwenden Sie stattdessen die Web-UI unter "📝 Anpassungen".

**Unterscheidung:**
- ✅ **Normale Bestandsbewegungen** (keine GoBD-Dokumentation erforderlich):
  - Produktion/Abfüllen → API `/stock/add`
  - Verkauf über Kasse/Rechnung → automatischer Abzug mit Beleg
  - Kommissionsware-Lieferung → Lieferschein
- 📝 **Steuerrelevante Bestandsanpassungen** (GoBD-Dokumentation erforderlich):
  - Eigenentnahme (§ 3 Abs. 1b Nr. 1 UStG) → Web-UI "📝 Anpassungen"
  - Verderb/Bruch → Web-UI "📝 Anpassungen"
  - Geschenke → Web-UI "📝 Anpassungen"
  - Inventurkorrekturen → Web-UI "📝 Anpassungen"

#### Bestand erhöhen

```http
POST /api/products/lot/<lot_number>/stock/add
Content-Type: application/json

{
  "amount": 50
}
```

**Parameter:**
- `lot_number` - Chargennummer (z.B. L0101)
- `amount` - Anzahl hinzuzufügen (im Body)

**Verhalten:**
- Existiert die Charge bereits → Bestand wird erhöht
- Neue Charge → Produkt wird automatisch angelegt (inaktiv, Name als Platzhalter)

**Anwendungsfall:** Automatische Bestandsbuchung beim Abfüllen/Verpacken (keine Steuerrelevanz, daher keine GoBD-Dokumentation)

**Beispiel:**
```bash
curl -X POST http://localhost:5000/api/products/lot/L0101/stock/add \
  -H "Content-Type: application/json" \
  -d '{"amount": 50}'
```

**Antwort (existierende Charge):**
```json
{
  "success": true,
  "message": "50 Stück zu Charge L0101 hinzugefügt",
  "product_id": 5,
  "product_name": "Honig Lindenhonig",
  "lot_number": "L0101",
  "new_stock": 200
}
```

**Antwort (neue Charge):**
```json
{
  "success": true,
  "message": "Neues Produkt mit Charge L0101 angelegt (50 Stück)",
  "product_id": 10,
  "product_name": "Produkt L0101",
  "lot_number": "L0101",
  "new_stock": 50,
  "new_product": true
}
```

#### Bestand reduzieren

```http
POST /api/products/lot/<lot_number>/stock/reduce
Content-Type: application/json

{
  "amount": 10
}
```

**Parameter:**
- `lot_number` - Chargennummer (z.B. L0101)
- `amount` - Anzahl abzuziehen (im Body)

**Validierung:**
- Prüft ob Charge existiert
- Prüft ob genug Bestand vorhanden ist

**Beispiel:**
```bash
curl -X POST http://localhost:5000/api/products/lot/L0101/stock/reduce \
  -H "Content-Type: application/json" \
  -d '{"amount": 10}'
```

**Antwort (Erfolg):**
```json
{
  "success": true,
  "message": "10 Stück von Charge L0101 abgezogen",
  "product_id": 5,
  "product_name": "Honig Lindenhonig",
  "lot_number": "L0101",
  "new_stock": 190
}
```

**Antwort (Fehler - nicht genug Bestand):**
```json
{
  "success": false,
  "error": "Nicht genug Bestand vorhanden (aktuell: 5)"
}
```

---

### Automatischer Zahlungsabgleich

Dieser Endpoint ermöglicht die automatische Verarbeitung von Zahlungseingängen durch externe Systeme (z.B. Banking-Software).

#### Zahlung prüfen und verbuchen

```http
POST /api/payments/check
Content-Type: application/json

{
  "invoice_number": "RE-20251107-0001",
  "amount": 555.00
}
```

**Parameter:**
- `invoice_number` - Rechnungsnummer (erforderlich)
- `amount` - Erhaltener Betrag in Euro (erforderlich)

**Verhalten:**
1. **Betrag stimmt (±0,01€ Toleranz)** → Rechnung wird automatisch als "paid" markiert
2. **Betragsdifferenz** → Status "mismatch", manuelle Prüfung erforderlich
3. **Rechnungsnummer nicht gefunden** → Status "not_found", manuelle Prüfung erforderlich
4. **Bereits bezahlt** → Status "duplicate", mögliche Doppelzahlung

**Beispiel:**
```bash
curl -X POST http://localhost:5000/api/payments/check \
  -H "Content-Type: application/json" \
  -d '{"invoice_number": "RE-20251107-0001", "amount": 555.00}'
```

**Antwort (Erfolg - Betrag stimmt):**
```json
{
  "success": true,
  "status": "matched",
  "message": "Zahlung für RE-20251107-0001 erfolgreich verbucht",
  "invoice_id": 5,
  "expected_amount": 555.00,
  "amount_received": 555.00,
  "difference": 0.00,
  "check_id": 12,
  "requires_review": false
}
```

**Antwort (Betragsdifferenz):**
```json
{
  "success": false,
  "status": "mismatch",
  "message": "Betragsdifferenz festgestellt - manuelle Prüfung erforderlich",
  "invoice_id": 5,
  "expected_amount": 555.00,
  "amount_received": 540.00,
  "difference": -15.00,
  "check_id": 13,
  "requires_review": true
}
```

**Antwort (Rechnung nicht gefunden):**
```json
{
  "success": false,
  "status": "not_found",
  "message": "Rechnung RE-20251107-9999 nicht gefunden",
  "check_id": 14,
  "requires_review": true
}
```

**Antwort (Doppelzahlung):**
```json
{
  "success": false,
  "status": "duplicate",
  "message": "Rechnung bereits bezahlt - mögliche Doppelzahlung",
  "invoice_id": 5,
  "expected_amount": 555.00,
  "amount_received": 555.00,
  "check_id": 15,
  "requires_review": true
}
```

**Manuelle Prüfung:**

Alle Zahlungen mit `requires_review: true` können unter `/payments/review` manuell geprüft werden:

- **UI-Zugriff:** http://localhost:5000/payments/review
- Zeigt alle offenen Prüfungen (Differenzen, nicht gefundene Rechnungen, Doppelzahlungen)
- Anzeige der Differenz mit Farbcodierung
- Aktionen: "Bezahlt markieren" oder "Ignorieren"
- Link zur zugehörigen Rechnung (falls vorhanden)

**Stati:**
- `matched` - Zahlung erfolgreich zugeordnet, Rechnung automatisch als bezahlt markiert
- `mismatch` - Betragsdifferenz festgestellt (Über- oder Unterzahlung)
- `not_found` - Rechnungsnummer existiert nicht in der Datenbank
- `duplicate` - Rechnung bereits als bezahlt markiert (mögliche Doppelzahlung)

**Toleranz:** Abweichungen ≤ 0,01 € werden automatisch akzeptiert (Rundungsdifferenzen)

---

## Mahnwesen

Das System bietet ein vollautomatisches Mahnwesen für überfällige Rechnungen.

### Automatische Erkennung überfälliger Rechnungen

In der Rechnungsliste (`/invoices?filter=overdue`) werden automatisch alle Rechnungen angezeigt, deren Fälligkeitsdatum mehr als 10 Tage überschritten ist. Für diese Rechnungen wird automatisch ein **Mahnung**-Button angezeigt.

### Mahnungserstellung

**URL:** `/invoices/<invoice_id>/reminder`

**Funktionen:**
- Automatische Ermittlung der Mahnstufe (1., 2., 3. Mahnung, etc.)
- Berechnung von Mahngebühren:
  - 1. Mahnung: 5,00 €
  - 2.+ Mahnung: 10,00 €
- Anzeige aller bisherigen Mahnungen
- Zwei Versandoptionen:
  1. **PDF-Download**: Mahnung als PDF herunterladen
  2. **E-Mail-Versand**: Direkt an Kunden-E-Mail senden

**Mahnungsstufen:**
- **1. Mahnung**: Höfliche Zahlungserinnerung, 7 Tage Zahlungsfrist
- **2. Mahnung**: Dringende Aufforderung, 5 Tage Zahlungsfrist
- **3. Mahnung**: Letzte Mahnung vor Inkasso, 3 Tage Zahlungsfrist

### PDF-Inhalt

Die Mahnungs-PDFs enthalten:
- Empfängeradresse (Fensterbriefumschlag-kompatibel)
- Mahnstufe prominent hervorgehoben (rot)
- Ursprüngliche Rechnungsinformationen
- Anzahl Tage überfällig
- Mahntext entsprechend der Mahnstufe
- Offene Forderung (Rechnungsbetrag + Mahngebühr)
- Zahlungsinformationen (Bank, IBAN, BIC)
- Warnung bei späteren Mahnstufen
- Faltmarken nach DIN 5008

### E-Mail-Versand

Bei E-Mail-Versand wird automatisch:
- PDF als Anhang mitgesendet
- Mahntext an Mahnstufe angepasst
- Gesamtforderung berechnet und angezeigt
- Zeitstempel und Versandart in Datenbank gespeichert

### Mahnhistorie

Alle versendeten Mahnungen werden in der Datenbank protokolliert:
- Mahnstufe
- Mahndatum
- Versanddatum und -art (PDF/E-Mail)
- Mahngebühr
- Notizen

Die Historie ist auf der Mahnung-Erstellungsseite sichtbar.

### Migration

Um die Mahnungsfunktion zu aktivieren, führen Sie die Migration aus:

```bash
python migrate_add_reminders.py
```

Dies erstellt die Tabelle `reminders` mit allen erforderlichen Feldern und Indizes.

---

### Rechnungsinformationen

#### Rechnungsdetails abrufen

```http
GET /api/invoices/<invoice_id>
```

**Beispiel:**
```bash
curl http://localhost:5000/api/invoices/1
```

#### Rechnungsintegrität prüfen

```http
GET /api/invoices/<invoice_id>/verify
```

**Beispiel:**
```bash
curl http://localhost:5000/api/invoices/1/verify
```

**Antwort:**
```json
{
  "invoice_id": 1,
  "invoice_number": "RE-2024-11-07-0001",
  "is_valid": true,
  "data_hash": "abc123..."
}
```

---

### Microcontroller-Integration

Die Bestandsverwaltungs-Endpoints sind speziell für die Integration mit Microcontrollern konzipiert:

**Anwendungsfall:** Automatische Bestandsbuchung beim Abfüllen/Verpacken

**Arduino/ESP32 Beispiel:**
```cpp
#include <HTTPClient.h>
#include <ArduinoJson.h>

void addStock(String lotNumber, int amount) {
  HTTPClient http;
  String url = "http://192.168.1.100:5000/api/products/lot/" + lotNumber + "/stock/add";

  http.begin(url);
  http.addHeader("Content-Type", "application/json");

  String payload = "{\"amount\":" + String(amount) + "}";
  int httpCode = http.POST(payload);

  if (httpCode == 200 || httpCode == 201) {
    String response = http.getString();
    Serial.println("Erfolg: " + response);
  } else {
    Serial.println("Fehler: " + String(httpCode));
  }

  http.end();
}

// Verwendung:
addStock("L0101", 50);  // 50 Stück zur Charge L0101 hinzufügen
```

**Vorteile:**
- ✅ Keine Datenbank-ID erforderlich
- ✅ Chargennummer kann direkt von QR-Code/Barcode gelesen werden
- ✅ Automatische Produktanlage bei neuen Chargen
- ✅ Echtzeit-Bestandsaktualisierung
- ✅ Keine GoBD-Overhead für Produktionsprozesse

**Hinweis zur GoBD-Compliance:**

Diese Endpoints sind **bewusst ohne GoBD-Dokumentation** implementiert, da:
1. **Produktion ist nicht steuerrelevant** - Erst der Verkauf löst Steuerpflicht aus
2. **Verkäufe haben bereits Belege** - Rechnungen/Kassenbons erfüllen GoBD-Anforderungen
3. **Performance** - Kein Overhead für jeden Produktionsschritt (z.B. jedes einzelne Glas)

Für **steuerrelevante Abgänge ohne Beleg** (Eigenentnahme, Verderb, Geschenke) nutzen Sie die Web-UI unter "📝 Anpassungen", die vollständige GoBD-Dokumentation mit Belegnummern erstellt.

**Siehe auch:** [GOBD_COMPLIANCE.md - Kapitel 8: Bestandsanpassungen](GOBD_COMPLIANCE.md#8-bestandsanpassungen)

## API-Endpunkte

### Eigene Shop-Integration

Erstellen Sie einen eigenen E-Mail-Parser in `email_parser.py`:

```python
class MeinShopEmailParser(EmailInvoiceParser):
    def parse_email_to_invoice_data(self, email_message):
        # Ihre shopspezifische Logik
        pass
```

### Zusätzliche Felder

Erweitern Sie die Modelle in `models.py` und führen Sie eine Migration durch:

```bash
# 1. Feld in models.py hinzufügen
# Beispiel: birthday = db.Column(db.Date, nullable=True) in Customer-Klasse

# 2. Migration generieren
alembic revision --autogenerate -m "Add customer birthday field"

# 3. Migration anwenden
alembic upgrade head
```

**Detaillierte Anleitung:** Siehe [MIGRATIONS.md](MIGRATIONS.md)

## Fehlerbehebung

### Port 5000 bereits belegt

Falls Port 5000 bereits belegt ist (z.B. durch Docker Registry):

```bash
# Welcher Prozess belegt den Port?
sudo lsof -i :5000

# Alternative 1: Flask auf anderem Port starten
python app.py --port 5001

# Alternative 2: Mit Flask CLI
flask run --port 5001

# Alternative 3: Docker Registry stoppen (falls nicht benötigt)
sudo systemctl stop docker-registry
```

### Datenbankverbindung fehlgeschlagen

```bash
# PostgreSQL-Status prüfen
sudo systemctl status postgresql

# PostgreSQL starten
sudo systemctl start postgresql
```

### PDF-Generierung schlägt fehl

Stellen Sie sicher, dass der `pdfs/` Ordner beschreibbar ist:
```bash
mkdir -p pdfs
chmod 755 pdfs
```

### E-Mail-Import funktioniert nicht

Prüfen Sie die E-Mail-Konfiguration in `.env` und testen Sie die Verbindung:
```python
from email_parser import EmailInvoiceParser
parser = EmailInvoiceParser('imap.example.com', 993, 'user', 'pass')
parser.connect()  # Sollte True zurückgeben
```

## Lizenz

Dieses Projekt steht unter der MIT-Lizenz.

## Support

Bei Fragen oder Problemen erstellen Sie bitte ein Issue im Repository oder kontaktieren Sie den Entwickler.

---

## Progressive Web App (PWA)

Die Rechnungsverwaltung ist eine **installierbare Progressive Web App** mit Offline-Unterstützung.

### Features

✅ **Installierbar auf allen Geräten**
- Desktop (Windows, macOS, Linux)
- Mobile (iOS, Android)
- "Add to Home Screen" für schnellen Zugriff

✅ **Offline-Funktionalität**
- Rechnungen ansehen ohne Internet
- Automatische Synchronisation bei Verbindung
- Background-Sync für POST-Requests

✅ **App-ähnliches Erlebnis**
- Vollbild-Modus (ohne Browser-UI)
- Custom App-Icon
- Splash-Screen
- Native Shortcuts (Neue Rechnung, Liste, Kunden)

✅ **Performance**
- Cache-First Strategy für Static Assets
- Network-First für API-Calls
- Schnelle Ladezeiten

### Installation

#### Desktop (Chrome/Edge/Brave)

1. Öffne die App im Browser: `https://ihr-server.de`
2. Klicke auf das **⊕ Install**-Icon in der Adressleiste
3. Oder: **Menü → App installieren**
4. Die App erscheint im Anwendungsmenü

**Shortcut:** App ist jetzt wie ein natives Programm nutzbar!

#### Android

1. Öffne die App im Chrome-Browser
2. Tippe auf **Menü (⋮) → Zum Startbildschirm hinzufügen**
3. Bestätige mit "Hinzufügen"
4. Icon erscheint auf dem Startbildschirm

#### iOS/iPadOS

1. Öffne die App in Safari
2. Tippe auf das **Teilen-Icon** (Viereck mit Pfeil)
3. Scrolle und wähle **"Zum Home-Bildschirm"**
4. Bestätige mit "Hinzufügen"

**Hinweis:** iOS unterstützt Service Worker teilweise - Background-Sync funktioniert nur auf Android/Desktop.

### Offline-Nutzung

**Was funktioniert offline:**
- ✅ Rechnungsliste ansehen (gecacht)
- ✅ Rechnungsdetails öffnen (gecacht)
- ✅ Kundenliste durchsuchen (gecacht)
- ✅ Neue Rechnung erstellen (wird gespeichert)
- ✅ PDF-Downloads (wenn vorher geladen)

**Was erfordert Online-Verbindung:**
- ❌ Rechnungen versenden (Status ändern)
- ❌ Neue Kunden anlegen (POST)
- ❌ Zahlungen verbuchen

**Automatische Synchronisation:**
- Sobald Verbindung verfügbar, werden offline-erstellte Rechnungen automatisch hochgeladen
- Benachrichtigung über erfolgreiche Sync

### Service Worker

Der Service Worker cached automatisch:
- Static Assets (CSS, JS, Icons)
- HTML-Seiten (Network-First)
- API-Responses (für Offline-Zugriff)
- CDN-Ressourcen (Bootstrap)

**Cache-Strategie:**
- **Network-First**: HTML, API → Aktuelle Daten bevorzugt, Cache als Fallback
- **Cache-First**: CSS, JS, Bilder → Schnelle Auslieferung, Background-Update

**Version:** `v1` (siehe `service-worker.js`)

### Updates

PWA-Updates erfolgen automatisch:

1. Neue Version wird im Hintergrund heruntergeladen
2. **Update-Benachrichtigung** erscheint oben rechts
3. Klick auf "Aktualisieren" lädt neue Version
4. Seite wird neu geladen mit neuem Service Worker

**Manuelles Update:**
- Browser-DevTools → Application → Service Workers → "Update"

### Manifest

**Datei:** `static/manifest.json`

Wichtige Einstellungen:
```json
{
  "name": "Rechnungsverwaltung",
  "short_name": "Rechnungen",
  "start_url": "/",
  "display": "standalone",
  "theme_color": "#0d6efd",
  "background_color": "#ffffff"
}
```

**Custom Shortcuts:**
- 📝 Neue Rechnung → `/invoices/create`
- 📋 Rechnungsliste → `/invoices`
- 👥 Kunden → `/customers`

(Rechtsklick auf App-Icon zeigt Shortcuts)

### Icons

**Generiert mit:** `python generate_icons.py`

**Verfügbare Größen:**
- PWA: 72x72, 96x96, 128x128, 144x144, 152x152, 192x192, 384x384, 512x512
- iOS: 120x120, 152x152, 167x167, 180x180
- Favicon: 16x16, 32x32, 48x48, favicon.ico
- Maskable: 192x192, 512x512 (für Android Adaptive Icons)

**Custom Icons:**
```bash
# Eigenes Logo verwenden (mind. 512x512 PNG)
python generate_icons.py /pfad/zu/logo.png
```

### Push Notifications (Optional)

Service Worker unterstützt Push-Notifications für:
- Neue Rechnungen
- Zahlungseingänge
- Mahnungen

**Aktivierung:** Siehe `service-worker.js` → `push` Event

**Backend-Setup erforderlich:** Web Push Protocol (VAPID Keys)

### Deinstallation

**Desktop:**
- Chrome: `chrome://apps` → Rechtsklick → Deinstallieren
- Edge: Einstellungen → Apps → Installierte Apps

**Android:**
- Wie jede andere App: Lange drücken → Deinstallieren

**iOS:**
- Icon gedrückt halten → "App entfernen"

### Entwicklung & Debugging

**Service Worker debuggen:**

```bash
# Chrome DevTools
1. F12 → Application Tab
2. Service Workers
3. "Update on reload" aktivieren (während Entwicklung)
4. Console für SW-Logs
```

**PWA-Audit:**
```bash
# Lighthouse
1. Chrome DevTools → Lighthouse Tab
2. "Progressive Web App" auswählen
3. "Generate report"
```

**Cache löschen:**
```bash
# Chrome
chrome://settings/clearBrowserData
→ "Cached images and files"

# Oder: DevTools → Application → Clear storage
```

### Troubleshooting

**PWA lässt sich nicht installieren:**
- ✅ HTTPS aktiv? (oder localhost)
- ✅ `manifest.json` korrekt verlinkt?
- ✅ Icons vorhanden? (min. 192x192 + 512x512)
- ✅ Service Worker registriert?

**Offline-Modus funktioniert nicht:**
- Prüfe DevTools → Application → Service Workers → Status
- Prüfe Cache Storage → Sind Dateien gecacht?
- Console-Logs für Fehler

**Alte Version wird angezeigt:**
- Hard-Refresh: `Ctrl+Shift+R` (Windows/Linux) / `Cmd+Shift+R` (macOS)
- Service Worker Update erzwingen (DevTools)
- Cache leeren

**iOS Safari-Probleme:**
- Service Worker-Unterstützung eingeschränkt
- Background-Sync nicht verfügbar
- IndexedDB-Limits beachten (50MB)

---

## Roadmap

Geplante Features:
- [ ] Rechnungsvorlagen anpassen
- [x] E-Mail-Versand direkt aus der App
- [ ] Wiederkehrende Rechnungen
- [x] Zahlungserinnerungen / Mahnwesen
- [ ] Statistiken und Reports
- [x] REST API für externe Integrationen
- [x] **Progressive Web App (PWA)** ✅
- [x] **Offline-Funktionalität** ✅
- [x] **JWT-API für Mobile Apps** ✅
- [x] Bestandsverwaltung mit Autocomplete
- [x] Automatischer Zahlungsabgleich
- [ ] Push-Notifications für Zahlungseingänge
- [ ] QR-Code-Zahlung (SEPA/PayPal)
- [ ] Automatisches Backup zu Cloud (S3, Dropbox)
