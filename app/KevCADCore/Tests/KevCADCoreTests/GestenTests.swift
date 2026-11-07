import XCTest

@testable import KevCADCore

/// I-3b (PLAN-IPAD.md, 4.6): Die Hinweisleiste und die Übersicht am iPad lesen die Gesten aus `Tastenbelegung.gesten`,
/// derselben Quelle wie die Maus am Mac. Läuft auf beiden Plattformen.
final class GestenTests: XCTestCase {
    func testJedeGesteBeschriebenUndJeZustandEinmal() {
        let ids = Tastenbelegung.gesten.map(\.id)
        XCTAssertEqual(Set(ids).count, ids.count, "eine Geste steht je Zustand höchstens einmal in der Liste")
        XCTAssertEqual(Set(Tastenbelegung.gesten.map(\.geste)), Set(GestenBelegung.Geste.allCases),
                       "jede Geste der Eingabeebene hat eine Beschreibung")
        for g in Tastenbelegung.gesten {
            XCTAssertFalse(g.wirkung.isEmpty, g.id)
            XCTAssertFalse(g.eingabe.isEmpty, g.id)
        }
    }

    func testWichtigsteGestenZuerst() {
        // Bei wenig Platz bleiben in der Leiste die vorderen stehen: Drehen, Verschieben, Zoom, Auswählen
        let auswahl = Tastenbelegung.gesten.filter { $0.zustand == .immer || $0.zustand == .auswahl }.map(\.geste)
        XCTAssertEqual(Array(auswahl.prefix(4)), [.einFinger, .zweiFinger, .spreizen, .tippen])
        let messen = Tastenbelegung.gesten.filter { $0.zustand == .messen }
        XCTAssertEqual(messen.map(\.geste), [.tippen], "im Messmodus misst der Tipp")
        let sprechen = Tastenbelegung.gesten.filter { $0.zustand == .sprechen }
        XCTAssertEqual(sprechen.map(\.geste), [.stift], "beim Sprechen zeichnet der Stift")
    }
}
