import Foundation

// Schnellansichten unter dem Viewport (Strang „Material“): Stückliste kompakt, Zuschnitt kompakt und später die
// Druckvorschau. Jede klappt einzeln auf und zu, mehrere können zugleich offen sein, alle zu ist erlaubt. Eingeklappt
// bleibt eine schmale Kopfzeile mit den Kennzahlen. Die Höhe jeder offenen Ansicht ist ziehbar. Hier nur die Logik ohne
// SwiftUI (testbar); die Oberfläche merkt sich den Zustand je Projektfenster in den Einstellungen.

public enum Schnellansicht: String, CaseIterable, Codable, Identifiable, Sendable {
    case stueckliste, zuschnitt, druck

    public var id: String { rawValue }

    public var titel: String {
        switch self {
        case .stueckliste: return "Stückliste"
        case .zuschnitt: return "Zuschnitt"
        case .druck: return "Druck"
        }
    }

    public var symbol: String {
        switch self {
        case .stueckliste: return "list.bullet.rectangle"
        case .zuschnitt: return "scissors"
        case .druck: return "printer"
        }
    }

    /// Höhe des Inhalts beim ersten Aufklappen (Punkte).
    public var standardHoehe: Double {
        switch self {
        case .stueckliste: return 250
        case .zuschnitt: return 170
        case .druck: return 170
        }
    }
}

public struct SchnellansichtenZustand: Equatable, Codable, Sendable {
    /// Kleinste und größte Höhe eines Inhalts (ohne Kopfzeile).
    public static let mindestHoehe: Double = 72
    public static let hoechstHoehe: Double = 720

    public var offen: Set<Schnellansicht>
    /// Eingestellte Höhe je Ansicht (Schlüssel `Schnellansicht.rawValue`).
    public var hoehen: [String: Double]
    /// Was offen war, bevor alles zugeklappt wurde (Umschalten öffnet es wieder).
    public var zuletzt: Set<Schnellansicht>

    public init(offen: Set<Schnellansicht> = [], hoehen: [String: Double] = [:], zuletzt: Set<Schnellansicht> = [.stueckliste]) {
        self.offen = offen
        self.hoehen = hoehen
        self.zuletzt = zuletzt.isEmpty ? [.stueckliste] : zuletzt
    }

    public func istOffen(_ a: Schnellansicht) -> Bool { offen.contains(a) }

    public func hoehe(_ a: Schnellansicht) -> Double {
        Self.begrenzt(hoehen[a.rawValue] ?? a.standardHoehe)
    }

    public mutating func setzeHoehe(_ a: Schnellansicht, _ h: Double) {
        hoehen[a.rawValue] = Self.begrenzt(h)
    }

    static func begrenzt(_ h: Double) -> Double { min(max(h, mindestHoehe), hoechstHoehe) }

    // MARK: Auf und zu

    public mutating func umschalten(_ a: Schnellansicht) {
        if offen.contains(a) { schliesse(a) } else { oeffne(a) }
    }

    public mutating func oeffne(_ a: Schnellansicht) { offen.insert(a) }

    public mutating func schliesse(_ a: Schnellansicht) {
        if offen == [a] { zuletzt = [a] }
        offen.remove(a)
    }

    /// Alle zuklappen; was offen war, merkt sich `zuletzt`.
    public mutating func alleZu() {
        if !offen.isEmpty { zuletzt = offen }
        offen = []
    }

    public mutating func alleAuf(_ sichtbar: [Schnellansicht]) { offen.formUnion(sichtbar) }

    /// Ist etwas offen, alles zu; sonst das zuletzt Offene wieder auf (nur, was sichtbar ist; sonst die Stückliste).
    public mutating func allesUmschalten(_ sichtbar: [Schnellansicht]) {
        if !offene(sichtbar).isEmpty {
            alleZu()
        } else {
            let wieder = zuletzt.intersection(sichtbar)
            offen.formUnion(wieder.isEmpty ? [.stueckliste] : wieder)
        }
    }

    /// Offene bzw. eingeklappte Ansichten in fester Reihenfolge.
    public func offene(_ sichtbar: [Schnellansicht]) -> [Schnellansicht] {
        Schnellansicht.allCases.filter { sichtbar.contains($0) && offen.contains($0) }
    }

    public func eingeklappte(_ sichtbar: [Schnellansicht]) -> [Schnellansicht] {
        Schnellansicht.allCases.filter { sichtbar.contains($0) && !offen.contains($0) }
    }

    // MARK: Höhen

    /// Höhen der offenen Inhalte bei `platz` Punkten für alle Inhalte zusammen: wie eingestellt, sonst im gleichen
    /// Verhältnis gekürzt, aber nicht unter die Mindesthöhe; reicht auch das nicht, bekommt jede den gleichen Teil.
    public func verteilt(_ sichtbar: [Schnellansicht], platz: Double) -> [Schnellansicht: Double] {
        let liste = offene(sichtbar)
        guard !liste.isEmpty else { return [:] }
        let wunsch = liste.map(hoehe)
        let summe = wunsch.reduce(0, +)
        let frei = max(0, platz)
        var out: [Schnellansicht: Double] = [:]
        if summe <= frei {
            for (a, h) in zip(liste, wunsch) { out[a] = h }
            return out
        }
        if Double(liste.count) * Self.mindestHoehe > frei {
            for a in liste { out[a] = frei / Double(liste.count) }
            return out
        }
        // Gekürzt im Verhältnis; was unter die Mindesthöhe fiele, bleibt dort, der Rest teilt sich den übrigen Platz
        var fest: [Schnellansicht: Double] = [:]
        var rest = liste
        while true {
            let verfuegbar = frei - fest.values.reduce(0, +)
            let restSumme = rest.map(hoehe).reduce(0, +)
            let f = restSumme > 0 ? verfuegbar / restSumme : 0
            let zuKlein = rest.filter { hoehe($0) * f < Self.mindestHoehe }
            if zuKlein.isEmpty {
                for a in rest { out[a] = hoehe(a) * f }
                break
            }
            for a in zuKlein { fest[a] = Self.mindestHoehe }
            rest.removeAll { zuKlein.contains($0) }
            if rest.isEmpty { break }
        }
        for (a, h) in fest { out[a] = h }
        return out
    }

    /// Griff über `a` um `dy` Punkte gezogen (positiv nach unten), ausgehend von den Höhen beim Beginn (`start`, wie
    /// angezeigt). Über der ersten offenen Ansicht liegt der Viewport: sie wächst nach oben (höchstens bis `platz` für
    /// alle Inhalte). Zwischen zwei offenen Ansichten wandert die Höhe von der einen zur anderen.
    public mutating func ziehe(
        _ a: Schnellansicht, dy: Double, start: [Schnellansicht: Double], sichtbar: [Schnellansicht], platz: Double
    ) {
        let liste = offene(sichtbar)
        guard let i = liste.firstIndex(of: a), let h0 = start[a] else { return }
        if i == 0 {
            let andere = liste.dropFirst().reduce(0) { $0 + (start[$1] ?? hoehe($1)) }
            let oben = min(Self.hoechstHoehe, max(Self.mindestHoehe, platz - andere))
            let neu = min(max(h0 - dy, Self.mindestHoehe), oben)
            hoehen[a.rawValue] = neu
            for b in liste.dropFirst() { hoehen[b.rawValue] = Self.begrenzt(start[b] ?? hoehe(b)) }
        } else {
            let davor = liste[i - 1]
            let summe = (start[davor] ?? hoehe(davor)) + h0
            let neu = min(max(h0 - dy, Self.mindestHoehe), max(Self.mindestHoehe, summe - Self.mindestHoehe))
            hoehen[a.rawValue] = Self.begrenzt(neu)
            hoehen[davor.rawValue] = Self.begrenzt(summe - neu)
            for b in liste where b != a && b != davor { hoehen[b.rawValue] = Self.begrenzt(start[b] ?? hoehe(b)) }
        }
    }

    // MARK: Speichern

    public var daten: Data { (try? JSONEncoder().encode(self)) ?? Data() }

    public static func aus(_ daten: Data?) -> SchnellansichtenZustand? {
        guard let daten, !daten.isEmpty else { return nil }
        return try? JSONDecoder().decode(SchnellansichtenZustand.self, from: daten)
    }
}
