# Day 9: Mock Interview 2

**Goal for today:** a second full rehearsal in a different interview style. Mock Interview 1 (Day 8) was a test plus a greenfield project. This one simulates an interviewer who digs into “why” with follow-up questions, asks you to review someone else’s code, and has you **extend an existing codebase**, then changes the requirements halfway through. All four are common in real SvelteKit interviews.

Do it on Tuesday 1 December, or on the last free day before the interview. If the interview is on 1 December, do Part 1 and Part 2 on the evening of Day 8 instead (50 minutes).

## The plan (2 hours)

| Time | Part | Format |
|---|---|---|
| 0:00–0:35 | **1. Questions with follow-ups** | 12 questions, answered aloud. Each has follow-ups; answer those too. |
| 0:35–0:50 | **2. Code review** | Find the problems in a SvelteKit page that a colleague wrote. |
| 0:50–1:45 | **3. Live coding in an existing project** | Add pagination to your practice project with Claude Code, then handle a change request. |
| 1:45–2:00 | **4. Debrief** | Score yourself; compare with Mock 1; pick what to revise. |

Do not read the answer notes at the end of this chapter until you have finished Parts 1 and 2.

## Part 1: Questions with follow-ups (35 minutes)

Rules: answer each question **out loud**, in under 90 seconds, then the follow-ups in under 45 seconds each. If you can, record yourself and listen to two answers afterwards. Use the answer framework from Day 8: context, default approach, reason, pitfall, how you would test it. Give yourself a mark per question (2 = complete and confident, 1 = partly, 0 = stuck), then check the answer notes.

1. **“Walk me through what happens when a user clicks a link to `/products/42` in a SvelteKit app that is already loaded.”**
   - Follow-up: what changes if the user hovered over the link first?
   - Follow-up: which `load` functions run, and where?

2. **“We have a component that copies a prop into `$state` and it doesn’t update when the parent changes. Why, and what are the fixes?”**
   - Follow-up: when *is* copying a prop into state correct?

3. **“Explain `$effect`. Give me an example where it is the right tool and one where it is the wrong one.”**
   - Follow-up: how would you test a component that has an effect?

4. **“A teammate wants to store the logged-in user in a module-level `$state` in `src/lib/user.svelte.ts`. What do you tell them?”**
   - Follow-up: what would you use instead, on the server and on the client?

5. **“How do you decide between a form action, a `+server` endpoint and a remote function for a ‘create comment’ feature?”**
   - Follow-up: which of the three work without JavaScript?

6. **“Our dashboard is slow on navigation. Network tab shows three sequential requests. What do you look for?”**
   - Follow-up: what does `await parent()` have to do with it?

7. **“How is authorisation enforced in your SvelteKit apps?”**
   - Follow-up: why is a check in `+layout.server.ts` not enough?
   - Follow-up: does your answer change for remote functions?

8. **“What does `use:enhance` give you over a plain form, and what changed about it in SvelteKit 3?”**
   - Follow-up: how do you keep the user’s input when validation fails?

9. **“A page shows a hydration mismatch warning in production. How do you investigate?”**
   - Follow-up: name three typical causes.

10. **“How would you structure tests for a page with a search box, a list loaded from the server and a ‘delete’ action?”**
    - Follow-up: which of those tests runs in a real browser, and why?

11. **“You use Claude Code at work. How do you make sure what it writes is correct and current?”**
    - Follow-up: give an example of something you would reject in a generated Svelte component.

12. **“We are still on SvelteKit 2. What would the upgrade to 3 involve, and what would you test after it?”**
    - Follow-up: which change is most likely to break things silently?

## Part 2: Code review (15 minutes)

A colleague opened a pull request for a “team members” page. List every problem you can find, how severe it is, and the fix. There are at least ten. Write your list before reading the notes.

```ts
// src/routes/team/+page.server.ts
import { db } from '$lib/server/db';
import { error } from '@sveltejs/kit';

let cachedMembers = null;

export const load = async ({ locals, url }) => {
	try {
		if (!cachedMembers) cachedMembers = await db.members.findAll();
		const q = url.searchParams.get('q') ?? '';
		return {
			members: cachedMembers.filter((m) => m.name.includes(q)),
			viewer: locals.user
		};
	} catch (e) {
		error(500, e.message);
	}
};

export const actions = {
	remove: async ({ request }) => {
		const data = await request.formData();
		await db.members.delete(data.get('id'));
		cachedMembers = null;
	}
};
```

```html
<!-- src/routes/team/+page.svelte -->
<script lang="ts">
	import { page } from '$app/stores';
	export let data;

	let query = $page.url.searchParams.get('q') ?? '';
	let count = 0;
	$: count = data.members.length;
</script>

<h1>Team ({count})</h1>

<input bind:value={query} placeholder="Search" />
<a href={'?q=' + query}>Search</a>

<ul>
	{#each data.members as member, i (i)}
		<li>
			<img src={member.avatar} />
			{@html member.bio}
			<form method="POST" action="?/remove">
				<input type="hidden" name="id" value={member.id} />
				<div class="btn" on:click={() => this.closest('form').submit()}>Remove</div>
			</form>
		</li>
	{/each}
</ul>
```

## Part 3: Live coding in an existing project (55 minutes)

This part runs in your **practice project**, which by now has the counter, todos and guestbook. Treat it as a codebase you have never seen: start by spending two minutes reading `package.json`, `vite.config.ts` and one existing test, and say out loud what you found.

### The task (as the interviewer would give it)

> “We need a product catalogue with pagination. Add a `/products` page that lists products 10 per page, with a reusable `Pagination` component. The page must work without JavaScript and the current page must survive a reload. Write a component test for `Pagination` and an e2e test for the page. You have 40 minutes, then I will ask for a change.”

Clarifying questions worth asking (and the answers to assume):

- Where does the data come from? → Generate 47 fake products in `src/lib/server/products.ts`.
- What should happen for `?page=99` or `?page=abc`? → An out-of-range page gives a 404; a non-number is treated as page 1.
- Should page numbers be links or buttons? → Links, so it works without JavaScript and pages can be shared.
- How many page links? → All of them for now (5 pages).

### Acceptance criteria to write down first

1. `/products` shows products 1–10; `/products?page=2` shows 11–20; page 5 shows 41–47.
2. `Pagination` receives `page`, `totalPages` and `href(page) => string`, and renders a `<nav aria-label="Pagination">` with a link per page.
3. The current page link has `aria-current="page"`.
4. “Previous” and “Next” are links, except on the first/last page, where they are rendered as non-interactive text (not a disabled link).
5. `?page=99` returns a 404; `?page=abc` shows page 1.
6. Works without JavaScript; reload keeps the page.

### Session outline

| Minutes | Step |
|---|---|
| 0–5 | Read the project, write the criteria, check `CLAUDE.md` is still there |
| 5–15 | `src/lib/server/products.ts` with `listProducts()` and a pure `paginate(items, page, perPage)` returning `{ items, page, totalPages }`; Node unit test for `paginate` (first, middle, last page, out-of-range) |
| 15–25 | `Pagination.svelte` and `Pagination.svelte.spec.ts` (links and hrefs, `aria-current`, no “Previous” link on page 1, no “Next” link on the last page) |
| 25–35 | `src/routes/products/+page.server.ts` (read and parse `page`, `error(404)` when out of range) and `+page.svelte` using the component with `href={(p) => '?page=' + p}` |
| 35–40 | `products.e2e.ts`: click page 2, URL has `?page=2`, the first product is “Product 11”; reload keeps it; `?page=99` responds 404 |

### The change request (at minute 40)

> “Product wants a ‘per page’ selector with 10, 20 and 50. It must also be in the URL. And if I’m on page 5 with 10 per page and switch to 50, don’t show me a 404.”

You have 15 minutes. Things to get right, and to say out loud:

- `perPage` is URL state too (`?page=2&perPage=20`), validated against the allowed values (anything else → 10).
- `Pagination`’s `href` must keep `perPage`: build the URL from the current `page.url` (`new URL(page.url)`, `searchParams.set(...)`) or pass `perPage` into the `href` function.
- Changing `perPage` should reset to page 1 (simplest, and avoids the out-of-range page). A GET form with a `<select name="perPage">` and a submit button works without JavaScript; with JavaScript you can submit on change.
- Update the unit test for `paginate` and add one e2e test for the selector.
- If you run out of time, say exactly what is left and how you would do it. That is a valid finish.

### Things the interviewer will notice

- Did you read the existing code and follow its conventions (file names, `#lib` imports, test style)?
- Did you keep the existing tests green? Run the **whole** suite at the end, not just your new tests.
- Did you keep URL state on the server (`url.searchParams` in the load), so SSR, reload and no-JS work?
- How did you react to the change request: did you clarify, adjust the criteria, and keep tests in step?

## Part 4: Debrief (15 minutes)

Score yourself:

| Area | 0 | 1 | 2 |
|---|---|---|---|
| Part 1 (sum of the 12 marks, divided by 12, rounded) | | | |
| Part 2 (0 = under 5 problems, 1 = 5–8, 2 = 9 or more) | | | |
| Read the existing code before changing it | | | |
| Acceptance criteria before the first prompt | | | |
| Reviewed every diff, caught at least one problem | | | |
| `paginate` unit test, `Pagination` component test, e2e test all pass | | | |
| Whole suite green at the end, `npm run check` clean | | | |
| Handled the change request calmly, criteria and tests updated | | | |

Then compare with Mock 1: which area improved, which did not? Write down the two topics you will re-read on the evening before the interview.

## Answer notes

### Part 1

1. The client router intercepts the click and runs `beforeNavigate`. It loads the route’s code (already preloaded if the user hovered, since the scaffold sets `data-sveltekit-preload-data="hover"`, which also fetches the data). Server loads that need to run are fetched in one `__data.json` request; universal loads run in the browser. Loads whose dependencies did not change are skipped (for example the root layout). Then `onNavigate`, the DOM update (the page component is reused if the route is the same), focus and scroll handling, and `afterNavigate`. *Follow-ups:* hovering starts the code and data preload, so the click may complete instantly; server loads run on the server via `__data.json`, universal loads in the browser, and only those whose inputs changed.
2. `$state(prop)` captures the initial value only, and components are reused across navigations. Fixes: `$derived(prop)` for a value that follows the prop; a writable `$derived` when the user may edit it locally but it should reset when the prop changes; `{#key}` to recreate the component. *Follow-up:* when the prop is deliberately an *initial* value (`initialCount`), and the component owns the value afterwards; document it, for example with a `svelte-ignore state_referenced_locally` comment.
3. An effect runs after DOM updates, in the browser only, to synchronise with something outside Svelte. Right: drawing on a canvas, subscribing to a WebSocket, setting `document.title` from a value, with cleanup. Wrong: computing filtered data (`$derived`), reacting to a click (handler), syncing props to state. *Follow-up:* in a component test, render and assert on the visible result (effects run in the browser); for logic in a `.svelte.ts` module, `$effect.root` plus `flushSync`.
4. On the server that module is shared by every request, so users would see each other’s data during SSR, and it is a race between concurrent requests. *Follow-up:* server: `event.locals.user` set in `handle`, exposed to pages by returning a projection from a layout server load; client: read it from `data`/`page.data`, or put a per-tree object in context in the root layout.
5. Form action: page-bound, stable, works without JavaScript, good default for a form on that page. `+server` endpoint: an HTTP API for other clients or non-form calls (webhooks, mobile apps). Remote function: a typed, reusable `form`/`command` callable from any component, but experimental in SvelteKit 3. *Follow-up:* form actions and remote `form`s work without JavaScript; a `+server` endpoint only if a plain HTML form posts to it and it responds with a redirect or HTML.
6. A waterfall: requests that could run in parallel run in sequence. Look for `await parent()` before independent work, universal loads that each call a remote API, sequential awaits in one load, and data fetched in components after mount. Fix: start promises first and await together, move to server loads (batched into one `__data.json`), stream secondary data. *Follow-up:* `await parent()` makes a load wait for all parent loads; start independent fetches before calling it.
7. Validate the session in `handle` and set `locals.user`; a coarse path guard in `handle` redirects anonymous users; and every server load, action, endpoint and remote function checks permission on the data it touches (`requireUser()` and scoped queries). *Follow-ups:* layout loads run in parallel with page loads and may not re-run on client navigation, so the page data can be returned; for remote functions, path guards do not apply (query calls hit the remote endpoint, form/command URLs are client-reported), so authorise inside each function.
8. No full reload, `form` updates in place, reset on success, `refreshAll()`, redirects followed, error page rendered; still works without JavaScript. SvelteKit 3: enhanced failures carry the real HTTP status, and a form that posts to another page navigates there (`update({ navigate: false })` to opt out). *Follow-up:* return the submitted values in `fail(400, { values, errors })` and render them as `value={form?.values?.name ?? ''}`; or `update({ reset: false })` in a custom callback.
9. Reproduce with a production build, read the warning’s details in the browser console, compare server HTML (view source) with the rendered DOM, and look for values that differ between server and client. *Follow-up:* `Date.now()`/time zones, `Math.random()`/generated ids (use `$props.id()`), `window`/`localStorage`/`matchMedia` reads during render, invalid HTML nesting that the browser repairs, browser extensions changing the DOM.
10. Unit (Node): the search/filter logic and the server load with a fake `fetch` or stubbed data; the `delete` action’s success and failure shapes, including authorisation. Component (browser mode): the search box calls back with the query; the list renders and the delete button is accessible. E2E (Playwright, production build): search updates the URL and list; delete removes an item; delete works without JavaScript. *Follow-up:* component tests and e2e run in real browsers, because they need real events, layout and focus; logic tests run in Node because they need none of that and are faster.
11. A `CLAUDE.md` with the conventions, small prompts with acceptance criteria, reading every diff, running the tests and type check myself, breaking code once to prove a test is meaningful. *Follow-up:* `export let` or `on:click` (Svelte 4), `$app/stores` or `$lib` (SvelteKit 2), `$effect` that sets derived state, an each block keyed by index, a test that waits with `setTimeout`, a `div` with `onclick` instead of a button.
12. Upgrade to the latest 2.x and fix deprecations; raise Node, TypeScript, Svelte and Vite; run `npx sv migrate sveltekit-3` in small commits; then work through `MIGRATION_TASKS.md`. Test: full unit and e2e suites against a production build, staging behind the real proxy, forms with and without JavaScript, auth flows, error pages. *Follow-up:* behavioural changes the type checker cannot see: enhanced forms now return real status codes and navigate cross-page; `handleError` now receives all errors (logging volume, status overrides); external redirects throw unless allowed; `ORIGIN` removal behind proxies.

### Part 2: problems in the pull request

**Server file**

1. `$lib` import: SvelteKit 3 uses `#lib/server/db.js` (with extension).
2. `cachedMembers` at module level: shared across all users and never invalidated by other instances; if members are per team or per permission, it leaks data. Cache explicitly (with a key and TTL) or not at all.
3. No authorisation: anyone can load the page, and the `remove` action deletes any member by id. Check `locals.user` and permissions in both.
4. The catch-all `try/catch` would also swallow a `redirect()`/`error()` thrown inside, and `error(500, e.message)` leaks internal error messages to users. Let unexpected errors propagate to `handleError`.
5. The search is case-sensitive and the filter runs on the full list; fine for small data, but say so (and move filtering into the query for large data).
6. `return { members: ... }` returns whole database rows, possibly emails or internal fields: project to the fields the page needs.
7. The action does not validate `id` (could be `null`) and does not return a failure; no `satisfies Actions` and no types (`PageServerLoad`).

**Page file**

8. `$app/stores` and `$page` are removed in SvelteKit 3: use `page` from `$app/state`.
9. `export let data` and `$:` are Svelte 4 syntax: `let { data } = $props();` and `let count = $derived(data.members.length);`.
10. `query` is initialised once from the URL and never follows navigation; and the search uses a link built from the input instead of a GET form (`<form method="GET"><input name="q" value={data.q}>`), which also works without JavaScript and on Enter.
11. Each block keyed by index `(i)`: key by `member.id`.
12. `<img>` without `alt` (a11y warning).
13. `{@html member.bio}`: XSS risk if bios are user-written; sanitise or render as text.
14. A `div` with `on:click` instead of a `<button>`: not keyboard accessible, Svelte 4 event syntax, `this` is not the element in an arrow function, and `form.submit()` bypasses validation and enhancement. Use `<button>Remove</button>` and `use:enhance` on the form; add `aria-label={'Remove ' + member.name}`.
15. No confirmation and no feedback for a destructive action, and no error handling for a failed delete: return `fail` and show a message.

### Part 3: reference points

- `paginate(items, page, perPage)` should compute `totalPages = Math.max(1, Math.ceil(items.length / perPage))` and slice `(page - 1) * perPage`. The load parses `page` with `Number.parseInt`, treats `NaN` or values below 1 as 1, and calls `error(404, 'Page not found')` when `page > totalPages`.
- Render “Previous”/“Next” as `<a>` only when there is a target; otherwise a `<span>` (an `<a>` without `href` is not a link and a “disabled link” is not a thing in HTML).
- Component test locators: `page.getByRole('navigation', { name: 'Pagination' })`, `getByRole('link', { name: '2' })` with `toHaveAttribute('href', '?page=2')`, the current link `toHaveAttribute('aria-current', 'page')`, and `getByRole('link', { name: 'Previous' })` → `not.toBeInTheDocument()` on page 1.
- E2E 404 check: `const response = await page.goto('/products?page=99'); expect(response?.status()).toBe(404);`.
- Change request: `perPage` parsed from `url.searchParams` against `[10, 20, 50]`; the `href` builder keeps it; the selector is a GET form with `name="perPage"` (no hidden `page`, so it resets to page 1).
