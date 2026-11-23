# The Live-Coding Playbook

The live-coding part asks you to build a component, a component test and an end-to-end test, using Claude Code, while someone watches. This chapter gives you a fixed routine, a project setup that steers Claude Code towards current syntax, a review checklist, and six drills. The first three come with reference solutions that were run and passed on 23 November 2026; the last three are unseen practice for any spare time you have (see Day 8).

## What the interviewer is actually evaluating

Using an AI assistant does not make the exercise easier to judge; it changes what is judged. Expect them to watch for:

1. **Understanding the task before generating code.** Clarifying questions, a short spec, explicit acceptance criteria.
2. **Steering.** Precise prompts that name the files, conventions, test levels and constraints.
3. **Reviewing.** Reading every diff, catching outdated syntax and weak tests, and explaining any line on request.
4. **Verifying.** Running the tests and the type check yourself, and showing a failing test turn green.
5. **Communicating.** Narrating what you are doing and why, especially when you reject or change generated code.

You should be able to write every drill below **by hand**. If Claude Code goes off track, you must be able to take over.

## Before the interview: environment checklist

Do this the day before, on the machine you will use:

- [ ] Node 22.17 or later (`node -v`); Claude Code installed and signed in (`claude --version`).
- [ ] A scratch run of `npx sv create … --add vitest="usages:unit,component" playwright="demo:yes"` works, and `npx playwright install chromium` has downloaded the browser (it is ~120 MB; do not do this live).
- [ ] `npx vitest --run`, `npx playwright test` and `npm run check` all pass in the scratch project.
- [ ] Your editor has the Svelte extension.
- [ ] You know where Claude Code’s permission prompts appear, and how to stop a run (Esc).

If they give you an existing project, spend the first two minutes reading `package.json` (versions, scripts), `vite.config.ts` (test projects) and an existing test, and tell the interviewer what you found.

## A `CLAUDE.md` that prevents outdated code

Language models have seen far more Svelte 4 and SvelteKit 2 than Svelte 5 and SvelteKit 3 code. A short `CLAUDE.md` at the project root is the cheapest way to prevent `export let`, `on:click`, `$lib` or `$app/stores` from appearing. If the rules allow it, create this file first and say why you are doing it; that alone is a good signal:

```markdown
# Project conventions

- Svelte 5 runes only: $state, $derived, $effect, $props, $bindable. No `export let`, no `$:`,
  no `on:` directives, no createEventDispatcher, no slots (use snippets and {@render}).
- Component events are callback props (`onchange`), DOM events are attributes (`onclick`).
- SvelteKit 3: import from `#lib/...` (with file extensions), never `$lib`. Use `$app/state`,
  never `$app/stores`. Config lives in vite.config.ts.
- Accessible markup: real buttons and labels; tests locate elements by role and name.
- Tests:
  - Component tests: `src/**/Name.svelte.spec.ts`, Vitest browser mode, `render` from
    `vitest-browser-svelte`, `page` from `vitest/browser`, `await expect.element(...)`.
  - Unit tests: `src/**/name.spec.ts` (Node).
  - E2E: `src/routes/**/name.e2e.ts`, Playwright, role-based locators, no waitForTimeout.
- Commands: `npx vitest --run`, `npx playwright test`, `npm run check`.
```

## The 45-minute routine

| Minutes | Step | What you say and do |
|---|---|---|
| 0–5 | **Clarify** | Restate the task. Ask about props, edge cases, accessibility, styling expectations. Write 4–6 acceptance criteria in a comment or a file. |
| 5–8 | **Look** | Read the project setup (or scaffold it). Add `CLAUDE.md`. |
| 8–18 | **Component** | Prompt for the component only. Review the diff against the checklist below. Render it on a route and try it in the browser. |
| 18–28 | **Component test** | Prompt for the component test with the acceptance criteria as test cases. Run it. Break the component on purpose once to show the test catches it, then restore. |
| 28–38 | **E2E test** | Add a route if needed; prompt for the Playwright test of the main journey. Run it. |
| 38–43 | **Verify** | `npx vitest --run`, `npx playwright test`, `npm run check`. Fix what fails. |
| 43–45 | **Wrap up** | Summarise what you built, what you would add with more time (edge cases, no-JS test, visual states). |

Prefer several small prompts to one large one: the interviewer sees your reasoning, and each diff is small enough to review properly.

## Prompt templates

**Component:**

> Create `src/lib/components/StarRating.svelte` (Svelte 5 runes, TypeScript). Props: `value` (bindable number, default 0), `max` (default 5), `readonly` (boolean), `onchange?: (value: number) => void`. Render a radio group of `max` buttons with accessible names “1 star”, “2 stars”… and `aria-checked` on the selected one. Clicking sets the value and calls `onchange`. Arrow keys move the selection. No styling beyond a `.filled` class. Do not write tests yet.

**Component test:**

> Write `src/lib/components/StarRating.svelte.spec.ts` with `vitest-browser-svelte`. Cover: renders `max` stars; initial value is checked; clicking the 4th star checks it and calls `onchange` with 4; `readonly` ignores clicks; ArrowRight increases the value. Use role-based locators and `await expect.element`. Then run `npx vitest --run --project client` and show me the output.

**E2E test:**

> Add `src/routes/rating/+page.svelte` that renders the rating and shows “You rated N” below it. Write `src/routes/rating/rating.e2e.ts` (Playwright) for: open the page, click the 3rd star, see “You rated 3”. Run `npx playwright test`.

## Review checklist for generated code

Read every diff for these. Say out loud what you check.

**Svelte 5 / SvelteKit 3 syntax**

- [ ] No `export let`, `$:`, `on:click`, `createEventDispatcher`, `<slot>`, `$lib`, `$app/stores`, `$page`.
- [ ] `$props()` destructuring with a typed `Props` interface; defaults in the destructuring.
- [ ] `$derived` for computed values, not `$effect` + assignment.
- [ ] `$state(initialProp)` only when copying the initial value is intended.
- [ ] Each blocks keyed by a stable id.
- [ ] No `window`/`document` access at the top level of a component (breaks SSR).

**Accessibility (also what makes tests easy)**

- [ ] Buttons are `<button type="button">` (or submit buttons inside forms), inputs have labels, icon buttons have `aria-label`.
- [ ] State is exposed to assistive technology: `aria-pressed`, `aria-checked`, `aria-expanded`, `aria-current`, `role="status"`/`<output>` for live values, `role="alert"` for errors.

**Tests**

- [ ] Tests assert behaviour the user sees, located by role and name, not CSS classes or markup snapshots.
- [ ] Every interaction is awaited; page assertions use `await expect.element(...)` (Vitest) or web-first `await expect(locator)` (Playwright).
- [ ] No `waitForTimeout`, no arbitrary sleeps.
- [ ] Each test checks something that would fail if the feature broke. Prove it once by breaking the code.
- [ ] Locators match exactly one element in Playwright (scope with a parent locator if needed).
- [ ] File names follow the project’s conventions (`*.svelte.spec.ts`, `*.e2e.ts`).

## Drill 1: Counter with bounds

**Spec.** Props `initial` (default 0), `min`, `max`, `step` (default 1), and `onchange`. Two buttons named “Decrease” and “Increase”; the value is shown in an `<output>`. A button is disabled when the next step would cross a bound. `onchange` receives the new value.

**Component:** `src/lib/components/Counter.svelte`

```html
<script lang="ts">
	interface Props {
		initial?: number;
		min?: number;
		max?: number;
		step?: number;
		onchange?: (value: number) => void;
	}

	let { initial = 0, min = -Infinity, max = Infinity, step = 1, onchange }: Props = $props();

	// svelte-ignore state_referenced_locally
	let count = $state(initial);

	const atMin = $derived(count - step < min);
	const atMax = $derived(count + step > max);

	function set(value: number) {
		count = value;
		onchange?.(count);
	}
</script>

<div class="counter">
	<button type="button" aria-label="Decrease" disabled={atMin} onclick={() => set(count - step)}>-</button>
	<output aria-live="polite">{count}</output>
	<button type="button" aria-label="Increase" disabled={atMax} onclick={() => set(count + step)}>+</button>
</div>
```

Notes: the `svelte-ignore` comment documents that copying `initial` into state is intentional. An `<output>` has the ARIA role `status`, which gives the test a clean locator.

**Component test:** `src/lib/components/Counter.svelte.spec.ts`

```ts
import { page } from 'vitest/browser';
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import Counter from './Counter.svelte';

describe('Counter', () => {
	it('starts at the initial value', async () => {
		render(Counter, { initial: 5 });
		await expect.element(page.getByRole('status')).toHaveTextContent('5');
	});

	it('increments and decrements by step and reports changes', async () => {
		const onchange = vi.fn();
		render(Counter, { initial: 0, step: 2, onchange });

		await page.getByRole('button', { name: 'Increase' }).click();
		await expect.element(page.getByRole('status')).toHaveTextContent('2');

		await page.getByRole('button', { name: 'Decrease' }).click();
		await expect.element(page.getByRole('status')).toHaveTextContent('0');

		expect(onchange).toHaveBeenNthCalledWith(1, 2);
		expect(onchange).toHaveBeenNthCalledWith(2, 0);
	});

	it('disables the buttons at the bounds', async () => {
		render(Counter, { initial: 1, min: 0, max: 2 });

		await page.getByRole('button', { name: 'Increase' }).click();
		await expect.element(page.getByRole('button', { name: 'Increase' })).toBeDisabled();
		await expect.element(page.getByRole('button', { name: 'Decrease' })).toBeEnabled();
	});
});
```

**Route:** `src/routes/counter/+page.svelte`

```html
<script lang="ts">
	import Counter from '#lib/components/Counter.svelte';
</script>

<h1>Counter</h1>
<Counter initial={0} min={0} max={3} />
```

**E2E test:** `src/routes/counter/counter.e2e.ts`

```ts
import { expect, test } from '@playwright/test';

test('counter stops at its maximum', async ({ page }) => {
	await page.goto('/counter');
	const plus = page.getByRole('button', { name: 'Increase' });

	await plus.click();
	await plus.click();
	await plus.click();

	await expect(page.getByRole('status')).toHaveText('3');
	await expect(plus).toBeDisabled();
});
```

## Drill 2: Todo list with filters

**Spec.** Add todos with a labelled input (Enter or an “Add” button); blank input is ignored and text is trimmed. Each todo has a checkbox and a delete button named “Delete <text>”. Filter buttons “all”, “active”, “done” with `aria-pressed`. Show “N remaining” and an empty-state row.

The logic lives in a `.svelte.ts` class, so most of it is unit-testable without a DOM.

**Logic:** `src/lib/todos.svelte.ts`

```ts
export interface Todo {
	id: number;
	text: string;
	done: boolean;
}

export type Filter = 'all' | 'active' | 'done';

export class TodoList {
	items = $state<Todo[]>([]);
	filter = $state<Filter>('all');
	#nextId = 1;

	visible = $derived(
		this.filter === 'all'
			? this.items
			: this.items.filter((t) => (this.filter === 'done' ? t.done : !t.done))
	);
	remaining = $derived(this.items.filter((t) => !t.done).length);

	add = (text: string) => {
		const trimmed = text.trim();
		if (!trimmed) return false;
		this.items.push({ id: this.#nextId++, text: trimmed, done: false });
		return true;
	};

	toggle = (id: number) => {
		const todo = this.items.find((t) => t.id === id);
		if (todo) todo.done = !todo.done;
	};

	remove = (id: number) => {
		this.items = this.items.filter((t) => t.id !== id);
	};
}
```

Notes: the methods are arrow-function fields, so they keep `this` even when passed around as callbacks. `remove` reassigns `items` instead of splicing; both are reactive.

**Unit test:** `src/lib/todos.svelte.spec.ts`

```ts
import { describe, expect, it } from 'vitest';
import { TodoList } from './todos.svelte';

describe('TodoList (logic)', () => {
	it('ignores blank input and trims text', () => {
		const list = new TodoList();
		expect(list.add('   ')).toBe(false);
		expect(list.add('  milk ')).toBe(true);
		expect(list.items.map((t) => t.text)).toEqual(['milk']);
	});

	it('derives remaining and visible items', () => {
		const list = new TodoList();
		list.add('a');
		list.add('b');
		list.toggle(list.items[0].id);

		expect(list.remaining).toBe(1);
		list.filter = 'done';
		expect(list.visible.map((t) => t.text)).toEqual(['a']);
		list.filter = 'active';
		expect(list.visible.map((t) => t.text)).toEqual(['b']);
	});
});
```

**Component:** `src/lib/components/Todos.svelte`

```html
<script lang="ts">
	import { TodoList, type Filter } from '#lib/todos.svelte.js';

	const list = new TodoList();
	let draft = $state('');
	const filters: Filter[] = ['all', 'active', 'done'];

	function submit(event: SubmitEvent) {
		event.preventDefault();
		if (list.add(draft)) draft = '';
	}
</script>

<form onsubmit={submit}>
	<label>
		New todo
		<input bind:value={draft} />
	</label>
	<button>Add</button>
</form>

<div role="group" aria-label="Filter">
	{#each filters as f (f)}
		<button type="button" aria-pressed={list.filter === f} onclick={() => (list.filter = f)}>{f}</button>
	{/each}
</div>

<ul aria-label="Todo items">
	{#each list.visible as todo (todo.id)}
		<li>
			<label>
				<input type="checkbox" checked={todo.done} onchange={() => list.toggle(todo.id)} />
				{todo.text}
			</label>
			<button type="button" aria-label={`Delete ${todo.text}`} onclick={() => list.remove(todo.id)}>x</button>
		</li>
	{:else}
		<li>Nothing to do</li>
	{/each}
</ul>

<p>{list.remaining} remaining</p>
```

**Component test:** `src/lib/components/Todos.svelte.spec.ts`

```ts
import { page, userEvent } from 'vitest/browser';
import { describe, expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import Todos from './Todos.svelte';

describe('Todos', () => {
	it('adds, completes, filters and deletes todos', async () => {
		render(Todos);
		await expect.element(page.getByText('Nothing to do')).toBeInTheDocument();

		const input = page.getByLabelText('New todo');
		await input.fill('Buy milk');
		await userEvent.keyboard('{Enter}');
		await input.fill('Walk dog');
		await page.getByRole('button', { name: 'Add' }).click();

		await expect.element(page.getByRole('listitem')).toHaveLength(2);
		await expect.element(input).toHaveValue('');
		await expect.element(page.getByText('2 remaining')).toBeInTheDocument();

		await page.getByRole('checkbox', { name: 'Buy milk' }).click();
		await expect.element(page.getByText('1 remaining')).toBeInTheDocument();

		await page.getByRole('button', { name: 'done' }).click();
		await expect.element(page.getByRole('listitem')).toHaveLength(1);
		await expect.element(page.getByRole('checkbox', { name: 'Buy milk' })).toBeInTheDocument();
		await expect.element(page.getByRole('checkbox', { name: 'Walk dog' })).not.toBeInTheDocument();

		await page.getByRole('button', { name: 'all' }).click();
		await page.getByRole('button', { name: 'Delete Walk dog' }).click();
		await expect.element(page.getByRole('listitem')).toHaveLength(1);
	});
});
```

**Route and E2E test:** `src/routes/todos/+page.svelte` renders `<Todos />` under an `<h1>`, and:

```ts
import { expect, test } from '@playwright/test';

test('user can add and complete a todo', async ({ page }) => {
	await page.goto('/todos');
	await page.getByLabel('New todo').fill('Write tests');
	await page.getByRole('button', { name: 'Add' }).click();

	const items = page.getByRole('list', { name: 'Todo items' }).getByRole('listitem');
	await expect(items).toHaveCount(1);
	await expect(items).toContainText('Write tests');
	await page.getByRole('checkbox', { name: 'Write tests' }).check();
	await expect(page.getByText('0 remaining')).toBeVisible();
});
```

The list has `aria-label="Todo items"` because the scaffold’s layout contains another list; without scoping, `getByRole('listitem')` violates Playwright’s strict mode.

## Drill 3: Guestbook with a form action

**Spec.** A page `/guestbook` lists entries and has a form with “Name” and “Message”. Name is required; the message needs at least 3 characters. Errors show next to the fields and the inputs keep their values. On success show “Thanks for signing!”. The form must work without JavaScript and be enhanced with it.

**Server logic:** `src/lib/server/guestbook.ts`

```ts
export interface Entry {
	name: string;
	message: string;
}

// Demo only: module state is shared by every user of the server process.
const entries: Entry[] = [];

export function listEntries(): Entry[] {
	return [...entries];
}

export function validate(name: unknown, message: unknown) {
	const errors: Partial<Record<keyof Entry, string>> = {};
	if (typeof name !== 'string' || name.trim().length === 0) errors.name = 'Name is required';
	if (typeof message !== 'string' || message.trim().length < 3)
		errors.message = 'Message must be at least 3 characters';
	return errors;
}

export function addEntry(entry: Entry) {
	entries.push({ name: entry.name.trim(), message: entry.message.trim() });
}
```

**Load and action:** `src/routes/guestbook/+page.server.ts`

```ts
import { fail } from '@sveltejs/kit';
import { addEntry, listEntries, validate } from '#lib/server/guestbook.js';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = () => {
	return { entries: listEntries() };
};

export const actions = {
	default: async ({ request }) => {
		const data = await request.formData();
		const name = data.get('name');
		const message = data.get('message');

		const errors = validate(name, message);
		if (Object.keys(errors).length > 0) {
			return fail(400, { name: String(name ?? ''), message: String(message ?? ''), errors });
		}

		addEntry({ name: String(name), message: String(message) });
		return { success: true };
	}
} satisfies Actions;
```

**Page:** `src/routes/guestbook/+page.svelte`

```html
<script lang="ts">
	import { enhance } from '$app/forms';
	import type { PageProps } from './$types';

	let { data, form }: PageProps = $props();
</script>

<h1>Guestbook</h1>

<form method="POST" use:enhance>
	<label>
		Name
		<input name="name" value={form?.name ?? ''} aria-invalid={!!form?.errors?.name} />
	</label>
	{#if form?.errors?.name}<p role="alert">{form.errors.name}</p>{/if}

	<label>
		Message
		<textarea name="message" aria-invalid={!!form?.errors?.message} value={form?.message ?? ''}></textarea>
	</label>
	{#if form?.errors?.message}<p role="alert">{form.errors.message}</p>{/if}

	<button>Sign</button>
</form>

{#if form?.success}<p role="status">Thanks for signing!</p>{/if}

<ul aria-label="Entries">
	{#each data.entries as entry, i (i)}
		<li><strong>{entry.name}</strong>: {entry.message}</li>
	{/each}
</ul>
```

**Unit tests (Node):** `src/lib/server/guestbook.spec.ts` and `src/routes/guestbook/page.server.spec.ts`

```ts
import { describe, expect, it } from 'vitest';
import { validate } from './guestbook';

describe('validate', () => {
	it('accepts a valid entry', () => {
		expect(validate('Ann', 'Hello!')).toEqual({});
	});

	it('reports each invalid field', () => {
		expect(validate('  ', 'hi')).toEqual({
			name: 'Name is required',
			message: 'Message must be at least 3 characters'
		});
	});
});
```

```ts
import { describe, expect, it } from 'vitest';
import { isActionFailure } from '@sveltejs/kit';
import { actions, load } from './+page.server';

function post(fields: Record<string, string>) {
	const body = new FormData();
	for (const [k, v] of Object.entries(fields)) body.set(k, v);
	const request = new Request('http://localhost/guestbook', { method: 'POST', body });
	return actions.default({ request } as Parameters<typeof actions.default>[0]);
}

describe('guestbook action', () => {
	it('fails with 400 and echoes input when invalid', async () => {
		const result = await post({ name: '', message: 'yo' });
		expect(isActionFailure(result)).toBe(true);
		expect(result).toMatchObject({ status: 400, data: { message: 'yo' } });
	});

	it('stores a valid entry that load then returns', async () => {
		const result = await post({ name: 'Ann', message: 'Nice site' });
		expect(result).toEqual({ success: true });

		const data = await load({} as Parameters<typeof load>[0]);
		expect(data).toMatchObject({ entries: [{ name: 'Ann', message: 'Nice site' }] });
	});
});
```

**E2E tests, including the no-JavaScript path:** `src/routes/guestbook/guestbook.e2e.ts`

```ts
import { expect, test } from '@playwright/test';

test.describe('guestbook', () => {
	test('shows validation errors', async ({ page }) => {
		await page.goto('/guestbook');
		await page.getByRole('button', { name: 'Sign' }).click();
		await expect(page.getByRole('alert').first()).toHaveText('Name is required');
	});

	test('adds an entry', async ({ page }) => {
		await page.goto('/guestbook');
		await page.getByLabel('Name').fill('Playwright');
		await page.getByLabel('Message').fill('Hello from e2e');
		await page.getByRole('button', { name: 'Sign' }).click();

		await expect(page.getByRole('status')).toHaveText('Thanks for signing!');
		await expect(page.getByRole('list', { name: 'Entries' })).toContainText('Playwright: Hello from e2e');
	});
});

test.describe('without JavaScript', () => {
	test.use({ javaScriptEnabled: false });

	test('the form still works', async ({ page }) => {
		await page.goto('/guestbook');
		await page.getByLabel('Name').fill('NoJS');
		await page.getByLabel('Message').fill('Progressive enhancement');
		await page.getByRole('button', { name: 'Sign' }).click();
		await expect(page.getByText('NoJS: Progressive enhancement')).toBeVisible();
	});
});
```

## Two extra verified examples

**A component that reads `$app/state`**, tested by mocking the module and passing a snippet built with `createRawSnippet`:

```html
<script lang="ts">
	import { page } from '$app/state';
	import type { Snippet } from 'svelte';

	let { href, children }: { href: string; children: Snippet } = $props();
	const current = $derived(page.url.pathname === href);
</script>

<a {href} aria-current={current ? 'page' : undefined}>{@render children()}</a>
```

```ts
import { page } from 'vitest/browser';
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { createRawSnippet } from 'svelte';
import NavLink from './NavLink.svelte';

vi.mock('$app/state', () => ({
	page: { url: new URL('http://localhost/about') }
}));

const text = (t: string) => createRawSnippet(() => ({ render: () => `<span>${t}</span>` }));

describe('NavLink', () => {
	it('marks the current page', async () => {
		render(NavLink, { href: '/about', children: text('About') });
		await expect.element(page.getByRole('link', { name: 'About' })).toHaveAttribute('aria-current', 'page');
	});

	it('does not mark other pages', async () => {
		render(NavLink, { href: '/blog', children: text('Blog') });
		await expect.element(page.getByRole('link', { name: 'Blog' })).not.toHaveAttribute('aria-current');
	});
});
```

**An `$effect` tested without a component**, using `$effect.root` and `flushSync`:

```ts
import { flushSync } from 'svelte';
import { describe, expect, it } from 'vitest';

describe('effects in a unit test', () => {
	it('runs an effect inside $effect.root after flushSync', () => {
		const log: number[] = [];
		const cleanup = $effect.root(() => {
			let count = $state(0);
			$effect(() => {
				log.push(count);
			});

			flushSync();
			expect(log).toEqual([0]);

			count = 1;
			flushSync();
			expect(log).toEqual([0, 1]);
		});
		cleanup();
	});
});
```

## Drills 4–6: unseen practice

Do these when you have spare time, with a timer, using the 45-minute routine and Claude Code. There are no solutions on purpose: judge yourself with the review checklist, and by whether all three commands pass.

### Drill 4: Star rating

- Props: `value` (`$bindable`, default 0), `max` (default 5), `readonly`, `onchange`.
- A `role="radiogroup"` with a label; each star is a `role="radio"` button named “1 star”, “2 stars”…, with `aria-checked`.
- Click selects; ArrowRight/ArrowLeft change the value within 1..max; `readonly` ignores input.
- Component tests: rendering, click plus `onchange`, keyboard, readonly, and `bind:value` through a small harness component.
- E2E: a `/rating` page showing “You rated N”.

### Drill 5: Searchable list

- Props: `items: { id: string; name: string }[]`, `placeholder`.
- A labelled search input; the list shows items whose name contains the query, case-insensitively; “No results” when empty; a live “N results” count (`role="status"`).
- Use `$derived` for the filtered list (no `$effect`).
- Stretch: debounce the query by 200 ms. Test it with `vi.useFakeTimers()` in the component test, or test the debounce helper separately.
- E2E: a `/search` page whose `+page.server.ts` load returns the items; type, see the filtered list. Stretch: keep the query in the URL (`?q=`) with a GET form so a reload keeps the results.

### Drill 6: Accordion (disclosure)

- Props: `items: { id: string; title: string; content: string }[]`, `multiple` (default false).
- Each header is a `<button aria-expanded aria-controls>` (use `$props.id()` for ids) inside a heading; panels are hidden when collapsed.
- With `multiple = false`, opening one closes the others.
- Component tests: initial state, toggle, single versus multiple mode, `aria-expanded` values.
- E2E (single mode): open the first section, then the second, and check that the second section’s content is visible and the first one’s is hidden again.

## Things that commonly go wrong live, and the fix

| Symptom | Likely cause | Fix |
|---|---|---|
| `rune_outside_svelte` in a test | Test file lacks `.svelte` in the name | Rename to `*.svelte.spec.ts` |
| `effect_orphan` | `$effect` created outside a component or root | Wrap in `$effect.root`, call `flushSync()`, clean up |
| Component test cannot find an element by role | Markup is not accessible (a `div` with `onclick`, an input without a label) | Fix the markup, not the test |
| `toHaveTextContent` fails with extra text | The element’s full text includes child text | Assert on a more specific element |
| Playwright “strict mode violation” | Locator matches several elements | Scope it with a parent locator or a name |
| E2E click does nothing, intermittently | Clicked before hydration | Assert on results with retrying assertions; wait for a hydration marker |
| E2E shows stale behaviour | With `reuseExistingServer`, Playwright reused a preview server running an old build | Stop the old preview server so the next run rebuilds |
| `Cannot find module './$types'` | Types not generated | `npx svelte-kit sync` (or `npm run check`) |
| Generated code uses `export let` / `on:click` / `$lib` | Model defaulted to old syntax | Point at `CLAUDE.md`, ask it to fix, and say why |
