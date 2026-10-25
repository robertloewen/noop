"""Phase 1 + Phase 2 (Ebene 1) report: WHOOP data patterns, and NOOP's recovery formula vs WHOOP.

Usage (from the repo root, after the importers ran):
    python3 -m research.compare.report [--db research/data/whoop.sqlite] [--scorecompare PATH] [--out DIR]

Needs numpy, scipy, matplotlib (research/requirements.txt) and the ScoreCompare binary
(`cd Tools/ScoreCompare && swift build -c release`). Writes a self-contained HTML page plus a JSON of
the numbers to research/data/reports/ (gitignored: the report is personal health data).

Ebene 1 feeds NOOP's shipped Charge scorer WHOOP's own nightly inputs (HRV, resting HR, respiration,
sleep performance, skin temperature), so any difference to WHOOP's recovery comes from the formula and
its baselines, never from a different sensor or HRV algorithm.
"""

from __future__ import annotations

import argparse
import base64
import csv
import html
import io
import json
import math
import sqlite3
import subprocess
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy import optimize, stats  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "research" / "data" / "whoop.sqlite"
DEFAULT_BIN = ROOT / "Tools" / "ScoreCompare" / ".build" / "release" / "scorecompare"
DEFAULT_OUT = ROOT / "research" / "data" / "reports"

WINDOWS = [14, 21, 30, 45, 60, 90]  # 21 = what the app ships
Z_COLS = ["z_hrv", "z_rhr", "z_resp", "z_sleep", "z_skin"]
TRAIN_FRACTION = 0.7


# ── data ────────────────────────────────────────────────────────────────────────────────────────

def load_nights(db_path: Path) -> list[dict]:
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    has_view = db.execute("SELECT 1 FROM sqlite_master WHERE name='cycles_with_device'").fetchone()
    table = "cycles_with_device" if has_view else "cycles"
    rows = db.execute(f"""
        SELECT substr(wake_onset_local, 1, 10) AS day, cycle_start_utc, recovery_score_pct AS whoop,
               heart_rate_variability_ms AS hrv, resting_heart_rate_bpm AS rhr, respiratory_rate_rpm AS resp,
               sleep_performance_pct AS sleep_perf, skin_temp_celsius AS skin, blood_oxygen_pct AS spo2,
               asleep_duration_min AS asleep, day_strain AS strain,
               {'device' if has_view else 'NULL AS device'}
        FROM {table}
        WHERE wake_onset_local IS NOT NULL
        ORDER BY day""").fetchall()
    out = [dict(r) for r in rows]
    # Strain of the PREVIOUS cycle: the load that precedes tonight's sleep.
    for prev, cur in zip(out, out[1:]):
        cur["prev_strain"] = prev["strain"]
    if out:
        out[0]["prev_strain"] = None
    db.close()
    return out


def load_journal(db_path: Path) -> list[tuple[str, str, int]]:
    db = sqlite3.connect(db_path)
    rows = db.execute("SELECT cycle_start_utc, question_text, answered_yes FROM journal "
                      "WHERE answered_yes IS NOT NULL").fetchall()
    db.close()
    return rows


def run_scorecompare(binary: Path, nights: list[dict], window: int) -> dict[str, dict]:
    def cell(v, scale=1.0):
        return "" if v is None else repr(v * scale)
    lines = ["day,hrv,rhr,resp,sleep_perf,skin_temp_c"]
    lines += [",".join([n["day"], cell(n["hrv"]), cell(n["rhr"]), cell(n["resp"]),
                        cell(n["sleep_perf"], 0.01), cell(n["skin"])]) for n in nights]
    res = subprocess.run([str(binary), "--window", str(window)], input="\n".join(lines) + "\n",
                         capture_output=True, text=True, check=True)
    out = {}
    for r in csv.DictReader(io.StringIO(res.stdout)):
        out[r["day"]] = {k: (float(v) if v not in ("", None) and k != "day" else None) for k, v in r.items()}
    return out


# ── metrics ─────────────────────────────────────────────────────────────────────────────────────

def band(score: float) -> int:
    return 0 if score < 34 else (1 if score < 67 else 2)


def metrics(pred: np.ndarray, truth: np.ndarray) -> dict:
    if len(pred) < 3:
        return {"n": int(len(pred))}
    err = pred - truth
    pb, tb = np.array([band(p) for p in pred]), np.array([band(t) for t in truth])
    return {
        "n": int(len(pred)),
        "mae": float(np.mean(np.abs(err))),
        "bias": float(np.mean(err)),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "pearson_r": float(stats.pearsonr(pred, truth)[0]),
        "spearman_r": float(stats.spearmanr(pred, truth)[0]),
        "band_agreement": float(np.mean(pb == tb)),
        "kappa": cohen_kappa(pb, tb),
    }


def cohen_kappa(a: np.ndarray, b: np.ndarray, k: int = 3) -> float:
    po = float(np.mean(a == b))
    pe = sum(float(np.mean(a == c)) * float(np.mean(b == c)) for c in range(k))
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


# ── replica model ───────────────────────────────────────────────────────────────────────────────

def replica_predict(params: np.ndarray, Z: np.ndarray) -> np.ndarray:
    return 100.0 / (1.0 + np.exp(-(params[0] + Z @ params[1:])))


def fit_replica(Z: np.ndarray, y: np.ndarray) -> np.ndarray:
    x0 = np.zeros(Z.shape[1] + 1)
    res = optimize.least_squares(lambda p: replica_predict(p, Z) - y, x0, loss="soft_l1", f_scale=10.0)
    return res.x


NOOP_WEIGHTS = {"z_hrv": 0.55, "z_rhr": 0.20, "z_resp": 0.05, "z_sleep": 0.15, "z_skin": 0.05}
APP_CURVE = (1.6 * 0.20, 1.6)  # RecoveryScorer: 100 / (1 + exp(-k (z - z0))) = sigmoid(-k*z0 + k*z), k=1.6, z0=-0.2


def noop_composite(r: dict) -> float:
    """NOOP's renormalised weighted z, from the exported terms (pinned against the scorer in Swift tests)."""
    terms = [(r[k], w) for k, w in NOOP_WEIGHTS.items() if r.get(k) is not None]
    return sum(z * w for z, w in terms) / sum(w for _, w in terms)


def curve_predict(p, z: np.ndarray) -> np.ndarray:
    return 100.0 / (1.0 + np.exp(-(p[0] + p[1] * z)))


def fit_curve(z: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Keep NOOP's weights, refit only the logistic: offset and steepness."""
    return optimize.least_squares(lambda p: curve_predict(p, z) - y, list(APP_CURVE),
                                  loss="soft_l1", f_scale=10.0).x


def design(rows: list[dict]) -> np.ndarray:
    return np.array([[r[c] if r.get(c) is not None else 0.0 for c in Z_COLS] for r in rows])


# ── journal ─────────────────────────────────────────────────────────────────────────────────────

def journal_effects(nights: list[dict], journal: list[tuple[str, str, int]], min_each: int = 10) -> list[dict]:
    """Mean WHOOP recovery of the SAME cycle with vs without a 'yes' (the export attaches answers to
    the cycle whose recovery they explain; checked on alcohol, which only moves the same cycle)."""
    rec = {n["cycle_start_utc"]: n["whoop"] for n in nights if n["whoop"] is not None}
    by_q: dict[str, tuple[list, list]] = {}
    for cyc, q, yes in journal:
        r = rec.get(cyc)
        if r is None:
            continue
        by_q.setdefault(q, ([], []))[0 if yes else 1].append(r)
    out = []
    for q, (y, n) in by_q.items():
        if len(y) < min_each or len(n) < min_each:
            continue
        t = stats.ttest_ind(y, n, equal_var=False)
        out.append({"question": q, "n_yes": len(y), "n_no": len(n), "mean_yes": float(np.mean(y)),
                    "mean_no": float(np.mean(n)), "effect": float(np.mean(y) - np.mean(n)), "p": float(t.pvalue)})
    # Benjamini-Hochberg across all questions tested.
    out.sort(key=lambda e: e["p"])
    m = len(out)
    prev = 1.0
    for i in range(m - 1, -1, -1):
        prev = min(prev, out[i]["p"] * m / (i + 1))
        out[i]["q"] = prev
    out.sort(key=lambda e: e["effect"])
    return out


# ── plotting ────────────────────────────────────────────────────────────────────────────────────

INK, MUTED, GRID = "#1f2328", "#6e7781", "#d0d7de"
C_WHOOP, C_NOOP, C_FIT = "#0969da", "#cf222e", "#1a7f37"


def fig_to_img(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return f'<img alt="" src="data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}">'


def style(ax):
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=8)


def plot_timeseries(days, whoop, noop, fit, switch_day):
    fig, ax = plt.subplots(figsize=(8, 3.2))
    x = [date.fromisoformat(d) for d in days]

    def roll(v, k=7):
        v = np.array(v, dtype=float)
        return np.convolve(np.nan_to_num(v), np.ones(k) / k, mode="same")
    ax.plot(x, roll(whoop), color=C_WHOOP, label="WHOOP", linewidth=1.6)
    ax.plot(x, roll(noop), color=C_NOOP, label="NOOP (wie ausgeliefert)", linewidth=1.2)
    if fit is not None:
        ax.plot(x, roll(fit), color=C_FIT, label="Nachbau-Modell", linewidth=1.2, linestyle="--")
    if switch_day:
        ax.axvline(date.fromisoformat(switch_day), color=MUTED, linestyle=":", linewidth=1)
        ax.text(date.fromisoformat(switch_day), 3, " 4.0 → 5.0", color=MUTED, fontsize=8)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Recovery (7-Tage-Mittel)", fontsize=8, color=MUTED)
    ax.legend(fontsize=8, frameon=False, loc="lower left", ncol=3)
    style(ax)
    return fig_to_img(fig)


def plot_scatter(pairs: dict[str, tuple[np.ndarray, np.ndarray]]):
    fig, axes = plt.subplots(1, len(pairs), figsize=(4 * len(pairs), 3.6), squeeze=False)
    for ax, (title, (pred, truth)) in zip(axes[0], pairs.items()):
        ax.scatter(truth, pred, s=7, alpha=0.45, color=C_NOOP, linewidths=0)
        ax.plot([0, 100], [0, 100], color=MUTED, linewidth=0.8)
        for b in (34, 67):
            ax.axhline(b, color=GRID, linewidth=0.6)
            ax.axvline(b, color=GRID, linewidth=0.6)
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.set_xlabel("WHOOP", fontsize=8, color=MUTED)
        ax.set_ylabel(title, fontsize=8, color=MUTED)
        style(ax)
    return fig_to_img(fig)


def plot_effects(effects: list[dict]):
    eff = [e for e in effects if e["q"] < 0.2] or effects[:8]
    fig, ax = plt.subplots(figsize=(7.5, 0.38 * len(eff) + 0.8))
    labels = [e["question"].rstrip("?")[:48] for e in eff]
    vals = [e["effect"] for e in eff]
    ax.barh(labels, vals, color=[C_NOOP if v < 0 else C_FIT for v in vals])
    ax.axvline(0, color=MUTED, linewidth=0.8)
    ax.set_xlabel("Unterschied Recovery (Punkte), Ja minus Nein", fontsize=8, color=MUTED)
    ax.tick_params(axis="y", labelsize=8)
    style(ax)
    return fig_to_img(fig)


def plot_corr(nights: list[dict]):
    cols = [("whoop", "Recovery"), ("hrv", "HRV"), ("rhr", "Ruhepuls"), ("resp", "Atemfreq."),
            ("sleep_perf", "Schlafleistung"), ("asleep", "Schlafdauer"), ("skin", "Hauttemp."),
            ("spo2", "SpO2"), ("prev_strain", "Belastung Vortag")]
    data = {k: np.array([n[k] if n.get(k) is not None else np.nan for n in nights], dtype=float) for k, _ in cols}
    m = np.zeros((len(cols), len(cols)))
    for i, (a, _) in enumerate(cols):
        for j, (b, _) in enumerate(cols):
            ok = ~np.isnan(data[a]) & ~np.isnan(data[b])
            m[i, j] = stats.spearmanr(data[a][ok], data[b][ok])[0]
    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(m, cmap="RdBu", vmin=-1, vmax=1)
    ax.set_xticks(range(len(cols)), [c[1] for c in cols], rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(cols)), [c[1] for c in cols], fontsize=8)
    for i in range(len(cols)):
        for j in range(len(cols)):
            ax.text(j, i, f"{m[i, j]:.2f}", ha="center", va="center", fontsize=6.5,
                    color="white" if abs(m[i, j]) > 0.5 else INK)
    fig.colorbar(im, ax=ax, shrink=0.75)
    return fig_to_img(fig), {c[1]: dict(zip([d[1] for d in cols], map(float, m[i]))) for i, c in enumerate(cols)}


# ── report ──────────────────────────────────────────────────────────────────────────────────────

def fmt(v, d=1):
    return "–" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{d}f}"


def metrics_table(rows: list[tuple[str, dict]]) -> str:
    head = "<tr><th></th><th>n</th><th>MAE</th><th>Bias</th><th>r</th><th>Zonen gleich</th><th>κ</th></tr>"
    body = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{m.get('n', 0)}</td><td>{fmt(m.get('mae'))}</td>"
        f"<td>{fmt(m.get('bias'))}</td><td>{fmt(m.get('pearson_r'), 2)}</td>"
        f"<td>{fmt(100 * m['band_agreement'], 0) + ' %' if 'band_agreement' in m else '–'}</td>"
        f"<td>{fmt(m.get('kappa'), 2)}</td></tr>" for name, m in rows)
    return f"<table>{head}{body}</table>"


CSS = """
:root{--ink:#1f2328;--muted:#6e7781;--line:#d0d7de;--bg:#ffffff;--card:#f6f8fa}
@media (prefers-color-scheme:dark){:root{--ink:#e6edf3;--muted:#9da7b3;--line:#30363d;--bg:#0d1117;--card:#161b22}
 img{background:#fff;border-radius:6px}}
body{font:15px/1.5 -apple-system,system-ui,sans-serif;color:var(--ink);background:var(--bg);margin:0;padding:16px;max-width:860px}
h1{font-size:22px;margin:.2em 0}h2{font-size:18px;margin-top:2em;border-bottom:1px solid var(--line);padding-bottom:4px}
h3{font-size:15px;margin-top:1.4em}p,li{color:var(--ink)}small,.muted{color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:13px;margin:.6em 0;display:block;overflow-x:auto}
th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left;white-space:normal}
img{max-width:100%;height:auto;margin:.5em 0}
.box{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:1em 0}
"""


def build(db_path: Path, binary: Path, out_dir: Path) -> Path:
    nights = load_nights(db_path)
    journal = load_journal(db_path)
    scored = {w: run_scorecompare(binary, nights, w) for w in WINDOWS}

    switch_day = next((n["day"] for n in nights if n.get("device") == "WHOOP 5.0"), None)
    days = [n["day"] for n in nights]
    whoop = {n["day"]: n["whoop"] for n in nights}
    device = {n["day"]: n.get("device") or "unbekannt" for n in nights}

    # Ebene 1: NOOP as shipped (21-day window), three variants.
    s21 = scored[21]
    eval_days = [d for d in days if whoop[d] is not None and s21[d]["noop_full"] is not None]
    truth = np.array([whoop[d] for d in eval_days])
    variants = {"noop_full": "NOOP komplett", "noop_no_sleep": "NOOP ohne Schlafterm", "noop_hrv_rhr": "NOOP nur HRV+Ruhepuls"}
    shipped = {}
    for key, name in variants.items():
        pred = np.array([s21[d][key] for d in eval_days])
        shipped[name] = metrics(pred, truth)
        for dev in sorted({device[d] for d in eval_days}):
            idx = [i for i, d in enumerate(eval_days) if device[d] == dev]
            shipped[f"{name} · {dev}"] = metrics(pred[idx], truth[idx])

    # Window sweep for the shipped formula, and the replica fit per window (time split).
    split = int(len(eval_days) * TRAIN_FRACTION)
    train_days, test_days = eval_days[:split], eval_days[split:]
    sweep = {}
    fits = {}
    for w in WINDOWS:
        s = scored[w]
        ok = [d for d in eval_days if s[d]["noop_full"] is not None]
        sweep[w] = metrics(np.array([s[d]["noop_full"] for d in ok]), np.array([whoop[d] for d in ok]))
        tr = [d for d in train_days if s[d]["noop_full"] is not None]
        te = [d for d in test_days if s[d]["noop_full"] is not None]
        params = fit_replica(design([s[d] for d in tr]), np.array([whoop[d] for d in tr]))
        fits[w] = {
            "params": params,
            "train": metrics(replica_predict(params, design([s[d] for d in tr])), np.array([whoop[d] for d in tr])),
            "test": metrics(replica_predict(params, design([s[d] for d in te])), np.array([whoop[d] for d in te])),
        }
        zc_tr = np.array([noop_composite(s[d]) for d in tr])
        zc_te = np.array([noop_composite(s[d]) for d in te])
        cp = fit_curve(zc_tr, np.array([whoop[d] for d in tr]))
        fits[w]["curve"] = {"params": cp, "test": metrics(curve_predict(cp, zc_te), np.array([whoop[d] for d in te]))}
    best_w = min(fits, key=lambda w: fits[w]["test"]["mae"])
    best = fits[best_w]
    sb = scored[best_w]
    fit_series = {d: (float(replica_predict(best["params"], design([sb[d]]))[0]) if sb[d]["noop_full"] is not None else None)
                  for d in days}

    # Implied relative weights of the replica (logit-scale coefficients, normalised to sum 1 in |.|).
    coef = best["params"][1:]
    rel = np.abs(coef) / np.sum(np.abs(coef))
    term_names = ["HRV", "Ruhepuls", "Atemfrequenz", "Schlafleistung", "Hauttemperatur"]
    noop_w = [0.55, 0.20, 0.05, 0.15, 0.05]

    effects = journal_effects(nights, journal)
    corr_img, corr = plot_corr(nights)

    # ── HTML ──
    n_rec = sum(1 for n in nights if n["whoop"] is not None)
    first, last = days[0], max(d for d in days if whoop[d] is not None)
    shipped_rows = [(k, v) for k, v in shipped.items()]
    sweep_rows = [(f"{w} Tage{' (App)' if w == 21 else ''}", sweep[w]) for w in WINDOWS]
    fit_rows = [(f"{w} Tage · Test", fits[w]["test"]) for w in WINDOWS]
    curve_rows = [(f"{w} Tage · Test", fits[w]["curve"]["test"]) for w in WINDOWS]
    curve_best_w = min(fits, key=lambda w: fits[w]["curve"]["test"]["mae"])
    cb = fits[curve_best_w]["curve"]
    weights_rows = "".join(
        f"<tr><td>{n}</td><td>{fmt(100 * nw, 0)} %</td><td>{fmt(100 * r, 0)} %</td><td>{fmt(c, 2)}</td></tr>"
        for n, nw, r, c in zip(term_names, noop_w, rel, coef))
    eff_rows = "".join(
        f"<tr><td>{html.escape(e['question'])}</td><td>{e['n_yes']}/{e['n_yes'] + e['n_no']}</td>"
        f"<td>{fmt(e['effect'])}</td><td>{'✓' if e['q'] < 0.05 else ('~' if e['q'] < 0.2 else '')}</td></tr>"
        for e in effects)
    full = shipped["NOOP komplett"]
    page = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>WHOOP vs NOOP</title><style>{CSS}</style></head><body>
<h1>WHOOP-Daten &amp; NOOP-Recovery</h1>
<p class="muted">{n_rec} Nächte mit WHOOP-Recovery, {first} bis {last}. Persönlicher Bericht, nicht teilen.</p>

<div class="box"><b>Kurz gesagt</b><ul>
<li>NOOPs Formel, gefüttert mit WHOOPs eigenen Messwerten, liegt im Mittel <b>{fmt(full['mae'])} Punkte</b> neben WHOOP
(Korrelation r = {fmt(full['pearson_r'], 2)}, gleiche Farbzone an {fmt(100 * full['band_agreement'], 0)} % der Tage).</li>
<li>Der Abstand ist vor allem ein <b>Versatz</b> (NOOP im Mittel {fmt(-full['bias'])} Punkte niedriger). Nur NOOPs Kurve
anzupassen, ohne die Gewichte anzurühren, bringt die Abweichung auf <b>{fmt(cb['test']['mae'])} Punkte</b> (Baseline {curve_best_w} Tage).</li>
<li>Ein an deine Daten angepasstes Nachbau-Modell schafft auf den <b>neuesten {len(test_days)} Tagen</b> (nicht zum Anpassen benutzt)
<b>{fmt(best['test']['mae'])} Punkte</b> Abweichung, mit einer Baseline über <b>{best_w} Tage</b>.</li>
<li>Größter Logbuch-Effekt: <b>{html.escape(effects[0]['question'].rstrip('?'))}</b> ({fmt(effects[0]['effect'])} Punkte).</li>
</ul></div>

<h2>Teil 1 · Deine Daten (Phase 1)</h2>
<h3>Zusammenhänge zwischen den Messwerten</h3>
<p>Rangkorrelation (Spearman) pro Nacht. Blau = steigen gemeinsam, rot = gegenläufig.</p>
{corr_img}
<p>Recovery hängt mit HRV r = {fmt(corr['Recovery']['HRV'], 2)} und mit dem Ruhepuls r = {fmt(corr['Recovery']['Ruhepuls'], 2)} zusammen;
mit der Schlafleistung r = {fmt(corr['Recovery']['Schlafleistung'], 2)}, mit der Belastung des Vortags r = {fmt(corr['Recovery']['Belastung Vortag'], 2)}.</p>

<h3>Logbuch: was geht mit besserer oder schlechterer Recovery einher?</h3>
<p>Mittlere Recovery an Tagen mit „Ja“ minus Tage mit „Nein“, für Fragen mit je mindestens 10 Antworten.
✓ = statistisch belastbar nach Korrektur für {len(effects)} gleichzeitige Tests, ~ = Tendenz.
<b>Das sind Zusammenhänge, keine Ursachen:</b> Alkohol fällt z. B. oft aufs Wochenende, mit anderem Schlafrhythmus.</p>
{plot_effects(effects)}
<table><tr><th>Frage</th><th>Ja</th><th>Effekt</th><th></th></tr>{eff_rows}</table>

<h2>Teil 2 · NOOP vs WHOOP (Phase 2, Ebene 1)</h2>
<p>NOOPs Recovery-Code („Charge“, unverändert aus der App) wird mit <b>WHOOPs</b> nächtlichen Werten gefüttert:
HRV, Ruhepuls, Atemfrequenz, Schlafleistung, Hauttemperatur. Unterschiede kommen also nur aus der Formel und ihren
Baselines, nicht aus Sensoren. Einziger Ersatz: In der App fließt NOOPs eigener Ruhe-Score ein, hier WHOOPs Schlafleistung.</p>
{plot_timeseries(days, [whoop[d] for d in days], [s21[d]['noop_full'] for d in days], [fit_series[d] for d in days], switch_day)}

<h3>Wie nah ist NOOP, so wie ausgeliefert?</h3>
<p class="muted">MAE = mittlere Abweichung in Punkten · Bias = NOOP minus WHOOP im Mittel · r = Korrelation ·
Zonen gleich = rot/gelb/grün identisch · κ = Zonen-Übereinstimmung jenseits von Zufall (0,6+ = gut).</p>
{metrics_table(shipped_rows)}
{plot_scatter({'NOOP komplett': (np.array([s21[d]['noop_full'] for d in eval_days]), truth),
               f'Nachbau ({best_w} Tage)': (np.array([fit_series[d] for d in eval_days]), truth)})}

<h3>Baseline-Fenster</h3>
<p>Die App vergleicht jede Nacht mit den letzten 21 Tagen. So würde NOOPs Formel mit anderen Fensterlängen abschneiden:</p>
{metrics_table(sweep_rows)}

<h3>Kleinste Korrektur: nur NOOPs Kurve verschieben</h3>
<p>NOOPs Gewichte bleiben, nur die logistische Kurve (Versatz und Steilheit, zwei Zahlen) wird an die älteren Tage
angepasst. Bestes Fenster: <b>{curve_best_w} Tage</b>, Kurve a = {fmt(cb['params'][0], 2)}, k = {fmt(cb['params'][1], 2)}
(App: a = {fmt(APP_CURVE[0], 2)}, k = {fmt(APP_CURVE[1], 2)}). Das ist der einfachste Kandidat für Phase 5/6.</p>
{metrics_table(curve_rows)}

<h3>Nachbau-Modell: wie gewichtet WHOOP vermutlich?</h3>
<p>Gleiche Bausteine wie NOOP (Abweichung von der persönlichen Baseline je Messwert, logistische Kurve), aber
Gewichte und Kurve an die ältesten {len(train_days)} Tage angepasst und auf den neuesten {len(test_days)} Tagen geprüft.</p>
{metrics_table(fit_rows)}
<table><tr><th>Messwert</th><th>NOOP-Gewicht</th><th>Nachbau ({best_w} Tage)</th><th>Koeffizient</th></tr>{weights_rows}</table>
<p class="muted">Relative Gewichte = Anteil am Betrag der Koeffizienten. Ein negativer Koeffizient heißt: der Messwert
wirkt im Nachbau entgegen NOOPs Annahme.</p>

<h3>Einordnung</h3>
<ul>
<li>Zielwert laut Plan: MAE &lt; 10 Punkte, r &gt; 0,8, κ &gt; 0,6.</li>
<li>Das Nachbau-Modell ist eine Beschreibung von WHOOPs Verhalten auf deinen Daten, kein Original-Algorithmus.</li>
<li>Gerätewechsel 4.0 → 5.0 ist geschätzt ({switch_day or '–'}); Zeilen „· WHOOP 4.0/5.0“ oben trennen die Zeiträume.</li>
</ul>
</body></html>"""
    out_dir.mkdir(parents=True, exist_ok=True)
    page_path = out_dir / "report.html"
    page_path.write_text(page, encoding="utf-8")
    (out_dir / "metrics.json").write_text(json.dumps({
        "shipped": shipped, "window_sweep": {str(k): v for k, v in sweep.items()},
        "replica": {str(w): {"params": list(map(float, f["params"])), "train": f["train"], "test": f["test"],
                             "curve_params": list(map(float, f["curve"]["params"])), "curve_test": f["curve"]["test"]}
                    for w, f in fits.items()},
        "best_window": best_w, "journal_effects": effects, "correlations": corr,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return page_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--scorecompare", type=Path, default=DEFAULT_BIN)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    print("Report:", build(args.db, args.scorecompare, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
