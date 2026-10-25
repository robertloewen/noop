// swift-tools-version:5.9
import PackageDescription

// ScoreCompare — run NOOP's shipped Charge (recovery) scorer over nightly summary values.
//
// Fork-only (ENTWICKLUNGSPLAN.md, Phase 2). The input is one row per night with the values a WHOOP export
// already carries (HRV, resting HR, respiration, sleep performance, skin temperature). The tool folds the
// personal baselines and scores each night through `ChargeBaselines`, `Baselines` and `RecoveryScorer`
// exactly as the app does, so the comparison against WHOOP's own recovery measures the FORMULA, not a
// re-implementation of it.
//
// No health data lives in this repo: input comes from stdin or a file argument, output goes to stdout.
let package = Package(
    name: "scorecompare",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(path: "../../Packages/StrandAnalytics"),
    ],
    targets: [
        .target(name: "ScoreCompareCore", dependencies: ["StrandAnalytics"]),
        .executableTarget(name: "scorecompare", dependencies: ["ScoreCompareCore", "StrandAnalytics"]),
        .testTarget(name: "ScoreCompareCoreTests", dependencies: ["ScoreCompareCore", "StrandAnalytics"]),
    ]
)
