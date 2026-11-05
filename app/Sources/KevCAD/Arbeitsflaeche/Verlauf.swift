import Combine
import Foundation
import KevCADCore

/// Parameter des Modells (`param()` in model.py) mit dem Wert vor dem letzten Lauf: Was sich im letzten Lauf geändert
/// hat (durch Kevin in der Werkstatt oder durch den Agenten), zeigt die Werkstatt mit „vorher …“.
@MainActor
final class ParameterVerlauf: ObservableObject {
    @Published private(set) var werte: [String: Double] = [:]
    @Published private(set) var vorher: [String: Double] = [:]
    private var projekt: String?
    private var abos: Set<AnyCancellable> = []

    func beobachten(_ model: AppModel) {
        guard abos.isEmpty else { return }
        werte = model.referenzen.params
        projekt = model.project?.path.path
        model.referenzen.$params
            .receive(on: DispatchQueue.main)
            .sink { [weak self] p in self?.uebernehmen(p) }
            .store(in: &abos)
        model.$project
            .map { $0?.path.path }
            .removeDuplicates()
            .sink { [weak self] p in
                guard let self, p != self.projekt else { return }
                self.projekt = p
                self.werte = [:]
                self.vorher = [:]
            }
            .store(in: &abos)
    }

    /// Neue Werte eines Laufs: geändert ist, was es vorher schon gab und jetzt anders ist.
    func uebernehmen(_ neu: [String: Double]) {
        var v: [String: Double] = [:]
        for (k, alt) in werte {
            if let n = neu[k], abs(n - alt) > 1e-9 { v[k] = alt }
        }
        if v != vorher { vorher = v }
        if neu != werte { werte = neu }
    }

    /// Namen, sortiert wie in model.py meist gemeint: zuerst die geänderten, dann alphabetisch.
    var namen: [String] {
        werte.keys.sorted { a, b in
            let va = vorher[a] != nil, vb = vorher[b] != nil
            if va != vb { return va }
            return a.localizedStandardCompare(b) == .orderedAscending
        }
    }
}

/// Ein Schritt der Agentenspur.
struct SpurEintrag: Identifiable, Equatable {
    enum Art: Equatable { case fertig, jetzt, befund, info }

    let id = UUID()
    var text: String
    var zeit: Date
    var art: Art
}

/// Agentenspur bis V2-5: entsteht aus der Tätigkeitszeile des Agenten (`AppModel.agentActivity`), dem Ende jedes
/// Laufs und den Befunden der Prüfung. V2-5 ersetzt das durch echte Schritte mit Zeiten.
@MainActor
final class AgentenSpur: ObservableObject {
    static let hoechstens = 6

    @Published private(set) var eintraege: [SpurEintrag] = []
    private var abos: Set<AnyCancellable> = []

    /// Was der Agent gerade tut (für die schmale Ansicht).
    var jetzt: SpurEintrag? { eintraege.last { $0.art == .jetzt } }

    func beobachten(_ model: AppModel) {
        guard abos.isEmpty else { return }
        model.$agentActivity
            .removeDuplicates()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] t in self?.taetigkeit(t) }
            .store(in: &abos)
        model.$run
            .removeDuplicates()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] r in self?.lauf(r) }
            .store(in: &abos)
        model.$pruefung
            .map { p -> String? in
                guard let p, !p.bandText.isEmpty else { return nil }
                return p.bandText
            }
            .removeDuplicates()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] t in if let t { self?.dazu(SpurEintrag(text: "Prüfung: \(t)", zeit: Date(), art: .befund)) } }
            .store(in: &abos)
        model.$project
            .map { $0?.path.path }
            .removeDuplicates()
            .dropFirst()
            .sink { [weak self] _ in self?.eintraege = [] }
            .store(in: &abos)
    }

    private func taetigkeit(_ t: String?) {
        var e = eintraege
        if let i = e.lastIndex(where: { $0.art == .jetzt }) { e[i].art = .fertig }
        if let t, !t.isEmpty {
            e.append(SpurEintrag(text: Self.satzAnfang(t), zeit: Date(), art: .jetzt))
        }
        eintraege = Array(e.suffix(Self.hoechstens))
    }

    private func lauf(_ r: RunState) {
        switch r {
        case .finished(let run, let ms, let teile, _):
            guard teile > 0 else { return }  // der Lauf eines leeren Projekts sagt nichts
            let dauer = ms >= 1000 ? String(format: "%.1f s", Double(ms) / 1000).replacingOccurrences(of: ".", with: ",")
                : "\(ms) ms"
            dazu(SpurEintrag(text: "Lauf \(run) fertig: \(KevFormat.count(teile, one: "Teil", many: "Teile")), \(dauer)",
                             zeit: Date(), art: .info))
        case .failed(let run, let message, let line, _):
            guard !message.contains("anderes Projekt") else { return }  // abgebrochen, kein Fehler
            let wo = line.map { " in Zeile \($0)" } ?? ""
            dazu(SpurEintrag(text: "Lauf \(run): Fehler\(wo): \(message)", zeit: Date(), art: .befund))
        default:
            break
        }
    }

    private func dazu(_ e: SpurEintrag) {
        var neu = eintraege
        // Der laufende Schritt bleibt der letzte
        if let i = neu.lastIndex(where: { $0.art == .jetzt }) {
            neu.insert(e, at: i)
        } else {
            neu.append(e)
        }
        eintraege = Array(neu.suffix(Self.hoechstens))
    }

    /// „rechnet model.py“ wird „Rechnet model.py“.
    static func satzAnfang(_ t: String) -> String {
        guard let first = t.first else { return t }
        return first.uppercased() + t.dropFirst()
    }
}
