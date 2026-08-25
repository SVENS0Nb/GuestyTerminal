# Änderungshistorie

Alle wesentlichen Änderungen an GuestyTerminal werden hier gesammelt. Einträge
unter „Unveröffentlicht“ gehören noch zu keinem freigegebenen Tag.

## 0.3.43 – 2026-08-26

### Willkommensbild und Home-Assistant-Start

- Display-Zustellungen laufen jetzt als von GuestyTerminal verwaltete
  Hintergrundaufgaben. Home Assistant wartet beim Start dadurch nicht mehr auf
  die bis zu 135 Sekunden dauernde physische E-Paper-Bestätigung und meldet
  keinen blockierten Bootstrap, während ein Display zeichnet oder nicht
  antwortet.
- Der Willkommens-Payload kann nicht mehr zwischen `received` und `rendering`
  durch die WiFi-QR-Erzeugung den ESPHome-Hauptthread überlasten: Die
  QR-Berechnung erfolgt nur noch einmal im Renderer, und der ESP32-Loop erhält
  16 KiB statt 8 KiB Stackreserve. Der beim Start protokollierte neutrale
  QR-Platzhalter enthält außerdem keine kennwortähnliche Testbelegung mehr.
- Die v10-Schnittstelle und ihr datenschutzneutraler Ablauf bleiben
  unverändert: Home Assistant übergibt weiterhin strukturierte Displaydaten und
  wartet getrennt auf `received`, `rendering` und den bestätigten physischen
  Abschluss. Der Fehler trat vor dem Renderer auf; Reservierungsauswahl,
  Fünf-Buchungen-RAM-Snapshot und Mehrdisplay-Zuordnung werden nicht verändert.
- Die vollständige Suite mit 289 Tests bestand gegen Home Assistant 2025.12.0
  und 2026.2.3 mit 90,71 % Branch-Abdeckung. Ruff, Mypy, Compileall und die
  Release-Vorprüfung waren ebenfalls erfolgreich.
- Beide Firmwareprofile wurden mit ESPHome 2026.8.1 validiert und vollständig
  kompiliert. Der sichere 4-MB-OTA-Build belegt 82,0 % Flash; das optionale
  32-MB-Profil belegt 9,1 % Flash. Beide nutzen 41,7 % RAM. Die Korrektur ist
  noch nicht auf einem realen E1001 ausgeführt; die vollständige
  Hardwarematrix bleibt deshalb ausdrücklich offen.
- Version 0.3.43 benötigt gemeinsam ein HACS-/Integrationsupdate und ein
  Display-Firmwareupdate. Bestehende 4-MB-Installationen können normal per OTA
  aktualisiert werden; das Flashlayout bleibt unverändert. Das vom E-Paper
  festgehaltene Testbild wird erst durch einen erfolgreichen Vollrefresh
  ersetzt.

## 0.3.42 – 2026-08-25

### Wiederherstellung nach einem hängenden E-Paper-Refresh

- Ein realer E1001-Hardwaretest bestätigte, dass Framebuffer, SPI-Übertragung
  und Vier-Grau-Darstellung funktionieren, der Controller im automatischen
  OTP-Pfad nach dem sichtbaren Bildaufbau jedoch nicht mehr aus `BUSY_N`
  zurückkehrte. Der bisher 70 Sekunden wartende Selbsttest endete deshalb noch
  während der insgesamt 91,8 Sekunden dauernden fehlgeschlagenen Transaktion
  und konnte das vorherige Buchungsbild nicht wiederherstellen.
- Der OTP-Pfad übernimmt nun Seeed_GFXs vollständige Vorbereitung von `R50h`
  vor der Aktivierung der internen Vier-Grau-Wellenform. Die nachgelagerte
  Auswahl der separaten panelinternen `LUTBD` bleibt erhalten, damit die
  Randelektrode nicht wieder eine Pixel-LUT verwendet.
- Falls eine als unterstützt erkannte OTP-Wellenform trotzdem an `BUSY_N`
  hängen bleibt, führt `auto` genau einen kontrollierten Rückfall aus und
  wiederholt dasselbe Vollbild nach einer Controller-Rücksetzung mit Seeeds
  lizenzierten Register-LUTs. Nur ein physisch erfolgreich abgeschlossener
  Rückfall wird für weitere Tiefschlafzyklen behalten; der explizite Modus
  `otp` bleibt unverändert.
- Reset, Einschalten, Bildaufbau und Ausschalten besitzen jetzt getrennte
  Zeitgrenzen und protokollieren ausschließlich Phase, BUSY-Pegel und Dauer.
  Ein Ausschaltfehler kann dadurch nicht mehr weitere 45 Sekunden an eine
  bereits fehlgeschlagene Aktualisierung anhängen.
- Payload-, Datenschutz- und Selbsttestpfade warten bis zu 120 Sekunden auf
  den serialisierten Hardwareauftrag; Home Assistant lässt der korrelierten
  Abschlussbestätigung 135 Sekunden. Der Selbsttest kann damit nach einem
  beendeten Fehlerpfad das normale Bild wieder zeichnen. Die 15-minütige
  Datenschutz-Lease bleibt unverändert.
- Die vollständige Suite mit 288 Tests bestand gegen Home Assistant 2025.12.0
  und 2026.2.3 mit 90,7 % Testabdeckung. Statische Analyse, Format- und
  Typprüfung waren ebenfalls erfolgreich.
- Renderrevision 28 erzwingt nach dem nächsten Firmwareupdate einen
  vollständigen Neuaufbau. Beide Firmwareprofile wurden mit ESPHome 2026.8.1
  erfolgreich geprüft und vollständig kompiliert; das sichere 4-MB-Profil
  belegt 82,0 % seiner App-Partition, das optionale 32-MB-Profil 9,1 %. Nur der
  abschließende Test auf dem realen E1001 steht noch aus.
- Version 0.3.42 benötigt gemeinsam ein HACS-/Integrationsupdate und ein
  Display-Firmwareupdate. Bestehende 4-MB-Installationen können dieses Update
  normal per OTA einspielen; das Flashlayout wird dabei nicht geändert. Das
  festgehaltene Testbild wird beim ersten erfolgreichen Vollrefresh ersetzt.

## 0.3.41 – 2026-08-25

### Zuverlässige v10-Zustellung

- Die ESPHome-v10-Aktion ist jetzt ausdrücklich eine schnelle
  Fire-and-forget-Übergabe. Empfang, Renderbeginn und physischer Panelabschluss
  werden weiterhin ausschließlich über die korrelierten, datenschutzneutralen
  Endpoint-Signale bestätigt. Damit wartet Home Assistant nicht mehr auf eine
  Aktionsantwort, die erst nach dem bis zu 70 Sekunden langen E-Paper-Refresh
  eintreffen könnte.
- Endpoint-Zustände werden ohne API-Batching gesendet und die
  `received`-Bestätigung erhält vor dem Renderer ein eigenes 150-ms-Zeitfenster.
  Langsamere oder VLAN-übergreifende Verbindungen können den Empfang dadurch
  nicht mehr mit dem unmittelbar folgenden Renderzustand zusammenfassen.
- Home Assistant wartet bei der Serviceübergabe wieder bis zur tatsächlichen
  Annahme durch die ESPHome-Integration. Übergabefehler bleiben dadurch in der
  neutralen GuestyTerminal-Ausnahmebehandlung, statt als abgelöste
  Home-Assistant-Core-Aufgabe den vollständigen Zugangsdaten-Payload zu
  protokollieren.

### Diagnose und Installation

- Ein realer Diagnoseexport mit Home Assistant 2026.8.3 und ESPHome 2026.8.1
  bestätigte bereits die richtige Buchungsauswahl im Modus `welcome`, während
  jede v10-Aktion nach 30 Sekunden ohne Antwort auslief und das Gerät weder
  `received` noch einen Panelabschluss meldete. Der Guesty-Filter und die
  Zuordnung waren nicht die Ursache.
- Version 0.3.41 benötigt gemeinsam ein HACS-/Integrationsupdate und ein
  Display-Firmwareupdate. Der erste erfolgreich empfangene Willkommens-Payload
  unterscheidet sich vom festgehaltenen Leerseitenbild und erzwingt deshalb
  einen vollständigen Refresh; erst danach ist eine noch sichtbare
  Randelektrodenabweichung getrennt vom Transportfehler bewertbar.
- Die Runtime-/Firmware-Vertragstests und ESPHome-Konfigurationsvalidierung
  decken den antwortfreien v10-Kanal, die sofortige Empfangsbestätigung und die
  blockierende, datenschutzsichere Home-Assistant-Übergabe ab. Die abschließende
  Zustellungs- und Randprüfung auf dem realen E1001 steht noch aus.

## 0.3.40 – 2026-08-25

### Offizielle E1001-Hardwarekompatibilität

- Die ungenutzte SD-Karten-Stromversorgung wird jetzt über GPIO16 bei jedem
  Start und unmittelbar vor jedem Deep Sleep ausdrücklich ausgeschaltet. Der
  interne Pulldown des TPS22916 bleibt damit nicht länger die einzige
  Absicherung gegen eine versehentlich aktive SD-Versorgung.
- Ein neuer, datenschutzneutraler **E-paper Hardwaretest** prüft auf bestätigter
  externer Versorgung einen vollständigen Vier-Grau-Refresh, einen echten
  differentiellen Refresh des 136×64-Statusfensters und die anschließende
  Wiederherstellung der zuvor aktiven Gast-, Checkout- oder Leerseite. Bei
  Abbruch bleibt der Inhaltsnachweis absichtlich ungültig, sodass der nächste
  Payload das reale Bild zwingend neu zeichnet.
- Die Diagnose **E-paper self-test** meldet getrennt Vollbild-, Teilbild-,
  Wiederherstellungs-, Strom- und Zeitüberschreitungsfehler. Während des Tests
  werden Payloadzustellung, Datenschutz-Löschung und Akkuschlaf serialisiert;
  Gast-, Türcode- und WLAN-Werte werden nicht in Testzustände übernommen.

### Kontrolliertes 32-MB-Flashlayout

- Neu per USB installierte E1001 können im Firmware-Assistenten nun die
  tatsächlich vorhandenen 32 MB Flash verwenden. Das erzeugte Layout wird als
  neutrale Geräte-Diagnose veröffentlicht.
- Bestehende Konfigurationen ohne `flash_size` gelten weiterhin ausdrücklich
  als bisheriges 4-MB-Layout. Automatische Sammelupdates ändern ausschließlich
  Versionsreferenzen und migrieren niemals still die Partitionstabelle.
- Ein Layoutwechsel beim Überschreiben einer verwalteten Gerätekonfiguration
  wird blockiert, bis die einmalige vollständige USB-Installation ausdrücklich
  bestätigt wurde. Eine normale OTA-Installation ist für diesen einzelnen
  Migrationsschritt nicht zulässig.
- Das 32-MB-Profil aktiviert gezielt ESPHomes dafür erforderliche erweiterte
  ESP-IDF-Unterstützung; das bestehende 4-MB-Profil übernimmt diese experimentell
  gekennzeichnete Einstellung nicht. Bis zur Bestätigung auf echter Hardware
  bleibt deshalb das bewährte 4-MB-Profil die Voreinstellung.

### Dokumentation und Prüfstatus

- README, Agenten- und Beitragsleitfaden unterscheiden jetzt die logische
  Framebuffer-Pegelzuordnung von der invertierten UC8179-DTM-Übertragung und
  dokumentieren ESPHome 2026.8.1 sowie den sicheren Flash-Migrationsweg.
- ESPHome 2026.8.1 kompiliert beide Profile vollständig: Das 4-MB-Profil nutzt
  1.510.619 von 1.835.008 App-Bytes (82,3 %), das 32-MB-Profil 1.510.299 von
  16.515.072 Bytes (9,1 %). Beide Profile laufen künftig als parallele CI-Jobs
  mit eigenem 95-Prozent-Limit. Die reale Wirkung des Hardwaretests, die
  explizite SD-Abschaltung und eine vollständige 32-MB-USB-Migration müssen
  noch auf einem E1001 bestätigt werden.

### Physisch bestätigte Display-Zustellung

- Die neue, rückwärtskompatible ESPHome-Aktion v10 bestätigt getrennt, dass ein
  Payload empfangen wurde, der Renderer arbeitet und der physische E-Paper-
  Refresh erfolgreich abgeschlossen wurde. Home Assistant wertet eine bloß
  angenommene Service-Anfrage nicht mehr als Display-Erfolg.
- Zufällige, datenschutzneutrale Zustellkennungen ordnen Reconnect-Meldungen dem
  richtigen Auftrag zu. Begrenzte Empfangs-, Panel- und Wiederholungszeiten,
  ein einzelner aktiver Payload-Handler und das Zusammenfassen überholter
  Aufträge verhindern parallele Rendererzugriffe und Auftragsschleifen.
- Ein fehlgeschlagener v10-Auftrag gilt nicht als empfangenes Wachfenster. Ein
  Akku-Display bleibt dadurch für weitere Zustellversuche bis zur normalen
  90-Sekunden-Grenze wach; ein zuvor sensitives Bild durchläuft anschließend
  weiterhin den bestehenden datenschutzsicheren Löschpfad.
- Der Integrationsstart wartet bei einem schlafenden oder offline befindlichen
  Display weder den gesamten Wiederholungszeitraum noch eine bis zu
  80-sekündige physische Bestätigung ab. Der erste Versuch läuft als sauber
  verwaltete Hintergrundaufgabe; der echte Endpoint- oder Reconnect-Impuls
  startet die zuverlässige Wiederholung später selbst.
- Nach einer bestätigten Aktualisierung darf ein Akku-Display direkt schlafen.
  Sein anschließender Status „nicht verfügbar“ beendet die Zustellung sofort,
  statt noch fünf Sekunden auf einen Aktionsnamen zu warten, den das schlafende
  Gerät nicht mehr veröffentlichen kann.
- ESPHome-Transportausnahmen werden ohne fremden Ausnahmetext oder Traceback
  protokolliert. Zusätzlich akzeptiert die Firmware für Diagnoseimpulse nur
  das erwartete 24-stellige Hexformat der zufälligen Zustellkennung; ungültige
  Direktaufrufe werden auf einen neutralen Ersatzwert begrenzt.
- Lokale Datenschutz-Löschvorgänge auf Akku und Netzstrom sowie der
  Abschlusswait des Legacy-v9-Pfads besitzen jetzt eine feste 70-Sekunden-
  Grenze. Ein Timeout kann weder einen alten Panelerfolg bestätigen noch ein
  Akku-Gerät während einer weiterlaufenden Paneltransaktion schlafen legen.

### Panel-, Rahmen- und Neustartdiagnose

- Neue neutrale ESPHome-Entitäten zeigen Zustellstatus, Resetgrund, aktuelle
  E-Paper-Phase, letzten Controllerfehler, aktive Graustufen-Wellenform und die
  Ansteuerungsart der separaten UC8179-Randelektrode. Gast-, Zugangs- und
  WLAN-Daten werden darin nicht ausgegeben.
- Der Treiber erfasst seine Phasen und Fehler thread-sicher. Damit lässt sich
  unterscheiden, ob ein erzwungener Vollrefresh an Vorbereitung, SPI,
  `BUSY_N` oder Panel-Refresh scheitert und welche Rahmenansteuerung dabei
  tatsächlich gewählt wurde. Die bestehende validierte `LUTBD`-Korrektur und
  Renderrevision 27 bleiben unverändert.
- Download-Diagnosen enthalten zusätzlich ausschließlich neutrale
  Zustellzeitpunkte, Erfolgsstatus und Fehleranzahl. Optionale Guesty-
  Anreicherungsfehler protokollieren keine Reservierungs-/Gastkennungen oder
  fremden Transporttexte mehr. Kontoweite Reservierungen außerhalb der
  konfigurierten Listings werden als erwarteter Debug-Fall statt als
  Mehrdeutigkeitswarnung behandelt.

### Prüfstatus

- Alle 283 Tests sind sowohl mit Home Assistant 2025.12.0 als auch 2026.2.3
  erfolgreich; die Branch-Abdeckung beträgt 90,70 %. Ruff, Formatprüfung,
  Mypy und Bytecode-Kompilierung sind fehlerfrei.
- Die Tests decken zusätzlich den Completion-Timeout, Busy-Retry, parallele
  Display-Zuordnung, echtes Payload-Coalescing, Entladen während einer
  Zustellung, den nicht blockierenden Integrationsstart und die sichere
  Protokollierung von Servicefehlern ab.
- ESPHome 2026.8.1 hat die Referenzkonfiguration validiert und die Firmware
  vollständig kompiliert. Das OTA-Abbild ist 1.506.528 Bytes groß und belegt
  82,1 % der App-Partition; das festgelegte 95-%-Budget wird eingehalten.
- Die Wirkung der bestätigten v10-Zustellung, der automatische Strompfad und
  die Rahmenanzeige müssen nach der Installation noch auf einem realen E1001
  geprüft werden.

### Schnellere CI-Anlaufphase

- Release-Metadaten, statische Analyse, beide Home-Assistant-Baselines und der
  ESPHome-Firmwarebau starten nun sofort parallel. Die Release-Freigabe verlangt
  weiterhin den vollständig erfolgreichen Gesamtworkflow; lediglich die zuvor
  vorgeschaltete Wartezeit entfällt.
- Der stabile ESPHome-Werkzeugcache und der inkrementelle projektbezogene
  Buildcache werden getrennt gespeichert. Bei Firmwareänderungen muss dadurch
  nicht mehr der vollständige rund 1-GB-Cache neu hochgeladen werden, während
  bereits übersetzte Objektdateien weiterhin wiederverwendet werden können.

## 0.3.38 – 2026-08-25

### Verbindlicher Veröffentlichungsprozess

- Ein eigener, manuell gestarteter GitHub-Workflow veröffentlicht nur noch den
  unveränderten `main`-Commit, für den der normale Test-Workflow bereits
  erfolgreich abgeschlossen wurde. Er prüft Versionsangaben, Changelog,
  Distributionsentscheidung und Drittanbieterhinweise erneut, verlangt einen
  ausdrücklichen Hardwarestatus und erzeugt Release-Notizen, annotierten Tag
  und GitHub-Release automatisch.
- Die CI führt die schnelle Release-Vorprüfung zuerst aus und startet danach
  statische Analyse, beide Home-Assistant-Baselines und den ESPHome-Bau
  parallel. Getrennte, exakt gepinnte Abhängigkeiten und sichere Buildcaches
  reduzieren Wiederholungsarbeit; Tag-Pushes starten keinen doppelten Testlauf.
- GitHub-Actions sind auf feste Commitstände gepinnt. Ein abgebrochener Lauf
  darf einen bereits korrekt auf denselben Commit zeigenden Tag sicher
  weiterverwenden, verschiebt oder überschreibt aber niemals einen
  widersprüchlichen Tag.

### Watchdog-sichere Panel-Aufgabe

- Die Geräteprotokolle von 0.3.37 belegen wiederholte Native-API-Abbrüche im
  Abstand von ungefähr 40 Sekunden sowie mehrere zu schnelle Neustarts, obwohl
  die Firmware korrekt installiert und das Gerät am Strom war.
- Die ausgelagerte Panel-Aufgabe rief ESPHomes `App.feed_wdt()` auf. ESPHome
  2026.8.1 registriert jedoch ausschließlich seine Hauptschleife beim
  Task-Watchdog. Der fremde Aufruf konnte den Watchdog nicht für die
  Hauptschleife zurücksetzen, aktualisierte aber deren gemeinsamen
  Zeitstempel. Dadurch unterblieb der echte Watchdog-Reset der Hauptschleife.
- OTP-Lesen und zeilenweise Panel-Übertragungen geben die CPU nun kooperativ
  für Netzwerk-, Haupt- und Idle-Aufgaben frei, ohne aus der Panel-Aufgabe den
  ESPHome-Watchdog anzufassen. Synchrone sichere Abschaltvorgänge versorgen den
  Watchdog weiterhin aus der registrierten Hauptschleife.
- Datenschutz- und Buchungsbestätigung bleiben unverändert an einen
  nachweislich erfolgreichen physischen Refresh gebunden. Neue neutrale
  Diagnosemeldungen markieren Beginn, Ende, Dauer und Erfolg der
  Hardwaretransaktion.

### Prüfstatus

- Der vollständige lokale Python-Prüflauf war mit jeweils 268 Tests gegen Home
  Assistant 2025.12.0 und 2026.2.3 erfolgreich; die Branch-Abdeckung beträgt
  90,79 %. Ruff, Formatprüfung, Mypy und Bytecode-Kompilierung sind ebenfalls
  fehlerfrei.
- ESPHome 2026.8.1 hat die Referenzkonfiguration validiert und die Firmware
  vollständig gebaut. Das Abbild ist 1.465.115 Bytes groß; 20 % der
  App-Partition bleiben frei. Die Korrektur muss nach der Installation noch
  auf dem realen E1001 anhand einer abgeschlossenen Hardwaretransaktion ohne
  Neustart- oder Reconnect-Schleife bestätigt werden.

## 0.3.37 – 2026-08-25

### Erreichbarkeit während der Display-Aktualisierung

- Die reale Geräteanalyse zeigte einen TCP-erreichbaren ESP32, dessen
  ESPHome-Handshake während eines vollständigen E-Paper-Refreshs länger als
  60 Sekunden blockiert war. Home Assistant markierte dadurch alle Entitäten
  als nicht verfügbar. Nach der Wiederverbindung löste der Endpunkt denselben
  Willkommens-Payload erneut aus und konnte so in eine Refresh-/Reconnect-
  Schleife geraten. Die Stromerkennung blieb dabei korrekt auf
  `SY6974B BUS_GD`; Deep Sleep war nicht die Ursache.
- Framebuffer-Aufbau und Payload-Übergabe bleiben im ESPHome-Hauptablauf,
  während ausschließlich die langsamen, hardwarenahen OTP-, SPI- und
  Panel-Transaktionen in einer eigenen ESP32-Aufgabe laufen. Damit bleiben
  Native API, Home Assistant und Diagnose-Entitäten auch während eines langen
  Vollrefreshs ansprechbar.
- Vollständige Payload-Handler und lokale Datenschutz-Löschvorgänge warten
  jetzt auf den Abschluss einer laufenden Panel-Transaktion. Dadurch kann kein
  zweiter Auftrag gemeinsame Renderer-Daten verändern oder einen fremden
  Refresh als seinen eigenen Erfolg verbuchen.
- Die Wartezeit für reine UC8179-OTP-Lesephasen ist auf die dreisekündige
  Grenze der festgehaltenen Seeed-Referenz begrenzt. Die längere
  45-Sekunden-Grenze für echte Panel-Power- und Refreshphasen bleibt erhalten.

### Prüfstatus

- Der vollständige lokale Python-Prüflauf war mit 258 Tests gegen Home
  Assistant 2026.2.3 erfolgreich; die Branch-Abdeckung beträgt 90,79 %. Ruff,
  Formatprüfung, Mypy und Bytecode-Kompilierung sind ebenfalls fehlerfrei.
- ESPHome 2026.8.1 hat die Referenzkonfiguration validiert und die Firmware
  vollständig gebaut. Das OTA-Abbild ist 1.465.024 Bytes groß und bleibt unter
  dem festgelegten 95-Prozent-Flashbudget. Die korrigierte Nebenläufigkeit muss
  nach der Installation noch auf dem realen E1001 bestätigt werden.

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
