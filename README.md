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
- drei automatische Seiten für Willkommen, Check-out und leeres Zimmer;
- nächste Buchung mit Vorname, Zeitraum und nur tatsächlich vorhandenen
  Guesty-Notizen auf der Seite für das leere Zimmer;
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

1. Die Custom Integration gleicht Guesty standardmäßig alle fünf Minuten ab.
   Neben laufenden und gerade beendeten Aufenthalten lädt sie pro zugeordnetem
   Listing immer mindestens die nächsten fünf bestätigten Reservierungen. Der
   lokale RAM-Snapshot wird nur ersetzt, wenn eine Buchung hinzugekommen,
   geändert oder aus der bestätigten Ergebnismenge verschwunden ist.
   Abgeschlossene Buchungen bleiben noch zwölf Stunden nach Check-out im Cache.
   Wechselt dieselbe Reservierung zeitgesteuert von einem `stay`-Segment zum
   nächsten Listing, wird die alte Kopie jedoch sofort entfernt, damit nie zwei
   Displays denselben Gast übernehmen.
   Fehlt eine bereits bekannte laufende Reservierung nach einer
   Einheitenzuweisung in der gefilterten Suche, verifiziert die Integration
   ausschließlich diese Reservierungs-ID noch einmal über Guestys V3-Endpunkt,
   in Paketen mit maximal zehn IDs. Zukünftige Buchungen verwenden diesen
   Rückfall nicht, damit Stornierungen sofort wirksam bleiben. Zusätzlich gibt
   es pro Lauf einen kontoweiten aktuellen Such-Snapshot, weil Guestys
   Listing-Filter nur das erste `stay`-Segment berücksichtigt. Die Integration
   verwirft daraus lokal alle Reservierungen, die keinem eingerichteten Listing
   eindeutig gehören. Dadurch wird auch ein späteres aktives Segment direkt
   nach einem Home-Assistant-Neustart gefunden.

   Fehler einer einzelnen Listing-Abfrage lassen nur dessen letzten
   erfolgreichen RAM-Snapshot stehen, erzeugen dafür aber keine neue Payload
   und verlängern die 15-minütige Anzeigefrist nicht. Andere Listings laufen
   weiter; schlägt alles fehl, bleibt der vorherige Gesamtstand erhalten.
   Dieser Cache überbrückt damit kurze Guesty- oder Internetstörungen in Home
   Assistant, ist aber bewusst kein dauerhafter Offline-Speicher: Er liegt nur
   im Arbeitsspeicher, geht bei einem Home-Assistant-Neustart verloren und darf
   sensible Displayinhalte ohne erfolgreich erneuerte 15-Minuten-Freigabe nicht
   unbegrenzt sichtbar halten.
   Unvollständige oder formal falsche HTTP-200-Antworten gelten nie als leere,
   autoritative Buchungsliste. Alle API-Anfragen werden pro Client innerhalb von
   Guestys Grenzen von 15 pro Sekunde, 120 pro Minute und 5.000 pro Stunde
   eingereiht; HTTP 429 gibt `Retry-After` sofort an Home Assistant weiter,
   anstatt einen manuellen Aufruf im Hintergrund schlafen zu lassen. Guesty
   zählt diese Grenzen kontoweit über alle API-Tokens, sodass getrennte Clients
   oder Home-Assistant-Instanzen dasselbe Kontingent teilen.
2. `keycode`, `keyCode` und `doorCode` werden zuerst direkt aus der
   Reservierung gelesen. Falls Guesty den Türcode als Custom Field zurückgibt,
   löst die Integration die Field-ID über die Account-Felddefinitionen auf.
   Explizit geleerte Werte in einer aktuellen Reservierungsprojektion haben
   Vorrang vor älteren Direktwerten, Cache-Inhalten und optionalen
   Detailabfragen; auch ein abgelaufener Felddefinitions-Cache wird nach einem
   fehlgeschlagenen Neuabruf nicht weiterverwendet.
3. Jedes E1001 veröffentlicht in Home Assistant eine diagnostische Entität
   namens `GuestyTerminal Endpoint`.
4. In den Optionen der Integration wird diese Entität einem Listing zugeordnet.
   Mehrere Displays dürfen dasselbe Listing verwenden; GuestyTerminal lädt den
   gemeinsamen Buchungssnapshot nur einmal und erzeugt anschließend für jedes
   Display einen eigenen Payload mit dessen Texten, Sprache, Zeitformat,
   Wetterauswahl und Sichtbarkeitseinstellungen. Bei verschiedenen Listings
   bleiben Reservierungen, Zugangsdaten und Notizen strikt getrennt. Bei
   Guesty-Mehrfacheinheiten bleibt diese Zuordnung auch dann stabil, wenn beim
   Check-in zusätzlich zur übergeordneten `unitTypeId` eine konkrete `unitId`
   vergeben wird oder die laufende Suchantwort danach nur noch diese konkrete
   Einheit enthält. Das gilt auch nach einem Neustart von Home Assistant. Eine
   ohne Identitäten für mehrere Listings mehrdeutige Antwort wird nicht an
   mehrere Displays verteilt. Besitzt eine Reservierung mehrere zeitlich
   aufeinanderfolgende `stay`-Segmente, wird mit dem einmal je
   Aktualisierungslauf erfassten Zeitpunkt zuerst das aktive, sonst das nächste
   oder zuletzt abgeschlossene Segment gewählt. Derselbe Zeitpunkt gilt für
   API-Datumsfilter, Normalisierung, Snapshot-Abgleich und alle Payloads.
   Projektionen derselben Reservierung werden nur ergänzend zusammengeführt;
   explizit geleerte sensible Felder bleiben leer.
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

Die Konfiguration wurde vollständig mit ESPHome 2026.8.1 für ESP32-S3 gebaut
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
   die empfohlenen Energieeinstellungen. Das bewährte 4-MB-Flashlayout bleibt
   bis zur realen Gerätebestätigung die sichere Voreinstellung. Das vollständige
   32-MB-Layout nur bewusst für eine vollständige USB-Installation wählen; es
   benötigt derzeit ESPHomes experimentell gekennzeichnete Large-Flash-
   Unterstützung. Ein vorhandenes OTA-Display darf erst bei einer einmaligen
   vollständigen USB-Migration das Layout wechseln.
4. Nach dem Speichern ESPHome Device Builder öffnen. Das neue Gerät erscheint
   dort unmittelbar.
5. **Installieren** wählen. Für die erste Installation das E1001 per USB
   anschließen; spätere Aktualisierungen sind auch OTA möglich.

Der Assistent erzeugt für jedes Gerät einen eigenen API-Schlüssel, ein eigenes
OTA-Passwort und ein eigenes Fallback-AP-Passwort. Eine vorhandene, nicht von
GuestyTerminal verwaltete ESPHome-Datei wird niemals überschrieben. Beim
bewussten Aktualisieren einer vom Assistenten erzeugten Datei bleiben diese
Geräteschlüssel erhalten, damit der OTA-Zugriff nicht verloren geht.
Ein Wechsel des Flashlayouts wird beim Ersetzen einer verwalteten Datei nur
nach ausdrücklicher USB-Migrationsbestätigung zugelassen. Die anschließend
erzeugte Konfiguration muss einmal vollständig per USB installiert werden;
eine OTA-Installation aktualisiert die vorhandene Partitionstabelle nicht
zuverlässig. Normale spätere Firmwareupdates funktionieren wieder OTA.
ESPHome verlangt für OTA auf 32-MB-Flash derzeit ausdrücklich seine erweiterte
ESP-IDF-Unterstützung; der Assistent aktiviert sie ausschließlich im gewählten
32-MB-Profil. Das konservative 4-MB-Profil bleibt davon unberührt.

### Manuell flashen

1. `esphome/secrets.example.yaml` nach `esphome/secrets.yaml` kopieren.
2. Alle Platzhalter durch neue, zufällige Werte ersetzen.
3. In `esphome/guestyterminal-display-1.yaml` Gerätenamen, Anzeigenamen und bei
   Bedarf die Energieeinstellungen anpassen. Für bestehende OTA-Geräte
   `flash_layout: legacy_4mb`, `flash_size: 4MB` und
   `large_flash_experimental: "false"` unverändert lassen. Nur für eine
   vollständige Neu-/USB-Installation gemeinsam auf `expanded_32mb`, `32MB`
   und `"true"` umstellen.
4. Konfiguration installieren:

   ```bash
   esphome run esphome/guestyterminal-display-1.yaml
   ```

Beim Build erscheinen Hinweise zu GPIO 3, 19 und 20. Diese Pins stammen aus
der offiziellen E1001-Hardwarebelegung und sind für dieses Board beabsichtigt.

GuestyTerminal verwendet einen eigenen UC8179-Treiber für die vier nativen
Graustufen des GDEY075T7-Panels. Schriftdateien werden direkt mit 2 Bit pro
Pixel auf die vier Panelstufen gerastert. QR-Code
und Türcode bleiben dabei satt schwarz und werden ohne sichtbare
Umrandung gezeichnet. Im Standardmodus `auto` prüft der Treiber einmalig die
von Seeed dokumentierten UC8179-OTP-Markierungen. Unterstützt die jeweilige
Panelrevision eine interne Vier-Grau-Wellenform, wird diese verwendet;
andernfalls greift der Treiber auf Seeeds MIT-lizenzierte Register-LUTs zurück.
Die erkannte Auswahl bleibt über den Tiefschlaf erhalten, damit der
30-Minuten-Akkuzyklus nicht durch eine erneute Modusprüfung bei jedem Aufwachen
belastet wird. Der sichtbare schmale Panelrand liegt außerhalb des
800×480-Bildspeichers und besitzt eine eigene Elektrode. Normale OTP- und
Register-LUT-Vollrefreshs lassen diese Elektrode über das dokumentierte
`R50h.BDZ=1` hochohmig, damit die für Text und Bild gewählte Pixelwellenform den
Rand nicht erneut verfärbt. Auch Teilrefreshs behalten diesen Zustand bei. Eine
begrenzte Randkorrektur auf bestätigter externer Versorgung bildet einmalig den
monochromen UC8179-OTP-Ablauf des früher verwendeten ESPHome-Modells
`7.50inv2` anhand des Controllerdatenblatts nach. Sie überträgt eine
Schwarz-Weiß-Quantisierung ausschließlich in die neue DTM2-Ebene und zeichnet
den unveränderten Vier-Grau-Framebuffer anschließend mit der gewählten
Pixelwellenform sowie hochohmigem Rand neu. Der aktuelle Graustufentreiber
bleibt damit vollständig erhalten. Ein spätes `R50h` vor `POWER OFF` entfällt;
der Ausschaltbefehl selbst schaltet laut Datenblatt alle Panel-Ausgänge
hochohmig. Der zuvor ergänzte Laufzeitpfad, der
42 OTP-Bytes nach `R25h/LUTBD` kopierte, wurde entfernt: Das reale Gerät blieb
damit nach dem sichtbaren Bildaufbau in `BUSY_N` hängen. Die OTP-Prüfung liest
nur noch die Checkcodes und Graustufen-Markierungen wiederholt; Rohdaten der
Panel-Wellenformen werden weder übernommen, protokolliert noch in der Firmware
gebündelt.
Für den bidirektionalen OTP-Lesevorgang gibt der Treiber den dedizierten
SPI2-Bus vollständig frei und initialisiert Bus und SPI-Gerät danach mit der
E1001-Konfiguration neu. Nach `POWER ON` und `DISPLAY REFRESH` wartet er gemäß
der Seeed-Sequenz zunächst fest 100 ms und anschließend bis `BUSY_N` inaktiv
ist; eine bereits vor der ersten Abfrage erfolgte BUSY-Flanke muss nicht noch
einmal beobachtet werden. Reset, Einschalten, Refresh und Ausschalten besitzen
getrennte Sicherheitsgrenzen. Meldet eine als kompatibel erkannte interne
OTP-Wellenform den sichtbaren Bildaufbau nicht als abgeschlossen, setzt der
automatische Modus den Controller einmal zurück und wiederholt dasselbe Bild
mit den lizenzierten Seeed-Register-LUTs. Erst ein erfolgreicher Rückfall wird
über den Tiefschlaf hinweg behalten. Die Diagnose protokolliert dabei nur
BUSY-Pegel, Phase und Dauer, niemals Displayinhalte.
Der logische ESPHome-Framebuffer verwendet
`00 = Schwarz`, `01 = Dunkelgrau`, `10 = Hellgrau` und `11 = Weiß`. Vor der
Übertragung invertiert der Treiber jeden Pegel mit `3 - gray`; erst danach
werden nieder- und höherwertiges Bit getrennt an UC8179-DTM1 und DTM2 gesendet.
Die Standard-Tonkurve `gray_gamma: "1.35"` verteilt Zwischenwerte mit einem
festen 4×4-Muster auf zwei benachbarte native Stufen. Dadurch erscheinen die
beiden mittleren Graubereiche heller, während Papierweiß und sattes Schwarz
pixelgenau erhalten bleiben. Wer die frühere dunklere Abstufung benötigt, kann
in den `substitutions` `gray_gamma: "1.0"` setzen. Diese Einstellung verändert
nur die Pixel-Tonkurve, nicht die Wellenform oder die separate Randkorrektur.
Die Firmware erkennt einen geänderten Wert und erzwingt genau einen neuen
Vollaufbau; danach werden identische Bilder wieder normal unterdrückt.
Quellen, feste Revisionen und Lizenztexte sind in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) dokumentiert.

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
4. Zuerst das reTerminal und danach dessen Displaysprache auswählen. Für neue
   Zuordnungen wird Deutsch, Englisch, Französisch oder Spanisch passend zur
   Home-Assistant-Systemsprache vorausgewählt.
5. Anschließend werden das gespeicherte Listing, alle Texte und der
   Anzeigezeitraum geladen. Bleibt die Sprache unverändert, bleiben eigene
   Texte erhalten. Ein bewusster Sprachwechsel setzt die Textfelder auf die
   Vorlagen der neuen Sprache zurück, bevor sie individuell bearbeitet werden.
6. Neben Überschrift und Begrüßung lassen sich die Beschriftungen für Türcode,
   WiFi, Name, Passwort und Check-out pro Display frei bearbeiten. Die
   Checkout- und Leerzimmer-Seiten besitzen jeweils eine eigene
   Konfigurationsseite.
7. Optional eine Home-Assistant-`weather`-Entität für Wettersymbol und
   Außentemperatur auswählen.
8. Für jedes weitere Display wiederholen.

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

Ein physisches Display kann immer nur einem Guesty-Konto gleichzeitig gehören.
Die Konfiguration blendet bereits anderweitig zugeordnete Endpunkte aus. Auch
alte doppelte Zuordnungen werden beim Laden blockiert; das Entfernen einer
solchen Alt-Zuordnung darf das vom anderen Konto verwaltete Display nicht
leeren.

Verfügbare Platzhalter für Begrüßungen:

- `{first_name}`
- `{property_name}`
- `{check_in}`
- `{check_out}`

Der Standardtitel lautet `Willkommen, {first_name}!`.

## Checkout-Seite konfigurieren

Für jedes bereits zugeordnete Display gibt es unter **Konfigurieren →
Checkout-Seite konfigurieren** eine eigene Seite. Sprache sowie EU-/US-Datums-
und Zeitformat werden automatisch aus der Display-Zuordnung übernommen. Die
Startzeit ist standardmäßig `05:00` am lokalen Checkout-Tag und kann pro
Display geändert werden.

Überschrift, Abschiedsnachricht, Überschrift der Anweisungen und ein Ersatztext
für Listings ohne Anweisungen sind frei editierbar und werden dauerhaft pro
Display gespeichert. Zusätzlich zu den Begrüßungsvariablen stehen
`{check_out_date}` und `{check_out_time}` zur Verfügung. Bei einem bewussten
Wechsel der Displaysprache werden auch diese Checkout-Texte mit den passenden
deutschen, englischen, französischen oder spanischen Vorlagen neu befüllt.

Die eigentlichen Checkout-Anweisungen liest GuestyTerminal aus dem vollständigen
Guesty-Listing. Der Checkout-Modus zeigt weder Türcode noch WiFi-Daten. Wetter
und globales Logo bleiben sichtbar. Nach Ablauf der konfigurierten
Nachlaufzeit erscheint die Seite für das leere Zimmer.

## Seite für ein leeres Zimmer konfigurieren

Die dritte Seite wird unter **Konfigurieren → Seite für leeres Zimmer
konfigurieren** pro Display eingestellt. Sie übernimmt automatisch die bereits
gewählte Displaysprache sowie das EU-/US-Datums- und Zeitformat. Überschrift,
Text für den Fall ohne weitere Buchung und die drei Notizüberschriften sind
frei editierbar und bleiben beim erneuten Öffnen gespeichert. Ein bewusster
Wechsel der Displaysprache setzt auch diese Texte auf die deutschen,
englischen, französischen oder spanischen Vorlagen zurück.

Wenn eine nächste bestätigte Buchung existiert, zeigt die Seite deren Vornamen
und Zeitraum. Aus Guesty werden ausschließlich **General notes**, **Notes for
cleaner** und **Special requests** übernommen. Leere Notizarten erzeugen kein
Feld: Eine vorhandene Notiz nutzt die gesamte Breite, zwei Notizen werden in
zwei gleich große Felder und drei Notizen in drei gleich große Felder verteilt.
Ohne Notizen stehen Buchungsname und Zeitraum großzügig und vertikal
ausgewogen. Die Seite hat keine Fußleiste und zeigt weder Türcode noch WiFi.
Oben rechts ersetzt eine kompakte Batterieanzeige das Wetter-Widget. Der
Prozentwert steht links neben einem waagerechten, 24 Pixel großen
Füllstandssymbol aus der eingebundenen Material-Design-Piktogrammfamilie; beide
sind an der Kopfzeile ausgerichtet. Der Messwert wird in stromsparenden
Fünf-Prozent-Schritten über das kleine partielle Headerfenster aktualisiert; das
Symbol folgt ihm in Zehn-Prozent-Stufen.

## Anzeige- und Sicherheitsverhalten

- Der Gastbildschirm erscheint standardmäßig eine Stunde vor Check-in.
- Am Checkout-Tag wechselt er ab der pro Display eingestellten Startzeit
  standardmäßig um 05:00 Uhr auf die eigene Checkout-Seite.
- 30 Minuten nach Check-out erscheint die Seite für das leere Zimmer mit der
  nächsten bestätigten Buchung. Existiert keine, erscheint der konfigurierbare
  Ersatztext.
- Maßgeblich ist ausschließlich der Guesty-Reservierungsstatus `confirmed`.
  Zahlungsstatus, Zahlungseingang und Auszahlung durch Airbnb oder andere
  Buchungsportale werden bewusst nicht ausgewertet.
- Home Assistant fragt Guesty standardmäßig alle fünf Minuten ab und hält pro
  zugeordnetem Listing die fünf nächsten bestätigten Buchungen im RAM. Neue,
  geänderte und stornierte Buchungen werden durch einen vollständigen
  Snapshot-Abgleich erkannt. Ist der normalisierte Snapshot identisch, bleibt
  der Buchungscache unverändert und das E-Paper wird nicht neu gezeichnet. Die
  separat übertragene 15-Minuten-Freigabe kann aus Datenschutzgründen trotzdem
  erneuert werden; sie verändert den sichtbaren Inhaltsfingerabdruck nicht.
  Abgeschlossene Buchungen werden erst zwölf Stunden nach Check-out aus diesem
  RAM-Cache entfernt; die sichtbare Nachlaufzeit des Displays bleibt davon
  unabhängig standardmäßig bei 30 Minuten.
- Im empfohlenen Modus **Automatisch** erkennt die Firmware beide offiziellen
  E1001-Hardwarestände selbst. Auf v1.2 identifiziert sie zuerst den SY6974B und
  verlangt drei konsistente Messungen seines dedizierten `REG0A.BUS_GD`-Signals.
  USB-Hosts, CDP-/DCP-Netzteile sowie unbekannte und nicht standardisierte
  Adapter werden dadurch unabhängig von der Ladequellenklassifizierung erkannt.
  Auf v1.0 besitzt der ETA6003 kein auslesbares USB-Statusregister. Dort prüft
  die Firmware stattdessen den ausschließlich von `TYPEC_5V` versorgten
  USB-UART-Baustein. Sie unterbindet vor der Messung eine mögliche
  Rückspeisung vom ESP32, hält die Leitung definiert und verlangt drei
  übereinstimmende Messfenster. Sobald ein SY6974B erkannt wurde, bleibt dessen
  Signal maßgeblich; ein vorübergehender I²C-Fehler darf dann nicht auf die
  ältere Methode umschalten. Auf Akku schläft das Gerät standardmäßig 30
  Minuten und bleibt nach dem Aufwachen höchstens 90 Sekunden aktiv. Sobald
  Home Assistant aktuelle Daten geliefert hat, schläft es früher wieder ein.
- Bei angeschlossenem USB-Strom bleibt das Gerät online. Wird der Strom später
  getrennt, wechselt es nach spätestens zwei aufeinanderfolgenden
  15-Sekunden-Tests in den Akkubetrieb; eine einzelne unauflösbare Messgruppe
  kann ein zuvor bestätigt über USB versorgtes Gerät dadurch nicht schlafen
  schicken.
  Im Akkubetrieb schläft es für das konfigurierte Intervall – standardmäßig 30
  Minuten – vollständig. Wird währenddessen USB angeschlossen, erkennt das
  Gerät dies beim nächsten regulären Aufwachen und bleibt danach online.
- Die grüne Taste kann das Gerät zusätzlich aus dem Deep Sleep wecken. Ohne
  USB-Verbindung führt dieser Tasten-Wakeup genau wie der regelmäßige Zyklus
  einen kurzen Abgleich aus und kehrt danach in den Deep Sleep zurück. Während
  das Gerät bereits wach ist, ändert die Taste weder Betriebsmodus noch
  Wachzeit. Ein beim Einschlafen noch gehaltener Taster kann keine Schleife aus
  Deep Sleep und sofortigem Wiederaufwachen erzeugen.
- GPIO-Status-LED und Buzzer bleiben auf beiden Hardwareständen deaktiviert.
  Die Mikrofon-Stromversorgung bleibt beim Start und im Akkubetrieb ebenfalls
  aus. Erst nach bestätigter externer Versorgung wird sie eingeschaltet; das
  E1001 berechnet dann lokal alle 30 Sekunden einen relativen RMS-Schallpegel
  aus dem jeweils unmittelbar vorhergehenden vollständigen 30-Sekunden-Fenster.
  Beim Abziehen des Kabels werden Aufnahme und Versorgung wieder
  gestoppt. Auf v1.2 schaltet die Firmware zusätzlich den Lade-LED-Ausgang des
  SY6974B ab. Der ETA6003 von v1.0 bietet dafür keinen entsprechenden
  Software-Schalter; dort kann die rote, hardwaregesteuerte Lade-LED während
  des Ladens sichtbar bleiben. Auch auf v1.2 kann sie nach einem vollständig
  stromlosen Neustart bis zum Firmwarestart kurz aufleuchten.
- Die ungenutzte SD-Karten-Stromversorgung wird über GPIO16 beim Start und vor
  jedem Deep Sleep ausdrücklich ausgeschaltet. Der interne Pulldown des
  Lastschalters ist dadurch nicht die einzige Absicherung gegen unnötigen
  Ruhestrom.
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
- Die normale Home-Assistant-Geräteseite zeigt nur die im Alltag sinnvollen
  Werte und Bedienelemente: geschätzter **Batteriestand**, **Battery charging
  status**, **External power**, Temperatur, relative Luftfeuchte, **Angezeigte
  Buchung**, **Display
  aktualisieren**, **E-paper Hardwaretest** und **Neustart** sowie die drei
  physischen Tasten **Green button**, **Middle button** und **Left button** als
  Binärsensoren. Bei bestätigter externer Versorgung steht zusätzlich
  **Relativer Schallpegel (30 Sekunden)** zur Verfügung. Der für die Integration
  benötigte **GuestyTerminal Endpoint** bleibt als Diagnose-Entität sichtbar.
  Der Aktualisieren-Button stößt zuerst einen sofortigen Guesty-Abgleich an,
  übernimmt den danach ermittelten Seitenmodus und zeichnet anschließend genau
  dieses aktuelle Bild neu. Im Deep Sleep sind diese Bedienelemente bis zum
  nächsten Aufwachen nicht erreichbar. Der Batteriestand wird bei jedem
  Aufwachen und bei USB-Betrieb alle fünf Minuten aus 16 gemittelten
  Spannungsmessungen neu geschätzt. Die Prozentanzeige basiert nicht auf einem
  Coulomb-Counter, sondern auf einer stückweisen Li-Ion-Spannungskennlinie und
  kann deshalb unter Last schwanken. Auf E1001 v1.2 ergänzt der identifizierte
  SY6974B diese Schätzung um Vorladen, Schnellladen, Ladeabschluss und neutrale
  Fehlerklassen. Nur ein zusammen mit externer Versorgung bestätigter
  Ladeabschluss setzt den effektiven Wert auf 100 %. E1001 v1.0 melden diesen
  digitalen Ladestatus als nicht unterstützt.
- Erweiterte Hardwarediagnosen bleiben vollständig in der Firmware erhalten,
  werden standardmäßig aber nicht an Home Assistant veröffentlicht. Dazu
  gehören Batteriespannung, Wach-/Resetgrund, Wachzeit, Stromerkennungsmethode,
  Flashlayout, Zustell- und E-Paper-Phasen, Wellenform/Randmodus,
  Hardwaretest-Ergebnis sowie Randkorrektur. Für eine zeitlich begrenzte
  Fehlersuche kann in den YAML-`substitutions`
  `advanced_diagnostics_internal: "false"` gesetzt und die Firmware erneut
  installiert werden. Mit `"true"` oder ohne eigene Angabe gilt wieder die
  aufgeräumte Alltagsansicht.
- Die erweiterte Diagnose **Display delivery status** unterscheidet Annahme,
  Rendern, bestätigten
  Erfolg, ein nachweislich unverändertes Bild und begrenzte Fehlerzustände.
  **E-paper phase**, **E-paper error**, **E-paper waveform** und
  **E-paper border mode** zeigen neutral, in welcher Controllerphase ein
  Vollrefresh steht und ob die Randelektrode gerade einmalig über den
  monochromen OTP-Pfad konditioniert oder für den normalen Bildaufbau
  hochohmig ist. Diese Entitäten enthalten keine Gast-, Türcode- oder
  WLAN-Daten.
- Die erweiterte Diagnose **E-paper Randkorrektur** wiederholt die begrenzte Zwei-Pass-Korrektur nur bei
  bestätigter externer Versorgung. **E-paper border recovery** meldet
  `success`, `failed`, `hardware_timeout`, `busy` oder
  `requires_external_power`. Der sichtbare Payload und seine gespeicherten
  Inhaltsnachweise bleiben dabei unverändert.
- **E-paper Hardwaretest** führt den Test nur bei bestätigter externer
  Versorgung aus. Er zeigt kurz ein neutrales Vier-Grau-Testbild, verändert danach
  ausschließlich das 136×64-Pixel-Statusfenster per Teilrefresh und stellt die
  vorherige Displayseite wieder her. **E-paper self-test** meldet `success`,
  `full_failed`, `partial_failed`, `restore_failed`, `hardware_timeout`, `busy`
  oder `requires_external_power`. Ein abgebrochener Test entwertet den
  gespeicherten Bildnachweis, damit der nächste Guesty-Payload sicher neu
  gezeichnet wird.
- **Flash layout** zeigt `legacy_4mb` oder `expanded_32mb`. Dieser Wert
  beschreibt die kompilierte Konfiguration; ein Wechsel auf 32 MB ist erst nach
  einer vollständigen USB-Installation physisch wirksam.
- Für die Akkudiagnose sollte **Wake-up reason** beim regulären Zyklus `timer`
  melden. **Awake duration** zeigt die Dauer des letzten Wachfensters vor dem
  Schlafen; bei schneller Home-Assistant-Zustellung liegt sie deutlich unter
  dem konfigurierten Maximum von standardmäßig 90 Sekunden. Wiederholte
  `button`-Wakeups oder häufig ausgeschöpfte Wachfenster erklären einen hohen
  Verbrauch und lassen sich mit diesen beiden Entitäten im Verlauf erkennen.
- **External power** zeigt das erkannte Versorgungsergebnis. Die zusätzliche
  Diagnose-Entität **Power detection method** nennt dazu `SY6974B BUS_GD` auf
  v1.2, `USB-UART` beim revisionskompatiblen Rückfall oder `Unavailable`, wenn
  eine Messgruppe nicht eindeutig war. Ein zuvor bestätigtes Kabel übersteht
  einmalig `Unavailable`; nach zwei solchen Gruppen verwendet die Firmware
  sicherheitshalber das Akkuverhalten.
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
Manuell gestartete Aktionen melden einen Guesty-Fehler beziehungsweise einen
vollständigen Zustellfehler sichtbar in Home Assistant, statt still erfolgreich
zu erscheinen. Schlafende Displays bleiben beim regulären Hintergrundabgleich
weiterhin ein erwarteter Zustand.

Aktuelle Displays verwenden dafür die bestätigte Aktionsschnittstelle v10:
Home Assistant betrachtet eine Aktualisierung erst nach der physischen
Erfolgsmeldung des E-Paper-Treibers als abgeschlossen. Empfang, Renderphase und
Endergebnis werden mit einer zufälligen, nicht auf Buchungsdaten rückführbaren
Kennung korreliert. Reconnects während eines langen Vollrefreshs starten keinen
zweiten parallelen Rendererauftrag; ausbleibende Bestätigungen werden innerhalb
fester Grenzen erneut versucht.

Die Konfigurationsentität **Alle Display-Firmwares aktualisieren** hebt zuerst
alle durch den Firmware-Assistenten erzeugten YAML-Dateien auf die aktuelle
GuestyTerminal-Version. Danach übergibt sie sämtliche Konfigurationen als einen
OTA-Sammelauftrag an den ESPHome Device Builder. Gerätespezifische WiFi-, API-,
OTA- und Fallback-Zugangsdaten bleiben unverändert. Fremde ESPHome-Dateien
werden weder verändert noch installiert.
Das Sammelupdate ändert absichtlich kein Flashlayout. Eine Umstellung von 4 MB
auf 32 MB wird ausschließlich über den Firmware-Assistenten vorbereitet und
einmal vollständig per USB installiert.

Am Strom angeschlossene Displays werden nach dem Build direkt aktualisiert.
Für schlafende Akku-Displays merkt der Device Builder den Auftrag vor und
installiert ihn beim nächsten Aufwachen. Während des eigentlichen Flashens darf
das Gerät nicht ausgeschaltet werden. Fortschritt und mögliche Fehler sind im
ESPHome Device Builder sichtbar.

Die kompakte, fortlaufende Änderungshistorie steht in
[`CHANGELOG.md`](CHANGELOG.md). Die folgenden Hinweise erklären zusätzlich die
Firmwareanforderungen älterer Installationen.

Version **0.3.50** korrigiert zusätzlich den Boot-Lebenszyklus des in 0.3.48
hinzugefügten Schallpegelsensors. Die frühe Netzstromerkennung darf die
I²S-Aufnahme nicht mehr starten, bevor der passive Schallpegel-Sensor seinen
Daten-Callback registriert hat. Der erste Start erfolgt deshalb erst nach dem
vollständigen Komponenten-Setup. Falls der I²S-Task nicht läuft, folgen pro
Kabelverbindung höchstens zwei kontrollierte Wiederholungen im bestehenden
15-Sekunden-Hardwarezyklus. Neutrale Logmeldungen machen Start, laufenden Task
und ersten gültigen Messwert nachvollziehbar, ohne Samples oder Audioinhalte zu
protokollieren.

Version **0.3.49** korrigierte zuvor den in 0.3.48 hinzugefügten
Schallpegelsensor.
Seeeds funktionierendes E1001-Mikrofonbeispiel empfängt den Mono-PDM-Datenstrom
über den linken Slot; GuestyTerminal hatte ESPHomes abweichenden rechten
Standard-Slot unbeabsichtigt übernommen. Die Firmware setzt deshalb nun
ausdrücklich `channel: left`, wartet nach dem Einschalten auf den tatsächlich
laufenden I²S-Task und prüft nach einem vollständigen Messfenster, ob ein
endlicher RMS-Wert vorliegt. Die Firmware veröffentlicht nun lückenlos alle
30 Sekunden den relativen RMS-Durchschnitt der unmittelbar vorhergehenden
30 Sekunden.

Mit `advanced_diagnostics_internal: "false"` zeigt die zusätzliche neutrale
Entität **Microphone status**, ob die Aufnahme startet, läuft, ihr Start
fehlschlägt oder nach 30 Sekunden noch kein gültiger Messwert vorliegt. Die
Prüfung erhält zehn Sekunden Sicherheitsmarge und meldet den Fehler daher nach
40 Sekunden. Bei jedem neuen Kabelzyklus wird der vorherige RMS-Zustand
verworfen, damit nur ein vollständig neues Fenster als erfolgreicher Start
gilt. Die Diagnose enthält keine Samples oder Audioinformationen und bleibt im
normalen Alltagsprofil intern. Die Mikrofonversorgung ist weiterhin
ausschließlich bei bestätigter externer Versorgung aktiv.

Der Sensor heißt ab 0.3.49 **Relativer Schallpegel (30 Sekunden)**. Da ESPHome
den Entity-Schlüssel aus dem Namen ableitet, kann Home Assistant den alten
1-Minuten-Eintrag einmalig als nicht verfügbar weiterführen. Nach erfolgreichem
Firmwareupdate und sobald der neue Sensor Werte liefert, kann der alte Eintrag
aus der Entity Registry entfernt werden.

Version 0.3.50 benötigt ein gemeinsames HACS-/Integrations- und
Display-Firmwareupdate. Bestehende 4-MB-Geräte können sie normal per OTA
installieren; Flashlayout, E-Paper-Renderer und sichtbarer Bildinhalt ändern
sich nicht. 302 Tests gegen Home Assistant 2025.12.0 und 2026.2.3 bestehen bei
90,72 % Branch-Abdeckung. ESPHome 2026.8.1 kompiliert das sichere 4-MB-Profil
mit 16 % und das experimentelle 32-MB-Profil mit 91 % freier App-Partition.
Die vollständige Mikrofonmatrix auf einem realen E1001 ist vor dem Release
noch nicht abgeschlossen und wird deshalb als nicht hardwaregetestet
ausgewiesen.

Version **0.3.48** kombiniert beim E1001 v1.2 die vorhandene
Batteriespannungsschätzung mit dem digitalen Ladestatus des eindeutig
identifizierten SY6974B. Drei gleiche `REG08`-/`REG09`-Messungen bestätigen
Vorladen, Schnellladen, Ladeabschluss oder einen neutralen Fehlerzustand. Nur
`complete` zusammen mit `REG0A.BUS_GD` ergibt 100 %; ein Zielwert aus dem
Laderegister wird nie als gemessene Kapazität behandelt. Auf dem leeren
Buchungsbildschirm kennzeichnet ein Blitz im Batteriesymbol den aktiven
Ladevorgang. Die Anzeige bleibt auf fünf Prozent quantisiert und kann
Ladezustandsänderungen weiterhin mit einem kleinen Teilrefresh darstellen.
E1001 v1.0 verwenden unverändert die ADC-Kennlinie und melden den digitalen
Ladestatus als nicht unterstützt.

Die Version veröffentlicht außerdem bei bestätigter externer Versorgung den
lokal berechneten relativen 60-Sekunden-RMS-Schallpegel. Rohsamples und Audio
verlassen das Gerät nicht; auf Akku bleiben Mikrofon und Aufnahme ausgeschaltet.
Der E-Paper-Hardwaretest und alle drei physischen Tastensensoren sind wieder in
der Alltagsansicht sichtbar. Renderrevision 33 fordert wegen des neuen
Ladesymbols genau einen vollständigen Neuaufbau an.

Version 0.3.48 benötigt ein gemeinsames HACS-/Integrations- und
Display-Firmwareupdate. Bestehende 4-MB-Geräte können normal per OTA
aktualisiert werden; das Flashlayout bleibt unverändert. Die Ladestatuslogik,
das Ladesymbol und der Schallpegelsensor sind noch nicht auf einem realen E1001
geprüft und werden deshalb als nicht hardwaregetestet veröffentlicht.
Die vollständige Suite besteht aus 302 bestandenen Tests bei 90,72 %
Abdeckung; die Freigabe prüft Home Assistant 2025.12.0 und 2026.2.3. Beide
ESPHome-2026.8.1-Profile kompilieren, mit 16 % freier App-Partition im sicheren
4-MB-Profil und 91 % im experimentellen 32-MB-Profil.

Version **0.3.47** hellt mit Renderrevision 32 die beiden mittleren
Graubereiche über eine feste 4×4-Matrix und die neue Standard-Tonkurve
`gray_gamma: "1.35"` auf. Reines Weiß, schwarzer Text, Türcode und QR-Code
bleiben unverändert. Eine lokale Gamma-Änderung erzwingt genau einen
Vollaufbau. Der erfolgreiche Rand-Vorlauf wird erstmals getrennt von normalen
Rendererrevisionen gespeichert; beim Upgrade von 0.3.46 kann er einmalig
wiederholt werden, spätere Layout- oder Tonkurvenänderungen starten ihn nicht
erneut. Die normale Home-Assistant-Geräteseite zeigt standardmäßig nur noch
die für den Alltag sinnvollen Werte und Bedienelemente, während die vollständige
Hardwarediagnose intern erhalten bleibt und bei Bedarf eingeblendet werden
kann.

Version 0.3.47 benötigt ein gemeinsames HACS-/Integrations- und
Display-Firmwareupdate. Bestehende 4-MB-Geräte können normal per OTA
aktualisiert werden; das Flashlayout wird nicht geändert. 293 Tests gegen Home
Assistant 2025.12.0 und 2026.2.3, 90,72 % Branch-Abdeckung, alle statischen
Prüfungen und beide ESPHome-2026.8.1-Firmwareprofile sind erfolgreich. Die in
0.3.46 eingeführte Randkorrektur wurde am realen E1001 bestätigt; die neue
Gamma-Tonkurve und die vollständige Hardwarematrix von 0.3.47 sind noch nicht
am realen Gerät geprüft.

Version **0.3.46** ersetzt ausschließlich den erfolglosen Rand-Vorlauf aus
0.3.45: Statt der Custom-Graustufen-LUT bildet sie den
monochromen UC8179-Registerablauf des früher randfreien ESPHome-Modells
`7.50inv2` nach. Der aktuelle Vier-Graustufen-Treiber, Renderer, Datenweg und
die Inhaltsunterdrückung bleiben unverändert. Renderrevision 31 fordert diesen
zweistufigen Hardwaretest bei bestätigter externer Versorgung einmalig an. Die
zweite unmittelbar folgende Aktualisierung ist dabei der absichtliche Aufbau
des endgültigen Graustufenbildes; spätere identische Payloads lösen weiterhin
keinen physischen Refresh aus. Der Realgerätetest am 26. August 2026 bestätigt,
dass dieser Ablauf den zuvor dunklen/grauen Außenrand vollständig entfernt,
ohne den schwarzen Text oder das Vier-Grau-Bild aufzuhellen. Für diese
Korrektur sind ein HACS-/Integrationsupdate und die Display-Firmware 0.3.46
erforderlich.
Bestehende 4-MB-Geräte können sie normal per OTA installieren; das Flashlayout
bleibt unverändert. 291 Tests, beide ESPHome-2026.8.1-Flashprofile und die
statischen Freigabeprüfungen sind erfolgreich.

Version **0.3.45** trennt den sichtbaren Panelrand von der Wellenform für Text
und Bild. Normale Voll- und Teilrefreshs lassen die eigene Randelektrode
hochohmig. Beim ersten Bild mit Renderrevision 30 führt ein sicher am Strom
erkanntes Display genau eine begrenzte Randkonditionierung mit Seeeds bereits
lizenziertem Custom-`LUTKW` aus und baut unmittelbar danach denselben
Framebuffer mit der ausgewählten `auto`-/OTP- oder Custom-Pixelwellenform neu
auf. Dadurch kann die Randbehandlung den guten schwarzen Textkontrast nicht
mehr mit aufhellen oder ein späterer Refresh den Rand wieder abdunkeln. Die
Diagnose **E-paper Randkorrektur** erlaubt den gleichen Ablauf ausschließlich
bei bestätigter externer Versorgung kontrolliert zu wiederholen.
Für diese Korrektur sind ein HACS-/Integrationsupdate und die Display-Firmware
0.3.45 erforderlich. Bestehende 4-MB-Geräte können sie normal per OTA
installieren; das Flashlayout bleibt unverändert. 291 Tests, beide
ESPHome-2026.8.1-Flashprofile und die statischen Freigabeprüfungen sind
erfolgreich. Die sichtbare Randwirkung und die vollständige Hardwarematrix
müssen nach der Installation auf dem realen E1001 noch bestätigt werden.

Version **0.3.44** wertet das reale 0.3.43-Protokoll
aus: Der korrekte, unveränderte Willkommens-Framebuffer wurde nicht wegen eines
Zeitintervalls wiederholt, sondern weil der zusätzliche `R25/LUTBD`-Randpfad
mit dem anschließenden `BUSY_N`-Stillstand korrelierte und jede Zustellung als
`panel_error` endete. Der Treiber behält Seeeds
`R50h=0x10,0x07`-Auswahl, ergänzt aber erstmals den datenblattdefinierten
fließenden Rand-Endzustand `R52h.BDEND=11`. Renderrevision 29 baut das Bild
einmal neu auf, und Runtime plus Firmware unterdrücken identische
Wiederholungen nach einem bestätigten Hardwarefehler. Der flüchtige
WLAN-QR-Wert wird außerdem direkt nach dem Framebuffer-Aufbau neutralisiert,
damit ESPHome ihn nicht in einer späteren Konfigurationsausgabe protokolliert.
Die dazugehörige MIT-lizenzierte QR-Bibliothek ist auf ihren inhaltlich mit
PlatformIO 1.7.0 identischen GitHub-Quellcommit festgeschrieben, sodass eine
vorübergehend nicht erreichbare PlatformIO-Registry den Firmwarebau nicht
blockiert.
Die genaue Diagnose steht in
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).
Für diese Korrektur sind ein HACS-/Integrationsupdate und die Display-Firmware
0.3.44 erforderlich. Bestehende 4-MB-Geräte können sie normal per OTA
installieren; das Flashlayout bleibt unverändert. Die Softwarepfade und beide
Firmwareprofile sind vollständig geprüft, die Randwirkung muss jedoch noch auf
dem realen E1001 bestätigt werden.

Version **0.3.43** behebt den im Gerätelog sichtbaren Stillstand zwischen der
v10-Bestätigung `received` und dem noch ausbleibenden `rendering`: Der
WLAN-QR-Code wird nur noch einmal im eigentlichen Renderer erzeugt, und der
ESPHome-Hauptprozess besitzt dafür 16 KiB Stackreserve. Physische
Displayzustellungen laufen in Home Assistant als verwaltete
Hintergrundaufgaben und können dessen Start nicht mehr bis zur langen
E-Paper-Abschlussfrist blockieren. Die Reservierungsauswahl, der lokale
Fünf-Buchungen-RAM-Snapshot und die Zuordnung mehrerer Displays bleiben
unverändert. Für die Korrektur sind ein HACS-/Integrationsupdate und die
Display-Firmware 0.3.43 erforderlich. Bestehende 4-MB-Geräte können normal per
OTA aktualisiert werden; das Flashlayout ändert sich nicht. Die Firmware wurde
mit ESPHome 2026.8.1 für beide Profile kompiliert, aber noch nicht vollständig
auf einem realen E1001 geprüft. Das physisch festgehaltene Testbild verschwindet
erst beim ersten erfolgreichen Vollrefresh. Nach der Veröffentlichung wurde
die korrekte Synchronisierung des Willkommensbilds auf dem betroffenen realen
Gerät bestätigt; Ursache und Gegenmaßnahmen sind in
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) festgehalten. Die vollständige
Hardwarematrix bleibt weiterhin offen.

Version **0.3.42** korrigiert zusätzlich den auf dem realen E1001 beobachteten
`BUSY_N`-Fehler nach einem tatsächlich sichtbaren Hardwaretestbild. Sie
vervollständigt die Seeed-OTP-Initialisierung, begrenzt die einzelnen
Controllerphasen getrennt und verwendet im automatischen Modus genau einen
kontrollierten Register-LUT-Rückfall. Selbsttest und normale Zustellung warten
bis zum Ende dieses Hardwareauftrags und versuchen anschließend wieder das
aktuelle Buchungsbild. Renderrevision 28 erzwingt dafür einmalig einen
Vollrefresh; die Datenschutz-Lease bleibt bei 15 Minuten. Für diese Korrektur
sind das HACS-/Integrationsupdate und die Display-Firmware 0.3.42 erforderlich.
Bestehende 4-MB-Geräte können sie normal per OTA installieren; das Flashlayout
bleibt unverändert. Die vollständige Wirkung ist noch auf dem realen E1001 zu
bestätigen.

Version **0.3.41** korrigiert die Übergabe an die
mit Home Assistant 2026.8 eingeführten antwortenden ESPHome-Aktionen. v10 ist
jetzt wieder eine schnelle Fire-and-forget-Aktion; Empfang, Renderbeginn und
physischer Abschluss werden weiterhin separat über den Display-Endpunkt
bestätigt. Dadurch kann die E-Paper-Transaktion
nicht mehr in die kürzere Aktionsantwortfrist laufen. Übergabefehler werden
blockierend innerhalb der datenschutzneutralen Integration behandelt, damit
Home Assistant nicht den vollständigen Service-Payload protokolliert. Für die
Korrektur sind sowohl das HACS-/Integrationsupdate als auch die
Display-Firmware 0.3.41 erforderlich. Der erste zugestellte
Willkommens-Payload erzwingt einen Vollrefresh; Rand und Randelektrodendiagnose
sind danach am realen E1001 erneut zu prüfen.

Version **0.3.40** ergänzt die ausdrückliche Abschaltung der ungenutzten
SD-Karten-Stromversorgung, einen neutralen Voll-/Teilrefresh-Hardwaretest und
die kontrollierte Wahl zwischen dem bisherigen 4-MB- und dem vollständigen
32-MB-Flashlayout des E1001. Bestehende OTA-Geräte wechseln nicht automatisch
das Layout. Für eine Umstellung ist im Firmware-Assistenten die USB-Migration
zu bestätigen und die erzeugte Konfiguration einmal vollständig per USB zu
installieren. Ein Display-Firmwareupdate auf 0.3.40 ist für SD-Abschaltung,
Hardwaretest und Layoutdiagnose erforderlich; die reale Panelwirkung und eine
32-MB-Migration sind noch am Gerät zu bestätigen. Beide Profile wurden mit
ESPHome 2026.8.1 vollständig kompiliert; das sichere 4-MB-Profil belegt 82,3 %
seiner App-Partition, das optionale 32-MB-Profil 9,1 %. Die CI baut beide
Profile künftig parallel und kontrolliert für jedes das eigene Speicherlimit.

Das Design mit den zwei grauen Zugangsfeldern wird auf dem E1001 gerendert und
benötigt Firmware **0.3.11** oder neuer. Die MDI-Wettersymbole und der hybride
Teilrefresh benötigen Firmware **0.3.13** oder neuer. Firmware **0.3.14**
rekonstruiert nach jedem Deep Sleep beide vollständigen Controller-RAM-Ebenen,
bevor nur das Wetterfenster differentiell aktualisiert wird. Dadurch bleiben
alle Pixel außerhalb des Teilfensters definiert. Die Wetterentität kann ohne
erneutes Kompilieren in der GuestyTerminal-Zuordnung geändert werden. Firmware
**0.3.15** ergänzt die frei konfigurierbaren und pro Display lokalisierten
Beschriftungen. Änderungen an diesen Texten werden anschließend dynamisch über
Home Assistant übertragen und benötigen keine weitere Firmwarekompilierung.
Firmware **0.3.16** ergänzt den lokalisierten Checkout-Tagesmodus mit eigener
Konfigurationsseite und den im Guesty-Listing hinterlegten
Checkout-Anweisungen. Nach der einmaligen Aktualisierung auf 0.3.16 können die
Checkout-Texte und die Startzeit ohne erneute Firmwarekompilierung geändert
werden. Firmware **0.3.17** ergänzt die dritte Seite für ein leeres Zimmer,
die gezielte Suche nach der nächsten Buchung und die dynamischen Notizfelder.
Nach der einmaligen Aktualisierung auf 0.3.17 können alle Texte dieser Seite
über Home Assistant geändert werden, ohne erneut zu kompilieren. Version
**0.3.18** hält die Checkout-Seite für die vollständig konfigurierte
Nachlaufzeit sichtbar, auch wenn die nächste Buchung bereits im
Anreise-Vorlauf liegt. Eine laufende neue Buchung übernimmt weiterhin sofort.
Für diese reine Integrationskorrektur müssen Geräte mit Firmware 0.3.17 nicht
neu geflasht werden. Version **0.3.19** macht den geräteeigenen
Aktualisieren-Button zu einem vollständigen Guesty-Abgleich mit anschließendem
erzwungenem Neuzeichnen und stellt den richtigen Seitenmodus nach jedem
Neustart wieder her. Auf der Seite für ein leeres Zimmer ersetzt außerdem eine
Batterieanzeige das Wetter und nutzt für reine Prozentänderungen denselben
sicheren Teilrefresh des Headerfensters. Für diese Änderungen müssen die
Integration und anschließend die Display-Firmware auf 0.3.19 aktualisiert
werden.

Version **0.3.20** verbessert die Ausfallsicherheit der Guesty-Abfragen, der
Konfigurations- und Firmware-Aktualisierung sowie der laufenden Display-
Synchronisierung. Beim Entladen oder Neustarten der Integration werden eigene
Hintergrundaufgaben nun sauber beendet. Der interne ESPHome-Reconnect-Marker
wird nicht mehr als Display-Aktion behandelt; dadurch entstehen beim
Wiederverbinden keine irreführenden Warnungen oder verzögerten ungültigen
Serviceaufrufe. Die Integration wurde zusätzlich gegen Home Assistant
2025.12.0, 2026.2.3 und in einer laufenden Installation mit Home Assistant
2026.8.2 geprüft. Wegen der enthaltenen E-Paper-Treiber- und
Renderkorrekturen sollten nach dem HACS-Update auch die Displays einmalig auf
Firmware 0.3.20 aktualisiert werden.

Version **0.3.21** verkleinert das Batteriesymbol der Seite für ein leeres
Zimmer von 48 auf 24 Pixel und passt seinen sichtbaren Füllstand dynamisch in
Zehn-Prozent-Stufen an den angezeigten Batteriewert an. Die Prozentanzeige und
der sichere partielle Header-Refresh bleiben erhalten. Nach dem HACS-Update
muss die Display-Firmware einmalig auf 0.3.21 aktualisiert werden.

Version **0.3.22** ordnet die Batterieanzeige der Seite für ein leeres Zimmer
neu an: Der Prozentwert steht links, das dynamische MDI-Batteriesymbol rechts.
Das Symbol wird um 90 Grad im Uhrzeigersinn gedreht, an der ursprünglichen
Kopfzeile ausgerichtet und behält seine abgestuften Füllstände. Die erhöhte
Renderrevision erzwingt nach dem Firmware-Update genau eine vollständige
Aktualisierung; spätere reine Batterieänderungen verwenden weiterhin den
sicheren partiellen Header-Refresh. Nach dem HACS-Update muss die
Display-Firmware einmalig auf 0.3.22 aktualisiert werden.

Version **0.3.23** korrigiert die sichtbare Größe und vertikale Ausrichtung des
gedrehten Batteriesymbols. Die Darstellung richtet sich nun an der tatsächlich
gerasterten MDI-Glyphenfläche aus: Symbol und Prozentwert sind auf derselben
Mittellinie zentriert und besitzen eine vergleichbare sichtbare Höhe. Der
dynamische Füllstand und der sichere partielle Header-Refresh bleiben erhalten.
Nach dem HACS-Update muss die Display-Firmware einmalig auf 0.3.23 aktualisiert
werden.

Version **0.3.24** gleicht Guesty standardmäßig alle fünf Minuten mit einem
lokalen, pro Listing getrennten RAM-Snapshot ab. Neben laufenden Aufenthalten
werden mindestens die nächsten fünf bestätigten Buchungen erfasst;
Neuzugänge, Änderungen und Stornierungen werden ohne unnötigen E-Paper-Refresh
abgeglichen. Abgeschlossene Buchungen bleiben zwölf Stunden nach Check-out im
Cache, ohne die konfigurierte sichtbare Nachlaufzeit zu verlängern. Mehrere
Displays desselben Listings erhalten getrennte, endpunktspezifische Payloads;
Daten verschiedener Listings und Guesty-Konten werden nicht vermischt. Die
Firmware stabilisiert außerdem die USB-/Akkuerkennung und stellt sicher, dass
ein Aufwachen über die grüne Taste auf Akku nach dem kurzen Abgleich wieder in
den Deep Sleep zurückkehrt. Nach dem HACS-Update muss die Display-Firmware für
diese Energie-Korrekturen einmalig auf 0.3.24 aktualisiert werden.

Version **0.3.25** verhindert OTA-Rollbacks bei akkubetriebenen Displays, die
nach einer erfolgreichen Synchronisierung vor ESPHomes standardmäßigem
60-Sekunden-Bestätigungsfenster in den Deep Sleep wechseln. Jeder geordnete
Deep-Sleep-Eintritt bestätigt den erfolgreichen Firmwarestart nun explizit.
Zusätzlich wiederholt die Home-Assistant-Integration die Datenzustellung nach
einer ESPHome-Wiederverbindung kurz und begrenzt, falls die benutzerdefinierte
Display-Aktion beim ersten Versuch noch nicht registriert ist. Dadurch wird
eine bereits korrekt ausgewählte Buchung nach Firmwareupdate, Neustart oder
Aufwachen zuverlässig als Willkommensseite zugestellt. Nach dem HACS-Update
muss die Display-Firmware einmalig auf 0.3.25 aktualisiert werden.

Version **0.3.26** wartet bei jeder ESPHome-Verbindung, bis Home Assistant die
Gerätezustände tatsächlich abonniert hat, bevor der Display-Endpunkt seine
erneute Datenanforderung signalisiert. Dadurch erreicht die bereits korrekt
ausgewählte Buchung das E-Paper auch nach Firmwareupdate, Neustart und kurzen
oder instabilen API-Verbindungen. Die Integration reagiert sowohl auf den
Reconnect-Impuls als auch auf den wiederhergestellten Aktionsnamen und versucht
die Zustellung innerhalb eines begrenzten Zeitfensters erneut. Nach dem
HACS-Update muss die Display-Firmware einmalig auf 0.3.26 aktualisiert werden.

Version **0.3.40** führt außerdem die physisch bestätigte Display-Zustellung
ein. Home
Assistant unterscheidet jetzt Empfang, Renderbeginn und den tatsächlich
erfolgreichen E-Paper-Refresh; nur Erfolg oder ein nachweislich bereits
gezeichnetes identisches Bild gelten als zugestellt. Aufträge pro Display
werden serialisiert, überholte Zwischenstände zusammengefasst und mit festen
Empfangs-, Panel- und Wiederholungszeiten begrenzt. Der Integrationsstart bleibt
auch bei einem nicht antwortenden Display sofort verfügbar, während ein
bestätigtes Akku-Gerät nach dem Einschlafen ohne zusätzliche Wartezeit
abgeschlossen wird. Neutrale Panel-, Reset-, Wellenform-, Rand- und
Zustelldiagnosen erleichtern die Ursachenanalyse, ohne Zugangsdaten oder
Zustellkennungen in Downloads zu übernehmen. Ein Display-Firmwareupdate auf
0.3.40 ist erforderlich; physische Zustellung, Strompfad und Randbild müssen
anschließend noch am realen E1001 geprüft werden.

Version **0.3.38** korrigiert die Watchdog-Anbindung der mit 0.3.37
eingeführten Panel-Aufgabe. Diese Aufgabe darf ESPHomes Watchdog nicht selbst
zurücksetzen, weil ESPHome 2026.8.1 ausschließlich seine Hauptschleife dafür
registriert. OTP-Lesevorgänge und zeilenweise Panel-Übertragungen geben die CPU
jetzt stattdessen kooperativ frei. Damit bleiben Netzwerk und Hauptschleife
arbeitsfähig, ohne dass ein fremder Watchdog-Aufruf wiederholte Neustarts und
Reconnects auslöst. Beginn, Ende, Dauer und Erfolg jeder Hardwaretransaktion
werden neutral protokolliert. Ein Display-Firmwareupdate auf 0.3.38 ist
erforderlich; die Wirkung auf dem realen E1001 wird nach der Installation
bestätigt.

Version **0.3.37** verhindert, dass ein langer E-Paper-Vollrefresh die
ESPHome-Verbindung zu Home Assistant blockiert. Die hardwarenahen OTP-, SPI-
und Panel-Transaktionen laufen nun getrennt vom ESPHome-Hauptablauf; Payloads
und lokale Datenschutz-Löschvorgänge bleiben vollständig serialisiert. Dadurch
entsteht nach einem mehr als 60 Sekunden dauernden Refresh keine
Reconnect-/Redraw-Schleife mehr, und Diagnose-Entitäten bleiben erreichbar.
Die OTP-Wartezeit ist zusätzlich auf die dreisekündige Seeed-Referenzgrenze
beschränkt. Ein Display-Firmwareupdate auf 0.3.37 ist erforderlich. 258 Tests,
90,79 % Branch-Abdeckung sowie Konfigurationsprüfung und vollständiger Build
mit ESPHome 2026.8.1 waren erfolgreich; die Wirkung auf dem realen E1001 wird
nach der Installation bestätigt.

Version **0.3.36** versuchte den dunklen Außenrand über die dedizierte `LUTBD`
zu korrigieren. Im Registermodus wurden ihre 42 Bytes aus der gültigen OTP-Bank
zweimal gelesen und bei Übereinstimmung nach `R25h` geladen. Diese Maßnahme war
nur statisch und per Firmware-Build geprüft. Der spätere reale 0.3.43-Test hat
die damalige Ursachenannahme widerlegt: Genau dieser Pfad ließ `BUSY_N` nach dem
sichtbaren Bildaufbau aktiv und löste die identische Refresh-Schleife aus. Die
Version 0.3.44 entfernt den `R25/LUTBD`-Hostpfad, behält
Seeeds E1001-Auswahl `R50h=0x10,0x07` und gibt die Randelektrode nach der
Wellenform mit `R52h.BDEND=11` frei.

Version **0.3.35** korrigierte zuvor die
Rand-Endspannung während des vollständigen Bildaufbaus. Im Custom-LUT-Pfad
endet die Randelektrode nun wie vom UC8179 vorgesehen auf `VCOM_DC` statt auf
0 V; erst danach wird sie mit datenblattkonformen Registerbits elektrisch
freigegeben. Renderrevision 26 erzwingt einmalig den dafür notwendigen
Vollrefresh. Die Randpixel des 800×480-Framebuffers werden weiterhin vollständig
weiß übertragen. Für diese Version ist ein Display-Firmwareupdate erforderlich;
der anschließende reale Hardwaretest zeigte jedoch, dass diese Maßnahme allein
den Rahmen nicht beseitigte, weil `R52h` erst nach der eigentlichen LUT wirkt.

Version **0.3.34** gab die separate UC8179-Randelektrode unmittelbar vor dem
Ausschalten hochohmig. Der anschließende Hardwaretest zeigte, dass dies allein
einen zuvor dunkel aufgebauten bistabilen Pigmentzustand nicht aufhellt. Die
Konfigurationsprüfung und der Firmware-Build waren mit ESPHome 2026.7.4
erfolgreich; 0.3.35 verlagert die eigentliche Korrektur deshalb in die
Refresh-Wellenform.

Version **0.3.33** erweitert den Modus **Automatisch** um
eine revisionsabhängige USB-Erkennung. E1001 v1.2 verwenden weiterhin den
identifizierten SY6974B und dessen dediziertes `BUS_GD`-Signal. Antwortet dieser
Ladecontroller gar nicht und wurde er auf dem Gerät noch nie sicher erkannt,
prüft die Firmware den bei E1001 v1.0 ausschließlich von `TYPEC_5V` versorgten
USB-UART-Baustein. Vor jeder Messung pausiert sie die serielle Ausgabe, trennt
den ESP32-Sendepin, hält ihn zum Schutz vor Rückspeisung auf Low und wertet beim
älteren Pfad drei Messfenster aus. Nur ein roh bestätigter USB-Pegel aktiviert
UART0 anschließend wieder; auf Akku bleibt die Brücke bis zum Deep Sleep
elektrisch ruhig. Ein einmal sicher erkannter SY6974B wird als nicht sensible
Hardwareeigenschaft gespeichert und bleibt bei späteren I²C-Störungen
maßgeblich. Die neue Diagnose-Entität **Power detection method** macht den
tatsächlich verwendeten Pfad sichtbar. Für 0.3.33 ist ein
Display-Firmwareupdate nötig. Die Vier-Grau-Übertragung korrigiert außerdem die
zuvor vertauschte UC8179-Polarität, damit wieder ein heller Hintergrund mit
dunkler Schrift erscheint. Die Renderrevision steigt deshalb auf 24 und
erzwingt einmalig einen vollständigen Neuaufbau. Der Stand wurde mit jeweils
254 Tests gegen Home Assistant 2025.12.0 und 2026.2.3 bei 90,79 %
Branch-Abdeckung sowie einem vollständigen Firmware-Build mit ESPHome 2026.7.4
geprüft; im App-Partitionsreport bleiben 21 % frei. Die automatische
Altgeräteerkennung muss noch auf realer v1.0- und v1.2-Hardware mit Akku, PC-USB, hostlosem
Netzteil, reinem Ladekabel und Abziehen/Wiederanstecken geprüft werden. Ein
dauerhaft auf Low gehaltener serieller Eingang ist auf v1.0 physikalisch nicht
von einer unversorgten USB-UART-Brücke unterscheidbar.

Version **0.3.32** verifiziert bereits bekannte aktive
Reservierungen zusätzlich anhand ihrer V3-ID, wenn Guestys gefilterte Suche sie
nach einer Einheitenzuweisung nicht mehr eindeutig zurückliefert. Die Abfrage
erfolgt in Paketen mit höchstens zehn IDs. Ein gemeinsamer Zeitpunkt steuert
API-Filter, zeitabhängige `stay`-Segmente, Normalisierung, Abgleich und
Seitenauswahl. Ein zusätzlicher kontoweiter aktueller Snapshot entdeckt spätere
aktive `stay`-Segmente auch nach einem Home-Assistant-Neustart; nur lokal
eindeutig gemappte Identitäten gelangen weiter. Kontrolliertes Zusammenführen
verhindert zugleich, dass ältere Projektionen explizit geleerte sensible Felder
über alternative Guesty-Feldformen wiederherstellen; Löschungen aus jeder
aktuellen Projektion gelten dabei auch über Gast-ID- und Custom-Field-Aliase.
Das schließt direkte `keycode`-/`keyCode`-/`doorCode`-Formen, Custom-Field-
Datensätze mit `value` oder `code` und zunächst nur über ihre Field-ID
erkennbare Felder ein. Ein leerer aktueller Wert kann daher weder durch den
Türcode-Cache noch durch die optionale Populated-Fields-Abfrage oder eine
spätere Normalisierung wieder auftauchen.
Fehler bleiben auf das jeweils betroffene Listing begrenzt, dessen RAM-Snapshot
wird aber nicht als neue Display-Payload ausgegeben und erneuert deshalb keine
Datenschutzfrist. Fehlerhafte oder widersprüchliche Antwortformen gelten nicht
als Löschung. Der Client reiht Anfragen in Guestys Grenzen von 15 pro Sekunde,
120 pro Minute und 5.000 pro Stunde ein;
`Retry-After` nach HTTP 429 wird ohne versteckten Langzeitschlaf sofort
weitergegeben. Die Grenzen gelten bei Guesty kontoweit und tokenübergreifend;
getrennte Clients teilen daher dasselbe Kontingent.

Die zugehörige Firmware gibt beim `auto`-OTP-Test den SPI2-Bus tatsächlich frei
und stellt ihn anschließend vollständig wieder her. Außerdem folgt sie Seeeds
Abfolge aus 100 ms Mindestwartezeit und anschließendem Warten auf den inaktiven
`BUSY_N`-Pegel. Die Renderrevision ist 23; bei Installation von Version
0.3.32 ist daher zwingend auch ein Display-Firmwareupdate
erforderlich. Der Stand wurde mit jeweils 237 Tests gegen Home Assistant
2025.12.0 und 2026.2.3 bei 90,79 % Branch-Abdeckung sowie Ruff, Formatprüfung,
Mypy und Bytecode-Kompilierung geprüft. ESPHome 2026.7.4 hat die
Referenzkonfiguration validiert und vollständig gebaut; im App-Partitionsreport
bleiben 21 % frei. Eine Prüfung der OTP-, Voll-/Teilaktualisierungs- und
BUSY-Pfade auf einem realen E1001 steht noch aus.

Version **0.3.31** behebt den weiterhin möglichen Verlust einer laufenden
Buchung beim Übergang von der Vorbereitungs- zur Willkommensseite. Projektionen
derselben Guesty-Reservierung werden listingübergreifend zusammengeführt und
anhand konkreter Einheit, Listing, Einheitentyp und übergeordnetem Listing
eindeutig genau einem konfigurierten Display zugeordnet. Mehrdeutige Antworten
werden zum Schutz der Gästedaten nicht dupliziert.

Der UC8179-Treiber verwendet ab 0.3.31 ausschließlich dokumentiert permissiv
lizenzierte Seeed-Quellen. Im Modus `auto` nutzt er die interne
Vier-Grau-Wellenform kompatibler Panelrevisionen und andernfalls Seeeds
Register-LUTs; die erkannte Auswahl bleibt über Tiefschlaf erhalten. Wegen der
neuen Treiberfolge und Renderrevision 22 müssen nach dem HACS-Update auch alle
Displays einmalig auf Firmware 0.3.31 aktualisiert werden. Der Release wurde
mit jeweils 177 Tests gegen Home Assistant 2025.12.0 und 2026.2.3 bei 91,38 %
Abdeckung sowie einem vollständigen Build mit ESPHome 2026.7.4 geprüft. Eine
physische Sichtprüfung auf einem realen E1001 steht noch aus.

Version **0.3.30** stabilisiert bei Guesty-Mehrfacheinheiten den Übergang von
der Vorbereitungsseite zur Willkommensseite. Eine beim Check-in nachträglich
vergebene konkrete Einheit trennt die aktive Buchung nicht mehr vom
konfigurierten Listing. Alle drei Zustände – Vorbereitung, Willkommen und
Check-out – verwenden außerdem denselben Aktualisierungszeitpunkt. Dies ist
eine reine Integrationskorrektur; vorhandene Displays mit Firmware 0.3.29
müssen nicht neu geflasht werden.

Version **0.3.29** korrigiert die automatische Netzstromerkennung. Die Firmware
verwendet jetzt das dedizierte `REG0A.BUS_GD`-Signal des SY6974B und erkennt
dadurch auch CDP-, unbekannte und nicht standardisierte USB-Netzteile korrekt.
Ein angeschlossenes Display bleibt damit im Modus **Automatisch** zuverlässig
online. Nach dem HACS-Update muss die Display-Firmware einmalig auf 0.3.29
aktualisiert werden.

Version **0.3.28** korrigiert die Akkuanzeige und härtet den Energiesparpfad.
Die nichtlineare Spannungskennlinie wird nun wirklich stückweise ausgewertet und
aus 16 ADC-Messungen gemittelt. Einheitliche Deep-Sleep-Pfade sowie die neuen
Diagnose-Entitäten **Wake-up reason** und **Awake duration** helfen dabei,
Wake-Schleifen und lange Verbindungsfenster zu erkennen. Nach dem HACS-Update
muss die Display-Firmware einmalig auf 0.3.28 aktualisiert werden.

Version **0.3.27** härtet Datenschutz, Zustellung und Wartung systematisch.
Ein sensibler Bildschirm gilt erst nach einem bestätigten physischen Refresh
als gelöscht; fehlgeschlagene Löschungen werden erneut versucht. Manuelle
Aktualisierungen melden Guesty- und Zustellfehler zuverlässig, Display-Mappings
bleiben auch bei Entity-Umbenennungen stabil, Diagnose-Downloads verwenden eine
strikte Positivliste und Firmwaredateien werden sicher atomar geschrieben.
Abfragen mehrerer Listings laufen begrenzt parallel, ungültige Zeitdaten werden
robust verworfen und CI prüft beide unterstützten Home-Assistant-Baselines sowie
ESPHome. Nach dem HACS-Update muss die Display-Firmware einmalig auf 0.3.27
aktualisiert werden.

## Datenschutz

Die von der Integration angelegten Statussensoren enthalten weder Gastnamen
noch Tür- oder WiFi-Codes. In den Attributen steht lediglich, ob der aktuelle
Bildschirm solche Daten enthält. Fehlerprotokolle geben ebenfalls keine
Zugangsdaten aus.

Der Display-Sensor **Relativer Schallpegel (30 Sekunden)** verarbeitet die
PDM-Samples ausschließlich im flüchtigen Speicher des ESP32 und veröffentlicht
alle 30 Sekunden nur den relativen RMS-Wert des unmittelbar vorhergehenden
vollständigen 30-Sekunden-Fensters. Es werden weder Audiodaten noch einzelne
Messproben an Home Assistant übertragen, aufgezeichnet oder dauerhaft
gespeichert. `0 dB` bezeichnet dabei den digitalen Vollpegel des eingebauten
Mikrofons; ohne individuelle akustische Kalibrierung ist der Wert bewusst kein
geeichter dB(A)-Raumpegel. Auf Akku ist der Sensor nicht aktiv. Die optionale
erweiterte Entität **Microphone status** enthält ausschließlich neutrale
Laufzeitzustände und niemals einen Sample- oder Lautstärkewert.

Über Home Assistants Download-Diagnose kann zusätzlich ein strikt
erlaubnisbasiertes Abbild mit Listingnamen, Entity-IDs, Protokollversionen,
Anzeigearten, Lease-Zeitpunkten und neutralem Zustellstatus erzeugt werden.
Gastnamen, SSIDs, Passwörter, Türcodes, Guesty-Zugangsdaten und
Fehlermeldungstexte werden dort nicht ausgegeben.

Der dauerhaft gespeicherte Datenschutzstatus wird erst nach einem erfolgreich
bestätigten physischen E-Paper-Refresh geändert. Schlägt das Löschen eines
sensitiven Bildschirms fehl, bleibt das Gerät als sensitiv markiert und versucht
den neutralen Bildschirm erneut zu zeichnen. Auf Akku bleibt es in diesem
Fehlerfall wach, statt einen nicht erfolgten Löschvorgang zu bestätigen.
Der häufig erneuerte Lease-Zeitpunkt bleibt dagegen im flüchtigen Speicher;
fehlt er nach einem Neustart, behandelt die Firmware den sensitiven Bildschirm
vorsorglich als abgelaufen.

Für Teilupdates behält der RTC-Speicher ausschließlich ein monochromes Abbild
des kleinen Wetterfensters und die Anzahl der Teilupdates. Zusätzlich werden
zwei nicht rückrechenbare Inhaltsfingerabdrücke gespeichert. Buchungsname,
Türcode und WiFi-Zugangsdaten werden dafür nicht dauerhaft abgelegt.

Die ESPHome-Diagnose-Entität **Angezeigte Buchung** ist hiervon bewusst
ausgenommen: Sie enthält den Gastnamen sowie Check-in und Check-out zur
Fernkontrolle des Displays. Home Assistant kann diese Zustände im Recorder
speichern. Wer diese personenbezogene Historie nicht benötigt, sollte die
Entität in den Recorder-Einstellungen ausschließen.

## Projektwissen und Wartung

Die gepflegte Wissensbasis besteht aus wenigen, klar abgegrenzten Dokumenten:

- [`AGENTS.md`](AGENTS.md) enthält Architektur, nicht verhandelbare
  Produktregeln, Änderungsfolgen, Prüfungen und Releasevorgaben für Agents und
  Maintainer.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) fasst den Beitrags- und Prüfablauf
  kompakt zusammen.
- [`CHANGELOG.md`](CHANGELOG.md) dokumentiert veröffentlichte und noch nicht
  veröffentlichte Änderungen.
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) hält bestätigte Fehlerursachen,
  eindeutige Log-Signaturen und verbindliche Schutzregeln gegen Regressionen
  fest.
- [`SECURITY.md`](SECURITY.md) beschreibt die private Meldung von
  Sicherheitsproblemen und den sicheren Umgang mit Diagnosedaten.
- [`LICENSE_STATUS.md`](LICENSE_STATUS.md) und
  [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) dokumentieren den aktuellen
  Distributionsstatus sowie Herkunft und Lizenz externer Bestandteile.

Bei widersprüchlichen technischen Angaben gilt der getestete Quellcode
zusammen mit `AGENTS.md` als Wartungsgrundlage; Benutzerverhalten und
Installationsschritte müssen anschließend in diesem README nachgezogen werden.

## Automatische Veröffentlichungen

Neue Versionen werden ausschließlich über den GitHub-Workflow **Release** vom
aktuellen `main`-Stand veröffentlicht. Er lässt eine Freigabe nur zu, wenn genau
dieser Stand bereits alle automatischen Prüfungen bestanden hat. Versionsnummer,
Changelog, Lizenzstatus und Drittanbieterhinweise werden erneut kontrolliert;
außerdem muss angegeben werden, ob die vollständige Hardwareprüfung auf einem
realen E1001 erfolgreich war oder noch aussteht. Die Release-Notizen, der
annotierte Versions-Tag und das GitHub-Release entstehen danach automatisch.

Der Testablauf startet die Release-Vorprüfung, beide unterstützten
Home-Assistant-Versionen, die statische Prüfung und den ESPHome-Firmwarebau
sofort parallel. Der stabile ESPHome-Werkzeugcache und der inkrementelle
Projekt-Buildcache werden getrennt wiederverwendet. Ein Versions-Tag startet
keinen überflüssigen zweiten Firmwarebau, weil das Release nur einen bereits
erfolgreich geprüften Commit verwenden darf.

## Tests

```bash
python3 -m pip install -r requirements-test.txt
ruff check .
ruff format --check .
mypy custom_components/guesty_terminal
python3 -m compileall -q custom_components/guesty_terminal
pytest
```

Für einen lokalen Lauf gegen die minimale Home-Assistant-Version werden die
historisch kompatiblen Transitivabhängigkeiten zusätzlich festgesetzt:

```bash
python3 -m pip install -r requirements-test-tools.txt \
  -c constraints-homeassistant-2025.12.txt homeassistant==2025.12.0
```

`pytest` misst automatisch die Zeilen- und Branch-Coverage der vollständigen
Python-Integration. Sobald die Gesamtdeckung unter **80 %** fällt, endet der
Testlauf mit einem Fehler. Der aktuelle Bericht wird direkt im Terminal
ausgegeben und zeigt nicht abgedeckte Zeilen an.

Vor dem ersten produktiven Einsatz sollte mit einer Testreservierung geprüft
werden, ob das konkrete Guesty-Konto `keycode`, `wifiName` und `wifiPassword` in
den erwarteten API-Antworten bereitstellt.

Hinweise für Beiträge, Sicherheit und Distribution sind in der obigen
Wissensbasis zentral verknüpft.
