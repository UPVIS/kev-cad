import CoreGraphics
import CoreText
import Foundation

/// Die eine Zeichenfunktion für Bildschirm, PDF und Druck (DOKUMENTE.md, App; RECHERCHE-PHASE6.md 5).
///
/// `zeichne(_:in:)` arbeitet im aktuellen Benutzerraum in Blatt-mm mit y nach oben: Der Aufrufer legt die Abbildung fest
/// (Bildschirm: Zoom und Verschiebung; PDF und Druck: `zeichneSeite` skaliert mm auf Punkt). Linien nach ISO 128 als
/// echte Vektoren mit runden Enden, Strichmuster als einzelne Striche (beginnen und enden mit einem Strich), Schraffur als
/// Clip-Pfad mit Linien (kein Muster), Texte über CoreText in osifont mit exakter Versalhöhe (eingebettet im PDF).
public enum BlattZeichner {
    /// 1 mm in PDF-Punkten.
    public static let punkteJeMM: CGFloat = 72 / 25.4

    public struct Optionen: @unchecked Sendable {
        /// Papierfarbe (nil = nicht füllen, etwa für eine eigene Seite).
        public var papier: CGColor?
        public var linien: CGColor
        /// Verwaiste Maße (Bezug nach einer Modelländerung nicht mehr gefunden).
        public var verwaist: CGColor?
        /// Maße von Kevin oder Claude (nur am Bildschirm, sonst wie alle).
        public var eigene: CGColor?
        /// Mindestbreite einer Linie in Gerätepixeln (Bildschirm), nil = exakt (PDF, Druck).
        public var mindestbreitePixel: CGFloat?
        /// Maße, die der Aufrufer selbst zeichnet (Vorschau beim Ziehen).
        public var ohneMasse: Set<String>
        /// Ansichten, die der Aufrufer selbst zeichnet (Vorschau beim Verschieben).
        public var ohneAnsichten: Set<String>
        /// Texte (Index in `Zeichnung.texte`), die der Aufrufer selbst zeichnet (Notiz, Ansichtstitel beim Verschieben).
        public var ohneTexte: Set<Int>
        /// Nur zeichnen, was diesen Ausschnitt (Blatt-mm) schneidet; nil = alles.
        public var ausschnitt: CGRect?

        public init(
            papier: CGColor? = CGColor(gray: 1, alpha: 1), linien: CGColor = CGColor(gray: 0, alpha: 1),
            verwaist: CGColor? = BlattZeichner.rot, eigene: CGColor? = nil, mindestbreitePixel: CGFloat? = nil,
            ohneMasse: Set<String> = [], ohneAnsichten: Set<String> = [], ohneTexte: Set<Int> = [],
            ausschnitt: CGRect? = nil
        ) {
            self.papier = papier
            self.linien = linien
            self.verwaist = verwaist
            self.eigene = eigene
            self.mindestbreitePixel = mindestbreitePixel
            self.ohneMasse = ohneMasse
            self.ohneAnsichten = ohneAnsichten
            self.ohneTexte = ohneTexte
            self.ausschnitt = ausschnitt
        }

        /// PDF und Druck: exakte Breiten, verwaiste Maße rot (damit sie auf keinem Ausdruck untergehen).
        public static var druck: Optionen { Optionen() }
        /// Bildschirm: mindestens ein Gerätepixel breit.
        public static var bildschirm: Optionen { Optionen(mindestbreitePixel: 1) }
    }

    /// Rot der verwaisten Maße (wie systemRed, druckbar).
    public static let rot = CGColor(srgbRed: 0.84, green: 0.07, blue: 0.10, alpha: 1)

    // MARK: Ganzes Blatt

    /// Zeichnet das Blatt im aktuellen Benutzerraum (Blatt-mm, y nach oben).
    public static func zeichne(_ z: Zeichnung, in ctx: CGContext, optionen o: Optionen = .druck) {
        let g = z.grafik
        let blattRect = CGRect(origin: .zero, size: z.groesse)
        ctx.saveGState()
        defer { ctx.restoreGState() }
        if let papier = o.papier {
            ctx.setFillColor(papier)
            ctx.fill(blattRect)
        }
        let skala = geraeteSkala(ctx)
        ctx.setLineCap(.round)
        ctx.setLineJoin(.round)
        ctx.setStrokeColor(o.linien)
        ctx.setFillColor(o.linien)
        let sicht = o.ausschnitt
        for gruppe in g.gruppen where !o.ohneAnsichten.contains(gruppe.id) {
            if let sicht, !gruppe.istBlatt, !gruppe.huelle.insetBy(dx: -2, dy: -2).intersects(sicht) { continue }
            zeichneGruppe(gruppe, in: ctx, skala: skala, optionen: o)
        }
        if !g.gefuellt.isEmpty {
            ctx.addPath(g.gefuellt)
            ctx.fillPath()
        }
        for m in g.masse where !o.ohneMasse.contains(m.mass.id) {
            if let sicht, !m.huelle.insetBy(dx: -2, dy: -2).intersects(sicht) { continue }
            if let a = m.mass.ansicht, o.ohneAnsichten.contains(a) { continue }
            zeichneMass(m, in: ctx, farbe: farbe(fuer: m.mass, o), skala: skala, optionen: o)
        }
        ctx.setFillColor(o.linien)
        for (i, t) in g.texte.enumerated() where !o.ohneTexte.contains(i) {
            if let sicht, !t.rahmen.intersects(sicht) { continue }
            t.zeichne(in: ctx)
        }
    }

    /// PDF- bzw. Druckseite: Benutzerraum in Punkt (Ursprung links unten), Seite so groß wie das Blatt.
    public static func zeichneSeite(_ z: Zeichnung, in ctx: CGContext, optionen: Optionen = .druck) {
        ctx.saveGState()
        ctx.scaleBy(x: punkteJeMM, y: punkteJeMM)
        zeichne(z, in: ctx, optionen: optionen)
        ctx.restoreGState()
    }

    static func farbe(fuer m: MassDarstellung, _ o: Optionen) -> CGColor {
        if m.verwaist, let v = o.verwaist { return v }
        if m.eigenes, let e = o.eigene { return e }
        return o.linien
    }

    /// Gerätepixel je Benutzereinheit (für die Mindestbreite am Bildschirm).
    static func geraeteSkala(_ ctx: CGContext) -> CGFloat {
        let t = ctx.userSpaceToDeviceSpaceTransform
        return max(sqrt(abs(t.a * t.d - t.b * t.c)), 1e-6)
    }

    static func breite(_ b: CGFloat, skala: CGFloat, optionen o: Optionen) -> CGFloat {
        guard let px = o.mindestbreitePixel else { return b }
        return max(b, px / skala)
    }

    // MARK: Teile

    /// Eine Ansicht (oder die Gruppe „blatt“) mit allen Linienarten.
    public static func zeichneGruppe(_ g: BlattGrafik.Gruppe, in ctx: CGContext, skala: CGFloat? = nil,
                                     optionen o: Optionen = .druck) {
        let s = skala ?? geraeteSkala(ctx)
        if let linien = g.schraffurLinien, !linien.isEmpty {
            let stil = LinienStil.fuer("schraffur")
            ctx.saveGState()
            if let clip = g.schraffurClip {
                ctx.addPath(clip)
                ctx.clip(using: .evenOdd)
            }
            ctx.setLineWidth(breite(stil.breite, skala: s, optionen: o))
            ctx.setLineCap(.butt)
            ctx.addPath(linien)
            ctx.strokePath()
            ctx.restoreGState()
        }
        for strich in g.striche {
            ctx.setLineWidth(breite(strich.stil.breite, skala: s, optionen: o))
            ctx.addPath(strich.pfad)
            ctx.strokePath()
        }
    }

    /// Ein Maß in einer Farbe; `dicker` > 1 für hervorgehobene Maße am Bildschirm.
    public static func zeichneMass(_ m: MassGrafik, in ctx: CGContext, farbe: CGColor, skala: CGFloat? = nil,
                                   optionen o: Optionen = .druck, dicker: CGFloat = 1) {
        let s = skala ?? geraeteSkala(ctx)
        ctx.saveGState()
        ctx.setStrokeColor(farbe)
        ctx.setFillColor(farbe)
        ctx.setLineCap(.round)
        ctx.setLineJoin(.round)
        ctx.setLineWidth(breite(LinienStil.schmal * dicker, skala: s, optionen: o))
        if !m.linien.isEmpty {
            ctx.addPath(m.linien)
            ctx.strokePath()
        }
        if !m.pfeileOffen.isEmpty {
            ctx.addPath(m.pfeileOffen)
            ctx.strokePath()
        }
        if !m.pfeileVoll.isEmpty {
            ctx.addPath(m.pfeileVoll)
            ctx.fillPath()
        }
        for t in m.texte { t.zeichne(in: ctx) }
        ctx.restoreGState()
    }

    /// Strichbild aus Polylinien (z. B. ein Bauplanbild): jede Linienart in ihrem Stil, unbekannte dünn durchgezogen.
    /// `farben` färbt einzelne Linienarten (etwa `neu`), sonst `optionen.linien`.
    public static func zeichneLinien(_ gruppe: LinienGruppe, in ctx: CGContext, optionen o: Optionen = .druck,
                                     farben: [String: CGColor] = [:]) {
        let gz = ZeichnungsGruppe(id: "bild", art: "bild", rahmen: .zero, linien: gruppe)
        var n = 0
        let g = BlattGrafik.gruppe(gz, zaehler: &n)
        ctx.saveGState()
        ctx.setLineCap(.round)
        ctx.setLineJoin(.round)
        let s = geraeteSkala(ctx)
        if let linien = g.schraffurLinien, !linien.isEmpty {
            ctx.saveGState()
            ctx.setStrokeColor(o.linien)
            if let clip = g.schraffurClip {
                ctx.addPath(clip)
                ctx.clip(using: .evenOdd)
            }
            ctx.setLineWidth(breite(LinienStil.schmal, skala: s, optionen: o))
            ctx.addPath(linien)
            ctx.strokePath()
            ctx.restoreGState()
        }
        for strich in g.striche {
            ctx.setStrokeColor(farben[strich.art] ?? o.linien)
            ctx.setLineWidth(breite(strich.stil.breite, skala: s, optionen: o))
            ctx.addPath(strich.pfad)
            ctx.strokePath()
        }
        ctx.restoreGState()
    }

    /// Ein vorbereiteter Text in einer Farbe (Hervorhebung am Bildschirm).
    public static func zeichneText(_ t: TextGrafik, in ctx: CGContext, farbe: CGColor) {
        ctx.saveGState()
        ctx.setFillColor(farbe)
        t.zeichne(in: ctx)
        ctx.restoreGState()
    }

    /// Ein einzelner Text (Versalhöhe in Benutzereinheiten), z. B. für Seiten, die P6-A2 um ein Blatt herum setzt.
    public static func zeichneText(_ t: BlattText, in ctx: CGContext, farbe: CGColor = CGColor(gray: 0, alpha: 1)) {
        ctx.saveGState()
        ctx.setFillColor(farbe)
        TextGrafik(t).zeichne(in: ctx)
        ctx.restoreGState()
    }
}
