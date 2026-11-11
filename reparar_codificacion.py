import re
PAT = re.compile(r'[\u00e0-\u00ef][^\x00-\x7f]{2}|[\u00c2-\u00df][^\x00-\x7f]')

def to_bytes(s):
    out = bytearray()
    for ch in s:
        try:
            out += ch.encode('cp1252')
        except UnicodeEncodeError:
            if ord(ch) < 256:
                out.append(ord(ch))
            elif ch == '\ufffd':
                out.append(0x8d)      # el unico caso de este proyecto: la letra I con tilde
            else:
                raise
    return bytes(out)

def rep(m):
    try:
        return to_bytes(m.group(0)).decode('utf-8')
    except Exception:
        return m.group(0)

def malos(s):
    return len(PAT.findall(s))

for p in ['app.py', 'pdfgen.py', 'static/app.js', 'static/app.css', 'static/index.html', 'README.md']:
    try:
        raw = open(p, encoding='utf-8', newline='').read()
    except FileNotFoundError:
        print('no existe:', p)
        continue
    try:
        fixed = to_bytes(raw).decode('utf-8')
    except Exception:
        fixed = PAT.sub(rep, raw)
    print(f'{p}: dañadas antes={malos(raw)} despues={malos(fixed)}')
    if fixed != raw:
        open(p, 'w', encoding='utf-8', newline='').write(fixed)
