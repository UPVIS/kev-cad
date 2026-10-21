import CoreGraphics
import CoreText
import Foundation
import OCCTSwiftViewport
import simd

#if canImport(AppKit)
    import AppKit
#endif

/// Etwas, das über dem 3D-Bild gezeichnet wird (Weltkoordinaten in mm).
public enum OverlayPrimitive: Sendable {
    case polyline(points: [SIMD3<Float>], color: SIMD4<Float>, width: CGFloat)
    case dot(point: SIMD3<Float>, color: SIMD4<Float>, radius: CGFloat)
    /// Maßlinie zwischen zwei Punkten mit Beschriftung in der Mitte.
    case dimension(a: SIMD3<Float>, b: SIMD3<Float>, text: String, color: SIMD4<Float>)
    case arrow(from: SIMD3<Float>, to: SIMD3<Float>, text: String?, color: SIMD4<Float>)
    case label(point: SIMD3<Float>, text: String, color: SIMD4<Float>)
    /// Kleines Symbol am Punkt (Zwangsbedingung wie in CAD-Programmen): `filled` = verletzt (gefüllt, weiße Schrift).
    case badge(point: SIMD3<Float>, text: String, color: SIMD4<Float>, filled: Bool)
}

/// Welt → Bildpunkte (Ursprung oben links, y nach unten), passend zur Kamera des Viewports.
public struct OverlayProjector {
    public let viewProjection: simd_float4x4
    public let size: CGSize

    public init(camera: CameraState, size: CGSize) {
        let aspect = size.height > 0 ? Float(size.width / size.height) : 1
        // Nah- und Fernebene beeinflussen x und y nicht
        viewProjection = camera.projectionMatrix(aspectRatio: aspect, near: 0.01, far: 1e7) * camera.viewMatrix
        self.size = size
    }

    public func project(_ p: SIMD3<Float>) -> CGPoint? {
        let c = viewProjection * SIMD4(p, 1)
        guard c.w > 1e-6 else { return nil }
        let x = CGFloat((c.x / c.w + 1) * 0.5) * size.width
        let y = CGFloat((1 - c.y / c.w) * 0.5) * size.height
        guard x.isFinite, y.isFinite else { return nil }
        return CGPoint(x: x, y: y)
    }
}

/// Zeichnet Überlagerungen in einen CGContext, dessen y-Achse nach unten zeigt. Dieselbe Funktion dient der
/// Anzeige im Viewport (SwiftUI-Canvas) und den Bildern für den Agenten, damit beide gleich aussehen.
public enum OverlayPainter {
    public static func draw(
        _ items: [OverlayPrimitive], in ctx: CGContext, projector: OverlayProjector, scale: CGFloat = 1
    ) {
        guard !items.isEmpty else { return }
        ctx.saveGState()
        ctx.setLineCap(.round)
        ctx.setLineJoin(.round)
        // Linien zuerst, Symbole und Beschriftungen obenauf
        var labels: [(CGPoint, String, SIMD4<Float>)] = []
        var badges: [(CGPoint, String, SIMD4<Float>, Bool)] = []
        for item in items {
            switch item {
            case .badge(let p, let text, let color, let filled):
                guard let s = projector.project(p) else { continue }
                badges.append((s, text, color, filled))
            case .polyline(let pts, let color, let width):
                let ps = pts.compactMap(projector.project)
                guard ps.count >= 2 else { continue }
                ctx.setStrokeColor(cg(color))
                ctx.setLineWidth(width * scale)
                ctx.addLines(between: ps)
                ctx.strokePath()
            case .dot(let p, let color, let radius):
                guard let s = projector.project(p) else { continue }
                let r = radius * scale
                ctx.setFillColor(cg(color))
                ctx.fillEllipse(in: CGRect(x: s.x - r, y: s.y - r, width: 2 * r, height: 2 * r))
                ctx.setStrokeColor(CGColor(gray: 1, alpha: 0.9))
                ctx.setLineWidth(1.5 * scale)
                ctx.strokeEllipse(in: CGRect(x: s.x - r, y: s.y - r, width: 2 * r, height: 2 * r))
            case .dimension(let a, let b, let text, let color):
                guard let pa = projector.project(a), let pb = projector.project(b) else { continue }
                ctx.setStrokeColor(cg(color))
                ctx.setLineWidth(1.5 * scale)
                ctx.move(to: pa)
                ctx.addLine(to: pb)
                ctx.strokePath()
                // Endstriche quer zur Linie
                let dx = pb.x - pa.x, dy = pb.y - pa.y
                let len = max(hypot(dx, dy), 0.001)
                let nx = -dy / len * 6 * scale, ny = dx / len * 6 * scale
                for p in [pa, pb] {
                    ctx.move(to: CGPoint(x: p.x - nx, y: p.y - ny))
                    ctx.addLine(to: CGPoint(x: p.x + nx, y: p.y + ny))
                }
                ctx.strokePath()
                for p in [pa, pb] {
                    ctx.setFillColor(cg(color))
                    ctx.fillEllipse(in: CGRect(x: p.x - 2.5 * scale, y: p.y - 2.5 * scale, width: 5 * scale, height: 5 * scale))
                }
                labels.append((CGPoint(x: (pa.x + pb.x) / 2, y: (pa.y + pb.y) / 2), text, color))
            case .arrow(let from, let to, let text, let color):
                guard let pa = projector.project(from), let pb = projector.project(to) else { continue }
                ctx.setStrokeColor(cg(color))
                ctx.setLineWidth(2 * scale)
                ctx.move(to: pa)
                ctx.addLine(to: pb)
                ctx.strokePath()
                let ang = atan2(pb.y - pa.y, pb.x - pa.x)
                let head = 11 * scale
                ctx.setFillColor(cg(color))
                ctx.move(to: pb)
                ctx.addLine(to: CGPoint(x: pb.x - head * cos(ang - 0.4), y: pb.y - head * sin(ang - 0.4)))
                ctx.addLine(to: CGPoint(x: pb.x - head * cos(ang + 0.4), y: pb.y - head * sin(ang + 0.4)))
                ctx.closePath()
                ctx.fillPath()
                if let text, !text.isEmpty { labels.append((pa, text, color)) }
            case .label(let p, let text, let color):
                guard let s = projector.project(p) else { continue }
                ctx.setFillColor(cg(color))
                ctx.fillEllipse(in: CGRect(x: s.x - 3 * scale, y: s.y - 3 * scale, width: 6 * scale, height: 6 * scale))
                labels.append((CGPoint(x: s.x + 8 * scale, y: s.y - 14 * scale), text, color))
            }
        }
        // Symbole nebeneinander, wenn mehrere am selben Punkt sitzen
        var used: [CGRect] = []
        for (p, text, color, filled) in badges {
            used.append(drawBadge(text, at: p, color: color, filled: filled, in: ctx, scale: scale, avoid: used))
        }
        // Beschriftungen nicht übereinander: eine verdeckte rutscht nach unten
        var placed: [CGRect] = []
        for (p, text, color) in labels {
            placed.append(drawLabel(text, at: p, color: color, in: ctx, scale: scale, avoid: placed))
        }
        ctx.restoreGState()
    }

    /// Beschriftung mit hellem Kasten, mittig um `p`.
    @discardableResult
    static func drawLabel(
        _ text: String, at p: CGPoint, color: SIMD4<Float>, in ctx: CGContext, scale: CGFloat, avoid: [CGRect] = []
    ) -> CGRect {
        let font = CTFontCreateUIFontForLanguage(.system, 12 * scale, nil)
            ?? CTFontCreateWithName("Helvetica" as CFString, 12 * scale, nil)
        let attrs: [CFString: Any] = [
            kCTFontAttributeName: font,
            kCTForegroundColorAttributeName: CGColor(srgbRed: 0.1, green: 0.1, blue: 0.12, alpha: 1),
        ]
        guard let attributed = CFAttributedStringCreate(nil, text as CFString, attrs as CFDictionary) else { return .null }
        let line = CTLineCreateWithAttributedString(attributed)
        var ascent: CGFloat = 0, descent: CGFloat = 0, leading: CGFloat = 0
        let width = CGFloat(CTLineGetTypographicBounds(line, &ascent, &descent, &leading))
        let padX = 6 * scale, padY = 3 * scale
        var box = CGRect(
            x: p.x - width / 2 - padX, y: p.y - (ascent + descent) / 2 - padY, width: width + 2 * padX,
            height: ascent + descent + 2 * padY)
        for _ in 0..<8 where avoid.contains(where: { $0.intersects(box) }) {
            box.origin.y += box.height + 3 * scale
        }
        let path = CGPath(roundedRect: box, cornerWidth: 4 * scale, cornerHeight: 4 * scale, transform: nil)
        ctx.addPath(path)
        ctx.setFillColor(CGColor(srgbRed: 1, green: 1, blue: 1, alpha: 0.92))
        ctx.fillPath()
        ctx.addPath(path)
        ctx.setStrokeColor(cg(color))
        ctx.setLineWidth(1 * scale)
        ctx.strokePath()
        ctx.saveGState()
        // y zeigt nach unten: Text spiegeln, damit er aufrecht steht
        ctx.textMatrix = CGAffineTransform(scaleX: 1, y: -1)
        ctx.textPosition = CGPoint(x: box.minX + padX, y: box.minY + padY + ascent)
        CTLineDraw(line, ctx)
        ctx.restoreGState()
        return box
    }

    /// Symbol einer Bedingung: abgerundetes Quadrat neben dem Punkt, Zeichen in der Mitte.
    @discardableResult
    static func drawBadge(
        _ text: String, at p: CGPoint, color: SIMD4<Float>, filled: Bool, in ctx: CGContext, scale: CGFloat,
        avoid: [CGRect] = []
    ) -> CGRect {
        let size = 18 * scale
        var box = CGRect(x: p.x + 4 * scale, y: p.y - size - 4 * scale, width: size, height: size)
        for _ in 0..<6 where avoid.contains(where: { $0.intersects(box) }) {
            box.origin.x += size + 2 * scale
        }
        let path = CGPath(roundedRect: box, cornerWidth: 4 * scale, cornerHeight: 4 * scale, transform: nil)
        ctx.addPath(path)
        ctx.setFillColor(filled ? cg(color) : CGColor(srgbRed: 1, green: 1, blue: 1, alpha: 0.92))
        ctx.fillPath()
        ctx.addPath(path)
        ctx.setStrokeColor(cg(color))
        ctx.setLineWidth(1.2 * scale)
        ctx.strokePath()
        // Fähnchen zum Punkt
        ctx.setStrokeColor(cg(color))
        ctx.setLineWidth(1 * scale)
        ctx.move(to: p)
        ctx.addLine(to: CGPoint(x: box.minX, y: box.maxY))
        ctx.strokePath()
        let font = CTFontCreateUIFontForLanguage(.system, 11 * scale, nil)
            ?? CTFontCreateWithName("Helvetica" as CFString, 11 * scale, nil)
        let ink = filled ? CGColor(gray: 1, alpha: 1) : cg(color)
        let attrs: [CFString: Any] = [kCTFontAttributeName: font, kCTForegroundColorAttributeName: ink]
        guard let attributed = CFAttributedStringCreate(nil, text as CFString, attrs as CFDictionary) else { return box }
        let line = CTLineCreateWithAttributedString(attributed)
        var ascent: CGFloat = 0, descent: CGFloat = 0, leading: CGFloat = 0
        let width = CGFloat(CTLineGetTypographicBounds(line, &ascent, &descent, &leading))
        ctx.saveGState()
        ctx.textMatrix = CGAffineTransform(scaleX: 1, y: -1)
        ctx.textPosition = CGPoint(x: box.midX - width / 2, y: box.midY + (ascent - descent) / 2)
        CTLineDraw(line, ctx)
        ctx.restoreGState()
        return box
    }

    static func cg(_ c: SIMD4<Float>) -> CGColor {
        CGColor(srgbRed: CGFloat(c.x), green: CGFloat(c.y), blue: CGFloat(c.z), alpha: CGFloat(c.w))
    }
}
