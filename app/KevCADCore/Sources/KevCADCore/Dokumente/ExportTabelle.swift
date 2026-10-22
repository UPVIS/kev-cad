import CoreGraphics
import Foundation

// Tabellen und Seitenfluss der Berichte (Strang P6-A2): Zeilen brechen nie mitten auf der Seite, der Tabellenkopf
// wiederholt sich, Gruppenüberschriften bleiben bei ihrer ersten Zeile, Summen bei der letzten.

/// Eine Zelle: Text, optional zweite Zeile (grau), Bild, Kästchen, Verweis.
public struct ExportZelle {
    public var text: String
    public var unter: String?
    public var fett: Bool
    public var farbe: CGColor?
    public var bild: CGImage?
    public var kaestchen: Bool
    public var verweis: URL?

    public init(_ text: String = "", unter: String? = nil, fett: Bool = false, farbe: CGColor? = nil,
                bild: CGImage? = nil, kaestchen: Bool = false, verweis: URL? = nil)
    {
        self.text = text
        self.unter = unter
        self.fett = fett
        self.farbe = farbe
        self.bild = bild
        self.kaestchen = kaestchen
        self.verweis = verweis
    }
}

public struct ExportZeile {
    public enum Art { case normal, gruppe(String), summe }
    public var art: Art
    public var zellen: [String: ExportZelle]

    public init(_ zellen: [String: ExportZelle]) {
        art = .normal
        self.zellen = zellen
    }

    public static func gruppe(_ titel: String) -> ExportZeile {
        var z = ExportZeile([:])
        z.art = .gruppe(titel)
        return z
    }

    public static func summe(_ zellen: [String: ExportZelle]) -> ExportZeile {
        var z = ExportZeile(zellen)
        z.art = .summe
        return z
    }

    var istGruppe: Bool { if case .gruppe = art { return true } else { return false } }
    var istSumme: Bool { if case .summe = art { return true } else { return false } }
}

public struct ExportTabelle {
    public var spalten: [ExportSpalte]
    public var zeilen: [ExportZeile]
    public var schrift = ExportSchrift.normal(8.5)
    public var kopfSchrift = ExportSchrift.mittel(7)
    /// Höhe der Vorschaubilder in mm (nur mit Bildspalte).
    public var bildHoehe: CGFloat = 13
    public var polster: CGFloat = 1.6

    public init(spalten: [ExportSpalte], zeilen: [ExportZeile]) {
        self.spalten = spalten
        self.zeilen = zeilen
    }

    public var kopfHoehe: CGFloat { 7.5 }

    /// Spaltenbreiten für die Gesamtbreite: erst die Mindestbreiten, der Rest nach Gewicht (ohne Gewicht: auf die
    /// breiteste Textspalte).
    public func breiten(_ gesamt: CGFloat) -> [CGFloat] {
        var b = spalten.map(\.mindestbreite)
        let rest = gesamt - b.reduce(0, +)
        let g = spalten.map(\.gewicht).reduce(0, +)
        if rest > 0 {
            if g > 0 {
                for (i, s) in spalten.enumerated() { b[i] += rest * s.gewicht / g }
            } else if !b.isEmpty {
                b[b.count - 1] += rest
            }
        } else if rest < 0 {
            let s = gesamt / max(1, b.reduce(0, +))
            b = b.map { $0 * s }
        }
        return b
    }

    func zeilenHoehe(_ z: ExportZeile, _ breiten: [CGFloat]) -> CGFloat {
        if z.istGruppe { return 7.5 }
        var h = schrift.zeilenhoehe
        for (i, s) in spalten.enumerated() {
            guard let c = z.zellen[s.id] else { continue }
            let w = breiten[i] - 2 * polster
            if c.bild != nil { h = max(h, bildHoehe) }
            var t = ExportSatz(c.text, breite: w, schrift: c.fett ? .fett(schrift.pt) : schrift, maxZeilen: 3).hoehe
            if let u = c.unter, !u.isEmpty {
                t += ExportSatz(u, breite: w, schrift: .normal(schrift.pt - 1.5), maxZeilen: 2).hoehe + 0.3
            }
            h = max(h, t)
        }
        return h + 2 * polster + 0.4
    }

    /// Höhen aller Zeilen für eine Gesamtbreite.
    public func hoehen(_ gesamt: CGFloat) -> [CGFloat] {
        let b = breiten(gesamt)
        return zeilen.map { zeilenHoehe($0, b) }
    }

    /// Seitenumbruch: Bereiche der Zeilen je Seite. `erste` ist der Platz auf der ersten Seite, `folgende` auf jeder
    /// weiteren, jeweils ohne den Kopf (`kopf`), der auf jeder Seite wiederholt wird. Eine Zeile wird nie geteilt; eine
    /// Gruppenüberschrift kommt nie als letzte Zeile auf eine Seite, eine Summenzeile nie allein auf eine neue.
    /// Ist auf der ersten Seite nicht einmal Platz für eine Zeile, beginnt die Tabelle mit einem leeren Bereich.
    public static func umbruch(hoehen: [CGFloat], gruppen: Set<Int> = [], summen: Set<Int> = [], kopf: CGFloat,
                               erste: CGFloat, folgende: CGFloat) -> [Range<Int>]
    {
        var seiten: [Range<Int>] = []
        var start = 0
        var platz = erste - kopf
        var i = 0
        while i < hoehen.count {
            var used: CGFloat = 0
            var j = start
            while j < hoehen.count && used + hoehen[j] <= platz + 0.001 {
                used += hoehen[j]
                j += 1
            }
            if j == start {
                if seiten.isEmpty && erste < folgende {  // erste Seite zu voll: neu anfangen
                    seiten.append(start..<start)
                    platz = folgende - kopf
                    continue
                }
                j = start + 1  // Zeile höher als eine Seite: allein, wird abgeschnitten gezeichnet
            }
            if j < hoehen.count {
                // Gruppenüberschrift nicht als letzte Zeile, Summe nicht allein auf der nächsten Seite
                while j - 1 > start && gruppen.contains(j - 1) { j -= 1 }
                if summen.contains(j) && j == hoehen.count - 1 && j - 1 > start { j -= 1 }
            }
            seiten.append(start..<j)
            start = j
            i = j
            platz = folgende - kopf
        }
        if seiten.isEmpty { seiten.append(0..<0) }
        return seiten
    }

    public var gruppenIndizes: Set<Int> { Set(zeilen.indices.filter { zeilen[$0].istGruppe }) }
    public var summenIndizes: Set<Int> { Set(zeilen.indices.filter { zeilen[$0].istSumme }) }

    /// Zeichnet Kopf und die Zeilen `bereich` ab `oben`; liefert die Höhe.
    @discardableResult
    public func zeichne(_ l: ExportLeinwand, x: CGFloat, oben: CGFloat, breite: CGFloat, bereich: Range<Int>)
        -> CGFloat
    {
        let b = breiten(breite)
        var y = oben
        // Kopf: kleine Versalien grau, Linie darunter
        var xs: [CGFloat] = []
        var cx = x
        for w in b {
            xs.append(cx)
            cx += w
        }
        for (i, s) in spalten.enumerated() {
            let w = b[i] - 2 * polster
            let base = y + kopfHoehe - 2.4
            let ax = s.ausrichtung == .rechts ? xs[i] + b[i] - polster : s.ausrichtung == .mitte ? xs[i] + b[i] / 2
                : xs[i] + polster
            l.text(s.titel.uppercased(), x: ax, y: base, kopfSchrift, farbe: ExportStil.grau,
                   s.ausrichtung == .rechts ? .rechts : s.ausrichtung == .mitte ? .mitte : .links, maxBreite: w,
                   laufweite: 0.08)
        }
        y += kopfHoehe
        l.linie(CGPoint(x: x, y: y), CGPoint(x: x + breite, y: y), breite: 0.35, farbe: ExportStil.tinte)
        var gerade = false
        for k in bereich {
            let z = zeilen[k]
            let h = zeilenHoehe(z, b)
            if case .gruppe(let titel) = z.art {
                l.rechteck(CGRect(x: x, y: y, width: breite, height: h), fuellung: ExportStil.flaecheTief)
                l.text(titel, x: x + polster, y: y + h - 2.4, .fett(schrift.pt), farbe: ExportStil.tinte,
                       maxBreite: breite - 2 * polster)
                y += h
                gerade = false
                continue
            }
            if z.istSumme {
                l.linie(CGPoint(x: x, y: y), CGPoint(x: x + breite, y: y), breite: 0.35, farbe: ExportStil.tinte)
            } else if gerade {
                l.rechteck(CGRect(x: x, y: y, width: breite, height: h), fuellung: ExportStil.flaeche)
            }
            gerade.toggle()
            for (i, s) in spalten.enumerated() {
                guard let c = z.zellen[s.id] else { continue }
                let w = b[i] - 2 * polster
                let zelle = CGRect(x: xs[i] + polster, y: y + polster, width: w, height: h - 2 * polster)
                if let img = c.bild {
                    l.bild(img, in: zelle.insetBy(dx: 0, dy: 0))
                }
                if c.kaestchen {
                    let k = min(3.6, zelle.height)
                    l.kaestchen(CGRect(x: zelle.midX - k / 2, y: zelle.minY + 0.3, width: k, height: k))
                }
                if !c.text.isEmpty {
                    let sch = c.fett || z.istSumme ? ExportSchrift.fett(schrift.pt) : schrift
                    let ausr: ExportTextAusrichtung = s.ausrichtung == .rechts ? .rechts
                        : s.ausrichtung == .mitte ? .mitte : .links
                    let hh = l.absatz(c.text, x: zelle.minX, y: zelle.minY, breite: w, sch,
                                      farbe: c.farbe ?? ExportStil.tinte, ausr, maxZeilen: 3)
                    if let u = c.unter, !u.isEmpty {
                        l.absatz(u, x: zelle.minX, y: zelle.minY + hh + 0.3, breite: w, .normal(schrift.pt - 1.5),
                                 farbe: ExportStil.grau, ausr, maxZeilen: 2)
                    }
                    if let url = c.verweis { l.verweis(url, zelle) }
                }
            }
            y += h
            if !z.istSumme {
                l.linie(CGPoint(x: x, y: y), CGPoint(x: x + breite, y: y), breite: 0.12, farbe: ExportStil.linieFein)
            }
        }
        return y - oben
    }
}

// MARK: - Seitenfluss

/// Ein Block im Fluss einer Seite: feste Höhe (nie geteilt) oder Tabelle (bricht zwischen Zeilen).
public enum ExportBlock {
    /// `mitNaechstem`: nicht als letzter Block einer Seite (Überschriften).
    case fest(hoehe: CGFloat, mitNaechstem: Bool, zeichne: (ExportLeinwand, CGRect) -> Void)
    case tabelle(ExportTabelle)
    case abstand(CGFloat)
    case neueSeite
    /// Eintrag der PDF-Gliederung auf der Seite, auf der der nächste Block landet.
    case marke(String)
}

/// Eine verteilte Seite: Zeichenaufträge und Gliederungseinträge.
public struct ExportFlussSeite {
    public var auftraege: [ExportFluss.Auftrag] = []
    public var marken: [String] = []
}

/// Ordnet Blöcke auf Seiten an. Ergebnis je Seite: Zeichenaufträge mit ihrem Rechteck im Inhaltsbereich.
public enum ExportFluss {
    public typealias Auftrag = (rect: CGRect, zeichne: (ExportLeinwand, CGRect) -> Void)

    public static func verteile(_ bloecke: [ExportBlock], inhalt: CGRect) -> [ExportFlussSeite] {
        var seiten: [ExportFlussSeite] = [ExportFlussSeite()]
        var y = inhalt.minY
        var offen: [(CGFloat, (ExportLeinwand, CGRect) -> Void)] = []  // „mitNaechstem“-Blöcke, die warten
        var marken: [String] = []
        func neueSeite() {
            seiten.append(ExportFlussSeite())
            y = inhalt.minY
        }
        func platziere(_ h: CGFloat, _ f: @escaping (ExportLeinwand, CGRect) -> Void) {
            seiten[seiten.count - 1].auftraege.append((CGRect(x: inhalt.minX, y: y, width: inhalt.width, height: h), f))
            seiten[seiten.count - 1].marken += marken
            marken = []
            y += h
        }
        func offeneHoehe() -> CGFloat { offen.reduce(0) { $0 + $1.0 } }
        func offeneSetzen() {
            for (h, f) in offen { platziere(h, f) }
            offen = []
        }
        for b in bloecke {
            switch b {
            case .marke(let t):
                marken.append(t)
            case .abstand(let h):
                if !offen.isEmpty {
                    offen.append((h, { _, _ in }))
                } else if y > inhalt.minY {
                    y = min(inhalt.maxY, y + h)
                }
            case .neueSeite:
                offeneSetzen()
                if !(seiten.last?.auftraege.isEmpty ?? true) { neueSeite() }
            case .fest(let h, let mit, let f):
                if mit {
                    offen.append((h, f))
                    continue
                }
                let bedarf = offeneHoehe() + h
                if y + bedarf > inhalt.maxY + 0.001 && y > inhalt.minY { neueSeite() }
                offeneSetzen()
                platziere(h, f)
            case .tabelle(let t):
                let hoehen = t.hoehen(inhalt.width)
                let ersteZeile = hoehen.first ?? 0
                // Überschrift und Kopf mit mindestens einer Zeile zusammenhalten
                if y + offeneHoehe() + t.kopfHoehe + ersteZeile > inhalt.maxY + 0.001 && y > inhalt.minY {
                    neueSeite()
                }
                offeneSetzen()
                let bereiche = ExportTabelle.umbruch(
                    hoehen: hoehen, gruppen: t.gruppenIndizes, summen: t.summenIndizes, kopf: t.kopfHoehe,
                    erste: inhalt.maxY - y, folgende: inhalt.height)
                for (n, r) in bereiche.enumerated() {
                    if n > 0 { neueSeite() }
                    if r.isEmpty { continue }
                    let h = t.kopfHoehe + r.reduce(CGFloat(0)) { $0 + hoehen[$1] } + 0.5
                    platziere(h) { l, rect in
                        t.zeichne(l, x: rect.minX, oben: rect.minY, breite: rect.width, bereich: r)
                    }
                }
            }
        }
        offeneSetzen()
        if !marken.isEmpty { seiten[seiten.count - 1].marken += marken }
        if seiten.count > 1, seiten.last?.auftraege.isEmpty == true {
            let rest = seiten.removeLast()
            seiten[seiten.count - 1].marken += rest.marken
        }
        return seiten
    }
}
