#if os(macOS)
import AppKit
#endif
import Foundation
import OCCTSwiftViewport
import QuartzCore
import simd

// Selbsttest des Viewers (V2) in der Testvariante, ohne Maus und Tastatur: KEVCAD_SELFTEST=viewer.
//
// Öffnet KEVCAD_SELFTEST_PROJEKT (falls gesetzt), wartet auf den ersten Lauf und geht die neuen Zustände durch:
// Hinweisleiste, Ansichtsmenü, Darstellungsmenü, Tastenübersicht, lokale Ansicht mit Hauch, Achsansicht, Messen mit
// Vorschau und Fangpunkten, Darstellungsarten. Vor jedem Zustand steht im Protokoll (stderr) „FOTO <name>“; ein Skript
// außen fotografiert dann das Fenster (screencapture -l). Zum Schluss misst er Bildzeiten beim Drehen (3 s je
// Darstellung) und schreibt alles nach KEVCAD_SELFTEST_AUSGABE/selftest-viewer.txt.

extension AppController {
    static var viewerSelbsttestGewuenscht: Bool {
        AppInfo.isTestVariant && ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "viewer"
    }

    static var viewerSelbsttestAusgabe: URL {
        if let p = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_AUSGABE"], !p.isEmpty {
            return URL(fileURLWithPath: p, isDirectory: true)
        }
        return AppInfo.supportDirectory.appendingPathComponent("selftest-viewer", isDirectory: true)
    }

    /// Nach HELLO: Projekt des Selbsttests öffnen.
    func viewerSelbsttestProjektOeffnen() {
        let selbsttest = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"]
        guard Self.viewerSelbsttestGewuenscht || Self.sprachSelbsttestGewuenscht || (AppInfo.isTestVariant && selbsttest == "core"),
            model.project == nil, let p = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_PROJEKT"], !p.isEmpty
        else { return }
        openProject(at: URL(fileURLWithPath: p, isDirectory: true))
    }

    /// Nach dem ersten fertigen Lauf: Selbsttest starten.
    func viewerSelbsttestPlanen() {
        guard Self.viewerSelbsttestGewuenscht, !viewerSelbsttestLaeuft, !model.parts.isEmpty else { return }
        viewerSelbsttestLaeuft = true
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(2))
            await self?.viewerSelbsttest()
        }
    }

    private func pause(_ s: Double) async { try? await Task.sleep(for: .milliseconds(Int(s * 1000))) }

    /// Warten, bis der Kernel `ruhe` Sekunden nichts mehr geschickt hat (Prüfung und Statik kommen nach dem Lauf),
    /// höchstens `bis` Sekunden; gibt die gewartete Zeit zurück.
    func kernelRuhe(_ ruhe: Double = 3, bis: Double = 120) async -> Double {
        let t0 = CACurrentMediaTime()
        while CACurrentMediaTime() - letzteKernelNachricht < ruhe && CACurrentMediaTime() - t0 < bis {
            await pause(0.25)
        }
        return CACurrentMediaTime() - t0
    }

    /// Das Modell ohne Kulisse (Boden, Wände) einrahmen und die Fahrt abwarten.
    private func modellEinrahmen() async {
        let teile = scene.order.filter { !$0.hasPrefix("Kulisse/") && scene.isVisible($0) }
        focus(on: teile.isEmpty ? scene.order : teile)
        await pause(0.5)
    }

    private func foto(_ name: String) async {
        await pause(0.6)  // Kamerafahrten und Einblendungen ablaufen lassen
        log(.info, "Selbsttest Viewer: FOTO \(name)")
        await pause(1.4)  // Zeit für das Foto von außen
    }

    func viewerSelbsttest() async {
        var zeilen: [String] = []
        var bestanden = true
        func pruefe(_ ok: Bool, _ text: String) {
            bestanden = bestanden && ok
            let z = "\(ok ? "OK    " : "FEHLER") \(text)"
            zeilen.append(z)
            log(ok ? .info : .error, "Selbsttest Viewer: \(z)")
        }
        try? FileManager.default.createDirectory(at: Self.viewerSelbsttestAusgabe, withIntermediateDirectories: true)
        log(.info, "Selbsttest Viewer: \(model.parts.count) Teile, \(model.triangleCount) Dreiecke")

        // 1. Ausgangslage mit Hinweisleiste (vorher darf der Kernel seine Prüf- und Statik-Ergebnisse schicken)
        let gewartet = await kernelRuhe()
        log(.info, "Selbsttest Viewer: Kernel ruhig nach \(String(format: "%.1f", gewartet)) s")
        await modellEinrahmen()
        orbitStep(yaw: 25, pitch: -10)
        await pause(0.3)
        await foto("01-start")
        pruefe(viewer.hinweisleiste, "Hinweisleiste an")

        // 2. Menüs und Übersicht (über die Belegung, wie die Tasten ^, Z, ?)
        ausfuehren(.ansichtMenue)
        pruefe(viewer.menue == .ansicht, "Ansichtsmenü offen")
        await foto("02-ansichtsmenue")
        ausfuehren(.abbrechen)
        pruefe(viewer.menue == nil, "Esc schließt das Menü")
        ausfuehren(.shadingMenue)
        await foto("03-darstellungsmenue")
        ausfuehren(.abbrechen)
        ausfuehren(.tastenuebersicht)
        pruefe(viewer.tastenuebersicht, "Tastenübersicht offen")
        await foto("04-tastenuebersicht")
        ausfuehren(.tastenuebersicht)

        // 3. Achsansichten (weich, parallel) und Projektion
        ausfuehren(.vorne)
        await pause(0.4)
        pruefe(viewport.camera.isOrthographic && ViewportCoordinator.nearestStandardName(viewport.camera) == "front",
               "1: vorne, parallel")
        ausfuehren(.hinten)
        await pause(0.4)
        pruefe(ViewportCoordinator.nearestStandardName(viewport.camera) == "back", "Strg+1: hinten")
        ausfuehren(.projektion)
        await pause(0.4)
        pruefe(!viewport.camera.isOrthographic, "5: perspektivisch")
        orbitStep(yaw: 30, pitch: -20)
        await pause(0.3)
        await modellEinrahmen()

        // 4. Lokale Ansicht mit Hauch und zurück
        let groesstes = model.parts.filter { !$0.id.hasPrefix("Kulisse/") }.max { $0.triangles < $1.triangles }?.id
        if let g = groesstes {
            select([g])
            await pause(0.3)  // Kamera steht (sonst stimmt der Vergleich unten nicht)
            let vorher = viewport.camera
            ausfuehren(.isolieren)
            let gemerkt = localView?.camera
            pruefe(viewer.lokaleAnsicht && scene.hauchTeile.count == max(0, scene.order.count - 1),
                   "/: lokale Ansicht, \(scene.hauchTeile.count) Teile als Hauch")
            await foto("05-lokal-hauch")
            ausfuehren(.isolieren)
            await pause(0.5)
            pruefe(!viewer.lokaleAnsicht && scene.hauchTeile.isEmpty, "/: zurück, alles wieder sichtbar")
            let d = simd_distance(viewport.camera.position, vorher.position)
            let dGemerkt = gemerkt.map { simd_distance($0.position, vorher.position) } ?? -1
            pruefe(d < max(1, vorher.distance * 0.01),
                   "/: Kamera wiederhergestellt (Abweichung \(String(format: "%.2f", d)) mm, gemerkt \(String(format: "%.2f", dGemerkt)) mm, Fahrt \(viewport.kameraBewegtSich ? "läuft" : "fertig"))")
            select([])
        }

        // 5. Messen: Vorschau einer Kreiskante, zwei Fangpunkte
        await modellEinrahmen()
        await messenPruefen(pruefe)

        // 6. Darstellungsarten
        await modellEinrahmen()
        orbitStep(yaw: -35, pitch: -12)
        await pause(0.3)
        for m in ShadingModus.allCases {
            setShading(m)
            await foto("07-darstellung-\(m.rawValue)")
        }
        setShading(.solid)

        // 7. Bild und Video mit einem Klick
        bildschirmfoto(.doppelt)
        let bild = viewer.meldung?.datei
        pruefe(bild.map { FileManager.default.fileExists(atPath: $0.path) } ?? false,
               "Bildschirmfoto: \(viewer.meldung?.text ?? "-")")
        videoDrehung()
        let t0 = CACurrentMediaTime()
        while viewer.aufnahme.laeuft && CACurrentMediaTime() - t0 < 180 { await pause(0.25) }
        let video = viewer.meldung?.datei
        pruefe(video?.pathExtension == "mp4" && FileManager.default.fileExists(atPath: video!.path),
               "Video Drehung: \(viewer.meldung?.text ?? "-") in \(String(format: "%.1f", CACurrentMediaTime() - t0)) s")
        navigationAufnehmen()
        orbitStep(yaw: 40, pitch: 0)
        await pause(0.5)
        orbitStep(yaw: 0, pitch: -15)
        await pause(0.6)
        navigationAufnehmen()
        let t1 = CACurrentMediaTime()
        while viewer.aufnahme.laeuft && CACurrentMediaTime() - t1 < 120 { await pause(0.25) }
        pruefe(viewer.meldung?.datei?.lastPathComponent.hasPrefix("Navigation") == true,
               "Mitschnitt: \(viewer.meldung?.text ?? "-")")

        // 8. Bildzeiten beim Drehen
        _ = await kernelRuhe()
        await modellEinrahmen()
        let zeiten = await bildzeitenMessen()
        zeilen.append(contentsOf: zeiten)

        let bericht = (["Selbsttest Viewer: \(bestanden ? "bestanden" : "NICHT bestanden")"] + zeilen)
            .joined(separator: "\n")
        try? bericht.write(to: Self.viewerSelbsttestAusgabe.appendingPathComponent("selftest-viewer.txt"),
                           atomically: true, encoding: .utf8)
        log(.info, "Selbsttest Viewer fertig")
    }

    /// Kreiskante suchen, Vorschau zeigen lassen, dann zwei Fangpunkte messen.
    private func messenPruefen(_ pruefe: (Bool, String) -> Void) async {
        setMeasureMode(true)
        let size = viewport.viewSize
        let projector = OverlayProjector(camera: viewport.camera, size: size)
        var kreis: (ElementRef, CGPoint)?
        var ecken: [(ElementRef, CGPoint)] = []
        for name in scene.order where scene.isVisible(name) {
            guard let rec = scene.record(name) else { continue }
            for (i, e) in rec.header.edges.enumerated() where kreis == nil && e.t == "circle" {
                let poly = rec.geometry.edgePolyline(i)
                guard let p = poly.first, let s = projector.project(weltpunktTest(name, p)),
                    s.x > 40, s.y > 40, s.x < size.width - 40, s.y < size.height - 80
                else { continue }
                kreis = (.edge(name, i), s)
            }
            if ecken.count < 2, rec.vertexCount > 0 {
                let p = rec.geometry.brepVertex(0)
                if let s = projector.project(weltpunktTest(name, p)), s.x > 40, s.y > 40, s.x < size.width - 40,
                    s.y < size.height - 80
                {
                    ecken.append((.vertex(name, 0), s))
                }
            }
        }
        if let (ref, s) = kreis {
            messVorschauSetzen(ref, bildpunkt: CGPoint(x: s.x + 30, y: s.y + 30))  // neben der Kante: kein Fang
            pruefe(viewport.eingabe.unterMaus?.contains("Ø") == true,
                   "Vorschau Kreiskante: „\(viewport.eingabe.unterMaus ?? "-")“")
            await foto("06-messen-kreis")
        } else {
            pruefe(false, "keine Kreiskante im Bild gefunden")
        }
        if ecken.count == 2 {
            for (ref, s) in ecken {
                messVorschauSetzen(ref, bildpunkt: s)
                pruefe(aktuellerFang?.art == .ecke,
                       "Fang an Ecke \(ref.string): \(aktuellerFang.map { "\($0.art.titel) \($0.ref.string)" } ?? "kein Fang")")
                messKlick(ref)
            }
            await pause(1.5)
            pruefe(!model.measurements.isEmpty, "Messung Ecke–Ecke: \(model.measurements.last?.text ?? "-")")
            await foto("06b-messung")
        }
        setMeasureMode(false)
    }

    private func weltpunktTest(_ teil: String, _ p: SIMD3<Float>) -> SIMD3<Float> {
        let v = scene.worldTransform(teil) * SIMD4(p, 1)
        return SIMD3(v.x, v.y, v.z)
    }

    /// Dreht 3 s um die Senkrechte (eine volle Umdrehung) je Darstellung und wertet die Bildzeiten aus.
    private func bildzeitenMessen() async -> [String] {
        var out = ["", "Bildzeiten beim Drehen (3 s, eine Umdrehung, \(model.parts.count) Teile, \(model.triangleCount) Dreiecke):"]
        let faelle: [(String, ShadingModus, ShadingOptionen)] = {
            var ohne = ShadingOptionen()
            ohne.umgebungsverdeckung = false
            ohne.kantenbetonung = false
            var nackt = ohne
            nackt.kanten = false
            var mit = ShadingOptionen()
            mit.schatten = false
            var alles = ShadingOptionen()
            alles.schatten = true
            return [("Solid ohne Verdeckung, ohne Kanten", .solid, nackt),
                    ("Solid ohne Verdeckung (Kanten, Silhouetten)", .solid, ohne),
                    ("Solid mit Verdeckung und Kantenbetonung", .solid, mit),
                    ("Solid mit allem und Schatten", .solid, alles),
                    ("Material mit Verdeckung", .material, mit),
                    ("Technisch", .technisch, mit)]
        }()
        let vorher = (viewer.shading, viewer.optionen)
        // Vergleich: der Renderweg vor V2 (SSAO des Pakets mit Radius 0,8 und Stärke 0,8, Silhouetten, Kanten)
        do {
            viewer.optionen = ShadingOptionen()
            setShading(.solid)
            viewport.controller.lightingConfiguration = ViewportCoordinator.zUpLighting
            await pause(0.8)
            if let z = await drehungMessen(sekunden: 3) {
                let d = durchsatz()
                let gross = durchsatz(breite: 2560, hoehe: 1600)
                out.append("  wie bisher (SSAO des Pakets, Silhouetten, Kanten): \(z); \(d); \(gross)")
                log(.info, "Selbsttest Viewer: Bildzeiten wie bisher: \(z); \(d); \(gross)")
            }
        }
        for (titel, modus, optionen) in faelle {
            viewer.optionen = optionen
            setShading(modus)
            await pause(0.8)
            if let z = await drehungMessen(sekunden: 3) {
                let d = durchsatz()
                let gross = durchsatz(breite: 2560, hoehe: 1600)
                out.append("  \(titel): \(z); \(d); \(gross)")
                log(.info, "Selbsttest Viewer: Bildzeiten \(titel): \(z); \(d); \(gross)")
            } else {
                out.append("  \(titel): keine Messung (Renderer nicht gefunden)")
            }
        }
        viewer.optionen = vorher.1
        setShading(vorher.0)
        return out
    }

    /// Wie viele Bilder je Sekunde der Viewport ohne Bildschirmtakt schafft: dieselben Durchgänge wie im Viewport
    /// (zweiter Renderer, Größe des Zeichenpuffers), 120 Bilder hintereinander, gemessen bis die GPU fertig ist.
    private func durchsatz(breite: Int? = nil, hoehe: Int? = nil) -> String {
        var px = viewport.controller.drawablePixelSize
        if let breite, let hoehe { px = CGSize(width: breite, height: hoehe) }
        guard px.width > 16, px.height > 16 else { return "Durchsatz: kein Zeichenpuffer" }
        let ansicht = offlineAnsicht()
        _ = ansicht.bild(kamera: viewport.camera, breite: Int(px.width), hoehe: Int(px.height),
                         hintergrund: hintergrundFarbe)  // Puffer anlegen
        let n = 120
        let t0 = CACurrentMediaTime()
        let ok = ansicht.serie(kamera: viewport.camera, breite: Int(px.width), hoehe: Int(px.height),
                               hintergrund: hintergrundFarbe, bilder: n)
        let s = CACurrentMediaTime() - t0
        guard ok else { return "Durchsatz: fehlgeschlagen" }
        return String(format: "ohne Bildschirmtakt %.0f Bilder/s (%d × %d)", Double(n) / s, Int(px.width), Int(px.height))
    }

    /// Eine Umdrehung in `sekunden` im Bildschirmtakt; Bildzeiten aus dem Renderer.
    func drehungMessen(sekunden: Double) async -> String? {
        guard let renderer = viewport.renderer, let view = viewport.mtkView else { return nil }
        let sammler = BildzeitSammler()
        renderer.onFrameTiming = { sammler.zeiten.append($0) }
        let takt = SelbsttestTakt()
        let start = CACurrentMediaTime()
        var letzte = start
        var taktAbstaende: [Double] = []  // Hauptfaden: Abstände der Takte (Hänger dort = Hauptfaden blockiert)
        var letzterTakt = CACurrentMediaTime()
        takt.schritt = { [weak self] jetzt in
            guard let self else { return }
            let nun = CACurrentMediaTime()
            taktAbstaende.append((nun - letzterTakt) * 1000)
            letzterTakt = nun
            let dt = jetzt - letzte
            letzte = jetzt
            // 360° in `sekunden`: 0,4° je Punkt
            self.viewport.navOrbit(dx: Float(360 / 0.4 / sekunden * dt), dy: 0)
        }
        let link = view.bildschirmtakt(takt, #selector(SelbsttestTakt.tick(_:)))
        link.add(to: .main, forMode: .common)
        let protokoll = HauptfadenProtokoll()
        hauptfadenProtokoll = protokoll
        protokoll.start()
        await pause(sekunden)
        link.invalidate()
        protokoll.stop()
        hauptfadenProtokoll = nil
        let lange = protokoll.bericht
        await pause(0.25)
        renderer.onFrameTiming = nil
        let zeiten = sammler.zeiten
        let angezeigt = zeiten.map(\.presentedTime).filter { $0 > 0 }.sorted()
        guard angezeigt.count > 10 else {
            // Hinter dem Schreibtisch (KEVCAD_TEST_VERSTECKT) wird nichts angezeigt, gezeichnet aber schon
            let s = zeiten.map(\.cpuMilliseconds).sorted(), g = zeiten.map(\.gpuMilliseconds).sorted()
            guard !s.isEmpty else { return "keine Bilder" }
            return String(format: "%d Bilder in %.1f s, nicht angezeigt; Hauptfaden je Bild Median %.2f ms, GPU Median %.2f ms, "
                + "Takt des Hauptfadens max %.1f ms", zeiten.count, sekunden, s[s.count / 2], g[g.count / 2],
                taktAbstaende.dropFirst().max() ?? 0) + lange
        }
        var abstaende: [Double] = []
        for i in 1..<angezeigt.count { abstaende.append((angezeigt[i] - angezeigt[i - 1]) * 1000) }
        func q(_ a: [Double], _ p: Double) -> Double {
            let s = a.sorted()
            return s[min(s.count - 1, Int(Double(s.count - 1) * p))]
        }
        let fps = Double(angezeigt.count - 1) / (angezeigt.last! - angezeigt.first!)
        let ueber = abstaende.filter { $0 > 1000 / 120 * 1.5 }.count
        let cpu = zeiten.map(\.cpuMilliseconds), gpu = zeiten.map(\.gpuMilliseconds)
        let takte = Array(taktAbstaende.dropFirst())
        return String(
            format: "%.0f Bilder/s, Abstand Median %.1f ms, 95 %% %.1f ms, max %.1f ms, %d von %d über 12,5 ms; "
                + "Hauptfaden je Bild Median %.2f ms, 95 %% %.2f ms; GPU Median %.2f ms, 95 %% %.2f ms; "
                + "Takt des Hauptfadens max %.1f ms",
            fps, q(abstaende, 0.5), q(abstaende, 0.95), abstaende.max() ?? 0, ueber, abstaende.count,
            q(cpu, 0.5), q(cpu, 0.95), q(gpu, 0.5), q(gpu, 0.95), takte.max() ?? 0) + lange
    }
}

/// Selbsttest: Arbeitsstücke des Hauptfadens über 30 ms und was darin lief. Ein Arbeitsstück ist die Zeit zwischen
/// Aufwachen und Einschlafen der Hauptschleife (ohne `sample`, das die Zeiten verfälscht). Kernel-Nachrichten nennen sich
/// selbst; steht nichts dabei, war es Oberfläche (SwiftUI, AppKit, Core Animation) oder Zeichnen.
@MainActor
final class HauptfadenProtokoll {
    private var beobachter: CFRunLoopObserver?
    private var beginn: CFTimeInterval = 0
    private var nachrichten: [String] = []
    private var lange: [(ms: Double, was: String)] = []

    func start() {
        let o = CFRunLoopObserverCreateWithHandler(
            nil, CFRunLoopActivity.afterWaiting.rawValue | CFRunLoopActivity.beforeWaiting.rawValue, true, 0
        ) { [weak self] _, aktivitaet in
            MainActor.assumeIsolated { self?.wechsel(aktivitaet) }
        }
        beobachter = o
        CFRunLoopAddObserver(CFRunLoopGetMain(), o, .commonModes)
    }

    func stop() {
        if let beobachter { CFRunLoopRemoveObserver(CFRunLoopGetMain(), beobachter, .commonModes) }
        beobachter = nil
    }

    private func wechsel(_ a: CFRunLoopActivity) {
        let jetzt = CACurrentMediaTime()
        if a == .afterWaiting {
            beginn = jetzt
            nachrichten.removeAll(keepingCapacity: true)
        } else if beginn > 0, (jetzt - beginn) * 1000 > 30 {
            lange.append(((jetzt - beginn) * 1000, nachrichten.isEmpty ? "Oberfläche" : nachrichten.joined(separator: " ")))
        }
    }

    func merke(_ events: [IncomingEvent]) {
        for e in events {
            switch e {
            case .part: nachrichten.append("Teil")
            case .message(let m): nachrichten.append(m.typeName)
            default: nachrichten.append("Verbindung")
            }
        }
    }

    /// Die fünf längsten Stücke, sonst leer.
    var bericht: String {
        guard !lange.isEmpty else { return "; kein Arbeitsstück über 30 ms" }
        let top = lange.sorted { $0.ms > $1.ms }.prefix(5).map { String(format: "%.0f ms %@", $0.ms, String($0.was.prefix(60))) }
        return "; \(lange.count) Arbeitsstücke über 30 ms: " + top.joined(separator: ", ")
    }
}

/// Bildzeiten des Selbsttests (auf dem Hauptfaden gesammelt).
@MainActor
final class BildzeitSammler: Sendable {
    nonisolated(unsafe) var zeiten: [ViewportFrameTiming] = []
}

/// Ziel für den Bildschirmtakt des Selbsttests.
final class SelbsttestTakt: NSObject {
    var schritt: ((CFTimeInterval) -> Void)?

    @objc func tick(_ link: CADisplayLink) {
        let t = link.targetTimestamp
        MainActor.assumeIsolated { schritt?(t) }
    }
}
