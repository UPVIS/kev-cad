import Foundation
import XCTest

@testable import KevCADWire

/// Pfade im Repo (die Testdateien des Spiegels liegen außerhalb des Pakets, in `mirror-fixtures/` und
/// `samples/mirror-recordings/`, damit VoiceBridge und der Kernel dieselben Dateien lesen).
enum WireFiles {
    static var repo: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()  // KevCADWireTests
            .deletingLastPathComponent()  // Tests
            .deletingLastPathComponent()  // KevCADCore
            .deletingLastPathComponent()  // app
            .deletingLastPathComponent()  // Repo
    }

    static var fixtures: URL { repo.appendingPathComponent("mirror-fixtures") }
    static var recordings: URL { repo.appendingPathComponent("samples/mirror-recordings") }

    static func fixture(_ name: String) throws -> Frame {
        let data = try Data(contentsOf: fixtures.appendingPathComponent(name))
        let frames = try FrameReader().feed(data)
        guard frames.count == 1 else { throw NSError(domain: "WireFiles", code: 1, userInfo: [NSLocalizedDescriptionKey: "\(name): \(frames.count) Rahmen statt 1"]) }
        return frames[0]
    }

    static func frames(_ url: URL) throws -> [Frame] {
        try FrameReader().feed(Data(contentsOf: url))
    }

    /// Erwartete Werte aus `mirror-fixtures/fixtures.json`.
    static func expected() throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: Data(contentsOf: fixtures.appendingPathComponent("fixtures.json")))
    }
}
