import Foundation
import XCTest

@testable import KevCADCore

/// I-8 Datei ans Gerät (PROTOCOL.md): Nachrichten gegen die Testdateien aus `make_datei_fixtures.py`, Holen in Stücken
/// und Wiederverwenden einer schon geholten Fassung.
@MainActor
final class DateiTests: XCTestCase {
    private func json(_ data: Data) throws -> JSONValue { try JSONDecoder().decode(JSONValue.self, from: data) }

    func testNachrichtenGleichDenTestdateien() throws {
        let erwartet = try XCTUnwrap(Fixtures.expected()["datei"])
        XCTAssertEqual(erwartet["faehigkeit"]?.stringValue, DateiAnsGeraet.faehigkeit)
        XCTAssertEqual(erwartet["stueck_vorgabe"]?.intValue, DateiAnsGeraet.stueckVorgabe)
        XCTAssertEqual(erwartet["stueck_max"]?.intValue, DateiAnsGeraet.stueckMax)
        var anfrage = DateiRequestMessage(id: "a-31", pfad: "/Users/kevin/Documents/Kev CAD/Halter/output/Halter.stl",
                                          ab: 0, max: 16)
        anfrage.seq = 31
        XCTAssertEqual(try json(anfrage.encodedHeader()), try json(Fixtures.frame("datei_req.frame").header))
        guard case .datei(let a) = try Fixtures.message("datei_stueck.frame"),
              case .datei(let b) = try Fixtures.message("datei_stueck_ende.frame")
        else { return XCTFail("DATEI nicht erkannt") }
        XCTAssertEqual(a.replyTo, "a-31")
        XCTAssertEqual(a.name, "Halter.stl")
        XCTAssertEqual(a.ab + a.laenge, b.ab)
        XCTAssertEqual(b.ab + b.laenge, b.groesse)
        XCTAssertEqual(String(decoding: a.daten + b.daten, as: UTF8.self), "solid Halter\nendsolid Halter\n")
        XCTAssertEqual(KernelMessage.datei(a).replyTo, "a-31")
        XCTAssertTrue(LiveFaehigkeit.app.allSatisfy { $0 != LiveFaehigkeit.datei }, "nur der Kernel meldet datei-1")
    }

    func testFalscheLaengeWirdAbgelehnt() throws {
        let kopf = #"{"type":"DATEI","reply_to":"a","pfad":"/x/y","name":"y","groesse":4,"ab":0,"laenge":3}"#
        XCTAssertThrowsError(try KernelMessage.decode(Frame(header: Data(kopf.utf8), payload: Data([1, 2]))))
    }

    func testHolenInStueckenUndWiederverwenden() async throws {
        let c = AppController(model: AppModel())
        c.handle([.connected])
        let inhalt = Data((0..<10_000).map { UInt8($0 % 251) })
        let pfad = "/Users/kevin/Documents/Kev CAD/Test-\(UUID().uuidString)/output/Halter.stl"
        var anfragen = 0
        var stand = 1_793_480_977.0
        c.sendeBeobachter = { [weak c] rahmen in
            guard let kopf = try? JSONDecoder().decode(JSONValue.self, from: rahmen.header),
                  kopf["type"]?.stringValue == "DATEI_REQ", let id = kopf["id"]?.stringValue,
                  let ab = kopf["ab"]?.intValue
            else { return }
            anfragen += 1
            let stueck = inhalt.subdata(in: ab..<min(ab + 4096, inhalt.count))
            let antwort = DateiStueckMessage(replyTo: id, pfad: pfad, name: "Halter.stl", groesse: inhalt.count,
                                             ab: ab, laenge: stueck.count, geaendert: stand, daten: stueck)
            DispatchQueue.main.async { c?.handle([.message(.datei(antwort))]) }
        }
        var anteile: [Double] = []
        let url = try await c.dateiHolen(pfad, fortschritt: { anteile.append($0) })
        defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        XCTAssertEqual(url.lastPathComponent, "Halter.stl")
        XCTAssertEqual(try Data(contentsOf: url), inhalt)
        XCTAssertEqual(anfragen, 3)
        XCTAssertEqual(anteile.last, 1)
        // Unverändert am Mac: nur das erste Stück zur Kontrolle, dieselbe Datei
        let wieder = try await c.dateiHolen(pfad, fortschritt: nil)
        XCTAssertEqual(wieder, url)
        XCTAssertEqual(anfragen, 4)
        // Am Mac geändert: wieder ganz
        stand += 10
        _ = try await c.dateiHolen(pfad, fortschritt: nil)
        XCTAssertEqual(anfragen, 7)
    }

    func testFehlerDesKernelsKommtAn() async throws {
        let c = AppController(model: AppModel())
        c.handle([.connected])
        c.sendeBeobachter = { [weak c] rahmen in
            guard let kopf = try? JSONDecoder().decode(JSONValue.self, from: rahmen.header),
                  kopf["type"]?.stringValue == "DATEI_REQ", let id = kopf["id"]?.stringValue else { return }
            let fehler = #"{"type":"ERROR","reply_to":"\#(id)","message":"Die Datei gibt es nicht: x.stl"}"#
            DispatchQueue.main.async {
                c?.handle([.message(try! KernelMessage.decode(Frame(header: Data(fehler.utf8))))])
            }
        }
        do {
            _ = try await c.dateiHolen("/Users/kevin/x.stl", fortschritt: nil)
            XCTFail("Fehler erwartet")
        } catch {
            XCTAssertTrue("\(error)".contains("gibt es nicht"))
        }
    }

    func testLokaleDateiBleibtWoSieIst() async throws {
        let c = AppController(model: AppModel())
        let datei = FileManager.default.temporaryDirectory.appendingPathComponent("kevcad-datei-\(UUID().uuidString).txt")
        try Data("hier".utf8).write(to: datei)
        defer { try? FileManager.default.removeItem(at: datei) }
        let url = try await c.dateiFuerGeraet(datei)
        XCTAssertEqual(url, datei)
        XCTAssertTrue(c.kannDateienHolen, "ohne Netzverbindung (Mac) immer")
    }
}
