# Chapter 4: `$derived` and `$effect` — Dependency Tracking and Side Effects

State is only half of reactivity. The other half is what *depends* on state: values computed from it, and side effects that must happen when it changes. Svelte gives you two runes for that, `$derived` for pure computation and `$effect` for everything that touches the outside world. Choosing correctly between them, and understanding exactly when each runs, what it tracks and what it cleans up, is the difference between a Svelte 5 codebase that is quiet and predictable and one that is full of effect chains and update loops. This chapter covers `$derived` and `$derived.by`, the dependency rules, writable deriveds, `$effect` and its variants (`.pre`, `.tracking`, `.pending`, `.root`), cancellation with `getAbortSignal`, lifecycle hooks, the escape hatches that replace effects (`createSubscriber`, attachments, function bindings), loop protection, and the debugging helpers `$inspect` and `$inspect.trace`. The next chapter shows the graph machinery that implements all of this. Behaviour below was verified on `svelte@5.57.2`, mostly with `$effect.root` plus `flushSync` in Vitest/jsdom.

## `$derived`: computed values

```html
<script lang="ts">
  let count = $state(0);
  let doubled = $derived(count * 2);
</script>

<button onclick={() => count++}>{count} doubled is {doubled}</button>
```

`$derived(expr)` is exactly `$derived.by(() => expr)`. Use `$derived.by` when you need statements:

```ts
let numbers = $state([1, 2, 3]);
let total = $derived.by(() => {
  let sum = 0;
  for (const n of numbers) sum += n;
  return sum;
});
```

Rules of placement mirror `$state`: a variable declaration initializer or a class field. `$derived` takes an *expression*, not a function; passing a function gives you the function back, which is a common mistake (`$derived(() => x)` is a derived whose value is a function).

### Lazy, memoised, push-pull

Svelte uses *push-pull* reactivity. When a source changes, everything that depends on it is notified immediately (push) but derived values are not recomputed until somebody reads them (pull). I measured it by counting computations:

```ts
let count = $state(0);
let computes = 0;
const large = $derived.by(() => { computes++; return count > 10; });
// computes === 0     (never read, never computed)
large;               // computes === 1
large;               // computes === 1   (memoised)
count = 1;           // computes === 1   (marked dirty, not recomputed)
large;               // computes === 2
```

Two properties follow. A derived nobody reads costs nothing after creation. And multiple writes between reads cause at most one recomputation.

### Referential equality cut-off

If a recomputation yields a value identical (by `===`) to the previous one, downstream reactions are not re-run. From the docs’ own example, an effect that reads `large = $derived(count > 10)` does not run when `count` goes from 1 to 2. I counted: an effect reading `large` ran once at setup and when `count` went 2 then 3 it stayed at one run; it ran again only when `count` became 11. So deriveds act as *filters on change*: they convert a high-frequency source into a low-frequency signal. Use that deliberately, for example `let isNarrow = $derived(width < 600)` instead of reading `width` in many places.

The cut-off is by identity. A derived returning a new object each time always propagates:

```ts
let state = $state({ value: 0 });
let derived = $derived({ value: state.value * 2 });
$effect(() => { derived; });   // re-runs whenever state.value changes
```

### Dependencies

Anything read **synchronously** while the expression runs is a dependency. That includes reads inside functions the expression calls. Reads after an `await` or inside callbacks (`setTimeout`, `.then`) are not tracked (with one exception under the experimental async flag, below).

Dependencies are re-collected on each run, so conditionals matter. I tested an effect `if (a) b; else c;`:

- while `a` is true, changing `c` did not re-run it (1 run), changing `b` did (2),
- after `a` became false, changes to `b` no longer re-ran it, changes to `c` did.

The same applies to deriveds. Short-circuit operators and early returns reduce the dependency set, which is both a feature and a trap: a dependency read only in one branch will silently stop mattering.

**`untrack`** (from `svelte`) reads state without subscribing:

```ts
import { untrack } from 'svelte';

let a = $state(1), b = $state(2);
const sum = $derived(a + untrack(() => b));   // only `a` is tracked
```

An effect reading `untrack(() => b)` stayed at 1 run after `b++`.

**With `await`** (experimental, `compilerOptions.experimental.async: true`): “if an expression contains an `await`, Svelte transforms it such that any state after the `await` is also tracked”. So in `$derived(await a + b)` both `a` and `b` are dependencies even though `b` is read after the first suspension. This does not extend to `await`s inside functions the expression calls; reading state there triggers the `await_reactivity_loss` warning. Chapter 13 covers async deriveds fully.

### Deriveds are not deeply reactive

A derived value is returned as-is. If it is an object derived from `$state`, mutating it mutates the source:

```ts
let items = $state([{ n: 1 }, { n: 2 }]);
let index = $state(0);
let selected = $derived(items[index]);   // a proxy from `items`
selected.n = 9;                          // updates items[0]
```

That is documented: you can `bind:` to properties of `selected`. If `items` were not state, mutating `selected` would do nothing reactive. Need independent reactive state computed from something? Use `$state` inside `$derived.by`, which works but is rarely the right design.

### Destructuring

```ts
let { a, b, c } = $derived(stuff());
```

is roughly `let _s = $derived(stuff()); let a = $derived(_s.a); ...`. Each variable is its own derived on top of the first, so an effect reading only `a` is not re-run when only `b` changes. I verified with `let { a, b } = $derived(o)`: after replacing `o` with an object with the same `a` and a new `b`, an effect reading `a` stayed at 1 run; after `a` changed it ran again. Compare with `$state` destructuring, which copies.

### Writable deriveds (5.25)

Before 5.25 deriveds were read-only. Now you can assign to one (unless declared `const`), which temporarily overrides the value until the dependencies change again:

```html
<script lang="ts">
  let { post, like }: { post: { likes: number }; like: () => Promise<void> } = $props();

  let likes = $derived(post.likes);

  async function onclick() {
    likes += 1;               // optimistic
    try {
      await like();           // server updates `post` eventually
    } catch {
      likes -= 1;             // roll back
    }
  }
</script>

<button {onclick}>♥ {likes}</button>
```

Verified: after `likes += 1` the derived read `2`, then replacing `post` with `{ likes: 5 }` reset it to `5`. This is the idiomatic *optimistic UI* pattern and also the clean replacement for “copy prop into state with an effect”: the local value follows the prop and can be edited in between. It is also the answer to “reset local state when the parent’s value changes”, without an effect.

Caveat: the derived recomputes only when its dependencies change. If the parent re-renders with the same `post.likes`, the override stays; if you need an override that survives source changes, keep it in separate `$state`.

### State mutation inside deriveds is an error

```ts
let n = $state(0);
let x = $state(0);
const bad = $derived.by(() => { x = n; return 1; });
bad;  // throws state_unsafe_mutation
```

I got `state_unsafe_mutation` (“Updating state inside `$derived(...)`, `$inspect(...)` or a template expression is forbidden. If the value should not be reactive, declare it without `$state`”). Deriveds must be pure, because they run lazily at unpredictable times and may run zero times. The docs example of “deriving two pieces of state in one go” shows the typical mistake; the fix is two deriveds, or one derived returning an object.

**Exception, since 5.24:** state *created inside* a derived or effect can be written and read there without error and without self-invalidation. My test `$derived.by(() => { let local = $state(0); local++; return local; })` returned `1`. The compiler can tell this state is local because it is declared inside the reaction.

Related errors: `derived_references_self` (“A derived value cannot reference itself recursively”) for cycles, and `effect_in_unowned_derived` for creating effects inside a derived that was not itself created inside an effect.

### Class fields

`$derived` also works as a class field (`remaining = $derived(this.items.filter(...).length)`), compiled to a private derived with accessors, like `$state` (Chapter 3). A derived field is writable the same way.

### Derived values outside components

Deriveds created in a module or class at top level (not inside any effect) are *unowned*: they are not tied to a component lifecycle. They are connected to the graph only while a reaction depends on them; with no observers they are disconnected, so they can be garbage-collected and are reconnected when read inside a tracking context again. I measured that an unobserved derived still memoises between reads (three reads with no state change computed once, a write followed by reads computed once more). Chapter 5 explains the disconnection logic. A derived created *inside* an effect stops updating when that effect is destroyed; reading it afterwards may be stale (warning `derived_inert`: “Reading a derived belonging to a now-destroyed effect may result in stale values”). Create such deriveds outside the effect or inside an `$effect.root`. (I could not reproduce the stale read in a small test, so treat the warning as a guard against reliance on undefined behaviour.)

## `$effect`: side effects

Effects are functions that run when state they read changes. They are for talking to the outside: canvas drawing, third-party libraries, analytics, timers, subscriptions. They run **only in the browser**, never during SSR.

```html
<script lang="ts">
  let size = $state(50);
  let color = $state('#ff3e00');
  let canvas: HTMLCanvasElement;

  $effect(() => {
    const ctx = canvas.getContext('2d')!;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, size, size);
  });
</script>

<canvas bind:this={canvas} width="100" height="100"></canvas>
```

### When it runs

I logged the order of every hook in a component with `$effect.pre`, `$effect`, `onMount` and `onDestroy`, mounted it, flushed, incremented its state, and unmounted it:

```text
script
pre 0                      <- $effect.pre runs during component init (before DOM exists)
tracking in setup false
--mounted (sync)           <- mount() returned; effects have NOT run
effect 0                   <- first flush: effects after DOM is ready
onMount
tracking in effect true
--flushed
--inc
pre 1                      <- state change: pre effects first
teardown 0                 <- then the previous run's cleanup
effect 1                   <- then the effect
--flushed
teardown 1                 <- unmount: cleanups
onMount cleanup
onDestroy
--unmounted
```

Read it as the lifecycle:

1.  The component script runs. `$effect.pre` effects run immediately during creation (so they see the component *before* its DOM is inserted).
2.  `mount` returns with the DOM in place. User effects and `onMount` are queued.
3.  In a microtask (or on `flushSync`) effects run, **after** the DOM has been created or updated, in the order they were declared. `onMount` is, in practice, implemented like an effect that does not track.
4.  After later changes, the pre effects run, then for each effect that is dirty the previous teardown, then the new run. Re-runs are batched: changing several dependencies in one go gives one re-run.
5.  On unmount, teardowns run, then `onMount` cleanups, then `onDestroy` callbacks.

The documented summary: effects run “after the component has been mounted to the DOM, and in a microtask after state changes. Re-runs are batched… and happen after any DOM updates have been applied.” Chapter 5 gives the exact flush order of block effects, render effects and user effects.

Note the teardown line: `teardown 0` was logged *after* `count` had already become 1, yet reports 0. Since 5.23 the values read by a cleanup function are consistent with the run it belongs to.

### Teardown

An effect may return a function that runs before each re-run and when the effect is destroyed (parent destroyed or parent effect re-run). Typical:

```ts
$effect(() => {
  const id = setInterval(() => { count += 1; }, ms);
  return () => clearInterval(id);
});
```

Because the cleanup runs *before the next run* and *on destroy*, effects are naturally idempotent resource managers: acquire in the body, release in the cleanup, and never track manual flags. Note `effect_in_teardown`: creating effects (or using effect runes) inside a teardown is an error.

### What an effect tracks

Same rules as deriveds: synchronous reads of reactive values (including through called functions), conditionally; async reads are not tracked. Two notes specific to effects:

- State created directly inside the effect (for example `new SvelteMap()` or a class with `$state` fields instantiated in it) is not treated as a dependency of that effect (5.24).
- An effect reading an object re-runs when *identity* changes, not on nested mutation, unless nested properties are read (the `s` vs `s.value` result above).

### Effects can be created anywhere a parent effect is running

You can call `$effect` in a component script, in a function called from it, or inside another effect. You cannot call it from an event handler or after an `await` in a function: that is `effect_orphan` (“`$effect` can only be used inside an effect (e.g. during component initialisation)”). I verified: calling `$effect(() => {})` in a plain test body threw `effect_orphan`. Top-level script `await` (async mode) is the one exception, since the compiler restores the context.

### `$effect.pre`

`$effect.pre` is `$effect` with different timing: it runs before the DOM updates that are scheduled after it. The docs’ example autoscrolls a chat view by measuring before the DOM grows:

```html
<script lang="ts">
  import { tick } from 'svelte';

  let div: HTMLDivElement | undefined = $state();
  let messages = $state<string[]>([]);

  $effect.pre(() => {
    if (!div) return;
    messages.length;                       // dependency
    if (div.offsetHeight + div.scrollTop > div.scrollHeight - 20) {
      tick().then(() => div!.scrollTo(0, div!.scrollHeight));
    }
  });
</script>

<div bind:this={div}>
  {#each messages as message}<p>{message}</p>{/each}
</div>
```

The precise promise: it runs “before DOM updates that are scheduled after it, not before every DOM mutation in the flush — DOM of parent components may already be updated. When using await expressions, block updates like `{#if ...}` and `{#each ...}` in the same component also run before `$effect.pre`.” In my log `pre 1` came before `effect 1`, and `pre 0` during initialisation. Use it only when you need to read the DOM *before* Svelte changes it (scroll positions, element sizes). Combined with `await tick()` it replaces `beforeUpdate`/`afterUpdate`.

### `$effect.tracking`

`$effect.tracking()` returns `true` inside an effect or a template expression (a tracking context) and `false` in plain component setup. My log: `tracking in setup false`, `tracking in effect true`. It exists so abstractions can avoid work when nobody is listening, notably `createSubscriber` (below and Chapter 9): a reactive wrapper should only attach listeners if its value is being read in a reaction.

### `$effect.pending`

`$effect.pending()` returns the number of pending promises in the current boundary (excluding child boundaries) and is part of async Svelte. It throws `effect_pending_outside_reaction` outside an effect or derived (I saw this). Chapter 13.

### `$effect.root`

`$effect.root(fn)` creates an effect scope that is not tracked and not cleaned up automatically, returning a destroy function:

```ts
const destroy = $effect.root(() => {
  $effect(() => { /* ... */ });
  return () => { /* root cleanup */ };
});
// later
destroy();
```

I confirmed the lifecycle: run, cleanup on re-run, and on `destroy()` the effect cleanup and then the root’s own cleanup (`['run 0','cleanup 0','run 1','cleanup 1','root cleanup']`). Use it (a) in tests, where there is no component, (b) in long-lived modules (a singleton store that needs its own effects), (c) for effects whose lifetime you manage yourself. Always keep and call the destroy function; leaking roots leaks everything they reference. `$effect.root` is how every Vitest example in this book creates effects.

## Cancellation: `getAbortSignal`

`getAbortSignal()` (5.35) returns an `AbortSignal` that aborts when the current derived or effect re-runs or is destroyed. It may only be called inside a reaction (`get_abort_signal_outside_reaction` otherwise; I saw it).

```ts
$effect(() => {
  const signal = getAbortSignal();
  fetch(`/api/search?q=${encodeURIComponent(query)}`, { signal })
    .then((r) => r.json())
    .then((data) => { results = data; })
    .catch((e) => { if (e.name !== 'AbortError') throw e; });
});
```

When `query` changes, the previous request is aborted *before* the new run. The abort reason is a `StaleReactionError` (I observed `'a:StaleReactionError'` and `'b:StaleReactionError'`): your handlers can distinguish “superseded” from real failures. In async deriveds (Chapter 13) this is the standard way to cancel work.

Compare with the manual approach (teardown with an `AbortController`): equivalent but more code. Use the signal.

## Lifecycle hooks: `onMount`, `onDestroy`, `tick`

“In Svelte 5, the component lifecycle consists of only two parts: Its creation and its destruction.” Updating is the business of individual effects, so there are no before/after-update hooks.

- `onMount(fn)` runs after the component is mounted. It must be called during initialisation (it can live in an external module). The function’s return value is called on unmount **only if `fn` is synchronous**; an `async` function returns a promise, so no cleanup is registered. It does not run on the server.
- `onDestroy(fn)` runs immediately before unmount, and is the only lifecycle function that runs during SSR. Destruction runs children first.
- `tick()` returns a promise resolving after pending state changes have been applied (or on the next microtask).
- `beforeUpdate`/`afterUpdate` are deprecated and throw `lifecycle_legacy_only` (“`%name%(...)` cannot be used in runes mode”); at compile time, importing them in a runes component is `runes_mode_invalid_import`. Replace `beforeUpdate` by `$effect.pre`, `afterUpdate` by `$effect`, and the “after DOM update” pattern by `await tick()`.

Is `onMount` redundant with `$effect`? Mostly: an effect with no reactive reads runs once after mount, and its teardown runs on destroy. `onMount` documents intent (“run once, no tracking”) and guarantees no dependency tracking, so accidentally reading state in it never causes re-runs. Use `onMount` for one-time setup. Use `$effect` when the work must be redone as state changes, and wrap any reads that should not trigger a re-run in `untrack`.

## When *not* to use `$effect`

The docs call effects “an escape hatch”. The recurring rule: *do not use an effect to synchronise state*. Each case below has a better tool.

**1. Derive, do not copy.**

```ts
// bad
let doubled = $state(0);
$effect(() => { doubled = count * 2; });
// good
let doubled = $derived(count * 2);
```

The effect version renders a frame with stale `doubled`, doubles the work, and invites loops.

**2. Respond to events in event handlers.** Code that should run “when the user does X” belongs in the handler, not in an effect watching state that X changes.

**3. Linked inputs: use function bindings.** The docs’ “money spent / money left” example uses two cross-writing effects. The fix is state plus a derived plus a function binding:

```html
<script lang="ts">
  const total = 100;
  let spent = $state(0);
  let left = $derived(total - spent);

  function updateLeft(value: number) { spent = total - value; }
</script>

<input type="range" bind:value={spent} max={total} />
<input type="range" bind:value={() => left, updateLeft} max={total} />
```

`bind:value={get, set}` (5.9) lets a derived be bidirectionally bound without an effect (Chapter 8).

**4. Writable deriveds for optimistic UI** instead of “state + effect that resets it”.

**5. Observe external sources with `createSubscriber`.** Instead of an effect that subscribes and writes into `$state`, wrap the source in a reactive object:

```ts
// src/lib/reactive-online.svelte.ts
import { createSubscriber } from 'svelte/reactivity';
import { on } from 'svelte/events';

export class OnlineStatus {
  #subscribe = createSubscriber((update) => {
    const offOnline = on(window, 'online', update);
    const offOffline = on(window, 'offline', update);
    return () => { offOnline(); offOffline(); };
  });

  get current() {
    this.#subscribe();            // registers the calling effect/template
    return navigator.onLine;
  }
}
```

`subscribe()` starts the `start` function when the first reaction reads it, calls `update()` to re-run those reactions, and runs the returned cleanup when the last one is gone. Consumers just read `status.current` in a template or derived. It is built on `$effect.tracking` internally (Chapter 9 dissects it).

**6. DOM libraries: use `{@attach}`.** The docs recommend attachments for syncing state to D3 and similar (Chapter 9).

**7. Logging for debugging: use `$inspect`.**

And when you really need an effect that also writes state, avoid reading what you write; if you must, use `untrack`. Never wrap an effect body in `if (browser)`; effects do not run on the server anyway.

## Infinite loops

An effect that reads and writes the same state re-triggers itself:

```ts
$effect(() => { count += 1; });   // reads count (+=) and writes it
```

Svelte intervenes: after more than 1000 consecutive flush iterations it throws `effect_update_depth_exceeded` (“Maximum update depth exceeded. This typically indicates that an effect reads and writes the same piece of state”). In my run the counter was `1001` when the error surfaced. Array mutation counts too: `array.push(...)` reads `length` and writes.

What *does* settle: an effect that writes state it does not read, or that writes a value equal to the current one (equal writes do not invalidate). A chain of effects A writes B, B writes C is legal but each hop costs a flush and a render in between; it is the “effect chain” smell. Prefer deriveds.

Fix options: restructure into `$derived`; split the state; read via `untrack`:

```ts
$effect(() => {
  const next = source.value;            // tracked
  untrack(() => { history.push(next); });   // not tracked
});
```

## Debugging helpers: `$inspect`

`$inspect(...values)` logs the values now and whenever they change, *deeply*, and prints a stack trace on updates. It is a no-op in production builds.

```html
<script lang="ts">
  let count = $state(0);
  let message = $state('hello');
  $inspect(count, message);
</script>
```

`.with(callback)` replaces `console.log`; the callback receives `'init' | 'update'` and then the values:

```ts
$inspect(count).with((type, value) => {
  if (type === 'update') debugger;
});
```

I ran `$inspect(count, o).with(...)`: `init` fired once and each change fired `update` with the current values, including a nested mutation (`o.a.b++`), confirming deep tracking. Because `$inspect` runs eagerly and not as a normal user effect, it is also fired without waiting for the flush (state_unsafe_mutation applies: do not write state in it).

**`$inspect.trace(label?)`** (5.14; source names 5.34) must be the first statement in a function body. It makes the surrounding effect or derived print *which reactive values caused this run*:

```ts
$effect(() => {
  $inspect.trace('search effect');
  doWork(query, filters);
});
```

Output (excerpt from my run): a console group labelled with the string you passed (here `search effect`) with a line per cause, e.g. `$state count 0`, each with a stack trace of where the write happened. It reports names (`count`, `o.a.b`) thanks to the dev-mode `$.tag` calls (Chapter 2). It is the right tool for “why does this effect keep running”. Placement errors: `inspect_trace_invalid_placement`, and it cannot be used in generator functions (`inspect_trace_generator`).

## Putting it together: a search box

```html
<script lang="ts">
  import { getAbortSignal } from 'svelte';

  let query = $state('');
  let limit = $state(10);
  let results = $state.raw<string[]>([]);
  let error = $state<string | null>(null);

  // pure: filtered view of results
  let shown = $derived(results.slice(0, limit));
  let summary = $derived(`${shown.length} of ${results.length} results`);

  // side effect: network, cancellable, runs when `query` changes
  $effect(() => {
    const q = query.trim();
    if (!q) { results = []; return; }

    const signal = getAbortSignal();
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`, { signal });
        results = await res.json();
        error = null;
      } catch (e) {
        if ((e as Error).name !== 'AbortError') error = String(e);
      }
    }, 200);
    return () => clearTimeout(timer);     // debounce: cleanup cancels pending timer
  });
</script>

<input bind:value={query} placeholder="search" />
<input type="range" min="1" max="50" bind:value={limit} />
{#if error}<p role="alert">{error}</p>{/if}
<p>{summary}</p>
<ul>{#each shown as r (r)}<li>{r}</li>{/each}</ul>
```

Division of labour: `results` is raw (replaced wholesale), `shown` and `summary` are deriveds (no effect needed), and the only effect talks to the network. The effect body reads only `query`. `results` and `error` are written *inside* the timeout callback, which runs asynchronously and is therefore untracked, and `limit` is read only by the deriveds, so the effect depends on `query` alone. The effect writes `results` but never reads it, so it cannot loop. The debounce is a teardown cleaning a timer, and the abort signal cancels in-flight requests. Under the async flag (Chapter 13) this whole component collapses to `$derived(await ...)` with a boundary.

## A decision checklist

Before writing `$effect`, ask in order: Is the result a value computed from state? Use `$derived`. Is it a response to a user action? Put it in the handler. Is it a two-way relationship between inputs? Use a function binding or a writable derived. Is it a subscription to something outside Svelte? Use `createSubscriber`. Is it configuration of a DOM node or third-party widget? Use `{@attach}`. Only when none applies (analytics, canvas drawing, imperative APIs, logging to external systems) is an effect the right tool. Then keep it small: read only what you need, do cleanup in the teardown, cancel with `getAbortSignal`, and never write state you also read without `untrack`.

## Key takeaways

- `$derived(expr)` = `$derived.by(() => expr)`: lazy, memoised, push-pull. It recomputes only when read after a dependency changed, and its change propagates only if the new value is not identical to the old one.
- Dependencies are the values read synchronously during the latest run (including through called functions); conditionals and early returns shrink them; `untrack` opts out; after `await` only expression-level reads are tracked, and only in async mode.
- Deriveds are not deeply reactive, destructure into one derived per variable, are writable since 5.25 (optimistic UI), and must be pure: writing outside state throws `state_unsafe_mutation`, but local state created inside is allowed (5.24).
- `$effect` runs only in the browser, after DOM update, batched in a microtask; its teardown runs before each re-run and on destroy and sees values consistent with its own run.
- `$effect.pre` runs before DOM updates scheduled after it (and during component init); `$effect.tracking` tells whether you are in a tracking context; `$effect.pending` counts pending async work; `$effect.root` creates a manually-destroyed scope, required outside component initialisation (`effect_orphan` otherwise).
- `getAbortSignal()` aborts with `StaleReactionError` when the reaction re-runs or is destroyed, giving built-in cancellation.
- There are only creation and destruction hooks. `onMount` cleanup needs a synchronous callback; `onDestroy` is the sole lifecycle function on the server; `beforeUpdate`/`afterUpdate` are legacy-only.
- Avoid effects for synchronisation. Use `$derived`, event handlers, function bindings, writable deriveds, `createSubscriber` and `{@attach}` instead.
- Effects that read and write the same state loop until `effect_update_depth_exceeded` (after 1000 iterations).
- `$inspect`, `.with` and `$inspect.trace` are dev-only tools for seeing changes and the cause of effect re-runs.

## Review Questions

1.  Why is `$derived` described as “push-pull”? Give the sequence of events from a source write to a read in a template.

2.  A derived is declared but never read. How many times is its expression evaluated?

3.  What does this print and why?

    ```ts
    let n = $state(0);
    let big = $derived(n > 10);
    let runs = 0;
    $effect.root(() => { $effect(() => { big; runs++; }); });
    flushSync();
    n = 3; flushSync();
    n = 4; flushSync();
    console.log(runs);
    ```

4.  Rewrite `const x = $derived(() => a + b)` so that `x` is a number. What does the original compute?

5.  In which order are `a`, `b`, `c` tracked, and which changes re-run the effect?

    ```ts
    let a = $state(true), b = $state(1), c = $state(1);
    $effect(() => { if (a) b; else c; });
    ```

6.  Find the bug:

    ```ts
    let total = $state(0);
    let items = $state<number[]>([]);
    let sum = $derived.by(() => { total = items.reduce((x, y) => x + y, 0); return total; });
    ```

    What is thrown, when, and how do you fix it?

7.  Why does `let { a, b } = $derived(obj)` avoid re-running an effect that reads only `a` when only `b` changed, whereas `let { a, b } = obj` (state) does not stay in sync at all?

8.  Explain how to implement an optimistic “like” counter using a writable derived. When does the optimistic value get replaced?

9.  Is the following valid? Why or why not?

    ```ts
    const d = $derived.by(() => { let local = $state(0); local++; return local; });
    ```

10. List the sequence of hook calls (script, `$effect.pre`, `$effect`, `onMount`, teardown, `onDestroy`) from mount to unmount for one state change.

11. Why does `mount()` return before `$effect` and `onMount` callbacks have run? How do you wait for them in a test?

12. What happens here, and what is the error code?

    ```ts
    function onclick() {
      $effect(() => console.log('clicked'));
    }
    ```

13. Give two situations in which `$effect.root` is the correct tool.

14. What is the difference between `$effect` and `$effect.pre`? Which would you use for measuring scroll position before new messages are rendered?

15. What does `$effect.tracking()` return in component setup, in an effect, and in a template? Why does `createSubscriber` care?

16. Why will this `$effect` not re-run when `size` changes?

    ```ts
    $effect(() => {
      ctx.fillStyle = color;
      setTimeout(() => ctx.fillRect(0, 0, size, size), 0);
    });
    ```

17. What is the abort reason when `getAbortSignal()` aborts because the effect re-ran? Write a fetch effect that ignores aborts.

18. Why does the following `onMount` not clean up the interval?

    ```ts
    onMount(async () => {
      const id = setInterval(tick, 1000);
      return () => clearInterval(id);
    });
    ```

19. Which lifecycle function runs during server rendering? Which are legacy-only in runes mode and what do they throw?

20. Replace these two cross-writing effects with a derived and a function binding.

    ```ts
    const total = 100;
    let spent = $state(0), left = $state(total);
    $effect(() => { left = total - spent; });
    $effect(() => { spent = total - left; });
    ```

21. What error does `$effect(() => { count += 1 })` produce and after how many iterations? Is `$effect(() => { latest = source.value })` safe, if `latest` is never read in the effect?

22. How does `untrack` fix a loop caused by `list.push(x)` inside an effect that also reads `list`? What is the downside?

23. Multiple choice: Which is NOT a recommended replacement for an effect?

    a.  `$derived` for computed values
    b.  `createSubscriber` for external event sources
    c.  An `$effect` that copies one `$state` into another
    d.  Function bindings for linked inputs

24. What does `$inspect(a, b).with(fn)` pass to `fn`, and when is it called? Is it active in production?

25. Where must `$inspect.trace()` be placed, and what does it tell you?

26. Design question: a `useWindowSize` helper must expose `width` and `height` reactively and attach a `resize` listener only while something reads them. Sketch it with `createSubscriber`, and explain why an unconditional `$effect` in a module would be wrong.

27. A derived is created inside an `$effect`, the effect is destroyed, and the derived is read later. What warning can appear and what are the two fixes?
