#if os(macOS)
import AppKit
#endif
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
    /// Rechner ohne Berechtigung dafür (kernel/tools/kachel_selbsttest.py). Nur am Mac (iPad: folgt in I-9).
    private func fensterbild(nach pfad: String) -> (Bool, String?) {
        #if os(macOS)
        guard let v = (NSApp.mainWindow ?? NSApp.windows.first { $0.isVisible })?.contentView,
              let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds)
        else { return (false, "kein Fenster") }
        v.cacheDisplay(in: v.bounds, to: rep)
        guard let d = rep.representation(using: .png, properties: [:]), (try? d.write(to: URL(fileURLWithPath: pfad))) != nil
        else { return (false, "Bild nicht geschrieben") }
        return (true, nil)
        #else
        return (false, "Fensterbild gibt es auf dem iPad noch nicht")
        #endif
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
            "modus": .string(z.modus.rawValue), "leiste_links": .bool(z.leisteLinks), "leiste_rechts": .bool(z.leisteRechts),
            "kacheln": .array(z.kacheln.map { .string($0.rawValue) }),
            "gross": text(z.gross?.rawValue), "aktiv": text(z.aktiv?.rawValue), "rand": text(z.rand?.rawValue),
            "zeitleiste": .bool(z.zeitleiste), "ansicht": .string(z.zweiteAnsicht), "blatt": blatt,
        ])
    }

    // MARK: Zweite Ansicht (V2-10: zweiter Viewer, Viewer/ZweiterViewer.swift)

    /// Die Kachel ist erschienen: Steht ihre Kamera noch nicht, kommt sie in die Richtung der Kachel und wird eingepasst.
    /// Kurz danach, damit der Viewer seine Größe kennt (sonst passt das Einpassen auf ein falsches Seitenverhältnis).
    public func zweiteAnsichtErscheint() {
        guard !zweiterViewer.eingepasst else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) { [weak self] in self?.zweiteAnsichtStellen(animiert: false) }
    }

    /// In die Richtung der Kachel stellen (`OberflaechenZustand.zweiteAnsicht`: Achsansichten parallel, Iso perspektivisch)
    /// und auf das Ziel des letzten Kamerabefehls bzw. alle sichtbaren Teile einpassen. Ist die Kachel zu, geschieht das
    /// beim nächsten Erscheinen.
    func zweiteAnsichtStellen(animiert: Bool) {
        guard zweiterViewer.aktiv else {
            zweiterViewer.eingepasst = false
            return
        }
        let name = model.oberflaeche.zweiteAnsicht
        guard let sv = ViewportCoordinator.standardView(protocolName: name) else { return }
        let parallel = !name.hasPrefix("iso")
        let bereich = zweiteAnsichtBereich()
        let z = zweiterViewer.coordinator
        z.apply(rotation: sv.rotation, orthographic: parallel, fitTo: bereich, animated: animiert)
        z.autoOrtho = parallel  // wie der Ziffernblock: Drehen kehrt zur Perspektive zurück
        if bereich != nil { zweiterViewer.eingepasst = true }
    }

    /// Nach einem Lauf: Bewegt wird die Kamera nur, solange sie noch nie Teile eingepasst hat.
    func zweiteAnsichtNachLauf() {
        if zweiterViewer.aktiv && !zweiterViewer.eingepasst { zweiteAnsichtStellen(animiert: false) }
    }

    /// Ziel des letzten Kamerabefehls, sonst alle sichtbaren Teile.
    private func zweiteAnsichtBereich() -> BoundingBox? {
        if !zweiteAnsichtZiel.isEmpty {
            let refs = scene.expand(zweiteAnsichtZiel.compactMap(ElementRef.init)).known
            if !refs.isEmpty, let b = scene.worldBounds(of: refs) { return b }
        }
        return scene.visibleBounds()
    }

    /// Die zweite Ansicht folgt einem Kamerabefehl des Agenten: Sie bleibt in ihrer Richtung und zeigt dasselbe Ziel.
    /// Sichtbarkeit, Schnitt und Explosion übernimmt sie ohnehin vom Hauptviewer.
    func zweiteAnsichtFolgt(_ v: ViewCommandMessage) {
        switch v.cmd {
        case "focus":
            zweiteAnsichtZiel = v.args["refs"]?.stringList ?? []
            blattZumKontext(teile: zweiteAnsichtZiel)  // V2-10: Das Blatt der Zeichnung zeigt, wovon der Agent spricht
        case "highlight":
            blattZumKontext(teile: v.args["refs"]?.stringList ?? [])
            return
        case "view":
            guard v.args["fit"]?.boolValue == true || v.args["standard"]?.stringValue != nil else { return }
            zweiteAnsichtZiel = []
        default:
            return
        }
        guard zweiterViewer.aktiv, let b = zweiteAnsichtBereich() else { return }
        zweiterViewer.coordinator.fit(b, animated: true)
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
