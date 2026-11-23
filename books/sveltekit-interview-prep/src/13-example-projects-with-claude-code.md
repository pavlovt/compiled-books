# Example Projects with Claude Code

Three small but complete SvelteKit applications to build with Claude Code. They are bigger than the drills: each combines a reusable component, server logic, routing and all three levels of tests, which is the shape of a realistic interview task, plus a bit more.

Each project lists:

- **Spec and acceptance criteria.** What “done” means. Turn these into test cases.
- **Suggested structure.** Where things go. You may deviate, but have a reason.
- **Session plan.** The sequence of prompts to give Claude Code. Write each prompt yourself from the outline; do not paste the outline.
- **Tests required.** The minimum test set, by level.
- **Review hotspots.** Where generated code tends to go wrong for this project.
- **Self-review rubric.** Score yourself at the end.

| Project | Time box | Main topics |
|---|---|---|
| 1. Reading List | 60–75 min | Component with props and callbacks, server `load`, named form actions, `use:enhance`, URL state, no-JS e2e |
| 2. Recipe Browser | 75 min | Routing with a matcher, `+server` JSON endpoint, universal `load` with `fetch`, `error(404)`, streaming, a debounced search component, a `.svelte.ts` class |
| 3. Team Board with Login | 75–90 min | Cookies, `handle` and `locals`, protected routes, login/logout actions, a keyboard-accessible board component, `handleError`, auth e2e tests |

## How to run each session

1. Start from a fresh scaffold (or a new branch of your practice project):

   ```bash
   npx sv create --template minimal --types ts --add vitest="usages:unit,component" playwright="demo:yes" --install npm reading-list
   cd reading-list
   ```

2. Add the `CLAUDE.md` from the playbook, and start `claude` in the project folder.
3. Commit after each green step (`git init` first). If Claude Code takes a wrong turn, you can return to the last good commit.
4. Keep a timer running and talk out loud, as in the interview.
5. At the end, run `npx vitest --run`, `npx playwright test` and `npm run check`, then fill in the rubric.

Data storage: all three projects keep data in memory in a server module (`src/lib/server/…`). That is fine for an exercise, but say in the session that module state is shared by all users and lost on restart, and name what you would use in production.

## Project 1: Reading List

A personal reading list where you add books, mark them as read, delete them and filter by status.

### Spec and acceptance criteria

1. `/books` lists books (title, author, status “to read” or “read”), loaded in a server `load`.
2. An “Add book” form with “Title” (required) and “Author” (required). Invalid submissions show field errors and keep the typed values. Valid submissions add the book and clear the form.
3. Each book has a “Mark as read”/“Mark as unread” button and a “Delete” button, implemented as **named form actions** (`?/toggle`, `?/delete`) with the book id in a hidden input.
4. Filter links “All”, “To read”, “Read” set `?status=` in the URL; the server `load` filters by it, so a reload keeps the filter. The current filter link has `aria-current="page"`.
5. A count line: “3 books, 1 read”.
6. Everything works **without JavaScript**, and is enhanced with `use:enhance` when JavaScript is available.
7. A reusable `BookCard.svelte` component renders one book. It receives the book as a prop; the page passes the two action forms in as an `actions` snippet, which the card renders with `{@render actions?.()}`.

### Suggested structure

```text
src/lib/server/books.ts                  # in-memory store + validateBook()
src/lib/server/books.spec.ts
src/lib/components/BookCard.svelte
src/lib/components/BookCard.svelte.spec.ts
src/routes/books/+page.server.ts         # load (reads ?status), actions: add, toggle, delete
src/routes/books/+page.svelte
src/routes/books/page.server.spec.ts
src/routes/books/books.e2e.ts
```

### Session plan

1. **Clarify and write criteria** (5 min). Write the seven criteria above as a checklist in a comment at the top of `books.e2e.ts`, or in a `TASK.md`.
2. **Server logic** (8 min). Prompt: the in-memory store with `list(status?)`, `add`, `toggle`, `remove`, and a pure `validateBook(title, author)` that returns an errors object. Ask for the Node unit test of `validateBook` and of `list` filtering at the same time. Run it.
3. **BookCard** (10 min). Prompt: props `book` and an optional `actions` snippet; `<article>` with the title as a heading; status text. Then ask for its component test (renders title, author and status; renders the snippet when given). Run it.
4. **Page and actions** (15 min). Prompt: `+page.server.ts` with the load and the three named actions using `fail(400, …)` for validation; `+page.svelte` with `use:enhance` on every form, the filter links built from the URL, and the count line. Try it in the browser, with and without JavaScript.
5. **Action tests** (8 min). Prompt for `page.server.spec.ts`: `add` fails with 400 and echoes the input on invalid data; `add` then `load` returns the new book; `delete` removes it.
6. **E2E** (12 min). Prompt for `books.e2e.ts`: add a book; mark it as read and see the count change; filter by “Read” and check the URL and the list; a `javaScriptEnabled: false` test that adds a book.
7. **Verify and wrap up** (5 min).

### Tests required

| Level | Minimum |
|---|---|
| Unit (Node) | `validateBook` valid and invalid; `list('read')` filtering; the `add` action’s failure shape; add-then-load |
| Component | `BookCard`: renders the book; renders the `actions` snippet |
| E2E | Add; toggle with count change; filter via URL; add without JavaScript |

### Review hotspots

- Hidden inputs for the id must be inside **each** form, and actions must check that the id exists (return `fail(404)` otherwise).
- The `form` prop holds the result of whichever action ran last, so the add form must not show errors from a failed toggle or delete. Return a marker from each action (for example `fail(400, { action: 'add', values, errors })`) and show errors only when `form?.action === 'add'`.
- The filter must come from `url.searchParams.get('status')` in the **load**, not from client-side state, so it works with SSR and reloads.
- A route cannot mix a `default` action with named actions.
- E2E: the same book title on several tests can collide because the in-memory store persists across tests. Use unique titles per test (`` `Book ${Date.now()}` ``).
- Check for Svelte 4 slot syntax in `BookCard` (should be a snippet prop rendered with `{@render actions?.()}`).

### Stretch goals

- Optimistic UI for toggling: in the `use:enhance` callback, flip the status before the response and roll back on failure.
- Rewrite the add form as a remote `form` behind the experimental flags, and compare the code.

## Project 2: Recipe Browser

A read-only recipe site with search, detail pages, related recipes and browser-side favourites.

### Spec and acceptance criteria

1. A JSON endpoint `GET /api/recipes?q=` (`+server.ts`) returns recipes whose title contains `q` (case-insensitive) from an in-memory array of about ten recipes (`slug`, `title`, `minutes`, `tags`, `ingredients`).
2. `/recipes` uses a **universal** `load` (`+page.ts`) that calls the endpoint with the provided `fetch`, passing `q` from the URL.
3. A `SearchBox.svelte` component: a labelled input that calls an `onsearch(query)` callback **debounced by 300 ms**. The page passes a callback that navigates to `?q=…` with `goto(…, { replace: true, reset: false })`. A reload keeps the search.
4. `/recipes/[slug=slug]` shows one recipe. A `slug` matcher in `src/params.ts` accepts only `a-z`, digits and hyphens. An unknown but valid slug gives a **404** with a custom `+error.svelte` (“Recipe not found”).
5. The detail page’s **server** `load` awaits the recipe and **streams** “related recipes” (same tag) as an un-awaited promise, rendered with `{#await}` and a loading text.
6. A favourites feature: a `Favourites` class in `src/lib/favourites.svelte.ts` (a `SvelteSet` of slugs or a `$state` array, with `toggle`, `has`, `count`) persisted to `localStorage` **only in the browser**. A heart button with `aria-pressed` on cards and on the detail page; a “Favourites (N)” count in the layout.

### Suggested structure

```text
src/lib/server/recipes.ts                 # data + search() + bySlug() + related()
src/lib/server/recipes.spec.ts
src/lib/favourites.svelte.ts
src/lib/favourites.svelte.spec.ts
src/lib/components/SearchBox.svelte
src/lib/components/SearchBox.svelte.spec.ts
src/params.ts
src/routes/api/recipes/+server.ts
src/routes/api/recipes/server.spec.ts
src/routes/recipes/+page.ts
src/routes/recipes/+page.svelte
src/routes/recipes/[slug=slug]/+page.server.ts
src/routes/recipes/[slug=slug]/+page.svelte
src/routes/recipes/+error.svelte
src/routes/recipes/recipes.e2e.ts
```

### Session plan

1. **Criteria** (5 min).
2. **Data and endpoint** (10 min). `recipes.ts` with pure functions plus a unit test; the `+server.ts` handler returning `Response.json(...)`; a Node test that calls `GET` with a `URL` containing `?q=`.
3. **Matcher and routes** (12 min). `src/params.ts` with `defineParams`; the list page with a universal load; the detail page with a server load that throws `error(404, 'Recipe not found')` and streams `related`. Check `/recipes/does-not-exist` and `/recipes/Bad_Slug!` in the browser, and explain the difference (a 404 from your load versus no route match).
4. **SearchBox** (12 min). Prompt for the component with the debounce implemented with a timer cleared on each keystroke (and on destroy). Ask for a component test that types and asserts `onsearch` is called **once** with the final value; it can use `vi.useFakeTimers()` or a small wait with `expect.poll`. Read the test carefully: it must fail if the debounce is removed.
5. **Favourites** (12 min). Prompt for the class, with persistence guarded by `browser` from `$app/env` (or done in an effect/`onMount`), never at module load during SSR. Unit test `toggle`/`has`/`count` in a `.svelte.spec.ts` file.
6. **E2E** (15 min). Search narrows the list and updates the URL; reload keeps the results; open a recipe; related recipes appear; unknown slug shows “Recipe not found” with a 404 status (`const response = await page.goto(...)`; `expect(response?.status()).toBe(404)`); favouriting updates the count and survives a reload.
7. **Verify and wrap up** (5 min).

### Tests required

| Level | Minimum |
|---|---|
| Unit (Node) | `search()` case-insensitivity; `GET /api/recipes?q=` handler; the matcher accepts and rejects |
| Unit (browser project) | `Favourites` toggle, has, count |
| Component | `SearchBox` debounce: one call with the final value |
| E2E | Search and URL; reload; detail page; streamed related recipes; 404 page and status; favourites persist |

### Review hotspots

- The universal load must use the `fetch` **from the event**, with a relative URL (`/api/recipes?q=...`). The global `fetch` with a relative URL fails during SSR.
- `localStorage` access at module level or in the class constructor breaks SSR. Look for it.
- The search page reads `q` from `url.searchParams` in the load, which makes it re-run when `q` changes. Check that the input shows the current `q` after a reload (initialise it from `page.url` or `data`).
- The streamed promise needs a `.catch`, and SEO-relevant content (the recipe itself) must be awaited, not streamed.
- A matcher must be synchronous and return a value or `undefined`, not a boolean (the SvelteKit 2 contract was boolean).
- Debounce tests that use real timers with long sleeps are slow and flaky; prefer fake timers or `expect.poll`.

### Stretch goals

- Prerender the detail pages (`export const prerender = true` plus `entries()`), and explain why the search page cannot be prerendered.
- Add `<svelte:head>` titles per page and an e2e assertion with `toHaveTitle`.

## Project 3: Team Board with Login

A small task board for logged-in users: three columns (To do, Doing, Done), tasks you can move between columns with buttons or the keyboard.

### Spec and acceptance criteria

1. **Login.** `/login` with “Email” and “Password” and a default form action. Two hard-coded users in `src/lib/server/users.ts` (store a hash or simply compare in this exercise, but say what you would do in production). Wrong credentials show one generic error (“Invalid email or password”). Success creates a random session id, stores it in an in-memory session map, sets a `sid` cookie (`httpOnly`, `sameSite: 'lax'`, `path: '/'`, `secure` outside dev) and redirects (303) to `/board` or to a validated `?next=` path.
2. **Session.** `src/hooks.server.ts` reads the cookie and sets `event.locals.user` (typed in `app.d.ts`). A second `handle` in a `sequence` redirects anonymous users from `/board` and its sub-paths to `/login?next=…`.
3. **Defence in depth.** The board’s server `load` and its actions also check `locals.user` (a `requireUser()` helper using `getRequestEvent()` from `$app/server`).
4. **Logout.** A POST form action `?/logout` deletes the session and the cookie and redirects to `/login`.
5. **Board.** A `TaskBoard.svelte` component receives `tasks` (`{ id, title, column }[]`) and an `onmove(id, column)` callback. Each column is a labelled list (`aria-label`), each task has “Move left”/“Move right” buttons (disabled at the edges) with accessible names including the task title. When a task button has focus, ArrowLeft/ArrowRight also move it.
6. The board page wires `onmove` to a `?/move` action through a hidden `<form method="POST" action="?/move" use:enhance>` with `id` and `column` inputs: `onmove` fills the inputs and calls `form.requestSubmit()`. `use:enhance` re-runs the load afterwards, so the board updates. Tasks are per user.
7. **Errors.** `handleError` in `hooks.server.ts` logs unexpected errors with a generated `errorId` and returns `{ message: 'Something went wrong', errorId }`; extend `App.Error` with `errorId`. The `+error.svelte` page shows the id.

### Suggested structure

```text
src/app.d.ts                               # App.Locals { user }, App.Error { errorId? }
src/hooks.server.ts                        # sequence(session, guard), handleError
src/hooks.server.spec.ts
src/lib/server/users.ts
src/lib/server/sessions.ts
src/lib/server/auth.ts                     # requireUser()
src/lib/server/auth.spec.ts                # mocks $app/server
src/lib/server/tasks.ts
src/lib/components/TaskBoard.svelte
src/lib/components/TaskBoard.svelte.spec.ts
src/routes/login/+page.server.ts
src/routes/login/+page.svelte
src/routes/board/+page.server.ts           # load, actions: move, logout
src/routes/board/+page.svelte
src/routes/+error.svelte
src/routes/board/board.e2e.ts
```

### Session plan

1. **Criteria and security notes** (5 min). Say out loud which guard does what, and why the layout is not the place for it.
2. **Auth core** (15 min). Users, sessions, `requireUser()`. Ask for `auth.spec.ts` that mocks `$app/server` and checks the redirect with `isRedirect` and the returned user.
3. **Hooks** (12 min). `session` and `guard` handles combined with `sequence`, plus `handleError`. Ask for `hooks.server.spec.ts` that calls `handle` with a stub `resolve` and checks: a valid cookie sets `locals.user`; an anonymous request to `/board` gets a redirect; `/login` passes through.
4. **Login and logout** (12 min). Login page and action; logout action. Try it in the browser and inspect the cookie in the dev tools.
5. **TaskBoard** (15 min). The component first, with its component test: renders three labelled lists; clicking “Move right” on a task calls `onmove(id, 'doing')`; the left button is disabled in “To do”; ArrowRight on a focused task calls `onmove`.
6. **Board page** (10 min). Load, `move` action with validation (column must be one of three, task must belong to the user), wiring to the component.
7. **E2E** (12 min). Anonymous `/board` redirects to `/login?next=%2Fboard`; wrong password shows the generic error; login lands on `/board`; moving a task updates the column after reload; logout returns to `/login` and `/board` redirects again. Optional: a login `setup` project that saves `storageState` and is reused by the board tests.
8. **Verify and wrap up** (5 min).

### Tests required

| Level | Minimum |
|---|---|
| Unit (Node) | `requireUser` with mocked `$app/server`; `handle` with stub `resolve` (three cases); the `move` action rejects an invalid column |
| Component | `TaskBoard`: columns, move buttons, disabled edges, keyboard |
| E2E | Redirect when anonymous; failed login; login; move persists; logout |

### Review hotspots

- **Open redirect:** `?next=` must be a relative path starting with a single `/` (reject `//evil.com` and absolute URLs). Ask Claude to add a test for it.
- The guard must use `event.url.pathname` and cover sub-paths; it must not break `/login` or static assets.
- After login, `handle` has already run for this request, so set `event.locals.user` in the action or redirect (redirecting is simpler).
- Cookies: `httpOnly`, `sameSite: 'lax'`, `path: '/'`. The generated code sometimes forgets `path`, which makes the cookie invisible on other routes.
- Do not return the user’s password hash or the session id from any load.
- Keyboard handling should be on the task’s buttons (`onkeydown`), not on a `div` with `tabindex` (the a11y warnings will tell you).
- The `move` action must check that the task belongs to `locals.user`: otherwise any user can move any task by id.
- If the generated code posts to the action with a bare `fetch`, reject it: without SvelteKit’s own request headers the response is the page’s HTML, not an action result. The enhanced hidden form is simpler. If it calls `invalidateAll()`, note that it is deprecated in SvelteKit 3 (`refreshAll()`), and unnecessary here because `use:enhance` already refreshes.

### Stretch goals

- Rewrite the board’s data with remote functions (`query` for tasks, `command` for move), with authorisation inside each function, and explain why the `handle` guard does not cover them.
- Add an optimistic move that rolls back on failure.

## Self-review rubric

Score each line 0 (no), 1 (partly) or 2 (yes) for every project. 16 or more out of 20 is interview-ready.

| # | Criterion |
|---|---|
| 1 | I wrote the acceptance criteria before the first prompt |
| 2 | Every prompt named the files, the conventions and what not to do yet |
| 3 | I reviewed every diff and rejected or corrected at least one thing, with a reason |
| 4 | No Svelte 4 or SvelteKit 2 syntax survived (`export let`, `on:`, slots, `$lib`, `$app/stores`) |
| 5 | Markup is accessible; tests find elements by role and name |
| 6 | Each acceptance criterion is covered by at least one test |
| 7 | I broke the code once to prove a test fails |
| 8 | Unit, component and e2e tests all pass; `npm run check` is clean |
| 9 | I can explain every line, including the generated ones |
| 10 | I finished within the time box, or I knew exactly what was left and said so |
