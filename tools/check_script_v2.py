"""Code check for podcast spec v2.2 episodes (the new pipeline). The old producer keeps tools/check_script.py until Sunday.

usage: python3 tools/check_script_v2.py <script.txt> <guide.txt> <guide.json> [numbers.json]
  guide.txt   the redesigned guide as text (the source)
  guide.json  the guide's v4 data (blocks[].title gives the map)
  numbers.json  [{"figure": "...", "tag": "learn|look-up"}]  (optional; enables the look-up figure check)
Prints JSON: ok, errors (blocking), flags (for the Opus checks to judge), stats.
"""
import json, re, sys, collections, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_script as C          # the content checks (figures, names, years, tags, markup)
from scriptfmt import parse

CONFIRM = re.compile(r"^(\([^)]*\)\s*)?(yes|right|correct|that's right|that's it|spot on|true|good,? and right)\b", re.I)
CORRECT = re.compile(r"^(\([^)]*\)\s*)?(no\b|not quite|nearly|close|careful|almost|not so fast|that's the trap|wrong)", re.I)
NEG = re.compile(r"\b(isn't|aren't|doesn't|don't|can't|cannot|won't|never|not|no)\b", re.I)
ORD = re.compile(r"\b(one|two|three|four|five|six|seven|eight|first|second|third|fourth|fifth|sixth)\b[,:.]", re.I)


def base_checks(script, guide_text):
    """The repo's content checks, with v2's sections mapped onto the old ones and the old shape rules dropped."""
    t = script.replace('## Map', '## Rule')
    t = re.sub(r'^## Block [^\n]*\n', '', t, flags=re.M).replace('<think>', '<long pause>')
    if '## Exam mode' not in t:
        t = t.replace('## Recap', '## Exam mode\nWill: (exam scenarios sit inside the blocks in spec v2)\n## Recap')
    r = C.check(t, guide_text)
    drop = ('length', 'header: map must list', 'header: recap must list', 'sections must be exactly')
    errors = [x for x in r['errors'] if not x.startswith(drop)]
    flags = [x for x in r['warnings'] if not x.startswith(('section ', 'very long turn'))]
    return errors, flags, r.get('stats', {})


def runs(turns):
    """Consecutive turns by one presenter, merged (they count as one turn)."""
    out = []
    for i, t in enumerate(turns):
        if out and out[-1]['who'] == t['who'] and t['text'].strip() != '<think>' and out[-1]['text'].strip() != '<think>':
            out[-1]['text'] += ' ' + t['text']; out[-1]['idx'].append(i)
        else:
            out.append({'who': t['who'], 'text': t['text'], 'idx': [i], 'section': t['section']})
    return out


def list_items(text):
    worst = 0
    for sent in re.split(r'(?<=[.?!])\s+', text):
        m = re.search(r'((?:[^,;:]+,){2,}[^,;:]*\b(?:and|or)\b[^,;:.?!]+)', sent)
        if m: worst = max(worst, m.group(1).count(',') + 1)
    return worst


def check(script, guide_text, guide, numbers=None):
    errors, flags, stats = base_checks(script, guide_text)
    ps = parse(script); meta, turns = ps['meta'], ps['turns']
    all_titles = [b['title'] for b in guide['blocks']]
    first, last = 1, len(all_titles)
    if meta.get('part') or meta.get('blocks'):          # a part of a split episode (spec v2.2, Splitting)
        m = re.match(r'\s*(\d+)\s*-\s*(\d+)\s*$', str(meta.get('blocks', '')))
        if not (m and re.match(r'\s*\d+ of \d+\s*$', str(meta.get('part', '')))):
            errors.append('header: a part needs `part: n of N` and `blocks: a-b`')
        else:
            first, last = int(m.group(1)), int(m.group(2))
    titles = all_titles[first - 1:last]
    # shape
    if [x.strip() for x in meta.get('map', [])] != titles:
        errors.append('map: lines must equal the guide block titles in order: %s' % titles)
    want = ['Block %d: %s' % (i, t) for i, t in enumerate(all_titles, 1)][first - 1:last]
    blocks = [s for s in ps['sections'] if s.startswith('Block ')]
    if blocks != want: errors.append('sections: expected %s, got %s' % (want, blocks))
    per = collections.Counter(t['section'] for t in turns if t['text'].strip() == '<think>')
    for b in want:
        if per[b] > 2: errors.append('%s has %d think-gaps (at most 2)' % (b, per[b]))
    for i, t in enumerate(turns):
        if t['text'].strip() == '<think>':
            prev = turns[i - 1]['text'] if i else ''
            if '?' not in prev or not re.search(r'\bor\b', prev): errors.append('think-gap at turn %d: the turn before must restate the question with its options' % i)
            if i + 1 < len(turns) and turns[i + 1]['text'].strip() == '<think>': errors.append('two think-gaps in a row at turn %d' % i)
    ngaps = sum(per.values())
    if not 2 <= ngaps <= 4: flags.append('%d think-gaps (spec: 2-4 scenarios an episode)' % ngaps)
    summ = (meta.get('summary') or '').lower()
    miss = [t for t in titles if not any(w.lower() in summ for w in re.findall(r'[A-Za-z]{5,}', t)[:1])]
    if miss: flags.append('summary may not name every topic: %s' % miss)
    # spoken rules (A26a)
    NUMW = r'(one|two|three|four|five|six|seven|eight|nine|ten|\d+)'
    for i, t in enumerate(turns):
        x = t['text']
        if re.search(r'\bBPP', x): errors.append('turn %d names BPP' % i)
        if re.search(r'\bblocks?\s+' + NUMW + r'\b|\b' + NUMW + r'\s+blocks\b', x, re.I): errors.append('turn %d uses a block number' % i)
        for m in re.finditer(r"(?<![\w'’])(section|s|rule|reg(?:ulation)?|para(?:graph)?|article|CPR|PD)\.?\s?\d+[A-Z]?(\.\d+)?\b", x):
            flags.append('turn %d section number "%s": keep only if it is how the rule is known' % (i, m.group(0)))
        for m in re.finditer(r'\b[A-Z][A-Za-z]+ v [A-Z][A-Za-z]+', x):
            flags.append('turn %d case "%s": keep only if it genuinely helps' % (i, m.group(0)))
        for m in re.finditer(r'\b(19|20)\d\d\b', x):
            flags.append('turn %d year %s: only if the date decides a question' % (i, m.group(0)))
    # the same presenter twice in a row (except before a think-gap)
    for i in range(1, len(turns)):
        if turns[i]['section'] == turns[i - 1]['section'] and turns[i]['who'] == turns[i - 1]['who'] and '<think>' not in (turns[i]['text'], turns[i - 1]['text']) and turns[i]['text'].strip() != '<think>':
            if not (i + 1 < len(turns) and turns[i + 1]['text'].strip() == '<think>'):
                errors.append('turn %d: %s speaks twice in a row' % (i, turns[i]['who']))
    # confirmations
    R = runs(turns)
    for k in range(1, len(R) - 1):
        h, prev, nxt = R[k], R[k - 1], R[k + 1]
        if h['who'] != 'Hannah' or h['text'].strip() == '<think>' or nxt['who'] != 'Will': continue
        answers = prev['who'] == 'Will' and prev['text'].rstrip().endswith('?')
        sums = '(summing up)' in h['text'] or re.match(r'^\s*So\b', h['text'])
        after_gap = k >= 2 and R[k - 1]['text'].strip() == '<think>'
        if (answers or sums or after_gap) and not h['text'].rstrip().endswith('?'):
            if not (CONFIRM.match(nxt['text'].strip()) or CORRECT.match(nxt['text'].strip())):
                errors.append("turn %d: Hannah answers or sums up; Will's next turn must confirm ('Yes'/'Right' + the point) or correct" % h['idx'][0])
            if re.match(r"^(\([^)]*\)\s*)?No\b[.,]", nxt['text'].strip()) and NEG.search(h['text']):
                flags.append("turn %d: Will answers a negative statement with 'No': if he agrees, use 'Right' (never a bare 'No.')" % nxt['idx'][0])
    # lists counted across one presenter's consecutive lines
    for r in R:
        n = list_items(r['text'])
        if n > 4 and r['section'] != 'Recap': errors.append('turn %d: a list of %d items (at most four; consecutive lines count together)' % (r['idx'][0], n))
    # repeated 8-word runs within three turns
    def grams(x):
        w = re.findall(r"[a-z0-9']+", x.lower()); return {' '.join(w[j:j + 8]) for j in range(len(w) - 7)}
    G = [grams(t['text']) for t in turns]
    for i in range(len(turns)):
        for j in range(i + 1, min(len(turns), i + 4)):
            common = G[i] & G[j]
            if common and j == i + 1 and CONFIRM.match(turns[j]['text'].strip()):
                continue                      # a confirmation restating the point it confirms (spec v2.2: "Yes"/"Right" plus the point)
            if common: errors.append('turns %d and %d repeat an 8-word run: "%s"' % (i, j, sorted(common)[0])); break
    # spoken look-up figures
    if numbers:
        learn = {n['figure'] for n in numbers if n.get('tag') == 'learn' and n.get('figure')}
        look = {n['figure'] for n in numbers if n.get('tag') == 'look-up' and n.get('figure')} - learn   # a figure tagged both ways is not flagged
        gap_near = {j for k, t in enumerate(turns) if t['text'].strip() == '<think>' for j in range(k - 6, k + 4) if 0 <= j < len(turns)}
        for f in look:
            core = re.findall(r"£?\d[\d,.]*(?:/\d+)?(?:\s?(?:%|per cent|m\b|bn\b|million|billion))?", f)
            if not core: continue
            c = core[0].strip()
            if any(c == lc for lf in learn for lc in [x.strip() for x in re.findall(r"£?\d[\d,.]*(?:/\d+)?(?:\s?(?:%|per cent|m\b|bn\b|million|billion))?", lf)]):
                continue                      # the same figure is a learn figure for another rule
            pat = re.compile(r"(?<![\d.,/])" + re.escape(c).replace(r"\,", ",?").replace(r"\ ", r"\s?") + r"(?![\d/]|,\d|\.\d)")
            for i, t in enumerate(turns):
                if pat.search(t['text']) and i not in gap_near:
                    flags.append('turn %d says a look-up figure (%s) outside a scenario' % (i, f))
    stats['think_gaps'] = ngaps
    stats['turns'] = len(turns)
    return {'ok': not errors, 'errors': errors, 'flags': flags, 'stats': stats}


if __name__ == '__main__':
    a = sys.argv[1:]
    res = check(open(a[0]).read(), open(a[1]).read(), json.load(open(a[2])), json.load(open(a[3])) if len(a) > 3 else None)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    sys.exit(0 if res['ok'] else 1)
