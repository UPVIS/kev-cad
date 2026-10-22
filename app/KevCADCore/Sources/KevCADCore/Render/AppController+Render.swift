import AppKit
import Foundation
import MetalKit
import OCCTSwiftViewport
import simd

// Phase 7: Renderings im App-Kern. RENDER_REQ → RealityKit (PBRRenderer) → PNG → RENDER_RES; RENDER_SCENE_REQ → Kamera,
// Lagen und Sichtbarkeit für Blender; RENDER_STATUS → RenderStore (Dialog „Rendern …“). Der Dialog startet Aufträge mit
// RENDER_START beim Kernel, der die Materialien aus dem Katalog dazugibt.

/// Aktionen des Dialogs „Rendern …“ (die Oberfläche ruft nur diese).
@MainActor
public protocol RenderActions: AnyObject {
    /// Auftrag mit den Einstellungen aus `model.render` starten (Ergebnis unter output/renders/).
    func renderStarten()
    /// Kleines Vorschaubild mit denselben Einstellungen (schnell, 960 px breit).
    func renderVorschau()
    func renderAbbrechen(_ auftrag: String)
    func renderImFinderZeigen(_ url: URL)
}

extension AppModel {
    public var renderActions: RenderActions? { actions as? RenderActions }
}

extension AppController: RenderActions {
    func handleRender(_ n: RenderNachricht) {
        switch n {
        case .auftrag(let a):
            Task { @MainActor [weak self] in await self?.renderAuftrag(a) }
        case .szeneAnfrage(let a):
            renderSzeneAntworten(a)
        case .status(let s):
            model.render.status(s)
            guard !s.vorschau else { return }
            switch s.zustand {
            case .fertig: log(.info, "Rendering \(s.auftrag) fertig: \(s.pfad ?? "?") (\(s.text))")
            case .fehler: log(.error, "Rendering \(s.auftrag) fehlgeschlagen: \(s.fehler ?? s.text)")
            case .abgebrochen: log(.info, "Rendering \(s.auftrag) abgebrochen")
            default: break
            }
        }
    }

    // MARK: RENDER_REQ (schnell)

    func renderAuftrag(_ a: RenderAuftrag) async {
        let t0 = Date()
        let alter = Date().timeIntervalSince(a.empfangen)
        do {
            let ergebnis = try await renderBild(a)
            let url = URL(fileURLWithPath: a.path)
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try ergebnis.png.write(to: url)
            let ms = Int(Date().timeIntervalSince(t0) * 1000)
            if !a.vorschau {
                log(.info, "Rendering \(a.auftrag) (\(a.szene.titel), \(a.width) × \(a.height)) in \(ms) ms: \(url.path)")
            }
            var phasen = ergebnis.phasen
            if alter > 0.05 { phasen["start_ms"] = Int(alter * 1000) }
            send(RenderResponseMessage(replyTo: a.id, ok: true, path: url.path, width: a.width, height: a.height,
                                       ms: ms, kamera: ergebnis.kamera.json, phasen: phasen))
        } catch {
            let text = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            log(.error, "Rendering \(a.auftrag) fehlgeschlagen: \(text)")
            send(RenderResponseMessage(replyTo: a.id, ok: false, path: nil, width: 0, height: 0,
                                       ms: Int(Date().timeIntervalSince(t0) * 1000), message: text))
        }
    }

    /// Bild für einen Auftrag: Teile, Kamera und Szene wie im Viewer, Materialien vom Kernel.
    func renderBild(_ a: RenderAuftrag) async throws -> (png: Data, bild: CGImage, kamera: PBRRenderer.Kamera,
                                                         phasen: [String: Int]) {
        let kulisse = Set(a.teile.filter(\.kulisse).map(\.name))
        guard let kamera = renderKamera(ansicht: a.ansicht, kamera: a.kamera, breite: a.width, hoehe: a.height,
                                        kulisse: kulisse) else {
            throw PBRRenderer.Fehler.rendern(a.kamera.map { "Kamera \($0) gibt es in der App nicht" }
                                             ?? "Keine sichtbaren Teile")
        }
        if !a.teile.isEmpty { letzteRenderMaterialien = a.teile }
        let materialien = Dictionary(a.teile.map { ($0.name, $0) }, uniquingKeysWith: { x, _ in x })
        // Freigestellt: nur das Produkt, ohne Kulisse (Boden, Wand)
        let teile = renderTeile(materialien: materialien, kamera: a.kamera).filter {
            !a.szene.transparent || !(kulisse.contains($0.name) || $0.name.hasPrefix("Kulisse/"))
        }
        // Der Viewport zeichnet sonst mit bis zu 120 Bildern/s weiter und belegt Hauptfaden und GPU; für die
        // Dauer des Bildes anhalten (Kevin sieht höchstens ein kurzes Stehenbleiben)
        let ansicht = viewport.mtkView
        let warPausiert = ansicht?.isPaused ?? false
        ansicht?.isPaused = true
        defer { ansicht?.isPaused = warPausiert }
        var e: PBRRenderer.Ergebnis
        do {
            e = try await pbr.render(teile: teile, kamera: kamera, szene: a.szene, width: a.width, height: a.height)
        } catch let f as PBRRenderer.Fehler where f.istZeitueberschreitung {
            // Einmal mit neuem Renderer wiederholen (der alte ist verworfen); der Befund steht im Protokoll
            log(.warning, "Rendering \(a.auftrag): \(f.errorDescription ?? "Zeitüberschreitung"); zweiter Versuch mit "
                + "neuem Renderer")
            do {
                e = try await pbr.render(teile: teile, kamera: kamera, szene: a.szene, width: a.width, height: a.height)
            } catch let f2 as PBRRenderer.Fehler where f2.istZeitueberschreitung {
                log(.error, "Rendering \(a.auftrag): auch der zweite Versuch kam nicht zurück: \(f2.errorDescription ?? "")")
                throw f2
            }
            e.phasen["wiederholt"] = 1
        }
        return (e.png, e.bild, kamera, e.phasen)
    }

    // MARK: RENDER_SCENE_REQ (Foto über Blender)

    func renderSzeneAntworten(_ a: RenderSzeneAnfrage) {
        guard let kamera = renderKamera(ansicht: a.ansicht, kamera: a.kamera, breite: a.width, hoehe: a.height,
                                        kulisse: Set(a.kulisse)) else {
            send(RenderSceneMessage(replyTo: a.id, ok: false,
                                    message: a.kamera.map { "Kamera \($0) gibt es in der App nicht" }
                                        ?? "Keine sichtbaren Teile"))
            return
        }
        var json = kamera.json
        if case .object(var o) = json {
            o["name"] = a.kamera.map(JSONValue.string) ?? .null
            json = .object(o)
        }
        let teile = renderSichtbar(kamera: a.kamera).map { name -> (name: String, matrix: [Float]?) in
            let m = scene.worldTransform(name)
            if m == matrix_identity_float4x4 { return (name, nil) }
            return (name, [m.columns.0, m.columns.1, m.columns.2, m.columns.3].flatMap { [$0.x, $0.y, $0.z, $0.w] })
        }
        send(RenderSceneMessage(replyTo: a.id, ok: true, kamera: json, teile: teile))
    }

    // MARK: Teile und Kamera

    /// Sichtbare Teile wie im Viewer; mit Kamera ohne ihr Objektiv und ohne Teile vor dem Augpunkt.
    func renderSichtbar(kamera name: String?) -> [String] {
        var namen = scene.order.filter { scene.isVisible($0) && !scene.animationHidden.contains($0) }
        let kamera = name.flatMap { cameras.camera($0) } ?? cameras.activeView.flatMap { cameras.camera($0) }
        if let kamera {
            let weg = hiddenForCamera(posedCamera(kamera))
            namen.removeAll { weg.contains($0) }
        }
        return namen
    }

    func renderTeile(materialien: [String: RenderPBR], kamera: String?) -> [PBRRenderer.Teil] {
        renderSichtbar(kamera: kamera).compactMap { name in
            guard let rec = scene.record(name) else { return nil }
            let c = rec.header.colorVector
            let pbr = materialien[name] ?? RenderPBR(name: name, basisfarbe: SIMD3(c.x, c.y, c.z))
            return PBRRenderer.Teil(name: name, geometry: rec.geometry, digest: rec.digest,
                                    transform: scene.worldTransform(name), pbr: pbr)
        }
    }

    /// Kamera für ein Rendering (mm, Z oben, perspektivisch): aktuelle Ansicht, Produktansicht, Standardansicht oder
    /// eine Kamera aus model.py (posiert wie im Viewer). Eingepasst wird auf das Produkt: Kulisse (Boden, Wand, vom
    /// Kernel gemeldet oder in der Gruppe „Kulisse/“) bleibt im Bild, zählt aber nicht für den Ausschnitt.
    func renderKamera(ansicht: String, kamera name: String?, breite: Int, hoehe: Int,
                      kulisse: Set<String> = []) -> PBRRenderer.Kamera? {
        let aspekt = Float(breite) / Float(max(hoehe, 1))
        if let name {
            guard let c = cameras.camera(name) else { return nil }
            let s = CameraViewMath.state(for: posedCamera(c))
            return PBRRenderer.Kamera(position: s.position, ziel: s.pivot, oben: s.upVector, fovGrad: s.fieldOfView)
        }
        let sichtbar = renderSichtbar(kamera: nil)
        let produkt = sichtbar.filter { !kulisse.contains($0) && !$0.hasPrefix("Kulisse/") }
        guard let b = scene.worldBounds(of: (produkt.isEmpty ? sichtbar : produkt).map { ElementRef.part($0) }) else {
            return nil
        }
        switch ansicht {
        case "aktuell":
            let s = viewport.camera
            if s.isOrthographic {
                // Parallele Ansicht: echt orthografisch mit derselben sichtbaren Höhe; das Auge so weit zurück, dass
                // alles vor der Kamera liegt (sonst schnitte die Nahebene das Modell an)
                return Self.orthoKamera(blick: s.viewDirection, ziel: s.pivot, oben: s.upVector,
                                        hoehe: s.orthographicScale, fovGrad: max(5, min(s.fieldOfView, 120)),
                                        bounds: scene.worldBounds(of: sichtbar.map { ElementRef.part($0) }) ?? b)
            }
            return PBRRenderer.Kamera(position: s.position, ziel: s.pivot, oben: s.upVector,
                                      fovGrad: max(5, min(s.fieldOfView, 120)))
        case "produkt":
            // 3/4-Ansicht vorn rechts, 24° von oben, Brennweite um 85 mm (Kleinbild)
            let iso = StandardView.isometricFrontRight.cameraState(distance: 1000)
            let v = iso.viewDirection
            let az = atan2(v.y, v.x)
            let el: Float = 24 * .pi / 180
            let blick = SIMD3(cos(el) * cos(az), cos(el) * sin(az), -sin(el))
            return Self.eingepasst(blick: blick, oben: SIMD3(0, 0, 1), fov: 22, bounds: b, aspekt: aspekt)
        default:
            guard let sv = ViewportCoordinator.standardView(protocolName: ansicht) else { return nil }
            let s = sv.cameraState(distance: 1000)
            return Self.eingepasst(blick: s.viewDirection, oben: s.upVector, fov: 26, bounds: b, aspekt: aspekt)
        }
    }

    /// Orthografische Kamera (sichtbare Höhe `hoehe` mm) mit Blick auf `ziel`; das Auge liegt außerhalb der Hüllkugel
    /// von `bounds`, damit nichts vor der Nahebene liegt.
    nonisolated static func orthoKamera(blick: SIMD3<Float>, ziel: SIMD3<Float>, oben: SIMD3<Float>, hoehe: Float,
                                        fovGrad: Float, bounds b: BoundingBox) -> PBRRenderer.Kamera {
        let v = simd_normalize(blick)
        // Abstand längs der Blickrichtung bis hinter die Hüllkugel (vom Ziel aus gemessen)
        let r = max(b.diagonalLength / 2, 1)
        let zurMitte = simd_dot(b.center - ziel, -v)
        let abstand = max(zurMitte + r * 1.5, r * 1.5, 10)
        return PBRRenderer.Kamera(position: ziel - v * abstand, ziel: ziel, oben: oben, fovGrad: fovGrad,
                                  orthoHoehe: max(hoehe, 0.01))
    }

    /// Perspektivische Kamera mit Blickrichtung `blick`, die die Hüllkugel der Teile ganz zeigt.
    nonisolated static func eingepasst(blick: SIMD3<Float>, oben: SIMD3<Float>, fov: Float, bounds b: BoundingBox, aspekt: Float,
                           rand: Float = 1.12) -> PBRRenderer.Kamera {
        let mitte = b.center
        let radius = max(b.diagonalLength / 2, 1)
        let halbV = fov * .pi / 360
        let halbH = atan(tan(halbV) * aspekt)
        let abstand = radius * rand / sin(min(halbV, halbH))
        var o = oben
        if abs(simd_dot(simd_normalize(o), simd_normalize(blick))) > 0.99 { o = SIMD3(0, 1, 0) }
        return PBRRenderer.Kamera(position: mitte - simd_normalize(blick) * abstand, ziel: mitte, oben: o, fovGrad: fov)
    }

    // MARK: Aktionen des Dialogs

    public func renderStarten() {
        guard model.project != nil else { return }
        let r = model.render
        let (w, h) = renderGroesse()
        let msg = RenderStartMessage(id: nextRequestID(), szene: r.szene, ansicht: r.ansicht, kamera: r.kamera,
                                     breite: w, hoehe: h, qualitaet: r.qualitaet, hintergrund: r.hintergrund)
        request(msg, timeout: 20) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)) where a.ok:
                self.log(.info, "Rendering \(a.message ?? "") gestartet (\(r.qualitaet == "foto" ? "Foto, Blender" : "schnell"))")
            case .success(.ack(let a)):
                self.model.render.meldung = a.message ?? "Rendering nicht gestartet"
                self.log(.error, "Rendering nicht gestartet: \(a.message ?? "?")")
            case .success(let m):
                self.log(.warning, "Rendering: unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                self.model.render.meldung = e.message
                self.log(.error, "Rendering nicht gestartet: \(e.message)")
            }
        }
    }

    public func renderVorschau() {
        guard model.project != nil, !scene.isEmpty else { return }
        let r = model.render
        let (w, h) = renderGroesse()
        let vw = 960, vh = max(16, Int((Float(h) / Float(w) * 960).rounded()))
        model.render.vorschauGestartet()
        let msg = RenderStartMessage(id: nextRequestID(), szene: r.szene, ansicht: r.ansicht, kamera: r.kamera,
                                     breite: vw, hoehe: vh, qualitaet: "schnell", hintergrund: r.hintergrund,
                                     vorschau: true)
        request(msg, timeout: 20) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)) where a.ok: break
            case .success(.ack(let a)): self.model.render.vorschauFehlgeschlagen(a.message ?? "Vorschau nicht möglich")
            case .success: break
            case .failure(let e): self.model.render.vorschauFehlgeschlagen(e.message)
            }
        }
    }

    public func renderAbbrechen(_ auftrag: String) {
        send(RenderCancelMessage(id: nextRequestID(), auftrag: auftrag))
    }

    public func renderImFinderZeigen(_ url: URL) {
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }

    /// Größe aus dem Dialog; mit Kamera aus model.py die Höhe aus deren Seitenverhältnis.
    func renderGroesse() -> (Int, Int) {
        let g = model.render.groesseWerte
        if let k = model.render.kamera, let c = cameras.camera(k), c.aufloesung.x > 0 {
            return (g.breite, max(16, Int((Double(g.breite) * Double(c.aufloesung.y) / Double(c.aufloesung.x)).rounded())))
        }
        return (g.breite, g.hoehe)
    }

    // MARK: Produktbild für den Export (Phase 6, Baustein „Produktbild“)

    /// Produktbild für das PDF: das jüngste Rendering aus output/renders/, wenn es nach dem letzten Lauf entstand,
    /// sonst ein schnelles Studio-Bild aus der Produktansicht. Mit Kernel über RENDER_START (Materialien aus dem
    /// Katalog, als Vorschau-Auftrag), ohne Kernel direkt mit den Materialien des letzten Auftrags bzw. Teilfarben.
    func exportProduktbild(breite: Int = 2400, hoehe: Int = 1600) async -> (bild: CGImage, quelle: String)? {
        if let (url, datum) = Self.juengstesRendering(model.project?.path), datum > letzterLaufZeitpunkt,
            let img = Self.ladeBild(url)
        {
            return (img, url.lastPathComponent)
        }
        if connected, model.project != nil {
            var auftrag: String?
            var abgelehnt = false
            let msg = RenderStartMessage(id: nextRequestID(), szene: "studio", ansicht: "produkt", breite: breite,
                                         hoehe: hoehe, qualitaet: "schnell", vorschau: true)
            request(msg, timeout: 20) { result in
                if case .success(.ack(let a)) = result, a.ok { auftrag = a.message } else { abgelehnt = true }
            }
            let store = model.render
            _ = await exportWarte(60) {
                abgelehnt || (auftrag != nil && store.letzteVorschau?.auftrag == auftrag
                              && store.letzteVorschau?.zustand.istEnde == true)
            }
            if let s = store.letzteVorschau, s.auftrag == auftrag, s.zustand == .fertig, let p = s.pfad,
                let img = Self.ladeBild(URL(fileURLWithPath: p))
            {
                return (img, "Studio, schnell (RealityKit)")
            }
        }
        let a = RenderAuftrag(id: "export", auftrag: "export", szene: RenderSzene(), ansicht: "produkt", kamera: nil,
                              width: breite, height: hoehe, teile: letzteRenderMaterialien, path: "")
        guard let e = try? await renderBild(a) else { return nil }
        return (e.bild, "Studio, schnell (RealityKit)")
    }

    static func ladeBild(_ url: URL) -> CGImage? {
        guard let src = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
        return CGImageSourceCreateImageAtIndex(src, 0, nil)
    }

    static func juengstesRendering(_ projekt: URL?) -> (URL, Date)? {
        guard let dir = projekt?.appendingPathComponent("output/renders", isDirectory: true),
            let dateien = try? FileManager.default.contentsOfDirectory(
                at: dir, includingPropertiesForKeys: [.contentModificationDateKey], options: [.skipsHiddenFiles])
        else { return nil }
        return dateien.filter { $0.pathExtension.lowercased() == "png" }
            .compactMap { u -> (URL, Date)? in
                guard let d = try? u.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate
                else { return nil }
                return (u, d)
            }
            .max { $0.1 < $1.1 }
    }
}
