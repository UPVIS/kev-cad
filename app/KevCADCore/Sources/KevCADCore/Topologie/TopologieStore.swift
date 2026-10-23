import Foundation
import simd

/// Topologieoptimierung im Fenster (additiv zu AppModel, PLAN-TOPOLOGIE.md): letzter Stand (TOPO), Netze (TOPO_FIELD)
/// und die Einstellungen des Abschnitts „Optimieren“ im Inspektor.
@MainActor
public final class TopologieStore: ObservableObject {
    public enum Ansicht: String, CaseIterable, Sendable {
        /// nichts zusätzlich im Viewer
        case aus
        /// während der Rechnung: Dichte der letzten Iteration halbdurchsichtig über dem Teil
        case live
        /// Spannungsfarben am Ausgangsteil
        case vorher
        /// Spannungsfarben am optimierten Körper
        case nachher

        public var titel: String {
            switch self {
            case .aus: return "Aus"
            case .live: return "Dichte"
            case .vorher: return "Vorher"
            case .nachher: return "Nachher"
            }
        }
    }

    @Published public var stand: TopologieStand?
    @Published public var felder: [TopologieFeldArt: TopologieFeld] = [:]
    @Published public var ansicht: Ansicht = .live
    @Published public var schutzZeigen = false
    // Einstellungen des Abschnitts
    @Published public var behalten: Double = 0.4
    @Published public var ueberhang = false
    @Published public var fein = false
    /// Die Schrauben in den Bohrungen halten das Teil (statt der ganzen Auflagefläche).
    @Published public var schraubenHalten = false
    /// Szenario für die nächste Optimierung (nil = das mit der größten Ausnutzung des Teils).
    @Published public var szenario: String?

    public init() {}

    /// Feld des aktuellen Auftrags.
    public func feld(_ art: TopologieFeldArt) -> TopologieFeld? {
        guard let f = felder[art], let s = stand, f.auftrag == s.auftrag || f.auftrag == 0 else { return nil }
        return f
    }
}

/// Aktionen des Abschnitts „Optimieren“; die Oberfläche ruft sie über `model.actions as? TopologieActions`.
@MainActor
public protocol TopologieActions: AnyObject {
    /// Optimierung starten (TOPO_START) mit den Einstellungen des Stores.
    func starteTopologie(teil: String)
    /// Laufende Optimierung beenden (TOPO_CANCEL).
    func brecheTopologieAb()
    /// Ergebnis als Variante übernehmen (TOPO_APPLY).
    func uebernehmeTopologie()
    func setTopologieAnsicht(_ ansicht: TopologieStore.Ansicht)
    func setTopologieSchutz(_ an: Bool)
}
