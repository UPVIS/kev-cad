import CoreGraphics
import Foundation
import PDFKit
import XCTest

@testable import KevCADCore

/// Phase 6, Bauplan und Export (P6-A2): Decoder BAUPLAN gegen die Testdateien des Kernels, Encoder BAUPLAN_REQ/EDIT/
/// PRUEFEN, DOC_EXPORT_REQ/RES, Durchspielen, Seitenumbruch der Tabellen, Seitenfluss, Export-Vorlagen und das PDF.
final class BauplanExportTests: XCTestCase {
    private func erwartet(_ k: String) throws -> JSONValue { try XCTUnwrap(Fixtures.expected()[k]) }

    private func bauplan() throws -> BauplanNachricht {
        guard case .bauplan(let b) = try Fixtures.message("bauplan.frame") else {
            throw XCTSkip("bauplan.frame ist kein BAUPLAN")
        }
        return b
    }

    private func kopf(_ m: some OutgoingMessage) throws -> JSONValue {
        var j = try JSONDecoder().decode(JSONValue.self, from: m.encodedHeader())
        if case .object(var o) = j {
            o["seq"] = nil
            j = .object(o)
        }
        return j
    }

    private func fixtureKopf(_ datei: String) throws -> JSONValue {
        var j = try JSONDecoder().decode(JSONValue.self, from: Fixtures.frame(datei).header)
        if case .object(var o) = j {
            o["seq"] = nil
            j = .object(o)
        }
        return j
    }

    // MARK: Decoder

    func testBauplanFixture() throws {
        let e = try erwartet("bauplan")
        let b = try bauplan()
        XCTAssertEqual(b.replyTo, e["reply_to"]?.stringValue)
        XCTAssertEqual(b.run, e["run"]?.intValue)
        XCTAssertEqual(b.linienReihenfolge, e["linien_reihenfolge"]?.stringList)
        XCTAssertEqual(Double(b.feld.width), e["feld"]?.doubles?[0])
        XCTAssertEqual(b.plan.abschnitte.map(\.art.raw), e["abschnitte"]?.stringList)
        XCTAssertEqual(b.plan.abschnitte.map { Double($0.schritte.count) }, e["schritte_je_abschnitt"]?.doubles)
        XCTAssertEqual(b.plan.montage?.schritte.map(\.id), e["montage_ids"]?.stringList)
        XCTAssertEqual(b.plan.vorher.count, e["vorher"]?.intValue)
        let bef = try XCTUnwrap(b.plan.montage?.schritte[1].pruefung.first)
        XCTAssertEqual(bef.id, e["befund"]?["id"]?.stringValue)
        XCTAssertEqual(bef.art, e["befund"]?["art"]?.stringValue)
        XCTAssertEqual(bef.schwere.rawValue, e["befund"]?["schwere"]?.stringValue)
        XCTAssertEqual(bef.schritt, e["befund"]?["schritt"]?.stringValue)
        XCTAssertEqual(bef.artTitel, "Werkzeugzugang")
        XCTAssertNotNil(bef.loesung)
        // Strichbilder: Anzahl je Linienart und erster Pfeil
        let eb = try XCTUnwrap(e["bilder"]?.arrayValue)
        XCTAssertEqual(b.bilder.map(\.schritt), eb.compactMap { $0["schritt"]?.stringValue })
        for (bild, x) in zip(b.bilder, eb) {
            for (art, n) in x["linien"]?.objectValue ?? [:] {
                XCTAssertEqual(bild.linien[art]?.count ?? 0, n.intValue, "\(bild.schritt).\(art)")
            }
        }
        let pfeil = try XCTUnwrap(b.bilder[1].linien["pfeil"]?.first)
        let ep = try XCTUnwrap(e["erster_pfeil"]?.arrayValue)
        XCTAssertEqual(Double(pfeil[0].x), ep[0].doubles?[0] ?? -1, accuracy: 1e-3)
        XCTAssertEqual(Double(pfeil[1].y), ep[1].doubles?[1] ?? -1, accuracy: 1e-3)
        XCTAssertEqual(b.bilder[0].rahmen, CGRect(x: 0, y: 0, width: 180, height: 120))
        // Felder eines Montageschritts
        let m2 = try XCTUnwrap(b.plan.schritt("m-2"))
        XCTAssertTrue(m2.fest)
        XCTAssertEqual(m2.quelle, "agent")
        XCTAssertEqual(m2.werkzeug, ["Innensechskant 5 mm"])
        XCTAssertEqual(m2.verbindungsmittel.first?.benennung, "Zylinderschraube ISO 4762 M6 × 20")
        XCTAssertEqual(m2.einbau.first?.richtung, SIMD3<Float>(0, 0, -1))
        XCTAssertEqual(m2.bild?.explosion["Halter/Deckel"], SIMD3<Float>(0, 0, 25))
        XCTAssertEqual(m2.bild?.pfeile.count, 1)
        XCTAssertNotNil(m2.bild?.rotation)
        XCTAssertEqual(m2.schwersterBefund, .fehler)
        XCTAssertEqual(b.plan.nummer("m-2"), 5)
        let bohr = try XCTUnwrap(b.plan.schritt("b-1")?.bohrbild.first)
        XCTAssertEqual(bohr.bohrerText, "Ø 6,6")
        XCTAssertEqual(bohr.lageText, "25 mm")
        XCTAssertEqual(b.plan.schritt("b-1")?.anzahl, 2)
        XCTAssertEqual(b.plan.schritt("m-1")?.material.first?.menge, 2)
        XCTAssertEqual(b.plan.fehlerAnzahl, 1)
    }

    func testDocsMitBauplanKommtUeberDokumente() throws {
        // die Zusammenfassung in DOCS dekodiert P6-A1 (DocsUebersicht.bauplan); hier nur, dass sie ankommt
        guard case .dokumente(.docs(let d, _)) = try Fixtures.message("docs_bauplan.frame") else {
            return XCTFail("docs_bauplan.frame ist kein DOCS")
        }
        XCTAssertEqual(d.bauplan?.schritte, try erwartet("bauplan")["docs"]?["schritte"]?.intValue)
    }

    // MARK: Encoder

    func testAnfragenWieDieTestdateien() throws {
        XCTAssertEqual(try kopf(BauplanAnfrageMessage(id: "a-7")), try fixtureKopf("bauplan_req.frame"))
        XCTAssertEqual(try kopf(BauplanPruefenMessage(id: "a-9", schritt: nil)), try fixtureKopf("bauplan_pruefen.frame"))
        let ops: [JSONValue] = [
            BauplanOp.text(schritt: "m-2", titel: "Deckel aufsetzen", text: "Deckel auflegen, Schraube von oben eindrehen."),
            BauplanOp.fest(schritt: "m-2", true), BauplanOp.verschieben(schritt: "m-2", nach: "m-1g"),
            ["op": "bild", "schritt": "m-2", "explosion": ["Halter/Deckel": [0.0, 0.0, 40.0]]],
        ]
        XCTAssertEqual(try kopf(BauplanBearbeitenMessage(id: "a-8", ops: ops, von: "kevin")),
                       try fixtureKopf("bauplan_edit.frame"))
        let v = try kopf(BauplanBearbeitenMessage(id: "a-1", ops: [BauplanOp.vorher(a: "m-1g", b: "m-2", grund: "x")]))
        XCTAssertEqual(v["ops"]?.arrayValue?.first?["op"]?.stringValue, "vorher")
        XCTAssertEqual(v["von"]?.stringValue, "kevin")
        XCTAssertEqual(try kopf(BauplanPruefenMessage(id: "a-2", schritt: "m-2"))["schritt"]?.stringValue, "m-2")
    }

    func testDokumentExportAnfrageUndAntwort() throws {
        let e = try erwartet("export")
        guard case .dokumentExport(let a) = try Fixtures.message("doc_export_req.frame") else {
            return XCTFail("doc_export_req.frame ist kein DOC_EXPORT_REQ")
        }
        XCTAssertEqual(a.id, "k-12")
        XCTAssertEqual(a.bausteine.map(\.art.rawValue), ["deckblatt", "stueckliste", "zeichnungen", "bauplan"])
        XCTAssertEqual(a.bausteine[1].spalten, ["pos", "bild", "benennung", "anzahl", "masse"])
        XCTAssertEqual(a.bausteine[2].auswahl, ["seitenstange-links", "zusammenbau"])
        XCTAssertEqual(a.ziel?.path, "/tmp/Halter/output/Halter-dokumente.pdf")
        XCTAssertFalse(a.drucken)
        XCTAssertEqual(a.format, .a4)
        XCTAssertEqual(a.ausrichtung, .hoch)
        XCTAssertEqual(e["bausteine"]?.stringList, ExportBausteinArt.allCases.map(\.rawValue))
        // Antwort wie die Testdatei (ohne seq)
        let r = try XCTUnwrap(e["res"])
        let ergebnis = ExportErgebnis(
            pfad: URL(fileURLWithPath: "/tmp/Halter/output/Halter-dokumente.pdf"), seiten: 14,
            bausteine: [(.deckblatt, 1), (.stueckliste, 2), (.zeichnungen, 2), (.bauplan, 9)],
            formate: ["A4 hoch": 13, "A3 quer": 1], hinweise: [], ms: 1830,
            phasen: ["bauplan_ms": 0, "blaetter_ms": 410, "bilder_ms": 760, "seiten_ms": 95, "pdf_ms": 520])
        var ich = try kopf(DokumentExportAntwortMessage(replyTo: "k-12", ergebnis: ergebnis))
        var soll = r
        if case .object(var o) = soll { o["seq"] = nil; soll = .object(o) }
        if case .object(var o) = ich { o["seq"] = nil; ich = .object(o) }
        XCTAssertEqual(ich, soll)
        let f = try kopf(DokumentExportAntwortMessage(replyTo: "k-1", fehler: "kaputt"))
        XCTAssertEqual(f["ok"]?.boolValue, false)
        XCTAssertEqual(f["fehler"]?.stringValue, "kaputt")
        XCTAssertEqual(f["pfad"], .null)
        // Anfrage mit Vorlage: Bausteine der Vorlage, Spalten übernommen
        var datei = ExportVorlagenDatei()
        datei.setze(ExportVorlage(name: "Werkstatt", format: .a3, ausrichtung: .quer, bausteine: [
            ExportBausteinWahl(art: .stueckliste, spalten: ["pos", "benennung"]), ExportBausteinWahl(art: .bauplan),
        ]))
        var nurVorlage = a
        nurVorlage.bausteine = []
        nurVorlage.vorlage = "werkstatt"
        nurVorlage.format = nil
        nurVorlage.ausrichtung = nil
        let (v1, h1) = nurVorlage.vorlage(aus: datei)
        XCTAssertEqual(v1.aktive.map(\.art), [.stueckliste, .bauplan])
        XCTAssertEqual(v1.seitenformat, ExportSeitenformat(.a3, .quer))
        XCTAssertTrue(h1.isEmpty)
        var mitBausteinen = a
        mitBausteinen.vorlage = "Werkstatt"
        mitBausteinen.bausteine = [ExportBausteinWahl(art: .stueckliste)]
        let (v2, _) = mitBausteinen.vorlage(aus: datei)
        XCTAssertEqual(v2.aktive.first?.spalten, ["pos", "benennung"])
        XCTAssertEqual(v2.seitenformat, ExportSeitenformat(.a4, .hoch))  // Format der Anfrage gewinnt
        nurVorlage.vorlage = "gibtsnicht"
        XCTAssertEqual(nurVorlage.vorlage(aus: datei).1.count, 1)
    }

    // MARK: Durchspielen

    func testDurchspielenPose() throws {
        let plan = try bauplan().plan
        XCTAssertEqual(BauplanAblauf.schritte(plan), ["m-1g", "m-2"])
        let p1 = try XCTUnwrap(BauplanAblauf.pose(plan, schritt: "m-1g", fortschritt: 1))
        XCTAssertEqual(p1.sichtbar, ["Halter/Bein 1"])
        XCTAssertTrue(p1.versatz.isEmpty)
        let p2 = try XCTUnwrap(BauplanAblauf.pose(plan, schritt: "m-2", fortschritt: 0))
        XCTAssertEqual(p2.sichtbar, ["Halter/Bein 1", "Halter/Deckel", "Halter/Schraube 1"])
        XCTAssertEqual(p2.neu, ["Halter/Deckel", "Halter/Schraube 1"])
        XCTAssertEqual(p2.versatz["Halter/Deckel"], SIMD3<Float>(0, 0, 25))  // aus der Explosion des Bilds
        XCTAssertEqual(p2.versatz["Halter/Schraube 1"], SIMD3<Float>(0, 0, 47.5))
        let halb = try XCTUnwrap(BauplanAblauf.pose(plan, schritt: "m-2", fortschritt: 0.5))
        let z = try XCTUnwrap(halb.versatz["Halter/Deckel"]?.z)
        XCTAssertTrue(z > 0 && z < 25)
        XCTAssertTrue(try XCTUnwrap(BauplanAblauf.pose(plan, schritt: "m-2", fortschritt: 1)).versatz.isEmpty)
        // ohne Explosion: gegen die Fügerichtung um den Weg
        var s = try XCTUnwrap(plan.schritt("m-2"))
        s.bild?.explosion = [:]
        XCTAssertEqual(BauplanAblauf.startVersatz(s, teil: "Halter/Deckel"), SIMD3<Float>(0, 0, 25))
        XCTAssertEqual(BauplanAblauf.weich(0), 0)
        XCTAssertEqual(BauplanAblauf.weich(1), 1)
        XCTAssertEqual(BauplanAblauf.weich(0.5), 0.5, accuracy: 1e-9)
    }

    func testVormontageZeigtNurIhreBaugruppe() throws {
        var plan = try bauplan().plan
        var m = try XCTUnwrap(plan.montage)
        let vor = BauplanSchritt(
            id: "v-1", titel: "Rad montieren", text: "", quelle: "auto", fest: false, verwaist: false,
            teile: ["Wagen/Rad"], neu: ["Wagen/Rad"], baugruppe: "Wagen", anzahl: 1, verbindungsmittel: [],
            werkzeug: [], bohrbild: [], zuschnitt: [], druck: nil, material: [], bild: nil, pruefung: [], hinweise: [],
            einbau: [])
        m.schritte.insert(vor, at: 1)
        plan.abschnitte[plan.abschnitte.firstIndex { $0.art == .montage }!] = m
        XCTAssertEqual(BauplanAblauf.montiert(plan, bis: "v-1"), ["Wagen/Rad"])
        XCTAssertEqual(BauplanAblauf.montiert(plan, bis: "m-2"), ["Halter/Bein 1", "Halter/Deckel", "Halter/Schraube 1"])
    }

    func testTexteUndWerkzeug() throws {
        XCTAssertTrue(BauplanText.istSicherheit("Schutzbrille tragen, Werkstück fest spannen"))
        XCTAssertTrue(BauplanText.istSicherheit("Lötspitze und Einsatz sind heiß: Ablage nutzen"))
        XCTAssertFalse(BauplanText.istSicherheit("Längstes Stück zuerst schneiden"))
        XCTAssertEqual(BauplanText.ohneNummer("Lenkrolle 3"), "Lenkrolle")
        XCTAssertEqual(BauplanText.ohneNummer("Schraube M6x16 1 vorn links"), "Schraube M6x16 1 vorn links")
        XCTAssertEqual(BauplanWerkzeug.art("Kappsäge mit Alu-Sägeblatt"), .saege)
        XCTAssertEqual(BauplanWerkzeug.art("Bohrer Ø 6,6"), .bohrer)
        XCTAssertEqual(BauplanWerkzeug.art("Innensechskant 5 mm"), .innensechskant)
        XCTAssertEqual(BauplanWerkzeug.art("Lötkolben mit Einsatzspitze"), .loetkolben)
        XCTAssertEqual(BauplanWerkzeug.art("Bambu Lab P1P"), .drucker)
        let plan = try bauplan().plan
        let m2 = try XCTUnwrap(plan.schritt("m-2"))
        // Verbindungsmittel zählen nicht als „neue Teile“, gleiche Kurznamen werden gezählt
        XCTAssertEqual(m2.neueTeileGruppiert.map(\.name), ["Deckel", "Schraube 1"].map { BauplanText.ohneNummer($0) })
    }

    // MARK: Seitenumbruch und Fluss

    func testUmbruchTeiltNieEineZeileUndWiederholtDenKopf() {
        let hoehen: [CGFloat] = Array(repeating: 10, count: 25)
        let r = ExportTabelle.umbruch(hoehen: hoehen, kopf: 8, erste: 100, folgende: 208)
        // erste Seite: (100 - 8) / 10 = 9 Zeilen, dann je (208 - 8) / 10 = 20
        XCTAssertEqual(r, [0..<9, 9..<25])
        XCTAssertEqual(r.flatMap { Array($0) }, Array(0..<25))
        // jede Seite passt mit Kopf in ihren Platz
        for (i, b) in r.enumerated() {
            let h = 8 + b.reduce(CGFloat(0)) { $0 + hoehen[$1] }
            XCTAssertLessThanOrEqual(h, i == 0 ? 100 : 208)
        }
    }

    func testUmbruchHaeltGruppeUndSumme() {
        // Zeile 8 ist eine Gruppenüberschrift und wäre die letzte der ersten Seite
        var h: [CGFloat] = Array(repeating: 10, count: 12)
        let r = ExportTabelle.umbruch(hoehen: h, gruppen: [8], kopf: 8, erste: 100, folgende: 100)
        XCTAssertEqual(r.first, 0..<8)
        XCTAssertEqual(r[1].first, 8)
        // Summe (letzte Zeile) nie allein auf einer neuen Seite
        h = Array(repeating: 10, count: 10)
        let s = ExportTabelle.umbruch(hoehen: h, summen: [9], kopf: 8, erste: 100, folgende: 100)
        XCTAssertEqual(s, [0..<8, 8..<10])
        // erste Seite fast voll: Tabelle beginnt auf der nächsten
        let v = ExportTabelle.umbruch(hoehen: [10, 10], kopf: 8, erste: 12, folgende: 100)
        XCTAssertEqual(v, [0..<0, 0..<2])
        // Zeile höher als die Seite: allein, kein Endlosumbruch
        XCTAssertEqual(ExportTabelle.umbruch(hoehen: [300, 10], kopf: 8, erste: 100, folgende: 100), [0..<1, 1..<2])
    }

    func testFlussHaeltUeberschriftBeiDerTabelle() {
        let inhalt = CGRect(x: 0, y: 0, width: 170, height: 100)
        let zeilen = (0..<30).map { ExportZeile(["a": ExportZelle("Zeile \($0)")]) }
        var t = ExportTabelle(spalten: [ExportSpalte("a", "A", mindest: 50, gewicht: 1)], zeilen: zeilen)
        t.bildHoehe = 0
        let titel = ExportBlock.fest(hoehe: 10, mitNaechstem: true) { _, _ in }
        let platz = ExportBlock.fest(hoehe: 85, mitNaechstem: false) { _, _ in }
        let seiten = ExportFluss.verteile([platz, .marke("Teil"), titel, .tabelle(t)], inhalt: inhalt)
        // Überschrift und Tabellenkopf passen nicht mehr mit einer Zeile auf Seite 1: beide auf Seite 2
        XCTAssertEqual(seiten[0].auftraege.count, 1)
        XCTAssertEqual(seiten[1].auftraege.first?.rect.minY, 0)
        XCTAssertEqual(seiten[1].marken, ["Teil"])
        XCTAssertGreaterThan(seiten.count, 2)
        for s in seiten {
            for a in s.auftraege { XCTAssertLessThanOrEqual(a.rect.maxY, inhalt.maxY + 0.01) }
        }
        // neue Seite ohne leere Seiten
        let n = ExportFluss.verteile([.neueSeite, platz, .neueSeite, .neueSeite, platz], inhalt: inhalt)
        XCTAssertEqual(n.count, 2)
    }

    // MARK: Vorlagen

    func testVorlagenSpeichernUndLaden() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("kc-vorlagen-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }
        XCTAssertEqual(ExportVorlagenDatei.laden(projekt: dir).0.vorlagen.count, 0)
        var d = ExportVorlagenDatei()
        d.setze(ExportVorlage(name: "Werkstatt", bausteine: [
            ExportBausteinWahl(art: .bauplan), ExportBausteinWahl(art: .stueckliste, spalten: ["pos", "bild"]),
        ]).vollstaendig)
        d.setze(ExportVorlage(name: "werkstatt", format: .a3, bausteine: [ExportBausteinWahl(art: .zuschnitt)]))
        XCTAssertEqual(d.vorlagen.count, 1)  // gleichnamig (ohne Groß/klein) ersetzt
        d.setze(ExportVorlage.standard)
        try d.speichern(projekt: dir)
        let (l, f) = ExportVorlagenDatei.laden(projekt: dir)
        XCTAssertNil(f)
        XCTAssertEqual(l.zuletzt, "Alles")
        XCTAssertEqual(l.vorlage("WERKSTATT")?.format, .a3)
        XCTAssertEqual(l.vorlage("werkstatt")?.bausteine.count, ExportBausteinArt.allCases.count)  // vollständig
        XCTAssertEqual(l.vorlage("Alles")?.aktive.count, ExportBausteinArt.allCases.count)
        // Datei wie im Vertrag; unbekannte Bausteine einer neueren App werden übersprungen
        let json = """
            {"version": 1, "zuletzt": "X", "vorlagen": [{"name": "X", "format": "A4", "ausrichtung": "quer",
             "bausteine": [{"art": "deckblatt", "an": true}, {"art": "gewicht_und_kosten", "an": true},
                           {"art": "stueckliste", "an": false, "spalten": ["pos", "gibtsnicht", "preis"]}]}]}
            """
        try json.write(to: ExportVorlagenDatei.url(projekt: dir), atomically: true, encoding: .utf8)
        let x = try XCTUnwrap(ExportVorlagenDatei.laden(projekt: dir).0.vorlage("X"))
        XCTAssertEqual(x.ausrichtung, .quer)
        XCTAssertEqual(x.aktive.map(\.art), [.deckblatt])
        let st = try XCTUnwrap(x.bausteine.first { $0.art == .stueckliste })
        XCTAssertEqual(st.wirksameSpalten.map(\.id), ["pos", "preis"])
        XCTAssertEqual(ExportBausteinWahl(art: .stueckliste).wirksameSpalten.map(\.id), ExportBausteinArt.stueckliste.standardSpalten)
        // kaputte Datei: Fehlertext, leere Liste
        try "{kaputt".write(to: ExportVorlagenDatei.url(projekt: dir), atomically: true, encoding: .utf8)
        XCTAssertNotNil(ExportVorlagenDatei.laden(projekt: dir).1)
        d.entferne("Alles")
        XCTAssertNil(d.zuletzt)
    }

    func testFormate() {
        XCTAssertEqual(ExportSeitenformat(.a4, .hoch).mm, CGSize(width: 210, height: 297))
        XCTAssertEqual(ExportSeitenformat(.a3, .quer).mm, CGSize(width: 420, height: 297))
        XCTAssertEqual(ExportSeitenformat.passend(mm: CGSize(width: 297, height: 210))?.name, "A4 quer")
        XCTAssertEqual(ExportSeitenformat(.a4, .hoch).punkte.width, 595.28, accuracy: 0.01)
    }

    // MARK: PDF

    @MainActor
    func testPDFAusDemBauplan() throws {
        let b = try bauplan()
        var bilder: [String: BauplanStrichbild] = [:]
        for x in b.bilder { bilder[x.schritt] = x }
        let bom = BillOfMaterials(
            run: 3,
            lines: (1...40).map { i in
                BOMLine(pos: i, art: i % 3 == 0 ? "schraube" : "rohr", stockID: "rohr-\(i)", benennung: "Rohr \(i)",
                        material: "Alu", laenge: Double(100 + i), masseText: "12 × 1", anzahl: i % 4 + 1, kg: 0.1,
                        preis: 1.5, teile: ["Teil \(i)"])
            },
            cuts: [], totals: BOMTotals(kg: 4.0, preis: 60, positionen: 40, teile: 100))
        let q = ExportQuellen(kopf: ExportKopf(projekt: "Halter", version: "V3"), bom: bom, bauplan: b.plan,
                              strichbilder: bilder,
                              zeichnungen: [ExportZeichnungsblatt(id: "z1", titel: "Blatt A3", groesse: CGSize(width: 420, height: 297)) { ctx, s in
                                  ctx.stroke(CGRect(origin: .zero, size: s).insetBy(dx: 20, dy: 20))
                              }])
        let doc = ExportBauer.dokument(ExportVorlage.standard, q)
        let arten = doc.bausteinSeiten.map(\.art)
        XCTAssertEqual(arten.first, .deckblatt)
        XCTAssertTrue(arten.contains(.stueckliste) && arten.contains(.bauplan) && arten.contains(.zeichnungen))
        XCTAssertGreaterThan(doc.bausteinSeiten.first { $0.art == .stueckliste }?.anzahl ?? 0, 1)  // 40 Zeilen brechen um
        XCTAssertEqual(doc.formate["A3 quer"], 1)
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("kc-export-\(UUID().uuidString).pdf")
        defer { try? FileManager.default.removeItem(at: url) }
        try doc.schreibePDF(nach: url)
        let pdf = try XCTUnwrap(PDFDocument(url: url))
        XCTAssertEqual(pdf.pageCount, doc.seiten.count)
        XCTAssertEqual(pdf.page(at: 0)?.bounds(for: .mediaBox).width ?? 0, 595.28, accuracy: 0.1)
        let a3 = try XCTUnwrap((0..<pdf.pageCount).compactMap { pdf.page(at: $0) }.first { $0.bounds(for: .mediaBox).width > 1000 })
        XCTAssertEqual(a3.bounds(for: .mediaBox).height, 841.89, accuracy: 0.1)
        XCTAssertGreaterThanOrEqual(pdf.outlineRoot?.numberOfChildren ?? 0, 4)
        // Text ist echter Text: Kopfzeile und Seitenzahl sind durchsuchbar
        XCTAssertTrue(pdf.page(at: 1)?.string?.contains("Seite 2 / \(pdf.pageCount)") == true)
        XCTAssertTrue(pdf.string?.contains("Deckel einbauen") == true)
        // Druckaufträge je Format, 1:1 ohne Ränder
        let auftraege = ExportDrucker.auftraege(pdf)
        XCTAssertEqual(auftraege.count, 2)
        XCTAssertEqual(auftraege.map(\.format), ["A4 hoch", "A3 quer"])
        XCTAssertEqual(auftraege.map(\.seiten).reduce(0, +), pdf.pageCount)
        XCTAssertNotNil(ExportDrucker.hinweis(auftraege))
        let info = ExportDrucker.druckInfo(auftraege[1])
        XCTAssertEqual(info.orientation, .landscape)
        XCTAssertEqual(max(info.paperSize.width, info.paperSize.height), 1190.55, accuracy: 0.1)
        XCTAssertEqual(info.leftMargin, 0)
        XCTAssertEqual(info.scalingFactor, 1)
        XCTAssertNotNil(ExportDrucker.operation(auftraege[0]))
        // Gliederung zeigt auf die erste Seite jedes Bausteins
        let zweiter = try XCTUnwrap(pdf.outlineRoot?.child(at: 1))
        XCTAssertEqual(zweiter.label, doc.bausteinSeiten[1].art.titel)
        XCTAssertEqual(zweiter.destination?.page.flatMap { pdf.index(for: $0) }, doc.bausteinSeiten[1].seite - 1)
        // Vorschaubild einer Seite
        let img = try XCTUnwrap(doc.bild(0, pixelJeMM: 2))
        XCTAssertEqual(img.width, 420)
    }
}
