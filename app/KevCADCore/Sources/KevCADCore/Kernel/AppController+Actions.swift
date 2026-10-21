import AppKit
import Foundation
import OCCTSwiftViewport
import simd

// AppActions: alles, was die Oberfläche auslösen kann.

extension AppController {
    // MARK: Projekte und Läufe

    public func openProject(at url: URL) {
        if AppInfo.isDemoMode {
            demoOpen(url)
            return
        }
        whenKernelReady { [weak self] in
            guard let self else { return }
            let msg = ProjectOpenMessage(id: self.nextRequestID(), path: url.path)
            self.request(msg, timeout: 60) { result in self.projectReply(result, action: "öffnen") }
        }
    }

    public func newProject(at url: URL, template: String) {
        if AppInfo.isDemoMode {
            demoOpen(url)
            return
        }
        whenKernelReady { [weak self] in
            guard let self else { return }
            let msg = ProjectNewMessage(id: self.nextRequestID(), path: url.path, template: template)
            self.request(msg, timeout: 60) { result in self.projectReply(result, action: "anlegen") }
        }
    }

    private func projectReply(_ result: Result<KernelMessage, RequestError>, action: String) {
        switch result {
        case .success(.project):
            // schon in handle(_:) übernommen; nach einem Update gleich rechnen, damit die Teile wieder da sind
            if pendingRestore != nil { runModel() }
        case .success(let m): log(.warning, "Projekt \(action): unerwartete Antwort \(m.typeName)")
        case .failure(let e): log(.error, "Projekt \(action) fehlgeschlagen: \(e.message)")
        }
    }

    /// Projektaufträge, bevor der Kernel bereit ist, werden nach HELLO nachgeholt.
    private func whenKernelReady(_ work: @escaping () -> Void) {
        if helloReceived {
            work()
        } else {
            queuedProjectRequest = work
            log(.info, "Kernel ist noch nicht bereit, Auftrag folgt nach dem Start")
        }
    }

    public func runModel() {
        if AppInfo.isDemoMode {
            demoRun()
            return
        }
        let msg = RunRequestMessage(
            id: nextRequestID(), params: nil, slowMs: model.slowMotion ? Self.slowMotionMs : 0)
        request(msg, timeout: 600) { [weak self] result in
            switch result {
            case .success(.ack(let a)) where !a.ok:
                self?.log(.warning, "Lauf abgelehnt: \(a.message ?? "ohne Grund")")
            case .failure(let e):
                self?.log(.error, "Lauf nicht gestartet: \(e.message)")
            default:
                break
            }
        }
    }

    // MARK: Sichtbarkeit

    public func setVisibility(_ partIDs: [String], visible: Bool) {
        scene.setVisible(partNames(partIDs), visible)
        updateParts()
        refreshOverlay()
    }

    public func isolate(_ partIDs: [String]) {
        scene.isolate(partNames(partIDs))
        updateParts()
        refreshOverlay()
    }

    public func showAll() {
        scene.showAll()
        updateParts()
        refreshOverlay()
    }

    // MARK: Kamera

    /// Teil- oder Baugruppennamen → Teilnamen.
    private func partNames(_ ids: [String]) -> [String] {
        scene.expand(ids.compactMap(ElementRef.init).map(\.partRef)).known.map(\.part)
    }

    public func focus(on refs: [String]) {
        let parsed = scene.expand(refs.compactMap(ElementRef.init)).known
        guard let b = scene.worldBounds(of: parsed) else {
            log(.warning, "Einpassen: nichts gefunden für \(refs.joined(separator: ", "))")
            return
        }
        viewport.fit(b, animated: true)
    }

    public func select(_ refs: [String]) {
        measurePending = []
        applySelection(refs.compactMap(ElementRef.init))
    }

    public func setStandardView(_ view: StandardViewName) {
        let sv = ViewportCoordinator.standardView(view)
        viewport.apply(rotation: sv.rotation, orthographic: nil, fitTo: scene.visibleBounds(), animated: true)
    }

    // MARK: Darstellung

    public func setDisplayStyle(_ style: DisplayStyle) { applyDisplayStyle(style) }

    public func setSection(enabled: Bool, axis: String, offset: Double) {
        applySection(enabled: enabled, normal: Self.axisVector(axis), offset: Float(offset))
    }

    public func setExplode(_ factor: Double) { applyExplode(factor) }

    func applyDisplayStyle(_ style: DisplayStyle) {
        scene.setDisplayStyle(style)
        viewport.controller.displayMode = scene.viewportDisplayMode
        model.displayStyle = style
    }

    func applySection(enabled: Bool, normal: SIMD3<Float>?, offset: Float) {
        scene.setSection(normal: enabled ? normal : nil, offset: offset)
        viewport.controller.clipPlanes = scene.section.map { [$0] } ?? []
        model.sectionEnabled = scene.section != nil
    }

    func applyExplode(_ factor: Double) {
        scene.setExplode(Float(factor))
        model.explodeFactor = Double(scene.explodeFactor)
        refreshOverlay()
    }

    static func axisVector(_ axis: String) -> SIMD3<Float>? {
        switch axis.lowercased() {
        case "x": return SIMD3(1, 0, 0)
        case "y": return SIMD3(0, 1, 0)
        case "z": return SIMD3(0, 0, 1)
        case "-x": return SIMD3(-1, 0, 0)
        case "-y": return SIMD3(0, -1, 0)
        case "-z": return SIMD3(0, 0, -1)
        default: return nil
        }
    }

    // MARK: Messen

    public func setMeasureMode(_ on: Bool) {
        model.measureMode = on
        measurePending = []
        updateMeasureHint()
    }

    public func clearMeasurements() {
        model.measurements = []
        // Auch die Maße, die der Agent mit measure(show=True) eingeblendet hat (kommen zusätzlich als Anmerkung)
        removeDimensionAnnotations(matching: nil)
        refreshOverlay()
    }

    /// Eingeblendete Maße (Anmerkungen der Art dimension) entfernen: alle oder nur die mit diesen Endpunkten.
    func removeDimensionAnnotations(matching points: [SIMD3<Float>]?) {
        annotations.removeAll { ann in
            guard case .dimension(let a, let b, _, _) = ann.item else { return false }
            guard let points, points.count >= 2 else { return true }
            return Self.samePair(a, b, points[0], points[1])
        }
    }

    static func samePair(_ a: SIMD3<Float>, _ b: SIMD3<Float>, _ c: SIMD3<Float>, _ d: SIMD3<Float>) -> Bool {
        let eps: Float = 1e-3
        return (simd_distance(a, c) < eps && simd_distance(b, d) < eps)
            || (simd_distance(a, d) < eps && simd_distance(b, c) < eps)
    }

    // MARK: Einstellungen

    public func setAutoRun(_ on: Bool) {
        model.autoRun = on
        sendSettings()
    }

    public func setSlowMotion(_ on: Bool) {
        model.slowMotion = on
        sendSettings()
    }

    // MARK: Export und Bild

    public func export(formats: [String]) {
        if AppInfo.isDemoMode {
            log(.info, "Demomodus: kein Export")
            return
        }
        let msg = ExportRequestMessage(id: nextRequestID(), formats: formats, parts: nil)
        request(msg, timeout: 600) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.exportResponse(let e)):
                self.log(.info, "Export fertig: " + (e.files.isEmpty ? "keine Dateien" : e.files.joined(separator: ", ")))
                // Stückliste: die CSV-Datei gleich im Finder zeigen (öffnet von dort in Numbers oder Excel)
                if formats.contains("bom_csv") {
                    let csv = e.files.filter { $0.lowercased().hasSuffix(".csv") }
                    self.revealFiles((csv.isEmpty ? e.files : csv).map { URL(fileURLWithPath: $0) })
                }
            case .success(let m):
                self.log(.warning, "Export: unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                self.log(.error, "Export fehlgeschlagen: \(e.message)")
            }
        }
    }

    /// Bild der aktuellen Ansicht in `<Projekt>/output/` (ohne Projekt auf den Schreibtisch).
    public func saveScreenshot() {
        let px = viewport.controller.drawablePixelSize
        let w = px.width > 16 ? Int(px.width) : 2560
        let h = px.height > 16 ? Int(px.height) : 1600
        guard
            let r = screenshots.render(
                bodies: scene.snapshotBodies(), camera: viewport.camera, width: w, height: h,
                displayMode: scene.viewportDisplayMode, lighting: viewport.controller.lightingConfiguration,
                overlay: overlayItems())
        else {
            log(.error, "Bild ließ sich nicht rendern")
            return
        }
        let dir =
            model.project?.path.appendingPathComponent("output", isDirectory: true)
            ?? FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask)[0]
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd-HHmmss"
        let url = dir.appendingPathComponent("Bild-\(f.string(from: Date())).png")
        do {
            try r.png.write(to: url)
            log(.info, "Bild gespeichert: \(url.path)")
        } catch {
            log(.error, "Bild nicht gespeichert: \(error.localizedDescription)")
        }
    }

    public func restartKernel() {
        log(.info, "Kernel wird neu gestartet")
        resetCrashCounter()
        start()
    }
}

// Ergänzung der Oberfläche (AP4, MeasurementRemoving in AppModel.swift): eine einzelne Messung löschen.
extension AppController: MeasurementRemoving {
    public func removeMeasurement(id: UUID) {
        if let m = model.measurements.first(where: { $0.id == id }) {
            removeDimensionAnnotations(matching: m.points)
        }
        model.measurements.removeAll { $0.id == id }
        refreshOverlay()
    }
}

// MARK: - Ansichtsbefehle und Bilder für den Kernel

extension AppController {
    /// Führt ein VIEW_CMD aus. Rückgabe für das ACK.
    func performViewCommand(_ v: ViewCommandMessage) -> (Bool, String?) {
        let a = v.args
        func refs(_ key: String = "refs") -> [ElementRef] {
            (a[key]?.stringList ?? a[key]?.stringValue.map { [$0] } ?? []).compactMap(ElementRef.init)
        }
        switch v.cmd {
        case "view":
            var rotation: simd_quatf?
            if let name = a["standard"]?.stringValue {
                guard let sv = ViewportCoordinator.standardView(protocolName: name) else {
                    return (false, "Unbekannte Ansicht \(name)")
                }
                rotation = sv.rotation
            }
            var ortho: Bool?
            switch a["projection"]?.stringValue {
            case "orthographic"?: ortho = true
            case "perspective"?: ortho = false
            case nil: break
            case let p?: return (false, "Unbekannte Projektion \(p)")
            }
            if let d = a["display"]?.stringValue {
                guard let style = Self.displayStyle(protocolName: d) else { return (false, "Unbekannte Darstellung \(d)") }
                applyDisplayStyle(style)
            }
            let fit = a["fit"]?.boolValue ?? false
            viewport.apply(rotation: rotation, orthographic: ortho, fitTo: fit ? scene.visibleBounds() : nil, animated: true)
            return (true, nil)

        case "focus":
            let (known, missing) = scene.expand(refs())
            guard let b = scene.worldBounds(of: known) else {
                return (false, "Unbekannte Referenz: \(missing.joined(separator: ", "))")
            }
            viewport.fit(b, animated: a["animate"]?.boolValue ?? true)
            return (true, missing.isEmpty ? nil : "Nicht gefunden: \(missing.joined(separator: ", "))")

        case "visibility":
            let mode = a["mode"]?.stringValue ?? "show"
            let (hits, missing) = scene.expand(refs().map(\.partRef))
            let known = hits.map(\.part)
            switch mode {
            case "show": scene.setVisible(known, true)
            case "hide": scene.setVisible(known, false)
            case "isolate":
                guard !known.isEmpty else { return (false, "Keine bekannten Teile") }
                scene.isolate(known)
            case "show_all": scene.showAll()
            default: return (false, "Unbekannter Modus \(mode)")
            }
            updateParts()
            refreshOverlay()
            if mode != "show_all" && !missing.isEmpty {
                return (!known.isEmpty, "Nicht gefunden: \(missing.joined(separator: ", "))")
            }
            return (true, nil)

        case "highlight":
            let list = refs()
            let clear = a["clear"]?.boolValue ?? false
            if list.isEmpty {
                if clear {
                    scene.clearHighlights()
                    annotations.removeAll { highlightLabels.values.contains($0.id) }
                    highlightLabels = [:]
                    refreshOverlay()
                    return (true, nil)
                }
                return (false, "Keine Referenzen")
            }
            if clear {
                annotations.removeAll { highlightLabels.values.contains($0.id) }
                highlightLabels = [:]
            }
            let (known, missing) = scene.expand(list)
            let color = a["color"]?.vector4
            let h = scene.addHighlight(refs: known, color: color, label: a["label"]?.stringValue, clear: clear)
            if let label = h.label, !label.isEmpty, let first = known.first, let p = scene.worldAnchor(of: first) {
                let id = "hl-\(h.id)"
                annotations.append((id, .label(point: p, text: label, color: h.overlayColor)))
                highlightLabels[h.id] = id
            }
            refreshOverlay()
            startAnimationTimerIfNeeded()
            if known.isEmpty { return (false, "Unbekannte Referenz: \(missing.joined(separator: ", "))") }
            return (true, missing.isEmpty ? nil : "Nicht gefunden: \(missing.joined(separator: ", "))")

        case "section":
            let enabled = a["enabled"]?.boolValue ?? true
            var normal: SIMD3<Float>?
            if let n = a["normal"]?.vector3 {
                normal = n
            } else if let ax = a["axis"]?.stringValue {
                normal = Self.axisVector(ax)
                if normal == nil { return (false, "Unbekannte Achse \(ax)") }
            } else {
                normal = SIMD3(0, 0, 1)
            }
            let offset = Float(a["offset"]?.doubleValue ?? 0)
            applySection(enabled: enabled, normal: normal, offset: offset)
            return (true, nil)

        case "explode":
            applyExplode(a["factor"]?.doubleValue ?? 0)
            return (true, nil)

        case "annotate":
            let kind = a["kind"]?.stringValue ?? "label"
            let pts = (a["points"]?.arrayValue ?? []).compactMap(\.vector3)
            let text = a["text"]?.stringValue ?? ""
            let id = a["id"]?.stringValue ?? "anm-\(annotations.count + 1)-\(Int(Date().timeIntervalSince1970))"
            let item: OverlayPrimitive
            switch kind {
            case "dimension":
                guard pts.count >= 2 else { return (false, "Maß braucht zwei Punkte") }
                // Gehört das Maß zu einer Messung, die schon in der Liste steht, nicht doppelt zeichnen
                if model.measurements.contains(where: {
                    $0.points.count >= 2 && Self.samePair($0.points[0], $0.points[1], pts[0], pts[1])
                }) {
                    return (true, id)
                }
                let t = text.isEmpty ? "\(GermanFormat.mm(Double(simd_distance(pts[0], pts[1]))))" : text
                item = .dimension(a: pts[0], b: pts[1], text: t, color: Self.annotationColor)
            case "arrow":
                guard pts.count >= 2 else { return (false, "Pfeil braucht zwei Punkte") }
                item = .arrow(from: pts[0], to: pts[1], text: text, color: Self.annotationColor)
            case "label":
                guard let p = pts.first else { return (false, "Beschriftung braucht einen Punkt") }
                item = .label(point: p, text: text, color: Self.annotationColor)
            default:
                return (false, "Unbekannte Art \(kind)")
            }
            annotations.removeAll { $0.id == id }
            annotations.append((id, item))
            refreshOverlay()
            return (true, id)

        case "clear_annotations":
            if let ids = a["ids"]?.stringList {
                let set = Set(ids)
                annotations.removeAll { set.contains($0.id) }
            } else {
                annotations.removeAll { !highlightLabels.values.contains($0.id) }
            }
            refreshOverlay()
            return (true, nil)

        default:
            return (false, "Unbekannter Befehl \(v.cmd)")
        }
    }

    static func displayStyle(protocolName: String) -> DisplayStyle? {
        switch protocolName {
        case "shaded_edges": return .shadedEdges
        case "shaded": return .shaded
        case "wireframe": return .wireframe
        case "xray": return .xray
        default: return nil
        }
    }

    /// SCREENSHOT_REQ beantworten: aktuelle Ansicht (gleiche Kamera, Sichtbarkeit, Schnitt, Hervorhebungen) oder
    /// offscreen aus einer Standardansicht, eingepasst auf die sichtbaren Teile.
    func answerScreenshot(_ s: ScreenshotRequestMessage) {
        // Kommt die Anfrage direkt nach view/focus, läuft die Kamerafahrt noch: erst deren Ende abwarten (höchstens
        // 1,5 s, falls das Fenster gerade nicht zeichnet und die Fahrt deshalb nicht weiterläuft).
        if s.source != "offscreen" {
            waitForCameraIdle(until: CACurrentMediaTime() + 1.5) { [weak self] in self?.renderScreenshot(s) }
        } else {
            renderScreenshot(s)
        }
    }

    private func waitForCameraIdle(until deadline: CFTimeInterval, _ done: @escaping () -> Void) {
        if !viewport.controller.isAnimating || CACurrentMediaTime() > deadline {
            done()
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.03) { [weak self] in
            self?.waitForCameraIdle(until: deadline, done)
        }
    }

    private func renderScreenshot(_ s: ScreenshotRequestMessage) {
        let w = max(16, min(s.width, 8192)), h = max(16, min(s.height, 8192))
        var camera = viewport.camera
        if s.source == "offscreen", let name = s.view {
            guard let sv = ViewportCoordinator.standardView(protocolName: name) else {
                send(
                    ScreenshotResponseMessage(
                        replyTo: s.id, ok: false, width: 0, height: 0, camera: .null, mmPerPx: nil,
                        message: "Unbekannte Ansicht \(name)"))
                return
            }
            camera = sv.cameraState(distance: 1000, orthographicScale: 100)
            if let b = scene.visibleBounds() {
                camera = ViewportCoordinator.fitted(camera, to: b, aspect: Float(w) / Float(h))
            }
        }
        let started = CACurrentMediaTime()
        guard
            let r = screenshots.render(
                bodies: scene.snapshotBodies(), camera: camera, width: w, height: h,
                displayMode: scene.viewportDisplayMode, lighting: viewport.controller.lightingConfiguration,
                overlay: s.hideOverlays ? [] : overlayItems())
        else {
            send(
                ScreenshotResponseMessage(
                    replyTo: s.id, ok: false, width: 0, height: 0, camera: .null, mmPerPx: nil,
                    message: "Bild ließ sich nicht rendern"))
            return
        }
        let ms = Int((CACurrentMediaTime() - started) * 1000)
        log(.info, "Bild für den Kernel: \(w) × \(h) in \(ms) ms (\(r.png.count / 1024) kB)")
        send(
            ScreenshotResponseMessage(
                replyTo: s.id, ok: true, width: w, height: h, camera: ViewportCoordinator.cameraJSON(camera, height: h),
                mmPerPx: r.mmPerPixel),
            payload: r.png)
    }
}
