# Chapter 12: State Management: Server, Client, and URL

In a client-only app, “state management” is a question about libraries. In SvelteKit it is a question about *where state is allowed to live*. The same module is evaluated on a long-lived server that serves thousands of users, and in a browser tab that serves exactly one. The same component renders once on the server and again on the client. The history stack, the URL and `sessionStorage` all hold state that survives things your component tree does not. Getting this wrong produces the worst class of bug a web framework offers: one user seeing another user’s data.

This chapter gives you a map. We start with the hazards of shared server state, then cover client state with runes and context, URL-driven state, page state and shallow routing, the reactive `$app/state` module (and what replaced `$app/stores`), snapshots, navigation lifecycle hooks and view transitions, remote-function caches as state, and finish with a decision guide for where each kind of state belongs. Svelte 5 runes are assumed; the Svelte book covers their semantics. Examples use `#lib`, never `$lib`.

## Server state: the shared-process hazard

A browser tab is stateful and single-user. A Node (or Bun) server process is *stateful and multi-user*: module-level variables live as long as the process, and every request shares them. Conceptually, SvelteKit treats the server as stateless; physically it is not, and the code you write must behave as if it were.

```ts
// src/routes/profile/+page.server.ts
let user: { name: string; secret: string } | undefined; // module scope: shared by everyone

export function load() {
    return { user };
}

export const actions = {
    default: async ({ request }) => {
        const data = await request.formData();
        // NEVER DO THIS: Alice's data is visible to Bob
        user = { name: String(data.get('name')), secret: String(data.get('secret')) };
    }
};
```

Besides leaking data between users, module state is lost when the process restarts and diverges between instances behind a load balancer. The remedy is always the same: identify the user from the request (cookies, Chapter 14) and persist state in a datastore.

### Safe and unsafe module-level state

Not all module-level state is a bug. The question is whether it is *per-user*.

| Pattern | Safe? | Why |
|------------------------|------------------------|------------------------|
| Database pool, HTTP agent, loaded config | Yes | Shared infrastructure, identical for all users |
| In-memory cache of public, user-independent data (with TTL) | Yes, with care | Same value for everyone; beware unbounded growth |
| `let currentUser` set in `handle` | **No** | Races between concurrent requests |
| A Svelte `$state` or store in a shared `.svelte.ts` module, mutated during SSR | **No** | Shared singleton, survives across requests |
| Per-request values on `event.locals` | Yes | Scoped to the request |

The rule extends to *universal* modules: `.svelte.ts` files that export `$state` objects run on the server during SSR, once per process. If a `load` or component writes to such an object during server rendering, the write is visible to the next request.

```ts
// src/lib/cart.svelte.ts   (imported as #lib/cart.svelte.js)
export const cart = $state({ items: [] as string[] }); // singleton!
```

On the client, this is fine: one tab, one user. On the server, anything that writes to `cart` leaks. Either guarantee that it is only written in the browser (inside `$effect`, event handlers, or `if (browser)`), or avoid the singleton by using context (below).

### No side effects in `load`

`load` functions must be pure: take input, return data. A load that writes to a store, a module variable or a global is a hazard on the server (shared across users) and also on the client (it makes behaviour depend on invocation order, which changes when SvelteKit reruns loads selectively; see Chapter 5). Return the data and let components or `page.data` carry it.

```ts
// src/routes/+layout.ts
import type { LayoutLoad } from './$types';
import { user } from '#lib/user.svelte.js';

export const load: LayoutLoad = async ({ fetch }) => {
    const me = await (await fetch('/api/me')).json();
    user.current = me; // NEVER DO THIS
    return {};
};
```

```ts
// src/routes/+layout.ts (correct)
import type { LayoutLoad } from './$types';

export const load: LayoutLoad = async ({ fetch }) => {
    return { user: await (await fetch('/api/me')).json() };
};
```

If you are not using SSR at all and can guarantee you never will, module singletons are safe, but you still lose the clarity of having data flow through `load`.

### `locals` and `getRequestEvent`: request-scoped state

For server-only per-request state (the authenticated user, a request id, a tenant), use `event.locals`, typed through `App.Locals` in `src/app.d.ts`. It is created per request, populated in `handle`, and available in server `load`, actions, `+server` handlers and remote functions (via `getRequestEvent()` from `$app/server`).

```ts
// src/app.d.ts
declare global {
    namespace App {
        interface Locals {
            user: { id: string; name: string } | null;
            requestId: string;
        }
    }
}
export {};
```

```ts
// src/hooks.server.ts
import type { Handle } from '@sveltejs/kit/hooks';

export const handle: Handle = async ({ event, resolve }) => {
    event.locals.requestId = crypto.randomUUID();
    event.locals.user = await lookupUser(event.cookies.get('session'));
    return resolve(event);
};
```

Two caveats (details in Chapters 6 and 9): `handle` does not rerun for each form action *after* the initial request, so if an action changes the user, update `event.locals` yourself; and `locals` are server-only, so to make a value visible to components you return it from a server `load`.

For *deep* call chains, `getRequestEvent()` lets helper functions read request state without threading `event` through every signature. It works in `handle`, `load`, actions and remote functions, and throws outside a request. This is a form of async-local request context; use it for things like `requireUser()` (Chapter 14), not as a general dependency-injection container.

## Client state: runes, modules and context

On the client you have the full Svelte 5 toolbox. The SvelteKit-specific question is which scope a piece of state belongs to.

### Component-local state

`$state` in a component is local to that component instance. This is the default and the right answer for most UI state: input values, open/closed toggles, hover state.

### Shared state in modules (client-only)

A `.svelte.ts` module exporting state is a singleton for the lifetime of the page. In a pure client app that is exactly what a global store is. In SvelteKit it is only safe for state that is written *in the browser only*.

```ts
// src/lib/prefs.svelte.ts
import { browser } from '$app/env';

class Preferences {
    density = $state<'compact' | 'comfortable'>('comfortable');

    constructor() {
        if (browser) {
            const saved = localStorage.getItem('density');
            if (saved === 'compact' || saved === 'comfortable') this.density = saved;
        }
    }

    set(value: 'compact' | 'comfortable') {
        this.density = value;
        if (browser) localStorage.setItem('density', value);
    }
}

export const prefs = new Preferences();
```

During SSR, `prefs.density` is always `'comfortable'` for every user (it is never written on the server), so there is no leak, but the server-rendered HTML will not reflect the stored preference and hydration will flip it. If SSR output must reflect a user preference, store it in a cookie and read it in `handle`/`load`, then pass it down.

### Context: per-request, per-tree state

Svelte’s context API attaches state to the component tree, so each request (each SSR render) and each mounted app gets its own instance. This is how `page` from `$app/state` works on the server: it reads a request-scoped context created by SvelteKit, which is why `page.data` can only be read *during rendering* on the server (not from `load`, not from module scope, and, in dev, a clear error will tell you so). In the browser it can be read at any time.

Build your own request-scoped state the same way:

```html
<!-- src/routes/+layout.svelte -->
<script lang="ts">
    import { setCartContext } from '#lib/cart-context.svelte.js';
    let { data, children } = $props();

    setCartContext(data.initialCart);
</script>

{@render children()}
```

```ts
// src/lib/cart-context.svelte.ts
import { getContext, setContext } from 'svelte';

const KEY = Symbol('cart');

class Cart {
    items = $state<string[]>([]);
    constructor(initial: string[]) {
        this.items = initial;
    }
    add(id: string) {
        this.items.push(id);
    }
    get count() {
        return this.items.length;
    }
}

export function setCartContext(initial: string[]) {
    return setContext(KEY, new Cart(initial));
}

export function getCartContext(): Cart {
    return getContext<Cart>(KEY);
}
```

Each SSR render creates a fresh `Cart`, seeded from the layout’s `data`. On the client there is exactly one. Use a `Symbol` key to avoid collisions.

> **Note:** If you pass a *value* into `setContext` that originates from reactive props (`data.user`), pass a function or an object with getters so that updates propagate; a plain value is captured once (see the Svelte book on passing state into functions). In the example above the `Cart` owns its state, so the issue does not arise, but if `data.initialCart` changes on navigation, nothing will reseed the cart. That is usually the correct behaviour for client-owned state, and wrong for server-owned state: decide which one you have.

Context has one more limitation relevant to SSR: it flows *down* the tree. During server rendering, a child that updates context cannot affect a parent that has already been rendered into the output stream. On the client, the update propagates upward as expected. That mismatch causes “flash of different value” during hydration. Pass state down; do not rely on children to push state up to layouts.

### Component and page state is preserved across navigations

SvelteKit reuses layout and page components when navigating between URLs that match the same route. Going from `/blog/a` to `/blog/b` updates the `data` prop and does *not* destroy and recreate the component. `onMount` does not rerun, and any non-reactive computation from props becomes stale:

```html
<script lang="ts">
    let { data } = $props();

    // BUG: computed once, stale after navigating to another post
    const readingTime = data.content.split(' ').length / 250;
</script>
```

```html
<script lang="ts">
    let { data } = $props();

    const wordCount = $derived(data.content.split(' ').length);
    const readingTime = $derived(wordCount / 250);
</script>
```

If you *want* a fresh instance per URL (resetting scroll containers, local state, animations), key it:

```html
<script lang="ts">
    import { page } from '$app/state';
    import Article from './Article.svelte';
    let { data } = $props();
</script>

{#key page.url.pathname}
    <Article {data} />
{/key}
```

Reuse is a feature: a sidebar’s scroll position, an open accordion and a playing video survive navigation within the layout. Choose per component whether it should be keyed.

## URL state

If state should survive a reload, be shareable, be bookmarkable, or influence server rendering, put it in the URL. Filters, sort order, pagination, the selected tab and search terms are the canonical examples. The URL is also the only state that works without JavaScript: a `<form method="GET">` and `<a href="?page=2">` are state transitions.

```ts
// src/routes/products/+page.server.ts
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ url }) => {
    const sort = url.searchParams.get('sort') === 'price' ? 'price' : 'name';
    const page = Math.max(1, Number(url.searchParams.get('page') ?? '1') || 1);
    return { products: await listProducts({ sort, page }), sort, page };
};
```

The `load` re-runs when a *tracked* search param changes (SvelteKit tracks `url.searchParams` per key; Chapter 5). The component reads and writes the URL:

```html
<!-- src/routes/products/+page.svelte -->
<script lang="ts">
    import { goto } from '$app/navigation';
    import { page } from '$app/state';
    import { resolve } from '$app/paths';
    let { data } = $props();

    function setSort(sort: string) {
        const next = new URL(page.url);
        next.searchParams.set('sort', sort);
        next.searchParams.delete('page'); // reset pagination on sort change
        goto(next, { replace: true, reset: false });
    }
</script>

<nav aria-label="Sort">
    <a href="?sort=name" aria-current={data.sort === 'name'}>Name</a>
    <a href="?sort=price" aria-current={data.sort === 'price'}>Price</a>
</nav>

<ul>
    {#each data.products as p (p.id)}
        <li><a href={resolve('/products/[id]', { id: p.id })}>{p.name}</a></li>
    {/each}
</ul>
```

Notes on the `goto` options in 3.x:

- `replace: true` swaps the current history entry rather than pushing one; use it for continuous controls like text filters, so that Back does not step through every keystroke.
- `reset: false` keeps scroll position and focus. (`noScroll` and `keepFocus` were removed in 3.0.)
- Prefer real `<a href>` and `<form method="GET">` where possible; they work before hydration and keep prefetch (`data-sveltekit-preload-data`) available.

Two design rules for URL state:

1.  **Validate on read.** URL state is user input. Coerce and clamp it in `load` exactly as you would a form field.
2.  **Keep it canonical.** Omit defaults (`?page=1` should not appear) so that equivalent states share one URL, which matters for caches and SEO.

When the same page is *prerendered*, reading `url.searchParams` during the build is an error (Chapter 11); a prerendered page can still read it in the browser via `page.url.searchParams`.

## Page state and shallow routing

URL state is shareable state. Sometimes you want state that belongs to a *history entry* but not to the URL: a modal that closes when the user swipes back, a lightbox, a multi-step dialog. SvelteKit calls this page state and exposes it through `goto` with `shallow: true`.

```html
<!-- src/routes/photos/+page.svelte -->
<script lang="ts">
    import { goto } from '$app/navigation';
    import { page } from '$app/state';
    import Modal from './Modal.svelte';

    function open() {
        goto('', { shallow: true, state: { showModal: true } });
    }
</script>

<button onclick={open}>Open</button>

{#if page.state.showModal}
    <Modal close={() => history.back()} />
{/if}
```

Declare the shape in `src/app.d.ts` for type safety:

```ts
// src/app.d.ts
declare global {
    namespace App {
        interface PageState {
            showModal?: boolean;
            selected?: { id: string; title: string };
        }
    }
}
export {};
```

Behaviours to know (all from the 3.x API; `pushState`/`replaceState` are deprecated aliases for this):

- `goto(url, { shallow: true, state })` pushes a history entry and updates `page.state`, **without** running `load` or changing which components are rendered. `goto(..., { replace: true, shallow: true })` replaces the current entry instead.
- `beforeNavigate`, `onNavigate` and `afterNavigate` all run for shallow navigations, with `navigation.type === 'goto'` and `navigation.shallow === true`. Handlers that assume a real navigation (for example scroll tracking, analytics page views) should check `navigation.shallow`.
- Shallow navigations keep scroll and focus by default (`reset` defaults to `false` when `shallow` is true).
- While shallow routing is active, `page.shallow` is `{ url, params, route }` describing the page that would be rendered if the user reloaded; `page.url` still describes what is rendered. A normal link click or non-shallow `goto` exits shallow routing.
- On a full reload, `page.state` is empty by default and the browser lands on the visible URL (`page.shallow.url`). Pass `persistState: true` to restore `page.state` after reload.
- During SSR, `page.state` is `{}` (the server cannot see history state). UI that depends on it appears only after JavaScript loads, which can flicker. Progressive-enhancement-minded designs make the modal’s content a real route too (`/photos/123`) and treat the shallow entry as an optimisation.

### The route-in-a-modal pattern

The most common production use of shallow routing is showing a route’s content in a modal over the current page, while giving it a real URL for direct visits. The flow: intercept the link click, preload the target route’s data, push a shallow entry carrying that data, and render the target’s page component inside the modal.

```html
<!-- src/routes/photos/+page.svelte -->
<script lang="ts">
    import { goto, preloadData } from '$app/navigation';
    import { page } from '$app/state';
    import Modal from './Modal.svelte';
    import PhotoPage from './[id]/+page.svelte';

    let { data } = $props();

    async function onclick(e: MouseEvent & { currentTarget: HTMLAnchorElement }) {
        if (innerWidth < 640 || e.shiftKey || e.metaKey || e.ctrlKey) return;
        e.preventDefault();

        const { href } = e.currentTarget;
        const result = await preloadData(href);

        if (result.type === 'loaded' && result.status === 200) {
            goto(href, { shallow: true, state: { selected: result.data } });
        } else {
            goto(href); // fall back to a real navigation
        }
    }
</script>

{#each data.thumbnails as t (t.id)}
    <a href="/photos/{t.id}" {onclick}><img src={t.src} alt={t.alt} /></a>
{/each}

{#if page.state.selected}
    <Modal onclose={() => history.back()}>
        <PhotoPage data={page.state.selected} />
    </Modal>
{/if}
```

`preloadData` returns one of three shapes (`loaded`, `redirect`, `error`; Chapter 5), which is why the example verifies `result.type === 'loaded'`. If the user reloads while the modal is open they land on `/photos/123`, the full page, which is the correct degradation.

## `$app/state`: `page`, `navigating`, `updated`

SvelteKit 3 removed `$app/stores`. The replacement, `$app/state`, exposes three *reactive objects* built on runes. They are read like plain properties; no `$` prefix, no subscription.

```html
<script lang="ts">
    import { page, navigating, updated } from '$app/state';
</script>

<p>Route: {page.route.id} ({page.status})</p>
{#if navigating.to}
    <progress aria-label="Loading {navigating.to.url.pathname}"></progress>
{/if}
{#if updated.current}
    <button onclick={() => location.reload()}>New version available</button>
{/if}
```

| Object | Properties | Notes |
|------------------------|------------------------|------------------------|
| `page` | `url` (readonly), `params`, `route.id`, `status`, `error`, `data`, `state`, `shallow`, `form` | Reactive: use in `$derived`/`$effect`/markup. On the server, readable only during rendering |
| `navigating` | `from`, `to`, `type`, `willUnload`, `delta`, `complete` | All `null` when idle and on the server. `delta` only for `popstate` |
| `updated` | `current` (boolean), `check()` | New-deployment detection |

Practical points:

- **Use `$derived`, not `$:`.** `page` changes are only reflected with runes. `const id = $derived(page.params.id)` updates; a legacy `$:` statement referencing it does not.
- **`page.data` is the merged data of every active `load`.** It is `$state.raw` internally, so replace, don’t mutate. Type the shared part via `App.PageData`. Prefer the `data` prop in the component that owns the route; use `page.data` in *layout-level chrome* (a header that needs the page title from whichever page is active).
- **`page.error` and `page.status`** let a layout react to error pages; error boundaries are covered in Chapter 10.
- **`navigating` has no server meaning.** It is `null` fields on the server and during hydration; render a progress indicator only from it.
- **Server reads must happen during render.** Reading `page.url` in a `load`, in module scope or after an `await` in server code throws (in dev with an explicit message). In `load`, use the event’s `url` instead.

### `updated`: detecting a new deployment

`updated.current` becomes `true` when the running deployment differs from the one the page was loaded from (`version.name`). In 3.x, SvelteKit checks not only on a poll timer (`version.pollInterval`, default one hour; `0` disables polling) but also from the `x-sveltekit-version` header on data requests, remote function calls and form actions, and when the tab regains focus or visibility. `updated.check()` forces an immediate check and returns a promise for the result. Use it to surface a “reload to update” prompt, or to skip client-side navigation and do a full page load when a new version is out:

```html
<!-- src/routes/+layout.svelte -->
<script lang="ts">
    import { beforeNavigate } from '$app/navigation';
    import { updated } from '$app/state';

    beforeNavigate(({ willUnload, to }) => {
        if (!willUnload && updated.current && to?.url) {
            location.href = to.url.href; // force a full load into the new version
        }
    });
</script>
```

### Migrating from `$app/stores`

`$app/stores` is removed in 3.0. The code-mod is `npx sv migrate app-state`; manually it is mechanical:

```html
<!-- Before (SvelteKit 2 stores) -->
<script>
    import { page, navigating } from '$app/stores';
</script>
<p>{$page.url.pathname}</p>
{#if $navigating}...{/if}

<!-- After -->
<script>
    import { page, navigating } from '$app/state';
</script>
<p>{page.url.pathname}</p>
{#if navigating.to}...{/if}
```

Note that `navigating` was `null` when idle as a store; as a state object it is *always an object* whose fields are `null` when idle, so `{#if navigating}` is now always true. Test `navigating.to` (or `.type`) instead. This is the most common silent migration bug.

## Snapshots

Ephemeral DOM state (what the user typed into an uncontrolled field, a scroll position in a container, which accordion is open) is discarded when they navigate away. For states where “back” should restore it, but where neither a URL nor a database write is warranted, SvelteKit offers *snapshots*: values captured when leaving a history entry and restored when returning to it.

```html
<!-- src/routes/feedback/+page.svelte -->
<script lang="ts">
    import { snapshot } from '$app/navigation';

    let comment = $state('');
    let rating = $state(3);

    snapshot({
        id: 'feedback-form',
        capture: () => ({ comment, rating }),
        restore: (value) => {
            comment = value.comment;
            rating = value.rating;
        },
        reset: () => {
            comment = '';
            rating = 3;
        }
    });
</script>

<form method="POST">
    <textarea bind:value={comment}></textarea>
    <input type="range" min="1" max="5" bind:value={rating} />
    <button>Send</button>
</form>
```

How it works (from the 3.x implementation):

- `snapshot()` is a function you call during component initialisation, from *any* component (not only pages and layouts). It registers on mount and unregisters on destroy.
- On navigation away, `capture` of every registered snapshot is called immediately before the page updates; the result is stored against the **history entry index**. Going back restores it by calling `restore(value)` after the page updates.
- `reset` runs on navigations where there is nothing to restore, for example a fresh link click creating a new entry, so that a reused component instance does not carry state from a previous entry.
- Values are serialised with **devalue**, so `Date`, `Map`, `Set`, `BigInt` and custom types registered in your `transport` hook (Chapter 9) round-trip. The result is persisted in `sessionStorage`, so state survives reloads and back-navigation from another site within the tab’s session.
- Shallow navigations also capture and restore, because each shallow entry is its own history entry.
- The `id` defaults to a hash derived from the call site (a stack frame). Give explicit ids when you want stability across deployments (the stack frame changes when source changes, orphaning stored values), or when one helper function or component is used multiple times and would otherwise produce duplicate ids. Duplicate ids on mounted snapshots raise a development error.

> **Warning:** Do not capture large objects. Captured values are kept in memory for the whole session and written to `sessionStorage`, which is small (roughly 5 MB per origin) and synchronous. Capture ids and small form values, never data you can refetch.

The legacy form, `export const snapshot = { capture, restore }` in `+page.svelte`/`+layout.svelte`, is deprecated. It serialises as JSON (not devalue) and shallow navigations do not capture it. Migrate to the function.

Snapshots are *not* a substitute for persistent drafts. They are keyed to history entries in one tab; a new tab, a cleared session or a different route entry gets nothing. For drafts that must survive, persist to the server or `localStorage` deliberately.

## Navigation lifecycle: before, on, after

Three lifecycle functions let components observe and influence navigation. Each must be called during component initialisation and is active while the component is mounted.

| Function | Runs | Can do |
|------------------------|------------------------|------------------------|
| `beforeNavigate(cb)` | Before any navigation (link, `goto`, back/forward, leaving the app) | `cancel()`; inspect `from`, `to`, `type`, `willUnload` |
| `onNavigate(cb)` | Immediately before navigating, except full-page navigations | Return a promise to delay completion; return a function to run after the DOM updates |
| `afterNavigate(cb)` | When the component mounts and after every navigation | Read-only; the right place for “page view” side effects |

```html
<script lang="ts">
    import { beforeNavigate, afterNavigate } from '$app/navigation';

    let dirty = $state(false);

    beforeNavigate(({ cancel, type, willUnload }) => {
        if (!dirty) return;
        // for 'leave', cancel() triggers the browser's native confirmation dialog
        if (type === 'leave' || willUnload) return cancel();
        if (!confirm('Discard unsaved changes?')) cancel();
    });

    afterNavigate(({ type, from, to, shallow }) => {
        if (shallow) return;
        analytics.pageview(to?.url.pathname ?? location.pathname, { from: from?.url.pathname, type });
    });
</script>
```

Specifics worth remembering:

- `navigation.type` is one of `enter` (the app hydrated), `form` (GET form), `goto`, `leave` (the document is being left), `link`, `popstate`. `delta` exists only for `popstate`.
- `willUnload` is `true` for `leave` navigations and for link navigations whose target is not a SvelteKit route (an `<a rel="external">` or a URL outside the app).
- `navigation.complete` is a promise that resolves when the navigation completes and rejects when it fails or is aborted. It never resolves for `willUnload` navigations.
- `from`/`to` are `NavigationTarget` objects with `url`, `params`, `route.id`, and `scroll`. For `to` in `beforeNavigate`/`onNavigate`, `scroll` is only known on `popstate`.
- Calling `invalidate`/`refreshAll` while a navigation is in flight no longer aborts it (3.0).
- Clicking a link to the *current* URL triggers `refreshAll`.

### View transitions

`onNavigate` is the integration point for the View Transitions API: returning a promise delays the DOM update until the transition has captured the old state.

```html
<!-- src/routes/+layout.svelte -->
<script lang="ts">
    import { onNavigate } from '$app/navigation';

    onNavigate((navigation) => {
        if (!document.startViewTransition) return;

        return new Promise((resolve) => {
            document.startViewTransition(async () => {
                resolve(); // let SvelteKit update the DOM
                await navigation.complete; // transition finishes after the navigation does
            });
        });
    });
</script>

<style>
    @keyframes fade-in { from { opacity: 0; } }
    @keyframes fade-out { to { opacity: 0; } }

    :root::view-transition-old(root) { animation: 90ms both fade-out; }
    :root::view-transition-new(root) { animation: 210ms 90ms both fade-in; }

    @media (prefers-reduced-motion: reduce) {
        :root::view-transition-group(*), :root::view-transition-old(*), :root::view-transition-new(*) {
            animation: none;
        }
    }
</style>
```

Do not return slow promises from `onNavigate`; the navigation will appear to stall. Skip the transition on shallow navigations (`if (navigation.shallow) return`) unless you really want it, and honour `prefers-reduced-motion`.

> **Note:** Svelte scopes component CSS, so global view-transition pseudo-selectors written in a component `<style>` need `:global(...)` or must live in a global stylesheet. Put the transition CSS in your global CSS file in a real app.

## Remote-function caches as state

If you use experimental remote functions (Chapters 7 and 8; both `experimental.remoteFunctions` and `compilerOptions.experimental.async` flags required), you gain a state container you did not write: the client-side cache of `query` results. A `query` call is cached by its serialised arguments, shared by every component that calls it with the same arguments, kept while in use and deduplicated per request on the server.

That makes queries a replacement for much of what teams reach for a global store to do: “the current user”, “the cart”, “the notification count” can each be a `query` that any component awaits. Mutations (`form`, `command`) then update that state through `refresh()`, `set()` or optimistic `withOverride()`; single-flight mutations send the new value along with the mutation response.

```ts
// src/lib/cart.remote.ts
import * as v from 'valibot';
import { query, command, getRequestEvent } from '$app/server';

export const getCart = query(async () => {
    const { locals } = getRequestEvent();
    return await loadCart(locals.user?.id);
});

export const addToCart = command(v.string(), async (sku) => {
    const { locals } = getRequestEvent();
    await insertCartItem(locals.user?.id, sku);
    await getCart().refresh(); // single-flight: updated value rides back in this response
});
```

Treat this cache as **server state mirrored on the client**. Do not copy it into `$state` and edit it locally; that creates two sources of truth. Edit through the mutation API so the cache and server stay consistent. Also note that queries are not re-run on navigation unless their arguments change, so they must not depend on `url`, `params` or `route`: those throw inside a query in 3.0.

## A decision guide

| State | Lives in | Why |
|------------------------|------------------------|------------------------|
| Per-user, authoritative, durable (profile, orders) | Database; read via `load`/`query` | Survives everything; the only trustworthy source |
| Identity of the current request’s user | Cookie, then `event.locals` | Request-scoped; never module scope |
| Server data displayed by a page | `load` return value → `data` prop | Participates in SSR, invalidation, streaming |
| Server data shared by many components, mutated by the client | `query` cache (if using remote functions) or `load` + `invalidate` | One source of truth, consistent invalidation |
| Filters, sort, pagination, tabs, search | URL search params | Shareable, SSR-visible, works without JS |
| Modal, lightbox, wizard step that Back should close | `page.state` via shallow `goto` | History-entry scoped, no URL pollution |
| Half-typed form values, scroll positions, accordion state | `snapshot()` | Restored on Back, no server round trip |
| UI preferences (theme, density) | Cookie (if SSR must reflect it) or `localStorage` | Cookie is visible to the server; storage is not |
| Pure UI state of one component | `$state` | Smallest possible scope |
| UI state shared in a subtree, differing per request | Context holding rune-based class instance | SSR-safe per-request instance |
| Browser-only shared state (audio player, WebSocket status) | `.svelte.ts` singleton guarded for browser | One tab, one user; never written on the server |
| Expensive cross-user cache on the server | Module-level cache of user-independent data with TTL and bounds | Shared by design; must not hold user data |

Two heuristics condense the table. First: **if the server needs it, it cannot live only in the client** (URL, cookie or database). Second: **if it is per-request, it cannot live in module scope** (context or `locals`).

## Key takeaways

- Server processes are long-lived and shared; module-level mutable state is shared by every user. Never store per-user data in module scope, including `$state` in `.svelte.ts` modules that run during SSR.
- Keep `load` pure. Return data; do not write to stores or globals. `event.locals` and `getRequestEvent()` are the request-scoped mechanisms on the server.
- On the client, use component `$state` by default, context for per-request/per-tree state, and `.svelte.ts` singletons only for state written exclusively in the browser. Context flows down; do not rely on children updating parents during SSR.
- Components and layouts are reused across navigations within a route; derive values with `$derived`, or `{#key}` the component to force a reset.
- Put shareable, reload-surviving, SSR-affecting state in the URL and validate it on read. Use `replace: true` for continuous controls and `reset: false` to keep scroll and focus.
- Page state and shallow routing (`goto(url, { shallow: true, state })`, `page.state`, `page.shallow`, optional `persistState`) tie UI state to history entries; `page.state` is empty during SSR, so design a real-route fallback. `pushState`/`replaceState` are deprecated.
- `$app/state` (`page`, `navigating`, `updated`) replaces the removed `$app/stores`; drop the `$`, and replace `{#if $navigating}` with `{#if navigating.to}`. On the server, `page` is readable only during render.
- Snapshots (`snapshot({ id?, capture, restore, reset? })`) restore ephemeral UI state per history entry via devalue-serialised `sessionStorage`; give explicit ids, keep payloads small, and prefer the function form over the deprecated export.
- `beforeNavigate`, `onNavigate` and `afterNavigate` observe and influence navigation; they fire for shallow navigations too (`navigation.shallow`). `onNavigate` is where view transitions plug in.
- Remote-function query caches are client-side mirrors of server state; mutate through the API rather than copying into local state.

## Review Questions

1.  Why is `let user;` at module scope of a `+page.server.ts` a security bug in a deployed SvelteKit app, even if it “works” in local development with one browser tab?

2.  Which of these module-level values is safe on the server? (a) a database connection pool, (b) `let currentUser` assigned in `handle`, (c) a `$state` object in `cart.svelte.ts` written by an event handler in the browser, (d) a TTL cache of the public product catalogue.

3.  What does this code print on the server, and what is wrong with the design?

    ```ts
    // src/lib/session.svelte.ts
    export const session = $state({ userId: null as string | null });

    // src/routes/+layout.server.ts
    import { session } from '#lib/session.svelte.js';
    export function load({ locals }) {
     session.userId = locals.userId;
     return {};
    }
    ```

4.  Explain why `page` from `$app/state` can be used on the server without being a shared singleton. What restriction does that imply for where you can read it?

5.  Find the bug in this component and fix it:

    ```html
    <script lang="ts">
     let { data } = $props();
     const slug = data.post.slug.toUpperCase();
    </script>
    <h1>{slug}</h1>
    ```

    Describe the exact user action that exposes it.

6.  When is `{#key page.url.pathname}` around a component the right choice, and what do you lose by using it?

7.  A product list’s sort order is held in `$state` and sent to the server in a `POST`. List three user-visible problems this causes compared with storing sort in the URL.

8.  Multiple choice: for a text filter input that updates the URL on each keystroke, which `goto` options are most appropriate?

    a.  `{ replace: true, reset: false }`
    b.  `{ shallow: true }`
    c.  `{ refreshAll: true }`
    d.  `{ persistState: true }`

9.  Why should URL-derived state be validated and canonicalised in `load`? Give an example of each.

10. What does `goto('', { shallow: true, state: { showModal: true } })` change, and what does it not change? Be specific about `load` functions, components, history, `page.url`, `page.state` and `page.shallow`.

11. A user opens a photo modal with shallow routing and presses reload. What do they see, and what does `persistState: true` change?

12. What does `page.state` contain during server-side rendering, and what design consequence does this have for modals driven by it?

13. Convert to SvelteKit 3 and explain the pitfall:

    ```html
    <script>
        import { navigating } from '$app/stores';
    </script>
    {#if $navigating}<Spinner />{/if}
    ```

14. Why is `$: id = page.params.id` wrong with `$app/state`, and what is the correct replacement?

15. Where can you read `page.url` on the server, and where does it throw? What should you use inside a `load` function instead?

16. What are the three sources that can set `updated.current` to `true` in SvelteKit 3? What does `version.pollInterval: 0` change?

17. Write a `beforeNavigate` handler that blocks leaving a dirty form, correctly handling both in-app navigation and closing the tab.

18. Multiple choice: which statement about `snapshot()` is true?

    a.  It stores captured values in `localStorage` as JSON.
    b.  It can only be called from `+page.svelte` files.
    c.  Captured values are serialised with devalue and persisted to `sessionStorage`, keyed by history entry.
    d.  `restore` is called before the navigation starts.

19. Two instances of the same `<Notes />` component each call `snapshot({ capture, restore })` without an id. What can go wrong, and how do you fix it? What goes wrong across deployments when ids are auto-generated?

20. What is the `reset` callback of `snapshot` for? Give an example where, without it, a reused component shows stale state.

21. Explain why `onNavigate` is the right hook for view transitions and what you must return from it. What is the risk of returning a slow promise?

22. A page-view analytics call is placed in `afterNavigate`. Why should it check `navigation.shallow`? What would be double-counted if it did not?

23. You adopt remote functions and write `const cart = $state(await getCart())` in a component, then edit `cart` locally after a mutation. What is wrong with this approach, and what do you do instead?

24. Design question: users filter a table, open a row in a side panel, and type notes about a row. For each of (filter, open-row, unsent notes) choose URL, page state, snapshot, cookie, or database and justify it in one sentence.

25. Why can a child component pushing state *up* into a parent via context cause a hydration flash, and what is the recommended data-flow direction?

26. A theme preference must be correct in the very first server-rendered byte (no flash). Which of `localStorage`, a cookie, `page.state` or a `.svelte.ts` singleton can achieve that, and how is it plumbed to the component tree?
