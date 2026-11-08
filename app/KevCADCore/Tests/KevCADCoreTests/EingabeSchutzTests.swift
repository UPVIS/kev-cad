#if os(macOS)
import AppKit
#endif
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Schutz vor Fehleingaben (Kevin, 08.11.2026; EingabeSchutz.swift, PLAN-IPAD.md 4.2 und 4.3): Sperre beim Erklären,
/// Handballen am iPad, Doppeltippen ohne Auswahl nebenbei. Läuft auf Mac und iPad.
@MainActor
final class EingabeSchutzTests: XCTestCase {
    // MARK: Sperre

    func testSperreLaesstNurKameraZeigenUndZeichnen() {
        let erlaubtGesperrt = Set(ViewerEingabeArt.allCases.filter { EingabeSchutz.erlaubt($0, gesperrt: true) })
        XCTAssertEqual(erlaubtGesperrt, [.kamera, .zeigen, .strich, .nadel, .randWischen])
        let erlaubtFrei = Set(ViewerEingabeArt.allCases.filter { EingabeSchutz.erlaubt($0, gesperrt: false) })
        XCTAssertEqual(erlaubtFrei, Set(ViewerEingabeArt.allCases).subtracting([.strich, .nadel]),
                       "ohne Sitzung wirkt alles außer Strich und Nadel")
        XCTAssertEqual(EingabeSchutz.tippenBeimSprechen(stift: true), .nadel)
        XCTAssertEqual(EingabeSchutz.tippenBeimSprechen(stift: false), .zeigen, "der Finger zeigt nur")
    }

    func testGesperrteGestenStehenBeimSprechenNichtInDerLeiste() {
        let gesperrt = GestenBelegung.Geste.allCases.filter {
            !EingabeSchutz.erlaubt(EingabeSchutz.art($0), gesperrt: true)
        }
        XCTAssertEqual(Set(gesperrt), [.tippen, .doppeltTippen, .halten, .zweiFingerTippen, .dreiFingerTippen])
        XCTAssertTrue(Tastenbelegung.gesten.contains { $0.geste == .tippen && $0.zustand == .sprechen },
                      "beim Sprechen hat Tippen eine eigene Zeile (Zeigen, Nadel)")
        XCTAssertTrue(Tastenbelegung.maus.contains { $0.geraet == .links && !$0.ziehen && $0.zustand == .sprechen },
                      "am Mac: Klick beim Sprechen setzt einen Bezug")
    }

    private func sitzung() throws -> AppController {
        let c = AppController(model: AppModel())
        let events = try FrameReader().feed(Fixtures.data("stream.bin")).map(KernelConnection.decode)
        c.handle(Array(events.prefix(7)))
        let ordner = FileManager.default.temporaryDirectory.appendingPathComponent("eingabeschutz-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: ordner, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: ordner) }
        c.model.project = ProjectInfo(path: ordner, name: "P", modelFile: ordner.appendingPathComponent("model.py"))
        let t = TestErkennung()
        c.sprache.erkennungFabrik = { t }
        c.sprache.gesendet = { _ in }
        return c
    }

    func testSprechenSperrtBeideViewerUndPauseGibtFrei() throws {
        let c = try sitzung()
        XCTAssertTrue(c.viewport.erlaubt(.auswaehlen))
        c.oberflaeche(.sprechen(true))
        for v in [c.viewport, c.zweiterViewer.coordinator] {
            XCTAssertFalse(v.erlaubt(.auswaehlen) || v.erlaubt(.einrahmen) || v.erlaubt(.kontextmenue)
                           || v.erlaubt(.verlauf) || v.erlaubt(.griff) || v.erlaubt(.rahmen))
            XCTAssertTrue(v.erlaubt(.kamera) && v.erlaubt(.zeigen) && v.erlaubt(.nadel))
        }
        c.oberflaeche(.sprechen(false))
        XCTAssertTrue(c.viewport.erlaubt(.auswaehlen), "in der Pause gehört das Modell wieder Kevin (kein roter Rahmen)")
        c.oberflaeche(.sprechenVerwerfen)
        XCTAssertTrue(c.viewport.erlaubt(.auswaehlen))
    }

    // MARK: Handballen

    private let stiftOrt = CGPoint(x: 600, y: 500)

    private func finger(_ dx: CGFloat, _ dy: CGFloat, radius: CGFloat = 20, zeit: TimeInterval = 100) -> FingerBeruehrung {
        FingerBeruehrung(ort: CGPoint(x: stiftOrt.x + dx, y: stiftOrt.y + dy), radius: radius, zeit: zeit)
    }

    func testGrosseFlaecheIstImmerHand() {
        XCTAssertTrue(Handballen.istHand(finger(-900, -400, radius: 60), stift: nil), "ohne Stift, weit weg: trotzdem Ballen")
        XCTAssertFalse(Handballen.istHand(finger(-900, -400, radius: 20), stift: nil), "Fingerkuppe ohne Stift zählt")
        XCTAssertFalse(Handballen.istHand(finger(0, 0, radius: 35), stift: nil), "fest aufgelegter Daumen zählt")
    }

    func testNaheDemStiftAufDerSeiteDerHand() {
        // Rechte Hand: Pencil-Azimut zeigt nach rechts unten (zur Hand)
        let s = StiftLage(ort: stiftOrt, zeit: 100, liegtAuf: true, zurHand: CGVector(dx: 0.6, dy: 0.8))
        XCTAssertTrue(Handballen.istHand(finger(150, 220), stift: s), "Ballen rechts unter der Spitze")
        XCTAssertTrue(Handballen.istHand(finger(-70, 40), stift: s), "kleiner Finger dicht neben der Spitze")
        XCTAssertFalse(Handballen.istHand(finger(-380, -120), stift: s), "andere Hand links oben navigiert weiter")
        XCTAssertFalse(Handballen.istHand(finger(700, 600), stift: s), "weit weg zählt wieder")
        // Linke Hand: Azimut nach links unten, jetzt ist rechts unten frei
        let links = StiftLage(ort: stiftOrt, zeit: 100, liegtAuf: true, zurHand: CGVector(dx: -0.6, dy: 0.8))
        XCTAssertTrue(Handballen.istHand(finger(-150, 220), stift: links))
        XCTAssertFalse(Handballen.istHand(finger(330, 120), stift: links))
        // Ohne Azimut gilt die rechte Hand
        let ohne = StiftLage(ort: stiftOrt, zeit: 100, liegtAuf: false)
        XCTAssertTrue(Handballen.istHand(finger(150, 220), stift: ohne))
    }

    func testNachlaufUndVergessenesAbheben() {
        let schwebt = StiftLage(ort: stiftOrt, zeit: 100, liegtAuf: false)
        XCTAssertTrue(Handballen.istHand(finger(150, 220, zeit: 100.4), stift: schwebt), "0,4 s nach dem Stift noch Hand")
        XCTAssertFalse(Handballen.istHand(finger(150, 220, zeit: 100.7), stift: schwebt), "nach 0,5 s wieder Finger")
        let liegt = StiftLage(ort: stiftOrt, zeit: 100, liegtAuf: true)
        XCTAssertTrue(Handballen.istHand(finger(150, 220, zeit: 102), stift: liegt), "der ruhende Stift liegt noch auf")
        XCTAssertFalse(Handballen.istHand(finger(150, 220, zeit: 105), stift: liegt),
                       "kam das Abheben nicht an, ist der Stift nach 4 s Stille weg")
    }

    func testBallenUndFingerSindKeinZweiFingerTippen() {
        let s = StiftLage(ort: stiftOrt, zeit: 100, liegtAuf: true, zurHand: CGVector(dx: 0.6, dy: 0.8))
        XCTAssertTrue(Handballen.enthaeltHand([finger(-400, -100), finger(150, 220)], stift: s))
        XCTAssertFalse(Handballen.enthaeltHand([finger(-400, -100), finger(-450, -40)], stift: s),
                       "zwei Finger der anderen Hand bleiben eine Geste")
        XCTAssertTrue(Handballen.enthaeltHand([finger(-900, -100), finger(-950, -40, radius: 55)], stift: nil))
    }

    // MARK: Doppeltippen

    func testTippFolgeMerktSichDenStandVorDemErstenTipp() {
        var f = TippFolge<[String]>()
        f.tipp(stand: ["vorher"], zeit: 10)
        f.tipp(stand: ["nach Tipp 1"], zeit: 10.25)  // der zweite Tipp derselben Folge überschreibt nicht
        XCTAssertEqual(f.doppelt(zeit: 10.3), ["vorher"])
        XCTAssertNil(f.doppelt(zeit: 10.35), "einmal zurückgenommen, dann ist nichts mehr da")
        f.tipp(stand: ["a"], zeit: 20)
        XCTAssertNil(f.doppelt(zeit: 21), "zu lange her: kein Tipp dieses Doppeltippens")
        f.tipp(stand: ["b"], zeit: 30)
        f.tipp(stand: ["c"], zeit: 31)
        XCTAssertEqual(f.doppelt(zeit: 31.2), ["c"], "neue Folge nach einer Pause")
    }

    func testDoppeltippenWaehltNichtNebenbeiAus() throws {
        let c = try sitzung()
        let platte = SceneStore.bodyID(part: "Grundplatte", chunk: 0)
        let bolzen = SceneStore.bodyID(part: "Halter/Bolzen", chunk: 0)
        func pick(_ o: UInt32, _ prim: UInt32) -> PickResult? {
            PickResult(rawValue: o | (prim << 16), indexMap: [0: platte, 1: bolzen])
        }
        c.applySelection([.part("Halter/Bolzen")])
        c.setSelectionMode(.elements)
        // Kevins Fall: Doppeltippen auf ein Teil im Elementmodus. Der erste Tipp wählt die Fläche, das Doppeltippen
        // nimmt das zurück und rahmt das Teil ein.
        c.handleClick(pick(0, 11), modifiers: [])
        XCTAssertEqual(c.model.selection.map(\.ref), ["Grundplatte#f5"], "erster Tipp: Fläche")
        let vorher = c.viewport.kameraZiel
        c.doppeltTippen(pick(0, 11), in: c.viewport)
        XCTAssertEqual(c.model.selection.map(\.ref), ["Halter/Bolzen"], "Auswahl wie vor dem Doppeltippen")
        XCTAssertEqual(c.model.selectionMode, .elements, "der Modus bleibt, wie er war")
        XCTAssertNotEqual(c.viewport.kameraZiel.distance, vorher.distance, "auf das Teil eingerahmt")
        // Doppeltippen ohne Tipp kurz davor (etwa nach einer Pause) lässt die Auswahl stehen
        c.doppeltTippen(nil, in: c.viewport)
        XCTAssertEqual(c.model.selection.map(\.ref), ["Halter/Bolzen"])
    }

    // MARK: Nadel

    func testNadelErscheintAlsPunkt() {
        let p = FeedbackPaket.StrichPunkt(t: 0, bild: [1, 1], welt: [1, 2, 3], ref: nil)
        let s = FeedbackPaket.Strich(nr: 1, t: 0, bis: 0, run: 1, teile: [], laengeMm: 0, kamera: .null, punkte: [p, p],
                                     farbe: nil, geraet: nil)
        guard case .dot(let ort, _, _)? = SprachSteuerung.strichItems([s]).first else {
            return XCTFail("Nadel ohne Punkt")
        }
        XCTAssertEqual(ort, SIMD3(1, 2, 3))
    }

    #if os(macOS)
    // MARK: Mac: Klick beim Sprechen

    private func maus(_ typ: NSEvent.EventType, _ p: CGPoint, _ mods: NSEvent.ModifierFlags = []) -> NSEvent {
        NSEvent.mouseEvent(with: typ, location: p, modifierFlags: mods, timestamp: 0, windowNumber: 0, context: nil,
                           eventNumber: 0, clickCount: 1, pressure: 1)!
    }

    func testKlickBeimSprechenAendertDieAuswahlNichtUndSetztEineNadel() throws {
        let c = try sitzung()
        let platte = SceneStore.bodyID(part: "Grundplatte", chunk: 0)
        c.handleClick(PickResult(rawValue: 0 | (11 << 16), indexMap: [0: platte]), modifiers: [])
        XCTAssertEqual(c.model.selection.map(\.ref), ["Grundplatte"])
        let v = NavigationInputView(frame: CGRect(x: 0, y: 0, width: 400, height: 300))
        v.coordinator = c.viewport
        var menueGefragt = false
        c.viewport.onKontextmenue = { _ in
            menueGefragt = true
            return []
        }
        c.oberflaeche(.sprechen(true))
        for mods: NSEvent.ModifierFlags in [[], .shift, .command] {
            v.mouseDown(with: maus(.leftMouseDown, CGPoint(x: 200, y: 150), mods))
            v.mouseUp(with: maus(.leftMouseUp, CGPoint(x: 200, y: 150), mods))
        }
        v.rightMouseDown(with: maus(.rightMouseDown, CGPoint(x: 200, y: 150)))
        XCTAssertEqual(c.model.selection.map(\.ref), ["Grundplatte"], "Klick in der Sitzung ändert die Auswahl nicht")
        XCTAssertFalse(menueGefragt, "kein Kontextmenü in der Sitzung")
        XCTAssertEqual(c.sprache.sitzung?.striche.count, 3, "jeder Klick ein Bezug (Nadel)")
        c.oberflaeche(.sprechenVerwerfen)
        // Ohne Sitzung wählt der Klick wieder (leerer Grund hebt die Auswahl auf)
        v.mouseDown(with: maus(.leftMouseDown, CGPoint(x: 200, y: 150)))
        v.mouseUp(with: maus(.leftMouseUp, CGPoint(x: 200, y: 150)))
        XCTAssertEqual(c.model.selection.map(\.ref), [])
    }
    #endif
}
