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

/// Eine Zeile der Agentenspur.
struct SpurEintrag: Identifiable, Equatable {
    enum Art: Equatable { case fertig, jetzt, befund, info }

    var id = UUID().uuidString
    var text: String
    var zeit: Date
    var art: Art
    /// Dauer eines fertigen Schritts (Text); ein laufender zählt ab `zeit`.
    var dauer: String?
    /// Was das Werkzeug tut, wenn `text` die Absicht des Agenten ist (Hilfetext).
    var werkzeug: String?
}

/// Agentenspur: die Schritte des Agenten mit Zeiten (V2-5, `AppModel.agentenspur`), dazu das Ende jedes Laufs und die
/// Befunde der Prüfung. Ältere Kernel melden keine Schritte; dann entsteht sie aus der Tätigkeitszeile
/// (`AppModel.agentActivity`).
@MainActor
final class AgentenSpur: ObservableObject {
    static let hoechstens = 6

    @Published private(set) var eintraege: [SpurEintrag] = []
    private var abos: Set<AnyCancellable> = []
    /// Lauf-Ende und Befunde, zwischen die Schritte einsortiert (nach Zeit)
    private var ereignisse: [SpurEintrag] = []
    private var schritte: [AgentSchritt] = []
    /// Tätigkeitszeile, falls der Kernel keine Schritte meldet
    private var zeilen: [SpurEintrag] = []

    /// Was der Agent gerade tut (für die schmale Ansicht).
    var jetzt: SpurEintrag? { eintraege.last { $0.art == .jetzt } }

    func beobachten(_ model: AppModel) {
        guard abos.isEmpty else { return }
        model.agentenspur.$schritte
            .removeDuplicates()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] s in
                self?.schritte = s
                self?.neuAufbauen()
            }
            .store(in: &abos)
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
            .sink { [weak self] _ in
                guard let self else { return }
                self.ereignisse = []
                self.zeilen = []
                self.neuAufbauen()
            }
            .store(in: &abos)
    }

    private func taetigkeit(_ t: String?) {
        var e = zeilen
        if let i = e.lastIndex(where: { $0.art == .jetzt }) { e[i].art = .fertig }
        if let t, !t.isEmpty {
            e.append(SpurEintrag(text: Self.satzAnfang(t), zeit: Date(), art: .jetzt))
        }
        zeilen = Array(e.suffix(Self.hoechstens))
        neuAufbauen()
    }

    private func lauf(_ r: RunState) {
        switch r {
        case .finished(let run, let ms, let teile, _):
            guard teile > 0 else { return }  // der Lauf eines leeren Projekts sagt nichts
            guard !schritte.contains(where: { $0.phasen?["run"]?.intValue == run }) else { return }  // steht schon im Schritt
            dazu(SpurEintrag(text: "Lauf \(run) fertig: \(KevFormat.count(teile, one: "Teil", many: "Teile")), \(Self.dauerText(Double(ms)))",
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
        ereignisse = Array((ereignisse + [e]).suffix(Self.hoechstens))
        neuAufbauen()
    }

    /// Schritte und Ereignisse nach Zeit, der laufende Schritt bleibt der letzte.
    private func neuAufbauen() {
        let eigene = schritte.compactMap(Self.eintrag)
        let basis = (schritte.isEmpty ? zeilen : eigene) + ereignisse
        let sortiert = basis.sorted { a, b in
            if (a.art == .jetzt) != (b.art == .jetzt) { return b.art == .jetzt }
            return a.zeit < b.zeit
        }
        let neu = Array(sortiert.suffix(Self.hoechstens))
        if neu != eintraege { eintraege = neu }
    }

    /// Ein Schritt als Zeile: Absicht vor der Beschreibung. Abfragen ohne Text bleiben knapp außen vor.
    static func eintrag(_ s: AgentSchritt) -> SpurEintrag? {
        guard let text = s.absicht ?? s.text ?? s.fehler else { return nil }
        let art: SpurEintrag.Art
        switch s.stand {
        case .laeuft: art = .jetzt
        case .ok: art = .fertig
        case .fehler: art = .befund
        }
        return SpurEintrag(
            id: s.id, text: satzAnfang(s.stand == .fehler ? s.fehler ?? text : text), zeit: Date(timeIntervalSince1970: s.beginn),
            art: art, dauer: s.dauerMs.map(dauerText), werkzeug: s.absicht == nil ? nil : s.text)
    }

    /// „2,3 s“ bzw. „640 ms“.
    static func dauerText(_ ms: Double) -> String {
        ms >= 1000 ? String(format: "%.1f s", ms / 1000).replacingOccurrences(of: ".", with: ",") : "\(Int(ms.rounded())) ms"
    }

    /// „rechnet model.py“ wird „Rechnet model.py“.
    static func satzAnfang(_ t: String) -> String {
        guard let first = t.first else { return t }
        return first.uppercased() + t.dropFirst()
    }
}
