# Chapter 7: Components, Props and Snippets

A Svelte 5 component is a function that receives an anchor and a props object, and everything that crosses a component boundary does so through that props object: data, callbacks, content (snippets), attachments and bindings. Svelte 4 had four separate mechanisms for this (`export let`, `createEventDispatcher`, slots with `let:` and `$$props`/`$$restProps`). Svelte 5 collapses them into one: **props are values, and values can be functions, and snippets are functions that render markup.** Once you internalise that, most component design questions become ordinary API design questions.

This chapter covers `$props` in depth (destructuring, fallbacks, renaming, rest, live reads, mutation rules), callback props as the replacement for component events, snippets and `{@render}` including typing, generics, module exports and `createRawSnippet`, the composition patterns that follow (render props, slot-style APIs, headless and compound components, polymorphic wrappers), component instance exports and `bind:this`, dynamic and recursive components, and `$bindable` at the contract level. Two-way binding mechanics are in Chapter 8, context in Chapter 12, attachments in Chapter 9, and the full TypeScript story in Chapter 15.

Examples are runes mode and TypeScript. I ran the runtime examples in this chapter against `svelte@5.57.2` with jsdom, in dev mode; where I quote an error code it is what the runtime threw.

## `$props`: the whole story

### Reading props

```html
<!-- Greeting.svelte -->
<script lang="ts">
  let { adjective }: { adjective: string } = $props();
</script>

<p>this component is {adjective}</p>
```

`let props = $props()` also works and gives you the props object itself (read `props.adjective`). Destructuring is the norm. Three destructuring features matter:

```ts
// fallback: used when the prop is missing OR undefined
let { adjective = 'happy' } = $props();

// rename: required for invalid identifiers or reserved words
let { super: trouper = 'lights are gonna find me' } = $props();

// rest: everything not listed
let { a, b, c, ...others } = $props();
```

Compiler rules you will meet: `$props()` may be called once per component (`props_duplicate`), only at the top level of a component’s script as a declaration initialiser, and a component using `$props()` is in runes mode, so mixing it with `export let` is an error (`legacy_export_invalid`). `$bindable()` may appear only inside a `$props()` destructuring (`bindable_invalid_location`).

### Destructured props are live, but only where you read them

The most important thing to understand is how destructuring interacts with reactivity. This is *not* ordinary JavaScript destructuring, which would copy the values once. The compiler rewrites each destructured binding into a read of the underlying props object. Here is the real output (illustrative, 5.57.2) for a snippet that uses a destructured prop `n` as an argument:

```js
row(node, () => ({ name: 'a' }), () => $$props.n);
```

`n` becomes `$$props.n` at each use site. Consequences:

1.  **Reads are live inside reactive contexts** (template, `$derived`, `$effect`, closures called from them).
2.  **A read in plain top-level script code runs once.** `let doubled = n * 2` at the top level captures the initial value, and the compiler warns: `state_referenced_locally` (“This reference only captures the initial value of `n`. Did you mean to reference it inside a closure instead?”). The fix is `$derived(n * 2)`. I got this warning for `const b = a * 2` and for `$state(a)` where `a` is a prop.
3.  If you want a local, editable copy of a prop that follows the parent when the parent changes, you want a derived (writable since 5.25) or a function binding, not `$state(prop)`.

When you do want a one-time snapshot (an `initialValue` prop), say so explicitly, silence the warning with a reason, and name the prop accordingly:

```html
<script lang="ts">
  let { initial }: { initial: number } = $props();
  // svelte-ignore state_referenced_locally (intentional: seed value only)
  let count = $state(initial);
</script>
```

### The child can temporarily override a prop

A child may *reassign* a prop. The docs describe it as “temporarily override the prop value, which can be useful for unsaved ephemeral state”:

```html
<!-- Counter.svelte -->
<script lang="ts">
  let { count }: { count: number } = $props();
</script>
<button onclick={() => count++}>{count}</button>
```

Mounting with `count: 1` and clicking once shows `2` (verified). The local override lasts until the parent next provides a new value, at which point the parent wins. This is deliberately limited: reassignment is a local concern, **mutation** of the prop’s content is a different matter.

### Mutation rules: do not mutate what you do not own

Three cases, all verified:

| Parent passes | Result of `obj.count++` in the child |
|------------------------------------|------------------------------------|
| a plain object literal | no effect, the object is not reactive |
| a `$state` proxy | UI updates, but dev warns `ownership_invalid_mutation` |
| nothing, child uses a fallback `{ object = { count: 0 } }` | no effect: fallbacks are **not** proxied |

In the second case the console shows `[svelte] ownership_invalid_mutation` (with a message naming the component that owns the state and the one that mutated it). The same ownership check powers `ownership_invalid_binding` for `bind:` chains (Chapter 8). The conclusion in the docs is blunt: “don’t mutate props. Either use callback props to communicate changes, or — if parent and child should share the same object — use the `$bindable` rune.”

The third case deserves attention because it is silent. A fallback value in a destructuring default is just the JavaScript default, so `object` is a plain object and `object.count++` changes a value nothing observes. After one click my test still rendered `0`. If a child needs its own local mutable state, create it with `$state`:

```ts
let { initial = { count: 0 } } = $props();
let local = $state(structuredClone(initial)); // a deliberate copy, not the parent's object
```

### Rest props are read-only

```html
<script lang="ts">
  let { a, ...rest }: { a: number; [k: string]: unknown } = $props();
</script>
```

Assigning to a rest property (`rest.x = 1`) throws `props_rest_readonly` (“Rest element properties of `$props()` such as `rest.x` are readonly”) in dev. The rest object is a proxy that forwards reads to the live props minus the excluded names; in production the set trap returns `false`, which throws a `TypeError` in strict mode. Treat the rest object as an immutable view; spreading it (`<button {...rest}>`) keeps it live.

### `$props.id()`

`const uid = $props.id();` (5.20) returns an id unique to the component instance that is **identical between server and client**, which is the point: hand-rolled counters and `Math.random()` ids cause hydration mismatches. Use it to link labels and controls:

```html
<script lang="ts">
  const uid = $props.id();
</script>

<label for="{uid}-email">Email</label>
<input id="{uid}-email" type="email" />
```

It may only be used at the top level as a variable-declaration initialiser (`props_id_invalid_placement`: I got this error when I put it inside a function).

### The `children` prop is reserved

Content between component tags that is not a snippet declaration becomes a snippet prop named `children`. The migration guide: “You cannot have a separate prop by that name.” Avoid the name for anything else, and never name a data prop `children`.

## Component events are callback props

Svelte 4 components emitted events with `createEventDispatcher()` and consumers wrote `on:inflate={...}` reading `event.detail`. That API is deprecated. In Svelte 5 a “component event” is a function-valued prop:

```html
<!-- Pump.svelte -->
<script lang="ts">
  let { inflate, deflate }: {
    inflate: (power: number) => void;
    deflate?: (power: number) => void;
  } = $props();
  let power = $state(5);
</script>

<button onclick={() => inflate(power)}>inflate</button>
<button onclick={() => deflate?.(power)}>deflate</button>
<button onclick={() => power--}>-</button> {power}
<button onclick={() => power++}>+</button>
```

```html
<!-- App.svelte -->
<script lang="ts">
  import Pump from './Pump.svelte';
  let size = $state(15);
  let burst = $derived(size > 75);
</script>

<Pump inflate={(p) => (size += p)} deflate={(p) => (size -= p)} />
```

Advantages over the dispatcher: typed arguments (no `CustomEvent<T>` ceremony), the callback’s return value is available to the child (a handler can veto or transform), an optional callback is simply `?.()`, and there is no event bubbling model to reason about. Naming convention: `onsomething` for notifications (`onclose`, `onselect`), imperative verbs for commands. Do not name a custom-element-destined prop starting with `on` unless it is an event (Chapter 19).

### Forwarding DOM events and spreading handlers

To “forward” a native event, accept the handler as a prop and attach it:

```html
<script lang="ts">
  let { onclick }: { onclick?: (e: MouseEvent) => void } = $props();
</script>
<button {onclick}>click me</button>
```

Since handlers are plain props, a wrapper can forward all attributes, handlers included, with a rest spread:

```html
<script lang="ts">
  import type { HTMLButtonAttributes } from 'svelte/elements';
  let { children, ...rest }: HTMLButtonAttributes = $props();
</script>
<button {...rest}>{@render children?.()}</button>
```

### Combining local and incoming handlers

Duplicate attributes are not allowed and spread order decides precedence. If a wrapper needs its own `onclick` *and* wants to honour the caller’s, put its handler **after** the spread and call the incoming one explicitly. The migration guide spells out the pattern:

```html
<script lang="ts">
  import type { HTMLButtonAttributes } from 'svelte/elements';
  let { children, ...props }: HTMLButtonAttributes = $props();
  let clicks = $state(0);
</script>

<button
  {...props}
  onclick={(e) => {
    clicks++;
    props.onclick?.(e);
  }}
>
  {@render children?.()} ({clicks})
</button>
```

Put the handler before the spread and the caller’s `onclick` silently replaces yours.

> **Warning:** In a single component you cannot mix the `on:click` directive with `onclick` attributes. The compiler throws `mixed_event_handler_syntaxes`. Migrating one file means migrating all of its events.

For listeners the parent attaches to a *mounted* app (rare), `mount` still accepts an `events` option but it is deprecated; use callback props.

## Snippets

A snippet is a named, parameterised chunk of markup: `{#snippet name(params)}...{/snippet}`, rendered with `{@render name(args)}`. Think of it as a function whose body is a template.

```html
{#snippet figure(image)}
  <figure>
    <img src={image.src} alt={image.caption} width={image.width} height={image.height} />
    <figcaption>{image.caption}</figcaption>
  </figure>
{/snippet}

{#each images as image}
  {#if image.href}
    <a href={image.href}>{@render figure(image)}</a>
  {:else}
    {@render figure(image)}
  {/if}
{/each}
```

### What a snippet compiles to

Here is the client output (illustrative, 5.57.2) for `{#snippet row(d, i = 0)}<td>{d.name} {i}</td>{/snippet}` rendered with `{@render row({name:'a'}, n)}`:

```js
const row = ($$anchor, d = $.noop, $$arg1) => {
  let i = $.derived_safe_equal(() => $.fallback($$arg1?.(), 0));
  var td = root();
  var text = $.only_child(td);
  $.template_effect(() => $.set_text(text, `${d().name ?? ''} ${$.get(i) ?? ''}`));
  $.append($$anchor, td);
};
// ...
row(node, () => ({ name: 'a' }), () => $$props.n);
```

Two details are worth knowing:

- A snippet is an ordinary function whose first parameter is the DOM anchor. Your parameters follow it, **wrapped as getters** (`d()`, `$$arg1?.()`). That is why a snippet parameter stays reactive: the call site passes `() => $$props.n`, not the value. Defaults are applied lazily (`$.fallback`).
- You must call snippets through `{@render}`. The `Snippet` type enforces it, and at runtime, passing wrong arguments throws `invalid_snippet_arguments` (“Snippets should only be instantiated via `{@render ...}`”) and writing `{snippet}` instead of `{@render snippet()}` throws `snippet_without_render_tag`.

### Parameters

Snippets accept any number of parameters, with defaults and destructuring, but **not rest parameters** (`snippet_invalid_rest_parameter`: “Snippets do not support rest parameters; use an array instead”). Redeclaring a parameter name inside the snippet with a declaration tag is `declaration_duplicate`.

```html
{#snippet badge({ label, tone = 'info' }: { label: string; tone?: 'info' | 'warn' })}
  <span class="badge {tone}">{label}</span>
{/snippet}

{@render badge({ label: 'new' })}
```

### Scope

Snippets are lexically scoped: visible to siblings declared in the same block and their descendants, able to see anything above them (script variables, `{#each}` variables), and not visible outside the element or block they are declared in. They can call themselves and one another, which gives you recursion without a component:

```html
{#snippet tree(node: { name: string; children: any[] })}
  <li>
    {node.name}
    {#if node.children.length}
      <ul>
        {#each node.children as child (child.name)}
          {@render tree(child)}
        {/each}
      </ul>
    {/if}
  </li>
{/snippet}

<ul>{@render tree(root)}</ul>
```

A snippet declared in the instance script scope reads the component’s current state each time it renders, so it is as reactive as the surrounding template.

### Passing snippets to components

Snippets are values, so there are three ways to give them to a child.

**Explicit props.** Declare the snippets and pass them by name: `<Table data={fruits} {header} {row} />`.

**Implicit props.** A snippet declared *directly inside* component tags becomes a prop on that component, with the snippet’s name:

```html
<Table {data}>
  {#snippet header()}<th>name</th><th>qty</th>{/snippet}
  {#snippet row(d)}<td>{d.name}</td><td>{d.qty}</td>{/snippet}
  footer text
</Table>
```

The compiled output for a similar call with one `row` snippet (illustrative) shows exactly this: `T($$anchor, { data: [1], row, children: ($$anchor, $$slotProps) => {...}, $$slots: { row: true, default: true } })`. The `$$slots` bookkeeping exists for interop with legacy components.

**Implicit `children`.** Everything inside the tags that is not a snippet declaration becomes the `children` snippet (the `"footer text"` above).

Two compile errors protect you here. A snippet declared inside component tags with the same name as an attribute prop on that component is `snippet_shadowing_prop` (“This snippet is shadowing the prop `header` with the same name”), and a snippet declared in a script scope cannot share its name with another declaration (`declaration_duplicate`).

The receiving side:

```html
<!-- Table.svelte -->
<script lang="ts" generics="T">
  import type { Snippet } from 'svelte';
  let { data, header, row, children }: {
    data: T[];
    header?: Snippet;
    row: Snippet<[T]>;
    children?: Snippet;
  } = $props();
</script>

<table>
  {#if header}<thead><tr>{@render header()}</tr></thead>{/if}
  <tbody>
    {#each data as d}<tr>{@render row(d)}</tr>{/each}
  </tbody>
</table>
<footer>{@render children?.()}</footer>
```

I ran this with a recursive tree component and this table; the output was the expected `<table><thead>...` markup.

### Optional snippets and fallbacks

`{@render children?.()}` renders nothing when the snippet is absent. To render fallback content, use an `{#if}`:

```html
{#if children}{@render children()}{:else}fallback{/if}
```

Rendering a snippet prop that is `undefined` without the optional call throws `invalid_snippet` in dev (“Could not `{@render}` snippet due to the expression being `null` or `undefined`. Consider using optional chaining `{@render snippet?.()}`”). I reproduced it with a required snippet and no value. The expression after `@render` can be any call expression: `{@render (cool ? coolSnippet : lameSnippet)()}`. Spread arguments are not allowed (`render_tag_invalid_spread_argument`) and the tag must be a call (`render_tag_invalid_expression`).

### Snippet types

Snippets implement `Snippet<Parameters extends unknown[] = []>`, where the parameter list is a **tuple**:

```ts
import type { Snippet } from 'svelte';

interface Props {
  header: Snippet;                 // no params
  row: Snippet<[Item]>;            // one param
  cell: Snippet<[Item, number]>;   // two params
}
```

The `Snippet` interface is callable only in a form that makes it unusable as a normal function: its return type is a branded object whose single key reads `'{@render ...} must be called with a Snippet'`. Arrays are rejected on purpose (the type checks `number extends Parameters['length']`, because arrays would imply rest parameters).

**Generics.** For `data` and `row` to agree on the item type, declare a generic on the script (the `generics` attribute holds what you would write between `<...>` on a function):

```html
<script lang="ts" generics="Item extends { id: string }">
  import type { Snippet } from 'svelte';
  let { items, row }: { items: Item[]; row: Snippet<[Item]> } = $props();
</script>
```

Generics on the component are the usual way; since 5.30 snippets themselves can also declare type parameters in TypeScript components: `{#snippet pick<T>(items: T[])}...{/snippet}` compiles (the AST carries a `typeParams` string on `SnippetBlock`).

### Exporting snippets from modules

Since 5.5, snippets declared at the top level of a `.svelte` file can be exported from the `<script module>` block, **provided they do not reference anything in the instance script**:

```html
<!-- snippets.svelte -->
<script module>
  export { add };
</script>

{#snippet add(a: number, b: number)}
  {a} + {b} = {a + b}
{/snippet}
```

```html
<script lang="ts">
  import { add } from './snippets.svelte';
</script>
{@render add(1, 2)}
```

If it does reference instance declarations, the compiler says `snippet_invalid_export` (“An exported snippet can only reference things declared in a `<script module>`, or other exportable snippets”). This turns a `.svelte` file into a library of shared fragments (icons, formatters). TypeScript needs the language-server plugin to see the export from `.ts` files.

### `createRawSnippet`

For the rare case where a snippet must be built in JavaScript, `createRawSnippet` returns a `Snippet` from a function:

```ts
function createRawSnippet<Params extends unknown[]>(
  fn: (...params: Getters<Params>) => {
    render: () => string;
    setup?: (element: Element) => void | (() => void);
  }
): Snippet<Params>;
```

The parameters arrive as **getter functions**, `render` returns an HTML string for a **single element**, and `setup` receives that element once and may return a cleanup function. `render` is re-run when the getters it reads change.

```html
<script lang="ts">
  import { createRawSnippet } from 'svelte';
  let { name = 'Ann' }: { name?: string } = $props();

  const greet = createRawSnippet((who: () => string) => ({
    render: () => `<strong>hello ${who()}</strong>`,
    setup: (el) => {
      el.setAttribute('data-ready', 'yes');
      return () => console.log('torn down');
    }
  }));
</script>

{@render greet(name)}
```

Note the signature: the callback gets `() => string`, and you call `who()`. (I initially passed a function as the argument and got `hello () => label()` rendered: the getter returns whatever you passed.) Because `render` produces markup as a string, you are responsible for escaping interpolated values. It is intended for wrappers that must call Svelte APIs from non-Svelte code, for example a table library whose cell renderers must return HTML. A `render` that returns more than one root element triggers the `invalid_raw_snippet_render` warning.

## Composition patterns

### Render props (snippets with arguments)

When a parent should control how each item is rendered but the child controls what the item is, pass a snippet that takes the item. This is the successor to `let:` on slots.

```html
<!-- List.svelte -->
<script lang="ts" generics="T">
  import type { Snippet } from 'svelte';
  let { items, item, empty }: {
    items: T[];
    item: Snippet<[T, number]>;
    empty?: Snippet;
  } = $props();
</script>

{#each items as it, i}
  {@render item(it, i)}
{:else}
  {@render empty?.()}
{/each}
```

### Replacing slots

| Svelte 4 | Svelte 5 |
|------------------------------------|------------------------------------|
| default `<slot />` | `children` snippet, `{@render children?.()}` |
| named `<slot name="header" />` | prop `header: Snippet` |
| slot props `<slot {item} />` / `let:item` | `Snippet<[Item]>` / `{#snippet row(item)}` |
| fallback content | `{#if header}...{:else}...{/if}` |
| `$$slots.header` | `header !== undefined` |
| `<svelte:fragment slot="x">` | `{#snippet x()}` |

Snippets can be passed through several layers, stored in objects and arrays, or chosen dynamically, which slots could not do.

### Headless components

A headless component owns behaviour and state but no markup, and hands everything to a snippet:

```html
<!-- Disclosure.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  let { open = $bindable(false), children }: {
    open?: boolean;
    children: Snippet<[{ open: boolean; toggle: () => void }]>;
  } = $props();
  const toggle = () => (open = !open);
</script>

{@render children({ open, toggle })}
```

```html
<Disclosure>
  {#snippet children({ open, toggle })}
    <button aria-expanded={open} onclick={toggle}>Details</button>
    {#if open}<p>...</p>{/if}
  {/snippet}
</Disclosure>
```

Declaring `children` explicitly as a snippet with parameters is legal; it is the one place where you write the implicit prop out. Alternatively, a class with `$state` fields in a `.svelte.ts` module can provide headless logic without any component at all (Chapter 3 and Chapter 12), which is often the better option because it composes without nesting.

### Compound components with context

For a family like `Tabs`/`Tab`, share state down the tree with context rather than prop-drilling. Preview of Chapter 12, using `createContext` (5.40; returns a `[get, set, has]` triplet since 5.57):

```ts
// tabs.svelte.ts
import { createContext } from 'svelte';

export class TabsState {
  active = $state('');
  constructor(initial: string) { this.active = initial; }
}
export const [getTabs, setTabs, hasTabs] = createContext<TabsState>();
```

```html
<!-- Tabs.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import { TabsState, setTabs } from './tabs.svelte';
  let { initial, children }: { initial: string; children: Snippet } = $props();
  // svelte-ignore state_referenced_locally (seed value only)
  const tabs = setTabs(new TabsState(initial));
</script>

<div role="tablist" data-active={tabs.active}>{@render children()}</div>
```

```html
<!-- Tab.svelte -->
<script lang="ts">
  import { getTabs } from './tabs.svelte';
  let { id, label }: { id: string; label: string } = $props();
  const tabs = getTabs();
</script>

<button role="tab" aria-selected={tabs.active === id} onclick={() => (tabs.active = id)}>
  {label}
</button>
```

```html
<Tabs initial="a"><Tab id="a" label="A" /><Tab id="b" label="B" /></Tabs>
```

I ran this; clicking the second tab sets `aria-selected="true"` on it and `data-active="b"` on the list. `getTabs()` throws if no ancestor called `setTabs`, which gives the compound children a clear contract; `hasTabs()` lets a child degrade gracefully.

> **Warning (found while testing):** my first version of `TabsState` registered tabs with `this.tabs.push(id)` inside a child `$effect`. That effect reads `length` (via `push`) and writes the same array, and the runtime stopped it with `effect_update_depth_exceeded`. Registration that mutates shared state from an effect needs `untrack`, a non-reactive structure, or a design where the parent derives the list from the snippet it renders.

### Polymorphic wrappers

Combine `<svelte:element>` (Chapter 6) with `HTMLAttributes` typing to let callers choose the tag:

```html
<!-- Box.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { ClassValue } from 'svelte/elements';

  let {
    as = 'div',
    class: klass,
    children,
    ...rest
  }: {
    as?: keyof HTMLElementTagNameMap;
    class?: ClassValue;
    children?: Snippet;
    [attr: string]: unknown;
  } = $props();
</script>

<svelte:element this={as} {...rest} class={['box', klass]}>
  {@render children?.()}
</svelte:element>
```

Typing the rest attributes precisely per tag needs a generic over the tag name and a lookup into `SvelteHTMLElements`; the index signature above is the pragmatic compromise. Do not forward `children` into `rest` for void elements (`<svelte:element this="hr">` with content throws in dev).

### Wrappers that forward attributes and attachments

A wrapper that spreads `rest` also forwards **attachments**: attachments passed to a component arrive as props keyed by symbols (`createAttachmentKey`, Chapter 9) and spreading `rest` onto an element applies them. That is why `<Button {@attach tooltip(...)}>` works when `Button` spreads its rest props onto its `<button>`. Type such wrappers with `HTMLButtonAttributes` (or `SvelteHTMLElements['div']` for elements without a dedicated interface), which include the `[attachment symbol]` slot (Chapter 15).

## Component instance exports and `bind:this`

A runes-mode component can export functions or constants from its instance script. These form its imperative API:

```html
<!-- Fancy.svelte -->
<script lang="ts">
  let input: HTMLInputElement;
  let count = $state(0);
  export function focus() { input.focus(); }
  export function increment() { return ++count; }
  export const version = 3;
</script>

<input bind:this={input} /> {count}
```

```html
<script lang="ts">
  import Fancy from './Fancy.svelte';
  let fancy: ReturnType<typeof Fancy> | undefined = $state();
</script>

<Fancy bind:this={fancy} />
<button onclick={() => fancy?.increment()}>inc</button>
<p>{fancy?.version}</p>
```

After clicking, my run showed the counter advance and `3` rendered for the version. Facts:

- `bind:this` on a component gives you **the exports only**, not props or internals. It is `undefined` until the component mounts and set back to `null`/`undefined` when it is destroyed (Chapter 8), so guard with `?.` and read it inside effects or handlers.
- Binding directly to an export, `<Fancy bind:version />`, is **not allowed in runes mode**. The migration guide: “Use `bind:this` instead — `<A bind:this={a} />` — and access the export as `a.foo`. This change … enforces a clear separation between props and exports.” (Props are bindable only with `$bindable`.)
- Typing: `typeof Fancy` is the component *constructor* type (what you pass to `mount` or store in a variable); `ReturnType<typeof Fancy>` (or declaring `let c: Fancy` per the docs’ pattern) is the instance type for `bind:this`. See Chapter 15.
- Prefer props and callbacks to imperative exports. Reserve exports for commands that have no state representation (`focus()`, `scrollTo()`, `reset()`), which is exactly what native elements do.

## Dynamic components and recursion

As covered in Chapter 6, a capitalised variable is a live component reference. Use `Component<Props>` to constrain what may be passed:

```html
<script lang="ts">
  import type { Component } from 'svelte';
  let { Renderer, value }: { Renderer: Component<{ value: unknown }>; value: unknown } = $props();
</script>

<Renderer {value} />
```

Use `ComponentProps<typeof Other>` to derive props from an existing component. A component may render itself in two ways. The modern way is to import the file into itself:

```html
<!-- Tree.svelte -->
<script lang="ts">
  import Self from './Tree.svelte';
  type Node = { name: string; children: Node[] };
  let { node }: { node: Node } = $props();
</script>

<li>
  {node.name}
  {#if node.children.length}
    <ul>{#each node.children as c (c.name)}<Self node={c} />{/each}</ul>
  {/if}
</li>
```

I mounted this on a three-level tree and it rendered nested lists correctly. `<svelte:self>` is deprecated (`svelte_self_deprecated`) and, if used, may only appear inside `{#if}`, `{#each}`, `{#snippet}` or a component slot (`svelte_self_invalid_placement`). A self-import does not have that restriction at compile time, but unconditional self-rendering is an infinite loop at runtime, so the recursion needs a base case. For simple trees, the recursive *snippet* shown earlier avoids a file and keeps state in one place.

## `$bindable` as a contract

Bindings are covered mechanically in Chapter 8. At the component-API level, the rules are:

- A prop is bindable only if the child declares it with `$bindable()`: `let { value = $bindable() } = $props();`. In runes mode `bind:` on any other prop is not part of the contract.
- A parent need not bind. A bindable prop works as a normal one-way prop when the parent passes a plain value.
- With a **fallback** — `$bindable('fb')` — a parent that uses `bind:` must pass a defined value. If it binds to `undefined`, the runtime throws `props_invalid_value` (“Cannot do `bind:value={undefined}` when `value` has a fallback value”). I reproduced it with `let v = $state<string | undefined>(undefined)` bound to `$bindable('fb')`. The rationale from the migration guide: in Svelte 4 the default was reflected back to the parent, “resulting in wasteful additional render cycles”; now parent and child must agree on the starting value.
- Fallbacks of bindable props **are** proxied if they are objects (unlike plain destructuring defaults), so child mutations of a bindable fallback object are reactive.
- A non-bindable prop being bound is declared as `bind_not_bindable` in the runtime error list. In 5.57.2 I could not trigger it in a simple test (the value flowed one way and the build was silent), so do not rely on the runtime to catch it. Type your components (`Component<Props, Exports, Bindings>` carries a `Bindings` parameter) and run `svelte-check` in CI.
- Overuse of `$bindable` makes data flow hard to follow. Use it for genuinely two-way controls (inputs, selected value, open state).

## Design checklist for component APIs

1.  **Inputs** are plain props; **notifications** are `on*` callback props; **content** is snippets; **commands** are exports; **shared state** is context or a shared class.
2.  Type everything: `Snippet<[...]>` for content, `HTMLButtonAttributes` for wrappers, `ClassValue` for `class`, generics for list-like components.
3.  Spread `rest` last on the element, but put your own handlers *after* the spread and call the caller’s.
4.  Never mutate objects you received; never use `$state(prop)` unless you mean a snapshot.
5.  Guard every optional snippet with `?.` or `{#if}`.
6.  Use `$props.id()` for generated ids.

## Key takeaways

- `$props()` destructuring is live: reads become reads of the props object at the use site. Top-level reads capture once and trigger `state_referenced_locally`; use `$derived`.
- A child may reassign a prop temporarily; it should not mutate it. Plain objects do not update, state proxies update with `ownership_invalid_mutation`, and destructuring fallbacks are never proxied.
- Rest props are read-only (`props_rest_readonly` in dev). `children` is a reserved prop name.
- Component events are callback props. Wrappers spread `rest` so handlers flow through; local handlers go after the spread and call `props.onclick?.(e)`.
- Snippets are functions that take the anchor first, with parameters wrapped as getters (which keeps them reactive). They support defaults and destructuring but not rest parameters.
- Pass snippets explicitly, implicitly (declared inside tags) or as `children`. Optional snippets need `?.` or `{#if}`; `{@render}` of `undefined` throws `invalid_snippet`.
- Type snippets as `Snippet<[A, B]>` (tuples only). Use `generics` for related props. Export snippets from `<script module>` only if they use nothing from the instance script.
- `createRawSnippet` takes getter parameters and returns a single-element HTML string plus optional `setup`.
- Compound components use `createContext`, headless ones use snippets with arguments or `.svelte.ts` classes, polymorphic ones use `<svelte:element>`.
- `bind:this` on a component exposes its exports only; `bind:exportName` is not allowed in runes mode.
- Bindable props with fallbacks reject `bind:x={undefined}` (`props_invalid_value`).

## Review Questions

1.  Why does `let doubled = count * 2` (with `count` from `$props()`) trigger `state_referenced_locally`, and how do you fix it?

2.  What does this print after one click when the parent passes `count: 1`? What happens if the parent later sets `count` to `10`?

    ```html
    <script lang="ts">let { count }: { count: number } = $props();</script>
    <button onclick={() => count++}>{count}</button>
    ```

3.  Three components each do `obj.count++` on a prop. The parent passes (a) `{ count: 0 }` literal, (b) a `$state` object, (c) nothing, and the child declares `{ obj = { count: 0 } }`. For each, say whether the UI updates and whether a warning appears.

4.  What happens at runtime when a child assigns to a property of the `...rest` object from `$props()`? Why is a dev-only check used?

5.  When would you choose `$props.id()` over `crypto.randomUUID()` for an input id?

6.  A component has a data prop named `children` and is also given content between its tags. What goes wrong?

7.  (Multiple choice) Which is the correct Svelte 5 replacement for `dispatch('select', item)` / `on:select={...}`?

    a.  `let { select } = $props(); select(item);` with `<Comp select={...} />`
    b.  `let { onselect } = $props(); onselect?.(item);` with `<Comp onselect={...} />`
    c.  `$emit('select', item)`
    d.  `<Comp on:select={...}>` still works with `$props()`

8.  Find the bug: a `Button` wrapper has `<button onclick={() => track()} {...props}>`. Callers report their `onclick` replaces tracking. Fix it.

9.  Why can a component not use both `on:click` and `onclick`? What is the error code?

10. In the compiled output of a snippet, why are the parameters wrapped as functions (`d()`), and what does that tell you about the reactivity of snippet parameters?

11. Which of these snippet declarations is a compile error, and why?

    a.  `{#snippet a(x = 1, y = 2)}`
    b.  `{#snippet b({ id, name })}`
    c.  `{#snippet c(...rest)}`
    d.  `{#snippet d(items: string[])}`

12. What does `snippet_shadowing_prop` protect against? Write a minimal example that triggers it.

13. Explain the difference between explicit, implicit and `children` snippet passing. What does `$$slots` in the compiled output exist for?

14. A parent renders `<Card />` without content. The child does `{@render header()}`, where `header` is an optional snippet prop. What happens and how is it fixed?

15. Write the TypeScript props type for a generic `<Select>` component whose `options: T[]`, `option: Snippet<[T]>` and `onchange: (value: T) => void` must agree on `T`.

16. Why does `Snippet<string[]>` not work as a type for a snippet with parameters? What do you write instead?

17. Under what conditions may a snippet be exported from `<script module>`? What error do you get otherwise?

18. In `createRawSnippet`, what do the parameters of the callback look like and what must `render` return? Why is escaping your responsibility?

19. Compare headless components built with snippets-with-arguments against a `.svelte.ts` class with `$state` fields. When is each preferable?

20. Predict the result: a compound `Tabs` registers each `Tab` by calling `this.tabs.push(id)` inside the child’s `$effect`. What error occurs and why? Give two fixes.

21. A parent holds `let c: ReturnType<typeof Fancy> | undefined = $state();` and `<Fancy bind:this={c} />`. What can it access through `c`? Why does `<Fancy bind:version />` fail in runes mode?

22. When is `c` set to its value and when does it go back to nothing? Why do guards matter?

23. How do `typeof Comp` and `ReturnType<typeof Comp>` differ in a TypeScript context?

24. What is wrong with `<svelte:self />` in a new component, and what replaces it? Why does a self-import still need a base case?

25. With `let { value = $bindable('fb') } = $props();`, what does the parent get if it renders `<Bind />` with no `bind:`? What if it writes `<Bind bind:value={v} />` with `v` undefined?

26. Explain why `bind:` on a prop without `$bindable()` is not part of the component contract in runes mode, and how TypeScript can help catch it.

27. Design question: you are building a data table component. Which parts of its API are props, which are snippets, which are callbacks, and which (if any) are exports? Justify each.

28. Why is “mutating a prop that is a `$state` proxy owned by the parent” worse than reassigning it, even though both update the UI?
