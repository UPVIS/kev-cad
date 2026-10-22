import CoreGraphics
import CoreText
import Foundation

/// Schrift der Zeichnungen: osifont (ISO 3098, LGPL-3 mit Font-Ausnahme), mitgeliefert in den App-Ressourcen
/// (`app/Resources/Fonts`, Lizenz daneben). Geladen direkt aus der Datei (ohne systemweite Registrierung), damit sie auch
/// in Tests und Hintergrundthreads gleich ist und im PDF als Teilmenge eingebettet wird.
///
/// Höhen auf dem Blatt sind Versalhöhen (ISO 3098 Typ B): `font(versalhoehe: 3.5)` liefert eine Schrift, deren
/// Großbuchstaben genau 3,5 Einheiten hoch sind (in Blatt-mm gezeichnet also 3,5 mm, entsprechend 13,46 pt).
public enum BlattSchrift {
    public static let dateiname = "osifont-lgpl3fe"

    private final class Zustand: @unchecked Sendable {
        let lock = NSLock()
        var url: URL?
        var gesucht = false
        var descriptor: CTFontDescriptor?
        var verhaeltnis: CGFloat?
        var fonts: [CGFloat: CTFont] = [:]
    }

    private static let zustand = Zustand()

    /// Schriftdatei vorgeben (vor der ersten Verwendung; Tests und Selbsttests).
    public static func verwende(datei url: URL) {
        let z = zustand
        z.lock.lock()
        defer { z.lock.unlock() }
        z.url = url
        z.gesucht = true
        z.descriptor = nil
        z.verhaeltnis = nil
        z.fonts = [:]
    }

    /// Mögliche Orte der Schriftdatei, in dieser Reihenfolge.
    static func kandidaten() -> [URL] {
        var out: [URL] = []
        for sub in [nil, "Fonts"] as [String?] {
            if let u = Bundle.main.url(forResource: dateiname, withExtension: "ttf", subdirectory: sub) { out.append(u) }
        }
        if let env = ProcessInfo.processInfo.environment["KEVCAD_SCHRIFT"], !env.isEmpty {
            out.append(URL(fileURLWithPath: env))
        }
        // Arbeitsstand des Repos (Tests von KevCADCore): app/Resources/Fonts neben app/KevCADCore
        var repo = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { repo.deleteLastPathComponent() }
        out.append(repo.appendingPathComponent("Resources/Fonts/\(dateiname).ttf"))
        out.append(URL(fileURLWithPath:
            "/Applications/FreeCAD.app/Contents/Resources/share/Mod/TechDraw/Resources/fonts/\(dateiname).ttf"))
        return out
    }

    /// Gefundene Schriftdatei (nil: Ersatzschrift Helvetica).
    public static var datei: URL? {
        let z = zustand
        z.lock.lock()
        defer { z.lock.unlock() }
        ladeWennNoetig(z)
        return z.descriptor == nil ? nil : z.url
    }

    /// osifont gefunden und lesbar.
    public static var istOsifont: Bool { datei != nil }

    private static func ladeWennNoetig(_ z: Zustand) {
        if z.descriptor != nil { return }
        if !z.gesucht {
            z.gesucht = true
            z.url = kandidaten().first { FileManager.default.fileExists(atPath: $0.path) }
        }
        if let url = z.url,
            let list = CTFontManagerCreateFontDescriptorsFromURL(url as CFURL) as? [CTFontDescriptor],
            let d = list.first
        {
            z.descriptor = d
        }
    }

    /// Versalhöhe je Schriftgrad (osifont 0,737).
    public static var versalVerhaeltnis: CGFloat {
        let z = zustand
        z.lock.lock()
        defer { z.lock.unlock() }
        return verhaeltnis(z)
    }

    private static func verhaeltnis(_ z: Zustand) -> CGFloat {
        if let v = z.verhaeltnis { return v }
        ladeWennNoetig(z)
        // Gemessen am „H“ (Glyphenhülle), nicht an der Angabe in der Schriftdatei: die Versalhöhe soll exakt stimmen
        let f = basis(z, groesse: 100)
        var cap = CTFontGetCapHeight(f)
        var zeichen: [UniChar] = Array("H".utf16)
        var glyph = [CGGlyph](repeating: 0, count: 1)
        if CTFontGetGlyphsForCharacters(f, &zeichen, &glyph, 1) {
            let r = CTFontGetBoundingRectsForGlyphs(f, .horizontal, glyph, nil, 1)
            if r.height > 1 { cap = r.maxY }
        }
        let v = cap > 1 ? cap / 100 : 0.72
        z.verhaeltnis = v
        return v
    }

    private static func basis(_ z: Zustand, groesse: CGFloat) -> CTFont {
        if let d = z.descriptor { return CTFontCreateWithFontDescriptor(d, groesse, nil) }
        return CTFontCreateWithName("Helvetica" as CFString, groesse, nil)
    }

    /// Schrift, deren Versalhöhe `h` Einheiten beträgt (in Blatt-mm gezeichnet: `h` mm).
    public static func font(versalhoehe h: CGFloat) -> CTFont {
        let z = zustand
        z.lock.lock()
        defer { z.lock.unlock() }
        let key = (h * 1000).rounded() / 1000
        if let f = z.fonts[key] { return f }
        let f = basis(z, groesse: key / verhaeltnis(z))
        if z.fonts.count > 200 { z.fonts.removeAll() }
        z.fonts[key] = f
        return f
    }

    /// Schriftgrad in Punkt für eine Versalhöhe in mm (3,5 mm → 13,46 pt bei osifont).
    public static func punktgroesse(versalhoehe mm: Double) -> Double {
        mm * 72.0 / 25.4 / Double(versalVerhaeltnis)
    }

    /// Name der Schrift, wie sie im PDF landet.
    public static var postscriptName: String {
        CTFontCopyPostScriptName(font(versalhoehe: 3.5)) as String
    }
}
