import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Bereich „Simulation“, offene Grenzen geschlossen (Zweig simulation2, PLAN-SIMULATION.md): Lager je Lastfall,
/// Gleitrichtung frei (Achse, Kante), Last auf der ganzen Fläche (Druck), Grenze mit FEM (Verfahren), Vergleich nur
/// gleicher Verfahren, Pfeil-Griff frei im Raum (Trackball, Ringe, Einrasten), Pfeile bildschirmfest.
final class Simulation2Tests: XCTestCase {
    private func erwartet(_ name: String) throws -> JSONValue {
        let j = try JSONDecoder().decode(JSONValue.self, from: Fixtures.data("sim.json"))
        return try XCTUnwrap(j[name])
    }

    private func nah(_ a: SIMD3<Float>?, _ b: SIMD3<Float>, _ tol: Float = 1e-4, _ text: String = "",
                     file: StaticString = #filePath, line: UInt = #line) {
        guard let a else { return XCTFail("nil statt \(b) \(text)", file: file, line: line) }
        XCTAssertLessThan(simd_length(a - b), tol, "\(a) statt \(b) \(text)", file: file, line: line)
    }

    // MARK: Nachrichten

    func testNeueFelderAusTestdatei() throws {
        guard case .simulation(let s) = try Fixtures.message("sim.frame") else { return XCTFail("kein SIM") }
        let soll = try erwartet("sim")
        // Lager je Lastfall
        let szen = try XCTUnwrap(soll["lager_szenarien"]?.arrayValue)
        XCTAssertEqual(s.lager.count, szen.count)
        XCTAssertNil(s.lager[0].szenarien)
        XCTAssertEqual(s.lager[1].szenarien, szen[1].stringList)
        XCTAssertTrue(s.lager[0].giltFuer("Bremsen aus 1 m/s"))
        XCTAssertTrue(s.lager[1].giltFuer("Aufstützen 30 kg"))
        XCTAssertFalse(s.lager[1].giltFuer("Bremsen aus 1 m/s"))
        XCTAssertFalse(s.lager[1].giltFuer(nil))
        XCTAssertEqual(s.lager[0].giltText, "alle Lastfälle")
        XCTAssertEqual(s.lager[1].giltText, "nur „Aufstützen 30 kg“")
        // gleitend entlang einer Kante (Schiene)
        let g = try XCTUnwrap(s.lager[1].gleiten)
        XCTAssertEqual(g.art, .richtung)
        nah(g.richtung, try XCTUnwrap(soll["gleiten_richtung"]?.vector3))
        XCTAssertEqual(g.quelle, soll["gleiten_quelle"]?.stringValue)
        XCTAssertEqual(g.kante, 7)
        XCTAssertEqual(g.titel, "entlang Kante 7")
        XCTAssertEqual(s.lager[1].gehaltenWirksam, (soll["gehalten_a2"]?.arrayValue ?? []).compactMap(\.vector3))
        XCTAssertNil(s.lager[0].gleiten)
        XCTAssertEqual(s.modellLager.first?.gehaltenWirksam, [SIMD3(0, 0, -1)])
        // Last auf der ganzen Fläche als Druck
        let l = try XCTUnwrap(s.lastfall(soll["erster"]?.stringValue))
        let l3 = l.lasten[2]
        XCTAssertEqual(l3.verteilung, soll["verteilung_l3"]?.stringValue)
        XCTAssertTrue(l3.aufFlaeche)
        XCTAssertEqual(l3.einheit, soll["einheit_l3"]?.stringValue)
        XCTAssertEqual(l3.flaecheMm2Wirksam, soll["flaeche_mm2_l3"]?.doubleValue)
        XCTAssertEqual(l3.betragN, 0.05 * 800, accuracy: 1e-9, "Druck × Fläche")
        XCTAssertFalse(l.lasten[0].aufFlaeche)
    }

    func testGrenzeMitVerfahrenAusTestdatei() throws {
        guard case .simulationJob(let j) = try Fixtures.message("sim_job.frame") else { return XCTFail() }
        let soll = try erwartet("sim_job")
        XCTAssertEqual(j.verfahren, soll["verfahren"]?.stringValue)
        XCTAssertEqual(j.massgebendVerfahren, soll["massgebend_verfahren"]?.stringValue)
        XCTAssertEqual(j.werte.map { $0.verfahren ?? "" }, soll["werte_verfahren"]?.stringList)
        XCTAssertEqual(j.probeAusnutzung, soll["probe_ausnutzung"]?.doubleValue)
        XCTAssertEqual(j.probeFaktor ?? 0, 1.24, accuracy: 1e-9)
        XCTAssertNotNil(j.hinweis)
        XCTAssertEqual(Set(j.werte.map(\.id)).count, j.werte.count, "gleiches Kriterium, anderes Verfahren: eigene Zeile")
        guard case .simulationJob(let l) = try Fixtures.message("sim_job_laeuft.frame") else { return XCTFail() }
        XCTAssertNil(l.verfahren)
        XCTAssertNil(l.probeAusnutzung)
    }

    func testDruckJsonUndAnfragen() throws {
        let n = SIMD3<Float>(0, 0, 1)
        nah(SimKraft.kraft(SimRichtung(art: .normale), betrag: 0.05, einheit: "N/mm2", normale: n, flaecheMm2: 800),
            SIMD3(0, 0, -40))
        nah(SimKraft.kraft(SimRichtung(art: .normale, umkehren: true), betrag: 0.05, einheit: "N/mm2", normale: n,
                           flaecheMm2: 800), SIMD3(0, 0, 40), 1e-4, "umkehren zieht")
        XCTAssertNil(SimKraft.kraft(SimRichtung(art: .achse, achse: "-z"), betrag: 0.05, einheit: "N/mm2", normale: n,
                                    flaecheMm2: 800), "Druck nur senkrecht auf die Fläche")
        XCTAssertNil(SimKraft.kraft(SimRichtung(art: .normale), betrag: 0.05, einheit: "N/mm2", normale: n),
                     "ohne Fläche kein Druck")
        // Entwurf rechnet mit dem Flächeninhalt der Signatur
        let sig = JSONValue.object(["t": .string("plane"), "a": .number(800)])
        let last = SimLast(teil: "Halter", ort: SimOrt(flaeche: 5, punkt: .zero, normale: n, signatur: sig),
                           richtung: SimRichtung(art: .normale), betrag: 0.05, einheit: "N/mm2", verteilung: "flaeche")
        nah(SimulationStore.KraftEntwurf(last: last).kraft, SIMD3(0, 0, -40))
        XCTAssertEqual(last.json["verteilung"]?.stringValue, "flaeche")
        XCTAssertEqual(last.json["einheit"]?.stringValue, "N/mm2")
        XCTAssertNil(SimLast(teil: "H", ort: SimOrt(), richtung: SimRichtung(), betrag: 1).json["verteilung"])
        // Lager: Lastfälle und Gleitrichtung im SIM_EDIT
        var lager = SimLager(teil: "Schlitten", art: .gleitend, ort: SimOrt(flaeche: 2), szenarien: ["A", "B"],
                             gleiten: .achse("+x"))
        var j = lager.json
        XCTAssertEqual(j["szenarien"]?.stringList, ["A", "B"])
        XCTAssertEqual(j["gleiten"]?["art"]?.stringValue, "richtung")
        XCTAssertEqual(j["gleiten"]?["richtung"]?.vector3, SIMD3(1, 0, 0))
        XCTAssertEqual(j["gleiten"]?["quelle"]?.stringValue, "achse")
        lager.szenarien = nil
        lager.gleiten = .flaeche
        j = lager.json
        XCTAssertEqual(j["szenarien"], .null, "alle Lastfälle: null")
        XCTAssertNil(j["gleiten"], "in der Fläche: kein gleiten")
        lager.art = .fest
        lager.gleiten = .achse("+y")
        XCTAssertNil(lager.json["gleiten"], "nur gleitend")
        XCTAssertEqual(SimGleiten.achse("-z").titel, "entlang −Z")
        XCTAssertEqual(SimGleiten.flaeche.titel, "in der Fläche")
        // SIM_RUN mit Verfahren
        let run = try JSONDecoder().decode(JSONValue.self, from: try SimRunMessage(
            id: "r", was: "grenze", lastfall: "A", grenze: "last", verfahren: "fem").frame().header)
        XCTAssertEqual(run["verfahren"]?.stringValue, "fem")
        let alt = try JSONDecoder().decode(JSONValue.self, from: try SimRunMessage(
            id: "r", was: "rechnen").frame().header)
        XCTAssertNil(alt["verfahren"], "ohne Verfahren wie bisher")
    }

    // MARK: Vergleich nur gleicher Verfahren

    private func szenario(_ json: String) throws -> StatikSzenario {
        StatikSzenario(json: try JSONDecoder().decode(JSONValue.self, from: Data(json.utf8)))
    }

    func testVergleichNurGleicheVerfahren() throws {
        // A: Halter mit FEM (Sicherheit 20, Kragträger S0 15); B: nur S0 (10); C: FEM (8); D: FEM ohne Kragträger
        let fem = { (s: Double, k: String) in
            """
            {"name": "L", "ampel": "gruen", "ziel": 4, "kennzahlen": {}, "urteile": [], "staebe": [],
             "teile": [{"name": "Halter", "ausnutzung": \(4 / s), "ampel": "gruen", "sicherheit": \(s), "fem": true}],
             "festkoerper": {"stand": "done", "teile": [{"teil": "Halter", "stand": "done", "ampel": "gruen",
                             "sicherheit": \(s), "ziel": 4\(k)}]}}
            """
        }
        let a = try szenario(fem(20, ", \"kragtraeger\": 15"))
        let b = try szenario("""
            {"name": "L", "ampel": "gelb", "ziel": 4, "kennzahlen": {}, "urteile": [], "staebe": [],
             "teile": [{"name": "Halter", "ausnutzung": 0.4, "ampel": "gruen", "sicherheit": 10}]}
            """)
        let c = try szenario(fem(8, ""))
        let d = try szenario(fem(16, ""))
        // FEM gegen nur S0: verglichen werden die Kragträger-Werte (S0 gegen S0), nicht FEM gegen S0
        let ab = try XCTUnwrap(SimErgebnis.vergleich(a, b).first { $0.name == "Halter" })
        XCTAssertEqual(ab.verfahren, "S0")
        XCTAssertEqual(ab.a, 15)
        XCTAssertEqual(ab.b, 10)
        XCTAssertEqual(ab.aenderung ?? 0, -100.0 / 3, accuracy: 1e-6)
        XCTAssertNil(ab.hinweis)
        // FEM gegen FEM
        let ac = try XCTUnwrap(SimErgebnis.vergleich(a, c).first { $0.name == "Halter" })
        XCTAssertEqual(ac.verfahren, "FEM")
        XCTAssertEqual(ac.a, 20)
        XCTAssertEqual(ac.b, 8)
        XCTAssertEqual(ac.aenderung ?? 0, -60, accuracy: 1e-6)
        // FEM ohne Kragträger gegen nur S0: kein gemeinsames Verfahren, keine Prozent
        let db = try XCTUnwrap(SimErgebnis.vergleich(d, b).first { $0.name == "Halter" })
        XCTAssertEqual(db.hinweis, "nicht vergleichbar (FEM ↔ S0)")
        XCTAssertNil(db.aenderung)
        XCTAssertEqual(db.verfahrenText, "nicht vergleichbar (FEM ↔ S0)")
        XCTAssertEqual(SimErgebnis.ampel(ausnutzung: 0.9), .gruen)
        XCTAssertEqual(SimErgebnis.ampel(ausnutzung: 1.5), .gelb)
        XCTAssertEqual(SimErgebnis.ampel(ausnutzung: 2.5), .rot)
    }

    // MARK: Griff (reine Mathematik)

    func testTrackballFolgtDerMaus() {
        // Blick nach +Y (Ansicht von vorn): rechts +X, oben +Z. Kraft nach +Y (vom Betrachter weg): das Pfeilende
        // liegt zum Betrachter hin, auf dem Bildschirm genau in der Mitte der Kugel.
        let rechts = SIMD3<Float>(1, 0, 0), oben = SIMD3<Float>(0, 0, 1), blick = SIMD3<Float>(0, 1, 0)
        let mitte = CGPoint(x: 400, y: 300)
        let d0 = SIMD3<Float>(0, 1, 0)
        nah(SimGriff.trackball(d0, von: mitte, nach: mitte, mitte: mitte, radius: 100, rechts: rechts, oben: oben,
                               blick: blick), d0, 1e-5, "ohne Bewegung unverändert")
        // Maus 50 Punkte nach rechts (halber Radius): das Pfeilende folgt auf die Kugel bei (0,5; 0; 0,866) im
        // Kamerasystem, also Welt (0,5; −0,866; 0); die Kraft zeigt vom Pfeilende zum Punkt
        let d1 = SimGriff.trackball(d0, von: mitte, nach: CGPoint(x: 450, y: 300), mitte: mitte, radius: 100,
                                    rechts: rechts, oben: oben, blick: blick)
        nah(d1, SIMD3<Float>(-0.5, Float(0.75).squareRoot(), 0), 1e-4)
        // weiter über den Rand der Kugel hinaus: dreht weiter, das Pfeilende kommt hinter die Kugel (vom Betrachter
        // weg, Kraft zeigt zum Betrachter)
        // 150 Punkte (1,5 Radien): 135° gedreht, das Pfeilende liegt hinter der Kugel bei (0,707; 0,707; 0)
        var d = d0
        var p = mitte
        for _ in 0..<15 {
            let q = CGPoint(x: p.x + 10, y: p.y)
            d = SimGriff.trackball(d, von: p, nach: q, mitte: mitte, radius: 100, rechts: rechts, oben: oben, blick: blick)
            p = q
        }
        nah(d, SIMD3<Float>(-Float(0.5).squareRoot(), -Float(0.5).squareRoot(), 0), 1e-3, "hinter die Kugel gedreht")
        XCTAssertEqual(simd_length(d), 1, accuracy: 1e-4)
        // am Rand stetig
        let innen = SimGriff.kugelpunkt(CGPoint(x: 400 + 99.9, y: 300), mitte: mitte, radius: 100)
        let aussen = SimGriff.kugelpunkt(CGPoint(x: 400 + 100.1, y: 300), mitte: mitte, radius: 100)
        XCTAssertLessThan(simd_length(innen - aussen), 0.05)
    }

    func testRingeUndEinrasten() {
        let P = SIMD3<Float>(0, 0, 0), L: Float = 100
        let d = simd_normalize(SIMD3<Float>(1, 0, -1))  // Pfeilende oben links: (−70,7; 0; 70,7)
        let ende = P - d * L
        let breite = SimGriff.breitenkreis(punkt: P, richtung: d, laenge: L)
        XCTAssertTrue(breite.allSatisfy { abs($0.z - ende.z) < 1e-3 }, "waagrecht in der Höhe des Pfeilendes")
        XCTAssertLessThan(breite.map { simd_length($0 - ende) }.min() ?? 1, 1e-2, "durch das Pfeilende")
        let meridian = SimGriff.meridian(punkt: P, richtung: d, laenge: L)
        XCTAssertLessThan(meridian.map { simd_length($0 - ende) }.min() ?? 1, 1e-2, "durch das Pfeilende")
        XCTAssertTrue(meridian.allSatisfy { abs($0.y) < 1e-3 && abs(simd_length($0) - L) < 1e-2 })
        // Breitenkreis ziehen: Blickstrahl von oben durch (0, 100, 0) → Pfeilende bei +Y, Kraft waagrecht nach −Y
        let d0 = SIMD3<Float>(1, 0, 0)
        let az = SimGriff.azimutZiehen(d0: d0, punkt: P, laenge: L, strahl: SIMD3(0, 100, 1000), SIMD3(0, 0, -1),
                                       bisher: d0)
        nah(az, SIMD3(0, -1, 0), 1e-2, "nur der Azimut")
        // Höhe bleibt beim Azimut
        let schraeg = simd_normalize(SIMD3<Float>(1, 0, -1))
        let az2 = SimGriff.azimutZiehen(d0: schraeg, punkt: P, laenge: L, strahl: SIMD3(0, 70.71, 1000),
                                        SIMD3(0, 0, -1), bisher: schraeg)
        XCTAssertEqual(az2?.z ?? 0, schraeg.z, accuracy: 1e-4)
        // Meridian ziehen: Blick von vorn auf den höchsten Punkt → Pfeilende oben, Kraft senkrecht nach unten
        let h = SimGriff.hoeheZiehen(d0: d0, punkt: P, laenge: L, strahl: SIMD3(0, -1000, 100), SIMD3(0, 1, 0),
                                     bisher: d0)
        nah(h, SIMD3(0, 0, -1), 1e-2, "nur die Höhe")
        // Einrasten: Normale vor Achse, unter 6°; ⌘ macht der Controller
        let fast = simd_normalize(SIMD3<Float>(0.05, 0, -1))
        XCTAssertEqual(SimGriff.einrasten(fast, normale: nil)?.ziel, .achse("-z"))
        XCTAssertEqual(SimGriff.einrasten(fast, normale: SIMD3(0, 0, 1))?.ziel, .normale(umgekehrt: false))
        XCTAssertEqual(SimGriff.einrasten(-fast, normale: SIMD3(0, 0, 1))?.ziel, .normale(umgekehrt: true))
        XCTAssertNil(SimGriff.einrasten(simd_normalize(SIMD3<Float>(0.3, 0, -1)), normale: nil), "17° zu weit")
        nah(SimGriff.einrasten(fast, normale: nil)?.richtung, SIMD3(0, 0, -1))
        let r = SimGriff.richtung(SIMD3(0, 0, -1), ziel: .achse("-z"), alt: SimRichtung(art: .frei))
        XCTAssertEqual(r.art, .achse)
        XCTAssertEqual(r.achse, "-z")
        let n = SimGriff.richtung(SIMD3(0, 0, 1), ziel: .normale(umgekehrt: true), alt: SimRichtung())
        XCTAssertEqual(n.art, .normale)
        XCTAssertTrue(n.umkehren)
        let f = SimGriff.richtung(simd_normalize(SIMD3(1, 1, 0)), ziel: nil, alt: SimRichtung())
        XCTAssertEqual(f.art, .frei)
        XCTAssertEqual(f.azimut, 45, accuracy: 0.05)
        XCTAssertEqual(f.hoehe, 0, accuracy: 0.05)
        XCTAssertEqual(SimGriff.Ziel.achse("-z").titel, "−Z")
        // Abstand zum Linienzug auf dem Bildschirm
        let linie = [CGPoint(x: 0, y: 0), CGPoint(x: 100, y: 0)]
        XCTAssertEqual(SimGriff.abstand(CGPoint(x: 50, y: 4), linie: linie), 4, accuracy: 1e-9)
    }

    // MARK: Controller

    @MainActor
    private func controller() throws -> AppController {
        let c = AppController(model: AppModel())
        let events = try FrameReader().feed(Fixtures.data("stream.bin")).map(KernelConnection.decode)
        c.handle(Array(events.prefix(7)))  // HELLO, PROJECT, Lauf mit Grundplatte und Halter/Bolzen
        guard case .simulation(let s) = try Fixtures.message("sim.frame") else { throw XCTSkip("kein SIM") }
        c.handle([.message(.simulation(s))])
        c.setSimulationAktiv(true)
        return c
    }

    @MainActor
    func testKanteSetztGleitrichtungUndLagerJeLastfall() throws {
        let c = try controller()
        let st = c.model.simulation
        // Einstellung für das nächste Lager: nur im gewählten Lastfall
        st.lagerSzenarien = ["Aufstützen 30 kg"]
        c.setSimulationWerkzeug(.lager)
        st.lagerArt = .gleitend
        XCTAssertTrue(c.simulationKlickAufFlaeche(teil: "Grundplatte", flaeche: 5))
        var e = try XCTUnwrap(st.lagerEntwurf)
        XCTAssertEqual(e.szenarien, ["Aufstützen 30 kg"], "Entwurf übernimmt die Lastfälle")
        XCTAssertNil(e.gleiten)
        // gerade Kante der Grundplatte: Gleitrichtung entlang ihr (Weltlage)
        let rec = try XCTUnwrap(c.scene.record("Grundplatte"))
        let k = try XCTUnwrap(rec.header.edges.indices.first { rec.header.edges[$0].t == "line" })
        let M = c.scene.worldTransform("Grundplatte")
        let poly = rec.geometry.edgePolyline(k).map { p -> SIMD3<Float> in
            let w = M * SIMD4(p, 1)
            return SIMD3(w.x, w.y, w.z)
        }
        let soll = simd_normalize(try XCTUnwrap(poly.last) - (try XCTUnwrap(poly.first)))
        st.kanteWaehlen = true
        c.simulationKanteGewaehlt(teil: "Grundplatte", kante: k)
        e = try XCTUnwrap(st.lagerEntwurf)
        XCTAssertFalse(st.kanteWaehlen)
        XCTAssertEqual(e.art, .gleitend)
        XCTAssertEqual(e.gleiten?.quelle, "kante")
        XCTAssertEqual(e.gleiten?.kante, k)
        nah(e.gleiten?.richtung, soll)
        XCTAssertEqual(e.json["gleiten"]?["kante"]?.intValue, k)
        XCTAssertTrue(c.scene.simulationBodies.contains { $0.id == "\(AppController.simulationPraefix)aeg" },
                      "Doppelpfeil der Schiene am Lagersymbol")
        // Werkzeug wechseln beendet „Kante wählen“
        st.kanteWaehlen = true
        c.setSimulationWerkzeug(.kraft)
        XCTAssertFalse(st.kanteWaehlen)
        // Lager, die im gewählten Lastfall nicht gelten, sind blass
        c.waehleLastfall("Bremsen aus 1 m/s")
        let a1 = try XCTUnwrap(c.scene.simulationBodies.first { $0.id == "\(AppController.simulationPraefix)a1k" })
        let a0 = try XCTUnwrap(c.scene.simulationBodies.first { $0.id == "\(AppController.simulationPraefix)a0k" })
        XCTAssertLessThan(a1.color.w, 0.5, "A2 gilt nur in „Aufstützen 30 kg“")
        XCTAssertEqual(a0.color.w, 1, accuracy: 1e-6)
        c.waehleLastfall("Aufstützen 30 kg")
        let a1b = try XCTUnwrap(c.scene.simulationBodies.first { $0.id == "\(AppController.simulationPraefix)a1k" })
        XCTAssertEqual(a1b.color.w, 1, accuracy: 1e-6)
        // Last auf der ganzen Fläche als Druck: Kraft = p · A (A aus der Signatur), Fläche getönt, Pfeile verteilt
        c.setSimulationWerkzeug(.kraft)
        XCTAssertTrue(c.simulationKlickAufFlaeche(teil: "Grundplatte", flaeche: 5))
        var k2 = try XCTUnwrap(st.entwurf)
        k2.last.verteilung = "flaeche"
        k2.last.einheit = SimKraft.druck
        k2.last.betrag = 0.01
        k2.last.richtung = SimRichtung(art: .normale)
        c.setKraftEntwurf(k2)
        let a = try XCTUnwrap(k2.last.flaecheMm2)
        XCTAssertEqual(Double(simd_length(try XCTUnwrap(st.entwurf?.kraft))), 0.01 * a, accuracy: 1e-3 * a)
        let ids = c.scene.simulationBodies.map(\.id)
        XCTAssertTrue(ids.contains { $0.hasPrefix("\(AppController.simulationPraefix)ef") })
        XCTAssertTrue(ids.contains { $0.hasPrefix("\(AppController.simulationPraefix)efp") }, "kleine Pfeile")
        XCTAssertFalse(ids.contains("\(AppController.simulationPraefix)era"), "Druck: kein Griff")
        XCTAssertFalse(c.simulationGriffBeginnt(CGPoint(x: 1, y: 1)))
    }

    @MainActor
    func testGriffRingeKugelUndBildschirmfest() throws {
        let c = try controller()
        let st = c.model.simulation
        defer { c.setPfeileBildschirmfest(false) }
        c.setPfeileBildschirmfest(false)
        c.setSimulationWerkzeug(.kraft)
        XCTAssertTrue(c.simulationKlickAufFlaeche(teil: "Grundplatte", flaeche: 5))
        var e = try XCTUnwrap(st.entwurf)
        e.last.richtung = SimRichtung(art: .frei, azimut: 30, hoehe: -40)
        c.setKraftEntwurf(e)
        let ids = Set(c.scene.simulationBodies.map(\.id))
        XCTAssertTrue(ids.contains("\(AppController.simulationPraefix)era"), "Ring Azimut")
        XCTAssertTrue(ids.contains("\(AppController.simulationPraefix)erh"), "Ring Höhe")
        // Ring Azimut anfassen (Viertelkreis vom Pfeilende entfernt) und ziehen: nur der Azimut ändert sich
        let ringe = try XCTUnwrap(c.simGriffRinge())
        let ende = try XCTUnwrap(c.simGriffPunkt())
        let fern = try XCTUnwrap(ringe.azimut.max { simd_length($0 - ende) < simd_length($1 - ende) })
        let anfassen = ringe.azimut.min { abs(simd_length($0 - ende) - simd_length(fern - ende) * 0.7071)
            < abs(simd_length($1 - ende) - simd_length(fern - ende) * 0.7071) }!
        let p0 = try XCTUnwrap(c.viewport.bildpunkt(anfassen))
        XCTAssertTrue(c.simulationGriffBeginnt(p0))
        XCTAssertEqual(st.griffArt, .ringAzimut)
        let p1 = try XCTUnwrap(c.viewport.bildpunkt(fern))
        c.simulationGriffZiehen(p1)
        let r1 = try XCTUnwrap(st.entwurf?.last.richtung)
        XCTAssertEqual(r1.art, .frei)
        XCTAssertEqual(r1.hoehe, -40, accuracy: 0.2, "Höhe bleibt")
        XCTAssertGreaterThan(abs(r1.azimut - 30), 20, "Azimut gedreht: \(r1.azimut)")
        c.viewport.onGriffEnde?(p1)
        XCTAssertFalse(st.griffAktiv)
        XCTAssertEqual(st.griffArt, .keins)
        // Kugel am Pfeilende: frei im Raum, Azimut und Höhe ändern sich
        let g = try XCTUnwrap(c.viewport.bildpunkt(try XCTUnwrap(c.simGriffPunkt())))
        XCTAssertTrue(c.simulationGriffBeginnt(g))
        XCTAssertEqual(st.griffArt, .kugel)
        var p = g
        for _ in 0..<6 {
            p = CGPoint(x: p.x + 9, y: p.y + 7)
            c.simulationGriffZiehen(p)
        }
        let r2 = try XCTUnwrap(st.entwurf?.last.richtung)
        if r2.art == .frei {
            XCTAssertGreaterThan(abs(r2.azimut - r1.azimut) + abs(r2.hoehe - r1.hoehe), 5, "frei gedreht")
        }
        c.simulationGriffEnde()
        // Einrasten über den Griff: Richtung fast −Z, ein kleiner Zug rastet auf −Z bzw. die Normale ein
        e = try XCTUnwrap(st.entwurf)
        e.last.richtung = SimRichtung(art: .frei, azimut: 0, hoehe: -86)
        c.setKraftEntwurf(e)
        let g2 = try XCTUnwrap(c.viewport.bildpunkt(try XCTUnwrap(c.simGriffPunkt())))
        XCTAssertTrue(c.simulationGriffBeginnt(g2))
        c.simulationGriffZiehen(CGPoint(x: g2.x + 0.5, y: g2.y))
        XCTAssertNotNil(st.eingerastet, "unter 6° eingerastet")
        let r3 = try XCTUnwrap(st.entwurf?.last.richtung)
        XCTAssertTrue(r3.art == .normale || (r3.art == .achse && r3.achse == "-z"), "\(r3)")
        c.viewport.griffModifiers = .command  // ⌘: ohne Einrasten
        c.simulationGriffZiehen(CGPoint(x: g2.x + 1, y: g2.y))
        XCTAssertNil(st.eingerastet)
        XCTAssertEqual(st.entwurf?.last.richtung.art, .frei)
        c.viewport.griffModifiers = []
        c.simulationGriffEnde()
        // Pfeile bildschirmfest: Länge folgt dem Zoom (halber Abstand → etwa halbe Länge in mm)
        let punkt = try XCTUnwrap(st.entwurf?.last.ort.punkt)
        let fest0 = c.simPfeilLaenge(bei: punkt)
        c.setPfeileBildschirmfest(true)
        let l1 = c.simPfeilLaenge(bei: punkt)
        let w1 = try XCTUnwrap(c.viewport.weltProPunkt(bei: punkt))
        XCTAssertEqual(l1, AppController.simPfeilPunkte * w1, accuracy: 1e-3 * l1)
        var cam = c.viewport.camera
        cam.pivot = punkt
        cam.distance *= 0.5
        cam.orthographicScale *= 0.5
        c.viewport.setCamera(cam)
        let l2 = c.simPfeilLaenge(bei: punkt)
        XCTAssertLessThan(l2, 0.8 * l1, "näher heran: kürzer in mm, gleich groß auf dem Bildschirm")
        let s1 = try XCTUnwrap(c.viewport.bildpunkt(punkt))
        let s2 = try XCTUnwrap(c.viewport.bildpunkt(punkt + simd_normalize(c.viewport.camera.rightVector) * l2))
        XCTAssertEqual(Float(hypot(s2.x - s1.x, s2.y - s1.y)), AppController.simPfeilPunkte, accuracy: 1)
        c.simulationKameraBewegt()
        XCTAssertFalse(st.bildschirmSchluessel.isEmpty)
        c.setPfeileBildschirmfest(false)
        XCTAssertEqual(c.simPfeilLaenge(bei: punkt), fest0, accuracy: 1e-3, "aus: wieder in Millimetern")
    }
}
