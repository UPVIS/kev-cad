import Foundation

// V2-3 (OBERFLAECHE.md): Zustand der neuen Oberfläche, den Sprache (V2-6) und Agent (V2-7) später auslösen sollen:
// Modus, Kacheln, Startübersicht, Sprechen, Fenster am Rand.
//
// Vertrag wie bei AppModel: Die Oberfläche liest `AppModel.oberflaeche` und ruft `OberflaechenActions`. Geändert wird
// der Zustand nur über `OberflaechenStore.ausfuehren(_:)`, und das ruft allein die Umsetzung der Aktionen (App-Kern bzw.
// Demomodus). Jeder Befehl ist ein Wert (`Oberflaechenbefehl`), damit ihn später auch eine Nachricht des Kernels oder
// die Spracherkennung auslösen kann.

/// Fokus: ultraminimal, nur Viewer, Gliederung, Live-Text und Agentenspur. Werkstatt: Gliederung mit Eigenschaften
/// und Kachelfläche.
public enum ArbeitsModus: String, CaseIterable, Codable, Sendable {
    case fokus, werkstatt
}

/// Was eine Kachel der Werkstatt zeigt. Jede Art gibt es höchstens einmal.
public enum KachelArt: String, CaseIterable, Codable, Sendable, Identifiable {
    case modell, zeichnung, stueckliste, zuschnitt, ansicht, material, simulation, versionen, details

    public var id: String { rawValue }
}

/// Bildschirmrand für das schmale Fenster neben dem Chat.
public enum Bildschirmrand: String, CaseIterable, Codable, Sendable {
    case links, rechts
}

/// Ein Auftrag an die Oberfläche.
public enum Oberflaechenbefehl: Equatable, Sendable {
    case modus(ArbeitsModus)
    /// Kachel öffnen (hinten anfügen) oder, wenn schon offen, nach vorn holen; sie wird die aktive.
    case kachelZeigen(KachelArt)
    case kachelSchliessen(KachelArt)
    /// Eine Kachel füllt die ganze Fläche; nil ordnet wieder alle ein.
    case kachelGross(KachelArt?)
    /// Genau diese Kacheln in dieser Reihenfolge (Nummer 1 bis 4).
    case kachelnOrdnen([KachelArt])
    /// Zuletzt angesprochene Kachel (Tastatur, Menüs der Kachel); nil = keine.
    case kachelAktiv(KachelArt?)
    /// Startübersicht der letzten Projekte zeigen oder wegschieben.
    case uebersicht(Bool)
    /// Kevin spricht (roter Rahmen um den Viewer); `false` hält an, die Sitzung bleibt offen.
    case sprechen(Bool)
    /// Was Kevin gesagt hat; nil leert die Zone.
    case sprechText(String?)
    /// ↩: Die Sitzung endet, das Paket geht zum Agenten.
    case sprechenFertig
    /// esc: Die Sitzung endet ohne Paket.
    case sprechenVerwerfen
    /// Fenster schmal an einen Bildschirmrand oder zurück (nil).
    case rand(Bildschirmrand?)
}

/// Reine Logik des Zustands, ohne Beobachtung (testbar, auch für den Demomodus und spätere Nachrichten).
public struct OberflaechenZustand: Equatable, Sendable {
    public static let hoechstensKacheln = 4

    public var modus: ArbeitsModus = .fokus
    public var kacheln: [KachelArt] = [.modell]
    public var gross: KachelArt?
    public var aktiv: KachelArt?
    public var uebersicht = false
    public var spricht = false
    /// Sitzung von V bis ↩ oder esc: Sie bleibt offen, wenn Kevin mit V anhält.
    public var sitzungOffen = false
    /// Live-Text, solange Kevin spricht; danach steht er als `zuletztGesagt` in der Statuszeile.
    public var sprechText: String?
    public var zuletztGesagt: String?
    public var rand: Bildschirmrand?
    /// Modus vor dem Rand: Zurück vom Rand stellt ihn wieder her.
    public var modusVorRand: ArbeitsModus?

    public init(modus: ArbeitsModus = .fokus, kacheln: [KachelArt] = [.modell], uebersicht: Bool = false) {
        self.modus = modus
        self.kacheln = Self.bereinigt(kacheln)
        self.uebersicht = uebersicht
    }

    public mutating func anwenden(_ befehl: Oberflaechenbefehl) {
        switch befehl {
        case .modus(let m):
            modus = m
            if m == .werkstatt && kacheln.isEmpty { kacheln = [.modell] }
        case .kachelZeigen(let a):
            if !kacheln.contains(a) {
                kacheln.append(a)
                if kacheln.count > Self.hoechstensKacheln, let weg = Self.verdraengt(kacheln, neu: a) {
                    kacheln.removeAll { $0 == weg }
                }
            }
            if gross != nil && gross != a { gross = nil }
            aktiv = a
            if a != .modell { modus = .werkstatt }
        case .kachelSchliessen(let a):
            kacheln.removeAll { $0 == a }
            if gross == a { gross = nil }
            if aktiv == a { aktiv = kacheln.last }
        case .kachelGross(let a):
            if let a {
                if !kacheln.contains(a) { anwenden(.kachelZeigen(a)) }
                gross = a
                aktiv = a
                modus = .werkstatt
            } else {
                gross = nil
            }
        case .kachelnOrdnen(let liste):
            kacheln = Self.bereinigt(liste)
            gross = nil
            if let a = aktiv, !kacheln.contains(a) { aktiv = kacheln.first }
            if kacheln.contains(where: { $0 != .modell }) { modus = .werkstatt }
        case .kachelAktiv(let a):
            aktiv = a.flatMap { kacheln.contains($0) ? $0 : nil }
        case .uebersicht(let an):
            uebersicht = an
        case .sprechen(let an):
            if !an, spricht, let t = sprechText, !t.isEmpty { zuletztGesagt = t }
            if !an { sprechText = nil }
            spricht = an
            if an { sitzungOffen = true }
        case .sprechText(let t):
            sprechText = t
        case .sprechenFertig:
            if let t = sprechText, !t.isEmpty { zuletztGesagt = t }
            sprechText = nil
            spricht = false
            sitzungOffen = false
        case .sprechenVerwerfen:
            sprechText = nil
            spricht = false
            sitzungOffen = false
        case .rand(let r):
            if let r {
                if rand == nil { modusVorRand = modus }
                rand = r
                modus = .fokus
            } else if rand != nil {
                rand = nil
                if let m = modusVorRand { modus = m }
                modusVorRand = nil
            }
        }
    }

    /// Nummer einer Kachel (1 bis 4) in der Reihenfolge der Fläche.
    public func nummer(_ art: KachelArt) -> Int? { kacheln.firstIndex(of: art).map { $0 + 1 } }

    public func kachel(nummer n: Int) -> KachelArt? { n >= 1 && n <= kacheln.count ? kacheln[n - 1] : nil }

    /// Ohne Doppelte, höchstens vier.
    static func bereinigt(_ liste: [KachelArt]) -> [KachelArt] {
        var gesehen: Set<KachelArt> = []
        return Array(liste.filter { gesehen.insert($0).inserted }.prefix(hoechstensKacheln))
    }

    /// Welche Kachel weicht, wenn eine fünfte dazukommt: die älteste außer Modell und der neuen.
    static func verdraengt(_ liste: [KachelArt], neu: KachelArt) -> KachelArt? {
        liste.first { $0 != .modell && $0 != neu } ?? liste.first { $0 != neu }
    }
}

/// Beobachtbarer Zustand der Oberfläche in `AppModel.oberflaeche`.
@MainActor
public final class OberflaechenStore: ObservableObject {
    @Published public private(set) var zustand: OberflaechenZustand

    public init(_ zustand: OberflaechenZustand = OberflaechenZustand()) {
        self.zustand = zustand
    }

    public var modus: ArbeitsModus { zustand.modus }
    public var kacheln: [KachelArt] { zustand.kacheln }
    public var gross: KachelArt? { zustand.gross }
    public var aktiv: KachelArt? { zustand.aktiv }
    public var uebersicht: Bool { zustand.uebersicht }
    public var spricht: Bool { zustand.spricht }
    public var sitzungOffen: Bool { zustand.sitzungOffen }
    public var sprechText: String? { zustand.sprechText }
    public var zuletztGesagt: String? { zustand.zuletztGesagt }
    public var rand: Bildschirmrand? { zustand.rand }

    public func nummer(_ art: KachelArt) -> Int? { zustand.nummer(art) }

    /// Einziger Weg, den Zustand zu ändern; nur für die Umsetzung von `OberflaechenActions` (App-Kern, Demomodus).
    public func ausfuehren(_ befehl: Oberflaechenbefehl) {
        var neu = zustand
        neu.anwenden(befehl)
        if neu != zustand { zustand = neu }
    }

    /// Gemerkter Modus und gemerkte Kacheln beim Start (vor dem ersten Erscheinen der Oberfläche).
    public func vorbelegen(modus: ArbeitsModus, kacheln: [KachelArt]) {
        zustand = OberflaechenZustand(modus: modus, kacheln: kacheln, uebersicht: zustand.uebersicht)
    }
}

/// Aktionen der Oberfläche (V2-3). Implementiert vom App-Kern (`AppController`) und vom Demomodus; Sprache (V2-6) und
/// Agent (V2-7) lösen später dieselben Befehle aus.
@MainActor
public protocol OberflaechenActions: AnyObject {
    func oberflaeche(_ befehl: Oberflaechenbefehl)
}

extension OberflaechenActions {
    public func setzeModus(_ modus: ArbeitsModus) { oberflaeche(.modus(modus)) }
    public func zeigeKachel(_ art: KachelArt) { oberflaeche(.kachelZeigen(art)) }
    public func schliesseKachel(_ art: KachelArt) { oberflaeche(.kachelSchliessen(art)) }
    public func vergroessereKachel(_ art: KachelArt?) { oberflaeche(.kachelGross(art)) }
    public func ordneKacheln(_ arten: [KachelArt]) { oberflaeche(.kachelnOrdnen(arten)) }
    public func setzeSprechen(_ an: Bool) { oberflaeche(.sprechen(an)) }
    public func sprechenFertig() { oberflaeche(.sprechenFertig) }
    public func sprechenVerwerfen() { oberflaeche(.sprechenVerwerfen) }
    public func setzeRand(_ rand: Bildschirmrand?) { oberflaeche(.rand(rand)) }
    public func zeigeUebersicht(_ an: Bool) { oberflaeche(.uebersicht(an)) }
}

extension AppModel {
    /// Aktionen der Oberfläche, wenn `actions` sie anbietet (App-Kern und Demomodus tun das).
    public var oberflaechenActions: OberflaechenActions? { actions as? OberflaechenActions }
}
