# Day 2: Svelte 5 Components: Templates, Snippets, Bindings, Context and SSR

**Goal for today:** build a non-trivial component (a todo list) with a keyed each block, bindings and a `.svelte.ts` class, explain snippets, and explain what runs on the server versus in the browser.

## Read (45 min)

1. **Svelte 6**, “Attributes and props”, “Events”, “Logic blocks”, “`class` and `style:`”. *Skim* “Local declarations”.
2. **Svelte 7**, “Snippets”, “Composition patterns”, “`$bindable` as a contract”. *Skim* “Dynamic components and recursion”.
3. **Svelte 8**, “How a binding works”, “Input bindings”, “Function bindings”, “Component bindings and ownership”.
4. **Svelte 12**, “Context”, “Shared state with runes: patterns”, “Anti-patterns”. *Skim* “Stores”.
5. **Svelte 14**, “What the server build runs, and what it skips”, “Hydration”, “SSR pitfalls”.
6. *Skim* **Svelte 9** “Attachments”, and **Svelte 17** “Semantic HTML first” (the a11y warnings).

## Core notes (20 min)

### Template essentials

```html
{#if user}…{:else if loading}…{:else}…{/if}

{#each todos as todo (todo.id)}   <!-- always key by a stable id -->
	<li>{todo.text}</li>
{:else}
	<li>Nothing to do</li>
{/each}

{#await promise}…{:then value}…{:catch error}…{/await}

{#key selectedId}<Editor />{/key}  <!-- destroy and recreate when the key changes -->
```

- **Key each blocks** by a unique, stable primitive (`todo.id`), never the index. Without a key, rows are matched by position, so per-row state (inputs, transitions, component state) ends up attached to the wrong item after a reorder or delete.
- `{#await}` renders only the pending branch on the server.
- `class` accepts strings, arrays and objects (`class={['btn', { active }]}`); prefer it over `class:active`. `style:color={c}` sets one property.
- `{@html}` is **not sanitised**. It is the main XSS vector in Svelte apps.
- Events: `onclick`, `oninput` and so on are plain attributes. Many are **delegated** to the app root; for manual listeners use `on()` from `svelte/events` so ordering works.

### Snippets

A **snippet** is a named piece of markup that can take arguments. You declare it in the template with `{#snippet name(args)}…{/snippet}` and draw it with `{@render name(args)}`. A snippet is to markup what a function is to code: write it once, call it wherever it is needed, with different arguments each time. Snippets replace Svelte 4's slots.

**Why we need them.** Snippets solve two problems that come up in almost every app:

1. **Repeated markup inside one component.** Without snippets, the only way to avoid copying the same ten lines of markup is to make a new component, with a new file and props for everything it needs. A snippet is declared next to where it is used and can read the component's variables directly.
2. **Letting the parent decide how part of a child looks.** A list, table or dropdown knows *where* each row goes and *which* data it holds; the page that uses it knows *what* a row should look like. The child calls a snippet and passes in the data; the parent writes the markup. Slots did this badly: `let:` directives, named slots and `$$slots`. A snippet is an ordinary value, so you can pass it as a prop, check it with `if` and give it a type.

#### Passing a snippet to a component

```html
<!-- List.svelte -->
<script>
	let { items, row } = $props();
</script>

<ul>
	{#each items as item}
		<li>
			{@render row(item)}
		</li>
	{/each}
</ul>

<!-- App.svelte -->
<List {items}>
	{#snippet row(item)}
		<strong>{item.name}</strong> - ${item.price}
	{/snippet}
</List>
```

- `List` owns the structure: the `<ul>`, the loop and the `<li>`. `App` owns how a row looks. `List` knows nothing about names or prices, so the same `List` can show products, users or todos. This is the **render prop** pattern, also called a headless component.
- A snippet declared **between a component's tags** becomes a prop of the same name, here `row`. `List` calls it with `{@render row(item)}`, so the child chooses the argument and the parent chooses the markup.
- The `$` in `${item.price}` is plain text: a dollar sign in front of the price.
- Content between the tags that is **not** inside a `{#snippet}` becomes the `children` snippet, rendered with `{@render children()}`.
- You can also declare the snippet anywhere in `App`'s template and pass it explicitly: `<List {items} {row} />`.

With TypeScript, a snippet prop is typed with `Snippet<[...]>`, a **tuple** of its argument types. `generics` makes `List` work for any item type:

```html
<script lang="ts" generics="T">
	import type { Snippet } from 'svelte';
	let { items, row }: { items: T[]; row?: Snippet<[T]> } = $props();
</script>

<ul>
	{#each items as item}
		<li>
			{#if row}{@render row(item)}{:else}{String(item)}{/if}
		</li>
	{/each}
</ul>
```

Here `row` is optional, and `List` falls back to plain text when the parent passes none. Rendering an `undefined` snippet throws, so an optional snippet needs `{#if}` or `{@render row?.(item)}`. Snippets are not components, so they have no `<script>` and no state of their own; inside one you can use `{@const}`, blocks and components.

#### Reusing a snippet within the same component

```html
<!-- Cart.svelte -->
<script>
	let { items, currency = '$' } = $props();
	let total = $derived(
		items.reduce((sum, item) => sum + item.price, 0)
	);
</script>

{#snippet money(amount)}
	<span class="money">{currency}{amount.toFixed(2)}</span>
{/snippet}

<ul>
	{#each items as item (item.id)}
		<li>{item.name}: {@render money(item.price)}</li>
	{/each}
</ul>
<p>Total: {@render money(total)}</p>

<style>
	.money { font-variant-numeric: tabular-nums; }
</style>
```

- `money` is written once and rendered for every row and for the total. Changing the format is a one-line change.
- A snippet **sees the variables around it**: `money` reads `currency` straight from the component's script without taking it as an argument. When `currency` changes, every place that renders `money` updates.
- A snippet is visible in the block where it is declared and in that block's children (snippets declared at the top level of the template are visible everywhere in the template). A snippet can render itself, which is how you draw a tree of comments or folders.
- Styles follow the file that **declares** the snippet: the `.money` rule above applies wherever `money` is rendered, even inside a child component.

#### Sharing a snippet between components

There are two ways to share a snippet:

1. **As a prop**, as with `List` above: the snippet lives in one component and is passed down to another.
2. **As an export** (Svelte 5.5 and later). A snippet declared at the top level of a `.svelte` file can be exported from its `<script module>` block and imported like a function:

```html
<!-- format.svelte -->
<script module>
	export { money };
</script>

{#snippet money(amount)}
	<span class="money">${amount.toFixed(2)}</span>
{/snippet}

<!-- Cart.svelte, Invoice.svelte, ... -->
<script>
	import { money } from './format.svelte';
	let { total } = $props();
</script>

<p>Total: {@render money(total)}</p>
```

An exported snippet can use only its arguments, module-level declarations and other top-level snippets, never the instance `<script>`'s variables, because there is no single component instance to read them from. That is why `currency` from `Cart` became a fixed `$` here: pass it as an argument if it varies.

#### Snippet or component?

| | Snippet | Component |
|---|---|---|
| State, effects, lifecycle | None of its own; reads the declaring component's | Its own |
| Surrounding variables | Visible (lexical scope) | Only through props or context |
| Styles | The declaring file's `<style>` | Its own `<style>` |
| Reuse | Same file; elsewhere as a prop or a `<script module>` export | Anywhere, by import |
| Typical use | Repeated markup; rows, cells, headers and empty states passed into a child | Self-contained UI with behaviour, tested on its own |

- **Use a snippet** when the markup belongs to one component and changes only with a few values, when it needs that component's variables, or when a parent should decide how part of a child renders.
- **Use a component** when the markup needs its own state, effects or styles, when it should be tested on its own, or when several features in the app need it.
- A common path: start with a snippet, and turn it into a component once it grows its own state or a second feature needs it.
- In an interview, the one-liner is: *a component is a unit of behaviour; a snippet is a unit of markup.*

### Bindings

- `bind:value`, `bind:checked`, `bind:group` (radios give one value, checkboxes give an array), `bind:this`.
- Number and range inputs give numbers. An empty number input gives `null` in Svelte 5.57 (the docs say `undefined`), so type the state as `number | null`.
- A component prop is bindable only if the child declares it with `$bindable()`. Every component in a chain of bindings must declare it.
- **Function bindings** (Svelte 5.9 and later). A normal binding copies the value both ways unchanged: whatever the user types lands in the variable as is. A function binding puts **two functions** in place of the variable, separated by a comma: a **getter**, which returns what the input should show, and a **setter**, which Svelte calls with the new value whenever the user changes it. You decide what is actually stored.

  ```html
  <script>
  	let username = $state('');
  </script>

  <input bind:value={
  	() => username,
  	(v) => (username = v.toLowerCase())
  } />
  ```

  Type `Alice` and `username` holds `alice`; the input shows `alice` too, because it reads its value back through the getter. The same shape covers validation (refuse or clamp the value in the setter), formatting and unit conversion (store metres, show centimetres). Before function bindings you bound to a second variable and copied it into the real one with an `$effect`. That runs a step late, can loop, and writing state from an effect is an anti-pattern.

- **Runes mode and each blocks.** Svelte 5 compiles each component in one of two modes. **Runes mode** is on as soon as the component uses any rune (`$state`, `$props`, `$derived`, ...) or sets `<svelte:options runes />`; this is the Svelte 5 way, and everything in this course uses it. Otherwise the component is in **legacy mode** and follows the Svelte 4 rules (`let` is reactive by itself, `$:` statements, `export let` props). The mode is chosen per component, so old and new components can live in one app.

  One difference matters for bindings. In an each block, `todo` is just a local name for the current item. Legacy mode quietly rewrote `todo = …` into `todos[i] = …`; runes mode dropped that hidden rewrite, so **assigning or binding to the each variable itself is a compile error**. Bind to a property of the item, or go through the array and index:

  ```html
  <script>
  	let todos = $state([
  		{ text: 'Write tests', done: false }
  	]);
  	let tags = $state(['svelte', 'kit']);
  </script>

  {#each todos as todo}
  	<!-- works: updates the item in todos -->
  	<input type="checkbox" bind:checked={todo.done} />
  {/each}

  {#each tags as tag, i}
  	<!-- bind:value={tag} does not compile -->
  	<input bind:value={tags[i]} />
  {/each}
  ```

  `bind:checked={todo.done}` works because `todos` is deep `$state`: each `todo` is a reactive proxy, so writing its `done` property changes the item inside the array. Strings and numbers have no property to bind to, so for an array of them you bind through the index.

### Sharing state: props, context, modules

| Need | Use |
|---|---|
| Parent to child | Props |
| Child to parent | Callback props, or `$bindable` |
| A subtree (theme, form, tabs) | Context |
| Logic you want to unit test | A class with `$state`/`$derived` fields in a `.svelte.ts` file |
| Truly global, browser-only state | A module-level instance, **never** for per-user data under SSR |

#### Context

Props pass data one level down, from a parent to its direct child. When components several levels deep need the same thing, passing it through every component in between (**prop drilling**) gets tedious, and the middle components end up carrying props they never use. **Context** lets a component *provide* a value once; any component below it in the tree can *read* it directly, however deep it sits.

- **Scoped to the tree.** Only components inside the one that set the context can read it. Two `<Tabs>` on the same page each provide their own value, and their tabs never mix.
- **Per request on the server.** Each request renders its own component tree, so each request gets its own context. That makes context the safe place for per-user data (the current user, a cart), unlike module-level variables, which every request shares.
- **Set and read during initialisation only:** at the top level of `<script>`, never in an event handler, an effect or a `setTimeout`. Svelte works out who the parent is from the component being created at that moment, so call `get` once and keep the result in a variable.

`createContext<T>()` (Svelte 5.40+) creates a private key and returns a typed pair of functions, `[get, set]` (plus a third, `has`, since 5.57). `set` provides the value, `get` reads it, and `get` throws `missing_context` when no parent set one (for example, a `<Tab>` used outside `<Tabs>`).

**Example: a tabs component.** `Tabs` provides the state, while `Tab` (a button) and `TabPanel` (the content) read it, wherever they are placed inside `Tabs`.

```ts
// tabs.ts

export interface TabsState {
	readonly active: string;
	select(id: string): void;
}

export const [getTabs, setTabs] = createContext<TabsState>();
```

```html
<!-- Tabs.svelte -->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import { setTabs } from './tabs';

	let { active, children }: { active: string; children: Snippet } =
		$props();

	setTabs({
		get active() {
			return active;
		},
		select(id) {
			active = id;
		}
	});
</script>

<div class="tabs">{@render children()}</div>
```

```html
<!-- Tab.svelte -->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import { getTabs } from './tabs';

	let { id, children }: { id: string; children: Snippet } = $props();
	const tabs = getTabs();
</script>

<button
	role="tab"
	aria-selected={tabs.active === id}
	onclick={() => tabs.select(id)}
>
	{@render children()}
</button>
```

```html
<!-- TabPanel.svelte -->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import { getTabs } from './tabs';

	let { id, children }: { id: string; children: Snippet } = $props();
	const tabs = getTabs();
</script>

{#if tabs.active === id}
	<div role="tabpanel">{@render children()}</div>
{/if}
```

```html
<!-- Settings.svelte: using it -->
<script lang="ts">
	import Tabs from './Tabs.svelte';
	import Tab from './Tab.svelte';
	import TabPanel from './TabPanel.svelte';
</script>

<Tabs active="profile">
	<div role="tablist">
		<Tab id="profile">Profile</Tab>
		<Tab id="billing">Billing</Tab>
	</div>
	<TabPanel id="profile">Your name and photo.</TabPanel>
	<TabPanel id="billing">Your card and invoices.</TabPanel>
</Tabs>
```

How the pieces fit together:

1. `tabs.ts` calls `createContext` **once** and exports the pair, so the component that sets and the components that get share the same private key. The names `getTabs` and `setTabs` are yours to choose.
2. `Tabs` calls `setTabs(...)` while it is being created. The object it provides has the current tab (`active`) and a way to change it (`select`).
3. `Tab` and `TabPanel` call `getTabs()` and receive **that same object**. `Tab` reads `tabs.active` to mark itself selected and calls `tabs.select(id)` on click; `TabPanel` shows its content only when its `id` is the active one.
4. `Settings` passes no props between `Tabs` and its tabs; context connects them. Clicking “Billing” calls `select('billing')`, which assigns to `active` inside `Tabs`, and every `Tab` and `TabPanel` that reads `tabs.active` updates. (A component may assign to its own prop; the new value holds until the parent passes a different one.)

**Why `active` is a getter.** Context itself is not reactive: `set` stores the object you give it, once. Had `Tabs` written `setTabs({ active, select })`, the object would hold the string `'profile'` forever, and clicks would change nothing on screen. A getter reads the current `active` each time a child asks, and because the child reads it in its template, Svelte tracks it. Providing a `$state` object, or an instance of a class with `$state` fields, works the same way: change its **properties** and children update. What never works is **reassigning** the variable after `set`: children keep the object they were given and never see the new one.

#### Stores

- Stores (`writable`, `$store`) still work but are no longer needed for most state. `$app/stores` is **removed** in SvelteKit 3 (use `$app/state`).

### SSR and hydration: what runs where

| Runs on the server | Does **not** run on the server |
|---|---|
| Instance `<script>`, `$state`, `$derived` (when read), markup, `onDestroy`, `$props.id()` | `$effect`, `onMount`, attachments, event handlers |

- Anything that needs `window`, `document` or `localStorage` goes in `onMount`, an effect, an attachment or an event handler.
- **Module-level state is shared by every request** on a server process. A `$state` in a module that you write per user during SSR leaks data between users. Use context (or SvelteKit’s `event.locals`) for per-request state.
- Hydration walks the server HTML using comment markers and attaches behaviour. Text mismatches are repaired; structural mismatches warn `hydration_mismatch` and the tree is re-mounted. Typical causes: `Date.now()`, `Math.random()`, or reading `window` during render.

### Attachments

**Attachments** (Svelte 5.29+) are element-level lifecycle functions. Svelte calls an attachment with the DOM element once the element is mounted, and lets you clean up when the element is removed. Use one whenever code needs the real element: wrapping a third-party DOM library (Chart.js, Tippy.js, GSAP), trapping focus in a modal, handling “click outside”, measuring or focusing an element.

An attachment is a plain function that receives the element and may return a **cleanup** function. It runs inside an effect: if any `$state` it reads changes, Svelte runs the cleanup and then the attachment again.

```html
<script>
	let color = $state('lightblue');

	function paint(element) {
		// runs on mount and whenever `color` changes
		element.style.backgroundColor = color;

		// cleanup (optional): before a re-run, and on removal
		return () => {
			element.style.backgroundColor = '';
		};
	}
</script>

<div {@attach paint}>Hello!</div>
<button onclick={() => (color = 'pink')}>Pink</button>

<!-- or write it inline -->
<input {@attach (el) => el.focus()} />
```

- `paint` runs once the `<div>` is in the DOM. It reads `color`, so clicking “Pink” runs the cleanup and then `paint` again with the new colour. When the `<div>` is removed, the cleanup runs one last time.
- Like every effect, attachments run **only in the browser**, never during server rendering, so `window`, `document` and third-party DOM libraries are safe to use inside them.
- **Arguments:** write a function that takes the arguments and *returns* the attachment, then call it in the markup. When an argument changes, the old attachment is cleaned up and a new one runs. Here the chart is destroyed and redrawn whenever `sales` changes:

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

- An element can have several attachments: `<div {@attach a} {@attach b}>`.
- **On components:** `<Button {@attach tooltip('Save')}>` hands the attachment to `Button` as part of its props. If `Button` spreads its props onto an element (`let { children, ...rest } = $props();` and `<button {...rest}>`), the attachment lands on that `<button>`. That is how a component library lets you attach behaviour to the element inside its components.
- **Old `use:` syntax.** Svelte 4 had *actions* (`use:name`), which run once and do not re-run when their argument changes. Do not write new ones. You will still meet the syntax in SvelteKit's `use:enhance` for forms (Day 4), and `fromAction` from `svelte/attachments` turns an old action from a library into an attachment.

### Accessibility, because it shows in live coding

- Use real elements: a `<button>` for actions, a `<label>` for inputs, a `<ul>`/`<li>` for lists. The compiler’s `a11y_*` warnings push you there; do not silence them.
- Role-based test locators (`getByRole('button', { name: 'Add' })`) only work if your markup is accessible. Writing accessible markup makes your tests easier to write.
- `$props.id()` gives SSR-stable unique ids for `for`/`aria-*` relationships.

## Hands-on (40 min)

1. Create `src/lib/todos.svelte.ts` with a `TodoList` class: `items` (`$state`), `filter` (`$state`), `visible` and `remaining` (`$derived`), and arrow-function methods `add`, `toggle`, `remove`.
2. Create `src/lib/components/Todos.svelte`: a form with a labelled input bound to `draft`, a filter button group (`aria-pressed`), a keyed `{#each}` with an `{:else}` row, checkboxes and delete buttons with accessible names, and a “N remaining” line.
3. Add a `src/routes/todos/+page.svelte` that renders it.
4. Compare with Drill 2 in the live-coding playbook.
5. Stretch: turn the list rows into a `row` snippet prop so the parent can customise how each todo renders.

## Quiz (15 min)

1. Why should each blocks be keyed, and why is the index a bad key?
2. What replaced slots in Svelte 5? Show the markup for rendering an optional `footer` that receives one string argument.
3. What does `$bindable()` do, and what happens if a parent uses `bind:value` on a prop that is not bindable?
4. You put `let theme = $state('light'); setContext('theme', theme);` in a layout, then later write `theme = 'dark'`. Children do not update. Why? Fix it.
5. List four things that never run during SSR.
6. **Find the bug** (SvelteKit app, runs on a Node server):

   ```ts
   // src/lib/user.svelte.ts
   export const current = $state({ user: null as User | null });
   // set in a layout during SSR from data.user
   ```

7. What causes a hydration mismatch? Give two examples.
8. Why is `{@html}` dangerous, and what would you do before using it?
9. Multiple choice: what is the Svelte 5 replacement for `on:click|preventDefault={submit}`?

   a. `onclick|preventDefault={submit}`
   b. `onclick={(e) => { e.preventDefault(); submit(); }}`
   c. `on:click={submit} preventDefault`
   d. `use:preventDefault={submit}`

10. An attachment reads a `$state` variable. What happens when that variable changes, and when does the attachment's cleanup run?
11. With `bind:group`, what value type do you get for radios versus checkboxes?
12. When do you choose context over a module-level singleton?
13. What does `createContext` return, and what happens if `get` is called when no ancestor called `set`?
14. In a test or a library, how do you make reactive state testable without mounting a component?
15. What does `{#key value}` do, and when is it the right tool?
