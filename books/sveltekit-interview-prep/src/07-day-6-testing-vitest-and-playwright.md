# Day 6: Testing: Vitest, Browser-Mode Component Tests and Playwright

**Goal for today:** from an empty project, set up and write a unit test, a component test and an end-to-end test without looking anything up. This day is the backbone of the live-coding part of the interview.

Every configuration and test in this chapter was run on 23 November 2026 against a fresh `sv` 1.7.0 scaffold (SvelteKit 3.2, Svelte 5.57, Vitest 5.1, `vitest-browser-svelte` 3.1, Playwright 1.65).

## Read (45 min)

1. **Kit 19**, Part 2: “Strategy”, “`sv add vitest` and `sv add playwright`”, “Unit tests: pure logic and framework helpers”, “Integration tests with `Request` objects”, “Component tests in practice”, “Playwright end to end”, “What to test, concretely”.
2. **Svelte 16**, “A testing strategy that fits the framework”, “Unit-testing reactive modules” (including “Testing effects”), “`@testing-library/svelte`”, “Wrapper components for context, bindings and snippets”.

## Core notes (20 min)

### The pyramid

| Level | Tool | Runs in | What it proves |
|---|---|---|---|
| Unit | Vitest, `server` project | Node | Pure logic: validators, `.svelte.ts` classes, loads, actions, `+server` handlers, hooks |
| Component | Vitest browser mode + `vitest-browser-svelte`, `client` project | Real Chromium | A component renders, reacts to clicks and typing, calls its callbacks |
| End to end | Playwright | Real browser against the **production build** | Routing, SSR plus hydration, forms, the whole app |

The design rule behind it: **keep logic out of framework entry points.** Put it in plain functions or `.svelte.ts` classes in `#lib`, test those cheaply, and keep components, loads and actions thin.

### Setup

```bash
npx sv create --template minimal --types ts --add vitest="usages:unit,component" playwright="demo:yes" --install npm my-app
# or, in an existing project:
npx sv add vitest playwright
npx playwright install chromium
```

What the Vitest add-on writes into `vite.config.ts` (trimmed):

```ts
import { defineConfig } from 'vitest/config';
import { playwright } from '@vitest/browser-playwright';
import { sveltekit } from '@sveltejs/kit/vite';

export default defineConfig({
	plugins: [sveltekit({ /* adapter, compilerOptions… */ })],
	test: {
		expect: { requireAssertions: true },
		projects: [
			{
				extends: './vite.config.ts',
				test: {
					name: 'client',
					browser: { enabled: true, provider: playwright(), instances: [{ browser: 'chromium', headless: true }] },
					include: ['src/**/*.svelte.{test,spec}.{js,ts}'],
					exclude: ['src/lib/server/**']
				}
			},
			{
				extends: './vite.config.ts',
				test: {
					name: 'server',
					environment: 'node',
					include: ['src/**/*.{test,spec}.{js,ts}'],
					exclude: ['src/**/*.svelte.{test,spec}.{js,ts}']
				}
			}
		]
	}
});
```

**The file name decides where a test runs:**

| File name | Project | Environment |
|---|---|---|
| `Counter.svelte.spec.ts` | `client` | Real Chromium (browser mode) |
| `todos.svelte.spec.ts` (tests a `.svelte.ts` class or uses runes) | `client` | Real Chromium |
| `guestbook.spec.ts`, `page.server.spec.ts` | `server` | Node |
| `counter.e2e.ts` | Playwright | Real browser against `npm run build && npm run preview` |

Also remember: **runes only compile in files with `.svelte` in the name**, test files included. `expect.requireAssertions: true` fails any test that asserts nothing.

The `playwright.config.ts` from the add-on:

```ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
	webServer: { command: 'npm run build && npm run preview', port: 4173 },
	testMatch: '**/*.e2e.{ts,js}'
});
```

Commands: `npx vitest` (watch), `npx vitest --run`, `npx vitest --run --project server`, `npx playwright test`, `npx playwright test --ui` (debugging), `npm run check`.

### A component test (browser mode)

```ts
// src/lib/components/Counter.svelte.spec.ts
import { page } from 'vitest/browser';
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import Counter from './Counter.svelte';

describe('Counter', () => {
	it('increments and reports changes', async () => {
		const onchange = vi.fn();
		render(Counter, { initial: 0, step: 2, onchange });

		await page.getByRole('button', { name: 'Increase' }).click();

		await expect.element(page.getByRole('status')).toHaveTextContent('2');
		expect(onchange).toHaveBeenCalledWith(2);
	});
});
```

- `render(Component, props)` mounts into a real page. Cleanup between tests is automatic.
- Locate by **role and accessible name**: `getByRole`, `getByLabelText`, `getByText`, `getByPlaceholder`. An `<output>` element has the role `status`.
- Interactions are async: `await locator.click()`, `await locator.fill('text')`, `await userEvent.keyboard('{Enter}')` (`userEvent` is from `vitest/browser`).
- `await expect.element(locator)` **retries** until the assertion passes or times out. Use it for anything on the page; use plain `expect` for mocks and values.
- Useful matchers: `toBeInTheDocument`, `toBeVisible`, `toBeDisabled`, `toBeEnabled`, `toHaveValue`, `toHaveAttribute`, `toHaveTextContent`, `toHaveLength` (for a locator matching many elements), `.not`.
- Verified gotcha: in Vitest 5 browser mode, `toHaveTextContent` accepts a string (no regex) and compared the **whole** text in our run, so `'Buy milk'` failed against a row whose text was `'Buy milk x'` (the delete button). Assert on a more specific element instead, such as `getByRole('checkbox', { name: 'Buy milk' })`.
- Callback props are the natural seam: pass `vi.fn()` and assert the call.

**Props that are snippets** (for example `children`): build one with `createRawSnippet`, or write a small harness component for anything complex.

```ts
import { createRawSnippet } from 'svelte';
const children = createRawSnippet(() => ({ render: () => '<span>About</span>' }));
render(NavLink, { href: '/about', children });
```

**Components that read `$app/state`** (or call `goto`): mock the module. The simplest structure, though, is to pass the data in as props.

```ts
vi.mock('$app/state', () => ({ page: { url: new URL('http://localhost/about') } }));
```

### Unit tests (Node)

```ts
// src/lib/todos.svelte.spec.ts : a .svelte.ts class, no DOM needed
const list = new TodoList();
list.add('a');
list.toggle(list.items[0].id);
expect(list.remaining).toBe(0);
```

- State and deriveds are **synchronous**: write, then read.
- Effects are scheduled. To test one, wrap the test in `$effect.root(() => { … })`, call `flushSync()` after each change, and call the returned cleanup at the end. Creating an `$effect` outside a root throws `effect_orphan`.

**Actions, loads and endpoints** are plain functions. Call them with a partial event:

```ts
// src/routes/guestbook/page.server.spec.ts
import { isActionFailure } from '@sveltejs/kit';
import { actions } from './+page.server';

const body = new FormData();
body.set('name', '');
const request = new Request('http://localhost/guestbook', { method: 'POST', body });
const result = await actions.default({ request } as Parameters<typeof actions.default>[0]);

expect(isActionFailure(result)).toBe(true);
expect(result).toMatchObject({ status: 400 });
```

- `redirect()` and `error()` **throw**: assert with `isRedirect(e)` / `isHttpError(e, 404)`, or `await expect(promise).rejects.toSatisfy((e) => isHttpError(e, 400))`.
- A helper that calls `getRequestEvent()` needs `vi.mock('$app/server', () => ({ getRequestEvent: () => fakeEvent }))`.
- Name the test file `page.server.spec.ts`, not `+page.server.spec.ts`, to avoid confusion with route files.

### End-to-end tests (Playwright)

```ts
// src/routes/guestbook/guestbook.e2e.ts
import { expect, test } from '@playwright/test';

test('adds an entry', async ({ page }) => {
	await page.goto('/guestbook');
	await page.getByLabel('Name').fill('Playwright');
	await page.getByLabel('Message').fill('Hello from e2e');
	await page.getByRole('button', { name: 'Sign' }).click();

	await expect(page.getByRole('status')).toHaveText('Thanks for signing!');
});

test.describe('without JavaScript', () => {
	test.use({ javaScriptEnabled: false });
	test('the form still works', async ({ page }) => { /* same steps */ });
});
```

- Runs against `vite build` + `vite preview` (port 4173): you test what ships. Locally, add `reuseExistingServer: !process.env.CI` to `webServer` to avoid rebuilding on every run.
- Web-first assertions retry: `await expect(locator).toHaveText(…)`, `toBeVisible()`, `toHaveCount(n)`, `toHaveURL(…)`. **Never** `waitForTimeout`.
- **Strict mode:** a locator used in an action or assertion must match exactly one element. Verified gotcha: the scaffold’s root layout renders its own `<li>`, so `page.getByRole('listitem')` matched two elements. Scope it: `page.getByRole('list', { name: 'Todo items' }).getByRole('listitem')`.
- **Hydration race:** the HTML arrives before JavaScript has attached handlers. A click that lands before hydration does a native form submit or does nothing. Mitigations: assert on the *result* with retrying assertions; for flaky cases, set a `data-hydrated` attribute in the root layout’s `onMount` and wait for it after `goto`.
- `test.use({ javaScriptEnabled: false })` proves progressive enhancement.
- `page.route` only mocks **browser** requests. Server-side `fetch` during SSR is not affected; stub upstream APIs through environment variables or `handleFetch`.
- Debug with `npx playwright test --ui` or `--headed`, and read `test-results/*/error-context.md` after a failure.

### What to test, briefly (an interview answer)

“Logic in plain functions and `.svelte.ts` classes with fast Node unit tests. Each component’s behaviour in a real browser: renders from props, reacts to the user, calls its callbacks. Each action’s failure shapes and success path. One Playwright test per critical user journey, including a no-JavaScript run for progressively enhanced forms. Type-check and build in CI, because the build is what catches server-only imports.”

## Hands-on (40 min)

Write, run and make green, without copying:

1. `Counter.svelte.spec.ts`: initial value, increment/decrement with step, `onchange` calls, disabled at bounds.
2. `todos.svelte.spec.ts` for the `TodoList` class.
3. `Todos.svelte.spec.ts`: add two todos (one with Enter, one with the button), complete one, filter, delete.
4. `guestbook.spec.ts` (the validator) and `page.server.spec.ts` (the action).
5. Three e2e tests: counter at max, todo add and complete, guestbook with and without JavaScript.
6. Run all three commands: `npx vitest --run`, `npx playwright test`, `npm run check`.

Then compare with the reference tests in the live-coding playbook.

## Quiz (15 min)

1. Name the three test levels, the tool for each and what each proves.
2. In the scaffolded config, how does Vitest decide whether `Foo.svelte.spec.ts` runs in Node or in the browser?
3. Why must a test file that uses `$state` have `.svelte` in its name?
4. What does `expect.requireAssertions: true` protect against?
5. What is the difference between `expect(x)` and `await expect.element(locator)` in a browser-mode test?
6. How do you test that a component calls its `onchange` callback with the new value?
7. How do you pass a `children` snippet to a component in a test? Give two ways.
8. A component reads `page.url` from `$app/state`. How do you test it?
9. How do you test an `$effect` in a `.svelte.ts` module? Name the two functions you need.
10. **What is wrong with this test?** `expect(() => load(event)).toThrow()` where `load` is async and calls `error(404)`.
11. Why does the Playwright add-on run against `npm run build && npm run preview` instead of `npm run dev`?
12. Your Playwright test fails with “strict mode violation: resolved to 2 elements”. What does it mean, and how do you fix it?
13. Describe the hydration race in SvelteKit e2e tests and one way to avoid it.
14. How would you prove a form works without JavaScript?
15. You mock an API with `page.route(...)` in Playwright, but the page still shows real data. Why?
