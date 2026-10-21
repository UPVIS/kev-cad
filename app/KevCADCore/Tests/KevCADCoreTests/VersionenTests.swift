import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Versionen: VERSIONEN, VERSION_VERGLEICH und VERSION_BILD_REQ dekodieren (Testdateien aus
/// kernel/tools/make_versionen_fixtures.py), Zeilen der Leiste, Vergleich im Controller, Anfragen der App.
@MainActor
final class VersionenTests: XCTestCase {
    private func erwartet(_ name: String) throws -> JSONValue {
        let all = try JSONDecoder().decode(JSONValue.self, from: Fixtures.data("versionen_fixtures.json"))
        return try XCTUnwrap(all[name])
    }

    func testVersionenFixture() throws {
        let msg = try Fixtures.message("versionen.frame")
        XCTAssertEqual(msg.typeName, "VERSIONEN")
        XCTAssertEqual(msg.replyTo, "a-12")
        guard case .versionen(.liste(let s, _)) = msg else { return XCTFail("kein VERSIONEN") }
        let exp = try erwartet("versionen")
        XCTAssertEqual(s.projekt, "/tmp/kevcad-fixture")
        XCTAssertTrue(s.verfuegbar)
        XCTAssertEqual(s.variante, "v-leicht")
        XCTAssertEqual(s.varianten.map(\.name), ["Hauptstand", "Leichtbau"])
        XCTAssertEqual(s.aktuelleVariante?.id, "v-leicht")
        XCTAssertEqual(s.varianten[1].von, 1)
        XCTAssertEqual(s.versionen.count, exp["versionen"]?.arrayValue?.count)
        XCTAssertEqual(s.anzahl, 7)
        XCTAssertEqual(s.meilensteine, 1)
        XCTAssertTrue(s.ungesichert)
        let v = try XCTUnwrap(s.aktuelleVersion)
        XCTAssertEqual(v.nr, 7)
        XCTAssertEqual(v.wer, .agent)
        XCTAssertEqual(v.werText, "Agent · 3f2a9c")
        XCTAssertEqual(v.meilenstein?.titel, "Halter fertig")
        XCTAssertEqual(v.meilenstein?.notiz, "Bohrungen M6 geprüft")
        XCTAssertEqual(v.anzeigeTitel, "Halter fertig")
        XCTAssertEqual(v.kennzahlen?.teile, 3)
        XCTAssertEqual(v.kennzahlen?.masseKg, 1.25)
        XCTAssertEqual(v.kennzahlen?.kosten, 12.4)
        XCTAssertEqual(v.params, ["breite": 140, "hoehe": 80])
        XCTAssertEqual(v.bild?.path, "/tmp/kevcad-fixture/.kevcad/versionen/bilder/7.png")
        XCTAssertEqual(v.zeit.timeIntervalSince1970, exp["versionen"]?.arrayValue?.first?["ts"]?.doubleValue)
        let w = try XCTUnwrap(s.version(6))
        XCTAssertEqual(w.quelle, "wiederherstellen")
        XCTAssertEqual(w.aus, 2)
        XCTAssertNil(s.version(3)?.kennzahlen)
        XCTAssertEqual(s.version(3)?.nachberechnung, "V3 ließ sich nicht neu rechnen: NameError")
        XCTAssertEqual(s.version(2)?.wer, .unbekannt)
        XCTAssertTrue(s.version(1)?.geerbt ?? false)
        XCTAssertEqual(s.gruppen.map(\.text), ["4 Läufe in 10 Minuten"])
    }

    func testZeilenFassenFolgenZusammen() throws {
        guard case .versionen(.liste(let s, _)) = try Fixtures.message("versionen.frame") else { return XCTFail() }
        let g = try XCTUnwrap(s.gruppen.first)
        let zu = s.zeilen()
        XCTAssertEqual(zu.map(\.id), ["v7", "v6", g.id, "v1"])
        if case .gruppe(let gruppe, let mitglieder) = zu[2] {
            XCTAssertEqual(gruppe.anzahl, 4)
            XCTAssertEqual(mitglieder.map(\.nr), [5, 4, 3, 2])
        } else {
            XCTFail("keine Gruppe")
        }
        let auf = s.zeilen(aufgeklappt: [g.id])
        XCTAssertEqual(auf.map(\.id), ["v7", "v6", g.id, "v5", "v4", "v3", "v2", "v1"])
        if case .version(_, let eingerueckt) = auf[3] { XCTAssertTrue(eingerueckt) } else { XCTFail() }
    }

    func testVergleichFixture() throws {
        let msg = try Fixtures.message("version_vergleich.frame")
        XCTAssertEqual(msg.replyTo, "a-13")
        guard case .versionen(.vergleich(let v, _)) = msg else { return XCTFail("kein VERSION_VERGLEICH") }
        let exp = try erwartet("version_vergleich")
        XCTAssertEqual(v.a.nr, 5)
        XCTAssertNil(v.b.nr)
        XCTAssertEqual(v.b.kurz, "aktueller Stand")
        XCTAssertTrue(v.aktuell)
        XCTAssertEqual(v.zusammenfassung, exp["zusammenfassung"]?.stringValue)
        XCTAssertEqual(v.params, [
            ParameterAenderung(name: "breite", alt: 120, neu: 140, art: "geaendert"),
            ParameterAenderung(name: "hoehe", alt: nil, neu: 80, art: "neu"),
        ])
        XCTAssertEqual(v.teileNeu, ["Deckel"])
        XCTAssertEqual(v.teileWeg, ["Schraube"])
        XCTAssertEqual(v.teileGeaendert.map(\.name), ["Platte"])
        XCTAssertEqual(v.teileGeaendert.first?.arten, ["form"])
        XCTAssertEqual(v.teileGleich, 1)
        XCTAssertEqual(v.stuecklisteNeu.map(\.benennung), ["Alu 3"])
        XCTAssertEqual(v.stuecklisteWeg.map(\.benennung), ["M6"])
        let ge = try XCTUnwrap(v.stuecklisteGeaendert.first)
        XCTAssertEqual(ge.benennung, "Flach 40")
        XCTAssertEqual(ge.altMasseText, "120 mm")
        XCTAssertEqual(ge.masseText, "140 mm")
        XCTAssertEqual(v.pruefungAlt, "in Ordnung")
        XCTAssertEqual(v.pruefungNeu, "1 Durchdringung")
        XCTAssertEqual(v.fehlerAlt, 0)
        XCTAssertEqual(v.fehlerNeu, 1)
        XCTAssertEqual(v.kennzahlenAlt?.teile, 3)
        XCTAssertEqual(v.codeDateien.map(\.pfad), ["model.py", "deckel.py"])
        XCTAssertEqual(v.codeDateien[1].status, "A")
        XCTAssertTrue(v.diff.contains("+breite = 140"))
        XCTAssertEqual(v.hinweise, ["V5 aus dem Zwischenspeicher"])
        XCTAssertEqual(v.ms, 37)
        XCTAssertFalse(v.gleich)
        XCTAssertEqual(v.geometrie.map(\.teil), ["Platte", "Schraube"])
        XCTAssertEqual(v.geometrie.map(\.art), ["alt", "weg"])
        let n = v.geometrie[0]
        XCTAssertEqual(n.vertexCount, 4)
        XCTAssertEqual(n.triangleCount, 2)
        XCTAssertEqual(Array(n.positions.prefix(6)), [0, 0, 5, 20, 0, 5])
        XCTAssertEqual(n.edgeLines.count, 1)
        XCTAssertEqual(n.edgeLines[0], [SIMD3(0, 0, 5), SIMD3(20, 0, 5)])
    }

    func testBildAnfrageUndKaputteNutzlast() throws {
        guard case .versionen(.bildAnfrage(let b)) = try Fixtures.message("version_bild_req.frame") else {
            return XCTFail("kein VERSION_BILD_REQ")
        }
        XCTAssertEqual(b.id, "k-31")
        XCTAssertEqual(b.nr, 7)
        XCTAssertEqual(b.width, 288)
        XCTAssertEqual(b.height, 180)
        XCTAssertEqual(b.view, "iso")
        XCTAssertEqual(b.teile.map(\.teil), ["Platte", "Klotz"])
        XCTAssertEqual(b.teile[0].farbe, SIMD4<Float>(0.8, 0.2, 0.1, 1))
        XCTAssertEqual(b.teile[1].netz.triangleCount, 2)
        let frame = try Fixtures.frame("version_vergleich.frame")
        XCTAssertThrowsError(try VersionMessage.decode(type: "VERSION_VERGLEICH", frame: Frame(
            header: frame.header, payload: frame.payload.dropLast(4))))
        XCTAssertThrowsError(try VersionMessage.decode(type: "VERSION_VERGLEICH", frame: Frame(
            header: frame.header, payload: frame.payload + Data([0, 0, 0, 0]))))
    }

    func testBildRahmenOhneBodenplatte() {
        let boden = BoundingBox(min: SIMD3(-10_000, -3000, -5), max: SIMD3(11_000, 3000, 0))
        let wagen = BoundingBox(min: SIMD3(0, 0, 0), max: SIMD3(610, 410, 250))
        let ball = BoundingBox(min: SIMD3(700, 0, 0), max: SIMD3(917, 217, 217))
        let r = AppController.bildRahmen([boden, wagen, ball])
        XCTAssertEqual(r?.min, SIMD3(0, 0, 0))
        XCTAssertEqual(r?.max, SIMD3(917, 410, 250))
        // zwei Bodenplatten (hell und dunkel, wie im Kugelschieber)
        let dunkel = BoundingBox(min: SIMD3(-3000, -1500, -5), max: SIMD3(3000, 1500, 0))
        XCTAssertEqual(AppController.bildRahmen([boden, dunkel, wagen, ball])?.max, SIMD3(917, 410, 250))
        // ohne Ausreißer bleibt alles drin
        XCTAssertEqual(AppController.bildRahmen([wagen, ball])?.max, SIMD3(917, 410, 250))
        XCTAssertEqual(AppController.bildRahmen([wagen])?.max, wagen.max)
        XCTAssertNil(AppController.bildRahmen([]))
    }

    func testAnfragenDerApp() throws {
        func kopf<M: OutgoingMessage>(_ m: M) throws -> JSONValue {
            try JSONDecoder().decode(JSONValue.self, from: m.encodedHeader())
        }
        let r = try kopf(VersionRestoreMessage(id: "a-1", version: "V12"))
        XCTAssertEqual(r["type"]?.stringValue, "VERSION_RESTORE")
        XCTAssertEqual(r["version"]?.stringValue, "V12")
        let c = try kopf(VersionCompareMessage(id: "a-2", a: "V3", b: nil))
        XCTAssertEqual(c["type"]?.stringValue, "VERSION_COMPARE")
        XCTAssertEqual(c["b"], .null)
        let m = try kopf(VersionMilestoneMessage(id: "a-3", version: nil, titel: "Fertig", notiz: "alles gut"))
        XCTAssertEqual(m["version"], .null)
        XCTAssertEqual(m["titel"]?.stringValue, "Fertig")
        XCTAssertEqual(m["entfernen"]?.boolValue, false)
        let v = try kopf(VariantMessage(id: "a-4", aktion: "umbenennen", name: "v-alt", neuerName: "Neu"))
        XCTAssertEqual(v["aktion"]?.stringValue, "umbenennen")
        XCTAssertEqual(v["neuer_name"]?.stringValue, "Neu")
        XCTAssertEqual(try kopf(VersionenRequestMessage(id: "a-5"))["type"]?.stringValue, "VERSIONEN_REQ")
    }

    func testControllerZeigtVergleichUndBeendetIhn() throws {
        let c = AppController(model: AppModel())
        let events = try FrameReader().feed(Fixtures.data("stream.bin")).map(KernelConnection.decode)
        c.handle(Array(events.prefix(7)))  // HELLO … beide Teile, RUN_END
        XCTAssertNotNil(c.scene.record("Grundplatte"))
        // Liste: nur übernehmen, wenn sie zum offenen Projekt gehört
        guard case .versionen(let liste) = try Fixtures.message("versionen.frame") else { return XCTFail() }
        c.handle([.message(.versionen(liste))])
        XCTAssertNil(c.model.versionen.stand, "Liste eines anderen Projekts")
        let projekt = try XCTUnwrap(c.model.project).path.path
        var s = VersionenStand(projekt: projekt, versionen: [VersionEintrag(nr: 1, zeit: Date(), aktuell: true)])
        s.anzahl = 1
        c.handle([.message(.versionen(.liste(s, replyTo: nil)))])
        XCTAssertEqual(c.model.versionen.stand?.aktuelleVersion?.nr, 1)
        // Vergleich: alte Grundplatte als Geist, Grundplatte orange, Bolzen grün
        let geo: JSONValue = ["teil": "Grundplatte", "art": "alt", "vert": 4, "tri": 2, "epts": 2, "edge": 1]
        let header: JSONValue = [
            "type": "VERSION_VERGLEICH", "a": ["nr": 1, "titel": "Erster Stand"], "b": ["nr": nil, "titel": "Aktuell"],
            "aktuell": true, "zusammenfassung": "Teile: 1 geändert, 1 neu", "params": [],
            "teile": ["neu": ["Halter/Bolzen"], "weg": [], "geaendert": [["name": "Grundplatte", "arten": ["form"]]],
                      "gleich": 0],
            "stueckliste": ["neu": [], "weg": [], "geaendert": []], "code": ["dateien": [], "diff": ""],
            "geometrie": [geo],
        ]
        let vf = try Fixtures.frame("version_vergleich.frame")
        guard case .versionen(.vergleich(let fix, _)) = try KernelMessage.decode(vf) else { return XCTFail() }
        var payload = Data()
        let n = fix.geometrie[0]
        for f in n.positions + n.normals { withUnsafeBytes(of: f.bitPattern.littleEndian) { payload.append(contentsOf: $0) } }
        for i in n.triangles { withUnsafeBytes(of: i.littleEndian) { payload.append(contentsOf: $0) } }
        for f in n.edgePoints { withUnsafeBytes(of: f.bitPattern.littleEndian) { payload.append(contentsOf: $0) } }
        for i in n.edgeOffsets { withUnsafeBytes(of: i.littleEndian) { payload.append(contentsOf: $0) } }
        let msg = try KernelMessage.decode(Frame(header: JSONEncoder().encode(header), payload: payload))
        c.handle([.message(msg)])
        XCTAssertEqual(c.model.versionen.vergleich?.teileGeaendert.map(\.name), ["Grundplatte"])
        XCTAssertEqual(c.scene.vergleichBodies.count, 1)
        XCTAssertFalse(c.scene.vergleichBodies[0].isPickable)
        XCTAssertEqual(c.scene.vergleichBodies[0].color, AppController.vergleichAltFarbe)
        XCTAssertEqual(c.scene.vergleichTints["Grundplatte"], AppController.vergleichGeaendertFarbe)
        XCTAssertEqual(c.scene.vergleichTints["Halter/Bolzen"], AppController.vergleichNeuFarbe)
        XCTAssertTrue(c.scene.renderBodies.contains { $0.id == c.scene.vergleichBodies[0].id })
        XCTAssertTrue(c.scene.snapshotBodies().contains { $0.id == c.scene.vergleichBodies[0].id })
        // Farbe der Grundplatte ist in Richtung Orange verschoben
        let farbe = c.scene.displayColor("Grundplatte", now: 0, includeFlash: false)
        XCTAssertGreaterThan(farbe.x, farbe.z)
        c.endCompare()
        XCTAssertNil(c.model.versionen.vergleich)
        XCTAssertTrue(c.scene.vergleichBodies.isEmpty)
        XCTAssertTrue(c.scene.vergleichTints.isEmpty)
        // Projektwechsel verwirft Liste und Vergleich
        c.handle([.message(msg)])
        c.resetVersionen()
        XCTAssertNil(c.model.versionen.stand)
        XCTAssertTrue(c.scene.vergleichBodies.isEmpty)
    }
}
