#!/usr/bin/env python3
"""Build the interactive final-tests quiz page from the course's Markdown.

Usage (from the repository root):
    python books/sveltekit-interview-prep/quiz/build_quiz.py

Reads the "Final Tests" chapter and its answer key from ../src, renders
each question and answer to HTML with pandoc, and writes final-tests.html
next to this script by filling the __DATA__ placeholder in template.html.

Question types are detected from the Markdown:
- four options on their own lines (a. / b. / c. / d.)  -> single choice
- four options on one line ("a. x  b. y  c. z  d. w")   -> choose all that apply
- anything else                                         -> open answer
For choice questions the correct letters are read from the start of the
answer-key item ("b." or "a, b and d.").
"""
import glob, json, os, re, subprocess, sys, textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'src')


def chapter(pattern):
    found = glob.glob(os.path.join(SRC, pattern))
    if len(found) != 1:
        sys.exit(f'expected one file matching {pattern}, found {found}')
    return open(found[0], encoding='utf-8').read()


def md2html(md):
    return subprocess.run(['pandoc', '-f', 'markdown-smart', '-t', 'html', '--no-highlight'],
                          input=md, capture_output=True, text=True, encoding='utf-8',
                          check=True).stdout.strip()


def split_tests(text):
    parts = re.split(r'^## (Test \d+: .+)$', text, flags=re.M)
    return [(parts[i], parts[i + 1]) for i in range(1, len(parts), 2)]


def items(body):
    """Split a top-level numbered list into {n: markdown}, dedenting continuation lines."""
    out, cur = {}, None
    for line in body.split('\n'):
        m = re.match(r'^(\d+)\.(?:\s(.*))?$', line)
        if m:
            cur = [m.group(2) or '']
            out[int(m.group(1))] = cur
        elif cur is not None:
            cur.append(line)
    return {k: (v[0] + '\n' + textwrap.dedent('\n'.join(v[1:]))).strip() for k, v in out.items()}


def build():
    tests = split_tests(chapter('*-final-tests.md'))
    keys = dict(split_tests(chapter('*-final-tests-answer-key.md')))
    data = []
    for title, body in tests:
        qs, ks = items(body), items(keys[title])
        if sorted(qs) != sorted(ks):
            sys.exit(f'{title}: questions {sorted(qs)} do not match answers {sorted(ks)}')
        questions = []
        for n in sorted(qs):
            q, a = qs[n], ks[n]
            entry = {'n': n}
            inline = re.search(r'^(.*?)\n+\s*a\. (.+?)\s{2,}b\. (.+?)\s{2,}c\. (.+?)\s{2,}d\. (.+)$', q, re.S)
            block = re.findall(r'^([a-d])\.\s+(.+)$', q, re.M)
            if inline:
                stem, opts = inline.group(1), list(inline.groups()[1:])
                entry['type'] = 'multi'
                entry['correct'] = sorted(set(re.findall(r'\b([a-d])\b', a.split('.')[0])))
            elif len(block) == 4:
                stem, opts = re.split(r'\n\s*a\.\s', q)[0], [o for _, o in block]
                entry['type'] = 'choice'
                entry['correct'] = [re.match(r'([a-d])\.', a).group(1)]
            else:
                stem, opts = q, None
                entry['type'] = 'open'
            entry['q'] = md2html(stem)
            if opts:
                entry['options'] = [md2html(o).removeprefix('<p>').removesuffix('</p>') for o in opts]
            entry['a'] = md2html(a)
            questions.append(entry)
        data.append({'title': title, 'questions': questions})
    return data


def main():
    data = build()
    payload = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    template = open(os.path.join(HERE, 'template.html'), encoding='utf-8').read()
    out = os.path.join(HERE, 'final-tests.html')
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(template.replace('__DATA__', payload))
    for t in data:
        kinds = {k: sum(q['type'] == k for q in t['questions']) for k in ('choice', 'multi', 'open')}
        print(f"{t['title']}: {len(t['questions'])} questions {kinds}")
    print('->', os.path.relpath(out))


if __name__ == '__main__':
    main()
