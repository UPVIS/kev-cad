import Foundation
import simd

/// Bauplan des offenen Projekts (DOKUMENTE.md, Strang P6-A2): Plan und Strichbilder aus BAUPLAN, laufende Anfragen,
/// Durchspielen im 3D-Bereich. Gepflegt vom App-Kern (BauplanSteuerung); die Oberfläche liest und ruft `BauplanActions`.
@MainActor
public final class BauplanStore: ObservableObject {
    /// Letzter Plan (BAUPLAN); nil, bis der Kernel ihn geschickt hat.
    @Published public internal(set) var plan: Bauplan?
    /// Strichbild je Schritt-id.
    @Published public internal(set) var bilder: [String: BauplanStrichbild] = [:]
    /// BAUPLAN_REQ läuft (beim ersten Mal rechnet der Kernel den Plan, das dauert einige Sekunden).
    @Published public internal(set) var laedt = false
    /// Was gerade beim Kernel liegt („Prüft alle Schritte“, „Text wird gespeichert“), nil = nichts.
    @Published public internal(set) var arbeitet: String?
    /// Ergebnis der letzten Aktion (Bestätigung oder Fehler).
    @Published public internal(set) var meldung: BauplanMeldung?
    /// Durchspielen läuft (nil = aus).
    @Published public internal(set) var durchspielen: BauplanDurchspielen?
    /// Die Oberfläche soll den 3D-Bereich zeigen (zählt hoch, wenn Durchspielen oder ein Befund dorthin springt).
    @Published public internal(set) var zeige3D = 0
    /// Zeitpunkt der letzten Anfrage und Antwortzeit in ms (Messwert).
    public internal(set) var angefordert: Date?
    public internal(set) var antwortMs: Double?
    /// Uhr und gesicherter Zustand des Durchspielens (nur App-Kern).
    let laufzeit = BauplanLaufzeit()

    public init() {}

    public func bild(_ schritt: String) -> BauplanStrichbild? { bilder[schritt] }

    func leeren() {
        plan = nil
        bilder = [:]
        laedt = false
        arbeitet = nil
        meldung = nil
        durchspielen = nil
        angefordert = nil
        antwortMs = nil
    }
}

public struct BauplanMeldung: Equatable, Sendable {
    public var text: String
    public var fehler: Bool
    public var zeit: Date

    public init(text: String, fehler: Bool = false, zeit: Date = Date()) {
        self.text = text
        self.fehler = fehler
        self.zeit = zeit
    }
}

/// Stand des Durchspielens: welcher Schritt, wie weit die neuen Teile schon eingefahren sind.
public struct BauplanDurchspielen: Equatable, Sendable {
    /// Schritt-ids in Abspielreihenfolge (alle Montageschritte, sonst alle Schritte mit Teilen).
    public var schritte: [String]
    public var index: Int
    /// 0 = neue Teile in Explosionslage, 1 = eingebaut.
    public var fortschritt: Double
    public var spielt: Bool
    /// Geschwindigkeit (1 = 1,6 s je Schritt).
    public var tempo: Double

    public var schritt: String? { schritte.indices.contains(index) ? schritte[index] : nil }
    public var istLetzter: Bool { index >= schritte.count - 1 }
}

/// Aktionen des Bauplans, implementiert vom App-Kern (BauplanSteuerung) und im Demomodus.
@MainActor
public protocol BauplanActions: AnyObject {
    /// BAUPLAN_REQ (der Kernel erzeugt den Plan bei Bedarf).
    func bauplanAnfordern()
    /// BAUPLAN_EDIT mit `von: "kevin"`; danach schickt der Kernel den neuen Plan.
    func bauplanBearbeiten(_ ops: [JSONValue], titel: String)
    /// BAUPLAN_PRUEFEN (nil = alle Schritte).
    func bauplanPruefen(schritt: String?)
    /// Durchspielen ab einem Schritt (nil = erster Montageschritt) starten und den 3D-Bereich zeigen.
    func durchspielenStarten(ab schritt: String?)
    /// Zum nächsten oder vorigen Schritt (fährt die neuen Teile ein).
    func durchspielenSchritt(_ delta: Int)
    func durchspielenGeheZu(_ index: Int)
    /// Automatisch weiter (an) oder anhalten.
    func durchspielenAbspielen(_ an: Bool)
    func durchspielenTempo(_ tempo: Double)
    /// Ende: alle Teile wieder sichtbar und in Ruhelage.
    func durchspielenBeenden()
    /// Teile eines Schritts oder Befunds im 3D-Bereich zeigen (auswählen, einpassen, hervorheben).
    func bauplanZeigen(teile: [String], ort: SIMD3<Float>?)
}

extension AppModel {
    /// Bauplanaktionen des App-Kerns (nil im Demomodus ohne Bauplan).
    public var bauplanActions: BauplanActions? { actions as? BauplanActions }
}
