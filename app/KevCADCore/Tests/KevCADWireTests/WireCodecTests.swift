import Foundation
import XCTest

@testable import KevCADWire

/// Netzformat, Hash, Blöcke und Kodierung der Spiegel-Nachrichten ohne Testdateien.
final class WireCodecTests: XCTestCase {
    static func box() -> PartGeometry {
        // Würfel 10 mm: 8 Punkte, 12 Dreiecke, 6 Flächen, 12 Kanten, 8 B-Rep-Punkte
        let p: [Float] = [0, 0, 0, 10, 0, 0, 10, 10, 0, 0, 10, 0, 0, 0, 10, 10, 0, 10, 10, 10, 10, 0, 10, 10]
        let tris: [UInt32] = [0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4, 1, 2, 6, 1, 6, 5, 2, 3, 7, 2, 7, 6,
                              3, 0, 4, 3, 4, 7]
        var edgePoints: [Float] = []
        var offsets: [UInt32] = [0]
        let pairs = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
        for (a, b) in pairs {
            edgePoints += Array(p[(a * 3)..<(a * 3 + 3)]) + Array(p[(b * 3)..<(b * 3 + 3)])
            offsets.append(offsets.last! + 2)
        }
        return PartGeometry(
            positions: p, normals: [Float](repeating: 0.577, count: p.count), triangles: tris,
            triFace: (0..<12).map { Int32($0 / 2) }, edgePoints: edgePoints, edgeOffsets: offsets, vertices: p)
    }

    func testRawLeavesOutBRepPoints() throws {
        let g = Self.box()
        let raw = KcadMesh.raw(g)
        let counts = MeshCounts(g.counts)
        XCTAssertEqual(raw.count, counts.rawBytes)
        XCTAssertEqual(raw.count, g.encodedPayload().count - g.vertices.count * 4)
        XCTAssertEqual(try KcadMesh.raw(partUpsertPayload: g.encodedPayload(), counts: g.counts), raw)
        let back = try KcadMesh.geometry(raw: raw, counts: counts)
        XCTAssertEqual(back.positions, g.positions)
        XCTAssertEqual(back.triangles, g.triangles)
        XCTAssertEqual(back.triFace, g.triFace)
        XCTAssertEqual(back.edgeOffsets, g.edgeOffsets)
        XCTAssertTrue(back.vertices.isEmpty)
    }

    func testHashIsFirst16HexOfSHA256() {
        // SHA-256("abc") = ba7816bf8f01cfea…
        XCTAssertEqual(KcadMesh.hash(raw: Data("abc".utf8)), "ba7816bf8f01cfea")
    }

    func testLZFSERoundTripAndBlocks() throws {
        // Zufallsdaten lassen sich kaum packen: mehrere Blöcke
        var rng = SystemRandomNumberGenerator()
        let big = Data((0..<200_000).map { _ in UInt8.random(in: 0...255, using: &rng) })
        let mesh = try PackedMesh(raw: big, counts: MeshCounts())
        XCTAssertGreaterThan(mesh.blockCount, 1)
        var assembler = MeshAssembler()
        var result: (hash: String, raw: Data)?
        // Blöcke in umgekehrter Reihenfolge: zusammengesetzt wird nach `block`
        for i in (0..<mesh.blockCount).reversed() {
            XCTAssertLessThanOrEqual(mesh.blockPayload(i).count, 64 * 1024)
            result = try assembler.add(mesh.blockHeader(i), payload: mesh.blockPayload(i))
            if i > 0 { XCTAssertNil(result) }
        }
        XCTAssertEqual(result?.hash, mesh.hash)
        XCTAssertEqual(result?.raw, big)
    }

    func testWrongHashIsRejected() throws {
        let mesh = try PackedMesh(geometry: Self.box())
        var header = mesh.blockHeader(0)
        header.hash = "0000000000000000"
        var assembler = MeshAssembler()
        XCTAssertThrowsError(try assembler.add(header, payload: mesh.blockPayload(0)))
    }

    func testEnvelopeAndRoundTrip() throws {
        let part = MirrorPart(
            name: "Rollwagen/Rad", hash: "9f3c000000000000", color: [0.2, 0.2, 0.2, 1], material: nil,
            bbox: BBox(min: [0, 0, 0], max: [1, 2, 3]), counts: MeshCounts(vert: 8, tri: 12, face: 6, edge: 12, epts: 24))
        let f = try MirrorPartMessage.upsert(epoche: "abcd", run: 3, part: part).frame(seq: 7)
        let json = try JSONSerialization.jsonObject(with: f.header) as! [String: Any]
        XCTAssertEqual(json["type"] as? String, "PART")
        XCTAssertEqual(json["seq"] as? Int, 7)
        XCTAssertEqual(json["prio"] as? String, "szene")
        XCTAssertEqual(json["op"] as? String, "upsert")
        XCTAssertEqual(json["name"] as? String, "Rollwagen/Rad")
        XCTAssertTrue(json.keys.contains("material"))
        guard case .part(let back) = try MirrorMessage.decode(f) else { return XCTFail("kein PART") }
        XCTAssertEqual(back.part, part)
        XCTAssertEqual(back.run, 3)

        let delta = MirrorStateDeltaMessage(
            epoche: "abcd", rev: 5, quelle: .iphone, change: MirrorStateChange(isoliert: .some(nil), schnitt: .some(nil)))
        let df = try delta.frame(seq: 8)
        let dj = try JSONSerialization.jsonObject(with: df.header) as! [String: Any]
        XCTAssertTrue(dj["isoliert"] is NSNull)
        XCTAssertTrue(dj["schnitt"] is NSNull)
        XCTAssertNil(dj["verborgen"])
        guard case .stateDelta(let d) = try MirrorMessage.decode(df) else { return XCTFail("kein STATE_DELTA") }
        XCTAssertEqual(d, delta)
        XCTAssertEqual(d.change.fieldNames, ["isoliert", "schnitt"])
    }

    func testStateDiffAndApply() {
        let a = MirrorViewState()
        var b = a
        b.verborgen = ["A"]
        b.isoliert = ["B"]
        b.kamera.distance = 99
        let change = MirrorStateChange.between(a, b)
        XCTAssertEqual(change.fieldNames, ["verborgen", "isoliert"])
        var expected = b
        expected.kamera = a.kamera
        XCTAssertEqual(a.applying(change), expected)
    }

    func testScenePagesStayBelowHeaderLimit() throws {
        let parts = (0..<300).map { i in
            MirrorPart(
                name: "Baugruppe \(i / 10)/Teil mit einem recht langen Namen \(i)", hash: String(format: "%016x", i),
                color: [0.5, 0.5, 0.5, 1], material: "aluminium",
                bbox: BBox(min: [-123.456, -7.5, 0], max: [123.456, 7.5, 1000.25]),
                counts: MeshCounts(vert: 1000, tri: 2000, face: 30, edge: 40, epts: 500))
        }
        let pages = MirrorScenePage.pages(epoche: "e", project: MirrorProject(path: "/x/y", name: "Y"), run: 1, bbox: nil, parts: parts)
        XCTAssertGreaterThan(pages.count, 1)
        var seq = 0
        for p in pages {
            seq += 1
            let f = try p.frame(seq: seq)
            XCTAssertLessThanOrEqual(f.header.count, 16 * 1024)
            XCTAssertFalse(String(decoding: f.header, as: UTF8.self).contains("/x/y"), "Pfad darf nicht in SCENE")
        }
        var r = MirrorReceiver()
        for p in pages.reversed() { _ = r.apply(.scene(p)) }
        XCTAssertEqual(r.parts.map(\.name), parts.map(\.name))
    }

    func testBodiesSplitAndResolve() throws {
        // Streifen mit 40.000 Dreiecken: drei Körper
        var pos: [Float] = []
        var tris: [UInt32] = []
        for i in 0..<20_001 { pos += [Float(i), 0, 0, Float(i), 1, 0] }
        for i in 0..<20_000 {
            let a = UInt32(i * 2)
            tris += [a, a + 2, a + 1, a + 1, a + 2, a + 3]
        }
        let g = PartGeometry(
            positions: pos, normals: [Float](repeating: 0, count: pos.count), triangles: tris,
            triFace: (0..<40_000).map { Int32($0 / 1000) }, edgeOffsets: [0])
        let parts = PartBodies(name: "Band", geometry: g)
        let bodies = parts.bodies(color: SIMD4(1, 1, 1, 1))
        XCTAssertEqual(bodies.count, 3)
        XCTAssertTrue(bodies.allSatisfy { $0.indices.count / 3 <= 16_000 })
        XCTAssertEqual(bodies.map(\.id), ["Band\u{1F}0", "Band\u{1F}1", "Band\u{1F}2"])
        XCTAssertEqual(parts.resolve(chunk: 1, kind: .face, primitive: 5), .face("Band", 16))
        XCTAssertEqual(PartBodies.owner(ofBody: "A/B\u{1F}2")?.part, "A/B")
        XCTAssertEqual(PartBodies.owner(ofBody: "A/B\u{1F}2")?.chunk, 2)
    }
}
