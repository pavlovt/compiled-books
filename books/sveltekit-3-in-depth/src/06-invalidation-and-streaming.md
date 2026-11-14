# Chapter 5: Invalidation and Streaming

Chapter 4 described how a `load` function runs. This chapter is about *when it runs again* and *when its result arrives*. Both questions are about time. Invalidation decides which parts of a page’s data are recomputed after something changes: a URL, a parameter, a mutation, a button press. Streaming decides whether the user waits for slow data or sees the page first and the data later. Together they determine whether a SvelteKit application feels instantaneous or sluggish, and whether it stays correct while it feels fast. We cover the dependency-tracking model in detail (including the places where it deliberately does not track), the manual invalidation APIs, why server loads never track fetched URLs, how streaming works end to end and where it fails (status codes, headers, buffering platforms, SEO, errors), preloading with `preloadData` and `preloadCode`, the experimental fork-based preloading, and strategies for optimistic and stale data at the load layer. It assumes the lifecycle from Chapter 2 (especially the `__data.json` protocol with its invalidation bitmask) and the load fundamentals of Chapter 4.

## The dependency model

SvelteKit decides whether to rerun a load by comparing what the load **used** last time with what has **changed**. Usage is recorded while the load function executes, through proxies and callbacks on the event. For each node the framework keeps a `uses` record:

```ts
interface Uses {
    dependencies: Set<string>;   // URLs and custom identifiers (fetch / depends)
    params: Set<string>;         // param names read
    parent: boolean;             // parent() was called
    route: boolean;              // route.* was read
    url: boolean;                // a tracked URL property was read
    search_params: Set<string>;  // searchParams.get/getAll/has keys
}
```

You saw it in Chapter 2’s data response as `"uses":{"params":["id"]}`. Server loads record `uses` on the server and send it to the client alongside their data (so the client can later decide whether to ask the server again); universal loads record theirs in the browser. On every navigation or invalidation, the client walks the node chain and, for each node, asks: is this node’s loader different (a different route), or does any recorded dependency show a change? The rules, taken from the client router’s `has_changed` function:

1.  A forced invalidation (`refreshAll`, `invalidateAll`, or `goto` with `refreshAll: true`) reruns everything.
2.  `uses.parent` is true and a parent node was rerun (or its data changed).
3.  `uses.route` is true and the route ID changed.
4.  `uses.url` is true and the URL key changed (pathname plus search string).
5.  Any key in `uses.search_params` changed value (compared as sorted lists of values, so reordering `?tag=a&tag=b` is not a change).
6.  Any name in `uses.params` has a different value than the current page.
7.  Any entry in `uses.dependencies` matches a pending invalidation predicate.

A node that passes none of these is **valid** and its previous result is reused. For server nodes, “valid” means a `0` in the `x-sveltekit-invalidated` bitmask and a `{"type":"skip"}` in the response. If all server nodes are valid, no request is made at all.

### What is tracked

Reading any of the following in the body of the load (synchronously, or after awaiting while the function has not yet returned) records a dependency:

| You read | Recorded as |
|------------------------------------|------------------------------------|
| `params.slug` | that param name only |
| `url.pathname`, `url.search`, `url.href`, `String(url)`, `url.toJSON()` | `url` (whole-URL change) |
| `url.searchParams.get('q')`, `.getAll('q')`, `.has('q')` | search param `q` only |
| `url.searchParams` iteration, `.entries()`, `.keys()`, `.toString()`, spreading | `url` (the whole URL) |
| `route.id` | `route` |
| `await parent()` | `parent` |
| `fetch(url)` (universal load only) | that URL as a dependency |
| `depends('app:foo')` | that identifier |
| `url.origin`, `url.hostname`, `url.port`, `url.protocol` | nothing (cannot change during a session) |
| `event.request.url` (server) | nothing |

The search parameter rule is subtle and valuable. A product list that reads only `searchParams.get('category')` does not refetch when the user changes `?view=grid` to `?view=list`; the load is valid and the server is not asked. Conversely, one careless `Object.fromEntries(url.searchParams)` makes the load depend on the whole query string:

```ts
// Reruns for ANY query-string change
const filters = Object.fromEntries(url.searchParams);

// Reruns only when `category` or `sort` change
const filters = {
    category: url.searchParams.get('category'),
    sort: url.searchParams.get('sort') ?? 'new'
};
```

### What is *not* tracked: after the load returns

Dependency tracking only covers reads that happen **before the load function returns**. Anything accessed later, for example inside a promise that is being streamed, is untracked, because the dependency set was already finalised and sent. In development, SvelteKit warns when it detects a read after the function returned (`Accessing params.x ... after the function returned will not cause the function to re-run when the param changes`). The implementation compares a `done` flag set when the load returned. The fix is to read what you need at the top:

```ts
// Bug: `params.id` is read inside the streamed promise, after return
export const load = ({ params }) => ({
    comments: fetchComments(() => params.id)       // reads later: untracked
});

// Correct: read in the main body
export const load = ({ params }) => {
    const id = params.id;                           // tracked
    return { comments: fetchComments(id) };
};
```

### Why a server load’s `fetch` is not tracked

In a universal load, calling `fetch('/api/items')` registers `/api/items` as a dependency, so `invalidate('/api/items')` reruns the load. In a **server** load, `event.fetch` deliberately registers nothing. The documentation states the reason: server loads never automatically depend on a fetched URL “to avoid leaking secrets to the client”. The dependency set is sent to the browser (the `uses` object you saw in the data response), and a fetched URL on the server may contain credentials, API keys in query strings, or the topology of an internal network. The consequence is practical:

```ts
// src/routes/dashboard/+page.server.ts
export const load = async ({ fetch, depends }) => {
    // `invalidate('https://internal.api/stats')` will NOT rerun this load.
    const stats = await (await fetch('https://internal.api/stats?token=…')).json();

    // Declare an opaque, public identifier instead:
    depends('app:dashboard-stats');
    return { stats };
};
```

Then a button calls `invalidate('app:dashboard-stats')`. In a server load, the same `depends` rule applies in the other direction: identifiers you declare are sent to the browser, so use opaque names, not URLs with secrets. (In older versions an opt-in `dangerZone.trackServerFetches` existed; it was removed in SvelteKit 2.)

### `depends`: custom identifiers

`depends(...ids)` takes URLs or custom identifiers. The identifier is resolved as a URL against the current URL, so a custom identifier must be a valid scheme-prefixed string, as the docs put it, “a string beginning with `[a-z]+:`” such as `app:cart` or `data:posts`. Some schemes are rejected or warned about (`moz-icon:`, `view-source:`, `jar:`) since they have browser-special meaning. In a universal load running on the server, `depends` is a no-op (the server render does not need it; the client’s hydration rerun records it).

The convention that scales is a small, central vocabulary:

```ts
// src/lib/keys.ts
export const keys = {
    cart: 'app:cart',
    notifications: 'app:notifications',
    post: (id: string) => `app:post:${id}`
} as const;
```

```ts
// src/routes/+layout.server.ts
import { keys } from '#lib/keys.js';
export const load = async ({ locals, depends }) => {
    depends(keys.cart);
    return { cart: await getCart(locals.user?.id) };
};
```

```html
<script lang="ts">
    import { invalidate } from '$app/navigation';
    import { keys } from '#lib/keys.js';
    async function addToCart(id: string) {
        await fetch('/api/cart', { method: 'POST', body: JSON.stringify({ id }) });
        await invalidate(keys.cart);       // reruns only loads that depend on it
    }
</script>
```

### `untrack`

`untrack(fn)` runs `fn` and discards any tracking caused inside it, then restores tracking. Use it when you need a value for a decision but a change to it must not trigger a rerun:

```ts
export const load = async ({ untrack, url, fetch }) => {
    // Don't rerun when only the pathname changes
    if (untrack(() => url.pathname === '/')) {
        return { message: 'Welcome!' };
    }
    // ...
};
```

Remember that `untrack` returns the callback’s value, and that it only suppresses *recording*; the read itself still happens, so the load may use stale information on the next reuse. In universal loads running on the server, `untrack` simply calls the function.

## Manual invalidation APIs

All live in `$app/navigation` and run in the browser.

### `invalidate`

```ts
invalidate(resource: string | URL | ((url: URL) => boolean), keepState?: boolean): Promise<void>
```

- A string or `URL` is resolved against `location.href` and matched by exact `href` against each recorded dependency: it must be the same URL (including query string) that was passed to `fetch` or `depends`. A custom identifier matches itself.
- A function receives each dependency URL and returns whether it matches, enabling patterns:

```ts
invalidate((url) => url.pathname === '/api/posts');        // any query string
invalidate((url) => url.href.startsWith('app:post:'));     // family of identifiers
```

- The returned promise resolves when the page has been updated with the new data.
- `keepState` (default false) controls whether `page.state` (shallow-routing state, Chapter 12) is preserved; `invalidate` by default resets it.

Multiple synchronous `invalidate` calls are **batched**: the first call chains onto a pending promise and subsequent calls in the same tick add predicates, so one pass reruns everything affected rather than one pass per call. Calls made while a pass is running are not swallowed: a later invalidation supersedes an earlier one in flight (“subsequent invalidations may make earlier ones outdated”), and a navigation that completes while an invalidation was loading wins, discarding the now-outdated invalidation result. Since 3.0, an invalidation that starts during a navigation no longer aborts the navigation.

### `refreshAll` (and the deprecated `invalidateAll`)

`refreshAll()` reruns every `load` function belonging to the current page, **and** refreshes all active remote function queries (Chapters 7 and 8), including reconnecting live queries. It preserves `page.state`. `invalidateAll()` does the same for loads but resets `page.state`, and is deprecated in favour of `refreshAll`. Note also that clicking a link to the page you are already on triggers `refreshAll`, which is a useful property: “click the nav item to refresh”.

`goto` accepts the same intent: `goto(url, { refreshAll: true })` forces every load to rerun during that navigation (used internally after redirected form submissions), and `goto(url, { invalidate: [...] })` marks specific dependencies invalid for that navigation only. With `refreshAll: true`, cached queries are reset up front so that newly rendered components do not read stale values, and restarted once the navigation has committed.

### Choosing the right granularity

| Need | Tool |
|------------------------------------|------------------------------------|
| The URL changed | Nothing: params/url/searchParams tracking handles it |
| A mutation affects one dataset | `depends(key)` + `invalidate(key)` |
| A mutation affects a family of datasets | predicate form of `invalidate` |
| “Refresh everything on this page” | `refreshAll()` |
| A form action succeeded | Automatic (Chapter 6): actions invalidate all loads by default |
| Remote form/command | Chapters 7 and 8: default invalidation or explicit `refresh()` |

Over-invalidating is a performance bug, not a correctness bug, and a safe starting default. Under-invalidating is a correctness bug. Prefer the narrowest key whose *names* you control, and keep the vocabulary in one module as shown above.

### A subtle interaction: what “rerun” does to components

A rerun produces a new `data` object, and Svelte updates the `data` prop of the existing component; **the component is not recreated**. Local `$state` survives, so a form half-filled in the page remains. Conversely, state derived from the initial data does not reset (Chapter 4’s `$state(data.posts)` bug). Intentional resets use `{#key}` or an `afterNavigate` callback.

Also note the data flow of a rerun for server loads: the client sends a `__data.json` request carrying an invalidation bitmask in which only the nodes with changed dependencies are `1`. The response carries `skip` for the others. This means a `depends`-based invalidation of one layout’s data costs one small request, not a full reload of the route.

## Streaming

### The basic pattern

In a **server** load, return promises without awaiting them; SvelteKit streams their resolutions:

```ts
// src/routes/blog/[slug]/+page.server.ts
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => ({
    // start immediately; do not await
    comments: loadComments(params.slug),
    // await the essential data last, so comments can start in parallel
    post: await loadPost(params.slug)
});
```

```html
<!-- src/routes/blog/[slug]/+page.svelte -->
<script lang="ts">
    import type { PageProps } from './$types';
    let { data }: PageProps = $props();
</script>

<h1>{data.post.title}</h1>
{@html data.post.html}

{#await data.comments}
    <p>Loading comments…</p>
{:then comments}
    {#each comments as c}<p>{c.content}</p>{/each}
{:catch error}
    <p>Could not load comments: {error.message}</p>
{/await}
```

Only the **top level** of the returned object is awaited if you `await` it; in SvelteKit 2 and 3, a promise value is no longer auto-awaited at the top level (SvelteKit 1 did that and only streamed nested promises). Nested promises are also streamed: the serializer walks the returned structure and replaces any thenable, at any depth, with a placeholder. With `async` Svelte enabled you can alternatively `await data.comments` directly in markup under a boundary; the `{#await}` block is the framework-neutral form.

### What the wire looks like

Chapter 2 showed both forms. Document request: the HTML is sent first with `defer(1)` placeholders in the inline payload, and when each promise settles, a `<script>__sveltekit_x.resolve(1, () => [...])</script>` chunk is appended after `</html>`. Data request (client navigation): NDJSON, with the first line carrying the `Promise` placeholder and later `{"type":"chunk","id":1,"data":[...]}` lines. The response content type for the streamed variant is `text/sveltekit-data`, and `cache-control: private, no-store`, specifically to evade intermediaries that buffer `application/json`.

The client side mirrors this: when the data response arrives, the first line resolves the navigation (so the page can render), and a background loop keeps reading the stream, resolving each deferred promise when its chunk appears.

Two practical consequences. First, **streaming only works with JavaScript enabled**, because chunk scripts call into the client runtime. Without JS the HTML contains only the loading branch of `{#await}`. Second, streamed pages carry no `ETag` and no `Content-Length`, so conditional requests do not apply.

### Unhandled rejections

SvelteKit attaches a handler to promises *it creates* (for example promises from the load `fetch`), and to the load results, but not to arbitrary promises you return. A promise that rejects **before** the renderer reaches it and has no handler triggers Node’s unhandled-rejection behaviour, which crashes the process by default. The documented remedy is a no-op `catch` on the promise you return (the original promise is what is serialised; `.catch(noop)` returns a new one):

```ts
export const load = ({ fetch }) => {
    const ok_manual = Promise.reject(new Error('later'));
    ok_manual.catch(() => {});             // marks it handled; still streamed as a rejection

    return {
        ok_manual,
        ok_fetch: fetch('/might/fail'),    // the wrapped fetch handles this for you
        dangerous: Promise.reject()         // BAD: can crash the process
    };
};
```

A cleaner approach is a tiny helper in your code base:

```ts
// src/lib/server/defer.ts
export function defer<T>(p: Promise<T>): Promise<T> {
    p.catch(() => {});   // handled for Node; the consumer still sees the rejection
    return p;
}
```

When a streamed promise rejects, the rejection value passes through `handleError`, so what the browser sees is the sanitised `App.Error`, not your raw exception. In the page it surfaces in the `:catch` branch of `{#await}`. If serialising the **resolved value** fails (a `Date` is fine, a class instance is not), the framework converts that into a rejection with an explanatory error rather than breaking the stream.

### Limits

Once the first byte has been sent, the status code and headers are fixed. This has direct consequences for what you may do in a streamed promise:

| Action inside a streamed promise | Result |
|------------------------------------|------------------------------------|
| `redirect(307, ...)` | Cannot redirect: the response already started. It becomes a rejection. |
| `error(404)` | Does not change the HTTP status (already 200); arrives as a rejection |
| `setHeaders(...)` | Too late; throws or no-ops |
| `cookies.set(...)` | Too late; the `Set-Cookie` header is already sent (and framework code throws after the response) |
| Read `params`, `url` | Untracked (see above) |

Therefore: decide on redirects, authentication and status codes in the **awaited** part of the load and stream only decoration: comments, recommendations, secondary panels.

Rendering order affects when the *response itself* begins. SvelteKit awaits the load results (top-level) before it starts rendering; since the streamed promises are not awaited, rendering begins as soon as the awaited parts are done. SSR of `{#await}` blocks renders the pending branch on the server; the resolved branch is rendered in the browser when the chunk arrives (the server does not wait for the promise to render the `:then` HTML).

### Universal loads do not stream

Promises returned from a universal `load` are not serialised. During SSR the promise exists on the server and is *recreated* when the load reruns in the browser on hydration, so the work is done twice and the server HTML contains only the pending branch. The docs advise avoiding promises in universal loads of SSR’d pages. If you need streamed data that depends on a public API, use a server load as the streaming layer, or fetch in the browser (`onMount` or a remote function).

### Platforms and proxies

Streaming requires the platform to deliver chunks as they are produced.

- **Lambda-style and some serverless platforms** buffer the response; the page then renders only after all promises resolve. Functionally correct, but without the latency benefit. The docs name AWS Lambda and Firebase explicitly.
- **Reverse proxies** (NGINX, some CDNs, corporate proxies) may buffer. For NGINX, disable `proxy_buffering` for the app or send `X-Accel-Buffering: no`. The `text/sveltekit-data` type for data requests exists to defeat content-type-based buffering and compression heuristics.
- **Compression** layers (gzip) can delay small chunks. `adapter-node` precompresses static assets, but dynamic compression is up to you: if you add middleware, use one that flushes (`@polka/compression` is the documented suggestion).
- **Edge caches** may cache the HTML of a streamed page and replay it whole. If the streamed parts are personalised, mark the page `private`.
- **Timeouts** apply to the whole response. A stream that stays open for 30 seconds can hit serverless limits or idle timeouts; adapter-node has `IDLE_TIMEOUT`, `KEEP_ALIVE_TIMEOUT` and `HEADERS_TIMEOUT` settings.

### Streaming, skeletons and SEO

Search engines render JavaScript, but the first-pass HTML is what is reliably indexed. If content matters for ranking (article body, product details), **await it**; stream only secondary content (comments, related items). Streamed content is not in the initial HTML at all when it arrives via a chunk script, and a crawler that does not execute the script never sees it. Conversely, for authenticated app screens SEO is irrelevant and streaming slow widgets is a clear win.

A decision rule that works in practice:

- **Block** (await) when the page is meaningless without the data, the data is fast (under roughly 100 ms at your percentile target), the content is SEO-critical, or a failure should be an error page (404, 403).
- **Stream** when the data is slow or highly variable, secondary to the main task, and acceptable to render later, with a skeleton that matches the final layout to avoid layout shift.

Also consider navigations. On a client navigation the router waits for the **first** chunk of the data response, which is available as soon as awaited parts are done; the streamed parts arrive later. So a streamed navigation feels as fast as the awaited part, and the skeleton is visible while the rest loads. Blocking everything makes every navigation as slow as the slowest query. That is the strongest practical argument for streaming even internal pages.

### Designing the loading UI

`navigating` from `$app/state` tells you a navigation is in flight (Chapter 12), which is where you place a global progress bar. For streamed promises use `{#await}` skeletons. For the failure path, give each streamed region its own `:catch` so a failing recommendations call does not blank the page, and make errors retryable with a call to `invalidate(key)` on a `depends` identifier owned by that region (note: a retry through `invalidate` reruns the whole server load, including the parts already shown; for fine-grained retry, a remote function query is the better tool).

## Preloading

SvelteKit can do the work of a navigation before the click.

### Link options

`data-sveltekit-preload-data` takes `"hover"` (start when the pointer rests over a link; on touch, at `touchstart`) or `"tap"` (start on `mousedown`/`touchstart`) or `false`. `data-sveltekit-preload-code` takes `"eager"`, `"viewport"`, `"hover"`, `"tap"` or `false`, in decreasing eagerness, and applies only when more eager than any preload-data setting. The scaffold’s `app.html` sets `data-sveltekit-preload-data="hover"` on `<body>`. Notes:

- Attributes apply to the link or any ancestor, and also to `<form method="GET">`. Use `"false"` to disable inside an enabled region; `data-sveltekit-preload-data={condition ? 'hover' : false}` for conditional use. (`"off"` was removed in 3.0.)
- `viewport` and `eager` apply only to links in the DOM right after navigation; links rendered later wait for hover or tap.
- Nothing is preloaded when `navigator.connection.saveData` is true.
- Preloading **data** runs load functions, which means it can have side effects and costs. Do not use `hover` on links to routes whose server load is expensive or non-idempotent (for example a “mark as read” implemented in `load`, which is a design smell anyway). Use `tap` for rapidly changing data where a hover-time response would be stale.

### The preload cache

The router keeps at most one preloaded route result (`load_cache`) keyed by the page’s key (pathname plus search). When a click arrives for the same key, the in-flight or completed promise **becomes the navigation**: no second load. The cache is discarded when:

- an invalidation starts (`invalidate`, `refreshAll`), since the result may be affected;
- another route is preloaded;
- a navigation to a different route commits;
- `goto` is called with `refreshAll: true`.

Preloading hence cannot serve stale data across an invalidation, but it also means that hovering over several links quickly causes several server load executions (each replaces the previous) and that the *effective* TTL of a preload is until the next interaction.

If a preload fails with an error, that error is thrown to the preloader (not rendered), and the cache is discarded; the real navigation will try again.

### `preloadData`

```ts
preloadData(href: string): Promise<
    | { type: 'loaded'; status: number; data: Record<string, any> }
    | { type: 'redirect'; status: number; location: string }
    | { type: 'error'; status: number; error: App.Error }
>
```

It performs the same work as a hover preload: imports the route’s code and runs its loads, and if the next navigation goes to that `href`, the result is used. It resolves with the outcome as a tagged union:

```ts
import { preloadData, goto } from '$app/navigation';

async function openPreview(href: string) {
    const result = await preloadData(href);

    if (result.type === 'loaded' && result.status === 200) {
        // e.g. use result.data to render a shallow-routed modal
        return result.data;
    }
    if (result.type === 'redirect') {
        await goto(result.location);
    }
    // result.type === 'error': decide whether to show message or navigate anyway
}
```

Details: the `href` must belong to the app (an external or unmatched URL throws a “preload outside app” error); the promise **resolves** (does not reject) for load errors, returning `{ type: 'error', status, error }` with the handled `App.Error`; `status` reflects the page status; and the `data` is the merged page data of that route. This shape is exactly what a “peek” interaction needs: render a modal with the target page’s data using `goto(href, { shallow: true, state })` (Chapter 12), while the full navigation remains one click away.

### `preloadCode`

```ts
preloadCode(routeId: RouteId): Promise<void>
```

Imports the code for a route but runs no loads. **It takes a route ID** (such as `/blog/[slug]`), not a pathname, since 3.0. Route IDs are never prefixed with `paths.base`. If you hold a pathname, convert it with `match`:

```ts
import { match } from '$app/paths';
import { preloadCode } from '$app/navigation';

const m = await match('/blog/hello-world');
if (m) await preloadCode(m.id);
```

A pathname passed by mistake produces a development warning that it looks like a pathname. An unknown ID warns; an ID of an endpoint-only route warns that there is nothing to preload. With `router.resolution: 'server'`, `preloadCode` fetches `/_app/routes/<id>/__route.js` (Chapter 3), which is prerendered where possible.

Use `preloadCode` for predictable next steps that do not need data yet, such as the checkout route after adding to cart, and `preloadData` when the data is also certain to be needed. Avoid scattering these calls; prefer link options for ordinary navigation.

## `forkPreloads` (experimental)

Plain preloading has a gap: the code and data are ready, but rendering the new page still happens at click time. If the page’s components use `await` expressions (async Svelte), that work starts only when the page is mounted, which reintroduces a waiting period after the click. Svelte 5.42 added `fork(fn)`, an API for frameworks to run `await` expressions that are *expected* to happen soon. SvelteKit uses it behind a flag:

```ts
// vite.config.ts
sveltekit({
    experimental: { forkPreloads: true },
    compilerOptions: { experimental: { async: true } }
})
```

With the option on, when a preload resolves with `type: 'loaded'`, the router calls `fork(() => apply_navigation_result(result))`: the new page’s props are applied inside a Svelte fork, so component trees and their `await` expressions start executing speculatively, off-screen. On the real navigation, the router awaits the fork and calls `fork.commit()` instead of applying the result normally, so async work is already in flight or done. If the user goes elsewhere, the fork is discarded.

How it interacts with the rest of the system, from the source:

- A fork is attached to the cached preload (`load_cache.fork`). It is created only when the preload completes with a loaded result, and discarded when the cache is discarded, when the preload is for a different route than the navigation, or when the preload is replaced. The code explicitly avoids “orphan forks” and reuse of forks from unrelated routes (these were fixed in several patch releases).
- If Svelte’s async mode is not enabled, `fork` throws, and SvelteKit swallows the error and falls back to normal navigation, so enabling the Kit flag alone is harmless but useless.
- On commit, previously failed `<svelte:boundary>` instances (`+error.svelte`) are reset immediately since the commit applies state synchronously.
- Speculative rendering means component script blocks, `$effect`-free async work and `await` expressions can run for pages the user never visits. Anything with side effects in a component’s top-level script or in its awaited remote functions will therefore run speculatively. Keep such components free of write-like effects, and treat this as a reason to keep the flag off for pages whose rendering triggers expensive queries.

Treat `forkPreloads` as an optimisation for async-Svelte apps with heavy `await` in components; it is experimental, defaults to `false`, and Svelte’s own docs note that async APIs may change outside a major version.

## Optimistic and stale data at the load layer

Loads return snapshots; mutations change the truth. Between the two there are three honest strategies.

### 1. Invalidate and refetch (consistent, slower)

The default: mutate, then `invalidate(key)` or let a form action trigger reruns, and render fresh data. Correct, simple, but the UI waits one round trip.

### 2. Optimistic local state over loaded data

Display the expected result immediately and reconcile when the load reruns. At the load layer this means holding a local overlay and clearing it once fresh data arrives:

```html
<script lang="ts">
    import { invalidate } from '$app/navigation';
    import type { PageProps } from './$types';

    let { data }: PageProps = $props();

    // ids toggled optimistically but not yet confirmed
    let pending = $state(new Map<string, boolean>());

    let todos = $derived(
        data.todos.map((t) => (pending.has(t.id) ? { ...t, done: pending.get(t.id)! } : t))
    );

    async function toggle(id: string, done: boolean) {
        pending.set(id, done);                        // optimistic
        try {
            const res = await fetch(`/api/todos/${id}`, {
                method: 'PATCH',
                headers: { 'content-type': 'application/json' },
                body: JSON.stringify({ done })
            });
            if (!res.ok) throw new Error(String(res.status));
            await invalidate('app:todos');             // fresh truth replaces the overlay
        } finally {
            pending.delete(id);                         // roll back on failure, clear on success
        }
    }
</script>
```

Properties of this pattern: the overlay is a pure function of `data` plus pending intents, so if the load reruns for any reason (navigation, `refreshAll`) the UI stays coherent; rollback is deleting the intent; and no mutation of `data` is needed (it is replaced, not mutated). For richer cases (ordering, conflict handling), the overlay can be a queue of operations reduced over `data`.

Remote functions give this a first-class form (`query.withOverride`, Chapter 8), which also handles releasing the override when the refreshed value arrives; the above is the manual equivalent for plain loads.

### 3. Serve stale data deliberately

Sometimes stale is the right answer for performance: a dashboard that can be a minute old, an expensive aggregate. Options at the load layer:

- **HTTP caching of the HTML** via `setHeaders` (for non-personalised pages), letting the CDN serve stale while revalidating (`cache-control: s-maxage=60, stale-while-revalidate=300`). Remember data requests are never cached.
- **Server-side memoisation** inside the load (a TTL cache in your data layer) so repeated navigations are cheap while every user still gets a consistent shape. Keyed per user or per tenant; never a module-level cache of personalised data without a key.
- **Client reuse through the fetch TTL**: universal loads whose responses carry `max-age` are replayed from the in-memory cache across navigations (Chapter 4).
- **Skipping reruns** with narrow dependency tracking or `untrack`, so data survives navigations by design (a layout’s user and settings).
- **Stale-while-revalidate in the UI** by rendering the existing `data` while a background `invalidate` runs; `invalidate` resolves when updated, and the old `data` remains in place until then. Track in-flight state yourself:

```html
<script lang="ts">
    import { invalidate } from '$app/navigation';
    let refreshing = $state(false);

    async function refresh() {
        refreshing = true;
        try { await invalidate('app:stats'); } finally { refreshing = false; }
    }

    $effect(() => {
        const id = setInterval(refresh, 30_000);
        return () => clearInterval(id);
    });
</script>

<p class:stale={refreshing}>…</p>
```

Be careful with polling through `invalidate`: it reruns the whole server load for every dependent node and hits your server every interval for every open tab. For frequently changing data, a live remote function (`query.live`, Chapter 7) or a dedicated endpoint with SSE is cheaper.

## A worked example: filters, streaming, and invalidation together

A product listing with filters in the URL, a slow “recommendations” panel, and a cart in the layout:

```ts
// src/routes/+layout.server.ts
import { keys } from '#lib/keys.js';
export const load = async ({ locals, depends }) => {
    depends(keys.cart);                       // only cart mutations rerun this
    return { cart: await getCart(locals.user?.id) };
};
```

```ts
// src/routes/shop/+page.server.ts
import { error } from '@sveltejs/kit';
import { defer } from '#lib/server/defer.js';

export const load = async ({ url, locals }) => {
    // Read ONLY the keys we use: view=grid|list does not rerun the load
    const category = url.searchParams.get('category');
    const sort = url.searchParams.get('sort') ?? 'new';
    const page = Math.max(1, Number(url.searchParams.get('page') ?? '1') || 1);

    const recommendations = defer(getRecommendations(locals.user?.id, category)); // streamed

    const result = await searchProducts({ category, sort, page });                  // awaited
    if (page > 1 && result.items.length === 0) error(404, 'No such page');          // status decided before streaming

    return { ...result, recommendations };
};
```

```html
<!-- src/routes/shop/+page.svelte -->
<script lang="ts">
    import { page } from '$app/state';
    import type { PageProps } from './$types';
    let { data }: PageProps = $props();
    let view = $derived(page.url.searchParams.get('view') ?? 'grid');   // read in the component, not the load
</script>

<section class={view}>
    {#each data.items as p (p.id)}<ProductCard {p} />{/each}
</section>

{#await data.recommendations}
    <RecommendationsSkeleton />
{:then recs}
    <Recommendations {recs} />
{:catch}
    <p>Recommendations are unavailable.</p>
{/await}
```

Reading each design choice against this chapter: the cart is `depends`-scoped so adding to it does not reload products; the listing reads individual search params so `?view=` is free; recommendations are streamed behind `defer` so a rejection cannot crash the process and the skeleton shows while the main query is awaited; and the 404 decision is made in the awaited section, where status can still change. Hovering links to other categories (`data-sveltekit-preload-data="hover"`) preloads this load for each; the `view` toggle, being derived in the component from `page.url`, does nothing at the network layer at all.

## Diagnosing reruns

When a load reruns more (or less) than you expect:

1.  In the Network tab, inspect `__data.json` requests: the `x-sveltekit-invalidated` value shows which nodes the client believed invalid, and the response’s `skip` entries show the unchanged ones.
2.  Log `url`/`params` reads: remember that spreading `searchParams`, calling `toString()` or reading `href` invalidates by whole URL.
3.  Look for `await parent()` calls: a rerun of any ancestor reruns the child.
4.  Check the dev console for warnings about reads after the load returned.
5.  Remember that a link to the current URL triggers `refreshAll`, and that form actions rerun all loads by default.
6.  For server loads, the `uses` field in the response is the exact record the client will use; `"uses":{}` means “valid forever until invalidated by a forced refresh”.

## Key takeaways

- Each load records `uses`: params, URL, per-key search params, route, `parent`, and dependency URLs or identifiers. A load reruns when a used item changes, a parent it awaited reran, a matching dependency was invalidated, or a refresh was forced. Unchanged nodes are skipped (`skip` in the data response); with no invalid server nodes, no request is made.
- Search params are tracked per key via `get`, `getAll` and `has`; iterating or stringifying them tracks the whole URL. `origin`, `hostname` and `request.url` are not tracked.
- Only reads before the load returns are tracked; reads inside streamed promises are not (development warning). Read what you need at the top.
- Server loads never register fetched URLs as dependencies because dependency sets are sent to the browser; use `depends` with opaque identifiers (`app:cart`) instead. `untrack` suppresses recording.
- `invalidate` matches exact URLs/identifiers or a predicate; calls in one tick are batched; `refreshAll` reruns all loads and queries and keeps `page.state` (`invalidateAll` is deprecated and resets it). A load rerun updates the component’s `data`; it does not recreate the component.
- Streaming applies to server loads only: return promises un-awaited, add a no-op `catch` (or helper) to avoid process-level unhandled rejections, and await essential data last. Status codes, headers, cookies and redirects cannot change after streaming starts; decide them before.
- Streaming requires JavaScript, produces no `ETag`, and is buffered by Lambda-style platforms and some proxies. Await SEO-critical content; stream secondary content with skeletons. Client navigations benefit most, since the page renders on the first chunk.
- Universal-load promises are not streamed; they are recreated in the browser.
- Preloading: `data-sveltekit-preload-data` (`hover`/`tap`/`false`) and `-code` (`eager`/`viewport`/`hover`/`tap`); a preload becomes the real navigation if the click targets the same key; invalidations and other preloads discard it. `preloadData(href)` returns `{type: 'loaded' | 'redirect' | 'error', status, ...}`; `preloadCode` takes a route ID.
- `experimental.forkPreloads` (needs Svelte’s async mode) speculatively applies preloaded results inside a Svelte fork so awaited component work starts before the click; it can run component logic for pages the user never visits.
- At the load layer, choose between invalidate-and-refetch, an optimistic overlay derived from `data`, and deliberate staleness (HTTP caching, memoisation, fetch TTL, narrow tracking). Avoid polling with `invalidate`; prefer live queries or SSE.

## Review Questions

1.  List the seven conditions (including forced refresh) under which the client considers a load node invalid. Which of them apply to server loads, and where is that information stored?

2.  A load reads `url.searchParams.get('category')` only. Does it rerun when the URL changes from `/shop?category=a&view=grid` to `/shop?category=a&view=list`? What about `/shop?category=a&sort=x` to `/shop?sort=x&category=a`?

3.  **What does this do?** `const filters = Object.fromEntries(url.searchParams);` in a load, versus two `get` calls. Explain the dependency difference and its cost.

4.  **Find the bug.** `export const load = ({ params }) => ({ comments: new Promise((r) => setTimeout(() => r(fetchFor(params.id)), 10)) });` The page doesn’t update comments when navigating `/p/1` to `/p/2` (same route). Why, and what is the fix?

5.  Why does a server load not register fetched URLs as dependencies, and what is the alternative? Give an example of `depends` identifiers that would be a mistake to use.

6.  A server load calls `fetch('https://api.internal/stats')`. A developer calls `invalidate('https://api.internal/stats')` after a mutation and nothing happens. Explain and fix.

7.  Which of these are valid custom identifiers for `depends`: `app:cart`, `cart`, `data:posts:42`, `view-source:x`? Why?

8.  Write an `invalidate` call using the function form that reruns every load that depends on any URL starting with `/api/posts`, regardless of query string.

9.  What are the differences between `invalidate(key)`, `refreshAll()` and `invalidateAll()` with respect to scope, remote queries and `page.state`?

10. Three `invalidate` calls are made synchronously in one click handler. How many load passes happen, and why?

11. An invalidation is running when the user clicks a link and the navigation finishes first. What happens to the invalidation’s result?

12. **Multiple choice.** A rerun caused by `invalidate` results in:

    a.  The page component being destroyed and recreated
    b.  The `data` prop being updated; component state is preserved
    c.  A full page reload
    d.  Only the layout being re-rendered

13. What does `x-sveltekit-invalidated=101` mean, and what comes back for the middle node?

14. Explain why returning `{ comments: loadComments(), post: await loadPost() }` is better than the reverse order.

15. What will happen if a streamed promise rejects before the renderer attaches a handler and nobody called `.catch` on it? What does the helper `defer` in this chapter do, and does the browser still see the rejection?

16. **Design question.** List four things you cannot do inside a streamed promise, and say where the corresponding logic must move.

17. Why does streaming not work for promises returned from a universal load on an SSR page? What happens instead?

18. A page uses `{#await data.comments}` and a user has JavaScript disabled. What do they see? What if the comments are SEO-critical?

19. Name three places in the delivery chain that can buffer a streamed response and one mitigation for each.

20. Why do streamed responses lack `ETag` and `Content-Length`? What content type is used for streamed data requests and why?

21. **Design question.** Give a decision rule for block vs stream and apply it to: product description, price, reviews, related products, logged-in user’s cart count.

22. Compare `data-sveltekit-preload-data="hover"` and `"tap"`. When is each appropriate? Why is `hover` a poor choice for a route whose server load has side effects?

23. When is a preloaded result discarded? What happens if the user clicks the link while the preload is still in flight?

24. **What does this return?** `await preloadData('/missing')` where no route matches inside the app’s base but the URL is internal; and `await preloadData('/protected')` where the load calls `redirect(307, '/login')`.

25. What argument does `preloadCode` take in 3.x, and how do you get it from a pathname? What does a pathname-looking argument produce?

26. Explain how `forkPreloads` shortens the time between click and visible page, what two flags are needed, and what failure mode appears if only one is set. Name a risk of speculative rendering.

27. Implement (in outline) an optimistic toggle over loaded data without mutating `data`. Why is deriving the displayed list from `data` plus an overlay robust against reruns?

28. **Design question.** A dashboard needs data refreshed every 10 seconds for 500 concurrent users. Critique polling with `invalidate` and propose an alternative using the tools of this book.
