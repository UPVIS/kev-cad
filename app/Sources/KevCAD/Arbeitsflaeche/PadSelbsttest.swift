#if os(iOS)
import KevCADCore
import SwiftUI
import UIKit

/// Selbsttest der Oberfläche auf dem iPad (PLAN-IPAD.md, I-9), ohne Mac-Prozesse: Start, Leisten, jede Kachel, die Blätter
/// für Protokoll und Lagerkatalog. Alles über `OberflaechenActions` und `AppSession` wie am Mac (`OberflaechenSelbsttest`),
/// gemessen wird die längste Pause des Hauptfadens; je Zustand ein Bild des Fensters. Start mit `KEVCAD_SELFTEST=pad`
/// (Debug-Bau, `tools/ipad-bau.sh selbsttest`). Ergebnis in `<Datenordner>/selftest-pad/bericht.txt`, die letzte Zeile ist
/// „ENDE bestanden“ bzw. „ENDE nicht bestanden“.
@MainActor
enum PadSelbsttest {
    private static var started = false
    private static var env: [String: String] { ProcessInfo.processInfo.environment }

    static var ausgabe: URL { AppInfo.supportDirectory.appendingPathComponent("selftest-pad", isDirectory: true) }

    static func runIfRequested(_ session: AppSession) {
        #if DEBUG
        guard !started, ["pad", "pad-bereiche"].contains(env["KEVCAD_SELFTEST"] ?? "") else { return }
        started = true
        if env["KEVCAD_SELFTEST"] == "pad-bereiche" {
            Task { await bereiche(session) }
        } else {
            Task { await run(session) }
        }
        #endif
    }

    private static func run(_ session: AppSession) async {
        let model = session.model
        let o = model.oberflaeche
        let a = model.oberflaechenActions
        var zeilen: [String] = []
        var ok = true
        try? FileManager.default.removeItem(at: ausgabe)
        try? FileManager.default.createDirectory(at: ausgabe, withIntermediateDirectories: true)
        func pruefe(_ b: Bool, _ text: String) {
            ok = ok && b
            zeilen.append("\(b ? "OK    " : "FEHLER") \(text)")
        }
        func notiere(_ text: String) { zeilen.append("       \(text)") }
        func pause(_ s: Double) async { try? await Task.sleep(for: .milliseconds(Int(s * 1000))) }
        func warte(_ s: Double, _ bedingung: () -> Bool) async -> Bool {
            let ende = Date().addingTimeInterval(s)
            while Date() < ende {
                if bedingung() { return true }
                await pause(0.05)
            }
            return bedingung()
        }
        func haenger(_ dauer: Double, _ aktion: () -> Void) async -> Double {
            let messer = HaengerMesser()
            messer.start()
            aktion()
            await pause(dauer)
            return messer.stop()
        }
        func foto(_ name: String) async {
            await pause(0.4)
            let szenen = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            guard let fenster = szenen.first?.keyWindow ?? szenen.first?.windows.first else { return }
            let bild = UIGraphicsImageRenderer(bounds: fenster.bounds).image { _ in
                fenster.drawHierarchy(in: fenster.bounds, afterScreenUpdates: true)
            }
            try? bild.pngData()?.write(to: ausgabe.appendingPathComponent(name + ".png"))
        }

        // 1. Start: Fenster da, Beispielmodell im Demo-Lauf des App-Kerns
        let teile = await warte(30) { !model.parts.isEmpty }
        pruefe(teile, "Teile da: \(model.parts.count)")
        pruefe(a != nil, "Oberfläche hat ihre Aktionen")
        a?.ordneKacheln([.modell])
        a?.zeigeUebersicht(false)
        pruefe(!o.uebersicht, "Startübersicht weggeschoben")
        await foto("01-start")

        // 2. Leisten
        var ms = await haenger(0.8) { a?.setzeLeisteRechts(true) }
        pruefe(o.leisteRechts, String(format: "Eigenschaften rechts an (längste Pause %.0f ms)", ms))
        await foto("02-leiste-rechts")
        a?.setzeLeisteRechts(false)
        a?.setzeLeisteLinks(true)
        await pause(0.4)
        pruefe(o.leisteLinks, "Gliederung links an")
        await foto("03-leiste-links")
        a?.setzeLeisteLinks(false)

        // 3. Jede Kachel einzeln: erscheint, kostet keine lange Pause, Bild
        for art in KachelArt.allCases where art != .modell {
            ms = await haenger(1.0) { a?.zeigeKachel(art) }
            pruefe(o.kacheln.contains(art), String(format: "Kachel %@ (längste Pause %.0f ms)", art.titel, ms))
            if ms > 500 { notiere("Achtung: Kachel \(art.titel) hielt den Hauptfaden \(Int(ms)) ms an") }
            await foto("04-kachel-\(art.rawValue)")
            a?.schliesseKachel(art)
            await pause(0.2)
        }
        a?.ordneKacheln([.modell])

        // 4. Blätter, die am Mac eigene Fenster sind
        session.showLog()
        pruefe(session.padBlatt == .protokoll, "Protokoll als Blatt")
        await foto("05-protokoll")
        session.padBlatt = nil
        await pause(0.6)
        session.showCatalog()
        pruefe(session.padBlatt == .lagerkatalog, "Lagerkatalog als Blatt")
        await foto("06-lagerkatalog")
        session.padBlatt = nil
        await pause(0.6)

        // 5. Dateien: ohne Mac kann das Gerät Dateien nicht vom Mac holen, eigene Dateien bleiben, wo sie sind
        if let d = model.actions as? DateiActions {
            let lokal = ausgabe.appendingPathComponent("probe.txt")
            try? Data("probe".utf8).write(to: lokal)
            let url = try? await d.dateiFuerGeraet(lokal)
            pruefe(url == lokal, "eigene Datei zum Teilen ohne Umweg")
        }

        // 6. Berichte als PDF am Gerät (CoreGraphics, ohne Mac): Stückliste in den Zwischenspeicher
        if let x = model.exportActions {
            let ziel = ausgabe.appendingPathComponent("Stueckliste.pdf")
            let v = ExportVorlage(name: "Stückliste", bausteine: [ExportBausteinWahl(art: .stueckliste)])
            do {
                let e = try await x.exportPDF(v, nach: ziel)
                let groesse = (try? FileManager.default.attributesOfItem(atPath: ziel.path)[.size] as? Int) ?? 0
                pruefe(e.seiten > 0 && groesse > 1000, "Stückliste als PDF am Gerät: \(e.seiten) Seiten, \(groesse) Byte")
            } catch {
                pruefe(false, "Stückliste als PDF am Gerät: \(error)")
            }
        }

        zeilen.append("ENDE \(ok ? "bestanden" : "nicht bestanden")")
        let bericht = (["Selbsttest Oberfläche iPad"] + zeilen).joined(separator: "\n") + "\n"
        try? bericht.write(to: ausgabe.appendingPathComponent("bericht.txt"), atomically: true, encoding: .utf8)
        print(bericht)
    }

    /// Stufe `pad-bereiche` (I-9): Die Bereiche, deren Daten der Kernel am Mac rechnet, über die Kopplung an eine
    /// Mac-Testvariante (`tools/ipad-kette.sh --bereiche`, das Modell baut der Kettentest über MCP). Je Bereich: Kachel
    /// auf, Daten aus dem Kernel da (DOCS und ein gerechnetes Blatt, BAUPLAN, PRINT_PREVIEW, BESTAND), Pause des
    /// Hauptfadens, Bild. Am Blatt dazu, was am Mac der Dokumente-Selbsttest prüft und am iPad ohne Maus geht: die
    /// Leinwand ist da, das Kontextmenü hat Einträge, Drucken teilt in Aufträge je Format. Statik und Simulation sind
    /// beim Beispielmodell ohne Lasten leer; sie werden nur vermerkt. Bericht wie `pad` in `selftest-pad/bericht.txt`.
    private static func bereiche(_ session: AppSession) async {
        let model = session.model
        let o = model.oberflaeche
        let a = model.oberflaechenActions
        var zeilen: [String] = []
        var ok = true
        try? FileManager.default.removeItem(at: ausgabe)
        try? FileManager.default.createDirectory(at: ausgabe, withIntermediateDirectories: true)
        func pruefe(_ b: Bool, _ text: String) {
            ok = ok && b
            zeilen.append("\(b ? "OK    " : "FEHLER") \(text)")
        }
        func notiere(_ text: String) { zeilen.append("       \(text)") }
        func pause(_ s: Double) async { try? await Task.sleep(for: .milliseconds(Int(s * 1000))) }
        func warte(_ s: Double, _ bedingung: () -> Bool) async -> Bool {
            let ende = Date().addingTimeInterval(s)
            while Date() < ende {
                if bedingung() { return true }
                await pause(0.1)
            }
            return bedingung()
        }
        func kachel(_ art: KachelArt) async -> Double {
            let messer = HaengerMesser()
            messer.start()
            a?.zeigeKachel(art)
            await pause(1.0)
            return messer.stop()
        }
        func foto(_ name: String) async {
            await pause(0.4)
            let szenen = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            guard let fenster = szenen.first?.keyWindow ?? szenen.first?.windows.first else { return }
            let bild = UIGraphicsImageRenderer(bounds: fenster.bounds).image { _ in
                fenster.drawHierarchy(in: fenster.bounds, afterScreenUpdates: true)
            }
            try? bild.pngData()?.write(to: ausgabe.appendingPathComponent(name + ".png"))
        }
        func leinwand() -> BlattLeinwand? {
            func suche(_ v: UIView) -> BlattLeinwand? {
                if let l = v as? BlattLeinwand { return l }
                for k in v.subviews { if let l = suche(k) { return l } }
                return nil
            }
            let szenen = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            return szenen.flatMap(\.windows).lazy.compactMap { suche($0) }.first
        }

        // 1. Verbunden mit dem Mac, Modell vom Kettentest gebaut
        pruefe(await warte(240) { model.kernelState == .ready }, "Kernel am Mac verbunden")
        pruefe(await warte(240) { !model.parts.isEmpty && !model.isRunning }, "Modell da: \(model.parts.count) Teile")
        a?.ordneKacheln([.modell])
        a?.zeigeUebersicht(false)
        await foto("b01-verbunden")

        // 2. Zeichnung (DOCS, DRAWING): Blätter erzeugen, erstes rechnen, Leinwand mit Kontextmenü, Druckaufträge
        var ms = await kachel(.zeichnung)
        pruefe(o.kacheln.contains(.zeichnung), String(format: "Kachel Zeichnung (längste Pause %.0f ms)", ms))
        let d = model.dokumente
        if d.uebersicht == nil { model.dokumenteActions?.dokumenteAnfordern() }
        pruefe(await warte(60) { d.uebersicht != nil }, "Übersicht der Blätter vom Kernel (DOCS)")
        if d.uebersicht?.blaetter.isEmpty ?? true {
            model.dokumenteActions?.zeichnungenErzeugen(teile: nil, art: "teil", format: nil)
        }
        pruefe(await warte(120) { !(d.uebersicht?.blaetter.isEmpty ?? true) },
               "Blätter erzeugt: \(d.uebersicht?.blaetter.count ?? 0)")
        if let erstes = d.uebersicht?.blaetter.first?.id {
            if d.zeichnung(erstes) == nil { model.dokumenteActions?.zeichnungAnfordern(erstes) }
            pruefe(await warte(90) { d.zeichnung(erstes) != nil }, "Blatt \(erstes) gerechnet (DRAWING)")
            if let z = d.zeichnung(erstes) {
                let auftraege = BlattDruck.auftraege([z])
                pruefe(auftraege.count == 1, "Drucken: \(auftraege.count) Auftrag im Format \(auftraege.first?.format ?? "-")")
                let pdf = BlattPDF.daten([z], metadaten: .init(titel: "Selbsttest"), inhaltsverzeichnis: false)
                pruefe(pdf.count > 1000, "Blatt als PDF am Gerät: \(pdf.count) Byte")
            }
        }
        await pause(1.0)
        if let l = leinwand() {
            pruefe(l.bounds.width > 100, "Leinwand der Blätter da (\(Int(l.bounds.width)) × \(Int(l.bounds.height)) pt)")
            let mitte = l.mm(CGPoint(x: l.bounds.midX, y: l.bounds.midY))
            let menue = l.menueEintraege(at: mitte)
            pruefe(!menue.isEmpty, "Kontextmenü auf dem Blatt: \(menue.count) Einträge")
        } else {
            pruefe(false, "Leinwand der Blätter da")
        }
        await foto("b02-zeichnung")
        a?.schliesseKachel(.zeichnung)

        // 3. Bauplan (BAUPLAN)
        ms = await kachel(.bauplan)
        pruefe(o.kacheln.contains(.bauplan), String(format: "Kachel Bauplan (längste Pause %.0f ms)", ms))
        if model.bauplan.plan == nil { model.bauplanActions?.bauplanAnfordern() }
        pruefe(await warte(120) { model.bauplan.plan != nil }, "Bauplan vom Kernel (BAUPLAN)")
        await foto("b03-bauplan")
        a?.schliesseKachel(.bauplan)

        // 4. Druck (PRINT_PREVIEW)
        ms = await kachel(.druck)
        pruefe(o.kacheln.contains(.druck), String(format: "Kachel Druck (längste Pause %.0f ms)", ms))
        if model.druck.vorschau == nil { model.druckActions?.druckvorschauAnfordern() }
        pruefe(await warte(120) { model.druck.vorschau != nil },
               "Druckvorschau vom Kernel (PRINT_PREVIEW): \(model.druck.vorschau?.platten.count ?? 0) Platten")
        await foto("b04-druck")
        // Vor „3MF sichern“ fragt das Blatt nach dem Filament (Kevins Regel, gleiche Texte wie am Mac); der Kettentest
        // baut dafür ein Druckteil ins Modell
        pruefe(await warte(60) { !(model.druck.vorschau?.istLeer ?? true) },
               "Druckvorschau mit Platten: \(model.druck.vorschau?.platten.count ?? 0)")
        if let v = model.druck.vorschau, !v.istLeer {
            let wahl = ExportFilamentWahl(v, platten: [])
            pruefe(!wahl.zeilen.isEmpty && wahl.zeilen.allSatisfy { $0.vorgewaehlt != nil },
                   "Filamentwahl vor dem 3MF: " + wahl.zeilen.map { z in
                       "\(z.name) → \(z.liste.first { $0.id == z.vorgewaehlt }?.name ?? "keins")"
                   }.joined(separator: ", "))
            DruckUI.shared.exportFilament = ExportFilamentAnfrage(platten: [], vorschau: v)
            await pause(1.0)
            await foto("b04-druck-filament")
            DruckUI.shared.exportFilament = nil
            await pause(0.8)
        }
        a?.schliesseKachel(.druck)

        // 5. Bestand (BESTAND), gezeigt in der Stückliste
        ms = await kachel(.stueckliste)
        pruefe(o.kacheln.contains(.stueckliste), String(format: "Kachel Stückliste (längste Pause %.0f ms)", ms))
        if !model.bestandZustand.empfangen { (model.actions as? BestandActions)?.requestBestand() }
        pruefe(await warte(60) { model.bestandZustand.empfangen }, "Bestand vom Kernel (BESTAND)")
        pruefe(model.bom != nil, "Stückliste vom Lauf")
        await foto("b05-stueckliste")
        a?.schliesseKachel(.stueckliste)

        // 6. Simulation und Statik: ohne Lasten im Beispielmodell nur vermerken
        ms = await kachel(.simulation)
        pruefe(o.kacheln.contains(.simulation), String(format: "Kachel Simulation (längste Pause %.0f ms)", ms))
        _ = await warte(10) { model.simulation.stand != nil }
        notiere("Simulation: Stand \(model.simulation.stand == nil ? "keiner (Modell ohne Lasten)" : "da")")
        notiere("Statik: Ergebnis \(model.statik.ergebnis == nil ? "keins (Modell ohne Lasten)" : "da")")
        await foto("b06-simulation")
        a?.schliesseKachel(.simulation)
        a?.ordneKacheln([.modell])

        zeilen.append("ENDE \(ok ? "bestanden" : "nicht bestanden")")
        let bericht = (["Selbsttest Bereiche iPad (gekoppelt)"] + zeilen).joined(separator: "\n") + "\n"
        try? bericht.write(to: ausgabe.appendingPathComponent("bericht.txt"), atomically: true, encoding: .utf8)
        print(bericht)
    }
}
#endif
