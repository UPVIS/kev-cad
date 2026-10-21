import Foundation
import OCCTSwiftViewport
import XCTest
import simd

@testable import KevCADCore

/// Phase 5 (Strang ANI): Decoder der Animationsnachrichten, Abspielen (Lage zur Zeit t), Zeitleiste im App-Kern und
/// ein kurzes Video.
@MainActor
final class AnimationTests: XCTestCase {
    private func clip() throws -> AnimationClip {
        guard case .animation(.definition(let c)) = try Fixtures.message("anim_def.frame") else {
            throw XCTSkip("anim_def.frame ist kein ANIM_DEF")
        }
        return c
    }

    private func expectedMatrix(_ key: String) throws -> simd_float4x4 {
        let exp = try XCTUnwrap(Fixtures.expected()["animations"]?["anim_def.frame"]?["matrices"]?[key]?.arrayValue)
        let rows = exp.compactMap { $0.arrayValue?.compactMap(\.doubleValue).map(Float.init) }
        XCTAssertEqual(rows.count, 4)
        // Zeilen aus JSON → Spalten für simd
        return simd_float4x4(rows: rows.map { SIMD4($0[0], $0[1], $0[2], $0[3]) })
    }

    private func assertClose(_ a: simd_float4x4, _ b: simd_float4x4, tol: Float = 1e-3, file: StaticString = #filePath,
                             line: UInt = #line) {
        for c in 0..<4 {
            for r in 0..<4 {
                XCTAssertEqual(a[c][r], b[c][r], accuracy: tol, "Spalte \(c), Zeile \(r)", file: file, line: line)
            }
        }
    }

    // MARK: Decoder

    func testAnimDefDecodesMatricesCameraAndVisibility() throws {
        let c = try clip()
        let exp = try XCTUnwrap(Fixtures.expected()["animations"]?["anim_def.frame"])
        XCTAssertEqual(c.name, "Fahrt")
        XCTAssertEqual(c.run, 4)
        XCTAssertEqual(c.frameCount, exp["bilder"]?.intValue)
        XCTAssertEqual(c.parts, exp["teile"]?.arrayValue?.compactMap(\.stringValue))
        XCTAssertEqual(c.parts, ["Wagen/Platte", "Wagen/Rad"])  // der Boden steht still
        XCTAssertEqual(c.duration, 1)
        XCTAssertEqual(c.fps, 4)
        XCTAssertTrue(c.isDefault)
        XCTAssertTrue(c.hasCamera)
        for k in [0, 2, 4] {
            for j in 0..<c.parts.count {
                assertClose(c.matrix(frame: k, part: j), try expectedMatrix("\(k)/\(j)"))
            }
        }
        // Rad: in der Mitte halbe Umdrehung (Strecke π · 50 bei Radius 50), am Ende volle Umdrehung plus π · 100
        let mid = c.matrix(frame: 2, part: 1)
        XCTAssertEqual(mid.columns.0.x, -1, accuracy: 1e-4)
        XCTAssertEqual(mid.columns.3.x, Float.pi * 50, accuracy: 1e-2)
        let end = c.matrix(frame: 4, part: 1)
        XCTAssertEqual(end.columns.0.x, 1, accuracy: 1e-4)
        XCTAssertEqual(end.columns.3.x, 314.159, accuracy: 1e-2)
        // Kamerafahrt: linear von (0, -1000, 500) nach (1000, -1000, 500), Bildwinkel nur am Ende
        let k0 = try XCTUnwrap(c.cameraKey(at: 0))
        XCTAssertEqual(k0.position, SIMD3(0, -1000, 500))
        let k2 = try XCTUnwrap(c.cameraKey(at: 0.5))
        XCTAssertEqual(k2.position.x, 500, accuracy: 1e-3)
        XCTAssertEqual(k2.target.x, 157, accuracy: 1e-3)
        XCTAssertEqual(try XCTUnwrap(c.cameraKey(at: 1)).fieldOfView, 40)
        // Sichtbarkeit: Rad ab 0,75 s ausgeblendet, davor sichtbar
        XCTAssertEqual(c.hiddenParts(at: 0.5), [])
        XCTAssertEqual(c.hiddenParts(at: 0.75), ["Wagen/Rad"])
    }

    func testOtherAnimationMessagesDecode() throws {
        guard case .animation(.collisions(let col)) = try Fixtures.message("anim_collisions.frame") else {
            return XCTFail("ANIM_COLLISIONS")
        }
        XCTAssertEqual(col.name, "Fahrt")
        XCTAssertEqual(col.replyTo, "a-12")
        XCTAssertEqual(col.collisions.count, 1)
        let k = col.collisions[0]
        XCTAssertEqual(k.parts, ["Wagen/Rad", "Boden"])
        XCTAssertEqual(k.from, 0.25)
        XCTAssertEqual(k.to, 0.5)
        XCTAssertEqual(k.frame, 2)
        XCTAssertEqual(k.depth, 1.5)
        XCTAssertEqual(k.frames, [1, 2])
        XCTAssertTrue(k.covers(time: 0.4, fps: 4))
        XCTAssertFalse(k.covers(time: 0.9, fps: 4))
        XCTAssertEqual(col.checkedFrames, 5)
        XCTAssertEqual(try Fixtures.message("anim_collisions.frame").replyTo, "a-12")

        guard case .animation(.remove(let name)) = try Fixtures.message("anim_remove.frame") else {
            return XCTFail("ANIM_REMOVE")
        }
        XCTAssertEqual(name, "Alt")
        guard case .animation(.play(let p)) = try Fixtures.message("anim_play.frame") else { return XCTFail("ANIM_PLAY") }
        XCTAssertEqual(p.id, "k-7")
        XCTAssertTrue(p.on && p.loop)
        XCTAssertEqual(p.speed, 0.5)
        guard case .animation(.seek(let s)) = try Fixtures.message("anim_seek.frame") else { return XCTFail("ANIM_SEEK") }
        XCTAssertEqual(s.time, 0.5)
        guard case .animation(.video(let v)) = try Fixtures.message("anim_video_req.frame") else {
            return XCTFail("ANIM_VIDEO_REQ")
        }
        XCTAssertEqual(v.width, 640)
        XCTAssertEqual(v.height, 360)
        XCTAssertEqual(v.format, "mp4")
        XCTAssertNil(v.camera)
        XCTAssertTrue(v.path.hasSuffix("output/animationen/Fahrt.mp4"))
    }

    func testOutgoingAnimationMessagesEncode() throws {
        let state = try JSONDecoder().decode(JSONValue.self, from: AnimationStateMessage(
            name: "Fahrt", time: 1.5, frame: 6, playing: true, loop: false, speed: 2).encodedHeader())
        XCTAssertEqual(state["type"]?.stringValue, "ANIM_STATE")
        XCTAssertEqual(state["zeit"]?.doubleValue, 1.5)
        XCTAssertEqual(state["spielt"]?.boolValue, true)
        let req = try JSONDecoder().decode(JSONValue.self, from: AnimationCollisionsRequestMessage(
            id: "a-3", name: "Fahrt", step: 2).encodedHeader())
        XCTAssertEqual(req["type"]?.stringValue, "ANIM_COLLISIONS_REQ")
        XCTAssertEqual(req["schritt"]?.intValue, 2)
        let res = try JSONDecoder().decode(JSONValue.self, from: AnimationVideoResponseMessage(
            replyTo: "k-9", ok: true, path: "/tmp/a.mp4", frames: 5, milliseconds: 80).encodedHeader())
        XCTAssertEqual(res["reply_to"]?.stringValue, "k-9")
        XCTAssertEqual(res["frames"]?.intValue, 5)
    }

    // MARK: Abspielen

    func testPoseAtTimeInterpolatesBetweenFrames() throws {
        let c = try clip()
        // zwischen Bild 0 und 1 (0,125 s): Rad um 45°, Wagen um π · 50 / 2 · … linear verschoben
        let pose = c.pose(at: 0.125)
        let rad = try XCTUnwrap(pose["Wagen/Rad"])
        let a = Float.pi / 4
        XCTAssertEqual(rad.columns.0.x, cos(a), accuracy: 1e-3)
        XCTAssertEqual(rad.columns.0.z, -sin(a), accuracy: 1e-3)
        let platte = try XCTUnwrap(pose["Wagen/Platte"])
        XCTAssertEqual(platte.columns.3.x, 314.159 / 8, accuracy: 1e-2)
        // Grenzen: vor 0 und nach dem Ende bleibt es beim ersten bzw. letzten Bild
        assertClose(try XCTUnwrap(c.pose(at: -1)["Wagen/Rad"]), c.matrix(frame: 0, part: 1))
        assertClose(try XCTUnwrap(c.pose(at: 5)["Wagen/Rad"]), c.matrix(frame: 4, part: 1))
    }

    /// Ein Teil weit weg vom Ursprung dreht sich schnell um die eigene Mitte: beim Überblenden zwischen zwei Bildern
    /// muss die Mitte stehen bleiben (lineares Mischen der Verschiebung ließe sie wandern).
    func testBlendKeepsPivotForFastSpin() throws {
        let c = SIMD3<Float>(1000, 0, 50)
        func spin(_ deg: Float) -> simd_float4x4 {
            let r = simd_float3x3(simd_quatf(angle: deg * .pi / 180, axis: SIMD3(0, 1, 0)))
            let t = c - r * c
            return simd_float4x4(SIMD4(r.columns.0, 0), SIMD4(r.columns.1, 0), SIMD4(r.columns.2, 0), SIMD4(t, 1))
        }
        let clip = AnimationClip(
            name: "Spin", duration: 1, fps: 1, frameCount: 2, parts: ["Rolle"],
            matrices: Self.pack(spin(0)) + Self.pack(spin(80)))
        let mid = try XCTUnwrap(clip.pose(at: 0.5, pivots: ["Rolle": c])["Rolle"])
        let moved = mid * SIMD4(c, 1)
        XCTAssertEqual(simd_distance(SIMD3(moved.x, moved.y, moved.z), c), 0, accuracy: 1e-2)
        assertClose(mid, spin(40), tol: 1e-3)
        // ohne Mitte wandert sie deutlich (deshalb gibt der App-Kern die Mitten mit)
        let naive = try XCTUnwrap(clip.pose(at: 0.5)["Rolle"]) * SIMD4(c, 1)
        XCTAssertGreaterThan(simd_distance(SIMD3(naive.x, naive.y, naive.z), c), 50)
    }

    func testPlayerClockLoopStepAndReset() throws {
        let model = AnimationModel()
        let player = AnimationPlayer(model: model)
        var clock: CFTimeInterval = 100
        player.now = { clock }
        var poses: [[String: simd_float4x4]] = []
        var states = 0
        player.onPose = { t, _, _, _ in poses.append(t) }
        player.onStateChange = { states += 1 }
        player.define(try clip())
        XCTAssertEqual(model.entries.map(\.name), ["Fahrt"])
        XCTAssertEqual(model.selected, "Fahrt")
        XCTAssertTrue(model.posed)

        player.play()
        XCTAssertTrue(model.playing)
        clock += 0.5
        player.tick()
        XCTAssertEqual(model.time, 0.5, accuracy: 1e-9)
        XCTAssertEqual(model.frame, 2)
        clock += 1.0  // über das Ende: ohne Schleife bleibt es stehen
        player.tick()
        XCTAssertEqual(model.time, 1)
        XCTAssertFalse(model.playing)

        player.setLoop(true)
        player.setSpeed(2)
        player.play()  // am Ende: von vorn
        XCTAssertEqual(model.time, 0)
        clock += 0.6  // doppelte Geschwindigkeit: 1,2 s → 0,2 s nach dem Umlauf
        player.tick()
        XCTAssertEqual(model.time, 0.2, accuracy: 1e-9)
        XCTAssertTrue(model.playing)
        player.pause()
        XCTAssertFalse(model.playing)

        player.jumpToStart()
        player.step(frames: 1)
        XCTAssertEqual(model.frame, 1)
        XCTAssertEqual(model.time, 0.25, accuracy: 1e-9)
        player.step(frames: 10)
        XCTAssertEqual(model.frame, 4)
        player.step(frames: -1)
        XCTAssertEqual(model.frame, 3)
        player.jumpToEnd()
        XCTAssertEqual(model.time, 1)
        let last = try XCTUnwrap(poses.last?["Wagen/Platte"])
        XCTAssertEqual(last.columns.3.x, 314.159, accuracy: 1e-2)

        player.resetPose()
        XCTAssertFalse(model.posed)
        XCTAssertEqual(poses.last?.isEmpty, true)
        XCTAssertGreaterThan(states, 5)

        player.remove("Fahrt")
        XCTAssertTrue(model.entries.isEmpty)
        XCTAssertNil(model.selected)
    }

    func testCollisionsMarkPairInMatchingFrames() throws {
        let model = AnimationModel()
        let player = AnimationPlayer(model: model)
        var lastCollision: Set<String> = []
        player.onPose = { _, _, col, _ in lastCollision = col }
        player.define(try clip())
        guard case .animation(.collisions(let col)) = try Fixtures.message("anim_collisions.frame") else {
            return XCTFail("ANIM_COLLISIONS")
        }
        player.setCollisions(col)
        XCTAssertEqual(model.collisions.count, 1)
        XCTAssertEqual(model.collisionState, .checked(frames: 5, milliseconds: 12.5))
        player.seek(to: 0.5)
        XCTAssertEqual(lastCollision, ["Wagen/Rad", "Boden"])
        XCTAssertEqual(model.activeCollisions.count, 1)
        player.seek(to: 1)
        XCTAssertEqual(lastCollision, [])
        XCTAssertTrue(model.activeCollisions.isEmpty)
        // neue Bewegung: alte Kollisionen gelten nicht mehr
        player.define(try clip())
        XCTAssertTrue(model.collisions.isEmpty)
        XCTAssertEqual(model.collisionState, .unchecked)
    }

    // MARK: App-Kern

    func testControllerPosesScenePartsWithMatricesOnly() throws {
        let c = AppController(model: AppModel())
        let box = try Fixtures.record("part_box.frame")  // "Grundplatte"
        c.handle([.part(box)])
        let bodiesBefore = c.scene.bodies.map(\.id)
        let move = simd_float4x4(translationX: 100)
        let clip = AnimationClip(
            name: "Schub", duration: 1, fps: 2, frameCount: 3, parts: ["Grundplatte"],
            matrices: [matrix_identity_float4x4, simd_float4x4(translationX: 50), move].flatMap(Self.pack),
            visibility: [AnimationVisibility(parts: ["Grundplatte"], events: [(0.9, false)])], isDefault: true)
        c.handleAnimation(.definition(clip))
        XCTAssertEqual(c.model.animation.entries.map(\.name), ["Schub"])
        c.seekAnimation(to: 0.5)
        XCTAssertEqual(c.scene.worldTransform("Grundplatte").columns.3.x, 50, accuracy: 1e-4)
        XCTAssertEqual(c.scene.bodies.first?.transform.columns.3.x ?? 0, 50, accuracy: 1e-4)
        XCTAssertEqual(c.scene.bodies.map(\.id), bodiesBefore)  // gleiche Körper, kein Neuvernetzen
        c.jumpToAnimationEnd()
        XCTAssertEqual(c.scene.worldTransform("Grundplatte").columns.3.x, 100, accuracy: 1e-4)
        XCTAssertEqual(c.scene.bodies.first?.isVisible, false)  // ab 0,9 s ausgeblendet
        c.stepAnimation(frames: -1)
        XCTAssertEqual(c.model.animation.frame, 1)
        XCTAssertEqual(c.scene.bodies.first?.isVisible, true)
        c.resetAnimationPose()
        XCTAssertEqual(c.scene.worldTransform("Grundplatte").columns.3.x, 0, accuracy: 1e-6)
        c.handleAnimation(.remove("Schub"))
        XCTAssertFalse(c.model.animation.hasAnimation)
    }

    static func pack(_ m: simd_float4x4) -> [Float] {
        [m.columns.0.x, m.columns.0.y, m.columns.0.z, m.columns.1.x, m.columns.1.y, m.columns.1.z,
         m.columns.2.x, m.columns.2.y, m.columns.2.z, m.columns.3.x, m.columns.3.y, m.columns.3.z]
    }

    // MARK: Video

    func testShortVideoWithFFmpeg() throws {
        guard AnimationVideoExporter.ffmpegPath() != nil else { throw XCTSkip("ffmpeg fehlt") }
        let s = SceneStore()
        s.upsert(try Fixtures.record("part_box.frame"), flash: false)
        let clip = AnimationClip(
            name: "Test", duration: 0.5, fps: 8, frameCount: 5, parts: ["Grundplatte"],
            matrices: (0..<5).flatMap { k in Self.pack(simd_float4x4(translationX: Float(k) * 3)) })
        let bounds = try XCTUnwrap(s.visibleBounds())
        let cam = ViewportCoordinator.fitted(StandardView.isometricFrontRight.cameraState(), to: bounds, aspect: 1.5)
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("kevcad-video-\(UUID().uuidString)")
        let out = dir.appendingPathComponent("Test.mp4")
        defer { try? FileManager.default.removeItem(at: dir) }
        let exporter = AnimationVideoExporter()
        let done = expectation(description: "Video")
        var result: Result<AnimationVideoExporter.Output, AnimationVideoExporter.ExportError>?
        var progress: [Int] = []
        let job = AnimationVideoExporter.Job(
            clip: clip, width: 96, height: 64, fps: 8, format: "mp4", output: out, camera: { _ in cam },
            bodies: { t in
                s.setAnimationPose(clip.pose(at: t))
                return s.snapshotBodies()
            }, displayMode: .shadedWithEdges, lighting: ViewportCoordinator.zUpLighting)
        exporter.export(job, progress: { k, _ in progress.append(k) }) { r in
            result = r
            done.fulfill()
        }
        wait(for: [done], timeout: 60)
        let output = try XCTUnwrap(try XCTUnwrap(result).get())
        XCTAssertEqual(output.frames, 5)
        XCTAssertEqual(progress, [1, 2, 3, 4, 5])
        let size = try XCTUnwrap(try FileManager.default.attributesOfItem(atPath: out.path)[.size] as? Int)
        XCTAssertGreaterThan(size, 500)
        // ffprobe zählt die Bilder, falls vorhanden
        let probe = URL(fileURLWithPath: AnimationVideoExporter.ffmpegPath()!).deletingLastPathComponent()
            .appendingPathComponent("ffprobe")
        if FileManager.default.isExecutableFile(atPath: probe.path) {
            let p = Process()
            p.executableURL = probe
            p.arguments = ["-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                           "stream=nb_read_frames,width,height,codec_name", "-of", "csv=p=0", out.path]
            let pipe = Pipe()
            p.standardOutput = pipe
            try p.run()
            p.waitUntilExit()
            let text = String(decoding: pipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
            XCTAssertTrue(text.contains("h264"), text)
            XCTAssertTrue(text.contains("96,64"), text)
            XCTAssertTrue(text.trimmingCharacters(in: .whitespacesAndNewlines).hasSuffix(",5"), text)
        }
    }

    func testFFmpegArguments() {
        let mp4 = AnimationVideoExporter.ffmpegArguments(width: 1920, height: 1080, fps: 30, format: "mp4", output: "/a.mp4")
        XCTAssertTrue(mp4.contains("libx264") && mp4.contains("1920x1080") && mp4.last == "/a.mp4")
        let pr = AnimationVideoExporter.ffmpegArguments(width: 1920, height: 1080, fps: 25, format: "prores", output: "/a.mov")
        XCTAssertTrue(pr.contains("prores_ks") && pr.contains("yuv422p10le"))
    }
}

extension simd_float4x4 {
    init(translationX x: Float) {
        self = matrix_identity_float4x4
        columns.3.x = x
    }
}
