import Foundation
import OCCTSwiftViewport
import simd

/// Statik (PROTOCOL.md Abschnitt „Statik“): STATICS übernehmen, gewähltes Szenario im Viewer als Farbverlauf der
/// Ausnutzung an Teilen und Stäben (wie die Färbung beim Versionsvergleich) und mit überhöhter Verformung als Geist.
extension AppController: StatikActions {
    func applyStatik(_ e: StatikErgebnis) {
        let s = model.statik
        let alt = s.auswahl
        s.ergebnis = e
        if e.zeigen, let a = e.aktiv, e.szenario(a) != nil {
            // Der Agent will das Szenario sehen (szenario_rechnen, statik(szenario))
            s.auswahl = a
            s.farbverlauf = true
            s.verformung = true
        } else if alt == nil || e.szenario(alt) == nil {
            s.auswahl = nil
        }
        if e.stand == "failed", let m = e.meldung { log(.warning, "Statik: \(m)") }
        updateStatikAnzeige()
    }

    /// Körper und Färbung des gewählten Szenarios in die Szene (oder entfernen, wenn beides aus ist).
    func updateStatikAnzeige() {
        let s = model.statik
        guard let sz = s.szenario, s.farbverlauf || s.verformung else {
            if !scene.statikBodies.isEmpty || !scene.statikTints.isEmpty { scene.setStatik(bodies: [], tints: [:]) }
            return
        }
        let toene = s.farbverlauf ? StatikGeometrie.toene(sz, bekannt: { self.scene.record($0) != nil }) : [:]
        scene.setStatik(
            bodies: StatikGeometrie.koerper(sz, farbverlauf: s.farbverlauf, verformung: s.verformung), tints: toene)
    }

    // MARK: StatikActions

    public func waehleStatikSzenario(_ name: String) {
        model.statik.auswahl = name
        model.statik.farbverlauf = true
        updateStatikAnzeige()
    }

    public func setStatikFarbverlauf(_ an: Bool) {
        model.statik.farbverlauf = an
        updateStatikAnzeige()
    }

    public func setStatikVerformung(_ an: Bool) {
        model.statik.verformung = an
        updateStatikAnzeige()
    }

    public func zeigeStatikUrteil(_ urteil: StatikUrteil) {
        if let teil = urteil.teil, scene.record(teil) != nil { select([teil]) }
        if let ort = urteil.ort {
            let r = SIMD3<Float>(repeating: 120)
            viewport.fit(BoundingBox(min: ort - r, max: ort + r), animated: true)
        } else if let teil = urteil.teil, scene.record(teil) != nil {
            focus(on: [teil])
        }
    }
}
