# Chapter 5: Inside the Reactivity Graph — Signals, Batches and the Flush Loop

The previous chapters described reactivity from the outside: what you write and what you observe. This chapter opens the runtime and walks through how a write becomes a DOM update. We will read the structure of sources, deriveds and effects; the flags that describe their state; how a component is “just” a branch effect; how templates and blocks become effects that own other effects; how the scheduler (`Batch`) orders work; how deriveds disconnect and reconnect; how async work keeps several batches alive; and what proxies, props objects and `$state.raw` cost.

> **Warning:** Everything here is private and version-specific. It describes `svelte@5.57.2`, read from `src/internal/client/**` in the published package. File names, function names, flag values and data structures change in minor and patch releases, `svelte/internal/*` imports are a compile error in runes components, and nothing in this chapter is API. Read it to build an accurate mental model and to debug, never to build on. Where I quote code I trim comments and unrelated branches.

## The graph at a glance

The runtime is a dependency graph with three node kinds:

- **Sources**: mutable values (`$.state`, `$.source`). Fields: `v` (value), `reactions` (who read me), `equals`, `rv` (read version), `wv` (write version), `f` (flags).
- **Deriveds**: computations that are both a reaction (they have `deps`) and a source (they have `reactions` and a cached `v`). Created by `$.derived(fn)`; initial `v` is the sentinel `UNINITIALIZED` and flags `DERIVED | DIRTY`.
- **Effects**: leaf reactions that run for their side effects, and which also form an **ownership tree** (`parent`, `first`, `last`, `next`, `prev`, `teardown`, `nodes`).

Edges are stored on both ends. A reaction has `deps: Value[]` (what it read in its last run). A value has `reactions: Reaction[] | null` (who currently depends on it). That double bookkeeping is what lets a write find its dependents and lets a re-run drop dependencies it no longer needs.

### Flags

Every node carries a bit field `f`. From `constants.js`:

| Flag | Meaning |
|------------------------------------|------------------------------------|
| `DERIVED`, `EFFECT`, `RENDER_EFFECT`, `BLOCK_EFFECT`, `BRANCH_EFFECT`, `ROOT_EFFECT`, `MANAGED_EFFECT`, `BOUNDARY_EFFECT`, `EAGER_EFFECT` | node kind (effects are further classified) |
| `USER_EFFECT` | the effect was created by `$effect`/`$effect.pre` |
| `CLEAN`, `DIRTY`, `MAYBE_DIRTY` | freshness status |
| `CONNECTED` | the reaction is attached to an effect root: it is an effect, or a derived that at least one effect depends on |
| `INERT`, `PAUSED` | subtree is paused (an outroing or hidden branch) |
| `DESTROYED`, `DESTROYING` | lifecycle |
| `REACTION_RAN`, `REACTION_IS_UPDATING` | has run once; is executing right now |
| `EFFECT_TRANSPARENT`, `EFFECT_PRESERVED`, `HEAD_EFFECT`, `ASYNC`, `ERROR_VALUE` | refinements |

Status is a tri-state: `CLEAN` (up to date), `DIRTY` (a direct dependency changed), `MAYBE_DIRTY` (a *derived* dependency was marked, and we do not know yet whether its value will actually change).

### Versions

Two counters make checks cheap:

- `write_version` is a global that increments on every write. A source’s `wv` records the write version of its last change; a reaction’s `wv` records the global write version at the end of its last run.
- `read_version` increments at the start of every reaction run. A source’s `rv` is stamped with it the first time the running reaction reads it, so repeated reads in one run are deduplicated with an integer comparison instead of a set lookup.

## A write: marking

`$.set(source, value)` (reached from `count = 5`) does the following:

1.  In dev and runes mode, if the active reaction is a derived, block effect, async derived or eager effect, throw `state_unsafe_mutation`, unless the source was created in that same reaction (`current_sources`). That is the rule you met in Chapter 4, implemented by one condition.
2.  Optionally proxify the value (for `$state` of objects).
3.  `internal_set`: if `source.equals(value)`, stop (no change). Otherwise remember the old value for teardown consistency (`old_values`, which is how a teardown sees the values from before the write, the 5.23 behaviour), get-or-create the current `Batch` (`Batch.ensure()`), record the write in it (`batch.capture`), bump `source.wv = ++write_version`, and call `mark_reactions(source, DIRTY)`.

`mark_reactions` is the push half of push-pull:

```js
for (reaction of signal.reactions) {
  if (!(reaction.f & DIRTY)) set_signal_status(reaction, status);   // DIRTY for direct readers
  if (reaction is EAGER_EFFECT)  eager_effects.add(reaction);
  else if (reaction is DERIVED)  mark_reactions(reaction, MAYBE_DIRTY);   // recurse
  else if (it was not already dirty) schedule_effect(reaction);
}
```

Direct readers become `DIRTY`; deriveds are marked `MAYBE_DIRTY` for their own readers, recursively; effects reached are *scheduled* into the batch. Nothing is recomputed. (There is a guard for pathological graphs: after 100,000 visited edges it starts tracking a `seen` set to avoid re-walking cycles.)

Also note the self-invalidation special case at the end of `internal_set`: if the write happens while an effect is running and that effect is `CLEAN` (which means it already read this source earlier in its run), the effect is rescheduled. That is how `$effect(() => count++)` re-runs itself, and why it loops.

## A read: tracking and pulling

`$.get(signal)`:

1.  If there is an active reaction and we are not in `untrack`, register the dependency. During a run (`REACTION_IS_UPDATING`) it compares `signal.rv < read_version` to skip duplicates, then either bumps `skipped_deps` (the dependency matches the same position in the previous run’s `deps`, so no allocation is needed) or pushes to `new_deps`. After an `await` (not updating), it appends directly to `deps` and `reactions` with dedup. The skipped-deps trick means a reaction that reads the same things in the same order each run allocates no arrays.
2.  If the signal is a derived, ensure it is fresh: `is_dirty(derived)` and, if so, `update_derived(derived)`. Additionally, if the derived is not `CONNECTED` and the active reaction is, connect it (see below).
3.  Return `signal.v` (or the value held by a batch, during time travel).

`is_dirty(reaction)` is the “pull” check:

```js
if (flags & DIRTY) return true;
if (flags & MAYBE_DIRTY) {
  for (dep of reaction.deps) {
    if (is_dirty(dep)) update_derived(dep);   // recompute the derived now
    if (dep.wv > reaction.wv) return true;    // it really changed
  }
  if (CONNECTED) set_signal_status(reaction, CLEAN);
}
return false;
```

So a `MAYBE_DIRTY` reaction asks each derived dependency to refresh itself, then compares write versions. `update_derived` runs the derived’s function, and **only if `!derived.equals(value)`** bumps the derived’s `wv`. That single comparison is the referential-equality cut-off from Chapter 4: an unchanged derived value leaves `dep.wv <= reaction.wv`, so the effect is never re-run.

### Running a reaction

`update_reaction(reaction)` saves the global tracking state (`new_deps`, `skipped_deps`, `active_reaction`, `untracking`, …), sets `active_reaction`, calls `fn()`, then `update_dependencies`: if new dependencies were found it removes the reaction from sources it no longer reads (`remove_reactions(reaction, skipped_deps)`), writes the new `deps` array, and adds the reaction to the `reactions` of each newly read source. Branch and root effects set `active_reaction = null`, which is why code directly inside them is untracked.

`update_effect(effect)` wraps that: set `CLEAN`, make it the `active_effect`, **destroy child effects** (unless it is a block or managed effect), run its teardown (with `is_destroying_effect` true, so reads of changed sources return old values), call `update_reaction`, store the returned function as the new teardown, and stamp `effect.wv`.

That order explains the earlier observation in Chapter 4: child effects are destroyed and the teardown runs *before* the new run, and nested `$effect`s created inside an effect are recreated on every re-run.

## Effect kinds and the ownership tree

Effects are created by `create_effect(type, fn)`, which allocates the node with `f: type | DIRTY | CONNECTED`, links it as the last child of the `active_effect`, and:

- for `EFFECT` (user effects): schedules it with the batch (or collects it if created during traversal), to be run later;
- for all others: **runs it immediately** (`update_effect`), which is why render effects and `$effect.pre` effects execute during component creation.

Some effects are then dropped from the tree: if an effect that ran immediately has no deps, no teardown, no DOM nodes, and at most one child, it is skipped and its child is linked instead (unless `EFFECT_PRESERVED`). This keeps the tree small for static content.

The kinds:

| Kind | Created by | Role |
|------------------------|------------------------|------------------------|
| `ROOT_EFFECT` | `mount`/`hydrate` (via `component_root`), `$effect.root` (`effect_root`) | top of a tree; not tracked; destroyed manually: `$effect.root` returns the destroy function, and for `mount` the runtime keeps it and calls it from `unmount` (optionally pausing for outros) |
| `BRANCH_EFFECT` | `branch(fn)`: component bodies, each item bodies, if/else branches, snippets | a group of child effects with no reactive dependencies of its own; can be paused/destroyed as a unit |
| `BLOCK_EFFECT` | `block(fn)`: `{#if}`, `{#each}`, `{#key}`, `{#await}`, `<svelte:element>`, boundaries | tracks the block’s controlling expression; owns branches; does *not* destroy children on re-run (it manages them) |
| `MANAGED_EFFECT` | `managed(fn)` | like block, but scheduled with render effects |
| `RENDER_EFFECT` | `render_effect`, `template_effect`, `$effect.pre` (with `USER_EFFECT`) | DOM updates; run during the render phase |
| `EFFECT` (+`USER_EFFECT`) | `$effect`, `effect(fn)` | after-DOM side effects |
| `EAGER_EFFECT` | `$inspect`, `$state.eager` | run synchronously on write |

### A component is a branch effect

The compiled component function begins with `$.push($$props, true)` (when it needs context or lifecycle) and ends with `$.pop()`. The runtime wraps the call in a `branch(...)` effect. Inside, the component body runs with `active_reaction = null` (so reading state in the script is untracked, which is why the script “runs once”), but `active_effect` is the branch, so everything created becomes its child:

```text
ROOT_EFFECT (mount)
└─ BRANCH_EFFECT  App
   ├─ RENDER_EFFECT  template_effect (text of {count})
   ├─ BLOCK_EFFECT   {#if show}
   │   └─ BRANCH_EFFECT  consequent
   │       └─ BRANCH_EFFECT  <Child />      <- a component, again a branch
   │           └─ ...
   └─ EFFECT         $effect(...)  (user effect)
```

There is no component object with an update method. A component “re-renders” only in the sense that some of its effects re-run. Destroying a component means destroying its branch effect, which walks the subtree running teardowns (this is how `onDestroy`, `$effect` cleanups and listener removal all happen with one mechanism). `onMount` and top-level `$effect`s in a component are deferred (`context.e`) and created when the component is mounted, so that they exist after the DOM is attached.

## Fine-grained updates: how `{count}` works

Recall the compiled counter:

```js
$.template_effect(() => $.set_text(text, `${$.get(count) ?? ''} / ${$.get(doubled) ?? ''}`));
```

`template_effect(fn)` creates a `RENDER_EFFECT`. On creation it runs once: `$.get(count)` registers the effect on `count`’s `reactions` and `$.get(doubled)` makes the derived `CONNECTED` and registers it as a reaction of `count` and the effect as a reaction of `doubled`. The resulting graph:

```text
count (source) ──reactions──▶ doubled (derived) ──reactions──▶ template effect
      └──────────reactions────────────────────────────────────▶ template effect
```

A click runs `$.update(count)`, which calls `set`. `mark_reactions` marks the template effect `DIRTY` (direct reader) and `doubled` `DIRTY`, then recurses into `doubled`, whose reaction (the same effect) is already dirty. The effect is scheduled. At flush time `update_effect` re-runs the closure; `set_text` compares the new string with the node’s cached text (`TEXT_CACHE`) and writes `nodeValue` only if different. The cost of the update is one effect run and at most one DOM write, independent of the size of the component.

The compiler groups several expressions in one element or block into one template effect when they are adjacent (we saw two text updates in one `template_effect` in Chapter 2’s test output), and moves purely static things out. Counting `$.template_effect` calls in compiled output is therefore a rough measure of how many independent reactive regions a component has.

### Blocks own branches

`{#if show}` compiles to `$.if(node, ($$render) => { if (show) $$render(consequent) })`. From `if.js`: it creates a `BranchManager` and a `block` effect whose function runs the condition callback; the callback calls `update_branch(key, fn)` with the branch key (0 for consequent, -1 for none/else). `BranchManager.ensure(key, fn)` pauses the current branch (so outro transitions can play and `INERT` is set on the subtree), creates the new branch effect with `branch(...)`, and, when outros finish, destroys the old one. Because the block effect reads the condition’s dependencies, a change schedules *the block effect* only. The branches themselves hold their own template effects with their own dependencies and are untouched.

`{#each}` is the same idea with more machinery (`each.js`): the block effect reads the collection, reconciles items by key (or index), keeping an `EachItem` record per item with its own branch effect and per-item sources for the item value and the index (made mutable only when the item is bound or reassigned, which is what the bit flags such as `16` in `$.each(node, 16, ...)` encode). Reordering moves DOM nodes; removal pauses (for transitions) then destroys the item’s branch. Keys are why an unchanged item’s effects survive. `{#key}` is simplest: a block effect over an expression that, on change, destroys and recreates its single branch.

So the update propagation rule for a structure change is: *change a controlling expression, re-run its block effect, which creates and destroys branch subtrees; everything inside the new subtrees initialises from scratch*. This is why `{#key}` is expensive: it tears down the entire subtree each time.

## The scheduler: `Batch`

All writes belong to a `Batch`. `Batch.ensure()` returns the current batch or creates one and schedules its flush on the microtask queue. The batch holds the scheduled effects (`#scheduled`), the values written (`current`, `previous`), pending async counts, commit callbacks and linkage to other batches.

`batch.flush()` (via `#process`) does, in outline:

1.  Re-schedule effects that were previously deferred.
2.  `apply()` the batch’s values.
3.  **Traversal loop**. While there are scheduled effects, for each root found by `#resolve()`, `#traverse(root, effects, render_effects)` walks the tree depth-first from `root.first`. For each node:
    - a branch/root that is `CLEAN` is skipped entirely (nothing below it can be dirty, because marking propagates to ancestors’ scheduling; this makes traversal proportional to the dirty parts);
    - `INERT` (paused) subtrees are skipped;
    - `EFFECT`s are collected into the `effects` array to run later;
    - `RENDER_EFFECT`/`MANAGED_EFFECT`s are run now if dirty (non-async mode) or collected as `render_effects` (async mode);
    - **block effects** are run during traversal if dirty (`update_effect`), which may create or destroy branches immediately.
4.  After traversal, if the batch is deferred by pending async work, stash the effects and wait; if an earlier batch shares sources, merge into it.
5.  Otherwise run the commit callbacks (DOM insertion/removal of branches), then `flush_queued_effects(render_effects)` and `flush_queued_effects(effects)` (each effect is checked with `is_dirty` first, so an effect whose dependencies turned out unchanged is skipped).
6.  If new effects were scheduled meanwhile (for example, an effect wrote state), loop.

The consequences for ordering, which my experiment on a component with `$effect.pre`, `$effect`, `{#if}` and a template expression confirmed:

- Initial run: `pre`, then the render effects (including the `{#if}` branch), then the user effect. Pre effects run at creation as render effects; user effects are deferred until after the tree exists.
- Update: `pre | template | user`. Block effects and render effects run during the traversal (parents before children, in tree order), and user effects run last, after the DOM is updated, in tree order. (In my run the `{#if}` branch disappeared on the update, so no block-body output appears.)
- Within each category the order is the order of the traversal (tree order). For render and block effects that means parents before children. A component’s own user effects are different: they are created when its initialisation finishes, after the child components it rendered, so on mount a child’s `$effect` and `onMount` run before the parent’s. The exact interleaving between sibling components’ user effects follows the order in which they were scheduled, so log or `$inspect.trace` rather than assuming when you depend on it.

### The microtask and the loop guard

I confirmed batching empirically: three writes (`a++; b++; a++`) in a row produced `runs === 0` synchronously, `1` after one microtask, and still `1` after `tick()`. The flush is queued once per batch by `queue_micro_task`.

The loop guard lives in the flush loop: `if (flush_count++ > 1000) { infinite_loop_guard(); }`, which in dev builds assembles the repeated write locations and throws `effect_update_depth_exceeded` (my run: the counter reached 1001). Because the flush is a loop *within one batch’s process*, effects that write state keep rescheduling themselves in the same flush; a finite chain of effects settles inside it. A chain `A: b = a*2` then `B: c = b+1` produced `c = 11` for `a = 5` after a single `flushSync`, with effects running in the order A, B: the write by A re-marked B, B was scheduled in the same loop.

### `flushSync`, `tick`, `settled`

- `flushSync(fn?)` sets `is_flushing_sync`, optionally flushes first and runs `fn`, then loops `flush_tasks(); if (current_batch === null) return; current_batch.flush()` until nothing is pending. It processes effects synchronously, including newly scheduled ones.
- `tick()` is `await Promise.resolve(); flushSync();`: wait one microtask then flush. (In async mode it instead races `requestAnimationFrame` with `setTimeout`, so it can resolve later; Chapter 13.)
- `settled()` is `Batch.ensure().settled()`: resolves when the batch has no pending async work and has been committed. In non-async code it behaves much like `tick`.

## Derived disconnection and garbage collection

A derived’s `reactions` array is how a write finds it. A derived that is *read but not depended on by an effect* has no reason to sit in its dependencies’ `reactions` arrays, because that would keep it (and its closure) alive as long as the sources live. Svelte therefore uses the `CONNECTED` flag:

- Reading a derived inside a `CONNECTED` reaction while the derived is not connected connects it (`derived.f |= CONNECTED` before it runs, so `update_dependencies` adds it to each dependency’s `reactions`).
- When a reaction stops depending on a derived and `derived.reactions` becomes `null` (`remove_reaction`), the derived is disconnected: the flag is cleared, its status is reset so it will be re-validated, effects created inside it are frozen (`freeze_derived_effects`, which run their teardowns), and it removes *itself* from its own dependencies (`remove_reactions(derived, 0)`), cascading up the chain.

A disconnected derived holds `deps` (strong references to its sources) but is not referenced *by* them, so it can be collected when your code drops it. When read again outside a tracking context it validates itself with the version check: my test showed that an unobserved derived, read three times with no state change, computed once, and after a write computed once more on the next read. Reading it from an effect reconnects it and unfreezes its inner effects.

This is also what `derived_inert` is about: a derived created while an effect runs records that effect as its `parent`. Once the effect is destroyed the derived is no longer connected to a live tree, so its dependencies no longer notify it. Reads often still revalidate through version checks (I could not produce a stale value in a small test), but the runtime warns because it cannot guarantee freshness. Create deriveds at component or root scope.

## Time travel, async batches and forks

Everything above assumes a single batch. With `experimental.async`, a batch can be *held open* while promises it depends on are pending. Meanwhile new writes may create *other* batches. To keep each batch’s view consistent, batches record the values they wrote (`current`) and the previous values (`previous`) and temporarily *apply* a batch’s values when it is traversed (`batch.apply()`, which sets the global `batch_values` map). While `batch_values` is non-null, `$.get` consults it first (`batch_values.get(signal)`), and deriveds cache into it instead of updating their real status. This is the “time travel”: effects in an old batch see old state; a newer batch sees the new state; and the UI shows the older, committed state until the held batch resolves. When two batches write overlapping sources, `#find_earlier_batch` finds the earlier one and the later is merged into it, so the UI never displays a mix.

`fork(fn)` (5.42, requires the async flag, otherwise `experimental_async_required`) uses the same mechanism deliberately: it ensures a batch, marks it `is_fork`, runs `fn` with `batch_values = new Map()` (so writes go into the map and not the real sources), flushes it synchronously to build the speculative DOM, and returns `{ commit, discard }`. `commit` copies the batch’s values into the real sources, bumps write versions, runs eager effects, and flushes; `discard` bumps write versions so deriveds revalidate and discards the batch. `fork()` throws `fork_timing` if called while a batch is active and `fork_discarded` on committing a discarded fork. Chapter 13 covers its use.

`$state.eager(value)` (`eager(fn)` in `batch.js`) is implemented with `eager_effect`: an `EAGER_EFFECT` that is added to `eager_effects` in `mark_reactions` and run immediately by `flush_eager_effects()` at the end of `internal_set` (unless it is a fork or deferred), with `batch_values = null` so it reads the real, latest source values rather than the batch’s held ones. It bumps a per-parent `version` source (an `eager_versions` list, flushed on a microtask via `eager_flush`) so that the consuming template effect re-runs and shows the new value. That is precisely the behaviour I observed: the eager text changed after `await tick()` while the plain one lagged.

## Proxies in the graph

`proxy.js` (Chapter 3) makes each property a source, created lazily in a `Map`. Reading `o.a` inside an effect calls `get(sources.get('a'))`, so the effect depends on that one source. Notable details:

- The array `length` source is created eagerly. `ownKeys` reads a `version` source that `deleteProperty` and property additions increment, so key-enumerating reactions depend on structure only.
- A source is created for a property on first *read*, `has` or *write*, not on proxy creation. Reading a missing property creates a source holding the sentinel `UNINITIALIZED` so that a later add triggers.
- `with_parent(fn)` creates sources *as if* inside the reaction that created the proxy (`update_version` comparison), so that a source created lazily while an unrelated effect reads the property is not attributed to that effect (this is the same logic that keeps local state from being a dependency).
- The proxy exposes the raw target through `STATE_SYMBOL`, used by `$state.snapshot`, `is()` (the equality helper behind the warning) and ownership checks.
- Mutating array methods are wrapped in dev for `$inspect` and, for `set`, updating `length` happens inside the trap so `push` is a single logical change.

## Props: `$.prop` and lazy reads

For `let { value = $bindable(''), items, label = 'x' } = $props()` the compiler emitted (5.57.2):

```js
$.push($$props, true);
let value = $.prop($$props, 'value', 15, ''),
    label = $.prop($$props, 'label', 3, 'x');
...
$.template_effect(() => {
  $.set_text(text, `${$$props.items.length ?? ''} ${label() ?? ''}`);
});
$.bind_value(input, value);
$.pop();
```

- A prop with no fallback and not bindable (`items`) does not become a variable at all: each use is `$$props.items`. The `$$props` object is built by the parent with **getters** (`get items() { return $.get(list) }`), so reading `$$props.items` inside the template effect registers a dependency on the parent’s expression. That is the mechanism behind “props are live”.
- A prop with a fallback or that is bindable goes through `$.prop(props, key, flags, fallback)`, which returns an accessor function (`label()`). The flags (`PROPS_IS_*` constants: immutable, runes, updated, bindable, lazy initial) are encoded in an integer (`15` and `3` above). The accessor reads `props[key]`, returns the fallback when the value is `undefined`, and for a bindable prop carries a setter taken from the property descriptor (the parent’s `bind:` setter). A non-bindable, non-updated prop can be assigned locally; the child’s local override is stored in an internal source until the parent value changes again, which is the “temporarily override” behaviour documented for props.
- The fallback value is evaluated lazily and is not proxied, matching the documented rule that fallback objects are not reactive.
- `$.push($$props, true)` and `$.pop()` maintain the component context that carries `ctx`, context maps, deferred effects (`context.e`), and in dev the ownership validator.

Spreading props (`<Child {...props} />`) uses `$.spread_props(...)`, a Proxy over an array of prop sources whose traps resolve a key from the last object that has it. That is why spreading is slower than named props: every read goes through a trap that iterates the list, and `ownKeys`/`has` enumerate everything. Chapter 18 returns to this.

`let { a, ...rest } = $props()` uses `$.rest_props($$props, excludes)` (seen in Chapter 2), a read-only proxy; writing to it throws `props_rest_readonly`.

## Cost model

Putting the pieces together:

**Creating state.** `$.state(v)` allocates a plain object with seven fields. A proxy adds a `Proxy`, a `Map`, a `version` source and (for arrays) a `length` source, plus a source per touched property. `$state.raw` stays at one source.

**Reading.** Outside a reaction, a source read is a function call and a property access. Inside a reaction it adds a version check and either an integer increment (same dependency order as last time) or an array push. Proxy reads add a trap, a `Map` lookup and potentially lazy proxy creation for the nested value.

**Writing.** `set` does an equality check; if changed, it increments the global write version, records into the batch, and walks `reactions` (and transitively derived reactions) marking and scheduling. Cost is proportional to the number of *reactions reachable through deriveds*, not to component size. Writing a value equal to the current one costs only the equality check. Writing to a source with no reactions is almost free apart from the batch bookkeeping.

**Flushing.** Traversal visits only non-`CLEAN` branches, so untouched subtrees cost nothing. Each dirty effect runs, re-tracks its dependencies (cheaply when stable), and writes the DOM only if values differ.

**Memory.** Each effect is a node with several pointers; each connected derived is in its sources’ `reactions` arrays. Large lists create an effect tree per item (branch plus template effects), so a 10,000-row table has tens of thousands of effects. That is the main reason for virtualisation on huge lists and for keeping row components lean. Deep proxies multiply the source count with the number of *touched* properties.

**Why `$state.raw` is cheaper.** No proxy, no per-property sources, no trap on reads. The trade-off is coarse invalidation: all readers of the value re-run on reassignment.

## Experiments for the reader

Svelte provides enough hooks to observe all of this without touching internals.

1.  **Why did this run?** Put `$inspect.trace('label')` as the first line of an effect or `$derived.by` callback. The console shows the sources that caused the re-run, with names (from `$.tag` in dev) and the stack where they were written.

2.  **Count effect runs.** Use the technique from this book’s Vitest examples:

    ```ts
    function track(fn: () => void) {
      let runs = 0;
      const destroy = $effect.root(() => {
        $effect(() => { runs++; fn(); });
      });
      flushSync();
      return { get runs() { return runs; }, destroy };
    }
    ```

    Compare `track(() => s)` with `track(() => s.value)` for a mutated proxy, or an array’s `length` with `arr[0]`.

3.  **Observe flush ordering.** Log from `$effect.pre`, a template expression with a comma operator (`{(log.push('tpl'), n)}`) and `$effect`, as in the ordering test above. Then add `{#if}` around the template expression and observe branch creation and destruction.

4.  **Count template effects.** Compile a component and count `$.template_effect(` occurrences; try merging or splitting markup and see how the compiler groups expressions.

5.  **Log the effect tree.** The runtime exposes no public tree dump, but in a dev build you can read the structure through a debugger by inspecting the component’s branch effect (the object with `first`, `next`, `parent`, `deps`). Treat that as exploration only.

6.  **Measure derived memoisation.** Add a counter to a `$derived.by` and read it from different contexts (unobserved, inside an effect, inside a template), as in the disconnection experiment above.

7.  **Provoke the loop guard.** `$effect(() => { n += 1 })` under `$effect.root` and `flushSync()`, and inspect the dev message.

## Key takeaways

- The runtime graph has sources, deriveds and effects. Edges are stored on both sides (`deps` and `reactions`). Flags encode kind and freshness (`CLEAN`, `DIRTY`, `MAYBE_DIRTY`) and attachment (`CONNECTED`); write and read versions make staleness checks and deduplication cheap.
- A write marks direct readers `DIRTY` and derived readers `MAYBE_DIRTY` recursively and schedules the effects it reaches; nothing is recomputed (push). A read of a dirty derived recomputes it, and its write version bumps only if the value changed, which gives the equality cut-off (pull).
- Effects form an ownership tree: root, branch, block, render, user, eager. A component is a branch effect whose script runs untracked; every reactive expression in its template is a render effect, and blocks (`if`, `each`, `key`) are block effects that own branch effects.
- There is no component re-render: an update re-runs the specific template, block or user effects whose dependencies changed, and DOM helpers write only when the value differs.
- `Batch` collects writes and scheduled effects and flushes once per microtask: traverse the tree (skipping clean branches), run block and render effects, commit branches, then run user effects in tree order, looping until stable. More than 1000 iterations throws `effect_update_depth_exceeded`. `flushSync` runs this synchronously; `tick` waits a microtask then flushes; `settled` waits for async work too.
- Deriveds with no dependents are disconnected so they can be garbage-collected, and reconnected on demand; deriveds created inside effects die with them (`derived_inert`).
- Async work keeps batches open and uses `batch_values` to present consistent old or new state; `fork` and `$state.eager` are built on this machinery.
- Proxies create property sources lazily plus `length` and key-version sources; props use getters, `$.prop` accessors with flags and lazy fallbacks; spreads and rest use trap-based proxies.
- Writes cost proportional to reachable reactions, reads are cheap, effect trees grow with list sizes, and `$state.raw` saves proxy and per-property overhead.
- All of this is private: use `$inspect.trace`, effect counting and logging, never internals.

## Review Questions

1.  List the three node kinds in the reactivity graph and the fields each uses to record its edges.

2.  What do `CLEAN`, `DIRTY` and `MAYBE_DIRTY` mean, and which kind of dependency makes a reaction `MAYBE_DIRTY` rather than `DIRTY`?

3.  What is the purpose of the `CONNECTED` flag, and when is a derived connected or disconnected?

4.  Describe what `$.set(count, 5)` does, step by step, up to the point where effects are scheduled. Which step throws `state_unsafe_mutation`?

5.  Why does writing an equal primitive value cost almost nothing?

6.  Explain how the referential equality cut-off for deriveds is implemented using write versions. Why is the check done in `is_dirty` and not in `mark_reactions`?

7.  What are `rv` and `skipped_deps` for, and what GC cost do they avoid?

8.  What does `update_effect` do before running the effect function, and why does that explain nested `$effect`s being recreated on each re-run?

9.  Match each to an effect kind: (a) `mount(App)`; (b) the body of a component; (c) `{#if}`; (d) `{count}` in markup; (e) `$effect(...)`; (f) `$state.eager`.

10. Why does the code directly inside a component script not create dependencies, although it reads state?

11. Draw (as an indented tree) the effects created by this component:

    ```html
    <script>
      let show = $state(true);
      let n = $state(0);
      $effect(() => console.log(n));
    </script>
    {#if show}<p>{n}</p>{/if}
    <Child />
    ```

12. After `n++`, which effects are marked, which re-run, and in which order?

13. Why is `{#key}` expensive compared with a derived value?

14. How does a keyed `{#each}` preserve effects of unchanged items when the list is reordered?

15. List the phases of a batch flush in order, and say where block effects, render effects and user effects run.

16. Predict the log:

    ```ts
    let a = $state(0);
    const log: string[] = [];
    $effect.root(() => {
      $effect(() => { log.push('A:' + a); });
    });
    flushSync();
    a = 1; log.push('after write');
    await Promise.resolve();
    log.push('after microtask');
    ```

17. What is the infinite-loop guard? After how many iterations does it fire and what does it throw?

18. A chain `$effect(() => { b = a * 2 })` and `$effect(() => { c = b + 1 })` is legal. Why does it settle, and why is it still discouraged?

19. Compare `flushSync`, `tick` and `settled`.

20. A derived is read three times outside any effect with no state change, then once after a write. How many times does its function run, and why can it still be garbage-collected when unused?

21. What happens to effects created inside a derived when the derived is disconnected?

22. Why can a derived created inside an `$effect` produce the `derived_inert` warning?

23. Explain “time travel” in async mode: what are `batch_values` and why does `$.get` consult them?

24. What does `fork(fn)` do to state writes made by `fn`, and what do `commit` and `discard` do?

25. How is `$state.eager` implemented so that it sees newer state than the rest of the UI?

26. Why are proxy property sources created lazily, and what sources does `Object.keys(proxy)` depend on?

27. In the compiled output, why is `items` (a plain prop) read as `$$props.items` while `label = 'x'` is read as `label()`?

28. Why is a spread `<Child {...props} />` slower than named props?

29. Estimate the number of effect nodes for a keyed list of 1,000 rows where each row has two text expressions and one `{#if}`. What strategies reduce it?

30. Why is it unsafe to rely on any function name or flag from `svelte/internal/client` in tooling, and what supported tools give you the same insight?
