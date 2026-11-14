# Chapter 19: Custom Elements and Web Component Interop

Svelte components normally live inside a Svelte application, but the compiler can also emit a standard custom element (a “web component”): a class registered with `customElements.define`, usable from plain HTML, from other frameworks, or from a CMS that knows nothing about Svelte. This chapter covers how that compilation mode works, what the wrapper does at runtime, how props map to attributes and properties, how shadow DOM and styles behave, how to emit events with `$host()`, how slots differ from snippets, how to make form-associated elements with `extend`, and what does not work (context, SSR, some slot semantics). It also covers the opposite direction: using third-party web components inside Svelte templates, with proper types, and the packaging choices for publishing your own.

Examples were compiled and run with Svelte 5.57.2 in jsdom, using `customElement: true` in the Vite plugin options.

## Compiling a component as a custom element

Two switches are involved. The compiler option `customElement: true` turns the mode on for the compile; `<svelte:options customElement=...>` inside a component describes that component’s element.

```html
<!-- MyElement.svelte -->
<svelte:options customElement="my-element" />

<script lang="ts">
  let { name = 'world' }: { name?: string } = $props();
</script>

<h1>Hello {name}!</h1>
<slot />
```

```ts
// vite.config.ts
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte({ compilerOptions: { customElement: true } })]
});
```

Since 5.54, `customElement` may also be a function `({ filename }) => boolean`, which allows a single project to compile only some files as custom elements (for example everything under `src/elements/`):

```ts
svelte({
  compilerOptions: {
    customElement: ({ filename }) => filename.includes('/src/elements/')
  }
})
```

What goes wrong when the two halves are out of step is covered by compiler diagnostics. With `<svelte:options customElement="x-a" />` but no compile option we got the warning `options_missing_custom_element` (“The `customElement` option is used when generating a custom element. Did you forget the `customElement: true` compile option?”). Invalid tags are compile errors: `customElement="foo"` gives `svelte_options_invalid_tagname` (“Tag name must be lowercase and hyphenated”) and `font-face` gives `svelte_options_reserved_tagname`. `$host()` in a normally compiled component is `host_invalid_placement`.

### The tag: string form and object form

`customElement="my-element"` is shorthand for the tag only. If you omit the tag entirely (or omit `<svelte:options customElement>` while the compile flag is on), the component is still compiled as an element class but is not registered. That is the right setup for inner components: “You can leave out the tag name for any of your inner components which you don’t want to expose and use them like regular Svelte components.” Consumers can register the class later under any name via the static `element` property:

```ts
import MyElement from './MyElement.svelte';

customElements.define('my-element', MyElement.element);
```

(The `static element` property holds the constructor and exists when the `customElement` compile option is `true`.) Svelte’s own typings describe it as an optional `element?: typeof HTMLElement` member of the `Component` type.

The object form has four keys:

```html
<svelte:options
  customElement={{
    tag: 'x-rating',
    shadow: 'open',
    props: {
      value: { type: 'Number', reflect: true, attribute: 'value' },
      label: { type: 'String' },
      readonly: { type: 'Boolean' }
    },
    extend: (ElementClass) => class extends ElementClass { /* ... */ }
  }}
/>
```

All of these must be statically analysable: `props` “must be a statically analyzable object literal” (`svelte_options_invalid_customelement_props`), and `<svelte:options>` can only receive static attributes (you cannot compute the tag name at runtime, though you can use `import.meta.env.DEV` style constants inside `shadow`, as the docs do). The older `tag` option on `<svelte:options tag="...">` is gone: `svelte_options_deprecated_tag` says to use `customElement` instead.

## A complete example

A star rating element exercising props, reflection, a custom event, a named slot and scoped styles:

```html
<!-- src/elements/Rating.svelte -->
<svelte:options
  customElement={{
    tag: 'x-rating',
    props: {
      value: { type: 'Number', reflect: true, attribute: 'value' },
      label: { type: 'String' },
      readonly: { type: 'Boolean' }
    }
  }}
/>

<script lang="ts">
  let {
    value = 0,
    label = 'Rating',
    readonly = false
  }: { value?: number; label?: string; readonly?: boolean } = $props();

  function set(n: number) {
    if (readonly) return;
    value = n;
    $host().dispatchEvent(new CustomEvent('rate', { detail: n, bubbles: true, composed: true }));
  }
</script>

<div role="radiogroup" aria-label={label}>
  {#each [1, 2, 3, 4, 5] as n}
    <button
      type="button"
      role="radio"
      aria-checked={value === n}
      disabled={readonly}
      onclick={() => set(n)}
    >{n <= value ? '★' : '☆'}</button>
  {/each}
  <slot name="hint" />
</div>

<style>
  button { background: none; border: 0; font-size: 1.5rem; }
</style>
```

It compiles without warnings. Consumed from plain HTML:

```html
<x-rating value="3" label="Quality"><small slot="hint">tap a star</small></x-rating>

<script type="module">
  import './Rating.svelte';   // registers <x-rating>
  const el = document.querySelector('x-rating');
  el.addEventListener('rate', (e) => console.log('rated', e.detail));
</script>
```

We ran this in jsdom and observed the following sequence, which maps directly onto the lifecycle described next:

    tag defined: true  static element: function
    sync shadow children: 0                     <- immediately after innerHTML: nothing rendered yet
    after tick: 5 buttons, value prop 3 (number) <- attribute "3" converted by type: 'Number'
    click 5th star: 'rate' event detail 5, attribute value="5" (reflected), property value 5
    setAttribute('label', 'Other'): aria-label in the shadow DOM becomes 'Other' after a tick

## The wrapper architecture and lifecycle

Svelte does not turn your component into a class directly. It generates a *wrapper* custom element class around an ordinary Svelte component; the inner component “has no knowledge that it is a custom element”. The wrapper handles lifecycle:

1.  **Construction.** The element is created (by the parser, `document.createElement`, or `new`). No Svelte component exists yet. Properties assigned now are stored, not applied.
2.  **`connectedCallback`.** The inner component is created in the *next tick* after this callback, not synchronously. Previously buffered properties become the component’s initial props. This is why `shadowRoot` was empty right after `innerHTML` in our run.
3.  **Updates.** Setting a property or attribute updates the inner component’s props; the shadow DOM “will reflect the value in the next tick, not immediately”. This batching also means that a DOM move, which temporarily and synchronously disconnects and reconnects the element, does not destroy and recreate the component.
4.  **`disconnectedCallback`.** The inner component is destroyed in the next tick after it. If the element is reconnected within the same tick (a move), the component survives.

Consequences to design for:

- **Reading rendered output synchronously is wrong.** After creating or updating the element, `await` a microtask or listen for an event your component fires.
- **Exported functions are not available before mount.** If your component has `export function focus() {...}`, calling `el.focus()` (on the custom element) before the inner component exists fails, because “invoking exported functions on the custom element… are only available after the element has mounted”. Property assignment is safe before mount; method calls are not. The workaround is to define such methods in the `extend` class (below), so they exist from construction and can store state until the component appears.
- **Teardown is deferred**, so cleanup in `$effect` teardowns and `onDestroy` runs a tick after removal. Tests should `await tick()` before asserting that cleanup ran.

## Props, attributes and properties

Every prop you declare is exposed as a property on the element (“Any props are exposed as properties of the DOM element (as well as being readable/writable as attributes, where possible)”). Svelte must know the list at compile time. That is why a bare `let props = $props()` or a rest element cannot work: the compiler warns `custom_element_props_identifier` (“Using a rest element or a non-destructured declaration with `$props()` means that Svelte can’t infer what properties to expose when creating a custom element. Consider destructuring all the props or explicitly specifying the `customElement.props` option.”). We reproduced the warning with `let p = $props()`. The remedies are to destructure every prop, or to list them in `customElement.props`.

Each entry in `props` can set three things:

| Key | Meaning | Default |
|------------------------|------------------------|------------------------|
| `attribute` | HTML attribute name used to read the prop | lowercase prop name |
| `reflect` | write prop changes back to the attribute | `false` |
| `type` | `'String' \| 'Boolean' \| 'Number' \| 'Array' \| 'Object'`, how to convert the attribute string | `'String'` |

Attributes are strings, so without `type` your `value` prop would receive `"3"`. With `type: 'Number'` we observed `typeof el.value === 'number'`. `Boolean` follows attribute presence semantics; `Array` and `Object` parse JSON from the attribute. Props not listed use the defaults, so you only list what needs customising (“You don’t need to list all properties”).

Properties assigned from JavaScript are not converted: `el.value = 4` sets the value as given. This is the right way to pass objects, arrays and functions: `el.items = [...]`. Frameworks that set properties for custom elements (Vue with `.prop`, Lit, Svelte itself, React 19) work directly. Frameworks that only set attributes will stringify non-primitives, so for those pass JSON through `type: 'Object'`/`'Array'` attributes or use a wrapper.

`reflect: true` writes the value back as an attribute whenever the prop changes (we saw `value="5"` after a click). Reflect only primitives that are useful in CSS selectors (`[state="open"]`) and accessibility; reflecting large objects is wasteful.

### Reserved names

“Don’t declare properties or attributes starting with `on`, as their usage will be interpreted as an event listener.” Svelte treats `<custom-element oneworld={true}>` as `customElement.addEventListener('eworld', true)`, not as setting a `oneworld` property. This is a trap in both directions: a prop of yours called `onToggle` will never be set, and a third-party element with a property called `oneworld` cannot be set through a Svelte attribute. Name props with verbs or nouns that do not start with `on`.

## Shadow DOM and styles

By default, each element gets an open shadow root. The `shadow` option changes this:

- `"open"`: `attachShadow({ mode: 'open' })` (the default behaviour).
- `"none"`: no shadow root. Styles are then no longer encapsulated and you “can’t use slots”.
- a `ShadowRootInit` object (5.49+), passed to `attachShadow()`: for `mode: 'closed'`, `delegatesFocus`, `clonable`, `serializable` and others. The docs’ example uses `mode: import.meta.env.DEV ? 'open' : 'closed'`.

```html
<svelte:options
  customElement={{
    tag: 'x-menu-button',
    shadow: { mode: 'open', delegatesFocus: true }
  }}
/>
```

`delegatesFocus: true` is the interesting one for accessibility: clicking non-focusable parts of the shadow content focuses the first focusable element, and the host participates in `:focus` styling correctly.

**Styles** are encapsulated by the shadow root, not merely scoped by a class hash. The consequences are the opposite of ordinary Svelte:

- Global stylesheets do not reach inside, “including styles with the `:global(...)` modifier”. The way to let consumers style your element is CSS custom properties (which inherit through shadow boundaries) and `::part()` (give inner elements a `part="..."` attribute).
- CSS is always injected: “Instead of being extracted out as a separate .css file, styles are inlined into the component as a JavaScript string”. Whatever `css` option you pass, custom elements behave as `'injected'`; the style is placed inside the shadow root (we found a `<style>` element in the shadow root in our run).
- With `shadow: 'none'`, the style is not encapsulated at all (we compiled such a component and the compiler returned no separate CSS, no shadow root code). Treat it as an ordinary global stylesheet.

```html
<button part="trigger"><slot /></button>

<style>
  button {
    background: var(--x-button-bg, #eee);   /* themable from outside */
    border-radius: var(--x-button-radius, 4px);
  }
</style>
```

```css
x-menu-button { --x-button-bg: rebeccapurple; }
x-menu-button::part(trigger):hover { text-decoration: underline; }
```

## Events: `$host()`

The `$host` rune returns the host element. It is valid only in custom element components and runs on the client. Its main use is dispatching events that the outside world can hear:

```html
<svelte:options customElement="my-stepper" />

<script lang="ts">
  function dispatch(type: string) {
    $host().dispatchEvent(new CustomEvent(type));
  }
</script>

<button onclick={() => dispatch('decrement')}>decrement</button>
<button onclick={() => dispatch('increment')}>increment</button>
```

Used from Svelte:

```html
<script lang="ts">
  import './Stepper.svelte';
  let count = $state(0);
</script>

<my-stepper ondecrement={() => count -= 1} onincrement={() => count += 1}></my-stepper>
<p>count: {count}</p>
```

Svelte maps `onxyz` attributes on custom elements to `addEventListener('xyz', ...)`, which is exactly what makes the reserved-name rule above necessary. Event design guidance:

- Set `bubbles: true` if consumers will listen on ancestors, and `composed: true` if the event must cross a shadow boundary to reach listeners outside nested shadow roots (we used both in the rating element). Without `composed`, an event dispatched inside nested shadow roots stops at the boundary.
- Put the payload in `detail`, and do not rely on consumers reading your internal state.
- Dispatch after state changes that the consumer might read back: a `rate` event listener that reads `el.value` should see the new value, so assign the prop first (as `set` does).
- Name events in lowercase with no dashes problems: `onrate`, `onitem-selected` is awkward in Svelte attribute syntax (use `addEventListener` in that case).

Typing `$host()`: it is generic, `$host<El extends HTMLElement = HTMLElement>()`, so `$host<HTMLElement & { value: number }>()` gives you typed access.

## Slots, not snippets

Custom elements are consumed from HTML, which knows slots, not snippets. Svelte therefore keeps the `<slot>` element (deprecated elsewhere) in custom element components, and does so also in runes mode without warning (our component compiled with no warnings). Named slots use `<slot name="hint">` and consumers use `slot="hint"` on children, exactly as in the platform.

Where the Svelte and DOM models differ, from the docs:

- **Eager versus lazy.** “In Svelte, slotted content renders lazily. In the DOM, it renders eagerly. In other words, it will always be created even if the component’s `<slot>` element is inside an `{#if ...}` block. Similarly, including a `<slot>` in an `{#each ...}` block will not cause the slotted content to be rendered multiple times.” A `<slot>` is a projection point for existing light DOM nodes; hiding the slot hides those nodes from rendering but they are still created (and may run their own code, for example a nested element’s constructor).
- **`let:` has no effect.** Platform slots cannot pass data back to the content provider, so scoped slot parameters are unavailable. If you need render-prop style APIs, use properties holding functions (set from JavaScript), or events.
- **`shadow: 'none'` has no slots.** Slotting is a shadow DOM feature.

Snippet props do not map to attributes at all (an HTML attribute cannot hold a function). If your component accepts a `children` snippet, a custom element consumer will not provide it. Design custom-element-facing components around slots, and use inner Svelte components with snippets internally.

A related note from the migration guide: in Svelte 5, a `<slot>` that is a child of a `<template shadowrootmode="...">` (declarative shadow DOM) is preserved rather than replaced by Svelte’s own slot handling, which matters if you write declarative shadow roots by hand inside Svelte templates.

## `extend`: form-associated elements and early methods

`extend` receives the generated element class and must return a class. This is the escape hatch for anything the wrapper does not provide: `ElementInternals`, `formAssociated`, methods that must exist before the component mounts, `observedAttributes` tweaks and so on.

```html
<svelte:options
  customElement={{
    tag: 'x-field',
    props: { value: { reflect: true }, name: {} },
    extend: (customElementConstructor) =>
      class extends customElementConstructor {
        static formAssociated = true;
        attachedInternals: ElementInternals;

        constructor() {
          super();
          this.attachedInternals = this.attachInternals();
        }

        // Defined here, not in the component, so it exists from construction
        reset() {
          this.value = '';
        }
      }
  }}
/>

<script lang="ts">
  let { value = $bindable(''), name = '', attachedInternals } = $props();

  $effect(() => {
    attachedInternals?.setFormValue(value);
  });
</script>

<input bind:value aria-label={name} />
```

(An abbreviation of the documentation’s example: the class is passed through `extend`, and instance fields set in the class are visible to the component as props, since the wrapper passes the element’s properties on.) Two limitations from the docs:

- TypeScript is supported in `extend`, “it is subject to limitations: you need to set `lang="ts"` on one of the scripts AND you can only use erasable syntax in it. They are not processed by script preprocessors.” Erasable syntax means type annotations, interfaces and the like that can be stripped without transformation. No enums, no constructor parameter properties, no `namespace`. (This corresponds to TypeScript’s `erasableSyntaxOnly` flag.) In the example above, `attachedInternals: ElementInternals;` as a field declaration with a type is erasable; a parameter property such as `constructor(private x: number)` is not.
- `extend` code runs at class-definition time, outside any Svelte component, so runes are not available in it.

With `formAssociated = true` the element participates in `<form>` submission, validation and `form.reset()` through `ElementInternals`: call `setFormValue`, `setValidity` and implement `formResetCallback`/`formDisabledCallback` on the class.

## What does not work

- **Context across element boundaries.** “You can use Svelte’s context feature between regular Svelte components within a custom element, but you can’t use them across custom elements.” Each custom element is its own Svelte root; `setContext` in a parent element is invisible to `getContext` in a child element. For cross-element communication use DOM events, properties, or the platform’s Context Protocol (the community `@lit/context`-style event-based protocol, which you would implement with `$host()` events).
- **Server-side rendering.** “Custom elements are not generally suitable for server-side rendering, as the shadow DOM is invisible until JavaScript loads.” Svelte’s `render()` works on the component, but the output is not declarative shadow DOM, so the page content appears only after the element upgrades. Expect a flash of empty content and layout shift; reserve space with CSS (`x-rating:not(:defined) { display: inline-block; min-height: 2rem }`) and use `:defined`.
- **Older browsers** need polyfills (custom elements and shadow DOM are Baseline today, but Svelte’s own browser floor is older than some CE features; check `ElementInternals`, `adoptedStyleSheets`, and `ShadowRootInit` options such as `clonable` for your targets).
- **Global styles.** Utility CSS (Tailwind) and page-level resets do not penetrate. Either use `shadow: 'none'` or ship styles with the element.
- **Bundle duplication.** Each independently bundled element brings its own copy of the Svelte runtime unless you bundle them together or externalise `svelte`. See below.
- **Two-way binding.** There is no `bind:` across the custom element boundary from non-Svelte consumers. Use events plus properties; in Svelte, `bind:value` on a custom element works only on elements you listen to via standard property/event semantics, so prefer explicit `value={x}` and `onchange` handlers.

## Using Svelte custom elements from other frameworks

Because the output is the platform’s `customElements` API, integration is idiomatic in each host:

- **Plain HTML / CMS**: import the module (or a script tag) and write the tag. Attributes configure; properties carry rich data.
- **React**: React 19 passes properties to custom elements when a matching property exists on the element and supports custom events via `onevent` props with the `on` + CamelCase convention only for known React events, so for custom events such as `rate` attach with a `ref` and `addEventListener`. Pass objects as properties, which React 19 does.
- **Vue**: configure `compilerOptions.isCustomElement` for your prefix; use `.prop` modifier for property binding and `@rate` for events.
- **Angular**: add `CUSTOM_ELEMENTS_SCHEMA` and use property binding `[value]` and event binding `(rate)`.

Because the custom element wrapper creates the inner component in the next tick, a host framework that immediately queries the element’s shadow DOM will see nothing. Prefer your own events (`ready`) when the host must wait.

## Using web components inside Svelte

Svelte treats any element with a hyphen in its tag name as a custom element and passes attributes and properties accordingly: for custom elements it sets the *property* when the (registered) element has a setter for it, otherwise the attribute (for elements not yet defined, objects are set as properties), which means objects and functions flow properly, and event attributes `onxyz` map to listeners for the event `xyz`.

```html
<script lang="ts">
  import '@shoelace-style/shoelace/dist/components/button/button.js';
  let count = $state(0);
  let items = $state.raw([{ id: 1 }, { id: 2 }]);
</script>

<sl-button variant="primary" onclick={() => count++}>Clicked {count}</sl-button>
<x-list {items} onselect={(e: CustomEvent<number>) => console.log(e.detail)}></x-list>
```

A few practical points:

- Quoted attributes on custom elements and components are subject to the `attribute_quoted` warning (“will be stringified in a future version of Svelte”): write `{items}` rather than `items="{items}"`.
- `bind:this` gives you the element, from which you call its methods once it is defined and upgraded. If the element is defined lazily, `await customElements.whenDefined('x-list')` first.
- The `oneworld` problem described above applies to third-party elements with `on*` properties.
- Hyphenated tags are *not* treated as Svelte components, even when capitalised differently; Svelte components must begin with an uppercase letter or use dot notation, and a lowercase component name triggers `component_name_lowercase`.

### Typing custom elements in templates

With TypeScript, unknown elements are errors in the language tooling. The documented fix is to augment `svelte/elements`:

```ts
// src/custom-elements.d.ts
import type { HTMLAttributes } from 'svelte/elements';

interface XRatingAttributes extends HTMLAttributes<HTMLElement> {
  value?: number;
  label?: string;
  readonly?: boolean;
  onrate?: (e: CustomEvent<number>) => void;
}

declare module 'svelte/elements' {
  interface SvelteHTMLElements {
    'x-rating': XRatingAttributes;
  }
}

export {};   // makes this file a module so the augmentation merges
```

The file must be a module (hence the `export {}`), and be included by your `tsconfig`. For libraries that ship types, `svelte-html.d.ts`-style declarations through the `svelteHTML` namespace are the older mechanism; the `SvelteHTMLElements` augmentation above is what the docs now recommend. Note the event property name: it is `onrate`, the Svelte-style attribute, typed with your `CustomEvent` detail; this is how a consumer gets type-safe handlers.

If a third-party element’s property starts with `on` you can type it, but you cannot set it (the `oneworld` rule); use `bind:this` and assign it in an attachment.

## Building and publishing

Typical choices:

1.  **One bundle with all elements.** Build with Vite library mode, `customElement: true`, an entry that imports every element file (each registers itself through its `tag`). One runtime copy, one request, easy `<script type="module">` deployment.
2.  **Per-element entry points** (tree-shakable ESM): `import '@acme/elements/rating'` registers only that element. The runtime is a peer dependency (`svelte`), and consumers’ bundlers dedupe it. Beware version skew when several packages bundle different Svelte versions; `window.__svelte.v` (from `discloseVersion`) can show which majors are present.
3.  **No auto-registration**: omit `tag`, export the classes (`Component.element`) and let consumers choose names with `customElements.define`. This avoids tag name collisions when two versions of your library meet on a page, because `customElements.define` throws for an already-registered name.

```ts
// vite.config.ts (library mode)
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte({ compilerOptions: { customElement: true } })],
  build: {
    lib: { entry: 'src/index.ts', formats: ['es'], fileName: 'elements' }
  }
});
```

```ts
// src/index.ts
import './elements/Rating.svelte';       // self-registers x-rating
import './elements/Stepper.svelte';
export { default as Rating } from './elements/Rating.svelte';   // with `.element` for manual define
```

Publishing notes: ship type declarations (the `SvelteHTMLElements` augmentation above, plus a global `HTMLElementTagNameMap` entry for `document.querySelector('x-rating')` typing), document attributes versus properties, document events with their `detail` types and document CSS custom properties and parts, which are your styling API. Because styles are inlined into JavaScript, CSS-only theming by consumers is limited to what you expose.

Tag registration has a failure mode worth guarding in widely shared libraries: defining the same tag twice throws `NotSupportedError`. When your element may be loaded by several bundles, check `customElements.get('x-rating')` before defining, which you do by omitting `tag` and registering manually.

## Design guidelines for public elements

A custom element is a public API in the platform’s vocabulary, so design it as one:

- **Attributes for configuration, properties for data, events for output, slots for content, CSS custom properties and parts for styling.** Document each category. Do not expose internal Svelte concepts (snippets, bindings, context).
- **Keep the element thin.** Put the logic into ordinary Svelte components and modules, and wrap them in a small element component that maps attributes, properties and events. Tests then target the inner components in the normal way (Chapter 16), and the wrapper is tested only for its mapping.
- **Be defensive about timing.** Consumers will set properties before the element is connected, and will call methods too early. Buffering of properties is automatic; methods are your responsibility (`extend`).
- **Accessibility crosses shadow boundaries badly.** ID references (`for`, `aria-labelledby`, `aria-describedby`) do not cross shadow roots, so a label outside the element cannot reference an input inside it. Offer a `label` prop that becomes `aria-label` internally, use `delegatesFocus`, and make form-associated elements report their value through `ElementInternals` (Chapter 17 covers the underlying rules; the compiler checks the markup inside your element as usual).
- **Version the tag or the registration.** Two copies of an element on one page conflict on `customElements.define`; either let consumers register, or put a version in the tag name for widely embedded widgets.
- **Avoid global side effects at import time** beyond registration: importing the module should not fetch data or mutate the page.

## Testing custom elements

Our test used jsdom, which supports custom elements and shadow DOM well enough. Configure Vitest with the plugin option `compilerOptions: { customElement: true }` in a dedicated config (or `dynamicCompileOptions` for just the element files), import the component to register it, create the element via `innerHTML` or `document.createElement`, then `await tick()` before asserting on `el.shadowRoot`. Query inside the shadow root (`el.shadowRoot.querySelector(...)`); Testing Library queries do not pierce shadow roots by default, so use `within(el.shadowRoot)`-style helpers or a pierce-capable library. Use a real browser (Vitest browser mode, Playwright) for focus delegation, `::part` styling and form association, which jsdom does not model faithfully.

## Key takeaways

- Enable with the compiler option `customElement: true` (boolean or `({ filename }) => boolean` since 5.54) and describe each element with `<svelte:options customElement=...>`: a tag string or an object with `tag`, `shadow`, `props`, `extend`.
- Elements are wrappers around ordinary components: the inner component is created in the next tick after `connectedCallback`, updates render in the next tick, and it is destroyed in the next tick after `disconnectedCallback`. Properties set early are buffered; exported functions are not available before mount.
- All props must be enumerable at compile time (destructure them or list them in `props`), or you get `custom_element_props_identifier`. Use `attribute`, `reflect` and `type` to map attributes; pass rich data as properties.
- Never name props starting with `on`; `oneworld` becomes `addEventListener('eworld')`.
- Styles are encapsulated in the shadow root and always inlined in JavaScript; expose styling through CSS custom properties and `::part`. `shadow: 'none'` removes encapsulation and slots; `ShadowRootInit` objects are supported since 5.49.
- Use `$host().dispatchEvent(new CustomEvent(...))` for events (set `bubbles` and `composed` as needed); consumers listen with `onxyz` in Svelte or `addEventListener`.
- Slots are kept in custom elements, render eagerly in the DOM, and `let:` does nothing; snippets cannot cross the HTML boundary.
- Use `extend` for `ElementInternals`/form association and early methods; erasable TypeScript only, and `lang="ts"` on a script.
- Context does not cross element boundaries; SSR is not generally suitable; mind bundle duplication and polyfills.
- To use third-party elements in Svelte, type them by augmenting `SvelteHTMLElements` in `svelte/elements`, avoid quoted attributes and `on*` property names.

## Review Questions

1.  What are the two switches needed to compile a Svelte component as a custom element, and which warning do you get if you set only one?
2.  How can you compile only the files in `src/elements/` as custom elements?
3.  What is the difference between `customElement="x-a"` and the object form? Name the four keys of the object.
4.  Why might you intentionally omit `tag`, and how does a consumer then register the element?
5.  Describe the lifecycle: when is the inner component created and destroyed? What does this mean for code that runs `el.shadowRoot.querySelector(...)` right after `innerHTML = '<x-rating>'`?
6.  A teammate calls `el.focusInput()` on a custom element immediately after creating it, and it throws. Why, and what are two fixes?
7.  What does this component compile to in terms of warnings, and how do you fix it?

```html
<svelte:options customElement="x-card" />
<script lang="ts">
  let props = $props();
</script>
<p>{props.title}</p>
```

8.  Given `props: { value: { type: 'Number', reflect: true } }`, what happens when HTML contains `value="3"`, and what happens to the attribute when the component sets `value = 5`?
9.  How should you pass an array to a custom element from a framework that only supports attributes? From Svelte?
10. Explain the `oneworld` trap. Which direction does it affect: your own props, third-party props, or both?
11. List the `shadow` options and what each implies for styles and slots.
12. Why do your global Tailwind classes not style content inside the element, and what are three ways to deal with it?
13. Where do the styles of a custom element end up in the build, and what does the `css` compile option do for custom elements?
14. Write a handler in a custom element that dispatches a `change` event with `detail: value` that reaches listeners outside nested shadow roots.
15. What is `$host()`, what are its restrictions, and what error appears if used in a normal component?
16. Multiple choice: which statement about slots in a Svelte custom element is true?

<!-- -->

a.  Slot content is created lazily and only when the `<slot>` is rendered.
b.  Slot content is created eagerly by the DOM even if the `<slot>` is inside a false `{#if}`.
c.  `let:` passes data from child to slotted content.
d.  Slots work with `shadow: 'none'`.

<!-- -->

17. Why can’t a `children` snippet prop be supplied by an HTML consumer, and how should you design around it?
18. What does the `extend` option receive and return? Give two things it is good for.
19. Which TypeScript features may you not use in `extend`, and what must you set on the component scripts?
20. In what way does the `static formAssociated = true` example let the element take part in a form?
21. Explain why Svelte context set in one custom element is not visible in a child custom element, and name an alternative.
22. Why are Svelte custom elements “not generally suitable for server-side rendering”, and what can you do to reduce the visual impact?
23. How do you give Svelte templates type information about `<x-rating onrate={...}>`? Why must the declaration file contain `export {}`?
24. Find the bug: `<x-list items="{items}"></x-list>` in a Svelte template where `items` is an array.
25. What are the pros and cons of one bundle versus per-element entry points for distribution?
26. What happens if the same tag is defined twice, and how does omitting `tag` help library authors?
27. How would you test a custom element’s rendered output in Vitest, and what must you wait for?
28. When would you pick `shadow: 'none'` and what do you give up?
