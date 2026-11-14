# Chapter 12: Context, Stores and Shared-State Architecture

Every application eventually needs state that is not owned by a single component: the signed-in user, a shopping cart, a design-system theme, an editor document with undo history. Svelte 5 gives you three families of tools for this. **Context** hands a value to a subtree without prop drilling. **Reactive classes and `.svelte.ts` modules** let you put runes anywhere. **Stores** (`svelte/store`) are the original mechanism and remain the right tool for asynchronous streams and RxJS interop. Choosing between them, and knowing the failure modes of each, is most of what “state management in Svelte” means.

This chapter covers the mechanics (`createContext`, `setContext`, the store contract, `$store` auto-subscription, the `toStore`/`fromStore` bridges), the places where they break (SSR leakage, reassigning shared state, setting context too late), and then moves to architecture: class-based stores, factories with getters, singleton versus context-scoped instances, selectors, undo/redo, normalised collections with `SvelteMap`, persistence and cross-tab sync with `createSubscriber`, service injection, and the anti-patterns that make shared state unmaintainable. The examples were run against Svelte 5.57.2 with a small jsdom harness; where behaviour surprised me it is called out.

## Context

Context lets a component expose a value to every descendant — including descendants it never renders directly, such as content passed through a `children` snippet — without threading it through props. It is *lexical to the component tree*, not global: two sibling subtrees can hold different values for the same context.

### `createContext`

Since Svelte 5.40 the recommended API is `createContext`, which returns a triplet of functions:

```ts
createContext<T>(): [get: () => T, set: (context: T) => T, has: () => boolean]
```

The `has` function was added in 5.57; the first version returned only the pair `[get, set]`. A context module typically looks like this:

```ts
// src/lib/theme.svelte.ts
import { createContext } from 'svelte';

export interface Theme {
    readonly mode: 'light' | 'dark';
    toggle(): void;
}

export const [getTheme, setTheme, hasTheme] = createContext<Theme>();
```

```html
<!-- ThemeProvider.svelte -->
<script lang="ts">
    import { setTheme } from './theme.svelte.ts';
    import type { Snippet } from 'svelte';

    let { children }: { children: Snippet } = $props();

    let mode = $state<'light' | 'dark'>('light');

    setTheme({
        get mode() { return mode; },
        toggle() { mode = mode === 'light' ? 'dark' : 'light'; }
    });
</script>

<div data-theme={mode}>{@render children()}</div>
```

```html
<!-- ThemeButton.svelte -->
<script lang="ts">
    import { getTheme } from './theme.svelte.ts';
    const theme = getTheme();
</script>

<button onclick={theme.toggle}>{theme.mode}</button>
```

Why is this better than `setContext('theme', ...)` with a string key? The documentation says it directly: “`createContext` is preferred since it provides better type safety and makes it unnecessary to use keys.” Looking at the implementation (shared by client and server):

```js
export function create_context(get_context, set_context, has_context) {
    const key = {};                       // a fresh object per createContext() call
    return [
        () => { if (!has_context(key)) missing_context(); return get_context(key); },
        (context) => set_context(key, context),
        () => has_context(key)
    ];
}
```

Three properties follow:

1.  **The key is a private object**, unique per `createContext()` call. No collisions between libraries (a classic problem with string keys), and nothing to export except the functions.
2.  **`get` throws if the context was never set**: the `missing_context` error, “Context was not set in the current component or any of its ancestors”. With `getContext('theme')` you silently receive `undefined` and fail later, somewhere less helpful. Use `has` when the context is genuinely optional (a component that works with or without a provider).
3.  **The types flow from one declaration**: `getTheme()` returns `Theme` without a generic at the call site.

The functions returned by `createContext` follow the same lifecycle rules as `setContext`/`getContext`: they must run during component initialisation (the synchronous top-level execution of `<script>`), or in a function that is itself called from there. Calling `getTheme()` from an event handler throws `lifecycle_outside_component` (“`getContext(...)` can only be used during component initialisation”). Read it once at the top and close over the result.

> **Senior tip:** Put each context in its own tiny module named after the concept, exporting `[getX, setX, hasX]`. Components import functions, never a key, and the module is the natural place to attach a doc comment describing the provider’s contract.

### `setContext`, `getContext`, `hasContext`, `getAllContexts`

The lower-level API takes an explicit key, which can be any JavaScript value:

```ts
setContext<T>(key: any, context: T): T;
getContext<T>(key: any): T;
hasContext(key: any): boolean;
getAllContexts<T extends Map<any, any> = Map<any, any>>(): T;
```

`getAllContexts` returns the whole context map visible to the current component. Its main use is programmatic instantiation: if you call `mount` yourself from inside a component (a tooltip portal, an imperative modal), you can forward the current context into the new root so the mounted tree still sees the providers:

```html
<script lang="ts">
    import { getAllContexts, mount, unmount } from 'svelte';
    import Modal from './Modal.svelte';

    const context = getAllContexts();   // must be called during init

    export function open(text: string) {
        const modal = mount(Modal, {
            target: document.body,
            props: { text },
            context                       // forward providers to the portal
        });
        return () => unmount(modal);
    }
</script>
```

A rule documented for `setContext`: a call in the current component is only visible to `getContext` calls that run *after* it. Mechanically, each component gets its own context map lazily on the first context call, created as a copy of the nearest ancestor’s map (`new Map(parentMap)`); a child therefore sees the parent’s entries as they were when the child first touched context, and shadows them by setting its own. Overriding a context for a subtree is just calling the setter again in an intermediate component.

### Context must be set during initialisation

With the experimental async flag (Chapter 13), `setContext` and the setter returned by `createContext` enforce the rule that they must run when the component first initialises: after an `await` or in a later effect you get `set_context_after_init` (“`setContext` must be called when a component first initializes, not in a subsequent effect or after an `await` expression”). The docs note this restriction “will be active by default in Svelte 6”. Without the flag the check is not made, but the code is wrong regardless: the map you write to is not the one descendants read. Set context first, then `await`.

### Reactive context: share objects, never reassign

Context values are not reactive by themselves; context is a plain map lookup performed once. Reactivity comes from *what you put in*. The docs show the pattern: store a `$state` object in context and let descendants read and mutate its properties.

```html
<script lang="ts">
    import { setCounter } from './context.ts';

    let counter = $state({ count: 0 });
    setCounter(counter);
</script>

<button onclick={() => (counter.count += 1)}>increment</button>
```

The trap, in the docs’ words: “if you *reassign* `counter` instead of updating it, you will ‘break the link’”. After `counter = { count: 0 }` the provider’s variable points at a new proxy while every consumer still holds the old one. Reset by mutating (`counter.count = 0`). Svelte warns when it can detect the mistake (the `state_referenced_locally`-family and ownership warnings), but the rule is architectural: **the object identity placed into context must be stable for the lifetime of the provider.**

Primitives are the second trap. `setX(count)` copies the *number*. Pass a getter, or wrap in an object with a getter, exactly as in the theme example above (`get mode() { return mode; }`). That is the “passing state into functions” principle from the `$state` documentation: functions (including getters on objects) are how you pass *current values* rather than snapshots.

A class instance with `$state` fields is the cleanest way to satisfy both rules, and it is the shape I recommend for anything non-trivial; we build one below.

### Context and server rendering

Module-level state is shared by every request that the server process handles. The docs describe the hazard with a `.svelte.js` module that holds `$state` and a component that assigns into it during rendering:

```ts
// state.svelte.ts
export const myGlobalState = $state({ user: null as null | { name: string } });
```

```html
<script lang="ts">
    import { myGlobalState } from './state.svelte.ts';
    let { data } = $props();
    if (data.user) myGlobalState.user = data.user;   // runs on the server, per request
</script>
```

“…then the data may be accessible by the *next* user. Context solves this problem because it is not shared between requests.” Each `render()` call builds a fresh component tree and context map. Treat any module-level mutable value (`$state`, plain `let`, a `writable` store, a cache `Map`) as process-wide in SSR. Immutable constants are fine; per-user or per-request data must travel through props or context. Chapter 14 returns to this in the SSR pitfalls section.

This also constrains your architecture: a store *singleton* is acceptable for browser-only state (UI preferences read from `localStorage`, say) but a hazard for anything an SSR render might write. The default for shared state in an SSR-capable app should be **context-scoped instances**.

### Providing context from outside the tree: `mount`, `hydrate`, `render`

All three roots accept a `context` option (a `Map`), but because `createContext` keys are private, you cannot construct that map by hand. The supported pattern (documented since 5.49) is a **wrapper component** that calls the setters and then delegates to the real component:

```ts
import { mount, unmount, flushSync } from 'svelte';
import { setCart, Cart } from './cart.svelte.ts';
import Badge from './Badge.svelte';

function Wrapper(...args: Parameters<typeof Badge>) {
    setCart(new Cart());
    return Badge(...args);
}

const app = mount(Wrapper, { target: document.body });
flushSync();
unmount(app);
```

I ran this with Vitest-style tooling and with a bare jsdom harness: the badge renders with the provided `Cart`, and mounting `Badge` *without* the wrapper throws `missing_context`. On the server the same wrapper works with `render`:

```ts
import { render } from 'svelte/server';

function Wrapper(renderer: any, props: any) {
    setCart(cart);
    return Badge(renderer, props);
}
const { body } = render(Wrapper, {});
```

Note the signature difference: server-compiled components take a renderer as the first argument rather than an anchor; in practice you only write wrappers like this in tests and entry files, and TypeScript typing for the server form is loose. The context set by the wrapper applies to that tree only: “Each call to `mount`, `hydrate` or `render` creates a separate wrapper instance, so the context does not leak into other mounted components.” Since 5.50 `createContext` setters also work when you instantiate components programmatically in this way.

> **Note:** `render()` is lazy in 5.57: calling it does not execute the component until you access `.body`/`.head` or `await` the result. In my run, `render(Badge, {})` without a provider threw `missing_context` only when `.body` was read. Wrap the access, not just the call, in your error handling.

## Stores

A *store* is any object satisfying a three-rule contract. From the docs:

```ts
store = { subscribe: (subscription: (value: any) => void) => (() => void), set?: (value: any) => void }
```

1.  `.subscribe(fn)` must call `fn` **immediately and synchronously** with the current value, and again synchronously whenever the value changes.
2.  It returns an unsubscribe function; after calling it, `fn` must not be called again.
3.  An optional `.set(value)` makes it *writable*; it synchronously notifies active subscribers.

For RxJS interoperability `.subscribe` may instead return an object with `.unsubscribe()`. The docs add the caveat that, unless `.subscribe` calls the subscriber synchronously (which the Observable spec does not require), Svelte sees `undefined` until the first emission. This is why `BehaviorSubject` works as a store directly while a plain `Subject` shows `undefined` initially.

### Auto-subscription: the `$store` syntax

In a `.svelte` file, prefixing a store variable with `$` reads its value and subscribes for the component’s lifetime:

```html
<script lang="ts">
    import { writable } from 'svelte/store';

    const count = writable(0);
    console.log($count);   // 0
    $count = 2;            // compiles to count.set(2)
</script>

<p>{$count}</p>
```

Restrictions, all compile-time:

- The store variable must be declared at the **top level** of the component’s instance script — not inside an `if` or a function (`store_invalid_scoped_subscription`: “Cannot subscribe to stores that are not declared at the top level of the component”).
- You cannot use `$store` inside `<script module>` (`store_invalid_subscription`), nor in `.svelte.ts`/plain modules (`store_invalid_subscription_module`: “Cannot reference store value outside a `.svelte` file”). Outside components use `get(store)` or call `.subscribe` yourself.
- The `$` prefix is reserved: you cannot declare a variable or import starting with `$` (`dollar_prefix_invalid`), and a local variable `foo` plus a rune-looking `$foo` triggers the `store_rune_conflict` warning, because `$state` would otherwise silently refer to a store named `state`.
- At runtime, a value used with `$` that has no `subscribe` method throws `store_invalid_shape` (“`x` is not a store with a `subscribe` method”). Assigning with `$x = v` requires a writable store.

### `svelte/store`

```ts
writable<T>(value?: T, start?: StartStopNotifier<T>): Writable<T>
readable<T>(value?: T, start?: StartStopNotifier<T>): Readable<T>
derived<S extends Stores, T>(stores: S, fn: (values: StoresValues<S>) => T, initial_value?: T): Readable<T>
derived<S extends Stores, T>(
    stores: S,
    fn: (values: StoresValues<S>, set: (value: T) => void, update: (fn: Updater<T>) => void) => Unsubscriber | void,
    initial_value?: T
): Readable<T>
readonly<T>(store: Readable<T>): Readable<T>
get<T>(store: Readable<T>): T
```

**`writable`** — `set(v)` notifies subscribers only if `safe_not_equal(old, new)`: primitives compare by `===`, but any object or function value is *always* considered changed. I confirmed it: `store.set(store_value_same_object)` re-notified the subscriber. So `update(o => { o.n++; return o; })` works (and is the idiom for mutation) but you cannot rely on equality to suppress redundant object updates.

**Start/stop notifier.** The second argument is called when the subscriber count goes from 0 to 1, receives `set` and `update`, and may return a stop function called when it goes back to 0. This is the primitive that makes stores good at *resource-backed* values: sockets, timers, geolocation watches are opened only while someone is listening.

```ts
import { readable } from 'svelte/store';

export const now = readable(new Date(), (set) => {
    const id = setInterval(() => set(new Date()), 1000);
    return () => clearInterval(id);
});
```

Note: `set` calls made while no one is subscribed (`stop` is null) update the stored value but notify nobody, and the value is retained until the next subscription (it is not reset).

**`derived`** has a synchronous form (`fn` returns the value) and an asynchronous form (`fn` receives `set`, optionally `update`, and may return a cleanup). Whether it is “auto” is decided by `fn.length < 2`: a callback declaring a second parameter is treated as manual. A falsy store argument throws `derived() expects stores as input, got a falsy value`. The callback runs when the first subscriber arrives and re-runs on dependency changes, calling the cleanup first. The initial value (third argument) is what subscribers see before the first `set` in async mode.

> **Warning:** Store `derived` is not glitch-free in the way `$derived` is. In a diamond (`b = derived(a, ...)`, `c = derived([a, b], ...)`), my run with `a.set(2)` logged the calls `c 1 2`, then `c 2 2`, then `c 2 4`: the callback saw the new `a` with the stale `b` before settling. Subscribers received `3`, `4`, `6`. Whether intermediate values appear depends on subscription order. If intermediate states would be wrong (a request fired for each), derive from the fewest possible stores or move to runes.

**`readonly(store)`** returns an object exposing only `subscribe` — a type-level *and* runtime restriction, useful for exporting a read-only view of an internal writable.

**`get(store)`** subscribes, reads and unsubscribes. The docs warn it is not for hot paths: for a `readable` with a start function it will start and stop the underlying resource each call.

### The bridges: `toStore` and `fromStore`

When a rune-based API meets a store-based one:

```ts
toStore<V>(get: () => V, set: (v: V) => void): Writable<V>;
toStore<V>(get: () => V): Readable<V>;
fromStore<V>(store: Writable<V>): { current: V };
fromStore<V>(store: Readable<V>): { readonly current: V };
```

`toStore(() => state.value, (v) => (state.value = v))` produces a store whose subscribers are notified when the getter’s dependencies change. It captures the effect context at the time it is called (so call it during component initialisation) and runs a render effect inside an effect root only while it has subscribers. `fromStore(store)` goes the other way: `.current` reads the store, and — when read inside an effect or template — subscribes through `createSubscriber`, so reading `fromStore(store).current` in `$derived` is reactive. When read *outside* a tracking context it falls back to `get(store)`. For writable stores, assigning to `.current` calls `store.set`. These bridges are how you adopt runes in a component while a library or legacy module still exports stores:

```html
<script lang="ts">
    import { fromStore } from 'svelte/store';
    import { page } from './legacy-stores.ts';        // a Readable<Page>

    const current = fromStore(page);
    const title = $derived(current.current.title);
</script>
```

### Stores vs. runes: when each wins

The documentation’s position: “Prior to Svelte 5, stores were the go-to solution … With runes, these use cases have greatly diminished.” For extracting logic and sharing state use runes, which work in `.svelte.ts` files and inside classes. Stores “are still a good solution when you have complex asynchronous data streams or it’s important to have more manual control over updating values or listening to changes.”

| Need | Prefer |
|------------------------------------|------------------------------------|
| Local reactive value, derived values | `$state`, `$derived` |
| Shared state with methods | class with `$state` fields |
| Value tied to a resource that should open/close with subscribers | `readable`/`writable` with a start function, or `createSubscriber` |
| Interop with RxJS or any `subscribe`-based library | stores (`$observable` works if it follows the contract) |
| Event streams, multi-value emission with `set`/`update` inside `derived` | stores |
| Reading store values outside components | `get`, or `fromStore` inside reactive code |
| Value must survive SSR safely | context-scoped instance, store or class |
| Fine-grained reactivity over large objects | `$state` proxies (stores notify at whole-value granularity) |

Granularity is the quiet differentiator. A store notifies every subscriber whenever *any part* of its object changes (and subscribers re-run their consumers); `$state` proxies notify only readers of the property that changed. For store-heavy codebases that is the main performance argument for migrating.

## Shared state with runes: patterns

### Class-based stores

A class with `$state` fields and `$derived` properties is the idiomatic replacement for a custom store. The compiler turns each field into getter/setter pairs backed by private signals (so the properties are not enumerable) and `$derived` fields into lazily computed getters.

```ts
// src/lib/cart.svelte.ts
import { createContext } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';

export interface Line { sku: string; price: number; qty: number }

export class Cart {
    lines = new SvelteMap<string, Line>();

    total = $derived.by(() => {
        let sum = 0;
        for (const line of this.lines.values()) sum += line.price * line.qty;
        return sum;
    });
    count = $derived(this.lines.size);

    add(sku: string, price: number) {
        const line = this.lines.get(sku) ?? { sku, price, qty: 0 };
        this.lines.set(sku, { ...line, qty: line.qty + 1 });
    }

    clear() {
        this.lines.clear();
    }
}

export const [getCart, setCart, hasCart] = createContext<Cart>();
```

Provide in a layout and consume anywhere beneath (a `Badge` rendering `{cart.count}:{cart.total}` showed `0:0`, then `2:25` after adding two of one item priced 10 and one of another priced 5):

```html
<!-- CartProvider.svelte -->
<script lang="ts">
    import { Cart, setCart } from './cart.svelte.ts';
    import type { Snippet } from 'svelte';
    let { children }: { children: Snippet } = $props();
    setCart(new Cart());
</script>

{@render children()}
```

Points to internalise:

- **Methods lose `this` when detached.** `onclick={cart.clear}` passes an unbound method. Use an arrow function field (`clear = () => this.lines.clear();`), or call it inline (`onclick={() => cart.clear()}`). This is a general JavaScript hazard that the `$state` docs call out for classes.
- `SvelteMap` replaces a `Map` you would otherwise wrap in `$state` (a `$state` Map is *not* proxied). Its values are not made deeply reactive, which is why `add` replaces the entry with a new object rather than mutating `line.qty`: a consumer reading `line.qty` would never be notified of an in-place mutation of a plain object stored in a `SvelteMap`. Svelte 5.57 also adds `getOrInsert` and `getOrInsertComputed` to `SvelteMap`, but on the server `SvelteMap` is simply the global `Map` (`export const SvelteMap = globalThis.Map` in the server entry), so those methods exist at render time only if your Node version implements them. In my Node 22 run, calling `getOrInsert` during SSR threw `this.lines.getOrInsert is not a function`. Code that must run in both places should use `get(...) ?? set(...)`.
- Derived fields declared with `$derived` in a class are recomputed when read after a dependency changed; reading them outside an effect is allowed and always gives current values.

### Factory functions with getters

If you dislike classes, a closure returning an object with getters has the same reactive properties. The getters are what keep the link live:

```ts
// src/lib/counter.svelte.ts
export function createCounter(initial = 0) {
    let count = $state(initial);
    const doubled = $derived(count * 2);

    return {
        get count() { return count; },
        get doubled() { return doubled; },
        increment() { count += 1; },
        reset() { count = initial; }
    };
}
```

Returning `{ count, doubled }` would capture two numbers and kill reactivity; this is the same “pass by value” lesson. Factories shine for composition (a `createX` that calls other `createY` and wires them) and when you want true privacy without `#`; classes shine for `instanceof`, inheritance of behaviour, and tooling. The compiler offers a perf hint, `perf_avoid_inline_class` / `perf_avoid_nested_class`, against declaring classes inside functions: keep classes at module top level.

### Module singletons vs. context-scoped instances

Both use the same class; they differ in lifetime.

```ts
// singleton: one per JS realm (per browser tab, but ALSO per server process)
export const prefs = new Preferences();

// scoped: one per provider (per render, per test, per subtree)
export const [getPrefs, setPrefs] = createContext<Preferences>();
```

Use a **singleton** only when all of the following hold: the state is purely client-side, it is not written during SSR, and you will never want two instances (tests, Storybook stories and multi-root pages all want two). Otherwise use a **scoped instance**: tests construct a fresh one per test; SSR gets one per request; two independent widgets on a page do not interfere. A pragmatic compromise is to write the class once and offer both:

```ts
export const [getPrefs, setPrefs, hasPrefs] = createContext<Preferences>();

// fallback for non-SSR contexts
export function usePrefs(): Preferences {
    return hasPrefs() ? getPrefs() : fallbackPrefs;
}
```

Beware of the SSR leak with the fallback; it is only safe if `fallbackPrefs` is never mutated on the server.

### Derived selectors

Components that need “the items matching X” should receive them from a derived selector on the shared state rather than filtering in each component, but they should not each re-derive large collections. Expose derived views as class fields, and parametrised selectors as methods returning a `$derived` created by the *consumer*:

```ts
export class Tasks {
    all = $state<Task[]>([]);
    open = $derived(this.all.filter((t) => !t.done));
    byId = $derived(new Map(this.all.map((t) => [t.id, t] as const)));
}
```

```html
<script lang="ts">
    import { getTasks } from './tasks.svelte.ts';
    let { id }: { id: string } = $props();
    const tasks = getTasks();
    const task = $derived(tasks.byId.get(id));     // cheap lookup, recomputed only when `all` or `id` changes
</script>
```

The `byId` map is built once per change of `all`; each consumer’s `$derived` is a constant-time lookup. Deriveds are memoised and skip downstream updates when the new value is referentially equal, so selectors compose well.

### Undo/redo and the command pattern

Shared document state with history is a good stress test. Store *commands* (do/undo pairs), not snapshots, and keep the stacks in `$state.raw`, since they are only ever reassigned and need no deep proxy:

```ts
// src/lib/history.svelte.ts
export interface Command {
    label: string;
    do(): void;
    undo(): void;
}

export class History {
    #undo = $state.raw<Command[]>([]);
    #redo = $state.raw<Command[]>([]);

    canUndo = $derived(this.#undo.length > 0);
    canRedo = $derived(this.#redo.length > 0);
    nextUndoLabel = $derived(this.#undo.at(-1)?.label);

    execute(cmd: Command) {
        cmd.do();
        this.#undo = [...this.#undo, cmd];
        this.#redo = [];
    }
    undo() {
        const cmd = this.#undo.at(-1);
        if (!cmd) return;
        cmd.undo();
        this.#undo = this.#undo.slice(0, -1);
        this.#redo = [...this.#redo, cmd];
    }
    redo() {
        const cmd = this.#redo.at(-1);
        if (!cmd) return;
        cmd.do();
        this.#redo = this.#redo.slice(0, -1);
        this.#undo = [...this.#undo, cmd];
    }
}

export class Doc {
    title = $state('untitled');
    history = new History();

    rename(next: string) {
        const prev = this.title;
        this.history.execute({
            label: `rename to ${next}`,
            do: () => (this.title = next),
            undo: () => (this.title = prev)
        });
    }
}
```

Running two renames, then `undo` three times (the extra is a no-op), then `redo`, then a new rename gave: title `b` with `canUndo` true; `a` after one undo; `untitled` with `canUndo` false; `a` after redo; and `canRedo === false` after a fresh command cleared the redo stack. Two design notes: commands capture the *previous* value at creation time (`prev`), so replaying them is deterministic; and commands that mutate `$state` objects mutate them through the same proxies the UI reads, so undo needs no special “notify” step.

Snapshot-based history (store `$state.snapshot(doc)` copies) is simpler but O(size) memory per step; use it for small documents or combine with structural sharing.

### Normalised collections with `SvelteMap`

Nested object graphs (`orders[].customer.address`) make updates and subscriptions expensive and error-prone. Normalise: keep entities by id in `SvelteMap`s and reference other entities by id.

```ts
export class Store {
    customers = new SvelteMap<string, Customer>();
    orders = new SvelteMap<string, Order>();          // order.customerId: string

    customerOf(order: Order) {
        return this.customers.get(order.customerId);
    }
    ordersFor = (customerId: string) =>
        [...this.orders.values()].filter((o) => o.customerId === customerId);
}
```

`SvelteMap` tracks per-key reads: a component reading `customers.get('c1')` re-runs only when that key changes (or when it is added/removed), not when `c2` changes; iteration (`values()`, `size`) tracks the collection. This gives you database-like update granularity without proxies on every entity. Remember that values are not deeply reactive; replace entities immutably (`set(id, { ...old, name })`), or store class instances whose own fields are `$state`.

## Persistence and cross-tab sync

Shared state that should survive reloads needs a persistence layer, and `localStorage` is an *external* system whose changes Svelte cannot observe. The docs’ guidance for this exact situation: “If you need to observe something external to Svelte, use `createSubscriber`.” Its contract: calling the returned `subscribe()` inside a tracking context (an effect or template) starts your `start(update)` function once while at least one effect is subscribed; calling `update()` re-runs those effects; the cleanup you return from `start` runs when the last subscriber goes away (the implementation delays the decrement by a microtask to avoid resubscribing churn).

```ts
// src/lib/persisted.svelte.ts
import { createSubscriber } from 'svelte/reactivity';
import { on } from 'svelte/events';

export class PersistedState<T> {
    #key: string;
    #fallback: T;
    #subscribe: () => void;
    #version = $state(0);            // bumps on local writes

    constructor(key: string, fallback: T) {
        this.#key = key;
        this.#fallback = fallback;
        this.#subscribe = createSubscriber((update) =>
            // `storage` fires only in OTHER documents sharing the origin
            on(window, 'storage', (e) => {
                if (e.key === this.#key || e.key === null) update();
            })
        );
    }

    get current(): T {
        this.#subscribe();           // register interest (cross-tab changes)
        this.#version;               // register interest (local writes)
        try {
            const raw = localStorage.getItem(this.#key);
            return raw === null ? this.#fallback : (JSON.parse(raw) as T);
        } catch {
            return this.#fallback;
        }
    }

    set current(value: T) {
        try { localStorage.setItem(this.#key, JSON.stringify(value)); } catch { /* quota, private mode */ }
        this.#version++;
    }
}
```

In a jsdom test: initial read `light`; after `theme.current = 'dark'` the DOM showed `dark` and the storage value was `"dark"`; after writing `"light"` directly into storage and dispatching a `StorageEvent`, the DOM returned to `light`. Notes:

- `on` from `svelte/events` is used instead of `addEventListener` so ordering relative to Svelte’s delegated handlers is preserved; it returns the remover that `createSubscriber` expects as its cleanup.
- The `storage` event never fires in the tab that made the change, hence the local `#version` signal. This is the usual pattern: a local signal for writes and a subscriber for external ones.
- Every read parses JSON. Cache the parsed value in a `$state.raw` field if reads are hot, and update it from both paths.
- On the server `createSubscriber` is a no-op and `localStorage` does not exist; the `try/catch` returns the fallback, which matches what the client renders on first paint only if the stored value equals the fallback. For SSR-visible state (a theme) that is a hydration-mismatch hazard; store such preferences in a cookie that the server can read, or apply them with a blocking script before hydration.
- For a `$state`-with-side-effect alternative, `$effect(() => localStorage.setItem(...))` inside a class constructor works for *writing* but belongs to an owning component or `$effect.root`; the subscriber approach needs no owner and does not run on the server at all.

## Dependency injection and layering

Context is Svelte’s dependency-injection mechanism. Use it for **services**, not only for state: an API client, a logger, a router abstraction, a feature-flag reader.

```ts
// src/lib/services.ts
import { createContext } from 'svelte';

export interface Api {
    getUser(id: string, signal?: AbortSignal): Promise<{ id: string; name: string }>;
}
export interface Services { api: Api; now(): Date }

export const [getServices, setServices] = createContext<Services>();
```

```html
<!-- Root.svelte -->
<script lang="ts">
    import { setServices } from '$lib/services.ts';
    import { httpApi } from '$lib/http-api.ts';
    import type { Snippet } from 'svelte';
    let { children }: { children: Snippet } = $props();
    setServices({ api: httpApi, now: () => new Date() });
</script>
{@render children()}
```

Tests mount the component with a wrapper that provides fakes (the pattern from the previous section), without module mocking.

A layering that scales:

1.  **Domain modules** (`*.svelte.ts` or plain `.ts`): classes and functions with no DOM, no components. They use runes for reactivity, but only for state that the UI observes. They receive their collaborators (`api`, `clock`) through constructors, never by importing singletons.
2.  **Feature composition**: a provider component builds the domain object, wires it to services from context, and calls `setX`.
3.  **UI components**: read from context, render, dispatch intent by calling methods (`cart.add(...)`). They hold only view state (open/closed, hover).

```ts
export class UserDirectory {
    #api: Api;
    users = new SvelteMap<string, { id: string; name: string }>();
    loading = $state(false);

    constructor(api: Api) { this.#api = api; }

    async load(id: string, signal?: AbortSignal) {
        this.loading = true;
        try {
            const user = await this.#api.getUser(id, signal);
            this.users.set(user.id, user);
        } finally {
            this.loading = false;
        }
    }
}
```

This class is unit-testable in plain Vitest with a fake `Api`, with no component in sight. Remember the file extension rule: a module using runes must be named `.svelte.ts`/`.svelte.js`; plain `.ts` modules cannot contain `$state`.

`getContext` can also be used inside `$derived` (since 5.1) and in any function called during initialisation, so helper functions like `useUserDirectory()` that call `getServices()` internally are legitimate “composables” as long as callers invoke them at the top level of a component’s script.

## Anti-patterns

**Effect-based synchronisation.** The most common state bug in Svelte 5 code is copying state into other state with `$effect`:

```ts
// don't
let doubled = $state(0);
$effect(() => { doubled = count * 2; });

// do
const doubled = $derived(count * 2);
```

The effect version renders a stale frame first, can cascade (effect updates state, which triggers other effects, up to `effect_update_depth_exceeded`), and does not run on the server, so SSR output disagrees with the client. The documentation’s “when not to use `$effect`” list is explicit: use `$derived`, function bindings, event handlers, `{@attach}`, or `createSubscriber`. Synchronising two *independent* sources of truth is the only legitimate use, and even then prefer one writable `$derived` (writable since 5.25) or a function binding.

**God stores.** A single `appState` object with forty fields invites every component to depend on everything and makes tests assemble the world. Split by *reason to change* (session, cart, UI chrome, editor document), each with its own context. Cross-cutting derived values live in a composition layer that depends on both.

**Prop drilling versus context abuse.** Passing a prop through one or two layers is cheaper to read than context; context hides data flow. Use context when (a) the value is consumed at many depths, (b) intermediate components are generic and should not know about it (they render `children`), or (c) it is a service. Do not use context to avoid designing a component’s props: a `Button` that reaches into a global form context to know it is disabled is a component whose behaviour cannot be understood from its signature.

**Reassigning shared state.** `store = newObject` in a provider breaks every consumer. Mutate, or replace through a holder object (`holder.value = next`).

**Exporting reassigned module state.** The compiler rejects `export let count = $state(0)` that is reassigned (`state_invalid_export`) and exported deriveds (`derived_invalid_export`) because other modules would see the underlying signal object. Export an object you mutate, a class instance, or accessor functions.

**Setting context late.** Anything after an `await` in a component script, or in an effect or event handler, is too late.

**Module-level mutable state on the server.** Covered above; the default should be “per-request unless proven client-only”.

**Subscribing manually and forgetting to unsubscribe.** `store.subscribe(...)` outside a component returns an unsubscribe function that nobody calls. Inside components prefer `$store`; in modules prefer `fromStore` inside reactive code or scope the subscription with an effect root and dispose it.

## Key takeaways

- `createContext<T>()` returns `[get, set, has]` (`has` since 5.57; the API since 5.40). Keys are private objects, `get` throws `missing_context` if unset, and all three must be called during component initialisation. `setContext`/`getContext`/`hasContext`/`getAllContexts` remain for explicit keys and for forwarding context into imperatively mounted roots.
- Context values are not reactive; put a stable `$state` object (or a class with `$state` fields) in context and mutate it. Reassigning breaks the link; primitives need getters. With the async flag, setting context after `await` throws `set_context_after_init`.
- Module-level state is process-wide on the server and can leak between requests. Scope shared state with context, and provide it to `mount`/`hydrate`/`render` through a wrapper component that calls the setters.
- A store is any `{ subscribe, set? }` object whose `subscribe` calls back synchronously and returns an unsubscriber. `$store` works only at the top level of `.svelte` files; `store_invalid_*` errors and `dollar_prefix_invalid` guard the rest. `writable` always notifies for object values; store `derived` can glitch in diamonds.
- `toStore` and `fromStore` bridge runes and stores; `fromStore` uses `createSubscriber` and falls back to `get` outside tracking contexts.
- Prefer classes with `$state`/`$derived` fields, or factories returning getters, for shared state. Keep methods bound, keep classes at module scope, use `$state.raw` for reassigned collections, and `SvelteMap` for keyed entities whose values you replace immutably.
- `SvelteMap` is just `Map` on the server in 5.57; `getOrInsert` needs runtime support there.
- Use `createSubscriber` plus a local version signal to persist to `localStorage` and sync across tabs; keep SSR-visible preferences in cookies.
- Treat context as dependency injection: services in context, domain logic in `.svelte.ts` classes with injected collaborators, UI as thin consumers. Avoid effect-based synchronisation, god stores and context as a substitute for props.

## Review Questions

1.  What are the three functions returned by `createContext`, in order, and which of them was added in Svelte 5.57?

2.  Why is `createContext` preferred over `setContext('user', ...)` with a string key? Give two concrete benefits.

3.  A component calls `getUser()` (from `createContext`) inside an `onclick` handler and gets an error. Which error, and how do you fix the component?

4.  What does `get` from `createContext` do when no ancestor called `set`? When would you use `has` instead?

5.  Predict the output:

    ```html
    <!-- Parent.svelte -->
    <script lang="ts">
     import { setCounter } from './ctx.ts';
     let counter = $state({ count: 0 });
     setCounter(counter);
    </script>
    <button onclick={() => (counter = { count: 0 })}>reset</button>
    <button onclick={() => counter.count++}>inc</button>
    <Child />
    ```

    (Child renders `getCounter().count`.) After clicking inc twice, then reset, what does Child show, and why?

6.  Fix the bug: a provider calls `setTheme({ mode, toggle })` where `mode` is a `$state` string declared in the provider. Consumers never update when `mode` changes.

7.  What is `getAllContexts` for? Show how you would use it to make a component imperatively mounted via `mount` see the same providers as its caller.

8.  Explain how the client implementation derives a component’s context map. What does this imply about a child that calls `getContext` before versus after its parent’s `setContext`?

9.  You must render `<Badge />`, which calls `getCart()`, in a unit test with a prepared `Cart`. Write the mounting code. Why does the `Wrapper` need to call the setter itself rather than passing a `context` map to `mount`?

10. (Multiple choice) In SSR, which of the following can leak data from one user’s request to another?

    a.  A `createContext` value set in the root component
    b.  A `$state` object exported from a `.svelte.ts` module and mutated during rendering
    c.  Props passed to `render`
    d.  A class instance created inside a provider component

11. A colleague argues that it is fine to use a module-level singleton cart because the app “only renders on the client”. Under what conditions is that safe, and what would make you reject it?

12. Under `experimental.async`, why does this fail, and how do you rewrite it? `svelte <script lang="ts"> import { setUser } from './ctx.ts'; const user = await fetchUser(); setUser(user); </script>`

13. State the three rules of the store contract. What extra behaviour is allowed for RxJS interop, and what is the downside if the subscription is not called synchronously?

14. Which of these compile or run successfully, and what error (if any) does each produce?

    a.  `$count` used inside an `if` block where `count` was declared in that block
    b.  `$count` inside `<script module>`
    c.  `$count` in a `.svelte.ts` file
    d.  A local variable named `$total`

15. What does the following log, and why? `ts const s = writable({ n: 1 }); let calls = 0; s.subscribe(() => calls++); s.set(get(s)); console.log(calls);`

16. A `readable` with a start function opens a WebSocket. Describe exactly when the socket opens and closes. What does `get(store)` do to it, and why does the documentation discourage `get` in hot paths?

17. Given `a = writable(1)`, `b = derived(a, x => x * 2)` and `c = derived([a, b], ([x, y]) => x + y)`, can a subscriber to `c` ever observe an inconsistent pair (new `a`, stale `b`)? What does this say about choosing stores versus `$derived`?

18. How does `derived` decide whether its callback is synchronous or manual (receives `set`)? Write a derived store that debounces `a` by 300 ms and cleans up its timer.

19. Explain what `toStore(() => x.value, (v) => (x.value = v))` returns and what it requires from the calling context. When would you use `fromStore` instead?

20. List three situations in which a store is still a better choice than a rune-based class, and one in which a class is clearly better.

21. Find the bugs: `ts export class Counter { count = $state(0); increment() { this.count++; } }` `svelte <script lang="ts"> const c = new Counter(); </script> <button onclick={c.increment}>+</button>`

22. Why does the `Cart.add` method replace the entry with a new object in the `SvelteMap` instead of doing `line.qty += 1`? What changes if the values are class instances with `$state` fields?

23. Why can `SvelteMap#getOrInsert` fail during server rendering on Node 22, and how do you write portable code?

24. Describe the difference between a factory function returning `{ count, doubled }` and one returning an object with getters. Which stays reactive, and why?

25. Design question: you are building a multi-widget dashboard page in which each widget has its own filter state, and the app is server-rendered. Compare a module singleton, a context-scoped class instance, and props for sharing the filter state, and recommend one.

26. In the `History` class, why are the stacks declared with `$state.raw` and replaced rather than mutated? What would break with `$state([])` and `push` for `canUndo`?

27. Complete the persistence class: what two signals does `PersistedState.current` read, and why is each needed? Why does the `storage` event handler not fix local writes?

28. What is the `createSubscriber` contract for when `start` runs and when its cleanup runs? Why does the implementation count down subscribers in a microtask?

29. An `$effect` copies `props.items.length` into a `$state` called `count`. List three problems with this approach and the one-line replacement.

30. Why does the compiler reject `export let count = $state(0)` when `count` is reassigned in the module, and what are two alternatives?
