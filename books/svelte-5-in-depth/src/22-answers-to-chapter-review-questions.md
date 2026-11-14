# Answers to Chapter Review Questions

## Chapter 1: Svelte 5 Mental Model and Project Setup

1.  The compiler parses `.svelte` (and `.svelte.js/.ts`) files and rewrites them into JavaScript that calls helpers; the runtime is a small library (`svelte/internal/client`) implementing signals, effects, batching and DOM operations. Because the dependency graph is built at runtime by those helpers, any code that the compiler processed can create sources and deriveds, in a component or in a plain `.svelte.ts` module, and they interoperate.

2.  Svelte 4 emitted `$$invalidate` after each assignment and re-ran a component-level `update` function that checked a dirty bitmask. Svelte 5 builds a runtime graph: writing a `$state` source marks dependent deriveds and effects dirty, and only those effects (for example a template effect that sets one text node) re-run. Signals and effects replaced `$$invalidate`.

3.  It prints `setup 0` exactly once, when the component instance is created. The instance script never re-runs; clicking only updates the text node inside the button through a template effect.

4.  a\. `let n = 0` becomes `let n = $state(0)`; (b) `export let x` becomes `let { x } = $props()`; (c) `on:click` becomes `onclick`; (d) `new App({ target })` becomes `mount(App, { target })`.

5.  b\. Option a scaffolds SvelteKit; `create-svelte` is the old name for the SvelteKit scaffolder; c is not a real setup.

6.  Svelte 5 parses `lang="ts"` and strips type-only syntax itself, so annotations, interfaces and generics need no preprocessor. Add `vitePreprocess({ script: true })` for TypeScript features that need code generation (enums, constructor parameter properties), and add `vitePreprocess()` for `<style lang="scss">`/`postcss`-style preprocessing.

7.  For example `preprocess` (preprocessor groups), `compilerOptions` (passed to `compile`), `onwarn` (warning handler), `extensions`, `vitePlugin` (plugin options). `filename`, `format` and `generate` cannot be set because the plugin controls them for each file and for client versus server builds.

8.  a\. The module script runs once when the module is first evaluated; the instance script runs for every component instance. (b) Instance script and markup can reference module bindings, but module code cannot reference instance bindings. (c) `export default` is forbidden in `<script module>`, since the default export is the component.

9.  Module-level variables live for the lifetime of the process and are shared by every request, so one user’s value can be read by (or leak into) another user’s render. Per-request state belongs in context or must be created inside the request.

10. `state_referenced_locally`: “This reference only captures the initial value of `kind`”. Fix: `let label = $derived(kind === 'error' ? 'Error!' : 'Note')`.

11. It throws `rune_outside_svelte`. The file is a plain `.ts` file that the compiler does not process, and the TypeScript types declare runes globally so the editor sees no problem. Rename it to `makeCounter.svelte.ts` (any name containing `.svelte.ts`).

12. Rename the file to something like `counter.svelte.ts` (or `.svelte.js`), so the Svelte plugin compiles it as a module with runes support. Import it without the `.ts` extension (`./counter.svelte`).

13. `user` is reassigned and exported, so the compiler reports `state_invalid_export`: importers would see the underlying signal, because the compiler only rewrites references in the file it processes. Either export an object that you only mutate (`export const session = $state({ user: null })`) or keep the state private and export functions/getters (`export function getUser()`).

14. `track(count)` passes the current value, not the variable, so the callee gets a snapshot of a number. Pass a getter (`track(() => count)`), or an object whose property you read lazily, or use a class with accessor properties.

15. A rune is compiler syntax; there is no runtime function you can reference. The compiler rejects things like `const s = $state; s(0)` or `foo($state)` and errors on misplaced use such as `$state(0)` inside an expression (`state_invalid_placement`).

16. Order: the `runes` option (value or function), overridden by `<svelte:options runes>`; if still undefined, infer runes when any rune is referenced or the component uses `await` at top level/in markup; modules are always runes. Only (c) is compiled in runes mode. (a) and (b) are legacy; (d) uses `export let`, which is legacy.

17. It forces runes mode for the whole project including components in `node_modules`, and libraries still written in legacy mode will fail to compile. Use `dynamicCompileOptions` in the plugin options to scope by filename, or a function-valued `runes` option (5.54+), or `<svelte:options runes />` per component.

18. `mount` returns the component’s exports object (what the component exposes with `export`). `unmount` takes that returned object (the handle returned by `mount` or `hydrate`) plus an optional `{ outro }`.

19. A\. `[]`: the DOM exists but effects and `onMount` have not run. (B) `['mount', 'effect']`: both have run after the flush (in my run `onMount` logged before the initial `$effect`, as in the Vitest experiment). The point is that nothing runs synchronously inside `mount`.

20. Use it when the component has outro transitions and you want them to play before removal. The promise resolves after the transitions finish; by default it resolves immediately and the DOM is removed synchronously.

21. `intro` defaults to `true`, so transitions on elements in the initial render play. Pass `intro: false` to mount without playing them.

22. Call `flushSync()` (synchronous, flushes pending effects and DOM updates right away) or `await tick()` (resolves after pending state changes are applied, on the microtask). `flushSync` is synchronous and defeats batching; `tick` waits for the normal flush.

23. Generated code is compiled against the runtime and must call it, but the runtime internals are private and may change in any release, so user code importing `svelte/internal/*` is a compile error (`import_svelte_internal_forbidden`).

24. Domain logic in `.svelte.ts` classes/factories per feature folder, DOM-free helpers in plain `.ts`, presentational components in `.svelte` files. For SSR, replace module-level singletons by context-scoped instances so state is not shared between requests, and keep browser-only code in effects/`onMount`.

25. b\. `$state.snapshot` needs newer browsers only if you use it; `flip` needs Firefox 126; IE is unsupported.

26. It makes Vite/Vitest resolve the `svelte` package export to the client build (`index-client.js`) instead of the default server build. Without it `mount` is unavailable (server build throws `lifecycle_function_unavailable`) and effects do not run, so component tests would fail.

## Chapter 2: The Compiler — From `.svelte` to JavaScript

1.  Parse (source to AST for script, markup and CSS), analyze (scopes, bindings, runes/legacy mode, validation, CSS selector matching, warnings), transform (client or server JS, plus the CSS transform), print (ESTree to code and source map). The “never reassigned” decision is made in analyze, which tracks assignments and mutations per binding.

2.  `$.from_html` creates the static template once per module (the `root` variable); each instance clones it. `$.template_effect` runs once per instance immediately and then again whenever one of the sources it read changes. `$.delegated` runs once per instance for that element and registers the handler on the element (the single listener on the root exists once per event type).

3.  The server renders once: state does not need to be reactive, so `$state` becomes a plain variable, and event handlers can never run, so they are dropped. Output is a template string with `$.escape` around values.

4.  `a` is never reassigned, so it is a plain variable (`let a = 1`, even inlined into the text); `b` is reassigned (via `b++` in `bump`), so it is a signal (`$.state(2)`) read with `$.get(b)`; `o` is a `$.proxy({ x: 1 })` held in a plain variable because `o` itself is never reassigned.

5.  It means evaluating the parts of an expression that do not depend on reactive values at compile time. `{w + 1}` is folded to `4` (verified: output `'4 items'`) and `class="a {'b'}"` is folded to `'a b'`. `{count}` reads state, so it needs a template effect and cannot be folded.

6.  `'html'` creates a `<template>` via `innerHTML`, which is a Trusted Types sink and is incompatible with `require-trusted-types-for 'script'`; `'tree'` builds the elements one by one (`$.from_tree`), which works everywhere but is slower. `'html'` is the default because it is the faster strategy.

7.  Delegated: `click`, `keydown`, `input`, `touchstart`, `pointerdown`. Not delegated: `focus`, `mouseenter`, `scroll`.

8.  Delegated handlers run from a listener on the root; when the widget stops propagation in a native listener below the root, the event never reaches the root, so Svelte’s handler is not called. Fixes: use `on` from `svelte/events` (or `onclickcapture`) so ordering is preserved, or attach the widget’s listener differently or avoid `stopPropagation`; alternatively listen with a non-delegated event/capture phase.

9.  Props can change over time. Reading `$$props.a` inside the effect makes the effect depend on the prop’s getter, so when the parent changes the prop only that effect re-runs. Destructuring once would capture a single value.

10. `compileModule(source, { filename: 'x.svelte.ts' })` (the source must be JavaScript, i.e. types stripped). A module is always compiled in runes mode (`metadata.runes` is `true`).

11. `js` is `null` and `warnings` is still populated (I observed `js: null` and 0 warnings for a clean component). Linters, language servers and `svelte-check`-style tools use it to get diagnostics without generating code.

12. `css` is `null` when there is no `<style>` or when `css: 'injected'` embeds styles in the JS. `hasGlobal` is `true` when the stylesheet contains `:global` rules, so the bundler knows the CSS may affect the whole page.

13. `state_invalid_export`: `theme` is reassigned in `toggle`, so every reference is rewritten to `$.get`/`$.set` and importers would receive the signal object. Fix: export `getTheme()`/`toggle()` functions, or `export const ui = $state({ theme: 'light' })` and mutate `ui.theme`.

14. `settings` is never reassigned and compiles to a proxy that is exported directly; importers get the proxy and property reads/writes on it are reactive without compiler help.

15. A derived is accessed through its own function internally (`$.derived(() => ...)` read with `$.get`), so importers could not read it correctly; the reference to the derived value needs compiler rewriting in the file. Export a function returning the value instead.

16. `type`, `start`, `end`, `fragment`, `options`, `css`, `instance`, `module`, `comments`. Walk `ast.fragment` with `estree-walker` and collect `node.name` for nodes whose `type === 'RegularElement'`.

17. A deprecated stub that throws. Use `import { walk } from 'estree-walker'`.

18. A node from a modern AST (`parse(..., { modern: true })`) or any sub-node of it. It does not guarantee the original formatting (whitespace and quoting may differ), only valid Svelte; it returns `{ code, map }`.

19. `a:markup, a:script, a:style, b:markup, b:script, b:style`. The second group’s style preprocessor sees the `attributes` returned by the first group (the empty object, so no `lang`).

20. The output gets `lang="undefined"` (the key is written with the string `undefined`). Fix: return a new attributes object without the key, e.g. `const { lang, ...rest } = attributes; return { code, attributes: rest }` (or `{}`).

21. d\. `$effect.pre` does not silence a compile-time warning (and a declaration cannot sensibly live there). a, b and c all work.

22. Svelte scopes by adding a generated class to selectors and elements. If it kept an unmatched selector with the scope class, it would likely never match (and definitely not for content from child components or `{@html}`); if it kept it without the class, the rule would become global and affect the whole page. So it removes it and warns (`css_unused_selector`). Use `:global(...)` to opt out.

23. `'injected'` embeds the CSS in the JS (`$$css` object and `$.append_styles` on the client; a `<style>` in `head` during SSR) and `result.css` is `null`. With no `css` option, `compile()` returned the CSS in `result.css` (external behaviour).

24. `cssHash: ({ hash, filename }) =>`app-\${hash(filename)}\`\`. Reasons: stable, readable class names for tests, avoiding collisions when several Svelte apps (or versions) share a page, or hiding file paths.

25. It forces legacy mode for files in `node_modules` and runes mode for everything else. Returning `undefined` for a file means “infer the mode” from the component’s contents.

26. c\. `$.template_effect` re-runs when a dependency it read changes, not on props identity; generated helpers are private (not importable), and server output drops effects entirely.

27. With `warningFilter`/`onwarn` you can only act on warnings the compiler already emits; `on:` produces `event_directive_deprecated`, and `{@html}` has no compile warning, so this covers only the first rule but is trivial to set up and exactly matches compiler semantics. With `parse` plus `estree-walker` you can detect both (`OnDirective`, `HtmlTag`) and report line numbers, at the cost of maintaining the script and depending on AST node names (modern AST; stable across the 5.x line but part of the tooling surface).

28. The output is a private contract between compiler and runtime and changes in minor and patch releases (names, flags, argument orders). Regexes break silently or produce wrong transformations. Use the public API (options, `parse`/`print`, preprocessors) and the documented behaviour instead.

## Chapter 3: `$state` — Deep Reactivity, Proxies and Ownership

1.  `0`: a plain source. `[]`: a deep proxy. `{}`: a deep proxy. `new Map()` and class instances: stored as-is in a source (no proxy); a class needs `$state` fields for reactivity and `Map` needs `SvelteMap`.

2.  `typeof value === 'object'`, not null, not already a proxy, and its prototype is exactly `Object.prototype` or `Array.prototype`.

3.  It prints `false 0`. `list[0]` is a proxy distinct from `item`, so `includes(item)` fails; `indexOf(list[0])` uses the proxy and finds it.

4.  `proxy === original` warns (operators are instrumented). `list.includes(original)` silently returns false, no warning. `proxy.a === 1` compares primitives, no warning.

5.  `s` is never reassigned, only mutated, so reading the proxy itself registers a dependency on nothing that changes. Read the property: `$effect(() => { s.value; })`.

6.  `done` is a copy made at destructuring; it prints `false`. Read `todos[0].done` at the point of use.

7.  It prints `[]` and warns `assignment_value_stale`: `??=` evaluates to the raw right-hand array, so the push is lost. Fix: `o.list ??= []; o.list.push(1);`.

8.  The proxy only permits plain data descriptors that are enumerable, configurable and writable; error `state_descriptors_fixed`.

9.  `Object.keys` gives `['text']` and `JSON.stringify` gives `{"text":"a"}`; `done` is a prototype accessor over a private field, so it is not an own enumerable property.

10. A prototype method called by the event system has `this` set to the element. Fix 1: inline closure `onclick={() => todo.reset()}` (no per-instance cost, slight verbosity). Fix 2: arrow function field `reset = () => {...}` (bound everywhere, but one closure per instance).

11. Valid as the first assignment at the top level of the constructor (5.31); invalid in a method (`state_invalid_placement`). It generates a private field with a getter/setter pair on the prototype and `this.#a = $.state($.proxy(value))` in the constructor.

12. For large data that is only reassigned (API payloads), class instances or third-party objects. Avoided costs: per-object Proxy creation, trap overhead on every read/write, and per-property sources plus the Map/version memory.

13. No re-run, because raw state has no property tracking; but the value does change (the object is mutated), so reads show the new age. Reassign to notify.

14. a\. A real `Date` clone; (b) the clone of `toJSON()`’s result; (c) a plain object copy without the prototype (not `instanceof` the class); (d) the original is returned and dev logs `state_snapshot_uncloneable`.

15. It uses `structuredClone`, available from those versions.

16. b\.

17. A reassigned state variable is compiled to a signal object with `$.get`/`$.set` rewriting inside the file; importers would receive the signal and the compiler cannot rewrite them. A never-reassigned object is a proxy exported directly, whose property accesses are reactive on their own.

18. Export functions (`getCount()`, `increment()`) over a private `$state` variable; or export an object (`export const counter = $state({count: 0})`) and mutate `counter.count`; or a class instance.

19. It returns an object whose `value` is a snapshot of the number at creation (actually the derived’s current value read once, then constant). Use `get value() { return d; }` and pass a getter for `n` (`() => n`) so it stays live.

20. The mutation works and updates the parent (it is a shared proxy), and dev warns `ownership_invalid_mutation`. Fix with a callback or `$bindable`.

21. Nothing visible happens: the plain object is not reactive and no warning is given (not a proxy).

22. `GrandParent` does `<Parent {value}>` (no `bind:`) while `Parent` does `<Child bind:value>`: Parent binds a value its own parent did not declare as a binding, so dev warns `ownership_invalid_binding`. Fix with `<Parent bind:value>`.

23. After `m.get('a')!.n++`: no, values are not deeply reactive. After `m.set('a', {n: 5})`: yes, the per-key source changes.

24. `SvelteMap`, `SvelteSet`, `SvelteDate`, `SvelteURL`, `SvelteURLSearchParams` (plus `MediaQuery` and `createSubscriber`). `SvelteDate` memoises each getter in a derived so only effects whose result changes re-run.

25. Use `$state.raw` for the 50,000-row array (no proxies), update a cell by replacing the row/array immutably (or hold per-row class instances with `$state` fields if edits are frequent and rows few at a time), and compute filtered/sorted views with `$derived` so equality cut-off and memoisation apply. Deep `$state` would proxy every row lazily and add per-property overhead.

26. Module state lives for the process, so requests share it and can leak user data. Use context (`createContext`/`setContext`) to create per-render instances (Chapters 12 and 14).

27. `console_log_state`. Use `$inspect(todos)` for tracking changes, or `console.log($state.snapshot(todos))` for one-off logs.

## Chapter 4: `$derived` and `$effect` — Dependency Tracking and Side Effects

1.  On a source write, dependents are notified immediately and marked dirty or maybe-dirty (push) but not recomputed. When something reads the derived (a template effect during the flush, or code), it recomputes if dirty (pull) and caches the result; if the result is identical to the old one, downstream reactions are skipped.

2.  Zero times. Deriveds are lazy; I observed `computes === 0` before the first read.

3.  It prints `1`. `big` stays `false` for `n = 3` and `n = 4`, so the cut-off prevents the effect from re-running.

4.  `const x = $derived(a + b)` (or `$derived.by(() => a + b)`). The original makes `x` a function (the derived’s value is the arrow function), not a number.

5.  `a` is always tracked; while `a` is true `b` is tracked and `c` is not, so changes to `a` or `b` re-run it. Once `a` is false, `c` is tracked and `b` is not. Dependencies are those of the latest run.

6.  Writing `total` inside the derived throws `state_unsafe_mutation` when the derived is read. Fix: make `total` itself the derived (`let total = $derived(items.reduce(...))`) and drop the extra state.

7.  `$derived` destructuring creates one derived per variable on top of the derived object, so `a` has equality cut-off from `obj.a` (unchanged `a` does not propagate). Destructuring `$state` copies values once and never updates.

8.  `let likes = $derived(post.likes)`; on click do `likes += 1`, call the server, and `likes -= 1` on failure. The override is replaced as soon as a dependency (`post.likes`) changes and the derived recomputes (I saw it go from 2 to 5 when `post` was replaced).

9.  Yes. Since 5.24 state created inside a derived or effect may be written and read locally without error; it returned 1.

10. Script, `$effect.pre` (during init), mount returns, then first flush: `$effect`, `onMount`. On a state change: `$effect.pre`, teardown of the previous run, then `$effect`. On unmount: effect teardown, `onMount` cleanup, `onDestroy`.

11. `mount` builds the DOM synchronously and queues effects for a microtask. In tests call `flushSync()` (or `await tick()`).

12. It throws `effect_orphan`: effects can only be created while a parent effect (such as component initialisation) is running, not in event handlers.

13. Tests (no component exists to own the effect) and long-lived modules or singletons that need effects with a manually managed lifetime (also effects created after an `await` in a function).

14. Same semantics, different timing: `$effect.pre` runs before DOM updates that are scheduled after it (and during component init), `$effect` after the DOM update. Use `$effect.pre` to measure scroll position before the new messages render.

15. `false`, `true`, `true`. `createSubscriber` should only attach listeners when the value is read in a tracking context, so it checks it (via `$effect.tracking`) to avoid leaking listeners when read in an event handler.

16. `size` is read inside `setTimeout`, asynchronously, so it is not tracked. Only `color` is tracked.

17. A `StaleReactionError`. Example: `const signal = getAbortSignal(); fetch(url, { signal }).catch((e) => { if (e.name !== 'AbortError') throw e; })` (or check for `StaleReactionError` in the reason).

18. `onMount` registers the returned function only if the callback is synchronous; an `async` function returns a promise, so the cleanup is ignored.

19. `onDestroy` runs on the server; `onMount` does not. `beforeUpdate` and `afterUpdate` throw `lifecycle_legacy_only` in runes mode (and importing them in a runes component is `runes_mode_invalid_import` at compile time).

20. `let left = $derived(total - spent); function updateLeft(v: number) { spent = total - v; }` and `<input type="range" bind:value={() => left, updateLeft} />`.

21. `effect_update_depth_exceeded` after more than 1000 iterations (I saw 1001 writes). The second is safe: it writes state it does not read, so it settles after one run (and equal writes do not invalidate).

22. Wrapping the read in `untrack(() => list.push(x))` removes the dependency on `list`, so the effect no longer re-triggers itself. Downside: the effect will not re-run when `list` changes, which may hide a real dependency; also `push` is a mutation that still triggers other readers.

23. c\.

24. It passes `'init'` or `'update'` followed by the current values of `a` and `b`, replacing the default `console.log`; it is called initially and whenever the values (deeply) change. It is a no-op in production builds.

25. As the first statement of a function body (typically an `$effect` or `$derived.by` callback). It prints which reactive values caused this run, with their names and stack traces (dev only).

26. `const subscribe = createSubscriber((update) => on(window, 'resize', update));` then `get width() { subscribe(); return window.innerWidth; }` (same for `height`), inside a class. The listener attaches only while an effect/template reads it and is removed when the last reader goes away. An unconditional `$effect` in a module would be an orphan (`effect_orphan`) or need `$effect.root`, would attach the listener forever, and would not run on the server.

27. `derived_inert`: “Reading a derived belonging to a now-destroyed effect may result in stale values”. Create the derived outside the effect, or inside an `$effect.root`.

## Chapter 5: Inside the Reactivity Graph — Signals, Batches and the Flush Loop

1.  Sources (`reactions`), deriveds (`deps` and `reactions`, since they are both reaction and source), effects (`deps`, plus the tree links `parent`, `first`, `last`, `next`, `prev`).

2.  `CLEAN`: up to date. `DIRTY`: a direct dependency changed. `MAYBE_DIRTY`: a derived dependency was marked, so the reaction may or may not need to run. A reaction that reads a source through a derived is marked `MAYBE_DIRTY`.

3.  It marks reactions attached to an effect root: effects, and deriveds that at least one effect depends on. A derived is connected when read inside a connected reaction and disconnected when its last reaction goes away, so unused deriveds can be collected.

4.  Check `state_unsafe_mutation` conditions (active derived/block/async/eager reaction and source not created locally); proxify if requested; in `internal_set` return if `equals`; record old value, `Batch.ensure()` and `capture`; bump `wv`; `mark_reactions(source, DIRTY)`, which marks readers, recurses through deriveds with `MAYBE_DIRTY`, and schedules effects. The first check throws.

5.  `internal_set` returns right after `source.equals(value)`; nothing is marked or scheduled.

6.  `update_derived` recomputes and increments the derived’s `wv` only if `!equals(newValue)`. `is_dirty` compares each dependency’s `wv` with the reaction’s `wv`. Unchanged derived means no version bump, so the effect stays clean. It must be in the pull phase because the new value is only known when the derived is evaluated, which mark does not do.

7.  `rv` stamps a source with the current read version so a duplicate read in one run is detected by an integer compare; `skipped_deps` counts reads that match the previous run’s `deps` in the same order so no new array is allocated. They avoid Set lookups and array allocation (GC).

8.  It destroys child effects (unless block/managed) and runs the previous teardown, then runs the function. Thus child effects created inside the effect are destroyed and recreated each time.

9.  a\. root; (b) branch; (c) block; (d) render effect (template effect); (e) user effect (`EFFECT | USER_EFFECT`); (f) eager effect.

10. The component body runs under a branch effect, which sets `active_reaction = null`, so reads are not registered; only render/user effects and deriveds track.

11. ROOT (mount) \> BRANCH (App) \> \[ BLOCK `{#if}` \> BRANCH consequent \> RENDER (template effect for `{n}`), BRANCH (Child) \> …, EFFECT (`$effect` logging n) \]. The static `<p>` creates no effect of its own; the order of children follows creation order.

12. `n` marks the `{n}` render effect and the user effect (both direct readers). They are scheduled; at flush the render effect runs during traversal, then the user effect runs after, in tree order. The `{#if}` block does not depend on `n` and is not re-run.

13. `{#key}` destroys and recreates its entire branch subtree (all effects and DOM) when the expression changes; a derived only recomputes a value and updates the nodes that read it.

14. The block effect reconciles by key and keeps an item record with its own branch effect and sources per key; reorder moves DOM nodes without destroying the branches.

15. Apply batch values; traverse the tree skipping clean branches, running dirty block effects (and render effects in non-async mode) during traversal and collecting user effects (and render effects in async mode); if deferred by async work, stash; run commit callbacks; run queued render effects; run queued user effects; loop if new effects were scheduled.

16. `A:0`, then `after write`, then after the microtask `A:1` has been pushed before `after microtask`: order `['A:0', 'after write', 'A:1', 'after microtask']`. The write is flushed in a microtask queued earlier than the `await` continuation.

17. A counter in the flush loop; when it exceeds 1000 iterations it calls `infinite_loop_guard`, which throws `effect_update_depth_exceeded` (in dev with the locations of repeated writes).

18. Each write schedules the next effect in the same flush loop, so the chain finishes within one flush (A then B). It is discouraged because it adds a pass per hop, intermediate state is observable, and a `$derived` expresses it directly.

19. `flushSync` flushes everything synchronously. `tick` waits one microtask then calls `flushSync` (in async mode it races `requestAnimationFrame` and `setTimeout`). `settled` waits until pending async work is finished and the batch has committed.

20. Once for the three reads (the first computes, the rest use the cached value), then once more after the write: two runs in total. It can be collected because, when disconnected, sources do not hold it in their `reactions`; only it holds references to them.

21. They are frozen: their teardowns run and they are detached; they are unfrozen (re-run) when the derived is reconnected.

22. Its parent effect can be destroyed while the derived survives; it is then no longer connected to a live tree and may not be notified, so reads may be stale.

23. `batch_values` is a map of the values a batch wrote; during traversal of a batch it is set, and `get` returns the batch’s value instead of the real one so effects in that batch see a consistent snapshot while another batch holds the older state. This lets the UI keep showing old state until async work resolves.

24. Writes are stored in the fork batch’s `batch_values` instead of the real sources, and the fork batch is flushed to build the speculative DOM. `commit` writes those values into the sources, bumps write versions, runs eager effects and flushes; `discard` bumps write versions so deriveds revalidate and drops the batch.

25. An `EAGER_EFFECT` reads the expression with `batch_values = null` (real current values) and runs immediately after the write (`flush_eager_effects`), then bumps a version source to re-run the consuming template effect, bypassing the batch’s deferral.

26. Creating a source for every property of every object would waste memory; most properties are never read. A source is created on first read/has/write. `Object.keys` depends on the proxy’s `version` source (key set changes), plus per-key existence through `ownKeys` filtering.

27. Props without fallback or binding are accessed via the props object whose getters register the dependency. Props with a fallback or bindable flag go through `$.prop`, which returns an accessor handling fallback evaluation, local overrides and the bindable setter.

28. Spread builds a proxy over a list of prop objects; each read goes through traps iterating the list (and `ownKeys`/`has` enumerate everything), instead of a direct getter.

29. Roughly: per row a branch plus one or two template effects (the two text expressions are likely merged into one), an `{#if}` block effect and, while true, its branch with children, so about 3 to 6 per row, i.e. 3,000 to 6,000 for the list. Reduce by virtualising, merging expressions, removing per-row blocks, and `$state.raw` data.

30. They are private and change between minor/patch releases (and imports are rejected by the compiler in runes mode). Use `$inspect.trace`, effect counting, `compile()` output inspection and the public API.

## Chapter 6: Template Syntax — Markup, Events and Control Flow

1.  Component-versus-element is decided lexically: only capitalised or dot-notation tags are components. Write `<View />` (rename the variable to a capitalised identifier) or use dot notation such as `<views.current />` / `<item.component />`. `<svelte:component this={view}>` also works but is deprecated.
2.  `data-a="0"` (present: 0 is not nullish), `data-b="false"` (present: false is not nullish for a non-boolean attribute), `data-c` absent (null), `hidden` absent (boolean attribute, falsy), `aria-hidden="false"` (present).
3.  b). (a) works in HTML-style only when the value is a single token without braces; `/user/{id}` mixes text and an expression unquoted and gives `attribute_unquoted_sequence`. (c) is the same error. (d) is `attribute_invalid_event_handler` because event attributes must be expressions.
4.  `<C prop="{n}" />` warns (`attribute_quoted`): in Svelte 6 a quoted single expression on a component or custom element becomes a string instead of passing the number. On a plain element the DOM attribute is a string anyway, so nothing changes.
5.  `a` is `1` (the spread comes after `a="b"` and wins) and `c` is `"d"` (the literal after the spread wins). Later attributes always take precedence.
6.  `[][false][][0]`. In Svelte 4 `null` and `undefined` printed as the strings “null”/“undefined”; in Svelte 5 nullish values become the empty string. `false` and `0` still print.
7.  The binding updates first, then `oninput` runs. Docs: event attributes always fire after events from bindings. This lets `oninput` read the already-synchronised bound value for validation or side effects.
8.  Event attribute names are case-sensitive and map directly to the event type: `onClick` listens to an event literally named `Click`. This allows custom events with uppercase letters (e.g. `onMyEvent` for `MyEvent`) to be listened to.
9.  Append `capture` to the name: `onclickcapture={handler}`. It is not delegated; the compiler emits a real listener with the capture flag (`$.event('click', el, handler, true)`).
10. The native `stopPropagation` on the container prevents the event reaching the app root, where delegated handlers (`pointerdown` is delegated) run, so the buttons’ declared handlers never execute. Fixes: register the library’s (or your own) listener with `on()` from `svelte/events`, which keeps ordering and honours `stopPropagation` for declared handlers; or use a non-delegated/capture route such as `onpointerdowncapture`, or stop calling `stopPropagation` in the library.
11. `click` is delegated and a manually dispatched event does not bubble by default, so it never reaches the root listener. `button.click()` creates a bubbling event. Use `new MouseEvent('click', { bubbles: true })`.
12. For example `focus`, `blur`, `mouseenter`, `scroll`, `submit`, `load`, media events, custom events. A delegated handler compiles to `$.delegated('click', el, fn)` plus a module-level `$.delegate(['click'])`, with no listener on the element; a non-delegated one compiles to `$.event('focus', el, fn)`, a real `addEventListener`.
13. The native button listener runs first (target phase), then Svelte’s root listener runs declared handlers in bubbling order: the button’s `onclick`, then the div’s `onclick`. Order: native, button handler, div handler.
14. When you need `{ passive: false }` (to call `preventDefault()` in a touch handler): `ontouchstart`/`ontouchmove` attributes are always passive, so register with `on(node, 'touchmove', fn, { passive: false })`, typically inside an attachment or action.
15. 1.  Unescaped, so XSS if not sanitised. (2) Must be valid standalone HTML. (3) It is not compiled as Svelte (no components). (4) Content gets no scoped-style hash, so component selectors don’t match; use `:global`. (5) Hydration mismatches are not repaired (dev warning only). (6) Any change replaces the whole fragment, which is expensive.
16. The compiler warns `css_unused_selector` for `article a` because it cannot see the injected nodes. Fix: `article :global { a { color: red } }` (or `article :global(a)`).
17. b\. `each_key_duplicate` is thrown at runtime (verified in dev).
18. `{#each { length: 3 }, row}{#each { length: 3 }, col}<div></div>{/each}{/each}`. Each without an item was added in Svelte 5.4; `{ length: 3 }` is an array-like.
19. An index key is equivalent to no key: inserting at the front reuses DOM and component state by position, so state sticks to the wrong data. Leaving the key off is better for lists of simple, stateless text that are replaced wholesale, since reconciliation by key costs time and gains nothing.
20. a\. The pending branch only. (b) The `:then` branch (non-promises skip pending even on the server). (c) Nothing: the catch-only form has no pending content.
21. Rendered values: `2`, `2`, then `1` (inner declaration shadows inside the div and its children; the outer `x` is visible again after the div).
22. `{#each rows as row}{const total = row.qty * row.price}<td>{total}</td>{/each}`. Declaration tags work anywhere in markup (not only as the immediate child of a block) and may contain `$state` and `$derived`, e.g. `{let draft = $state(row.name)}`. `{@const}` is legacy and cannot hold state.
23. `declaration_tag_invalid_type`; `declaration_duplicate`; `declaration_tag_no_legacy_mode` (declaration tags only work in runes mode, and `export let` puts the component in legacy mode).
24. It renders `foo- bar` because whitespace at the start of a tag’s content is trimmed. Restore with `foo <span>- bar</span>` or `<span>{' '}- bar</span>`.
25. `class="btn"` (the `active` key is falsy, and `false` in an array is skipped). If the whole value is `false`, the attribute is rendered as `class="false"` today (only `null`/`undefined` omit it); a future Svelte version will omit it.
26. Red. `style:` directives take precedence over the `style` attribute, even over `!important` declarations in it.
27. `{#if}` chains: no runtime magic, verbose, good typing per branch, forces duplicated attributes. `<svelte:element this={`h\${level}`}>`: a single element, any props and attributes, but the tag type is a string so you lose per-tag typing and it must be a valid DOM tag; nullish hides it; no built-in bindings except `bind:this`. A lookup of component references adds an indirection and wrapper components with no benefit for plain tags. For headings, `svelte:element` is the usual choice; use branches only if each level needs different structure.
28. Browsers auto-insert `<tbody>`, so the parsed DOM would differ from the DOM the compiler assumed (and from what hydration expects from the server-rendered HTML). Rejecting it at compile time prevents hydration mismatches and broken node references.

## Chapter 7: Components, Props and Snippets

1.  A destructured prop is compiled to a read of the props object at each use site, but a top-level statement runs once, so `count * 2` captures only the initial value. Fix: `let doubled = $derived(count * 2)` (or compute it inside the template/closure).
2.  It prints `2` after one click: the child may temporarily override (reassign) a prop. If the parent later provides a new value (`10`), the parent’s value wins and the button shows `10`.
3.  a\. No UI update and no warning: a plain object is not reactive. (b) The UI updates but dev mode warns `ownership_invalid_mutation`, because the child mutates state it does not own. (c) No UI update: destructuring fallbacks are not proxied, so the mutation is invisible.
4.  In dev it throws `props_rest_readonly`; in production the proxy’s `set` trap returns `false`, which throws a `TypeError` in strict mode. The extra readable error is a dev-only convenience (there is a TODO in the source about enabling it in production), keeping the production bundle small.
5.  `$props.id()` is identical on server and client, so SSR output and hydration agree. `crypto.randomUUID()` (or counters/`Math.random`) differs between server and client and causes hydration mismatches.
6.  The name is reserved: content between the tags becomes the `children` snippet prop, so it collides with (or overwrites) your data prop. Rename the data prop.
7.  b\. Callback props named `onsomething`. (a) works technically but breaks the naming convention; (c) does not exist; (d) `on:` on components is the legacy event API and is not available with runes-mode components’ callback props.
8.  The handler comes before the spread, so `props.onclick` replaces it. Put local handlers after the spread and call the incoming one: `<button {...props} onclick={(e) => { track(); props.onclick?.(e); }}>`.
9.  Mixing old and new event syntaxes in one component is the compile error `mixed_event_handler_syntaxes`. Migrate the whole component to `onevent` attributes.
10. The call site passes getters (e.g. `() => $$props.n`) so the snippet re-reads the value when it changes. Parameters are therefore reactive, not copies, and defaults are evaluated lazily through `$.fallback`.
11. c\. `{#snippet c(...rest)}`: rest parameters are not supported (`snippet_invalid_rest_parameter`: use an array). Defaults, destructuring and type annotations are fine.
12. It prevents a snippet declared inside component tags from silently replacing an attribute prop of the same name: `<C header={1}>{#snippet header()}x{/snippet}</C>` is an error because the implicit prop and the explicit attribute collide.
13. Explicit: declare snippets and pass them by name (`{header}`). Implicit: snippets declared directly inside component tags become props of the same name. `children`: non-snippet content becomes the `children` snippet. `$$slots` in the compiled output is bookkeeping for interop with components that use legacy slots.
14. `{@render header()}` throws `invalid_snippet` (expression is `undefined`). Fix with optional chaining `{@render header?.()}` or an `{#if header}` block with fallback content; type the prop as optional (`header?: Snippet`).
15. `<script lang="ts" generics="T">` … `let { options, option, onchange }: { options: T[]; option: Snippet<[T]>; onchange: (value: T) => void } = $props();`
16. The `Snippet` type takes a tuple of parameter types; an array type would imply a rest parameter, which snippets do not support (the type uses `number extends Parameters['length'] ? never : Parameters`). Write `Snippet<[string]>` for one string parameter.
17. Only top-level snippets, exported from `<script module>`, that reference nothing from the instance script (directly or through other non-exportable snippets). Otherwise: `snippet_invalid_export`. Requires 5.5+.
18. The callback receives each parameter as a getter function (`(who: () => string) => ...`). `render` must return an HTML string for a single element, and optional `setup(element)` runs once with that element and may return a cleanup. The result is inserted as HTML, so interpolated values must be escaped by you.
19. Snippets-with-arguments suit headless UI that is inherently tied to markup and lifetime of a component (a disclosure or popover that hands state and handlers to a template). A `.svelte.ts` class with `$state` fields suits logic that should be shared, reused outside the component tree, tested without mounting, or composed without extra nesting.
20. `effect_update_depth_exceeded`: the effect reads (`push` reads `length`) and writes the same reactive array, so it re-triggers itself. Fixes: wrap the write in `untrack`, use a non-reactive container for the registry, have the parent derive the tab list from its own state, or register in an event handler/attachment instead of an effect.
21. Only the component’s exports (`focus`, `increment`, `version`), not its props or internals. Runes mode forbids `bind:` to exports to keep props and exports separate; use `bind:this` and `c?.version`.
22. It is assigned after the component mounts, and goes back to `null`/`undefined` when the component is destroyed. Before mount or after destroy it is empty, so guard with `?.` and read it in handlers or effects.
23. `typeof Comp` is the component constructor/function type (what you pass to `mount` or store as a value); `ReturnType<typeof Comp>` is the instance type with exports, which is what `bind:this` provides.
24. `<svelte:self>` is deprecated (`svelte_self_deprecated`) and restricted to `{#if}`, `{#each}`, `{#snippet}` or slots (`svelte_self_invalid_placement`). Import the file into itself (`import Self from './Tree.svelte'`) instead. Without a base case (an `{#if}` or empty children) a self-render loops forever.
25. Without `bind:` the child’s fallback `'fb'` is used. With `bind:value={v}` and `v === undefined` the runtime throws `props_invalid_value` (“Cannot do `bind:value={undefined}` when `value` has a fallback value”): the parent and child must share one defined starting value.
26. A prop is only bindable if the child marks it with `$bindable()`; the compiler/runtime treat other props as one-way. The runtime does not reliably throw (`bind_not_bindable` is declared but I could not trigger it in 5.57.2), so use typed components and `svelte-check` to catch it.
27. Example: data (`rows`), config (`columns`, `sortKey`), and `selected = $bindable()` as props; cell and header rendering as snippets (`Snippet<[Row]>`, `Snippet<[Column]>`); `onsort`, `onrowclick` as callback props; optional `scrollToRow()` as an export. State shared by sub-components (selection) lives in context or a class. Justification: data flows down, content is passed as snippets, notifications flow up through callbacks, and only commands without state representation are exported.
28. Reassigning only changes the child’s local view of the prop and is overwritten by the next parent value. Mutating a proxy changes the parent’s state from a place that does not own it, so data flow becomes untraceable (hence `ownership_invalid_mutation`). Use a callback or `$bindable` to make the intent explicit.

## Chapter 8: Bindings and Forms

1.  A listener on the element’s `input` event reads the DOM value and calls the setter (DOM to state), and a render effect reads the getter and assigns the DOM property when it differs (state to DOM). After the handler, `await tick()` lets the setter’s result propagate; if the getter now returns something different from what was typed (validation or transformation), the DOM value is rewritten and the caret restored.
2.  `null` in 5.57.2 (`to_number` returns `null` for `''`). The prose docs say `undefined`; the source is authoritative, so type the state `number | null` and avoid `=== undefined` checks.
3.  It shows `ab` in the paragraph and the input is rewritten to `ab`. The setter stores the lowercase value; after the tick the getter differs from the typed `Ab`, so Svelte writes `ab` back to the input.
4.  In practice the binding updates first, so `oninput` sees the new value (basic-markup doc: event attributes fire after bindings). The `bind:` doc statement (“an existing listener for the same event fires before the bound value is updated”) covers listeners registered before the binding, such as earlier native listeners or legacy `on:` handlers.
5.  b). `bind:checked` and `bind:group` on checkboxes are the supported forms.
6.  `bind:group` coordinates inputs within the same component only. Split a group by having a parent own the value and pass it down with a callback prop (`checked={v === x}` and `onchange={() => select(x)}`), or bind a `$bindable` prop in each child.
7.  `const dt = new DataTransfer(); [...files].forEach((f, i) => i !== 1 && dt.items.add(f)); files = dt.files;`. `FileList` is immutable and cannot be constructed directly, so `DataTransfer` is the only way to produce a new one.
8.  `DataTransfer` does not exist in server runtimes, so evaluating it during SSR throws. Leave the state uninitialised (`$state<FileList | undefined>()`) and create `DataTransfer` only in handlers.
9.  It is the identical object (same reference, not a copy), because Svelte stores the JS value on the option. You can compare with `===` or use it as a Map key.
10. `undefined` or `null`: the current selection is kept. A string (non-array): the runtime warns `select_multiple_invalid_value` and keeps the selection.
11. a\. The binding wins on first render: `typed`. (b) After reset the field shows `x` (the default) and the state becomes `x` one microtask later, because the reset listener waits a microtask for the DOM to update, then re-reads the control.
12. Capture phase on `document` means `stopPropagation` elsewhere cannot hide the event; the microtask delay exists because the control’s properties have not been reset yet when the event fires. A `defaultPrevented` reset event cancels the resync (as it cancels the reset).
13. Yes: controls associated with `form="f"` are in `form.elements`, so they are resynced. A control with no association is not part of `elements` and is not touched.
14. Two-way: `currentTime`, `playbackRate`, `paused`, `volume`, `muted`. Read-only: `duration`, `buffered`, `seekable`, `seeking`, `ended`, `readyState`, `played` (plus `videoWidth`/`videoHeight` for video). `duration` is `NaN` until metadata loads, so start from `0` and guard.
15. The binding takes full control of the contents, so expressions inside do not update (migration guide). `bind:innerHTML` is not safe to render elsewhere unsanitised: user or pasted content controls the HTML, same XSS concerns as `{@html}`.
16. Inline elements have no box size and cannot be observed by `ResizeObserver`. Fix: `display: inline-block` (or another non-inline display), or use an element with intrinsic dimensions. `devicePixelContentBoxSize` does not work in Safari; the others (`clientWidth`, `offsetWidth`, `contentRect`, …) are fine.
17. `el` is `undefined` while `show` is false (and during init), so `el.focus()` throws a TypeError on the first effect run. Use `el?.focus()` and make `el` `$state` so the effect re-runs when the element mounts.
18. a\. `undefined`, (b) the element/exports, (c) `null`. With a function binding the getter lets Svelte check that the variable still holds this element before nulling it, so it does not null a value that another element has taken over.
19. `<input bind:value={() => name, (v) => (name = v.trim().slice(0, 20))} />`. The effect version writes state after DOM updates (a transient wrong value, an extra flush, and a loop risk); the function binding transforms at the moment of input and Svelte rewrites the field.
20. It is a read-only binding with a `null` getter: nothing is stored, and `redraw` is called whenever the width changes. Use it to run a side effect on measurements without keeping state.
21. `Own.svelte` forwards the prop `data` into `bind:value` of the child, but the parent passed it one-way, so a mutation in the child changes state owned by the parent through an intermediary that did not declare a binding. Fixes: declare `data` as `$bindable()` in `Own` and use `<Own bind:data={d} />`; or give the child a callback and let the owner mutate.
22. `each_item_invalid_assignment`: runes mode forbids binding or reassigning the each variable itself. Use `bind:value={items[i]}` (with the index) or bind to a property of the item (`bind:value={item.text}`).
23. `scrollX` and `scrollY` (the rest are read-only). The initial value does not scroll, to avoid accessibility problems; only later changes scroll. To scroll at mount call `scrollTo()` in an `$effect`.
24. Controlled: bind to state when other UI depends on the value live (previews, counters). Uncontrolled: no binding, read `FormData` on submit; cheapest, works without JS. Draft: bind to a copy and commit or discard; best for editing existing records.
25. Each effect writes the state the other one reads, so they re-trigger each other (rounding eventually stops them, or `effect_update_depth_exceeded` fires). With one source of truth (`celsius`) and a function binding for Fahrenheit, there is only one piece of state and nothing to ping-pong.
26. After each keystroke the getter returns the formatted string, which differs from what was typed, so Svelte rewrites the field. Fix: keep a `draft` string while editing (show `draft ?? formatted`) and clear it on `blur`.
27. `bind:value={pin}` with `pin` undefined throws `props_invalid_value` (a bindable with a fallback requires a defined parent value). Fixes: initialise `let pin = $state('0')`, or remove the fallback (or do not bind).
28. a\. `bind_invalid_expression`; (b) `bind_invalid_target` (`bind:value` only on input/textarea/select); (c) `constant_binding` (“Cannot bind to import”); (d) `bind_invalid_expression` (a getter without a setter is not a valid `{get, set}` pair).

## Chapter 9: Actions, Attachments, Special Elements and Browser APIs

1.  1.  Actions run once, untracked, and ignore argument changes (unless they use effects or the legacy `update`); attachments run in an effect and re-run when state read in the function or factory expression changes. (2) Actions cannot be used on components (`component_invalid_directive`); attachments become Symbol-keyed props that flow through spread. (3) Both run after mount and not on the server, but an attachment’s cleanup also runs before each re-run, not only on removal.
2.  Only `run 0` at mount; nothing after `n++`. The action is invoked once and untracked; the argument change does not call it again (it has no `update` method).
3.  `run 0` at mount, then `run 1` after `n++`. The expression `track(n)` is evaluated in an effect and yields a new function, so the old attachment is destroyed (cleanup runs) and the new one runs.
4.  `function tooltip(getContent: () => string): Attachment { return (el) => { const inst = tippy(el); $effect(() => inst.setContent(getContent())); return inst.destroy; }; }` used as `<button {@attach tooltip(() => content)}>`. The instance is created once; only the nested effect tracks `content`.
5.  The template expression `tooltip(() => content)` never reads `content` itself (the getter is only called inside the nested effect), so nothing the expression read changed and it is not re-evaluated. The arrow function is created once per evaluation, not per change.
6.  A prop keyed by a Symbol holding the attachment. `Button` must spread its rest props onto an element (`<button {...rest}>`). Named destructuring ignores symbol keys, and `...rest` carries them through, so a component that only picks named props drops the attachment.
7.  c\. No attachment and no error. Falsy values are treated as no attachment.
8.  `<div {@attach fromAction(foo, () => bar)}>`. `fromAction(foo, bar)` is wrong because the second argument must be a function returning the argument, not the argument itself.
9.  The action body runs untracked, so it never re-runs. Fixes: read the state in a nested `$effect` inside the action; or convert it to an attachment (factory re-runs, or getter plus nested effect); or implement the legacy `update`.
10. Actions run in an effect after mount, and effects never run on the server. Therefore `window`/`document` access inside an action (or a nested effect) is safe without `typeof window` guards; code in the component’s top-level script is not.
11. None: it must be at the top level of the component. Inside a block or element it is `svelte_meta_invalid_placement`. For a conditional window listener use `$effect(() => { if (!active) return; return on(window, 'keydown', handler); })`.
12. `scrollX` and `scrollY` only. An initial value does not scroll the page (accessibility); only later changes do. To scroll at mount call `scrollTo()` in an `$effect`.
13. `activeElement`, `fullscreenElement`, `pointerLockElement`, `visibilityState`; all read-only.
14. `visibilitychange` (document) and `mouseenter`/`mouseleave` (body); `fullscreenchange` and `selectionchange` also work on document.
15. `runes`, `namespace`, `customElement`, `css="injected"`, `preserveWhitespace`, and deprecated `immutable`/`accessors`. Children give `svelte_meta_invalid_content`; an unknown attribute gives `svelte_options_unknown_attribute`.
16. Declarative `onclick` handlers are delegated and run from a root listener; the native `stopPropagation` stops the event before it reaches the root. `on()` registers the handler so ordering relative to delegated handlers is preserved and `stopPropagation` is handled correctly (declared handlers below still run).
17. `const preventScroll: Attachment<HTMLElement> = (el) => on(el, 'touchmove', (e) => e.preventDefault(), { passive: false });`. `ontouchmove` attributes are always passive, so `preventDefault()` would be ignored.
18. `undefined` (the sources are created with a server stub). Use a fallback: `const compact = $derived((innerWidth.current ?? 1024) < 640);`.
19. The constructor adds parentheses only when the string has none and is not made only of keywords, so `'(min-width: 800px)'` is used as is, `'min-width: 800px'` is wrapped, and `'screen'` (a keyword) is left unwrapped. The documented form is without outer parentheses.
20. On the server the real value is unknown, so the server output uses the fallback and the client may differ after hydration, causing a visible change. Use CSS media queries when only styling is affected.
21. Svelte transitions run through the Web Animations API, which a CSS `animation-duration`/`transition-duration` override does not affect. `prefersReducedMotion.current` lets you set `duration: 0` (or skip the transition) in script.
22. `start(update)` is called when the first tracking effect calls `subscribe()`; only once while at least one effect is active; its returned cleanup runs when the last subscribing effect is destroyed; called outside a tracking context `subscribe` does nothing.
23. When an effect re-runs, its teardown runs first and the effect then subscribes again. Counting down immediately would hit zero and restart the subscription; deferring the decrement by a microtask lets the re-run increment first, avoiding resubscribe churn and leaks.
24. The listeners are never removed and the state exists even if nothing reads it, so it leaks and runs forever (and `navigator.onLine` is read during SSR). Fix with `createSubscriber((update) => { const a = on(window, 'online', update); const b = on(window, 'offline', update); return () => { a(); b(); }; })` and a getter that calls `subscribe()` then returns `navigator.onLine`; or just use `online` from `svelte/reactivity/window`.
25. `class Visibility { #sub = createSubscriber((update) => on(document, 'visibilitychange', update)); get current() { this.#sub(); return document.visibilityState; } }`.
26. `bind:contentRect` is a template binding tied to one element in one component, simplest for local layout. The `createSubscriber` class is reusable from scripts and `$derived`s, can be shared and observes only while read, and can be constructed for any element (including ones from `bind:this` or attachments).
27. Libraries often do not tolerate state proxies (identity checks, structured cloning), so pass a plain snapshot, which also tracks deeply. Reading `getConfig()` in the outer function subscribes the whole attachment to it, so any change destroys and recreates the chart instead of updating it.
28. Attachments: they work on components through spread, are reactive, and compose. Document that wrapper components must spread `...rest` (onto the root element, last), type props with `HTMLButtonAttributes`/`HTMLInputAttributes`, and provide `fromAction` adapters for any library-provided actions. Use getter parameters where setup is expensive.

## Chapter 10: Styling

1.  The selector becomes `p.a.svelte-hash { color: red }` and the `<p>` gets `class="a svelte-hash"`. The hash class adds 0-1-0 specificity, so the rule is more specific than the source selector (here 0-2-1 instead of 0-1-1) and beats an equal global rule regardless of load order.
2.  The first compound gets the plain hash class (+0-1-0); repeats use `:where(.svelte-x)`, which has zero specificity, so scoping does not compound. Using the plain class twice would add 0-2-0 and make rules’ specificity grow with selector length, making overrides unpredictable.
3.  It cannot be disabled. Keeping the selector with the scoping class would not match what the author expects (elements it cannot see); keeping it without the class would make it a global style. The correct escape is an explicit `:global`.
4.  a\. kept (dynamic class could be anything); (b) pruned (`class="bar"` can never carry `foo`); (c) kept (spread may add any class); (d) kept; (e) pruned.
5.  `{@html}` content gets no scoping class, so the compiler sees no `<a>` inside the article and prunes the rule. Rewrites: `article :global a { }` or the block form `article :global { a { } }`. The block form is preferred (documented), since it keeps the anchor `article` scoped and groups the rules.
6.  `div :global(strong)` gives `div.svelte-x strong` (scoped div, any strong inside it); `:global(div) strong` gives `div strong.svelte-x` (any div, but only this component’s strong); `:global(div strong)` gives `div strong` entirely unscoped. The last one leaks to the whole page.
7.  `.a :global(b) .c`: `css_global_invalid_placement` (global in the middle). `:global { color: red }`: `css_global_block_invalid_declaration` (declarations in a top-level block). `:global, x { y {} }`: `css_global_block_invalid_list`.
8.  With `@keyframes -global-spin`, the prefix is stripped from the rule (`@keyframes spin`) and `animation: spin 1s` stays unscoped and matches it. With `@keyframes spin` both the rule and the reference are rewritten to the hashed name (`svelte-hash-spin`).
9.  The reference is left unchanged (`animation: fade 1s`), because the keyframes are not defined in this component. It will only work if some global `@keyframes fade` exists; otherwise nothing animates.
10. Selectors inside `:is`, `:where` and `:has` used to be treated as global; Svelte 5 analyses them in component context, so ones that relied on that (elements from children or `{@html}`) are now reported unused and pruned. Fix with `:global(...)` inside the pseudo-class.
11. c\. Only the `.zzz` alternative is pruned; `:is(.a:where(.svelte-x)) .b.svelte-x` remains.
12. It compiles to `<svelte-css-wrapper style="display: contents; --track-color: black">` around the component. Consequences: it is a real DOM node, so child combinators (`>`), `:first-child` and sibling selectors across the boundary see the wrapper rather than the component’s root; it does not affect layout because of `display: contents`.
13. The wrapper’s style is set by `$.css_props(node, () => ({...}))`, which re-runs when the expressions’ dependencies change. Inside an SVG a `<g>` is used instead.
14. Custom properties are an explicit, stable API that does not depend on the child’s internal markup and does not leak. `:global` is the only option when the child exposes no tokens (typically a third-party component), and then it should be anchored on an element you own.
15. `let { class: klass, children }: { class?: ClassValue; children?: Snippet } = $props();` then `<div class={['card', klass]} style:--accent="var(--accent, blue)">`; the parent writes `<Card --accent="red" class="mt-2" />`. The type is `ClassValue` from `svelte/elements`.
16. `class={false}` gives `false` (stringified); `[false, null]` gives no value (empty, attribute only has the scoping class); `{ a: 0, b: 1 }` gives `b`; `undefined` is omitted; `['x', 0]` gives `x`.
17. It renders red: directives win over the `style` attribute, even over `!important` declarations. `style:opacity|important={0.5}` emits `opacity: 0.5 !important`.
18. It keeps values in CSS, avoids string concatenation, and the compiler updates only the changed property (a single `set_style` with per-property entries) instead of rewriting the whole `style` attribute.
19. One top-level `<style>` (a second is `style_duplicate`). A nested `<style>` is inserted into the DOM as is, with no scoping or processing, so its rules apply to the whole document.
20. `'external'` returns the CSS separately for the bundler to emit as an asset; `'injected'` embeds it in the component (SSR `<style>` in head, client `append_styles`). Use injected for libraries without a CSS pipeline, Shadow DOM and micro-frontends; it is forced for custom elements.
21. `<svelte:options css="injected" />` overrides the compiler option for that component. Since 5.54 the option itself can be a function `({ filename }) => 'injected' | 'external'`.
22. `` cssHash: ({ hash, css, name }) => `acme-${name}-${hash(css)}` ``. It must be deterministic and include enough entropy (the content hash) to avoid collisions between components with the same name.
23. It reports whether the compiled CSS contains global rules. Tooling that tree-shakes or isolates component CSS can use it to avoid treating such files as purely scoped.
24. Put a `:global` selector in front of the `@apply` block, e.g. `main :global { @apply bg-blue-100 dark:bg-blue-900; }`, so rules generated with `:is(...)` are not scoped away.
25. The scoped component rule wins: `.card.svelte-x` is 0-2-0 against the utility’s 0-1-0. To let the utility win: place component styles in a lower `@layer` than the utilities, or write the component rule as `:where(.card)` (zero specificity) so any utility overrides it.
26. Define tokens on `:root` with a light default, override with `@media (prefers-color-scheme: dark) { :root:not([data-theme='light']) { ... } }` and `:root[data-theme='dark'] { ... }`. Without the `:not(...)` guard the dark media query would override an explicit light choice; persist the choice in JS and set the attribute early to avoid a flash.
27. The server cannot know the value, so it renders the fallback and the page can flash after hydration; CSS media queries and custom properties switch without JavaScript. Use `MediaQuery` only when script logic (such as chart colours or behaviour) genuinely depends on the preference.
28. The rule is pruned as unused (`css_unused_selector`), since the `h1` belongs to a child component. The least invasive fix is a partially global rule anchored on an element you own: `div :global(h1) { color: red }` (or `div :global { h1 { ... } }`), ideally with a comment.

## Chapter 11: Transitions, Animations and Motion

1.  It stays until the `fade` on the first `<li>` finishes (400 ms by default). When a block transitions out, every element inside it is kept in the DOM until all transitions in that block complete, including elements with no transition of their own. It is also `inert` during that time.

2.  `transition:fly` is bidirectional: the reversal starts from the current position and runs for the proportional remainder of the duration. With `in:`/`out:` the transitions are not reversible: the intro continues to play alongside the outro rather than reversing, and an aborted outro restarts from scratch.

3.  `transition_conflict`: “Cannot use `transition:` alongside existing `in:` directive”. `<div in:fly out:fade>` is allowed (one `in:` and one `out:`); only `transition:` is exclusive with them, and duplicates of the same kind give `transition_duplicate`.

4.  Only B. Transitions are local by default and the `{#if y}` block did not change; `x` changing creates the `{#if y}` block as a consequence, but A is local to the `y` block. B has `|global`, so it plays when an ancestor block changes.

5.  Because the function and parameters are evaluated when the transition starts (and cached while it runs), not when the component renders. Parameters can therefore read current state, for instance `y: prefersReducedMotion.current ? 0 : 200`, and each transition starts with fresh values.

6.  c\. Svelte calls `css(t, u)` ahead of time, about `ceil(duration / 16.67) + 1` times, applying the easing itself, and passes the resulting keyframes to `element.animate`. It is not called per frame.

7.  `backOut` overshoots, so `t` can exceed 1 near the end, yielding `opacity` above 1 (invalid or clamped inconsistently) for some frames. Clamp with `Math.min(1, t)` or use a non-overshooting easing.

8.  `css` is converted to Web Animations keyframes that the browser can run off the main thread, while `tick` runs in a requestAnimationFrame loop on the main thread. Only `tick` can animate something CSS cannot express, such as changing text content (the typewriter effect) or non-CSS state.

9.  It prints `is` immediately after the intro starts, `ie` after \~300 ms, and after the toggle-off `os` then (after \~300 ms) `oe`. Order: `is`, `ie`, `os`, `oe`. (`introstart` fires when the zero-length delay animation finishes, effectively at the start.)

10. The element’s stylesheet transform is overwritten for the duration of the animation (it jumps to unrotated, scaling), then snaps back to rotated when the animation ends. The built-ins read `getComputedStyle(node).transform` (treating `none` as empty) and prepend it to the generated transform.

11. A deferred transition returns a function instead of a config; the runtime calls that function in the next microtask. `crossfade`’s `send` and `receive` each register their node in a map under `params.key` and return the deferred function; when it runs, each looks for a counterpart under the same key in the other map, and if found animates between the two bounding rectangles, otherwise uses `fallback`.

12. The deferred function finds no counterpart, removes its own entry from the map and returns `fallback(node, params, intro)`, or `undefined` if there is no fallback (no outro runs). For `send` (an out transition) the third argument `intro` is `false`; for `receive` it is `true`.

13. a\. A keyed each block is required (`animation_missing_key`). Being the only immediate child is required, reordering is what triggers it, and parameters are allowed.

14. Neither animates. `animate:` runs only when an existing item’s position changes; additions and removals do not trigger it, and appending leaves existing items where they were (`apply()` finds identical rectangles and skips).

15. `flip` measures the first rectangle (before the DOM update) and last rectangle (after), computes the translation (and relative scale) between the transform origins, and plays from that inverted state back to the identity transform. The default duration is `Math.sqrt(distance) * 120` so that long moves are not proportionally slow and short moves are not instant.

16. `fade`: linear, 400; `fly`: cubicOut, 400; `slide`: cubicOut, 400; `blur`: cubicInOut, 400; `draw`: cubicInOut, no fixed default (800 ms if no `speed`/`duration`, else `length / speed`); `Tween`: linear, 400. `draw` is derived from path length.

17. `slide` animates `height` (or `width`), which has no effect on elements with `display` like `inline` (the default for `<span>`), `inline-block`, `inline-flex`, `inline-grid`, `contents` or table displays. Use `block`, `flex` or `grid`.

18. `current` stays `'red'` and then snaps to `'blue'` immediately (non-interpolable values snap, since 5.17). Setting a `Tween<number>` to `'x'` throws `Cannot interpolate values of different type` when the tween starts.

19. The first `await` never settles: the superseded task is removed from the scheduler without resolving its promise. For `Spring`, the earlier call’s promise is rejected with `Error('Aborted')`, so an awaiting caller must catch it.

20. ``` {.sourceCode .html}
    <script lang="ts">
        import { Tween } from 'svelte/motion';
        let { score }: { score: number } = $props();
        const shown = Tween.of(() => score, { duration: 400 });
    </script>
    <span>{Math.round(shown.current)}</span>
    ```

    `Tween.of` creates a render effect that calls `set` when the expression changes, so it needs an owning effect root, which component initialisation provides.

21. Raise `damping` (more resistance to velocity, less oscillation). Both `stiffness` and `damping` are clamped to the range 0 to 1.

22. `preserveMomentum`, in milliseconds: the spring behaves as if it had infinite mass for that long, continuing along its trajectory before the spring force takes over.

23. b\. Transitions are driven by the Web Animations API, so the CSS rule does not affect them. Use `prefersReducedMotion.current` to adapt.

24. \`\`\`ts import { prefersReducedMotion } from ‘svelte/motion’; import { fade, slide, type SlideParams, type TransitionConfig } from ‘svelte/transition’;

export function safeSlide(node: Element, params: SlideParams = {}): TransitionConfig { return prefersReducedMotion.current ? fade(node, { duration: 100 }) : slide(node, params); }

    `SlideParams` is exported from `svelte/transition`.

    25. `mount`: `intro` defaults to `true`; `hydrate`: the runtime defaults it to `false`. Use `unmount(app, { outro: true })` (since 5.13); it returns a promise that resolves after the outros finish (immediately if `outro` is not set).

    26. During the overlap the old and new spans coexist in the DOM, so inline layout puts them side by side or shifts the surrounding content. Put both in the same grid cell (`display: inline-grid` with both children in `grid-area: 1 / 1`) or give the container a fixed width.

    27. Pass a `duration` of 0 (via prop) and no delay, then assert immediately after `flushSync()`. The runtime completes transitions with neither duration nor delay synchronously (calling start and finish callbacks directly), and an outro's finish callback is what removes the DOM.

    28. The first call creates a dummy animation of length `delay` (often 0), the second the real animation. The dummy lets the runtime wait a microtask so sibling transitions all measure before styles are applied, holds the `t = 0` styles of an intro during the delay (`fill: 'forwards'`), and its `onfinish` starts the real animation.

    ## Chapter 12: Context, Stores and Shared-State Architecture

    1. `[get, set, has]`. `has` was added in 5.57 (the original 5.40 API returned only `[get, set]`).

    2. The key is a private object created per call, so there are no collisions between libraries and no key to export; and `get` is typed (`createContext<T>()`) and throws `missing_context` when the context is absent, instead of silently returning `undefined`.

    3. `lifecycle_outside_component` ("`getContext(...)` can only be used during component initialisation"). Call `getUser()` once at the top level of the `<script>` and use the result inside the handler.

    4. It throws `missing_context` ("Context was not set in the current component or any of its ancestors"). Use `has` when the provider is optional, for example `hasTheme() ? getTheme() : defaultTheme`.

    5. Child shows `2`. The reset replaces the provider's `counter` with a new proxy, but context still holds the old object that Child reads, so the link is broken. Reset by mutating: `counter.count = 0`.

    6. The context holds a copied string. Provide a getter: `setTheme({ get mode() { return mode; }, toggle })`, so consumers read the current value on each access (or provide a `$state` object/class instance and mutate its properties).

    7. It returns the entire context map visible to the current component. Call `const context = getAllContexts()` during initialisation and pass `mount(Comp, { target, props, context })`; the mounted root then sees the same providers.

    8. The first context call in a component creates its map as `new Map(nearestAncestorMap)`, a copy. A child that touches context sees the parent's entries as they were at that moment; a `setContext` in the parent is only visible to `getContext` calls that run after it, and the child can shadow entries by setting its own.

    9. ```ts
    function Wrapper(...args: Parameters<typeof Badge>) {
        setCart(new Cart());
        return Badge(...args);
    }
    const app = mount(Wrapper, { target: document.body });
    flushSync();

The keys created by `createContext` are private objects, so you cannot build the `context` map by hand; calling the setter inside a wrapper component writes to the right key.

10. b\. A module-level `$state` object is shared by all renders in the process. Context, props and instances created inside components are per render.

11. It is safe only if the state is never written during SSR (or no SSR exists) and you never need two instances (tests, stories, multiple roots). Reject it if the app might be server-rendered or if tests need isolation; use a context-scoped instance.

12. The setter runs after an `await`, so it is not at initialisation; with `experimental.async` it throws `set_context_after_init`. Call `setUser` first with a holder, for example `const state = $state({ user: null }); setUser(state); state.user = await fetchUser();`, or provide a getter or promise.

13. 1.  `subscribe(fn)` calls `fn` immediately and synchronously with the current value, and synchronously on each change; (2) it returns an unsubscribe function after which `fn` is not called; (3) an optional `set` synchronously notifies subscribers. For RxJS, `subscribe` may return an object with `.unsubscribe()`. If it does not emit synchronously, the value is `undefined` until the first emission.

14. a: compile error `store_invalid_scoped_subscription`. b: compile error `store_invalid_subscription` (“Cannot reference store value inside `<script module>`”). c: compile error `store_invalid_subscription_module` (“outside a `.svelte` file”). d: compile error `dollar_prefix_invalid` (the `$` prefix is reserved).

15. `2`. The subscriber runs once on subscription, and `set` with the same object still notifies because `safe_not_equal` treats objects as always changed.

16. The start function runs when the subscriber count goes 0 to 1 (open the socket) and its returned stop function when it goes 1 to 0 (close it). `get` subscribes, reads and unsubscribes, so for such a store it would open and close the socket on every call.

17. Yes. With `a.set(2)` the callback of `c` was observed running with the new `a` and the stale `b` (`c 2 2`) before `c 2 4`, depending on subscription order. If transient inconsistent values are harmful, prefer `$derived`, which is glitch-free, or restructure the derivation.

18. By `fn.length`: a callback declaring fewer than two parameters is auto (its return value is `set`); two or more means manual. Debounce:

```ts
const debounced = derived(a, ($a, set) => {
    const t = setTimeout(() => set($a), 300);
    return () => clearTimeout(t);
}, undefined as number | undefined);
```

19. A writable store whose subscribers are notified when the getter’s dependencies change and whose `set` calls your setter. It captures the effect context when called (so call it during component initialisation) and runs an internal effect root only while subscribed. Use `fromStore` for the reverse: reading an existing store as a reactive `.current` in runes code.

20. Stores: RxJS or other `subscribe`-based interop; resource-backed values with start/stop semantics; async streams with `derived`’s `set`/`update`. A class is clearly better for shared domain state with methods, derived fields and fine-grained property reactivity.

21. `onclick={c.increment}` passes an unbound method, so `this` is lost when invoked (use `() => c.increment()` or an arrow-function field). Also, the file must be named `.svelte.ts` for the `$state` rune to be compiled, and `Counter` must be imported in the component.

22. `SvelteMap` values are not deeply reactive, so mutating `line.qty` in place would notify no one. Replacing the entry triggers the map’s per-key signal. If the values are class instances with `$state` fields, in-place mutation of those fields is reactive.

23. On the server `SvelteMap` is the plain global `Map`, so `getOrInsert` exists only if the Node runtime implements it (Node 22 does not). Portable code uses `map.get(k) ?? (map.set(k, v), v)` or separate `get`/`set`.

24. The factory returning `{ count, doubled }` copies the current values at creation, so it is not reactive. Getters (`get count() { return count; }`) read the signal on each access, so consumers stay current. This is the “pass state into functions” rule.

25. Props if the state is local to one widget; a context-scoped class instance per widget (or one provider per widget) is the recommended default because each render gets its own instance, widgets stay independent, and nothing leaks across SSR requests. A module singleton would be shared by all widgets and all requests. Recommend scoped context with a provider per widget.

26. The stacks are only reassigned, so a deep proxy is unnecessary overhead; replacing the array also signals the change. With `$state([])` and `push`, `canUndo` would still work through proxy tracking, but `$state.raw` with replacement is cheaper and makes the changes explicit. (Mutating a `$state.raw` array would not be reactive.)

27. A cross-tab signal (via `createSubscriber`, fired by the `storage` event) and a local `#version` signal. The `storage` event is only delivered to other documents, never the one that wrote, so local writes need their own signal.

28. Calling the returned function inside a tracking context starts `start(update)` once while at least one effect is subscribed; `update()` re-runs the dependents; the cleanup runs when the last subscriber is gone. The decrement is deferred by a microtask so that an effect re-running (teardown then re-subscribe) does not drop to zero and trigger a needless unsubscribe and resubscribe, which would leak the old subscription.

29. It renders a stale frame first, can cascade or loop (`effect_update_depth_exceeded`), and does not run on the server so SSR output differs. Replacement: `const count = $derived(props.items.length);`.

30. Other modules importing the binding would receive the underlying signal object rather than the value (the compiler only transforms references within one file), so it raises `state_invalid_export`. Alternatives: export an object and mutate its properties, or export a function returning the value (or a class instance with `$state` fields).

## Chapter 13: Async Svelte — `await` in Components, Boundaries and Forks (Experimental)

1.  The top level of `<script>`, inside `$derived(...)`, and inside markup. Without `compilerOptions.experimental.async: true` the compiler throws `experimental_async`.

2.  a: `illegal_await_expression`. b: compiles. c: compiles (the restriction concerns `await` inside the binding, not next to it). d: `illegal_await_expression`. e: compiles.

3.  In `svelte.config.js` under `compilerOptions.experimental.async`, or via the Svelte plugin’s `compilerOptions` in `vite.config`. The compiled output gains `import 'svelte/internal/flags/async'` (and uses `$.async_derived` / `$.run([...])`).

4.  They throw `experimental_async_required` at runtime. A library calling them only works in apps that enabled the flag, so it silently imposes the experimental requirement on its users.

5.  Still `1 + 2 = 3` (the old value). The change to `a` is in a batch that depends on the pending `add(a, b)`, so the DOM update is held until the promise resolves at 500 ms, then `2 + 2 = 4` appears. The UI never shows the new inputs with the old sum.

6.  No: independent batches overlap, so the fast `y` update is applied while the slow one is pending. If the second update is to `x` as well, the newer value wins and the stale result is discarded on arrival.

7.  The second derived is not created until the first resolves. Warning: `await_waterfall`. Fix: `let aP = $derived(one()); let bP = $derived(two()); let a = $derived(await aP); let b = $derived(await bP);`.

8.  The `await` is hidden inside `sum`, so reads after it (`b`) are not tracked (`await_reactivity_loss`). Pass the values in: `async function sum(a, b) { return await a + b } ... $derived(await sum(a, b))`.

9.  It throws `async_derived_orphan`. An async derived must start its work proactively through an effect, and effects need an owning effect tree (a component or `$effect.root`) so Svelte knows when to destroy them.

10. Only when the boundary is first created, until all awaits inside have resolved. It does not reappear on refreshes. Use `$effect.pending()` (for example to show a spinner or dim stale content).

11. The number of pending promises in the current boundary, excluding child boundaries. In an event handler (outside an effect or derived) it throws `effect_pending_outside_reaction`.

12. b\. `await tick()` moves the in-flight batch out of the current slot, so `settled()` creates a fresh empty batch and resolves at once; the DOM still shows the old value.

13. ``` {.sourceCode .ts}
    async function onclick() {
        updating = true;
        await tick();            // give `updating` its own batch
        color = 'octarine';
        answer = 42;
        await settled();         // same run as the changes
        updating = false;
    }
    ```

14. A race between `requestAnimationFrame` and `setTimeout`, whichever fires first. It is not tied to promise completion, so it can resolve while async work is still in flight.

15. After typing `a` the eager text shows `a` immediately; the list shows nothing/pending until the `a` search resolves. On `ab`, the eager text shows `ab` at once while the list keeps showing the old results until the latest search finishes (the `a` result is discarded if superseded). Using eager for the list would display data inconsistent with its inputs, defeating synchronisation.

16. Pass `getAbortSignal()` to the async function and to `fetch`: `$derived(await search(q, getAbortSignal()))`. The signal belongs to the current run of the derived/effect and must be obtained synchronously while it is the active reaction. In an event handler it throws `get_abort_signal_outside_reaction`.

17. No. Rejections from superseded runs are treated as stale and not surfaced, so you need not catch `AbortError` in this pattern.

18. The `onclick` error is not caught by the boundary (outside rendering), so `failed`/`onerror` do not run. The same error thrown while rendering a child is handled: `onerror` is called, the content is replaced by `failed`.

19. It throws `svelte_boundary_reset_onerror`, because the boundary is still in a broken state. Fix the cause, then `await tick()` before calling `reset()`.

20. The existing content is removed. If `onerror` throws (or you rethrow), the error is handled by the parent boundary.

21. A root boundary with a `pending` splash around everything, inside it separate boundaries for the sidebar and the feed (each with its own skeleton and `failed`), and the cheap header outside them. `$effect.pending()` indicators must sit in the component whose nearest boundary is the one doing the waiting (inside that boundary’s content), because counts exclude child boundaries.

22. ``` {.sourceCode .html}
    let serverCount = $state(initial);
    let shown = $derived(serverCount);
    async function like() {
        shown += 1;
        try { await api.like(); serverCount += 1; } catch { shown = serverCount; }
    }
    ```

    Without rollback, `shown` keeps the optimistic value until `serverCount` changes, so the UI shows a count the server never accepted.

23. `fork(fn)` runs `fn` in a separate batch whose async work starts immediately but is not rendered. `commit()` applies it (reusing the work), `discard()` throws it away. Errors: `fork_timing` (created inside an effect or with pending state changes) and `fork_discarded` (committing a discarded fork).

24. A fork must not be created during effect flushing or with pending changes because it needs a clean batch boundary. Create it in an event handler (`await tick()` first if state is pending).

25. Block effects (`{#if}`, `{#each}`) run before `$effect.pre` (and `beforeUpdate`) in the same component. You would notice only if you update state inside an effect and relied on the old order, so that a block that should no longer exist is updated.

26. Context must be set during initialisation; after an `await` the component is no longer initialising. Under the flag you get `set_context_after_init`. Set context before the first `await`.

27. On the server it serialises the result under the key into the head; during hydration it returns that value instead of calling `fn`. It uses `devalue`, so `Map`, `Set`, `URL`, `BigInt` and promises work. Keys are global, so libraries prefix them to avoid conflicts.

28. Only the `pending` snippet (the rest of the content is ignored). Awaits outside such boundaries resolve and render before `await render(...)` returns.

29. Risks: breaking changes outside semver majors, and `fork` throws without the flag (library/runtime coupling). Design risk: a fork only helps if the real render uses the same promises/arguments; if inputs differ, the speculative work is wasted.

30. Mount a harness with a `<svelte:boundary>` and a loader prop; use `Promise.withResolvers()`; assert the pending/loading text, resolve, then `await vi.waitFor(() => expect(text).toContain('42'))`; for the stale case, change a prop, assert old content and pending count 1 before resolving, then assert the new content; unmount.

## Chapter 14: Server-Side Rendering and Hydration

1.  Only the `onDestroy` log. `onMount` and `$effect` never run on the server; `onDestroy` is the only lifecycle function that does.

2.  `RenderOutput = SyncRenderOutput & PromiseLike<SyncRenderOutput>`, where the sync part has `head`, `body`, deprecated `html` and `hashes`. You can read `.body` synchronously when there is no async work; with a top-level `await` in the tree, synchronous access throws `await_invalid` and you must `await render(...)`.

3.  The properties are accessors (and `render` is lazy), so they are not own enumerable keys. Destructure `{ head, body }` instead of spreading.

4.  c\. `csp.hash` together with `csp.nonce` throws `invalid_csp`.

5.  `idPrefix` must not contain `--` (it would collide with the ID format); `render` throws `invalid_id_prefix`.

6.  `$state` becomes a plain variable, `$derived` becomes a function evaluated when read, and `$effect` is dropped. The server renders once from initial state, so nothing can change afterwards and tracking would be dead weight.

7.  Effects never run on the server, so the `if (browser)` guard is redundant noise (the docs say never to wrap effect contents in it). The effect itself is fine for SSR: it is simply skipped.

8.  `<!--[-->`/`<!--]-->` bracket the component or a block (here the fragment and the `{#each}`); `<!--[0-->` marks the first `{#if}` branch having rendered. An `{:else}` branch emits `<!--[-1-->` (5.57.2); a boundary’s pending branch emits `<!--[!-->`; a failed boundary is marked with `<!--[?-->`.

9.  Hydration locates and walks nodes via these comments. Minifiers with comment removal, HTML-rewriting CDNs/proxies, and sanitisers or templating steps may remove them.

10. a\. Repaired: the text is updated to the client value. (b) Not repaired: the server `src` stays, with dev warning `hydration_attribute_changed`. (c) The structure cannot be matched, so Svelte warns `hydration_mismatch`, clears the target and mounts from scratch (recovery).

11. It recovers: clears the target and runs `mount`. `recover: false` throws `hydration_failed` instead. Use it in tests/CI/dev to catch mismatches loudly.

12. Repairing could refetch the image or reload an iframe, and comparing arbitrary HTML is expensive. Warnings: `hydration_attribute_changed`, `hydration_html_changed`. To force an update, stash the value, set it to `undefined` during initial render and restore it in an `$effect`.

13. The browser’s parser inserts a `<tbody>` (repairs the HTML), so the live DOM differs from the string Svelte expects; the walk goes wrong and a mismatch results. The compiler rejects or warns about such structures.

14. The time differs between server and client. Fix: render a placeholder (or a value passed as a prop/`hydratable`) first and update in `onMount`, or format deterministically with a fixed locale and time zone from data supplied by the server.

15. `localStorage` does not exist on the server and, if the client reads it during init, text/markup will differ. Render the server-compatible default and update in `onMount`/an effect (or use a cookie the server can read).

16. No: hydration defaults `intro` to `false`. Pass `intro: true` to play them.

17. `render` must be awaited (`await render(App)`). A boundary with `pending` renders only the pending snippet (marked with a branch comment); its contents, including their awaits and `hydratable` loaders, are skipped on the server and filled in by the client.

18. It needs per-render context to survive across `await`s. Missing support produces `async_local_storage_unavailable`.

19. On hydration the client would redo the awaited work, blocking hydration. Fix: `const user = await hydratable('user', () => getUser());` so the server’s serialised result is reused.

20. Anything `devalue`’s `uneval` can (including `Map`, `Set`, `URL`, `BigInt`, `Date`) plus Promises. Unserialisable values (class instances with methods, DOM nodes, functions) throw `hydratable_serialization_failed`.

21. The server throws `hydratable_clobbering`. Make keys unique or ensure identical values. Libraries should prefix keys with the library name.

22. The server did not emit that key, so the client falls back to running `fn` during hydration, blocking it, and warns `hydratable_missing_but_expected`.

23. Nonce for dynamically rendered responses (new per response); hash for static or cached HTML (`hashes.script` into the header). A reused nonce defeats its purpose because an attacker could replay it. Nonces are preferred because hashes will interfere with streaming SSR in the future.

24. `fragments: 'tree'` builds nodes one by one instead of using `<template>.innerHTML`; the trade-off is slower startup than the default `'html'`.

25. The whole render fails. Example: `render(App, { transformError: (e) => { console.error(e); return { message: 'An error occurred!' }; } })`. The `failed` snippet receives that returned object as `error`, it is serialised into the page and used to hydrate; `onerror` is called on hydration with the deserialised object.

26. The value returned by `transformError`, not the original `Error`. It must be JSON-stringifiable because it is serialised to the browser to hydrate the snippet.

27. 5.53 or later (docs say 5.51; the changelog’s server-boundary entry is 5.53.0).

28. A module counter is shared across requests on the server and diverges from the client counter, so IDs mismatch. Use `$props.id()` (with `idPrefix` for multiple roots).

29. State at module level is shared by all requests, so one request may leak data to the next. Remedies: create per-request instances and provide them through context; pass data through props; keep such state client-only.

30. On the server `current` is the `fallback` (default `false`), so desktop users get the mobile layout in server HTML and it changes after hydration. Use a CSS media query for layout instead (or set an appropriate fallback).

## Chapter 15: TypeScript with Svelte

1.  Native: type-only features that vanish on transpilation, e.g. type annotations, `interface`/`type`, generics, `as`, `satisfies`. Need a preprocessor: `enum`, constructor parameter properties (`constructor(private x: number)`), non-standard syntax not yet parsed. The compiler error is `typescript_invalid_feature`.

2.  Configuration: use `vitePreprocess({ script: true })` in `svelte.config.js`. Without configuration: replace the enum with a `const` object plus a union type (`as const`).

3.  Svelte decides which imports the template uses after TypeScript tooling has run. If TypeScript elided an import used only in markup (such as a component), the component would break. `verbatimModuleSyntax` leaves imports as written; type-only imports must use `import type`.

4.  d\. `experimentalDecorators` is not recommended; the docs list `target >= ES2015`, `verbatimModuleSyntax` and `isolatedModules`.

5.  The build (Vite/esbuild) only strips types and does not type-check. `svelte-check` (`sv check`) performs the checking; add it to CI.

6.  A `<script lang="ts">` in the file (even an empty one); without it the template is parsed as plain JavaScript.

7. ``` {.sourceCode .ts}
   import type { Snippet } from 'svelte';
   interface Props {
       label: string;
       disabled?: boolean;
       onselect?: (id: number) => void;
       children?: Snippet;
       value?: string;
   }
   let { label, disabled = false, onselect, children, value = $bindable('') }: Props = $props();
   ```

8.  `Cannot use 'bind:' with this property. It is declared as non-bindable inside the component. To mark a property as bindable: 'let { other = $bindable() } = $props()'`. Binding a `string` variable to a `number` prop gives an ordinary assignability error (`Type 'string' is not assignable to type 'number'`).

9. ``` {.sourceCode .html}
   <script lang="ts" generics="T">
       interface Props {
           options: T[];
           value?: T | undefined;
           label: (o: T) => string;
           onchange?: (o: T) => void;
       }
       let { options, value = $bindable(), label, onchange }: Props = $props();
   </script>
   ```

10. `item` is `{ id: string; text: string; n: number }`: the generic `Item` is inferred from `items`, and the snippet’s parameter type comes from `Snippet<[Item]>`, so no annotation is needed.

11. A snippet taking two parameters, a `string` and a `number`; the parameters are a tuple. `Snippet<string[]>` is rejected because an array type would imply a rest parameter, which is not supported (`number extends Parameters['length'] ? never`). Rendering `undefined` throws `invalid_snippet` at runtime; use `{@render children?.()}`.

12. `Props`: the props object; `Exports`: the shape of the component’s `export function/const` members (what `bind:this` returns); `Bindings`: which props are `$bindable`. `Component<{ prop: string }>` restricts a dynamic component prop to components whose required props fit `{ prop: string }`.

13. `typeof MyComponent` is the component (function/constructor) type; `MyComponent` as a type is the instance type (the exports). Use the instance type (`let r: MyComponent | undefined`) for `bind:this`.

14. Deprecated: `SvelteComponent` (use `Component`), `ComponentType` (use `Component`), `ComponentEvents` (events are callback props). `Component` and `ComponentProps` are the current types.

15. `$state()` without an initial value is typed `T | undefined`, which is not assignable to `number`. Fixes: `let count = $state<number>();` (type is `number | undefined`) or an `as` cast, `$state() as number`. The cast is better in a class field when the constructor assigns it.

16. Type it as a readonly array: `$state.raw<readonly Item[]>(...)`, so `.push` is a type error; update by reassigning.

17. It fails: `Module '"svelte"' has no exported member 'Snapshot'` (the alias is not exported, also not as `$state.Snapshot`). Let inference type the result of `$state.snapshot`, or assign it to your own plain type.

18. ``` {.sourceCode .html}
    <script lang="ts">
        import type { SvelteHTMLElements, ClassValue } from 'svelte/elements';
        interface Props extends SvelteHTMLElements['div'] { class?: ClassValue }
        let { class: klass, children, ...rest }: Props = $props();
    </script>
    <div class={klass} {...rest}>{@render children?.()}</div>
    ```

19. `HTMLAttributes` (which the button attributes extend) already declares `children` as an optional snippet, so it is inherited.

20. It makes the file a module so that `declare module 'svelte/elements'` augments (merges with) the existing declarations. Without it the file is ambient and the declaration replaces the module’s types.

21. ``` {.sourceCode .ts}
    import type { HTMLAttributes } from 'svelte/elements';
    declare module 'svelte/elements' {
        export interface SvelteHTMLElements {
            'fancy-input': HTMLAttributes<HTMLElement> & { kind?: 'text' | 'number' };
        }
        export interface HTMLAttributes<T> {
            'data-track'?: string;
        }
    }
    export {};
    ```

    (`data-*` attributes are in fact already allowed by an index signature.)

22. `const longpress: Action<HTMLElement, number, { onlongpress: (e: CustomEvent) => void }> = (node, ms) => { ...; return { update(v) { ms = v }, destroy() {} }; }`. Attachments are preferred because they are reactive (re-run when state read in them changes), compose, and need no separate parameter/`update` plumbing.

23. `Attachment<HTMLElement>` (or `Attachment` for any `Element`), i.e. `(element) => void | (() => void)`. Attaching an `Attachment<HTMLInputElement>` to a `<div>` is a type error because the element type does not match.

24. The `*.svelte` ambient module declaration types imports loosely; only the Svelte language service/`svelte-check` (via `typescript-svelte-plugin`) knows `<script module>` exports. Put shared types in a plain `types.ts` and import from there (or emit declarations with `svelte-package`).

25. Runes are only compiled in `.svelte`, `.svelte.js` and `.svelte.ts`; in plain `.ts` it fails at runtime (`rune_outside_svelte`). Rename it `cart.svelte.ts`.

26. Use `@type`/`@template` JSDoc:

```html
<script>
    /**
     * @template T
     * @type {{ items: T[], select: (item: T) => void }}
     */
    let { items, select } = $props();
</script>
```

with `checkJs` (or `// @ts-check`) enabled.

27. Destructuring `rest` out of a union loses the link between `href` and the other attributes, so narrowing on `rest.href` does not narrow `rest`. Options: cast `rest` to the specific attribute type in each branch, or split into separate `LinkButton`/`Button` components with a thin dispatcher.

28. `Component` is the function type of Svelte 5 components, while the shipped `declare module '*.svelte'` types default imports loosely as `LegacyComponentType`. Editors and `svelte-check` run the Svelte language tools, which infer each component’s real type from its source.

29. Either drop the explicit `undefined` in the parent (omit the prop), widen the type to `prop?: string | undefined`, or turn off `exactOptionalPropertyTypes`; pick one policy.

30. Examples: `noUncheckedIndexedAccess` (indexing arrays/maps may be undefined, common with each-block data), `noImplicitOverride` (class-based stores with inheritance), `erasableSyntaxOnly` (keeps `.svelte` and `.ts` under the same erasable-syntax rules and avoids needing a script preprocessor), or `exactOptionalPropertyTypes` (prop/undefined consistency).

## Chapter 16: Testing and Debugging

1.  The Svelte plugin only compiles runes in `.svelte`, `.svelte.js` and `.svelte.ts` files, and “`.svelte`” must appear in the name (for example `x.svelte.test.ts`). In a plain `.test.ts`, `$state` is an undeclared identifier and the runtime throws `rune_outside_svelte`.
2.  Under Node, `import 'svelte'` would resolve to the server entry, where `mount` is unavailable. The `browser` condition fixes this for tests, but forcing it unconditionally would also change resolution during `vite build`/dev. `process.env.VITEST` is set by Vitest, so the override applies only to test runs.
3.  a\. No: deriveds are pull-based, so reading after the write recomputes synchronously. (b) Yes: DOM updates are scheduled in a microtask, so `flushSync()` (or `await tick()`) is needed. (c) Yes: effects run after a microtask, so the pushed value appears only after a flush.
4.  It prints `0` then `1`. `mount` creates DOM but does not run effects; the effect that calls `onchange(3)` runs on `flushSync()`.
5.  The effect inside `logger` is created outside any effect root, so it throws `effect_orphan`. Wrap the body in `const cleanup = $effect.root(() => { ... }); cleanup();`, and call `flushSync()` once after creating `logger` so the initial `[0]` is recorded before the update.
6.  An effect root has no parent to destroy it, so the cleanup is the only thing that tears the effects down. If an assertion throws first, cleanup is skipped and the live effects can react to later tests that touch the same state. Use `try/finally` or `afterEach`.
7.  Examples: leftover DOM (queries find elements from earlier tests, `getByRole` finds multiple matches); live effects and event listeners from previous components keep running and may mutate shared module state; focus or `document.activeElement` carries over; timers or subscriptions keep going.
8.  Make the props object reactive: `const props = $state({ show: true }); mount(C, { target, props }); props.show = false; flushSync();`. The test file must have `.svelte` in its name so `$state` is compiled.
9.  b\. `user-event` is asynchronous and yields to the event loop, so Svelte’s microtask update has run by the time your next assertion executes. It does not bypass delegation and does not need fake timers.
10. Svelte delegates `input` (and `click`, `keydown` etc.) to a root listener, so the event must bubble. `new Event('input')` does not bubble by default; you need `{ bubbles: true }`. `HTMLElement.click()` dispatches a bubbling event.
11. Define `function Wrapper(...args) { setUserContext(value); return Component(...args); }` and pass `Wrapper` to `mount` (also works with `hydrate` and `render`). That was added in 5.49. The context applies only to that mounted tree; each `mount` call creates its own wrapper instance, so nothing leaks into other mounts.
12. 1.  A harness `.svelte` file that renders the component and declares `{#snippet footer(t)}...{/snippet}`: best for snippets with parameters, components, or reactive content. (2) `createRawSnippet(() => ({ render: () => '<em>x</em>' }))` passed in `props`: best for static single-element content in quick tests.
13. `get(store)` subscribes, reads the synchronously delivered value and unsubscribes. In hot paths this repeatedly runs start/stop notifiers and creates subscriptions. In tests it is fine.
14. The jsdom environment makes the plugin compile the component for the client, so `render()` executes client code (including `$effect`) on the server renderer and throws `effect_orphan`. Fixes: put `// @vitest-environment node` at the top of the file; or use a separate Vitest project for SSR tests with a node environment and no `browser` condition.
15. The output includes hydration marker comments (`<!--[-->...<!--]-->`) and other internals that may change between releases. Use `toContain`, a regex, or parse the HTML.
16. It flushes microtasks between timers, so promise continuations run as timers fire. `await tick()` is still needed because Svelte’s DOM update for the resolved promise is itself scheduled in a microtask.
17. jsdom has no `element.animate`, so when a transition starts the flush throws `TypeError: element.animate is not a function`. Strategies: stub `Element.prototype.animate` in a setup file; use browser mode or Playwright; or make the component testable with zero durations / `prefersReducedMotion`.
18. No. Local transitions (default) play only when their own block is toggled, not when an ancestor is destroyed; in the chapter’s run the element disappeared immediately. Add `|global` to the directive so it plays when an ancestor block changes or the component is unmounted with `outro: true`.
19. b\. `$inspect` tracks deeply, so `push` re-fires it, even though the array identity is unchanged.
20. `'init'` on the first run and `'update'` on later changes. Use it to run `debugger` or `console.trace` only on updates, or when a value crosses a threshold.
21. It must be the first statement in a function body (otherwise `inspect_trace_invalid_placement`) and cannot be used in generator functions. It reports which reactive state caused the surrounding effect or derived to re-run; `$inspect` only reports the values.
22. `{@debug user}` and `{@debug a, b}` compile, and `{@debug}` compiles. `{@debug user.name}` and `{@debug !ok}` do not (identifiers only). Bare `{@debug}` inserts a `debugger` statement triggered whenever any state in the component changes.
23. Logging shows a `Proxy`, whose target may not resemble the current value, so Svelte warns `console_log_state` in dev. Use `$inspect(...)` to log over time or `$state.snapshot(...)` for a one-off plain clone.
24. The derived assigns to `even`, which is forbidden: `state_unsafe_mutation`. Derive both: `let even = $derived(count % 2 === 0); let odd = $derived(!even);`.
25. `ownership_invalid_mutation` (“Mutating unbound props … is strongly discouraged”). Fix by passing a callback prop to change the data in the owner, or by declaring `person` as `$bindable` and using `bind:person` in the parent.
26. Any three of: HTML the browser repairs (`<div>` in `<p>`, missing `<tbody>`), client-only branching on `window`/`typeof document`, non-deterministic values (`Date.now()`, `Math.random()`), stripped hydration comments, browser extensions injecting nodes. In development a `console.error` preceding the warning shows the offending HTML, and the warning names the location.
27. The production build exercises minification, tree-shaking and the production runtime (no dev checks, `$inspect` no-op), and the HTML path your users get. Dev-only behaviour can hide or create bugs.
28. The parenthesised text is the stated reason, documenting why ignoring is justified. Globally, use the `warningFilter(warning)` compiler option (return `true` to keep the warning).

## Chapter 17: Accessibility and the A11y Warnings

1.  ARIA validity (`a11y_unknown_aria_attribute`); roles and requirements (`a11y_role_has_required_aria_props`); interactive semantics (`a11y_click_events_have_key_events`); labels, names and content (`a11y_label_has_associated_control`); keyboard and focus (`a11y_positive_tabindex`); document structure and distractions (`a11y_figcaption_parent`). Other codes in each group are equally valid answers.
2.  A `div` with a click handler triggers `a11y_click_events_have_key_events` (no keyboard equivalent) and `a11y_no_static_element_interactions` (no role). Adding `onkeydown` removes the first; the second remains until you give the element a role, which then triggers `a11y_interactive_supports_focus` until you add `tabindex`. The end state is a hand-built button, so the real fix is `<button type="button">`.
3.  It checks that an element with an interactive role and interactive handlers is focusable. Adding `tabindex` (for example `tabindex="0"`) satisfies it.
4.  b\. a\. lacks `tabindex` (`a11y_interactive_supports_focus`), (c) warns about a click on a non-interactive element, and (d) triggers `a11y_img_redundant_alt` because of “Photo of”.
5.  The element already has the implicit role `button`, so the explicit role is redundant: `a11y_no_redundant_roles`.
6.  The compiler cannot know what a spread contains, so checks that need to know whether an attribute is present (for example `alt`) are skipped. Type `props` precisely (for example with `HTMLImgAttributes` where `alt` is required) so that TypeScript enforces what the compiler cannot.
7.  `<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions (backdrop click is a pointer convenience; Escape closes via a window handler) -->` before the element. The parenthesised text records why the ignore is justified, for reviewers and future maintainers.
8.  Scope the filter to specific directories or codes that are known false positives; use `<!-- svelte-ignore ... (reason) -->` per occurrence; or use the Vite plugin’s `onwarn` to throw on chosen warnings in CI. Blanket removal of all `a11y_` codes hides real defects.
9.  `warningFilter(warning)` decides which warnings are kept: `true` keeps the warning, `false` drops it.
10. Server and client may allocate sequential IDs in different orders, which makes server HTML and client output disagree (hydration mismatch) and can break label associations. `$props.id()` returns an ID unique to the component instance and consistent between server and client. It must be called at the top level of the instance script as a variable declaration initializer (`props_id_invalid_placement` otherwise).
11. `$props.id()` is called inside a function, not at the top level as a declaration initializer, so the compiler reports `props_id_invalid_placement`. Write `const id = $props.id();` at the top level. (`label` is also untyped, but that is not the error.)
12. The input is a descendant of the `label`, which is a supported association, so no `for`/`id` pair is needed.
13. When the focused element is removed from the DOM, focus falls to `<body>` and the user loses their place. Fixes: after the state change `await tick()` and then focus the logical successor via `bind:this`; or use an attachment that focuses an element when it is mounted.
14. Inside a `<dialog>`, where focusing the first control on opening is expected behaviour (we verified `<dialog><input autofocus></dialog>` produces no warning). Elsewhere autofocus disorients screen reader users and skips content.
15. A read-only reference to `document.activeElement` that updates reactively. The element can only appear at the top level of a component (not inside blocks or elements), and all its bindings (`activeElement`, `fullscreenElement`, `pointerLockElement`, `visibilityState`) are readonly.
16. Focus trapping, inertness of the rest of the page, `Escape` to close, top-layer rendering, backdrop, and restoring focus to the previously focused element. jsdom does not implement `showModal()`, so it needs a real browser (Playwright or Vitest browser mode).
17. It sets `open = false` whenever the dialog closes by any route (Close button, `Escape`, programmatic `close()`), keeping the bindable `open` state in sync. Handling only the Close button would leave `open` stuck at `true` after `Escape`, preventing reopen.
18. Transitions use the Web Animations API, so global CSS such as `@media (prefers-reduced-motion: reduce) { * { transition-duration: 0s } }` does not affect them. Use `prefersReducedMotion.current` from `svelte/motion`, for example `transition:fly={{ y: prefersReducedMotion.current ? 0 : 200, duration: prefersReducedMotion.current ? 0 : 300 }}`.
19. A user can change the OS setting while the page is open, and `prefersReducedMotion` is reactive. Reading `.current` when the transition starts reflects the current preference; module-level evaluation would freeze it at load time (and would also be evaluated on the server).
20. The live region is created at the same time as the message, and many screen readers announce only changes to an existing region. Keep `<div role="status">` always rendered and change its text content.
21. `role="alert"` is assertive and interrupts; use it for errors, for example “Email is invalid” after submit. `role="status"` is polite; use it for non-urgent information, for example “3 results available” or “Saved”.
22. The `failed` snippet should tell the user what happened (for example in a `role="alert"` container) and offer a way forward such as a retry button calling `reset`, and focus should be handled since the original content was removed. Boundaries do not catch errors outside rendering: event handlers, `setTimeout` callbacks and other async work.
23. Shared: the selected tab name and the ID prefix (`TabsState` via `createContext`). `$props.id()` produces the unique prefix so that `aria-controls` on the tab and `aria-labelledby` on the panel reference matching IDs for this instance.
24. It implements a roving tabindex: only the selected tab is in the Tab order. Users move between tabs with arrow keys (and Home/End), implemented in the `onkeydown` handler of `Tab`, which focuses and clicks the target tab.
25. `aria-controls` and `aria-expanded`. `aria-activedescendant` lets DOM focus stay on the text input (so typing keeps working) while telling assistive technology which option is the active one, instead of moving real focus into the list.
26. The `li` is not a separate tab stop: the keyboard path (arrow keys, Enter) is handled on the input, and the click is a pointer equivalent. It would be indefensible if there were no keyboard path to choose an option or if the element were meant to receive focus itself.
27. Since 5.47 Svelte supports the browser’s customizable `<select>`: options may contain rich markup and `<selectedcontent>` mirrors the selected option inside a `<button>`. A native select still brings built-in roles, keyboard operation, form participation and platform behaviour that hand-built dropdowns must reimplement.
28. Any five of: dynamic attribute values; spread contents; component internals; focus order and focus loss; meaningfulness of names/alt text; colour contrast and target size; live region timing; heading hierarchy and landmarks; `{@html}` content; third-party components.
29. In jsdom axe can detect structural issues (missing names, invalid ARIA, duplicate IDs); layout and style rules such as colour contrast need a real browser. Playwright: `const results = await new AxeBuilder({ page }).analyze(); expect(results.violations).toEqual([]);` with `import AxeBuilder from '@axe-core/playwright'`.
30. b\. `getByRole` matches explicit and implicit roles and filters by accessible name, so success indicates the element is exposed to assistive technology correctly.

## Chapter 18: Performance and Production Readiness

1.  No virtual DOM / per-expression effects (does not make large data or slow derived computations cheap); template cloning (does not reduce the number of DOM nodes you render); event delegation (does not help events outside the delegated list, and requires bubbling); lazy fine-grained deriveds (do not stop effect chains or expensive derived work from re-running when inputs change).
2.  An unkeyed each is keyed by index (`$.index`). Inserting at the front makes every row shift position: DOM and component instances are reused by position, so each row’s content is rewritten, and internal state (input text, focus) stays at the position rather than following the item.
3.  The key expression creates a new array on each call, so two calls return different objects. In dev the runtime calls the key function twice and compares, throwing `each_key_volatile`; the check is dev-only, so production silently degrades. Use a primitive: `(todo.id)`.
4.  Two items produce the same key (message names the key and indexes). Usual cause: keys that are not unique, such as non-unique names, or using a field that duplicates across items.
5.  Reads go through a `get` trap that registers dependencies, and writes through a `set` trap; nested objects are proxied lazily. Identity: the proxy is not `===` to the original (`state_proxy_equality_mismatch`), and it cannot be cloned with `structuredClone`/`postMessage`. Use `$state.raw` for large API responses that are only replaced, and for data handed to identity-caching libraries.
6.  `let total = $derived(items.reduce((a, i) => a + i.price, 0));`. The effect version runs after the DOM update, writes state and triggers a second flush (possibly showing stale UI in between); the derived is lazy, synchronous and consistent.
7.  It logs `even` once at start, and `odd` once when `n` becomes 7. Moving 2→4→6 recomputes the derived to the same primitive `'even'`, so the equality cut-off does not notify the effect.
8.  Arrays and objects are compared by identity. `filter` returns a new array each time, so it always looks changed.
9.  Mostly false. In Svelte the update scope is already the individual expression, so splitting does not reduce re-rendering; split for reuse, readability and testability instead.
10. For local repetition inside one component: a snippet creates no component boundary and passes arguments directly. Limitation: no encapsulated state/lifecycle of its own, and it is lexically scoped (module-level export only if it does not reference instance state).
11. A spread makes the set of attributes open-ended, so the compiler cannot statically analyse them (also disables a11y attribute checks) and the runtime must re-evaluate all attributes when any prop changes. List known props explicitly and spread only the remaining rest props where pass-through is truly needed.
12. A class expression or declaration created inside a component or function is a new class object per instantiation. Declare classes at module top level (for example in a `.svelte.ts` file) and instantiate them in the component.
13. b\. `css` is converted to Web Animations keyframes that can run off the main thread; `tick` runs JavaScript each frame and should be used only when CSS cannot express the effect.
14. `injected` embeds CSS in the JS and injects it at mount (and into `<head>` on SSR): fewer requests, but larger JS and no separate caching. `external` returns CSS for the bundler to emit as files, cacheable and parallel. Custom elements always use `injected`.
15. It builds DOM nodes one by one instead of cloning parsed `<template>.innerHTML`. Enable it when a CSP with Trusted Types (`require-trusted-types-for 'script'`) forbids the `innerHTML` path, at some performance cost.
16. `svelte/internal/*` is private API shaped for compiler output and may change in patch releases. Importing it is a compile error (`import_svelte_internal_forbidden`).
17. Any three: unowned `$effect.root` never destroyed (call the returned function); global listeners/timers not removed (return cleanups, use `<svelte:window>` or `on()`); external subscriptions (use `createSubscriber`); closures over big proxies/global caches (release references); imperatively mounted components never unmounted (`unmount`).
18. Bridging external event sources to reactivity. Calling the returned function inside an effect starts `start(update)` once while at least one effect depends on it; `update()` re-runs those effects; the returned cleanup runs when all dependent effects are destroyed.
19. Use a declarative or cleaned-up listener: `<svelte:window onresize={() => (w = innerWidth)} />`, or `$effect(() => { const off = on(window, 'resize', ...); return off; })` with `on` from `svelte/events`. The original leaks one listener per component instance.
20. The `lifecycle_double_unmount` warning (“Tried to unmount a component that was not mounted”); it signals confused ownership.
21. Errors in event handlers and in `setTimeout`/async work after rendering. Use `try/catch` (or global `onerror`/`unhandledrejection` backstops) and put the failure into state that renders an error UI.
22. A function that converts a render-time error into a JSON-stringifiable value used for the `failed` snippet and hydration. Accepted by `render` (server), `mount` and `hydrate` (identity by default). It lets you log the real error and send only a redacted message to the browser.
23. When unsanitized or user-controlled HTML is injected (XSS). Escape or sanitise with an allow-list sanitiser such as DOMPurify at the point of entry; TrustedHTML is supported. Other vectors: `javascript:` URLs in `href`/`src` from user input, and user-controlled `<svelte:element this>`.
24. Module-level state exists once per server process, so every request shares it; a second visitor’s render can show the first visitor’s data (we observed `alice@example.com` in a later render). Keep per-request state in an instance created per request and share it with context.
25. b\. Compile with `fragments: 'tree'`.
26. `nonce` for dynamically rendered per-request responses (the same nonce goes into the CSP header); `hash: true` for statically generated HTML (use `hashes.script` in the policy). Setting both is an `invalid_csp` error.
27. `$state.snapshot` needs Chrome/Edge 98, Firefox 94, Safari 15.4; `bind:devicePixelContentBoxSize` is unsupported in Safari (Firefox 93+); `flip` needs Firefox 126.
28. Read the changelog for the range; pin with a lockfile and run all test layers; treat new warnings as work items; avoid internals; isolate experimental usage. Risk: experimental features (`experimental.async`, `fork`, `hydratable`) may change outside semver.

## Chapter 19: Custom Elements and Web Component Interop

1.  The compiler option `customElement: true` and `<svelte:options customElement=...>` in the component. With the options tag but without the compile flag you get `options_missing_custom_element`.
2.  Use the function form (5.54): `customElement: ({ filename }) => filename.includes('/src/elements/')`.
3.  The string form only sets the tag name. The object form has `tag`, `shadow`, `props` and `extend`.
4.  For inner components you do not want to register. Consumers call `customElements.define('name', Component.element)` using the static `element` property (available when `customElement` is `true`); it also avoids tag collisions.
5.  The inner component is created in the next tick after `connectedCallback` and destroyed in the next tick after `disconnectedCallback`. Right after `innerHTML` the shadow root is still empty (we saw 0 children), so await a tick first.
6.  Exported functions of the inner component exist only after it has mounted. Fixes: wait until the element has mounted (for example await a tick or an event), or define the method in the `extend` class so it exists from construction.
7.  `custom_element_props_identifier`: Svelte cannot infer the props to expose. Destructure all props (`let { title } = $props()`) or list them in `customElement.props`.
8.  The attribute string `"3"` is converted to the number 3. When the component sets `value = 5`, the attribute becomes `value="5"` because `reflect: true`.
9.  Via an attribute with `type: 'Array'` (JSON string), or better, a wrapper that sets the property. From Svelte: `<x-list {items}>`, which sets the property when the element has a setter.
10. Svelte interprets `oneworld={...}` on an element as `addEventListener('eworld', ...)`. It affects both: your own props starting with `on` will never be set as props, and third-party properties starting with `on` cannot be set via template attributes.
11. `"open"`: open shadow root, styles encapsulated, slots work. `"none"`: no shadow root, no encapsulation, no slots. `ShadowRootInit` object (5.49): passed to `attachShadow()` (closed mode, `delegatesFocus`, `clonable`, …).
12. Shadow DOM encapsulates styles, so global CSS (including `:global(...)`) does not apply inside. Options: expose CSS custom properties, expose `part` attributes for `::part()`, ship the styles with the element, or use `shadow: 'none'`.
13. They are inlined into the JavaScript as a string and injected into the shadow root. Custom elements always behave as `css: 'injected'`.
14. `$host().dispatchEvent(new CustomEvent('change', { detail: value, bubbles: true, composed: true }))`.
15. A rune returning the host element, valid only in custom element components and only on the client. In a normal component the compiler reports `host_invalid_placement`.
16. b\. Slotted content is created eagerly by the DOM; `let:` has no effect and slots need a shadow root.
17. An HTML attribute cannot carry a function/snippet and HTML consumers use slots. Provide named `<slot>`s for the element’s public API and use snippets only internally.
18. A function receiving the generated element class and returning a class. Good for `ElementInternals`/form association (`static formAssociated`) and for methods that must exist before the component mounts.
19. Only erasable syntax (no enums, parameter properties, namespaces); `lang="ts"` must be set on one of the scripts; `extend` is not processed by script preprocessors.
20. The class sets `formAssociated = true` and calls `attachInternals()`; the component can then call `setFormValue`/`setValidity` on the internals so the element contributes a value to the form and participates in validation and reset.
21. Each custom element is its own Svelte root, so `setContext`/`getContext` only work among regular components inside one element. Alternatives: DOM events/properties or an event-based context protocol implemented with `$host()` events.
22. The shadow DOM is invisible until JavaScript loads (no declarative shadow DOM output), so content appears after upgrade. Mitigate with `:not(:defined)` placeholder sizing, or by SSR-ing the content with another approach.
23. Augment `SvelteHTMLElements` in `declare module 'svelte/elements'` with `'x-rating': XRatingAttributes`. The file needs `export {}` to be a module so that the declaration merges instead of replacing the module.
24. The attribute is quoted, so it triggers `attribute_quoted` (will be stringified in the future). Write `items={items}` or `{items}`.
25. One bundle: one runtime copy and simple deployment, but no tree-shaking per element. Per-element entry points: consumers load only what they use, but risk runtime duplication/version skew unless `svelte` is deduplicated.
26. `customElements.define` throws for an already-registered name. Omitting `tag` and exporting the class lets consumers choose names or guard with `customElements.get`.
27. Compile with `customElement: true` in the Vitest plugin config, import the component, create the element, `await tick()`, then query `el.shadowRoot`. Use a real browser for focus delegation, `::part` and form association.
28. When you want global styles to apply and do not need slots or encapsulation. You give up style encapsulation and slot support.

## Chapter 20: Migrating from Svelte 4 (and Living with Legacy Mode)

1.  Per component. It is in runes mode if it uses any rune, if `<svelte:options runes />` is set, or if the compile option `runes: true` (or a function returning true) applies; `.svelte.js/.svelte.ts` modules are always runes. Otherwise it is legacy mode (`metadata.runes` is false).
2.  A compile error, `legacy_export_invalid` (“Cannot use `export let` in runes mode — use `$props()` instead”).
3.  It forces runes mode for every compiled file including `node_modules`, breaking legacy dependencies. Alternatives: the function form `runes: ({ filename }) => filename.includes('node_modules') ? undefined : true`, or `dynamicCompileOptions` in vite-plugin-svelte.
4.  Yes; each file is compiled in the mode it declares, so legacy library components work in runes apps. Asymmetry: snippets can be passed to a component that uses slots, but slotted content cannot be passed to a component that uses `{@render}`.
5.  Does: bump dependencies; `let` to `$state`; `on:click` to `onclick`; `<slot>` to `{@render}`; slot usage to snippets; `new Component` to `mount` (also `export let` to `$props`, `$:` to `$derived`/`run`). Does not: `createEventDispatcher`, `beforeUpdate`/`afterUpdate`, removing `svelte/legacy` helpers, and files with `$$props` plus named props or slot-name collisions.
6.  `run` runs once on the server (like `$:`) and as `$effect.pre`-like on the client. For `document.title = title` use a client `$effect(() => { document.title = title })` (effects do not run on the server, which is correct for DOM access).
7.  Converting events to callback props changes the component’s public API and the script cannot see its consumers, so automatic conversion could break them.
8.  A `beforeUpdate` present; `$$props` used together with named props; a slot name that would collide with a variable name (item to item_1).
9.  `let { value = $bindable(0) } = $props();` only if bound; otherwise `let { value = 0 } = $props();` plus `let doubled = $derived(value * 2);` and `$effect(() => { if (doubled > 10) console.log('big'); });`. The button uses `onclick`. Since `value` is mutated locally, either make it bindable or hold `let count = $state(value)`.
10. `let { onsave }: { onsave?: (p: { id: string }) => void } = $props();` call `onsave?.({ id })`; consumer `<Form onsave={(p) => handle(p)} />` (no `.detail`).
11. Child: `let { item } = $props()` and `{@render item?.(entry)}`. Consumer: `{#snippet item(entry)}...{/snippet}` inside the component tags.
12. Components are dynamic in Svelte 5: `<X />` re-renders when `X` changes. For conditional choice use a capitalised `$derived`: `const C = $derived(cond ? A : B)` then `<C />`, or dot notation like `<item.component />`.
13. `$set`: pass a `$state` props object to `mount` and mutate it. `$on`: callback props (or `events` option, discouraged). `$destroy`: `unmount(app)`.
14. The component’s exports. Effects, `onMount` and pending `#await` blocks do not run synchronously, so `flushSync()` is needed to force them.
15. A compile option that wraps components so `new Component(...)`, `$set` and `$on` keep working. Use it for components you do not control; it adds overhead per component and is deprecated.
16. When you control the call site and want the old API for a specific instantiation without changing every component’s compilation.
17. Use `render(App, { props })` from `svelte/server` instead of `App.render()`; the result is `{ body, head }` (`html` deprecated); CSS is not returned unless `css: 'injected'`, which puts `<style>` in `head`.
18. `Component<Props, Exports, Bindings>` replaces all (with `ComponentProps` for extraction). `ComponentEvents` is obsolete because events are callback props.
19. Exports from runes components cannot be bound with `bind:`. Use `bind:this={a}` and access `a.foo`.
20. Runtime error `props_invalid_value`: cannot bind `undefined` to a prop that has a `$bindable` fallback; pass a defined value.
21. Reactivity is determined at runtime, not by compile-time assignment analysis, and class instances are not proxied. Declare `$state` fields in the class (wrapping `new Foo()` in `$state` does nothing).
22. Whitespace at the start/end of a tag is trimmed, so it renders `foo- bar` instead of `foo - bar`. Move the space outside the span or use `{' '}`.
23. `:is(...)`, `:has(...)`, `:where(...)` are now analysed in component scope, so selectors relying on being treated as global become unused. Use `:global` (for example `main :global { @apply ... }`).
24. `ontouchstart`/`ontouchmove` attributes are passive. Use `on` from `svelte/events` with `{ passive: false }` (in an action or attachment).
25. Compile warning `legacy_component_creation`; runtime error `component_api_invalid_new`.
26. Codes were renamed from dashes to underscores; use `a11y_click_events_have_key_events`. Old names warn with `legacy_code` or `unknown_code`.
27. Any four of: runes by default (use the `runes` function option), remove quoted single expressions (`attribute_quoted`), falsy `class` values omit the attribute, avoid `flushSync` in effects and `setContext` after `await`, modern AST in `parse`, preprocessor `name`.
28. c\. `mount` plays transitions by default (`intro` true). It returns exports, does not run effects synchronously, and `hydrate` is the one that hydrates.
29. The bundler `browser` condition requirement from v4; Vitest needs `resolve.conditions: ['browser']`.
30. Stores remain supported and are appropriate for complex asynchronous streams, manual control over updates, and for consumers (or libraries) that rely on the store contract and `$store` syntax; you can expose both with `fromStore`/`toStore`.
