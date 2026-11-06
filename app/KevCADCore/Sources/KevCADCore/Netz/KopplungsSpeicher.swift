import Foundation
import Security
#if os(macOS)
import SystemConfiguration
#endif

// I-2b: Wo die Kopplungen liegen. Mac: Liste der iPads mit ihren Schlüsseln. iPad: der gescannte Code seines Mac.

#if os(macOS)
/// Gekoppelte iPads am Mac: `kopplungen.json` im Ordner der App (Datei 0600, Ordner 0700 wie beim Spiegel-Socket).
/// Bewusst eine Datei und nicht der Anmeldeschlüsselbund: Der fragt nach jeder neuen Signatur der App nach (Neubau,
/// Testvarianten), und eine solche Abfrage auf Kevins Bildschirm darf es nicht geben. Schutz wie bei ssh-Schlüsseln:
/// nur dieser Benutzer kann die Datei lesen.
public final class MacKopplungen {
    struct Eintrag: Codable {
        var geraet: GekoppeltesGeraet
        var schluessel: Data
    }

    private let datei: URL
    private var eintraege: [Eintrag] = []

    public init(datei: URL = AppInfo.supportDirectory.appendingPathComponent("kopplungen.json")) {
        self.datei = datei
        laden()
    }

    public var geraete: [GekoppeltesGeraet] { eintraege.map(\.geraet) }

    /// Schlüssel für den Eingang: bestätigte Geräte und Codes, die noch gelten.
    public func schluessel(jetzt: Date = Date()) -> [(kennung: String, schluessel: Data)] {
        eintraege.filter { $0.geraet.bestaetigt || ($0.geraet.bis ?? .distantPast) > jetzt }
            .map { ($0.geraet.kennung, $0.schluessel) }
    }

    /// Neuer Code für ein Gerät, das sich in den nächsten `dauer` Sekunden zum ersten Mal verbinden muss.
    public func neu(mac: String, macName: String, port: UInt16, wege: [String], dauer: TimeInterval = 600,
                    jetzt: Date = Date()) throws -> KopplungsCode {
        aufraeumen(jetzt: jetzt)
        let kennung = neueKopplungsKennung()
        let schluessel = NetzKanal.neuerSchluessel()
        let bis = jetzt.addingTimeInterval(dauer)
        eintraege.append(Eintrag(geraet: GekoppeltesGeraet(kennung: kennung, name: "iPad", angelegt: jetzt, bis: bis),
                                 schluessel: schluessel))
        try speichern()
        return KopplungsCode(mac: mac, name: macName, port: port, wege: wege, kennung: kennung, schluessel: schluessel,
                             bis: bis)
    }

    /// Ein Gerät hat sich verbunden; `name` meldet das iPad selbst (HELLO_APP.geraet).
    public func verbunden(kennung: String, name: String?, jetzt: Date = Date()) {
        guard let i = eintraege.firstIndex(where: { $0.geraet.kennung == kennung }) else { return }
        eintraege[i].geraet.zuletzt = jetzt
        eintraege[i].geraet.bis = nil
        if let name, !name.isEmpty { eintraege[i].geraet.name = name }
        try? speichern()
    }

    public func entfernen(_ kennung: String) {
        eintraege.removeAll { $0.geraet.kennung == kennung }
        try? speichern()
    }

    /// Abgelaufene Codes, mit denen sich nie ein Gerät verbunden hat, entfernen.
    public func aufraeumen(jetzt: Date = Date()) {
        let vorher = eintraege.count
        eintraege.removeAll { !$0.geraet.bestaetigt && ($0.geraet.bis ?? .distantPast) <= jetzt }
        if eintraege.count != vorher { try? speichern() }
    }

    private func laden() {
        guard let daten = try? Data(contentsOf: datei) else { return }
        eintraege = (try? Self.decoder.decode([Eintrag].self, from: daten)) ?? []
    }

    private func speichern() throws {
        let ordner = datei.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: ordner, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        let tmp = ordner.appendingPathComponent(".kopplungen-\(UUID().uuidString).json")
        try Self.encoder.encode(eintraege).write(to: tmp)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: tmp.path)
        _ = try FileManager.default.replaceItemAt(datei, withItemAt: tmp)
    }

    private static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        e.outputFormatting = [.prettyPrinted, .sortedKeys]
        return e
    }()

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()
}

/// Adressen, unter denen das iPad den Mac außer über Bonjour findet: Adressen im lokalen Netz, Tailscale (100.64/10)
/// und `<Name>.local`.
public enum MacWege {
    public static func aktuell() -> [String] {
        var lokal: [String] = []
        var tailscale: [String] = []
        var liste: UnsafeMutablePointer<ifaddrs>?
        if getifaddrs(&liste) == 0, let start = liste {
            var p: UnsafeMutablePointer<ifaddrs>? = start
            while let ifa = p {
                defer { p = ifa.pointee.ifa_next }
                let flags = Int32(ifa.pointee.ifa_flags)
                guard let addr = ifa.pointee.ifa_addr, addr.pointee.sa_family == UInt8(AF_INET),
                    flags & IFF_UP != 0, flags & IFF_LOOPBACK == 0
                else { continue }
                var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                guard getnameinfo(addr, socklen_t(addr.pointee.sa_len), &host, socklen_t(host.count), nil, 0,
                                  NI_NUMERICHOST) == 0
                else { continue }
                let ip = String(cString: host)
                let teile = ip.split(separator: ".").compactMap { Int($0) }
                guard teile.count == 4, !(teile[0] == 169 && teile[1] == 254) else { continue }
                if teile[0] == 100, (64...127).contains(teile[1]) {
                    tailscale.append(ip)
                } else {
                    lokal.append(ip)
                }
            }
            freeifaddrs(start)
        }
        var wege = lokal + tailscale
        if let name = SCDynamicStoreCopyLocalHostName(nil) as String?, !name.isEmpty { wege.append(name + ".local") }
        var gesehen = Set<String>()
        return wege.filter { gesehen.insert($0).inserted }
    }
}
#endif

#if os(iOS)
/// Kopplung des iPads mit seinem Mac: der gescannte Code im Schlüsselbund dieses Geräts (nach dem ersten Entsperren
/// lesbar, damit die App sich nach einem Neustart selbst verbinden kann; geht nicht in Sicherungen auf andere Geräte).
public enum PadKopplung {
    static let dienst = "de.upvis.kevcad.kopplung"
    static let konto = "mac"

    public static func laden() -> KopplungsCode? {
        let frage: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: dienst,
            kSecAttrAccount as String: konto, kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var ergebnis: CFTypeRef?
        guard SecItemCopyMatching(frage as CFDictionary, &ergebnis) == errSecSuccess, let daten = ergebnis as? Data,
            let text = String(data: daten, encoding: .utf8)
        else { return nil }
        return KopplungsCode.lesen(text)
    }

    public static func speichern(_ code: KopplungsCode) throws {
        loeschen()
        let eintrag: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: dienst,
            kSecAttrAccount as String: konto, kSecValueData as String: Data(try code.text().utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        let status = SecItemAdd(eintrag as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw NSError(domain: "KevCAD.Kopplung", code: Int(status),
                          userInfo: [NSLocalizedDescriptionKey: "Kopplung ließ sich nicht sichern (\(status))"])
        }
    }

    public static func loeschen() {
        let frage: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: dienst,
            kSecAttrAccount as String: konto,
        ]
        SecItemDelete(frage as CFDictionary)
    }
}
#endif
