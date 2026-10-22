"""Testdateien für den Dokument-Export (DOKUMENTE.md, Anhang „Export“: DOC_EXPORT_REQ, DOC_EXPORT_RES; Strang P6-A2).

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_export_fixtures.py
Ziel: app/KevCADCore/Tests/KevCADCoreTests/Fixtures/doc_export_req.frame (Kernel → App), doc_export_res.frame
(App → Kernel, so wie die App antwortet) und der Abschnitt „export“ in fixtures.json. Die übrigen Testdateien bleiben.
"""

from __future__ import annotations

import json
from pathlib import Path

from kevcad_kernel.protocol import DOC_EXPORT_BAUSTEINE, doc_export_req, encode_frame

ZIEL = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    bausteine = [{"art": "deckblatt"},
                 {"art": "stueckliste", "spalten": ["pos", "bild", "benennung", "anzahl", "masse"]},
                 {"art": "zeichnungen", "auswahl": ["seitenstange-links", "zusammenbau"]},
                 {"art": "bauplan"}]
    req = doc_export_req(bausteine, ziel="/tmp/Halter/output/Halter-dokumente.pdf", drucken=False, format="A4",
                         ausrichtung="hoch", vorlage=None, id="k-12", seq=40)
    (ZIEL / "doc_export_req.frame").write_bytes(encode_frame(req))
    res = {"type": "DOC_EXPORT_RES", "seq": 9, "reply_to": "k-12", "ok": True,
           "pfad": "/tmp/Halter/output/Halter-dokumente.pdf", "seiten": 14, "fehler": None,
           "bausteine": [{"art": "deckblatt", "seiten": 1}, {"art": "stueckliste", "seiten": 2},
                         {"art": "zeichnungen", "seiten": 2}, {"art": "bauplan", "seiten": 9}],
           "formate": {"A4 hoch": 13, "A3 quer": 1}, "gedruckt": None, "hinweise": [], "ms": 1830}
    (ZIEL / "doc_export_res.frame").write_bytes(encode_frame(res))
    fx = ZIEL / "fixtures.json"
    daten = json.loads(fx.read_text()) if fx.exists() else {}
    daten["export"] = {"bausteine": list(DOC_EXPORT_BAUSTEINE), "req": req, "res": res,
                       "frames": ["doc_export_req.frame", "doc_export_res.frame"]}
    fx.write_text(json.dumps(daten, indent=1, ensure_ascii=False))
    print(f"Export-Testdateien nach {ZIEL}")


if __name__ == "__main__":
    main()
