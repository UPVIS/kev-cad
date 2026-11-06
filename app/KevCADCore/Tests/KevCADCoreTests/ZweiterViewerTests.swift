#if os(macOS)
import AppKit
#endif
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// V2-10: zweite Ansicht als zweiter Viewer (eigene Kamera, sonst alles wie der Hauptviewer) und das Blatt der Zeichnung,
/// das dem Zusammenhang folgt.
@MainActor
final class ZweiterViewerTests: XCTestCase {
    /// Lauf mit zwei Teilen aus stream.bin (wie ControllerTests).
    private func controller() throws -> AppController {
        let c = AppController(model: AppModel())
        let events = try FrameReader().feed(Fixtures.data("stream.bin")).map(KernelConnection.decode)
        c.handle(Array(events.prefix(7)))
        return c
    }

    /// Kachelfläche mit Modell und zweiter Ansicht, die Ansicht ist eingehängt.
    private func zeigeZweiteAnsicht(_ c: AppController) {
        c.oberflaeche(.kachelnOrdnen([.modell, .ansicht]))
        c.zweiterViewer.setOffen(true)
        c.zweiterViewer.coordinator.viewSize = CGSize(width: 600, height: 400)
    }

    private func gleicheRichtung(_ a: CameraState, _ b: StandardView) -> Bool {
        abs(simd_dot(a.rotation.vector, b.rotation.vector)) > 0.999
    }

    func testSpiegeltKoerperUndUeberlagerung() throws {
        let c = try controller()
        XCTAssertFalse(c.viewport.bodies.isEmpty)
        XCTAssertEqual(c.zweiterViewer.coordinator.bodies.map(\.id), c.viewport.bodies.map(\.id))
        c.viewport.setOverlay([.polyline(points: [.zero, SIMD3(10, 0, 0)], color: ViewerStil.strich, width: 2)])
        XCTAssertEqual(c.zweiterViewer.coordinator.overlayItems.count, 1, "Maße und Striche erscheinen in beiden Viewern")
        c.viewport.controller.clipPlanes = [ClipPlane(normal: SIMD3(0, 0, 1), distance: 5)]
        XCTAssertEqual(c.zweiterViewer.coordinator.controller.clipPlanes.count, 1, "der Schnitt gilt in beiden")
    }

    func testNimmtNurEingabenAnWennZuSehen() throws {
        let c = try controller()
        let z = c.zweiterViewer
        XCTAssertFalse(z.aktiv)
        XCTAssertFalse(z.coordinator.eingabeAktiv, "verborgen eingehängt: keine Maus, keine Tasten")
        zeigeZweiteAnsicht(c)
        XCTAssertTrue(z.aktiv)
        XCTAssertTrue(z.coordinator.eingabeAktiv)
        c.oberflaeche(.kachelGross(.modell))
        XCTAssertFalse(z.aktiv, "Modell groß: die Kachel ist verborgen")
        XCTAssertFalse(z.coordinator.eingabeAktiv)
        z.coordinator.letzteMaus = CGPoint(x: 10, y: 10)
        XCTAssertTrue(c.eingabeViewport === c.viewport, "eine verborgene zweite Ansicht bekommt keine Tasten")
        c.oberflaeche(.kachelGross(nil))
        XCTAssertTrue(z.aktiv)
        XCTAssertTrue(c.eingabeViewport === z.coordinator)
    }

    func testTastenWirkenImViewerUnterDerMaus() throws {
        let c = try controller()
        zeigeZweiteAnsicht(c)
        let z = c.zweiterViewer.coordinator
        let vorher = c.viewport.kameraZiel
        z.letzteMaus = CGPoint(x: 100, y: 100)
        c.axisView(.top)  // Ziffernblock 7 über dem zweiten Viewer
        XCTAssertTrue(gleicheRichtung(z.kameraZiel, .top))
        XCTAssertEqual(c.viewport.kameraZiel.rotation.vector, vorher.rotation.vector, "der Hauptviewer bleibt stehen")
        c.zoomStep(1)
        XCTAssertEqual(c.viewport.kameraZiel.distance, vorher.distance, accuracy: 1e-4)

        z.letzteMaus = nil
        XCTAssertTrue(c.eingabeViewport === c.viewport)
        c.axisView(.front)
        XCTAssertTrue(gleicheRichtung(c.viewport.kameraZiel, .front))
        XCTAssertTrue(gleicheRichtung(z.kameraZiel, .top), "die zweite Ansicht bleibt, wie Kevin sie verlassen hat")
    }

    func testRichtungDerKachelStelltDieKameraEin() throws {
        let c = try controller()
        zeigeZweiteAnsicht(c)
        c.zweiteAnsichtStellen(animiert: false)
        let z = c.zweiterViewer.coordinator
        XCTAssertTrue(gleicheRichtung(z.camera, .top), "Vorgabe der Kachel: von oben")
        XCTAssertTrue(z.camera.isOrthographic)
        XCTAssertTrue(c.zweiterViewer.eingepasst)
        c.oberflaeche(.zweiteAnsicht("iso"))
        XCTAssertTrue(gleicheRichtung(z.kameraZiel, .isometricFrontRight))
        XCTAssertFalse(z.kameraZiel.isOrthographic, "Iso perspektivisch wie bisher")
    }

    func testMessVorschauNurImViewerUnterDerMaus() throws {
        let c = try controller()
        zeigeZweiteAnsicht(c)
        let z = c.zweiterViewer.coordinator
        z.letzteMaus = CGPoint(x: 5, y: 5)
        c.unterMausSetzen("Kante 12,00 mm")
        XCTAssertEqual(z.eingabe.unterMaus, "Kante 12,00 mm")
        XCTAssertNil(c.viewport.eingabe.unterMaus)
        z.letzteMaus = nil
        c.unterMausSetzen(nil)
        XCTAssertNil(z.eingabe.unterMaus)
    }

    func testZeichnenGiltInBeidenViewern() throws {
        let c = try controller()
        c.zeichnenSetzen(true)
        XCTAssertTrue(c.viewport.zeichnen && c.zweiterViewer.coordinator.zeichnen)
        c.zeichnenSetzen(false)
        XCTAssertFalse(c.viewport.zeichnen || c.zweiterViewer.coordinator.zeichnen)
    }

    // MARK: Blatt folgt dem Zusammenhang

    private let blaetter = [
        BlattEintrag(id: "zusammenbau", titel: "Zusammenbau", inhaltArt: "zusammenbau"),
        BlattEintrag(id: "rohr", titel: "Rohr", teile: ["Rahmen/Rohr 1"]),
        BlattEintrag(id: "platte", titel: "Platte", teile: ["Platte"]),
        BlattEintrag(id: "rahmen", titel: "Rahmen", inhaltArt: "baugruppe", teile: ["Rahmen"]),
        BlattEintrag(id: "ecke", titel: "Ecke", inhaltArt: "baugruppe", teile: ["Rahmen/Ecke"]),
    ]
    private let gleiche = [["Rahmen/Rohr 1", "Rahmen/Rohr 2", "Rahmen/Rohr 3"], ["Platte"], ["Schraube 1", "Schraube 2"]]

    func testBlattwahlEinTeil() {
        XCTAssertEqual(Blattwahl.blatt(fuer: ["Platte"], in: blaetter, gleiche: gleiche), "platte")
        XCTAssertEqual(Blattwahl.blatt(fuer: ["Rahmen/Rohr 3"], in: blaetter, gleiche: gleiche), "rohr",
                       "gleiche Teile teilen sich das Blatt, das nur das erste nennt")
        XCTAssertEqual(Blattwahl.blatt(fuer: ["Rahmen/Rohr 1", "Rahmen/Rohr 2"], in: blaetter, gleiche: gleiche), "rohr")
    }

    func testBlattwahlBaugruppeUndZusammenbau() {
        XCTAssertEqual(Blattwahl.blatt(fuer: ["Rahmen/Rohr 1", "Rahmen/Ecke/Winkel"], in: blaetter, gleiche: gleiche),
                       "rahmen")
        XCTAssertEqual(Blattwahl.blatt(fuer: ["Rahmen/Ecke/Winkel", "Rahmen/Ecke/Blech"], in: blaetter, gleiche: gleiche),
                       "ecke", "die engste Baugruppe")
        XCTAssertEqual(Blattwahl.blatt(fuer: ["Schraube 1"], in: blaetter, gleiche: gleiche), "zusammenbau",
                       "Zukaufteil ohne eigenes Blatt: im Zusammenhang")
        XCTAssertEqual(Blattwahl.blatt(fuer: ["Platte", "Rahmen/Rohr 1"], in: blaetter, gleiche: gleiche), "zusammenbau")
        XCTAssertNil(Blattwahl.blatt(fuer: [], in: blaetter, gleiche: gleiche))
        XCTAssertNil(Blattwahl.blatt(fuer: ["Platte"], in: [], gleiche: gleiche))
    }

    func testBlattFolgtDerAuswahlUndLaesstSichFesthalten() throws {
        let c = try controller()
        let teile = c.scene.order
        XCTAssertGreaterThanOrEqual(teile.count, 2)
        c.model.dokumente.uebersicht = DocsUebersicht(blaetter: [
            BlattEintrag(id: "zb", titel: "Zusammenbau", inhaltArt: "zusammenbau"),
            BlattEintrag(id: "a", titel: "A", teile: [teile[0]]),
            BlattEintrag(id: "b", titel: "B", teile: [teile[1]]),
        ])
        c.select([teile[1]])
        XCTAssertNil(c.model.oberflaeche.blatt, "ohne Kachel Zeichnung wechselt nichts")

        c.oberflaeche(.kachelZeigen(.zeichnung))
        c.select([teile[1]])
        XCTAssertEqual(c.model.oberflaeche.blatt, "b")
        c.select([teile[0]])
        XCTAssertEqual(c.model.oberflaeche.blatt, "a")
        c.select(teile)
        XCTAssertEqual(c.model.oberflaeche.blatt, "zb")
        c.select([])
        XCTAssertEqual(c.model.oberflaeche.blatt, "zb", "nichts gewählt: das Blatt bleibt")

        c.oberflaeche(.blattFolgt(false))
        c.select([teile[0]])
        XCTAssertEqual(c.model.oberflaeche.blatt, "zb", "festgehalten")
        c.oberflaeche(.blattFolgt(true))

        // Kamerabefehl des Agenten: das Blatt zeigt, wovon er spricht
        c.zweiteAnsichtFolgt(ViewCommandMessage(id: "v1", cmd: "focus", args: .object(["refs": .array([.string(teile[1])])])))
        XCTAssertEqual(c.model.oberflaeche.blatt, "b")
    }

    func testOberflaecheKenntSichtbarkeitUndFesthalten() {
        var z = OberflaechenZustand()
        XCTAssertFalse(z.zweiteAnsichtSichtbar)
        z.anwenden(.kachelZeigen(.ansicht))
        XCTAssertTrue(z.zweiteAnsichtSichtbar)
        z.anwenden(.kachelZeigen(.druck))
        z.anwenden(.kachelGross(.druck))
        XCTAssertFalse(z.zweiteAnsichtSichtbar, "eine andere Kachel ist groß")
        z.anwenden(.kachelGross(.ansicht))
        XCTAssertTrue(z.zweiteAnsichtSichtbar)
        z.anwenden(.rand(.rechts))
        XCTAssertFalse(z.zweiteAnsichtSichtbar, "am Rand steht nur der Viewer")
        XCTAssertTrue(z.blattFolgt)
        z.anwenden(.blattFolgt(false))
        XCTAssertFalse(z.blattFolgt)
    }
}

/// Kachel Bauplan, die über einen Projektwechsel eingehängt bleibt (06.11.2026): Nennt DOCS einen Bauplan und ist noch
/// keiner geladen, holt die offene Kachel ihn.
@MainActor
final class KachelBauplanTests: XCTestCase {
    private func docs() throws -> DokumenteMessage {
        guard case .dokumente(let m) = try Fixtures.message("docs_bauplan.frame") else {
            throw XCTSkip("docs_bauplan.frame ohne DOCS")
        }
        return m
    }

    func testOffeneKachelHoltDenBauplan() throws {
        let c = AppController(model: AppModel())
        c.oberflaeche(.kachelnOrdnen([.modell, .bauplan]))
        XCTAssertNil(c.model.bauplan.angefordert)
        c.bauplanNachDocs(try docs())
        XCTAssertNotNil(c.model.bauplan.angefordert, "die Kachel fragt den Plan an")
    }

    func testOhneKachelBleibtEsBeiDerUebersicht() throws {
        let c = AppController(model: AppModel())
        c.bauplanNachDocs(try docs())
        XCTAssertNil(c.model.bauplan.angefordert, "ohne Kachel Bauplan nichts laden")
    }
}

