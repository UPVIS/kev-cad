import Foundation
import simd

// Zwangsbedingungen im App-Kern: Bericht übernehmen (CONSTRAINTS), Symbole am Teil in die Überlagerung zeichnen
// (verletzte rot und gefüllt, erfüllte als Umriss), Bedingung im Viewer zeigen, Symbole ein- und ausblenden.

extension AppController: ConstraintActions {
    static let constraintOK = SIMD4<Float>(0.16, 0.42, 0.75, 1)
    static let constraintError = SIMD4<Float>(0.86, 0.16, 0.16, 1)
    static let constraintWarning = SIMD4<Float>(0.93, 0.55, 0.1, 1)
    static let constraintUnchecked = SIMD4<Float>(0.5, 0.5, 0.52, 1)
    /// Höchstens so viele Symbole (große Baugruppen bleiben lesbar und schnell).
    static let maxConstraintSymbols = 400

    /// Zeichen je Art der Bedingung (wie die Symbole in CAD-Programmen).
    public static func constraintGlyph(_ symbol: String) -> String {
        switch symbol {
        case "auf": return "⊤"
        case "buendig": return "≡"
        case "konzentrisch": return "◎"
        case "parallel": return "∥"
        case "senkrecht": return "⊥"
        case "abstand": return "↔"
        case "winkel": return "∠"
        case "tangential": return "◠"
        case "mittig": return "⊕"
        case "in_bohrung": return "⌀"
        case "drehgelenk": return "⟲"
        case "schiebegelenk": return "⇄"
        case "zylindergelenk": return "⟳"
        case "kugelgelenk": return "●"
        case "fest": return "▣"
        case "verbinde": return "⊶"
        case "gleich": return "="
        case "spiel", "min_abstand": return "↕"
        case "min_wand": return "▯"
        case "param": return "P"
        default: return "?"
        }
    }

    static func constraintColor(_ item: ConstraintItem) -> SIMD4<Float> {
        switch item.stand {
        case .erfuellt: return constraintOK
        case .ungeprueft: return constraintUnchecked
        case .verletzt: return (item.schwere ?? .fehler) == .fehler ? constraintError : constraintWarning
        }
    }

    func applyConstraints(_ report: ConstraintReport) {
        model.constraints = report
        refreshOverlay()
        let s = report.summary
        if s.gesamt > 0 || s.fehler > 0 {
            log(s.fehler > 0 ? .warning : .info,
                "Bedingungen zu Lauf \(report.run): \(s.gesamt) gesamt, \(s.erfuellt) erfüllt, \(s.verletzt) verletzt"
                    + (s.fehler > 0 ? ", \(s.fehler) Befunde mit Fehler" : ""))
        }
        for f in report.findings where f.schwere == .fehler {
            log(.warning, f.text)
        }
    }

    /// Symbole der Bedingungen (nur sichtbare Teile) und Befunde ohne eigene Bedingung (Bewegungsraum, Befestigung).
    func constraintOverlay() -> [OverlayPrimitive] {
        guard model.showConstraintSymbols, let report = model.constraints else { return [] }
        let known = Set(scene.order)
        func sichtbar(_ teile: [String]) -> Bool {
            let vorhanden = teile.filter { known.contains($0) }
            return vorhanden.isEmpty ? true : vorhanden.contains { scene.isVisible($0) }
        }
        var out: [OverlayPrimitive] = []
        var count = 0
        // verletzte zuerst, damit sie bei vielen Bedingungen sicher zu sehen sind
        let sorted = report.items.sorted { ($0.stand == .verletzt ? 0 : 1) < ($1.stand == .verletzt ? 0 : 1) }
        for item in sorted {
            guard count < Self.maxConstraintSymbols, let p = item.punkte.first, sichtbar(item.teile) else { continue }
            let color = Self.constraintColor(item)
            if item.stand == .verletzt, item.punkte.count >= 2, simd_distance(item.punkte[0], item.punkte[1]) > 1e-3 {
                out.append(.polyline(points: [item.punkte[0], item.punkte[1]], color: color, width: 1.5))
            }
            out.append(.badge(point: p, text: Self.constraintGlyph(item.symbol), color: color,
                              filled: item.stand == .verletzt))
            count += 1
        }
        for f in report.findings where f.bedingung == nil && f.schwere != .hinweis {
            guard count < Self.maxConstraintSymbols, let p = f.ort, sichtbar(f.teile) else { continue }
            out.append(.badge(point: p, text: "!", color: f.schwere == .fehler ? Self.constraintError
                                : Self.constraintWarning, filled: true))
            count += 1
        }
        for f in report.findings where f.pruefung == "bewegungsraum" && f.bedingung != nil && f.schwere == .fehler {
            guard count < Self.maxConstraintSymbols, let p = f.ort, sichtbar(f.teile) else { continue }
            out.append(.badge(point: p, text: "!", color: Self.constraintError, filled: true))
            count += 1
        }
        return out
    }

    public func setConstraintSymbolsVisible(_ on: Bool) {
        model.showConstraintSymbols = on
        refreshOverlay()
    }

    public func showConstraint(_ id: String) {
        guard let item = model.constraints?.items.first(where: { $0.id == id }) else { return }
        let refs = item.teile.compactMap(ElementRef.init).map(\.partRef)
        let known = scene.expand(refs).known
        guard !known.isEmpty else {
            log(.info, "Bedingung \(id): beteiligte Teile sind nicht in der Szene")
            return
        }
        let hidden = known.map(\.part).filter { !scene.isVisible($0) }
        if !hidden.isEmpty { setVisibility(hidden, visible: true) }
        applySelection(known)
        if let b = scene.worldBounds(of: known) { viewport.fit(b, animated: true) }
        if !model.showConstraintSymbols { setConstraintSymbolsVisible(true) }
    }
}
