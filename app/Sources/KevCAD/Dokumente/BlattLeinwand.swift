#if os(macOS)
import AppKit
#else
import UIKit
#endif
import KevCADCore
import QuartzCore
import SwiftUI

/// Messwerte der Blattansicht (Bildrate beim Zoomen und Verschieben, Zeit bis zur ersten Darstellung). Werden im
/// Protokoll und vom Selbsttest gelesen.
@MainActor
final class BlattMesswerte {
    static let shared = BlattMesswerte()

    /// Gezeichnete Bilder während einer Geste: Zeitpunkt und Zeichenzeit in ms.
    private(set) var bilder: [(zeit: CFTimeInterval, ms: Double, zwischenspeicher: Bool)] = []
    private(set) var ersteDarstellung: [String: Double] = [:]

    func bild(ms: Double, zwischenspeicher: Bool) {
        bilder.append((CACurrentMediaTime(), ms, zwischenspeicher))
        if bilder.count > 4000 { bilder.removeFirst(bilder.count - 4000) }
    }

    func erste(_ blatt: String, ms: Double) { ersteDarstellung[blatt] = ms }

    func zuruecksetzen() { bilder = [] }

    /// Bilder je Sekunde und Zeichenzeiten über die Bilder seit `seit`.
    func auswertung(seit: CFTimeInterval) -> (fps: Double, mittelMs: Double, maxMs: Double, anzahl: Int) {
        let b = bilder.filter { $0.zeit >= seit }
        guard b.count >= 2, let a = b.first, let e = b.last, e.zeit > a.zeit else { return (0, 0, 0, b.count) }
        let fps = Double(b.count - 1) / (e.zeit - a.zeit)
        let ms = b.map(\.ms)
        return (fps, ms.reduce(0, +) / Double(ms.count), ms.max() ?? 0, b.count)
    }
}

// Eine Leinwand für Mac und iPad (I-8): Zeichnen, Treffer, Gesten und Bearbeiten sind gemeinsam, nur die Eingänge sind
// je Gerät eigen (Maus, Trackpad und Tastatur am Mac; Finger, Stift, Schweben, Kneifen und Kontextmenü am iPad). Am iPad
// rechnet die Ansicht wie am Mac mit y nach oben: `draw` spiegelt den Kontext, Berührungen gehen über `oben(_:)`.
#if os(macOS)
typealias BlattLeinwandBasis = NSView
#else
typealias BlattLeinwandBasis = UIView
#endif

/// Die Blattansicht: zeichnet mit `BlattZeichner` (derselben Funktion wie PDF und Druck), zoomt und
/// verschiebt (Trackpad, Pinch, Mausrad), wählt aus und bearbeitet (Maße ziehen, neue Maße, Notizen, Ansichten).
///
/// Koordinaten: Die Ansicht ist nicht gespiegelt (y nach oben) wie das Blatt. `ursprung` ist die Lage der Blattecke
/// links unten in Ansichtspunkten, `skala` Punkte je Blatt-mm.
final class BlattLeinwand: BlattLeinwandBasis {
    weak var zustand: DokumenteZustand?
    weak var model: AppModel?

    private(set) var zeichnung: Zeichnung?
    private(set) var skala: CGFloat = 2
    private(set) var ursprung: CGPoint = .zero
    /// Blatt ist eingepasst: bei Größenänderung des Fensters neu einpassen.
    private var eingepasst = true
    var letzterBefehl: UUID?

    var werkzeug: BlattWerkzeug = .auswahl {
        didSet {
            guard werkzeug != oldValue else { return }
            massKlicks = []
            notizStart = nil
            schnittStart = nil
            hoverLinie = nil
            hinweisAktualisieren()
            #if os(macOS)  // nur am Mac: Mauszeiger je Werkzeug
            window?.invalidateCursorRects(for: self)
            #endif
            needsDisplay = true
        }
    }

    var element: BlattElement? {
        didSet { if element != oldValue { needsDisplay = true } }
    }

    // MARK: Zustand der Gesten

    private enum MassZiehen { case versatz, text }

    private enum Geste {
        case keine
        case schwenken(start: CGPoint, ursprung0: CGPoint)
        case mass(id: String, art: MassZiehen, start: CGPoint)
        case ansicht(id: String, start: CGPoint)
        case notiz(id: String, start: CGPoint)
        case notizNeu(start: CGPoint)
        case schnittNeu(start: CGPoint)
        case einzelheitNeu(mitte: CGPoint)
    }

    private var geste: Geste = .keine {
        didSet { if case .keine = geste {} else { protokolliere("Geste \(geste) auf Stand \(zeichnung?.stand ?? "-")") } }
    }
    /// Letzte Gesten, Operationen und Antworten (Selbsttest und Fehlersuche).
    private(set) var gestenProtokoll: [String] = []

    private func protokolliere(_ s: String) {
        gestenProtokoll.append(s)
        if gestenProtokoll.count > 40 { gestenProtokoll.removeFirst(gestenProtokoll.count - 40) }
    }
    private var gezogen = false
    private var zug = CGVector.zero
    private var maus: CGPoint?  // Blatt-mm
    /// Element unter dem Zeiger (Hervorhebung im Auswahlwerkzeug).
    private var hoverElement: BlattElement?

    /// Nach dem Loslassen bis zur Antwort des Kernels: die verschobenen Dinge an ihrer neuen Stelle (kein Zurückspringen).
    private struct Ausstehend {
        var masse: [String: MassGrafik] = [:]
        var ansichten: [String: CGVector] = [:]
        var notizen: [String: CGVector] = [:]
        var stand: String
        var seit = Date()

        var leer: Bool { masse.isEmpty && ansichten.isEmpty && notizen.isEmpty }
    }

    private var ausstehend: Ausstehend?

    /// Pfeiltasten: gesammelte Verschiebung, gesendet nach einer kurzen Pause.
    private var schubs = CGVector.zero
    private var schubsTimer: Timer?

    // Maß-Werkzeug
    private struct Klick {
        var ansicht: String
        var punkt: CGPoint
        var linie: [CGPoint]?
    }

    private var massKlicks: [Klick] = []
    private var hoverLinie: (ansicht: String, linie: [CGPoint])?
    private var notizStart: CGPoint?
    /// Schnitt-Werkzeug: erster Punkt der Linie (zweiter Klick oder Loslassen nach dem Ziehen setzt den Schnitt).
    private var schnittStart: CGPoint?

    // Zeichnen und Messen
    private var interaktionBis: CFTimeInterval = 0
    private var ruheTimer: Timer?
    private var zwischenspeicher: (bild: CGImage, stand: String, pxJeMM: CGFloat)?
    private var zwischenspeicherLaeuft = false
    /// Gemessene Rechenzeit des Zwischenbilds je Megapixel (echter Aufwand des Blatts beim Rastern).
    private var rasterMsJeMpx: Double = 0
    private var ersteDarstellungFuer: (blatt: String, seit: Date)?
    private var animation: Timer?
    #if os(macOS)
    private weak var popover: NSPopover?

    override var isFlipped: Bool { false }
    override var isOpaque: Bool { true }
    override var acceptsFirstResponder: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layerContentsRedrawPolicy = .onSetNeedsDisplay
        addTrackingArea(NSTrackingArea(
            rect: .zero, options: [.mouseMoved, .mouseEnteredAndExited, .activeInKeyWindow, .inVisibleRect,
                                   .cursorUpdate],
            owner: self, userInfo: nil))
    }
    #else
    /// iPad: offene Texteingabe (Popover mit `BlattTextEingabeAnsicht`).
    private weak var eingabe: UIViewController?
    /// Größe beim letzten Layout (Gegenstück zu `setFrameSize` am Mac).
    private var letzteGroesse = CGSize.zero
    /// Umschalt und Wahl der Hardware-Tastatur beim letzten Berühren (Gegenstück zu `NSEvent.modifierFlags`).
    static var tasten: UIKeyModifierFlags = []

    override init(frame: CGRect) {
        super.init(frame: frame)
        isOpaque = true
        contentMode = .redraw
        isMultipleTouchEnabled = true
        gestenEinrichten()
    }
    #endif

    required init?(coder: NSCoder) { nil }

    #if os(macOS)
    /// Im Bereich Dokumente bekommt das Blatt die Tastatur (⌫, Pfeile, Esc), nicht die ruhende 3D-Ansicht dahinter.
    /// iPad: dasselbe in `didMoveToWindow` (Eingänge am Ende der Datei).
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        guard let w = window else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self, self.window === w, !KeyboardGuard.isTextInput(w.firstResponder) else { return }
            w.makeFirstResponder(self)
        }
    }
    #endif

    // MARK: Blatt setzen

    /// Neues oder aktualisiertes Blatt. Gleiches Blatt (neuer Stand nach Lauf oder Änderung): Zoom, Lage und Auswahl
    /// bleiben; anderes Blatt: einpassen.
    func setze(_ z: Zeichnung?, angefordertSeit: Date?) {
        let alt = zeichnung
        guard alt?.id != z?.id || alt?.stand != z?.stand || (alt == nil) != (z == nil) else { return }
        zeichnung = z
        if let a = ausstehend, z?.stand != a.stand || z == nil { ausstehend = nil }
        if z?.id != alt?.id {
            zwischenspeicher = nil
            massKlicks = []
            hoverLinie = nil
            if let z { ersteDarstellungFuer = (z.id, angefordertSeit ?? Date()) }
            eingepasst = true
            einpassen(animiert: false)
        } else if eingepasst, z?.groesse != alt?.groesse {
            einpassen(animiert: true)
        }
        // Auswahl, die es nicht mehr gibt, aufheben
        if let e = element, let z, !Self.gibt(e, in: z) {
            element = nil
            DispatchQueue.main.async { [weak self] in self?.zustand?.element = nil }
        }
        zwischenspeicherAnstossen()
        needsDisplay = true
    }

    static func gibt(_ e: BlattElement, in z: Zeichnung) -> Bool {
        switch e {
        case .mass(let id): return z.mass(id) != nil
        case .ansicht(let id): return z.gruppe(id) != nil
        case .notiz(let id): return z.blatt.notizen.contains { $0.id == id }
        }
    }

    /// Antwort auf eine Änderung kam mit Fehler: verschobene Dinge zurück an ihre alte Stelle.
    func aenderungGescheitert() {
        ausstehend = nil
        needsDisplay = true
    }

    // MARK: Umrechnung

    func mm(_ v: CGPoint) -> CGPoint { CGPoint(x: (v.x - ursprung.x) / skala, y: (v.y - ursprung.y) / skala) }
    func punkt(_ p: CGPoint) -> CGPoint { CGPoint(x: ursprung.x + p.x * skala, y: ursprung.y + p.y * skala) }

    private var papier: CGRect {
        guard let z = zeichnung else { return .zero }
        return CGRect(x: ursprung.x, y: ursprung.y, width: z.groesse.width * skala, height: z.groesse.height * skala)
    }

    /// Toleranz für Treffer in Blatt-mm (5 Bildschirmpunkte).
    private var toleranz: CGFloat { 5 / skala }

    // MARK: Zoom

    static let randPunkte: CGFloat = 28

    func einpassen(animiert: Bool) {
        guard let z = zeichnung, bounds.width > 40, bounds.height > 40 else { return }
        let rand = Self.randPunkte
        let s = min((bounds.width - 2 * rand) / z.groesse.width, (bounds.height - 2 * rand - 26) / z.groesse.height)
        let neuSkala = max(0.2, s)
        let neuUrsprung = CGPoint(x: (bounds.width - z.groesse.width * neuSkala) / 2,
                                  y: (bounds.height - z.groesse.height * neuSkala) / 2 + 13)
        eingepasst = true
        setzeAnsicht(skala: neuSkala, ursprung: neuUrsprung, animiert: animiert)
    }

    /// 1:1 auf dem Bildschirm: 1 mm auf dem Blatt ist 1 mm auf dem Monitor (aus der physischen Größe des Bildschirms).
    func originalgroesse() {
        #if os(macOS)
        guard let screen = window?.screen ?? NSScreen.main,
              let nr = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID
        else { return }
        let mmBreite = CGDisplayScreenSize(nr).width
        guard mmBreite > 50 else { return }
        let s = screen.frame.width / mmBreite
        #else
        let s = Self.punkteJeMMBildschirm()
        #endif
        zoom(auf: s, um: CGPoint(x: bounds.midX, y: bounds.midY), animiert: true)
    }

    func zoom(faktor: CGFloat, um p: CGPoint, animiert: Bool = false) {
        zoom(auf: skala * faktor, um: p, animiert: animiert)
    }

    func zoom(auf s: CGFloat, um p: CGPoint, animiert: Bool) {
        let neu = min(max(s, 0.25), 120)
        let m = mm(p)
        let u = CGPoint(x: p.x - m.x * neu, y: p.y - m.y * neu)
        eingepasst = false
        setzeAnsicht(skala: neu, ursprung: u, animiert: animiert)
    }

    private func setzeAnsicht(skala s: CGFloat, ursprung u: CGPoint, animiert: Bool) {
        animation?.invalidate()
        guard animiert, window != nil else {
            skala = s
            ursprung = u
            ansichtGeaendert()
            return
        }
        let s0 = skala
        let u0 = ursprung
        let t0 = CACurrentMediaTime()
        let dauer = 0.22
        animation = Timer.scheduledTimer(withTimeInterval: 1.0 / 120, repeats: true) { [weak self] t in
            MainActor.assumeIsolated {
                guard let self else {
                    t.invalidate()
                    return
                }
                let x = min(1, (CACurrentMediaTime() - t0) / dauer)
                let k = CGFloat(1 - pow(1 - x, 3))  // sanft auslaufend
                self.skala = s0 * pow(s / s0, k)
                self.ursprung = CGPoint(x: u0.x + (u.x - u0.x) * k, y: u0.y + (u.y - u0.y) * k)
                self.interagiere()
                self.ansichtGeaendert()
                if x >= 1 { t.invalidate() }
            }
        }
    }

    private func ansichtGeaendert() {
        needsDisplay = true
        let prozent = Int((skala / punkteJeMM * 100).rounded())
        if zustand?.anzeige.zoomProzent != prozent {
            DispatchQueue.main.async { [weak self] in self?.zustand?.anzeige.zoomProzent = prozent }
        }
    }

    #if os(macOS)
    /// Bildschirmpunkte je mm bei 100 % (Papiergröße auf dem Monitor).
    static func punkteJeMMBildschirm(_ screen: NSScreen?) -> CGFloat {
        guard let screen = screen ?? NSScreen.main,
              let nr = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID
        else { return 72 / 25.4 }
        let mmBreite = CGDisplayScreenSize(nr).width
        return mmBreite > 50 ? screen.frame.width / mmBreite : 72 / 25.4
    }

    private var punkteJeMM: CGFloat { Self.punkteJeMMBildschirm(window?.screen) }
    private var pixelJePunkt: CGFloat { window?.backingScaleFactor ?? 2 }

    override func setFrameSize(_ newSize: NSSize) {
        let alt = bounds.size
        super.setFrameSize(newSize)
        groesseGeaendert(von: alt, auf: newSize)
    }
    #else
    /// iPad: Punkte je mm bei 100 %. iPadOS nennt die Pixeldichte nicht; die großen iPads haben 264 ppi bei Faktor 2,
    /// also 132 Punkte je Zoll (iPad mini 163).
    static func punkteJeMMBildschirm() -> CGFloat { 132 / 25.4 }

    private var punkteJeMM: CGFloat { Self.punkteJeMMBildschirm() }
    private var pixelJePunkt: CGFloat { window?.screen.scale ?? traitCollection.displayScale }

    override func layoutSubviews() {
        super.layoutSubviews()
        guard bounds.size != letzteGroesse else { return }
        let alt = letzteGroesse
        letzteGroesse = bounds.size
        groesseGeaendert(von: alt, auf: bounds.size)
    }
    #endif

    private func groesseGeaendert(von alt: CGSize, auf newSize: CGSize) {
        if eingepasst {
            einpassen(animiert: false)
        } else {
            ursprung.x += (newSize.width - alt.width) / 2
            ursprung.y += (newSize.height - alt.height) / 2
        }
    }

    func fuehreAus(_ b: BlattBefehl.Art) {
        let mitte = CGPoint(x: bounds.midX, y: bounds.midY)
        switch b {
        case .einpassen: einpassen(animiert: true)
        case .originalgroesse: originalgroesse()
        case .vergroessern: zoom(faktor: 1.25, um: mitte, animiert: true)
        case .verkleinern: zoom(faktor: 0.8, um: mitte, animiert: true)
        }
    }

    // MARK: Trackpad, Mausrad

    #if os(macOS)  // iPad: Kneifen und Verschieben mit zwei Fingern in `gestenEinrichten`
    override func magnify(with event: NSEvent) {
        interagiere()
        zoom(faktor: 1 + event.magnification, um: convert(event.locationInWindow, from: nil))
    }

    override func smartMagnify(with event: NSEvent) {
        let p = convert(event.locationInWindow, from: nil)
        if eingepasst {
            zoom(faktor: 2.5, um: p, animiert: true)
        } else {
            einpassen(animiert: true)
        }
    }

    override func scrollWheel(with event: NSEvent) {
        interagiere()
        let p = convert(event.locationInWindow, from: nil)
        if event.hasPreciseScrollingDeltas && !event.modifierFlags.contains(.command) {
            // Trackpad: verschieben (Inhalt folgt den Fingern)
            eingepasst = false
            ursprung.x += event.scrollingDeltaX
            ursprung.y -= event.scrollingDeltaY
            ansichtGeaendert()
        } else {
            // Mausrad oder ⌘ + Trackpad: zoomen um den Zeiger
            let d = event.hasPreciseScrollingDeltas ? event.scrollingDeltaY * 0.01 : event.scrollingDeltaY * 0.12
            zoom(faktor: pow(1.6, d), um: p)
        }
    }
    #endif

    /// Während Zoom und Verschieben aus dem Zwischenbild zeichnen, danach wieder scharf.
    func interagiere() {
        interaktionBis = CACurrentMediaTime() + 0.16
        ruheTimer?.invalidate()
        ruheTimer = Timer.scheduledTimer(withTimeInterval: 0.18, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self else { return }
                self.needsDisplay = true
                self.zwischenspeicherAnstossen()
            }
        }
    }

    private var interaktiv: Bool { CACurrentMediaTime() < interaktionBis }

    // MARK: Zwischenbild

    /// Höchstens so viele Pixel für das Zwischenbild des ganzen Blatts.
    static let maxPixel: CGFloat = 8_000_000

    /// Rechnet im Hintergrund ein Bild des ganzen Blatts in der aktuellen Auflösung (für flüssiges Zoomen auch bei
    /// Blättern mit vielen Linien und Maßen).
    private func zwischenspeicherAnstossen() {
        guard let z = zeichnung, !zwischenspeicherLaeuft else { return }
        let backing = pixelJePunkt
        let wunsch = skala * backing
        let flaeche = z.groesse.width * z.groesse.height
        let pxJeMM = min(wunsch, sqrt(Self.maxPixel / flaeche))
        if let c = zwischenspeicher, c.stand == z.stand, abs(c.pxJeMM - pxJeMM) / pxJeMM < 0.2 { return }
        zwischenspeicherLaeuft = true
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let t = CACurrentMediaTime()
            let bild = Self.raster(z, pxJeMM: pxJeMM)
            let ms = (CACurrentMediaTime() - t) * 1000
            let mpx = Double(z.groesse.width * z.groesse.height * pxJeMM * pxJeMM) / 1e6
            DispatchQueue.main.async {
                guard let self else { return }
                self.zwischenspeicherLaeuft = false
                if mpx > 0 { self.rasterMsJeMpx = ms / mpx }
                if let bild, self.zeichnung?.stand == z.stand { self.zwischenspeicher = (bild, z.stand, pxJeMM) }
            }
        }
    }

    nonisolated static func raster(_ z: Zeichnung, pxJeMM: CGFloat) -> CGImage? {
        let w = Int((z.groesse.width * pxJeMM).rounded(.up))
        let h = Int((z.groesse.height * pxJeMM).rounded(.up))
        guard w > 0, h > 0, let ctx = CGContext(
            data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
            space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)
        else { return nil }
        ctx.scaleBy(x: pxJeMM, y: pxJeMM)
        BlattZeichner.zeichne(z, in: ctx, optionen: .bildschirm)
        return ctx.makeImage()
    }

    // MARK: Zeichnen

    #if os(macOS)
    static let auswahlFarbe = NSColor.controlAccentColor
    #else
    static let auswahlFarbe = UIColor.systemBlue
    #endif

    /// Zeichenbrett um das helle Blatt (Stil Reißbrett, V2-7): leise Planquadrate im Abstand von 10 mm. Zu klein gezoomt
    /// würden sie flimmern, dann bleibt die Fläche frei.
    private func planquadrate(_ ctx: CGContext, in r: CGRect) {
        let schritt = 10 * skala
        guard schritt >= 6 else { return }
        let weg = CGMutablePath()
        var x = ursprung.x + ((r.minX - ursprung.x) / schritt).rounded(.down) * schritt
        while x <= r.maxX {
            weg.move(to: CGPoint(x: x, y: r.minY))
            weg.addLine(to: CGPoint(x: x, y: r.maxY))
            x += schritt
        }
        var y = ursprung.y + ((r.minY - ursprung.y) / schritt).rounded(.down) * schritt
        while y <= r.maxY {
            weg.move(to: CGPoint(x: r.minX, y: y))
            weg.addLine(to: CGPoint(x: r.maxX, y: y))
            y += schritt
        }
        ctx.saveGState()
        ctx.setStrokeColor(CGColor(gray: 1, alpha: 0.05))
        ctx.setLineWidth(1)
        ctx.addPath(weg)
        ctx.strokePath()
        ctx.restoreGState()
    }

    #if os(macOS)
    override func draw(_ dirtyRect: NSRect) {
        guard let ctx = NSGraphicsContext.current?.cgContext else { return }
        zeichne(in: ctx, dirtyRect, grund: NSColor.underPageBackgroundColor.cgColor)
    }
    #else
    /// iPad: Kontext spiegeln, damit wie am Mac y nach oben zeigt.
    override func draw(_ rect: CGRect) {
        guard let ctx = UIGraphicsGetCurrentContext() else { return }
        ctx.translateBy(x: 0, y: bounds.height)
        ctx.scaleBy(x: 1, y: -1)
        let dirty = CGRect(x: rect.minX, y: bounds.height - rect.maxY, width: rect.width, height: rect.height)
        zeichne(in: ctx, dirty, grund: UIColor(white: 0.16, alpha: 1).cgColor)
    }
    #endif

    private func zeichne(in ctx: CGContext, _ dirtyRect: CGRect, grund: CGColor) {
        let t0 = CACurrentMediaTime()
        ctx.setFillColor(grund)
        ctx.fill(dirtyRect)
        guard let z = zeichnung else { return }
        let blatt = papier
        planquadrate(ctx, in: dirtyRect)
        // Papier mit Schatten (bleibt in Hell und Dunkel weiß)
        ctx.saveGState()
        ctx.setShadow(offset: CGSize(width: 0, height: -3), blur: 14, color: CGColor(gray: 0, alpha: 0.32))
        ctx.setFillColor(CGColor(gray: 1, alpha: 1))
        ctx.fill(blatt)
        ctx.restoreGState()

        ctx.saveGState()
        ctx.clip(to: blatt)
        ctx.translateBy(x: ursprung.x, y: ursprung.y)
        ctx.scaleBy(x: skala, y: skala)
        var o = BlattZeichner.Optionen.bildschirm
        o.papier = nil
        let sicht = CGRect(origin: mm(dirtyRect.origin), size: CGSize(width: dirtyRect.width / skala,
                                                                      height: dirtyRect.height / skala))
        o.ausschnitt = sicht
        let (ohneMasse, ohneAnsichten, ohneTexte) = ausgeblendet(z)
        o.ohneMasse = ohneMasse
        o.ohneAnsichten = ohneAnsichten
        o.ohneTexte = ohneTexte
        var ausBild = false
        let backing = pixelJePunkt
        // Während Zoom und Verschieben aus dem Zwischenbild, wenn das Rastern des sichtbaren Teils spürbar Zeit kostet
        // (gemessen am Zwischenbild) und das Bild scharf genug ist; in Ruhe immer als Vektor
        let sichtbarMpx = Double(blatt.intersection(dirtyRect).width * blatt.intersection(dirtyRect).height
                                 * backing * backing) / 1e6
        let teuer = rasterMsJeMpx * sichtbarMpx
        if interaktiv, teuer > 5, ohneMasse.isEmpty, ohneAnsichten.isEmpty, ohneTexte.isEmpty,
           let c = zwischenspeicher, c.stand == z.stand, c.pxJeMM >= skala * backing * 0.7 || teuer > 14
        {
            ctx.interpolationQuality = .medium
            ctx.draw(c.bild, in: CGRect(origin: .zero, size: z.groesse))
            ausBild = true
        } else {
            BlattZeichner.zeichne(z, in: ctx, optionen: o)
        }
        zeichneBewegtes(z, in: ctx, ohneMasse: ohneMasse, ohneAnsichten: ohneAnsichten, ohneTexte: ohneTexte)
        zeichneUeberlagerung(z, in: ctx)
        ctx.restoreGState()

        let ms = (CACurrentMediaTime() - t0) * 1000
        BlattMesswerte.shared.bild(ms: ms, zwischenspeicher: ausBild)
        if let e = ersteDarstellungFuer, e.blatt == z.id {
            let gesamt = Date().timeIntervalSince(e.seit) * 1000
            BlattMesswerte.shared.erste(z.id, ms: gesamt)
            model?.append(LogLine(text: "Blatt \(z.id): erste Darstellung nach \(Int(gesamt)) ms (Zeichnen \(Int(ms)) ms)"))
            ersteDarstellungFuer = nil
        }
    }

    /// Was gerade gezogen wird oder auf die Antwort wartet, zeichnet die Ansicht selbst an der neuen Stelle.
    private func ausgeblendet(_ z: Zeichnung) -> (Set<String>, Set<String>, Set<Int>) {
        var masse = Set<String>()
        var ansichten = Set<String>()
        var notizen = Set<String>()
        if let a = ausstehend {
            masse.formUnion(a.masse.keys)
            ansichten.formUnion(a.ansichten.keys)
            notizen.formUnion(a.notizen.keys)
        }
        switch geste {
        case .mass(let id, _, _) where gezogen: masse.insert(id)
        case .ansicht(let id, _) where gezogen: ansichten.insert(id)
        case .notiz(let id, _) where gezogen: notizen.insert(id)
        default: break
        }
        if schubs != .zero, let e = element {
            switch e {
            case .mass(let id): masse.insert(id)
            case .ansicht(let id): ansichten.insert(id)
            case .notiz(let id): notizen.insert(id)
            }
        }
        var texte = Set<Int>()
        for id in ansichten { texte.formUnion(titelTexte(von: id, in: z)) }
        for id in notizen { if let i = notizIndex(id, in: z) { texte.insert(i) } }
        return (masse, ansichten, texte)
    }

    /// Titel einer Ansicht („A–A“, „Einzelheit B (5:1)“, Maßstab) gehören beim Verschieben dazu.
    private func titelTexte(von id: String, in z: Zeichnung) -> [Int] {
        guard let g = z.gruppe(id) else { return [] }
        let feld = g.rahmen.insetBy(dx: -4, dy: -14)
        return z.texte.indices.filter { i in
            let t = z.texte[i]
            return ["ansicht", "schnitt", "einzelheit"].contains(t.art) && feld.contains(t.lage)
        }
    }

    /// Index des Notiztexts in `Zeichnung.texte`.
    private func notizIndex(_ id: String, in z: Zeichnung) -> Int? {
        let notizen = z.blatt.notizen.filter { !$0.text.isEmpty }
        guard let k = notizen.firstIndex(where: { $0.id == id }) else { return nil }
        let indices = z.texte.indices.filter { z.texte[$0].art == "notiz" }
        return k < indices.count ? indices[k] : nil
    }

    private func zeichneBewegtes(_ z: Zeichnung, in ctx: CGContext, ohneMasse: Set<String>, ohneAnsichten: Set<String>,
                                 ohneTexte: Set<Int>) {
        let schwarz = CGColor(gray: 0, alpha: 1)
        // Ansichten (gezogen oder ausstehend) samt ihrer Maße und Titel
        for id in ohneAnsichten {
            guard let gi = z.grafik.gruppen.firstIndex(where: { $0.id == id }) else { continue }
            let d = versatz(ansicht: id)
            ctx.saveGState()
            ctx.translateBy(x: d.dx, y: d.dy)
            ctx.setStrokeColor(schwarz)
            ctx.setLineCap(.round)
            ctx.setLineJoin(.round)
            BlattZeichner.zeichneGruppe(z.grafik.gruppen[gi], in: ctx, optionen: .bildschirm)
            for m in z.grafik.masse where m.mass.ansicht == id && !ohneMasse.contains(m.mass.id) {
                BlattZeichner.zeichneMass(m, in: ctx, farbe: farbe(m.mass), optionen: .bildschirm)
            }
            for i in titelTexte(von: id, in: z) { BlattZeichner.zeichneText(z.grafik.texte[i], in: ctx, farbe: schwarz) }
            ctx.restoreGState()
        }
        // Maße
        for id in ohneMasse {
            guard let m = vorschauMass(id, z) else { continue }
            let d = z.mass(id)?.ansicht.map { versatz(ansicht: $0) } ?? .zero
            ctx.saveGState()
            ctx.translateBy(x: d.dx, y: d.dy)
            let ausgewaehlt = element == .mass(id)
            BlattZeichner.zeichneMass(m, in: ctx, farbe: ausgewaehlt ? Self.auswahlFarbe.cgColor : farbe(m.mass),
                                      optionen: .bildschirm, dicker: ausgewaehlt ? 1.6 : 1)
            ctx.restoreGState()
        }
        // Notizen
        for (i, t) in z.grafik.texte.enumerated() where ohneTexte.contains(i) && z.texte[i].art == "notiz" {
            guard let n = z.notizTexte.first(where: { $0.text.lage == t.text.lage })?.notiz else { continue }
            let d = versatz(notiz: n.id)
            ctx.saveGState()
            ctx.translateBy(x: d.dx, y: d.dy)
            BlattZeichner.zeichneText(t, in: ctx, farbe: element == .notiz(n.id) ? Self.auswahlFarbe.cgColor : schwarz)
            ctx.restoreGState()
        }
    }

    private func farbe(_ m: MassDarstellung) -> CGColor {
        m.verwaist ? BlattZeichner.rot : CGColor(gray: 0, alpha: 1)
    }

    private func versatz(ansicht id: String) -> CGVector {
        if case .ansicht(let g, _) = geste, g == id, gezogen { return zug }
        if element == .ansicht(id), schubs != .zero { return schubs }
        return ausstehend?.ansichten[id] ?? .zero
    }

    private func versatz(notiz id: String) -> CGVector {
        if case .notiz(let g, _) = geste, g == id, gezogen { return zug }
        if element == .notiz(id), schubs != .zero { return schubs }
        return ausstehend?.notizen[id] ?? .zero
    }

    /// Maß an der Stelle, an die es gerade gezogen wird (oder nach dem Loslassen bis zur Antwort steht).
    private func vorschauMass(_ id: String, _ z: Zeichnung) -> MassGrafik? {
        if case .mass(let g, let art, _) = geste, g == id, gezogen, let m = z.mass(id) {
            return MassGrafik(MassVorschau.verschoben(m, blatt: z.blatt.mass(id), um: zug, text: art == .text))
        }
        if element == .mass(id), schubs != .zero, let m = z.mass(id) {
            return MassGrafik(MassVorschau.verschoben(m, blatt: z.blatt.mass(id), um: schubs, text: false))
        }
        return ausstehend?.masse[id]
    }

    // MARK: Überlagerung (Auswahl, Werkzeuge)

    private func zeichneUeberlagerung(_ z: Zeichnung, in ctx: CGContext) {
        let akzent = Self.auswahlFarbe.cgColor
        let px = 1 / skala
        ctx.setLineCap(.round)
        ctx.setLineJoin(.round)
        // Hervorhebung unter dem Zeiger (Auswahlwerkzeug)
        if werkzeug == .auswahl, case .keine = geste, maus != nil, let h = hoverElement, h != element,
           BlattLeinwand.gibt(h, in: z)
        {
            zeichneHervorhebung(h, z, in: ctx, farbe: akzent.copy(alpha: 0.55) ?? akzent, staerke: 1.3)
        }
        if let e = element, !(gezogen && istGezogen(e)), schubs == .zero || !istElement(e) {
            zeichneHervorhebung(e, z, in: ctx, farbe: akzent, staerke: 1.6)
        }
        switch werkzeug {
        case .mass:
            ctx.setStrokeColor(akzent)
            ctx.setLineWidth(max(0.5, 2.2 * px))
            if let h = hoverLinie {
                ctx.addLines(between: h.linie)
                ctx.strokePath()
            }
            for k in massKlicks {
                if let l = k.linie {
                    ctx.addLines(between: l)
                    ctx.strokePath()
                }
                let q = k.linie.map { Geometrie2D.naechsterPunkt(k.punkt, auf: $0) } ?? k.punkt
                ctx.setFillColor(akzent)
                ctx.fillEllipse(in: CGRect(x: q.x - 3 * px, y: q.y - 3 * px, width: 6 * px, height: 6 * px))
            }
            if massKlicks.count == 2, let m = maus, let v = massVorschau(maus: m, z) {
                BlattZeichner.zeichneMass(MassGrafik(v.darstellung), in: ctx, farbe: akzent, optionen: .bildschirm)
            }
        case .notiz:
            if let a = notizStart, let m = maus, hypot(m.x - a.x, m.y - a.y) > 3 {
                ctx.setStrokeColor(akzent)
                ctx.setLineWidth(max(0.25, 1.2 * px))
                ctx.move(to: a)
                ctx.addLine(to: m)
                ctx.strokePath()
                ctx.setFillColor(akzent)
                ctx.fillEllipse(in: CGRect(x: a.x - 0.6, y: a.y - 0.6, width: 1.2, height: 1.2))
            }
        case .ansicht(let art):
            if let m = maus {
                ctx.setStrokeColor(akzent)
                ctx.setLineWidth(max(0.25, 1.2 * px))
                ctx.setLineDash(phase: 0, lengths: [4 * px, 3 * px])
                let r = CGRect(x: m.x - 30, y: m.y - 20, width: 60, height: 40)
                ctx.stroke(r)
                ctx.setLineDash(phase: 0, lengths: [])
                ctx.move(to: CGPoint(x: m.x - 4, y: m.y))
                ctx.addLine(to: CGPoint(x: m.x + 4, y: m.y))
                ctx.move(to: CGPoint(x: m.x, y: m.y - 4))
                ctx.addLine(to: CGPoint(x: m.x, y: m.y + 4))
                ctx.strokePath()
                BlattZeichner.zeichneText(
                    BlattText(text: ZeichnungText.ansichtArt(art), lage: CGPoint(x: m.x, y: m.y - 26), hoehe: 3.5,
                              anker: .mitte), in: ctx, farbe: akzent)
            }
        case .schnitt:
            if let a = schnittStart, let m = maus {
                zeichneSchnittVorschau(von: a, bis: schnittPunkt(a, m), z, in: ctx, farbe: akzent)
            } else if let m = maus {
                zeichneFadenkreuz(m, in: ctx, farbe: akzent)
            }
        case .einzelheit:
            if case .einzelheitNeu(let c) = geste, let m = maus {
                let r = hypot(m.x - c.x, m.y - c.y)
                ctx.setStrokeColor(akzent)
                ctx.setLineWidth(max(0.25, 1.4 * px))
                ctx.strokeEllipse(in: CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r))
                ctx.setLineDash(phase: 0, lengths: [3 * px, 3 * px])
                ctx.move(to: c)
                ctx.addLine(to: m)
                ctx.strokePath()
                ctx.setLineDash(phase: 0, lengths: [])
                BlattZeichner.zeichneText(
                    BlattText(text: "Einzelheit \(naechsterBuchstabe(z))", lage: CGPoint(x: c.x, y: c.y + r + 2),
                              hoehe: 3.5, anker: .mitte), in: ctx, farbe: akzent)
            } else if let m = maus {
                zeichneFadenkreuz(m, in: ctx, farbe: akzent)
            }
        case .auswahl:
            break
        }
    }

    private func zeichneFadenkreuz(_ m: CGPoint, in ctx: CGContext, farbe: CGColor) {
        ctx.setStrokeColor(farbe)
        ctx.setLineWidth(max(0.25, 1.2 / skala))
        ctx.move(to: CGPoint(x: m.x - 4, y: m.y))
        ctx.addLine(to: CGPoint(x: m.x + 4, y: m.y))
        ctx.move(to: CGPoint(x: m.x, y: m.y - 4))
        ctx.addLine(to: CGPoint(x: m.x, y: m.y + 4))
        ctx.strokePath()
    }

    /// Schnittverlauf wie auf dem Blatt (Strichpunkt, Enden breit) mit Pfeilen in Blickrichtung: zur größeren Hälfte
    /// der Ansicht, bei einer Linie durch die Mitte nach links der Zeichenrichtung (wie der Kernel rechnet).
    private func zeichneSchnittVorschau(von a: CGPoint, bis b: CGPoint, _ z: Zeichnung, in ctx: CGContext,
                                        farbe: CGColor)
    {
        let px = 1 / skala
        let d = CGVector(dx: b.x - a.x, dy: b.y - a.y)
        let l = hypot(d.dx, d.dy)
        guard l > 0.5 else { return }
        let u = CGVector(dx: d.dx / l, dy: d.dy / l)
        var n = CGVector(dx: -u.dy, dy: u.dx)
        let mitte = CGPoint(x: (a.x + b.x) / 2, y: (a.y + b.y) / 2)
        if let vid = ansichtTreffer(mitte, z), let g = z.gruppe(vid) {
            let seite = (g.rahmen.midX - a.x) * n.dx + (g.rahmen.midY - a.y) * n.dy
            if abs(seite) > 0.02 * max(g.rahmen.width, g.rahmen.height), seite < 0 { n = CGVector(dx: -n.dx, dy: -n.dy) }
        }
        if Self.schnittUmgekehrt { n = CGVector(dx: -n.dx, dy: -n.dy) }  // ⌥: zur anderen Seite blicken
        ctx.setStrokeColor(farbe)
        ctx.setLineWidth(max(0.25, 1.2 * px))
        ctx.setLineDash(phase: 0, lengths: [6, 1.5, 0.6, 1.5])
        ctx.move(to: a)
        ctx.addLine(to: b)
        ctx.strokePath()
        ctx.setLineDash(phase: 0, lengths: [])
        ctx.setLineWidth(max(0.5, 2.6 * px))
        for (p, s) in [(a, 1.0), (b, -1.0)] {
            ctx.move(to: p)
            ctx.addLine(to: CGPoint(x: p.x + u.dx * 5 * s, y: p.y + u.dy * 5 * s))
            ctx.strokePath()
            // Pfeil in Blickrichtung an jedem Ende, mit dem Namen daneben
            let fuss = CGPoint(x: p.x + u.dx * 2.5 * s, y: p.y + u.dy * 2.5 * s)
            let spitze = CGPoint(x: fuss.x + n.dx * 7, y: fuss.y + n.dy * 7)
            ctx.setLineWidth(max(0.25, 1.2 * px))
            ctx.move(to: fuss)
            ctx.addLine(to: spitze)
            ctx.strokePath()
            let tri = CGMutablePath()
            tri.addLines(between: [
                spitze,
                CGPoint(x: spitze.x - n.dx * 2.6 + u.dx * 0.9, y: spitze.y - n.dy * 2.6 + u.dy * 0.9),
                CGPoint(x: spitze.x - n.dx * 2.6 - u.dx * 0.9, y: spitze.y - n.dy * 2.6 - u.dy * 0.9),
            ])
            tri.closeSubpath()
            ctx.setFillColor(farbe)
            ctx.addPath(tri)
            ctx.fillPath()
            BlattZeichner.zeichneText(
                BlattText(text: naechsterBuchstabe(z), lage: CGPoint(x: spitze.x + u.dx * 3 * s, y: spitze.y - 1.2),
                          hoehe: 3.5, anker: .mitte), in: ctx, farbe: farbe)
            ctx.setLineWidth(max(0.5, 2.6 * px))
        }
    }

    /// ⌥ beim Ziehen des Schnitts: Blick zur anderen Seite als vorgeschlagen.
    static var schnittUmgekehrt: Bool { tasteWahl }

    #if os(macOS)
    static var tasteWahl: Bool { NSEvent.modifierFlags.contains(.option) }
    static var tasteUmschalt: Bool { NSEvent.modifierFlags.contains(.shift) }
    #else
    static var tasteWahl: Bool { tasten.contains(.alternate) }
    static var tasteUmschalt: Bool { tasten.contains(.shift) }
    #endif

    /// Zweiter Punkt der Schnittlinie; fast waagrecht oder senkrecht (unter 4°) oder mit Umschalt rastet sie ein.
    private func schnittPunkt(_ a: CGPoint, _ m: CGPoint) -> CGPoint {
        let dx = m.x - a.x, dy = m.y - a.y
        if Self.tasteUmschalt {
            return abs(dx) >= abs(dy) ? CGPoint(x: m.x, y: a.y) : CGPoint(x: a.x, y: m.y)
        }
        let winkel = abs(atan2(dy, dx)) * 180 / .pi  // 0 … 180
        if min(winkel, 180 - winkel) < 4 { return CGPoint(x: m.x, y: a.y) }
        if abs(90 - winkel) < 4 { return CGPoint(x: a.x, y: m.y) }
        return m
    }

    /// Name, den der Kernel dem nächsten Schnitt bzw. der nächsten Einzelheit gibt (A, B, … ohne I, O, Q).
    private func naechsterBuchstabe(_ z: Zeichnung) -> String {
        let benutzt = Set((z.blatt.json["ansichten"]?.arrayValue ?? []).compactMap {
            ($0["schnitt"]?["name"] ?? $0["einzelheit"]?["name"])?.stringValue
        })
        return "ABCDEFGHJKLMNPRSTUVWXYZ".map(String.init).first { !benutzt.contains($0) } ?? "Z"
    }

    private func schnittSetzen(_ a: CGPoint, _ b: CGPoint, _ z: Zeichnung) {
        schnittStart = nil
        let mitte = CGPoint(x: (a.x + b.x) / 2, y: (a.y + b.y) / 2)
        guard hypot(b.x - a.x, b.y - a.y) * skala >= 8 else {
            kurzerHinweis("Schnitt: die Linie ist zu kurz, durch die ganze Ansicht ziehen")
            return
        }
        guard let vid = ansichtTreffer(mitte, z) else {
            kurzerHinweis("Schnitt: die Linie muss durch eine Ansicht gehen")
            needsDisplay = true
            return
        }
        bearbeite([.schnittNeu(von: vid, linie: [a, b], umkehren: Self.schnittUmgekehrt)])
        zustand?.setzeWerkzeug(.auswahl)
    }

    private func einzelheitSetzen(_ c: CGPoint, _ m: CGPoint, _ z: Zeichnung) {
        let r = hypot(m.x - c.x, m.y - c.y)
        guard r * skala >= 6, r >= 1 else {
            kurzerHinweis("Einzelheit: von der Mitte aus einen Kreis aufziehen")
            return
        }
        guard let vid = ansichtTreffer(c, z) else {
            kurzerHinweis("Einzelheit: die Mitte muss in einer Ansicht liegen")
            return
        }
        bearbeite([.einzelheitNeu(von: vid, mitte: c, radius: (Double(r) * 100).rounded() / 100)])
        zustand?.setzeWerkzeug(.auswahl)
    }

    private func istGezogen(_ e: BlattElement) -> Bool {
        switch (geste, e) {
        case (.mass(let a, _, _), .mass(let b)): return a == b
        case (.ansicht(let a, _), .ansicht(let b)): return a == b
        case (.notiz(let a, _), .notiz(let b)): return a == b
        default: return false
        }
    }

    private func istElement(_ e: BlattElement) -> Bool { element == e }

    private func zeichneHervorhebung(_ e: BlattElement, _ z: Zeichnung, in ctx: CGContext, farbe: CGColor,
                                     staerke: CGFloat) {
        switch e {
        case .mass(let id):
            guard ausstehend?.masse[id] == nil, let m = z.grafik.mass(id) else { return }
            BlattZeichner.zeichneMass(m, in: ctx, farbe: farbe, optionen: .bildschirm, dicker: staerke)
        case .ansicht(let id):
            guard let g = z.gruppe(id) else { return }
            let d = versatz(ansicht: id)
            let r = g.rahmen.insetBy(dx: -3, dy: -3).offsetBy(dx: d.dx, dy: d.dy)
            ctx.saveGState()
            ctx.setFillColor(farbe.copy(alpha: 0.06) ?? farbe)
            ctx.fill(r)
            ctx.setStrokeColor(farbe)
            ctx.setLineWidth(1.2 / skala * staerke)
            ctx.setLineDash(phase: 0, lengths: [5 / skala, 3 / skala])
            ctx.stroke(r)
            ctx.restoreGState()
        case .notiz(let id):
            guard let i = notizIndex(id, in: z) else { return }
            let d = versatz(notiz: id)
            ctx.saveGState()
            ctx.translateBy(x: d.dx, y: d.dy)
            BlattZeichner.zeichneText(z.grafik.texte[i], in: ctx, farbe: farbe)
            ctx.setStrokeColor(farbe)
            ctx.setLineWidth(1 / skala)
            ctx.stroke(z.grafik.texte[i].rahmen.insetBy(dx: -0.8, dy: -0.8))
            ctx.restoreGState()
        }
    }

    // MARK: Treffer

    /// Element unter dem Punkt (Blatt-mm): Maß (Zahl vor Linie), Notiz, Ansicht.
    func treffer(_ p: CGPoint, in z: Zeichnung) -> BlattElement? {
        if let m = massTreffer(p, z) { return .mass(m.id) }
        if let n = notizTreffer(p, z) { return .notiz(n) }
        if let a = ansichtTreffer(p, z) { return .ansicht(a) }
        return nil
    }

    private func massTreffer(_ p: CGPoint, _ z: Zeichnung) -> (id: String, aufText: Bool)? {
        var best: (String, CGFloat, Bool)?
        for m in z.grafik.masse where m.huelle.insetBy(dx: -toleranz, dy: -toleranz).contains(p) {
            if m.trifftText(p, toleranz: 0.3) { return (m.mass.id, true) }
            let d = m.abstand(zu: p)
            if d <= toleranz, best == nil || d < best!.1 { best = (m.mass.id, d, false) }
        }
        return best.map { ($0.0, $0.2) }
    }

    private func notizTreffer(_ p: CGPoint, _ z: Zeichnung) -> String? {
        for n in z.blatt.notizen {
            if let i = notizIndex(n.id, in: z), z.grafik.texte[i].enthaelt(p, toleranz: toleranz) { return n.id }
        }
        return nil
    }

    private func ansichtTreffer(_ p: CGPoint, _ z: Zeichnung) -> String? {
        z.ansichten.filter { $0.rahmen.insetBy(dx: -2, dy: -2).contains(p) }
            .min { $0.rahmen.width * $0.rahmen.height < $1.rahmen.width * $1.rahmen.height }?.id
    }

    /// Feld des Schriftfelds unter dem Punkt (Bezeichnung über dem Wert, links oben in der Zelle).
    func schriftfeldTreffer(_ p: CGPoint, _ z: Zeichnung) -> (feld: String, titel: String)? {
        let labels = z.texte.filter { $0.art == "schriftfeld_label" }
        guard !labels.isEmpty else { return nil }
        let huelle = z.texte.filter { $0.art.hasPrefix("schriftfeld") }.map(\.lage)
        guard let x0 = huelle.map(\.x).min(), let y1 = huelle.map(\.y).max(), p.x >= x0 - 2, p.y <= y1 + 3 else {
            return nil
        }
        let kandidaten = labels.filter { $0.lage.x <= p.x + 0.5 && $0.lage.y >= p.y - 0.5 && $0.lage.y - p.y < 10 }
        guard let l = kandidaten.max(by: { ($0.lage.x - $0.lage.y * 1000) < ($1.lage.x - $1.lage.y * 1000) }) else {
            return nil
        }
        // In derselben Zeile das Label mit dem größten x links vom Punkt
        let zeile = kandidaten.filter { abs($0.lage.y - l.lage.y) < 0.5 }
        guard let zelle = zeile.max(by: { $0.lage.x < $1.lage.x }), let feld = Self.schriftfelder[zelle.text] else {
            return nil
        }
        return (feld, zelle.text)
    }

    /// Bezeichnungen im Schriftfeld (Kernel) → Feld der Blattdatei.
    static let schriftfelder: [String: String] = [
        "Benennung": "benennung", "Sachnummer": "zeichnungsnummer", "Werkstoff": "werkstoff", "Halbzeug": "halbzeug",
        "Allgemeintoleranz": "allgemeintoleranz", "Stückzahl": "stueckzahl", "Dokumentart": "dokumentart",
        "Version": "version", "Projekt": "projekt", "Eigentümer": "eigentuemer", "Erstellt": "gezeichnet",
        "Freigegeben": "freigegeben", "Ausgabedatum": "datum",
    ]

    /// Nächste Kante (Polylinie) einer Ansicht unter dem Punkt, für das Maß-Werkzeug.
    private func kante(_ p: CGPoint, _ z: Zeichnung) -> (ansicht: String, linie: [CGPoint])? {
        guard let vid = ansichtTreffer(p, z), let g = z.gruppe(vid) else { return nil }
        var best: ([CGPoint], CGFloat)?
        for art in ["sichtbar", "verdeckt", "mitte"] {
            for pl in g.linien[art] ?? [] {
                let d = Geometrie2D.abstand(p, zu: pl) + (art == "sichtbar" ? 0 : 0.4)
                if d < max(2.5, toleranz), best == nil || d < best!.1 { best = (pl, d) }
            }
        }
        // Der Kernel fasst Kanten zu Zügen zusammen: nur das glatte Stück bis zur nächsten Ecke ist die Kante
        return best.map { (vid, MassVorschau.kantenzug($0.0, nahe: p)) }
    }

    // MARK: Zeiger, Drücken, Ziehen, Loslassen (gemeinsam für Maus, Finger und Stift; `v` in Ansichtspunkten, y oben)

    private enum ZeigerForm { case pfeil, offen, zu, kreuz }

    /// Mauszeiger setzen. Nur am Mac; am iPad zeigt der Zeiger des Systems selbst, was unter ihm liegt.
    private func zeigerForm(_ f: ZeigerForm) {
        #if os(macOS)  // nur am Mac: Mauszeiger (iPad: Zeiger des Systems)
        switch f {
        case .pfeil: NSCursor.arrow.set()
        case .offen: NSCursor.openHand.set()
        case .zu: NSCursor.closedHand.set()
        case .kreuz: NSCursor.crosshair.set()
        }
        #endif
    }

    /// Zeiger, schwebender Stift oder Trackpad über dem Blatt (ohne gedrückt).
    func zeigerBewegt(_ v: CGPoint) {
        let p = mm(v)
        maus = p
        zustand?.anzeige.zeiger = p
        // Neu zeichnen nur, wenn sich die Hervorhebung ändert oder eine Vorschau dem Zeiger folgt
        var neu = false
        switch werkzeug {
        case .mass:
            if let z = zeichnung {
                let k = kante(p, z)
                if k?.linie != hoverLinie?.linie {
                    hoverLinie = k
                    neu = true
                }
            }
            neu = neu || massKlicks.count == 2
        case .auswahl:
            if let z = zeichnung {
                // Zeiger zeigt, was sich ziehen lässt: Maß, Notiz, Ansicht; leeres Papier verschiebt das Blatt
                let t = treffer(p, in: z)
                zeigerForm(t != nil ? .offen : .pfeil)
                if t != hoverElement {
                    hoverElement = t
                    neu = true
                }
            }
        case .ansicht, .notiz, .schnitt, .einzelheit:
            neu = true
        }
        if neu { needsDisplay = true }
    }

    func zeigerWeg() {
        maus = nil
        hoverElement = nil
        zustand?.anzeige.zeiger = nil
        hoverLinie = nil
        needsDisplay = true
    }

    /// Drücken: `klicks` 2 ist ein Doppelklick bzw. Doppeltippen; `schwenken` verschiebt immer das Blatt (⌥ oder
    /// mittlere Maustaste am Mac).
    func druecke(_ v: CGPoint, klicks: Int, schwenken: Bool) {
        schliesseEingabe()
        guard let z = zeichnung else { return }
        let p = mm(v)
        gezogen = false
        zug = .zero
        if schwenken {
            geste = .schwenken(start: v, ursprung0: ursprung)
            return
        }
        switch werkzeug {
        case .auswahl:
            if klicks == 2 {
                doppelklick(p, z)
                return
            }
            if let m = massTreffer(p, z) {
                waehle(.mass(m.id))
                let hinweis = z.mass(m.id)?.istHinweis ?? false
                let kette = z.mass(m.id)?.art == "bezugskette"
                geste = .mass(id: m.id, art: (m.aufText || hinweis) && !kette ? .text : .versatz, start: p)
            } else if let n = notizTreffer(p, z) {
                waehle(.notiz(n))
                geste = .notiz(id: n, start: p)
            } else if let a = ansichtTreffer(p, z) {
                waehle(.ansicht(a))
                geste = .ansicht(id: a, start: p)
            } else {
                waehle(nil)
                geste = .schwenken(start: v, ursprung0: ursprung)
            }
        case .mass:
            massKlick(p, z, doppelt: klicks == 2)
        case .notiz:
            notizStart = p
            geste = .notizNeu(start: p)
        case .ansicht(let art):
            bearbeite([.ansichtNeu(art: art, lage: p)])
            zustand?.setzeWerkzeug(.auswahl)
        case .schnitt:
            if let a = schnittStart {  // zweiter Klick
                schnittSetzen(a, schnittPunkt(a, p), z)
            } else {
                schnittStart = p
                geste = .schnittNeu(start: p)
                hinweisAktualisieren()
            }
        case .einzelheit:
            geste = .einzelheitNeu(mitte: p)
        }
    }

    /// Ziehen mit gedrückter Taste bzw. aufliegendem Finger; `nurAchse` (Umschalt) rastet waagrecht oder senkrecht ein.
    func ziehe(_ v: CGPoint, nurAchse: Bool) {
        let p = mm(v)
        maus = p
        zustand?.anzeige.zeiger = p
        switch geste {
        case .keine:
            break
        case .schwenken(let start, let u0):
            eingepasst = false
            ursprung = CGPoint(x: u0.x + v.x - start.x, y: u0.y + v.y - start.y)
            interagiere()
            zeigerForm(.zu)
            ansichtGeaendert()
        case .mass(_, _, let start), .ansicht(_, let start), .notiz(_, let start):
            let d = CGVector(dx: p.x - start.x, dy: p.y - start.y)
            if !gezogen, hypot(d.dx, d.dy) * skala < 3 { return }
            if !gezogen { zeigerForm(.zu) }
            gezogen = true
            zug = d
            if nurAchse {  // Umschalt: nur waagrecht oder senkrecht
                if abs(d.dx) > abs(d.dy) { zug.dy = 0 } else { zug.dx = 0 }
            }
            needsDisplay = true
        case .notizNeu, .schnittNeu, .einzelheitNeu:
            needsDisplay = true
        }
    }

    /// Ein zweiter Finger, das Kontextmenü oder das System hat die Berührung übernommen: nichts übernehmen.
    func gesteAbbrechen() {
        if case .notizNeu = geste { notizStart = nil }
        geste = .keine
        gezogen = false
        zug = .zero
        needsDisplay = true
    }

    func lasse(_ v: CGPoint) {
        defer {
            geste = .keine
            gezogen = false
            zug = .zero
        }
        guard let z = zeichnung else { return }
        let p = mm(v)
        protokolliere("Loslassen bei \(p), gezogen \(gezogen), Zug \(zug)")
        switch geste {
        case .schwenken:
            zeigerForm(.pfeil)
        case .mass(let id, let art, _) where gezogen:
            guard let m = z.mass(id) else { return }
            let neu = MassVorschau.verschoben(m, blatt: z.blatt.mass(id), um: zug, text: art == .text)
            let op: ZeichnungsOp
            if art == .text {
                op = .massVerschieben(id: id, versatz: nil, textLage: neu.textAnker)
            } else {
                guard let v = MassVorschau.neuerVersatz(m, blatt: z.blatt.mass(id), um: zug) else { return }
                op = .massVerschieben(id: id, versatz: (v * 100).rounded() / 100, textLage: nil)
            }
            merkeAusstehend { $0.masse[id] = MassGrafik(neu) }
            bearbeite([op])
        case .ansicht(let id, _) where gezogen:
            guard let lage = ansichtLage(id, z) else { return }
            let d = zug
            merkeAusstehend { $0.ansichten[id] = d }
            bearbeite([.ansichtVerschieben(id: id, lage: CGPoint(x: lage.x + d.dx, y: lage.y + d.dy))])
        case .notiz(let id, _) where gezogen:
            guard let n = z.blatt.notizen.first(where: { $0.id == id }) else { return }
            let d = zug
            merkeAusstehend { $0.notizen[id] = d }
            bearbeite([.notizLoeschen(id: id), .notiz(text: n.text, lage: CGPoint(x: n.lage.x + d.dx, y: n.lage.y + d.dy),
                                                      zeiger: Self.zeiger(n))], titel: "Notiz verschieben")
        case .schnittNeu(let start):
            // gezogen statt geklickt: Loslassen setzt den Schnitt, sonst wartet er auf den zweiten Klick
            if hypot(p.x - start.x, p.y - start.y) * skala >= 8 { schnittSetzen(start, schnittPunkt(start, p), z) }
        case .einzelheitNeu(let c):
            einzelheitSetzen(c, p, z)
        case .notizNeu(let start):
            notizStart = nil
            let mitZeiger = hypot(p.x - start.x, p.y - start.y) > 3
            let zeiger = mitZeiger ? ZeichnungsKlick(ansicht: ansichtTreffer(start, z), punkt: start) : nil
            let lage = mitZeiger ? p : start
            zeigeEingabe(BlattTextEingabe(zweck: .notiz(lage: lage, zeiger: zeiger), titel: "Notiz", text: "", ort: lage))
        default:
            break
        }
        needsDisplay = true
    }

    #if os(macOS)  // Maus am Mac; iPad: Berührung, Stift und Schweben am Ende der Datei
    override func mouseMoved(with event: NSEvent) {
        zeigerBewegt(convert(event.locationInWindow, from: nil))
    }

    override func mouseExited(with event: NSEvent) {
        zeigerWeg()
    }

    override func cursorUpdate(with event: NSEvent) {
        switch werkzeug {
        case .auswahl: NSCursor.arrow.set()
        default: NSCursor.crosshair.set()
        }
    }

    override func mouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self)
        druecke(convert(event.locationInWindow, from: nil), klicks: event.clickCount,
                schwenken: event.modifierFlags.contains(.option) && werkzeug == .auswahl || event.buttonNumber == 2)
    }

    override func mouseDragged(with event: NSEvent) {
        ziehe(convert(event.locationInWindow, from: nil), nurAchse: event.modifierFlags.contains(.shift))
    }

    override func mouseUp(with event: NSEvent) {
        lasse(convert(event.locationInWindow, from: nil))
    }
    #endif

    static func zeiger(_ n: BlattNotiz) -> ZeichnungsKlick? { BlattWerte.zeiger(n) }

    private func ansichtLage(_ id: String, _ z: Zeichnung) -> CGPoint? {
        if let l = z.blatt.ansicht(id)?.lage { return l }
        return z.gruppe(id).map { CGPoint(x: $0.rahmen.midX, y: $0.rahmen.midY) }
    }

    private func merkeAusstehend(_ f: (inout Ausstehend) -> Void) {
        guard let z = zeichnung else { return }
        var a = ausstehend ?? Ausstehend(stand: z.stand)
        a.stand = z.stand
        a.seit = Date()
        f(&a)
        ausstehend = a
        // Sicherheitsnetz: kommt keine Antwort, nach 30 s den alten Stand zeigen
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self] in
            guard let self, let a = self.ausstehend, Date().timeIntervalSince(a.seit) >= 29 else { return }
            self.ausstehend = nil
            self.needsDisplay = true
        }
    }

    private func waehle(_ e: BlattElement?) {
        element = e
        if zustand?.element != e { zustand?.element = e }
    }

    private func doppelklick(_ p: CGPoint, _ z: Zeichnung) {
        if let m = massTreffer(p, z), let d = z.mass(m.id) {
            let b = z.blatt.mass(m.id)
            zeigeEingabe(BlattTextEingabe(
                zweck: .massText(id: m.id), titel: "Maß \(d.text)", text: b?.text ?? "", toleranz: b?.toleranz ?? "",
                ort: d.textLage))
        } else if let s = schriftfeldTreffer(p, z) {
            zeigeEingabe(BlattTextEingabe(
                zweck: .schriftfeld(feld: s.feld), titel: s.titel, text: z.blatt.schriftfeldText(s.feld), ort: p))
        } else if ansichtTreffer(p, z) == nil, massTreffer(p, z) == nil {
            einpassen(animiert: true)
        }
    }

    // MARK: Maß-Werkzeug

    private func massKlick(_ p: CGPoint, _ z: Zeichnung, doppelt: Bool) {
        if massKlicks.count == 2 {
            // dritter Klick: Maßlinie hier
            if let v = massVorschau(maus: p, z) {
                let k = massKlicks
                bearbeite([.massNeu(art: nil, ansicht: k[0].ansicht, richtung: v.richtung,
                                    versatz: (v.versatz * 100).rounded() / 100,
                                    klicks: k.map { ZeichnungsKlick(ansicht: $0.ansicht, punkt: Self.angesetzt($0)) },
                                    bezuege: [], text: nil, toleranz: nil)])
            }
            massKlicks = []
            hinweisAktualisieren()
            needsDisplay = true
            return
        }
        guard let vid = ansichtTreffer(p, z) else {
            kurzerHinweis("Maß: in eine Ansicht klicken")
            return
        }
        let k = kante(p, z)
        if doppelt, let erster = massKlicks.first, erster.ansicht == vid {
            // Doppelklick auf ein Element: Maß an diesem Element (Durchmesser, Radius, Bohrung …)
            bearbeite([.massNeu(art: nil, ansicht: vid, richtung: nil, versatz: nil,
                                klicks: [ZeichnungsKlick(ansicht: vid, punkt: Self.angesetzt(erster))], bezuege: [],
                                text: nil, toleranz: nil)])
            massKlicks = []
            hinweisAktualisieren()
            needsDisplay = true
            return
        }
        if let erster = massKlicks.first, erster.ansicht != vid {
            massKlicks = []
        }
        massKlicks.append(Klick(ansicht: vid, punkt: p, linie: k?.ansicht == vid ? k?.linie : nil))
        hinweisAktualisieren()
        needsDisplay = true
    }

    /// Punkt auf der gewählten Kante (sonst der Klick selbst); der Kernel sucht von dort das Element.
    private static func angesetzt(_ k: Klick) -> CGPoint {
        k.linie.map { Geometrie2D.naechsterPunkt(k.punkt, auf: $0) } ?? k.punkt
    }

    private func massVorschau(maus m: CGPoint, _ z: Zeichnung) -> MassVorschau.Neu? {
        guard massKlicks.count == 2, let g = z.gruppe(massKlicks[0].ansicht) else { return nil }
        let frei = Self.tasteWahl
        return MassVorschau.neu(
            a: (Self.angesetzt(massKlicks[0]), massKlicks[0].linie), b: (Self.angesetzt(massKlicks[1]), massKlicks[1].linie),
            maus: m, frei: frei, massstab: g.massstab ?? z.blatt.massstab)
    }

    private func hinweisAktualisieren() {
        let text: String?
        switch werkzeug {
        case .auswahl: text = nil
        case .mass:
            switch massKlicks.count {
            case 0: text = "Maß: erstes Element anklicken (Doppelklick: Maß an einem Element)"
            case 1: text = "Maß: zweites Element anklicken"
            default: text = "Maß: Maßlinie platzieren (⌥ ausgerichtet, Esc bricht ab)"
            }
        case .notiz: text = "Notiz: klicken oder vom Ziel zur Textstelle ziehen"
        case .ansicht(let art): text = "\(ZeichnungText.ansichtArt(art)): Stelle auf dem Blatt anklicken"
        case .schnitt:
            text = schnittStart == nil
                ? "Schnitt: Linie durch eine Ansicht ziehen oder Anfang und Ende anklicken (⇧ waagrecht/senkrecht, "
                    + "⌥ Blick zur anderen Seite)"
                : "Schnitt: Ende der Linie anklicken (⌥ Blick zur anderen Seite, Esc bricht ab)"
        case .einzelheit: text = "Einzelheit: auf die Stelle drücken und den Kreis aufziehen"
        }
        if zustand?.anzeige.hinweis != text {
            DispatchQueue.main.async { [weak self] in self?.zustand?.anzeige.hinweis = text }
        }
    }

    /// Hinweis in der Statuszeile, der nach einigen Sekunden wieder dem Hinweis des Werkzeugs weicht.
    private func kurzerHinweis(_ text: String) {
        zustand?.anzeige.hinweis = text
        DispatchQueue.main.asyncAfter(deadline: .now() + 4) { [weak self] in
            guard let self, self.zustand?.anzeige.hinweis == text else { return }
            self.zustand?.anzeige.hinweis = nil
            self.hinweisAktualisieren()
        }
    }

    // MARK: Rückgängig (Menü Bearbeiten, ⌘Z und ⇧⌘Z)

    #if os(macOS)  // iPad: ⌘Z und ⇧⌘Z der Hardware-Tastatur über `keyCommands` am Ende der Datei
    @objc func undo(_ sender: Any?) { zustand?.bearbeiter.rueckgaengig() }
    @objc func redo(_ sender: Any?) { zustand?.bearbeiter.wiederholen() }

    @objc func validateMenuItem(_ item: NSMenuItem) -> Bool {
        guard let b = zustand?.bearbeiter else { return false }
        switch item.action {
        case #selector(undo(_:))?:
            item.title = b.rueckgaengigTitel.map { "Rückgängig: \($0)" } ?? "Rückgängig"
            return b.rueckgaengigTitel != nil
        case #selector(redo(_:))?:
            item.title = b.wiederholenTitel.map { "Wiederholen: \($0)" } ?? "Wiederholen"
            return b.wiederholenTitel != nil
        default:
            return true
        }
    }

    // MARK: Tastatur

    override func flagsChanged(with event: NSEvent) {
        if werkzeug == .schnitt, schnittStart != nil { needsDisplay = true }  // ⌥ dreht die Pfeile der Vorschau
        super.flagsChanged(with: event)
    }

    override func keyDown(with event: NSEvent) {
        let t: Taste?
        switch event.keyCode {
        case 51, 117: t = .loeschen  // Rückschritt, Entfernen
        case 53: t = .esc
        case 123: t = .links
        case 124: t = .rechts
        case 125: t = .runter
        case 126: t = .hoch
        default:
            switch event.charactersIgnoringModifiers {
            case "+", "=": t = .plus
            case "-": t = .minus
            default: t = nil
            }
        }
        guard let t, taste(t, umschalt: event.modifierFlags.contains(.shift)) else { return super.keyDown(with: event) }
    }
    #endif

    /// Tasten der Leinwand, gleich für die Tastatur am Mac und die Hardware-Tastatur am iPad.
    enum Taste { case loeschen, esc, links, rechts, runter, hoch, plus, minus }

    /// Führt eine Taste aus; `false`, wenn sie hier nichts tut (dann geht sie weiter an die Responder-Kette).
    @discardableResult
    func taste(_ t: Taste, umschalt: Bool) -> Bool {
        switch t {
        case .loeschen:
            loeschen()
        case .esc:
            if massKlicks.isEmpty && notizStart == nil && schnittStart == nil && werkzeug == .auswahl {
                waehle(nil)
            } else {
                massKlicks = []
                notizStart = nil
                schnittStart = nil
                zustand?.setzeWerkzeug(.auswahl)
            }
            needsDisplay = true
        case .links, .rechts, .runter, .hoch:  // Pfeile: Auswahl um 1 mm (mit Umschalt 5 mm) verschieben
            guard element != nil else { return false }
            let s: CGFloat = umschalt ? 5 : 1
            switch t {
            case .links: schubs.dx -= s
            case .rechts: schubs.dx += s
            case .runter: schubs.dy -= s
            default: schubs.dy += s
            }
            needsDisplay = true
            schubsTimer?.invalidate()
            schubsTimer = Timer.scheduledTimer(withTimeInterval: 0.45, repeats: false) { [weak self] _ in
                MainActor.assumeIsolated { self?.schubsSenden() }
            }
        case .plus:
            zoom(faktor: 1.25, um: CGPoint(x: bounds.midX, y: bounds.midY), animiert: true)
        case .minus:
            zoom(faktor: 0.8, um: CGPoint(x: bounds.midX, y: bounds.midY), animiert: true)
        }
        return true
    }

    private func schubsSenden() {
        guard let z = zeichnung, let e = element, schubs != .zero else { return }
        let d = schubs
        switch e {
        case .mass(let id):
            if let m = z.mass(id), let v = MassVorschau.neuerVersatz(m, blatt: z.blatt.mass(id), um: d) {
                merkeAusstehend { $0.masse[id] = MassGrafik(MassVorschau.verschoben(m, blatt: z.blatt.mass(id), um: d,
                                                                                     text: false)) }
                bearbeite([.massVerschieben(id: id, versatz: (v * 100).rounded() / 100, textLage: nil)])
            } else if let m = z.mass(id) {  // Hinweis: Text verschieben
                let neu = MassVorschau.verschoben(m, blatt: z.blatt.mass(id), um: d, text: true)
                merkeAusstehend { $0.masse[id] = MassGrafik(neu) }
                bearbeite([.massVerschieben(id: id, versatz: nil, textLage: neu.textAnker)])
            }
        case .ansicht(let id):
            if let lage = ansichtLage(id, z) {
                merkeAusstehend { $0.ansichten[id] = d }
                bearbeite([.ansichtVerschieben(id: id, lage: CGPoint(x: lage.x + d.dx, y: lage.y + d.dy))])
            }
        case .notiz(let id):
            if let n = z.blatt.notizen.first(where: { $0.id == id }) {
                merkeAusstehend { $0.notizen[id] = d }
                bearbeite([.notizLoeschen(id: id), .notiz(text: n.text, lage: CGPoint(x: n.lage.x + d.dx, y: n.lage.y + d.dy),
                                                          zeiger: Self.zeiger(n))], titel: "Notiz verschieben")
            }
        }
        schubs = .zero
    }

    /// Auswahl löschen (Ansichten nach Rückfrage).
    func loeschen() {
        guard let e = element else { return }
        switch e {
        case .mass(let id):
            bearbeite([.massLoeschen(id: id)])
            if zeichnung?.mass(id)?.quelle == "auto" {
                kurzerHinweis("Automatisches Maß ausgeblendet (⌘Z oder im Inspektor wiederherstellen)")
            }
        case .notiz(let id):
            bearbeite([.notizLoeschen(id: id)])
        case .ansicht(let id):
            zustand?.ansichtLoeschen = id
            return
        }
        waehle(nil)
    }

    private func bearbeite(_ ops: [ZeichnungsOp], titel: String? = nil) {
        guard let z = zeichnung, let zustand else { return }
        protokolliere("Ops \(ops.map(\.name).joined(separator: ", ")) für \(z.id) (Stand \(z.stand))")
        zustand.bearbeiter.ausfuehren(ops, blatt: z.id, titel: titel) { [weak self] erg in
            self?.protokolliere("Antwort ok \(erg.ok) \(erg.fehlerText ?? "")")
            if !erg.ok { self?.aenderungGescheitert() }
        }
    }

    // MARK: Kontextmenü

    /// Eintrag des Kontextmenüs, gemeinsam für NSMenu (Mac) und UIMenu (iPad).
    indirect enum MenueEintrag {
        case knopf(String, destruktiv: Bool = false, @MainActor () -> Void)
        case trenner
        case unter(String, [MenueEintrag])
    }

    /// Einträge für die Stelle `p` (Blatt-mm); wählt das getroffene Element aus.
    func menueEintraege(at p: CGPoint) -> [MenueEintrag] {
        guard let z = zeichnung else { return [] }
        var menu: [MenueEintrag] = []
        #if os(iOS)  // iPad ohne Tastatur: Rückgängig und Wiederholen oben im Menü (am Mac im Menü Bearbeiten)
        if let b = zustand?.bearbeiter {
            if let t = b.rueckgaengigTitel { menu.append(.knopf("Rückgängig: \(t)") { b.rueckgaengig() }) }
            if let t = b.wiederholenTitel { menu.append(.knopf("Wiederholen: \(t)") { b.wiederholen() }) }
            if b.rueckgaengigTitel != nil || b.wiederholenTitel != nil { menu.append(.trenner) }
        }
        #endif
        let e = treffer(p, in: z)
        if let e { waehle(e) }
        switch e {
        case .mass(let id)?:
            let m = z.mass(id)
            menu.append(.knopf("Maßtext ändern …") { [weak self] in self?.doppelklick(m?.textLage ?? p, z) })
            if let b = z.blatt.mass(id), b.fest || b.quelle != "auto" {
                if b.quelle == "auto" {
                    menu.append(.knopf("Automatisch platzieren") { [weak self] in
                        self?.bearbeite([.massAendern(id: id, text: nil, toleranz: nil, fest: false)])
                    })
                }
            }
            menu.append(.trenner)
            menu.append(.knopf(m?.quelle == "auto" ? "Maß ausblenden" : "Maß löschen", destruktiv: true) { [weak self] in
                self?.loeschen()
            })
        case .notiz?:
            menu.append(.knopf("Notiz löschen", destruktiv: true) { [weak self] in self?.loeschen() })
        case .ansicht(let id)?:
            let art = z.gruppe(id)?.art ?? ""
            if art == "schnitt" {
                menu.append(.knopf("Blickrichtung umkehren") { [weak self] in
                    self?.bearbeite([.schnittUmkehren(id: id)])
                })
                menu.append(.trenner)
            }
            menu.append(.knopf("\(ZeichnungText.ansichtArt(art)) löschen …", destruktiv: true) { [weak self] in
                self?.loeschen()
            })
        case nil:
            if let s = schriftfeldTreffer(p, z) {
                menu.append(.knopf("\(s.titel) ändern …") { [weak self] in self?.doppelklick(p, z) })
                menu.append(.trenner)
            }
            var sub: [MenueEintrag] = ["vorn", "oben", "links", "rechts", "hinten", "unten", "iso"].map { art in
                .knopf(ZeichnungText.ansichtArt(art)) { [weak self] in self?.bearbeite([.ansichtNeu(art: art, lage: p)]) }
            }
            sub.append(.trenner)
            sub.append(.knopf("Schnitt (Linie ziehen)") { [weak self] in self?.zustand?.setzeWerkzeug(.schnitt) })
            sub.append(.knopf("Einzelheit (Kreis aufziehen)") { [weak self] in self?.zustand?.setzeWerkzeug(.einzelheit) })
            menu.append(.unter("Ansicht hier hinzufügen", sub))
            menu.append(.knopf("Notiz hier …") { [weak self] in
                self?.zeigeEingabe(BlattTextEingabe(zweck: .notiz(lage: p, zeiger: nil), titel: "Notiz", text: "", ort: p))
            })
            menu.append(.trenner)
            menu.append(.knopf("Blatt einpassen") { [weak self] in self?.einpassen(animiert: true) })
        }
        menu.append(.trenner)
        #if os(macOS)
        menu.append(.knopf("Als PDF sichern …") { [weak self] in self?.zustand?.pdfSichern?() })
        #else
        menu.append(.knopf("Als PDF teilen …") { [weak self] in self?.zustand?.pdfSichern?() })
        #endif
        menu.append(.knopf("Drucken …") { [weak self] in self?.zustand?.drucken?() })
        needsDisplay = true
        return menu
    }

    #if os(macOS)  // iPad: UIContextMenuInteraction am Ende der Datei
    override func menu(for event: NSEvent) -> NSMenu? {
        let p = mm(convert(event.locationInWindow, from: nil))
        let eintraege = menueEintraege(at: p)
        guard !eintraege.isEmpty else { return nil }
        func bauen(_ liste: [MenueEintrag]) -> NSMenu {
            let menu = NSMenu()
            for e in liste {
                switch e {
                case .knopf(let titel, _, let block): menu.addItem(BlattMenuePunkt(titel, block))
                case .trenner: menu.addItem(.separator())
                case .unter(let titel, let unter):
                    let punkt = NSMenuItem(title: titel, action: nil, keyEquivalent: "")
                    punkt.submenu = bauen(unter)
                    menu.addItem(punkt)
                }
            }
            return menu
        }
        return bauen(eintraege)
    }
    #endif

    // MARK: Texteingabe in einer Sprechblase

    #if os(macOS)
    var eingabeOffen: Bool { popover?.isShown ?? false }

    func schliesseEingabe() { popover?.close() }

    func zeigeEingabe(_ e: BlattTextEingabe) {
        popover?.close()
        let pop = NSPopover()
        pop.behavior = .transient
        let ansicht = BlattTextEingabeAnsicht(eingabe: e) { [weak self, weak pop] ergebnis in
            pop?.close()
            guard let self, let ergebnis else { return }
            self.uebernehme(e, ergebnis)
        }
        pop.contentViewController = NSHostingController(rootView: ansicht)
        let v = punkt(e.ort)
        pop.show(relativeTo: CGRect(x: v.x - 2, y: v.y - 2, width: 4, height: 4), of: self, preferredEdge: .maxY)
        popover = pop
    }
    #else
    var eingabeOffen: Bool { eingabe?.presentingViewController != nil }

    func schliesseEingabe() {
        guard let e = eingabe, e.presentingViewController != nil else { return }
        e.dismiss(animated: true)
    }

    /// iPad: dieselbe Eingabe als Popover an der Stelle auf dem Blatt (auf kleinen Breiten als Blatt von unten).
    func zeigeEingabe(_ e: BlattTextEingabe) {
        schliesseEingabe()
        guard let vc = naechsterController() else { return }
        var host: UIHostingController<BlattTextEingabeAnsicht>?
        let ansicht = BlattTextEingabeAnsicht(eingabe: e) { [weak self] ergebnis in
            host?.dismiss(animated: true)
            guard let self, let ergebnis else { return }
            self.uebernehme(e, ergebnis)
        }
        let h = UIHostingController(rootView: ansicht)
        host = h
        h.modalPresentationStyle = .popover
        h.preferredContentSize = h.sizeThatFits(in: CGSize(width: 420, height: 400))
        let v = unten(punkt(e.ort))
        h.popoverPresentationController?.sourceView = self
        h.popoverPresentationController?.sourceRect = CGRect(x: v.x - 2, y: v.y - 2, width: 4, height: 4)
        vc.present(h, animated: true)
        eingabe = h
    }

    private func naechsterController() -> UIViewController? {
        var r: UIResponder? = self
        while let n = r?.next {
            if let vc = n as? UIViewController {
                var oben = vc
                while let p = oben.presentedViewController { oben = p }
                return oben
            }
            r = n
        }
        return nil
    }
    #endif

    private func uebernehme(_ e: BlattTextEingabe, _ r: (text: String, toleranz: String)) {
        switch e.zweck {
        case .notiz(let lage, let zeiger):
            let t = r.text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !t.isEmpty else { return }
            bearbeite([.notiz(text: t, lage: lage, zeiger: zeiger)])
            zustand?.setzeWerkzeug(.auswahl)
        case .massText(let id):
            let alt = zeichnung?.blatt.mass(id)
            guard r.text != (alt?.text ?? "") || r.toleranz != (alt?.toleranz ?? "") else { return }
            bearbeite([.massAendern(id: id, text: r.text, toleranz: r.toleranz, fest: nil)], titel: "Maßtext ändern")
        case .schriftfeld(let feld):
            guard r.text != zeichnung?.blatt.schriftfeldText(feld) else { return }
            bearbeite([.schriftfeld(feld: feld, wert: Self.schriftfeldWert(feld, r.text))])
        }
    }

    /// Zahlenfelder als Zahl, leere Felder als null.
    static func schriftfeldWert(_ feld: String, _ text: String) -> JSONValue { BlattWerte.schriftfeldWert(feld, text) }

    #if os(iOS)
    // MARK: iPad: Finger, Stift, Schweben, Kneifen, Tastatur

    /// Punkt von UIKit (y unten) in Ansichtspunkte mit y oben wie am Mac; `unten` rechnet zurück.
    func oben(_ p: CGPoint) -> CGPoint { CGPoint(x: p.x, y: bounds.height - p.y) }
    func unten(_ p: CGPoint) -> CGPoint { CGPoint(x: p.x, y: bounds.height - p.y) }

    /// Ein Finger oder der Stift wirken wie die Maus (Tippen wählt, Ziehen verschiebt Maße, Ansichten und Notizen,
    /// auf leerem Papier das Blatt, doppelt tippen ändert Text bzw. passt ein). Zwei Finger kneifen und verschieben,
    /// das Trackpad scrollt, der schwebende Stift hebt wie der Mauszeiger hervor, langes Drücken öffnet das Menü.
    private func gestenEinrichten() {
        let kneifen = UIPinchGestureRecognizer(target: self, action: #selector(gekniffen(_:)))
        kneifen.delegate = self
        addGestureRecognizer(kneifen)
        let zwei = UIPanGestureRecognizer(target: self, action: #selector(zweiFinger(_:)))
        zwei.minimumNumberOfTouches = 2
        zwei.maximumNumberOfTouches = 2
        zwei.allowedScrollTypesMask = .all
        zwei.delegate = self
        addGestureRecognizer(zwei)
        addGestureRecognizer(UIHoverGestureRecognizer(target: self, action: #selector(geschwebt(_:))))
        addInteraction(UIContextMenuInteraction(delegate: self))
    }

    @objc private func gekniffen(_ g: UIPinchGestureRecognizer) {
        guard g.state == .began || g.state == .changed else { return }
        interagiere()
        zoom(faktor: g.scale, um: oben(g.location(in: self)))
        g.scale = 1
    }

    @objc private func zweiFinger(_ g: UIPanGestureRecognizer) {
        guard g.state == .began || g.state == .changed else { return }
        let d = g.translation(in: self)
        g.setTranslation(.zero, in: self)
        interagiere()
        eingepasst = false
        ursprung.x += d.x
        ursprung.y -= d.y
        ansichtGeaendert()
    }

    @objc private func geschwebt(_ g: UIHoverGestureRecognizer) {
        switch g.state {
        case .began, .changed: zeigerBewegt(oben(g.location(in: self)))
        default: zeigerWeg()
        }
    }

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        Self.tasten = event?.modifierFlags ?? []
        if !isFirstResponder { becomeFirstResponder() }
        guard let t = touches.first, (event?.allTouches?.count ?? 1) == 1 else {
            gesteAbbrechen()  // zweiter Finger: Kneifen und Verschieben übernehmen
            return
        }
        druecke(oben(t.location(in: self)), klicks: t.tapCount, schwenken: false)
    }

    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
        Self.tasten = event?.modifierFlags ?? []
        guard let t = touches.first, (event?.allTouches?.count ?? 1) == 1 else { return }
        ziehe(oben(t.location(in: self)), nurAchse: Self.tasteUmschalt)
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard let t = touches.first else { return }
        lasse(oben(t.location(in: self)))
    }

    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) {
        gesteAbbrechen()
    }

    override var canBecomeFirstResponder: Bool { true }

    /// Hardware-Tastatur: dieselben Tasten wie am Mac (⌫, Esc, Pfeile, + und −).
    override func pressesBegan(_ presses: Set<UIPress>, with event: UIPressesEvent?) {
        var rest = Set<UIPress>()
        for p in presses {
            guard let k = p.key else {
                rest.insert(p)
                continue
            }
            let t: Taste?
            switch k.keyCode {
            case .keyboardDeleteOrBackspace, .keyboardDeleteForward: t = .loeschen
            case .keyboardEscape: t = .esc
            case .keyboardLeftArrow: t = .links
            case .keyboardRightArrow: t = .rechts
            case .keyboardDownArrow: t = .runter
            case .keyboardUpArrow: t = .hoch
            default:
                switch k.charactersIgnoringModifiers {
                case "+", "=": t = .plus
                case "-": t = .minus
                default: t = nil
                }
            }
            if let t, k.modifierFlags.isDisjoint(with: [.command, .control]), taste(t, umschalt: k.modifierFlags.contains(.shift)) {
                continue
            }
            rest.insert(p)
        }
        if !rest.isEmpty { super.pressesBegan(rest, with: event) }
    }

    /// ⌘Z und ⇧⌘Z nehmen Änderungen am Blatt zurück (am Mac über das Menü Bearbeiten).
    override var keyCommands: [UIKeyCommand]? {
        let zurueck = UIKeyCommand(title: "Rückgängig", action: #selector(blattRueckgaengig), input: "z", modifierFlags: .command)
        let wieder = UIKeyCommand(title: "Wiederholen", action: #selector(blattWiederholen), input: "z",
                                  modifierFlags: [.command, .shift])
        zurueck.wantsPriorityOverSystemBehavior = true
        wieder.wantsPriorityOverSystemBehavior = true
        return [zurueck, wieder]
    }

    @objc private func blattRueckgaengig() { zustand?.bearbeiter.rueckgaengig() }
    @objc private func blattWiederholen() { zustand?.bearbeiter.wiederholen() }

    /// Einträge des Kontextmenüs als UIMenu; Trenner werden zu Gruppen.
    static func uiMenue(_ liste: [MenueEintrag], titel: String = "") -> UIMenu {
        var kinder: [UIMenuElement] = []
        var gruppe: [UIMenuElement] = []
        for e in liste {
            switch e {
            case .knopf(let t, let destruktiv, let block):
                gruppe.append(UIAction(title: t, attributes: destruktiv ? .destructive : []) { _ in block() })
            case .trenner:
                if !gruppe.isEmpty { kinder.append(UIMenu(options: .displayInline, children: gruppe)) }
                gruppe = []
            case .unter(let t, let unter):
                gruppe.append(uiMenue(unter, titel: t))
            }
        }
        if !gruppe.isEmpty { kinder.append(UIMenu(options: .displayInline, children: gruppe)) }
        return UIMenu(title: titel, children: kinder)
    }

    /// Kleiner Ring an der Stelle statt des ganzen Blatts als Vorschau des Menüs.
    fileprivate func menueVorschau(_ i: UIContextMenuInteraction) -> UITargetedPreview {
        let d: CGFloat = 30
        let ring = UIView(frame: CGRect(x: 0, y: 0, width: d, height: d))
        ring.backgroundColor = UIColor(white: 1, alpha: 0.12)
        ring.layer.cornerRadius = d / 2
        ring.layer.borderWidth = 2
        ring.layer.borderColor = Self.auswahlFarbe.cgColor
        let p = UIPreviewParameters()
        p.backgroundColor = .clear
        p.visiblePath = UIBezierPath(ovalIn: ring.bounds)
        return UITargetedPreview(view: ring, parameters: p, target: UIPreviewTarget(container: self, center: i.location(in: self)))
    }
    #endif
}

#if os(macOS)  // nur am Mac: NSMenu (iPad: `uiMenue`)
/// Menüpunkt mit Block.
final class BlattMenuePunkt: NSMenuItem {
    private let block: () -> Void

    init(_ titel: String, _ block: @escaping () -> Void) {
        self.block = block
        super.init(title: titel, action: #selector(ausloesen), keyEquivalent: "")
        target = self
    }

    required init(coder: NSCoder) { fatalError("init(coder:) nicht benutzt") }

    @objc private func ausloesen() { block() }
}
#endif

/// Werte, die Leinwand und Inspektor dem Kernel schicken (gemeinsam für Mac und iPad).
enum BlattWerte {
    /// Zeiger einer Notiz als Klick auf das Blatt (Ansicht und Punkt), nil ohne Zeiger.
    static func zeiger(_ n: BlattNotiz) -> ZeichnungsKlick? {
        guard let z = n.zeiger, let p = z["punkt"]?.doubles, p.count >= 2 else { return nil }
        return ZeichnungsKlick(ansicht: z["ansicht"]?.stringValue, punkt: CGPoint(x: p[0], y: p[1]))
    }

    /// Wert eines Schriftfelds: Zahlen als Zahl (Masse, Stückzahl, Blattnummern), leer als null, sonst Text.
    static func schriftfeldWert(_ feld: String, _ text: String) -> JSONValue {
        let t = text.trimmingCharacters(in: .whitespaces)
        if t.isEmpty { return .null }
        if ["masse_g", "stueckzahl", "blatt_nr", "blatt_anzahl"].contains(feld),
           let d = Double(t.replacingOccurrences(of: ",", with: "."))
        {
            return .number(d)
        }
        return .string(t)
    }
}

/// Eingabe in der Sprechblase: ein Textfeld (Notiz, Schriftfeld) bzw. Maßtext mit Toleranz.
struct BlattTextEingabeAnsicht: View {
    let eingabe: BlattTextEingabe
    let fertig: ((text: String, toleranz: String)?) -> Void
    @State private var text = ""
    @State private var toleranz = ""
    @FocusState private var fokus: Bool

    init(eingabe: BlattTextEingabe, fertig: @escaping ((text: String, toleranz: String)?) -> Void) {
        self.eingabe = eingabe
        self.fertig = fertig
        _text = State(initialValue: eingabe.text)
        _toleranz = State(initialValue: eingabe.toleranz)
    }

    private var istMass: Bool {
        if case .massText = eingabe.zweck { return true }
        return false
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(eingabe.titel).font(.headline)
            if istMass {
                TextField("Messwert", text: $text, prompt: Text("<> (Messwert)"))
                    .focused($fokus)
                Text("<> steht für den Messwert, z. B. „<> H7“ oder „(<>)“ als Hilfsmaß. Leer: nur der Messwert.")
                    .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                TextField("Toleranz", text: $toleranz, prompt: Text("z. B. ±0,1"))
            } else {
                TextField(eingabe.titel, text: $text, prompt: Text(eingabe.titel), axis: .vertical)
                    .lineLimit(1...4)
                    .focused($fokus)
            }
            HStack {
                Spacer()
                Button("Abbrechen", role: .cancel) { fertig(nil) }
                    .keyboardShortcut(.cancelAction)
                Button(istMass || !eingabe.text.isEmpty ? "Übernehmen" : "Hinzufügen") { fertig((text, toleranz)) }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .textFieldStyle(.roundedBorder)
        .padding(16)
        .frame(width: 320)
        .onAppear { fokus = true }
    }
}

/// Vorschau beim Ziehen und Anlegen von Maßen: rechnet die Darstellung eines Maßes an seiner neuen Stelle, so wie der
/// Kernel sie danach liefert (Maßlinie samt Pfeilen und Zahl verschoben, Hilfslinien verlängert).
enum MassVorschau {
    /// Richtung, in der `versatz` zählt (Vertrag: x → +y, y → +x, frei → links von p1→p2).
    static func normale(_ m: MassDarstellung, blatt b: BlattMassEintrag?) -> CGVector {
        switch b?.richtung {
        case "x": return CGVector(dx: 0, dy: 1)
        case "y": return CGVector(dx: 1, dy: 0)
        default:
            if let a = b?.anker, a.count >= 2 {
                let u = CGVector(dx: a[1].x - a[0].x, dy: a[1].y - a[0].y)
                let l = max(hypot(u.dx, u.dy), 1e-9)
                return CGVector(dx: -u.dy / l, dy: u.dx / l)
            }
            // aus der längsten Linie (Maßlinie)
            if let pl = m.linien.max(by: { laenge($0) < laenge($1) }), let p = pl.first, let q = pl.last {
                let l = max(hypot(q.x - p.x, q.y - p.y), 1e-9)
                return CGVector(dx: -(q.y - p.y) / l, dy: (q.x - p.x) / l)
            }
            return CGVector(dx: 0, dy: 1)
        }
    }

    static func laenge(_ pl: [CGPoint]) -> CGFloat {
        zip(pl, pl.dropFirst()).reduce(0) { $0 + hypot($1.1.x - $1.0.x, $1.1.y - $1.0.y) }
    }

    /// Neuer Versatz nach dem Ziehen um `d` (nil, wenn das Maß keinen Versatz hat, etwa ein Hinweis).
    static func neuerVersatz(_ m: MassDarstellung, blatt b: BlattMassEintrag?, um d: CGVector) -> Double? {
        guard !m.istHinweis, let alt = b?.versatz else { return nil }
        let n = normale(m, blatt: b)
        return alt + Double(d.dx * n.dx + d.dy * n.dy)
    }

    static func verschoben(_ m: MassDarstellung, blatt b: BlattMassEintrag?, um d: CGVector, text: Bool) -> MassDarstellung {
        var out = m
        if text || m.istHinweis {
            if m.istHinweis {
                // Hinweislinie: Spitze bleibt, Knick und Bezugslinie wandern mit der Zahl
                out.linien = m.linien.map { pl in pl.enumerated().map { i, p in i == 0 ? p : p + d } }
                out.textLage = m.textLage + d
                out.texte = m.texte.map { var t = $0; t.lage = t.lage + d; return t }
            } else {
                // Zahl nur entlang der Maßlinie
                let n = normale(m, blatt: b)
                let u = CGVector(dx: n.dy, dy: -n.dx)
                let s = d.dx * u.dx + d.dy * u.dy
                out.textLage = m.textLage + CGVector(dx: u.dx * s, dy: u.dy * s)
            }
            return out
        }
        let n = normale(m, blatt: b)
        let s = d.dx * n.dx + d.dy * n.dy
        let v = CGVector(dx: n.dx * s, dy: n.dy * s)
        // Maßlinie: die längste Linie quer zur Normalen; Hilfslinien liegen längs der Normalen
        let quer = m.linien.filter { !laengsNormale($0, n) }
        let lage = quer.first.flatMap { $0.first }.map { $0.x * n.dx + $0.y * n.dy }
        out.linien = m.linien.map { pl in
            guard laengsNormale(pl, n), pl.count == 2, let lage else { return pl.map { $0 + v } }
            // Hilfslinie: das Ende an der Maßlinie wandert mit, der Ansatz am Körper bleibt
            let a = abs(pl[0].x * n.dx + pl[0].y * n.dy - lage)
            let b = abs(pl[1].x * n.dx + pl[1].y * n.dy - lage)
            return a < b ? [pl[0] + v, pl[1]] : [pl[0], pl[1] + v]
        }
        out.pfeile = m.pfeile.map { var p = $0; p.spitze = p.spitze + v; p.polygon = p.polygon.map { $0 + v }; return p }
        out.textLage = m.textLage + v
        out.texte = m.texte.map { var t = $0; t.lage = t.lage + v; return t }
        if let box = m.box { out.box = box.offsetBy(dx: v.dx, dy: v.dy) }
        return out
    }

    static func laengsNormale(_ pl: [CGPoint], _ n: CGVector) -> Bool {
        guard let p = pl.first, let q = pl.last else { return false }
        let l = hypot(q.x - p.x, q.y - p.y)
        guard l > 1e-6 else { return false }
        return abs(((q.x - p.x) * n.dx + (q.y - p.y) * n.dy) / l) > 0.9
    }

    struct Neu {
        var richtung: String
        var versatz: Double
        var darstellung: MassDarstellung
    }

    /// Vorschau eines neuen linearen Maßes zwischen zwei angeklickten Elementen, Maßlinie am Mauszeiger. Ansatzpunkte
    /// wie im Kernel am äußeren Ende des Elements auf der Seite der Maßlinie (Kreise: Mittelpunkt).
    static func neu(a: (CGPoint, [CGPoint]?), b: (CGPoint, [CGPoint]?), maus m: CGPoint, frei: Bool, massstab: String)
        -> Neu?
    {
        let p1 = a.0
        let p2 = b.0
        let lo = CGPoint(x: min(p1.x, p2.x), y: min(p1.y, p2.y))
        let hi = CGPoint(x: max(p1.x, p2.x), y: max(p1.y, p2.y))
        let ausX = m.x < lo.x ? lo.x - m.x : (m.x > hi.x ? m.x - hi.x : 0)
        let ausY = m.y < lo.y ? lo.y - m.y : (m.y > hi.y ? m.y - hi.y : 0)
        let richtung: String
        if frei {
            richtung = "frei"
        } else if ausX == 0 && ausY == 0 {
            richtung = (hi.x - lo.x) >= (hi.y - lo.y) ? "x" : "y"
        } else {
            richtung = ausY >= ausX ? "x" : "y"
        }
        func anker(_ e: (CGPoint, [CGPoint]?)) -> CGPoint {
            guard let pl = e.1, pl.count >= 2 else { return e.0 }
            if let mitte = kreisMitte(pl) { return mitte }  // Bohrung, Kreis: Ansatz in der Mitte
            switch richtung {
            case "x":
                let y = m.y >= e.0.y ? pl.map(\.y).max()! : pl.map(\.y).min()!
                return CGPoint(x: e.0.x, y: y)
            case "y":
                let x = m.x >= e.0.x ? pl.map(\.x).max()! : pl.map(\.x).min()!
                return CGPoint(x: x, y: e.0.y)
            default:
                return e.0
            }
        }
        let q1 = anker(a)
        let q2 = anker(b)
        let faktor = Self.faktor(massstab)
        var linien: [[CGPoint]] = []
        var pfeile: [MassPfeil] = []
        let wert: CGFloat
        let versatz: CGFloat
        let lageText: CGPoint
        var winkel: Double = 0
        switch richtung {
        case "x":
            let y = m.y
            versatz = y - q1.y
            linien = [[q1, CGPoint(x: q1.x, y: y + (y >= q1.y ? 2 : -2))],
                      [q2, CGPoint(x: q2.x, y: y + (y >= q2.y ? 2 : -2))],
                      [CGPoint(x: q1.x, y: y), CGPoint(x: q2.x, y: y)]]
            let l = q1.x < q2.x ? 1.0 : -1.0
            pfeile = [pfeil(CGPoint(x: q1.x, y: y), CGVector(dx: -l, dy: 0)), pfeil(CGPoint(x: q2.x, y: y), CGVector(dx: l, dy: 0))]
            wert = abs(q2.x - q1.x)
            lageText = CGPoint(x: (q1.x + q2.x) / 2, y: y + 0.9)
        case "y":
            let x = m.x
            versatz = x - q1.x
            linien = [[q1, CGPoint(x: x + (x >= q1.x ? 2 : -2), y: q1.y)],
                      [q2, CGPoint(x: x + (x >= q2.x ? 2 : -2), y: q2.y)],
                      [CGPoint(x: x, y: q1.y), CGPoint(x: x, y: q2.y)]]
            let l = q1.y < q2.y ? 1.0 : -1.0
            pfeile = [pfeil(CGPoint(x: x, y: q1.y), CGVector(dx: 0, dy: -l)), pfeil(CGPoint(x: x, y: q2.y), CGVector(dx: 0, dy: l))]
            wert = abs(q2.y - q1.y)
            lageText = CGPoint(x: x - 0.9, y: (q1.y + q2.y) / 2)
            winkel = 90
        default:
            let u0 = CGVector(dx: q2.x - q1.x, dy: q2.y - q1.y)
            let l = max(hypot(u0.dx, u0.dy), 1e-9)
            let u = CGVector(dx: u0.dx / l, dy: u0.dy / l)
            let n = CGVector(dx: -u.dy, dy: u.dx)
            versatz = (m.x - q1.x) * n.dx + (m.y - q1.y) * n.dy
            let v = CGVector(dx: n.dx * versatz, dy: n.dy * versatz)
            linien = [[q1, q1 + v], [q2, q2 + v], [q1 + v, q2 + v]]
            pfeile = [pfeil(q1 + v, CGVector(dx: -u.dx, dy: -u.dy)), pfeil(q2 + v, u)]
            wert = l
            lageText = CGPoint(x: (q1.x + q2.x) / 2 + v.dx + n.dx * 0.9, y: (q1.y + q2.y) / 2 + v.dy + n.dy * 0.9)
            winkel = Double(atan2(u.dy, u.dx) * 180 / .pi)
            if winkel > 90 || winkel <= -90 { winkel += winkel > 0 ? -180 : 180 }
        }
        guard wert > 0.05 else { return nil }
        let text = "≈ " + zahl(Double(wert / faktor))
        let d = MassDarstellung(id: "neu", linien: linien, pfeile: pfeile, text: text, textLage: lageText,
                                textWinkel: winkel, art: "linear", quelle: "kevin")
        return Neu(richtung: richtung, versatz: Double(versatz), darstellung: d)
    }

    /// Mittelpunkt, wenn die Polylinie ein Kreis ist (geschlossen, alle Punkte gleich weit von der Mitte).
    static func kreisMitte(_ pl: [CGPoint]) -> CGPoint? {
        guard pl.count >= 8, let a = pl.first, let b = pl.last, hypot(a.x - b.x, a.y - b.y) < 0.05 else { return nil }
        let r = CGRect.huelle(pl)
        let m = CGPoint(x: r.midX, y: r.midY)
        let radien = pl.map { hypot($0.x - m.x, $0.y - m.y) }
        guard let rmin = radien.min(), let rmax = radien.max(), rmax > 0.05, (rmax - rmin) / rmax < 0.04 else { return nil }
        return m
    }

    /// Glattes Stück einer Polylinie um den Punkt `p`: von der nächsten Strecke aus bis zu den Ecken (Knick über 30°).
    /// So wird aus einem Kantenzug des Kernels die eine Kante (oder der ganze Kreis, der ganze Bogen).
    static func kantenzug(_ pl: [CGPoint], nahe p: CGPoint) -> [CGPoint] {
        guard pl.count > 2 else { return pl }
        var naechste = 0
        var abstand = CGFloat.greatestFiniteMagnitude
        for i in 0..<(pl.count - 1) {
            let d = Geometrie2D.abstand(p, a: pl[i], b: pl[i + 1])
            if d < abstand {
                abstand = d
                naechste = i
            }
        }
        func richtung(_ i: Int) -> CGFloat? {
            let dx = pl[i + 1].x - pl[i].x
            let dy = pl[i + 1].y - pl[i].y
            return hypot(dx, dy) < 1e-6 ? nil : atan2(dy, dx)
        }
        func glatt(_ i: Int, _ j: Int) -> Bool {
            guard let a = richtung(i), let b = richtung(j) else { return true }
            var d = abs(a - b).truncatingRemainder(dividingBy: 2 * .pi)
            if d > .pi { d = 2 * .pi - d }
            return d < 30 * .pi / 180
        }
        var lo = naechste
        var hi = naechste
        while lo > 0, glatt(lo - 1, lo) { lo -= 1 }
        while hi < pl.count - 2, glatt(hi, hi + 1) { hi += 1 }
        return Array(pl[lo...(hi + 1)])
    }

    /// Zahl wie auf der Zeichnung: höchstens zwei Nachkommastellen, ohne Nullen am Ende, Komma.
    static func zahl(_ v: Double) -> String {
        var s = KevFormat.number(v, digits: 2)
        while s.hasSuffix("0"), s.contains(",") { s.removeLast() }
        if s.hasSuffix(",") { s.removeLast() }
        return s
    }

    static func pfeil(_ spitze: CGPoint, _ r: CGVector) -> MassPfeil {
        MassPfeil(spitze: spitze, richtung: r, art: "voll", laenge: 2.5, breite: 0.66)
    }

    /// „1:2“ → 0,5; „2:1“ → 2.
    static func faktor(_ massstab: String) -> CGFloat {
        let t = massstab.split(separator: ":").compactMap { Double($0.replacingOccurrences(of: ",", with: ".")) }
        guard t.count == 2, t[1] > 0 else { return 1 }
        return CGFloat(t[0] / t[1])
    }
}

private func + (p: CGPoint, v: CGVector) -> CGPoint { CGPoint(x: p.x + v.dx, y: p.y + v.dy) }

#if os(iOS)
extension BlattLeinwand {
    /// Wie `NSView.needsDisplay`, damit der gemeinsame Code auf beiden Geräten gleich neu zeichnen lässt.
    var needsDisplay: Bool {
        get { false }
        set { if newValue { setNeedsDisplay() } }
    }
}

extension BlattLeinwand: UIGestureRecognizerDelegate, UIContextMenuInteractionDelegate {
    func gestureRecognizer(_ g: UIGestureRecognizer, shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer) -> Bool {
        true  // Kneifen und Verschieben zugleich
    }

    func contextMenuInteraction(_ i: UIContextMenuInteraction,
                                configurationForMenuAtLocation location: CGPoint) -> UIContextMenuConfiguration? {
        gesteAbbrechen()
        let eintraege = menueEintraege(at: mm(oben(location)))
        guard !eintraege.isEmpty else { return nil }
        return UIContextMenuConfiguration(identifier: nil, previewProvider: nil) { _ in Self.uiMenue(eintraege) }
    }

    func contextMenuInteraction(_ i: UIContextMenuInteraction, configuration: UIContextMenuConfiguration,
                                highlightPreviewForItemWithIdentifier identifier: any NSCopying) -> UITargetedPreview? {
        menueVorschau(i)
    }

    func contextMenuInteraction(_ i: UIContextMenuInteraction, configuration: UIContextMenuConfiguration,
                                dismissalPreviewForItemWithIdentifier identifier: any NSCopying) -> UITargetedPreview? {
        menueVorschau(i)
    }
}
#endif
