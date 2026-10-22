import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Statik (PROTOCOL.md Abschnitt „Statik“): STATICS aus den Testdateien (kernel/tools/make_statik_fixtures.py),
/// Farbverlauf und Verformung im Viewer, Auswahl eines Szenarios.
final class StatikTests: XCTestCase {
    private func erwartet(_ name: String) throws -> JSONValue {
        let j = try JSONDecoder().decode(JSONValue.self, from: Fixtures.data("statics.json"))
        return try XCTUnwrap(j[name])
    }

    func testStaticsAusTestdatei() throws {
        guard case .statik(let e) = try Fixtures.message("statics.frame") else { return XCTFail("kein STATICS") }
        let soll = try erwartet("statics")
        XCTAssertEqual(e.run, soll["run"]?.intValue)
        XCTAssertEqual(e.aktiv, soll["aktiv"]?.stringValue)
        XCTAssertFalse(e.zeigen)
        XCTAssertEqual(e.szenarien.map(\.name), soll["szenarien"]?.arrayValue?.compactMap { $0["name"]?.stringValue })
        XCTAssertEqual(e.ampel, .rot)
        let sz = try XCTUnwrap(e.szenario("Aufstützen 30 kg"))
        XCTAssertEqual(sz.ampel, .rot)
        XCTAssertEqual(sz.urteile.count, 2)
        XCTAssertEqual(sz.auffaellig.first?.ampel, .rot)
        XCTAssertEqual(sz.kennzahlen.sicherheit, 0.2)
        XCTAssertEqual(sz.staebe.first?.punkte.count, 3)
        XCTAssertEqual(sz.staebe.first?.verschiebung.last, SIMD3<Float>(0, 0, -61))
        XCTAssertEqual(sz.teile.map(\.name), ["Rahmen/Rohr", "Rahmen/Halter (Druck)"])
        let eigen = try XCTUnwrap(e.szenario("Eigengewicht"))
        XCTAssertEqual(eigen.kippen.first?.jeRichtung.first?.kippwinkel, 31)
        XCTAssertEqual(eigen.ueberhoehung, 66.7, accuracy: 1e-4)
        XCTAssertEqual(e.grenzen.count, soll["grenzen"]?.intValue)
        guard case .statik(let antwort) = try Fixtures.message("statics_eigengewicht.frame") else { return XCTFail() }
        XCTAssertTrue(antwort.zeigen)
        XCTAssertEqual(antwort.replyTo, "k-12")
        guard case .statik(let fehl) = try Fixtures.message("statics_failed.frame") else { return XCTFail() }
        XCTAssertEqual(fehl.stand, "failed")
        XCTAssertTrue(fehl.szenarien.isEmpty)
    }

    func testFarbverlaufUndVerformung() throws {
        guard case .statik(let e) = try Fixtures.message("statics.frame") else { return XCTFail() }
        let sz = try XCTUnwrap(e.szenario("Aufstützen 30 kg"))
        let nur = StatikGeometrie.koerper(sz, farbverlauf: true, verformung: false)
        XCTAssertEqual(nur.count, 2)  // drei Stationen: zwei Segmente
        XCTAssertTrue(nur.allSatisfy { !$0.isPickable && $0.id.hasPrefix(StatikGeometrie.praefix) })
        // erstes Segment (Ausnutzung 10 → 5): rot; Farben linear
        XCTAssertEqual(nur[0].color.x, StatikGeometrie.farbe(2).x, accuracy: 1e-5)
        let beide = StatikGeometrie.koerper(sz, farbverlauf: true, verformung: true)
        XCTAssertEqual(beide.count, 3)
        let geist = try XCTUnwrap(beide.last)
        XCTAssertLessThan(geist.color.w, 1)
        // Geist mit Überhöhung 1: Spitze 61 mm unter der Ruhelage
        let zMin = stride(from: 2, to: geist.vertexData.count, by: 6).map { geist.vertexData[$0] }.min() ?? 0
        XCTAssertLessThan(zMin, 30 - 61 + 1)
        // Farbe: grün bei 0, gelb bei 1, rot ab 2
        XCTAssertGreaterThan(StatikGeometrie.farbe(0).y, StatikGeometrie.farbe(0).x)
        XCTAssertEqual(StatikGeometrie.farbe(5), StatikGeometrie.farbe(2))
        let toene = StatikGeometrie.toene(sz, bekannt: { $0 == "Rahmen/Rohr" })
        XCTAssertEqual(Array(toene.keys), ["Rahmen/Rohr"])
        let (vd, idx) = StatikGeometrie.rohr([SIMD3(0, 0, 0), SIMD3(100, 0, 0)], radius: 5)
        XCTAssertEqual(vd.count % 6, 0)
        XCTAssertEqual(idx.count % 3, 0)
        XCTAssertTrue(idx.allSatisfy { Int($0) < vd.count / 6 })
    }

    /// Nachbesserung (T32): Lasten mit Angriffspunkt, Kraftpaar mit Gegenseite; im Viewer Pfeile zum Angriffspunkt, das
    /// Paar als zwei gegeneinander gerichtete Pfeile in eigener Farbe.
    func testLastenUndKraftpaar() throws {
        guard case .statik(let e) = try Fixtures.message("statics.frame") else { return XCTFail("kein STATICS") }
        let soll = try erwartet("statics")
        let sz = try XCTUnwrap(e.szenario("Aufstützen 30 kg"))
        let sollLasten = soll["szenarien"]?.arrayValue?.first { $0["name"]?.stringValue == sz.name }?["lasten"]?
            .arrayValue ?? []
        XCTAssertEqual(sz.lasten.count, sollLasten.count)
        XCTAssertEqual(sz.lasten.map(\.paar), sollLasten.map { $0["paar"]?.boolValue ?? false })
        let paar = try XCTUnwrap(sz.lasten.first { $0.paar })
        XCTAssertEqual(paar.gegen, ["Ball"])
        XCTAssertEqual(paar.teile, ["Rahmen/Rohr"])
        XCTAssertEqual(paar.kraft, SIMD3<Float>(100, 0, 0))
        XCTAssertEqual(paar.punkt, SIMD3<Float>(500, 0, 30))
        XCTAssertTrue(try XCTUnwrap(e.szenario("Eigengewicht")).lasten.isEmpty)
        // Viewer: eine äußere Last ein Pfeil, das Paar zwei (beide enden am Angriffspunkt, entgegengesetzt)
        let pf = StatikGeometrie.lastpfeile(sz.lasten)
        XCTAssertEqual(pf.count, 3)
        XCTAssertTrue(pf.allSatisfy { !$0.isPickable && $0.id.hasPrefix(StatikGeometrie.praefix) })
        let violett = PartBodies.linear(StatikGeometrie.paarFarbe)
        let paarKoerper = pf.filter { $0.color == violett }
        XCTAssertEqual(paarKoerper.count, 2)
        func ecken(_ b: ViewportBody) -> [SIMD3<Float>] {
            stride(from: 0, to: b.vertexData.count, by: 6).map {
                SIMD3<Float>(b.vertexData[$0], b.vertexData[$0 + 1], b.vertexData[$0 + 2])
            }
        }
        for b in paarKoerper {
            XCTAssertLessThan(ecken(b).map { simd_distance($0, paar.punkt) }.min() ?? 99, 1e-3)  // Spitze am Punkt
        }
        // Kraft auf das Rohr kommt von −x, die Gegenkraft von +x
        let xs = paarKoerper.map { ecken($0).map(\.x).reduce(0, +) / Float(ecken($0).count) }.sorted()
        XCTAssertLessThan(xs[0], paar.punkt.x)
        XCTAssertGreaterThan(xs[1], paar.punkt.x)
        XCTAssertTrue(StatikGeometrie.lastpfeile([]).isEmpty)
    }

    /// Stufe 2: Szenario mit Ablauf (statics_ablauf.frame): Kennzahlen, Verlauf, Kontaktpfeile als Körper.
    func testAblaufAusTestdatei() throws {
        guard case .statik(let e) = try Fixtures.message("statics_ablauf.frame") else { return XCTFail("kein STATICS") }
        let soll = try erwartet("statics_ablauf")
        XCTAssertEqual(e.aktiv, "Bremsen aus 1 m/s")
        XCTAssertTrue(e.zeigen)
        let sz = try XCTUnwrap(e.szenario("Bremsen aus 1 m/s"))
        let ab = try XCTUnwrap(sz.ablauf)
        let sollAb = soll["szenarien"]?.arrayValue?.compactMap { $0["ablauf"] }.first
        XCTAssertEqual(ab.animation, sollAb?["animation"]?.stringValue)
        XCTAssertEqual(ab.bilder, sollAb?["bilder"]?.intValue)
        XCTAssertEqual(ab.kippreserve, sollAb?["kippreserve"]?.doubleValue)
        XCTAssertEqual(ab.pfeile.map(\.count), sollAb?["pfeile"]?.arrayValue?.compactMap(\.intValue))
        XCTAssertEqual(ab.ladung.map(\.name), ["Bowlingball"])
        XCTAssertEqual(ab.ladung.first?.vGrenze, 1.12)
        XCTAssertTrue(ab.fertig)
        XCTAssertEqual(ab.ampel, .rot)
        XCTAssertEqual(ab.aKippHand, 14.1)
        XCTAssertEqual(ab.zeit.count, ab.kipp.count)
        XCTAssertEqual(ab.bild(zur: 0.021), 1)
        XCTAssertEqual(ab.bild(zur: 5), 2)
        XCTAssertEqual(ab.kraftMax, simd_length(SIMD3<Float>(0, 0, 156.5)), accuracy: 1e-3)
        XCTAssertEqual(sz.urteile.first?.art, "dyn_kippen")
        // Szenarien ohne Ablauf haben keinen
        XCTAssertNil(e.szenario("Eigengewicht")?.ablauf)
        // Pfeile: einer je Kontaktkraft, enden am Angriffspunkt
        let pf = StatikGeometrie.pfeile(ab.pfeile[2], kraftMax: ab.kraftMax)
        XCTAssertEqual(pf.count, 2)
        XCTAssertTrue(pf.allSatisfy { !$0.isPickable && $0.id.hasPrefix(StatikGeometrie.praefix) })
        let p0 = ab.pfeile[2][1].punkt
        let ecken = stride(from: 0, to: pf[1].vertexData.count, by: 6).map {
            SIMD3<Float>(pf[1].vertexData[$0], pf[1].vertexData[$0 + 1], pf[1].vertexData[$0 + 2])
        }
        XCTAssertLessThan(ecken.map { simd_distance($0, p0) }.min() ?? 99, 1e-3)  // Spitze am Punkt
        XCTAssertTrue(pf[1].indices.allSatisfy { Int($0) < ecken.count })
        XCTAssertTrue(StatikGeometrie.pfeile(ab.pfeile[0], kraftMax: ab.kraftMax).isEmpty)
    }

    @MainActor
    func testAblaufZeigenUndPfeile() throws {
        let c = AppController(model: AppModel())
        c.handle([.connected])
        c.handle([.message(try Fixtures.message("hello.frame"))])
        c.handle([.message(try Fixtures.message("statics_ablauf.frame"))])
        XCTAssertEqual(c.model.statik.szenario?.name, "Bremsen aus 1 m/s")
        // Ohne geladene Animation passiert nichts (nur eine Warnung)
        c.zeigeAblauf("Bremsen aus 1 m/s")
        XCTAssertNil(c.model.animation.selected)
        XCTAssertTrue(c.scene.ablaufBodies.isEmpty)
        // ANIM_DEF des Ablaufs (3 Bilder, ein Teil in Ruhe): „Ablauf zeigen“ wählt und spielt ihn
        let kopf: [String: Any] = [
            "type": "ANIM_DEF", "name": "Ablauf: Bremsen aus 1 m/s", "run": 9, "dauer": 0.04, "fps": 50.0,
            "bilder": 3, "teile": ["Bowlingball"], "kamera": false, "sichtbar": [], "standard": false,
            "warnungen": [], "spuren": 0, "ablauf": true,
        ]
        var werte: [Float] = []
        for _ in 0..<3 { werte += [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0] }
        let nutz = werte.withUnsafeBufferPointer { Data(buffer: $0) }
        let clip = try AnimationClip.decode(header: try JSONSerialization.data(withJSONObject: kopf), payload: nutz)
        c.handleAnimation(.definition(clip))
        c.zeigeAblauf("Bremsen aus 1 m/s")
        XCTAssertEqual(c.model.animation.selected, "Ablauf: Bremsen aus 1 m/s")
        XCTAssertTrue(c.model.animation.playing)
        c.seekAnimation(to: 0.04)  // letztes Bild: zwei Kontaktkräfte
        XCTAssertEqual(c.scene.ablaufBodies.count, 2)
        c.seekAnimation(to: 0.0)  // erstes Bild: keine Kraft
        XCTAssertTrue(c.scene.ablaufBodies.isEmpty)
        c.seekAnimation(to: 0.04)
        c.setKontaktpfeile(false)
        XCTAssertFalse(c.model.statik.kontaktpfeile)
        XCTAssertTrue(c.scene.ablaufBodies.isEmpty)
        c.resetAnimationPose()  // Ruhelage: keine Pfeile
        c.setKontaktpfeile(true)
        XCTAssertTrue(c.scene.ablaufBodies.isEmpty)
    }

    @MainActor
    func testControllerZeigtGewaehltesSzenario() throws {
        let c = AppController(model: AppModel())
        c.handle([.connected])
        c.handle([.message(try Fixtures.message("hello.frame"))])
        c.handle([.message(try Fixtures.message("statics.frame"))])
        let s = c.model.statik
        XCTAssertEqual(s.szenario?.name, "Aufstützen 30 kg")
        XCTAssertFalse(s.farbverlauf)
        XCTAssertTrue(c.scene.statikBodies.isEmpty)  // nach einem Lauf nichts einfärben, bis Kevin es will
        c.waehleStatikSzenario("Eigengewicht")
        XCTAssertTrue(s.farbverlauf)
        XCTAssertEqual(c.scene.statikBodies.count, 2)
        c.setStatikVerformung(true)
        XCTAssertEqual(c.scene.statikBodies.count, 3)
        c.setStatikFarbverlauf(false)
        c.setStatikVerformung(false)
        XCTAssertTrue(c.scene.statikBodies.isEmpty)
        // Der Agent will ein Szenario sehen: Farbverlauf und Verformung an
        c.handle([.message(try Fixtures.message("statics_eigengewicht.frame"))])
        XCTAssertEqual(s.szenario?.name, "Eigengewicht")
        XCTAssertTrue(s.farbverlauf && s.verformung)
        XCTAssertEqual(c.scene.statikBodies.count, 3)
        // Szenario mit Lasten: dazu je Last ein Pfeil, das Kraftpaar mit zwei Pfeilen
        c.waehleStatikSzenario("Aufstützen 30 kg")
        XCTAssertEqual(c.scene.statikBodies.filter { $0.id.hasPrefix(StatikGeometrie.praefix + "l") }.count, 3)
        c.setStatikFarbverlauf(false)
        XCTAssertFalse(c.scene.statikBodies.contains { $0.id.hasPrefix(StatikGeometrie.praefix + "l") })
    }
}
