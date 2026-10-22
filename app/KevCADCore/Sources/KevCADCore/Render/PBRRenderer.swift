import AppKit
import CoreGraphics
import Foundation
import ImageIO
import Metal
import RealityKit
import simd

/// Rendering „schnell“ (Phase 7, PLAN-PHASE7-RENDERINGS.md R1, R7): RealityKit offscreen (`RealityRenderer`, ab
/// macOS 15) mit PBR-Materialien, Bildbeleuchtung und Schatten.
///
/// Ablauf je Bild: drei Durchgänge in eigene Texturen – (C) nur die Teile auf durchsichtigem Grund, (A) Teile mit
/// beleuchtetem Boden, (B) nur der Boden. A / B ergibt die Schattenmaske (RealityKit hat auf dem Mac keinen
/// Schattenfänger), weichgezeichnet und über den Hintergrund gelegt (Farbe, unscharfe Umgebung oder durchsichtig),
/// darüber C. Modell in mm mit Z oben, RealityKit in m mit Y oben.
@MainActor
public final class PBRRenderer {
    public struct Teil {
        public var name: String
        public var geometry: PartGeometry
        /// Prüfsumme der Geometrie (Netze werden je Prüfsumme zwischengespeichert)
        public var digest: Int
        /// Weltlage in mm (Explosion, Animation)
        public var transform: simd_float4x4
        public var pbr: RenderPBR

        public init(name: String, geometry: PartGeometry, digest: Int, transform: simd_float4x4, pbr: RenderPBR) {
            self.name = name
            self.geometry = geometry
            self.digest = digest
            self.transform = transform
            self.pbr = pbr
        }
    }

    /// Kamera in Modellkoordinaten (mm, Z oben), immer perspektivisch.
    public struct Kamera: Equatable {
        public var position: SIMD3<Float>
        public var ziel: SIMD3<Float>
        public var oben: SIMD3<Float>
        /// vertikaler Öffnungswinkel in Grad
        public var fovGrad: Float

        public init(position: SIMD3<Float>, ziel: SIMD3<Float>, oben: SIMD3<Float>, fovGrad: Float) {
            self.position = position
            self.ziel = ziel
            self.oben = oben
            self.fovGrad = fovGrad
        }

        public var json: JSONValue {
            func v(_ p: SIMD3<Float>) -> JSONValue { .array([.number(Double(p.x)), .number(Double(p.y)), .number(Double(p.z))]) }
            return .object([
                "projection": .string("perspective"), "position": v(position), "target": v(ziel), "up": v(oben),
                "fov_deg": .number(Double(fovGrad)), "ortho_height_mm": .null,
            ])
        }
    }

    public struct Ergebnis {
        public var bild: CGImage
        public var png: Data
        public var phasen: [String: Int]
    }

    public enum Fehler: Error, LocalizedError {
        case metal, keineTeile, umgebung(String), rendern(String), png

        public var errorDescription: String? {
            switch self {
            case .metal: return "Metal ist nicht verfügbar"
            case .keineTeile: return "Keine sichtbaren Teile"
            case .umgebung(let t): return "Umgebung nicht lesbar: \(t)"
            case .rendern(let t): return "RealityKit: \(t)"
            case .png: return "PNG ließ sich nicht schreiben"
            }
        }
    }

    private var renderer: RealityRenderer?
    private let device = MTLCreateSystemDefaultDevice()
    private var netze: [String: MeshResource] = [:]
    private var umgebungen: [String: EnvironmentResource] = [:]
    private var hdrBilder: [String: HDRBild] = [:]
    private var texturen: [String: TextureResource] = [:]
    private var laeuft = false

    public init() {}

    /// Zwischenspeicher leeren (Projekt gewechselt, Speicher knapp).
    public func leeren() {
        netze.removeAll()
        texturen.removeAll()
    }

    // MARK: Rendern

    public func render(teile: [Teil], kamera: Kamera, szene: RenderSzene, width: Int, height: Int) async throws
        -> Ergebnis
    {
        while laeuft { try await Task.sleep(nanoseconds: 20_000_000) }  // ein Bild nach dem anderen
        laeuft = true
        defer { laeuft = false }
        guard let device else { throw Fehler.metal }
        guard !teile.isEmpty else { throw Fehler.keineTeile }
        let w = max(16, min(width, 8192)), h = max(16, min(height, 8192))
        var phasen: [String: Int] = [:]
        var t = Date()
        func phase(_ name: String) {
            phasen[name] = Int(Date().timeIntervalSince(t) * 1000)
            t = Date()
        }
        if renderer == nil {
            do { renderer = try RealityRenderer() } catch { throw Fehler.rendern(error.localizedDescription) }
        }
        guard let renderer else { throw Fehler.metal }

        // Welt: mm → m, Z oben → Y oben
        let welt = Entity()
        welt.transform = Transform(matrix: Self.modellNachRK)
        var lo = SIMD3<Float>(repeating: .greatestFiniteMagnitude), hi = -lo
        for teil in teile {
            guard teil.geometry.triangleCount > 0 else { continue }
            let achse = Self.laengsteAchse(teil.geometry)
            let mesh = try netz(teil, achse: achse)
            let e = ModelEntity(mesh: mesh, materials: [try material(teil.pbr)])
            e.transform = Transform(matrix: teil.transform)
            e.components.set(GroundingShadowComponent(castsShadow: true, receivesShadow: true))
            welt.addChild(e)
            let (a, b) = Self.grenzen(teil.geometry, teil.transform)
            lo = simd_min(lo, a)
            hi = simd_max(hi, b)
        }
        guard lo.x <= hi.x else { throw Fehler.keineTeile }
        phase("netze_ms")

        // Umgebung (Bildbeleuchtung) und Hintergrundbild
        let env: EnvironmentResource
        var hdr: HDRBild?
        if szene.licht == "umgebung", let pfad = szene.umgebung {
            hdr = try hdrBild(pfad)
            env = try umgebung(schluessel: pfad) { try Self.ladeCGImage(pfad) }
        } else {
            env = try umgebung(schluessel: "studio") { try Self.studioUmgebung() }
        }
        let iblStaerke: Float = szene.licht == "umgebung" ? Float(log2(max(szene.staerke, 0.05))) + 0.3 : 0.55
        renderer.lighting.resource = env
        renderer.lighting.intensityExponent = iblStaerke
        let ibl = Entity()
        var iblKomp = ImageBasedLightComponent(source: .single(env), intensityExponent: iblStaerke)
        iblKomp.inheritsRotation = true
        ibl.components.set(iblKomp)
        ibl.orientation = simd_quatf(angle: Float(szene.drehung) * .pi / 180, axis: [0, 1, 0])
        for case let m as ModelEntity in welt.children {
            m.components.set(ImageBasedLightReceiverComponent(imageBasedLight: ibl))
        }
        phase("umgebung_ms")

        // Licht: Hauptlicht mit Schatten (Studio wie in Blender von vorn links oben, sonst aus der hellsten Richtung)
        let mitte = (lo + hi) / 2
        let diag = max(simd_length(hi - lo), 1)
        var richtung = simd_normalize(SIMD3<Float>(-0.9, -1.1, 1.25))
        var lux: Float = 2600
        if let hdr, let sonne = hdr.hellsteRichtung(drehungGrad: Float(szene.drehung)), sonne.z > 0.12 {
            richtung = simd_normalize(sonne)
            lux = 1400 * Float(szene.staerke)
        } else if hdr != nil {
            richtung = simd_normalize(SIMD3<Float>(-0.4, -0.6, 1.4))
            lux = 900 * Float(szene.staerke)
        }
        let licht = DirectionalLight()
        licht.light.intensity = lux
        let rkMitte = Self.rk(mitte)
        let rkDiag = diag * 0.001
        licht.shadow = DirectionalLightComponent.Shadow(
            shadowProjection: .fixed(zNear: rkDiag * 0.05, zFar: rkDiag * 6, orthographicScale: rkDiag * 1.6),
            depthBias: 0.6)
        licht.look(at: rkMitte, from: rkMitte + Self.rkRichtung(richtung) * rkDiag * 3, relativeTo: nil)

        // Boden knapp unter dem tiefsten Punkt, weiß und matt (nur für die Schattenmaske)
        var bodenMat = PhysicallyBasedMaterial()
        bodenMat.baseColor = .init(tint: NSColor(white: 0.85, alpha: 1))
        bodenMat.roughness = 1.0
        bodenMat.metallic = 0.0
        let groesse = rkDiag * 40
        let boden = ModelEntity(mesh: .generatePlane(width: groesse, depth: groesse), materials: [bodenMat])
        boden.position = Self.rk(SIMD3(mitte.x, mitte.y, lo.z - diag * 0.0005))
        boden.components.set(GroundingShadowComponent(castsShadow: false, receivesShadow: true))
        boden.components.set(ImageBasedLightReceiverComponent(imageBasedLight: ibl))

        // Kamera
        let cam = Entity()
        let abstand = simd_length(kamera.ziel - kamera.position)
        let near = max(0.5, abstand - diag * 1.5) * 0.001 * 0.5
        cam.components.set(PerspectiveCameraComponent(
            near: max(near, 0.0005), far: (abstand + diag * 50) * 0.001, fieldOfViewInDegrees: kamera.fovGrad))
        cam.look(at: Self.rk(kamera.ziel), from: Self.rk(kamera.position), upVector: Self.rkRichtung(kamera.oben),
                 relativeTo: nil)

        renderer.entities.removeAll()
        renderer.entities.append(contentsOf: [welt, boden, licht, ibl, cam])
        renderer.activeCamera = cam
        renderer.cameraSettings.colorBackground = .color(CGColor(red: 0, green: 0, blue: 0, alpha: 0))
        renderer.cameraSettings.antialiasing = .multisample4X
        defer { renderer.entities.removeAll() }
        phase("szene_ms")

        // Drei Durchgänge
        let texC = try textur(device, w, h), texA = try textur(device, w, h), texB = try textur(device, w, h)
        boden.isEnabled = false
        try await durchgang(renderer, texC)
        let c = Self.lesen(texC, w, h)
        var a: [Float16] = [], b: [Float16] = []
        if szene.boden {
            boden.isEnabled = true
            try await durchgang(renderer, texA)
            a = Self.lesen(texA, w, h)
            welt.isEnabled = false
            try await durchgang(renderer, texB)
            b = Self.lesen(texB, w, h)
            welt.isEnabled = true
        }
        phase("rendern_ms")

        // Zusammensetzen und PNG abseits des Hauptfadens (bei 4K einige hundert ms Rechnen je Pixel)
        let mitBoden = szene.boden, transparent = szene.transparent
        let umgebungAlsHintergrund = szene.hintergrund == "umgebung"
        let farbe = szene.hintergrundFarbe ?? SIMD3(0.945, 0.949, 0.957)
        let drehung = Float(szene.drehung), staerke = Float(szene.staerke)
        let fertig = await Task.detached(priority: .userInitiated) { () -> (CGImage, Data)? in
            let schatten = mitBoden ? Self.schattenmaske(a: a, b: b, w: w, h: h) : [Float](repeating: 1, count: w * h)
            let hintergrund: Hintergrund
            if transparent {
                hintergrund = .durchsichtig
            } else if umgebungAlsHintergrund, let hdr {
                hintergrund = .bild(hdr.projektion(kamera: kamera, breite: w, hoehe: h, drehungGrad: drehung,
                                                   staerke: staerke))
            } else {
                hintergrund = .farbe(farbe)
            }
            let pixel = Self.zusammensetzen(c: c, schatten: schatten, hintergrund: hintergrund, w: w, h: h)
            guard let bild = Self.cgImage(pixel, w, h), let png = Self.pngDaten(bild) else { return nil }
            return (bild, png)
        }.value
        guard let (bild, png) = fertig else { throw Fehler.png }
        phase("png_ms")
        return Ergebnis(bild: bild, png: png, phasen: phasen)
    }

    private func durchgang(_ r: RealityRenderer, _ tex: MTLTexture) async throws {
        let out: RealityRenderer.CameraOutput
        do { out = try RealityRenderer.CameraOutput(.singleProjection(colorTexture: tex)) } catch {
            throw Fehler.rendern(error.localizedDescription)
        }
        // Zwei Bilder: im ersten sind Schattenkarte und Bildbeleuchtung womöglich noch nicht fertig
        for i in 0..<2 {
            let letztes = i == 1
            try await withCheckedThrowingContinuation { (k: CheckedContinuation<Void, Error>) in
                do {
                    try r.updateAndRender(deltaTime: 1.0 / 60, cameraOutput: out, onComplete: { _ in
                        k.resume()
                    })
                } catch {
                    k.resume(throwing: Fehler.rendern(error.localizedDescription))
                }
            }
            _ = letztes
        }
    }

    private func textur(_ device: MTLDevice, _ w: Int, _ h: Int) throws -> MTLTexture {
        let d = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .rgba16Float, width: w, height: h, mipmapped: false)
        d.usage = [.renderTarget, .shaderRead, .shaderWrite]
        d.storageMode = .shared
        guard let t = device.makeTexture(descriptor: d) else { throw Fehler.metal }
        return t
    }

    // MARK: Netze und Materialien

    private func netz(_ teil: Teil, achse: Int) throws -> MeshResource {
        let key = "\(teil.digest)|\(achse)"
        if let m = netze[key] { return m }
        let g = teil.geometry
        let n = g.vertexCount
        var pos = [SIMD3<Float>](), nor = [SIMD3<Float>](), uv = [SIMD2<Float>]()
        pos.reserveCapacity(n)
        nor.reserveCapacity(n)
        uv.reserveCapacity(n)
        for i in 0..<n {
            let p = SIMD3(g.positions[i * 3], g.positions[i * 3 + 1], g.positions[i * 3 + 2])
            var q = i * 3 + 2 < g.normals.count ? SIMD3(g.normals[i * 3], g.normals[i * 3 + 1], g.normals[i * 3 + 2])
                : SIMD3<Float>(0, 0, 1)
            if simd_length_squared(q) < 1e-12 { q = SIMD3(0, 0, 1) }
            pos.append(p)
            nor.append(simd_normalize(q))
            uv.append(Self.quaderUV(p, q, laengs: achse))
        }
        var d = MeshDescriptor(name: teil.name)
        d.positions = MeshBuffers.Positions(pos)
        d.normals = MeshBuffers.Normals(nor)
        d.textureCoordinates = MeshBuffers.TextureCoordinates(uv)
        d.primitives = .triangles(g.triangles)
        let m: MeshResource
        do { m = try MeshResource.generate(from: [d]) } catch { throw Fehler.rendern(error.localizedDescription) }
        if netze.count > 600 { netze.removeAll() }
        netze[key] = m
        return m
    }

    /// Quaderprojektion in mm: Ebene quer zur stärksten Normalenachse, die längste Achse des Teils wird u (Faser,
    /// Schliff); Deckflächen (Normale Z) bekommen v = 0, damit Schichtlinien nur an den Seiten erscheinen.
    nonisolated static func quaderUV(_ p: SIMD3<Float>, _ n: SIMD3<Float>, laengs: Int) -> SIMD2<Float> {
        let a = abs(n)
        let dominant = a.x >= a.y && a.x >= a.z ? 0 : (a.y >= a.z ? 1 : 2)
        let ebene = [0, 1, 2].filter { $0 != dominant }
        var u = p[ebene[0]], v = p[ebene[1]]
        if ebene[1] == laengs && ebene[1] != 2 { swap(&u, &v) }
        if dominant == 2 { v = 0 }
        return SIMD2(u, v)
    }

    nonisolated static func laengsteAchse(_ g: PartGeometry) -> Int {
        var lo = SIMD3<Float>(repeating: .greatestFiniteMagnitude), hi = -lo
        for i in stride(from: 0, to: g.positions.count - 2, by: 3) {
            let p = SIMD3(g.positions[i], g.positions[i + 1], g.positions[i + 2])
            lo = simd_min(lo, p)
            hi = simd_max(hi, p)
        }
        let s = hi - lo
        return s.x >= s.y && s.x >= s.z ? 0 : (s.y >= s.z ? 1 : 2)
    }

    nonisolated static func grenzen(_ g: PartGeometry, _ m: simd_float4x4) -> (SIMD3<Float>, SIMD3<Float>) {
        var lo = SIMD3<Float>(repeating: .greatestFiniteMagnitude), hi = -lo
        for i in stride(from: 0, to: g.positions.count - 2, by: 3) {
            let w = m * SIMD4(g.positions[i], g.positions[i + 1], g.positions[i + 2], 1)
            let p = SIMD3(w.x, w.y, w.z)
            lo = simd_min(lo, p)
            hi = simd_max(hi, p)
        }
        return (lo, hi)
    }

    func material(_ pbr: RenderPBR) throws -> PhysicallyBasedMaterial {
        var m = PhysicallyBasedMaterial()
        let c = pbr.basisfarbe
        let farbe = NSColor(srgbRed: CGFloat(c.x), green: CGFloat(c.y), blue: CGFloat(c.z), alpha: 1)
        m.baseColor = .init(tint: farbe)
        m.metallic = .init(floatLiteral: pbr.metallisch)
        m.roughness = .init(floatLiteral: max(0.04, pbr.rauheit))
        if pbr.klarlack > 0 {
            m.clearcoat = .init(floatLiteral: pbr.klarlack)
            m.clearcoatRoughness = .init(floatLiteral: pbr.klarlackRauheit)
        }
        if pbr.anisotropie > 0 { m.anisotropyLevel = .init(floatLiteral: pbr.anisotropie) }
        if pbr.durchsichtig > 0.01 {
            m.blending = .transparent(opacity: .init(floatLiteral: max(0.12, 1 - pbr.durchsichtig * 0.85)))
        }
        let wiederholen = Self.wiederholSampler
        switch pbr.oberflaeche {
        case "schichten":
            let tex = try textur("schichten") { try Self.schichtNormalen() }
            m.normal = .init(texture: .init(tex, sampler: wiederholen))
            let periode = max(0.05, pbr.schichthoehe) * 4  // vier Schichten je Textur
            m.textureCoordinateTransform = .init(scale: SIMD2(1 / periode, 1 / periode))
        case "holz":
            let tex = try textur("holz") { try Self.holzMaserung() }
            m.baseColor = .init(tint: farbe, texture: .init(tex, sampler: wiederholen))
            m.textureCoordinateTransform = .init(scale: SIMD2(1 / 240.0, 1 / 60.0))
        case "gebuerstet":
            let tex = try textur("gebuerstet") { try Self.schliffNormalen() }
            m.normal = .init(texture: .init(tex, sampler: wiederholen))
            m.textureCoordinateTransform = .init(scale: SIMD2(1 / 200.0, 1 / 8.0))
        default:
            break
        }
        return m
    }

    private static var wiederholSampler: MaterialParameters.Texture.Sampler {
        let d = MTLSamplerDescriptor()
        d.sAddressMode = .repeat
        d.tAddressMode = .repeat
        d.minFilter = .linear
        d.magFilter = .linear
        d.mipFilter = .linear
        d.maxAnisotropy = 8
        return MaterialParameters.Texture.Sampler(d)
    }

    private func textur(_ key: String, _ bauen: () throws -> (CGImage, TextureResource.Semantic)) throws -> TextureResource {
        if let t = texturen[key] { return t }
        let (bild, semantik) = try bauen()
        let t: TextureResource
        do { t = try TextureResource(image: bild, withName: key, options: .init(semantic: semantik)) } catch {
            throw Fehler.rendern("Textur \(key): \(error.localizedDescription)")
        }
        texturen[key] = t
        return t
    }

    private func umgebung(schluessel: String, _ bild: () throws -> CGImage) throws -> EnvironmentResource {
        if let e = umgebungen[schluessel] { return e }
        let e: EnvironmentResource
        do { e = try EnvironmentResource(equirectangular: try bild(), withName: nil) } catch let f as Fehler {
            throw f
        } catch {
            throw Fehler.umgebung(error.localizedDescription)
        }
        umgebungen[schluessel] = e
        return e
    }

    private func hdrBild(_ pfad: String) throws -> HDRBild {
        if let b = hdrBilder[pfad] { return b }
        let b = try HDRBild(cgImage: try Self.ladeCGImage(pfad), breite: 512, hoehe: 256)
        hdrBilder[pfad] = b
        return b
    }

    // MARK: Koordinaten

    /// Modell (mm, Z oben) → RealityKit (m, Y oben): (x, y, z) → (x, z, −y) · 0,001
    nonisolated static let modellNachRK: simd_float4x4 = {
        let r = simd_float4x4(simd_quatf(angle: -.pi / 2, axis: SIMD3(1, 0, 0)))
        return simd_float4x4(diagonal: SIMD4(0.001, 0.001, 0.001, 1)) * r
    }()

    nonisolated static func rk(_ p: SIMD3<Float>) -> SIMD3<Float> { SIMD3(p.x, p.z, -p.y) * 0.001 }
    nonisolated static func rkRichtung(_ d: SIMD3<Float>) -> SIMD3<Float> { SIMD3(d.x, d.z, -d.y) }

    // MARK: Bilder lesen und zusammensetzen

    nonisolated static func lesen(_ tex: MTLTexture, _ w: Int, _ h: Int) -> [Float16] {
        var px = [Float16](repeating: 0, count: w * h * 4)
        px.withUnsafeMutableBytes { buf in
            tex.getBytes(buf.baseAddress!, bytesPerRow: w * 8, from: MTLRegionMake2D(0, 0, w, h), mipmapLevel: 0)
        }
        return px
    }

    /// Schatten je Pixel (1 = kein Schatten): Helligkeit mit Teilen durch Helligkeit ohne Teile, nur wo Boden ist;
    /// weichgezeichnet (zweimal Kastenfilter).
    nonisolated static func schattenmaske(a: [Float16], b: [Float16], w: Int, h: Int) -> [Float] {
        var s = [Float](repeating: 1, count: w * h)
        for i in 0..<(w * h) {
            let ab = Float(b[i * 4 + 3])
            guard ab > 0.5 else { continue }
            let la = 0.2126 * Float(a[i * 4]) + 0.7152 * Float(a[i * 4 + 1]) + 0.0722 * Float(a[i * 4 + 2])
            let lb = 0.2126 * Float(b[i * 4]) + 0.7152 * Float(b[i * 4 + 1]) + 0.0722 * Float(b[i * 4 + 2])
            s[i] = lb > 1e-4 ? min(1, max(0, la / lb)) : 1
        }
        let r = max(1, min(w, h) / 220)
        kastenfilter(&s, w, h, r)
        kastenfilter(&s, w, h, r)
        return s
    }

    nonisolated static func kastenfilter(_ s: inout [Float], _ w: Int, _ h: Int, _ r: Int) {
        var tmp = s
        let n = Float(2 * r + 1)
        for y in 0..<h {
            let z = y * w
            var summe: Float = 0
            for x in -r...r { summe += s[z + min(max(x, 0), w - 1)] }
            for x in 0..<w {
                tmp[z + x] = summe / n
                summe += s[z + min(x + r + 1, w - 1)] - s[z + max(x - r, 0)]
            }
        }
        for x in 0..<w {
            var summe: Float = 0
            for y in -r...r { summe += tmp[min(max(y, 0), h - 1) * w + x] }
            for y in 0..<h {
                s[y * w + x] = summe / n
                summe += tmp[min(y + r + 1, h - 1) * w + x] - tmp[max(y - r, 0) * w + x]
            }
        }
    }

    enum Hintergrund {
        case farbe(SIMD3<Float>)  // sRGB
        case bild([SIMD3<Float>])  // linear, je Pixel
        case durchsichtig
    }

    /// C (vormultipliert, linear) über dem Hintergrund mit Schatten; Ergebnis 8 bit sRGB, vormultipliert.
    nonisolated static func zusammensetzen(c: [Float16], schatten: [Float], hintergrund: Hintergrund, w: Int, h: Int) -> [UInt8] {
        var out = [UInt8](repeating: 0, count: w * h * 4)
        let staerke: Float = 0.9
        var farbeLin = SIMD3<Float>(repeating: 1)
        if case .farbe(let f) = hintergrund { farbeLin = SIMD3(linear(f.x), linear(f.y), linear(f.z)) }
        for i in 0..<(w * h) {
            let ca = min(1, max(0, Float(c[i * 4 + 3])))
            let crgb = SIMD3(Float(c[i * 4]), Float(c[i * 4 + 1]), Float(c[i * 4 + 2]))
            let sch = 1 - (1 - schatten[i]) * staerke
            var rgb: SIMD3<Float>
            var alpha: Float
            switch hintergrund {
            case .farbe:
                rgb = crgb + (1 - ca) * farbeLin * sch
                alpha = 1
            case .bild(let bild):
                rgb = crgb + (1 - ca) * bild[i] * sch
                alpha = 1
            case .durchsichtig:
                let schattenAlpha = (1 - sch)
                rgb = crgb  // Schatten ist schwarz: trägt nur Deckung bei
                alpha = ca + (1 - ca) * schattenAlpha
            }
            let a = max(alpha, 1e-6)
            for k in 0..<3 {
                let gerade = min(1, max(0, rgb[k] / a))
                out[i * 4 + k] = UInt8(min(255, max(0, srgb(gerade) * a * 255 + 0.5)))
            }
            out[i * 4 + 3] = UInt8(min(255, max(0, alpha * 255 + 0.5)))
        }
        return out
    }

    nonisolated static func linear(_ v: Float) -> Float {
        let x = min(max(v, 0), 1)
        return x <= 0.04045 ? x / 12.92 : pow((x + 0.055) / 1.055, 2.4)
    }

    nonisolated static func srgb(_ v: Float) -> Float {
        let x = min(max(v, 0), 1)
        return x <= 0.0031308 ? x * 12.92 : 1.055 * pow(x, 1 / 2.4) - 0.055
    }

    nonisolated static func pngDaten(_ image: CGImage) -> Data? {
        let data = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(data as CFMutableData, "public.png" as CFString, 1, nil)
        else { return nil }
        CGImageDestinationAddImage(dest, image, nil)
        guard CGImageDestinationFinalize(dest) else { return nil }
        return data as Data
    }

    nonisolated static func cgImage(_ px: [UInt8], _ w: Int, _ h: Int) -> CGImage? {
        guard let space = CGColorSpace(name: CGColorSpace.sRGB) else { return nil }
        var daten = px
        return daten.withUnsafeMutableBytes { buf -> CGImage? in
            guard let ctx = CGContext(
                data: buf.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4, space: space,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
            else { return nil }
            return ctx.makeImage()
        }
    }

    // MARK: Umgebungen und Texturen erzeugen

    static func ladeCGImage(_ pfad: String) throws -> CGImage {
        guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: pfad) as CFURL, nil),
            let img = CGImageSourceCreateImageAtIndex(src, 0, nil)
        else { throw Fehler.umgebung(pfad) }
        return img
    }

    /// Studio: neutrales Grau, oben heller, dazu drei Softboxen (wie die Flächenlichter in Blender) für Glanzlichter.
    static func studioUmgebung() throws -> CGImage {
        let w = 512, h = 256
        var px = [Float](repeating: 0, count: w * h * 4)
        // Softboxen: Richtung (Modell, Z oben), halbe Breite und Höhe in Grad, Helligkeit
        let boxen: [(SIMD3<Float>, Float, Float, Float)] = [
            (simd_normalize(SIMD3(-0.9, -1.1, 1.25)), 22, 15, 9),
            (simd_normalize(SIMD3(1.3, -0.6, 0.5)), 26, 18, 3.5),
            (simd_normalize(SIMD3(0.4, 1.3, 1.1)), 16, 12, 6),
            (SIMD3(0, 0, 1), 30, 30, 2.5),
        ]
        for y in 0..<h {
            let v = 1 - (Float(y) + 0.5) / Float(h)  // 1 oben
            let el = (v - 0.5) * .pi
            for x in 0..<w {
                let u = (Float(x) + 0.5) / Float(w)
                let az = (u - 0.5) * 2 * .pi
                // Richtung wie Blender: u = atan2(y, −x) / 2π + 0,5
                let d = SIMD3<Float>(-cos(el) * cos(az), cos(el) * sin(az), sin(el))
                var c: Float = 0.32 + 0.38 * max(0, sin(el)) - 0.12 * max(0, -sin(el))
                for (r, bw, bh, hell) in boxen {
                    let winkel = acos(min(1, max(-1, simd_dot(d, r)))) * 180 / .pi
                    let grenze = (bw + bh) / 2
                    if winkel < grenze { c += hell * min(1, (grenze - winkel) / 4) }
                }
                let i = (y * w + x) * 4
                px[i] = c * 1.0
                px[i + 1] = c * 0.995
                px[i + 2] = c * 0.985
                px[i + 3] = 1
            }
        }
        return try floatBild(px, w, h)
    }

    static func floatBild(_ px: [Float], _ w: Int, _ h: Int) throws -> CGImage {
        guard let space = CGColorSpace(name: CGColorSpace.extendedLinearSRGB) else { throw Fehler.umgebung("Farbraum") }
        var daten = px
        let info = CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.floatComponents.rawValue
            | CGImageByteOrderInfo.order32Little.rawValue
        let bild = daten.withUnsafeMutableBytes { buf -> CGImage? in
            CGContext(data: buf.baseAddress, width: w, height: h, bitsPerComponent: 32, bytesPerRow: w * 16,
                      space: space, bitmapInfo: info)?.makeImage()
        }
        guard let bild else { throw Fehler.umgebung("Studio-Umgebung") }
        return bild
    }

    /// Normalen für Schichtlinien: vier Perioden einer Sinuswelle längs v.
    static func schichtNormalen() throws -> (CGImage, TextureResource.Semantic) {
        let w = 8, h = 32
        var px = [UInt8](repeating: 255, count: w * h * 4)
        for y in 0..<h {
            let phase = Float(y) / Float(h) * 4 * 2 * .pi
            let n = simd_normalize(SIMD3<Float>(0, -0.55 * cos(phase), 1))
            for x in 0..<w {
                let i = (y * w + x) * 4
                px[i] = UInt8((n.x * 0.5 + 0.5) * 255)
                px[i + 1] = UInt8((n.y * 0.5 + 0.5) * 255)
                px[i + 2] = UInt8((n.z * 0.5 + 0.5) * 255)
            }
        }
        return (try rgbBild(px, w, h, linear: true), .normal)
    }

    /// Normalen für Schliff: feine Riefen längs u mit zufälliger Tiefe.
    static func schliffNormalen() throws -> (CGImage, TextureResource.Semantic) {
        let w = 64, h = 256
        var px = [UInt8](repeating: 255, count: w * h * 4)
        var zufall = SystemRandomNumberGenerator()
        var hoehe = [Float](repeating: 0, count: h)
        for y in 0..<h { hoehe[y] = Float.random(in: -1...1, using: &zufall) }
        for y in 0..<h {
            let d = (hoehe[(y + 1) % h] - hoehe[(y + h - 1) % h]) * 0.25
            let n = simd_normalize(SIMD3<Float>(0, -d, 1))
            for x in 0..<w {
                let i = (y * w + x) * 4
                px[i] = UInt8((n.x * 0.5 + 0.5) * 255)
                px[i + 1] = UInt8((n.y * 0.5 + 0.5) * 255)
                px[i + 2] = UInt8((n.z * 0.5 + 0.5) * 255)
            }
        }
        return (try rgbBild(px, w, h, linear: true), .normal)
    }

    /// Holzmaserung: helle und dunkle Bänder längs u, mit Rauschen verzerrt (Graustufen, multipliziert mit der Farbe).
    static func holzMaserung() throws -> (CGImage, TextureResource.Semantic) {
        let w = 512, h = 256
        var px = [UInt8](repeating: 255, count: w * h * 4)
        func rauschen(_ x: Float, _ y: Float) -> Float {
            sin(x * 0.021 + sin(y * 0.05) * 1.7) * 0.6 + sin(x * 0.053 + y * 0.011) * 0.4
        }
        for y in 0..<h {
            for x in 0..<w {
                let fx = Float(x), fy = Float(y)
                let ringe = fy * 0.32 + rauschen(fx, fy) * 2.4
                let band = 0.5 + 0.5 * sin(ringe)
                let fein = 0.5 + 0.5 * sin(fy * 2.1 + rauschen(fx * 3, fy) * 0.8)
                let wert = 0.80 + 0.14 * pow(band, 3) + 0.06 * fein
                let i = (y * w + x) * 4
                let v = UInt8(min(255, max(0, wert * 255)))
                px[i] = v
                px[i + 1] = UInt8(min(255, Float(v) * 0.985))
                px[i + 2] = UInt8(min(255, Float(v) * 0.96))
            }
        }
        return (try rgbBild(px, w, h, linear: false), .color)
    }

    static func rgbBild(_ px: [UInt8], _ w: Int, _ h: Int, linear: Bool) throws -> CGImage {
        guard let space = CGColorSpace(name: linear ? CGColorSpace.linearSRGB : CGColorSpace.sRGB) else {
            throw Fehler.rendern("Farbraum")
        }
        var daten = px
        let bild = daten.withUnsafeMutableBytes { buf -> CGImage? in
            CGContext(data: buf.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                      space: space, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)?.makeImage()
        }
        guard let bild else { throw Fehler.rendern("Textur") }
        return bild
    }
}

/// Verkleinerte Umgebung (linear, Z oben, Abbildung wie Blender) für den unscharfen Hintergrund und die Sonne.
struct HDRBild {
    let breite: Int
    let hoehe: Int
    let px: [SIMD3<Float>]

    init(cgImage: CGImage, breite: Int, hoehe: Int) throws {
        self.breite = breite
        self.hoehe = hoehe
        guard let space = CGColorSpace(name: CGColorSpace.extendedLinearSRGB) else {
            throw PBRRenderer.Fehler.umgebung("Farbraum")
        }
        var f = [Float](repeating: 0, count: breite * hoehe * 4)
        let info = CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.floatComponents.rawValue
            | CGImageByteOrderInfo.order32Little.rawValue
        let ok = f.withUnsafeMutableBytes { buf -> Bool in
            guard let ctx = CGContext(data: buf.baseAddress, width: breite, height: hoehe, bitsPerComponent: 32,
                                      bytesPerRow: breite * 16, space: space, bitmapInfo: info)
            else { return false }
            ctx.interpolationQuality = .high
            ctx.draw(cgImage, in: CGRect(x: 0, y: 0, width: breite, height: hoehe))
            return true
        }
        guard ok else { throw PBRRenderer.Fehler.umgebung("HDR verkleinern") }
        // Unschärfe wie in Blender (Richtung leicht verrauscht): je Kanal zweimal Kastenfilter, etwa 1,5°
        var kanaele = (0..<3).map { k in (0..<(breite * hoehe)).map { f[$0 * 4 + k] } }
        for k in 0..<3 {
            PBRRenderer.kastenfilter(&kanaele[k], breite, hoehe, 2)
            PBRRenderer.kastenfilter(&kanaele[k], breite, hoehe, 2)
        }
        var p = [SIMD3<Float>](repeating: .zero, count: breite * hoehe)
        for i in 0..<(breite * hoehe) { p[i] = SIMD3(kanaele[0][i], kanaele[1][i], kanaele[2][i]) }
        px = p
    }

    /// Wert in Richtung `d` (Modell, Z oben), bilinear; Zeile 0 ist oben.
    func wert(_ d: SIMD3<Float>) -> SIMD3<Float> {
        let u = atan2(d.y, -d.x) / (2 * .pi) + 0.5
        let v = atan2(d.z, (d.x * d.x + d.y * d.y).squareRoot()) / .pi + 0.5
        let fx = u * Float(breite) - 0.5
        let fy = (1 - v) * Float(hoehe) - 0.5
        let x0 = Int(floor(fx)), y0 = Int(floor(fy))
        let tx = fx - Float(x0), ty = fy - Float(y0)
        func p(_ x: Int, _ y: Int) -> SIMD3<Float> {
            let xx = ((x % breite) + breite) % breite
            let yy = min(max(y, 0), hoehe - 1)
            return px[yy * breite + xx]
        }
        let a = p(x0, y0) * (1 - tx) + p(x0 + 1, y0) * tx
        let b = p(x0, y0 + 1) * (1 - tx) + p(x0 + 1, y0 + 1) * tx
        return a * (1 - ty) + b * ty
    }

    /// Hintergrund durch die Kamera: je Pixel die Umgebung in Blickrichtung (linear).
    func projektion(kamera k: PBRRenderer.Kamera, breite w: Int, hoehe h: Int, drehungGrad: Float,
                    staerke: Float) -> [SIMD3<Float>] {
        let vor = simd_normalize(k.ziel - k.position)
        var rechts = simd_cross(vor, k.oben)
        if simd_length(rechts) < 1e-6 { rechts = SIMD3(1, 0, 0) }
        rechts = simd_normalize(rechts)
        let oben = simd_normalize(simd_cross(rechts, vor))
        let t = tan(k.fovGrad * .pi / 360)
        let aspekt = Float(w) / Float(h)
        let dreh = simd_quatf(angle: -drehungGrad * .pi / 180, axis: SIMD3(0, 0, 1))
        var out = [SIMD3<Float>](repeating: .zero, count: w * h)
        for y in 0..<h {
            let ny = 1 - 2 * (Float(y) + 0.5) / Float(h)
            for x in 0..<w {
                let nx = 2 * (Float(x) + 0.5) / Float(w) - 1
                let d = simd_normalize(vor + rechts * (nx * t * aspekt) + oben * (ny * t))
                out[y * w + x] = wert(dreh.act(d)) * staerke
            }
        }
        return out
    }

    /// Richtung des hellsten Bereichs (Sonne, Fenster, Lampe) in Modellkoordinaten.
    func hellsteRichtung(drehungGrad: Float) -> SIMD3<Float>? {
        var best = -Float.greatestFiniteMagnitude, bi = 0
        for (i, c) in px.enumerated() {
            let l = 0.2126 * c.x + 0.7152 * c.y + 0.0722 * c.z
            if l > best {
                best = l
                bi = i
            }
        }
        guard best > 0 else { return nil }
        let x = bi % breite, y = bi / breite
        let u = (Float(x) + 0.5) / Float(breite), v = 1 - (Float(y) + 0.5) / Float(hoehe)
        let az = (u - 0.5) * 2 * .pi, el = (v - 0.5) * .pi
        let d = SIMD3<Float>(-cos(el) * cos(az), cos(el) * sin(az), sin(el))
        return simd_quatf(angle: drehungGrad * .pi / 180, axis: SIMD3(0, 0, 1)).act(d)
    }
}
