# Chapter 3: `$state` — Deep Reactivity, Proxies and Ownership

`$state` is the rune that turns a variable into a source of change. It looks trivial (`let count = $state(0)`), but behind that one call sit three different mechanisms: a plain signal for primitives, a recursive proxy for arrays and plain objects, and a class transform for fields. Each has its own identity rules, performance profile and failure modes. This chapter explains all of them, plus the neighbouring APIs you need to reason about state in a real application: `$state.raw`, `$state.snapshot`, `$state.eager`, passing state across function and module boundaries, prop ownership, and the reactive built-ins in `svelte/reactivity`. Most claims below were checked by running code against `svelte@5.57.2` under Vitest/jsdom, using `$effect.root` plus `flushSync` to count effect runs. Compiler output and runtime internals are illustrative; Chapter 5 covers the machinery in depth.

## Primitives and the compiler’s decision

For a primitive, `$state` produces a *source*: a box holding a value and a list of reactions that read it.

```html
<script lang="ts">
  let count = $state(0);
</script>

<button onclick={() => count++}>clicks: {count}</button>
```

As Chapter 2 showed, the compiler turns this into `$.state(0)`, reads into `$.get(count)` and `count++` into `$.update(count)`. If the variable is never reassigned in the file, it stays a plain variable. There is no API on the value: `count` is a number, not a wrapper.

A source uses `===`-like equality (`Object.is` semantic via the internal `equals`) to decide whether a write is a change: assigning the same primitive again does nothing. For objects assigned to a plain (non-proxy) source the check is identity, which is why `$state.raw` needs reassignment, as we will see.

## Deep state: proxies for arrays and plain objects

If the initial value (or any later assigned value) is an **array or a plain object**, `$state` wraps it in a `Proxy`. The proxy is recursive: reading a property that holds another array or plain object yields another proxy.

```ts
const todos = $state([{ done: false, text: 'add more todos' }]);

todos[0].done = !todos[0].done;          // fine-grained update
todos.push({ done: false, text: 'eat lunch' }); // pushed object becomes a proxy
```

### What is proxied

The rule, read from `proxy.js`: a value is proxied only if `typeof value === 'object'`, it is not already a proxy, and its prototype is exactly `Object.prototype` or `Array.prototype`. Everything else is returned untouched:

| Value | Proxied? |
|------------------------------------|------------------------------------|
| `{}` / object literal | yes |
| `[]` | yes |
| `Object.create(proto)` with a custom prototype | no |
| class instances | no |
| `Date`, `Map`, `Set`, `URL`, DOM nodes | no |
| `Object.create(null)` | no (prototype is `null`, not `Object.prototype`) |
| frozen plain object | yes (reading works; writes to it are the usual frozen-object failure) |
| functions | no |

I confirmed that a `$state({ inst, plain: Object.create({y:1}), date, map })` keeps `holder.inst === inst`: the class instance is stored as-is. Non-proxied values inside state are still stored in a source, so *replacing* `holder.inst = other` is reactive, but mutating `inst.x` is not, unless `Pt` uses `$state` fields itself.

### Lazily created sources

The proxy does not create a signal per property up front. It keeps a `Map` from property key to source and creates a source on first read (or write) of that key. Arrays also eagerly create a `length` source. A separate `version` source is incremented whenever the set of keys changes, and is what `Object.keys(o)`, `for...in` and `ownKeys` read. Consequences, all confirmed by counting effect runs:

```ts
const s = $state({ value: 0 });
$effect(() => { s; });        // runs once: s is never reassigned, only mutated
$effect(() => { s.value; });  // re-runs on s.value++
```

An effect that reads the proxy but no property depends on nothing that mutation can change (documented: “An effect only reruns when the object it reads changes, not when a property inside it changes”).

For arrays: after `push`, an effect reading `arr.length` and one iterating the array re-run, but one reading only `arr[0]` does not. After `arr[0] = 10`, the effect reading `arr[0]` and the iterating one re-run, `length` does not. After `arr.length = 1`, all three re-run. For objects, `Object.keys` effects re-run on key addition and deletion, and `'b' in o` effects re-run when `b` appears.

> **Note:** In dev builds the compiler/runtime also names each source (`todos[0].done`) for `$inspect.trace`; mutating array methods are wrapped so `$inspect` fires once per call instead of at each intermediate state.

### The original is not mutated

`$state` copies on write in a sense: the proxy never writes to the target object it wraps for new properties. After `p.a = 5; p.nested.b = 9; p.list.push(3)` the `original` object still held `{"a":1,"nested":{"b":2},"list":[1,2]}`. This is by design, so that state can be forked (Chapter 5, 13), but it means you must stop using the original reference once you hand it to `$state`.

### Identity: `proxy !== original`

```ts
const item = { id: 1 };
const list = $state<{ id: number }[]>([]);
list.push(item);

list.includes(item);   // false
list.indexOf(item);    // -1
list[0] === item;      // false
list.indexOf(list[0]); // 0
```

All verified. The proxy returned when you read `list[0]` is a different object from `item`. Comparisons must use values that went through the same path. In dev, `===`, `==`, `!==`, `!=` between a proxy and its original raise the `state_proxy_equality_mismatch` warning (“Reactive `$state(...)` proxies and the values they proxy have different identities. Because of this, comparisons with `%operator%` will produce unexpected results”). I saw it fire twice for `v === p` and `p == v`. Note that `includes`/`indexOf` are not instrumented, so they silently return wrong results.

Remedies: look items up by id (`list.find(x => x.id === item.id)`), keep the proxy reference you got back (`const added = list[list.length - 1]`), or use `$state.raw` for collections of objects whose identity matters. The same issue appears with `Set`/`Map` keys: a plain `Set` holding the original does not match the proxy.

Another consequence: `structuredClone(proxy)` throws `DataCloneError` (verified). Use `$state.snapshot`.

### Destructuring loses reactivity

```ts
let { done } = todos[0];       // evaluated now; `done` is a plain boolean
todos[0].done = !todos[0].done; // does not update `done`
```

In my test an effect reading `todo.done` ran twice after the mutation while an effect reading the destructured `done` ran once. In templates, `{#each todos as { done }}` destructuring is allowed, but the best-practices page warns “avoid destructuring if you need to mutate the item (with something like `bind:value={item.count}`)”.

### Assignment value gotcha: `assignment_value_stale`

```ts
let object = $state({ array: null as number[] | null });
function add() {
  (object.array ??= []).push(object.array.length);   // warns
}
```

`??=` evaluates to the right-hand side (`[]`, the raw array), not to the proxy the property now holds. The push goes into the raw array and is lost: in my run `object.array` was still `[]`. Dev builds warn `assignment_value_stale`. Split it into two statements: `object.array ??= []; object.array.push(...)`.

### Logging: `console_log_state`

Logging a proxy in devtools shows the proxy internals. Svelte patches `console` methods in dev to warn (`console_log_state`) when an argument is a state proxy, and to print a snapshot. Prefer `$inspect(value)` for logging over time and `console.log($state.snapshot(value))` for one-offs.

### Property descriptor and prototype restrictions

The proxy only accepts plain data descriptors. `Object.defineProperty(p, 'x', { value: 1, enumerable: false })` throws `state_descriptors_fixed` (“Property descriptors defined on `$state` objects must contain `value` and always be `enumerable`, `configurable` and `writable`”), and `Object.setPrototypeOf(p, ...)` throws `state_prototype_fixed`. Accessors defined with `get`/`set` in an object literal are fine because they are defined on the target before wrapping, and reads on prototype chains pass through.

## `$state` in classes

Class instances are not proxied. To get reactivity in a class, put `$state` on fields, public or private, or on the first assignment in the constructor (5.31):

```ts
// src/lib/todo.svelte.ts
export class Todo {
  done = $state(false);
  #attempts = $state.raw(0);
  text: string;

  constructor(text: string) {
    this.text = text;
  }

  get attempts() { return this.#attempts; }

  reset = () => {
    this.text = '';
    this.done = false;
  };
}
```

What the compiler generates for this shape (illustrative, via `compileModule`):

```js
export class Todo {
  #done = $.state(false);
  get done() { return $.get(this.#done); }
  set done(value) { $.set(this.#done, value, true); }
  ...
}
```

and for a constructor assignment `this.text = $state(text)`:

```js
#text;
get text() { return $.get(this.#text); }
set text(value) { $.set(this.#text, value, true); }
constructor(text) { this.#text = $.state($.proxy(text)); }
```

Observations that I confirmed:

- The fields become **accessors on the prototype** backed by private fields, so they are **not own, enumerable properties**: `Object.keys(todo)` listed only `text` (the plain field), and `JSON.stringify(todo)` produced `{"text":"a"}`: reactive fields vanish from JSON. Add a `toJSON` method (or use `$state.snapshot`, which honours `toJSON`).
- A constructor-assigned state (`this.a = $state(1)`) works the same way and is also non-enumerable.
- `$state` accepts objects: `items = $state<Todo[]>([])` makes the array a proxy while `Todo` instances stay raw, which is good, because each manages itself.
- The `$state` call must be a field initializer or the *first* assignment at the top level of the constructor; anywhere else is `state_invalid_placement`. Assigning to a state field before its declaration is `state_field_invalid_assignment`.
- Class `$derived` fields work too (`twice = $derived(this.#n * 2)`) and compile to a derived with a getter; Chapter 4 covers them.

### The `this` pitfall

Methods lose `this` when detached. `<button onclick={todo.reset}>` calls `reset` with `this` set to the button (for a prototype method), failing or mutating the wrong object. In my test, destructuring `const { bump } = t; bump()` threw `TypeError`. Two fixes: an inline closure (`onclick={() => todo.reset()}`) or an arrow-function field (`reset = () => {...}`, as above). The trade-off: arrow fields are per-instance closures (they cost memory per instance and live on the instance, not the prototype), so use them only for methods you pass around. The compiler even warns about related patterns: `perf_avoid_inline_class` and `perf_avoid_nested_class` discourage creating classes in hot code.

## `$state.raw`

`$state.raw(value)` skips the proxy. The value is stored in a plain source; changes happen only through reassignment.

```ts
let person = $state.raw({ name: 'Heraclitus', age: 49 });

person.age += 1;            // no effect on reactivity
person = { ...person, age: 50 };  // reactive
```

I counted effect runs: after `person.age += 1`, effects reading `person` and `person.age` each ran once (no re-run), though the underlying object did change (`age` read back 50). After reassignment both ran again. Raw state can contain reactive state, and class fields can be `$state.raw`.

### Cost model: when to prefer raw

The best-practices page: “In cases where you’re dealing with large objects that are only ever reassigned (rather than mutated), use `$state.raw` instead. This is often the case with API responses.”

What a deep proxy costs:

- **Creation**: one `Proxy` per object/array, created lazily (nested values are proxied as they are first read through `proxy(...)` in the `get` trap; assignments proxify eagerly).
- **Every read** passes through a trap that looks up a `Map` of sources and calls `get(source)` (dependency registration when inside a reaction).
- **Memory**: one `Map` and a `version` source per proxy, and one source per property that has been touched.
- **Every write** goes through the `set` trap, which also proxifies the new value.

What raw costs: one source for the whole value; reads are `get(source)`; no per-property tracking. The trade-off is that updates are coarse: any change re-runs every effect that read the value, and you must produce new objects immutably (`items = items.map(...)`, `[...items, x]`, `structuredClone`-free spreads). Raw is the right default for:

- data fetched from a server and replaced wholesale,
- big read-only datasets (tables, charts, parsed files),
- objects with identity semantics (class instances, DOM nodes, third-party objects) that you do not want wrapped,
- anything you pass to libraries that dislike proxies.

Use `$state` (deep) for small, user-edited structures where mutation ergonomics matter: forms, todo lists, settings. Chapter 18 returns to measuring this.

## `$state.snapshot`

`$state.snapshot(value)` returns a deep, static copy, suitable for `structuredClone`-like consumers, `postMessage`, IndexedDB, or libraries that reject proxies:

```ts
function send() {
  navigator.sendBeacon('/log', JSON.stringify($state.snapshot(counter)));
}
```

From `internal/shared/clone.js`, the algorithm is:

1.  `Map` and `Set` are copied shallowly (`new Map(value)`).
2.  Arrays and plain objects are copied recursively, with a cycle map so shared references and cycles are preserved.
3.  `Date` becomes a `structuredClone` (and reads `getTime()` so `SvelteDate` is tracked).
4.  Any other object with a `toJSON` function is replaced by the clone of the `toJSON()` result.
5.  `EventTarget`s are returned as-is.
6.  Everything else goes through `structuredClone`; if it throws, the **original value is returned** and, in dev, `state_snapshot_uncloneable` is logged listing the offending paths.

Verified: a snapshot of `{ a: [1, {b: 2}], d: new Date(0), toJSONer: { toJSON(){ return 'custom' } } }` was a distinct object with `a` also distinct, a real `Date`, and `toJSONer` replaced by `'custom'`. Because the replacement happens in the clone, the snapshot’s `toJSONer` was the string. A class instance (no `toJSON`) falls to `structuredClone`, which drops the prototype: `$state.snapshot(new A())` returned an `Object` that is not `instanceof A`. And an object containing a function triggered `state_snapshot_uncloneable` (functions cannot be structured-cloned), leaving the original function in the snapshot.

The `Snapshot<T>` type (see `types/index.d.ts`) maps `SvelteDate`, `SvelteMap` and `SvelteSet` to `Date`, `Map` and `Set`, and treats `URL` as uncloneable. Browser support: Chrome/Edge 98, Firefox 94, Safari 15.4 (because of `structuredClone`).

> **Senior tip:** A snapshot inside a hot path is O(size). Take snapshots at boundaries (submit handlers, persistence), not inside effects that run on every keystroke.

## `$state.eager`

Under the experimental async flag, state updates that an `await` expression depends on are applied together and the UI keeps showing the old state until the new async work resolves (Chapter 13). Sometimes you want immediate feedback. `$state.eager(value)` returns the latest value immediately:

```html
<nav>
  <a href="/" aria-current={$state.eager(pathname) === '/' ? 'page' : null}>home</a>
  <a href="/about" aria-current={$state.eager(pathname) === '/about' ? 'page' : null}>about</a>
</nav>
```

I verified this with the async flag on (`svelte({ compilerOptions: { experimental: { async: true } } })`). In a component with `{$state.eager(page)}`, `{page}` and `{await load(page)}` (50 ms delay), clicking the button and awaiting `tick()` gave: eager shows `2`, plain shows `1`, data shows `page 1`; after the promise resolved all showed 2. So the plain read and the async read are synchronised and lag, while the eager read is updated at once. Internally `$state.eager` creates an `eager_effect` that is run synchronously after each write (outside the batch’s deferred values) and bumps a version source to re-run the consumer (Chapter 5). Without the flag there is no pending async work, so it behaves like a plain read. When called outside a reaction it just returns `fn()`.

Use sparingly: the docs say “only to provide feedback in response to user action”.

## Passing state to functions

JavaScript passes values. `$state` variables are read as values:

```ts
let a = $state(1);
let b = $state(2);
const total = add(a, b);   // add receives 1 and 2
```

To give a function access to the *current* value you pass functions (getters):

```ts
function add(getA: () => number, getB: () => number) {
  return () => getA() + getB();
}
const total = add(() => a, () => b);
total(); // always current
```

Equivalent shapes: proxy objects (`add(input)` reading `input.a` later), accessor properties (`get value() {...}`), or class instances with `$state` fields. The docs say that if you find yourself writing accessor objects by hand, consider a class.

This is the same constraint that makes reactive composition functions return getters:

```ts
// src/lib/useDouble.svelte.ts
export function useDouble(read: () => number) {
  const doubled = $derived(read() * 2);
  return { get value() { return doubled; } };
}
```

```html
<script lang="ts">
  import { useDouble } from './useDouble.svelte';
  let n = $state(1);
  const d = useDouble(() => n);
</script>
{d.value}
```

Returning `{ value: doubled }` would freeze the number at creation. (Chapter 12 builds larger patterns on this.)

## Sharing state across modules

You can create state in `.svelte.ts` files. You can export it only if it is not reassigned:

```ts
// state.svelte.ts
export const counter = $state({ count: 0 });   // allowed: never reassigned
export function increment() { counter.count += 1; }
```

```ts
export let count = $state(0);   // state_invalid_export
```

The second yields the compile error “Cannot export state from a module if it is reassigned. Either export a function returning the state value or only mutate the state value’s properties”. Why: Chapter 2 showed the rewrite `export let count = $.state(0)` with every internal use `$.get(count)`/`$.set(...)`. Another file importing `count` receives the signal object (`typeof count` would be `'object'`), and the compiler, which sees one file at a time, cannot rewrite the importer. A `$state` object that is only mutated compiles to `export const counter = $.proxy({ count: 0 })` with no wrapping source, so importers read properties on the proxy, which is reactive on its own.

Alternatives: keep the state private and export accessor functions (`getCount()`), or use a class and export one instance. `$derived` cannot be exported either (`derived_invalid_export`): export a function returning the value.

> **Warning:** Module-level state is per module *instance*, i.e. per process in SSR. A module singleton shared across requests leaks data between users. Chapter 12 and 14 cover context-scoped alternatives.

## Ownership: who may mutate what

Props are one-way by default. A child may *reassign* a prop temporarily (the local value overrides until the parent changes it) but should not *mutate* an object it did not create. In dev, Svelte checks this.

```html
<!-- Parent.svelte -->
<script lang="ts">
  import Child from './Child.svelte';
  let person = $state({ name: 'Florida' });
</script>
<Child {person} plain={{ count: 0 }} />
<p>{person.name}</p>
```

```html
<!-- Child.svelte -->
<script lang="ts">
  let { person, plain } = $props();
</script>
<button onclick={() => (person.name = 'changed')}>mutate state</button>
<button onclick={() => plain.count++}>mutate plain</button>
```

I ran this. Clicking the first button changed the parent’s text to `changed` (state proxies propagate) and logged:

```text
[svelte] ownership_invalid_mutation Mutating unbound props (`person`, at Child.svelte:4:34) is strongly discouraged. Consider using `bind:person={...}` in Parent.svelte (or using a callback) instead
```

Clicking the second changed nothing visible: a plain object is not reactive, so the mutation is silent and has no UI effect (“`plain` count 0” remained). The same applies to fallback values: `let { object = { count: 0 } } = $props()` leaves the fallback unproxied, so mutations to it do nothing.

How the check works (`dev/ownership.js`): when a component mutates a prop path (compiled with `$$ownership_validator.mutation(...)`), the validator looks at the prop in the component’s props object. If the prop has a setter (it was passed with `bind:`) or is not present, it is allowed. Otherwise, if the chain of values is a state proxy (`STATE_SYMBOL`) it warns, naming the parent component. The validator is dev-only.

The fix is either a callback prop (`onrename(name)`), or `$bindable`:

```html
<script lang="ts">
  let { person = $bindable() } = $props();
</script>
```

with `<Child bind:person />` in the parent. Binding chains must be unbroken: if `Top` does `<Middle bind:value={v}>` and `Middle` does `<Bind bind:value />` all is well (no warning in my run). If `Top` passes `value={v}` without `bind:` and `Middle` still binds it onward, you get `ownership_invalid_binding` (“`Middle.svelte` passed property `value` to `Bind.svelte` with `bind:`, but its parent component `Top2.svelte` did not declare `value` as a binding…”). A bindable prop with a fallback requires the parent to pass a non-`undefined` value when it uses `bind:` (`props_invalid_value`). Chapter 7 and 8 detail props and bindings.

## Reactive built-ins: `svelte/reactivity`

Native `Map`, `Set`, `Date` and `URL` hold their state in internal slots; proxies cannot observe them, which is why `$state` does not proxy them. `svelte/reactivity` provides subclasses.

```ts
import { SvelteMap, SvelteSet, SvelteDate, SvelteURL, SvelteURLSearchParams } from 'svelte/reactivity';
```

They extend the native classes (so `instanceof Map` works) and keep their own sources. Reading registers dependencies; writing triggers them. From `map.js`, `set.js`, `date.js`, `url.js`:

**`SvelteMap`** keeps a per-key source map, a `size` source and a `version` source. `get(key)`/`has(key)` track the key’s source if present, or the version if absent (so a later insert re-runs). Iteration (`entries`, `values`, `forEach`) reads everything. `set` of an existing key with the same value is a no-op; a new key increments size and version. In my test: effects on `m.get('a')`, `m.get('b')`, `m.size` and an iterating effect responded as follows. `set('b')`: `b` effect, size and iteration re-ran, `a` did not. `set('a', newValue)`: `a` and the iterator re-ran, size did not. `delete('a')` re-ran the `a` and size effects. Since 5.57 there are `getOrInsert(key, value)` and `getOrInsertComputed(key, fn)`, mirroring the TC39 proposal:

```ts
const groups = new SvelteMap<string, string[]>();
function add(key: string, v: string) {
  groups.getOrInsertComputed(key, () => []).push(v);   // the array is NOT reactive
}
```

Note the comment: **values are not deeply reactive**. `m.get('a').n = 99` did not re-run an effect reading `m.get('a')?.n` (it ran once). If you need reactive values, store `$state` class instances or proxies (`m.set(k, $state({...}))` is invalid placement; use a class with `$state` fields or replace the value).

**`SvelteSet`** tracks per-value `has` sources, `size` and a version; adding an existing value is a no-op (verified: no re-run). Set-algebra methods (`union`, `intersection`, …) return new `SvelteSet`s.

**`SvelteDate`** wraps the time in one source and memoises each getter (`getFullYear()`, …) in a derived so that an effect reading `getFullYear()` does not re-run when only the hours change (verified: after `setUTCHours(5)` the `getFullYear` effect stayed at 1 run while `getUTCHours` re-ran).

**`SvelteURL`** has one source per component (`protocol`, `hostname`, `pathname`, `hash`, `search`, …), and a linked `SvelteURLSearchParams`. In my test `u.searchParams.set('q','2')` re-ran the `searchParams.get('q')` effect but not the `pathname` or `hash` effects; assigning `pathname` re-ran only the `pathname` effect (and `href` consumers).

There is no `SvelteWeakMap` etc. in this version. Creating these classes inside effects ties their internal sources to the creating reaction in a way designed to avoid self-invalidation (the `update_version` logic in `map.js`); in practice create them at component or module initialisation.

## Putting it together: choosing a state shape

| Situation | Choice |
|----|----|
| Counter, flag, input text | `$state(primitive)` |
| Small editable record or list | `$state({...})`, mutate in place |
| Entities with behaviour | class with `$state` fields |
| Big server payload, replaced on refetch | `$state.raw`, reassign |
| Keyed collection with frequent single-key updates | `SvelteMap` |
| Membership set | `SvelteSet` |
| Needs to leave the app (JSON, postMessage) | `$state.snapshot` |
| Needs immediate feedback during async updates | `$state.eager` |

A worked example mixing them, a searchable inventory:

```ts
// src/lib/inventory.svelte.ts
import { SvelteSet } from 'svelte/reactivity';

export interface Item { id: number; name: string; qty: number }

export class Inventory {
  items = $state.raw<Item[]>([]);        // replaced on every load
  selected = new SvelteSet<number>();
  query = $state('');

  visible = $derived(
    this.items.filter((i) => i.name.toLowerCase().includes(this.query.toLowerCase()))
  );

  async load() {
    const res = await fetch('/api/items');
    this.items = await res.json();       // one source write, no proxy cost
  }

  adjust(id: number, delta: number) {
    this.items = this.items.map((i) => (i.id === id ? { ...i, qty: i.qty + delta } : i));
  }

  toggle(id: number) {
    if (this.selected.has(id)) this.selected.delete(id);
    else this.selected.add(id);
  }

  export() {
    return JSON.stringify($state.snapshot(this.items));
  }
}
```

`items` is raw because it is replaced wholesale, and `adjust` shows the immutable-update idiom. `selected` is a `SvelteSet` held in a plain field: the instance is never reassigned, so no `$state` is required (a `$state` field would wrap a class instance, which is not proxied anyway). Note that `SvelteSet` members keep identity semantics, there is no proxy to compare against.

## Seeding state from props

A frequent pattern is local editable state that starts from a prop. Writing `let draft = $state(initial)` captures the prop’s value once, and the compiler warns (`state_referenced_locally`; I saw it for exactly this code in a test component). Sometimes that is the intent, since the parent’s later changes should not clobber the user’s edits. Make the intent explicit by naming the prop for what it is and silencing the warning with a reason:

```html
<script lang="ts">
  let { initialName }: { initialName: string } = $props();

  // svelte-ignore state_referenced_locally (we only want the initial value)
  let name = $state(initialName);
</script>

<input bind:value={name} />
```

If the edit should reset whenever the parent supplies a new value, do not use an effect to copy it. Use a writable derived (5.25), which re-evaluates when its source changes but can be overridden locally, as Chapter 4 shows, or key the component with `{#key}` when a full reset is acceptable. Both keep the dependency explicit and avoid the write-in-effect pattern the docs discourage.

A second variant is state created inside deriveds or effects. Since 5.24 such state can be written and read locally without invalidating the reaction that created it, which makes helper objects such as `new SvelteMap()` safe to create inside an effect; the `update_version` bookkeeping in `map.js` exists precisely so the map’s own sources are not registered as dependencies of the effect that created it.

## Gotchas collected

- `let { a } = state` and `const x = state.field` copy values. Read through the object inside effects/templates.
- `list.includes(rawItem)` returns `false` for state arrays: compare by id or find via the proxy.
- `JSON.stringify(classInstance)` omits `$state` fields; provide `toJSON`.
- `structuredClone(proxy)` throws; `$state.snapshot` does not.
- A `$state` call in the wrong position is a compile error (`state_invalid_placement`), never silent.
- Reassigning `$state.raw` to an object with the same identity is *not* a change; create a new object.
- `state_referenced_locally` (compile warning) fires for `let copy = state` at top level of a component/module scope. Ignore it intentionally with `svelte-ignore` when you want a one-time copy of a prop.
- Mutating props: use callbacks or `$bindable`; otherwise expect `ownership_invalid_mutation` in dev.
- `$state` inside `.ts` (not `.svelte.ts`) throws `rune_outside_svelte` at runtime.

## Key takeaways

- `$state` of a primitive is a signal; of an array or plain object it is a lazily-populated recursive proxy; class instances, `Map`, `Set`, `Date` and `Object.create` objects are not proxied.
- The proxy keeps one source per touched property plus `length` and a keys-version source. The original object is never mutated and has a different identity from the proxy; `includes`, `indexOf` and `===` with originals fail (and warn in dev only for operators).
- Destructuring copies values. Effects re-run only when what they actually read changes.
- Class `$state` fields compile to prototype accessors over private fields: non-enumerable, absent from `JSON.stringify`, and `this` is lost on detached methods unless you use arrow fields or closures. Constructor-first-assignment is supported (5.31).
- `$state.raw` avoids proxy cost and requires reassignment; it is the right default for large, replaced-wholesale data.
- `$state.snapshot` deep-copies (honouring `toJSON`, preserving cycles), returns originals with `state_snapshot_uncloneable` for things `structuredClone` rejects, and needs Chrome 98 / Firefox 94 / Safari 15.4.
- `$state.eager` gives instant values while `await` work holds back other updates (experimental async).
- Runes are not values: pass getters or objects. Export module state only if it is never reassigned (`state_invalid_export`).
- Mutating a prop you do not own is flagged by `ownership_invalid_mutation`/`ownership_invalid_binding` in dev; use callbacks or an unbroken `$bindable` chain.
- `SvelteMap`, `SvelteSet`, `SvelteDate`, `SvelteURL`, `SvelteURLSearchParams` provide fine-grained reactive built-ins; their values are not deeply reactive; `SvelteMap` gained `getOrInsert`/`getOrInsertComputed` in 5.57.

## Review Questions

1.  What does `$state` do differently for `0`, `[]`, `{}`, `new Map()` and `new Todo()` (a class instance)?

2.  State the exact condition under which a value is wrapped in a proxy.

3.  What does this print, and why?

```ts
const item = { id: 1 };
const list = $state<{ id: number }[]>([]);
list.push(item);
console.log(list.includes(item), list.indexOf(list[0]));
```

4.  Which of these triggers `state_proxy_equality_mismatch` in dev: `proxy === original`, `list.includes(original)`, `proxy.a === 1`?

5.  Why does the effect below run only once even after `s.value++`? Rewrite it so it re-runs.

```ts
const s = $state({ value: 0 });
$effect(() => { s; });
```

6.  Find the bug:

```ts
const todos = $state([{ done: false }]);
let { done } = todos[0];
todos[0].done = true;
console.log(done);
```

7.  What is printed, and which warning appears in dev?

```ts
let o = $state<{ list: number[] | null }>({ list: null });
(o.list ??= []).push(1);
console.log(o.list);
```

8.  Why does `Object.defineProperty(proxy, 'x', { value: 1, enumerable: false })` throw? Give the error code.

9.  Given `class Todo { done = $state(false); text = 'a'; }`, what do `Object.keys(new Todo())` and `JSON.stringify(new Todo())` return?

10. Why does `<button onclick={todo.reset}>` fail for a prototype method, and what are two fixes with their trade-offs?

11. Is `this.a = $state(1)` valid inside a constructor? What about inside a method? What does the compiler produce?

12. When is `$state.raw` preferable to `$state`? Name the three costs of a deep proxy it avoids.

13. After `person.age += 1` on raw state `{ name, age }`, does an effect reading `person.age` re-run? Does the value change?

14. Describe what `$state.snapshot` returns for (a) a `Date`, (b) an object with `toJSON`, (c) an instance of a class with methods, (d) an object containing a function.

15. Why does `$state.snapshot` need Chrome 98 / Firefox 94 / Safari 15.4?

16. Multiple choice: which statement about `$state.eager` is true?

    a.  It disables batching for all state.
    b.  It returns the latest value immediately even while async work is holding back other updates.
    c.  It is required for every `await`.
    d.  It makes a value deeply reactive.

17. Explain why `export let count = $state(0)` is rejected but `export const counter = $state({ count: 0 })` is allowed.

18. Write two valid ways to share a counter that is reassigned between modules.

19. What does this return and why is the getter needed?

```ts
export function useDouble(n: number) {
  const d = $derived(n * 2);
  return { value: d };
}
```

20. A child component does `person.name = 'x'` on a prop that the parent passed as `{person}` where `person` is `$state`. What happens at runtime and in dev?

21. What happens if the parent passes a plain object `{ count: 0 }` and the child mutates `count`?

22. Explain `ownership_invalid_binding` with a three-component example.

23. In a `SvelteMap<string, {n: number}>`, will an effect reading `m.get('a')?.n` re-run after `m.get('a')!.n++`? After `m.set('a', {n: 5})`? Why?

24. Which built-ins does `svelte/reactivity` export, and what does `SvelteDate` memoise?

25. Design question: you load 50,000 rows once and filter/sort them client-side, and a user can edit one cell at a time. Propose a state shape and justify `$state` vs `$state.raw`, immutability and derived filtering.

26. Why is a module-level `$state` singleton dangerous in SSR, and what do you use instead?

27. A teammate logs `console.log(todos)` and sees a Proxy with confusing content. Name the dev warning and two better approaches.
