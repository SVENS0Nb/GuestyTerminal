# GuestyTerminal-Fehlerdiagnose

Dieses Dokument hält wiederverwendbare Diagnosewege und bestätigte
Fehlerursachen fest. Es darf keine Gastnamen, Reservierungs-IDs, Türcodes,
WLAN-Zugangsdaten oder Home-Assistant-/ESPHome-Schlüssel enthalten.

## Störung 2026-08-26: identischer Vollrefresh wiederholt sich und Rand bleibt dunkel

### Bestätigte Diagnose

Das reale Gerät mit Firmware 0.3.43 nahm den korrekten Willkommens-Payload an.
Jeder Auftrag erreichte `received` und `rendering`; der Renderer meldete bei
aufeinanderfolgenden Versuchen exakt dieselbe Verteilung der vier
Framebufferstufen. Erst der physische Controllerpfad scheiterte:

1. Reset und `POWER ON` wurden bestätigt.
2. Der Custom-LUT-Pfad meldete für den Rand `validated_lutbd`.
3. Nach `DISPLAY REFRESH` blieb das aktive-low Signal `BUSY_N` 45 Sekunden
   aktiv, obwohl das sichtbare Bild bereits aufgebaut war.
4. Auch `POWER OFF` erreichte innerhalb weiterer zehn Sekunden keinen
   Ruhezustand; v10 meldete deshalb korrekt `panel_error`.
5. Die Home-Assistant-Wiederholungsfolge übertrug unmittelbar danach denselben
   Payload mit neuem Transporttoken. Dadurch entstand etwa alle 56 bis 57
   Sekunden ein weiterer physischer Bildaufbau.

Die sichtbare Wiederholung wurde also weder vom 15-Sekunden-Stromprüfintervall
noch von Wetter, Guesty-Polling oder einem wechselnden Inhaltsfingerabdruck
verursacht. Der erfolgreiche Fingerabdruck durfte nach dem Panel-Fehler
absichtlich nicht gespeichert werden; die Runtime unterschied den bestätigten
Hardwarefehler jedoch noch nicht von einer kurzzeitig fehlenden ESPHome-Aktion.

### Ursache und Korrektur

Der nachträglich ergänzte Randpfad wich von beiden festgehaltenen Seeed-
Referenzen ab: Er las die gemeinsame OTP-`LUTBD`, schrieb sie im Registermodus
nach `R25h` und wählte sie mit einem zusätzlichen `R50h=0x00,0x07` aus. Die
UC8179-Dokumentation beschreibt `R25h` als separate White-to-White-Randtabelle;
auf dem realen E1001 korrelierte dieser Host-Kopierpfad jedoch mit einer nicht
beendeten Vollrefresh-Transaktion. Das Protokoll allein ist kein isolierter
A/B-Nachweis für den Registerpfad; seine Entfernung beseitigt aber die
undokumentierte Abweichung und ermöglicht einen sauberen Vergleich mit Seeeds
Basisfolge. Die frühere Annahme, dieser Pfad habe den dunklen Rand behoben, war
ohne Realgerätetest getroffen worden und ist durch das neue Protokoll
widerlegt.

Der Treiber verwendet deshalb eine begrenzte, nachvollziehbare Kombination aus
Seeeds Basisfolge und dem offiziellen UC8179-Datenblatt:

- OTP und Register-LUT verwenden einmalig `R50h=0x10,0x07`. Mit `PSR` im
  KW-Modus und `DDX=00` wählt `BDV=01` die Schwarz-zu-Weiß-`LUTKW` für die
  separate Randelektrode.
- Nach OTP `RE5h=0x5F` folgt kein zweites `R50h` mehr; `R25h` wird nicht
  beschrieben.
- Die unveränderte Seeed-Endspannung `R52h=0x00` aus 0.3.33 hatte den Rand auf
  dem realen Gerät nicht beseitigt. Beide Vollrefresh-Modi verwenden nun
  `R52h=0x03`: `VCEND` bleibt auf `VCOM_DC`, während `BDEND=11` die
  Randelektrode direkt nach ihrer Weiß-Wellenform freigibt.
- Vor `POWER OFF` wird `R50h` nicht erneut verändert. Laut Datenblatt gibt der
  Ausschaltbefehl Source, Gate, Border und VCOM selbst hochohmig frei; die in
  0.3.34 bis 0.3.43 getesteten späten `R50h`-Varianten hatten den bistabilen
  dunklen Rand nicht aufgehellt.
- Die RTC-Auswahl erhält eine neue Versionskennung und wird einmal neu geprüft;
  Renderrevision 29 erzwingt genau einen korrigierten Vollrefresh.

Zwei unabhängige Schleifensicherungen verhindern unnötige E-Paper-Belastung:
Home Assistant wiederholt einen bestätigten `panel_error`/`panel_timeout` nicht
sofort, und die Firmware hält den fehlgeschlagenen Inhaltsfingerabdruck bis zum
Neustart nur im RAM. Ein wirklich geänderter Payload oder ein ausdrücklich
erzwungener Refresh bleibt möglich.

Die Schleifensperre und ihre bestätigte Ursache sind damit vollständig
softwareseitig testbar. Ob der neue fließende Rand-Endzustand den sichtbaren
Pigmentrand tatsächlich aufhellt, kann dagegen nur der nächste Vollrefresh auf
dem realen E1001 entscheiden; bis dahin ist diese Teilkorrektur ausdrücklich
nicht als hardwarebestätigt dokumentiert.

### Realgerät-Nachtest 0.3.44 und Folgerung

Der anschließende Test mit Firmware 0.3.44 bestätigte zunächst die
Transaktionskorrektur: Im OTP-Modus endete der Vollrefresh nach rund 3,5
Sekunden erfolgreich, `POWER OFF` nach rund 33 Millisekunden, und ein danach
identisch zugestellter Payload wurde ohne weitere Panelaktivität unterdrückt.
Die frühere Refresh-Schleife war damit behoben.

Der sichtbare Rand blieb jedoch grau. Ein kontrollierter Wechsel nur der
vorhandenen Einstellung `gray_lut_mode` ergab:

- `auto/otp`: Schrift und Bild sind dunkler und kontrastreicher, der separate
  Rand ist ebenfalls dunkler.
- `custom`: Der Rand wird sichtbar heller, aber zugleich wird auch das gesamte
  Pixelbild einschließlich der Schrift heller.

Damit ist der 800×480-Renderer als Ursache ausgeschlossen. Pixelbild und Rand
verwenden zwar getrennte UC8179-Ausgänge, wurden aber weiterhin von derselben
ausgewählten Schwarz-zu-Weiß-Wellenform beeinflusst. Die nachhaltige Korrektur
trennt deshalb beide Aufgaben: Normale Vollrefreshs lassen die Randelektrode
mit `R50h.BDZ=1` hochohmig. Eine nur auf bestätigter externer Versorgung
zulässige Randkorrektur führt einmal Seeeds bereits vorhandene Custom-`LUTKW`
aus, schaltet das Panel sauber aus und zeichnet denselben Framebuffer danach
mit der zuvor gewählten Pixelwellenform und weiterhin hochohmigem Rand neu.
Renderrevision 30 fordert diesen Ablauf beim Upgrade einmalig an; der
Diagnosebutton **E-paper Randkorrektur** erlaubt eine kontrollierte,
serialisierte Wiederholung. Inhaltsfingerabdrücke und Gastdaten werden dabei
nicht verändert. Die Architektur ist statisch und per Firmwarebau prüfbar;
die endgültige Weißwirkung benötigt weiterhin den Realgerätetest.

### Realgerät-Nachtest 0.3.45 und isolierter Monochrom-Testpfad

Der Realgerätetest von 0.3.45 widerlegte auch die Custom-LUT-Konditionierung:
Der Rand wurde zwar heller, verschwand aber nicht; zugleich war die Schrift im
Custom-Modus sichtbar weniger schwarz. Die zwei unmittelbar
aufeinanderfolgenden Refreshs waren der vorgesehene Zwei-Pass-Ablauf und kein
zweiter Home-Assistant-Payload. Der erste Pass verwendete jedoch weiterhin die
Vier-Grau-Initialisierung und reproduzierte damit nicht den früheren
randfreien Zustand.

Die Historie zeigt, dass GuestyTerminal bis einschließlich 0.3.2 ESPHomes
eingebautes Waveshare-Modell `7.50inv2` verwendete. Dieser alte Pfad zeichnete
das E1001 ausschließlich monochrom über den panelinternen KW-OTP-Modus: Er
programmierte `R50h=0x10,0x07`, `R60h=0x22`, `R00h=0x1F`, Geometrie und
Single-SPI und übertrug nur die neue DTM2-Ebene (`R13h`). Er verwendete weder
die Custom-Graustufen-LUTs noch `R52h` oder die Force-Temperature-Auswahl des
Vier-Grau-Pfads.

Firmware 0.3.46 wechselt nicht zum alten Treiber zurück. Sie implementiert
diese funktionale UC8179-Registerfolge unabhängig aus dem offiziellen
Datenblatt als einmaligen, nur bei bestätigter externer Versorgung zulässigen
Vorlauf im aktuellen Treiber:

1. Der UC8179 wird für den früher randfreien monochromen KW-OTP-Zustand mit
   `R01h=07,07,3F,3F`, `R50h=0x10,0x07`, `R60h=0x22`, `R00h=0x1F`, der
   800×480-Geometrie in `R61h` und Single-SPI über `R15h=0x00` initialisiert.
2. Der aktuelle Framebuffer wird nur für diesen Vorlauf nach Schwarzweiß
   quantisiert und ausschließlich als neue DTM2-Ebene über `R13h` übertragen.
   Nach dem abgeschlossenen Refresh wird der Controller sauber ausgeschaltet.
3. Anschließend wird exakt derselbe, unangetastete Vier-Grau-Framebuffer mit
   dem aktuellen Vier-Graustufen-Treiber, der ausgewählten Pixelwellenform und
   hochohmiger Randelektrode neu gezeichnet.

Der Realgerätetest am 26. August 2026 bestätigte das Ergebnis: Der zuvor auch
nach mehreren LUTBD-, High-Z- und Custom-LUT-Versuchen sichtbare dunkle bzw.
graue Außenrand ist nach diesem Ablauf vollständig verschwunden; Text und Bild
bleiben im kontrastreichen `auto/otp`-Graustufenpfad schwarz. Die zwei direkt
aufeinanderfolgenden Panelaktualisierungen beim ersten maßgeblichen Bild sind
absichtlich der Monochrom-Vorlauf und der endgültige Vier-Grau-Aufbau, nicht
zwei Home-Assistant-Payloads. In Firmware 0.3.46 gilt verbindlich:
Renderrevision 31 fordert den Test einmalig an. Neuere Firmwarestände bewahren
den erfolgreichen Rand-Vorlauf in einem eigenen, nicht sensiblen
Konditionierungsstand auf. Dadurch können Layout, Schrift oder Tonkurve einen
notwendigen Pixel-Neuaufbau auslösen, ohne den Rand-Vorlauf erneut zu starten.
Spätere identische Inhalte bleiben durch den erfolgreichen Inhalts- und
Rendernachweis ohne weitere physische Aktualisierung unterdrückt.

Ist das Pixelbild insgesamt zu dunkel, wird die Helligkeit nicht über
`gray_lut_mode` oder die Randkorrektur eingestellt. Die Substitution
`gray_gamma` steuert ausschließlich die mittleren Pixelstufen: `1.35` ist der
hellere Standard, `1.0` entspricht der früheren dunkleren Abstufung. Schwarz
und Weiß bleiben bei beiden Werten unverändert.

Diese Abgrenzung ist für künftige Änderungen verbindlich: Den Rand nicht über
den Renderer, einen Pixelrahmen, die Custom-Graustufen-LUT oder eine späte
`R50h`-Änderung beim Ausschalten behandeln. Diese Ansätze entfernten den
bistabilen Rand nicht oder hellten zugleich die Schrift auf. Der funktionierende
Monochrom-Vorlauf darf nicht periodisch ausgeführt, nicht mit Gastdaten oder
Inhaltsfingerabdrücken gekoppelt und nicht durch einen Wechsel zurück zum alten
GPL-Treiber ersetzt werden. ESPHomes GPL-Treibercode wurde nur zur historischen
Verhaltenszuordnung verglichen und nicht übernommen.

Die zugehörigen Hardwaretest-, Randkorrektur- und Controllerdiagnosen sind in
der normalen Alltagsansicht nicht sichtbar. Für eine begrenzte Fehlersuche kann
`advanced_diagnostics_internal: "false"` in den YAML-`substitutions` gesetzt
und die Firmware erneut installiert werden. Danach stellt `"true"` wieder die
reduzierte Standardansicht her; die Diagnosefunktionen selbst werden dabei
nicht aus der Firmware entfernt.

### Nebenbefund: WLAN-QR in ESPHome-Diagnose

Das Protokoll zeigte außerdem, dass ESPHomes `qr_code.dump_config()` den
aktuellen QR-Rohwert ausgibt. Ein Willkommensauftrag konnte vor der späteren
Konfigurationsausgabe bereits den echten WLAN-QR gesetzt haben. Ein neutraler
Startwert allein reicht daher nicht. Der QR-Inhalt wird nun nur für den
synchronen Framebuffer-Aufbau gesetzt und unmittelbar nach
`component.update` wieder auf `GuestyTerminal` zurückgesetzt. Auch die
Wiederherstellung nach dem Hardwaretest benutzt dieses kurze Zeitfenster.

Künftige Logprüfungen müssen zusätzlich sicherstellen, dass keine Zeile mit
einem `WIFI:T:`-Payload erscheint. Wurde ein solches Protokoll außerhalb einer
vertraulichen Umgebung weitergegeben, ist das betroffene WLAN-Passwort zu
ändern.

## Störung 2026-08-25/26: Willkommensbild bleibt aus

### Ergebnis und Geltungsbereich

Nach der gemeinsamen Installation von Integration und Display-Firmware 0.3.43
wurde das richtige Willkommensbild am realen reTerminal E1001 erfolgreich
synchronisiert. Damit ist die Korrektur des hier beschriebenen Zustellfehlers
praktisch bestätigt. Die vollständige Hardwarematrix, insbesondere alle
Wellenform-, Rand-, Teilrefresh-, Tiefschlaf- und Fehlerszenarien, ist dadurch
nicht automatisch abgedeckt.

Der Fehler lag nicht in Guestys Buchungsdaten, der Drei-Seiten-Auswahl, dem
Fünf-Buchungen-RAM-Snapshot oder der Zuordnung von Listing und Display. Home
Assistant hatte den Willkommens-Payload korrekt vorbereitet und das Gerät hatte
ihn bereits angenommen. Der Ausfall entstand danach in der Firmware, noch vor
dem Beginn des normalen Renderers.

### Eindeutige Diagnosekette

Die v10-Zustellung veröffentlicht nacheinander drei datenschutzneutrale
Bestätigungen:

1. `received`: Die ESPHome-Aktion hat den Payload angenommen.
2. `rendering`: Der Payload wurde in den flüchtigen Gerätezustand übernommen
   und der Renderer wird gestartet.
3. `success` oder `unchanged`: Der physische Refresh war erfolgreich oder ein
   bereits identischer, erfolgreich gezeichneter Inhalt wurde nachgewiesen.

Beim Fehler erschien `received`, aber kein `rendering`. Das grenzt den Defekt
auf den synchronen Abschnitt der ESPHome-Aktion zwischen Empfangsbestätigung
und Rendererstart ein. Guesty-Abfrage, Reservierungsauswahl, Home-Assistant-
Transport und E-Paper-BUSY/LUT-Ablauf liegen außerhalb dieses Abschnitts.

### Technische Ursache

Die Aktion setzte den WLAN-QR-Wert und rief anschließend
`generate_qr_code()` ausdrücklich auf. ESPHomes QR-Encoder benötigt dabei
ungefähr 4 KiB temporären Stack. Gleichzeitig lagen die vielen versionierten
Aktionsargumente und lokalen Werte des Willkommens-Payloads noch auf dem
standardmäßig nur 8 KiB großen ESP32-Loop-Task-Stack.

Diese frühe QR-Berechnung war außerdem doppelt: Der eigentliche Renderer ruft
später `get_size()` auf. ESPHome erzeugt dort einen als geändert markierten
QR-Code automatisch und löscht anschließend dessen Dirty-Status. Die erste
Berechnung belastete daher den tiefen API-Aktionspfad, ohne für das Bild nötig
zu sein. Das beobachtete Muster – `received`, danach kein `rendering`,
Panic/Neustart beziehungsweise vorübergehende Unerreichbarkeit – entspricht
einem Loop-Task-Stacküberlauf an genau dieser Stelle. Da kein vollständiger
Low-Level-Stacktrace erhalten blieb, ist „Stacküberlauf“ die durch Codepfad,
Loggrenze und erfolgreiche 0.3.43-Gegenprobe gestützte technische Ursache,
nicht die Bezeichnung eines direkt aufgezeichneten Exception-Texts.

### Warum das Hardwaretestbild trotzdem funktionierte und stehen blieb

Das neutrale Hardwaretestbild benutzt weder den normalen v10-Willkommens-
Payload noch dessen WLAN-QR-Berechnung. Es konnte deshalb Framebuffer, SPI,
Panel und Vier-Grau-Refresh erreichen, obwohl der normale Aktionspfad vorher
abstürzte. Ein erfolgreiches Testbild beweist in diesem Fall nur den separaten
Panelpfad; es beweist nicht, dass der Buchungspfad funktioniert.

E-Paper ist bistabil und behält das zuletzt physisch gezeichnete Bild ohne
Strom. Ein Neustart des ESP32 löscht dieses Bild nicht. Weil der spätere
Willkommens-Payload nie bis zu einem erfolgreichen Vollrefresh kam, blieb das
Testbild beziehungsweise zuvor gezeichnete Leerseitenbild sichtbar. Das war
kein Beweis für einen veralteten Home-Assistant-Payload.

### Korrektur in 0.3.43

- v10 und die kompatible v9-Aktion setzen nur noch den QR-Wert. Ausschließlich
  der Renderer erzeugt ihn einmalig über `get_size()`.
- Der ESP32-Loop-Task erhält 16 KiB Stack als zusätzliche Sicherheitsreserve
  für QR-Encoder, Aktionsargumente und Rendering.
- Der QR-Startwert ist neutral, damit `dump_config()` keine
  kennwortähnliche Testbelegung ausgibt.
- Home Assistant plant lange physische Displayzustellungen mit
  `async_create_background_task()` statt als Bootstrap-Aufgabe. Dieser zweite
  Fehler verursachte nicht den QR-Absturz, konnte aber Home Assistants Start
  bis zur langen E-Paper-Frist blockieren und Entitäten verspätet verfügbar
  machen.

### Verbindliche Schutzregeln

- In einer ESPHome-Payload-Aktion niemals `generate_qr_code()` aufrufen. Der
  QR-Code wird genau einmal und nur im Renderer über `get_size()` erzeugt.
- `loop_task_stack_size: 16384` nicht ohne gemessene Stackanalyse und einen
  vollständigen Realgerätetest reduzieren.
- Änderungen an QR-Code, Aktionsschema oder Renderer müssen mit nicht leerem
  WLAN-Namen und Passwort die Folge `received` → `rendering` → `success` auf
  einem realen E1001 erreichen. Zugangsdaten dürfen dabei nicht protokolliert
  werden.
- Ein funktionierendes Hardwaretestbild darf niemals als Nachweis für den
  normalen Buchungspfad gelten. Beide Pfade müssen getrennt geprüft werden.
- Lange Panelzustellungen dürfen Home Assistants Integrationseinrichtung nicht
  als Setup-Aufgabe blockieren; die Runtime muss ihre Hintergrundaufgaben
  trotzdem beim Entladen abbrechen.
- Die Firmware-Vertragstests müssen den fehlenden expliziten
  `generate_qr_code()`-Aufruf, genau einen Renderer-`get_size()`-Pfad, 16 KiB
  Loop-Stack und den neutralen QR-Startwert festhalten. Die Runtime-Tests müssen
  weiterhin nachweisen, dass keine Displayzustellung als Setup-Aufgabe erzeugt
  wird.

### Schnelle Einordnung künftiger Zustellfehler

| Letzte Bestätigung | Wahrscheinlicher Fehlerbereich |
| --- | --- |
| keine | Endpoint-Erkennung, ESPHome-Verbindung oder Serviceübergabe |
| `received` | synchroner Firmware-Aktionspfad vor dem Renderer; zuerst QR, Stack und Payload-Übernahme prüfen |
| `rendering` | Renderer, Auftragsserialisierung oder physischer Panel-/BUSY-/LUT-Pfad |
| `success` | Bild wurde physisch bestätigt; danach Seitenzustand, sichtbaren Inhalt und Diagnosezuordnung prüfen |
| `unchanged` | Fingerprint-Unterdrückung; prüfen, ob Inhalt und Renderrevision wirklich identisch sind |

Ein dunkler Panelrand ist getrennt zu untersuchen. Er gehört zur
Randelektroden-/Wellenformansteuerung nach dem Renderbeginn und war nicht die
Ursache dafür, dass der Willkommens-Payload vor `rendering` abbrach.
