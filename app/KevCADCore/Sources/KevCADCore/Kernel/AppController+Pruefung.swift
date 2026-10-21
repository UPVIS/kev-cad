import Foundation
import OCCTSwiftViewport
import simd

/// Prüfung (PROTOCOL.md Abschnitt „Prüfung“): CHECK übernehmen, betroffene Teile rot, Schnittkörper als roter
/// Geisterkörper, Befund anklicken = Teile auswählen und auf den Ort zoomen.
extension AppController: PruefActions {
    /// Farbe der Schnittkörper (linear), durchscheinend, immer obenauf.
    static let schnittkoerperFarbe = SIMD4<Float>(0.95, 0.02, 0.02, 0.6)
    static let schnittkoerperPrefix = "\u{1F}pruefung\u{1F}"

    func applyCheck(_ c: CheckMessage) {
        let e = c.ergebnis
        switch e.zustand {
        case .running:
            // die Befunde des letzten Laufs bleiben stehen, bis das neue Ergebnis da ist (kein Flackern)
            if var p = model.pruefung {
                p.laeuft = true
                model.pruefung = p
            } else {
                model.pruefung = PruefErgebnis(run: e.run, zustand: .running, laeuft: true)
            }
            return
        case .cancelled:
            return  // ein neuerer Lauf kam dazwischen; dessen Ergebnis folgt
        case .done, .failed:
            let alt = model.pruefung?.bandText ?? ""
            model.pruefung = e
            if e.zustand == .failed {
                log(.warning, "Prüfung von Lauf \(e.run) fehlgeschlagen: \(e.meldung ?? "ohne Meldung")")
            } else if !e.bandText.isEmpty, e.bandText != alt {
                log(.warning, "Prüfung Lauf \(e.run): \(e.bandText)")
            }
        }
        updateSchnittkoerper()
        updateParts()
    }

    /// Schnittkörper aus dem letzten Ergebnis in die Szene legen (oder entfernen).
    func updateSchnittkoerper() {
        guard let p = model.pruefung, model.schnittkoerperSichtbar else {
            if !scene.ghostBodies.isEmpty { scene.setGhostBodies([]) }
            return
        }
        scene.setGhostBodies(Self.schnittkoerper(p))
    }

    static func schnittkoerper(_ p: PruefErgebnis) -> [ViewportBody] {
        var out: [ViewportBody] = []
        for (i, g) in p.geometrie.enumerated() where g.triangleCount > 0 {
            var vd = [Float]()
            vd.reserveCapacity(g.vertexCount * 6)
            for v in 0..<g.vertexCount {
                vd.append(contentsOf: g.positions[(v * 3)..<(v * 3 + 3)])
                if g.normals.count >= v * 3 + 3 {
                    vd.append(contentsOf: g.normals[(v * 3)..<(v * 3 + 3)])
                } else {
                    vd.append(contentsOf: [0, 0, 1])
                }
            }
            out.append(
                ViewportBody(
                    id: schnittkoerperPrefix + String(i), vertexData: vd, indices: g.triangles, edges: [],
                    color: schnittkoerperFarbe, roughness: 0.6, isPickable: false, renderLayer: .overlay))
        }
        return out
    }

    // MARK: PruefActions

    public func zeigeBefund(_ befund: PruefBefund) {
        let bekannt = befund.teile.filter { scene.record($0) != nil }
        if !bekannt.isEmpty { select(bekannt) }
        // auf den Ort zoomen: Schnittkörper (vergrößert), sonst die Teile
        let alle = model.pruefung?.geometrie ?? []
        if let gi = befund.geometrie, alle.indices.contains(gi), alle[gi].vertexCount > 0 {
            let g = alle[gi]
            var lo = SIMD3<Float>(repeating: .greatestFiniteMagnitude)
            var hi = SIMD3<Float>(repeating: -.greatestFiniteMagnitude)
            for v in 0..<g.vertexCount {
                let p = SIMD3<Float>(g.positions[v * 3], g.positions[v * 3 + 1], g.positions[v * 3 + 2])
                lo = simd_min(lo, p)
                hi = simd_max(hi, p)
            }
            let rand = simd_max(SIMD3<Float>(repeating: 15), (hi - lo) * 1.5)
            viewport.fit(BoundingBox(min: lo - rand, max: hi + rand), animated: true)
        } else if let ort = befund.ort {
            let r = SIMD3<Float>(repeating: 60)
            viewport.fit(BoundingBox(min: ort - r, max: ort + r), animated: true)
        } else if !bekannt.isEmpty {
            focus(on: bekannt)
        }
    }

    public func setSchnittkoerperSichtbar(_ sichtbar: Bool) {
        model.schnittkoerperSichtbar = sichtbar
        updateSchnittkoerper()
    }

    public func zeigeMontageSchritt(_ schritt: Int?) {
        guard let schritt, let p = model.pruefung else {
            showAll()
            return
        }
        let alle = p.montageSchritte
        guard !alle.isEmpty else { return }
        let k = max(1, min(schritt, alle.count))
        let bekannt = { (n: String) in self.scene.record(n) != nil }
        let bisher = alle.prefix(k).flatMap(\.teile).filter(bekannt)
        isolate(bisher)
        let aktuell = alle[k - 1].teile.filter(bekannt)
        if !aktuell.isEmpty { select(aktuell) }
    }
}
