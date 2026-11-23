# Day 4: Data: `load`, Invalidation, Streaming and Form Actions

**Goal for today:** choose correctly between universal and server `load`, explain when loads re-run, and build a progressively enhanced form with validation.

This is the day with the most interview questions. Do not skip the quiz.

## Read (45 min)

1. **Kit 4**, “Two kinds of `load`”, “The event object”, “Merging, `data`, and `page.data`”, “`fetch` in load”, “Parallelism, `parent()` and waterfalls”, “Redirects and errors from load”, “Reading data in components”, “Common failure modes”.
2. **Kit 5**, “The dependency model” (first half), “Manual invalidation APIs”, “Streaming” (first half), “Preloading” (first page).
3. **Kit 6**, “6.1 The mental model” to “6.5 SvelteKit 3 behaviour changes”, then “6.8 GET forms” and “6.12 Actions or remote functions?”.

## Core notes (20 min)

### Universal versus server `load`

| | Universal `+page.ts` | Server `+page.server.ts` |
|---|---|---|
| Runs | Server during SSR, then **in the browser** on navigation | **Server only** |
| Can use | Public APIs, anything the browser could do | Database, secrets, `cookies`, `locals`, `request` |
| Return value | Anything (even components, classes) | Must be serialisable by `devalue` (Date, Map, Set, BigInt are fine; functions and class instances are not) |
| On client navigation | Calls the API directly from the browser | The browser fetches `__data.json` from your server |

```ts
// src/routes/blog/[slug]/+page.server.ts
import { error } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';
import { getPost } from '#lib/server/posts.js';

export const load: PageServerLoad = async ({ params }) => {
	const post = await getPost(params.slug);
	if (!post) error(404, 'Post not found');
	return { post: { title: post.title, html: post.html } }; // project, don't leak the row
};
```

- Everything a server `load` returns is **sent to the browser**. Return only what the page needs, never the whole database row.
- If both exist for one route, the server load runs first and its result arrives in the universal load as `event.data`. The universal result **replaces** it, so forward what you need.
- Data merges shallowly from the root layout down to the page. A component gets its own and its ancestors’ data as the `data` prop. Use `page.data` (from `$app/state`) when a parent needs child data, such as the `<title>`.
- Derive from `data` with `$derived`. Copying `data.x` into `$state` freezes the first value, because components are **reused** when you navigate between two URLs of the same route.

### The `fetch` in load

Use the `fetch` passed in the event, not the global one:

- It forwards cookies and `authorization` for same-origin requests.
- It resolves relative URLs on the server.
- Internal requests (`/api/...`) are dispatched in-process, without HTTP.
- During SSR, responses fetched in a **universal** load are inlined into the HTML and replayed during hydration, so the browser does not fetch them again.

### Parallelism and waterfalls

- All `load` functions for a route **start in parallel**. `await parent()` makes one wait for its parent: start independent work *before* awaiting `parent()`.
- Consequence for security: a redirect in a layout `load` does **not** stop the page `load` from running. Do authorisation in `handle` or in each load (Day 7).

### Errors and redirects

```ts
import { error, redirect } from '@sveltejs/kit';
error(404, 'Not found');        // throws: renders the nearest +error.svelte
redirect(303, '/login');        // throws: redirect
```

- Both **throw** by themselves (since SvelteKit 2, no `throw` keyword needed). Never wrap them in a catch-all `try/catch`; if you must catch, rethrow when `isHttpError(e)` or `isRedirect(e)`.
- External redirects throw in SvelteKit 3 unless you opt in with `{ external: true }`.

### When does a `load` re-run?

SvelteKit tracks what each `load` **reads**:

- `params.x` that it read changed;
- `url.pathname`, or a search param it read with `url.searchParams.get('q')` (tracked per key), changed;
- it awaited `parent()` and the parent re-ran;
- it called `depends('app:cart')` (or fetched a URL) and someone called `invalidate('app:cart')` (or that URL);
- someone called `refreshAll()` (SvelteKit 3; `invalidateAll()` is deprecated).

Loads whose inputs did not change are skipped. A re-run updates the component’s `data` prop; it does not recreate the component.

Server loads never register fetched URLs as dependencies (the dependency list is sent to the browser), so use `depends('app:id')` identifiers there.

### Streaming

```ts
export const load: PageServerLoad = async () => {
	const comments = getComments().catch(() => []); // a promise, not awaited
	const post = await getPost();                    // essential: awaited
	return { post, comments };
};
```

```html
{#await data.comments}<p>Loading comments…</p>{:then comments}…{/await}
```

- Only **server** loads stream. Return un-awaited promises for secondary data; await what the page cannot render without (and anything SEO-critical).
- Once streaming starts, the status code, headers, cookies and redirects can no longer change.
- Attach a `.catch` to streamed promises so a rejection does not become an unhandled rejection.

### Form actions

```ts
// src/routes/guestbook/+page.server.ts
import { fail } from '@sveltejs/kit';
import type { Actions } from './$types';

export const actions = {
	default: async ({ request }) => {
		const data = await request.formData();
		const name = String(data.get('name') ?? '');
		if (!name.trim()) return fail(400, { name, errors: { name: 'Name is required' } });
		await save(name);
		return { success: true };
	}
} satisfies Actions;
```

```html
<script lang="ts">
	import { enhance } from '$app/forms';
	let { data, form } = $props();
</script>

<form method="POST" use:enhance>
	<input name="name" value={form?.name ?? ''} />
	{#if form?.errors?.name}<p role="alert">{form.errors.name}</p>{/if}
	<button>Sign</button>
</form>
```

- An action is a **POST to the page URL**. Order: the action runs, then the loads re-run, then the page renders with the action’s return value as the `form` prop.
- Named actions: `export const actions = { create, delete }` and `<form action="?/create">` or `<button formaction="?/delete">`. A route cannot mix `default` with named actions.
- `return fail(status, data)` for validation errors (the form re-renders with `form` set). `redirect()` and `error()` are thrown, as in `load`. `satisfies Actions` keeps `form` typed.
- **It works without JavaScript.** That is progressive enhancement: the browser posts, the server renders the result.
- `use:enhance` makes it work without a full reload. With no argument it: submits with `fetch`, updates `form`, resets the form on success, calls `refreshAll()`, follows redirects and renders errors. Passing a callback lets you show pending state or keep the inputs. Call `update()` to keep the defaults.
- SvelteKit 3: enhanced failures return the real HTTP status (400, 422…), and an enhanced form that posts to **another** page now navigates there (use `update({ navigate: false })` for widget-style posts).
- GET forms (`<form method="GET">`) are navigations, not actions. Use them for search and filters; the query ends up in the URL.
- CSRF: SvelteKit rejects cross-origin form POSTs in production by checking the `Origin` header.

## Hands-on (40 min)

1. Build the guestbook: `src/lib/server/guestbook.ts` with `listEntries`, `validate` and `addEntry`; `src/routes/guestbook/+page.server.ts` with `load` and a default action; `+page.svelte` with `use:enhance`, inline errors and an entries list. The reference solution is Drill 3 in the live-coding playbook.
2. Disable JavaScript in the browser’s dev tools and submit the form. It must still work.
3. Add a `+page.ts` to the blog route from Day 3 that fetches `https://jsonplaceholder.typicode.com/posts/1` with the provided `fetch`. In the Network tab, check that the browser does not request it again on the first page load.
4. Add `depends('app:entries')` to the guestbook load and a button that calls `invalidate('app:entries')`.

## Quiz (15 min)

1. Give three reasons to choose a server `load` and two reasons to choose a universal `load`.
2. Why must you be careful about what a server `load` returns? Show the safe pattern.
3. A page has both `+page.server.ts` and `+page.ts`. What does the component’s `data` prop contain?
4. **Find the bug:**

   ```ts
   let { data } = $props();
   let title = $state(data.post.title);
   ```

   The user navigates from `/blog/a` to `/blog/b` and the title does not change. Why? Fix it.
5. Name four ways a `load` function can be made to re-run.
6. Why should you use the `fetch` passed to `load` instead of the global `fetch`? Give three reasons.
7. Your layout `load` redirects anonymous users to `/login`. Is the page’s server `load` (which reads private data) protected? Explain.
8. **Find the bug:**

   ```ts
   try {
   	const user = await getUser();
   	if (!user) redirect(303, '/login');
   } catch (e) {
   	console.error(e);
   	error(500, 'Failed');
   }
   ```

9. How do you stream a slow, non-essential part of the page? What can no longer change once streaming has started?
10. In what order do the action, the `load` functions and the render happen when a form posts to a page?
11. What is the difference between `return fail(400, {...})` and `error(400, ...)` in an action?
12. What does `use:enhance` do with no arguments? Name four behaviours.
13. Multiple choice: which is true in SvelteKit 3?

    a. `invalidateAll()` is the recommended way to refresh all data
    b. An enhanced form posting to another page now navigates to it
    c. Enhanced failures always return HTTP 200
    d. `fail` must be thrown

14. When should a form use `method="GET"` instead of an action?
15. What is progressive enhancement, and how would you prove in a test that a form has it?
