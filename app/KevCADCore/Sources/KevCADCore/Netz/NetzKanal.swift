import CryptoKit
import Foundation
import Network

// I-2b (PLAN-IPAD.md, Entscheidung I8): verschlüsselter Kanal zwischen iPad und Mac-App. Kein Zertifikat, keine
// Zertifizierungsstelle: Beide Seiten kennen denselben 256-Bit-Schlüssel aus der Kopplung (QR-Code am Mac). Wer ihn
// nicht hat, kommt über den TLS-Handschlag nicht hinaus, der Mac antwortet ihm also gar nicht erst. Jedes gekoppelte
// iPad hat seinen eigenen Schlüssel unter seiner eigenen Kennung (PSK-Identität), so lässt sich eines allein entfernen.
//
// Vorbild ist VoiceBridge (`Archiv/v2/Shared/SecureChannel.swift`, im Alltag erprobt): TLS 1.2 mit gemeinsamem
// Schlüssel, weil Network.framework gemeinsame Schlüssel mit TLS 1.3 nicht aushandelt. Der Transportschlüssel wird per
// HKDF aus dem Kopplungsschlüssel abgeleitet.

public enum NetzKanal {
    /// Bonjour-Dienst der Mac-App für iPads.
    public static let dienstTyp = "_kevcad._tcp"
    /// Fassung des Kanals (im TXT-Eintrag und im Kopplungscode).
    public static let fassung = 1

    /// Parameter für das iPad (Client): ein Schlüssel, eine Kennung.
    public static func parameter(schluessel: Data, kennung: String) -> NWParameters {
        parameter(schluessel: [(kennung, schluessel)])
    }

    /// Parameter für den Eingang am Mac (Server): alle gekoppelten Geräte, jedes mit seiner Kennung.
    public static func parameter(schluessel: [(kennung: String, schluessel: Data)]) -> NWParameters {
        let tls = NWProtocolTLS.Options()
        let sicherheit = tls.securityProtocolOptions
        sec_protocol_options_set_min_tls_protocol_version(sicherheit, .TLSv12)
        sec_protocol_options_set_max_tls_protocol_version(sicherheit, .TLSv13)
        for (kennung, roh) in schluessel {
            let transport = transportSchluessel(roh)
            let schluesselDaten = transport.withUnsafeBytes { DispatchData(bytes: $0) }
            let kennungDaten = Data(kennung.utf8).withUnsafeBytes { DispatchData(bytes: $0) }
            sec_protocol_options_add_pre_shared_key(sicherheit, schluesselDaten as __DispatchData,
                                                    kennungDaten as __DispatchData)
        }
        sec_protocol_options_append_tls_ciphersuite(sicherheit, tls_ciphersuite_t.AES_128_GCM_SHA256)

        let tcp = NWProtocolTCP.Options()
        tcp.enableKeepalive = true
        tcp.keepaliveIdle = 10
        tcp.connectionTimeout = 8
        tcp.noDelay = true  // Kamera und Auswahl sind kleine Rahmen, die sofort raus sollen

        let parameter = NWParameters(tls: tls, tcp: tcp)
        // Auch wenn das WLAN die Geräte voneinander abschottet (Client-Isolation): direkter Weg über AWDL
        parameter.includePeerToPeer = true
        return parameter
    }

    /// Transportschlüssel aus dem Kopplungsschlüssel (eigener Zweck, damit derselbe Schlüssel an anderer Stelle einen
    /// anderen ergibt).
    static func transportSchluessel(_ roh: Data) -> SymmetricKey {
        HKDF<SHA256>.deriveKey(inputKeyMaterial: SymmetricKey(data: roh),
                               info: Data("kevcad.transport.v1".utf8), outputByteCount: 32)
    }

    /// 256 Bit aus dem Zufallsgenerator des Systems.
    public static func neuerSchluessel() -> Data {
        var daten = Data(count: 32)
        let status = daten.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, 32, $0.baseAddress!) }
        precondition(status == errSecSuccess, "Zufallsgenerator nicht verfügbar")
        return daten
    }

    /// Kurzer Fingerabdruck zum Vergleichen beider Seiten in der Oberfläche („3F2A-91C0“).
    public static func fingerabdruck(_ schluessel: Data) -> String {
        let hex = SHA256.hash(data: schluessel).prefix(4).map { String(format: "%02X", $0) }.joined()
        return String(hex.prefix(4)) + "-" + String(hex.suffix(4))
    }

    /// Bedeutet der Fehler, dass die Gegenseite einen anderen Schlüssel hat (dann neu koppeln)? Nur dann stimmen die
    /// Prüfsummen der verschlüsselten Daten nicht (-9846/-9820, seltener -9845/-9821). Ein abgebrochener Aufbau (App im
    /// Hintergrund, WLAN weg) endet anders und ist kein Grund zum Neukoppeln (Erfahrung aus VoiceBridge).
    public static func schluesselPasstNicht(_ fehler: Error?) -> Bool {
        guard let fehler = fehler as? NWError, case .tls(let status) = fehler else { return false }
        return [-9846, -9820, -9845, -9821].contains(status)
    }
}
