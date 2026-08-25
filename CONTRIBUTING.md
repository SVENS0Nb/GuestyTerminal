# Zu GuestyTerminal beitragen

Vielen Dank für Beiträge. Vor Änderungen bitte `AGENTS.md` sowie die Architektur-
und Datenschutzabschnitte in `README.md` lesen. Änderungen an sichtbaren Feldern
müssen immer auf beiden Seiten der Home-Assistant-/ESPHome-Grenze umgesetzt und
getestet werden.

Bei Guesty-Mehrfacheinheiten müssen konkrete `unitId`, direkte `listingId`,
übergeordnete `unitTypeId` und `parentListingId` kontextbezogen auf genau ein
konfiguriertes Listing aufgelöst bleiben. Auswahl, Snapshot-Abgleich und
Payload-Erstellung müssen innerhalb eines Aktualisierungslaufs denselben
zeitzonenbewussten Zeitstempel verwenden; dazu gehören auch API-Datumsfilter,
die Auswahl zeitabhängiger `stay`-Segmente und die Normalisierung. Exakte
`stay.checkIn`-/`stay.checkOut`-Werte bestimmen Segmentbesitz. Laufende und
zukünftige Abfragen bleiben pro Listing kontextgebunden; ein zusätzlicher
kontoweiter Current/Recent-Snapshot entdeckt spätere Segmente, weil Guestys
Listing-Filter nur das erste Segment prüft. Seine Zeilen besitzen keinen
Query-Kontext und dürfen ausschließlich anhand gemappter Identitäten geroutet
werden. Mehrere Projektionen derselben Reservierung werden vor der
Normalisierung kontrolliert zusammengeführt: Aktuelle Daten sind maßgeblich,
und explizit geleerte sensible Felder dürfen über keine Aliasform oder spätere
optionale Abfrage aus älteren Projektionen wiederhergestellt werden. Das gilt
für jede aktuelle Projektion sowie insbesondere für
`guest`/`guestId`/`bookerId` und
`customFields`/`customField`/`fields`. Türcodes müssen zusätzlich über
`keycode`/`keyCode`/`doorCode`, `value`/`code` und kontoweite
Custom-Field-Definitionen hinweg dieselbe Löschsemantik behalten. Ein explizit
leerer aktueller Wert darf weder aus Cache- oder Populated-Fields-Daten noch in
der späteren Normalisierung wiederhergestellt werden; abgelaufene
Felddefinitionen sind nach einem fehlgeschlagenen Neuabruf nicht autoritativ.
Mehrdeutige Antworten ohne eindeutige Identität dürfen nie auf mehrere
Listings verteilt werden.

Fehlt eine bereits bekannte aktive Reservierung in der gefilterten Suche, darf
sie gezielt über `GET /reservations-v3` mit `reservationIds[]` verifiziert
werden; Pakete enthalten höchstens zehn IDs. Dieser Rückfall darf nicht auf
zukünftige Reservierungen ausgedehnt werden, weil deren Fehlen im erfolgreichen
Upcoming-Snapshot eine sofortige Stornierung signalisiert. Fehler werden pro
Listing isoliert und erhalten dessen letzten erfolgreichen RAM-Snapshot;
für ein fehlgeschlagenes Listing darf daraus keine neue Payload oder Lease
entstehen. Authentifizierungs-, Discovery- und Rate-Limit-Fehler bleiben global.
Änderungen am API-Client müssen die gleitenden Guesty-Grenzen von 15 Anfragen
pro Sekunde, 120 pro Minute und 5.000 pro Stunde, sofort propagiertes
`Retry-After` bei HTTP 429, Abbruch paralleler Geschwisteraufrufe,
datenschutzneutrale Exception-Texte sowie fail-closed HTTP-200-Schemata testen.
Die Grenzen gelten kontoweit und tokenübergreifend; getrennte Clients oder
Home-Assistant-Instanzen teilen dasselbe Kontingent.

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

Beim `auto`-OTP-Pfad muss der dedizierte SPI2-Bus vollständig freigegeben und
nach dem GPIO-Lesevorgang mit derselben E1001-Konfiguration neu initialisiert
werden; das erneute Anlegen nur des SPI-Geräts genügt nicht. `POWER ON` und
`DISPLAY REFRESH` behalten Seeeds feste 100-ms-Wartezeit und warten danach auf
den inaktiven `BUSY_N`-Pegel. Jede sichtbare Treiberänderung erhöht erwartete
und gespeicherte Renderrevision gemeinsam; der aktuelle Stand verwendet
Revision 27.

## Veröffentlichungen und Distribution

Vor einer Veröffentlichung müssen die Versionsangaben in Manifest,
Firmwaregenerator, Referenz-YAML und versionsabhängigen Tests übereinstimmen.
`README.md` und `CHANGELOG.md` müssen die Änderung sowie die Notwendigkeit eines
Display-Firmwareupdates eindeutig nennen.

Jede Veröffentlichung läuft ausschließlich über den manuell gestarteten
GitHub-Workflow **Release** auf `main`. Direkte lokale Tags und manuell
angelegte GitHub-Releases sind nicht Teil des unterstützten Ablaufs. Der
Workflow akzeptiert nur den unveränderten `main`-Commit, für den **Tests** bereits
vollständig erfolgreich war, prüft Versions- und Lizenzmarker erneut, verlangt
eine wahrheitsgemäße Angabe zur realen Hardwareprüfung und erzeugt die
Release-Notizen aus dem aktuellen Changelog. Erst danach legt er den annotierten
Tag und das GitHub-Release an. Ein vorhandener Tag wird nur dann wiederverwendet,
wenn er exakt auf denselben geprüften Commit zeigt.

Der normale Test-Workflow trennt Vorprüfung, statische Analyse, beide
Home-Assistant-Baselines und den ESPHome-Bau. Diese Arbeiten laufen nach der
schnellen Vorprüfung parallel; Abhängigkeiten und nicht produktive
Firmware-Builddaten werden gecacht. Tag-Pushes lösen keinen zweiten identischen
Testlauf aus.

Version 0.3.38 benötigt wegen der watchdog-sicheren, kooperativen
Panel-Transaktionen ein
Display-Firmwareupdate. Zusätzlich zum vollständigen Testlauf und zur
ESPHome-Kompilierung sind während wiederholter Vollrefreshs die dauerhafte
Native-API-Erreichbarkeit und die serielle Payload-Verarbeitung auf einem
realen E1001 zu prüfen oder ausdrücklich als nicht hardwaregetestet
offenzulegen. Im Protokoll müssen Start und erfolgreicher Abschluss der
Hardwaretransaktion ohne schnellen Neustart oder Reconnect-Schleife erscheinen.
Die mit 0.3.36 eingeführte LUTBD-Randansteuerung und
Renderrevision 27 bleiben bestehen; Vollrefreshs in `auto`, `otp` und `custom`
gehören weiterhin zur Hardwarematrix.

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
