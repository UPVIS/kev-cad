import Foundation

/// V2-5 (delta-1): Basen für WIE_ZUVOR auf dem Lesefaden der Verbindung (PROTOCOL.md, „Große JSON-Nachrichten“). Je Art
/// die letzten 6 Rahmen ohne `reply_to`, vollständig empfangen oder selbst aufgebaut. Ein WIE_ZUVOR wird hier wieder zu
/// dem Rahmen, der es ersetzt hat; der Rest der App sieht nur diesen Rahmen. Nur vom Lesefaden aus benutzen.
public final class WieZuvorSpeicher {
    public enum Ergebnis {
        /// Rahmen, der weiterverarbeitet wird, mit seinem Umschlag (der empfangene oder der aufgebaute)
        case rahmen(Frame, MessageEnvelope)
        /// WIE_ZUVOR ließ sich nicht aufbauen: verwerfen und mit NOCHMAL neu anfordern
        case fehlt(art: String, grund: String)
    }

    private struct Basis {
        var seq: Int
        var frame: Frame
    }

    private var basen: [String: [Basis]] = [:]

    public init() {}

    /// Für eine neue Verbindung: alles vergessen.
    public func leeren() { basen = [:] }

    /// Anzahl der Basen einer Art (für Tests).
    public func anzahl(_ art: String) -> Int { basen[art]?.count ?? 0 }

    public func empfangen(_ frame: Frame, envelope env: MessageEnvelope) -> Ergebnis {
        if env.type == "WIE_ZUVOR" { return aufbauen(frame, seq: env.seq) }
        if LiveGrenzen.wieZuvorArten.contains(env.type), env.replyTo == nil, let seq = env.seq {
            merken(env.type, seq: seq, frame: frame)
        }
        return .rahmen(frame, env)
    }

    private func merken(_ art: String, seq: Int, frame: Frame) {
        var liste = basen[art] ?? []
        liste.append(Basis(seq: seq, frame: frame))
        if liste.count > LiveGrenzen.wieZuvorBasen { liste.removeFirst(liste.count - LiveGrenzen.wieZuvorBasen) }
        basen[art] = liste
    }

    private enum PfadFehler: Error { case passtNicht }

    private func aufbauen(_ frame: Frame, seq: Int?) -> Ergebnis {
        // JSONSerialization statt JSONValue: hält Ganzzahl und Kommazahl auseinander und ist bei 400 KB deutlich schneller
        guard
            let wz = (try? JSONSerialization.jsonObject(with: frame.header, options: [.mutableContainers]))
                as? NSDictionary,
            let art = wz["art"] as? String, LiveGrenzen.wieZuvorArten.contains(art),
            let basisSeq = (wz["basis"] as? NSNumber)?.intValue, let seq
        else { return .fehlt(art: (try? Self.art(frame)) ?? "", grund: "WIE_ZUVOR nicht lesbar") }
        guard let basis = basen[art]?.last(where: { $0.seq == basisSeq }) else {
            return .fehlt(art: art, grund: "Basis \(basisSeq) von \(art) unbekannt")
        }
        do {
            guard
                let kopf = try JSONSerialization.jsonObject(with: basis.frame.header, options: [.mutableContainers])
                    as? NSMutableDictionary
            else { throw PfadFehler.passtNicht }
            kopf.removeObject(forKey: "seq")
            for paar in wz["setzen"] as? [Any] ?? [] {
                guard let p = paar as? [Any], p.count == 2, let pfad = p[0] as? [Any] else { throw PfadFehler.passtNicht }
                try Self.setzen(kopf, pfad, p[1])
            }
            for eintrag in wz["weg"] as? [Any] ?? [] {
                guard let pfad = eintrag as? [Any] else { throw PfadFehler.passtNicht }
                try Self.entfernen(kopf, pfad)
            }
            kopf["type"] = art
            kopf["seq"] = seq
            let daten = try JSONSerialization.data(withJSONObject: kopf)
            let neu = Frame(header: daten, payload: basis.frame.payload)
            merken(art, seq: seq, frame: neu)
            return .rahmen(neu, try JSONDecoder().decode(MessageEnvelope.self, from: daten))
        } catch {
            return .fehlt(art: art, grund: "Pfad von WIE_ZUVOR passt nicht zur Basis \(basisSeq) von \(art)")
        }
    }

    private static func art(_ frame: Frame) throws -> String? {
        (try JSONSerialization.jsonObject(with: frame.header) as? NSDictionary)?["art"] as? String
    }

    /// Geht bis zum vorletzten Schritt des Pfads und gibt den Behälter und den letzten Schritt zurück.
    private static func eltern(_ wurzel: NSMutableDictionary, _ pfad: [Any]) throws -> (Any, Any) {
        guard let letzter = pfad.last else { throw PfadFehler.passtNicht }
        var ziel: Any = wurzel
        for schritt in pfad.dropLast() {
            if let d = ziel as? NSMutableDictionary, let k = schritt as? String, let w = d[k] {
                ziel = w
            } else if let a = ziel as? NSMutableArray, let i = index(schritt), i < a.count {
                ziel = a[i]
            } else {
                throw PfadFehler.passtNicht
            }
        }
        return (ziel, letzter)
    }

    private static func index(_ schritt: Any) -> Int? {
        guard let n = schritt as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), n.intValue >= 0 else { return nil }
        return n.intValue
    }

    private static func setzen(_ wurzel: NSMutableDictionary, _ pfad: [Any], _ wert: Any) throws {
        let (ziel, letzter) = try eltern(wurzel, pfad)
        if let d = ziel as? NSMutableDictionary, let k = letzter as? String {
            d[k] = wert
        } else if let a = ziel as? NSMutableArray, let i = index(letzter), i < a.count {
            a[i] = wert
        } else {
            throw PfadFehler.passtNicht
        }
    }

    private static func entfernen(_ wurzel: NSMutableDictionary, _ pfad: [Any]) throws {
        let (ziel, letzter) = try eltern(wurzel, pfad)
        guard let d = ziel as? NSMutableDictionary, let k = letzter as? String, d[k] != nil else {
            throw PfadFehler.passtNicht
        }
        d.removeObject(forKey: k)
    }
}
