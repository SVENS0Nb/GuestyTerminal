# Zu GuestyTerminal beitragen

Vielen Dank für Beiträge. Vor Änderungen bitte `AGENTS.md` sowie die Architektur-
und Datenschutzabschnitte in `README.md` lesen. Änderungen an sichtbaren Feldern
müssen immer auf beiden Seiten der Home-Assistant-/ESPHome-Grenze umgesetzt und
getestet werden.

## Lokale Prüfung

```bash
python3 -m pip install -r requirements-test.txt
ruff check .
ruff format --check .
mypy custom_components/guesty_terminal
pytest
python3 -m compileall custom_components/guesty_terminal
```

Firmwareänderungen benötigen zusätzlich eine nicht produktive
`esphome/secrets.yaml` sowie:

```bash
esphome config esphome/guestyterminal-display-1.yaml
esphome compile esphome/guestyterminal-display-1.yaml
```

Bitte keine echten Secrets, Buildverzeichnisse, Caches oder generierten
ESPHome-Output committen. Hardwareänderungen müssen im Pull Request als auf
einem realen E1001 getestet oder ausdrücklich als nicht hardwaregetestet
gekennzeichnet werden.
