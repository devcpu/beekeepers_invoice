# GoBD-Konformität - Rechnungsverwaltungssystem

## Übersicht

Dieses System erfüllt die Anforderungen der **GoBD (Grundsätze zur ordnungsmäßigen Führung und Aufbewahrung von Büchern, Aufzeichnungen und Unterlagen in elektronischer Form sowie zum Datenzugriff)** für die elektronische Rechnungsstellung und -verwaltung.

**Implementierungsdatum:** Dezember 2024  
**Version:** 1.1  
**Rechtsgrundlage:** BMF-Schreiben vom 28.11.2019

**Erfasste Geschäftsvorfälle:**
- Rechnungen (Verkauf an Kunden)
- Stornorechnungen (Korrekturbelege)
- BAR-Rechnungen (Direktverkauf/Kasse)
- Bestandsanpassungen (Eigenentnahme, Inventur, Verderb, etc.)

---

## Inhaltsverzeichnis

1. [Unveränderbarkeit von Belegen](#1-unveränderbarkeit-von-belegen-immutability)
2. [Vollständiger Audit Trail](#2-vollständiger-audit-trail)
3. [Stornierung durch Korrekturbeleg](#3-stornierung-durch-korrekturbeleg)
4. [PDF-Archivierung mit Hash-Verifizierung](#4-pdf-archivierung-mit-hash-verifizierung)
5. [Datenbankstruktur](#5-datenbankstruktur)
6. [Migration bestehender Daten](#6-migration-bestehender-daten)
7. [Verfahrensdokumentation](#7-verfahrensdokumentation)
8. [Bestandsanpassungen (Eigenentnahme, Inventur)](#8-bestandsanpassungen-eigenentnahme-inventur)
9. [Backup-Strategie](#9-backup-strategie)
10. [Datenschutz (DSGVO)](#10-datenschutz-dsgvo)
11. [Betriebsprüfung (Finanzamt)](#11-betriebsprüfung-finanzamt)
12. [Checkliste: GoBD-Konformität](#12-checkliste-gobd-konformität)

---

## 1. Unveränderbarkeit von Belegen (Immutability)

### Anforderung
Versendete Rechnungen dürfen nicht mehr nachträglich verändert werden können.

### Implementierung

#### Status-Workflow
```
draft → sent → paid
   ↓          ↓
DELETE    cancelled
```

**Regeln:**
- ✅ `draft` → `sent`: Erlaubt
- ✅ `draft` → **LÖSCHEN**: Erlaubt (nicht buchungsrelevant)
- ✅ `sent` → `paid`: Erlaubt
- ✅ `sent` → `cancelled`: Erlaubt (nur über Stornorechnung)
- ✅ `paid` → `cancelled`: Erlaubt (nur über Stornorechnung)
- ❌ `sent` → `draft`: **VERBOTEN**
- ❌ `sent` → **LÖSCHEN**: **VERBOTEN** (nur Stornierung)
- ❌ `paid` → `draft`: **VERBOTEN**
- ❌ `paid` → `sent`: **VERBOTEN**
- ❌ `paid` → **LÖSCHEN**: **VERBOTEN** (nur Stornierung)

#### Löschung von Entwürfen (GoBD-konform)

**Wichtig:** Entwürfe sind noch nicht geschäftsrelevant und unterliegen **nicht** der Aufbewahrungspflicht.

**Route:** `/invoices/<id>/delete` (POST)  
**Datei:** `app.py` - Funktion `delete_invoice()`

```python
# GoBD: Nur Entwürfe dürfen gelöscht werden
if invoice.status != 'draft':
    flash('Fehler: Nur Entwürfe können gelöscht werden. Versendete Rechnungen müssen storniert werden (GoBD-Konformität).', 'error')
    return redirect(url_for('view_invoice', invoice_id=invoice_id))
```

**Was wird gelöscht:**
- ✅ Rechnung selbst
- ✅ Alle Rechnungspositionen (LineItems)
- ✅ Status-Log-Einträge (wenn vorhanden)
- ❌ **NICHT** gelöscht: Kundendaten (werden wiederverwendet)

**Rechtfertigung:** Ein Entwurf ist noch keine Rechnung im steuerrechtlichen Sinne. Die Aufbewahrungspflicht beginnt erst mit der Versendung an den Kunden (Status `sent`).

#### Status-Übergang zu 'sent' als kritischer Punkt

Ab dem Moment, in dem eine Rechnung als "versendet" markiert wird:
- Wird der **SHA-256 Hash** gespeichert
- Greift die **Unveränderbarkeit**
- Beginnt die **10-jährige Aufbewahrungspflicht**
- Sind **keine Löschungen** mehr erlaubt

#### Code-Implementierung
**Datei:** `app.py` - Funktion `update_invoice_status()`

```python
# Verhindere unzulässige Status-Änderungen (GoBD)
if invoice.status == 'sent':
    if new_status == 'draft':
        flash('Fehler: Versendete Rechnungen können nicht zurück zu Entwurf gesetzt werden (GoBD).', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
```

#### Datenbank-Integritätsprüfung
Jede Rechnung hat einen **SHA-256 Hash** über alle Rechnungsdaten:
- Gespeichert in: `Invoice.data_hash`
- Berechnet bei Erstellung
- Verifiziert bei Anzeige
- Bei Manipulation wird Warnung angezeigt

---

## 2. Vollständiger Audit Trail

### Anforderung
Alle Änderungen an Rechnungen müssen nachvollziehbar protokolliert werden.

### Implementierung

#### Datenbank-Modell: `InvoiceStatusLog`
**Datei:** `models.py`

```sql
CREATE TABLE invoice_status_log (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    old_status VARCHAR(20),
    new_status VARCHAR(20) NOT NULL,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    changed_by VARCHAR(100) NOT NULL,
    reason TEXT
);
```

**Erfasste Informationen:**
- **invoice_id**: Referenz zur Rechnung
- **old_status**: Status vor Änderung (NULL bei Erstellung)
- **new_status**: Neuer Status
- **changed_at**: Zeitstempel der Änderung (Mikrosekunden-genau)
- **changed_by**: Benutzer (aktuell "System", erweiterbar)
- **reason**: Optionaler Grund für die Änderung

#### Automatische Protokollierung
Jede Status-Änderung wird automatisch protokolliert:

```python
log_entry = InvoiceStatusLog(
    invoice_id=invoice.id,
    old_status=invoice.status,
    new_status=new_status,
    changed_by='System',  # TODO: Aktuellen User integrieren
    reason=reason
)
db.session.add(log_entry)
```

#### Anzeige im Frontend
**Datei:** `templates/invoices/view.html`

Die Status-Historie wird in jedem Rechnungsdetail angezeigt:
- Chronologische Auflistung aller Status-Änderungen
- Zeitstempel
- Grund der Änderung
- Benutzer

---

## 3. Stornierung durch Korrekturbeleg

### Anforderung
Rechnungen dürfen nicht gelöscht werden. Stornierungen müssen durch Gegenbuchungen erfolgen.

### Implementierung

#### Stornorechnung-Workflow

**Route:** `/invoices/<id>/cancel` (GET + POST)  
**Datei:** `app.py` - Funktion `create_cancellation_invoice()`

**Ablauf:**
1. **Validierung**
   - Nur für Status `sent` oder `paid`
   - Rechnung darf nicht bereits storniert sein

2. **Neue Rechnung erstellen**
   - Rechnungsnummer: `STORNO-{YYYYMMDD}-{laufende Nummer}`
   - Alle Beträge: **Negativ**
   - Gleiche Positionen wie Original
   - Referenz auf Original-Rechnung in Notizen

3. **Positionen übernehmen**
   ```python
   for item in original_invoice.line_items:
       storno_item = LineItem(
           description=item.description,
           quantity=-item.quantity,  # NEGATIV!
           unit_price=item.unit_price,
           total=-item.total,  # NEGATIV!
           tax_rate=item.tax_rate,
           product_id=item.product_id
       )
   ```

4. **Bestandsrückbuchung**
   - Produkte: `product.number += quantity`
   - Kommissionsware: `consignment_item.quantity_remaining += quantity`

5. **Status-Updates**
   - Original-Rechnung: Status → `cancelled`
   - Stornorechnung: Status → `draft`
   - Beide Status-Änderungen werden protokolliert

6. **Hash-Generierung**
   - Stornorechnung erhält eigenen SHA-256 Hash

#### Benutzeroberfläche
**Template:** `templates/invoices/create_cancellation.html`

- Anzeige der Original-Rechnungsdaten
- Eingabefeld für Stornierungsgrund (Pflichtfeld)
- Übersicht der zu stornierenden Positionen
- Warnung über Unumkehrbarkeit
- Bestätigung erforderlich

---

## 4. PDF-Archivierung mit Hash-Verifizierung

### Anforderung
PDFs müssen unveränderbar archiviert und ihre Integrität prüfbar sein.

### Implementierung

#### Datenbank-Modell: `InvoicePdfArchive`
**Datei:** `models.py`

```sql
CREATE TABLE invoice_pdf_archive (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    pdf_filename VARCHAR(255) NOT NULL,
    pdf_hash VARCHAR(64) NOT NULL,
    file_size INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    archived_by VARCHAR(100) NOT NULL,
    UNIQUE (invoice_id, pdf_filename)
);
```

**Erfasste Informationen:**
- **pdf_filename**: Name der PDF-Datei
- **pdf_hash**: SHA-256 Hash des PDF-Inhalts
- **file_size**: Dateigröße in Bytes
- **created_at**: Zeitpunkt der Archivierung
- **archived_by**: Benutzer

#### Automatische Archivierung beim Download
**Route:** `/invoices/<id>/pdf`  
**Datei:** `app.py` - Funktion `download_invoice_pdf()`

**Ablauf:**
1. PDF wird generiert
2. **Beim ersten Download** (wenn Status = `sent`):
   - SHA-256 Hash wird berechnet
   - Archive-Eintrag wird erstellt
   - PDF wird ausgeliefert
3. Bei weiteren Downloads wird der Hash nicht neu berechnet

```python
# Hash berechnen
pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()

# Archiv-Eintrag erstellen
archive = InvoicePdfArchive(
    invoice_id=invoice.id,
    pdf_filename=pdf_filename,
    pdf_hash=pdf_hash,
    file_size=len(pdf_bytes),
    archived_by='System'
)
```

#### PDF-Verifizierung
**Datei:** `models.py` - Methode `InvoicePdfArchive.verify_pdf()`

```python
def verify_pdf(self, pdf_path: str) -> bool:
    """Verifiziert die Integrität einer PDF-Datei"""
    with open(pdf_path, 'rb') as f:
        current_hash = hashlib.sha256(f.read()).hexdigest()
    return current_hash == self.pdf_hash
```

#### Anzeige im Frontend
**Template:** `templates/invoices/view.html`

- Liste aller archivierten PDFs
- Dateiname, Größe, Archivierungszeitpunkt
- Vollständiger SHA-256 Hash zur Verifizierung
- Hinweis auf GoBD-Konformität

---

## 5. Datenbankstruktur

### Entity-Relationship

```
Invoice (1) ←→ (N) InvoiceStatusLog
Invoice (1) ←→ (N) InvoicePdfArchive
Invoice (1) ←→ (N) LineItem
```

### Indizes für Performance

```sql
-- Status-Historie
CREATE INDEX idx_invoice_status_log_invoice_id ON invoice_status_log(invoice_id);
CREATE INDEX idx_invoice_status_log_changed_at ON invoice_status_log(changed_at);

-- PDF-Archiv
CREATE INDEX idx_invoice_pdf_archive_invoice_id ON invoice_pdf_archive(invoice_id);
CREATE INDEX idx_invoice_pdf_archive_pdf_hash ON invoice_pdf_archive(pdf_hash);
```

---

## 6. Migration bestehender Daten

### Migrations-Skript
**Datei:** `migrate_add_gobd_tables.py`

**Was wurde migriert:**
1. Erstellung der neuen Tabellen
2. Indizes erstellt
3. Für alle bestehenden Rechnungen wurde ein initialer Status-Log-Eintrag erstellt:
   - `old_status = NULL`
   - `new_status = <aktueller Status>`
   - `reason = 'Initial migration - existing invoice'`

**Ausführung:**
```bash
python migrate_add_gobd_tables.py
```

**Ergebnis:**
- ✅ 2 neue Tabellen erstellt
- ✅ 4 Indizes angelegt
- ✅ 9 bestehende Rechnungen migriert

---

## 7. Verfahrensdokumentation

### 7.1 Prozess: Rechnung erstellen

1. **Entwurf erstellen** (Status: `draft`)
   - Kundendaten eingeben
   - Positionen hinzufügen
   - Rechnung kann noch bearbeitet oder gelöscht werden
   
2. **Optional: Entwurf löschen**
   - ℹ️ Solange Status `draft`, kann die Rechnung gelöscht werden
   - Button "Entwurf löschen" in Rechnungsansicht
   - Bestätigung erforderlich
   - ➜ Rechnung wird komplett aus der Datenbank entfernt
   - **Wichtig:** Nach Versendung (Status `sent`) ist Löschung nicht mehr möglich!

3. **PDF generieren und prüfen**
   - Vorschau erstellen
   - Auf Fehler prüfen

4. **Als "Versendet" markieren** (Status: `sent`)
   - ⚠️ **Ab jetzt GoBD-relevant!**
   - ➜ Status-Log-Eintrag wird erstellt
   - ➜ Aufbewahrungspflicht beginnt (10 Jahre)
   - ➜ Unveränderbarkeit greift
   - ➜ Löschung nicht mehr möglich

5. **PDF herunterladen**
   - ➜ Beim ersten Download: PDF-Hash wird berechnet und archiviert

6. **Als "Bezahlt" markieren** (Status: `paid`)
   - ➜ Status-Log-Eintrag wird erstellt

### 7.2 Prozess: Rechnung stornieren

**Nur für Status `sent` oder `paid`!**

1. Rechnung öffnen (muss Status `sent` oder `paid` haben)
2. Klick auf "Stornorechnung erstellen"
3. Grund für Stornierung eingeben (Pflichtfeld)
4. Bestätigen
   - ➜ Neue Rechnung mit negativen Beträgen wird erstellt
   - ➜ Bestand wird zurückgebucht
   - ➜ Original-Rechnung erhält Status `cancelled`
   - ➜ Beide Status-Änderungen werden protokolliert
5. Stornorechnung versenden (wie normale Rechnung)

**Wichtig für Entwürfe:** Entwürfe (Status `draft`) können nicht storniert werden, sondern müssen gelöscht werden!

### 7.3 Prozess: Integrität prüfen

#### Rechnungsdaten
- Hash wird automatisch bei jedem Aufruf geprüft
- Bei Manipulation: Rote Warnung wird angezeigt

#### PDF-Dateien
```python
# Manuell (Python):
from models import InvoicePdfArchive
archive = InvoicePdfArchive.query.filter_by(invoice_id=123).first()
is_valid = archive.verify_pdf('/path/to/invoice.pdf')
```

---

## 8. Bestandsanpassungen (Eigenentnahme, Inventur)

### Anforderung
Bestandsveränderungen ohne Verkauf (Eigenentnahme, Verderb, Inventur) müssen GoBD-konform dokumentiert werden, auch wenn keine Rechnung erstellt wird.

### Implementierung

#### Datenbank-Modell: `StockAdjustment`
**Datei:** `models.py`

```sql
CREATE TABLE stock_adjustments (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,              -- Positiv = Zugang, Negativ = Abgang
    old_stock INTEGER NOT NULL,             -- Bestand vor Anpassung
    new_stock INTEGER NOT NULL,             -- Bestand nach Anpassung
    adjustment_type adjustment_type_enum NOT NULL,
    reason TEXT NOT NULL,                   -- Pflichtfeld für GoBD
    adjusted_by INTEGER NOT NULL REFERENCES users(id),
    adjusted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    document_number VARCHAR(50) UNIQUE      -- Beleg-Nummer für Eigenentnahmen
);
```

**Anpassungstypen:**
- `eigenentnahme` - Privater Verbrauch (§ 3 Abs. 1b Nr. 1 UStG)
- `geschenk` - Unentgeltliche Zuwendung
- `verderb` - Verdorbene/unverkäufliche Ware
- `bruch` - Beschädigte Ware
- `inventur_plus` - Inventur-Mehrbestand
- `inventur_minus` - Inventur-Minderbestand
- `korrektur` - Fehlerkorrektur
- `sonstiges` - Andere Gründe

#### Beleg-Nummern für Eigenentnahmen
**Format:** `ENT-YYYYMMDD-####`

Beispiel: `ENT-20251108-0001`

**Generierung:**
```python
today = datetime.now().date()
prefix = f"ENT-{today.strftime('%Y%m%d')}"
# Finde letzte Nummer des Tages
last_doc = StockAdjustment.query.filter(
    StockAdjustment.document_number.like(f"{prefix}%")
).order_by(StockAdjustment.document_number.desc()).first()
# Inkrementiere
next_num = (int(last_doc.document_number.split('-')[-1]) + 1) if last_doc else 1
document_number = f"{prefix}-{next_num:04d}"
```

**Wann wird Beleg-Nummer erstellt:**
- ✅ Bei `eigenentnahme` (privater Verbrauch)
- ✅ Bei `geschenk` (unentgeltliche Zuwendung)
- ❌ **Nicht** bei Inventur-Korrekturen (interne Buchung)
- ❌ **Nicht** bei Verderb/Bruch (nur Dokumentation)

#### Unveränderbarkeit
- **Keine Löschung** - Bestandsanpassungen können nicht gelöscht werden
- **Keine Änderung** - Einträge sind unveränderbar
- **Vollständige Historie** - Alle Anpassungen bleiben dauerhaft gespeichert

#### Route-Implementierung
**Datei:** `app.py`

**Neue Anpassung erstellen:**
```python
@app.route('/stock-adjustments/create', methods=['GET', 'POST'])
@login_required
def create_stock_adjustment():
    # Validierung
    if new_stock < 0:
        flash('Bestand würde negativ werden!', 'error')
        return redirect(...)
    
    # Erstelle Anpassung
    adjustment = StockAdjustment(
        product_id=product.id,
        quantity=quantity,
        old_stock=old_stock,
        new_stock=new_stock,
        adjustment_type=adjustment_type,
        reason=reason,
        adjusted_by=current_user.id,
        document_number=document_number  # Falls eigenentnahme/geschenk
    )
    
    # Bestand aktualisieren
    product.number = new_stock
    db.session.commit()
```

#### PDF-Export (GoBD Z2-Datenzugriff)
**Route:** `/stock-adjustments/export-pdf`

Exportiert alle Bestandsanpassungen als PDF-Übersicht:
- Datum, Produkt, Typ, Menge, Bestand vorher/nachher
- Grund, Benutzer, Beleg-Nummer
- Zeitraum-Filter möglich
- Landschaftsformat (A4 quer)

**Verwendung bei Betriebsprüfung:**
```bash
# Export für Zeitraum
GET /stock-adjustments/export-pdf?start_date=2024-01-01&end_date=2024-12-31

# Export nur Eigenentnahmen
GET /stock-adjustments/export-pdf?adjustment_type=eigenentnahme
```

### Steuerliche Relevanz

#### Eigenentnahme (§ 3 Abs. 1b Nr. 1 UStG)
Entnahme von Gegenständen für private Zwecke ist **umsatzsteuerpflichtig**.

**Bewertung:**
- Kleinunternehmer (§ 19 UStG): Keine USt-Pflicht
- Regelbesteuerung: USt auf Einkaufspreis/Herstellungskosten
- Landwirt (§ 24 UStG): Durchschnittssatz

**Dokumentation erforderlich:**
- ✅ Datum der Entnahme
- ✅ Menge und Bezeichnung
- ✅ Grund ("privater Verbrauch")
- ✅ Beleg-Nummer

#### Geschenke
Unentgeltliche Zuwendungen > 35 EUR sind USt-pflichtig.

**Dokumentation erforderlich:**
- ✅ Empfänger (im Feld "Grund" vermerken)
- ✅ Anlass
- ✅ Wert

#### Verderb/Bruch
Keine steuerliche Relevanz, aber Dokumentation notwendig:
- Nachweis für Bestandsminderung
- Plausibilität für Inventur
- Betriebsprüfung

### Verfahrensdokumentation

**Prozess: Eigenentnahme dokumentieren**

1. Navigation: **📝 Anpassungen** → "Neue Anpassung"
2. Produkt auswählen
3. Typ: "🏠 Eigenentnahme"
4. Menge: Negativ (z.B. `-5`)
5. Grund: "5 Gläser Honig für privaten Verbrauch entnommen"
6. Speichern
   - ➜ Beleg-Nummer wird generiert: `ENT-20251108-0001`
   - ➜ Bestand wird automatisch reduziert
   - ➜ Eintrag ist unveränderbar

**Prozess: PDF-Export für Steuerberater**

1. Navigation: **📝 Anpassungen**
2. Klick auf "PDF exportieren"
3. Optional: Filter setzen (Zeitraum, Typ)
4. PDF wird generiert und heruntergeladen

### Beispiel-Einträge

| Datum | Produkt | Typ | Menge | Alt → Neu | Grund | Beleg-Nr. |
|-------|---------|-----|-------|-----------|-------|-----------|
| 08.11.2024 | Waldhonig 500g | Eigenentnahme | -5 | 100 → 95 | 5 Gläser für privaten Verbrauch | ENT-20241108-0001 |
| 08.11.2024 | Blütenhonig 500g | Geschenk | -2 | 150 → 148 | Geschenk an Nachbarn (Weihnachten) | ENT-20241108-0002 |
| 08.11.2024 | Rapshonig 500g | Inventur + | +10 | 80 → 90 | Inventur: 10 Gläser mehr gefunden | - |
| 08.11.2024 | Akazienhonig 500g | Verderb | -3 | 50 → 47 | Kristallisiert, nicht mehr verkaufbar | - |

---

## 9. Backup-Strategie

### Empfohlene Maßnahmen

1. **Datenbank-Backup**
   - Täglich vollständig sichern
   - Transaktionslogs archivieren
   - Aufbewahrung: **10 Jahre** (gesetzliche Frist)

2. **PDF-Dateien**
   - Separate Sicherung aller PDFs
   - Aufbewahrung: **10 Jahre**
   - Optional: Zusätzliche Hash-Datei erstellen

3. **Beispiel-Backup-Skript:**
   ```bash
   #!/bin/bash
   # Datenbank
   pg_dump -U user rechnungen > backup_$(date +%Y%m%d).sql
   
   # PDFs
   tar -czf pdfs_$(date +%Y%m%d).tar.gz invoices/pdfs/
   
   # Hashes exportieren
   psql -U user -d rechnungen -c "COPY invoice_pdf_archive TO '/backups/hashes_$(date +%Y%m%d).csv' CSV HEADER;"
   ```

---

## 9. Datenschutz (DSGVO)

### Personenbezogene Daten

**Gespeichert in:**
- `customers`: Name, E-Mail, Adresse, Telefon
- `invoices`: Kundenbezug
- `invoice_status_log`: Benutzer (bei Implementierung)

### Löschung
**Problem:** GoBD verbietet Löschung, DSGVO fordert Löschung

**Lösung:**
- Anonymisierung statt Löschung:
  ```sql
  UPDATE customers
  SET first_name = 'ANONYMISIERT',
      last_name = 'ANONYMISIERT',
      email = 'deleted@example.com',
      phone = NULL,
      address = NULL
  WHERE id = ?;
  ```
- Rechnungen bleiben bestehen (10 Jahre Aufbewahrungspflicht)
- Hash-Werte bleiben unverändert (keine personenbezogenen Daten)

---

## 10. Betriebsprüfung (Finanzamt)

### Z1 - Datenzugriff
Das System ermöglicht den gesetzlich geforderten Datenzugriff:

1. **Z1 (Nur-Lesezugriff)**
   - Rechnung-Detailansicht
   - Status-Historie-Anzeige
   - PDF-Download mit Hash-Verifizierung

2. **Z2 (Maschinell auswertbare Datenträger)**
   ```bash
   # Rechnungen exportieren (CSV)
   psql -U user -d rechnungen -c "COPY (
       SELECT i.*, c.company_name, c.first_name, c.last_name
       FROM invoices i
       LEFT JOIN customers c ON i.customer_id = c.id
   ) TO '/export/invoices.csv' CSV HEADER;"
   
   # Status-Historie exportieren
   psql -U user -d rechnungen -c "COPY invoice_status_log TO '/export/audit_trail.csv' CSV HEADER;"
   
   # PDF-Hashes exportieren
   psql -U user -d rechnungen -c "COPY invoice_pdf_archive TO '/export/pdf_hashes.csv' CSV HEADER;"
   
   # Bestandsanpassungen exportieren (NEU)
   psql -U user -d rechnungen -c "COPY stock_adjustments TO '/export/stock_adjustments.csv' CSV HEADER;"
   
   # Oder: PDF-Export über Weboberfläche
   # → Navigation: 📝 Anpassungen → "PDF exportieren"
   ```

3. **Z3 (Unmittelbarer Datenzugriff)**
   - Finanzamt erhält Datenbank-Lesezugriff
   - Oder: Read-Only-Benutzer anlegen

### Verfahrensdokumentation für Betriebsprüfung

**Dieses Dokument (`GOBD_COMPLIANCE.md`) dient als Verfahrensdokumentation!**

Zusätzlich bereithalten:
- Systembeschreibung (diese Datei)
- Installationsanleitung
- Backup-Konzept
- Benutzerhandbuch
- Migrationsprotokoll

---

## 11. Checkliste: GoBD-Konformität

| Anforderung | Status | Implementierung |
|-------------|--------|-----------------|
| ✅ Unveränderbarkeit | Erfüllt | Status-Workflow-Validierung, Entwürfe löschbar |
| ✅ Nachvollziehbarkeit | Erfüllt | `InvoiceStatusLog` + `StockAdjustment` (Audit Trail) |
| ✅ Vollständigkeit | Erfüllt | Keine Löschung ab Status `sent`, nur Stornierung |
| ✅ Richtigkeit | Erfüllt | SHA-256 Hash-Prüfung |
| ✅ Zeitgerechte Buchung | Erfüllt | Automatische Timestamps (Mikrosekunden-genau) |
| ✅ Ordnung | Erfüllt | Fortlaufende Rechnungsnummern + Beleg-Nummern |
| ✅ Sicherheit | Erfüllt | PDF-Hashes, Datenbankindizes |
| ✅ Verfügbarkeit | Erfüllt | Backup-Konzept |
| ✅ Datenzugriff | Erfüllt | Export-Funktionen (PDF, SQL) |
| ✅ Prüfbarkeit | Erfüllt | Vollständige Dokumentation |
| ✅ Entwurfsverwaltung | Erfüllt | Löschung nur bei Status `draft` |
| ✅ Bestandsanpassungen | Erfüllt | Eigenentnahme mit Beleg-Nummern, PDF-Export |

---

## 12. Technische Details

### Verwendete Hash-Algorithmen
- **SHA-256** für Rechnungsdaten und PDFs
- Kodierung: Hexadezimal (64 Zeichen)

### Zeitstempel
- Format: `TIMESTAMP` (Mikrosekunden-genau)
- Zeitzone: UTC (empfohlen) oder Serverzeit
- **Wichtig:** Keine nachträgliche Änderung!

### Software-Versionen
- Python: 3.8+
- Flask: 3.0+
- SQLAlchemy: 2.0+
- PostgreSQL: 12+
- ReportLab: 4.0+ (PDF-Generierung)

---

## 13. Erweiterungsmöglichkeiten

### Zukünftige Verbesserungen

1. **Benutzer-Authentifizierung**
   - Ersetze `"System"` durch echte Benutzernamen
   - Implementiere Login/Logout
   - Erfasse IP-Adressen bei Änderungen

2. **Digitale Signatur**
   - PDF-Signierung mit Zertifikat
   - Langzeit-Archivierung (PAdES)

3. **Automatische Backups**
   - Cron-Job für tägliche Backups
   - Cloud-Synchronisation
   - Integritätsprüfung der Backups

4. **API-Endpunkt für Verifizierung**
   ```python
   @app.route('/api/verify/<invoice_id>')
   def verify_invoice_api(invoice_id):
       # Prüfe Hash, PDF-Hash
       # Gebe JSON zurück
   ```

5. **Erweiterte Audit-Logs**
   - IP-Adresse
   - User-Agent
   - Geänderte Felder (vor/nach)

---

## 14. Häufige Fragen (FAQ)

**Q: Kann ich eine Rechnung löschen?**  
A: **Entwürfe (Status `draft`) JA** - Diese sind noch nicht geschäftsrelevant und können gelöscht werden. **Versendete/Bezahlte Rechnungen NEIN** - Diese müssen 10 Jahre aufbewahrt werden. Verwenden Sie stattdessen die Stornorechnung.

**Q: Warum kann ich einen Entwurf löschen, aber eine versendete Rechnung nicht?**  
A: Ein Entwurf ist noch keine Rechnung im steuerrechtlichen Sinne. Die GoBD-Aufbewahrungspflicht beginnt erst mit der Versendung (Status `sent`). Ab diesem Zeitpunkt ist die Rechnung unveränderbar und muss 10 Jahre aufbewahrt werden.

**Q: Was ist der Unterschied zwischen Löschen und Stornieren?**  
A: 
- **Löschen** (nur Entwürfe): Rechnung wird komplett aus der Datenbank entfernt
- **Stornieren** (versendete/bezahlte): Originalrechnung bleibt bestehen, neue Stornorechnung mit negativen Beträgen wird erstellt

**Q: Was passiert, wenn der Hash nicht übereinstimmt?**  
A: Das System zeigt eine Warnung an. Die Daten wurden möglicherweise manipuliert oder die Datenbankintegrität ist beschädigt.

**Q: Muss ich PDFs archivieren?**  
A: Ja. Das System speichert automatisch einen Hash beim ersten Download. Die PDF-Dateien selbst sollten in einem separaten Backup gesichert werden.

**Q: Was ist, wenn ein Kunde Löschung seiner Daten fordert (DSGVO)?**  
A: Anonymisieren Sie die Kundendaten. Die Rechnung selbst muss 10 Jahre aufbewahrt werden (GoBD hat Vorrang).

**Q: Wie kann ich die Integrität einer PDF-Datei prüfen?**  
A: Verwenden Sie die `verify_pdf()` Methode oder berechnen Sie den SHA-256 Hash manuell und vergleichen Sie ihn mit dem gespeicherten Hash.

---

## 15. Kontakt & Support

**Entwickler:** [Ihr Name]  
**Version:** 1.0  
**Letzte Aktualisierung:** Dezember 2024

**Bei Fragen zur GoBD-Konformität:**
- Steuerberater konsultieren
- Fachliteratur: BMF-Schreiben vom 28.11.2019
- IHK-Beratung

---

## 16. Lizenz & Haftungsausschluss

Dieses System wurde nach bestem Wissen und Gewissen entwickelt, um die GoBD-Anforderungen zu erfüllen. Eine rechtliche Prüfung durch einen Steuerberater wird empfohlen.

**Keine Gewährleistung:**  
Die korrekte Implementierung und Anwendung der GoBD liegt in der Verantwortung des Anwenders.

---

**Ende der Verfahrensdokumentation**
