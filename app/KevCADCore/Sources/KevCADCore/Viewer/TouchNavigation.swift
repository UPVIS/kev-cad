#if os(iOS)
import OCCTSwiftViewport
import QuartzCore
import SwiftUI
import UIKit
import simd

// I-3b (PLAN-IPAD.md, Abschnitt 4): Eingabeebene des iPad über dem MTKView. Gleiche Wirkung und gleiche Rückrufe des
// Koordinators wie die Maus am Mac (BlenderNavigation.swift), damit Auswahl, Messen, Zeigen und Zeichnen beim Sprechen
// auf beiden Geräten derselbe Code sind. Punkte gehen wie am Mac mit Ursprung unten links an den Koordinator.
//
// - Finger: einer dreht um den Punkt unter dem Finger, zwei verschieben, Spreizen zoomt zur Mitte der Finger. Tippen
//   wählt aus, Doppeltippen rahmt das Teil ein (auf leerem Grund alles), langes Drücken öffnet das Kreismenü der
//   Ansichten an dieser Stelle.
// - Stift: Schweben zeigt wie die Maus (Hervorhebung, Maß-Vorschau, beim Sprechen „das hier“), Tippen wählt aus,
//   Ziehen zeichnet beim Sprechen, sonst dreht es. Werkzeugkranz, Strichfarben und Start des Sprechens per Strich: I-4.
// - Trackpad und Maus: Zeiger zeigt wie die Maus, zwei Finger drehen (⇧ verschieben, ⌃ oder ⌘ zoomen), Zoomgeste zoomt.
// - Magic Keyboard: Kürzel des Viewers aus Tastenbelegung.swift (HID-Codes werden den Tastencodes des Mac zugeordnet).
//
// Noch offen: 2 Finger tippen (Rückgängig), 3 Finger tippen (Wiederholen), Kontextmenü am Teil, Werkzeugkranz (I-4).

/// Eingabeebene über dem MTKView (Name wie am Mac, damit Koordinator und Viewport auf beiden Seiten gleich bleiben).
final class NavigationInputView: UIView, UIGestureRecognizerDelegate {
    weak var coordinator: ViewportCoordinator? {
        didSet { aktivGeaendert() }
    }

    private enum Modus: Equatable { case ruht, drehen, verschieben, zoomen, griff, strich }
    private var modus = Modus.ruht {
        didSet { meldeNavigation() }
    }

    private var letzteVerschiebung = CGPoint.zero
    private var letzteSkala: CGFloat = 1
    private var drehToken = 0
    /// Letzter Zeigerpunkt (Stift schwebt, Trackpad), Ursprung unten links; nil = kein Zeiger über dem Viewer.
    private var zeiger: CGPoint? {
        didSet { coordinator?.letzteMaus = zeiger }
    }
    private var hoverLaeuft = false
    private var hoverNochmal = false

    // Strich beim Sprechen (wie am Mac: die Linie folgt sofort, Treffer immer nur einer zugleich)
    private let strichLayer = CAShapeLayer()
    private var strichPfad: CGMutablePath?
    private var strichPickLaeuft = false
    private var strichNaechster: (punkt: CGPoint, zeit: Double)?
    private var strichEndeOffen = false

    private lazy var einFinger = UIPanGestureRecognizer(target: self, action: #selector(einFingerZiehen(_:)))
    private lazy var zweiFinger = UIPanGestureRecognizer(target: self, action: #selector(zweiFingerZiehen(_:)))
    private lazy var spreizen = UIPinchGestureRecognizer(target: self, action: #selector(spreizenGeste(_:)))
    private lazy var tippen = UITapGestureRecognizer(target: self, action: #selector(tippenGeste(_:)))
    private lazy var doppeltTippen = UITapGestureRecognizer(target: self, action: #selector(doppeltTippenGeste(_:)))
    private lazy var langDruecken = UILongPressGestureRecognizer(target: self, action: #selector(langDrueckenGeste(_:)))
    private lazy var stift = UIPanGestureRecognizer(target: self, action: #selector(stiftZiehen(_:)))
    private lazy var schweben = UIHoverGestureRecognizer(target: self, action: #selector(schwebenGeste(_:)))
    private lazy var rollen = UIPanGestureRecognizer(target: self, action: #selector(rollenGeste(_:)))

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .clear
        isMultipleTouchEnabled = true

        let finger = [NSNumber(value: UITouch.TouchType.direct.rawValue)]
        let stiftArt = [NSNumber(value: UITouch.TouchType.pencil.rawValue)]
        einFinger.minimumNumberOfTouches = 1
        einFinger.maximumNumberOfTouches = 1
        einFinger.allowedTouchTypes = finger
        zweiFinger.minimumNumberOfTouches = 2
        zweiFinger.maximumNumberOfTouches = 2
        zweiFinger.allowedTouchTypes = finger
        stift.allowedTouchTypes = stiftArt
        stift.maximumNumberOfTouches = 1
        tippen.allowedTouchTypes = finger + stiftArt
        doppeltTippen.numberOfTapsRequired = 2
        doppeltTippen.allowedTouchTypes = finger
        langDruecken.minimumPressDuration = 0.45
        langDruecken.allowedTouchTypes = finger
        // Trackpad und Maus: nur das Rollen mit zwei Fingern, keine Berührungen
        rollen.allowedScrollTypesMask = .continuous
        rollen.maximumNumberOfTouches = 0

        for g in [einFinger, zweiFinger, spreizen, tippen, doppeltTippen, langDruecken, stift, rollen] as [UIGestureRecognizer] {
            g.delegate = self
            addGestureRecognizer(g)
        }
        addGestureRecognizer(schweben)

        strichLayer.fillColor = nil
        strichLayer.strokeColor = CGColor(srgbRed: CGFloat(ViewerStil.strich.x), green: CGFloat(ViewerStil.strich.y),
                                          blue: CGFloat(ViewerStil.strich.z), alpha: 1)
        strichLayer.lineWidth = 3
        strichLayer.lineCap = .round
        strichLayer.lineJoin = .round
        strichLayer.isHidden = true
        layer.addSublayer(strichLayer)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) wird nicht benutzt") }

    override func layoutSubviews() {
        super.layoutSubviews()
        coordinator?.viewSize = bounds.size
        strichLayer.frame = bounds
    }

    /// V2-10: Der zweite Viewer bleibt eingehängt, wenn seine Kachel verborgen ist; dann nimmt er nichts an.
    override func hitTest(_ point: CGPoint, with event: UIEvent?) -> UIView? {
        coordinator?.eingabeAktiv == false ? nil : super.hitTest(point, with: event)
    }

    func aktivGeaendert() {
        isUserInteractionEnabled = coordinator?.eingabeAktiv != false
    }

    // MARK: Gesten gemeinsam

    func gestureRecognizer(_ g: UIGestureRecognizer, shouldRecognizeSimultaneouslyWith o: UIGestureRecognizer) -> Bool {
        // Verschieben und Zoomen mit zwei Fingern zugleich; Tippen und Doppeltippen nebeneinander (Doppeltippen wählt
        // mit dem ersten Tipp schon aus)
        let paar: Set<ObjectIdentifier> = [ObjectIdentifier(g), ObjectIdentifier(o)]
        return paar == [ObjectIdentifier(zweiFinger), ObjectIdentifier(spreizen)]
            || paar == [ObjectIdentifier(tippen), ObjectIdentifier(doppeltTippen)]
    }

    /// UIKit zählt von oben, Koordinator und Mac von unten links.
    private func eingabePunkt(_ p: CGPoint) -> CGPoint { CGPoint(x: p.x, y: bounds.height - p.y) }

    private func meldeNavigation() {
        let n: ViewerEingabe.Navigation?
        switch modus {
        case .drehen: n = .drehen
        case .verschieben: n = .verschieben
        case .zoomen: n = .zoomen
        case .griff: n = .griff
        case .strich: n = .strich
        case .ruht: n = nil
        }
        if coordinator?.eingabe.navigation != n { coordinator?.eingabe.navigation = n }
    }

    private func bedient() {
        if !isFirstResponder { becomeFirstResponder() }  // Tastatur des Magic Keyboard gilt jetzt dem Viewer
        coordinator?.fahrtAbbrechen()
    }

    /// Drehung beginnt: Drehpunkt ist der Punkt unter dem Finger (Treffer; bis zur Antwort um die Bildmitte).
    private func beginneDrehung(bei p: CGPoint) {
        guard let c = coordinator else { return }
        c.drehZentrum = nil
        drehToken += 1
        let token = drehToken
        c.pickPoint(p, in: self) { [weak self] result in
            guard let self, self.drehToken == token, let c = self.coordinator, let result,
                let w = c.surfacePoint(of: result, at: p, in: self)
            else { return }
            c.drehZentrum = w
        }
    }

    private func endeDrehung() {
        drehToken += 1
        coordinator?.drehZentrum = nil
    }

    /// Verschiebung seit dem letzten Aufruf, in Punkten mit y nach oben (wie die Maus am Mac).
    private func schritt(_ g: UIPanGestureRecognizer) -> (dx: Float, dy: Float) {
        let t = g.translation(in: self)
        let d = CGPoint(x: t.x - letzteVerschiebung.x, y: t.y - letzteVerschiebung.y)
        letzteVerschiebung = t
        return (Float(d.x), Float(-d.y))
    }

    // MARK: Finger

    @objc private func einFingerZiehen(_ g: UIPanGestureRecognizer) {
        guard let c = coordinator else { return }
        let p = eingabePunkt(g.location(in: self))
        switch g.state {
        case .began:
            bedient()
            letzteVerschiebung = .zero
            let t = g.translation(in: self)
            let start = eingabePunkt(CGPoint(x: g.location(in: self).x - t.x, y: g.location(in: self).y - t.y))
            if let griff = c.onGriffBeginnt, griff(start) {
                modus = .griff
                return
            }
            modus = .drehen
            beginneDrehung(bei: start)
            letzteVerschiebung = .zero
        case .changed:
            switch modus {
            case .griff:
                c.onGriffZiehen?(p)
            case .drehen:
                let d = schritt(g)
                c.navOrbit(dx: d.dx, dy: d.dy)
            default:
                break
            }
        default:
            if modus == .griff { c.onGriffEnde?(p) }
            modus = .ruht
            endeDrehung()
        }
    }

    @objc private func zweiFingerZiehen(_ g: UIPanGestureRecognizer) {
        guard let c = coordinator else { return }
        switch g.state {
        case .began:
            bedient()
            letzteVerschiebung = g.translation(in: self)
            modus = .verschieben
        case .changed:
            let d = schritt(g)
            c.navPan(dx: d.dx, dy: d.dy)
        default:
            if modus == .verschieben { modus = .ruht }
        }
    }

    @objc private func spreizenGeste(_ g: UIPinchGestureRecognizer) {
        guard let c = coordinator else { return }
        switch g.state {
        case .began:
            bedient()
            letzteSkala = g.scale
        case .changed:
            guard g.scale > 0, letzteSkala > 0 else { return }
            let f = g.scale / letzteSkala
            letzteSkala = g.scale
            // Finger auseinander (f > 1) = näher heran (Faktor < 1), zur Mitte der Finger
            c.navZoom(factor: Float(1 / f), zu: eingabePunkt(g.location(in: self)))
        default:
            break
        }
    }

    @objc private func tippenGeste(_ g: UITapGestureRecognizer) {
        guard g.state == .ended, let c = coordinator else { return }
        bedient()
        let p = eingabePunkt(g.location(in: self))
        let flags = g.modifierFlags  // ⇧ am Magic Keyboard ergänzt die Auswahl wie am Mac
        c.pickPoint(p, in: self) { [weak self] result in
            guard let self, let c = self.coordinator else { return }
            if let punkt = c.onClickPunkt {
                let welt = result.flatMap { c.surfacePoint(of: $0, at: p, in: self) }
                if punkt(result, welt, flags) { return }
            }
            c.onClick?(result, flags)
        }
    }

    @objc private func doppeltTippenGeste(_ g: UITapGestureRecognizer) {
        guard g.state == .ended, let c = coordinator else { return }
        let p = eingabePunkt(g.location(in: self))
        c.pickPoint(p, in: self) { [weak self] result in
            guard let self, let c = self.coordinator else { return }
            // Der erste Tipp hat schon ausgewählt: einrahmen, auf leerem Grund alles
            _ = c.onBefehl?(result == nil ? .allesEinrahmen : .auswahlEinrahmen)
            _ = self
        }
    }

    @objc private func langDrueckenGeste(_ g: UILongPressGestureRecognizer) {
        guard g.state == .began, let c = coordinator else { return }
        bedient()
        zeiger = eingabePunkt(g.location(in: self))  // das Kreismenü öffnet an dieser Stelle
        _ = c.onBefehl?(.ansichtMenue)
        UISelectionFeedbackGenerator().selectionChanged()
    }

    // MARK: Stift

    @objc private func stiftZiehen(_ g: UIPanGestureRecognizer) {
        guard let c = coordinator else { return }
        let p = eingabePunkt(g.location(in: self))
        switch g.state {
        case .began:
            bedient()
            let t = g.translation(in: self)
            let start = eingabePunkt(CGPoint(x: g.location(in: self).x - t.x, y: g.location(in: self).y - t.y))
            letzteVerschiebung = .zero
            if c.zeichnen {
                modus = .strich
                strichBeginnen(start)
                strichZiehen(p)
            } else {
                // I-4: ein Strich ohne Sitzung startet das Sprechen; bis dahin dreht der Stift wie ein Finger
                modus = .drehen
                beginneDrehung(bei: start)
            }
        case .changed:
            if modus == .strich {
                strichZiehen(p)
            } else if modus == .drehen {
                let d = schritt(g)
                c.navOrbit(dx: d.dx, dy: d.dy)
            }
        default:
            if modus == .strich { strichBeenden(p) } else { endeDrehung() }
            modus = .ruht
        }
    }

    // Stift schwebt, Trackpad- oder Mauszeiger: zeigt wie die Maus am Mac
    @objc private func schwebenGeste(_ g: UIHoverGestureRecognizer) {
        guard let c = coordinator else { return }
        switch g.state {
        case .began, .changed:
            zeiger = eingabePunkt(g.location(in: self))
            if !c.eingabe.mausImViewport { c.eingabe.mausImViewport = true }
            hoverTest()
        default:
            zeiger = nil
            c.eingabe.mausImViewport = false
            c.onHover?(nil, nil, nil)
        }
    }

    /// Treffertest unter dem Zeiger (Messen, Drehpunkt, Zoomziel, Zeigen beim Sprechen); höchstens einer zugleich.
    func hoverTest() {
        guard let p = zeiger, let c = coordinator, modus == .ruht else { return }
        if hoverLaeuft {
            hoverNochmal = true
            return
        }
        hoverLaeuft = true
        c.pickPoint(p, in: self) { [weak self] result in
            guard let self, let c = self.coordinator else { return }
            self.hoverLaeuft = false
            let welt = result.flatMap { c.surfacePoint(of: $0, at: p, in: self) }
            if let welt { c.mausPunkt = (welt, p, CACurrentMediaTime()) }
            if self.zeiger != nil {
                c.onHover?(result, welt, CGPoint(x: p.x, y: self.bounds.height - p.y))  // oben links für die Überlagerung
            }
            if self.hoverNochmal {
                self.hoverNochmal = false
                self.hoverTest()
            }
        }
    }

    // MARK: Trackpad und Maus

    @objc private func rollenGeste(_ g: UIPanGestureRecognizer) {
        guard let c = coordinator else { return }
        let flags = g.modifierFlags
        switch g.state {
        case .began:
            bedient()
            letzteVerschiebung = .zero
            if flags.contains(.shift) {
                modus = .verschieben
            } else if flags.contains(.control) || flags.contains(.command) {
                modus = .zoomen
            } else {
                modus = .drehen
                beginneDrehung(bei: eingabePunkt(g.location(in: self)))
            }
        case .changed:
            let d = schritt(g)
            switch modus {
            case .drehen: c.navOrbit(dx: d.dx, dy: d.dy)
            case .verschieben: c.navPan(dx: d.dx, dy: d.dy)
            case .zoomen: c.navZoom(factor: exp(-d.dy * BlenderNav.zoomPerPoint), zu: eingabePunkt(g.location(in: self)))
            default: break
            }
        default:
            if modus == .drehen { endeDrehung() }
            modus = .ruht
        }
    }

    // MARK: Strich beim Sprechen (wie am Mac, V2-6)

    private func strichBeginnen(_ p: CGPoint) {
        let pfad = CGMutablePath()
        pfad.move(to: CGPoint(x: p.x, y: bounds.height - p.y))
        strichPfad = pfad
        strichNaechster = nil
        strichEndeOffen = false
        strichZeigen()
        coordinator?.onStrich?(.beginn)
        strichTreffer(p, ProcessInfo.processInfo.systemUptime)
    }

    private func strichZiehen(_ p: CGPoint) {
        strichPfad?.addLine(to: CGPoint(x: p.x, y: bounds.height - p.y))
        strichZeigen()
        strichTreffer(p, ProcessInfo.processInfo.systemUptime)
    }

    private func strichBeenden(_ p: CGPoint) {
        strichEndeOffen = true
        strichTreffer(p, ProcessInfo.processInfo.systemUptime)
    }

    private func strichZeigen() {
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        strichLayer.frame = bounds
        strichLayer.path = strichPfad
        strichLayer.isHidden = false
        CATransaction.commit()
    }

    private func strichTreffer(_ p: CGPoint, _ zeit: Double) {
        guard let c = coordinator else { return }
        guard !strichPickLaeuft else {
            strichNaechster = (p, zeit)
            return
        }
        strichPickLaeuft = true
        c.pickPoint(p, in: self) { [weak self] result in
            guard let self, let c = self.coordinator else { return }
            self.strichPickLaeuft = false
            let welt = result.flatMap { c.surfacePoint(of: $0, at: p, in: self) }
            c.onStrich?(.punkt(eingabe: p, bild: CGPoint(x: p.x, y: self.bounds.height - p.y), zeit: zeit, treffer: result,
                               welt: welt))
            if let n = self.strichNaechster {
                self.strichNaechster = nil
                self.strichTreffer(n.punkt, n.zeit)
            } else if self.strichEndeOffen {
                self.strichEndeOffen = false
                c.onStrich?(.ende)  // die fertige Linie zeichnet ab jetzt die Überlagerung
                self.strichPfad = nil
                self.strichLayer.isHidden = true
            }
        }
    }

    // MARK: Tastatur (Magic Keyboard)

    override var canBecomeFirstResponder: Bool { true }

    override func pressesBegan(_ presses: Set<UIPress>, with event: UIPressesEvent?) {
        var erledigt = false
        for press in presses {
            guard let key = press.key, let befehl = Self.befehl(key) else { continue }
            if coordinator?.onBefehl?(befehl) == true { erledigt = true }
        }
        if !erledigt { super.pressesBegan(presses, with: event) }
    }

    /// Befehl der Belegung zu einer Taste: Tastencode des Mac aus dem HID-Code (Ziffernblock, Pos1, ^), sonst Zeichen.
    static func befehl(_ key: UIKey) -> ViewerBefehl? {
        Tastenbelegung.befehl(keyCode: macTastencode(key.keyCode) ?? 0xFFFF, zeichen: key.charactersIgnoringModifiers,
                              flags: key.modifierFlags)
    }

    /// HID-Code (UIKit) → Tastencode des Mac für die Tasten, die Tastenbelegung.swift über den Code erkennt.
    static func macTastencode(_ hid: UIKeyboardHIDUsage) -> UInt16? {
        switch hid {
        case .keypad0: return 82
        case .keypad1: return 83
        case .keypad2: return 84
        case .keypad3: return 85
        case .keypad4: return 86
        case .keypad5: return 87
        case .keypad6: return 88
        case .keypad7: return 89
        case .keypad8: return 91
        case .keypad9: return 92
        case .keypadPeriod: return 65
        case .keypadPlus: return 69
        case .keypadHyphen: return 78
        case .keypadSlash: return 75
        case .keypadEnter: return 76
        case .keyboardReturnOrEnter: return 36
        case .keyboardHome: return 115
        case .keyboardGraveAccentAndTilde: return 50  // ANSI: Taste links der 1
        case .keyboardNonUSBackslash: return 10  // ISO (deutsch „^“), wie kVK_ISO_Section
        default: return nil
        }
    }
}

/// SwiftUI-Hülle der Eingabeebene (wie `NavigationInputLayer` am Mac).
struct NavigationInputLayer: UIViewRepresentable {
    let coordinator: ViewportCoordinator

    func makeUIView(context: Context) -> NavigationInputView {
        let v = NavigationInputView()
        v.coordinator = coordinator
        coordinator.eingabeView = v
        return v
    }

    func updateUIView(_ uiView: NavigationInputView, context: Context) {
        uiView.coordinator = coordinator
        coordinator.eingabeView = uiView
    }
}
#endif
