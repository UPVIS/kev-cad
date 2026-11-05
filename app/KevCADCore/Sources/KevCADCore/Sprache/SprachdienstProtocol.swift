import Foundation

/// Name des Mach-Dienstes im LaunchAgent von Wortlaut.
public let sprachdienstMachName = "de.upvis.wortlaut.sprachdienst"
public let sprachdienstVersion = 1

/// Was Wortlaut anbietet.
@objc public protocol SprachdienstProtocol {
    /// Begrüßung. Antwort: Fassung des Dienstes, sonst ein Satz, warum es nicht geht.
    func hello(client: String, version: Int, reply: @escaping (Int, String?) -> Void)
    /// Zuhören einschalten. `options`: "pause" (Sekunden Stille bis zum Satzende, Vorgabe 0,6),
    /// "partials" (Bool, Vorgabe true). Antwort: ob es läuft, sonst ein Satz, warum nicht.
    func startListening(options: [String: Any], reply: @escaping (Bool, String?) -> Void)
    /// Zuhören ausschalten. Danach ist das Mikrofon für diesen Kunden zu.
    func stopListening(reply: @escaping () -> Void)
}

/// Was der Kunde anbietet; Wortlaut ruft es über dieselbe Verbindung.
@objc public protocol SprachdienstClientProtocol {
    /// Pegel, rund zehnmal je Sekunde, 0 bis 1.
    func level(_ value: Float)
    /// Zwischenstand des laufenden Satzes. Jeder Aufruf ersetzt den vorigen desselben Satzes.
    func partial(_ text: String, utterance: Int)
    /// Der fertige Satz nach der Pause. `seconds` ist die Länge des Tons, `latency` die Zeit vom
    /// Ende des Sprechens bis zu diesem Aufruf.
    func final(_ text: String, utterance: Int, seconds: Double, latency: Double)
    /// Zustand: "listening", "paused" (Wortlaut diktiert gerade selbst), "unavailable" (kein
    /// Mikrofon, kein Modell), "stopped". `detail` ist ein Satz für die Oberfläche oder nil.
    func state(_ name: String, detail: String?)
}
