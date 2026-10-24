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
- [ ] Fork von `ryanbr/noop` anlegen, `upstream` als Remote hinzufügen
- [ ] Branch-Strategie: `main` = 1:1 Upstream, `custom` = eigene Änderungen (regelmäßig auf `main` rebasen)
- [ ] Eigene Bundle-ID + Apple-Team in `project.yml` – **als einzelner, isolierter Commit**
- [ ] GitHub Action: täglicher Upstream-Sync von `main` (Fehler bei Konflikt → Issue/Benachrichtigung)
- [ ] `.gitignore` um `research/data/`, `*.sqlite`, `*.zip`, `.env` erweitern
- [ ] Prüfen: Welche Packages bauen unter Linux? (`cd Packages/StrandAnalytics && swift build && swift test`) → Ergebnis hier dokumentieren

**Ergebnis:** Fork baut lokal auf dem MacBook, App läuft auf dem iPhone, Upstream-Sync funktioniert.

### Phase 1: Datenbasis (historische WHOOP-Daten)
- [ ] WHOOP-Datenexport anfordern (ZIP: `physiological_cycles.csv`, `sleeps.csv`, `workouts.csv`, `journal_entries.csv`)
- [ ] Importer in `research/importers/` → lokale SQLite (`research/data/whoop.sqlite`)
- [ ] Datenqualität: Lücken, Ausreißer, **Bruch beim Wechsel 4.0 → 5.0** markieren
- [ ] Explorative Auswertung: Verteilungen, Korrelationen HRV / RHR / Schlaf / Recovery

**Ergebnis:** Saubere, versionierte Analyse-Datenbasis über ~2 Jahre.

### Phase 2: Ebene 1 – Score-Logik prüfen (ohne Rohdaten)
- [ ] `Tools/ScoreCompare`: Swift-CLI, die `RecoveryScorer` mit vorgegebenen Inputs (HRV, RHR, Atemfrequenz, Sleep Performance, Hauttemp.) aufruft → JSON
  - Fallback, falls Linux-Build scheitert: Logik 1:1 in Python portieren, gegen Swift-Tests verifizieren
- [ ] NOOP-Recovery mit **WHOOPs eigenen Inputs** füttern → mit WHOOP-Recovery vergleichen
- [ ] Eigenes Nachbau-Modell der WHOOP-Recovery fitten (gleitende persönliche Baselines, logistische Funktion)
- [ ] Getrennte Auswertung 4.0-Zeitraum / 5.0-Zeitraum
- [ ] Report (`research/compare/report_ebene1.md` + Grafiken)

**Ergebnis:** Wissen, wie nah NOOPs Formel an WHOOP ist und wie WHOOP vermutlich gewichtet.

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
