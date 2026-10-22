import CoreGraphics
import CoreText
import Foundation

/// Linienstil nach ISO 128 (Liniengruppe 0,5: breit 0,5 mm, schmal 0,25 mm; Rahmen 0,7 mm nach ISO 5457).
///
/// `muster` sind die sichtbaren Längen als Vielfache der Linienbreite d nach ISO 128-20 Tabelle 3 (Strich 12d, Lücke 3d,
/// langer Strich 24d, Punkt ≤ 0,5d), abwechselnd Strich und Lücke, beginnend mit einem Strich; 0 steht für einen Punkt.
/// Gezeichnet wird mit runden Enden, deshalb werden Striche beim Zerlegen um d kürzer und Lücken um d länger ausgegeben.
public struct LinienStil: Equatable, Sendable {
    public var breite: CGFloat
    public var muster: [CGFloat]?
    /// Breite Linien liegen oben (sichtbare Kanten, Schnittverlauf, Rahmen).
    public var breitLinie: Bool

    public init(breite: CGFloat, muster: [CGFloat]? = nil, breitLinie: Bool = false) {
        self.breite = breite
        self.muster = muster
        self.breitLinie = breitLinie
    }

    /// Breiten der Liniengruppe 0,5 in mm (sehr breit : breit : schmal = 4 : 2 : 1).
    public static let sehrBreit: CGFloat = 1.0
    public static let breit: CGFloat = 0.5
    public static let schmal: CGFloat = 0.25
    /// Blattrahmen und Mittenmarken nach ISO 5457.
    public static let rahmen: CGFloat = 0.7

    public static let strich: [CGFloat] = [12, 3]
    public static let strichPunkt: [CGFloat] = [24, 3, 0, 3]
    public static let strichZweipunkt: [CGFloat] = [24, 3, 0, 3, 0, 3]

    /// Stil einer Linienart; `blatt`: Gruppe „blatt“ (Rahmen, Schriftfeld), dort ist „sichtbar“ der Rahmen.
    /// Unbekannte Linienarten zeichnet die App dünn durchgezogen (Vertrag 1.1).
    public static func fuer(_ art: String, blatt: Bool = false) -> LinienStil {
        switch art {
        case "sichtbar": return LinienStil(breite: blatt ? rahmen : breit, breitLinie: true)
        case "verdeckt": return LinienStil(breite: schmal, muster: strich)
        case "mitte": return LinienStil(breite: schmal, muster: strichPunkt)
        case "schnitt": return LinienStil(breite: breit, muster: strichPunkt, breitLinie: true)
        case "nachbar": return LinienStil(breite: schmal, muster: strichZweipunkt)
        case "schraffur", "duenn", "bruch": return LinienStil(breite: schmal)
        case "neu": return LinienStil(breite: breit, breitLinie: true)  // Bauplan: neue Teile
        case "pfeil": return LinienStil(breite: breit, breitLinie: true)  // Bauplan: Einführpfeile
        default: return LinienStil(breite: schmal)
        }
    }

    /// Ausgegebene Längen (mm) für runde Linienenden: Striche um d kürzer, Lücken um d länger, Punkte fast 0.
    public var ausgabeMuster: [CGFloat]? {
        guard let muster else { return nil }
        let d = breite
        return muster.enumerated().map { i, v in
            i % 2 == 0 ? max(v * d - d, LinienStil.punktLaenge) : v * d + d
        }
    }

    /// Länge eines Punktes; mit runden Enden wird daraus ein Punkt mit Durchmesser d.
    public static let punktLaenge: CGFloat = 0.002
}

/// Ein Text, fertig gesetzt (CoreText-Zeile, Lage, Drehung, Ausrichtung).
public struct TextGrafik: @unchecked Sendable {
    public let text: BlattText
    let zeile: CTLine
    /// Versatz entlang der Grundlinie für die Ausrichtung (links 0, mitte −b/2, rechts −b).
    public let dx: CGFloat
    public let breite: CGFloat
    public let hoehe: CGFloat
    public let abstieg: CGFloat

    /// Zeichen, die osifont nicht hat, durch gleichwertige ersetzen (sonst setzt CoreText sie in einer Ersatzschrift).
    static let ersatz: [Character: String] = [
        "\u{2212}": "\u{2013}",  // Minus → Halbgeviertstrich (deutscher Satz)
        "\u{2026}": "...", "\u{201E}": ",,", "\u{201C}": "\"", "\u{201D}": "\"", "\u{2018}": "'", "\u{2019}": "'",
        "\u{201A}": ",", "\u{2192}": "->",
    ]

    static func fuerSchrift(_ s: String) -> String {
        guard s.contains(where: { ersatz[$0] != nil }) else { return s }
        return s.map { ersatz[$0] ?? String($0) }.joined()
    }

    init(_ t: BlattText) {
        text = t
        let font = BlattSchrift.font(versalhoehe: CGFloat(t.hoehe))
        let attr: [NSAttributedString.Key: Any] = [
            NSAttributedString.Key(kCTFontAttributeName as String): font,
            NSAttributedString.Key(kCTForegroundColorFromContextAttributeName as String): true,
        ]
        zeile = CTLineCreateWithAttributedString(
            NSAttributedString(string: TextGrafik.fuerSchrift(t.text), attributes: attr))
        var asc: CGFloat = 0
        var desc: CGFloat = 0
        var lead: CGFloat = 0
        breite = CGFloat(CTLineGetTypographicBounds(zeile, &asc, &desc, &lead))
        hoehe = CGFloat(t.hoehe)
        abstieg = desc
        switch t.anker {
        case .links: dx = 0
        case .mitte: dx = -breite / 2
        case .rechts: dx = -breite
        }
    }

    /// Ecken des Textrahmens (Grundlinie bis Versalhöhe, mit Abstieg) in Blatt-mm.
    public var ecken: [CGPoint] {
        let a = CGFloat(text.winkel) * .pi / 180
        let c = cos(a)
        let s = sin(a)
        let lokal = [
            CGPoint(x: dx, y: -abstieg), CGPoint(x: dx + breite, y: -abstieg),
            CGPoint(x: dx + breite, y: hoehe), CGPoint(x: dx, y: hoehe),
        ]
        return lokal.map { p in CGPoint(x: text.lage.x + p.x * c - p.y * s, y: text.lage.y + p.x * s + p.y * c) }
    }

    public var rahmen: CGRect { CGRect.huelle(ecken) }

    /// Liegt `p` im Textrahmen (erweitert um `toleranz`)?
    public func enthaelt(_ p: CGPoint, toleranz: CGFloat = 0.5) -> Bool {
        let a = -CGFloat(text.winkel) * .pi / 180
        let x = p.x - text.lage.x
        let y = p.y - text.lage.y
        let lx = x * cos(a) - y * sin(a)
        let ly = x * sin(a) + y * cos(a)
        return lx >= dx - toleranz && lx <= dx + breite + toleranz && ly >= -abstieg - toleranz
            && ly <= hoehe + toleranz
    }

    func zeichne(in ctx: CGContext) {
        ctx.saveGState()
        ctx.translateBy(x: text.lage.x, y: text.lage.y)
        if text.winkel != 0 { ctx.rotate(by: CGFloat(text.winkel) * .pi / 180) }
        ctx.textMatrix = .identity
        ctx.textPosition = CGPoint(x: dx, y: 0)
        CTLineDraw(zeile, ctx)
        ctx.restoreGState()
    }
}

/// Ein Maß, fertig zum Zeichnen.
public struct MassGrafik: @unchecked Sendable {
    public let mass: MassDarstellung
    let linien: CGPath
    let pfeileVoll: CGPath
    let pfeileOffen: CGPath
    public let texte: [TextGrafik]
    /// Hülle aller Linien, Pfeile und Texte (Blatt-mm).
    public let huelle: CGRect

    public init(_ m: MassDarstellung) {
        mass = m
        let l = CGMutablePath()
        for pl in m.linien where pl.count >= 2 { l.addLines(between: pl) }
        linien = l
        let voll = CGMutablePath()
        let offen = CGMutablePath()
        for p in m.pfeile {
            if p.art == "ursprung" {
                // Ursprung der steigenden Bemaßung: offener Kreis (ISO 129-1)
                let r = p.polygon.isEmpty ? 1.2 : CGRect.huelle(p.polygon).width / 2
                offen.addEllipse(in: CGRect(x: p.spitze.x - r, y: p.spitze.y - r, width: 2 * r, height: 2 * r))
            } else if p.polygon.count >= 3 {
                voll.addLines(between: p.polygon)
                voll.closeSubpath()
            } else {
                voll.addPath(MassGrafik.pfeilPfad(p))
            }
        }
        pfeileVoll = voll
        pfeileOffen = offen
        // Maßzahl (bei steigender Bemaßung die „0“ am Ursprung), dann die Zahlen je Lage
        var ts: [TextGrafik] = []
        if !m.text.isEmpty {
            ts.append(TextGrafik(BlattText(
                text: m.text, lage: m.textLage, hoehe: m.textHoehe, winkel: m.textWinkel, anker: .mitte, art: "mass")))
        }
        ts += m.texte.map { TextGrafik($0) }
        texte = ts
        var h = l.boundingBoxOfPath.union(voll.boundingBoxOfPath).union(offen.boundingBoxOfPath)
        for t in ts { h = h.union(t.rahmen) }
        huelle = h
    }

    /// Pfeil aus Spitze, Richtung, Länge und Breite, falls der Kernel kein Polygon schickt.
    static func pfeilPfad(_ p: MassPfeil) -> CGPath {
        let len = max(hypot(p.richtung.dx, p.richtung.dy), 1e-9)
        let u = CGVector(dx: p.richtung.dx / len, dy: p.richtung.dy / len)
        let n = CGVector(dx: -u.dy, dy: u.dx)
        let basis = CGPoint(x: p.spitze.x - u.dx * p.laenge, y: p.spitze.y - u.dy * p.laenge)
        let path = CGMutablePath()
        path.move(to: p.spitze)
        path.addLine(to: CGPoint(x: basis.x + n.dx * p.breite / 2, y: basis.y + n.dy * p.breite / 2))
        path.addLine(to: CGPoint(x: basis.x - n.dx * p.breite / 2, y: basis.y - n.dy * p.breite / 2))
        path.closeSubpath()
        return path
    }

    /// Abstand von `p` zur nächsten Linie, zum nächsten Pfeil oder Text dieses Maßes (0 im Text).
    public func abstand(zu p: CGPoint) -> CGFloat {
        var best = CGFloat.greatestFiniteMagnitude
        for pl in mass.linien { best = min(best, Geometrie2D.abstand(p, zu: pl)) }
        for a in mass.pfeile { best = min(best, hypot(a.spitze.x - p.x, a.spitze.y - p.y)) }
        for t in texte where t.enthaelt(p, toleranz: 0.6) { return 0 }
        return best
    }

    /// Liegt `p` auf einer Zahl dieses Maßes?
    public func trifftText(_ p: CGPoint, toleranz: CGFloat = 0.6) -> Bool {
        texte.contains { $0.enthaelt(p, toleranz: toleranz) }
    }
}

/// Vorbereitete Pfade eines Blatts: je Ansicht und Linienart ein Pfad (Strichmuster schon zerlegt), Maße, Texte.
/// Einmal je Blatt gerechnet (beim Lesen der Nachricht, im Hintergrund); unveränderlich und daher threadsicher.
public final class BlattGrafik: @unchecked Sendable {
    public struct Strich {
        public let art: String
        public let stil: LinienStil
        public let pfad: CGPath
    }

    public struct Gruppe {
        public let id: String
        public let rahmen: CGRect
        public let istBlatt: Bool
        /// Schraffur: geschlossene Ringe der Schnittflächen (Clip, gerade-ungerade) und die Schraffurlinien.
        public let schraffurClip: CGPath?
        public let schraffurLinien: CGPath?
        /// In Zeichenreihenfolge: schmale zuerst, breite oben.
        public let striche: [Strich]
        /// Hülle aller Linien (für das Überspringen außerhalb des Bildausschnitts).
        public let huelle: CGRect
    }

    public let gruppen: [Gruppe]
    public let masse: [MassGrafik]
    public let texte: [TextGrafik]
    public let gefuellt: CGPath
    /// Zahl der Punkte nach dem Zerlegen der Strichmuster (Messwert).
    public let punkte: Int

    public init(gruppen g: [ZeichnungsGruppe], masse m: [MassDarstellung], texte t: [BlattText], gefuellt f: [[CGPoint]]) {
        var zaehler = 0
        gruppen = g.map { BlattGrafik.gruppe($0, zaehler: &zaehler) }
        masse = m.map(MassGrafik.init)
        texte = t.map(TextGrafik.init)
        let fp = CGMutablePath()
        for poly in f where poly.count >= 3 {
            fp.addLines(between: poly)
            fp.closeSubpath()
        }
        gefuellt = fp
        punkte = zaehler
    }

    public func mass(_ id: String) -> MassGrafik? { masse.first { $0.mass.id == id } }

    /// Reihenfolge beim Zeichnen: Schraffur, schmale Linien, dann breite.
    static let reihenfolge = ["schraffur", "bruch", "nachbar", "duenn", "mitte", "verdeckt", "neu", "pfeil", "schnitt",
                              "sichtbar"]

    static func gruppe(_ g: ZeichnungsGruppe, zaehler: inout Int) -> Gruppe {
        var arten = reihenfolge.filter { g.linien[$0] != nil }
        let unbekannt = g.linien.keys.filter { !reihenfolge.contains($0) }.sorted()
        // Unbekannte Linienarten dünn, vor den breiten Linien
        if let i = arten.firstIndex(where: { LinienStil.fuer($0, blatt: g.istBlatt).breitLinie }) {
            arten.insert(contentsOf: unbekannt, at: i)
        } else {
            arten += unbekannt
        }
        var striche: [Strich] = []
        var clip: CGPath?
        var schraffur: CGPath?
        var huelle = CGRect.null
        for art in arten {
            guard let liste = g.linien[art], !liste.isEmpty else { continue }
            let stil = LinienStil.fuer(art, blatt: g.istBlatt)
            if art == "schraffur" {
                let ringe = CGMutablePath()
                let linien = CGMutablePath()
                var hatRinge = false
                for pl in liste {
                    zaehler += pl.count
                    if pl.count >= 4, let a = pl.first, let b = pl.last, hypot(a.x - b.x, a.y - b.y) < 1e-3 {
                        ringe.addLines(between: pl)
                        ringe.closeSubpath()
                        hatRinge = true
                    } else {
                        linien.addLines(between: pl)
                    }
                }
                if hatRinge {
                    clip = ringe
                    striche.append(Strich(art: "schraffur_rand", stil: stil, pfad: ringe))
                }
                schraffur = linien
                huelle = huelle.union(ringe.boundingBoxOfPath).union(linien.boundingBoxOfPath)
                continue
            }
            let pfad = CGMutablePath()
            if let muster = stil.ausgabeMuster {
                for pl in liste { zaehler += Strichmuster.zerlege(pl, muster: muster, in: pfad) }
            } else {
                for pl in liste {
                    pfad.addLines(between: pl)
                    zaehler += pl.count
                }
            }
            huelle = huelle.union(pfad.boundingBoxOfPath)
            striche.append(Strich(art: art, stil: stil, pfad: pfad))
        }
        return Gruppe(id: g.id, rahmen: g.rahmen, istBlatt: g.istBlatt, schraffurClip: clip, schraffurLinien: schraffur,
                      striche: striche, huelle: huelle.isNull ? g.rahmen : huelle)
    }
}

/// Zerlegt Polylinien in Striche nach ISO 128-20: Strich- und Strichpunktlinien beginnen und enden mit einem Strich
/// (das Muster wird je Linie leicht gestreckt oder gestaucht); kurze Linien werden durchgezogen.
public enum Strichmuster {
    /// Hängt die Striche von `pl` an `pfad` an; liefert die Zahl der erzeugten Punkte.
    @discardableResult
    public static func zerlege(_ pl: [CGPoint], muster: [CGFloat], in pfad: CGMutablePath) -> Int {
        guard pl.count >= 2, muster.count >= 2 else { return 0 }
        var laenge: CGFloat = 0
        for i in 1..<pl.count { laenge += hypot(pl[i].x - pl[i - 1].x, pl[i].y - pl[i - 1].y) }
        guard laenge > 0 else { return 0 }
        // Punkte (sehr kurze Striche) bleiben fest, Striche und Lücken werden gestreckt
        let fest = muster.enumerated().reduce(CGFloat(0)) { s, e in
            e.offset % 2 == 0 && e.element <= LinienStil.punktLaenge * 1.01 ? s + e.element : s
        }
        let periode = muster.reduce(0, +)
        let erster = muster[0]
        var n = max(0, ((laenge - erster) / periode).rounded())
        if fest > 0, n.truncatingRemainder(dividingBy: 2) == 1 {
            // Strichpunktlinien (Mittellinien) kreuzen sich im Strich: gerade Zahl an Perioden, damit die Mitte der
            // Linie in einem Strich liegt und nicht im Punkt
            let roh = (laenge - erster) / periode
            n = roh > n || n == 1 ? n + 1 : n - 1
            if n == 2, roh < 1.2 { n = 0 }  // zu kurz für zwei Perioden: durchgezogen (kleine Bohrungen)
        }
        if n == 0 {
            pfad.addLines(between: pl)  // kürzer als ein Strich: durchgezogen
            return pl.count
        }
        let variabel = periode - fest
        var s = (laenge - n * fest) / (n * variabel + erster)
        if !(s.isFinite) || s < 0.5 || s > 2 { s = 1 }
        let laengen = muster.enumerated().map { i, v in
            i % 2 == 0 && v <= LinienStil.punktLaenge * 1.01 ? v : v * s
        }
        var idx = 0
        var rest = laengen[0]
        var an = true
        var punkte = 1
        pfad.move(to: pl[0])
        for i in 1..<pl.count {
            let a = pl[i - 1]
            let b = pl[i]
            let segL = hypot(b.x - a.x, b.y - a.y)
            if segL <= 0 { continue }
            var t: CGFloat = 0
            while segL - t > rest {
                t += rest
                let p = CGPoint(x: a.x + (b.x - a.x) * t / segL, y: a.y + (b.y - a.y) * t / segL)
                if an { pfad.addLine(to: p) } else { pfad.move(to: p) }
                punkte += 1
                idx = (idx + 1) % laengen.count
                rest = laengen[idx]
                an.toggle()
            }
            rest -= segL - t
            if an {
                pfad.addLine(to: b)
                punkte += 1
            }
        }
        return punkte
    }
}

/// Kleine Hilfen für 2D-Geometrie in Blatt-mm.
public enum Geometrie2D {
    /// Abstand eines Punktes zu einer Strecke.
    public static func abstand(_ p: CGPoint, a: CGPoint, b: CGPoint) -> CGFloat {
        let dx = b.x - a.x
        let dy = b.y - a.y
        let l2 = dx * dx + dy * dy
        if l2 <= 1e-12 { return hypot(p.x - a.x, p.y - a.y) }
        let t = max(0, min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2))
        return hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))
    }

    /// Abstand eines Punktes zu einer Polylinie.
    public static func abstand(_ p: CGPoint, zu pl: [CGPoint]) -> CGFloat {
        guard pl.count >= 2 else { return pl.first.map { hypot(p.x - $0.x, p.y - $0.y) } ?? .greatestFiniteMagnitude }
        var best = CGFloat.greatestFiniteMagnitude
        for i in 1..<pl.count { best = min(best, abstand(p, a: pl[i - 1], b: pl[i])) }
        return best
    }

    /// Nächster Punkt auf einer Polylinie.
    public static func naechsterPunkt(_ p: CGPoint, auf pl: [CGPoint]) -> CGPoint {
        guard pl.count >= 2 else { return pl.first ?? p }
        var best = (CGFloat.greatestFiniteMagnitude, p)
        for i in 1..<pl.count {
            let a = pl[i - 1]
            let b = pl[i]
            let dx = b.x - a.x
            let dy = b.y - a.y
            let l2 = dx * dx + dy * dy
            let t = l2 <= 1e-12 ? 0 : max(0, min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2))
            let q = CGPoint(x: a.x + t * dx, y: a.y + t * dy)
            let d = hypot(p.x - q.x, p.y - q.y)
            if d < best.0 { best = (d, q) }
        }
        return best.1
    }
}

extension CGRect {
    /// Kleinstes Rechteck um alle Punkte.
    public static func huelle(_ pts: [CGPoint]) -> CGRect {
        guard let f = pts.first else { return .null }
        var x0 = f.x
        var x1 = f.x
        var y0 = f.y
        var y1 = f.y
        for p in pts.dropFirst() {
            x0 = Swift.min(x0, p.x)
            x1 = Swift.max(x1, p.x)
            y0 = Swift.min(y0, p.y)
            y1 = Swift.max(y1, p.y)
        }
        return CGRect(x: x0, y: y0, width: x1 - x0, height: y1 - y0)
    }
}
