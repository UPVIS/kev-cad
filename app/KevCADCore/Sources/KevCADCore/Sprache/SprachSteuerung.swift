import AppKit
import CoreGraphics
import Foundation
import ImageIO
import OCCTSwiftViewport
import UniformTypeIdentifiers
import simd

// V2-6: Eine Sitzung von V bis ↩ oder esc (PROTOCOL.md, „V2-6 Sprach-Feedback“). Hier kommen Erkennung, Maus, Striche,
// Kamera und Auswahl auf einer Uhr zusammen, und am Ende entsteht das Paket. Die Oberfläche liest `AppModel.sprache` und
// `AppModel.oberflaeche`; ausgelöst wird alles über `OberflaechenActions`.

/// Was die Oberfläche beim Sprechen zeigt. Eigener Speicher, damit nicht jedes Wort das Hauptfenster neu auswertet
/// (OBERFLAECHE.md, Abschnitt 5).
@MainActor
public final class SprachStore: ObservableObject {
    /// Was Kevin bisher gesagt hat, der laufende Satz zuletzt.
    @Published public internal(set) var text: String?
    /// Lautstärke 0…1
    @Published public internal(set) var pegel: Float = 0
    /// ↩ ist gedrückt, das Paket entsteht gerade.
    @Published public internal(set) var schickt = false

    public init() {}
}

/// Ein Strich im Viewer, wie ihn die Eingabeebene meldet.
public enum StrichEreignis {
    case beginn
    /// Punkt mit dem Treffer an dieser Stelle. `eingabe`: Ursprung unten links, `bild`: oben links, `zeit`: Uptime.
    case punkt(eingabe: CGPoint, bild: CGPoint, zeit: Double, treffer: PickResult?, welt: SIMD3<Float>?)
    case ende
}

@MainActor
public final class SprachSteuerung {
    weak var controller: AppController?
    public private(set) var sitzung: FeedbackSitzung?
    private var stand: FeedbackStand = .aus
    private var standSeit: Double = 0
    /// Projekt beim Beginn: Dorthin geht das Paket, auch wenn der Agent inzwischen eines geöffnet hat.
    private var projekt: ProjectInfo?
    private var erkennung: (any Spracherkennung)?
    private var gesagt: [String] = []
    private var zwischenstand: String?
    /// Beginn des laufenden Satzes, solange sein Ende fehlt.
    private var satzBeginn: Double?
    private var stoppen: Task<Void, Never>?
    private var probenTakt: Timer?
    private var tastenMonitor: Any?
    /// ↩ ist gedrückt, das Paket entsteht gerade.
    private var schliesst = false
    /// Letzter Treffer des laufenden Strichs (Bildebene für Punkte daneben).
    private var strichAnker: SIMD3<Float>?

    /// Selbsttest: jeder Zwischenstand mit Uptime; das Paket, sobald es geschrieben ist.
    var beiZwischenstand: ((String, Double) -> Void)?
    var beiPaket: ((URL, FeedbackPaket) -> Void)?
    /// Tests: eigene Erkennung statt Wortlaut, und was an den Kernel geht.
    var erkennungFabrik: (() -> any Spracherkennung)?
    var gesendet: ((any OutgoingMessage) -> Void)?

    public var offen: Bool { sitzung != nil }
    public var spricht: Bool { stand == .spricht }
    /// So lange höchstens wartet ↩ auf die letzten Wörter (Budget: Paket beim Agenten unter 1 s). Wortlaut schließt einen
    /// Satz nach 0,6 s Stille ab; drückt Kevin ↩ gleich nach dem letzten Wort, ist der Satz damit gerade noch da.
    static let letzteWorteS = 0.7
    /// V hält an: Hier wartet niemand, der Satz darf zu Ende kommen.
    static let satzAbwartenS = 1.5

    private var jetzt: Double { ProcessInfo.processInfo.systemUptime }

    private func uhr() -> Double { sitzung?.zeit(uptime: jetzt) ?? 0 }

    // MARK: Befehle

    /// V: beginnen, pausieren, weiter.
    func umschalten(an: Bool) {
        guard !schliesst else { return }
        if an {
            if sitzung == nil { beginnen() } else if stand == .pause { weiter() }
        } else if stand == .spricht {
            anhalten()
        }
    }

    private func beginnen() {
        guard let c = controller else { return }
        guard let p = c.model.project else {
            c.viewer.zeige("Dafür braucht es ein offenes Projekt.")
            return
        }
        let unix = Date().timeIntervalSince1970
        projekt = p
        var s = FeedbackSitzung(id: "s-\(Int(unix * 1000))", uhrStart: unix, uhrNull: jetzt)
        s.mikrofonAn(t: 0)
        s.kamera(t: 0, c.lageKamera())
        s.auswahl(t: 0, run: c.scene.latestRun, refs: c.scene.selection.map(\.string))
        sitzung = s
        gesagt = []
        zwischenstand = nil
        satzBeginn = nil
        c.model.sprache.text = nil
        erkennung = erkennungFabrik?() ?? neueErkennung()
        erkennung?.beiEreignis = { [weak self] e in self?.ereignis(e) }
        c.model.oberflaeche.ausfuehren(.sprechen(true))
        c.viewport.zeichnen = true
        melden(.spricht)
        tonStarten()
        probenAn()
    }

    /// Mikrofon aus, Sitzung offen.
    private func anhalten() {
        guard let c = controller, stand == .spricht else { return }
        let t = uhr()
        sitzung?.mikrofonAus(t: t)
        c.model.oberflaeche.ausfuehren(.sprechen(false))
        c.viewport.zeichnen = false
        melden(.pause)
        let e = erkennung
        stoppen = Task { await e?.anhalten(hoechstens: Self.satzAbwartenS) }
    }

    private func weiter() {
        guard let c = controller else { return }
        let t = uhr()
        sitzung?.mikrofonAn(t: t)
        c.model.oberflaeche.ausfuehren(.sprechen(true))
        c.viewport.zeichnen = true
        melden(.spricht)
        tonStarten()
    }

    private func tonStarten() {
        let vorher = stoppen
        let e = erkennung
        Task {
            await vorher?.value  // der vorige Abschnitt schließt erst seine Wörter ab
            e?.starten()
        }
    }

    /// ↩: Das Paket entsteht. Bild und letzte Wörter laufen nebeneinander; die Oberfläche ist sofort wieder frei.
    func fertig() {
        guard let c = controller, sitzung != nil, !schliesst else { return }
        schliesst = true
        let ende = uhr()
        sitzung?.strichEnden(t: ende)
        sitzung?.mikrofonAus(t: ende)
        melden(.aus, grund: .fertig)
        c.viewport.zeichnen = false
        c.model.oberflaeche.ausfuehren(.sprechen(false))  // der rote Rahmen geht sofort
        c.model.sprache.schickt = true
        let e = erkennung
        let letzte = stoppen
        let abschluss = Task {
            await letzte?.value
            await e?.anhalten(hoechstens: Self.letzteWorteS)
        }
        // Der Agent darf gleich weiterarbeiten: Die Lage steht jetzt fest
        let roh = c.feedbackBild()
        let lage = c.feedbackLage()
        let run = c.scene.latestRun
        let erstellt = Date()
        Task { [weak self] in
            await Self.warten(auf: abschluss, hoechstens: Self.letzteWorteS + 0.05)
            await self?.schreiben(ende: ende, lage: lage, run: run, erstellt: erstellt, bild: roh)
        }
    }

    /// esc: nichts bleibt.
    func verwerfen() {
        guard let c = controller, sitzung != nil, !schliesst else { return }
        melden(.aus, grund: .verworfen)
        let e = erkennung
        Task { await e?.anhalten(hoechstens: 0) }
        aufraeumen()
        c.model.oberflaeche.ausfuehren(.sprechenVerwerfen)
    }

    /// Neuer Kernel: Er kennt die offene Sitzung noch nicht.
    func nachVerbindung() {
        guard let s = sitzung, stand != .aus else { return }
        senden(FeedbackStandMessage(sitzung: s.id, stand: stand, seit: standSeit))
    }

    private func senden<M: OutgoingMessage>(_ m: M) {
        gesendet?(m)
        controller?.send(m)
    }

    private func melden(_ neu: FeedbackStand, grund: FeedbackGrund? = nil) {
        guard let s = sitzung else { return }
        stand = neu
        standSeit = Date().timeIntervalSince1970
        senden(FeedbackStandMessage(sitzung: s.id, stand: neu, seit: standSeit, grund: grund))
    }

    /// Am Mac zuerst Wortlaut, Apples Erkennung als Rückfall. Selbsttests und Demomodus fragen nie nach dem Mikrofon; der
    /// Testeingang liest eine Datei.
    private func neueErkennung() -> any Spracherkennung {
        let env = ProcessInfo.processInfo.environment
        let kontext = Fachwoerter.kontext(teile: controller?.scene.order ?? [])
        func apple(_ tonDatei: URL?) -> any Spracherkennung {
            if #available(macOS 26.0, *) {
                let e = AppleErkennung(tonDatei: tonDatei)
                e.kontext = kontext
                return e
            }
            return KeineErkennung()
        }
        if AppInfo.isTestVariant, let pfad = env["KEVCAD_SPRACHE_TONDATEI"], !pfad.isEmpty {
            return apple(URL(fileURLWithPath: pfad))
        }
        if env["KEVCAD_SELFTEST"] != nil || AppInfo.isDemoMode { return TestErkennung() }
        return ErkennungMitRueckfall(erste: WortlautErkennung(), rueckfall: { apple(nil) })
    }

    // MARK: Erkennung

    private func ereignis(_ e: SprachEreignis) {
        guard let c = controller, sitzung != nil else { return }
        switch e {
        case .pegel(let p):
            c.model.sprache.pegel = p
        case .zwischenstand(let t):
            if satzBeginn == nil { satzBeginn = max(0, uhr() - 0.4) }  // der erste Zwischenstand kommt so viel später
            zwischenstand = t
            beiZwischenstand?(t, jetzt)
            textZeigen()
        case .satz(let text, let worte, let von, let bis):
            guard let s = sitzung else { return }
            let jetztUhr = uhr()
            let beginn = von.map(s.zeit(uptime:)) ?? satzBeginn ?? jetztUhr
            let ende = bis.map(s.zeit(uptime:)) ?? jetztUhr
            let rohWorte = worte.map {
                FeedbackSitzung.RohWort(text: $0.text, von: s.zeit(uptime: $0.von), bis: s.zeit(uptime: $0.bis))
            }
            sitzung?.satz(text: text, von: beginn, bis: ende, worte: rohWorte)
            gesagt.append(text)
            zwischenstand = nil
            satzBeginn = nil
            textZeigen()
        case .verworfen:
            zwischenstand = nil
            satzBeginn = nil
            textZeigen()
        case .zustand(.fehler(let meldung)):
            c.viewer.zeige(meldung)
            if offen, !schliesst, gesagt.isEmpty, zwischenstand == nil, (sitzung?.striche.isEmpty ?? true) {
                verwerfen()
            }
        case .zustand(.rueckfall(let grund)):
            // Ohne Wortlaut ist das der normale Weg, das braucht keine Meldung
            if Wortlaut.installiert { c.viewer.zeige("\(grund) Es hört jetzt Apples Spracherkennung zu.") }
        case .zustand(.pausiert):
            c.viewer.zeige("Du diktierst gerade in Wortlaut, danach hört Kev CAD wieder zu.")
        case .zustand(.laedt(let meldung)):
            c.viewer.zeige(meldung)
        case .zustand:
            break
        }
    }

    private var ganzerText: String {
        (gesagt + (zwischenstand.map { [$0] } ?? [])).joined(separator: " ")
    }

    private func textZeigen() {
        // Mehr als drei Zeilen zeigt die Oberfläche nicht: Ein langer Monolog bleibt so billig
        controller?.model.sprache.text = String(ganzerText.suffix(320))
    }

    // MARK: Zeigen, Kamera, Auswahl

    /// Mausprobe aus dem Treffertest unter der Maus; `bildpunkt` nil: Die Maus hat den Viewer verlassen.
    func maus(_ pick: PickResult?, _ welt: SIMD3<Float>?, _ bildpunkt: CGPoint?) {
        guard sitzung != nil else { return }
        let p = probe(t: uhr(), pick, welt, bildpunkt)
        sitzung?.maus(p)
    }

    private func probe(t: Double, _ pick: PickResult?, _ welt: SIMD3<Float>?, _ bildpunkt: CGPoint?) -> FeedbackPaket.MausProbe {
        var p = FeedbackPaket.MausProbe(t: t, bild: bildpunkt.map { [Double($0.x.rounded()), Double($0.y.rounded())] })
        if let c = controller, let pick, let ref = c.scene.resolve(pick) {
            p.teil = ref.part
            p.ref = ref.string
            p.run = c.scene.latestRun
            p.punkt = (welt ?? c.scene.worldAnchor(of: ref)).map(Self.zahlen)  // Kanten und Ecken: ihr Ankerpunkt
            p.normale = c.viewport.surfaceNormal(of: pick).map(Self.zahlen)
        }
        return p
    }

    static func zahlen(_ v: SIMD3<Float>) -> [Double] {
        [v.x, v.y, v.z].map { (Double($0) * 1000).rounded() / 1000 }
    }

    private func probenAn() {
        guard probenTakt == nil else { return }
        let takt = Timer(timeInterval: 0.1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.proben() }
        }
        RunLoop.main.add(takt, forMode: .common)  // auch während die Maustaste gedrückt ist
        probenTakt = takt
        tastenAn()
    }

    /// Kamera und Auswahl sind Zustand: ein Blick je Takt genügt, gezeichnet wird dabei nichts.
    private func proben() {
        guard let c = controller, sitzung != nil else { return }
        let t = uhr()
        sitzung?.kamera(t: t, c.lageKamera())
        sitzung?.auswahl(t: t, run: c.scene.latestRun, refs: c.scene.selection.map(\.string))
    }

    /// ↩ gilt überall im Fenster, auch wenn der Fokus nicht im Viewer steht. Textfelder und Dialoge gehen vor.
    private func tastenAn() {
        guard tastenMonitor == nil else { return }
        tastenMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] e in
            nonisolated(unsafe) let e = e
            let verbraucht = MainActor.assumeIsolated { self?.taste(e) ?? false }
            return verbraucht ? nil : e
        }
    }

    private func taste(_ e: NSEvent) -> Bool {
        guard Tastenbelegung.eingabeCodes.contains(e.keyCode), TastenMods(e.modifierFlags).isEmpty,
            let w = e.window, w.attachedSheet == nil, !NavigationInputView.istTexteingabe(w.firstResponder)
        else { return false }
        fertig()
        return true
    }

    // MARK: Striche

    func strich(_ e: StrichEreignis) {
        guard let c = controller, sitzung != nil else { return }
        switch e {
        case .beginn:
            strichAnker = nil
            let t = uhr()
            sitzung?.strichBeginnen(t: t, run: c.scene.latestRun, kamera: c.lageKamera())
        case .punkt(let eingabe, let bild, let zeit, let treffer, let welt):
            let t = sitzung?.zeit(uptime: zeit) ?? 0
            let ref = treffer.flatMap { c.scene.resolve($0) }
            if welt != nil { strichAnker = welt }
            let ort = welt ?? c.viewport.weltpunkt(eingabe, durch: strichAnker ?? c.viewport.camera.pivot) ?? .zero
            sitzung?.strichPunkt(
                .init(t: t, bild: [Double(bild.x.rounded()), Double(bild.y.rounded())], welt: Self.zahlen(ort),
                      ref: ref?.string), teil: ref?.part)
            let p = probe(t: t, treffer, welt, bild)
            sitzung?.maus(p)
        case .ende:
            let t = uhr()
            sitzung?.strichEnden(t: t)
            c.refreshOverlay()
        }
    }

    /// Fertige Striche im Viewer; sie folgen der Kamera.
    func overlay() -> [OverlayPrimitive] {
        guard let s = sitzung else { return [] }
        return Self.strichItems(s.striche)
    }

    static func strichItems(_ striche: [FeedbackPaket.Strich]) -> [OverlayPrimitive] {
        striche.compactMap { s in
            let punkte = s.punkte.compactMap { p -> SIMD3<Float>? in
                p.welt.count == 3 ? SIMD3(Float(p.welt[0]), Float(p.welt[1]), Float(p.welt[2])) : nil
            }
            return punkte.count >= 2 ? .polyline(points: punkte, color: ViewerStil.strich, width: 3) : nil
        }
    }

    // MARK: Paket

    private func schreiben(ende: Double, lage: JSONValue, run: Int, erstellt: Date, bild: FeedbackRohbild?) async {
        guard let c = controller, let s = sitzung, let projekt else { return }
        var sitzung = s
        if let rest = zwischenstand, !rest.isEmpty {  // ↩ kam vor dem endgültigen Ergebnis
            let von = satzBeginn ?? ende
            let worte = Wortzeiten.schaetzen(text: rest, von: von, bis: ende, stuetzen: [])
                .map { FeedbackSitzung.RohWort(text: $0.text, von: $0.von, bis: $0.bis) }
            sitzung.satz(text: rest, von: von, bis: ende, worte: worte, vorlaeufig: true)
        }
        let (saetze, _) = sitzung.saetzeMitBezuegen(run: run)
        let text = (gesagt + (zwischenstand.map { [$0] } ?? [])).joined(separator: " ")
        // Ohne ein Wort und ohne Strich gibt es nichts zu melden
        guard !saetze.isEmpty || !sitzung.striche.isEmpty else {
            aufraeumen()
            c.model.oberflaeche.ausfuehren(.sprechenVerwerfen)
            c.viewer.zeige("Du hast nichts gesagt, deshalb geht nichts an den Agenten.")
            return
        }
        let ordner = FeedbackAblage.ordner(projekt: projekt.path)
        let name = FeedbackAblage.name(in: ordner, datum: erstellt)
        let eintrag = bild.map { FeedbackPaket.Bild(datei: name + ".jpg", breite: $0.image.width, hoehe: $0.image.height) }
        let paket = sitzung.paket(
            name: name, erstellt: erstellt, dauer: ende, spracherkennung: erkennung?.kennung ?? "test",
            wortzeiten: erkennung?.wortzeiten ?? "ton", projekt: .init(name: projekt.name, pfad: projekt.path.path), run: run, ende: lage, bild: eintrag)
        let overlay = Self.strichItems(paket.striche) + Self.nummern(paket.saetze)
        // Kevin ist fertig: Die Oberfläche ist frei, bevor die Datei liegt
        c.model.oberflaeche.ausfuehren(.sprechText(text))
        c.model.oberflaeche.ausfuehren(.sprechenFertig)
        let sitzungID = s.id
        let ergebnis: Result<URL, Error> = await Task.detached(priority: .userInitiated) {
            do {
                let jpeg = bild.flatMap { Self.jpeg($0, overlay: overlay) }
                return .success(try FeedbackAblage.schreiben(paket, bild: jpeg, in: ordner))
            } catch {
                return .failure(error)
            }
        }.value
        switch ergebnis {
        case .success(let datei):
            senden(FeedbackPaketMessage(sitzung: sitzungID, name: name, datei: datei.path, saetze: paket.saetze.count,
                                        striche: paket.striche.count, dauerS: paket.dauerS))
            c.log(.info, "Feedback \(name): \(paket.saetze.count) Sätze, \(paket.striche.count) Striche")
            beiPaket?(datei, paket)
        case .failure(let fehler):
            c.log(.error, "Feedback nicht geschrieben: \(fehler.localizedDescription)")
            c.viewer.zeige("Das Feedback ließ sich nicht speichern: \(fehler.localizedDescription)", fehler: true)
        }
        aufraeumen()
    }

    /// Eine Nummer je Satz am ersten Zeiger: So findet der Agent im Bild, was welcher Satz meint.
    static func nummern(_ saetze: [FeedbackPaket.Satz]) -> [OverlayPrimitive] {
        saetze.compactMap { s in
            guard let p = s.bezuege.first(where: { $0.punkt != nil })?.punkt, p.count == 3 else { return nil }
            return .badge(point: SIMD3(Float(p[0]), Float(p[1]), Float(p[2])), text: String(s.nr), color: ViewerStil.strich,
                          filled: true)
        }
    }

    nonisolated static func jpeg(_ roh: FeedbackRohbild, overlay: [OverlayPrimitive]) -> Data? {
        let bild = overlay.isEmpty ? roh.image
            : (ScreenshotRenderer.composite(roh.image, overlay: overlay, camera: roh.kamera) ?? roh.image)
        let daten = NSMutableData()
        guard let ziel = CGImageDestinationCreateWithData(daten as CFMutableData, UTType.jpeg.identifier as CFString, 1, nil)
        else { return nil }
        CGImageDestinationAddImage(ziel, bild, [kCGImageDestinationLossyCompressionQuality: 0.82] as CFDictionary)
        return CGImageDestinationFinalize(ziel) ? daten as Data : nil
    }

    private func aufraeumen() {
        probenTakt?.invalidate()
        probenTakt = nil
        if let m = tastenMonitor { NSEvent.removeMonitor(m) }
        tastenMonitor = nil
        sitzung = nil
        projekt = nil
        erkennung = nil
        stoppen = nil
        stand = .aus
        schliesst = false
        gesagt = []
        zwischenstand = nil
        satzBeginn = nil
        controller?.viewport.zeichnen = false
        controller?.model.sprache.text = nil
        controller?.model.sprache.pegel = 0
        controller?.model.sprache.schickt = false
        controller?.refreshOverlay()
    }

    /// Wartet auf `aufgabe`, höchstens `s` Sekunden; die Aufgabe läuft danach weiter.
    private static func warten(auf aufgabe: Task<Void, Never>, hoechstens s: Double) async {
        let einmal = Einmal()
        await withCheckedContinuation { (k: CheckedContinuation<Void, Never>) in
            einmal.setzen(k)
            Task {
                await aufgabe.value
                einmal.weiter()
            }
            Task {
                try? await Task.sleep(for: .seconds(s))
                einmal.weiter()
            }
        }
    }

    private final class Einmal: @unchecked Sendable {
        private let sperre = NSLock()
        private var k: CheckedContinuation<Void, Never>?

        func setzen(_ k: CheckedContinuation<Void, Never>) { sperre.withLock { self.k = k } }

        func weiter() {
            let k = sperre.withLock { () -> CheckedContinuation<Void, Never>? in
                defer { self.k = nil }
                return self.k
            }
            k?.resume()
        }
    }
}

/// Bild der Ansicht beim Abschließen, noch ohne Striche und Nummern.
public struct FeedbackRohbild: @unchecked Sendable {
    public var image: CGImage
    public var kamera: CameraState
}

extension AppController {
    /// Kamera in den Feldern von LAGE.kamera (PROTOCOL.md).
    func lageKamera() -> JSONValue {
        let c = viewport.camera
        func v(_ p: SIMD3<Float>) -> JSONValue { .array(SprachSteuerung.zahlen(p).map(JSONValue.number)) }
        return .object([
            "position": v(c.position), "ziel": v(c.pivot), "richtung": v(c.viewDirection), "oben": v(c.upVector),
            "abstand": .number(Double(c.distance)), "projektion": .string(c.isOrthographic ? "orthographic" : "perspective"),
            "fov": c.isOrthographic ? .null : .number(Double(c.fieldOfView)),
            "ortho_hoehe": c.isOrthographic ? .number(Double(c.orthographicScale)) : .null,
            "ansicht": ViewportCoordinator.nearestStandardName(c).map(JSONValue.string) ?? .null,
            "durch": cameras.activeView.map { .string("Kamera/\($0)") } ?? .null,
        ])
    }

    /// Lage beim Abschließen, Felder wie LAGE ohne Kopf und Maus.
    func feedbackLage() -> JSONValue {
        let groesse = viewport.viewSize
        let projector = OverlayProjector(camera: viewport.camera, size: groesse)
        let bild = CGRect(origin: .zero, size: groesse)
        var sichtbar: [String] = []
        var verborgen: [String] = []
        for name in scene.order {
            guard scene.isVisible(name) else {
                verborgen.append(name)
                continue
            }
            if let b = scene.worldBounds(of: .part(name)), !Self.imBild(b, projector, bild) { continue }
            sichtbar.append(name)
        }
        let anim = model.animation
        var animation = JSONValue.null
        if anim.posed, let aktuell = anim.current {
            animation = .object(["name": .string(aktuell.name), "zeit": .number(anim.time), "spielt": .bool(anim.playing)])
        }
        func namen(_ n: [String]) -> JSONValue { .array(n.map(JSONValue.string)) }
        return .object([
            "kamera": lageKamera(),
            "viewport": .object(["breite": .number(groesse.width), "hoehe": .number(groesse.height)]),
            "sichtbar": namen(sichtbar), "verborgen": namen(verborgen),
            "isoliert": model.viewer.lokaleAnsicht ? namen(sichtbar) : .null,
            "auswahl": .object(["run": .number(Double(scene.latestRun)), "refs": namen(scene.selection.map(\.string))]),
            "darstellung": .string(model.viewer.shading.rawValue),
            "schnitt": model.sectionEnabled ? .object(["an": .bool(true)]) : .null,
            "explosion": .number(model.explodeFactor), "animation": animation,
        ])
    }

    /// Liegt der Hüllquader ganz oder teilweise im Bild?
    private static func imBild(_ b: BoundingBox, _ p: OverlayProjector, _ bild: CGRect) -> Bool {
        var punkte: [CGPoint] = []
        for x in [b.min.x, b.max.x] {
            for y in [b.min.y, b.max.y] {
                for z in [b.min.z, b.max.z] {
                    // Hinter der Kamera lässt sich nichts projizieren: im Zweifel zählt das Teil als im Bild
                    guard let s = p.project(SIMD3(x, y, z)) else { return true }
                    punkte.append(s)
                }
            }
        }
        let xs = punkte.map(\.x), ys = punkte.map(\.y)
        let huelle = CGRect(x: xs.min()!, y: ys.min()!, width: xs.max()! - xs.min()!, height: ys.max()! - ys.min()!)
        return huelle.intersects(bild)
    }

    /// Bild der Ansicht, längste Seite höchstens 1600 Pixel, ohne Überlagerung (die Striche kommen danach darauf).
    func feedbackBild() -> FeedbackRohbild? {
        let groesse = viewport.viewSize
        guard groesse.width > 0, groesse.height > 0, !scene.isEmpty else { return nil }
        let grenze = CGFloat(FeedbackGrenzen.bildLaengeMax)
        let faktor = min(2, grenze / max(groesse.width, groesse.height))
        let kamera = viewport.camera
        guard let bild = screenshots.renderBild(
            bodies: scene.snapshotBodies(), camera: kamera, width: Int(groesse.width * faktor),
            height: Int(groesse.height * faktor), displayMode: scene.viewportDisplayMode,
            lighting: viewport.controller.lightingConfiguration)
        else { return nil }
        return FeedbackRohbild(image: bild, kamera: kamera)
    }
}
