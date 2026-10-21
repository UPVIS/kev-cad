import CaptureCore
import Foundation

let usage = """
kevcad-capture – Referenz aus einem Handyvideo mit Apple Object Capture (Kev CAD, Phase 4)

Aufruf:
  kevcad-capture lauf <video> --aus <ordner> [Optionen]      Bilder + Rekonstruktion + Nachbearbeitung
  kevcad-capture bilder <video> --aus <ordner> [Optionen]    nur Bilder auswählen
  kevcad-capture rekonstruktion <ordner> [Optionen]          Object Capture auf <ordner>/bilder
  kevcad-capture nachbearbeitung <ordner> [Optionen]         Boden, Ausrichtung, Maßstab, Bericht neu

Bilder:
  --bilder N            Anzahl Bilder (Standard 80, sinnvoll 60–150)
  --kante PX            lange Kante der Bilder (Standard 1920; 0 = Original)
  --brennweite35 MM     35-mm-äquivalente Brennweite in die EXIF-Daten schreiben (nur wenn bekannt)
  --von S, --bis S      nur diesen Abschnitt des Videos verwenden (Sekunden)
Rekonstruktion:
  --detail D            preview | reduced | medium | full | raw (Standard reduced)
  --ohne-maske          Objektmaskierung aus (Boden und Umgebung bleiben im Netz)
  --hohe-empfindlichkeit  featureSensitivity high (texturarme Gegenstände, langsamer)
  --ungeordnet          sampleOrdering unordered statt sequential
  --roh-usdz            zusätzlich die USDZ von Object Capture (ohne Maßstab, kostet 5–17 s)
  --ohne-usdz           kein netz_mm.usdz (nur OBJ)
  --posen-zuerst        Posen vorab in eigener Anfrage (poses.json nach ~50 % der Zeit, Lauf ~40 % länger)
Nachbearbeitung:
  --masz NAME=MM        bekanntes Maß: laenge (längste waagrechte Ausdehnung), breite, hoehe,
                        grund_laenge, grund_breite (dichteste waagrechte Schicht, z. B. ein Rahmen)
  --pruef NAME=MM       Prüfmaß zur Genauigkeitsangabe (Namen wie --masz, dazu rad), z. B. breite=410
  --ohne-boden-schnitt  Boden finden und ausrichten, aber nichts abschneiden
  --kontrollbilder ORDNER  Kontrollbilder (vorne, Seite, oben, schräg) mit Blender dorthin rendern
Allgemein:
  --kopie ORDNER        poses.json sofort und alle Ergebnisse am Ende zusätzlich dorthin kopieren
  --behalte-checkpoint  Zwischenstände von Object Capture nicht löschen
  --leise               keine Hinweise auf stderr (JSON-Zeilen auf stdout bleiben)

Ausgabe: JSON-Zeilen auf stdout (event: start, video, progress, stage, file, warning, error, done).
"""

struct Args {
    var command = ""
    var input: URL?
    var out: URL?
    var extraction = ExtractionOptions()
    var recon = ReconstructionOptions()
    var post = PostProcessOptions()
    var copyTo: URL?
    var keepCheckpoint = false
}

func parse() throws -> Args {
    var a = Args()
    var it = CommandLine.arguments.dropFirst().makeIterator()
    func value(_ name: String) throws -> String {
        guard let v = it.next() else { throw CaptureError.message("\(name) braucht einen Wert") }
        return v
    }
    func measure(_ s: String) throws -> (String, Double) {
        let parts = s.split(separator: "=", maxSplits: 1).map(String.init)
        guard parts.count == 2, let mm = Double(parts[1].replacingOccurrences(of: ",", with: ".")), mm > 0 else {
            throw CaptureError.message("Maß als NAME=MM angeben, z. B. laenge=610")
        }
        return (parts[0].lowercased().replacingOccurrences(of: "ä", with: "ae").replacingOccurrences(of: "ö", with: "oe"), mm)
    }
    while let arg = it.next() {
        switch arg {
        case "-h", "--hilfe", "--help": print(usage); exit(0)
        case "--aus", "-o": a.out = URL(fileURLWithPath: try value(arg)).standardizedFileURL
        case "--bilder": a.extraction.count = Int(try value(arg)) ?? 80
        case "--kante": a.extraction.longEdge = Int(try value(arg)) ?? 1920
        case "--brennweite35": a.extraction.focal35mm = Double(try value(arg))
        case "--von": a.extraction.start = Double(try value(arg).replacingOccurrences(of: ",", with: ".")) ?? 0
        case "--bis": a.extraction.end = Double(try value(arg).replacingOccurrences(of: ",", with: "."))
        case "--detail":
            let v = try value(arg)
            guard let d = ReconstructionOptions.detail(named: v) else { throw CaptureError.message("Unbekannte Detailstufe \(v)") }
            a.recon.detail = d
        case "--ohne-maske": a.recon.objectMasking = false
        case "--hohe-empfindlichkeit": a.recon.highSensitivity = true
        case "--ungeordnet": a.recon.sequential = false
        case "--roh-usdz": a.recon.writeUSDZ = true
        case "--ohne-usdz": a.post.writeUSDZ = false
        case "--posen-zuerst": a.recon.posesFirst = true
        case "--masz", "--maß":
            let (n, mm) = try measure(try value(arg))
            a.post.known = KnownMeasure(name: n, mm: mm)
        case "--pruef", "--prüf":
            let (n, mm) = try measure(try value(arg))
            a.post.checks.append(KnownMeasure(name: n, mm: mm))
        case "--ohne-boden-schnitt": a.post.cutFloor = false
        case "--kontrollbilder": a.post.previewDir = URL(fileURLWithPath: try value(arg)).standardizedFileURL
        case "--kopie": a.copyTo = URL(fileURLWithPath: try value(arg)).standardizedFileURL
        case "--behalte-checkpoint": a.keepCheckpoint = true
        case "--leise": ProgressLog.shared.quiet = true
        default:
            if arg.hasPrefix("-") { throw CaptureError.message("Unbekannte Option \(arg)") }
            if a.command.isEmpty { a.command = arg }
            else if a.input == nil { a.input = URL(fileURLWithPath: arg).standardizedFileURL }
            else { throw CaptureError.message("Überzähliges Argument \(arg)") }
        }
    }
    return a
}

func copyResult(_ layout: Layout, to dest: URL?, names: [String]) {
    guard let dest else { return }
    // Texturen eines früheren Laufs (andere Dateinamen) entfernen
    let fm = FileManager.default
    if let old = try? fm.contentsOfDirectory(atPath: dest.path) {
        for f in old where f.hasPrefix("baked_mesh_") && f.hasSuffix(".png") && !names.contains(f) {
            try? fm.removeItem(at: dest.appendingPathComponent(f))
        }
    }
    var copied: [String] = []
    for n in names {
        let src = layout.root.appendingPathComponent(n)
        guard FileManager.default.fileExists(atPath: src.path) else { continue }
        do {
            try Files.copyReplacing(src, to: dest.appendingPathComponent(n))
            copied.append(n)
        } catch {
            ProgressLog.shared.warn("Kopie von \(n) nach \(dest.path) fehlgeschlagen: \(error.localizedDescription)")
        }
    }
    ProgressLog.shared.emit("copied", ["dest": dest.path, "items": copied])
}

/// poses.json auf die Bilder im Kopie-Ordner umschreiben (Pfade zeigen dann dorthin).
func copyPoses(_ layout: Layout, to dest: URL?) {
    guard let dest else { return }
    do {
        try FileManager.default.createDirectory(at: dest, withIntermediateDirectories: true)
        let fm = FileManager.default
        let destImages = dest.appendingPathComponent("bilder", isDirectory: true)
        try fm.createDirectory(at: destImages, withIntermediateDirectories: true)
        for f in try fm.contentsOfDirectory(atPath: layout.images.path) where f.hasSuffix(".jpg") {
            let d = destImages.appendingPathComponent(f)
            if fm.fileExists(atPath: d.path) { try fm.removeItem(at: d) }
            try fm.copyItem(at: layout.images.appendingPathComponent(f), to: d)
        }
        // überzählige Bilder eines früheren Laufs entfernen
        let current = Set(try fm.contentsOfDirectory(atPath: layout.images.path))
        for f in try fm.contentsOfDirectory(atPath: destImages.path) where !current.contains(f) {
            try fm.removeItem(at: destImages.appendingPathComponent(f))
        }
        // Bildpfade auf den Kopie-Ordner umschreiben
        var root = (try JSONSerialization.jsonObject(with: Data(contentsOf: layout.poses)) as? [String: Any]) ?? [:]
        root["images_dir"] = destImages.path
        if var cams = root["cameras"] as? [[String: Any]] {
            for i in cams.indices {
                if let img = cams[i]["image"] as? String { cams[i]["path"] = destImages.appendingPathComponent(img).path }
            }
            root["cameras"] = cams
        }
        try JSONSerialization.data(withJSONObject: root, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
            .write(to: dest.appendingPathComponent("poses.json"), options: .atomic)
        try Files.copyReplacing(layout.imagesJSON, to: dest.appendingPathComponent("bilder.json"))
        ProgressLog.shared.emit("file", ["kind": "poses_copy", "path": dest.appendingPathComponent("poses.json").path])
    } catch {
        ProgressLog.shared.warn("poses.json nicht kopiert: \(error.localizedDescription)")
    }
}

func runExtraction(_ a: Args, _ layout: Layout) async throws -> ExtractionResult {
    guard let video = a.input else { throw CaptureError.message("Video fehlt") }
    if FileManager.default.fileExists(atPath: layout.images.path) {
        try FileManager.default.removeItem(at: layout.images)
    }
    let r = try await FrameExtractor().extract(video: video, to: layout.images, options: a.extraction)
    ProgressLog.shared.info("\(r.frames.count) Bilder aus \(r.frameCount) ausgewählt in \(String(format: "%.1f", r.seconds)) s")
    ProgressLog.shared.emit("frames_done", ["count": r.frames.count, "decoded": r.frameCount, "seconds": r.seconds,
                                            "dir": layout.images.path])
    return r
}

func runReconstruction(_ a: Args, _ layout: Layout, extractionSeconds: Double?) async throws {
    let log = ProgressLog.shared
    let infos = Files.imageInfos(layout: layout)
    let meta: [String: Any] = [
        "source": "Apple Object Capture (PhotogrammetrySession)",
        "os": ProcessInfo.processInfo.operatingSystemVersionString,
        "images_dir": layout.images.path,
        "detail": ReconstructionOptions.name(of: a.recon.detail),
        "object_masking": a.recon.objectMasking,
        "sequential": a.recon.sequential,
    ]
    func writePoses(_ r: ReconstructionResult) throws {
        try FileManager.default.createDirectory(at: layout.raw, withIntermediateDirectories: true)
        try PosesWriter.write(poses: r.poses, images: infos, imageDir: layout.images, meta: meta, aligned: nil,
                              to: layout.rawPoses)
        try PosesWriter.write(poses: r.poses, images: infos, imageDir: layout.images, meta: meta, aligned: nil,
                              to: layout.poses)
        log.emit("file", ["kind": "poses", "path": layout.poses.path, "cameras": r.poses.count,
                          "images": infos.count])
        copyPoses(layout, to: a.copyTo)
    }
    if FileManager.default.fileExists(atPath: layout.raw.path) { try FileManager.default.removeItem(at: layout.raw) }
    let r = try await Reconstructor().run(
        images: layout.images, rawDir: layout.raw, checkpoint: layout.checkpoint, options: a.recon,
        onPoses: writePoses,
        onPointCloud: { r in
            try PLYWriter.write(points: r.points, colors: r.colors, to: layout.rawPLY)
            log.emit("file", ["kind": "point_cloud_raw", "path": layout.rawPLY.path, "points": r.points.count])
        })
    let cpSize = Files.directorySize(layout.checkpoint)
    if !a.keepCheckpoint { try? FileManager.default.removeItem(at: layout.checkpoint) }
    var times: [String: Any] = ["reconstruction_s": r.seconds, "stages_s": r.stageSeconds,
                                "poses_after_s": r.posesAt ?? NSNull(), "checkpoint_bytes": cpSize]
    if let e = extractionSeconds { times["extraction_s"] = e }
    let rec: [String: Any] = [
        "detail": ReconstructionOptions.name(of: a.recon.detail), "object_masking": a.recon.objectMasking,
        "images": infos.count, "posed": r.poses.count, "points": r.points.count,
        "skipped": r.skipped, "invalid": r.invalid.map { ["sample": $0.key, "reason": $0.value] },
        "times": times, "obj_dir": r.objDir?.path ?? NSNull(), "usdz": r.usdz?.path ?? NSNull(),
    ]
    try JSONSerialization.data(withJSONObject: rec, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]).write(to: layout.reconstructionJSON)
    log.info("Rekonstruktion fertig in \(String(format: "%.1f", r.seconds)) s (Posen nach \(String(format: "%.1f", r.posesAt ?? -1)) s, Zwischenstände \(cpSize / 1_000_000) MB)")
    log.emit("reconstruction_done", rec)
}

func runPost(_ a: Args, _ layout: Layout) throws {
    let report = try PostProcessor(layout: layout, options: a.post).run()
    copyPoses(layout, to: a.copyTo)
    copyResult(layout, to: a.copyTo, names: ["roh", "netz_mm.obj", "netz_mm.mtl", "netz_mm.usdz", "punktwolke_mm.ply",
                                             "bericht.json", "bericht.md"] + report.extraFiles)
    ProgressLog.shared.emit("done", ["report": layout.reportJSON.path, "summary": report.summary])
}

let args: Args
do { args = try parse() } catch {
    FileHandle.standardError.write("\(error.localizedDescription)\n\n\(usage)\n".data(using: .utf8)!)
    exit(2)
}

let semaphore = DispatchSemaphore(value: 0)
var exitCode: Int32 = 0
Task {
    let log = ProgressLog.shared
    do {
        switch args.command {
        case "lauf", "bilder":
            guard let out = args.out else { throw CaptureError.message("--aus <ordner> fehlt") }
            let layout = Layout(out)
            log.emit("start", ["command": args.command, "input": args.input?.path ?? "", "out": out.path,
                               "images": args.extraction.count, "long_edge": args.extraction.longEdge,
                               "detail": ReconstructionOptions.name(of: args.recon.detail)])
            let ex = try await runExtraction(args, layout)
            if args.command == "lauf" {
                try await runReconstruction(args, layout, extractionSeconds: ex.seconds)
                try runPost(args, layout)
            }
        case "rekonstruktion":
            guard let dir = args.input ?? args.out else { throw CaptureError.message("Ordner fehlt") }
            let layout = Layout(dir)
            log.emit("start", ["command": args.command, "out": dir.path,
                               "detail": ReconstructionOptions.name(of: args.recon.detail)])
            try await runReconstruction(args, layout, extractionSeconds: nil)
            try runPost(args, layout)
        case "nachbearbeitung":
            guard let dir = args.input ?? args.out else { throw CaptureError.message("Ordner fehlt") }
            log.emit("start", ["command": args.command, "out": dir.path])
            try runPost(args, Layout(dir))
        default:
            print(usage)
            exitCode = 2
        }
    } catch {
        log.emit("error", ["message": error.localizedDescription])
        log.info("Fehler: \(error.localizedDescription)")
        exitCode = 1
    }
    semaphore.signal()
}
semaphore.wait()
exit(exitCode)
