-- PostgreSQL Berechtigungen für rechnungen_user korrigieren
-- Führen Sie dieses Skript als postgres-User aus

-- Mit der Datenbank verbinden
\c rechnungen

-- Berechtigungen für das public Schema erteilen
GRANT ALL ON SCHEMA public TO rechnungen_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO rechnungen_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO rechnungen_user;

-- Zukünftige Objekte ebenfalls berechtigen
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO rechnungen_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO rechnungen_user;
