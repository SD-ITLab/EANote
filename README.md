# EAN-Tool

Ein leichtgewichtiges Web-Tool zur Erfassung und Protokollierung von Seriennummern mit Barcode-/DataMatrix-Ausgabe im PDF-Format.

---

## Features

* **EAN-Lookup**: Automatische Produkt-Recherche per EAN über OpenIcecat.
* **Seriennummern-Protokoll**: Erfassung beliebig vieler Seriennummern pro Position.
* **Barcode & DataMatrix**: Ausgabe von Barcodes bzw. DataMatrix im PDF.
* **PDF-Export**: Generierung eines Seriennummernprotokolls mit Logo, Briefkopf und Tabellen.
* **Zwei Benutzerrollen**:

  * **Admin**: Vollzugriff auf Produktverwaltung und Einstellungen.
  * **Techniker**: Erfassung neuer Protokolle und Ansicht bestehender.

---

## Quickstart

### 1. `.env.example` anpassen

Erstelle eine Kopie `.env` aus der Vorlage `.env.example` und passe dort deine Zugangsdaten an:

```env
# -------------------------------
# FELDER DIE DU ANPASSEN SOLLTEST
# -------------------------------

# MariaDB
MARIADB_ROOT_PASSWORD=dein_root_passwort
MARIADB_DATABASE=dein_datenbankname
MARIADB_USER=dein_db_user
MARIADB_PASSWORD=dein_db_passwort

# OpenIcecat Zugang
ICE_USER=dein_openicecat_user
ICE_LANG=de

# Anwendungspasswörter
EAN_ADMIN_PW=dein_admin_passwort
TECH_PW=dein_tech_passwort

# Zeitzone (z.B. Europe/Berlin)
TZ=Europe/Berlin

# DB-Verbindungsstring (wird aus den Variablen zusammengestellt)
# DB_DSN=mysql+pymysql://${MARIADB_USER}:${MARIADB_PASSWORD}@ean-db:3306/${MARIADB_DATABASE}
```

### 2. Docker Compose starten

```bash
docker-compose up -d
```

Das Setup besteht aus drei Containern:

* **db** (MariaDB)
* **ean-tool** (Flask-App)
* **phpmyadmin** (MySQL-Admin-Oberfläche)

### 3. Webinterface

* **Techniker-Login**: `http://localhost:8005/login` (Rollentrennung: Techniker vs. Admin)
* **PHPMyAdmin**:        `http://localhost:8080/`

---

## Struktur & Konfiguration

```yaml
services:
  db:
    image: mariadb:11
    restart: unless-stopped
    env_file:
      - .env
    environment:
      MARIADB_ROOT_PASSWORD: ${MARIADB_ROOT_PASSWORD}
      MARIADB_DATABASE:      ${MARIADB_DATABASE}
      MARIADB_USER:          ${MARIADB_USER}
      MARIADB_PASSWORD:      ${MARIADB_PASSWORD}
    volumes:
      - db:/var/lib/mysql
    healthcheck:
      test: ["CMD-SHELL", "mariadb-admin ping -u${MARIADB_USER} -p${MARIADB_PASSWORD} --silent"]
      interval: 5s
      timeout: 3s
      retries: 20
      start_period: 5s
    networks:
      proxy-manager:
        aliases:
          - ean-db

  ean-tool:
    build: .
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    env_file:
      - .env
    environment:
      ICE_USER:     ${ICE_USER}
      ICE_LANG:     ${ICE_LANG}
      TZ:           ${TZ}
      EAN_ADMIN_PW: ${EAN_ADMIN_PW}
      TECH_PW:      ${TECH_PW}
      DB_DSN:       "mysql+pymysql://${MARIADB_USER}:${MARIADB_PASSWORD}@ean-db:3306/${MARIADB_DATABASE}"
    ports:
      - "8005:8000"
    networks:
      - proxy-manager

  phpmyadmin:
    image: phpmyadmin
    restart: unless-stopped
    depends_on:
      db:
        condition: service_started
    env_file:
      - .env
    environment:
      PMA_HOST:      ean-db
      PMA_USER:      ${MARIADB_USER}
      PMA_PASSWORD:  ${MARIADB_PASSWORD}
      PMA_AUTH_TYPE: config
    ports:
      - "8080:80"
    networks:
      - proxy-manager

volumes:
  db:

networks:
  proxy-manager:
    external: true
    name: proxy-manager_default
```

---

## Lizenz

MIT © SD-ITLab

---
