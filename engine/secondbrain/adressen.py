"""adressen.py - Absender und Empfaenger einer Mail: vollstaendig und als Verweise auf die Personenseiten.

Aus den Kopfzeilen (From, To, CC) werden Eintraege: Name, Adresse und die Person des Vaults - erkannt
ueber die Mail-Adresse auf ihrer Seite (`email:`), den Namen, einen Alias, "Nachname, Vorname" oder
vorname.nachname@ - oder ein Verteiler (eine Gruppen-Adresse, kein Personenname). Daraus schreibt
mails.py die Felder der Mail-Notiz, nachziehen.py bringt alte Mails auf denselben Stand:

    von:        "[[slug|Name]]"  oder  "Name <adresse>"
    an, cc:     ebenso, als Liste - vollstaendig
    verteiler:  Gruppen-Adressen aus An und CC
    teilnehmer: die erkannten Personen aus Von und An (wie bei Terminen); bei einer Rundmail nur der
                Absender - sonst waere jeder Empfaenger einer Rundmail an ihren Themen "beteiligt"

Ein Name, der auf mehrere Personen passt, wird kein Verweis - geraten wird nie.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.utils import getaddresses

import vault_paths as vp

# Fassung der Mail-Felder: steigt sie, zieht nachziehen.py alte Mail-Notizen nach
MAIL_FASSUNG = 2
# Mehr Empfaenger (An und CC, ohne Verteiler) als das - oder ein Verteiler in An: eine Rundmail
RUNDMAIL_AB = 15
# Woerter, an denen man eine Gruppen-Adresse erkennt (im Namen oder vor dem @)
_GRUPPE = re.compile(r"(?i)(?<![a-z])(all-?members|verteiler|distribution|mailing|newsletter|no-?reply|"
                     r"team|group|gruppe|support|service|helpdesk|admin|office|info|alle)(?![a-z])")
_LINK = re.compile(r"^\[\[([^\]|#]+)(?:[|#]([^\]]*))?\]\]$")
_NAME_ADRESSE = re.compile(r"^(.*?)\s*<([^<>@\s]+@[^<>\s]+)>$")


def fold(text: str) -> str:
    """Zum Vergleichen: klein, Umlaute als ae/oe/ue, ohne Akzente, Trennzeichen als Leerzeichen."""
    t = str(text or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[.\-_,;'\"()]+", " ", t).split())


def _dekodiert(text: str) -> str:
    try:
        return str(make_header(decode_header(text)))
    except Exception:  # noqa: BLE001 - kaputter Header: wie er ist
        return text


@dataclass
class Eintrag:
    name: str                  # Anzeigename (dekodiert) - oder aus der Adresse gebildet
    adresse: str
    slug: str | None = None    # Personenseite
    person_name: str = ""      # Name auf der Personenseite
    verteiler: bool = False

    def text(self) -> str:
        """So steht der Eintrag im Frontmatter."""
        if self.slug:
            return f"[[{self.slug}|{self.person_name or self.name or self.slug}]]"
        if self.name and self.adresse and fold(self.name) != fold(self.adresse):
            return f"{self.name} <{self.adresse}>"
        return self.name or self.adresse


class Personen:
    """Die Personenseiten nach Mail-Adresse und Namen (Name, Titel, Aliasse, Dateiname) - nur Eindeutiges."""

    def __init__(self) -> None:
        self.adressen: dict[str, str] = {}
        namen: dict[str, set[str]] = {}
        self.namen_von: dict[str, str] = {}
        for f in sorted(vp.PEOPLE_DIR.glob("*.md")) if vp.PEOPLE_DIR.is_dir() else []:
            fm = vp.read_frontmatter_head(f)
            slug = f.stem
            self.namen_von[slug] = str(fm.get("name") or fm.get("title") or slug)
            mails = fm.get("email")
            for m in (mails if isinstance(mails, list) else [mails]):
                if m and "@" in str(m):
                    self.adressen.setdefault(str(m).strip().lower(), slug)
            aliase = fm.get("aliases") or []
            for n in [fm.get("name"), fm.get("title"), slug.replace("-", " "),
                      *(aliase if isinstance(aliase, list) else [aliase])]:
                k = fold(re.sub(r"\s*\([^)]*\)\s*$", "", str(n or "")))
                if len(k.split()) >= 2:       # nur volle Namen - ein Vorname allein ist kein Beleg
                    namen.setdefault(k, set()).add(slug)
        self.namen = {k: next(iter(v)) for k, v in namen.items() if len(v) == 1}

    def finde(self, name: str, adresse: str) -> str | None:
        if adresse and adresse.lower() in self.adressen:
            return self.adressen[adresse.lower()]
        kandidaten = [name]
        if "," in name:                                   # "Nachname, Vorname"
            teile = [t.strip() for t in name.split(",", 1)]
            kandidaten.append(f"{teile[1]} {teile[0]}")
        worte = name.split()
        if len(worte) == 2:                               # "Nachname Vorname" ohne Komma
            kandidaten.append(f"{worte[1]} {worte[0]}")
        initialen = re.fullmatch(r"([A-ZÀ-Þ][a-zß-ÿ]+)[A-Z]{1,3}", worte[0]) if worte else None
        if initialen:                                     # "SteveMH Lee": Initialen am Vornamen
            kandidaten.append(" ".join([initialen.group(1), *worte[1:]]))
        lokal = adresse.split("@", 1)[0] if adresse else ""
        if re.fullmatch(r"[A-Za-zÀ-ÿ]+[._][A-Za-zÀ-ÿ.\-_]+", lokal or ""):
            kandidaten.append(lokal)                      # vorname.nachname@
        for k in kandidaten:
            slug = self.namen.get(fold(re.sub(r"\s*\([^)]*\)\s*$", "", k)))
            if slug:
                return slug
        return None


def _ist_verteiler(name: str, adresse: str) -> bool:
    lokal = adresse.split("@", 1)[0] if adresse else ""
    if _GRUPPE.search(name) or _GRUPPE.search(lokal):
        return True
    if len(name.split()) >= 2:                            # "Vorname Nachname" - Leerzeichen, nicht Bindestriche
        return False                                      # ("GIS-EDI-Global" ist ein Verteiler)
    return not re.fullmatch(r"[A-Za-zÀ-ÿ]+[._][A-Za-zÀ-ÿ\-]+", lokal or "")


def eintraege(kopf: str, personen: Personen) -> list[Eintrag]:
    """Eine Kopfzeile (From, To oder CC) als Eintraege - in ihrer Reihenfolge, ohne Doppelte."""
    out, gesehen = [], set()
    for name, adresse in getaddresses([str(kopf or "")]):
        name = " ".join(_dekodiert(name).replace('"', "").split()).strip("' ")
        adresse = adresse.strip()
        if not name and not adresse:
            continue
        if not name and adresse and "@" in adresse:
            name = " ".join(re.sub(r"[._]+", " ", adresse.split("@")[0]).split()).title()
        schluessel = adresse.lower() or fold(name)
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        slug = personen.finde(name, adresse)
        out.append(Eintrag(name=name, adresse=adresse, slug=slug, person_name=personen.namen_von.get(slug or "", ""),
                           verteiler=not slug and _ist_verteiler(name, adresse)))
    return out


def felder(von: str, an: str, cc: str, personen: Personen | None = None) -> dict:
    """Die Felder der Mail-Notiz aus ihren Kopfzeilen (siehe oben)."""
    personen = personen or Personen()
    v, a, c = (eintraege(k, personen) for k in (von, an, cc))
    verteiler = [e for e in a + c if e.verteiler]
    an_p, cc_p = [e for e in a if not e.verteiler], [e for e in c if not e.verteiler]
    rund = len(an_p) + len(cc_p) > RUNDMAIL_AB or any(e.verteiler for e in a)
    teilnehmer = [e for e in v[:1] + ([] if rund else an_p) if e.slug]
    return {"von": v[0].text() if v else "",
            "an": [e.text() for e in an_p], "cc": [e.text() for e in cc_p],
            "verteiler": [e.text() for e in verteiler],
            "teilnehmer": list(dict.fromkeys(e.text() for e in teilnehmer)),
            "rundmail": rund}


def aus_kopfzeile(zeile: str) -> str:
    """Eine schon dekodierte Kopfzeile ("**An:** Kurz, Karl <k@x>, Anna Berg <a@x>") wieder als Adressliste,
    die getaddresses sicher zerlegt: jeder Name steht zwischen dem vorigen ">" und seinem "<" - ein Komma im
    Namen ("Nachname, Vorname") trennt dann nicht mehr. Adressen ohne Klammern bleiben, wie sie sind."""
    teile, rest = [], str(zeile or "")
    for m in re.finditer(r"([^<>]*?)<([^<>@\s]+@[^<>\s]+)>", rest):
        name = m.group(1).strip().lstrip(",;").strip().replace('"', "")
        teile.append(f'"{name}" <{m.group(2)}>' if name else f"<{m.group(2)}>")
    ohne = re.sub(r"[^<>]*?<[^<>@\s]+@[^<>\s]+>", "", rest)
    teile += [t.strip() for t in re.split(r"[,;]", ohne) if "@" in t]
    return ", ".join(teile)


def link_slug(wert: str) -> str | None:
    """Slug aus einem Eintrag "[[slug|Name]]" - None, wenn er kein Verweis ist."""
    m = _LINK.match(str(wert or "").strip())
    return m.group(1).strip() if m else None


def name_adresse(wert: str) -> tuple[str, str]:
    """Name und Adresse aus einem Eintrag "Name <adresse>" (oder nur einem Namen)."""
    m = _NAME_ADRESSE.match(str(wert or "").strip())
    return (m.group(1).strip(), m.group(2)) if m else (str(wert or "").strip(), "")
