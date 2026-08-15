# GuestyTerminal für reTerminal E1001

<img src="assets/guestyterminal-logo.png" alt="GuestyTerminal Logo" width="128">

Dieses Projekt verbindet Guesty mit Home Assistant und zeigt die Daten der
aktuellen Reservierung auf einem Seeed Studio reTerminal E1001 an:

- persönlicher Willkommensgruß;
- Guesty-Reservierungsfeld `keycode`;
- WiFi-Name und Passwort;
- lokal erzeugter, direkt verbindender WiFi-QR-Code;
- Check-out-Zeit;
- automatische neutrale Seite 30 Minuten nach Check-out oder bei Stornierung;
- Zuordnung eines Guesty-Listings zu jedem Display in der Home-Assistant-UI.

Die Guesty-Zugangsdaten verbleiben in Home Assistant. Sie werden niemals auf
dem ESP32 gespeichert oder an das Display übertragen.

Die Geräte verwenden weiterhin ESPHome. Es ist keine separate C++-Firmware
erforderlich; das mitgelieferte E1001-Paket ersetzt lediglich die bisherige
Dashboard-Konfiguration und ergänzt die sichere Home-Assistant-Aktion.

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
   eine ESPHome Native-API-Aktion und das Gerät zeichnet den Bildschirm.

## Voraussetzungen

- Home Assistant 2025.12 oder neuer;
- ESPHome mit Unterstützung für `api.actions` und `qr_code`;
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

## E1001 flashen

1. `esphome/secrets.example.yaml` nach `esphome/secrets.yaml` kopieren.
2. Alle Platzhalter durch neue, zufällige Werte ersetzen.
3. In `esphome/guestyterminal-display-1.yaml` `device_name` und `friendly_name`
   anpassen.
4. Konfiguration installieren:

   ```bash
   esphome run esphome/guestyterminal-display-1.yaml
   ```

Beim Build erscheinen Hinweise zu GPIO 3, 19 und 20. Diese Pins stammen aus
der offiziellen E1001-Hardwarebelegung und sind für dieses Board beabsichtigt.

Für weitere Displays die Beispieldatei kopieren und einen eindeutigen
`device_name` verwenden. Alle Geräte verwenden dasselbe Layout-Paket.

## Listing einem Display zuordnen

1. Das E1001 mit der grünen Taste aufwecken und warten, bis es in Home
   Assistant online ist.
2. In **Einstellungen → Geräte & Dienste → GuestyTerminal → Konfigurieren**
   gehen.
3. **Listing einem Display zuordnen** wählen.
4. reTerminal, Guesty-Listing, Begrüßung und Anzeigezeitraum auswählen.
5. Für jedes weitere Display wiederholen.

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
- Das E1001 wacht alle fünf Minuten auf und bleibt maximal 45 Sekunden aktiv.
- Weil E-Paper das letzte Bild stromlos behält, erhält jeder Gastbildschirm eine
  erneuerbare 15-Minuten-Freigabe. Home Assistant erneuert sie beim regulären
  Abruf bis 30 Minuten nach Check-out. Nach dem Entfernen einer Zuordnung oder
  Integration verschwinden die Zugangsdaten dadurch auch dann zeitnah, wenn das
  Display beim Entfernen geschlafen hat.
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

## Datenschutz

Die von der Integration angelegten Statussensoren enthalten weder Gastnamen
noch Tür- oder WiFi-Codes. In den Attributen steht lediglich, ob der aktuelle
Bildschirm solche Daten enthält. Fehlerprotokolle geben ebenfalls keine
Zugangsdaten aus.

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
