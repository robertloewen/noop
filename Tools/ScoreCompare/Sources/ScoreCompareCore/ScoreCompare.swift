import Foundation
import StrandAnalytics

/// One night of summary inputs, as a WHOOP export (or any other source) reports them.
public struct Night: Equatable, Sendable {
    public let day: String          // yyyy-MM-dd, the local day the night is scored on
    public let hrv: Double?         // RMSSD, ms
    public let rhr: Double?         // bpm
    public let resp: Double?        // breaths/min
    public let sleepPerf: Double?   // 0...1
    public let skinTempC: Double?   // absolute nightly skin temperature, °C

    public init(day: String, hrv: Double?, rhr: Double?, resp: Double?, sleepPerf: Double?, skinTempC: Double?) {
        self.day = day; self.hrv = hrv; self.rhr = rhr; self.resp = resp
        self.sleepPerf = sleepPerf; self.skinTempC = skinTempC
    }
}

/// The scored night: NOOP's Charge in three variants plus the baselines and per-term z-scores behind it.
public struct ScoredNight: Equatable, Sendable {
    public let day: String
    /// All terms the input supports (HRV, RHR, resp, sleep, skin temp): the app's strap path, with the
    /// supplied sleep performance standing in for NOOP's own Rest score.
    public let full: Double?
    /// The same without the sleep term, so the stand-in's effect can be measured on its own.
    public let noSleep: Double?
    /// HRV and resting HR only, the minimal path (as `WatchRecovery` scores).
    public let hrvRhr: Double?
    public let hrvBase: BaselineState
    public let rhrBase: BaselineState
    public let respBase: BaselineState
    public let skinBase: BaselineState
    public let skinDev: Double?
    /// Term z-scores in the scorer's orientation (higher is better), nil when the term is dropped.
    public let zHrv: Double?
    public let zRhr: Double?
    public let zResp: Double?
    public let zSleep: Double?
    public let zSkin: Double?
}

public enum ScoreCompare {

    /// Score every night against baselines anchored on that night, the way the app scores "today":
    /// `ChargeBaselines.history` takes the `windowDays` calendar days up to and including the anchor,
    /// and `Baselines.foldHistory` folds them. No recalibration epoch (0) and no imported seed rows,
    /// because the input is treated as the wearer's own nights.
    public static func score(_ nights: [Night], windowDays: Int = ChargeBaselines.windowDays) -> [ScoredNight] {
        let sorted = nights.sorted { $0.day < $1.day }
        let series: (KeyPath<Night, Double?>) -> [(day: String, value: Double?)] = { kp in
            sorted.map { (day: $0.day, value: $0[keyPath: kp]) }
        }
        let hrvS = series(\.hrv), rhrS = series(\.rhr), respS = series(\.resp), skinS = series(\.skinTempC)

        func fold(_ s: [(day: String, value: Double?)], _ anchor: String, _ cfg: MetricCfg) -> BaselineState {
            let h = ChargeBaselines.history(imported: [], own: s, anchorDay: anchor, cfg: cfg,
                                            baselineEpoch: 0, windowDays: windowDays)
            return Baselines.foldHistory(h.values, dayKeys: h.dayKeys, cfg: cfg, baselineEpoch: 0)
        }

        return sorted.map { n in
            let hrvB = fold(hrvS, n.day, Baselines.hrvCfg)
            let rhrB = fold(rhrS, n.day, Baselines.restingHRCfg)
            let respB = fold(respS, n.day, Baselines.respCfg)
            let skinB = fold(skinS, n.day, Baselines.metricCfg["skin_temp"]!)
            // Same use-site gate and rounding as AnalyticsEngine's skinTempDevC.
            let skinDev: Double? = n.skinTempC.flatMap { v in
                skinB.usable ? (Baselines.deviation(v, state: skinB).delta * 100).rounded() / 100 : nil
            }
            let respUsable: BaselineState? = respB.usable ? respB : nil

            func charge(resp: Bool, sleep: Bool, skin: Bool) -> Double? {
                guard let hrv = n.hrv, let rhr = n.rhr else { return nil }
                return RecoveryScorer.recovery(hrv: hrv, rhr: rhr,
                                               resp: resp ? n.resp : nil,
                                               hrvBaseline: hrvB, rhrBaseline: rhrB,
                                               respBaseline: resp ? respUsable : nil,
                                               sleepPerf: sleep ? n.sleepPerf : nil,
                                               skinTempDev: skin ? skinDev : nil)
            }

            let full = charge(resp: true, sleep: true, skin: true)
            let z = { (v: Double?, b: BaselineState?, higherIsBetter: Bool) -> Double? in
                guard full != nil, let v, let b, b.usable else { return nil }
                let sigma = max(1.253 * b.spread, 1e-9)
                return higherIsBetter ? (v - b.baseline) / sigma : (b.baseline - v) / sigma
            }
            return ScoredNight(
                day: n.day,
                full: full,
                noSleep: charge(resp: true, sleep: false, skin: true),
                hrvRhr: charge(resp: false, sleep: false, skin: false),
                hrvBase: hrvB, rhrBase: rhrB, respBase: respB, skinBase: skinB, skinDev: skinDev,
                zHrv: z(n.hrv, hrvB, true),
                zRhr: z(n.rhr, rhrB, false),
                zResp: z(n.resp, respUsable, false),
                zSleep: (full != nil) ? n.sleepPerf.map { ($0 - RecoveryScorer.sleepPerfCenter) / RecoveryScorer.sleepPerfScale } : nil,
                zSkin: (full != nil) ? skinDev.map { -abs($0) / RecoveryScorer.skinTempScaleC } : nil)
        }
    }

    // MARK: - CSV

    public static let inputHeader = ["day", "hrv", "rhr", "resp", "sleep_perf", "skin_temp_c"]

    /// Parse the input CSV: header `day,hrv,rhr,resp,sleep_perf,skin_temp_c` (any column order), plain
    /// numbers, empty cells for missing values. No quoting, which the numeric columns never need.
    public static func parseCSV(_ text: String) throws -> [Night] {
        var lines = text.split(whereSeparator: \.isNewline).map(String.init).filter { !$0.isEmpty }
        guard !lines.isEmpty else { return [] }
        let header = lines.removeFirst().split(separator: ",", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespaces) }
        var idx: [String: Int] = [:]
        for name in inputHeader {
            guard let i = header.firstIndex(of: name) else { throw ParseError.missingColumn(name) }
            idx[name] = i
        }
        return try lines.enumerated().map { lineNo, line in
            let cells = line.split(separator: ",", omittingEmptySubsequences: false)
                .map { $0.trimmingCharacters(in: .whitespaces) }
            func num(_ name: String) throws -> Double? {
                let i = idx[name]!
                guard i < cells.count, !cells[i].isEmpty else { return nil }
                guard let v = Double(cells[i]) else { throw ParseError.badNumber(line: lineNo + 2, column: name) }
                return v
            }
            return Night(day: cells[idx["day"]!], hrv: try num("hrv"), rhr: try num("rhr"), resp: try num("resp"),
                         sleepPerf: try num("sleep_perf"), skinTempC: try num("skin_temp_c"))
        }
    }

    public enum ParseError: Error, Equatable {
        case missingColumn(String)
        case badNumber(line: Int, column: String)
    }

    public static let outputHeader = [
        "day", "noop_full", "noop_no_sleep", "noop_hrv_rhr",
        "hrv_base", "hrv_spread", "hrv_n", "rhr_base", "rhr_spread", "rhr_n",
        "resp_base", "resp_spread", "resp_n", "skin_base", "skin_dev_c",
        "z_hrv", "z_rhr", "z_resp", "z_sleep", "z_skin",
    ].joined(separator: ",")

    public static func csvRow(_ s: ScoredNight) -> String {
        func f(_ v: Double?) -> String { v.map { String(format: "%.4f", $0) } ?? "" }
        return [s.day, f(s.full), f(s.noSleep), f(s.hrvRhr),
                f(s.hrvBase.baseline), f(s.hrvBase.spread), String(s.hrvBase.nValid),
                f(s.rhrBase.baseline), f(s.rhrBase.spread), String(s.rhrBase.nValid),
                f(s.respBase.baseline), f(s.respBase.spread), String(s.respBase.nValid),
                f(s.skinBase.baseline), f(s.skinDev),
                f(s.zHrv), f(s.zRhr), f(s.zResp), f(s.zSleep), f(s.zSkin)].joined(separator: ",")
    }
}
