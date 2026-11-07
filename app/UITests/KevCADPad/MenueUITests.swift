import XCTest

/// Menüs am iPad (PLAN-IPAD.md 4.7, I-9) im Simulator: Die Menüs des Mac (app/Sources/KevCAD/Menues) liegen auch in der
/// Menüleiste des iPad, ihre Kürzel wirken über die Hardware-Tastatur (XCUITest `typeKey`). Dazu: In einem Textfeld
/// gehen einbuchstabige Kürzel ins Feld, nicht ans Menü (am Mac sorgt dafür `KeyboardGuard`).
///
/// Ein Test mit einem App-Start: Im Simulator wirken ⌘-Kürzel nur beim ersten App-Start eines Testlaufs (nach `terminate`
/// und neuem Start kamen sie nicht mehr an, Pfeiltasten schon; auch Tippen oder Home und zurück halfen nicht). Darum fährt
/// `tools/ipad-bau.sh gesten` diese Klasse in einem eigenen Lauf vor den Gesten-Tests.
///
/// Aufruf: tools/ipad-bau.sh gesten (alle Oberflächentests) bzw. `KEVCAD_IPAD_UITEST=MenueUITests tools/ipad-bau.sh gesten`.
final class MenueUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchEnvironment = [
            "KEVCAD_PAD_UITEST": "1",
            "KEVCAD_PAD_OHNE_KOPPLUNGSBLATT": "1",
            "KEVCAD_DEMO": "1",
            "KEVCAD_DEMO_VIEWPORT": "kern",
            "KEVCAD_DEMO_STATE": "live",
        ]
        app.launch()
    }

    override func tearDown() {
        app.terminate()
    }

    /// Zustand der App aus dem unsichtbaren Element (PadTestZustand.swift), wie in GestenUITests.
    private func zustand() -> [String: String] {
        let e = app.staticTexts["test.zustand"]
        guard e.exists else { return [:] }
        var out: [String: String] = [:]
        for teil in e.label.split(separator: ";", omittingEmptySubsequences: false) {
            let kv = teil.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            if kv.count == 2 { out[String(kv[0])] = String(kv[1]) }
        }
        return out
    }

    @discardableResult
    private func warte(_ beschreibung: String, frist: TimeInterval = 10,
                       _ bedingung: ([String: String]) -> Bool) -> [String: String] {
        let ende = Date().addingTimeInterval(frist)
        var z = zustand()
        while Date() < ende {
            z = zustand()
            if bedingung(z) { return z }
            RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        }
        XCTFail("\(beschreibung) – Zustand: \(z)")
        return z
    }

    private func bereit() -> [String: String] {
        XCTAssertTrue(app.staticTexts["test.zustand"].waitForExistence(timeout: 120), "App mit Testzustand gestartet")
        warte("Modell geladen", frist: 120) { Int($0["teile"] ?? "") ?? 0 > 0 }
        // Bis der Demo-Lauf fertig eingerahmt hat (Kamera ruhig): Vorher ist die App beschäftigt, und unter Last ging im
        // Simulator ein einzelner Tastendruck verloren. Menükürzel gelten für die Szene mit Fokus.
        var letzter = ""
        warte("Kamera ruhig", frist: 30) { z in
            defer { letzter = z["abstand"] ?? "" }
            return !(z["abstand"] ?? "").isEmpty && z["abstand"] == letzter
        }
        RunLoop.current.run(until: Date().addingTimeInterval(1.0))
        return zustand()
    }

    // MARK: Tests

    func testKuerzelDerMenuesUndTextfeld() {
        let start = bereit()

        // ⌘1 und ⌘2 (Darstellung): Objekte links, Eigenschaften rechts
        app.typeKey("1", modifierFlags: .command)
        let links = warte("⌘1 schaltet die Objekte links") { $0["links"] != start["links"] }
        app.typeKey("1", modifierFlags: .command)
        warte("⌘1 schaltet zurück") { $0["links"] == start["links"] }
        app.typeKey("2", modifierFlags: .command)
        warte("⌘2 schaltet die Eigenschaften rechts") { $0["rechts"] != links["rechts"] }

        // 5 ohne Umschalter (Darstellung › Perspektive bzw. Parallelprojektion), solange das Modell aktiv ist
        let ortho = zustand()["ortho"]
        app.typeKey("5", modifierFlags: [])
        warte("5 wechselt die Projektion") { $0["ortho"] != ortho }

        // ⌃⌘3 (Kacheln): Kachel Zeichnung zeigen (danach gehören einbuchstabige Tasten wie am Mac dem Blatt)
        app.typeKey("3", modifierFlags: [.command, .control])
        warte("⌃⌘3 zeigt die Kachel Zeichnung") { ($0["kacheln"] ?? "").split(separator: ",").contains("zeichnung") }

        // ⌥⌘L öffnet das Protokoll (am Mac ein Fenster, am iPad ein Blatt)
        app.typeKey("l", modifierFlags: [.command, .option])
        warte("⌥⌘L öffnet das Protokoll") { $0["blatt"] == "protokoll" }
        app.buttons["Fertig"].firstMatch.tap()
        warte("Protokoll geschlossen") { ($0["blatt"] ?? "x").isEmpty }

        // Ein Textfeld hat den Fokus: einbuchstabige Kürzel gehen ins Feld, nicht ans Menü (am Mac `KeyboardGuard`).
        // Im selben Test wie oben: ⌘-Kürzel kommen im Simulator nur beim ersten App-Start eines Testlaufs an.
        let vorher = zustand()
        // ⇧⌘S (Ablage › Sichern unter bzw. Umbenennen): Feld für den Projektnamen in der Kopfleiste
        app.typeKey("s", modifierFlags: [.command, .shift])
        warte("⇧⌘S kommt im Menü an", frist: 15) { $0["umbenennen"] != vorher["umbenennen"] }
        let feld = app.textFields.firstMatch
        XCTAssertTrue(feld.waitForExistence(timeout: 5), "⇧⌘S öffnet das Namensfeld")
        RunLoop.current.run(until: Date().addingTimeInterval(0.5))
        app.typeKey("5", modifierFlags: [])
        app.typeKey("h", modifierFlags: [])
        RunLoop.current.run(until: Date().addingTimeInterval(1.0))
        let wert = feld.value as? String ?? ""
        XCTAssertTrue(wert.hasSuffix("5h"), "Tasten landen im Feld (Wert „\(wert)“)")
        let z = zustand()
        XCTAssertEqual(z["ortho"], vorher["ortho"], "5 hat die Projektion nicht gewechselt")
        XCTAssertEqual(z["verborgen"], vorher["verborgen"], "H hat nichts ausgeblendet")
        app.typeKey(XCUIKeyboardKey.escape.rawValue, modifierFlags: [])
    }
}
