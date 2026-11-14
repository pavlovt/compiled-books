# Chapter 14: ClientRouter, View Transitions and Prefetch

Astro’s default navigation model is the plain browser one: click a link, the browser tears down the document and loads a new one. That is fast, simple, and robust, and it is the right default. Two opt-in features change it. `<ClientRouter />` turns the site into a hybrid: still server-rendered multi-page HTML, but with navigations intercepted, the next page fetched with `fetch()`, and the DOM swapped in place, optionally animated with the View Transitions API. Prefetching, a separate feature that `<ClientRouter />` happens to enable by default, fetches pages ahead of the click so navigation feels instant either way.

This chapter explains the router’s navigation algorithm precisely (because every bug you will meet comes from a misunderstanding of it), the `transition:*` directives, script and island behavior across swaps with a Svelte 5 focus, the lifecycle events and custom swap functions, forms, accessibility, and the prefetch strategies including the experimental `clientPrerender`. It also lists the APIs removed in 6.0 and 7.0, which matter when you read older tutorials. I verified directive output by building a page with persisted Svelte islands (Astro 7.4.1, `@astrojs/svelte` 9.1.0); behaviors that only exist in a live browser (animations, focus restoration) come from the documentation and I mark them as such.

> **Note:** There are two distinct things called view transitions. *Browser-native cross-document view transitions* (CSS `@view-transition`) animate ordinary multi-page navigations with no JavaScript. *Astro’s `<ClientRouter />`* is a JavaScript router built on the same-document View Transitions API with extras: persistence, fallbacks, lifecycle events. The Astro docs themselves say the router will become less necessary as the platform matures. Choose the router when you need persisted state, not merely for animation.

## When to use `<ClientRouter />`

Use it when pages share live client state: an audio player, a cart island with local state, a sidebar with scroll position, a video that must keep playing, a persistent WebSocket connection. Use it when you want shared-element animations between pages. Do not use it merely to make navigation faster: prefetching plus regular navigation is usually faster to build and more robust, and does not change the script execution model.

The costs are real:

- Scripts no longer run on every navigation (details below), so every inline `DOMContentLoaded` assumption breaks.
- Global state accumulates: event listeners added by page scripts and not removed will pile up.
- Content Security Policy is not compatible with `<ClientRouter />` (Chapter 16): the router must run scripts and swap inline styles it fetched from the network.
- You take on responsibility for accessibility behaviors (focus, announcements) that the browser provides for free on full loads. Astro handles route announcements, but not everything.
- Error handling changes: a failed `fetch` or a non-HTML response falls back to a full navigation.

## Enabling it

Add the component to the `<head>` of every page that should participate, which in practice means your shared layout. Both the source and destination page must include it, otherwise the navigation is a full page load.

```html
---
// src/layouts/Base.astro
import { ClientRouter } from 'astro:transitions';
const { title } = Astro.props;
---
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>{title}</title>
    <ClientRouter />
  </head>
  <body><slot /></body>
</html>
```

The component renders two `<meta>` tags and a bundled module script. In my build the output contained:

```html
<meta name="astro-view-transitions-enabled" content="true">
<meta name="astro-view-transitions-fallback" content="animate">
<script type="module" src="/_astro/ClientRouter.astro_astro_type_script_index_0_lang.C6g13bIw.js">
```

The `fallback` prop (`'animate'` default, `'swap'`, `'none'`) controls browsers without View Transitions API support (Firefox for much of the router’s history; check current support): `animate` simulates transitions with attributes and CSS animations before swapping; `swap` swaps immediately with no animation; `none` does a full page navigation where unsupported. The documented limitation is that the `initial` animation is not simulated. Because the fallback is a separate code path, test it explicitly in a non-Chromium browser.

`supportsViewTransitions` and `transitionEnabledOnThisPage()` from `astro:transitions/client` expose the two facts a component might need: whether the browser supports it and whether this page includes the router.

## The navigation algorithm

Everything in this chapter follows from the sequence below (from the guide). Memorize the order.

1.  A navigation is triggered by a click on an internal `<a>`, a back or forward traversal, a form submission, or `navigate()`.
2.  The router starts fetching the target page. **Events:** `astro:before-preparation` fires first; the response is parsed into a `Document`; `astro:after-preparation` fires.
3.  `data-astro-transition="forward" | "back"` is set on `<html>`.
4.  `document.startViewTransition()` is called: the browser snapshots the old page.
5.  Inside the callback, the **swap**: `astro:before-swap` fires with `newDocument` and a `swap()` function, then the default swap runs:
    - `<head>`: stylesheets present in the new page are *kept* (avoiding a flash of unstyled content), scripts present in the new page are kept, other head elements are replaced unless marked `transition:persist` and present in both.
    - `<body>` is replaced wholesale with the new body.
    - Elements and islands with `transition:persist` are moved into the new DOM.
    - Scroll is restored.
    - `astro:after-swap` fires on `document`.
6.  The router waits for new stylesheets to load, then resolves the transition (the browser plays the animations).
7.  New scripts execute.
8.  `astro:page-load` fires. Navigation is complete.

Two consequences deserve emphasis. First, the page is *swapped, not reloaded*: `window`, `document`, global variables, module-level state and any listener on `window` or `document` all survive. Only the contents of `<body>` and non-persisted `<head>` elements change. Second, between steps 5 and 8 the old page’s JavaScript is still alive while the new body is already in the DOM. Islands in the new body are hydrated by the same `astro-island` custom element machinery as on a full load, which is why client directives (`client:visible`, `client:idle`) keep working across navigations.

Non-HTML responses, network failures, `data-astro-reload` links, cross-origin links, links with `target`, `download`, modifier-key clicks, and hash-only changes are not intercepted or are handled by falling back to the browser.

## Transition directives

Four template directives control animation and persistence. They apply to HTML elements and, when added to a component, to the component’s *root* element or island wrapper.

### `transition:name`

Astro infers matching pairs of elements between the old and new pages from element type and DOM position, and assigns them a shared `view-transition-name`. Override it with `transition:name="hero"` on the old and new elements to force a pairing, for instance a thumbnail on a listing page and the full image on a detail page; the browser then animates the geometry between them. A name must be unique on a page.

### `transition:animate`

Selects the animation for the element’s old and new snapshots:

- `fade` (default): crossfade.
- `initial`: browser’s own default animation (not simulated in the fallback).
- `slide`: old content slides out to the left, new content in from the right; reversed on back navigation.
- `none`: disable animation. Put it on `<html>` together with `transition:name="root"` to disable the default page-wide crossfade, then opt in per element.

`fade({ duration })` and `slide({ duration })` from `astro:transitions` customize durations. A custom animation is an object with `forwards` and `backwards`, each containing `old` and `new` descriptors with `name` (a `@keyframes` name defined in a global style), `duration`, `delay`, `easing`, `fillMode` and `direction`. The object must be defined in the frontmatter of every component using it, so factor it into a module:

```ts
// src/lib/transitions.ts
const anim = {
  old: { name: 'bump', duration: '0.5s', easing: 'ease-in', direction: 'reverse' },
  new: { name: 'bump', duration: '0.5s', easing: 'ease-in-out' },
};
export const bump = { forwards: anim, backwards: anim };
```

```html
---
import { bump } from '../lib/transitions';
---
<header transition:animate={bump}>...</header>
```

The `@keyframes bump` itself must be in a `<style is:global>` (scoped styles would rename it, and the browser looks up keyframes by name from the document, not from your component).

### `transition:persist`

By default every navigation replaces the body. `transition:persist` tells the router to move the matching element from the old DOM into the new one instead of recreating it. Matching is by the persist key: the value of the directive if given (`transition:persist="player"`), else the `transition:name`, else an automatically assigned identity from position and type. In my build:

```html
<Counter client:load transition:persist transition:name="ctr" label="A" />
<Counter client:load transition:persist="other" transition:persist-props label="B" />
```

rendered the islands with these attributes:

```html
<astro-island ... data-astro-transition-scope="astro-2iri6xem-1" data-astro-transition-persist="ctr" ...>
<astro-island ... data-astro-transition-persist="other" data-astro-transition-persist-props ...>
```

The first island’s persist key is its `transition:name` (`ctr`); the second uses the explicit value `other`. For the router to carry the island across, the *new page must contain an element with the same key*. If the new page lacks it, the persisted element is dropped.

Persisting works for native elements too. A `<video>` keeps playing, an `<input>` keeps its value and focus, an `<audio>` keeps its position. Documented limitations: CSS animations restart and `<iframe>`s reload even when persisted, because moving them in the DOM resets those.

### `transition:persist-props`

For an island with `transition:persist`, the *state* is retained, but the component is told about the new page’s props (it re-renders with them). `transition:persist-props` additionally keeps the *old* props. Use the default when the island displays page-specific data (a title, a current locale), and `persist-props` when props are configuration that should not change.

### What “state is retained” means for a Svelte 5 island

An island is a custom element, `<astro-island>`, wrapping the Svelte component’s DOM. Persistence moves that element, which has already been hydrated, to the new document; Svelte’s reactive state (the `$state` in the component instance) lives in the JavaScript heap, not in the DOM, and the instance keeps running. This is why a counter’s `n` survives. Some concrete rules:

- The Svelte component instance is *not* remounted, so `onMount` and `$effect` setup does not run again. Code that must react to navigation should listen to the router events (below) or derive from `$props()`. With default `transition:persist`, the new page’s props are delivered to the existing instance, so `let { label } = $props()` updates reactively: no remount, but your derived values and effects re-run on prop change, as they always do.
- Module-level rune state (`.svelte.ts` stores, Chapter 4) survives every navigation regardless of persistence, because the JavaScript realm survives. This is a feature (a cart store shared by islands on every page) and a hazard (state leaking between logically separate pages).
- Persisted state that depends on the DOM position (focus, scroll in a container) is restored for the focused element via `saveFocus()`; other scroll positions are not.
- The integration changelog notes a fix for view-transition state persistence in 5.7.1; make sure you are not on an old integration version if persisted state seems to reset.
- `transition:persist` on an island requires the same *component* to be on the next page. If the two pages render different Svelte components under the same persist key, the old one is discarded.
- The directive attributes (`data-astro-transition-scope`, `data-astro-transition-persist`, `data-astro-transition-persist-props`) are also serialized into the island’s `props` JSON (visible in my output), as the scoped-style attribute is (Chapter 13). Svelte ignores unknown props unless you spread rest props onto a DOM element.

A design pattern follows. Put a persistent, stateful UI (the cart island, a music player) in the shared *layout*, mark it `transition:persist`, and keep page-specific data flowing in through props. That is the core of the capstone’s persisted cart (Chapter 20).

## Controlling the router

### Opting out

`data-astro-reload` on an `<a>` or `<form>` forces a full browser navigation. Use it for links to non-HTML resources, for pages that load third-party scripts that must run fresh, to bust persisted state deliberately, and for pages without the router.

### History

`data-astro-history="push" | "replace" | "auto"` on a link and the `history` option of `navigate()` select how the history entry is written: `push` always adds one, `replace` overwrites the current, `auto` pushes when the URL can be transitioned to and otherwise leaves history untouched. `replace` is the correct choice after a “confirmation” step so Back skips it.

### `navigate()`

```ts
import { navigate } from 'astro:transitions/client';

navigate('/cart', {
  history: 'push',
  info: { reason: 'checkout' },        // surfaced as event.info
  state: { scroll: 0 },                // associated with the history entry
  sourceElement: buttonEl,             // surfaced as event.sourceElement
  formData,                            // if given, the request is a POST
});
```

`navigate()` works from scripts and framework components. In a Svelte island:

```html
<!-- src/components/Search.svelte -->
<script lang="ts">
  import { navigate } from 'astro:transitions/client';
  let q = $state('');

  function submit(e: SubmitEvent) {
    e.preventDefault();
    navigate(`/search?q=${encodeURIComponent(q)}`);
  }
</script>

<form onsubmit={submit}>
  <input bind:value={q} type="search" aria-label="Search" />
</form>
```

Three cautions. `navigate()` called during the *server render* of a component does nothing useful: guard with event handlers or `$effect`, which only run in the browser. On a page that does *not* include `<ClientRouter />` it degrades to a normal navigation. And it performs no URL sanitization: never pass raw user input; the `javascript:` scheme and external hosts are the exploit routes (the docs recommend an allowlist, and a Content Security Policy as defense in depth, which, as noted, you cannot have together with the router). A safe redirect helper:

```ts
// src/lib/safe-redirect.ts
export function safeInternalPath(candidate: string | null, fallback = '/'): string {
  if (!candidate) return fallback;
  try {
    const url = new URL(candidate, location.origin);
    if (url.origin !== location.origin) return fallback;
    return url.pathname + url.search + url.hash;
  } catch {
    return fallback;
  }
}
```

For back and forward, combine `history.back()`, `history.forward()` and `history.go()`; the router listens for the traversal.

## Lifecycle events

The router dispatches five events on `document`, in this order: `astro:before-preparation`, `astro:after-preparation`, `astro:before-swap`, `astro:after-swap`, `astro:page-load`. Since 7.0 the old helper constants and type guards are gone, and you compare `event.type` strings directly (see “Removed APIs”).

| Event | When | What you can do |
|------------------------|------------------------|------------------------|
| `before-preparation` | Navigation started, nothing fetched | Show a spinner; replace `event.loader` to change *how* the page is loaded; set `event.direction`; modify `event.to`; read/set `event.formData` |
| `after-preparation` | New document parsed | Hide the spinner |
| `before-swap` | Inside the view transition, old page still visible | Mutate `event.newDocument`; replace `event.swap` with a custom implementation; read `viewTransition`, `direction` |
| `after-swap` | New body in place, before paint and before new scripts | Re-apply DOM state; override scroll restoration |
| `page-load` | Navigation complete, also fires on the first load | (Re)initialize behavior |

`before-preparation` and `before-swap` events share these attributes: `info`, `sourceElement`, `navigationType` (`push`, `replace`, `traverse`), `direction` (`forward`, `back`, or a custom string writable in `before-preparation`), `from` and `to` (`URL`; `to` is writable). `formData` and `loader()` are specific to `before-preparation`; `newDocument`, `viewTransition` and `swap()` to `before-swap`. `before-swap` cannot be canceled: `preventDefault()` is a no-op. To veto a navigation, intercept earlier: in `before-preparation` you can replace `loader` and trigger `location.href = ...` yourself, or put `data-astro-reload` on the link.

A typical global loading bar, with typing:

```ts
// src/scripts/progress.ts  (imported from the layout's <script>)
import type { TransitionBeforePreparationEvent } from 'astro:transitions/client';

// #progress lives in the body, which is replaced on every navigation: query it inside each handler
const bar = () => document.querySelector<HTMLElement>('#progress');

document.addEventListener('astro:before-preparation', (e) => {
  const event = e as TransitionBeforePreparationEvent;
  bar()?.classList.add('active');
  const originalLoader = event.loader;
  event.loader = async () => {
    const started = performance.now();
    await originalLoader();
    console.debug(`navigated ${event.from.pathname} -> ${event.to.pathname} in ${performance.now() - started}ms`);
  };
});

document.addEventListener('astro:after-preparation', () => bar()?.classList.remove('active'));
```

Because a bundled `<script>` runs once, a reference captured at the top of the script would keep pointing at the first page’s `#progress` element after the body is replaced; that is why the handlers above re-query it. Only an element marked `transition:persist` can safely be queried once.

### Theme and direction examples

The `before-swap` event is the correct place to carry DOM attributes the old page had onto the new document, because the old page remains visible until the swap completes, and setting attributes on `event.newDocument` avoids a flash:

```ts
document.addEventListener('astro:before-swap', (event) => {
  const e = event as import('astro:transitions/client').TransitionBeforeSwapEvent;
  e.newDocument.documentElement.dataset.theme = localStorage.getItem('theme') ?? 'light';
});
```

(This is the fix for the dark-mode script from Chapter 13, whose inline script only runs on a full load.) Custom direction lets you animate by *meaning* rather than by history: in `before-preparation`, set `event.direction = 'up'` when going to a parent route, then key your CSS on `[data-astro-transition='up']`.

### Custom swap functions

`swapFunctions` from `astro:transitions/client` exposes the five steps the default swap performs: `deselectScripts(doc)`, `swapRootAttributes(doc)`, `swapHeadElements(doc)`, `saveFocus()` (returns a restore function) and `swapBodyElement(newBody, oldBody)`. Replace `event.swap` to modify one step while keeping the others:

```ts
import { swapFunctions } from 'astro:transitions/client';

document.addEventListener('astro:before-swap', (event) => {
  const e = event as import('astro:transitions/client').TransitionBeforeSwapEvent;
  e.swap = () => {
    swapFunctions.deselectScripts(e.newDocument);
    swapFunctions.swapRootAttributes(e.newDocument);
    swapFunctions.swapHeadElements(e.newDocument);
    const restoreFocus = swapFunctions.saveFocus();
    swapFunctions.swapBodyElement(e.newDocument.body, document.body);
    restoreFocus();
  };
});
```

Always call `swapRootAttributes`: it also swaps Astro’s internal root attributes such as `data-astro-transition`, which the generated animation CSS depends on. A realistic custom swap preserves a specific container’s DOM (a map, a canvas) by moving it between bodies before `swapBodyElement`, without the persistence overhead; or integrates morphing libraries (`idiomorph`-style diffing of `document`) so that unchanged DOM, including form field state, is kept.

## Scripts across navigations

The most common migration bug. The rules from the guide, applied:

| Script kind | Runs on first load | Runs again after a client navigation |
|------------------------|------------------------|------------------------|
| Bundled `<script>` (default, module) | Yes | **No.** Executed once; later pages that include it are ignored |
| `<script is:inline>` | Yes | Can re-execute when present on a new page, but not reliably; use `data-astro-rerun` to force it and guard global setup |
| `<script is:inline data-astro-rerun>` | Yes | Yes, on every navigation (adding any attribute implies `is:inline`) |
| Island hydration | Yes | Yes for islands in the new body |

Do not rely on script re-execution; use events. The robust patterns:

**1. Initialize on `astro:page-load`.** It fires on the first load and after every navigation, so one handler covers both:

```html
<nav>
  <button class="hamburger" aria-expanded="false">Menu</button>
  <ul class="links"><slot /></ul>
</nav>
<script>
  document.addEventListener('astro:page-load', () => {
    const button = document.querySelector<HTMLButtonElement>('.hamburger');
    button?.addEventListener('click', () => {
      const open = button.getAttribute('aria-expanded') === 'true';
      button.setAttribute('aria-expanded', String(!open));
      document.querySelector('.links')?.classList.toggle('expanded', !open);
    });
  });
</script>
```

Binding inside `page-load` is safe here because the whole `<nav>` is replaced each navigation (the old listener goes with the old element). If the element is *persisted*, binding again each time would add duplicate listeners: use a guard flag on the element (`if (button.dataset.bound) return; button.dataset.bound = '1'`) or `{ once: true }`.

**2. Use a custom element.** A custom element’s `connectedCallback` runs whenever the element enters the DOM, including after a swap, and `disconnectedCallback` cleans up. This is the pattern the docs recommend for scripts that interact with framework-rendered DOM, and it is independent of router events:

```html
<theme-picker><button>Toggle</button></theme-picker>
<script>
  class ThemePicker extends HTMLElement {
    #onClick = () => {
      const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      localStorage.setItem('theme', next);
    };
    connectedCallback() { this.querySelector('button')?.addEventListener('click', this.#onClick); }
    disconnectedCallback() { this.querySelector('button')?.removeEventListener('click', this.#onClick); }
  }
  customElements.define('theme-picker', ThemePicker);
</script>
```

The bundled script executes once, defining the element; every later page that contains `<theme-picker>` upgrades it automatically. (A guard `if (!customElements.get('theme-picker'))` avoids redefinition errors in unusual reload scenarios.)

**3. Avoid re-running side effects in inline scripts.** An inline script that runs again must be idempotent: `window.SomeGlobal ??= {}` style guards for globals, and removal of listeners in `astro:before-swap` for anything registered on `window` or `document` that depends on the old page.

**4. Svelte islands.** For islands, none of this applies: hydration runs for every island in the new body, and `$effect` setup runs per instance. The hazards are *leaks*, not missed initialization: an `$effect` that adds a `window` listener must return a cleanup function (Svelte calls it when the component is destroyed, which happens when the old body is replaced). Persisted islands are never destroyed, so their effects continue across pages: if that effect references `location.pathname`, it must listen to navigation events itself:

```html
<script lang="ts">
  let path = $state(location.pathname);

  $effect(() => {
    const update = () => (path = location.pathname);
    document.addEventListener('astro:page-load', update);
    return () => document.removeEventListener('astro:page-load', update);
  });
</script>

<nav aria-label="Primary">
  <a href="/" aria-current={path === '/' ? 'page' : undefined}>Home</a>
  <a href="/blog" aria-current={path.startsWith('/blog') ? 'page' : undefined}>Blog</a>
</nav>
```

Note `location.pathname` in the `$state` initializer is a problem for SSR (`location` is undefined on the server). In real code initialize from a prop (`initialPath`) passed by the Astro parent from `Astro.url.pathname`, and update on the event. I wrote it the short way to show the event subscription; production code should not use `location` at component top level in an island that renders on the server.

## Forms

With `<ClientRouter />`, form submissions are intercepted: `GET` forms navigate with the query string, and `POST` forms send the form data to the target URL with `fetch` (as `multipart/form-data` by default; set `enctype="application/x-www-form-urlencoded"` to match the browser default) and swap the resulting page as for any other navigation. Opt out per form with `data-astro-reload`. In 6.0 the `handleForms` prop on the router was removed: form handling is always on, and `data-astro-reload` is the single opt-out.

This composes with Astro Actions in form mode (Chapter 11): a `<form method="POST" action={actions.subscribe}>` is submitted by the router, the page re-renders with the action result, and the DOM is swapped, with no page flash. To keep the user’s typed values after a validation error, add `transition:persist` to the inputs (as the actions guide notes): the old input elements, with their current values, are moved into the new DOM. That works only for elements the new page also renders with the same persist key. A caution: persisting an input also persists a *stale error state* if you derive attributes like `aria-invalid` from server-rendered state, because persisted elements keep their old attributes; render error state outside the persisted element.

Redirect responses (`303` after POST) are followed by `fetch`, and the router uses the final URL for the history entry, so the post/redirect/get pattern of Chapter 11 works naturally.

## Accessibility

Astro handles two things for you: a route announcer (an element with `aria-live="assertive"` added to the new page that reads the new `<title>`, or else the first `<h1>`, or else the pathname), and a media query that disables all view transition animations, including the fallback, when `prefers-reduced-motion: reduce` is set. Therefore *always give each page a `<title>`*. Things that remain yours: moving focus (after a swap focus stays where `saveFocus()` put it, typically `body`, so consider focusing the `<main>` or the `<h1>` in `astro:after-swap` for long pages), restoring scroll for in-page containers, and not hiding information in animations. If you add your own animations, respect the same media query.

## Prefetching

Prefetch fetches a page in the background before the user clicks, so the navigation has little or nothing left to download. It is independent of the router and works for plain multi-page navigation, but it is enabled by default with the router.

### Enabling and configuring

```js
// astro.config.mjs
export default defineConfig({
  prefetch: true,   // or an options object
});
```

`prefetch: true` adds a prefetch script to every page and activates the `data-astro-prefetch` attribute. Options:

```js
prefetch: {
  defaultStrategy: 'viewport',  // 'hover' (default) | 'tap' | 'viewport' | 'load'
  prefetchAll: true,            // prefetch every internal link without the attribute
}
```

- `hover` (default): on hover or keyboard focus. Quickly hovering over a link without lingering does not prefetch.
- `tap`: on `pointerdown`/touch start, just before the click completes. Cheapest; wins only the click latency.
- `viewport`: when the link enters the viewport.
- `load`: all links, after page load. Use only for tiny sites or a handful of links.

Per link, `data-astro-prefetch="tap"` selects a strategy and `data-astro-prefetch="false"` opts out when `prefetchAll` is on. With `<ClientRouter />` present, `prefetchAll` defaults to `true` (an explicit config overrides: `prefetch: false` disables prefetch completely; `{ prefetchAll: false }` restricts it to annotated links).

Both the attribute and the programmatic API respect the data-saver mode and slow connections (`navigator.connection.saveData`, `effectiveType`): on such connections every strategy falls back to `tap`.

### Programmatic prefetching

```html
<!-- src/components/ProductRow.svelte -->
<script lang="ts">
  import { prefetch } from 'astro:prefetch';

  let { href, name }: { href: string; name: string } = $props();
</script>

<a {href} onpointerenter={() => prefetch(href)} onfocus={() => prefetch(href)}>{name}</a>
```

`prefetch(url, { ignoreSlowConnection?, eagerness? })` is for navigation that is not an `<a>` (buttons, `navigate()` calls) or for logic such as “prefetch the next page of results when the user is at 80% scroll”. Import it only in client code; it uses browser APIs. The 6.0 release removed the `prefetch({ with })` option.

### Prefetch and caching: the part that surprises people

Astro prefetches with `<link rel="prefetch">` when the browser supports it, and falls back to `fetch()` otherwise. The prefetched response is only *useful* if the browser’s HTTP cache will reuse it, which depends on cache headers:

- **Chrome**: `<link rel="prefetch">` works as intended.
- **Firefox**: supports the link, but without explicit `Cache-Control`/`Expires` the prefetch errors (`NS_BINDING_ABORTED`); an `ETag` still lets the response be reused.
- **Safari**: no `<link rel="prefetch">`, so the `fetch()` fallback requires cache headers; ETags do not work in private windows.

For prerendered pages the host usually sets `ETag`. For on-demand pages *you* must send sensible headers, or prefetching wastes bandwidth with no benefit. A short browser-cache lifetime is enough: `Cache-Control: public, max-age=30` on public HTML covers the hover-to-click window. Remember the route cache of Chapter 12 does not emit `Cache-Control` for browsers; set it yourself in the page (`Astro.response.headers.set('Cache-Control', 'public, max-age=30')`), or via your CDN. And never prefetch personalized pages with side effects: a `GET` that mutates state (a logout link, “mark as read”) will be triggered by hover prefetching. Mutations belong in `POST` actions (Chapter 11); mark any unavoidable such link with `data-astro-prefetch="false"`.

With the router, a navigation to a prefetched page reuses the same response through the HTTP cache. With on-demand pages that are expensive to render, remember prefetch multiplies load: every hover can cost a render. Pair it with caching and with the `tap` strategy for expensive routes.

### Experimental: `clientPrerender`

```js
export default defineConfig({
  prefetch: { prefetchAll: true, defaultStrategy: 'viewport' },
  experimental: { clientPrerender: true },
});
```

With `experimental.clientPrerender: true` (still experimental in 7.4), Astro stops appending `<link>` tags or calling `fetch()` and instead appends a `<script type="speculationrules">` with matching rules (the Speculation Rules API). In supporting browsers (Chromium), the target page is not just downloaded but *prerendered*: fully rendered in a hidden context, including running its JavaScript, so activation is near instant. In other browsers it falls back to the normal prefetch strategy. The programmatic `prefetch()` then accepts `eagerness: 'immediate' | 'eager' | 'moderate' | 'conservative'` (default `'immediate'`), mapped to speculation rule eagerness; use `moderate` for lists of many links to let browser heuristics (and its FIFO limits) decide. Prerendering executes the target page, so analytics, side-effecting inline scripts and personalized renders run before the user actually visits; review MDN’s “unsafe prefetching” notes and gate analytics on `document.prerendering` / the `prerenderingchange` event. It also stacks with the router: the router fetches again on click (a cache hit), while a prerendered page does not give the router’s swap anything to use unless navigation is a native one, so test the combination on your site before relying on it.

## Removed and changed APIs (6.0 and 7.0)

When you meet older code or tutorials, these no longer exist:

| Removed | In | Replacement |
|------------------------|------------------------|------------------------|
| `<ViewTransitions />` component | 6.0 | `<ClientRouter />` (since 5.0) |
| `handleForms` prop of `ClientRouter` | 6.0 | Always on; opt out with `data-astro-reload` |
| `prefetch({ with: ... })` | 6.0 | Choose strategy via config or attribute |
| `TRANSITION_BEFORE_PREPARATION`, `TRANSITION_AFTER_PREPARATION`, `TRANSITION_BEFORE_SWAP`, `TRANSITION_AFTER_SWAP`, `TRANSITION_PAGE_LOAD` | 7.0 | The event name strings (`'astro:before-swap'`, etc.) |
| `isTransitionBeforePreparationEvent()`, `isTransitionBeforeSwapEvent()` | 7.0 | `event.type === 'astro:before-preparation'` / `'astro:before-swap'` |
| `createAnimationScope()` | 7.0 | Remove; no replacement needed |

The 7.0 migration is mechanical: search the codebase for these identifiers. Libraries that wrapped them need updated versions. `TransitionBeforePreparationEvent` and `TransitionBeforeSwapEvent` types remain for typing listeners.

## Troubleshooting guide

1.  **A script stopped working after enabling the router.** It was a bundled script that ran once. Move initialization into an `astro:page-load` handler or into a custom element.
2.  **Handlers fire twice, three times…** Listeners on persisted elements or on `window`/`document` added in `page-load` accumulate. Guard, use `{ once: true }`, or clean up in `astro:before-swap`.
3.  **Island state resets on navigation.** Missing `transition:persist`, or the next page does not render the same component with the same persist key, or the router is not on both pages, or the link has `data-astro-reload`.
4.  **Persisted island shows stale props.** You used `transition:persist-props`; remove it if the island should see the new page’s props.
5.  **Flash of unstyled or wrongly themed content.** Apply theme attributes to `event.newDocument` in `before-swap`.
6.  **Third-party widget does not initialize.** Its script is in a page that was already visited; mark the script with `data-astro-rerun` or load it in `page-load`.
7.  **Full page reloads on some links.** The destination page lacks `<ClientRouter />`, the response was not HTML, the link has `data-astro-reload`, `target` or `download`, or it is cross-origin.
8.  **Back button shows a stale page.** The router uses the browser’s cache and the stored scroll state; set proper cache headers on on-demand pages.
9.  **Animation jank on large pages.** View transition snapshots are bitmaps of named elements; reduce the number of `transition:name` elements, avoid animating the full-viewport `root`, and respect `prefers-reduced-motion`.

## Key takeaways

- `<ClientRouter />` keeps server-rendered HTML but intercepts navigation, fetches the next page and swaps the DOM; it must be on both pages, it survives only as `window`-level JavaScript state, and it is incompatible with CSP.
- The sequence is before-preparation, load, after-preparation, `startViewTransition`, before-swap, swap, after-swap, stylesheets, new scripts, page-load. Use `astro:page-load` for initialization, `before-swap` to alter the incoming document, and `after-swap` for post-swap DOM state or scroll.
- Bundled scripts execute once; use `astro:page-load`, custom elements, or `data-astro-rerun` for inline scripts. Islands are re-hydrated automatically in the new body.
- `transition:persist` moves the existing DOM node, and for islands keeps the component instance and state alive; matching uses the persist value, else `transition:name`, else position; `persist-props` keeps old props; iframes reload and CSS animations restart regardless.
- Module-level rune state survives every navigation because the JavaScript realm does; persisted instances do not re-run `onMount`/setup, so subscribe to router events for navigation-dependent logic.
- `data-astro-reload` and `data-astro-history` control per-link behavior; `navigate()` does no sanitization, so validate its input.
- Form submissions are routed automatically (`handleForms` was removed in 6.0); combine with form-mode actions and `transition:persist` on inputs.
- Accessibility: Astro adds a route announcer and disables animations under `prefers-reduced-motion`; always provide a `<title>` and manage focus yourself.
- Prefetch strategies are `hover`, `tap`, `viewport`, `load`; the router turns on `prefetchAll`; reuse depends on HTTP cache headers, and `GET` links with side effects must never be prefetched.
- `experimental.clientPrerender` swaps link prefetching for Speculation Rules prerendering in Chromium and adds `eagerness` to `prefetch()`.
- 6.0 removed `<ViewTransitions />`, `handleForms`, `prefetch({ with })`; 7.0 removed the `TRANSITION_*` constants, the `isTransition*Event()` guards and `createAnimationScope()`.

## Review Questions

1.  Name two reasons to prefer plain navigation plus prefetch over `<ClientRouter />`, and two reasons to choose the router.
2.  A link goes from a page with `<ClientRouter />` to a page without it. What happens and why?
3.  List, in order, the five lifecycle events and one thing each is typically used for.
4.  In which event is the old page still visible while you can mutate the incoming document? Why does that matter for a theme attribute?
5.  Multiple choice. Which is true of `astro:before-swap`?

    a.  It can be canceled with `preventDefault()`.
    b.  It fires before any network request.
    c.  It exposes `newDocument` and a replaceable `swap()`.
    d.  It only fires on back navigation.
6.  Why does a bundled `<script>` containing `document.querySelector('.menu').addEventListener(...)` stop working after the second navigation, and what are three fixes?
7.  When does `astro:page-load` fire, and why is it preferable to `DOMContentLoaded` under the router?
8.  A persisted Svelte island has `let { label } = $props()`. The next page passes a different `label`. What does the island show with plain `transition:persist`? With `transition:persist-props`? Does `onMount` run again?
9.  How does the router match a persisted element on the old page to one on the new page? Give the precedence.
10. What happens if the new page does not contain an element with the persist key of a persisted island?
11. Name two things that cannot be preserved by `transition:persist`.
12. Module-level `$state` in a `.svelte.ts` file: does it survive client-side navigations? Does `transition:persist` matter for it?
13. Find the bug: a Svelte island’s `$effect` does `window.addEventListener('resize', onResize)` and returns nothing. What goes wrong without the router, and what changes with it for persisted versus non-persisted islands?
14. How do you opt a single link out of client-side routing? A single form?
15. Why is `navigate(new URLSearchParams(location.search).get('next')!)` dangerous? Show a safer approach.
16. What are the three `fallback` values of `<ClientRouter />` and what does each do in a browser without view transition support?
17. Given `<html transition:name="root" transition:animate="none">` and `<main transition:animate="slide">`, what animates and what does not?
18. Why must `@keyframes` for a custom `transition:animate` live in a `<style is:global>`?
19. What does the default swap consist of? Which `swapFunctions` entry must a custom swap always call, and why?
20. How do forms behave under the router by default, and what is the default encoding of a `POST` form?
21. A form-mode action fails validation and the page re-renders with errors, but the user’s typed values are gone. How do you keep them under the router, and what pitfall comes with persisted inputs?
22. What does the router do for accessibility without configuration, and what must you provide on every page?
23. What triggers each prefetch strategy, and what happens to all strategies on a data-saver connection?
24. Under what conditions is `prefetchAll` true by default? How do you turn prefetching off entirely?
25. A page served on demand has no cache headers. In which browsers does prefetching not help and why?
26. Why must you never expose a state-changing `GET` link when prefetching is on? What do you use instead?
27. How does `experimental.clientPrerender` change what the prefetch script appends, and what is `eagerness`?
28. What does prerendering imply for analytics and side-effecting scripts on the target page?
29. Which of these were removed in 7.0 and what replaces them: `TRANSITION_AFTER_SWAP`, `isTransitionBeforeSwapEvent`, `createAnimationScope`, `<ViewTransitions />`, `handleForms`?
30. Design: a layout with a persistent audio player (Svelte island) and a cart badge, on a site with CSP-free pages. Describe which directives, events and stores you would use, and what you would do about the active-link state in a persisted nav island.
