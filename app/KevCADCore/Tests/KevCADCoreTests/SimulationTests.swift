import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Bereich „Simulation“ (PROTOCOL.md „Simulation“, PLAN-SIMULATION.md): SIM und SIM_JOB aus den Testdateien
/// (kernel/tools/make_simulation_fixtures.py), Kraft aus Richtung und Betrag (Spiegel von kraft.py), Operationen und
/// Anfragen der App, Ergebnistabelle, Controller (Klick → Entwurf, Griff, Körper im Viewer, Vorher-Stand).
final class SimulationTests: XCTestCase {
    private func erwartet(_ name: String) throws -> JSONValue {
        let j = try JSONDecoder().decode(JSONValue.self, from: Fixtures.data("sim.json"))
        return try XCTUnwrap(j[name])
    }

    func testSimAusTestdatei() throws {
        guard case .simulation(let s) = try Fixtures.message("sim.frame") else { return XCTFail("kein SIM") }
        let soll = try erwartet("sim")
        XCTAssertEqual(s.run, soll["run"]?.intValue)
        XCTAssertEqual(s.stand, soll["stand"]?.intValue)
        XCTAssertEqual(s.lastfaelle.count, soll["lastfaelle"]?.intValue)
        let l = try XCTUnwrap(s.lastfall(soll["erster"]?.stringValue))
        XCTAssertEqual(l.lasten.count, soll["lasten"]?.intValue)
        XCTAssertEqual(l.lasten[0].kraft, soll["kraft_l1"]?.vector3)
        XCTAssertEqual(l.lasten[0].zustand, .ok)
        XCTAssertEqual(l.lasten[0].einheit, "kg")
        XCTAssertEqual(l.lasten[0].richtung.art, .normale)
        XCTAssertEqual(l.lasten[0].ort.flaeche, 5)
        XCTAssertNotNil(l.lasten[0].ort.signatur)
        XCTAssertEqual(l.lasten[1].zustand.rawValue, soll["zustand_l2"]?.stringValue)
        XCTAssertEqual(l.lasten[1].gegen, "Bolzen")
        XCTAssertTrue(l.lasten[1].paar)
        XCTAssertNil(l.lasten[1].kraftWirksam)
        XCTAssertEqual(l.lasten[1].richtung.art, .frei)
        XCTAssertEqual(l.lasten[1].richtung.hoehe, -30, accuracy: 1e-9)
        XCTAssertEqual(l.nichtZuordenbar, 1)
        XCTAssertEqual(l.neigungGrad, soll["neigung"]?.doubleValue ?? -1, accuracy: 1e-9)
        XCTAssertEqual(l.neigungRichtung, "+y")
        XCTAssertEqual(l.zielSicherheit, soll["ziel"]?.doubleValue)
        XCTAssertEqual(l.untergrund, soll["untergrund"]?.stringValue)
        XCTAssertEqual(l.ampel, .gelb)
        let fahrt = try XCTUnwrap(s.lastfaelle[1].fahrt)
        XCTAssertEqual(fahrt.bremsen, .abrupt)
        XCTAssertEqual(fahrt.geschwindigkeit, 1)
        XCTAssertTrue(s.lastfaelle[1].dynamisch)
        XCTAssertEqual(s.lager.count, soll["lager"]?.intValue)
        XCTAssertEqual(s.lager[0].zustand.rawValue, soll["lager_zustand"]?.stringValue)
        XCTAssertEqual(s.lager[0].auf, .flaeche)
        XCTAssertEqual(s.modellLager.first?.art, .gleitend)
        XCTAssertEqual(s.modellLager.first?.punkt, SIMD3(0, 0, 0))
        XCTAssertEqual(s.modell.count, soll["modell"]?.intValue)
        XCTAssertEqual(s.modell.filter(\.ersetzt).map(\.name), soll["ersetzt"]?.stringList)
        // Szenarien aus model.py, die die App ersetzt, zählen nicht doppelt
        XCTAssertEqual(s.alleNamen, ["Aufstützen 30 kg", "Bremsen aus 1 m/s", "Eigengewicht"])
        XCTAssertEqual(s.abgeleitet.filter { !$0.aktiv }.map(\.id), soll["abgeleitet_aus"]?.stringList)
        XCTAssertEqual(s.topologie["Halter"]?.schutz.first?.index, soll["topologie_schutz"]?.intValue)
        XCTAssertEqual(s.topologie["Halter"]?.behalten, 0.42)
        XCTAssertEqual(s.hinweise.count, soll["hinweise"]?.intValue)
    }

    func testJobAusTestdatei() throws {
        guard case .simulationJob(let j) = try Fixtures.message("sim_job.frame") else { return XCTFail() }
        let soll = try erwartet("sim_job")
        XCTAssertEqual(j.auftrag, soll["auftrag"]?.intValue)
        XCTAssertEqual(j.was, "grenze")
        XCTAssertFalse(j.laeuft)
        XCTAssertEqual(j.werte.count, soll["werte"]?.intValue)
        XCTAssertEqual(j.werte.first?.kriterium, "Ziel-Sicherheit")
        XCTAssertEqual(j.werte.first?.grenze ?? 0, 1.24, accuracy: 1e-9)
        XCTAssertEqual(j.titel, "Grenze: wie viel Last")
        guard case .simulationJob(let l) = try Fixtures.message("sim_job_laeuft.frame") else { return XCTFail() }
        XCTAssertTrue(l.laeuft)
        XCTAssertEqual(l.fortschritt ?? 0, 0.45, accuracy: 1e-9)
        XCTAssertEqual(l.titel, "Festigkeit (FEM)")
    }

    /// Spiegel von kernel/src/kevcad_kernel/simulation/kraft.py (gleiche Zahlen wie test_simulation.py).
    func testKraftAusRichtungUndBetrag() {
        let n = SIMD3<Float>(0, 0, 1)
        XCTAssertEqual(SimKraft.kraft(SimRichtung(art: .normale), betrag: 100, einheit: "N", normale: n), SIMD3(0, 0, -100))
        XCTAssertEqual(SimKraft.kraft(SimRichtung(art: .normale, umkehren: true), betrag: 100, einheit: "N",
                                      normale: SIMD3(0, 0, 2)), SIMD3(0, 0, 100))
        XCTAssertNil(SimKraft.kraft(SimRichtung(art: .normale), betrag: 100, einheit: "N", normale: nil))
        let kg = SimKraft.kraft(SimRichtung(art: .achse, achse: "-z"), betrag: 30, einheit: "kg", normale: nil)
        XCTAssertEqual(kg?.z ?? 0, -294.3, accuracy: 1e-3)
        let frei = SimKraft.kraft(SimRichtung(art: .frei, azimut: 90, hoehe: -45), betrag: 10, einheit: "N", normale: nil)
        XCTAssertEqual(frei?.x ?? 1, 0, accuracy: 1e-5)
        XCTAssertEqual(frei?.y ?? 0, Float(10 / 2.0.squareRoot()), accuracy: 1e-4)
        XCTAssertEqual(frei?.z ?? 0, Float(-10 / 2.0.squareRoot()), accuracy: 1e-4)
        let w = SimKraft.winkel(SIMD3(0, 1, -1))
        XCTAssertEqual(w.azimut, 90, accuracy: 1e-4)
        XCTAssertEqual(w.hoehe, -45, accuracy: 1e-4)
        XCTAssertNil(SimKraft.kraft(SimRichtung(art: .achse), betrag: 0, einheit: "N", normale: nil))
        XCTAssertEqual(SimKraft.achse("x"), SIMD3(1, 0, 0))
    }

    func testOperationenUndAnfragen() throws {
        var l = SimLastfall(name: "A")
        l.neigungGrad = 5
        l.neigungRichtung = "-y"
        l.zielSicherheit = 2.5
        let op = SimOp.lastfallSetzen(l)
        XCTAssertEqual(op["op"]?.stringValue, "lastfall_setzen")
        XCTAssertEqual(op["felder"]?["neigung"]?["grad"]?.doubleValue, 5)
        XCTAssertEqual(op["felder"]?["ziel"]?["sicherheit"]?.doubleValue, 2.5)
        XCTAssertEqual(op["felder"]?["art"]?.stringValue, "statisch")
        let last = SimLast(teil: "Halter", gegen: "Ball", ort: SimOrt(flaeche: 3, punkt: SIMD3(1, 2, 3),
                                                                       normale: SIMD3(0, 0, 1)),
                           richtung: SimRichtung(art: .frei, azimut: 10, hoehe: -20), betrag: 5, einheit: "kg")
        let ls = SimOp.lastSetzen("A", last)
        XCTAssertEqual(ls["last"]?["teil"]?.stringValue, "Halter")
        XCTAssertEqual(ls["last"]?["gegen"]?.stringValue, "Ball")
        XCTAssertEqual(ls["last"]?["ort"]?["flaeche"]?.intValue, 3)
        XCTAssertEqual(ls["last"]?["richtung"]?["azimut"]?.doubleValue, 10)
        XCTAssertNil(ls["last"]?["id"], "neue Last ohne Kennung")
        XCTAssertNil(ls["last"]?["kraft"], "die Kraft rechnet der Kernel")
        XCTAssertEqual(SimOp.lastfallNeu("F", dynamisch: true)["fahrt"]?["bremsen"]?.stringValue, "abrupt")
        XCTAssertEqual(SimOp.abgeleitet("boden:Fuß", aktiv: false)["aktiv"]?.boolValue, false)
        let edit = SimEditMessage(id: "e1", basis: 4, ops: [op, ls])
        let j = try JSONDecoder().decode(JSONValue.self, from: try edit.frame().header)
        XCTAssertEqual(j["type"]?.stringValue, "SIM_EDIT")
        XCTAssertEqual(j["basis"]?.intValue, 4)
        XCTAssertEqual(j["ops"]?.arrayValue?.count, 2)
        let run = try JSONDecoder().decode(
            JSONValue.self, from: try SimRunMessage(id: "r1", was: "grenze", lastfall: "A", grenze: "last").frame().header)
        XCTAssertEqual(run["type"]?.stringValue, "SIM_RUN")
        XCTAssertEqual(run["grenze"]?.stringValue, "last")
        XCTAssertNil(run["teil"])
        let cancel = try JSONDecoder().decode(JSONValue.self, from: try SimCancelMessage().frame().header)
        XCTAssertEqual(cancel["type"]?.stringValue, "SIM_CANCEL")
        let topo = TopologieStartErweitert(
            basis: TopologieStartMessage(teil: "Halter", szenario: "A", behalten: 0.4, ueberhang: false, fein: false),
            bohrungen: false, einsaetze: true, kontakt: true, bett: false, steg: 8, schutz: [7, 9])
        let t = try JSONDecoder().decode(JSONValue.self, from: try topo.frame().header)
        XCTAssertEqual(t["type"]?.stringValue, "TOPO_START")
        XCTAssertEqual(t["bohrungen"]?.boolValue, false)
        XCTAssertEqual(t["schutz"]?.arrayValue?.compactMap { $0["index"]?.intValue }, [7, 9])
        XCTAssertEqual(t["steg"]?.doubleValue, 8)
    }

    func testErgebnistabelleUndVergleich() throws {
        guard case .statik(let e) = try Fixtures.message("statics_festkoerper.frame") else { return XCTFail() }
        let sz = try XCTUnwrap(e.szenarien.first { $0.festkoerper?.teile.contains { $0.stand == "done" } == true })
        let z = SimErgebnis.zeilen(sz)
        XCTAssertFalse(z.isEmpty)
        let fem = try XCTUnwrap(z.first { $0.nachweis == .fem })
        XCTAssertNotNil(fem.sicherheit)
        XCTAssertEqual(fem.teil, fem.name)
        for s in sz.staebe {
            XCTAssertEqual(z.first { $0.name == s.name }?.nachweis, .s1, s.name)
        }
        XCTAssertTrue(SimErgebnis.gefiltert(z, .rot).allSatisfy { $0.ampel == .rot })
        XCTAssertTrue(SimErgebnis.gefiltert(z, .gelbRot).allSatisfy { $0.ampel == .rot || $0.ampel == .gelb })
        let sortiert = z.sorted(using: KeyPathComparator(\SimErgebnisZeile.sicherheitSort))
        XCTAssertEqual(sortiert.first?.sicherheit, z.compactMap(\.sicherheit).min())
        // Vergleich mit sich selbst: keine Änderung; mit einem anderen Szenario gleiche Kennungen
        let v = SimErgebnis.vergleich(sz, sz)
        XCTAssertTrue(v.allSatisfy { ($0.aenderung ?? 0) == 0 })
        guard case .statik(let s2) = try Fixtures.message("statics.frame") else { return XCTFail() }
        let a = try XCTUnwrap(s2.szenarien.first)
        let vv = SimErgebnis.vergleich(a, sz)
        XCTAssertEqual(Set(vv.map(\.id)), Set(SimErgebnis.zeilen(a).map(\.id)).union(Set(z.map(\.id))))
    }

    // MARK: Controller

    @MainActor
    private func controller() throws -> AppController {
        let c = AppController(model: AppModel())
        let events = try FrameReader().feed(Fixtures.data("stream.bin")).map(KernelConnection.decode)
        c.handle(Array(events.prefix(7)))  // HELLO, PROJECT, Lauf mit Grundplatte und Halter/Bolzen
        return c
    }

    @MainActor
    func testKlickErzeugtEntwurfUndKoerper() throws {
        let c = try controller()
        let st = c.model.simulation
        guard case .simulation(let s) = try Fixtures.message("sim.frame") else { return XCTFail() }
        c.handle([.message(.simulation(s))])
        XCTAssertEqual(st.auswahl, "Aufstützen 30 kg", "erster Lastfall der App gewählt")
        // ohne aktiven Bereich verbraucht ein Klick nichts
        c.setSimulationWerkzeug(.kraft)
        XCTAssertFalse(c.simulationKlick(nil, nil))
        c.setSimulationAktiv(true)
        XCTAssertEqual(c.viewport.hint, SimulationStore.Werkzeug.kraft.hinweis)
        // Fläche 5 der Grundplatte (Ebene, Normale aus dem Netz)
        XCTAssertTrue(c.simulationKlickAufFlaeche(teil: "Grundplatte", flaeche: 5))
        let e = try XCTUnwrap(st.entwurf)
        XCTAssertEqual(e.last.teil, "Grundplatte")
        XCTAssertEqual(e.last.ort.flaeche, 5)
        let n = try XCTUnwrap(e.last.ort.normale)
        let fn = try XCTUnwrap(c.flaecheNormale("Grundplatte", 5))
        XCTAssertGreaterThan(simd_dot(n, fn), 0.99, "Normale am Treffer wie die der Fläche")
        XCTAssertEqual(e.last.ort.signatur?["t"]?.stringValue, "plane")
        XCTAssertEqual(e.last.richtung.art, .normale)
        let f = try XCTUnwrap(e.kraft)
        XCTAssertEqual(simd_dot(simd_normalize(f), fn), -1, accuracy: 1e-4, "drückt in die Fläche")
        // Körper: Lasten des Lastfalls (die zugeordnete), Entwurf mit Griff, Lager, abgeleitetes Bodenlager aus
        let ids = c.scene.simulationBodies.map(\.id)
        XCTAssertTrue(ids.contains("\(AppController.simulationPraefix)e"))
        XCTAssertTrue(ids.contains("\(AppController.simulationPraefix)eg"))
        XCTAssertTrue(ids.contains("\(AppController.simulationPraefix)l0"))
        XCTAssertFalse(ids.contains("\(AppController.simulationPraefix)l1"), "nicht zuordenbare Last nicht gezeigt")
        XCTAssertTrue(ids.contains { $0.hasPrefix("\(AppController.simulationPraefix)a0") })
        XCTAssertTrue(c.scene.renderBodies.contains { $0.id == "\(AppController.simulationPraefix)e" })
        XCTAssertTrue(c.scene.simulationBodies.allSatisfy { !$0.isPickable })
        // Griff: das Ende des Pfeils liegt gegen die Kraft vor dem Punkt
        let g = try XCTUnwrap(c.simGriffPunkt())
        let p = try XCTUnwrap(e.last.ort.punkt)
        XCTAssertGreaterThan(simd_dot(p - g, simd_normalize(f)), 0)
        // Speichern ohne Kernel: Fehler als Meldung, der Entwurf bleibt
        c.kraftEntwurfSpeichern()
        XCTAssertTrue(st.meldungFehler)
        XCTAssertNotNil(st.entwurf)
        // Lager per Klick, Schutzfläche per Klick
        c.setSimulationWerkzeug(.lager)
        st.lagerArt = .gleitend
        XCTAssertTrue(c.simulationKlickAufFlaeche(teil: "Grundplatte", flaeche: 5))
        XCTAssertEqual(st.lagerEntwurf?.art, .gleitend)
        XCTAssertEqual(st.lagerEntwurf?.auf, .flaeche)
        XCTAssertTrue(c.scene.simulationBodies.contains { $0.id.hasPrefix("\(AppController.simulationPraefix)aef") },
                      "Lagerfläche des Entwurfs halbdurchsichtig")
        c.setSimulationWerkzeug(.schutz)
        XCTAssertTrue(c.simulationKlickAufFlaeche(teil: "Grundplatte", flaeche: 5))
        XCTAssertEqual(st.topologieTeil, "Grundplatte")
        XCTAssertEqual(st.schutzFlaechen, [5])
        XCTAssertTrue(c.scene.simulationBodies.contains { $0.id.hasPrefix("\(AppController.simulationPraefix)s5") })
        c.simulationOrtGewaehlt(teil: "Grundplatte", flaeche: 5, punkt: nil, normale: nil)
        XCTAssertEqual(st.schutzFlaechen, [], "noch einmal: entfernt")
        // Bereich verlassen: Werkzeug aus, Körper weg
        c.setSimulationAktiv(false)
        XCTAssertEqual(st.werkzeug, .keins)
        XCTAssertNil(c.viewport.hint)
        XCTAssertTrue(c.scene.simulationBodies.isEmpty)
    }

    @MainActor
    func testFreieRichtungUndVorherStand() throws {
        let c = try controller()
        let st = c.model.simulation
        guard case .simulation(let s) = try Fixtures.message("sim.frame") else { return XCTFail() }
        c.handle([.message(.simulation(s))])
        c.setSimulationAktiv(true)
        c.lastBearbeiten("L1")
        let e = try XCTUnwrap(st.entwurf)
        XCTAssertEqual(e.bearbeitet, "L1")
        XCTAssertEqual(e.last.ort.punkt, SIMD3(40, 0, 60), "Ort wie im Modell zugeordnet")
        XCTAssertFalse(c.scene.simulationBodies.contains { $0.id == "\(AppController.simulationPraefix)l0" },
                       "die bearbeitete Last steht nur als Entwurf im Viewer")
        // Kraft frei: Winkel in Kraft
        var x = e
        x.last.richtung = SimRichtung(art: .frei, azimut: 0, hoehe: 0)
        c.setKraftEntwurf(x)
        let f = try XCTUnwrap(st.entwurf?.kraft)
        XCTAssertEqual(f.x, Float(30 * SimKraft.g), accuracy: 1e-2)
        // STATICS zweimal mit anderem Inhalt: der vorherige Stand des Szenarios bleibt für den Vergleich
        guard case .statik(var a) = try Fixtures.message("statics.frame") else { return XCTFail() }
        c.handle([.message(.statik(a))])
        XCTAssertTrue(st.vorher.isEmpty)
        let name = a.szenarien[0].name
        a.szenarien[0].urteile.append(StatikUrteil(id: 99, art: "kippen", teil: nil, ampel: .rot, text: "kippt"))
        c.handle([.message(.statik(a))])
        XCTAssertNotNil(st.vorher[name])
        // SIM_JOB: fertige Grenze bleibt als Ergebnis stehen
        guard case .simulationJob(let j) = try Fixtures.message("sim_job.frame") else { return XCTFail() }
        c.handle([.message(.simulationJob(j))])
        XCTAssertEqual(st.grenze?.auftrag, j.auftrag)
        XCTAssertFalse(st.meldungFehler)
        XCTAssertEqual(st.meldung, j.text)
    }
}
