import Foundation
import OCCTSwiftViewport
import simd

/// Ansichten zur Analyse (MCP `ansichten`, `pruefen(bilder=True)`): SCREENSHOT_REQ mit dem Feld `ansicht`. Eigene
/// Blickrichtung (Standardansicht oder Vektor), Ziel (Teile oder Punkt mit Radius), Darstellung, rot hervorgehobene
/// Teile und die Schnittkörper der Prüfung. Kevins Kamera, Darstellung und Auswahl bleiben unverändert: gerendert wird
/// aus einer Kopie der Körper über den Offscreen-Renderer.
///
/// Bewusst klein und für sich: beim Zusammenführen mit dem Kamerabild (Strang KAM) wird die Kamerawahl vereinigt.
extension AppController {
    static let analyseRot = SIMD4<Float>(0.92, 0.10, 0.08, 1)

    func renderAnsicht(_ s: ScreenshotRequestMessage, _ a: JSONValue) {
        let w = max(16, min(s.width, 4096)), h = max(16, min(s.height, 4096))
        let camera = Self.ansichtKamera(a, scene: scene, aspect: Float(w) / Float(h))
        let bodies = Self.ansichtKoerper(a, from: scene.snapshotBodies())
        let darstellung = a["darstellung"]?.stringValue ?? "shaded_edges"
        let mode: DisplayMode =
            darstellung == "wireframe" ? .wireframe : darstellung == "shaded" ? .shaded : .shadedWithEdges
        guard
            let r = screenshots.render(
                bodies: bodies, camera: camera, width: w, height: h, displayMode: mode,
                lighting: viewport.controller.lightingConfiguration, overlay: [])
        else {
            send(
                ScreenshotResponseMessage(
                    replyTo: s.id, ok: false, width: 0, height: 0, camera: .null, mmPerPx: nil,
                    message: "Ansicht ließ sich nicht rendern"))
            return
        }
        var cam = ViewportCoordinator.cameraJSON(camera, height: h)
        if case .object(var o) = cam {
            o["ansicht"] = .bool(true)  // die App hat die Felder von `ansicht` umgesetzt
            cam = .object(o)
        }
        send(
            ScreenshotResponseMessage(replyTo: s.id, ok: true, width: w, height: h, camera: cam, mmPerPx: r.mmPerPixel),
            payload: r.png)
    }

    /// Kamera: Richtung aus `standard` oder `richtung` (Blickrichtung), eingepasst auf `ziel`, `punkt`/`radius` oder
    /// alles Sichtbare.
    static func ansichtKamera(_ a: JSONValue, scene: SceneStore, aspect: Float) -> CameraState {
        let iso = ViewportCoordinator.standardView(protocolName: "iso")!
        var cam = iso.cameraState(distance: 1000, orthographicScale: 100)
        if let name = a["standard"]?.stringValue, let sv = ViewportCoordinator.standardView(protocolName: name) {
            cam.rotation = sv.rotation
        } else if let d = a["richtung"]?.vector3, simd_length(d) > 1e-6 {
            cam.rotation = rotation(blick: d)
        }
        var ziel: BoundingBox?
        if let refs = a["ziel"]?.stringList, !refs.isEmpty {
            ziel = scene.worldBounds(of: scene.expand(refs.compactMap(ElementRef.init)).known)
        }
        if ziel == nil, let p = a["punkt"]?.vector3 {
            let r = SIMD3<Float>(repeating: Float(max(1, a["radius"]?.doubleValue ?? 50)))
            ziel = BoundingBox(min: p - r, max: p + r)
        }
        if let b = ziel ?? scene.visibleBounds() {
            cam = ViewportCoordinator.fitted(cam, to: b, aspect: aspect)
        }
        return cam
    }

    /// Drehung einer Kamera, die entlang `blick` schaut, Z bleibt oben (bei senkrechtem Blick: Y oben).
    static func rotation(blick: SIMD3<Float>) -> simd_quatf {
        let zurueck = simd_normalize(-blick)  // lokale +Z der Kamera zeigt zum Betrachter
        var oben = SIMD3<Float>(0, 0, 1)
        if abs(simd_dot(oben, zurueck)) > 0.999 { oben = SIMD3<Float>(0, 1, 0) }
        let rechts = simd_normalize(simd_cross(oben, zurueck))
        let hoch = simd_cross(zurueck, rechts)
        return simd_quatf(simd_float3x3(columns: (rechts, hoch, zurueck)))
    }

    /// Teilname eines Körpers aus `snapshotBodies()` (live: "Teil␟Stück", sonst "snap␟Teil␟…"); nil für Hilfskörper.
    static func teilName(ofBody id: String) -> String? {
        let teile = id.split(separator: "\u{1F}", omittingEmptySubsequences: false).map(String.init)
        if teile.first == "snap", teile.count > 1 { return teile[1] }
        return teile.first.flatMap { $0.isEmpty ? nil : $0 }
    }

    /// Körper für die Ansicht: Schnittkörper ein oder aus, hervorgehobene Teile rot, Röntgen durchscheinend.
    static func ansichtKoerper(_ a: JSONValue, from bodies: [ViewportBody]) -> [ViewportBody] {
        let hervor = Set(a["hervorheben"]?.stringList ?? [])
        let roentgen = a["darstellung"]?.stringValue == "xray"
        let geister = a["schnittkoerper"]?.boolValue ?? true
        var out: [ViewportBody] = []
        for var b in bodies {
            if b.id.hasPrefix(schnittkoerperPrefix) {
                if geister { out.append(b) }
                continue
            }
            if b.id == SceneStore.depthHelperID {
                out.append(b)
                continue
            }
            if let name = teilName(ofBody: b.id), hervor.contains(name)
                || hervor.contains(where: { name.hasPrefix($0.hasSuffix("/") ? $0 : $0 + "/") })
            {
                let c = b.color
                let rgb = SIMD3(c.x, c.y, c.z) + (SIMD3(analyseRot.x, analyseRot.y, analyseRot.z) - SIMD3(c.x, c.y, c.z)) * 0.7
                b.color = SIMD4(rgb, c.w)
            }
            if roentgen { b.color.w = min(b.color.w, 0.3) }
            out.append(b)
        }
        return out
    }
}
