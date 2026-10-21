import Foundation
import XCTest

@testable import KevCADWire

/// Die Aufzeichnung `samples/mirror-recordings/gestell.kcadmirror` (aus mirror_demo.py) vollständig lesen: Szene,
/// Zustand, alle Netze mit geprüftem Hash, Körper für den Viewport.
final class RecordingTests: XCTestCase {
    func testGestellRecordingBuildsCompleteScene() throws {
        let url = WireFiles.recordings.appendingPathComponent("gestell.kcadmirror")
        let frames = try WireFiles.frames(url)
        XCTAssertGreaterThan(frames.count, 100)
        var r = MirrorReceiver()
        var rejected: [String] = []
        for f in frames {
            for e in try r.apply(frame: f) {
                if case .meshRejected(let h, let why) = e { rejected.append("\(h): \(why)") }
            }
        }
        XCTAssertEqual(rejected, [])
        XCTAssertEqual(r.parts.count, 17)
        XCTAssertTrue(r.isComplete, "Szene, Zustand und alle Netze")
        XCTAssertEqual(r.state?.darstellung, "shaded_edges")
        XCTAssertNil(r.state?.isoliert)
        var triangles = 0
        for p in r.parts {
            let g = try XCTUnwrap(try r.geometry(of: p))
            XCTAssertEqual(g.triangleCount, p.counts.tri)
            let bodies = PartBodies(name: p.name, geometry: g).bodies(color: p.colorVector)
            XCTAssertFalse(bodies.isEmpty)
            triangles += bodies.reduce(0) { $0 + $1.indices.count / 3 }
        }
        XCTAssertEqual(triangles, 27_148)
    }
}
