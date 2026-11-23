# Compiled books

Markdown sources for books compiled with Claude, and the script that builds them into EPUB. Every book lives in its own folder under `books/` and is built the same way, so a new book only needs a new folder.

| Folder | Book | Output |
|---|---|---|
| `books/svelte-5-in-depth/` | *Svelte 5 in Depth*: runes, the compiler and reactivity internals | `Svelte-5-in-Depth.epub` |
| `books/sveltekit-3-in-depth/` | *SvelteKit 3 in Depth*: routing, data, remote functions and deployment | `SvelteKit-3-in-Depth.epub` |
| `books/astro-7-in-depth/` | *Astro 7 in Depth*: islands, content and the server with Svelte 5 | `Astro-7-in-Depth-with-Svelte.epub` |
| `books/sveltekit-interview-prep/` | *SvelteKit Interview Prep*: a nine-day course in Svelte 5, SvelteKit 3 and testing, two hours a day | `SvelteKit-Interview-Prep.epub` |
| `books/living-well-with-type-2-diabetes/` | *Living Well with Type 2 Diabetes*: a practical guide to the things that matter most | `Living-Well-with-Type-2-Diabetes.epub` |

Each of the three *in Depth* books has 20 chapters, a preface, answers to the chapter review questions, six final tests and their answer key. *SvelteKit Interview Prep* is a study course built on the Svelte 5 and SvelteKit 3 books: seven daily lessons with quizzes, two mock interviews, a live-coding playbook with tested drills, three example projects to build with Claude Code, three final tests and answer keys.

## Layout

```
build.py                 builds the EPUBs into dist/
style.css                shared stylesheet for every book
fonts/                   Source Sans 3, embedded in every EPUB (SIL OFL, see fonts/LICENSE.txt)
books/<name>/meta.yaml   title page, EPUB metadata, output file name
books/<name>/cover.png   cover image (optional)
books/<name>/src/NN-*.md one file per chapter, test or answer key
dist/                    build output (not committed)
```

The two-digit prefix sets a file's position in the book; it is the build order, not the chapter number. Every file starts with a `# ` heading, and each `# ` heading becomes one EPUB chapter. The table of contents shows `#` and `##` headings.

## Building

Requires [pandoc](https://pandoc.org/installing.html) 2.9 or later and Python 3.

```
python build.py                       # every book
python build.py svelte-5-in-depth     # one or more books, by folder name
python build.py --list                # list the books
```

Long code lines are hard-wrapped at 62 characters after pandoc runs, because some readers (SumatraPDF among them) cut off code that does not fit the page.

### The interview-prep quiz page

`books/sveltekit-interview-prep/quiz/` holds one interactive page with every quiz in the course, each selectable on its own: the seven daily quizzes and the three final tests. It has `template.html` (the page), `build_quiz.py` (reads the `## Quiz` section of each day chapter, the Final Tests chapter and both answer-key chapters, renders them with pandoc and fills the template) and the generated `quizzes.html`, which opens directly in a browser. It is also served by GitHub Pages at <https://pavlovt.github.io/compiled-books/books/sveltekit-interview-prep/quiz/quizzes.html> (the repository root is published from `main`; `.nojekyll` keeps Pages from processing the files), so a pushed change goes live a minute or two later. After editing a quiz or an answer key, regenerate it:

```
python books/sveltekit-interview-prep/quiz/build_quiz.py
```

`build.py` ignores this folder; it only reads `meta.yaml` and `src/`.

## Adding a book

1. Create `books/<name>/` with a `meta.yaml`:

   ```yaml
   ---
   title: Book Title
   subtitle: One-line subtitle
   author: Claude
   date: 2026-11
   lang: en-US
   rights: For personal study use
   output: Book-Title.epub
   ---
   ```

   Add `identifier: urn:uuid:...` to keep the same book identity across rebuilds; without it pandoc makes a new one each time.
2. Optionally add `books/<name>/cover.png`.
3. Put the chapters in `books/<name>/src/` as `01-preface.md`, `02-<chapter-slug>.md`, ... Each file starts with `# Title`.
4. Run `python build.py <name>`.

## Markdown conventions

- Code blocks are fenced with a language (`ts`, `js`, `html`, `bash`, ...); `text` for plain output.
- Tables are pipe tables.
- Typographic quotes and dashes are written as the characters themselves; the build reads Markdown with `-smart`, so straight quotes stay straight.
