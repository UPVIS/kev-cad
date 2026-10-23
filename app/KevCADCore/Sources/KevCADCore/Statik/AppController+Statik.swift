import Foundation
import OCCTSwiftViewport
import simd

/// Statik (PROTOCOL.md Abschnitt „Statik“): STATICS übernehmen, gewähltes Szenario im Viewer als Farbverlauf der
/// Ausnutzung an Teilen und Stäben (wie die Färbung beim Versionsvergleich) und mit überhöhter Verformung als Geist.
extension AppController: StatikActions {
    func applyStatik(_ e: StatikErgebnis) {
        let s = model.statik
        let alt = s.auswahl
        if let vorher = s.ergebnis, vorher.run != e.run { s.felder = [:] }  // Stufe 3: Felder gelten je Lauf
        simulationVorherMerken(alt: s.ergebnis, neu: e)  // Simulation: vorheriger Stand je Lastfall (Vergleich)
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
        updateAblaufPfeile()
    }

    /// Statik Stufe 2: Ablauf zum gerade gezeigten Clip der Zeitleiste (Animation „Ablauf: …“), falls es ihn gibt.
    func ablaufZumClip() -> StatikAblauf? {
        guard let name = animationPlayer.current?.name, model.animation.posed else { return nil }
        return model.statik.ergebnis?.szenarien.compactMap(\.ablauf).first { $0.animation == name }
    }

    /// Kontaktkräfte des aktuellen Bilds als Pfeile, solange ein Ablauf in der Zeitleiste steht.
    func updateAblaufPfeile() {
        guard model.statik.kontaktpfeile, let ab = ablaufZumClip(), !ab.pfeile.isEmpty else {
            scene.setAblauf(bodies: [])
            return
        }
        let k = ab.bild(zur: model.animation.time)
        let bild = k < ab.pfeile.count ? ab.pfeile[k] : []
        scene.setAblauf(bodies: StatikGeometrie.pfeile(bild, kraftMax: ab.kraftMax))
    }

    /// Stufe 3: Feld eines Teils übernehmen (STATICS_FIELD); gezeigt wird es, sobald STATICS denselben Schlüssel nennt.
    func applyStatikFeld(_ f: StatikFeld) {
        let s = model.statik
        if let e = s.ergebnis, e.run != f.run { return }
        s.felder[f.key] = f
        updateStatikAnzeige()
    }

    /// Körper und Färbung des gewählten Szenarios in die Szene (oder entfernen, wenn beides aus ist). Stufe 3: Teile
    /// mit Festkörper-Feld zeigen statt der Teilfarbe den Farbverlauf auf ihrem Netz (das Teil selbst ist dann
    /// ausgeblendet) und ihre Verformung als Geist.
    func updateStatikAnzeige() {
        let s = model.statik
        guard let sz = s.szenario, s.farbverlauf || s.verformung else {
            if !scene.statikBodies.isEmpty || !scene.statikTints.isEmpty || !scene.statikVerdeckt.isEmpty {
                scene.setStatik(bodies: [], tints: [:])
            }
            return
        }
        var toene = s.farbverlauf ? StatikGeometrie.toene(sz, bekannt: { self.scene.record($0) != nil }) : [:]
        var koerper = StatikGeometrie.koerper(sz, farbverlauf: s.farbverlauf, verformung: s.verformung)
        // Lasten als Pfeile zum Angriffspunkt, Kraftpaare als zwei gegeneinander gerichtete Pfeile (violett)
        if s.farbverlauf { koerper += StatikGeometrie.lastpfeile(sz.lasten) }
        var verdeckt: Set<String> = []
        for (i, f) in s.felder(fuer: sz).enumerated() where scene.record(f.teil) != nil {
            if s.farbverlauf {
                koerper += StatikFeldGeometrie.farbverlauf(f, id: "\(i)")
                verdeckt.insert(f.teil)
                toene.removeValue(forKey: f.teil)
            }
            if s.verformung { koerper += StatikFeldGeometrie.verformung(f, id: "\(i)") }
        }
        scene.setStatik(bodies: koerper, tints: toene, verdeckt: verdeckt)
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

    public func zeigeAblauf(_ szenario: String) {
        guard let ab = model.statik.ergebnis?.szenario(szenario)?.ablauf, let name = ab.animation,
              animationPlayer.clips[name] != nil
        else {
            log(.warning, "Ablauf „\(szenario)“ ist noch nicht gerechnet")
            return
        }
        model.statik.auswahl = szenario
        selectAnimation(name)
        seekAnimation(to: 0)
        setPlaying(true)
    }

    public func setKontaktpfeile(_ an: Bool) {
        model.statik.kontaktpfeile = an
        updateAblaufPfeile()
    }

    public func festkoerperAbbrechen() {
        if !send(StatikAbbrechenMessage()) { log(.warning, "Festkörper: keine Verbindung zum Kernel") }
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
