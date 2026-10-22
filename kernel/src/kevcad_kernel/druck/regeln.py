"""Konstruktionsregeln für 3D-Druckteile als Daten: Druckerprofil Bambu Lab P1P, Materialwerte, Tabellen.

Die Zahlen und ihre Herkunft stehen ausführlich in ``skill/kev-cad/3d-druck.md``. Jede Angabe trägt hier einen
Quellen-Schlüssel aus ``QUELLEN``; ``EW`` heißt Erfahrungswert (Größenordnung aus der Praxis, nicht belegt) und ist
bewusst vorsichtig gewählt. Winkel in Grad, Längen in mm.

Überhangwinkel werden **von der Senkrechten** gemessen: 0° = senkrechte Wand, 90° = waagrechte Unterseite. Bambu
Studio gibt die Stützenschwelle vom Waagrechten an (30° bei 0,2 mm Schicht = 60° von der Senkrechten).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ---------------------------------------------------------------------------------------------------------------------
# Quellen
# ---------------------------------------------------------------------------------------------------------------------

QUELLEN: dict[str, str] = {
    "B-P1P": "Bambu Lab, P1P Technical Specifications (Datenblatt) – "
             "https://public-cdn.bambulab.com/store/bambulab-P1P-tech-specs.pdf",
    "B-Kit": "Bambu Lab Wiki, P1P Enclosure Kit – https://wiki.bambulab.com/en/p1/manual/p1p-to-p1s",
    "B-AMS": "Bambu Lab Store, AMS 2 Pro (X1/P1: Buffer/Hub, Kupplung, Kabel; bis 4 AMS) – "
             "https://us.store.bambulab.com/products/ams-2-pro",
    "BS-M": "Bambu Studio, Maschinenprofil „Bambu Lab P1P 0.4 nozzle“ (installiert unter ~/Library/Application "
            "Support/BambuStudio/system/BBL/machine, gleich im Repo) – "
            "https://github.com/bambulab/BambuStudio/tree/master/resources/profiles/BBL",
    "BS-P": "Bambu Studio, Prozessprofil „0.20mm Standard @BBL P1P“ (installiert, gleich im Repo) – "
            "https://github.com/bambulab/BambuStudio/tree/master/resources/profiles/BBL",
    "BS-F": "Bambu Studio, Filamentprofile „@BBL P1P“ (system/BBL/filament/P1P) – "
            "https://github.com/bambulab/BambuStudio/tree/master/resources/profiles/BBL/filament/P1P",
    "KEV-PLA": "Kevins Bambu-Studio-Filament „Amazon Basics PLA“ (erbt Bambu PLA Basic @BBL P1P; Düse 205 °C, "
               "max. 210, Bett 47 °C)",
    "KEV-PETG": "Kevins PETG: Polymaker PolyLite PETG gelb 1,75 mm (Systemprofil „PolyLite PETG @BBL P1P“, erbt "
                "PolyLite PETG @base; Düse 255 °C, Bereich 220–270, Texturplatte 80 °C, Lüfter 40–90 %; Polymaker "
                "nennt 230–240 °C bei 30–50 mm/s) und Bambu Lab PETG Basic (Profil „Bambu PETG Basic @BBL X1C“, "
                "für den P1P 0.4 freigegeben; Düse 255 °C, erste Schicht 245, Texturplatte 70 °C; Bambu nennt "
                "230–260 °C); Filamentliste druck/filamente.py",
    "BS-Cut": "Bambu Studio, Schnittwerkzeug (GLGizmoAdvancedCut) – https://github.com/bambulab/BambuStudio/tree/master/src",
    "BS-Flow": "Bambu Studio, Flow.cpp (Linienabstand) – "
               "https://github.com/bambulab/BambuStudio/blob/master/src/libslic3r/Flow.cpp",
    "B-Sup": "Bambu Lab Wiki, Support – https://wiki.bambulab.com/en/software/bambu-studio/support",
    "B-Shr": "Bambu Lab Wiki, 3D Prints Shrinkage – https://wiki.bambulab.com/en/knowledge-sharing/3d-prints-shrinkage",
    "B-XY": "Bambu Lab Wiki, XY Hole/Contour Compensation – "
            "https://wiki.bambulab.com/en/software/bambu-studio/xy-hole-contour-compensation",
    "B-Fil": "Bambu Lab Wiki, Filament Guide (offene Drucker wie P1P: ABS/ASA/PC/PA „Not Recommended“) – "
             "https://wiki.bambulab.com/en/general/filament-guide-material-table",
    "B-TPU": "Bambu Lab Wiki, TPU Printing Guide – https://wiki.bambulab.com/en/knowledge-sharing/tpu-printing-guide",
    "B-PT": "Bambu Lab Wiki, Prime Tower – https://wiki.bambulab.com/en/software/bambu-studio/parameter/prime-tower",
    "B-Waste": "Bambu Lab Wiki, Reduce Waste – "
               "https://wiki.bambulab.com/en/software/bambu-studio/reduce-wasting-during-filament-change",
    "B-BT": "Bambu Lab Store, BT2.6 Self-Tapping Screw (Testdaten) – "
            "https://eu.store.bambulab.com/products/bt2-6-socket-head-cap-self-tapping-screw-shcs",
    "P-Mod": "Prusa Knowledge Base, Modeling with 3D printing in mind – "
             "https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135",
    "P-EF": "Prusa Knowledge Base, Elephant foot compensation – "
            "https://help.prusa3d.com/article/elephant-foot-compensation_114487",
    "P-PETG": "Prusa Knowledge Base, PETG – https://help.prusa3d.com/article/petg_2059",
    "P-ABS": "Prusa Knowledge Base, ABS – https://help.prusa3d.com/article/abs_2058",
    "P-ASA": "Prusa Knowledge Base, ASA – https://help.prusa3d.com/article/asa_1809",
    "P-PC": "Prusa Knowledge Base, Polycarbonate – https://help.prusa3d.com/article/polycarbonate-pc_165812",
    "P-PA": "Prusa Knowledge Base, Polyamide – https://help.prusa3d.com/article/polyamide-nylon_167188",
    "P-Flex": "Prusa Knowledge Base, Flexible materials – https://help.prusa3d.com/article/flexible-materials_2057",
    "H-FDM": "Hubs, How to design parts for FDM 3D printing – "
             "https://www.hubs.com/knowledge-base/how-design-parts-fdm-3d-printing/",
    "H-Info": "3D Hubs, Design Rules for 3D Printing (Tabelle) – "
              "https://www.core77.com/posts/74401/Design-Rules-for-3D-Printing",
    "H-Snap": "Hubs, How to design snap-fit joints – "
              "https://www.hubs.com/knowledge-base/how-design-snap-fit-joints-3d-printing/",
    "H-LH": "Hubs, How to design living hinges – "
            "https://www.hubs.com/knowledge-base/how-design-living-hinges-3d-printing/",
    "X": "Xometry, Quick Design Guide FDM – https://xometry.pro/en/?p=154421",
    "HR": "Hydra Research, Design Rules – https://www.hydraresearch3d.com/design-rules",
    "RX": "ruthex Gewindeeinsätze, Maßtabelle – https://www.ruthex.de/collections/gewindeeinsatze",
    "CK-Tab": "CNC Kitchen Store, Heat-Set Inserts (Maßtabelle) – https://cnckitchen.store",
    "CK-DS": "CNC Kitchen, Are our heat-set insert datasheets wrong? – "
             "https://www.cnckitchen.com/blog/are-our-heat-set-insert-datasheets-wrong",
    "CK-Tips": "CNC Kitchen, Tips and tricks for heat-set inserts – "
               "https://www.cnckitchen.com/blog/tips-and-tricks-for-heat-set-inserts",
    "CK-Nut": "CNC Kitchen, Helicoils, threaded inserts and embedded nuts – "
              "https://www.cnckitchen.com/blog/helicoils-threaded-insets-and-embedded-nuts-in-3d-prints-strength-amp-strength-assessment",
    "CK-45": "CNC Kitchen, Stop printing flat – https://www.cnckitchen.com/blog/stop-printing-flat-the-45-secret-for-stronger-parts",
    "CK-Kammer": "CNC Kitchen, Does a heated chamber make your prints stronger? – "
                 "https://www.cnckitchen.com/blog/does-a-heated-chamber-make-your-3d-prints-stronger",
    "CK-Grad": "CNC Kitchen, Gradient infill – https://www.cnckitchen.com/blog/gradient-infill-for-3d-prints",
    "BOSL": "BOSL2 shapes3d (Tropfenform 45°) – https://github.com/BelfrySCAD/BOSL2/wiki/shapes3d.scad",
    "BAY": "Bayer MaterialScience, Snap-Fit Joints for Plastics – "
           "https://cdn.sparkfun.com/assets/home_page_posts/1/4/1/0/Plastic_Snap_fit_design.pdf",
    "MH": "MatterHackers, Living hinge design guidelines – "
          "https://www.matterhackers.com/news/living-hinge:--design-guidelines-and-material-selection",
    "W": "Würth, DINO Kapitel 9 (Schrauben für Kunststoffe) – "
         "https://www.wuerth-industrie.com/web/media/de/pictures/wuerthindustrie/technikportal/dinokapitel/Kapitel_09_DINO_techn_Teil.pdf",
    "ISO": "DIN EN ISO 4032 (Sechskantmuttern) – https://fasten.it/norms/norm/din_en_iso_4032",
    "NOP": "nophead, Polyholes – https://hydraraptor.blogspot.com/2011/02/polyholes.html",
    "RJG": "Schwindmaße gängiger Kunststoffe (Spritzguss) – "
           "https://rjcmold.com/wp-content/uploads/Shrinkage-Rates-for-Common-Plastics.pdf",
    "EW": "Erfahrungswert (nicht direkt belegt, vorsichtig gewählt)",
}

# ---------------------------------------------------------------------------------------------------------------------
# Drucker
# ---------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Drucker:
    """Druckerprofil. Standardwerte: Kevins Bambu Lab P1P mit 0,4-mm-Düse und Profil „0.20mm Standard @BBL P1P“."""

    name: str = "Bambu Lab P1P"
    bauraum: tuple[float, float, float] = (256.0, 256.0, 250.0)  # BS-M: 256 × 256, Druckhöhe 250 (Datenblatt: 256³)
    sperrflaeche: tuple[float, float] = (18.0, 28.0)  # BS-M bed_exclude_area: vorne links (x 0–18, y 0–28) frei halten
    rand: float = 5.0                  # Platz für Brim (Standard 5 mm, BS-P) bzw. Sicherheitsabstand
    duese: float = 0.4
    duese_material: str = "Edelstahl"  # B-P1P, BS-M (stainless_steel)
    duese_gehaertet: bool = False      # CF/GF-Filamente brauchen HRC 40 (BS-F) – gehärtetes Hotend ist Zubehör
    linienbreite: float = 0.42         # Außenwand, BS-P
    linienbreite_innen: float = 0.45   # Innenwand und Füllung, BS-P
    erste_schicht_breite: float = 0.50  # BS-P
    schichthoehe: float = 0.20         # BS-P
    erste_schicht: float = 0.20        # BS-P
    schicht_min: float = 0.08          # BS-M
    schicht_max: float = 0.28          # BS-M
    waende: int = 2                    # Standard im Profil, BS-P („0.20mm Strength“: 6 Wände, 25 %)
    deckschichten: int = 5             # oben (mind. 1,0 mm), BS-P
    bodenschichten: int = 3            # BS-P
    elefantenfuss_kompensation: float = 0.15  # BS-P
    stuetzen_schwelle: float = 30.0    # vom Waagrechten, Profil 0,20 mm (BS-P)
    brim: float = 5.0                  # BS-P
    duese_max: float = 300.0           # °C, B-P1P
    bett_max: float = 100.0            # °C, B-P1P
    geschlossen: bool = False          # offener Rahmen, keine Kammer (B-P1P); Einhausung als Kit (B-Kit)
    zusatzluefter: bool = False        # Zusatz-Bauteillüfter optional (B-P1P, BS-M auxiliary_fan = 0)
    prime_tower_breite: float = 35.0   # BS-P, nur mit AMS
    ams: str = ("Zubehör: AMS, AMS 2 Pro (mit Upgrade-Kit) oder AMS HT, bis 4 Einheiten; ohne AMS Farbwechsel "
                "von Hand per Pause")  # B-AMS

    @property
    def linienabstand_innen(self) -> float:
        """Abstand benachbarter Innenwände: Breite − Schichthöhe · (1 − π/4) (BS-Flow)."""
        return self.linienbreite_innen - self.schichthoehe * (1 - math.pi / 4)

    def wandstaerke(self, bahnen: int) -> float:
        """Wandstärke für ``bahnen`` Wandlinien (2 → 0,83, 3 → 1,23, 4 → 1,64 mm bei 0,2-mm-Schicht)."""
        if bahnen < 1:
            raise ValueError("mindestens eine Bahn")
        return self.linienbreite + (bahnen - 1) * self.linienabstand_innen

    def z_mass(self, hoehe: float) -> float:
        """Nächstes Vielfaches der Schichthöhe (Z-Maße so konstruieren, sonst rundet der Slicer)."""
        return round(round(hoehe / self.schichthoehe) * self.schichthoehe, 4)

    @property
    def ueberhang_grenze(self) -> float:
        """Überhang ohne Stütze laut Profil, von der Senkrechten (90° − Stützenschwelle)."""
        return 90.0 - self.stuetzen_schwelle


P1P = Drucker()

# ---------------------------------------------------------------------------------------------------------------------
# Materialien
# ---------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Material:
    """Konstruktionsrelevante Werte eines druckbaren Materials (id wie im Kev-CAD-Katalog)."""

    id: str
    name: str
    dichte: float                       # g/cm³ (Kev-CAD-Katalog)
    aliase: tuple[str, ...] = ()
    verfahren: str = "3d-druck"         # "3d-druck" (FDM) oder "harzdruck"
    ueberhang_max: float = 55.0         # ° von der Senkrechten ohne Stütze (bei 0,2 mm Schicht)
    bruecke_gut: float = 10.0           # mm, bis hier ohne nennenswerten Durchhang (H-Info, X, HR)
    bruecke_max: float = 20.0           # mm, darüber Stütze (EW)
    kragarm_max: float = 1.0            # mm waagrecht frei auskragend ohne Stütze (EW, ca. 2 Bahnen)
    wand_empfohlen: float = 1.2         # mm, 3 Bahnen (H-Info, X, HR)
    schwund: float = 0.3                # % linear (Richtwert)
    verzug: int = 0                     # 0 kaum, 1 gering, 2 mittel, 3 stark (offener Bauraum)
    verzug_laenge: float | None = None  # mm Auflagelänge, ab der offen Verzug zu erwarten ist (EW)
    schnapp_dehnung: float | None = 1.5  # % zulässig bei einmaligem Fügen (EW aus BAY, siehe 3d-druck.md)
    filmscharnier: str = "nein"         # "ja", "bedingt", "nein"
    z_festigkeit: float = 0.5           # Zugfestigkeit quer zu den Schichten / in der Ebene, offen gedruckt
    einhausung: bool = False            # braucht einen geschlossenen Bauraum (B-Fil: offen „Not Recommended“)
    gehaertete_duese: bool = False      # abrasiv (CF/GF), Profil verlangt HRC 40 (BS-F)
    duese_temp: str = ""
    bett_temp: str = ""
    kammer: str = ""
    trocknen: str = ""
    ams: str = "ja, falls ein AMS vorhanden ist"
    hinweise: tuple[str, ...] = ()
    quellen: tuple[str, ...] = ()

    @property
    def fdm(self) -> bool:
        return self.verfahren == "3d-druck"


_OFFEN = "offen (P1P ohne Gehäuse)"
_NUR_GESCHLOSSEN = ("nur mit Einhausung (P1P Enclosure Kit oder Druckbox), Bett 10 min vorheizen; offen rät Bambu "
                    "ab – sonst PLA oder PETG nehmen")

MATERIALIEN: dict[str, Material] = {m.id: m for m in (
    Material(
        "pla", "PLA", 1.24, ("pla", "polylactid", "polylactide", "amazon basics pla"),
        ueberhang_max=60.0, bruecke_max=30.0, schwund=0.3, verzug=0,
        schnapp_dehnung=1.5, filmscharnier="nein", z_festigkeit=0.5,
        duese_temp="205 °C (Kevins „Amazon Basics PLA“, max. 210; Bambu PLA Basic 220, 190–240)",
        bett_temp="47 °C (Amazon Basics PLA; Bambu-Profil 65 °C Texturplatte, 35 °C Cool Plate)",
        kammer=_OFFEN + " – ideal für PLA", trocknen="55 °C 8 h",
        hinweise=("Kevins Standardfilament: Amazon Basics PLA (Bambu-Studio-Profil, erbt Bambu PLA Basic @BBL P1P)",
                  "weich ab ca. 55 °C – nicht für Auto, Sonne, Heizungsnähe",
                  "spröde: Schnapphaken und Filmscharniere ungeeignet"),
        quellen=("KEV-PLA", "BS-F", "B-P1P", "B-Fil", "CK-45", "MH", "H-Snap"),
    ),
    Material(
        "pla-cf", "PLA-CF (PLA mit Kohlefaser)", 1.26, ("pla-cf", "pla cf", "carbon pla"),
        ueberhang_max=55.0, bruecke_max=25.0, schwund=0.2, verzug=0,
        schnapp_dehnung=1.0, filmscharnier="nein", z_festigkeit=0.45, gehaertete_duese=True,
        duese_temp="230 °C (210–250)", bett_temp="65 °C Texturplatte", kammer=_OFFEN, trocknen="55 °C 8 h",
        hinweise=("braucht gehärtete Düse (Profil HRC 40); der P1P hat ab Werk Edelstahl – gehärtetes Hotend "
                  "nachrüsten, sonst PLA ohne Faser", "steif, aber spröde"),
        quellen=("BS-F", "B-P1P", "B-Fil", "B-Shr"),
    ),
    Material(
        "petg", "PETG", 1.27, ("petg", "pet-g", "polylite petg", "polymaker polylite petg"),
        ueberhang_max=55.0, bruecke_max=20.0, schwund=0.4, verzug=1, verzug_laenge=180.0,
        schnapp_dehnung=2.5, filmscharnier="bedingt", z_festigkeit=0.4,
        duese_temp="255 °C (PolyLite PETG @BBL P1P und Bambu PETG Basic @BBL X1C, dort erste Schicht 245; Bereich "
                   "220–270); es gilt das Preset des gewählten Filaments",
        bett_temp="80 °C Texturplatte mit PolyLite PETG, 70 °C mit Bambu PETG Basic (Engineering-Platte 70 °C)",
        kammer=_OFFEN + "; Bambu empfiehlt geschlossen, weil kühle Umgebung die Lagenhaftung senkt – Zugluft "
                        "vermeiden", trocknen="65 °C 12 h",
        hinweise=("Kevins PETG: Polymaker PolyLite PETG gelb oder Bambu PETG Basic; vor dem Druck fragen, welches "
                  "im Drucker ist – sein Preset kommt ins 3MF (druck/filamente.py)",
                  "Brücken und Überhänge etwas schlechter als PLA (P-PETG)",
                  "zäh, gut für Schnapphaken und Clips; Filmscharnier nur für wenige Zyklen",
                  "offen gedruckt eher etwas schwächer quer zu den Schichten (B-Fil)"),
        quellen=("KEV-PETG", "BS-F", "B-Fil", "P-PETG", "CK-45"),
    ),
    Material(
        "abs", "ABS", 1.04, ("abs", "acrylnitril-butadien-styrol"),
        ueberhang_max=55.0, bruecke_max=20.0, schwund=0.7, verzug=3, verzug_laenge=50.0,
        schnapp_dehnung=2.0, filmscharnier="nein", z_festigkeit=0.54, einhausung=True,
        duese_temp="270 °C (240–280)", bett_temp="100 °C Texturplatte (90 °C Engineering-Platte)",
        kammer=_NUR_GESCHLOSSEN, trocknen="80 °C 8 h",
        hinweise=("auf dem offenen P1P: Verzug, Lagentrennung, Risse – Bambu rät ab (B-Fil)",
                  "Prusa nennt für FDM bis 1–2 % Schwund"),
        quellen=("BS-F", "B-Fil", "B-P1P", "P-ABS", "RJG", "CK-Kammer"),
    ),
    Material(
        "asa", "ASA", 1.07, ("asa", "acrylester-styrol-acrylnitril"),
        ueberhang_max=55.0, bruecke_max=20.0, schwund=0.6, verzug=3, verzug_laenge=60.0,
        schnapp_dehnung=2.0, filmscharnier="nein", z_festigkeit=0.38, einhausung=True,
        duese_temp="260 °C (240–280)", bett_temp="100 °C Texturplatte", kammer=_NUR_GESCHLOSSEN,
        trocknen="80 °C 8 h",
        hinweise=("UV-beständig, für draußen; verzieht weniger als ABS (P-ASA), offen aber trotzdem nicht empfohlen",),
        quellen=("BS-F", "B-Fil", "P-ASA", "RJG", "CK-45"),
    ),
    Material(
        "pc-filament", "PC (Filament)", 1.20, ("pc filament", "polycarbonat filament", "pc-filament"),
        ueberhang_max=50.0, bruecke_max=15.0, schwund=0.8, verzug=3, verzug_laenge=40.0,
        schnapp_dehnung=3.0, filmscharnier="nein", z_festigkeit=0.65, einhausung=True,
        duese_temp="280 °C (260–290)", bett_temp="100 °C (P1P-Maximum; Bambu empfiehlt 100–120 °C)",
        kammer=_NUR_GESCHLOSSEN, trocknen="80 °C 8 h (Pflicht)",
        hinweise=("starker Verzug: runde Kanten verziehen weniger, nicht über das ganze Bett, weniger Füllung (P-PC)",),
        quellen=("BS-F", "B-Fil", "B-P1P", "P-PC", "RJG", "CK-Kammer", "BAY"),
    ),
    Material(
        "pa", "PA (Nylon)", 1.14, ("pa", "nylon", "polyamid", "pa6", "pa12", "copa"),
        ueberhang_max=50.0, bruecke_max=15.0, schwund=1.2, verzug=3, verzug_laenge=50.0,
        schnapp_dehnung=4.0, filmscharnier="ja", z_festigkeit=0.5, einhausung=True,
        duese_temp="260 °C (240–280)", bett_temp="100 °C Texturplatte, Klebestift", kammer=_NUR_GESCHLOSSEN,
        trocknen="80 °C 8–12 h (Pflicht, nimmt bis 10 % Wasser auf)", ams="ja (trocken, am besten AMS HT)",
        hinweise=("zäh: beste Wahl für Schnapphaken und Filmscharniere", "Maße ändern sich mit der Feuchte"),
        quellen=("BS-F", "B-Fil", "P-PA", "H-LH", "MH", "RJG"),
    ),
    Material(
        "pa-cf", "PA-CF (Nylon mit Kohlefaser)", 1.20, ("pa-cf", "pa cf", "nylon cf", "pa6-cf", "pa12-cf",
                                                       "carbon nylon"),
        ueberhang_max=55.0, bruecke_max=20.0, schwund=0.3, verzug=2, verzug_laenge=100.0,
        schnapp_dehnung=1.5, filmscharnier="nein", z_festigkeit=0.5, einhausung=True, gehaertete_duese=True,
        duese_temp="290 °C (260–300)", bett_temp="100 °C, Klebestift", kammer=_NUR_GESCHLOSSEN,
        trocknen="80 °C 8–12 h (Pflicht)", ams="nur Bambu PA-CF/PAHT-CF, trocken (B-Fil)",
        hinweise=("braucht gehärtete Düse (HRC 40) und Einhausung – auf dem P1P ab Werk beides nicht vorhanden",
                  "CF-Typen verziehen deutlich weniger als reines PA (P-PA)"),
        quellen=("BS-F", "B-Fil", "B-P1P", "P-PA"),
    ),
    Material(
        "tpu-95a", "TPU 95A (flexibel)", 1.21, ("tpu", "tpu 95a", "flex", "flexibel", "filaflex"),
        ueberhang_max=45.0, bruecke_gut=5.0, bruecke_max=8.0, kragarm_max=0.5, wand_empfohlen=1.2,
        schwund=0.3, verzug=0, schnapp_dehnung=None, filmscharnier="ja", z_festigkeit=0.8,
        duese_temp="230 °C (200–250)", bett_temp="45 °C Texturplatte (30 °C Cool Plate)", kammer=_OFFEN,
        trocknen="70 °C 8 h (Pflicht), Lagerung unter 20 % rF",
        ams="nein – nicht über AMS oder AMS 2 Pro; nur AMS HT (TPU-Ausgang) oder externe Spule (beim P1P ohne AMS "
            "der Normalfall)",
        hinweise=("Brücken und Überhänge sehr schlecht (P-Flex): Teil so legen, dass nichts überhängt",
                  "langsam: max. 3,6 mm³/s (ca. 40 mm/s); Flow-Dynamics-Kalibrierung aus",
                  "Passungen eher mit mehr Spiel (0,3–0,5 mm), Material gibt nach"),
        quellen=("BS-F", "B-TPU", "P-Flex"),
    ),
    Material(
        "harz-standard", "Harz Standard (Harzdruck)", 1.18, ("harz", "resin", "standardharz", "photopolymer",
                                                            "sla", "msla"),
        verfahren="harzdruck", ueberhang_max=60.0, bruecke_gut=5.0, bruecke_max=10.0, wand_empfohlen=1.0,
        schwund=0.5, verzug=0, schnapp_dehnung=1.0, filmscharnier="nein", z_festigkeit=0.9,
        ams="–",
        hinweise=("kein Harzdrucker vorhanden: Kevins Drucker ist ein Bambu Lab P1P (FDM)",),
        quellen=("B-P1P",),
    ),
)}


def material(name: str | Material) -> Material:
    """Material nach id oder Alias (Groß-/Kleinschreibung egal). Unbekannt: ``ValueError`` mit Vorschlägen."""
    if isinstance(name, Material):
        return name
    key = str(name).strip().lower()
    if key in MATERIALIEN:
        return MATERIALIEN[key]
    for m in MATERIALIEN.values():
        if key in m.aliase or key == m.name.lower():
            return m
    import difflib
    namen = list(MATERIALIEN) + [a for m in MATERIALIEN.values() for a in m.aliase]
    vorschlaege = difflib.get_close_matches(key, namen, n=3)
    raise ValueError(f"Unbekanntes Druckmaterial „{name}“. Druckbar sind: {', '.join(MATERIALIEN)}"
                     + (f". Meintest du: {', '.join(vorschlaege)}?" if vorschlaege else ""))


# ---------------------------------------------------------------------------------------------------------------------
# Schwellen der Prüfung (abgeleitet, mm)
# ---------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Schwellen:
    """Grenzwerte, nach denen ``pruefe_druckteil`` Hinweise vergibt."""

    wand_fehler: float           # dünner als eine Bahn: fällt im Slicer weg
    wand_warnung: float          # unter 2 Bahnen
    wand_hinweis: float          # unter 3 Bahnen bzw. Materialempfehlung
    schicht_fehler: float        # waagrechte Platte dünner als eine Schicht
    schicht_warnung: float       # unter 2 Schichten
    schicht_hinweis: float       # unter 3 Schichten
    bohrung_fehler: float = 1.0  # Ø kleiner: setzt zu (X: 1 mm)
    bohrung_warnung: float = 2.0  # H-Info: 2 mm
    stift_warnung: float = 2.0   # Ø kleiner: bricht ab (EW)
    stift_hinweis: float = 3.0   # H-Info: Stifte ab 3 mm
    auflage_min: float = 25.0    # mm² Auflagefläche (EW)
    schlank: float = 10.0        # Höhe / √Auflage, darüber Kippgefahr (EW)
    z_toleranz: float = 0.02     # Abweichung vom Schichtraster, ab der ein Hinweis kommt
    bettfase: float = 0.5        # empfohlene Fase gegen Elefantenfuß (EW, 1–2 Erstlagenbreiten)
    verzug_eckradius: float = 4.0  # HR: Bettecken R > 4 mm


def schwellen(drucker: Drucker, mat: Material) -> Schwellen:
    if not mat.fdm:
        return Schwellen(0.3, 0.5, mat.wand_empfohlen, 0.05, 0.1, 0.2, bohrung_fehler=0.5, bohrung_warnung=1.0,
                         stift_warnung=1.0, stift_hinweis=1.5)
    return Schwellen(
        wand_fehler=drucker.linienbreite * 0.95,
        wand_warnung=0.8,                       # H-Info/X: Mindestwand 0,8; 2 Bahnen = 0,83
        wand_hinweis=mat.wand_empfohlen,
        schicht_fehler=drucker.schichthoehe * 0.75,
        schicht_warnung=2 * drucker.schichthoehe,
        schicht_hinweis=3 * drucker.schichthoehe,
    )


# ---------------------------------------------------------------------------------------------------------------------
# Bohrungen und Passungen
# ---------------------------------------------------------------------------------------------------------------------


def bohrung_zugabe(d: float) -> float:
    """Typisches Untermaß gedruckter Bohrungen (Durchmesser, mm) ohne Lochkompensation im Slicer.

    CNC Kitchen hat bei Ø 4 mm im Mittel −0,25 mm gemessen (CK-DS); kleine Bohrungen verlieren relativ mehr
    (Polygonfehler, NOP). Senkrecht gedruckt; waagrecht ohne Tropfenform oben zusätzlich ca. 0,1–0,2 mm (EW).
    """
    if d < 3:
        return 0.3
    if d <= 10:
        return 0.25
    if d <= 30:
        return 0.2
    return 0.15


# Durchmesser-Zugabe der gedruckten Bohrung auf das Nennmaß der Welle (Metall oder Druckteil), ohne Slicer-Kompensation.
PASSUNGEN: dict[str, dict] = {
    "press": {"spiel": 0.0, "text": "Presspassung (eingepresst, hält ohne Kleber)", "quelle": "EW, CK-DS"},
    "fest": {"spiel": 0.15, "text": "Übergang/Schiebesitz (von Hand fügbar, sitzt fest)", "quelle": "EW, HR"},
    "spiel": {"spiel": 0.3, "text": "Spielpassung (dreht und gleitet leicht)", "quelle": "P-Mod (≥ 0,3)"},
    "lose": {"spiel": 0.5, "text": "lose (bewegliche Teile, Toleranzen unkritisch)", "quelle": "H-Info, X"},
}
PRINT_IN_PLACE_SPALT = (0.3, 0.5)   # mm je Seite zwischen beweglichen Teilen (P-Mod, H-Info)
PRINT_IN_PLACE_Z_SPALT = 0.3        # mm in Z, mind. eine Schicht und etwas Luft (EW)
SCHNITT_TOLERANZ = 0.1              # Bambu Studio, Schnittwerkzeug: Toleranz für Stifte/Schwalbenschwanz (BS-Cut)

# ---------------------------------------------------------------------------------------------------------------------
# Gewindeeinsätze (Heat-Set Inserts), Muttern, Schrauben
# ---------------------------------------------------------------------------------------------------------------------

# Werte in mm: laenge, aussen (D1), bohrung (CAD-Ø), wand_min (Wand um den Einsatz), kurz (Länge der Kurzversion)
GEWINDEEINSAETZE: dict[str, dict[str, dict[str, float | None]]] = {
    "ruthex": {   # RX
        "M2": {"laenge": 4.0, "aussen": 3.6, "bohrung": 3.2, "wand_min": 1.3, "kurz": None},
        "M2.5": {"laenge": 5.7, "aussen": 4.6, "bohrung": 4.0, "wand_min": 1.6, "kurz": None},
        "M3": {"laenge": 5.7, "aussen": 4.6, "bohrung": 4.0, "wand_min": 1.6, "kurz": 4.0},
        "M3-voron": {"laenge": 4.0, "aussen": 5.0, "bohrung": 4.4, "wand_min": 1.3, "kurz": None},
        "M4": {"laenge": 8.1, "aussen": 6.3, "bohrung": 5.6, "wand_min": 2.1, "kurz": 4.0},
        "M5": {"laenge": 9.5, "aussen": 7.1, "bohrung": 6.4, "wand_min": 2.6, "kurz": 5.8},
        "M6": {"laenge": 12.7, "aussen": 8.7, "bohrung": 8.0, "wand_min": 3.3, "kurz": 6.8},
        "M8": {"laenge": 12.7, "aussen": 10.1, "bohrung": 9.6, "wand_min": 4.5, "kurz": None},
        "M10": {"laenge": 12.7, "aussen": 12.6, "bohrung": 12.0, "wand_min": 6.0, "kurz": None},
    },
    "cnc-kitchen": {   # CK-Tab
        "M2": {"laenge": 3.0, "aussen": 3.6, "bohrung": 3.2, "wand_min": 1.3, "kurz": None},
        "M2.5": {"laenge": 4.0, "aussen": 4.6, "bohrung": 4.0, "wand_min": 1.6, "kurz": None},
        "M3": {"laenge": 5.7, "aussen": 4.6, "bohrung": 4.0, "wand_min": 1.6, "kurz": 3.0},
        "M3-voron": {"laenge": 4.0, "aussen": 5.0, "bohrung": 4.4, "wand_min": 1.6, "kurz": None},
        "M4": {"laenge": 8.1, "aussen": 6.3, "bohrung": 5.7, "wand_min": 2.1, "kurz": 4.0},
        "M5": {"laenge": 9.5, "aussen": 7.1, "bohrung": 6.5, "wand_min": 2.6, "kurz": 5.8},
        "M6": {"laenge": 12.7, "aussen": 8.7, "bohrung": 8.1, "wand_min": 3.3, "kurz": None},
        "M8": {"laenge": 12.7, "aussen": 10.2, "bohrung": 9.7, "wand_min": 4.5, "kurz": None},
        "M10": {"laenge": 12.7, "aussen": 12.6, "bohrung": 12.0, "wand_min": 6.0, "kurz": None},
    },
}
EINSATZ_TIEFE_ZUGABE = 1.0   # Sackloch mind. Einsatzlänge + 1 mm (RX, CK-Tips)
EINSATZ_BOHRUNG_PLUS = 0.2   # CNC-Kitchen-Test 2026: Nennmaß + 0,2 im CAD (M3: 4,2) ist der beste Kompromiss (CK-DS)


def einsatz(groesse: str, hersteller: str = "ruthex", kurz: bool = False) -> dict[str, float]:
    """Maße der Tasche für einen Gewindeeinsatz: ``bohrung`` (CAD-Ø), ``tiefe`` (Sackloch), ``wand_min``, ``laenge``."""
    tab = GEWINDEEINSAETZE[hersteller]
    key = groesse.upper().replace(",", ".").replace("-VORON", "-voron")
    if key not in tab:
        raise ValueError(f"Keine Einsatzgröße {groesse} bei {hersteller}: {', '.join(tab)}")
    e = tab[key]
    laenge = e["kurz"] if kurz and e["kurz"] else e["laenge"]
    return {"bohrung": e["bohrung"], "tiefe": laenge + EINSATZ_TIEFE_ZUGABE, "wand_min": e["wand_min"],
            "laenge": laenge, "aussen": e["aussen"]}


# ISO 4032: Schlüsselweite s, Höhe m (max), Eckmaß e (min)
MUTTERN_ISO4032: dict[str, dict[str, float]] = {
    "M2": {"sw": 4.0, "hoehe": 1.6, "eckmass": 4.32},
    "M2.5": {"sw": 5.0, "hoehe": 2.0, "eckmass": 5.45},
    "M3": {"sw": 5.5, "hoehe": 2.4, "eckmass": 6.01},
    "M4": {"sw": 7.0, "hoehe": 3.2, "eckmass": 7.66},
    "M5": {"sw": 8.0, "hoehe": 4.7, "eckmass": 8.79},
    "M6": {"sw": 10.0, "hoehe": 5.2, "eckmass": 11.05},
    "M8": {"sw": 13.0, "hoehe": 6.8, "eckmass": 14.38},
    "M10": {"sw": 16.0, "hoehe": 8.4, "eckmass": 17.77},
}
MUTTER_SPIEL_SW = 0.3       # mm auf die Schlüsselweite (EW, Praxis 0,2–0,4)
MUTTER_SPIEL_HOEHE = 0.3    # mm auf die Höhe (EW)


def muttertasche(groesse: str) -> dict[str, float]:
    """Sechskanttasche: ``sw`` (über die Flächen, mit Spiel), ``eck`` (über die Ecken), ``tiefe``."""
    m = MUTTERN_ISO4032[groesse.upper().replace(",", ".")]
    sw = m["sw"] + MUTTER_SPIEL_SW
    return {"sw": sw, "eck": sw / math.cos(math.radians(30)), "tiefe": m["hoehe"] + MUTTER_SPIEL_HOEHE}


# Kernloch (CAD-Ø) für Kunststoff-Direktschrauben, senkrecht gedruckt. Bambu BT-Schrauben (B-BT); liegend eine Stufe
# (ca. +0,1 mm) größer, sonst reißt die Schicht.
KERNLOCH_BAMBU_BT: dict[str, dict[str, float]] = {
    "pla": {"M2": 1.80, "M2.5": 2.17, "M3": 2.57},
    "petg": {"M2": 1.77, "M2.5": 2.07, "M3": 2.55},
}
# Würth WÜPLAST (W): Kernloch, Tubus-Außen-Ø und Einschraubtiefe als Vielfache des Nenn-Ø
KERNLOCH_WUERTH: dict[str, tuple[float, float, float]] = {
    "abs": (0.80, 2.0, 2.0), "asa": (0.78, 2.0, 2.0), "pa": (0.75, 1.85, 1.7), "pa-cf": (0.81, 2.0, 2.0),
    "petg": (0.75, 1.85, 1.7), "pc-filament": (0.85, 2.5, 2.2), "tpu-95a": (0.70, 2.0, 2.0),
}


def kernloch(groesse: str, mat: str | Material = "petg", liegend: bool = False) -> dict[str, float]:
    """Kernloch, Tubus-Ø und Einschraubtiefe für eine selbstschneidende Kunststoffschraube (``groesse`` wie "M3")."""
    m = material(mat)
    key = groesse.upper().replace(",", ".")
    d = float(key.lstrip("M"))
    if m.id in KERNLOCH_BAMBU_BT and key in KERNLOCH_BAMBU_BT[m.id]:
        loch = KERNLOCH_BAMBU_BT[m.id][key]
        tubus, tiefe = 2.0 * d, 2.0 * d
    else:
        f, ft, fe = KERNLOCH_WUERTH.get(m.id, (0.85, 2.0, 2.0))  # PLA/PLA-CF ohne Würth-Wert: Bambu-Verhältnis ≈ 0,85
        loch, tubus, tiefe = f * d, ft * d, fe * d
    if liegend:
        loch += 0.1
    return {"kernloch": round(loch, 2), "tubus": round(tubus, 2), "tiefe": round(tiefe, 2)}


# ---------------------------------------------------------------------------------------------------------------------
# Weitere Regeln (für Text und Rezepte)
# ---------------------------------------------------------------------------------------------------------------------

TEXT = {
    "strich_erhaben": 0.9,     # mm Strichbreite erhaben, ≥ 2 Bahnen (HR > 0,9)
    "strich_vertieft": 0.5,    # mm Strichbreite vertieft (HR, X)
    "hoehe": 0.6,              # mm Prägehöhe/-tiefe, 3 Schichten (X ≥ 0,5)
    "schrift_min": 3.5,        # mm Zeichenhöhe (X), empfohlen 5
    "schrift_empfohlen": 5.0,
}

SCHNAPPHAKEN = {
    "faktor_rechteck": 0.67,   # y = 0,67 · ε · l² / h (konstanter Querschnitt, BAY)
    "faktor_verjuengt": 1.09,  # Dicke zur Spitze auf h/2 verjüngt (BAY)
    "wiederholt": 0.6,         # zulässige Dehnung bei häufigem Lösen ≈ 60 % (BAY)
    "wurzelradius_zu_h": 0.6,  # R/h ≈ 0,6 optimal (BAY), mind. 0,5 · h (H-Snap)
    "laenge_zu_h": 5.0,        # l ≥ 5 · h (EW)
    "breite_min": 5.0,         # mm (H-Snap)
    "einfuehrwinkel": 30.0,    # ° (BAY)
    "rueckhalt_loesbar": 45.0,  # °, 90° ≈ unlösbar (EW)
}


def schnapp_auslenkung(laenge: float, dicke: float, mat: str | Material = "petg", verjuengt: bool = False,
                       oft_loesen: bool = False) -> float:
    """Zulässige Auslenkung (Hakentiefe) eines Schnapphakens in mm nach Bayer: y = k · ε · l² / h."""
    m = material(mat)
    if m.schnapp_dehnung is None:
        raise ValueError(f"{m.name}: Schnapphaken nicht sinnvoll (flexibles Material)")
    eps = m.schnapp_dehnung / 100 * (SCHNAPPHAKEN["wiederholt"] if oft_loesen else 1.0)
    k = SCHNAPPHAKEN["faktor_verjuengt" if verjuengt else "faktor_rechteck"]
    return k * eps * laenge ** 2 / dicke


FILMSCHARNIER = {"dicke": (0.4, 0.6), "laenge_min": 3.0}   # H-LH (0,4–0,6 mm, mind. 2 Schichten), Länge EW

TEILUNG = {
    "stift_d": (3.0, 5.0),     # mm Passstift (Metall Ø 3–5 oder gedruckt ≥ 5, H-FDM)
    "stift_tiefe_zu_d": 1.5,   # Bohrtiefe je Seite ≥ 1,5 · d (EW; Bambu-Schnittwerkzeug: Tiefenverhältnis 3 für den ganzen Stift)
    "spiel": SCHNITT_TOLERANZ,
    "fase_fuge": 0.3,          # mm Fase an der Fuge, verdeckt Versatz und Elefantenfuß (EW)
}

AMS = {
    "farbe_min_breite": 0.9,   # mm, ≥ 2 Bahnen (EW)
    "farbe_min_hoehe": 0.4,    # mm, ≥ 2 Schichten (EW)
    "prime_tower": 35.0,       # mm Breite (BS-P)
}

FESTIGKEIT = (
    "Wände bringen mehr Festigkeit als Füllung: Funktionsteile mit 3–4 Wänden (1,2–1,6 mm), 20–40 % Füllung "
    "(Gyroid/Grid) statt 2 Wänden und 15 % (Standardprofil); Biegespannung liegt außen (HR, CK).",
    "Schichthaftung ist die Schwachstelle: Zug und Biegung quer zu den Schichten halten nur 40–70 % (CK-45). "
    "Teil so legen, dass Hauptlasten in der Schichtebene liegen; Haken, Laschen, Stifte flach statt stehend.",
    "Innenkanten verrunden (R ≥ 0,5 · Wanddicke): Kerben an Schichtübergängen reißen zuerst (BAY, H-FDM).",
)
