# Chapter 16: Performance, Caching, and Preloading

SvelteKit ships with a performance posture that is better than most hand-assembled stacks: code is split per route, assets are content-hashed, the modules a page needs are preloaded, and `load` data is inlined into the HTML so the browser does not repeat it. What the framework cannot do is design your data access, choose your cache lifetimes, or decide which fonts are critical. Those decisions are yours, and they dominate real-world results.

This chapter is organised around that boundary. We start with what you get for free and how each default works internally, because you cannot improve what you misunderstand. Then we cover measurement, link preloading, waterfall elimination, HTTP caching at every layer (browser, CDN, framework, service worker), fonts, images and icons, bundle strategy, service workers, and finally the accessibility and SEO concerns that the docs group with performance. Where the official documentation is thin, I say so and label the guidance as author practice.

All examples use the SvelteKit 3 conventions from the rest of the book: configuration in `vite.config.ts` via `sveltekit({...})`, `#lib` imports, and `$app/env` rather than `$app/environment`.

## What you get for free, and how it works

The performance page in the docs lists nine defaults. Each has a mechanism, and each has a way to defeat it.

| Default | Mechanism | How you break it |
|------------------------|------------------------|------------------------|
| Code-splitting | Vite/Rolldown emit one chunk graph; each route’s leaf and layout nodes are dynamic imports | Importing a heavy library statically from the root layout |
| Asset preloading | `<link rel="modulepreload">` (and stylesheet links) emitted in `<head>` for the entry and the route’s dependencies | SPA mode, which has no server-rendered head to carry them |
| File hashing | Output under `_app/immutable/` has content hashes in filenames | Serving them with a short `Cache-Control` |
| Request coalescing | All server `load` functions for a navigation are resolved in one `__data.json` request | Doing client-side `fetch` calls from universal `load` that the server could have done |
| Parallel loading | Universal `load` functions for layouts and page start together | `await parent()` |
| Data inlining | Responses to `fetch` during SSR are serialised into `<script data-sveltekit-fetched>` and replayed on hydration | Raw `globalThis.fetch`, or a `fetch` with `Vary: *` |
| Conservative invalidation | `load` reruns only when tracked inputs change | Reading `url` wholesale instead of `url.searchParams.get('x')` |
| Prerendering | Per-route `prerender` produces static HTML at build | Reading `url.searchParams` or using actions on that page |
| Link preloading | `data-sveltekit-preload-*` | Never opting in, or opting in everywhere on side-effectful `load`s |

A few of these deserve a closer look because their details matter for the rest of the chapter.

### Preload tags, and the 3.0 change

In SvelteKit 2 you could choose `output.preloadStrategy` (`modulepreload`, `preload-js`, `preload-mjs`). In 3.0 that option is removed and `modulepreload` is always used. The strategies existed to paper over Safari and Firefox gaps that no longer matter for the browsers you target in 2026.

What 3.0 added is `output.linkHeaderPreload` (default `false`). By default preload hints are `<link>` elements in the HTML `<head>`. When you set it to `true`, dynamically rendered pages send them as an HTTP `Link` response header instead, with `nopush`:

```ts
// vite.config.ts
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [
        sveltekit({
            output: { linkHeaderPreload: true }
        })
    ]
});
```

Why would you want that? A `Link` header is available before the first byte of the body, so a CDN or browser can start fetching earlier, and some CDNs can convert it to HTTP 103 Early Hints. The cost is header size: the docs warn that Nginx and Apache default to header limits that a large route’s dependency list can exceed, in which case the response fails with a 502 or 431 rather than degrading gracefully. The source confirms the scope: the header path is used only when the page is not being prerendered (`state.prerendering` or a `prerender` default of `true` falls back to `<link>` tags, because a static file has no headers to attach them to). Fonts follow the same rule.

> **Senior tip:** Treat `linkHeaderPreload` as an optimisation you measure, not a default you flip. Turn it on in a preview environment behind your real proxy and check for truncated or rejected headers before you ship.

### Inlined fetches and `data-ttl`

When a server `load` or a universal `load` running on the server calls the provided `fetch`, SvelteKit records the response and writes it into the HTML as a JSON script tag. During hydration the client-side `fetch` finds a matching tag (keyed on URL plus a hash of the request headers and body when present) and returns a `Response` built from it with no network request.

There is a second, less known half. If the original response carried `Cache-Control` with `max-age` (or `s-maxage`, which wins) and no `Vary: *`, the tag also gets a `data-ttl` attribute equal to that lifetime minus the response’s `Age`. The client keeps the response in an in-memory map and keeps replaying it for later `fetch` calls with the same key until the TTL expires (measured with `performance.now()`, so it is relative to page load). The replay only applies when the request’s `cache` mode is `default`, `force-cache`, `only-if-cached` or unset. This means that a universal `load` that calls `fetch('/api/prices')` against an endpoint returning `Cache-Control: max-age=30` will not re-hit the endpoint on client-side re-runs for 30 seconds. It is a small but real client cache, and it explains why changing an upstream’s `Cache-Control` can change how often your `load` appears to “refresh”.

Only headers allowed by `filterSerializedResponseHeaders` are copied into the payload, and by default that is none; the TTL logic reads the raw headers independently of that filter. If your `load` needs to forward `content-type` for some reason, opt in explicitly in `handle`:

```ts
// src/hooks.server.ts
import type { Handle } from '@sveltejs/kit/hooks';

export const handle: Handle = ({ event, resolve }) =>
    resolve(event, {
        filterSerializedResponseHeaders: (name) => name === 'content-type'
    });
```

### Request coalescing

On a client-side navigation, SvelteKit does not issue one request per server `load`. It issues a single `GET /route/__data.json?x-sveltekit-invalidated=…` whose `x-sveltekit-invalidated` parameter is a string of `0`/`1` flags saying which nodes need to rerun, and the server responds with the results of those nodes only. The practical implication is that adding another `+layout.server.ts` load to a route does not add a round trip, but making a universal `load` call your own API from the browser does. Data requests carry `Cache-Control: private, no-store` (set unconditionally in the source for both JSON and streamed responses), so they are never cached by browsers or shared caches. Cache the *page* or the *upstream*, not `__data.json`.

## Measure first

Dev mode is a different program from production: unbundled modules, HMR, no preload tags, extra warnings. The docs are explicit that performance testing must happen against a build:

```bash
vite build && vite preview
```

Preview runs in Node, so adapter-specific behaviour (a Cloudflare `platform` object, Vercel ISR, precompression by adapter-node’s static server) is not reproduced. For those, test on a staging deployment of the real adapter.

For tooling, the docs point at Lighthouse, PageSpeed Insights and WebPageTest. My practice is to use lab tools (Lighthouse, the Performance panel) to find *why* something is slow and field data (Core Web Vitals from real users, see Chapter 17) to decide *whether it matters*. A route that scores 100 in Lighthouse on your laptop may have a 4-second LCP on a mid-range phone in another continent.

### Server-Timing from `handle`

The docs mention `Server-Timing` as a lightweight instrumentation option. It surfaces server phases in the browser’s Network panel with zero infrastructure. A `handle` that records the total time:

```ts
// src/hooks.server.ts
import type { Handle } from '@sveltejs/kit/hooks';

export const handle: Handle = async ({ event, resolve }) => {
    const start = performance.now();
    const response = await resolve(event);

    // A Response returned by resolve() has mutable headers for page renders,
    // but not for every Response (e.g. fetched or redirected ones). Clone defensively.
    const headers = new Headers(response.headers);
    headers.append('server-timing', `app;dur=${(performance.now() - start).toFixed(1)}`);

    return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers
    });
};
```

Note what this measures: until `resolve` returns a `Response`. For a streamed page that is time to first byte, not time to complete the stream. For per-`load` timings, use tracing (Chapter 17) rather than hand-rolled headers.

## Link preloading

By default, a click on an internal link triggers: route matching, dynamic import of the route’s nodes, the `load` calls, then render. Link preloading moves the first steps earlier, using a user-intent signal.

### The two attributes

`data-sveltekit-preload-data` controls code *and* data. `"hover"` starts when the pointer rests over the link (on touch devices, on `touchstart`), `"tap"` starts on `mousedown`/`touchstart`. `data-sveltekit-preload-code` controls code only, with four levels in decreasing eagerness: `eager`, `viewport`, `hover`, `tap`. The generated `src/app.html` puts `data-sveltekit-preload-data="hover"` on `<body>`.

Because data preloading implies code preloading, `preload-code` only has an effect when it is *more eager* than the `preload-data` value in force. A practical configuration for a content-heavy site:

```html
<!-- src/app.html -->
<body data-sveltekit-preload-data="hover" data-sveltekit-preload-code="viewport">
    <div style="display: contents">%sveltekit.body%</div>
</body>
```

Links that enter the viewport have their *code* fetched; a hover additionally runs `load`. Two caveats from the docs and source:

- `viewport` and `eager` only apply to links present in the DOM immediately after navigation. Links inserted later (inside an `{#if}`, after an `await`) are only preloaded on `hover` or `tap`. This is deliberate, to avoid observing the whole DOM for mutations.
- Everything is disabled when `navigator.connection.saveData` is `true`. The check happens once, at client startup: if the user has Data Saver on, the preload listeners are never installed (`setup_preload` is skipped). There is no override.

### Overriding per subtree

The attributes cascade through the DOM, and `"false"` disables an inherited value. Use that for links whose `load` is expensive or has side effects:

```html
<!-- src/routes/reports/+page.svelte -->
<script lang="ts">
    let { data } = $props();
</script>

<ul data-sveltekit-preload-data="false">
    {#each data.reports as report (report.id)}
        <li><a href="/reports/{report.id}">{report.title}</a></li>
    {/each}
</ul>
```

Conditional application uses a plain expression: `data-sveltekit-preload-data={slow ? false : 'hover'}`. In SvelteKit 3 the value `"off"` is gone; it must be `false`.

### What preloading does not do

A preload runs `load` functions, so any `load` with a side effect (incrementing a view counter, creating a draft, “mark as read”) will run on hover. The fix is to make `load` safe and idempotent, which it should be anyway, and move side effects to actions or remote `command`s. Preloading also cannot guess authorisation changes: it uses current cookies, so a preload that returns a redirect to `/login` is a valid outcome.

SvelteKit retains *one* preloaded navigation at a time. In the client router, a new `preloadData` for a different navigation intent discards the pending one (`discard_load_cache`) before starting its own. Rapidly sweeping the mouse across a navigation menu therefore wastes work but never accumulates it. If the user clicks the link whose preload is in flight or complete, that result is used and no second `load` runs.

### Programmatic preloading

`preloadData` and `preloadCode` from `$app/navigation` let you drive this from your own signals (a focus event, an `IntersectionObserver`, a timer after idle). Their result shapes are worth memorising:

```ts
import { preloadData, preloadCode, goto } from '$app/navigation';

// Code only: resolves when the route's modules are imported.
await preloadCode('/reports/42');

// Code + load. Discriminated result:
const result = await preloadData('/reports/42');
switch (result.type) {
    case 'loaded':
        // result.status, result.data  (data is the merged page data)
        break;
    case 'redirect':
        // result.location: the target a navigation would follow
        break;
    case 'error':
        // result.status, result.error
        break;
}
```

A common pattern is to preload on `pointerenter` for elements that are not `<a>` elements, such as a table row that navigates through `goto`:

```html
<!-- src/routes/orders/+page.svelte -->
<script lang="ts">
    import { goto, preloadData } from '$app/navigation';
    import { resolve } from '$app/paths';

    let { data } = $props();
</script>

<table>
    <tbody>
        {#each data.orders as order (order.id)}
            {@const href = resolve('/orders/[id]', { id: order.id })}
            <tr
                onpointerenter={() => void preloadData(href)}
                onclick={() => goto(href)}
            >
                <td>{order.id}</td>
                <td>{order.customer}</td>
            </tr>
        {/each}
    </tbody>
</table>
```

(For accessibility, the row needs a real link inside it as well; this snippet only illustrates the preload. See the accessibility section at the end of the chapter.)

`preloadData` rejects for external or non-route URLs, so wrap it if the `href` is user-supplied.

### `forkPreloads`

Chapter 5 covers `experimental.forkPreloads`. In one sentence: with the flag on, a completed preload also uses Svelte’s `fork` API to render the destination page off-screen, so that async `$derived`/`await` expressions in that page have already resolved when the navigation commits. It is useful if your pages rely on async Svelte; its cost is rendering work for navigations that never happen. Enable it by measuring.

## Waterfalls

The docs call waterfalls “one of the biggest performance killers”. There are three distinct kinds in a SvelteKit app, and each has a different cure.

### Asset waterfalls

HTML references JS, JS imports more JS, CSS references fonts and images. The framework solves the JS and CSS chains with preload tags. It does not solve:

- **Fonts**, which are referenced from CSS and so discovered only after the stylesheet is parsed. We handle these below.
- **Images** that are discovered late, such as an LCP hero image set from JS or a CSS `background-image` in an unloaded chunk.
- **SPA mode**, in which the server emits an empty shell: no per-route preload hints, so the browser needs the shell, then the entry module, then the route modules, then the data. If you must run as an SPA, prefer a prerendered shell and `data-sveltekit-preload-code="eager"` for key links.

### Load waterfalls

Within one navigation SvelteKit runs `load` functions concurrently, except where you create a dependency with `await parent()`. Compare:

```ts
// src/routes/dashboard/+page.server.ts
import type { PageServerLoad } from './$types';
import { db } from '#lib/server/db.js';

export const load: PageServerLoad = async ({ locals }) => {
    // Sequential: each query waits for the previous
    const user = await db.user.get(locals.userId);
    const projects = await db.project.listForUser(user.id);
    const alerts = await db.alert.listForUser(user.id);

    return { user, projects, alerts };
};
```

`locals.userId` is already known, so nothing here depends on `user`. The parallel form:

```ts
// src/routes/dashboard/+page.server.ts
import type { PageServerLoad } from './$types';
import { db } from '#lib/server/db.js';

export const load: PageServerLoad = async ({ locals }) => {
    const [user, projects, alerts] = await Promise.all([
        db.user.get(locals.userId),
        db.project.listForUser(locals.userId),
        db.alert.listForUser(locals.userId)
    ]);

    return { user, projects, alerts };
};
```

Three round trips become one wall-clock round trip. When the dependency is real (you need a project’s ID to load its tasks), the docs recommend a join or a single query where the database allows, because the sequential cost is paid per query, not per request.

### `parent()` and layout design

`await parent()` serialises the child behind its layout. Often it is used merely to read something like the current user. Two alternatives avoid it:

1.  Put the value in `event.locals` in `handle` (Chapter 9), which is available to every load at no waterfall cost.
2.  Read it through `getRequestEvent()` in a shared helper.

```ts
// src/routes/projects/[id]/+page.server.ts
import type { PageServerLoad } from './$types';
import { error } from '@sveltejs/kit';
import { db } from '#lib/server/db.js';

export const load: PageServerLoad = async ({ params, locals }) => {
    // No parent() needed: the user is on locals, set once in handle
    const project = await db.project.getForUser(params.id, locals.user.id);
    if (!project) error(404, 'Project not found');
    return { project };
};
```

If you do need `parent()`, call it *after* kicking off independent work:

```ts
export const load: PageLoad = async ({ parent, fetch, params }) => {
    const taskPromise = fetch(`/api/projects/${params.id}/tasks`).then((r) => r.json());
    const { project } = await parent();
    return { tasks: await taskPromise, title: project.name };
};
```

This also interacts with auth: as Chapter 14 explains, a guard placed only in a layout `load` requires every child to call `await parent()`, which is a structural waterfall. Guard in `handle` or in each page’s server `load` instead, which is both safer and faster.

### Server versus universal loads for backend calls

A universal `load` running in the browser calls your API across the public internet, then possibly calls a second endpoint with the result. The docs recommend using a server `load` for these dependent calls so the chain runs next to your backend. The corollary: if your page’s data comes from a service you control, a server `load` (or remote function) is almost always the right default, and universal `load` is for data that is genuinely public and benefits from browser-side re-fetching.

### Remote function batching

`query.batch` (Chapter 7) is the remote-function answer to the N+1 waterfall: 40 components in a list, each calling `getAuthor(id)` in the same macrotask, become one HTTP request and one database query. If you see a component-per-row data pattern, this is the fix rather than hoisting data into the parent.

### Non-essential data

For slow data that does not block first paint, return an un-awaited promise from a server `load` and render it in an `{#await}` or `await` block; it streams in after the shell (Chapter 5). The design rule I use: stream data that is below the fold or not needed for the LCP element; block on data that *is* the LCP element. Remember that streaming loses status and header control once started and may be buffered by platforms like AWS Lambda, so verify on your target.

## Caching

HTTP caching is the largest lever on both latency and cost, and SvelteKit deliberately gives you primitives rather than a policy. Think in layers, from the origin outward:

| Layer | What it caches | Who controls it |
|------------------------|------------------------|------------------------|
| Upstream (DB, CMS, API) | Query results | You, plus the upstream’s own headers |
| Server process | Computed values in memory or Redis | You (beware cross-request leakage, Chapter 12) |
| CDN / shared cache | Full responses | `Cache-Control` (`s-maxage`), `Vary`, platform rules |
| Browser HTTP cache | Full responses | `Cache-Control`, `ETag` |
| SvelteKit client | Inlined-fetch replay (`data-ttl`), load results for unchanged nodes | Upstream `max-age`, invalidation |
| Service worker | Whatever you code | You |
| Prerendered output | Whole pages as files | `prerender` option |

### Immutable assets

Everything under `/_app/immutable/` is content-hashed. Adapter-node’s static handler marks those with `Cache-Control: public,max-age=31536000,immutable` (you can see this in its asset table construction), and the other official adapters do the equivalent for their platforms. If you put a custom reverse proxy in front, make sure it does not override this. SvelteKit also protects the other side of the contract: a request under the app directory that matches nothing gets a 404 with `Cache-Control: public, max-age=0, must-revalidate`, so a missing chunk during a deploy is not cached by an overeager platform. Files from `static/` have no hash, so they get the platform’s default revalidation behaviour; version their names yourself if you need long-lived caching (for example `logo.v3.svg`) or import them through Vite so they are hashed.

### HTML and `setHeaders`

For pages, the tool is `setHeaders` in `load` (server or universal, effective only during SSR). The rules, repeated from Chapter 4 because they bite here: each header may be set once across all `load` functions for the request, and `set-cookie` is not permitted.

```ts
// src/routes/blog/[slug]/+page.server.ts
import type { PageServerLoad } from './$types';
import { error } from '@sveltejs/kit';
import { getPost } from '#lib/server/cms.js';

export const load: PageServerLoad = async ({ params, setHeaders }) => {
    const post = await getPost(params.slug);
    if (!post) error(404, 'Not found');

    setHeaders({
        // Browser: always revalidate. CDN: fresh for 5 min, serve stale up to 1 day while refreshing.
        'cache-control': 'public, max-age=0, s-maxage=300, stale-while-revalidate=86400'
    });

    return { post };
};
```

SvelteKit validates `Cache-Control` and `Content-Type` values in development: malformed directives (an empty directive from a stray comma, or an unrecognised name) produce warnings, because browsers and CDNs silently ignore headers they cannot parse. That check is cheap insurance; do not ignore the warnings.

**Danger: caching personalised HTML.** A public `s-maxage` on a page whose HTML contains user-specific data is a data leak. The CDN will happily serve user A’s page to user B. Rules I follow (author practice):

1.  Never set `public` caching in a layout `load` that runs for authenticated and anonymous pages alike.
2.  If cookies influence output, either send `Cache-Control: private` or make the CDN key on the cookie (platform-specific and brittle).
3.  Prefer splitting: a fully cacheable shell, with user-specific data fetched client-side or via streaming from a non-cached endpoint.

If a header such as `cache-control` must be set for *every* route of a class, do it in `handle` after `resolve` rather than in many `load`s, so there is exactly one place to audit:

```ts
// src/hooks.server.ts
import type { Handle } from '@sveltejs/kit/hooks';

export const handle: Handle = async ({ event, resolve }) => {
    const response = await resolve(event);

    // Only touch GET HTML that has not declared its own policy
    const isHtml = response.headers.get('content-type')?.startsWith('text/html');
    if (event.request.method === 'GET' && isHtml && !response.headers.has('cache-control')) {
        response.headers.set('cache-control', 'private, no-cache');
    }

    return response;
};
```

(`resolve` returns a `Response` whose headers are mutable in the normal rendering path. If you return responses you construct elsewhere, clone as shown earlier.)

### ETags and 304s

For non-streamed page renders SvelteKit computes an `ETag` from a hash of the final HTML (`"<hash>"`), and `respond` answers a matching `If-None-Match` with a `304 Not Modified`, preserving `Cache-Control`, `Vary`, `Date`, `Expires`, `Content-Location` and any cookies set on the response. Two consequences:

- It saves bandwidth, not CPU. The page is still rendered in full to compute the hash. A 304 does not make your origin cheaper; only a cache in front of it does.
- Streamed responses (where `load` returned promises) get no ETag, since the body is not complete when headers are sent.

For `+server` endpoints you own the ETag. A minimal conditional GET for expensive JSON:

```ts
// src/routes/api/catalog/+server.ts
import type { RequestHandler } from './$types';
import { getCatalog, catalogVersion } from '#lib/server/catalog.js';

export const GET: RequestHandler = async ({ request }) => {
    const etag = `"catalog-${await catalogVersion()}"`;

    if (request.headers.get('if-none-match') === etag) {
        return new Response(null, { status: 304, headers: { etag } });
    }

    return Response.json(await getCatalog(), {
        headers: {
            etag,
            'cache-control': 'public, max-age=0, s-maxage=60, must-revalidate'
        }
    });
};
```

Note the use of `Response.json`; the `json()` helper from `@sveltejs/kit` is deprecated in 3.x.

### Prerendering and ISR

The cheapest request is the one that never reaches your server. A page without per-user data is a candidate for `prerender = true` (Chapter 11), served as a static file by the CDN. For content that changes but is not per-user, Vercel’s ISR (adapter-vercel’s `isr` option, Chapter 18) approximates “prerender on demand with expiration”. Note two documented limits: ISR is ignored for prerendered routes, and ISR keys on the path unless you declare `allowQuery` parameters. On other platforms, the same effect is available with `s-maxage` plus `stale-while-revalidate`, as in the `blog` example above.

### The `fetch` replay as a cache

As described earlier, upstream `max-age` flows into `data-ttl`. You can exploit that for universal `load`s that call your own cacheable endpoints, but it is a happy accident of the inlining system rather than a managed cache. Do not use it for correctness. For managed client-side caching of server data, use remote `query` functions, whose cache semantics (keyed by arguments, shared across components, explicit `refresh`) are designed for it (Chapter 7).

## Fonts, images, and icons

### Fonts

SvelteKit preloads JS and CSS but not fonts by default, because it cannot know which weights and subsets a given page actually uses; blindly preloading all of them wastes bandwidth. You opt in with a `preload` filter in `resolve`. As of 3.x, the callback for fonts also receives `filename`, the source file path relative to the project root, so you can match on a stable name rather than a hashed output path:

```ts
// src/hooks.server.ts
import type { Handle } from '@sveltejs/kit/hooks';

export const handle: Handle = ({ event, resolve }) =>
    resolve(event, {
        preload: (input) => {
            if (input.type === 'font') {
                // Preload only the one critical face
                return input.filename.endsWith('inter-latin-400-normal.woff2');
            }
            // default for js, css and assets: preload
            return true;
        }
    });
```

The argument is a discriminated union that has `filename` only on the `font` branch, so narrowing on `input.type` is what makes the call type-check.

Design notes:

- Fonts imported through CSS `@font-face` with Vite-resolved URLs are the ones `preload` can see. Fonts loaded from a third-party host are invisible to this mechanism; preconnect or self-host them.
- The preload hint carries `crossorigin` and a `type="font/<ext>"`, as the source builds it; you cannot get the CORS mode wrong.
- Preloading two faces is rarely a win over one. Subset fonts (Latin only) and prefer `font-display: swap` or `optional` and a metric-compatible fallback to limit layout shift.
- With `linkHeaderPreload: true`, font hints move into the `Link` header on dynamic pages.

### Images

The official page describes three tools and recommends mixing them:

1.  **Vite asset handling**: imported images get hashed names and are inlined below `assetsInlineLimit`. Use this for logos and meta images.
2.  **`@sveltejs/enhanced-img`** (1.0.0 at the time of writing): a build-time plugin that turns `<enhanced:img>` into a `<picture>` with AVIF/WebP and multiple sizes, sets intrinsic `width`/`height`, and strips EXIF. In `vite.config.ts` it goes before `sveltekit()`:

```ts
// vite.config.ts
import { enhancedImages } from '@sveltejs/enhanced-img';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [enhancedImages(), sveltekit({})]
});
```

```html
<!-- src/routes/+page.svelte -->
<enhanced:img
    src="./hero.jpg"
    alt="Team at the offsite"
    sizes="min(1280px, 100vw)"
    fetchpriority="high"
/>
```

3.  **A CDN image service** for images not available at build time (CMS, user uploads). You trade build-time determinism for flexibility and pay the cost of lazily generated variants on low-traffic sites.

The rules that move the needle are the ones from the docs’ best-practices list: supply originals at 2x display size; give an LCP image `fetchpriority="high"` and never `loading="lazy"`; always reserve space (`width`/`height` or an aspect-ratio container) to protect CLS; and avoid `rem`/`em` in `sizes` because the browser’s preloader evaluates them against the default font size, not your CSS. Because `enhanced-img` can only process files on disk at build time, a database-driven image path must take the CDN route. The first build is slow (image transforms are cached in `node_modules/.cache/imagetools`), so persist that directory in CI.

### Icons

The icon advice is short and sharp: prefer CSS-based icons (for example via Iconify’s CSS or its Tailwind/UnoCSS plugins) over libraries with one `.svelte` file per icon. Thousands of tiny component files slow Vite’s dependency optimisation in development, and the problem becomes pathological when icons are imported both from an umbrella entry and from subpaths, as described in the vite-plugin-svelte FAQ. This is a *dev-time* performance concern; the production bundle tree-shakes either way.

### Video and third-party scripts

Compress and transcode video, use `preload="none"` for below-the-fold video (accepting slower start on play), and strip audio from muted clips. Minimise third-party JavaScript: prefer platform analytics that work server-side, and move unavoidable scripts off the main thread with Partytown’s SvelteKit integration. Any third-party script also interacts with your CSP (Chapter 15).

## Bundle shape

### Split, single, inline

`output.bundleStrategy` controls the chunk graph:

- `'split'` (default): many chunks, loaded lazily per route. Best caching and smallest initial payload when users visit a subset of routes. Needs HTTP/2 or newer, as the docs note, because it creates numerous small files that must load in parallel.
- `'single'`: one JS file and one CSS file for the whole app. Useful when the app is embedded in an environment without good parallelism (a Capacitor/Tauri shell loading from local disk, where it also eliminates dynamic-import latency) or when you want one cache entry.
- `'inline'`: everything into the HTML; the result opens from `file://`. It requires `build.assetsInlineLimit` raised (e.g. `Infinity`) and assets imported through Vite.

With `'split'` you can still adjust Rolldown’s `output.codeSplitting` through `build.rolldownOptions` in the Vite config. Do this only with a bundle analyser open; the default grouping is usually better than hand-tuned groups.

### Inline styles

`inlineStyleThreshold` (default `0`) merges and inlines all CSS files smaller than the given length (UTF-16 code units) into a `<style>` block in the head. That removes a render-blocking request and can improve First Contentful Paint, at the cost of larger HTML that the browser cannot cache separately from the document. It suits low-repeat-visit marketing pages with little CSS; it is a poor fit for an app where users load dozens of pages per session and could have cached the stylesheet. Note that in dev, styles are always inlined and removed when CSR takes over, which is why dev looks different from prod.

### Code size hygiene

- Inspect the bundle (the docs suggest `rollup-plugin-visualizer`; the plugin works with Rolldown-based Vite but check its current compatibility with your Vite 8 version before wiring it into CI). You can also build with `build: { minify: false }` temporarily to read the output.
- Use dynamic `import()` for code needed only conditionally (a charting library behind a tab). In Svelte 5 you can also write `{#await import('./Chart.svelte')}` or lazy-load via a `$state` holding the component.
- Keep Svelte current; the docs note each major generation is smaller and faster.

### Hosting

Co-locate compute with your data store. A server `load` that makes three sequential database calls from an edge location a continent away from the database is far worse than the same code in the database’s region. Use edge only when data is globally replicated or absent. Confirm your host serves HTTP/2 or HTTP/3. Note that SvelteKit 3’s Vercel adapter has dropped the Edge runtime (Chapter 18), so “edge” there means the CDN layer, not your server code.

## Service workers

SvelteKit’s service worker support is minimal by design: if `src/service-worker/index.ts` exists, it is bundled and registered automatically (as a module worker, `type: 'module'`). The legacy location `src/service-worker.ts` still works, but the directory form lets the worker have its own `tsconfig.json`.

### What the worker can import (3.x)

| Import                                         | From                  |
|------------------------------------------------|-----------------------|
| `self` (typed `ServiceWorkerGlobalScope`)      | `$app/service-worker` |
| `version`                                      | `$app/env`            |
| `immutable`, `assets`, `prerendered`, `routes` | `$app/manifest`       |
| `resolve`                                      | `$app/paths`          |

`$service-worker`, the module you may remember from SvelteKit 2 (`build`, `files`, `prerendered`, `version`, `base`), is removed. The mapping is: `build` is `immutable`, `files` is `assets`, `version` moves to `$app/env`, and `base` handling is replaced by `resolve()`. In `$app/manifest`, `immutable` and `prerendered` are empty arrays in development, so a worker that precaches them has nothing to do until you build. `assets` and `routes` are populated in dev. Paths in the manifest are relative to the configured base path, so resolve them before comparing with `url.pathname`.

The type setup: the root `tsconfig.json` extends `$app/tsconfig` and *excludes* `src/service-worker`; the worker directory has its own `tsconfig.json` that extends `$app/tsconfig/service-worker`.

### A production-shaped worker

The docs’ example uses cache-first for build assets and network-first with cache fallback for everything else. Here is a version that adds the safeguards I consider mandatory:

```ts
// src/service-worker/index.ts
import { self } from '$app/service-worker';
import { version } from '$app/env';
import { immutable, assets } from '$app/manifest';
import { resolve } from '$app/paths';

const CACHE = `cache-${version}`;

const PRECACHE = [
    ...immutable.map((a) => resolve(a.path)),
    ...assets.map((a) => resolve(a.path))
];
const PRECACHE_SET = new Set<string>(PRECACHE);

self.addEventListener('install', (event) => {
    event.waitUntil(
        (async () => {
            const cache = await caches.open(CACHE);
            await cache.addAll(PRECACHE);
        })()
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        (async () => {
            for (const key of await caches.keys()) {
                if (key !== CACHE) await caches.delete(key);
            }
        })()
    );
});

self.addEventListener('fetch', (event) => {
    const { request } = event;
    if (request.method !== 'GET') return;

    const url = new URL(request.url);
    // Only handle same-origin requests
    if (url.origin !== self.location.origin) return;

    // Never intercept data/remote calls: they carry `private, no-store`
    // and (for live queries) are long-lived streams.
    if (url.pathname.endsWith('/__data.json') || url.pathname.includes('/_app/remote/')) return;

    event.respondWith(respond(request, url));
});

async function respond(request: Request, url: URL): Promise<Response> {
    const cache = await caches.open(CACHE);

    if (PRECACHE_SET.has(url.pathname)) {
        const hit = await cache.match(url.pathname);
        if (hit) return hit;
    }

    try {
        const response = await fetch(request);
        const noStore = response.headers.get('cache-control')?.includes('no-store');
        if (response.status === 200 && !noStore) {
            void cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        const fallback = await cache.match(request);
        if (fallback) return fallback;
        throw error;
    }
}
```

Points of care that are easy to get wrong:

- **Remote functions and live queries.** The SvelteKit docs say a `query.live` response must not be cached by a service worker because it sends `Cache-Control: no-store`; the `no-store` check above handles that, but intercepting a long-lived stream with `respondWith(fetch())` and cloning it for the cache is still wasteful and can stall. I skip those requests outright. Remote calls from the client go to `${base}/${appDir}/remote/<id>` (the client source builds the URL that way), so the path check follows `appDir` if you have changed it; the `no-store` rule remains the more robust signal.
- **Cache-first for the HTML shell breaks deploys.** The sample uses network-first for everything not in the precache list, which is why users get new HTML after a deploy. A cache-first strategy for documents requires an explicit update UX.
- **Stale data is sometimes worse than no data** (the docs’ own warning). Do not cache authenticated API responses without keying on user.
- **Quota eviction.** Browsers evict caches when storage is tight. Do not rely on the cache holding large media.
- **Registration.** To control registration yourself (for example only after consent, or only on certain routes) set `serviceWorker: { register: false }` in `sveltekit({...})` and register in your own code with `{ type: 'module' }`.

### Updating

The browser checks for a new worker on full-page navigations within scope and on functional events. A SvelteKit app mostly navigates client-side, so a user can stay on an old worker for a long time. SvelteKit itself calls `registration.update()` only during error recovery: when a route module fails to load or a navigation hits an error status *and* the version check (`updated`, polled every `version.pollInterval`, default one hour; `0` disables polling) has found a new deployment. To check eagerly, call `update()` from `afterNavigate` in the root layout, as the docs show. A new worker installs in the background and takes over when the number of tabs controlled by the old one drops to zero; you can offer a reload prompt using `updated.current` from `$app/state`, which in SvelteKit 3 also refreshes on focus, visibility change, server-data navigations and remote calls, not only by polling.

If you want Workbox-style recipes (stale-while-revalidate, background sync, runtime caching rules), the docs point to the Vite PWA plugin as the alternative. Use the built-in support for precaching and simple fallbacks; reach for a PWA plugin once you need a manifest, installability and runtime strategies.

## Accessibility and SEO as performance-adjacent concerns

These do not make pages faster, but a client-routed app can silently regress them while looking fast, so they belong in the same review.

### Route announcements and titles

A full page load makes a screen reader announce the new title. Client-side navigation does not, so SvelteKit injects a live region and announces the new page based on `<title>`. Therefore *every* page needs a unique, descriptive `<title>`:

```html
<!-- src/routes/orders/[id]/+page.svelte -->
<script lang="ts">
    let { data } = $props();
</script>

<svelte:head>
    <title>Order {data.order.id} · Acme</title>
    <meta name="description" content="Status and line items for order {data.order.id}." />
</svelte:head>
```

A common structure from the docs: return SEO data from `load` and render it once in the root layout’s `<svelte:head>` using `page.data` from `$app/state`.

### Focus

After each navigation and enhanced form submission SvelteKit focuses `<body>` (unless an element with `autofocus` is present), simulating a fresh page load. Preserving scroll and focus is opt-in via `reset: false` on `goto` or `data-sveltekit-reset="false"` on a link or GET form. The docs warn to use it only when the focused element survives the navigation, and generally not on links. A search-as-you-type GET form is the legitimate use case. To customise, use `afterNavigate` and focus your own landmark.

The earlier table-row example violates accessibility: a clickable `<tr>` is not keyboard-reachable. The right fix is a real `<a>` in a cell with the preload attribute inherited from `<body>`, and the row click as a convenience on top of it.

### Language

`app.html` defaults to English. Set `<html lang="…">`; for multi-language sites, put a placeholder in `app.html` and substitute it in `handle` through `transformPageChunk`, as in the docs.

### SEO checklist

- SSR is on by default and is more reliably indexed; keep it.
- URLs are normalised by `trailingSlash` so duplicates do not occur. Keep it consistent with your sitemap.
- Unique `<title>` and `<meta name="description">` per page.
- Sitemaps: a `+server` endpoint at `src/routes/sitemap.xml/+server.ts`. The docs example builds the XML in a template literal; note that a leading newline before `<?xml` makes the document invalid for some parsers, and the docs’ sample calls `.trim()` for that reason. Generate it from your content source, and prerender it if the content is static:

```ts
// src/routes/sitemap.xml/+server.ts
import type { RequestHandler } from './$types';
import { listPublishedSlugs } from '#lib/server/cms.js';

export const prerender = false; // the CMS changes between deploys; use true if it does not

export const GET: RequestHandler = async ({ url }) => {
    const slugs = await listPublishedSlugs();
    const urls = slugs
        .map((slug) => `<url><loc>${url.origin}/blog/${slug}</loc></url>`)
        .join('');

    return new Response(
        `<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls}</urlset>`,
        {
            headers: {
                'content-type': 'application/xml',
                'cache-control': 'public, max-age=0, s-maxage=3600'
            }
        }
    );
};
```

If you set `paths.origin` (3.0), prefer building absolute URLs from it so the sitemap does not depend on an unreliable `Host` header behind a proxy; `url.origin` is correct only when your adapter derives the origin properly (see the adapter-node proxy headers in Chapter 18).

- Core Web Vitals influence ranking; the techniques in this chapter are the SEO performance work.

## A performance review checklist

Use this in code review for any new route (author practice):

1.  Is the data on the critical path fetched in parallel, and without `parent()` unless needed?
2.  Could this be prerendered or cached at the CDN? What is its `Cache-Control`, and is it safe for personalised output?
3.  Does any link with an expensive or side-effectful `load` opt out of preloading?
4.  Is the LCP element an image or text, and is it prioritised appropriately (`fetchpriority`, font preload, no lazy loading)?
5.  Is anything heavy statically imported into a layout?
6.  Does the page have a unique `<title>`, and does keyboard focus land somewhere sensible after navigation?
7.  Have you tested on a build, throttled, ideally on a real device?

## Key takeaways

- SvelteKit’s performance defaults are mechanisms with failure modes: preload tags need server rendering, inlined fetches need the provided `fetch`, coalescing needs server loads, and `parent()` and universal loads that call remote APIs create waterfalls.
- 3.0 removed `preloadStrategy` (modulepreload always) and added opt-in `output.linkHeaderPreload`, which uses a `Link` header for dynamic pages and can exceed proxy header limits.
- `data-sveltekit-preload-data` and `-code` cascade, disable with `false`, are skipped under `saveData`, and only one preload is retained at a time; `preloadData` returns `loaded`, `redirect` or `error` results.
- Data requests are `private, no-store`; you cache pages (`setHeaders`, CDN rules), upstreams, or use remote `query` caching. Upstream `max-age` also feeds the client’s inlined-fetch replay through `data-ttl`.
- Non-streamed SSR pages get an HTML-hash `ETag` and 304 support, which saves bandwidth but not render CPU.
- Never publicly cache personalised HTML. Centralise cache policy so it can be audited.
- Fonts are not preloaded by default; filter them in `resolve({ preload })`, using `filename` for font assets.
- Choose images by origin: Vite for static assets, `enhanced-img` for build-time photos, a CDN for dynamic. Avoid per-icon component libraries.
- `bundleStrategy` and `inlineStyleThreshold` trade caching for fewer requests; defaults are right for most apps.
- Service workers in 3.x import from `$app/service-worker`, `$app/env`, `$app/manifest`, and `$app/paths`; skip data and live-query requests, version the cache with `version`, and trigger update checks yourself.
- Titles, focus and `lang` are part of navigation correctness, not polish.

## Review Questions

1.  List four of SvelteKit’s built-in performance defaults and, for each, name one coding pattern that defeats it.

2.  What happened to `output.preloadStrategy` in SvelteKit 3, and what does `output.linkHeaderPreload` do? Name the operational risk of enabling it behind Nginx.

3.  Why does `linkHeaderPreload` not apply to prerendered pages?

4.  A universal `load` calls `fetch('/api/prices')`, and that endpoint responds with `Cache-Control: max-age=30`. The page is server-rendered, then the user triggers a client-side re-run of the `load` 10 seconds after page load. Does the browser perform a network request? Explain which mechanism decides this.

5.  Why do `__data.json` responses never benefit from CDN caching, and what should you cache instead?

6.  **Find the bug:** the following `handle` caches personalised pages at the CDN. What goes wrong?

    ```ts
    export const handle: Handle = async ({ event, resolve }) => {
     const res = await resolve(event);
     res.headers.set('cache-control', 'public, s-maxage=600');
     return res;
    };
    ```

7.  Why should you run performance tests with `vite build && vite preview` rather than `vite dev`? Name two things that `preview` still does not reproduce.

8.  Rewrite this server `load` so that it avoids an unnecessary waterfall, and state why it is safe to do so:

    ```ts
    export const load = async ({ locals }) => {
     const a = await getAccount(locals.userId);
     const b = await getInvoices(locals.userId);
     return { a, b };
    };
    ```

9.  In what way can an `await parent()` in a page `load` be avoided when all you need is the current user?

10. Which of these is true of `data-sveltekit-preload-code="viewport"`?

    a.  It applies to links inserted into the DOM after an `{#if}` toggles on
    b.  It fetches both code and data when the link scrolls into view
    c.  It only affects links present in the DOM right after navigation
    d.  It overrides `data-sveltekit-preload-data="tap"` to always preload data

11. What happens to preloading when the user has `navigator.connection.saveData` enabled, and can you override it per link?

12. Why is preloading on hover dangerous for a `load` that increments a “views” counter, and what are two ways to fix the design?

13. What does `preloadData('/x')` resolve to when `/x` redirects? When it throws an error status? When `/x` is an external URL?

14. What does SvelteKit do when a second `preloadData` call starts while a different preload is still pending?

15. Explain why `await parent()` in a layout-based auth guard is both a performance and a security concern.

16. When would you choose `query.batch` over hoisting data into a parent component?

17. Why does SvelteKit not preload fonts by default? Write a `preload` filter that preloads only `inter-latin-400-normal.woff2` and leaves JS and CSS preloading unchanged.

18. What field is available on the `preload` callback argument only when `type === 'font'`, and why is it needed?

19. What does the source of an `<enhanced:img>` need to be true for the plugin to optimise it? Which of your images must use a CDN instead?

20. Why does the docs’ icon advice discourage libraries that ship one `.svelte` file per icon? Is the effect on development, production, or both?

21. Compare `bundleStrategy: 'split'`, `'single'` and `'inline'`. For which deployment would you choose each?

22. A page has 3 KB of CSS and gets very low repeat traffic. Would you set `inlineStyleThreshold`? What would change for a logged-in app used for hours?

23. **What does this print / return?** A non-streamed page is rendered; the client sends `If-None-Match` equal to the page’s current ETag. What status does the server return, which headers survive, and was the page rendered?

24. List the modules a SvelteKit 3 service worker imports to replace the SvelteKit 2 `$service-worker` exports `build`, `files`, `version`, and `base`.

25. Why does the example service worker skip `__data.json` and live-query requests? What header lets you detect the latter reliably?

26. Why might a user remain on an old service worker for days even though you deploy daily? Give two ways SvelteKit or you can trigger an update check.

27. What causes SvelteKit to announce a new page to screen readers after a client-side navigation, and what do you have to provide for this to work?

28. **Design:** You operate a news site (anonymous, 95% traffic) with a logged-in comment widget. Sketch a caching and rendering design that keeps article HTML cacheable at the CDN while personalising comments. Name the headers you set and where.
