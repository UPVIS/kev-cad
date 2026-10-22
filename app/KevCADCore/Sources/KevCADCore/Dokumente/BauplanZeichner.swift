import CoreGraphics
import Foundation

// Strichbild eines Bauplanschritts zeichnen (Strang P6-A2): dieselbe Funktion für die Schrittansicht am Bildschirm, das
// PDF und den Druck. Linien im Stil einer IKEA-Anleitung: schwarze Kontur, neue Teile in der Akzentfarbe etwas kräftiger,
// Einführpfeile mit gefüllter Spitze.

public struct BauplanPalette: Sendable {
    public var tinte: CGColor
    public var neu: CGColor
    public var pfeil: CGColor
    public var duenn: CGColor
    public var verdeckt: CGColor

    public init(tinte: CGColor, neu: CGColor, pfeil: CGColor, duenn: CGColor, verdeckt: CGColor) {
        self.tinte = tinte
        self.neu = neu
        self.pfeil = pfeil
        self.duenn = duenn
        self.verdeckt = verdeckt
    }

    /// Papier (PDF, Druck, helle Ansicht).
    public static let papier = BauplanPalette(
        tinte: ExportStil.tinte, neu: ExportStil.akzent, pfeil: ExportStil.akzent, duenn: ExportStil.grauHell,
        verdeckt: ExportStil.grauHell)

    /// Dunkle Ansicht am Bildschirm.
    public static let dunkel = BauplanPalette(
        tinte: ExportStil.farbe(0.90, 0.90, 0.92), neu: ExportStil.farbe(1.0, 0.58, 0.25),
        pfeil: ExportStil.farbe(1.0, 0.58, 0.25), duenn: ExportStil.farbe(0.50, 0.50, 0.54),
        verdeckt: ExportStil.farbe(0.45, 0.45, 0.50))
}

public enum BauplanZeichner {
    /// Linienbreiten in mm auf dem Papier (unabhängig von der Bildgröße).
    public static let breiten: [String: CGFloat] = [
        "sichtbar": 0.30, "neu": 0.42, "pfeil": 0.40, "duenn": 0.15, "verdeckt": 0.15, "mitte": 0.15,
        "schnitt": 0.35, "schraffur": 0.12, "nachbar": 0.15, "bruch": 0.15,
    ]

    /// Abbildung vom Bildfeld (y nach oben) in ein Zielrechteck (y nach unten, Einheit des Kontexts), eingepasst auf
    /// den Umriss der Linien mit etwas Rand, Seitenverhältnis bleibt.
    public static func abbildung(_ bild: BauplanStrichbild, ziel: CGRect, rand: CGFloat = 0.04) -> CGAffineTransform {
        var quelle = bild.umriss ?? bild.rahmen
        if quelle.width < 1 || quelle.height < 1 { quelle = bild.rahmen }
        let pad = max(quelle.width, quelle.height) * rand
        quelle = quelle.insetBy(dx: -pad, dy: -pad)
        let s = min(ziel.width / quelle.width, ziel.height / quelle.height)
        let ox = ziel.midX - quelle.midX * s
        let oy = ziel.midY + quelle.midY * s
        return CGAffineTransform(a: s, b: 0, c: 0, d: -s, tx: ox, ty: oy)
    }

    /// Zeichnet das Bild in `ziel` (Koordinaten des Kontexts, y nach unten). `einheitJeMM` rechnet Papier-mm in die
    /// Einheit des Kontexts um (Leinwand: 1; Bildschirm: Punkte je mm der Darstellung).
    public static func zeichne(_ bild: BauplanStrichbild, in ctx: CGContext, ziel: CGRect,
                               palette: BauplanPalette = .papier, einheitJeMM: CGFloat = 1)
    {
        let t = abbildung(bild, ziel: ziel)
        ctx.saveGState()
        ctx.clip(to: ziel)
        ctx.setLineJoin(.round)
        ctx.setLineCap(.round)
        // Reihenfolge: dünne und verdeckte zuerst, dann Kontur, neue Teile und Pfeile obenauf
        let reihenfolge = ["duenn", "verdeckt", "mitte", "nachbar", "bruch", "schraffur", "schnitt", "sichtbar", "neu",
                           "pfeil"]
        let arten = reihenfolge + bild.linien.keys.filter { !reihenfolge.contains($0) }.sorted()
        for art in arten {
            guard let pls = bild.linien[art], !pls.isEmpty else { continue }
            let farbe: CGColor
            switch art {
            case "neu": farbe = palette.neu
            case "pfeil": farbe = palette.pfeil
            case "duenn", "mitte", "nachbar", "bruch", "schraffur": farbe = palette.duenn
            case "verdeckt": farbe = palette.verdeckt
            default: farbe = palette.tinte
            }
            let breite = (breiten[art] ?? 0.15) * einheitJeMM
            ctx.setStrokeColor(farbe)
            ctx.setLineWidth(breite)
            switch art {
            case "verdeckt": ctx.setLineDash(phase: 0, lengths: [1.2 * einheitJeMM, 0.8 * einheitJeMM])
            case "mitte": ctx.setLineDash(phase: 0, lengths: [4 * einheitJeMM, 0.8 * einheitJeMM, 0.6 * einheitJeMM,
                                                               0.8 * einheitJeMM])
            default: ctx.setLineDash(phase: 0, lengths: [])
            }
            let path = CGMutablePath()
            var spitzen: [[CGPoint]] = []
            for pl in pls where pl.count >= 2 {
                let pts = pl.map { $0.applying(t) }
                if art == "pfeil" && pts.count == 3 {
                    spitzen.append(pts)
                    continue
                }
                path.addLines(between: pts)
            }
            ctx.addPath(path)
            ctx.strokePath()
            if !spitzen.isEmpty {
                // Pfeilspitzen als gefüllte Dreiecke
                ctx.setFillColor(farbe)
                for s in spitzen {
                    let tri = CGMutablePath()
                    tri.addLines(between: s)
                    tri.closeSubpath()
                    ctx.addPath(tri)
                }
                ctx.drawPath(using: .fillStroke)
            }
        }
        ctx.restoreGState()
    }
}

/// Werkzeug-Piktogramme als Vektor (für PDF und Druck; am Bildschirm stehen SF Symbols). Gezeichnet in ein Quadrat,
/// y nach unten, Strich in `farbe`.
public enum ExportPiktogramm {
    public static func zeichne(_ art: BauplanWerkzeug.Art, in r: CGRect, ctx: CGContext, farbe: CGColor) {
        let s = min(r.width, r.height)
        let o = CGPoint(x: r.midX - s / 2, y: r.midY - s / 2)
        func p(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: o.x + x * s, y: o.y + y * s) }
        ctx.saveGState()
        ctx.setStrokeColor(farbe)
        ctx.setFillColor(farbe)
        ctx.setLineWidth(s * 0.07)
        ctx.setLineCap(.round)
        ctx.setLineJoin(.round)
        let path = CGMutablePath()
        let fuellen = CGMutablePath()
        func bogen(_ c: CGPoint, _ radius: CGFloat, _ a0: CGFloat, _ a1: CGFloat) {
            path.move(to: CGPoint(x: c.x + radius * cos(a0), y: c.y + radius * sin(a0)))
            path.addArc(center: c, radius: radius, startAngle: a0, endAngle: a1, clockwise: false)
        }
        switch art {
        case .saege:
            // Bügelsäge: Bügel, Blatt mit Zähnen, Griff
            path.addLines(between: [p(0.12, 0.62), p(0.12, 0.30), p(0.80, 0.30), p(0.80, 0.62)])
            path.addLines(between: [p(0.12, 0.62), p(0.80, 0.62)])
            var zahn: [CGPoint] = []
            for i in 0...8 {
                let x = 0.14 + CGFloat(i) * 0.075
                zahn.append(p(x, 0.62))
                zahn.append(p(x + 0.037, 0.70))
            }
            path.addLines(between: zahn)
            fuellen.addRoundedRect(in: CGRect(origin: p(0.80, 0.42), size: CGSize(width: s * 0.14, height: s * 0.26)),
                                   cornerWidth: s * 0.04, cornerHeight: s * 0.04)
        case .bohrer:
            // Bohrmaschine: Gehäuse, Griff, Bohrer
            fuellen.addRoundedRect(in: CGRect(origin: p(0.28, 0.22), size: CGSize(width: s * 0.46, height: s * 0.22)),
                                   cornerWidth: s * 0.06, cornerHeight: s * 0.06)
            fuellen.addRoundedRect(in: CGRect(origin: p(0.44, 0.40), size: CGSize(width: s * 0.16, height: s * 0.40)),
                                   cornerWidth: s * 0.05, cornerHeight: s * 0.05)
            path.addLines(between: [p(0.28, 0.33), p(0.10, 0.33)])
            path.addLines(between: [p(0.10, 0.30), p(0.14, 0.36), p(0.18, 0.30), p(0.22, 0.36)])
        case .schluessel:
            // Maulschlüssel
            path.addLines(between: [p(0.30, 0.70), p(0.70, 0.30)])
            bogen(p(0.75, 0.25), s * 0.13, .pi * 0.85, .pi * 2.35)
            path.addEllipse(in: CGRect(x: p(0.25, 0.75).x - s * 0.11, y: p(0.25, 0.75).y - s * 0.11,
                                       width: s * 0.22, height: s * 0.22))
        case .innensechskant:
            // Winkelschlüssel mit Sechskant
            path.addLines(between: [p(0.25, 0.20), p(0.25, 0.75), p(0.72, 0.75)])
            var sechs: [CGPoint] = []
            for i in 0..<7 {
                let a = CGFloat(i) * .pi / 3
                sechs.append(p(0.25 + 0.10 * cos(a), 0.20 + 0.10 * sin(a)))
            }
            path.addLines(between: sechs)
        case .schraubendreher:
            fuellen.addRoundedRect(in: CGRect(origin: p(0.20, 0.18), size: CGSize(width: s * 0.22, height: s * 0.36)),
                                   cornerWidth: s * 0.08, cornerHeight: s * 0.08)
            path.addLines(between: [p(0.31, 0.54), p(0.31, 0.84)])
            path.addLines(between: [p(0.27, 0.84), p(0.35, 0.84)])
        case .loetkolben:
            fuellen.addRoundedRect(in: CGRect(origin: p(0.14, 0.58), size: CGSize(width: s * 0.38, height: s * 0.16)),
                                   cornerWidth: s * 0.07, cornerHeight: s * 0.07)
            path.addLines(between: [p(0.52, 0.66), p(0.86, 0.52)])
            // Hitzewellen
            for dx in [0.62, 0.74] as [CGFloat] {
                path.move(to: p(dx, 0.40))
                path.addCurve(to: p(dx, 0.16), control1: p(dx + 0.06, 0.32), control2: p(dx - 0.06, 0.24))
            }
        case .drucker:
            path.addRect(CGRect(origin: p(0.14, 0.16), size: CGSize(width: s * 0.72, height: s * 0.68)))
            path.addLines(between: [p(0.14, 0.32), p(0.86, 0.32)])
            fuellen.addRect(CGRect(origin: p(0.44, 0.32), size: CGSize(width: s * 0.12, height: s * 0.10)))
            fuellen.addRect(CGRect(origin: p(0.30, 0.66), size: CGSize(width: s * 0.40, height: s * 0.08)))
        case .messen:
            path.addRect(CGRect(origin: p(0.08, 0.38), size: CGSize(width: s * 0.84, height: s * 0.24)))
            for i in 1...7 {
                let x = 0.08 + CGFloat(i) * 0.105
                path.addLines(between: [p(x, 0.38), p(x, i % 2 == 0 ? 0.52 : 0.46)])
            }
        case .entgrater:
            fuellen.addRoundedRect(in: CGRect(origin: p(0.14, 0.58), size: CGSize(width: s * 0.36, height: s * 0.16)),
                                   cornerWidth: s * 0.07, cornerHeight: s * 0.07)
            path.addLines(between: [p(0.50, 0.66), p(0.74, 0.54)])
            bogen(p(0.78, 0.46), s * 0.09, .pi * 0.6, .pi * 1.9)
        case .koerner:
            path.addLines(between: [p(0.44, 0.10), p(0.56, 0.10), p(0.56, 0.62), p(0.50, 0.80), p(0.44, 0.62),
                                    p(0.44, 0.10)])
            path.addLines(between: [p(0.30, 0.90), p(0.70, 0.90)])
        case .hand:
            // Hand von der Seite: Daumen und Finger angedeutet
            path.move(to: p(0.30, 0.86))
            path.addLines(between: [p(0.30, 0.50), p(0.20, 0.36), p(0.26, 0.30), p(0.38, 0.42), p(0.38, 0.18),
                                    p(0.46, 0.18), p(0.48, 0.40), p(0.50, 0.14), p(0.58, 0.14), p(0.60, 0.40),
                                    p(0.64, 0.20), p(0.72, 0.22), p(0.72, 0.62), p(0.66, 0.86)])
        case .spachtel:
            path.addLines(between: [p(0.30, 0.20), p(0.70, 0.20), p(0.62, 0.52), p(0.38, 0.52), p(0.30, 0.20)])
            fuellen.addRoundedRect(in: CGRect(origin: p(0.44, 0.52), size: CGSize(width: s * 0.12, height: s * 0.34)),
                                   cornerWidth: s * 0.04, cornerHeight: s * 0.04)
        case .kleber:
            path.move(to: p(0.50, 0.14))
            path.addCurve(to: p(0.50, 0.84), control1: p(0.20, 0.50), control2: p(0.22, 0.84))
            path.addCurve(to: p(0.50, 0.14), control1: p(0.78, 0.84), control2: p(0.80, 0.50))
        case .allgemein:
            path.addLines(between: [p(0.22, 0.78), p(0.62, 0.38)])
            bogen(p(0.70, 0.30), s * 0.13, .pi * 0.75, .pi * 2.25)
            path.addLines(between: [p(0.78, 0.78), p(0.38, 0.38)])
            path.addLines(between: [p(0.22, 0.22), p(0.38, 0.38)])
        }
        ctx.addPath(path)
        ctx.strokePath()
        if !fuellen.isEmpty {
            ctx.addPath(fuellen)
            ctx.fillPath()
        }
        ctx.restoreGState()
    }
}
