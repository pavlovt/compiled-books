# Chapter 4: State, Events and Scripts Across Islands

Islands are isolated by design: each is mounted by its own call to the framework, with no shared component tree, no context, and no parent to hold state. The moment a cart badge in the header has to reflect what an “add to cart” button in the page body does, you must build the communication channel yourself. This chapter covers the options in order of how much they cost and how much they can go wrong: Nano Stores (the officially documented recipe), Svelte 5 rune modules in `.svelte.ts` files, DOM events and `BroadcastChannel`, and plain scripts and custom elements for non-framework behaviour. It then covers the hazard that catches most teams, module state on the server, how `transition:persist` interacts with island state, and how to test it all.

Everything marked “verified” was built and run against Astro 7.4.1, `@astrojs/svelte` 9.1.0 and Svelte 5.57.2 (with `@astrojs/node` for the server test). Examples use runes.

## The problem, precisely

Two islands on one page:

```html
---
import CartBadge from '../components/CartBadge.svelte';
import AddToCart from '../components/AddToCart.svelte';
---
<header><CartBadge client:load /></header>
<main><AddToCart client:visible sku="a1" /></main>
```

There is no common ancestor in the browser: Astro called `hydrate()` separately for each, at different times (the second may hydrate minutes later when scrolled to). Any mechanism must therefore satisfy three requirements:

1.  **Shared module instance in the browser.** Both islands must reference the same state object, or exchange messages through something global (the DOM, `window`, a `BroadcastChannel`).
2.  **Late subscribers.** The badge hydrates first; the button later. But if the button hydrates first and acts, the badge must still get the right *current* state when it hydrates. Messages that are only events fail this; state that is read on subscription does not.
3.  **Server-render consistency.** The server renders the badge with *some* value. On hydration, Svelte expects the client’s first render to match.

State containers satisfy (2) naturally; events do not. Keep that in mind throughout.

## Nano Stores

Astro’s documented recipe uses [Nano Stores](https://github.com/nanostores/nanostores): tiny, framework-agnostic observable stores (`atom`, `map`, `computed`). They are the right choice when islands from *different frameworks* must share state, or when `.astro` `<script>` tags must participate.

```ts
// src/lib/ui.ts
import { atom, map } from 'nanostores';

export const isCartOpen = atom(false);
export const cartItems = map<Record<string, number>>({});

export function addItem(sku: string) {
  const current = cartItems.get()[sku] ?? 0;
  cartItems.setKey(sku, current + 1);
}
```

The official Svelte examples use the legacy `$store` auto-subscription. In Svelte 5 with runes, the `$` prefix still works for stores in `.svelte` files, but mixing a `$store` shorthand into a runes component is something this book avoids; use `fromStore` from `svelte/store`, which wraps any store contract (including Nano Stores, whose atoms implement `subscribe`) in a reactive `.current` object. I built and rendered this:

```html
<!-- src/components/CartToggle.svelte -->
<script lang="ts">
  import { fromStore } from 'svelte/store';
  import { isCartOpen, cartItems } from '../lib/ui';

  const open = fromStore(isCartOpen);
  const items = fromStore(cartItems);
  const count = $derived(Object.values(items.current).reduce((a, b) => a + b, 0));
</script>

<button onclick={() => isCartOpen.set(!open.current)} aria-expanded={open.current}>
  Cart ({count})
</button>
```

It server-rendered `open 0` for the initial state and hydrated against the same store module used by other islands. From an `.astro` `<script>` you can use the store directly:

```html
<button id="open-cart">Open</button>
<script>
  import { isCartOpen } from '../lib/ui';
  document.getElementById('open-cart')?.addEventListener('click', () => isCartOpen.set(true));
</script>
```

Because Vite bundles the `<script>` and the island chunks with a shared dependency, `ui.ts` ends up in a single shared chunk and the instance is shared. (I confirmed the analogous behaviour for a rune module: two islands’ chunks imported the same `cart.svelte.*.js` chunk.)

### Nano Stores caveats

The docs list restrictions that are really consequences of the architecture:

- **Writes on the server do not reach the client.** Setting a store in frontmatter, or in a non-hydrated component, changes the *server’s* module instance. The browser has its own, initialized from scratch. A store is not a transport for server data; use props.
- **A store cannot be a prop.** Stores are not serializable.
- **`.astro` frontmatter cannot subscribe**; Astro components never re-render. Only `<script>` tags can.
- **The server instance is shared across requests** (next sections). A store that is only mutated in the browser is safe; one mutated in render code leaks between users.

### Persisting store state

Stores start from their initial value on every full page load. For cart-like state, persist explicitly: `@nanostores/persistent` provides `persistentAtom`, or hand-roll `localStorage` in a client-only initialization. Remember the server-render consistency rule: the server renders the initial value, the first client render must match, and you then update after mount.

```ts
// src/lib/cart-store.ts
import { atom } from 'nanostores';

export const cart = atom<Record<string, number>>({});

if (typeof window !== 'undefined') {
  try {
    cart.set(JSON.parse(localStorage.getItem('cart') ?? '{}'));
  } catch {
    /* corrupted storage: start empty */
  }
  cart.listen((value) => localStorage.setItem('cart', JSON.stringify(value)));
}
```

Reading storage at module load on the client means the first render of an island that imports it *already* differs from the server’s HTML (empty cart on the server, filled on the client), which causes a hydration mismatch. Svelte warns about mismatches in development and the result may be inconsistent; prefer to apply stored state in `onMount`, or accept a brief flash with a skeleton. The cleanest solution to hydration mismatches with persisted state is to render the persisted-dependent part client-only (`client:only`) or to start `hydrated = false` and flip it in `onMount`.

## Rune modules (`.svelte.ts`)

Svelte 5 lets reactive state live in plain modules whose filename ends in `.svelte.js` or `.svelte.ts`. Because Vite compiles them with Svelte’s rune transform, `$state` and `$derived` work at module level. For an all-Svelte site, this is simpler and lighter than Nano Stores: no library, no subscription glue, fine-grained reactivity.

```ts
// src/lib/cart.svelte.ts
export const cart = $state<{ items: Record<string, number>; open: boolean }>({
  items: {},
  open: false,
});

export const count = () => Object.values(cart.items).reduce((a, b) => a + b, 0);

export function add(sku: string) {
  cart.items[sku] = (cart.items[sku] ?? 0) + 1;
}
```

```html
<!-- AddToCart.svelte -->
<script lang="ts">
  import { add } from '../lib/cart.svelte';
  let { sku }: { sku: string } = $props();
</script>
<button onclick={() => add(sku)}>Add {sku}</button>
```

```html
<!-- CartBadge.svelte -->
<script lang="ts">
  import { count } from '../lib/cart.svelte';
</script>
<span>Cart: {count()}</span>
```

Both islands, hydrated separately, import one module. In a verified build the output contained `Add.*.js` and `Badge.*.js` each importing the same `cart.svelte.*.js` chunk, so they share a single instance in the browser, and a click in one updates the other.

Rules for rune modules:

- **Export an object, not a reassigned primitive.** `export let count = $state(0)` cannot be reassigned from other modules (Svelte forbids exporting reassigned state). Export a `$state` object and mutate its properties, or export getter/setter functions, or a class with `$state` fields.
- **Derived values across modules** must be wrapped: `export const total = $derived(...)` is not allowed at module level for export of a reassignable binding. Export a function (`count()` above) or use a class with `get total()`.
- **Class-based stores** read well and avoid the primitive limitation:

```ts
// src/lib/cart.svelte.ts
class Cart {
  items = $state<Record<string, number>>({});
  open = $state(false);
  count = $derived(Object.values(this.items).reduce((a, b) => a + b, 0));

  add(sku: string) {
    this.items[sku] = (this.items[sku] ?? 0) + 1;
  }
  clear() {
    this.items = {};
  }
}

export const cart = new Cart();
```

- **Effects at module level** require a root: use `$effect.root()` if you need to persist state to storage from a module, and only in the browser:

```ts
if (typeof window !== 'undefined') {
  $effect.root(() => {
    $effect(() => {
      localStorage.setItem('cart', JSON.stringify($state.snapshot(cart.items)));
    });
  });
}
```

- **Not usable from `.astro` or non-Svelte islands.** A rune module is reactive only inside Svelte components or effects. A `<script>` in an `.astro` file can read and write properties, but nothing re-renders on its own, and it cannot subscribe without an `$effect.root`. If you need Astro scripts and React/Vue islands to participate, Nano Stores is the better fit.

### Hydration timing

An island’s state is defined by its hydration time. Consider `CartBadge client:load` and `AddToCart client:visible`:

1.  Page loads. The server HTML contains the badge showing the server’s value (`Cart: 0`) and the button, inert.
2.  `client:load` hydrates the badge. It imports `cart.svelte.js`, creating the module state; the badge shows the module’s current value.
3.  The user scrolls; the button hydrates, imports the same module (already loaded), and handlers attach.
4.  Click: state changes, the badge updates.

The important consequences. State is created when the *first importer* hydrates, not at page load. State changes before a subscriber hydrates are simply visible when it does: the module is the source of truth, which satisfies the “late subscriber” requirement. Server HTML always reflects the *initial* value, so initial module state must equal what the server rendered. If you restore from `localStorage` at import time, islands rendered with the empty-state HTML will mismatch.

A robust pattern separates “hydrated from storage” from “initial”:

```ts
// src/lib/cart.svelte.ts
class Cart {
  items = $state<Record<string, number>>({});
  ready = $state(false);

  init() {
    if (this.ready) return;
    try {
      this.items = JSON.parse(localStorage.getItem('cart') ?? '{}');
    } catch {}
    this.ready = true;
  }
}
export const cart = new Cart();
```

```html
<script lang="ts">
  import { onMount } from 'svelte';
  import { cart } from '../lib/cart.svelte';
  onMount(() => cart.init());
  const count = $derived(Object.values(cart.items).reduce((a, b) => a + b, 0));
</script>
<span aria-live="polite">Cart: {cart.ready ? count : '…'}</span>
```

`onMount` never runs on the server, so server HTML and the first client render agree (`…`), and the real count appears after mount.

## The SSR cross-request module-state hazard

This is the most serious pitfall in the chapter. In the server environment, ES modules are evaluated once per process and cached. A module-level `$state` object (or a Nano Store, or any `let`) is therefore **shared by every request handled by that process**. Rendering a component that *writes* to it during SSR leaks state between visitors.

I built exactly this with `@astrojs/node` in standalone mode:

```html
<script lang="ts">
  import { cart } from '../lib/cart.svelte';   // export const cart = $state({ n: 0 });
  cart.n++;                                    // runs during SSR
</script>
<p>n={cart.n}</p>
```

and requested the page three times with `curl`. The responses were `n=1`, `n=2`, `n=3`. Each request saw the accumulated effects of earlier ones. For a counter that is a curiosity; for `cart.items`, `user`, or a “current locale” it is a data leak (one customer sees another’s cart) or a correctness bug. Prerendered pages hide the problem at build time and show it only after you move a route on demand.

The same applies to any server-side module: a database client is fine (intentionally shared); a per-user cache keyed by nothing is not.

How to avoid it:

1.  **Never write module-level state during render.** Writes belong in event handlers, `onMount`, and `$effect`, none of which run on the server. A top-level statement in `<script>` (`cart.n++`) and a `$derived` that mutates are the culprits.
2.  **Treat module state as client-only.** Reading the initial value on the server is harmless if nothing mutates it there. Ensure the initial value is constant.
3.  **Pass per-request data as props** (or via a context set in a parent *within* an island), never through a module singleton. Per-request server data lives in `Astro.locals`, `Astro.session` or `Astro.props` (Chapters 10 and 12), not in modules.
4.  **If a store must exist on the server**, create it per render: a factory (`createCart()`) called in the component or placed in Svelte context (`setContext`/`getContext`, which works *within* one island). Context cannot span islands, so cross-island sharing remains client-only.
5.  **Lint for it.** A rule of thumb for code review: any `export const x = $state(...)`/`atom(...)` in a file imported by a hydrated component is acceptable only if nothing writes to it outside handlers.

> **Warning:** Rune modules and Nano Stores look identical on both sides of the boundary, which is exactly why the bug is easy to introduce. When you convert a route from `prerender = true` to on-demand, grep your islands for top-level writes to shared modules.

## Events and messaging

State containers are for state. For *notifications* (something happened, whoever cares may react), the browser’s native event system needs no library, works across frameworks and across non-framework scripts, and avoids the server-state hazard because events only exist in the browser.

### `CustomEvent` on `window` (or `document`)

```html
<!-- AddToCart.svelte -->
<script lang="ts">
  let { sku }: { sku: string } = $props();

  function add() {
    window.dispatchEvent(new CustomEvent('cart:add', { detail: { sku } }));
  }
</script>
<button onclick={add}>Add</button>
```

```html
<!-- CartBadge.svelte -->
<script lang="ts">
  import { onMount } from 'svelte';

  let count = $state(0);

  onMount(() => {
    const onAdd = (e: Event) => {
      count += 1;
      console.log('added', (e as CustomEvent<{ sku: string }>).detail.sku);
    };
    window.addEventListener('cart:add', onAdd);
    return () => window.removeEventListener('cart:add', onAdd);
  });
</script>
<span>Cart: {count}</span>
```

Points to get right:

- **Register in `onMount`** (browser only) and **return the cleanup**; with the client router or conditional rendering, islands are created and destroyed repeatedly.
- **Namespace event names** (`cart:add`). Use `bubbles` and `composed` only when needed.
- **Typed events.** Augment `WindowEventMap` in `src/env.d.ts` so `addEventListener('cart:add', e => e.detail.sku)` is typed without casts:

```ts
// src/env.d.ts
interface WindowEventMap {
  'cart:add': CustomEvent<{ sku: string }>;
}
```

- **Events are lossy for late subscribers.** If `AddToCart` fires before the badge has hydrated (`client:idle` badge, `client:load` button), the event is gone. Either hydrate the listener island earlier than any emitter, or pair events with a state container as the source of truth: emit events for *reactions* (toast, analytics) and keep state in a module.
- **Don’t pass functions through events across origins of trust**; treat `detail` as untrusted input in listeners, since any script can dispatch your event names.

### Targeted events and `astro-island` hooks

Astro itself dispatches events you may use: `astro:hydrate` (on an island when hydration completes), `astro:hydration-error`, `astro:unmount`, and the client router’s `astro:page-load`, `astro:before-swap` and friends (Chapter 14). A non-framework script can wait for a particular island to hydrate:

```ts
// in an .astro <script>
const island = document.querySelector('astro-island[component-url*="CartBadge"]');
island?.addEventListener('astro:hydrate', () => console.log('badge ready'), { once: true });
```

Matching on the generated `component-url` is brittle (it includes a content hash but also the component name, so `*=` on the name works until you rename the file). Prefer a stable `data-*` attribute you put on a wrapper.

### `BroadcastChannel`

`BroadcastChannel` sends messages between same-origin browsing contexts: other tabs, windows, iframes and workers, but **not** within the same context (a channel object does not receive its own messages, but a *second* channel object with the same name in the same page does). It is the right tool for “cart changed in another tab”, logout propagation and sign-in state:

```ts
// src/lib/sync.ts
export function createSync<T>(name: string, onMessage: (data: T) => void) {
  if (typeof BroadcastChannel === 'undefined') {
    return { post() {}, close() {} };
  }
  const channel = new BroadcastChannel(name);
  channel.onmessage = (e: MessageEvent<T>) => onMessage(e.data);
  return {
    post: (data: T) => channel.postMessage(data),
    close: () => channel.close(),
  };
}
```

```html
<script lang="ts">
  import { onMount } from 'svelte';
  import { cart } from '../lib/cart.svelte';
  import { createSync } from '../lib/sync';

  onMount(() => {
    const sync = createSync<Record<string, number>>('cart', (items) => {
      cart.items = items;               // received from another tab
    });
    const stop = $effect.root(() => {
      $effect(() => sync.post($state.snapshot(cart.items)));
    });
    return () => {
      stop();
      sync.close();
    };
  });
</script>
```

The sketch has an echo hazard: assigning received items triggers the effect, which posts them back and may ping-pong between tabs. Guard with a version counter or compare serialized values before posting. In practice `storage` events (fired in *other* tabs when `localStorage` changes) are the simplest cross-tab sync for state that is already persisted, and need no channel. Use `BroadcastChannel` when the data is not stored or when you need request/response between tabs.

### `window` messaging and iframes

`window.postMessage` is the cross-origin primitive; use it for embedded third-party widgets and **always verify `event.origin`** and the message shape. For islands on the same page it is unnecessary.

### Choosing

| Need | Use |
|------------------------------------|------------------------------------|
| Shared reactive state, Svelte only | Rune module (`.svelte.ts`) |
| Shared state across frameworks, or with `.astro` scripts | Nano Stores |
| One-off notification, fire and forget | `CustomEvent` on `window` |
| Sync between tabs | `storage` event or `BroadcastChannel` |
| Per-request server data | Props, `Astro.locals`, sessions: never modules |
| Data that must survive reloads | Server session/database, or `localStorage` with an explicit ready flag |

## Scripts and custom elements

Not every interaction deserves an island. A `<script>` in an `.astro` file gives you event wiring, observers and analytics without a framework.

### How Astro processes scripts

From the Chapter 2 rules, restated for this chapter: a `<script>` with no attributes (besides `src`) is bundled by Vite: TypeScript works, imports resolve (including your rune modules or stores), it becomes `type="module"`, it is deduplicated across component instances, and tiny scripts may be inlined. `is:inline` or any other attribute leaves it untouched; `define:vars` implies `is:inline`. Module scripts are deferred, so they run after the document is parsed, and in 6.0+ keep their source order (`preserveScriptOrder`).

Because the processed script runs once per *page*, even if its component appears 40 times, bind to all instances:

```html
<button class="copy" data-text="npm i astro">Copy</button>
<button class="copy" data-text="npm i svelte">Copy</button>

<script>
  document.querySelectorAll<HTMLButtonElement>('button.copy').forEach((btn) => {
    btn.addEventListener('click', () => navigator.clipboard.writeText(btn.dataset.text ?? ''));
  });
</script>
```

### Custom elements as the robust unit

Querying the whole document is fragile: elements may not exist yet (framework-rendered DOM), or may be inserted later (client-router navigation, a Svelte `{#if}`). A custom element solves both, because the browser calls `connectedCallback` for every instance whenever it is connected, in any context. The official docs recommend it, notably for scripts that touch framework-rendered DOM.

```html
---
// src/components/QuantityStepper.astro
interface Props { sku: string; min?: number }
const { sku, min = 1 } = Astro.props;
---
<quantity-stepper data-sku={sku} data-min={min}>
  <button type="button" data-dec aria-label="Decrease">−</button>
  <output>{min}</output>
  <button type="button" data-inc aria-label="Increase">+</button>
</quantity-stepper>

<script>
  class QuantityStepper extends HTMLElement {
    #abort?: AbortController;

    connectedCallback() {
      this.#abort = new AbortController();
      const { signal } = this.#abort;
      const out = this.querySelector('output')!;
      const min = Number(this.dataset.min ?? 1);
      let value = min;

      const set = (next: number) => {
        value = Math.max(min, next);
        out.textContent = String(value);
        this.dispatchEvent(
          new CustomEvent('quantity-change', {
            bubbles: true,
            detail: { sku: this.dataset.sku, value },
          }),
        );
      };

      this.querySelector('[data-dec]')?.addEventListener('click', () => set(value - 1), { signal });
      this.querySelector('[data-inc]')?.addEventListener('click', () => set(value + 1), { signal });
    }

    disconnectedCallback() {
      this.#abort?.abort();
    }
  }

  if (!customElements.get('quantity-stepper')) {
    customElements.define('quantity-stepper', QuantityStepper);
  }
</script>
```

Details that matter: `customElements.define` throws if the name is already registered (a re-executed script under certain navigation modes, or two bundles), so guard it. `disconnectedCallback` plus `AbortController` prevents listener leaks when elements are removed. The `quantity-change` event bubbles, so a Svelte island that *contains or sits beside* the element can listen on `window` or on a shared ancestor. Pass server data via `data-*` attributes (the docs’ own pattern, and what Astro does for islands with the `props` attribute).

A custom element and a Svelte island can interoperate in either direction: the island listens for `quantity-change` in `onMount`; or an island dispatches an event that a custom element handles. When the island needs to *render* the stepper, import a Svelte version instead: do not mix hydration of framework markup with a script that mutates the same DOM.

### Scripts that touch framework-rendered DOM

If a bundled script queries for an element rendered by a Svelte island, it may run **before** the island hydrates or even before the island’s JavaScript is fetched (for `client:visible`). Server-rendered HTML is present from the start, but if the script attaches listeners to it and Svelte then hydrates, Svelte takes over its own nodes: listeners attached with `addEventListener` to elements that Svelte keeps will persist, but elements Svelte replaces will lose them. Safer approaches: attach to a stable *ancestor outside the island* with event delegation, or use a custom element wrapper, or do the work inside the island.

### `is:inline`, third-party scripts and `data-astro-rerun`

Inline scripts are emitted verbatim, once per component instance. With the client router (Chapter 14), bundled module scripts execute only once for the lifetime of the session, because the browser caches module evaluation, while inline scripts re-execute only if marked `data-astro-rerun` (and, per the docs, that attribute applies to inline scripts). For code that must run on every navigation, use the `astro:page-load` event:

```html
<script>
  document.addEventListener('astro:page-load', () => {
    document.querySelector('#year')!.textContent = String(new Date().getFullYear());
  });
</script>
```

`astro:page-load` fires on initial load and after every client-router navigation, so one handler covers both. Without `<ClientRouter />`, there are no navigations, and plain top-level code suffices. Chapter 14 describes the full lifecycle.

## `transition:persist` and island state

With `<ClientRouter />`, navigations swap the body but you can keep an island alive across pages with `transition:persist`:

```html
<CartBadge client:load transition:persist />
```

If the next page contains an island with the same identity, the old island’s DOM, and hence its Svelte instance and `$state`, is moved into the new document instead of being replaced; the new page’s version of the island is discarded. Rules from the documentation and the integration’s changelog:

- **State persists; props do not by default.** The island keeps its component state but its `props` attribute is updated from the new page, and the Svelte renderer’s `setProps` pushes new values into the running component (the client entrypoint checks `existingApplications` and updates the `$state` props object, removing missing keys). This suits page-specific props such as a `title`.
- **`transition:persist-props`** additionally keeps the old props: no re-render with new values.
- **Identity.** Islands match by component and position, or you set an explicit name: `transition:persist="cart-badge"` or `transition:name="cart-badge"`. If the target page lacks a matching island, the old one is dropped (and `astro:unmount` fires, destroying the Svelte component).
- **`astro:unmount`** is dispatched on a removed island root so the renderer can `unmount()` it. Cleanups in `onMount` run then.
- **CSS animations restart and iframes reload** regardless of persistence.
- Integration 5.7.1 fixed state persistence for Svelte components under view transitions, so you need a version at or above that (any 9.x is).

For a shared rune module, persistence of the *island* is a belt-and-braces matter: module state survives client-router navigations anyway, since the page is not reloaded and the module stays cached; what resets are the *components* subscribed to it, which re-initialize from module state when they remount. That makes a rune module (or Nano Store) plus a non-persisted badge resilient: the badge remounts with the correct count. Use `transition:persist` where *component-internal* state matters: an open dropdown, a video, a form draft, an audio player. A full browser reload still resets module state; that is when you need `localStorage` or the server.

> **Senior tip:** Treat `transition:persist` as an optimization for UI continuity, never as the source of truth. State that matters belongs in a module, a session, or the server, so a reload, a back/forward cache restore, or a failed persist match does not lose it.

## Server-rendered state and the cart as a worked design

Combine the pieces for the capstone’s cart (Chapter 20 completes it):

- **Source of truth:** the server (session via actions, Chapters 11 and 12). The page props or an initial fetch provide the initial cart.
- **Client state:** a class in `cart.svelte.ts`, initialized *from a prop* in the island that renders first, never at module load.
- **Fan-out:** islands read the module; non-Svelte scripts listen for `cart:changed` events dispatched from the module’s mutators.
- **Cross-tab:** `BroadcastChannel` or `storage` event, with echo protection.
- **Server safety:** no writes in render; `cart.init()` only called in `onMount`.

```ts
// src/lib/cart.svelte.ts
class Cart {
  items = $state<Record<string, number>>({});
  ready = $state(false);

  init(initial: Record<string, number>) {
    if (this.ready) return;          // first island wins; later islands get the same state
    this.items = initial;
    this.ready = true;
  }

  add(sku: string) {
    this.items[sku] = (this.items[sku] ?? 0) + 1;
    window.dispatchEvent(new CustomEvent('cart:changed', { detail: { sku } }));
  }
}
export const cart = new Cart();
```

```html
<!-- CartBadge.svelte: server-provided initial cart via prop -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { cart } from '../lib/cart.svelte';

  let { initial = {} }: { initial?: Record<string, number> } = $props();
  onMount(() => cart.init(initial));

  const count = $derived(Object.values(cart.items).reduce((a, b) => a + b, 0));
  const shown = $derived(cart.ready ? count : Object.values(initial).reduce((a, b) => a + b, 0));
</script>
<span>Cart: {shown}</span>
```

The badge renders the server value (from the prop) before and after hydration, so there is no mismatch; `init` runs in `onMount`, never on the server, so no cross-request write occurs.

## Testing island communication

Test at the level where the contract lives.

**Unit-test the module.** Rune modules compile only through Svelte’s transform, so test them with Vitest configured with the Svelte plugin (or via Astro’s `getViteConfig()`, Chapter 17). A class with plain methods is straightforward:

```ts
// src/lib/cart.svelte.test.ts
import { describe, it, expect } from 'vitest';
import { flushSync } from 'svelte';

describe('cart', () => {
  it('counts items', async () => {
    const { cart } = await import('./cart.svelte');
    cart.init({});
    cart.add('a');
    cart.add('a');
    flushSync();
    expect(cart.items.a).toBe(2);
  });
});
```

(`add` dispatches on `window`; run these tests in an environment with `window`, such as `happy-dom` or `jsdom`, or guard the dispatch.) Note this is a Svelte-island test, so the Vitest *node* environment requirement for Astro components (Chapter 17) does not apply to it.

**Test the SSR hazard as a regression.** Start the built server, request the same page twice, and assert that responses are identical. This test is cheap and catches the entire class of module-state leaks:

```ts
// tests/ssr-isolation.test.ts
import { expect, test } from 'vitest';

test('server render has no cross-request state', async () => {
  const a = await (await fetch('http://localhost:4321/shop')).text();
  const b = await (await fetch('http://localhost:4321/shop')).text();
  expect(b).toBe(a);
});
```

**End-to-end for the real thing.** Hydration order, `client:visible` triggering, persistence under the client router and cross-tab messaging only exist in a browser. With Playwright, wait on the island’s `ssr` attribute disappearing as the signal that hydration finished:

```ts
// tests/cart.spec.ts
import { test, expect } from '@playwright/test';

test('badge updates when button island hydrates', async ({ page }) => {
  await page.goto('/shop');
  const island = page.locator('astro-island:has(button.add)');
  await island.scrollIntoViewIfNeeded();
  await expect(island).not.toHaveAttribute('ssr', '');   // hydrated
  await page.click('button.add');
  await expect(page.locator('#badge')).toHaveText('Cart: 1');
});

test('cross-tab sync', async ({ context }) => {
  const a = await context.newPage();
  const b = await context.newPage();
  await a.goto('/shop');
  await b.goto('/shop');
  await a.click('button.add');
  await expect(b.locator('#badge')).toHaveText('Cart: 1');
});
```

Waiting for `ssr` to disappear avoids the classic flake of clicking an inert server-rendered button. A final check: disable JavaScript in one test and assert that the page still shows the server-rendered content, which documents what no-JS users get.

## Key takeaways

- Islands share no tree; shared state needs a module singleton in the browser (Nano Store or `.svelte.ts` rune module) or a global channel (events). Prefer state containers over events because they survive late subscribers.
- Nano Stores suit cross-framework and `.astro` `<script>` use; in Svelte 5 runes components read them with `fromStore(...).current`. Stores cannot be props, and server writes never reach the client.
- Rune modules (`.svelte.ts`) give lightweight shared reactive state between Svelte islands (verified: separate islands import one shared chunk). Export objects or classes, not reassigned primitives; wrap module-level effects in `$effect.root`.
- Module state on the server is shared by all requests in a process. A top-level write during SSR leaked state across requests (`n=1`, `n=2`, `n=3` in a verified Node build). Write only in handlers, `onMount` and `$effect`; pass per-request data as props.
- Initialize client state in `onMount` from a prop or storage to keep server HTML and first client render identical.
- `CustomEvent` on `window` is ideal for notifications; register in `onMount`, clean up, type via `WindowEventMap`. Events are lost if the listener has not hydrated yet.
- `BroadcastChannel` and `storage` events sync tabs; guard against echo loops. Verify `origin` for `postMessage`.
- Use custom elements for scripts that must handle many instances or framework-rendered DOM; define them once, clean up in `disconnectedCallback`. Use `astro:page-load` for per-navigation code.
- `transition:persist` keeps island state across client-router navigations and updates props unless `transition:persist-props` is set; treat it as UX continuity, not the source of truth.
- Test modules with Vitest, SSR isolation with repeated requests, and hydration/persistence/cross-tab behaviour with Playwright, waiting for the `ssr` attribute to be removed.

## Review Questions

1.  List the three requirements any cross-island communication mechanism must satisfy. Which of them do plain `CustomEvent`s fail by themselves?

2.  Why does the Astro recipe choose Nano Stores rather than Svelte context for sharing state between islands?

3.  Rewrite the legacy snippet `<button on:click={() => isOpen.set(!$isOpen)}>` for Svelte 5 runes, using a Nano Store atom.

4.  Name three limitations the docs give for using Nano Stores in `.astro` frontmatter or non-hydrated components, and explain each as a consequence of the rendering model.

5.  What does this code do, and why is it a bug in a long-running Node server?

    ```html
    <script lang="ts">
      import { visits } from '../lib/stats.svelte';   // export const visits = $state({ n: 0 })
      visits.n++;
    </script>
    <p>Visitors: {visits.n}</p>
    ```

6.  The page above works in development and in a static build but misbehaves in production on-demand. Why does the problem hide in the static build?

7.  Give three distinct ways to fix question 5’s component so that every visitor sees a value that does not depend on earlier requests.

8.  Why can `export let count = $state(0)` not be incremented from another module, and what are two alternatives?

9.  Write a class-based `Counter` rune module with a `$derived` double, an `increment()` method, and explain why a class is convenient for module-level state.

10. When must `$effect.root()` be used in a `.svelte.ts` module? What does it return, and who is responsible for calling it?

11. Multiple choice. Two islands `client:load` import `cart.svelte.ts`. In the browser: (a) each gets a private copy; (b) they share one instance; (c) the module is evaluated once per island directive; (d) state is shared only if both use `transition:persist`.

12. A `client:visible` button island fires `cart:add` before the `client:idle` badge island has hydrated. What happens to the event, and what design change prevents a wrong badge count?

13. Why must event listeners be registered in `onMount` (or an effect) and cleaned up? Name two situations in which an island is created and destroyed repeatedly.

14. How do you get type-safe `addEventListener('cart:add', e => e.detail.sku)` without casts?

15. What does `BroadcastChannel` not deliver to, and when would you prefer the `storage` event? Describe the echo problem in a cross-tab cart sync.

16. A script at the top of an `.astro` component queries `document.querySelector('.stepper')`. The component is used five times on the page and sometimes inside a Svelte island’s slot. List two problems and the fix.

17. Complete this custom element so that it cleans up properly:

    ```ts
    class Tabs extends HTMLElement {
      connectedCallback() {
        this.querySelectorAll('button').forEach((b) =>
          b.addEventListener('click', () => this.select(b)));
      }
      select(b: Element) { /* ... */ }
    }
    customElements.define('x-tabs', Tabs);
    ```

18. Why guard `customElements.define` with `customElements.get`?

19. With `<ClientRouter />`, a bundled `<script>` in a layout runs how many times across ten navigations? Which event do you use to run code after every navigation, and what does `data-astro-rerun` apply to?

20. An island has `transition:persist`. The next page contains the same island with a different `title` prop. What happens to its internal `$state` and to `title`? What changes with `transition:persist-props`?

21. Where is `astro:unmount` dispatched and who listens to it? What happens to `onMount` cleanups?

22. If the shared cart lives in a rune module, is `transition:persist` required for the badge to keep its count across client-router navigations? Explain, and say what *would* require persist.

23. Hydration mismatch: the server renders `Cart: 0`, and a `localStorage` read at module load makes the first client render `Cart: 3`. Give two strategies to avoid the mismatch.

24. In Playwright, how do you know an island has finished hydrating before clicking, and why does the test flake without it?

25. Write a regression test, in prose or code, that detects cross-request SSR state leaks in a built server.

26. Design: a site has a Svelte cart island, a React-free `.astro` header with a “Cart (n)” link updated by a plain `<script>`, and a checkout page reached via client-router navigation. Choose the state mechanism(s), where initialization happens, and how the header script stays in sync after navigations.
