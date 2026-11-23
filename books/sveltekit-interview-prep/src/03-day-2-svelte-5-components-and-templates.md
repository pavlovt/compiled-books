# Day 2: Svelte 5 Components: Templates, Snippets, Bindings, Context and SSR

**Goal for today:** build a non-trivial component (a todo list) with a keyed each block, bindings and a `.svelte.ts` class, explain snippets, and explain what runs on the server versus in the browser.

## Read (45 min)

1. **Svelte 6**, “Attributes and props”, “Events”, “Logic blocks”, “`class` and `style:`”. *Skim* “Local declarations”.
2. **Svelte 7**, “Snippets”, “Composition patterns”, “`$bindable` as a contract”. *Skim* “Dynamic components and recursion”.
3. **Svelte 8**, “How a binding works”, “Input bindings”, “Function bindings”, “Component bindings and ownership”.
4. **Svelte 12**, “Context”, “Shared state with runes: patterns”, “Anti-patterns”. *Skim* “Stores”.
5. **Svelte 14**, “What the server build runs, and what it skips”, “Hydration”, “SSR pitfalls”.
6. *Skim* **Svelte 9** “Actions” and “Attachments”, and **Svelte 17** “Semantic HTML first” (the a11y warnings).

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

### Snippets replace slots

```html
<!-- Card.svelte -->
<script lang="ts">
	import type { Snippet } from 'svelte';
	let { title, children, footer }: { title: string; children: Snippet; footer?: Snippet<[string]> } = $props();
</script>

<section>
	<h2>{title}</h2>
	{@render children()}
	{@render footer?.(title)}
</section>

<!-- usage -->
<Card title="Hi">
	<p>This paragraph becomes the children snippet.</p>
	{#snippet footer(t)}<small>{t}</small>{/snippet}
</Card>
```

- Snippets are typed with `Snippet<[ArgTypes]>` (a tuple). Optional snippets need `?.()` or `{#if}`; rendering `undefined` throws.
- Snippets can take arguments, which is how you build headless or “render prop” components (for example a list that lets the parent render each row).

### Bindings

- `bind:value`, `bind:checked`, `bind:group` (radios give one value, checkboxes give an array), `bind:this`.
- Number and range inputs give numbers. An empty number input gives `null` in Svelte 5.57 (the docs say `undefined`), so type the state as `number | null`.
- A component prop is bindable only if the child declares it with `$bindable()`. Every component in a chain of bindings must declare it.
- **Function bindings** (`bind:value={() => get, (v) => set(v)}`) replace the old “write state from an effect” patterns: validation, formatting, unit conversion.
- In runes mode, bind to `item.done` inside an each block, never to the each variable itself.

### Sharing state: props, context, modules

| Need | Use |
|---|---|
| Parent to child | Props |
| Child to parent | Callback props, or `$bindable` |
| A subtree (theme, form, tabs) | Context |
| Logic you want to unit test | A class with `$state`/`$derived` fields in a `.svelte.ts` file |
| Truly global, browser-only state | A module-level instance, **never** for per-user data under SSR |

```ts
// context.ts
import { createContext } from 'svelte';
export const [getTabs, setTabs] = createContext<TabsState>();
```

- `createContext<T>()` (Svelte 5.40+) returns typed `[get, set]` (plus `has` since 5.57). `get` throws if nothing was set. Call them during component initialisation only.
- Context values are not reactive by themselves. Put a `$state` object or a class instance in context and **mutate** it; reassigning the variable breaks the link.
- Stores (`writable`, `$store`) still work but are no longer needed for most state. `$app/stores` is **removed** in SvelteKit 3 (use `$app/state`).

### SSR and hydration: what runs where

| Runs on the server | Does **not** run on the server |
|---|---|
| Instance `<script>`, `$state`, `$derived` (when read), markup, `onDestroy`, `$props.id()` | `$effect`, `onMount`, actions, attachments, event handlers |

- Anything that needs `window`, `document` or `localStorage` goes in `onMount`, an effect, an attachment or an event handler.
- **Module-level state is shared by every request** on a server process. A `$state` in a module that you write per user during SSR leaks data between users. Use context (or SvelteKit’s `event.locals`) for per-request state.
- Hydration walks the server HTML using comment markers and attaches behaviour. Text mismatches are repaired; structural mismatches warn `hydration_mismatch` and the tree is re-mounted. Typical causes: `Date.now()`, `Math.random()`, or reading `window` during render.

### Actions and attachments (short)

- `use:action` runs once per element after mount, never on the server. Svelte 5.29+ adds **attachments**, `{@attach fn}`, which run in an effect, re-run when state they read changes, and can be passed through components. Prefer attachments in new code.

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

10. What is the difference between an action (`use:`) and an attachment (`{@attach}`)?
11. With `bind:group`, what value type do you get for radios versus checkboxes?
12. When do you choose context over a module-level singleton?
13. What does `createContext` return, and what happens if `get` is called when no ancestor called `set`?
14. In a test or a library, how do you make reactive state testable without mounting a component?
15. What does `{#key value}` do, and when is it the right tool?
