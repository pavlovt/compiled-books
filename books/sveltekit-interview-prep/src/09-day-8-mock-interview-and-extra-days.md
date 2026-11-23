# Day 8: Mock Interview (and Optional Days 9–10)

**Goal for today:** rehearse both halves of the interview under time pressure, and find your remaining weak spots while there is still time to fix them.

## Day 8 plan (2 hours)

| Time | Block | What to do |
|---|---|---|
| 0:00–0:30 | **Final Test 1** | Do “Final Tests”, Test 1, closed book, 30 minutes. Check it against the answer key. |
| 0:30–0:50 | **Questions aloud** | Pick 12 random questions from the question bank and answer each **out loud** in under a minute, as if to an interviewer. Record yourself if you can; listen back to two answers. |
| 0:50–1:50 | **Mock live coding** | Example Project 1 (“Example Projects”), with Claude Code, following the 45-minute routine of the playbook. Stop at 60 minutes wherever you are. |
| 1:50–2:00 | **Review** | Fill in the project’s self-review rubric. Write down your three weakest topics. |

Rules for the mock live coding, to make it realistic:

- Talk out loud the whole time, as if someone were listening.
- Write the acceptance criteria before the first prompt.
- Review every diff before accepting it, using the playbook’s checklist.
- Do not open the reference solutions in the playbook.

## If the interview is later: optional Days 9 and 10

If you have more days before the interview, use the same two-hour shape:

| Day | Block 1 (30 min) | Block 2 (75 min) | Block 3 (15 min) |
|---|---|---|---|
| 9 | Final Test 2 | Example Project 2 | Retest every daily-quiz question you got wrong |
| 10 | Final Test 3 | Example Project 3 | Re-read the core notes of your two weakest days |

If you have even more time, do Drills 4–6 from the playbook (45 minutes each, timed), and the final tests in the two companion books: *SvelteKit 3 in Depth*, Tests 1–3, and *Svelte 5 in Depth*, Tests 1–2. They are harder than this course’s tests; aim for 70%.

## The evening before the interview

Do not learn anything new. Instead:

1. Run the environment checklist in the playbook on the machine you will use.
2. Re-read the core notes of Day 1 (runes) and Day 6 (testing), and the playbook’s review checklist.
3. Rehearse three short stories you can tell when asked about experience: a bug you tracked down, a performance or testing improvement, and a design decision you would make differently today.
4. Prepare two or three questions for them, for example: which SvelteKit version and adapter they run, whether they use remote functions, and how their test pyramid looks.

## Answer frameworks for open questions

Interviewers often ask open “how would you…” questions. A structure keeps you from rambling:

1. **Clarify** the context in one sentence (“For a logged-in dashboard behind a proxy…”).
2. **State the default** SvelteKit approach (“I would load it in a server `load`…”).
3. **Give the reason** (“…because it needs the session cookie and the result is serialised to the page anyway”).
4. **Name the trade-off or pitfall** (“…the catch is that layout loads don’t protect page loads, so I’d also check in `handle`”).
5. **Say how you would test it** (“…a unit test of the load with a fake `locals`, and an e2e test that an anonymous user is redirected”).

Step 5 is what separates good answers from very good ones in an interview that includes a testing exercise.
