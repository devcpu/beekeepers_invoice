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

## Technologie-Stack

- **Backend:** Flask 3.0, SQLAlchemy
- **Datenbank:** PostgreSQL
- **PDF-Generierung:** ReportLab
- **E-Mail:** Python IMAP

## Installation

### 1. Voraussetzungen

- Python 3.9+
- PostgreSQL 12+
- pip und virtualenv

### 2. Repository klonen und einrichten

```bash
cd /home/janusz/git/privat/rechnungen

# Virtuelle Umgebung erstellen
python3 -m venv venv
source venv/bin/activate

# Abhängigkeiten installieren
pip install -r requirements.txt
```

### 3. PostgreSQL-Datenbank erstellen

```bash
# Als postgres-User
sudo -u postgres psql

# In der PostgreSQL-Konsole:
CREATE DATABASE rechnungen;
CREATE USER rechnungen_user WITH PASSWORD 'sicheres_passwort';
GRANT ALL PRIVILEGES ON DATABASE rechnungen TO rechnungen_user;
\q
```

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
```

**Tipp:** Ihre aktuellen Einstellungen können Sie jederzeit in der Web-UI unter "⚙️ Einstellungen" einsehen.

### 5. Datenbank initialisieren

```bash
# Virtuelle Umgebung aktivieren (falls nicht aktiv)
source venv/bin/activate

# Datenbank-Tabellen erstellen
flask init-db

# Optional: Testdaten einfügen
flask seed-db
```

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
# Mit Alembic für Datenbankmigrationen
pip install alembic
alembic init migrations
alembic revision --autogenerate -m "Add new field"
alembic upgrade head
```

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

## Roadmap

Geplante Features:
- [ ] Rechnungsvorlagen anpassen
- [x] E-Mail-Versand direkt aus der App
- [ ] Wiederkehrende Rechnungen
- [x] Zahlungserinnerungen / Mahnwesen
- [ ] Statistiken und Reports
- [x] REST API für externe Integrationen
- [ ] Mobile App
- [x] Bestandsverwaltung mit Autocomplete
- [x] Automatische Zahlungsabgleich

