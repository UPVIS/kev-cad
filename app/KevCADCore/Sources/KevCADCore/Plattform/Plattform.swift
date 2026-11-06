// Plattform-Weichen des Kerns (Paket I-1: KevCADCore übersetzt für macOS und iPadOS). Hier stehen nur Typen und kleine
// Hilfen, die es auf beiden Seiten gibt, nur unter anderem Namen. Was es nur am Mac gibt (Kernel-Prozess, XPC zu
// Wortlaut, NSEvent-Monitore, Druckdialog, Kontextmenü als NSMenu), steht in den Dateien selbst hinter `#if os(macOS)`.
// Offene Stellen auf dem iPad tragen den Kommentar „iPad: folgt in I-x“ nach PLAN-IPAD.md (I-2b Kernel übers Netz, I-3
// Eingabe und Touch, I-4 Stift, I-5 Sprechen, I-7 iCloud, I-8 Teilen, Drucken, Video, I-9 Selbsttests). Am Mac ändert
// diese Datei nichts: Die Namen zeigen dort auf genau die Typen, die der Kern bisher benutzt hat.

#if os(macOS)
import AppKit

/// Farbe der Oberfläche: NSColor am Mac, UIColor auf dem iPad.
public typealias PlattformFarbe = NSColor
/// Ansicht der Oberfläche: NSView am Mac, UIView auf dem iPad.
public typealias PlattformView = NSView
/// Sondertasten eines Ereignisses: NSEvent.ModifierFlags am Mac (unverändert), UIKeyModifierFlags auf dem iPad.
public typealias PlattformTastenFlags = NSEvent.ModifierFlags
/// Bild der Oberfläche: NSImage am Mac, UIImage auf dem iPad (seit I-3a).
public typealias PlattformBild = NSImage
#else
import UIKit

public typealias PlattformFarbe = UIColor
public typealias PlattformView = UIView
public typealias PlattformTastenFlags = UIKeyModifierFlags
public typealias PlattformBild = UIImage

extension UIKeyModifierFlags {
    /// Wahltaste unter dem Namen des Mac (UIKit nennt sie `alternate`), damit Auswertungen im Kern auf beiden Seiten
    /// gleich lesen. Nur im Kern sichtbar.
    static let option = UIKeyModifierFlags.alternate
}
#endif

extension PlattformFarbe {
    /// Farbe aus sRGB-Anteilen 0…1 (am Mac `NSColor(srgbRed:…)`; UIKit rechnet `UIColor(red:…)` ebenfalls in sRGB).
    static func srgb(_ rot: CGFloat, _ gruen: CGFloat, _ blau: CGFloat, _ alpha: CGFloat = 1) -> PlattformFarbe {
        #if os(macOS)
        NSColor(srgbRed: rot, green: gruen, blue: blau, alpha: alpha)
        #else
        UIColor(red: rot, green: gruen, blue: blau, alpha: alpha)
        #endif
    }
}

extension PlattformView {
    /// Bildpunkte je Punkt auf dem Bildschirm des Fensters; nil ohne Fenster.
    var bildschirmSkala: CGFloat? {
        #if os(macOS)
        window?.backingScaleFactor
        #else
        window?.traitCollection.displayScale
        #endif
    }

    /// Takt des Bildschirms, auf dem die Ansicht liegt (am Mac `NSView.displayLink`, auf dem iPad `CADisplayLink` mit bis
    /// zu 120 Bildern je Sekunde auf ProMotion). Wie bisher: noch nicht in eine Ereignisschleife eingehängt.
    func bildschirmtakt(_ ziel: Any, _ auswahl: Selector) -> CADisplayLink {
        #if os(macOS)
        displayLink(target: ziel, selector: auswahl)
        #else
        let link = CADisplayLink(target: ziel, selector: auswahl)
        link.preferredFrameRateRange = CAFrameRateRange(minimum: 60, maximum: 120, preferred: 120)
        return link
        #endif
    }

    /// Ein neues Bild anfordern (`needsDisplay` am Mac, `setNeedsDisplay()` auf dem iPad).
    func neuZeichnenAnfordern() {
        #if os(macOS)
        needsDisplay = true
        #else
        setNeedsDisplay()
        #endif
    }
}

/// Zustand der App selbst (öffentlich seit I-3a, auch die Oberfläche nimmt diesen Weg).
@MainActor
public enum PlattformApp {
    /// Mitteilung kurz vor dem Beenden der App.
    public static var wirdBeendet: Notification.Name {
        #if os(macOS)
        NSApplication.willTerminateNotification
        #else
        UIApplication.willTerminateNotification
        #endif
    }

    /// Zeigt die Ansicht (ohne Ansicht: die App) gerade das dunkle Erscheinungsbild?
    public static func istDunkel(_ view: PlattformView?) -> Bool {
        #if os(macOS)
        (view?.effectiveAppearance ?? NSApp.effectiveAppearance).bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
        #else
        (view?.traitCollection ?? UITraitCollection.current).userInterfaceStyle == .dark
        #endif
    }
}

extension PlattformBild {
    /// Bild aus einer Datei; nil, wenn sie fehlt oder kein Bild ist (am Mac `NSImage(contentsOf:)`).
    public static func laden(_ url: URL) -> PlattformBild? {
        #if os(macOS)
        NSImage(contentsOf: url)
        #else
        UIImage(contentsOfFile: url.path)
        #endif
    }

    /// Bild aus einem CGImage mit der Größe in Punkten (am Mac `NSImage(cgImage:size:)`; auf dem iPad bestimmt der
    /// Maßstab die Größe in Punkten).
    public static func ausCG(_ cg: CGImage, punkte: CGSize) -> PlattformBild {
        #if os(macOS)
        NSImage(cgImage: cg, size: punkte)
        #else
        UIImage(cgImage: cg, scale: punkte.width > 0 ? CGFloat(cg.width) / punkte.width : 1, orientation: .up)
        #endif
    }
}
