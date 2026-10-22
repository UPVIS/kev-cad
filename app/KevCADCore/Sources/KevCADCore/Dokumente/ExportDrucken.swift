import AppKit
import PDFKit

// Drucken (RECHERCHE-PHASE6.md 5.2, DOKUMENTE.md „App“): immer mit `.pageScaleNone` (sonst verkleinert macOS ein
// A4-Blatt auf 97,18 % und kein Maßstab stimmt mehr), je Blattformat ein eigener Druckauftrag, weil ein Auftrag nur
// eine Papiergröße hat.

/// Ein Druckauftrag: alle Seiten eines Formats.
public struct ExportDruckauftrag {
    public var format: String
    public var groessePt: CGSize
    public var dokument: PDFDocument
    public var seiten: Int { dokument.pageCount }
}

@MainActor
public final class ExportDrucker: NSObject {
    private var offen: [ExportDruckauftrag] = []
    private weak var fenster: NSWindow?
    private var titel = ""
    private var fertig: ((Int) -> Void)?
    private var gedruckt = 0
    /// Läuft gerade (hält sich selbst, bis der letzte Auftrag durch ist).
    private static var aktiv: ExportDrucker?

    /// Teilt ein PDF in Aufträge je Seitengröße (Reihenfolge des ersten Auftretens).
    public static func auftraege(_ pdf: PDFDocument) -> [ExportDruckauftrag] {
        var out: [ExportDruckauftrag] = []
        for i in 0..<pdf.pageCount {
            guard let page = pdf.page(at: i), let kopie = page.copy() as? PDFPage else { continue }
            let box = page.bounds(for: .mediaBox).size
            let name = ExportSeitenformat.passend(mm: CGSize(width: box.width / ExportSeitenformat.ptJeMM,
                                                       height: box.height / ExportSeitenformat.ptJeMM))?.name
                ?? "\(Int((box.width / ExportSeitenformat.ptJeMM).rounded())) × \(Int((box.height / ExportSeitenformat.ptJeMM).rounded())) mm"
            if let k = out.firstIndex(where: { abs($0.groessePt.width - box.width) < 1 && abs($0.groessePt.height - box.height) < 1 }) {
                out[k].dokument.insert(kopie, at: out[k].dokument.pageCount)
            } else {
                let d = PDFDocument()
                d.insert(kopie, at: 0)
                out.append(ExportDruckauftrag(format: name, groessePt: box, dokument: d))
            }
        }
        return out
    }

    /// Hinweis für den Dialog, wenn Formate gemischt sind.
    public static func hinweis(_ auftraege: [ExportDruckauftrag]) -> String? {
        guard auftraege.count > 1 else { return nil }
        let teile = auftraege.map { "\($0.format): \(KevFormat.count($0.seiten, one: "Seite", many: "Seiten"))" }
        return "Gemischte Formate: \(auftraege.count) Druckaufträge nacheinander (\(teile.joined(separator: ", "))). "
            + "Jeder Auftrag druckt 1:1 ohne Skalierung."
    }

    /// Druckeinstellungen eines Auftrags: Papier so groß wie die Seiten, ohne Ränder, Maßstab 1.
    public static func druckInfo(_ a: ExportDruckauftrag) -> NSPrintInfo {
        let info = (NSPrintInfo.shared.copy() as? NSPrintInfo) ?? NSPrintInfo()
        info.orientation = a.groessePt.width > a.groessePt.height ? .landscape : .portrait
        info.paperSize = a.groessePt
        info.topMargin = 0
        info.bottomMargin = 0
        info.leftMargin = 0
        info.rightMargin = 0
        info.horizontalPagination = .clip
        info.verticalPagination = .clip
        info.isHorizontallyCentered = true
        info.isVerticallyCentered = true
        info.scalingFactor = 1
        return info
    }

    /// Druckoperation eines Auftrags, immer `.pageScaleNone` (1:1).
    public static func operation(_ a: ExportDruckauftrag, info: NSPrintInfo? = nil) -> NSPrintOperation? {
        a.dokument.printOperation(for: info ?? druckInfo(a), scalingMode: .pageScaleNone, autoRotate: false)
    }

    /// Öffnet den Druckdialog für jeden Auftrag nacheinander (als Blatt am Fenster, sonst modal). `fertig` bekommt
    /// die Zahl der gedruckten Aufträge.
    public static func drucke(_ pdf: PDFDocument, titel: String, fenster: NSWindow?, fertig: ((Int) -> Void)? = nil) {
        let d = ExportDrucker()
        d.offen = auftraege(pdf)
        d.fenster = fenster
        d.titel = titel
        d.fertig = fertig
        aktiv = d
        d.naechster()
    }

    private func naechster() {
        guard !offen.isEmpty else {
            fertig?(gedruckt)
            Self.aktiv = nil
            return
        }
        let a = offen.removeFirst()
        guard let op = Self.operation(a) else {
            naechster()
            return
        }
        op.jobTitle = "\(titel) – \(a.format)"
        op.showsPrintPanel = true
        op.showsProgressPanel = true
        op.printPanel.options.remove(.showsScaling)
        op.printPanel.options.insert(.showsPaperSize)
        if let fenster, fenster.isVisible {
            op.runModal(for: fenster, delegate: self, didRun: #selector(gelaufen(_:success:contextInfo:)),
                        contextInfo: nil)
        } else {
            if op.run() { gedruckt += 1 }
            naechster()
        }
    }

    @objc private func gelaufen(_ op: NSPrintOperation, success: Bool, contextInfo: UnsafeMutableRawPointer?) {
        if success { gedruckt += 1 }
        // nächstes Blatt erst, wenn das vorige Fenster zu ist
        DispatchQueue.main.async { [weak self] in
            MainActor.assumeIsolated { self?.naechster() }
        }
    }
}
