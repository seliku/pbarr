# PBArr - German Public Broadcasting Archive Indexer

Automatischer Download-Manager für deutsche Mediatheken (ARD, ZDF, 3SAT, BR, etc.) mit intelligenter Episode-Erkennung und Sonarr-Integration.

**PBArr cached Mediathek-Inhalte und ermöglicht gezielte Downloads basierend auf TVDB-Matching und flexiblen Filtern.**

## 🏗️ Architektur

```
MediathekViewWeb API → PBArr Cache → TVDB Matching → Filter → Download Queue → yt-dlp
```

1. **MediathekViewWeb**: Zentrales Verzeichnis aller deutschen Mediathek-Inhalte
2. **PBArr Cache**: Stündliche Synchronisation und lokale Speicherung
3. **TVDB Matching**: Automatische Episode-Erkennung via TheTVDB API
4. **Filter-System**: Dauer, Keywords, Sender-basierte Filterung
5. **Download Queue**: Asynchrone Verarbeitung mit yt-dlp

## 🎯 Features

- ✅ Dashboard zur Serie-Verwaltung mit Filter-Einstellungen
- ✅ Intelligentes Episode-Matching (MediathekViewWeb ↔ TVDB)
- ✅ Min/Max Dauer-Filter (z.B. nur Episoden 20-120 Min)
- ✅ Ausschluss von Audiodeskription, Gebärdensprache, etc.
- ✅ Automatische Downloads mit yt-dlp
- ✅ Sonarr-Integration für Library-Management
- ✅ PostgreSQL-Datenbank für persistente Speicherung

## 🚀 Installation - 3 Schritte

### Schritt 1: docker-compose.yml kopieren

Kopiere diesen Inhalt in eine neue Datei `docker-compose.yml`:

```
version: '3.8'

services:
  pbarr:
    image: ghcr.io/seliku/pbarr:latest
    container_name: pbarr
    restart: unless-stopped
    
    ports:
      - "8070:8000"
    
    environment:
      DATABASE_URL: postgresql://pbarr:changeme123@postgres:5432/pbarr_db
      LOG_LEVEL: INFO
    
    depends_on:
      postgres:
        condition: service_healthy
    
    volumes:
      - ./downloads:/app/downloads
      - ./logs:/app/logs
      - ./data:/app/data

  postgres:
    image: postgres:15-alpine
    container_name: pbarr-postgres
    restart: unless-stopped
    
    environment:
      POSTGRES_USER: pbarr
      POSTGRES_PASSWORD: changeme123
      POSTGRES_DB: pbarr_db
    
    volumes:
      - postgres_data:/var/lib/postgresql/data
    
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U pbarr"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

### Schritt 2: Starten

```
docker compose up -d
```

Öffne im Browser: **http://[deine-server-ip]:[dein-port]/admin**

### Schritt 3: Konfiguration im Admin-Panel

1. Gehe zu **http://[deine-server-ip]:[dein-port]/admin**
2. Konfiguriere die API-Keys:
   - **TVDB API Key:** Dein TheTVDB API-Key
   - **Sonarr URL:** `http://sonarr:8989` (oder deine Sonarr-Adresse)
   - **Sonarr API Key:** Dein Sonarr API-Key

## 🎬 Erste Schritte

1. Serie hinzufügen (z.B. "Tatort")
2. Filter einstellen:
   - Minimale Dauer: 0 Min
   - Maximale Dauer: 360 Min
   - Ausschlüsse: "klare Sprache, Audiodeskription, Gebärdensprache"
3. Dashboard zeigt verfügbare Episoden

## 🔄 Updates einspielen

```
docker compose pull pbarr
docker compose up -d
```

### Datenbank-Migrationen

Bei Updates können Datenbank-Migrationen nötig sein:

```bash
# Migration-Scripts ausführen (befinden sich im app/ Verzeichnis)
docker compose exec pbarr python app/migrate_watchlist.py
docker compose exec pbarr python app/migrate_episode_monitoring.py

# Oder alle Migrationen automatisch ausführen
docker compose exec pbarr find app/ -name "migrate_*.py" -exec python {} \;
```

## 🛠 Troubleshooting

### Logs anschauen

```
docker compose logs pbarr -f
```

### Container neu starten

```
docker compose restart pbarr
```

### Datenbank zurücksetzen (WARNUNG: Löscht alle Daten!)

```
docker compose down -v
docker compose up -d
```

### API-Port 8000 bereits in Verwendung?

Ändere in `docker-compose.yml`:

```
ports:
  - "8080:8000"  # Neuer Port: 8080
```

Dann: `docker compose up -d`

## 🔧 Konfiguration

### Admin-Panel Konfiguration

Die Hauptkonfiguration erfolgt über das **Admin-Panel** (`/admin`):

- **TVDB API Key:** Für Episode-Matching mit TheTVDB
- **Sonarr URL:** Adresse deines Sonarr-Servers
- **Sonarr API Key:** Für Sonarr-Integration

### Filter im Dashboard

- **Min-Dauer:** Mindestlänge in Minuten (0 = keine Einschränkung)
- **Max-Dauer:** Maximale Länge (360 = 6 Stunden)
- **Ausschlüsse:** Keywords trennen mit ", " z.B. `klare Sprache, Audiodeskription, Gebärdensprache`

## 🐛 Probleme?

Erstelle ein Issue: https://github.com/seliku/pbarr/issues

## 📄 Lizenz

MIT License

---

**Version:** 1.0.0