#if os(iOS)
import OCCTSwiftViewport
import QuartzCore
import SwiftUI
import UIKit
import UIKit.UIGestureRecognizerSubclass
import simd

// I-3b (PLAN-IPAD.md, Abschnitt 4): Eingabeebene des iPad über dem MTKView. Gleiche Wirkung und gleiche Rückrufe des
// Koordinators wie die Maus am Mac (BlenderNavigation.swift), damit Auswahl, Messen, Zeigen und Zeichnen beim Sprechen
// auf beiden Geräten derselbe Code sind. Punkte gehen wie am Mac mit Ursprung unten links an den Koordinator.
//
// - Finger: einer dreht um den Punkt unter dem Finger, zwei verschieben, Spreizen zoomt zur Mitte der Finger. Tippen
//   wählt aus, Doppeltippen rahmt das Teil ein (auf leerem Grund alles), langes Drücken öffnet das Kontextmenü am Teil
//   (Kontextmenue.swift, dieselben Einträge wie die rechte Maustaste am Mac). 2 Finger tippen nimmt Ansicht, Auswahl
//   oder Sichtbarkeit zurück, 3 Finger tippen wiederholt (AnsichtsVerlauf.swift). Das Kreismenü der Ansichten bleibt
//   über ^ und später den Werkzeugkranz (I-4) erreichbar. Vom Rand wischen öffnet die Leisten (iPad-Hülle, RandWischen).
// - Stift: Schweben zeigt wie die Maus (Hervorhebung, Maß-Vorschau, beim Sprechen „das hier“), Tippen wählt aus,
//   Ziehen zeichnet beim Sprechen; ohne Sitzung beginnt ein Strich das Sprechen (I-4, abschaltbar, dann dreht er).
//   Doppeltippen am Pencil (Pencil Pro: Drücken) öffnet den Werkzeugkranz an der Spitze (I-4, UIPencilInteraction).
// - Trackpad und Maus: Zeiger zeigt wie die Maus, zwei Finger drehen (⇧ verschieben, ⌃ oder ⌘ zoomen), Zoomgeste zoomt,
//   der Sekundärklick öffnet das Kontextmenü.
// - Magic Keyboard: Kürzel des Viewers aus Tastenbelegung.swift (HID-Codes werden den Tastencodes des Mac zugeordnet),
//   ⌘Z und ⇧⌘Z wie am Mac.
//
// Hinweisleiste und Übersicht beschreiben diese Gesten aus `Tastenbelegung.gesten`: Wer hier eine Geste ändert oder
// dazunimmt, trägt sie dort im selben Schritt nach.
//
// Noch offen: Rollen am Pencil Pro für den Drehregler des Werkzeugkranzes (I-4).

/// Eingabeebene über dem MTKView (Name wie am Mac, damit Koordinator und Viewport auf beiden Seiten gleich bleiben).
final class NavigationInputView: UIView, UIGestureRecognizerDelegate, UIContextMenuInteractionDelegate,
    UIPencilInteractionDelegate {
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
    /// I-4: Spur des Strichs mit zusammengefassten und vorhergesagten Punkten (StrichSpur.swift)
    private let spur = StrichSpur()
    /// Vorhersage bis zum nächsten Ereignis, gleicher Stil wie der Strich
    private let vorhersageLayer = CAShapeLayer()
    private var strichPickLaeuft = false
    private var strichNaechster: (punkt: CGPoint, zeit: Double)?
    private var strichEndeOffen = false

    private lazy var einFinger = UIPanGestureRecognizer(target: self, action: #selector(einFingerZiehen(_:)))
    private lazy var zweiFinger = UIPanGestureRecognizer(target: self, action: #selector(zweiFingerZiehen(_:)))
    private lazy var spreizen = UIPinchGestureRecognizer(target: self, action: #selector(spreizenGeste(_:)))
    private lazy var tippen = UITapGestureRecognizer(target: self, action: #selector(tippenGeste(_:)))
    private lazy var doppeltTippen = UITapGestureRecognizer(target: self, action: #selector(doppeltTippenGeste(_:)))
    private lazy var zweiFingerTippen = UITapGestureRecognizer(target: self, action: #selector(zweiFingerTippenGeste(_:)))
    private lazy var dreiFingerTippen = UITapGestureRecognizer(target: self, action: #selector(dreiFingerTippenGeste(_:)))
    /// Langes Drücken und Sekundärklick: Kontextmenü am Teil (Einträge nach dem Treffertest nachgeladen).
    private lazy var kontextMenue = UIContextMenuInteraction(delegate: self)
    /// Wo das Kontextmenü aufging (UIKit, oben links): dort sitzt die kleine Vorschau am Finger.
    private var kontextOrt: CGPoint = .zero
    private lazy var stift = StiftZugErkenner(target: self, action: #selector(stiftZiehen(_:)))
    /// I-4, Pencil Pro: Rollen um die Längsachse beim Schweben dreht einen offenen Drehregler. Hängt am Fenster, weil
    /// der Werkzeugkranz über dieser Ebene liegt und das Schweben dort ankommt.
    private lazy var stiftRolle = UIHoverGestureRecognizer(target: self, action: #selector(stiftRolleGeste(_:)))
    private lazy var schweben = UIHoverGestureRecognizer(target: self, action: #selector(schwebenGeste(_:)))
    private lazy var rollen = UIPanGestureRecognizer(target: self, action: #selector(rollenGeste(_:)))

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .clear
        isMultipleTouchEnabled = true
        // Ein Element für VoiceOver und die Gesten-Tests; Gesten gehen mit VoiceOver direkt an den Viewer
        isAccessibilityElement = true
        accessibilityLabel = "3D-Ansicht"
        accessibilityIdentifier = "viewer"
        accessibilityTraits = .allowsDirectInteraction

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
        zweiFingerTippen.numberOfTouchesRequired = 2
        zweiFingerTippen.allowedTouchTypes = finger
        dreiFingerTippen.numberOfTouchesRequired = 3
        dreiFingerTippen.allowedTouchTypes = finger
        // Trackpad und Maus: nur das Rollen mit zwei Fingern, keine Berührungen
        rollen.allowedScrollTypesMask = .continuous
        rollen.maximumNumberOfTouches = 0

        for g in [einFinger, zweiFinger, spreizen, tippen, doppeltTippen, zweiFingerTippen, dreiFingerTippen, stift, rollen]
            as [UIGestureRecognizer]
        {
            g.delegate = self
            addGestureRecognizer(g)
        }
        addGestureRecognizer(schweben)
        addInteraction(kontextMenue)
        addInteraction(UIPencilInteraction(delegate: self))

        strichLayer.fillColor = nil
        strichLayer.strokeColor = CGColor(srgbRed: CGFloat(ViewerStil.strich.x), green: CGFloat(ViewerStil.strich.y),
                                          blue: CGFloat(ViewerStil.strich.z), alpha: 1)
        strichLayer.lineWidth = 3
        strichLayer.lineCap = .round
        strichLayer.lineJoin = .round
        strichLayer.isHidden = true
        layer.addSublayer(strichLayer)
        vorhersageLayer.fillColor = nil
        vorhersageLayer.lineCap = .round
        vorhersageLayer.lineJoin = .round
        vorhersageLayer.isHidden = true
        layer.addSublayer(vorhersageLayer)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) wird nicht benutzt") }

    /// Jede Berührung (Finger, Stift, Klick mit Trackpad oder Maus) meldet sich, bevor eine Geste erkannt ist: Tippen in den
    /// Viewer macht ihn zur aktiven Kachel.
    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        schwungStoppen()  // ein Finger hält die nachlaufende Drehung an
        coordinator?.onBeruehrt?()
        super.touchesBegan(touches, with: event)
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        coordinator?.viewSize = bounds.size
        strichLayer.frame = bounds
        vorhersageLayer.frame = bounds
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
        if g === stiftRolle || o === stiftRolle { return true }  // stört nichts, liest nur den Winkel
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

    /// I-4: Dort öffnet der Werkzeugkranz, wenn der Stift nicht schwebt.
    private func beruehrt(_ g: UIGestureRecognizer) {
        coordinator?.letzteBeruehrung = eingabePunkt(g.location(in: self))
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
            beruehrt(g)
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
            // Schnell losgelassen: die Drehung läuft kurz weiter (Schalter „Schwung“, Kranz › Mehr)
            if g.state == .ended, modus == .drehen, c.schwung {
                let v = g.velocity(in: self)
                if let s = Schwung(geschwindigkeit: CGVector(dx: v.x, dy: -v.y)) {
                    schwungStarten(s)
                    return
                }
            }
            modus = .ruht
            endeDrehung()
        }
    }

    // MARK: Schwung (PLAN-IPAD.md 4.2)

    private var schwungLink: CADisplayLink?
    private var schwungLauf: Schwung?
    private var schwungZeit: CFTimeInterval = 0

    /// Drehpunkt und Modus „drehen“ bleiben, bis der Schwung verklingt (so merkt sich der Verlauf erst den Endstand).
    private func schwungStarten(_ s: Schwung) {
        schwungLauf = s
        schwungZeit = CACurrentMediaTime()
        let link = CADisplayLink(target: self, selector: #selector(schwungSchritt(_:)))
        link.preferredFrameRateRange = CAFrameRateRange(minimum: 60, maximum: 120, preferred: 120)
        link.add(to: .main, forMode: .common)
        schwungLink = link
    }

    @objc private func schwungSchritt(_ link: CADisplayLink) {
        let jetzt = link.targetTimestamp
        let dt = jetzt - schwungZeit
        schwungZeit = jetzt
        guard let c = coordinator, var s = schwungLauf, let d = s.schritt(dt) else {
            schwungStoppen()
            return
        }
        schwungLauf = s
        c.navOrbit(dx: Float(d.dx), dy: Float(d.dy))
    }

    private func schwungStoppen() {
        guard schwungLink != nil else { return }
        schwungLink?.invalidate()
        schwungLink = nil
        schwungLauf = nil
        if modus == .drehen { modus = .ruht }
        endeDrehung()
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
        beruehrt(g)
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

    // 2 Finger tippen: Rückgängig, 3 Finger tippen: Wiederholen (Ansicht, Auswahl, Sichtbarkeit; wie ⌘Z und ⇧⌘Z)

    @objc private func zweiFingerTippenGeste(_ g: UITapGestureRecognizer) {
        guard g.state == .ended else { return }
        bedient()
        _ = coordinator?.onBefehl?(.rueckgaengig)
    }

    @objc private func dreiFingerTippenGeste(_ g: UITapGestureRecognizer) {
        guard g.state == .ended else { return }
        bedient()
        _ = coordinator?.onBefehl?(.wiederholen)
    }

    // MARK: Kontextmenü am Teil (langes Drücken, Sekundärklick)

    func contextMenuInteraction(_ interaction: UIContextMenuInteraction,
                                configurationForMenuAtLocation location: CGPoint) -> UIContextMenuConfiguration? {
        guard let c = coordinator, c.onKontextmenue != nil, modus == .ruht else { return nil }
        // Beim Sprechen zeichnet der Finger bzw. Stift; ein Menü dazwischen wäre im Weg
        guard !c.zeichnen else { return nil }
        kontextOrt = location
        let p = eingabePunkt(location)
        return UIContextMenuConfiguration(identifier: "teil" as NSString, previewProvider: nil) { [weak self] _ in
            // Die Einträge hängen am Treffer (das Teil wird ausgewählt): erst nach dem Treffertest nachladen
            let nachgeladen = UIDeferredMenuElement.uncached { fertig in
                MainActor.assumeIsolated {
                    guard let self, let c = self.coordinator else {
                        fertig([])
                        return
                    }
                    c.pickPoint(p, in: self) { [weak c] result in
                        guard let c else {
                            fertig([])
                            return
                        }
                        let gruppen = c.onKontextmenue?(result) ?? []
                        fertig(KontextmenuePad.elemente(gruppen) { [weak c] befehl in _ = c?.onBefehl?(befehl) })
                    }
                }
            }
            return UIMenu(children: [nachgeladen])
        }
    }

    /// Kleine Vorschau am Finger statt des ganzen Viewers: ein Ring in der Farbe der Striche.
    func contextMenuInteraction(_ interaction: UIContextMenuInteraction, configuration: UIContextMenuConfiguration,
                                highlightPreviewForItemWithIdentifier identifier: any NSCopying) -> UITargetedPreview? {
        kontextVorschau()
    }

    func contextMenuInteraction(_ interaction: UIContextMenuInteraction, configuration: UIContextMenuConfiguration,
                                dismissalPreviewForItemWithIdentifier identifier: any NSCopying) -> UITargetedPreview? {
        kontextVorschau()
    }

    func contextMenuInteraction(_ interaction: UIContextMenuInteraction,
                                willDisplayMenuFor configuration: UIContextMenuConfiguration,
                                animator: (any UIContextMenuInteractionAnimating)?) {
        bedient()
        modus = .ruht
        endeDrehung()
    }

    private func kontextVorschau() -> UITargetedPreview {
        let d: CGFloat = 34
        let ring = UIView(frame: CGRect(x: 0, y: 0, width: d, height: d))
        ring.backgroundColor = UIColor(white: 1, alpha: 0.12)
        ring.layer.cornerRadius = d / 2
        ring.layer.borderWidth = 2
        ring.layer.borderColor = CGColor(srgbRed: CGFloat(ViewerStil.strich.x), green: CGFloat(ViewerStil.strich.y),
                                         blue: CGFloat(ViewerStil.strich.z), alpha: 1)
        let p = UIPreviewParameters()
        p.backgroundColor = .clear
        p.visiblePath = UIBezierPath(ovalIn: ring.bounds)
        return UITargetedPreview(view: ring, parameters: p, target: UIPreviewTarget(container: self, center: kontextOrt))
    }

    // MARK: Stift

    @objc private func stiftZiehen(_ g: UIPanGestureRecognizer) {
        guard let c = coordinator else { return }
        let p = eingabePunkt(g.location(in: self))
        switch g.state {
        case .began:
            bedient()
            beruehrt(g)
            let t = g.translation(in: self)
            let start = eingabePunkt(CGPoint(x: g.location(in: self).x - t.x, y: g.location(in: self).y - t.y))
            letzteVerschiebung = .zero
            // I-4: Ohne laufendes Sprechen beginnt der Strich die Sitzung (Vorgabe, im Kranz abschaltbar); geht das
            // nicht (abgeschaltet, kein Projekt), dreht der Stift wie ein Finger
            if c.zeichnen || c.stiftBeginntSprechen?() == true {
                modus = .strich
                strichBeginnen(start)
                strichZiehen(p, erkenner: stift)
            } else {
                modus = .drehen
                beginneDrehung(bei: start)
            }
        case .changed:
            if modus == .strich {
                strichZiehen(p, erkenner: stift)
            } else if modus == .drehen {
                let d = schritt(g)
                c.navOrbit(dx: d.dx, dy: d.dy)
            }
        default:
            if modus == .strich { strichBeenden(p) } else { endeDrehung() }
            modus = .ruht
        }
    }

    // MARK: Pencil doppelt tippen und drücken (I-4)

    override func didMoveToWindow() {
        super.didMoveToWindow()
        stiftRolle.view?.removeGestureRecognizer(stiftRolle)
        guard let w = window else { return }
        stiftRolle.delegate = self
        stiftRolle.cancelsTouchesInView = false
        w.addGestureRecognizer(stiftRolle)
    }

    @objc private func stiftRolleGeste(_ g: UIHoverGestureRecognizer) {
        switch g.state {
        case .began, .changed: _ = coordinator?.onStiftRolle?(Double(g.rollAngle))
        default: _ = coordinator?.onStiftRolle?(nil)
        }
    }

    func pencilInteraction(_ interaction: UIPencilInteraction, didReceiveTap tap: UIPencilInteraction.Tap) {
        guard UIPencilInteraction.preferredTapAction != .ignore else { return }  // Kevin hat es in den Einstellungen aus
        kranzAnDerSpitze(tap.hoverPose?.location)
    }

    func pencilInteraction(_ interaction: UIPencilInteraction, didReceiveSqueeze squeeze: UIPencilInteraction.Squeeze) {
        guard squeeze.phase == .ended, UIPencilInteraction.preferredSqueezeAction != .ignore else { return }
        kranzAnDerSpitze(squeeze.hoverPose?.location)
    }

    /// Kranz an der Spitze (sie schwebt), sonst an der letzten Berührung.
    private func kranzAnDerSpitze(_ ort: CGPoint?) {
        if let ort { zeiger = eingabePunkt(ort) }
        _ = coordinator?.onBefehl?(.werkzeugkranz)
        UISelectionFeedbackGenerator().selectionChanged()
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
        if let stil = coordinator?.strichStil() {  // I-4: Farbe und Breite aus dem Werkzeugkranz
            let farbe = CGColor(srgbRed: CGFloat(stil.farbe.x), green: CGFloat(stil.farbe.y),
                                blue: CGFloat(stil.farbe.z), alpha: 1)
            for l in [strichLayer, vorhersageLayer] {
                l.strokeColor = farbe
                l.lineWidth = stil.breite
            }
        }
        spur.beginnen(CGPoint(x: p.x, y: bounds.height - p.y))
        strichNaechster = nil
        strichEndeOffen = false
        strichZeigen()
        coordinator?.onStrich?(.beginn)
        strichTreffer(p, ProcessInfo.processInfo.systemUptime)
    }

    /// I-4: alle zusammengefassten Punkte in die Linie, die Vorhersage bis zum nächsten Ereignis; Treffer wie bisher
    /// nur für den neuesten Punkt (`p`, Ursprung unten links).
    private func strichZiehen(_ p: CGPoint, erkenner: StiftZugErkenner) {
        let echt = erkenner.zusammengefasst.isEmpty ? [CGPoint(x: p.x, y: bounds.height - p.y)] : erkenner.zusammengefasst
        spur.anfuegen(echt, vorhersage: erkenner.vorhergesagt)
        strichZeigen()
        spur.latenz(beruehrung: erkenner.zeitstempel, jetzt: ProcessInfo.processInfo.systemUptime)
        strichTreffer(p, ProcessInfo.processInfo.systemUptime)
    }

    private func strichBeenden(_ p: CGPoint) {
        spur.beenden()
        strichZeigen()
        coordinator?.strichLatenzMs = spur.latenzAnteil(0.95)
        strichEndeOffen = true
        strichTreffer(p, ProcessInfo.processInfo.systemUptime)
    }

    private func strichZeigen() {
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        strichLayer.frame = bounds
        strichLayer.path = spur.pfad
        strichLayer.isHidden = false
        vorhersageLayer.frame = bounds
        vorhersageLayer.path = spur.vorhersagePfad()
        vorhersageLayer.isHidden = vorhersageLayer.path == nil
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
                self.strichLayer.isHidden = true
                self.vorhersageLayer.isHidden = true
            }
        }
    }

    // MARK: Tastatur (Magic Keyboard)

    override var canBecomeFirstResponder: Bool { true }

    // ⌘Z und ⇧⌘Z: kommen sie über das Menü des Systems (`undo:`, `redo:`), sonst über pressesBegan und die Belegung
    @objc func undo(_ sender: Any?) { _ = coordinator?.onBefehl?(.rueckgaengig) }
    @objc func redo(_ sender: Any?) { _ = coordinator?.onBefehl?(.wiederholen) }

    override func canPerformAction(_ action: Selector, withSender sender: Any?) -> Bool {
        if action == #selector(undo(_:)) || action == #selector(redo(_:)) { return coordinator != nil }
        return super.canPerformAction(action, withSender: sender)
    }

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

/// I-4: Stift ziehen mit den zusammengefassten und vorhergesagten Punkten des letzten Ereignisses (Punkte der Ansicht,
/// oben links) und dem Zeitstempel der Berührung. Sonst ein gewöhnlicher Pan-Erkenner.
final class StiftZugErkenner: UIPanGestureRecognizer {
    private(set) var zusammengefasst: [CGPoint] = []
    private(set) var vorhergesagt: [CGPoint] = []
    private(set) var zeitstempel: TimeInterval = 0

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent) {
        erfassen(touches, event)
        super.touchesBegan(touches, with: event)
    }

    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent) {
        erfassen(touches, event)
        super.touchesMoved(touches, with: event)
    }

    override func reset() {
        super.reset()
        zusammengefasst = []
        vorhergesagt = []
        zeitstempel = 0
    }

    private func erfassen(_ touches: Set<UITouch>, _ event: UIEvent) {
        guard let t = touches.first, let v = view else { return }
        zusammengefasst = (event.coalescedTouches(for: t) ?? [t]).map { $0.preciseLocation(in: v) }
        vorhergesagt = (event.predictedTouches(for: t) ?? []).map { $0.preciseLocation(in: v) }
        zeitstempel = t.timestamp
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
