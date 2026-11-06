import AppKit
import Combine
import KevCADCore
import SwiftUI

// V2-3 (OBERFLAECHE.md, Abschnitt 3): Start ohne Dialog in ein leeres Projekt, Benennen, Umbenennen von Teilen und
// Parametern aus der Werkstatt, Fenster am Rand.
//
// Ablauf beim Start: Ist der Kernel bereit und hat 0,35 s danach noch niemand ein Projekt geöffnet (Wiederherstellen
// nach einem Update, Selbsttest, ein schneller Klick in der Startübersicht, der Agent), legt die App einen Entwurf an
// (PROJECT_NEW mit der leeren Vorlage). Bis dahin zeigt das Fenster schon das leere Projekt; bedienbar ist es sofort.

extension AppSession {
    /// Das offene Projekt ist ein Entwurf (oder es ist noch keins offen).
    var istEntwurf: Bool {
        guard let p = model.project else { return true }
        return entwuerfe.enthaelt(p.path)
    }

    /// Name in der Kopfleiste: „Neues Projekt“ beim Entwurf, sonst der Projektname.
    var projektTitel: String {
        guard let p = model.project, !entwuerfe.enthaelt(p.path) else { return EntwurfAblage.projektName }
        return p.name
    }

    // MARK: Start und neues Projekt

    func entwurfVorbereiten(wiederherstellen: Bool) {
        let selbsttest = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"]
        startEntwurfErlaubt = demo == nil && !wiederherstellen && (selbsttest == nil || selbsttest == "oberflaeche")
        // Leere Entwürfe früherer Sitzungen weg (nur Ordnerliste und Prüfsummen weniger kleiner Dateien)
        entwuerfe.aufraeumen()
        if !wiederherstellen && demo?.config.isFrozen != true
            && (!recents.items.isEmpty || !entwuerfe.mitInhalt().isEmpty)
        {
            model.oberflaechenActions?.zeigeUebersicht(true)
        }
        guard startEntwurfErlaubt else { return }
        model.$kernelState
            .filter { $0 == .ready }
            .first()
            .delay(for: .milliseconds(350), scheduler: DispatchQueue.main)
            .sink { [weak self] _ in
                guard let self, self.model.project == nil else { return }
                self.entwurfAnlegen()
            }
            .store(in: &oberflaechenAbos)
    }

    /// Neuer Entwurf: Ordner in der Ablage, Kernel legt model.py mit der leeren Vorlage an.
    func entwurfAnlegen() {
        let ordner = entwuerfe.neuerProjektordner()
        try? FileManager.default.createDirectory(at: ordner.deletingLastPathComponent(), withIntermediateDirectories: true)
        actions?.newProject(at: ordner, template: ProjectTemplate.empty.rawValue)
    }

    /// ⌘N: sofort ein leeres Projekt, ohne Formular. Ist das offene schon ein leerer Entwurf, bleibt es dabei.
    func neuesProjekt() {
        model.oberflaechenActions?.zeigeUebersicht(false)
        showProjectWindow()
        if let p = model.project, entwuerfe.enthaelt(p.path), entwuerfe.istLeer(p.path) { return }
        if demo != nil {
            actions?.newProject(at: proposedFolder(for: EntwurfAblage.projektName), template: ProjectTemplate.empty.rawValue)
            return
        }
        entwurfAnlegen()
    }

    // MARK: Benennen

    /// Gibt dem Projekt einen Namen. Ein Entwurf zieht dabei nach ~/Documents/Kev CAD (bzw. `KEVCAD_PROJECTS_DIR`), ein
    /// benanntes Projekt wird im selben Ordner umbenannt. Danach öffnet der Kernel es am neuen Ort.
    func projektBenennen(_ eingabe: String) {
        if case .failure(let f) = projektUmziehen(eingabe) { melde(f.text, fehler: true) }
    }

    /// Dasselbe für Kevin (Doppelklick auf den Titel, ⇧⌘S) und den Agenten (`VIEW_CMD projekt_name`): neuer Ort oder der Grund,
    /// warum es nicht ging.
    func projektUmziehen(_ eingabe: String) -> Result<URL, FlaecheFehler> {
        guard let p = model.project else { return .failure(.init("Es ist kein Projekt offen.")) }
        let name = ProjectLocator.sanitizedName(eingabe)
        guard demo == nil else { return .failure(.init("Im Demomodus bleibt der Name, wie er ist.")) }
        if model.isRunning {
            return .failure(.init("Der Lauf ist noch nicht fertig. Danach klappt das Benennen."))
        }
        do {
            let neu: URL
            if entwuerfe.enthaelt(p.path) {
                neu = try entwuerfe.uebernehmen(p.path, name: name, nach: AppInfo.projectsDirectory)
            } else {
                neu = try EntwurfAblage.umbenennen(p.path, name: name)
                if RecentProjects.normalizedPath(neu) == RecentProjects.normalizedPath(p.path) { return .success(p.path) }
                recents.remove(p.path)
            }
            model.append(LogLine(text: "Projekt heißt jetzt „\(neu.lastPathComponent)“: "
                + KevFormat.abbreviatedPath(neu.path)))
            melde("Gesichert als „\(neu.lastPathComponent)“ in "
                + KevFormat.abbreviatedPath(neu.deletingLastPathComponent().path), fehler: false)
            letztesProjekt = neu
            actions?.openProject(at: neu)
            return .success(neu)
        } catch {
            return .failure(.init("Benennen ging nicht: \(error.localizedDescription)"))
        }
    }

    // MARK: Änderungen an model.py aus der Werkstatt

    /// Teil oder Gruppe umbenennen (Doppelklick in der Gliederung): ändert die Namen in model.py, dann neu rechnen.
    func teilBenennen(_ id: String, gruppe: Bool, neu: String) {
        guard let datei = model.project?.modelFile,
              let code = try? String(contentsOf: datei, encoding: .utf8)
        else { return }
        switch ModellQuelle.benenneUm(code, name: id, gruppe: gruppe, neuerLetzterTeil: neu) {
        case .success(let r):
            do {
                try ModellQuelle.schreiben(r.code, nach: datei)
            } catch {
                melde("model.py ließ sich nicht schreiben: \(error.localizedDescription)", fehler: true)
                return
            }
            model.append(LogLine(text: "„\(id)“ heißt jetzt „\(r.neuerName)“ (\(r.stellen) Stellen in model.py)"))
            if !model.autoRun { actions?.runModel() }
        case .failure(let f):
            melde(f.errorDescription ?? "Umbenennen ging nicht.", fehler: true)
        }
    }

    /// Maß des Modells setzen (Feld in der Werkstatt): Vorgabewert von `param("name", …)` in model.py.
    func parameterSetzen(_ name: String, text: String) {
        guard let wert = ModellQuelle.zahl(aus: text) else {
            melde(ModellQuelle.Fehler.ungueltigeZahl(text).errorDescription ?? "", fehler: true)
            return
        }
        guard let datei = model.project?.modelFile,
              let code = try? String(contentsOf: datei, encoding: .utf8)
        else { return }
        switch ModellQuelle.setzeParameter(code, name: name, wert: wert) {
        case .success(let neu):
            do {
                try ModellQuelle.schreiben(neu, nach: datei)
            } catch {
                melde("model.py ließ sich nicht schreiben: \(error.localizedDescription)", fehler: true)
                return
            }
            model.append(LogLine(text: "\(name) = \(ModellQuelle.zahlText(wert)) in model.py"))
            if !model.autoRun { actions?.runModel() }
        case .failure(let f):
            melde(f.errorDescription ?? "Ändern ging nicht.", fehler: true)
        }
    }

    // MARK: Meldungen

    /// Kurze Meldung in der Kopfleiste, verschwindet nach einigen Sekunden.
    func melde(_ text: String, fehler: Bool) {
        let m = Meldung(text: text, fehler: fehler)
        meldung = m
        if fehler { model.append(LogLine(level: .warning, text: text)) }
        DispatchQueue.main.asyncAfter(deadline: .now() + (fehler ? 8 : 5)) { [weak self] in
            if self?.meldung == m { self?.meldung = nil }
        }
    }

    // MARK: Leisten und Kacheln merken

    static let leistenSchluessel = "oberflaeche.leisten"
    static let grossSchluessel = "oberflaeche.gross"
    static let kachelSchluessel = "oberflaeche.kacheln"
    static let ansichtSchluessel = "kachel.ansicht"

    /// Leisten und Kacheln wie beim letzten Beenden. Ohne gemerkte Leisten (erster Start nach V2-9) wie das ruhige Bild:
    /// Objekte links, rechte Leiste zu, Kacheln eingeklappt.
    static func oberflaecheVorbelegen(_ store: OberflaechenStore) {
        let d = UserDefaults.standard
        let kacheln = (d.stringArray(forKey: kachelSchluessel) ?? [KachelArt.modell.rawValue])
            .compactMap(KachelArt.init(rawValue:))
        let ansicht = d.string(forKey: ansichtSchluessel).flatMap {
            standardAnsichten.contains($0) ? $0 : nil  // früher Namen der Viewport-Bibliothek
        }
        let leisten = d.stringArray(forKey: leistenSchluessel)
        let gross = leisten == nil ? (kacheln.count > 1 ? KachelArt.modell : nil)
            : d.string(forKey: grossSchluessel).flatMap(KachelArt.init(rawValue:))
        store.vorbelegen(leisteLinks: leisten?.contains("links") ?? true, leisteRechts: leisten?.contains("rechts") ?? false,
                         kacheln: kacheln, gross: gross, zweiteAnsicht: ansicht)
    }

    func oberflaecheMerken() {
        model.oberflaeche.$zustand
            .map(Self.merkSchluessel)
            .removeDuplicates()
            .dropFirst()
            .sink { [weak self] _ in self?.oberflaecheSichern() }
            .store(in: &oberflaechenAbos)
    }

    /// Was gemerkt wird (am Rand der Stand davor), als Werte zum Vergleichen.
    nonisolated static func merkWerte(_ z: OberflaechenZustand) -> (leisten: [String], gross: String, kacheln: [String]) {
        let rechts = z.vorRand?.leisteRechts ?? z.leisteRechts
        let gross = z.rand != nil ? z.vorRand?.gross : z.gross
        var leisten: [String] = []
        if z.leisteLinks { leisten.append("links") }
        if rechts { leisten.append("rechts") }
        return (leisten, gross?.rawValue ?? "", z.kacheln.map { $0.rawValue })
    }

    /// Was sich gemerkt wird, als ein Text (zum Vergleichen).
    nonisolated static func merkSchluessel(_ z: OberflaechenZustand) -> String {
        let w = merkWerte(z)
        return w.leisten.joined(separator: ",") + "|" + w.gross + "|" + w.kacheln.joined(separator: ",") + "|"
            + z.zweiteAnsicht
    }

    private func oberflaecheSichern() {
        let z = model.oberflaeche.zustand
        let w = Self.merkWerte(z)
        UserDefaults.standard.set(w.leisten, forKey: Self.leistenSchluessel)
        UserDefaults.standard.set(w.gross, forKey: Self.grossSchluessel)
        UserDefaults.standard.set(w.kacheln, forKey: Self.kachelSchluessel)
        UserDefaults.standard.set(z.zweiteAnsicht, forKey: Self.ansichtSchluessel)
    }

    // MARK: Fenster

    /// Hauptfenster einrichten: dunkel (Graphit), Platz für die Ampel in der Kopfleiste.
    func fensterEinrichten(_ fenster: NSWindow) {
        fenster.appearance = NSAppearance(named: .darkAqua)
        fenster.titlebarAppearsTransparent = true
        fenster.titleVisibility = .hidden
        fenster.backgroundColor = NSColor(srgbRed: 0.098, green: 0.102, blue: 0.114, alpha: 1)  // Graphit „tief“
    }

    /// Fenster an den Rand bzw. zurück (folgt `oberflaeche.rand`).
    func fensterRand(_ rand: Bildschirmrand?) {
        fensterRandSteuerung.anwenden(rand, fenster: projectWindow)
    }

    /// Ein Klick in den Viewer macht in der Werkstatt das Modell zur aktiven Kachel (der Viewer ist eine Metal-Ansicht
    /// und meldet Klicks nicht an SwiftUI). Das Ereignis läuft unverändert weiter.
    func viewerKlickBeobachten() {
        guard viewerKlickMonitor == nil else { return }
        viewerKlickMonitor = NSEvent.addLocalMonitorForEvents(matching: .leftMouseDown) { [weak self] event in
            nonisolated(unsafe) let event = event
            MainActor.assumeIsolated {
                guard let self, let w = self.projectWindow, event.window === w, let v = w.contentView else { return }
                let o = self.model.oberflaeche
                guard o.kachelflaeche, o.aktiv != .modell, o.kacheln.contains(.modell) else { return }
                let p = CGPoint(x: event.locationInWindow.x, y: v.bounds.height - event.locationInWindow.y)
                if self.viewerRahmen.contains(p) {
                    self.model.oberflaechenActions?.oberflaeche(.kachelAktiv(.modell))
                }
            }
            return event
        }
    }

    /// Beim Beenden: Fenster nicht schmal zurücklassen, leeren Entwurf wegräumen.
    func beimBeenden() {
        fensterRandSteuerung.sofortZurueck(projectWindow)
        if let p = model.project, entwuerfe.enthaelt(p.path) { entwuerfe.loeschenWennLeer(p.path) }
    }
}
