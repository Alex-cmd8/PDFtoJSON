# -*- coding: utf-8 -*-
"""
Generator przypadków testowych dla parsera PDF -> JSON (odwołania do KIO).

Każdy przypadek to katalog test_XX_<nazwa>/ z plikami w tej samej konwencji co dane/przyklad_XX:
  odwolanie.pdf + odwolanie.json
  pelnomocnictwo.pdf + pelnomocnictwo.json
  potwierdzenie_przelewu.pdf + przelew.json
Oczekiwane JSON-y są wyliczane z tej samej specyfikacji, z której renderowany jest PDF,
więc PDF i JSON są zawsze spójne. Układy dokumentów są CELOWO inne niż w przykładach.

Uruchomienie:  python3 generate.py <katalog_wyjściowy>
Wymaga: reportlab; dla przypadku skanu dodatkowo: pdftoppm, Pillow, img2pdf.
"""
import json, os, sys, random, subprocess, shutil, tempfile

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_JUSTIFY, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                PageBreak, KeepTogether)
from reportlab.pdfgen import canvas as rl_canvas

# ---------------------------------------------------------------- fonty
FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation",
             "/usr/share/fonts/truetype/liberation2", "C:/Windows/Fonts"]

def _find(name):
    for d in FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(name)

def reg(alias, fname):
    pdfmetrics.registerFont(TTFont(alias, _find(fname)))

reg("Serif", "DejaVuSerif.ttf"); reg("Serif-B", "DejaVuSerif-Bold.ttf")
reg("Sans", "DejaVuSans.ttf"); reg("Sans-B", "DejaVuSans-Bold.ttf")
reg("Mono", "DejaVuSansMono.ttf")
try:
    reg("Lib", "LiberationSans-Regular.ttf"); reg("Lib-B", "LiberationSans-Bold.ttf")
except FileNotFoundError:
    reg("Lib", "DejaVuSans.ttf"); reg("Lib-B", "DejaVuSans-Bold.ttf")
from reportlab.lib.fonts import addMapping
for fam, n, b in (("Serif", "Serif", "Serif-B"), ("Sans", "Sans", "Sans-B"), ("Lib", "Lib", "Lib-B")):
    addMapping(fam, 0, 0, n); addMapping(fam, 1, 0, b); addMapping(fam, 0, 1, n); addMapping(fam, 1, 1, b)

def styles(font="Serif", size=10.5):
    return dict(
        p=ParagraphStyle("p", fontName=font, fontSize=size, leading=size * 1.35, alignment=TA_JUSTIFY, spaceAfter=4),
        l=ParagraphStyle("l", fontName=font, fontSize=size, leading=size * 1.35, alignment=TA_LEFT),
        r=ParagraphStyle("r", fontName=font, fontSize=size, leading=size * 1.35, alignment=TA_RIGHT),
        c=ParagraphStyle("c", fontName=font, fontSize=size, leading=size * 1.35, alignment=TA_CENTER),
        h=ParagraphStyle("h", fontName=font + "-B" if font != "Lib" else "Lib-B", fontSize=size + 5,
                         leading=size * 2, alignment=TA_CENTER, spaceBefore=8, spaceAfter=8),
        b=ParagraphStyle("b", fontName=font + "-B" if font != "Lib" else "Lib-B", fontSize=size,
                         leading=size * 1.35, alignment=TA_LEFT, spaceBefore=6),
        small=ParagraphStyle("s", fontName=font, fontSize=size - 2.5, leading=(size - 2.5) * 1.3),
        ind=ParagraphStyle("i", fontName=font, fontSize=size, leading=size * 1.35, leftIndent=14,
                           firstLineIndent=-14, alignment=TA_JUSTIFY),
    )

# ---------------------------------------------------------------- słowniki
POWOD = {
    1: "Decyzja o odrzuceniu oferty",
    2: "Ogłoszenie wyboru oferty",
    3: "Decyzja o wykluczeniu wykonawcy",
    4: "Publikacja specyfikacji warunków zamówienia (SWZ)",
    5: "Modyfikacja treści SWZ",
    6: "Odpowiedzi i wyjaśnienia do SWZ",
    7: "Zaniechanie odrzucenia oferty",
    8: "Zaniechanie wykluczenia wykonawcy",
    9: "Decyzja o unieważnieniu postępowania",
    10: "Zaniechanie unieważnienia postępowania",
    11: "Opis przedmiotu zamówienia (OPZ)",
}
MIES = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia",
        "września", "października", "listopada", "grudnia"]
ROM = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]

def d_words(iso):  # 2026-05-05 -> 5 maja 2026
    y, m, d = iso.split("-"); return f"{int(d)} {MIES[int(m)-1]} {y}"
def d_dots(iso):
    y, m, d = iso.split("-"); return f"{d}.{m}.{y}"
def d_slash(iso):
    y, m, d = iso.split("-"); return f"{d}/{m}/{y}"
def d_roman(iso):
    y, m, d = iso.split("-"); return f"{d}.{ROM[int(m)-1]}.{y}"

def iban(rng):
    return "".join(str(rng.randint(0, 9)) for _ in range(26))
def iban_spaced(n, pl=True):
    s = n[:2] + " " + " ".join(n[2 + i:6 + i] for i in range(0, 24, 4))
    return ("PL" + s) if pl else s

def money(v):  # 15000.5 -> 15 000,50
    s = f"{v:,.2f}".replace(",", " ").replace(".", ",")
    return s

# ---------------------------------------------------------------- canvas z numeracją "Strona X z Y"
def make_canvas(footer_fmt="Strona {p} z {n}", header=None, watermark=None, font="Serif"):
    class NumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *a, **k):
            super().__init__(*a, **k); self._saved = []
        def showPage(self):
            self._saved.append(dict(self.__dict__)); self._startPage()
        def save(self):
            n = len(self._saved)
            for st in self._saved:
                self.__dict__.update(st); self._decor(n); super().showPage()
            super().save()
        def _decor(self, n):
            w, h = A4
            if watermark:
                self.saveState(); self.setFont("Sans-B", 70); self.setFillColor(colors.Color(0.85, 0.85, 0.85))
                self.translate(w / 2, h / 2); self.rotate(40); self.drawCentredString(0, 0, watermark)
                self.restoreState()
            self.setFont(font, 8.5)
            if footer_fmt:
                self.drawCentredString(w / 2, 12 * mm, footer_fmt.format(p=self._pageNumber, n=n))
            if header and self._pageNumber > 1:
                self.drawRightString(w - 20 * mm, h - 12 * mm, header)
    return NumberedCanvas

def build(path, story, title, **canvas_kw):
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm,
                            topMargin=20 * mm, bottomMargin=22 * mm, title=title,
                            author="generator testów", producer="TestCaseGen (reportlab)")
    doc.build(story, canvasmaker=make_canvas(**canvas_kw))

# ---------------------------------------------------------------- tekst wypełniający (uzasadnienie)
FILLER = [
    "Odwołujący posiada interes w uzyskaniu zamówienia, ponieważ złożył ofertę, która w świetle kryteriów "
    "oceny ofert określonych w SWZ mogłaby zostać uznana za najkorzystniejszą. Wskutek naruszenia przez "
    "Zamawiającego przepisów ustawy Odwołujący może ponieść szkodę polegającą na utracie możliwości "
    "uzyskania zamówienia i osiągnięcia zakładanego zysku.",
    "Termin na wniesienie odwołania został zachowany. Odwołanie wnoszone jest w terminie określonym w "
    "art. 515 Pzp, liczonym od dnia, w którym Odwołujący powziął wiadomość o okolicznościach stanowiących "
    "podstawę jego wniesienia. Kopia odwołania została przekazana Zamawiającemu przed upływem terminu.",
    "Zgodnie z utrwaloną linią orzeczniczą Krajowej Izby Odwoławczej, obowiązkiem zamawiającego jest "
    "dokonanie czynności w postępowaniu w sposób przejrzysty, umożliwiający wykonawcom weryfikację ich "
    "prawidłowości. Lakoniczne uzasadnienie czynności nie spełnia tego wymogu i samo w sobie stanowi "
    "naruszenie zasady przejrzystości wyrażonej w art. 16 pkt 2 Pzp.",
    "Wymagania stawiane wykonawcom powinny być związane z przedmiotem zamówienia i proporcjonalne do "
    "niego. Zamawiający nie wykazał, aby przyjęte przez niego rozwiązania były niezbędne do zaspokojenia "
    "jego uzasadnionych potrzeb, a jednocześnie w istotny sposób ograniczają one krąg wykonawców zdolnych "
    "do realizacji zamówienia.",
    "Na marginesie Odwołujący wskazuje, że w toku postępowania prowadził z Zamawiającym korespondencję, "
    "w której sygnalizował opisane wątpliwości. Zamawiający nie odniósł się do nich merytorycznie, "
    "ograniczając się do odesłania wykonawców do treści dokumentów zamówienia.",
    "Mając na uwadze powyższe, zarzuty odwołania należy uznać za w pełni zasadne, a naruszenia, których "
    "dopuścił się Zamawiający, mają lub mogą mieć istotny wpływ na wynik postępowania o udzielenie "
    "zamówienia publicznego.",
]

# ================================================================ JSON
def entity_ids_text(e, sep=", ", colon=": "):
    parts = []
    for k, lab in (("krs", "KRS"), ("nip", "NIP"), ("regon", "REGON")):
        raw = e.get(k + "_txt", e.get(k))
        if raw:
            parts.append(f"{lab}{colon}{raw}")
    return sep.join(parts)

def json_odwolanie(c):
    o = c["odw"]
    lead = o["odwolujacy"][0]
    pel = o.get("pelnomocnicy") or []
    przez = 1 if pel else 0
    zam = o["zamawiajacy"]
    return {
        "OdwolanieKIO": {
            "data": o.get("data"),
            "czynnosc_dzien": o["czynnosc_dzien"],
            "czynnosc_powod_id": o["powod"],
            "czynnosc_opis": POWOD[o["powod"]],
            "miejscowosc": o.get("miejscowosc"),
        },
        "Odwolujacy": [{
            "krs": lead.get("krs"), "nazwa": lead["nazwa"], "nip": lead["nip"], "regon": lead["regon"],
            "przez-pelnomocnika": przez,
            "pelnomocnik": {
                "imie_nazwisko": pel[0]["imie_nazwisko"] if pel else None,
                "nazwa": o["kancelaria"]["nazwa"] if pel else None,
                "mail": o["kancelaria"]["mail"] if pel else None,
            },
        }],
        "Zamawiajacy": [{
            "krs": z.get("krs"), "nazwa": z["nazwa"], "nip": z["nip"], "regon": z["regon"],
            "prowadzacy_postepowanie": (None if len(zam) == 1 else (1 if z.get("lider") else 0)),
        } for z in zam],
        "ZamowieniePubliczne": {
            "numer_bzp": o.get("bzp"), "numer_postepowania": o["numer"],
            "numer_ted": o.get("ted"), "tytul": o["tytul"],
        },
    }

def json_pelnomocnictwo(c):
    o = c["odw"]
    return {
        "mocodawca": [{
            "data": {
                "imie_nazwisko": e.get("imie_nazwisko"),
                "krs": e.get("krs"), "nazwa": e["nazwa"], "nip": e["nip"],
                "typ": "osoba_fizyczna" if e.get("imie_nazwisko") else "osoba_prawna",
            },
            "podpisujacy": [{"imie_nazwisko": n} for n, _ in e["podpis"]],
        } for e in o["odwolujacy"]],
        "pelnomocnicy": [{"imie_nazwisko": p["imie_nazwisko"], "pesel": p.get("pesel")}
                         for p in o["pelnomocnicy"]],
    }

def json_przelew(c):
    t = c["przelew"]
    return {"przelew_bankowy": {
        "data_operacji": t["data_operacji"], "kwota": float(t["kwota"]),
        "na_rachunek": t["na"], "numer_transakcji": t["nr"], "tytul": t["tytul"], "z_rachunku": t["z"],
    }}

# ================================================================ render: odwołanie
def p_entity_block(S, e, with_mail=True):
    out = [Paragraph(f"<b>{e['nazwa']}</b>", S["l"]), Paragraph(e["adres"], S["l"])]
    if e.get("ceidg"):
        out.append(Paragraph("przedsiębiorca wpisany do CEIDG", S["l"]))
    out.append(Paragraph(e.get("ids_line") or entity_ids_text(e), S["l"]))
    if with_mail and e.get("mail"):
        out.append(Paragraph(e["mail"], S["l"]))
    return out

def pel_label(p):
    return f"{p['tyt']} {p['imie_nazwisko']}".strip()

def render_odwolanie(c, path):
    o, v = c["odw"], c.get("v", {})
    S = styles(v.get("font", "Serif"))
    st = []
    if v.get("header_date"):
        st += [Paragraph(v["header_date"], S["r"]), Spacer(1, 8)]
    adr = v.get("adresat", ["Prezes Krajowej Izby Odwoławczej", "ul. Postępu 17A", "02-676 Warszawa"])
    st += [Table([[None, Paragraph("<br/>".join(adr), S["l"])]], colWidths=[85 * mm, 80 * mm]), Spacer(1, 10)]

    def odw_part():
        r = []
        ods = o["odwolujacy"]
        if len(ods) == 1:
            r.append(Paragraph(v.get("lab_odw", "<b>Odwołujący:</b>"), S["l"]))
            r += p_entity_block(S, ods[0], with_mail=False)
        else:
            r.append(Paragraph("<b>Odwołujący</b> – wykonawcy wspólnie ubiegający się o udzielenie zamówienia:", S["l"]))
            for i, e in enumerate(ods, 1):
                r.append(Paragraph(f"{i}) {'Pełnomocnik (Lider) Konsorcjum' if i == 1 else 'Członek Konsorcjum'}:", S["l"]))
                r += p_entity_block(S, e, with_mail=False)
        pel = o.get("pelnomocnicy")
        if pel:
            r.append(Paragraph("reprezentowani przez: " if len(ods) > 1 else "reprezentowany przez: ", S["l"]))
            r[-1] = Paragraph(("reprezentowani" if len(ods) > 1 else "reprezentowany") + " przez: "
                              + ", ".join(pel_label(p) for p in pel), S["l"])
            k = o["kancelaria"]
            r.append(Paragraph(f"adres do korespondencji: {k['nazwa']}, {k['adres']}", S["l"]))
            r.append(Paragraph(f"e-mail: {k['mail']}", S["l"]))
        else:
            r.append(Paragraph(v.get("bez_pel", ""), S["l"]))
        return r

    def zam_part():
        r = []
        zs = o["zamawiajacy"]
        if len(zs) == 1:
            r.append(Paragraph("<b>Zamawiający:</b>", S["l"])); r += p_entity_block(S, zs[0])
        else:
            r.append(Paragraph("<b>Zamawiający</b> (zamówienie wspólne, art. 38 Pzp):", S["l"]))
            for i, z in enumerate(zs, 1):
                lab = ("Zamawiający prowadzący postępowanie w imieniu i na rzecz pozostałych zamawiających"
                       if z.get("lider") else "Zamawiający")
                r.append(Paragraph(f"{i}) {lab}:", S["l"])); r += p_entity_block(S, z)
        return r

    if v.get("table_header"):
        def ent_rows(e):
            rows = [["Nazwa", e["nazwa"]], ["Adres", e["adres"]]]
            for k, lab in (("krs", "KRS"), ("nip", "NIP"), ("regon", "REGON")):
                if e.get(k): rows.append([lab, e.get(k + "_txt", e[k])])
            if e.get("mail"): rows.append(["E-mail", e["mail"]])
            return rows
        cell = lambda t: Paragraph(t, S["small"])
        data = [[cell("<b>STRONA</b>"), cell("<b>POLE</b>"), cell("<b>DANE</b>")]]
        for i, (role, e) in enumerate([("Odwołujący", o["odwolujacy"][0])] +
                                      [("Zamawiający", z) for z in o["zamawiajacy"]]):
            for j, (a, b) in enumerate(ent_rows(e)):
                data.append([cell(role if j == 0 else ""), cell(a), cell(b)])
        k = o["kancelaria"]
        data.append([cell("Pełnomocnik Odwołującego"), cell("Osoba"), cell(", ".join(pel_label(p) for p in o["pelnomocnicy"]))])
        data.append([cell(""), cell("Kancelaria"), cell(f"{k['nazwa']}, {k['adres']}")])
        data.append([cell(""), cell("E-mail"), cell(k["mail"])])
        t = Table(data, colWidths=[38 * mm, 22 * mm, 106 * mm])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.Color(.9, .9, .9)),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        st += [t, Spacer(1, 10)]
    else:
        parts = [zam_part(), odw_part()] if v.get("zam_first") else [odw_part(), zam_part()]
        for p_ in parts:
            st += p_ + [Spacer(1, 8)]

    # dotyczy
    dot = v.get("dotyczy")
    if dot is None:
        ogl = []
        if o.get("bzp_txt"): ogl.append(f"ogłoszenie o zamówieniu w Biuletynie Zamówień Publicznych nr {o['bzp_txt']}")
        if o.get("ted_txt"): ogl.append(f"ogłoszenie w Dzienniku Urzędowym Unii Europejskiej {o['ted_txt']}")
        dot = (f"<b>dotyczy:</b> postępowania o udzielenie zamówienia publicznego pn. „{o['tytul']}”, "
               f"znak sprawy: {o['numer']}" + ("; " + "; ".join(ogl) if ogl else ""))
    if isinstance(dot, list):  # ręczne łamanie (np. przez stronę)
        for chunk in dot:
            st.append(PageBreak() if chunk == "<PAGEBREAK>" else Paragraph(chunk, S["l"]))
    else:
        st.append(Paragraph(dot, S["p"]))
    st.append(Spacer(1, 6))
    st.append(Paragraph(v.get("title", "ODWOŁANIE"), S["h"]))
    st.append(Paragraph(v["czynnosc_txt"], S["p"]))
    for extra in v.get("extra_before_filler", []):
        st.append(Paragraph(extra, S["p"]))
    st.append(Paragraph("W związku z powyższym wnoszę o uwzględnienie odwołania w całości oraz nakazanie "
                        "Zamawiającemu unieważnienia zaskarżonej czynności i powtórzenia czynności badania "
                        "i oceny ofert, a także o zasądzenie kosztów postępowania odwoławczego.", S["p"]))
    st.append(Paragraph("<b>UZASADNIENIE</b>", S["c"]))
    for i in range(v.get("filler", 2)):
        st.append(Paragraph(FILLER[i % len(FILLER)], S["p"]))
        for dd in v.get("distractors", {}).get(i, []):
            st.append(Paragraph(dd, S["p"]))
    st.append(Spacer(1, 10))
    st.append(Paragraph("Załączniki: 1) pełnomocnictwo; 2) dowód uiszczenia opłaty skarbowej; 3) dowód "
                        "uiszczenia wpisu; 4) dowód przekazania kopii odwołania Zamawiającemu.", S["small"]))
    st.append(Spacer(1, 22))
    sig = v.get("signers") or [f"{p['imie_nazwisko']}, {p['tyt_po']}" for p in o["pelnomocnicy"]]
    st.append(KeepTogether([Paragraph("..............................<br/>" + s, S["r"]) for s in sig]))
    if v.get("sig_note"):
        st.append(Spacer(1, 6)); st.append(Paragraph(v["sig_note"], S["small"]))
    build(path, st, "Odwołanie", footer_fmt=v.get("footer", "Strona {p} z {n}"),
          header=v.get("running_header"), watermark=v.get("watermark"), font=v.get("font", "Serif"))

# ================================================================ render: pełnomocnictwo
def render_pelnomocnictwo(c, path):
    o, v = c["odw"], c.get("pv", {})
    S = styles(v.get("font", "Serif"))
    st = []
    if v.get("header_date"):
        st.append(Paragraph(v["header_date"], S["r"]))
    st.append(Paragraph(v.get("title", "PEŁNOMOCNICTWO"), S["h"]))
    ods = o["odwolujacy"]
    pel = o["pelnomocnicy"]
    def pel_txt(p):
        s = f"{pel_label(p)}"
        if p.get("pesel"): s += f", PESEL {p['pesel']}"
        if p.get("wpis"): s += f" (nr wpisu: {p['wpis']})"
        return s

    if v.get("table"):
        cell = lambda t: Paragraph(t, S["small"])
        rows = [[cell("<b>Dane Mocodawcy</b>"), ""]]
        for i, e in enumerate(ods, 1):
            pre = f"Mocodawca {i}: " if len(ods) > 1 else ""
            rows += [[cell(pre + "Firma / nazwa"), cell(e["nazwa"])], [cell("Siedziba / adres"), cell(e["adres"])]]
            if e.get("imie_nazwisko"): rows.append([cell("Imię i nazwisko"), cell(e["imie_nazwisko"])])
            for k, lab in (("krs", "Numer KRS"), ("nip", "NIP"), ("regon", "REGON")):
                if e.get(k): rows.append([cell(lab), cell(e.get(k + "_txt", e[k]))])
        rows.append([cell("<b>Pełnomocnicy</b>"), ""])
        for i, p in enumerate(pel, 1):
            rows.append([cell(f"Pełnomocnik {i}"), cell(pel_txt(p))])
        rows.append([cell("<b>Postępowanie</b>"), ""])
        rows.append([cell("Nazwa zamówienia"), cell(o["tytul"])])
        rows.append([cell("Znak sprawy"), cell(o["numer"])])
        t = Table(rows, colWidths=[50 * mm, 116 * mm])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]
                              + [("SPAN", (0, i), (1, i)) for i, r in enumerate(rows) if r[1] == ""]
                              + [("BACKGROUND", (0, i), (1, i), colors.Color(.92, .92, .92)) for i, r in enumerate(rows) if r[1] == ""]))
        st += [t, Spacer(1, 8),
               Paragraph("Mocodawca udziela wskazanym wyżej pełnomocnikom pełnomocnictwa do reprezentowania go "
                         "w postępowaniu odwoławczym przed Krajową Izbą Odwoławczą, w tym do wniesienia odwołania, "
                         "udziału w posiedzeniach i rozprawach, zawarcia ugody, cofnięcia odwołania oraz wniesienia "
                         "skargi do sądu zamówień publicznych. Każdy z pełnomocników może działać samodzielnie.", S["p"])]
    else:
        if len(ods) == 1:
            e = ods[0]
            if e.get("imie_nazwisko"):
                intro = (f"Ja, {e['imie_nazwisko']}, prowadzący działalność gospodarczą pod firmą {e['nazwa']}, "
                         f"{e['adres']}, {entity_ids_text(e, colon=' ')}, ")
            else:
                intro = f"{e['nazwa']} z siedzibą: {e['adres']}, {entity_ids_text(e, colon=' ')}, reprezentowana zgodnie z zasadami reprezentacji, "
        else:
            intro = "Wykonawcy wspólnie ubiegający się o udzielenie zamówienia: " + "; ".join(
                f"{i}) {e['nazwa']}, {e['adres']}, {entity_ids_text(e, colon=' ')}" for i, e in enumerate(ods, 1)) + " – "
        if v.get("pel_as_list"):
            st.append(Paragraph(intro + "niniejszym udziela pełnomocnictwa następującym osobom:", S["p"]))
            for i, p in enumerate(pel, 1):
                if v.get("pagebreak_in_list") and i == 2:
                    st.append(PageBreak())
                st.append(Paragraph(f"{i}. {pel_txt(p)}", S["ind"]))
        else:
            st.append(Paragraph(intro + "udziela pełnomocnictwa: " + "; ".join(pel_txt(p) for p in pel) + ".", S["p"]))
        st.append(Paragraph(f"do reprezentowania Mocodawcy w postępowaniu o udzielenie zamówienia publicznego "
                            f"pn. „{o['tytul']}”, znak sprawy {o['numer']}, w szczególności do wniesienia "
                            f"odwołania do Prezesa Krajowej Izby Odwoławczej, udziału w posiedzeniach i "
                            f"rozprawach, składania pism procesowych oraz wniesienia skargi do sądu zamówień "
                            f"publicznych. Pełnomocnicy działają samodzielnie.", S["p"]))
    st.append(Spacer(1, 22))
    blocks = []
    for e in ods:
        b = []
        if len(ods) > 1:
            b.append(Paragraph(f"Za {e['nazwa']}:", S["l"]))
        for n, role in e["podpis"]:
            b.append(Paragraph("....................................<br/>" + n + (f"<br/>{role}" if role else ""), S["l"]))
            b.append(Spacer(1, 6))
        blocks.append(KeepTogether(b))
    st += blocks
    st.append(Spacer(1, 6))
    st.append(Paragraph("Przyjmuję pełnomocnictwo:", S["l"]))
    for p in pel:
        st.append(Paragraph("....................................<br/>" + pel_label(p), S["l"]))
    build(path, st, "Pełnomocnictwo", footer_fmt=v.get("footer"), watermark=c.get("v", {}).get("watermark"),
          font=v.get("font", "Serif"))

# ================================================================ render: potwierdzenie przelewu
def render_przelew(c, path):
    t, v = c["przelew"], c.get("tv", {})
    S = styles(v.get("font", "Sans"), 9.5)
    st = [Paragraph(v.get("title", "Potwierdzenie przelewu"), S["h"]),
          Paragraph(v.get("bank", "Bank Testowy S.A."), S["c"]), Spacer(1, 10)]
    rows = v["rows"]
    style = v.get("style", "grid")
    cell = lambda x: Paragraph(x, S["l"])
    if style == "grid":
        tab = Table([[cell(f"<b>{a}</b>"), cell(b)] for a, b in rows], colWidths=[52 * mm, 114 * mm])
        tab.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("BACKGROUND", (0, 0), (0, -1), colors.Color(.94, .94, .94))]))
        st.append(tab)
    elif style == "stacked":  # etykieta nad wartością, dwie kolumny
        pairs = [[cell(f"<font size=7.5 color='#555555'>{a.upper()}</font><br/>{b}") for a, b in rows[i:i + 2]]
                 for i in range(0, len(rows), 2)]
        for r in pairs:
            if len(r) == 1: r.append("")
        tab = Table(pairs, colWidths=[83 * mm, 83 * mm])
        tab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                                 ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.lightgrey)]))
        st.append(tab)
    elif style == "history":  # wyciąg z kilkoma operacjami
        st.append(Paragraph(v["hist_head"], S["l"])); st.append(Spacer(1, 6))
        head = ["Data operacji", "Data księg.", "Opis operacji", "Kwota", "Saldo"]
        data = [[cell(f"<b>{h}</b>") for h in head]] + [[cell(x) for x in r] for r in v["hist_rows"]]
        tab = Table(data, colWidths=[25 * mm, 25 * mm, 72 * mm, 22 * mm, 22 * mm])
        tab.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        st.append(tab)
        if rows:
            st.append(Spacer(1, 10)); st.append(Paragraph("<b>Szczegóły zaznaczonej operacji</b>", S["l"]))
            tab2 = Table([[cell(a), cell(b)] for a, b in rows], colWidths=[52 * mm, 114 * mm])
            tab2.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey)]))
            st.append(tab2)
    st.append(Spacer(1, 14))
    st.append(Paragraph(v.get("foot", "Dokument wygenerowany elektronicznie, nie wymaga podpisu ani stempla."), S["small"]))
    for extra in v.get("extra_pages", []):
        st.append(PageBreak()); st.append(Paragraph(extra, S["p"]))
    build(path, st, "Potwierdzenie przelewu", footer_fmt=v.get("footer"), font=v.get("font", "Sans"))

# ================================================================ przypadki
R = random.Random(20261121)

def P(imie_nazwisko, tyt="r. pr.", tyt_po=None, pesel=None, wpis=None):
    return dict(imie_nazwisko=imie_nazwisko, tyt=tyt, tyt_po=tyt_po or tyt, pesel=pesel, wpis=wpis)

def fee_title(pel, numer, ref):
    names = [p["imie_nazwisko"] for p in pel]
    s = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " i " + names[-1]
    return f"opłata skarbowa od pełnomocnictwa dla {s} w postępowaniu przed KIO w przetargu {numer} {ref}"

def std_rows(t, labels=None, extra=None, fmt_date=lambda x: x, fmt_acc=lambda x: iban_spaced(x), kw=None):
    L = dict(z="Rachunek nadawcy", n="Nadawca", na="Rachunek odbiorcy", o="Odbiorca", k="Kwota",
             d="Data operacji", ty="Tytuł", nr="Numer transakcji")
    L.update(labels or {})
    rows = [(L["n"], t["nadawca"]), (L["z"], fmt_acc(t["z"])), (L["o"], t["odbiorca"]),
            (L["na"], fmt_acc(t["na"])), (L["k"], kw or f"{money(t['kwota'])} PLN"),
            (L["d"], fmt_date(t["data_operacji"])), (L["ty"], t["tytul"]), (L["nr"], t["nr"])]
    return rows + (extra or [])

CASES = []

# ---------------------------------------------------------------- 01
def case01():
    odw = dict(nazwa="Kormoran Systemy Pomiarowe sp. z o.o.", adres="ul. Morska 112, 81-225 Gdynia",
               krs="0000412345", nip="9995412783", nip_txt="999-541-27-83", regon="99928467000017",
               podpis=[("Tomasz Wilczyński", "Prezes Zarządu")])
    zam = dict(nazwa="Port Morski Gdynia Usługi Techniczne S.A.", adres="ul. Rotterdamska 9, 81-337 Gdynia",
               krs="0000187654", nip="9993307218", nip_txt="PL 999 330 72 18", regon="999102384",
               mail="zamowienia@pmgut.example")
    pel = [P("Marta Żurawska", "r. pr.", wpis="GD-3127")]
    o = dict(data="2026-05-05", miejscowosc="Gdynia", czynnosc_dzien="2026-04-28", powod=3,
             odwolujacy=[odw], zamawiajacy=[zam], pelnomocnicy=pel,
             kancelaria=dict(nazwa="Żurawska i Wspólnicy Kancelaria Radców Prawnych sp.p.",
                             adres="ul. Świętojańska 40/2, 81-372 Gdynia", mail="kancelaria@zurawska.example"),
             bzp="2026/BZP00512377", bzp_txt="2026/BZP 00512377", ted=None,
             numer="PMG/ZP/TT/04/2026",
             tytul="Dostawa i montaż systemu monitoringu przemieszczeń nabrzeży wraz z serwisem gwarancyjnym")
    ref = "TRX/2026/04/30/0048812"
    t = dict(data_operacji="2026-04-30", kwota=17, z=iban(R), na=iban(R), nr=ref,
             nadawca="KORMORAN SYSTEMY POMIAROWE SP Z O O UL MORSKA 112 81-225 GDYNIA",
             odbiorca="URZAD MIASTA GDYNI WYDZIAL BUDZETU",
             tytul="Oplata skarbowa za pelnomocnictwo r.pr. Marta Zurawska - KIO PMG/ZP/TT/04/2026")
    return dict(
        id="test_01_formaty_dat_i_identyfikatorow", odw=o, przelew=t,
        cel=["NIP z myślnikami (999-541-27-83) i z prefiksem PL ze spacjami (PL 999 330 72 18) – oczekiwane same cyfry",
             "KRS z zerami wiodącymi (0000412345) – musi zostać stringiem, bez obcinania zer",
             "14-cyfrowy REGON (jednostka lokalna)",
             "daty słownie ('dnia 5 maja 2026 r.'), z kropkami, z ukośnikami (30/04/2026), rzymski miesiąc (05.V.2026)",
             "dystraktory dat w treści (termin składania ofert, data ogłoszenia)",
             "przelew: kwota ze znakiem minus (-17,00 PLN), rachunki bez 'PL' w formacie NRB, tytuł bez polskich znaków (bank je usunął), numer transakcji z ukośnikami"],
        v=dict(header_date="Gdynia, dnia 5 maja 2026 r.", filler=3,
               czynnosc_txt="Działając w imieniu Odwołującego, na podstawie art. 513 pkt 1 Pzp wnoszę odwołanie wobec "
                            "czynności Zamawiającego polegającej na <b>wykluczeniu Odwołującego z postępowania</b>, o "
                            "której Zamawiający poinformował wykonawców pismem przesłanym w dniu 28.04.2026 r., "
                            "z naruszeniem art. 108 ust. 1 pkt 4 oraz art. 109 ust. 1 pkt 7 Pzp.",
               distractors={0: ["Termin składania ofert upłynął w dniu 14/04/2026, a otwarcie ofert nastąpiło "
                                "tego samego dnia o godz. 12:30. Ogłoszenie o zamówieniu opublikowano 2026-03-02."]}),
        pv=dict(header_date="Gdynia, 05.V.2026 r."),
        tv=dict(style="grid", title="Szczegóły transakcji", bank="Bałtycki Bank Komercyjny S.A.",
                rows=std_rows(t, labels=dict(z="Z rachunku", na="Na rachunek", d="Data waluty", k="Kwota"),
                              fmt_date=d_slash, fmt_acc=lambda x: iban_spaced(x, pl=False), kw="-17,00 PLN")),
    )
CASES.append(case01())

# ---------------------------------------------------------------- 02
def case02():
    odw = dict(nazwa="Brzask Usługi Komunalne sp. z o.o.", adres="ul. Ozimska 77, 45-368 Opole",
               krs="9994471203", nip="9997120563", regon="999358140",
               podpis=[("Ewa Kalinowska", "Prezes Zarządu"), ("Dariusz Mazur", "Członek Zarządu")])
    zam = dict(nazwa="Gmina Miasto Opolec", adres="Rynek 1, 45-015 Opolec", krs=None,
               nip="9995530214", regon="999021477", mail="zp@opolec.example")
    o = dict(data="2026-06-12", miejscowosc="Opole", czynnosc_dzien="2026-06-05", powod=2,
             odwolujacy=[odw], zamawiajacy=[zam], pelnomocnicy=[], kancelaria=None,
             bzp="2026/BZP00733102", bzp_txt="2026/BZP 00733102", ted=None, numer="GMO.271.33.2026",
             tytul="Odbiór i zagospodarowanie odpadów komunalnych z nieruchomości zamieszkałych na terenie Gminy Miasto Opolec")
    return dict(
        id="test_02_bez_pelnomocnika", odw=o, only=["odwolanie"],
        cel=["Odwołujący działa samodzielnie przez zarząd – brak pełnomocnika ('przez-pelnomocnika': 0, pola pełnomocnika = null)",
             "w zestawie jest TYLKO odwolanie.pdf – brak pełnomocnictwa i przelewu; parser nie powinien się wywrócić",
             "Zamawiający – gmina bez KRS"],
        zalozenia=["Konwencja dla braku pełnomocnika nie występuje w przykładach: przyjęto 'przez-pelnomocnika': 0 "
                   "i pelnomocnik = {imie_nazwisko: null, nazwa: null, mail: null}."],
        v=dict(header_date="Opole, 12.06.2026 r.",
               bez_pel="działający przez członków zarządu uprawnionych do łącznej reprezentacji, bez ustanawiania pełnomocnika; e-mail: zarzad@brzask.example",
               czynnosc_txt="Działając w imieniu własnym Odwołującego, wnoszę odwołanie od czynności <b>wyboru oferty "
                            "najkorzystniejszej</b>, o której Zamawiający zawiadomił wykonawców w dniu 5 czerwca 2026 r., "
                            "oraz od zaniechania zbadania, czy wybrana oferta zawiera rażąco niską cenę.",
               signers=["Ewa Kalinowska – Prezes Zarządu", "Dariusz Mazur – Członek Zarządu"]),
    )
CASES.append(case02())

# ---------------------------------------------------------------- 03
def case03():
    odw = dict(nazwa="Medivio Polska sp. z o.o.", adres="al. Jerozolimskie 181B, 02-222 Warszawa",
               krs="9990938271", nip="9993817264", regon="999740612", podpis=[("Paweł Głowacki", "Prokurent samoistny")])
    z1 = dict(nazwa="Szpital Powiatowy w Lesznowoli sp. z o.o.", adres="ul. Szkolna 6, 05-506 Lesznowola",
              krs="9992218406", nip="9991203398", regon="999305118", mail="zp@szpital-lesznowola.example")
    z2 = dict(nazwa="Mazowieckie Centrum Zakupów Medycznych", adres="ul. Kłopotowskiego 5, 03-718 Warszawa",
              krs=None, nip="9998140772", regon="999662013", mail="przetargi@mczm.example", lider=True)
    z3 = dict(nazwa="Centrum Rehabilitacji Wola sp. z o.o.", adres="ul. Górczewska 89, 01-401 Warszawa",
              krs="9997305581", nip="9990662145", regon="999418833", mail="sekretariat@crwola.example")
    pel = [P("Bartosz Kołodziej", "adw.", wpis="WAW/Adw/7781"), P("Iwona Sadowska", "r. pr.", wpis="WA-11872")]
    o = dict(data="2026-09-24", miejscowosc="Warszawa", czynnosc_dzien="2026-09-14", powod=7,
             odwolujacy=[odw], zamawiajacy=[z1, z2, z3], pelnomocnicy=pel,
             kancelaria=dict(nazwa="Kołodziej Sadowska Adwokaci i Radcowie Prawni sp.k.",
                             adres="ul. Hoża 51/14, 00-681 Warszawa", mail="biuro@ks-legal.example"),
             bzp="2026/BZP00654321", bzp_txt="2026/BZP 00654321",
             ted="555012-2026", ted_txt="nr 2026/S 178-555012",
             numer="MCZM-ZP/26/09/K",
             tytul="Dostawa sprzętu do diagnostyki obrazowej wraz z instalacją i szkoleniem personelu")
    ref = "CEN2609157731150"
    t = dict(data_operacji="2026-09-22", kwota=34, z=iban(R), na=iban(R), nr=ref,
             nadawca="Medivio Polska sp. z o.o.", odbiorca="Urząd m.st. Warszawy",
             tytul=fee_title(pel, o["numer"], ref))
    return dict(
        id="test_03_trzech_zamawiajacych_lider_w_srodku", odw=o, przelew=t,
        cel=["3 zamawiających wspólnych; prowadzący postępowanie jest DRUGI na liście → prowadzacy_postepowanie [0, 1, 0]",
             "zamawiający-lider bez KRS",
             "Zamawiający podani PRZED Odwołującym",
             "jednocześnie numer BZP i TED (TED w formacie '2026/S 178-555012' → '555012-2026')",
             "przelew w układzie 'etykieta nad wartością' w dwóch kolumnach"],
        v=dict(header_date="Warszawa, 24 września 2026 r.", zam_first=True, filler=3,
               czynnosc_txt="Wnoszę odwołanie wobec <b>zaniechania odrzucenia oferty</b> wykonawcy RadiaMed Solutions "
                            "S.A., mimo że jej treść jest niezgodna z warunkami zamówienia, o czym Odwołujący dowiedział "
                            "się z informacji o wyniku postępowania przekazanej w dniu 14 września 2026 r."),
        pv=dict(header_date="Warszawa, 21.09.2026", pel_as_list=True),
        tv=dict(style="stacked", title="Potwierdzenie wykonania operacji", bank="Mazowiecki Bank Depozytowy",
                rows=std_rows(t, labels=dict(n="Zleceniodawca", o="Beneficjent", nr="Nr referencyjny"),
                              fmt_date=d_dots)),
    )
CASES.append(case03())

# ---------------------------------------------------------------- 04
def case04():
    odw = dict(nazwa="Gryf Infrastruktura S.A.", adres="ul. Wały Chrobrego 4, 70-502 Szczecin",
               krs="9996601247", nip="9994028835", regon="999213907",
               podpis=[("Magdalena Pietrzak-Ziółkowska", "Prezes Zarządu"), ("Hubert Ćwikliński", "Wiceprezes Zarządu")])
    zam = dict(nazwa="Zachodniopomorski Zarząd Dróg Wojewódzkich", adres="ul. Golisza 10, 71-682 Szczecin",
               krs=None, nip="9992273041", regon="999660518", mail="przetargi@zzdw.example")
    pel = [P("Krzysztof Wróblewski-Ostoja", "adw. dr hab.", tyt_po="adw.", wpis="SZ/Adw/204"),
           P("Agnieszka Nowak-Kowalska", "r. pr. dr", tyt_po="r. pr.", pesel="81020714328", wpis="SZ-1890"),
           P("Józef Ślązak", "apl. r. pr.", tyt_po="apl. r. pr.", pesel="96111803554")]
    o = dict(data="2026-02-27", miejscowosc="Szczecin", czynnosc_dzien="2026-02-19", powod=5,
             odwolujacy=[odw], zamawiajacy=[zam], pelnomocnicy=pel,
             kancelaria=dict(nazwa="Kancelaria Wróblewski-Ostoja i Partnerzy sp.p.",
                             adres="pl. Żołnierza Polskiego 3/7, 70-551 Szczecin", mail="kio@wroblewski-ostoja.example"),
             bzp=None, ted="118204-2026", ted_txt="nr 118204-2026 z dnia 06.02.2026", numer="ZZDW-ZP.3310.4.2026",
             tytul="Przebudowa drogi wojewódzkiej nr 142 na odcinku Chociwel – Dobrzany wraz z budową ścieżki rowerowej")
    ref = "CEN2602201184772"
    t = dict(data_operacji="2026-02-20", kwota=51, z=iban(R), na=iban(R), nr=ref,
             nadawca="Gryf Infrastruktura S.A.", odbiorca="Urząd Miasta Szczecin", tytul=fee_title(pel, o["numer"], ref))
    return dict(
        id="test_04_trzech_pelnomocnikow_tytuly", odw=o, przelew=t,
        cel=["3 pełnomocników (w przykładach max 2), dwóch z numerem PESEL",
             "tytuły przed nazwiskiem: 'adw. dr hab.', 'r. pr. dr', 'apl. r. pr.' – oczekiwane czyste imię i nazwisko",
             "nazwiska dwuczłonowe z łącznikiem i polskimi znakami (Wróblewski-Ostoja, Nowak-Kowalska, Ślązak, Ćwikliński)",
             "pełnomocnicy w pełnomocnictwie jako lista numerowana",
             "kwota 51,00 zł (3 × 17) – wartość spoza zbioru z przykładów",
             "tylko numer TED (bez BZP) z doklejoną datą"],
        v=dict(header_date="Szczecin, 27 lutego 2026 roku",
               czynnosc_txt="Odwołanie wnoszę wobec czynności Zamawiającego polegającej na <b>modyfikacji treści "
                            "Specyfikacji Warunków Zamówienia</b> dokonanej w dniu 19.02.2026 r., w zakresie "
                            "rozdziału VII SWZ (warunki udziału w postępowaniu) oraz § 14 projektowanych "
                            "postanowień umowy.",
               signers=["Krzysztof Wróblewski-Ostoja, adw.", "Agnieszka Nowak-Kowalska, r. pr."]),
        pv=dict(header_date="Szczecin, 20 lutego 2026 r.", pel_as_list=True),
        tv=dict(style="grid", title="POTWIERDZENIE PRZELEWU", bank="Pomorski Bank Regionalny S.A.",
                rows=std_rows(t, fmt_date=d_words, labels=dict(d="Data realizacji"))),
    )
CASES.append(case04())

# ---------------------------------------------------------------- 05
def case05():
    e1 = dict(nazwa="INSTAL-PRO Marek Sowa", imie_nazwisko="Marek Sowa", ceidg=True,
              adres="ul. Kościuszki 15, 34-100 Wadowice", krs=None, nip="9998801422", regon="999170355",
              podpis=[("Marek Sowa", "właściciel")])
    e2 = dict(nazwa="Termobud sp. z o.o.", adres="ul. Zakopiańska 62, 30-418 Kraków",
              krs="9991137806", nip="9992508817", regon="999476120", podpis=[("Renata Łukaszewicz", "Prokurent")])
    e3 = dict(nazwa="Elektra Serwis S.A.", adres="ul. Wrocławska 3, 43-300 Bielsko-Biała",
              krs="9995519006", nip="9996674103", regon="999083356",
              podpis=[("Grzegorz Jasiński", "Prezes Zarządu"), ("Monika Fijałkowska", "Członek Zarządu")])
    zam = dict(nazwa="Gmina Wadowice", adres="pl. Jana Pawła II 23, 34-100 Wadowice", krs=None,
               nip="9993342818", regon="999072201", mail="zamowienia@wadowice.example")
    pel = [P("Szymon Adamczyk", "r. pr.", wpis="KR-5512")]
    o = dict(data="2026-10-09", miejscowosc="Kraków", czynnosc_dzien="2026-10-01", powod=1,
             odwolujacy=[e1, e2, e3], zamawiajacy=[zam], pelnomocnicy=pel,
             kancelaria=dict(nazwa="Kancelaria Radcy Prawnego Szymon Adamczyk", adres="ul. Długa 8/3, 31-147 Kraków",
                             mail="s.adamczyk@radca.example"),
             bzp="2026/BZP00890456", bzp_txt="2026/BZP 00890456", ted=None, numer="ZP.271.58.2026",
             tytul="Termomodernizacja budynków użyteczności publicznej wraz z montażem instalacji fotowoltaicznych")
    ref = "CEN2610061044218"
    t = dict(data_operacji="2026-10-06", kwota=17, z=iban(R), na=iban(R), nr=ref,
             nadawca="INSTAL-PRO Marek Sowa", odbiorca="Gmina Miejska Kraków", tytul=fee_title(pel, o["numer"], ref))
    return dict(
        id="test_05_konsorcjum_trzech_lider_osoba_fizyczna", odw=o, przelew=t,
        cel=["konsorcjum 3 wykonawców (w przykładach max 2)",
             "lider konsorcjum to osoba fizyczna (CEIDG, bez KRS) → Odwolujacy[0].krs = null",
             "pełnomocnictwo: 3 mocodawców, mieszane typy (osoba_fizyczna + 2× osoba_prawna), różna liczba podpisujących (1/1/2)",
             "podpisujący w roli prokurenta i 'właściciela'"],
        zalozenia=["Zgodnie z przykładem 41: w odwolanie.json w 'Odwolujacy' wpisywany jest tylko lider konsorcjum."],
        v=dict(header_date="Kraków, 9 października 2026 r.",
               czynnosc_txt="Wnoszę odwołanie od czynności <b>odrzucenia oferty Odwołującego</b> na podstawie "
                            "art. 226 ust. 1 pkt 5 Pzp, o której Zamawiający poinformował w dniu 1 października 2026 r."),
        pv=dict(header_date="Wadowice / Kraków / Bielsko-Biała, 5 października 2026 r."),
        tv=dict(style="grid", bank="Bank Spółdzielczy Ziemi Wadowickiej",
                rows=std_rows(t, labels=dict(n="Zleceniodawca"))),
    )
CASES.append(case05())

# ---------------------------------------------------------------- 06
def case06():
    odw = dict(nazwa="Wielkopolskie Studio Projektowe ARCADA sp. z o.o.", adres="ul. Garbary 48, 61-758 Poznań",
               krs="9993381150", nip="9997713046", regon="999551820", podpis=[("Oskar Banaszak", "Prezes Zarządu")])
    zam = dict(nazwa="Uniwersytet Przyrodniczy w Kórnikowie", adres="ul. Wojska Polskiego 28, 60-637 Kórnikowo",
               krs=None, nip="9990120884", regon="999137505", mail="dzp@upk.example")
    pel = [P("Weronika Szulc", "adw.", wpis="PO/Adw/1520"), P("Tadeusz Grabowski", "r. pr.", wpis="PO-4419")]
    o = dict(data="2026-10-02", miejscowosc="Poznań", czynnosc_dzien="2026-09-25", powod=11,
             odwolujacy=[odw], zamawiajacy=[zam], pelnomocnicy=pel,
             kancelaria=dict(nazwa="Szulc Grabowski Kancelaria Prawna s.c.", adres="ul. Półwiejska 12/1, 61-885 Poznań",
                             mail="kontakt@szulc-grabowski.example"),
             bzp="2026/BZP00811947", bzp_txt="2026/BZP 00811947", ted=None, numer="DZP-PN-062/2026",
             tytul="Opracowanie dokumentacji projektowej przebudowy budynku Collegium Zoologicum")
    ref = "PL260926/0091/AX7"
    t = dict(data_operacji="2026-09-26", kwota=34, z=iban(R), na=iban(R), nr=ref,
             nadawca="ARCADA sp. z o.o.", odbiorca="Miasto Poznań – Wydział Finansowy", tytul=fee_title(pel, o["numer"], ref))
    return dict(
        id="test_06_uklad_tabelaryczny", odw=o, przelew=t,
        cel=["dane stron odwołania w tabeli (kolumny: strona / pole / dane) zamiast bloków tekstu",
             "pełnomocnictwo w formie formularza-tabeli",
             "przelew z innymi etykietami: 'Nadawca', 'Z rachunku', 'Na rachunek', 'Tytułem', 'Identyfikator transakcji'",
             "numer transakcji o innym formacie (ze znakami '/')",
             "daty w formacie ISO w nagłówku"],
        v=dict(header_date="Poznań, 2026-10-02", table_header=True, font="Lib",
               czynnosc_txt="Zaskarżam czynność Zamawiającego polegającą na <b>sporządzeniu opisu przedmiotu zamówienia</b> "
                            "(Załącznik nr 1 do SWZ – OPZ) udostępnionego w dniu 2026-09-25 w sposób utrudniający "
                            "uczciwą konkurencję."),
        pv=dict(header_date="Poznań, 2026-09-26", table=True, font="Lib"),
        tv=dict(style="grid", title="Potwierdzenie transakcji", bank="Wielkopolski Bank Inwestycyjny", font="Lib",
                rows=std_rows(t, labels=dict(n="Nadawca", z="Z rachunku", na="Na rachunek", ty="Tytułem",
                                             nr="Identyfikator transakcji", d="Data wykonania"),
                              fmt_acc=lambda x: "PL" + x)),
    )
CASES.append(case06())

# ---------------------------------------------------------------- 07
def case07():
    odw = dict(nazwa="Sygnet Ochrona Mienia sp. z o.o. sp.k.", adres="ul. Piotrkowska 270, 90-361 Łódź",
               krs="9998412270", nip="9991562209", regon="999287344",
               podpis=[("Kamil Zieliński", "Prezes Zarządu Komplementariusza")])
    zam = dict(nazwa="Łódzkie Centrum Kultury i Sztuki", adres="ul. Tuwima 34, 90-002 Łódź", krs=None,
               nip="9994461130", regon="999822071", mail="administracja@lckis.example")
    pel = [P("Olga Wasilewska", "r. pr.", wpis="ŁD-2306"), P("Filip Kaczmarczyk", "adw.", wpis="ŁD/Adw/899")]
    o = dict(data="2026-02-12", miejscowosc="Łódź", czynnosc_dzien="2026-02-02", powod=8,
             odwolujacy=[odw], zamawiajacy=[zam], pelnomocnicy=pel,
             kancelaria=dict(nazwa="Wasilewska Kaczmarczyk Kancelaria sp. z o.o.", adres="ul. Kilińskiego 81, 90-119 Łódź",
                             mail="sekretariat@wk-kancelaria.example"),
             bzp="2026/BZP00104488", bzp_txt="2026/BZP 00104488", ted=None, numer="LCKiS/ZP/1/2026",
             tytul="Świadczenie usług ochrony osób i mienia w obiektach Łódzkiego Centrum Kultury i Sztuki")
    ref = "CEN2602105530190"
    t = dict(data_operacji="2026-02-10", kwota=34, z=iban(R), na=iban(R), nr=ref,
             nadawca="Sygnet Ochrona Mienia sp. z o.o. sp.k.", odbiorca="Urząd Miasta Łodzi", tytul=fee_title(pel, o["numer"], ref))
    rows = [("Odbiorca", t["odbiorca"]), ("Rachunek odbiorcy", iban_spaced(t["na"])),
            ("Zleceniodawca", t["nadawca"]), ("Rachunek zleceniodawcy", iban_spaced(t["z"])),
            ("Data zlecenia", "09.02.2026"), ("Data operacji", "10.02.2026"), ("Data księgowania", "11.02.2026"),
            ("Kwota", "34,00 PLN"), ("Prowizja", "1,50 PLN"), ("Kwota obciążenia łącznie", "35,50 PLN"),
            ("Saldo po operacji", "48 213,07 PLN"),
            ("Tytuł", t["tytul"]), ("Numer transakcji", ref), ("Numer zlecenia w systemie", "ZL-000918273")]
    return dict(
        id="test_07_dystraktory_w_przelewie", odw=o, przelew=t,
        cel=["przelew z czterema różnymi datami (zlecenia, operacji, księgowania, wygenerowania) – oczekiwana 'Data operacji'",
             "kilka kwot: prowizja, kwota łączna obciążenia, saldo – oczekiwana kwota przelewu 34,00",
             "rachunek odbiorcy podany PRZED rachunkiem zleceniodawcy",
             "dodatkowy numer zlecenia jako dystraktor dla numeru transakcji",
             "w odwołaniu: dodatkowe daty innych czynności w uzasadnieniu"],
        v=dict(header_date="Łódź, dnia 12.02.2026 r.", filler=4,
               czynnosc_txt="Wnoszę odwołanie wobec <b>zaniechania wykluczenia z postępowania wykonawcy</b> Fort-Guard "
                            "Security sp. z o.o., pomimo zaistnienia podstaw z art. 109 ust. 1 pkt 8 i 10 Pzp; "
                            "zaniechanie to ujawniło się wraz z informacją o wyborze oferty przekazaną w dniu 2 lutego 2026 r.",
               distractors={1: ["Wcześniej, w dniu 21 stycznia 2026 r., Zamawiający wezwał wykonawcę Fort-Guard Security "
                                "do złożenia wyjaśnień, a w dniu 26 stycznia 2026 r. wyjaśnienia te otrzymał."]}),
        pv=dict(header_date="Łódź, 10 lutego 2026 r."),
        tv=dict(style="grid", title="Potwierdzenie operacji", bank="Bank Centralno-Łódzki S.A. · wygenerowano 12.02.2026 14:22",
                rows=rows),
    )
CASES.append(case07())

# ---------------------------------------------------------------- 08
def case08():
    odw = dict(nazwa="Hydrotech Rzeszów S.A.", adres="ul. Lwowska 140, 35-301 Rzeszów",
               krs="9994400918", nip="9998350271", regon="999611449", podpis=[("Artur Michalski", "Prezes Zarządu")])
    zam = dict(nazwa="Rzeszowskie Wodociągi i Kanalizacja sp. z o.o.", adres="ul. Naruszewicza 18, 35-055 Rzeszów",
               krs="9990077214", nip="9993918860", regon="999500271", mail="przetargi@rwik.example")
    pel = [P("Dominika Jaworska", "adw.", wpis="RZ/Adw/311"), P("Rafał Pawlak", "adw.", wpis="RZ/Adw/402")]
    tytul = ("Rozbudowa i przebudowa oczyszczalni ścieków wraz z wdrożeniem systemu sterowania procesem "
             "technologicznym i modernizacją ciągu osadowego")
    o = dict(data="2026-07-21", miejscowosc="Rzeszów", czynnosc_dzien="2026-07-14", powod=9,
             odwolujacy=[odw], zamawiajacy=[zam], pelnomocnicy=pel,
             kancelaria=dict(nazwa="Jaworska Pawlak Adwokaci sp.p.", adres="ul. 3 Maja 21/4, 35-030 Rzeszów",
                             mail="kancelaria@jaworska-pawlak.example"),
             bzp=None, ted="402771-2026", ted_txt="2026/S 133-402771", numer="RWiK/ZP/PN/17/2026", tytul=tytul)
    dot = ["<b>dotyczy:</b> postępowania o udzielenie zamówienia publicznego prowadzonego w trybie przetargu",
           "nieograniczonego pn. „Rozbudowa i przebudowa oczyszczalni ścieków wraz z wdro-",
           "<PAGEBREAK>",
           "żeniem systemu sterowania procesem technologicznym i modernizacją ciągu osado-",
           "wego”, znak sprawy: RWiK/ZP/PN/17/2026, ogłoszenie w Dz. Urz. UE nr 2026/S 133-402771"]
    ref = "CEN2607175521007"
    t = dict(data_operacji="2026-07-17", kwota=34, z=iban(R), na=iban(R), nr=ref,
             nadawca="Hydrotech Rzeszów S.A.", odbiorca="Gmina Miasto Rzeszów", tytul=fee_title(pel, o["numer"], ref))
    return dict(
        id="test_08_lamanie_stron_i_wyrazow", odw=o, przelew=t,
        cel=["tytuł zamówienia przerwany podziałem strony, ze stopką i nagłówkiem bieżącym pomiędzy częściami",
             "wyrazy podzielone łącznikiem na końcu linii ('wdro-/żeniem', 'osado-/wego') – oczekiwany tytuł bez łączników",
             "znak wodny 'KOPIA' na każdej stronie odwołania i pełnomocnictwa",
             "bieżący nagłówek stron zawierający datę (dystraktor)",
             "pełnomocnictwo: lista pełnomocników przerwana podziałem strony",
             "potwierdzenie przelewu z drugą stroną regulaminu"],
        v=dict(header_date="Rzeszów, 21.07.2026", dotyczy=dot, watermark="KOPIA",
               running_header="Odwołanie z dnia 21.07.2026 r. – sprawa RWiK/ZP/PN/17/2026", filler=6,
               czynnosc_txt="Wnoszę odwołanie od czynności <b>unieważnienia postępowania</b> na podstawie art. 255 pkt 3 "
                            "Pzp, o której Zamawiający poinformował wykonawców w dniu 14 lipca 2026 r."),
        pv=dict(header_date="Rzeszów, 16.07.2026", pel_as_list=True, pagebreak_in_list=True, footer="str. {p}/{n}"),
        tv=dict(style="grid", bank="Podkarpacki Bank Gospodarczy", rows=std_rows(t), footer="{p}/{n}",
                extra_pages=["Informacje dodatkowe. Bank realizuje polecenia przelewu zgodnie z Regulaminem rachunków "
                             "bankowych. Reklamacje dotyczące transakcji można składać w terminie 13 miesięcy od dnia "
                             "obciążenia rachunku. Kwota przykładowa w regulaminie: 1 000,00 PLN, data przykładowa 01.01.2026."]),
    )
CASES.append(case08())

# ---------------------------------------------------------------- 09 (skan)
def case09():
    odw = dict(nazwa="Kujawska Grupa Drogowa sp. z o.o.", adres="ul. Szosa Bydgoska 52, 87-100 Toruń",
               krs="9992701458", nip="9995906632", regon="999416277",
               podpis=[("Leszek Urbaniak", "Prezes Zarządu"), ("Halina Czerwińska", "Prokurent")])
    zam = dict(nazwa="Miejski Zarząd Dróg w Inowrocławku", adres="ul. Kasprowicza 31, 88-100 Inowrocławek",
               krs=None, nip="9997260419", regon="999358812", mail="mzd@inowroclawek.example")
    pel = [P("Natalia Krawczyk", "r. pr.", wpis="TO-2215")]
    o = dict(data="2026-04-17", miejscowosc="Toruń", czynnosc_dzien="2026-04-08", powod=4,
             odwolujacy=[odw], zamawiajacy=[zam], pelnomocnicy=pel,
             kancelaria=dict(nazwa="Kancelaria Radcy Prawnego Natalia Krawczyk", adres="ul. Szeroka 12, 87-100 Toruń",
                             mail="n.krawczyk@kancelaria-torun.example"),
             bzp="2026/BZP00377410", bzp_txt="2026/BZP 00377410", ted=None, numer="MZD.ZP.3.2026",
             tytul="Remont nawierzchni ulic osiedla Rąbinek wraz z przebudową kanalizacji deszczowej")
    ref = "CEN2604142290831"
    t = dict(data_operacji="2026-04-14", kwota=17, z=iban(R), na=iban(R), nr=ref,
             nadawca="Kujawska Grupa Drogowa sp. z o.o.", odbiorca="Urząd Miasta Torunia", tytul=fee_title(pel, o["numer"], ref))
    return dict(
        id="test_09_skan_bez_warstwy_tekstowej", odw=o, przelew=t, scan=True,
        cel=["wszystkie trzy PDF-y to skany (obraz w odcieniach szarości, 200 dpi, lekko obrócony, z szumem) BEZ warstwy tekstowej",
             "sprawdza, czy parser ma ścieżkę OCR / poprawnie zgłasza brak tekstu zamiast zwracać pusty lub zmyślony JSON"],
        v=dict(header_date="Toruń, 17 kwietnia 2026 r.",
               czynnosc_txt="Wnoszę odwołanie wobec treści <b>Specyfikacji Warunków Zamówienia opublikowanej</b> wraz "
                            "z ogłoszeniem o zamówieniu w dniu 8 kwietnia 2026 r., w zakresie warunków udziału "
                            "w postępowaniu dotyczących doświadczenia wykonawcy."),
        pv=dict(header_date="Toruń, 14 kwietnia 2026 r."),
        tv=dict(style="grid", bank="Bank Toruński S.A.", rows=std_rows(t, fmt_date=d_dots)),
    )
CASES.append(case09())

# ---------------------------------------------------------------- 10
def case10():
    odw = dict(nazwa="Lubuskie Przedsiębiorstwo Energetyki Cieplnej LUBTERM sp. z o.o.",
               adres="ul. Sulechowska 31, 65-119 Zielona Góra", krs="9991846620", nip="9990735518", regon="999247061",
               podpis=[("Jacek Kozłowski", "Prezes Zarządu")])
    zam = dict(nazwa="Gmina Świebodzinek", adres="ul. Rynek 2, 66-200 Świebodzinek", krs=None,
               nip="9996017742", regon="999700319", mail="sekretariat@swiebodzinek.example")
    pel = [P("Edyta Mróz", "r. pr.", wpis="ZG-1047")]
    o = dict(data=None, miejscowosc=None, czynnosc_dzien="2026-05-04", powod=10,
             odwolujacy=[odw], zamawiajacy=[zam], pelnomocnicy=pel,
             kancelaria=dict(nazwa="Mróz Legal Kancelaria Radcy Prawnego", adres="ul. Żeromskiego 5, 65-066 Zielona Góra",
                             mail="biuro@mrozlegal.example"),
             bzp=None, ted="123456-2026", ted_txt="Dz. Urz. UE S: 2026/S 087-123456", numer="ZP/PN/12/2026/WIM-II",
             tytul="Budowa sieci ciepłowniczej z przyłączami dla budynków komunalnych w Świebodzinku")
    ref = "CEN2605083376401"
    t = dict(data_operacji="2026-05-08", kwota=17, z=iban(R), na=iban(R), nr=ref,
             nadawca="LUBTERM sp. z o.o.", odbiorca="Gmina Świebodzinek", tytul=fee_title(pel, o["numer"], ref))
    return dict(
        id="test_10_brak_daty_tylko_ted", odw=o, przelew=t,
        cel=["odwołanie bez daty i miejscowości w nagłówku → data i miejscowosc = null (parser nie może ich zgadywać z treści)",
             "w treści występuje miejscowość (Zielona Góra) i daty innych zdarzeń – nie powinny trafić do pól 'data'/'miejscowosc'",
             "tylko numer TED w formacie 'Dz. Urz. UE S: 2026/S 087-123456' → '123456-2026', brak BZP",
             "nietypowy numer postępowania 'ZP/PN/12/2026/WIM-II'",
             "czynność: zaniechanie unieważnienia (id 10)"],
        v=dict(header_date=None, adresat=["Krajowa Izba Odwoławcza", "ul. Postępu 17A", "02-676 Warszawa"],
               czynnosc_txt="Wnoszę odwołanie wobec <b>zaniechania unieważnienia postępowania</b>, pomimo że cena "
                            "najkorzystniejszej oferty przewyższa kwotę przeznaczoną na sfinansowanie zamówienia, "
                            "a Zamawiający w dniu 4 maja 2026 r. wybrał tę ofertę zamiast unieważnić postępowanie.",
               extra_before_filler=["Odwołujący prowadzi działalność na terenie Zielonej Góry od 1994 r. i realizował "
                                    "podobne zadania m.in. w dniach 12–30 czerwca 2025 r."],
               sig_note="/dokument podpisany kwalifikowanym podpisem elektronicznym/"),
        pv=dict(header_date="Zielona Góra, 6 maja 2026 r."),
        tv=dict(style="stacked", bank="Bank Ziemi Lubuskiej", rows=std_rows(t, fmt_date=d_dots)),
    )
CASES.append(case10())

# ---------------------------------------------------------------- 11
def case11():
    odw = dict(nazwa="Silesia Catering Group sp. z o.o.", adres="ul. Chorzowska 150, 40-101 Katowice",
               krs="9995082317", nip="9992741190", regon="999602447", podpis=[("Beata Szewczyk", "Prezes Zarządu")])
    zam = dict(nazwa="Śląskie Centrum Opieki Długoterminowej", adres="ul. Ligocka 4, 40-570 Katowice",
               krs="9997720163", nip="9995318804", regon="999146228", mail="dzp@scod.example")
    pel = [P("Wiktor Król", "adw.", wpis="KAT/Adw/1640")]
    o = dict(data="2026-08-14", miejscowosc="Katowice", czynnosc_dzien="2026-08-07", powod=2,
             odwolujacy=[odw], zamawiajacy=[zam], pelnomocnicy=pel,
             kancelaria=dict(nazwa="Kancelaria Adwokacka Wiktor Król", adres="ul. Mariacka 20/2, 40-014 Katowice",
                             mail="wkrol@adwokat-katowice.example"),
             bzp="2026/BZP00603985", bzp_txt="2026/BZP 00603985", ted=None, numer="SCOD/DZP/22/2026",
             tytul="Przygotowywanie i dostarczanie całodziennego wyżywienia dla pacjentów")
    ref = "CEN2608107745126"
    t = dict(data_operacji="2026-08-10", kwota=17, z=iban(R), na=iban(R), nr=ref,
             nadawca="Silesia Catering Group sp. z o.o.", odbiorca="Urząd Miasta Katowice",
             tytul=fee_title(pel, o["numer"], ref))
    hist = [["10.08.2026", "10.08.2026", "PRZELEW WYCH. Wpis od odwołania SCOD/DZP/22/2026 – Urząd Zamówień Publicznych", "-7 500,00", "41 233,17"],
            ["10.08.2026", "10.08.2026", f"PRZELEW WYCH. {t['tytul']}", "-17,00", "48 733,17"],
            ["09.08.2026", "11.08.2026", "PRZELEW PRZYCH. Zapłata FV 118/07/2026", "12 400,00", "48 750,17"]]
    rows = [("Rachunek obciążony", iban_spaced(t["z"])), ("Rachunek uznany", iban_spaced(t["na"])),
            ("Odbiorca", t["odbiorca"]), ("Kwota", "17,00 PLN"), ("Data operacji", "10.08.2026"),
            ("Tytuł", t["tytul"]), ("Identyfikator", ref)]
    return dict(
        id="test_11_wyciag_wiele_operacji_synonimy", odw=o, przelew=t,
        cel=["potwierdzenie w formie wyciągu z 3 operacjami: wpis od odwołania (7 500 zł), opłata skarbowa (17 zł) i wpływ – "
             "oczekiwana operacja opłaty skarbowej od pełnomocnictwa",
             "kwoty z minusem i separatorem tysięcy w tabeli",
             "czynność 'wybór oferty' opisana innymi słowami ('dokonanie wyboru jako najkorzystniejszej'), "
             "z dodatkową, drugorzędną czynnością (zaniechanie odrzucenia) wymienioną później"],
        zalozenia=["W przelew.json oczekiwana jest opłata skarbowa od pełnomocnictwa (jak we wszystkich przykładach), nie wpis od odwołania."],
        v=dict(header_date="Katowice, 14 sierpnia 2026 r.",
               czynnosc_txt="Odwołujący kwestionuje <b>dokonanie przez Zamawiającego wyboru jako najkorzystniejszej</b> "
                            "oferty złożonej przez wykonawcę Gastro-Max S.C., o czym Zamawiający poinformował za "
                            "pośrednictwem platformy zakupowej w dniu 7 sierpnia 2026 r. Z ostrożności Odwołujący "
                            "zarzuca także zaniechanie odrzucenia tej oferty jako zawierającej rażąco niską cenę."),
        pv=dict(header_date="Katowice, 10.08.2026 r."),
        tv=dict(style="history", title="Historia rachunku – wydruk", bank="Śląski Bank Przemysłowy S.A.",
                hist_head=f"Rachunek: {iban_spaced(t['z'])} · Posiadacz: Silesia Catering Group sp. z o.o. · Okres: 09.08.2026 – 11.08.2026",
                hist_rows=hist, rows=rows),
    )
CASES.append(case11())

# ---------------------------------------------------------------- 12
def case12():
    odw = dict(nazwa="Przedsiębiorstwo Handlowo-Usługowe „ŻUBR” Grzegorz Łęcki", imie_nazwisko="Grzegorz Łęcki",
               ceidg=True, adres="ul. Kłodzka 9, 57-300 Kłodzko", krs=None, nip="9996152207",
               ids_line="NIP 999 615 22 07 · REGON 999 384 015", regon="999384015",
               podpis=[("Grzegorz Łęcki", "")])
    zam = dict(nazwa="„Wodociągi Ziemi Kłodzkiej” sp. z o.o.", adres="ul. Wojska Polskiego 2a, 57-300 Kłodzko",
               krs="9998813022", nip="9992046639", regon="999731558", mail="zp@wzk.example")
    pel = [P("Zofia Żółkiewska-Dąbrowska", "r. pr.", wpis="WR-4471")]
    o = dict(data="2026-11-03", miejscowosc="Kłodzko", czynnosc_dzien="2026-10-27", powod=6,
             odwolujacy=[odw], zamawiajacy=[zam], pelnomocnicy=pel,
             kancelaria=dict(nazwa="Kancelaria Radcy Prawnego Zofia Żółkiewska-Dąbrowska",
                             adres="ul. Łużycka 1/3, 57-300 Kłodzko", mail="biuro+kio@zolkiewska-prawo.example"),
             bzp="2026/BZP01002914", bzp_txt="2026/BZP 01002914", ted=None, numer="WZK/ZP-2/2026",
             tytul="Dostawa paliw płynnych (ON, Pb95) & olejów smarowych – część nr 2 „Rejon Północ”")
    ref = "CEN2610300018563"
    t = dict(data_operacji="2026-10-30", kwota=17, z=iban(R), na=iban(R), nr=ref,
             nadawca="PHU „ŻUBR” Grzegorz Łęcki", odbiorca="Gmina Miejska Kłodzko", tytul=fee_title(pel, o["numer"], ref))
    return dict(
        id="test_12_znaki_specjalne_cudzyslowy", odw=o, przelew=t,
        cel=["nazwy z polskimi cudzysłowami w środku („ŻUBR”, „Wodociągi Ziemi Kłodzkiej”) – nie mogą zostać obcięte na cudzysłowie",
             "tytuł zamówienia z wewnętrznym cudzysłowem, nawiasem, '&' i półpauzą",
             "NIP/REGON ze spacjami i separatorem '·'",
             "tytuł dokumentu rozstrzelony ('O D W O Ł A N I E')",
             "e-mail z '+' (biuro+kio@...)",
             "mocodawca – osoba fizyczna z nazwą firmy zawierającą cudzysłów; podpis bez funkcji",
             "czynność: odpowiedzi/wyjaśnienia treści SWZ (id 6)"],
        zalozenia=["Wewnętrzne cudzysłowy w nazwach i tytule są zachowane w JSON dokładnie jak w dokumencie; "
                   "usuwany jest tylko zewnętrzny cudzysłów „…” otaczający tytuł zamówienia."],
        v=dict(header_date="Kłodzko, 3 listopada 2026 r.", title="O D W O Ł A N I E",
               czynnosc_txt="Wnoszę odwołanie wobec czynności Zamawiającego polegającej na <b>udzieleniu w dniu "
                            "27 października 2026 r. odpowiedzi na pytania wykonawców</b> nr 4 i 9 (wyjaśnienia treści "
                            "SWZ), które w rzeczywistości zmieniają wymagania dotyczące parametrów paliwa."),
        pv=dict(header_date="Kłodzko, 30 października 2026 r."),
        tv=dict(style="grid", bank="Sudecki Bank Spółdzielczy", rows=std_rows(t, fmt_date=d_dots)),
    )
CASES.append(case12())

# ================================================================ skan
def to_scan(pdf_path, seed):
    from PIL import Image, ImageFilter
    import img2pdf, glob
    rng = random.Random(seed)
    tmp = tempfile.mkdtemp()
    subprocess.run(["pdftoppm", "-r", "200", "-gray", "-png", pdf_path, os.path.join(tmp, "p")], check=True)
    jpgs = []
    for png in sorted(glob.glob(os.path.join(tmp, "p*.png"))):
        im = Image.open(png).convert("L")
        im = im.rotate(rng.uniform(-0.9, 0.9), resample=Image.BICUBIC, expand=False, fillcolor=255)
        px = im.load(); w, h = im.size
        for _ in range(w * h // 400):
            x, y = rng.randrange(w), rng.randrange(h); px[x, y] = rng.randint(120, 200)
        im = im.filter(ImageFilter.GaussianBlur(0.4))
        jp = png[:-4] + ".jpg"; im.save(jp, quality=70, dpi=(200, 200)); jpgs.append(jp)
    with open(pdf_path, "wb") as f:
        f.write(img2pdf.convert(jpgs))
    shutil.rmtree(tmp)

# ================================================================ main
def main(out):
    os.makedirs(out, exist_ok=True)
    manifest = []
    for i, c in enumerate(CASES):
        d = os.path.join(out, c["id"]); os.makedirs(d, exist_ok=True)
        docs = c.get("only", ["odwolanie", "pelnomocnictwo", "przelew"])
        files = {}
        if "odwolanie" in docs:
            render_odwolanie(c, os.path.join(d, "odwolanie.pdf"))
            json.dump(json_odwolanie(c), open(os.path.join(d, "odwolanie.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            files["odwolanie.pdf"] = "odwolanie.json"
        if "pelnomocnictwo" in docs:
            render_pelnomocnictwo(c, os.path.join(d, "pelnomocnictwo.pdf"))
            json.dump(json_pelnomocnictwo(c), open(os.path.join(d, "pelnomocnictwo.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            files["pelnomocnictwo.pdf"] = "pelnomocnictwo.json"
        if "przelew" in docs:
            render_przelew(c, os.path.join(d, "potwierdzenie_przelewu.pdf"))
            json.dump(json_przelew(c), open(os.path.join(d, "przelew.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            files["potwierdzenie_przelewu.pdf"] = "przelew.json"
        if c.get("scan"):
            for f in files:
                to_scan(os.path.join(d, f), seed=i * 10 + len(f))
        manifest.append(dict(id=c["id"], pliki=files, sprawdza=c["cel"], zalozenia=c.get("zalozenia", [])))
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("OK", len(manifest), "przypadków ->", out)

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out")
