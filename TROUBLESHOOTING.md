# GuestyTerminal-Fehlerdiagnose

Dieses Dokument hält wiederverwendbare Diagnosewege und bestätigte
Fehlerursachen fest. Es darf keine Gastnamen, Reservierungs-IDs, Türcodes,
WLAN-Zugangsdaten oder Home-Assistant-/ESPHome-Schlüssel enthalten.

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
