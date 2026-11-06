import Foundation
#if os(macOS)
import SystemConfiguration
#else
import UIKit
#endif

// I-2b (PLAN-IPAD.md): Kopplung von iPad und Mac. Der Mac zeigt einen QR-Code mit Name, Wegen, Kennung und Schlüssel;
// das iPad scannt ihn einmal und verbindet sich danach von selbst (im WLAN über Bonjour, unterwegs über Tailscale).
// Bis zur ersten Verbindung gilt der Code nur kurz (`bis`); danach ist das iPad gekoppelt, bis Kevin es am Mac entfernt.

/// Inhalt des QR-Codes am Mac.
public struct KopplungsCode: Codable, Equatable, Sendable {
    public var v: Int
    /// Kennung der Mac-App (`GeraeteKennung.kennung` des Mac).
    public var mac: String
    /// Name des Mac, wie das iPad ihn zeigt.
    public var name: String
    public var port: UInt16
    /// Adressen zum Mac außer Bonjour: Adressen im WLAN, Tailscale, `<Name>.local`.
    public var wege: [String]
    /// Kennung dieses iPads (TLS-Identität).
    public var kennung: String
    /// 32 Byte; im JSON base64.
    public var schluessel: Data
    /// Bis dahin nimmt der Mac die erste Verbindung mit diesem Code an.
    public var bis: Date

    public init(mac: String, name: String, port: UInt16, wege: [String], kennung: String, schluessel: Data, bis: Date) {
        self.v = NetzKanal.fassung
        self.mac = mac
        self.name = name
        self.port = port
        self.wege = wege
        self.kennung = kennung
        self.schluessel = schluessel
        self.bis = bis
    }

    public static let schema = "kevcad://koppeln/"

    /// Text für den QR-Code: Schema plus JSON in base64url.
    public func text() throws -> String {
        let enc = JSONEncoder()
        enc.dateEncodingStrategy = .secondsSince1970
        enc.outputFormatting = [.sortedKeys]
        let b64 = try enc.encode(self).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        return Self.schema + b64
    }

    /// Liest einen gescannten Text; nil, wenn es kein Kopplungscode von Kev CAD ist.
    public static func lesen(_ text: String) -> KopplungsCode? {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t.hasPrefix(schema) else { return nil }
        var b64 = String(t.dropFirst(schema.count))
            .replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while b64.count % 4 != 0 { b64 += "=" }
        guard let daten = Data(base64Encoded: b64) else { return nil }
        let dec = JSONDecoder()
        dec.dateDecodingStrategy = .secondsSince1970
        guard let code = try? dec.decode(KopplungsCode.self, from: daten), code.v == NetzKanal.fassung,
            code.schluessel.count == 32, !code.kennung.isEmpty
        else { return nil }
        return code
    }
}

/// Ein gekoppeltes Gerät aus Sicht des Mac.
public struct GekoppeltesGeraet: Codable, Equatable, Identifiable, Sendable {
    public var kennung: String
    public var name: String
    public var angelegt: Date
    /// Letzte Verbindung; nil, solange das Gerät sich noch nie verbunden hat.
    public var zuletzt: Date?
    /// Ablauf des QR-Codes, solange das Gerät noch nicht verbunden war; danach nil.
    public var bis: Date?

    public var id: String { kennung }
    public var bestaetigt: Bool { zuletzt != nil }

    public init(kennung: String, name: String, angelegt: Date, zuletzt: Date? = nil, bis: Date? = nil) {
        self.kennung = kennung
        self.name = name
        self.angelegt = angelegt
        self.zuletzt = zuletzt
        self.bis = bis
    }
}

/// Dauerhafte Kennung, Art und Name dieses Geräts (HELLO_APP.geraet, PROTOCOL.md „I-2 Mehrere Geräte“).
public enum GeraeteKennung {
    private static let schluessel = "KevCADGeraetKennung"

    /// Bleibt über Neustarts gleich (UserDefaults der jeweiligen App bzw. Testvariante).
    public static var kennung: String {
        let d = UserDefaults.standard
        if let k = d.string(forKey: schluessel), !k.isEmpty { return k }
        let neu = UUID().uuidString.lowercased()
        d.set(neu, forKey: schluessel)
        return neu
    }

    public static var art: String {
        #if os(macOS)
        "mac"
        #else
        "ipad"
        #endif
    }

    /// Name für Anzeigen am anderen Gerät („MacBook Pro von Kevin“, „iPad“).
    @MainActor
    public static var name: String {
        #if os(macOS)
        if let n = SCDynamicStoreCopyComputerName(nil, nil) as String?, !n.isEmpty { return n }
        return Host.current().localizedName ?? "Mac"
        #else
        UIDevice.current.name
        #endif
    }

    /// Feld `geraet` für HELLO_APP.
    @MainActor
    public static var helloFeld: [String: String] { ["id": kennung, "art": art, "name": name] }
}

/// Neue Kennung für ein zu koppelndes Gerät („kc-“ und 12 Hex-Zeichen).
public func neueKopplungsKennung() -> String {
    "kc-" + NetzKanal.neuerSchluessel().prefix(6).map { String(format: "%02x", $0) }.joined()
}
