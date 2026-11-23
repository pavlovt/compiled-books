# Day 1: Svelte 5 Core: Runes, Reactivity and Props

**Goal for today:** explain how Svelte 5 reactivity works, without hesitating, and write a component with props, state, derived values and a callback prop.

## Read (45 min)

1. **Svelte 1**, “What Svelte is today”, “Anatomy of a `.svelte` file”, “`.svelte.js` and `.svelte.ts` modules”, “Runes: what they are and where they are valid”. *Skim* “Runes mode versus legacy mode”.
2. **Svelte 3**, “Primitives and the compiler’s decision”, “Deep state: proxies…”, “`$state` in classes”, “`$state.raw`”, “`$state.snapshot`”, “Passing state to functions”, “Sharing state across modules”, “Gotchas collected”.
3. **Svelte 4**, “`$derived`”, “`$effect`”, “When *not* to use `$effect`”, “Infinite loops”, “`$inspect`”.
4. **Svelte 7**, “`$props`: the whole story”, “Component events are callback props”.

## Core notes (20 min)

### The mental model

- Svelte 5 is a **compiler plus a small signals runtime**. A component is a function that runs **once**. There is no virtual DOM and no component re-render: when state changes, only the effects that read that state re-run, and each of them updates its own small piece of the DOM.
- Runes (`$state`, `$derived`, `$effect`, `$props`, `$bindable`, `$inspect`, `$host`) are **compiler keywords**, not functions. They work in `.svelte` files and in `.svelte.js`/`.svelte.ts` modules. In a plain `.ts` file you get `rune_outside_svelte`.
- A `.svelte` file has an instance `<script>` (runs per instance), an optional `<script module>` (runs once per module), markup, and a scoped `<style>`.

### `$state`

```ts
let count = $state(0);                 // primitive: a signal
let todos = $state([{ done: false }]); // array/object: a deep reactive proxy
todos[0].done = true;                  // fine-grained update, no reassignment needed
todos.push({ done: false });           // also reactive
```

- Plain objects and arrays become **deep proxies**. Class instances, `Map`, `Set` and `Date` are **not** proxied; use `SvelteMap`, `SvelteSet`, `SvelteDate`, `SvelteURL` from `svelte/reactivity`, or `$state` fields in your class.
- The proxy is not the original object: `===` against the original and `includes(original)` fail.
- `$state.raw(value)`: no proxy; only **reassignment** triggers updates. Use it for large data you replace wholesale (API responses).
- `$state.snapshot(proxy)`: a plain deep copy, for `console.log`, `structuredClone` or sending to an API.
- Classes: `count = $state(0)` as a field compiles to a getter/setter pair. Methods lose `this` when passed as callbacks (`onclick={obj.inc}`), so use arrow-function fields.
- **Sharing across modules:** you cannot export a `$state` variable that you reassign (`state_invalid_export`). Export an object you mutate, a class instance, or getter functions.
- Runes are not values. To pass reactivity into a function, pass a **getter** (`() => count`), not `count`.

### `$derived`

```ts
let total = $derived(items.reduce((s, i) => s + i.price, 0));
let label = $derived.by(() => {
	if (total > 100) return 'big';
	return 'small';
});
```

- **Lazy and memoised.** Recomputed only when read after a dependency changed. If the new value is identical (`===`) to the old one, nothing downstream updates.
- Dependencies are whatever was **read synchronously** during the last run. Wrap reads in `untrack(() => …)` to exclude them.
- Must be pure. Writing to state inside a derived throws `state_unsafe_mutation`.
- Since 5.25 you can **assign** to a derived (useful for optimistic UI). The assigned value holds until a dependency changes; then the derived recomputes from its expression again.

### `$effect`

```ts
$effect(() => {
	const id = setInterval(tick, interval); // reads `interval` → dependency
	return () => clearInterval(id);         // teardown before re-run and on destroy
});
```

- Runs **only in the browser**, after the DOM has updated, batched in a microtask. Never on the server.
- `$effect.pre` runs before DOM updates. `$effect.root` creates a scope you destroy yourself (needed outside components, for instance in tests); creating an `$effect` with no parent throws `effect_orphan`.
- `onMount` still exists and is fine. `onDestroy` is the only lifecycle function that also runs on the server. `beforeUpdate`/`afterUpdate` are legacy only.
- **When not to use `$effect`:** to compute a value from other state (use `$derived`), to react to a user action (put the code in the event handler), or to sync two pieces of state (use a function binding or writable derived). An effect that reads and writes the same state loops until `effect_update_depth_exceeded`.
- This is one of the most common Svelte 5 interview questions. The short answer: **effects are an escape hatch for talking to the outside world** (DOM APIs, timers, subscriptions, analytics), not for data flow.

### `$props` and component events

```html
<script lang="ts">
	interface Props {
		label: string;
		count?: number;
		onchange?: (n: number) => void;
		value?: string;
	}
	let { label, count = 0, onchange, value = $bindable(''), ...rest }: Props = $props();
</script>
```

- Destructured props stay reactive: reading `count` later reads the current prop. But `let x = $state(count)` captures only the **initial** value (warning `state_referenced_locally`). Use `$derived(count * 2)` to follow the prop.
- **Events are callback props.** `createEventDispatcher` and `on:click` are Svelte 4. Parents pass `onchange={(n) => …}`; children call `onchange?.(n)`.
- DOM events are attributes: `onclick={handler}`. There are no modifiers (`|preventDefault`); call `event.preventDefault()` yourself.
- A child should not mutate a prop object it does not own (`ownership_invalid_mutation` in dev). Use a callback, or make it `$bindable` so the parent can opt in with `bind:value`.
- `children` is the reserved prop for the default content (a snippet, Day 2).

### Svelte 4 → 5 vocabulary (always ready to say)

| Svelte 4 | Svelte 5 |
|---|---|
| `let x = 0` (implicitly reactive) | `let x = $state(0)` |
| `$: doubled = x * 2` | `let doubled = $derived(x * 2)` |
| `$: { sideEffect(x) }` | `$effect(() => sideEffect(x))` |
| `export let name` | `let { name } = $props()` |
| `on:click={f}` | `onclick={f}` |
| `createEventDispatcher` | callback props |
| `<slot />` | `{@render children()}` |
| `new App({ target })` | `mount(App, { target })` |

## Hands-on (40 min)

1. Scaffold the practice project (see “How to Use This Course”) and run the three test commands once.
2. Create `src/lib/components/Counter.svelte`: props `initial`, `min`, `max`, `step`, a callback prop `onchange`; `$state` for the count; `$derived` for “at min” and “at max”; buttons disabled at the bounds; the value in an `<output>`. The finished version is Drill 1 in the live-coding playbook. Try it yourself first and compare afterwards.
3. Render it from `src/routes/counter/+page.svelte` and try it in `npm run dev`.
4. Experiment: replace the `$derived` with `let atMax = count + step > max` (no rune). Click until the max. What happens, and why? Put the rune back.
5. Add `$inspect(count)` and watch the console; then remove it.

## Quiz (15 min)

1. In one sentence each: what does Svelte do at compile time, and what does it do at run time?
2. What is the difference between `$state([])` and `$state.raw([])`? When would you choose `raw`?
3. You write `let user = $state(fetchedUser); console.log(user === fetchedUser);`. What is logged, and why?
4. Why does this component not update `doubled` when the parent changes `count`? Fix it.

   ```ts
   let { count } = $props();
   let doubled = $state(count * 2);
   ```

5. Name three things you should *not* use `$effect` for, with the alternative for each.
6. When does an `$effect` run relative to the DOM update? Does it run during SSR?
7. What does the function returned from an `$effect` do, and when is it called?
8. **What happens?**

   ```ts
   let n = $state(0);
   $effect(() => { n = n + 1; });
   ```

9. How do you emit a “change” event from a Svelte 5 component to its parent?
10. A module `counter.svelte.ts` contains `export let count = $state(0); export function inc() { count++; }`. What error do you get, and what are two ways to fix it?
11. Multiple choice: which file can use `$state`?

    a. `utils.ts`
    b. `+page.server.ts`
    c. `vite.config.ts`
    d. `store.svelte.ts`

12. What is the difference between `$derived(expr)` and `$derived.by(fn)`?
13. Is `$derived` eager or lazy? What does “equality cut-off” mean?
14. You pass `onclick={cart.add}` where `cart` is a class instance with an `add()` method that uses `this`. It breaks. Why, and what is the idiomatic fix?
15. Translate to Svelte 5: `export let name; $: greeting = 'Hi ' + name; <button on:click={() => dispatch('greet', greeting)}>`.
