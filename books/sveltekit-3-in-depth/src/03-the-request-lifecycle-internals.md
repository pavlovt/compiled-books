# Chapter 2: The Request Lifecycle Internals

Almost every production question about SvelteKit reduces to “where in the lifecycle did that happen, and who saw it?”. Why did my `handle` hook not run for that image? Why is my cookie missing on the first client-side navigation? Why did a user see a stale page after a deployment? This chapter follows a request through the framework in the order the code executes it: from the adapter, through `server.respond`, the `reroute` hook, route matching, `handle`, the page renderer or endpoint, and out as a `Response`; then it follows the browser through client startup, hydration and a client-side navigation. It ends with version skew detection and a map of where tracing hooks in. The descriptions here come from reading the 3.1.0 runtime source and from instrumenting a real app, and where a trace is shown it was captured from a SvelteKit 3.1.0 minimal project.

The goal is a mental model you can apply to bugs you have not seen yet. Chapter 4 and Chapter 5 build on it for data loading, and Chapter 9 for hooks.

## From the platform to `server.respond`

A built SvelteKit server is a generated module with two entry points:

```ts
server.init({ env, read }): Promise<void>
server.respond(request: Request, options: { getClientAddress(): string; platform?: unknown }): Promise<Response>
```

`init` is called once per process (or isolate). Internally it configures module-level state (the manifest, the asset-reading function, the environment) and then imports the runtime, which in turn loads your `src/hooks.server.ts` and universal hooks exactly once, however many times an adapter calls `init`. If your `init` hook exists, it runs here, before the first request is served; an exception thrown from it fails initialization. Treat the `init` hook as the place for one-time setup such as opening a connection pool, and remember that on serverless platforms “once” means once per cold start.

`respond` is called for every request. The adapter’s job is purely translation:

- Node: `getRequest` builds a `Request` from `IncomingMessage` (this is synchronous in 3.x), and `setResponse` pipes a `Response` into `ServerResponse`. adapter-node adds its own static-file handling and compression in front.
- Cloudflare, Netlify, Vercel: the platform already gives you `Request`/`Response`, and the adapter adds `platform` data (bindings, context) and a `getClientAddress` implementation.

Two consequences follow. First, anything the adapter’s own handler serves never reaches `respond`: static assets, precompressed files, and prerendered pages are usually served by the adapter or platform before Kit is consulted. Second, `getClientAddress()` is adapter-specific; calling it on an adapter that cannot provide it throws a descriptive error naming the adapter.

## The kinds of requests

A SvelteKit server answers more kinds of requests than the URL space of your routes suggests. It is worth enumerating them, because each takes a different path through `respond`.

| Kind | How it is recognised | Reaches `handle`? |
|------------------------|------------------------|------------------------|
| Page document | `GET`/`HEAD` for a route with a `+page`, `Accept` prefers HTML | Yes |
| Action POST | `POST` to a page route (`?/name`), non-JSON or JSON (enhanced) | Yes |
| Data request | Pathname ends in `/__data.json`; carries `x-sveltekit-invalidated` | Yes (`event.isDataRequest`) |
| `+server` endpoint | Any method; or `GET`/`POST` when `Accept` does not prefer HTML on a route with both | Yes |
| Remote function call | Path under the remote endpoint prefix (`/_app/remote/...`) | Yes (`event.isRemoteRequest`) |
| Sub-request | `event.fetch` from `load`, hooks or remote functions to your own app | Yes (`event.isSubRequest`) |
| Route resolution | Pathname ends in `/__route.js` (only with `router.resolution: 'server'`) | No |
| Public env module | `/_app/env.js` (only when dynamic public env is used) | No |
| Static asset | File in `static/` or immutable build output | No (served by adapter) |
| Prerendered page | HTML/JSON saved at build time | No (served by adapter) |
| Unmatched `/_app/...` | Reserved prefix, nothing there | No, 404 with `must-revalidate` |

Before drawing conclusions, let us look at what actually happens. This is a minimal instrumentation, added to a minimal project, with one dynamic page, one `+server` endpoint, and one prerendered page:

```ts
// src/hooks.server.ts
import type { Handle } from '@sveltejs/kit';

export const handle: Handle = async ({ event, resolve }) => {
    console.log(
        'handle', event.request.method, event.url.pathname,
        'data=' + event.isDataRequest,
        'sub=' + event.isSubRequest,
        'remote=' + event.isRemoteRequest,
        'route=' + event.route.id
    );
    return resolve(event);
};
```

```ts
// src/hooks.ts  (universal)
import type { Reroute } from '@sveltejs/kit/hooks';

export const reroute: Reroute = ({ url }) => {
    console.log('reroute', url.pathname);
};
```

```ts
// src/routes/posts/[id]/+page.server.ts
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, fetch }) => {
    const t = await (await fetch('/api/time')).json();
    return {
        id: params.id,
        t,
        slow: new Promise<string>((resolve) => setTimeout(() => resolve('slow'), 300))
    };
};
```

After `vite build` and `vite preview`, requesting `/posts/42`, then its data request, `/robots.txt`, the prerendered `/about`, and a missing page produced this log:

```text
reroute /posts/42
handle GET /posts/42 data=false sub=false remote=false route=/posts/[id]
reroute /api/time
handle GET /api/time data=false sub=true remote=false route=/api/time
reroute /posts/42
handle GET /posts/42 data=true sub=false remote=false route=/posts/[id]
reroute /api/time
handle GET /api/time data=false sub=true remote=false route=/api/time
reroute /nope
handle GET /nope data=false sub=false remote=false route=null
```

Notice what is *not* there: `/robots.txt` and the prerendered `/about` produced no log lines. They were served as files. Notice also what is present twice: `reroute` runs before `handle` for every request, and the internal `fetch('/api/time')` from the `load` function generated a complete second pass through `reroute` and `handle` with `isSubRequest` set. And note `route=null` for the 404: `handle` runs for unmatched URLs too, with `event.route.id === null`, which is the correct place to implement a “redirect legacy URLs” fallback. The same log, during `vite build`, also shows `handle GET /about` once while prerendering, because prerendering drives the real pipeline.

> **Warning:** Do not read `event.url.search` in `handle` for a request that may be prerendered. During prerendering `url.search` is disabled and throws “Cannot access `url.search` on a page with prerendering enabled”. Our first instrumented build failed with exactly that error and a 500 for `/about`. Guard with `building` from `$app/env` or only read it when the route is not prerendered.

## Inside `respond`: the ordered pipeline

The core function, `internal_respond`, is a long, linear function. Reading its order of operations tells you which guarantee holds at which point. The sequence below is what the 3.1.0 source does, with the consequences for you after each step.

**1. Tracing context.** If OpenTelemetry is installed, incoming trace headers are extracted so spans become children of an upstream trace.

**2. URL classification.** The URL is parsed and three flags are computed: is it a route-resolution request (`/__route.js` suffix), a data request (`/__data.json` suffix), or a remote function call (a path under the remote prefix). For data requests the suffix is stripped from `url.pathname`; the trailing slash is restored from an `x-sveltekit-trailing-slash` query parameter, and the `x-sveltekit-invalidated` parameter is parsed into a per-node boolean array (a string of `0` and `1`, one character per layout and page node). These internal parameters are then deleted from `event.url`, so your code never sees them. Your `handle` sees the *logical* URL of the page, with `event.isDataRequest === true`.

**3. CSRF checks (production only).** Remote calls are checked for cross-site origin and answered with a 403 JSON error; other requests go through the `csrf` check for form-like content types. These checks run before routing and before `handle`, so a rejected cross-site POST never reaches your hooks. The check is skipped in development, and `csrf.trustedOrigins` and `paths.origin` feed into it.

**4. Hash router guard.** With `router.type: 'hash'`, only the root URL is served by the server (it is just the SPA shell); everything else is a 404.

**5. Reserved parameters.** Any query parameter starting with `x-sveltekit-` (after the legitimate ones were removed in step 2) results in a 400.

**6. Event construction.** The `RequestEvent` is created: `cookies`, a lazy `fetch`, `getClientAddress`, an empty `locals`, `platform` (from the adapter or its emulator), `request`, `route: { id: null }` and empty `params` (both filled in later), `setHeaders`, `url`, and the three `is*Request` flags. `setHeaders` is implemented here, and so are its rules: duplicate headers are an error, except `server-timing` values, which are comma-joined; `set-cookie` is rejected.

**7. `reroute`.** The universal `reroute` hook runs with a copy of the URL (skipped for remote calls and for route-ID resolution). If it throws, the response is a plain-text 500 with no `handleError`, no `handle`, nothing. That is the one place in the pipeline where an error bypasses your error handling entirely, so `reroute` must be pure and cheap. If `reroute` changes the pathname and a prerendered file exists for the new path, that file is fetched and returned directly, bypassing `handle`.

**8. Decoding and base path.** The pathname is decoded. A malformed URI sets the path to `null`, which later becomes a 400 `Malformed URI` page, *after* `handle` has run (so the hook still observes it). If `paths.base` is set, requests outside it get a plain 404 and the prefix is stripped.

**9. Special internal responses.** Route-resolution requests are answered here by returning a JavaScript module describing the route. `/_app/env.js` returns the public dynamic env module. Any other path under `/_app/` that is not a remote call is a 404 with `cache-control: public, max-age=0, must-revalidate`, which keeps CDNs from caching misses for assets that may exist after the next deployment.

**10. Route matching.** `find_route` matches the decoded path against the manifest, using matchers from `src/params.ts`. On success `event.route.id` and `event.params` are populated. A throwing matcher results in a fatal error response.

**11. Trailing slash normalisation.** For a matched non-remote route, the effective `trailingSlash` option is read (from the page nodes or the endpoint) and the path is compared against it. A mismatch returns a `308` redirect with an `x-sveltekit-normalize: 1` header, *before `handle`*. The redirect `Location` is relative so path prefixes the app cannot see (proxies) are preserved. Data requests skip this redirect, because the client has already computed the URL it navigates to. Chapter 3 explains the option itself; the lifecycle point is that URL normalisation is not interceptable from `handle`.

**12. Adapter hooks.** If the adapter provides an `emulate().platform` function, `event.platform` is recomputed with the route’s `config` and `prerender` option. The prerenderer’s `before_handle` callback runs here too.

**13. `handle`.** Finally, the hook runs, wrapped in a root tracing span. Calling `resolve(event, opts)` continues to the renderer.

**14. Post-`handle` processing.** Once a `Response` exists: headers collected via `setHeaders` are merged into it; cookies set during the request are serialised into `Set-Cookie` headers; when prerendering, an `x-sveltekit-routeid` header is added; and if the response has an `ETag` that matches `If-None-Match` (weak `W/` prefixes ignored), a `304` is returned with a minimal set of headers (`cache-control`, `content-location`, `date`, `expires`, `vary` and any `set-cookie`). Finally, if it was a data request and your `handle` returned a 3xx `Response`, that redirect is converted into a JSON `{ type: 'redirect' }` payload, because `fetch` would otherwise follow the redirect transparently and the client router would never see it.

**15. Error and redirect catch-all.** `redirect()` thrown anywhere inside becomes the right kind of redirect response: JSON for data and remote requests, an `ActionResult` for enhanced form posts, an HTTP redirect otherwise. Any other thrown error goes to the fatal-error responder, which consults `handleError` and picks JSON, the `+error.svelte` page, or `error.html` based on the request’s `Accept`.

Two lessons stand out. First, `handle` is *not* the first code to run: CSRF, `reroute`, normalisation redirects and several early 404s happen first. Second, `handle` wraps `resolve`, and `resolve` is where almost all of the framework’s work occurs; the rest of this section is about what `resolve` does.

## Inside `resolve`: dispatching to a renderer

When your `handle` calls `resolve(event, opts)`, the options you pass replace the defaults (`transformPageChunk` passes HTML through unchanged, `filterSerializedResponseHeaders` includes nothing, `preload` includes JS and CSS). The dispatch then goes in this order:

1.  **Bad URI:** if decoding failed earlier, render the 400 error page.
2.  **Hash routing or the SPA fallback prerender:** render the empty shell page with `ssr: false` and `csr: true`, with only the root layout in the branch.
3.  **Remote call:** hand off to the remote function handler.
4.  **A matched route:**
    - **Data request** (`__data.json`): run only the server `load` functions for invalidated nodes and return the data protocol response (below).
    - **Endpoint or page.** A `+server` handler is used when the route has no page, or when the route has both and the request is judged an endpoint request (not a `text/html`-preferring `GET`/`HEAD`/`POST`; `PUT`, `PATCH`, `DELETE`, `OPTIONS` and `QUERY` always go to the endpoint). A subtle fallback exists: if the route has both and the endpoint cannot handle this `GET`, `HEAD` or `POST` (no matching export and no `fallback`), the page renders instead.
    - **Page** for `GET`, `HEAD`, `POST`: render it. For other methods the response is a 204 `OPTIONS` reply with an `allow` header, or 405.
    - After either, if the route has both a page and an endpoint and the method is `GET` or `HEAD`, `Vary: Accept` is appended, because the same URL can return different content types.
5.  **No matched route:** if this is a sub-request that is itself failing, it is proxied; if a request came directly from a user (depth 0) and is a non-HTML `Sec-Fetch-Dest` (image, script, style, and so on), it receives a plain `404 Not Found` with `Vary: Sec-Fetch-Dest` rather than a full HTML error page; otherwise the 404 error page is rendered. Inside prerendering, a plain `404`.
6.  **A `finally` block** replaces `event.cookies.set` and `event.setHeaders` with functions that throw. Setting cookies or headers after the response has been produced is an error rather than a silent no-op. This is why you must not call `setHeaders` from code that runs after `resolve` returns.

## The SSR render pipeline for a page

`render_page` is where load functions, actions and rendering meet. Its structure is the best description of when your code runs.

**Guards.** A request depth above 10 returns a 404 to break infinite fetch cycles (a `load` that fetches its own page). An enhanced action request (`x-sveltekit-action: true`, JSON accept) is handled entirely by the action handler and returns JSON.

**Actions first.** For a `POST` to a page, the action runs before any `load` function. Its result (`success`, `failure`, `redirect` or `error`) determines the response status: `failure` uses its own status, an `error` its error’s status, and a `redirect` returns immediately. Chapter 6 covers actions; the lifecycle point is that `load` functions run *after* the action in the same request, so they see its effects, but `handle` ran before it and its `locals` are not refreshed.

**Prerender decision.** The page’s `prerender` option is resolved from the node chain. Pages with actions cannot be prerendered. While prerendering, a page that is not prerenderable returns a bare 204 so the crawler moves on.

**SSR off.** If `ssr` is `false` (and the page is not being prerendered with server data), no `load` function runs on the server at all. The response is an empty shell, but the branch of nodes is still included so that stylesheets and fonts are linked in the head before client-side rendering takes over.

**Loading data, in parallel.** For SSR, two promise arrays are created, one per node. The first runs each node’s *server* `load`, the second each node’s *universal* `load` (which awaits the server promise of the same node to supply `data`). All start concurrently. The only ordering comes from `parent()`: a server `parent()` awaits the earlier server nodes and merges their `data`; a universal `parent()` awaits earlier universal results. After scheduling, the code attaches no-op catch handlers to every promise to avoid unhandled-rejection crashes, and then awaits results node by node from the root layout downward. The first failure wins:

- A thrown `redirect` becomes an HTTP redirect (and, while prerendering, also a stored JSON redirect so the client router can follow it).
- Any other error is normalised, passed to `handleError`, and the nearest `+error.svelte` *above the failing node* is rendered with the successfully loaded layouts above it. If the failure happened in the root layout, none exists, and the static `error.html` is returned. Chapter 10 treats this fully.

Notice that one layout failing does not stop sibling loads from *starting*; it only changes what is rendered. If a layout’s server `load` throws, the page’s `load` may already have run, and its results are discarded. This is the root of the documented warning that layout-level auth checks are not sufficient to protect page loads.

**Rendering.** `render_response` assembles the page:

1.  The branch’s data is merged from root to leaf into a single `page.data` object (later keys win), and a render tree of components is built.
2.  Svelte’s `render` is called with a context carrying the `page` object, a CSP hash/nonce configuration, and a `transformError` function that sends component rendering errors to `handleError` (when `+error.svelte` boundaries exist). In development, a global `fetch` guard warns when relative URLs or non-SvelteKit `fetch` are used during rendering.
3.  The rendered `head` and `body` are combined with stylesheets, modulepreload links, font preloads and inlined CSS (files under `inlineStyleThreshold`). Modulepreloads are placed as `<link rel="modulepreload">` tags; with `output.linkHeaderPreload` enabled they go in a `Link` header instead, but never for prerendered pages.
4.  For `ssr && csr` pages, each `fetch` response that was captured during universal loads is appended as a `<script type="application/json" data-sveltekit-fetched data-url="...">` element (more on those below).
5.  For `csr` pages, a boot `<script>` is appended. It sets up a global `__sveltekit_<hash>` object (`base`, `version`, optionally `assets`, `env`, and deferred-promise helpers), then imports the client entry, calls `kit.init(...)` and `kit.start(app, element, { node_ids, data, form, error, status?, params?, server_route? })`. With `bundleStrategy: 'single'` or `'inline'` the same logic is inlined.
6.  A CSP header is produced for dynamic pages (or a `<meta http-equiv>` tag for prerendered pages).
7.  `app.html` is filled: `%sveltekit.head%`, `%sveltekit.body%`, `%sveltekit.assets%`, `%sveltekit.nonce%`, `%sveltekit.env.[NAME]%` and `%sveltekit.version%` are substituted.
8.  `transformPageChunk({ html, done: true })` is called. Today it is invoked **once** with the complete document and `done: true`; the source contains a TODO about flushing chunks earlier. Do not rely on it as a streaming hook, and do not assume it is called several times.
9.  For non-streaming pages an `ETag` header (a hash of the final HTML) is set; this is what feeds the `304` logic described earlier. Streaming pages have no `ETag`.

### The hydration payload and deferred data

Look at the real boot script from `/posts/42`:

```html
<script>
    {
        const deferred = new Map();

        __sveltekit_1pb5i3 = {
            base: new URL("..", location).pathname.slice(0, -1),
            version: "1792442575475",
            defer: (id) => new Promise((fulfil, reject) => { deferred.set(id, { fulfil, reject }); }),
            resolve: async (id, fn) => { /* settles deferred promise `id` */ }
        };

        const element = document.currentScript.parentElement;

        import("../_app/immutable/entry/start.B0hWEwK7.js").then(async (kit) => {
            kit.init(__sveltekit_1pb5i3);
            const app = await import("../_app/immutable/entry/app.VNLI3AFL.js");
            kit.start(app, element, {
                node_ids: [0, 4],
                data: [null, { type: "data",
                    data: { id: "42", t: { now: "T" }, slow: __sveltekit_1pb5i3.defer(1) },
                    uses: { params: ["id"] } }],
                form: null,
                error: null
            });
        });
    }
</script>
```

Several design decisions are visible here.

- **`base` is relative.** Because `paths.relative` defaults to `true`, the base is computed from `location` (`new URL("..", location).pathname.slice(0, -1)`), which keeps the app functional behind path-rewriting proxies or when served from a static archive. The preload links in the head are likewise relative (`../_app/immutable/...`).
- **Server data is inlined as a JavaScript expression**, via `devalue.uneval`, not as JSON. That is why server `load` data can contain `Date`, `Map`, `BigInt`, repeated references and custom `transport` types, and why a non-serialisable value fails the request with a descriptive message that includes the path inside the data (for example `data.user.avatar`).
- **`data` is an array aligned with `node_ids`.** Node 0 is the root layout; its `null` indicates it has no server data. `uses` records what the server `load` touched (`params: ["id"]`), which the client needs later to decide whether to refetch.
- **Promises become `defer(id)` placeholders.** The `slow` promise was not awaited by `load`, so the initial HTML did not wait for it. The response is a chunked stream, and after the document’s closing tags, a second script arrives when the promise settles:

```html
</html>

<script>__sveltekit_1pb5i3.resolve(1, () => ["slow"])</script>
```

The client’s `resolve` helper retries on a zero-delay timer until the matching `defer(1)` call has registered, which guards against the order in which scripts evaluate. These chunk scripts appear *after* `</html>`, which browsers tolerate. A rejected promise is serialised the same way, with the error already passed through `handleError`; a value that cannot be serialised becomes a rejection with an explanatory error. When any promise exists, the response has no `ETag` and no `Content-Length`, because it is streamed. Chapter 5 returns to the consequences.

Before you read on, note the difference from universal `load` fetches: calls made with the `fetch` given to a server `load` are *not* inlined in the HTML (our trace’s `/api/time` response appears nowhere in the document). Only universal `load` fetches are captured into `data-sveltekit-fetched` scripts, because only the browser’s rerun of a universal load needs to replay them. The inlined entries carry the URL, request hash (when headers or a body were sent), status and filtered headers, and a `data-ttl` derived from `s-maxage` or `max-age` minus `age` (skipped when prerendering, for non-`GET`, or with `Vary: *`).

## Data requests: the `__data.json` protocol

When the client navigates and needs fresh server data, it calls the same URL with `/__data.json` appended to the pathname. The request carries one query parameter, `x-sveltekit-invalidated`, a string such as `01` with one digit per node of the route (layouts then page): `1` means “the server `load` for this node is invalid, rerun it”, `0` means “reuse”. Our trace requested `/posts/42/__data.json?x-sveltekit-invalidated=01` and received:

```text
HTTP/1.1 200 OK
cache-control: private, no-store
content-type: text/sveltekit-data
x-sveltekit-version: 1792442575475
Transfer-Encoding: chunked

{"type":"data","nodes":[{"type":"skip"},{"type":"data","data":[{"id":1,"t":2,"slow":4},"42",{"now":3},"T",["Promise",5],1],"uses":{"params":["id"]}}]}
{"type":"chunk","id":1,"data":["slow"]}
```

The format is newline-delimited JSON:

- The first line is `{"type":"data","nodes":[...]}`. Each node is `{"type":"skip"}` (not invalidated), `{"type":"data","data":<devalue>,"uses":{...}}`, `{"type":"error","error":...}`, or `null` (no server load). The `data` field uses `devalue.stringify`’s flat array format, here with a `["Promise", 5]` entry standing for a deferred value.
- Later lines are `{"type":"chunk","id":N,"data":...}` or `"error":...` for each deferred promise, in resolution order.
- A redirect is a single `{"type":"redirect","status":307,"location":"..."}` JSON body with HTTP status 200; an error response keeps the error’s status with a JSON body.

Headers matter here. `cache-control: private, no-store` is always set so intermediaries never cache these personalised payloads. The content type is `application/json` for non-streaming responses (so you get `Content-Length` and browser JSON viewing) and the proprietary `text/sveltekit-data` for streamed ones, chosen specifically to prevent proxy buffering. And `x-sveltekit-version` carries the build version for skew detection.

Two details explain real bugs. A route with no `+page` answers `/__data.json` with 404, since only pages have data nodes. And because `handle` sees the data request with the *normal* pathname, `locals` and auth logic apply identically to document and data requests, which is exactly why guards belong in `handle`, not in assumptions about navigation type.

## Prerendered pages and static assets

When a page is prerendered, `vite build` drives the same pipeline at build time: it starts the server module, requests entry pages, follows links found in the HTML (crawl), and stores responses. During this process `handle` runs (we saw `handle GET /about` in the build log), `building` is true, `event.url.search` is disabled, and a sub-request’s response is recorded so that anything the page fetched becomes a static file too. Server `load` data for prerendered pages is stored as a `__data.json` file as well, so client-side navigation to a prerendered page still gets its data without a server. At runtime the adapter or platform serves those files directly, which is why `handle` does not see them. Chapter 11 covers the mechanics.

There is one place where Kit itself consults the prerendered set: sub-requests. When a `load` function fetches a path that is a prerendered file, the internal `fetch` makes a *real* HTTP request instead of dispatching in-process, because the same path might also match a dynamic route that exists in the manifest, and serving the wrong one would be wrong. For static assets (files in `static/` or server assets bundled into the build), the internal `fetch` reads the file directly through `read` when available.

## Internal `fetch` and `handleFetch`

The `fetch` you receive in `load`, hooks and remote functions is created per request and routes through `handleFetch`. For a same-origin URL inside `paths.base` that is not a static asset or a prerendered path, it:

- copies `cookie` (from the browser’s cookies plus any `Set-Cookie` produced earlier in this request) and `authorization` headers, unless `credentials: 'omit'`;
- sets `accept: */*` and forwards `accept-language` if the caller did not set them;
- calls `respond` *directly* with a forked per-request state and an incremented depth. No network is involved. This is why your `handle` ran a second time for `/api/time`;
- absorbs any `Set-Cookie` headers from the sub-response back into the parent’s cookie jar, so a cookie set by the internal endpoint is visible to later fetches and is sent to the browser.

For cross-origin URLs, cookies are forwarded only when the target host equals or is a subdomain of the app’s host (`api.example.com` does not receive cookies from `my.example.com`; `sub.my.example.com` does), and only when `credentials` is not `omit`. The rest is a plain platform `fetch`. Chapter 4 covers the developer-facing semantics; here the lifecycle fact is that sub-requests are real, complete requests inside the process, and they cost a `reroute`, a `handle` pass and a route match each.

## The client: startup

The server’s work ends with the HTML. The browser then follows this sequence, from `client.js`:

1.  **Entry.** The boot script imports the client entry module (`start.<hash>.js`) and calls `init(global)`, which stores the payload (`base`, `version`, `env`, `defer`…) before importing the rest of the client, so that modules such as `$app/paths` can read it during their own initialisation. It then dynamically imports the generated app module (`app.<hash>.js`), which contains the node loaders, hooks and matchers, and calls `start(app, element, hydrateOptions)`. (With `bundleStrategy: 'single'` the entry is one file and the `init` step happens inline.)
2.  **Remote data seeding.** If the payload includes remote function results rendered into the page (Chapter 7), they are stored in the client’s caches before anything runs.
3.  **Credential URL check.** If the document URL carries basic-auth credentials, the page reloads without them.
4.  **Transport and `init`.** The universal `transport` hook is installed, then the client `init` hook is awaited. Because hydration waits for `init`, a slow `init` delays interactivity; keep it fast and put long work behind your own async state.
5.  **Route table.** With client-side routing, the route list is parsed from the app dictionary (route IDs compiled to regexes plus node loaders). The root layout and root error node are imported eagerly so that a connectivity failure after startup cannot leave the app without an error page.
6.  **History bootstrap.** If there is no Kit entry in `history.state`, one is created with a fresh index, and a saved scroll position (from a reload or tab restore) is recovered.
7.  **Hydration.** `_hydrate` takes the server’s `node_ids` and data. It resolves `params` and `route` on the client (`get_navigation_intent`, including the client `reroute` hook), and for each node calls `load_node`, which runs the universal `load` (if any) with the server data attached as `data`. Fetches made inside that `load` are answered from the `data-sveltekit-fetched` scripts through the initial-fetch cache rather than the network, honouring `data-ttl` and matching on URL plus request hash. If hydration loading throws, the root error page is rendered and the target is cleared (`should_hydrate` is false), i.e. a client-side render replaces the SSR markup.
8.  **Mount.** Svelte’s `hydrate` (or `mount` when SSR was off) attaches to the markup. After a microtask (so that async Svelte component scripts have started), `afterNavigate` callbacks run with `type: 'enter'`, snapshots are restored, and the router is marked started.
9.  **Router start.** `_start_router` installs `beforeunload` (persisting scroll and snapshots to `sessionStorage` and firing `beforeNavigate` with `type: 'leave'`), `visibilitychange` and `focus` (version checks, described below), preload listeners (skipped when `navigator.connection.saveData` is true), the container click handler, `popstate` and `hashchange` handling.

The distinction between steps 7 and 8 explains a common surprise: a universal `load` runs *again* in the browser during hydration even for server-rendered pages, but its `fetch` calls do not hit the network. A load function with side effects other than `fetch` will run twice.

## The client: a navigation, step by step

A click on an internal link travels through the router like this.

**Interception.** The click handler ignores modified clicks (meta, ctrl, shift, alt), non-primary buttons and already-prevented events; finds the nearest `<a>`; and bails out for `download`, other `target`s, non-HTTP(S) schemes, external origins and `data-sveltekit-reload`. In those cases `beforeNavigate` still fires (type `link`), so you can intercept a full-page navigation, but the browser performs it. Same-page hash links defer to native behaviour to preserve `hashchange`.

**Intent.** `get_navigation_intent` runs the client `reroute` hook (results are cached per URL string, so `reroute` must be idempotent), then loops the route table for the first matching regex, producing `{ id, route, params, url }`. In `router.resolution: 'server'` mode, it instead imports `<pathname>/__route.js`, which the server answers in the early step 9 of `respond` (no `handle` involved). If no route matches and the URL is internal, the navigation falls back to a server request; if the reroute hook throws, the client does a full page load.

**`beforeNavigate`.** Callbacks run with a `cancel()` function; if any cancels, the navigation is aborted and pending tokens restored. `beforeNavigate` is also called for `leave` navigations when the page unloads.

**Load.** `load_route` computes what to reload. It first checks the preload cache: if a hover or tap preload for the same page key is in flight or done, that promise becomes the real navigation. Otherwise it eagerly starts importing node modules (so code loading does not wait behind data). For every node with a server `load`, it decides validity: the node is invalid if its loader changed (a different route), or its recorded `uses` indicate a change (a used `param` differs, `url` or a tracked search param changed, `parent` changed upstream, a dependency matched an invalidation, or `force_invalidation` is set). All invalid server nodes are fetched in *one* `__data.json` request, with the invalidation bitmask. The response header `x-sveltekit-version` is observed here. Then universal loads run in parallel with the same validity logic against their own `uses`, reusing previous results for valid nodes. Chapter 5 details the tracking.

**Outcomes.** A redirect restarts navigation up to 20 hops (the Fetch specification’s limit) and then renders a redirect-loop error. An error result renders the nearest error boundary; for a status of 400 or above, or for failed node imports, the router first calls `updated.check()` and, if a newer deployment exists, falls back to a full-page navigation to the target so the user receives the new build instead of an error from a skewed one.

**Commit.** If the navigation is still current (a newer one would have changed the token and rejected this one with “navigation aborted”), the new `history` entry is created (`pushState` or `replaceState`, with serialisable `state` and Kit’s metadata), scroll for the old entry and snapshots are captured, and `onNavigate` callbacks run (this is where View Transitions hook in; the function they return runs after the update). The new `page` state is applied, focus is blurred from the old element before the DOM changes, and the component tree updates; boundaries that failed previously are reset once the new props have flushed. The router waits for Svelte to settle.

**Finish.** `finish_navigation` restores scroll (or resets to top), resets focus (unless `reset: false` or `data-sveltekit-reset="false"`), clears `navigating`, resolves the navigation’s `complete` promise, records the final scroll in `to.scroll`, and calls every `afterNavigate` callback.

The ordering is the point: `beforeNavigate` happens before loading, `onNavigate` after loading but before the DOM update, and `afterNavigate` after the DOM has settled. Chapter 12 uses this for view transitions and scroll behaviour.

## Version skew detection

A static client bundle can outlive the server it was built against: the user keeps a tab open across a deployment. The next navigation then requests chunk filenames that no longer exist, or data in a shape the old code does not expect. SvelteKit has several defences.

**The version.** Every build has a `version.name`, which by default is a timestamp (our trace shows `1792442575475`); set it from your commit SHA for reproducibility, or for platforms that implement skew protection:

```ts
// vite.config.ts
sveltekit({
    version: {
        name: process.env.GIT_SHA ?? Date.now().toString(),
        pollInterval: 5 * 60_000 // default is 3_600_000 (1 hour); 0 disables polling
    }
})
```

It is embedded in the page (`version` in the boot payload, `%sveltekit.version%` in `app.html`) and written to `/_app/version.json`.

**Passive detection.** Server responses for data requests (and, in 3.x, remote function calls and form action responses) carry `x-sveltekit-version`. When the client sees a different value, `updated.current` flips to `true`. The `notify_version` path deliberately does not reset the poll timer, because on platforms with skew protection an old server instance may legitimately keep answering with the old version string.

**Active detection.** `updated.check()` fetches `/_app/version.json` with `cache-control: no-cache` and compares. It is invoked on a timer (`pollInterval`), when the tab becomes visible, and on window `focus`. A failed or non-OK check returns `false`, and the polling timer is rescheduled until an update is found.

**Recovery.** A navigation that fails because a route node cannot be imported (a non-HTTP error during `load_node`) triggers `updated.check()`; if the version changed, the client updates the service worker (if present) and performs a full-page navigation to the target. The same applies to an error-status result. So even if you do nothing, many skew failures recover into a reload.

In dev, `check()` always returns `false`, and with `bundleStrategy: 'inline'` version checks are disabled because there are no chunks to go stale.

To use the signal yourself, prefer a non-blocking nudge:

```html
<!-- src/routes/+layout.svelte -->
<script lang="ts">
    import { page, updated } from '$app/state';
    import { beforeNavigate } from '$app/navigation';

    let { children } = $props();

    // Reload on next navigation rather than interrupting the user now.
    beforeNavigate(({ willUnload, to }) => {
        if (updated.current && !willUnload && to?.url) {
            location.href = to.url.href;
        }
    });
</script>

{#if updated.current}
    <aside role="status">
        A new version is available. <button onclick={() => location.reload()}>Reload</button>
    </aside>
{/if}

{@render children()}
```

> **Senior tip:** Skew is also a *server* concern. During a rolling deployment two versions serve traffic simultaneously, and a client from the old build may hit a new server (or the reverse). Combine unchanging, immutable asset paths (the default `_app/immutable/` with content hashes), `version.name` from your CI, and your platform’s skew protection (Vercel offers it) so an old client keeps talking to its own build.

## Where tracing hooks in

Chapter 17 covers observability in depth. For lifecycle purposes, here is where spans are emitted when you enable `tracing: { server: true }` in the plugin options (and have `@opentelemetry/api` installed):

| Span | Emitted | Parent |
|------------------------|------------------------|------------------------|
| `sveltekit.handle.root` | Around the whole `handle` call, after routing and before post-processing. Attributes: `http.route`, `http.method`, `http.url`, `sveltekit.is_data_request`, `sveltekit.is_sub_request`; later `http.response.status_code`. | Incoming trace context, if any |
| `sveltekit.handle.sequenced.<name or index>` | One per handle in `sequence(...)` | Nested, root first |
| `sveltekit.resolve` | Around `resolve(event, opts)` | `handle` span |
| `sveltekit.load` | Each server `load` and each universal `load` run on the server. Attributes `sveltekit.load.node_id`, `node_type`, `environment: 'server'` | `resolve` |
| `sveltekit.form_action` | Each form action | `resolve` |
| `sveltekit.endpoint` | `+server` handlers (new in 3.1) | `resolve` |
| `sveltekit.remote.call`, `sveltekit.remote.form.post` | Remote function invocations | `resolve` |

Three facts about that placement are useful in practice. Work done *before* `handle`, namely CSRF checks, `reroute`, normalisation redirects and route matching, is outside any Kit span, so a slow `reroute` shows up as unexplained gap time before the root span. Trace context propagation reads standard headers (`traceparent`) at the very top of `respond`, so a traced upstream proxy connects naturally. And `event.tracing` (`enabled`, `root`, `current`) lets you annotate the active span; the `load` event gets a `tracing` object too, so a server `load` can add attributes to its own span. Client-side navigation is *not* traced by this mechanism; the client `load` receives a no-op tracing object (`enabled: false`).

## A diagnostic `handle` you can keep

The following hook classifies every request and emits `Server-Timing`, using only public API. It is a good local tool for confirming the claims in this chapter on your own app.

```ts
// src/hooks.server.ts
import type { Handle } from '@sveltejs/kit';

function kind(event: Parameters<Handle>[0]['event']): string {
    if (event.isRemoteRequest) return 'remote';
    if (event.isDataRequest) return 'data';
    if (event.isSubRequest) return 'sub';
    if (event.route.id === null) return 'unmatched';
    if (event.request.method === 'POST' && event.route.id !== null) return 'post (action or endpoint)';
    return 'document-or-endpoint';
}

export const handle: Handle = async ({ event, resolve }) => {
    const start = performance.now();
    const response = await resolve(event);
    const ms = (performance.now() - start).toFixed(1);

    // Server-Timing is one of the headers setHeaders may append to, but here
    // we already have a Response, so mutate its headers.
    response.headers.append('server-timing', `app;dur=${ms};desc="${kind(event)}"`);
    return response;
};
```

(Classification flags exist for data, sub and remote requests, but not for “action POST”; you infer it from the method, the matched route and the `?/name` search key. For enhanced requests, the `x-sveltekit-action: true` request header is a reliable marker.)

Be aware that `resolve` returns a response whose headers may be immutable in some situations (for instance, a response passed through `fetch`). If you see a `TypeError` mutating headers, construct a new `Response(response.body, response)` first; Kit does this itself for proxied responses.

## Putting it together: debugging by lifecycle position

The following questions are answered by locating the symptom in the pipeline.

- *“`handle` did not run for my page.”* The page was prerendered (served as a file), the request hit a static asset, or an adapter/CDN answered it. Check `prerender` and the adapter’s static handling.
- *“`handle` runs more than once per page view.”* Sub-requests from `load` (`isSubRequest`), data requests when navigating, remote calls, and favicon or asset 404s that fall through. Filter with the flags.
- *“My redirect for `/foo` to `/foo/` never fires in `handle`.”* Trailing slash normalisation happens in step 11, before `handle`.
- *“A 500 with the text ‘Internal Server Error’ and no logging.”* A throw in `reroute` (step 7).
- *“I set a header in `handle` but the cached copy lacks it.”* Headers from `setHeaders` and cookies are merged after `handle`; a `304` response keeps only specific headers.
- *“Streaming data arrives all at once.”* The platform or a proxy buffers (Lambda-style adapters; NGINX with buffering on); the framework sent a chunked response with a `text/sveltekit-data` or HTML stream.
- *“After deploy, users get errors until they reload.”* Version skew; see the recovery rules and set `version.name` and skew protection.
- *“The page flashes or loses state on first interaction.”* The universal `load` ran again on hydration, or the client `init` hook was slow.

## Key takeaways

- A SvelteKit server exposes `server.init` (once) and `server.respond(Request) -> Response`. Adapters only translate to and from the platform; static assets and prerendered pages are normally served before Kit is called, so `handle` never sees them.
- `respond` is a linear pipeline: classify the URL (page, data, remote, route-resolution), run CSRF (production), build the `RequestEvent`, run `reroute`, match routes, normalise trailing slashes (a `308` before `handle`), then call `handle`, then merge headers and cookies, honour `ETag`/`304`, and convert redirects for data requests.
- `reroute`, CSRF and trailing-slash redirects happen before `handle`; an error thrown in `reroute` yields a bare 500 that bypasses `handleError`.
- Server `load` and universal `load` for all nodes start concurrently; only `parent()` orders them. Actions run before `load` in the same request. A failing node renders the nearest `+error.svelte` above it, or `error.html` for the root layout.
- The HTML contains server data as devalue-serialised JavaScript, deferred promises as `defer(id)` placeholders that resolve through trailing `<script>` chunks, and captured universal `fetch` responses as `data-sveltekit-fetched` JSON scripts. `transformPageChunk` is currently called once with the full document.
- Client navigations request `__data.json` with an `x-sveltekit-invalidated` bitmask; the response is `application/json` or streaming NDJSON (`text/sveltekit-data`) with `cache-control: private, no-store` and an `x-sveltekit-version` header.
- Internal `fetch` dispatches into `respond` in-process, with a forked state and incremented depth, so each sub-request runs `reroute`, route matching and `handle` again; cookies and `authorization` are forwarded, and `Set-Cookie` from sub-responses is absorbed.
- Client startup awaits the `init` hook before hydrating, reruns universal `load` against inlined fetch responses, and then starts the router. A navigation runs `beforeNavigate`, then loading (preload cache, one batched data request), then `onNavigate`, the DOM update and `afterNavigate`.
- Version skew is handled with `version.name`, the `x-sveltekit-version` header, `/_app/version.json` polling (`pollInterval`, focus, visibility) and an automatic full-page reload when a navigation fails after a deployment.
- With `tracing.server`, spans cover `handle`, `resolve`, `load`, actions, endpoints and remote functions, but not the work before `handle` and not the client.

## Review Questions

1.  List the two methods of the generated server object and say which is called once and which per request.

2.  A prerendered `/about` page and a file in `static/` never trigger your `handle` hook in production. Why, and what does `handle` see during `vite build`?

3.  In the trace in this chapter, why did `handle` run for `/api/time` even though the browser never requested it? Which `RequestEvent` flag identifies that case?

4.  **What does this log?** Suppose `/posts/42` is a dynamic page whose server `load` calls `event.fetch('/api/time')`, and a user opens it directly, then clicks a link to `/posts/43`. Given the hooks from this chapter, how many `handle` invocations occur in total (assume `/api/time` is called by each load), and how many have `isDataRequest` true?

5.  Put these in the order they execute for an incoming page request in production: (a) `handle`, (b) `reroute`, (c) trailing-slash `308`, (d) CSRF origin check, (e) route matching, (f) `ETag`/`304` processing.

6.  Find the bug: a developer implements “redirect `/products` to `/products/`” inside `handle` using `event.url.pathname`, but the redirect never triggers and the browser is already being redirected. Explain what is happening.

7.  What happens if the `reroute` hook throws on the server? Which hooks are bypassed, and what does the user see?

8.  **Multiple choice.** An internal `fetch('/api/data')` in a server `load` results in:

    a.  A real HTTP request to the same host
    b.  A direct in-process call to `respond` with `isSubRequest: true`
    c.  A direct call to the `GET` function in `+server.ts`, bypassing `handle`
    d.  A cached response from the previous request

9.  Explain the difference in how `fetch` responses are treated when made from a server `load` versus a universal `load` during SSR. Where in the HTML do the latter appear?

10. Why does `transformPageChunk` in a `handle` hook not give you true streaming of the HTML in 3.1?

11. What is the purpose of the `x-sveltekit-invalidated` parameter, and what does a value of `101` mean for a route with two layouts and a page?

12. Describe the three possible shapes of a node in a `__data.json` response and the meaning of each.

13. Why are `__data.json` responses `cache-control: private, no-store`, and why is the streaming content type `text/sveltekit-data` rather than `application/json`?

14. **Design question.** A page’s server `load` returns `{ post: await getPost(), comments: getComments() }` (not awaited). Describe what the browser receives, in order, and why the response has no `ETag` or `Content-Length`.

15. A layout `+layout.server.ts` throws `error(401)` and a page `+page.server.ts` in the same route reads from the database. Does the page `load` execute? Does the user see its data? What does this imply for authorization design?

16. Order these client startup steps: (a) hydration, (b) `init` hook awaited, (c) router listeners installed, (d) `afterNavigate` with type `enter`, (e) remote-data cache seeded from the payload.

17. Why can a universal `load` run twice for a server-rendered page, and why does that not double the network traffic of its `fetch` calls?

18. **Multiple choice.** On a client-side navigation, which callback runs after data has loaded but before the DOM is updated?

    a.  `beforeNavigate`
    b.  `onNavigate`
    c.  `afterNavigate`
    d.  `$effect.pre` in the page

19. How many redirects will the client router follow during one navigation before reporting a redirect loop, and where does that number come from?

20. Under what conditions does SvelteKit automatically recover from a failed client navigation by doing a full-page load?

21. What is the difference between the passive and active mechanisms of version detection? Which of them does not reset the poll timer, and why?

22. **What does this print?** A deployment has `version: { pollInterval: 0 }`, the user keeps the tab open and never navigates, and the tab is never refocused. After a deployment, can `updated.current` become `true`? Explain which mechanisms are disabled and which are not.

23. A request with the query parameter `?x-sveltekit-foo=1` arrives. What happens and why?

24. A teammate says “the `sveltekit.handle.root` span covers the entire request, so I can see slow CSRF and `reroute` time in it”. Is that right? What does the trace actually cover?

25. **Design question.** You must add a locale-detection redirect (`/` to `/en/`) and a maintenance mode that returns 503 for every dynamic route but not for static assets. For each, say which pipeline stage you can implement it in and what you cannot intercept.
