import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// I-6 Live-Kopplung (PROTOCOL.md, „I-6 Live-Kopplung“): Nachrichten gegen die Testdateien aus
/// `make_kopplung_fixtures.py`, Folgen einer fremden Ansicht, Unterschiede, Live-Striche.
@MainActor
final class KopplungTests: XCTestCase {
    private func expected() throws -> JSONValue { try XCTUnwrap(Fixtures.expected()["kopplung"]) }

    private func json(_ data: Data) throws -> JSONValue { try JSONDecoder().decode(JSONValue.self, from: data) }

    private final class Gesendet {
        var rahmen: [Frame] = []
        func koepfe(_ typ: String) throws -> [JSONValue] {
            try rahmen.map { try JSONDecoder().decode(JSONValue.self, from: $0.header) }
                .filter { $0["type"]?.stringValue == typ }
        }
    }

    private func verbunden() throws -> (AppController, Gesendet) {
        let c = AppController(model: AppModel())
        let g = Gesendet()
        c.sendeBeobachter = { g.rahmen.append($0) }
        c.handle([.connected])
        let liste = LiveFaehigkeit.app.map { "\"\($0)\"" }.joined(separator: ",")
        c.handle([.message(try KernelMessage.decode(Frame(header: Data(#"{"type":"HELLO","seq":1,"protocol":1,"faehigkeiten":[\#(liste)]}"#.utf8))))])
        return (c, g)
    }

    // MARK: Nachrichten

    func testAlleRahmenSindLesbar() throws {
        for f in try XCTUnwrap(try expected()["frames"]?.arrayValue) {
            let datei = try XCTUnwrap(f["file"]?.stringValue)
            let rahmen = try Fixtures.frame(datei)
            guard f["richtung"]?.stringValue == "kernel" else { continue }
            let m = try KernelMessage.decode(rahmen)
            XCTAssertEqual(m.typeName, f["type"]?.stringValue, datei)
            guard case .kopplung = m else { return XCTFail("\(datei) nicht erkannt") }
        }
    }

    func testGrenzenWieImKernel() throws {
        let e = try expected()
        XCTAssertEqual(LiveFaehigkeit.ansicht, e["faehigkeit"]?.stringValue)
        XCTAssertEqual(AnsichtModus.allCases.map(\.rawValue), e["modi"]?.stringList)
        XCTAssertEqual(KopplungGrenzen.fuehrungPause, e["fuehrung_pause_s"]?.doubleValue)
        XCTAssertEqual(KopplungGrenzen.ansichtJeS, e["ansicht_je_s"]?.doubleValue)
        XCTAssertEqual(KopplungGrenzen.sprechenLiveJeS, e["sprechen_live_je_s"]?.doubleValue)
        XCTAssertTrue(LiveFaehigkeit.app.contains(LiveFaehigkeit.ansicht))
        XCTAssertEqual(e["teile"]?.stringList?.last, "flaeche")
        XCTAssertEqual(KopplungGrenzen.kachelnNebeneinanderAb, 640)
    }

    func testGeraeteUndAnsichtLesen() throws {
        guard case .kopplung(.geraete(let g)) = try Fixtures.message("geraete.frame") else { return XCTFail() }
        XCTAssertEqual(g.geraete.count, 2)
        XCTAssertEqual(g.geraete.filter(\.ich).map(\.anzeigeName), ["iPad von Kevin"])
        XCTAssertEqual(g.geraete.first { $0.fuehrt }?.art, "ipad")
        guard case .kopplung(.ansicht(let a)) = try Fixtures.message("ansicht_parallel.frame") else { return XCTFail() }
        XCTAssertEqual(a.von, 1)
        XCTAssertEqual(a.stand.kamera?.projektion, "orthographic")
        XCTAssertEqual(a.stand.sicht?.isoliert, ["Halter/Lasche"])
        XCTAssertNotNil(a.stand.schnitt)
        XCTAssertNil(a.stand.schnitt!, "schnitt null = kein Schnitt")
        XCTAssertNil(a.stand.auswahl)
        guard case .kopplung(.sprechenLive(let s)) = try Fixtures.message("sprechen_live_ende.frame") else {
            return XCTFail()
        }
        XCTAssertTrue(s.ende)
        XCTAssertEqual(s.von, 2)
    }

    func testRahmenDerAppGleichDenTestdateien() throws {
        for datei in ["ansicht_voll.frame", "ansicht_kamera.frame", "sprechen_live_strich.frame", "blick.frame"] {
            let kopf = try Fixtures.frame(datei).header
            var m: any OutgoingMessage
            if datei.hasPrefix("ansicht") {
                m = try JSONDecoder().decode(AnsichtMessage.self, from: kopf)
            } else if datei.hasPrefix("blick") {
                m = try JSONDecoder().decode(BlickMessage.self, from: kopf)
            } else {
                m = try JSONDecoder().decode(SprechenLiveMessage.self, from: kopf)
            }
            m.seq = try XCTUnwrap(try json(kopf)["seq"]?.intValue)
            XCTAssertEqual(try json(m.encodedHeader()), try json(kopf), datei)
        }
        for (datei, modus) in [("ansicht_modus.frame", AnsichtModus.gemeinsam), ("ansicht_modus_eigen.frame", .eigen)] {
            var m = AnsichtModusMessage(modus: modus)
            let kopf = try Fixtures.frame(datei).header
            m.seq = try XCTUnwrap(try json(kopf)["seq"]?.intValue)
            XCTAssertEqual(try json(m.encodedHeader()), try json(kopf), datei)
        }
    }

    // MARK: App

    func testVerbindungMeldetAnsicht() throws {
        let (_, g) = try verbunden()
        XCTAssertEqual(try g.koepfe("ANSICHT_MODUS").last?["modus"]?.stringValue, AnsichtModus.gemeinsam.rawValue)
        let hallo = try XCTUnwrap(try g.koepfe("HELLO_APP").first)
        XCTAssertTrue(hallo["faehigkeiten"]?.stringList?.contains(LiveFaehigkeit.ansicht) ?? false)
    }

    func testFremdeAnsichtWirdUebernommenUndNichtZurueckgeschickt() throws {
        let (c, g) = try verbunden()
        guard case .kopplung(.ansicht(let a)) = try Fixtures.message("ansicht_weiter.frame") else { return XCTFail() }
        c.handle(.kopplung(.ansicht(a)))
        // Ohne Bildschirm setzt das Folgen die Kamera sofort
        let k = try XCTUnwrap(a.stand.kamera)
        XCTAssertEqual(Double(c.viewport.camera.distance), k.abstand, accuracy: 1e-3)
        XCTAssertEqual(Double(c.viewport.camera.pivot.x), k.ziel[0], accuracy: 1e-3)
        XCTAssertEqual(c.liveKopplung.basis.kamera, AppController.kameraTeil(c.viewport.camera))
        g.rahmen = []
        // Der Stand gleicht der Basis: keine eigene ANSICHT
        let jetzt = c.ansichtJetzt(alles: false)
        XCTAssertTrue(AppController.unterschied(jetzt, zu: c.liveKopplung.basis).kamera == nil)
        XCTAssertTrue(try g.koepfe("ANSICHT").isEmpty)
        // Verzögerung wird gemessen (Senden am anderen Gerät bis hier)
        var frisch = a
        frisch.t = Date().timeIntervalSince1970 - 0.02
        frisch.voll = false
        c.handle(.kopplung(.ansicht(frisch)))
        XCTAssertEqual(try XCTUnwrap(c.kopplungLatenzMs), 20, accuracy: 15)
    }

    func testLeistenUndKachelnGehenMit() throws {
        let (c, g) = try verbunden()
        let a = try JSONDecoder().decode(AnsichtMessage.self, from: Fixtures.frame("ansicht_voll.frame").header)
        let f = try XCTUnwrap(a.stand.flaeche)
        XCTAssertEqual(f.kacheln, ["modell", "zeichnung"])
        c.model.kopplung.fensterBreite = 1200
        c.handle(.kopplung(.ansicht(a)))
        XCTAssertEqual(c.model.oberflaeche.kacheln, [.modell, .zeichnung])
        XCTAssertNil(c.model.oberflaeche.gross)
        XCTAssertEqual(c.model.oberflaeche.aktiv, .zeichnung)
        XCTAssertEqual(c.flaecheJetzt(), f, "übernommen ist gleich geteilt: nichts zurück")
        g.rahmen = []
        // Schmales Fenster: dieselben Kacheln, die aktive groß; geteilt bleibt „keine groß“
        let (schmal, _) = try verbunden()
        schmal.model.kopplung.fensterBreite = 500
        schmal.handle(.kopplung(.ansicht(a)))
        XCTAssertEqual(schmal.model.oberflaeche.gross, .zeichnung)
        XCTAssertNil(schmal.flaecheJetzt().gross)
        // Kevin ändert dort selbst: dann gilt seine Wahl
        schmal.oberflaeche(.kachelGross(.modell))
        XCTAssertEqual(schmal.flaecheJetzt().gross, "modell")
    }

    func testEigeneAnsichtFolgtNicht() throws {
        let (c, _) = try verbunden()
        c.ansichtModus(.eigen)
        let vorher = c.viewport.camera
        guard case .kopplung(.ansicht(let a)) = try Fixtures.message("ansicht_weiter.frame") else { return XCTFail() }
        c.handle(.kopplung(.ansicht(a)))
        XCTAssertEqual(c.viewport.camera, vorher)
        c.ansichtModus(.gemeinsam)
    }

    func testKevinsHandGehtVor() throws {
        let (c, _) = try verbunden()
        c.lokaleEingabe()
        XCTAssertTrue(c.liveKopplung.griffOffen)
        let vorher = c.viewport.camera
        guard case .kopplung(.ansicht(let a)) = try Fixtures.message("ansicht_weiter.frame") else { return XCTFail() }
        c.handle(.kopplung(.ansicht(a)))
        XCTAssertEqual(c.viewport.camera, vorher, "während Kevin hier bedient, folgt die App nicht")
    }

    func testUnterschiedNurGeaenderteTeile() {
        let k = AnsichtStand.Kamera(drehung: [0, 0, 0, 1], ziel: [0, 0, 0], abstand: 400, projektion: "perspective",
                                    fov: 30, orthoHoehe: 200)
        let alt = AnsichtStand(kamera: k, sicht: .init(verborgen: [], isoliert: nil), auswahl: .init(run: nil, refs: []),
                               darstellung: "shaded_edges", schnitt: .some(nil), explosion: 0)
        XCTAssertTrue(alt.vollstaendig)
        var neu = alt
        neu.kamera?.abstand = 380
        neu.schnitt = .some(.init(normale: [0, 0, -1], abstand: 5))
        let d = AppController.unterschied(neu, zu: alt)
        XCTAssertEqual(d.kamera?.abstand, 380)
        XCTAssertNotNil(d.schnitt)
        XCTAssertNil(d.sicht)
        XCTAssertNil(d.darstellung)
        XCTAssertTrue(AppController.unterschied(alt, zu: alt).leer)
    }

    func testFremdeStricheImViewerUndWegBeiEnde() throws {
        let (c, _) = try verbunden()
        guard case .kopplung(.sprechenLive(var s)) = try Fixtures.message("sprechen_live_strich.frame") else {
            return XCTFail()
        }
        s.von = 2
        c.handle(.kopplung(.sprechenLive(s)))
        let striche = c.fremdesSprechenOverlay()
        XCTAssertEqual(striche.count, 2, "ein Strich und der Zeiger")
        c.handle(.kopplung(.sprechenLive(SprechenLiveMessage(sitzung: s.sitzung, ende: true, von: 2))))
        XCTAssertTrue(c.fremdesSprechenOverlay().isEmpty)
    }

    func testBlickDesAnderenGeraetsNurInDerEigenenAnsichtUndAufWunsch() throws {
        let (c, _) = try verbunden()
        guard case .kopplung(.geraete(let liste)) = try Fixtures.message("geraete.frame") else { return XCTFail() }
        c.handle(.kopplung(.geraete(liste)))
        guard case .kopplung(.blick(var b)) = try Fixtures.message("blick_weiter.frame") else { return XCTFail() }
        b.von = 1  // das MacBook aus der Geräteliste
        c.blickZeigen(false)
        c.handle(.kopplung(.blick(b)))
        XCTAssertEqual(c.model.kopplung.blickVon, ["MacBook von Kevin"])
        XCTAssertTrue(c.fremdeBlickeOverlay().isEmpty, "Gemeinsame Ansicht: kein Rahmen")
        c.ansichtModus(.eigen)
        XCTAssertTrue(c.fremdeBlickeOverlay().isEmpty, "nur auf Wunsch")
        XCTAssertFalse(c.model.kopplung.blickSichtbar)
        c.blickZeigen(true)
        XCTAssertTrue(c.model.kopplung.blickSichtbar)
        let rahmen = c.fremdeBlickeOverlay()
        XCTAssertEqual(rahmen.count, 6, "Rahmen, vier Kanten zum Augpunkt, Name")
        c.blickZeigen(false)  // der Aus-Knopf der Kapsel
        XCTAssertTrue(c.fremdeBlickeOverlay().isEmpty)
        c.ansichtModus(.gemeinsam)
    }

    func testFremderTextLive() throws {
        let (c, _) = try verbunden()
        guard case .kopplung(.geraete(let liste)) = try Fixtures.message("geraete.frame") else { return XCTFail() }
        c.handle(.kopplung(.geraete(liste)))
        guard case .kopplung(.sprechenLive(var s)) = try Fixtures.message("sprechen_live_strich.frame") else {
            return XCTFail()
        }
        s.von = 1
        c.handle(.kopplung(.sprechenLive(s)))
        XCTAssertEqual(c.model.kopplung.fremdeTexte, [FremderText(id: 1, geraet: "MacBook von Kevin", text: "Mach das hier")])
        c.handle(.kopplung(.sprechenLive(SprechenLiveMessage(sitzung: s.sitzung, ende: true, von: 1))))
        XCTAssertTrue(c.model.kopplung.fremdeTexte.isEmpty)
    }

    func testGeraeteTextFuerDieOberflaeche() throws {
        let (c, _) = try verbunden()
        guard case .kopplung(.geraete(let g)) = try Fixtures.message("geraete.frame") else { return XCTFail() }
        c.handle(.kopplung(.geraete(g)))
        XCTAssertEqual(c.model.kopplung.liveGeraete.count, 2)
        XCTAssertTrue(c.model.kopplung.fuehrtSelbst)
        XCTAssertEqual(c.model.kopplung.ansichtText, "Gemeinsame Ansicht mit MacBook von Kevin · du führst")
        c.ansichtModus(.eigen)
        XCTAssertEqual(c.model.kopplung.ansichtText, "Eigene Ansicht · MacBook von Kevin verbunden")
        c.ansichtModus(.gemeinsam)
    }
}
