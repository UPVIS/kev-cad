import Foundation

/// Empfängerseite des Spiegels (iPhone, VoiceBridge-Mac-App, Simulator-Client, Tests). Hält Szene und Zustand nach den
/// Regeln aus MIRROR.md, ohne Ein- und Ausgabe:
///
/// - Epoche: wechselt sie (HELLO, SCENE oder STATE mit neuer Epoche), gilt alles Bisherige als überholt; Netze nach Hash
///   bleiben gültig. Deltas, Teile und Kameras mit fremder Epoche werden verworfen.
/// - SCENE kommt in Seiten; die Teileliste wird erst ersetzt, wenn alle Seiten `0 … seiten − 1` da sind.
/// - STATE_DELTA mit kleinerem `rev` als dem bekannten wird verworfen; die Kamera zählt für sich (latest-only).
/// - Netze: Blöcke je Hash zusammensetzen, entpacken, Hash prüfen; `takeMeshRequest()` fragt nur Fehlendes an.
/// - Freigaben (Version 1.1): offene Anfragen aus FREIGABE, ohne Miete; FREIGABE_ENDE nimmt einen Eintrag bzw. die
///   ganze Anfrage heraus, eine neue Epoche alle.
public struct MirrorReceiver: Sendable {
    public enum Event: Sendable, Equatable {
        case hello(MirrorHello)
        case agents([MirrorAgent])
        /// Neue Epoche: Zustand, `rev` und offene Befehle sind überholt.
        case epochChanged(old: String?, new: String)
        /// Alle Seiten einer SCENE sind da; die Teileliste ist ersetzt.
        case sceneReplaced
        case partUpserted(String)
        case partRemoved(String)
        case stateReplaced
        /// Geänderte Felder eines STATE_DELTA und woher die Änderung kam.
        case stateChanged(fields: [String], quelle: MirrorSource)
        case camera(MirrorSource)
        case meshReady(String)
        case meshRejected(hash: String, reason: String)
        case commandResult(MirrorCommandResult)
        /// Version 1.1: Anfrage neu oder aktualisiert (`freigaben` enthält sie).
        case freigabe(MirrorFreigabeMessage)
        /// Version 1.1: Eintrag (mit `id`) oder ganze Anfrage erledigt.
        case freigabeEnde(MirrorFreigabeEndeMessage)
        /// Verworfen (fremde Epoche, altes `rev`, unbekannter Typ …), mit Grund.
        case ignored(String)
    }

    public private(set) var epoche: String?
    public private(set) var hello: MirrorHello?
    public private(set) var agents: [MirrorAgent] = []
    public private(set) var project: MirrorProject?
    public private(set) var run = 0
    public private(set) var bbox: BBox?
    /// Teile in der Reihenfolge der Szene.
    public private(set) var parts: [MirrorPart] = []
    /// Voller Zustand, sobald STATE da ist.
    public private(set) var state: MirrorViewState?
    public private(set) var rev = 0
    public private(set) var cameraRev = 0
    /// Eine vollständige SCENE der aktuellen Epoche ist da.
    public private(set) var hasScene = false
    /// Ungepackte Netze nach Hash (`kcad-mesh-1`).
    public private(set) var meshes: [String: Data] = [:]
    /// Offene Freigabe-Anfragen der aktuellen Epoche in der Reihenfolge ihres Eintreffens, je nur mit den noch offenen
    /// Einträgen (Version 1.1).
    public private(set) var freigaben: [MirrorFreigabeMessage] = []

    private var pages: [Int: [MirrorPart]] = [:]
    private var pageKey: (epoche: String, run: Int, seiten: Int)?
    private var assembler = MeshAssembler()
    /// Angeforderte Netze und wann (für das Wiederholen nach etwa 10 s).
    private var requested: [String: Date] = [:]
    /// Nach so vielen Sekunden ohne Antwort darf ein MESH_REQ wiederholt werden (MIRROR.md).
    public static let meshRetrySeconds: TimeInterval = 10

    public init() {}

    /// Teil nach Namen.
    public func part(_ name: String) -> MirrorPart? { parts.first { $0.name == name } }

    /// Geometrie eines Teils, sobald sein Netz da ist.
    public func geometry(of part: MirrorPart) throws -> PartGeometry? {
        guard let raw = meshes[part.hash] else { return nil }
        return try KcadMesh.geometry(raw: raw, counts: part.counts)
    }

    /// Alles da: Szene, Zustand und alle Netze.
    public var isComplete: Bool {
        hasScene && state != nil && parts.allSatisfy { meshes[$0.hash] != nil }
    }

    /// Hashes der Teile ohne Netz (ohne die angeforderten, die noch keine `meshRetrySeconds` alt sind).
    public func missingMeshes(now: Date = Date()) -> [String] {
        var seen = Set<String>()
        var out: [String] = []
        for p in parts where meshes[p.hash] == nil && seen.insert(p.hash).inserted {
            if let at = requested[p.hash], now.timeIntervalSince(at) < Self.meshRetrySeconds { continue }
            out.append(p.hash)
        }
        return out
    }

    /// MESH_REQ für die fehlenden Netze (merkt sie als angefordert) oder nil, wenn nichts fehlt. Bleibt eine Anfrage
    /// länger als `meshRetrySeconds` unbeantwortet, kommt der Hash wieder mit.
    public mutating func takeMeshRequest(now: Date = Date()) -> MirrorMeshRequest? {
        let missing = missingMeshes(now: now)
        guard !missing.isEmpty else { return nil }
        for h in missing { requested[h] = now }
        return MirrorMeshRequest(hashes: missing)
    }

    /// Netz von außen einsetzen (z. B. aus einem Plattenspeicher nach Hash).
    public mutating func insertMesh(hash: String, raw: Data) {
        meshes[hash] = raw
        requested[hash] = nil
    }

    public mutating func removeMesh(hash: String) { meshes[hash] = nil }

    /// Offene Anfragen, die zum Zeitpunkt `now` noch nicht abgelaufen sind.
    public func offeneFreigaben(now: Date = Date()) -> [MirrorFreigabeMessage] {
        freigaben.filter { !$0.abgelaufen(now: now) && !$0.eintraege.isEmpty }
    }

    /// Nach dem Trennen: halbe Netze und Anforderungen vergessen (der volle Stand kommt nach dem nächsten WATCH neu).
    public mutating func connectionLost() {
        assembler.reset()
        requested = [:]
        pages = [:]
        pageKey = nil
    }

    // MARK: Nachrichten

    public mutating func apply(_ message: MirrorMessage) -> [Event] {
        switch message {
        case .hello(let h):
            hello = h
            var events: [Event] = [.hello(h)]
            if let e = h.epoche { events += adoptEpoch(e) }
            if let a = h.agents {
                agents = a
                events.append(.agents(a))
            }
            if let p = h.project { project = p }
            return events

        case .agents(let a):
            if let e = epoche, !a.epoche.isEmpty, a.epoche != e { return [.ignored("AGENTS mit fremder Epoche")] }
            agents = a.agents
            return [.agents(a.agents)]

        case .scene(let page):
            var events = adoptEpoch(page.epoche)
            if pageKey == nil || pageKey!.epoche != page.epoche || pageKey!.run != page.run
                || pageKey!.seiten != page.seiten
            {
                pages = [:]
                pageKey = (page.epoche, page.run, page.seiten)
            }
            pages[page.seite] = page.parts
            if (0..<max(page.seiten, 1)).allSatisfy({ pages[$0] != nil }) {
                parts = (0..<max(page.seiten, 1)).flatMap { pages[$0]! }
                pages = [:]
                pageKey = nil
                run = page.run
                bbox = page.bbox
                project = page.project
                hasScene = true
                events.append(.sceneReplaced)
            }
            return events

        case .part(let m):
            guard m.epoche == epoche else { return [.ignored("PART mit fremder Epoche")] }
            run = max(run, m.run)
            switch m.op {
            case .upsert:
                guard let p = m.part else { return [.ignored("PART ohne Teil")] }
                if let i = parts.firstIndex(where: { $0.name == p.name }) {
                    parts[i] = p
                } else {
                    parts.append(p)
                }
                return [.partUpserted(p.name)]
            case .remove:
                parts.removeAll { $0.name == m.name }
                return [.partRemoved(m.name)]
            }

        case .mesh(let block, let payload):
            // Wiederholte Anfrage: Blöcke eines schon vollständigen Netzes verwerfen
            guard meshes[block.hash] == nil else { return [.ignored("Netz \(block.hash) ist schon vollständig")] }
            do {
                guard let done = try assembler.add(block, payload: payload) else { return [] }
                meshes[done.hash] = done.raw
                requested[done.hash] = nil
                return [.meshReady(done.hash)]
            } catch {
                requested[block.hash] = nil
                return [.meshRejected(hash: block.hash, reason: "\(error)")]
            }

        case .state(let m):
            var events = adoptEpoch(m.epoche)
            state = m.state
            rev = m.rev
            cameraRev = max(cameraRev, m.rev)
            events.append(.stateReplaced)
            return events

        case .stateDelta(let m):
            guard m.epoche == epoche, let current = state else {
                return [.ignored("STATE_DELTA ohne vollen Stand dieser Epoche")]
            }
            guard m.rev >= rev else { return [.ignored("STATE_DELTA mit altem rev \(m.rev) < \(rev)")] }
            rev = m.rev
            state = current.applying(m.change)
            if m.change.kamera != nil { cameraRev = max(cameraRev, m.rev) }
            return [.stateChanged(fields: m.change.fieldNames, quelle: m.quelle)]

        case .camera(let m):
            guard m.epoche == epoche, state != nil else { return [.ignored("CAMERA ohne vollen Stand dieser Epoche")] }
            guard m.rev > cameraRev else { return [.ignored("CAMERA mit altem rev")] }
            cameraRev = m.rev
            state?.kamera = m.kamera
            return [.camera(m.quelle)]

        case .commandResult(let r):
            return [.commandResult(r)]

        case .freigabe(let f):
            if let e = epoche, !f.epoche.isEmpty, f.epoche != e { return [.ignored("FREIGABE mit fremder Epoche")] }
            if let i = freigaben.firstIndex(where: { $0.anfrageID == f.anfrageID }) {
                freigaben[i] = f
            } else {
                freigaben.append(f)
            }
            return [.freigabe(f)]

        case .freigabeEnde(let ende):
            if let e = epoche, !ende.epoche.isEmpty, ende.epoche != e {
                return [.ignored("FREIGABE_ENDE mit fremder Epoche")]
            }
            if let id = ende.id {
                if let i = freigaben.firstIndex(where: { $0.anfrageID == ende.anfrageID }) {
                    freigaben[i].eintraege.removeAll { $0.id == id }
                    if freigaben[i].eintraege.isEmpty { freigaben.remove(at: i) }
                }
            } else {
                freigaben.removeAll { $0.anfrageID == ende.anfrageID }
            }
            return [.freigabeEnde(ende)]

        case .watch, .unwatch, .meshRequest, .command:
            return [.ignored("\(message.typeName) ist für Kev CAD bestimmt")]

        case .unknown(let t):
            return [.ignored("unbekannter Typ \(t)")]
        }
    }

    /// Liest einen Rahmen und wendet ihn an.
    public mutating func apply(frame: Frame) throws -> [Event] {
        try apply(MirrorMessage.decode(frame))
    }

    private mutating func adoptEpoch(_ e: String) -> [Event] {
        guard !e.isEmpty, e != epoche else { return [] }
        let old = epoche
        epoche = e
        state = nil
        rev = 0
        cameraRev = 0
        parts = []
        hasScene = false
        pages = [:]
        pageKey = nil
        bbox = nil
        assembler.reset()
        requested = [:]
        freigaben = []  // Anfragen gelten nur in ihrer Epoche; die offenen kommen nach dem HELLO neu
        return [.epochChanged(old: old, new: e)]
    }
}
