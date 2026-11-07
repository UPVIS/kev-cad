import Foundation
@testable import KevCADCore
import XCTest

/// Projektablage (PLAN-IPAD.md, I-7): Schalter, Pfade zwischen iPad und Mac, Projektliste mit Konfliktkopien.
final class ProjektablageTests: XCTestCase {
    private var ordner: URL!

    override func setUpWithError() throws {
        ordner = FileManager.default.temporaryDirectory.appendingPathComponent("ablage-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: ordner, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: ordner)
    }

    func testOrdnerNachVorrang() {
        let vorgabe = URL(fileURLWithPath: "/tmp/vorgabe", isDirectory: true)
        XCTAssertEqual(Projektablage.ordner(umgebung: [:], schalter: .init(), vorgabe: vorgabe), vorgabe)
        XCTAssertEqual(Projektablage.ordner(umgebung: [:], schalter: .init(ort: .icloud), vorgabe: vorgabe),
                       Projektablage.iCloudOrdner)
        XCTAssertEqual(Projektablage.ordner(umgebung: [:], schalter: .init(ordner: "/tmp/eigen"), vorgabe: vorgabe).path,
                       "/tmp/eigen")
        XCTAssertEqual(Projektablage.ordner(umgebung: ["KEVCAD_PROJECTS_DIR": "/tmp/test"], schalter: .init(ort: .icloud),
                                            vorgabe: vorgabe).path, "/tmp/test")
    }

    func testSchalterSchreibenUndLesen() throws {
        XCTAssertEqual(Projektablage.schalterLesen(in: ordner), .init())
        try Projektablage.schalterSchreiben(.init(ort: .icloud), in: ordner)
        XCTAssertEqual(Projektablage.schalterLesen(in: ordner).ort, .icloud)
        // dieselbe Datei liest der Kernel (ablage.py): {"ort": "icloud"}
        let text = try String(contentsOf: ordner.appendingPathComponent(Projektablage.schalterDatei), encoding: .utf8)
        XCTAssertTrue(text.contains("\"ort\" : \"icloud\""), text)
        try Projektablage.schalterSchreiben(.init(ort: .lokal), in: ordner)
        XCTAssertFalse(FileManager.default.fileExists(atPath: ordner.appendingPathComponent(Projektablage.schalterDatei).path))
    }

    func testKernelPfadVomIPad() {
        let pad = URL(fileURLWithPath: "/private/var/mobile/Library/Mobile Documents/com~apple~CloudDocs/Kev CAD/Wandhalter")
        XCTAssertTrue(Projektablage.inICloud(pad))
        XCTAssertEqual(Projektablage.kernelPfad(pad), "~/Library/Mobile Documents/com~apple~CloudDocs/Kev CAD/Wandhalter")
        let mac = Projektablage.iCloudOrdner.appendingPathComponent("Wandhalter")
        XCTAssertEqual(Projektablage.kernelPfad(mac), "~/Library/Mobile Documents/com~apple~CloudDocs/Kev CAD/Wandhalter")
        let lokal = URL(fileURLWithPath: "/Users/k/Documents/Kev CAD/Wandhalter")
        XCTAssertFalse(Projektablage.inICloud(lokal))
        XCTAssertEqual(Projektablage.kernelPfad(lokal), lokal.path)
    }

    func testNeuesProjektVomIPadOhneICloud() {
        let lokal = URL(fileURLWithPath: "/private/var/mobile/Containers/Data/Application/X/Documents/Kev CAD")
        XCTAssertEqual(Projektablage.kernelPfad(lokal.appendingPathComponent("Strebe"), lokalerOrdner: lokal), "Strebe")
        let anders = URL(fileURLWithPath: "/Users/k/Documents/Kev CAD/Strebe")
        XCTAssertEqual(Projektablage.kernelPfad(anders, lokalerOrdner: lokal), anders.path)
    }

    func testPfadVomMacAufDemIPad() {
        let padOrdner = URL(fileURLWithPath: "/private/var/mobile/Library/Mobile Documents/com~apple~CloudDocs/Kev CAD")
        let wurzel = Projektablage.iCloudWurzel(von: padOrdner)
        XCTAssertEqual(wurzel?.path, "/private/var/mobile/Library/Mobile Documents")
        let mac = URL(fileURLWithPath: "/Users/k/Library/Mobile Documents/com~apple~CloudDocs/Kev CAD/Halter")
        XCTAssertEqual(Projektablage.hierAbgelegt(mac, wurzel: wurzel)?.path, padOrdner.path + "/Halter")
        XCTAssertNil(Projektablage.hierAbgelegt(URL(fileURLWithPath: "/Users/k/Documents/Kev CAD/Halter"), wurzel: wurzel))
        XCTAssertNil(Projektablage.hierAbgelegt(mac, wurzel: nil))
    }

    func testKonfliktKopien() {
        XCTAssertEqual(ProjektListe.konfliktKopien(["model.py", "model 2.py", "kevcad.json", "kevcad 3.json"]),
                       ["kevcad 3.json", "model 2.py"])
        // „Teil 2.py“ ohne „Teil.py“ ist ein gewöhnlicher Name, „model 1.py“ keine Kopie
        XCTAssertEqual(ProjektListe.konfliktKopien(["model.py", "Teil 2.py", "model 1.py", "output 2"]), [])
        XCTAssertEqual(ProjektListe.konfliktKopien(["output", "output 2"]), ["output 2"])
    }

    func testProjektListe() throws {
        let fm = FileManager.default
        func projekt(_ name: String, modell: Bool = true, platzhalter: Bool = false, alter: TimeInterval) throws {
            let p = ordner.appendingPathComponent(name, isDirectory: true)
            try fm.createDirectory(at: p, withIntermediateDirectories: true)
            let datei = p.appendingPathComponent(modell ? "model.py" : (platzhalter ? ".model.py.icloud" : "notiz.txt"))
            try Data("x = 1\n".utf8).write(to: datei)
            try fm.setAttributes([.modificationDate: Date(timeIntervalSinceNow: -alter)], ofItemAtPath: datei.path)
        }
        try projekt("Alt", alter: 3600)
        try projekt("Neu", alter: 10)
        try projekt("Kein Projekt", modell: false, alter: 5)
        try projekt("Nur in der iCloud", modell: false, platzhalter: true, alter: 20)
        try Data().write(to: ordner.appendingPathComponent("Neu/model 2.py"))
        let liste = ProjektListe.lesen(ordner)
        XCTAssertEqual(liste.map(\.name), ["Neu", "Nur in der iCloud", "Alt"])
        XCTAssertEqual(liste[0].konflikte, ["model 2.py"])
        XCTAssertTrue(liste[0].geladen)
        XCTAssertFalse(liste[1].geladen)
        XCTAssertNil(ProjectLocator.check(ordner.appendingPathComponent("Nur in der iCloud")))  // Platzhalter reicht
    }
}
