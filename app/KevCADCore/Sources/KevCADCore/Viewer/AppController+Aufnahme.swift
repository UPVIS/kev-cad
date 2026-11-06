import AVFoundation
#if os(macOS)
import AppKit
#endif
import Combine
import CoreVideo
import Foundation
import OCCTSwiftViewport
import QuartzCore
import SwiftUI
import simd

// Bild und Video mit einem Klick (V2, Schritt 7). Gerendert wird mit einem zweiten, unsichtbaren Renderer desselben
// Pakets (gleiche Durchgänge wie der Viewport: Verdeckung, Kantenbetonung, Silhouetten, Umriss, Umgebungsbild), damit
// Bild und Video genau so aussehen wie die Ansicht. Ablage im Projektordner unter output/ (Bilder) und output/videos/.

/// Mitschnitt der eigenen Navigation: Kamera je Änderung mit Zeitpunkt.
struct NavigationsMitschnitt {
    var beginn: CFTimeInterval
    var kameras: [(zeit: CFTimeInterval, kamera: CameraState)] = []
    var abo: AnyCancellable?
}

/// Unsichtbarer Renderer mit eigener Kamera; übernimmt Darstellung, Licht, Auswahl und Schnitt vom Viewport.
@MainActor
final class OfflineAnsicht {
    let controller: ViewportController
    private var koerper: [ViewportBody] = []
    private var renderer: ViewportRenderer?

    init(vorbild: ViewportController) {
        controller = ViewportController(configuration: vorbild.configuration)
    }

    func uebernehmen(von live: ViewportController, koerper: [ViewportBody]) {
        controller.configuration = live.configuration
        controller.lightingConfiguration = live.lightingConfiguration
        controller.displayMode = live.displayMode
        controller.selectedBodyIDs = live.selectedBodyIDs
        controller.clipPlanes = live.clipPlanes
        controller.edgeIntensity = live.edgeIntensity
        controller.showGrid = false
        controller.showAxes = false
        self.koerper = koerper
        if renderer == nil {
            renderer = ViewportRenderer(
                controller: controller,
                bodies: Binding(get: { [weak self] in self?.koerper ?? [] }, set: { [weak self] in self?.koerper = $0 }))
        }
    }

    /// `bilder` Bilder hintereinander rechnen (Selbsttest: Durchsatz ohne Bildschirmtakt); true = geklappt.
    func serie(kamera: CameraState, breite: Int, hoehe: Int, hintergrund: SIMD4<Float>, bilder: Int) -> Bool {
        controller.cameraController.cancelAnimation()
        controller.animateTo(kamera, duration: 0)
        return renderer?.renderHeadlessBGRA(
            width: breite, height: hoehe, backgroundColor: hintergrund, frameCount: bilder) != nil
    }

    /// Bild mit dieser Kamera (BGRA → CGImage).
    func bild(kamera: CameraState, breite: Int, hoehe: Int, hintergrund: SIMD4<Float>) -> CGImage? {
        controller.cameraController.cancelAnimation()
        controller.animateTo(kamera, duration: 0)
        return renderer?.renderHeadless(width: breite, height: hoehe, backgroundColor: hintergrund)
    }
}

/// HEVC-Video über AVAssetWriter (Hardware-Kodierer, ohne ffmpeg).
final class HEVCSchreiber {
    private let writer: AVAssetWriter
    private let input: AVAssetWriterInput
    private let adapter: AVAssetWriterInputPixelBufferAdaptor
    let breite: Int, hoehe: Int, fps: Int32
    private var bild = 0

    init(ziel: URL, breite: Int, hoehe: Int, fps: Int32) throws {
        self.breite = breite
        self.hoehe = hoehe
        self.fps = fps
        try? FileManager.default.removeItem(at: ziel)
        writer = try AVAssetWriter(outputURL: ziel, fileType: .mp4)
        input = AVAssetWriterInput(mediaType: .video, outputSettings: [
            AVVideoCodecKey: AVVideoCodecType.hevc,
            AVVideoWidthKey: breite,
            AVVideoHeightKey: hoehe,
            AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: breite * hoehe * 6],
        ])
        input.expectsMediaDataInRealTime = false
        adapter = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            kCVPixelBufferWidthKey as String: breite,
            kCVPixelBufferHeightKey as String: hoehe,
        ])
        writer.add(input)
        guard writer.startWriting() else { throw writer.error ?? CocoaError(.fileWriteUnknown) }
        writer.startSession(atSourceTime: .zero)
    }

    /// Ein Bild anhängen (wartet kurz, bis der Kodierer bereit ist).
    func anhaengen(_ image: CGImage) -> Bool {
        var n = 0
        while !input.isReadyForMoreMediaData && n < 200 {
            Thread.sleep(forTimeInterval: 0.005)
            n += 1
        }
        guard input.isReadyForMoreMediaData, let pool = adapter.pixelBufferPool else { return false }
        var puffer: CVPixelBuffer?
        CVPixelBufferPoolCreatePixelBuffer(nil, pool, &puffer)
        guard let puffer else { return false }
        CVPixelBufferLockBaseAddress(puffer, [])
        defer { CVPixelBufferUnlockBaseAddress(puffer, []) }
        guard let ctx = CGContext(
            data: CVPixelBufferGetBaseAddress(puffer), width: breite, height: hoehe, bitsPerComponent: 8,
            bytesPerRow: CVPixelBufferGetBytesPerRow(puffer), space: CGColorSpace(name: CGColorSpace.sRGB)!,
            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)
        else { return false }
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: breite, height: hoehe))
        let zeit = CMTime(value: CMTimeValue(bild), timescale: fps)
        bild += 1
        return adapter.append(puffer, withPresentationTime: zeit)
    }

    func beenden(_ fertig: @escaping @Sendable (Bool) -> Void) {
        input.markAsFinished()
        writer.finishWriting { [writer] in fertig(writer.status == .completed) }
    }

    func abbrechen() { writer.cancelWriting() }
}

extension AppController {
    /// Ordner für Bilder und Videos: <Projekt>/output (ohne Projekt der Schreibtisch).
    func ausgabeOrdner(_ unter: String? = nil) -> URL {
        var dir = model.project?.path.appendingPathComponent("output", isDirectory: true)
            ?? FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask)[0]
        if let unter { dir = dir.appendingPathComponent(unter, isDirectory: true) }
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    static func zeitstempel() -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd-HHmmss"
        return f.string(from: Date())
    }

    /// Unsichtbarer Renderer mit dem Stand des Viewports.
    func offlineAnsicht() -> OfflineAnsicht {
        let o = offline ?? OfflineAnsicht(vorbild: viewport.controller)
        offline = o
        o.uebernehmen(von: viewport.controller, koerper: viewport.bodies)
        return o
    }

    var hintergrundFarbe: SIMD4<Float> { wirksamerHintergrund }

    // MARK: Bildschirmfoto

    public func bildschirmfoto(_ groesse: FotoGroesse) {
        guard viewport.mtkView != nil, !viewport.bodies.isEmpty else {
            saveScreenshot()
            return
        }
        let px = viewport.controller.drawablePixelSize
        let seite = px.width > 16 && px.height > 16 ? px : CGSize(width: 2400, height: 1600)
        var w: Int, h: Int
        switch groesse {
        case .doppelt:
            w = Int(seite.width) * 2
            h = Int(seite.height) * 2
        case .uhd4k:
            let a = seite.width / seite.height
            if a >= 1 {
                w = 3840
                h = Int((3840 / a).rounded())
            } else {
                h = 3840
                w = Int((3840 * a).rounded())
            }
        }
        let grenze = 8192
        if w > grenze || h > grenze {
            let k = Double(grenze) / Double(max(w, h))
            w = Int(Double(w) * k)
            h = Int(Double(h) * k)
        }
        let t0 = CACurrentMediaTime()
        let kamera = viewport.camera
        guard let roh = offlineAnsicht().bild(kamera: kamera, breite: w, hoehe: h, hintergrund: hintergrundFarbe)
        else {
            viewer.zeige("Bild ließ sich nicht rendern", fehler: true)
            log(.error, "Bildschirmfoto: Rendern fehlgeschlagen")
            return
        }
        let overlay = overlayItems().filter { if case .badge = $0 { return false } else { return true } }
        let bild = overlay.isEmpty ? roh : (ScreenshotRenderer.composite(roh, overlay: overlay, camera: kamera) ?? roh)
        guard let png = ScreenshotRenderer.pngData(bild) else {
            viewer.zeige("Bild ließ sich nicht speichern", fehler: true)
            return
        }
        let url = ausgabeOrdner().appendingPathComponent("Bild-\(Self.zeitstempel()).png")
        do {
            try png.write(to: url)
            let ms = Int((CACurrentMediaTime() - t0) * 1000)
            log(.info, "Bildschirmfoto: \(w) × \(h) in \(ms) ms, \(url.path)")
            viewer.zeige("Bild gespeichert (\(w) × \(h))", datei: url)
        } catch {
            viewer.zeige("Bild nicht gespeichert: \(error.localizedDescription)", fehler: true)
        }
    }

    // MARK: Video: Drehung um das Ziel

    /// Videogröße: Seitenverhältnis der Ansicht, 1080 Bildpunkte hoch (gerade Maße), höchstens 3840 breit.
    func videoGroesse() -> (Int, Int) {
        let px = viewport.controller.drawablePixelSize
        let a = px.width > 16 && px.height > 16 ? Double(px.width / px.height) : 16.0 / 9
        var h = 1080, w = Int((1080 * a).rounded())
        if w > 3840 {
            w = 3840
            h = Int((3840 / a).rounded())
        }
        return (w / 2 * 2, h / 2 * 2)
    }

    public func videoDrehung() {
        guard !viewer.aufnahme.laeuft else { return }
        guard !viewport.bodies.isEmpty else {
            viewer.zeige("Nichts zu filmen", fehler: true)
            return
        }
        let start = viewport.kameraZiel
        let fps = 60, dauer = 8.0
        let n = Int(dauer * Double(fps))
        // Volle Drehung um die senkrechte Achse durch den Drehpunkt, gleichmäßig (Bild n = Bild 0, deshalb n Bilder)
        let kamera: (Int) -> CameraState = { k in
            var c = start
            let winkel = -2 * Float.pi * Float(k) / Float(n)
            c.rotation = simd_normalize(simd_quatf(angle: winkel, axis: SIMD3<Float>(0, 0, 1)) * start.rotation)
            return c
        }
        let url = ausgabeOrdner("videos").appendingPathComponent("Drehung-\(Self.zeitstempel()).mp4")
        videoRendern(bilder: n, fps: fps, kamera: kamera, ziel: url, art: "Drehung") { [weak self] p in
            self?.viewer.aufnahme = .drehung(p)
        }
    }

    // MARK: Mitschnitt der Navigation

    public func navigationAufnehmen() {
        if var m = mitschnitt {
            // Ende: Kamerafolge zu einem Video rechnen
            mitschnitt = nil
            m.abo?.cancel()
            let ende = CACurrentMediaTime()
            m.kameras.append((ende, viewport.camera))
            let dauer = ende - m.beginn
            guard dauer >= 0.5, m.kameras.count >= 3 else {
                viewer.aufnahme = .keine
                viewer.zeige("Mitschnitt zu kurz, nichts gespeichert", fehler: true)
                return
            }
            let fps = 60
            let n = Int(dauer * Double(fps))
            let folge = m.kameras
            let beginn = m.beginn
            let kamera: (Int) -> CameraState = { k in
                let t = beginn + Double(k) / Double(fps)
                // letzter Stand vor t, zwischen zwei Ständen weich verbunden
                var i = 0
                while i + 1 < folge.count && folge[i + 1].zeit <= t { i += 1 }
                guard i + 1 < folge.count else { return folge[i].kamera }
                let a = folge[i], b = folge[i + 1]
                let u = Float((t - a.zeit) / max(b.zeit - a.zeit, 1e-6))
                return Kamerafahrt.zwischen(a.kamera, b.kamera, min(max(u, 0), 1))
            }
            let url = ausgabeOrdner("videos").appendingPathComponent("Navigation-\(Self.zeitstempel()).mp4")
            videoRendern(bilder: n, fps: fps, kamera: kamera, ziel: url, art: "Mitschnitt") { [weak self] p in
                self?.viewer.aufnahme = .navigationRechnen(p)
            }
            return
        }
        guard !viewer.aufnahme.laeuft else { return }
        let jetzt = CACurrentMediaTime()
        var m = NavigationsMitschnitt(beginn: jetzt, kameras: [(jetzt, viewport.camera)])
        m.abo = viewport.controller.$cameraState.dropFirst().sink { [weak self] c in
            self?.mitschnitt?.kameras.append((CACurrentMediaTime(), c))
        }
        mitschnitt = m
        viewer.aufnahme = .navigation(Date())
        log(.info, "Mitschnitt der Navigation läuft (noch einmal ⇧⌥⌘R beendet)")
    }

    // MARK: Gemeinsam: Bilder rechnen und kodieren

    /// Rechnet `bilder` Bilder auf dem Hauptthread, je eines pro Durchlauf der Ereignisschleife (die App bleibt
    /// bedienbar), kodiert HEVC und meldet das Ergebnis.
    func videoRendern(
        bilder n: Int, fps: Int, kamera: @escaping (Int) -> CameraState, ziel: URL, art: String,
        fortschritt: @escaping (Double) -> Void
    ) {
        let (w, h) = videoGroesse()
        let ansicht = offlineAnsicht()
        let schreiber: HEVCSchreiber
        let tmp = ziel.deletingLastPathComponent().appendingPathComponent(".\(ziel.lastPathComponent)-entsteht.mp4")
        do {
            schreiber = try HEVCSchreiber(ziel: tmp, breite: w, hoehe: h, fps: Int32(fps))
        } catch {
            viewer.aufnahme = .keine
            viewer.zeige("Video ließ sich nicht anlegen: \(error.localizedDescription)", fehler: true)
            return
        }
        let hintergrund = hintergrundFarbe
        let t0 = CACurrentMediaTime()
        fortschritt(0)
        func schritt(_ k: Int) {
            if k >= n {
                schreiber.beenden { ok in
                    DispatchQueue.main.async {
                        MainActor.assumeIsolated { [weak self] in
                            guard let self else { return }
                            self.viewer.aufnahme = .keine
                            guard ok else {
                                self.viewer.zeige("\(art): Video nicht geschrieben", fehler: true)
                                return
                            }
                            try? FileManager.default.removeItem(at: ziel)
                            try? FileManager.default.moveItem(at: tmp, to: ziel)
                            let s = CACurrentMediaTime() - t0
                            self.log(.info, "\(art): \(n) Bilder \(w) × \(h) in \(String(format: "%.1f", s)) s, \(ziel.path)")
                            self.viewer.zeige("\(art) gespeichert (\(n / fps) s, \(w) × \(h), HEVC)", datei: ziel)
                        }
                    }
                }
                return
            }
            guard let bild = ansicht.bild(kamera: kamera(k), breite: w, hoehe: h, hintergrund: hintergrund),
                schreiber.anhaengen(bild)
            else {
                schreiber.abbrechen()
                viewer.aufnahme = .keine
                viewer.zeige("\(art): Bild \(k) ließ sich nicht rechnen", fehler: true)
                return
            }
            if k % 6 == 0 { fortschritt(Double(k) / Double(n)) }
            DispatchQueue.main.async { MainActor.assumeIsolated { schritt(k + 1) } }
        }
        schritt(0)
    }
}
