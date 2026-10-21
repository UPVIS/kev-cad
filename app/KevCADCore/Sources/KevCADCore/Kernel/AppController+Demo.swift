import Foundation

// Demomodus (KEVCAD_DEMO=1): kein Kernel, ein kleiner Wandhalter baut sich wie bei einem echten Lauf auf.

extension AppController {
    func startDemo() {
        model.kernelState = .ready
        log(.info, "Demomodus: kein Kernel, Beispielteile")
        demoOpen(AppInfo.projectsDirectory.appendingPathComponent("Demo", isDirectory: true))
    }

    func demoOpen(_ url: URL) {
        handle(.project(demoProject(url)))
        demoRun()
    }

    private func demoProject(_ url: URL) -> ProjectMessage {
        let json = """
            {"type":"PROJECT","path":\(Self.jsonString(url.path)),"name":\(Self.jsonString(url.lastPathComponent)),
             "model":\(Self.jsonString(url.appendingPathComponent("model.py").path))}
            """
        // swiftlint:disable:next force_try
        return try! JSONDecoder().decode(ProjectMessage.self, from: Data(json.utf8))
    }

    static func jsonString(_ s: String) -> String {
        String(decoding: (try? JSONEncoder().encode(s)) ?? Data("\"\"".utf8), as: UTF8.self)
    }

    func demoRun() {
        let run = scene.latestRun + 1
        let parts = DemoScene.parts(run: run)
        let delay = model.slowMotion ? Double(Self.slowMotionMs) / 1000 : 0.25
        func decode<T: Decodable>(_ t: T.Type, _ json: String) -> T? { try? JSONDecoder().decode(t, from: Data(json.utf8)) }
        if let m = decode(RunStartMessage.self, #"{"run":\#(run),"slow_ms":0}"#) { handle(.runStart(m)) }
        for (i, p) in parts.enumerated() {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay * Double(i + 1)) { [weak self] in
                MainActor.assumeIsolated {
                    guard let self else { return }
                    if let s = decode(StepMessage.self, #"{"run":\#(run),"index":\#(i + 1),"text":\#(Self.jsonString(p.step))}"#) {
                        self.handle(.step(s))
                    }
                    self.handle(.partUpsert(p.header, p.geometry))
                }
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + delay * Double(parts.count + 1)) { [weak self] in
            MainActor.assumeIsolated {
                guard let self else { return }
                let json = #"{"run":\#(run),"duration_ms":\#(Int(delay * 1000) * parts.count),"parts":\#(parts.count),"triangles":0,"warnings":[]}"#
                if let m = decode(RunEndMessage.self, json) { self.handle(.runEnd(m)) }
            }
        }
    }
}
