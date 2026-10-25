# research/ — calibration work for this fork

Fork-only analysis code for ENTWICKLUNGSPLAN.md (phases 1–5). Python 3.9+, standard library only so far.

**Health data never goes into git.** Everything personal lives in `research/data/`, which is
gitignored, as are `*.sqlite`, `*.zip` and `.env` anywhere in the repo.

## Import a WHOOP export (Phase 1)

```bash
python3 -m research.importers.whoop_export ~/Downloads/my_whoop_data_2026_10_23.zip
```

Writes `research/data/whoop.sqlite` with the tables `cycles`, `sleeps`, `workouts`, `journal` and an
`imports` log. Works with German and English exports, ZIP or extracted folder. Column names follow
NOOP's own canonical keys (`recovery_score_pct`, `heart_rate_variability_ms`, …). Each timestamp is
stored twice, as `*_utc` and `*_local`. Re-importing a newer export upserts, so it is safe to repeat.

## Mark which strap recorded which day

The export does not say. Keep the periods in `research/device_periods.csv` (dates only, committed),
then:

```bash
python3 -m research.importers.device_periods
```

This adds the table `device_periods` and the view `cycles_with_device` (= `cycles` plus `device`).

## Report: data patterns + NOOP vs WHOOP (Phases 1–2)

```bash
pip install -r research/requirements.txt
(cd Tools/ScoreCompare && swift build -c release)   # NOOP's own scorer as a CLI
python3 -m research.compare.report
```

Writes `research/data/reports/report.html` (self-contained, readable on a phone) and `metrics.json`.
Both stay in the gitignored data folder, because they describe personal health data.

`Tools/ScoreCompare` runs the app's `ChargeBaselines` + `Baselines` + `RecoveryScorer` unchanged over
nightly WHOOP values, so the comparison measures NOOP's formula and nothing else. On Linux it needs the
snapshot-enabled SQLite described in ENTWICKLUNGSPLAN.md (Phase 0).

## Tests

Synthetic data only:

```bash
python3 -m unittest discover -s research/tests -t .
```
