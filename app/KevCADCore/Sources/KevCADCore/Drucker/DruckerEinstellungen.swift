import CryptoKit
import Foundation
import Security

// Drucker-Einstellungen (DRUCKVORSCHAU.md „Drucken (Phase 8)“, Einstellungen): `drucker.json` im Ordner der Variante,
// nie mit Geheimnissen. Seriennummer und Zugangscode liegen nur im Schlüsselbund (ein Eintrag je Drucker).

/// Ein Drucker in `drucker.json` (geht so auch als PRINTER_CONFIG an den Kernel).
public struct DruckerEintrag: Equatable, Sendable, Codable {
    public var id: String
    public var name: String
    /// Modellcode von Bambu, P1P = "C11"
    public var modell: String
    public var ip: String
    public var weg: DruckWeg
    /// Anfangs aus: Kevin schaltet den lesenden Live-Status bewusst ein.
    public var statusLesen: Bool
    /// Nur ein Hinweis für Menschen, wo die Zugangsdaten liegen.
    public var schluesselbund: Verweis
    /// Erste 12 Hex-Zeichen von SHA-256 der Seriennummer (zum Wiedererkennen in `gefunden`), nie die Seriennummer.
    public var kennung: String?
    /// Nur für die Attrappe auf 127.0.0.1 (Selbsttest); der Kernel nimmt sie sonst nicht an.
    public var portMqtt: Int?
    public var portFtps: Int?

    public struct Verweis: Equatable, Sendable, Codable {
        public var dienst: String
        public var konto: String
    }

    public init(id: String = "p1p", name: String = "P1P", modell: String = "C11", ip: String = "",
                weg: DruckWeg = .a, statusLesen: Bool = false)
    {
        self.id = id
        self.name = name
        self.modell = modell
        self.ip = ip
        self.weg = weg
        self.statusLesen = statusLesen
        schluesselbund = Verweis(dienst: DruckerSchluesselbund.dienst, konto: id)
    }

    enum CodingKeys: String, CodingKey {
        case id, name, modell, ip, weg, schluesselbund, kennung
        case statusLesen = "status_lesen", portMqtt = "port_mqtt", portFtps = "port_ftps"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? c.decode(String.self, forKey: .id)) ?? "p1p"
        name = (try? c.decode(String.self, forKey: .name)) ?? "P1P"
        modell = (try? c.decode(String.self, forKey: .modell)) ?? "C11"
        ip = (try? c.decode(String.self, forKey: .ip)) ?? ""
        weg = (try? c.decode(DruckWeg.self, forKey: .weg)) ?? .a
        statusLesen = (try? c.decode(Bool.self, forKey: .statusLesen)) ?? false
        schluesselbund = (try? c.decode(Verweis.self, forKey: .schluesselbund))
            ?? Verweis(dienst: DruckerSchluesselbund.dienst, konto: id)
        kennung = try? c.decode(String.self, forKey: .kennung)
        portMqtt = try? c.decode(Int.self, forKey: .portMqtt)
        portFtps = try? c.decode(Int.self, forKey: .portFtps)
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(name, forKey: .name)
        try c.encode(modell, forKey: .modell)
        try c.encode(ip, forKey: .ip)
        try c.encode(weg, forKey: .weg)
        try c.encode(statusLesen, forKey: .statusLesen)
        try c.encode(Verweis(dienst: DruckerSchluesselbund.dienst, konto: id), forKey: .schluesselbund)
        try c.encodeIfPresent(kennung, forKey: .kennung)
        try c.encodeIfPresent(portMqtt, forKey: .portMqtt)
        try c.encodeIfPresent(portFtps, forKey: .portFtps)
    }

    /// Drucker-ID: a–z, 0–9 und Bindestrich (nicht vorn), höchstens 32 Zeichen; zugleich das Konto im Schlüsselbund.
    public static func gueltigeID(_ s: String) -> Bool {
        s.range(of: "^[a-z0-9][a-z0-9-]{0,31}$", options: .regularExpression) != nil
    }

    /// IPv4 oder Hostname, ohne Leerzeichen und Schema.
    public static func gueltigeIP(_ s: String) -> Bool {
        let t = s.trimmingCharacters(in: .whitespaces)
        return !t.isEmpty && t.count <= 64 && t.range(of: "^[A-Za-z0-9.:-]+$", options: .regularExpression) != nil
    }

    /// Kennung wie im Kernel (`ssdp.kennung`): die ersten 12 Hex-Zeichen von SHA-256 der Seriennummer.
    public static func kennung(seriennummer: String) -> String {
        let d = SHA256.hash(data: Data(seriennummer.trimmingCharacters(in: .whitespacesAndNewlines).utf8))
        return d.map { String(format: "%02x", $0) }.joined().prefix(12).description
    }
}

/// Inhalt von `drucker.json`.
public struct DruckerEinstellungenDatei: Equatable, Sendable, Codable {
    public var version = 1
    public var aktiv: String?
    public var drucker: [DruckerEintrag] = []

    public init(aktiv: String? = nil, drucker: [DruckerEintrag] = []) {
        self.aktiv = aktiv
        self.drucker = drucker
    }

    public var aktiver: DruckerEintrag? {
        drucker.first { $0.id == aktiv } ?? drucker.first
    }

    public mutating func setze(_ e: DruckerEintrag) {
        if let i = drucker.firstIndex(where: { $0.id == e.id }) {
            drucker[i] = e
        } else {
            drucker.append(e)
        }
        aktiv = e.id
    }

    public static func standardURL() -> URL {
        AppInfo.supportDirectory.appendingPathComponent("drucker.json")
    }

    public static func laden(von url: URL = standardURL()) -> DruckerEinstellungenDatei {
        guard let d = try? Data(contentsOf: url),
              let datei = try? JSONDecoder().decode(DruckerEinstellungenDatei.self, from: d)
        else { return DruckerEinstellungenDatei() }
        return datei
    }

    public func speichern(nach url: URL = standardURL()) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        try enc.encode(self).write(to: url, options: .atomic)
    }
}

// MARK: - Schlüsselbund

/// Zugriff auf die Zugangsdaten. Die App schreibt und löscht nur; lesen tut allein der Kernel (`/usr/bin/security`).
@MainActor
public protocol DruckerZugangsSpeicher: AnyObject {
    func speichern(id: String, seriennummer: String, zugangscode: String) throws
    func loeschen(id: String) throws
    /// Gibt es einen Eintrag? (liest nur Attribute, nie den Inhalt)
    func vorhanden(id: String) -> Bool
}

public struct DruckerSchluesselbundFehler: Error, LocalizedError {
    public var status: OSStatus
    public var was: String
    public var errorDescription: String? {
        let text = (SecCopyErrorMessageString(status, nil) as String?) ?? "Code \(status)"
        return "Schlüsselbund: \(was) fehlgeschlagen (\(text))"
    }
}

/// macOS-Schlüsselbund (generisches Passwort, Dienst `de.upvis.kevcad.drucker`, Konto = Drucker-ID, Inhalt JSON).
/// Zugriff erlaubt für Kev CAD und `/usr/bin/security`, damit der Kernel ohne Rückfrage lesen kann und macOS nach
/// einem neuen Ad-hoc-Build nicht erneut nach dem Kennwort fragt. Folge: Jedes Programm unter Kevins Benutzer kann den
/// Zugangscode über `security` ohne Rückfrage lesen (steht so in den Einstellungen).
@MainActor
public final class DruckerSchluesselbund: DruckerZugangsSpeicher {
    public static let dienst = "de.upvis.kevcad.drucker"
    public static let security = "/usr/bin/security"

    public init() {}

    private func basis(_ id: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: Self.dienst,
         kSecAttrAccount as String: id]
    }

    public func speichern(id: String, seriennummer: String, zugangscode: String) throws {
        guard DruckerEintrag.gueltigeID(id) else {
            throw DruckerSchluesselbundFehler(status: errSecParam, was: "Speichern (ungültige Drucker-ID)")
        }
        let inhalt = try JSONSerialization.data(withJSONObject: [
            "seriennummer": seriennummer.trimmingCharacters(in: .whitespacesAndNewlines),
            "zugangscode": zugangscode.trimmingCharacters(in: .whitespacesAndNewlines),
        ], options: [.sortedKeys])
        try? loeschen(id: id)
        var q = basis(id)
        q[kSecValueData as String] = inhalt
        q[kSecAttrLabel as String] = "Kev CAD: Drucker \(id)"
        q[kSecAttrDescription as String] = "Seriennummer und Zugangscode des Bambu-Druckers (nur lesender Status)"
        if let access = Self.zugriff(id: id) {
            q[kSecAttrAccess as String] = access
        }
        let s = SecItemAdd(q as CFDictionary, nil)
        guard s == errSecSuccess else { throw DruckerSchluesselbundFehler(status: s, was: "Speichern") }
    }

    public func loeschen(id: String) throws {
        let s = SecItemDelete(basis(id) as CFDictionary)
        guard s == errSecSuccess || s == errSecItemNotFound else {
            throw DruckerSchluesselbundFehler(status: s, was: "Löschen")
        }
    }

    public func vorhanden(id: String) -> Bool {
        var q = basis(id)
        q[kSecReturnAttributes as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        return SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess
    }

    /// Zugriffsliste: diese App und `/usr/bin/security` (Altes Schlüsselbund-API; ohne Team-ID gibt es kein anderes).
    private static func zugriff(id: String) -> SecAccess? {
        var apps: [SecTrustedApplication] = []
        var selbst: SecTrustedApplication?
        if SecTrustedApplicationCreateFromPath(nil, &selbst) == errSecSuccess, let selbst { apps.append(selbst) }
        var sec: SecTrustedApplication?
        if SecTrustedApplicationCreateFromPath(security, &sec) == errSecSuccess, let sec { apps.append(sec) }
        var access: SecAccess?
        let s = SecAccessCreate("Kev CAD: Drucker \(id)" as CFString, apps as CFArray, &access)
        return s == errSecSuccess ? access : nil
    }
}

/// Für Tests: Speicher im Arbeitsspeicher.
@MainActor
public final class DruckerZugangImSpeicher: DruckerZugangsSpeicher {
    public private(set) var eintraege: [String: (String, String)] = [:]

    public init() {}

    public func speichern(id: String, seriennummer: String, zugangscode: String) throws {
        guard DruckerEintrag.gueltigeID(id) else {
            throw DruckerSchluesselbundFehler(status: errSecParam, was: "Speichern (ungültige Drucker-ID)")
        }
        eintraege[id] = (seriennummer, zugangscode)
    }

    public func loeschen(id: String) throws { eintraege[id] = nil }
    public func vorhanden(id: String) -> Bool { eintraege[id] != nil }
}
