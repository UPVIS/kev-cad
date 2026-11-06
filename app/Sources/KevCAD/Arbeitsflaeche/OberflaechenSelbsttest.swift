import AppKit
import Darwin
import KevCADCore
import QuartzCore
import SwiftUI

/// Selbsttest der neuen Oberfläche (V2-3) in der Testvariante (`KEVCAD_SELFTEST=oberflaeche`), ohne Maus- und
/// Tastatureingaben: alles über `OberflaechenActions`, wie es später Sprache und Agent auslösen.
///
/// Misst die Zeit vom Prozessstart bis zum bedienbaren Fenster und bis zum leeren Projekt, die längste Pause des
/// Hauptfadens beim Umschalten der Leisten und Kacheln, beim Öffnen von Kacheln und beim Schieben an den Rand. Fotografiert
/// jeden Zustand (mit `KEVCAD_SELFTEST_FOTO_AUSSEN=1` von außen per `screencapture -l`, Auftrag in
/// `foto-auftrag.txt`). `KEVCAD_SELFTEST_PROJEKT` öffnet danach ein Projekt mit Teilen. Ergebnis in
/// `selftest-oberflaeche.txt` unter `KEVCAD_SELFTEST_AUSGABE`; `KEVCAD_SELFTEST_QUIT=1` beendet die App danach.
@MainActor
enum OberflaechenSelbsttest {
    private static var started = false
    /// Zeitpunkte relativ zum Prozessstart (Sekunden).
    static var erschienen: Double?
    static var bedienbar: Double?
    /// Läuft vom ersten Bild an: Wann war der Hauptfaden zuletzt länger blockiert?
    private static let startMesser = HaengerMesser()

    private static var env: [String: String] { ProcessInfo.processInfo.environment }
    private static var gewuenscht: Bool { AppInfo.isTestVariant && env["KEVCAD_SELFTEST"] == "oberflaeche" }

    static var ausgabe: URL {
        if let p = env["KEVCAD_SELFTEST_AUSGABE"], !p.isEmpty { return URL(fileURLWithPath: p, isDirectory: true) }
        return AppInfo.supportDirectory.appendingPathComponent("selftest-oberflaeche", isDirectory: true)
    }

    /// Sekunden seit dem Start dieses Prozesses (Startzeit aus dem Kernel, nicht aus der App).
    nonisolated static func seitStart() -> Double {
        var info = kinfo_proc()
        var groesse = MemoryLayout<kinfo_proc>.stride
        var mib: [Int32] = [CTL_KERN, KERN_PROC, KERN_PROC_PID, getpid()]
        guard sysctl(&mib, 4, &info, &groesse, nil, 0) == 0 else { return -1 }
        let s = info.kp_proc.p_un.__p_starttime
        let start = Double(s.tv_sec) + Double(s.tv_usec) / 1_000_000
        return Date().timeIntervalSince1970 - start
    }

    /// Hauptfenster erschienen: Zeit festhalten, nach dem ersten Bild noch einmal (bedienbar).
    static func fensterErschienen() {
        guard erschienen == nil else { return }
        erschienen = seitStart()
        Startzeiten.marke("Fenster erschienen")
        if gewuenscht { startMesser.start() }
        DispatchQueue.main.async { DispatchQueue.main.async { bedienbar = seitStart() } }
    }

    static func runIfRequested(_ session: AppSession) {
        guard !started, gewuenscht else { return }
        started = true
        Task { await run(session) }
    }

    private static func run(_ session: AppSession) async {
        let model = session.model
        let o = model.oberflaeche
        var zeilen: [String] = []
        var ok = true
        try? FileManager.default.createDirectory(at: ausgabe, withIntermediateDirectories: true)
        try? FileManager.default.removeItem(at: ausgabe.appendingPathComponent("foto-auftrag.txt"))
        func pruefe(_ b: Bool, _ text: String) {
            ok = ok && b
            let z = "\(b ? "OK    " : "FEHLER") \(text)"
            zeilen.append(z)
            model.append(LogLine(level: b ? .info : .error, text: "Selbsttest Oberfläche: \(z)"))
        }
        func notiere(_ text: String) {
            zeilen.append("       \(text)")
            model.append(LogLine(text: "Selbsttest Oberfläche: \(text)"))
        }
        func warte(_ s: Double, _ bedingung: () -> Bool) async -> Bool {
            let ende = Date().addingTimeInterval(s)
            while Date() < ende {
                if bedingung() { return true }
                try? await Task.sleep(for: .milliseconds(50))
            }
            return bedingung()
        }
        func pause(_ s: Double) async { try? await Task.sleep(for: .milliseconds(Int(s * 1000))) }
        func foto(_ name: String) async {
            await pause(0.45)
            guard let w = session.projectWindow else { return }
            if env["KEVCAD_SELFTEST_FOTO_AUSSEN"] == "1" {
                let auftrag = ausgabe.appendingPathComponent("foto-auftrag.txt")
                let zeile = "\(w.windowNumber) \(name)\n"
                if let h = try? FileHandle(forWritingTo: auftrag) {
                    h.seekToEndOfFile()
                    h.write(Data(zeile.utf8))
                    try? h.close()
                } else {
                    try? zeile.write(to: auftrag, atomically: true, encoding: .utf8)
                }
                let ziel = ausgabe.appendingPathComponent(name + ".png")
                _ = await warte(10) { FileManager.default.fileExists(atPath: ziel.path) }
                return
            }
            guard let v = w.contentView, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) else { return }
            v.cacheDisplay(in: v.bounds, to: rep)
            if let d = rep.representation(using: .png, properties: [:]) {
                try? d.write(to: ausgabe.appendingPathComponent(name + ".png"))
            }
        }
        /// Längste Pause des Hauptfadens (ms), während `aktion` läuft und `dauer` Sekunden danach.
        func haenger(_ dauer: Double, _ aktion: () -> Void) async -> Double {
            let messer = HaengerMesser()
            messer.start()
            aktion()
            await pause(dauer)
            return messer.stop()
        }
        let a = model.oberflaechenActions
        // Leisten und Kacheln sind gemerkt: jeder Lauf beginnt gleich
        a?.ordneKacheln([.modell])
        a?.setzeLeisteLinks(true)
        a?.setzeLeisteRechts(false)

        // 1. Start
        _ = await warte(10) { erschienen != nil && bedienbar != nil }
        if let e = erschienen, let b = bedienbar {
            // Die Wanduhr hängt an der Last anderer Prozesse, die Rechenzeit des Hauptfadens nicht
            let rechenzeit = Startzeiten.marken.first { $0.0 == "Fenster erschienen" }?.2 ?? 0
            notiere(String(format: "Fenster erschienen nach %.2f s, bedienbar nach %.2f s", e, b))
            pruefe(rechenzeit < 1.2, String(format: "Rechenzeit des Hauptfadens bis zum Fenster %.2f s", rechenzeit))
        }
        await pause(3)
        let pause0 = startMesser.stop()
        notiere(String(format: "längste Pause im Start nach dem ersten Bild: %.0f ms, frei seit %.2f s", pause0,
                       seitStart() - startMesser.seitLetzterLangerPause))
        notiere(Startzeiten.marken.map { String(format: "%@ %.2f s (Rechenzeit %.2f s)", $0.0, $0.1, $0.2) }
            .joined(separator: " · "))
        notiere("Menüleiste: " + (NSApp.mainMenu?.items.map(\.title).joined(separator: " | ") ?? "keine"))
        if session.demo == nil {
            let bereit = await warte(60) { model.kernelState == .ready || model.kernelState == .busy }
            notiere(String(format: "Kernel bereit nach %.2f s", seitStart()))
            pruefe(bereit, "Kernel meldet sich")
            let entwurf = await warte(20) { session.istEntwurf && model.project != nil }
            pruefe(entwurf, String(format: "leeres Projekt (Entwurf) offen nach %.2f s: %@", seitStart(),
                                   model.project?.path.path ?? "keins"))
            if let p = model.project?.path {
                let gemerkt = await warte(3) { EntwurfAblage.standard.hatMarke(p) }
                pruefe(gemerkt, "Entwurf ist gemerkt (.kevcad/entwurf.json)")
                pruefe(!p.path.contains("/Documents/"), "Entwurf liegt nicht in ~/Documents")
            }
        }
        await foto("01-start")

        // 2. Übersicht wegschieben, Viewer leer
        a?.zeigeUebersicht(false)
        pruefe(!o.uebersicht, "Startübersicht weggeschoben")
        await foto("02-fokus-leer")

        // 3. Projekt mit Teilen
        if let pfad = env["KEVCAD_SELFTEST_PROJEKT"], !pfad.isEmpty {
            let alt = model.project?.path
            session.openProject(at: URL(fileURLWithPath: pfad, isDirectory: true))
            let offen = await warte(60) { model.project?.path.lastPathComponent == URL(fileURLWithPath: pfad).lastPathComponent }
            pruefe(offen, "Projekt geöffnet: \(URL(fileURLWithPath: pfad).lastPathComponent)")
            if model.parts.isEmpty { model.actions?.runModel() }
            let teile = await warte(240) { !model.parts.isEmpty && !model.isRunning }
            pruefe(teile, "Teile da: \(model.parts.count)")
            if let alt, EntwurfAblage.standard.enthaelt(alt) {
                let weg = await warte(5) { !FileManager.default.fileExists(atPath: alt.path) }
                pruefe(weg, "leerer Entwurf nach dem Wechsel weggeräumt")
            }
        }
        await foto("03-fokus")

        /// Wer bekommt Klicks mitten im Viewer? Eine Ebene der Oberfläche darf sie nicht schlucken.
        func treffer() -> String {
            guard let w = session.projectWindow, let f = w.contentView?.superview else { return "kein Fenster" }
            let r = session.viewerRahmen
            let t = f.hitTest(NSPoint(x: r.midX, y: f.bounds.height - r.midY))
            return t.map { String(describing: type(of: $0)) } ?? "nichts"
        }
        notiere("Klick im Viewer (allein): \(treffer())")

        // 4. Rechte Leiste (Eigenschaften)
        var ms = await haenger(0.8) { a?.setzeLeisteRechts(true) }
        pruefe(o.leisteRechts, "Eigenschaften rechts an")
        notiere(String(format: "Rechte Leiste zum ersten Mal aufbauen: längste Pause %.0f ms", ms))
        if let erst = model.parts.first { model.actions?.select([erst.id]) }
        notiere("Klick im Viewer (mit rechter Leiste): \(treffer())")
        await foto("04-leiste-rechts")

        // 5. Kacheln
        ms = await haenger(1.0) { a?.zeigeKachel(.zeichnung) }
        notiere(String(format: "Kachel Zeichnung öffnen: längste Pause %.0f ms", ms))
        ms = await haenger(1.0) { a?.zeigeKachel(.stueckliste) }
        notiere(String(format: "Kachel Stückliste öffnen: längste Pause %.0f ms", ms))
        await pause(0.5)
        pruefe(o.kacheln == [.modell, .zeichnung, .stueckliste], "drei Kacheln: \(o.kacheln.map(\.rawValue))")
        pruefe(o.nummer(.stueckliste) == 3, "Stückliste ist Kachel 3")
        await foto("05-kacheln-3")
        a?.zeigeKachel(.ansicht)
        await pause(1.0)
        pruefe(o.kacheln.count == 4, "vier Kacheln")
        await foto("06-kacheln-4")
        a?.vergroessereKachel(.zeichnung)
        pruefe(o.gross == .zeichnung, "Kachel 2 groß")
        await foto("07-gross")
        a?.vergroessereKachel(nil)
        a?.schliesseKachel(.ansicht)
        pruefe(o.kacheln.count == 3 && o.gross == nil, "Kachel geschlossen, wieder eingeordnet")
        ms = await haenger(1.5) { a?.vergroessereKachel(.material) }
        notiere(String(format: "Kachel Material groß: längste Pause %.0f ms", ms))
        await foto("07b-material")
        a?.schliesseKachel(.material)
        await pause(0.5)
        // Beim ersten Aufbau kostet SwiftUI die Typen von Table und Form; das zweite Mal zeigt die laufenden Kosten
        a?.schliesseKachel(.stueckliste)
        await pause(0.5)
        ms = await haenger(1.0) { a?.zeigeKachel(.stueckliste) }
        notiere(String(format: "Kachel Stückliste zum zweiten Mal: längste Pause %.0f ms", ms))
        ms = await haenger(1.5) { a?.vergroessereKachel(.material) }
        notiere(String(format: "Kachel Material zum zweiten Mal: längste Pause %.0f ms", ms))
        a?.schliesseKachel(.material)
        await pause(0.5)

        // 6. Nur das Modell und zurück, Sprechen
        ms = await haenger(0.8) { a?.vergroessereKachel(.modell) }
        pruefe(!o.kachelflaeche, "nur das Modell, Kacheln eingeklappt")
        pruefe(ms < 250, String(format: "Umschalten Kacheln → nur das Modell: längste Pause %.0f ms", ms))
        ms = await haenger(0.8) { a?.vergroessereKachel(nil) }
        pruefe(o.kachelflaeche, "Kacheln wieder nebeneinander")
        pruefe(ms < 250, String(format: "Umschalten nur das Modell → Kacheln: längste Pause %.0f ms", ms))
        a?.vergroessereKachel(.modell)
        a?.setzeLeisteRechts(false)
        await pause(0.5)
        a?.setzeSprechen(true)
        a?.oberflaeche(.sprechText("Den Griff hätte ich gern höher, so ungefähr bis hier, wo der Strich ist."))
        pruefe(o.spricht, "Sprechen an (roter Rahmen)")
        await foto("08-sprechen")
        a?.setzeSprechen(false)
        a?.sprechenVerwerfen()  // die Sitzung bleibt sonst offen
        pruefe(o.zuletztGesagt?.hasPrefix("Den Griff") == true, "Gesagtes bleibt für die Statuszeile")

        // 7. An den Rand und zurück
        let vorher = session.projectWindow?.frame
        ms = await haenger(0.33) { a?.setzeRand(.rechts) }
        let einpassen = await haenger(0.7) {}
        notiere(String(format: "nach dem Rand, Modell einpassen: längste Pause %.0f ms", einpassen))
        let schmal = session.projectWindow?.frame
        pruefe(abs((schmal?.width ?? 0) - GA.schmal) < 2, String(format: "am rechten Rand, %.0f pt breit", schmal?.width ?? 0))
        pruefe(ms < 250, String(format: "an den Rand: längste Pause %.0f ms", ms))
        await foto("09-rand")
        ms = await haenger(1.0) { a?.setzeRand(nil) }
        let zurueck = session.projectWindow?.frame
        pruefe(zurueck == vorher, "zurück vom Rand: Größe und Lage wie vorher")
        pruefe(ms < 250, String(format: "zurück vom Rand: längste Pause %.0f ms", ms))
        await foto("10-zurueck")

        // 8. Übersicht wieder zeigen
        a?.zeigeUebersicht(true)
        await foto("11-uebersicht")
        a?.zeigeUebersicht(false)

        zeilen.append(ok ? "ERGEBNIS: bestanden" : "ERGEBNIS: FEHLER")
        try? zeilen.joined(separator: "\n").appending("\n")
            .write(to: ausgabe.appendingPathComponent("selftest-oberflaeche.txt"), atomically: true, encoding: .utf8)
        if env["KEVCAD_SELFTEST_QUIT"] == "1" {
            await pause(0.5)
            NSApp.terminate(nil)
        }
    }
}

/// Zeitmarken des Starts (Sekunden seit Prozessstart), nur für den Selbsttest.
enum Startzeiten {
    nonisolated(unsafe) static var marken: [(String, Double, Double)] = []

    /// Wanduhr seit Prozessstart und Rechenzeit des Hauptfadens: Ihr Abstand zeigt, wie sehr fremde Last bremst.
    static func marke(_ name: String) {
        let rechenzeit = Double(clock_gettime_nsec_np(CLOCK_THREAD_CPUTIME_ID)) / 1_000_000_000
        marken.append((name, OberflaechenSelbsttest.seitStart(), rechenzeit))
    }
}
