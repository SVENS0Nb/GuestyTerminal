# Zu GuestyTerminal beitragen

Vielen Dank für Beiträge. Vor Änderungen bitte `AGENTS.md` sowie die Architektur-
und Datenschutzabschnitte in `README.md` lesen. Änderungen an sichtbaren Feldern
müssen immer auf beiden Seiten der Home-Assistant-/ESPHome-Grenze umgesetzt und
getestet werden.

Bei Guesty-Mehrfacheinheiten müssen konkrete `unitId`, direkte `listingId`,
übergeordnete `unitTypeId` und `parentListingId` kontextbezogen auf genau ein
konfiguriertes Listing aufgelöst bleiben. Auswahl, Snapshot-Abgleich und
Payload-Erstellung müssen innerhalb eines Aktualisierungslaufs denselben
zeitzonenbewussten Zeitstempel verwenden. Laufende und zukünftige Abfragen
bleiben pro Listing kontextgebunden; mehrere Projektionen derselben Reservierung
werden vor der Normalisierung zusammengeführt. Mehrdeutige Antworten ohne
eindeutige Identität dürfen nie auf mehrere Listings verteilt werden.

## Lokale Prüfung

```bash
python3 -m pip install -r requirements-test.txt
ruff check .
ruff format --check .
mypy custom_components/guesty_terminal
python3 -m compileall -q custom_components/guesty_terminal
pytest
```

Die maßgebliche CI prüft diese Befehle sowohl mit Home Assistant 2025.12.0 als
auch mit 2026.2.3. Vor einer Veröffentlichung müssen beide Baselines und die
Coverage-Schranke aus `pyproject.toml` erfolgreich sein.

Firmwareänderungen benötigen zusätzlich eine nicht produktive
`esphome/secrets.yaml` sowie:

```bash
esphome config esphome/guestyterminal-display-1.yaml
esphome compile esphome/guestyterminal-display-1.yaml
```

Bitte keine echten Secrets, Buildverzeichnisse, Caches oder generierten
ESPHome-Output committen. Hardwareänderungen müssen im Pull Request als auf
einem realen E1001 getestet oder ausdrücklich als nicht hardwaregetestet
gekennzeichnet werden.

## Veröffentlichungen und Distribution

Vor einer Veröffentlichung müssen die Versionsangaben in Manifest,
Firmwaregenerator, Referenz-YAML und versionsabhängigen Tests übereinstimmen.
`README.md` und `CHANGELOG.md` müssen die Änderung sowie die Notwendigkeit eines
Display-Firmwareupdates eindeutig nennen.

Zusätzlich sind `LICENSE_STATUS.md` und `THIRD_PARTY_NOTICES.md` vor jeder
öffentlichen Veröffentlichung zu prüfen. Dokumentieren sie einen anwendbaren,
ungeklärten Rechte- oder Weiterverteilungspunkt, ist vor der Veröffentlichung
eine ausdrückliche Entscheidung des Projektinhabers erforderlich. Eine
allgemeine Freigabe zum Veröffentlichen ersetzt weder diese Entscheidung noch
die Auswahl einer projektweiten Lizenz.

Bei Änderungen am E-Paper-Treiber müssen außerdem dessen lokale Lizenzdateien
`LICENSE` und `SEEED_GFX_LICENSE.txt`, die festen Quellrevisionen in
`THIRD_PARTY_NOTICES.md` und die dazugehörigen Copyright-Hinweise erhalten
bleiben. Neue Waveformtabellen oder Initialisierungssequenzen dürfen nur aus
einer eindeutig dokumentierten, für die Weiterverteilung geeigneten Quelle
übernommen werden.
