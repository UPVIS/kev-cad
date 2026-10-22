import CoreGraphics
import CoreText
import Foundation

// Zeichenfläche für Berichts- und Bauplanseiten (Strang P6-A2): Millimeter, Ursprung links oben, y nach unten. Dieselbe
// Funktion zeichnet ins PDF, in die Vorschau am Bildschirm und für den Druck. Text bleibt echter Text (CoreText), die
// Schrift kommt als Teilmenge ins PDF.

/// Farben und Schriften der Papierseiten (Druckfarben, unabhängig von Hell und Dunkel am Bildschirm).
public enum ExportStil {
    public static let schrift = "HelveticaNeue"
    public static let schriftMittel = "HelveticaNeue-Medium"
    public static let schriftFett = "HelveticaNeue-Bold"
    public static let schriftLeicht = "HelveticaNeue-Light"

    public static let tinte = farbe(0.106, 0.110, 0.122)
    public static let grau = farbe(0.40, 0.41, 0.44)
    public static let grauHell = farbe(0.62, 0.63, 0.66)
    public static let linie = farbe(0.80, 0.81, 0.83)
    public static let linieFein = farbe(0.89, 0.89, 0.91)
    public static let flaeche = farbe(0.955, 0.957, 0.965)
    public static let flaecheTief = farbe(0.915, 0.918, 0.93)
    /// Akzent: neue Teile, Pfeile, Schrittnummern (Kev CAD Orange).
    public static let akzent = farbe(0.93, 0.38, 0.06)
    public static let akzentHell = farbe(0.995, 0.93, 0.88)
    public static let rot = farbe(0.80, 0.09, 0.11)
    public static let rotHell = farbe(0.99, 0.92, 0.92)
    public static let gelb = farbe(1.0, 0.80, 0.0)
    public static let gelbHell = farbe(1.0, 0.965, 0.82)
    public static let gruen = farbe(0.13, 0.55, 0.27)
    public static let blau = farbe(0.10, 0.42, 0.80)
    public static let weiss = farbe(1, 1, 1)

    public static func farbe(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat, _ a: CGFloat = 1) -> CGColor {
        CGColor(srgbRed: r, green: g, blue: b, alpha: a)
    }

    /// Farbe einer Zuschnittquelle (Rest, Bestand, kaufen) wie in der Zuschnittansicht der App.
    public static func farbe(_ f: ZuschnittFarbe) -> CGColor {
        let c = f.rgb
        return farbe(CGFloat(c.r), CGFloat(c.g), CGFloat(c.b))
    }

    /// Farbe einer Kennzeichnung (Kaufen, Bestand, Rest, Zukauf, Druckteil, Eigenteil) wie im Bereich „Material“.
    public static func farbe(_ k: MaterialKennzeichen) -> CGColor {
        let c = k.rgb
        return farbe(CGFloat(c.r), CGFloat(c.g), CGFloat(c.b))
    }
}

public enum ExportTextAusrichtung: Sendable { case links, rechts, mitte }

/// Schrift für die Leinwand (Größe in Punkt, intern in mm).
public struct ExportSchrift: Sendable {
    public var name: String
    public var pt: CGFloat

    public init(_ name: String = ExportStil.schrift, _ pt: CGFloat) {
        self.name = name
        self.pt = pt
    }

    public static func normal(_ pt: CGFloat) -> ExportSchrift { ExportSchrift(ExportStil.schrift, pt) }
    public static func mittel(_ pt: CGFloat) -> ExportSchrift { ExportSchrift(ExportStil.schriftMittel, pt) }
    public static func fett(_ pt: CGFloat) -> ExportSchrift { ExportSchrift(ExportStil.schriftFett, pt) }
    public static func leicht(_ pt: CGFloat) -> ExportSchrift { ExportSchrift(ExportStil.schriftLeicht, pt) }

    /// CoreText-Schrift in mm (1 pt = 25,4/72 mm).
    public var ctFont: CTFont {
        let key = "\(name)|\(pt)"
        if let f = ExportSchriftCache.shared.get(key) { return f }
        let f = CTFontCreateWithName(name as CFString, pt / ExportSeitenformat.ptJeMM, nil)
        ExportSchriftCache.shared.set(key, f)
        return f
    }

    /// Zeilenhöhe in mm (Ober- plus Unterlänge plus Durchschuss).
    public var zeilenhoehe: CGFloat {
        let f = ctFont
        return CTFontGetAscent(f) + CTFontGetDescent(f) + max(CTFontGetLeading(f), pt * 0.12 / ExportSeitenformat.ptJeMM)
    }

    public var oberlaenge: CGFloat { CTFontGetAscent(ctFont) }
    public var versalhoehe: CGFloat { CTFontGetCapHeight(ctFont) }
}

final class ExportSchriftCache: @unchecked Sendable {
    static let shared = ExportSchriftCache()
    private let lock = NSLock()
    private var fonts: [String: CTFont] = [:]

    func get(_ k: String) -> CTFont? {
        lock.lock()
        defer { lock.unlock() }
        return fonts[k]
    }

    func set(_ k: String, _ f: CTFont) {
        lock.lock()
        fonts[k] = f
        lock.unlock()
    }
}

/// Satz eines Textes: Zeilen für eine Breite, ohne zu zeichnen (für Höhen beim Seitenumbruch).
public struct ExportSatz {
    public var zeilen: [CTLine]
    public var schrift: ExportSchrift
    public var zeilenabstand: CGFloat

    public var hoehe: CGFloat { CGFloat(zeilen.count) * schrift.zeilenhoehe * zeilenabstand }

    public static func attributiert(_ s: String, _ schrift: ExportSchrift, _ farbe: CGColor, laufweite: CGFloat = 0)
        -> NSAttributedString
    {
        var attrs: [NSAttributedString.Key: Any] = [
            NSAttributedString.Key(kCTFontAttributeName as String): schrift.ctFont,
            NSAttributedString.Key(kCTForegroundColorAttributeName as String): farbe,
        ]
        if laufweite != 0 { attrs[NSAttributedString.Key(kCTKernAttributeName as String)] = laufweite }
        return NSAttributedString(string: ersetzt(s, schrift.ctFont), attributes: attrs)
    }

    /// Zeichen, die der Berichtsschrift fehlen, und ihr Ersatz aus der Schrift selbst. Sonst setzt CoreText eine
    /// Ersatzschrift ein (etwa Lucida Grande für „→“), und das PDF bettet eine dritte Schrift ein.
    static let ersatz: [Character: String] = [
        "→": "›", "⇒": "›", "⟶": "›", "←": "‹", "⇐": "‹", "↔": "‹›", "⌀": "Ø", "∅": "Ø", "⋅": "·", "∙": "·",
        "✓": "ja", "✔": "ja", "✗": "nein", "✘": "nein",
    ]

    /// Text mit Ersatz für Zeichen, die `font` nicht hat (nur bekannte, siehe `ersatz`; alles andere bleibt).
    public static func ersetzt(_ s: String, _ font: CTFont) -> String {
        guard s.unicodeScalars.contains(where: { $0.value > 0x2000 }) else { return s }
        var out = ""
        out.reserveCapacity(s.count)
        for ch in s {
            if let r = ersatz[ch] {
                let u = Array(String(ch).utf16)
                var g = [CGGlyph](repeating: 0, count: u.count)
                if !CTFontGetGlyphsForCharacters(font, u, &g, u.count) {
                    out += r
                    continue
                }
            }
            out.append(ch)
        }
        return out
    }

    public init(_ text: String, breite: CGFloat, schrift: ExportSchrift, farbe: CGColor = ExportStil.tinte,
                zeilenabstand: CGFloat = 1.0, maxZeilen: Int = 0)
    {
        self.schrift = schrift
        self.zeilenabstand = zeilenabstand
        let a = Self.attributiert(text, schrift, farbe)
        let ts = CTTypesetterCreateWithAttributedString(a)
        var out: [CTLine] = []
        var start = 0
        let n = a.length
        while start < n {
            var count = CTTypesetterSuggestLineBreak(ts, start, Double(max(1, breite)))
            if count <= 0 { count = 1 }
            if maxZeilen > 0 && out.count == maxZeilen - 1 && start + count < n {
                // letzte erlaubte Zeile: Rest mit Auslassungszeichen abschneiden
                let rest = CTTypesetterCreateLine(ts, CFRange(location: start, length: n - start))
                let ell = CTLineCreateWithAttributedString(Self.attributiert("…", schrift, farbe))
                out.append(CTLineCreateTruncatedLine(rest, Double(breite), .end, ell) ?? rest)
                start = n
                break
            }
            out.append(CTTypesetterCreateLine(ts, CFRange(location: start, length: count)))
            start += count
        }
        zeilen = out
    }
}

/// Zeichenfläche in mm mit Ursprung links oben.
public final class ExportLeinwand {
    public let ctx: CGContext
    public let groesse: CGSize

    /// `ctx` in Punkt mit Ursprung links unten (PDF-Kontext); `groesse` in mm.
    public init(ctx: CGContext, groesse: CGSize, punktJeMM: CGFloat = ExportSeitenformat.ptJeMM) {
        self.ctx = ctx
        self.groesse = groesse
        ctx.translateBy(x: 0, y: groesse.height * punktJeMM)
        ctx.scaleBy(x: punktJeMM, y: -punktJeMM)
        ctx.setLineJoin(.round)
        ctx.setLineCap(.round)
    }

    // MARK: Text

    public static func breite(_ s: String, _ schrift: ExportSchrift) -> CGFloat {
        let line = CTLineCreateWithAttributedString(ExportSatz.attributiert(s, schrift, ExportStil.tinte))
        return CGFloat(CTLineGetTypographicBounds(line, nil, nil, nil))
    }

    /// Eine Zeile, `y` ist die Grundlinie. Mit `maxBreite` wird gekürzt (…). Liefert die gezeichnete Breite.
    @discardableResult
    public func text(_ s: String, x: CGFloat, y: CGFloat, _ schrift: ExportSchrift, farbe: CGColor = ExportStil.tinte,
                     _ ausrichtung: ExportTextAusrichtung = .links, maxBreite: CGFloat? = nil, laufweite: CGFloat = 0)
        -> CGFloat
    {
        var line = CTLineCreateWithAttributedString(ExportSatz.attributiert(s, schrift, farbe, laufweite: laufweite))
        var w = CGFloat(CTLineGetTypographicBounds(line, nil, nil, nil))
        if let m = maxBreite, w > m {
            let ell = CTLineCreateWithAttributedString(ExportSatz.attributiert("…", schrift, farbe))
            if let t = CTLineCreateTruncatedLine(line, Double(m), .end, ell) {
                line = t
                w = CGFloat(CTLineGetTypographicBounds(line, nil, nil, nil))
            }
        }
        let x0: CGFloat
        switch ausrichtung {
        case .links: x0 = x
        case .rechts: x0 = x - w
        case .mitte: x0 = x - w / 2
        }
        zeichneZeile(line, x: x0, y: y)
        return w
    }

    func zeichneZeile(_ line: CTLine, x: CGFloat, y: CGFloat) {
        ctx.saveGState()
        ctx.textMatrix = .identity
        ctx.translateBy(x: x, y: y)
        ctx.scaleBy(x: 1, y: -1)
        ctx.textPosition = .zero
        CTLineDraw(line, ctx)
        ctx.restoreGState()
    }

    /// Absatz mit Umbruch; `y` ist die Oberkante. Liefert die Höhe.
    @discardableResult
    public func absatz(_ s: String, x: CGFloat, y: CGFloat, breite: CGFloat, _ schrift: ExportSchrift,
                       farbe: CGColor = ExportStil.tinte, zeilenabstand: CGFloat = 1.0,
                       _ ausrichtung: ExportTextAusrichtung = .links, maxZeilen: Int = 0) -> CGFloat
    {
        let satz = ExportSatz(s, breite: breite, schrift: schrift, farbe: farbe, zeilenabstand: zeilenabstand,
                              maxZeilen: maxZeilen)
        zeichne(satz, x: x, y: y, breite: breite, ausrichtung)
        return satz.hoehe
    }

    public func zeichne(_ satz: ExportSatz, x: CGFloat, y: CGFloat, breite: CGFloat,
                        _ ausrichtung: ExportTextAusrichtung = .links)
    {
        let lh = satz.schrift.zeilenhoehe * satz.zeilenabstand
        var base = y + satz.schrift.oberlaenge + (lh - satz.schrift.zeilenhoehe) / 2
        for line in satz.zeilen {
            let w = CGFloat(CTLineGetTypographicBounds(line, nil, nil, nil))
            let x0 = ausrichtung == .links ? x : ausrichtung == .rechts ? x + breite - w : x + (breite - w) / 2
            zeichneZeile(line, x: x0, y: base)
            base += lh
        }
    }

    // MARK: Formen

    public func linie(_ a: CGPoint, _ b: CGPoint, breite: CGFloat = 0.2, farbe: CGColor = ExportStil.linie,
                      strich: [CGFloat]? = nil)
    {
        ctx.saveGState()
        ctx.setStrokeColor(farbe)
        ctx.setLineWidth(max(0.05, breite))
        if let strich { ctx.setLineDash(phase: 0, lengths: strich) }
        ctx.move(to: a)
        ctx.addLine(to: b)
        ctx.strokePath()
        ctx.restoreGState()
    }

    public func rechteck(_ r: CGRect, fuellung: CGColor? = nil, rand: CGColor? = nil, randBreite: CGFloat = 0.25,
                         radius: CGFloat = 0, strich: [CGFloat]? = nil)
    {
        let path = radius > 0
            ? CGPath(roundedRect: r, cornerWidth: min(radius, r.width / 2), cornerHeight: min(radius, r.height / 2),
                     transform: nil)
            : CGPath(rect: r, transform: nil)
        ctx.saveGState()
        if let fuellung {
            ctx.setFillColor(fuellung)
            ctx.addPath(path)
            ctx.fillPath()
        }
        if let rand {
            ctx.setStrokeColor(rand)
            ctx.setLineWidth(max(0.05, randBreite))
            if let strich { ctx.setLineDash(phase: 0, lengths: strich) }
            ctx.addPath(path)
            ctx.strokePath()
        }
        ctx.restoreGState()
    }

    public func kreis(_ mitte: CGPoint, radius: CGFloat, fuellung: CGColor? = nil, rand: CGColor? = nil,
                      randBreite: CGFloat = 0.25)
    {
        let r = CGRect(x: mitte.x - radius, y: mitte.y - radius, width: 2 * radius, height: 2 * radius)
        ctx.saveGState()
        if let fuellung {
            ctx.setFillColor(fuellung)
            ctx.fillEllipse(in: r)
        }
        if let rand {
            ctx.setStrokeColor(rand)
            ctx.setLineWidth(randBreite)
            ctx.strokeEllipse(in: r)
        }
        ctx.restoreGState()
    }

    /// Bild in ein Rechteck einpassen (Seitenverhältnis bleibt), mittig.
    public func bild(_ image: CGImage, in r: CGRect) {
        let w = CGFloat(image.width), h = CGFloat(image.height)
        guard w > 0, h > 0, r.width > 0, r.height > 0 else { return }
        let s = min(r.width / w, r.height / h)
        let ziel = CGRect(x: r.midX - w * s / 2, y: r.midY - h * s / 2, width: w * s, height: h * s)
        ctx.saveGState()
        ctx.interpolationQuality = .high
        // y nach unten: das Bild für CGContext.draw zurückdrehen
        ctx.translateBy(x: ziel.minX, y: ziel.maxY)
        ctx.scaleBy(x: 1, y: -1)
        ctx.draw(image, in: CGRect(origin: .zero, size: ziel.size))
        ctx.restoreGState()
    }

    /// Anklickbarer Verweis im PDF (in anderen Kontexten wirkungslos).
    public func verweis(_ url: URL, _ r: CGRect) {
        let geraet = r.applying(ctx.ctm)
        ctx.saveGState()
        ctx.concatenate(ctx.ctm.inverted())
        ctx.setURL(url as CFURL, for: geraet.standardized)
        ctx.restoreGState()
    }

    /// Abhakkästchen.
    public func kaestchen(_ r: CGRect) {
        rechteck(r, rand: ExportStil.grau, randBreite: 0.25, radius: 0.6)
    }
}
