import Combine
import XCTest
@testable import KevCADCore

/// V2-3: Zustand der Oberfläche (Modus, Kacheln, Rand), Entwürfe und Änderungen an model.py aus der Oberfläche.
final class OberflaechenZustandTests: XCTestCase {
    func testKachelnHoechstensVierUndModellBleibt() {
        var z = OberflaechenZustand(modus: .werkstatt, kacheln: [.modell])
        for a in [KachelArt.zeichnung, .stueckliste, .zuschnitt] { z.anwenden(.kachelZeigen(a)) }
        XCTAssertEqual(z.kacheln, [.modell, .zeichnung, .stueckliste, .zuschnitt])
        XCTAssertEqual(z.nummer(.stueckliste), 3)
        z.anwenden(.kachelZeigen(.material))
        // Die älteste außer Modell weicht, die neue kommt hinten an
        XCTAssertEqual(z.kacheln, [.modell, .stueckliste, .zuschnitt, .material])
        XCTAssertEqual(z.aktiv, .material)
        XCTAssertEqual(z.kachel(nummer: 4), .material)
        XCTAssertNil(z.kachel(nummer: 5))
    }

    func testKachelZeigenWechseltInDieWerkstatt() {
        var z = OberflaechenZustand()
        XCTAssertEqual(z.modus, .fokus)
        z.anwenden(.kachelZeigen(.modell))
        XCTAssertEqual(z.modus, .fokus, "das Modell sieht man auch im Fokus")
        z.anwenden(.kachelZeigen(.zeichnung))
        XCTAssertEqual(z.modus, .werkstatt)
    }

    func testGrossUndSchliessen() {
        var z = OberflaechenZustand(modus: .werkstatt, kacheln: [.modell, .zeichnung, .stueckliste])
        z.anwenden(.kachelGross(.zeichnung))
        XCTAssertEqual(z.gross, .zeichnung)
        z.anwenden(.kachelZeigen(.stueckliste))
        XCTAssertNil(z.gross, "eine andere Kachel nach vorn holen ordnet wieder ein")
        z.anwenden(.kachelGross(.stueckliste))
        z.anwenden(.kachelSchliessen(.stueckliste))
        XCTAssertNil(z.gross)
        XCTAssertEqual(z.kacheln, [.modell, .zeichnung])
        XCTAssertEqual(z.aktiv, .zeichnung)
    }

    func testOrdnenOhneDoppelteUndHoechstensVier() {
        var z = OberflaechenZustand()
        z.anwenden(.kachelnOrdnen([.zeichnung, .modell, .zeichnung, .stueckliste, .zuschnitt, .ansicht]))
        XCTAssertEqual(z.kacheln, [.zeichnung, .modell, .stueckliste, .zuschnitt])
        XCTAssertEqual(z.modus, .werkstatt)
    }

    func testRandMerktDenModus() {
        var z = OberflaechenZustand(modus: .werkstatt, kacheln: [.modell, .zeichnung])
        z.anwenden(.rand(.rechts))
        XCTAssertEqual(z.rand, .rechts)
        XCTAssertEqual(z.modus, .fokus)
        z.anwenden(.rand(.links))
        XCTAssertEqual(z.rand, .links)
        z.anwenden(.rand(nil))
        XCTAssertNil(z.rand)
        XCTAssertEqual(z.modus, .werkstatt)
    }

    @MainActor
    func testStoreVeroeffentlichtNurAenderungen() {
        let s = OberflaechenStore()
        var meldungen = 0
        let c = s.objectWillChange.sink { meldungen += 1 }
        s.ausfuehren(.sprechen(true))
        s.ausfuehren(.sprechen(true))
        XCTAssertTrue(s.spricht)
        XCTAssertEqual(meldungen, 1)
        c.cancel()
    }
}

final class EntwurfAblageTests: XCTestCase {
    private var temp: URL!
    private var ablage: EntwurfAblage!

    override func setUpWithError() throws {
        temp = FileManager.default.temporaryDirectory
            .appendingPathComponent("kevcad-entwurf-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
        ablage = EntwurfAblage(ordner: temp.appendingPathComponent("Entwürfe", isDirectory: true))
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: temp)
    }

    /// Legt einen Entwurf an wie der Kernel (model.py, kevcad.json, output, .kevcad) und merkt ihn.
    private func anlegen(_ datum: Date = Date()) throws -> URL {
        let p = ablage.neuerProjektordner(datum: datum)
        let fm = FileManager.default
        try fm.createDirectory(at: p.appendingPathComponent("output"), withIntermediateDirectories: true)
        try fm.createDirectory(at: p.appendingPathComponent(".kevcad/versions"), withIntermediateDirectories: true)
        try "from build123d import *\n".write(to: p.appendingPathComponent("model.py"), atomically: true, encoding: .utf8)
        try "{}\n".write(to: p.appendingPathComponent("kevcad.json"), atomically: true, encoding: .utf8)
        XCTAssertTrue(ablage.merken(p))
        return p
    }

    func testNeuerEntwurfIstLeerUndLiegtInDerAblage() throws {
        let p = try anlegen()
        XCTAssertEqual(p.lastPathComponent, "Neues Projekt")
        XCTAssertTrue(ablage.enthaelt(p))
        XCTAssertFalse(ablage.enthaelt(temp))
        XCTAssertTrue(ablage.istLeer(p))
        XCTAssertEqual(ablage.alle().map(\.lastPathComponent), ["Neues Projekt"])
        XCTAssertTrue(ablage.mitInhalt().isEmpty)
    }

    func testGeaendertesModellZaehltAlsInhalt() throws {
        let p = try anlegen()
        try "show(Box(1, 1, 1), \"Klotz\")\n".write(
            to: p.appendingPathComponent("model.py"), atomically: true, encoding: .utf8)
        XCTAssertFalse(ablage.istLeer(p))
        XCTAssertEqual(ablage.mitInhalt().count, 1)
        XCTAssertTrue(ablage.aufraeumen().isEmpty, "mit Inhalt wird nichts gelöscht")
        XCTAssertTrue(FileManager.default.fileExists(atPath: p.path))
    }

    func testDateienZaehlenAlsInhalt() throws {
        let p = try anlegen()
        try "x".write(to: p.appendingPathComponent("output/bild.png"), atomically: true, encoding: .utf8)
        XCTAssertFalse(ablage.istLeer(p))
        let q = try anlegen(Date().addingTimeInterval(5))
        try FileManager.default.createDirectory(
            at: q.appendingPathComponent("referenzen"), withIntermediateDirectories: true)
        XCTAssertFalse(ablage.istLeer(q))
    }

    func testOhneMarkeNieLeer() throws {
        let p = ablage.neuerProjektordner()
        try FileManager.default.createDirectory(at: p, withIntermediateDirectories: true)
        try "x\n".write(to: p.appendingPathComponent("model.py"), atomically: true, encoding: .utf8)
        XCTAssertFalse(ablage.istLeer(p))
    }

    func testAufraeumenLoeschtLeereAusserDemOffenen() throws {
        let a = try anlegen(Date(timeIntervalSince1970: 1_000_000))
        let b = try anlegen(Date(timeIntervalSince1970: 2_000_000))
        let weg = ablage.aufraeumen(ausser: [b])
        XCTAssertEqual(weg.map { $0.standardizedFileURL }, [a.standardizedFileURL])
        XCTAssertFalse(FileManager.default.fileExists(atPath: a.deletingLastPathComponent().path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: b.path))
        XCTAssertTrue(ablage.loeschenWennLeer(b))
        XCTAssertTrue(ablage.alle().isEmpty)
    }

    func testUebernehmenZiehtMitNamenAus() throws {
        let p = try anlegen()
        try "show(Box(1, 1, 1), \"Klotz\")\n".write(
            to: p.appendingPathComponent("model.py"), atomically: true, encoding: .utf8)
        let ziel = temp.appendingPathComponent("Kev CAD", isDirectory: true)
        try FileManager.default.createDirectory(
            at: ziel.appendingPathComponent("Kamerawagen"), withIntermediateDirectories: true)
        let neu = try ablage.uebernehmen(p, name: "Kamerawagen", nach: ziel)
        XCTAssertEqual(neu.lastPathComponent, "Kamerawagen 2")
        XCTAssertTrue(ProjectLocator.isProject(neu))
        XCTAssertFalse(ablage.hatMarke(neu))
        XCTAssertFalse(FileManager.default.fileExists(atPath: p.deletingLastPathComponent().path))
        XCTAssertFalse(ablage.enthaelt(neu))
    }

    func testUmbenennenImSelbenOrdner() throws {
        let p = temp.appendingPathComponent("Regal", isDirectory: true)
        try FileManager.default.createDirectory(at: p, withIntermediateDirectories: true)
        try "x\n".write(to: p.appendingPathComponent("model.py"), atomically: true, encoding: .utf8)
        let neu = try EntwurfAblage.umbenennen(p, name: "Regal Keller")
        XCTAssertEqual(neu.lastPathComponent, "Regal Keller")
        XCTAssertTrue(ProjectLocator.isProject(neu))
        XCTAssertEqual(try EntwurfAblage.umbenennen(neu, name: "Regal Keller"), neu)
    }
}

final class ModellQuelleTests: XCTestCase {
    private let code = """
        hoehe = param("hoehe", 120)  # Länge der Grundplatte
        abstand = param('abstand', 70.5, min=10)
        loch = param("loch", 2 * 3.3)
        show(platte, "Halter/Grundplatte")
        lasche = flach.verbauen(laenge=arm, name="Halter/Lasche")
        show(lasche, "Halter/Lasche")
        show(rohr, 'Rohr')
        befestigt("Halter/Grundplatte", grund="Wand")
        for i in range(4):
            show(rolle, f"Rollen/Rolle {i}")
        """

    func testParameterSetzen() throws {
        let neu = try ModellQuelle.setzeParameter(code, name: "hoehe", wert: 140).get()
        XCTAssertTrue(neu.contains(#"param("hoehe", 140)  # Länge"#))
        let b = try ModellQuelle.setzeParameter(code, name: "abstand", wert: 72.25).get()
        XCTAssertTrue(b.contains("param('abstand', 72.25, min=10)"))
    }

    func testParameterAlsAusdruckOderFehlend() {
        XCTAssertEqual(ModellQuelle.setzeParameter(code, name: "loch", wert: 7).fehlerWert,
                       .parameterNichtGefunden("loch"))
        XCTAssertEqual(ModellQuelle.setzeParameter(code, name: "breite", wert: 7).fehlerWert,
                       .parameterNichtGefunden("breite"))
        let doppelt = code + "\nh2 = param(\"hoehe\", 10)\n"
        XCTAssertEqual(ModellQuelle.setzeParameter(doppelt, name: "hoehe", wert: 7).fehlerWert,
                       .parameterMehrdeutig("hoehe", 2))
    }

    func testZahlenLesenUndSchreiben() {
        XCTAssertEqual(ModellQuelle.zahl(aus: "1040"), 1040)
        XCTAssertEqual(ModellQuelle.zahl(aus: "12,5 mm"), 12.5)
        XCTAssertEqual(ModellQuelle.zahl(aus: "Ø 100"), 100)
        XCTAssertEqual(ModellQuelle.zahl(aus: "1.234,5"), 1234.5)
        XCTAssertNil(ModellQuelle.zahl(aus: "viel"))
        XCTAssertEqual(ModellQuelle.zahlText(140), "140")
        XCTAssertEqual(ModellQuelle.zahlText(12.5), "12.5")
        XCTAssertEqual(ModellQuelle.zahlText(-0.125), "-0.125")
    }

    func testTeilUmbenennen() throws {
        let r = try ModellQuelle.benenneUm(code, name: "Halter/Lasche", gruppe: false, neuerLetzterTeil: "Arm").get()
        XCTAssertEqual(r.stellen, 2)
        XCTAssertEqual(r.neuerName, "Halter/Arm")
        XCTAssertTrue(r.code.contains(#"name="Halter/Arm""#))
        XCTAssertTrue(r.code.contains(#"show(lasche, "Halter/Arm")"#))
        XCTAssertTrue(r.code.contains(#""Halter/Grundplatte""#), "andere Teile bleiben")
        let rohr = try ModellQuelle.benenneUm(code, name: "Rohr", gruppe: false, neuerLetzterTeil: "Stange").get()
        XCTAssertTrue(rohr.code.contains("show(rohr, 'Stange')"))
    }

    func testGruppeUmbenennen() throws {
        let r = try ModellQuelle.benenneUm(code, name: "Halter", gruppe: true, neuerLetzterTeil: "Wandhalter").get()
        XCTAssertEqual(r.stellen, 4)
        XCTAssertFalse(r.code.contains("\"Halter/"))
        XCTAssertTrue(r.code.contains(#"befestigt("Wandhalter/Grundplatte""#))
    }

    func testNameAusDemCodeBleibtBeimAgenten() {
        XCTAssertEqual(
            ModellQuelle.benenneUm(code, name: "Rollen/Rolle 2", gruppe: false, neuerLetzterTeil: "Vorne").fehlerWert,
            .nameNichtGefunden("Rollen/Rolle 2"))
        XCTAssertEqual(
            ModellQuelle.benenneUm(code, name: "Rohr", gruppe: false, neuerLetzterTeil: "A/B").fehlerWert,
            .ungueltigerName("A/B"))
    }

    func testSchreibenErsetztGanz() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("kevcad-mq-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let datei = dir.appendingPathComponent("model.py")
        try "alt\n".write(to: datei, atomically: true, encoding: .utf8)
        try ModellQuelle.schreiben("neu\n", nach: datei)
        XCTAssertEqual(try String(contentsOf: datei, encoding: .utf8), "neu\n")
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: dir.path), ["model.py"])
    }
}

private extension Result {
    var fehlerWert: Failure? {
        if case .failure(let f) = self { return f }
        return nil
    }
}
