import CoreGraphics
import XCTest

@testable import KevCADCore

/// I-4 (PLAN-IPAD.md 4.4): Werkzeugkranz. Geometrie und Auswahl nach Richtung, Drehregler, Befehlskatalog mit Auslöser
/// je Gerät, Strichfarbe und Gerät im Feedback-Paket. Läuft auf Mac und iPad.
final class WerkzeugkranzTests: XCTestCase {
    private typealias G = KranzGeometrie

    // MARK: Geometrie

    func testWinkelNullObenImUhrzeigersinn() {
        XCTAssertEqual(G.winkel(0, -10), 0, accuracy: 1e-9)
        XCTAssertEqual(G.winkel(10, 0), 90, accuracy: 1e-9)
        XCTAssertEqual(G.winkel(0, 10), 180, accuracy: 1e-9)
        XCTAssertEqual(G.winkel(-10, 0), 270, accuracy: 1e-9)
        XCTAssertEqual(G.winkel(-1, -1000), 359.94, accuracy: 0.01)
    }

    func testSektorLiegtMittigUmSeineRichtung() {
        XCTAssertEqual(G.sektor(winkel: 0, anzahl: 8), 0)
        XCTAssertEqual(G.sektor(winkel: 350, anzahl: 8), 0, "kurz links von oben gehört noch zu oben")
        XCTAssertEqual(G.sektor(winkel: 22, anzahl: 8), 0)
        XCTAssertEqual(G.sektor(winkel: 23, anzahl: 8), 1)
        XCTAssertEqual(G.sektor(winkel: 90, anzahl: 8), 2)
        XCTAssertEqual(G.sektor(winkel: 337, anzahl: 8), 7)
        XCTAssertEqual(G.sektor(winkel: 150, anzahl: 5), 2)
        XCTAssertEqual(G.sektor(winkel: 181, anzahl: 5), 3, "Grenze zwischen 2 und 3 liegt bei 180°")
        XCTAssertEqual(G.sektor(winkel: 359.99, anzahl: 12), 0)
    }

    func testLageImUhrzeigersinnAbOben() {
        let oben = G.lage(index: 0, anzahl: 8, radius: 60)
        XCTAssertEqual(oben.x, 0, accuracy: 1e-9)
        XCTAssertEqual(oben.y, -60, accuracy: 1e-9)
        let rechts = G.lage(index: 2, anzahl: 8, radius: 60)
        XCTAssertEqual(rechts.x, 60, accuracy: 1e-9)
        XCTAssertEqual(rechts.y, 0, accuracy: 1e-9)
        // Lage und Auswahl passen zusammen: Wer auf ein Symbol zeigt, trifft sein Feld
        for n in [5, 8, 9, 12] {
            for i in 0..<n {
                let p = G.lage(index: i, anzahl: n, radius: 50)
                XCTAssertEqual(G.sektor(winkel: G.winkel(p.x, p.y), anzahl: n), i, "\(i) von \(n)")
            }
        }
    }

    func testZielAufDerScheibe() {
        XCTAssertEqual(G.ziel(CGPoint(x: 3, y: -4), ebene: .haupt, unterAnzahl: 0, gezogen: false), .mitte)
        XCTAssertEqual(G.ziel(CGPoint(x: 0, y: -G.pillenRadius), ebene: .haupt, unterAnzahl: 0, gezogen: false),
                       .pille(0))
        XCTAssertEqual(G.ziel(CGPoint(x: 0, y: -G.feldRadius), ebene: .haupt, unterAnzahl: 0, gezogen: false), .feld(0))
        XCTAssertEqual(G.ziel(CGPoint(x: G.feldRadius, y: 0), ebene: .haupt, unterAnzahl: 0, gezogen: false), .feld(2),
                       "rechts liegt die Darstellung")
        XCTAssertEqual(KranzFeld.allCases[2], .darstellung)
        // Weit daneben: ein Tipp bricht ab, ein Wisch wählt nach seiner Richtung
        let weit = CGPoint(x: 0, y: 400)
        XCTAssertEqual(G.ziel(weit, ebene: .haupt, unterAnzahl: 0, gezogen: false), .daneben)
        XCTAssertEqual(G.ziel(weit, ebene: .haupt, unterAnzahl: 0, gezogen: true), .feld(4))
        XCTAssertEqual(KranzFeld.allCases[4], .mehr, "unten liegt „mehr“ wie im Plan")
    }

    func testZielImZweitenRing() {
        let n = Tastenbelegung.kranz(.ansichten).count
        let e = KranzEbene.feld(.ansichten)
        XCTAssertEqual(G.ziel(CGPoint(x: 0, y: -G.unterRadius), ebene: e, unterAnzahl: n, gezogen: false), .unter(0))
        XCTAssertEqual(Tastenbelegung.kranz(.ansichten)[0].aktion, .befehl(.oben), "oben liegt die Ansicht von oben")
        let rechts = Tastenbelegung.kranz(.ansichten)[G.sektor(winkel: 90, anzahl: n)]
        XCTAssertEqual(rechts.aktion, .befehl(.rechts), "rechts die Ansicht von rechts")
        let unten = Tastenbelegung.kranz(.ansichten)[G.sektor(winkel: 180, anzahl: n)]
        XCTAssertEqual(unten.aktion, .befehl(.unten))
        let links = Tastenbelegung.kranz(.ansichten)[G.sektor(winkel: 270, anzahl: n)]
        XCTAssertEqual(links.aktion, .befehl(.links))
        // Auf der Scheibe bleibt das Feld wählbar, weit daneben nur gewischt
        XCTAssertEqual(G.ziel(CGPoint(x: 0, y: -G.feldRadius), ebene: e, unterAnzahl: n, gezogen: false), .feld(0))
        XCTAssertEqual(G.ziel(CGPoint(x: 0, y: -500), ebene: e, unterAnzahl: n, gezogen: false), .daneben)
        XCTAssertEqual(G.ziel(CGPoint(x: 0, y: -500), ebene: e, unterAnzahl: n, gezogen: true), .unter(0))
    }

    func testKranzBleibtImBild() {
        let groesse = CGSize(width: 1000, height: 700)
        let r = G.platz + 8
        let m = G.mitte(fuer: CGPoint(x: 5, y: 690), in: groesse)
        XCTAssertEqual(m.x, r, accuracy: 1e-9)
        XCTAssertEqual(m.y, 700 - r, accuracy: 1e-9)
        XCTAssertEqual(G.mitte(fuer: CGPoint(x: 500, y: 350), in: groesse), CGPoint(x: 500, y: 350))
        // Zu klein für den ganzen Kranz: dann mittig
        XCTAssertEqual(G.mitte(fuer: .zero, in: CGSize(width: 200, height: 200)), CGPoint(x: 100, y: 100))
    }

    // MARK: Drehregler

    func testVolleUmdrehungDurchlaeuftDenBereich() {
        let b = KranzReglerBereich(min: 0, max: 1, raster: 0.05)
        XCTAssertEqual(G.reglerWert(0, grad: 360, bereich: b), 1, accuracy: 1e-9)
        XCTAssertEqual(G.reglerWert(0.5, grad: -90, bereich: b), 0.25, accuracy: 1e-9)
        XCTAssertEqual(G.reglerWert(0.9, grad: 180, bereich: b), 1, "endet am Anschlag")
        // Kleine Schritte sammeln sich im Rohwert, bis sie eine Raste erreichen
        var roh = 0.0
        for _ in 0..<10 { roh = G.reglerWert(roh, grad: 1.5, bereich: b) }
        XCTAssertEqual(b.klemmen(roh), 0.05, accuracy: 1e-9)
        XCTAssertEqual(b.klemmen(0.024), 0)
    }

    func testWinkelSchrittUeberNull() {
        XCTAssertEqual(G.winkelSchritt(von: 350, nach: 10), 20, accuracy: 1e-9)
        XCTAssertEqual(G.winkelSchritt(von: 10, nach: 350), -20, accuracy: 1e-9)
        XCTAssertEqual(G.winkelSchritt(von: 90, nach: 180), 90, accuracy: 1e-9)
    }

    func testMausradJeRasteEinTeilstrich() {
        let b = ViewerStore.strichbreiten
        XCTAssertEqual(b.klemmen(G.reglerWert(3, schritte: 1, regler: .strichbreite, bereich: b)), 4)
        XCTAssertEqual(b.klemmen(G.reglerWert(3, schritte: -5, regler: .strichbreite, bereich: b)), 1)
        let e = KranzReglerBereich(min: 0, max: 1, raster: 0.05)
        XCTAssertEqual(e.klemmen(G.reglerWert(0, schritte: 2, regler: .explosion, bereich: e)), 0.1, accuracy: 1e-9)
        XCTAssertEqual(KranzRegler.explosion.text(0.4), "40 %")
        XCTAssertEqual(KranzRegler.schnitt.text(120.4), "120 mm")
    }

    // MARK: Befehlskatalog

    /// Jeder Befehl hat am Mac eine Taste und am iPad einen Auslöser ohne Tastatur (Geste, Knopf, Kranz) oder eine
    /// begründete Ausnahme. Wer einen Befehl dazunimmt, trägt beides im selben Schritt ein.
    func testJederBefehlHatAuslöserAufBeidenGeraeten() {
        for b in ViewerBefehl.allCases {
            guard let bel = Tastenbelegung.belegung(b) else {
                XCTFail("\(b) fehlt in Tastenbelegung.alle")
                continue
            }
            XCTAssertFalse(bel.tasten.isEmpty, "\(b): keine Taste am Mac")
            XCTAssertFalse(Tastenbelegung.ipadAusloeser(b).isEmpty, "\(b): kein Auslöser am iPad")
        }
    }

    func testKranzFelderSindVollstaendigUndEindeutig() {
        for f in KranzFeld.allCases {
            let e = Tastenbelegung.kranz(f)
            XCTAssertTrue(e.isEmpty != (Tastenbelegung.kranzDirekt(f) == nil), "\(f): entweder Ring oder direkt")
            XCTAssertLessThanOrEqual(e.count, 12, "\(f): höchstens zwölf Einträge, sonst werden sie zu eng")
            XCTAssertEqual(Set(e.map(\.name)).count, e.count, "\(f): Namen doppelt")
            for x in e {
                if case .befehl(let b) = x.aktion {
                    XCTAssertNotNil(Tastenbelegung.belegung(b), "\(f): \(b) ohne Belegung")
                }
            }
        }
        XCTAssertEqual(Tastenbelegung.kranzDirekt(.sprechen), .sprechenOderSenden, "oben: Sprechen bzw. Senden")
        XCTAssertEqual(Tastenbelegung.kranzWeg(.vorne), "Kranz › Ansichten › Vorne")
        XCTAssertEqual(Tastenbelegung.kranzWeg(.shadingMenue), "Kranz › Darstellung")
        XCTAssertNil(Tastenbelegung.kranzWeg(.drehenLinks), "Drehen in Schritten geht am iPad mit dem Finger")
        // Explosion, Schnittebene und Strichbreite sind Drehregler (PLAN-IPAD.md 4.4)
        let regler = KranzFeld.allCases.flatMap(Tastenbelegung.kranz).compactMap { e -> KranzRegler? in
            if case .regler(let r) = e.aktion { return r }
            return nil
        }
        XCTAssertEqual(Set(regler), Set(KranzRegler.allCases))
    }

    func testQOeffnetDenKranz() {
        XCTAssertEqual(Tastenbelegung.menuTaste(.werkzeugkranz), .z("q"))
        XCTAssertTrue(Tastenbelegung.einfacheZeichen.contains("q"))
        XCTAssertEqual(Tastenbelegung.befehl(keyCode: 12, zeichen: "q", flags: []), .werkzeugkranz)
    }

    // MARK: Paket

    func testStrichTraegtFarbeUndGeraet() throws {
        var s = FeedbackSitzung(id: "s-1", uhrStart: 1000, uhrNull: 50)
        let kamera = JSONValue.object(["abstand": .number(100)])
        s.strichBeginnen(t: 1, run: 3, kamera: kamera, farbe: .rot, geraet: .ipad)
        s.strichPunkt(.init(t: 1, bild: [0, 0], welt: [0, 0, 0], ref: nil), teil: nil)
        s.strichEnden(t: 1.2)
        s.strichBeginnen(t: 2, run: 3, kamera: kamera)
        s.strichPunkt(.init(t: 2, bild: [0, 0], welt: [0, 0, 0], ref: nil), teil: nil)
        s.strichEnden(t: 2.2)
        XCTAssertEqual(s.striche.map(\.farbe), ["rot", nil])
        XCTAssertEqual(s.striche.map(\.geraet), ["ipad", nil])
        XCTAssertEqual(s.striche.map(\.strichfarbe), [.rot, .blau], "ohne Farbe lichtblau wie bisher")
        let p = s.paket(name: "fb-20261107-120000", erstellt: Date(), dauer: 3, spracherkennung: "test",
                        projekt: .init(name: "P", pfad: "/tmp/P"), run: 3, ende: .object([:]), bild: nil,
                        geraet: .ipad)
        XCTAssertEqual(p.geraet, "ipad")
        let json = try JSONDecoder().decode(JSONValue.self, from: p.json())
        guard case .object(let o) = json, case .array(let striche)? = o["striche"], case .object(let erster) = striche[0],
            case .object(let zweiter) = striche[1]
        else { return XCTFail("Paket ohne Striche") }
        XCTAssertEqual(o["geraet"], .string("ipad"))
        XCTAssertEqual(erster["farbe"], .string("rot"))
        XCTAssertNil(zweiter["farbe"], "ohne Farbe steht das Feld nicht im Paket (wie ältere Pakete)")
        XCTAssertEqual(Set(Strichfarbe.allCases.map(\.rawValue)), ["rot", "gelb", "gruen", "blau", "weiss"],
                       "Namen wie FEEDBACK_STRICHFARBEN in protocol.py")
        XCTAssertEqual(Strichfarbe.blau.rgba, ViewerStil.strich)
    }
}
