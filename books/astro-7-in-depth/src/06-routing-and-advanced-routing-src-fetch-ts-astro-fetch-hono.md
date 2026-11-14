# Chapter 5: Routing and Advanced Routing (`src/fetch.ts`, `astro/fetch`, Hono)

Astro routing has two layers. The first is the one everybody meets on day one: files under `src/pages` become routes, with dynamic segments, priorities, redirects, rewrites and error pages. The second arrived stable in Astro 7.0: *advanced routing*, where a `src/fetch.ts` file replaces the framework’s fixed request pipeline with one you compose yourself, optionally on top of Hono. This chapter covers both in depth, along with the sharp edges that matter in production: string-only params, decoding differences, the priority table, trailing-slash and `base` interplay, static redirect output, and an authorization pitfall that I reproduced against a real server and that the documentation only hints at.

Verification note: the behaviours reported below come from a test project on Astro 7.4.1 with `@astrojs/node` 11.1.9 (standalone) and Hono 4.13.13, queried with `curl`. Where the docs and my test results differ, I say so.

## File-based routes

Every supported file in `src/pages` creates a route: `.astro`, `.md`, `.mdx`, `.html`, and `.ts`/`.js` endpoints. Static routes map directly:

```text
src/pages/index.astro        -> /
src/pages/about.astro        -> /about
src/pages/about/index.astro  -> /about
src/pages/posts/1.md         -> /posts/1
```

Files or directories whose name starts with `_` are ignored by the router, so components, tests and helpers can sit next to pages (`src/pages/_components/Row.astro` is never a route, and is not written to `dist`). I confirmed that a file under `_private/` was not routed; the request fell through to the catch-all.

### Dynamic parameters

A bracketed segment is a parameter: `[slug]` matches one segment, `[...path]` matches any number of segments including zero (when defined with `undefined`). Several parameters may appear in one filename (`[lang]-[version]/info.astro`) or across segments. In on-demand routes, only one rest parameter is allowed per route (`[locale]/[...slug]` is fine; `[...a]/[...b]` is not).

```html
---
// src/pages/shop/[category]/[...rest].astro
const { category, rest } = Astro.params;   // rest is undefined for /shop/shoes
---
```

### Prerendered dynamic routes: `getStaticPaths()`

A prerendered dynamic route must export `getStaticPaths()` returning the full list of paths to build, each `{ params, props? }`.

```html
---
// src/pages/products/[sku].astro
import type { GetStaticPaths } from 'astro';

export const getStaticPaths = (async () => {
  const products = await fetch('https://api.example.com/products').then((r) => r.json());
  return products.map((p: { sku: string; name: string }) => ({
    params: { sku: p.sku },
    props: { product: p },
  }));
}) satisfies GetStaticPaths;

const { product } = Astro.props;
---
<h1>{product.name}</h1>
```

Constraints worth internalizing:

- **`params` values must be strings (or `undefined` for a rest parameter).** Astro 6.0 removed the old number coercion. I returned `{ tag: 1 }` and the build failed with `[GetStaticPathsInvalidRouteParam] Invalid getStaticPaths() route parameter for tag. Expected a string or undefined, received number (1)`. When migrating from 5.x, stringify ids.
- **Params are not decoded.** Values you return are encoded into the URL as given; use `decodeURI()` when you need to compare or display decoded names (`decodeURI('%5Bpage%5D')` yields `[page]`).
- **`props` are not limited to strings**; they are passed in memory to the page at build time (never serialized to the browser unless you pass them to an island).
- **`getStaticPaths` runs in an isolated scope**, once, before the page renders. It can use imports but not frontmatter variables declared outside it; the compiler warns. In `server` mode a route that needs it must set `prerender = true`; on-demand dynamic routes must **not** use it and cannot receive props, so they read `Astro.params` and fetch data themselves.
- **`Astro` inside `getStaticPaths` is deprecated** (6.0). The context it needs is passed as arguments: `paginate` and `routePattern` (since 5.14).

`routePattern` gives `getStaticPaths` the original route definition as a string, even for files with several dynamic segments. I logged it and saw `/blog/[...page]` (the leading slash is present in 7.4 even though the docs’ comment shows it without). It is useful for building the params of a localized or multi-segment route generically.

### Pagination

`paginate(data, options)` is passed to `getStaticPaths` and returns the array of path objects, each carrying a `page` prop.

```html
---
// src/pages/blog/[...page].astro
import type { GetStaticPaths } from 'astro';

export const getStaticPaths = (({ paginate }) => {
  const all = Array.from({ length: 5 }, (_, n) => ({ n }));
  return paginate(all, { pageSize: 2 });
}) satisfies GetStaticPaths;

const { page } = Astro.props;
---
<p>Page {page.currentPage} of {page.lastPage}</p>
<ul>{page.data.map((x) => <li>{x.n}</li>)}</ul>
{page.url.prev && <a href={page.url.prev}>Previous</a>}
{page.url.next && <a href={page.url.next}>Next</a>}
```

The filename decides the URL shape. With `[...page].astro`, page one is `/blog` and the rest `/blog/2`, `/blog/3`; with `[page].astro` page one is `/blog/1`. My build produced `dist/blog/index.html`, `dist/blog/2/index.html`, `dist/blog/3/index.html` (5 items, size 2), and the `page.url` object for page 2 was `{"current":"/blog/2","next":"/blog/3","prev":"/blog","first":"/blog","last":"/blog/3"}`.

Options: `pageSize` (default 10), `params` (extra params for nested pagination such as `[tag]/[page]`), `props` (extra props for each page), and `format` (since 7.1), a function from the computed URL to the final URL, useful for emitting `.html`-style URLs:

```ts
return paginate(items, { pageSize: 10, format: (url) => `${url}.html` });
```

The `page` object has `data`, `start` and `end` (zero-based indexes), `size`, `total`, `currentPage` (from 1), `lastPage`, and `url.current|prev|next|first|last` (the latter two `undefined` on the first/last page respectively). `page.url` respects `base`: with `base: '/docs'` my output showed `"/docs/blog/2"`.

Nested pagination returns one `paginate()` result per group, passing the group in `params`:

```ts
return tags.flatMap((tag) =>
  paginate(postsFor(tag), { params: { tag }, pageSize: 10 }),
);
```

## Route priority

When several routes could build the same URL, Astro sorts them with these rules, applied in order:

1.  Reserved routes: `_astro/` (bundled assets, optimized images), `_server_islands/` (server islands, Chapter 9), `_actions/` (actions, Chapter 11).
2.  Routes with more path segments beat routes with fewer.
3.  Static routes beat dynamic ones.
4.  Named parameters (`[page]`) beat rest parameters (`[...slug]`).
5.  Prerendered dynamic routes beat on-demand dynamic routes.
6.  Endpoints beat pages.
7.  File-based routes beat configured redirects.
8.  Otherwise, alphabetical by the Node locale.

I put these files in `src/pages` with `output: 'server'`: `[...slug].astro`, `posts/create.astro`, `posts/[page].astro`, `posts/[pid].ts` and `posts/[...slug].astro`, and queried the server:

| Request | Result |
|------------------------------------|------------------------------------|
| `/posts/create` | the static page |
| `/posts/1`, `/posts/abc` | the `[pid].ts` endpoint (endpoint beats page for the same dynamic pattern) |
| `/posts/a/b` | `posts/[...slug]` with `slug=a/b` |
| `/zzz/yy` | root `[...slug]` with `slug=zzz/yy` |

The build also warned: `The route "/posts/[pid]" is defined in both "src/pages/posts/[pid].ts" and "src/pages/posts/[page].astro" using SSR mode. A dynamic SSR route cannot be defined more than once. A collision will result in a hard error in following versions of Astro.` Note what that says: `[pid]` and `[page]` are the *same pattern* (one dynamic segment), so the priority rule “endpoints beat pages” resolved the ambiguity for now, but the framework tells you it will become an error. The documentation’s own example lists both files; treat it as an illustration of ordering, not a layout to copy. Name the parameter identically and split by method or content type instead, or design distinct patterns.

Two corollaries. Redirects defined in config lose to any file route with the same pattern. And because reserved routes win, you cannot define a page at `/_astro/...` or `/_actions/...`; plan URL space accordingly (and never name a top-level section `_actions`).

> **Senior tip:** Ambiguity is a design smell. If two routes can match one URL you now depend on a tie-breaker. Prefer routes that are disjoint by construction, and run `astro build` in CI with warnings treated seriously.

## Redirects

### Configured redirects

```js
// astro.config.mjs
export default defineConfig({
  redirects: {
    '/old': '/posts/create',
    '/blog/[...slug]': '/articles/[...slug]',
    '/gone': { status: 302, destination: '/' },
    '/external': 'https://example.com/',
  },
});
```

Dynamic redirects require the same parameters on both sides. External URLs (`http`/`https`) are allowed since 5.2. In on-demand rendering, the response is a real HTTP redirect; I measured the status codes from a Node standalone server:

- A `GET` to a string redirect: **301**. A `POST` to the same: **308** (to preserve the method).
- An object redirect with `status: 302`: **302** for both `GET` and `POST`.

(The runtime computes: explicit numeric `status` if given, otherwise 301 for `GET` and 308 for other methods.) In static builds there is no server to send a `Location` header, so Astro writes an HTML page with a meta refresh for each redirect; supported adapters instead emit the host’s native redirect configuration (Netlify `_redirects`, Vercel config, etc.), and the status code is only meaningful there. `build.redirects` (default `true`) controls whether the redirect pages are generated.

### Experimental custom redirect page

For static builds, `experimental.redirectPage` (7.4) lets you replace Astro’s generated redirect HTML with your own `src/pages/3xx.astro`, for translated text or branding:

```js
// astro.config.mjs
export default defineConfig({ experimental: { redirectPage: true } });
```

```html
---
// src/pages/3xx.astro
import type { RedirectPageProps as Props } from 'astro';
const { from, to, status, delay } = Astro.props as Props;
---
<html lang="en">
  <head>
    <meta http-equiv="refresh" content={`${delay};url=${to}`} />
    <meta name="robots" content="noindex" />
    <title>Redirecting</title>
  </head>
  <body><p>This page moved. <a href={to}>Continue to {to}</a>.</p></body>
</html>
```

Props: `from` (the pathname being redirected), `to`, `status` (e.g. 301/302) and `delay` (meta-refresh seconds: Astro uses `2` for `302`, `0` for others). It applies to configured redirects, `Astro.redirect()` in prerendered pages and i18n redirects, and *not* to on-demand redirects, which use `Location`. If the file is missing or fails, Astro falls back to its built-in page; if your `<meta http-equiv="refresh">` is missing or points elsewhere, the build warns. Because the file also builds as an ordinary `/3xx` route, visiting it directly shows it without redirect props. Without the flag, `3xx.astro` is just a normal page. Being experimental, pin Astro’s version if you use it.

### Dynamic redirects

`Astro.redirect(path, status?)` (and `context.redirect` in endpoints/middleware) returns a `Response`. In pages, `return` it from the frontmatter:

```html
---
const user = Astro.locals.user;
if (!user) return Astro.redirect('/login', 302);
---
```

Because on-demand rendering streams, **redirects must happen at the page level**, before any output is flushed; calling it from a child component cannot work. Use middleware (Chapter 10) for cross-cutting redirects.

## Rewrites

A rewrite serves another route’s content *without* changing the browser URL. `Astro.rewrite('/es/articles/introduction')` (pages) and `context.rewrite()` (endpoints, middleware) re-run the rendering for the target, including its middleware. If the target does not exist, the result is a 404; if it errors, a 500 in production.

```html
---
// src/pages/[item].astro (on-demand)
const { item } = Astro.params;
if (!(await itemExists(item))) return Astro.rewrite('/404');
---
```

This renders your 404 page with the URL preserved, a good pattern for “product no longer available”. Use a rewrite for shared content under multiple paths (`/products/men/shoes` and `/products/shoes/men`) or for locale variants (`/es-cu` rendering `/es`); use a redirect when the URL should change. Middleware can rewrite conditionally on the response status (Chapter 10 compares `next(payload)` with `context.rewrite()`).

## Error pages, partials and special files

- **`404.astro`** (or `404.md`) builds to `404.html`, which most hosts serve for unmatched URLs. With on-demand rendering it is rendered for unmatched routes.
- **`500.astro`** applies to on-demand routes only and receives an `error` prop (type `unknown`) for whatever was thrown in a page or middleware. I requested a page that throws and got the custom 500 with `error instanceof Error` true. Do not render `error.stack` or raw messages; they reveal server structure. In dev, the terminal logs the error instead of showing the overlay when a `500.astro` exists. If the 500 page itself fails, the host’s default is shown.
- **Partials**: `export const partial = true` renders a page without document wrapper or hoisted styles/scripts, for htmx-style fragment fetching. My server returned `<li>partial</li>` with no doctype.

```html
---
// src/pages/500.astro
interface Props { error: unknown }
const { error } = Astro.props;
console.error(error);            // log it; do not show details
---
<h1>Something went wrong</h1>
```

## URL shape: `trailingSlash`, `build.format`, `base`

Three options control how routes appear:

- **`trailingSlash`: `'ignore'` (default) \| `'always'` \| `'never'`.** For the dev server and on-demand pages, it decides how trailing slashes are matched; in the default, both `/dash` and `/dash/` work. It also affects `import.meta.env.BASE_URL` and what integrations see in `config.base`. `'always'` or `'never'` redirect non-conforming requests (this is the `trailingSlash()` handler in the pipeline).
- **`build.format`: `'directory'` (default) \| `'file'` \| `'preserve'`.** For static output: `/about` is `about/index.html` (directory) or `about.html` (file). I built the same pages with `format: 'file'`: `dist/about.html`, `dist/blog.html`, `dist/blog/2.html`. Pick it to match your host’s URL mapping. Endpoints with file extensions (`rss.xml.ts`) have no trailing slash since 6.0.
- **`base`**: a subpath prefix for the whole site (`base: '/docs'`). Links must include it (use `import.meta.env.BASE_URL`); `page.url` properties include it, as the test showed. In dev, the site is served under the base.

Make the three consistent with the host: a static host serving directories with `trailingSlash: 'never'` causes redirect loops or duplicates. Set `site` too if you generate canonical URLs or sitemaps.

### Decoding

Since Astro 6, route pathnames may be *partially decoded* during normalization, so `Astro.url.pathname` can differ from `new URL(Astro.request.url).pathname` for percent-encoded segments; params derived from the normalized path are affected the same way. My test showed it: for the request `/%64ash`, a page printed `/dash | /%64ash`, the first value being `Astro.url.pathname` (decoded) and the second the raw request path. Over-encoded paths (for example `%252e`) are rejected with an empty 400, and an invalid escape such as `/%E0%A4%A` produced a 400 from the server. Files whose names contain `%25` are no longer supported (they enabled ambiguous encodings).

The lesson: the string you see in `request.url` is *not* necessarily the string Astro routed on.

## Advanced routing: `src/fetch.ts`

By default Astro handles every request with a built-in pipeline of handlers in a fixed order: trailing-slash normalization, redirects, sessions, actions, your middleware, page rendering, i18n and caching. Since 7.0 (stable, on by default), you can replace it by creating `src/fetch.ts` (also `.js`, `.mjs`, `.mts`) whose default export is an object with a `fetch(request): Response | Promise<Response>` method, the same shape as Cloudflare Workers, Bun and Hono. The `Fetchable` type from `astro` describes it.

```ts
// src/fetch.ts
import type { Fetchable } from 'astro';

export default {
  async fetch(request) {
    return new Response('Hello from advanced routing!');
  },
} satisfies Fetchable;
```

`src/fetch.ts` is a **reserved filename**. Rename an unrelated file or set the top-level `fetchFile` option (default `'fetch'`) to another name, or `fetchFile: null` to disable the feature.

Advanced routing replaces *request orchestration*. Pages, endpoints, middleware, actions, sessions and i18n are still defined the usual way; you decide which run, in which order, with what extra logic around them.

### `FetchState`

`new FetchState(request)` creates the per-request state object that every handler takes as its first argument. It exposes `request`, `url` (normalized), `pathname` (base-stripped and decoded, e.g. `/blog/my-post`), `routeData` (matched route, resolved at construction), `cookies` (`AstroCookies`), `locals`, `params`, `status` (default 200, assignable), `response` (set by `pages()` and `middleware()`), and `rewrite(payload)`. `locals` is the same object user middleware and endpoints see, so a custom handler can seed it:

```ts
state.locals.requestId = crypto.randomUUID();
```

### The handlers

Imported from `astro/fetch`:

| Handler | Signature | Purpose |
|------------------------|------------------------|------------------------|
| `astro` | `(state) => Promise<Response>` | The full default pipeline |
| `trailingSlash` | `(state) => Response \| undefined` | Redirect if slash normalization is needed |
| `redirects` | `(state) => Promise<Response> \| undefined` | Configured redirect routes |
| `sessions` | `(state) => void \| Promise<void>` | Registers the session provider (lazy, persisted at end of request) |
| `actions` | `(state) => Promise<Response> \| undefined` | RPC actions return a response; form actions and non-actions return `undefined` |
| `cache` | `(state, next) => Promise<Response>` | Wraps rendering in route-cache logic |
| `middleware` | `(state, next) => Promise<Response>` | Runs `src/middleware.ts`; `next` produces the response, usually `pages` |
| `notFound` | `(state) => Promise<Response> \| undefined` | Renders the custom 404 for unmatched routes (7.4) |
| `pages` | `(state) => Promise<Response>` | Dispatches to the matched page/endpoint/fallback |
| `i18n` | `(state, response) => Promise<Response>` | Post-processes a response: locale redirects, 404s, fallbacks |

The built-in order, which `astro(state)` reproduces, is the table’s list of stages: trailing slash, redirects, sessions, actions, middleware, pages, i18n, with caching wrapped around rendering.

### Pattern 1: wrap the default pipeline

For logging, headers, request ids and timing, you rarely need to take the pipeline apart:

```ts
// src/fetch.ts
import { FetchState, astro } from 'astro/fetch';

export default {
  async fetch(request: Request): Promise<Response> {
    const started = performance.now();
    const state = new FetchState(request);
    state.locals.requestId = crypto.randomUUID();

    const response = await astro(state);

    response.headers.set('server-timing', `app;dur=${(performance.now() - started).toFixed(1)}`);
    response.headers.set('x-request-id', String(state.locals.requestId));
    return response;
  },
};
```

(`state.locals.requestId` needs an `App.Locals` declaration; see Chapter 10.) Headers on a streamed response may need cloning if the `Response` is immutable for some paths such as redirects from `Response.redirect`; in my Hono test, `c.res.headers.set(...)` after `next()` worked for pages, endpoints and redirects alike.

### Pattern 2: compose handlers

When you want to drop stages (no sessions, no i18n) or insert logic between them:

```ts
// src/fetch.ts
import { FetchState, actions, middleware, notFound, pages, redirects, trailingSlash } from 'astro/fetch';

export default {
  async fetch(request: Request): Promise<Response> {
    const state = new FetchState(request);

    const slash = trailingSlash(state);
    if (slash) return slash;

    const redirect = await redirects(state);
    if (redirect) return redirect;

    const action = await actions(state);
    if (action) return action;

    const missing = await notFound(state);
    if (missing) return missing;

    return middleware(state, (s) => pages(s));
  },
};
```

Rules the docs give for composing: put `sessions(state)` before middleware runs if sessions are configured; call `i18n(state, response)` after rendering when you use i18n; add `notFound()` before `middleware()`/`pages()` if you want custom 404 pages for unmatched routes (the all-in-one `astro()` already includes that, and the handler returns `undefined` for a matching route, or an empty 400 for an over-encoded path). Omitting a handler omits the feature: leave out `i18n()` and locale routing logic does not run.

The 7.4 changelog also records a fix that `cache()` now registers the provider before rendering so `Astro.cache` is available to `pages()`.

> **Note:** Earlier previews exposed `state.provide()`, `state.resolve()` and `state.finalizeAll()`. They are removed from the public API, as is `App.Providers`. If a pre-7.0 blog post uses them, it is out of date: stick to the handlers above.

### Pattern 3: Hono

`astro/hono` exports the same handlers as Hono middleware, plus `getFetchState(c)`, which returns the `FetchState` from a Hono context so your own middleware can read `locals`, cookies and the matched route.

```ts
// src/fetch.ts
import { Hono } from 'hono';
import { logger } from 'hono/logger';
import { actions, middleware, notFound, pages, i18n, redirects, trailingSlash, sessions, getFetchState } from 'astro/hono';

const app = new Hono();

app.use(logger());

app.use(async (c, next) => {
  const t = performance.now();
  await next();
  c.res.headers.set('server-timing', `app;dur=${(performance.now() - t).toFixed(1)}`);
});

app.use('/dash', requireAuth);
app.use('/dash/*', requireAuth);

app.use(trailingSlash());
app.use(redirects());
app.use(sessions());
app.use(actions());
app.use(middleware());
app.use(notFound());
app.use(pages());
app.use(i18n());

export default app;

async function requireAuth(c: any, next: () => Promise<void>) {
  const state = getFetchState(c);
  if (!state.locals.user) return c.redirect('/login');
  return next();
}
```

A Hono app exports `fetch`, so it satisfies the entrypoint contract. In my test, installing `hono` and exporting the app from `src/fetch.ts` worked, with `Server-Timing` set on pages, endpoints, redirects and the 500 page. Hono gives you routing, typed context variables, validators and ecosystem middleware (CORS, secure headers, rate limiting) before requests reach Astro.

Note the interplay: `state.locals.user` above is only populated if something earlier set it. Your own Hono middleware (before `requireAuth`) or Astro middleware (which runs *after* `middleware()` in the order shown, so too late for a guard placed before it) must populate it. Ordering is the whole point of the feature, and the most common bug.

## Authorization pitfalls: do not trust pathname matching

The docs carry a caution that a check like `url.pathname.startsWith('/dashboard')` can be bypassed, because the pathname of the incoming request is not guaranteed to be the route Astro matches. I reproduced it concretely. First, a pre-processing guard in `src/fetch.ts` that compares the raw path:

```ts
// DON'T
import { FetchState, astro } from 'astro/fetch';
export default {
  async fetch(request: Request) {
    const state = new FetchState(request);
    if (new URL(request.url).pathname.startsWith('/dash')) {
      return new Response('blocked', { status: 403 });
    }
    return astro(state);
  },
};
```

with a page at `src/pages/dash/index.astro`. Results against the built Node server:

| Request | Status | What happened |
|------------------------|------------------------|------------------------|
| `/dash` | 403 | blocked, as intended |
| `/dash/` | 403 | blocked |
| `/%64ash` (percent-encoded `d`) | **200** | the page rendered: Astro decoded the path and matched `/dash` |
| `//dash` | **200** | the page rendered: the guard saw `//dash`, Astro normalized to `/dash` |
| `/DASH` | 200 | a different route (the catch-all), not the dashboard: matching is case-sensitive |

In the dashboard page, `Astro.url.pathname` printed `/dash` while `new URL(Astro.request.url).pathname` printed `/%64ash` and `//dash`. Pathname string checks protect nothing when the router and your guard disagree about what the path *is*.

The docs suggest guarding with a router that owns matching (Hono). I applied their example (`app.use('/dashboard', requireAuth)` and `app.use('/dashboard/*', requireAuth)`) to `/dash` with Hono 4.13.13: `/dash`, `/dash/` and `/%64ash` redirected to `/login`, **but `//dash` returned 200 and rendered the page**. That is an observed result of my test setup, not a statement about all Hono versions, but it demonstrates the principle: *any* guard that runs before Astro matches a route can disagree with Astro’s matching.

The robust rules:

1.  **Authorize at the point where the route is known.** Do it in Astro middleware (`src/middleware.ts`), where `context.url.pathname` is already Astro’s normalized path and the route has been matched, or inside the page/endpoint itself, or in the actions that perform the sensitive work (`getActionContext`, Chapter 11).
2.  **Prefer matching by route, not string.** In middleware use the matched route pattern (`context.routePattern`, e.g. `/dash`) rather than prefix-checking a pathname string; keep protected pages under a segment, and ask “is this route protected?” using normalized data.
3.  **Defense in depth.** A router guard may stay as a fast path, but the page or data layer must refuse unauthenticated access by itself. Never rely on a single layer, and never put secrets in a prerendered page: prerendered files are served by the host without any Astro code, so no `fetch.ts` guard applies to them at all.
4.  **Test the bypasses.** Add integration tests for encoded segments, double slashes, trailing slashes and case variants against every protected prefix.

## `notFound()` and the 404 contract

Before 7.4, a composed pipeline had to reimplement “no route matched, render `404.astro`”. `notFound(state)` renders your custom 404 (including a prerendered `404.astro`) when no route matches; returns `undefined` for a matching route; and returns an empty `400` for an over-encoded path. Place it before `middleware()` and `pages()`. In Hono: `app.use(notFound())`. Remember that `astro()` already includes it.

## Putting routing decisions together

A checklist when designing routes for a real site:

- Choose `output` by the majority of routes (Chapter 1), override by `prerender`.
- Keep dynamic prerendered routes data-driven through `getStaticPaths`, stringify every param, and use `cacheKey`-aware incremental builds if build time grows (Chapter 6).
- Keep route patterns disjoint; resolve collisions the build warns about.
- Decide `trailingSlash`, `build.format` and `base` together with your host; set `site`.
- Use config redirects for permanent moves, `Astro.redirect()` for conditional ones, rewrites to keep URLs.
- Add `404.astro` and `500.astro` (the latter only for on-demand routes); never display error details.
- Use `src/fetch.ts` only when the default order does not fit: wrapping with `astro()` covers logging, headers and ids; Hono when you want a router in front.
- Never gate access on a raw pathname before Astro matches.

## Key takeaways

- `src/pages` files become routes; `_`-prefixed files and directories are excluded. Dynamic parts use `[param]` and `[...rest]`.
- `getStaticPaths()` is for prerendered dynamic routes; params must be strings (numbers fail the build in 6.0+), props may be anything, and `routePattern` and `paginate` are passed as arguments. On-demand dynamic routes read `Astro.params` and cannot use `getStaticPaths`.
- `paginate()` takes `pageSize`, `params`, `props` and `format` (7.1). `[...page]` makes page one the base URL; `[page]` gives `/1`. `page.url` includes `base`.
- Priority: reserved routes, more segments, static, named over rest, prerendered over on-demand, endpoints over pages, files over redirects, then alphabetical. Identical patterns (`[pid]` vs `[page]`) trigger a collision warning that will become an error.
- Config redirects return 301 for `GET` and 308 for other methods unless a `status` is given; static builds write meta-refresh pages (or host config), customizable with experimental `redirectPage` (`3xx.astro` with `from`, `to`, `status`, `delay`).
- Redirect at page level, before streaming. Rewrites keep the URL and re-run rendering and middleware.
- `500.astro` is on-demand only and gets an `error` prop (`unknown`); never render stacks.
- `trailingSlash`, `build.format` and `base` must agree with your host. `Astro.url.pathname` can differ from the raw request path, as pathnames may be partially decoded.
- `src/fetch.ts` (reserved, `fetchFile` configurable or `null`) default-exports `{ fetch(request) }`. Use `astro(state)` to wrap the full pipeline, or compose `trailingSlash`, `redirects`, `sessions`, `actions`, `cache`, `middleware`, `notFound`, `pages`, `i18n` from `astro/fetch`, or the Hono equivalents (with `getFetchState`) from `astro/hono`.
- Pre-routing pathname guards are bypassable. In tests, `/%64ash` and `//dash` bypassed a raw `startsWith('/dash')` guard, and `//dash` even bypassed a Hono path guard; authorize in middleware, pages or actions, and test encoded variants.
- `notFound()` (7.4) renders the custom 404 in composed pipelines. `state.provide/resolve/finalizeAll` and `App.Providers` are gone.

## Review Questions

1.  Which files in `src/pages` are not turned into routes? Give two reasons you would use that.

2.  Write the file name and `getStaticPaths` for a route that builds `/docs` and `/docs/a/b` from the slugs `undefined` and `"a/b"`.

3.  This build fails. Why, and what is the fix?

    ```html
    ---
    export function getStaticPaths() {
      return [{ params: { id: 1 } }, { params: { id: 2 } }];
    }
    ---
    ```

4.  A dynamic on-demand route `src/pages/u/[id].astro` exports `getStaticPaths`. What is wrong, and how does the page receive per-route data instead?

5.  What does `routePattern` return for `src/pages/[...locale]/[files]/[slug].astro`, and when is it more useful than `params`?

6.  With five items and `pageSize: 2`, list the URLs and file paths generated by `[...page].astro` and by `[page].astro`.

7.  What does `format` do in `paginate()`, and since which version?

8.  Using the priority rules, say which file handles each request: files are `[...slug].astro`, `posts/create.astro`, `posts/[page].astro`, `posts/[...slug].astro`. Requests: `/posts/create`, `/posts/7`, `/posts/a/b`, `/about`, `/`.

9.  `posts/[pid].ts` and `posts/[page].astro` both exist in SSR mode. What does Astro do today, and what does the build warn about the future?

10. Where is a config redirect `/old: '/new'` ignored even though it is defined?

11. What status codes does a string redirect return to a `GET` and to a `POST`? What if the entry is `{ status: 302, destination: '/x' }`?

12. In a static build, how is a redirect represented? Which experimental flag lets you customize the page, which file does it use, and which four props does it receive?

13. Why can a child component not call `Astro.redirect()`? Where should the redirect go?

14. Explain the difference between `Astro.rewrite('/404')` and `Astro.redirect('/404')` from the browser’s perspective, including URL and status code.

15. What does the `error` prop of `500.astro` contain, for which routes is the page used, and what must you avoid displaying?

16. Which `build.format` produces `dist/blog/2.html`? Which `trailingSlash` values redirect? Which three options should you decide together with your host?

17. A page prints `Astro.url.pathname` as `/dash` while `new URL(Astro.request.url).pathname` is `/%64ash`. Explain, and say why that matters for security checks.

18. Multiple choice. Which statement about `src/fetch.ts` is true? (a) It runs only in development; (b) it must default-export an object with a `fetch(request)` method; (c) it replaces `src/middleware.ts`; (d) it is optional but ignored if `output` is `static`.

19. What are two ways to handle an unrelated existing `src/fetch.ts`? Which value disables advanced routing?

20. Write a `src/fetch.ts` that adds an `x-request-id` header to every response while keeping the default pipeline.

21. In what order does Astro’s built-in pipeline run its stages? Which handler would you call before middleware if you use sessions, and which after rendering if you use i18n?

22. What does `actions(state)` return for an RPC action versus an HTML form submission versus a normal page request?

23. What did 7.4 add with `notFound()` and what does it return in each of its three cases?

24. Find the bug: the guard below is intended to protect `/admin`, and the pipeline uses Astro middleware that sets `locals.user`. Why does the guard never see the user?

    ```ts
    app.use('/admin/*', (c, next) => getFetchState(c).locals.user ? next() : c.redirect('/login'));
    app.use(middleware());
    app.use(pages());
    ```

25. Using the results table in this chapter, why is `if (pathname.startsWith('/dash')) return 403` in a `fetch.ts` insufficient? Name two request paths that bypass it.

26. Give three places where a robust authorization check can live, and one place where it can never apply (hint: prerendered output).

27. Which APIs were removed from the public advanced-routing surface in 7.x, and what replaced the need for them?

28. Design: a multilingual shop wants request ids, timing headers, a rate limiter on `/_actions/*`, i18n routing, and an admin area. Sketch a Hono-based `src/fetch.ts` order of handlers and say where each authorization check belongs.
