import Foundation

// I-2b (PLAN-IPAD.md, Entscheidung I8): Kopplung von Mac und iPad. Am Mac öffnet die App einen Eingang für gekoppelte
// iPads und reicht ihre Verbindungen an den Kernel durch; das iPad hat keinen eigenen Kernel und verbindet sich über
// den Mac. Für den Kernel ist jedes Gerät eine App-Verbindung (PROTOCOL.md, „I-2 Mehrere Geräte“).

extension AppController {
    /// HELLO_APP.geraet: Kennung, Art und Name dieses Geräts; das iPad dazu die Kennung seiner Kopplung.
    func helloGeraet() -> [String: String] {
        var feld = GeraeteKennung.helloFeld
        #if os(iOS)
        if let code = PadKopplung.laden() { feld["kopplung"] = code.kennung }
        #endif
        return feld
    }

    /// Verbindung zum Kernel steht oder ist weg (auf dem iPad: zum Mac).
    func kopplungVerbunden(_ verbunden: Bool, grund: String? = nil) {
        #if os(iOS)
        model.kopplung.verbunden = verbunden
        if verbunden {
            model.kopplung.meldung = nil
        } else if grund == "Schlüssel passt nicht" {
            model.kopplung.meldung = "Der Mac kennt dieses iPad nicht mehr. Bitte am Mac neu koppeln."
        }
        #endif
    }
}

#if os(macOS)
extension AppController: KopplungsActions {
    /// Port des iPad-Eingangs: zwei über dem MCP-Port der Variante (Installation 47825), so hat jede Testvariante
    /// ihren eigenen.
    static var ipadPort: UInt16 { UInt16(clamping: AppInfo.mcpPort + 2) }

    /// Eingang für iPads öffnen (nur mit gekoppeltem Gerät oder offenem Code; sonst bleibt kein Port offen).
    func ipadEingangStarten() {
        if ipadEingang == nil {
            let eingang = IPadEingang(port: Self.ipadPort, kernelSocket: AppInfo.kernelSocket.path,
                                      dienstName: GeraeteKennung.name, macKennung: GeraeteKennung.kennung)
            eingang.onProtokoll = { [weak self] zeile in self?.log(.info, zeile) }
            eingang.onBereit = { [weak self] port in self?.model.kopplung.eingangPort = port }
            eingang.onGeraet = { [weak self] kennung, name in self?.ipadGemeldet(kennung, name) }
            ipadEingang = eingang
        }
        ipadEingangErneuern()
    }

    func ipadEingangStoppen() {
        ipadEingang?.stoppen()
        ipadEingang = nil
        model.kopplung.eingangPort = nil
    }

    /// Schlüssel neu laden (nach Koppeln oder Entfernen) und den Eingang damit neu starten.
    func ipadEingangErneuern() {
        kopplungen.aufraeumen()
        model.kopplung.geraete = kopplungen.geraete
        ipadEingang?.starten(schluessel: kopplungen.schluessel())
    }

    func ipadGemeldet(_ kennung: String, _ name: String?) {
        kopplungen.verbunden(kennung: kennung, name: name)
        if model.kopplung.code?.kennung == kennung { model.kopplung.code = nil }  // QR hat seinen Zweck erfüllt
        model.kopplung.geraete = kopplungen.geraete
    }

    public func ipadKoppeln() {
        do {
            model.kopplung.code = try kopplungen.neu(mac: GeraeteKennung.kennung, macName: GeraeteKennung.name,
                                                     port: Self.ipadPort, wege: MacWege.aktuell())
            if ipadEingang == nil, running, !AppInfo.isDemoMode {
                ipadEingangStarten()
            } else {
                ipadEingangErneuern()
            }
            log(.info, "Kopplungscode für ein iPad erstellt (gilt 10 Minuten)")
        } catch {
            log(.error, "Kopplungscode ließ sich nicht anlegen: \(error)")
        }
    }

    public func ipadKopplungSchliessen() {
        model.kopplung.code = nil
    }

    public func ipadEntfernen(_ kennung: String) {
        kopplungen.entfernen(kennung)
        if model.kopplung.code?.kennung == kennung { model.kopplung.code = nil }
        ipadEingangErneuern()
        log(.info, "iPad entfernt (\(kennung))")
    }
}
#endif

#if os(iOS)
extension AppController: KopplungsActions {
    /// Start auf dem iPad: mit dem gekoppelten Mac verbinden; ohne Kopplung wartet die App auf den QR-Code.
    func startUeberMac() {
        guard let code = PadKopplung.laden() else {
            model.kopplung.macName = nil
            log(.info, "Noch nicht mit einem Mac gekoppelt")
            return
        }
        model.kopplung.macName = code.name
        log(.info, "Verbinde mit \(code.name)")
        connection.open(netz: NetzZiel(code: code))
    }

    @discardableResult
    public func koppeln(text: String) -> Bool {
        guard let code = KopplungsCode.lesen(text) else { return false }
        do {
            try PadKopplung.speichern(code)
        } catch {
            model.kopplung.meldung = "\(error.localizedDescription)"
            return false
        }
        model.kopplung.macName = code.name
        model.kopplung.meldung = nil
        log(.info, "Mit \(code.name) gekoppelt")
        if running { connection.open(netz: NetzZiel(code: code)) }
        return true
    }

    public func kopplungLoesen() {
        PadKopplung.loeschen()
        connection.close()
        model.kopplung.macName = nil
        model.kopplung.verbunden = false
        log(.info, "Kopplung mit dem Mac gelöst")
    }
}
#endif
