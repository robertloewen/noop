# Entwicklungsplan: Eigener NOOP-Fork mit WHOOP-Kalibrierung

> Ablage: im Root des eigenen Forks (`DEIN-NAME/noop`).
> Claude Code: Diese Datei zuerst lesen, dann phasenweise abarbeiten. Status-Checkboxen aktuell halten.

---

## 1. Ziel

Ein eigener, privat genutzter Fork von [ryanbr/noop](https://github.com/ryanbr/noop) (iOS + macOS), der

1. **Updates von NOOP weiterhin sauber übernimmt** (Upstream-Sync),
2. **NOOPs Algorithmen (Recovery, Strain, HRV, Sleep) gegen die echten WHOOP-Scores prüft**,
3. **diese Algorithmen auf die eigenen Daten kalibriert** (WHOOP-API als Referenz),
4. **optisch angepasst** werden kann, ohne Merge-Chaos.

Nutzung ausschließlich **privat und nicht-kommerziell** (PolyForm Noncommercial 1.0.0).

---

## 2. Ausgangslage

| Punkt | Stand |
|---|---|
| Hardware | WHOOP 4.0 und WHOOP 5.0, zusammen ~2 Jahre getragen |
| WHOOP-Abo | aktiv → Developer API (OAuth2) nutzbar |
| Geräte | iPhone (Zielgerät), MacBook (Xcode-Build + Signierung) |
| NOOP-Support | WHOOP 4.0 voll (Rohdaten, History-Offload); WHOOP 5.0/MG nur Live-HR zuverlässig |
| Historische Daten | Nur WHOOP-Scores (CSV-Export / API); Strap speichert Rohdaten nur ~14 Tage |

### Wichtige technische Rahmenbedingungen

- **Cloud-Umgebung (Claude Code) ist Linux → kein Xcode, kein iOS-Build.**
  In der Cloud: Swift-Packages (`swift build` / `swift test`, sofern Linux-kompatibel), Python-Analyse, Skripte, Doku.
  Lokal auf dem MacBook: `xcodegen generate`, Xcode-Build, Signierung, Installation aufs iPhone.
- **Ein WHOOP-Strap kann nur an ein Gerät gebunden sein.** Für saubere Paralleldaten: 4.0 an NOOP, 5.0 an WHOOP-App.
- **Gesundheitsdaten nie ins Git committen.** Rohdaten, Exporte, API-Tokens bleiben außerhalb des Repos bzw. in `.gitignore`.

---

## 3. Repo-Struktur (Ergänzungen im Fork)

```
noop/
├── ENTWICKLUNGSPLAN.md           ← diese Datei
├── research/                     ← NEU: Analyse & Kalibrierung (Python)
│   ├── README.md
│   ├── requirements.txt
│   ├── whoop_api/                ← OAuth + Sync-Skript
│   ├── importers/                ← WHOOP-CSV, NOOP-Export
│   ├── compare/                  ← Vergleichsmetriken, Reports
│   ├── calibrate/                ← Parameter-Optimierung
│   └── data/                     ← in .gitignore! (lokale DB, Exporte)
├── Tools/ScoreCompare/           ← NEU: Swift-CLI, rechnet StrandAnalytics auf Inputs → JSON
└── Packages/StrandDesign/...     ← Design-Anpassungen (möglichst nur Tokens)
```

---

## 4. Phasen

### Phase 0: Fork & Infrastruktur
- [x] Fork von `ryanbr/noop` anlegen, `upstream` als Remote hinzufügen
  - Fork `robertloewen/noop` existiert (GitHub-Fork, **öffentlich**, Issues deaktiviert).
  - `upstream` ist nur ein lokales Remote, also pro Klon einmal einrichten (auch auf dem MacBook):
    `git remote add upstream https://github.com/ryanbr/noop.git && git fetch upstream`
- [x] Branch-Strategie: `main` = 1:1 Upstream, `custom` = eigene Änderungen (regelmäßig auf `main` rebasen)
- [ ] Eigene Bundle-ID + Apple-Team → lokal auf dem MacBook, **ohne Commit**
  - Nicht in `project.yml` eintragen: Das Repo liest `BUNDLE_ID_PREFIX` und `DEVELOPMENT_TEAM` aus der
    gitignorierten `Config/BundleIdSecrets.xcconfig` (Vorlage: `Config/BundleIdSecrets.example.xcconfig`,
    siehe `docs/IOS.md`). So entsteht kein Upstream-Konflikt, und die Werte überleben jedes `xcodegen generate`.
  - Ohne Apple Watch lässt sich die eingebettete Watch-App mit kostenloser Apple-ID nicht signieren.
    Statt `xcodegen generate` deshalb **`Tools/fork/generate-ios.sh`** nutzen: erzeugt das Projekt ohne
    Watch-Einbettung (aus einer gitignorierten Kopie `project.fork.yml`, `project.yml` bleibt unverändert)
    und übernimmt die in Xcode gewählte Team-ID einmalig nach `Config/BundleIdSecrets.xcconfig`.
- [x] GitHub Action: täglicher Upstream-Sync von `main` (Fehler bei Konflikt → Issue/Benachrichtigung) → `.github/workflows/upstream-sync.yml`
- [x] `.gitignore` um `research/data/`, `*.sqlite`, `*.zip`, `.env` erweitern
- [x] Prüfen: Welche Packages bauen unter Linux? (`cd Packages/StrandAnalytics && swift build && swift test`) → Ergebnis siehe unten

**Ergebnis:** Fork baut lokal auf dem MacBook, App läuft auf dem iPhone, Upstream-Sync funktioniert.

#### Upstream-Sync: einmalige Einrichtung (manuell in GitHub)
1. **Actions im Fork aktivieren** (Tab „Actions“ → „I understand my workflows, enable them“). In Forks sind
   Workflows standardmäßig aus.
   GitHub registriert Workflow-Dateien erst bei einem Push **nach** dem Aktivieren. Steht im Actions-Tab
   „No workflows found“, obwohl Dateien da sind, fehlt dieser Push noch (so geschehen am 2026-10-25).
2. ✅ **`custom` als Default-Branch setzen** (erledigt 2026-10-25) (Settings → General → Default branch). Geplante Workflows
   (`schedule`) laufen nur vom Default-Branch; die Action liegt nur auf `custom`, damit `main` 1:1 bleibt.
   Alternativ manuell über „Run workflow“ starten.
   Außerdem unter Settings → Actions → General: „Allow all actions …“ und *Workflow permissions* „Read and write“ (erledigt).
3. **Secret `UPSTREAM_SYNC_TOKEN`** anlegen: Fine-grained PAT, nur dieses Repo, Rechte *Contents* und
   *Workflows* (read/write). Ohne Workflows-Recht lehnt GitHub jeden Push ab, der Upstream-Änderungen an
   `.github/workflows/**` enthält – das passiert bei NOOP regelmäßig. Ohne Secret nutzt die Action
   `GITHUB_TOKEN` und schlägt dann fehl.
4. Optional **Issues aktivieren** (Settings → Features). Dann legt die Action bei Problemen ein Issue
   „Upstream sync needs attention“ an bzw. kommentiert das offene. Ohne Issues ist der fehlgeschlagene
   Lauf (plus GitHubs Fehler-Mail) die Benachrichtigung.

Was die Action macht (täglich 03:41 UTC): `main` per Fast-Forward auf `upstream/main` bringen (schlägt fehl,
wenn `main` eigene Commits hat) und danach `custom` probeweise auf `main` mergen, **ohne zu pushen**. Bei
Konflikt: Fehlschlag mit Liste der Konfliktdateien. Das Rebasen von `custom` bleibt Handarbeit.
Lokal getestet mit Wegwerf-Repos: sauberer Fast-Forward, Konflikt in `custom` und abweichendes `main`
werden jeweils korrekt erkannt.

Hinweis: Mit `main` kommen auch die Upstream-Workflows in den Fork (u. a. `prune-stale-branches.yml`
wöchentlich, löscht nur Branches gemergter/geschlossener PRs). Wer die nicht will, deaktiviert sie
einzeln im Actions-Tab statt die Dateien zu ändern.

#### Linux-Build-Check (2026-10-24, Ubuntu 24.04 x86_64, Swift 6.2.1)

| Package | `swift build` | `swift test` | Anmerkung |
|---|---|---|---|
| `Packages/WhoopProtocol` | ✅ | ✅ 816 Tests (1 Skip) | ohne Zusatz-Setup |
| `Packages/OuraProtocol` | ✅ | ✅ 267 Tests | ohne Zusatz-Setup |
| `Packages/PolarProtocol` | ✅ | ✅ 25 Tests | ohne Zusatz-Setup |
| `Packages/StrandAnalytics` | ✅ | ✅ 2143 Tests | braucht Snapshot-SQLite (s. u.) |
| `Packages/WhoopStore` | ✅ | ✅ 621 Tests | braucht Snapshot-SQLite |
| `Packages/NoopLocalAccess` | ✅* | ✅ 14 Tests | braucht Snapshot-SQLite |
| `Packages/StrandImport` | ❌ | ❌ | **Upstream-Bug**, s. u.; mit lokalem Fix: ✅ 327 Tests (1 Skip) |
| `Packages/StrandDesign` | ❌ | ❌ | SwiftUI, nur macOS (erwartet) |
| `Tools/SleepPSG` | ✅ | ✅ 33 Tests | |
| `Tools/Backfill` | ❌ | – | hängt an StrandImport; mit lokalem Fix ✅ (keine Tests) |
| `Tools/SleepBench` | ❌ | ❌ | `import SQLite3` ist Darwin-only |

\* ohne Snapshot-SQLite schlägt der Link-Schritt fehl (`undefined reference to sqlite3_snapshot_open`).

**Konsequenz für Phase 2:** `StrandAnalytics` baut und testet unter Linux vollständig →
`Tools/ScoreCompare` kann in der Cloud gebaut werden; der Python-Port-Fallback ist nicht nötig.

**Setup Snapshot-SQLite** (Rezept aus `docs/BUILD.md` → „Swift package tests on Linux“):
- `swift.org`-Toolchain entpacken; Systempakete laut `AGENTS.md` (waren im Container bereits da).
- In der Claude-Code-Cloud ist `sqlite.org` vom Proxy gesperrt. Ersatzquelle: das npm-Paket
  `better-sqlite3` (13.0.3) bündelt dieselbe Amalgamation 3.53.4 unter `package/deps/sqlite3/`.
  Achtung: Die Datei ist **nicht** byte-identisch zur sqlite.org-Version (SHA-256 weicht vom Wert in
  `docs/BUILD.md` ab, better-sqlite3 patcht). Für lokale Tests okay, für alles andere die Originalquelle nehmen.
- Bauen: `cc -O2 -shared -fPIC -DSQLITE_ENABLE_SNAPSHOT=1 sqlite3.c -o libsqlite3.so.0 -lpthread -lm`,
  dann `ln -s libsqlite3.so.0 libsqlite3.so`.
- Testen: `LD_LIBRARY_PATH=$DIR swift test -Xcc -I$DIR -Xlinker -L$DIR`.
- **Zusätzlich für `StrandImport`/`Backfill`:** ZIPFoundation holt zlib per pkg-config, SwiftPM setzt dabei
  `-L/usr/lib/x86_64-linux-gnu` **vor** das eigene `-L`, sodass die System-SQLite (ohne Snapshot) gewinnt.
  Workaround: eigene `zlib.pc` ohne `-L` (`Libs: -lz`) in `$DIR/pc` ablegen und `PKG_CONFIG_PATH=$DIR/pc` setzen.
  Das fehlt in `docs/BUILD.md`.

**Upstream-Bug `StrandImport`:** `Sources/StrandImport/XlsxSheet.swift` nutzt `XMLParser`, importiert aber
nicht `FoundationXML` (die Nachbardateien `GpxParser.swift`, `TcxParser.swift` usw. tun es per
`#if canImport(FoundationXML)`). Unter Linux bricht deshalb der Compile ab; `docs/BUILD.md` behauptet
noch „builds + tests“. Für den Test lokal geflickt, **nicht committet** (Upstream-Code bleibt unangetastet).
Der Fix sind drei Zeilen und gehört als PR an `ryanbr/noop`, nicht in `custom`.

### Phase 1: Datenbasis (historische WHOOP-Daten)
- [x] WHOOP-Datenexport anfordern (ZIP: `physiological_cycles.csv`, `sleeps.csv`, `workouts.csv`, `journal_entries.csv`)
- [x] Importer in `research/importers/` → lokale SQLite (`research/data/whoop.sqlite`) → `research/importers/whoop_export.py`, siehe `research/README.md`
- [x] Datenqualität: Lücken, Ausreißer, **Bruch beim Wechsel 4.0 → 5.0** markieren
- [x] Explorative Auswertung: Verteilungen, Korrelationen HRV / RHR / Schlaf / Recovery → `research/compare/report.py` (Teil 1)

**Ergebnis:** Saubere, versionierte Analyse-Datenbasis über ~2 Jahre.

#### Stand Import (Export vom 2026-10-23, deutsch)
- Zyklen 672 (Recovery-Werte 665) · Schlaf 677 (12 Nickerchen) · Trainings 318 · Logbuch 23 057 (44 Fragen)
- Zeitraum 2024-11-18 bis 2026-09-18; danach 34 Tage ohne Zyklen bis zum Exportdatum.
- Logbuch: 210 identische Doppelzeilen im Export, beim Import zusammengeführt.
- Ausreißer (> 4 MAD) bei Recovery/RHR/HRV fallen jeweils auf dieselben Tage → echte schlechte Nächte,
  keine Messfehler; nicht entfernen.
- Wechsel 4.0 → 5.0: laut Nutzer Nov./Dez. 2025. In den Daten am klarsten am **2025-12-07**: Tagesbelastung
  (12,7 → 8,8), Ø-Puls (75,7 → 71,0) und Energie fallen, obwohl Trainings zunehmen (9 → 10, 324 → 435 Min.),
  also eher Gerät als Verhalten. Schlafphasen bleiben gleich. Als Schätzung in `research/device_periods.csv`
  erfasst; genaues Datum (z. B. Bestellbestätigung) bei Gelegenheit nachtragen.
- 2026-09-18: 5.0 verloren. Seit Ende Oktober 2026 wieder ein 4.0, neues 5.0 bestellt → Start von Phase 4.

### Phase 2: Ebene 1 – Score-Logik prüfen (ohne Rohdaten)
- [x] `Tools/ScoreCompare`: Swift-CLI, die `RecoveryScorer` mit vorgegebenen Inputs (HRV, RHR, Atemfrequenz, Sleep Performance, Hauttemp.) aufruft → CSV
  - Kein Python-Port nötig: baut unter Linux (Snapshot-SQLite, s. Phase 0). Nutzt `ChargeBaselines` + `Baselines` + `RecoveryScorer` unverändert.
- [x] NOOP-Recovery mit **WHOOPs eigenen Inputs** füttern → mit WHOOP-Recovery vergleichen
- [x] Eigenes Nachbau-Modell der WHOOP-Recovery fitten (gleitende persönliche Baselines, logistische Funktion)
- [x] Getrennte Auswertung 4.0-Zeitraum / 5.0-Zeitraum
- [x] Report → `research/data/reports/report.html` (gitignored, persönliche Daten; Erzeugung: `python3 -m research.compare.report`)

**Ergebnis:** Wissen, wie nah NOOPs Formel an WHOOP ist und wie WHOOP vermutlich gewichtet.

#### Befunde Ebene 1 (Stand 2026-10-25, 662 Nächte, zeitlicher Split 70/30)
- NOOP wie ausgeliefert: MAE 11,8, Bias −9,6 (NOOP zu niedrig), r 0,92, Zonen gleich 68 %, κ 0,48.
  Kaum Unterschied 4.0 vs 5.0 (MAE 11,7 / 11,8). Der Fehler ist vor allem **Versatz + zu steile Kurve**:
  NOOP drückt schwache Nächte gegen 0.
- Nur die Logistik neu anpassen (NOOP-Gewichte bleiben), 30-Tage-Baseline: Test-MAE **4,6**, r 0,97, κ 0,77
  (a = 0,85, k = 0,84 statt App a = 0,32, k = 1,60). Erfüllt die Zielwerte aus Abschnitt 5.
- Freies Nachbau-Modell, 30-Tage-Baseline: Test-MAE 4,0, r 0,98, κ 0,81. HRV dominiert (~3/4 des Gewichts),
  Ruhepuls trägt neben HRV fast nichts bei, Schlafleistung ~1/8.
- Baseline-Fenster: 30 Tage ist bei allen Varianten am besten oder gleichauf; die App nutzt 21.
- **Kandidat für Phase 5/6:** nur Kurve (a, k) + Fensterlänge konfigurierbar machen. Kleinster Eingriff, größter Effekt.
  Offen: Ob der Effekt mit NOOPs *eigenen* Messwerten (Phase 4) genauso trägt, denn hier rechnet NOOP mit WHOOPs HRV/RHR.

### Phase 3: WHOOP-API-Sync
- [ ] App im WHOOP Developer Dashboard registrieren
- [ ] OAuth2-Flow mit Scopes `read:recovery read:sleep read:cycles read:workout offline`
- [ ] Token sicher speichern (`.env` / Keychain, nie committen), Refresh automatisieren
- [ ] Tägliches Sync-Skript → `research/data/whoop.sqlite` (idempotent, Upserts)
- [ ] Optional: Webhooks statt Polling
- [ ] **WHOOP API Terms prüfen** und Ergebnis hier notieren (Nutzung zur Kalibrierung, privat)

**Ergebnis:** Laufend aktuelle WHOOP-Referenzwerte.

### Phase 4: Ebene 2 – Paralleltragen (Rohdaten)
- [ ] Setup: **4.0 an NOOP** (Rohdaten), **5.0 an WHOOP-App** (Referenz)
  - **Regel: ein Band, eine App.** NOOP holt den Bandspeicher ab und bestätigt ihn dem Band (Trim-Cursor,
    `docs/BLE_REVERSE_ENGINEERING.md` → „Safe offload + trim“). Hängt dasselbe Band zusätzlich an der WHOOP-App,
    fehlen ihr Teile der Nacht. Am 2026-10-26 so passiert: WHOOP erkannte den Schlaf (21:42–8:24), Stress-Kurve
    mit Lücken, aber keine Schlafleistung und keine Recovery. Vor dem Umstecken das Band in der anderen App entkoppeln.
- [ ] Optional testen: 5.0 an WHOOP-App + NOOP liest Live-HR über Standard-BLE-HR-Profil (ohne Bond) – kommen R-R-Intervalle mit? Stabil über Nacht?
- [ ] NOOP-Rohdatenexport nutzen (siehe `docs/RAW_DATA_CAPTURE.md`) → Importer in `research/importers/`
- [ ] Tagesweise Zuordnung NOOP ↔ WHOOP (WHOOP-Cycles laufen nach Schlaf, nicht nach Kalendertag!)
- [ ] Mindestens 4 Wochen sammeln, für Schlaf eher 8+

**Ergebnis:** Gepaarter Datensatz Rohdaten → WHOOP-Scores.

### Phase 5: Kalibrierung
- [ ] Parameter in `StrandAnalytics` konfigurierbar machen (Config-Struct statt Konstanten) – **möglichst als eigene Datei / Extension**, um Upstream-Konflikte zu minimieren
- [ ] Kalibrier-Ziele:
  - **HRV:** Messfenster (letzter Tiefschlafzyklus vs. ganze Nacht), Artefaktfilter
  - **Recovery:** Gewichte HRV / RHR / Schlaf, Baseline-Fensterlänge, logistische Parameter
  - **Strain:** TRIMP-Skalierung auf 0–21, HRmax-Annahme
  - **Sleep:** Stager-Schwellen gegen WHOOP-Phasendauern (nur Summen pro Nacht)
- [ ] Optimierung (Least Squares / Bayesian) auf MAE zu WHOOP
- [ ] **Zeitlicher Train/Test-Split** (ältere Wochen trainieren, neueste testen) gegen Overfitting
- [ ] Report vorher/nachher

**Ergebnis:** Persönliches Parameter-Profil mit messbar kleinerer Abweichung.

### Phase 6: Integration in die App
- [ ] Kalibriertes Profil als Datei/Setting in die App laden
- [ ] Settings-Schalter „Persönliche Kalibrierung“ (Standard: aus → Original-NOOP-Verhalten)
- [ ] Optional: Anzeige der Abweichung zu WHOOP in einem Debug-/Experimental-Screen
- [ ] Lokal auf dem MacBook bauen, auf dem iPhone testen

### Phase 7: Optische Anpassungen
- [ ] Eigene Farbwelt/Fonts über **Design-Tokens** in `Packages/StrandDesign/` (z. B. `MyTheme.swift`)
- [ ] App-Name + Icon über `project.yml` / Asset-Katalog
- [ ] Größere UI-Änderungen (eigenes Dashboard) als **eigene Views**, an wenigen Stellen eingebunden
- [ ] Nach jedem Upstream-Sync visuell prüfen (NOOP entwickelt das Design aktiv weiter)

---

## 5. Erfolgskriterien & Metriken

| Größe | Metrik | Zielwert (vorläufig, nach Phase 2 anpassen) |
|---|---|---|
| Ruhepuls | MAE | < 2 bpm |
| HRV (RMSSD) | MAE, Bland-Altman | < 10 % Abweichung |
| Recovery | MAE, Pearson r | MAE < 10 Punkte, r > 0,8 |
| Recovery-Farbzone | Cohens Kappa | > 0,6 |
| Strain | MAE | < 1,5 |
| Schlafdauer gesamt | MAE | < 20 min |
| Schlafphasen | MAE je Phase | erst messen, dann Ziel setzen |

---

## 6. Risiken & offene Punkte

- **Linux-Kompatibilität** der Swift-Packages unklar → Phase 0 klärt das, Fallback Python-Port
- **WHOOP 5.0/MG** in NOOP nur teilweise dekodiert → Rohdaten-Vergleich primär mit 4.0
- **Zwei Straps = zwei Sensoren/Positionen** → zusätzliches Messrauschen einkalkulieren
- **WHOOP API Terms** → vor Phase 3 prüfen; kalibrierte Parameter nicht ungeprüft upstream (PR) einreichen
- **Overfitting** auf eine Person / kurze Zeiträume → zeitlicher Split, regelmäßig neu validieren
- **Datenschutz:** Gesundheitsdaten nur lokal bzw. in privatem, verschlüsseltem Speicher
- **Signierung:** Kostenlose Apple-ID → Neuinstallation alle 7 Tage; ggf. Developer Account

---

## 7. Arbeitsregeln für Claude Code

- Diese Datei vor jeder Session lesen; erledigte Punkte abhaken, Erkenntnisse unter der jeweiligen Phase ergänzen.
- Eigene Änderungen nur auf `custom`, nie direkt auf `main`.
- Upstream-Code möglichst nicht umschreiben – Erweiterungen in neue Dateien.
- Keine Gesundheitsdaten, Exporte oder Tokens committen.
- Nach jeder Code-Änderung: fertige **Commit-Summary (≤ 72 Zeichen) + Description** liefern.
- Bei Arbeiten, die Xcode/iOS-Build brauchen: klar markieren „lokal auf dem MacBook ausführen“ inkl. Befehle.

---

## 8. Startprompt für die erste Claude-Code-Session

```
Lies ENTWICKLUNGSPLAN.md. Starte mit Phase 0:
1. Prüfe Remotes und richte upstream (ryanbr/noop) ein, falls nötig.
2. Lege den Branch "custom" an.
3. Erweitere .gitignore um research/data/, *.sqlite, *.zip, .env.
4. Erstelle eine GitHub Action für den täglichen Upstream-Sync von main.
5. Teste, welche Swift-Packages unter Linux bauen und testen (swift build / swift test),
   und dokumentiere das Ergebnis in Phase 0 dieser Datei.
Gib am Ende Commit-Summary und Description aus.
```
