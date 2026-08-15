# GuestyTerminal für reTerminal E1001

<img src="assets/guestyterminal-logo.png" alt="GuestyTerminal Logo" width="128">

Das Logo wird zusätzlich als lokales Home-Assistant-Brand-Asset ausgeliefert
und erscheint ab Home Assistant 2026.3 direkt auf der Integrationsseite.

Dieses Projekt verbindet Guesty mit Home Assistant und zeigt die Daten der
aktuellen Reservierung auf einem Seeed Studio reTerminal E1001 an:

- persönlicher Willkommensgruß;
- Guesty-Reservierungsfeld `keycode`;
- WiFi-Name und Passwort;
- lokal erzeugter, direkt verbindender WiFi-QR-Code;
- Check-out-Zeit;
- pro Display wählbares EU- oder US-Datums- und Zeitformat;
- optionales Wettersymbol mit gerundeter Außentemperatur aus einer pro Display
  wählbaren Home-Assistant-Wetterentität;
- einheitliches Design mit zwei gleich großen, hellgrauen Feldern für Türcode
  und WiFi;
- höhere, aufgeräumte Fußleiste mit optionalem globalem Unterkunftslogo;
- vier echte Graustufen für geglättete, besser lesbare Schriftkanten;
- automatische neutrale Seite 30 Minuten nach Check-out oder bei Stornierung;
- Zuordnung eines Guesty-Listings zu jedem Display in der Home-Assistant-UI;
- Firmware-Assistent für gerätespezifische E1001-Konfigurationen;
- zentraler Home-Assistant-Knopf für OTA-Sammelupdates aller von
  GuestyTerminal verwalteten Displays.

Die Guesty-Zugangsdaten verbleiben in Home Assistant. Sie werden niemals auf
dem ESP32 gespeichert oder an das Display übertragen.

Die Geräte verwenden weiterhin ESPHome. GuestyTerminal erstellt die passende
Konfiguration über die Home-Assistant-UI; ESPHome Device Builder kompiliert und
installiert daraus die Firmware.

## Architektur

1. Die Custom Integration ruft Listings und ausschließlich bestätigte
   Reservierungen über die aktuelle Guesty-v3-Suche ab.
2. `keycode` wird zuerst direkt aus der Reservierung gelesen. Falls Guesty es
   als Custom Field zurückgibt, löst die Integration die Field-ID über die
   Account-Felddefinitionen auf.
3. Jedes E1001 veröffentlicht in Home Assistant eine diagnostische Entität
   namens `GuestyTerminal Endpoint`.
4. In den Optionen der Integration wird diese Entität einem Listing zugeordnet.
5. Wenn das E1001 aufwacht, überträgt Home Assistant die aktuellen Daten über
   eine ESPHome Native-API-Aktion. Dazu gehört auch das einmal zentral gewählte
   Logo. Das Gerät zeichnet nur dann neu, wenn sich der sichtbare Inhalt
   tatsächlich geändert hat. Wetterwerte werden auf ganze Grad gerundet, damit
   kleine Sensorschwankungen keine unnötigen E-Paper-Aktualisierungen auslösen.

## Voraussetzungen

- Home Assistant 2025.12 oder neuer;
- das Home-Assistant-Add-on **ESPHome Device Builder 2026.7 oder neuer** mit
  Unterstützung für Sammelupdates, `api.actions` und `qr_code`;
- Guesty Open API-Zugriff mit Client-ID und Client-Secret;
- reTerminal E1001 im 2,4-GHz-WLAN;
- in Guesty gepflegte Listing-Felder `wifiName` und `wifiPassword`;
- Reservierungsfeld oder Custom Field `keycode`.

Die Konfiguration wurde vollständig mit ESPHome 2026.7.4 für ESP32-S3 gebaut
und mit Home Assistant 2026.2.3 importiert. Neuere kompatible Versionen können
ebenfalls verwendet werden.

## Installation der Home-Assistant-Integration

### Über HACS als benutzerdefiniertes Repository

1. Die Repository-URL
   `https://github.com/SVENS0Nb/GuestyTerminal` kopieren.
2. In HACS **Integrationen** öffnen.
3. **Benutzerdefinierte Repositories** auswählen.
4. Die Repository-URL als Kategorie **Integration** hinzufügen.
5. **GuestyTerminal** installieren und Home Assistant neu starten.

### Manuell

Den Ordner `custom_components/guesty_terminal` nach
`/config/custom_components/guesty_terminal` kopieren und Home Assistant neu
starten.

## Guesty verbinden

1. Guesty öffnen und unter **Integrationen → API & Webhooks** eine API-Anwendung
   erstellen.
2. In Home Assistant **Einstellungen → Geräte & Dienste → Integration
   hinzufügen → **GuestyTerminal** öffnen.
3. Client-ID und Client-Secret eingeben. Zugangsdaten nicht in YAML, Git oder
   Support-Nachrichten einfügen.

Die Integration speichert und verwendet das etwa 24 Stunden gültige
OAuth-Zugriffstoken weiter, statt bei jedem Abruf ein neues Token zu erzeugen.

## Firmware über die GuestyTerminal-UI erstellen

1. In `/config/esphome/secrets.yaml` mindestens `wifi_ssid` und
   `wifi_password` hinterlegen. Diese beiden Werte werden von der erzeugten
   Konfiguration nur als ESPHome-Secrets referenziert.
2. In Home Assistant **Einstellungen → Geräte & Dienste → GuestyTerminal →
   Konfigurieren → E1001-Firmware erstellen** öffnen.
3. Einen eindeutigen Gerätenamen vergeben. **Automatisch** und 30 Minuten sind
   die empfohlenen Energieeinstellungen.
4. Nach dem Speichern ESPHome Device Builder öffnen. Das neue Gerät erscheint
   dort unmittelbar.
5. **Installieren** wählen. Für die erste Installation das E1001 per USB
   anschließen; spätere Aktualisierungen sind auch OTA möglich.

Der Assistent erzeugt für jedes Gerät einen eigenen API-Schlüssel, ein eigenes
OTA-Passwort und ein eigenes Fallback-AP-Passwort. Eine vorhandene, nicht von
GuestyTerminal verwaltete ESPHome-Datei wird niemals überschrieben. Beim
bewussten Aktualisieren einer vom Assistenten erzeugten Datei bleiben diese
Geräteschlüssel erhalten, damit der OTA-Zugriff nicht verloren geht.

### Manuell flashen

1. `esphome/secrets.example.yaml` nach `esphome/secrets.yaml` kopieren.
2. Alle Platzhalter durch neue, zufällige Werte ersetzen.
3. In `esphome/guestyterminal-display-1.yaml` Gerätenamen, Anzeigenamen und bei
   Bedarf die Energieeinstellungen anpassen.
4. Konfiguration installieren:

   ```bash
   esphome run esphome/guestyterminal-display-1.yaml
   ```

Beim Build erscheinen Hinweise zu GPIO 3, 19 und 20. Diese Pins stammen aus
der offiziellen E1001-Hardwarebelegung und sind für dieses Board beabsichtigt.

GuestyTerminal verwendet einen eigenen UC8179-Treiber für die vier nativen
Graustufen des GDEY075T7-Panels. Schriftdateien werden zunächst mit 4 Bit pro
Pixel gerastert und anschließend auf die vier Panelstufen quantisiert. QR-Code
und Türcode bleiben dabei satt schwarz und werden ohne sichtbare
Umrandung gezeichnet. Da das Panel im OTP nur eine
Schwarz-Weiß-Wellenform enthält, verwendet der Treiber für vier Graustufen
ausschließlich die erprobten Register-LUTs und die Initialisierungsfolge aus
GxEPD2_4G. So bleibt GPIO9 durchgehend als SPI-Datenleitung konfiguriert. Die
beiden UC8179-Bitebenen verwenden die direkte Pegelzuordnung
`00 = Schwarz`, `01 = Dunkelgrau`, `10 = Hellgrau` und `11 = Weiß`.

Für weitere Displays die Beispieldatei kopieren und einen eindeutigen
`device_name` verwenden. Alle Geräte verwenden dasselbe Layout-Paket.

## Globales Logo für alle Displays

1. In **Einstellungen → Geräte & Dienste → GuestyTerminal → Konfigurieren →
   Allgemeine Einstellungen** gehen.
2. Eine PNG- oder JPEG-Datei mit maximal 5 MB auswählen.
3. Speichern. Die Integration entfernt transparente bzw. weiße Außenflächen,
   skaliert das Logo proportional auf 144 × 48 Pixel und quantisiert es auf die
   vier E-Paper-Graustufen. Das sichtbare Motiv wird innerhalb dieser Fläche
   rechtsbündig ausgerichtet und endet wie der linke Fußtext mit 32 Pixel
   Abstand zum Displayrand.

Das Logo wird einmal zentral gespeichert und gilt für alle Display-Zuordnungen.
Es erscheint ohne Rahmen unten rechts in der höheren Fußleiste. Ersetzen oder
Entfernen wird nach der einmaligen Firmwareaktualisierung dynamisch an alle
erreichbaren Displays übertragen und erfordert keine weitere Kompilierung.
Bereits gespeicherte Logos werden automatisch rechts ausgerichtet; ein erneuter
Upload ist nicht erforderlich.

## Listing einem Display zuordnen

1. Das E1001 mit der grünen Taste aufwecken und warten, bis es in Home
   Assistant online ist.
2. In **Einstellungen → Geräte & Dienste → GuestyTerminal → Konfigurieren**
   gehen.
3. **Listing einem Display zuordnen** wählen.
4. Zuerst das reTerminal auswählen. Anschließend werden dessen bereits
   gespeichertes Listing, Begrüßung und Anzeigezeitraum geladen und können
   bearbeitet werden.
5. Optional eine Home-Assistant-`weather`-Entität für Wettersymbol und
   Außentemperatur auswählen.
6. Für jedes weitere Display wiederholen.

Das Datums- und Zeitformat wird pro Display gespeichert. **EU** verwendet
beispielsweise `17.08.2026 · 14:00 Uhr`, **US** dagegen
`08/17/2026 · 2:00 PM`. Die Auswahl gilt auch für die Platzhalter `check_in`
und `check_out`.

Die Wetterauswahl wird ebenfalls pro Display gespeichert. Ist keine Entität
ausgewählt oder ist sie nicht verfügbar, bleibt der Wetterbereich leer. Die
Firmware zeigt nur das zum aktuellen Zustand passende Symbol und die gerundete
Temperatur samt Einheit; eine zusätzliche Beschreibung wird nicht eingeblendet.
Die Symbole stammen aus dem fest auf Version 7.4.47 gesetzten
[Material-Design-Icons-Wetterset](https://pictogrammers.com/library/mdi/). In die
Firmware werden nur die tatsächlich benötigten Wetterglyphen eingebaut.

Verfügbare Platzhalter für Begrüßungen:

- `{first_name}`
- `{property_name}`
- `{check_in}`
- `{check_out}`

Der Standardtitel lautet `Willkommen, {first_name}!`.

## Anzeige- und Sicherheitsverhalten

- Der Gastbildschirm erscheint standardmäßig eine Stunde vor Check-in.
- 30 Minuten nach Check-out wird er durch eine neutrale Seite ersetzt.
- Maßgeblich ist ausschließlich der Guesty-Reservierungsstatus `confirmed`.
  Zahlungsstatus, Zahlungseingang und Auszahlung durch Airbnb oder andere
  Buchungsportale werden bewusst nicht ausgewertet.
- Im empfohlenen Modus **Automatisch** liest die Firmware den Power-Good-Status
  des E1001-v1.2-Ladecontrollers aus. Auf Akku schläft das Gerät 30 Minuten und
  bleibt nach dem Aufwachen höchstens 90 Sekunden aktiv. Sobald Home Assistant
  die aktuellen Daten geliefert hat, schläft es früher wieder ein. Falls ein
  älterer Hardwarestand USB-Strom nicht erkennt, kann im Assistenten **Immer
  online** ausgewählt werden.
- Bei angeschlossenem USB-Strom bleibt das Gerät online. Wird der Strom später
  getrennt, wechselt es automatisch beim nächsten 15-Sekunden-Test in den
  Akkubetrieb. Im Akkubetrieb schläft es für das konfigurierte Intervall –
  standardmäßig 30 Minuten – vollständig. Wird währenddessen USB angeschlossen,
  erkennt das Gerät dies beim nächsten regulären Aufwachen und bleibt danach
  online.
- Die grüne Taste kann das Gerät zusätzlich aus dem Deep Sleep wecken.
- GPIO-Status-LED, Lade-LED-Ausgang, Buzzer und Mikrofon-Stromversorgung werden
  von der Firmware deaktiviert. Nach einem vollständigen stromlosen Neustart
  kann die hardwaregesteuerte Lade-LED bis zum Start der Firmware sehr kurz
  aufleuchten; vollständig verhindern lässt sich diese Startphase nur durch
  eine physische Abdeckung oder Hardwareänderung.
- Weil E-Paper das letzte Bild stromlos behält, erhält jeder Gastbildschirm eine
  erneuerbare 15-Minuten-Freigabe. Home Assistant erneuert sie beim regulären
  Abruf bis 30 Minuten nach Check-out. Nach dem Entfernen einer Zuordnung oder
  Integration verschwinden die Zugangsdaten dadurch auch dann zeitnah, wenn das
  Display beim Entfernen geschlafen hat.
- Wiederholte Abgleiche und 30-Minuten-Aufwachzyklen mit identischen Daten
  lösen keine E-Paper-Aktualisierung und damit auch kein Kontrastblinken aus.
  Nach einer schnellen Wiederverbindung signalisiert die Firmware Home
  Assistant trotzdem zuverlässig, den zwischengespeicherten Inhalt erneut zu
  senden; unveränderte Bilder werden dabei weiterhin nicht neu gezeichnet.
  Auf dem Gerät bleibt dafür nur eine kryptografische, mit der Reservierungs-ID
  gesalzene Inhalts-ID erhalten; die Zugangsdaten selbst werden nicht dauerhaft
  gespeichert.
- Ändert sich ausschließlich der Wetterzustand oder die gerundete Temperatur,
  aktualisiert die Firmware nur das 136 × 64 Pixel große Wetterfenster oben
  rechts. Dieser differentielle Schwarzweiß-Refresh verursacht kein
  vollständiges Kontrastblinken. Nach fünf aufeinanderfolgenden Teilupdates
  folgt beim nächsten Wetterwechsel automatisch ein vollständiger
  Vier-Graustufen-Refresh gegen Ghosting. Änderungen an Buchung, Logo,
  Zugangsdaten oder Layout werden immer vollständig aktualisiert. Kann ein
  Teilupdate nicht sicher ausgeführt werden, fällt der Treiber automatisch auf
  einen vollständigen Refresh zurück. Unveränderte Wetterdaten lösen weiterhin
  überhaupt keine E-Paper-Aktualisierung aus.
- Jedes Display stellt in Home Assistant seinen Batteriestand sowie die Buttons
  **Display aktualisieren** und **Neustart** bereit. Der Aktualisieren-Button
  zeichnet das aktuelle Bild bewusst sofort neu. Im Deep Sleep sind die beiden
  Buttons bis zum nächsten Aufwachen nicht erreichbar. Der Batteriestand wird
  bei jedem Aufwachen und bei USB-Betrieb alle fünf Minuten neu gemessen.
- Die Diagnose-Entität **Angezeigte Buchung** nennt Gastname und Zeitraum der
  Buchung, deren Bild das E-Paper zuletzt erfolgreich bestätigt hat. Sie wird
  erst nach einem abgeschlossenen BUSY-Zyklus aktualisiert. Nach einem normalen
  Aufwachen darf die Firmware denselben bestätigten Stand anhand der
  gespeicherten, nicht umkehrbaren Inhalts-ID erneut melden.
- Türcode, WiFi-Name und WiFi-Passwort werden auf dem E1001 nur im RAM gehalten.
- Der WiFi-QR-Code wird lokal erzeugt. Sonderzeichen werden nach dem WiFi-QR-
  Format maskiert; es wird kein externer QR-Dienst verwendet.
- Das Display sollte nur innerhalb der Unterkunft und nicht von außen sichtbar
  montiert werden.
- Falls eine frühere YAML-Datei echte WLAN-, OTA- oder API-Schlüssel enthielt,
  diese vor dem produktiven Einsatz ändern.

## Manuelle Aktualisierung

Die Home-Assistant-Aktion `guesty_terminal.refresh` lädt Guesty-Daten sofort neu
und aktualisiert alle momentan erreichbaren Displays. Schlafende Displays
erhalten die Daten bei ihrem nächsten Aufwachen.

Die Aktion `guesty_terminal.force_redraw` zeichnet den bereits geladenen Inhalt
einmal neu. Sie fragt Guesty nicht erneut ab und ist für die Wiederherstellung
nach einem Treiber- oder Firmwarewechsel gedacht. Im normalen Betrieb bleibt
die automatische Unterdrückung identischer E-Paper-Aktualisierungen aktiv.

Die Konfigurationsentität **Alle Display-Firmwares aktualisieren** hebt zuerst
alle durch den Firmware-Assistenten erzeugten YAML-Dateien auf die aktuelle
GuestyTerminal-Version. Danach übergibt sie sämtliche Konfigurationen als einen
OTA-Sammelauftrag an den ESPHome Device Builder. Gerätespezifische WiFi-, API-,
OTA- und Fallback-Zugangsdaten bleiben unverändert. Fremde ESPHome-Dateien
werden weder verändert noch installiert.

Am Strom angeschlossene Displays werden nach dem Build direkt aktualisiert.
Für schlafende Akku-Displays merkt der Device Builder den Auftrag vor und
installiert ihn beim nächsten Aufwachen. Während des eigentlichen Flashens darf
das Gerät nicht ausgeschaltet werden. Fortschritt und mögliche Fehler sind im
ESPHome Device Builder sichtbar.

Das Design mit den zwei grauen Zugangsfeldern wird auf dem E1001 gerendert und
benötigt Firmware **0.3.11** oder neuer. Die MDI-Wettersymbole und der hybride
Teilrefresh benötigen Firmware **0.3.13** oder neuer. Die Wetterentität kann
danach ohne erneutes Kompilieren in der GuestyTerminal-Zuordnung geändert
werden.

## Datenschutz

Die von der Integration angelegten Statussensoren enthalten weder Gastnamen
noch Tür- oder WiFi-Codes. In den Attributen steht lediglich, ob der aktuelle
Bildschirm solche Daten enthält. Fehlerprotokolle geben ebenfalls keine
Zugangsdaten aus.

Für Teilupdates behält der RTC-Speicher ausschließlich ein monochromes Abbild
des kleinen Wetterfensters und die Anzahl der Teilupdates. Zusätzlich werden
zwei nicht rückrechenbare Inhaltsfingerabdrücke gespeichert. Buchungsname,
Türcode und WiFi-Zugangsdaten werden dafür nicht dauerhaft abgelegt.

Die ESPHome-Diagnose-Entität **Angezeigte Buchung** ist hiervon bewusst
ausgenommen: Sie enthält den Gastnamen sowie Check-in und Check-out zur
Fernkontrolle des Displays. Home Assistant kann diese Zustände im Recorder
speichern. Wer diese personenbezogene Historie nicht benötigt, sollte die
Entität in den Recorder-Einstellungen ausschließen.

## Tests

```bash
python3 -m pip install -r requirements-test.txt
pytest
python3 -m compileall custom_components
```

`pytest` misst automatisch die Zeilen- und Branch-Coverage der vollständigen
Python-Integration. Sobald die Gesamtdeckung unter **80 %** fällt, endet der
Testlauf mit einem Fehler. Der aktuelle Bericht wird direkt im Terminal
ausgegeben und zeigt nicht abgedeckte Zeilen an.

Vor dem ersten produktiven Einsatz sollte mit einer Testreservierung geprüft
werden, ob das konkrete Guesty-Konto `keycode`, `wifiName` und `wifiPassword` in
den erwarteten API-Antworten bereitstellt.
