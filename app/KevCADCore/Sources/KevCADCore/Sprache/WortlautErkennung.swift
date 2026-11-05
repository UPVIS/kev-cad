import AppKit
import Foundation

// V2-6: Kev CAD als Kunde von Wortlauts Sprachdienst (Parakeet auf der Neural Engine). Vertrag:
// `SprachdienstProtocol.swift`, wörtlich aus Wortlaut; Ablauf wie `WortlautQuelle` in Sichtung: `hello`, `startListening`
// mit `pause` und `partials`, dann Pegel, Zwischenstände, fertige Sätze und Zustände. Nur eine mit Kevins Team signierte
// Fassung kommt durch; Wortlaut hört für ein Programm zur Zeit, und hält Kevin Fn zum Diktieren, ruht der Dienst.
//
// Der Dienst nennt keine Zeiten je Wort. `Wortzeiten` schätzt sie aus Beginn und Ende des Satzes und dem Takt der
// Zwischenstände.

enum Wortlaut {
    static let team = "2GX7UC98J6"
    static let anforderung = "anchor apple generic and certificate leaf[subject.OU] = \"\(team)\""
    static let name = "Kev CAD"

    static var installiert: Bool {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return ["/Applications/Wortlaut.app", "\(home)/Applications/Wortlaut.app"].contains {
            FileManager.default.fileExists(atPath: $0)
        }
    }
}

/// Wortzeiten aus dem Takt der Zwischenstände. Ein Zwischenstand sagt: Bis hierhin war der Text gesprochen, kurz bevor er
/// ankam. Zwischen diesen Stützstellen verteilen sich die Wörter nach ihrer Länge.
enum Wortzeiten {
    /// So lange braucht ein Zwischenstand vom Ton bis hierher, grob (Wortlaut rechnet im Takt von 0,4 s).
    static let nachlaufS = 0.25

    struct Stuetze: Equatable {
        /// Zeichen, die zu dieser Zeit gesprochen waren.
        var zeichen: Int
        var zeit: Double
    }

    static func schaetzen(text: String, von: Double, bis: Double, stuetzen: [Stuetze]) -> [SprachWort] {
        let worte = text.split(whereSeparator: \.isWhitespace).map(String.init)
        let gesamt = worte.reduce(0) { $0 + $1.count }
        guard gesamt > 0 else { return [] }
        // Stützstellen steigen in Zeichen und Zeit; außerhalb des Satzes zählen sie nicht
        var punkte: [(zeichen: Double, zeit: Double)] = [(0, von)]
        for s in stuetzen.sorted(by: { $0.zeit < $1.zeit }) {
            let z = Double(min(s.zeichen, gesamt)), t = s.zeit - nachlaufS
            guard z > punkte[punkte.count - 1].zeichen, z < Double(gesamt), t > punkte[punkte.count - 1].zeit, t < bis
            else { continue }
            punkte.append((z, t))
        }
        punkte.append((Double(gesamt), max(bis, punkte[punkte.count - 1].zeit)))
        func zeit(_ zeichen: Double) -> Double {
            for i in 1..<punkte.count where zeichen <= punkte[i].zeichen {
                let a = punkte[i - 1], b = punkte[i]
                let anteil = b.zeichen > a.zeichen ? (zeichen - a.zeichen) / (b.zeichen - a.zeichen) : 0
                return a.zeit + (b.zeit - a.zeit) * anteil
            }
            return bis
        }
        var aus: [SprachWort] = []
        var zeichen = 0.0
        for w in worte {
            let ende = zeichen + Double(w.count)
            aus.append(.init(text: w, von: zeit(zeichen), bis: zeit(ende)))
            zeichen = ende
        }
        return aus
    }
}

/// Eine Verbindung zum Dienst. Eigener Typ, damit Tests ohne Wortlaut laufen.
protocol WortlautVerbindung: AnyObject {
    var dienst: (any SprachdienstProtocol)? { get }
    /// Letztes `stopListening`; danach ist die Verbindung zu.
    func schliessenNachStopp()
    func abbrechen()
}

@MainActor
public final class WortlautErkennung: Spracherkennung {
    public let kennung = "wortlaut-parakeet"
    public let wortzeiten = "geschaetzt"
    public var beiEreignis: ((SprachEreignis) -> Void)?
    /// Stille bis zum Satzende (Sichtung, README: mit 0,6 s steht ein Satz rund eine Sekunde nach dem Sprechen fertig).
    var pause = 0.6
    /// Wer nach Pegel laut ist, spricht noch: Der erste Zwischenstand kommt erst nach rund einer halben Sekunde.
    static let lautAb: Float = 0.2
    static let lautNachklangS = 0.45

    enum Meldung: Sendable {
        case pegel(Float)
        case zwischenstand(String, Int)
        case fertig(String, Int, Double, Double)
        case zustand(String, String?)
        case hallo(Int, String?, Int)
        case gestartet(Bool, String?, Int)
        case unterbrochen
        case ungueltig
    }

    private let verbinder: (@escaping @Sendable (Meldung) -> Void) -> any WortlautVerbindung
    private var verbindung: (any WortlautVerbindung)?
    private(set) var leitung = 0
    private var versuch = 0
    private(set) var gewollt = false
    private var begruesst = false
    private var angenommen = false
    private var geantwortet = false
    private var neuVerbunden: [TimeInterval] = []
    private var zustand: SprachZustand = .aus
    /// Laufender Satz: Stützstellen für die Wortzeiten; nil, wenn gerade keiner läuft.
    private var offenerSatz: (nummer: Int, stuetzen: [Wortzeiten.Stuetze])?
    private var letzterLaut: Double = 0

    convenience public init() {
        self.init(verbinder: { XPCVerbindung(weiter: $0) })
    }

    init(verbinder: @escaping (@escaping @Sendable (Meldung) -> Void) -> any WortlautVerbindung) {
        self.verbinder = verbinder
    }

    public func starten() {
        guard !gewollt else { return }
        gewollt = true
        versuch += 1
        neuVerbunden = []
        offenerSatz = nil
        setzen(.startet)
        verbinden()
    }

    /// Der Dienst verwirft beim Stoppen einen angefangenen Satz. Spricht Kevin noch oder fehlt das Ende des Satzes, läuft
    /// das Mikrofon deshalb weiter, bis der Satz da ist, höchstens `s` Sekunden. Was dann fehlt, kommt aus dem letzten
    /// Zwischenstand.
    public func anhalten(hoechstens s: Double) async {
        guard gewollt else { return }
        let ende = ProcessInfo.processInfo.systemUptime + s
        while gewollt, ProcessInfo.processInfo.systemUptime < ende, satzUnterwegs {
            try? await Task.sleep(for: .milliseconds(10))
        }
        stoppen()
    }

    private var satzUnterwegs: Bool {
        offenerSatz != nil || ProcessInfo.processInfo.systemUptime - letzterLaut < Self.lautNachklangS
    }

    private func stoppen() {
        guard gewollt else { return }
        gewollt = false
        versuch += 1
        angenommen = false
        if begruesst { verbindung?.schliessenNachStopp() } else { verbindung?.abbrechen() }
        verbindung = nil
        begruesst = false
        leitung += 1
        setzen(.aus)
    }

    // MARK: Ablauf

    private func verbinden() {
        if verbindung == nil {
            leitung += 1
            geantwortet = false
            begruesst = false
            verbindung = verbinder(Self.weiterleitung(an: self, leitung: leitung))
        }
        if begruesst { einschalten(versuch) } else { hallo(versuch) }
    }

    private func hallo(_ nummer: Int) {
        let weiter = Self.weiterleitung(an: self, leitung: leitung)
        let antwort: @Sendable (Int, String?) -> Void = { fassung, grund in weiter(.hallo(fassung, grund, nummer)) }
        verbindung?.dienst?.hello(client: Wortlaut.name, version: sprachdienstVersion, reply: antwort)
    }

    private func einschalten(_ nummer: Int) {
        let weiter = Self.weiterleitung(an: self, leitung: leitung)
        let antwort: @Sendable (Bool, String?) -> Void = { laeuft, grund in weiter(.gestartet(laeuft, grund, nummer)) }
        verbindung?.dienst?.startListening(options: ["pause": pause, "partials": true], reply: antwort)
    }

    func empfangen(_ m: Meldung, leitung nummer: Int) {
        guard nummer == leitung else { return }
        switch m {
        case .pegel(let wert):
            guard gewollt, angenommen else { return }
            if wert > Self.lautAb { letzterLaut = ProcessInfo.processInfo.systemUptime }
            beiEreignis?(.pegel(wert))
        case .zwischenstand(let text, let u):
            guard gewollt, angenommen else { return }
            let stuetze = Wortzeiten.Stuetze(zeichen: text.filter { !$0.isWhitespace }.count,
                                             zeit: ProcessInfo.processInfo.systemUptime)
            offenerSatz = (u, (offenerSatz?.nummer == u ? offenerSatz!.stuetzen : []) + [stuetze])
            beiEreignis?(.zwischenstand(text))
        case .fertig(let text, let u, let sekunden, let latenz):
            guard gewollt, angenommen else { return }
            // Der Ton eines Satzes hat 0,3 s Vorlauf und 0,4 s Nachlauf (Wortlaut, SCHLACHTPLAN Abschnitt 12)
            let ende = ProcessInfo.processInfo.systemUptime - max(0, latenz)
            let start = ende - max(0.2, sekunden - 0.7)
            let stuetzen = offenerSatz?.nummer == u ? offenerSatz!.stuetzen : []
            offenerSatz = nil
            letzterLaut = 0
            let worte = Wortzeiten.schaetzen(text: text, von: start, bis: ende, stuetzen: stuetzen)
            beiEreignis?(.satz(text: text, worte: worte, von: start, bis: ende))
        case .zustand(let name, let detail):
            geantwortet = true
            guard gewollt else { return }
            switch name {
            case "listening":
                angenommen = true
                setzen(.hoert)
            case "paused":
                // Kevin diktiert in Wortlaut: Der angefangene Satz verfällt, danach geht es frisch weiter
                if offenerSatz != nil {
                    offenerSatz = nil
                    beiEreignis?(.verworfen)
                }
                setzen(.pausiert)
            case "unavailable":
                setzen(.laedt(detail ?? "Wortlaut kann gerade nicht zuhören."))
            case "stopped":
                beenden(detail.map { $0.hasSuffix(".") ? $0 : $0 + "." } ?? "Wortlaut hat das Zuhören beendet.")
            default:
                break
            }
        case .hallo(_, let grund, let nummer):
            geantwortet = true
            guard nummer == versuch, gewollt else { return }
            if let grund {
                beenden(grund)
                return
            }
            begruesst = true
            einschalten(nummer)
        case .gestartet(let laeuft, let grund, let nummer):
            geantwortet = true
            guard nummer == versuch, gewollt else {
                if laeuft, !gewollt { verbindung?.dienst?.stopListening(reply: Self.nichts) }
                return
            }
            if laeuft {
                angenommen = true
                if zustand == .startet { setzen(.hoert) }
            } else {
                beenden(grund ?? "Wortlaut hört gerade für ein anderes Programm zu.")
            }
        case .unterbrochen:
            let warGeantwortet = geantwortet
            geantwortet = false
            begruesst = false
            angenommen = false
            guard gewollt else { return }
            if warGeantwortet { spaeterNeuVerbinden() } else { beenden("Wortlaut nimmt nur signierte Fassungen von Kev CAD an.") }
        case .ungueltig:
            let warGeantwortet = geantwortet
            verbindung = nil
            begruesst = false
            angenommen = false
            guard gewollt else { return }
            if warGeantwortet {
                beenden("Die Verbindung zu Wortlaut ist abgerissen.")
            } else {
                beenden(Wortlaut.installiert ? "Diese Fassung von Wortlaut bietet den Sprachdienst noch nicht an."
                        : "Wortlaut ist nicht installiert.")
            }
        }
    }

    private func spaeterNeuVerbinden() {
        let jetzt = ProcessInfo.processInfo.systemUptime
        neuVerbunden = neuVerbunden.filter { jetzt - $0 < 60 }
        guard neuVerbunden.count < 3 else {
            beenden("Wortlaut antwortet nicht mehr.")
            return
        }
        neuVerbunden.append(jetzt)
        setzen(.laedt("Wortlaut antwortet nicht, Kev CAD verbindet sich neu …"))
        let nummer = versuch
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(1))
            guard let self, self.gewollt, self.versuch == nummer else { return }
            self.verbinden()
        }
    }

    private func beenden(_ grund: String) {
        let warBegruesst = begruesst
        gewollt = false
        versuch += 1
        angenommen = false
        if warBegruesst { verbindung?.dienst?.stopListening(reply: Self.nichts) }
        setzen(.fehler(grund))
    }

    private func setzen(_ neu: SprachZustand) {
        guard neu != zustand else { return }
        zustand = neu
        beiEreignis?(.zustand(neu))
    }

    // MARK: Bausteine für XPC (außerhalb des Hauptfadens gebildet, XPC ruft sie auf eigenen Schlangen)

    private static let nichts: @Sendable () -> Void = {}

    private nonisolated static func weiterleitung(an quelle: WortlautErkennung, leitung: Int) -> @Sendable (Meldung) -> Void {
        let verweis = SchwacherVerweis(quelle)
        return { meldung in
            DispatchQueue.main.async {
                MainActor.assumeIsolated { verweis.quelle?.empfangen(meldung, leitung: leitung) }
            }
        }
    }

    /// Prüft nur die Begrüßung, ohne das Mikrofon einzuschalten (`KEVCAD_SELFTEST=wortlaut`).
    public nonisolated static func begruessung(_ fertig: @escaping @Sendable (String) -> Void) {
        let v = NSXPCConnection(machServiceName: sprachdienstMachName, options: [])
        v.remoteObjectInterface = NSXPCInterface(with: SprachdienstProtocol.self)
        v.exportedInterface = NSXPCInterface(with: SprachdienstClientProtocol.self)
        v.exportedObject = WortlautEmpfaenger(weiter: { _ in })
        v.setCodeSigningRequirement(Wortlaut.anforderung)
        let halter = VerbindungsHalter(v)
        v.invalidationHandler = { fertig("ungültig: Verbindung abgelehnt oder Dienst fehlt") }
        v.interruptionHandler = { fertig("unterbrochen: Wortlaut hat die Verbindung abgewiesen") }
        v.resume()
        let dienst = v.remoteObjectProxyWithErrorHandler({ fehler in
            fertig("Fehler: \(fehler.localizedDescription)")
        }) as? any SprachdienstProtocol
        dienst?.hello(client: Wortlaut.name, version: sprachdienstVersion) { fassung, grund in
            fertig(grund.map { "Absage: \($0)" } ?? "Dienst Fassung \(fassung): Begrüßung angenommen")
            halter.verbindung.invalidate()
        }
    }
}

private final class SchwacherVerweis: @unchecked Sendable {
    weak var quelle: WortlautErkennung?
    init(_ quelle: WortlautErkennung) { self.quelle = quelle }
}

private final class VerbindungsHalter: @unchecked Sendable {
    let verbindung: NSXPCConnection
    init(_ verbindung: NSXPCConnection) { self.verbindung = verbindung }
}

/// Die echte Verbindung über XPC.
private final class XPCVerbindung: WortlautVerbindung {
    private let v: NSXPCConnection
    private static let fehlerEgal: @Sendable (any Error) -> Void = { _ in }

    init(weiter: @escaping @Sendable (WortlautErkennung.Meldung) -> Void) {
        v = NSXPCConnection(machServiceName: sprachdienstMachName, options: [])
        v.remoteObjectInterface = NSXPCInterface(with: SprachdienstProtocol.self)
        v.exportedInterface = NSXPCInterface(with: SprachdienstClientProtocol.self)
        v.exportedObject = WortlautEmpfaenger(weiter: weiter)
        v.setCodeSigningRequirement(Wortlaut.anforderung)
        v.interruptionHandler = { weiter(.unterbrochen) }
        v.invalidationHandler = { weiter(.ungueltig) }
        v.resume()
    }

    var dienst: (any SprachdienstProtocol)? {
        v.remoteObjectProxyWithErrorHandler(Self.fehlerEgal) as? any SprachdienstProtocol
    }

    func schliessenNachStopp() {
        let halter = VerbindungsHalter(v)
        let zu: @Sendable () -> Void = { halter.verbindung.invalidate() }
        let fehler: @Sendable (any Error) -> Void = { _ in halter.verbindung.invalidate() }
        (v.remoteObjectProxyWithErrorHandler(fehler) as? any SprachdienstProtocol)?.stopListening(reply: zu)
    }

    func abbrechen() { v.invalidate() }
}

/// Was Wortlaut bei Kev CAD ruft, auf der Schlange der Verbindung.
final class WortlautEmpfaenger: NSObject, SprachdienstClientProtocol, @unchecked Sendable {
    private let weiter: @Sendable (WortlautErkennung.Meldung) -> Void

    init(weiter: @escaping @Sendable (WortlautErkennung.Meldung) -> Void) {
        self.weiter = weiter
    }

    func level(_ value: Float) { weiter(.pegel(value)) }
    func partial(_ text: String, utterance: Int) { weiter(.zwischenstand(text, utterance)) }
    func final(_ text: String, utterance: Int, seconds: Double, latency: Double) {
        weiter(.fertig(text, utterance, seconds, latency))
    }
    func state(_ name: String, detail: String?) { weiter(.zustand(name, detail)) }
}
