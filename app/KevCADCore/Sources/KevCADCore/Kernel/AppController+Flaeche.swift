import AppKit
import CoreGraphics
import Foundation
import OCCTSwiftViewport
import QuartzCore

// V2-7 (PROTOCOL.md, „Fläche“): Der Agent stellt die Oberfläche (`VIEW_CMD flaeche`), benennt das Projekt
// (`VIEW_CMD projekt_name`), und die zweite Ansicht rechnet ihr Bild im Hintergrund.

extension AppController {
    /// Befehle von V2-7; nil für alle anderen.
    func performFlaecheCommand(_ v: ViewCommandMessage) -> (Bool, String?)? {
        switch v.cmd {
        case "flaeche":
            let blaetter = model.dokumente.uebersicht.map { $0.blaetter.map { (id: $0.id, titel: $0.titel) } }
            switch FlaecheAuftrag.aus(v.args, zustand: model.oberflaeche.zustand, blaetter: blaetter) {
            case .failure(let f):
                return (false, f.text)
            case .success(let auftrag):
                for b in auftrag.befehle { oberflaeche(b) }
                return (true, auftrag.meldung)
            }
        case "projekt_name":
            guard let name = v.args["name"]?.stringValue, !name.isEmpty else { return (false, "Name fehlt") }
            guard let benennen = projektBenennen else { return (false, "Diese Fassung kann kein Projekt benennen") }
            switch benennen(name) {
            case .success(let pfad): return (true, pfad.path)
            case .failure(let f): return (false, f.text)
            }
        case "test_foto" where AppInfo.isTestVariant:
            return fensterbild(nach: v.args["pfad"]?.stringValue ?? "")
        default:
            return nil
        }
    }

    /// Testvarianten: Bild der Oberfläche ohne Bildschirmaufnahme (der Viewer bleibt darin leer), für Selbsttests auf einem
    /// Rechner ohne Berechtigung dafür (kernel/tools/kachel_selbsttest.py).
    private func fensterbild(nach pfad: String) -> (Bool, String?) {
        guard let v = (NSApp.mainWindow ?? NSApp.windows.first { $0.isVisible })?.contentView,
              let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds)
        else { return (false, "kein Fenster") }
        v.cacheDisplay(in: v.bounds, to: rep)
        guard let d = rep.representation(using: .png, properties: [:]), (try? d.write(to: URL(fileURLWithPath: pfad))) != nil
        else { return (false, "Bild nicht geschrieben") }
        return (true, nil)
    }

    /// `LAGE.flaeche`.
    func lageFlaeche() -> JSONValue {
        let z = model.oberflaeche.zustand
        func text(_ s: String?) -> JSONValue { s.map(JSONValue.string) ?? .null }
        var blatt: JSONValue = .null
        if z.kacheln.contains(.zeichnung), let id = z.blatt, let liste = model.dokumente.uebersicht?.blaetter,
           let i = liste.firstIndex(where: { $0.id == id })
        {
            blatt = .object(["id": .string(id), "titel": .string(liste[i].titel), "nr": .number(Double(i + 1)),
                             "von": .number(Double(liste.count))])
        }
        return .object([
            "modus": .string(z.modus.rawValue), "kacheln": .array(z.kacheln.map { .string($0.rawValue) }),
            "gross": text(z.gross?.rawValue), "aktiv": text(z.aktiv?.rawValue), "rand": text(z.rand?.rawValue),
            "zeitleiste": .bool(z.zeitleiste), "ansicht": .string(z.zweiteAnsicht), "blatt": blatt,
        ])
    }

    // MARK: Zweite Ansicht

    /// Die Kachel meldet ihre Größe in Pixeln (nil: zu, dann rechnet nichts mehr).
    public func zweiteAnsichtGroesse(_ pixel: CGSize?) {
        zweiteAnsichtPixel = pixel
        if pixel != nil {
            zweiteAnsichtNeu()
        } else {
            zweiteAnsichtAuftrag?.cancel()
            zweiteAnsichtRechner.freigeben()
        }
    }

    /// Die zweite Ansicht folgt einem Kamerabefehl des Agenten: Sie bleibt in ihrer Richtung und zeigt dasselbe Ziel.
    func zweiteAnsichtFolgt(_ v: ViewCommandMessage) {
        guard zweiteAnsichtPixel != nil else { return }
        switch v.cmd {
        case "focus":
            zweiteAnsichtZiel = v.args["refs"]?.stringList ?? []
        case "view":
            if v.args["fit"]?.boolValue == true || v.args["standard"]?.stringValue != nil { zweiteAnsichtZiel = [] }
        case "visibility", "section", "explode":
            break
        default:
            return
        }
        zweiteAnsichtNeu()
    }

    /// Neues Bild anfordern (Lauf fertig, andere Größe, andere Richtung, Kamerabefehl). Mehrere Anlässe in Folge ergeben
    /// ein Bild: Der Auftrag wartet kurz, und der Rechner verwirft, was nicht mehr das Neueste ist.
    public func zweiteAnsichtNeu() {
        guard zweiteAnsichtPixel != nil else { return }
        zweiteAnsichtAuftrag?.cancel()
        let auftrag = DispatchWorkItem { [weak self] in self?.zweiteAnsichtRechnen() }
        zweiteAnsichtAuftrag = auftrag
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.06, execute: auftrag)
    }

    /// Nur das Zusammenstellen läuft auf dem Hauptfaden (Kopien der Körper teilen ihren Speicher), gerechnet wird daneben.
    private func zweiteAnsichtRechnen() {
        guard let px = zweiteAnsichtPixel, !scene.isEmpty else {
            if scene.isEmpty { model.zweiteAnsicht.setze(nil) }
            return
        }
        let w = max(16, min(Int(px.width), 2048)), h = max(16, min(Int(px.height), 2048))
        let name = model.oberflaeche.zweiteAnsicht
        var a: [String: JSONValue] = ["standard": .string(name)]
        if !zweiteAnsichtZiel.isEmpty { a["ziel"] = .array(zweiteAnsichtZiel.map(JSONValue.string)) }
        var camera = Self.ansichtKamera(.object(a), scene: scene, aspect: Float(w) / Float(h))
        camera.isOrthographic = !name.hasPrefix("iso")
        let store = model.zweiteAnsicht
        store.rechnet = true
        zweiteAnsichtRechner.rechne(
            bodies: scene.snapshotBodies(), camera: camera, breite: w, hoehe: h,
            lighting: viewport.controller.lightingConfiguration
        ) { bild in
            store.rechnet = false
            if let bild { store.setze(bild) }
        }
    }
}

extension AppController {
    /// Testvarianten: längste Pause des Hauptfadens seit dem letzten Aufruf in Millisekunden (Selbsttest
    /// kernel/tools/kachel_selbsttest.py). Das erste Lagebild startet die Messung.
    func hauptfadenPause() -> Double {
        let bisher = pausenMesser.laeuft ? pausenMesser.stop() : 0
        pausenMesser.start()
        return bisher
    }
}

/// Misst die längste Pause zwischen zwei Takten eines 4-ms-Zeitgebers auf dem Hauptfaden.
@MainActor
public final class HaengerMesser {
    private var zeitgeber: Timer?
    private var letzter = CACurrentMediaTime()
    private var groesste: Double = 0
    private var letzteLange: Double?

    public init() {}

    public var laeuft: Bool { zeitgeber != nil }

    /// Sekunden seit dem Ende der letzten Pause über 100 ms.
    public var seitLetzterLangerPause: Double { letzteLange.map { CACurrentMediaTime() - $0 } ?? 0 }

    public func start() {
        letzter = CACurrentMediaTime()
        groesste = 0
        let t = Timer(timeInterval: 0.004, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self else { return }
                let jetzt = CACurrentMediaTime()
                self.groesste = max(self.groesste, jetzt - self.letzter)
                if jetzt - self.letzter > 0.1 { self.letzteLange = jetzt }
                self.letzter = jetzt
            }
        }
        RunLoop.main.add(t, forMode: .common)
        zeitgeber = t
    }

    /// Längste Pause in Millisekunden.
    public func stop() -> Double {
        zeitgeber?.invalidate()
        zeitgeber = nil
        return max(groesste, CACurrentMediaTime() - letzter) * 1000
    }
}

/// Bild der Kachel „zweite Ansicht“ für die Oberfläche.
@MainActor
public final class ZweiteAnsichtStore: ObservableObject {
    @Published public private(set) var bild: CGImage?
    @Published public internal(set) var rechnet = false
    /// Zahl der fertigen Bilder (Selbsttest)
    public private(set) var fertig = 0

    public init() {}

    func setze(_ neu: CGImage?) {
        bild = neu
        if neu != nil { fertig += 1 }
    }
}

/// Rechnet die zweite Ansicht auf einer eigenen Warteschlange, damit der Hauptfaden frei bleibt (Metal wartet dort auf das
/// Ende des Bildes). Immer nur das Neueste: Ein Auftrag, der beim Start schon überholt ist, fällt weg.
final class ZweiteAnsichtRechner: @unchecked Sendable {
    private let schlange = DispatchQueue(label: "de.upvis.kevcad.zweite-ansicht", qos: .utility)
    private let sperre = NSLock()
    private var stand = 0
    private var renderer: OffscreenRenderer?

    /// Kachel zu: Die Puffer der Körper belegen sonst weiter Grafikspeicher.
    func freigeben() {
        sperre.lock()
        stand += 1
        sperre.unlock()
        schlange.async { [self] in renderer = nil }
    }

    /// `fertig` läuft auf dem Hauptfaden; mit nil, wenn das Bild nicht ging oder überholt ist.
    func rechne(bodies: [ViewportBody], camera: CameraState, breite: Int, hoehe: Int, lighting: LightingConfiguration,
                fertig: @escaping @MainActor @Sendable (CGImage?) -> Void) {
        sperre.lock()
        stand += 1
        let meiner = stand
        sperre.unlock()
        schlange.async { [self] in
            sperre.lock()
            let neu = stand == meiner
            sperre.unlock()
            var bild: CGImage?
            if neu {
                if renderer == nil { renderer = OffscreenRenderer() }
                let optionen = OffscreenRenderOptions(
                    width: breite, height: hoehe, cameraState: camera, displayMode: .shadedWithEdges,
                    lightingConfiguration: lighting, backgroundColor: SIMD4<Float>(0.18, 0.19, 0.20, 1), showGrid: false,
                    showAxes: false, msaaSampleCount: 4)
                bild = renderer?.render(bodies: bodies, options: optionen)
            }
            let ergebnis = SendableBild(bild)
            DispatchQueue.main.async { MainActor.assumeIsolated { fertig(ergebnis.bild) } }
        }
    }
}

/// CGImage gilt in den Metadaten nicht als Sendable, ist aber unveränderlich.
private struct SendableBild: @unchecked Sendable {
    let bild: CGImage?
    init(_ bild: CGImage?) { self.bild = bild }
}
