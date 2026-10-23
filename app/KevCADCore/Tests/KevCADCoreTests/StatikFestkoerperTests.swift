import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Statik Stufe 3 (PROTOCOL.md „Festkörper (Stufe 3)“): STATICS mit Festkörper und STATICS_FIELD aus den Testdateien
/// (kernel/tools/make_statik_fixtures.py), Farbverlauf als Bänder, verformter Geist, Teil unter dem Feld verdeckt,
/// Abbruch.
final class StatikFestkoerperTests: XCTestCase {
    private func erwartet(_ name: String) throws -> JSONValue {
        let j = try JSONDecoder().decode(JSONValue.self, from: Fixtures.data("statics.json"))
        return try XCTUnwrap(j[name])
    }

    func testFestkoerperUndFeldAusTestdatei() throws {
        guard case .statik(let e) = try Fixtures.message("statics_festkoerper.frame") else { return XCTFail() }
        let soll = try erwartet("statics_festkoerper")
        XCTAssertEqual(e.run, soll["run"]?.intValue)
        XCTAssertEqual(e.aktiv, "Haken 2 kg")
        let sz = try XCTUnwrap(e.szenario("Haken 2 kg"))
        let fk = try XCTUnwrap(sz.festkoerper)
        XCTAssertEqual(fk.stand, "done")
        let t = try XCTUnwrap(fk.teile.first)
        XCTAssertEqual(t.teil, "Wandhalter (Druck)")
        XCTAssertEqual(t.ampel, .rot)
        XCTAssertEqual(t.sicherheit, 1.87)
        XCTAssertEqual(t.kriterium, "schicht")
        XCTAssertEqual(t.ausrichtungBeste, "-z")
        XCTAssertEqual(t.ausrichtungen.first?.1, 4.82)
        XCTAssertEqual(t.feld, "d0f84561664942f7ae15")
        XCTAssertEqual(sz.urteile.first?.art, "festkoerper")
        let laeuft = try XCTUnwrap(e.szenario("Aufstützen 30 kg")?.festkoerper)
        XCTAssertTrue(laeuft.laeuft)
        XCTAssertEqual(laeuft.fortschritt, 0.45, accuracy: 1e-9)
        XCTAssertNil(e.szenario("Eigengewicht")?.festkoerper)

        guard case .statikFeld(let f) = try Fixtures.message("statics_feld.frame") else { return XCTFail() }
        let sf = try erwartet("statics_feld")
        XCTAssertEqual(f.run, sf["run"]?.intValue)
        XCTAssertEqual(f.teil, sf["teil"]?.stringValue)
        XCTAssertEqual(f.schluessel, sf["feld"]?.stringValue)
        XCTAssertEqual(f.punkte.count, sf["punkte"]?.intValue)
        XCTAssertEqual(f.dreiecke.count, 3 * (sf["dreiecke"]?.intValue ?? 0))
        XCTAssertEqual(Double(f.ueberhoehung), sf["ueberhoehung"]?.doubleValue ?? 0, accuracy: 1e-5)
        XCTAssertEqual(Double(f.ausnutzung.max() ?? 0), sf["ausnutzung_max"]?.doubleValue ?? 0, accuracy: 1e-5)
        let v1 = sf["verschiebung_1"]?.doubles ?? []
        XCTAssertEqual(f.verschiebung[1], SIMD3<Float>(v1.map(Float.init)))
        XCTAssertEqual(f.ampel, .rot)
        // kaputte Nutzlast
        let frame = try Fixtures.frame("statics_feld.frame")
        XCTAssertThrowsError(try StatikFeld.decode(header: frame.header, payload: frame.payload.dropLast(4)))
    }

    /// Die Bänder decken die Oberfläche genau ab (Fläche bleibt), jedes Band hat eine Farbe der Skala; die Höhenlinie
    /// zwischen Wand (2,1) und Spitze (0) teilt die Längsseiten in 21 Abschnitte.
    func testBaenderUndVerformung() throws {
        guard case .statikFeld(let f) = try Fixtures.message("statics_feld.frame") else { return XCTFail() }
        func flaeche(_ vd: [Float]) -> Float {
            var s: Float = 0
            for t in stride(from: 0, to: vd.count, by: 18) {
                let a = SIMD3(vd[t], vd[t + 1], vd[t + 2]), b = SIMD3(vd[t + 6], vd[t + 7], vd[t + 8])
                let c = SIMD3(vd[t + 12], vd[t + 13], vd[t + 14])
                s += simd_length(simd_cross(b - a, c - a)) / 2
            }
            return s
        }
        let baender = StatikFeldGeometrie.farbverlauf(f, id: "0")
        XCTAssertEqual(baender.count, StatikFeldGeometrie.baender)  // 0 … 2,1 überstreicht alle Bänder
        XCTAssertTrue(baender.allSatisfy { !$0.isPickable && $0.id.hasPrefix(StatikGeometrie.praefix) })
        let soll: Float = 2 * (80 * 20 + 80 * 8 + 20 * 8)
        XCTAssertEqual(baender.map { flaeche($0.vertexData) }.reduce(0, +), soll, accuracy: soll * 1e-4)
        XCTAssertEqual(baender.first?.color.x ?? 0, StatikGeometrie.farbe(0.05).x, accuracy: 1e-5)
        XCTAssertEqual(StatikFeldGeometrie.band(0.05), 0)
        XCTAssertEqual(StatikFeldGeometrie.band(1.0), 10)
        XCTAssertEqual(StatikFeldGeometrie.band(7), 19)
        XCTAssertEqual(StatikFeldGeometrie.band(.nan), 19)
        let geist = StatikFeldGeometrie.verformung(f, id: "0")
        XCTAssertEqual(geist.count, 1)
        XCTAssertLessThan(geist[0].color.w, 1)
        let zMin = stride(from: 2, to: geist[0].vertexData.count, by: 6).map { geist[0].vertexData[$0] }.min() ?? 0
        XCTAssertEqual(zMin, 96 - 2.4 * f.ueberhoehung, accuracy: 1e-3)  // Spitze überhöht abgesenkt
    }

    /// Großes Feld: Körper werden ab 16 000 Dreiecken geteilt (AP0).
    func testGrosseFelderWerdenGeteilt() throws {
        guard case .statikFeld(var f) = try Fixtures.message("statics_feld.frame") else { return XCTFail() }
        let n = 20_000
        f.punkte = (0..<(3 * n)).map { i in
            SIMD3(Float(i % 3 == 1 ? 1 : 0), Float(i / 3), Float(i % 3 == 2 ? 1 : 0))
        }
        f.dreiecke = (0..<UInt32(3 * n)).map { $0 }
        f.ausnutzung = Array(repeating: 0.5, count: 3 * n)
        f.verschiebung = Array(repeating: .zero, count: 3 * n)
        let b = StatikFeldGeometrie.farbverlauf(f, id: "x")
        XCTAssertEqual(b.count, 2)
        XCTAssertTrue(b.allSatisfy { $0.indices.count / 3 <= 16_000 })
    }

    @MainActor
    func testControllerZeigtFeldStattTeil() throws {
        let c = AppController(model: AppModel())
        c.handle([.connected])
        c.handle([.message(try Fixtures.message("hello.frame"))])
        c.handle([.message(try Fixtures.message("part_box.frame"))])  // „Grundplatte“ steht in der Szene
        // STATICS mit Festkörper, Teil umbenannt auf das Teil der Szene
        let kopf = try Fixtures.frame("statics_festkoerper.frame").header
        let text = String(decoding: kopf, as: UTF8.self).replacingOccurrences(of: "Wandhalter (Druck)", with: "Grundplatte")
        let e = try StatikErgebnis.decode(Data(text.utf8))
        c.applyStatik(e)
        let s = c.model.statik
        XCTAssertEqual(s.szenario?.name, "Haken 2 kg")
        XCTAssertTrue(s.farbverlauf)  // zeigen: der Agent will es sehen
        guard case .statikFeld(var f) = try Fixtures.message("statics_feld.frame") else { return XCTFail() }
        f.teil = "Grundplatte"
        c.applyStatikFeld(f)
        XCTAssertEqual(s.felder(fuer: try XCTUnwrap(s.szenario)).count, 1)
        XCTAssertEqual(c.scene.statikVerdeckt, ["Grundplatte"])
        XCTAssertFalse(c.scene.bodies.filter { $0.id.hasPrefix("Grundplatte") }.isEmpty)
        XCTAssertFalse(c.scene.bodies.filter { $0.id.hasPrefix("Grundplatte") }.contains { $0.isVisible })
        XCTAssertTrue(c.scene.statikBodies.contains { $0.id.hasPrefix(StatikGeometrie.praefix + "f") })
        XCTAssertTrue(c.scene.statikBodies.contains { $0.id.hasPrefix(StatikGeometrie.praefix + "g") })
        XCTAssertNil(c.scene.statikTints["Grundplatte"])
        // Schnappschuss (Bild): Teil fehlt, Feld ist da
        XCTAssertFalse(c.scene.snapshotBodies().contains { $0.id.contains("Grundplatte") })
        // Farbverlauf aus: Teil wieder sichtbar, nur der Geist bleibt
        c.setStatikFarbverlauf(false)
        XCTAssertTrue(c.scene.statikVerdeckt.isEmpty)
        XCTAssertTrue(c.scene.bodies.filter { $0.id.hasPrefix("Grundplatte") }.allSatisfy { $0.isVisible })
        XCTAssertFalse(c.scene.statikBodies.contains { $0.id.hasPrefix(StatikGeometrie.praefix + "f") })
        // Feld mit anderem Schlüssel (veraltet): nicht gezeigt
        c.setStatikFarbverlauf(true)
        f.schluessel = "alt"
        c.applyStatikFeld(f)
        XCTAssertTrue(c.scene.statikVerdeckt.isEmpty)
        // neuer Lauf: Felder verfallen
        f.schluessel = "d0f84561664942f7ae15"
        c.applyStatikFeld(f)
        XCTAssertEqual(c.scene.statikVerdeckt, ["Grundplatte"])
        var neu = e
        neu.run = e.run + 1
        c.applyStatik(neu)
        XCTAssertTrue(s.felder.isEmpty)
        XCTAssertTrue(c.scene.statikVerdeckt.isEmpty)
        // Abbruch ohne Verbindung: nur eine Warnung, kein Absturz
        c.festkoerperAbbrechen()
    }

    func testAbbruchNachricht() throws {
        let frame = try StatikAbbrechenMessage().frame()
        let j = try JSONDecoder().decode(JSONValue.self, from: frame.header)
        XCTAssertEqual(j["type"]?.stringValue, "STATICS_CANCEL")
    }

    // MARK: Stufe 4 (CalculiX)

    /// STATICS mit einem Teil der Stufe 4 (statics_s4.frame): Verfahren, Traglast, Plastizität, Kontakt, Klemmung; die
    /// Teile der Stufe 3 bleiben ohne die neuen Felder.
    func testStufe4AusTestdatei() throws {
        guard case .statik(let e) = try Fixtures.message("statics_s4.frame") else { return XCTFail("kein STATICS") }
        let soll = try erwartet("statics_s4")
        XCTAssertEqual(e.run, soll["run"]?.intValue)
        XCTAssertEqual(e.aktiv, soll["aktiv"]?.stringValue)
        XCTAssertEqual(e.szenarien.map(\.name), soll["szenarien"]?.arrayValue?.compactMap { $0["name"]?.stringValue })
        let sollTeil = try XCTUnwrap(soll["szenarien"]?.arrayValue?.last?["festkoerper"]?["teile"]?.arrayValue?.first)
        let sz = try XCTUnwrap(e.szenario("Haken 2 kg (Kontakt)"))
        let t = try XCTUnwrap(sz.festkoerper?.teile.first)
        XCTAssertEqual(t.teil, sollTeil["teil"]?.stringValue)
        XCTAssertEqual(t.verfahren, sollTeil["verfahren"]?.stringValue)
        XCTAssertTrue(t.istCalculix)
        XCTAssertEqual(t.ampel, .gelb)
        XCTAssertEqual(t.sicherheit, sollTeil["sicherheit"]?.doubleValue)
        XCTAssertEqual(t.feld, sollTeil["feld"]?.stringValue)
        XCTAssertEqual(t.sicherheitLast, 1.12)
        let tl = try XCTUnwrap(t.traglast)
        XCTAssertEqual(tl.faktor, sollTeil["traglast"]?.doubleValue)
        XCTAssertEqual(tl.kriterium, "schicht")
        XCTAssertEqual(tl.text, "Schichtfuge")
        XCTAssertEqual(tl.lastfaktorMax, 12)
        XCTAssertEqual(tl.erreicht, 6.3)
        XCTAssertFalse(tl.nichtErreicht)
        let pl = try XCTUnwrap(t.plastisch)
        XCTAssertEqual(pl.dehnungMax, sollTeil["dehnung_max"]?.doubleValue)
        XCTAssertTrue(pl.fliesst)
        XCTAssertEqual(pl.bleibendMm, 0.12)
        XCTAssertEqual(pl.grenzdehnung, 0.02)
        XCTAssertEqual(pl.ort, SIMD3<Float>(0, -10, 104))
        XCTAssertEqual(t.kontaktPaare.map(\.mit), sollTeil["kontakt_mit"]?.stringList)
        let k = try XCTUnwrap(t.kontaktPaare.first)
        XCTAssertEqual(k.rolle, "lager")
        XCTAssertEqual(k.druckMax, 6.5)
        XCTAssertEqual(k.anteilTraegt, 0.5)
        XCTAssertEqual(k.klaffenMaxMm, 0.08)
        XCTAssertEqual(k.schlupfMaxMm, 0.01)
        XCTAssertEqual(k.gleitetAnteil, 0)
        XCTAssertEqual(t.klemmungen.map(\.schraube), ["Schraube M4"])
        XCTAssertEqual(t.klemmungen.first?.kraftN, 480)
        XCTAssertNil(t.beulfaktor)  // "beulen": null
        XCTAssertFalse(t.rutscht)
        XCTAssertEqual(t.zusatzMax["kontaktdruck"], 6.5)
        XCTAssertEqual(t.zusatzMax["plast_dehnung"], 0.004)
        XCTAssertEqual(t.zusatzMax.count, 4)
        XCTAssertEqual(e.grenzen.count, soll["grenzen"]?.intValue)
        // Stufe 3 im selben Ergebnis: ohne Verfahren und ohne die neuen Felder
        let s3 = try XCTUnwrap(e.szenario("Haken 2 kg")?.festkoerper?.teile.first)
        XCTAssertNil(s3.verfahren)
        XCTAssertFalse(s3.istCalculix)
        XCTAssertNil(s3.traglast)
        XCTAssertNil(s3.plastisch)
        XCTAssertTrue(s3.kontaktPaare.isEmpty && s3.klemmungen.isEmpty && s3.zusatzMax.isEmpty)
        XCTAssertFalse(s3.rutscht)
        // Beulen und Rutschen, wenn gesetzt
        let kopf = try Fixtures.frame("statics_s4.frame").header
        let text = String(decoding: kopf, as: UTF8.self)
            .replacingOccurrences(of: "\"beulen\": null", with: "\"beulen\": {\"faktor\": 3.4}")
            .replacingOccurrences(of: "\"beulen\":null", with: "\"beulen\":{\"faktor\":3.4}")
            .replacingOccurrences(of: "\"rutscht\": false", with: "\"rutscht\": true")
            .replacingOccurrences(of: "\"rutscht\":false", with: "\"rutscht\":true")
        let mit = try XCTUnwrap(StatikErgebnis.decode(Data(text.utf8)).szenario("Haken 2 kg (Kontakt)")?.festkoerper?
            .teile.first)
        XCTAssertEqual(mit.beulfaktor, 3.4)
        XCTAssertTrue(mit.rutscht)
    }

    /// STATICS_FIELD mit Zusatzwerten (statics_feld_s4.frame): Namen in der Reihenfolge der Nutzlast, Länge genau
    /// geprüft, größte Werte aus dem Kopf.
    func testFeldStufe4AusTestdatei() throws {
        guard case .statikFeld(let f) = try Fixtures.message("statics_feld_s4.frame") else { return XCTFail() }
        let soll = try erwartet("statics_feld_s4")
        let frame = try Fixtures.frame("statics_feld_s4.frame")
        XCTAssertEqual(frame.payload.count, soll["payload_bytes"]?.intValue)
        XCTAssertEqual(f.run, soll["run"]?.intValue)
        XCTAssertEqual(f.szenario, soll["szenario"]?.stringValue)
        XCTAssertEqual(f.teil, soll["teil"]?.stringValue)
        XCTAssertEqual(f.schluessel, soll["feld"]?.stringValue)
        XCTAssertEqual(f.punkte.count, soll["punkte"]?.intValue)
        XCTAssertEqual(f.verfahren, "ccx")
        XCTAssertEqual(f.zusatzNamen, soll["zusatz"]?.stringList)
        XCTAssertEqual(f.zusatzNamen, StatikFeldWert.zusatz)
        for name in f.zusatzNamen { XCTAssertEqual(f.zusatz[name]?.count, f.punkte.count) }
        XCTAssertEqual(Double(f.zusatz["kontaktdruck"]?.max() ?? 0), soll["kontaktdruck_max"]?.doubleValue ?? 0,
                       accuracy: 1e-6)
        XCTAssertEqual(Double(f.zusatz["plast_dehnung"]?.max() ?? 0), soll["plast_dehnung_max"]?.doubleValue ?? 0,
                       accuracy: 1e-9)
        XCTAssertEqual(f.groesster("kontaktdruck") ?? 0, 6.5, accuracy: 1e-9)
        XCTAssertEqual(f.groesster("klaffen") ?? 0, 0.08, accuracy: 1e-6)
        XCTAssertEqual(f.groesster("schlupf") ?? 0, 0.01, accuracy: 1e-6)
        XCTAssertNil(f.groesster("ausnutzung"))
        // Kontaktdruck an der Wand unten, Schlupf an der ganzen Wand
        for (i, p) in f.punkte.enumerated() {
            XCTAssertEqual(f.zusatz["kontaktdruck"]?[i], p.x < 1 && p.z < 100 ? 6.5 : 0)
            XCTAssertEqual(f.zusatz["schlupf"]?[i], p.x < 1 ? 0.01 : 0)
        }
        // Grundwerte wie in Stufe 3
        XCTAssertEqual(f.ausnutzung.count, f.punkte.count)
        XCTAssertEqual(f.verschiebung.count, f.punkte.count)
        // Nutzlast zu kurz, zu lang oder ohne Zusatz im Kopf: kaputt
        XCTAssertThrowsError(try StatikFeld.decode(header: frame.header, payload: frame.payload.dropLast(4)))
        XCTAssertThrowsError(try StatikFeld.decode(header: frame.header, payload: frame.payload + Data(count: 4)))
        var kopf = try XCTUnwrap(try JSONDecoder().decode(JSONValue.self, from: frame.header).objectValue)
        kopf["zusatz"] = nil
        kopf["zusatz_max"] = nil
        let ohne = try JSONEncoder().encode(JSONValue.object(kopf))
        XCTAssertThrowsError(try StatikFeld.decode(header: ohne, payload: frame.payload))
        let s3 = try StatikFeld.decode(header: ohne, payload: frame.payload.prefix(frame.payload.count - 4 * 4 * 8))
        XCTAssertTrue(s3.zusatz.isEmpty && s3.zusatzNamen.isEmpty)
        // Zusatzname doppelt: kaputt
        kopf["zusatz"] = .array([.string("klaffen"), .string("klaffen")])
        let doppelt = try JSONEncoder().encode(JSONValue.object(kopf))
        XCTAssertThrowsError(try StatikFeld.decode(header: doppelt, payload: frame.payload.prefix(frame.payload.count - 2 * 4 * 8)))
        // Ohne zusatz_max im Kopf: größter Wert aus den Werten
        kopf["zusatz"] = .array([.string("kontaktdruck")])
        let ohneMax = try JSONEncoder().encode(JSONValue.object(kopf))
        let nurDruck = try StatikFeld.decode(header: ohneMax, payload: frame.payload.prefix(frame.payload.count - 3 * 4 * 8))
        XCTAssertEqual(nurDruck.zusatzMax["kontaktdruck"] ?? 0, 6.5, accuracy: 1e-6)
        // Ältere Felder (Stufe 3) ohne Zusatzwerte
        guard case .statikFeld(let alt) = try Fixtures.message("statics_feld.frame") else { return XCTFail() }
        XCTAssertNil(alt.verfahren)
        XCTAssertTrue(alt.zusatz.isEmpty && alt.zusatzMax.isEmpty)
    }

    /// Farbfeld eines Zusatzwerts: 2 · Wert / größter Wert auf derselben Skala wie die Ausnutzung (größter Wert 0:
    /// alles 0); ohne den Wert bleibt die Ausnutzung.
    func testFarbfeldZusatzwert() throws {
        guard case .statikFeld(var f) = try Fixtures.message("statics_feld_s4.frame") else { return XCTFail() }
        let druck = StatikFeldGeometrie.skalenwerte(f, wert: "kontaktdruck")
        XCTAssertEqual(druck.count, f.punkte.count)
        for (i, v) in druck.enumerated() {
            XCTAssertEqual(v, f.zusatz["kontaktdruck"]![i] > 0 ? 2 : 0, accuracy: 1e-6)
        }
        let dehnung = StatikFeldGeometrie.skalenwerte(f, wert: "plast_dehnung")
        XCTAssertEqual(dehnung.max() ?? 0, 2, accuracy: 1e-5)
        // gemeinsamer Bezug: doppelt so großer größter Wert → halbe Skala
        XCTAssertEqual(StatikFeldGeometrie.skalenwerte(f, wert: "kontaktdruck", groesster: 13).max() ?? 0, 1,
                       accuracy: 1e-6)
        XCTAssertEqual(StatikFeldGeometrie.skalenwerte(f, wert: "ausnutzung"), f.ausnutzung)
        XCTAssertEqual(StatikFeldGeometrie.skalenwerte(f, wert: "unbekannt"), f.ausnutzung)
        // Farben: Wand unten rot (Band 19), Spitze grün (Band 0)
        let baender = StatikFeldGeometrie.farbverlauf(f, id: "0", wert: "kontaktdruck")
        XCTAssertEqual(baender.first?.color.x ?? 0, StatikGeometrie.farbe(0.05).x, accuracy: 1e-5)
        XCTAssertEqual(baender.last?.color.x ?? 0, StatikGeometrie.farbe(1.95).x, accuracy: 1e-5)
        XCTAssertTrue(baender.last?.id.hasSuffix("\u{1F}19\u{1F}0") ?? false)
        // Fläche bleibt, das rote Band ist kleiner als bei der Ausnutzung (nur die untere Wandkante)
        func flaeche(_ b: [ViewportBody]) -> Float {
            b.map { body -> Float in
                let vd = body.vertexData
                var s: Float = 0
                for t in stride(from: 0, to: vd.count, by: 18) {
                    let a = SIMD3(vd[t], vd[t + 1], vd[t + 2]), b = SIMD3(vd[t + 6], vd[t + 7], vd[t + 8])
                    let c = SIMD3(vd[t + 12], vd[t + 13], vd[t + 14])
                    s += simd_length(simd_cross(b - a, c - a)) / 2
                }
                return s
            }.reduce(0, +)
        }
        let aus = StatikFeldGeometrie.farbverlauf(f, id: "0")
        XCTAssertEqual(flaeche(baender), flaeche(aus), accuracy: flaeche(aus) * 1e-4)
        let rot = { (b: [ViewportBody]) in flaeche(b.filter { $0.id.contains("\u{1F}19\u{1F}") }) }
        XCTAssertLessThan(rot(baender), rot(aus))
        // größter Wert 0: alles grün
        f.zusatz["klaffen"] = Array(repeating: 0, count: f.punkte.count)
        f.zusatzMax["klaffen"] = 0
        XCTAssertEqual(StatikFeldGeometrie.skalenwerte(f, wert: "klaffen"), Array(repeating: 0, count: f.punkte.count))
        let gruen = StatikFeldGeometrie.farbverlauf(f, id: "0", wert: "klaffen")
        XCTAssertEqual(Set(gruen.map { $0.id.split(separator: "\u{1F}").dropLast().last.map(String.init) ?? "" }),
                       ["0"])
        // Texte der Skala
        XCTAssertEqual(StatikFeldWert.text("kontaktdruck", 6.5), "6,5 N/mm²")
        XCTAssertEqual(StatikFeldWert.text("plast_dehnung", 0.004), "0,4 %")
        XCTAssertEqual(StatikFeldWert.text("klaffen", 0.08), "0,08 mm")
        XCTAssertEqual(StatikFeldWert.text("schlupf", 0.004), "0,004 mm")
        XCTAssertEqual(StatikFeldWert.text("kontaktdruck", 0), "0 N/mm²")
        XCTAssertEqual(StatikFeldWert.titel("plast_dehnung"), "plastische Dehnung")
    }

    /// Controller: Farbfeld wählen baut die Feldkörper neu; Szenarien ohne den Wert färben nach der Ausnutzung.
    @MainActor
    func testControllerFarbfeldWaehlen() throws {
        let c = AppController(model: AppModel())
        c.handle([.connected])
        c.handle([.message(try Fixtures.message("hello.frame"))])
        c.handle([.message(try Fixtures.message("part_box.frame"))])  // „Grundplatte“ steht in der Szene
        let kopf = try Fixtures.frame("statics_s4.frame").header
        let text = String(decoding: kopf, as: UTF8.self).replacingOccurrences(of: "Wandhalter (Druck)", with: "Grundplatte")
        c.applyStatik(try StatikErgebnis.decode(Data(text.utf8)))
        let s = c.model.statik
        let sz = try XCTUnwrap(s.szenario)
        XCTAssertEqual(sz.name, "Haken 2 kg (Kontakt)")
        XCTAssertEqual(s.feldWerte(fuer: sz), ["ausnutzung"])  // noch kein Feld
        guard case .statikFeld(var f) = try Fixtures.message("statics_feld_s4.frame") else { return XCTFail() }
        f.teil = "Grundplatte"
        c.applyStatikFeld(f)
        XCTAssertEqual(s.feldWerte(fuer: sz), ["ausnutzung"] + StatikFeldWert.zusatz)
        XCTAssertEqual(s.feldWert, "ausnutzung")
        XCTAssertEqual(s.feldGroesster("kontaktdruck", fuer: sz) ?? 0, 6.5, accuracy: 1e-9)
        XCTAssertNil(s.feldGroesster("ausnutzung", fuer: sz))
        func feldKoerper() -> [[Float]] {
            c.scene.statikBodies.filter { $0.id.hasPrefix(StatikGeometrie.praefix + "f") }.map(\.vertexData)
        }
        let nachAusnutzung = feldKoerper()
        XCTAssertFalse(nachAusnutzung.isEmpty)
        c.setStatikFarbverlauf(false)
        c.waehleStatikFeldWert("kontaktdruck")
        XCTAssertEqual(s.feldWert, "kontaktdruck")
        XCTAssertTrue(s.farbverlauf)  // Wählen schaltet den Farbverlauf ein
        XCTAssertEqual(s.wirksamerFeldWert(fuer: sz), "kontaktdruck")
        let nachDruck = feldKoerper()
        XCTAssertFalse(nachDruck.isEmpty)
        XCTAssertNotEqual(nachDruck, nachAusnutzung)
        let soll = StatikFeldGeometrie.farbverlauf(f, id: "0", wert: "kontaktdruck", groesster: 6.5).map(\.vertexData)
        XCTAssertEqual(nachDruck, soll)
        XCTAssertEqual(c.scene.statikVerdeckt, ["Grundplatte"])
        // Szenario der Stufe 3 ohne Feld mit Zusatzwerten: Ausnutzung wirksam, Wahl bleibt gemerkt
        c.waehleStatikSzenario("Haken 2 kg")
        let s3 = try XCTUnwrap(s.szenario)
        XCTAssertEqual(s.wirksamerFeldWert(fuer: s3), "ausnutzung")
        XCTAssertEqual(s.feldWert, "kontaktdruck")
        // unbekannter Wert: zurück zur Ausnutzung
        c.waehleStatikFeldWert("quatsch")
        XCTAssertEqual(s.feldWert, "ausnutzung")
        c.waehleStatikSzenario("Haken 2 kg (Kontakt)")
        XCTAssertEqual(feldKoerper(), nachAusnutzung)
    }
}
