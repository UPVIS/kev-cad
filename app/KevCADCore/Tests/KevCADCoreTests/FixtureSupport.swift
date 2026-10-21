import Foundation
import XCTest

@testable import KevCADCore

/// Zugriff auf die Protokoll-Testdateien (erzeugt von kernel/tools/make_fixtures.py).
enum Fixtures {
    static var directory: URL {
        guard let url = Bundle.module.url(forResource: "Fixtures", withExtension: nil) else {
            fatalError("Fixtures fehlen im Test-Bundle")
        }
        return url
    }

    static func data(_ name: String) throws -> Data {
        try Data(contentsOf: directory.appendingPathComponent(name))
    }

    /// Erwartete Werte aus fixtures.json.
    static func expected() throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: data("fixtures.json"))
    }

    /// Genau ein Rahmen aus einer .frame-Datei.
    static func frame(_ name: String) throws -> Frame {
        let frames = try FrameReader().feed(data(name))
        XCTAssertEqual(frames.count, 1, name)
        return frames[0]
    }

    static func message(_ name: String) throws -> KernelMessage {
        try KernelMessage.decode(frame(name))
    }

    static func part(_ name: String) throws -> (PartUpsertHeader, PartGeometry) {
        guard case .partUpsert(let h, let g) = try message(name) else {
            throw NSError(domain: "Fixtures", code: 1, userInfo: [NSLocalizedDescriptionKey: "\(name) ist kein PART_UPSERT"])
        }
        return (h, g)
    }

    static func record(_ name: String) throws -> PartRecord {
        let (h, g) = try part(name)
        return PartRecord(header: h, geometry: g)
    }
}
