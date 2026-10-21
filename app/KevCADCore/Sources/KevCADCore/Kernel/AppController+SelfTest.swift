import AppKit
import Foundation
import MetalKit
import OCCTSwiftViewport
import simd

// Selbsttest für Live-Tests ohne simulierte Maus (nur Testvariante, Umgebungsvariable KEVCAD_SELFTEST=core):
// Nach dem ersten Lauf wird geprüft, ob ein Klick im MTKView landet (Überlagerungen dürfen ihn nicht abfangen),
// dann wird über die GPU in der Mitte jedes Teils gepickt, der Treffer zurückgerechnet und wie ein Klick
// verarbeitet (Auswahl, Umschalt-Klick, Messen über den Kernel). Alles steht im Protokoll (stderr).

extension AppController {
    func scheduleSelfTestIfRequested() {
        guard AppInfo.isTestVariant, ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "core",
            !selfTestStarted
        else { return }
        selfTestStarted = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { [weak self] in
            MainActor.assumeIsolated { self?.runSelfTest() }
        }
    }

    func runSelfTest() {
        guard let mtk = viewport.mtkView, let window = mtk.window,
            let renderer = mtk.delegate as? ViewportRenderer
        else {
            log(.error, "Selbsttest: MTKView oder Renderer nicht gefunden")
            return
        }
        log(.info, "Selbsttest: MTKView \(Int(mtk.bounds.width)) × \(Int(mtk.bounds.height)) pt, \(mtk.preferredFramesPerSecond) Bilder/s gewünscht")
        // Landet ein Klick in der Bildmitte im MTKView?
        if let content = window.contentView {
            let center = mtk.convert(CGPoint(x: mtk.bounds.midX, y: mtk.bounds.midY), to: nil)
            let hit = content.hitTest(content.superview?.convert(center, from: nil) ?? center)
            log(hit === mtk ? .info : .error, "Selbsttest: Klick in der Mitte trifft \(hit === mtk ? "das MTKView" : String(describing: hit))")
        }
        let size = mtk.bounds.size
        let scale = size.width > 0 ? mtk.drawableSize.width / size.width : 2
        let projector = OverlayProjector(camera: viewport.camera, size: size)
        let names = scene.order.filter(scene.isVisible)
        var picks: [(String, PickResult?)] = []
        // Je Teil die Mitte; bei aufgeteilten Teilen zusätzlich ein zur Kamera gewandtes Dreieck je Körper
        var targets: [(String, SIMD3<Float>)] = names.compactMap { n in scene.worldAnchor(of: .part(n)).map { (n, $0) } }
        let toCamera = -viewport.camera.viewDirection
        for n in names {
            guard let rec = scene.record(n), rec.chunks.count > 1 else { continue }
            for chunk in rec.chunks where chunk.triangleCount > 0 {
                // Das am stärksten zur Kamera gewandte Dreieck dieses Körpers
                let vd = chunk.vertexData
                var best: (Float, SIMD3<Float>)?
                for t in stride(from: 0, to: chunk.triangleCount, by: 3) {
                    let v = (0..<3).map { k -> SIMD3<Float> in
                        let i = Int(chunk.indices[t * 3 + k]) * 6
                        return SIMD3(vd[i], vd[i + 1], vd[i + 2])
                    }
                    let cr = simd_cross(v[1] - v[0], v[2] - v[0])
                    guard simd_length(cr) > 1e-9 else { continue }
                    let d = simd_dot(simd_normalize(cr), toCamera)
                    if best == nil || d > best!.0 { best = (d, (v[0] + v[1] + v[2]) / 3) }
                }
                if let best, best.0 > 0.2 { targets.append(("\(n) (Körper \(chunk.index))", best.1)) }
            }
        }

        func step(_ i: Int) {
            guard i < targets.count else {
                finish(picks)
                return
            }
            let (label, p) = targets[i]
            let name = label.components(separatedBy: " (").first ?? label
            guard let s = projector.project(p) else {
                step(i + 1)
                return
            }
            let px = SIMD2(Int(s.x * scale), Int(s.y * scale))
            renderer.performPick(at: px) { result in
                DispatchQueue.main.async {
                    MainActor.assumeIsolated {
                        let ref = result.flatMap { self.scene.resolve($0) }
                        let ok = ref?.part == name
                        self.log(
                            ok ? .info : .warning,
                            "Selbsttest: Pick bei \(px) auf \(label) → \(ref?.string ?? "nichts") (\(result.map { "\($0.kind)" } ?? "-"), Körper \(result?.bodyID.replacingOccurrences(of: "\u{1F}", with: ":") ?? "-"))"
                        )
                        picks.append((name, result))
                        step(i + 1)
                    }
                }
            }
        }

        func finish(_ picks: [(String, PickResult?)]) {
            let hits = picks.prefix(names.count).compactMap(\.1)
            guard hits.count >= 2 else {
                log(.error, "Selbsttest: zu wenige Treffer (\(hits.count))")
                return
            }
            // Wie Klicks: auswählen, mit Umschalt ergänzen, dann zwei Klicks im Messmodus
            handleClick(hits[0], modifiers: [])
            handleClick(hits[1], modifiers: .shift)
            log(.info, "Selbsttest: Auswahl \(model.selection.map { "\($0.ref) = \($0.summary)" })")
            setMeasureMode(true)
            handleClick(hits[0], modifiers: [])
            handleClick(hits[hits.count - 1], modifiers: [])
            setMeasureMode(false)
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
                MainActor.assumeIsolated {
                    guard let self else { return }
                    self.log(.info, "Selbsttest: Messungen \(self.model.measurements.map(\.text))")
                    self.log(.info, "Selbsttest: Kernel neu starten")
                    self.restartKernel()
                    DispatchQueue.main.asyncAfter(deadline: .now() + 4) {
                        MainActor.assumeIsolated {
                            self.log(
                                .info,
                                "Selbsttest: nach Neustart Kernel \(self.model.kernelState), \(self.model.parts.count) Teile, Projekt \(self.model.project?.name ?? "-")"
                            )
                            self.log(.info, "Selbsttest fertig")
                        }
                    }
                }
            }
        }

        step(0)
    }
}
