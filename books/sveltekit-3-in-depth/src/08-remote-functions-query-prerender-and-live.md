# Chapter 7: Remote Functions: query, prerender, and live

Remote functions let you write a function on the server and call it from anywhere, typed end to end, without declaring a route. The client gets a `fetch` wrapper; the server gets a function that can touch databases, secrets and `locals`. This chapter covers the read side of that system: `query`, `query.batch`, `query.live` and `prerender`, plus everything they share: module layout, validation, serialisation, request-scoped deduplication and the restrictions on `getRequestEvent()`. Chapter 8 covers the write side (`form` and `command`) and single-flight mutations, which build on the cache semantics described here.

> **Warning:** Remote functions are **still experimental in SvelteKit 3.1**. The API can change in a minor release, and you must opt in twice. The Svelte compiler needs `compilerOptions.experimental.async` (remote functions are consumed with `await` in markup), and SvelteKit needs `experimental.remoteFunctions`. Both options now live in the `sveltekit({...})` call in `vite.config.ts`; there is no `svelte.config.js` in SvelteKit 3.

```ts
// vite.config.ts
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [
        sveltekit({
            compilerOptions: { experimental: { async: true } },
            experimental: { remoteFunctions: true }
        })
    ]
});
```

With the flag off, the mere existence of a `*.remote.ts` file is an error. Throughout the chapter, when documentation and published types disagree, the types win; such places are called out.

## 7.1 Remote modules

A remote module is any file under `src` whose name has a `remote` segment: `posts.remote.ts`, `remote.ts`, `cart.remote.test.ts` (the segment rule mirrors server-only modules from Chapter 13). Rules the build enforces:

- **Placement.** Anywhere in `src` *except* inside a `server` directory. Files in server-only directories cannot be imported by client code, which is the whole point of a remote module, so the two are contradictory.
- **Exports.** Every export must be a remote function created by `query`, `query.batch`, `query.live`, `form`, `command` or `prerender`. A `default` export raises `remote_module_default_export`; any other value raises `remote_module_invalid_export`. Type-only exports are erased and therefore fine. Consequence: **you cannot export a schema** from a `.remote.ts` file. Put shared schemas in an ordinary module (`schemas.ts`) and import it from both sides.
- **Names.** Exports are named; reserved words such as `delete` or `class` are allowed (the client module is generated with care for that). Names that are `Object.prototype` members answer 404.
- **Libraries.** Files inside `node_modules` are remote modules only if the package lists `@sveltejs/kit` in `peerDependencies`. Section 7.9 returns to this.

### What the build does with them

The Vite plugin transforms each remote module twice. In the **server** build the module is kept as is, then a few lines are appended that give every export an `id` of `<hash>/<name>`, where `hash` is a hash of the file path relative to the project root. Each remote module is emitted as its own chunk so the server can load it lazily by hash. In the **client** build the module is replaced with a generated one that exports, for each name, a call such as `query('a1b2c3/getPost')` from SvelteKit’s client runtime; the server code never reaches the browser. To know the type of each export (query, form, …) in production, the server build is analysed first and the metadata is handed to the client build; in development the module is loaded in the Vite runner and inspected.

Two things follow. First, the HTTP endpoint is derived from file location: **moving a remote file changes its endpoint**, which matters for clients on an old deployment (section 7.9, and the version polling in Chapters 2 and 12). Second, importing a remote module in server code, for example calling `await getPost(slug)` from a `load` function, calls the real function directly, with request-scoped deduplication, no HTTP involved.

## 7.2 On the wire

Knowing the wire protocol makes caching, proxies, logging and security reviews much easier. Every remote call goes to `/<appDir>/remote/<hash>/<name>` (default `/_app/remote/...`, honouring `paths.base`) and passes through `handle`:

| Function | Method and body | Response |
|------------------------|------------------------|------------------------|
| `query` | `GET ...?payload=<devalue-string>` | JSON envelope |
| `query.batch` | `POST` JSON `{ payloads: string[] }` | JSON envelope with one result or error per payload |
| `query.live` | `GET ...?payload=...`, `accept: text/event-stream` | `text/event-stream`, `data:` lines, `: keep-alive` comments every 30 s |
| `prerender` | `GET /<appDir>/remote/<hash>/<name>/<payload>` | JSON envelope; prerendered file on a CDN, or computed (if `dynamic`) |
| `form` | `POST`, SvelteKit’s binary form encoding | JSON envelope (Chapter 8) |
| `command` | `POST` JSON `{ payload, refreshes }` | JSON envelope (Chapter 8) |

The JSON envelope is `{ type: 'result', data: <devalue string> }`, `{ type: 'error', error: App.Error }` or, for a redirect, a result whose data holds `redirect: <location>` which the client follows with `goto`. Responses carry `cache-control: private, no-store` (except while prerendering) so a shared cache can never serve one user’s personalised query result to another; they also carry the version header SvelteKit uses to notice new deployments.

Three observations that matter in production:

- **Errors travel inside HTTP 200.** At runtime, an error raised by a remote function (including a validation failure) is serialised as `{ type: 'error', error }` in a normal response; the error’s `status` (400, 404, 500…) is in the body. The HTTP status is only non-200 during prerendering (so the build fails) or when something *around* the function, such as `handle` or a CSRF check, rejects the request. The client handles both: it prefers the body when it is a recognisable envelope and otherwise synthesises an `HttpError` from the HTTP status. If you monitor error rates by HTTP status, remote function failures will not show up there; use the tracing spans (`sveltekit.remote.call`, Chapter 17) or log in `handleError`.
- **Non-`GET` calls are origin-checked.** `form`, `command` and `query.batch` are `POST`s. Any non-`GET` remote request whose `Origin` header differs from the app’s origin is rejected, and unlike classic form posts, `csrf.trustedOrigins` is *not* honoured for them: remote endpoints are an implementation detail, not a public API. A `query` is a `GET`, so it is not origin-checked: never rely on a `GET` being “same-site only”.
- **Calls carry the page URL in headers.** The client adds `x-sveltekit-pathname` and `x-sveltekit-search` identifying the page the call was made from. SvelteKit uses them to populate `event.url`, `event.params` and `event.route` for `form` and `command`, which is why those are *client-controlled* and must never inform authorisation (section 7.8).

## 7.3 Validation

Anything that takes an argument must declare how it is validated, because the endpoint is public HTTP:

```ts
// src/routes/blog/schemas.ts
import * as v from 'valibot';

export const slug = v.pipe(v.string(), v.regex(/^[a-z0-9-]{1,80}$/));
export const pageArg = v.object({
    page: v.optional(v.pipe(v.number(), v.integer(), v.minValue(1)), 1),
    tag: v.optional(v.string())
});
```

The first argument of the builder is either a [Standard Schema](https://standardschema.dev) (Valibot, Zod, ArkType, and others implement it), the string `'unchecked'`, or absent. The shapes:

```ts
query(async () => { ... });                    // no argument; passing one is an error
query(schema, async (arg) => { ... });         // validated; arg is the schema OUTPUT type
query('unchecked', async (arg: Foo) => { ... });// no runtime check; you vouch for the type
```

What happens at runtime:

- **No schema, argument passed:** the server answers with `error(400, 'Bad Request')`. A function declared without a validator refuses all input, which makes “I forgot to validate” fail closed.
- **Schema, invalid input:** a `ValidationError` is raised; the function body never runs. The error reaches `handleError` with `kind: 'validation'`, `error: { status: 400, message: 'Bad Request' }` and the Standard Schema `issues`. By default the issues are *not* sent to the client, because they teach an attacker about your internals.
- **`'unchecked'`:** the value goes through untouched. TypeScript will believe whatever annotation you wrote; the network will not. Reserve it for cases where the argument is an opaque value you validate later or where a schema would reject legitimate data. Never use it with an argument you interpolate into a query.
- **Transforming schemas:** `Input` (what callers pass) and `Output` (what the function body sees) can differ. The generated function type carries a third type parameter, `Validated`, equal to the schema’s output. It is the type `requested()` yields in Chapter 8.

Async validators are allowed, with one caveat: `requested()` can only be iterated synchronously when the validator is synchronous; otherwise use `for await`.

A good production `handleError` treats validation failures as security events, not application errors:

```ts
// src/hooks.server.ts
import type { HandleServerError } from '@sveltejs/kit/hooks';

export const handleError: HandleServerError = ({ kind, error, issues, event }) => {
    if (kind === 'validation') {
        // log paths, not values: issues can contain attacker-supplied data
        console.warn('remote validation failed', {
            path: event.url.pathname,
            fields: issues.map((i) => i.path?.map((p) => (typeof p === 'object' ? p.key : p)).join('.'))
        });
        return error; // generic { status: 400, message: 'Bad Request' }
    }
    // ... other kinds, see Chapter 10
};
```

The two legitimate causes of validation failures, per the docs, are a signature change between deployments (an old tab calling the new schema) and someone poking the endpoint. Both are worth separate dashboards.

## 7.4 `query`

A query reads server data. It is declared with a schema and a function:

```ts
// src/routes/blog/posts.remote.ts
import { error } from '@sveltejs/kit';
import { query } from '$app/server';
import * as db from '#lib/server/db.js';
import { slug, pageArg } from './schemas';

export const getPosts = query(pageArg, async ({ page, tag }) => {
    return db.listPosts({ page, tag, pageSize: 20 });
});

export const getPost = query(slug, async (s) => {
    const post = await db.getPostBySlug(s);
    if (!post) error(404, 'Post not found');
    return post;
});
```

The returned function is called with the argument and yields a **query resource**, a promise with extras. Its type, `RemoteQuery<T>`, is `Promise<T>` plus `error`, `loading`, `ready`, `current`, `refresh()`, `set(value)` and `withOverride(fn)`. `current` is `undefined` until `ready` is `true`; TypeScript models this as a discriminated union, so after checking `ready` the type of `current` is narrowed to `T`.

### Consuming a query

With Svelte’s async support, the idiomatic use is `await` in markup, `$derived` or `<script>`, and the nearest `<svelte:boundary>` handles pending and failed states:

```html
<!-- src/routes/blog/[slug]/+page.svelte -->
<script lang="ts">
    import { getPost } from '../posts.remote';
    import type { PageProps } from './$types';

    let { params }: PageProps = $props();
    const post = $derived(await getPost(params.slug));
</script>

<svelte:boundary>
    <h1>{post.title}</h1>
    <article>{@html post.html}</article>

    {#snippet pending()}<p>Loading...</p>{/snippet}
    {#snippet failed(error: App.Error, reset)}
        <p>{error.status === 404 ? 'No such post.' : 'Something went wrong.'}</p>
        <button onclick={reset}>Retry</button>
    {/snippet}
</svelte:boundary>
```

When you want local control instead of a boundary, use the reactive properties:

```html
<script lang="ts">
    import { getPosts } from '../posts.remote';
    let page = $state(1);
    const posts = $derived(getPosts({ page }));   // not awaited: a resource
</script>

{#if posts.error}
    <p>{posts.error.message}</p>
{:else if !posts.ready}
    <p>Loading...</p>
{:else}
    <ul class:stale={posts.loading}>
        {#each posts.current as p (p.slug)}<li>{p.title}</li>{/each}
    </ul>
{/if}
<button onclick={() => page++}>Next</button>
```

`loading` is `true` before the first value *and during refreshes*, whereas `ready` becomes `true` once and stays. That combination gives the “keep showing the old data, dim it while reloading” pattern above. Note that `posts.error` is typed `App.Error | undefined` in SvelteKit 3 (previously `any`), because every error has been through `handleError`.

A query is also awaitable outside reactive contexts: in event handlers, async callbacks, module scope and universal `load` functions. `query.run()`, which older versions had for this, was removed in 2.61 in favour of plain `await`.

### Keys and sharing

A query’s identity is the pair (function id, serialised argument). The argument is stringified with devalue using stable ordering: object keys, `Map` and `Set` members are sorted, so `getPosts({ page: 1, tag: 'a' })` and `getPosts({ tag: 'a', page: 1 })` are the same key. Arrays keep their order, so use an array when order matters. Arguments must be serialisable: `RegExp` and promises raise `remote_argument_unsupported`; custom classes need a `transport` encoder (section 7.9). Return values are not sorted or canonicalised.

**On the server**, a request-scoped cache keyed this way ensures the body runs at most once per request, no matter how many components or `load` functions call it. That is the dedupe the docs advertise, and it is why a private helper query such as `getUser` (called by a dozen other queries) is cheap:

```ts
// src/routes/me.remote.ts
import { getRequestEvent, query } from '$app/server';
import { error } from '@sveltejs/kit';

// not exported: a private query has no endpoint, but still dedupes per request
const currentUser = query(async () => {
    const { locals } = getRequestEvent();
    return locals.user ?? null;
});

export const getDashboard = query(async () => {
    const user = await currentUser();
    if (!user) error(401, 'Sign in required');
    return db.dashboardFor(user.id);
});
```

A private (non-exported) query never appears in a response payload, so it is safe for data that must not reach the client. (The implementation deliberately skips serialising anything without an `id`.)

**On the client**, identical calls return proxies that point at one underlying `Query` instance. The cache entry lives as long as something references it: a rendered component, an in-flight await, a stored resource. When the last proxy is garbage collected (the runtime uses a `FinalizationRegistry`) and no effect pins it, the entry is evicted on the next tick. You do not manage lifetimes, but you should know the consequence: **a query is not a long-lived store**. (It is also why the runtime’s cache factory takes care not to close over the proxy: a reference from the cache entry back to its proxy would keep the proxy alive, and the entry would never be evicted.) If you navigate away and back, or hold no reference, you will refetch. Persist data you want to keep in `$state` outside the query, or use `prerender` for data that rarely changes.

### Server-side rendering and hydration

When a query is awaited during SSR, the server runs it, serialises the result into the HTML via Svelte’s `hydratable` mechanism, and the client seeds its cache from that payload without issuing a request. Details that affect design:

- Only queries that **settled** before the response chunk was flushed are included. A query still pending when the payload is assembled is omitted and the client fetches it itself.
- A failed query’s error is serialised too, so the client hydrates in the same failed state.
- Queries called on a page that is **prerendered** fail the build (`remote_query_prerender`): runtime data has no place in static HTML. Use `prerender` instead (section 7.7) or opt that page out of prerendering.
- Calling `.refresh()` or `.set()` on the server is only meaningful inside a `form`/`command` handler (Chapter 8); `withOverride` throws on the server (`server_api_unavailable`).

### `refresh`, `set` and `withOverride` on the client

```ts
const posts = getPosts({ page: 1 });

await posts.refresh();            // refetch from the server
posts.set(newList);               // replace the value locally, no request
const release = posts.withOverride((list) => [draft, ...list]);  // optimistic view
release();                        // drop the override
```

`refresh()` returns a promise for the refetch and, importantly, handles races: each run registers a resolver, and a response is applied only if no *later* refresh has started, so a slow earlier response cannot overwrite a newer one. `set()` also settles any in-flight request’s waiters with the new value. `withOverride(fn)` pushes a pure function onto a stack that is reduced over the real value to derive `current`; it returns a release function, usable on its own or handed to `.updates(...)` so it is released automatically when a mutation finishes (Chapter 8). Overrides compose: two overrides apply in insertion order, and refreshes underneath them continue to land.

Because the cache is keyed by argument, `getPosts({ page: 1 }).set(...)` affects only that instance. To touch every active instance of a function use `refreshAll()` from `$app/navigation` (Chapter 5), which re-runs load functions and refreshes active queries, or `.updates(getPosts)` on a mutation.

### Queries versus `load`

|  | `load` | `query` |
|------------------------|------------------------|------------------------|
| Granularity | per route node, keyed by route and dependencies | per call, keyed by argument |
| Waterfalls | parallel across nodes; `parent()` serialises | whatever your `await` structure creates |
| Invalidation | `invalidate`, `depends`, `refreshAll` | `.refresh()`, mutation single-flight, `refreshAll` |
| Co-location | in the route file | next to the component that needs it |
| Streaming | un-awaited promises from server load | `await` + `<svelte:boundary pending>` |
| Works with prerendered pages | yes | no (use `prerender`) |
| Stability | stable | experimental |

Queries make components self-sufficient, but they also make waterfalls easy to create: a child component that awaits inside an `{#if await a()}` block will not start `b()` until `a()` resolves. Hoist independent queries (`const [a, b] = await Promise.all([getA(), getB()])`, or start them in `<script>` before awaiting) or pass them down as props.

## 7.5 `query.batch`

N+1 is the classic cost of component-level data fetching: a list of 40 cards each asking for “its” weather or price fires 40 requests and 40 database calls. `query.batch` solves both by collecting every call made within **one macrotask** into a single request, and on the server a single invocation of your function:

```ts
// src/routes/cities/weather.remote.ts
import * as v from 'valibot';
import { query } from '$app/server';
import * as db from '#lib/server/db.js';

export const getWeather = query.batch(v.string(), async (cityIds) => {
    const rows = await db.sql`SELECT * FROM weather WHERE city_id = ANY(${cityIds})`;
    const byCity = new Map(rows.map((r) => [r.city_id, r]));

    // return a resolver: called once per input, in order, with (arg, index)
    return (cityId, index) => byCity.get(cityId) ?? null;
});
```

The callback receives the array of **validated** arguments (de-duplicated by serialised payload) and returns a function `(arg, index) => result`. SvelteKit calls that function once per call-site. Consequences:

- A throw inside the resolver rejects only *that* call. Other entries in the batch succeed; on the wire each entry is `{ type: 'result' | 'error' }`. A throw in the outer callback rejects the whole batch.
- Duplicate arguments in one macrotask are collapsed into one entry whose result is shared among the callers.
- The client side uses `setTimeout(..., 0)` rather than a microtask on purpose: Svelte uses microtasks to flush reactive updates, and a flush can reveal more queries that belong to the same batch. On the server, the same macrotask rule applies to concurrent SSR calls, so a server-rendered list triggers one call to your batch function.
- Validation runs for all elements *before* the batch body is invoked, and an invalid element rejects the **whole** batch (the validation promises are combined with `Promise.all`). Isolation is per resolver call, not per validation.

Use `query.batch` when the data source supports a bulk lookup (`WHERE id = ANY(...)`, a DataLoader-like API). It does not make N independent slow computations faster; it only reduces round-trips. And note the cost of the pattern: a batched function’s cache key is still per-argument, so `.refresh()` refetches one id (one request of size one).

## 7.6 `query.live`

`query.live` is for data the server pushes: prices, notifications, job progress. The callback returns an async iterable, typically an async generator:

```ts
// src/routes/jobs/jobs.remote.ts
import * as v from 'valibot';
import { getRequestEvent, query } from '$app/server';
import * as bus from '#lib/server/bus.js';
import * as db from '#lib/server/db.js';

export const jobProgress = query.live(v.string(), async function* (jobId) {
    const { request } = getRequestEvent();

    // first value is what SSR renders and hydration reuses: always yield one immediately
    yield await db.jobStatus(jobId);

    const subscription = bus.subscribe(`job:${jobId}`);
    try {
        for await (const update of subscription.iterate({ signal: request.signal })) {
            yield update;
        }
    } finally {
        subscription.close(); // runs when the client disconnects or the stream is closed
    }
});
```

Mechanics, from the runtime source:

**Server side rendering.** `await jobProgress(id)` during SSR runs the generator, takes the **first** value, then closes the generator (its `finally` runs). A generator that finishes without yielding raises `remote_query_live_no_value`. The first value is serialised for hydration.

**The stream.** On the client the connection is a `fetch` with `accept: text/event-stream` to the query endpoint, read as server-sent events by SvelteKit’s own reader (not `EventSource`, so errors and aborts are controllable). The server sends `data: {"type":"result","result":"<devalue>"}` frames. Details worth knowing:

- **Consecutive identical values are suppressed.** The server compares the devalue string of each yielded value to the previous one and does not resend duplicates, so a generator that polls and yields the same snapshot every second costs no bandwidth after the first frame.
- A `: keep-alive` comment is sent after 30 seconds without a message, so idle-timeouts on proxies and load balancers do not kill a quiet stream.
- The response has `cache-control: private, no-store`.
- A thrown `redirect` becomes a `redirect` frame (the client navigates); other throws become an `error` frame, serialised through `handleError`.
- The request’s abort signal is the cancellation channel. When the client disconnects, SvelteKit aborts the request signal and calls `generator.return()`, but it cannot interrupt an `await` that is pending *inside* your generator. **Cooperative cancellation via `request.signal` is yours to implement** (as above, by passing the signal to whatever you are awaiting).

**Client state.** The resource has the usual `current`, `loading`, `ready`, `error`, and two additional flags:

- `connected` is `true` while a stream is open.
- `done` is `true` once the server finished the stream (the generator returned) or the query hard-failed. A finished stream does not restart on its own; call `reconnect()`.

```html
<script lang="ts">
    import { jobProgress } from './jobs.remote';
    let { id }: { id: string } = $props();
    const job = $derived(jobProgress(id));
</script>

<svelte:boundary>
    <progress value={(await job).percent} max="100"></progress>
    <small>{job.connected ? 'live' : job.done ? 'finished' : 'reconnecting...'}</small>
    {#snippet pending()}<p>Connecting...</p>{/snippet}
</svelte:boundary>
```

**Sharing.** All consumers of the same key share one connection, whether reactive (`await`, `.current`) or imperative. The resource is async-iterable for imperative consumers:

```ts
for await (const update of jobProgress(id)) {
    if (update.percent === 100) break;
}
```

A new iterator first yields the most recent value if one is already available, then each new value. It is a **latest-value** channel, not an event log: if values arrive faster than the consumer drains, intermediate ones are dropped. If you need every event (an audit feed, chat history), model it as a query that returns a cursor-paginated list and use live only as a “something changed” signal.

When no consumers remain, the client closes the stream and the server stops iterating. On the server, concurrent `for await` consumers inside one request also share one pumped iteration of your generator.

**Reconnection.** On a network-level failure after a value has been received, the client keeps the last good value and retries with exponential backoff, base `250 ms * 2^attempt` capped at 10 s with ±20 % jitter; the attempt counter resets on a successful connect. Specific behaviours:

- If `navigator.onLine` is `false`, retrying stops until the browser fires `online`.
- On `pagehide`/`beforeunload` the stream is closed; if the page returns from the back/forward cache (`pageshow` with `persisted`), it reconnects.
- If the server produces an *intentional* error (`HttpError`, validation failure) after the first value, the query fails terminally (`done` is `true`, `error` set). Only `reconnect()` revives it. An error before the first value surfaces to the awaiting consumer immediately.
- `reconnect()` closes the current stream and opens a new one, resolving when the new connection is established. Active `for await` loops keep running across it.
- There is no `refresh()`: the query refreshes itself. Single-flight mutations use `reconnect()` instead (`requested(...).reconnectAll()`, Chapter 8), for example when a command changes a cookie the generator captured when it started.

> **Warning:** Do not cache live responses in a service worker. The stream outlives the page, and a cloned response will keep streaming. Exclude any response whose `Cache-Control` contains `no-store` from your caching logic (Chapter 16).

Operationally, a live query holds a connection and an in-flight request open per subscribed client. Budget for it like any SSE endpoint: platform timeouts (serverless platforms usually cap duration), connection limits, and proxy buffering. Adapters that buffer responses (Lambda-style) cannot stream; the stream will only deliver when the function ends.

## 7.7 `prerender`

`prerender` is `query` for data that changes at most once per deployment. It runs at build time and its results become static files:

```ts
// src/routes/docs/docs.remote.ts
import * as v from 'valibot';
import { error } from '@sveltejs/kit';
import { prerender } from '$app/server';
import * as db from '#lib/server/db.js';

export const getDocsIndex = prerender(async () => db.docsIndex());

export const getDoc = prerender(
    v.string(),
    async (slug) => {
        const doc = await db.docBySlug(slug);
        if (!doc) error(404, 'No such doc');
        return doc;
    },
    {
        // seed the build with inputs the crawler cannot discover
        inputs: () => db.allDocSlugs()
    }
);
```

How it works:

- **Discovery.** While prerendering pages, every call to `getDoc(arg)` that the crawler’s render performs is recorded, executed once, and written as a static response at `/_app/remote/<hash>/getDoc/<payload>`. `inputs` adds arguments the crawl would not hit. Within one prerender run the same call is shared across all pages (the result is memoised by URL).
- **Excluded from the server bundle.** By default prerender functions are tree-shaken from the server build, so at runtime you *cannot* call them with an argument that was not prerendered; the request is served from static assets. Set `dynamic: true` to keep the function in the server bundle: prerendered arguments are still served statically, anything else is computed on demand.
- **Runtime lookup.** During SSR in production, calling a prerender function first tries to fetch the static response from the app’s own URL (with `redirect: 'manual'` as an SSRF guard); only if it is not there does it fall back to running the function (`dynamic` required to exist). In dev, it always runs the function.
- **Browser cache.** The browser stores results with the Cache API under a name derived from the deployment version, deletes caches from other versions, and consults the cache before the network. So results survive reloads and are cleared when the user first visits a new deployment. A prerender *error* in the static file is propagated rather than silently re-running the function.
- **Hydration.** A prerender called during SSR is serialised into the page like a query, so the client does not refetch.
- **No mutation API.** A prerender resource has `current`, `loading`, `ready`, `error`, and is awaitable, but no `refresh`, `set` or `withOverride`. Use `query` if you need to mutate or invalidate.

Prerender fits the “partial prerendering” strategy: a dynamic, personalised page can embed prerendered building blocks that a CDN serves, which is often a bigger win than prerendering the whole route. Choose by freshness: if an edit must show up without a redeploy, it is a `query`; if a redeploy is acceptable, a `prerender`.

Unlike queries, prerender functions *can* be called from pages that are fully prerendered, which is precisely the `adapter-static` use case. During the build, a failing prerender function fails the build with the error’s status.

## 7.8 `getRequestEvent` and request-scoped behaviour

`getRequestEvent()` from `$app/server` returns the current `RequestEvent` from within `handle`, `load`, actions, endpoints and every remote function. It uses `AsyncLocalStorage` where available (on runtimes without it, the event is only reliably available synchronously at the start of the function, before the first `await`; read what you need first). It enables auth helpers that do not need the event passed explicitly:

```ts
// src/lib/server/auth.ts  (imported as #lib/server/auth.js)
import { getRequestEvent } from '$app/server';
import { error } from '@sveltejs/kit';

export function requireUser() {
    const { locals } = getRequestEvent();
    if (!locals.user) error(401, 'Sign in required');
    return locals.user;
}
```

Inside remote functions the event is a *derived* view with deliberate restrictions:

| Property | `query` / `.batch` / `.live` / `prerender` | `form` / `command` |
|------------------------|------------------------|------------------------|
| `locals`, `request`, `platform`, `getClientAddress()` | available | available |
| `cookies.get/getAll` | available | available |
| `cookies.set/delete` | **throws** (`remote_cookie_forbidden`) | allowed; `path` must be absolute |
| `setHeaders` | **throws** (`remote_headers_forbidden`) | **throws** |
| `url`, `params`, `route` | **throws** (`remote_request_property`) | refer to the *calling page* (client-supplied) |
| `isRemoteRequest` | `true` for HTTP calls | `true` for HTTP calls |

The reasoning for queries is cache coherence: a result is cached by its argument, and is not re-run on navigation, so a function whose output silently depends on the current URL would go stale without the cache noticing. Pass what you need as an argument. The restriction applies transitively to queries nested inside live queries, and the getters are non-enumerable so spreading the event does not trigger them.

What `handle` sees is another subtle point. For a `query`, `handle` runs with the URL of the **remote endpoint**, not of the page, so a path-prefix guard in `handle` (`if (event.url.pathname.startsWith('/admin'))`) does not protect an admin query. For `form` and `command`, `handle`’s `url`/`route`/`params` reflect the calling page because of the headers described in 7.2, and may be forged. The robust pattern is the one above: derive trust in `handle` from **cookies/headers** into `locals`, and re-check authorisation **inside each remote function** with `requireUser()` and a data-level permission check. Chapter 14 builds a full model on this.

Cookies read inside a query are not part of its cache key. If the same argument can return different data per user, the server-side per-request cache is still safe (it is per request), and responses are `no-store`. The *client* cache, however, is per page lifetime and does not know about sign-in changes: after login or logout, call `refreshAll()` or navigate with a full reload, or pass a user-scoped value as an argument.

## 7.9 Serialisation, transport and versioning

Arguments and results go through [devalue](https://github.com/sveltejs/devalue), so they can contain `Date`, `Map`, `Set`, `BigInt`, `URL`, typed arrays, repeated references and cycles, but not functions, class instances (unless transported), `RegExp` arguments, or promises (arguments only). Serialising Node `Buffer` results during SSR was fixed in a recent release, but prefer `Uint8Array` for portability. `File` is allowed in `command` arguments and `form` fields, not in query arguments.

Custom types use the universal `transport` hook from `src/hooks.ts`, shared with `load` data and action results:

```ts
// src/hooks.ts
import type { Transport } from '@sveltejs/kit/hooks';
import { Money } from '#lib/money.js';

export const transport: Transport = {
    Money: {
        encode: (v) => v instanceof Money && [v.cents, v.currency],
        decode: ([cents, currency]) => new Money(cents, currency)
    }
};
```

`encode` returns a truthy encoding or `false`. It must be total and cheap: it is called on every value. The same encoders apply to *arguments*, so `getTotal(new Money(500, 'EUR'))` works and, because the cache key is built from the encoded form, two equal `Money` values share a cache entry.

Versioning is the operational hazard. Because a client may be running a previous build while the server is new (or vice versa during a rolling deploy):

- Adding an optional argument field is safe; removing or renaming one produces validation failures on stale clients.
- Moving or renaming a remote module changes its hash; old clients get 404. SvelteKit detects new deployments via the version header on remote responses and `version.pollInterval` (default one hour) and the `updated` object from `$app/state`; call `updated.check()` or reload on the first failed call after `updated.current` becomes `true`.
- Treat `kind: 'validation'` errors during a deployment window as expected noise.

### Libraries that ship remote functions

A package can export remote modules if it lists `@sveltejs/kit` in `peerDependencies`; only then does the Vite plugin treat its `*.remote.js` files as remote modules (otherwise any `remote.ts` in `node_modules` would be hijacked). The published module is ordinary compiled JavaScript importing `query`/`form` from `$app/server`; the consuming app’s build assigns the ids from the file path inside `node_modules`. Keep these constraints in mind when designing such a package: it inherits the app’s `handleError`, `handle`, transport and auth model; it cannot assume a particular `locals` shape without documenting it; and, because the feature is experimental, you should pin a peer range such as `^3.1.0` and expect churn. Packaging mechanics are covered in Chapter 19.

## 7.10 Testing and debugging notes

- Remote modules are normal modules on the server, but they import `$app/server`, whose builders need a request context (`get_request_store`). To unit test the *logic*, extract it into plain functions and keep the remote function a thin wrapper. To test end to end, use Playwright against `vite preview`.
- In development, editing a remote module re-runs the generated client module; active queries refresh automatically (HMR calls `refresh()` on live entries).
- Tracing: with `tracing.server` on, each call is a `sveltekit.remote.call` span with `sveltekit.remote.call.id`, `.type` and `.name` attributes (Chapter 17).
- Errors thrown by a query during SSR are not fatal to the response unless awaited in a position without a boundary. Un-awaited reads (`.current`, `.error`) swallow the rejection, serialise it for hydration and render the failed state.

## Key takeaways

- Remote functions are experimental in 3.1 and need `experimental.remoteFunctions` plus `compilerOptions.experimental.async`, both inside `sveltekit({...})`.
- Remote modules are `*.remote.ts` / `remote.ts` files outside `server` directories; all exports must be remote functions; schemas live elsewhere. The endpoint id is a hash of the file path plus the export name.
- Every argument is public HTTP input: use a Standard Schema or the deliberate `'unchecked'`. Functions without a validator reject any argument with 400. Validation failures reach `handleError` with `kind: 'validation'` and the issues.
- Query keys are `(id, stable-serialised argument)`. The server dedupes per request; the client shares one instance per key and evicts when unreferenced.
- `refresh`, `set` and `withOverride` are client-side operations; on the server, `refresh`/`set` only matter inside mutation handlers.
- `query.batch` collapses calls from one macrotask into one request and one server call, with per-entry error isolation.
- `query.live` is a latest-value SSE stream: first value for SSR, no duplicate frames, 30 s keep-alives, backoff reconnection, terminal intentional errors, `reconnect()`, no service-worker caching.
- `prerender` produces static responses at build time, is excluded from the server bundle unless `dynamic: true`, caches in the browser per deployment version, and is the only remote read usable on fully prerendered pages.
- In queries, `event.url`, `params` and `route` throw; cookies are read-only; headers cannot be set. In forms and commands those properties come from the client and must not drive authorisation. `handle` sees the endpoint URL for queries.
- Runtime errors in remote functions travel in an HTTP 200 envelope; monitor with `handleError` and tracing rather than HTTP status alone.
- Use `transport` for custom types, plan for stale clients during deployments, and list `@sveltejs/kit` as a peer dependency to ship remote functions in a library.

## Review Questions

1.  Which two options enable remote functions in SvelteKit 3.1, and where do they live?
2.  A teammate exports a Valibot schema from `posts.remote.ts` so the form and server share it. What happens and what is the fix?
3.  Why can a remote module not live in `src/lib/server/`?
4.  How is the HTTP endpoint for `getPost` in `src/routes/blog/posts.remote.ts` derived, and what breaks if you move the file?
5.  A `query` is declared as `query(async () => ...)` and called as `getThing('x')`. What does the server return?
6.  What does `'unchecked'` change at runtime, and what does it not change at compile time? Give one situation where it is acceptable.
7.  Explain the difference between `Input`, `Output` and `Validated` for a query whose schema is `v.pipe(v.string(), v.transform(Number))`.
8.  Predict: are `getPosts({ page: 1, tag: 'a' })` and `getPosts({ tag: 'a', page: 1 })` the same cache entry? What about `getPosts([1, 'a'])` versus `getPosts(['a', 1])`?
9.  Multiple choice: a validation failure for a remote query reaches the client as

    a.  an HTTP 400 response with the Valibot issues in the body
    b.  an HTTP 200 response whose envelope has `type: 'error'` and `{ status: 400, message: 'Bad Request' }`
    c.  an HTTP 500 response
    d.  a thrown `ValidationError` instance
10. What is the difference between `loading` and `ready` on a query resource, and how would you use both for a “dim while refreshing” list?
11. What does this render the second time `Next` is clicked, and how many requests are made if `getPosts` is a plain `query`?

    ```html
    <script lang="ts">
      let page = $state(1);
      const posts = $derived(getPosts({ page }));
    </script>

    <button onclick={() => page++}>Next</button>
    {#each (await posts) as p}<li>{p.title}</li>{/each}
    ```
12. Why does a private (non-exported) query still dedupe per request, and why is it safe for sensitive data?
13. A page that is prerendered calls `await getPosts()` where `getPosts` is a `query`. What happens at build time and what are two fixes?
14. How is a client query’s cache entry evicted? Why does the implementation avoid closing over `this` in the cache factory?
15. Design: 30 `<ProductCard>` components each call `await getStock(id)`. Sketch the server-side function so that one database query serves all of them, and say what happens if one id does not exist.
16. Find the bug:

    ```ts
    export const getStock = query.batch(v.string(), async (ids) => {
      const rows = await db.stock(ids);
      return (id) => rows.find((r) => r.id === id).qty;
    });
    ```
17. Why does the client batch use `setTimeout(0)` instead of a microtask?
18. A live-query generator never yields before awaiting an event that may take minutes. What goes wrong during SSR and hydration?
19. A live-query generator polls a database every second and yields the snapshot. Does the client receive 60 messages a minute if nothing changes? Explain.
20. Describe the reconnection policy of a live query: backoff formula, what stops retries, and what makes a failure terminal.
21. Multiple choice: what does `done` indicate on a live query?

    a.  the browser is offline
    b.  the server finished the stream or the query failed terminally; only `reconnect()` restarts it
    c.  the first value has arrived
    d.  the generator is paused
22. Why is `request.signal` important inside a live-query generator that awaits an external subscription?
23. Why must live responses not be cached by a service worker, and how can you detect them?
24. What is the difference between `prerender` and `query` regarding (a) when they run, (b) the server bundle, (c) browser caching, (d) `refresh`?
25. A `prerender` function without `dynamic: true` is called at runtime with an argument that was never prerendered. What happens?
26. Table-fill: for each of `url`, `cookies.set`, `setHeaders`, say whether it works inside `query` and inside `form`.
27. Why does an authorisation check in `handle` based on `event.url.pathname.startsWith('/admin')` not protect an admin `query`? Where should the check be?
28. Name two ways a user’s identity can change while a client-side query cache still holds the previous user’s data, and how you would handle it.
29. Which remote function types can receive `File` arguments, and which cannot?
30. You rename `posts.remote.ts` to `articles.remote.ts` and deploy with a rolling update. Describe what stale clients experience and how SvelteKit helps you detect it.
