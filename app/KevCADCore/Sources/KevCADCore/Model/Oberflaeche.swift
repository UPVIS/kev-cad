import Foundation

// V2-3 (OBERFLAECHE.md): Zustand der neuen Oberfläche, den Sprache (V2-6) und Agent (V2-7, `VIEW_CMD flaeche`) auslösen:
// Leisten, Kacheln, Startübersicht, Sprechen, Fenster am Rand.
//
// V2-9 (Kevin nach dem ersten Test, 06.11.2026): Fokus und Werkstatt sind keine Modi mehr. Links und rechts gibt es je
// eine Leiste (Objekte bzw. Eigenschaften), Kacheln gehen unabhängig davon auf und zu. Ohne weitere Kachel oder mit dem
// Modell groß füllt der Viewer das Fenster.
//
// Vertrag wie bei AppModel: Die Oberfläche liest `AppModel.oberflaeche` und ruft `OberflaechenActions`. Geändert wird
// der Zustand nur über `OberflaechenStore.ausfuehren(_:)`, und das ruft allein die Umsetzung der Aktionen (App-Kern bzw.
// Demomodus). Jeder Befehl ist ein Wert (`Oberflaechenbefehl`), damit ihn später auch eine Nachricht des Kernels oder
// die Spracherkennung auslösen kann.

/// Nur noch Übergang für ältere Agenten und das Lagebild (`modus`): Fokus heißt Viewer allein ohne rechte Leiste,
/// Werkstatt heißt Kacheln eingeordnet und rechte Leiste an.
public enum ArbeitsModus: String, CaseIterable, Codable, Sendable {
    case fokus, werkstatt
}

/// Was eine Kachel der Werkstatt zeigt. Jede Art gibt es höchstens einmal. Die Namen sind Teil des Protokolls (`KACHELN`
/// in protocol.py, PROTOCOL.md, „Fläche“).
public enum KachelArt: String, CaseIterable, Codable, Sendable, Identifiable {
    case modell, zeichnung, bauplan, stueckliste, zuschnitt, druck, animation, ansicht, material, simulation, versionen, details, render

    public var id: String { rawValue }

    public var titel: String {
        switch self {
        case .modell: return "Modell"
        case .zeichnung: return "Zeichnung"
        case .bauplan: return "Bauplan"
        case .stueckliste: return "Stückliste"
        case .zuschnitt: return "Zuschnitt"
        case .druck: return "Druck"
        case .animation: return "Animation"
        case .ansicht: return "Zweite Ansicht"
        case .material: return "Material"
        case .simulation: return "Simulation"
        case .versionen: return "Versionen"
        case .details: return "Details"
        case .render: return "Rendern"
        }
    }
}

/// Bildschirmrand für das schmale Fenster neben dem Chat.
public enum Bildschirmrand: String, CaseIterable, Codable, Sendable {
    case links, rechts
}

/// Ein Auftrag an die Oberfläche.
public enum Oberflaechenbefehl: Equatable, Sendable {
    /// Übergang: Fokus = Modell groß, rechte Leiste zu; Werkstatt = Kacheln eingeordnet, rechte Leiste auf.
    case modus(ArbeitsModus)
    /// Linke Leiste (Objekte) zeigen oder ausblenden.
    case leisteLinks(Bool)
    /// Rechte Leiste (Eigenschaften und Maße des Modells) zeigen oder ausblenden.
    case leisteRechts(Bool)
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
    /// Zeitleiste im Fokus zeigen (V2-7); beim Abspielen steht sie dort von selbst, in der Werkstatt ist sie eine Kachel.
    case zeitleiste(Bool)
    /// Blickrichtung der zweiten Ansicht, Name wie in `VIEW_CMD view`.
    case zweiteAnsicht(String)
    /// Blatt der Kachel Zeichnung (Kennung); nil, wenn keins gewählt ist.
    case blatt(String?)
}

/// Reine Logik des Zustands, ohne Beobachtung (testbar, auch für den Demomodus und spätere Nachrichten).
public struct OberflaechenZustand: Equatable, Sendable {
    public static let hoechstensKacheln = 4

    /// Linke Leiste: Objekte (über dem Viewer leise, neben Kacheln als Spalte)
    public var leisteLinks = true
    /// Rechte Leiste: Eigenschaften der Auswahl und Maße des Modells
    public var leisteRechts = false
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
    /// Vor dem Rand: rechte Leiste und große Kachel; zurück vom Rand stellt sie wieder her.
    public var vorRand: VorRand?

    public struct VorRand: Equatable, Sendable {
        public var leisteRechts: Bool
        public var gross: KachelArt?
    }

    /// Kacheln stehen nebeneinander: Es ist mehr als das Modell offen, und das Modell ist nicht groß. Sonst füllt der
    /// Viewer das Fenster.
    public var kachelflaeche: Bool { kacheln.contains { $0 != .modell } && gross != .modell }

    /// Übergang für ältere Agenten und das Lagebild.
    public var modus: ArbeitsModus { kachelflaeche || leisteRechts ? .werkstatt : .fokus }
    /// Zeitleiste im Fokus auf Zuruf
    public var zeitleiste = false
    /// Blickrichtung der zweiten Ansicht
    public var zweiteAnsicht = "top"
    /// Gewähltes Blatt der Kachel Zeichnung
    public var blatt: String?

    public init(leisteLinks: Bool = true, leisteRechts: Bool = false, kacheln: [KachelArt] = [.modell],
                gross: KachelArt? = nil, uebersicht: Bool = false) {
        self.leisteLinks = leisteLinks
        self.leisteRechts = leisteRechts
        self.kacheln = Self.bereinigt(kacheln)
        self.gross = gross.flatMap { self.kacheln.contains($0) ? $0 : nil }
        self.uebersicht = uebersicht
    }

    /// Übergang: wie früher mit einem Modus.
    public init(modus: ArbeitsModus, kacheln: [KachelArt] = [.modell], uebersicht: Bool = false) {
        self.init(kacheln: kacheln, uebersicht: uebersicht)
        anwenden(.modus(modus))
    }

    public mutating func anwenden(_ befehl: Oberflaechenbefehl) {
        switch befehl {
        case .modus(let m):
            if m == .werkstatt {
                if kacheln.isEmpty { kacheln = [.modell] }
                if gross == .modell { gross = nil }
                leisteRechts = true
            } else {
                if kacheln.contains(where: { $0 != .modell }) || gross != nil { einreihen(.modell); gross = .modell }
                leisteRechts = false
            }
        case .leisteLinks(let an):
            leisteLinks = an
        case .leisteRechts(let an):
            leisteRechts = an
        case .kachelZeigen(let a):
            if a == .animation { einreihen(.modell) }  // die Bewegung sieht man im Modell
            einreihen(a)
            if gross != nil && gross != a { gross = nil }
            aktiv = a
        case .kachelSchliessen(let a):
            kacheln.removeAll { $0 == a }
            if gross == a { gross = nil }
            if aktiv == a { aktiv = kacheln.last }
        case .kachelGross(let a):
            if let a {
                if !kacheln.contains(a) { anwenden(.kachelZeigen(a)) }
                gross = a
                aktiv = a
            } else {
                gross = nil
            }
        case .kachelnOrdnen(let liste):
            kacheln = Self.bereinigt(liste.contains(.animation) && !liste.contains(.modell) ? [.modell] + liste : liste)
            gross = nil
            if let a = aktiv, !kacheln.contains(a) { aktiv = kacheln.first }
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
                // Am Rand ist das Fenster schmal: nur der Viewer, ohne rechte Leiste
                if rand == nil {
                    vorRand = VorRand(leisteRechts: leisteRechts, gross: gross)
                    leisteRechts = false
                    if kachelflaeche { gross = .modell }
                }
                rand = r
            } else if rand != nil {
                rand = nil
                if let v = vorRand {
                    leisteRechts = leisteRechts || v.leisteRechts
                    // Hat am Rand jemand die Kacheln geändert (der Agent), gilt das weiter
                    if gross == .modell { gross = v.gross }
                }
                vorRand = nil
            }
        case .zeitleiste(let an):
            zeitleiste = an
        case .zweiteAnsicht(let name):
            zweiteAnsicht = name
        case .blatt(let id):
            blatt = id
        }
    }

    /// Kachel hinten anfügen, wenn sie noch nicht offen ist; eine fünfte verdrängt die älteste.
    private mutating func einreihen(_ a: KachelArt) {
        guard !kacheln.contains(a) else { return }
        kacheln.append(a)
        if kacheln.count > Self.hoechstensKacheln, let weg = Self.verdraengt(kacheln, neu: a) {
            kacheln.removeAll { $0 == weg }
        }
    }

    /// Nummer einer Kachel (1 bis 4) in der Reihenfolge der Fläche.
    public func nummer(_ art: KachelArt) -> Int? { kacheln.firstIndex(of: art).map { $0 + 1 } }

    public func kachel(nummer n: Int) -> KachelArt? { n >= 1 && n <= kacheln.count ? kacheln[n - 1] : nil }

    /// Stand in einem Satz für den Agenten: „Kacheln 1 Modell, 2 Druck (groß) · Objekte links · Fenster am rechten Rand“.
    public var kurztext: String {
        var teile: [String] = []
        if kachelflaeche {
            let liste = kacheln.enumerated().map { "\($0.offset + 1) \($0.element.titel)" + (gross == $0.element ? " (groß)" : "") }
            teile.append("Kacheln " + liste.joined(separator: ", "))
        } else {
            let weitere = kacheln.filter { $0 != .modell }.count
            teile.append("Viewer allein" + (weitere > 0 ? " (\(weitere) weitere Kacheln eingeklappt)" : "")
                         + (zeitleiste ? ", Zeitleiste an" : ""))
        }
        var leisten: [String] = []
        if leisteLinks { leisten.append("Objekte links") }
        if leisteRechts { leisten.append("Eigenschaften rechts") }
        teile.append(leisten.isEmpty ? "keine Leiste" : leisten.joined(separator: ", "))
        if let r = rand { teile.append("Fenster am \(r == .rechts ? "rechten" : "linken") Rand") }
        return teile.joined(separator: " · ")
    }

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
    public var leisteLinks: Bool { zustand.leisteLinks }
    public var leisteRechts: Bool { zustand.leisteRechts }
    public var kachelflaeche: Bool { zustand.kachelflaeche }
    public var kacheln: [KachelArt] { zustand.kacheln }
    public var gross: KachelArt? { zustand.gross }
    public var aktiv: KachelArt? { zustand.aktiv }
    public var uebersicht: Bool { zustand.uebersicht }
    public var spricht: Bool { zustand.spricht }
    public var sitzungOffen: Bool { zustand.sitzungOffen }
    public var sprechText: String? { zustand.sprechText }
    public var zuletztGesagt: String? { zustand.zuletztGesagt }
    public var rand: Bildschirmrand? { zustand.rand }
    public var zeitleiste: Bool { zustand.zeitleiste }
    public var zweiteAnsicht: String { zustand.zweiteAnsicht }
    public var blatt: String? { zustand.blatt }

    public func nummer(_ art: KachelArt) -> Int? { zustand.nummer(art) }

    /// Einziger Weg, den Zustand zu ändern; nur für die Umsetzung von `OberflaechenActions` (App-Kern, Demomodus).
    public func ausfuehren(_ befehl: Oberflaechenbefehl) {
        var neu = zustand
        neu.anwenden(befehl)
        if neu != zustand { zustand = neu }
    }

    /// Gemerkte Leisten und Kacheln beim Start (vor dem ersten Erscheinen der Oberfläche).
    public func vorbelegen(leisteLinks: Bool, leisteRechts: Bool, kacheln: [KachelArt], gross: KachelArt?,
                           zweiteAnsicht: String? = nil) {
        var z = OberflaechenZustand(leisteLinks: leisteLinks, leisteRechts: leisteRechts, kacheln: kacheln, gross: gross,
                                    uebersicht: zustand.uebersicht)
        if let zweiteAnsicht { z.zweiteAnsicht = zweiteAnsicht }
        zustand = z
    }

    /// Übergang: wie früher mit einem Modus.
    public func vorbelegen(modus: ArbeitsModus, kacheln: [KachelArt], zweiteAnsicht: String? = nil) {
        var z = OberflaechenZustand(modus: modus, kacheln: kacheln, uebersicht: zustand.uebersicht)
        if let zweiteAnsicht { z.zweiteAnsicht = zweiteAnsicht }
        zustand = z
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
    public func setzeLeisteLinks(_ an: Bool) { oberflaeche(.leisteLinks(an)) }
    public func setzeLeisteRechts(_ an: Bool) { oberflaeche(.leisteRechts(an)) }
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

/// Standardansichten wie in `VIEW_CMD view`.
public let standardAnsichten: Set<String> = [
    "top", "bottom", "front", "back", "left", "right", "iso", "iso_front_left", "iso_back_right", "iso_back_left",
]

/// Antwort auf `VIEW_CMD flaeche` (PROTOCOL.md, „Fläche“): die Befehle für die Oberfläche und der Stand danach, oder was an
/// den Angaben nicht stimmt. Reine Rechnung: Erst wenn alles passt, setzt der Aufrufer etwas um.
public struct FlaecheAuftrag: Equatable, Sendable {
    public var befehle: [Oberflaechenbefehl] = []
    public var stand: OberflaechenZustand
    /// Kacheln, die dabei weichen mussten
    public var gewichen: [KachelArt] = []

    public var meldung: String {
        stand.kurztext + (gewichen.isEmpty ? "" : "; \(gewichen.map(\.titel).joined(separator: ", ")) musste weichen")
    }

    /// `blaetter`: Kennung und Titel der Blätter in der Reihenfolge der Übersicht, nil, solange sie noch nicht da ist.
    public static func aus(_ a: JSONValue, zustand: OberflaechenZustand,
                           blaetter: [(id: String, titel: String)]?) -> Result<FlaecheAuftrag, FlaecheFehler> {
        var auftrag = FlaecheAuftrag(stand: zustand)
        func tu(_ b: Oberflaechenbefehl) {
            auftrag.befehle.append(b)
            auftrag.stand.anwenden(b)
        }
        func kachel(_ v: JSONValue) -> KachelArt? {
            if let n = v.doubleValue { return auftrag.stand.kachel(nummer: Int(n)) }
            return v.stringValue.flatMap(KachelArt.init(rawValue:))
        }
        func kacheln(_ feld: String) -> Result<[KachelArt]?, FlaecheFehler> {
            guard let v = a[feld], v != .null else { return .success(nil) }
            guard let liste = v.arrayValue else { return .failure(.init("\(feld) ist keine Liste von Kacheln")) }
            var out: [KachelArt] = []
            for e in liste {
                guard let k = e.stringValue.flatMap(KachelArt.init(rawValue:)) else {
                    return .failure(.init("Unbekannte Kachel in \(feld): \(e.anzeige)"))
                }
                out.append(k)
            }
            return .success(out)
        }
        let vorher = Set(zustand.kacheln)
        tu(.uebersicht(false))  // die Startübersicht läge sonst über dem, was der Agent zeigt

        if let r = a["rand"]?.stringValue {
            if r == "aus" {
                tu(.rand(nil))
            } else if let rand = Bildschirmrand(rawValue: r) {
                tu(.rand(rand))
            } else {
                return .failure(.init("Unbekannter Rand \(r)"))
            }
        }
        switch kacheln("ordnen") {
        case .failure(let f): return .failure(f)
        case .success(let liste?):
            tu(.kachelnOrdnen(liste))
        case .success(nil): break
        }
        switch kacheln("zeigen") {
        case .failure(let f): return .failure(f)
        case .success(let liste?):
            for k in liste { tu(.kachelZeigen(k)) }
        case .success(nil): break
        }
        if let z = a["schliessen"], z != .null {
            if z.stringValue == "alle" {
                for k in auftrag.stand.kacheln { tu(.kachelSchliessen(k)) }
            } else if let liste = z.arrayValue {
                // Nummern gelten für den Stand vor dem Schließen: „schließ 2 und 3“ meint die Kacheln, die Kevin sieht
                var weg: [KachelArt] = []
                for e in liste {
                    guard let k = kachel(e), auftrag.stand.kacheln.contains(k) else {
                        return .failure(.init("Kachel \(e.anzeige) ist nicht offen"))
                    }
                    weg.append(k)
                }
                for k in weg { tu(.kachelSchliessen(k)) }
            } else {
                return .failure(.init("schliessen ist weder alle noch eine Liste"))
            }
        }
        if let g = a["gross"], g != .null {
            if g.stringValue == "aus" {
                tu(.kachelGross(nil))
            } else if let k = kachel(g) {
                tu(.kachelGross(k))
            } else {
                return .failure(.init("Kachel \(g.anzeige) gibt es nicht"))
            }
        }
        if let n = a["ansicht"]?.stringValue {
            guard standardAnsichten.contains(n) else { return .failure(.init("Unbekannte Ansicht \(n)")) }
            tu(.zweiteAnsicht(n))
            if !auftrag.stand.kacheln.contains(.ansicht) { tu(.kachelZeigen(.ansicht)) }
        }
        if let b = a["blatt"], b != .null {
            guard let blaetter, !blaetter.isEmpty else { return .failure(.init("Noch keine Zeichnungsblätter da")) }
            let treffer: (id: String, titel: String)?
            if let n = b.doubleValue {
                treffer = Int(n) >= 1 && Int(n) <= blaetter.count ? blaetter[Int(n) - 1] : nil
            } else {
                let t = b.stringValue ?? ""
                treffer = blaetter.first { $0.id == t } ?? blaetter.first { $0.titel.localizedCaseInsensitiveCompare(t) == .orderedSame }
                    ?? blaetter.first { $0.titel.localizedCaseInsensitiveContains(t) }
            }
            guard let treffer else {
                return .failure(.init("Blatt \(b.anzeige) gibt es nicht (\(blaetter.count) Blätter)"))
            }
            tu(.blatt(treffer.id))
            if !auftrag.stand.kacheln.contains(.zeichnung) { tu(.kachelZeigen(.zeichnung)) }
        }
        if let m = a["modus"]?.stringValue {
            guard let modus = ArbeitsModus(rawValue: m) else { return .failure(.init("Unbekannter Modus \(m)")) }
            tu(.modus(modus))
        }
        let leisten: [(String, (Bool) -> Oberflaechenbefehl)] = [
            ("leiste_links", Oberflaechenbefehl.leisteLinks), ("leiste_rechts", Oberflaechenbefehl.leisteRechts),
        ]
        for (feld, befehl) in leisten {
            guard let v = a[feld], v != .null else { continue }
            guard let an = v.boolValue else { return .failure(.init("\(feld) ist kein Wahrheitswert")) }
            tu(befehl(an))
        }
        if let z = a["zeitleiste"], z != .null {
            guard let an = z.boolValue else { return .failure(.init("zeitleiste ist kein Wahrheitswert")) }
            tu(.zeitleiste(an))
        }
        auftrag.gewichen = KachelArt.allCases.filter { vorher.contains($0) && !auftrag.stand.kacheln.contains($0) }
            .filter { k in !auftrag.befehle.contains(.kachelSchliessen(k)) && a["ordnen"] == nil }
        return .success(auftrag)
    }
}

public struct FlaecheFehler: Error, Equatable, Sendable {
    public var text: String
    public init(_ text: String) { self.text = text }
}

extension JSONValue {
    /// Wert für eine Meldung: Text ohne Anführungszeichen, Zahl ohne Nachkommastellen.
    fileprivate var anzeige: String {
        if let s = stringValue { return s }
        if let d = doubleValue { return d == d.rounded() ? String(Int(d)) : String(d) }
        return "?"
    }
}

extension AppModel {
    /// Aktionen der Oberfläche, wenn `actions` sie anbietet (App-Kern und Demomodus tun das).
    public var oberflaechenActions: OberflaechenActions? { actions as? OberflaechenActions }
}
