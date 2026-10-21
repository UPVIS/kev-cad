"""Simulation des Bauplans: jeder Montageschritt wird nachgespielt.

Je Schritt, in der Reihenfolge des Bauplans (Vormontagen je Unterbaugruppe für sich, dann die Hauptmontage):

- **Einführweg:** Jede neue Einheit fährt ihren Weg aus der Explosion an ihren Platz (``einbau``: Richtung, Weg,
  zweistufig ``zuerst``), gegen alles bis dahin Montierte (wege.py). Sperrt ein Teil aus einem früheren Schritt, das
  ohne dieses Teil frei wäre, ist es ein Befund ``reihenfolge`` (Lösung: Schritt vorziehen); sonst ``einfuehrweg``.
  Führt der Weg unter die Aufstandsfläche: Hinweis aufbocken.
- **Werkzeugzugang:** Für jedes Verbindungsmittel des Schritts der Raum, den das Werkzeug braucht (Innensechskant
  gerade über dem Kopf, Schlüssel rund um die Mutter, Finger rund um die Flügelmutter), gegen das Montierte.
- **Standsicherheit:** Schwerpunkt der Teilbaugruppe über ihrer Aufstandsfläche (Hauptmontage); in der Vormontage,
  ob die neuen Teile schon am Montierten halten.

Befunde im gemeinsamen Format (``art``, ``teile``, ``schwere``, ``text``, ``ort``, ``loesung``) mit ``schritt``.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from kevcad_kernel.bauplan import werkstatt as ws
from kevcad_kernel.bauplan.eingang import Eingang
from kevcad_kernel.bauplan.wege import WegPruefer, raum_frei, richtung_text, ring, standsicherheit, zylinder
from kevcad_kernel.bom import de_num

KIPP_KNAPP_GRAD = 3.0


def _b(art: str, teile: list[str], schwere: str, text: str, loesung: str, schritt: str, ort: Any = None,
       wert: dict | None = None) -> dict[str, Any]:
    return {"art": art, "teile": list(teile), "schwere": schwere, "text": text, "loesung": loesung, "schritt": schritt,
            "ort": None if ort is None else [round(float(c), 1) for c in ort], "wert": wert or {}}


def _vec(v: Any) -> np.ndarray | None:
    return None if v is None else np.asarray(v, dtype=float)


def montage_schritte(plan: dict[str, Any]) -> list[dict[str, Any]]:
    for a in plan.get("abschnitte") or []:
        if a.get("art") == "montage":
            return list(a.get("schritte") or [])
    return []


class Simulation:
    def __init__(self, ein: Eingang, wp: WegPruefer) -> None:
        self.ein = ein
        self.wp = wp
        self.boden = ein.boden_z()

    # -- Einführweg ------------------------------------------------------------------------------------------------

    def _sperren(self, teile: list[str], el: dict[str, Any], gegen: list[str]) -> dict[str, Any]:
        """Teile aus ``gegen``, die den Weg des Elements sperren: {Name: Sperre}."""
        d1 = -_vec(el["richtung"])
        s = float(el.get("weg") or 0.0)
        zuerst = _vec(el.get("zuerst"))
        out: dict[str, Any] = {}
        for t in teile:
            if t not in self.wp.koerper:
                continue
            if zuerst is not None:
                out.update(self.wp.sperrer(t, d1, gegen=gegen, weg=max(s, 1.0)))
                out.update(self.wp.sperrer(t, -zuerst, gegen=gegen, versatz=d1 * s))
            else:
                out.update(self.wp.sperrer(t, d1, gegen=gegen))
        return out

    def _anderer_weg(self, teile: list[str], gegen: list[str]) -> np.ndarray | None:
        from kevcad_kernel.bauplan.montagefolge import ACHSEN

        for d in ACHSEN:
            if not any(self.wp.sperrer(t, d, gegen=gegen) for t in teile if t in self.wp.koerper):
                return d
        return None

    # -- Werkzeug --------------------------------------------------------------------------------------------------

    def _werkzeug(self, name: str, montiert: list[str], ohne: set[str]) -> tuple[list[tuple[str, float]], str, Any]:
        t = self.ein.teile.get(name)
        if t is None or t.rolle != "vm" or t.wirt:
            return [], "", None
        vm = t.vm
        if vm.get("achse") is None:
            return [], "", None
        a = np.asarray(vm["achse"], dtype=float)
        mitte = np.asarray(vm.get("mitte") or t.zentrum, dtype=float)
        r, laenge, art = ws.zugang_mass(vm, name)
        pos = t.koerper.pos
        tt = (pos - mitte) @ a
        rr = np.linalg.norm((pos - mitte) - np.outer(tt, a), axis=1)
        if art == "stift":
            k = _vec(vm.get("kopf"))
            if k is None:  # Gewindestift ohne Kopf: von der freien Seite (weg vom Teil mit dem Gewinde)
                k = a
            tk = (pos - mitte) @ k
            p0 = mitte + k * float(tk.max())
            raum = zylinder(p0 + k * 0.3, k, r, laenge)
            wo = p0
        else:
            r_innen = float(rr.max()) + 0.5
            hoehe = float(tt.max() - tt.min())
            p0 = mitte + a * (float(tt.min()) + 0.3)  # nur auf Höhe der Mutter (nicht in die Scheibe darunter)
            raum = ring(p0, a, r_innen, max(r, r_innen + 6.0), max(hoehe - 0.6, 1.0))
            wo = mitte
        return raum_frei(raum, self.wp.koerper, montiert, ohne, min_volumen=2.0), art, wo

    # -- Lauf ------------------------------------------------------------------------------------------------------

    def pruefe(self, plan: dict[str, Any], nur: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """Befunde je Schritt-id (alle Montageschritte, ``nur``: nur dieser Schritt wird geprüft, die anderen bauen
        trotzdem auf)."""
        t0 = time.perf_counter()
        schritte = montage_schritte(plan)
        ergebnis: dict[str, list[dict[str, Any]]] = {s["id"]: [] for s in schritte}
        montiert: dict[str | None, list[str]] = {}
        von_schritt: dict[str, tuple[int, str]] = {}  # Teil → (Nr, Schritt-id)
        nummer = {s["id"]: i for i, s in enumerate(schritte, 1)}
        bekannte = set(self.wp.koerper)
        for s in schritte:
            ebene = s.get("baugruppe")
            liste = montiert.setdefault(ebene, [])
            pruefen = nur is None or nur == s["id"]
            befunde = ergebnis[s["id"]]
            neue: list[str] = []
            for el in s.get("einbau") or []:
                teile = [t for t in el.get("teile") or [] if t in bekannte]
                fehlend = [t for t in el.get("teile") or [] if t not in bekannte]
                if fehlend and pruefen:
                    befunde.append(_b("reihenfolge", fehlend[:3], "warnung",
                                      f"{len(fehlend)} Teil(e) aus diesem Schritt gibt es im Modell nicht mehr: "
                                      f"{', '.join(fehlend[:3])}", "Bauplan neu erzeugen (bauplan) oder den festen "
                                      "Schritt anpassen.", s["id"]))
                if el.get("grundteil") or el.get("richtung") is None:
                    liste += teile
                    neue += teile
                    for t in teile:
                        von_schritt[t] = (nummer[s["id"]], s["id"])
                    continue
                if pruefen and teile:
                    self._einfuehren(s, el, teile, liste, von_schritt, nummer, befunde)
                    if el.get("art") == "vm":
                        for t in teile:
                            self._zugang(s, t, liste + teile, set(teile), befunde, von_schritt)
                liste += teile
                neue += teile
                for t in teile:
                    von_schritt[t] = (nummer[s["id"]], s["id"])
            if pruefen and neue:
                if ebene is None:
                    self._stand(s, liste, befunde)
                else:
                    self._haelt(s, neue, liste, befunde)
        self.dauer_ms = round((time.perf_counter() - t0) * 1000, 1)
        return ergebnis

    def _einfuehren(self, s: dict[str, Any], el: dict[str, Any], teile: list[str], montiert: list[str],
                    von_schritt: dict[str, tuple[int, str]], nummer: dict[str, int],
                    befunde: list[dict[str, Any]]) -> None:
        sperr = self._sperren(teile, el, montiert)
        name = el.get("name") or teile[0]
        e_txt = richtung_text(el["richtung"])
        if el.get("aufbocken") and float(el["aufbocken"]) > 0 and el.get("art") != "vm":
            befunde.append(_b("einfuehrweg", [el.get("haupt") or teile[0]], "hinweis",
                              f"{name}: der Weg {e_txt} führt {de_num(float(el['aufbocken']), 0)} mm unter die "
                              "Aufstandsfläche.", "Baugruppe aufbocken (Klötze unter den Rahmen) oder auf den Kopf "
                              "stellen, dann einsetzen.", s["id"], wert={"mm": el["aufbocken"]}))
        if not sperr:
            return
        jetzt = nummer[s["id"]]
        frueher = sorted({q for q in sperr if q in von_schritt and von_schritt[q][0] < jetzt},
                         key=lambda q: von_schritt[q][0])
        im_schritt = [q for q in sperr if q not in frueher]
        ort = next((sp.ort for sp in sperr.values() if sp.ort is not None), None)
        tiefe = max(sp.tiefe for sp in sperr.values())
        if frueher and not im_schritt:
            # ohne die früher montierten Sperrer frei? Dann ist es die Reihenfolge
            erst = min(von_schritt[q][0] for q in frueher)
            vorher = [q for q in montiert if von_schritt.get(q, (0, ""))[0] < erst]
            if not self._sperren(teile, el, vorher):
                q0 = frueher[0]
                befunde.append(_b(
                    "reihenfolge", [el.get("haupt") or teile[0], *frueher[:3]], "fehler",
                    f"{name} kommt {e_txt} nicht mehr an seinen Platz: {', '.join(frueher[:3])} (Schritt "
                    f"{von_schritt[q0][0]}) ist schon montiert und im Weg ({de_num(tiefe, 1)} mm).",
                    f"{name} vor Schritt {von_schritt[q0][0]} einbauen (bauplan_bearbeiten: verschieben) oder "
                    f"{q0.rsplit('/', 1)[-1]} später montieren.", s["id"], ort,
                    {"tiefe": tiefe, "vor_schritt": von_schritt[q0][1]}))
                return
        anders = self._anderer_weg(teile, montiert)
        loesung = (f"Anders einführen: {richtung_text(-anders)} ist frei (Schritt anpassen)." if anders is not None
                   else "Konstruktion ändern: Spiel, Einführschräge, Schlitz oder Teilung vorsehen, damit das Teil "
                        "an seinen Platz kommt; oder die Reihenfolge ändern.")
        alle = frueher + im_schritt
        befunde.append(_b("einfuehrweg", [el.get("haupt") or teile[0], *alle[:3]], "fehler",
                          f"Einführweg von {name} ({e_txt}) ist versperrt durch {', '.join(alle[:3])}"
                          f"{' …' if len(alle) > 3 else ''} ({de_num(tiefe, 1)} mm).", loesung, s["id"], ort,
                          {"tiefe": tiefe}))

    def _zugang(self, s: dict[str, Any], name: str, montiert: list[str], ohne: set[str],
                befunde: list[dict[str, Any]], von_schritt: dict[str, tuple[int, str]]) -> None:
        t = self.ein.teile.get(name)
        if t is None:
            return
        # Partner auf derselben Achse (Schraube in Mutter, Stift in Einsatz) zählen nicht
        partner = set(ohne)
        a = t.vm.get("achse")
        if a is not None:
            a = np.asarray(a, float)
            m = np.asarray(t.vm.get("mitte") or t.zentrum, float)
            for n in montiert:
                u = self.ein.teile.get(n)
                if u is None or u.rolle not in ("vm", "einsatz") or u.vm.get("achse") is None:
                    continue
                b = np.asarray(u.vm["achse"], float)
                mu = np.asarray(u.vm.get("mitte") or u.zentrum, float)
                off = mu - m
                if abs(float(np.dot(a, b))) > 0.99 and np.linalg.norm(off - a * float(np.dot(off, a))) < 0.5:
                    partner.add(n)
        try:
            stoerer, art, wo = self._werkzeug(name, montiert, partner)
        except Exception:  # noqa: BLE001 - eine fehlgeschlagene Raumprüfung ist kein Befund
            return
        if not stoerer:
            return
        werkzeug = ", ".join(ws.werkzeug_vm(t.vm, name)) or "Werkzeug"
        namen = [n for n, _ in stoerer]
        spaeter = [n for n in namen if von_schritt.get(n, (0, ""))[1] == s["id"]]
        loesung = ("Verbindungsmittel anbringen, bevor " + ", ".join(namen[:2]) + " montiert wird (Schritt teilen)"
                   if not spaeter else "Zugang schaffen: Aussparung oder Langloch für das Werkzeug, kürzeres "
                                       "Werkzeug (Kugelkopf-Innensechskant, Ratsche) oder andere Richtung")
        schwere = "warnung" if art == "finger" else "fehler"
        befunde.append(_b("werkzeugzugang", [name, *namen[:3]], schwere,
                          f"Werkzeug kommt schlecht an {name.rsplit('/', 1)[-1]} ({werkzeug}): "
                          f"{', '.join(n.rsplit('/', 1)[-1] for n in namen[:3])} im Weg "
                          f"({de_num(stoerer[0][1], 0)} mm³ im Werkzeugraum).", loesung, s["id"], wo,
                          {"volumen": stoerer[0][1], "art": art}))

    def _stand(self, s: dict[str, Any], montiert: list[str], befunde: list[dict[str, Any]]) -> None:
        teile = [self.ein.teile[n] for n in montiert if n in self.ein.teile]
        if not teile:
            return
        st = standsicherheit(teile, self.boden)
        if not st.steht:
            befunde.append(_b("standsicherheit", [teile[0].name], "warnung",
                              "Die Teilbaugruppe berührt den Boden noch nicht: sie muss gehalten werden.",
                              "Abstützen oder auf der Werkbank in einer stabilen Lage aufbauen.", s["id"],
                              st.schwerpunkt, {"masse_g": round(st.masse_g, 1)}))
        elif not st.sicher:
            befunde.append(_b("standsicherheit", [teile[-1].name], "warnung",
                              f"Die Teilbaugruppe kippt: Schwerpunkt {de_num(-st.abstand, 0)} mm außerhalb der "
                              "Aufstandsfläche" + (" (Masse teils geschätzt)" if st.geschaetzt else "") + ".",
                              "Während der Montage abstützen oder erst das Gegengewicht bzw. die Stützen montieren.",
                              s["id"], st.schwerpunkt, {"abstand": st.abstand}))
        elif st.kippwinkel is not None and st.kippwinkel < KIPP_KNAPP_GRAD:
            befunde.append(_b("standsicherheit", [teile[-1].name], "hinweis",
                              f"Standsicherheit knapp: kippt schon ab {de_num(st.kippwinkel, 1)}°.",
                              "Beim Montieren festhalten oder abstützen.", s["id"], st.schwerpunkt,
                              {"kippwinkel": st.kippwinkel}))

    def _haelt(self, s: dict[str, Any], neue: list[str], montiert: list[str], befunde: list[dict[str, Any]]) -> None:
        """Vormontage: halten die neuen Teile am schon Montierten (Verbindung oder Kontakt)?"""
        alt = set(montiert) - set(neue)
        if not alt:
            return
        lose = []
        for n in neue:
            t = self.ein.teile.get(n)
            if t is None or t.rolle in ("vm", "einsatz") or t.wirt:
                continue
            nb = self.ein.nachbarn(n, kontakt=True)
            if not (nb & (alt | set(neue))):
                lose.append(n)
        if lose:
            befunde.append(_b("standsicherheit", lose[:3], "hinweis",
                              f"{', '.join(x.rsplit('/', 1)[-1] for x in lose[:3])} hält noch nicht am Montierten.",
                              "Bis zum nächsten Schritt festhalten oder mit Klebeband sichern.", s["id"]))


def befund_ids(ergebnis: dict[str, list[dict[str, Any]]]) -> None:
    """Fortlaufende ids b1, b2 … über alle Schritte."""
    i = 0
    for befunde in ergebnis.values():
        for b in befunde:
            i += 1
            b["id"] = f"bp{i}"
