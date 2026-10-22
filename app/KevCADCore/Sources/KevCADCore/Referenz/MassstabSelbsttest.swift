import AppKit
import Foundation
import MetalKit
import OCCTSwiftViewport
import simd

// Selbsttest des Werkzeugs „Maßstab setzen“ ohne simulierte Maus (nur Testvariante, Umgebungsvariable
// KEVCAD_SELFTEST=massstab): Sobald ein Referenznetz in der Szene steht, startet das Werkzeug, die Ansicht wird auf das
// Netz gerichtet und über die GPU auf zwei Punkte des Netzes gepickt (die zur Kamera gewandten Punkte ganz links und ganz
// rechts). Jeder Treffer geht wie ein Klick an `massstabKlick`. Mit KEVCAD_SELFTEST_MM=<mm> wird der Maßstab danach
// gesetzt (REF_SCALE). Alles steht im Protokoll (stderr).

@MainActor
enum MassstabSelbsttest {
    static var gestartet = false

    static var gewuenscht: Bool {
        AppInfo.isTestVariant && ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "massstab"
    }
}

extension AppController {
    func massstabSelbsttestPlanen(_ n: ReferenzNetz) {
        guard MassstabSelbsttest.gewuenscht, !MassstabSelbsttest.gestartet, n.triangleCount > 0,
              referenzen.referenz(n.name)?.istScan == false  // Scans sind metrisch, für sie gibt es kein Werkzeug
        else { return }
        MassstabSelbsttest.gestartet = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
            MainActor.assumeIsolated { self?.massstabSelbsttest(n.name) }
        }
    }

    func massstabSelbsttest(_ name: String) {
        guard let n = referenzen.netze[name], let mtk = viewport.mtkView,
              let renderer = mtk.delegate as? ViewportRenderer
        else {
            log(.error, "Selbsttest Maßstab: Netz, MTKView oder Renderer fehlt")
            return
        }
        viewport.fit(BoundingBox(min: n.bboxMin, max: n.bboxMax), animated: false)
        massstabWerkzeug(name)
        log(.info, "Selbsttest Maßstab: Werkzeug für \(name) gestartet, \(scene.referenzBodies.filter(\.isPickable).count) "
            + "anklickbare Körper")
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
            MainActor.assumeIsolated {
                guard let self else { return }
                let size = mtk.bounds.size
                let scale = size.width > 0 ? mtk.drawableSize.width / size.width : 2
                let projector = OverlayProjector(camera: self.viewport.camera, size: size)
                let zurKamera = -self.viewport.camera.viewDirection
                // Zur Kamera gewandte Punkte, davon der linke und der rechte Rand im Bild (etwas nach innen)
                var kandidaten: [(CGPoint, SIMD3<Float>)] = []
                let nv = n.vertexCount
                let schritt = max(1, nv / 4000)
                for i in stride(from: 0, to: nv, by: schritt) {
                    let p = SIMD3(n.positions[i * 3], n.positions[i * 3 + 1], n.positions[i * 3 + 2])
                    let nn = SIMD3(n.normals[i * 3], n.normals[i * 3 + 1], n.normals[i * 3 + 2])
                    guard simd_dot(nn, zurKamera) > 0.5, let s = projector.project(p) else { continue }
                    kandidaten.append((s, p))
                }
                guard kandidaten.count >= 2 else {
                    self.log(.error, "Selbsttest Maßstab: keine zur Kamera gewandten Punkte")
                    return
                }
                kandidaten.sort { $0.0.x < $1.0.x }
                let k = max(0, kandidaten.count / 20)
                let ziele = [kandidaten[k], kandidaten[kandidaten.count - 1 - k]]
                @MainActor func klick(_ i: Int) {
                    guard i < ziele.count else {
                        let d = self.referenzen.massstabWerkzeug?.abstand
                        self.log(d == nil ? .error : .info, "Selbsttest Maßstab: \(self.referenzen.massstabWerkzeug?.punkte.count ?? 0) "
                            + "Punkte, Abstand am Netz \(d.map { KevFormat.number($0, digits: 2) } ?? "–") mm")
                        if let d, let mm = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_MM"].flatMap(Double.init),
                           let w = self.referenzen.massstabWerkzeug {
                            self.log(.info, "Selbsttest Maßstab: setze \(KevFormat.number(d, digits: 2)) mm → \(mm) mm")
                            self.massstabSetzen(w.referenz, mm: mm, punkte: w.punkte, kante: nil)
                        }
                        self.log(.info, "Selbsttest Maßstab fertig")
                        return
                    }
                    let (s, p) = ziele[i]
                    let px = SIMD2(Int(s.x * scale), Int(s.y * scale))
                    renderer.performPick(at: px) { result in
                        DispatchQueue.main.async {
                            MainActor.assumeIsolated {
                                let ok = self.massstabKlick(result, p)
                                let getroffen = result?.bodyID.hasPrefix(Self.referenzKoerperPrefix) == true
                                self.log(getroffen ? .info : .warning,
                                         "Selbsttest Maßstab: Pick bei \(px) → \(result?.bodyID.replacingOccurrences(of: "\u{1F}", with: ":") ?? "nichts")"
                                             + ", Punkt (\(KevFormat.number(Double(p.x), digits: 1)); \(KevFormat.number(Double(p.y), digits: 1)); "
                                             + "\(KevFormat.number(Double(p.z), digits: 1))), verbraucht \(ok), "
                                             + "Werkzeug \(self.referenzen.massstabWerkzeug?.punkte.count ?? 0) Punkte")
                                klick(i + 1)
                            }
                        }
                    }
                }
                klick(0)
            }
        }
    }
}
