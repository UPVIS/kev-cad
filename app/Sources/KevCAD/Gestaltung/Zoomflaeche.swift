#if os(macOS)
import AppKit
#else
import UIKit
#endif
import SwiftUI

// V2-10 (Kevin, 06.11.2026: „dass man auch beliebig die anderen Ansichten, egal welche das sind, zoomen kann“): Zoom und
// Verschieben für gezeichnete Ansichten (Bild eines Bauplanschritts, Druckplatte), wie in Vorschau: Trackpad aufziehen
// oder ⌘ mit dem Mausrad zoomt um den Zeiger, Ziehen verschiebt, sobald vergrößert, mit zwei Fingern ebenso;
// „Einpassen“ (oder ein Doppelklick, wo der nichts anderes tut) setzt zurück. Der 3D-Viewer, die zweite Ansicht und die
// Blätter der Zeichnung zoomen mit eigener Steuerung. Gezeichnet wird mit der Transformation im Canvas, damit Linien bei
// jeder Vergrößerung scharf bleiben.

/// Vergrößerung und Verschiebung einer gezeichneten Ansicht. Reine Rechnung, damit Treffer und Zeichnung dasselbe nutzen.
struct ZoomZustand: Equatable {
    static let hoechstens: CGFloat = 12

    var skala: CGFloat = 1
    /// Verschiebung in Punkten nach dem Vergrößern
    var versatz: CGSize = .zero

    var vergroessert: Bool { skala > 1.001 }

    /// Punkt im ungezoomten Bild → Punkt der Ansicht: um die Mitte vergrößert, dann verschoben.
    func transform(in groesse: CGSize) -> CGAffineTransform {
        let m = CGPoint(x: groesse.width / 2, y: groesse.height / 2)
        return CGAffineTransform(translationX: m.x + versatz.width, y: m.y + versatz.height)
            .scaledBy(x: skala, y: skala)
            .translatedBy(x: -m.x, y: -m.y)
    }

    /// Punkt der Ansicht → Punkt im ungezoomten Bild (Treffer, Zeiger).
    func zurueck(_ p: CGPoint, in groesse: CGSize) -> CGPoint { p.applying(transform(in: groesse).inverted()) }

    /// Um `faktor` zoomen; was unter `p` liegt, bleibt unter dem Zeiger.
    mutating func zoomen(_ faktor: CGFloat, um p: CGPoint, in groesse: CGSize) {
        guard faktor.isFinite, faktor > 0 else { return }
        let fest = zurueck(p, in: groesse)
        skala = min(Self.hoechstens, max(1, skala * faktor))
        let jetzt = fest.applying(transform(in: groesse))
        versatz.width += p.x - jetzt.x
        versatz.height += p.y - jetzt.y
        begrenzen(in: groesse)
    }

    mutating func verschieben(_ d: CGSize, in groesse: CGSize) {
        versatz.width += d.width
        versatz.height += d.height
        begrenzen(in: groesse)
    }

    /// Das Bild deckt die Ansicht immer ganz: verschoben wird höchstens bis zu seinem Rand, ungezoomt liegt es mittig.
    mutating func begrenzen(in groesse: CGSize) {
        guard vergroessert else {
            self = ZoomZustand()
            return
        }
        let gx = groesse.width * (skala - 1) / 2, gy = groesse.height * (skala - 1) / 2
        versatz.width = min(gx, max(-gx, versatz.width))
        versatz.height = min(gy, max(-gy, versatz.height))
    }
}

extension View {
    /// Zoom und Verschieben wie in Vorschau (siehe oben). `doppelklick`: ein Doppelklick setzt zurück (nur wo er sonst
    /// nichts tut).
    func zoombar(_ zoom: Binding<ZoomZustand>, doppelklick: Bool = false) -> some View {
        modifier(Zoombar(zoom: zoom, doppelklick: doppelklick))
    }
}

private struct Zoombar: ViewModifier {
    @Binding var zoom: ZoomZustand
    let doppelklick: Bool
    @StateObject private var rad = ZoomRad()
    @State private var startSkala: CGFloat?
    @State private var gezogen: CGSize?

    func body(content: Content) -> some View {
        GeometryReader { geo in
            content
                .contentShape(Rectangle())
                .gesture(
                    MagnifyGesture()
                        .onChanged { v in
                            let s0 = startSkala ?? zoom.skala
                            if startSkala == nil { startSkala = s0 }
                            zoom.zoomen(s0 * v.magnification / zoom.skala, um: v.startLocation, in: geo.size)
                        }
                        .onEnded { _ in startSkala = nil })
                #if os(iOS)
                // iPad (I-3b): Vergrößert gehört der Finger dem Bild, eine Liste darum rollt nicht mit; eingepasst
                // rollt sie wie gewohnt. Zwei Finger spreizen zoomt um ihre Mitte (MagnifyGesture oben).
                .highPriorityGesture(ziehen(geo.size), including: zoom.vergroessert ? .all : .none)
                #else
                .simultaneousGesture(ziehen(geo.size))
                #endif
                .simultaneousGesture(TapGesture(count: 2).onEnded { zoom = ZoomZustand() },
                                     including: doppelklick ? .all : .none)
                .onContinuousHover { phase in
                    switch phase {
                    case .active(let p): rad.zeiger = p
                    case .ended: rad.zeiger = nil
                    }
                }
                .overlay(alignment: .topTrailing) {
                    if zoom.vergroessert {
                        Button {
                            zoom = ZoomZustand()
                        } label: {
                            Text("\(Int((zoom.skala * 100).rounded())) %  ·  Einpassen")
                                .font(.system(size: 10, weight: .semibold))
                                .monospacedDigit()
                        }
                        .buttonStyle(.plain)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(.regularMaterial, in: Capsule())
                        .padding(8)
                        .help("Zoom zurücksetzen (⌘ und Mausrad oder zwei Finger zoomen)")
                    }
                }
                .onAppear {
                    rad.groesse = geo.size
                    rad.aendern = { f in f(&zoom) }
                    rad.vergroessert = { zoom.vergroessert }
                    rad.an()
                }
                .onChange(of: geo.size) { _, s in
                    rad.groesse = s
                    zoom.begrenzen(in: s)
                }
                .onDisappear { rad.aus() }
        }
    }

    /// Vergrößert verschiebt Ziehen das Bild.
    private func ziehen(_ groesse: CGSize) -> some Gesture {
        DragGesture(minimumDistance: 4)
            .onChanged { v in
                guard zoom.vergroessert else { return }
                let vorher = gezogen ?? .zero
                zoom.verschieben(CGSize(width: v.translation.width - vorher.width,
                                        height: v.translation.height - vorher.height), in: groesse)
                gezogen = v.translation
            }
            .onEnded { _ in gezogen = nil }
    }
}

/// Mausrad und Trackpad über der Ansicht: ⌘ zoomt um den Zeiger, vergrößert verschieben zwei Finger das Bild. Sonst
/// bleibt das Ereignis bei der Liste darum, die weiter rollt.
@MainActor
private final class ZoomRad: ObservableObject {
    var zeiger: CGPoint?
    var groesse: CGSize = .zero
    var aendern: (((inout ZoomZustand) -> Void)) -> Void = { _ in }
    var vergroessert: () -> Bool = { false }
    private var monitor: Any?

    /// Mausrad und Trackpad am Mac. iPad: zwei Finger spreizen (MagnifyGesture in `Zoombar`), auch am Trackpad.
    func an() {
        #if os(macOS)
        guard monitor == nil else { return }
        monitor = NSEvent.addLocalMonitorForEvents(matching: .scrollWheel) { [weak self] e in
            nonisolated(unsafe) let e = e
            let verbraucht = MainActor.assumeIsolated { self?.rad(e) ?? false }
            return verbraucht ? nil : e
        }
        #endif
    }

    func aus() {
        #if os(macOS)
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
        #endif
    }

    #if os(macOS)
    private func rad(_ e: NSEvent) -> Bool {
        guard let p = zeiger else { return false }
        let g = groesse
        if e.modifierFlags.contains(.command) {
            let k: CGFloat = e.hasPreciseScrollingDeltas ? 0.01 : 0.12
            let faktor = exp(e.scrollingDeltaY * k)
            aendern { $0.zoomen(faktor, um: p, in: g) }
            return true
        }
        if vergroessert(), e.hasPreciseScrollingDeltas {
            aendern { $0.verschieben(CGSize(width: e.scrollingDeltaX, height: e.scrollingDeltaY), in: g) }
            return true
        }
        return false
    }
    #endif
}
