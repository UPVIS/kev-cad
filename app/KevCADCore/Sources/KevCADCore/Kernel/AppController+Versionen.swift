import Foundation
import OCCTSwiftViewport
import QuartzCore
import simd

/// Versionen (PROTOCOL.md Abschnitt „Versionen“): Liste übernehmen, Vergleich mit Geisterkörpern und Färbung zeigen,
/// Vorschaubilder für den Kernel rendern, Aktionen der Versionsleiste an den Kernel schicken.
extension AppController: VersionenActions {
    /// Alte Form eines geänderten Teils: blau, durchscheinend, obenauf (linear).
    static let vergleichAltFarbe = SIMD4<Float>(0.10, 0.32, 0.95, 0.30)
    /// Entferntes Teil der alten Version: rot, durchscheinend.
    static let vergleichWegFarbe = SIMD4<Float>(0.90, 0.05, 0.04, 0.42)
    /// Färbung der aktuellen Teile: geändert orange, neu grün (linear).
    static let vergleichGeaendertFarbe = SIMD3<Float>(1.00, 0.36, 0.00)
    static let vergleichNeuFarbe = SIMD3<Float>(0.05, 0.62, 0.12)
    static let vergleichPrefix = "\u{1F}vergleich\u{1F}"

    func handleVersionen(_ m: VersionMessage) {
        switch m {
        case .liste(let s, _): applyVersionen(s)
        case .vergleich(let v, _): applyVergleich(v)
        case .bildAnfrage(let b): answerVersionBild(b)
        }
    }

    /// Projektwechsel: Vergleich und Liste des alten Projekts verwerfen.
    func resetVersionen() {
        model.versionen.stand = nil
        model.versionen.vergleich = nil
        model.versionen.vergleichLaeuft = nil
        model.versionen.arbeitet = nil
        scene.setVergleich(bodies: [], tints: [:])
    }

    func applyVersionen(_ s: VersionenStand) {
        if let p = model.project, !s.projekt.isEmpty,
            URL(fileURLWithPath: s.projekt).resolvingSymlinksInPath().path != p.path.resolvingSymlinksInPath().path
        {
            return  // Liste eines anderen (alten) Projekts
        }
        let alt = model.versionen.stand
        if !s.verfuegbar, let m = s.meldung, alt?.meldung != m { log(.warning, m) }
        if let alt, alt.variante != s.variante, let v = s.aktuelleVariante {
            log(.info, "Variante \(v.name) aktiv")
        }
        if let neu = s.aktuelleVersion, let a = alt?.aktuelleVersion, neu.nr > a.nr, alt?.variante == s.variante {
            log(.info, "Version V\(neu.nr): \(neu.anzeigeTitel)")
        }
        model.versionen.stand = s
    }

    func applyVergleich(_ v: VersionVergleich) {
        model.versionen.vergleich = v
        model.versionen.vergleichLaeuft = nil
        updateVergleichAnzeige()
        log(.info, "Vergleich \(v.a.kurz) → \(v.b.kurz): \(v.zusammenfassung) (\(v.ms) ms)")
    }

    /// Geisterkörper und Färbung aus dem aktuellen Vergleich (nur, wenn mit dem aktuellen Stand verglichen wird).
    func updateVergleichAnzeige() {
        guard let v = model.versionen.vergleich, v.aktuell else {
            scene.setVergleich(bodies: [], tints: [:])
            return
        }
        var tints: [String: SIMD3<Float>] = [:]
        for t in v.teileGeaendert where scene.record(t.name) != nil { tints[t.name] = Self.vergleichGeaendertFarbe }
        for n in v.teileNeu where scene.record(n) != nil { tints[n] = Self.vergleichNeuFarbe }
        scene.setVergleich(bodies: Self.vergleichKoerper(v), tints: tints)
    }

    static func vergleichKoerper(_ v: VersionVergleich) -> [ViewportBody] {
        v.geometrie.enumerated().compactMap { i, n in
            guard n.triangleCount > 0 else { return nil }
            return ViewportBody(
                id: vergleichPrefix + String(i), vertexData: interleaved(n), indices: n.triangles, edges: n.edgeLines,
                color: n.art == "weg" ? vergleichWegFarbe : vergleichAltFarbe, roughness: 0.6, isPickable: false,
                renderLayer: .overlay)
        }
    }

    /// Punkte und Normalen verschränkt, wie ViewportBody sie erwartet.
    static func interleaved(_ n: VergleichsNetz) -> [Float] {
        var vd = [Float]()
        vd.reserveCapacity(n.vertexCount * 6)
        for v in 0..<n.vertexCount {
            vd.append(contentsOf: n.positions[(v * 3)..<(v * 3 + 3)])
            if n.normals.count >= v * 3 + 3 {
                vd.append(contentsOf: n.normals[(v * 3)..<(v * 3 + 3)])
            } else {
                vd.append(contentsOf: [0, 0, 1])
            }
        }
        return vd
    }

    // MARK: Vorschaubild

    /// VERSION_BILD_REQ: die mitgeschickten Netze offscreen aus der Standardansicht rendern (unabhängig von dem, was
    /// gerade im Viewer zu sehen ist) und als SCREENSHOT_RES zurückschicken.
    func answerVersionBild(_ b: VersionBildAnfrage) {
        let w = max(16, min(b.width, 2048)), h = max(16, min(b.height, 2048))
        var lo = SIMD3<Float>(repeating: .greatestFiniteMagnitude)
        var hi = SIMD3<Float>(repeating: -.greatestFiniteMagnitude)
        var bodies: [ViewportBody] = []
        for (i, t) in b.teile.enumerated() where t.netz.triangleCount > 0 {
            let n = t.netz
            for v in 0..<n.vertexCount {
                let p = SIMD3<Float>(n.positions[v * 3], n.positions[v * 3 + 1], n.positions[v * 3 + 2])
                lo = simd_min(lo, p)
                hi = simd_max(hi, p)
            }
            // Der Offscreen-Renderer erwartet sRGB; die Farben aus model.py sind sRGB
            bodies.append(
                ViewportBody(
                    id: "bild\u{1F}\(i)", vertexData: Self.interleaved(n), indices: n.triangles, edges: n.edgeLines,
                    color: SIMD4(t.farbe.x, t.farbe.y, t.farbe.z, 1), roughness: 0.55))
        }
        guard !bodies.isEmpty, lo.x <= hi.x,
            let sv = ViewportCoordinator.standardView(protocolName: b.view)
        else {
            send(
                ScreenshotResponseMessage(
                    replyTo: b.id, ok: false, width: 0, height: 0, camera: .null, mmPerPx: nil,
                    message: "Keine Geometrie für das Vorschaubild"))
            return
        }
        var camera = sv.cameraState(distance: 1000, orthographicScale: 100)
        camera = ViewportCoordinator.fitted(camera, to: BoundingBox(min: lo, max: hi), aspect: Float(w) / Float(h),
                                            padding: 1.05)
        let started = CACurrentMediaTime()
        guard
            let r = screenshots.render(
                bodies: bodies, camera: camera, width: w, height: h, displayMode: .shadedWithEdges,
                lighting: viewport.controller.lightingConfiguration)
        else {
            send(
                ScreenshotResponseMessage(
                    replyTo: b.id, ok: false, width: 0, height: 0, camera: .null, mmPerPx: nil,
                    message: "Vorschaubild ließ sich nicht rendern"))
            return
        }
        let ms = Int((CACurrentMediaTime() - started) * 1000)
        if AppInfo.isTestVariant { log(.info, "Vorschaubild V\(b.nr): \(w) × \(h) in \(ms) ms") }
        send(
            ScreenshotResponseMessage(
                replyTo: b.id, ok: true, width: w, height: h, camera: ViewportCoordinator.cameraJSON(camera, height: h),
                mmPerPx: nil),
            payload: r.png)
    }

    // MARK: VersionenActions

    private func versionRequest<M: OutgoingRequest>(
        _ message: M, arbeitet: String?, timeout: TimeInterval = 120,
        erfolg: @escaping (KernelMessage) -> Void
    ) {
        if let arbeitet { model.versionen.arbeitet = arbeitet }
        request(message, timeout: timeout) { [weak self] result in
            guard let self else { return }
            if arbeitet != nil { self.model.versionen.arbeitet = nil }
            switch result {
            case .success(let m):
                erfolg(m)
            case .failure(let e):
                self.model.versionen.vergleichLaeuft = nil
                self.model.versionen.meldung = VersionenMeldung(text: e.message, fehler: true)
                self.log(.error, "Versionen: \(e.message)")
            }
        }
    }

    private func bestaetige(_ m: KernelMessage) {
        if case .ack(let a) = m {
            model.versionen.meldung = VersionenMeldung(text: a.message ?? (a.ok ? "Erledigt" : "Abgelehnt"), fehler: !a.ok)
            if !a.ok { log(.warning, "Versionen: \(a.message ?? "abgelehnt")") }
        }
    }

    public func requestVersionen() {
        versionRequest(VersionenRequestMessage(id: nextRequestID()), arbeitet: nil, timeout: 60) { [weak self] m in
            if case .versionen(let v) = m { self?.handleVersionen(v) }
        }
    }

    public func restoreVersion(_ nr: Int) {
        endCompare()
        versionRequest(VersionRestoreMessage(id: nextRequestID(), version: "V\(nr)"), arbeitet: "V\(nr) wird wiederhergestellt") {
            [weak self] m in self?.bestaetige(m)
        }
    }

    public func compareVersion(_ a: Int, with b: Int?) {
        model.versionen.vergleichLaeuft = a
        versionRequest(
            VersionCompareMessage(id: nextRequestID(), a: "V\(a)", b: b.map { "V\($0)" }), arbeitet: nil, timeout: 600
        ) { [weak self] m in
            guard let self else { return }
            if case .versionen(let v) = m { self.handleVersionen(v) }
            self.model.versionen.vergleichLaeuft = nil
        }
    }

    public func endCompare() {
        guard model.versionen.vergleich != nil || !scene.vergleichBodies.isEmpty else { return }
        model.versionen.vergleich = nil
        scene.setVergleich(bodies: [], tints: [:])
    }

    public func setMilestone(version: Int?, titel: String, notiz: String) {
        versionRequest(
            VersionMilestoneMessage(id: nextRequestID(), version: version.map { "V\($0)" }, titel: titel, notiz: notiz),
            arbeitet: "Meilenstein wird gesetzt"
        ) { [weak self] m in self?.bestaetige(m) }
    }

    public func removeMilestone(version: Int) {
        versionRequest(
            VersionMilestoneMessage(id: nextRequestID(), version: "V\(version)", titel: "", entfernen: true),
            arbeitet: nil
        ) { [weak self] m in self?.bestaetige(m) }
    }

    public func createVariant(name: String, from version: Int?) {
        endCompare()
        versionRequest(
            VariantMessage(id: nextRequestID(), aktion: "anlegen", name: name, von: version.map { "V\($0)" }),
            arbeitet: "Variante \(name) wird angelegt"
        ) { [weak self] m in self?.bestaetige(m) }
    }

    public func switchVariant(_ id: String) {
        endCompare()
        let name = model.versionen.stand?.varianten.first { $0.id == id }?.name ?? id
        versionRequest(
            VariantMessage(id: nextRequestID(), aktion: "wechseln", name: id), arbeitet: "Wechsel zu \(name)"
        ) { [weak self] m in self?.bestaetige(m) }
    }

    public func renameVariant(_ id: String, to name: String) {
        versionRequest(VariantMessage(id: nextRequestID(), aktion: "umbenennen", name: id, neuerName: name), arbeitet: nil) {
            [weak self] m in
            self?.bestaetige(m)
            self?.requestVersionen()
        }
    }
}
