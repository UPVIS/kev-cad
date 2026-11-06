import AppKit
import Foundation
import OCCTSwiftViewport
import QuartzCore
import simd

// Selbsttest des Sprach-Feedbacks (V2-6) in der Testvariante, ohne Mikrofon und ohne simulierte Eingaben:
// KEVCAD_SELFTEST=sprache, Ton aus KEVCAD_SPRACHE_TONDATEI. Das Skript KEVCAD_SPRACHE_SKRIPT nennt Schritte mit Zeiten ab
// Beginn der Sitzung; Zeigen und Strich laufen über dieselben Wege wie die Maus (echter Treffertest der GPU). Am Ende steht
// alles in KEVCAD_SELFTEST_AUSGABE/selftest-sprache.json; kernel/tools/feedback_selbsttest.py wartet als Agent mit.

/// Ein Schritt des Skripts.
struct SprachSkriptSchritt: Codable {
    /// Sekunden ab Beginn der Sitzung
    var t: Double
    /// `zeigen`, `strich`, `anhalten`, `weiter`, `drehen`, `fertig`
    var art: String
    /// Nummer des Ziels (zeigen, strich)
    var ziel: Int?
    /// Sekunden (drehen)
    var dauer: Double?
}

/// Ergebnis für den Treiber.
struct SprachSelbsttestBericht: Codable {
    var ok = true
    var pruefungen: [String] = []
    var ziele: [String] = []
    var fertigUnix: Double = 0
    var paketUnix: Double = 0
    var paket: String?
    var datei: String?
    var worte = 0
    var wortLatenzMs: [Double] = []
    var drehen: String?
    var drehenOhneSitzung: String?

    enum CodingKeys: String, CodingKey {
        case ok, pruefungen, ziele, paket, datei, worte, drehen
        case drehenOhneSitzung = "drehen_ohne_sitzung"
        case fertigUnix = "fertig_unix"
        case paketUnix = "paket_unix"
        case wortLatenzMs = "wort_latenz_ms"
    }
}

extension AppController {
    static var sprachSelbsttestGewuenscht: Bool {
        AppInfo.isTestVariant && ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "sprache"
    }

    /// Nach dem ersten fertigen Lauf.
    func sprachSelbsttestPlanen() {
        guard Self.sprachSelbsttestGewuenscht, !viewerSelbsttestLaeuft, !model.parts.isEmpty else { return }
        viewerSelbsttestLaeuft = true
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(2))
            await self?.sprachSelbsttest()
        }
    }

    private func sprachPause(_ s: Double) async { try? await Task.sleep(for: .milliseconds(Int(s * 1000))) }

    /// Mitte des Teils in der Ansicht, wenn dort wirklich dieses Teil zu treffen ist (Eingabeebene, unten links).
    private func trifft(_ name: String) async -> CGPoint? {
        guard let welt = scene.worldAnchor(of: .part(name)), let p = viewport.bildpunkt(welt),
            let ansicht = viewport.eingabeView,
            p.x > 8, p.y > 8, p.x < viewport.viewSize.width - 8, p.y < viewport.viewSize.height - 8
        else { return nil }
        let treffer: PickResult? = await withCheckedContinuation { k in
            viewport.pickPoint(p, in: ansicht) { k.resume(returning: $0) }
        }
        guard let treffer, scene.resolve(treffer)?.part == name else { return nil }
        return p
    }

    private func sprachZiele() async -> [(name: String, punkt: CGPoint)] {
        var ziele: [(String, CGPoint)] = []
        // Große Teile zuerst: Dort liegen Maus und Strich sicher auf dem Teil
        let geordnet = scene.order.filter { !$0.hasPrefix("Kulisse/") && scene.isVisible($0) }.sorted {
            (scene.worldBounds(of: .part($0))?.diagonalLength ?? 0) > (scene.worldBounds(of: .part($1))?.diagonalLength ?? 0)
        }
        for name in geordnet {
            if let p = await trifft(name) { ziele.append((name, p)) }
            if ziele.count == 3 { break }
        }
        return ziele
    }

    func sprachSelbsttest() async {
        let env = ProcessInfo.processInfo.environment
        var bericht = SprachSelbsttestBericht()
        func pruefe(_ ok: Bool, _ text: String) {
            bericht.ok = bericht.ok && ok
            bericht.pruefungen.append("\(ok ? "OK" : "FEHLER") \(text)")
            log(ok ? .info : .error, "Selbsttest Sprache: \(ok ? "OK" : "FEHLER") \(text)")
        }
        let ausgabe = env["KEVCAD_SELFTEST_AUSGABE"].map { URL(fileURLWithPath: $0, isDirectory: true) }
            ?? AppInfo.supportDirectory.appendingPathComponent("selftest-sprache", isDirectory: true)
        try? FileManager.default.createDirectory(at: ausgabe, withIntermediateDirectories: true)

        _ = await kernelRuhe()
        let teile = scene.order.filter { !$0.hasPrefix("Kulisse/") && scene.isVisible($0) }
        focus(on: teile.isEmpty ? scene.order : teile)
        orbitStep(yaw: 25, pitch: -10)
        await sprachPause(1.0)
        let ziele = await sprachZiele()
        bericht.ziele = ziele.map(\.name)
        pruefe(ziele.count >= 2, "\(ziele.count) Ziele getroffen: \(ziele.map(\.name).joined(separator: ", "))")

        var schritte: [SprachSkriptSchritt] = [
            .init(t: 0.3, art: "zeigen", ziel: 0), .init(t: 2.5, art: "zeigen", ziel: 1),
            .init(t: 3.0, art: "strich", ziel: 1), .init(t: 8.0, art: "fertig"),
        ]
        if let pfad = env["KEVCAD_SPRACHE_SKRIPT"], let daten = FileManager.default.contents(atPath: pfad),
            let eigene = try? JSONDecoder().decode([SprachSkriptSchritt].self, from: daten)
        {
            schritte = eigene
        }

        // Wörter: Wann erscheint jedes als Text?
        var zwischen: [(text: String, zeit: Double)] = []
        var fertigPaket: (URL, FeedbackPaket)?
        sprache.beiZwischenstand = { zwischen.append(($0, $1)) }
        sprache.beiPaket = { fertigPaket = ($0, $1) }

        // Vergleich für das Drehen während des Sprechens
        bericht.drehenOhneSitzung = await drehungMessen(sekunden: 2)
        await sprachPause(0.3)

        // Hauptlauf
        oberflaeche(.sprechen(true))
        let uhrNull = sprache.sitzung?.uhrNull ?? 0
        pruefe(sprache.spricht && model.oberflaeche.spricht && viewport.zeichnen, "V: Sitzung läuft, Ziehen zeichnet")
        let start = CACurrentMediaTime()
        for s in schritte {
            let warten = s.t - (CACurrentMediaTime() - start)
            if warten > 0 { await sprachPause(warten) }
            switch s.art {
            case "zeigen":
                if let i = s.ziel, i < ziele.count { viewport.eingabeView?.testMaus(ziele[i].punkt) }
            case "strich":
                if let i = s.ziel, i < ziele.count { await strichUeber(ziele[i].punkt) }
            case "anhalten":
                oberflaeche(.sprechen(false))
                pruefe(!sprache.spricht && sprache.offen && !model.oberflaeche.spricht && model.oberflaeche.sitzungOffen,
                       "V: angehalten, Sitzung offen")
            case "weiter":
                oberflaeche(.sprechen(true))
                pruefe(sprache.spricht, "V: es geht weiter")
            case "drehen":
                bericht.drehen = await drehungMessen(sekunden: s.dauer ?? 2)
            case "fertig":
                bericht.fertigUnix = Date().timeIntervalSince1970
                oberflaeche(.sprechenFertig)
            default:
                pruefe(false, "unbekannter Schritt \(s.art)")
            }
        }
        let frist = CACurrentMediaTime() + 5
        while fertigPaket == nil, CACurrentMediaTime() < frist { await sprachPause(0.005) }
        bericht.paketUnix = Date().timeIntervalSince1970
        pruefe(fertigPaket != nil, "↩: Paket geschrieben")
        pruefe(!model.oberflaeche.sitzungOffen && !sprache.offen && !viewport.zeichnen, "↩: Sitzung zu")
        if let (datei, paket) = fertigPaket {
            bericht.paket = paket.name
            bericht.datei = datei.path
            bericht.worte = paket.worte.count
            bericht.wortLatenzMs = Self.wortLatenz(paket, null: uhrNull, zwischen: zwischen)
            pruefe(paket.worte.count > 5, "\(paket.worte.count) Wörter, \(paket.saetze.count) Sätze")
            pruefe(paket.saetze.contains { $0.bezuege.contains { $0.art == "zeiger" && $0.wort != nil } }, "Zeigewort getroffen")
            pruefe(paket.striche.contains { !$0.teile.isEmpty }, "Strich liegt auf einem Teil")
        }

        // esc: nichts bleibt
        let vorher = (try? FileManager.default.contentsOfDirectory(atPath: FeedbackAblage.ordner(
            projekt: model.project?.path ?? ausgabe).path)) ?? []
        oberflaeche(.sprechen(true))
        await sprachPause(0.5)
        if let z = ziele.first {
            viewport.eingabeView?.testMaus(z.punkt)
            await strichUeber(z.punkt)
        }
        await sprachPause(0.4)
        ausfuehren(.abbrechen)
        await sprachPause(0.3)
        let nachher = (try? FileManager.default.contentsOfDirectory(atPath: FeedbackAblage.ordner(
            projekt: model.project?.path ?? ausgabe).path)) ?? []
        pruefe(!sprache.offen && !model.oberflaeche.sitzungOffen, "esc: Sitzung zu")
        pruefe(vorher.sorted() == nachher.sorted(), "esc: nichts geschrieben")

        sprache.beiZwischenstand = nil
        sprache.beiPaket = nil
        if let daten = try? JSONEncoder().encode(bericht) {
            try? daten.write(to: ausgabe.appendingPathComponent("selftest-sprache.json"), options: .atomic)
        }
        log(.info, "Selbsttest Sprache: \(bericht.ok ? "bestanden" : "FEHLGESCHLAGEN")")
    }

    /// Ein Strich quer über den Punkt, in Schritten wie eine ruhige Hand (rund 60 Punkte je Sekunde).
    private func strichUeber(_ mitte: CGPoint) async {
        guard let ansicht = viewport.eingabeView else { return }
        var punkte: [CGPoint] = []
        for i in 0...40 {
            let a = Double(i) / 40
            punkte.append(CGPoint(x: mitte.x - 30 + 60 * a, y: mitte.y + 8 * sin(a * 6)))
        }
        ansicht.testStrichBeginnen(punkte[0])
        for p in punkte.dropFirst() {
            await sprachPause(0.016)
            ansicht.testStrichZiehen(p)
        }
        ansicht.testStrichBeenden(punkte[punkte.count - 1])
        await sprachPause(0.05)
    }

    /// Je Wort: Zeit vom Ende des Worts im Ton, bis es als Text da war (ms). Maßstab ist die Zahl der Wörter im Zwischenstand.
    static func wortLatenz(_ paket: FeedbackPaket, null: Double, zwischen: [(text: String, zeit: Double)]) -> [Double] {
        var aus: [Double] = []
        for satz in paket.saetze {
            let worte = paket.worte.filter { $0.satz == satz.nr }
            for (i, w) in worte.enumerated() {
                let wortEnde = null + w.bis
                // Nur Zwischenstände dieses Satzes: Sie beginnen nach dem Ende des vorigen Satzes
                let treffer = zwischen.first {
                    $0.zeit >= null + satz.von && $0.text.split(separator: " ").count >= i + 1
                }
                if let treffer { aus.append(((treffer.zeit - wortEnde) * 1000).rounded()) }
            }
        }
        return aus
    }
}
