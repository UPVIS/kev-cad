import Foundation
import Network
import XCTest

@testable import KevCADCore

/// I-2b (PLAN-IPAD.md): Kopplungscode, Kopplungen am Mac und der Weg iPad → Eingang der Mac-App → Kernel über TLS.
@MainActor
final class NetzTests: XCTestCase {
    func testKopplungsCodeHinUndZurueck() throws {
        let code = KopplungsCode(mac: "mac-1", name: "MacBook Pro von Kevin", port: 47825,
                                 wege: ["192.168.1.20", "100.101.102.103", "kevins-mbp.local"], kennung: "kc-0a1b2c3d4e5f",
                                 schluessel: NetzKanal.neuerSchluessel(), bis: Date(timeIntervalSince1970: 1_800_000_000))
        let text = try code.text()
        XCTAssertTrue(text.hasPrefix("kevcad://koppeln/"))
        let teil = text.dropFirst(KopplungsCode.schema.count)
        XCTAssertFalse(teil.contains("+") || teil.contains("/") || teil.contains("="), "base64url erwartet")
        XCTAssertEqual(KopplungsCode.lesen(text), code)
        XCTAssertEqual(KopplungsCode.lesen("  " + text + "\n"), code, "Leerzeichen vom Scanner stören nicht")
        XCTAssertNil(KopplungsCode.lesen("https://example.com"))
        XCTAssertNil(KopplungsCode.lesen("kevcad://koppeln/kaputt"))
        XCTAssertEqual(NetzKanal.fingerabdruck(code.schluessel).count, 9)
    }

    #if os(macOS)
    func testKopplungenAmMac() throws {
        let ordner = FileManager.default.temporaryDirectory.appendingPathComponent("kc-kopplung-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: ordner) }
        let datei = ordner.appendingPathComponent("kopplungen.json")
        let jetzt = Date()
        let k = MacKopplungen(datei: datei)
        let code = try k.neu(mac: "mac-1", macName: "Mac", port: 47825, wege: ["127.0.0.1"], dauer: 600, jetzt: jetzt)
        XCTAssertEqual(k.schluessel(jetzt: jetzt).map(\.kennung), [code.kennung], "offener Code kommt herein")
        XCTAssertEqual(k.schluessel(jetzt: jetzt.addingTimeInterval(601)).count, 0, "abgelaufener Code nicht mehr")
        let rechte = try FileManager.default.attributesOfItem(atPath: datei.path)[.posixPermissions] as? NSNumber
        XCTAssertEqual(rechte?.intValue, 0o600)

        k.verbunden(kennung: code.kennung, name: "iPad von Kevin", jetzt: jetzt)
        let neu = MacKopplungen(datei: datei)  // von der Platte
        XCTAssertEqual(neu.geraete.map(\.name), ["iPad von Kevin"])
        XCTAssertTrue(neu.geraete[0].bestaetigt)
        XCTAssertEqual(neu.schluessel(jetzt: jetzt.addingTimeInterval(86_400 * 30)).first?.schluessel, code.schluessel,
                       "bestätigte Geräte bleiben gekoppelt")

        let zweiter = try neu.neu(mac: "mac-1", macName: "Mac", port: 47825, wege: [], dauer: 60, jetzt: jetzt)
        neu.aufraeumen(jetzt: jetzt.addingTimeInterval(61))
        XCTAssertFalse(neu.geraete.contains { $0.kennung == zweiter.kennung }, "nie benutzter Code wird aufgeräumt")
        neu.entfernen(code.kennung)
        XCTAssertTrue(MacKopplungen(datei: datei).geraete.isEmpty)
    }

    /// Ganzer Weg wie mit dem iPad: KernelConnection übers Netz (TLS mit Kopplungsschlüssel) → IPadEingang → Unix-Socket
    /// des „Kernels“. Der Testdatenstrom kommt vollständig und in Reihenfolge an, HELLO_APP geht zurück, und der Eingang
    /// erkennt das Gerät an seiner Kopplung.
    func testIPadUeberDenEingangZumKernel() throws {
        let kernel = TestSocketServer()
        try kernel.listen()
        defer { kernel.stop() }
        let schluessel = NetzKanal.neuerSchluessel()
        let eingang = IPadEingang(port: 0, kernelSocket: kernel.path, dienstName: "", macKennung: "mac-test")
        defer { eingang.stoppen() }
        var port: UInt16?
        let bereit = expectation(description: "Eingang lauscht")
        eingang.onBereit = { p in
            if let p, port == nil {
                port = p
                bereit.fulfill()
            }
        }
        var gemeldet: (String, String?)?
        let geraet = expectation(description: "Gerät erkannt")
        eingang.onGeraet = { kennung, name in
            gemeldet = (kennung, name)
            geraet.fulfill()
        }
        eingang.starten(schluessel: [("kc-test", schluessel)])
        wait(for: [bereit], timeout: 10)

        let stream = try Fixtures.data("stream.bin")
        DispatchQueue.global().async { kernel.acceptAndSend(stream) }

        let conn = KernelConnection()
        let total = try XCTUnwrap(Fixtures.expected()["frames"]?.arrayValue).count
        let verbunden = expectation(description: "verbunden")
        let alle = expectation(description: "\(total) Nachrichten")
        var arten: [String] = []
        var fertig = false
        conn.onEvents = { batch in
            for e in batch {
                switch e {
                case .connected: verbunden.fulfill()
                case .message(let m): arten.append(m.typeName)
                case .part: arten.append("PART_UPSERT")
                case .invalid(let t, let r): XCTFail("ungültig \(t): \(r)")
                default: break
                }
                if !fertig, arten.count == total {
                    fertig = true
                    alle.fulfill()
                }
            }
        }
        let ziel = NetzZiel(wege: [.hostPort(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: try XCTUnwrap(port))!)],
                            schluessel: schluessel, kennung: "kc-test")
        conn.open(netz: ziel)
        wait(for: [verbunden, alle], timeout: 15)
        let erwartet = try XCTUnwrap(Fixtures.expected()["frames"]?.arrayValue).compactMap { $0["type"]?.stringValue }
        XCTAssertEqual(arten, erwartet)
        XCTAssertTrue(conn.istNetz)

        var hello = HelloAppMessage(appVersion: "test", bundleID: "de.upvis.kevcad.ipad.test",
                                    geraet: ["id": "pad-1", "art": "ipad", "name": "Test-iPad", "kopplung": "kc-test"])
        hello.seq = 1
        conn.send(try hello.frame().encoded)
        let angekommen = kernel.readFrames(count: 1, timeout: 5)
        XCTAssertEqual(angekommen.count, 1)
        let kopf = try XCTUnwrap(JSONSerialization.jsonObject(with: angekommen[0].header) as? [String: Any])
        XCTAssertEqual(kopf["type"] as? String, "HELLO_APP")
        XCTAssertEqual((kopf["geraet"] as? [String: String])?["art"], "ipad")
        wait(for: [geraet], timeout: 5)
        XCTAssertEqual(gemeldet?.0, "kc-test")
        XCTAssertEqual(gemeldet?.1, "Test-iPad")
        XCTAssertEqual(eingang.verbindungen, 1)
        conn.close()
    }

    /// Ohne den richtigen Schlüssel kommt niemand über den Handschlag: keine Verbindung, nichts am Kernel.
    func testFremderSchluesselKommtNichtHerein() throws {
        let kernel = TestSocketServer()
        try kernel.listen()
        defer { kernel.stop() }
        let eingang = IPadEingang(port: 0, kernelSocket: kernel.path, dienstName: "", macKennung: "mac-test")
        defer { eingang.stoppen() }
        var port: UInt16?
        let bereit = expectation(description: "Eingang lauscht")
        eingang.onBereit = { p in
            if let p, port == nil {
                port = p
                bereit.fulfill()
            }
        }
        eingang.starten(schluessel: [("kc-echt", NetzKanal.neuerSchluessel())])
        wait(for: [bereit], timeout: 10)

        let conn = KernelConnection()
        let verbunden = expectation(description: "darf nicht verbinden")
        verbunden.isInverted = true
        conn.onEvents = { batch in
            for e in batch { if case .connected = e { verbunden.fulfill() } }
        }
        let falsch = NetzZiel(wege: [.hostPort(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: try XCTUnwrap(port))!)],
                              schluessel: NetzKanal.neuerSchluessel(), kennung: "kc-echt")
        conn.open(netz: falsch)
        wait(for: [verbunden], timeout: 3)
        conn.close()
        XCTAssertEqual(kernel.readFrames(count: 1, timeout: 0.2).count, 0)
    }

    /// Ohne Kopplung bleibt kein Port offen.
    func testOhneKopplungKeinPort() {
        let eingang = IPadEingang(port: 0, kernelSocket: "/tmp/gibt-es-nicht.sock", dienstName: "", macKennung: "m")
        defer { eingang.stoppen() }
        let zu = expectation(description: "zu")
        eingang.onBereit = { p in if p == nil { zu.fulfill() } }
        eingang.starten(schluessel: [])
        wait(for: [zu], timeout: 5)
    }
    #endif
}
