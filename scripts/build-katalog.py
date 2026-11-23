#!/usr/bin/env python3
"""
Python-Port von scripts/build-katalog.mjs.
Erzeugt katalog.json aus der Ordnerstruktur des Repositorys.
Aufruf: python3 scripts/build-katalog.py [Wurzelordner]
"""

import sys
import os
import re
import json
import html
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
AUSGABE = ROOT / 'katalog.json'
IGNORIEREN = {'assets', 'scripts', 'node_modules'}
BILDENDUNGEN = ['webp', 'png', 'jpg', 'jpeg', 'svg']

kategorien = []
materialien = []
warnungen = []


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace('\\', '/')


def lese_head(datei: Path):
    try:
        text = datei.read_text(encoding='utf-8', errors='replace')
    except Exception as e:
        warnungen.append(f"{rel(datei)}: Lesefehler ({e})")
        return {}, ''

    m_head = re.search(r'<head\b[^>]*>([\s\S]*?)</head>', text, re.IGNORECASE)
    head_content = m_head.group(1) if m_head else text

    meta = {}
    for tag_match in re.finditer(r'<meta\b([^>]*)>', head_content, re.IGNORECASE):
        tag_attrs = tag_match.group(1)
        attrs = {}
        for attr_m in re.finditer(r'([\w:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))', tag_attrs):
            name = attr_m.group(1).lower()
            val = attr_m.group(2) if attr_m.group(2) is not None else (
                attr_m.group(3) if attr_m.group(3) is not None else attr_m.group(4)
            )
            attrs[name] = val or ''
        key = (attrs.get('name') or attrs.get('property') or '').lower()
        if key and 'content' in attrs:
            meta[key] = html.unescape(attrs['content']).strip()

    titel_m = re.search(r'<title\b[^>]*>([\s\S]*?)</title>', head_content, re.IGNORECASE)
    titel = re.sub(r'\s+', ' ', html.unescape(titel_m.group(1))).strip() if titel_m else ''

    return meta, titel


def liste(s: str) -> list[str]:
    return [x.strip() for x in re.split(r'[,;]', s or '') if x.strip()]


def klassen(s: str) -> list[str]:
    aus = []
    for teil in liste(s):
        r = re.match(r'^(\d{1,2})\s*[-–]\s*(\d{1,2})$', teil)
        if r:
            start, end = int(r.group(1)), int(r.group(2))
            for k in range(start, end + 1):
                aus.append(str(k))
        else:
            aus.append(re.sub(r'^(kl\.?|klasse)\s*', '', teil, flags=re.IGNORECASE))
    return list(dict.fromkeys(aus))


def git_datum(p: Path) -> str:
    try:
        out = subprocess.check_output(
            ['git', 'log', '-1', '--format=%cI', '--', str(p)],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            encoding='utf-8'
        ).strip()
        if out:
            return out[:10]
    except Exception:
        pass
    mtime = datetime.fromtimestamp(p.stat().st_mtime)
    return mtime.strftime('%Y-%m-%d')


def huebscher_name(ordner: str) -> str:
    s = re.sub(r'[-_]+', ' ', ordner).strip()
    return s[:1].upper() + s[1:] if s else ''


def vorschau_suchen(basis: Path) -> str:
    for ext in BILDENDUNGEN:
        cand = basis.with_suffix('.' + ext)
        if cand.exists():
            return rel(cand)
    return ''


def erfasse_material(html_datei: Path, kategorie_pfad: list[str], ist_ordner: bool):
    meta, titel = lese_head(html_datei)
    def m(k: str) -> str:
        return meta.get(f'material:{k}', '')

    if re.match(r'^(nein|false|aus)$', m('katalog'), re.IGNORECASE):
        return

    ordner = html_datei.parent
    ziel = ordner if ist_ordner else html_datei
    url = '/'.join(rel(ziel).split(os.sep)) + ('/' if ist_ordner else '')

    vorschau_meta = m('vorschau')
    if vorschau_meta:
        vorschau = rel((ordner / vorschau_meta).resolve())
    else:
        basis = ordner / 'vorschau' if ist_ordner else html_datei.with_suffix('')
        vorschau = vorschau_suchen(basis)

    ziel_name = ziel.name[:-5] if ziel.name.lower().endswith('.html') else ziel.name
    eintrag = {
        'titel': m('titel') or titel or huebscher_name(ziel_name),
        'beschreibung': meta.get('description', ''),
        'url': url,
        'pfad': kategorie_pfad,
        'typ': m('typ'),
        'klassen': klassen(m('klasse')),
        'geraete': liste(m('geraet')),
        'stichworte': liste(m('stichworte')),
        'vorschau': vorschau,
        'reihenfolge': int(m('reihenfolge')) if m('reihenfolge').isdigit() else 100,
        'datum': git_datum(ziel)
    }

    if not eintrag['beschreibung']:
        warnungen.append(f"{url}: keine <meta name=\"description\">")
    if not eintrag['typ']:
        warnungen.append(f"{url}: kein material:typ")

    materialien.append(eintrag)


def durchsuche(ordner: Path, segmente: list[str]):
    try:
        eintraege = sorted(list(ordner.iterdir()), key=lambda e: e.name.lower())
    except Exception as e:
        warnungen.append(f"{rel(ordner)}: Kann Ordner nicht lesen ({e})")
        return

    vorher = len(materialien)

    if segmente:
        index_datei = next((e for e in eintraege if e.is_file() and e.name.lower() == 'index.html'), None)
        if index_datei:
            erfasse_material(index_datei, segmente[:-1], ist_ordner=True)
            return

        for e in eintraege:
            if e.is_file() and e.name.lower().endswith(('.html', '.htm')):
                erfasse_material(e, segmente, ist_ordner=False)

    for e in eintraege:
        if not e.is_dir() or e.name.startswith('.') or e.name.startswith('_'):
            continue
        if not segmente and e.name in IGNORIEREN:
            continue
        durchsuche(e, segmente + [e.name])

    if segmente and len(materialien) > vorher:
        info = {}
        json_datei = ordner / 'ordner.json'
        if json_datei.exists():
            try:
                info = json.loads(json_datei.read_text(encoding='utf-8'))
            except Exception as err:
                warnungen.append(f"{rel(json_datei)}: ungültiges JSON ({err})")
        
        kat = {
            'pfad': segmente,
            'titel': info.get('titel') or huebscher_name(segmente[-1]),
            'beschreibung': info.get('beschreibung', ''),
            'reihenfolge': int(info.get('reihenfolge', 100))
        }
        if 'farbe' in info:
            kat['farbe'] = info['farbe']
        kategorien.append(kat)


def main():
    durchsuche(ROOT, [])

    kategorien.sort(key=lambda k: '/'.join(k['pfad']))
    materialien.sort(key=lambda m: m['url'])

    katalog = {
        'version': 1,
        'kategorien': kategorien,
        'materialien': materialien
    }

    AUSGABE.write_text(json.dumps(katalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"katalog.json: {len(materialien)} Materialien in {len(kategorien)} Kategorien")
    for w in warnungen:
        print(f"  Hinweis: {w}")


if __name__ == '__main__':
    main()
