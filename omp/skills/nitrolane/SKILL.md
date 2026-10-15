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
- `target:"desktop"`: `app` = `{"title":"<Teil des Fenstertitels>"}` (optional `"launch":"calc.exe"`) oder `{"pid":N}`. Mit `cua-driver` im PATH laufen Klicks/Werte auf eindeutig benannten Elementen im Hintergrund (gemessen 0 Fokuswechsel bei Rechner und Notepad, ~0,3 s/Aktion mehr; `"background":false` schaltet ab). Tasten und unbenannte/mehrdeutige Ziele brauchen kurz den Vordergrund; das Fenster des Users wird am Ende wiederhergestellt.
- `check` (Browser: JS-Ausdruck; Desktop: Text, der danach in Name/Wert eines Elements steht) unabhängig vom Modell prüfen lassen und immer mitgeben; Ergebnis in `"check"`. `extract` (Browser) liefert zusätzlich den Wert eines JS-Ausdrucks von der Ergebnis-Seite — Lesen und Prüfen im selben Aufruf. Niemals denselben Subtask erneut ausführen, nur um zu prüfen.
- Optionen: `timeout_s` (90), `min_confidence` (0.35), `min_completion_confidence` (0.3), `min_margin`, `keep_tab`, `cache`, `provider`, `transitions`, `steps`, `background`.
- `"cache":true` (nur mit `check`): verifizierte Trajektorie wird als parametrisiertes Template gespeichert (Input-Werte als Variablen) und bei gleicher Aufgabe — auch mit anderen Eingabewerten — ohne Modell-Calls replayt (`cache: hit|stored|healed|rebuilt|stale|delta`). Umbenannte/übersetzte Elemente heilt eine Einzelentscheidung pro Schritt (`healed`, gemessen 3,7 s, danach wieder 2,6 s ohne Modell); nicht heilbare Schritte vollendet das Modell und das Template wird neu geschrieben (`rebuilt`). Schlägt der Check nach Replay fehl, wird der Eintrag gelöscht und NEEDS_AGENT gemeldet.
- `provider`: `{"name":"jev"}` (Standard) oder `{"name":"chat","model":"…","base_url":"…","api_key_env":"…"}` für jeden OpenAI-kompatiblen Endpoint (OpenAI/OpenRouter/Ollama/LM Studio), oder `{"name":"openai"}` für die OpenAI Decisions API. Env: `NITROLANE_PROVIDER/MODEL/BASE_URL`.
- `transitions`: `{"<Schrittnummer>":"<Check-Ausdruck>"}` — erwarteter Zustand nach genau dieser Aktion; Verletzung stoppt mit NEEDS_AGENT, auch wenn der Endzustand gut aussähe.
- Desktop-Läufe stellen das ursprüngliche Vordergrundfenster des Users am Ende wieder her. `nitrolane.py doctor` prüft die Maschine; `nitrolane_mcp.py` stellt `nitrolane_run`/`nitrolane_doctor` als MCP-Tools bereit.
- **Fleet** für mehrere Aufgaben in einem Aufruf: `nitrolane_fleet.py` mit `{"parallel":4,"tasks":[…]}` — Browser-Tabs parallel, Desktop-Aufgaben seriell (ein Vordergrund). Gemessen: 4 Wiki-Aufgaben 10,2 s statt 17,0 s seriell.
- **Recorder**: `nitrolane_record.py --title "<Fenster>" --seconds 30 --out wf.json --goal "…" --check "…"` zeichnet eine echte Demonstration auf (Klicks als Elementnamen, getippte Werte als Input-Variablen, Dropdown-Wahl als SET_VALUE) und installiert sie als Replay-Template; danach `nitrolane.py < wf.json` — ohne Modell-Calls, auch mit neuen Eingabewerten.
- **OCR-Notpfad** für reine Pixel-UIs: Desktop-Request mit `"ocr":{"text":"Start Mission","action":"click","check_text":"Mission Done"}`; UIA hat immer Vorrang, OCR greift nur, wenn kein Element gefunden wird.
- **Fremdes Chrome** (eingeloggte Session): `"cdp":"http://127.0.0.1:9222"` statt eigenem Profil — nur auf ausdrücklichen Auftrag, die Spur handelt dann als dieser Login.

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
- Reihenfolgen als `steps` (Pflicht: `check`): `"steps":["Click the clear button","Click 7","Click plus","Click 8","Click equals"]` — je Schritt genau eine Aktion, gemessen 3/3. „compute 7 plus 8“ als Ziel klickte 7, 8, Plus (0/3); Reihenfolge-Hinweise im Ziel halfen nicht (1/3, 0/3).
- Jeder Literalwert in `inputs`; im `goal` erwähnter Text wird nie getippt.
- Risiko-Wörter wirken auf ganze Wörter im Label, auch falsch-positiv: Checkbox „Send me product updates“ braucht `allowed_risks:["send"]`.
- Nicht für: Logins/2FA/Zahlung, Uploads, Drag&Drop, Canvas/Spiele, Cross-Origin-iframes, minimierte/gesperrte/elevated Fenster.

## Messwerte (Win 11, 2026-10-15, Battery 28 Läufe + 11 Feature-Läufe, jevify-geprüft)

38/39 korrekt (32 verifiziert erledigt, 6 korrekte Rückgaben, 0 Falsch-Erfolge, 0 Regelverstöße); einziger Fehlgriff: „7 plus 8“ als reines Ziel (mit `steps` 3/3). Laufzeit: Link/Artikel 1–3 s, Formular mit 6 Feldern 4,8–5,1 s, Notepad-Text 2,2 s, 7 Rechner-Klicks 6,5 s, zzgl. ~0,7 s Prozessstart und 0,5–1,5 s Seitenladen.

## Wartung

Battery: Fixture-Server `python -m http.server 8765 --bind 127.0.0.1` in `tests/pages`, dann `"$ARC" tests/battery.py` → `last_run.json`, mit der Rubrik in `battery.json` per jevify bewerten. Backend-Patches: `patches/README.md` (im Vendor-Clone als `NITROLANE_PATCHES.md`).
