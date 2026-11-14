# Chapter 6: Template Syntax — Markup, Events and Control Flow

A Svelte template is the part of a `.svelte` file outside `<script>` and `<style>`. The docs call it “HTML++”, and that is a fair summary: it is HTML plus a small set of curly-brace constructs, all of which the compiler turns into direct DOM operations (Chapter 2). There is no virtual DOM, no template interpreter at runtime and no expression sandbox; what you write in a `{...}` is real JavaScript evaluated in the scope of the component.

This chapter is the complete tour of that syntax for engineers who will read, review and architect Svelte code: how attributes and props are interpreted (including the quirks of nullish and boolean values), how events work now that `on:` is legacy, what event delegation actually does to your handlers and your third-party listeners, how each of the logic blocks behaves, where declaration tags and `{@const}` fit, how whitespace is collapsed, and how `class` and `style:` produce strings. Directives that belong to later chapters (`bind:` in Chapter 8, `use:`/`{@attach}` in Chapter 9, `transition:` in Chapter 11) are only mentioned here. Snippets and `{@render}` are covered in Chapter 7.

All examples use runes mode (see Chapter 1) and TypeScript. Where I show “what the compiler produces”, the output was generated with `svelte@5.57.2` and is illustrative: internals are private and can change in any patch release.

## Tags: elements, components and the lowercase trap

A lowercase tag such as `<div>` denotes an HTML element. A capitalised tag or a tag using dot notation (`<Widget>`, `<item.component>`) denotes a component. The rule is purely lexical and is applied by the compiler, not at runtime:

```html
<script lang="ts">
  import Widget from './Widget.svelte';
  import * as ui from './ui';
  let { item }: { item: { component: typeof Widget } } = $props();
</script>

<Widget />
<ui.Card />
<item.component />
```

If you import a component under a lowercase name and use it as `<widget />`, Svelte treats it as an HTML element and emits `component_name_lowercase` (“`<foo>` will be treated as an HTML element unless it begins with a capital letter”). Dot notation is how you render a component that lives in a variable, a namespace import or an object property, which brings us to dynamic components.

### Dynamic components need no special syntax

In Svelte 4 you needed `<svelte:component this={X}>` to re-render when `X` changed. In runes mode, any capitalised variable (or dot-notation path) is a live reference: if the variable is `$state`, replacing it swaps the component.

```html
<script lang="ts">
  import Home from './Home.svelte';
  import Settings from './Settings.svelte';

  const views = { home: Home, settings: Settings } as const;
  let current = $state<keyof typeof views>('home');
  const View = $derived(views[current]);
</script>

<nav>
  <button onclick={() => (current = 'home')}>Home</button>
  <button onclick={() => (current = 'settings')}>Settings</button>
</nav>

<View />
```

`<svelte:component>` still works but is deprecated in runes mode (`svelte_component_deprecated`). Components are functions, and functions are never proxied by `$state`, so storing one in state needs no special care. (If you keep components in an object literal inside `$state({...})`, the object is proxied but the component functions are not.) The thing to be careful about is capitalisation: `const view = $derived(...)` followed by `<view />` renders an HTML element named `view`.

### `<svelte:element>` for unknown tags

When the tag name is data (from a CMS, a heading level prop), use `<svelte:element this={expression}>`:

```html
<script lang="ts">
  import type { Snippet } from 'svelte';
  let { level = 2, children }: { level?: 1 | 2 | 3 | 4 | 5 | 6; children: Snippet } = $props();
  const tag = $derived(`h${level}`);
</script>

<svelte:element this={tag} class="heading">
  {@render children()}
</svelte:element>
```

Rules, all from the docs and the compiler:

- `this` must be an expression. `this="div"` compiles but warns (`svelte_element_invalid_this`: “Using a string attribute value will cause an error in future versions of Svelte”). Always write `this={'div'}`.
- If `this` is nullish, the element and its children are not rendered. This makes `this={href ? 'a' : undefined}` a way to conditionally wrap.
- The only supported binding is `bind:this`; built-in bindings such as `bind:value` do not work because the compiler cannot know what element it will be.
- If `this` is a void element (`br`, `hr`, `input`) and the element has children, dev mode throws. On the server, an invalid tag name raises `dynamic_element_invalid_tag`. `this` must be a valid DOM tag: `#text` or `svelte:head` will not work.
- Namespace is inferred from the surroundings (inside an `<svg>` you get SVG elements), but you can force it with `xmlns="http://www.w3.org/2000/svg"`.

Chapter 7 uses this element to build polymorphic wrapper components.

## Attributes and props

### Values, booleans and nullish

By default, attributes behave like their HTML counterparts, and values can be unquoted (`<input type=checkbox />`), quoted, or JavaScript expressions. A value that mixes text and expressions must be quoted (`href="page/{p}"`). Without the quotes, runes mode throws `attribute_unquoted_sequence` (“Attribute values containing `{...}` must be enclosed in quote marks, unless the value only contains the expression”). That was legal in Svelte 4 (`prop=this{is}valid`) and was removed as a footgun.

Two rules govern how a value is serialised to the DOM:

1.  **Boolean attributes** (`disabled`, `checked`, `hidden`, `required`…) are present if the value is truthy and absent if falsy.
2.  **All other attributes** are present unless the value is `null` or `undefined`.

```html
<input required={false} placeholder="Not required" />
<div title={null}>No title attribute</div>
<div data-count={0}>data-count="0" is present</div>
<div aria-hidden={false}>aria-hidden="false" is present</div>
```

The last line is the one that bites people: `false` is not nullish, so `aria-hidden={false}` renders `aria-hidden="false"`, which is exactly what ARIA wants. If you instead need the attribute removed, pass `undefined` (`aria-hidden={hidden || undefined}`).

> **Note:** Svelte sets *properties* rather than attributes where the DOM exposes them, so `value`, `checked` and `selected` go through the property. The “present or absent” description is the observable result for attributes serialised to markup (SSR and static templates).

### Quoting a single expression

`<button disabled="{n !== 42}">` parses exactly like `disabled={n !== 42}` today. The docs warn that in Svelte 6 a quoted single expression “will cause the value to be coerced to a string”. As a first step you get the `attribute_quoted` compile warning, but note where it fires. I compiled both forms with 5.57.2:

- `<C prop="{n}" />` on a **component** (or custom element): warning `attribute_quoted` (“Quoted attributes on components and custom elements will be stringified in a future version of Svelte”).
- `<div data-x="{n}">` on a plain element: no warning, because the attribute is a string in the DOM anyway.

So the actual risk is on component props: a quoted number would silently become a string in Svelte 6. Lint for it now.

### Shorthand and spread

`name={name}` may be written `{name}`, for both elements and components. Spread attributes pass many at once, and **order matters**: later wins.

```html
<script lang="ts">
  import Widget from './Widget.svelte';
  const things = { a: 'from things', c: 'from things' };
</script>

<!-- a="from things" (spread overrides earlier a="b"), c="d" (later literal overrides spread) -->
<Widget a="b" {...things} c="d" />
```

Spread has a runtime cost. A spread forces the compiler to treat the whole attribute set as dynamic: instead of a handful of targeted `set_attribute` calls it uses a helper that diffs the whole object each time. This is fine for wrapper components (Chapter 7) but avoid spreading large objects onto hot elements in long lists.

### Comments

HTML comments work anywhere in markup. Three kinds are special:

```html
<!-- svelte-ignore a11y_autofocus -->
<input bind:value={name} autofocus />

<!--
@component
A greeting card. Shown on hover in editors.
- Usage: `<Card name="Aretha" />`
-->
<script lang="ts">
  let { name }: { name: string } = $props();
</script>

<div
  // JavaScript line comments are allowed between attributes (5.53)
  data-foo="bar"
>
  hello {name}
</div>
```

- `<!-- svelte-ignore code1, code2 -->` silences warnings for the next block of markup. Codes use underscores (`a11y_autofocus`, `css_unused_selector`, `state_referenced_locally`); a parenthesised reason can follow: `<!-- svelte-ignore a11y_missing_attribute (decorative image) -->`. Treat each one as a code-review flag.
- `<!-- @component ... -->` becomes the hover documentation for the component in language-server-enabled editors. Markdown is allowed.
- Since 5.53, JavaScript-style comments may appear between attributes inside a tag.

By default comments are stripped from client output; `preserveComments` in the compiler options keeps them. Do not strip comments from *server-rendered* HTML if you hydrate it: Svelte 5 uses special comment markers (`<!--[-->`, `<!--]-->`) for hydration (Chapter 14).

## Text expressions

`{expression}` interpolates a JavaScript expression as text. The value is coerced to a string and **escaped**, except that `null` and `undefined` render as the empty string. That last point is a Svelte 5 change: Svelte 4 printed “null” and “undefined”.

```html
<script lang="ts">
  let name: string | null = $state(null);
  const flag = false;
</script>

<p>[{name}] [{undefined}] [{flag}] [{0}] [{NaN}]</p>
<!-- <p>[] [] [false] [0] [NaN]</p> -->
```

Only nullish values vanish. `false`, `0` and `NaN` print. A regular-expression literal inside an expression must be wrapped in parentheses so the parser does not confuse its braces with block syntax: `{(/^[a-z]+$/).test(value) ? 'ok' : 'bad'}`. To write a literal brace in markup use an entity: `&lbrace;` `&lcub;` `&#123;` for `{` and `&rbrace;` `&rcub;` `&#125;` for `}`.

Expressions in templates must be free of side effects. Writing to `$state` inside a template expression throws `state_unsafe_mutation` at runtime. Put writes in event handlers or effects (Chapter 4).

Template expressions are re-evaluated when their dependencies change, and only they are. In the compiled client output for `<p>{a} + {b}</p>`, the paragraph’s text is one text node set by one `$.template_effect`; expressions in separate nodes get their own setters or are grouped (Chapters 2 and 5 show the output; do not depend on the function names). A consequence for design: there is no “render function” that re-runs; only the expression that read the changed signal runs again.

### `{@html}`

`{@html expr}` inserts raw HTML:

```html
<script lang="ts">
  let { article }: { article: { html: string } } = $props();
</script>

<article>
  {@html article.html}
</article>

<style>
  article :global {
    a { color: hotpink; }
    img { width: 100%; }
  }
</style>
```

Facts you must internalise:

1.  **XSS.** The string is not escaped and not sanitised. The docs: “Never render unsanitized content.” Sanitise on the server or with a library like DOMPurify before it reaches `{@html}`. Svelte supports Trusted Types (`TrustedHTML` values are accepted by `{@html}` since 5.52, and Trusted Types are used for HTML handling where supported since 5.51), so you can enforce a CSP `require-trusted-types-for 'script'` policy and sanitise inside a Trusted Types policy. Note the compiler option `fragments: 'html'` (the default) is incompatible with that CSP directive and `fragments: 'tree'` is the alternative (Chapter 2).
2.  **Valid standalone HTML.** `{@html '<div>'}content{@html '</div>'}` does not work; each `{@html}` is parsed as an independent fragment.
3.  **It does not compile Svelte.** `{@html '<Button />'}` yields an unknown HTML element named `button` (HTML is case-insensitive), not your component.
4.  **It is invisible to scoped CSS.** The inserted nodes never receive the component’s hash class, so selectors like `article a` are pruned as unused. Use `:global` (as above; the nested `article :global { ... }` form is the idiomatic one). Chapter 10 explains why.
5.  **Hydration mismatches are not repaired.** In Svelte 4 a differing `{@html}` between server and client was repaired. In Svelte 5 the compiler assumes the markup is unchanged and dev mode warns (`hydration_html_changed`). If server and client really can differ, the migration guide shows a stash-and-reset trick in an `$effect`.

`{@html}` re-runs whenever its expression changes, and it replaces the entire fragment each time. Do not use it for frequently-changing content.

## Events

### Events are attributes

Since Svelte 5 an event listener is an attribute beginning with `on`:

```html
<script lang="ts">
  let count = $state(0);
  function onclick(e: MouseEvent) {
    count += e.shiftKey ? 10 : 1;
  }
</script>

<button {onclick}>clicks: {count}</button>
```

Because it is “just an attribute”:

- the shorthand `{onclick}` works,
- spread works: `<button {...props}>` forwards `onclick`, `onkeydown`… from a props object,
- the name is **case sensitive**: `onclick` listens to `click`, `onClick` listens to the event named `Click`. This is deliberate so that custom events with capital letters can be listened to.
- a string value (`onclick="alert(1)"`) is a compile error (`attribute_invalid_event_handler`: “Event attribute must be a JavaScript expression, not a string”).
- you cannot mix `on:click` and `onclick` in the same component (`mixed_event_handler_syntaxes`).

There are **no modifiers** in the attribute form. `on:click|preventDefault|once` has no direct equivalent; you call `event.preventDefault()` yourself, wrap the handler (`once` is three lines of code), or, for the one modifier with a different mechanism, use a suffix: capture-phase listeners are registered by appending `capture` to the attribute name, `onclickcapture={...}`. The compiler turns that into a non-delegated listener with the capture flag (`$.event('click', button, handler, true)` in 5.57.2 output).

### Ordering: bindings before event attributes

> “Timing-wise, event attributes always fire after events from bindings (e.g. `oninput` always fires after an update to `bind:value`).”

I verified this: in a component with `<input bind:value oninput={() => log.push(value)} />` the handler sees the already-updated value. That guarantee lets you write validation or formatting in `oninput` knowing the binding has synchronised. (Chapter 8 covers function bindings, which are usually the better tool for transformations.)

### Passive touch handlers

`ontouchstart` and `ontouchmove` are registered as passive listeners, matching browser defaults, so scrolling is never blocked by waiting for `preventDefault()`. If you really need to prevent default in a touch handler, you must register the listener yourself with `on` from `svelte/events` (see below) and pass `{ passive: false }`, typically inside an attachment (Chapter 9).

### Event delegation

To save memory and listeners, Svelte registers **one listener per delegated event type at the application root** (the `target` passed to `mount`) and, on each event, walks the composed path from the target upward invoking whichever handlers were declared with attributes. The delegated events are:

`beforeinput`, `click`, `change`, `dblclick`, `contextmenu`, `focusin`, `focusout`, `input`, `keydown`, `keyup`, `mousedown`, `mousemove`, `mouseout`, `mouseover`, `mouseup`, `pointerdown`, `pointermove`, `pointerout`, `pointerover`, `pointerup`, `touchend`, `touchmove`, `touchstart`.

Everything else (`focus`, `blur`, `mouseenter`, `scroll`, `submit`, `load`, `error`, media events, custom events) is attached directly with `addEventListener`. Here is the compiler output for a button with `onclick`, `onfocus` and `onmouseenter` (illustrative, 5.57.2):

```js
$.delegated('click', button, () => $.update(n));   // no listener on the button itself
$.event('focus', button, () => {});                // real addEventListener
$.event('mouseenter', button, () => {});
// ...
$.delegate(['click']);                             // module level: root listener for 'click'
```

Delegation is invisible until you mix it with listeners you add yourself. I ran three experiments against 5.57.2 in jsdom to see the exact behaviour.

**Experiment 1: native listeners on the same or nearby elements.** A `<div onclick>` containing `<button onclick>`, plus a native `button.addEventListener('click', ...)` added in an effect. Click log:

```text
native-on-button | button handler | div (delegated)
```

The native listener on the target fires first (it is a real listener in the target phase). Then, when the event reaches the root, Svelte runs the declared handlers in bubbling order, innermost first. If you expect a *native* listener on a *parent* to fire after the button’s declared handler, you will be disappointed: any listener you add yourself inside the app root runs before declared handlers lower in the tree, in both capture and bubble phases, because declared handlers do not run until the event reaches the root.

**Experiment 2: `stopPropagation` in a manual listener.** A wrapper `<div>` with a native listener calling `e.stopPropagation()`, containing a `<button onclick>`:

```text
click button in A:  native A            (the button's own handler never ran)
```

The event was stopped before it reached the root, so the delegated handler is never invoked. This is the classic “my third-party widget swallowed my click” bug. In a second wrapper, B, I swapped the manual `addEventListener` for `on()` from `svelte/events`:

```ts
import { on } from 'svelte/events';

$effect(() => on(wrapper, 'click', (e) => { e.stopPropagation(); }));
```

and the log becomes `B button handler | on() B`: the button’s declared handler runs first (as it would if it were a native listener on a deeper element), then the `on` handler, and `stopPropagation` is honoured for everything above. `on` returns a function that removes the listener, which is why `$effect(() => on(...))` is a complete lifecycle.

**Experiment 3: manual dispatch.** `button.dispatchEvent(new MouseEvent('click'))` did nothing visible; adding `{ bubbles: true }` triggered the handler. Delegated events must bubble to reach the root.

Summary of rules for delegated events:

1.  Dispatch synthetic delegated events with `bubbles: true`.
2.  Never call `stopPropagation()` from a raw `addEventListener` inside the app root if you want declared handlers above or below to run. Use `on`.
3.  Inside the app root, ordering between declared and raw handlers is not DOM-natural. Prefer `on` for anything you add imperatively.
4.  Calling `event.stopPropagation()` in a **declared** handler of a delegated event works for the other declared handlers: the runtime walks the event path and stops as soon as the event’s `cancelBubble` is set. Because that walk happens in the root listener, native listeners on elements inside the root have already run by then, and listeners above the mount root never see the event, since propagation was stopped at the root.
5.  The root listener belongs to the `mount` target, so each mounted app (or shadow root) gets its own.

> **Senior tip:** If a bug report says “click handler doesn’t fire inside the third-party widget”, the first thing to check is whether the widget calls `stopPropagation` on a delegated event type. If you cannot patch it, switch the handler to a non-delegated route, for example use a capture-phase attribute (`onpointerdowncapture`, a real non-delegated listener that runs before the bubble-phase `stopPropagation`), or register the handler with `on()`.

### `on` from `svelte/events`

```ts
function on(
  target: Window | Document | HTMLElement | MediaQueryList | EventTarget,
  type: string,
  handler: (event: Event) => any,
  options?: AddEventListenerOptions
): () => void
```

Besides preserving ordering with declared handlers and handling `stopPropagation` correctly, it is the supported way to register listeners with options such as `{ passive: false }` or `{ once: true }`. Chapter 9 covers it in the context of attachments and actions.

## Logic blocks

### `{#if}`

```html
{#if porridge.temperature > 100}
  <p>too hot!</p>
{:else if 80 > porridge.temperature}
  <p>too cold!</p>
{:else}
  <p>just right!</p>
{/if}
```

Blocks may wrap text as well as elements. Each branch is its own effect scope: when the condition flips, the previous branch’s DOM and effects are destroyed (after outros, see Chapter 11) and the new branch is created from its template. The condition is re-evaluated when its dependencies change, but the branch is only replaced when the *selected branch* changes. If `{#if user}` is truthy and `user` changes from one object to another, the branch is not re-created; expressions inside simply update.

### `{#each}`

```html
{#each items as item, i (item.id)}
  <li>{i + 1}: {item.name} x {item.qty}</li>
{:else}
  <li>No items</li>
{/each}
```

Details worth knowing:

- **What can be iterated:** arrays, array-likes (anything with `length`) and iterables (`Map`, `Set`, generators). Internally Svelte converts via `Array.from`. `null`/`undefined` behave as an empty array (so `{:else}` renders). An iterable is consumed once per evaluation, so a generator function result cannot be re-read; use a derived array.
- **Index:** the second identifier is the index, as in `map`. It is a reactive value.
- **Destructuring and rest** in the item pattern work: `{#each items as { id, name, qty }, i (id)}`, `{#each objects as { id, ...rest }}`, `{#each pairs as [id, ...rest]}`. Binding to a rest object (`bind:value={rest.x}`) triggers `bind_invalid_each_rest` because the rest object is a copy. The docs add: “Avoid destructuring if you need to mutate the item”.
- **`{:else}`** renders when the list is empty (or null).
- **Each without an item** (5.4): `{#each { length: 8 }, rank}` repeats the body n times; the object `{ length: 8 }` is an array-like. It is the idiomatic way to render a grid or skeleton rows:

```html
<div class="board">
  {#each { length: 8 }, rank}
    {#each { length: 8 }, file}
      <div class={{ black: (rank + file) % 2 === 1 }}></div>
    {/each}
  {/each}
</div>
```

#### Keyed each blocks: when and how

Without a key, Svelte updates **by position**: item *i* in the new list reuses DOM node *i*. Adding an item at the front then rewrites every row’s text and leaves component state (focus, input contents, local `$state`) attached to the wrong data. With a key, Svelte matches new items to existing rows by key and inserts, moves or deletes DOM nodes. The key expression goes in parentheses after the item/index:

```html
{#each todos as todo (todo.id)}
  <TodoRow {todo} />
{/each}
```

Rules:

- Keys must uniquely identify items. Duplicate keys throw `each_key_duplicate` at runtime (I reproduced this in dev mode with two items sharing `id: 1`).
- Keys should be stable primitives (strings, numbers). The docs: “The key can be any object, but strings and numbers are recommended since they allow identity to persist when the objects themselves change.” A key function that returns something different each time it is called for the same item (for example a freshly created object) is “volatile”. In dev mode the runtime calls the key function twice per item and throws `each_key_volatile` (“Keyed each block has key that is not idempotent”) if the results differ; in production this check is skipped.
- “Do not use the index as a key.” It is equivalent to no key.
- Keys are required for `animate:` (Chapter 11) and strongly advisable when rows contain stateful components or inputs.
- Not keying is *faster* for pure text lists whose items are replaced wholesale, because it avoids the reconciliation. Key when identity matters, not by reflex.

With `$state` arrays, the each block reads the array and the items it needs. Pushing to the array re-runs the block’s list expression; setting `todos[3].done = true` only updates the expressions in row 3 that read `done`, because `todo` is a reference to the proxied item and the field is its own signal (Chapter 3).

### `{#key}`

`{#key expr}...{/key}` destroys and recreates its contents whenever `expr` changes (by reference/equality). Use it to reinitialise a component, or to replay a transition:

```html
{#key currentUserId}
  <Profile id={currentUserId} />
{/key}
```

This is the blunt instrument. Prefer making the child react to its props (`$derived`, effects keyed on props). The cost is a complete teardown and re-creation, including losing child state and focus.

### `{#await}`

```html
<script lang="ts">
  let promise = $state(fetch('/api/user').then((r) => r.json() as Promise<{ name: string }>));
</script>

{#await promise}
  <p>loading...</p>
{:then user}
  <p>Hello {user.name}</p>
{:catch error}
  <p>Failed: {(error as Error).message}</p>
{/await}
```

Short forms: `{#await promise then value}...{/await}` (skip pending), `{#await promise catch error}...{/await}` (only the error), and `{#await import('./Heavy.svelte') then { default: Heavy }}<Heavy />{/await}` for lazy components.

Behaviours:

- If the expression is not a promise, only the `:then` branch is rendered, including on the server.
- On the server **only the pending branch** is rendered. I rendered a component with three await blocks using `svelte/server`: the promise block gave `<p>pending</p>`, a plain value `5` gave `<p>plain 5</p>`, and the catch-only block rendered nothing. The server does not wait for the promise (in classic, non-experimental mode), so data you need in the HTML must be loaded before rendering (in an application framework, in its load function). Chapter 13 covers the experimental `await` expressions that change this.
- When the expression’s value changes to a new promise, the block shows the pending branch again and the older promise’s result is ignored if it settles late. There is no automatic cancellation of the underlying request: pair it with `getAbortSignal()` (Chapter 4) if cancellation matters.
- `{#await}` is a good fit for one-off lazy loads. For repeated data fetching with loading and error states consider the experimental async features (Chapter 13) or a data layer.

## Local declarations

Sometimes a template needs an intermediate value. Svelte offers two syntaxes.

### Declaration tags: `{const}` and `{let}` (5.56)

Declaration tags define variables inside markup:

```html
<script lang="ts">
  let boxes = [{ width: 10, height: 10 }, { width: 15, height: 15 }];
</script>

{#each boxes as box}
  {const area = box.width * box.height}
  {const label = `${box.width} × ${box.height} = ${area}`}
  <p>{label}</p>
{/each}
```

They may appear anywhere in the component, may reference anything in scope, and are visible to **siblings that follow** and their descendants (lexical scope). Shadowing in nested elements is allowed:

```html
{const hello = 'hello'}
{hello}            <!-- hello -->
<div>
  {const hello = 'hi'}
  {hello}          <!-- hi -->
  <div>{hello}</div> <!-- hi -->
</div>
{hello}            <!-- hello -->
```

Unlike `{@const}`, they can hold reactive state. `$state` and `$derived` are legal inside them, which makes them a way to give a block its own local state without extracting a component:

```html
<script lang="ts">
  let user = $state({ name: 'Svelte' });
  let editing = $state(false);
</script>

<p>Hello {user.name}</p>
<button onclick={() => (editing = true)}>edit name</button>

{#if editing}
  {let name = $state(user.name)}
  {const greeting = $derived(`Hello ${name}`)}

  <input bind:value={name} />
  <p>{greeting}</p>
  <button onclick={() => { user.name = name; editing = false; }}>save</button>
{/if}
```

I ran this in jsdom: typing “Ada” updates the greeting to “Hello Ada” while `user.name` stays “Svelte” until save; after saving, the `{#if}` branch is destroyed and `user.name` is “Ada”. The local `name` is created fresh every time the branch is created, which is exactly the “draft state” pattern.

Compiler errors you can hit (all verified with 5.57.2):

| Code | Trigger |
|------------------------------------|------------------------------------|
| `declaration_tag_invalid_type` | `{var x = 1}` (“Declaration tags must be `let` or `const` declarations”) |
| `declaration_duplicate` | `{const a = 1}{const a = 2}` in the same scope |
| `declaration_tag_no_legacy_mode` | used in a component that is not in runes mode |

Use `{const}` for derived presentation values (labels, formatting). A plain `{const x = expr}` is re-evaluated when its dependencies change like any template expression; wrap in `$derived(...)` when the expression is expensive or you want it memoised.

### `{@const}` (legacy)

`{@const area = box.width * box.height}` predates declaration tags and is now documented as legacy. It is limited to being an immediate child of `{#if}`, `{:else if}`, `{:else}`, `{#each}`, `{:then}`, `{:catch}`, `{#snippet}`, `<svelte:fragment>`, `<svelte:boundary>` or a component; elsewhere you get `const_tag_invalid_placement`. It cannot be reassigned (stricter validation since Svelte 5). It is fine to meet in existing code; new code should use `{const}`. (`await` inside `{@const}` has been supported since 5.38 with the experimental async flag.)

## `{@debug}`

`{@debug user, order}` logs the listed variables whenever any changes and pauses if devtools are open. It accepts only a comma-separated list of identifiers; `{@debug user.firstname}` fails with `debug_tag_invalid_arguments`. `{@debug}` with no arguments inserts a bare `debugger` statement that triggers on any state change. Dev-only. For tracing *why* something re-ran, `$inspect.trace()` (Chapter 4) is more precise.

## Whitespace

Svelte 5 has two simple rules. Whitespace between nodes collapses to a single space, and whitespace at the start and end of a tag is removed entirely, with exceptions such as `<pre>`. The consequence is that `<p>foo<span> - bar</span></p>` renders `foo- bar` (browsers would render `foo - bar`). Move the space outside the span (`foo <span>- bar</span>`) or write it as an expression (`<span>{' '}- bar</span>`). You can disable trimming with the `preserveWhitespace` compiler option or `<svelte:options preserveWhitespace />`.

This matters most for inline-formatted text and for `inline-block` layouts where the gap between elements is significant.

## HTML structure strictness

Svelte 5 refuses to compile markup that the browser would “repair”, because repair would silently desynchronise the DOM that the compiler assumes. Verified errors:

```html
<table><tr><td>hi</td></tr></table>
<!-- node_invalid_placement: `<tr>` cannot be a child of `<table>`. `<table>` only allows these
     children: `<caption>`, `<colgroup>`, `<tbody>`, `<thead>`, `<tfoot>`, `<style>`, `<script>`, `<template>` -->

<p><div>x</div></p>
<!-- element_invalid_closing_tag_autoclosed: `</p>` attempted to close element that was already
     automatically closed by `<div>` (cannot nest `<div>` inside `<p>`) -->
```

Also, self-closing non-void tags (`<div />`) compile, but warn with `element_invalid_self_closing_tag` because HTML ignores the slash. Implicitly closed elements warn with `element_implicitly_closed` (5.32). On the server, `node_invalid_placement_ssr` is the warning variant. All of these are about keeping SSR output and client parsing identical so hydration works.

## `class` and `style:`

### The `class` attribute

A primitive is set as is. Since 5.16, `class` also accepts objects and arrays, converted with [clsx](https://github.com/lukeed/clsx):

```html
<script lang="ts">
  let { cool, faded, large }: { cool: boolean; faded: boolean; large: boolean } = $props();
</script>

<div class={{ cool, lame: !cool }}>object: truthy keys are added</div>
<div class={['base', faded && 'saturate-0 opacity-50', large && 'scale-200']}>array: truthy values</div>
<div class={['base', { active: cool }, ['nested', large && 'big']]}>arrays and objects nest</div>
```

Arrays can contain arrays and objects, which clsx flattens. In a verified run, `class={[n>0 && 'pos', {big: n>5}]}` with `n = 0` produced no class attribute at all (an empty result omits it), while `class={false}` produced `class="false"`.

That last behaviour is a documented historical wart: “falsy values (like `false` and `NaN`) are stringified (`class="false"`), though `class={undefined}` (or `null`) cause the attribute to be omitted altogether. In a future version of Svelte, all falsy values will cause `class` to be omitted.” Use `undefined` or an array/object form today.

Component authors accept a `class` prop and merge it:

```html
<!-- Button.svelte -->
<script lang="ts">
  import type { ClassValue } from 'svelte/elements';
  import type { Snippet } from 'svelte';
  let { class: klass, children, ...rest }: { class?: ClassValue; children: Snippet; [k: string]: unknown } = $props();
</script>

<button {...rest} class={['btn', klass]}>{@render children()}</button>
```

```html
<!-- usage -->
<Button class={{ 'bg-blue-700 sm:w-1/2': useTailwind }}>Accept</Button>
```

`ClassValue` (`string | clsx.ClassArray | clsx.ClassDictionary`, exported from `svelte/elements` since 5.19) is the right prop type, and `HTMLAttributes['class']` already uses it. This composition replaces the `class:` directive, which the docs now discourage: `class:cool={cool}` and `class:cool` (shorthand) still work, but “the attribute is more powerful and composable”. `class:` cannot be spread onto components or merged with a `class` prop.

### The `style:` directive

`style:` sets individual CSS properties:

```html
<div
  style:color={myColor}
  style:width="12rem"
  style:background-color={dark ? 'black' : 'white'}
  style:--columns={columns}
  style:opacity|important={0.5}
>
```

Shorthand `style:color` works when a variable of that name exists. `|important` adds `!important`. **Directives win over the `style` attribute, even over its `!important`**: `<div style:color="red" style="color: blue !important">` is red. Nullish values remove the property, and CSS custom properties (`--x`) are supported. For many properties at once, build a string or use several directives; there is no object form for `style` in 5.57. The directive form updates only the one property when its value changes, instead of rewriting the whole `style` attribute.

## Customizable `<select>` and `<template>`

Svelte 5.47 added support for the browser’s customizable `<select>` (rich content inside `<option>`, `<selectedcontent>`). Svelte accounts for how browsers parse such content (it feature-tests support at runtime, using `TrustedHTML` where required). As an author you write the markup the platform specification describes, opt in with CSS (`appearance: base-select`), and Svelte’s `<select bind:value>` continues to work (Chapter 8 for bindings). Since 5.18, `<template>` elements may contain any child, so patterns like declarative shadow DOM (`<template shadowrootmode="open">`) compile.

## A tour of diagnostics from this chapter

| Code | Kind | When |
|------------------------|------------------------|------------------------|
| `attribute_unquoted_sequence` | error | `prop=a{b}c` |
| `attribute_quoted` | warning | `<Comp prop="{n}">` |
| `attribute_invalid_event_handler` | error | `onclick="..."` |
| `mixed_event_handler_syntaxes` | error | `on:click` + `onclick` in one component |
| `node_invalid_placement` | error | browser would repair the DOM |
| `element_invalid_self_closing_tag` | warning | `<div />` |
| `component_name_lowercase` | warning | lowercase import used as tag |
| `const_tag_invalid_placement` | error | `{@const}` outside an allowed parent |
| `debug_tag_invalid_arguments` | error | `{@debug a.b}` |
| `bind_invalid_each_rest` | warning | binding to an each-rest object |
| `each_key_duplicate` | runtime error | duplicate keys |
| `svelte_element_invalid_this` | warning | `this="div"` string |

## Key takeaways

- Capitalised or dot-notation tags are components; in runes mode a state variable holding a component is enough for dynamic rendering, and `<svelte:component>` is deprecated.
- Boolean attributes follow truthiness; all other attributes are omitted only for `null`/`undefined`. `aria-hidden={false}` renders `"false"`.
- Concatenation requires quotes; a quoted single expression on a *component* prop warns because it will become a string in Svelte 6.
- Events are `on...` attributes, case-sensitive, with no modifiers. `capture` is a suffix, touch start/move are passive, and bindings fire before event attributes.
- Twenty-three event types are delegated to the app root. Manual `addEventListener` inside the root fires before declared handlers and `stopPropagation` there blocks them; use `on` from `svelte/events`, and give synthetic events `bubbles: true`.
- `{@html}` is unsanitised, standalone, uncompiled, unscoped and not repaired on hydration mismatch.
- Key each blocks by a stable unique primitive whenever rows have identity or state; never by index. `{#key}` recreates everything.
- `{#await}` renders only the pending branch on the server; non-promises go straight to `:then`.
- Declaration tags (`{const}`, `{let}`, 5.56) replace `{@const}` and, unlike it, may hold `$state` and `$derived`.
- Whitespace collapses and trims at tag edges; HTML the browser would repair is a compile error.
- Prefer `class={[...]}` / `ClassValue` over `class:`; `style:` directives beat the `style` attribute.

## Review Questions

1.  Why does the compiler treat `<view />` as an HTML element even though `view` is a variable holding a component? What are the two ways to write it correctly?

2.  What does each line render?

    ```html
    <div data-a={0} data-b={false} data-c={null} hidden={false} aria-hidden={false}></div>
    ```

3.  (Multiple choice) In runes mode, which of these compiles without error?

    a.  `<a href=/user/{id}>profile</a>`
    b.  `<a href="/user/{id}">profile</a>`
    c.  `<Comp prop=this{x}end />`
    d.  `<button onclick="save()">save</button>`

4.  Which of `<C prop="{n}" />` and `<div data-x="{n}">` produces the `attribute_quoted` warning, and why is the other one harmless?

5.  Given `<Widget a="b" {...things} c="d" />` where `things = { a: 1, c: 2 }`, what values do `a` and `c` receive?

6.  What does this print, and what changed from Svelte 4?

    ```html
    <script lang="ts">let a: string | null = null; let b = false;</script>
    <p>[{a}][{b}][{undefined}][{0}]</p>
    ```

7.  Explain the order in which `oninput` and `bind:value` update on the same input, and why this ordering is useful.

8.  Why is `onClick={...}` not a typo-tolerant alias for `onclick`? Give a use case for the case-sensitivity rule.

9.  How do you register a capture-phase click listener declaratively? Is the resulting listener delegated?

10. Find the bug: a team adds a drag library that calls `event.stopPropagation()` in a native `pointerdown` listener on a container. Buttons inside it, declared with `onpointerdown`, no longer respond. Explain why and give two fixes.

11. A test dispatches `button.dispatchEvent(new MouseEvent('click'))` and the `onclick` handler never runs, although `button.click()` works. Why?

12. List four event types that are *not* delegated. How does the compiled output differ for a delegated vs a non-delegated handler?

13. Given a native `addEventListener('click')` on `<button>` and `onclick` attributes on both the button and its parent div, in what order do the three handlers run, and why?

14. When would you need `on()` from `svelte/events` instead of an `ontouchmove` attribute?

15. List five consequences of `{@html}`’s design (security, parsing, styling, hydration, performance).

16. Style problem: `<article>{@html md}</article>` with `article a { color: red }` has no effect. What warning appears and what is the fix?

17. (Multiple choice) What happens when two items in a keyed `{#each todos as t (t.id)}` share the same `id`?

    a.  The second is silently dropped
    b.  `each_key_duplicate` error
    c.  Svelte falls back to index keys
    d.  A compile-time error

18. Write the markup to render a 3×3 grid of cells without an array variable. Which Svelte version introduced the feature?

19. Why is it dangerous to use the index as the key, and when is *no* key the better choice?

20. What does `{#await}` render on the server for (a) a pending promise, (b) a resolved non-promise value, (c) `{#await p catch e}`?

21. Predict the output:

    ```html
    {const x = 1}
    <div>
      {const x = 2}
      {x}
      <span>{x}</span>
    </div>
    {x}
    ```

22. Rewrite this with declaration tags and explain what extra capability they have:

    ```html
    {#each rows as row}
      {@const total = row.qty * row.price}
      <td>{total}</td>
    {/each}
    ```

23. Which compile error is produced by `{var a = 1}`, by `{const a = 1}{const a = 2}`, and by using `{const}` in a component with `<script>` that uses `export let`?

24. What does `<p>foo<span> - bar</span></p>` render in Svelte 5, and how do you restore the space?

25. Given `class={['btn', { active }, size === 'lg' && 'btn-lg']}` and `active = false`, `size = 'sm'`, what is the class attribute? What if the whole value is `false`?

26. `<div style:color="red" style="color: blue !important">` — what colour, and why?

27. Design question: you are building `<Heading level={n}>`. Compare implementing it with `{#if}` chains, with ``<svelte:element this={`h${level}`}>``, and with a lookup of component references. State the trade-offs.

28. Why does Svelte refuse to compile `<table><tr>...</tr></table>`, and what category of runtime problem does this prevent?
