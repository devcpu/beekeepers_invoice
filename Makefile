.PHONY: help build up down restart logs ps clean backup restore init-db create-admin

help: ## Zeige diese Hilfe
  @grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

build: ## Docker Images bauen
  docker-compose build

up: ## Container starten
  docker-compose up -d

down: ## Container stoppen
  docker-compose down

restart: ## Container neu starten
  docker-compose restart

logs: ## Logs anzeigen (alle Services)
  docker-compose logs -f

logs-app: ## App Logs anzeigen
  docker-compose logs -f app

logs-traefik: ## Traefik Logs anzeigen
  docker-compose logs -f traefik

logs-crowdsec: ## CrowdSec Logs anzeigen
  docker-compose logs -f crowdsec

ps: ## Container Status
  docker-compose ps

clean: ## Alle Container, Volumes und Images löschen (VORSICHT!)
  docker-compose down -v
  docker system prune -af

backup: ## Datenbank Backup erstellen
  @echo "Creating backup..."
  @mkdir -p backups
  @docker-compose exec -T db pg_dump -U rechnungen_user rechnungen | gzip > backups/db_$$(date +%Y%m%d_%H%M%S).sql.gz
  @tar -czf backups/files_$$(date +%Y%m%d_%H%M%S).tar.gz invoices/ uploads/ 2>/dev/null || true
  @echo "✓ Backup created in backups/"

restore: ## Datenbank wiederherstellen (BACKUP_FILE=backup.sql.gz make restore)
  @if [ -z "$(BACKUP_FILE)" ]; then echo "Usage: BACKUP_FILE=backup.sql.gz make restore"; exit 1; fi
  @echo "Restoring $(BACKUP_FILE)..."
  @gunzip -c $(BACKUP_FILE) | docker-compose exec -T db psql -U rechnungen_user rechnungen
  @echo "✓ Database restored"

init-db: ## Datenbank initialisieren (Migrations)
  docker-compose exec app flask db upgrade

create-admin: ## Admin-User erstellen (admin/admin123)
  docker-compose exec app python -c "\
  from app import create_app, db; \
  from models import User; \
  app = create_app(); \
  with app.app_context(): \
      if User.query.filter_by(username='admin').first(): \
          print('⚠ Admin user already exists'); \
      else: \
          admin = User(username='admin', email='admin@example.com', role='admin', is_active=True); \
          admin.set_password('admin123'); \
          db.session.add(admin); \
          db.session.commit(); \
          print('✓ Admin created: admin / admin123');"

shell: ## Shell im App-Container öffnen
  docker-compose exec app /bin/bash

db-shell: ## PostgreSQL Shell öffnen
  docker-compose exec db psql -U rechnungen_user rechnungen

update: ## App aktualisieren (git pull + rebuild + restart)
  git pull
  docker-compose build app
  docker-compose up -d app
  docker-compose exec app flask db upgrade
  @echo "✓ App updated"

crowdsec-setup: ## CrowdSec Bouncer einrichten
  @echo "Generating CrowdSec Bouncer API Key..."
  @docker-compose exec crowdsec cscli bouncers add traefik-bouncer
  @echo ""
  @echo "⚠ Copy the API key and paste it in traefik/dynamic/middlewares.yml"
  @echo "  → crowdsecLapiKey: \"YOUR_KEY_HERE\""

crowdsec-metrics: ## CrowdSec Metriken anzeigen
  docker-compose exec crowdsec cscli metrics

crowdsec-decisions: ## Gebannte IPs anzeigen
  docker-compose exec crowdsec cscli decisions list

crowdsec-unban: ## IP entsperren (IP=1.2.3.4 make crowdsec-unban)
  @if [ -z "$(IP)" ]; then echo "Usage: IP=1.2.3.4 make crowdsec-unban"; exit 1; fi
  docker-compose exec crowdsec cscli decisions delete -i $(IP)
  @echo "✓ IP $(IP) unbanned"

stats: ## Container Resource Usage
  docker stats

disk: ## Docker Disk Usage
  docker system df -v

health: ## Health Check
  @echo "App Health:"
  @curl -s https://$(shell grep DOMAIN .env | cut -d '=' -f2)/health | jq . || echo "Failed"
  @echo ""
  @echo "Container Status:"
  @docker-compose ps

deploy: ## Vollständiges Deployment (build + up + init)
  make build
  make up
  sleep 10
  make init-db
  make create-admin
  @echo ""
  @echo "✓ Deployment complete!"
  @echo "  App: https://$(shell grep DOMAIN .env | cut -d '=' -f2)"
  @echo "  Login: admin / admin123"
  @echo "  ⚠ Change password immediately!"
