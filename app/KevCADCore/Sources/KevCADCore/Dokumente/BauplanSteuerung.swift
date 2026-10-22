import Foundation
import OCCTSwiftViewport
import QuartzCore
import simd

/// Zustand des Durchspielens im App-Kern (Uhr, gesicherte Explosion, abgelaufene Pause).
@MainActor
final class BauplanLaufzeit {
    var timer: Timer?
    var letzterTakt: CFTimeInterval = 0
    var pauseBis: CFTimeInterval = 0
    var explosionVorher: Double = 0
    var animationVorher: Bool = false
}

/// Bauplan (DOKUMENTE.md, Strang P6-A2): BAUPLAN in den BauplanStore, Anfragen und Änderungen der Oberfläche an den
/// Kernel (BAUPLAN_REQ, BAUPLAN_EDIT mit `von: "kevin"`, BAUPLAN_PRUEFEN), Durchspielen im 3D-Bereich (nur montierte
/// Teile sichtbar, neue fahren ein, Kamera wie im Schrittbild) und Sprung zu einem Befund.
extension AppController: BauplanActions {
    static let bauplanNeuFarbe = SIMD4<Float>(1.0, 0.42, 0.05, 1)

    var bauplanLaufzeit: BauplanLaufzeit { model.bauplan.laufzeit }

    func handleBauplan(_ m: BauplanNachricht) {
        let store = model.bauplan
        if let t = store.angefordert { store.antwortMs = Date().timeIntervalSince(t) * 1000 }
        store.angefordert = nil
        store.plan = m.plan
        var bilder: [String: BauplanStrichbild] = [:]
        for b in m.bilder { bilder[b.schritt] = b }
        store.bilder = bilder
        store.laedt = false
        if let d = store.durchspielen {
            // neuer Plan während des Durchspielens: Schritte neu, Stelle möglichst behalten
            let schritte = BauplanAblauf.schritte(m.plan)
            let idx = d.schritt.flatMap { schritte.firstIndex(of: $0) } ?? min(d.index, max(0, schritte.count - 1))
            store.durchspielen = schritte.isEmpty ? nil
                : BauplanDurchspielen(schritte: schritte, index: idx, fortschritt: d.fortschritt, spielt: d.spielt,
                                      tempo: d.tempo)
            durchspielenAnwenden(neuerSchritt: false)
        }
        log(.info, "Bauplan: \(m.plan.alleSchritte.count) Schritte, \(m.bilder.count) Bilder"
            + (m.plan.fehlerAnzahl > 0 ? ", \(m.plan.fehlerAnzahl) Fehler aus der Simulation" : ""))
    }

    /// Nach DOCS: hat sich der Bauplan geändert (neuer Lauf), wird ein schon geladener Plan neu angefordert.
    func bauplanNachDocs(_ m: DokumenteMessage) {
        guard case .docs(let d, _) = m, let kurz = d.bauplan, let plan = model.bauplan.plan,
              !model.bauplan.laedt
        else { return }
        let run = kurz.json["run"]?.intValue
        let schritte = kurz.schritte
        if (run != nil && run != plan.run) || schritte != plan.alleSchritte.count
            || kurz.fehler != plan.fehlerAnzahl
        {
            bauplanAnfordern()
        }
    }

    /// Projektwechsel: Plan des alten Projekts verwerfen, Durchspielen beenden.
    func resetBauplan() {
        if model.bauplan.durchspielen != nil { durchspielenBeenden() }
        model.bauplan.leeren()
    }

    // MARK: Anfragen

    public func bauplanAnfordern() {
        let store = model.bauplan
        guard !store.laedt else { return }
        store.laedt = true
        store.angefordert = Date()
        request(BauplanAnfrageMessage(id: nextRequestID()), timeout: 300) { [weak self] result in
            guard let self else { return }
            let store = self.model.bauplan
            store.laedt = false
            switch result {
            case .success(.bauplan(let m)):
                self.handleBauplan(m)
            case .success(let m):
                self.log(.warning, "Bauplan: unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                store.meldung = BauplanMeldung(text: e.message, fehler: true)
                self.log(.error, "Bauplan laden: \(e.message)")
            }
        }
    }

    public func bauplanBearbeiten(_ ops: [JSONValue], titel: String) {
        guard !ops.isEmpty else { return }
        let store = model.bauplan
        store.arbeitet = titel
        request(BauplanBearbeitenMessage(id: nextRequestID(), ops: ops, von: "kevin"), timeout: 180) { [weak self] r in
            guard let self else { return }
            let store = self.model.bauplan
            store.arbeitet = nil
            switch r {
            case .success(.ack(let a)) where a.ok:
                store.meldung = BauplanMeldung(text: a.message?.isEmpty == false ? a.message! : titel)
            case .success(.ack(let a)):
                store.meldung = BauplanMeldung(text: a.message ?? "\(titel): abgelehnt", fehler: true)
                self.log(.warning, "Bauplan, \(titel): \(a.message ?? "abgelehnt")")
            case .success(let m):
                store.meldung = BauplanMeldung(text: "Unerwartete Antwort \(m.typeName)", fehler: true)
            case .failure(let e):
                store.meldung = BauplanMeldung(text: "\(titel): \(e.message)", fehler: true)
                self.log(.error, "Bauplan, \(titel): \(e.message)")
            }
        }
    }

    public func bauplanPruefen(schritt: String?) {
        let store = model.bauplan
        store.arbeitet = schritt == nil ? "Prüft alle Schritte" : "Prüft den Schritt"
        request(BauplanPruefenMessage(id: nextRequestID(), schritt: schritt), timeout: 300) { [weak self] r in
            guard let self else { return }
            let store = self.model.bauplan
            store.arbeitet = nil
            switch r {
            case .success(.ack(let a)) where !a.ok:
                store.meldung = BauplanMeldung(text: a.message ?? "Prüfung abgelehnt", fehler: true)
            case .failure(let e):
                store.meldung = BauplanMeldung(text: e.message, fehler: true)
            default:
                store.meldung = BauplanMeldung(text: "Simulation neu gerechnet")
            }
        }
    }

    // MARK: Zeigen

    public func bauplanZeigen(teile: [String], ort: SIMD3<Float>?) {
        let refs = teile.compactMap(ElementRef.init).filter { scene.record($0.part) != nil }
        if model.bauplan.durchspielen == nil { scene.setAnimationPose([:]) }
        applySelection(refs)
        scene.addHighlight(refs: refs, color: Self.bauplanNeuFarbe, label: nil, clear: true)
        if let ort {
            let r = SIMD3<Float>(repeating: 60)
            viewport.fit(BoundingBox(min: ort - r, max: ort + r), animated: true)
        } else if let b = scene.worldBounds(of: refs) {
            viewport.fit(b, animated: true, padding: 1.6)
        }
        model.bauplan.zeige3D += 1
    }

    // MARK: Durchspielen

    public func durchspielenStarten(ab schritt: String?) {
        guard let plan = model.bauplan.plan else {
            bauplanAnfordern()
            return
        }
        let schritte = BauplanAblauf.schritte(plan)
        guard !schritte.isEmpty else {
            model.bauplan.meldung = BauplanMeldung(text: "Keine Montageschritte zum Durchspielen", fehler: true)
            return
        }
        let lz = bauplanLaufzeit
        if model.bauplan.durchspielen == nil {
            lz.explosionVorher = model.explodeFactor
            lz.animationVorher = model.animation.posed
            animationPlayer.pause()
            if model.explodeFactor != 0 { applyExplode(0) }
        }
        let idx = schritt.flatMap { schritte.firstIndex(of: $0) } ?? 0
        model.bauplan.durchspielen = BauplanDurchspielen(schritte: schritte, index: idx, fortschritt: 0, spielt: false,
                                                          tempo: model.bauplan.durchspielen?.tempo ?? 1)
        model.bauplan.zeige3D += 1
        durchspielenAnwenden(neuerSchritt: true)
        starteUhr()
    }

    public func durchspielenSchritt(_ delta: Int) {
        guard let d = model.bauplan.durchspielen else { return }
        durchspielenGeheZu(d.index + delta)
    }

    public func durchspielenGeheZu(_ index: Int) {
        guard var d = model.bauplan.durchspielen, !d.schritte.isEmpty else { return }
        let neu = min(max(0, index), d.schritte.count - 1)
        if neu == d.index && d.fortschritt >= 1 {
            d.fortschritt = 0  // denselben Schritt noch einmal einfahren
        } else {
            d.index = neu
            d.fortschritt = 0
        }
        model.bauplan.durchspielen = d
        durchspielenAnwenden(neuerSchritt: true)
        starteUhr()
    }

    public func durchspielenAbspielen(_ an: Bool) {
        guard var d = model.bauplan.durchspielen else { return }
        if an && d.istLetzter && d.fortschritt >= 1 {
            d.index = 0
            d.fortschritt = 0
            d.spielt = true
            model.bauplan.durchspielen = d
            durchspielenAnwenden(neuerSchritt: true)
        } else {
            d.spielt = an
            model.bauplan.durchspielen = d
        }
        starteUhr()
    }

    public func durchspielenTempo(_ tempo: Double) {
        guard var d = model.bauplan.durchspielen else { return }
        d.tempo = min(4, max(0.25, tempo))
        model.bauplan.durchspielen = d
    }

    public func durchspielenBeenden() {
        let lz = bauplanLaufzeit
        lz.timer?.invalidate()
        lz.timer = nil
        guard model.bauplan.durchspielen != nil else { return }
        model.bauplan.durchspielen = nil
        scene.clearHighlights()
        scene.setAnimationPose([:])
        if lz.animationVorher { animationPlayer.seek(to: model.animation.time) }
        if lz.explosionVorher != 0 { applyExplode(lz.explosionVorher) }
        viewport.fit(scene.visibleBounds(), animated: true)
        refreshOverlay()
    }

    private func starteUhr() {
        let lz = bauplanLaufzeit
        lz.letzterTakt = CACurrentMediaTime()
        guard lz.timer == nil else { return }
        let t = Timer(timeInterval: 1.0 / 60, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.durchspielenTakt() }
        }
        RunLoop.main.add(t, forMode: .common)
        lz.timer = t
    }

    private func durchspielenTakt() {
        let lz = bauplanLaufzeit
        let jetzt = CACurrentMediaTime()
        let dt = min(0.1, jetzt - lz.letzterTakt)
        lz.letzterTakt = jetzt
        guard var d = model.bauplan.durchspielen else {
            lz.timer?.invalidate()
            lz.timer = nil
            return
        }
        if d.fortschritt < 1 {
            d.fortschritt = min(1, d.fortschritt + dt * d.tempo / 1.6)
            model.bauplan.durchspielen = d
            durchspielenAnwenden(neuerSchritt: false)
            if d.fortschritt >= 1 { lz.pauseBis = jetzt + 0.9 / d.tempo }
            return
        }
        guard d.spielt else {
            lz.timer?.invalidate()  // steht: Uhr aus, bis wieder etwas passiert
            lz.timer = nil
            return
        }
        guard jetzt >= lz.pauseBis else { return }
        if d.istLetzter {
            d.spielt = false
            model.bauplan.durchspielen = d
            return
        }
        d.index += 1
        d.fortschritt = 0
        model.bauplan.durchspielen = d
        durchspielenAnwenden(neuerSchritt: true)
    }

    /// Lage, Sichtbarkeit, Hervorhebung und (bei neuem Schritt) Kamera aus dem Stand des Durchspielens.
    func durchspielenAnwenden(neuerSchritt: Bool) {
        guard let d = model.bauplan.durchspielen, let id = d.schritt, let plan = model.bauplan.plan,
              let pose = BauplanAblauf.pose(plan, schritt: id, fortschritt: d.fortschritt)
        else { return }
        var transforms: [String: simd_float4x4] = [:]
        for (teil, v) in pose.versatz where scene.record(teil) != nil {
            var m = matrix_identity_float4x4
            m.columns.3 = SIMD4(v.x, v.y, v.z, 1)
            transforms[teil] = m
        }
        let hidden = Set(scene.order.filter { !pose.sichtbar.contains($0) })
        scene.setAnimationPose(transforms, hidden: hidden)
        if neuerSchritt {
            let refs = pose.neu.filter { scene.record($0) != nil }.sorted().map { ElementRef.part($0) }
            scene.addHighlight(refs: refs, color: Self.bauplanNeuFarbe, label: nil, clear: true)
            var bounds: BoundingBox?
            if let lo = pose.ausschnittMin, let hi = pose.ausschnittMax {
                bounds = BoundingBox(min: simd_min(lo, hi), max: simd_max(lo, hi))
            } else {
                bounds = scene.worldBounds(of: pose.sichtbar.map { ElementRef.part($0) })
            }
            viewport.apply(rotation: pose.rotation, orthographic: true, fitTo: bounds, animated: true)
        }
        refreshOverlay()
    }
}
