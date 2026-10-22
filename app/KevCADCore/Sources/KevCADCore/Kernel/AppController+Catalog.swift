import AppKit
import Foundation

// Phase 2: Stückliste, Lagerkatalog und Neustart nach einem Update (CatalogActions in AppModel.swift).

extension AppController: CatalogActions {
    /// Zeitlimit für BOM- und Katalog-Anfragen. Ältere Kernel antworten gar nicht, die Oberfläche soll nicht ewig warten.
    static var catalogTimeout: TimeInterval = 15

    // MARK: Stückliste

    public func requestBOM() {
        requestBOM(quiet: false)
    }

    func requestBOM(quiet: Bool) {
        guard !AppInfo.isDemoMode else { return }
        let msg = BOMRequestMessage(id: nextRequestID())
        request(msg, timeout: Self.catalogTimeout) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.bom):
                break  // schon in handle(_:) übernommen
            case .success(let m):
                self.log(.warning, "Stückliste: unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                if quiet {
                    if !self.bomSilenceLogged {
                        self.bomSilenceLogged = true
                        self.log(.info, "Kernel liefert keine Stückliste (\(e.message))")
                    }
                } else {
                    self.log(.warning, "Stückliste nicht erhalten: \(e.message)")
                }
            }
        }
    }

    /// Nach dem Verbinden schickt der Kernel Projekt und Teile, aber keine Stückliste: einmal nachfragen.
    func requestBOMAfterConnect() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
            MainActor.assumeIsolated {
                guard let self, self.helloReceived, self.model.project != nil, self.model.bom == nil,
                    !self.model.isRunningRun
                else { return }
                self.requestBOM(quiet: true)
            }
        }
    }

    func applyBOM(_ message: BOMMessage) {
        let bom = message.bom
        model.bom = bom
        // Nach jedem Lauf: hat Claude dabei Lagerteile oder Materialien vorgeschlagen?
        refreshCatalogQuietly()
        let price = bom.totals.preis.map { " · \(KevFormat.number($0, digits: 2)) €" } ?? ""
        log(.info, "Stückliste zu Lauf \(bom.run): \(bom.lines.count) Positionen, \(bom.totals.teile) Teile, "
            + "\(KevFormat.number(bom.totals.kg, digits: 2)) kg\(price)")
    }

    public func showBOMLine(_ line: BOMLine) {
        let refs = line.teile.compactMap(ElementRef.init).map(\.partRef)
        let (known, missing) = scene.expand(refs)
        guard !known.isEmpty else {
            log(.warning, "Stückliste Pos. \(line.pos): Teile nicht in der Szene (\(line.teile.joined(separator: ", ")))")
            return
        }
        if !missing.isEmpty { log(.info, "Stückliste Pos. \(line.pos): nicht gefunden: \(missing.joined(separator: ", "))") }
        // Ausgeblendete Teile der Zeile wieder zeigen, sonst sieht man die Auswahl nicht
        let hidden = known.map(\.part).filter { !scene.isVisible($0) }
        if !hidden.isEmpty {
            scene.setVisible(hidden, true)
            updateParts()
        }
        measurePending = []
        applySelection(known)
        if let b = scene.worldBounds(of: known) { viewport.fit(b, animated: true) }
    }

    // MARK: Katalog

    public func requestCatalog(query: String?, art: String?) {
        catalogQuery = (query, art)
        catalogWanted = true
        guard !AppInfo.isDemoMode else { return }
        guard helloReceived else {
            model.catalogActivity = .failed("Der Kernel ist nicht verbunden.")
            return
        }
        if model.catalog == nil { model.catalogActivity = .loading }
        sendCatalogRequest()
    }

    /// Mit der letzten Suche neu laden, ohne Ladezustand (Ergebnis von Speichern/Löschen bleibt stehen). Gibt die ID der
    /// Anfrage zurück (nil ohne Kernel).
    @discardableResult
    func reloadCatalog() -> String? {
        guard !AppInfo.isDemoMode, helloReceived else { return nil }
        return sendCatalogRequest()
    }

    @discardableResult
    private func sendCatalogRequest() -> String {
        let msg = CatalogRequestMessage(id: nextRequestID(), query: catalogQuery.query, art: catalogQuery.art)
        request(msg, timeout: Self.catalogTimeout) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.catalog):
                break  // schon in handle(_:) übernommen
            case .success(let m):
                self.catalogFailed("Unerwartete Antwort \(m.typeName) auf die Katalog-Anfrage")
            case .failure(let e):
                let text = e.message.contains("keine Antwort")
                    ? "Der Kernel antwortet nicht auf die Katalog-Anfrage. Ältere Kernel-Versionen kennen den "
                        + "Lagerkatalog noch nicht." : e.message
                self.catalogFailed(text)
                // Nachladen nach einer Freigabe gescheitert: Ob sie wirkt, ist offen, also melden statt warten
                if let check = self.approvalCheck, check.reloadID == msg.id {
                    self.approvalCheck = nil
                    self.saveFailed("Freigabe von „\(check.id)“ nicht bestätigt: Der Katalog ließ sich danach nicht neu "
                        + "laden (\(e.message)).")
                }
            }
        }
        return msg.id
    }

    private func catalogFailed(_ text: String) {
        log(.warning, "Lagerkatalog: \(text)")
        // Ein vorhandener Katalog bleibt stehen; nur beim ersten Laden zeigt die Oberfläche den Fehler als Leerzustand
        if model.catalog == nil || model.catalogActivity == .loading { model.catalogActivity = .failed(text) }
    }

    func applyCatalog(_ message: CatalogMessage) {
        let hadCatalog = model.catalog != nil
        model.catalog = message.catalog
        if model.catalogActivity == .loading { model.catalogActivity = .idle }
        // Nur ein Fehler beim ersten Laden ist damit erledigt. Fehler beim Speichern, Freigeben oder Löschen bleiben
        // stehen, bis die nächste Aktion beginnt: Früher löschte jedes Nachladen (etwa still nach jeder Stückliste) die
        // Meldung nach wenigen Sekunden, und eine gescheiterte Freigabe sah aus wie keine.
        if !hadCatalog, case .failed = model.catalogActivity { model.catalogActivity = .idle }
        verifyApproval(message)
    }

    /// Nach einer Freigabe: Das Nachladen (Anfrage `reloadID`) muss den Eintrag als frei zeigen, sonst ist die Freigabe
    /// nicht wirksam (z. B. überdeckt ein Vorschlag gleicher ID in einer späteren Ebene den gespeicherten Eintrag).
    private func verifyApproval(_ message: CatalogMessage) {
        guard let check = approvalCheck, message.replyTo == check.reloadID else { return }
        approvalCheck = nil
        let what = check.kind == "material" ? "das Material" : "den Eintrag"
        let found: (suggested: Bool, ebene: CatalogLevel)? = check.kind == "material"
            ? message.catalog.material(check.id).map { ($0.vorgeschlagen, $0.ebene) }
            : message.catalog.item(check.id).map { ($0.vorgeschlagen, $0.ebene) }
        guard let found else {
            saveFailed("Freigabe von „\(check.id)“ nicht wirksam: Nach dem Speichern fehlt \(what) im Katalog.")
            return
        }
        guard found.suggested else { return }
        let reason = found.ebene != check.ebene
            ? " Ein Vorschlag gleicher ID in der Ebene „\(found.ebene.title)“ überdeckt ihn; dort freigeben oder löschen."
            : ""
        saveFailed("Freigabe von „\(check.id)“ nicht wirksam: Der Kernel hat gespeichert, der Katalog führt \(what) aber "
            + "weiter als Vorschlag.\(reason)")
    }

    public func saveCatalogEntry(kind: String, json: Data, ebene: CatalogLevel) {
        guard !AppInfo.isDemoMode else { return }
        guard let entry = try? JSONDecoder().decode(JSONValue.self, from: json), entry.objectValue != nil else {
            model.catalogActivity = .failed("Der Eintrag ist kein gültiges JSON-Objekt.")
            return
        }
        guard ebene.isEditable else {
            model.catalogActivity = .failed("In den mitgelieferten Katalog kann nicht gespeichert werden.")
            return
        }
        let entryID = entry["id"]?.lenientString ?? "?"
        guard helloReceived else {
            model.catalogActivity = .failed("Der Kernel ist nicht verbunden, der Eintrag wurde nicht gespeichert.")
            return
        }
        // Freigabe eines Vorschlags: status frei für einen Eintrag, der im Katalog noch vorgeschlagen ist
        let wasSuggested = kind == "material"
            ? model.catalog?.material(entryID)?.vorgeschlagen == true
            : model.catalog?.item(entryID)?.vorgeschlagen == true
        let approving = wasSuggested && (entry["status"]?.stringValue ?? "frei") == "frei"
        let action = approving ? "freigegeben" : "gespeichert"
        approvalCheck = nil
        model.catalogActivity = .saving
        let msg = CatalogSaveMessage(id: nextRequestID(), kind: kind, entry: entry, ebene: ebene)
        request(msg, timeout: Self.catalogTimeout) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)) where a.ok:
                let note = a.message.flatMap { $0.isEmpty ? nil : $0 }
                self.model.catalogActivity = .saved(id: entryID, message: note)
                self.log(.info, "Katalog: \(entryID) \(action) (\(ebene.title))" + (note.map { ", \($0)" } ?? ""))
                let reloadID = self.reloadCatalog()
                if approving, let reloadID {
                    self.approvalCheck = (kind, entryID, ebene, reloadID)
                } else if approving {
                    self.saveFailed("Freigabe von „\(entryID)“ nicht bestätigt: Der Kernel hat gespeichert, ist danach aber "
                        + "nicht mehr verbunden; nach dem Neuverbinden im Katalog prüfen.")
                }
            case .success(.ack(let a)):
                self.saveFailed("„\(entryID)“ nicht \(action): " + (a.message ?? "Der Kernel hat den Eintrag abgelehnt."))
            case .success(let m):
                self.saveFailed("„\(entryID)“ nicht \(action): unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                let reason = e.message.contains("keine Antwort")
                    ? "Der Kernel hat nicht geantwortet (\(e.message)). Ob gespeichert wurde, zeigt der Katalog nach "
                        + "dem Neuladen." : e.message
                self.saveFailed("„\(entryID)“ nicht \(action): \(reason)")
            }
        }
    }

    public func deleteCatalogEntry(kind: String, id: String, ebene: CatalogLevel) {
        guard !AppInfo.isDemoMode else { return }
        guard ebene.isEditable else {
            model.catalogActivity = .failed("Mitgelieferte Einträge lassen sich nicht löschen.")
            return
        }
        guard helloReceived else {
            model.catalogActivity = .failed("Der Kernel ist nicht verbunden, der Eintrag wurde nicht gelöscht.")
            return
        }
        model.catalogActivity = .saving
        let msg = CatalogDeleteMessage(id: nextRequestID(), kind: kind, entryID: id, ebene: ebene)
        request(msg, timeout: Self.catalogTimeout) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(.ack(let a)) where a.ok:
                self.model.catalogActivity = .deleted(id: id)
                self.log(.info, "Katalog: \(id) gelöscht (\(ebene.title))")
                self.reloadCatalog()
            case .success(.ack(let a)):
                self.saveFailed(a.message ?? "Der Kernel hat das Löschen abgelehnt.")
            case .success(let m):
                self.saveFailed("Unerwartete Antwort \(m.typeName)")
            case .failure(let e):
                self.saveFailed(e.message)
            }
        }
    }

    private func saveFailed(_ text: String) {
        model.catalogActivity = .failed(text)
        log(.warning, "Lagerkatalog: \(text)")
    }

    /// Katalog im Hintergrund nachladen, damit Vorschläge von Claude auch ohne offenes Katalogfenster auffallen.
    /// Höchstens alle 5 s; antwortet der Kernel nicht (ältere Version), bis zum nächsten HELLO nicht mehr.
    func refreshCatalogQuietly() {
        guard !AppInfo.isDemoMode, helloReceived, !quietCatalogOff else { return }
        let now = Date()
        if let last = lastQuietCatalog, now.timeIntervalSince(last) < 5 { return }
        lastQuietCatalog = now
        let msg = CatalogRequestMessage(id: nextRequestID(), query: nil, art: nil)
        request(msg, timeout: Self.catalogTimeout) { [weak self] result in
            guard let self, case .failure(let e) = result else { return }
            self.quietCatalogOff = true
            self.log(.info, "Lagerkatalog im Hintergrund nicht geladen (\(e.message))")
        }
    }

    // MARK: Update

    /// Absichtlich leer: Nach einem Update startet das Update-Skript die App selbst neu und stellt Projekt und Kamera
    /// wieder her (Entscheidung vom 21.10.2026, wird auf main gebaut). Die Oberfläche zeigt keinen Hinweis.
    public func relaunchForUpdate() {}
}

extension AppModel {
    /// Lauf aktiv (RUN_START bis RUN_END/RUN_ERROR).
    var isRunningRun: Bool {
        if case .running = run { return true }
        return false
    }
}

// MARK: - Inventar-Regel

extension AppController: InventoryActions {
    static let inventarDefaultsKey = "KevCADInventarRegel"

    /// Einstellung je Projektordner (falls der Kernel sie nicht im PROJECT mitschickt).
    static func storedInventarRegel(_ project: URL, defaults: UserDefaults = .standard) -> Bool? {
        (defaults.dictionary(forKey: inventarDefaultsKey) as? [String: Bool])?[project.standardizedFileURL.path]
    }

    static func storeInventarRegel(_ on: Bool, project: URL, defaults: UserDefaults = .standard) {
        var all = (defaults.dictionary(forKey: inventarDefaultsKey) as? [String: Bool]) ?? [:]
        all[project.standardizedFileURL.path] = on
        defaults.set(all, forKey: inventarDefaultsKey)
    }

    /// Beim Öffnen eines Projekts: Angabe des Kernels, sonst die gemerkte, sonst an; dann dem Kernel melden.
    func adoptInventarRegel(_ p: ProjectMessage, project: URL) {
        let on = p.inventarRegel ?? Self.storedInventarRegel(project) ?? true
        if model.inventarRegel != on { model.inventarRegel = on }
        if p.inventarRegel == nil { sendSettings() }
    }

    public func setInventarRegel(_ on: Bool) {
        guard model.inventarRegel != on else { return }
        model.inventarRegel = on
        if let project = model.project?.path { Self.storeInventarRegel(on, project: project) }
        log(.info, "Inventar-Regel \(on ? "an" : "aus")" + (on ? "" : " (nur für Nachbauten und Skizzen)"))
        sendSettings()
        // Verstöße und Stückliste hängen an der Regel: gleich neu rechnen
        if model.project != nil, !AppInfo.isDemoMode, helloReceived { runModel() }
    }
}
