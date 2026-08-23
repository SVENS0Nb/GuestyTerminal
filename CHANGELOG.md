# Änderungshistorie

Alle wesentlichen Änderungen an GuestyTerminal werden hier gesammelt. Einträge
unter „Unveröffentlicht“ gehören noch zu keinem freigegebenen Tag.

## Unveröffentlicht

Noch keine Änderungen.

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
