import Foundation
import Security

/// Freigabe vom iPhone (MIRROR.md, Version 1.1), die App-Seite des Spiegels.
///
/// - Öffnet ein Agent mit `freigabe_anfragen` den Dialog im Projektfenster, entsteht hier eine Anfrage mit eigener
///   Kennung, Nonce (128 Bit, nur im Speicher) und Ablauf (24 h). FREIGABE geht an jede geprüfte Gegenstelle (ohne
///   Miete), sobald der Katalog nachgeladen ist; eine später verbundene bekommt sie nach ihrem HELLO.
/// - CMD `freigabe` wird geprüft (Gegenstelle, Anfrage, Nonce, Ablauf, Eintrag, schon entschieden) und dann ausgeführt
///   wie Kevins Klick: Freigeben über `FreigabeActions.freigeben` (CATALOG_SAVE, Bestätigung im neu geladenen Katalog)
///   mit dem Vermerk `freigegeben_von: "Kevin (iPhone)"`, Ablehnen über CATALOG_DELETE mit Bestätigung. CMD_RES erst
///   nach der Bestätigung, danach FREIGABE_ENDE mit `id` an alle.
/// - Entscheidet Kevin am Mac (Dialog, Lagerkatalog) oder schließt er den Dialog, kommt FREIGABE_ENDE mit `grund: "mac"`;
///   eine neue Anfrage zieht die alte zurück; nach 24 h läuft sie ab.
@MainActor
final class FreigabeVomIPhone {
    /// Eine offene Anfrage (die App hat höchstens einen Freigabedialog offen).
    struct Anfrage {
        var anfrageID: String
        /// Kennung des Kernels („F-0001“), für FREIGABE_GESCHLOSSEN.
        var kernelAnfrage: String
        var nonce: String
        var ablauf: Date
        var eintraege: [FreigabeEintrag]
        var grund: String?
        var projekt: String?
        /// Entschiedene Einträge und wie.
        var entschieden: [String: MirrorFreigabeEntscheidung] = [:]
        /// FREIGABE ist hinaus (erst nach dem Nachladen des Katalogs, damit die Kurzdaten stimmen).
        var gesendet = false

        var offen: [FreigabeEintrag] { eintraege.filter { entschieden[$0.id] == nil } }
    }

    /// Ein CMD `freigabe` in Ausführung (je Katalog-ID höchstens eines).
    private struct Laufend {
        var verbindung: Int
        var befehl: String
        var anfrageID: String
        var eintrag: FreigabeEintrag
        var entscheidung: MirrorFreigabeEntscheidung
        var timer: Timer?
        /// Freigabe ist an `FreigabeActions` übergeben (vorher läuft nur die Prüfung im frischen Katalog).
        var uebergeben = false
    }

    /// So lange gilt eine Anfrage.
    var laufzeit: TimeInterval = MirrorProtocol.freigabeLaufzeit
    /// So lange wartet ein CMD `freigabe` höchstens auf die Bestätigung im Katalog.
    var bestaetigungsFrist: TimeInterval = 45
    /// So lange wartet FREIGABE höchstens auf den nachgeladenen Katalog.
    var katalogFrist: TimeInterval = 3

    private unowned let service: MirrorService
    private var controller: AppController { service.controller }
    private(set) var anfrage: Anfrage?
    /// Erledigte Anfragen und warum (für `abgelaufen` bzw. `beendet` im CMD_RES).
    private var beendet: [String: MirrorFreigabeEndeMessage.Grund] = [:]
    private var laufend: [String: Laufend] = [:]
    private var ablaufTimer: Timer?
    private var katalogTimer: Timer?
    /// Eigene Katalog-Anfrage ohne Filter, um verschwundene Einträge sicher zu erkennen.
    private var pruefKatalog: String?

    init(service: MirrorService) {
        self.service = service
    }

    // MARK: Hooks aus dem AppController

    /// FREIGABE_ANFRAGE vom Kernel: neue Anfrage; eine offene wird zurückgezogen.
    func angefragt(_ a: FreigabeAnfrage) {
        if let alt = anfrage {
            // Dieselbe Anfrage noch einmal (gleiche Kennung und Einträge): bleibt. Nach einem Kernel-Neustart zählt der
            // Kernel wieder ab F-0001, dann zählen die Einträge.
            if alt.kernelAnfrage == a.anfrage && alt.eintraege.map(\.id) == a.eintraege.map(\.id) { return }
            beenden(.zurueckgezogen)
        }
        anfrage = Anfrage(
            anfrageID: "\(a.anfrage)-\(Self.zufall(4))", kernelAnfrage: a.anfrage, nonce: Self.zufall(
                MirrorProtocol.freigabeNonceBytes), ablauf: Date().addingTimeInterval(laufzeit), eintraege: a.eintraege,
            grund: a.grund, projekt: controller.model.project?.name)
        ablaufTimer?.invalidate()
        ablaufTimer = Timer.scheduledTimer(withTimeInterval: laufzeit, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated { self?.abgelaufeneBeenden() }
        }
        // Die App lädt den Katalog gerade nach; spätestens nach `katalogFrist` mit dem, was da ist
        katalogTimer?.invalidate()
        katalogTimer = Timer.scheduledTimer(withTimeInterval: katalogFrist, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated { self?.senden() }
        }
        controller.log(.info, "Freigabe vom iPhone möglich (\(a.anfrage)), wartet auf VoiceBridge")
    }

    /// Kevin hat den Dialog am Mac geschlossen.
    func dialogGeschlossen(_ kernelAnfrage: String) {
        guard anfrage?.kernelAnfrage == kernelAnfrage else { return }
        beenden(.mac)
    }

    /// Eine Freigabe ist im neu geladenen Katalog bestätigt (aus `freigabeBestaetigt`).
    func bestaetigt(_ id: String) {
        guard let l = laufend[id], l.entscheidung == .frei, l.uebergeben else { return }
        abschliessen(id, .frei)
    }

    /// Die Freigabe-Warteschlange hat den Eintrag übersprungen, weil er schon frei war.
    func schonFrei(_ id: String) {
        if let l = laufend[id], l.entscheidung == .frei, l.uebergeben {
            abschliessen(id, .schonFrei, "Schon freigegeben (am Mac)")
        }
        entschieden(id, .frei, grund: .mac)
    }

    /// Die Freigabe-Warteschlange ist angehalten (Fehler): alle übergebenen Freigaben vom iPhone sind gescheitert.
    func angehalten(_ text: String) {
        for (id, l) in laufend where l.entscheidung == .frei && l.uebergeben {
            abschliessen(id, .katalogfehler, text)
        }
    }

    /// Neuer Katalog (nach jedem CATALOG, nach der Prüfung der Freigaben): FREIGABE senden, Entscheidungen am Mac
    /// erkennen.
    func katalogAktualisiert(_ m: CatalogMessage) {
        let vollstaendig = pruefKatalog != nil && m.replyTo == pruefKatalog
        if vollstaendig { pruefKatalog = nil }
        guard anfrage != nil else { return }
        if anfrage?.gesendet == false { senden() }
        guard let a = anfrage else { return }
        var unklar = false
        for e in a.offen where laufend[e.id] == nil {
            let vorgeschlagen = e.kind == "material"
                ? m.catalog.material(e.id).map(\.vorgeschlagen) : m.catalog.item(e.id).map(\.vorgeschlagen)
            switch vorgeschlagen {
            case .some(false): entschieden(e.id, .frei, grund: .mac)
            case .some(true): break
            case .none:
                // Fehlt der Eintrag in einer gefilterten Antwort (Suche im Lagerkatalog), erst ungefiltert nachsehen
                if vollstaendig { entschieden(e.id, .abgelehnt, grund: .mac) } else { unklar = true }
            }
        }
        if unklar && pruefKatalog == nil { katalogUngefiltertLaden() }
    }

    /// Katalog ohne Suche nachladen (die Antwort läuft wie jede über `applyCatalog` und damit hierher zurück).
    private func katalogUngefiltertLaden() {
        guard controller.helloReceived else { return }
        let req = CatalogRequestMessage(id: controller.nextRequestID())
        pruefKatalog = req.id
        controller.request(req, timeout: AppController.catalogTimeout) { [weak self] result in
            if case .failure = result, self?.pruefKatalog == req.id { self?.pruefKatalog = nil }
        }
    }

    // MARK: Verbindungen

    /// Nach dem HELLO einer geprüften Gegenstelle: die offene Anfrage gleich hinterher.
    func nachHello(_ verbindung: Int) {
        abgelaufeneBeenden()
        guard let msg = nachricht(), anfrage?.gesendet == true else { return }
        service.server.send(msg, to: [verbindung])
    }

    private func nachricht() -> MirrorFreigabeMessage? {
        guard let a = anfrage, !a.offen.isEmpty else { return nil }
        let catalog = controller.model.catalog
        let eintraege = a.offen.map { Self.eintrag($0, catalog: catalog, grund: a.grund, projekt: a.projekt) }
        return MirrorFreigabeMessage(
            epoche: service.epoche, anfrageID: a.anfrageID, nonce: a.nonce, ablauf: MirrorFreigabeZeit.text(a.ablauf),
            eintraege: eintraege)
    }

    private func senden() {
        katalogTimer?.invalidate()
        katalogTimer = nil
        guard anfrage != nil, anfrage?.gesendet == false else { return }
        anfrage?.gesendet = true
        guard let msg = nachricht() else { return }
        let an = service.freigabeEmpfaenger
        service.server.send(msg, to: an)
        if !an.isEmpty {
            controller.log(.info, "Freigabe \(msg.anfrageID) ans iPhone: " + msg.eintraege.map(\.id).joined(separator: ", "))
        }
    }

    private func ende(_ m: MirrorFreigabeEndeMessage) {
        service.server.send(m, to: service.freigabeEmpfaenger)
    }

    // MARK: Befehl vom iPhone

    /// CMD `freigabe`. `urteil` ist die Prüfung der Gegenstelle direkt vor diesem Befehl.
    func befehl(_ cmd: MirrorCommand, von verbindung: Int, urteil: MirrorGegenstelle.Urteil) {
        let b = cmd.freigabeBefehl
        func antwort(_ status: MirrorFreigabeStatus, _ fehler: String? = nil) {
            service.server.send(
                MirrorCommandResult.freigabe(replyTo: cmd.id, status: status, fehler: fehler), to: [verbindung])
            if status != .frei && status != .abgelehnt {
                controller.log(.warning, "Freigabe vom iPhone abgewiesen (\(status.rawValue)): \(fehler ?? "")")
            }
        }
        guard urteil.erlaubt else {
            return antwort(.nichtErlaubt, "Nur die VoiceBridge-App darf freigeben (\(urteil.grund), PID \(urteil.pid)).")
        }
        guard let entscheidung = b.entscheidung, !b.id.isEmpty, !b.anfrageID.isEmpty, !b.nonce.isEmpty else {
            return antwort(.ungueltig, "anfrage_id, nonce, id und entscheidung (frei oder abgelehnt) angeben.")
        }
        abgelaufeneBeenden()
        guard let a = anfrage, a.anfrageID == b.anfrageID else {
            switch beendet[b.anfrageID] {
            case .abgelaufen?: return antwort(.abgelaufen, "Die Anfrage ist abgelaufen.")
            case let g?: return antwort(.beendet, "Die Anfrage ist erledigt (\(g.rawValue)).")
            case nil: return antwort(.ungueltig, "Die Anfrage ist unbekannt.")
            }
        }
        guard Self.gleich(b.nonce, a.nonce) else { return antwort(.ungueltig, "Die Nonce passt nicht zur Anfrage.") }
        guard let e = a.eintraege.first(where: { $0.id == b.id }) else {
            return antwort(.ungueltig, "„\(b.id)“ gehört nicht zu dieser Anfrage.")
        }
        guard a.entschieden[e.id] == nil, laufend[e.id] == nil else {
            return antwort(.verbraucht, "„\(e.name)“ ist schon entschieden oder wird gerade ausgeführt.")
        }
        guard !AppInfo.isDemoMode else { return antwort(.katalogfehler, "Demomodus ohne Kernel.") }
        // Ab hier gilt der Eintrag als in Ausführung: eine Wiederholung bekommt `verbraucht`
        let timer = Timer.scheduledTimer(withTimeInterval: bestaetigungsFrist, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated {
                self?.abschliessen(
                    e.id, .katalogfehler, "Keine Bestätigung im Katalog binnen \(Int(self?.bestaetigungsFrist ?? 0)) s.")
            }
        }
        laufend[e.id] = Laufend(
            verbindung: verbindung, befehl: cmd.id, anfrageID: a.anfrageID, eintrag: e, entscheidung: entscheidung,
            timer: timer)
        controller.log(.info, "Freigabe vom iPhone: \(e.id) \(entscheidung.rawValue) (\(urteil.grund))")
        // Erst im frischen, ungefilterten Katalog nachsehen (am Mac könnte sich inzwischen etwas geändert haben)
        let req = CatalogRequestMessage(id: controller.nextRequestID())
        controller.request(req, timeout: AppController.catalogTimeout) { [weak self] result in
            guard let self, self.laufend[e.id]?.befehl == cmd.id else { return }
            switch result {
            case .success(.catalog(let m)):
                // Erst nachdem `applyCatalog` den Katalog übernommen hat: die Freigabe liest `model.catalog`
                DispatchQueue.main.async {
                    MainActor.assumeIsolated {
                        guard self.laufend[e.id]?.befehl == cmd.id else { return }
                        self.ausfuehren(e, entscheidung, katalog: m.catalog)
                    }
                }
            case .success(let m): self.abschliessen(e.id, .katalogfehler, "Unerwartete Antwort \(m.typeName)")
            case .failure(let err): self.abschliessen(e.id, .katalogfehler, err.message)
            }
        }
    }

    private func ausfuehren(_ e: FreigabeEintrag, _ entscheidung: MirrorFreigabeEntscheidung, katalog: Catalog) {
        let found: (vorgeschlagen: Bool, ebene: CatalogLevel)? = e.kind == "material"
            ? katalog.material(e.id).map { ($0.vorgeschlagen, $0.ebene) }
            : katalog.item(e.id).map { ($0.vorgeschlagen, $0.ebene) }
        guard let found else {
            abschliessen(e.id, .fehlt, "„\(e.name)“ steht nicht mehr im Katalog.")
            entschieden(e.id, .abgelehnt, grund: .mac)
            return
        }
        guard found.vorgeschlagen else {
            abschliessen(e.id, .schonFrei, "„\(e.name)“ ist schon freigegeben.")
            entschieden(e.id, .frei, grund: .mac)
            return
        }
        switch entscheidung {
        case .frei:
            laufend[e.id]?.uebergeben = true
            var mitVermerk = e
            mitVermerk.von = MirrorProtocol.freigabeVonIPhone
            controller.freigeben([mitVermerk])  // derselbe Weg wie Kevins Klick im Dialog
        case .abgelehnt:
            ablehnen(e, ebene: found.ebene)
        }
    }

    /// Ablehnen = Vorschlag löschen (wie im Lagerkatalog), danach im ungefilterten Katalog bestätigen.
    private func ablehnen(_ e: FreigabeEintrag, ebene: CatalogLevel) {
        guard ebene.isEditable else {
            return abschliessen(e.id, .katalogfehler, "„\(e.name)“ liegt im mitgelieferten Katalog.")
        }
        let msg = CatalogDeleteMessage(id: controller.nextRequestID(), kind: e.kind, entryID: e.id, ebene: ebene)
        controller.request(msg, timeout: AppController.catalogTimeout) { [weak self] result in
            guard let self, self.laufend[e.id] != nil else { return }
            switch result {
            case .success(.ack(let ack)) where ack.ok:
                self.controller.log(.info, "Katalog: \(e.id) vom iPhone abgelehnt und gelöscht (\(ebene.title))")
                let req = CatalogRequestMessage(id: self.controller.nextRequestID())
                self.controller.request(req, timeout: AppController.catalogTimeout) { [weak self] result in
                    guard let self, self.laufend[e.id] != nil else { return }
                    guard case .success(.catalog(let m)) = result else {
                        return self.abschliessen(
                            e.id, .katalogfehler, "Gelöscht, aber der Katalog ließ sich danach nicht neu laden.")
                    }
                    let noch = e.kind == "material" ? m.catalog.material(e.id)?.ebene : m.catalog.item(e.id)?.ebene
                    if let noch {
                        self.abschliessen(
                            e.id, .katalogfehler,
                            "„\(e.name)“ steht nach dem Löschen weiter im Katalog (Ebene \(noch.title)).")
                    } else {
                        self.abschliessen(e.id, .abgelehnt)
                    }
                }
            case .success(.ack(let ack)):
                self.abschliessen(e.id, .katalogfehler, ack.message ?? "Der Kernel hat das Löschen abgelehnt.")
            case .success(let m):
                self.abschliessen(e.id, .katalogfehler, "Unerwartete Antwort \(m.typeName)")
            case .failure(let err):
                self.abschliessen(e.id, .katalogfehler, err.message)
            }
        }
    }

    /// CMD_RES schicken; bei Erfolg den Eintrag als vom iPhone entschieden melden.
    private func abschliessen(_ id: String, _ status: MirrorFreigabeStatus, _ fehler: String? = nil) {
        guard let l = laufend.removeValue(forKey: id) else { return }
        l.timer?.invalidate()
        service.server.send(MirrorCommandResult.freigabe(replyTo: l.befehl, status: status, fehler: fehler),
                            to: [l.verbindung])
        switch status {
        case .frei:
            entschieden(id, .frei, grund: .iphone)
        case .abgelehnt:
            entschieden(id, .abgelehnt, grund: .iphone)
        default:
            controller.log(.warning, "Freigabe vom iPhone für \(id): \(status.rawValue)" + (fehler.map { ", \($0)" } ?? ""))
        }
    }

    // MARK: Ende

    /// Ein Eintrag der offenen Anfrage ist entschieden: FREIGABE_ENDE mit `id`, nach dem letzten auch ohne.
    private func entschieden(_ id: String, _ ergebnis: MirrorFreigabeEntscheidung, grund: MirrorFreigabeEndeMessage.Grund) {
        guard var a = anfrage, a.eintraege.contains(where: { $0.id == id }), a.entschieden[id] == nil else { return }
        a.entschieden[id] = ergebnis
        anfrage = a
        if a.gesendet {
            ende(MirrorFreigabeEndeMessage(epoche: service.epoche, anfrageID: a.anfrageID, id: id, grund: grund,
                                           ergebnis: ergebnis))
        }
        if a.offen.isEmpty { beenden(grund) }
    }

    /// Die ganze Anfrage endet; die Nonce wird vergessen.
    private func beenden(_ grund: MirrorFreigabeEndeMessage.Grund) {
        guard let a = anfrage else { return }
        anfrage = nil
        ablaufTimer?.invalidate()
        ablaufTimer = nil
        katalogTimer?.invalidate()
        katalogTimer = nil
        beendet[a.anfrageID] = grund
        if a.gesendet { ende(MirrorFreigabeEndeMessage(epoche: service.epoche, anfrageID: a.anfrageID, grund: grund)) }
        controller.log(.info, "Freigabe \(a.anfrageID) für das iPhone beendet (\(grund.rawValue))")
    }

    private func abgelaufeneBeenden(now: Date = Date()) {
        if let a = anfrage, now >= a.ablauf { beenden(.abgelaufen) }
    }

    // MARK: Hilfen

    /// Kurzdaten einer Karte aus dem Katalog: Maße, Preis, Händler (bzw. Dichte und Preis je kg).
    static func eintrag(_ e: FreigabeEintrag, catalog: Catalog?, grund: String?, projekt: String?)
        -> MirrorFreigabeEintrag
    {
        func knapp(_ s: String?, _ n: Int) -> String? {
            guard let s = s?.trimmingCharacters(in: .whitespacesAndNewlines), !s.isEmpty else { return nil }
            return s.count > n ? String(s.prefix(n - 1)) + "…" : s
        }
        var art = e.kind == "material" ? "material" : ""
        var name = e.name
        var teile: [String] = []
        var link: String?
        if e.kind == "material", let m = catalog?.material(e.id) {
            name = m.name
            teile.append(KevFormat.number(m.dichte, digits: 2) + " g/cm³")
            if let p = m.preisJeKg { teile.append(KevFormat.euro(p) + "/kg") }
            link = FreigabeListe.url(m.entry["bezugsquelle"]?["url"])?.absoluteString
        } else if let item = catalog?.item(e.id) {
            let x = item.entry
            name = item.name
            art = item.art
            if let masse = FreigabeListe.masseText(x["masse"]) { teile.append(masse) }
            if let preis = Catalog.priceText(x["preis"]) { teile.append(preis) }
            let url = FreigabeListe.url(x["bezugsquelle"]?["url"]) ?? FreigabeListe.url(x["url"])
            link = url?.absoluteString
            let haendler = x["bezugsquelle"]?["name"]?.lenientString ?? x["haendler"]?.lenientString
                ?? x["hersteller"]?.lenientString ?? url?.host
            if let h = haendler, !h.isEmpty { teile.append(h) }
        }
        return MirrorFreigabeEintrag(
            id: e.id, kind: e.kind, name: knapp(name, 160) ?? e.id, art: art,
            kurz: knapp(teile.joined(separator: " · "), 200) ?? "", link: link, grund: knapp(grund, 300),
            projekt: knapp(projekt, 120))
    }

    /// `n` Byte Zufall als Hex (SecRandomCopyBytes).
    static func zufall(_ n: Int) -> String {
        var bytes = [UInt8](repeating: 0, count: n)
        if SecRandomCopyBytes(kSecRandomDefault, n, &bytes) != errSecSuccess {
            var rng = SystemRandomNumberGenerator()
            for i in bytes.indices { bytes[i] = UInt8.random(in: 0...255, using: &rng) }
        }
        return bytes.map { String(format: "%02x", $0) }.joined()
    }

    /// Vergleich in konstanter Zeit (gleiche Länge vorausgesetzt).
    static func gleich(_ a: String, _ b: String) -> Bool {
        let x = Array(a.utf8), y = Array(b.utf8)
        guard x.count == y.count, !x.isEmpty else { return false }
        var d: UInt8 = 0
        for i in x.indices { d |= x[i] ^ y[i] }
        return d == 0
    }
}
