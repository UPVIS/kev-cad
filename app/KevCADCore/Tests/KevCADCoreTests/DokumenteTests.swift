import CoreGraphics
import Foundation
import PDFKit
import XCTest

@testable import KevCADCore

/// Phase 6, Zeichnungen (DOKUMENTE.md): Decoder gegen die Testdateien des Kernels, Encoder der Anfragen, BlattZeichner
/// (Linienbreiten, Strichmuster, Schriftgröße in pt, Seitengrößen, Clip der Schraffur, PDF) und Rückgängig.
/// Länge einer Polylinie (Hilfsfunktion der Tests).
private func MassVorschau_laenge(_ pl: [CGPoint]) -> CGFloat {
    zip(pl, pl.dropFirst()).reduce(0) { $0 + hypot($1.1.x - $1.0.x, $1.1.y - $1.0.y) }
}

final class DokumenteTests: XCTestCase {
    private func erwartet() throws -> JSONValue {
        try XCTUnwrap(Fixtures.expected()["dokumente"])
    }

    private func zeichnung(_ datei: String) throws -> (Zeichnung, String?) {
        guard case .dokumente(.drawing(let z, let r)) = try Fixtures.message(datei) else {
            throw XCTSkip("\(datei) ist kein DRAWING")
        }
        return (z, r)
    }

    // MARK: Decoder

    func testDrawingFixture() throws {
        let e = try XCTUnwrap(erwartet()["drawing"])
        let (z, reply) = try zeichnung("drawing.frame")
        XCTAssertEqual(reply, e["reply_to"]?.stringValue)
        XCTAssertEqual(z.id, e["blatt_id"]?.stringValue)
        XCTAssertEqual(z.blatt.format, e["format"]?.stringValue)
        XCTAssertEqual(z.blatt.ausrichtung, e["ausrichtung"]?.stringValue)
        XCTAssertEqual(z.blatt.massstab, e["massstab"]?.stringValue)
        let g = try XCTUnwrap(e["blattgroesse"]?.doubles)
        XCTAssertEqual(Double(z.groesse.width), g[0])
        XCTAssertEqual(Double(z.groesse.height), g[1])
        XCTAssertEqual(z.linienReihenfolge, e["linien_reihenfolge"]?.stringList)
        let geo = try XCTUnwrap(e["geometrie"]?.arrayValue)
        XCTAssertEqual(z.gruppen.map(\.id), geo.compactMap { $0["id"]?.stringValue })
        XCTAssertEqual(z.gruppen.map(\.art), geo.compactMap { $0["art"]?.stringValue })
        for (gruppe, eg) in zip(z.gruppen, geo) {
            for (art, n) in eg["linien"]?.objectValue ?? [:] {
                XCTAssertEqual(gruppe.linien[art]?.count ?? 0, n.intValue, "\(gruppe.id).\(art)")
            }
        }
        XCTAssertTrue(z.gruppen.last?.istBlatt == true)
        // erste Polylinie in Vertragsreihenfolge
        let erste = try XCTUnwrap(z.gruppen.lazy.flatMap { gr in z.linienReihenfolge.flatMap { gr.linien[$0] ?? [] } }.first)
        let p = try XCTUnwrap(e["erster_punkt"]?.doubles)
        XCTAssertEqual(Double(erste[0].x), p[0], accuracy: 1e-3)
        XCTAssertEqual(Double(erste[0].y), p[1], accuracy: 1e-3)
        XCTAssertEqual(z.masse.count, e["masse"]?.intValue)
        let m0 = try XCTUnwrap(e["erstes_mass"])
        XCTAssertEqual(z.masse[0].id, m0["id"]?.stringValue)
        XCTAssertEqual(z.masse[0].text, m0["text"]?.stringValue)
        XCTAssertEqual(z.masse[0].wert, m0["wert"]?.doubleValue)
        XCTAssertEqual(z.masse[0].textWinkel, m0["text_winkel"]?.doubleValue)
        XCTAssertEqual(z.masse.map(\.text).sorted(), e["masstexte"]?.stringList)
        XCTAssertEqual(z.texte.count, e["texte"]?.intValue)
        XCTAssertEqual(z.gefuellt.count, e["gefuellt"]?.intValue)
        // Maß 1: Hüllmaß 200 mit zwei Pfeilen, Pfeilpolygon, Textbox
        let m1 = z.masse[0]
        XCTAssertEqual(m1.pfeile.count, 2)
        XCTAssertEqual(m1.pfeile[0].polygon.count, 4)
        XCTAssertNotNil(m1.box)
        XCTAssertEqual(m1.quelle, "auto")
        // Blattdatei: Bezüge, Anker, Schriftfeld (gegen den Rohkopf, damit neu erzeugte Testdateien passen)
        let roh = try JSONDecoder().decode(JSONValue.self, from: Fixtures.frame("drawing.frame").header)
        let rm = try XCTUnwrap(roh["blatt"]?["masse"]?.arrayValue?.first)
        let bm = try XCTUnwrap(z.blatt.mass("m1"))
        XCTAssertEqual(bm.versatz, rm["versatz"]?.doubleValue)
        XCTAssertEqual(bm.richtung, rm["richtung"]?.stringValue)
        XCTAssertEqual(bm.anker.count, rm["anker"]?.arrayValue?.count)
        XCTAssertEqual(bm.bezuege.count, rm["bezuege"]?.arrayValue?.count)
        XCTAssertEqual(z.blatt.schriftfeldText("zeichnungsnummer"), roh["blatt"]?["schriftfeld"]?["zeichnungsnummer"]?.stringValue)
        let lage = try XCTUnwrap(roh["blatt"]?["ansichten"]?.arrayValue?.first?["lage"]?.doubles)
        XCTAssertEqual(z.blatt.ansichten.first?.lage, CGPoint(x: lage[0], y: lage[1]))
        // steigende Bemaßung: Zahlen je Lage
        let kette = try XCTUnwrap(z.masse.first { $0.art == "bezugskette" })
        let rohKette = try XCTUnwrap(roh["masse"]?.arrayValue?.first { $0["art"]?.stringValue == "bezugskette" })
        XCTAssertEqual(kette.texte.count, rohKette["texte"]?.arrayValue?.count)
        XCTAssertGreaterThan(kette.texte.count, 0)
        XCTAssertEqual(kette.pfeile.first?.art, "ursprung")
    }

    func testDrawingTubeFixture() throws {
        let e = try XCTUnwrap(erwartet()["drawing_tube"])
        let (z, reply) = try zeichnung("drawing_tube.frame")
        XCTAssertNil(reply)
        XCTAssertEqual(z.id, e["blatt_id"]?.stringValue)
        XCTAssertEqual(z.gruppen.reduce(0) { $0 + ($1.linien["bruch"]?.count ?? 0) }, e["bruch"]?.intValue)
        XCTAssertEqual(z.masse.map(\.text).sorted(), e["masstexte"]?.stringList)
        XCTAssertEqual(try Fixtures.frame("drawing_tube.frame").payload.count, e["payload_bytes"]?.intValue)
        // unbekannte bzw. neue Linienart bruch wird gezeichnet (dünn)
        XCTAssertEqual(LinienStil.fuer("bruch").breite, LinienStil.schmal)
        XCTAssertEqual(LinienStil.fuer("gibt-es-nicht").breite, LinienStil.schmal)
        XCTAssertNil(LinienStil.fuer("gibt-es-nicht").muster)
    }

    func testDocsFixtures() throws {
        let e = try XCTUnwrap(erwartet()["docs"])
        guard case .dokumente(.docs(let d, let r)) = try Fixtures.message("docs.frame") else { return XCTFail("kein DOCS") }
        XCTAssertNil(r)
        XCTAssertEqual(d.run, e["run"]?.intValue)
        XCTAssertEqual(d.blaetter.map(\.id), e["blaetter"]?.stringList)
        XCTAssertEqual(d.blaetter.first?.masse, 6)
        XCTAssertEqual(d.blaetter.first?.formatText, "A4 quer")
        XCTAssertEqual(d.einzelteile.count, 2)
        XCTAssertNil(d.bauplan)

        let b = try XCTUnwrap(Fixtures.expected()["bauplan"]?["docs"])
        guard case .dokumente(.docs(let d2, _)) = try Fixtures.message("docs_bauplan.frame") else {
            return XCTFail("kein DOCS")
        }
        let bp = try XCTUnwrap(d2.bauplan)
        XCTAssertEqual(bp.schritte, b["schritte"]?.intValue)
        XCTAssertEqual(bp.probleme, b["probleme"]?.intValue)
        XCTAssertEqual(bp.abschnitte.map(\.art), ["material", "zuschnitt", "bearbeiten", "drucken", "montage"])
    }

    func testStoreErkenntVeralteteBlaetter() async throws {
        let (z, _) = try zeichnung("drawing.frame")
        await MainActor.run {
            let store = DokumenteStore()
            store.zeichnungen[z.id] = z
            store.uebersicht = DocsUebersicht(run: 8, blaetter: [BlattEintrag(id: z.id, titel: "Platte", stand: z.stand)])
            XCTAssertFalse(store.istVeraltet(z.id))
            store.uebersicht = DocsUebersicht(run: 9, blaetter: [BlattEintrag(id: z.id, titel: "Platte", stand: "neu")])
            XCTAssertTrue(store.istVeraltet(z.id))
        }
    }

    // MARK: Nutzlast

    func testPolylinienNutzlast() throws {
        var d = Data()
        func u32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        func f32(_ v: Float) { withUnsafeBytes(of: v.bitPattern.littleEndian) { d.append(contentsOf: $0) } }
        // Gruppe 1: a = 1 Polylinie mit 2 Punkten, b = 0; Gruppe 2: a = 0, b = 1 Polylinie mit 3 Punkten
        u32(1); u32(2); f32(1); f32(2); f32(3); f32(4)
        u32(0)
        u32(0)
        u32(1); u32(3); f32(0); f32(0); f32(1); f32(0); f32(1); f32(1)
        let g = try PolylinienNutzlast.lesen(d, gruppen: 2, reihenfolge: ["a", "b"])
        XCTAssertEqual(g.count, 2)
        XCTAssertEqual(g[0]["a"]?.first, [CGPoint(x: 1, y: 2), CGPoint(x: 3, y: 4)])
        XCTAssertEqual(g[1]["b"]?.first?.count, 3)
        XCTAssertThrowsError(try PolylinienNutzlast.lesen(d.dropLast(4), gruppen: 2, reihenfolge: ["a", "b"]))
        XCTAssertThrowsError(try PolylinienNutzlast.lesen(d + Data([0]), gruppen: 2, reihenfolge: ["a", "b"]))
    }

    // MARK: Encoder

    func testDrawingRequestEncoder() throws {
        let f = try Fixtures.frame("drawing_req.frame")
        var m = DrawingRequestMessage(id: "a-11", blatt: "platte")
        m.seq = 5
        XCTAssertEqual(try JSONDecoder().decode(JSONValue.self, from: m.encodedHeader()),
                       try JSONDecoder().decode(JSONValue.self, from: f.header))
        let docs = try JSONDecoder().decode(JSONValue.self, from: DocsRequestMessage(id: "a-1").encodedHeader())
        XCTAssertEqual(docs["type"], "DOCS_REQ")
        XCTAssertEqual(docs["id"], "a-1")
    }

    func testDrawingEditEncoder() throws {
        let f = try Fixtures.frame("drawing_edit.frame")
        let ops: [ZeichnungsOp] = [
            .massVerschieben(id: "m1", versatz: -18, textLage: nil),
            .massVerschieben(id: "m3", versatz: nil, textLage: CGPoint(x: 120.5, y: 80.25)),
            .massLoeschen(id: "m2"),
            .massNeu(art: "linear", ansicht: "v1", richtung: "x", versatz: 20,
                     klicks: [ZeichnungsKlick(ansicht: "v1", punkt: CGPoint(x: 40, y: 100)),
                              ZeichnungsKlick(ansicht: "v1", punkt: CGPoint(x: 60, y: 100))],
                     bezuege: [], text: nil, toleranz: nil),
            .ansichtNeu(art: "iso", lage: CGPoint(x: 230, y: 150)),
            .ansichtVerschieben(id: "v1", lage: CGPoint(x: 120, y: 110)),
            .ansichtLoeschen(id: "v2"),
            .massstab("1:2"),
            .notiz(text: "Grat entfernen", lage: CGPoint(x: 30, y: 30),
                   zeiger: ZeichnungsKlick(ansicht: "v1", punkt: CGPoint(x: 50, y: 90))),
            .notizLoeschen(id: "n1"),
            .schriftfeld(feld: "freigegeben", wert: "Kevin Schwed"),
            .auto(ansichten: true, masse: true, zuruecksetzen: false),
            .unterdrueckungAufheben(index: 0),
        ]
        var m = DrawingEditMessage(id: "a-12", blatt: "platte", ops: ops)
        m.seq = 6
        let ich = try JSONDecoder().decode(JSONValue.self, from: m.encodedHeader())
        let kernel = try JSONDecoder().decode(JSONValue.self, from: f.header)
        XCTAssertEqual(ich, kernel)
        XCTAssertEqual(ops.map(\.name), try erwartet()["drawing_edit"]?["ops"]?.stringList)
        // Zusätze aus dem Anhang
        XCTAssertEqual(ZeichnungsOp.format("A3", ausrichtung: "quer").json,
                       ["op": "format", "wert": "A3", "ausrichtung": "quer"])
        XCTAssertEqual(ZeichnungsOp.massAendern(id: "m4", text: "<> H7", toleranz: nil, fest: true).json,
                       ["op": "mass_aendern", "id": "m4", "text": "<> H7", "fest": true])
    }

    /// DRAWING_CREATE (Vertrag 1.2): mit Teilen und Format, ohne Teile für alle gefertigten Teile.
    func testDrawingCreateEncoder() throws {
        let f = try Fixtures.frame("drawing_create.frame")
        var m = DrawingCreateMessage(id: "a-13", teile: ["Halter/Platte"], art: "teil", format: "A3 quer")
        m.seq = 7
        XCTAssertEqual(try JSONDecoder().decode(JSONValue.self, from: m.encodedHeader()),
                       try JSONDecoder().decode(JSONValue.self, from: f.header))
        let e = try XCTUnwrap(erwartet()["drawing_create"])
        XCTAssertEqual(e["teile"]?.stringList, m.teile)
        XCTAssertEqual(e["format"]?.stringValue, m.format)
        let alle = try JSONDecoder().decode(JSONValue.self, from: DrawingCreateMessage(id: "a-4").encodedHeader())
        XCTAssertNil(alle["teile"])
        XCTAssertNil(alle["format"])
        XCTAssertEqual(alle["art"], "teil")
    }

    func testAckMitErgebnissen() throws {
        let h = #"{"type":"ACK","seq":3,"reply_to":"a-12","ok":false,"message":"mass_neu: kein Element","ergebnisse":[{"op":"mass_verschieben","ok":true,"id":"m1"},{"op":"mass_neu","ok":false,"fehler":"kein Element"}]}"#
        guard case .ack(let a) = try KernelMessage.decode(Frame(header: Data(h.utf8))) else { return XCTFail() }
        let b = ZeichnungsBearbeitung(ok: a.ok, meldung: a.message, ergebnisse: a.ergebnisse)
        XCTAssertEqual(b.ergebnisse.count, 2)
        XCTAssertEqual(b.ergebnisse[0].id, "m1")
        XCTAssertEqual(b.fehlerText, "kein Element")
    }

    /// Schnitt und Einzelheit aus der App (Vertrag 1.3): gezogene Linie bzw. Kreis in Blatt-mm, Blickrichtung umkehren.
    func testSchnittUndEinzelheitEncoder() throws {
        let s = ZeichnungsOp.schnittNeu(von: "v1", linie: [CGPoint(x: 10, y: 20), CGPoint(x: 90, y: 20)], umkehren: true)
        XCTAssertEqual(s.json, ["op": "ansicht_neu", "art": "schnitt",
                                "schnitt": ["von": "v1", "linie": [[10, 20], [90, 20]], "umkehren": true]])
        XCTAssertNil(ZeichnungsOp.schnittNeu(von: nil, linie: [.zero, CGPoint(x: 1, y: 0)]).json["schnitt"]?["umkehren"])
        XCTAssertEqual(ZeichnungsOp.einzelheitNeu(von: "v2", mitte: CGPoint(x: 50, y: 40), radius: 7.5).json,
                       ["op": "ansicht_neu", "art": "einzelheit",
                        "einzelheit": ["von": "v2", "kreis": ["mitte": [50, 40], "radius": 7.5]]])
        XCTAssertEqual(ZeichnungsOp.schnittUmkehren(id: "v4").json, ["op": "schnitt_umkehren", "id": "v4"])
        XCTAssertEqual(s.titel, "Schnitt anlegen")
        // Rückgängig: neue Ansicht mit der Kennung aus dem ACK löschen; Umkehren kehrt sich selbst um
        let (z, _) = try zeichnung("drawing.frame")
        let neu = ZeichnungsBearbeitung(ok: true, ergebnisse: [["op": "ansicht_neu", "ok": true, "id": "v7"]])
        XCTAssertEqual(ZeichnungsUmkehr.gegen([s], vorher: z, bearbeitung: neu), [.ansichtLoeschen(id: "v7")])
        let um = ZeichnungsBearbeitung(ok: true, ergebnisse: [["op": "schnitt_umkehren", "ok": true, "id": "v4"]])
        XCTAssertEqual(ZeichnungsUmkehr.gegen([.schnittUmkehren(id: "v4")], vorher: z, bearbeitung: um),
                       [.schnittUmkehren(id: "v4")])
    }

    // MARK: Rückgängig

    func testUmkehr() throws {
        let (z, _) = try zeichnung("drawing.frame")
        let ok = ZeichnungsBearbeitung(ok: true, ergebnisse: [["op": "mass_verschieben", "ok": true, "id": "m1"]])
        // Verschieben eines automatischen Maßes: alter Versatz, danach wieder nicht fest
        let alt = try XCTUnwrap(z.blatt.mass("m1")?.versatz)
        XCTAssertEqual(z.blatt.mass("m1")?.fest, false)
        XCTAssertEqual(
            ZeichnungsUmkehr.gegen([.massVerschieben(id: "m1", versatz: alt - 12, textLage: nil)], vorher: z, bearbeitung: ok),
            [.massVerschieben(id: "m1", versatz: alt, textLage: nil),
             .massAendern(id: "m1", text: nil, toleranz: nil, fest: false)])
        // Löschen eines automatischen Maßes: Unterdrückung (am Ende der Liste) aufheben
        let weg = ZeichnungsBearbeitung(ok: true, ergebnisse: [["op": "mass_loeschen", "ok": true, "id": "m2"]])
        XCTAssertEqual(ZeichnungsUmkehr.gegen([.massLoeschen(id: "m2")], vorher: z, bearbeitung: weg),
                       [.unterdrueckungAufheben(index: z.blatt.unterdrueckt.count)])
        // Neues Maß: mit der Kennung aus dem ACK löschen
        let neu = ZeichnungsBearbeitung(ok: true, ergebnisse: [["op": "mass_neu", "ok": true, "id": "m9"]])
        let op = ZeichnungsOp.massNeu(art: nil, ansicht: "v1", richtung: "x", versatz: 12, klicks: [], bezuege: [],
                                      text: nil, toleranz: nil)
        XCTAssertEqual(ZeichnungsUmkehr.gegen([op], vorher: z, bearbeitung: neu), [.massLoeschen(id: "m9")])
        // Ansicht löschen lässt sich nicht umkehren (dafür gibt es die Versionen)
        XCTAssertNil(ZeichnungsUmkehr.gegen([.ansichtLoeschen(id: "v1")], vorher: z, bearbeitung: ok))
        // Schriftfeld: alter Wert, auch null
        XCTAssertEqual(ZeichnungsUmkehr.gegen([.schriftfeld(feld: "freigegeben", wert: "Kevin")], vorher: z,
                                              bearbeitung: ok), [.schriftfeld(feld: "freigegeben", wert: .null)])
    }

    // MARK: BlattZeichner

    func testLinienbreitenNachISO128() {
        XCTAssertEqual(LinienStil.fuer("sichtbar").breite, 0.5)
        XCTAssertEqual(LinienStil.fuer("verdeckt").breite, 0.25)
        XCTAssertEqual(LinienStil.fuer("mitte").breite, 0.25)
        XCTAssertEqual(LinienStil.fuer("schnitt").breite, 0.5)
        XCTAssertEqual(LinienStil.fuer("duenn").breite, 0.25)
        XCTAssertEqual(LinienStil.fuer("schraffur").breite, 0.25)
        XCTAssertEqual(LinienStil.fuer("sichtbar", blatt: true).breite, 0.7)  // Rahmen ISO 5457
        XCTAssertEqual(LinienStil.sehrBreit / LinienStil.breit, 2)
        XCTAssertEqual(LinienStil.breit / LinienStil.schmal, 2)
        XCTAssertEqual(Double(LinienStil.breit * BlattZeichner.punkteJeMM), 1.41732, accuracy: 1e-4)
        XCTAssertEqual(Double(LinienStil.rahmen * BlattZeichner.punkteJeMM), 1.984252, accuracy: 1e-5)
        // Strichlinie 02.1: Strich 12d, Lücke 3d; mit runden Enden ausgegeben als 11d und 4d
        XCTAssertEqual(LinienStil.fuer("verdeckt").ausgabeMuster, [2.75, 1.0])
        let mitte = try? XCTUnwrap(LinienStil.fuer("mitte").ausgabeMuster)
        XCTAssertEqual(mitte?[0], 5.75)
        XCTAssertEqual(mitte?[1], 1.0)
        XCTAssertEqual(mitte?[2], LinienStil.punktLaenge)
        XCTAssertEqual(LinienStil.fuer("nachbar").muster?.count, 6)
    }

    /// Strichstücke als Abschnitte entlang einer waagrechten Linie (aus dem Pfad).
    private func stuecke(_ p: CGPath) -> [(CGFloat, CGFloat)] {
        var out: [(CGFloat, CGFloat)] = []
        var start: CGFloat = 0
        var letzter: CGFloat = 0
        p.applyWithBlock { el in
            let pt = el.pointee.points[0]
            switch el.pointee.type {
            case .moveToPoint:
                if letzter > start { out.append((start, letzter)) }
                start = pt.x
                letzter = pt.x
            case .addLineToPoint:
                letzter = pt.x
            default: break
            }
        }
        if letzter > start { out.append((start, letzter)) }
        return out
    }

    func testStrichlinienBeginnenUndEndenMitStrich() throws {
        for (art, laenge) in [("verdeckt", 47.3), ("mitte", 61.0), ("mitte", 26.0), ("nachbar", 80.0)] {
            let pfad = CGMutablePath()
            let muster = try XCTUnwrap(LinienStil.fuer(art).ausgabeMuster)
            Strichmuster.zerlege([CGPoint(x: 0, y: 0), CGPoint(x: laenge, y: 0)], muster: muster, in: pfad)
            let s = stuecke(pfad)
            XCTAssertGreaterThan(s.count, 2, art)
            XCTAssertEqual(Double(s.first?.0 ?? -1), 0, accuracy: 1e-9, "\(art) beginnt mit Strich")
            XCTAssertEqual(Double(s.last?.1 ?? -1), laenge, accuracy: 1e-6, "\(art) endet mit Strich")
            XCTAssertGreaterThan(Double(s.last!.1 - s.last!.0), 1.0, "\(art) endet mit langem Strich, nicht mit Punkt")
            if art == "mitte" {
                // Mittellinien kreuzen sich im Strich: die Mitte liegt in einem langen Strich
                let mitteX = CGFloat(laenge / 2)
                XCTAssertTrue(s.contains { $0.0 < mitteX - 0.5 && $0.1 > mitteX + 0.5 }, "\(art) \(laenge): Mitte im Strich")
            }
        }
        // kurze Mittellinie (kleine Bohrung): durchgezogen
        let kurz = CGMutablePath()
        Strichmuster.zerlege([CGPoint(x: 0, y: 0), CGPoint(x: 9, y: 0)], muster: LinienStil.fuer("mitte").ausgabeMuster!,
                             in: kurz)
        XCTAssertEqual(stuecke(kurz).count, 1)
    }

    func testSchriftgroesseInPunkt() {
        XCTAssertTrue(BlattSchrift.istOsifont, "osifont nicht gefunden (app/Resources/Fonts)")
        XCTAssertTrue(BlattSchrift.postscriptName.lowercased().contains("osifont"))
        XCTAssertEqual(BlattSchrift.punktgroesse(versalhoehe: 3.5), 13.46, accuracy: 0.01)
        XCTAssertEqual(BlattSchrift.punktgroesse(versalhoehe: 2.5), 9.61, accuracy: 0.01)
        XCTAssertEqual(BlattSchrift.punktgroesse(versalhoehe: 5), 19.23, accuracy: 0.01)
        // Versalhöhe des gesetzten „H“ = verlangte Höhe
        let f = BlattSchrift.font(versalhoehe: 3.5)
        var c: [UniChar] = Array("H".utf16)
        var g: [CGGlyph] = [0]
        XCTAssertTrue(CTFontGetGlyphsForCharacters(f, &c, &g, 1))
        let r = CTFontGetBoundingRectsForGlyphs(f, .horizontal, g, nil, 1)
        XCTAssertEqual(Double(r.maxY), 3.5, accuracy: 0.01)
        // Zeichen, die osifont fehlen, werden ersetzt (keine Ersatzschrift im PDF)
        XCTAssertEqual(TextGrafik.fuerSchrift("Kanten \u{2212}0,3 …"), "Kanten \u{2013}0,3 ...")
    }

    func testSeitengroessen() throws {
        let z = Self.testblatt(groesse: CGSize(width: 297, height: 210))  // A4 quer
        XCTAssertEqual(Double(z.seitengroessePunkte.width), 841.89, accuracy: 0.01)
        XCTAssertEqual(Double(z.seitengroessePunkte.height), 595.28, accuracy: 0.01)
        let (f, _) = try zeichnung("drawing.frame")
        XCTAssertEqual(Double(f.seitengroessePunkte.width), Double(f.groesse.width) * 72 / 25.4, accuracy: 1e-6)
        let a3 = Self.testblatt(groesse: CGSize(width: 420, height: 297))
        XCTAssertEqual(Double(a3.seitengroessePunkte.width), 1190.55, accuracy: 0.01)
        XCTAssertEqual(Double(a3.seitengroessePunkte.height), 841.89, accuracy: 0.01)
        XCTAssertEqual(BlattDruck.auftraege([z, a3, z]).map(\.zeichnungen.count), [2, 1])
    }

    /// Kleines Blatt mit einer geschnittenen Fläche: Ring 10…20 mm und Schraffurlinien, die darüber hinausragen.
    static func testblatt(groesse: CGSize = CGSize(width: 40, height: 30)) -> Zeichnung {
        let ring = [CGPoint(x: 10, y: 10), CGPoint(x: 20, y: 10), CGPoint(x: 20, y: 20), CGPoint(x: 10, y: 20),
                    CGPoint(x: 10, y: 10)]
        let schraffur: [[CGPoint]] = [ring] + stride(from: 0.0, through: 30.0, by: 2.0).map {
            [CGPoint(x: 0, y: $0), CGPoint(x: 30, y: $0)]  // waagrecht, weit über den Ring hinaus
        }
        let gruppe = ZeichnungsGruppe(id: "v1", art: "schnitt", rahmen: CGRect(x: 5, y: 5, width: 20, height: 20),
                                      linien: ["schraffur": schraffur])
        let blatt = DokumenteMessage.blattInfo(["id": "test", "titel": "Test", "format": "A3", "ausrichtung": "quer"])
        return Zeichnung(blatt: blatt, groesse: groesse, gruppen: [gruppe], masse: [], texte: [])
    }

    func testSchraffurNurInnerhalbDesClips() throws {
        let z = Self.testblatt()
        let s: CGFloat = 20  // Pixel je mm
        let w = Int(z.groesse.width * s)
        let h = Int(z.groesse.height * s)
        let ctx = try XCTUnwrap(CGContext(
            data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
            space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        ctx.scaleBy(x: s, y: s)
        BlattZeichner.zeichne(z, in: ctx, optionen: .druck)
        let daten = try XCTUnwrap(ctx.data).assumingMemoryBound(to: UInt8.self)
        func dunkel(_ x: CGFloat, _ y: CGFloat) -> Bool {
            let px = Int(x * s)
            let py = h - 1 - Int(y * s)  // Bitmap-Zeilen von oben
            return daten[(py * w + px) * 4] < 128
        }
        XCTAssertTrue(dunkel(15, 14), "Schraffurlinie innerhalb der Schnittfläche")
        XCTAssertFalse(dunkel(25, 14), "Schraffurlinie außerhalb ist abgeschnitten")
        XCTAssertFalse(dunkel(5, 14), "Schraffurlinie außerhalb ist abgeschnitten")
        XCTAssertFalse(dunkel(15, 15), "zwischen zwei Schraffurlinien weiß")
    }

    /// Verwaiste Maße erscheinen rot (Bildschirm, PDF, Druck), alle anderen schwarz.
    func testVerwaistesMassRot() throws {
        let basis = Self.testblatt()
        let rot = MassDarstellung(id: "m9", linien: [[CGPoint(x: 5, y: 5), CGPoint(x: 35, y: 5)]], verwaist: true)
        let schwarz = MassDarstellung(id: "m8", linien: [[CGPoint(x: 5, y: 25), CGPoint(x: 35, y: 25)]])
        let z = Zeichnung(blatt: basis.blatt, groesse: basis.groesse, gruppen: [], masse: [rot, schwarz], texte: [])
        let s: CGFloat = 20
        let w = Int(z.groesse.width * s)
        let h = Int(z.groesse.height * s)
        let ctx = try XCTUnwrap(CGContext(
            data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
            space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        ctx.scaleBy(x: s, y: s)
        BlattZeichner.zeichne(z, in: ctx, optionen: .druck)
        let d = try XCTUnwrap(ctx.data).assumingMemoryBound(to: UInt8.self)
        func farbe(_ x: CGFloat, _ y: CGFloat) -> (UInt8, UInt8, UInt8) {
            let i = ((h - 1 - Int(y * s)) * w + Int(x * s)) * 4
            return (d[i], d[i + 1], d[i + 2])
        }
        let r = farbe(20, 5)
        XCTAssertGreaterThan(r.0, 150, "verwaistes Maß rot")
        XCTAssertLessThan(r.1, 90)
        let k = farbe(20, 25)
        XCTAssertLessThan(k.0, 80, "normales Maß schwarz")
    }

    /// Hinweise werden am Knick verschoben (so legt der Kernel `text_lage` ab), lineare Maße an der Zahl.
    func testTextAnker() {
        let tip = CGPoint(x: 10, y: 10)
        let knick = CGPoint(x: 15, y: 18)
        let h = MassDarstellung(id: "m1", linien: [[tip, knick, CGPoint(x: 35, y: 18)]],
                                pfeile: [MassPfeil(spitze: tip, richtung: CGVector(dx: -1, dy: -1))], text: "Ø8",
                                textLage: CGPoint(x: 25, y: 18.9), art: "bohrung")
        XCTAssertTrue(h.istHinweis)
        XCTAssertEqual(h.textAnker, knick)
        let l = MassDarstellung(id: "m2", linien: [[CGPoint(x: 0, y: 0), CGPoint(x: 40, y: 0)]],
                                pfeile: [MassPfeil(spitze: .zero, richtung: CGVector(dx: -1, dy: 0)),
                                         MassPfeil(spitze: CGPoint(x: 40, y: 0), richtung: CGVector(dx: 1, dy: 0))],
                                text: "40", textLage: CGPoint(x: 20, y: 0.9), art: "linear")
        XCTAssertFalse(l.istHinweis)
        XCTAssertEqual(l.textAnker, l.textLage)
    }

    func testPDFMitGemischtenFormatenUndEingebetteterSchrift() throws {
        let (z, _) = try zeichnung("drawing.frame")
        let a3 = Self.testblatt(groesse: CGSize(width: 420, height: 297))
        let daten = BlattPDF.daten([z, a3], metadaten: .init(titel: "Test"))
        let doc = try XCTUnwrap(PDFDocument(data: daten))
        XCTAssertEqual(doc.pageCount, 2)
        XCTAssertEqual(Double(doc.page(at: 0)!.bounds(for: .mediaBox).width), Double(z.seitengroessePunkte.width),
                       accuracy: 0.01)
        XCTAssertEqual(Double(doc.page(at: 1)!.bounds(for: .mediaBox).width), 1190.55, accuracy: 0.01)
        XCTAssertEqual(doc.outlineRoot?.numberOfChildren, 2)
        XCTAssertEqual(doc.documentAttributes?[PDFDocumentAttribute.titleAttribute] as? String, "Test")
        // echter Text (durchsuchbar) in osifont, keine Ersatzschrift
        let text = doc.page(at: 0)?.string ?? ""
        for m in z.masse where m.text.contains("Ø") { XCTAssertTrue(text.contains(m.text), "\(m.text) in \(text)") }
        XCTAssertTrue(text.contains("ISO 2768-m"))
        let roh = String(decoding: daten, as: UTF8.self)
        XCTAssertTrue(roh.contains("osifont"))
        XCTAssertFalse(roh.contains("Helvetica"))
    }

    func testDruckAuftragNichtSkaliert() async throws {
        let z = Self.testblatt(groesse: CGSize(width: 297, height: 210))  // A4 quer
        await MainActor.run {
            let a = BlattDruck.auftraege([z])[0]
            let info = BlattDruck.druckInfo(a)
            XCTAssertEqual(max(info.paperSize.width, info.paperSize.height), a.papier.width, accuracy: 0.01)
            XCTAssertEqual(min(info.paperSize.width, info.paperSize.height), a.papier.height, accuracy: 0.01)
            XCTAssertEqual(info.orientation, .landscape)
            XCTAssertEqual(info.leftMargin, 0)
            XCTAssertEqual(info.scalingFactor, 1)
        }
    }

    /// Zweizeiliger Bohrungshinweis mit Knick („4× Ø8,2 × 13,8 tief“ / „Einsatz M6 × 12,7“, Kameraträger): greifbar auf
    /// beiden Zeilen und auf der Bezugslinie; der Anker zum Verschieben ist der Knick.
    func testZweizeiligerHinweisIstGreifbar() {
        let spitze = CGPoint(x: 233.275, y: 95.725)
        let knick = CGPoint(x: 245.775, y: 74.074)
        let h = MassDarstellung(
            id: "m4", linien: [[spitze, knick, CGPoint(x: 290.745, y: 74.074)]],
            pfeile: [MassPfeil(spitze: spitze, richtung: CGVector(dx: -0.5, dy: 0.87))], text: "4× Ø8,2 × 13,8 tief",
            textLage: CGPoint(x: 268.26, y: 74.974), art: "bohrung")
        var mit = h
        mit.texte = [BlattText(text: "Einsatz M6 × 12,7", lage: CGPoint(x: 268.26, y: 67.574), hoehe: 3.5, anker: .mitte)]
        XCTAssertTrue(mit.istHinweis)
        XCTAssertEqual(mit.textAnker, knick)
        let g = MassGrafik(mit)
        XCTAssertTrue(g.trifftText(CGPoint(x: 268.26, y: 76.2), toleranz: 0.3))  // erste Zeile
        XCTAssertTrue(g.trifftText(CGPoint(x: 262, y: 68.8), toleranz: 0.3))  // zweite Zeile
        XCTAssertLessThan(g.abstand(zu: CGPoint(x: 239.5, y: 84.9)), 0.3)  // schräge Bezugslinie
        XCTAssertTrue(g.huelle.contains(CGPoint(x: 262, y: 68.8)))
    }

    func testTrefferAufMassUndText() throws {
        let (z, _) = try zeichnung("drawing.frame")
        let m1 = try XCTUnwrap(z.grafik.mass("m1"))
        // auf der Maßlinie (längste Linie), auf der Zahl, daneben
        let linie = try XCTUnwrap(m1.mass.linien.max { MassVorschau_laenge($0) < MassVorschau_laenge($1) })
        let mitteLinie = CGPoint(x: (linie[0].x + linie[1].x) / 2, y: (linie[0].y + linie[1].y) / 2)
        XCTAssertLessThan(m1.abstand(zu: mitteLinie), 0.2)
        let t = m1.mass.textLage
        XCTAssertTrue(m1.trifftText(CGPoint(x: t.x, y: t.y + 1.5)))
        XCTAssertFalse(m1.trifftText(CGPoint(x: t.x + 40, y: t.y + 1.5)))
    }
}
