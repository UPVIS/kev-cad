import SwiftUI

/// Rahmen beim Blick durch eine Kamera (Taste 0): abgedunkelter Rand außerhalb des Formats, Formatrahmen,
/// Aktions- und Titelbereich (EBU R 95), Mittelkreuz und die Angaben der Kamera. Meldet Größenänderungen, damit der
/// App-Kern den Öffnungswinkel nachführt.
struct CameraFrameOverlay: View {
    @ObservedObject var store: CameraStore
    let onResize: (CGSize) -> Void

    var body: some View {
        GeometryReader { geo in
            ZStack {
                if let name = store.activeView, let cam = store.camera(name) {
                    frame(cam, size: geo.size)
                }
            }
            .frame(width: geo.size.width, height: geo.size.height)
            .onAppear { onResize(geo.size) }
            .onChange(of: geo.size) { _, size in onResize(size) }
        }
        .allowsHitTesting(false)
    }

    @ViewBuilder
    private func frame(_ cam: CameraInfo, size: CGSize) -> some View {
        let rect = CameraViewMath.frameRect(viewSize: size, aspect: cam.seitenverhaeltnis)
        let safe = CameraViewMath.safeAreas(in: rect)
        Canvas { ctx, canvasSize in
            var outside = Path(CGRect(origin: .zero, size: canvasSize))
            outside.addRect(rect)
            ctx.fill(outside, with: .color(.black.opacity(0.5)), style: FillStyle(eoFill: true))
            ctx.stroke(Path(rect), with: .color(.white.opacity(0.95)), lineWidth: 1.5)
            let dash = StrokeStyle(lineWidth: 1, dash: [5, 4])
            ctx.stroke(Path(safe.action), with: .color(.white.opacity(0.55)), style: dash)
            ctx.stroke(Path(safe.title), with: .color(.white.opacity(0.35)), style: dash)
            var cross = Path()
            let c = CGPoint(x: rect.midX, y: rect.midY)
            cross.move(to: CGPoint(x: c.x - 10, y: c.y))
            cross.addLine(to: CGPoint(x: c.x + 10, y: c.y))
            cross.move(to: CGPoint(x: c.x, y: c.y - 10))
            cross.addLine(to: CGPoint(x: c.x, y: c.y + 10))
            ctx.stroke(cross, with: .color(.white.opacity(0.7)), lineWidth: 1)
        }
        let top = "\(cam.displayName) · \(cam.kameraName) · \(cam.formatName)"
            + (cam.vorschlag ? " · Vorschlag aus der Ansicht" : "")
        let bottom = "\(cam.brennweiteText) · \(cam.blendeText) · Fokus \(cam.fokusText) · Bildwinkel "
            + "\(cam.bildwinkelText) · Schärfe \(cam.schaerfeText)"
        CameraLabel(text: top, detail: cam.objektivName)
            .padding(.leading, rect.minX + 6)
            .padding(.top, rect.minY + 6)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        CameraLabel(text: bottom, detail: cam.vignettierung ? "Bildkreis zu klein: die Ecken vignettieren" : nil)
            .padding(.leading, rect.minX + 6)
            .padding(.bottom, size.height - rect.maxY + 6)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
        CameraLabel(text: "0: zurück · Strg+Alt+0: Kamera auf Ansicht", detail: nil, small: true)
            .padding(.trailing, size.width - rect.maxX + 6)
            .padding(.top, rect.minY + 6)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
    }
}

private struct CameraLabel: View {
    let text: String
    let detail: String?
    var small = false

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(text).font(.system(size: small ? 10.5 : 12, weight: small ? .regular : .semibold))
            if let detail { Text(detail).font(.system(size: 11)).opacity(0.8) }
        }
        .foregroundStyle(.white.opacity(small ? 0.8 : 1))
        .lineLimit(1)
        .padding(.horizontal, 6)
        .padding(.vertical, 3)
        .background(RoundedRectangle(cornerRadius: 4).fill(.black.opacity(0.45)))
        .fixedSize()
    }
}
