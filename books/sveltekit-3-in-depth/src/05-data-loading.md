# Chapter 4: Data Loading

`load` functions are where a SvelteKit route turns a URL into data. They are the most heavily used API in the framework and the one with the most hidden machinery: two flavours (universal and server) with different serialisation rules, an event object whose properties double as dependency-tracking probes, a `fetch` that is not the platform `fetch`, a parent/child data model that can silently serialise your requests, and a pipeline that must work identically for a first server render, a hydration, and a client-side navigation. This chapter covers the data model and the event object, the merge rules, `fetch` semantics, `parent()` and waterfalls, headers and cookies, how page data reaches components, and how errors and redirects behave. The mechanics of rerunning loads (invalidation) and streaming are developed in Chapter 5, and the request lifecycle in Chapter 2 is assumed throughout.

Where this chapter shows a request or an HTML fragment, it was captured from a SvelteKit 3.1.0 build.

## Two kinds of `load`

A route’s chain consists of nodes: each layout and the page. Each node can have a **universal** `load` in `+layout.ts`/`+page.ts` and a **server** `load` in `+layout.server.ts`/`+page.server.ts`. In a given node both may exist.

|  | Universal (`+page.ts`) | Server (`+page.server.ts`) |
|------------------------|------------------------|------------------------|
| Runs | Server during SSR, then browser on hydration and navigation (browser only if `ssr = false`) | Server only |
| Event | `LoadEvent` | `ServerLoadEvent` (adds `cookies`, `locals`, `request`, `platform`, `getClientAddress`) |
| Return value | Anything: class instances, functions, component constructors | Must be serialisable by devalue (plus your `transport` types) |
| Crosses the wire | Never as a value (the code runs in both places) | Yes: inlined in HTML, or in `__data.json` |
| Streaming promises | Not streamed (recreated in the browser) | Streamed |
| Secrets/DB | No | Yes |

When both exist for one node, the server `load` runs first and its return value is passed to the universal `load` as `event.data`. The universal result then *replaces* the server result for that node; if you want the server fields in the page you must return them:

```ts
// src/routes/+page.server.ts
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => ({
    serverMessage: 'hello from server load'
});
```

```ts
// src/routes/+page.ts
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ data }) => ({
    serverMessage: data.serverMessage,        // forward explicitly
    universalMessage: 'hello from universal load'
});
```

This pairing is for rare cases: you need a value that cannot be serialised (a class instance, a component) but constructed from server-only data. The common decision is simply:

- Need a database, filesystem, private environment variable, `cookies`, `locals`, or want to hide a third-party API’s credentials: **server**.
- Calling a public API that the browser can reach, and want client navigations to go straight to it rather than through your server: **universal**.
- Returning something that cannot cross the wire (a component constructor, a store instance): **universal**.

There is also a performance trade-off that is easy to miss. A server `load` executes on every client navigation that invalidates it, as an HTTP request to your server (`__data.json`), then your server may call the real backend. A universal `load` on the client calls the backend directly. For a public API far from your server, universal is one hop; for a private backend near your server, server `load` is one cheap hop plus a fast internal call. Chapter 2 showed that all invalidated server loads for a navigation are *batched into one request*, which is a strong argument for server loads when a page has several data dependencies.

### What crosses the wire

For server loads, the return value is serialised with `devalue`, which handles what JSON cannot: `Date`, `Map`, `Set`, `BigInt`, `RegExp`, `undefined`, `NaN`, `±Infinity`, `-0`, typed arrays, repeated references and cycles. It does not handle functions, class instances (except via `transport`), `Symbol`s or DOM objects. A failure throws a descriptive error that includes the path to the offending value, for example `data.user.avatar` is not serialisable. Server `load` must return a plain object (or nothing); returning an array, class instance or `Response` fails validation in development with a message that a `load` function returned an array but must return a plain object at the top level.

Custom types are opted in through the universal `transport` hook:

```ts
// src/hooks.ts
import type { Transport } from '@sveltejs/kit/hooks';
import { Money } from '#lib/money.js';

export const transport: Transport = {
    Money: {
        encode: (value) => value instanceof Money && [value.cents, value.currency],
        decode: ([cents, currency]) => new Money(cents, currency)
    }
};
```

The `encode` function must return a falsy value for anything that is not its type. The same transporters are used for data requests, inlined HTML data, form action results, remote functions and history `state` (Chapters 6 to 8 and 12). The mechanism uses the hydration payload you saw in Chapter 2: encoded values appear as `app.decode('Money', [...])` in the inlined JavaScript expression.

One nuance on size: server data is serialised into the HTML **and** later re-fetched as `__data.json` when invalidated. Everything you return from a server `load` is visible to the browser. Treat the return value as a public API: return the fields the page needs, not the database row.

```ts
// Bad: leaks passwordHash and internal columns to every visitor
return { user: await db.users.findById(id) };

// Good: explicit projection
const u = await db.users.findById(id);
return { user: { id: u.id, name: u.name, avatarUrl: u.avatarUrl } };
```

## The event object

Every `load` receives an event. Its members, with what they actually are:

- **`params`**: the decoded route params, typed from the route ID (and matcher output types). A `Proxy` records which keys you read.
- **`route`**: `{ id }`, the route ID such as `/blog/[slug]`. Also tracked (reading `route.id` marks the load as route-dependent).
- **`url`**: a `URL` instrumented to track reads of `href`, `pathname`, `search`, `toString`, `toJSON` and the `searchParams` methods `get`, `getAll` and `has` (per key). Other properties (`origin`, `hostname`, `port`) are not tracked because they cannot change during a client session. `url.hash` is unavailable on the server and in `load` generally, and reading it throws.
- **`fetch`**: the wrapped fetch described below.
- **`setHeaders`**: sets response headers during SSR (no effect in the browser).
- **`parent`**: returns a promise for the merged data of all ancestor nodes.
- **`depends`**: registers custom dependencies (Chapter 5).
- **`untrack`**: runs a function without recording dependency reads.
- **`tracing`**: the OpenTelemetry handles from Chapter 2 (`enabled`, `root`, `current`). On the client, `enabled` is false.
- **`data`** (universal only): the server load’s result for the same node.
- **Server only**: `cookies`, `locals`, `request`, `platform`, `getClientAddress`, plus `isDataRequest`, `isSubRequest`, `isRemoteRequest` through the `RequestEvent` inheritance.

Two notes about `url` and `request.url`. `ServerLoadEvent.request` is the raw `Request`; its `url` property is the *original* URL including `__data.json` and internal parameters for data requests, and **it is not tracked**. Reading `request.url` in a server load gives you a value but registers no dependency, so the load will not rerun when the URL changes. Always use `event.url`. And during prerendering, `url.searchParams` is disabled and reading `url.search` throws, since a prerendered page cannot depend on a query string.

### Typing: `$types`

The generated `./$types` module gives each route precise types:

```ts
// src/routes/blog/[slug]/+page.server.ts
import { error } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, fetch }) => {
    const res = await fetch(`/api/posts/${params.slug}`); // params.slug: string
    if (!res.ok) error(res.status === 404 ? 404 : 502, 'Could not load post');
    const post: { title: string; html: string } = await res.json();
    return { post };
};
```

```html
<!-- src/routes/blog/[slug]/+page.svelte -->
<script lang="ts">
    import type { PageProps } from './$types';
    let { data }: PageProps = $props(); // data.post is typed from the load above
</script>

<h1>{data.post.title}</h1>
{@html data.post.html}
```

The generated types per route include `PageServerLoad`, `PageLoad`, `LayoutServerLoad`, `LayoutLoad`, `PageData`, `LayoutData`, `PageServerData`, `PageProps`, `LayoutProps`, `ActionData`, and `RouteParams`. `PageData` is computed from the merged chain: the return types of all parent layout loads, then the page’s, using the same rules as the runtime. In an editor with the Svelte language tools you can omit the annotations: the tooling inserts them automatically and `svelte-check` verifies them. `PageData` also incorporates `App.PageData`, which is how app-wide optional fields (like a `title`) are typed at every depth.

Be aware of what types do not guarantee. If a universal `load` runs after a server `load` and you forget to forward a field, TypeScript knows: the page’s data type is the universal return type. But types say nothing about *when* the code runs, so a universal `load` that uses `window` compiles and fails during SSR. Guard with `BROWSER` from `esm-env` or `browser` from `$app/env`, or move the logic to `onMount`.

## Merging, `data`, and `page.data`

The data a component sees is the merge of every node’s result, root first, page last, with later keys winning:

```ts
// +layout.ts returns { a: 1, b: 2 }; +page.ts returns { b: 3, c: 4 }
// page receives { a: 1, b: 3, c: 4 }
```

The merge is shallow, per key. A page returning `{ user: { name: 'x' } }` replaces a layout’s `user` entirely. This is a common source of bugs when two loads own the same key; give keys unique names or namespace them (`layoutUser`, `viewer`).

A component sees its own node’s data **plus all ancestors’**, never descendants’. A layout does not receive the page’s data. When a parent genuinely needs a child’s data, for example the root layout setting `<title>` from the page’s data, use `page.data` from `$app/state`:

```html
<!-- src/routes/+layout.svelte -->
<script lang="ts">
    import { page } from '$app/state';
    let { children } = $props();
</script>

<svelte:head>
    <title>{page.data.title ?? 'My app'}</title>
</svelte:head>

{@render children()}
```

`page.data` is the full merged object for the current page, typed by `App.PageData`. Declare shared optional fields there:

```ts
// src/app.d.ts
declare global {
    namespace App {
        interface PageData {
            title?: string;
            description?: string;
        }
    }
}
export {};
```

Every route’s `PageData` is checked against it: a load returning `title: 42` fails to compile. The runtime behaviour to remember is that `page` is a reactive object, so `page.data` updates after every navigation and invalidation. During SSR, `page` may only be read while rendering (reading it in module scope on the server throws), because the server has many concurrent requests and the current page is request-scoped.

Components versus `page.data` is a design choice. Use `data` for the route’s own data (statically typed per route, can only be wrong at the data source) and `page.data` for cross-cutting UI (titles, breadcrumbs, analytics) typed loosely. Do not use `page.data` as a general global store: it changes identity with every navigation and invites coupling between unrelated layouts.

### Layout data survives navigation

Layout loads do not rerun on every navigation. When you move from `/blog/a` to `/blog/b`, a root `+layout.server.ts` load that did not read `params` or `url` is considered valid, its result is reused, and its component is not recreated; only changed nodes rerun. This is the desired behaviour and the source of the “stale layout” surprises. The rules for when a load reruns are in Chapter 5; the architectural rule is: **a layout load should only return data that depends on things the layout can see**.

## `fetch` in load

The `fetch` provided to `load` is a wrapped version of the platform `fetch`, with different guarantees on server and client.

### On the server

Chapter 2 described its construction. As a data-loading primitive, its properties are:

1.  **Relative URLs work.** `fetch('/api/items')` resolves against the current request URL (and `paths.base` is respected if the path starts with it).
2.  **Internal requests skip the network.** If the URL belongs to your app (same origin, within `paths.base`, not a static asset or prerendered path), it is dispatched in-process into `respond`: your `handle`, route matching and the target `+server` run, with `isSubRequest` true. This makes calling your own API from a load almost free, at the cost of repeating `handle` for each call. It also means a load that fetches its own page URL recurses; Kit stops at a depth of 10 and returns a 404.
3.  **Credentials are forwarded**, following the browser credentials model. For same-origin requests, `cookie` and `authorization` headers are copied from the incoming request unless `credentials: 'omit'`. For cross-origin requests, `cookie` is forwarded only if the target host is the app’s host or a subdomain of it: from `my.example.com`, `sub.my.example.com` receives cookies, `api.example.com` and `example.com` do not. `credentials: 'include'` does not widen this, because Kit cannot know which domain a cookie belongs to. For sibling subdomains, forward explicitly in `handleFetch` (Chapter 9).
4.  **`accept` and `accept-language` defaults.** An internal request without `accept` receives `*/*`, and the `accept-language` of the original request is copied. Both matter for caching and content negotiation of the target.
5.  **Cookies set by the callee are absorbed.** A `Set-Cookie` in an internal response is parsed into the request’s cookie jar, so later fetches in the same request carry it and it is emitted to the browser.
6.  **`handleFetch` can rewrite everything.** All server-side `fetch` calls run through this hook, including those from `load`, actions, endpoints, `handle` and remote functions.

For external URLs, the wrapper also *simulates CORS*: a cross-origin response without a matching `access-control-allow-origin` triggers a clear error (“CORS error: No `Access-Control-Allow-Origin` header is present on the requested resource”), because the call would fail in the browser during client-side navigation, and you want to learn that during SSR in development. `mode: 'no-cors'` yields an opaque-like empty body.

### Inlining and hydration

For a universal `load` during SSR on a page with `csr` enabled, every response read through `text()`, `json()`, `arrayBuffer()` or `body` is captured and later emitted into the HTML:

```html
<script type="application/json" data-sveltekit-fetched data-url="/api/items" data-ttl="60">
    {"status":200,"statusText":"","headers":{"content-type":"application/json"},"body":"[{\"id\":1}]"}
</script>
```

During hydration, the browser’s `fetch` wrapper looks for a script whose `data-url` equals the request (plus `data-hash` of the request headers/body, when present) and replays it with no network call, removing the element once used. If the response had `cache-control` with `max-age` or `s-maxage`, the `data-ttl` (max-age minus `age`) keeps it in a small in-memory cache so a client-side navigation back to the same data within the TTL does not refetch; a non-GET request to the same URL evicts it. `Vary: *` disables the TTL. Requests whose body is not a string or typed array are not serialised and are repeated in the browser.

What is **not** inlined: server `load` fetches (the server load’s result is what gets serialised, not its inputs); responses never read (a `fetch` whose body you don’t consume); and, by default, response **headers**. This is a security-conscious default: only headers permitted by `filterSerializedResponseHeaders` in `resolve` are included, and reading a filtered header from a universal `load` fetch response throws an error during SSR so the mismatch with hydration is caught early:

```ts
// src/hooks.server.ts
import type { Handle } from '@sveltejs/kit/hooks';

export const handle: Handle = ({ event, resolve }) =>
    resolve(event, {
        filterSerializedResponseHeaders: (name) => name === 'content-type' || name === 'etag'
    });
```

Without that filter, `response.headers.get('etag')` in a universal load throws in SSR: `Failed to get response header "etag" — it must be included by the filterSerializedResponseHeaders option`. (Headers beginning `x-sveltekit-` are exempt.)

### In the browser

Browser `fetch` in `load` resolves relative URLs against the *target page’s* URL (the one being navigated to), so `fetch('items')` from `/blog/a` resolves as it would on that page. A `Request` object passed in is rebuilt into equivalent `init` options (a body is read into memory). While the app has not yet started (hydration), responses come from the inlined scripts; afterwards, from the TTL cache or the network. In development, calling the global `fetch` instead of the load `fetch` during SSR warns you, because it would bypass inlining and credentials.

Registering dependencies: in a universal load, every `fetch` URL is automatically registered as a dependency (when not inside `untrack`), so `invalidate('/api/items')` reruns it. A **server** load’s `fetch` is *not* registered, a deliberate decision to avoid leaking secrets to the client (Chapter 5). The same asymmetry applies to `depends`.

### Choosing between `fetch` and direct calls

If a server load needs data from your own database, call the data layer directly; do not `fetch('/api/...')` yourself. An in-process fetch still pays for `reroute`, route matching, `handle` and serialisation to a `Response` and back. Use `fetch` when you want a single API contract shared by browser code and load code, when the endpoint implements caching headers you want honoured, or when `handleFetch` is the seam for service routing. A pragmatic structure is a shared function in `src/lib/server/` called by both the `+server.ts` and the `load`:

```ts
// src/lib/server/posts.ts
export async function listPosts(opts: { tag?: string; limit: number }) { /* db */ }
```

```ts
// src/routes/api/posts/+server.ts
import { listPosts } from '#lib/server/posts.js';
export const GET = async ({ url }) =>
    Response.json(await listPosts({ tag: url.searchParams.get('tag') ?? undefined, limit: 20 }));
```

```ts
// src/routes/blog/+page.server.ts
import { listPosts } from '#lib/server/posts.js';
export const load = async ({ url }) => ({
    posts: await listPosts({ tag: url.searchParams.get('tag') ?? undefined, limit: 20 })
});
```

## Parallelism, `parent()` and waterfalls

By default every node’s loads start at once. In the SSR pipeline (Chapter 2) there are two arrays of promises, started concurrently: server loads for all nodes, and universal loads for all nodes (each universal load waiting only for the server load of its own node). On the client, universal loads for all nodes start together, and all invalid server loads are fetched in **one** request. A page that needs three independent datasets from three layers therefore takes as long as the slowest, not the sum.

`parent()` introduces an ordering: `await parent()` waits for all ancestors’ results (merged) and, importantly, for the *ancestors’ own* `parent()` chains. It also records that this load depends on the parent’s data, so if an ancestor reruns, this load reruns too.

```ts
// src/routes/org/[org]/+layout.server.ts
export const load = async ({ params }) => ({ org: await db.orgs.bySlug(params.org) });
```

```ts
// src/routes/org/[org]/projects/+page.server.ts
export const load = async ({ parent, params }) => {
    const { org } = await parent();               // waits for the layout
    return { projects: await db.projects.forOrg(org.id) };
};
```

Semantics worth pinning down:

- In `+page.server.ts`/`+layout.server.ts`, `parent()` returns the merged data of ancestor **server** layouts only.
- In `+page.ts`/`+layout.ts`, `parent()` returns the merged data of ancestor **universal** layouts, with a twist: a layout with no `+layout.ts` is treated as `({ data }) => data`, so unshadowed `+layout.server.ts` results pass through. A layout that *has* a universal load shadows its server data unless it forwards `data`.
- `parent()` is not free of ordering hazards: calling it first, then starting independent work, serialises everything after it.

**The fix for accidental waterfalls** is to start independent work before awaiting `parent()`, or to avoid it entirely by recomputing from `params`:

```ts
// Waterfall: independent query waits for the layout
export const load = async ({ parent, params }) => {
    const { org } = await parent();
    const stats = await db.stats(params.org);      // could have started earlier
    return { stats, org };
};

// Parallel: start the work, then await both
export const load = async ({ parent, params }) => {
    const statsPromise = db.stats(params.org);
    const { org } = await parent();
    return { stats: await statsPromise, org };
};
```

Choose between `parent()` and re-querying by considering cost. If two nodes need the same row, a duplicated cheap lookup (cached per request in `locals` or by a memoising helper) beats a serialised chain, particularly since layout loads can be slow to resolve and every child would wait. A request-scoped cache is the cleanest tool:

```ts
// src/lib/server/org.ts
import { getRequestEvent } from '$app/server';

const cache = new WeakMap<object, Map<string, Promise<Org>>>();

export function getOrg(slug: string): Promise<Org> {
    const { request } = getRequestEvent();          // identity of the current request
    let perRequest = cache.get(request);
    if (!perRequest) cache.set(request, (perRequest = new Map()));
    let p = perRequest.get(slug);
    if (!p) perRequest.set(slug, (p = db.orgs.bySlug(slug)));
    return p;
}
```

Because `getRequestEvent()` returns the current request event inside `load`, helpers do not need the event threaded through (it works in `handle`, actions, `load` and remote functions, and throws elsewhere, with Chapter 7 covering its restrictions in remote functions). The `WeakMap` keyed on the `Request` ensures the cache is garbage-collected with the request and, critically, that two concurrent requests never share entries. Do not use a module-level `Map`: module state is shared across all requests (Chapter 12).

Finally, the documented warning about auth in layouts is a parallelism consequence: layout and page loads run concurrently unless the page calls `parent()`. If a layout load throws (say `error(401)`), the page load may already be running, and its work (a database read) happened even though the user will never see it. Guards belong in `handle` or in each page’s server load; a layout guard is a rendering convenience, not a barrier.

## Headers and cookies

### `setHeaders`

`setHeaders({ ... })` on the server sets response headers for the **document** response, available in both load flavours. Rules:

- A header can be set **once** per response across all loads: setting the same header twice, even from different nodes, is an error (`cache-control` header is already set). The one exception is `server-timing`, whose values are comma-joined.
- You cannot set `set-cookie`; use `cookies`.
- In the browser it is a no-op.
- It has no effect after the response has started streaming, and in `finally` of `resolve` it is replaced by a function that throws.
- In development, header names and values are validated.
- While prerendering, a `cache-control` header set via `setHeaders` is converted to a `<meta http-equiv>` tag in the HTML.

The canonical use is propagating cache semantics from a backing API to the page, as the documentation shows:

```ts
// src/routes/products/+page.ts
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, setHeaders }) => {
    const response = await fetch('https://cms.example.com/products.json');

    setHeaders({
        age: response.headers.get('age') ?? '0',
        'cache-control': response.headers.get('cache-control') ?? 'no-store'
    });

    return { products: await response.json() };
};
```

Note the null-safe defaults; `setHeaders` expects strings. And note a caching trap: a layout’s `setHeaders` and a page’s `setHeaders` cannot both set `cache-control`. If you want a baseline policy and per-page overrides, set the baseline in `handle` after `resolve` (if absent) rather than in a layout load.

For a data request (`__data.json`), the document headers are not used: client navigations don’t see them, and the data response always carries `cache-control: private, no-store`. `setHeaders` governs the HTML only, so CDN caching of HTML via load-driven headers coexists with uncached data requests. This is why `setHeaders`-based page caching works best for pages whose server data is not personalised, since a cached HTML shell with inlined server data bakes that data in.

### Cookies

Server loads receive `cookies` (Chapter 9 and Chapter 14 build on this):

```ts
// src/routes/+layout.server.ts
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ cookies }) => {
    const sessionId = cookies.get('sessionid');
    return { user: sessionId ? await getUser(sessionId) : null };
};
```

`cookies.set(name, value, options)` defaults `path` to `/` in 3.0 (in 2.x it had to be set explicitly), and defaults to `httpOnly: true`, `secure: true` (relaxed on `localhost` in development) and `sameSite: 'lax'`. `cookies.delete`, `cookies.getAll`, `cookies.serialize` and `cookies.parse` exist too. A cookie set in a load is applied to the response when `resolve` returns; but a `Set-Cookie` produced in a **streamed** promise would be too late, as would any response header (see “Redirects and errors”).

## `getRequestEvent`

`getRequestEvent()` from `$app/server` returns the current `RequestEvent` anywhere in the dynamic extent of a request (`handle`, `load`, actions, `+server`, remote functions), implemented with `AsyncLocalStorage`. It is how shared guards avoid prop-drilling:

```ts
// src/lib/server/auth.ts
import { redirect } from '@sveltejs/kit';
import { getRequestEvent } from '$app/server';

export function requireLogin() {
    const { locals, url } = getRequestEvent();

    if (!locals.user) {
        const redirectTo = url.pathname + url.search;
        redirect(303, `/login?${new URLSearchParams({ redirectTo })}`);
    }
    return locals.user;
}
```

```ts
// src/routes/account/+page.server.ts
import { requireLogin } from '#lib/server/auth.js';

export function load() {
    const user = requireLogin();     // guaranteed non-null below
    return { message: `hello ${user.name}` };
}
```

A subtle point: the event it returns during a load is the *load’s* event, so `url` there is the tracked `URL`: reading `url.pathname` inside `requireLogin` records a dependency for the load that called it. That is usually what you want (the redirect target depends on the URL) and occasionally a source of unexpected reruns; wrap in `untrack` if not. It also means `getRequestEvent` must be called synchronously during the request, not after an unrelated callback boundary that breaks async context (for example, inside a timer registered at module scope).

## Redirects and errors from load

### `redirect` and `error`

Both helpers **throw themselves**; you do not `throw redirect(...)` (that was SvelteKit 1). Their types return `never`, so TypeScript understands control flow stops:

```ts
import { error, redirect } from '@sveltejs/kit';

export const load = async ({ params, locals }) => {
    if (!locals.user) redirect(307, `/login?next=/posts/${params.id}`);

    const post = await db.posts.get(params.id);
    if (!post) error(404, 'Post not found');
    if (post.ownerId !== locals.user.id) error(403, { message: 'Forbidden', code: 'NOT_OWNER' });

    return { post };
};
```

In 3.0, `redirect(status, location, { external })` rejects external locations by default: a redirect to another origin throws unless you pass `{ external: true }` or an allow-list array, and `javascript:` and `data:` locations are blocked even with `external: true` unless the allow-list form is used. This closes the open-redirect class of bugs for `?next=` parameters. Validate user-supplied targets anyway:

```ts
function safeNext(raw: string | null): string {
    return raw && raw.startsWith('/') && !raw.startsWith('//') ? raw : '/';
}
```

Since both throw, never call them inside `try { ... } catch { ... }` unless the catch re-throws control-flow errors:

```ts
import { isHttpError, isRedirect } from '@sveltejs/kit';

try {
    await riskyThing();
    redirect(303, '/done');
} catch (e) {
    if (isRedirect(e) || isHttpError(e)) throw e;   // let the framework handle it
    // handle genuine failures here
}
```

### What happens to them

On the server (document request): a redirect becomes an HTTP response with the status and `Location`; an `error()` renders the nearest `+error.svelte` with that status (or `error.html` for the root layout; Chapter 10). On a data request, a redirect becomes `{"type":"redirect","status":307,"location":"..."}` with HTTP 200, and the client router follows it (up to 20 hops). On the client, a redirect thrown in a universal load during navigation behaves the same. An `error()` in a server load reaches the client as `{"type":"error","error":{...}}` for that node, and the router renders the `+error.svelte` above that node.

Each error passes through `handleError` (in 3.0 all of them, including expected `error()` ones, with a `kind`), which may transform the message and status. Uncaught non-HTTP errors become status 500 with the message from `handleError` (default “Internal Error”), so internal details never reach the client unless you return them.

### In streamed promises

Once a response has started, status and headers are committed. A `redirect()` thrown inside an un-awaited promise cannot change them, and `setHeaders` is a no-op or error there. A rejected streamed promise instead arrives as a rejection on the client (after passing through `handleError`) and is handled by the `{#await}` `:catch` or an unhandled-rejection report. Chapter 5 covers designing around this.

## Reading data in components

Data reaches a page through the `data` prop, validated at compile time by `PageProps`. A few practical patterns:

**Derive from props.** `data` is replaced (not mutated) when loads rerun. Copying it into `$state` at initialisation freezes the first value:

```html
<script lang="ts">
    let { data }: PageProps = $props();
    let posts = $state(data.posts);              // BUG: not updated when data changes
    let filtered = $derived(data.posts.filter((p) => p.published)); // correct
</script>
```

When you need local mutable state seeded from data (an editable draft), reset it explicitly on navigation: key the component with `{#key data.post.id}`, or use `$derived` with overrides (Svelte’s writable derived), or compare ids in an effect. Components survive navigation between URLs of the same route, which is why this matters.

**Reaching across the tree.** A layout accesses the page’s data through `page.data`; deeply nested components can read `page.data` or `page.params`, but prefer passing props for anything the component’s correctness depends on. `page` is also available in `+error.svelte` with `page.status` and `page.error`.

**`form` and `state`.** `page.form` and `page.state` are covered in Chapters 6 and 12.

## Tracing loads

With `tracing: { server: true }`, each server load and each universal load executed on the server produces a `sveltekit.load` span, with attributes `sveltekit.load.node_id`, `sveltekit.load.node_type` (the file name without extension, such as `+page.server` or `+layout`), `sveltekit.load.environment: 'server'` and `http.route`. Because the event passed to your load carries a merged `tracing` object, you can annotate the current span, and spans created by instrumented libraries (database drivers, `fetch`) nest under it:

```ts
// src/routes/orders/+page.server.ts
export const load = async ({ tracing, locals }) => {
    tracing.current.setAttribute('app.user_id', locals.user.id);
    const orders = await db.orders.recent(locals.user.id);
    tracing.current.setAttribute('app.orders_count', orders.length);
    return { orders };
};
```

Client-side loads are not traced by Kit; `tracing.enabled` is `false` and the spans are no-ops there, so shared universal code can call them safely.

## Common failure modes

- **Empty or stale layout data after navigation.** The layout load did not read the params/url that changed; read them, call `depends`, or move the data to the page.
- **`load` runs twice and logs twice.** A universal load on SSR runs on the server and again on hydration. Side effects belong in `onMount` or a server load.
- **A secret appears in the page source.** It was in a server load’s return value. Everything returned is serialised.
- **“`x` header is already set”.** Two loads (often a layout and a page) set the same header.
- **Hydration mismatch with `new Date()`.** Time or random values computed in a universal load differ between server and client. Compute once on the server, pass through server `load`, or use the same deterministic input.
- **Requests fan out unexpectedly on the server.** Many internal `fetch('/api/...')` calls each run `handle`; call the data layer directly.
- **Type says it exists, runtime says undefined.** A universal load that shadows a server load without forwarding `data`.
- **Cookies missing in `fetch` to `api.example.com`.** Not a subdomain of the app host; forward in `handleFetch`.

## Key takeaways

- A node can have a universal load, a server load, or both. Server load runs only on the server, can use secrets, and must return devalue-serialisable data (extended by `transport`); everything returned is visible to the client. When both exist, the server result arrives as `data` and the universal result replaces it, so forward what you need.
- Choose server load for databases, secrets, cookies and batching of several dependencies into one `__data.json` request; choose universal load for public APIs the browser can call directly or for non-serialisable return values.
- The event’s `params`, `route` and `url` are instrumented proxies that record reads (per search-param key for `get`, `getAll`, `has`); `request.url` is not tracked. `url.hash` is unavailable in load.
- Data merges shallowly from root to page with later keys winning; components see their own and ancestor data. Use `page.data` (typed by `App.PageData`) for parents needing child data, such as titles.
- The load `fetch` forwards `cookie` and `authorization` same-origin, forwards cookies only to the app host and its subdomains, resolves relative URLs, dispatches internal requests in-process (running `handle` again), absorbs `Set-Cookie`, simulates CORS for external hosts, and is routed through `handleFetch`.
- Universal-load fetches are inlined as `data-sveltekit-fetched` scripts and replayed during hydration; headers are only included if allowed by `filterSerializedResponseHeaders`, and reading a filtered header throws during SSR. `max-age`/`s-maxage` seed a short client cache.
- Loads run in parallel; `parent()` creates ordering and a dependency. Start independent work before awaiting `parent()`, or use a request-scoped cache keyed on the request via `getRequestEvent()`. Layout guards do not prevent page loads from executing.
- `setHeaders` sets each header at most once (except `server-timing`), cannot set cookies, only affects the document response, and is a no-op in the browser. Cookies have secure defaults.
- `redirect()` and `error()` throw themselves; do not catch them blindly (use `isRedirect`/`isHttpError`). External redirects are rejected unless allowed. In streamed promises, status and headers can no longer change.
- Derive from `data` with `$derived`; copying into `$state` freezes the first value. Components are reused across navigations within a route.

## Review Questions

1.  List three situations in which you would choose a server `load` over a universal `load`, and two in which the reverse is true.

2.  A route has `+page.server.ts` returning `{ a: 1, b: 2 }` and `+page.ts` returning `{ c: 3 }`. What does the page receive in `data`? What must the universal load do to fix it?

3.  **What does this print?** Layout `load` returns `{ user: 'ana', theme: 'dark' }`; page `load` returns `{ user: { name: 'ben' } }`. What is `data.user` and `data.theme` in the page? In the layout component?

4.  Why can a server `load` not return a class instance by default, and how can the class be supported? What must `encode` return for values that are not an instance?

5.  **Find the bug.** A server load does `return { user: await db.users.get(id) }` where the user row includes `passwordHash`. Explain why this leaks even if the component never renders the field, and fix it.

6.  A load reads `event.request.url` to filter by `?page=`. The page does not update when the user clicks “next”. Why, and what should it read?

7.  Which `URL` properties are tracked and which are not? Give one example of each kind.

8.  A universal load uses `url.searchParams.get('q')`. A user goes from `?q=a&sort=1` to `?q=a&sort=2`. Does the load rerun? And with `[...url.searchParams]`?

9.  **Multiple choice.** On the server, `fetch('/api/items')` inside a load:

    a.  Makes a real HTTP request to the public origin
    b.  Dispatches into `respond` in-process, running `handle` with `isSubRequest`
    c.  Calls the `GET` function directly, skipping `handle`
    d.  Is rejected because relative URLs are not allowed on the server

10. From `my.example.com`, which of these targets receive the user’s cookies via the load `fetch`: `example.com`, `api.example.com`, `sub.my.example.com`, `my.example.com`? What does `credentials: 'include'` change?

11. What does `data-sveltekit-fetched` contain, when is it emitted, and what happens to it during hydration? Why are server-load fetches not inlined?

12. A universal load calls `response.headers.get('etag')` and works in the browser but throws during SSR. Why, and what is the fix?

13. A universal load fetches `/api/items` with `cache-control: max-age=60`. What does `data-ttl` do for a client-side navigation back to the page 30 seconds later? What would a `POST` to `/api/items` in between do?

14. Why is calling `fetch('/api/posts')` from a server load usually worse than calling the data layer directly? Name a case where it is the right choice.

15. **Design question.** A layout load gets the organisation; three child page loads need it too. Compare (a) `await parent()`, (b) re-querying, (c) a request-scoped cache. Which do you choose and why?

16. What does `parent()` return in `+page.server.ts` versus in `+page.ts` when the nearest layout has only `+layout.server.ts`? What if that layout also has a `+layout.ts` that does not forward `data`?

17. **What does this do?** Page load: `const { org } = await parent(); const stats = await getStats(params.org); return { org, stats };`. Where is the waterfall, and how do you restructure?

18. A layout `+layout.server.ts` calls `error(401)` when unauthenticated. The page’s `+page.server.ts` reads the database. Is the page load executed? What does this imply for authorisation?

19. List the rules of `setHeaders`: how many times may a header be set, which headers are special, and where does it have no effect?

20. A layout sets `cache-control` via `setHeaders` and a page also sets it. What happens, and how would you implement a baseline plus override?

21. Why does `cache-control` from `setHeaders` not influence client-side navigation data requests?

22. Write the `getRequestEvent`-based helper `requireRole(role)` that redirects to `/login` or errors 403. What side effect does reading `url` inside it have when called from a load?

23. **Multiple choice.** Which is correct about `redirect()` in 3.x?

    a.  You must `throw redirect(...)`
    b.  External URLs are allowed by default
    c.  External URLs require `{ external: true }` or an allow-list
    d.  It may be called inside a streamed promise to redirect the page

24. Rewrite so redirects and HTTP errors are not swallowed:

    ```ts
    try {
      const r = await getThing();
      if (!r) error(404);
      return r;
    } catch {
      return fallback;
    }
    ```

25. In a data request, how is a thrown `redirect(307, '/login')` represented, and what HTTP status does that response have? Who follows it?

26. **What does this render?** `let posts = $state(data.posts);` in a page; the user navigates from `/blog?tag=a` to `/blog?tag=b` (same route). Explain the bug and two fixes.

27. Why does a universal `load` that uses `window.innerWidth` break SSR, and what are two correct alternatives?

28. How would you add a span attribute for the current user ID inside a server load, and why is the same code safe in a universal load?
