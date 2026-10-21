// fotomess-hilfe: kleine macOS-Hilfe für fotomess (Apple Vision, AVFoundation), ohne Abhängigkeiten.
//
//   fotomess-hilfe maske AUSGABEORDNER BILD ...   Vordergrund-Masken (VNGenerateForegroundInstanceMaskRequest,
//                                                  Neural Engine), je Instanz <name>_inst<i>.pgm in voller Größe
//   fotomess-hilfe meta VIDEO                      Objektiv und Kleinbild-Brennweite aus den QuickTime-Metadaten
//
// Ausgabe je Bild bzw. Video eine JSON-Zeile auf stdout.
import AVFoundation
import CoreVideo
import Foundation
import Vision

func json(_ d: [String: Any]) -> String {
    let data = try! JSONSerialization.data(withJSONObject: d, options: [.sortedKeys])
    return String(data: data, encoding: .utf8)!
}

func schreibePGM(_ pb: CVPixelBuffer, _ ziel: URL) throws {
    CVPixelBufferLockBaseAddress(pb, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(pb, .readOnly) }
    let w = CVPixelBufferGetWidth(pb), h = CVPixelBufferGetHeight(pb)
    let zeile = CVPixelBufferGetBytesPerRow(pb)
    let basis = CVPixelBufferGetBaseAddress(pb)!
    var daten = Data("P5\n\(w) \(h)\n255\n".utf8)
    daten.reserveCapacity(w * h + 32)
    var puffer = [UInt8](repeating: 0, count: w)
    for y in 0..<h {
        let p = basis.advanced(by: y * zeile).assumingMemoryBound(to: Float32.self)
        for x in 0..<w { puffer[x] = UInt8(max(0, min(255, (p[x] * 255).rounded()))) }
        daten.append(contentsOf: puffer)
    }
    try daten.write(to: ziel)
}

func masken(_ ausgabe: URL, _ bilder: [String]) {
    for pfad in bilder {
        let url = URL(fileURLWithPath: pfad)
        let handler = VNImageRequestHandler(url: url, options: [:])
        let anfrage = VNGenerateForegroundInstanceMaskRequest()
        let t0 = Date()
        do {
            try handler.perform([anfrage])
            guard let beob = anfrage.results?.first else {
                print(json(["bild": pfad, "instanzen": [String]()]))
                continue
            }
            var namen: [String] = []
            for inst in beob.allInstances.sorted() {
                let pb = try beob.generateScaledMaskForImage(forInstances: IndexSet(integer: inst), from: handler)
                let name = url.deletingPathExtension().lastPathComponent + "_inst\(inst).pgm"
                try schreibePGM(pb, ausgabe.appendingPathComponent(name))
                namen.append(name)
            }
            print(json(["bild": pfad, "instanzen": namen, "sekunden": Date().timeIntervalSince(t0)]))
        } catch {
            print(json(["bild": pfad, "fehler": "\(error)"]))
        }
    }
}

func meta(_ pfad: String) {
    let asset = AVURLAsset(url: URL(fileURLWithPath: pfad))
    let fertig = DispatchSemaphore(value: 0)
    var out: [String: Any] = ["video": pfad]
    Task {
        do {
            for item in try await asset.load(.metadata) {
                if let k = item.identifier?.rawValue, let v = try? await item.load(.stringValue) { out[k] = v }
            }
            for spur in try await asset.load(.tracks) {
                for item in try await spur.load(.metadata) {
                    if let k = item.identifier?.rawValue, let v = try? await item.load(.stringValue) { out[k] = v }
                }
                if spur.mediaType == .video {
                    let g = try await spur.load(.naturalSize)
                    let t = try await spur.load(.preferredTransform)
                    out["breite"] = Int(g.width)
                    out["hoehe"] = Int(g.height)
                    out["drehung"] = Int((atan2(Double(t.b), Double(t.a)) * 180 / .pi).rounded())
                }
            }
        } catch { out["fehler"] = "\(error)" }
        fertig.signal()
    }
    fertig.wait()
    print(json(out))
}

let args = CommandLine.arguments
if args.count >= 3 && args[1] == "maske" {
    masken(URL(fileURLWithPath: args[2]), Array(args.dropFirst(3)))
} else if args.count == 3 && args[1] == "meta" {
    meta(args[2])
} else {
    FileHandle.standardError.write("Aufruf: fotomess-hilfe maske ORDNER BILD... | meta VIDEO\n".data(using: .utf8)!)
    exit(2)
}
