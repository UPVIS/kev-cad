import CoreGraphics
import Foundation
import OCCTSwiftViewport
import simd

/// Rechnung für den Blick durch eine Kamera: Formatrahmen im Viewport (Letterbox), Öffnungswinkel des Viewports,
/// Kamerazustand für Viewport und Offscreen-Bild, Pyramide im Raum, auszublendende Teile, Vorschlag aus der Ansicht.
public enum CameraViewMath {
    /// Rand um den Formatrahmen (Anteil der knappen Seite), Platz für Rahmen und Angaben.
    public static let frameMargin: CGFloat = 0.9
    /// EBU R 95: Aktionsbereich 93 % (3,5 % Rand), Titelbereich 90 % (5 % Rand) des Bildes.
    public static let actionSafe: CGFloat = 0.93
    public static let titleSafe: CGFloat = 0.90

    /// Formatrahmen mit Seitenverhältnis `aspect` mittig im Viewport (Punkte, Ursprung oben links).
    public static func frameRect(viewSize: CGSize, aspect: Double, margin: CGFloat = frameMargin) -> CGRect {
        let w = max(viewSize.width, 1), h = max(viewSize.height, 1)
        let a = CGFloat(max(aspect, 0.01))
        var fw = w * margin, fh = fw / a
        if fh > h * margin {
            fh = h * margin
            fw = fh * a
        }
        return CGRect(x: (w - fw) / 2, y: (h - fh) / 2, width: fw, height: fh)
    }

    /// Vertikaler Öffnungswinkel des Viewports (Grad), damit der Formatrahmen genau den vertikalen Bildwinkel der
    /// Kamera zeigt: tan(fov / 2) = tan(v / 2) · Viewporthöhe / Rahmenhöhe.
    public static func viewportFieldOfView(cameraVertical deg: Double, viewSize: CGSize, frame: CGRect) -> Float {
        let half = deg * .pi / 360
        let t = tan(half) * Double(max(viewSize.height, 1)) / Double(max(frame.height, 1))
        return Float(2 * atan(t) * 180 / .pi)
    }

    /// Entfernung des Drehpunkts vor dem Augpunkt: Fokusebene (Fokus ab Sensor minus Brennweite), sonst 3 m.
    public static func pivotDistance(_ c: CameraInfo) -> Float {
        let f = c.fokus.map { $0 - c.brennweite } ?? 3000
        return Float(min(max(f.isFinite ? f : 3000, 50), 1e6))
    }

    /// Kamerazustand des Viewports für den Blick durch `c` (perspektivisch, Augpunkt, Blick und Oben der Kamera).
    public static func viewportState(for c: CameraInfo, viewSize: CGSize) -> CameraState {
        let frame = frameRect(viewSize: viewSize, aspect: c.seitenverhaeltnis)
        var s = state(for: c)
        s.fieldOfView = viewportFieldOfView(cameraVertical: c.bildwinkelV, viewSize: viewSize, frame: frame)
        return s
    }

    /// Kamerazustand mit genau dem vertikalen Bildwinkel der Kamera (für ein Bild im Seitenverhältnis des Formats).
    public static func state(for c: CameraInfo) -> CameraState {
        let d = pivotDistance(c)
        var s = CameraState.lookAt(target: c.auge + c.blick * d, from: c.auge, up: c.oben)
        s.fieldOfView = Float(c.bildwinkelV)
        s.isOrthographic = false
        s.panOffset = .zero
        return s
    }

    /// Gleicher Blick wie erwartet (Kamera unverändert, abgesehen von Rundung)?
    public static func same(_ a: CameraState, _ b: CameraState) -> Bool {
        simd_distance(a.position, b.position) < 0.05 * max(1, a.distance * 0.001)
            && abs(simd_dot(a.rotation.vector, b.rotation.vector)) > 0.99999
            && abs(a.fieldOfView - b.fieldOfView) < 0.01 && a.isOrthographic == b.isOrthographic
    }

    // MARK: Pyramide im Raum

    /// Länge der Pyramide: bis zur Fokusebene, begrenzt auf 0,1 bis 8 m (bei Fokus unendlich die hyperfokale
    /// Distanz).
    public static func pyramidLength(_ c: CameraInfo) -> Float {
        let fokus = c.fokus ?? c.hyperfokal ?? 3000
        return Float(min(max(fokus - c.brennweite, 100), 8000))
    }

    /// Ecken des Bildfelds im Abstand `length` vor dem Augpunkt (oben links, oben rechts, unten rechts, unten links).
    public static func corners(_ c: CameraInfo, length: Float) -> [SIMD3<Float>] {
        let hw = length * Float(tan(c.bildwinkelH * .pi / 360))
        let hh = length * Float(tan(c.bildwinkelV * .pi / 360))
        let m = c.auge + c.blick * length
        return [m - c.rechts * hw + c.oben * hh, m + c.rechts * hw + c.oben * hh, m + c.rechts * hw - c.oben * hh,
                m - c.rechts * hw - c.oben * hh]
    }

    public static let pyramidColor = SIMD4<Float>(0.80, 0.83, 0.88, 0.95)
    public static let activeColor = SIMD4<Float>(0.95, 0.52, 0.1, 1)
    public static let dofColor = SIMD4<Float>(0.2, 0.55, 0.85, 0.7)

    /// Ist die Kamera mit ihrem Teil ausgeblendet? `teil`: gezeigtes Teil, dem sie folgt (nil = steht frei, nie
    /// verborgen); `gruppe`: Name aus model.py (Teil oder Baugruppe). Eine Baugruppe gilt als verborgen, wenn alle
    /// ihre Teile verborgen sind, ein Teil, wenn es selbst verborgen ist.
    public static func verborgen(teil: String?, gruppe: String?, order: [String], hidden: Set<String>) -> Bool {
        guard let teil else { return false }
        if let g = gruppe, !g.isEmpty, g != teil {
            let glieder = order.filter { $0.hasPrefix(g + "/") }
            if !glieder.isEmpty { return glieder.allSatisfy { hidden.contains($0) } }
        }
        return hidden.contains(teil)
    }

    /// Pyramide vom Augpunkt bis zur Fokusebene, Dreieck über der Oberkante (wo oben ist), Namen und die Grenzen der
    /// Schärfentiefe als dünne Rahmen.
    public static func overlay(_ c: CameraInfo, selected: Bool) -> [OverlayPrimitive] {
        let len = pyramidLength(c)
        let k = corners(c, length: len)
        let color = selected ? activeColor : pyramidColor
        var out: [OverlayPrimitive] = []
        for p in k { out.append(.polyline(points: [c.auge, p], color: color, width: 1.2)) }
        out.append(.polyline(points: k + [k[0]], color: color, width: selected ? 2 : 1.5))
        let top = (k[0] + k[1]) / 2
        let side = simd_distance(k[0], k[1])
        let tri = [k[0] + (k[1] - k[0]) * 0.35, top + c.oben * side * 0.12, k[0] + (k[1] - k[0]) * 0.65]
        out.append(.polyline(points: tri + [tri[0]], color: color, width: 1.5))
        // Sensorebene: kleiner Rahmen in Sensorgröße an der Sensormitte
        let sw = Float(c.sensorMM.x / 2), sh = Float(c.sensorMM.y / 2)
        let s = c.sensorPos
        let sensor = [s - c.rechts * sw + c.oben * sh, s + c.rechts * sw + c.oben * sh, s + c.rechts * sw - c.oben * sh,
                      s - c.rechts * sw - c.oben * sh]
        out.append(.polyline(points: sensor + [sensor[0]], color: color, width: 1))
        for limit in selected ? [c.schaerfeNah, c.schaerfeFern] : [] {  // Schärfentiefe nur bei der gewählten
            guard let l = limit, l.isFinite, l - c.brennweite > 10, Float(l - c.brennweite) < len * 4 else { continue }
            let q = corners(c, length: Float(l - c.brennweite))
            out.append(.polyline(points: q + [q[0]], color: dofColor, width: 1))
        }
        out.append(.label(point: top + c.oben * side * 0.14, text: "\(c.displayName) · \(c.brennweiteText)", color: color))
        return out
    }

    // MARK: Ausblenden beim Blick durch die Kamera

    /// Teile, die beim Blick durch `c` stören: das eigene Objektiv (`ausblenden`) und jedes Teil, dessen Hüllquader
    /// die Strecke vom Augpunkt bis zur Frontlinse (plus 5 mm) schneidet.
    public static func hiddenParts(for c: CameraInfo, bounds: [(String, BoundingBox)]) -> Set<String> {
        var out = Set(c.ausblenden)
        let a = c.auge
        let b = c.sensorPos + c.blick * Float(max(c.objektivVorne + 5, c.brennweite + 1))
        for (name, box) in bounds where segmentHits(a, b, box) { out.insert(name) }
        return out
    }

    /// Schneidet die Strecke a–b den Quader? (Slab-Verfahren)
    public static func segmentHits(_ a: SIMD3<Float>, _ b: SIMD3<Float>, _ box: BoundingBox) -> Bool {
        let d = b - a
        var t0: Float = 0, t1: Float = 1
        for i in 0..<3 {
            if abs(d[i]) < 1e-9 {
                if a[i] < box.min[i] || a[i] > box.max[i] { return false }
                continue
            }
            var ta = (box.min[i] - a[i]) / d[i], tb = (box.max[i] - a[i]) / d[i]
            if ta > tb { swap(&ta, &tb) }
            t0 = max(t0, ta)
            t1 = min(t1, tb)
            if t0 > t1 { return false }
        }
        return true
    }

    /// Körper ohne die Teile in `hidden` (Körper-ids beginnen mit dem Teilnamen und dem Trennzeichen U+001F).
    public static func filter(_ bodies: [ViewportBody], hiding hidden: Set<String>) -> [ViewportBody] {
        guard !hidden.isEmpty else { return bodies }
        return bodies.filter { body in
            var id = Substring(body.id)
            if id.hasPrefix("snap\u{1F}") { id = id.dropFirst(5) }
            guard let cut = id.firstIndex(of: "\u{1F}") else { return true }
            return !hidden.contains(String(id[..<cut]))
        }
    }

    // MARK: Vorschlag aus der Ansicht (Strg+Alt+0)

    /// Lage der Kamera aus dem Viewport: Augpunkt = Kameraposition des Viewports, Blick und Oben wie dort; Roll in Grad
    /// gegenüber einer waagrechten Kamera (positiv im Uhrzeigersinn von hinten, wie `roll` in model.py).
    public static func suggestion(from s: CameraState, for c: CameraInfo) -> CameraSuggestMessage {
        suggestion(auge: s.position, blick: s.viewDirection, oben: s.upVector, for: c)
    }

    /// Vorschlag aus Augpunkt, Blick und Oben (Weltkoordinaten der Ruhelage).
    public static func suggestion(
        auge: SIMD3<Float>, blick viewDirection: SIMD3<Float>, oben upVector: SIMD3<Float>, for c: CameraInfo
    ) -> CameraSuggestMessage {
        let blick = simd_normalize(viewDirection)
        let oben = simd_normalize(upVector)
        let rechts = simd_normalize(simd_cross(blick, oben))
        let ref: SIMD3<Float> = abs(blick.z) < 0.999 ? SIMD3(0, 0, 1) : SIMD3(0, 1, 0)
        let r0 = simd_normalize(simd_cross(blick, ref))
        let o0 = simd_cross(r0, blick)
        let roll = Double(atan2(simd_dot(oben, r0), simd_dot(oben, o0))) * 180 / .pi
        return CameraSuggestMessage(
            name: c.name, sensorPos: auge - blick * Float(c.brennweite), auge: auge, blick: blick, oben: oben,
            rechts: rechts, roll: roll)
    }

    // MARK: Rahmen im Kamerabild

    /// Sicherheitsbereiche innerhalb des Formatrahmens.
    public static func safeAreas(in frame: CGRect) -> (action: CGRect, title: CGRect) {
        func inset(_ k: CGFloat) -> CGRect {
            frame.insetBy(dx: frame.width * (1 - k) / 2, dy: frame.height * (1 - k) / 2)
        }
        return (inset(actionSafe), inset(titleSafe))
    }
}
