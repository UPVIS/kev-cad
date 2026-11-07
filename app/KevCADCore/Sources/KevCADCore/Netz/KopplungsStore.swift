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

    // MARK: I-6 Live-Kopplung (beide Geräte)

    /// Gemeinsame oder Eigene Ansicht; jedes Gerät merkt sich seine Wahl.
    @Published public internal(set) var modus: AnsichtModus = KopplungsStore.gemerkterModus
    /// Verbundene Geräte laut Kernel (GERAETE), mit diesem Gerät (`ich`).
    @Published public internal(set) var liveGeraete: [GeraetEintrag] = []
    /// Breite des Hauptfensters in Punkten (die Oberfläche misst sie, ohne Beobachtung); 0 = unbekannt. Unter
    /// `KopplungGrenzen.kachelnNebeneinanderAb` zeigt das Gerät geteilte Kacheln als große Kachel.
    public var fensterBreite: Double = 0
    /// Eigene Ansicht: den Blick der anderen Geräte als dünnen Rahmen im Modell zeigen (auf Wunsch, gemerkt).
    @Published public internal(set) var blickZeigen: Bool = UserDefaults.standard.bool(forKey: KopplungsStore.blickSchluessel)
    /// Geräte, deren Blick gerade bekannt ist (Namen, für die Kapsel mit dem Aus-Knopf).
    @Published public internal(set) var blickVon: [String] = []
    /// Was auf den anderen Geräten gerade gesprochen wird (Name des Geräts, bisheriger Text).
    @Published public internal(set) var fremdeTexte: [FremderText] = []

    /// Zeigt der Viewer gerade Rahmen anderer Geräte?
    public var blickSichtbar: Bool { modus == .eigen && blickZeigen && !blickVon.isEmpty }

    public init() {}

    /// Die anderen verbundenen Geräte (ohne dieses).
    public var andere: [GeraetEintrag] { liveGeraete.filter { !$0.ich } }
    /// Führt dieses Gerät die Gemeinsame Ansicht?
    public var fuehrtSelbst: Bool { liveGeraete.first { $0.ich }?.fuehrt ?? false }
    /// Anderes Gerät, das die Gemeinsame Ansicht führt.
    public var fuehrendesAnderes: GeraetEintrag? { andere.first { $0.fuehrt } }
    /// Gibt es überhaupt jemanden, mit dem dieses Gerät die Ansicht teilen kann?
    public var teiltMitAnderen: Bool { modus == .gemeinsam && andere.contains { $0.ansicht == .gemeinsam } }

    /// Kurzer Text für Kopfleiste und Kopplungs-Chip, etwa „Gemeinsame Ansicht mit iPad von Kevin · iPad führt“;
    /// nil ohne anderes Gerät.
    public var ansichtText: String? {
        let partner = andere.filter { $0.ansicht != nil }
        guard !partner.isEmpty else { return nil }
        let namen = partner.map(\.anzeigeName).joined(separator: ", ")
        if modus == .eigen { return "Eigene Ansicht · \(namen) verbunden" }
        guard partner.contains(where: { $0.ansicht == .gemeinsam }) else { return "Gemeinsame Ansicht · \(namen) hat eine eigene" }
        if fuehrtSelbst { return "Gemeinsame Ansicht mit \(namen) · du führst" }
        if let f = fuehrendesAnderes { return "Gemeinsame Ansicht mit \(namen) · \(f.anzeigeName) führt" }
        return "Gemeinsame Ansicht mit \(namen)"
    }

    static let modusSchluessel = "kevcad.kopplung.ansicht"
    static let blickSchluessel = "kevcad.kopplung.blick"
    static var gemerkterModus: AnsichtModus {
        UserDefaults.standard.string(forKey: modusSchluessel).flatMap(AnsichtModus.init(rawValue:)) ?? .gemeinsam
    }
}

/// Text, den Kevin gerade an einem anderen Gerät spricht.
public struct FremderText: Equatable, Identifiable, Sendable {
    /// Verbindungsnummer des Geräts
    public var id: Int
    public var geraet: String
    public var text: String

    public init(id: Int, geraet: String, text: String) {
        self.id = id
        self.geraet = geraet
        self.text = text
    }
}

/// Aktionen der Kopplung (Oberfläche → App-Kern).
@MainActor
public protocol KopplungsActions: AnyObject {
    /// I-6: Gemeinsame oder Eigene Ansicht (beide Geräte).
    func ansichtModus(_ modus: AnsichtModus)
    /// I-6: In der Eigenen Ansicht den Blick der anderen Geräte als Rahmen zeigen oder ausblenden.
    func blickZeigen(_ an: Bool)
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
