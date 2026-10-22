import Darwin
import Foundation
import Security

/// Prüfung der Gegenstelle für die Freigabe vom iPhone (MIRROR.md, Version 1.1, „Prüfung der Gegenstelle“).
///
/// Freigeben darf nur Kevin, und vom iPhone nur über die VoiceBridge-App. Ein Agent oder ein Programm, das er startet
/// (Python aus model.py, die MCP-Prozesse von VoiceBridge), läuft unter derselben UID und käme über `getpeereid` allein
/// an den Socket. Deshalb prüft Kev CAD für die Freigabe das Audit-Token des Sockets (`LOCAL_PEERTOKEN`), nie die PID
/// allein (PIDs werden wiederverwendet):
///
/// 1. Code der Gegenstelle aus dem Audit-Token (`SecCodeCopyGuestWithAttributes` mit `kSecGuestAttributeAudit`, wie
///    `SecCodeCreateWithAuditToken`, das im öffentlichen SDK fehlt).
/// 2. Argumente des Prozesses (`KERN_PROCARGS2`, PID aus dem Audit-Token) ohne `--mcp`: Die MCP-Prozesse der Agenten
///    sind dieselbe Datei wie die VoiceBridge-App und haben dieselbe Signatur.
/// 3. `SecCodeCheckValidity` gegen `voiceBridgeRequirement`. Das kommt nach Schritt 2 und bindet über die PID-Version
///    im Audit-Token an genau den Prozess, der verbunden hat: Wäre er beendet und die PID neu vergeben, scheitert es.
///
/// Testmodus: nur in einer Testvariante (Bundle-ID mit `.test`) und nur mit `KEVCAD_FREIGABE_TESTMODUS=1` ist jede
/// Gegenstelle derselben UID erlaubt (etwa `mirror_sim.py --client`). Die installierte App kennt ihn nicht.
public enum MirrorGegenstelle {
    /// Requirement der VoiceBridge-Mac-App, mit VoiceBridge abgestimmt am 22.10.2026 (am installierten Bündel geprüft:
    /// Identifier `de.upvis.voicebridge.mac`, Team-ID `2GX7UC98J6`, Zertifikat Apple Development). Bewusst ein
    /// Requirement statt einzelner Felder: Es gilt auch nach einem Wechsel auf Developer ID. Testinstanzen von
    /// VoiceBridge haben eine eigene Bundle-ID mit „test“ und fallen damit gewollt heraus.
    public static let voiceBridgeRequirement =
        #"anchor apple generic and identifier "de.upvis.voicebridge.mac" and certificate leaf[subject.OU] = "2GX7UC98J6""#

    /// Flags der Signaturprüfung: Standard, also laufender Prozess und Datei auf der Platte. Folge (geprüft am
    /// 22.10.2026): Wurde VoiceBridge auf der Platte ersetzt, scheitert der noch laufende alte Prozess mit
    /// `errSecCSStaticCodeChanged` (−67034), bis er neu startet; das ist gewollt (im Zweifel nein). Die Prüfung im Kernel
    /// (`kSecCSMatchGuestRequirementInKernel`) kann Zertifikatsfelder wie `leaf[subject.OU]` nicht auswerten (−67052).
    public static let pruefFlags: SecCSFlags = []

    /// Argument, das die Gegenstelle nicht tragen darf (MCP-Prozesse der Agenten, auch `--mcp=…`).
    public static let verbotenesArgument = "--mcp"

    /// Umgebungsvariable des Testmodus (wirkt nur in Testvarianten).
    public static let testmodusVariable = "KEVCAD_FREIGABE_TESTMODUS"

    /// Ergebnis der Prüfung.
    public struct Urteil: Equatable, Sendable {
        /// Darf FREIGABE bekommen und `freigabe` schicken.
        public var erlaubt: Bool
        /// Begründung für das Protokoll (ohne Geheimnisse).
        public var grund: String
        /// PID aus dem Audit-Token (nur zur Anzeige).
        public var pid: Int32

        public init(erlaubt: Bool, grund: String, pid: Int32 = 0) {
            self.erlaubt = erlaubt
            self.grund = grund
            self.pid = pid
        }

        public static func nein(_ grund: String, pid: Int32 = 0) -> Urteil { Urteil(erlaubt: false, grund: grund, pid: pid) }
    }

    /// Prüft eine Gegenstelle anhand ihres Audit-Tokens (nil, wenn es sich nicht lesen ließ).
    public typealias Pruefer = @Sendable (audit_token_t?) -> Urteil

    /// Testmodus an? Nur Testvarianten mit der Umgebungsvariable.
    public static func testmodus(
        bundleID: String = AppInfo.bundleID, environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Bool {
        bundleID.contains(".test") && environment[testmodusVariable] == "1"
    }

    /// Prüfer der App: im Testmodus jede Gegenstelle, sonst nur die VoiceBridge-App.
    public static func standardPruefer(testmodus: Bool) -> Pruefer {
        { token in
            if testmodus {
                return Urteil(erlaubt: true, grund: "Testmodus der Testvariante", pid: token.map(pid) ?? 0)
            }
            guard let token else { return .nein("Audit-Token der Gegenstelle nicht lesbar") }
            return pruefe(token)
        }
    }

    // MARK: Audit-Token

    /// Audit-Token der Gegenstelle eines Unix-Sockets (`getsockopt(SOL_LOCAL, LOCAL_PEERTOKEN)`).
    public static func auditToken(fd: Int32) -> audit_token_t? {
        var token = audit_token_t()
        var len = socklen_t(MemoryLayout<audit_token_t>.size)
        let rc = getsockopt(fd, SOL_LOCAL, LOCAL_PEERTOKEN, &token, &len)
        guard rc == 0, len == socklen_t(MemoryLayout<audit_token_t>.size) else { return nil }
        return token
    }

    /// PID aus dem Audit-Token (wie `audit_token_to_pid` aus libbsm: `val[5]`).
    public static func pid(_ token: audit_token_t) -> Int32 { Int32(bitPattern: token.val.5) }

    // MARK: Prüfung

    /// Volle Prüfung gegen ein Requirement (Vorgabe: die VoiceBridge-App).
    public static func pruefe(_ token: audit_token_t, requirement: String = voiceBridgeRequirement) -> Urteil {
        var tok = token
        let pid = pid(token)
        // Gleichwertig zu SecCodeCreateWithAuditToken, das das öffentliche SDK nicht anbietet: Gast-Code über das
        // Audit-Token als Attribut (bindet an PID und PID-Version)
        let audit = withUnsafeBytes(of: &tok) { Data($0) }
        var code: SecCode?
        let st = SecCodeCopyGuestWithAttributes(
            nil, [kSecGuestAttributeAudit as String: audit] as CFDictionary, [], &code)
        guard st == errSecSuccess, let code else {
            return .nein("Code der Gegenstelle nicht ermittelbar (OSStatus \(st))", pid: pid)
        }
        // Argumente vor der Signaturprüfung lesen: Die Prüfung danach stellt sicher, dass es derselbe Prozess war.
        guard let args = argumente(pid: pid) else { return .nein("Argumente der Gegenstelle nicht lesbar", pid: pid) }
        if let bad = args.first(where: { $0.hasPrefix(verbotenesArgument) }) {
            return .nein("Gegenstelle läuft mit \(bad) (MCP-Prozess)", pid: pid)
        }
        var req: SecRequirement?
        let rs = SecRequirementCreateWithString(requirement as CFString, [], &req)
        guard rs == errSecSuccess, let req else { return .nein("Requirement ungültig (OSStatus \(rs))", pid: pid) }
        let check = SecCodeCheckValidity(code, pruefFlags, req)
        guard check == errSecSuccess else {
            if check == errSecCSStaticCodeChanged {
                return .nein("VoiceBridge wurde auf der Platte aktualisiert; VoiceBridge neu starten", pid: pid)
            }
            let text = (SecCopyErrorMessageString(check, nil) as String?) ?? "OSStatus \(check)"
            return .nein("Signatur der Gegenstelle passt nicht zu VoiceBridge (\(text))", pid: pid)
        }
        return Urteil(erlaubt: true, grund: "VoiceBridge-App (Signatur geprüft)", pid: pid)
    }

    /// Argumente eines Prozesses (`argv`, ohne den Programmpfad davor) über `sysctl KERN_PROCARGS2`.
    public static func argumente(pid: Int32) -> [String]? {
        guard pid > 0 else { return nil }
        var argmax: Int32 = 0
        var size = MemoryLayout<Int32>.size
        var mibMax: [Int32] = [CTL_KERN, KERN_ARGMAX]
        guard sysctl(&mibMax, 2, &argmax, &size, nil, 0) == 0, argmax > 0 else { return nil }
        var buffer = [UInt8](repeating: 0, count: Int(argmax))
        var len = buffer.count
        var mib: [Int32] = [CTL_KERN, KERN_PROCARGS2, pid]
        guard sysctl(&mib, 3, &buffer, &len, nil, 0) == 0 else { return nil }
        return argumente(procargs2: Array(buffer.prefix(len)))
    }

    /// Liest den Puffer von `KERN_PROCARGS2`: `argc` (Int32), Programmpfad, Nullbytes, dann `argc` Zeichenketten.
    public static func argumente(procargs2 data: [UInt8]) -> [String]? {
        guard data.count >= 4 else { return nil }
        let argc = Int(Int32(littleEndian: data.withUnsafeBytes { $0.loadUnaligned(as: Int32.self) }))
        guard argc >= 0 else { return nil }
        var i = 4
        while i < data.count, data[i] != 0 { i += 1 }  // Programmpfad
        while i < data.count, data[i] == 0 { i += 1 }  // Auffüllung
        var out: [String] = []
        while out.count < argc, i < data.count {
            var j = i
            while j < data.count, data[j] != 0 { j += 1 }
            out.append(String(decoding: data[i..<j], as: UTF8.self))
            i = j + 1
        }
        return out.count == argc ? out : nil
    }
}
