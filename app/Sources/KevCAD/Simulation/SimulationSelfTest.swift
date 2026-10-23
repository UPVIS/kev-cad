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
        func jobFertig(_ was: String, _ s: Double) async -> SimJob? {
            _ = await wait(5) { st.job?.was == was && st.job?.laeuft == true || st.job?.was == was && st.job?.laeuft == false }
            _ = await wait(s) { st.job?.was == was && st.job?.laeuft == false }
            return st.job?.was == was ? st.job : nil
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

        // 13. Zurück im 3D-Bereich: Kräfte und Lager verschwinden aus dem Viewer
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
