"""Inspect and patch Word packages while preserving untouched package parts.

Python 3.10+, standard library only. Never executes code from source archives.
"""
import argparse
import copy
import hashlib
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}
def tag(s): return '{' + W + '}' + s
def digest(b): return hashlib.sha256(b).hexdigest()
def text(p): return ''.join(t.text or '' for t in p.iter(tag('t')))
def read_json(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write_json(p, data):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
def xml_parts(z):
    return [n for n in z.namelist() if n.startswith('word/') and n.endswith('.xml') and
            (n == 'word/document.xml' or re.search(r'/(header\d+|footer\d+|footnotes|endnotes|comments)\.xml$', n))]
def scan(path):
    result = {'source': str(Path(path).resolve()), 'sha256': digest(Path(path).read_bytes()), 'parts': {}, 'paragraphs': [], 'warnings': []}
    with zipfile.ZipFile(path) as z:
        result['parts'] = {n: digest(z.read(n)) for n in z.namelist()}
        for name in xml_parts(z):
            root = ET.fromstring(z.read(name))
            for i, p in enumerate(root.iter(tag('p'))):
                result['paragraphs'].append({'id': f'{name}#{i}', 'text': text(p),
                    'properties': ET.tostring(p.find(tag('pPr')), encoding='unicode') if p.find(tag('pPr')) is not None else '',
                    'run_properties': [ET.tostring(r, encoding='unicode') for r in p.findall('w:r/w:rPr', NS)],
                    'tabs': len(list(p.iter(tag('tab')))), 'breaks': [x.attrib for x in p.iter(tag('br'))],
                    'hidden_runs': len(list(p.iter(tag('vanish')))),
                    'complex': any(list(p.iter(tag(t))) for t in ['drawing','pict','fldChar','instrText','hyperlink','sdt','txbxContent'])})
            if name == 'word/document.xml':
                result['sections'] = [ET.tostring(s, encoding='unicode') for s in root.iter(tag('sectPr'))]
        all_text = '\n'.join(p['text'] for p in result['paragraphs'])
        for label, pattern in [('placeholder', r'…{3,}|\.{8,}|\{\{.*?\}\}|25[Xx]+'), ('TLP label', r'TLP\s*:\s*(?:AMBER|CLEAR|GREEN|RED)'), ('CVE', r'CVE-\d{4}-\d+')]:
            result['warnings'].append({'kind': label, 'matches': sorted(set(re.findall(pattern, all_text)))})
    return result

def patch(source, planfile, output):
    plan = read_json(planfile)
    if Path(source).resolve() == Path(output).resolve(): raise ValueError('Output must differ from source')
    if Path(output).exists(): raise ValueError('Output already exists; choose a new version')
    if digest(Path(source).read_bytes()) != plan['source_sha256']: raise ValueError('Source hash mismatch')
    grouped = {}
    for item in plan['replacements']:
        part, index = item['id'].rsplit('#', 1)
        if int(index) in grouped.setdefault(part, {}): raise ValueError('Duplicate slot')
        grouped[part][int(index)] = item
    changed = {}
    with zipfile.ZipFile(source) as z:
        for part, edits in grouped.items():
            if part not in xml_parts(z): raise ValueError('Unsupported part')
            raw = z.read(part)
            # Keep namespace prefixes used by compatibility attributes.
            for prefix, uri in re.findall(rb'xmlns(?::([\w]+))?="([^"]+)"', raw):
                try: ET.register_namespace(prefix.decode(), uri.decode())
                except ValueError: pass
            root = ET.fromstring(raw)
            paras = list(root.iter(tag('p')))
            for index, item in edits.items():
                p = paras[index]
                if text(p) != item['old_text']: raise ValueError('Slot text mismatch: ' + item['id'])
                if any(list(p.iter(tag(t))) for t in ['drawing','pict','fldChar','instrText','hyperlink','sdt','txbxContent','bookmarkStart','bookmarkEnd','commentRangeStart','commentRangeEnd','ins','del']):
                    raise ValueError('Complex slot requires a dedicated OOXML edit: ' + item['id'])
                # Refuse paragraph rewrites with mixed inline formatting.
                formats = {ET.tostring(r.find(tag('rPr'))) if r.find(tag('rPr')) is not None else b'' for r in p.findall('w:r',NS) if r.find(tag('t')) is not None}
                if len(formats) > 1 and not item.get('allow_flatten_runs', False):
                    raise ValueError('Mixed run formatting: explicitly choose allow_flatten_runs or use targeted text edits')
                values = item['text']
                if isinstance(values, str): values = [values]
                if not values or not all(isinstance(v,str) for v in values): raise ValueError('text must be a string or nonempty string list')
                prototype = copy.deepcopy(p)
                parent = next(x for x in root.iter() if p in list(x))
                pos = list(parent).index(p)
                for j, value in enumerate(values):
                    dest = p if j == 0 else copy.deepcopy(prototype)
                    if j and dest.find('w:pPr/w:sectPr',NS) is not None: raise ValueError('Cannot clone section-break paragraph')
                    rp = dest.find('w:r/w:rPr', NS)
                    rp = copy.deepcopy(rp) if rp is not None else None
                    for child in list(dest):
                        if child.tag != tag('pPr'): dest.remove(child)
                    run = ET.SubElement(dest, tag('r'))
                    if rp is not None: run.append(rp)
                    node = ET.SubElement(run, tag('t'), {'{http://www.w3.org/XML/1998/namespace}space':'preserve'})
                    node.text = value
                    if j: parent.insert(pos+j, dest)
            serialized = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            # ElementTree drops declarations referenced only by mc:Ignorable.
            decls = re.findall(rb'(xmlns(?::[\w]+)?="[^"]+")', raw)
            end = serialized.index(b'>', serialized.index(b'?>')+2)
            missing = [d for d in decls if d.split(b'=')[0]+b'=' not in serialized[:end]]
            if missing: serialized = serialized[:end]+b' '+b' '.join(missing)+serialized[end:]
            ET.fromstring(serialized)
            changed[part] = serialized
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as out:
            for info in z.infolist(): out.writestr(info, changed.get(info.filename, z.read(info.filename)))
    with zipfile.ZipFile(source) as a, zipfile.ZipFile(output) as b:
        assert a.namelist() == b.namelist()
        assert all(a.read(n) == b.read(n) for n in a.namelist() if n not in changed)
    return {'output': str(Path(output).resolve()), 'changed_parts': list(changed), 'untouched_parts_byte_identical': True, 'visual_review': 'required'}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    s=sub.add_parser('inspect'); s.add_argument('docx'); s.add_argument('output_json')
    s=sub.add_parser('patch'); s.add_argument('docx'); s.add_argument('plan_json'); s.add_argument('output_docx')
    s=sub.add_parser('catalog'); s.add_argument('archive'); s.add_argument('output_json')
    a=p.parse_args()
    if a.command=='inspect': write_json(a.output_json,scan(a.docx)); print(a.output_json)
    elif a.command=='patch': print(json.dumps(patch(a.docx,a.plan_json,a.output_docx),ensure_ascii=False))
    else:
        with zipfile.ZipFile(a.archive) as z:
            write_json(a.output_json,[{'path':n.filename,'bytes':n.file_size} for n in z.infolist()])
        print(a.output_json)
if __name__=='__main__': main()
