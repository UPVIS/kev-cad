import CoreGraphics
import Foundation
import PDFKit

// Das Dokument aus allen Bausteinen (Strang P6-A2): Seiten mit eigenem Format, Kopf- und Fußzeile, PDF mit Outline.
// Eine Zeichenfunktion für PDF, Vorschau und Druck.

/// Kopfdaten des Dokuments (Kopf- und Fußzeile, Deckblatt, PDF-Metadaten).
public struct ExportKopf: Sendable {
    public var projekt: String
    /// z. B. „V14 · Meilenstein Halter fertig“; nil ohne Versionen.
    public var version: String?
    public var datum: Date
    public var autor: String

    public init(projekt: String, version: String? = nil, datum: Date = Date(), autor: String = "Kevin Schwed") {
        self.projekt = projekt
        self.version = version
        self.datum = datum
        self.autor = autor
    }

    public var datumText: String {
        let f = DateFormatter()
        f.locale = KevFormat.locale
        f.dateFormat = "d. MMMM yyyy"
        return f.string(from: datum)
    }

    public var datumKurz: String {
        let f = DateFormatter()
        f.locale = KevFormat.locale
        f.dateFormat = "dd.MM.yyyy"
        return f.string(from: datum)
    }
}

/// Eine Seite: Format (mm), Baustein, Titel in der Kopfzeile, Inhalt.
public struct ExportSeite {
    public enum Inhalt {
        /// Berichtsseite: Inhalt in mm, Ursprung links oben (Kopf- und Fußzeile zeichnet das Dokument).
        case leinwand((ExportLeinwand, ExportSeitenInfo) -> Void)
        /// Eigenes Blatt (Zeichnung): in Punkt, Ursprung links unten, ohne Kopf- und Fußzeile.
        case roh((CGContext, CGSize) -> Void)
    }

    public var groesse: CGSize
    public var baustein: ExportBausteinArt
    public var titel: String
    public var mitKopf: Bool
    public var inhalt: Inhalt
    /// Einträge im Inhaltsverzeichnis des PDF (Unterpunkte des Bausteins), die auf dieser Seite beginnen.
    public var gliederung: [String]

    public init(groesse: CGSize, baustein: ExportBausteinArt, titel: String, mitKopf: Bool = true,
                gliederung: [String] = [], inhalt: Inhalt)
    {
        self.groesse = groesse
        self.baustein = baustein
        self.titel = titel
        self.mitKopf = mitKopf
        self.inhalt = inhalt
        self.gliederung = gliederung
    }

    public var formatName: String {
        if let f = ExportSeitenformat.passend(mm: groesse) { return f.name }
        return "\(Int(groesse.width.rounded())) × \(Int(groesse.height.rounded())) mm"
    }

    public var punkte: CGSize { CGSize(width: groesse.width * ExportSeitenformat.ptJeMM, height: groesse.height * ExportSeitenformat.ptJeMM) }
}

public struct ExportSeitenInfo {
    public var nummer: Int
    public var anzahl: Int
    public var kopf: ExportKopf
    /// Erste Seite je Baustein (für das Inhaltsverzeichnis auf dem Deckblatt).
    public var bausteinSeiten: [(art: ExportBausteinArt, seite: Int, anzahl: Int)]
}

/// Ränder und Bänder der Berichtsseiten.
public enum ExportRand {
    public static let links: CGFloat = 18
    public static let rechts: CGFloat = 14
    public static let oben: CGFloat = 13
    public static let unten: CGFloat = 12
    public static let kopf: CGFloat = 11
    public static let fuss: CGFloat = 9

    /// Inhaltsbereich einer Seite mit Kopf- und Fußzeile (mm, Ursprung links oben).
    public static func inhalt(_ groesse: CGSize) -> CGRect {
        CGRect(x: links, y: oben + kopf, width: groesse.width - links - rechts,
               height: groesse.height - oben - kopf - unten - fuss)
    }
}

public final class ExportDokument {
    public var kopf: ExportKopf
    public private(set) var seiten: [ExportSeite]
    public var hinweise: [String]

    public init(kopf: ExportKopf, seiten: [ExportSeite], hinweise: [String] = []) {
        self.kopf = kopf
        self.seiten = seiten
        self.hinweise = hinweise
    }

    public var bausteinSeiten: [(art: ExportBausteinArt, seite: Int, anzahl: Int)] {
        var out: [(art: ExportBausteinArt, seite: Int, anzahl: Int)] = []
        for (i, s) in seiten.enumerated() {
            if let last = out.last, last.art == s.baustein {
                out[out.count - 1].anzahl += 1
            } else {
                out.append((s.baustein, i + 1, 1))
            }
        }
        return out
    }

    public var formate: [String: Int] {
        var f: [String: Int] = [:]
        for s in seiten { f[s.formatName, default: 0] += 1 }
        return f
    }

    func info(_ i: Int) -> ExportSeitenInfo {
        ExportSeitenInfo(nummer: i + 1, anzahl: seiten.count, kopf: kopf, bausteinSeiten: bausteinSeiten)
    }

    /// Zeichnet Seite `i` in einen Kontext in Punkt mit Ursprung links unten (PDF, Druck, Vorschau mit Skalierung).
    public func zeichne(_ i: Int, in ctx: CGContext) {
        let s = seiten[i]
        ctx.saveGState()
        switch s.inhalt {
        case .roh(let f):
            f(ctx, s.punkte)
        case .leinwand(let f):
            let l = ExportLeinwand(ctx: ctx, groesse: s.groesse)
            if s.mitKopf { kopfUndFuss(l, s, info(i)) }
            f(l, info(i))
        }
        ctx.restoreGState()
    }

    func kopfUndFuss(_ l: ExportLeinwand, _ s: ExportSeite, _ info: ExportSeitenInfo) {
        let w = s.groesse.width, h = s.groesse.height
        let x0 = ExportRand.links, x1 = w - ExportRand.rechts
        let base = ExportRand.oben + 5.2
        // Kopf: Projekt fett, Baustein; rechts Version und Datum
        let pw = l.text(kopf.projekt, x: x0, y: base, .fett(9), farbe: ExportStil.tinte, maxBreite: (x1 - x0) * 0.45)
        l.text("  ·  " + s.titel, x: x0 + pw, y: base, .normal(9), farbe: ExportStil.grau, maxBreite: (x1 - x0) * 0.3)
        let rechts = [kopf.version, kopf.datumKurz].compactMap { $0 }.joined(separator: "  ·  ")
        l.text(rechts, x: x1, y: base, .normal(8), farbe: ExportStil.grau, .rechts, maxBreite: (x1 - x0) * 0.4)
        let linieY = ExportRand.oben + 7.6
        l.linie(CGPoint(x: x0, y: linieY), CGPoint(x: x1, y: linieY), breite: 0.25, farbe: ExportStil.tinte)
        // Akzent links an der Linie (Kennfarbe des Bausteins)
        l.rechteck(CGRect(x: x0, y: linieY - 0.45, width: 12, height: 0.9), fuellung: ExportStil.akzent)
        // Fuß: Kev CAD, Seite x / y
        let fy = h - ExportRand.unten
        l.linie(CGPoint(x: x0, y: fy - 4.8), CGPoint(x: x1, y: fy - 4.8), breite: 0.12, farbe: ExportStil.linie)
        l.text("Erstellt mit Kev CAD  ·  \(kopf.autor)", x: x0, y: fy - 1, .normal(7), farbe: ExportStil.grauHell)
        l.text("Seite \(info.nummer) / \(info.anzahl)", x: x1, y: fy - 1, .mittel(7.5), farbe: ExportStil.grau, .rechts)
    }

    // MARK: PDF

    /// Schreibt das PDF (Vektor, Seitenformate gemischt) und ergänzt die Gliederung über PDFKit.
    public func schreibePDF(nach url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let tmp = url.deletingLastPathComponent().appendingPathComponent(".\(UUID().uuidString).pdf")
        defer { try? FileManager.default.removeItem(at: tmp) }
        var box = CGRect(origin: .zero, size: seiten.first?.punkte ?? ExportSeitenformat().punkte)
        let meta: [CFString: Any] = [
            kCGPDFContextTitle: "\(kopf.projekt) – Dokumente", kCGPDFContextAuthor: kopf.autor,
            kCGPDFContextCreator: "Kev CAD", kCGPDFContextSubject: "Stückliste, Zeichnungen und Bauplan",
        ]
        guard let ctx = CGContext(tmp as CFURL, mediaBox: &box, meta as CFDictionary) else {
            throw ExportFehler.pdf("PDF-Kontext für \(url.path) nicht anlegbar")
        }
        for i in seiten.indices {
            var mb = CGRect(origin: .zero, size: seiten[i].punkte)
            let pageInfo: [CFString: Any] = [kCGPDFContextMediaBox: Data(bytes: &mb, count: MemoryLayout<CGRect>.size)]
            ctx.beginPDFPage(pageInfo as CFDictionary)
            zeichne(i, in: ctx)
            ctx.endPDFPage()
        }
        ctx.closePDF()
        // Gliederung (Inhaltsverzeichnis in der Seitenleiste von Vorschau und Acrobat)
        guard let doc = PDFDocument(url: tmp) else { throw ExportFehler.pdf("PDF nicht lesbar") }
        let wurzel = PDFOutline()
        var aktuell: (art: ExportBausteinArt, eintrag: PDFOutline)?
        for (i, s) in seiten.enumerated() {
            guard let page = doc.page(at: i) else { continue }
            let ziel = PDFDestination(page: page, at: CGPoint(x: 0, y: s.punkte.height))
            if aktuell?.art != s.baustein {
                let e = PDFOutline()
                e.label = s.baustein.titel
                e.destination = ziel
                wurzel.insertChild(e, at: wurzel.numberOfChildren)
                aktuell = (s.baustein, e)
            }
            for g in s.gliederung {
                let u = PDFOutline()
                u.label = g
                u.destination = ziel
                aktuell?.eintrag.insertChild(u, at: aktuell!.eintrag.numberOfChildren)
            }
        }
        doc.outlineRoot = wurzel
        doc.documentAttributes = [
            PDFDocumentAttribute.titleAttribute: "\(kopf.projekt) – Dokumente",
            PDFDocumentAttribute.authorAttribute: kopf.autor, PDFDocumentAttribute.creatorAttribute: "Kev CAD",
        ]
        if FileManager.default.fileExists(atPath: url.path) { try? FileManager.default.removeItem(at: url) }
        guard doc.write(to: url) else { throw ExportFehler.pdf("PDF nicht geschrieben: \(url.path)") }
    }

    /// Eine Seite als Bild (Vorschau, Prüfbilder), `pixelJeMM` z. B. 4 (≈ 100 dpi).
    public func bild(_ i: Int, pixelJeMM: CGFloat = 4) -> CGImage? {
        let s = seiten[i]
        let w = Int((s.groesse.width * pixelJeMM).rounded()), h = Int((s.groesse.height * pixelJeMM).rounded())
        guard let space = CGColorSpace(name: CGColorSpace.sRGB),
              let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0, space: space,
                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
        else { return nil }
        ctx.setFillColor(ExportStil.weiss)
        ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
        let k = pixelJeMM / ExportSeitenformat.ptJeMM
        ctx.scaleBy(x: k, y: k)
        zeichne(i, in: ctx)
        return ctx.makeImage()
    }
}

public enum ExportFehler: Error, CustomStringConvertible {
    case pdf(String)
    case leer(String)

    public var description: String {
        switch self {
        case .pdf(let s), .leer(let s): return s
        }
    }
}
