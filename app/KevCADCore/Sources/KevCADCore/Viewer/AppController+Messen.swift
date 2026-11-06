import Foundation
import OCCTSwiftViewport
import QuartzCore
import simd

// Messen (V2, Schritt 6): Vorschau beim Darüberfahren (eine Kreiskante zeigt ihren Durchmesser, eine Kante ihre Länge),
// Fangen an Ecken, Kantenmitten und Kreismitten, Messungen zwischen Punkten in der App. Zwei Elemente misst weiter der
// Kernel exakt (MEASURE_REQ), ebenso ein Element allein (zweimal dasselbe anklicken).

/// Art eines Fangpunkts.
public enum FangArt: String, Sendable {
    case ecke, kantenmitte, kreismitte

    public var titel: String {
        switch self {
        case .ecke: return "Ecke"
        case .kantenmitte: return "Kantenmitte"
        case .kreismitte: return "Kreismitte"
        }
    }
}

/// Gefangener Punkt (Welt) und das Element, zu dem er gehört.
public struct Fangpunkt: Equatable, Sendable {
    public var welt: SIMD3<Float>
    public var art: FangArt
    public var ref: ElementRef
}

/// Ziel eines Messklicks: ein Element (exakt im Kernel) oder ein gefangener Punkt.
enum MessZiel: Equatable {
    case element(ElementRef)
    case punkt(Fangpunkt)

    var ref: ElementRef {
        switch self {
        case .element(let r): return r
        case .punkt(let f): return f.ref
        }
    }

    /// Referenz, die der Kernel exakt kennt: Elemente und Ecken (B-Rep-Punkte).
    var kernelRef: ElementRef? {
        switch self {
        case .element(let r): return r
        case .punkt(let f): return f.art == .ecke ? f.ref : nil
        }
    }
}

/// Vorschau im Messmodus (Überlagerung, nicht in der Liste).
struct MessVorschau {
    var items: [OverlayPrimitive] = []
    var text: String?
}

extension AppController {
    static let fangFarbe = ViewerStil.fangpunkt
    static let vorschauFarbe = ViewerStil.massVorschau

    // MARK: Darüberfahren

    func hoverGeaendert(_ pick: PickResult?, _ welt: SIMD3<Float>?, _ bildpunkt: CGPoint?) {
        mausMerken(pick, welt, bildpunkt)  // V2-5: fürs Lagebild
        guard model.measureMode else {
            if messVorschau != nil || aktuellerFang != nil {
                messVorschau = nil
                aktuellerFang = nil
                viewport.eingabe.unterMaus = nil
                refreshOverlay()
            }
            return
        }
        guard let pick, let bildpunkt, let ref = scene.resolve(pick) else {
            messVorschau = nil
            aktuellerFang = nil
            viewport.eingabe.unterMaus = nil
            refreshOverlay()
            return
        }
        messVorschauSetzen(ref, welt: welt, bildpunkt: bildpunkt)
    }

    /// Vorschau für das Element `ref` unter der Maus (Bildpunkt oben links); auch für den Selbsttest.
    func messVorschauSetzen(_ ref: ElementRef, welt: SIMD3<Float>? = nil, bildpunkt: CGPoint) {
        let fang = fangpunkt(nahe: bildpunkt, teil: ref.part)
        aktuellerFang = fang
        var v = MessVorschau()
        v.items = vorschauItems(ref, fang: fang)
        v.text = vorschauText(ref, fang: fang)
        // Erster Punkt gesetzt: Maß vom ersten Ziel zur Maus
        if let erstes = messZiele.first, let a = punkt(von: erstes) {
            let b = fang?.welt ?? welt ?? a
            if simd_distance(a, b) > 1e-4 {
                v.items.append(.dimension(a: a, b: b, text: GermanFormat.mm(Double(simd_distance(a, b))),
                                          color: Self.vorschauFarbe))
            }
        }
        messVorschau = v
        viewport.eingabe.unterMaus = v.text
        refreshOverlay()
    }

    /// Nächster Fangpunkt des Teils unter der Maus innerhalb des Fangradius (Bildschirm, Ursprung oben links).
    func fangpunkt(nahe maus: CGPoint, teil: String) -> Fangpunkt? {
        guard let rec = scene.record(teil) else { return nil }
        let projector = OverlayProjector(camera: viewport.camera, size: viewport.viewSize)
        let m = scene.worldTransform(teil)
        func w(_ p: SIMD3<Float>) -> SIMD3<Float> {
            let v = m * SIMD4(p, 1)
            return SIMD3(v.x, v.y, v.z)
        }
        var best: (Fangpunkt, CGFloat)?
        func pruefe(_ p: SIMD3<Float>, _ art: FangArt, _ ref: ElementRef) {
            let welt = w(p)
            guard let s = projector.project(welt) else { return }
            let d = hypot(s.x - maus.x, s.y - maus.y)
            // Ecken leicht bevorzugen (wie in CAD üblich), damit Kantenmitte und Ecke kurzer Kanten nicht flackern
            let gewicht = art == .ecke ? d * 0.85 : d
            guard gewicht <= ViewerStil.fangRadius else { return }
            if best == nil || gewicht < best!.1 { best = (Fangpunkt(welt: welt, art: art, ref: ref), gewicht) }
        }
        for v in 0..<rec.vertexCount { pruefe(rec.geometry.brepVertex(v), .ecke, .vertex(teil, v)) }
        for e in 0..<rec.edgeCount {
            let info = e < rec.header.edges.count ? rec.header.edges[e] : nil
            if info?.t == "circle", let c = info?.c, c.count >= 3 {
                pruefe(SIMD3(Float(c[0]), Float(c[1]), Float(c[2])), .kreismitte, .edge(teil, e))
            } else if info?.t == "line" || info == nil {
                let poly = rec.geometry.edgePolyline(e)
                if poly.count >= 2 { pruefe((poly.first! + poly.last!) / 2, .kantenmitte, .edge(teil, e)) }
            } else {
                let poly = rec.geometry.edgePolyline(e)
                if let mitte = Self.mitteNachLaenge(poly) { pruefe(mitte, .kantenmitte, .edge(teil, e)) }
            }
        }
        return best?.0
    }

    /// Punkt in der Mitte eines Polygonzugs (nach Länge).
    static func mitteNachLaenge(_ poly: [SIMD3<Float>]) -> SIMD3<Float>? {
        guard poly.count >= 2 else { return poly.first }
        var laenge: Float = 0
        for i in 1..<poly.count { laenge += simd_distance(poly[i - 1], poly[i]) }
        var rest = laenge / 2
        for i in 1..<poly.count {
            let d = simd_distance(poly[i - 1], poly[i])
            if d >= rest, d > 0 { return poly[i - 1] + (poly[i] - poly[i - 1]) * (rest / d) }
            rest -= d
        }
        return poly.last
    }

    private func weltpunkt(_ teil: String, _ p: SIMD3<Float>) -> SIMD3<Float> {
        let v = scene.worldTransform(teil) * SIMD4(p, 1)
        return SIMD3(v.x, v.y, v.z)
    }

    private func vorschauItems(_ ref: ElementRef, fang: Fangpunkt?) -> [OverlayPrimitive] {
        var out: [OverlayPrimitive] = []
        guard let rec = scene.record(ref.part) else { return out }
        if let fang {
            out.append(.badge(point: fang.welt, text: Self.fangZeichen(fang.art), color: Self.fangFarbe, filled: true))
            if fang.art == .kreismitte, case .edge(_, let e) = fang.ref.kindIndex {
                let poly = rec.geometry.edgePolyline(e).map { weltpunkt(ref.part, $0) }
                if poly.count >= 2 { out.append(.polyline(points: poly, color: Self.vorschauFarbe, width: 2.5)) }
            }
            return out
        }
        switch ref.kind {
        case .edge:
            let poly = rec.geometry.edgePolyline(ref.index).map { weltpunkt(ref.part, $0) }
            if poly.count >= 2 { out.append(.polyline(points: poly, color: Self.vorschauFarbe, width: 3)) }
            if ref.index < rec.header.edges.count, let c = rec.header.edges[ref.index].c, c.count >= 3,
                rec.header.edges[ref.index].t == "circle"
            {
                out.append(.dot(point: weltpunkt(ref.part, SIMD3(Float(c[0]), Float(c[1]), Float(c[2]))),
                                color: Self.vorschauFarbe, radius: 3))
            }
        case .vertex:
            if ref.index < rec.vertexCount {
                out.append(.dot(point: weltpunkt(ref.part, rec.geometry.brepVertex(ref.index)),
                                color: Self.vorschauFarbe, radius: 5))
            }
        case .face, .part:
            break
        }
        return out
    }

    static func fangZeichen(_ a: FangArt) -> String {
        switch a {
        case .ecke: return "□"
        case .kantenmitte: return "△"
        case .kreismitte: return "◎"
        }
    }

    /// Kurztext für die Hinweisleiste: Kreiskante Ø, Kantenlänge, Zylinder Ø, Fläche.
    private func vorschauText(_ ref: ElementRef, fang: Fangpunkt?) -> String? {
        guard let rec = scene.record(ref.part) else { return nil }
        if let fang {
            var t = fang.art.titel
            if fang.art == .kreismitte, case .edge(_, let e) = fang.ref.kindIndex, e < rec.header.edges.count,
                let r = rec.header.edges[e].r
            {
                t += " · Ø " + GermanFormat.mm(2 * r)
            }
            return t
        }
        switch ref.kind {
        case .edge:
            guard ref.index < rec.header.edges.count else { return "Kante" }
            let e = rec.header.edges[ref.index]
            if e.t == "circle", let r = e.r {
                return "Kreiskante Ø " + GermanFormat.mm(2 * r) + " · R " + GermanFormat.mm(r)
            }
            if let l = e.l { return GermanFormat.edgeType(e.t) + " · " + GermanFormat.mm(l) }
            return GermanFormat.edgeType(e.t)
        case .face:
            guard ref.index < rec.header.faces.count else { return "Fläche" }
            let f = rec.header.faces[ref.index]
            if (f.t == "cylinder" || f.t == "sphere"), let r = f.r {
                return GermanFormat.faceType(f.t) + " Ø " + GermanFormat.mm(2 * r)
            }
            if let a = f.a { return GermanFormat.faceType(f.t) + " · " + GermanFormat.mm2(a) }
            return GermanFormat.faceType(f.t)
        case .vertex:
            guard ref.index < rec.vertexCount else { return "Ecke" }
            return "Ecke " + GermanFormat.point(weltpunkt(ref.part, rec.geometry.brepVertex(ref.index)), decimals: 2)
        case .part:
            return nil
        }
    }

    /// Überlagerung der Vorschau (in `overlayItems()` angehängt).
    func messVorschauItems() -> [OverlayPrimitive] {
        guard model.measureMode else { return [] }
        var out = messVorschau?.items ?? []
        // Gesetzte, aber noch nicht gemessene Punkte
        for z in messZiele {
            if case .punkt(let f) = z {
                out.append(.badge(point: f.welt, text: Self.fangZeichen(f.art), color: ViewerStil.mass, filled: true))
            }
        }
        return out
    }

    // MARK: Klicken

    /// Klick im Messmodus: gefangener Punkt vor Element. Zwei Ziele: messen.
    func messKlick(_ ref: ElementRef?) {
        let ziel: MessZiel
        if let f = aktuellerFang {
            ziel = .punkt(f)
        } else if let ref, ref.kind != .part {
            ziel = .element(ref)
        } else {
            return
        }
        messZiele.append(ziel)
        let refs = messZiele.map(\.ref)
        measurePending = refs
        applySelection(refs)
        if messZiele.count >= 2 {
            let z = messZiele
            messZiele = []
            measurePending = []
            messen(z[0], z[1])
        }
        updateMeasureHint()
        refreshOverlay()
    }

    /// ↩ im Messmodus: das eine gewählte Ziel allein messen (Kreiskante: Radius und Durchmesser; Kante: Länge; Fläche:
    /// Inhalt). Bei einem Fangpunkt das Element, zu dem er gehört.
    func messungAbschliessen() {
        guard model.measureMode, messZiele.count == 1 else { return }
        let ref = messZiele[0].ref
        messZiele = []
        measurePending = []
        measure([ref])
        updateMeasureHint()
        refreshOverlay()
    }

    func messen(_ a: MessZiel, _ b: MessZiel) {
        // Zwei Elemente (oder Ecken): exakt im Kernel
        if let ra = a.kernelRef, let rb = b.kernelRef {
            measure([ra, rb])
            return
        }
        if let m = punktMessung(a, b) {
            addMeasurement(m)
            return
        }
        // Rückfall: das Element, zu dem der Punkt gehört (Kante der Mitte, Kreis der Kreismitte)
        measure([a.ref, b.ref])
    }

    /// Weltpunkt eines Ziels (für die Vorschau des Maßes): Fangpunkt bzw. Ankerpunkt des Elements.
    func punkt(von z: MessZiel) -> SIMD3<Float>? {
        switch z {
        case .punkt(let f): return f.welt
        case .element(let r): return scene.worldAnchor(of: r)
        }
    }

    /// Messung mit mindestens einem gefangenen Punkt, in der App gerechnet (Werte in mm wie der Kernel, drei Stellen).
    func punktMessung(_ a: MessZiel, _ b: MessZiel) -> MeasureResult? {
        let (p, anderes, refP) : (SIMD3<Float>, MessZiel, ElementRef)
        if case .punkt(let fa) = a {
            (p, anderes, refP) = (fa.welt, b, fa.ref)
        } else if case .punkt(let fb) = b {
            (p, anderes, refP) = (fb.welt, a, fb.ref)
        } else {
            return nil
        }
        let refs = [a.ref.string, b.ref.string]
        func ergebnis(_ q: SIMD3<Float>, _ was: String) -> MeasureResult {
            let d = q - p
            let dist = Double(simd_length(d))
            let teile = [("dx", d.x), ("dy", d.y), ("dz", d.z)].filter { abs($0.1) >= 0.0005 }
                .map { "\($0.0) \(GermanFormat.number(Double($0.1), decimals: 3))" }
            let text = "\(was) \(GermanFormat.number(dist, decimals: 3)) mm" + (teile.isEmpty ? "" : " (" + teile.joined(separator: ", ") + ")")
            return MeasureResult(
                refs: refs, run: scene.latestRun, kind: "distance",
                values: .object(["distance": .number(dist), "dx": .number(Double(d.x)), "dy": .number(Double(d.y)),
                                 "dz": .number(Double(d.z))]),
                points: [[Double(p.x), Double(p.y), Double(p.z)], [Double(q.x), Double(q.y), Double(q.z)]],
                text: text)
        }
        _ = refP
        switch anderes {
        case .punkt(let f):
            return ergebnis(f.welt, "Abstand")
        case .element(let r):
            guard let rec = scene.record(r.part) else { return nil }
            let m = scene.worldTransform(r.part)
            let rot = simd_float3x3(SIMD3(m.columns.0.x, m.columns.0.y, m.columns.0.z),
                                    SIMD3(m.columns.1.x, m.columns.1.y, m.columns.1.z),
                                    SIMD3(m.columns.2.x, m.columns.2.y, m.columns.2.z))
            func v3(_ a: [Double]?) -> SIMD3<Float>? {
                guard let a, a.count >= 3 else { return nil }
                return SIMD3(Float(a[0]), Float(a[1]), Float(a[2]))
            }
            switch r.kind {
            case .vertex:
                guard r.index < rec.vertexCount else { return nil }
                return ergebnis(weltpunkt(r.part, rec.geometry.brepVertex(r.index)), "Abstand")
            case .face:
                guard r.index < rec.header.faces.count else { return nil }
                let f = rec.header.faces[r.index]
                if f.t == "plane", let n0 = v3(f.n), let c0 = v3(f.c) {
                    let n = simd_normalize(rot * n0), c = weltpunkt(r.part, c0)
                    let q = p - n * simd_dot(p - c, n)
                    return ergebnis(q, "Abstand zur Ebene")
                }
                if f.t == "cylinder", let ax0 = v3(f.ax), let c0 = v3(f.c), let rad = f.r {
                    let ax = simd_normalize(rot * ax0), c = weltpunkt(r.part, c0)
                    let aufAchse = c + ax * simd_dot(p - c, ax)
                    let radial = p - aufAchse
                    guard simd_length(radial) > 1e-6 else { return nil }
                    let q = aufAchse + simd_normalize(radial) * Float(rad)
                    return ergebnis(q, "Abstand zur Zylinderfläche")
                }
                return nil
            case .edge:
                guard r.index < rec.header.edges.count else { return nil }
                let e = rec.header.edges[r.index]
                if e.t == "circle", let c0 = v3(e.c) {
                    return ergebnis(weltpunkt(r.part, c0), "Abstand zur Kreismitte")
                }
                let poly = rec.geometry.edgePolyline(r.index).map { weltpunkt(r.part, $0) }
                if e.t == "line", poly.count >= 2 {
                    let a0 = poly.first!, dir = poly.last! - poly.first!
                    let l2 = simd_length_squared(dir)
                    guard l2 > 1e-12 else { return nil }
                    // Lot auf die Strecke (am Ende auf den Endpunkt)
                    let t = min(max(simd_dot(p - a0, dir) / l2, 0), 1)
                    return ergebnis(a0 + dir * t, "Abstand zur Kante")
                }
                return nil
            case .part:
                return nil
            }
        }
    }
}

extension ElementRef {
    /// Art und Index für Muster (`case .edge(_, let e)`).
    enum KindIndex { case part, face(String, Int), edge(String, Int), vertex(String, Int) }

    var kindIndex: KindIndex {
        switch kind {
        case .part: return .part
        case .face: return .face(part, index)
        case .edge: return .edge(part, index)
        case .vertex: return .vertex(part, index)
        }
    }
}
