import Foundation

/// V2-5 (spur-1): die letzten 50 Schritte des Agenten (AGENT_SPUR, AGENT_SCHRITT), älteste zuerst. Ein Schritt ist ein
/// Werkzeugaufruf; ein neuer Stand mit derselben `id` ersetzt ihn. Ohne `spur-1` bleibt die Liste leer.
@MainActor
public final class AgentenspurStore: ObservableObject {
    @Published public private(set) var schritte: [AgentSchritt] = []

    public init() {}

    /// AGENT_SPUR: die ganze Spur nach HELLO_APP.
    public func setzen(_ liste: [AgentSchritt]) { schritte = Array(liste.suffix(LiveGrenzen.spurLaenge)) }

    /// AGENT_SCHRITT: Stand eines Schritts übernehmen, ein neuer kommt hinten dazu.
    public func aktualisieren(_ s: AgentSchritt) {
        if let i = schritte.lastIndex(where: { $0.id == s.id }) {
            schritte[i] = s
        } else {
            schritte.append(s)
            if schritte.count > LiveGrenzen.spurLaenge { schritte.removeFirst(schritte.count - LiveGrenzen.spurLaenge) }
        }
    }

    /// Der Schritt, der gerade läuft (der jüngste, falls mehrere Sitzungen zugleich arbeiten).
    public var laufend: AgentSchritt? { schritte.last { $0.stand == .laeuft } }
}
