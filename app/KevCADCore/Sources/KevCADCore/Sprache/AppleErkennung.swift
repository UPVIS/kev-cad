import AVFoundation
import CoreMedia
import Foundation
import Speech

// V2-6: Apples Spracherkennung auf dem Gerät (SpeechAnalyzer), der Rückfall hinter Wortlaut. Vorbild `AppleQuelle` in
// Sichtung. Die Diktaterkennung
// liefert nach knapp einer Sekunde Text und schließt Sätze an Pausen; das genaue Modell (SpeechTranscriber) arbeitet in
// Schüben und ist nur Rückfall. Ton kommt vom Mikrofon oder, im Selbsttest, aus einer Datei in Echtzeit.

@available(macOS 26.0, *)
@MainActor
final class AppleErkennung: Spracherkennung {
    private(set) var kennung = "apple-dictation"
    let wortzeiten = "ton"
    var beiEreignis: ((SprachEreignis) -> Void)?

    enum Fehler: LocalizedError {
        case keinZugriff, keineSprache, keinFormat

        var errorDescription: String? {
            switch self {
            case .keinZugriff:
                return "Kev CAD darf das Mikrofon nicht benutzen. Das gibst du in den Systemeinstellungen unter "
                    + "Datenschutz frei."
            case .keineSprache: return "Für Deutsch gibt es auf diesem Mac keine Spracherkennung."
            case .keinFormat: return "Die Spracherkennung nennt kein passendes Tonformat."
            }
        }
    }

    /// Testeingang: Ton aus dieser Datei statt vom Mikrofon. Fragt nach keinem Recht.
    private let tonDatei: URL?
    /// Teilnamen und Fachwörter: helfen der Erkennung bei „Laufrolle“ oder „Sterngriff“.
    var kontext: [String] = []

    private var eingang: TonEingang?
    private var dateiLauf: Task<Void, Never>?
    /// Bleibt über Abschnitte offen: Nach einer Pause geht der Ton dort weiter, wo er stand.
    private var offeneDatei: AVAudioFile?
    private var eingabe: AsyncStream<AnalyzerInput>.Continuation?
    private var analyzer: SpeechAnalyzer?
    private var hoerer: Task<Void, Never>?
    private var anlauf: Task<Void, Never>?
    /// Uptime des ersten Tons dieses Abschnitts: Zeit null der Erkennung.
    private let null = TonNull()
    private var laeuft = false

    init(tonDatei: URL? = nil) {
        self.tonDatei = tonDatei
    }

    func starten() {
        guard !laeuft else { return }
        laeuft = true
        beiEreignis?(.zustand(.startet))
        anlauf = Task { [weak self] in await self?.hochfahren() }
    }

    func anhalten(hoechstens s: Double) async {
        guard laeuft else { return }
        laeuft = false
        await anlauf?.value
        eingang?.stoppen()
        eingang = nil
        dateiLauf?.cancel()
        dateiLauf = nil
        eingabe?.finish()
        eingabe = nil
        if let analyzer {
            try? await analyzer.finalizeAndFinishThroughEndOfInput()  // die letzten Wörter fertig erkennen
        }
        analyzer = nil
        await hoerer?.value
        hoerer = nil
        beiEreignis?(.zustand(.aus))
    }

    private func hochfahren() async {
        do {
            if tonDatei == nil, !(await Self.mikrofonErlaubt()) { throw Fehler.keinZugriff }
            let sprache = Locale(identifier: "de-DE")
            let diktat: DictationTranscriber?
            let genau: SpeechTranscriber?
            if let locale = await DictationTranscriber.supportedLocale(equivalentTo: sprache) {
                // farField: Kevin spricht aus einer Armlänge Abstand; frequentFinalization: Sätze an Pausen abschließen
                diktat = DictationTranscriber(locale: locale, contentHints: [.farField], transcriptionOptions: [.punctuation],
                                              reportingOptions: [.volatileResults, .frequentFinalization],
                                              attributeOptions: [.audioTimeRange])
                genau = nil
            } else if let locale = await SpeechTranscriber.supportedLocale(equivalentTo: sprache) {
                genau = SpeechTranscriber(locale: locale, transcriptionOptions: [], reportingOptions: [.volatileResults],
                                          attributeOptions: [.audioTimeRange])
                diktat = nil
                kennung = "apple-speech"
            } else {
                throw Fehler.keineSprache
            }
            let modul: any SpeechModule = diktat.map { $0 as any SpeechModule } ?? genau!
            if await AssetInventory.status(forModules: [modul]) != .installed {
                beiEreignis?(.zustand(.laedt("Das Sprachpaket lädt …")))
                if let anfrage = try await AssetInventory.assetInstallationRequest(supporting: [modul]) {
                    try await anfrage.downloadAndInstall()
                }
            }
            guard laeuft else { return }
            guard let format = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [modul]) else {
                throw Fehler.keinFormat
            }
            // Ton zuerst: Was Kevin sagt, während die Erkennung noch anläuft, wartet im Strom
            let (strom, eingabe) = AsyncStream<AnalyzerInput>.makeStream(bufferingPolicy: .unbounded)
            self.eingabe = eingabe
            null.setzen(nil)
            if let tonDatei {
                dateiLauf = dateiEinspeisen(tonDatei, format: format, eingabe: eingabe)
            } else {
                let e = TonEingang(ziel: format, eingabe: eingabe, null: null, pegel: pegelWeitergabe())
                try e.starten()
                eingang = e
            }
            let analyzer = SpeechAnalyzer(modules: [modul],
                                          options: SpeechAnalyzer.Options(priority: .userInitiated, modelRetention: .lingering))
            try await analyzer.prepareToAnalyze(in: format)
            if !kontext.isEmpty {
                // Kontext hilft nur, er ist keine Bedingung
                let zusammenhang = AnalysisContext()
                zusammenhang.contextualStrings[.general] = kontext
                try? await analyzer.setContext(zusammenhang)
            }
            self.analyzer = analyzer
            hoerer = Task { [weak self] in
                do {
                    if let diktat {
                        for try await e in diktat.results { self?.ergebnis(e.text, final: e.isFinal, bereich: e.range) }
                    } else if let genau {
                        for try await e in genau.results { self?.ergebnis(e.text, final: e.isFinal, bereich: e.range) }
                    }
                } catch {
                    self?.beiEreignis?(.zustand(.fehler(error.localizedDescription)))
                }
            }
            try await analyzer.start(inputSequence: strom)
            if laeuft { beiEreignis?(.zustand(.hoert)) }
        } catch {
            laeuft = false
            eingang?.stoppen()
            eingang = nil
            beiEreignis?(.zustand(.fehler(error.localizedDescription)))
        }
    }

    /// Ton aus einer Datei in Echtzeit, danach Stille, bis `anhalten` kommt (wie ein stilles Mikrofon).
    private func dateiEinspeisen(_ url: URL, format: AVAudioFormat, eingabe: AsyncStream<AnalyzerInput>.Continuation) -> Task<Void, Never> {
        nonisolated(unsafe) let ziel = format
        let null = self.null
        if offeneDatei == nil { offeneDatei = try? AVAudioFile(forReading: url) }
        nonisolated(unsafe) let offen = offeneDatei
        return Task.detached(priority: .userInitiated) {
            do {
                guard let datei = offen else { return }
                guard let wandler = AVAudioConverter(from: datei.processingFormat, to: ziel) else { return }
                wandler.primeMethod = .none
                let block: AVAudioFrameCount = 1024
                let dauer = Double(block) / datei.processingFormat.sampleRate
                var naechster = ProcessInfo.processInfo.systemUptime
                null.setzen(naechster)
                while !Task.isCancelled {
                    guard let puffer = AVAudioPCMBuffer(pcmFormat: datei.processingFormat, frameCapacity: block) else { break }
                    if datei.framePosition < datei.length {
                        try datei.read(into: puffer, frameCount: block)
                    } else {
                        puffer.frameLength = block
                        for k in 0..<Int(puffer.format.channelCount) {
                            puffer.floatChannelData?[k].update(repeating: 0, count: Int(block))
                        }
                    }
                    if let g = TonEingang.wandeln(puffer, mit: wandler) { eingabe.yield(AnalyzerInput(buffer: g)) }
                    naechster += dauer
                    let warten = naechster - ProcessInfo.processInfo.systemUptime
                    if warten > 0 { try await Task.sleep(for: .seconds(warten)) }
                }
            } catch {
                // Abbruch beim Anhalten, oder die Datei fehlt: dann bleibt die Erkennung still
            }
        }
    }

    private func ergebnis(_ text: AttributedString, final: Bool, bereich: CMTimeRange) {
        let roh = String(text.characters).trimmingCharacters(in: .whitespacesAndNewlines)
        // Die Diktaterkennung beginnt einen Satz manchmal mit dem Punkt des vorigen
        let sauber = roh.drop { $0.isPunctuation || $0.isWhitespace }.description
        guard final else {
            if !sauber.isEmpty { beiEreignis?(.zwischenstand(sauber)) }
            return
        }
        guard sauber.contains(where: { $0.isLetter || $0.isNumber }) else { return }
        let n = null.wert ?? ProcessInfo.processInfo.systemUptime
        let worte = Self.worte(aus: text, null: n)
        let von = bereich.start.isNumeric ? n + bereich.start.seconds : worte.first?.von
        let bis = bereich.end.isNumeric ? n + bereich.end.seconds : worte.last?.bis
        beiEreignis?(.satz(text: sauber, worte: worte, von: von, bis: bis))
    }

    /// Wörter mit Zeiten aus den Abschnitten des Texts. Ein Abschnitt ohne eigene Zeit (Satzzeichen, Leerzeichen) hängt am
    /// Wort davor; enthält ein Abschnitt mehrere Wörter, teilen sie sich seine Zeit nach ihrer Länge.
    nonisolated static func worte(aus text: AttributedString, null: Double) -> [SprachWort] {
        var aus: [SprachWort] = []
        var offen = false  // das letzte Wort geht weiter, wenn kein Leerzeichen folgt
        for run in text.runs {
            let stueck = String(text[run.range].characters)
            let zeit = run[AttributeScopes.SpeechAttributes.TimeRangeAttribute.self]
            let teile = stueck.split(whereSeparator: \.isWhitespace).map(String.init)
            guard !teile.isEmpty else {
                offen = false
                continue
            }
            let vorn = stueck.first?.isWhitespace == true
            var erste = 0
            if !vorn, offen, !aus.isEmpty {
                aus[aus.count - 1].text += teile[0]
                if let zeit, zeit.end.isNumeric, teile.count == 1 { aus[aus.count - 1].bis = null + zeit.end.seconds }
                erste = 1
            }
            if erste < teile.count {
                let rest = Array(teile[erste...])
                let start = zeit.flatMap { $0.start.isNumeric ? null + $0.start.seconds : nil } ?? aus.last?.bis ?? null
                let ende = zeit.flatMap { $0.end.isNumeric ? null + $0.end.seconds : nil } ?? start
                let gesamt = Double(rest.reduce(0) { $0 + $1.count })
                var t = start
                for wort in rest {
                    let anteil = gesamt > 0 ? (ende - start) * Double(wort.count) / gesamt : 0
                    aus.append(.init(text: wort, von: t, bis: t + anteil))
                    t += anteil
                }
            }
            offen = stueck.last?.isWhitespace != true
        }
        return aus
    }

    private func pegelWeitergabe() -> @Sendable (Float) -> Void {
        let verweis = SchwacheErkennung(self)
        return { wert in
            DispatchQueue.main.async {
                MainActor.assumeIsolated { verweis.erkennung?.beiEreignis?(.pegel(wert)) }
            }
        }
    }

    private static func mikrofonErlaubt() async -> Bool {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: return true
        case .notDetermined: return await AVCaptureDevice.requestAccess(for: .audio)
        default: return false
        }
    }
}

@available(macOS 26.0, *)
private final class SchwacheErkennung: @unchecked Sendable {
    weak var erkennung: AppleErkennung?
    init(_ e: AppleErkennung) { erkennung = e }
}

/// Zeit null der Erkennung, gesetzt vom Tonfaden, gelesen auf dem Hauptfaden.
final class TonNull: @unchecked Sendable {
    private let sperre = NSLock()
    private var zeit: Double?

    var wert: Double? { sperre.withLock { zeit } }

    func setzen(_ neu: Double?) { sperre.withLock { zeit = neu } }

    /// Nur der erste Ton eines Abschnitts zählt.
    func ersterTon(_ t: Double) {
        sperre.withLock { if zeit == nil { zeit = t } }
    }
}

/// Holt den Ton vom Mikrofon, wandelt ihn ins Format der Erkennung und misst den Pegel. Der Abgriff läuft auf dem
/// Tonfaden; alles, was er anfasst, liegt hinter einer Sperre.
@available(macOS 26.0, *)
final class TonEingang: @unchecked Sendable {
    enum Fehler: LocalizedError {
        case keinMikrofon
        var errorDescription: String? { "Kein Mikrofon gefunden." }
    }

    private let engine = AVAudioEngine()
    private let sperre = NSLock()
    private let ziel: AVAudioFormat
    private let eingabe: AsyncStream<AnalyzerInput>.Continuation
    private let null: TonNull
    private let pegel: @Sendable (Float) -> Void
    private var wandler: AVAudioConverter?
    private var aktiv = false
    private var letzterPegel: Double = 0

    init(ziel: AVAudioFormat, eingabe: AsyncStream<AnalyzerInput>.Continuation, null: TonNull,
         pegel: @escaping @Sendable (Float) -> Void) {
        self.ziel = ziel
        self.eingabe = eingabe
        self.null = null
        self.pegel = pegel
    }

    func starten() throws {
        let eingang = engine.inputNode
        let format = eingang.inputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else { throw Fehler.keinMikrofon }
        sperre.withLock { aktiv = true }
        // Kleine Blöcke: Jeder Block ist Wartezeit, bevor die Erkennung ihn sieht
        eingang.installTap(onBus: 0, bufferSize: 1024, format: nil) { [weak self] puffer, zeit in
            self?.verarbeiten(puffer, zeit)
        }
        engine.prepare()
        try engine.start()
    }

    func stoppen() {
        sperre.withLock { aktiv = false }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
    }

    private func verarbeiten(_ puffer: AVAudioPCMBuffer, _ zeit: AVAudioTime) {
        sperre.lock()
        guard aktiv else {
            sperre.unlock()
            return
        }
        if wandler == nil || wandler?.inputFormat != puffer.format {
            wandler = AVAudioConverter(from: puffer.format, to: ziel)
            wandler?.primeMethod = .none
        }
        let w = wandler
        sperre.unlock()
        // Hostzeit und systemUptime laufen auf derselben Uhr
        let jetzt = zeit.isHostTimeValid ? AVAudioTime.seconds(forHostTime: zeit.hostTime)
            : ProcessInfo.processInfo.systemUptime - Double(puffer.frameLength) / max(1, puffer.format.sampleRate)
        null.ersterTon(jetzt)
        if let w, let g = Self.wandeln(puffer, mit: w) { eingabe.yield(AnalyzerInput(buffer: g)) }
        guard jetzt - letzterPegel > 0.09, let kanal = puffer.floatChannelData?[0], puffer.frameLength > 0 else { return }
        letzterPegel = jetzt
        let n = Int(puffer.frameLength)
        var summe: Float = 0
        for i in 0..<n { summe += kanal[i] * kanal[i] }
        let rms = (summe / Float(n)).squareRoot()
        pegel(min(1, max(0, (20 * log10(max(rms, 1e-6)) + 62) / 46)))
    }

    static func wandeln(_ puffer: AVAudioPCMBuffer, mit wandler: AVAudioConverter) -> AVAudioPCMBuffer? {
        let verhaeltnis = wandler.outputFormat.sampleRate / wandler.inputFormat.sampleRate
        let platz = AVAudioFrameCount((Double(puffer.frameLength) * verhaeltnis).rounded(.up)) + 64
        guard let ausgabe = AVAudioPCMBuffer(pcmFormat: wandler.outputFormat, frameCapacity: platz) else { return nil }
        let zufuhr = Zufuhr(puffer)
        var fehler: NSError?
        let status = wandler.convert(to: ausgabe, error: &fehler) { _, eingabeStatus in zufuhr.naechster(eingabeStatus) }
        guard status != .error, fehler == nil, ausgabe.frameLength > 0 else { return nil }
        return ausgabe
    }

    private final class Zufuhr: @unchecked Sendable {
        private let puffer: AVAudioPCMBuffer
        private var verbraucht = false
        init(_ puffer: AVAudioPCMBuffer) { self.puffer = puffer }
        func naechster(_ status: UnsafeMutablePointer<AVAudioConverterInputStatus>) -> AVAudioBuffer? {
            if verbraucht {
                status.pointee = .noDataNow
                return nil
            }
            verbraucht = true
            status.pointee = .haveData
            return puffer
        }
    }
}
