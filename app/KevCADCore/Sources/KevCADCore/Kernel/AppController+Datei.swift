import Foundation

// I-8 Datei ans Gerät (PROTOCOL.md, PLAN-IPAD.md Abschnitt 9): Exporte, 3MF, PDF, CSV, Videos und model.py schreibt der
// Kernel am Mac. Am Mac liegen sie also hier und werden im Finder gezeigt; das iPad hat sie nicht und holt sie zum Teilen
// stückweise über seine Verbindung (DATEI_REQ, Antwort DATEI) in seinen Zwischenspeicher.

/// Dateien des Kernels für dieses Gerät bereitstellen (Vertrag zwischen App-Kern und Oberfläche, wie `AppActions`).
@MainActor
public protocol DateiActions: AnyObject {
    /// Kann dieses Gerät Dateien des Kernels bekommen? Am Mac immer; auf dem iPad, wenn der Kernel am Mac `datei-1` kann.
    var kannDateienHolen: Bool { get }
    /// Lokale Datei zu einem Pfad, den der Kernel genannt hat: liegt sie hier, die Datei selbst, sonst eine Kopie vom Mac
    /// im Zwischenspeicher (unverändert seit dem letzten Holen: ohne neue Übertragung). `fortschritt` bekommt den Anteil
    /// von 0 bis 1.
    func dateiFuerGeraet(_ pfad: URL, fortschritt: (@MainActor (Double) -> Void)?) async throws -> URL
    /// Gegenrichtung: Pfad am Mac zu einer Datei dieses Geräts (Referenz, CAD-Datei). Am Mac die Datei selbst; auf dem
    /// iPad schickt die App sie stückweise an den Kernel (DATEI_HOCH), der sie in seinen Eingang legt.
    func dateiAnMac(_ lokal: URL, fortschritt: (@MainActor (Double) -> Void)?) async throws -> URL
}

extension DateiActions {
    public func dateiFuerGeraet(_ pfad: URL) async throws -> URL { try await dateiFuerGeraet(pfad, fortschritt: nil) }
    public func dateiAnMac(_ lokal: URL) async throws -> URL { try await dateiAnMac(lokal, fortschritt: nil) }
}

extension AppController: DateiActions {
    public var kannDateienHolen: Bool {
        !connection.istNetz || live.kernelFaehigkeiten.contains(DateiAnsGeraet.faehigkeit)
    }

    /// Zwischenspeicher für geholte Dateien (je Pfad am Mac ein Ordner, darin die Datei unter ihrem Namen, damit das
    /// Teilen-Blatt den richtigen Namen und Typ zeigt).
    static var dateiAblage: URL {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Vom Mac", isDirectory: true)
    }

    public func dateiFuerGeraet(_ pfad: URL, fortschritt: (@MainActor (Double) -> Void)?) async throws -> URL {
        if FileManager.default.fileExists(atPath: pfad.path) { return pfad }
        guard connection.istNetz else {
            throw RequestError(message: "Die Datei gibt es nicht mehr: \(pfad.lastPathComponent)")
        }
        guard connected else { throw RequestError(message: "Nicht mit dem Mac verbunden") }
        guard live.kernelFaehigkeiten.contains(DateiAnsGeraet.faehigkeit) else {
            throw RequestError(message: "Kev CAD am Mac schickt noch keine Dateien (Mac aktualisieren)")
        }
        return try await dateiHolen(pfad.path, fortschritt: fortschritt)
    }

    /// Holt die Datei stückweise vom Kernel. Eine schon geholte Fassung mit gleicher Größe und Änderungszeit bleibt.
    func dateiHolen(_ pfad: String, fortschritt: (@MainActor (Double) -> Void)?) async throws -> URL {
        let erstes = try await dateiStueck(pfad, ab: 0)
        let ordner = Self.dateiAblage.appendingPathComponent(Self.ablageName(pfad), isDirectory: true)
        let ziel = ordner.appendingPathComponent(erstes.name)
        let fm = FileManager.default
        if let a = try? fm.attributesOfItem(atPath: ziel.path), (a[.size] as? Int) == erstes.groesse,
           let d = a[.modificationDate] as? Date, abs(d.timeIntervalSince1970 - erstes.geaendert) < 1 {
            fortschritt?(1)
            return ziel
        }
        try fm.createDirectory(at: ordner, withIntermediateDirectories: true)
        let teil = ordner.appendingPathComponent(".\(erstes.name).\(UUID().uuidString).teil")
        fm.createFile(atPath: teil.path, contents: nil)
        do {
            let h = try FileHandle(forWritingTo: teil)
            defer { try? h.close() }
            var stueck = erstes
            while true {
                try h.write(contentsOf: stueck.daten)
                let weiter = stueck.ab + stueck.laenge
                fortschritt?(erstes.groesse > 0 ? Double(weiter) / Double(erstes.groesse) : 1)
                if weiter >= erstes.groesse { break }
                guard stueck.laenge > 0 else { throw RequestError(message: "Datei endet vor ihrer Größe") }
                stueck = try await dateiStueck(pfad, ab: weiter)
                guard stueck.groesse == erstes.groesse, stueck.geaendert == erstes.geaendert else {
                    throw RequestError(message: "Die Datei hat sich am Mac während des Holens geändert, bitte noch einmal")
                }
            }
        } catch {
            try? fm.removeItem(at: teil)
            throw error
        }
        try? fm.removeItem(at: ziel)
        try fm.moveItem(at: teil, to: ziel)
        try? fm.setAttributes([.modificationDate: Date(timeIntervalSince1970: erstes.geaendert)], ofItemAtPath: ziel.path)
        return ziel
    }

    private func dateiStueck(_ pfad: String, ab: Int) async throws -> DateiStueckMessage {
        let msg = DateiRequestMessage(id: nextRequestID(), pfad: pfad, ab: ab)
        return try await withCheckedThrowingContinuation { fertig in
            request(msg, timeout: 60) { result in
                switch result {
                case .success(.datei(let s)): fertig.resume(returning: s)
                case .success(let m): fertig.resume(throwing: RequestError(message: "Datei: unerwartete Antwort \(m.typeName)"))
                case .failure(let e): fertig.resume(throwing: e)
                }
            }
        }
    }

    public func dateiAnMac(_ lokal: URL, fortschritt: (@MainActor (Double) -> Void)?) async throws -> URL {
        guard connection.istNetz else { return lokal }  // am Mac liegt die Datei schon dort
        guard connected else { throw RequestError(message: "Nicht mit dem Mac verbunden") }
        guard live.kernelFaehigkeiten.contains(DateiAnsGeraet.faehigkeitHoch) else {
            throw RequestError(message: "Kev CAD am Mac nimmt noch keine Dateien an (Mac aktualisieren)")
        }
        return try await dateiHochladen(lokal, fortschritt: fortschritt)
    }

    /// Schickt eine lokale Datei in Stücken an den Kernel; Antwort ist der Pfad im Eingang am Mac.
    func dateiHochladen(_ lokal: URL, fortschritt: (@MainActor (Double) -> Void)?) async throws -> URL {
        // Dateien aus der Dateien-App sind nur mit Freigabe lesbar
        let freigabe = lokal.startAccessingSecurityScopedResource()
        defer { if freigabe { lokal.stopAccessingSecurityScopedResource() } }
        let h = try FileHandle(forReadingFrom: lokal)
        defer { try? h.close() }
        let groesse = Int(try h.seekToEnd())
        try h.seek(toOffset: 0)
        let sitzung = String(UUID().uuidString.prefix(8)).lowercased()
        var ab = 0
        repeat {
            let stueck = try h.read(upToCount: DateiAnsGeraet.stueckVorgabe) ?? Data()
            let stand = try await dateiHochStueck(
                DateiHochMessage(id: nextRequestID(), sitzung: sitzung, name: lokal.lastPathComponent,
                                 groesse: groesse, ab: ab), daten: stueck)
            ab += stueck.count
            fortschritt?(groesse > 0 ? Double(ab) / Double(groesse) : 1)
            guard stand.empfangen == ab else { throw RequestError(message: "Mac hat \(stand.empfangen) statt \(ab) Byte") }
            if let pfad = stand.pfad { return URL(fileURLWithPath: pfad) }
            guard !stueck.isEmpty else { break }
        } while ab < groesse
        throw RequestError(message: "Mac hat die Datei nicht abgeschlossen")
    }

    private func dateiHochStueck(_ msg: DateiHochMessage, daten: Data) async throws -> DateiHochStandMessage {
        guard send(msg, payload: daten) else { throw RequestError(message: "Nicht mit dem Mac verbunden") }
        // Antwort über die Liste offener Anfragen (wie request, nur mit Nutzlast)
        return try await withCheckedThrowingContinuation { fertig in
            warteAufAntwort(id: msg.id, kind: DateiHochMessage.type, timeout: 60) { result in
                switch result {
                case .success(.dateiHochStand(let s)): fertig.resume(returning: s)
                case .success(let m): fertig.resume(throwing: RequestError(message: "Datei: unerwartete Antwort \(m.typeName)"))
                case .failure(let e): fertig.resume(throwing: e)
                }
            }
        }
    }

    /// Ordnername je Pfad am Mac (ohne Schrägstriche, eindeutig genug für den Zwischenspeicher).
    static func ablageName(_ pfad: String) -> String {
        var h: UInt64 = 0xcbf2_9ce4_8422_2325  // FNV-1a
        for b in pfad.utf8 {
            h ^= UInt64(b)
            h = h &* 0x0000_0100_0000_01b3
        }
        return String(h, radix: 16)
    }
}
