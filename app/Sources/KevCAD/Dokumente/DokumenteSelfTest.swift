import AppKit
import KevCADCore
import PDFKit

/// Selbsttest des Bereichs Dokumente in der Testvariante (`KEVCAD_SELFTEST=dokumente`, Projekt mit Blättern in
/// `KEVCAD_SELFTEST_PROJEKT`): alle Blätter zeigen und die Zeit bis zur ersten Darstellung messen, Bildrate beim Zoomen
/// und Verschieben, Bearbeiten über die echte Leinwand (Maß ziehen, ⌘Z, Wiederholen, Löschen, neues Maß mit drei Klicks,
/// Ansicht ziehen) und über die Aktionen (Notiz mit Zeiger, Schriftfeld, Maßstab), PDF und Druck in eine Datei (1:1).
///
/// Mausereignisse gehen nur an das Fenster der Testvariante (`NSWindow.sendEvent`), der Mauszeiger bleibt, wo er ist.
/// An Prüfpunkten schreibt der Test `<Datenordner>/selftest-dokumente-schritt.txt` (Schritt und Fensternummer) und
/// wartet bis zu `KEVCAD_SELFTEST_PAUSE` Sekunden (Vorgabe 0) auf die Datei `selftest-dokumente-weiter`, damit ein
/// Skript ein Fensterbild aufnehmen kann. Ergebnis im Protokoll und in `<Datenordner>/selftest-dokumente.txt`.
@MainActor
enum DokumenteSelfTest {
    private static var started = false

    static func runIfRequested(_ session: AppSession, state: ProjectWindowState, zustand: DokumenteZustand) {
        guard !started, session.demo == nil, AppInfo.isTestVariant,
              ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "dokumente"
        else { return }
        started = true
        Task { await Lauf(session: session, state: state, zustand: zustand).run() }
    }

    /// Testvariante mit `KEVCAD_SELFTEST=dokumente`: das Projekt aus `KEVCAD_SELFTEST_PROJEKT` öffnen, sobald der Kernel
    /// bereit ist; das Projektfenster startet dann den eigentlichen Test.
    static func projektOeffnenWennVerlangt(_ session: AppSession) {
        guard session.demo == nil, AppInfo.isTestVariant,
              ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "dokumente",
              let p = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_PROJEKT"], !p.isEmpty
        else { return }
        Task { @MainActor in
            let ende = Date().addingTimeInterval(120)
            while Date() < ende, session.model.kernelState != .ready {
                try? await Task.sleep(for: .milliseconds(200))
            }
            if session.model.project == nil {
                session.model.actions?.openProject(at: URL(fileURLWithPath: p, isDirectory: true))
            }
        }
    }

    @MainActor
    private final class Lauf {
        let session: AppSession
        let state: ProjectWindowState
        let zustand: DokumenteZustand
        var model: AppModel { session.model }
        var store: DokumenteStore { session.model.dokumente }
        var zeilen: [String] = []
        var ok = true
        let pause = Double(ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_PAUSE"] ?? "") ?? 0

        init(session: AppSession, state: ProjectWindowState, zustand: DokumenteZustand) {
            self.session = session
            self.state = state
            self.zustand = zustand
        }

        func check(_ b: Bool, _ text: String) {
            ok = ok && b
            let z = "\(b ? "OK    " : "FEHLER") \(text)"
            zeilen.append(z)
            model.append(LogLine(level: b ? .info : .error, text: "Selbsttest Dokumente: \(z)"))
        }

        func info(_ text: String) {
            zeilen.append("      \(text)")
            model.append(LogLine(text: "Selbsttest Dokumente: \(text)"))
        }

        func warte(_ s: Double, _ bedingung: () -> Bool) async -> Bool {
            let ende = Date().addingTimeInterval(s)
            while Date() < ende {
                if bedingung() { return true }
                try? await Task.sleep(for: .milliseconds(50))
            }
            return bedingung()
        }

        var fenster: NSWindow? { session.projectWindow }

        var leinwand: BlattLeinwand? {
            func suche(_ v: NSView) -> BlattLeinwand? {
                if let l = v as? BlattLeinwand { return l }
                for s in v.subviews { if let l = suche(s) { return l } }
                return nil
            }
            return fenster?.contentView.flatMap(suche)
        }

        /// Prüfpunkt für ein Fensterbild (siehe Kopf).
        func pruefpunkt(_ name: String) async {
            try? await Task.sleep(for: .milliseconds(450))
            let dir = AppInfo.supportDirectory
            let weiter = dir.appendingPathComponent("selftest-dokumente-weiter")
            try? FileManager.default.removeItem(at: weiter)
            let text = "\(name) \(fenster?.windowNumber ?? 0)\n"
            try? text.write(to: dir.appendingPathComponent("selftest-dokumente-schritt.txt"), atomically: true,
                            encoding: .utf8)
            guard pause > 0 else { return }
            _ = await warte(pause) { FileManager.default.fileExists(atPath: weiter.path) }
            try? FileManager.default.removeItem(at: weiter)
        }

        // MARK: Ereignisse nur an dieses Fenster

        func fensterPunkt(_ mm: CGPoint) -> CGPoint? {
            guard let l = leinwand else { return nil }
            return l.convert(l.punkt(mm), to: nil)
        }

        func maus(_ typ: NSEvent.EventType, _ mm: CGPoint, klicks: Int = 1, mods: NSEvent.ModifierFlags = []) {
            guard let w = fenster, let p = fensterPunkt(mm),
                  let e = NSEvent.mouseEvent(with: typ, location: p, modifierFlags: mods,
                                             timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: w.windowNumber,
                                             context: nil, eventNumber: 0, clickCount: klicks, pressure: 1)
            else { return }
            w.sendEvent(e)
        }

        /// Die Leinwand bekommt einen neuen Stand erst mit dem nächsten Neuaufbau der Ansicht; bis dahin zeigt sie (und
        /// trifft) den alten. Vor jeder Geste warten, bis sie den Stand des Speichers zeigt, sonst landet ein Klick auf
        /// der alten Lage (so schlug „Hinweis ziehen“ nach dem Rückgängig des Maßstabs fehl: Klick ins Leere, Schwenken).
        func leinwandAktuell() async {
            _ = await warte(5) {
                guard let lz = leinwand?.zeichnung, let sz = store.zeichnung(lz.id) else { return true }
                return lz.stand == sz.stand
            }
        }

        func klick(_ mm: CGPoint, klicks: Int = 1) async {
            await leinwandAktuell()
            maus(.leftMouseDown, mm, klicks: klicks)
            maus(.leftMouseUp, mm, klicks: klicks)
            try? await Task.sleep(for: .milliseconds(60))
        }

        func ziehe(_ von: CGPoint, nach: CGPoint) async {
            await leinwandAktuell()
            maus(.leftMouseDown, von)
            for i in 1...12 {
                let t = CGFloat(i) / 12
                maus(.leftMouseDragged, CGPoint(x: von.x + (nach.x - von.x) * t, y: von.y + (nach.y - von.y) * t))
                try? await Task.sleep(for: .milliseconds(16))
            }
            maus(.leftMouseUp, nach)
        }

        func taste(_ code: UInt16, _ zeichen: String) {
            guard let w = fenster,
                  let e = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [],
                                           timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: w.windowNumber,
                                           context: nil, characters: zeichen, charactersIgnoringModifiers: zeichen,
                                           isARepeat: false, keyCode: code)
            else { return }
            w.sendEvent(e)
        }

        /// ⌘Z und ⇧⌘Z wie aus dem Menü: `undo:` bzw. `redo:` an die Blattansicht als ersten Antwortgeber.
        func rueckgaengig() {
            guard let l = leinwand else { return }
            let punkt = NSMenuItem(title: "", action: #selector(BlattLeinwand.undo(_:)), keyEquivalent: "z")
            let frei = l.validateMenuItem(punkt)
            info("Menü: „\(punkt.title)“\(frei ? "" : " (gesperrt)")")
            NSApp.sendAction(#selector(BlattLeinwand.undo(_:)), to: l, from: punkt)
        }

        func wiederholen() {
            guard let l = leinwand else { return }
            let punkt = NSMenuItem(title: "", action: #selector(BlattLeinwand.redo(_:)), keyEquivalent: "Z")
            let frei = l.validateMenuItem(punkt)
            info("Menü: „\(punkt.title)“\(frei ? "" : " (gesperrt)")")
            NSApp.sendAction(#selector(BlattLeinwand.redo(_:)), to: l, from: punkt)
        }

        /// Wartet auf ein neues Blatt (anderer Stand als `alt`).
        func neuerStand(_ id: String, alt: String, s: Double = 60) async -> Zeichnung? {
            _ = await warte(s) { (store.zeichnung(id)?.stand ?? alt) != alt && store.bearbeitung[id] == nil }
            return store.zeichnung(id)
        }

        // MARK: Ablauf

        func run() async {
            check(await warte(120) { model.kernelState == .ready || model.kernelState == .busy }, "Kernel bereit")
            if let p = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_PROJEKT"], !p.isEmpty {
                if model.project?.path.standardizedFileURL != URL(fileURLWithPath: p, isDirectory: true).standardizedFileURL {
                    model.actions?.openProject(at: URL(fileURLWithPath: p, isDirectory: true))
                }
                check(await warte(400) { model.project != nil && !model.isRunning && model.run != .idle },
                      "Projekt offen, Lauf fertig: \(model.run)")
            }
            state.bereich = .dokumente
            check(await warte(180) { !(store.uebersicht?.blaetter.isEmpty ?? true) },
                  "Übersicht (DOCS): \(store.uebersicht?.blaetter.count ?? 0) Blätter")
            guard let u = store.uebersicht, !u.blaetter.isEmpty else { return fertig() }
            await pruefpunkt("uebersicht")

            // Alle Blätter zeigen: Zeit bis zur ersten Darstellung
            var zeiten: [(String, Double)] = []
            for e in u.zusammenbau + u.baugruppen + u.einzelteile {
                zustand.waehle(.blatt(e.id))
                let da = await warte(90) { BlattMesswerte.shared.ersteDarstellung[e.id] != nil }
                let ms = BlattMesswerte.shared.ersteDarstellung[e.id] ?? -1
                zeiten.append((e.id, ms))
                check(da, "Blatt \(e.id) gezeigt nach \(Int(ms)) ms (\(store.zeichnung(e.id)?.formatText ?? "?"), "
                      + "\(store.zeichnung(e.id)?.masse.count ?? 0) Maße)")
                await pruefpunkt("blatt-\(e.id)")
            }
            if !zeiten.isEmpty {
                let ms = zeiten.map(\.1).filter { $0 >= 0 }
                info("Erste Darstellung: Mittel \(Int(ms.reduce(0, +) / Double(max(ms.count, 1)))) ms, "
                     + "höchstens \(Int(ms.max() ?? 0)) ms")
            }

            // Bildrate beim Zoomen und Verschieben (Zusammenbau, sonst erstes Blatt)
            if let gross = (u.zusammenbau.first ?? u.einzelteile.first)?.id {
                zustand.waehle(.blatt(gross))
                _ = await warte(30) { self.leinwand?.zeichnung?.id == gross }
                try? await Task.sleep(for: .milliseconds(600))
                await messeZoom(gross)
            }

            // Bearbeiten auf einem Einzelteil mit linearen Maßen
            if let teil = u.einzelteile.first(where: { e in
                store.zeichnung(e.id)?.blatt.masse.contains { $0.art == "linear" && $0.versatz != nil && $0.quelle == "auto" }
                    ?? false
            }) {
                await bearbeiten(teil.id)
            } else {
                check(false, "kein Einzelteil mit linearem automatischem Maß")
            }

            await erzeugen()
            await pdfUndDruck()
            fertig()
        }

        func messeZoom(_ id: String) async {
            guard let l = leinwand else { return check(false, "Leinwand nicht gefunden") }
            for (name, schritt) in [("Zoomen", 0), ("Verschieben", 1)] as [(String, Int)] {
                BlattMesswerte.shared.zuruecksetzen()
                let t0 = CACurrentMediaTime()
                var i = 0
                while CACurrentMediaTime() - t0 < 2.5 {
                    let mitte = CGPoint(x: l.bounds.midX + 80, y: l.bounds.midY + 40)
                    if schritt == 0 {
                        // wie eine Pinch-Geste: hinein und wieder heraus
                        l.interagiere()
                        l.zoom(faktor: (i / 60) % 2 == 0 ? 1.025 : 1 / 1.025, um: mitte)
                    } else {
                        l.interagiere()
                        l.zoom(faktor: 1, um: mitte)  // Lage bleibt, Zwischenbild bleibt gültig
                        l.scrollWheel(with: Self.scroll(dx: (i / 60) % 2 == 0 ? 6 : -6, dy: 3))
                    }
                    i += 1
                    try? await Task.sleep(for: .milliseconds(8))
                }
                l.needsDisplay = true
                try? await Task.sleep(for: .milliseconds(300))
                let a = BlattMesswerte.shared.auswertung(seit: t0)
                let ausBild = BlattMesswerte.shared.bilder.filter { $0.zeit >= t0 && $0.zwischenspeicher }.count
                info(String(format: "%@ (%@): %.0f Bilder/s, Zeichnen im Mittel %.1f ms, höchstens %.1f ms, %d Bilder (%d aus dem Zwischenbild)",
                            name, id, a.fps, a.mittelMs, a.maxMs, a.anzahl, ausBild))
                check(a.fps >= 50, "\(name) flüssig (mindestens 50 Bilder/s)")
            }
            // Ehrlicher Gegenwert: das ganze Blatt in Fenstergröße als Bitmap gerechnet (CPU, ohne Zwischenbild)
            if let z = l.zeichnung {
                let backing = fenster?.backingScaleFactor ?? 2
                var ms: [Double] = []
                for _ in 0..<5 {
                    let t = CACurrentMediaTime()
                    _ = BlattLeinwand.raster(z, pxJeMM: l.skala * backing)
                    ms.append((CACurrentMediaTime() - t) * 1000)
                }
                let px = Int(z.groesse.width * l.skala * backing)
                info(String(format: "Ganzes Blatt %@ als Bitmap %d px breit: %.1f ms im Mittel, %.1f ms bestes",
                            id, px, ms.reduce(0, +) / Double(ms.count), ms.min() ?? 0))
            }
            l.einpassen(animiert: false)
        }

        static func scroll(dx: Int32, dy: Int32) -> NSEvent {
            let cg = CGEvent(scrollWheelEvent2Source: nil, units: .pixel, wheelCount: 2, wheel1: dy, wheel2: dx, wheel3: 0)!
            cg.setIntegerValueField(.scrollWheelEventIsContinuous, value: 1)
            return NSEvent(cgEvent: cg)!
        }

        func bearbeiten(_ id: String) async {
            zustand.waehle(.blatt(id))
            _ = await warte(60) { self.leinwand?.zeichnung?.id == id }
            try? await Task.sleep(for: .milliseconds(500))
            guard var z = store.zeichnung(id), let l = leinwand else { return check(false, "Blatt \(id) nicht gezeigt") }
            info("Bearbeiten auf \(id)")

            // 1. Maß ziehen (Maßlinie um 8 mm vom Körper weg)
            guard let b = z.blatt.masse.first(where: { $0.art == "linear" && $0.versatz != nil && $0.quelle == "auto" }),
                  let m = z.mass(b.id), let linie = m.linien.max(by: { MassVorschau.laenge($0) < MassVorschau.laenge($1) }),
                  linie.count >= 2
            else { return check(false, "kein ziehbares Maß") }
            let auf = CGPoint(x: (linie[0].x * 0.3 + linie[1].x * 0.7), y: (linie[0].y * 0.3 + linie[1].y * 0.7))
            let n = MassVorschau.normale(m, blatt: b)
            let richtung: CGFloat = (b.versatz ?? 0) >= 0 ? 1 : -1
            let ziel = CGPoint(x: auf.x + n.dx * 8 * richtung, y: auf.y + n.dy * 8 * richtung)
            let alt = b.versatz ?? 0
            var stand = z.stand
            await ziehe(auf, nach: ziel)
            check(l.element == .mass(b.id), "Maß \(b.id) (\(m.text)) ausgewählt")
            z = await neuerStand(id, alt: stand) ?? z
            let neu = z.blatt.mass(b.id)?.versatz ?? alt
            check(abs(abs(neu - alt) - 8) < 0.6, "Maß \(m.text) gezogen: Versatz \(alt) → \(neu)")
            await pruefpunkt("mass-gezogen")

            // 2. ⌘Z und Wiederholen
            stand = z.stand
            rueckgaengig()
            z = await neuerStand(id, alt: stand) ?? z
            check(abs((z.blatt.mass(b.id)?.versatz ?? 999) - alt) < 0.05,
                  "Rückgängig: Versatz wieder \(z.blatt.mass(b.id)?.versatz ?? .nan)")
            check(z.blatt.mass(b.id)?.fest == false, "Rückgängig: Maß wieder automatisch platziert")
            stand = z.stand
            wiederholen()
            z = await neuerStand(id, alt: stand) ?? z
            check(abs((z.blatt.mass(b.id)?.versatz ?? 999) - neu) < 0.05, "Wiederholen: Versatz wieder \(neu)")

            // 3. Löschen mit ⌫ (automatisches Maß wird unterdrückt), dann rückgängig
            let unterdrueckt = z.blatt.unterdrueckt.count
            let anzahl = z.masse.count
            zustand.element = .mass(b.id)
            try? await Task.sleep(for: .milliseconds(100))
            fenster?.makeFirstResponder(l)
            stand = z.stand
            taste(51, "\u{7f}")
            z = await neuerStand(id, alt: stand) ?? z
            check(z.masse.count == anzahl - 1 && z.blatt.unterdrueckt.count == unterdrueckt + 1,
                  "Löschen: \(anzahl) → \(z.masse.count) Maße, unterdrückt \(z.blatt.unterdrueckt.count)")
            stand = z.stand
            rueckgaengig()
            z = await neuerStand(id, alt: stand) ?? z
            check(z.masse.count == anzahl && z.blatt.unterdrueckt.count == unterdrueckt,
                  "Rückgängig: Maß wieder da (\(z.masse.count) Maße)")

            // 4. Neues Maß mit drei Klicks: zwei senkrechte Kanten der ersten Ansicht, Maßlinie darüber
            if let v = z.ansichten.first, let kanten = senkrechteKanten(v) {
                zustand.setzeWerkzeug(.mass)
                try? await Task.sleep(for: .milliseconds(150))
                let anzahl = z.masse.count
                stand = z.stand
                await klick(kanten.0)
                await klick(kanten.1)
                maus(.mouseMoved, CGPoint(x: (kanten.0.x + kanten.1.x) / 2, y: v.rahmen.maxY + 14))
                try? await Task.sleep(for: .milliseconds(200))
                await pruefpunkt("mass-vorschau")
                await klick(CGPoint(x: (kanten.0.x + kanten.1.x) / 2, y: v.rahmen.maxY + 14))
                z = await neuerStand(id, alt: stand) ?? z
                let eigen = z.masse.filter { $0.quelle == "kevin" }
                check(z.masse.count == anzahl + 1 && !eigen.isEmpty,
                      "Neues Maß: \(eigen.map(\.text).joined(separator: ", ")) (von Kevin)")
                zustand.setzeWerkzeug(.auswahl)
                await pruefpunkt("mass-neu")
            } else {
                check(false, "keine zwei senkrechten Kanten in der ersten Ansicht")
            }

            // 5. Ansicht ziehen (10 mm nach rechts), danach rückgängig
            if let v = z.ansichten.first {
                let lage = z.blatt.ansicht(v.id)?.lage ?? CGPoint(x: v.rahmen.midX, y: v.rahmen.midY)
                // Punkt in der Ansicht, aber nicht auf einem Maß
                let p = CGPoint(x: v.rahmen.minX + v.rahmen.width * 0.37, y: v.rahmen.minY + v.rahmen.height * 0.41)
                zustand.element = nil
                stand = z.stand
                await ziehe(p, nach: CGPoint(x: p.x + 10, y: p.y))
                z = await neuerStand(id, alt: stand) ?? z
                let neu = z.blatt.ansicht(v.id)?.lage ?? lage
                check(abs(neu.x - lage.x - 10) < 0.6, "Ansicht \(v.id) gezogen: x \(lage.x) → \(neu.x)")
                stand = z.stand
                rueckgaengig()
                z = await neuerStand(id, alt: stand) ?? z
                check(abs((z.blatt.ansicht(v.id)?.lage?.x ?? 0) - lage.x) < 0.6, "Rückgängig: Ansicht zurück")
            }

            // 6. Notiz mit Zeiger, Schriftfeld, Maßstab über die Aktionen (wie Inspektor und Sprechblase)
            if let v = z.ansichten.first, let kante = senkrechteKanten(v)?.0 {
                stand = z.stand
                zustand.bearbeiter.ausfuehren(
                    [.notiz(text: "Kanten entgraten", lage: CGPoint(x: v.rahmen.maxX + 12, y: v.rahmen.maxY + 6),
                            zeiger: ZeichnungsKlick(ansicht: v.id, punkt: kante))], blatt: id)
                z = await neuerStand(id, alt: stand) ?? z
                check(z.blatt.notizen.contains { $0.text == "Kanten entgraten" }, "Notiz mit Zeiger angelegt")
            }
            stand = z.stand
            zustand.bearbeiter.ausfuehren([.schriftfeld(feld: "freigegeben", wert: "Kevin Schwed")], blatt: id)
            z = await neuerStand(id, alt: stand) ?? z
            check(z.texte.contains { $0.text == "Kevin Schwed" && $0.art == "schriftfeld" }
                    && z.blatt.schriftfeldText("freigegeben") == "Kevin Schwed", "Schriftfeld „Freigegeben“ gesetzt")
            let massstab = z.blatt.massstab
            let anderer = massstab == "1:2" ? "1:1" : "1:2"
            stand = z.stand
            zustand.bearbeiter.ausfuehren([.massstab(anderer)], blatt: id)
            z = await neuerStand(id, alt: stand) ?? z
            check(z.blatt.massstab == anderer, "Maßstab \(massstab) → \(z.blatt.massstab)")
            await pruefpunkt("bearbeitet")
            stand = z.stand
            rueckgaengig()
            z = await neuerStand(id, alt: stand) ?? z
            check(z.blatt.massstab == massstab, "Rückgängig: Maßstab wieder \(z.blatt.massstab)")

            // 7. Maßzahl eines Hinweises ziehen (Bohrung, Fase …): Knick und Text wandern, die Spitze bleibt
            if let h = z.masse.first(where: { $0.istHinweis && !$0.text.isEmpty }) {
                zustand.element = nil
                stand = z.stand
                // vom Ziel weg ziehen, damit die Bezugslinie auf ihrer Seite bleibt
                let sx: CGFloat = (h.linien.first.map { $0.count >= 2 && $0[1].x < $0[0].x } ?? false) ? -1 : 1
                let von = CGPoint(x: h.textLage.x, y: h.textLage.y + 1.2)
                await ziehe(von, nach: CGPoint(x: von.x + 12 * sx, y: von.y + 6))
                z = await neuerStand(id, alt: stand) ?? z
                let neu = z.mass(h.id)?.textLage ?? h.textLage
                let gezogen = hypot(neu.x - h.textLage.x - 12 * sx, neu.y - h.textLage.y - 6) < 1.5
                check(gezogen,
                      "Hinweis \(h.text) gezogen: Text (\(Int(h.textLage.x)), \(Int(h.textLage.y))) → (\(Int(neu.x)), \(Int(neu.y)))")
                if !gezogen {  // Fehlersuche: was die Leinwand aus den Ereignissen gemacht hat
                    for zeile in (leinwand?.gestenProtokoll ?? []).suffix(6) { info("Leinwand: \(zeile)") }
                }
                stand = z.stand
                rueckgaengig()
                z = await neuerStand(id, alt: stand) ?? z
                let zurueck = z.mass(h.id)?.textLage ?? .zero
                check(hypot(zurueck.x - h.textLage.x, zurueck.y - h.textLage.y) < 1.5, "Rückgängig: Hinweis wieder an seiner Stelle")
            }

            // 8. Ansicht über das Werkzeug hinzufügen (Klick auf eine freie Stelle), dann rückgängig
            if let frei = freieStelle(z) {
                let anzahl = z.ansichten.count
                zustand.setzeWerkzeug(.ansicht("rechts"))
                try? await Task.sleep(for: .milliseconds(150))
                stand = z.stand
                await klick(frei)
                z = await neuerStand(id, alt: stand) ?? z
                check(z.ansichten.count == anzahl + 1, "Ansicht hinzugefügt: \(anzahl) → \(z.ansichten.count) Ansichten")
                await pruefpunkt("ansicht-neu")
                stand = z.stand
                rueckgaengig()
                z = await neuerStand(id, alt: stand) ?? z
                check(z.ansichten.count == anzahl, "Rückgängig: Ansicht wieder entfernt")
            }

            // 8b. Schnitt (Linie ziehen) und Einzelheit (Kreis aufziehen) über die echte Leinwand, dann rückgängig
            if let v = z.ansichten.first(where: { ["vorn", "oben", "links", "rechts", "hinten", "unten"].contains($0.art) }) {
                let anzahl = z.ansichten.count
                zustand.setzeWerkzeug(.schnitt)
                try? await Task.sleep(for: .milliseconds(150))
                stand = z.stand
                let y = v.rahmen.midY + v.rahmen.height * 0.07
                await ziehe(CGPoint(x: v.rahmen.minX - 6, y: y), nach: CGPoint(x: v.rahmen.maxX + 6, y: y + 0.4))
                z = await neuerStand(id, alt: stand) ?? z
                let schnitt = z.ansichten.first { $0.art == "schnitt" }
                check(z.ansichten.count == anzahl + 1 && schnitt != nil,
                      "Schnitt gezogen: \(anzahl) → \(z.ansichten.count) Ansichten"
                      + (schnitt.map { ", Schraffur \($0.linien["schraffur"]?.count ?? 0)" } ?? ""))
                check(zustand.werkzeug == .auswahl, "nach dem Schnitt wieder Auswählen")
                await pruefpunkt("schnitt-neu")
                // Einzelheit: Kreis um eine Ecke der Ausgangsansicht (der Schnitt kann Format und Lage geändert haben)
                zustand.setzeWerkzeug(.einzelheit)
                try? await Task.sleep(for: .milliseconds(150))
                stand = z.stand
                let w = z.gruppe(v.id) ?? v
                let c = CGPoint(x: w.rahmen.minX + w.rahmen.width * 0.2, y: w.rahmen.minY + w.rahmen.height * 0.3)
                await ziehe(c, nach: CGPoint(x: c.x + 7, y: c.y))
                z = await neuerStand(id, alt: stand) ?? z
                let einzel = z.ansichten.first { $0.art == "einzelheit" }
                check(einzel != nil, "Einzelheit aufgezogen: \(z.ansichten.count) Ansichten")
                await pruefpunkt("einzelheit-neu")
                for _ in 0..<2 {
                    stand = z.stand
                    rueckgaengig()
                    z = await neuerStand(id, alt: stand) ?? z
                }
                check(z.ansichten.count == anzahl, "Rückgängig: Schnitt und Einzelheit wieder entfernt")
            }

            // 9. Notiz-Werkzeug: Klick öffnet die Sprechblase für den Text
            if let frei = freieStelle(z) {
                zustand.setzeWerkzeug(.notiz)
                try? await Task.sleep(for: .milliseconds(150))
                await klick(frei)
                try? await Task.sleep(for: .milliseconds(400))
                check(leinwand?.eingabeOffen ?? false, "Notiz-Werkzeug öffnet die Sprechblase")
                await pruefpunkt("notiz-eingabe")
                leinwand?.schliesseEingabe()
                zustand.setzeWerkzeug(.auswahl)
            }

            // 10. Sprechblase für ein Feld des Schriftfelds (Doppelklick auf „Benennung“)
            if let label = z.texte.first(where: { $0.art == "schriftfeld_label" && $0.text == "Benennung" }) {
                let p = CGPoint(x: label.lage.x + 20, y: label.lage.y - 5)
                await klick(p, klicks: 1)
                maus(.leftMouseDown, p, klicks: 2)
                maus(.leftMouseUp, p, klicks: 2)
                try? await Task.sleep(for: .milliseconds(500))
                let offen = leinwand?.eingabeOffen ?? false
                check(offen, "Doppelklick auf das Schriftfeld öffnet die Sprechblase")
                await pruefpunkt("sprechblase")
                leinwand?.schliesseEingabe()
            }
        }

        /// Freie Stelle auf dem Blatt (nicht in einer Ansicht, keinem Maß, nicht im Schriftfeld), für neue Ansichten und
        /// Notizen.
        func freieStelle(_ z: Zeichnung) -> CGPoint? {
            let belegt = z.ansichten.map { $0.rahmen.insetBy(dx: -15, dy: -15) } + z.grafik.masse.map(\.huelle)
                + z.grafik.texte.map(\.rahmen)
            for y in stride(from: z.groesse.height * 0.75, to: 40, by: -10) {
                for x in stride(from: z.groesse.width * 0.6, to: z.groesse.width - 30, by: 10) {
                    let p = CGPoint(x: x, y: y)
                    if !belegt.contains(where: { $0.insetBy(dx: -4, dy: -4).contains(p) }) { return p }
                }
            }
            return nil
        }

        /// Zwei senkrechte sichtbare Kanten mit verschiedenem x (Mitte je Kante), Abstand mindestens 8 mm. Gesucht wird in
        /// allen Strecken der Polylinien (der Kernel fasst Kanten zu Zügen zusammen).
        func senkrechteKanten(_ v: ZeichnungsGruppe) -> (CGPoint, CGPoint)? {
            var senkrecht: [CGPoint] = []
            for pl in v.linien["sichtbar"] ?? [] {
                for (a, b) in zip(pl, pl.dropFirst()) where abs(a.x - b.x) < 0.02 && abs(a.y - b.y) > 6 {
                    senkrecht.append(CGPoint(x: a.x, y: (a.y + b.y) / 2))
                }
            }
            senkrecht.sort { $0.x < $1.x }
            guard let a = senkrecht.first, let b = senkrecht.last(where: { $0.x - a.x >= 8 }) else { return nil }
            return (a, b)
        }

        /// DRAWING_CREATE wie „Zeichnung anlegen“ im Teilebaum: Blatt für die Baugruppe der obersten Ebene.
        func erzeugen() async {
            guard let gruppe = model.parts.first(where: { $0.path.count >= 2 })?.path.first else { return }
            let vorher = store.uebersicht?.blaetter.count ?? 0
            zustand.wunschTeile = [gruppe]
            model.dokumenteActions?.zeichnungenErzeugen(teile: [gruppe], art: "baugruppe", format: nil)
            let neu = await warte(180) { (store.uebersicht?.blaetter.count ?? 0) > vorher }
            check(neu, "Zeichnung anlegen (DRAWING_CREATE, Baugruppe „\(gruppe)“): \(vorher) → "
                  + "\(store.uebersicht?.blaetter.count ?? 0) Blätter")
            if neu {
                _ = await warte(60) { self.zustand.blattID.flatMap { self.store.uebersicht?.blatt($0)?.inhaltArt } == "baugruppe" }
                check(zustand.blattID.flatMap { store.uebersicht?.blatt($0)?.inhaltArt } == "baugruppe",
                      "Neues Blatt der Baugruppe gewählt: \(zustand.blattID ?? "–")")
                _ = await warte(60) { self.leinwand?.zeichnung?.id == self.zustand.blattID }
                await pruefpunkt("baugruppe")
            }
        }

        func pdfUndDruck() async {
            let ids = store.uebersicht?.blaetter.map(\.id) ?? []
            let zs = await BlattAusgabe.sicherstellen(ids, model: model)
            let pdf = BlattPDF.daten(zs, metadaten: .init(titel: "Selbsttest"))
            let url = AppInfo.supportDirectory.appendingPathComponent("selftest-dokumente.pdf")
            try? pdf.write(to: url)
            let doc = PDFDocument(data: pdf)
            check(doc?.pageCount == zs.count, "PDF: \(doc?.pageCount ?? 0) Seiten, \(pdf.count / 1024) KB → \(url.path)")
            let formate = Set(zs.map(\.formatText)).sorted()
            info("Formate im PDF: " + formate.joined(separator: ", "))

            // Druck in eine Datei: Seite muss so groß bleiben wie das Blatt (nicht skaliert)
            for a in BlattDruck.auftraege(zs) {
                let ziel = AppInfo.supportDirectory.appendingPathComponent("selftest-druck-\(a.format.replacingOccurrences(of: " ", with: "-")).pdf")
                try? FileManager.default.removeItem(at: ziel)
                let pi = BlattDruck.druckInfo(a)
                pi.jobDisposition = .save
                pi.dictionary()[NSPrintInfo.AttributeKey.jobSavingURL.rawValue] = ziel
                guard let op = BlattDruck.operation(a, titel: "Selbsttest \(a.format)", info: pi) else {
                    check(false, "Druckoperation \(a.format)")
                    continue
                }
                op.showsPrintPanel = false
                op.showsProgressPanel = false
                let lief = op.run()
                let gedruckt = PDFDocument(url: ziel)
                let seite = gedruckt?.page(at: 0)?.bounds(for: .mediaBox).size ?? .zero
                let soll = a.zeichnungen[0].seitengroessePunkte
                let passt = abs(max(seite.width, seite.height) - max(soll.width, soll.height)) < 1
                    && abs(min(seite.width, seite.height) - min(soll.width, soll.height)) < 1
                check(lief && passt, "Druck \(a.format) (\(a.zeichnungen.count) Blätter): Seite "
                      + "\(Int(seite.width)) × \(Int(seite.height)) pt, Blatt \(Int(soll.width)) × \(Int(soll.height)) pt")
            }
        }

        func fertig() {
            zeilen.append(ok ? "ERGEBNIS: bestanden" : "ERGEBNIS: FEHLER")
            let text = zeilen.joined(separator: "\n") + "\n"
            try? text.write(to: AppInfo.supportDirectory.appendingPathComponent("selftest-dokumente.txt"), atomically: true,
                            encoding: .utf8)
            model.append(LogLine(level: ok ? .info : .error, text: "Selbsttest Dokumente: " + (ok ? "bestanden" : "FEHLER")))
        }
    }
}
