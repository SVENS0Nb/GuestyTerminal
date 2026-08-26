# Lizenzstatus

Dieses Repository enthält derzeit keine projektweite Lizenz, die eine Nutzung,
Änderung oder Weiterverteilung des gesamten GuestyTerminal-Quellcodes erlaubt.
Ohne eine solche ausdrückliche Lizenz bleiben die gesetzlichen Rechte bei den
jeweiligen Rechteinhabern.

Der Unterordner `esphome/components/guesty_epaper_gray4` enthält eine eigene
MIT-Lizenzdatei. Seine statischen UC8179-Waveformtabellen, die bidirektionale
OTP-Lesemechanik und die zugrunde liegenden Initialisierungssequenzen stammen
aus den in `THIRD_PARTY_NOTICES.md` festgehaltenen, permissiv lizenzierten
Seeed-Quellen. Bankpriorität, Checkcodes, Registerfelder und OTP-Adressbereiche
sind anhand des dort ebenfalls genannten offiziellen UltraChip-Datenblatts
eigenständig umgesetzt. Weder Datenblattinhalt noch panelinterne OTP-Bytes
werden im Repository oder Firmware-Artefakt gebündelt. Die dazugehörigen
Seeed-Lizenztexte liegen direkt beim Treiber. Der zuvor dokumentierte, unklare
Drittanbieter-Codepfad wurde entfernt.

Die historische ESPHome-Implementierung des früher verwendeten Waveshare-
Modells `7.50inv2` steht unter GPLv3. Sie wurde ausschließlich verglichen, um
den damaligen Hardwareablauf zu identifizieren. Der aktuelle optionale
Monochrom-Vorlauf ist anhand der offiziellen UC8179-Registerdokumentation
eigenständig implementiert; Quellcode, Kommentare, Klassenstruktur oder
Wellenformdaten aus ESPHomes GPL-Datei wurden nicht übernommen. Die Details und
festgehaltene Quellversion stehen in `THIRD_PARTY_NOTICES.md`.

Vor einem öffentlichen Release oder einer Weiterverteilung sollte der
Projektinhaber:

1. entscheiden, ob Dritte den eigenen GuestyTerminal-Code nutzen, ändern oder
   weiterverteilen dürfen;
2. bei gewünschter Freigabe eine passende Projektlizenz ausdrücklich auswählen
   und als Root-Datei `LICENSE` hinzufügen;
3. vor jedem Release die Drittanbieterhinweise sowie die Rechte an eigenen
   Marken-, Logo- und Bilddateien erneut prüfen.

Die öffentliche Bereitstellung als proprietärer Quellcode wird durch den
früheren Treiberbefund nicht mehr blockiert. Ohne projektweite Lizenz erhalten
Dritte jedoch weiterhin keine ausdrückliche Erlaubnis zur Nutzung, Änderung
oder Weiterverteilung der übrigen GuestyTerminal-Dateien.

Der Projektinhaber hat sich für öffentliche Releases als proprietär
bereitgestellter Quellcode entschieden. Der folgende maschinenlesbare Marker
dokumentiert diese bestehende Entscheidung für den automatischen
Veröffentlichungsprozess; er ersetzt weder die Prüfung der Drittanbieterrechte
noch eine Rechtsberatung:

`PUBLIC_PROPRIETARY_SOURCE_RELEASES_PERMITTED`

Diese Datei dokumentiert nur den aktuellen Zustand und ist keine Rechtsberatung.
