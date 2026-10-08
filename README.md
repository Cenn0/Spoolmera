# Filament Manager

Eine schlanke, selbst gehostete Webanwendung zur Verwaltung von 3D-Druck-Filamenten. Produkte (Hersteller, Material, Farbe) und physische Rollen werden getrennt verwaltet.

## Funktionen (MVP)

- Übersicht über Rollen, Gesamtbestand, angebrochene und fast leere Rollen
- Filamentprodukte mit Material, Hersteller, Farbe und Durchmesser anlegen und bearbeiten
- Einzelne Rollen mit Startmenge, Restmenge, Lagerort und Öffnungsstatus verwalten
- Verbrauch buchen und Bestände mit dokumentiertem Grund korrigieren
- Vollständige Bestandsbewegungen pro Rolle, aktuelle Buchungen im Verlauf
- Rollen archivieren statt ihre Buchungshistorie zu löschen
- Suche und Filter nach Material und Status

## Schnellstart mit Docker

```bash
docker compose up -d --build
```

Anschließend **http://127.0.0.1:8765** öffnen. Die SQLite-Datenbank liegt im persistenten Docker-Volume `filament_data`. Das Port-Mapping ist bewusst auf den lokalen Rechner begrenzt.

## Lokal entwickeln

Python 3.12 oder neuer verwenden:

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows (PowerShell):
# .venv\\Scripts\\Activate.ps1
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

Die Anwendung ist dann unter http://127.0.0.1:8765 erreichbar. API-Dokumentation: http://127.0.0.1:8765/docs.

Tests:

```bash
python -m pytest -q
```

## Sicherheit und Datensicherung

**Kein integriertes Login:** Dieser MVP ist ausschließlich für vertrauenswürdige, lokale Umgebungen vorgesehen. Den Webdienst **nicht direkt ins Internet oder ein ungeschütztes LAN** stellen. Bei Fernzugriff einen authentifizierenden Reverse Proxy mit TLS oder einen abgesicherten VPN-Zugang einsetzen. SQLite-Daten regelmäßig sichern; bei laufendem Betrieb die SQLite-Backup-API bzw. ein konsistentes Backup verwenden, nicht nur unkoordiniert die offene Datenbankdatei kopieren.

Standard-Datenbankpfad: `.data/filaments.sqlite3`; per `FILAMENT_DB_PATH` konfigurierbar (Docker: `/data/filaments.sqlite3`).

## Entwicklungsprinzipien

- Bestand ist pro Rolle in ganzen Gramm geführt.
- Ein Verbrauch und die dazugehörige Buchung werden in **einer Datenbanktransaktion** gespeichert.
- Die Historie wird bei Bestandskorrekturen nicht überschrieben.
- Der Anfangsbestand einer Rolle ist unveränderlich; Korrekturen werden explizit gebucht.
- Keine Cloud-Dienste, keine externe JavaScript-CDN-Abhängigkeit.

## Projektstruktur

```text
app/
  main.py           API-Endpunkte
  database.py       Datenbank und Transaktionen
  models.py         Eingabevalidierung
  static/
    index.html      Benutzeroberfläche
    styles.css
    app.js
tests/              API-Tests
Dockerfile
compose.yaml
requirements*.txt
.github/workflows/   CI
```

## Spätere Erweiterungen

QR-/Barcode-Etiketten pro Rolle, Mehrbenutzerfähigkeit, Import/Export, Materialprofile, Drucker-/Slicer-Integration und automatische Restmengenbuchung. Diese Funktionen sind **noch nicht implementiert**.

Lizenz: noch nicht festgelegt.
