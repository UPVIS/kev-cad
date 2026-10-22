import CoreGraphics
import Foundation
import ImageIO
import OCCTSwiftViewport
import simd

/// Fotoansicht (Phase 4): das Modell durch die eingepasste Kamera eines Fotos rendern und mit dem Foto verrechnen.
///
/// - Kamera: OpenCV-Kamera aus REF_PHOTOS (R, t, f, cx, cy, Bildgröße). Der Viewport kennt nur einen Hauptpunkt in
///   der Bildmitte; liegt er im Foto anders, wird auf eine größere Leinwand gerendert, auf der er in der Mitte liegt,
///   und das Foto daraus ausgeschnitten (`Leinwand`).
/// - Deckung des Modells: zwei Bilder, einmal auf weißem, einmal auf schwarzem Grund. Die Differenz ist die Deckung
///   je Pixel (Kanten mit Kantenglättung inklusive), das schwarze Bild ist schon mit ihr multipliziert.
/// - Überlagern: Foto, darüber das Modell mit der Deckkraft des Reglers. Differenz: Foto grau, rot nur im Foto (Maske
///   von fotomess), blau nur im Modell; die Überdeckung (IoU) steht daneben.
public enum FotoAbgleich {
    public struct Leinwand: Equatable, Sendable {
        public var breite: Int
        public var hoehe: Int
        /// Lage des Fotos auf der Leinwand (Pixel, links oben)
        public var x0: Int
        public var y0: Int
    }

    public static func leinwand(_ k: ReferenzKamera) -> Leinwand {
        let w = Double(k.breite), h = Double(k.hoehe)
        let lw = Int(ceil(2 * max(k.cx, w - k.cx))), lh = Int(ceil(2 * max(k.cy, h - k.cy)))
        let x0 = Int((Double(lw) / 2 - k.cx).rounded()), y0 = Int((Double(lh) / 2 - k.cy).rounded())
        return Leinwand(breite: max(lw, k.breite), hoehe: max(lh, k.hoehe), x0: max(0, x0), y0: max(0, y0))
    }

    /// Viewport-Kamera durch die eingepasste Kamera, für ein Bild der Höhe `hoehe` (Pixel der Leinwand).
    public static func kameraZustand(_ k: ReferenzKamera, hoehe: Int) -> CameraState {
        let c = SIMD3<Float>(k.zentrum)
        let d = SIMD3<Float>(k.blick)
        var s = CameraState.lookAt(target: c + d * 300, from: c, up: SIMD3<Float>(k.oben))
        s.fieldOfView = Float(2 * atan(Double(hoehe) / 2 / k.f) * 180 / .pi)
        s.isOrthographic = false
        s.panOffset = .zero
        return s
    }

    // MARK: Pixel

    /// RGBA8-Pixel (Zeile 0 oben) eines Bildes in der Größe `breite` × `hoehe`.
    public static func pixel(_ bild: CGImage, breite: Int, hoehe: Int) -> [UInt8] {
        var px = [UInt8](repeating: 0, count: breite * hoehe * 4)
        guard let space = CGColorSpace(name: CGColorSpace.sRGB) else { return px }
        px.withUnsafeMutableBytes { buf in
            guard let ctx = CGContext(
                data: buf.baseAddress, width: breite, height: hoehe, bitsPerComponent: 8, bytesPerRow: breite * 4,
                space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
            else { return }
            ctx.interpolationQuality = .high
            ctx.draw(bild, in: CGRect(x: 0, y: 0, width: breite, height: hoehe))
        }
        return px
    }

    /// Grauwerte (0…255) einer Maske in der Größe `breite` × `hoehe`.
    public static func grau(_ bild: CGImage, breite: Int, hoehe: Int) -> [UInt8] {
        let p = pixel(bild, breite: breite, hoehe: hoehe)
        var out = [UInt8](repeating: 0, count: breite * hoehe)
        for i in 0..<(breite * hoehe) { out[i] = p[i * 4] }
        return out
    }

    public static func bild(_ px: [UInt8], breite: Int, hoehe: Int) -> CGImage? {
        guard let space = CGColorSpace(name: CGColorSpace.sRGB),
              let provider = CGDataProvider(data: Data(px) as CFData)
        else { return nil }
        return CGImage(
            width: breite, height: hoehe, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: breite * 4, space: space,
            bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue), provider: provider,
            decode: nil, shouldInterpolate: true, intent: .defaultIntent)
    }

    public static func laden(_ url: URL) -> CGImage? {
        guard let src = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
        return CGImageSourceCreateImageAtIndex(src, 0, [kCGImageSourceShouldCache: true] as CFDictionary)
    }

    /// Deckung (0…255) und vormultiplizierte Farbe des Modells aus dem Bild auf weißem und auf schwarzem Grund.
    public static func deckung(weiss: [UInt8], schwarz: [UInt8]) -> [UInt8] {
        let n = min(weiss.count, schwarz.count) / 4
        var a = [UInt8](repeating: 0, count: n)
        for i in 0..<n {
            let j = i * 4
            let d = (Int(weiss[j]) - Int(schwarz[j]) + Int(weiss[j + 1]) - Int(schwarz[j + 1]) + Int(weiss[j + 2])
                - Int(schwarz[j + 2])) / 3
            a[i] = UInt8(clamping: 255 - d)
        }
        return a
    }

    public struct Ergebnis {
        public var pixel: [UInt8]
        /// Überdeckung Modell und Maske (nur mit Maske)
        public var ueberdeckung: Double?
    }

    /// Foto mit Modell verrechnen. `foto`: RGBA8, `deckung`: 0…255 je Pixel, `modell`: das Bild auf schwarzem Grund
    /// (vormultipliziert), `maske`: 0…255 (Objekt hell) oder nil. Alles in derselben Größe.
    public static func verrechnen(
        foto: [UInt8], deckung: [UInt8], modell: [UInt8], maske: [UInt8]?, deckkraft: Double,
        modus: FotoAnsicht.Modus
    ) -> Ergebnis {
        let n = deckung.count
        var out = [UInt8](repeating: 255, count: n * 4)
        let d = Float(min(max(deckkraft, 0), 1))
        var schnitt = 0, vereinigt = 0
        if modus == .differenz, let maske {
            let rot = SIMD3<Float>(232, 44, 44), blau = SIMD3<Float>(38, 112, 238)
            for i in 0..<n {
                let j = i * 4
                let g = (0.3 * Float(foto[j]) + 0.59 * Float(foto[j + 1]) + 0.11 * Float(foto[j + 2])) * 0.6 + 40
                let imFoto = maske[i] >= 128, imModell = deckung[i] >= 128
                var c = SIMD3<Float>(repeating: g)
                if imFoto && !imModell {
                    c += (rot - c) * (0.35 + 0.6 * d)
                } else if imModell && !imFoto {
                    c += (blau - c) * (0.35 + 0.6 * d)
                }
                if imFoto && imModell { schnitt += 1 }
                if imFoto || imModell { vereinigt += 1 }
                out[j] = UInt8(clamping: Int(c.x))
                out[j + 1] = UInt8(clamping: Int(c.y))
                out[j + 2] = UInt8(clamping: Int(c.z))
            }
        } else {
            for i in 0..<n {
                let j = i * 4
                let a = Float(deckung[i]) / 255 * d
                for k in 0..<3 {
                    let v = Float(foto[j + k]) * (1 - a) + Float(modell[j + k]) * d
                    out[j + k] = UInt8(clamping: Int(v.rounded()))
                }
                if let maske {
                    let imFoto = maske[i] >= 128, imModell = deckung[i] >= 128
                    if imFoto && imModell { schnitt += 1 }
                    if imFoto || imModell { vereinigt += 1 }
                }
            }
        }
        let iou = maske != nil && vereinigt > 0 ? Double(schnitt) / Double(vereinigt) : nil
        return Ergebnis(pixel: out, ueberdeckung: iou)
    }

    /// Ausschnitt der Leinwand an der Stelle des Fotos (CGImage-Koordinaten, Ursprung links oben).
    public static func ausschnitt(_ bild: CGImage, _ l: Leinwand, breite: Int, hoehe: Int) -> CGImage? {
        if l.x0 == 0 && l.y0 == 0 && bild.width == breite && bild.height == hoehe { return bild }
        return bild.cropping(to: CGRect(x: l.x0, y: l.y0, width: breite, height: hoehe))
    }
}
