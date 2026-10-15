---
alwaysApply: true
---

Desktop- und Browser-Bedienung delegieren: Aufgaben, die eine Desktop-App bedienen oder interaktiv im Browser arbeiten, an den Subagenten `computer` bzw. `browser` über das `task`-Tool geben, statt die Preludes im Hauptkontext zu fahren. Ausnahmen: einzelne, rein lesende Kurzabfragen (z. B. ein `computer.windows()` oder ein `read` einer statischen URL) und klar umrissene Teilaufgaben über die Schnellspur `arc-lane` (Skill; ein Bash-Aufruf, eine JSON-Zeile zurück) — die direkt im Hauptkontext ausführen; erst bei `NEEDS_AGENT`/`BLOCKED`/`ERROR` oder offenen, mehrstufigen Aufgaben delegieren. Statische Webseiten weiter per `read`.

Meldet ein `computer`/`browser`-Subagent unter `Lektionen:` etwas Neues und Wiederverwendbares, hänge es an den Managed Skill `cu-lessons` an (erst `skill://cu-lessons` vollständig lesen, dann `manage_skill` update mit ALLEM Bestehenden plus der neuen Zeile) oder speichere es per `learn` — nur belegte Erkenntnisse. Den Skill `fast-computer-browser-use` (Kern-Prozedur, vom User gepflegt) nie per `manage_skill` ändern; Browser-/GUI-Lektionen aus anderen Aufgaben gehören ebenfalls nach `cu-lessons`.
