import Foundation

// Freigabe im Projektfenster (Strang „Feinschliff 2“, Model/Freigabe.swift): FREIGABE_ANFRAGE öffnet den Dialog,
// „Freigeben“ und „Alle freigeben“ laufen über dieselbe Freigabe wie im Lagerkatalog (CATALOG_SAVE mit status frei und
// Prüfung im neu geladenen Katalog), einer nach dem anderen. Schließen meldet FREIGABE_GESCHLOSSEN.

extension AppController: FreigabeActions {
    /// Claude bittet um Freigabe: Dialog öffnen (die Oberfläche beobachtet `model.freigabe.anfrage`), bestätigen und den
    /// Katalog frisch laden, damit die Vorschläge zu sehen sind.
    func handleFreigabeAnfrage(_ a: FreigabeAnfrage) {
        if let alt = model.freigabe.anfrage, alt.anfrage != a.anfrage {
            meldeGeschlossen(alt)  // eine ältere Anfrage ist damit erledigt
        }
        model.freigabe.anfrage = a
        model.freigabe.freigegeben = []
        model.freigabe.fehler = nil
        send(AckOutMessage(replyTo: a.requestID, ok: true, message: "Freigabedialog im Projektfenster offen"))
        reloadCatalog()
        log(.info, "Claude bittet um Freigabe (\(a.anfrage)): " + a.eintraege.map(\.id).joined(separator: ", "))
        mirror?.freigabe.angefragt(a)  // auch aufs iPhone (MIRROR.md 1.1), am Agenten vorbei
    }

    public func freigeben(_ eintraege: [FreigabeEintrag]) {
        guard !AppInfo.isDemoMode else { return }
        model.freigabe.fehler = nil
        for e in eintraege where !model.freigabe.wartet(e.id) {
            model.freigabe.warteschlange.append(e)
        }
        naechsteFreigabe()
    }

    public func freigabeSchliessen() {
        if let a = model.freigabe.anfrage {
            meldeGeschlossen(a)
            mirror?.freigabe.dialogGeschlossen(a.anfrage)
        }
        model.freigabe.anfrage = nil
        model.freigabe.freigegeben = []
    }

    public func freigabeFehlerVerwerfen() {
        model.freigabe.fehler = nil
    }

    private func meldeGeschlossen(_ a: FreigabeAnfrage) {
        let catalog = model.catalog
        var frei: [String] = [], ab: [String] = [], offen: [String] = []
        for e in a.eintraege {
            let vorgeschlagen = e.kind == "material"
                ? catalog?.material(e.id).map(\.vorgeschlagen) : catalog?.item(e.id).map(\.vorgeschlagen)
            switch vorgeschlagen {
            case .some(true): offen.append(e.id)
            case .some(false): frei.append(e.id)
            case .none: if catalog != nil { ab.append(e.id) } else { offen.append(e.id) }
            }
        }
        send(FreigabeGeschlossenMessage(anfrage: a.anfrage, freigegeben: frei, abgelehnt: ab, offen: offen))
        log(.info, "Freigabedialog geschlossen (\(a.anfrage)): \(frei.count) freigegeben, \(offen.count) offen")
    }

    /// Nächsten Eintrag der Warteschlange freigeben, falls keiner läuft. Schon freie Einträge überspringen.
    func naechsteFreigabe() {
        guard model.freigabe.laeuft == nil else { return }
        while !model.freigabe.warteschlange.isEmpty {
            let e = model.freigabe.warteschlange.removeFirst()
            guard let catalog = model.catalog else {
                freigabeAnhalten("Der Lagerkatalog ist nicht geladen, die Freigabe wurde nicht gesendet.")
                return
            }
            let gefunden: (json: Data, ebene: CatalogLevel, vorgeschlagen: Bool)? = e.kind == "material"
                ? catalog.material(e.id).map { ($0.json, $0.ebene, $0.vorgeschlagen) }
                : catalog.item(e.id).map { ($0.json, $0.ebene, $0.vorgeschlagen) }
            guard let gefunden else {
                freigabeAnhalten("„\(e.name)“ steht nicht mehr im Katalog (inzwischen geändert oder entfernt). Katalog "
                    + "neu laden und erneut versuchen.")
                return
            }
            guard gefunden.vorgeschlagen else {
                if !model.freigabe.freigegeben.contains(e.id) { model.freigabe.freigegeben.append(e.id) }
                mirror?.freigabe.schonFrei(e.id)
                continue
            }
            model.freigabe.laeuft = e.id
            // Vom iPhone mit Vermerk `freigegeben_von` (MIRROR.md 1.1), sonst wie bisher
            saveCatalogEntry(
                kind: e.kind, json: Catalog.approvedJSON(gefunden.json, von: e.von),
                ebene: gefunden.ebene.isEditable ? gefunden.ebene : .eigen)
            // Sofort gescheitert (nicht verbunden, ungültiges JSON): saveCatalogEntry setzt nur den Katalogzustand
            if case .failed(let text) = model.catalogActivity, model.freigabe.laeuft == e.id {
                freigabeGescheitert(text)
            }
            return
        }
    }

    /// Die Freigabe von `id` ist im neu geladenen Katalog bestätigt.
    func freigabeBestaetigt(_ id: String) {
        guard model.freigabe.laeuft == id else { return }
        model.freigabe.laeuft = nil
        if !model.freigabe.freigegeben.contains(id) { model.freigabe.freigegeben.append(id) }
        mirror?.freigabe.bestaetigt(id)
        naechsteFreigabe()
    }

    /// Freigabe gescheitert (aus `saveFailed`, auch bei anderen Katalogaktionen gerufen): nur wenn eine Freigabe des
    /// Projektfensters läuft, anhalten.
    func freigabeGescheitert(_ text: String) {
        guard model.freigabe.laeuft != nil || !model.freigabe.warteschlange.isEmpty else { return }
        freigabeAnhalten(text)
    }

    /// Warteschlange anhalten; der Fehler bleibt sichtbar, bis Kevin ihn wegklickt oder neu freigibt.
    private func freigabeAnhalten(_ text: String) {
        model.freigabe.laeuft = nil
        model.freigabe.warteschlange = []
        model.freigabe.fehler = text
        log(.warning, "Freigabe: \(text)")
        mirror?.freigabe.angehalten(text)
    }
}
