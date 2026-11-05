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
        guard let p = model.project else { return }
        let name = ProjectLocator.sanitizedName(eingabe)
        guard demo == nil else {
            melde("Im Demomodus bleibt der Name, wie er ist.", fehler: true)
            return
        }
        if model.isRunning {
            melde("Der Lauf ist noch nicht fertig. Danach klappt das Benennen.", fehler: true)
            return
        }
        do {
            let neu: URL
            if entwuerfe.enthaelt(p.path) {
                neu = try entwuerfe.uebernehmen(p.path, name: name, nach: AppInfo.projectsDirectory)
            } else {
                neu = try EntwurfAblage.umbenennen(p.path, name: name)
                if RecentProjects.normalizedPath(neu) == RecentProjects.normalizedPath(p.path) { return }
                recents.remove(p.path)
            }
            model.append(LogLine(text: "Projekt heißt jetzt „\(neu.lastPathComponent)“: "
                + KevFormat.abbreviatedPath(neu.path)))
            melde("Gesichert als „\(neu.lastPathComponent)“ in "
                + KevFormat.abbreviatedPath(neu.deletingLastPathComponent().path), fehler: false)
            letztesProjekt = neu
            actions?.openProject(at: neu)
        } catch {
            melde("Benennen ging nicht: \(error.localizedDescription)", fehler: true)
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

    // MARK: Modus und Kacheln merken

    static let modusSchluessel = "oberflaeche.modus"
    static let kachelSchluessel = "oberflaeche.kacheln"

    /// Modus und Kacheln wie beim letzten Beenden.
    static func oberflaecheVorbelegen(_ store: OberflaechenStore) {
        let d = UserDefaults.standard
        let modus = d.string(forKey: modusSchluessel).flatMap(ArbeitsModus.init(rawValue:)) ?? .fokus
        let kacheln = (d.stringArray(forKey: kachelSchluessel) ?? [KachelArt.modell.rawValue])
            .compactMap(KachelArt.init(rawValue:))
        store.vorbelegen(modus: modus, kacheln: kacheln)
    }

    func oberflaecheMerken() {
        model.oberflaeche.$zustand
            .map(Self.merkSchluessel)
            .removeDuplicates()
            .dropFirst()
            .sink { [weak self] _ in self?.oberflaecheSichern() }
            .store(in: &oberflaechenAbos)
    }

    /// Was sich gemerkt wird, als ein Text (zum Vergleichen).
    nonisolated static func merkSchluessel(_ z: OberflaechenZustand) -> String {
        let modus: ArbeitsModus = z.modusVorRand ?? z.modus
        let kacheln: [String] = z.kacheln.map { $0.rawValue }
        return modus.rawValue + "|" + kacheln.joined(separator: ",")
    }

    private func oberflaecheSichern() {
        let z = model.oberflaeche.zustand
        let modus: ArbeitsModus = z.modusVorRand ?? z.modus
        let kacheln: [String] = z.kacheln.map { $0.rawValue }
        UserDefaults.standard.set(modus.rawValue, forKey: Self.modusSchluessel)
        UserDefaults.standard.set(kacheln, forKey: Self.kachelSchluessel)
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

    /// Beim Beenden: Fenster nicht schmal zurücklassen, leeren Entwurf wegräumen.
    func beimBeenden() {
        fensterRandSteuerung.sofortZurueck(projectWindow)
        if let p = model.project, entwuerfe.enthaelt(p.path) { entwuerfe.loeschenWennLeer(p.path) }
    }
}
