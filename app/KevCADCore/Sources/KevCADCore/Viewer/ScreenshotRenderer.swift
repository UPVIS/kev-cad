import CoreGraphics
import Foundation
import ImageIO
import OCCTSwiftViewport
import UniformTypeIdentifiers

/// Bilder ohne Fenster (OffscreenRenderer) mit derselben Überlagerung wie im Viewport.
@MainActor
public final class ScreenshotRenderer {
    private var renderer: OffscreenRenderer?
    public var backgroundColor = SIMD4<Float>(0.95, 0.95, 0.95, 1)

    public init() {}

    public struct Result {
        public var image: CGImage
        public var png: Data
        public var camera: CameraState
        /// mm je Pixel bei Parallelprojektion, sonst nil
        public var mmPerPixel: Double?
    }

    public func render(
        bodies: [ViewportBody], camera: CameraState, width: Int, height: Int, displayMode: DisplayMode,
        lighting: LightingConfiguration = .threePoint, overlay: [OverlayPrimitive] = []
    ) -> Result? {
        let w = max(16, min(width, 8192)), h = max(16, min(height, 8192))
        if renderer == nil { renderer = OffscreenRenderer() }
        guard let renderer else { return nil }
        let options = OffscreenRenderOptions(
            width: w, height: h, cameraState: camera, displayMode: displayMode, lightingConfiguration: lighting,
            backgroundColor: backgroundColor, showGrid: false, showAxes: false, msaaSampleCount: 4)
        guard let base = renderer.render(bodies: bodies, options: options) else { return nil }
        let image = overlay.isEmpty ? base : (Self.composite(base, overlay: overlay, camera: camera) ?? base)
        guard let png = Self.pngData(image) else { return nil }
        let mm = camera.isOrthographic ? Double(camera.orthographicScale) / Double(h) : nil
        return Result(image: image, png: png, camera: camera, mmPerPixel: mm)
    }

    /// Überlagerung in das Bild zeichnen.
    static func composite(_ image: CGImage, overlay: [OverlayPrimitive], camera: CameraState) -> CGImage? {
        let w = image.width, h = image.height
        guard let space = CGColorSpace(name: CGColorSpace.sRGB),
            let ctx = CGContext(
                data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0, space: space,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
        else { return nil }
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
        // y nach unten wie im Viewport
        ctx.translateBy(x: 0, y: CGFloat(h))
        ctx.scaleBy(x: 1, y: -1)
        let size = CGSize(width: w, height: h)
        let scale = max(1, CGFloat(h) / 800)
        OverlayPainter.draw(overlay, in: ctx, projector: OverlayProjector(camera: camera, size: size), scale: scale)
        return ctx.makeImage()
    }

    public static func pngData(_ image: CGImage) -> Data? {
        let data = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(data as CFMutableData, UTType.png.identifier as CFString, 1, nil)
        else { return nil }
        CGImageDestinationAddImage(dest, image, nil)
        guard CGImageDestinationFinalize(dest) else { return nil }
        return data as Data
    }
}
