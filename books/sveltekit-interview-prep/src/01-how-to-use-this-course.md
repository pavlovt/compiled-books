# How to Use This Course

This is a nine-day course that prepares you for a live SvelteKit interview with two parts:

1. **Questions.** Conceptual questions on SvelteKit and on Svelte itself (runes, components, reactivity).
2. **Live coding with Claude Code.** While the interviewer watches, you build a component, a unit test for it (in a SvelteKit project this is usually a component test that renders it in a browser) and an end-to-end test.

It is built on the two companion books in this collection, *SvelteKit 3 in Depth* (cited as **Kit**) and *Svelte 5 in Depth* (cited as **Svelte**). A reference such as “Kit 4” means Chapter 4 of the SvelteKit book. The course does not replace the books. It tells you which parts to read, condenses what interviewers ask most, and gives you drills and quizzes.

## The budget: two hours a day

Every day has the same shape, so you never have to decide what to do next:

| Block | Time | What you do |
|---|---|---|
| Read | 45 min | The sections listed under “Read”, in order. Skim anything marked *skim*. |
| Core notes | 20 min | Read the day’s core notes. They are the interview-ready summary of the reading. |
| Hands-on | 40 min | The day’s exercise in your practice project. Type the code; do not paste it. |
| Quiz | 15 min | Answer the quiz *without* looking, then check the answer key at the back of the course. |

If you run short of time, cut the reading first, never the hands-on or the quiz. The core notes are written so that, in an emergency, they alone cover what is most likely to be asked.

## The schedule

The plan assumes you start on Monday 23 November and the interview is in the first days of December. Day 9 is a second mock interview. If the interview is later than that, continue with the optional Days 10 and 11, which work through the remaining final tests and example projects.

| Day | Date | Topic | Main reading |
|---|---|---|---|
| 1 | Mon 23 Nov | Svelte 5 core: runes, reactivity, props | Svelte 1, 3, 4, 7 |
| 2 | Tue 24 Nov | Svelte 5 components: template, snippets, bindings, context, SSR | Svelte 6, 7, 8, 12, 14 |
| 3 | Wed 25 Nov | SvelteKit foundations: architecture, project, routing | Kit 1, 3 (2 skim) |
| 4 | Thu 26 Nov | Data: `load`, invalidation, streaming, form actions | Kit 4, 5, 6 |
| 5 | Fri 27 Nov | Hooks, errors, page options, state, environment | Kit 9, 10, 11, 12, 13 |
| 6 | Sat 28 Nov | **Testing**: Vitest, browser-mode component tests, Playwright | Kit 19 (part 2), Svelte 16 |
| 7 | Sun 29 Nov | SvelteKit 3 specials and breadth: remote functions, auth, security, performance, deployment, migration | Kit 7, 8, 14–18, 20 (skims) |
| 8 | Mon 30 Nov | Mock Interview 1: Final Test 1, questions aloud, Example Project 1 with Claude Code | Course chapters at the back |
| 9 | Tue 1 Dec | Mock Interview 2: questions with follow-ups, a code review, live coding in an existing project with a change request | Day 9 chapter |
| 10 | *optional* | Final Test 2 and Example Project 2 | |
| 11 | *optional* | Final Test 3 and Example Project 3 | |

If the interview is on 1 December, do Parts 1 and 2 of Mock Interview 2 (50 minutes) on the evening of Day 8.

Day 6 is the most important day for the live-coding part, and the live-coding playbook (near the back of the course) is the most important chapter. If anything slips, protect those.

## What is at the back of the course

| Chapter | Use it for |
|---|---|
| The Live-Coding Playbook | The routine, a `CLAUDE.md`, the review checklist and six drills (three with verified solutions) |
| Interview Question Bank | Short model answers to the questions asked most often; rehearse them aloud |
| Example Projects | Three small SvelteKit apps to build with Claude Code, each with a spec, a prompt sequence, test requirements and a self-review rubric |
| Final Tests | Three cumulative tests: Svelte 5, SvelteKit, and testing plus SvelteKit 3 |
| Quiz Answer Keys and Final Tests: Answer Key | The answers, with short explanations |

## Versions, and why they matter in the interview

Everything here targets **SvelteKit 3** (3.0 shipped on 1 October 2026; the practice project in this course was scaffolded with 3.2) and **Svelte 5.57**. The test stack was verified on 23 November 2026 by scaffolding a fresh project with `sv` 1.7.0 and running the drill solutions and test examples in Day 6 and the playbook: Vitest 5.1, `vitest-browser-svelte` 3.1, `@vitest/browser-playwright` 5.1 and Playwright 1.65. (The example projects have no reference solutions, so there was nothing to run for them.)

Many companies still run SvelteKit 2 code. Be ready to say what changed, because “what is new in SvelteKit 3?” is a natural opening question and old habits (`$lib`, `$app/stores`, `svelte.config.js`) are what an interviewer will notice in your live code. Day 3 has a table of the 2-versus-3 changes, and Day 7 covers the migration itself.

## The practice project

On Day 1 you scaffold one project and keep adding to it all week. Every exercise in the course lives there, so by Day 8 you have a working reference project you have typed yourself:

```bash
npx sv create --template minimal --types ts --add vitest="usages:unit,component" playwright="demo:yes" --install npm practice
cd practice
npx playwright install chromium
```

Check what the scaffold gave you:

```bash
npm run dev          # http://localhost:5173
npx vitest --run     # unit + component tests
npx playwright test  # end-to-end tests against a production build
npm run check        # svelte-check: types and Svelte diagnostics
```

On Windows, run these in PowerShell or the VS Code terminal; they are the same commands.

## How to use the quizzes

Days 1 to 7 each end with 15 questions: short answers, multiple choice, “what does this code do?” and “find the bug”. Write your answers down, then check them against “Quiz Answer Keys” at the back. Mark the questions you got wrong; before the interview (on Day 10 if you have it, otherwise on the evening before) you retest only those.

The same quizzes, and the three final tests, also exist as an interactive web page that times you, grades multiple-choice answers and keeps track of what you missed. It is `books/sveltekit-interview-prep/quiz/quizzes.html` in the repository this course comes from; open it in any browser.

Scoring guide: 12+ correct out of 15 is interview-ready for that topic. Below 9 means re-read that day’s core notes before the next day starts.

## What the interview probably looks like

Interviewers for a SvelteKit role tend to ask about the same clusters. In rough order of frequency:

1. Runes: `$state`, `$derived`, `$effect`, `$props`, and *when not to use `$effect`*.
2. `load`: universal versus server, where code runs, what is serialised, and data flow into `data`.
3. Form actions and progressive enhancement (`use:enhance`).
4. Routing: dynamic parameters, layouts, groups, `+server` endpoints.
5. SSR and hydration: what runs where, and the “shared server state” trap.
6. Hooks (`handle`, `locals`) and error handling.
7. Testing strategy, and how you would test a component and a page.
8. What is new in Svelte 5 and SvelteKit 3.

The live coding is usually a small, self-contained component (counter, todo list, search filter, accordion, star rating, modal) with one or two tests at each level. The live-coding playbook gives you a fixed routine for it.
