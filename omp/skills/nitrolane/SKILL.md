---
name: nitrolane
description: Schnellspur für klar umrissene Browser- und Windows-Desktop-Teilaufgaben (Formular ausfüllen, Link/Artikel öffnen, Feld setzen, Buttons in Reihenfolge) über arc-cua + TypeSafe JEV — 1–6 s statt 20–70 s Subagent-Loop. Vor dem browser-/computer-Prelude versuchen.
---

# nitrolane

JEV wählt pro Schritt nur aus angebotenen Elementen und Operationen (~0,3 s/Entscheidung); Text kommt nur aus `inputs`. Ein Aufruf = eine Teilaufgabe; Ergebnis ist ein eingerücktes JSON-Objekt.

## Aufruf (git-bash)

```bash
ARC="$HOME/nitrolane/vendor/arc-cua-windows/.venv/Scripts/python.exe"   # created by setup.ps1
LANE="$HOME/nitrolane/nitrolane.py"
"$ARC" "$LANE" <<'EOF'
{"target":"browser","url":"https://httpbin.org/forms/post",
 "subtask":{"goal":"Fill the pizza order form and submit it",
  "inputs":{"name":"Max Muster","phone":"0123456","email":"max@example.com"},
  "verification":["The order was submitted and the response page is shown"],
  "constraints":["Choose size Medium","Select topping Bacon only"],"max_actions":15},
 "check":"document.body.innerText.includes('Max Muster')"}
EOF
```

- `target:"browser"`: eigenes headless Chrome (Profil `%LOCALAPPDATA%\nitrolane`, Port 9333, Viewport 1280×2400), bleibt warm; nie das Chrome des Users. `"headed":true` nur beim Kaltstart wirksam.
- `target:"desktop"`: `app` = `{"title":"<Teil des Fenstertitels>"}` (optional `"launch":"calc.exe"`) oder `{"pid":N}`. **Vordergrund**: bewegt echte Maus/Fokus — User vorher nicht mitten im Tippen stören; für Hintergrund-Bedienung stattdessen cua-driver.
- `check` (Browser: JS-Ausdruck; Desktop: Text, der danach in Name/Wert eines Elements steht) unabhängig vom Modell prüfen lassen und immer mitgeben; Ergebnis in `"check"`. `extract` (Browser) liefert zusätzlich den Wert eines JS-Ausdrucks von der Ergebnis-Seite — Lesen und Prüfen im selben Aufruf. Niemals denselben Subtask erneut ausführen, nur um zu prüfen.
- Optionen: `timeout_s` (90), `min_confidence` (0.45), `min_completion_confidence` (0.3), `min_margin`, `keep_tab`, `cache`.
- `"cache":true` (nur mit `check`): verifizierte Trajektorie wird gespeichert und bei identischer Anfrage ohne Modell-Calls replayt (`cache: hit|stored|stale|invalidated`). Gemessen: Browser 4,7→2,95 s, Notepad 3,98→0,53 s. Schlägt der Check nach Replay fehl, wird der Eintrag gelöscht und NEEDS_AGENT gemeldet.

## Ergebnis lesen

| `status` | Bedeutung → nächster Schritt |
|---|---|
| `SUBTASK_COMPLETE` | fertig (bei `check:false` trotzdem selbst prüfen) |
| `NEEDS_INPUT` | `needs_input` nennt das Feld → Wert in `inputs` ergänzen, erneut |
| `NEEDS_AGENT` mit `Refused CLICK on '…': a delete/send/… action` | riskante Schaltfläche; nur wenn der User genau das will: `allowed_risks:["delete"]` |
| `NEEDS_AGENT` mit `confidence … below` | JEV war unsicher, hat nichts getan → Zustand prüfen, Aufgabe präziser oder Prelude-Weg |
| `BLOCKED` / `ERROR` | Prelude-Weg (`browser`/`computer`) oder cua-driver |

`steps[]` ist je Aktion eine Zeile mit Ziel, Wert, `conf`, `(no change)`; `sec.run` die reine Laufzeit.

## Aufgaben so formulieren (aus der Testbatterie belegt)

- Jede Anforderung als eigenes `verification`-Kriterium; Kriterien auf `inputs` beziehen („The document text is exactly the supplied text“) statt umschreiben — „three lines ending with …“ verwarf JEV trotz richtigem Text.
- Reihenfolgen explizit: „Using the buttons in exactly this order: Clear, 7, Plus, 8, Equals“. „compute 7 plus 8“ klickte 7, 8, Plus, Gleich.
- Jeder Literalwert in `inputs`; im `goal` erwähnter Text wird nie getippt.
- Risiko-Wörter wirken auf ganze Wörter im Label, auch falsch-positiv: Checkbox „Send me product updates“ braucht `allowed_risks:["send"]`.
- Nicht für: Logins/2FA/Zahlung, Uploads, Drag&Drop, Canvas/Spiele, Cross-Origin-iframes, minimierte/gesperrte/elevated Fenster.

## Messwerte (Win 11, 2026-10-15, Battery 27 Läufe, jevify-geprüft)

26/27 korrekt (20 verifiziert erledigt, 6 korrekte Rückgaben, 0 Falsch-Erfolge, 0 Regelverstöße); einziger Fehlgriff: „7 plus 8“ ohne explizite Reihenfolge. Laufzeit: Link/Artikel 1–3 s, Formular mit 6 Feldern 4,5 s, Notepad-Text 1,8 s, 7 Rechner-Klicks 5,9 s, zzgl. ~0,6 s Prozessstart und 0,5–1,5 s Seitenladen.

## Wartung

Battery: Fixture-Server `python -m http.server 8765 --bind 127.0.0.1` in `tests/pages`, dann `"$ARC" tests/battery.py` → `last_run.json`, mit der Rubrik in `battery.json` per jevify bewerten. Lokale Patches am Fork: `vendor/arc-cua-windows/LOCAL_PATCHES.md`.
