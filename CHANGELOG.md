# Änderungshistorie

Alle wesentlichen Änderungen an GuestyTerminal werden hier gesammelt. Einträge
unter „Unveröffentlicht“ gehören noch zu keinem freigegebenen Tag.

## 0.3.36 – 2026-08-25

### Displayrand – dedizierte Panel-Wellenform

- Die Ursache des erst in der letzten Refreshphase erscheinenden dunklen
  Rahmens liegt nicht im 800×480-Framebuffer: `R50h.BDV=01` ließ die separate
  UC8179-Randelektrode die Pixel-Wellenform `LUTKW` verwenden. `R52h=0x02`
  bestimmt lediglich die Spannung nach deren Abschluss und konnte den zuvor
  aufgebauten bistabilen Pigmentzustand deshalb nicht korrigieren.
- Der OTP-Vier-Grau-Pfad setzt nun nach seiner Wellenformauswahl
  `R50h=0x00,0x07` und verwendet damit direkt die gemeinsame, im Panel-OTP
  gespeicherte `LUTBD`.
- Im Register-LUT-Pfad prüft der Treiber entsprechend der Controllerpriorität
  zuerst Bank 0 und nur bei zwei übereinstimmend ungültigen Checkcodes Bank 1.
  Checkcode, Vier-Grau-Marker und die 42 Bytes aus `0x001F…0x0048`
  beziehungsweise `0x0C1F…0x0C48` müssen in zwei getrennten Lesevorgängen
  identisch sein. Erst dann werden die Laufzeitdaten nach `R25h` geschrieben und
  mit `BDV=00` ausgewählt. Bei unsicheren Daten bleibt der Rand hochohmig; echte
  OTP-Werte werden weder protokolliert noch mit der Firmware verteilt.
- Die alte Modusentscheidung aus beiden OTP-Markern wird einmalig verworfen:
  Wie der UC8179 berücksichtigt die Firmware jetzt ausschließlich den Marker
  der durch `0xA5` ausgewählten Bank. Vor `POWER OFF` wird der Rand mit
  dem bewährten `R50h=0x90,0x07` freigegeben. Renderrevision 27 erzwingt für die
  sichtbare Treiberänderung einmalig einen vollständigen Neuaufbau.

### Prüfstatus

- Der vollständige lokale Python-Prüflauf war mit 257 Tests gegen Home Assistant
  2026.2.3 erfolgreich; die Branch-Abdeckung beträgt 90,79 %. Ruff,
  Formatprüfung, Mypy und Bytecode-Kompilierung sind ebenfalls fehlerfrei.
- ESPHome 2026.7.4 hat die Referenzkonfiguration validiert und die Firmware
  vollständig gebaut; im App-Partition-Report bleiben 21 % frei. Die optische
  Randkorrektur ist noch nicht auf einem realen E1001 bestätigt.

## 0.3.35 – 2026-08-25

### Displayrand – zweite Korrektur

- Die 0.3.34-Abschaltkorrektur konnte einen bereits dunklen Rand nicht optisch
  löschen: `R50h.BDZ` gibt die separate Elektrode erst nach dem Bildaufbau
  elektrisch frei, E-Paper behält seinen zuvor aufgebauten Pigmentzustand aber
  ohne eine weitere Refresh-Wellenform bei.
- Der Custom-LUT-Pfad beendet die Rand-Wellenform nun mit dem dokumentierten
  UC8179-Standard `R52h.BDEND=VCOM_DC` statt mit 0 V. Dadurch bleibt nach der
  Weißfahrt kein Differenzfeld am Rand bestehen. Der OTP-Pfad verwendete diesen
  Standard bereits und bleibt unverändert.
- Vor `POWER OFF` setzt die Firmware `R50h` jetzt vollständig und mit auf null
  gehaltenen reservierten Bits auf `0x90, 0x07`. Dies gibt den Rand frei, ohne
  den sichtbaren Zustand nachträglich verändern zu wollen.
- Automatisches Löschen des vollständigen 800×480-Framebuffers wird in der
  ESPHome-Konfiguration nun ausdrücklich aktiviert. Die Renderrevision steigt
  auf 26 und alle Versionsmarkierungen auf 0.3.35, damit nach dem
  Firmwareupdate ein vollständiger Neuaufbau erfolgt.

### Prüfstatus

- Der vollständige lokale Python-Prüflauf war mit 254 Tests gegen Home Assistant
  2026.2.3 erfolgreich; die Branch-Abdeckung beträgt 90,79 %. Ruff,
  Formatprüfung, Mypy und Bytecode-Kompilierung sind ebenfalls fehlerfrei.
- ESPHome 2026.7.4 hat die Referenzkonfiguration validiert und die Firmware
  vollständig gebaut; im App-Partition-Report bleiben 21 % frei. Die
  Mindestversion Home Assistant 2025.12.0 wird vor einer Veröffentlichung in CI
  geprüft. Die Wirkung auf einem realen E1001 steht noch aus.

## 0.3.34 – 2026-08-25

### Displayrand

- Der UC8179-Rand wird unmittelbar vor `POWER OFF` über `R50h.BDZ` hochohmig
  geschaltet. Die reale Hardwareprüfung nach der Veröffentlichung zeigte, dass
  diese Maßnahme allein den bereits während des Refreshs dunkel aufgebauten
  Pigmentzustand nicht entfernt; die Folgeberichtigung wurde mit Version 0.3.35
  veröffentlicht.
- Die Renderrevision steigt auf 25, damit ein bereits mit 0.3.33 gezeichnetes
  und ansonsten unverändertes Bild nach dem Firmwareupdate einmal vollständig
  neu aufgebaut wird. Alle Versionsmarkierungen stehen auf 0.3.34; ein
  Display-Firmwareupdate ist erforderlich.

### Prüfstatus

- Der vollständige Python-Prüflauf war mit 254 Tests gegen Home Assistant
  2026.2.3 erfolgreich; die Branch-Abdeckung beträgt 90,79 %. Ruff,
  Formatprüfung, Mypy und Bytecode-Kompilierung sind ebenfalls fehlerfrei.
- ESPHome 2026.7.4 hat die Referenzkonfiguration validiert und die Firmware
  vollständig gebaut; im App-Partition-Report bleiben 21 % frei. Die
  Randkorrektur wurde noch nicht auf einem realen E1001 geprüft.

## 0.3.33 – 2026-08-25

### Automatische Stromerkennung

- Der Modus `auto` erkennt nun beide offiziellen E1001-Hardwarestände ohne
  zusätzliche Benutzerauswahl. Auf v1.2 wird der SY6974B zuerst über `REG0B`
  identifiziert und externe Versorgung weiterhin dreifach über das dedizierte
  `REG0A.BUS_GD`-Signal bestätigt. Ein einmal gesehener Ladecontroller bleibt
  für den Startvorgang maßgeblich; drei Identitätsbestätigungen speichern die
  nicht sensible Hardwareeigenschaft über Deep Sleep hinweg.
- E1001 v1.0 verwendet den ausschließlich von `TYPEC_5V` versorgten
  USB-UART-Baustein als revisionsspezifischen Rückfall. Vor jeder Messung wird
  die physische UART0-Ausgabe pausiert, GPIO43 vom UART getrennt und mindestens
  60 ms auf Low gehalten. GPIO44 bleibt während drei Fenstern mit je 64
  Messungen definiert heruntergezogen. Das verhindert falsche Netzmeldungen und
  unnötigen Akkuverbrauch durch mögliche Rückspeisung bei älteren CH340C-Losen.
- UART0 wird nur nach einem roh bestätigten externen Stromsignal wieder
  verbunden. Bei Akku oder einer unklaren Messung bleibt GPIO43 bis zum
  nächsten Test beziehungsweise Deep Sleep auf Low. Jeder Schlafpfad führt
  diese elektrische Beruhigung erneut aus; API-Logs bleiben währenddessen
  verfügbar.
- Die neue Diagnose-Entität **Power detection method** zeigt `SY6974B BUS_GD`,
  `USB-UART` oder `Unavailable`. Ein bestätigtes Kabel übersteht weiterhin eine
  unklare Messgruppe; zwei Gruppen schalten sicher auf Akkuverhalten zurück.
- Die Lade-LED wird nur auf v1.2 per SY6974B deaktiviert. Der ETA6003 von v1.0
  bietet keinen entsprechenden Softwareschalter; UI und Dokumentation nennen
  diese Hardwaregrenze jetzt ausdrücklich.
- Die Vier-Grau-Übertragung wandelt die logischen Pufferwerte jetzt wie Seeeds
  E1001-Referenz mit `3 - Grauwert` in die beiden UC8179-Datenebenen um. Damit
  erscheinen Hintergrund und Text wieder in der vorgesehenen Polarität:
  heller Hintergrund mit dunkler Schrift statt dunklem Negativbild.
- Alle Versionsmarkierungen stehen auf 0.3.33. Die Renderrevision steigt wegen
  der sichtbaren Polaritätskorrektur auf 24 und erzwingt nach dem Update genau
  einen vollständigen Neuaufbau. Ein Display-Firmwareupdate ist erforderlich.

### Prüfstatus

- Der vollständige Python-Prüflauf war mit jeweils 254 Tests gegen Home
  Assistant 2025.12.0 und 2026.2.3 erfolgreich; die Branch-Abdeckung beträgt
  90,79 %. Ruff, Formatprüfung, Mypy und Bytecode-Kompilierung sind ebenfalls
  fehlerfrei.
- ESPHome 2026.7.4 hat die Referenzkonfiguration validiert und die Firmware
  vollständig gebaut; im App-Partition-Report bleiben 21 % frei. Reale
  USB-/Akku-Tests auf E1001 v1.0 und v1.2 stehen noch aus. Dazu gehören PC-USB,
  ein hostloses Netzteil, ein reines Ladekabel, Abziehen/Wiederanstecken und
  UART-Verkehr. Ein dauerhaftes UART-BREAK auf GPIO44 ist auf v1.0 physikalisch
  nicht von einer unversorgten USB-UART-Brücke unterscheidbar.

## 0.3.32 – 2026-08-25

### Buchungsübergänge und Fehlertoleranz

- Bereits bekannte laufende Reservierungen, die Guestys gefilterte Suche nach
  einer Einheitenzuweisung nicht mehr oder nicht eindeutig liefert, werden vor
  dem Entfernen gezielt über `GET /reservations-v3` verifiziert. Die
  `reservationIds[]` werden entsprechend Guestys Vorgabe in Pakete mit maximal
  zehn IDs aufgeteilt. Dieser Rückfall gilt bewusst nicht für zukünftige
  Buchungen, damit eine Stornierung weiterhin sofort aus dem autoritativen
  Upcoming-Snapshot verschwindet. ID-Antworten müssen selbst eine gemappte
  Identität enthalten; alter Cache-Besitz wird nie als erfundener Query-Kontext
  verwendet. Unvollständige aktive Projektionen werden verifiziert oder
  geschützt statt als Löschung behandelt.
- Ein zusätzlicher kontoweiter Current/Recent-Snapshot gleicht aus, dass Guestys
  V3-`filter[listingId]` nur das erste `stay`-Segment berücksichtigt. Nur lokal
  eindeutig einem eingerichteten Listing zuordenbare Zeilen werden übernommen;
  dadurch ist ein späteres aktives Segment auch direkt nach einem
  Home-Assistant-Neustart auffindbar.
- API-Datumsfilter, Auswahl des relevanten `stay`-Segments, Normalisierung,
  Listing-Zuordnung, Snapshot-Abgleich und alle Display-Payloads verwenden nun
  denselben zeitzonenbewussten Zeitpunkt eines Aktualisierungslaufs. Bei
  Reservierungen mit mehreren zeitlich aufeinanderfolgenden Aufenthaltssegmenten
  gehört dadurch die aktive, sonst die nächste beziehungsweise zuletzt
  abgeschlossene Einheit eindeutig zum richtigen Display. Segmentbesitz nutzt
  die exakten V3-`stay.checkIn`-/`stay.checkOut`-Grenzen. Wird dieselbe
  Reservierungs-ID frisch einem neuen Listing zugeordnet, entfällt die
  zwölfstündige Retention ihrer alten Listing-Kopie sofort.
- Mehrere Guesty-Projektionen derselben Reservierung werden kontrolliert
  zusammengeführt: Die aktuelle Projektion bleibt maßgeblich, fehlende Felder
  dürfen ergänzt werden, explizit geleerte Notizen, Custom Fields und andere
  sensible Werte werden jedoch auch über abweichende Root-, Nested- oder
  Metadaten-Aliase und spätere optionale Lookups nicht wiederhergestellt.
  Löschungen aus jeder aktuellen Projektion gewinnen dabei vor älteren
  Gast-, `guestId`-/`bookerId`- und
  `customFields`-/`customField`-/`fields`-Formen. Das gilt auch für direkte
  `keycode`-/`keyCode`-/`doorCode`-Aliase, Datensätze mit `value` oder `code`
  und zunächst nur per Account-Felddefinition erkennbare Field-IDs. Ein leerer
  aktueller Türcode wird weder aus einem Cache, einer optionalen
  Populated-Fields-Abfrage noch während der Normalisierung wiederhergestellt;
  abgelaufene Felddefinitionen werden nach einem fehlgeschlagenen Neuabruf
  nicht als gültige Grundlage verwendet.
- Fehler einer einzelnen Listing-Abfrage lassen die letzten erfolgreichen
  RAM-Daten dieses Listings bestehen, ohne erfolgreich aktualisierte Listings
  zu blockieren. Sie erzeugen jedoch keine neue Display-Payload und verlängern
  damit keine Datenschutzfrist. Ein manueller Geräte-Refresh löscht einen noch
  unbestätigten Bildschirm ebenfalls nicht. Wenn kein Listing erfolgreich ist,
  bleibt der ganze vorherige Coordinator-Stand erhalten. Authentifizierungs-,
  kontoweite Discovery- und Rate-Limit-Fehler bleiben Fehler des gesamten
  Aktualisierungslaufs.

### Guesty API

- Ein echter gleitender Request-Limiter reiht die Anfragen eines Clients in
  Guestys Grenzen von 15 Anfragen pro Sekunde, 120 pro Minute und 5.000 pro
  Stunde ein. Der Slot wird erst unmittelbar vor dem API-Aufruf nach einer
  möglichen OAuth-Aktualisierung reserviert. Ein `Retry-After` nach HTTP 429
  liefert bis zum Ablauf sofort den verbleibenden Rate-Limit-Fehler zurück,
  statt manuelle Aufrufe schlafen zu lassen; parallele Geschwisteraufrufe werden
  nach dem ersten Fehler abgebrochen.
- Verbindungs-, Request- und ungültige Responsefehler sind getrennt typisiert;
  weder ihre Meldungen noch verkettete Tracebacks geben Reservierungs-IDs,
  Request-Pfade oder Guesty-Antworttexte preis.
  Fehlende `results`, falsche Collection-Typen, ungültige Zeilen oder eine
  fremde/fehlende Listing-ID in einem HTTP-200-Detail gelten ausdrücklich nicht
  als autoritativer leerer Snapshot. Dasselbe gilt für eine leere
  Reservierungsseite mit `pagination.hasMore: true` und doppelte Zeilen in
  einer V3-ID-Verifikation.

### E-Paper-Firmware

- Der `auto`-OTP-Test gibt den dedizierten SPI2-Bus jetzt vollständig frei,
  liest die bidirektionale SDA/MOSI-Leitung per GPIO und initialisiert danach
  Bus und SPI-Gerät mit der E1001-Konfiguration neu. Damit bleiben die normalen
  Hardware-SPI-Übertragungen nach dem einmaligen OTP-Test funktionsfähig.
- Nach `POWER ON` und `DISPLAY REFRESH` hält der Treiber Seeeds feste
  100-ms-Wartezeit ein und wartet anschließend auf den inaktiven
  `BUSY_N`-Pegel, ohne zusätzlich eine möglicherweise bereits verpasste
  BUSY-Flanke zu verlangen.
- Die Renderrevision steigt auf 23. Für Version 0.3.32 ist
  deshalb zwingend ein Display-Firmwareupdate erforderlich.

### Prüfstatus

- Der vollständige Python-Prüflauf war mit jeweils 237 Tests gegen Home
  Assistant 2025.12.0 und 2026.2.3 erfolgreich; die Branch-Abdeckung beträgt
  90,79 %. Ruff, Formatprüfung, Mypy und Bytecode-Kompilierung sind ebenfalls
  fehlerfrei.
- ESPHome 2026.7.4 hat die Referenzkonfiguration validiert und die Firmware
  vollständig gebaut; im App-Partition-Report bleiben 21 % frei. Eine Prüfung
  der OTP-, Voll-/Teilaktualisierungs- und BUSY-Pfade auf einem realen
  reTerminal E1001 fehlt weiterhin.

## 0.3.31 – 2026-08-24

### Fehlerbehebungen

- Laufende Reservierungen werden nun auch dann weiterhin dem konfigurierten
  Mehrfach-Listing zugeordnet, wenn Guestys Suchantwort nach der Anreise nur
  noch die konkret zugewiesene Einheit enthält. Dadurch bleibt der Übergang von
  der Vorschau- zur Willkommens- und später zur Check-out-Seite auch nach einem
  Home-Assistant-Neustart erhalten.
- Projektionen derselben Reservierung werden listingübergreifend
  zusammengeführt und genau einem Listing zugeordnet. Eine ohne Identitäten für
  mehrere Listings mehrdeutige Antwort wird aus Datenschutzgründen nicht an
  mehrere Displays verteilt.

### Firmware und Lizenzherkunft

- Der UC8179-Treiber verwendet nur noch dokumentiert permissiv lizenzierte
  Seeed-Quellen. Die frühere Waveform- und Initialisierungsimplementierung mit
  unklarer Weiterverteilungslage wurde vollständig entfernt.
- `auto` erkennt die von Seeed vorgesehenen OTP-Vier-Grau-Wellenformen und
  verwendet andernfalls Seeeds MIT-lizenzierte Register-LUTs. Die Auswahl wird
  über Tiefschlaf hinweg im RTC-Speicher gehalten, um den Akkuzyklus nicht mit
  wiederholten OTP-Lesevorgängen zu belasten.
- Die Renderrevision steigt auf 22. Mit Version 0.3.31 ist daher einmalig ein
  Display-Firmwareupdate erforderlich. Die Änderung wurde vollständig
  kompiliert, aber noch nicht auf einem realen E1001 sichtbar geprüft.

### Dokumentation und Wartung

- Die Agentenanweisungen dokumentieren nun ausdrücklich die
  Mehrfach-Listing-Auflösung und den gemeinsamen Zeitstempel eines
  Aktualisierungslaufs aus Version 0.3.30.
- Die Batterie-Kennlinie, 16-fache ADC-Mittelung,
  `REG0A.BUS_GD`-Netzstromerkennung und Energie-Diagnose-Entitäten sind als
  nicht zu regressierende Firmware-Invarianten festgehalten.
- Lokale Prüfung, Release-Changelog, Firmware-Kompatibilität sowie Lizenz- und
  Drittanbieterstatus sind Bestandteil der vollständigen Definition of Done.
- Ein Repository-Vertragstest schützt die zentralen Wissenslinks und aktuellen
  Wartungsinvarianten vor unbeabsichtigtem Entfernen.

## 0.3.30 – 2026-08-24

### Buchungsübergänge

- Reservierungen von Guesty-Mehrfacheinheiten bleiben beim Wechsel von der
  Vorbereitungsseite zur Willkommensseite korrekt dem konfigurierten Listing
  zugeordnet, auch wenn Guesty beim Check-in nachträglich eine konkrete
  `unitId` zusätzlich zur übergeordneten `unitTypeId` liefert.
- Alle bekannten Listing-Identitäten werden nach ihrer Bedeutung priorisiert
  und ausschließlich gegen die tatsächlich konfigurierten Listings aufgelöst.
  Das erhält die strikte Trennung zwischen Displays und verhindert doppelte
  oder verwaiste Buchungen.
- Auswahl, Snapshot-Abgleich und Payload-Erstellung verwenden innerhalb eines
  Aktualisierungslaufs denselben Zeitstempel. Dadurch bleiben die Übergänge
  Vorbereitung, Willkommen und Check-out auch direkt an Zeitgrenzen
  konsistent.

## 0.3.29 – 2026-08-23

### Energie

- Die automatische Netzstromerkennung verwendet nun das dedizierte
  `REG0A.BUS_GD`-Signal des SY6974B. Damit bleiben Displays auch an CDP-,
  unbekannten und nicht standardisierten USB-Netzteilen zuverlässig online,
  statt diese Quellen fälschlich als Akkubetrieb einzustufen.

## 0.3.28 – 2026-08-23

### Akku und Energie

- Die nichtlineare Akku-Kennlinie wird nun ausdrücklich stückweise ausgewertet,
  statt versehentlich durch eine einzige Ausgleichsgerade ersetzt zu werden.
  Sechzehn gemittelte ADC-Messungen stabilisieren zusätzlich die angezeigte
  Spannung und Prozentzahl.
- Alle regulären Akku-Schlafpfade verwenden dieselbe Abschaltsequenz. Ein
  zusätzlicher Watchdog beendet auch einen verzögerten Wachzyklus nach einer
  erfolgreich empfangenen Anzeige, ohne fehlgeschlagene Datenschutz-Löschungen
  fälschlich zu bestätigen.
- Die neuen Diagnose-Entitäten **Wake-up reason** und **Awake duration** machen
  Tasten-Wakeups, Wake-Schleifen und ausgeschöpfte 90-Sekunden-Fenster in Home
  Assistant sichtbar.

## 0.3.27 – 2026-08-23

### Sicherheit und Datenschutz

- Der gespeicherte Bildschirmzustand wird erst nach einem erfolgreichen
  physischen E-Paper-Refresh bestätigt. Fehlgeschlagene Löschvorgänge bleiben
  sensitiv markiert und werden erneut versucht.
- Der alle fünf Minuten erneuerte Lease-Zeitpunkt bleibt im RAM; nur der selten
  wechselnde physische Sensitivitätsstatus wird persistent gespeichert. Das
  reduziert NVS-Schreibvorgänge und behandelt Neustarts weiterhin fail-closed.
- Managed ESPHome-Dateien werden von Beginn des atomaren Schreibvorgangs an mit
  `0600` geschützt. Updates validieren API-, OTA- und Fallback-Credentials vor
  jeder Änderung.
- Download-Diagnosen verwenden eine Positivliste und enthalten keine Gäste,
  Zugangsdaten, SSIDs, Passwörter oder Fehlermeldungstexte.

### Stabilität

- Ungültige Zeitzonen fallen vollständig auf UTC zurück; nicht-positive
  Buchungszeiträume werden verworfen.
- Unabhängige Listing- und Upcoming-Abfragen laufen mit maximal vier
  gleichzeitigen Guesty-Anfragen.
- Manuelle Home-Assistant-Aktionen melden fehlgeschlagene Guesty-Aktualisierungen
  und vollständig fehlgeschlagene Displayzustellungen.
- Display-Mappings besitzen eine stabile Identität und werden bei einer
  Umbenennung ihrer Endpoint-Entity migriert.

### Entwicklung

- Reproduzierbare Testwerkzeuge, Constraints für Home Assistant 2025.12,
  Mypy-Prüfung, erweiterte Ruff-Regeln, CI-Zeitlimits und Dependabot wurden
  ergänzt.

## 0.3.26

- ESPHome wartet vor dem Reconnect-Impuls auf das Home-Assistant-State-Abo und
  die Integration wiederholt die Zustellung innerhalb eines begrenzten Fensters.

## 0.3.25

- Geordneter Deep Sleep bestätigt einen erfolgreichen OTA-Start und verhindert
  Rollbacks bei kurzen Akku-Wachzyklen.

## 0.3.24

- Pro Listing getrennte RAM-Snapshots, fünf autoritative Upcoming-Buchungen und
  zwölf Stunden Aufbewahrung abgeschlossener Aufenthalte wurden eingeführt.

## 0.3.20–0.3.23

- Reconnect-, Aufgaben- und Fehlerpfade wurden gehärtet; die Batterieanzeige der
  Empty-Room-Seite erhielt ihre aktuelle Ausrichtung und Teilrefreshlogik.

## 0.3.11–0.3.19

- Vier-Graustufen-Rendering, Wetter-Teilrefresh, lokalisierte Labels,
  Checkout- und Empty-Room-Seiten sowie der autoritative Geräte-Refresh wurden
  schrittweise ergänzt.
