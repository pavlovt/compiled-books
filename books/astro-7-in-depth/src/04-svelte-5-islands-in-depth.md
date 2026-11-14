# Chapter 3: Svelte 5 Islands in Depth

A Svelte island is the unit where Astro’s server-first model meets a client-side framework, and almost every production question about the combination reduces to the same thing: what crosses the boundary between the `.astro` page and the Svelte component, and in which form? Props cross as serialized data in an HTML attribute. Children cross as strings of static HTML. Functions, snippets with arguments, class instances, and Astro components do not cross at all. This chapter pins those rules down by taking the integration apart: its configuration, the markup it generates, the hydration lifecycle, the `client:*` directives (including writing your own), prop serialization with its silent failure modes, how `children` and named slots reach Svelte 5 components, `client:only` fallback, async server rendering, and finally the renderer API that `@astrojs/svelte` implements.

Unlike the other chapters, much of what follows is not in the official documentation, which still shows legacy Svelte syntax and says little about snippets. Everything below was verified by building a test project with `astro@7.4.1`, `@astrojs/svelte@9.1.0` and `svelte@5.57.2`, and by reading the integration’s published source. Where I report output, it is real output.

## Setup and configuration

The integration is a Vite plugin wrapper. `svelte()` in `astro.config.mjs` does three things in `astro:config:setup`: it registers the renderer (server and client entrypoints) with `addRenderer`, it registers the container renderer for the Container API (Chapter 17), and it adds `@sveltejs/vite-plugin-svelte` v7 to Vite with your options, plus a small plugin that configures SSR environments so that Svelte component libraries in `node_modules` are processed by Vite rather than loaded as raw `.svelte` by Node.

```js
// astro.config.mjs
import { defineConfig } from 'astro/config';
import svelte from '@astrojs/svelte';

export default defineConfig({
  integrations: [svelte()],
});
```

```js
// svelte.config.js
import { vitePreprocess } from '@astrojs/svelte';

export default {
  preprocess: vitePreprocess(),
};
```

### Where options come from

Options are the `@sveltejs/vite-plugin-svelte` options (`compilerOptions`, `preprocess`, `extensions`, `vitePlugin`, `onwarn`, `include`/`exclude`, and so on). They can be given in two places, and **options passed to `svelte({...})` in `astro.config.mjs` take precedence over `svelte.config.js`**:

```js
// astro.config.mjs
integrations: [svelte({ extensions: ['.svelte'] })],
```

Use `svelte.config.js` for what the *editor* also needs to know, because the Svelte language server and `svelte-check` read that file: preprocessors (`vitePreprocess()`) and `compilerOptions` that change how code must be understood (for example `experimental.async`). Use the integration options for build-only concerns. Since integration 6.0.0, `vitePreprocess()` is no longer added by default, so a project that needs SCSS or Stylus in `<style lang="...">` must create `svelte.config.js` as above.

`svelte` and `typescript` are peer dependencies; install them explicitly if your package manager does not.

> **Senior tip:** Do not create a `svelte.config.js` that duplicates options you pass in `astro.config.mjs` with different values; the precedence rule means the editor will analyze your components under settings the build does not use. Pick one home for each option.

## What an island is on the wire

Consider this component and page:

```html
<!-- src/components/Box.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    title,
    children,
    header,
  }: { title: string; children?: Snippet; header?: Snippet } = $props();

  let n = $state(0);
  const uid = $props.id();
</script>

<section>
  <h2>{title}</h2>
  <div class="hdr">{#if header}{@render header()}{/if}</div>
  <div class="body">{@render children?.()}</div>
  <button onclick={() => n++}>{n}</button>
  <span id={uid}>id</span>
</section>
```

```html
---
import Box from '../components/Box.svelte';
---
<Box title="A" client:load>
  <p>child <b>html</b></p>
  <span slot="header">HDR</span>
</Box>
<Box title="B"><p>ssr only</p></Box>
```

The first `<Box>` produces (abridged, whitespace added):

```html
<astro-island uid="1ODz0J" component-url="/_astro/Box.BjnOE2lr.js" component-export="default"
  renderer-url="/_astro/client.svelte.DOW8nnPa.js" props="{&quot;title&quot;:[0,&quot;A&quot;]}"
  ssr client="load" opts="{&quot;name&quot;:&quot;Box&quot;,&quot;value&quot;:true}" await-children>
  <!--[-->
  <section data-box="">
    <h2>A</h2>
    <div class="hdr"><!--[0--><astro-slot name="header"><span>HDR</span></astro-slot><!--]--></div>
    <div class="body"><astro-slot><p>child <b>html</b></p></astro-slot></div>
    <button>0</button> <span id="s1-s1">id</span>
  </section>
  <!--]-->
  <!--astro:end-->
</astro-island>
```

and the second, with no directive, produces only the Svelte HTML: no `<astro-island>`, no `astro-slot` wrapper around its children, no JavaScript reference. Compare the two and the lifecycle is visible.

1.  **Server render.** Astro asks each registered renderer whether it recognizes the component (`check`), then calls `renderToStaticMarkup` with the props and the slots (as HTML strings). For `@astrojs/svelte` that calls Svelte’s `render()` from `svelte/server`.
2.  **Wrap.** If a client directive is present, Astro wraps the HTML in `<astro-island>` and writes the component URL, the export name, the renderer URL, the serialized props, the directive name and its options into attributes.
3.  **Directive script.** One small script per directive type present on the page registers `Astro.load`, `Astro.idle`, etc. The shared `astro-island` class is defined once.
4.  **Browser.** When the directive decides it is time, the island element dynamically imports the component and the renderer’s client module (with one retry, after 1 second, on import failure), parses the `props` attribute, collects slots from the `<astro-slot>` and `<template data-astro-template>` descendants, calls `hydrator(this)(Component, props, slots, { client })`, removes the `ssr` attribute, and dispatches `astro:hydrate` on itself.

Three details to notice. First, an island nested inside another island waits: `hydrate` looks for a parent `astro-island[ssr]` and defers until the parent has hydrated (it listens for the parent’s `astro:hydrate` event). Second, the `await-children` attribute makes the island wait, during streaming, for its server-rendered children to finish arriving (it watches for the `<!--astro:end-->` comment) before starting. Third, if hydration throws, the island dispatches a cancelable, bubbling, composed `astro:hydration-error` event with `{ error, componentUrl }` in `detail`; if nothing calls `preventDefault()`, it logs `[astro-island] Error hydrating <url>` to the console. That event is your hook for client-side error reporting:

```ts
// src/scripts/island-errors.ts
window.addEventListener('astro:hydration-error', (e) => {
  const { error, componentUrl } = (e as CustomEvent<{ error: unknown; componentUrl: string }>).detail;
  navigator.sendBeacon('/api/client-errors', JSON.stringify({ componentUrl, message: String(error) }));
});
```

### The identity of `<astro-island>` in CSS

Astro injects `astro-island, astro-slot, astro-static-slot { display: contents }` once per page. The wrapper elements therefore do not participate in layout: flex and grid containers see the island’s children as their children. Selectors, however, do see the elements: `.parent > .child` fails if there is an `<astro-island>` between them. When a CSS combinator misbehaves around an island, inspect the DOM, not the template.

## Client directives

| Directive | Fetch/hydrate trigger | Options |
|------------------------|------------------------|------------------------|
| `client:load` | Immediately | none |
| `client:idle` | `requestIdleCallback` (falls back to `setTimeout` with the timeout, default 200 ms) | `{ timeout }` |
| `client:visible` | `IntersectionObserver` on the island’s children | `{ rootMargin }` |
| `client:media="(query)"` | `matchMedia` match | the media query string |
| `client:only="svelte"` | Immediately, with **no server rendering** | framework name (mandatory) |

```html
<Cart client:load />
<Recommendations client:idle={{ timeout: 500 }} />
<Reviews client:visible={{ rootMargin: '200px' }} />
<Gallery client:media="(min-width: 64em)" />
<MapWidget client:only="svelte"><p slot="fallback">Loading map…</p></MapWidget>
```

The options are serialized into the `opts` attribute. From the generated directive scripts: `client:visible` observes the island’s *children* (`for (const child of el.children) observer.observe(child)`), which is why an island whose root is `display: contents` still works, and why an island with no element children never becomes visible, so `client:visible` on a component that renders nothing, or only text, never hydrates. Give such components a real root element.

### Choosing directives

Use the cheapest trigger that still meets the interaction requirement.

- `client:load` for anything interactive above the fold that the user may touch immediately: the cart badge, the mobile menu button, search.
- `client:idle` for things that must work soon but not now: a newsletter popover, analytics consent.
- `client:visible` for anything below the fold: reviews, a comment box, a long carousel. The JavaScript is not even downloaded until the user scrolls near it.
- `client:media` for responsive-only interactivity.
- `client:only="svelte"` when server rendering is impossible or pointless (the component depends on `window` at import time, or on a browser-only library) or the component is an entire SPA.

Directives are also a *dependency* decision. A component with `client:visible` is a code-split point: its chunk and everything only it imports is loaded lazily. Shared code (the Svelte runtime, a rune module imported by several islands) goes into shared chunks.

### Custom directives

An integration can add a directive with `addClientDirective`, which maps `client:<name>` to an entrypoint. The entrypoint default-exports a function `(load, opts, el)`; calling `await load()` returns the hydrate function, and calling that hydrates the island. I built the following and confirmed the output.

```js
// astro.config.mjs
import { defineConfig } from 'astro/config';
import svelte from '@astrojs/svelte';

const onInteraction = () => ({
  name: 'on-interaction',
  hooks: {
    'astro:config:setup': ({ addClientDirective }) => {
      addClientDirective({ name: 'click', entrypoint: './directives/click.js' });
    },
  },
});

export default defineConfig({ integrations: [svelte(), onInteraction()] });
```

```js
// directives/click.js
/** @type {import('astro').ClientDirective} */
export default (load, opts, el) => {
  const event = typeof opts.value === 'string' ? opts.value : 'click';
  el.addEventListener(
    event,
    async () => {
      const hydrate = await load();
      await hydrate();
    },
    { once: true },
  );
};
```

```html
<Add client:click="pointerdown" id="x" />
```

The build emits a directive script registering `Astro.click` and an island with `client="click"` and `opts="{&quot;name&quot;:&quot;Add&quot;,&quot;value&quot;:&quot;pointerdown&quot;}"`. Note that `opts.value` is the directive’s attribute value, and that `el` is the `<astro-island>` element, whose server-rendered children are available for listeners. To add types for the new directive, augment `AstroClientDirectives`:

```ts
import 'astro';
declare module 'astro' {
  interface AstroClientDirectives {
    'client:click'?: boolean | string;
  }
}
```

Directive entrypoints are bundled by esbuild and inlined into the page, so keep them small. Chapter 18 covers `addClientDirective` among the integration APIs.

> **Warning:** A hydration trigger that waits for user input (like `client:click`) leaves the island inert until then. For a button, that is fine only if the first click is *replayed* after hydration, and Astro does not replay events. Use trigger events that precede the real action (`pointerenter`, `focusin`, `touchstart`) rather than the action itself.

## Serializable props

Props to a hydrated island are serialized into the `props` attribute by Astro’s own serializer (not JSON, not devalue). Each value is encoded as `[type, payload]`. Verified against the source:

| Value | Wire form | Revived on the client as |
|------------------------|------------------------|------------------------|
| plain object, array, string, number, boolean, `null` | `[0, …]` (JSON-like) | itself |
| `RegExp` | `[2, source]` | `new RegExp(source)` (**flags are lost**) |
| `Date` | `[3, isoString]` | `Date` |
| `Map` | `[4, entries]` | `Map` |
| `Set` | `[5, values]` | `Set` |
| `BigInt` | `[6, "10"]` | `BigInt` |
| `URL` | `[7, href]` | `URL` |
| `Uint8Array`, `Uint16Array`, `Uint32Array` | `[8..10, numbers]` | typed array |
| `Infinity` | `[11, sign]` | `±Infinity` |

I built a component receiving a `Date`, `Map`, `Set`, `URL`, `BigInt`, a `/x/g` regular expression and a function. The server HTML printed `object 1 2 http://a.b/ 10 /x/g undefined`, and the `props` attribute was:

```json
{"d":[3,"2026-10-19T20:39:47.458Z"],"m":[4,[[1,[[0,1],[0,2]]]]],"s":[5,[[0,1],[0,2]]],
 "u":[7,"http://a.b/"],"big":[6,"10"],"re":[2,"x"]}
```

Two things stand out. The regular expression arrives on the client without its `g` flag (the server render sees `/x/g`, the client sees `/x/`), so server HTML and hydrated behaviour can diverge. And the `fn` prop is absent from the attribute entirely.

### Silent failures

Functions are not an *error*. Passing `fn={() => 1}` to a hydrated island built successfully; the serialized form was `{"fn":[0,null]}`, so the server render received a real function (and `typeof fn` was `"function"`) and the client received `null`. This is the most dangerous property of the boundary: a callback prop works in the server HTML, then vanishes at hydration. There is no build error, no warning.

```html
<!-- Looks fine, is broken: onSelect is null in the browser -->
<ProductList client:load products={products} onSelect={(id) => track(id)} />
```

Other cases:

- **Circular references fail the build** with `Cyclic reference detected while serializing props for <Props client:load>! Cyclic references cannot be safely serialized for client-side usage.` (I triggered it with `const o = {}; o.self = o;`). The error is thrown from the serializer while rendering the page, so it surfaces at build time for prerendered pages and at request time (a 500) for on-demand ones.
- **Class instances** are serialized by their own enumerable properties as plain objects, so methods and prototypes are lost. Pass data, not behaviour.
- **`undefined` values** vanish like in JSON.
- **Svelte snippets, render functions and `$state` proxies** do not cross.
- **Size matters**: the entire props payload is embedded in the HTML, so a 500 KB product list passed as a prop is 500 KB of HTML plus the HTML it renders. Pass an id and fetch, or trim to what the island displays.

> **Warning:** Anything you pass as a prop is readable in the page source. Never pass tokens, internal ids you consider private, or entire database rows when the island needs three fields.

### Patterns that work

Pass serializable *data* and let the island own behaviour. For callbacks, use events (Chapter 4) or a shared rune module:

```html
<!-- ProductList.svelte -->
<script lang="ts">
  let { products }: { products: { id: string; name: string }[] } = $props();

  function select(id: string) {
    window.dispatchEvent(new CustomEvent('product:select', { detail: { id } }));
  }
</script>

<ul>
  {#each products as p (p.id)}
    <li><button onclick={() => select(p.id)}>{p.name}</button></li>
  {/each}
</ul>
```

For dates, remember that a `Date` crosses as a `Date`, but `new Date().toLocaleString()` rendered on the server and again in the browser will produce different strings (server time zone and locale versus the user’s). If a value must be identical, format it on the server and pass the string, or format only on the client after hydration.

### Bindable props

`$bindable()` props cannot be bound from an `.astro` file, because an Astro template has no reactivity and no assignment target. A bindable prop simply behaves as a one-way input from Astro. Two-way binding exists only between Svelte components within the same island.

## Children and named slots

Astro passes slot content to a renderer as `Record<string, string>`: slot name to HTML. The default slot has the key `default`. There is no component structure here, only markup that was rendered by Astro on the server. The official guide says Svelte “uses `<slot />`”; it does not mention snippets. Since the integration’s 5.7.3 release it supports both, and I tested every combination.

### What the integration does

The server entrypoint turns every slot into a Svelte *raw snippet* wrapping the HTML in an `<astro-slot>` element (an `<astro-static-slot>` for components that will not hydrate, which Astro then strips), and passes it in three forms at once:

1.  a `children` snippet prop for the default slot;
2.  a snippet prop *named after each named slot*;
3.  a legacy `$$slots` map with the same snippets, for `<slot />`-style components.

The client entrypoint reconstructs the same snippets from the `<astro-slot>` elements’ `innerHTML` and passes them to `hydrate()`, so server and client output match, and no child component code runs in the browser.

### Svelte 5 style: snippet props

```html
<!-- Panel.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    title,
    children,
    header,
    footer,
  }: { title: string; children?: Snippet; header?: Snippet; footer?: Snippet } = $props();
</script>

<section>
  <header>{#if header}{@render header()}{:else}<h2>{title}</h2>{/if}</header>
  <div class="body">{@render children?.()}</div>
  {#if footer}<footer>{@render footer()}</footer>{/if}
</section>
```

```html
<Panel title="Cart" client:load>
  <p>Two items</p>
  <a slot="footer" href="/checkout">Checkout</a>
</Panel>
```

Results of my tests:

- The default slot arrives as `children`, rendered by `{@render children?.()}`. Output: `<astro-slot>…the children…</astro-slot>`.
- A named slot arrives as a prop with the slot’s name: `slot="header"` becomes `header`. The *absence* of a slot means the prop is `undefined`, so `{#if header}` correctly detects it (in the first example, `Box B`, which had no header, rendered `<!--[-1-->` for the false branch).
- **Slot names are not camel-cased for Svelte.** The docs say kebab-case names are “preserved” for Svelte, and that is literal. For `slot="my-slot"` the component receives a prop whose key is `'my-slot'`, and for `slot="mySlot"` a prop `mySlot`. I rendered both from one component whose props were `['children', 'my-slot', 'mySlot']`. A kebab-case name can only be reached with bracket access on the props object (`let all = $props(); all['my-slot']`), which is awkward. Use single-word or camelCase slot names for Svelte targets (React, Preact and Solid, by contrast, convert kebab-case to camelCase).
- You can call `$props()` **only once** per component. Destructuring with a rest element or keeping the object (`let all = $props()`) are the two options when you need dynamic keys; a second `$props()` call is a compile error (`props_duplicate`).

### Legacy style: `<slot />`

Components written with `<slot />` and `<slot name="side" />` still receive the content, in a component using the legacy slot API (a component that uses `<slot>` is in “legacy mode” for that feature, so mixing it with runes in the same component is not allowed by Svelte’s own rules; see the Svelte book). Output for `<slot />` and `<slot name="side" />` is `<astro-slot>…</astro-slot>` and `<astro-slot name="side">…</astro-slot>`. For new code, use snippets: it is the Svelte 5 idiom, works with TypeScript, and lets the component declare which slots it accepts.

### What a “slot” cannot be

A snippet prop in Svelte can take parameters: `{@render row(item)}`. Astro cannot supply such a snippet, because the slot has already been rendered to a static string on the server; there is nothing to call with `item`. A component designed around parameterized snippets (a generic table with a `row` snippet) cannot be driven from an `.astro` file. Two approaches: wrap it in a thin Svelte component that supplies the snippets and import *that* from Astro, or pass data props and let the Svelte component render its own markup.

For the same reason, Astro-rendered content inside an island is *static*. It does not re-render when island state changes. If an `.astro` component’s output is put in a slot of a hydrated Svelte component and the Svelte component conditionally renders `{@render children()}`, the HTML appears and disappears, but its content never changes.

### Typing slots in `.astro` files

`@astrojs/svelte` ships `svelte-shims.d.ts` with helper types (`PropsWithClientDirectives`, `HandleSnippetProps`) used by the language tooling. They exist so that a Svelte component with `children?: Snippet` or with required `Snippet`-typed props can be used from `.astro` without type errors: `children` is widened to accept Astro content, `client:*` attributes are added, and *other* snippet-typed or `any`-typed props are made optional, since Astro cannot provide snippets with arguments. The practical consequence: a required `header: Snippet` prop will not make the `.astro` call site fail type-checking, but at runtime it is `undefined` unless the caller provides `slot="header"`. Type slots as optional and guard with `{#if header}`.

### Nesting islands inside slots

Children of an island can themselves be islands:

```html
<Panel client:load title="Menu">
  <CartButton client:idle slot="footer" />
</Panel>
```

The inner island is rendered on the server inside the outer one’s slot HTML, and in the browser it waits for the outer island’s hydration (the `astro-island[ssr]` parent check described earlier), then hydrates by its own directive. Two things to know: the inner island’s `<astro-island>` markup becomes part of the string that the outer island’s client entrypoint re-injects as a raw snippet, so the DOM that the outer Svelte component controls contains the inner island; and if the outer component conditionally removes that slot from the DOM, the inner island is destroyed, and will not return. Use this pattern only when the inner island’s lifetime matches the slot’s.

## `client:only` and fallback content

`client:only="svelte"` skips server rendering. The page contains the `<astro-island>` and whatever fallback you provide, and the island mounts as soon as the page loads. From my build of `<Box client:only="svelte"><p slot="fallback">loading...</p><p>kid</p></Box>`:

```html
<astro-island ... client="only" opts="{&quot;name&quot;:&quot;Box&quot;,&quot;value&quot;:&quot;svelte&quot;}" await-children>
  <p>loading...</p>
  <template data-astro-template><p>kid</p></template>
  <template data-astro-template="fallback"><p>loading...</p></template>
  <!--astro:end-->
</astro-island>
```

Content marked `slot="fallback"` is visible until the island mounts; the regular children are stashed in `<template data-astro-template>` elements that the client reads (these `template` elements are what `hydrate()` scans for in addition to `<astro-slot>`). Then the client entrypoint calls `mount()` rather than `hydrate()` after clearing the island’s `innerHTML`, which removes the fallback. Integration 7.0.7 fixed a bug where fallback content remained visible after `client:only` rendering.

Design considerations for `client:only`:

- The component never appears in server HTML. SEO and no-JS users see only the fallback. Reserve it for widgets (maps, editors, charts) where that is acceptable.
- Layout shift: give the fallback the same dimensions as the component.
- It still needs the framework name, because Astro never loaded the component on the server and cannot detect the renderer. With a typo, the build cannot find a renderer for the name.
- Since the server never ran the component, module-level browser-only imports (`import Chart from 'some-lib-using-window'`) are safe inside it, while in a normal island they would crash SSR.

## Server-rendering concerns in Svelte components

Because a hydrated component runs in both worlds, the top level of its `<script>` executes on the server, once per render.

### Browser-only code

```html
<script lang="ts">
  import { onMount } from 'svelte';

  let theme = $state<'light' | 'dark'>('light');

  onMount(() => {
    theme = (localStorage.getItem('theme') as 'light' | 'dark' | null) ?? 'light';
  });

  $effect(() => {
    document.documentElement.dataset.theme = theme;
  });
</script>
```

`onMount` and `$effect` do not run on the server. Anything else at the top level (including `$derived` expressions) may. A frequent bug is a `$derived` that reads `window.innerWidth`.

### Module-level state on the server

A Svelte module’s top-level state lives for the life of the *process* in the server environment. I verified it directly: a rune module with `export const shared = $state({ n: 0 })` incremented in two components during one page render printed `n=1` and `n=2`; state accumulated across renders. In a long-running Node server, that is state shared **between visitors**. Chapter 4 treats this hazard and its fixes in depth; the short rule is that module-level mutable state belongs on the client only.

### `$props.id()`

`$props.id()` returns an id unique per component instance, suitable for `id`/`for`/`aria-*` wiring. It must be assigned at the top level of the component script (`const uid = $props.id();`); using it inline in the template is a compile error (`props_id_invalid_placement`). With Astro, the renderer passes an `idPrefix` per island (`s0`, `s1`, …), so ids are unique across islands on the same page (they looked like `s1-s1` in my output). Integration 7.0.6 fixed a case in which they were not.

### Async SSR

Svelte’s `await` expressions are experimental in Svelte 5.57 and enabled with a compiler option. Integration 7.2.0 added server support. Enable it in `svelte.config.js`, which both Astro and the editor read:

```js
// svelte.config.js
import { vitePreprocess } from '@astrojs/svelte';

export default {
  preprocess: vitePreprocess(),
  compilerOptions: { experimental: { async: true } },
};
```

```html
<!-- Async.svelte -->
<script lang="ts">
  let { id }: { id: number } = $props();
  const data = $derived(
    await new Promise<{ title: string }>((r) => setTimeout(() => r({ title: 'T' + id }), 20)),
  );
</script>

<h1>{data.title}</h1>
<p>{await Promise.resolve('direct')}</p>
```

With `<Async id={7} />` and `<Async client:load id={8} />`, both rendered fully on the server (`<h1>T7</h1> <p>direct</p>`; the hydrated instance’s markup was identical). So async work completes during `render()` and Astro’s response waits for it. Remember that the awaited promise runs again in the browser on hydration for a `client:*` component, unless it is guarded; Svelte’s `hydratable` helper is its mechanism for transferring server results, see the Svelte book. Svelte 6 will make the async option default, so enabling it now is a forward-compatible choice.

## Mixing frameworks and the Astro boundary

An `.astro` file may import components from any number of renderers, and each renders according to its extension (`.svelte` goes to `@astrojs/svelte`). Where two integrations share an extension (`.jsx` for React and Preact), you must configure `include`/`exclude`. Svelte has a unique extension, so there is no ambiguity.

The one-way rule: **`.astro` can import `.svelte`; `.svelte` can never import `.astro`.** A Svelte island is “entirely valid Svelte”, compiled by Svelte, with no knowledge of Astro’s template compiler. To get Astro-rendered markup into an island, render it in the `.astro` page and pass it as a slot:

```html
---
import Panel from '../components/Panel.svelte';
import ProductSpecs from '../components/ProductSpecs.astro';
import { Image } from 'astro:assets';
import hero from '../assets/hero.jpg';
---
<Panel client:load title="Details">
  <ProductSpecs slot="header" product={product} />
  <Image src={hero} alt="Hero" />
</Panel>
```

Likewise, Astro features that live in `.astro` (`<Image>`, `getImage()`, `astro:assets`’s `<Font>`) cannot be *called* from Svelte: a Svelte island cannot use `<Image>`. Pass an `<Image>` through a slot, or run `getImage()` in frontmatter and pass the resulting `src`, `width`, `height` and `srcset` as serializable props. (`getImage()` throws if invoked in the browser, since 6.0.) Chapter 13 shows the patterns.

And the converse: **hydrating an Astro component with `client:*` is an error.** An Astro component has no client runtime; if you need browser behaviour, put a `<script>` in it or write the piece in Svelte.

## The renderer API, implemented

A renderer is an integration that calls `addRenderer({ name, clientEntrypoint, serverEntrypoint })`. Understanding the two entrypoints explains every behaviour above, so here is what `@astrojs/svelte` 9.1.0 does, from its source.

### Server entrypoint: `check` and `renderToStaticMarkup`

Astro iterates its renderers, calling `check(Component, props, slots)` until one returns true. For Svelte:

```js
function check(Component) {
  if (typeof Component !== 'function') return false;
  const componentString = Component.toString();
  return componentString.includes('$$payload') || componentString.includes('$$renderer');
}
```

The heuristic: Svelte 5 server-compiled components are functions taking a `$$renderer` (formerly `$$payload`) parameter, which survives because Astro does not minify the SSR build. The source comment calls it “not the best check”, with rendering as the last-resort alternative. The practical consequence is that a minified or transformed SSR output could defeat detection, which is why `client:only` requires an explicit framework name.

Then `renderToStaticMarkup(Component, props, slots, metadata)` builds the snippets described above, calls `render(Component, { props, idPrefix })` from `svelte/server`, awaits it (this is why async SSR works), strips empty `class=""` attributes as a workaround for a Svelte bug, and returns `{ html }`. It chooses `astro-slot` as the wrapper element when `metadata.hydrate` is set and `astro-static-slot` otherwise, and declares `supportsAstroStaticSlot: true`, which tells Astro it may remove the static wrappers from the final HTML. That is why the non-hydrated `Box B` contained plain `<p>ssr only</p>`.

### Client entrypoint: hydrate or mount

The client module default-exports `(element) => async (Component, props, slotted, { client }) => { … }`. In `@astrojs/svelte`:

- If the element has no `ssr` attribute (already hydrated), it returns immediately.
- It builds snippet props from `slotted` exactly as the server did.
- If this element already has an application (tracked in a `WeakMap`), it calls `setProps()` on it, which assigns the new props into a `$state` object, removing keys that disappeared. This is how the island is *updated* when `<astro-island>`’s `props` attribute changes, which is what happens when a persisted island is re-rendered by the client router (Chapters 4 and 14).
- Otherwise it creates the app with `hydrate()` (for every directive except `only`) or `mount()` after `target.innerHTML = ""` (for `client:only`). Props live in a `$state` proxy passed to Svelte, so `setProps` later updates the running component reactively.
- It registers `element.addEventListener('astro:unmount', () => component.destroy(), { once: true })`. Astro dispatches `astro:unmount` on the island root when it is removed from the document (during client-router navigations the island checks `isConnected` after `astro:after-swap`). Calling Svelte’s `unmount()` runs component teardown and `onMount` cleanups. Custom renderers and your own scripts can listen for the same event.

```ts
// Cleaning up a non-Svelte resource tied to an island's lifetime
document.querySelectorAll('astro-island').forEach((island) => {
  island.addEventListener('astro:unmount', () => console.log('island destroyed'), { once: true });
});
```

### Writing a renderer

The renderer reference’s minimal example gives the contract: a server module default-exporting `{ name, check, renderToStaticMarkup }` (optionally `supportsAstroStaticSlot`), and a client module as above. `renderToStaticMarkup` may return `{ html, attrs }`; `metadata.hydrate` is `'load' | 'idle' | 'visible' | 'media' | 'only' | undefined`, with `hydrateArgs` carrying the directive’s value; `astroStaticSlot` signals the static-slot convention. Chapter 18 builds on this.

## Testing and debugging islands

A short debugging checklist when an island misbehaves:

1.  **View source.** Is there an `<astro-island>`? Is the `client` attribute what you expect? Does `props` contain the data (and `null` where you passed a function)?
2.  **Network tab.** Did the `component-url` and `renderer-url` modules load? A `client:visible` island with no element children never loads.
3.  **Console.** Look for `[astro-island] Error hydrating`. Listen to `astro:hydration-error` for details.
4.  **Hydration mismatch.** The server HTML and client first render differ: time, locale, `Math.random()`, `window` checks in the template, regex flags, browser-reparsed invalid HTML. Svelte warns in development.
5.  **Is the module state shared?** Two islands importing the same rune module share state in the browser (one shared chunk, verified in a build), but the *server* shares it across requests (Chapter 4).

> **Senior tip:** When a Svelte island needs an Astro-computed value only at hydration, pass it as a `data-*` attribute on a wrapper element, or as a plain-data prop. Do not reach for `window.__DATA__` globals unless you control the ordering; islands can hydrate before or after any script on the page.

## Key takeaways

- `svelte({...})` options override `svelte.config.js`. Use `svelte.config.js` for editor-relevant settings (`vitePreprocess()`, `compilerOptions`) and remember `vitePreprocess()` is no longer added by default.
- A hydrated island is an `<astro-island>` carrying component URL, renderer URL, serialized props, directive and options. It imports, deserializes, collects slots, hydrates, and dispatches `astro:hydrate`; failures dispatch a cancelable `astro:hydration-error`.
- Props use Astro’s own serializer. Supported: objects, arrays, numbers, strings, `Date`, `Map`, `Set`, `RegExp` (flags lost), `BigInt`, `URL`, three typed arrays and `Infinity`. Functions silently become `null` on the client; cycles fail; class instances become plain objects.
- Slots reach Svelte as static HTML wrapped in `<astro-slot>`. The default slot is `children` (and legacy `<slot />`), named slots are props with the same name; kebab-case names are preserved, not camel-cased. Snippets with parameters cannot be supplied from Astro.
- `client:visible` observes the island’s element children; an island without element children never hydrates.
- `client:only="svelte"` skips server rendering, shows `slot="fallback"` content until mount, and needs the framework name.
- Top-level island code runs on the server. Guard browser APIs with `onMount`/`$effect`. Module-level state in the server environment persists across requests.
- `$props.id()` must be a top-level declaration and is unique across islands thanks to a per-island prefix. Async SSR needs `compilerOptions.experimental.async` and works with `await` in `$derived` and markup.
- `.astro` can import `.svelte` but not the reverse; Astro-rendered content enters an island only through slots. You cannot hydrate an Astro component.
- The Svelte renderer’s `check` inspects the compiled function for `$$renderer`/`$$payload`, `renderToStaticMarkup` calls `svelte/server`’s `render`, and the client entrypoint `hydrate`s or `mount`s, updates props in place and destroys on `astro:unmount`.

## Review Questions

1.  Which takes precedence if `svelte({ compilerOptions: { runes: true } })` in `astro.config.mjs` and `compilerOptions: { runes: false }` in `svelte.config.js` disagree? Why might this still produce confusing editor behaviour?

2.  A project has `<style lang="scss">` in a Svelte file and no `svelte.config.js`. What happens, and what is the minimal fix?

3.  List, in order, the four steps from server render to a hydrated island, naming the attribute or element involved in each.

4.  What does the `await-children` attribute do, and why is it needed in a streaming context?

5.  An island nested inside another island’s slot is placed on a page. In what order do they hydrate, and what mechanism enforces that?

6.  A `client:visible` component’s root template is `{#if open}<div>…</div>{/if}` with `open = false` initially. When does it hydrate, and why?

7.  Write a custom client directive `client:hover` that hydrates on the first `pointerenter`. Which two files and which hook are involved? How do you type it?

8.  What does each of these produce on the client? (a) `d={new Date()}`; (b) `re={/ab/gi}`; (c) `fn={() => 1}`; (d) `m={new Map([[1, 2]])}`; (e) `o={new Foo()}` where `Foo` is a class with a method.

9.  A teammate passes `onSelect={(id) => …}` to `<ProductList client:load />` and reports that it works in the initial HTML but not after hydration. Explain precisely why, and give two correct alternatives.

10. What error is raised, and when, if a prop contains a circular reference? What differs between a prerendered and an on-demand page?

11. Why is it a bad idea to pass an entire 400 KB product catalogue as a prop to a `client:visible` island, even though the island hydrates lazily?

12. Which of these does Astro’s props serializer support? (a) `Uint8Array`; (b) `Float32Array`; (c) `Set`; (d) `Symbol`; (e) `Infinity`; (f) `Promise`.

13. Given `<Panel client:load><p>x</p><b slot="footer">y</b></Panel>`, write a Svelte 5 `Panel.svelte` with typed props that renders both, and explain how an absent `footer` is detected.

14. A component uses `<slot name="my-slot" />` in legacy style, and another uses `let { 'my-slot': mySlot } = $props()`. Does Astro’s `slot="my-slot"` reach both? What about `slot="mySlot"`?

15. Why can `{@render row(item)}` with a `row` snippet taking a parameter not be fed from an `.astro` template? Give a workaround.

16. Find the bug:

    ```html
    <script lang="ts">
      let { id } = $props();
      const label = `field-${$props.id()}`;
    </script>
    <input id={$props.id()} aria-label={label} />
    ```

17. What exactly happens to the content `<p slot="fallback">Loading</p>` on a `<Chart client:only="svelte">`? Which function does the client entrypoint call and why not `hydrate()`?

18. Why does `client:only` still require the string `"svelte"`, whereas `client:load` does not?

19. A `client:load` Svelte component reads `localStorage.getItem('cart')` at the top of its script. What happens during the page build? List two fixes.

20. A rune module `cart.svelte.ts` exports `export const cart = $state({ items: [] })`. Two requests are served by one Node process, and each page imports it in a `client:load` island. What is the problem on the server and what is *not* a problem in the browser?

21. How do you enable `await` in Svelte components used as Astro islands, where must the option live so the editor agrees with the build, and what does the integration have to do on the server for it to work?

22. Which side imports which: can a `.svelte` file import an `.astro` file? Can an `.astro` file hydrate another `.astro` file with `client:load`? What are the two supported ways to put Astro-rendered markup inside an island?

23. How can a Svelte island display an optimized image produced by `astro:assets`? Why can it not use `<Image>` directly?

24. What does `check()` in `@astrojs/svelte` inspect, and what limitation of the approach explains why `client:only` needs a framework hint?

25. Describe what the client entrypoint does when the island’s `props` attribute changes after it has already been hydrated. Which Svelte mechanism makes the update reactive?

26. When is `astro:unmount` dispatched and what does the Svelte renderer do in response? Write a snippet that logs when a specific island is removed.

27. Multiple choice. Which statement about `astro-slot` is correct? (a) It is a Svelte built-in element; (b) it is a display: contents wrapper that Astro’s runtime and the Svelte renderer use to mark slot content; (c) it appears only for `client:only` components; (d) it can be styled with `:global(astro-slot)` only in SvelteKit.

28. Design question. A page needs a map (browser-only library, below the fold), a search box (must work immediately), and a “recently viewed” list (personalized, below the fold, server data). Choose directives or island types for each and justify, noting what each costs in JavaScript and in SEO/no-JS behaviour.
