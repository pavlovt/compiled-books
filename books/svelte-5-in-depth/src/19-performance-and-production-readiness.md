# Chapter 18: Performance and Production Readiness

Svelte applications are fast by default, and that default is exactly what makes performance work in Svelte different: the framework does little at runtime, so when something is slow it is nearly always because of a decision you made about state shape, list rendering, effects or bundle contents, not because of an invisible diffing cost. This chapter is about those decisions. It explains where Svelte’s speed comes from (and where it stops), how to choose between `$state` and `$state.raw`, how derived caching and equality cut-offs work, how keyed `{#each}` blocks reconcile, what component granularity costs, how to read your bundle, how to find leaks, and then moves to the production checklist: build configuration, error handling and redaction, security (`{@html}`, CSP, state leaking between server requests), browser support and upgrade policy.

Measurements in this chapter were produced with Svelte 5.57.2 and Vite 8; byte counts are illustrative of one setup, not guarantees.

## Where the speed comes from, and where it does not

Four mechanisms define Svelte’s runtime profile:

1.  **No virtual DOM.** The compiler knows, per template expression, which DOM property depends on which piece of state. Updating state runs only the small effects that read it. There is no component re-render and no tree diff. For a `<button>{count}</button>`, the compiled client output is a template clone plus one `template_effect` that sets the text node (the generated code is `$.template_effect(() => $.set_text(text, ...))`; as always, compiler output is illustrative and not a public API).
2.  **Template cloning.** Static markup is turned into a string template (`$.from_html(...)`) that is parsed once and cloned for each use. Creating 1,000 rows costs 1,000 clones plus per-row effect setup, not 1,000 sequences of `createElement`/`setAttribute`. The `fragments` option controls this: `'html'` (default) uses `<template>.innerHTML`; `'tree'` builds nodes one by one, slower but compatible with a CSP that requires Trusted Types (`require-trusted-types-for 'script'`).
3.  **Event delegation.** For a fixed list of common events (`click`, `input`, `keydown`, `pointerdown`, `touchstart`, …), the compiler emits `$.delegated('click', button, handler)` and registers one listener per event type on the root. In our compile of `<button onclick>` plus `<div onmouseenter>`, `click` was delegated (`$.delegated`, with a module-level `$.delegate(['click'])`) while `mouseenter` got a direct listener (`$.event`). Delegation makes 10,000 list items with handlers cost one listener per event type. The caveats from Chapter 6 apply: manually dispatched events must bubble, and a `stopPropagation` in a manually attached listener can prevent delegated handlers from firing.
4.  **Fine-grained, lazily evaluated reactivity.** Deriveds are lazy (pull) and only notify dependents when their value changes (push), so expensive computations do not run until read.

What Svelte does *not* do for you:

- It does not make large data cheap. `$state` on a 100,000 element array of objects creates proxies; rendering 100,000 DOM rows is slow in any framework.
- It does not batch your own slow work: a `$derived` that sorts 50,000 items re-sorts every time its input changes.
- It does not prevent effect storms. Effects that write state which triggers other effects form chains of flushes.
- It does not keep runtime off your bundle: the runtime is small but not zero (measured below).

The practical consequence: performance work in Svelte is mostly *data-shape* work. Look first at what is reactive, how big it is, and how often it changes.

## State shape decisions

### `$state` versus `$state.raw`

`$state(object)` returns a deeply reactive proxy. Every property read goes through a `get` trap that registers a dependency, every write through a `set` trap that notifies, and nested objects and arrays are proxied lazily as they are accessed. In exchange you get fine-grained reactivity: `todos[3].done = true` updates only the DOM that read `todos[3].done`.

The official best-practices page states the trade-off: “in exchange for fine-grained reactivity, the objects must be proxied, which has performance overhead. In cases where you’re dealing with large objects that are only ever reassigned (rather than mutated), use `$state.raw` instead. This is often the case with API responses.”

`$state.raw` skips the proxy: the value is a plain object and “cannot be mutated; it can only be reassigned.” Updates are coarse (anything that read the variable re-runs) but reads are as cheap as plain property access.

```html
<script lang="ts">
  interface Row { id: number; name: string; score: number }

  // Result of a fetch: replaced wholesale, never edited in place
  let rows = $state.raw<Row[]>([]);

  // Small, edited in place: deep reactivity is the right tool
  let filters = $state({ query: '', minScore: 0 });

  const visible = $derived(
    rows.filter((r) => r.score >= filters.minScore && r.name.includes(filters.query))
  );

  async function reload() {
    rows = await (await fetch('/api/rows')).json();   // reassign, do not mutate
  }
</script>
```

Guidelines that follow from this:

| Data | Use | Why |
|------------------------|------------------------|------------------------|
| Form/UI state, small objects edited in place | `$state` | Fine-grained updates; proxy cost is negligible |
| Big arrays/objects from APIs, replaced wholesale | `$state.raw` | No proxy cost on every read; no accidental deep tracking |
| Class instances with mutable fields | `$state` on the *fields* | Class instances are not proxied; fields become reactive accessors |
| Large collections edited per element (Map/Set) | `SvelteMap` / `SvelteSet` | Per-key reactivity without proxying contents |
| Immutable data updated by spreading | `$state.raw` | Matches the pattern; avoids proxies of frozen structures |
| Things that never trigger updates (caches, timers, DOM refs read only in handlers) | plain variables | Reactivity has a cost, even when small |

Two compiler-level facts help here. First, `$state` that is never reassigned or mutated in a component compiles to a plain variable (`let n = 1;`), so unneeded `$state` is free at runtime but still noise. Second, `$state` of an object literal compiles to `$.proxy({...})`, and only a variable that is reassigned (primitive or object) is additionally wrapped in a `$.state(...)` signal (illustrative: we saw `let items = $.proxy([{ id: 1, t: 'a' }])` in our compile output).

Proxies also have semantic costs that matter for performance work:

- **Identity.** A proxy is not `===` to the object it wraps. Passing a proxy to libraries that cache by identity (charts, maps, workers) causes surprises. Warning `state_proxy_equality_mismatch` is the symptom. Use `$state.raw` for data handed to such libraries, or `$state.snapshot` when you need a plain copy.
- **Structured clone.** `postMessage(proxy)` and `structuredClone(proxy)` fail. `$state.snapshot(x)` produces a clone for that purpose, and it costs a deep traversal, so call it at boundaries, not in hot loops.
- **Logging.** The `console_log_state` warning (Chapter 16) exists because proxies display confusingly.

### Derived caching and the equality cut-off

`$derived` has two properties that you should design around:

- **Laziness and memoisation.** A derived recomputes only when read and only if a dependency changed since the last computation.
- **Equality cut-off.** When a derived recomputes and produces a value equal (by `===`) to its previous value, dependents are *not* notified. Svelte’s own description: “if the new value is referentially identical, downstream updates are skipped.”

We verified the cut-off. A component with `let parity = $derived(n % 2 === 0 ? 'even' : 'odd')` and an effect that reads `parity` was mounted with `n = 2`, then `n` was set to 4 and then 6: the effect ran once in total (its initial run). Setting `n = 7` changed the parity and the effect ran a second time. The practical lesson is that you can reduce downstream work by deriving *coarser* values from fast-changing ones: derive a boolean (`isNarrow`) from a continuously changing `innerWidth` and let the template depend on the boolean.

```html
<script lang="ts">
  import { innerWidth } from 'svelte/reactivity/window';

  // Re-evaluates on every resize, but only notifies dependents when the boolean flips
  const isNarrow = $derived((innerWidth.current ?? 1024) < 640);
</script>

{#if isNarrow}<MobileNav />{:else}<DesktopNav />{/if}
```

Objects and arrays are different: a derived that builds a new array every time compares unequal every time (objects are compared by identity, so even `[...x]` of the same contents is “changed”). So a derived such as `items.filter(...)` notifies dependents whenever *any* of its inputs change, even if the filter result has the same members. If that matters, split the work: derive the primitive pieces and build the array in the consumer, or cache by a stable key.

Also remember that a derived is not deeply reactive: it returns its object as-is. And that deriveds can be *written* since 5.25 (useful for optimistic UI), after which they hold the written value until a dependency changes.

### Avoid effect chains

The biggest performance smell in Svelte code is the effect that exists to compute something:

```html
<script lang="ts">
  let items = $state<number[]>([]);
  let total = $state(0);      // wrong: state derived from state

  $effect(() => {
    total = items.reduce((a, b) => a + b, 0);
  });
</script>
```

This runs after the DOM update, causes a second update pass when `total` changes, may flash stale UI in between, and invites update loops. Replace it with `let total = $derived(items.reduce((a, b) => a + b, 0))`. The best-practices page puts it bluntly: “Effects are an escape hatch and should mostly be avoided. In particular, avoid updating state inside effects.”

Each effect-induced state write schedules another flush; the runtime allows a bounded number of iterations before throwing `effect_update_depth_exceeded` (about 1,000 flushes in the source we read). A long chain that stays under the limit still costs a full flush per link. When you must write state in an effect, read the state you write with `untrack` so the effect does not depend on it.

Where an effect is legitimately needed (synchronising with an external system), keep its dependencies narrow: read only what you need inside it, and `untrack` everything else.

```ts
import { untrack } from 'svelte';

$effect(() => {
  const q = query;                     // dependency
  untrack(() => analytics.track('search', { q, filters }));   // not a dependency
});
```

## Lists

### Keyed each blocks

Take `{#each items as item}` without a key. The compiler emitted `$.each(node, 17, () => items, $.index, ...)`: an unkeyed block is a block *keyed by index*. Reordering, inserting at the front or removing from the middle therefore reuses DOM and component instances by position, rewriting each row’s contents instead of moving nodes. For primitives in a static list that is fine. For lists of components or rows with internal state (inputs, focus, animations), it is wrong and slow.

A keyed block, `{#each items as item (item.id)}`, compiles to a block whose key function is `(it) => it.id`. The runtime keeps a `Map` from key to row (an effect, DOM range and, if needed, signals for the item and index), and on each update it walks the new array: rows whose key exists are updated and *moved* if their position changed; rows for new keys are created; rows whose keys are gone are destroyed (after outros). The cost model is O(n) for a pass, plus work proportional to what changed, with DOM moves only where necessary.

```html
<script lang="ts">
  interface Todo { id: string; text: string; done: boolean }
  let todos = $state<Todo[]>([]);
</script>

<ul>
  {#each todos as todo (todo.id)}
    <li><input type="checkbox" bind:checked={todo.done} /> {todo.text}</li>
  {/each}
</ul>
```

Rules, from the docs and the source:

- **The key must uniquely identify the item.** “Do not use the index as a key.” Duplicates raise `each_key_duplicate` (“Keyed each block has duplicate key `x` at indexes a and b”).
- **Keys must be idempotent.** In development the runtime calls the key function twice per item and compares; a mismatch raises `each_key_volatile`. We reproduced it with `{#each items as it (['k', it.a])}`: the key function creates a new array on each call, and the error read “the key for item at index 0 was `k,1` but is now `k,1`. Keys must be the same each time for a given item”. (The printed strings look equal because arrays stringify equally, but they are different objects.) Use primitives: `(it.a + '-' + it.b)` or a stable ID. Because the check only runs in dev, a volatile key in production simply degrades to recreating rows each time.
- **Avoid destructuring if you need to mutate the item.** `{#each todos as { done }}` binds a copy; use `todo.done` with `bind:checked={todo.done}`.
- **Keys also give `animate:` something to work with**: `animate:flip` is only valid on the immediate child of a keyed each block.

### `{#key}` is not free

`{#key expr}...{/key}` destroys and recreates everything inside whenever `expr` changes. The docs: “it can be very expensive — it unmounts every element/component inside each time, so should be used sparingly”. Legitimate uses are replaying a transition or deliberately resetting a component’s internal state. Bad uses are forcing a re-run of a child’s `<script>` expressions; wrap those in `$derived` instead.

### Large lists

For thousands of rows, keyed each with fine-grained row updates handles surprisingly large lists; the constraint becomes DOM size, not diffing. Options, in order:

1.  **Do not render what is not visible.** Paginate or virtualise: render only the slice of rows in the viewport plus overscan, in a container whose height reflects the total.
2.  **Make rows cheap.** Fewer elements per row, fewer effects per row (every reactive expression in a row costs an effect per row), no per-row `$effect`.
3.  **Keep the data raw.** A `$state.raw` array of plain objects avoids per-row proxies; replace the array (or the changed row, by creating a new array) to update.

A minimal virtualiser shows how little machinery is needed:

```html
<script lang="ts">
  interface Props { rows: string[]; rowHeight?: number }
  let { rows, rowHeight = 28 }: Props = $props();

  let viewportHeight = $state(400);
  let scrollTop = $state(0);

  const overscan = 5;
  const start = $derived(Math.max(0, Math.floor(scrollTop / rowHeight) - overscan));
  const end = $derived(Math.min(rows.length, Math.ceil((scrollTop + viewportHeight) / rowHeight) + overscan));
  const slice = $derived(rows.slice(start, end));
</script>

<div
  class="viewport"
  bind:clientHeight={viewportHeight}
  onscroll={(e) => (scrollTop = e.currentTarget.scrollTop)}
  style="height: 400px; overflow: auto"
>
  <div style:height="{rows.length * rowHeight}px" style:position="relative">
    <div style:transform="translateY({start * rowHeight}px)">
      {#each slice as row, i (start + i)}
        <div style:height="{rowHeight}px">{row}</div>
      {/each}
    </div>
  </div>
</div>
```

The key `(start + i)` is the absolute row index, which is stable for a given row while scrolling (rows are identified by position in a fixed list). `slice` is a new array on each scroll, but the block only creates and destroys the few rows entering and leaving the window. `onscroll` is not a delegated event; the listener is attached directly to the element, which is appropriate for a hot event.

Note `bind:clientHeight`: dimension bindings use `ResizeObserver`, which jsdom lacks (stub it in component tests). Dimension bindings are cheap, but writing layout-dependent state back into layout-affecting style can cause a loop of layout, resize notification, state write, layout; keep such bindings out of tight feedback paths.

## Component granularity

A Svelte component is a function call that creates an effect scope; it is not an expensive unit like a React component with its own render cycle, but it is not free either. Heuristics:

- **Components are for cohesion, not for avoiding re-renders.** In frameworks with re-render-based reactivity you split components to limit re-render scope. In Svelte the update scope is already the individual expression, so splitting for performance rarely helps. Split for reuse, readability and testability.
- **Snippets are cheaper than components for local repetition.** A `{#snippet}` is a function that renders markup in the same scope; calling it with `{@render}` creates no component boundary and passes arguments directly. For a row layout used in two places inside one component, a snippet is lighter than an extra file. The trade-offs: no encapsulated state, and the snippet is lexically scoped.
- **Per-item components in huge lists** add an effect scope and props object per row. If rows are trivial, inline markup; if rows are complex, a component is fine, as the dominant costs are the DOM and the reactive expressions.
- **Props are getters.** In runes mode, `$props()` gives a props object whose properties are read through getters, so a child that reads `props.x` subscribes only to `x`. Destructuring in the declaration (`let { x, y } = $props()`) keeps that fine-grained behaviour because the compiler reads each lazily. Passing a whole `$props()` object around, spreading it (`{...props}`) into elements or components, or using legacy `$$props`/`$$restProps` forces the runtime to handle an open-ended set of properties and defeats the compiler’s static analysis (and for spreads onto elements, every attribute is re-evaluated when any prop changes). Spread when you need a pass-through; list props explicitly when you do not.
- **Do not create classes in components.** The compiler warns `perf_avoid_inline_class` (“Avoid ‘new class’ — instead, declare the class at the top level scope”) and `perf_avoid_nested_class` (“Avoid declaring classes below the top level scope”). A class created per component instance is a new class object every time: slower, and a breeding ground for identity bugs. Declare classes at module level (a `.svelte.ts` file), instantiate them in the component. We triggered both warnings with `new class { a = 1 }()` and a class inside a function.

```ts
// src/lib/selection.svelte.ts : a class declared once, instantiated many times
export class Selection<T> {
  selected = $state.raw<Set<T>>(new Set());
  toggle(item: T) {
    const next = new Set(this.selected);
    next.has(item) ? next.delete(item) : next.add(item);
    this.selected = next;
  }
  has(item: T) { return this.selected.has(item); }
}
```

Here `selected` is `$state.raw` of a `Set` which we replace; a `SvelteSet` would give per-element reactivity if you toggled thousands of items and rendered a cell per item.

## Transitions, animations and layout

- **`css` versus `tick`.** For custom transitions, return `css(t, u)` rather than `tick(t, u)` whenever possible. `css` is converted into Web Animations keyframes that the browser runs off the main thread; `tick` runs JavaScript on every frame. The docs advise `css` for this reason. Use `tick` only for things CSS cannot express (changing text content, for example the typewriter effect).
- **Animate compositor-friendly properties** (`opacity`, `transform`); avoid animating `height`, `width`, `top`. The built-in `slide` animates height, so it triggers layout each frame (and warns `transition_slide_display` for elements whose `display` it cannot handle).
- **Local by default.** Transitions play only when their own block toggles. That is both the correct UX default and a performance one: tearing down a large page does not start thousands of animations. Use `|global` deliberately.
- **Layout thrash with dimension bindings.** `bind:clientWidth` and friends are cheap observers, but writing to the DOM based on a read in the same frame forces synchronous layout. Do reads, then writes, in separate phases (or use `$effect.pre` for reading before the DOM updates and a normal `$effect` for writing after).
- **`animate:flip`** measures before and after each reorder; keep the animated list moderately sized.

## Bundle size

The framework’s runtime is small, and compiled components are efficient, but an application’s size is still the sum of the runtime features it uses and your code. Measured with Vite 8 (Rolldown with default minification), illustrative only:

| App | Minified | Gzip |
|------------------------|------------------------|------------------------|
| A counter: one `$state`, one button | 25.3 kB | 10.1 kB |
| The same plus a keyed `{#each}`, an `{#if}`, `transition:fade`, and a scoped style | 36.8 kB | 14.5 kB |

The first number is the cost of the runtime pieces needed to mount, run effects and delegate events. The increase in the second row is what the each block, if block, transition machinery and the CSS-related code add. These are one-time costs: the second component of the same kind adds only its own compiled code, which is small.

What shapes the bundle:

- **Tree-shaking of the runtime.** The runtime is split into many small functions, and the compiler imports only what a component uses (the `import * as $ from 'svelte/internal/client'` namespace import is analysed by bundlers). Hydration code, transitions, bindings, boundaries and `{#each}` machinery are included only when used. Flags like `import 'svelte/internal/flags/async'` and `.../legacy` select feature sets (for instance, the `delegate` output we saw imported `svelte/internal/flags/legacy` for a component that did not opt in to runes). Importing nothing from `svelte/transition` means no transition code.
- **`svelte/internal/*` is off limits.** Importing it yourself is a compile error (`import_svelte_internal_forbidden`). It is private API shaped for compiler output and changes between patch releases.
- **Runes mode versus legacy mode.** Legacy components pull in compatibility code (the legacy flag, `$$props` machinery, store handling for `$store` auto-subscriptions). A pure runes-mode app is slightly lighter, and is also the supported future (Chapter 20).
- **CSS strategy.** The compile option `css: 'injected' | 'external'`. `'external'` (the default of the bundler plugins) returns CSS separately so your bundler can emit a `.css` file, which can be cached and loaded in parallel. `'injected'` bundles each component’s CSS into the JavaScript and injects it into the document on mount (and into `<head>` during SSR): fewer requests, no flash of unstyled content for a single JS bundle, but more JS and no separate caching. It is always `'injected'` for custom elements, whose styles go inside the shadow root (Chapter 19). The option also accepts a function (5.54) to choose by file.
- **Custom elements bundle trade-off.** Each custom element wraps a component with the element class and injects CSS; shipping many small custom elements each with its own copy of the runtime is wasteful, so bundle them together (Chapter 19).
- **`discloseVersion`.** Defaults to `true` and adds the Svelte major version to `window.__svelte.v`. It is tiny, but if you want to avoid the global (or avoid advertising the version), set `discloseVersion: false`.
- **Dev-only code.** `$inspect`, ownership tracking, `each_key_volatile` checks and dev warnings are stripped in production. Never build for production with `dev: true`.
- **Libraries.** Check what your dependencies pull in. Importing an icon library as a barrel can dwarf the framework. Analyse with `rollup-plugin-visualizer` or your bundler’s analyzer.

### Source maps, `rootDir` and path leakage

Source maps are always generated; whether you *ship* them is your bundler’s decision. If you ship them to production, remember they contain source code. The compile option `rootDir` is “used for ensuring filenames don’t leak filesystem information” (default `process.cwd()` in Node-like environments): in dev builds components embed their filename for debugging hints, and `rootDir` makes those relative rather than absolute. Your bundler plugin sets both automatically; only override them in a custom build pipeline.

## Build and runtime configuration

- **`dev`.** Compiles with runtime checks and debugging info. Vite’s dev server sets it; production builds must not. In dev, `$inspect` logs; in production it is a no-op.
- **`hmr`.** Defaults to `false` in the compiler; the Vite plugin enables it for the dev server. Not a production concern.
- **`runes`.** A function form exists (5.54): `runes: ({ filename }) => !filename.includes('node_modules')`. Setting `runes: true` globally forces runes mode “for your entire project, including components in `node_modules`”, which breaks legacy libraries. Use the function form (or `dynamicCompileOptions` in vite-plugin-svelte) to scope it.
- **`fragments: 'tree'`** for Trusted Types CSP, at a performance cost (nodes are created one at a time instead of cloned from parsed HTML).
- **`preserveComments` / `preserveWhitespace`.** Defaults are off. Comments matter for hydration markers in SSR output, which are separate comment nodes Svelte generates (do not strip comments from SSR HTML if you hydrate it), but not source comments.
- **`warningFilter` and `onwarn`** to keep CI honest (Chapter 17).

## Memory and leak hunting

Svelte cleans up after itself: when a component is destroyed, its effects, their cleanup functions and its attachments’ cleanups run, and DOM listeners attached by the compiler go away. Leaks come from things Svelte does not own:

1.  **Unowned effects.** `$effect.root(fn)` creates effects outside any component and returns a destroy function; forgetting to call it leaks every effect, signal subscription and closed-over object inside. This includes tests (Chapter 16) and module-level code that creates effects. Pair every `$effect.root` with a destroy call in a `onDestroy`/cleanup path.
2.  **Listeners and timers on globals.** `window.addEventListener` inside `onMount` without removal, `setInterval` without `clearInterval`. Return cleanups: from `onMount` (only if the callback is synchronous), from `$effect`, or from attachments. Prefer declarative `<svelte:window onresize={...}>`, which Svelte removes for you, and `on()` from `svelte/events` (it returns a remover) inside attachments.

    ```html
    <script lang="ts">
      let now = $state(Date.now());

      $effect(() => {
        const id = setInterval(() => (now = Date.now()), 1000);
        return () => clearInterval(id);   // runs before re-run and on destroy
      });
    </script>
    ```

3.  **External subscriptions.** Observing something outside Svelte (a WebSocket, a `matchMedia` list, a third-party store) is the use case for `createSubscriber` from `svelte/reactivity`. It starts the subscription when the first effect reads it and stops it when the last one is destroyed, so you do not leak and do not do work when nobody is looking:

    ```ts
    // src/lib/online.svelte.ts
    import { createSubscriber } from 'svelte/reactivity';
    import { on } from 'svelte/events';

    export class OnlineStatus {
      #subscribe = createSubscriber((update) => {
        const offOnline = on(window, 'online', update);
        const offOffline = on(window, 'offline', update);
        return () => {
          offOnline();
          offOffline();
        };
      });

      get current() {
        this.#subscribe();            // registers the calling effect as a dependent
        return navigator.onLine;
      }
    }
    ```

    `#subscribe()` must be called inside a reactive context for the subscription to start. `start` is called once while at least one effect is active, and the cleanup runs when all dependents are gone. (The built-in `online` from `svelte/reactivity/window` is already implemented this way.)

4.  **Closures over large proxies.** A long-lived callback that closes over a component’s `$state` object keeps that object alive. Module-level caches keyed by component instances, global event buses holding handlers from destroyed components, and detached DOM nodes held in arrays are classic culprits.
5.  **Unmounted roots.** `mount()` returns a handle; `unmount(handle)` tears down the tree. Applications that mount tooltips or portals imperatively must unmount them. Calling `unmount` twice yields the `lifecycle_double_unmount` warning (“Tried to unmount a component that was not mounted”), which is a useful signal that your ownership is muddled.
6.  **Derived values created in effects.** The `derived_inert` warning (“Reading a derived belonging to a now-destroyed effect may result in stale values”) means a derived outlived its owner: create it outside the effect or in an effect root.

To confirm a leak, use the browser’s Memory panel: take a heap snapshot, perform the suspect action (open and close a dialog) ten times, force garbage collection, take another snapshot and compare retained instances of your component classes or DOM nodes (look for “Detached” elements). Then find the retainer chain: it will usually point at a global listener, a timer or a root.

## Measuring

Optimise from evidence:

- **Browser performance panel.** Record an interaction; look for long tasks, forced reflows (layout thrash), and repeated style recalculation. With Svelte’s fine-grained updates, time in “scripting” is usually your own derived computations or effect chains; time in “layout” is DOM size or thrash.
- **`$inspect.trace()`** (Chapter 16) tells you *why* an effect or derived re-ran, which is the right question when something runs too often.
- **Counting effects.** Every reactive expression in the template becomes an effect (`template_effect`). A row with ten bound attributes in a 5,000-row list is 50,000 effects. Inspect the compiled output (`compile(...).js.code`) when you suspect that a component compiles to more than you expect.
- **Benchmark methodology.** Measure in production builds, with CPU throttling, multiple runs and the median; use `performance.mark/measure` around the operation; ensure that you wait for the flush (`await tick()`), or you will time the call rather than the update; warm up the code before measuring; compare against a baseline commit. Microbenchmarks of `$state` in isolation are misleading, because real cost shows up in DOM and layout.

## Error handling in production

### Boundaries

`<svelte:boundary>` catches errors during rendering (and in effects within it) and renders its `failed` snippet; `onerror` is the place to report. Put boundaries around independent pieces of UI so one failing widget does not blank the page, and around anything that renders third-party or user-influenced data. Boundaries do not catch errors in event handlers or after `setTimeout`/async work. For those, use `try/catch` (or `window.onerror` and `unhandledrejection` as backstops) and feed the failure into state that renders an error UI.

```html
<svelte:boundary onerror={(error) => reportToService(error)}>
  <Widget />

  {#snippet failed(error, reset)}
    <p role="alert">This part of the page failed to load.</p>
    <button type="button" onclick={reset}>Retry</button>
  {/snippet}
</svelte:boundary>
```

Rules worth remembering: a rethrown error or an error in `onerror` goes to the parent boundary; calling `reset` synchronously inside `onerror` is an error (`svelte_boundary_reset_onerror`), so `await tick()` first; `reset` only works once (`svelte_boundary_reset_noop`).

### Redacting errors with `transformError`

On the server, boundaries have no effect by default: a rendering error fails the whole `render`. Since 5.51 per the docs (the changelog’s first server-boundary entry is 5.53, so require at least 5.53), you can pass `transformError` to `render`, `mount` or `hydrate`. It receives the original error and must return a JSON-stringifiable value that is used to render `failed` and is serialised into the page for hydration:

```ts
import { render } from 'svelte/server';
import App from './App.svelte';

const { head, body } = await render(App, {
  transformError: (error) => {
    console.error(error);                 // keep the real error server-side
    return { message: 'An error occurred!' };   // send only this to the browser
  }
});
```

The docs warn that “errors that occur during server-side rendering can contain sensitive information in the `message` and `stack`. It’s recommended to redact these rather than sending them unaltered to the browser.” If `transformError` throws, the whole render fails. If you use Svelte through a framework, the framework owns the `render` call and must configure this (the docs mention SvelteKit’s `handleError` hook as the integration point).

## Security

### `{@html}` and XSS

`{@html expr}` inserts raw HTML. The docs: “Make sure that you either escape the passed string or only populate it with values that are under your control in order to prevent XSS attacks. Never render unsanitized content.” Treat every `{@html}` as a security review item. Sanitise with an allow-list sanitiser such as DOMPurify at the point where untrusted content enters, not at the point of rendering, and keep the sanitiser’s configuration under test. Trusted Types support: since 5.52 `{@html}` accepts `TrustedHTML` values, which lets you enforce sanitation by policy. `{@html}` content also does not receive scoped styles (use `:global`), is not hydrated against changes (`hydration_html_changed`) and must be valid standalone HTML.

Ordinary `{expression}` interpolation is escaped, so the usual XSS vectors are `{@html}`, `href`/`src` attributes assigned from user input (`javascript:` URLs), and `<svelte:element this={userInput}>`.

### Dynamic elements

`<svelte:element this={tag}>` with a user-controlled tag is dangerous in a different way: on the server, an invalid tag name raises `dynamic_element_invalid_tag`, and on the client a user-controlled tag can create elements you did not intend. Restrict `this` to an allow-list (a `Record<string, string>` lookup), never pass raw user input.

### Content Security Policy

Svelte’s client output works with a strict CSP except for two things:

- **Trusted Types.** With `require-trusted-types-for 'script'`, the default `fragments: 'html'` templates (built via `innerHTML`) violate policy. Compile with `fragments: 'tree'`. Since 5.51/5.52 Svelte uses `TrustedTypes` for HTML handling where supported.
- **Inline scripts from `hydratable`.** `hydratable` (experimental, requires `experimental.async`) adds an inline `<script>` to `head`. For a per-request response, pass a nonce: `render(App, { csp: { nonce } })` and send `script-src 'nonce-...'`. For statically generated HTML use `csp: { hash: true }` and put `hashes.script` into the policy. Passing both is an error (`invalid_csp`). The docs recommend nonces, since hashes will interfere with streaming SSR in future.

Injected CSS (`css: 'injected'`) creates `<style>` elements; if your CSP restricts `style-src`, use `css: 'external'` so that styles ship as a file, or provide a nonce through your tooling.

### State leakage across SSR requests

This is the most serious Svelte-specific production bug. Module-level state exists once per *process*, not once per request. On the server, a `$state` at module level is shared by every request that process handles:

```ts
// src/lib/session.svelte.ts  (DANGEROUS on the server)
export const session = $state({ user: '' });
export function setUser(u: string) { session.user = u; }
```

We rendered a component reading `session.user` after another request had called `setUser('alice@example.com')`, and the output for the second render was `<p>alice@example.com</p>`. Visitor B received visitor A’s data. This is the same trap as module-level singletons in any server framework, but rune-based modules make it feel like “just state”.

Rules:

- **Never put per-user data in module-level state that is touched during SSR.** Hold it in a component-scoped object and share it down the tree with context (`createContext`), created inside the root component or provided through a wrapper component around the root (Chapter 12).
- Module-level state is fine for truly global, immutable or per-process data (feature flags loaded once, constants).
- Be careful with module-level *caches* (memoised fetches) and `hydratable` keys: key by request-specific values.
- Test it. A two-request SSR test (see Chapter 16) that asserts the second render does not contain the first user’s data is cheap insurance.

```ts
// Safe: state lives in an instance, shared via context
import { createContext } from 'svelte';

export class Session {
  user = $state('');
}
export const [getSession, setSession] = createContext<Session>();
```

```ts
import { render } from 'svelte/server';
import App from './App.svelte';
import { Session, setSession } from './session.svelte';

function handle(userId: string) {
  const session = new Session();          // one per request
  session.user = userId;
  // Wrapper component (Chapter 16): sets context, then renders the real root
  function Root(...args: Parameters<typeof App>) {
    setSession(session);
    return App(...args);
  }
  return render(Root).body;
}
```

We ran two consecutive renders of a component reading `getSession().user` this way (“alice” and then an empty session): the second output was `<p>anonymous</p>`, with no leakage. (For the keyed `setContext`/`getContext` API, `render` also takes a `context: Map` option.)

## Browser support, polyfills and upgrade policy

The docs derive the minimum supported browsers from the APIs Svelte’s own runtime uses (roughly the Baseline 2020 generation: Chrome and Edge 87, Firefox 83, Safari 14; Internet Explorer is not supported). Some features need more: `$state.snapshot` (which uses `structuredClone`) needs Chrome/Edge 98, Firefox 94, Safari 15.4; `bind:devicePixelContentBoxSize` is not available in Safari; `flip` needs Firefox 126. These numbers cover Svelte only, not your dependencies or your own code, so define your `browserslist`/`build.target` accordingly. If you must support older engines, polyfill `structuredClone` and check the Web Animations API and `ResizeObserver` availability (used by transitions and dimension bindings).

Upgrade policy that has served teams well:

1.  **Read the changelog for the range you upgrade across.** Within 5.x, features arrive as minor versions and are additive, but deprecations and tightened checks (new warnings, stricter validation) appear too.
2.  **Pin and test.** Use a lockfile; upgrade deliberately; run the unit, component, SSR/hydration and E2E layers.
3.  **Experimental means experimental.** `experimental.async` and everything that requires it (`await` in templates, `$effect.pending`, `fork`, `hydratable`, and the `flush_sync_in_effect` and `set_context_after_init` restrictions) can change outside semver. The docs say so and say the flag will be removed in Svelte 6. Isolate experimental usage so that it can be changed in one place.
4.  **Do not import from `svelte/internal/*`**, and do not depend on the shape of compiled output, hydration markers’ exact format, or the internal flush implementation.
5.  **Treat new warnings as work items.** A minor upgrade that adds a warning is the compiler telling you about a latent bug.
6.  **Plan for Svelte 6.** The docs flag future changes: `runes` default `true`, quoted single-expression attributes coerced to strings, all falsy `class` values omitting the attribute, the async flag removed, modern AST default (Chapter 20). Fix the warnings that predict them now (`attribute_quoted`).

## A production readiness checklist

- Production build verified with a preview server; no `dev: true`; source maps policy decided.
- No state per user at module level in anything imported during SSR; SSR isolation test in CI.
- Every `{@html}` reviewed and sanitised; no user-controlled `<svelte:element this>`.
- CSP strategy chosen (`nonce`, `hash`, `fragments: 'tree'`, `css: 'external'`) and tested.
- Boundaries around independent UI; `onerror` reporting; `transformError` redaction on the server.
- Lists keyed by stable unique IDs; no `{#key}` abuse; large lists paginated or virtualised.
- State shape reviewed: `$state.raw` for large replaced data; no effects that compute state; classes declared at module level.
- Bundle analysed; transitions and heavy dependencies justified.
- Leaks checked for dialogs/popovers/routes: effect roots destroyed, listeners removed, `createSubscriber` for external sources.
- Browser matrix and polyfills documented; upgrade runbook in place.

## Key takeaways

- Svelte’s speed comes from compile-time knowledge: template cloning, per-expression effects, event delegation, lazy deriveds. Most performance problems are state-shape and effect problems.
- Use `$state.raw` for large data that you replace; use `$state` for small, edited-in-place state. Proxies cost on every read and change identity.
- `$derived` is lazy and has an equality cut-off for primitives; derive coarse values from fast-changing ones. Objects and arrays are compared by identity and always look changed when rebuilt.
- Replace “effect that sets state” with `$derived`; each state write in an effect costs another flush.
- Unkeyed each blocks are keyed by index. Use unique, stable, idempotent keys (`each_key_duplicate`, `each_key_volatile`); never use the index; use `{#key}` sparingly.
- Snippets are lighter than components for local reuse; do not declare classes in components (`perf_avoid_inline_class`, `perf_avoid_nested_class`); avoid spreading whole props objects when you can list props.
- Prefer `css` over `tick` in custom transitions; animate `opacity`/`transform`.
- Bundle size is the runtime features you use plus your code (illustrative: 25 kB min for a counter, 37 kB with each/if/transition/CSS); choose `css: 'external'` or `'injected'` deliberately; never import `svelte/internal/*`.
- Leaks come from unowned effect roots, global listeners, timers and external subscriptions; use cleanups, `createSubscriber` and `unmount`.
- Boundaries catch render errors only; redact server errors with `transformError`.
- Module-level state is shared by all server requests: never store per-user data there. Review every `{@html}`; mind CSP (`fragments: 'tree'`, nonces/hashes).
- Treat experimental flags as unstable, read changelogs, and fix warnings that predict Svelte 6.

## Review Questions

1.  List the four mechanisms that account for Svelte’s runtime efficiency and state one thing each of them does *not* do for you.
2.  A list uses `{#each items as item}` with no key. What key does the compiled code use, and what are the consequences when you insert an item at the front of a list of stateful rows?
3.  Why does `{#each todos as todo (['t', todo.id])}` throw `each_key_volatile` in development but not obviously in production? Fix it.
4.  What does `each_key_duplicate` report, and what is the usual root cause?
5.  Explain what the proxy created by `$state` costs on reads and what it costs on identity. Give two situations where `$state.raw` is the better choice.
6.  Rewrite this to avoid an effect chain and explain the performance difference:

    ```html
    <script lang="ts">
      let items = $state<{ price: number }[]>([]);
      let total = $state(0);
      $effect(() => { total = items.reduce((a, i) => a + i.price, 0); });
    </script>
    ```

7.  What does this print and why? (`n` is a prop changed from 2 to 4 to 6 and then to 7.)

    ```html
    <script lang="ts">
      let { n }: { n: number } = $props();
      let parity = $derived(n % 2 === 0 ? 'even' : 'odd');
      $effect(() => { console.log(parity); });
    </script>
    ```

8.  Why does `let visible = $derived(items.filter(...))` notify its dependents even if the filtered result contains the same members as before?
9.  A teammate says “I’ll split this component into ten smaller ones so that Svelte re-renders less.” Evaluate the claim.
10. When is a `{#snippet}` a better choice than a child component? Name one limitation.
11. Why does spreading `{...props}` onto an element weaken the compiler’s ability to optimise? How can you keep pass-through ergonomics without it?
12. What do `perf_avoid_inline_class` and `perf_avoid_nested_class` warn about, and what is the fix?
13. Multiple choice: for a custom transition, which is preferred and why?

    a.  `tick`, because it gives per-frame control.
    b.  `css`, because it is compiled into a Web Animation that can run off the main thread.
    c.  Both are identical.
    d.  Neither; transitions must use CSS classes.

14. Explain the trade-off between `css: 'injected'` and `css: 'external'`, and say which is forced for custom elements.
15. What does `fragments: 'tree'` change and why would you enable it?
16. Why can importing from `svelte/internal/client` in your own code never be a good idea? What happens if you try?
17. List three common sources of memory leaks in Svelte applications and the fix for each.
18. What is `createSubscriber` for? Describe when the `start` callback runs and when its cleanup runs.
19. Write the cleanup-correct version of this component:

    ```html
    <script lang="ts">
      let w = $state(0);
      window.addEventListener('resize', () => (w = innerWidth));
    </script>
    ```

20. What does `unmount` twice on the same handle cause?
21. What does `<svelte:boundary>` not catch? Give two examples and the correct handling.
22. What is `transformError`, which functions accept it, and why does it matter in production?
23. Under what conditions is `{@html}` dangerous, and what is the recommended mitigation? Name two other XSS vectors in a Svelte template.
24. Explain how module-level `$state` can leak user data across SSR requests. Give the safe alternative.
25. Multiple choice: which CSP configuration is required for the default template cloning approach to work under `require-trusted-types-for 'script'`?

    a.  Nothing; it works by default.
    b.  Compile with `fragments: 'tree'`.
    c.  Compile with `css: 'external'`.
    d.  Disable `discloseVersion`.

26. When should you use `csp: { nonce }` versus `csp: { hash: true }` in `render`, and what happens if both are set?
27. Name two browser-support caveats listed in the docs and the features they affect.
28. You are upgrading from 5.40 to 5.57 in production. List four steps of a sensible upgrade policy and one risk specific to experimental features.
