import Foundation
import XCTest
@testable import ScoreCompareCore
import StrandAnalytics

final class ScoreCompareTests: XCTestCase {

    /// Thirty synthetic nights around HRV 65 / RHR 55, with a deliberately bad last night.
    private func nights() -> [Night] {
        (0..<30).map { i in
            let bad = i == 29
            return Night(day: String(format: "2025-01-%02d", i + 1),
                         hrv: bad ? 35 : 65 + Double(i % 5) - 2,
                         rhr: bad ? 64 : 55 + Double(i % 3) - 1,
                         resp: 15 + Double(i % 2) * 0.3,
                         sleepPerf: bad ? 0.6 : 0.9,
                         skinTempC: 33.2 + Double(i % 4) * 0.05)
        }
    }

    func testColdStartScoresNothingUntilTheHrvBaselineIsUsable() {
        let scored = ScoreCompare.score(nights())
        let firstScored = scored.firstIndex { $0.full != nil }
        XCTAssertEqual(firstScored, Baselines.minNightsSeed - 1, "the 4th night is the first with a usable baseline")
        XCTAssertNil(scored[0].hrvRhr)
    }

    func testBadNightScoresBelowAnOrdinaryOne() throws {
        let scored = ScoreCompare.score(nights())
        let ordinary = try XCTUnwrap(scored[27].full)
        let bad = try XCTUnwrap(scored[29].full)
        XCTAssertLessThan(bad, ordinary - 20)
        XCTAssertLessThan(try XCTUnwrap(scored[29].zHrv), -1)
        XCTAssertLessThan(try XCTUnwrap(scored[29].zRhr), -1)
    }

    /// The exported z-scores must be the ones the scorer used: re-weighting them through the published
    /// weights and the logistic must reproduce the score. This is what lets Phase 2 fit its own weights
    /// on these columns.
    func testExportedZScoresReproduceTheScore() throws {
        for s in ScoreCompare.score(nights()) where s.full != nil {
            var terms: [(Double, Double)] = []
            terms.append((try XCTUnwrap(s.zHrv), RecoveryScorer.wHRV))
            if let z = s.zRhr { terms.append((z, RecoveryScorer.wRHR)) }
            if let z = s.zResp { terms.append((z, RecoveryScorer.wResp)) }
            if let z = s.zSleep { terms.append((z, RecoveryScorer.wSleep)) }
            if let z = s.zSkin { terms.append((z, RecoveryScorer.wSkinTemp)) }
            let w = terms.reduce(0) { $0 + $1.1 }
            let z = terms.reduce(0) { $0 + $1.0 * $1.1 } / w
            let expected = max(0, min(100, 100 / (1 + exp(-RecoveryScorer.logisticK * (z - RecoveryScorer.logisticZ0)))))
            XCTAssertEqual(try XCTUnwrap(s.full), expected, accuracy: 1e-9, s.day)
        }
    }

    func testVariantsDropTheirTerms() throws {
        let s = ScoreCompare.score(nights())[29]
        XCTAssertNotEqual(try XCTUnwrap(s.full), try XCTUnwrap(s.noSleep))
        XCTAssertNotEqual(try XCTUnwrap(s.noSleep), try XCTUnwrap(s.hrvRhr))
    }

    func testMissingHrvMeansNoScore() {
        var n = nights()
        n[20] = Night(day: n[20].day, hrv: nil, rhr: 55, resp: 15, sleepPerf: 0.9, skinTempC: 33.2)
        XCTAssertNil(ScoreCompare.score(n)[20].full)
    }

    func testCsvRoundTrip() throws {
        let csv = "skin_temp_c,day,hrv,rhr,resp,sleep_perf\n33.1,2025-01-01,60,55,,0.85\n"
        XCTAssertEqual(try ScoreCompare.parseCSV(csv),
                       [Night(day: "2025-01-01", hrv: 60, rhr: 55, resp: nil, sleepPerf: 0.85, skinTempC: 33.1)])
        XCTAssertThrowsError(try ScoreCompare.parseCSV("day,hrv\n2025-01-01,60\n"))
        XCTAssertThrowsError(try ScoreCompare.parseCSV("day,hrv,rhr,resp,sleep_perf,skin_temp_c\n2025-01-01,x,55,,,\n"))
        let header = ScoreCompare.outputHeader.split(separator: ",").count
        let row = ScoreCompare.csvRow(ScoreCompare.score(nights())[10]).split(separator: ",", omittingEmptySubsequences: false).count
        XCTAssertEqual(header, row)
    }
}
