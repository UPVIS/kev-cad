import AppKit
import KevCADCore
import simd

/// Selbsttest „Simulation“ in der Testvariante (`KEVCAD_SELFTEST=simulation`): spielt die Bedienung des Bereichs ohne
/// echte Maus durch. Lastfall anlegen, Kraft per Klick auf eine Fläche (Treffer wie aus dem Pick-Puffer), Betrag in kg,
/// Richtung frei über den Pfeil-Griff, Lager per Klick, Rechnen, Ergebnistabelle mit Filter, Grenze suchen,
/// Festigkeit (FEM), Vergleich vorher und nachher, dynamischer Lastfall, Topologie mit einer Schutzfläche per Klick.
/// Fensterbilder mit `KEVCAD_SELFTEST_FOTO_AUSSEN=1` von außen (`screencapture -l`, Auftrag in `foto-auftrag.txt`),
/// sonst über `cacheDisplay`. `KEVCAD_SELFTEST_PROJEKT` öffnet ein Projekt, Ausgabe in `KEVCAD_SELFTEST_AUSGABE`,
/// Ergebnis in `selftest-simulation.txt`, `KEVCAD_SELFTEST_QUIT=1` beendet die App danach.
@MainActor
enum SimulationSelfTest {
    private static var started = false
    private static var gewuenscht: Bool {
        AppInfo.isTestVariant && ProcessInfo.processInfo.environment["KEVCAD_SELFTEST"] == "simulation"
    }

    static func projektOeffnen(_ session: AppSession) {
        guard gewuenscht, session.demo == nil,
              let p = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_PROJEKT"], !p.isEmpty
        else { return }
        Task { @MainActor in
            let ende = Date().addingTimeInterval(240)
            while Date() < ende, session.model.kernelState != .ready {
                try? await Task.sleep(for: .milliseconds(200))
            }
            if session.model.project == nil {
                session.model.actions?.openProject(at: URL(fileURLWithPath: p, isDirectory: true))
            }
        }
    }

    static func runIfRequested(_ session: AppSession, state: ProjectWindowState) {
        guard !started, session.demo == nil, gewuenscht else { return }
        started = true
        Task { await run(session, state) }
    }

    static var ausgabe: URL {
        if let p = ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_AUSGABE"], !p.isEmpty {
            return URL(fileURLWithPath: p, isDirectory: true)
        }
        return AppInfo.supportDirectory.appendingPathComponent("selftest-simulation", isDirectory: true)
    }

    // swiftlint:disable:next function_body_length
    private static func run(_ session: AppSession, _ state: ProjectWindowState) async {
        let model = session.model
        let st = model.simulation
        let zustand = state.simulationZustand
        let env = ProcessInfo.processInfo.environment
        var lines: [String] = []
        var passed = true
        let aktivitaet = ProcessInfo.processInfo.beginActivity(options: [.userInitiated, .latencyCritical],
                                                               reason: "Selbsttest Simulation")
        defer { ProcessInfo.processInfo.endActivity(aktivitaet) }
        try? FileManager.default.createDirectory(at: ausgabe, withIntermediateDirectories: true)
        try? FileManager.default.removeItem(at: ausgabe.appendingPathComponent("foto-auftrag.txt"))
        func check(_ ok: Bool, _ text: String) {
            passed = passed && ok
            let line = "\(ok ? "OK    " : "FEHLER") \(text)"
            lines.append(line)
            model.append(LogLine(level: ok ? .info : .error, text: "Selbsttest Simulation: \(line)"))
        }
        func wait(_ seconds: Double, _ condition: () -> Bool) async -> Bool {
            let end = Date().addingTimeInterval(seconds)
            while Date() < end {
                if condition() { return true }
                try? await Task.sleep(for: .milliseconds(100))
            }
            return condition()
        }
        func pause(_ s: Double) async { try? await Task.sleep(for: .milliseconds(Int(s * 1000))) }
        func foto(_ name: String) async {
            let w = session.projectWindow
            if env["KEVCAD_SELFTEST_FOTO_AUSSEN"] == "1", let w {
                let auftrag = ausgabe.appendingPathComponent("foto-auftrag.txt")
                let zeile = "\(w.windowNumber) \(name)\n"
                if let h = try? FileHandle(forWritingTo: auftrag) {
                    h.seekToEndOfFile()
                    h.write(zeile.data(using: .utf8)!)
                    try? h.close()
                } else {
                    try? zeile.write(to: auftrag, atomically: true, encoding: .utf8)
                }
                let ziel = ausgabe.appendingPathComponent(name + ".png")
                _ = await wait(8) { FileManager.default.fileExists(atPath: ziel.path) }
                return
            }
            guard let v = w?.contentView, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) else { return }
            v.cacheDisplay(in: v.bounds, to: rep)
            if let d = rep.representation(using: .png, properties: [:]) {
                try? d.write(to: ausgabe.appendingPathComponent(name + ".png"))
            }
        }
        func aendern(_ ops: [JSONValue]) async -> Bool {
            var ergebnis: Bool?
            model.simulationActions?.simulationAendern(ops) { ok, _ in ergebnis = ok }
            _ = await wait(90) { ergebnis != nil }
            return ergebnis ?? false
        }
        // Aufträge zählen hoch: gewartet wird auf einen neueren als den zuletzt fertigen (sonst gälte der vorige
        // Auftrag gleicher Art schon als fertig)
        var gesehen = st.job?.auftrag ?? 0
        func jobFertig(_ was: String, _ s: Double) async -> SimJob? {
            let alt = gesehen
            _ = await wait(10) { (st.job?.auftrag ?? 0) > alt && st.job?.was == was }
            _ = await wait(s) { (st.job?.auftrag ?? 0) > alt && st.job?.was == was && st.job?.laeuft == false }
            guard let j = st.job, j.auftrag > alt, j.was == was, !j.laeuft else { return nil }
            gesehen = j.auftrag
            return j
        }

        guard let controller = session.controller, let actions = model.simulationActions else {
            check(false, "App-Kern ohne Simulation")
            fertig(lines, passed)
            return
        }
        check(await wait(240) { model.kernelState == .ready }, "Kernel bereit")
        check(await wait(300) { model.project != nil && !model.isRunning && model.statik.ergebnis != nil },
              "Projekt offen, Statik gerechnet")
        let teil = "Halter"
        check(await wait(30) { controller.scene.record(teil) != nil }, "Teil \(teil) im Viewer")
        await pause(1)

        // 1. Bereich Simulation (⌘4)
        state.zeige(.simulation)
        check(await wait(10) { st.aktiv && st.stand != nil }, "Bereich Simulation vorne, SIM da")
        let modellNamen = st.stand?.modell.map(\.name) ?? []
        check(modellNamen.contains("Bolzen 50 N"), "Szenario aus model.py gekennzeichnet: \(modellNamen.joined(separator: ", "))")
        await foto("01-bereich")

        // 2. Lastfall anlegen
        let name = "Selbsttest Aufstützen"
        if st.stand?.lastfall(name) != nil { _ = await aendern([SimOp.loeschen(name)]) }
        check(await aendern([SimOp.lastfallNeu(name)]), "Lastfall „\(name)“ angelegt (SIM_EDIT)")
        check(await wait(20) { st.stand?.lastfall(name) != nil }, "Lastfall in SIM")
        actions.waehleLastfall(name)
        // Fensterleiste: der Untertitel folgt der Auswahl sofort (Punkt 10)
        let soll = "Simulation · \(name)"
        check(await wait(1) { session.projectWindow?.subtitle == soll },
              "Untertitel folgt sofort: „\(session.projectWindow?.subtitle ?? "–")“")
        zustand.reiter = .kraefte

        // 3. Kraft per Klick auf die Oberseite des Stegs (Normale +z), 2 kg
        guard let rec = controller.scene.record(teil),
              let oben = rec.header.faces.indices.filter({ rec.header.faces[$0].n?[2] ?? 0 > 0.99 })
                  .max(by: { (rec.header.faces[$0].c?[2] ?? 0) < (rec.header.faces[$1].c?[2] ?? 0) }),
              let unten = rec.header.faces.indices.first(where: { rec.header.faces[$0].n?[2] ?? 0 < -0.99 })
        else {
            check(false, "Flächen des Halters nicht gefunden")
            fertig(lines, passed)
            return
        }
        actions.setSimulationWerkzeug(.kraft)
        check(controller.simulationKlickAufFlaeche(teil: teil, flaeche: oben), "Klick auf Fläche \(oben) (Oberseite)")
        check(st.entwurf?.last.ort.flaeche == oben && (st.entwurf?.last.ort.normale?.z ?? 0) > 0.99,
              "Entwurf: Fläche \(oben), Normale +z aus dem Treffer")
        if var e = st.entwurf {
            e.last.richtung = SimRichtung(art: .normale)
            e.last.betrag = 2
            e.last.einheit = "kg"
            actions.setKraftEntwurf(e)
        }
        let f = st.entwurf?.kraft ?? .zero
        check(abs(f.z + 19.62) < 0.01 && abs(f.x) < 1e-3, "Vorschau: 2 kg in die Fläche = \(simKraftText(f))")
        await pause(0.8)
        await foto("02-kraft-entwurf")
        actions.kraftEntwurfSpeichern()
        check(await wait(30) { st.lastfall?.lasten.count == 1 && st.lastfall?.lasten.first?.zustand == .ok },
              "Kraft gespeichert und zugeordnet (simulation.json)")
        let l1 = st.lastfall?.lasten.first
        check(abs((l1?.kraftWirksam?.z ?? 0) + 19.62) < 0.05, "Kraft wirksam im Kernel: \(l1.flatMap(\.kraftWirksam).map(simKraftText) ?? "–")")
        check(await wait(20) { model.statik.ergebnis?.szenario(name)?.lasten.first?.id == l1?.id },
              "STATICS: Lastfall der App mit der Kraft gerechnet")

        // 4. Richtung frei: Pfeil-Griff ziehen
        if let id = l1?.id { actions.lastBearbeiten(id) }
        if var e = st.entwurf {
            e.last.richtung = SimRichtung(art: .frei, azimut: 90, hoehe: -60)
            actions.setKraftEntwurf(e)
        }
        await pause(0.5)
        if let g = controller.simGriffPunkt(), let p = controller.viewport.bildpunkt(g) {
            check(controller.simulationGriffBeginnt(p), "Griff am Pfeilende getroffen")
            controller.simulationGriffZiehen(CGPoint(x: p.x + 40, y: p.y + 10))
            controller.viewport.onGriffEnde?(p)
            let r = st.entwurf?.last.richtung
            check(r?.art == .frei && (r?.azimut ?? 90) != 90, "Griff gezogen: Azimut \(KevFormat.number(r?.azimut ?? 0, digits: 0))°, Höhe \(KevFormat.number(r?.hoehe ?? 0, digits: 0))°")
        } else {
            check(false, "Griff nicht im Bild")
        }
        await pause(0.5)
        await foto("03-kraft-griff")
        actions.kraftEntwurfSpeichern()
        check(await wait(30) { st.lastfall?.lasten.first?.richtung.art == .frei && st.entwurf == nil },
              "Kraft mit freier Richtung gespeichert")

        // 5. Lager per Klick: fest auf der Unterseite
        zustand.reiter = .lager
        st.lagerArt = .fest
        st.lagerAuf = .flaeche
        actions.setSimulationWerkzeug(.lager)
        check(controller.simulationKlickAufFlaeche(teil: teil, flaeche: unten), "Klick auf die Unterseite (Lager)")
        check(st.lagerEntwurf?.ort.flaeche == unten, "Lagerentwurf auf Fläche \(unten)")
        await pause(0.5)
        await foto("04-lager-entwurf")
        actions.lagerEntwurfSpeichern()
        check(await wait(30) { st.stand?.lager.contains { $0.teil == teil && $0.zustand == .ok } == true },
              "Lager gespeichert und zugeordnet")
        check(st.stand?.abgeleitet.contains { $0.id == "boden:\(teil)" && !$0.aktiv } ?? true,
              "Abgeleitetes Bodenlager vom ausdrücklichen ersetzt")
        actions.setSimulationWerkzeug(.keins)

        // 6. Rechnen (S0, S1) und Tabelle
        zustand.reiter = .rechnen
        actions.simulationRechnen(was: "rechnen", lastfall: nil, teil: nil, fein: false, grenze: nil)
        let j1 = await jobFertig("rechnen", 60)
        check(j1?.stand == "done", "Rechnen fertig: \(j1?.text ?? "–")")
        guard let sz = model.statik.ergebnis?.szenario(name) else {
            check(false, "Szenario fehlt in STATICS")
            fertig(lines, passed)
            return
        }
        let zeilen = SimErgebnis.zeilen(sz)
        check(zeilen.contains { $0.teil == teil }, "Tabelle: \(zeilen.count) Zeilen, \(teil) mit Sicherheit "
              + (zeilen.first { $0.teil == teil }?.sicherheit.map(StatikZahl.sf) ?? "–"))
        st.filter = .rot
        let rot = SimErgebnis.gefiltert(zeilen, .rot)
        check(rot.allSatisfy { $0.ampel == .rot }, "Filter „nur rot“: \(rot.count) Zeilen")
        st.filter = .alle
        actions.zeigeErgebnisTeil(teil)
        check(await wait(5) { model.selectedPartIDs == [teil] } && model.statik.farbverlauf,
              "Klick in der Tabelle: Teil gewählt, Farbverlauf an")
        await pause(1)
        await foto("05-ergebnisse")

        // 7. Grenze suchen: wie viel Last
        zustand.grenzeArt = "last"
        actions.simulationRechnen(was: "grenze", lastfall: name, teil: nil, fein: false, grenze: "last")
        let j2 = await jobFertig("grenze", 120)
        check(j2?.stand == "done" && !(j2?.werte.isEmpty ?? true), "Grenze: \(j2?.ergebnisText ?? j2?.meldung ?? "–")")
        await pause(0.5)
        await foto("06-grenze")

        // 8. Festigkeit (FEM) mit Fortschritt
        actions.simulationRechnen(was: "festigkeit", lastfall: name, teil: nil, fein: false, grenze: nil)
        let j3 = await jobFertig("festigkeit", 240)
        check(j3?.stand == "done", "Festigkeit (FEM): \(j3?.text ?? j3?.meldung ?? "–")")
        _ = await wait(10) { model.statik.ergebnis?.szenario(name)?.festkoerper?.teile.contains { $0.stand == "done" } == true }
        let fem = model.statik.ergebnis?.szenario(name).map(SimErgebnis.zeilen)?.first { $0.teil == teil }
        check(fem?.nachweis == .fem, "Tabelle: \(teil) mit Nachweis \(fem?.nachweis.rawValue ?? "–"), Sicherheit "
              + (fem?.sicherheit.map(StatikZahl.sf) ?? "–"))
        await pause(1.5)
        await foto("07-festigkeit")

        // 9. Vergleich vorher/nachher: Last verdoppeln
        if let l = st.lastfall?.lasten.first {
            var neu = l
            neu.betrag = 4
            _ = await aendern([SimOp.lastSetzen(name, neu)])
        }
        check(await wait(30) { st.vorher[name] != nil }, "Vorheriger Stand gemerkt")
        st.vergleich = SimulationStore.vorherSchluessel
        if let a = st.vorher[name], let b = model.statik.ergebnis?.szenario(name) {
            let v = SimErgebnis.vergleich(a, b)
            let h = v.first { $0.name == teil }
            check((h?.aenderung ?? 0) < 0, "Vergleich: \(teil) Sicherheit \(h?.a.map(StatikZahl.sf) ?? "–") → "
                  + "\(h?.b.map(StatikZahl.sf) ?? "–")")
            // nur gleiche Verfahren (vorher FEM, jetzt ohne FEM: verglichen wird S0 mit S0, nie FEM mit S0)
            let nachweisVorher = SimErgebnis.zeilen(a).first { $0.teil == teil }?.nachweis.rawValue ?? "–"
            let nachweisJetzt = SimErgebnis.zeilen(b).first { $0.teil == teil }?.nachweis.rawValue ?? "–"
            check(h?.verfahren != nil || h?.hinweis != nil,
                  "Vergleich nur gleicher Verfahren: \(h?.verfahrenText ?? "–") (vorher \(nachweisVorher), "
                  + "jetzt \(nachweisJetzt))")
            check(nachweisVorher == nachweisJetzt || h?.verfahren != "FEM" || h?.hinweis != nil,
                  "FEM nicht mit S0 gemischt")
        }
        await pause(1)
        await foto("08-vergleich")
        st.vergleich = nil

        // 10. Dynamischer Lastfall (Fahrt) im Editor
        let fahrt = "Selbsttest Fahrt"
        if st.stand?.lastfall(fahrt) != nil { _ = await aendern([SimOp.loeschen(fahrt)]) }
        check(await aendern([SimOp.lastfallNeu(fahrt, dynamisch: true)]), "Dynamischer Lastfall angelegt")
        _ = await wait(20) { st.stand?.lastfall(fahrt) != nil }
        actions.waehleLastfall(fahrt)
        zustand.reiter = .lastfall
        check(st.lastfall?.dynamisch == true && st.lastfall?.fahrt?.bremsen == .abrupt,
              "Fahrt: 1 m/s, abrupt bremsen")
        await pause(1)
        await foto("09-lastfall-dynamisch")

        // 11. Kopie eines Szenarios aus model.py
        check(await aendern([SimOp.kopieren(von: "Bolzen 50 N", name: "Bolzen 50 N (App)")]),
              "„Bolzen 50 N“ als Kopie bearbeitet")
        check(await wait(20) { st.stand?.lastfall("Bolzen 50 N (App)")?.lasten.count == 1 }, "Kopie mit der Kraft aus model.py")

        // 12. Topologie mit einer Schutzfläche per Klick
        actions.waehleLastfall(name)
        zustand.reiter = .topologie
        actions.waehleTopologieTeil(teil)
        model.topologie.szenario = name
        model.topologie.behalten = 0.45
        actions.setSimulationWerkzeug(.schutz)
        controller.simulationKlickAufFlaeche(teil: teil, flaeche: oben)
        check(st.schutzFlaechen == [oben], "Schutzfläche \(oben) per Klick")
        actions.setSimulationWerkzeug(.keins)
        check(await wait(20) { st.stand?.topologie[teil]?.schutz.map(\.index) == [oben] },
              "Schutzfläche in simulation.json")
        await pause(0.5)
        actions.starteSimulationsTopologie(teil: teil)
        check(await wait(60) { model.topologie.stand?.teil == teil && model.topologie.stand?.laeuft == true },
              "Topologie läuft")
        _ = await wait(90) { model.topologie.feld(.dichte) != nil }
        await pause(1)
        await foto("10-topologie-dichte")
        check(await wait(300) { model.topologie.stand?.laeuft == false }, "Topologie fertig: \(model.topologie.stand?.text ?? "–")")
        let ts = model.topologie.stand
        check(ts?.fertig == true, "Ergebnis: Volumen −\(KevFormat.number(ts?.ersparnisProzent ?? 0, digits: 0)) %, "
              + "Schutzzonen: \(ts?.zonen.map(\.art).joined(separator: ", ") ?? "–")")
        check(ts?.zonen.contains { $0.art == "Schutzfläche \(oben)" } == true,
              "Eigene Schutzfläche unter den Schutzzonen")
        await pause(2)
        await foto("11-topologie-nachher")

        // 13. Offene Grenzen (simulation2): Lager je Lastfall, gleitend entlang einer Kante, gelenkig in der FEM,
        // Last auf der ganzen Fläche als Druck, Grenze mit FEM, Pfeil-Griff frei im Raum, Pfeile bildschirmfest
        await simulation2(session, state, controller: controller, teil: teil, name: name, oben: oben, unten: unten,
                          check: check, wait: wait, foto: foto, aendern: aendern, jobFertig: jobFertig)

        // 14. Zurück im 3D-Bereich: Kräfte und Lager verschwinden aus dem Viewer
        state.zeige(.modell)
        check(await wait(5) { !st.aktiv && controller.scene.simulationBodies.isEmpty }, "3D-Bereich ohne Simulationskörper")
        fertig(lines, passed)
    }

    private static func fertig(_ lines: [String], _ passed: Bool) {
        let summary = passed ? "Selbsttest Simulation bestanden" : "Selbsttest Simulation FEHLGESCHLAGEN"
        let text = ([summary] + lines).joined(separator: "\n") + "\n"
        try? text.write(to: AppInfo.supportDirectory.appendingPathComponent("selftest-simulation.txt"), atomically: true,
                        encoding: .utf8)
        try? text.write(to: ausgabe.appendingPathComponent("selftest-simulation.txt"), atomically: true, encoding: .utf8)
        if ProcessInfo.processInfo.environment["KEVCAD_SELFTEST_QUIT"] == "1" {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { NSApp.terminate(nil) }
        }
    }
}

// MARK: - Offene Grenzen (simulation2)

extension SimulationSelfTest {
    /// Schritte der zweiten Ausbaustufe: Lager je Lastfall, gleitend entlang einer Kante, gelenkiges Lager im
    /// Bolzenloch mit Festigkeit (FEM), Last auf der ganzen Fläche als Druck, Grenze mit FEM, Pfeil-Griff (Kugel, Ring,
    /// Einrasten), Pfeile bildschirmfest, Untertitel. Läuft in einem eigenen Lastfall „Selbsttest Gelenk“.
    // swiftlint:disable:next function_body_length function_parameter_count cyclomatic_complexity
    static func simulation2(_ session: AppSession, _ state: ProjectWindowState, controller: AppController,
                            teil: String, name: String, oben: Int, unten: Int,
                            check: (Bool, String) -> Void,
                            wait: (Double, () -> Bool) async -> Bool,
                            foto: (String) async -> Void,
                            aendern: ([JSONValue]) async -> Bool,
                            jobFertig: (String, Double) async -> SimJob?) async {
        let model = session.model
        let st = model.simulation
        let zustand = state.simulationZustand
        guard let actions = model.simulationActions, let rec = controller.scene.record(teil) else {
            check(false, "simulation2: App-Kern oder Teil fehlt")
            return
        }
        func pause(_ s: Double) async { try? await Task.sleep(for: .milliseconds(Int(s * 1000))) }
        let gelenk = "Selbsttest Gelenk"
        if st.stand?.lastfall(gelenk) != nil { _ = await aendern([SimOp.loeschen(gelenk)]) }
        check(await aendern([SimOp.lastfallNeu(gelenk)]), "Lastfall „\(gelenk)“ angelegt")
        _ = await wait(20) { st.stand?.lastfall(gelenk) != nil }
        actions.waehleLastfall(gelenk)
        check(await wait(1) { session.projectWindow?.subtitle == "Simulation · \(gelenk)" },
              "Untertitel folgt dem Lastfallwechsel sofort: „\(session.projectWindow?.subtitle ?? "–")“")

        // a) Lager je Lastfall: das feste Lager auf der Unterseite gilt nur noch in „name“
        if var a1 = st.stand?.lager.first(where: { $0.teil == teil && $0.art == .fest }) {
            a1.szenarien = [name]
            check(await aendern([SimOp.lagerSetzen(a1)]), "Lager \(a1.id) nur in „\(name)“ (lager_setzen)")
            check(await wait(20) { st.stand?.lager.first { $0.id == a1.id }?.szenarien == [name] },
                  "SIM: \(a1.id) gilt \(st.stand?.lager.first { $0.id == a1.id }?.giltText ?? "–")")
            check(await wait(20) {
                (model.statik.ergebnis?.szenario(name)?.lagerIDs ?? []).contains(a1.id)
                    && !(model.statik.ergebnis?.szenario(gelenk)?.lagerIDs ?? [a1.id]).contains(a1.id)
            }, "STATICS: \(a1.id) in „\(name)“ \(model.statik.ergebnis?.szenario(name)?.lagerIDs ?? []), nicht in "
                + "„\(gelenk)“ \(model.statik.ergebnis?.szenario(gelenk)?.lagerIDs ?? [])")
        } else {
            check(false, "festes Lager aus Schritt 5 fehlt")
        }

        // b) Kraft 2 kg auf die Oberseite, c) Druck auf der ganzen Oberseite
        zustand.reiter = .kraefte
        actions.setSimulationWerkzeug(.kraft)
        actions.setKraftEntwurf(nil)
        check(controller.simulationKlickAufFlaeche(teil: teil, flaeche: oben), "Klick auf die Oberseite (Kraft)")
        if var e = st.entwurf {
            e.last.richtung = SimRichtung(art: .normale)
            e.last.betrag = 2
            e.last.einheit = "kg"
            actions.setKraftEntwurf(e)
        }
        actions.kraftEntwurfSpeichern()
        check(await wait(30) { st.stand?.lastfall(gelenk)?.lasten.count == 1 && st.entwurf == nil },
              "Kraft 2 kg gespeichert")
        let a = rec.header.faces[oben].a ?? 0
        check(controller.simulationKlickAufFlaeche(teil: teil, flaeche: oben), "Klick auf die Oberseite (Druck)")
        if var e = st.entwurf {
            e.last.verteilung = "flaeche"
            e.last.einheit = SimKraft.druck
            e.last.betrag = 0.02
            e.last.richtung = SimRichtung(art: .normale)
            actions.setKraftEntwurf(e)
        }
        let vorschau = st.entwurf?.kraft.map { Double(simd_length($0)) } ?? 0
        check(abs(vorschau - 0.02 * a) < 0.01 * 0.02 * a + 1e-6,
              "Vorschau Druck 0,02 N/mm² × \(KevFormat.number(a, digits: 0)) mm² = "
              + "\(KevFormat.number(vorschau, digits: 2)) N")
        await pause(0.5)
        await foto("12-flaechenlast-entwurf")
        actions.kraftEntwurfSpeichern()
        check(await wait(30) { st.stand?.lastfall(gelenk)?.lasten.count == 2 && st.entwurf == nil }, "Druck gespeichert")
        let druck = st.stand?.lastfall(gelenk)?.lasten.first { $0.aufFlaeche }
        let fw = druck?.kraftWirksam.map { Double(simd_length($0)) } ?? 0
        check(druck?.zustand == .ok && abs(fw - 0.02 * a) < 0.02 * 0.02 * a,
              "Kernel: Druck auf der ganzen Fläche \(KevFormat.number(fw, digits: 2)) N (p · A = "
              + "\(KevFormat.number(0.02 * a, digits: 2)) N), Fläche "
              + "\(KevFormat.number(druck?.flaecheMm2Wirksam ?? 0, digits: 0)) mm²")
        actions.setSimulationWerkzeug(.keins)

        // d) gelenkiges Lager im Bolzenloch, nur in „gelenk“
        zustand.reiter = .lager
        let bohrung = rec.header.faces.indices.first {
            rec.header.faces[$0].t == "cylinder" && (rec.header.faces[$0].r ?? 0) > 4
        }
        let vorher = Set(st.stand?.lager.map(\.id) ?? [])
        actions.setLagerEntwurf(nil)
        st.lagerSzenarien = [gelenk]
        st.lagerArt = .gelenkig
        st.lagerAuf = .flaeche
        st.lagerGleiten = nil
        actions.setSimulationWerkzeug(.lager)
        if let b = bohrung {
            check(controller.simulationKlickAufFlaeche(teil: teil, flaeche: b), "Klick ins Bolzenloch (Fläche \(b))")
            check(st.lagerEntwurf?.szenarien == [gelenk], "Entwurf gilt nur in „\(gelenk)“")
            actions.lagerEntwurfSpeichern()
            check(await wait(30) {
                st.stand?.lager.contains { !vorher.contains($0.id) && $0.art == .gelenkig && $0.zustand == .ok } == true
            }, "Gelenkiges Lager gespeichert")
        } else {
            check(false, "Bolzenloch nicht gefunden")
        }
        // e) gleitend entlang einer Kante auf der Unterseite
        st.lagerArt = .gleitend
        check(controller.simulationKlickAufFlaeche(teil: teil, flaeche: unten), "Klick auf die Unterseite (gleitend)")
        let kante = rec.header.edges.indices.first { rec.header.edges[$0].t == "line" }
        if let k = kante {
            st.kanteWaehlen = true
            controller.simulationKanteGewaehlt(teil: teil, kante: k)
        }
        check(st.lagerEntwurf?.gleiten?.quelle == "kante",
              "Gleitrichtung \(st.lagerEntwurf?.gleiten?.titel ?? "–") (Kante \(kante.map(String.init) ?? "–"))")
        await pause(0.5)
        await foto("13-lager-kante")
        let vorher2 = Set(st.stand?.lager.map(\.id) ?? [])
        actions.lagerEntwurfSpeichern()
        check(await wait(30) {
            st.stand?.lager.contains { !vorher2.contains($0.id) && $0.gleiten?.quelle == "kante" && $0.zustand == .ok
                && $0.gehaltenWirksam.count == 2 } == true
        }, "Gleitendes Lager (Schiene) gespeichert, zwei gehaltene Richtungen")
        let neu = Set(st.stand?.lager.map(\.id) ?? []).subtracting(vorher)
        check(await wait(20) { Set(model.statik.ergebnis?.szenario(gelenk)?.lagerIDs ?? []).isSuperset(of: neu) },
              "STATICS „\(gelenk)“: Lager \(model.statik.ergebnis?.szenario(gelenk)?.lagerIDs ?? [])")
        st.lagerSzenarien = nil
        actions.setSimulationWerkzeug(.keins)

        // f) Festigkeit (FEM) mit gelenkigem und gleitendem Lager
        zustand.reiter = .rechnen
        actions.simulationRechnen(was: "festigkeit", lastfall: gelenk, teil: nil, fein: false, grenze: nil)
        let jf = await jobFertig("festigkeit", 300)
        check(jf?.stand == "done", "Festigkeit (FEM) mit Gelenk und Schiene: \(jf?.text ?? jf?.meldung ?? "–")")
        _ = await wait(10) {
            model.statik.ergebnis?.szenario(gelenk)?.festkoerper?.teile.contains { $0.teil == teil && $0.stand != "laeuft" }
                == true
        }
        let fk = model.statik.ergebnis?.szenario(gelenk)?.festkoerper?.teile.first { $0.teil == teil }
        check(fk?.stand == "done", "FEM \(teil): Sicherheit \(fk?.sicherheit.map(StatikZahl.sf) ?? "–") "
              + "(\(fk?.meldung ?? fk?.text ?? ""))")
        await pause(1)
        await foto("14-festigkeit-gelenk")

        // g) Grenze mit FEM
        zustand.grenzeArt = "last"
        zustand.grenzeVerfahren = "fem"
        actions.simulationGrenzeSuchen(lastfall: gelenk, art: "last", verfahren: "fem")
        let jg = await jobFertig("grenze", 600)
        check(jg?.stand == "done" && jg?.verfahren == "fem",
              "Grenze mit FEM: \(jg?.ergebnisText ?? jg?.meldung ?? "–")")
        check(jg?.werte.contains { $0.verfahren == "FEM" } == true,
              "Werte je Verfahren: " + (jg?.werte.map { "\($0.kriterium) (\($0.verfahren ?? "?"))" }
                                            .joined(separator: ", ") ?? "–"))
        check(jg?.massgebendVerfahren != nil, "Maßgebend: \(jg?.massgebendVerfahren ?? "–"), Probe "
              + (jg?.probeAusnutzung.map { KevFormat.number($0, digits: 2) } ?? "–"))
        await pause(0.5)
        await foto("15-grenze-fem")

        // h) Pfeil-Griff frei im Raum: Kugel, Ring Azimut, Einrasten
        zustand.reiter = .kraefte
        actions.setSimulationWerkzeug(.kraft)
        check(controller.simulationKlickAufFlaeche(teil: teil, flaeche: oben), "Klick für den Griff")
        if var e = st.entwurf {
            e.last.richtung = SimRichtung(art: .frei, azimut: 30, hoehe: -40)
            e.last.betrag = 10
            e.last.einheit = "N"
            e.last.verteilung = "punkt"
            actions.setKraftEntwurf(e)
        }
        await pause(0.3)
        if let g = controller.simGriffPunkt(), let p0 = controller.viewport.bildpunkt(g) {
            check(controller.simulationGriffBeginnt(p0) && st.griffArt == .kugel, "Kugel am Pfeilende angefasst")
            var p = p0
            for _ in 0..<6 {
                p = CGPoint(x: p.x + 9, y: p.y + 7)
                controller.simulationGriffZiehen(p)
            }
            let r = st.entwurf?.last.richtung
            check(r?.art == .frei && abs((r?.azimut ?? 30) - 30) > 2 && abs((r?.hoehe ?? -40) + 40) > 2,
                  "Kugel: Azimut und Höhe gedreht (\(KevFormat.number(r?.azimut ?? 0, digits: 1))°, "
                  + "\(KevFormat.number(r?.hoehe ?? 0, digits: 1))°)")
            controller.simulationGriffEnde()
        } else {
            check(false, "Griff nicht im Bild")
        }
        if let ringe = controller.simGriffRinge(), let ende = controller.simGriffPunkt(),
           let fern = ringe.azimut.max(by: { simd_length($0 - ende) < simd_length($1 - ende) }) {
            let h0 = st.entwurf?.last.richtung.hoehe ?? 0
            let az0 = st.entwurf?.last.richtung.azimut ?? 0
            let ziel = simd_length(fern - ende) * 0.7071
            let anfassen = ringe.azimut.min { abs(simd_length($0 - ende) - ziel) < abs(simd_length($1 - ende) - ziel) }
            if let an = anfassen, let p0 = controller.viewport.bildpunkt(an),
               let p1 = controller.viewport.bildpunkt(fern) {
                check(controller.simulationGriffBeginnt(p0) && st.griffArt == .ringAzimut, "Ring „nur Azimut“ angefasst")
                controller.simulationGriffZiehen(p1)
                let r = st.entwurf?.last.richtung
                check(abs((r?.hoehe ?? 99) - h0) < 0.5 && abs((r?.azimut ?? az0) - az0) > 10,
                      "Ring: nur der Azimut (\(KevFormat.number(az0, digits: 1))° → "
                      + "\(KevFormat.number(r?.azimut ?? 0, digits: 1))°, Höhe "
                      + "\(KevFormat.number(r?.hoehe ?? 0, digits: 1))°)")
                await pause(0.4)
                await foto("16-griff-ring")
                controller.simulationGriffEnde()
            } else {
                check(false, "Ring nicht im Bild")
            }
        }
        if var e = st.entwurf {
            e.last.richtung = SimRichtung(art: .frei, azimut: 0, hoehe: -86)
            actions.setKraftEntwurf(e)
        }
        if let g = controller.simGriffPunkt(), let p0 = controller.viewport.bildpunkt(g) {
            _ = controller.simulationGriffBeginnt(p0)
            controller.simulationGriffZiehen(CGPoint(x: p0.x + 0.5, y: p0.y))
            let r = st.entwurf?.last.richtung
            check(st.eingerastet != nil && (r?.art == .normale || r?.art == .achse),
                  "Eingerastet: \(st.eingerastet ?? "–") (\(r?.art.titel ?? "–"))")
            await pause(0.4)
            await foto("17-griff-eingerastet")
            controller.simulationGriffEnde()
        }

        // i) Pfeile bildschirmfest: Länge in mm folgt dem Zoom
        let punkt = st.entwurf?.last.ort.punkt
        actions.setPfeileBildschirmfest(true)
        let l1 = controller.simPfeilLaenge(bei: punkt)
        controller.zoomStep(4)
        _ = await wait(2) { abs(controller.simPfeilLaenge(bei: punkt) - l1) > 0.1 * l1 }
        let l2 = controller.simPfeilLaenge(bei: punkt)
        check(abs(l2 - l1) > 0.1 * l1, "Bildschirmfest: Pfeil \(KevFormat.number(Double(l1), digits: 1)) mm → "
              + "\(KevFormat.number(Double(l2), digits: 1)) mm nach dem Zoomen (gleich groß auf dem Bildschirm)")
        await pause(0.5)
        await foto("18-bildschirmfest")
        controller.zoomStep(-4)
        actions.setPfeileBildschirmfest(false)
        actions.setKraftEntwurf(nil)
        actions.setSimulationWerkzeug(.keins)
    }
}
