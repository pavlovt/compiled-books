# Final Tests: Answer Key

## Test 1: Svelte 5

1. c.
2. a, b and d. Runes need `.svelte` in the file name.
3. `4`. Deriveds are pull-based: reading `double` after `count++` recomputes it synchronously.
4. A value computed from props is written in an effect: it renders once with `0` (and on the server stays `0`), costs an extra update, and is the classic effect misuse. Use `let total = $derived(items.reduce((s, i) => s + i.price, 0));`.
5. `$state` proxies every object and property lazily as it is read, which costs memory and time for data you never mutate in place; `$state.raw` stores the array as is, and reassignment after each fetch is all you need.
6. The method is passed detached, so `this` is `undefined` when it runs. Use an arrow-function field `inc = () => { this.count++; }`, or `onclick={() => counter.inc()}`.
7.
   ```html
   <script lang="ts">
   	let { label, onselect }: { label: string; onselect?: (id: string) => void } = $props();
   </script>
   <button onclick={() => onselect?.(id)}>{label}</button>
   ```
   (with `id` coming from a prop or local state).
8. The parent may bind to it (`<Input bind:value={name} />`), so changes in the child flow back up. Without `$bindable`, the prop is one-way.
9. A snippet prop with arguments:
   ```html
   <!-- List.svelte -->
   <script lang="ts" generics="T">
   	import type { Snippet } from 'svelte';
   	let { items, row }: { items: T[]; row: Snippet<[T]> } = $props();
   </script>
   <ul>{#each items as item}<li>{@render row(item)}</li>{/each}</ul>

   <!-- parent -->
   <List {items}>{#snippet row(item)}<b>{item.name}</b>{/snippet}</List>
   ```
   (Key the each block when items have ids.)
10. b. Filtering is a `$derived`.
11. It is the cleanup: it runs before the effect re-runs and when the component is destroyed.
12. Keying by the index is the same as not keying: identity follows positions, not items. Use `(todo.id)`.
13. In development Svelte warns (`ownership_invalid_mutation`): the child mutates state it does not own. Call a callback prop so the parent changes it, or make the prop `$bindable` and have the parent bind it.
14. `$derived` (when read), `onDestroy` and the `<script>` body. Not `onMount`, `$effect` or `onclick`.
15. Any two of: `Date.now()`/`new Date()` in render; `Math.random()`; reading `window`, `localStorage` or `matchMedia` during render; invalid HTML nesting that the browser repairs.
16. Importers get a binding, not a live signal, and the compiler forbids exporting reassigned state (`state_invalid_export`). Export an object and mutate its property, or export getter and setter functions (or a class instance).
17. Context holds the object that was set; reassigning the variable makes it point to a new object that the children never received. Mutate the existing object’s properties instead.
18. It renders unsanitised HTML, so stored content can execute scripts (XSS). Sanitise on the server with an allow-list sanitiser, render text where possible, and add a CSP.
19. A function that takes the data and returns the attachment; the cleanup destroys the chart:
   ```html
   <script>
   	import Chart from 'chart.js/auto';
   	let { sales } = $props();

   	function barChart(rows) {
   		return (canvas) => {
   			const chart = new Chart(canvas, {
   				type: 'bar',
   				data: {
   					labels: rows.map((r) => r.month),
   					datasets: [
   						{ data: rows.map((r) => r.total) }
   					]
   				}
   			});
   			return () => chart.destroy();
   		};
   	}
   </script>

   <canvas {@attach barChart(sales)}></canvas>
   ```
   When `sales` changes, Svelte runs the cleanup (destroying the old chart) and the new attachment draws a fresh one. It runs only in the browser, so the library never touches the server. (Svelte 9)
20. Radios: the selected value. Checkboxes: an array of the selected values.
21. In runes mode the each variable is not assignable through a binding; binding to a property of the item (`todo.done`) updates the underlying state.
22. A unique id per component instance that is identical on the server and the client, so `for`, `aria-labelledby`, `aria-describedby` and `aria-controls` relationships survive hydration.
23. a.
24. An effect (or chain of effects) keeps invalidating itself more than about 1000 times in one flush; typically an effect that reads and writes the same state.
25. Create it per request and per tree: for example, a `Cart` class instantiated in the root layout and provided through context (`createContext`), initialised from `data` returned by a server load (which reads the cart from the session or a cookie). A module singleton is shared by all requests on the server, so carts would leak between users during SSR.

## Test 2: SvelteKit

1. a.
2. `+page.ts`: universal load. `+page.server.ts`: server load and form actions. `+layout.svelte`: layout wrapping child routes. `+server.ts`: API endpoint (HTTP verb handlers returning `Response`). `+error.svelte`: error boundary for the subtree.
3. `/docs`, `/docs/…` (any depth); the group `(app)` is not in the URL. `params.path` is `'a/b'`.
4. The route does not match, and routing continues with the next route in sort order; if none matches, a 404.
5. Server for anything that needs secrets, the database, cookies or `locals` (loading the current user’s orders). Universal for public APIs callable from the browser, or non-serialisable return values (loading a public weather API on navigation).
6. It returns the whole database row (including fields such as a password hash) to the browser; it also does not handle a missing user or check authorisation. Return an explicit projection, `error(404)` when missing, and check `locals.user`.
7. `{ b: 2 }` only, unless `+page.ts` forwards `data.a`.
8. When the `page` search parameter changes (it is tracked per key), plus the other triggers: params, `depends` invalidations, `refreshAll`, a parent re-run if it awaited `parent()`.
9. Sequential awaits that could have run in parallel. Start independent promises first, then `await parent()`, then await the rest; or avoid `parent()` by having each load fetch what it needs.
10. The page load still runs (in parallel, and on navigations without the layout re-running), so the private data is returned to anonymous users. Check `locals.user` in the page load (and guard in `handle`).
11.
    ```ts
    import { fail } from '@sveltejs/kit';
    import type { Actions } from './$types';

    export const actions = {
    	default: async ({ request }) => {
    		const data = await request.formData();
    		const email = String(data.get('email') ?? '').trim();
    		if (!email) return fail(400, { email, missing: true });
    		// …save…
    		return { success: true };
    	}
    } satisfies Actions;
    ```
12. Submit via `fetch` without reloading; set `form`/`page.status`; reset the form; `refreshAll()`; follow redirects; render the error boundary on errors (and manage focus).
13. Action, then loads, then render.
14. `fail(status, data)` is returned and re-renders the page with `form` = `data`. `error(status, message)` throws and renders the nearest `+error.svelte`.
15. Through `handle`: page requests, data requests, actions, `+server` endpoints, remote calls and internal `event.fetch` sub-requests. Not: static files, built assets and prerendered pages.
16.
    ```ts
    import type { Handle } from '@sveltejs/kit/hooks';

    export const handle: Handle = async ({ event, resolve }) => {
    	const sid = event.cookies.get('sid');
    	event.locals.user = sid ? await getUser(sid) : null;
    	return resolve(event);
    };
    ```
17. c, then b, then a.
18. For errors in the root layout’s load, in `handle`, and (for non-HTML requests) in `+server` endpoints: `src/error.html` (or a JSON error body) is used.
19. `prerender = true`: static HTML at build time (docs, marketing). `ssr = false`: client-only rendering (a dashboard using browser-only libraries). `csr = false`: no JavaScript (a static legal page).
20. A prerendered page is a static file; there is no server to run an action when the form is posted.
21. A module-level variable is shared by all requests, so concurrent users overwrite and read each other’s searches. Return it from `load` as data (or keep it in the URL).
22. In the URL (`?sort=price`). Update it with links or a GET form, or `goto(url, { replace: true, reset: false })`, and read it in the load from `url.searchParams`.
23. `import { navigating } from '$app/state'` and `{#if navigating.to}<Spinner />{/if}`.
24. It is a server-only module (`server` directory). `vite build` fails with an error that names the import chain. Vitest does not check it.
25.
    ```ts
    // +page.server.ts
    export const load: PageServerLoad = async ({ params }) => {
    	const reviews = getReviews(params.id).catch(() => []); // streamed
    	const product = await getProduct(params.id);            // awaited
    	if (!product) error(404, 'Product not found');
    	return { product, reviews };
    };
    ```
    ```html
    <h1>{data.product.name}</h1>
    {#await data.reviews}<p>Loading reviews…</p>{:then reviews}…{/await}
    ```

## Test 3: Testing, SvelteKit 3 and Live Coding

1. Unit: Vitest in Node, proves logic and server functions. Component: Vitest browser mode with `vitest-browser-svelte`, proves a component’s behaviour in a real browser. E2E: Playwright on the production build, proves user journeys through the whole app.
2. `Foo.svelte.spec.ts`: the `client` project, in Chromium (browser mode). `foo.spec.ts`: the `server` project, in Node.
3. `rune_outside_svelte`.
4.
   ```ts
   import { page } from 'vitest/browser';
   import { expect, it, vi } from 'vitest';
   import { render } from 'vitest-browser-svelte';
   import Toggle from './Toggle.svelte';

   it('toggles and reports the state', async () => {
   	const onchange = vi.fn();
   	render(Toggle, { label: 'Dark mode', onchange });
   	const button = page.getByRole('button', { name: 'Dark mode' });

   	await expect.element(button).toHaveAttribute('aria-pressed', 'false');
   	await button.click();
   	await expect.element(button).toHaveAttribute('aria-pressed', 'true');
   	expect(onchange).toHaveBeenCalledWith(true);
   });
   ```
5. `expect` checks a value once; `await expect.element(locator)` retries a DOM assertion until it passes or times out.
6. `createRawSnippet(() => ({ render: () => '<p>content</p>' }))`, or a harness `.svelte` component.
7. `vi.mock('$app/state', () => ({ page: { url: new URL('http://localhost/path') } }))`, or pass the value as a prop.
8. `await expect(load(event)).rejects.toSatisfy((e) => isHttpError(e, 404));`
9.
   ```ts
   const body = new FormData();
   body.set('email', '');
   const request = new Request('http://localhost/x', { method: 'POST', body });
   const result = await actions.default({ request } as Parameters<typeof actions.default>[0]);
   expect(isActionFailure(result)).toBe(true);
   ```
10. `vi.mock('$app/server', () => ({ getRequestEvent: () => fakeEvent }))`, then import the helper and call it.
11. A fixed `waitForTimeout` (slow and flaky); a CSS-class locator instead of role and name; a non-retrying `count()` read instead of `await expect(locator).toHaveCount(1)`; `li` may match list items from the layout (strict mode and scoping).
12. To test the production build: bundling, real SSR plus hydration and production-only behaviour.
13.
    ```ts
    test.describe('without JavaScript', () => {
    	test.use({ javaScriptEnabled: false });
    	test('signs the guestbook', async ({ page }) => {
    		await page.goto('/guestbook');
    		await page.getByLabel('Name').fill('NoJS');
    		await page.getByLabel('Message').fill('Still works');
    		await page.getByRole('button', { name: 'Sign' }).click();
    		await expect(page.getByText('NoJS: Still works')).toBeVisible();
    	});
    });
    ```
14. Server-rendered HTML is visible before JavaScript attaches handlers, so an early click can submit natively or do nothing. Use retrying assertions on outcomes, and wait for a hydration marker set in the root layout’s `onMount` if needed.
15. The data was fetched on the server during SSR; `page.route` only intercepts browser requests.
16. Any five: no Svelte 4 syntax (`export let`, `$:`, `on:`, slots, dispatchers); no `$lib`/`$app/stores`; `$derived` instead of effect-assignments; keyed each blocks; no browser APIs at module or render level; accessible markup; tests use roles and names, await interactions, have no sleeps, and fail when the feature breaks; file names match the test projects.
17. Svelte 5/SvelteKit 3 conventions (runes only, callback props, `#lib`, `$app/state`), test file naming and tools, and the commands to run. It steers the model away from older syntax it has seen more often, and saves repeating constraints in each prompt.
18. Break the component on purpose (for example remove the `disabled` condition), show the test failing, and restore it.
19. Any five: `svelte.config.js` → `sveltekit({...})` in `vite.config.ts`; `$lib` → `#lib`; `$app/stores` → `$app/state`; `$env/*` → `src/env.ts` plus `$app/env/*`; `$app/environment` → `$app/env`; `base` → `resolve()`; `src/params/*` → `src/params.ts`; `pushState`/`replaceState` → `goto({ shallow })`; `invalidateAll` → `refreshAll`; hook types from `@sveltejs/kit/hooks`.
20. In `src/env.ts`: `NAME: { public: true, static: true }` inside `defineEnvVars`; in the component: `import { NAME } from '$app/env/public';`.
21. Type-safe server functions in `*.remote.ts` (`query`, `form`, `command`, `prerender`); experimental in 3.x; `experimental.remoteFunctions: true` and `compilerOptions.experimental.async: true` in `sveltekit({...})`.
22. Remote query calls are sent to the remote endpoint URL, not the page path, so a page-path guard never sees them. Check authorisation inside the function.
23. They now return the real `fail` status (for example 400) instead of 200. Tests or monitoring that expected 200 for enhanced failures break.
24. c.
25. 0–5 min: clarify and write criteria (renders a tab per item; first tab selected by default; clicking selects; ArrowLeft/Right move selection; `role="tablist"`/`tab`/`tabpanel` with `aria-selected` and `aria-controls`; only the selected panel visible; `onchange` called). 5–8: read the setup, add `CLAUDE.md`. 8–18: component, review, try it on a route. 18–28: component test covering the criteria; break the code once. 28–38: e2e test on the route. 38–43: run Vitest, Playwright and `npm run check`. 43–45: summarise and list what you would add.
