# Chapter 13: Async Svelte — `await` in Components, Boundaries and Forks (Experimental)

For most of its history Svelte, like every component framework, treated asynchronous data as someone else’s problem. You fetched in `onMount`, stored the result in state, tracked `loading` and `error` flags by hand, and wrote guard code (`{#if data}`) in every template. Svelte 5.36 introduced an alternative: you may write `await` directly in your component, in three new places, and the framework coordinates the UI around it. Updates that depend on pending async work are held back until the work finishes so the interface never shows a half-updated state; independent async work runs in parallel; loading UI is declared with a boundary; errors flow to the nearest error boundary; and a `fork` API lets frameworks start the work for a *future* UI state before the user commits to it.

This is the most consequential feature added to Svelte 5 after runes, and it is **still experimental in 5.57**. The documentation says so twice: “This feature is currently experimental, and you must opt in” and “the details of how `await` is handled (and related APIs like `$effect.pending()`) are subject to breaking changes outside of a semver major release”. The flag will be removed in Svelte 6, at which point the behaviour becomes the default. This chapter documents the model, the APIs (`$effect.pending`, `settled`, `$state.eager`, `getAbortSignal`, `fork`, `hydratable`), the error semantics, and the patterns that work well. Everything labelled “observed” was run against Svelte 5.57.2 with the async flag on, in a jsdom harness with fake timers replaced by real short delays.

> **Warning:** Do not ship business-critical code paths on an experimental API without pinning the Svelte version, wrapping usage in a thin internal layer, and reading the changelog on every upgrade. Part of the engineering value of this chapter is knowing exactly which parts are likely to move.

## Enabling the feature

The compiler option is `compilerOptions.experimental.async`. Where you set it depends on your toolchain; the documented form is `svelte.config.js`:

```js
// svelte.config.js
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

export default {
    preprocess: vitePreprocess(),
    compilerOptions: {
        experimental: {
            async: true
        }
    }
};
```

(The Svelte plugin options in `vite.config.ts` accept the same `compilerOptions`.) Without the flag, the compiler rejects any of the new usages with `experimental_async`: “Cannot use `await` in deriveds and template expressions, or at the top level of a component, unless the `experimental.async` compiler option is `true`”. The feature also requires runes mode; in legacy mode you get `legacy_await_invalid`.

Two runtime APIs are guarded separately: **`fork()` and `hydratable()` throw `experimental_async_required` at runtime unless the app was compiled with the flag**, even though both are exported from `'svelte'` with no experimental label on their doc pages. The flag adds an `import 'svelte/internal/flags/async'` to compiled output, and that import is what flips the runtime switch. Consequences worth stating: a library that calls `fork` or `hydratable` only works in apps that enabled the flag; and the flag is global to the runtime, not per component, because the runtime is shared.

Two further behaviours change when the flag is on:

- `tick()` becomes a race between `requestAnimationFrame` and `setTimeout` instead of “one microtask then `flushSync`”.
- `flushSync()` can no longer be called inside an effect (`flush_sync_in_effect`), and `setContext` must be called at initialisation (`set_context_after_init`). Both restrictions become the default in Svelte 6.

## Where `await` is allowed

The three new places, from the docs:

1.  at the top level of the component’s `<script>`;
2.  inside `$derived(...)` declarations;
3.  inside markup (text expressions, attributes, block expressions such as `{#if await ...}`, `{#each await ...}`, `{@const}`/declaration tags, `{@html await ...}`).

```html
<script lang="ts">
    let id = $state(1);

    const config = await loadConfig();                       // top-level script
    const user = $derived(await fetchUser(id));              // inside $derived
</script>

<h1>{user.name}</h1>
<p>{await fetchGreeting(id)}</p>                             // inside markup
```

What is *not* allowed. The compiler reports `illegal_await_expression`: “`use:`, `transition:` and `animate:` directives, attachments and bindings do not support await expressions”. I confirmed all of these at compile time:

| Placement | Result |
|------------------------------------|------------------------------------|
| `<div use:act={await p}>` | `illegal_await_expression` |
| `<div {@attach att(await p)}>` | `illegal_await_expression` |
| `<div transition:fade={{ duration: await p }}>` | `illegal_await_expression` |
| `animate:` parameters | same error |
| `bind:` expressions (with an `await` *inside the bound expression*) | same error |
| no `experimental.async` flag | `experimental_async` |
| legacy (non-runes) component | `legacy_await_invalid` |

Note that `bind:value={v}` placed next to an unrelated `{await x}` in the same component compiles fine: the restriction is about await *inside* these constructs. The reason is architectural: directives and attachments are set up after the element exists and are not themselves reactive “blocks” the batch can hold back.

A subtle point about `$derived(await ...)`: it can only be created inside an effect tree. Outside one, it throws `async_derived_orphan` (“Cannot create a `$derived(...)` with an `await` expression outside of an effect tree”). The explanation in the docs is instructive. Ordinary deriveds are lazy and can be garbage-collected, but an async derived must start its work *proactively* (waiting until something reads `{await getPromise()}` would be too late), so it uses an effect internally, and effects need an owner. A component’s initialisation provides one; a module-level `$derived(await ...)` in a `.svelte.ts` file, or inside a plain event handler, does not. Create async deriveds in component scripts (or inside `$effect.root`).

## The model: synchronised updates

Consider the documentation’s canonical example:

```html
<script lang="ts">
    let a = $state(1);
    let b = $state(2);

    async function add(a: number, b: number) {
        await new Promise((f) => setTimeout(f, 500)); // artificial delay
        return a + b;
    }
</script>

<input type="number" bind:value={a}>
<input type="number" bind:value={b}>

<p>{a} + {b} = {await add(a, b)}</p>
```

Increment `a` and the paragraph does **not** immediately show `2 + 2 = 3`. The change to `a` is part of a *batch* that also contains the pending `add(...)` call; the batch’s DOM effects are held until the promise resolves, then applied together, producing `2 + 2 = 4`. The UI never shows a state that no consistent set of data could produce — no tearing between “new inputs” and “old sum”.

I observed this directly with a component that logged its calls. After mounting and settling, calling `inc()` produced the sequence: DOM still `1 + 2 = 3` immediately after the flush, still `1 + 2 = 3` mid-flight (20 ms into a 50 ms request), and `2 + 2 = 4` once the promise resolved; the `add` function had been called exactly twice (initial and update).

Important properties of the model:

- **Batches.** State changes made in the same synchronous run (or microtask flush) form a batch. If any `await` expression in the component tree depends on state touched by the batch, the batch waits for that promise before committing its UI changes. A batch whose changes do not touch pending async work commits immediately.
- **Overlap.** The docs: “Updates can overlap — a fast update will be reflected in the UI while an earlier slow update is still ongoing.” If a slow batch is pending and a later, independent, fast batch resolves first, the fast one is applied. If the later batch *depends on the same state* as the earlier one, the newer value wins and the earlier result is discarded when it arrives (the effect is exactly “latest wins”).
- **Initial render.** The first time a boundary renders, there is nothing to hold; the `pending` snippet is shown until all awaits inside have resolved (next section). Without any boundary at all, the content simply does not appear until its async work finishes.
- **Concurrency.** The runtime runs independent async expressions in parallel. For two awaits in the markup, `<p>{await one(x)}</p><p>{await two(y)}</p>`, both functions run at the same time, “even though they are *visually* sequential”.

### Waterfalls and `await_waterfall`

Parallelism does not extend to *sequential* `await`s inside a script or inside an async function: those behave like any asynchronous JavaScript. The documented exception is subtle. Independent `$derived` declarations “will update independently, even though they will run sequentially when they are first created”:

```ts
// `b` will not be created until `a` has resolved,
// but once created they will update independently
let a = $derived(await one(x));
let b = $derived(await two(y));
```

The second derived is not even *created* until the first resolves (top-level script code after an `await` is itself suspended), so on first render you have a waterfall. In development the runtime warns with `await_waterfall`: “An async derived, `%name%` (%location%) was not read immediately after it resolved. This often indicates an unnecessary waterfall, which can slow down your app”. The fix from the warning’s documentation is to start the promises first and await them second:

```ts
let aPromise = $derived(one());
let bPromise = $derived(two());

let a = $derived(await aPromise);
let b = $derived(await bPromise);
```

Unrelated top-level awaits (`const config = await loadConfig(); const user = await loadUser();`) obviously also serialise; kick off both promises, then await.

```ts
const configP = loadConfig();
const userP = loadUser();
const config = await configP;
const user = await userP;
```

### Reactivity inside `await` expressions, and `await_reactivity_loss`

Normally a derived tracks what it reads synchronously. With `await`, Svelte rewrites the expression so that reads *after* an `await` in the same expression are also tracked. The docs’ example: `let total = $derived(await a + b)` tracks both `a` and `b`, “even though `b` is only read once `a` has resolved”.

That guarantee covers only awaits that are *visible* in the expression. If the `await` hides inside an async function, reads after it are not tracked, and you get `await_reactivity_loss`: “Detected reactivity loss when reading `%name%`. This happens when state is read in an async function after an earlier `await`”.

```ts
// loses reactivity on b
async function sum() { return await a + b; }
let total = $derived(await sum());

// fix: pass state in as arguments, so it is read before any await
async function sum(a: Promise<number>, b: number) { return await a + b; }
let total = $derived(await sum(a, b));
```

(If you intentionally read state after an await without wanting a dependency, wrap it in `untrack`; the warning is suppressed for reads inside `untrack`.) The principle for your own async functions: **read every piece of state you want tracked before the first `await`, and pass it in as an argument.**

## Loading UI: `<svelte:boundary>` and `pending`

```html
<svelte:boundary>
    <p>{await delayed('hello!')}</p>

    {#snippet pending()}
        <p>loading...</p>
    {/snippet}
</svelte:boundary>
```

The `pending` snippet is shown when the boundary is first created and stays until **all** awaits inside it have resolved; then the real content replaces it. Observed: a component with a pending snippet showed `loading` at mount, switched to `1 + 2 = 3` after the first resolution, and *never showed `loading` again* for later updates — the snippet is for the first render only. Subsequent async work is “globally coordinated” and invisible unless you ask about it.

Placement is a design decision. A boundary should wrap the *smallest region that can meaningfully be replaced by a placeholder*. One boundary at the app root gives you a single splash screen. Several boundaries give you independent regions that load and fail separately (a sidebar and a main pane), at the cost of the parts of the page appearing at different times. Boundaries nest: awaits belong to the *nearest* ancestor boundary; if a nested boundary has no `pending` snippet, its awaits are held by the enclosing boundary’s mechanism, so the outer one’s placeholder is what the user sees.

### `$effect.pending()`

After the first render, how do you show “saving…” or dim the stale content while a refresh is in flight? Use `$effect.pending()`, which “tells you how many promises are pending in the current boundary, not including child boundaries”:

```html
<script lang="ts">
    let a = $state(1);
    let b = $state(2);
    async function add(a: number, b: number) {
        await new Promise((f) => setTimeout(f, 500));
        return a + b;
    }
</script>

<button onclick={() => a++}>a++</button>
<button onclick={() => b++}>b++</button>

<p>{a} + {b} = {await add(a, b)}</p>

{#if $effect.pending()}
    <p>pending promises: {$effect.pending()}</p>
{/if}
```

Rules: it returns a number (0 when idle), it is scoped to the current boundary excluding children, and it must be called “inside an effect or derived” — in a template expression, in `$derived`, or in `$effect` — otherwise it throws `effect_pending_outside_reaction`. In my harness the counter read `0` after the initial resolution, `1` while an update was in flight, and `0` again when it landed.

A realistic use is a stale-content indicator:

```html
<div class:stale={$effect.pending() > 0} aria-busy={$effect.pending() > 0}>
    {#each await results as r (r.id)}<ResultRow {r} />{/each}
</div>
```

### `tick()` and `settled()`

```ts
tick(): Promise<void>          // pending state changes applied (or next microtask)
settled(): Promise<void>       // @since 5.36 — state changes AND async work resolved, DOM updated
```

The docs show the pattern for coordinating UI around an update:

```ts
import { tick, settled } from 'svelte';

async function onclick() {
    updating = true;

    // without this, the change to `updating` will be
    // grouped with the other changes, meaning it
    // won't be reflected in the UI
    await tick();

    color = 'octarine';
    answer = 42;

    await settled();

    // any updates affected by `color` or `answer`
    // have now been applied
    updating = false;
}
```

Here the `await tick()` is crucial: it forces `updating = true` into its own batch so it renders immediately; the following state changes form a second batch which may suspend on async work; `settled()` resolves when that batch has been applied.

Two behaviours I verified that the docs do not spell out, and that cause real bugs:

1.  **`settled()` waits for the batch you are currently building.** It is implemented as “ensure a batch exists, then wait for that batch”. Call it in the *same synchronous run* as the state change. In my test, `app.inc(); await settled();` waited the full 50 ms request and the DOM was updated afterwards. But `app.inc(); await tick(); await settled();` returned in about 2 ms with the DOM still stale: `tick()` had already moved the in-flight batch out of the “current” slot, so `settled()` created a fresh empty batch and resolved at once. Do not use `settled()` as a generic “is anything still loading” probe; use `$effect.pending()` for that.
2.  **With the flag on, `tick()` is a timing race, not a flush.** It resolves on `requestAnimationFrame` or the next `setTimeout`, whichever comes first, so it can resolve before an async batch finishes. It is “pending changes applied or the next tick”, not “all async work done”.

## Sync/async interplay: `$state.eager`

Synchronised updates are the right default but occasionally exactly wrong: a navigation bar that does not highlight the link you just clicked until the new page data arrives feels broken. `$state.eager(value)` (5.41) returns the latest `value` *immediately*, “even if the rest of the UI is suspending while async work (such as data loading) completes.”

```html
<script lang="ts">
    let query = $state('');
    const results = $derived(await search(query));
</script>

<input bind:value={query} />

<p>Searching for “{$state.eager(query)}”…</p>
<ul>
    {#each results as r (r.id)}<li>{r.title}</li>{/each}
</ul>
```

I observed the contrast in a harness component: after `setQuery('slow')` the eager text showed `slow` on the very next frame while the result paragraph still showed the previous result `A`; after `setQuery('fast')` the eager text showed `fast` and the result kept showing `A` until the latest request resolved, at which point it showed `FAST`. The doc’s own example is navigation:

```html
<nav>
    <a href="/" aria-current={$state.eager(pathname) === '/' ? 'page' : null}>home</a>
    <a href="/about" aria-current={$state.eager(pathname) === '/about' ? 'page' : null}>about</a>
</nav>
```

The docs’ guidance deserves repeating: “Use this feature sparingly, and only to provide feedback in response to user action — in general, allowing Svelte to coordinate updates will provide a better user experience.” Eager values create exactly the inconsistency synchronisation prevents (the label says “slow” while the list is the result for “a”). Use them for acknowledgement (what the user just did), not for data.

## Cancellation: `getAbortSignal()` and stale requests

Every async derived is re-run when its dependencies change, and an earlier run may still be in flight. `getAbortSignal()` (5.35) returns an `AbortSignal` that aborts “when the current derived/effect re-runs or is destroyed”. It can only be called inside a derived or effect (`get_abort_signal_outside_reaction` otherwise), and it must be called *synchronously* in the derived expression, which is why it appears in the call arguments:

```html
<script lang="ts">
    import { getAbortSignal } from 'svelte';

    let query = $state('svelte');

    async function search(q: string, signal: AbortSignal) {
        const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`, { signal });
        if (!res.ok) throw new Error(`search failed: ${res.status}`);
        return (await res.json()) as { id: string; title: string }[];
    }

    const results = $derived(await search(query, getAbortSignal()));
</script>
```

I instrumented a version of this with listeners on the signal. Setting the query to `'slow'` then immediately to `'fast'` logged `start a`, `abort a`, `start slow`, `abort slow`, `start fast`: each re-run aborted the previous run’s signal, the slow request’s result was never displayed, and the UI went directly from `A` to `FAST`. An aborted `fetch` rejects with `AbortError`; Svelte treats rejections from superseded runs as stale and does not surface them to boundaries, so you do not need to catch `AbortError` yourself in this pattern. (For non-derived code, such as an event handler that starts a request, you must manage your own `AbortController`.)

> **Senior tip:** Debounce at the *input* (a plain `$state` updated by the event handler after a timeout, or a `$state.eager` value for display plus a debounced value that feeds the derived), not inside the async function. The abort signal cancels network cost; it does not reduce the number of derivation runs.

## Error handling

Errors thrown by `await` expressions, by rejected promises feeding `$derived(await ...)`, and by any rendering or effect code inside a boundary go to the nearest `<svelte:boundary>`. A boundary has two ways to handle them, and either or both may be used:

```html
<svelte:boundary onerror={(e) => report(e)}>
    <UserCard {id} />

    {#snippet failed(error, reset)}
        <p>Could not load: {String(error)}</p>
        <button onclick={reset}>try again</button>
    {/snippet}
</svelte:boundary>
```

- `failed(error, reset)` is a snippet rendered *instead of* the boundary’s content. The `reset` function re-creates the content (re-running its initialisation, including its `await`s).
- `onerror(error, reset)` is a callback with the same arguments, for reporting or for managing UI outside the boundary.

Facts to hold:

- If a boundary handles an error (via `failed`, `onerror`, or both) “its existing content will be removed”. A boundary with neither does nothing.
- If `onerror` throws, or you rethrow, the error propagates to the **parent** boundary.
- **Boundaries do not catch everything.** “Errors occurring outside the rendering process (for example, in event handlers or after a `setTimeout` or async work) are *not* caught.” An `onclick` that throws, or a `fetch().then(...)` you started manually, bypass the boundary. Async work started *by* `$derived(await ...)` or markup awaits is part of rendering and *is* caught.
- `reset` is meant to be called once: after the first call it is a no-op with the warning `svelte_boundary_reset_noop`. Calling it **synchronously inside `onerror`** throws `svelte_boundary_reset_onerror`, because the boundary is still broken. Wait first:

```html
<svelte:boundary onerror={async (error, reset) => {
    fixTheError();
    await tick();
    reset();
}}>
    <Contents />
</svelte:boundary>
```

I verified the failed-snippet path: a child that threw during initialisation was replaced by the `failed` snippet (rendering `failed: boom`), `onerror` received the error exactly once, and after fixing the cause and clicking the button wired to `reset`, the failed snippet disappeared and the content rendered.

### What a failed async derived looks like to users

When `$derived(await fetchUser(id))` rejects:

- during the **first** render, the boundary shows `failed` (the pending snippet is replaced);
- during an **update** (a new `id`), the boundary also switches to `failed`, removing the stale content. If you would rather keep stale content visible and show an inline error, catch inside the async function and return a result type:

```ts
type Loaded<T> = { ok: true; value: T } | { ok: false; error: string };

async function safe<T>(p: Promise<T>): Promise<Loaded<T>> {
    try { return { ok: true, value: await p }; }
    catch (e) { return { ok: false, error: e instanceof Error ? e.message : String(e) }; }
}

const user = $derived(await safe(fetchUser(id, getAbortSignal())));
```

That moves error semantics out of the boundary and into data, which is often the right call for *expected* failures (404, validation) while boundaries remain the safety net for *unexpected* ones.

### Error reporting patterns

- Put a boundary at each major region with `onerror` calling your reporter and a `failed` snippet that offers retry; one at the app root as a last resort.
- Keep `reset` semantics in mind: reset re-runs the failed subtree, so make fetching idempotent.
- On the server, boundaries do nothing by default (“if an error occurs during rendering, the render as a whole will fail”); `transformError` on `render` changes that. See Chapter 14.

## Writable deriveds and optimistic UI

Since 5.25 a `$derived` can be assigned to. The value re-evaluates when its dependencies change, but in between you can write to it. Combined with async work this gives a compact optimistic-update pattern:

```html
<script lang="ts">
    let { initial = 0 }: { initial?: number } = $props();

    let serverCount = $state(initial);
    let shown = $derived(serverCount);        // reflects server truth; writable

    async function like() {
        shown += 1;                             // optimistic
        try {
            await api.like();
            serverCount += 1;                   // truth arrives; `shown` recomputes
        } catch {
            shown = serverCount;                // roll back
        }
    }
</script>

<button onclick={like}>♥ {shown}</button>
```

Run with a stubbed API: `shown` went `5 → 6` immediately on click, stayed `6` after the server confirmed (because `serverCount` became 6 and `shown` re-derived from it), and for a failing call went `6 → 7 → 6` after rollback. No flags are required for this pattern; it simply composes well with async because the optimistic value bypasses the synchronisation that would otherwise hold UI updates.

Two cautions: an optimistic assignment is overwritten the next time the derived’s dependencies change (that is the feature, but it means concurrent server updates can clobber it); and optimistic UI for lists is more naturally modelled by keeping the pending operations in state and deriving the displayed list from `server + pending`.

## `fork()`: speculative preloading

```ts
fork(fn: () => void): Fork            // @since 5.42; requires experimental.async at runtime
interface Fork { commit(): Promise<void>; discard(): void }
```

`fork` runs `fn`, which changes state, *in a separate batch that is not applied to the DOM*, so that the async work the new UI would trigger starts now. You then either `commit()` (apply the batch) or `discard()` (throw it away). The docs say it is “mainly intended for frameworks like SvelteKit to implement preloading when (for example) users signal an intent to navigate”, and give this menu example:

```html
<script lang="ts">
    import { fork, type Fork } from 'svelte';
    import Menu from './Menu.svelte';

    let open = $state(false);
    let pending: Fork | null = null;

    function preload() {
        pending ??= fork(() => { open = true; });
    }
    function discard() {
        pending?.discard();
        pending = null;
    }
</script>

<button
    onfocusin={preload}
    onfocusout={discard}
    onpointerenter={preload}
    onpointerleave={discard}
    onclick={() => {
        pending?.commit();
        pending = null;
        open = true;          // in case `pending` didn't exist (if it did, this is a no-op)
    }}
>open menu</button>

{#if open}
    <Menu onclose={() => (open = false)} />
{/if}
```

I ran a variant where `Menu` has a top-level `await` that logs when its loader runs and takes 30 ms. Result: immediately after `preload()` the log contained `menu load 1` (the loader had started), yet `#menu` was *not* in the DOM, and 60 ms later — loader long finished — it still was not in the DOM. After `await commit()`, `#menu` was in the DOM and the loader had still run exactly once. That is the contract: work happens at fork time, rendering happens at commit time, and the work is reused rather than repeated.

Rules and errors:

- `fork_timing`: “Cannot create a fork inside an effect or when state changes are pending”. Create forks from event handlers (or other places where no batch is pending), not from `$effect` or immediately after unflushed state changes. `await tick()` first if needed.
- `fork_discarded`: “Cannot commit a fork that was already discarded”. Committing after `discard()` throws; discarding after commit is ignored.
- A fork is only as good as the work it can reuse. If the speculative component creates *different* promises when it is really rendered (for example because the arguments include something that changed), nothing is saved.
- Library authors: calling `fork` makes your library require the flag at runtime. Treat `fork` as a framework-level primitive and expose preloading through your own API.

## Ordering changes under the flag

With `experimental.async: true`, effects run in a slightly different order. From the docs: “*block* effects like `{#if ...}` and `{#each ...}` now run before an `$effect.pre` or `beforeUpdate` in the same component”. The practical impact is rare: it matters only if you update state inside an effect (which you should avoid) and thereby depend on the old order to make an `{#if}` branch survive one more flush. The docs flag it as “very rare situations … it is possible to update a block that should no longer exist”.

Also on the list of flag-induced changes: `flush_sync_in_effect` (calling `flushSync` inside an effect is now an error) and `set_context_after_init` (context setters must run during initialisation, not after an `await`). For the second, structure components so the context is set before the first `await`:

```html
<script lang="ts">
    import { setStore } from './store.ts';

    const store = new Store();
    setStore(store);                // before any await

    await store.init();             // now safe
</script>
```

An `await` at the top level of a component also changes *when* the component’s later code runs: everything after it is suspended until the promise resolves, and the compiler arranges for dependent template expressions to wait via blocker promises (compiled output wraps the script in a `$.run([...])` sequence and passes `$$promises` to `$.template_effect`; this is private implementation detail, shown only to explain the behaviour). A practical consequence: a parent’s `onMount` and `$effect`s do not run until the awaits above them settle, so initialisation-order assumptions deserve a second look in components that await at the top level.

## Patterns

### Data-loading component with cancellation and retry

```html
<!-- UserPanel.svelte -->
<script lang="ts">
    import { getAbortSignal } from 'svelte';

    interface User { id: string; name: string; email: string }

    let { id }: { id: string } = $props();

    async function load(id: string, signal: AbortSignal): Promise<User> {
        const res = await fetch(`/api/users/${id}`, { signal });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    const user = $derived(await load(id, getAbortSignal()));
</script>

<h2>{user.name}</h2>
<p>{user.email}</p>
{#if $effect.pending()}<span class="spinner" aria-live="polite">updating…</span>{/if}
```

```html
<!-- Page.svelte -->
<script lang="ts">
    import UserPanel from './UserPanel.svelte';
    let id = $state('1');
</script>

<select bind:value={id}><option>1</option><option>2</option></select>

<svelte:boundary onerror={(e) => console.error(e)}>
    <UserPanel {id} />

    {#snippet pending()}<p>Loading user…</p>{/snippet}
    {#snippet failed(error, reset)}
        <p role="alert">{String(error)}</p>
        <button onclick={reset}>Retry</button>
    {/snippet}
</svelte:boundary>
```

The `$effect.pending()` inside `UserPanel` refers to the *nearest enclosing boundary* (the one in `Page`), because pending counts are attributed per boundary. Because the awaiting derived lives in a child while the indicator is also in the child, the indicator is rendered inside the boundary’s content and works; if you put the spinner outside the boundary (in `Page`, outside `svelte:boundary`) it belongs to the *parent* boundary and will not see the child’s pending work, since counts exclude child boundaries.

### Suspense-style layouts

Boundaries compose into a suspense-style layout: an outer boundary for the shell, inner boundaries for independent panes.

```html
<svelte:boundary>
    <Header />
    <div class="columns">
        <svelte:boundary>
            <Sidebar />
            {#snippet pending()}<SidebarSkeleton />{/snippet}
        </svelte:boundary>
        <svelte:boundary>
            <Feed />
            {#snippet pending()}<FeedSkeleton />{/snippet}
            {#snippet failed(e, reset)}<FeedError {e} {reset} />{/snippet}
        </svelte:boundary>
    </div>
    {#snippet pending()}<Splash />{/snippet}
</svelte:boundary>
```

Because Svelte starts independent async work in parallel, `Sidebar` and `Feed` fetch concurrently even though their boundaries render separately. Avoid waterfalls *across* components: if `Feed` needs data that `Sidebar` also needs, hoist the promise (or a shared cached loader) rather than awaiting in sequence.

### Request deduplication

Two components awaiting the same URL would issue two requests. Memoise promises in a module-level cache keyed by arguments for the *client*, and be careful on the server (Chapter 14): an unbounded module-level cache is shared by all requests. A scoped cache in context avoids both problems:

```ts
export class Loader {
    #cache = new Map<string, Promise<unknown>>();
    get<T>(key: string, fn: () => Promise<T>): Promise<T> {
        let p = this.#cache.get(key) as Promise<T> | undefined;
        if (!p) { p = fn(); this.#cache.set(key, p); p.catch(() => this.#cache.delete(key)); }
        return p;
    }
}
```

### Server rendering and `hydratable`

Async SSR is the other half of the feature (full treatment in Chapter 14): `render(App)` returns something you can `await`, so top-level awaits and markup awaits resolve on the server before `await render(...)` returns:

```ts
import { render } from 'svelte/server';
import App from './App.svelte';

const { head, body } = await render(App);
```

A boundary with a `pending` snippet is rendered on the server as *only* that snippet; its contents are skipped, so the client fills them in after hydration. Everything awaited *outside* such boundaries is resolved before the render completes.

The problem `hydratable` solves: on hydration the client re-runs the same awaits, blocking hydration while repeating work the server already did. `hydratable(key, fn)` (5.44) serialises the server’s result into the page head and returns it during hydration instead of calling `fn` again:

```html
<script lang="ts">
    import { hydratable } from 'svelte';
    import { getUser } from '$lib/db';

    const user = await hydratable('user', () => getUser());
</script>

<h1>{user.name}</h1>
```

Serialisation uses `devalue` (so `Map`, `Set`, `URL`, `BigInt` and even promises work), keys must be unique (library authors should prefix with the library name), and the call also works for stable random or time-based values (`hydratable('random', () => Math.random())`). It requires the async flag at runtime and adds an inline `<script>` that interacts with CSP; Chapter 14 covers nonces and hashes.

## Testing async components

Under the flag, assert on *settled* DOM, not intermediate frames:

- Prefer awaiting a condition (`await vi.waitFor(() => expect(el.textContent).toBe('2 + 2 = 4'))`) over fixed sleeps.
- For batch-level synchronisation, call `settled()` in the same synchronous run as the state change; remember that `await tick()` first would make it resolve immediately.
- Mock `fetch` or your loader with controllable promises (`const d = Promise.withResolvers()`) so you can check the intermediate “old content still shown, `$effect.pending()` is 1” state deterministically before resolving.
- Mount through a `<svelte:boundary>` wrapper component in tests, because a top-level await with no boundary at the root gives you nothing to render until it resolves, and rejections need somewhere to go.
- Fake timers interact with the `tick()` race; if you use them, advance both timers and animation frames.

A skeleton test with Vitest and a deferred promise:

```ts
import { mount, flushSync, unmount } from 'svelte';
import { expect, test } from 'vitest';
import Harness from './Harness.svelte';   // wraps <svelte:boundary> around the component under test

test('shows stale content until the request resolves', async () => {
    const d = Promise.withResolvers<number>();
    const app = mount(Harness, { target: document.body, props: { load: () => d.promise } });
    flushSync();
    expect(document.body.textContent).toContain('loading');

    d.resolve(42);
    await vi.waitFor(() => expect(document.body.textContent).toContain('42'));
    unmount(app);
});
```

## Design guidance and risk assessment

- **Use it where the synchronised-update model is what you want**: dashboards, detail views, search-as-you-type, anything where “never show an inconsistent mix of old and new data” is a feature. Use plain state plus explicit loading flags where you need fine control over every intermediate state, or where parts of the page must update independently of a slow request.
- **Keep awaits near the data’s consumer.** Hoisting an `await` to the root makes the whole app wait. Prefer a boundary around each independent region.
- **Isolate the experimental surface.** Wrap `fork`, `hydratable` and any reliance on `$effect.pending` or ordering in internal helpers, so a breaking change is a one-file fix.
- **Prepare for Svelte 6.** Treat code that works only because of the legacy ordering (state updates inside `$effect.pre` relying on block effects running later) as technical debt now; `flush_sync_in_effect` and `set_context_after_init` restrictions are already documented as becoming defaults.
- **Know what the flag does not do.** It does not make event handlers async-safe, does not cache anything, does not retry, and does not catch errors outside rendering. Those remain your job.

## Key takeaways

- `await` in components (5.36) is experimental in 5.57 and requires `compilerOptions.experimental.async: true`; the flag is removed in Svelte 6. Without it, the compiler throws `experimental_async`; `fork()` and `hydratable()` throw `experimental_async_required` at runtime unless the app was compiled with the flag.
- `await` is allowed at the top level of `<script>`, in `$derived`, and in markup; it is not allowed inside `use:`, `transition:`, `animate:`, attachments or bindings (`illegal_await_expression`). Async deriveds must be created inside an effect tree (`async_derived_orphan`).
- Updates are synchronised: state changes that feed a pending `await` are not painted until the work resolves; independent updates overlap; independent markup awaits run in parallel; sequential script-level awaits and sequential `$derived(await ...)` create waterfalls (`await_waterfall`), fixed by creating promises first. Read state before the first `await` or pass it as arguments (`await_reactivity_loss`).
- Loading UI: a `pending` snippet in `<svelte:boundary>` shows only on first render; `$effect.pending()` counts pending promises in the current boundary (not children) for later updates. `settled()` waits for the batch you are currently building, so call it in the same run as the change; `tick()` under the flag is a rAF/timeout race.
- `$state.eager` shows acknowledgement immediately at the cost of consistency; use it sparingly. `getAbortSignal()` inside a derived aborts superseded runs; stale rejections are not reported.
- Errors in rendering and in awaits in a boundary go to `failed(error, reset)` / `onerror`; they remove the boundary’s content, can be rethrown to a parent, and do not include event handlers or work outside rendering. Do not call `reset` synchronously inside `onerror`.
- Writable `$derived` (5.25) gives a simple optimistic-update pattern independent of the flag.
- `fork(fn)` (5.42) runs speculative work in a separate batch; `commit()` applies it, `discard()` drops it; it cannot be created inside an effect or with pending state changes (`fork_timing`), and a discarded fork cannot be committed (`fork_discarded`).
- With the flag, block effects run before `$effect.pre`; `flushSync` inside effects and `setContext` after `await` are errors. Async SSR uses `await render(App)`, and `hydratable(key, fn)` avoids repeating server work during hydration (Chapter 14).

## Review Questions

1.  Name the three places `await` may be used in a component under `experimental.async`, and give the compile-time error you get when the flag is off.

2.  Which of the following compile with the flag on? For each that does not, name the error.

    a.  `<div use:action={await load()}>`
    b.  `<p>{await load()}</p>`
    c.  `<input bind:value={v} />` next to `{await x}`
    d.  `<div transition:fade={{ duration: await d() }}>`
    e.  `let user = $derived(await fetchUser(id));`

3.  Where does the flag go in a plain Vite project, and what do you add to the compiled output (observably) when it is on?

4.  `fork()` and `hydratable()` are exported from `'svelte'` with no “experimental” label. What happens if you call them in an app compiled without the flag, and why does that matter for library authors?

5.  Explain “synchronised updates” using this component. What does the paragraph show 100 ms after `a` is incremented if the request takes 500 ms, and why?

    ```html
    <p>{a} + {b} = {await add(a, b)}</p>
    ```

6.  A slow update (1 s) to state `x` is in flight when a fast, independent update to `y` (50 ms) completes. Does the UI wait for the slow one? What if the second update is also to `x`?

7.  Spot the waterfall and fix it:

    ```ts
    let a = $derived(await one());
    let b = $derived(await two());
    ```

    What warning does Svelte emit in development?

8.  Why does the following lose reactivity on `b`, and how do you fix it?

    ```ts
    async function sum() { return await a + b; }
    let total = $derived(await sum());
    ```

9.  Why can a `$derived(await ...)` not be created in a `.svelte.ts` module at top level? Which error results, and what is the underlying reason given in the docs?

10. When is a `pending` snippet shown? Will it appear again when the user triggers a refresh of already-displayed data? How would you indicate the refresh?

11. What does `$effect.pending()` return and what counts? What does it not count? What error occurs if you call it in an event handler?

12. (Multiple choice) You call `inc(); await tick(); await settled();` where `inc` changes state that feeds a 500 ms request. After the `await settled()` line, the DOM

    a.  shows the new value
    b.  shows the old value, because `settled()` resolved immediately
    c.  throws `experimental_async_required`
    d.  shows the pending snippet

13. Rewrite this handler to use `settled()` correctly, so that `updating` is `true` while the async work is in flight and `false` afterwards: `ts async function onclick() { updating = true; color = 'octarine'; answer = 42; updating = false; }`

14. With the flag on, what does `tick()` resolve on, and why can this be earlier than the completion of async work?

15. Show what the user sees, step by step, for this search box when they type `a`, then quickly `ab`: `svelte <input bind:value={q} /> <p>Searching: {$state.eager(q)}</p> <ul>{#each await search(q) as r (r.id)}<li>{r.title}</li>{/each}</ul>` What is the risk in using `$state.eager` for the list itself?

16. How do you cancel a superseded `fetch` inside an async derived? Why must `getAbortSignal()` be called synchronously in the derived expression, and what error occurs if it is called in an event handler?

17. Does Svelte report the `AbortError` thrown by an aborted request to the boundary? Why or why not?

18. A boundary has a `failed` snippet and an `onerror` handler. An error is thrown in an `onclick` handler of a button inside it. What happens? What if the same error is thrown while rendering a child component?

19. You call `reset()` synchronously inside `onerror`. What happens, and what is the fix?

20. What does a handled error do to the boundary’s existing content? What if `onerror` itself throws?

21. Design question: a user profile page has a header (cheap), an activity feed (slow), and a sidebar (medium). Sketch the boundary structure and explain where `$effect.pending()` indicators should live so that they observe the right work.

22. Implement optimistic “like” with a writable derived. What happens to the displayed count if the server call fails and you do not roll back?

23. Describe the contract of `fork`, `commit` and `discard` using the menu example. Which two errors can occur?

24. Why is creating a fork inside an `$effect` an error? Where is the right place to create it?

25. What exactly changes about effect ordering under the flag, and in which circumstances would you notice?

26. Why must `setContext` (or a `createContext` setter) be called before the first `await` in the component, and what error do you get otherwise under the flag?

27. How does `hydratable` avoid duplicate work during hydration? What kinds of values can it serialise? Why should library authors prefix keys?

28. On the server, what does a `<svelte:boundary>` with a `pending` snippet render? What about awaits outside such boundaries?

29. A colleague proposes enabling the flag and using `fork` throughout the app for hover-prefetching. List two risks relating to the experimental status and one design risk relating to how forks reuse work.

30. Write a Vitest test outline for a component that loads data asynchronously, asserting the stale-content-while-pending behaviour without sleeping.
