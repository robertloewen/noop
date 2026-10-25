import Foundation
import ScoreCompareCore
import StrandAnalytics

// Usage: scorecompare [--window DAYS] [input.csv]
// Reads stdin when no file is given, writes CSV to stdout. --window overrides the app's 21-day baseline
// window for experiments; the default is what the app ships.
var args = Array(CommandLine.arguments.dropFirst())
var windowDays = ChargeBaselines.windowDays
if let i = args.firstIndex(of: "--window"), i + 1 < args.count, let w = Int(args[i + 1]), w > 0 {
    windowDays = w
    args.removeSubrange(i...(i + 1))
}
let text: String
if let path = args.first {
    guard let s = try? String(contentsOfFile: path, encoding: .utf8) else {
        FileHandle.standardError.write("cannot read \(path)\n".data(using: .utf8)!)
        exit(1)
    }
    text = s
} else {
    text = String(decoding: FileHandle.standardInput.readDataToEndOfFile(), as: UTF8.self)
}

do {
    let scored = ScoreCompare.score(try ScoreCompare.parseCSV(text), windowDays: windowDays)
    print(ScoreCompare.outputHeader)
    for s in scored { print(ScoreCompare.csvRow(s)) }
} catch {
    FileHandle.standardError.write("input error: \(error)\n".data(using: .utf8)!)
    exit(1)
}
