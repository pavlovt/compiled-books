#!/usr/bin/env python3
"""Build the interactive quiz page from the course's Markdown.

Usage (from the repository root):
    python books/sveltekit-interview-prep/quiz/build_quiz.py

Collects every quiz in the course as a separate quiz on one page:
- the daily quizzes: the "## Quiz" section of each day chapter, with answers
  from the "Quiz Answer Keys" chapter (matched by day number);
- the final tests: the "Final Tests" chapter, with answers from
  "Final Tests: Answer Key" (matched by test title).
Questions and answers are rendered to HTML with pandoc and written as JSON
into template.html (the __DATA__ placeholder), producing quizzes.html next to
this script.

Question types are detected from the Markdown:
- four options on their own lines (a. / b. / c. / d.)  -> single choice
- four options on one line ("a. x  b. y  c. z  d. w")   -> choose all that apply
- anything else                                         -> open answer
For choice questions the correct letters are read from the start of the
answer item ("b." or "a, b and d.").
"""
import glob, json, os, re, subprocess, sys, textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'src')

FINAL_REVIEW = {1: 'Days 1 and 2', 2: 'Days 3, 4 and 5', 3: 'Days 6 and 7 and the playbook'}


def read(pattern):
    found = glob.glob(os.path.join(SRC, pattern))
    if len(found) != 1:
        sys.exit(f'expected one file matching {pattern}, found {found}')
    return open(found[0], encoding='utf-8').read()


def md2html(md):
    return subprocess.run(['pandoc', '-f', 'markdown-smart', '-t', 'html', '--no-highlight'],
                          input=md, capture_output=True, text=True, encoding='utf-8',
                          check=True).stdout.strip()


def sections(text, heading_re):
    """Split text on level-2 headings matching heading_re; returns [(heading, body)]."""
    parts = re.split(r'^## (' + heading_re + r')$', text, flags=re.M)
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


def questions(qs, ks, where):
    if sorted(qs) != sorted(ks):
        sys.exit(f'{where}: questions {sorted(qs)} do not match answers {sorted(ks)}')
    out = []
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
            m = re.match(r'([a-d])\.', a)
            if not m:
                sys.exit(f'{where} Q{n}: answer does not start with a letter: {a[:40]!r}')
            entry['correct'] = [m.group(1)]
        else:
            stem, opts = q, None
            entry['type'] = 'open'
        entry['q'] = md2html(stem)
        if opts:
            entry['options'] = [md2html(o).removeprefix('<p>').removesuffix('</p>') for o in opts]
        entry['a'] = md2html(a)
        out.append(entry)
    return out


def daily_quizzes():
    keys = {}
    for heading, body in sections(read('*-quiz-answer-keys.md'), r'Day \d+: .+'):
        day = int(re.match(r'Day (\d+)', heading).group(1))
        keys[day] = (heading.split(': ', 1)[1], items(body))
    quizzes = []
    for path in sorted(glob.glob(os.path.join(SRC, '*-day-*.md'))):
        text = open(path, encoding='utf-8').read()
        quiz = re.search(r'^## Quiz[^\n]*\n(.*)', text, re.S | re.M)
        if not quiz:
            continue  # the mock-interview days have no quiz
        day = int(re.match(r'# Day (\d+)', text).group(1))
        topic, answers = keys[day]
        quizzes.append({
            'id': f'day-{day}', 'group': 'Daily quizzes', 'label': f'Day {day}', 'topic': topic,
            'minutes': 15, 'good': 12, 'ok': 9, 'review': f'the Day {day} core notes',
            'questions': questions(items(quiz.group(1)), answers, f'Day {day}'),
        })
    return quizzes


def final_tests():
    keys = dict(sections(read('*-final-tests-answer-key.md'), r'Test \d+: .+'))
    quizzes = []
    for heading, body in sections(read('*-final-tests.md'), r'Test \d+: .+'):
        n = int(re.match(r'Test (\d+)', heading).group(1))
        quizzes.append({
            'id': f'final-{n}', 'group': 'Final tests', 'label': f'Final Test {n}',
            'topic': heading.split(': ', 1)[1], 'minutes': 30, 'good': 20, 'ok': 15,
            'review': f'the core notes for {FINAL_REVIEW.get(n, "the related days")}',
            'questions': questions(items(body), items(keys[heading]), heading),
        })
    return quizzes


def main():
    data = daily_quizzes() + final_tests()
    payload = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    template = open(os.path.join(HERE, 'template.html'), encoding='utf-8').read()
    out = os.path.join(HERE, 'quizzes.html')
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(template.replace('__DATA__', payload))
    for q in data:
        kinds = {k: sum(x['type'] == k for x in q['questions']) for k in ('choice', 'multi', 'open')}
        print(f"{q['label']:13} {q['topic'][:45]:45} {len(q['questions'])} questions {kinds}")
    print('->', os.path.relpath(out))


if __name__ == '__main__':
    main()
