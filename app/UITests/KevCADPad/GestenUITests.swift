import XCTest

/// Gesten am iPad (PLAN-IPAD.md 4.2, I-3b) im Simulator: Tippen, Doppeltippen, langes Drücken, 2 und 3 Finger tippen,
/// vom Rand wischen. Die App läuft im Demo-Lauf des App-Kerns (Wandhalter mit echter Geometrie) und legt mit
/// `KEVCAD_PAD_UITEST=1` ihren Zustand in den Bedienbaum (PadTestZustand.swift).
///
/// Aufruf: tools/ipad-bau.sh gesten (unter der Simulator-Sperre, ohne Simulatorfenster).
final class GestenUITests: XCTestCase {
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
        // Fester Ausgangszustand: Der Simulator ist geteilt, die App merkt sich Leisten und Kacheln (UserDefaults). Die
        // Argumente gehen dem Gemerkten vor: Gliederung an, Eigenschaften zu, nur das Modell, Schwung an.
        app.launchArguments = ["-oberflaeche.leisten", "(links)", "-oberflaeche.kacheln", "(modell)",
                               "-viewer.schwung", "YES"]
        app.launch()
    }

    override func tearDown() {
        app.terminate()
    }

    // MARK: Zustand der App

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

    /// Wartet, bis `bedingung` für den Zustand gilt (höchstens `frist` Sekunden).
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

    /// Modell geladen und die Kamera ruhig (der Demo-Lauf rahmt am Ende ein).
    private func bereit() -> [String: String] {
        XCTAssertTrue(app.staticTexts["test.zustand"].waitForExistence(timeout: 120), "App mit Testzustand gestartet")
        warte("Modell geladen", frist: 120) { Int($0["teile"] ?? "") ?? 0 > 0 }
        var letzter = ""
        return warte("Kamera ruhig", frist: 30) { z in
            defer { letzter = z["abstand"] ?? "" }
            return !(z["abstand"] ?? "").isEmpty && z["abstand"] == letzter
        }
    }

    /// Der Viewer (Eingabeebene über dem Metal-Bild, TouchNavigation.swift).
    private var viewer: XCUIElement { app.descendants(matching: .any)["viewer"].firstMatch }

    /// Punkt im Fenster, unter dem ein Teil liegt: Tippen in der Mitte, sonst um sie herum suchen.
    private func punktAufTeil() -> XCUICoordinate? {
        let versuche: [(CGFloat, CGFloat)] = [(0.5, 0.5), (0.5, 0.45), (0.45, 0.5), (0.55, 0.5), (0.5, 0.55), (0.5, 0.4),
                                              (0.4, 0.5), (0.6, 0.5), (0.5, 0.6)]
        for (x, y) in versuche {
            let p = app.windows.firstMatch.coordinate(withNormalizedOffset: CGVector(dx: x, dy: y))
            p.tap()
            RunLoop.current.run(until: Date().addingTimeInterval(1.0))
            if !(zustand()["auswahl"] ?? "").isEmpty { return p }
        }
        return nil
    }

    // MARK: Tests

    func testTippenDoppeltippenUndRueckgaengig() throws {
        let start = bereit()
        guard let teil = punktAufTeil() else {
            XCTFail("kein Teil unter der Bildmitte gefunden")
            return
        }
        let gewaehlt = warte("Tippen wählt ein Teil") { !($0["auswahl"] ?? "").isEmpty }
        XCTAssertEqual(start["auswahl"], "", "vorher nichts gewählt")

        // Doppeltippen rahmt das Teil ein: die Kamera rückt näher
        teil.doubleTap()
        warte("Doppeltippen rahmt ein") { $0["abstand"] != gewaehlt["abstand"] && !($0["abstand"] ?? "").isEmpty }
        var vorig = ""
        let nah = warte("Kamera nach dem Einrahmen ruhig") { z in  // nicht mitten in der Fahrt lesen
            defer { vorig = z["abstand"] ?? "" }
            RunLoop.current.run(until: Date().addingTimeInterval(0.6))
            return z["abstand"] == vorig
        }
        warte("Schritt im Verlauf", frist: 5) { !($0["rueck"] ?? "").isEmpty }

        // 2 Finger tippen: zurück (die Ansicht vor dem Einrahmen), 3 Finger tippen: wieder vor
        try Mehrfinger.tippen(2, auf: viewer)
        warte("2 Finger tippen nimmt das Einrahmen zurück") {
            $0["abstand"] == gewaehlt["abstand"] && !($0["wieder"] ?? "").isEmpty
        }
        try Mehrfinger.tippen(3, auf: viewer)
        // Die kurze Meldung („Wiederholt …“) kann unter Last schon wieder weg sein; der Verlauf zählt
        warte("3 Finger tippen wiederholt (erwartet Abstand \(nah["abstand"] ?? "?"))") {
            $0["abstand"] == nah["abstand"] && ($0["wieder"] ?? "x").isEmpty
        }

        // Die Knöpfe der Daumenleiste tun dasselbe
        let zurueck = app.buttons["daumen.rueckgaengig"]
        XCTAssertTrue(zurueck.waitForExistence(timeout: 5), "↶ in der Daumenleiste")
        zurueck.tap()
        warte("↶ nimmt zurück") { $0["abstand"] == gewaehlt["abstand"] }
        app.buttons["daumen.wiederholen"].tap()
        warte("↷ wiederholt") { $0["abstand"] == nah["abstand"] }
    }

    func testLangesDrueckenOeffnetKontextmenue() throws {
        _ = bereit()
        // Auf leerem Grund nichts gewählt: langes Drücken auf ein Teil wählt es und zeigt das Menü
        guard let teil = punktAufTeil() else {
            XCTFail("kein Teil unter der Bildmitte gefunden")
            return
        }
        // Auswahl zurücknehmen (2 Finger tippen), dann lange auf dasselbe Teil drücken
        try Mehrfinger.tippen(2, auf: viewer)
        warte("Auswahl zurückgenommen") { ($0["auswahl"] ?? "x").isEmpty }
        teil.press(forDuration: 1.2)
        let ausblenden = app.descendants(matching: .any)["kontext.ausblenden"]
        XCTAssertTrue(ausblenden.waitForExistence(timeout: 8), "Kontextmenü mit „Ausblenden“")
        XCTAssertTrue(app.descendants(matching: .any)["kontext.isolieren"].exists, "… und „Lokale Ansicht“")
        let z = warte("das gedrückte Teil ist gewählt") { !($0["auswahl"] ?? "").isEmpty }
        XCTAssertTrue(ausblenden.isEnabled)
        ausblenden.tap()
        warte("Ausblenden wirkt") { $0["verborgen"] == "1" }
        // Rückgängig holt das Teil zurück
        try Mehrfinger.tippen(2, auf: viewer)
        warte("2 Finger tippen blendet wieder ein") { $0["verborgen"] == "0" && $0["auswahl"] == z["auswahl"] }
    }

    func testMehrfachNimmtDazu() throws {
        _ = bereit()
        // Zwei Punkte auf verschiedenen Teilen suchen (ohne „Mehrfach“ ersetzt jeder Tipp die Auswahl)
        let fenster = app.windows.firstMatch
        var treffer: [(XCUICoordinate, String)] = []
        for (x, y) in [(0.5, 0.5), (0.3, 0.42), (0.44, 0.64), (0.58, 0.54), (0.6, 0.66), (0.35, 0.6), (0.25, 0.3)] {
            let p = fenster.coordinate(withNormalizedOffset: CGVector(dx: x, dy: y))
            p.tap()
            RunLoop.current.run(until: Date().addingTimeInterval(1.0))
            let a = zustand()["auswahl"] ?? ""
            if !a.isEmpty, !treffer.contains(where: { $0.1 == a }) { treffer.append((p, a)) }
            if treffer.count == 2 { break }
        }
        guard treffer.count == 2 else { return XCTFail("keine zwei Teile gefunden: \(treffer.map(\.1))") }
        treffer[0].0.tap()
        warte("erstes Teil gewählt") { $0["auswahl"] == treffer[0].1 }
        let knopf = app.buttons["daumen.mehrfach"]
        XCTAssertTrue(knopf.waitForExistence(timeout: 5), "„Mehrfach“ in der Daumenleiste")
        knopf.tap()
        warte("Mehrfach an") { $0["mehrfach"] == "1" }
        treffer[1].0.tap()
        warte("mit „Mehrfach“ nimmt Tippen das zweite Teil dazu") { $0["auswahl"] == "\(treffer[0].1),\(treffer[1].1)" }
        treffer[0].0.tap()
        warte("… und nimmt es wieder heraus") { $0["auswahl"] == treffer[1].1 }
        knopf.tap()
        warte("Mehrfach aus") { $0["mehrfach"] == "0" }
    }

    /// Winkel zwischen zwei Drehungen (Grad) aus „x,y,z,w“.
    private func winkel(_ a: String?, _ b: String?) -> Double {
        let q1 = (a ?? "").split(separator: ",").compactMap { Double($0) }
        let q2 = (b ?? "").split(separator: ",").compactMap { Double($0) }
        guard q1.count == 4, q2.count == 4 else { return .nan }
        let d = min(1, abs(zip(q1, q2).map(*).reduce(0, +)))
        return 2 * acos(d) * 180 / .pi
    }

    /// Wartet, bis die Kamera eine Sekunde lang ruhig ist, und gibt die Drehung zurück.
    private func ruhigeDrehung() -> String? {
        var letzte = ""
        return warte("Kamera ruhig", frist: 15) { z in
            defer { letzte = z["drehung"] ?? "" }
            RunLoop.current.run(until: Date().addingTimeInterval(0.6))
            return !(z["drehung"] ?? "").isEmpty && z["drehung"] == letzte
        }["drehung"]
    }

    /// Gleicher Weg, einmal langsam, einmal schnell: Schnell losgelassen dreht es mit Schwung deutlich weiter.
    func testSchwungDrehtNach() {
        _ = bereit()
        let fenster = app.windows.firstMatch
        let von = fenster.coordinate(withNormalizedOffset: CGVector(dx: 0.35, dy: 0.5))
        let bis = fenster.coordinate(withNormalizedOffset: CGVector(dx: 0.6, dy: 0.5))
        let a = ruhigeDrehung()
        von.press(forDuration: 0.05, thenDragTo: bis, withVelocity: .slow, thenHoldForDuration: 0.3)
        let b = ruhigeDrehung()
        von.press(forDuration: 0.05, thenDragTo: bis, withVelocity: .fast, thenHoldForDuration: 0)
        let c = ruhigeDrehung()
        let langsam = winkel(a, b), schnell = winkel(b, c)
        XCTAssertGreaterThan(langsam, 1, "langsames Ziehen dreht")
        XCTAssertGreaterThan(schnell, langsam * 1.2, "schnell losgelassen läuft es nach (langsam \(langsam)°, schnell \(schnell)°)")
    }

    func testPfeiltastenInDerGliederung() {
        _ = bereit()
        let zeile = app.buttons["Grundplatte"].firstMatch
        XCTAssertTrue(zeile.waitForExistence(timeout: 10), "Gliederung mit „Grundplatte“")
        zeile.tap()
        warte("Grundplatte gewählt") { $0["auswahl"] == "Grundplatte" }
        app.typeKey(XCUIKeyboardKey.downArrow, modifierFlags: [])
        warte("↓ wählt die nächste Zeile") { ($0["auswahl"] ?? "") != "Grundplatte" && !($0["auswahl"] ?? "").isEmpty }
        app.typeKey(XCUIKeyboardKey.upArrow, modifierFlags: [])
        warte("↑ wieder zurück") { $0["auswahl"] == "Grundplatte" }
    }

    func testVomRandWischenOeffnetLeisten() {
        let z = bereit()
        let fenster = app.windows.firstMatch
        if z["rechts"] == "0" {
            let von = fenster.coordinate(withNormalizedOffset: CGVector(dx: 0.999, dy: 0.5))
            von.press(forDuration: 0.05, thenDragTo: fenster.coordinate(withNormalizedOffset: CGVector(dx: 0.75, dy: 0.5)))
            warte("vom rechten Rand: Eigenschaften") { $0["rechts"] == "1" }
        }
        if z["links"] == "0" {
            let von = fenster.coordinate(withNormalizedOffset: CGVector(dx: 0.001, dy: 0.5))
            von.press(forDuration: 0.05, thenDragTo: fenster.coordinate(withNormalizedOffset: CGVector(dx: 0.25, dy: 0.5)))
            warte("vom linken Rand: Gliederung") { $0["links"] == "1" }
        }
    }
}

/// Tippen mit mehreren Fingern zugleich. `twoFingerTap()` und `tap(withNumberOfTaps:numberOfTouches:)` scheitern im
/// Simulator mit iPadOS 26 („Unable to compute coordinates for gesture“, auch an einem freien Element). Darum hier über die
/// Ereignis-Synthese von XCTest selbst (XCPointerEventPath, XCSynthesizedEventRecord; nur im Testziel, nie in der App).
enum Mehrfinger {
    /// Alle Finger setzen gleichzeitig auf und heben nach `dauer` Sekunden ab. Punkte in Bildschirmpunkten.
    static func tippen(_ punkte: [CGPoint], dauer: Double = 0.08) throws {
        guard let pfadKlasse = NSClassFromString("XCPointerEventPath"),
              let satzKlasse = NSClassFromString("XCSynthesizedEventRecord")
        else { throw XCTSkip("Ereignis-Synthese von XCTest fehlt") }
        typealias SatzInit = @convention(c) (AnyObject, Selector, NSString, Int64) -> AnyObject
        typealias PfadInit = @convention(c) (AnyObject, Selector, CGPoint, Double) -> AnyObject
        typealias Abheben = @convention(c) (AnyObject, Selector, Double) -> Void
        typealias Hinzu = @convention(c) (AnyObject, Selector, AnyObject) -> Void
        // Der Block geht als Objekt hinüber: als Blocktyp in einer C-Signatur gälte er als nicht entkommend (Absturz
        // „non-escaping closure has escaped“, weil XCTest ihn nach dem Aufruf festhält)
        typealias Ausloesen = @convention(c) (AnyObject, Selector, AnyObject, AnyObject) -> Void

        func neu(_ klasse: AnyClass) -> AnyObject {
            (klasse as AnyObject).perform(NSSelectorFromString("alloc")).takeUnretainedValue()
        }
        func imp<T>(_ objekt: AnyObject, _ name: String, _: T.Type) -> (T, Selector)? {
            let sel = NSSelectorFromString(name)
            guard let m = class_getInstanceMethod(object_getClass(objekt), sel) else { return nil }
            return (unsafeBitCast(method_getImplementation(m), to: T.self), sel)
        }

        let roh = neu(satzKlasse)
        guard let (satzInit, s1) = imp(roh, "initWithName:interfaceOrientation:", SatzInit.self) else {
            throw XCTSkip("XCSynthesizedEventRecord ohne initWithName:interfaceOrientation:")
        }
        let satz = satzInit(roh, s1, "Mehrfinger" as NSString, 1)
        for p in punkte {
            let pr = neu(pfadKlasse)
            guard let (pfadInit, s2) = imp(pr, "initForTouchAtPoint:offset:", PfadInit.self) else {
                throw XCTSkip("XCPointerEventPath ohne initForTouchAtPoint:offset:")
            }
            let pfad = pfadInit(pr, s2, p, 0)
            if let (abheben, s3) = imp(pfad, "liftUpAtOffset:", Abheben.self) { abheben(pfad, s3, dauer) }
            if let (hinzu, s4) = imp(satz, "addPointerEventPath:", Hinzu.self) { hinzu(satz, s4, pfad) }
        }
        let geraet = XCUIDevice.shared
        guard geraet.responds(to: NSSelectorFromString("eventSynthesizer")),
              let synth = geraet.perform(NSSelectorFromString("eventSynthesizer"))?.takeUnretainedValue(),
              let (ausloesen, s5) = imp(synth, "synthesizeEvent:completion:", Ausloesen.self)
        else { throw XCTSkip("eventSynthesizer fehlt") }
        let fertig = XCTestExpectation(description: "Mehrfinger")
        var fehler: NSError?
        let rueckmeldung: @convention(block) (Bool, NSError?) -> Void = { _, e in
            fehler = e
            fertig.fulfill()
        }
        ausloesen(synth, s5, satz, rueckmeldung as AnyObject)
        _ = XCTWaiter.wait(for: [fertig], timeout: 10)
        if let fehler { throw fehler }
    }

    /// `anzahl` Finger nebeneinander um die Mitte von `element`.
    static func tippen(_ anzahl: Int, auf element: XCUIElement) throws {
        let f = element.frame
        let punkte = (0..<anzahl).map { i in
            CGPoint(x: f.midX + CGFloat(i - anzahl / 2) * 60, y: f.midY + CGFloat(i % 2) * 20)
        }
        try tippen(punkte)
    }
}
