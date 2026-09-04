# PROJECT.md

## Hintergrund

GoBD-konforme Rechnungsverwaltung fuer einen Imkereibetrieb mit
mehreren Vertriebswegen. Kein generisches Rechnungstool -- die
Kernanforderung ist steuerrechtliche Konformitaet fuer einen
Kleingewerbe-/Direktvermarkter-Kontext (Details in
GOBD_COMPLIANCE.md): Belege sind nach Versand unveraenderbar, jede
Korrektur laeuft ueber einen Korrekturbeleg statt einer Loeschung, und
alle Statusaenderungen werden in einem Audit-Trail protokolliert.

## Geschaeftsmodell / Vertriebswege

- **Direktverkauf**: normale Rechnungen an Endkunden
- **Wiederverkaeufer/Reseller**: Lieferscheine + Kommissionslager
  (Ware geht auf Kommission raus, Reseller verkauft weiter, 4
  unterschiedliche Reseller-Typen mit eigenem Steuer-/PWA-Verhalten)
- **Markt-/Hausverkauf**: eigenes POS/Kassen-System fuer Barverkauf
- Drei Steuermodelle: Standard-MwSt, Kleinunternehmerregelung, und
  §24 UStG Durchschnittssatzbesteuerung fuer landwirtschaftliche
  Urproduktion (z.B. Honig)

## Architektur auf einen Blick

Flask-3.0-Monolith (ein Prozess, keine Microservices), SQLAlchemy-ORM,
serverseitig gerenderte Jinja2-Templates plus eine schlanke PWA/JWT-API
fuer mobile Nutzung. PDF-Erzeugung (Rechnungen, Lieferscheine,
Mahnungen, Jahresbericht) mit ReportLab, inkl. scanbarem EPC-QR-Code
fuer SEPA-Ueberweisungen direkt aus der Rechnung. E-Mail-Import per
IMAP fuer automatisierte Rechnungserstellung aus Shop-Bestellungen.

Technische Details, Modulkarte und bekannte Fallen: siehe AGENTS.md.

## Deployment-Varianten

1. **docker-compose.yml** -- Produktivbetrieb: Traefik-Reverse-Proxy,
   Let's-Encrypt-Zertifikate per DNS-Challenge ueber http.net,
   CrowdSec-Absicherung.
2. **docker-compose.integrated.yml** -- fuer bestehende externe
   Traefik/CrowdSec/DB-Infrastruktur (Details: SETUP_INTEGRATED.md).
3. **docker-compose.test.yml** -- minimaler LAN-Testbetrieb ohne
   Traefik/TLS, direktes Port-Mapping. Fuer Probelaeufe hinter einem
   eigenen Reverse-Proxy (aktuell: Caddy auf einem separaten
   Gateway-Host) oder rein internen Test.

## Aktueller Stand (Stand 2026-09-04)

- DNS-Challenge fuer Let's Encrypt laeuft ueber http.net statt
  Cloudflare (eigene DNS-Zonen werden bei http.net verwaltet).
- Probelauf auf einem separaten LAN-Host eingerichtet
  (docker-compose.test.yml), erreichbar per Caddy-Reverse-Proxy unter
  einer internen `.home.arltus.de`-Domain -- kein Internet-Deployment.
- Alembic ist das aktuelle Migrationswerkzeug (siehe MIGRATIONS.md);
  zwei aeltere Migrationsverzeichnisse sind Altlasten (siehe AGENTS.md
  Abschnitt "Dead Ends").
- Ein Bug im `/health`-Endpoint (SQLAlchemy-2.x-Inkompatibilitaet mit
  rohem SQL-String) wurde behoben.
- Groessere vorangegangene Feature-Welle: Alembic-Einfuehrung,
  DSGVO-Anonymisierung fuer Kunden, GoBD-dokumentierte
  Bestandsanpassungen, Jahresumsatzbericht, Reseller-Flag,
  benutzerspezifische 2FA-Pflicht.
- Laufende Cleanup-Arbeit: Pylint-/Flake8-/djLint-Vereinheitlichung,
  Zeilenlaenge projektweit auf 160 Zeichen konsolidiert.

## Bekannte technische Schulden

Siehe AGENTS.md fuer Details -- kurz zusammengefasst: `app.py` ist ein
3300-Zeilen-Monolith ohne Blueprint-Aufteilung, es gibt keine
automatisierten Tests, und es bestehen Postgres/MariaDB-Inkonsistenzen
aus einem nicht vollstaendig nachgezogenen Datenbankwechsel.

## Team

Einzelentwickler-/Homelab-Projekt (privates Repository).
