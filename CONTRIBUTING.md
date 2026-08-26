# Zu GuestyTerminal beitragen

Vielen Dank für Beiträge. Vor Änderungen bitte `AGENTS.md` sowie die Architektur-
und Datenschutzabschnitte in `README.md` lesen. Änderungen an sichtbaren Feldern
müssen immer auf beiden Seiten der Home-Assistant-/ESPHome-Grenze umgesetzt und
getestet werden.

Bestätigte Fehlerursachen und ihre Diagnosegrenzen stehen in
`TROUBLESHOOTING.md`. Bei Displayzustellungsfehlern ist die letzte v10-
Bestätigung als Grenze zu verwenden: `received` ohne `rendering` verweist auf
den synchronen ESPHome-Aktionspfad vor dem Renderer. Ein funktionierendes
Hardwaretestbild umgeht unter anderem den WLAN-QR-Pfad und ersetzt deshalb
keinen Test des normalen Buchungspayloads.

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

Änderungen an der Displayzustellung müssen zusätzlich die aktuelle bestätigte
v10-Aktion, Statuskorrelation, Zeitüberschreitungen, Reconnect-Wiedergabe,
Auftragsserialisierung und die unveränderte Kompatibilität von v1 bis v9
abdecken. Ein angenommener Home-Assistant-Serviceaufruf ist kein Nachweis für
einen physischen Panel-Refresh.

Firmwareänderungen benötigen zusätzlich eine nicht produktive
`esphome/secrets.yaml` sowie:

```bash
esphome config esphome/guestyterminal-display-1.yaml
esphome compile esphome/guestyterminal-display-1.yaml
```

Die CI kompiliert diese Referenz mit überschriebenen Substitutionen parallel
für das sichere 4-MB- und das optionale 32-MB-Profil. Beide Profile müssen
innerhalb ihres eigenen 95-Prozent-Limits bleiben.

Bitte keine echten Secrets, Buildverzeichnisse, Caches oder generierten
ESPHome-Output committen. Hardwareänderungen müssen im Pull Request als auf
einem realen E1001 getestet oder ausdrücklich als nicht hardwaregetestet
gekennzeichnet werden.

Änderungen am Flashlayout sind keine normalen OTA-Änderungen. Eine bisherige
verwaltete Datei ohne `flash_size` gilt als 4-MB-Layout. Der Wechsel auf das
32-MB-Layout muss im Firmware-Assistenten ausdrücklich bestätigt und einmal
vollständig per USB installiert werden; automatische Sammelupdates dürfen
Layoutzeilen nur erhalten, niemals hinzufügen oder umschreiben. Hardwaretests
prüfen außerdem GPIO16 als ausgeschaltete SD-Versorgung sowie den neutralen
Voll-/Teilrefresh-Selbsttest und die Wiederherstellung der vorherigen Seite.

Beim `auto`-OTP-Pfad muss der dedizierte SPI2-Bus vollständig freigegeben und
nach dem GPIO-Lesevorgang mit derselben E1001-Konfiguration neu initialisiert
werden; das erneute Anlegen nur des SPI-Geräts genügt nicht. `POWER ON` und
`DISPLAY REFRESH` behalten Seeeds feste 100-ms-Wartezeit und warten danach auf
den inaktiven `BUSY_N`-Pegel. Jede sichtbare Treiberänderung erhöht erwartete
und gespeicherte Renderrevision gemeinsam; der aktuelle Stand verwendet
Revision 33.

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

Version 0.3.49 behält Renderrevision 33 bei und korrigiert ausschließlich den
stromgebundenen Mikrofonpfad: Seeeds E1001-Referenz verwendet den linken
Mono-PDM-Slot, während ESPHome 2026.8.1 ohne ausdrückliche Konfiguration den
rechten Slot wählt. Firmwareänderungen an diesem Pfad müssen deshalb
`channel: left`, die bestätigte externe Versorgung, mindestens 200 ms
Anlaufzeit, den nachgewiesenen I²S-Laufzustand, ein endliches vollständiges
30-Sekunden-RMS-Fenster, die lückenlose Veröffentlichung alle 30 Sekunden und
das Abschalten vor GPIO38 testen. Die neutrale
erweiterte Laufzeitdiagnose darf weder Rohsamples noch daraus abgeleitete
Detailwerte enthalten. Die Version benötigt ein gemeinsames Integrations- und
Firmwareupdate; 4-MB-Geräte bleiben OTA-kompatibel. Bis zur vollständigen
Mains-/Unplug-/Batterieprüfung auf realer Hardware muss der Release als
`not_tested` gekennzeichnet bleiben.

Version 0.3.48 verwendet Renderrevision 33 und ergänzt beim identifizierten
E1001 v1.2 die ADC-Batterieschätzung um drei bestätigte
`REG08.CHRG_STAT`-/`REG09`-Messungen. Nur Ladeabschluss zusammen mit
`REG0A.BUS_GD` darf den effektiven Wert auf 100 % setzen; v1.0 bleibt beim
ADC-Pfad und meldet den digitalen Status als nicht unterstützt. Vor- und
Schnellladen verwenden im kleinen Header ein Batteriesymbol mit Blitz, dessen
Zustand an der Teilrefresh-Unterdrückung teilnimmt. Die Version aktiviert
zusätzlich den mains-only relativen 60-Sekunden-Schallpegel und veröffentlicht
den Hardwaretest sowie die drei physischen Tasten wieder als Alltagsentitäten.
Sie benötigt ein gemeinsames Integrations- und Firmwareupdate; 4-MB-Geräte
bleiben OTA-kompatibel. Ladestatus, Ladesymbol, Mikrofon-Gate und die
vollständige Hardwarematrix sind zum Release noch nicht am realen E1001
geprüft und müssen als `not_tested` veröffentlicht werden.

Version 0.3.47 verwendet Renderrevision 32, eine feste 4×4-Matrix und eine
standardmäßige Gamma-Tonkurve von 1,35, um die mittleren Graustufen
aufzuhellen. Sie reduziert außerdem die normale Home-Assistant-Geräteseite auf
alltagstaugliche Entitäten und dokumentiert die reale Bestätigung der
Randkorrektur aus 0.3.46. Die Version benötigt gemeinsam ein Integrations- und
Display-Firmwareupdate; bestehende 4-MB-Geräte bleiben OTA-kompatibel.
Hardwaretests müssen besonders bestätigen, dass reines Weiß, schwarzer Text und
QR-Code unverändert bleiben, das Dithermuster ruhig wirkt, der monochrome
Teilrefresh stabil bleibt und nach dem einmaligen Aufbau keine identischen
Vollrefreshs folgen. Der neue separate Rand-Konditionierungsstand darf nur nach
einem erfolgreichen Zwei-Pass-Ablauf gesetzt werden. Die Tonkurve und die
vollständige Hardwarematrix sind zum Release noch nicht am realen E1001
geprüft und müssen deshalb als `not_tested` veröffentlicht werden.

Der normale Test-Workflow trennt Vorprüfung, statische Analyse, beide
Home-Assistant-Baselines und den ESPHome-Bau. Alle Prüfzweige starten sofort
parallel; Abhängigkeiten, der stabile ESPHome-Werkzeugsatz und nicht produktive
inkrementelle Firmware-Builddaten werden getrennt gecacht. Tag-Pushes lösen
keinen zweiten identischen Testlauf aus.

Version 0.3.46 ersetzt den erfolglosen Custom-Graustufen-Randvorlauf aus
0.3.45 durch eine isolierte, unabhängig aus dem UC8179-Datenblatt umgesetzte
Monochrom-Konditionierung nach dem früher randfreien ESPHome-Modell
`7.50inv2`. Der aktuelle Vier-Graustufen-Treiber bleibt für den endgültigen
Bildaufbau aktiv; Renderrevision 31 fordert den Zwei-Pass-Test einmalig an.
Die Version benötigt gemeinsam ein Integrations- und Display-Firmwareupdate.
Bei der Veröffentlichung war der neue Pfad deshalb korrekt als nicht getestet
gekennzeichnet. Der Realgerätetest am 26. August 2026 hat anschließend das
Verschwinden des Außenrands bei weiterhin schwarzer Schrift bestätigt. Die
vollständige Voll-/Teilrefresh- und Tiefschlafmatrix bleibt davon eine getrennte
Hardwareprüfung und darf nicht aus diesem einzelnen Ergebnis abgeleitet werden.

Version 0.3.45 trennt die Randelektrode vollständig von der gewählten
Pixelwellenform: Normale Voll- und Teilrefreshs lassen sie hochohmig. Auf sicher
erkannter externer Versorgung konditioniert ein einmaliger begrenzter
Custom-LUTKW-Pass den Rand vor dem sofortigen Neuaufbau desselben Framebuffers
mit der gewählten Pixelwellenform; die Diagnose **E-paper Randkorrektur** kann
diesen Ablauf kontrolliert wiederholen. Die Version benötigt gemeinsam ein
Integrations- und Display-Firmwareupdate. Bis Kontrast, Randwirkung und die
vollständige Voll-/Teilrefresh-Matrix auf einem realen E1001 geprüft sind, muss
die Veröffentlichung den Hardwarestatus ausdrücklich als nicht getestet
ausweisen.

Version 0.3.44 beendet Wiederholungsversuche nach einem bestätigten
`panel_error` oder `panel_timeout` und unterdrückt auf der Firmwareseite
weitere physische Aufträge für denselben in diesem Start bereits
fehlgeschlagenen Inhaltsfingerabdruck. Die Randansteuerung verwendet keinen
`R25/LUTBD`-Hostpfad mehr und setzt nach Seeeds `R50h=0x10,0x07` den
datenblattdefinierten fließenden Endzustand `R52h.BDEND=11`. Sie benötigt
gemeinsam ein Integrations- und Display-Firmwareupdate. Bis Randwirkung,
unveränderte Inhaltsunterdrückung und vollständiger Panelabschluss auf einem
realen E1001 geprüft sind, muss die Veröffentlichung den Hardwarestatus
ausdrücklich als nicht getestet ausweisen.

Version 0.3.43 benötigt wegen der korrigierten QR-Erzeugung, der vergrößerten
ESPHome-Loop-Stackreserve und der vom Home-Assistant-Bootstrap getrennten
Displayzustellung gemeinsam ein Integrations- und Display-Firmwareupdate. Die
Releaseprüfung muss insbesondere bestätigen, dass ein Willkommens-Payload mit
WLAN-Daten die vollständige Folge `received`, `rendering` und `success`
erreicht, ohne den ESPHome-Hauptprozess zu blockieren. Bis dieser Ablauf auf
einem realen E1001 geprüft ist, muss die Veröffentlichung den Hardwarestatus
ausdrücklich als nicht getestet ausweisen.

Version 0.3.42 benötigt wegen der vervollständigten OTP-Initialisierung, der
phasenbezogenen BUSY-Grenzen und des kontrollierten Register-LUT-Rückfalls
gemeinsam ein Integrations- und Display-Firmwareupdate. Zusätzlich zum
vollständigen Testlauf und zur ESPHome-Kompilierung sind während wiederholter
Vollrefreshs die Wiederherstellung nach einem Selbsttest, die dauerhafte
Native-API-Erreichbarkeit und die serielle Payload-Verarbeitung auf einem realen
E1001 zu prüfen oder ausdrücklich als nicht hardwaregetestet offenzulegen. Im
Protokoll müssen `received`, `rendering` und `success` ohne Aktions-Timeout,
schnellen Neustart oder Reconnect-Schleife erscheinen.
Die mit 0.3.36 eingeführte LUTBD-Randansteuerung bleibt bestehen;
Renderrevision 28 erzwingt nach der aktuellen Treiberkorrektur einen neuen
Vollrefresh. Die Modi `auto`, `otp` und `custom`
gehören weiterhin zur Hardwarematrix.

Der v10-Zustellpfad benötigt zusätzlich einen Realgerätetest
mit erfolgreicher `received`-/`rendering`-/`success`-Folge, einem absichtlich
unterbrochenen Reconnect während des Vollrefreshs, einem erzwungenen Fehlerpfad
ohne falsche Buchungsbestätigung sowie der Kontrolle von **E-paper waveform**
und **E-paper border mode** nach einem erzwungenen Vollrefresh.

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
