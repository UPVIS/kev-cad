import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Großes Testteil: Gitter aus Vierecken (je 2 Dreiecke), vier Flächen (Quadranten), eine sehr lange Kante und
/// einige kurze, dazu viele B-Rep-Punkte.
func makeLargeGeometry(nx: Int = 150, ny: Int = 120, longEdgePoints: Int = 20_001, vertexCount: Int = 20) -> PartGeometry {
    var g = PartGeometry()
    for j in 0...ny {
        for i in 0...nx {
            g.positions += [Float(i), Float(j), Float((i * j) % 7) * 0.1]
            g.normals += [0, 0, 1]
        }
    }
    let row = nx + 1
    for j in 0..<ny {
        for i in 0..<nx {
            let a = UInt32(j * row + i)
            g.triangles += [a, a + 1, a + UInt32(row), a + 1, a + UInt32(row) + 1, a + UInt32(row)]
            let face = Int32((i < nx / 2 ? 0 : 1) + (j < ny / 2 ? 0 : 2))
            g.triFace += [face, face]
        }
    }
    g.edgeOffsets = [0]
    for k in 0..<longEdgePoints { g.edgePoints += [Float(k) * 0.01, -1, 0] }
    g.edgeOffsets.append(UInt32(g.edgePoints.count / 3))
    for e in 0..<10 {
        g.edgePoints += [Float(e), -2, 0, Float(e) + 0.5, -2, 0, Float(e) + 0.9, -2.5, 0]
        g.edgeOffsets.append(UInt32(g.edgePoints.count / 3))
    }
    for v in 0..<vertexCount { g.vertices += [Float(v), -3, 0] }
    return g
}

func header(for g: PartGeometry, name: String, run: Int = 1) -> PartUpsertHeader {
    PartUpsertHeader(
        run: run, name: name, color: [0.5, 0.6, 0.7, 1], counts: g.counts,
        faces: (0..<g.counts.face).map { _ in FaceInfo(t: "plane", a: 1) },
        edges: (0..<g.edgeCount).map { _ in EdgeInfo(t: "line", l: 1) })
}

final class ChunkTests: XCTestCase {
    func testLargePartIsSplitBelowPickLimit() {
        let g = makeLargeGeometry()
        XCTAssertGreaterThan(g.triangleCount, 32_000)
        let chunks = ChunkBuilder.build(g)
        XCTAssertGreaterThanOrEqual(chunks.count, 3)
        var tris = 0, segs = 0, pts = 0
        for c in chunks {
            XCTAssertLessThanOrEqual(c.triangleCount, ChunkBuilder.limit)
            XCTAssertLessThanOrEqual(c.segmentCount, ChunkBuilder.limit)
            XCTAssertLessThanOrEqual(c.points.count, ChunkBuilder.limit)
            XCTAssertEqual(c.triFace.count, c.triangleCount)
            tris += c.triangleCount
            segs += c.segmentCount
            pts += c.pointTargets.filter { if case .vertex = $0 { return true } else { return false } }.count
            // Zuordnung Dreieck → Fläche und Punkte bleiben erhalten
            for t in stride(from: 0, to: c.triangleCount, by: 97) {
                XCTAssertEqual(c.triFace[t], g.triFace[c.firstTriangle + t])
                for k in 0..<3 {
                    let local = Int(c.indices[t * 3 + k])
                    let global = Int(g.triangles[(c.firstTriangle + t) * 3 + k])
                    XCTAssertEqual(c.vertexData[local * 6], g.positions[global * 3])
                    XCTAssertEqual(c.vertexData[local * 6 + 2], g.positions[global * 3 + 2])
                }
            }
        }
        XCTAssertEqual(tris, g.triangleCount)
        let expectedSegs = (0..<g.edgeCount).reduce(0) { $0 + Int(g.edgeOffsets[$1 + 1] - g.edgeOffsets[$1]) - 1 }
        XCTAssertEqual(segs, expectedSegs)
        XCTAssertEqual(pts, g.brepVertexCount)
        // Die lange Kante (20.000 Segmente) ist geteilt, jedes Segment gehört zu Kante 0
        let longSegs = chunks.flatMap(\.segEdge).filter { $0 == 0 }.count
        XCTAssertEqual(longSegs, 20_000)
    }

    func testSmallPartIsOneChunk() throws {
        let rec = try Fixtures.record("part_cylinder.frame")
        XCTAssertEqual(rec.chunks.count, 1)
        let c = rec.chunks[0]
        XCTAssertEqual(c.triangleCount, 248)
        XCTAssertEqual(c.vertexCount, 254)
        XCTAssertEqual(c.points.count, 2)
        XCTAssertEqual(c.edges.count, 3)
        XCTAssertEqual(c.segmentCount, 130 - 3)
    }

    func testManyVerticesAreSpread() {
        let g = makeLargeGeometry(nx: 4, ny: 4, longEdgePoints: 3, vertexCount: 40_000)
        let chunks = ChunkBuilder.build(g)
        XCTAssertGreaterThanOrEqual(chunks.count, 3)
        XCTAssertTrue(chunks.allSatisfy { $0.points.count <= ChunkBuilder.limit })
        let vtx = chunks.flatMap(\.pointTargets).compactMap { t -> Int? in if case .vertex(let v) = t { return v } else { return nil } }
        XCTAssertEqual(Set(vtx).count, 40_000)
    }

    func testEdgeOnlyPartGetsBoundsPoints() {
        var g = PartGeometry()
        g.edgePoints = [0, 0, 0, 10, 0, 0, 10, 5, 3]
        g.edgeOffsets = [0, 3]
        let chunks = ChunkBuilder.build(g)
        XCTAssertEqual(chunks.count, 1)
        XCTAssertTrue(chunks[0].indices.isEmpty)
        XCTAssertFalse(chunks[0].points.isEmpty)
        XCTAssertTrue(chunks[0].pointTargets.allSatisfy { $0 == .edge(0) })
    }
}

@MainActor
final class SceneTests: XCTestCase {
    func testPickResolvesFacesEdgesAndVerticesAcrossChunks() throws {
        let scene = SceneStore()
        let g = makeLargeGeometry()
        scene.upsert(PartRecord(header: header(for: g, name: "Halter/Platte"), geometry: g))
        let rec = try XCTUnwrap(scene.record("Halter/Platte"))
        XCTAssertEqual(scene.bodies.count, rec.chunks.count)

        for chunk in rec.chunks {
            let id = SceneStore.bodyID(part: "Halter/Platte", chunk: chunk.index)
            XCTAssertTrue(scene.bodies.contains { $0.id == id })
            if chunk.triangleCount > 0 {
                let t = chunk.triangleCount - 1
                let expected = Int(g.triFace[chunk.firstTriangle + t])
                XCTAssertEqual(scene.resolve(bodyID: id, kind: .face, primitive: t), .face("Halter/Platte", expected))
            }
            if chunk.segmentCount > 0 {
                let s = chunk.segmentCount - 1
                XCTAssertEqual(
                    scene.resolve(bodyID: id, kind: .edge, primitive: s), .edge("Halter/Platte", Int(chunk.segEdge[s])))
            }
            if case .vertex(let v)? = chunk.pointTargets.first {
                XCTAssertEqual(scene.resolve(bodyID: id, kind: .vertex, primitive: 0), .vertex("Halter/Platte", v))
            }
        }
        // Treffer jenseits von Dreieck 16.000 im Teil liegen im zweiten Körper und landen auf der richtigen Fläche
        let second = SceneStore.bodyID(part: "Halter/Platte", chunk: 1)
        let globalTri = rec.chunks[1].firstTriangle + 5
        XCTAssertGreaterThan(globalTri, 16_000)
        XCTAssertEqual(
            scene.resolve(bodyID: second, kind: .face, primitive: 5), .face("Halter/Platte", Int(g.triFace[globalTri])))

        XCTAssertNil(scene.resolve(bodyID: "gibt-es-nicht", kind: .face, primitive: 0))
        // Primitiv außerhalb: dann wenigstens das Teil
        XCTAssertEqual(scene.resolve(bodyID: second, kind: .face, primitive: 99_999), .part("Halter/Platte"))
    }

    /// Über die echte Dekodierung der Pick-ID des Viewports (14 Bit Primitiv, 2 Bit Art).
    func testPickResultFromRawValue() throws {
        let scene = SceneStore()
        scene.upsert(try Fixtures.record("part_box.frame"))
        let id = SceneStore.bodyID(part: "Grundplatte", chunk: 0)
        func raw(_ object: UInt32, _ prim: UInt32, _ kind: UInt32) -> UInt32 { object | (prim << 16) | (kind << 30) }
        let face = try XCTUnwrap(PickResult(rawValue: raw(0, 11, 0), indexMap: [0: id]))
        XCTAssertEqual(scene.resolve(face), .face("Grundplatte", 5))
        let edge = try XCTUnwrap(PickResult(rawValue: raw(0, 3, 1), indexMap: [0: id]))
        XCTAssertEqual(scene.resolve(edge), .edge("Grundplatte", 3))
        let vtx = try XCTUnwrap(PickResult(rawValue: raw(0, 7, 2), indexMap: [0: id]))
        XCTAssertEqual(scene.resolve(vtx), .vertex("Grundplatte", 7))
    }

    func testReferenceFormat() {
        XCTAssertEqual(ElementRef("Halter/Lasche#f12"), .face("Halter/Lasche", 12))
        XCTAssertEqual(ElementRef("Halter/Lasche#e3"), .edge("Halter/Lasche", 3))
        XCTAssertEqual(ElementRef("Halter/Lasche#v2"), .vertex("Halter/Lasche", 2))
        XCTAssertEqual(ElementRef("Halter/Lasche"), .part("Halter/Lasche"))
        XCTAssertEqual(ElementRef("A#b#e3"), .edge("A#b", 3))
        XCTAssertEqual(ElementRef("Teil#x1"), .part("Teil#x1"))
        XCTAssertEqual(ElementRef("Teil#f"), .part("Teil#f"))
        XCTAssertEqual(ElementRef("Teil#f1a"), .part("Teil#f1a"))
        XCTAssertNil(ElementRef(""))
        for s in ["Halter/Lasche#f12", "Grundplatte", "X#e0", "Y/Z#v10"] { XCTAssertEqual(ElementRef(s)?.string, s) }
        XCTAssertEqual(ElementRef.face("A", 1).partRef, .part("A"))
    }

    func testGermanNumbers() {
        XCTAssertEqual(GermanFormat.number(200, decimals: 1), "200,0")
        XCTAssertEqual(GermanFormat.number(6000, decimals: 1), "6.000,0")
        XCTAssertEqual(GermanFormat.number(-0.00001, decimals: 1), "0,0")
        XCTAssertEqual(GermanFormat.mm(12.5), "12,500 mm")
        XCTAssertEqual(GermanFormat.mm2(628.3185), "628,3 mm²")
        XCTAssertEqual(GermanFormat.mass(1234.6), "1,235 kg")
        XCTAssertEqual(GermanFormat.mass(16.2), "16,2 g")
        XCTAssertEqual(GermanFormat.size(SIMD3(10, 20, 30)), "10,0 × 20,0 × 30,0 mm")
    }

    func testInstantValuesFromMetadata() throws {
        let box = try Fixtures.record("part_box.frame")
        let f5 = box.selectionItem(for: .face("Grundplatte", 5))
        XCTAssertEqual(f5.ref, "Grundplatte#f5")
        XCTAssertEqual(f5.run, 1)
        XCTAssertEqual(f5.summary, "Fläche 5 · Ebene · 200,0 mm²")
        XCTAssertEqual(f5.values["area"], 200)
        XCTAssertEqual(f5.values["normal_z"], 1)
        XCTAssertEqual(f5.values["center_z"], 15)

        let e0 = box.selectionItem(for: .edge("Grundplatte", 0))
        XCTAssertEqual(e0.summary, "Kante 0 · Gerade · 30,000 mm")
        XCTAssertEqual(e0.values["length"], 30)

        let v0 = box.selectionItem(for: .vertex("Grundplatte", 0))
        XCTAssertTrue(v0.summary.hasPrefix("Punkt 0 · ("), v0.summary)
        XCTAssertNotNil(v0.values["x"])

        let part = box.selectionItem(for: .part("Grundplatte"))
        XCTAssertEqual(part.summary, "Grundplatte · 10,0 × 20,0 × 30,0 mm · 6.000,0 mm³")
        XCTAssertEqual(part.values["volume"], 6000)
        XCTAssertEqual(part.values["faces"], 6)

        let cyl = try Fixtures.record("part_cylinder.frame")
        XCTAssertEqual(cyl.selectionItem(for: .face("Halter/Bolzen", 0)).summary, "Fläche 0 · Zylinder r 5,000 mm · 628,3 mm²")
        XCTAssertEqual(cyl.selectionItem(for: .edge("Halter/Bolzen", 0)).summary, "Kante 0 · Kreis r 5,000 mm · 31,416 mm")
        XCTAssertEqual(cyl.selectionItem(for: .edge("Halter/Bolzen", 0)).values["radius"], 5)
    }

    func testSelectionTintsOnlyThatFace() throws {
        let scene = SceneStore()
        scene.upsert(try Fixtures.record("part_box.frame"), flash: false)
        let before = try XCTUnwrap(scene.bodies.first)
        XCTAssertTrue(before.triangleStyles.isEmpty)
        scene.setSelection([.face("Grundplatte", 2)])
        let body = try XCTUnwrap(scene.bodies.first)
        XCTAssertNotEqual(body.generation, before.generation, "Neue Stile brauchen einen neu gebauten Körper")
        XCTAssertEqual(body.triangleStyles.count, 12)
        let rec = try XCTUnwrap(scene.record("Grundplatte"))
        for t in 0..<12 {
            XCTAssertEqual(body.triangleStyles[t].color.w > 0, rec.geometry.triFace[t] == 2, "Dreieck \(t)")
        }
        // Ungültige Referenzen werden verworfen
        scene.setSelection([.face("Grundplatte", 99), .part("Fehlt")])
        XCTAssertTrue(scene.selection.isEmpty)
        XCTAssertTrue(try XCTUnwrap(scene.bodies.first).triangleStyles.isEmpty)
    }

    func testSameGeometryKeepsBodies() throws {
        let scene = SceneStore()
        let rec = try Fixtures.record("part_box.frame")
        XCTAssertTrue(scene.upsert(rec))
        let gen = try XCTUnwrap(scene.bodies.first).generation
        var again = rec
        again.header.run = 2
        XCTAssertFalse(scene.upsert(again), "gleiche Geometrie")
        XCTAssertEqual(try XCTUnwrap(scene.bodies.first).generation, gen)
        XCTAssertEqual(scene.record("Grundplatte")?.run, 2)
        // Farbe ändert sich ohne neuen Körper
        scene.setDisplayStyle(.xray)
        XCTAssertEqual(try XCTUnwrap(scene.bodies.first).generation, gen)
        XCTAssertLessThan(try XCTUnwrap(scene.bodies.first).color.w, 0.5)
    }

    func testVisibilityIsolateExplode() throws {
        let scene = SceneStore()
        scene.upsert(try Fixtures.record("part_box.frame"), flash: false)
        scene.upsert(try Fixtures.record("part_cylinder.frame"), flash: false)
        XCTAssertEqual(scene.order, ["Grundplatte", "Halter/Bolzen"])
        scene.isolate(["Halter/Bolzen"])
        XCTAssertFalse(scene.isVisible("Grundplatte"))
        XCTAssertEqual(scene.bodies.filter(\.isVisible).count, 1)
        scene.showAll()
        XCTAssertEqual(scene.bodies.filter(\.isVisible).count, 2)
        scene.setVisible(["Grundplatte"], false)
        let vb = try XCTUnwrap(scene.visibleBounds())
        XCTAssertEqual(vb.min.x, 25, accuracy: 1e-3)
        scene.showAll()

        // Gesamtmitte x = (-5 + 35) / 2 = 15; Grundplatte (Mitte 0) wandert um -15, der Bolzen (30) um +15
        scene.setExplode(1)
        let t = scene.worldTransform("Grundplatte").columns.3
        XCTAssertEqual(t.x, -15, accuracy: 1e-4)
        XCTAssertEqual(scene.worldTransform("Halter/Bolzen").columns.3.x, 15, accuracy: 1e-4)
        let body = try XCTUnwrap(scene.bodies.first { scene.owner(ofBody: $0.id)?.part == "Halter/Bolzen" })
        XCTAssertEqual(body.transform.columns.3.x, 15, accuracy: 1e-4)
        let b = try XCTUnwrap(scene.worldBounds(of: [.part("Halter/Bolzen")]))
        XCTAssertEqual(b.min.x, 40, accuracy: 1e-3)
        scene.setExplode(0)
        XCTAssertEqual(scene.worldTransform("Halter/Bolzen"), matrix_identity_float4x4)
    }

    func testRunDimsOldPartsAndRemove() throws {
        let scene = SceneStore()
        scene.upsert(try Fixtures.record("part_box.frame"), flash: false)
        let base = try XCTUnwrap(scene.bodies.first).color
        scene.beginRun(2)
        XCTAssertLessThan(try XCTUnwrap(scene.bodies.first).color.x, base.x)
        var rec = try Fixtures.record("part_box.frame")
        rec.header.run = 2
        scene.upsert(rec, flash: false)
        XCTAssertEqual(try XCTUnwrap(scene.bodies.first).color.x, base.x, accuracy: 1e-5)
        scene.upsert(try Fixtures.record("part_cylinder.frame"), flash: false)  // Lauf 1, also abgedunkelt
        let cyl = try XCTUnwrap(scene.bodies.last)
        XCTAssertLessThan(cyl.color.x, 0.85)
        scene.endRun(2)
        XCTAssertEqual(try XCTUnwrap(scene.bodies.last).color.x, 0.85, accuracy: 1e-5)
        scene.remove("Halter/Bolzen")
        XCTAssertEqual(scene.order, ["Grundplatte"])
        XCTAssertEqual(scene.bodies.count, 1)
    }

    func testNewPartFlashFades() throws {
        let scene = SceneStore()
        scene.upsert(try Fixtures.record("part_box.frame"), now: 100)
        XCTAssertTrue(scene.isAnimating(now: 100.1))
        scene.tick(now: 100.1)
        let flashing = try XCTUnwrap(scene.bodies.first).color
        XCTAssertGreaterThan(flashing.x, 0.72)
        scene.tick(now: 101)
        XCTAssertEqual(try XCTUnwrap(scene.bodies.first).color.x, 0.72, accuracy: 1e-5)
        XCTAssertFalse(scene.isAnimating(now: 101))
    }

    func testHighlightsAndOverlay() throws {
        let scene = SceneStore()
        scene.upsert(try Fixtures.record("part_cylinder.frame"), flash: false)
        let h = scene.addHighlight(
            refs: [.face("Halter/Bolzen", 1), .edge("Halter/Bolzen", 0), .vertex("Halter/Bolzen", 1), .face("Fehlt", 0)],
            color: SIMD4(0, 1, 0, 1), label: "Deckel", clear: true)
        XCTAssertEqual(h.refs.count, 3)
        let body = try XCTUnwrap(scene.bodies.first)
        let face1 = try XCTUnwrap(scene.record("Halter/Bolzen")).geometry.triFace.filter { $0 == 1 }.count
        XCTAssertGreaterThan(face1, 0)
        XCTAssertEqual(body.triangleStyles.filter { $0.color.w > 0 }.count, face1)
        let overlay = scene.elementOverlay()
        XCTAssertEqual(overlay.count, 2)  // Kante und Punkt
        // Bild: hervorgehobene Fläche als eigener Körper eingefärbt
        let snap = scene.snapshotBodies().filter { $0.id != SceneStore.depthHelperID }
        XCTAssertEqual(snap.count, 2)
        XCTAssertTrue(snap.allSatisfy { $0.triangleStyles.isEmpty })
        XCTAssertEqual(snap.reduce(0) { $0 + $1.indices.count / 3 }, 248)
        scene.clearHighlights()
        XCTAssertTrue(try XCTUnwrap(scene.bodies.first).triangleStyles.isEmpty)
        XCTAssertEqual(scene.snapshotBodies().filter { $0.id != SceneStore.depthHelperID }.count, 1)
    }

    func testSectionClipping() throws {
        // Ein Dreieck halb über z = 0: entfernt wird z > 0
        let tri: [Float] = [0, 0, -1, 0, 0, 1, 2, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1]
        let plane = ClipPlane(normal: SIMD3(0, 0, -1), distance: 0)
        let out = SectionClipper.clipTriangles(tri, plane: plane)
        XCTAssertEqual(out.count % 18, 0)
        XCTAssertEqual(out.count / 18, 1)
        var i = 2
        while i < out.count {
            XCTAssertLessThanOrEqual(out[i], 1e-5)
            i += 6
        }
        let lines = SectionClipper.clipPolylines([[SIMD3(0, 0, -1), SIMD3(0, 0, 1), SIMD3(1, 0, -1)]], plane: plane)
        XCTAssertEqual(lines.count, 2)
        XCTAssertEqual(lines[0].last!.z, 0, accuracy: 1e-6)

        let scene = SceneStore()
        scene.upsert(try Fixtures.record("part_box.frame"), flash: false)
        scene.setSection(normal: SIMD3(0, 0, 1), offset: 0)
        XCTAssertEqual(try XCTUnwrap(scene.section).normal, SIMD3(0, 0, -1))
        let snap = scene.snapshotBodies()
        let zs = snap.flatMap { b in stride(from: 2, to: b.vertexData.count, by: 6).map { b.vertexData[$0] } }
        XCTAssertFalse(zs.isEmpty)
        XCTAssertLessThanOrEqual(zs.max() ?? 99, 1e-4)
        scene.setSection(normal: nil, offset: 0)
        XCTAssertNil(scene.section)
    }
}
