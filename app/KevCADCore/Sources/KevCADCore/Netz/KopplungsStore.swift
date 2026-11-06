import Combine
import Foundation

/// I-2b (PLAN-IPAD.md): Zustand der Kopplung von Mac und iPad für die Oberfläche (`AppModel.kopplung`, Aktionen:
/// `actions as? KopplungsActions`).
@MainActor
public final class KopplungsStore: ObservableObject {
    /// Am Mac: gekoppelte iPads (ohne Schlüssel).
    @Published public internal(set) var geraete: [GekoppeltesGeraet] = []
    /// Am Mac: Kopplungscode, solange der QR-Code zu sehen sein soll.
    @Published public internal(set) var code: KopplungsCode?
    /// Am Mac: Port des iPad-Eingangs; nil = zu (ohne gekoppeltes Gerät gibt es keinen offenen Port).
    @Published public internal(set) var eingangPort: UInt16?
    /// Auf dem iPad: Name des gekoppelten Mac; nil = noch nicht gekoppelt.
    @Published public internal(set) var macName: String?
    /// Auf dem iPad: Die Verbindung zum Mac steht.
    @Published public internal(set) var verbunden = false
    /// Letzter Hinweis für Kevin, etwa „Schlüssel passt nicht mehr, bitte neu koppeln“.
    @Published public internal(set) var meldung: String?

    public init() {}
}

/// Aktionen der Kopplung (Oberfläche → App-Kern).
@MainActor
public protocol KopplungsActions: AnyObject {
    #if os(macOS)
    /// Neuen QR-Code für ein iPad zeigen (gilt 10 Minuten für die erste Verbindung).
    func ipadKoppeln()
    /// QR-Code ausblenden.
    func ipadKopplungSchliessen()
    /// Gekoppeltes iPad entfernen: Es kommt nicht mehr herein, bis es neu gekoppelt ist.
    func ipadEntfernen(_ kennung: String)
    #else
    /// Gescannten Text des QR-Codes vom Mac übernehmen; false, wenn es kein Kopplungscode von Kev CAD ist.
    @discardableResult
    func koppeln(text: String) -> Bool
    /// Kopplung mit dem Mac lösen.
    func kopplungLoesen()
    #endif
}
