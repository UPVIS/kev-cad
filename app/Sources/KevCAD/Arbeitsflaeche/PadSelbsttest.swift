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
        guard !started, env["KEVCAD_SELFTEST"] == "pad" else { return }
        started = true
        Task { await run(session) }
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
}
#endif
