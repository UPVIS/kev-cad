#if DEBUG
import KevCADCore
import SwiftUI

/// Gesten-Tests (I-3b, UITests/KevCADPad): Mit `KEVCAD_PAD_UITEST=1` legt die App ein unsichtbares Element mit dem
/// Zustand des Viewers in den Bedienbaum, damit der XCUITest prüfen kann, was Tippen, Doppeltippen, langes Drücken und
/// 2/3 Finger tippen bewirkt haben. Nur in Debug-Bauten und nur auf dem iPad: Am Mac prüfen die Selbsttests der App
/// (`KEVCAD_SELFTEST`) direkt am App-Kern, dort gibt es keine Gesten zu simulieren.
struct PadTestZustand: View {
    let session: AppSession

    static var an: Bool { ProcessInfo.processInfo.environment["KEVCAD_PAD_UITEST"] == "1" }

    var body: some View {
        // Einmal je halbe Sekunde neu lesen: Kamera und Szene sind nicht beobachtbar, im Test reicht das
        TimelineView(.periodic(from: .now, by: 0.5)) { _ in
            Text(text)
                .font(.system(size: 1))
                .frame(width: 1, height: 1)
                .opacity(0.02)
                .accessibilityIdentifier("test.zustand")
                .accessibilityLabel(text)
        }
        .allowsHitTesting(false)
    }

    private var text: String {
        let m = session.model
        let kamera = session.controller?.viewport.controller.cameraState
        let werte: [(String, String)] = [
            ("teile", "\(m.parts.count)"),
            ("auswahl", m.selection.map(\.ref).joined(separator: ",")),
            ("verborgen", "\(m.parts.filter { !$0.visible }.count)"),
            ("links", m.oberflaeche.leisteLinks ? "1" : "0"),
            ("rechts", m.oberflaeche.leisteRechts ? "1" : "0"),
            ("rueck", m.viewer.rueckgaengigTitel ?? ""),
            ("wieder", m.viewer.wiederholenTitel ?? ""),
            ("meldung", m.viewer.meldung?.text ?? ""),
            ("abstand", kamera.map { String(format: "%.1f", $0.distance) } ?? ""),
            ("drehung", kamera.map { q in [q.rotation.vector.x, q.rotation.vector.y, q.rotation.vector.z, q.rotation.vector.w]
                .map { String(format: "%.5f", $0) }.joined(separator: ",") } ?? ""),
            ("mehrfach", m.viewer.mehrfach ? "1" : "0"),
        ]
        return werte.map { "\($0.0)=\($0.1)" }.joined(separator: ";")
    }
}
#endif
