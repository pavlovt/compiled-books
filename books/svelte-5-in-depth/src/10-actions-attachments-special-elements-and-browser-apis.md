# Chapter 9: Actions, Attachments, Special Elements and Browser APIs

Sooner or later a component has to touch something Svelte does not own: a third-party widget that wants a raw DOM node, a canvas, `window` and `document`, a `ResizeObserver`, a media query. Svelte 5 gives you a layered toolbox for this. **Attachments** (`{@attach}`, 5.29) and the older **actions** (`use:`) hook a function to an element’s lifetime. **Special elements** (`<svelte:window>`, `<svelte:document>`, `<svelte:body>`, `<svelte:head>`, `<svelte:options>`) attach listeners, bindings and markup to global objects without cleanup code. The **`on`** function from `svelte/events` registers listeners that cooperate with Svelte’s event delegation. And **`createSubscriber`** plus the classes in `svelte/reactivity` and `svelte/reactivity/window` turn any event-driven source into a reactive value that works in templates, `$derived` and `$effect`.

This chapter treats each tool precisely, shows when each is the right choice, and ends by writing a reusable reactive primitive from scratch. Events and delegation were introduced in Chapter 6, bindings in Chapter 8, and effects in Chapter 4. Examples are TypeScript; behaviour claims were verified with `svelte@5.57.2` and jsdom unless noted.

## Actions: `use:`

An action is a function called with the element when it is mounted. The docs now steer you to attachments (“In Svelte 5.29 and newer, consider using attachments instead, as they are more flexible and composable”), but actions are everywhere in existing code and libraries, so you need to know exactly how they behave.

```html
<script lang="ts">
  import type { Action } from 'svelte/action';

  const autofocus: Action<HTMLInputElement> = (node) => {
    node.focus();
  };

  const clickOutside: Action<HTMLElement, () => void> = (node, callback) => {
    $effect(() => {
      const handler = (e: MouseEvent) => {
        if (!node.contains(e.target as Node)) callback();
      };
      document.addEventListener('click', handler, true);
      return () => document.removeEventListener('click', handler, true);
    });
  };

  let open = $state(true);
</script>

<input use:autofocus />
{#if open}
  <div use:clickOutside={() => (open = false)}>panel</div>
{/if}
```

### Semantics

- **When it runs.** The action runs in an effect after the element is mounted. It never runs during server rendering.
- **It runs once.** The action is invoked untracked: reading state directly in the action body does not subscribe, and **changing the argument does not call the action again**. The docs: “The action is only called once … it will not run again if the argument changes.” The runtime source confirms it: `untrack(() => action(dom, get_value?.()))`.
- **Reactivity is opt-in, by effects.** Because the action runs inside an effect context, you can create a child `$effect` inside it, and that effect tracks state, re-runs and cleans up on its own (the example above). The cleanup of those effects runs when the element is removed.
- **The legacy return value.** An action may return `{ update, destroy }`. `update(arg)` is called when the argument changes, and `destroy()` when the element is removed. This still works. In my test, `use:act={n}` with an `update` method logged `legacy update 1` after `n++`, and `destroy` ran when the `{#if}` removed the element. The docs call effects the preferred approach.
- **Argument identity.** The argument expression is evaluated by the runtime when needed; with an `update` method, Svelte does a deep read of the argument so mutation of a `$state` object triggers `update`.

### Typing: `Action<Element, Param, Attributes>`

```ts
interface Action<Element = HTMLElement, Parameter = undefined, Attributes extends Record<string, any> = Record<never, any>> {
  <Node extends Element>(node: Node, parameter?: Parameter): void | ActionReturn<Parameter, Attributes>;
}
interface ActionReturn<Parameter = undefined, Attributes = Record<never, any>> {
  update?: (parameter: Parameter) => void;
  destroy?: () => void;
}
```

The third parameter declares custom events or attributes the action adds, which makes them type-check on the element:

```html
<script lang="ts">
  import type { Action } from 'svelte/action';

  const gestures: Action<HTMLDivElement, undefined, {
    onswipeleft: (e: CustomEvent) => void;
    onswiperight: (e: CustomEvent) => void;
  }> = (node) => {
    $effect(() => {
      node.dispatchEvent(new CustomEvent('swipeleft'));
    });
  };
</script>

<div use:gestures onswipeleft={next} onswiperight={prev}>...</div>
```

This is typing only; at runtime `onswipeleft` is an ordinary event attribute (and `swipeleft` is not delegated, so the dispatched event does not need `bubbles`).

### Limits of actions

- They are **not valid on components** (`component_invalid_directive`: “This type of directive is not valid on components”). To augment a wrapper’s element you had to pass the action as a prop. Attachments solve this.
- The argument is a single value, not reactive by default, and there is no composable way to pass actions through spread props.
- The signature does not reveal whether the argument is meant to be live, which causes the classic bug: `use:tooltip={text}` showing the first `text` forever, unless the author remembered to implement `update`.

## Attachments: `{@attach}`

An attachment is a function that receives the element and runs **in an effect**: when the element is mounted and whenever state it read changes. It may return a cleanup function, which runs before each re-run and when the element is removed.

```html
<script lang="ts">
  import type { Attachment } from 'svelte/attachments';

  const logLifecycle: Attachment = (element) => {
    console.log('attached to', element.nodeName);
    return () => console.log('cleaning up');
  };
</script>

<div {@attach logLifecycle}>...</div>
```

The type is simply:

```ts
interface Attachment<T extends EventTarget = Element> {
  (element: T): void | (() => void);
}
```

An element can have any number of `{@attach}` tags. They run in the order written.

### Factories and reactivity

The conventional shape is a function that *returns* an attachment:

```html
<script lang="ts">
  import tippy from 'tippy.js';
  import type { Attachment } from 'svelte/attachments';

  let content = $state('Hello!');

  function tooltip(content: string): Attachment {
    return (element) => {
      const instance = tippy(element, { content });
      return instance.destroy;
    };
  }
</script>

<input bind:value={content} />
<button {@attach tooltip(content)}>Hover me</button>
```

The docs point out the crucial difference from actions: “Since the `tooltip(content)` expression runs inside an effect, the attachment will be destroyed and recreated whenever `content` changes.” The expression `tooltip(content)` is evaluated reactively, and so is anything the returned function reads. I verified this with a logging attachment: after `n++`, the log was `detach tip(0)` then `attach tip(1)`.

The source shows how it works (`attach` in `internal/client/dom/elements/attachments.js`): a managed effect evaluates the expression; if the resulting function is a *different function* than last time, the old branch is destroyed (running cleanups) and a new branch runs the new function. If the expression returns the same function reference, nothing re-runs, which is a useful optimisation: hoist stable attachments out of the template.

### Controlling when an attachment re-runs

Re-creating a tippy instance on every keystroke is wasteful. The idiom from the docs is to pass data as a *getter* and read it in a nested effect, so that the outer function (the expensive setup) runs once:

```ts
function tooltip(getContent: () => string): Attachment {
  return (element) => {
    const instance = tippy(element);        // expensive: once
    $effect(() => {                         // cheap: tracks getContent()
      instance.setContent(getContent());
    });
    return instance.destroy;
  };
}
```

```html
<button {@attach tooltip(() => content)}>Hover me</button>
```

In my test with `inner(() => n)`: the log on mount was `outer setup`, `inner n=0`; after `n++` only `inner n=1` was logged, with no second `outer setup`. The expression `tooltip(() => content)` reads no state itself (the getter is called only inside the nested effect), so it is never re-evaluated and the attachment is not recreated.

Rules of thumb:

- State read **directly** in the attachment function or in the factory call expression: re-run (destroy and recreate).
- State read inside a **nested `$effect`**: only that effect re-runs.
- Return a cleanup for anything you create. The cleanup runs before a re-run and on removal.

### Inline and conditional attachments

An attachment can be an inline function, which is convenient together with nested effects:

```html
<canvas
  width={32}
  height={32}
  {@attach (canvas) => {
    const context = canvas.getContext('2d')!;
    $effect(() => {
      context.fillStyle = color;
      context.fillRect(0, 0, canvas.width, canvas.height);
    });
  }}
></canvas>
```

The outer function reads no reactive state, so it runs once; the nested effect re-runs when `color` changes. Falsy values (`false`, `undefined`, `null`) mean “no attachment”, so you can write `{@attach enabled && tooltip(text)}`. When I toggled `on`, flipping to `false` ran the cleanup (`detach tip(100)`).

### Attachments on components

Used on a component, `{@attach}` becomes a prop whose key is a **Symbol**. If the component spreads its rest props onto an element, the element receives the attachment:

```html
<!-- Button.svelte -->
<script lang="ts">
  import type { HTMLButtonAttributes } from 'svelte/elements';
  let { children, ...props }: HTMLButtonAttributes = $props();
</script>

<button {...props}>{@render children?.()}</button>
```

```html
<Button {@attach tooltip(content)}>Hover me</Button>
```

This is what actions could never do, and it is why wrapper components should spread rest props (Chapter 7). Because the key is a symbol, ordinary destructuring (`let { children, onclick } = $props()`) never sees it, and it passes through `...rest` untouched. `use:` on a component is a compile error.

To attach programmatically to something you spread, create a key with `createAttachmentKey()`:

```html
<script lang="ts">
  import { createAttachmentKey } from 'svelte/attachments';

  const props = {
    class: 'cool',
    onclick: () => alert('clicked'),
    [createAttachmentKey()]: (node: Element) => { node.textContent = 'attached!'; }
  };
</script>

<button {...props}>click me</button>
```

I confirmed the keyed function runs on a spread `<p>`. This matters mainly for library authors who build prop bags (`getRootProps()` in a headless UI library).

### Where attachments can go

On elements, on components (via symbol props), and on `<svelte:document>`, `<svelte:window>` and `<svelte:body>` (the compile of `<svelte:body {@attach ...}>` and `<svelte:document {@attach ...}>` both succeeded). They do not support `await` expressions (`illegal_await_expression`).

### Converting actions: `fromAction`

If a library only offers actions, `fromAction` (5.32) turns one into an attachment, so it can be used on components:

```html
<!-- with an action -->
<div use:foo={bar}>...</div>
<!-- with an attachment -->
<div {@attach fromAction(foo, () => bar)}>...</div>
```

The second argument must be a function *returning* the action’s argument, not the argument itself. In my test, `fromAction(act, () => n)` called the action once and forwarded changes of `n` to the action’s legacy `update` method, the same as `use:` does.

### Migrating actions to attachments

| Action | Attachment |
|------------------------------------|------------------------------------|
| `function a(node, arg) {...}` | `function a(arg) { return (node) => {...}; }` |
| `$effect` in the action for reactive parts | same, nested `$effect` inside the attachment |
| `update(arg)` | not needed: the factory re-runs, or read `getArg()` in a nested effect |
| `return { destroy }` | `return () => {...}` |
| `use:a={x}` | `{@attach a(x)}`; for “run once with live data”, `{@attach a(() => x)}` plus a nested effect |
| not usable on components | usable through spread |

Behavioural differences to watch: actions are not reactive to argument changes (attachments are, so an attachment that did expensive setup will now re-run unless you restructure as above), and attachments run for each re-evaluation of a factory expression, so keep factories pure and cheap.

### Wrapping third-party libraries

The pattern is always the same: create the instance in the attachment, push reactive options through nested effects, return a destroy.

```ts
// chart.svelte.ts
import { untrack } from 'svelte';
import type { Attachment } from 'svelte/attachments';
import { Chart, type ChartConfiguration } from 'chart.js/auto';

export function chart(getConfig: () => ChartConfiguration): Attachment<HTMLCanvasElement> {
  return (canvas) => {
    const instance = new Chart(canvas, untrack(() => $state.snapshot(getConfig())));
    $effect(() => {
      const cfg = $state.snapshot(getConfig());   // tracks deeply, gives a plain clone
      instance.data = cfg.data;
      instance.update();
    });
    return () => instance.destroy();
  };
}
```

Notes: libraries rarely tolerate Svelte state proxies, so pass `$state.snapshot(...)` (Chapter 3); creating the instance in the outer function reads `getConfig()`, which would subscribe the whole attachment and recreate the chart on every change, so that first read is wrapped in `untrack` and the nested effect pushes later changes into the existing instance. The file is a `.svelte.ts` module because it uses runes. D3 and canvas libraries follow the same shape: `select(node)` in the outer function, join data in the effect. For libraries that need an `await`/dynamic import, import in the attachment and guard against the element being removed first (check a `destroyed` flag set in the cleanup).

## Special elements

All of `<svelte:window>`, `<svelte:document>`, `<svelte:body>` and `<svelte:head>` must be at the **top level** of the component, never inside an element or block: I got `svelte_meta_invalid_placement` (“`<svelte:window>` tags cannot be inside elements or blocks”) for both `{#if}` and `<div>` wrappers. If you need a conditional listener, use `on()` in an effect.

### `<svelte:window>`

```html
<script lang="ts">
  let y = $state(0);
  let width = $state(0);
  let online = $state(true);

  function onkeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') close();
  }
</script>

<svelte:window {onkeydown} bind:scrollY={y} bind:innerWidth={width} bind:online />
```

It adds listeners to `window` and removes them on destroy, and avoids `typeof window` checks during SSR. Bindings: `innerWidth`, `innerHeight`, `outerWidth`, `outerHeight`, `scrollX`, `scrollY`, `online` (an alias of `navigator.onLine`), `devicePixelRatio`. All except `scrollX`/`scrollY` are read-only. The initial value of a scroll binding does not scroll the page (accessibility); later changes do. Event attributes work as on any element (`onresize`, `onscroll`, `onpopstate`, …); handlers on `<svelte:window>` are ordinary listeners on `window`, not delegated ones.

### `<svelte:document>`

`<svelte:document>` listens to events that do not reach `window` (`visibilitychange`, `fullscreenchange`, `selectionchange`) and supports attachments:

```html
<script lang="ts">
  let visibility = $state<DocumentVisibilityState>('visible');
  let active = $state<Element | null>(null);
</script>

<svelte:document
  bind:visibilityState={visibility}
  bind:activeElement={active}
  onvisibilitychange={() => console.log('visibility', document.visibilityState)}
/>
```

Bindings (all read-only): `activeElement`, `fullscreenElement`, `pointerLockElement`, `visibilityState`.

### `<svelte:body>`

Events on `document.body` (`mouseenter`, `mouseleave`) that do not fire on `window`, plus actions or attachments on the body element: `<svelte:body onmouseenter={...} use:someAction />`.

### `<svelte:head>`

Inserts elements into `document.head` while mounted; on the server the content is returned separately as `head` from `render` (Chapter 14):

```html
<svelte:head>
  <title>{post.title}</title>
  <meta name="description" content={post.summary} />
</svelte:head>
```

It is how component-level `<title>`, meta tags and preload links work in a plain Vite app. Frameworks (SvelteKit and others) build routing and head management on top of it.

### `<svelte:element>`

Covered in Chapter 6 and used for polymorphic wrappers in Chapter 7: `this` must be an expression, nullish renders nothing, only `bind:this` is supported, and `xmlns` forces a namespace.

### `<svelte:options>`

Per-component compiler options, which override the options given to the compiler:

```html
<svelte:options runes={true} namespace="svg" css="injected" />
<svelte:options customElement="my-element" />
```

Supported: `runes` (`true`/`false`), `namespace` (`"html"`, `"svg"`, `"mathml"`), `customElement` (string tag or options object, Chapter 19), `css="injected"`, `preserveWhitespace`, plus the deprecated `immutable` and `accessors`. Content inside it is an error (`svelte_meta_invalid_content`, “`<svelte:options>` cannot have children”) and unknown attributes are `svelte_options_unknown_attribute` (both verified). `css="injected"` makes the component inject its styles itself (Chapter 10).

## `on()` from `svelte/events`

```ts
function on(
  target: Window | Document | HTMLElement | MediaQueryList | EventTarget,
  type: string,
  handler: (event: Event) => any,
  options?: AddEventListenerOptions
): () => void;
```

`on` attaches a listener and returns a function that removes it. Why use it instead of `addEventListener`? Because of delegation (Chapter 6): declarative handlers like `onclick` run from a single root listener, so a raw listener you add inside the app root fires **before** them and `stopPropagation` in it hides them. `on` wraps the handler so that ordering matches the DOM position and `stopPropagation` is honoured correctly. The docs: “Using this rather than `addEventListener` will preserve the correct order relative to handlers added declaratively.”

It composes perfectly with effects and attachments, since both accept a returned cleanup:

```html
<script lang="ts">
  import { on } from 'svelte/events';
  import type { Attachment } from 'svelte/attachments';

  // non-passive touch handling: attribute handlers are always passive
  const preventScroll: Attachment<HTMLElement> = (el) =>
    on(el, 'touchmove', (e) => e.preventDefault(), { passive: false });
</script>

<div {@attach preventScroll}>drag me</div>
```

And in an effect for a conditional listener: `$effect(() => { if (!active) return; return on(window, 'keydown', handler); });`.

## Reactive browser values

Sometimes you want `window.innerWidth` as a *value*, in a `$derived` or in a `.svelte.ts` module, not as a template binding. Svelte ships the building blocks.

### `svelte/reactivity/window`

`svelte/reactivity/window` (5.11) exports reactive views of window state, each an object with a `.current` property: `scrollX`, `scrollY`, `innerWidth`, `innerHeight`, `outerWidth`, `outerHeight`, `screenLeft`, `screenTop`, `online` and `devicePixelRatio`.

```html
<script lang="ts">
  import { innerWidth, online } from 'svelte/reactivity/window';
  const compact = $derived((innerWidth.current ?? 1024) < 640);
</script>

<p>{compact ? 'compact' : 'wide'} ({online.current ? 'online' : 'offline'})</p>
```

On the server, `.current` is `undefined` (they are created with `BROWSER ? () => window.scrollX : () => undefined`), so always supply a fallback. `screenLeft` and `screenTop` are polled in `requestAnimationFrame`. `devicePixelRatio` follows browser zoom in Chrome but not in Firefox or Safari. Each source adds its event listener only while some effect reads it (see `createSubscriber` below).

### `MediaQuery`

```html
<script lang="ts">
  import { MediaQuery } from 'svelte/reactivity';

  const large = new MediaQuery('min-width: 800px');
  const dark = new MediaQuery('prefers-color-scheme: dark', false); // server fallback
</script>

<h1>{large.current ? 'large screen' : 'small screen'}</h1>
```

Pass the query **without outer parentheses** (`'min-width: 800px'`); the constructor wraps it unless it already contains parentheses or consists only of the keywords `all`, `print`, `screen`, `and`, `or`, `not`, `only` (source: `media-query.js`). The optional second argument is the server fallback. The doc warning matters: during SSR the real value is unknown, so a `MediaQuery`-driven layout can change at hydration. If the same effect can be achieved in CSS, do it in CSS.

### `prefersReducedMotion`

`import { prefersReducedMotion } from 'svelte/motion'` is a `MediaQuery` for `prefers-reduced-motion: reduce` (5.7). It exists because Svelte transitions use the Web Animations API, which a global `@media (prefers-reduced-motion)` CSS override does not affect (Chapter 11):

```html
<script lang="ts">
  import { fade } from 'svelte/transition';
  import { prefersReducedMotion } from 'svelte/motion';
</script>

<div transition:fade={{ duration: prefersReducedMotion.current ? 0 : 300 }}>...</div>
```

## `createSubscriber`: wrapping any event source

`createSubscriber` is the primitive underneath `MediaQuery` and the window values:

```ts
function createSubscriber(start: (update: () => void) => (() => void) | void): () => void;
```

You give it a `start` function. It returns a `subscribe` function that you call **inside the getter** of your reactive value. The semantics (documented, and visible in the source):

1.  `subscribe()` does something only when called while an effect is tracking (`$effect.tracking()` true: inside an effect, a `$derived`, or a template expression). Outside a tracking context it is a no-op, so reading the value in an event handler is safe and cheap.
2.  The first tracking reader triggers `start(update)`. Calling `update()` bumps an internal version source, which re-runs every effect that called `subscribe()`.
3.  If many effects subscribe, `start` is still called **once**. When the last one is destroyed, the cleanup returned by `start` runs. (The teardown is deferred one microtask so that an effect that merely *re-runs* does not drop the count to zero and restart the subscription.)
4.  When the subscription is torn down and later resumed, the version is bumped, so cached `$derived` values re-read the external source instead of using stale data.

The canonical documented implementation is a few lines:

```ts
import { createSubscriber } from 'svelte/reactivity';
import { on } from 'svelte/events';

export class MediaQuery {
  #query: MediaQueryList;
  #subscribe: () => void;

  constructor(query: string) {
    this.#query = window.matchMedia(`(${query})`);
    this.#subscribe = createSubscriber((update) => {
      const off = on(this.#query, 'change', update);
      return () => off();
    });
  }

  get current() {
    this.#subscribe();            // makes the getter reactive when read in an effect
    return this.#query.matches;   // always returns the live value
  }
}
```

The two-line shape of `get current()` is the pattern: **subscribe, then read the live value**. Do not cache the value in a field you update from the callback; let `update()` merely signal “something changed” and read the truth on demand. That keeps the value correct even when no effect is subscribed.

### Writing a reusable primitive: `ElementSize`

Here is a `ResizeObserver` wrapper that observes only while someone reads it.

```ts
// element-size.svelte.ts
import { createSubscriber } from 'svelte/reactivity';

export class ElementSize {
  #el: Element;
  #width = 0;
  #height = 0;
  #subscribe: () => void;

  constructor(el: Element) {
    this.#el = el;
    this.#subscribe = createSubscriber((update) => {
      const ro = new ResizeObserver(([entry]) => {
        const r = entry.contentRect;
        this.#width = r.width;
        this.#height = r.height;
        update();
      });
      ro.observe(this.#el);
      return () => ro.disconnect();
    });
  }

  get width() { this.#subscribe(); return this.#width; }
  get height() { this.#subscribe(); return this.#height; }
}
```

```html
<script lang="ts">
  import { ElementSize } from './element-size.svelte';

  let el = $state<HTMLElement>();
  const size = $derived(el ? new ElementSize(el) : undefined);
</script>

<div bind:this={el}>{size ? `${size.width} × ${size.height}` : '...'}</div>
```

I ran this against a fake `ResizeObserver` in jsdom. The log showed exactly the lifecycle promised: `start, observe` on first read, a re-render to `100x50` when the observer callback fired (`update()`), then `stop, disconnect` after the reading block was removed, and `start, observe` again when it was re-shown. Two elements read `size.width` in the test (a `$derived` string and a template expression) and `start` was called once.

Design notes:

- Using a class with `get` accessors rather than a `$state` field avoids writing state from a callback and gives lazy, ref-counted observation.
- The values `#width` and `#height` are plain fields. That works because reactivity comes from `update()` re-running the readers, which then read fresh values. If you need `$derived` to *skip* downstream work when the value did not change, derived equality still applies to the result.
- `$effect.tracking()` is what `createSubscriber` consults. If you write a primitive that needs the same guard directly (for example, to avoid allocating in a non-reactive read), `$effect.tracking()` returns whether the current code is running in an effect or template.
- For `IntersectionObserver`, replace the observer and publish `isIntersecting`; for `WebSocket` or `BroadcastChannel`, `start` opens the connection and the cleanup closes it, so the connection lives exactly as long as some UI reads it.
- Do not use `$effect` plus `$state` to mirror an external source when `createSubscriber` fits: the effect version needs a component or `$effect.root` for lifetime, keeps observing when nothing reads the value and risks flashes of stale content. The docs’ stance in “when not to use `$effect`”: use `createSubscriber` to observe something external.

### Choosing the right tool

| You need to… | Use |
|------------------------------------|------------------------------------|
| Run code for one element’s lifetime, including libraries needing the node | attachment (`{@attach}`) |
| Support an existing action or a library that ships actions | `use:` (or `fromAction` for components) |
| Add a listener to `window`/`document`/`body` for the component’s lifetime | `<svelte:window>` etc. |
| A conditional or option-carrying listener, or a handler that must interoperate with delegated events | `on()` in an effect or attachment |
| Use a window or media value in script or in `$derived` | `svelte/reactivity/window`, `MediaQuery` |
| Reactive view of any other external event source | `createSubscriber` |
| Document title/meta | `<svelte:head>` |

## Worked example: a small attachment library

To tie the pieces together, here is a module of three attachments that a design system could ship, written to be composable, typed, reactive where it matters and safe to spread through wrapper components.

```ts
// attachments.svelte.ts
import { on } from 'svelte/events';
import type { Attachment } from 'svelte/attachments';

/** Calls `handler` when a pointerdown happens outside the element. */
export function clickOutside(getHandler: () => () => void): Attachment<HTMLElement> {
  return (node) => {
    const off = on(document, 'pointerdown', (e) => {
      if (!node.contains(e.target as Node)) getHandler()();
    }, { capture: true });
    return off;
  };
}

/** Keeps Tab focus inside the element while it is mounted. */
export function focusTrap(): Attachment<HTMLElement> {
  return (node) => {
    const previous = document.activeElement as HTMLElement | null;
    const selector = 'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';
    const focusables = () => [...node.querySelectorAll<HTMLElement>(selector)];
    focusables()[0]?.focus();

    const off = on(node, 'keydown', (e) => {
      if (e.key !== 'Tab') return;
      const items = focusables();
      if (items.length === 0) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { last.focus(); e.preventDefault(); }
      else if (!e.shiftKey && document.activeElement === last) { first.focus(); e.preventDefault(); }
    });

    return () => { off(); previous?.focus(); };   // restore focus on teardown
  };
}

/** Sets an aria-label that follows reactive text without re-running setup. */
export function label(getText: () => string): Attachment {
  return (node) => {
    $effect(() => { node.setAttribute('aria-label', getText()); });
    return () => node.removeAttribute('aria-label');
  };
}
```

Note the `.svelte.ts` suffix: runes such as `$effect` are only compiled in `.svelte`, `.svelte.js` and `.svelte.ts` files.

Usage on a dialog and on a wrapper component:

```html
<script lang="ts">
  import { clickOutside, focusTrap, label } from './attachments.svelte';
  import Button from './Button.svelte';

  let open = $state(false);
  let name = $state('Ada');
  const close = () => (open = false);
</script>

<Button onclick={() => (open = true)} {@attach label(() => `Edit ${name}`)}>Edit</Button>

{#if open}
  <div role="dialog" aria-modal="true" {@attach focusTrap()} {@attach clickOutside(() => close)}>
    <input bind:value={name} />
    <button onclick={close}>Done</button>
  </div>
{/if}
```

Points that this example makes concrete:

- **Each attachment is a factory** with explicit inputs. `clickOutside` takes a *getter for the handler*, so passing a new closure each time the expression is evaluated does not tear down and rebuild the document listener. `focusTrap()` takes nothing, so its expression never re-evaluates.
- **`on()` over `addEventListener`.** Dialog content often contains declaratively attached `onclick` and `onkeydown` handlers (delegated); `on` keeps their order consistent, and the `capture: true` option is passed straight through.
- **Cleanup does real work.** Focus is restored to the previously focused element when the dialog’s attachment is destroyed, whether the dialog closed or the whole page navigated.
- **Wrapper-friendliness.** `label()` works on `<Button>` because `Button` spreads its rest props. Document that requirement for wrapper authors: “spread `...rest` onto the root element, last”.
- **Several attachments on one element** run in order of appearance; each has its own effect and cleanup.

### Testing attachments

Because an attachment is a function from an element to a cleanup, the cheapest tests need no component. Create an element, run the attachment inside an effect root so that nested `$effect`s have an owner, flush, assert, then call the returned destroy function:

```ts
// attachments.test.svelte.ts  (Vitest + jsdom, Chapter 16)
import { flushSync } from 'svelte';
import { expect, test } from 'vitest';
import { focusTrap } from './attachments.svelte';

test('focusTrap focuses the first control and restores focus', () => {
  document.body.innerHTML = '<button id="opener">o</button>';
  const opener = document.getElementById('opener')!;
  opener.focus();

  const dialog = document.createElement('div');
  dialog.innerHTML = '<input id="first" /><button>ok</button>';
  document.body.append(dialog);

  const cleanup = $effect.root(() => {
    $effect(() => focusTrap()(dialog));
  });
  flushSync();
  expect(document.activeElement?.id).toBe('first');

  cleanup();
  expect(document.activeElement?.id).toBe('opener');
});
```

Component-level tests (mount a small wrapper with `{@attach ...}` and assert on the DOM) are better for checking spread forwarding and conditional attachments (Chapter 16 covers the harness).

### Pitfalls checklist

1.  **State read in the factory expression re-creates the attachment.** If the setup is expensive, pass getters and read them in nested effects.
2.  **Stable function identity skips re-runs.** Hoist attachments that do not depend on state (`const trap = focusTrap();` once, `{@attach trap}`), but be careful: the *same function* attached to two elements is fine, since each element gets its own run.
3.  **Do not mutate state read by the attachment itself** inside the attachment body; as with any effect, that loops (`effect_update_depth_exceeded`).
4.  **Actions on SSR output.** Neither actions nor attachments run on the server, so anything they set (focus, aria attributes computed in JS) is absent from the first HTML. Render critical attributes in markup.
5.  **Async setup.** If an attachment awaits (dynamic import), the element may be gone before the promise resolves; keep a local `let destroyed = false` set by the cleanup and check it before touching the node.
6.  **`$state.snapshot` for third-party code.** Proxies confuse libraries that do identity checks or structured cloning.

## Key takeaways

- Actions run once per element, untracked, after mount and never on the server; the argument is not reactive unless the action uses effects or the legacy `update` method. They cannot be used on components.
- Attachments run in an effect: they re-run, with cleanup, when state read in the function or in the factory expression changes. Use a nested `$effect` and pass getters for fine-grained updates. Falsy attachments are ignored.
- On components, `{@attach}` becomes a Symbol-keyed prop; wrappers that spread rest props forward it. Use `createAttachmentKey` to build such props, and `fromAction(action, () => arg)` to reuse actions.
- `<svelte:window>`, `<svelte:document>`, `<svelte:body>` and `<svelte:head>` are top level only; scroll bindings do not scroll initially; document bindings are read-only; `<svelte:options>` has no children.
- Use `on()` from `svelte/events` for imperatively added listeners, so ordering with delegated handlers and `stopPropagation` behave, and for `passive: false`.
- `svelte/reactivity/window` values and `MediaQuery` are `.current` objects that are `undefined` or fallback-driven on the server. Prefer CSS when a media query only affects styling.
- `createSubscriber` turns any event source into a reactive value: call `subscribe()` in the getter, then return the live value; `start` runs once while any effect reads it and is cleaned up after the last one is gone.

## Review Questions

1.  List three semantic differences between `use:` actions and `{@attach}` attachments with regard to reactivity, components and lifecycle.

2.  What does this log after `n++`? Why?

    ```html
    <div use:track={n}></div>
    ```

    ```ts
    const track: Action<HTMLElement, number> = (node, arg) => { console.log('run', arg); };
    ```

3.  Same question for `<div {@attach track(n)}></div>` where `const track = (v: number): Attachment => (el) => { console.log('run', v); }`.

4.  Rewrite a tooltip attachment so that the expensive library instance is created once, but the content follows a reactive value. Show both the attachment and its use.

5.  Why does `{@attach tooltip(() => content)}` not re-run the attachment when `content` changes, even though the arrow function is recreated?

6.  What is passed to a component that receives `<Button {@attach foo} />`, and what must `Button` do for the attachment to reach the DOM element? What happens with `let { children, ...rest } = $props()` versus destructuring named props only?

7.  (Multiple choice) `{@attach cond && foo}` where `cond` is `false`:

    a.  compile error
    b.  runtime error
    c.  no attachment, no error
    d.  foo is called with `undefined`

8.  How do you convert `<div use:foo={bar}>` to an attachment without rewriting `foo`? What is wrong with `fromAction(foo, bar)`?

9.  Find the bug: an action reads `$state` directly in its body and the developer expects it to re-run when the state changes. Give two fixes.

10. Why do actions not run during SSR, and how does this relate to where you may touch `window` inside them?

11. Which elements may contain `<svelte:window>`? What error occurs if you put it inside an `{#if}`? How would you add a window listener conditionally?

12. Which `<svelte:window>` bindings are writable? What happens when you initialise `scrollY` to 500?

13. What are the four `<svelte:document>` bindings? Are they readable, writable, or both?

14. Name two events you can listen to on `<svelte:document>` or `<svelte:body>` that you cannot on `<svelte:window>`.

15. What does `<svelte:options>` accept, and what happens if you give it children or an unknown attribute?

16. A third-party modal library calls `stopPropagation` on `click` in a native listener on its container. Why do your `onclick` handlers inside it stop working, and how does `on()` fix this?

17. Write an attachment using `on()` that prevents scrolling during `touchmove`. Why can’t `ontouchmove` be used?

18. What does `innerWidth.current` return on the server? How do you write a `$derived` that is safe there?

19. Why must `new MediaQuery('(min-width: 800px)')` and `new MediaQuery('min-width: 800px')` both work, and what happens with `new MediaQuery('screen')`?

20. Why might a layout driven by `MediaQuery` flash on hydration, and what is the alternative?

21. Why doesn’t `transition:fade` respect a CSS `@media (prefers-reduced-motion: reduce)` rule that zeroes `animation-duration`? How does `prefersReducedMotion` help?

22. Describe the four guarantees of `createSubscriber` (when `start` is called, how often, when cleanup runs, and what happens when `subscribe` is called outside an effect).

23. Why is the cleanup in `createSubscriber` deferred by a microtask?

24. Find the bug in this primitive and fix it:

    ```ts
    class Online {
      value = $state(navigator.onLine);
      constructor() {
        window.addEventListener('online', () => (this.value = true));
        window.addEventListener('offline', () => (this.value = false));
      }
    }
    ```

25. Implement `get current()` for a `Visibility` class based on `document.visibilityState` using `createSubscriber` and `on`.

26. Compare an `ElementSize` built with `createSubscriber` against `bind:contentRect` on the element. When is each preferable?

27. In a data-chart attachment, why pass `$state.snapshot(config)` to the library, and what happens if you read `getConfig()` in the outer attachment function?

28. Design question: your design system needs `use:clickOutside`, `use:focusTrap` and tooltips on every component, including ones that wrap `<button>` and `<input>`. Which mechanism do you choose and how do you document the contract for wrapper authors?
