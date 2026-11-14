# Answers to Chapter Review Questions

## Chapter 1: What SvelteKit 3 Is: Architecture and Toolchain

1.  (a) Svelte, the compiler. (b) The Vite plugin (`@sveltejs/kit/vite`), which scans `src/routes` and generates the manifests and types. (c) The adapter (`adapter-netlify`), invoked at the end of `vite build`.

2.  `server.init({ env, read })` is called once at boot to hand the platform’s environment and file-reading implementation to the runtime. `server.respond(request, { getClientAddress })` is called per request: it takes a web-standard `Request` and returns a `Response`.

3.  The adapter, not Kit, owns the listener and translates the platform request into a `Request`. Values such as `event.url.origin` are derived from what the adapter passes (and proxy headers), so a wrong origin is usually an adapter or proxy configuration problem (for example `paths.origin` or the `PROTOCOL_HEADER`/`HOST_HEADER` variables of adapter-node), not a routing bug.

4.  `svelte.config.js` is no longer read at all; options in it are silently ignored. They must move into `sveltekit({...})` in `vite.config`, with `kit.*` flattened to the top level (`npx sv migrate sveltekit-3` automates it).

5.  Kit consumes `adapter` and `experimental.remoteFunctions` (plus any other flag it recognises). Forwarded to `vite-plugin-svelte`: `preprocess`, `compilerOptions` and `inspector`; any unrecognised `experimental` key would also go there, since `experimental` is split key by key between the two.

6.  **b.** `sveltekit({ paths: { base: '/docs' } })`. The `kit` prefix is gone; Vite’s own `base` is a different option and Kit does not read `package.json` for this.

7.  The specifier has no file extension. `"#lib/*": "./src/lib/*"` maps literally, so `#lib/format` resolves to `./src/lib/format`, which does not exist. In 3.x you must write `#lib/format.js` (TypeScript maps `.js` to the `.ts` source).

8.  `#lib` is a Node subpath import declared in `package.json` `imports`, which Node, Vite, TypeScript (bundler resolution) and Vitest all implement natively. `$lib` was a Kit-defined alias that only worked where the Kit plugin or generated tsconfig `paths` were applied.

9.  TypeScript convention for ESM: import specifiers name the output extension (`.js`), and TypeScript maps `.js` to the `.ts` source. Vite resolves the same way in dev and build; `svelte-package` rewrites such imports for libraries.

10. `paths`, `types`, `isolatedModules`, `verbatimModuleSyntax`. For example: `isolatedModules` must be true because Vite compiles one module at a time; `types` must include `"$app/types"` so generated ambient declarations (env vars, route IDs) are visible.

11. `rootDirs` tells TypeScript that `src/routes/...` and `.svelte-kit/types/src/routes/...` are merged, so `import type { PageProps } from './$types'` resolves to a generated file stored elsewhere. Without `svelte-kit sync`, `./$types` and `$app/tsconfig` would not exist, and you would see unresolved import errors and untyped `data`/`params`.

12. **c.** `src/app.d.ts` is hand-written by you (the scaffold creates it once). The others are generated.

13. A `/blog` route with a server-rendered page, a server `load`/actions file and a colocated component. `+page.spec.ts` is safe because files beginning with `+` whose names contain `test`, `spec` or `stories` are ignored by the route scanner. `PostCard.svelte` is not special.

14. Browser extensions inject elements into `<body>`; hydration would then remove or mismatch them. Kit warns in dev if the body placeholder is a direct child of `<body>`. The scaffold wraps it in `<div style="display: contents">`, which creates no layout box.

15. `%sveltekit.head%` and `%sveltekit.body%`. If either is missing the template fails validation and the build/dev server errors with a message naming the file and tag.

16. When even the root layout cannot render, for example an error in the root layout’s `load` or a failure in the error handling path. Because it is a static HTML file with only `%sveltekit.status%` and `%sveltekit.error.message%` substitutions, there is no Svelte rendering or bundled CSS available.

17. Query parameters beginning `x-sveltekit-` (rejected with status 400, “Cannot use reserved query parameter”) and the `/_app` path prefix (`appDir`).

18. It still works in 3.1 but the helper is deprecated. Prefer `Response.json({ ok: true })`, which is a platform API available on every adapter target and will not be removed in a future major.

19. A JSON response `{"name": "..."}` with `content-type: application/json`. It uses `Request`, `FormData` and `Response.json`. With no `name` field `body.get('name')` is `null`, so `?? 'world'` yields `"world"`.

20. (a) Removed. (b) Deprecated. (c) Experimental (remote functions). (d) Stable. (e) Deprecated (`files.*`). (f) Stable.

21. `experimental: { remoteFunctions: true }` in `sveltekit({...})` and `compilerOptions: { experimental: { async: true } }` (Svelte’s flag). With the Kit flag off, `*.remote.*` files cause an error.

22. Experimental APIs may change in minor releases. A wrapper module confines a signature change to one file and makes it easier to remove or replace the dependency.

23. The website expands directives in the stub (exported-snippets markers) using types and JSDoc from the source. In an installed project, check `node_modules/@sveltejs/kit/types/index.d.ts` and the runtime JSDoc in `src/runtime/app/navigation/client.js`, or use go-to-definition.

24. Use one project, deciding per route: `prerender = true` in the marketing routes’ layout, default SSR for the dashboard, and `ssr = false` in the admin area’s layout (with a fallback page if deployed statically). The two deciding configurations are the page options exported from `+layout`/`+page` files and the adapter chosen in `sveltekit({ adapter })` (which must be a dynamic adapter because of SSR).

25. Against: (1) it is still experimental in 3.1, so the API can change in a minor release and `^3.0.0` will pull the change in; (2) it requires the Svelte `async` compiler flag, a second experimental dependency. Mitigation: pin the minor (`~3.1.0`), wrap remote functions in a thin module, and keep a test suite exercising them before upgrading.

## Chapter 2: The Request Lifecycle Internals

1.  `server.init({ env, read })` is called once per process or isolate; `server.respond(request, options)` is called for every request.

2.  They are served directly as files by the adapter or platform before Kit’s `respond` is called, so `handle` never executes. During `vite build`, prerendering drives the real pipeline, so `handle` does run for the prerendered page (with `building` true and `url.search` disabled).

3.  `fetch('/api/time')` inside `load` is a sub-request. It is dispatched in-process into `respond`, which performs `reroute`, route matching and `handle` again. `event.isSubRequest` is `true` for it.

4.  Four `handle` invocations: the document request (1) plus its `/api/time` sub-request (2), then the client-side navigation to `/posts/43`, which is a `__data.json` request (3) plus its `/api/time` sub-request (4). Only one invocation (the data request) has `isDataRequest` true. The sub-requests are plain `GET /api/time` calls with `isSubRequest` true.

5.  (d) CSRF origin check, (b) `reroute`, (e) route matching, (c) trailing-slash `308` (only when the path needs normalising), (a) `handle`, (f) `ETag`/`304` processing.

6.  Trailing-slash normalisation (step 11) happens before `handle` and returns a `308`, so your hook never sees the un-normalised request. Change the `trailingSlash` page option for the route instead of redirecting in `handle`.

7.  The response is a plain-text 500 “Internal Server Error”. `handle`, `handleError` and all load functions are bypassed. That is why `reroute` must be cheap, pure and not throw.

8.  **b.** It dispatches directly into `respond` with a forked request state, so `handle` runs again, with `isSubRequest` true. (Exceptions: static assets are read directly, and prerendered paths cause a real HTTP request.)

9.  A server `load`’s `fetch` responses are not inlined in the HTML. A universal `load`’s `fetch` responses are captured and appended as `<script type="application/json" data-sveltekit-fetched data-url="...">` elements (with status, filtered headers, body and optionally `data-hash`/`data-ttl`) when the page is SSR and CSR, so hydration can replay them without network calls.

10. Because `transformPageChunk` is called once with the complete rendered document and `done: true` (the source has a TODO for flushing chunks earlier). It is a post-processing hook, not an incremental streaming one.

11. It is the per-node invalidation bitmask of a data request: one digit per layout and page node. `1` means rerun the server `load`; `0` means reuse the previous data (the response contains `{"type":"skip"}` for it). `101` means the root layout (index 0) and the page (index 2) are invalid and the middle layout is reused.

12. `{"type":"skip"}` means not invalidated, use previous data. `{"type":"data","data":...,"uses":{...}}` carries devalue-encoded data and what the load used. `{"type":"error","error":...}` carries the handled error. (A `null` entry means the node has no server `load`.)

13. They are personalised and must never be stored by shared caches. The streaming type `text/sveltekit-data` is a proprietary content type chosen so that proxies do not buffer it (they commonly buffer or compress `application/json`); the `text` prefix keeps it inspectable.

14. The browser receives the HTML with the post data and a `defer(1)` placeholder for `comments`, the page renders (e.g. a skeleton from `{#await}`), and after the closing tags a `<script>__sveltekit_x.resolve(1, () => [...])</script>` arrives when comments resolve. Since the body is streamed as the promise settles, the total length and hash are unknown, so no `Content-Length` or `ETag` can be computed.

15. The page `load` does execute, because layout and page loads start concurrently. The user does not see its data, because the first failure (the layout’s `error(401)`) decides the response and the nearest error boundary above the layout renders. Therefore a layout-only guard does not protect page loads from running; guard in `handle` or in each page load (or have pages `await parent()`).

16. (e) remote-data cache seeded, (b) `init` hook awaited, (a) hydration, (d) `afterNavigate` with `type: 'enter'`, (c) router listeners installed.

17. During hydration, the client reruns universal `load` to rebuild its data and dependency tracking. Its `fetch` calls are answered from the inlined `data-sveltekit-fetched` scripts (matching URL and request hash, subject to `data-ttl`), so no network request is made. Side effects other than `fetch` do run twice.

18. **b.** `onNavigate` runs after loading but before the DOM update (used for view transitions). `beforeNavigate` runs before loading and `afterNavigate` after the update.

19. Twenty. The router follows redirects up to that count (the Fetch specification’s limit) and then renders a redirect-loop error page.

20. When a navigation fails because a route node cannot be loaded or the result has a status of 400 or more, the router calls `updated.check()`. If the deployed version differs from the one the page was built with, it updates the service worker (if any) and performs a native, full-page navigation to the target.

21. Passive: the `x-sveltekit-version` header on data, remote and form responses compared against the page’s version. Active: `updated.check()` fetching `/_app/version.json` on a timer, tab visibility and focus. The passive path (`notify_version`) does not reset the poll timer, since on platforms with skew protection the responding server may be an older version, so polling must continue as a backstop.

22. Not through the polling timer, which is disabled, and not through visibility or focus events, which never fire. Passive detection needs a server response carrying `x-sveltekit-version`, which also never occurs without navigation or remote calls. So `updated.current` stays `false` until something triggers one of these; a manual `updated.check()` would still work.

23. The request gets a 400 “Cannot use reserved query parameter” text response, because `x-sveltekit-` is reserved for internal protocol parameters (after the legitimate ones used by data requests have been removed).

24. No. The root span is created inside the `handle` stage; CSRF checks, `reroute`, URL normalisation redirects and route matching happen before it. Time spent there appears as a gap before the span unless you add your own instrumentation. Incoming trace context is extracted before it, so the span is correctly parented upstream.

25. Locale redirect: implement in `handle` (for matched or unmatched routes via `event.url.pathname`; return a redirect `Response`) or with `reroute` if you want an internal rewrite instead of a redirect. Maintenance mode: in `handle`, return a 503 `Response` before calling `resolve`. In both cases you cannot intercept static assets or prerendered pages, which are served before Kit, nor trailing-slash `308` redirects, which happen before `handle`. For static assets and prerendered pages, enforce maintenance mode at the CDN or platform level.

## Chapter 3: Routing in Depth

1.  `/(app)/orgs/[org=slug]/settings`. The group `(app)` never appears in the URL (the URL is `/orgs/acme/settings`).

2.  No. A directory without `+page` or `+server` is not a route and is not matchable. It only contributes its `+layout` to the layout chain of descendant routes.

3.  The build fails with a route conflict error. Both pairs have the same shape once groups are removed and parameter names ignored (`[a]` vs `[b]`; `about` vs `about`), so they would match the same URLs and cannot be told apart.

4.  It matches all three. `rest` is `''` for `/a/z`, `'b'` for `/a/b/z`, and `'b/c'` for `/a/b/c/z`.

5.  (a) invalid: a rest segment is always optional, so double brackets are an error. (c) invalid: adjacent parameters must be separated. (d) invalid: escapes must be lowercase (`[x+3a]`). (b) and (e) are valid.

6.  Name the directory `src/routes/[x+2e]well-known/security.txt/+server.ts`. A directory with a leading `.` causes trouble for TypeScript, so the dot is written as the escape `[x+2e]`.

7.  Matchers must be synchronous. An async function returns a promise, and the router throws `param_matcher_async`. A matcher cannot query a database; do that in `load` and call `error(404)`.

8.  `string`, `number`, `boolean` or `bigint`; anything else throws `param_matcher_result_invalid`. `params.id` is typed `number` (the matcher’s output type).

9.  `/items/007` parses to 7, but `resolve` produces `/items/7`: two URLs for one resource. Make the matcher canonical-only, for example `/^(0|[1-9]\d*)$/`, so `String(match(s)) === s` for every accepted segment.

10. `/items/abc` fails the matcher, so the route does not match and matching falls through to `[...catchall]` with `{ catchall: 'items/abc' }`. Without a catch-all it is a 404.

11. Priority: `foo-abc`, `foo-[c]`, `[[a=x]]`, `[b]`, `[...catchall]`. For `/foo-def`, `foo-[c]` matches, as do `[b]` and `[...catchall]` (`[[a=x]]` does not, since `x` only accepts `"x"`); the winner is `foo-[c]`.

12. **b.** Specificity is determined by route shape, so a matcher raises priority whether or not a particular segment satisfies it. (c) is wrong: `x/[[y]]/z` sorts as `x/z`, not below it. (d) is wrong because rest and optional only get lowest priority when final.

13. `+page@(app).svelte`. To inherit only the root layout: `+page@.svelte`.

14. Only Svelte files can reference named layouts; using `@name` in a `.ts` module is a build error.

15. The reset removes the `(admin)` layout from that page’s component chain, and with it the layout’s `load`/guard no longer applies to the page. So it does remove that guard. Guards belong in `handle` (matching the route ID or path) or in each protected `+page.server` load, not in layouts or groups.

16. No route matched, so no route directory is entered and the root error page is used. Add `src/routes/marx-brothers/[...path]/+page.ts` whose `load` calls `error(404, 'Not Found')`.

17. `resolve('/blog/[slug]', { slug: 'a/b' })` returns `/blog/a/b` (inner slashes are not rejected; this URL won’t match the route, so validate yourself). `resolve('/docs/[...path]', { path: 'a/b' })` returns `/docs/a/b`. Leading or trailing slashes in a value throw.

18. `base` and `assets` (use `resolve()` and `asset()`) and `resolveRoute` (use `resolve()` with a route ID). The types `Pathname` and `Asset` became `Path` and `AssetPath`.

19. On the client it goes through the router’s intent resolution, which may run an async `reroute` or, with server resolution, make a request. It resolves to `{ id, params } | null`, a discriminated union on `id`, so narrowing `route.id` types `route.params`.

20. **c.** A route ID. Use `match()` to convert a pathname.

21. (a) page; (b) endpoint, since JSON is requested; (c) endpoint, since `*/*` does not prioritise HTML; (d) endpoint (`DELETE` always goes to `+server`; there is no handler for it unless `fallback`/`DELETE` is exported, giving 405); (e) browsers send `text/html` first, so the page (a `HEAD` is handled like `GET`).

22. `Vary: Accept`, so that proxies and browsers cache the HTML and JSON variants of the same URL separately.

23. It must be pure and idempotent (cached per URL on the client), must be fast (async ones delay navigation), runs before `handle` so has no `locals` or `cookies`, and if it throws on the server the response is a bare 500. It cannot read cookies because it also runs in the browser with only a URL and must give the same answer on both sides.

24. ```ts
    // src/hooks.ts
    const map: Record<string, string> = {
      '/de/ueber-uns': '/de/about',
      '/fr/a-propos': '/fr/about'
    };

    export const reroute: Reroute = ({ url }) => map[url.pathname];
    ```

    `event.url.pathname` remains `/de/ueber-uns` in `load` and `handle`; only route selection and `params` (`lang: 'de'`) use the rewritten path.

25. Client resolution matches in the browser from a shipped manifest; server resolution asks the server (`__route.js`) for each unvisited path. Benefits: smaller initial payload, hidden route list, infrastructure can intercept navigations. Cost: a round trip on first visit to each path. `handle` does not see route-resolution requests (they are answered before it); `reroute` still applies.

26. A `308` with a relative `Location` (e.g. `../about`) and `x-sveltekit-normalize: 1`, produced before `handle`. The relative `Location` preserves path prefixes added by proxies that Kit cannot see.

27. Recommend `'never'` (or `'always'`) rather than `'ignore'`. With `ignore`, `/x` and `/x/` are separate URLs (duplicate content, SEO harm); relative links resolve differently between them (`./y` from `/x` is `/y`, from `/x/` is `/x/y`); and prerendered filenames depend on the option. Choosing one value gives one canonical URL and predictable static output (`about.html` vs `about/index.html`).

28. CSRF protection runs only in production. A cross-origin mutating request with a form-like content type (or none) is rejected with 403 before the handler. Fix by sending `application/json`, or adding the origin to `csrf.trustedOrigins`.

## Chapter 4: Data Loading

1.  Server: database/filesystem/secret access; cookies, `locals` or `request`; batching several data dependencies into one `__data.json` request. Universal: calling a public API directly from the browser on navigation (skips your server hop); returning non-serialisable values such as component constructors or class instances.

2.  `data` is `{ c: 3 }`. The universal result replaces the server result. Fix: `load({ data }) { return { ...data, c: 3 }; }`.

3.  In the page: `data.user` is `{ name: 'ben' }` (page key wins, shallow merge) and `data.theme` is `'dark'`. In the layout component: `user: 'ana'`, `theme: 'dark'`, because a layout never sees descendants’ data (use `page.data` to read the page’s).

4.  Server load output is serialised with devalue, which only handles built-in types. Provide a `transport` entry in `src/hooks.ts` with `encode` and `decode`; `encode` must return a falsy value for anything that is not an instance of the type.

5.  Everything returned from a server load is serialised into the HTML and `__data.json`, so `passwordHash` is visible in the page source regardless of rendering. Return an explicit projection of the fields needed.

6.  `request.url` is untracked, so no dependency is recorded and the load is considered valid when only the URL changes. Read `event.url.searchParams.get('page')` (tracked per key).

7.  Tracked: `href`, `pathname`, `search`, `toString`, `toJSON`, and `searchParams.get/getAll/has` (per key). Not tracked: `origin`, `hostname`, `port`, etc. `url.hash` throws in load.

8.  With `get('q')`: no, only `sort` changed, which wasn’t read. With `[...url.searchParams]` (iteration is not `get/getAll/has`), the whole URL is tracked, so it reruns for any change.

9.  **b.** In-process dispatch into `respond`; `handle` runs with `isSubRequest` true.

10. `my.example.com` and `sub.my.example.com` receive cookies; `example.com` and `api.example.com` do not. `credentials: 'include'` does not widen it, since Kit can’t know which domain a cookie belongs to; use `handleFetch` for sibling domains.

11. It is a `<script type="application/json" data-sveltekit-fetched data-url=...>` holding status, filtered headers and body (plus `data-hash`, `data-ttl`, `data-b64` when relevant), emitted for universal-load fetches on SSR pages with CSR. On hydration the browser fetch wrapper finds and removes it and replays the response without a network call. Server-load fetches aren’t inlined because the load result itself is serialised, and the inputs may contain secrets.

12. The browser sees the real response headers, but during SSR the header is not in `filterSerializedResponseHeaders`, so reading it throws to flag a hydration mismatch. Add it to the filter in `resolve(event, { filterSerializedResponseHeaders })`.

13. The response is cached for 60 seconds (max-age minus age), so navigating back at 30 s is served from the cache without a network request. A non-GET request to the same URL evicts the cache entry.

14. An in-process fetch still performs `reroute`, route matching, `handle` and Response serialisation; calling the data function is cheaper and simpler. Use `fetch` when you want one HTTP contract shared with browser code, want caching headers honoured, or use `handleFetch` as a service-routing seam.

15. Prefer (c) a request-scoped cache (memoise by request via `getRequestEvent()` and a `WeakMap`), or (b) if the query is cheap: both avoid serialising children behind the layout. (a) is simplest but makes every child wait for the layout and add a dependency on its rerun. Never use a module-level cache (shared between requests).

16. In `+page.server.ts` it returns merged ancestor server layout data. In `+page.ts`, with no `+layout.ts`, the layout acts like `({ data }) => data`, so you still get the server data. If the layout has a `+layout.ts` that does not forward `data`, those server fields are shadowed and absent.

17. `getStats` waits for `parent()` although it only needs `params`. Start it first: `const statsP = getStats(params.org); const { org } = await parent(); return { org, stats: await statsP };`.

18. Yes, it likely runs because layout and page loads start concurrently; the user doesn’t receive the result, but the database read happened. So authorisation must be enforced in `handle` or in each page load, not only a layout.

19. A given header can be set once across all loads (error on a second set), except `server-timing`, which is comma-joined; `set-cookie` is not allowed (use `cookies`). It has no effect in the browser, for data requests, or after streaming/response completion.

20. The second call errors (`cache-control` header is already set). Set the baseline in `handle` after `resolve` only when the response lacks `cache-control`, and let pages set overrides.

21. `setHeaders` governs the HTML document response. Data requests (`__data.json`) always carry `cache-control: private, no-store`.

22. ```ts
    export function requireRole(role: string) {
      const { locals, url } = getRequestEvent();
      if (!locals.user) {
        redirect(303, `/login?${new URLSearchParams({ redirectTo: url.pathname + url.search })}`);
      }
      if (locals.user.role !== role) error(403, 'Forbidden');
      return locals.user;
    }
    ```

    Inside a load, `url` is the tracked URL, so reading `pathname`/`search` records a dependency and the load reruns when they change (use `untrack` if undesired).

23. **c.** In 3.0 `redirect()` rejects locations on another origin unless you pass `{ external: true }` or an allow-list. You no longer `throw` it (it throws for you), external URLs are not allowed by default, and a redirect cannot happen inside a streamed promise because the response has already started.

24. ```ts
    try {
      const r = await getThing();
      if (!r) error(404);
      return r;
    } catch (e) {
      if (isHttpError(e) || isRedirect(e)) throw e;
      return fallback;
    }
    ```

    Better: call `error(404)` outside the `try`.

25. As a JSON body `{"type":"redirect","status":307,"location":"/login"}` with HTTP status 200. The client router follows it (up to 20 hops).

26. `$state(data.posts)` captures the initial value only; the component is reused for the same route, so the list stays stale after navigation. Fixes: `$derived(data.posts)`, or wrap the component in `{#key page.url.search}`/ re-key on an id.

27. Universal loads run on the server where `window` is undefined. Use `browser` from `$app/env` (or `BROWSER` from `esm-env`) guards, or move the logic into `onMount`/an `$effect`.

28. `tracing.current.setAttribute('app.user_id', locals.user.id)` on the load event. On the client the `tracing` object is a no-op (`enabled: false`), so tracing calls are harmless in universal loads (there the user ID would come from `data` or `parent()`, since `locals` exists only in server loads).

## Chapter 5: Invalidation and Streaming

1.  A node is invalid when: (1) a refresh is forced (`refreshAll`/`invalidateAll`/`goto` with `refreshAll`); (2) it used `parent()` and a parent reran or changed; (3) it used `route` and the route ID changed; (4) it used `url` and the URL key changed; (5) a search param key in `uses.search_params` changed value; (6) a param in `uses.params` changed; (7) a dependency in `uses.dependencies` matches a pending invalidation. Conditions 2 to 7 apply to server and universal loads alike. For server loads the `uses` record is computed on the server and sent to the browser with the data (the `"uses":{...}` field), so the client can decide without asking; for universal loads it is recorded in the browser.

2.  No: `view` was not read, so the node is valid and no request is made. Also no for the reordered query string: search param values are compared per key, so `category=a` is unchanged and `sort` was not read.

3.  `Object.fromEntries(url.searchParams)` iterates the params, which tracks the whole URL: the load reruns for any query-string (or pathname) change, including irrelevant keys such as `view` or `utm_source`, and each rerun costs a `__data.json` request. Two `get` calls track only `category` and `sort`.

4.  `params.id` is read inside the `setTimeout` callback, after the load has returned, so it is not tracked (and the dev server warns). Navigating `/p/1` to `/p/2` finds no used params, so the node stays valid. Fix: `const id = params.id;` at the top of the load, then use `id`. (The streamed promise would also need a no-op `catch` for safety.)

5.  The dependency set is sent to the browser, and a server-side fetch URL can contain secrets, tokens or internal host names. Use `depends('app:dashboard-stats')` with an opaque identifier. A mistake: `depends('https://internal.api/stats?token=abc')`, which leaks the URL and token to the client.

6.  Server loads do not track `fetch` URLs, so no dependency on that URL exists. Add `depends('app:stats')` in the load and call `invalidate('app:stats')` after the mutation.

7.  `app:cart` and `data:posts:42` are valid (they begin with `[a-z]+:`). `cart` has no scheme and is not a valid custom identifier. `view-source:x` uses a scheme that has special browser meaning and is rejected or warned about.

8.  `invalidate((url) => url.pathname.startsWith('/api/posts'))`. The predicate receives each dependency URL and ignores the query string by looking only at `pathname`.

9.  `invalidate(key)` reruns only the loads depending on the matching key or predicate, resets `page.state` unless `keepState` is true, and does not touch remote queries. `refreshAll()` reruns every load of the current page and refreshes all active remote queries (including live ones), keeping `page.state`. `invalidateAll()` reruns all loads but resets `page.state`, and is deprecated in favour of `refreshAll`.

10. One. Calls in the same tick are batched: the first chains onto a pending promise and later ones add their predicates, so a single pass reruns everything affected.

11. The navigation wins. An invalidation that finishes after a navigation committed is outdated, so its result is discarded rather than applied over the new page. (Since 3.0 the reverse no longer holds: an invalidation starting during a navigation does not abort it.)

12. **b.** The `data` prop is updated and the component is not recreated, so local `$state` survives.

13. It is a bitmask for three server nodes: the first and third are invalid (sent to the server, which reruns them), and the middle is valid. The response contains `{"type":"skip"}` for the middle node.

14. Starting `loadComments()` first without awaiting lets it run in parallel with `await loadPost()`, and the object is returned as soon as the post is ready; the comments continue streaming. The reverse order awaits the post before even starting comments, making the total time the sum rather than overlapping.

15. Node treats it as an unhandled rejection, which crashes the process by default. `defer` attaches a no-op `catch` to the original promise and returns that same promise, so Node considers it handled, while the serialiser still sees the rejection. The browser receives it (after `handleError` sanitisation) in the `{:catch}` branch.

16. Redirects (`redirect()` becomes a rejection), error status (`error(404)` cannot change the 200), `setHeaders`, and `cookies.set`. Also reading `params`/`url` is untracked. Move redirects, auth and status decisions, header and cookie writes into the awaited part of the load (or into `handle`); stream only decorative data.

17. Universal load results are not serialised with deferred placeholders. The promise is created on the server (the HTML contains only the pending branch) and the load runs again in the browser on hydration, recreating the promise, so the work is done twice. Use a server load to stream.

18. They see only the pending branch (the “Loading” content), since chunk scripts need JavaScript. For SEO-critical comments, await them in the load so they are in the initial HTML.

19. Examples: Lambda-style platforms (use a platform with response streaming, or accept no streaming); NGINX and other reverse proxies (`proxy_buffering off` or `X-Accel-Buffering: no`); compression middleware (use one that flushes, such as `@polka/compression`). CDN caches replaying whole pages are another (mark personalised pages `private`).

20. The length and content are unknown when the headers are sent, and a hash cannot be computed over a body that does not exist yet. Streamed data requests use `text/sveltekit-data` with `cache-control: private, no-store`, which defeats intermediaries that buffer or compress `application/json`.

21. Block when the page is meaningless without the data, it is fast, it is SEO-critical, or a failure should produce an error page; stream when slow, variable and secondary, with a layout-matched skeleton. Description: block (SEO, essential). Price: block (essential, usually fast). Reviews: stream, unless SEO matters for ratings (then await a summary and stream the list). Related products: stream. Cart count: await in the layout if cheap and fast, since it is visible chrome; stream if the cart service is slow.

22. `hover` starts on pointer rest (touchstart on touch devices), giving more lead time; `tap` starts on `mousedown`/`touchstart`, giving less lead time but fewer wasted requests and fresher data. Use `hover` for stable, cheap data; `tap` for fast-changing or costly data. Preloading runs the load, so on `hover` any side effect in it would fire for links the user merely passes over.

23. When an invalidation starts, another route is preloaded, a navigation to a different route commits, or `goto` is called with `refreshAll: true`. If the click happens while the preload is in flight, the in-flight promise becomes the navigation: no second load is made.

24. `preloadData('/missing')`: no navigation intent exists for a URL with no matching route, so it throws (the “preload outside app” error) instead of returning a result. `preloadData('/protected')` resolves with `{ type: 'redirect', status: 307, location: '/login' }`.

25. A route ID, such as `/blog/[slug]`, not a pathname. Convert a pathname with `const m = await match(pathname); if (m) await preloadCode(m.id);`. A pathname-looking argument produces a development warning.

26. After a preload resolves as loaded, the router applies the result inside a Svelte `fork`, starting component `await` work speculatively; on the real navigation it commits the fork instead of starting from scratch. Needs `experimental.forkPreloads: true` in `sveltekit({...})` and Svelte’s `compilerOptions.experimental.async: true`. With only the Kit flag, `fork` throws, Kit swallows the error and falls back to normal navigation: harmless but no benefit. Risk: component code and awaited queries run for pages the user may never visit (side effects, cost).

27. Keep `let pending = $state(new Map())` and `let todos = $derived(data.todos.map(t => pending.has(t.id) ? {...t, done: pending.get(t.id)} : t))`; on toggle, set the intent, send the mutation, `await invalidate(key)`, and delete the intent in `finally` (rollback on failure). It is robust because the display is a pure function of `data` and the pending intents, so any rerun (navigation, `refreshAll`) yields a coherent result, and rollback is just deleting the intent.

28. Polling with `invalidate` reruns the dependent server loads for each of 500 users every 10 s (about 50 server load executions per second, plus database queries) and wakes every open tab, even hidden ones. Alternatives: a live remote function (`query.live`, Chapter 7) or an SSE endpoint, with a shared server-side computation or cache that fans out to subscribers; use short HTTP caching for the shared part; pause updates when the tab is hidden.

## Chapter 6: Form Actions and Progressive Enhancement

1.  SvelteKit throws `action_default_with_named` for the page. A named action posted without a redirect leaves `?/name` in the URL; a later default `POST` would then hit the same URL and run the named action again, so the two forms of addressing are ambiguous. Use only named actions or only `default`.
2.  The `POST` reaches the page renderer, which finds no actions and returns a `405 Method Not Allowed` error result with an `Allow: GET` header. In dev the message names the route id. (Before that, `handle` has already run and CSRF checks have passed.)
3.  Native: the page is rendered as a full response, status 200. Enhanced (JSON request): the status is 204 and the body carries no data. Returning an object gives 200 in both.
4.  `throw fail(...)` is wrong: `fail` returns a value and must be `return`ed. In dev SvelteKit raises `action_throw_fail`; in production a thrown `ActionFailure` is treated as an error. Fix: `return fail(400, { missing: true })`.
5.  `satisfies` keeps the precise inferred return type of each action, so the generated `PageProps['form']` is a union of what you really return. An annotation widens the return type to the generic signature and `form` becomes loosely typed.
6.  It collapses repeated keys, keeping only one value (and files stay as `File`). Use `formData.getAll('name')` for checkbox groups and `<select multiple>`.
7.  The relative action resolves to `/items?/delete`, dropping `page=2`, so the user lands on `/items` (the `?/delete` part is stripped, nothing else remains). Write `action="?page=2&/delete"` to preserve it.
8.  (a) 422; since 3.0 the enhanced response uses the `fail` status. (b) `result.status` is 422 (the client copies the HTTP status onto failure results). (c) `page.status` is 422 once `update()` applies the result.
9.  **b.** `applyAction` updates `form`/`page.form`/`page.status` for success and failure and calls `goto` for redirects, but it neither refreshes data nor navigates to the location of a non-redirect result; `update` does those things.
10. In SvelteKit 3 the default is to navigate to `/other` and render it with the result. With `navigate: false` the result is applied to the current page (`form`, `page.form`, `page.status`; errors render the current route’s nearest boundary), restoring the v2 behaviour.
11. It is the `AbortController` bound to the request’s `fetch`. Keep the previous controller and call `abort()` at the start of a new submission (search-as-you-type, rapid toggles) so only the latest response is applied; aborted requests resolve silently without calling your callback.
12. The request is made, but nothing is applied: `form`, `page.status` and data are not updated, the form is not reset and no redirect is followed. Returning a callback replaces the defaults entirely.
13. `<form method="POST" action="/newsletter?/subscribe" use:enhance={() => async ({ update }) => { await update({ navigate: false }); }}>`. With `navigate: false` the result lands on the current page’s `page.form` (the `form` prop type belongs to the page that defines the action, so read `page.form` or `result.data` in the callback). Without it, SvelteKit 3 navigates to `/newsletter`.
14. Action results are encoded with devalue, not JSON, so they can contain `Date`, `BigInt`, `Map`, `Set` and transport-hook types. `JSON.parse` cannot decode them; `deserialize(await response.text())` can.
15. It marks the request as an action call. When a `+server` file sits next to `+page.server`, a plain `POST` goes to the endpoint; with the header it goes to the page action. `use:enhance` sets it automatically.
16. `"object"`: devalue revives `Date` instances on the client, so `form.at` is a `Date`.
17. Missing `enctype="multipart/form-data"` on the form. Without it the browser (and `use:enhance`) sends only the file name as a string; in dev SvelteKit logs `enhance_file_without_enctype`.
18. `request.formData()` has already buffered the whole body by then. The adapter/platform limit (e.g. adapter-node `BODY_SIZE_LIMIT`, default 512K) is what rejects oversized bodies earlier, or you must use presigned uploads or streaming.
19. `handle` populated `locals.user` before the action; deleting the cookie does not change `locals`, and the page `load` that runs after the action in the same request still sees the user. Fixes: set `locals.user = null` in the action (ideally via a shared helper that does both), or `redirect(303, ...)` so the next request runs `handle` afresh.
20. Layout loads and actions are separate code paths: an action runs before any loads and does not depend on layout data, and layout loads also run in parallel and do not rerun on every navigation. The check belongs in `handle` (route-pattern guard) or inside the action itself (and in each `+page.server` load).
21. **c.** `303 See Other` makes the browser follow with a `GET`; 307 would repeat the `POST`, 301/200 are inappropriate.
22. `redirect()` treats it as external (different origin than the current one) and, with no `external` option, throws a developer error, resulting in a 500. A safer version validates first: accept only values starting with `/`, not `//`, not containing a backslash, else fall back to a default path.
23. It checks the `Origin` header on form-typed (or content-type-less) `POST/PUT/PATCH/DELETE` requests against the app’s own origin (`paths.origin` if set, else the origin derived from `request.url`) and `csrf.trustedOrigins`. Behind a TLS-terminating proxy, make sure the adapter sees the correct protocol/host (adapter-node protocol/host headers) or set `paths.origin`; otherwise all form posts are rejected with 403.
24. Enhanced action responses now carry the real `fail` status (4xx) instead of 200, so validation failures show up as client errors in logs, CDNs and APM tools.
25. (a) Without JS: a 500 page rendered by the nearest `+error.svelte` (or `error.html` as a last resort). (b) With `use:enhance`: an `error` result, so the callback sees `result.type === 'error'` and the default flow renders the nearest `+error.svelte`. In both cases `handleError` receives the error with `kind` set to the unexpected-error kind and can return a sanitised `App.Error`.
26. Actions: manual `FormData` typing, hand-rolled validation shape, redirects and no-JS support, cannot be prerendered, stable. Remote `form`: schema-derived types, per-field issues and `preflight`, redirects supported, experimental. Choose actions for existing codebases, stability-sensitive projects, and page-scoped, URL-addressed flows.
27. Prerendering produces static HTML at build time with no server to receive the `POST`; SvelteKit fails the build (`prerender_actions`). Options: set `prerender = false` for the form route and deploy a server (or adapter with SSR for that route), or post to an external service or a separate `+server` endpoint.
28. Problems: results are lost on reload, URLs cannot be bookmarked or shared, back/forward behave badly, nothing is cacheable, and the response is a `POST`. Better: a GET form (`<form action="/search">`) whose `load` reads `url.searchParams`.

## Chapter 7: Remote Functions: query, prerender, and live

1.  `experimental.remoteFunctions: true` (SvelteKit option) and `compilerOptions.experimental.async: true` (Svelte compiler option). Both are options of the `sveltekit({...})` plugin call in `vite.config.ts`; `svelte.config.js` is no longer supported.
2.  A remote module may only export remote functions; exporting a schema raises `remote_module_invalid_export`. Move the schema into an ordinary module (for example `schemas.ts`) and import it in both the remote module and the component.
3.  Server-only directories (any `server` directory) cannot be imported by client code, while the client needs to import the remote module to get its generated fetch wrappers. The build therefore disallows remote modules there.
4.  The id is `<hash of the file path relative to the project root>/<export name>` and the endpoint is `/_app/remote/<hash>/getPost` (respecting `appDir` and `paths.base`). Moving or renaming the file changes the hash, so clients running the previous build call an endpoint that no longer exists (404) until they reload.
5.  An `error(400, 'Bad Request')`: functions declared without a validator refuse any argument. It reaches `handleError` as an app error and the client sees an error envelope with status 400.
6.  At runtime the argument is passed through without validation. At compile time, TypeScript still trusts your annotation, so the type may be a lie. Acceptable when the argument is an opaque value validated elsewhere (for example immediately checked by a library call in the body) and not used unsafely; never when interpolating it into queries.
7.  `Input` is `string` (what callers pass); `Output`/`Validated` is `number` (what the function body and `requested()` entries see). The `Validated` type parameter of `RemoteQueryFunction` carries this output type.
8.  Yes for the objects: keys are sorted, so they share an entry. No for the arrays: array order is preserved, so `[1,'a']` and `['a',1]` are different keys.
9.  **b.** At runtime the error is serialised inside a 200 envelope (`type: 'error'`) with the generic body `{ status: 400, message: 'Bad Request' }`; the issues are only visible to `handleError`. (The HTTP status is non-200 only while prerendering or when something around the function, like `handle`, rejects.)
10. `loading` is `true` before the first value and during every refresh; `ready` becomes `true` after the first value and stays `true`. Render `current` when `ready` is true and add a dimming class when `loading` is true, so stale data stays visible while refetching.
11. Each click creates a new argument and therefore a new key, so each triggers one request. A boundary’s `pending` snippet only covers its first render, so Svelte keeps showing the previous list until the new data arrives (use `$effect.pending()` for a loading indicator). After two clicks the list shows page 3, and three pages have been requested in total (page 1 may come from the SSR payload instead of a request).
12. The per-request cache is keyed by function and argument, regardless of whether the function is exported. Only exported functions have an `id`, and results of functions without an `id` are never added to the response payload, so a private query’s data cannot reach the client.
13. The build fails with `remote_query_prerender`: queries fetch runtime data and cannot be used while prerendering. Fixes: use `prerender` for that data; or set `prerender = false` for the page (render it dynamically).
14. When the last `QueryProxy` referencing an entry is garbage collected (a `FinalizationRegistry` decrements the entry’s count) and no effect or in-flight await pins it, a check on the next tick evicts the entry. The factory must not close over `this`, otherwise the cache entry would reference the proxy, which could then never be collected and the entry never evicted.
15. Use `query.batch(v.string(), async (ids) => { const rows = await db.stock(ids); const m = new Map(rows.map(r => [r.id, r])); return (id) => m.get(id) ?? error(404, 'Unknown id'); })`. All calls in the same macrotask become one request and one `db.stock` call; a missing id rejects only that entry’s promise (its card shows the failed state), while other cards succeed.
16. `rows.find(...)` can return `undefined` and `.qty` then throws a `TypeError` for that id; it becomes an unknown error (500) for that entry. Also `find` makes the resolver O(n\^2). Build a `Map` first and decide explicitly (`error(404)` or a default).
17. Svelte uses microtasks to batch and flush reactive updates; a flush can reveal more queries that should join the same batch. Waiting for the next macrotask lets all of them be collected before sending.
18. SSR awaits the first value and then closes the iterator; if the generator awaits for minutes before yielding, SSR hangs (or the page times out), and a generator that finishes without yielding raises `remote_query_live_no_value`. Always yield an initial value immediately.
19. No. The server compares the devalue-serialised value with the previously sent one and skips identical values, so unchanged snapshots cost no frames (only keep-alive comments every 30 s of silence).
20. Backoff delay is `min(250ms * 2^attempt, 10s)` with ±20% jitter, reset on a successful connect. Retries stop when `navigator.onLine` is false (until the `online` event) and when the page is hidden/unloaded (pagehide), resuming on bfcache restore. An intentional `HttpError` (including validation) after the first value, or any error before the first value, is terminal: `done` becomes true and only `reconnect()` revives it.
21. **b.** `done` means the stream ended (generator returned) or the query failed terminally.
22. When the client disconnects SvelteKit aborts `request.signal` and calls `generator.return()`, but a pending `await` inside the generator cannot be interrupted. Passing the signal to the awaited subscription lets you stop waiting, release the subscription and let the generator finish.
23. A cloned streaming response keeps streaming after the page is closed. Live responses have `Cache-Control: private, no-store` (and `content-type: text/event-stream`), so exclude any response with `no-store` from caching logic.
24. (a) `prerender` runs at build time (or lazily with `dynamic`), `query` at request time. (b) Prerender functions are excluded from the server bundle unless `dynamic: true`. (c) Prerender results are stored in the browser Cache API per deployment version; queries only in the in-memory cache. (d) `prerender` has no `refresh`/`set`/`withOverride`.
25. The server bundle does not contain the function, so the call cannot run; the static lookup finds nothing and the call fails (404/error). Use `dynamic: true` to compute non-prerendered arguments on demand.
26. `query`: `url` throws; `cookies.set` throws (reading is fine); `setHeaders` throws. `form`: `url` works but is the calling page and is client-supplied; `cookies.set` works (absolute path); `setHeaders` throws.
27. For a query, `handle` runs with the URL of the remote endpoint (`/_app/remote/...`), not the page, so the prefix never matches. Authorise inside the remote function (a `requireUser()` helper using `getRequestEvent().locals`, plus data-level permission checks); `handle` should only derive identity from cookies into `locals`.
28. Examples: login/logout in the same tab, or a session expiring or being switched in another tab. The client cache persists for the page lifetime, so call `refreshAll()` (or do a full navigation/reload) after identity changes, or include the user or tenant id in the query argument, and ensure server responses are not shared (they are `no-store`).
29. `command` arguments and `form` fields can contain `File`s. `query`, `query.batch`, `query.live` and `prerender` arguments cannot (they are cached and sent in a URL or a JSON payload).
30. Stale clients call endpoints with the old hash and get 404 errors (or validation errors if signatures changed). SvelteKit detects new deployments from the version header on remote responses (and data/form action responses), from tab focus and visibility changes, and from polling (`version.pollInterval`, default 1 hour); `updated.current` becomes true and you can reload or prompt the user.

## Chapter 8: Remote Functions: form and command, and Single-Flight Mutations

1.  `method="POST"` (so the form submits natively), `action` (`?...&/remote=<id>`, the URL for no-JS posts), and an attachment (a symbol-keyed `{@attach}` function) that intercepts `submit` when JavaScript runs, validates with preflight, sends the request to the remote endpoint and applies the result. Without JS only `method` and `action` matter; the server re-renders the page with the result.
2.  `?/remote=<hash>/<name>` appended to the current URL’s other query parameters. The page renderer recognises a `POST` with a `/remote` parameter and routes it to the remote form (`handle_remote_form_post`) instead of to `actions`.
3.  Control names are generated by `.as()` and encode the path, coercion type, array-ness and form id; a name not created by the form’s own field is not part of the form and the submission is rejected. A number field looks like `n:qty/<hash>/<formName>`.
4.  At the type level the `form(...)` call errors: all booleans in form schemas must be optional (`v.optional(v.boolean(), false)`). At runtime an unchecked checkbox sends nothing, so a required boolean would fail validation whenever unchecked.
5.  Declare it as `v.optional(v.array(...), [])` (or Zod `.default([])`), because an empty multi-select sends no entries.
6.  Fields (or nested paths) with an underscore prefix are never echoed back in the re-rendered page after a failed native submission. It matters for passwords, card numbers and tokens, which would otherwise appear in the HTML response.
7.  The option is `all` (renamed from `includeUntouched`; the docs are stale). `validate({ all: true })` shows issues for fields not yet edited and blurred. `preflightOnly: true` runs only the client-side preflight schema and skips the server validation round trip.
8.  Costs: a server request per call (the server runs the schema), and noisy or racing responses plus load. Mitigations: debounce or use `onchange`/blur, use `preflightOnly` for cheap checks, and rely on the default touched/dirty gating so untouched fields are not shown.
9.  `invalid(issue.address.postcode('Unknown postcode'));`
10. In dev it raises `remote_form_fail`: `fail` is for actions. Use `invalid(...)` for validation issues, or return a result value for non-validation outcomes.
11. `fields.allIssues()` returns every issue for the form (including those with an empty path); `fields.email.issues()` returns only the issues for that field, or `undefined`. String arguments to `invalid` are form-level, so only `allIssues()` shows them.
12. It resolves to `false` and no exception is thrown; issues are populated on the fields. Exceptions are reserved for unexpected failures (network errors, 5xx, handler throws).
13. The default callback resets the DOM form after success; once you provide `enhance`, nothing resets automatically. Call `form.element.reset()` yourself when `submit()` resolves `true`.
14. The response carries a redirect plus the refreshed `getTodos` data. The client applies the query data and calls `goto('/done')`, waits for the navigation to finish, then `submit()` resolves with `true`.
15. Commands are imperative mutations; a redirect inside one raises `remote_command_redirect` on the client. Return the destination (or any result) from the command and call `goto` after awaiting it.
16. **b.** A command does not invalidate anything automatically; you must use `refresh`/`set`/`.updates(...)` or call `refreshAll()` yourself.
17. A successful form calls `refreshAll()`: all queries and load functions that can rerun. A command invalidates nothing.
18. No. Any explicit `refresh()`, `set()` or `reconnect()` call replaces the default `refreshAll`, and `load` functions are not queries. Only `getPosts` is updated, so `user` stays stale unless you call `refreshAll()` yourself.
19. The query function is stored and executed after the handler body finishes. It therefore observes all writes made in the handler, regardless of call order, and if the query is awaited again in the handler the cache entry is reused rather than run twice.
20. It updates the client instance of `getTodo` whose argument equals `id` (same function id and serialised argument). It does not touch other `getTodo` instances or other queries such as `getTodos()`.
21. `await createPost.submit().updates(getPosts, getStats({ range: '7d' }))`
22. Those `getPosts` instances enter an error state on the client (“Requested update was not handled by the remote function”, status 400), even though the mutation succeeded.
23. The list of requested keys is controlled by the client and each entry costs validation and usually a data fetch, so an unbounded list is a denial-of-service vector. Entries beyond `limit` are skipped and fail on the client. `ignoreAll()` only ignores entries within the limit; the excess still fails.
24. `arg` is the validated output, a `number`. `query` stays bound to the client’s original key (the string form the client used), so `refresh()`/`set()` update the right client instance even though the schema transformed the value.
25. An empty `.updates()` is still a call: it opts out of automatic invalidation, so nothing is refreshed (no `refreshAll`). A bare `await submit()` triggers the default `refreshAll()` after success.
26. The second is rejected with `remote_updates_duplicate_override`: only one override per query instance per `updates()` call.
27. The UI reverts to the server’s value: the override is released in a `finally` when the command settles, so the optimistic change disappears; your `catch` should tell the user. The framework (the `.updates` machinery) restored the state, not your code.
28. Client: `await moveCard({ id, to }).updates(getCards({ board, column: from }).withOverride(removeCard), getCards({ board, column: to }).withOverride(addCard))`. Server: `for await (const { arg, query, ignore } of requested(getCards, 8))` refresh when `arg.board === board && (arg.column === from || arg.column === to)`, otherwise `ignore()`. A limit of about 8 (4 columns, some headroom) bounds the work.
29. In forms and commands `url`, `route` and `params` come from client-supplied headers identifying the calling page and can be forged, so they must not determine access. Check identity (`locals` from cookies) and resource ownership in the handler.
30. For example: `fail(422, data)` becomes `invalid(issue.field(msg))`; `form` prop / `page.form` becomes `myForm.result` and `fields.*.issues()`; `use:enhance` callback with `update()` becomes `myForm.enhance(cb)` with `form.submit()`; `name="email"` becomes `{...f.fields.email.as('email')}`; `formaction` buttons become `as('submit', value)` fields.

## Chapter 9: Hooks and Middleware Patterns

1.  `hooks.server.ts` (`handle`, `handleFetch`, `handleError`, `init`), `hooks.client.ts` (`handleError`, `init`), `hooks.ts` (`reroute`, `transport`). Only `hooks.ts` is universal.
2.  From `@sveltejs/kit/hooks` (`Handle`, `HandleFetch`, `HandleServerError`, `HandleClientError`, `ServerInit`, `ClientInit`, `Reroute`, `Transport`, `ResolveOptions`, `CaughtError`). Its only runtime export is `sequence` (plus a stub that throws for the moved `defineEnvVars`).
3.  Static assets (`static/`, `/_app/immutable`), prerendered pages, and route-resolution/`env.js` requests; also requests rejected by the CSRF check, and client-side navigations that need no server request.
4.  CSRF origin check (production only), `reroute`, route matching, then `handle`. Because CSRF runs before `handle`, a hook can neither see nor disable rejected requests.
5.  Four times: the original request plus three internal sub-requests. Sub-requests have `event.isSubRequest === true`.
6.  `a1 b1 b2 a2`.
7.  The first handler’s `preload` wins and the second is never consulted. If only the second defines it, the second’s is used.
8.  Chunks are split at component/placeholder boundaries, not elements, so the tag can straddle chunks and the regex silently misses it. Use placeholders you own in `app.html` (e.g. `%lang%`), which are in the first chunk, and replace those.
9.  `filterSerializedResponseHeaders` in `resolve`: by default no headers are serialised; allow `x-total-count`.
10. Responses with immutable headers (`Response.redirect()`, some `fetch` results) throw a `TypeError` on `headers.set`. Clone: `new Response(response.body, response)`.
11. Fatal error: it passes through `handleError`, then the browser sees the static `src/error.html` page and the JSON client gets a JSON error body. `+error.svelte` is not used.
12. `resolve` never throws; load errors are converted into an error response (page or JSON). Detect via `response.status` (and handle them in `handleError`).
13. After `resolve` completes the event is sealed: `cookies.set` and `setHeaders` throw. Set cookies before `resolve` or modify `response.headers`.
14. Types in `Locals` are non-optional, so an unassigned property is a runtime `undefined`. Declare properties optional (or give defaults) for conditionally applied handlers so consumers must check.
15. It sends every field (request id, internal flags, full user) to the browser as page data. Return an explicit projection of only what the UI needs.
16. Define a getter (or memoised `locals.getUser()`) that stores the promise on first access. Trade-off: the type becomes async/less ergonomic, and every consumer must await.
17. `handle` ran once before the action; deleting/changing the cookie does not change `locals`, and same-request loads see the stale object. Update `locals` in the action (or redirect so a fresh request runs `handle`).
18. It receives `{ event, request, fetch }` and returns a `Response`. It can rewrite internal URLs/route to private hosts and forward cookies with the event, and intercepts all `event.fetch` calls (including inside actions/endpoints/handle) in one place.
19. `startsWith` on the URL string matches `https://api.example.com.evil.test/`, leaking the user’s cookie to a third party. Compare `new URL(...).hostname` exactly.
20. `handleFetch` only wraps `event.fetch`. A global `fetch` also loses relative URL resolution, direct internal routing, cookie/authorization forwarding and SSR response inlining.
21. The client caches results and calls it once per URL; impure or varying output yields stale/inconsistent routing and hydration mismatches between server and client.
22. No: neither `event.url` nor the address bar change. It changes only the pathname used to select the route and derive `params`.
23. Async work in client `init` delays hydration, so the page stays non-interactive until it finishes.
24. **b.** `encode` returns a truthy encoding for instances of the type and `false` for everything else, and `decode` rebuilds the instance from that encoding. `encode` runs on the server (and on the client for remote function arguments), the transporter’s key identifies the type on both sides, and transport applies to remote functions and actions as well as `load` data.

25. `export const maintenance: Handle = async ({event, resolve}) => { if (building || process.env.MAINTENANCE !== '1') return resolve(event); if (event.url.pathname === '/healthz') return new Response('ok'); return new Response(html, { status: 503, headers: {'retry-after': '600', 'content-type': 'text/html'} }); }`. Static assets and prerendered pages still bypass it.
26. The response varies by `Origin`, so caches need `Vary: Origin` to avoid serving one origin’s CORS headers to another. The CSRF check applies only to form-typed (or content-type-less) requests, and a JSON `fetch` is neither.
27. Per-process state is not shared across instances (and resets on restart/serverless cold start); and behind a proxy `getClientAddress()` may return the proxy address unless trusted headers are configured, so all clients share one bucket. Unbounded map growth is a third.
28. `event.url` is the remote endpoint URL (`/_app/remote/...`) and `route.id` is `null`, so a path-prefix admin guard never matches; authorise inside the query.
29. `preload`; it depends on build-time chunk analysis that does not exist in dev.
30. Examples: import types from `@sveltejs/kit/hooks`; `handleError` now receives all errors with `kind` and `handleValidationError` is removed (branch on `kind`); `resolve` always returns `Promise<Response>`; cookie `path` defaults to `/`; `defineEnvVars` moved to `@sveltejs/kit/env`.

## Chapter 10: Errors and Error Handling

1.  `app` (`error(404, ...)`), `framework` (404 for no route, 405, 413), `validation` (remote function argument fails schema), `unknown` (a thrown `TypeError` or DB driver error).
2.  `status: number` and `message: string`. A required extra property must be supplied as the third argument to `error()` and must be returned from `handleError` (returning void becomes a type error).
3.  `error()` throws by itself, so `throw error(...)` is redundant (and obscures control flow). In an action, `return error(...)` raises `action_return_error`: call it without `return` or use `return fail(...)`.
4.  The `error(404)` is thrown inside the `try`, is caught, and is converted into a 500. Narrow the `try` to the DB call, or rethrow with `if (isHttpError(e) || isRedirect(e)) throw e`.
5.  `error(404, 'Not found', { code: 'NOT_FOUND' })`. The object form for the second argument is deprecated (dev warning).
6.  It throws a developer error (`redirect_external_not_allowed`), producing a 500. Allow with `{ external: true }` (any external except `javascript:`/`data:`) or an allow-list: `{ external: ['https://other.example'] }`.
7.  It turns attacker input into a server error instead of a clean fallback (and same-origin odd values may still lead to unexpected pages). Validate: accept only paths starting with a single `/` and fall back otherwise.
8.  Expected errors created with `error()` skipped it. In 3.0 all errors arrive, with `kind`. Filter by kind and status (do not report `app` 4xx or `framework` errors).
9.  `message` is `'Oops'` and `status` is inherited (500). With `{ status: 404 }`, the status is 404 and the message stays `Internal Error`.
10. SvelteKit logs `handle_error_hook_failed` (with the hook’s error as cause, then the original) and responds with the original status and a generic `Internal Error` message, discarding the hook’s result.
11. When the error occurs during server-side rendering and `compilerOptions.experimental.async` is off: a warning is logged and the result is discarded in favour of a generic error.
12. Errors already transformed on the server are not passed to the client hook again; the server hook reported it. The client `handleError` reports failures that only happen in the browser, such as a universal `load` failing there.
13. `'validation'`: only server-side remote function arguments are validated against a schema; the browser never produces it.
14. The root `+error.svelte`: layout load errors use the nearest boundary strictly above the layout, so `shop/+error.svelte` is skipped.
15. The static `src/error.html`, since no boundary exists above the root layout.
16. If it throws, the framework falls back to `error.html`; data needs also run into the root layout load (which may be the thing that failed), causing recursive failure.
17. The automatically created `<svelte:boundary>` around each `+error.svelte` (and error routing via `handleError`), on server and client. It is default in 3.0 (the experimental flag was removed); an async client `handleError` needs `experimental.async`.
18. **b.** A `+server.ts` handler has no page to render, so SvelteKit answers by the `Accept` header: a JSON-preferring client gets the error as JSON with status 422 (an HTML-preferring one gets `error.html`). `+error.svelte` is never used for endpoints.

19. They are replaced (message HTML-escaped) in `error.html`, the static fallback used for errors in `handle`, `+server` (non-JSON clients), the root layout, and errors while rendering the error page.
20. A plain-text `404 Not Found` with `Vary: Sec-Fetch-Dest`, since a full HTML error page is useless for non-HTML subresources and wastes bandwidth.
21. The boundary nearest the action’s route (`/b`’s, after navigating there). With `navigate: false`, the current route’s (`/a`’s) nearest boundary.
22. Runtime remote errors are serialised as `{ type: 'error' }` inside a 200 response; use `handleError`, tracing spans or application logs. HTTP status is used when `handle` (auth, CSRF, rate limit) rejects, and during prerendering.
23. A generic `{ status: 400, message: 'Bad Request' }` error; `issues` are visible only to `handleError` (`kind: 'validation'`).
24. They are expected, in-band outcomes (issues returned with a successful response or `fail`), shown beside fields; they are not exceptions.
25. `framework` -\> return nothing/keep defaults without reporting; `unknown` -\> if it is a `DomainError` return `{ status, message, code }`, otherwise report with an `errorId` and return `{ message: 'Something went wrong', errorId }`. Wrap reporting in `try/catch`.
26. The reporter can throw or hang, which would turn into `handle_error_hook_failed` and a slower or generic response. On serverless platforms, use `waitUntil` from `platform` so the report is flushed before the function freezes.
27. Request bodies or tokens embedded in driver/HTTP-client error messages and config, and URLs with query strings. Scrub before reporting; log `route.id`/method instead of full URLs.
28. No: status and headers are already sent. The promise rejects on the client’s `data` property; handle it with `{#await}`/boundary (and attach a server-side `.catch` to avoid unhandled rejection).
29. Domain errors (stable codes, safe messages, statuses) in server code; one translation point (`handleError`) mapping them to `App.Error`, deciding the status; presentation in `+error.svelte` by `code` and status.
30. SvelteKit only classifies its own `HttpError`, `SvelteKitError` and `ValidationError`; any other class is unknown. `handleError` must therefore check `instanceof DomainError` inside the `unknown` branch and map it explicitly.

## Chapter 11: Page Options and Rendering Modes

1.  The page’s `prerender = false` wins. SvelteKit walks the layout chain from the root down and the nearest definition takes precedence, so a root default of `true` can be overridden by any route that must be dynamic. That makes “prerender everything, opt out where needed” a safe default for mostly static sites.

2.  `true` removes the route from the runtime manifest (smaller server, but no runtime fallback if a URL was not prerendered). `'auto'` prerenders what the crawler finds and keeps the route in the manifest so other URLs render on demand. `/blog/[slug]` with the top posts listed in `entries()` and a long tail rendered at request time is the textbook case.

3.  (a) Make the route reachable: link from a prerendered page, add to `prerender.entries`, or export `entries()`: the correct fix when the page really is static. (b) Change to `prerender = 'auto'`: allows dynamic rendering, but then the route stays in the manifest and needs a server. (c) Relax `prerender.handleUnseenRoutes` to `'warn'`/a function: appropriate only when some routes are legitimately unreachable (e.g. empty CMS section), at the risk of 404s in production.

4.  Because `csr = dev` is not a literal, SvelteKit imports the module on the server for analysis, and `mapbox-gl` touches `window`/`document` at import time, which does not exist there. Move the import into `+page.svelte` (or a dynamically imported, browser-guarded path) so that `+page.ts` has no browser-only top-level code.

5.  False. With `ssr = false` the page component and universal `load` run only in the browser, but `+page.server.ts` `load` functions (and actions) still run on the server; the client fetches their data through `__data.json` requests.

6.  (a) Yes: parameters are fine if you provide entries or links. (b) No: reading `url.searchParams` while prerendering is an error. (c) No: pages with actions cannot be prerendered. (d) No: user-specific content violates the “same content for everyone” rule.

7.  Only `<meta http-equiv="cache-control" content="max-age=600">` is added to the document head. Other headers (`x-foo`) cannot be represented in a static file and are not emitted.

8.  It prerenders exactly `/` and `/pricing` and does not follow any links (`crawl: false`), so any other prerenderable route will not be discovered, and routes marked `prerender = true` that are not listed trigger the unseen-routes failure. It does not disable prerendering of the listed pages and does not affect SSR routes.

9.  **b.** The default `concurrency` is 1.

10. JavaScript is single-threaded. Concurrency overlaps waiting time, so while one page awaits a network response another can render. If the build is CPU-bound, rendering work is still serialised on the one thread, so extra concurrency adds nothing.

11. Any four of: `<script>` logic in components (removed), `use:enhance`/progressive enhancement of forms, client-side navigation (links do full page loads), hydration/interactivity such as `onMount` and `$effect`, HMR in development, and anything that relies on client router state.

12. Nothing is rendered. With both `ssr` and `csr` disabled there is no server HTML and no client code to render the app; SvelteKit’s docs warn about exactly this.

13. `{ runtime: 'a', regions: ['x'], foo: { baz: true } }`. Config merges only at the top level, so `regions` and `foo` are replaced wholesale and `runtime` is inherited.

14. The fallback page is served for arbitrary URLs (`/a/b/c`). Relative asset paths would resolve against whatever URL was requested and break, so absolute (`/_app/...`) paths are required.

15. **b.** The hash router determines the route from `location.hash`, which needs no server cooperation. (`inline` bundling and `embedded` do not solve routing, and `trailingSlash` is unrelated.)

16. SSR and prerendering are disabled (the build emits a single fallback `index.html`) and no server logic can be used. Every internal link must start with `#/`, e.g. `<a href="#/settings">`.

17. Arguments: (1) the SPA shell delays first paint by three sequential round trips (HTML, JS, data) and fails entirely if JS fails; (2) public and landing pages still benefit from prerender/SSR for SEO and Core Web Vitals; (3) SSR on authenticated pages still gives faster first paint, and you can opt individual routes into `ssr = false` only for browser-only libraries. Structure: root layout with default SSR, `(marketing)/+layout.ts` with `prerender = true`, `(app)/+layout.ts` with `ssr = false` only if required, or leave it SSR.

18. `split` produces many lazily loaded files (best caching and initial load), `single` produces one JS and one CSS file, `inline` embeds everything in the HTML. For a Capacitor wrapper, `single` (or `inline`) avoids many local file loads. For inlining images too you also need Vite’s `build.assetsInlineLimit` (e.g. `Infinity`) and must import the assets through Vite.

19. Benefit: fewer render-blocking CSS requests, better First Contentful Paint for small stylesheets. Cost: larger HTML, CSS repeated on every page and not cached across navigations. Raising it hurts when shared/global CSS is large and re-sent with each document, so that the lost caching outweighs the saved request.

20. During prerendering `url.origin` is `http://sveltekit-prerender` unless configured. Set `paths.origin` (e.g. from an environment variable at build time) to your real origin.

21. `base` is removed from `$app/paths` in SvelteKit 3. Use `resolve('/pricing')` (and `asset()` for static files): `<a href={resolve('/pricing')}>Pricing</a>`.

22. Prerendering writes files, and `foo` cannot be both a file (from `foo/+server.ts`) and a directory (containing `bar`). Give endpoints extensions: `foo.json` and `foo/bar.json`. Pages avoid the issue with `foo/index.html` or `foo.html`.

23. Navigation listeners attach to the parent of `%sveltekit.body%` instead of `window`, and `params` come from the server rather than being inferred from `location.pathname`. Multiple apps are unsupported because features such as history state manipulation assume a single instance.

24. A prerendered empty shell per route (no server-rendered content), provided no server data needs to be serialised. It is useful for hosts that need a real file at each path, or for SPA-style routes on a static host; it gives no SEO or first-paint benefit.

25. `export const prerender = 'auto'` in `+page.server.ts` and `export const entries = async () => (await popularEvents(200)).map(e => ({ id: e.id }))`. An unlisted id is rendered dynamically at request time because the route stays in the manifest. With `adapter-static` there is no runtime server, so unlisted ids would 404 (or you would need to prerender all 5,000 via `entries`, or add an SPA fallback and client rendering).

26. Not as a mixed file: static analysis is all-or-nothing per file. If any option in the file is non-literal, SvelteKit imports the whole file on the server to evaluate every option. The cost is that browser-only code at module load must be avoided. The mitigation is to put the non-literal option in a separate layout (e.g. `+layout.ts` with `csr = dev`) and keep other files literal.

## Chapter 12: State Management: Server, Client, and URL

1.  Module scope on the server is shared by every request for the life of the process. In local development with one tab you are the only user, so it appears to work; in production one user’s submitted data is returned to the next visitor (and is lost on restart or missing on other instances). Authenticate with cookies and persist in a datastore.

2.  (a) safe, shared infrastructure; (b) unsafe, concurrent requests race and leak; (c) safe, as long as it is only written in the browser; (d) safe, since it is user-independent (bound its size and TTL).

3.  On the server, `session.userId` is assigned during `load` and stays in the shared singleton, so the next request rendering before its own assignment could read the previous user’s id, and concurrent requests overwrite each other. The design violates “no side effects in `load`” and uses a process-wide singleton for per-request data. Return `{ userId: locals.userId }` and carry it through `data`, `page.data` or request-scoped context.

4.  On the server `page` reads from a request-scoped Svelte context (`getContext`), so each render has its own values. Therefore it can only be read during component rendering (initialisation), not in `load`, module scope or after an `await` in server code.

5.  `slug` is computed once and not reactive. Navigating from `/blog/a` to `/blog/b` reuses the component, so `data` changes but `slug` stays stale. Fix: `const slug = $derived(data.post.slug.toUpperCase());`.

6.  When you want a fresh component instance per URL (reset local state, scroll containers, restart animations or timers). You lose preservation of state and DOM across navigations, any exit/enter animation that relied on reuse, and pay the cost of recreating the subtree.

7.  Any three of: the state is not shareable or bookmarkable; it is lost on reload; the server cannot render the sorted list on first load/without JS; Back/Forward do not step through sort changes; SEO and caching treat sorted variants as one URL; it requires JavaScript and a POST for what is a read.

8.  **a.** `replace: true` avoids a history entry per keystroke and `reset: false` keeps scroll position and focus. `shallow` would not rerun `load`; `refreshAll` and `persistState` are unrelated.

9.  URL state is user input. Validate: `sort` must be one of a whitelist, `page` must be a positive integer (otherwise return the default). Canonicalise: omit defaults, so `?page=1` redirects to or is rendered as the same state as no param, keeping one URL per state for caching and SEO.

10. It pushes a new history entry and sets `page.state` to `{ showModal: true }`; `page.shallow` becomes an object describing the target URL (here the current one). It does not run `load`, does not change which components are rendered, and `page.url` still describes the rendered page. `beforeNavigate`/`onNavigate`/`afterNavigate` still fire with `type: 'goto'` and `shallow: true`. Scroll and focus are kept.

11. They land on the URL that was visible (`page.shallow.url`): the full page (e.g. `/photos/123`) and `page.state` is empty. With `persistState: true`, `page.state` is restored after the reload (though `page.shallow` is `null` for the initial load).

12. It is an empty object `{}`, since the server cannot see history state. Content depending on it appears only after JavaScript loads (possible flicker) and is absent without JS, so give the content a real route that works on direct visits, and treat shallow state as progressive enhancement.

13. `import { navigating } from '$app/state'; {#if navigating.to}<Spinner />{/if}`. The pitfall: `navigating` is always an object whose fields are `null` when idle, so `{#if navigating}` is always truthy and the spinner would always show.

14. `$:` is legacy reactivity and does not observe the runes-based `page` object, so it never updates after the first run. Use `const id = $derived(page.params.id);`.

15. During server rendering of components (initialisation of components in the render pass). It throws in `load`, module scope, hooks, or after an `await`. In `load` use the `url` property of the event.

16. Polling (`version.pollInterval`, default one hour), version headers on data requests, remote calls and form action responses, and tab focus/visibility changes. `pollInterval: 0` disables polling only; the other sources and `updated.check()` still work.

17. For example:

    ```ts
    beforeNavigate(({ cancel, type, willUnload }) => {
      if (!dirty) return;
      if (type === 'leave' || willUnload) return cancel(); // native browser dialog
      if (!confirm('Discard unsaved changes?')) cancel();
    });
    ```

    For `leave`, calling `cancel()` triggers the browser’s native unload confirmation.

18. **c.** Captured values are devalue-serialised, stored in `sessionStorage` and keyed by history entry; `restore` is called after the page updates.

19. Auto ids derive from the call site, so both instances of one component share the same id; a duplicate id on mounted snapshots errors in development and the values overwrite each other. Pass distinct explicit ids (e.g. including the item id). Across deployments the stack frame changes with source edits, so stored snapshots from the old version are orphaned; explicit ids keep them stable.

20. `reset` runs on navigations where there is no captured value to restore, such as a fresh link click creating a new history entry. If the same component instance is reused (same layout), typed values would otherwise carry over to the new entry; `reset` clears them.

21. It runs immediately before navigating (not for full-page loads), and returning a promise delays completing the navigation. You return a promise that resolves when `document.startViewTransition` has captured the old state (and call `resolve` inside the transition callback). A slow promise makes the navigation appear stalled.

22. Shallow navigations (modal open/close) also trigger `afterNavigate` with `shallow: true`. Without the check, opening and closing modals would be counted as page views.

23. Copying a query result into local `$state` creates a second source of truth that the query cache and server do not know about, so later refreshes, other components and invalidation diverge. Mutate through `form`/`command` and update the cache with `refresh()`, `set()` or `withOverride()` (optimistic), and read the query directly.

24. Filter: URL (shareable, SSR-visible). Open row: page state via shallow routing if it should close on Back, or URL if it should be linkable. Unsent notes: snapshot (restored on Back without server involvement), or database if they must survive.

25. During SSR the parent has already been rendered into the output by the time a child updates context, so the update is not reflected in the HTML; on the client the update propagates upward, producing a different value after hydration (a flash). Pass state down from layouts/pages to children instead.

26. Only a cookie: the server can read it in `handle`/`load`. `localStorage`, `page.state` and client singletons are invisible to the server render. Read the cookie in `handle` (or a server `load`), put it in `locals`/`data`, and use it for a class on `<html>` via `transformPageChunk` or in the layout.

## Chapter 13: Environment Variables and Server-Only Modules

1.  The `public: true` option on the variable’s entry in `src/env.ts` (`defineEnvVars`). Public variables are imported from `$app/env/public` (or used as `%sveltekit.env.NAME%` in `app.html`); private ones from `$app/env/private`, which only server-only code may import. No naming prefix is required.

2.  `'debug' | 'info'`. The plain-function validator’s return type is inferred by `defineEnvVars` into the generated declaration, so the imported value has the validator’s output type, not `string`.

3.  Without a `schema`, the variable must be set (a missing value yields the “Value is missing” issue), but any string, including an empty one, is accepted. So an empty string passes; if that is unacceptable, add a validator such as `v.pipe(v.string(), v.minLength(1))`.

4.  Any three of: static is read at build time, dynamic at process start; static is inlined into the bundle, dynamic is not; static enables dead-code elimination; changing static needs a rebuild, dynamic only a restart; static is validated at build, dynamic at startup (and during analysis); static is baked into an image, dynamic can differ per deployment.

5.  (a) Make the validator lenient during the build: `schema: building ? v.optional(url) : url` with `building` from `$app/env`. (b) Provide a dummy value to the build job. Prefer (a): no fake secrets in CI and the real requirement is still enforced when the server starts.

6.  For prerendered pages the values cannot be embedded per request, so the page loads a prerendered `_app/env.js` module before application code and takes the value from it, giving one extra (small) module request. The value is the runtime one the server provides. With `static: true` the value is inlined at build and no `env.js` request is needed, but you must rebuild to change it.

7.  **d.** `src/routes/server/...` is explicitly excluded from the `server` directory rule. a is a `.server` filename, b and c are inside `server` directories.

8.  The build fails. SvelteKit checks transitive import chains from browser entry points (`+page.svelte`); even though only `add` is used, `utils.js` re-exports the server-only module, so it could end up in client JavaScript. The error prints the chain `+page.svelte` → `utils.js` → `secrets.ts`.

9.  Change it to a type-only import: `import type { Secret } from '#lib/server/secrets.js';`. Type imports are erased and are not considered.

10. `apiKey: API_KEY` is returned from `load` and serialised to the browser, leaking the secret even though the import itself is allowed in a `+page.server.ts`. Fix: return only the result, `({ items: await fetchItems(API_KEY) })`.

11. Test runners such as Vitest do not distinguish server and browser code, so the check would block legitimate unit tests. Compensate by running a real `vite build` (which enforces the check) in CI.

12. Add `import '$app/server';` at the top of the file. Modules in `node_modules` and outside the project root are exempt from the filename and directory rules, so those conventions alone do not protect a published package.

13. They re-export the explicit modules, so `env` contains only variables declared in `src/env.ts`. Code that relied on arbitrary `process.env` entries or on every `PUBLIC_*` variable being available without declaration breaks: those values are missing until declared.

14. ```ts
    // src/env.ts
    export const variables = defineEnvVars({
      WEBHOOK_SECRET: {},
      PUBLIC_SENTRY_DSN: { public: true, static: true }
    });
    ```

    Code: `import { WEBHOOK_SECRET } from '$app/env/private'; import { PUBLIC_SENTRY_DSN } from '$app/env/public';` (static public mirrors `$env/static/public`).

15. `building` is `true` during build analysis and while prerendering, and `false` when serving requests in production and in `vite dev`. Guard side effects like opening a DB connection or starting a scheduler: `if (!building) connect();`.

16. `src/env.ts` is loaded to produce the env modules, so importing the generated `$app/env/private` or `/public` from it is circular and raises a dedicated error. `$app/env` provides only static facts such as `building` and is allowed.

17. Async validators are not supported: the variable is reported as invalid (“uses an async validator, which is not supported”). The values are validated synchronously when modules are generated and when the server starts.

18. `adapter-node` reads the process environment and does not load `.env` files in production. Fix with `node --env-file=.env build` or inject real environment variables via the platform/orchestrator.

19. (a) dynamic, (b) static (a build-time stamp), (c) dynamic (differs per environment, so one image can be promoted), (d) static (needs inlining for dead-code elimination, and it is the same constant per build target).

20. Fine: analytics ids, public API base URLs, feature flags, publishable keys. Never: secret keys, database credentials, signing secrets, private tokens.

21. The message, and therefore the secret value, appears in build and start-up logs. Rewrite without interpolating the value: `throw new Error('expected a key starting with sk_')`.

22. Set `env: { dir: '../..' }` (path to the root containing `.env`) in `sveltekit({...})` in `vite.config.ts`, and keep `src/env.ts` declarations in the app. Dev and build then load the files from that directory.

23. `server/` only prevents the *code* from being bundled into the browser. Anything it exports and that you serialise through a `+server.ts` response or server `load` result is sent to the client, so private data can still leak. It is enforcement of imports, not access control.

24. It documents the variable. It is emitted into the generated type declarations so that hovering the variable in your editor shows it, and it is a good source for `.env.example` files.

25. Declare it in `src/env.ts` with `static: true` (e.g. `{ public: true, static: true, schema: v.optional(v.string(), 'dev') }`) so the value is read at build time and inlined, since it is not present at runtime.

26. It renders an empty string, because the template substitution uses only the declared public variables (`env[NAME] ?? ""`); a private variable is never emitted into HTML. That is the correct, safe behaviour, but it fails silently, so check the rendered output.

## Chapter 14: Authentication, Sessions, and Authorization

1.  Sessions: advantages are immediate revocation and no stale claims; disadvantages are a datastore read per request and a single point of failure when the store is down. JWTs: advantages are no lookup (lower latency/load) and portability across services; disadvantages are that they cannot be revoked until expiry (without a denylist, which reintroduces a lookup) and claims can go stale. The documentation says session IDs can be revoked immediately.

2.  If the sessions table leaks, hashes cannot be used as cookies because the original token is not recoverable. Plain SHA-256 is fine because the token is 192 bits of random data, so there is nothing to brute-force; passwords are low-entropy and need a slow, salted, memory-hard function.

3.  `httpOnly: true`, `secure: true`, `sameSite: 'lax'`, `path: '/'`. `secure` defaults to `false` during development (on localhost) so cookies work over plain HTTP.

4.  The layout redirect does not protect the page: layout and page `load` functions run in parallel, and layout loads may not rerun on client-side navigations between child pages. Also `allInvoices()` is unscoped and the page does not check `locals.user`, so an unauthenticated request (or one that reaches the page `load` directly, e.g. via `__data.json`) can read all invoices. Fix: check the user in the page `load` (`requireUser()`) and scope the query to that user; add a guard in `handle`.

5.  (1) Layout loads do not necessarily rerun on each navigation; (2) layout and page loads run in parallel, so the page can fetch data before the redirect takes effect. Not covered at all: `+server.ts` endpoints, form actions, remote functions (also page loads of other routes outside the layout).

6.  It sees the old `locals.user` (typically `null`) because actions do not rerun `handle`; the cookie is set for the *next* request. Fix: set `locals.user` and `locals.session` in the action after creating the session (and redirect with 303 so the next request goes through `handle` properly).

7.  Static assets and already-prerendered pages are served without running `handle`. Therefore no authenticated or user-specific content can appear in prerendered pages: they are public by construction.

8.  For queries, `handle` sees the URL of the internal remote endpoint (`/_app/remote/...`), not the page URL, so the prefix never matches; for forms/commands the URL is a client-reported page. Protection must be inside the function: `requireUser()` and resource-level checks against `locals`.

9.  ```ts
    export function requireUser() {
      const event = getRequestEvent();
      if (event.locals.user) return event.locals.user;
      if (event.isRemoteRequest) error(401, 'Sign in required');
      redirect(303, `/login?next=${encodeURIComponent(event.url.pathname + event.url.search)}`);
    }
    ```

    `event.isRemoteRequest` distinguishes them. `command` cannot redirect (redirects are allowed in `form`, `query` and `prerender`, not in `command`), so the client has to decide what to do with the 401.

10. **c.** `url.pathname` in `form`/`command` describes the page the client claims to be calling from and can be manipulated. The others derive from the cookie-validated session or compare validated input to it.

11. Reusing an anonymous session id enables session fixation: an attacker who planted a known id in the victim’s browser would share the post-login session. Create a fresh session (new random token) on login and other privilege changes.

12. It makes the unknown-user path perform the same expensive hash as the wrong-password path. Without it, requests for non-existent accounts return noticeably faster, letting an attacker enumerate valid accounts by timing.

13. Per-IP alone is bypassed by distributed attackers; per-account alone lets an attacker lock out a victim (or an attacker rotates IPs freely). The chapter throttles by `ip:email` and by IP alone, combining both dimensions.

14. In-memory state is per process, so each replica has its own counters and an attacker effectively gets N times the budget (and counters reset on restart). Use a shared store (Redis or the database). If the server sees only the proxy’s address, every user shares one bucket; configure `ADDRESS_HEADER`/`XFF_DEPTH` (adapter-node) for a trusted proxy.

15. For an external URL, SvelteKit 3’s `redirect` throws an error (external redirects are not allowed without `{ external }`), so the user gets a 500 rather than a bounce to evil.example. That is a backstop, not validation: it turns a user-input error into a server error, and `{ external: true }` elsewhere could reintroduce the problem. Validate and fall back to a safe path.

16. `/app` → `/app`; `//evil.com` → `/app`; `/\evil.com` → `/app`; `https://evil.com` → `/app`; `javascript:alert(1)` → `/app`; `/a?b=c#d` → `/a?b=c#d`.

17. The callback is a top-level cross-site navigation from the provider; `strict` cookies are not sent on it, so state/verifier would be missing. `redirect` is told `external` because the provider is another origin, which SvelteKit 3 refuses by default; an allow-list of the provider origin is the narrowest form.

18. A constant-time comparison avoids leaking the state through timing (defence in depth). Deleting the cookies unconditionally makes them single-use, so a replayed callback or an error path cannot leave reusable state/verifier values.

19. The attacker’s identity (unverified email equal to the victim’s) is linked to the victim’s account, giving them access. Mitigations: key identities by `(provider, subject)`, require `email_verified`, and require an authenticated confirmation (e.g. the logged-in user links the provider) before linking to an existing account.

20. The CSRF origin check runs only in production, and the request’s origin is derived from `request.url`, which is wrong behind a proxy that does not forward the host. Configure `paths.origin` in `sveltekit({...})` (or `HOST_HEADER`/`PROTOCOL_HEADER` for adapter-node with a trusted proxy).

21. **b.** List the exact origin in `csrf.trustedOrigins`. `'*'` trusts everyone, `sameSite: 'none'` is unrelated to the origin check and weakens cookies, and `checkOrigin` was removed in 3.0.

22. No. Remote function calls (non-GET) from another origin are always rejected; `trustedOrigins` only applies to non-remote form-style requests. Cross-origin clients must use ordinary `+server.ts` endpoints instead.

23. The origin check applies to form-style content types (urlencoded, multipart, text/plain, or no content type), not `application/json`, so it is not what governs this. Browser cross-origin access is governed by CORS, which you implement (OPTIONS handler and headers). A native mobile app is not subject to CORS, and bearer tokens are not ambient credentials, so CSRF does not apply.

24. Marketing: prerendered, no auth. `/admin`: coarse role guard in `handle` plus `requireRole('admin')` in each load/action. Dashboard: `requireUser()` in loads and actions, and in every remote function body. A `handle` prefix check alone would be bypassed by remote function calls (query URL is the remote endpoint; form/command URL is client-reported) and gives no resource-level protection.

25. `invalidateAllSessions(userId)` to delete existing sessions, then `createSession(userId)` for the current device and `setSessionCookie`, update `locals`, and optionally notify the user. Also rate limit the endpoint and re-hash with the current parameters.

26. Make the scoped lookup the only way to reach data: e.g. a repository function `getProjectForUser(userId, projectId)` whose query includes the owner/membership condition, and make `deleteProject(userId, id)` take the principal and include it in its `WHERE` clause (or use database row-level security). With no unscoped accessor exported, forgetting the check is a type/compile error or returns no rows.

## Chapter 15: Security Hardening: CSP, CSRF, and Headers

1.  In `sveltekit({ csp: { ... } })` inside `vite.config.ts`. Write keywords unquoted, e.g. `'script-src': ['self']`; SvelteKit adds the quotes the header needs.

2.  When the effective script policy (`script-src`, else `default-src`) does not contain `'unsafe-inline'` (or contains `'strict-dynamic'`). If `'unsafe-inline'` is present, no nonce/hash is added, since browsers would ignore `unsafe-inline` next to a nonce.

3.  `nonce` uses a random value per response; `hash` uses a SHA-256 of each inline element; `auto` uses nonces for dynamic pages and hashes for prerendered ones. `nonce` fails a build that prerenders, because a prerendered page is the same file for everyone, so the nonce would be fixed and guessable.

4.  `frame-ancestors`, `report-uri` and `sandbox`. Clickjacking protection for that page must come from a header set by the host or CDN.

5.  The build fails, because the nonce placeholder cannot be filled safely on a prerendered page. Resolve by removing the placeholder from the shared template (moving the code into bundled JS or a non-prerendered setup), or by not prerendering those pages / using a hash-compatible approach.

6.  In dev SvelteKit injects `'unsafe-inline'` into style directives and drops nonces/hashes there because Vite injects styles for HMR. Test the policy with `vite build && vite preview`.

7.  SvelteKit does not nonce scripts placed in `<svelte:head>`, so the browser blocks it. Compliant options: self-host/bundle it (import from your code), or load it from a nonced snippet in `app.html` (with `'strict-dynamic'`) or allow-list its host in `script-src`.

8.  It sends violation reports only, without enforcing. Without `report-uri`/`report-to` it is useless, so SvelteKit throws a configuration error.

9.  `svelte-trusted-html` (required unless all pages have `csr = false`) and `sveltekit-trusted-url` (required when `serviceWorker.register` is true), when `require-trusted-types-for 'script'` is set. It does not make `{@html}` safe or replace sanitisation.

10. Rejected when the method is POST/PUT/PATCH/DELETE, the content type is form-style (urlencoded, multipart, text/plain) or absent, the `Origin` differs from the app origin, and it is not in `trustedOrigins`. (a) rejected; (b) not checked by this mechanism (CORS governs it); (c) rejected: `curl -d` sends `application/x-www-form-urlencoded` and no `Origin`, and a missing `Origin` never matches; (d) never checked, so a state change on GET is your bug.

11. The check is skipped in development. Test with a real form post against a production build in the deployed topology.

12. The CSRF check runs before `handle`, so rejected requests never reach your hook; logic in `handle` cannot see or rely on them.

13. `csrf: { trustedOrigins: ['https://pay.example'] }`. `'*'` removes protection for every origin. It does not allow remote function calls: those ignore `trustedOrigins`. Note that this works only when the post comes from the user’s browser (an auto-submitted form on `pay.example`, which sends `Origin: https://pay.example`); a true server-to-server webhook usually sends no `Origin`, so it must post JSON or go to a separate service.

14. Set `paths.origin: 'https://your.domain'` (build-time config; no trust needed beyond correctness), or with adapter-node set `PROTOCOL_HEADER`/`HOST_HEADER` to the forwarded headers (only valid if a trusted proxy overwrites them).

15. ```ts
    const h: Handle = async ({ event, resolve }) => {
      const res = await resolve(event);
      const headers = new Headers(res.headers);
      headers.set('x-content-type-options', 'nosniff');
      headers.set('referrer-policy', 'strict-origin-when-cross-origin');
      if (!dev) headers.set('strict-transport-security', 'max-age=63072000; includeSubDomains');
      return new Response(res.body, { status: res.status, headers });
    };
    ```

    Prerendered pages are served as static files and bypass `handle`; set their headers at the platform (`_headers`, `vercel.json`, nginx).

16. HSTS is sticky: if any subdomain lacks HTTPS it becomes unreachable, and preload is hard to undo. Start with a short `max-age`, no `includeSubDomains`/`preload`, then increase after verifying.

17. `//evil.example` is external and throws (500) in 3.x. With `{ external: true }` it redirects. `javascript:` with `external: true` throws; only an explicit allow-list entry permits it (never do that). Passing `?next` straight through relies on an error as validation and turns bad input into a 500; validate and fall back.

18. The server can be aimed at internal services or metadata endpoints with the server’s network position, regardless of user identity. Controls: https-only (prevents plaintext/odd schemes), no credentials in URL, no IP literals (blocks direct internal addresses), host allow-list (restricts destinations), `redirect: 'manual'` (stops redirects to internal hosts), timeout (bounds resource use).

19. The attacker’s DNS can return a public address at check time and a private one at fetch time. Robust variant: resolve once and connect to that vetted IP (validating at connect time), or use an isolated egress proxy/service that blocks private ranges.

20. The whole `post` row (including unpublished/internal columns) and the whole `author` row (e.g. email, password hash) are serialised to the browser. Return explicit projections: select only needed fields and map to view types.

21. Which response headers of inlined fetches are included in the serialised payload; default is none. The body is inlined verbatim, so the full upstream JSON is shipped even if the page uses two fields.

22. Returning a secret or sensitive field from a server `load`, e.g. `return { apiKey: API_KEY }` or a full DB row; also sensitive data in a `+server` JSON response.

23. Default 512 kilobytes; yes, it applies including while streaming/chunked. `Infinity` disables the limit (you must check yourself). Keep a low global limit and move large uploads to a separate service or direct pre-signed uploads to object storage.

24. Without it a client could request refreshes of unbounded query instances, so one mutation triggers huge work. Arguments beyond the limit are recorded as failures instead of executed. For a filter/sort table, a limit of 1-3 (the current instance and perhaps one more) suffices, since only the displayed instance needs updating.

25. N queries per request (latency, DB load) and an attacker-controlled N (DoS amplification). Fix: cap the array length and use one bounded query (`WHERE id IN (...)`), returning a lookup function.

26. Marketing (prerendered): headers and CSP meta from the platform/SvelteKit meta tag; no CSRF surface; DoS: CDN caching. Dashboard: `handle` headers + `csp` config nonces; origin-checked remote calls (same-origin only); DoS: `requested(limit)`, validation, rate limits. Public JSON API: your code/`handle` for headers and CORS; JSON is outside the form-style origin check; DoS: `BODY_SIZE_LIMIT` and rate limiting. CSP report endpoint: your code, application/csp-report is not form-style so no `trustedOrigins` needed; DoS: size cap and rate limit.

## Chapter 16: Performance, Caching, and Preloading

1.  Any four of: code-splitting (statically importing a heavy library in the root layout); asset preloading (SPA mode, which has no server-rendered head); file hashing (serving `_app/immutable` with short cache lifetimes); request coalescing (universal `load` calling remote APIs from the browser); parallel loading (`await parent()`); data inlining (using global `fetch` instead of the provided one); conservative invalidation (reading `url` wholesale instead of `searchParams.get(...)`); prerendering (reading `url.searchParams` or using actions); link preloading (never opting in, or preloading side-effectful loads).
2.  `preloadStrategy` was removed; `modulepreload` is always used. `linkHeaderPreload` (default `false`) sends preload hints as an HTTP `Link` header instead of `<link>` elements for dynamically rendered pages. Behind Nginx or Apache the default header size limits can be exceeded by a large dependency list, producing rejected responses.
3.  A prerendered page is a static file with no per-response headers to carry `Link`; the source falls back to `<link>` tags when prerendering (or when the prerender default is `true`).
4.  No network request. During SSR the response was inlined with a `data-ttl` of `30 - Age`; the client kept it in memory and replays it for matching `fetch` calls (default cache mode) until the TTL, measured with `performance.now()`, expires. At 10 seconds it is still fresh.
5.  They are sent with `Cache-Control: private, no-store` unconditionally. Cache the page HTML (`setHeaders`/`handle`), the upstream data, or use remote `query` caching.
6.  It applies `public, s-maxage=600` to every response, including pages rendered from user-specific data (cookies/session), so a shared cache can serve one user’s HTML to another. It also overrides any policy a route set itself. Set `private` for personalised output, or only add caching headers for routes known to be anonymous, and check `cache-control` is not already present.
7.  Dev is unbundled, uses HMR, lacks production preload tags, and inlines styles; production behaviour differs. Preview runs in Node, so it does not reproduce adapter-specific behaviour such as the `platform` object, Vercel ISR, or Cloudflare runtime constraints (and CDN behaviour).
8.  `const [a, b] = await Promise.all([getAccount(locals.userId), getInvoices(locals.userId)]);`. Neither call depends on the other’s result because both need only `locals.userId`, so the wall-clock time becomes the slower of the two.
9.  Put the user on `event.locals` in `handle` (or read it with `getRequestEvent()` in a shared helper), so every `load` has it without waiting for the layout.
10. **c.** Viewport/eager preloading applies only to links in the DOM right after navigation, and it fetches code only.
11. The preload listeners are never installed (the check happens once at client start), so neither hover/tap preloading nor viewport/eager code preloading occurs. There is no per-link override.
12. Preload runs `load`, so a hover (even without a click) increments the counter. Make `load` idempotent and side-effect free, and move the write to an action or remote `command`/`form` triggered by an explicit user action; alternatively disable preloading for those links with `data-sveltekit-preload-data="false"`.
13. For a redirect: `{ type: 'redirect', location }`. For an error status: `{ type: 'error', status, error }`. For a non-route or external URL, it rejects (throws) rather than returning a result.
14. It discards the pending preload (`discard_load_cache`) and starts the new one; only one preloaded navigation is retained at a time.
15. Layout loads run in parallel with page loads and do not rerun on every client navigation, so a layout-only guard is bypassable (security) and forcing every page to `await parent()` serialises loads (performance). Guard in `handle` or in each page’s server `load`.
16. When many independent components each need a small keyed piece of data (N+1 pattern): `query.batch` coalesces calls within one macrotask into one request and one backend query, while keeping data co-located with the component that uses it.
17. SvelteKit cannot know which weights/subsets a page needs, so preloading all would waste bandwidth. `resolve(event, { preload: (input) => input.type === 'font' ? input.filename.endsWith('inter-latin-400-normal.woff2') : true })`.
18. `filename`, the source file path relative to the project root. Fonts have hashed output paths, and `filename` gives a stable name to match; JS and CSS are bundled and have no single source file.
19. The image must exist on disk at build time (and be referenced statically or through the `?enhanced`/glob import). Images from a database, CMS or user uploads, known only at runtime, must use a CDN/dynamic service.
20. Thousands of tiny `.svelte` files slow Vite’s dependency optimisation, especially when imported both via umbrella and subpath imports. This is a development-time problem; production tree-shakes either way.
21. `split` (default) for most web apps with HTTP/2+: lazy per-route chunks. `single` for environments where parallel loading is poor or one cache entry is desired, such as a wrapped mobile/desktop app loading from disk. `inline` for a single self-contained HTML file usable without a server (requires raised `assetsInlineLimit` and Vite-imported assets).
22. Probably yes: 3 KB inlined removes a request and helps FCP for first-time visitors. In a long-session app the browser cache would have served the stylesheet for free, so inlining enlarges every HTML response and defeats caching.
23. `304 Not Modified`, with `ETag`, `Cache-Control`, `Vary`, `Date`, `Expires`, `Content-Location` and any `Set-Cookie` preserved. The page was still rendered (the ETag is the hash of the rendered HTML), so bandwidth was saved but not CPU.
24. `build` -\> `immutable` and `files` -\> `assets` from `$app/manifest` (plus `prerendered` and `routes`); `version` -\> `$app/env`; `base` handling -\> `resolve()` from `$app/paths`. `self` comes from `$app/service-worker`.
25. Data and remote responses are `private, no-store` and live queries are long-lived streams that should not be cached or cloned. Check `Cache-Control: no-store` on the response (the docs say live queries must not be cached by a service worker for this reason).
26. Browsers check for a new worker on full page navigations and functional events; client-side navigation does neither, and a new worker waits for old-worker tabs to close. SvelteKit calls `registration.update()` in error recovery when version polling finds a redeploy; you can call `registration.update()` from `afterNavigate` in the root layout, or prompt a reload using `updated.current`.
27. A live region injected by SvelteKit that reads the new `<title>`. Every page needs a unique, descriptive `<title>` (via `<svelte:head>`).
28. Example: prerender or `s-maxage` + `stale-while-revalidate` the article page (`setHeaders` in the page `load`, or one `handle` rule for `/articles/*`), with no user data in the HTML; render the comment widget client-side or via a separate uncached endpoint/remote `query` that returns `private, no-store` and uses the session cookie. Vary nothing on cookies for the article route; ensure no `Set-Cookie` is sent on the cacheable response, since many CDNs refuse to cache responses that set cookies.

## Chapter 17: Observability: Tracing, Logging, and Instrumentation

1.  `experimental.tracing` and `experimental.instrumentation`. They were replaced by the top-level `tracing: { server: boolean }`; a config that still sets them fails the build with an error saying the key “has been removed” and that tracing is configured via `tracing.server`.
2.  No. With tracing off the internal `record_span` helper calls the wrapped function with a noop span and the `@opentelemetry/api` import is eliminated from the bundled runtime, which is why the package is only an optional peer dependency.
3.  Any four of: `handle` (root and sequenced), server `load`, universal `load` run on the server, form actions, `+server` handlers, remote functions. `+server` handlers (the `sveltekit.endpoint` span) were added in 3.1.
4.  `sveltekit.handle.root` \> `sveltekit.handle.sequenced.auth` \> `sveltekit.handle.sequenced.rateLimit` \> `sveltekit.resolve` \> `sveltekit.load`.
5.  They are served before or without `handle`; static assets and prerendered pages bypass it, and spans are created inside `handle`/`resolve`.
6.  `error(404)`: attributes `...result.type = 'known_error'` with status/message, no exception, status not ERROR. `error(503)`: same attributes, plus a recorded exception and span status `ERROR`. `new Error('boom')`: `result.type = 'unknown_error'`, exception recorded with stack, status `ERROR`.
7.  In a `handle` (for example an `auth` handle) or any server code with the event, call `event.tracing.root.setAttribute('app.tenant.id', id)` (or `setAttributes`). The root span is the `sveltekit.handle.root` span, so the attribute is on the root of every trace for the request.
8.  The new span’s parent is `sveltekit.load` (the active span), because SvelteKit uses `startActiveSpan` and the SDK’s `AsyncLocalStorage` context manager propagates it. Without `span.end()` the span is never exported, leaving a truncated trace.
9.  In dev it is resolved per request and imported through Vite’s module runner before the server is configured for that request. In production with adapter-node it is part of a build-time facade entry that imports it natively before dynamically importing the server.
10. (1) Import the env initialiser; (2) import `instrumentation.server.js`; (3) dynamically import the real entry (`start.js`) and re-export its exports. Because the application is imported only after the instrumentation has registered its hooks, libraries are intercepted when first imported.
11. Dev fails with an `adapter_instrumentation_unsupported`-style error naming the file and adapter, on the first request that loads the instrumentation file (the check runs when the dev server resolves it).
12. `src/env.ts` is evaluated when `$app/env/*` modules are imported, before `instrumentation.server` can start, so anything it imports is loaded before interceptors exist and cannot be wrapped.
13. At startup the process cannot resolve `pg` (adapter-node keeps `dependencies` external; `devDependencies` are not installed in the image), so it fails with a module-not-found error. Move `pg` to `dependencies`.
14. (1) Shared chunks: code imported by the instrumentation file is bundled with application code, so the app evaluates before interceptors are registered. (2) The library is inlined/transformed into an application chunk so no bare import remains. `ssr.external` addresses the second.
15. `register-hooks.mjs` uses `module.registerHooks()` synchronously and requires Node 22.22.3+/24.11.1+/25.1.0+/26+; on older versions `register()` throws. Fallback: check `supportsSyncHooks()` and otherwise use `createAddHookMessageChannel()` with `node:module`’s async `register('import-in-the-middle/hook.mjs', ...)`.
16. (a) `OTEL_TRACES_SAMPLER=parentbased_traceidratio` and `OTEL_TRACES_SAMPLER_ARG=0.1`. (b) Sampling then becomes deployment configuration that can change per environment without a code change or rebuild.
17. Spans and metrics are exported in batches; without `await sdk.shutdown()` the last batch (often the failing request) is lost. adapter-node emits `process.on('sveltekit:shutdown', reason)` with `SIGINT`, `SIGTERM` or `IDLE`.
18. Errors generated by SvelteKit itself, such as 404, 405, 413, with safe `{ status, message }`. Since `handleError` is called for all errors (not only unexpected ones), logging every kind at error level would flood alerts with 404s, validation failures and expected `error()` outcomes.
19. `issues` (the array of Standard Schema issues). No: `validation` is server only; the client hook’s kinds are `app`, `framework`, `unknown`.
20. Augment `App.Error` with an optional `requestId`, generate the ID in `handle` (`locals.requestId`), return it from `handleError`, display it in `+error.svelte`, and log it (with `traceId`) in the same line and as an attribute on the root span. Support searches by that ID.
21. It logs `{ route: '/projects/[id]' }`. The route template has bounded cardinality and contains no identifiers, so it is safe and useful for aggregation, while pathnames explode label cardinality and may contain sensitive IDs.
22. SvelteKit’s spans are active spans, and the SDK context manager propagates the active span through async calls, so `trace.getActiveSpan()` returns the current request’s span anywhere in that async call chain.
23. The handle measures until `resolve` returns a `Response`; for streamed responses that is when headers are ready, before the stream completes. The span tree (`sveltekit.load` durations and the root span) shows total work; the client side shows render completion.
24. Sampling undercounts (and sampling decisions may be parent-based). Record metrics directly with the OpenTelemetry metrics API (or Prometheus) in `handle`: a duration histogram and error counter labelled by route ID, method and status code, not URL or user.
25. Errors in DOM event handlers, timers/callbacks, and unhandled promise rejections outside SvelteKit-managed flows. Use `window` `error` and `unhandledrejection` listeners (registered in the client `init` hook).
26. `sendBeacon` queues the request so it survives page unload and does not block navigation; a plain `fetch` can be cancelled when the page is torn down (unless `keepalive` is set).
27. Beyond polling (`version.pollInterval`, default one hour), it can become `true` after focus, tab visibility changes, server-data navigations and remote calls when a new `version.name` is detected. Operationally: show a reload prompt and log it to measure how long clients stay on stale code after a deploy, which bounds how long you must keep backward compatibility.
28. Run `node --inspect build` (or `--inspect-brk`) and attach DevTools or VS Code. Enable `build.sourcemap` so breakpoints map to source lines.
29. **b.** Interceptors must be registered before libraries are imported, and the adapter facade arranges for the instrumentation file to run first.
30. Logs: one structured line per request with `requestId`, `traceId`, route ID and status; unknown errors logged at `error` in `handleError` (by `kind`), 404/validation at info/warn. Spans: SvelteKit marks `ERROR` only for 5xx and unknown errors, so span-status-based alerts already exclude 4xx. Metrics: a counter incremented in `handle` for `status >= 500`, labelled by route ID and status, recorded on every instance (not sampled), alerting on the ratio to the duration histogram’s count. Sampled traces then serve diagnosis, not alerting.

## Chapter 18: Deployment and Adapters

1.  Phase one: Vite builds client, server and service worker, and prerenders using the server build. Phase two: the adapter’s `adapt(builder)` reshapes the output for a target. Phase two is platform-specific; prerendering happens in phase one.
2.  In `sveltekit({ adapter })` in `vite.config.ts`. `npx sv add sveltekit-adapter="adapter:<name>"` installs and configures it.
3.  `name` and `adapt`. `emulate` supplies `event.platform` in dev, build and preview; `supports.read` says whether `read()` works in production for a route; `supports.instrumentation` says whether `instrumentation.server.js` can be loaded.
4.  It delegates to whichever adapter it detects, so it has no options of its own. Replacing it adds the adapter to the lockfile, speeds CI installs and enables adapter options.
5.  Packages in `devDependencies` are bundled by Rolldown; packages in `dependencies` stay external. Keep native modules, instrumented libraries and packages that read their own files in `dependencies`.
6.  `.env` files are not loaded in production. Run `node --env-file=.env build` or supply real environment variables.
7.  `Content-Encoding: br`, `Vary: Accept-Encoding`, an ETag specific to the brotli variant, and `Cache-Control: public,max-age=31536000,immutable`.
8.  Node is single-threaded and compression is CPU work, so the proxy or load balancer does it better. In a custom server use `@polka/compression`, because SvelteKit streams and the popular `compression` package does not support streaming and can cause errors.
9.  Set `PROTOCOL_HEADER=x-forwarded-proto` and `HOST_HEADER=x-forwarded-host` (runtime, image stays portable), or set `paths.origin` (build time, pins one canonical origin but is baked into the build).
10. When the server can be reached directly or the proxy does not overwrite those headers: clients can spoof origin and IP, defeating CSRF checks and IP-based limits.
11. `XFF_DEPTH=3`; entries are read from the right, skipping three trusted hops. The left-most entry is client-controlled and spoofable.
12. It is evaluated at build time, so one image would carry one hostname. Use the header variables instead.
13. Stop accepting new connections; let in-flight requests finish and close idle connections; after `SHUTDOWN_TIMEOUT` force-close the rest. Then `sveltekit:shutdown` is emitted, after all connections are closed. Reasons: `SIGINT`, `SIGTERM`, `IDLE`.
14. Live connections count as in-flight, so each deploy can wait until `SHUTDOWN_TIMEOUT` fires. Lower `SHUTDOWN_TIMEOUT` to fit the orchestrator’s grace period.
15. `SHUTDOWN_TIMEOUT` is only honoured by the default `node build` server; a custom server must implement its own graceful shutdown.
16. The process fails at startup with a module-not-found error for `pg` (dependencies are external). Add a stage that runs `npm ci --omit=dev` and copy its `node_modules`.
17. `proxy_buffering off`; otherwise nginx buffers the response and clients receive nothing until the end.
18. The build must run under Bun, because the adapter calls Bun’s build API. `--bun` overrides Vite’s Node shebang so the build runs in Bun.
19. Startup fails because an unknown variable with the prefix exists. It catches typos and collisions with variables you do not control.
20. With `ssr = false`, prerendering saves an empty shell rather than rendered HTML. `strict` fails the build if some page or endpoint is not prerendered and no fallback exists, preventing unreachable routes.
21. `ssr` controls how a route renders; `fallback` controls which static file answers unknown URLs. Set `ssr = false` in the root layout and use `prerender = true; ssr = true` on the marketing pages, with `fallback` configured.
22. Set `paths.base` to `/blog` (for example from `BASE_PATH`), generate a `404.html` fallback, and write links with `resolve()` from `$app/paths`.
23. `env` and `waitUntil` from `cloudflare:workers`, `cf` on `request.cf`, and the global `caches`; also generate types with `wrangler types` and use Wrangler 4.
24. They require custom classes exported from the worker, which the adapter does not support. Deploy a separate worker for them and bind to it.
25. The Edge runtime. `nodejs22.x`, `nodejs24.x` and `bun1.x` remain. Move the route to a Node runtime and use CDN, ISR or prerendering for latency.
26. `expiration` is required, `allowQuery` controls the cache key. ISR on a prerendered route has no effect.
27. A page that renders the logged-in user’s name from a session cookie is cached and then served to the next visitor, who sees the first user’s content.
28. They describe the deployment, so their build-time values stay correct at run time, and some are not available to functions at run time at all; the adapter documentation therefore requires `static: true`, which inlines them (and allows dead-code elimination).
29. `builder.routes` replaced `createEntries`; `generateServerInstance` (or `builder.manifest`) replaced `generateManifest`. The entry must call `await server.init({ env, read })` and then `server.respond(request, { getClientAddress, platform })`.
30. Sample answer: adapter-node on Cloud Run suits `query.live` (long connections, though Cloud Run request timeouts and concurrency apply), gives control over shutdown (`SHUTDOWN_TIMEOUT` below the grace period) and runs in a region next to Postgres, but skew handling during rollouts is yours. Vercel gives skew protection and ISR, but function duration limits and buffering fit live connections poorly, and the Edge runtime is gone, so compute must be pinned to `fra1`. Recommend adapter-node on Cloud Run in the Frankfurt region because of the live dashboards, with `version.name` and retained assets for skew.

## Chapter 19: Building Libraries with svelte-package and Testing

1.  It reads `src/lib` and writes `dist`: Svelte preprocessed, TypeScript transpiled, `.d.ts` generated, other files copied. It validates your own `package.json` (it does not generate one since v2).
2.  `-w/--watch`, `-i/--input` (default `src/lib`), `-o/--output` (default `dist`), `-p/--preserve-output`, `-t/--types` (default true), `--tsconfig`. `-p` stops the output directory being emptied first.
3.  `import { clamp } from '../math.js'`. The `imports` mapping (`#lib`) points at source layout that does not exist in a consumer’s package, so `svelte-package` (3.0) rewrites `#` aliases to relative paths.
4.  Otherwise consumers can end up with two Svelte copies, which breaks runes and context in confusing ways; the peer range lets the app own the single version.
5.  `types` first so TypeScript matches it, then `svelte` to signal Svelte-aware tooling. Use `default` when the library has no components and works in non-Svelte projects (for example a store library).
6.  Require `moduleResolution` of `bundler`, `node16` or `nodenext` so TypeScript reads `exports`; or add `typesVersions` mapping the sub-path to the `.d.ts`. Drawback: once used, all type imports, including the root (`index.d.ts`), must be declared through it.
7.  It marks CSS files as having side effects so they are kept even if their exports are unused (webpack compatibility). If a script with side effects is not listed, bundlers may drop it in production and break consumers.
8.  Node’s ESM algorithm requires full specifiers, and TypeScript does not rewrite extensions; the emitted file is `index.js`, so you write `.js` (not `.ts`).
9.  The `.d.ts.map` files contain relative paths into the sources; the original `.ts`/`.svelte` files must exist on disk at those paths in the package.
10. `$app/env` exists only in SvelteKit builds, so non-SvelteKit consumers cannot resolve it. Use `BROWSER` from `esm-env`. Pass the URL (or a callback) as a prop instead of reading `page.url`.
11. The module is shared by all requests on the server, so per-user state leaks between users. Use context or per-use instances.
12. Breaking: removing a path from `exports`, removing a condition, changing `svelte` to `default`. Not breaking: adding a new path.
13. Files named `.server.` or in a `server` directory are server-only inside an app, but the import-chain check exempts `node_modules`, so published files are not protected by name. Add `import '$app/server'` (or `$app/env/private`) in them so importing on the client throws.
14. The library must list `@sveltejs/kit` as a peer dependency; the consuming app needs both experimental flags; the file cannot be in a server-only directory.
15. It packs with `npm pack` and lints `exports`, `types`, `files` and related fields. Manually check the file list for spec files, secrets and the presence of `dist` (and `src/lib` if shipping declaration maps).
16. There is no testing page in the official docs, so testing guidance beyond `sv add` and changelog notes must be labelled as the author’s practice.
17. `client` runs `*.svelte.{test,spec}` files in a real Chromium via Playwright browser mode; `server` runs the other `*.{test,spec}` files in Node. The `include`/`exclude` globs decide, driven by the `.svelte.spec` naming convention.
18. It fails tests that make no assertions, catching vacuous tests that always pass.
19. It passes for any thrown value, including unrelated errors. Better: catch and assert `isRedirect(e)`, plus `status` and `location`, to prove it is the intended redirect.
20. `getRequestEvent()` only works inside a request, so outside one it fails; mocking supplies a stub event.
21. The server-only import check is disabled under Vitest. It can hide an accidental client import of server code; catch it with a production build or E2E.
22. Either works, since 3.x ignores `+` files containing `test`, `spec` or `stories` in routes, but without the plus it is not confused with a route file. The other choice is not harmful.
23. `POST({ request: new Request(url, { method: 'POST', body: JSON.stringify(data) }) } as Parameters<typeof POST>[0])`; then `await expect(call(...)).rejects.toSatisfy((e) => isHttpError(e, 400))`.
24. CSRF/origin checks, real cookie serialisation or header validity, `setHeaders` conflicts, routing and rendering, `+error.svelte` behaviour (any two).
25. Put logic in plain functions (for example in `#lib/server/...`), keep the `*.remote.ts` file as a schema plus thin call, unit test the function and schema, and test the wrapper end to end.
26. It tests what ships (preload tags, bundles, hydration). Preview runs in Node and does not apply adapter-specific behaviour such as `platform`, ISR or edge/worker constraints.
27. A server-rendered element is clicked before hydration attaches handlers, so a form posts normally or the click is lost. Avoid by waiting for an explicit hydration signal (for example a `data-hydrated` attribute set in `onMount`) and by using auto-waiting web-first assertions instead of fixed sleeps.
28. Log in once in a setup project, save `storageState`, and reuse it in the other projects, avoiding UI login per test. The file must not be committed to version control.
29. **b.** Errors reported by a `pageerror`/console listener expose hydration mismatches that otherwise pass quietly; the other options hide or mask problems.
30. Sample: unit tests for validators, `requireUser`-style helpers, session lookup and `params.ts`; `Request`-based tests for the webhook handler (signature check, bad payload, idempotency), each action’s failure and success shapes and the `handle` branches; thin remote wrappers tested with logic as plain functions; component tests for the form UI; Playwright for login, one action flow, one remote-function flow with its single-flight update, and a no-JS form test. CI: install, `svelte-kit sync`, `check`, lint, Vitest, build, Playwright with traces and report upload on failure.

## Chapter 20: Migrating from SvelteKit 2 to 3, and a Capstone Architecture

1.  Node 22.17, TypeScript 6, Svelte 5.57.1, Vite 8.0.12, `@sveltejs/vite-plugin-svelte` 7.
2.  `package-json` and `tsconfig` are prerequisites. `collect-migration-instructions` writes `MIGRATION_TASKS.md`, a checklist of changes that could not be automated.
3.  The codemod rewrites recognisable syntax but cannot judge runtime behaviour. Examples: triaging `handleError` by `kind`, configuring `paths.origin`/proxy headers for `ORIGIN`, symmetric param matchers for `resolve()`, updating tests that assert statuses, auditing `server` directories.
4.  In `sveltekit({ adapter, paths: { origin: 'https://x.dev' }, csrf: { trustedOrigins: [...] } })` in `vite.config`: top-level options; `prerender.origin` becomes `paths.origin`; `checkOrigin: false` is removed (CSRF always on) and allowed origins go in `trustedOrigins`.
5.  `import { foo } from '#lib/util/foo.js'`, with `"imports": { "#lib": "./src/lib/index.js", "#lib/*": "./src/lib/*" }` in `package.json`.
6.  The module no longer exists (`$app/stores` is removed), so the import fails. Use `import { page } from '$app/state'` and `{page.url.pathname}`. `page.url` is a `ReadonlyURL`, so `searchParams.set` is a type error; copy with `new URL(page.url.href)`.
7.  `resolve('/blog/[slug]', { slug })` and `asset('img/a.png')`. `asset` and `resolve` path arguments no longer start with `/`; only route IDs do.
8.  `build` -\> `immutable` from `$app/manifest`; `files` -\> `assets` from `$app/manifest`; `version` -\> `$app/env`. (`base` handling -\> `resolve()` from `$app/paths`.)
9.  `goto('/foo', { shallow: true, state: { open: true } })` and `goto('', { shallow: true, replace: true, state: { open: false } })` (use the current URL as needed). `persistState: true` restores `page.state` after reload. Shallow navigations now trigger `beforeNavigate`, `onNavigate` and `afterNavigate` (filter with `shallow`).
10. `refreshAll` does not reset `page.state`; `invalidateAll` does and is deprecated. Neither aborts an in-flight navigation any more.
11. A branch for `result.type === 'error'` (`{ type: 'error', status, error }`).
12. 3.x navigates to the target page after submission instead of staying put (matching native behaviour); `navigate: false` on `update` opts out.
13. Enhanced responses now use the status passed to `fail(...)`; update the assertion to the fail status (for example 400 or 422).
14. `handleError` now receives all errors, including expected `error()` ones and 404s, with a `kind`. Triage by kind: log unknown at error level, others lower, and alert only on unknown/5xx; it can also return a `status`.
15. `error(404, 'x', { code: 'E1' })`: the second argument is always a string; extra properties go third.
16. `handleError` with `kind: 'validation'` and an `issues` array; the generic error is safe to return.
17. You must pass `{ external: true }` (any external URL except `javascript:`) or an array of allowed origins; `javascript:` stays blocked unless it is explicitly listed in the array form.
18. Any two: cookie names must be ASCII-only; types renamed to `SerializeOptions`/`ParseOptions`; omitted `path` defaults to `'/'`.
19. Cross-origin mutating requests without a `Content-Type` header are rejected as CSRF. Fix by sending a content type or adding the sender’s origin to `csrf.trustedOrigins`.
20. `csrf.trustedOrigins` allows listed external origins to submit forms; `paths.origin` declares the app’s public origin (used for CSRF checks on forms and remote calls, and prerender URLs). `paths.origin` replaces `prerender.origin` and adapter-node’s `ORIGIN`; `trustedOrigins` replaces `checkOrigin: false`.
21. Hook types from `@sveltejs/kit/hooks`; `defineParams` from `@sveltejs/kit/params`; `defineEnvVars` (and `EnvVarConfig`) from `@sveltejs/kit/env`.
22. All matchers are named exports in one `defineParams({...})` call in `src/params.ts`, as functions returning a parsed value or `undefined`, or as Standard Schemas. Transforms should be symmetric so `resolve()` can turn the parsed value back into a path segment.
23. Any directory named `server` (outside `src/routes` and `static`) is now server-only, so the component import fails the import-chain check at dev/build time.
24. Any four: Rolldown bundling; `ORIGIN` removed in favour of `paths.origin`; static assets served from a build-time list (late files not served); content-hash ETags and no `Last-Modified`; static assets only for GET/HEAD (405 otherwise).
25. `env` and `waitUntil` from `cloudflare:workers`; `cf` on `request.cf`; `caches` as a global.
26. Any five: `$env/*`, `$app/environment`, `invalidateAll`, `pushState`/`replaceState`, `json()`/`text()`, `files.*`, `alias`, `typescript.config`, `export const snapshot`, `adapter-cloudflare-workers`.
27. Session must exist before membership can be resolved, and the guard should see the final state. 404 avoids revealing that the tenant exists to non-members.
28. For a `query`, `handle` sees the internal remote endpoint URL, so it cannot resolve `params.tenant` and `locals.tenant` stays empty; in forms and commands `event.params`/`url` describe the calling page as reported by the client (and accessing them throws in queries). So the tenant slug is an explicit argument, and `requireTenantRole` re-resolves the membership from the session user, which makes the client-supplied value safe. Destructive commands also pass the tenant ID the page was rendered with and reject a mismatch with 409, so a renamed or reused slug or a stale tab cannot redirect the write to another tenant.
29. Sample: (1) `tenant` handle membership check: test that a non-member gets 404 on tenant routes; (2) tenant-scoped repositories with no unscoped API: test every method as tenant A against tenant B data returns nothing; (3) Postgres RLS: test that a query without the right session setting returns no rows.
30. Login page: prerendered, CDN-cacheable (no user data). Tenant dashboard: `private, no-store` (personalised and tenant-specific). `/_app/immutable/*`: `public,max-age=31536000,immutable` (content-hashed). `query.live` stream: `no-store` and never cached by a service worker. Billing webhook: no caching, plain status responses, signature verified.
