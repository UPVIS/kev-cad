import Darwin
import Foundation
import Security
import XCTest

@testable import KevCADCore

/// Freigabe vom iPhone (MIRROR.md, Version 1.1): Anfrage ohne Miete, CMD `freigabe` mit Nonce, Ablauf und
/// Wiederverwendung, Ausführung über die Freigabe des Projektfensters, Entscheidungen am Mac, Prüfung der Gegenstelle.
@MainActor
final class MirrorFreigabeTests: XCTestCase {
    var dir: String!
    var c: AppController!
    var cmdNr = 0

    override func setUp() async throws {
        dir = FileManager.default.temporaryDirectory.path.count > 60
            ? "/tmp/kcf-\(UUID().uuidString.prefix(8))" : NSTemporaryDirectory() + "kcf-\(UUID().uuidString.prefix(8))"
        c = AppController(model: AppModel())
        c.handle([.connected])
        c.handle([.message(try Fixtures.message("hello.frame"))])
    }

    override func tearDown() async throws {
        c.mirror?.stop()
        try? FileManager.default.removeItem(atPath: dir)
    }

    var socketPath: String { dir + "/m.sock" }

    func waitUntil(_ timeout: TimeInterval = 5, _ cond: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if cond() { return true }
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.005))
        }
        return cond()
    }

    /// Spiegel starten; `erlaubt`: Gegenstelle gilt als VoiceBridge (sonst die echte Prüfung, die den Testprozess
    /// abweist).
    func client(erlaubt: Bool = true, laufzeit: TimeInterval? = nil) throws -> TestMirrorClient {
        if c.mirror == nil {
            c.startMirror(path: socketPath)
            let m = try XCTUnwrap(c.mirror)
            XCTAssertFalse(m.freigabeTestmodus, "swift test ist keine Testvariante")
            if erlaubt { m.server.peerVerifier = { _ in .init(erlaubt: true, grund: "Test", pid: 1) } }
            if let laufzeit { m.freigabe.laufzeit = laufzeit }
            m.freigabe.bestaetigungsFrist = 5
        }
        let k = try TestMirrorClient(path: socketPath)
        try k.send(MirrorHello.client("test"))
        XCTAssertTrue(waitUntil { k.receiver.hello != nil })
        return k
    }

    // MARK: Kernel spielen

    private let rohr: JSONValue = [
        "id": "rohr-alfer-16x1", "art": "rohr", "name": "ALFER-Rundrohr 16 × 1", "masse": ["d": 16, "s": 1],
        "material": "aluminium-6060", "preis": ["je_m": 4.2], "bezugsquelle": ["url": "https://www.alfer.com/",
        "name": "ALFER"], "status": "vorgeschlagen", "ebene": "eigen"]
    private let roller: JSONValue = [
        "id": "alutec-05200", "art": "zukaufteil", "name": "ALUTEC Transportroller 05200", "hersteller": "ALUTEC",
        "url": "http://unsicher.example/p", "masse": ["l": 610, "b": 410, "h": 128], "status": "vorgeschlagen",
        "ebene": "projekt"]

    /// CATALOG als Antwort auf `replyTo`; `frei` sind freigegeben, `weg` fehlen.
    func catalog(_ replyTo: String, frei: Set<String> = [], weg: Set<String> = []) throws -> IncomingEvent {
        let items: [JSONValue] = [rohr, roller].compactMap { e in
            guard case .object(var o) = e, let id = o["id"]?.stringValue, !weg.contains(id) else { return nil }
            if frei.contains(id) { o["status"] = "frei" }
            return .object(o)
        }
        var mats: [JSONValue] = [
            ["id": "aluminium-6060", "name": "Aluminium 6060", "gruppe": "Aluminium", "dichte": 2.7, "farbe": "#C0C4C8"]
        ]
        if !weg.contains("petg-cf") {
            mats.append(["id": "petg-cf", "name": "PETG-CF", "gruppe": "Kunststoff", "dichte": 1.3, "farbe": "#222222",
                         "druckbar": true, "preis_je_kg": 29.0, "status": frei.contains("petg-cf") ? "frei" : "vorgeschlagen",
                         "ebene": "eigen"])
        }
        let head: JSONValue = ["type": "CATALOG", "reply_to": .string(replyTo), "materials": .array(mats),
                               "items": .array(items)]
        return .message(try KernelMessage.decode(Frame(header: try JSONEncoder().encode(head))))
    }

    func ack(_ replyTo: String, ok: Bool = true, message: String? = nil) throws -> IncomingEvent {
        let head: JSONValue = ["type": "ACK", "reply_to": .string(replyTo), "ok": .bool(ok),
                               "message": message.map(JSONValue.string) ?? .null]
        return .message(try KernelMessage.decode(Frame(header: try JSONEncoder().encode(head))))
    }

    /// Wartet auf eine offene Anfrage des Typs und beantwortet alle dieses Typs.
    func antworte(_ type: String, _ make: (String) throws -> IncomingEvent) throws {
        XCTAssertTrue(waitUntil { self.c.pendingRequestTypes.values.contains(type) }, "\(type) erwartet")
        for (id, t) in c.pendingRequestTypes where t == type { c.handle([try make(id)]) }
    }

    func anfrage(_ nr: Int = 2, ids: [(String, String)] = [("rohr-alfer-16x1", "teil"), ("petg-cf", "material")])
        throws
    {
        let eintraege = ids.map { #"{"id":"\#($0.0)","kind":"\#($0.1)"}"# }.joined(separator: ",")
        let json = #"{"type":"FREIGABE_ANFRAGE","id":"k-\#(nr)","anfrage":"F-000\#(nr)","grund":"Für den Wagen","eintraege":[\#(eintraege)]}"#
        c.handle([.message(try KernelMessage.decode(Frame(header: Data(json.utf8))))])
    }

    func befehl(_ k: TestMirrorClient, _ f: MirrorFreigabeMessage, _ id: String, _ e: MirrorFreigabeEntscheidung,
                nonce: String? = nil) throws -> String
    {
        cmdNr += 1
        let cid = "i-\(cmdNr)"
        try k.send(MirrorCommand.freigabe(id: cid, anfrageID: f.anfrageID, nonce: nonce ?? f.nonce, eintrag: id,
                                          entscheidung: e))
        return cid
    }

    func antwort(_ k: TestMirrorClient, _ cid: String) -> MirrorCommandResult? {
        guard waitUntil(5, { k.headers("CMD_RES").contains { $0["reply_to"]?.stringValue == cid } }) else { return nil }
        let h = k.headers("CMD_RES").first { $0["reply_to"]?.stringValue == cid }!
        return try? h.decoded(MirrorCommandResult.self)
    }

    func ende(_ k: TestMirrorClient, id: String?) -> MirrorFreigabeEndeMessage? {
        guard waitUntil(5, { k.headers("FREIGABE_ENDE").contains { $0["id"]?.stringValue == id } }) else { return nil }
        return try? k.headers("FREIGABE_ENDE").first { $0["id"]?.stringValue == id }!
            .decoded(MirrorFreigabeEndeMessage.self)
    }

    // MARK: Tests

    func testFreigebenUndAblehnenVomIPhone() throws {
        let k = try client()
        try anfrage()
        try antworte("CATALOG_REQ") { try catalog($0) }
        XCTAssertTrue(waitUntil { !k.receiver.freigaben.isEmpty }, "FREIGABE ohne WATCH")
        XCTAssertTrue(k.headers("STATE").isEmpty)
        let f = try XCTUnwrap(k.receiver.freigaben.first)
        XCTAssertTrue(f.anfrageID.hasPrefix("F-0002-"))
        XCTAssertEqual(f.nonce.count, 32)
        XCTAssertTrue(f.nonce.allSatisfy(\.isHexDigit))
        let ablauf = try XCTUnwrap(f.ablaufDatum)
        XCTAssertEqual(ablauf.timeIntervalSinceNow, 24 * 3600, accuracy: 60)
        XCTAssertEqual(f.eintraege.map(\.id), ["rohr-alfer-16x1", "petg-cf"])
        XCTAssertEqual(f.eintraege[0].kurz, "d 16 · s 1 mm · 4,20 €/m · ALFER")
        XCTAssertEqual(f.eintraege[0].link, "https://www.alfer.com/")
        XCTAssertEqual(f.eintraege[0].art, "rohr")
        XCTAssertEqual(f.eintraege[0].grund, "Für den Wagen")
        XCTAssertEqual(f.eintraege[1].kurz, "1,30 g/cm³ · 29,00 €/kg")
        XCTAssertNil(f.eintraege[1].link)

        // Falsche Nonce, falscher Eintrag
        var cid = try befehl(k, f, "rohr-alfer-16x1", .frei, nonce: String(repeating: "0", count: 32))
        XCTAssertEqual(antwort(k, cid)?.freigabeStatus, .ungueltig)
        cid = try befehl(k, f, "alutec-05200", .frei)
        XCTAssertEqual(antwort(k, cid)?.freigabeStatus, .ungueltig, "gehört nicht zur Anfrage")

        // Freigeben: frischer Katalog, dann derselbe Weg wie Kevins Klick (Warteschlange, CATALOG_SAVE, Bestätigung)
        cid = try befehl(k, f, "rohr-alfer-16x1", .frei)
        try antworte("CATALOG_REQ") { try catalog($0) }
        XCTAssertTrue(waitUntil { self.c.model.freigabe.laeuft == "rohr-alfer-16x1" }, "über FreigabeActions")
        // Wiederholung während der Ausführung
        let doppelt = try befehl(k, f, "rohr-alfer-16x1", .frei)
        XCTAssertEqual(antwort(k, doppelt)?.freigabeStatus, .verbraucht)
        try antworte("CATALOG_SAVE") { try ack($0) }
        try antworte("CATALOG_REQ") { try catalog($0, frei: ["rohr-alfer-16x1"]) }
        let ok = try XCTUnwrap(antwort(k, cid))
        XCTAssertTrue(ok.ok)
        XCTAssertEqual(ok.freigabeStatus, .frei)
        XCTAssertEqual(c.model.freigabe.freigegeben, ["rohr-alfer-16x1"], "der Dialog am Mac zeigt es")
        let e1 = try XCTUnwrap(ende(k, id: "rohr-alfer-16x1"))
        XCTAssertEqual(e1.grund, .iphone)
        XCTAssertEqual(e1.ergebnis, .frei)
        XCTAssertEqual(k.receiver.freigaben.first?.eintraege.map(\.id), ["petg-cf"])
        // Wiederverwendet: derselbe Eintrag mit derselben Nonce
        cid = try befehl(k, f, "rohr-alfer-16x1", .frei)
        XCTAssertEqual(antwort(k, cid)?.freigabeStatus, .verbraucht)

        // Ablehnen: CATALOG_DELETE und Bestätigung im ungefilterten Katalog
        cid = try befehl(k, f, "petg-cf", .abgelehnt)
        try antworte("CATALOG_REQ") { try catalog($0, frei: ["rohr-alfer-16x1"]) }
        try antworte("CATALOG_DELETE") { try ack($0) }
        try antworte("CATALOG_REQ") { try catalog($0, frei: ["rohr-alfer-16x1"], weg: ["petg-cf"]) }
        XCTAssertEqual(antwort(k, cid)?.freigabeStatus, .abgelehnt)
        XCTAssertEqual(ende(k, id: "petg-cf")?.ergebnis, .abgelehnt)
        let ganz = try XCTUnwrap(ende(k, id: nil))
        XCTAssertEqual(ganz.grund, .iphone)
        XCTAssertTrue(k.receiver.freigaben.isEmpty)
        // Danach ist die Anfrage erledigt
        cid = try befehl(k, f, "petg-cf", .frei)
        XCTAssertEqual(antwort(k, cid)?.freigabeStatus, .beendet)
    }

    func testKatalogfehlerGehtZurueckUndDarfWiederholtWerden() throws {
        let k = try client()
        try anfrage()
        try antworte("CATALOG_REQ") { try catalog($0) }
        XCTAssertTrue(waitUntil { !k.receiver.freigaben.isEmpty })
        let f = try XCTUnwrap(k.receiver.freigaben.first)
        var cid = try befehl(k, f, "rohr-alfer-16x1", .frei)
        try antworte("CATALOG_REQ") { try catalog($0) }
        try antworte("CATALOG_SAVE") { try ack($0, ok: false, message: "preis.stand fehlt") }
        let r = try XCTUnwrap(antwort(k, cid))
        XCTAssertEqual(r.freigabeStatus, .katalogfehler)
        XCTAssertTrue(r.fehler?.contains("preis.stand fehlt") == true, r.fehler ?? "")
        XCTAssertNotNil(c.model.freigabe.fehler, "der Fehler steht auch im Dialog")
        // Nach einem Katalogfehler darf das iPhone es noch einmal versuchen
        cid = try befehl(k, f, "rohr-alfer-16x1", .frei)
        try antworte("CATALOG_REQ") { try catalog($0) }
        try antworte("CATALOG_SAVE") { try ack($0) }
        try antworte("CATALOG_REQ") { try catalog($0, frei: ["rohr-alfer-16x1"]) }
        XCTAssertEqual(antwort(k, cid)?.freigabeStatus, .frei)
        // Eintrag inzwischen weg bzw. schon frei
        try anfrage(3, ids: [("alutec-05200", "teil"), ("petg-cf", "material")])
        try antworte("CATALOG_REQ") { try catalog($0, frei: ["rohr-alfer-16x1"]) }
        XCTAssertTrue(waitUntil { k.receiver.freigaben.first?.anfrageID.hasPrefix("F-0003") == true })
        let g = try XCTUnwrap(k.receiver.freigaben.first)
        cid = try befehl(k, g, "alutec-05200", .frei)
        try antworte("CATALOG_REQ") { try catalog($0, frei: ["rohr-alfer-16x1"], weg: ["alutec-05200"]) }
        XCTAssertEqual(antwort(k, cid)?.freigabeStatus, .fehlt)
        cid = try befehl(k, g, "petg-cf", .frei)
        try antworte("CATALOG_REQ") { try catalog($0, frei: ["rohr-alfer-16x1", "petg-cf"]) }
        XCTAssertEqual(antwort(k, cid)?.freigabeStatus, .schonFrei)
        XCTAssertEqual(ende(k, id: "petg-cf")?.grund, .mac)
    }

    func testAblaufNachLaufzeit() throws {
        let k = try client(laufzeit: 0.4)
        try anfrage()
        try antworte("CATALOG_REQ") { try catalog($0) }
        XCTAssertTrue(waitUntil { !k.receiver.freigaben.isEmpty })
        let f = try XCTUnwrap(k.receiver.freigaben.first)
        let e = try XCTUnwrap(ende(k, id: nil))
        XCTAssertEqual(e.grund, .abgelaufen)
        let cid = try befehl(k, f, "rohr-alfer-16x1", .frei)
        XCTAssertEqual(antwort(k, cid)?.freigabeStatus, .abgelaufen)
        XCTAssertNil(c.model.freigabe.laeuft, "nichts ausgeführt")
    }

    func testMacEntscheidetSchliesstUndErsetzt() throws {
        let k = try client()
        try anfrage()
        try antworte("CATALOG_REQ") { try catalog($0) }
        XCTAssertTrue(waitUntil { !k.receiver.freigaben.isEmpty })
        let f = try XCTUnwrap(k.receiver.freigaben.first)
        // Eine später verbundene Gegenstelle bekommt die offene Anfrage nach ihrem HELLO
        let spaet = try client()
        XCTAssertTrue(waitUntil { spaet.receiver.freigaben.first?.nonce == f.nonce })
        // Kevins Klick am Mac
        c.freigeben([FreigabeEintrag(id: "rohr-alfer-16x1", kind: "teil")])
        try antworte("CATALOG_SAVE") { try ack($0) }
        try antworte("CATALOG_REQ") { try catalog($0, frei: ["rohr-alfer-16x1"]) }
        let e = try XCTUnwrap(ende(k, id: "rohr-alfer-16x1"))
        XCTAssertEqual(e.grund, .mac)
        XCTAssertEqual(spaet.receiver.freigaben.first?.eintraege.map(\.id), ["petg-cf"])
        var cid = try befehl(k, f, "rohr-alfer-16x1", .frei)
        XCTAssertEqual(antwort(k, cid)?.freigabeStatus, .verbraucht)
        // Neue Anfrage ersetzt die offene
        try anfrage(3, ids: [("petg-cf", "material")])
        XCTAssertEqual(ende(k, id: nil)?.grund, .zurueckgezogen)
        try antworte("CATALOG_REQ") { try catalog($0, frei: ["rohr-alfer-16x1"]) }
        XCTAssertTrue(waitUntil { k.receiver.freigaben.first?.anfrageID.hasPrefix("F-0003") == true })
        cid = try befehl(k, f, "petg-cf", .frei)
        XCTAssertEqual(antwort(k, cid)?.freigabeStatus, .beendet, "alte Anfrage")
        // Dialog am Mac geschlossen
        let g = try XCTUnwrap(k.receiver.freigaben.first)
        c.freigabeSchliessen()
        XCTAssertTrue(waitUntil { k.receiver.freigaben.isEmpty })
        XCTAssertEqual(
            k.headers("FREIGABE_ENDE").last.flatMap { try? $0.decoded(MirrorFreigabeEndeMessage.self) }?.grund, .mac)
        cid = try befehl(k, g, "petg-cf", .frei)
        XCTAssertEqual(antwort(k, cid)?.freigabeStatus, .beendet)
    }

    func testFremderProzessWirdAbgelehnt() throws {
        let k = try client(erlaubt: false)  // echte Prüfung: der Testprozess ist nicht VoiceBridge
        try anfrage()
        try antworte("CATALOG_REQ") { try catalog($0) }
        _ = waitUntil(0.5) { false }
        XCTAssertTrue(k.headers("FREIGABE").isEmpty, "keine Nonce an fremde Gegenstellen")
        let f = MirrorFreigabeMessage(epoche: "", anfrageID: "F-0002-00000000", nonce: String(repeating: "a", count: 32),
                                      ablauf: "", eintraege: [])
        let cid = try befehl(k, f, "rohr-alfer-16x1", .frei)
        let r = try XCTUnwrap(antwort(k, cid))
        XCTAssertFalse(r.ok)
        XCTAssertEqual(r.freigabeStatus, .nichtErlaubt)
        XCTAssertTrue(r.fehler?.contains("VoiceBridge") == true, r.fehler ?? "")
        XCTAssertNil(c.model.freigabe.laeuft)
    }

    func testTestmodusNurInTestvarianten() {
        let v = [MirrorGegenstelle.testmodusVariable: "1"]
        XCTAssertFalse(MirrorGegenstelle.testmodus(bundleID: "de.upvis.kevcad", environment: v))
        XCTAssertTrue(MirrorGegenstelle.testmodus(bundleID: "de.upvis.kevcad.test.fi", environment: v))
        XCTAssertFalse(MirrorGegenstelle.testmodus(bundleID: "de.upvis.kevcad.test.fi", environment: [:]))
        XCTAssertTrue(MirrorGegenstelle.standardPruefer(testmodus: true)(nil).erlaubt)
        XCTAssertFalse(MirrorGegenstelle.standardPruefer(testmodus: false)(nil).erlaubt)
    }

    func testEigenerProzessIstNichtVoiceBridge() throws {
        var token = audit_token_t()
        var count = mach_msg_type_number_t(MemoryLayout<audit_token_t>.size / MemoryLayout<natural_t>.size)
        let kr = withUnsafeMutablePointer(to: &token) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(TASK_AUDIT_TOKEN), $0, &count)
            }
        }
        XCTAssertEqual(kr, KERN_SUCCESS)
        XCTAssertEqual(MirrorGegenstelle.pid(token), getpid())
        let u = MirrorGegenstelle.pruefe(token)
        XCTAssertFalse(u.erlaubt)
        XCTAssertTrue(u.grund.contains("Signatur"), u.grund)
        XCTAssertEqual(u.pid, getpid())
        XCTAssertNotNil(MirrorGegenstelle.argumente(pid: getpid()))
    }

    func testArgumenteAusProcargs() {
        var data = [UInt8]()
        var argc = Int32(3).littleEndian
        withUnsafeBytes(of: &argc) { data += $0 }
        data += Array("/Applications/VoiceBridge.app/Contents/MacOS/VoiceBridge".utf8) + [0, 0, 0, 0]
        for a in ["VoiceBridge", "--mcp", "x"] { data += Array(a.utf8) + [0] }
        data += Array("HOME=/Users/k".utf8) + [0]
        XCTAssertEqual(MirrorGegenstelle.argumente(procargs2: data), ["VoiceBridge", "--mcp", "x"])
        XCTAssertNil(MirrorGegenstelle.argumente(procargs2: [1, 0]))
    }

    /// Das Requirement passt zur installierten VoiceBridge (statisch) und zur laufenden App (dynamisch); ihre
    /// MCP-Prozesse tragen `--mcp` und fallen damit heraus. Ohne VoiceBridge auf diesem Mac übersprungen.
    func testRequirementPasstZurInstalliertenVoiceBridge() throws {
        var req: SecRequirement?
        XCTAssertEqual(SecRequirementCreateWithString(MirrorGegenstelle.voiceBridgeRequirement as CFString, [], &req),
                       errSecSuccess)
        let app = URL(fileURLWithPath: "/Applications/VoiceBridge.app")
        guard FileManager.default.fileExists(atPath: app.path), let req else {
            throw XCTSkip("VoiceBridge ist hier nicht installiert")
        }
        var stat: SecStaticCode?
        XCTAssertEqual(SecStaticCodeCreateWithPath(app as CFURL, [], &stat), errSecSuccess)
        XCTAssertEqual(SecStaticCodeCheckValidity(try XCTUnwrap(stat), [], req), errSecSuccess)
        // Laufende Prozesse: die App erfüllt das Requirement, die MCP-Prozesse auch, haben aber --mcp
        let ps = Process()
        ps.executableURL = URL(fileURLWithPath: "/bin/ps")
        ps.arguments = ["-axo", "pid=,args="]
        let pipe = Pipe()
        ps.standardOutput = pipe
        try ps.run()
        let out = String(decoding: pipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
        ps.waitUntilExit()
        let exe = app.appendingPathComponent("Contents/MacOS/VoiceBridge").path
        for line in out.split(separator: "\n") {
            let parts = line.trimmingCharacters(in: .whitespaces).split(separator: " ", maxSplits: 1)
            guard parts.count == 2, parts[1].hasPrefix(exe), let pid = Int32(parts[0]) else { continue }
            var code: SecCode?
            guard SecCodeCopyGuestWithAttributes(nil, [kSecGuestAttributePid as String: pid] as CFDictionary, [], &code)
                == errSecSuccess, let code
            else { continue }
            // Erfüllt, außer der Prozess ist älter als die Datei auf der Platte (VoiceBridge seitdem aktualisiert)
            let st = SecCodeCheckValidity(code, MirrorGegenstelle.pruefFlags, req)
            XCTAssertTrue(st == errSecSuccess || st == errSecCSStaticCodeChanged, "PID \(pid): \(st)")
            // Eine fremde Signatur fällt auch im Kernel durch
            var fremd: SecRequirement?
            SecRequirementCreateWithString(
                #"anchor apple generic and identifier "de.upvis.voicebridge.mac" and certificate leaf[subject.OU] = "XXXXXXXXXX""#
                    as CFString, [], &fremd)
            XCTAssertNotEqual(SecCodeCheckValidity(code, MirrorGegenstelle.pruefFlags, try XCTUnwrap(fremd)),
                              errSecSuccess)
            let args = try XCTUnwrap(MirrorGegenstelle.argumente(pid: pid))
            XCTAssertEqual(args.contains("--mcp"), parts[1].contains("--mcp"), "PID \(pid): \(args)")
        }
    }

    func testVermerkImKatalogeintrag() throws {
        let json = Data(#"{"id":"rohr-alfer-16x1","status":"vorgeschlagen","ebene":"eigen"}"#.utf8)
        let am = try XCTUnwrap(MirrorFreigabeZeit.datum("2026-10-22T13:00:00Z"))
        let frei = try JSONDecoder().decode(JSONValue.self, from: Catalog.approvedJSON(json, von: "Kevin (iPhone)", am: am))
        XCTAssertEqual(frei["status"]?.stringValue, "frei")
        XCTAssertEqual(frei["freigegeben_von"]?.stringValue, "Kevin (iPhone)")
        XCTAssertEqual(frei["freigegeben_am"]?.stringValue, "2026-10-22T13:00:00Z")
        XCTAssertNil(frei["ebene"])
        let mac = try JSONDecoder().decode(JSONValue.self, from: Catalog.approvedJSON(json))
        XCTAssertNil(mac["freigegeben_von"], "ohne von wie bisher")
    }

    func testNonceUndVergleich() {
        let a = FreigabeVomIPhone.zufall(16)
        XCTAssertEqual(a.count, 32)
        XCTAssertNotEqual(a, FreigabeVomIPhone.zufall(16))
        XCTAssertTrue(FreigabeVomIPhone.gleich(a, a))
        XCTAssertFalse(FreigabeVomIPhone.gleich(a, String(a.dropLast()) + "x"))
        XCTAssertFalse(FreigabeVomIPhone.gleich(a, String(a.dropLast())))
        XCTAssertFalse(FreigabeVomIPhone.gleich("", ""))
    }
}
