import Combine
import Foundation
import OCCTSwiftViewport
import simd

// I-3b (PLAN-IPAD.md 4.2): Rückgängig und Wiederholen für Ansicht, Auswahl und Sichtbarkeit, auf Mac und iPad.
// Am Mac ⌘Z und ⇧⌘Z (Menü Bearbeiten; der Viewer nimmt `undo:` und `redo:`, solange er die Tastatur hat, Textfelder und
// das Zeichnungsblatt behalten ihr eigenes Rückgängig), am iPad 2 Finger tippen, 3 Finger tippen, die Knöpfe ↶ ↷ der
// Daumenleiste und ⌘Z am Magic Keyboard.
//
// Der Verlauf hört nicht auf einzelne Befehle, sondern merkt sich den Stand, sobald der Viewer zur Ruhe kommt (keine
// Geste, keine Kamerafahrt, 0,4 s nichts Neues). So zählt ein Drehen mit dem Finger als ein Schritt, egal wie viele Bilder
// es dauerte, und auch Befehle des Agenten (view, Ausblenden über MCP) lassen sich zurücknehmen.

/// Verlauf mit Rückgängig und Wiederholen über beliebige Stände; `gleich` entscheidet, ob sich etwas geändert hat.
struct Verlauf<Stand> {
    private(set) var aktuell: Stand?
    private(set) var zurueck: [Stand] = []
    private(set) var vor: [Stand] = []
    let gleich: (Stand, Stand) -> Bool
    /// Höchstens so viele Schritte zurück.
    var grenze = 100

    init(gleich: @escaping (Stand, Stand) -> Bool) { self.gleich = gleich }

    var kannRueckgaengig: Bool { !zurueck.isEmpty }
    var kannWiederholen: Bool { !vor.isEmpty }

    /// Ein ruhiger Stand. Weicht er vom aktuellen ab, wird der aktuelle zum Schritt zurück und Wiederholen verfällt.
    /// true = neuer Schritt.
    @discardableResult
    mutating func merke(_ s: Stand) -> Bool {
        guard let a = aktuell else {
            aktuell = s
            return false
        }
        guard !gleich(a, s) else { return false }
        zurueck.append(a)
        if zurueck.count > grenze { zurueck.removeFirst(zurueck.count - grenze) }
        vor.removeAll()
        aktuell = s
        return true
    }

    /// Einen Schritt zurück: der Stand, der jetzt gelten soll (nil = nichts mehr zurück).
    mutating func rueckgaengig() -> Stand? {
        guard let a = aktuell, let s = zurueck.popLast() else { return nil }
        vor.append(a)
        aktuell = s
        return s
    }

    /// Einen Schritt vor (nil = nichts zu wiederholen).
    mutating func wiederholen() -> Stand? {
        guard let a = aktuell, let s = vor.popLast() else { return nil }
        zurueck.append(a)
        aktuell = s
        return s
    }

    /// Nach dem Anwenden: der Stand, wie er tatsächlich gilt (die Szene kann Teile verworfen haben).
    mutating func ersetzeAktuell(_ s: Stand) { aktuell = s }

    /// Neu beginnen (anderes Projekt); `s` = Stand, ab dem gezählt wird.
    mutating func leeren(ab s: Stand?) {
        zurueck.removeAll()
        vor.removeAll()
        aktuell = s
    }
}

/// Was Rückgängig zurücknimmt: Kamera, Auswahl und Sichtbarkeit (samt lokaler Ansicht).
struct AnsichtsStand {
    var kamera: CameraState
    var auswahl: [ElementRef]
    var verborgen: Set<String>
    var hauch: Set<String>
    var lokal: Bool

    /// Was sich zwischen zwei Ständen geändert hat, für Menü und Meldung: „Auswahl“, „Sichtbarkeit“, „Ansicht“.
    static func art(_ a: AnsichtsStand, _ b: AnsichtsStand) -> String {
        if a.auswahl != b.auswahl { return "Auswahl" }
        if a.verborgen != b.verborgen || a.hauch != b.hauch || a.lokal != b.lokal { return "Sichtbarkeit" }
        return "Ansicht"
    }

    static func gleich(_ a: AnsichtsStand, _ b: AnsichtsStand) -> Bool {
        a.auswahl == b.auswahl && a.verborgen == b.verborgen && a.hauch == b.hauch && a.lokal == b.lokal
            && kameraGleich(a.kamera, b.kamera)
    }

    /// Kameras gelten als gleich, wenn sich nichts sichtbar unterscheidet (eine Fahrt endet nicht immer bitgleich).
    static func kameraGleich(_ a: CameraState, _ b: CameraState) -> Bool {
        guard a.isOrthographic == b.isOrthographic else { return false }
        let massstab = max(1, max(a.distance, a.orthographicScale))
        let drehung = min(simd_length(a.rotation.vector - b.rotation.vector), simd_length(a.rotation.vector + b.rotation.vector))
        return drehung < 1e-4
            && abs(a.distance - b.distance) < 1e-4 * massstab
            && simd_length(a.pivot - b.pivot) < 1e-4 * massstab
            && abs(a.orthographicScale - b.orthographicScale) < 1e-4 * massstab
            && simd_length(a.panOffset - b.panOffset) < 1e-4 * massstab
            && abs(a.fieldOfView - b.fieldOfView) < 1e-3
    }
}

extension AppController {
    /// Wie lange der Viewer ruhig sein muss, bevor ein Stand zählt.
    static let verlaufRuhe: TimeInterval = 0.4

    func installVerlauf() {
        viewport.controller.$cameraState
            .dropFirst()
            .sink { [weak self] _ in self?.verlaufVormerken() }
            .store(in: &navCancellables)
        model.$project
            .map { $0?.path }
            .removeDuplicates()
            .sink { [weak self] _ in
                guard let self else { return }
                self.verlauf.leeren(ab: nil)
                self.verlaufBeschriften()
            }
            .store(in: &navCancellables)
    }

    /// Kamera, Auswahl oder Sichtbarkeit haben sich geändert: nach der Ruhezeit den Stand merken.
    func verlaufVormerken() {
        verlaufTimer?.invalidate()
        verlaufTimer = Timer.scheduledTimer(withTimeInterval: Self.verlaufRuhe, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated { self?.verlaufRuhig() }
        }
    }

    private func verlaufRuhig() {
        verlaufTimer = nil
        // Mitten in einer Geste oder Fahrt zählt nichts; dann später noch einmal
        if viewport.eingabe.navigation != nil || viewport.fahrt != nil {
            verlaufVormerken()
            return
        }
        if verlauf.merke(ansichtsStand()) { verlaufBeschriften() }
    }

    func ansichtsStand(kamera: CameraState? = nil) -> AnsichtsStand {
        AnsichtsStand(kamera: kamera ?? viewport.kameraZiel, auswahl: scene.selection, verborgen: scene.hidden,
                      hauch: scene.hauchTeile, lokal: localView != nil)
    }

    /// Einen Schritt zurück (⌘Z, 2 Finger tippen, ↶).
    public func rueckgaengig() {
        verlaufFestschreiben()
        let vorher = verlauf.aktuell
        guard let s = verlauf.rueckgaengig(), let vorher else {
            viewer.zeige("Nichts mehr rückgängig zu machen")
            return
        }
        verlaufAnwenden(s, von: vorher)
        viewer.zeige("Rückgängig: \(AnsichtsStand.art(vorher, s))")
    }

    /// Einen Schritt vor (⇧⌘Z, 3 Finger tippen, ↷).
    public func wiederholen() {
        verlaufFestschreiben()
        let vorher = verlauf.aktuell
        guard let s = verlauf.wiederholen(), let vorher else {
            viewer.zeige("Nichts zu wiederholen")
            return
        }
        verlaufAnwenden(s, von: vorher)
        viewer.zeige("Wiederholt: \(AnsichtsStand.art(vorher, s))")
    }

    /// Steht noch eine Änderung aus (Ruhezeit nicht abgelaufen), zählt sie jetzt: sonst nähme ⌘Z direkt nach einem Klick
    /// den Schritt davor zurück.
    func verlaufFestschreiben() {
        guard verlaufTimer != nil else { return }
        verlaufTimer?.invalidate()
        verlaufTimer = nil
        if verlauf.merke(ansichtsStand()) { verlaufBeschriften() }
    }

    private func verlaufAnwenden(_ s: AnsichtsStand, von vorher: AnsichtsStand) {
        // Sichtbarkeit: Ein Stand mit lokaler Ansicht bekommt als Rückweg (/) den Stand, aus dem wir kommen
        if s.lokal, localView == nil {
            localView = (vorher.verborgen, vorher.kamera)
        } else if !s.lokal {
            localView = nil
        }
        model.viewer.lokaleAnsicht = s.lokal
        if scene.hidden != s.verborgen {
            scene.showAll()
            if !s.verborgen.isEmpty { scene.setVisible(Array(s.verborgen), false) }
        }
        if scene.hauchTeile != s.hauch { scene.setHauch(s.hauch) }
        updateParts()
        measurePending = []
        applySelection(s.auswahl)
        viewport.smoothCamera(s.kamera, duration: 0.25)
        // Der Stand, wie er jetzt gilt (die Szene verwirft Teile, die es nicht mehr gibt); die Kamera ist das Ziel der Fahrt
        verlaufTimer?.invalidate()
        verlaufTimer = nil
        verlauf.ersetzeAktuell(ansichtsStand(kamera: s.kamera))
        verlaufBeschriften()
    }

    /// Titel für das Menü Bearbeiten (nil = nicht möglich). Eine Änderung in der Ruhezeit zählt dabei schon mit.
    func verlaufTitel(_ befehl: ViewerBefehl) -> String? {
        if verlaufTimer != nil, viewport.eingabe.navigation == nil {
            verlaufFestschreiben()
            verlaufBeschriften()
        }
        return befehl == .wiederholen ? viewer.wiederholenTitel : viewer.rueckgaengigTitel
    }

    /// Titel für Menü und Daumenleiste (nil = nicht möglich).
    func verlaufBeschriften() {
        let a = verlauf.aktuell
        viewer.rueckgaengigTitel = beide(a, verlauf.zurueck.last).map { "Rückgängig: \(AnsichtsStand.art($0, $1))" }
        viewer.wiederholenTitel = beide(a, verlauf.vor.last).map { "Wiederholen: \(AnsichtsStand.art($0, $1))" }
    }
}

private func beide<A, B>(_ a: A?, _ b: B?) -> (A, B)? {
    guard let a, let b else { return nil }
    return (a, b)
}
