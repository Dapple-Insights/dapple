"""Phone swipe slides for the visual stories (Pattern and Focus "what you receive", Method "what we measure")
and the home page's "Three questions" section. Each slide is a tile with a title, a screen and a line, built
from the desktop markup, so the wording always matches. The home tiles keep the home wording, numbered, and
borrow Method's screens. Re-run after changing any of those titles, lines or screens: it replaces the slides
it made before. Usage: python -I phone_slides.py <site html>"""
import re, sys
path = sys.argv[1]
src = open(path, encoding='utf-8').read()
START, END = '<!-- phone slides (phone_slides.py) -->', '<!-- /phone slides -->'
# Drop earlier slides (and the stand-alone dots of the first version)
src = re.sub(r'\n *' + re.escape(START) + r'.*?' + re.escape(END), '', src, flags=re.S)
src = re.sub(r'\n *<div data-fq-dots="true"[^\n]*</div>', '', src)

def section(label):
    s = src.index(f'data-screen-label="{label}"')
    return s, src[s:src.index('</section>', s)]

def words(sec):
    titles = re.findall(r'data-fq-title="true">(.*?)</span>', sec)
    texts = re.findall(r'<div data-fq-body="true"><div>(?:<div data-fq-bwrap="true">)?<p[^>]*>(.*?)</p>', sec)
    assert len(titles) == 3 and len(texts) == 3
    return titles, texts

def methods(sec):
    # Method's "Example methods" tags (if the section has them), copied to the foot of each tile
    found = re.findall(r'<div data-fq-methods="true">.*?</div>', sec)
    return found if len(found) == 3 else ['', '', '']

def screens(sec):
    return [re.search(r'<div data-fq-vis="%d">(.*)</div>\n' % i, sec).group(1) for i in range(3)]

def block(titles, shots, texts, extras=('', '', '')):
    # Each tile sits in a slot whose own left padding is the 20px margin, so a swipe always snaps the tile 20px in
    slides = ''.join(
        f'\n              <div data-fq-slot="true"><div data-fq-slide="true"><span data-fq-stitle="true">{t}</span><div data-fq-sshot="true">{v}</div><p data-fq-stext="true">{x}</p>{e}</div></div>'
        for t, v, x, e in zip(titles, shots, texts, extras))
    return (f'\n          {START}\n          <div data-fq-slides="true">\n            <div data-fq-track="true">{slides}\n            </div>'
            f'\n            <div data-fq-dots="true" aria-hidden="true"><i data-on="true"></i><i></i><i></i></div>\n          </div>\n          {END}')

def three(titles):
    # Home and Method's "three questions" tiles (Jason, 27 Oct): numbered, two set lines, the key word in green
    # (data-fq-skey): "1. What customers / value", "2. What brands / offer", "3. How it performs / in use"
    out = []
    for i, t in enumerate(titles):
        t = re.sub(r' (value|offer)(\??)$', r'<br><span data-fq-skey="true">\1</span>\2', t)
        t = re.sub(r' (performs?) in use(\??)$', r' <span data-fq-skey="true">\1</span><br>in use\2', t)
        # The number sits in its own column, so the second line starts under the first word, not under the number
        out.append(f'<span data-fq-snum="true">{i + 1}.</span><span data-fq-swords="true">{t}</span>')
    return out

# Method's tiles (Jason, 27 Oct): their own shorter wording, one line each, so they differ from the desktop titles
METHOD_TILES = ['What people <span data-fq-skey="true">value</span>', 'What brands <span data-fq-skey="true">offer</span>',
                'How it <span data-fq-skey="true">performs</span>']

method_shots = screens(section('Method — what we measure')[1])
jobs = []
for label in ['Snapshot — what you receive', 'Focus — what you receive', 'Method — what we measure']:
    s, sec = section(label)
    titles, texts = words(sec)
    if label.startswith('Method'):
        titles = [f'<span data-fq-snum="true">{i + 1}.</span><span data-fq-swords="true">{t}</span>' for i, t in enumerate(METHOD_TILES)]
    jobs.append((label, titles, screens(sec), texts, '<div data-fq-visual', '\n            </div>\n          </div>', methods(sec)))
# Home: its own (numbered) questions and lines, Method's screens; it has no screens of its own, so the slides
# go straight after its grid (after the last funnel tier)
s, sec = section('Home — how we measure')
titles, texts = words(sec)
jobs.append(('Home — how we measure', three(titles), method_shots, texts, '<div data-fq-tier="2"', '\n          </div>', ('', '', '')))

for label, titles, shots, texts, anchor, close, extras in jobs:
    s = src.index(f'data-screen-label="{label}"')
    v = src.index(anchor, s)
    c = src.index(close, v) + len(close)
    src = src[:c] + block(titles, shots, texts, extras) + src[c:]
    print('slides for', label.split(' ')[0])
open(path, 'w', encoding='utf-8', newline='').write(src)
