"""Validate this documentation slice without changing platform behavior."""
from __future__ import annotations

import ast
import collections
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup

OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[1]


def main():
    pages = sorted(OUT.glob('*.html'))
    trees = {p: BeautifulSoup(p.read_text(), 'html.parser') for p in pages}
    ids = {p: {n['id'] for n in soup.select('[id]')} for p,soup in trees.items()}
    failures = []
    link_count = 0
    snippets = 0
    refs = 0
    for path, soup in trees.items():
        raw = path.read_text()
        if '<!doctype html>' not in raw.lower():
            failures.append(f'{path.name}: missing doctype')
        if not soup.html or soup.html.get('lang') != 'zh-CN':
            failures.append(f'{path.name}: missing language')
        if not soup.select_one('meta[name="viewport"]'):
            failures.append(f'{path.name}: missing viewport')
        if re.search(r'\[\[[CER]\d{2}\]\]', raw):
            failures.append(f'{path.name}: unresolved source token')
        duplicate = [x for x,n in collections.Counter(n['id'] for n in soup.select('[id]')).items() if n>1]
        if duplicate:
            failures.append(f'{path.name}: duplicate IDs {duplicate}')
        if soup.select('script[src],link[rel="stylesheet"],iframe'):
            failures.append(f'{path.name}: external execution/assets')
        for element in soup.select('[src]'):
            if urlsplit(element['src']).scheme in ('http','https'):
                failures.append(f'{path.name}: remote asset')
        for value in re.findall(r'url\(#([^)]+)\)', raw):
            if value not in ids[path]:
                failures.append(f'{path.name}: missing SVG/CSS fragment {value}')
        for a in soup.select('a[href]'):
            link_count += 1
            if 'ref' in a.get('class',[]):
                refs += 1
            url = urlsplit(a['href'])
            if url.scheme in ('http','https','mailto'):
                continue
            target = (path.parent/unquote(url.path)).resolve() if url.path else path
            if not target.exists():
                failures.append(f'{path.name}: missing local target {a["href"]}')
            elif url.fragment and target in ids and unquote(url.fragment) not in ids[target]:
                failures.append(f'{path.name}: missing anchor {a["href"]}')
        for pre in soup.select('pre[data-language]'):
            snippets += 1
            source = pre.get_text()
            try:
                if pre['data-language']=='python':
                    ast.parse(source)
                elif pre['data-language']=='json':
                    json.loads(source)
            except Exception as ex:
                failures.append(f'{path.name}: bad code example {ex}')
    audit = json.loads((OUT/'verification/source-audit.json').read_text())
    for code in audit['code']:
        if hashlib.sha256((ROOT/code['path']).read_bytes()).hexdigest()!=code['sha256']:
            failures.append(f'Code source changed after audit: {code["path"]}')
    result = {'status':'passed' if not failures else 'failed','html_pages':len(pages),
              'checked_links':link_count,'evidence_citations':refs,'syntax_checked_snippets':snippets,
              'failures':failures,
              'limits':'Static structure/link/syntax checks, supplemented by separately saved real browser screenshots; not full accessibility or backend UI validation.'}
    (OUT/'verification/html-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(bool(failures))


if __name__=='__main__':
    main()
