import Foundation
import simd

/// Schatten auf dem Boden für das Schnellbild (Phase 7, R7 neu, 23.10.2026): auf der CPU statt über die Schattenkarte
/// von RealityKit, damit er dem Foto aus Blender nahekommt (Flächenlichter, Kontaktschatten).
///
/// Je Licht (Richtung zum Licht, halber Öffnungswinkel, Gewicht) werden die Dreiecke des Produkts längs des Lichts auf
/// den Boden projiziert und in ein Raster gezeichnet; jede Zelle merkt sich den kürzesten Weg t vom Boden zum
/// verdeckenden Teil (die tiefste Fläche darüber). Daraus weiche Schatten wie bei einer Flächenleuchte (PCSS): mittlerer
/// Abstand der Verdecker in einem Suchfenster, Halbschatten w = t · tan(Öffnungswinkel), Deckung im Fenster w über
/// Summentabellen in O(1) je Zelle. Wo das Teil den Boden berührt (t ≈ 0), wird der Schatten hart und dunkel
/// (Kontaktschatten), weiter oben weich. Die Helligkeit des Bodens ist die gewichtete Summe der Sichtbarkeit aller
/// Lichter (1 = kein Schatten). Lichter wie in Blender (render/blender_skript.py): Studio mit Hauptlicht, Kante,
/// Aufheller und Decke, dazu der Himmel; mit HDRI Sonne und Himmel.
struct BodenSchatten {
    struct Licht {
        /// Richtung zum Licht (Modell, Z oben), wird normiert; z muss positiv sein
        var richtung: SIMD3<Float>
        /// halber Öffnungswinkel der Leuchte in Grad (Größe der Softbox, Sonne klein)
        var winkelGrad: Float
        var gewicht: Float
        /// nur, was darunter liegt (mm über dem Boden; Dreiecke werden dort abgeschnitten), für den engen
        /// Kontaktschatten
        var nurUnter: Float? = nil
        /// mit der höchsten statt der tiefsten Fläche je Zelle rechnen: für Himmel und Kontakt (wie Umgebungsverdeckung:
        /// eine Wand neben dem Bodenpunkt verdeckt den Himmel nach ihrer Höhe, nicht nach ihrem Fuß)
        var hoechste: Bool = false
    }

    let z0: Float
    let ursprung: SIMD2<Float>
    let zelle: Float
    let nx: Int
    let ny: Int
    /// Helligkeit je Zelle (1 = voll beleuchtet), Zeile für Zeile
    let hell: [Float]

    /// Helligkeit am Bodenpunkt (x, y), bilinear; außerhalb des Rasters 1.
    func wert(_ x: Float, _ y: Float) -> Float {
        let fx = (x - ursprung.x) / zelle - 0.5, fy = (y - ursprung.y) / zelle - 0.5
        guard fx > -1, fy > -1, fx < Float(nx), fy < Float(ny) else { return 1 }
        let x0 = Int(floor(fx)), y0 = Int(floor(fy))
        let tx = fx - Float(x0), ty = fy - Float(y0)
        func h(_ i: Int, _ j: Int) -> Float {
            guard i >= 0, j >= 0, i < nx, j < ny else { return 1 }
            return hell[j * nx + i]
        }
        let a = h(x0, y0) * (1 - tx) + h(x0 + 1, y0) * tx
        let b = h(x0, y0 + 1) * (1 - tx) + h(x0 + 1, y0 + 1) * tx
        return a * (1 - ty) + b * ty
    }

    /// Lichter wie im Foto (Blender) für das Studio: Gewicht je Licht etwa Leistung · cos(Einfall) / π.
    static let studioLichter: [Licht] = [
        Licht(richtung: SIMD3(-0.9, -1.1, 1.25), winkelGrad: 15, gewicht: 2.3),  // Hauptlicht
        Licht(richtung: SIMD3(0.4, 1.3, 1.1), winkelGrad: 13, gewicht: 1.0),  // Kante (im Foto schwächer als gerechnet)
        Licht(richtung: SIMD3(1.3, -0.6, 0.5), winkelGrad: 18, gewicht: 0.37),  // Aufheller
        Licht(richtung: SIMD3(0, 0, 1), winkelGrad: 27, gewicht: 0.8, hoechste: true),  // Decke
        Licht(richtung: SIMD3(0, 0, 1), winkelGrad: 60, gewicht: 0.45, hoechste: true),  // Himmel (graue Welt)
    ]

    /// Lichter mit Umgebungsbild: Sonne bzw. hellste Stelle (klein) und Himmel (weit).
    static func umgebungsLichter(sonne: SIMD3<Float>?) -> [Licht] {
        let himmel = { (g: Float) in Licht(richtung: SIMD3(0, 0, 1), winkelGrad: 60, gewicht: g, hoechste: true) }
        if let s = sonne, s.z > 0.12 {
            return [Licht(richtung: s, winkelGrad: 4, gewicht: 0.55), himmel(0.45)]
        }
        return [Licht(richtung: SIMD3(-0.4, -0.6, 1.4), winkelGrad: 25, gewicht: 0.35), himmel(0.65)]
    }

    /// Kontaktschatten: eng und dunkel um die Aufstandsfläche, nur aus dem, was dicht über dem Boden liegt (Anteil der
    /// Modellgröße).
    static func kontakt(groesse: Float, gewicht: Float = 0.6) -> Licht {
        Licht(richtung: SIMD3(0, 0, 1), winkelGrad: 70, gewicht: gewicht, nurUnter: max(1, groesse * 0.04),
              hoechste: true)
    }

    /// Rechnet das Raster. `dreiecke`: je Dreieck drei Punkte (Modell, mm, Z oben), flach hintereinander.
    static func rechne(dreiecke: [SIMD3<Float>], z0: Float, lichter: [Licht], maxZellen: Int = 768) -> BodenSchatten? {
        guard dreiecke.count >= 3, !lichter.isEmpty else { return nil }
        var lo = SIMD3<Float>(repeating: .greatestFiniteMagnitude), hi = -lo
        for p in dreiecke {
            lo = simd_min(lo, p)
            hi = simd_max(hi, p)
        }
        let groesse = max(simd_length(hi - lo), 1)
        let hoehe = max(hi.z - z0, 0)
        // Raster: Grundriss plus Schatten jedes Lichts plus Halbschatten
        var rlo = SIMD2(lo.x, lo.y), rhi = SIMD2(hi.x, hi.y)
        var rand: Float = 0
        for l in lichter {
            let d = simd_normalize(l.richtung)
            guard d.z > 0.05 else { continue }
            let h = min(l.nurUnter ?? hoehe, hoehe)
            let versatz = -SIMD2(d.x, d.y) / d.z * h
            rlo = simd_min(rlo, SIMD2(lo.x, lo.y) + versatz)
            rhi = simd_max(rhi, SIMD2(hi.x, hi.y) + versatz)
            rand = max(rand, h / d.z * tan(l.winkelGrad * .pi / 180))
        }
        rand = min(rand, groesse * 1.5) + groesse * 0.02
        rlo -= SIMD2(repeating: rand)
        rhi += SIMD2(repeating: rand)
        let ausdehnung = rhi - rlo
        let zelle = max(max(ausdehnung.x, ausdehnung.y) / Float(maxZellen), groesse / 4000)
        let nx = max(2, Int(ceil(ausdehnung.x / zelle))), ny = max(2, Int(ceil(ausdehnung.y / zelle)))
        var summe = [Float](repeating: 0, count: nx * ny)
        var gewichte: Float = 0
        for l in lichter {
            let d = simd_normalize(l.richtung)
            guard d.z > 0.05 else { continue }
            var tmin = projiziere(dreiecke, d: d, z0: z0, ursprung: rlo, zelle: zelle, nx: nx, ny: ny,
                                  nurUnter: l.nurUnter, hoechste: l.hoechste)
            if let grenze = l.nurUnter {
                // Kontaktschatten: alles, was im Streifen über dem Boden liegt (Aufstandsfläche, Fuß der Wände), zählt
                // gleich hoch; so wird die Aufstandsfläche gleichmäßig um grenze · tan(Winkel) weich ausgeblendet
                let tk = grenze / d.z
                for i in 0..<(nx * ny) where tmin[i].isFinite { tmin[i] = tk }
            }
            let sicht = weich(tmin, nx: nx, ny: ny, zelle: zelle, tanW: tan(l.winkelGrad * .pi / 180),
                              tMax: min(l.nurUnter ?? hoehe, hoehe) / d.z, hoechste: l.hoechste)
            for i in 0..<(nx * ny) { summe[i] += l.gewicht * sicht[i] }
            gewichte += l.gewicht
        }
        guard gewichte > 0 else { return nil }
        for i in 0..<(nx * ny) { summe[i] /= gewichte }
        PBRRenderer.kastenfilter(&summe, nx, ny, 1)  // Treppen der Rasterung glätten
        return BodenSchatten(z0: z0, ursprung: rlo, zelle: zelle, nx: nx, ny: ny, hell: summe)
    }

    /// Dreiecke längs `d` auf den Boden projizieren und rastern: je Zelle der kleinste (mit `hoechste` der größte) Weg t
    /// (mm längs des Strahls vom Boden zum Teil); unendlich, wo nichts verdeckt. Mit `nurUnter` wird jedes Dreieck an
    /// dieser Höhe abgeschnitten.
    static func projiziere(_ tri: [SIMD3<Float>], d: SIMD3<Float>, z0: Float, ursprung: SIMD2<Float>, zelle: Float,
                           nx: Int, ny: Int, nurUnter: Float?, hoechste: Bool = false) -> [Float] {
        let leer: Float = hoechste ? -.infinity : .infinity
        var t = [Float](repeating: leer, count: nx * ny)
        let fx = d.x / d.z, fy = d.y / d.z, inv = 1 / d.z
        t.withUnsafeMutableBufferPointer { buf in
            func setze(_ i: Int, _ tt: Float) {
                if hoechste ? tt > buf[i] : tt < buf[i] { buf[i] = tt }
            }
            func zeichne(_ p0: SIMD3<Float>, _ p1: SIMD3<Float>, _ p2: SIMD3<Float>) {
                let h0 = max(p0.z - z0, 0), h1 = max(p1.z - z0, 0), h2 = max(p2.z - z0, 0)
                // Bodenpunkt in Zellkoordinaten und Weg längs des Strahls
                let a = SIMD2((p0.x - fx * h0 - ursprung.x) / zelle, (p0.y - fy * h0 - ursprung.y) / zelle)
                let b = SIMD2((p1.x - fx * h1 - ursprung.x) / zelle, (p1.y - fy * h1 - ursprung.y) / zelle)
                let c = SIMD2((p2.x - fx * h2 - ursprung.x) / zelle, (p2.y - fy * h2 - ursprung.y) / zelle)
                let ta = h0 * inv, tb = h1 * inv, tc = h2 * inv
                let minX = max(0, Int(floor(min(a.x, b.x, c.x)))), maxX = min(nx - 1, Int(floor(max(a.x, b.x, c.x))))
                let minY = max(0, Int(floor(min(a.y, b.y, c.y)))), maxY = min(ny - 1, Int(floor(max(a.y, b.y, c.y))))
                if minX > maxX || minY > maxY { return }
                let flaeche = (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
                if abs(flaeche) < 0.25 {
                    // schmal oder längs des Lichts (Wand von oben, dünner Stab): die Kanten als Linien zeichnen, damit
                    // nichts zwischen den Zellmitten verloren geht
                    for (u, v, tu, tv) in [(a, b, ta, tb), (b, c, tb, tc), (c, a, tc, ta)] {
                        let n = max(1, Int(ceil(max(abs(v.x - u.x), abs(v.y - u.y)) * 2)))
                        for k in 0...n {
                            let s = Float(k) / Float(n)
                            let q = u + (v - u) * s
                            let x = Int(floor(q.x)), y = Int(floor(q.y))
                            if x >= 0, y >= 0, x < nx, y < ny { setze(y * nx + x, tu + (tv - tu) * s) }
                        }
                    }
                    return
                }
                let inv2 = 1 / flaeche
                for y in minY...maxY {
                    let py = Float(y) + 0.5
                    for x in minX...maxX {
                        let px = Float(x) + 0.5
                        let w0 = ((b.x - px) * (c.y - py) - (b.y - py) * (c.x - px)) * inv2
                        let w1 = ((c.x - px) * (a.y - py) - (c.y - py) * (a.x - px)) * inv2
                        let w2 = 1 - w0 - w1
                        guard w0 >= -1e-4, w1 >= -1e-4, w2 >= -1e-4 else { continue }
                        setze(y * nx + x, w0 * ta + w1 * tb + w2 * tc)
                    }
                }
            }
            var i = 0
            while i + 2 < tri.count {
                let p = [tri[i], tri[i + 1], tri[i + 2]]
                i += 3
                guard let grenze = nurUnter else {
                    zeichne(p[0], p[1], p[2])
                    continue
                }
                // an der Höhe z0 + grenze abschneiden (Sutherland-Hodgman an einer Ebene), dann als Fächer zeichnen
                let zc = z0 + grenze
                if p.allSatisfy({ $0.z <= zc }) {
                    zeichne(p[0], p[1], p[2])
                    continue
                }
                if p.allSatisfy({ $0.z > zc }) { continue }
                var poly: [SIMD3<Float>] = []
                for k in 0..<3 {
                    let u = p[k], v = p[(k + 1) % 3]
                    if u.z <= zc { poly.append(u) }
                    if (u.z <= zc) != (v.z <= zc) {
                        let s = (zc - u.z) / (v.z - u.z)
                        poly.append(u + (v - u) * s)
                    }
                }
                if poly.count >= 3 {
                    for k in 1..<(poly.count - 1) { zeichne(poly[0], poly[k], poly[k + 1]) }
                }
            }
        }
        return t
    }

    /// Weicher Schatten (PCSS) aus dem Raster der Wege: Suchfenster für den mittleren Verdecker, dann Deckung im
    /// Halbschatten-Fenster (Summentabellen, O(1) je Zelle). Liefert die Sichtbarkeit des Lichts je Zelle (1 = frei).
    static func weich(_ t: [Float], nx: Int, ny: Int, zelle: Float, tanW: Float, tMax: Float,
                      hoechste: Bool = false) -> [Float] {
        let n = nx * ny
        var deckt = [Double](repeating: 0, count: n), weg = [Double](repeating: 0, count: n)
        for i in 0..<n where t[i].isFinite {
            deckt[i] = 1
            weg[i] = Double(t[i])
        }
        let satD = summentabelle(deckt, nx, ny), satT = summentabelle(weg, nx, ny)
        let suche = max(1, Int(ceil(tMax * tanW / zelle)))
        var out = [Float](repeating: 1, count: n)
        let w = nx + 1
        satD.withUnsafeBufferPointer { sd in
            satT.withUnsafeBufferPointer { st in
                t.withUnsafeBufferPointer { tb in
                    out.withUnsafeMutableBufferPointer { o in
                        @inline(__always) func box(_ s: UnsafeBufferPointer<Double>, _ x: Int, _ y: Int, _ r: Int)
                            -> Double
                        {
                            let x0 = max(0, x - r), x1 = min(nx, x + r + 1), y0 = max(0, y - r), y1 = min(ny, y + r + 1)
                            return s[y1 * w + x1] - s[y0 * w + x1] - s[y1 * w + x0] + s[y0 * w + x0]
                        }
                        let k = Double(tanW / zelle)
                        for y in 0..<ny {
                            for x in 0..<nx {
                                let anzahl = box(sd, x, y, suche)
                                guard anzahl > 0.5 else { continue }
                                let tMittel = box(st, x, y, suche) / anzahl
                                let tHier = Double(tb[y * nx + x])
                                // tiefste Fläche: am Fuß wird der Schatten hart (Kontakt); höchste: Mittel ringsum
                                let tt = tHier.isFinite && !hoechste ? min(tHier, tMittel) : tMittel
                                let r = max(0, Int((tt * k).rounded()))
                                let flaeche = Double((2 * r + 1) * (2 * r + 1))
                                o[y * nx + x] = Float(max(0, 1 - box(sd, x, y, r) / flaeche))
                            }
                        }
                    }
                }
            }
        }
        return out
    }

    /// Summentabelle ((nx + 1) × (ny + 1)).
    static func summentabelle(_ v: [Double], _ nx: Int, _ ny: Int) -> [Double] {
        var s = [Double](repeating: 0, count: (nx + 1) * (ny + 1))
        let w = nx + 1
        v.withUnsafeBufferPointer { vb in
            s.withUnsafeMutableBufferPointer { sb in
                for y in 0..<ny {
                    var zeile = 0.0
                    for x in 0..<nx {
                        zeile += vb[y * nx + x]
                        sb[(y + 1) * w + x + 1] = sb[y * w + x + 1] + zeile
                    }
                }
            }
        }
        return s
    }
}
