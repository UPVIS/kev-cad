#if os(macOS)
import AppKit
#endif
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
    /// Das Mikrofon geht gerade an: Was Kevin jetzt sagt, hört die Erkennung womöglich nicht.
    @Published public internal(set) var startet = false

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
    /// Tests: an Stelle des Kernels, mit Nutzlast; die Rückgabe sagt, ob die Nachricht hinausging.
    var versand: ((any OutgoingMessage, Data) -> Bool)?
    /// I-5: Paket als Nutzlast schicken statt als Datei in den Projektordner. Vorgabe (nil): über das Netz verbunden,
    /// also auf dem iPad, das den Projektordner des Mac nicht hat.
    var paketMitschicken: Bool?
    /// Postausgang für Pakete, die nicht hinausgingen (Mac nicht verbunden); Vorgabe in der Ablage der App.
    var postausgangOrdner: URL?

    public var offen: Bool { sitzung != nil }
    public var spricht: Bool { stand == .spricht }
    /// So lange höchstens wartet ↩ auf die letzten Wörter (Budget: Paket beim Agenten unter 1 s). Wortlaut schließt einen
    /// Satz nach 0,6 s Stille ab; drückt Kevin ↩ gleich nach dem letzten Wort, ist der Satz damit gerade noch da.
    static let letzteWorteS = 0.7
    /// V hält an: Hier wartet niemand, der Satz darf zu Ende kommen.
    static let satzAbwartenS = 1.5
    /// Läuft die Erkennung noch an (Apples Modell lädt, unter Last Sekunden), steckt das Gesagte noch im Ton. Lieber warten,
    /// als Kevins Worte zu verlieren.
    static let kaltstartS = 12.0

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
        c.zeichnenSetzen(true)
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
        c.zeichnenSetzen(false)
        melden(.pause)
        let e = erkennung
        stoppen = Task { await e?.anhalten(hoechstens: Self.satzAbwartenS) }
    }

    private func weiter() {
        guard let c = controller else { return }
        let t = uhr()
        sitzung?.mikrofonAn(t: t)
        c.model.oberflaeche.ausfuehren(.sprechen(true))
        c.zeichnenSetzen(true)
        melden(.spricht)
        tonStarten()
    }

    private func tonStarten() {
        controller?.model.sprache.startet = true
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
        c.zeichnenSetzen(false)
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
        let frist = c.model.sprache.startet ? Self.kaltstartS : Self.letzteWorteS + 0.05
        Task { [weak self] in
            await Self.warten(auf: abschluss, hoechstens: frist)
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

    /// Neuer Kernel: Er kennt die offene Sitzung noch nicht. Was im Postausgang wartet, geht jetzt los.
    func nachVerbindung() {
        postausgangLeeren()
        guard let s = sitzung, stand != .aus else { return }
        senden(FeedbackStandMessage(sitzung: s.id, stand: stand, seit: standSeit))
    }

    @discardableResult
    private func senden<M: OutgoingMessage>(_ m: M, nutzlast: Data = Data()) -> Bool {
        gesendet?(m)
        if let versand { return versand(m, nutzlast) }
        return controller?.send(m, payload: nutzlast) ?? false
    }

    private func melden(_ neu: FeedbackStand, grund: FeedbackGrund? = nil) {
        guard let s = sitzung else { return }
        stand = neu
        standSeit = Date().timeIntervalSince1970
        senden(FeedbackStandMessage(sitzung: s.id, stand: neu, seit: standSeit, grund: grund))
    }

    /// Am Mac zuerst Wortlaut, Apples Erkennung als Rückfall; auf dem iPad gleich Apples Erkennung (Wortlaut ist eine
    /// Mac-App; dort fragt sie beim ersten Sprechen nach dem Mikrofon, I-5). Selbsttests und Demomodus fragen nie nach
    /// dem Mikrofon; der Testeingang liest eine Datei.
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
        #if os(macOS)
        return ErkennungMitRueckfall(erste: WortlautErkennung(), rueckfall: { apple(nil) })
        #else
        return apple(nil)
        #endif
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
        case .zustand(.hoert):
            c.model.sprache.startet = false
        case .zustand(.fehler(let meldung)):
            c.model.sprache.startet = false
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
        guard sitzung != nil, !schliesst else { return }  // nach ↩ zählt die Maus nicht mehr
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
        guard let c = controller, sitzung != nil, !schliesst else { return }
        let t = uhr()
        sitzung?.kamera(t: t, c.lageKamera())
        sitzung?.auswahl(t: t, run: c.scene.latestRun, refs: c.scene.selection.map(\.string))
    }

    /// ↩ gilt überall im Fenster, auch wenn der Fokus nicht im Viewer steht. Textfelder und Dialoge gehen vor.
    /// iPad: Senden in Daumenleiste und Live-Zeile, ↩ einer Tastatur über die Eingabeebene (`Tastenbelegung`).
    private func tastenAn() {
        #if os(macOS)
        guard tastenMonitor == nil else { return }
        tastenMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] e in
            nonisolated(unsafe) let e = e
            let verbraucht = MainActor.assumeIsolated { self?.taste(e) ?? false }
            return verbraucht ? nil : e
        }
        #endif
    }

    #if os(macOS)
    private func taste(_ e: NSEvent) -> Bool {
        guard Tastenbelegung.eingabeCodes.contains(e.keyCode), TastenMods(e.modifierFlags).isEmpty,
            let w = e.window, w.attachedSheet == nil, !NavigationInputView.istTexteingabe(w.firstResponder)
        else { return false }
        fertig()
        return true
    }
    #endif

    // MARK: Striche

    func strich(_ e: StrichEreignis) {
        guard let c = controller, sitzung != nil, !schliesst else { return }
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
        if paketMitschicken ?? c.connection.istNetz {
            await mitschicken(paket, bild: bild, overlay: overlay, sitzung: sitzungID)
            aufraeumen()
            return
        }
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

    // MARK: Paket als Nutzlast und Postausgang (I-5, PLAN-IPAD.md 4.5)

    /// Paket und Bild als Nutzlast an den Kernel am Mac; geht das nicht, wartet beides im Postausgang.
    private func mitschicken(_ paket: FeedbackPaket, bild: FeedbackRohbild?, overlay: [OverlayPrimitive],
                             sitzung: String) async {
        guard let c = controller else { return }
        let daten: Result<(Data, Data?), Error> = await Task.detached(priority: .userInitiated) {
            do {
                return .success((try paket.json(), bild.flatMap { Self.jpeg($0, overlay: overlay) }))
            } catch {
                return .failure(error)
            }
        }.value
        switch daten {
        case .success(let (json, jpeg)):
            let (m, nutzlast) = FeedbackPaketMessage.mitNutzlast(
                sitzung: sitzung, name: paket.name, json: json, bild: jpeg, saetze: paket.saetze.count,
                striche: paket.striche.count, dauerS: paket.dauerS)
            if senden(m, nutzlast: nutzlast) {
                c.log(.info, "Feedback \(paket.name) an den Mac: \(paket.saetze.count) Sätze, \(paket.striche.count) "
                    + "Striche, \(nutzlast.count / 1024) KB")
            } else if postausgangAblegen(m, nutzlast: nutzlast) {
                c.viewer.zeige("Der Mac ist gerade nicht verbunden. Dein Feedback geht los, sobald er wieder da ist.")
            } else {
                c.viewer.zeige("Der Mac ist nicht verbunden, das Feedback ist nicht angekommen.", fehler: true)
            }
        case .failure(let fehler):
            c.log(.error, "Feedback nicht gepackt: \(fehler.localizedDescription)")
            c.viewer.zeige("Das Feedback ließ sich nicht packen: \(fehler.localizedDescription)", fehler: true)
        }
    }

    /// Ein wartendes Paket: die Felder der Nachricht und die Größen in der Nutzlast daneben.
    private struct Wartend: Codable {
        var sitzung: String
        var name: String
        var saetze: Int
        var striche: Int
        var dauerS: Double
        var json: Int
        var bild: Int
    }

    /// Postausgang in der Ablage der App (nur auf dem iPad; am Mac liegt das Paket gleich im Projektordner).
    private var postausgang: URL? {
        if let postausgangOrdner { return postausgangOrdner }
        #if os(iOS)
        return FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first?
            .appendingPathComponent("Postausgang", isDirectory: true)
        #else
        return nil
        #endif
    }

    /// Je Paket `<name>.kopf` und `<name>.nutzlast`; true, wenn beides liegt.
    private func postausgangAblegen(_ m: FeedbackPaketMessage, nutzlast: Data) -> Bool {
        guard let ordner = postausgang, let n = m.nutzlast else { return false }
        let w = Wartend(sitzung: m.sitzung, name: m.name, saetze: m.saetze, striche: m.striche, dauerS: m.dauerS,
                        json: n.json, bild: n.bild)
        do {
            try FileManager.default.createDirectory(at: ordner, withIntermediateDirectories: true)
            try nutzlast.write(to: ordner.appendingPathComponent(m.name + ".nutzlast"), options: .atomic)
            try JSONEncoder().encode(w).write(to: ordner.appendingPathComponent(m.name + ".kopf"), options: .atomic)
            controller?.log(.info, "Feedback \(m.name) wartet im Postausgang")
            return true
        } catch {
            controller?.log(.error, "Postausgang: \(error.localizedDescription)")
            return false
        }
    }

    /// Wartende Pakete senden, das älteste zuerst; was hinausging, verlässt den Postausgang. Ohne Verbindung bleibt alles.
    func postausgangLeeren() {
        let fm = FileManager.default
        guard let ordner = postausgang,
            let dateien = try? fm.contentsOfDirectory(at: ordner, includingPropertiesForKeys: nil)
        else { return }
        let koepfe = dateien.filter { $0.pathExtension == "kopf" }.sorted { $0.lastPathComponent < $1.lastPathComponent }
        for kopf in koepfe {
            let datei = kopf.deletingPathExtension().appendingPathExtension("nutzlast")
            guard let w = try? JSONDecoder().decode(Wartend.self, from: Data(contentsOf: kopf)),
                let nutzlast = try? Data(contentsOf: datei), nutzlast.count == w.json + w.bild
            else {
                // Halb geschrieben oder kaputt: Es hielte sonst alles Spätere auf
                controller?.log(.error, "Postausgang: \(kopf.lastPathComponent) unvollständig, entfernt")
                try? fm.removeItem(at: kopf)
                try? fm.removeItem(at: datei)
                continue
            }
            let (m, n) = FeedbackPaketMessage.mitNutzlast(
                sitzung: w.sitzung, name: w.name, json: Data(nutzlast.prefix(w.json)),
                bild: w.bild > 0 ? Data(nutzlast.suffix(w.bild)) : nil, saetze: w.saetze, striche: w.striche,
                dauerS: w.dauerS)
            guard senden(m, nutzlast: n) else { return }
            try? fm.removeItem(at: kopf)
            try? fm.removeItem(at: datei)
            controller?.log(.info, "Feedback \(w.name) aus dem Postausgang nachgeschickt")
            controller?.viewer.zeige("Dein Feedback von vorhin ist jetzt beim Mac.")
        }
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
        #if os(macOS)
        if let m = tastenMonitor { NSEvent.removeMonitor(m) }
        #endif
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
        controller?.zeichnenSetzen(false)
        controller?.model.sprache.text = nil
        controller?.model.sprache.pegel = 0
        controller?.model.sprache.schickt = false
        controller?.model.sprache.startet = false
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
    /// Kamera in den Feldern von LAGE.kamera (PROTOCOL.md), ohne den Rest des Lagebilds: Sie geht zehnmal je Sekunde durch.
    func lageKamera() -> JSONValue {
        let c = viewport.camera
        func v(_ p: SIMD3<Float>) -> JSONValue { .array(SprachSteuerung.zahlen(p).map(JSONValue.number)) }
        return .object([
            "position": v(c.position), "ziel": v(c.pivot), "richtung": v(c.viewDirection), "oben": v(c.upVector),
            "abstand": .number(Double(c.distance)), "projektion": .string(c.isOrthographic ? "orthographic" : "perspective"),
            "fov": c.isOrthographic ? .null : .number(Double(c.fieldOfView)),
            "ortho_hoehe": c.isOrthographic ? .number(Double(c.orthographicScale)) : .null,
            "ansicht": ViewportCoordinator.nearestStandardName(c).map(JSONValue.string) ?? .null,
            "durch": cameras.activeView.map { .string($0.hasPrefix("Kamera/") ? $0 : "Kamera/" + $0) } ?? .null,
        ])
    }

    /// Lage beim Abschließen: das Lagebild (V2-5) ohne Maus und ohne Zahlen für den Selbsttest.
    func feedbackLage() -> JSONValue {
        var felder = lagebild()
        felder["maus"] = nil
        felder["statistik"] = nil
        return .object(felder)
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
