# Chapter 8: On-Demand Rendering, Adapters and Deployment

Astro’s default output is a folder of static files. The moment a page needs the request (a cookie, a header, a database row, a personalised fragment) it must be rendered by a server at request time. That is **on-demand rendering**, and it is gated by exactly one requirement: an **adapter** that packages your project for a runtime.

This chapter explains how to opt routes in and out of prerendering, what the request-time API surface looks like (`Astro.request`, `clientAddress`, `cookies`, `Astro.response`), how adapters work (including the `createApp()` entrypoint API you would use to write one), what is specific to the Node, Cloudflare, Vercel and Netlify adapters, how streaming behaves and how to turn it off, how to deploy statically versus on a server (including Docker), how to survive version skew during rolling deploys, and how to cache and observe what you ship. Behaviours not settled by the docs were checked against `astro@7.4.1` with `@astrojs/node@11.1.9`, and are marked as verified.

## Prerendering and on-demand rendering

### `output` and `prerender`

`output` has two values: `'static'` (the default) and `'server'`. Per-route `export const prerender = true | false` overrides the default for a page or endpoint.

| `output` | Default for each route | Opt out with | Typical use |
|------------------|------------------|------------------|------------------|
| `'static'` | Prerendered at build | `export const prerender = false` | Mostly static site with a few dynamic routes |
| `'server'` | Rendered on demand | `export const prerender = true` | App-like site with a few static pages |

The docs’ advice is to **start with `'static'`** until most routes are dynamic: `'server'` “does not bring any additional functionality”, it only flips the default. Many guides mention a third “hybrid” mode; since Astro 5 that is simply `'static'` plus `prerender = false` on some routes, though adapter feature lists (`supportedAstroFeatures`) still contain a `hybridOutput` key for historical reasons.

```html
---
// src/pages/account.astro
export const prerender = false; // required in output: 'static'; redundant in 'server'
const session = Astro.cookies.get('sid')?.value;
if (!session) return Astro.redirect('/login');
---
<h1>Your account</h1>
```

`prerender` must be a literal `true` or `false` that Astro can read statically (not computed from environment variables), because the decision happens at build analysis time.

### The adapter requirement

Any non-prerendered route requires an adapter, and so do **server islands** (`server:defer`, Chapter 9) and live content collections (Chapter 6). The official adapters are Node, Netlify, Vercel and Cloudflare; install with `npx astro add node` (or `netlify`, `vercel`, `cloudflare`), which edits `astro.config.mjs` for you.

An adapter can also be useful on an entirely static site: Netlify’s adapter enables the Image CDN and translates `redirects` into a `_redirects` file; server islands need one even if every page is prerendered.

### Build output shape

With the Node adapter and `output: 'static'` plus one dynamic route, `astro build` produced (verified):

```text
dist/
  client/          static assets and prerendered HTML (index.html files, _astro/)
  server/
    entry.mjs      the server entrypoint
    chunks/        on-demand renderers
    .prerender/    the prerender environment's bundle, used during the build
```

Astro builds with several Vite environments (Chapter 1): `client`, `ssr`, `prerender` and `astro`. The prerender bundle exists so prerendered pages can be rendered in a runtime different from the production server (for Cloudflare, `workerd` by default; see below).

### `Astro.isPrerendered` and middleware at build time

`Astro.isPrerendered` (and `context.isPrerendered` in endpoints and middleware) is `true` while rendering a page at build time and `false` at request time. It exists mainly for middleware: **middleware runs at build time for prerendered pages**, where there is no real request. Reading headers or `clientAddress` there is meaningless, and `Astro.clientAddress` on a prerendered route throws. I verified this: building a prerendered page that reads `Astro.clientAddress` fails with `PrerenderClientAddressNotAvailable: Astro.clientAddress cannot be used inside prerendered route src/pages/ip.astro`.

In my test project a middleware pair that recorded `ctx.isPrerendered` showed `true` in the HTML baked into a prerendered page (`pre=true`) and `false` in an on-demand response header, and the prerendered page, served by the standalone server from `dist/client`, did not pass through middleware again at runtime. This is the `middlewareMode: 'classic'` behaviour; Chapter 10 covers `'edge'`.

> **Warning:** Do not put request-dependent logic in middleware without guarding on `isPrerendered`. A header read that “works in dev” will either throw or bake a constant into static HTML at build time.

## The request-time API

### `Astro.request` and `context.request`

A standard `Request`. In prerendered pages you only get a usable `request.url`. On demand you get headers, method and a body you can read once:

```html
---
export const prerender = false;
const ua = Astro.request.headers.get('user-agent') ?? 'unknown';
const accept = Astro.request.headers.get('accept-language');
---
```

### `Astro.clientAddress`

`clientAddress` is the peer IP and is available only on demand. The key design point: **who sets it is the adapter**, not the client. With the Node adapter I sent `x-forwarded-for: 9.9.9.9` and received `clientAddress` of `127.0.0.1` (verified): the header was ignored. Behind a reverse proxy you will therefore see the proxy’s address unless the adapter or your entrypoint maps a trusted header. On Cloudflare the adapter’s entrypoint maps `cf-connecting-ip`. If you write your own entrypoint, pass `clientAddress` to `app.render()` from a source you trust.

```ts
// custom entrypoint fragment
const response = await app.render(request, {
  clientAddress: trustedProxyHeader(request) ?? undefined,
});
```

Do not rate-limit or geolocate on a client-supplied `x-forwarded-for` unless your edge strips and rewrites it. A related setting is `security.allowedDomains`, which lists the host patterns the app will accept so `Astro.url` and origin checks cannot be spoofed by a `Host` or `X-Forwarded-Host` header (Chapter 16).

### Cookies

`Astro.cookies` (and `context.cookies`) work on demand:

| Method | Notes |
|------------------------------------|------------------------------------|
| `get(key, { decode })` | Returns `AstroCookie` (`value`, `json()`, `number()`, `boolean()`) or `undefined` |
| `has(key)` | True if set during this request *or* present in the request |
| `set(key, value, options)` | `value` may be a string or an object (JSON-stringified); options include `domain`, `expires`, `httpOnly`, `maxAge`, `path`, `sameSite`, `secure`, `partitioned` (5.17) |
| `delete(key, options)` | Expires the cookie; `has()` then returns false |
| `merge(other)` | Merge another `AstroCookies`; same names overwrite |
| `headers()` | Iterator of `Set-Cookie` values to be sent |
| `consume()` | 6.3+: marks cookies as consumed and returns headers; later `set()` logs a warning. Used by adapters |

```html
---
export const prerender = false;
const count = Astro.cookies.get('views')?.number() ?? 0;
Astro.cookies.set('views', String(count + 1), {
  path: '/', httpOnly: true, sameSite: 'lax', secure: true, maxAge: 60 * 60 * 24 * 30,
});
---
<p>Visit #{count + 1}</p>
```

An endpoint returning `Response` does not need to copy cookie headers manually: with the standard adapters, cookies set through `context.cookies` are added to the response. In a custom server entrypoint, either pass `addCookieHeader: true` to `app.render()` or iterate `app.setCookieHeaders(response)` and `append('Set-Cookie', ...)` for each value so that multiple cookies are not folded into one header.

### `Astro.response`

`Astro.response` is a `ResponseInit`-like object: set `status`, `statusText` and `headers` on it from the page frontmatter.

```html
---
export const prerender = false;
import { getProduct } from '../../lib/db';
const product = await getProduct(Astro.params.id!);
if (!product) {
  Astro.response.status = 404;
  Astro.response.statusText = 'Not found';
}
Astro.response.headers.set('Cache-Control', 'public, max-age=60, s-maxage=300');
---
```

Two limits matter in production:

1.  **Headers and status are page-level only.** Layouts and components cannot change them: by the time a component runs, streaming may already have flushed the head of the response. Set them in the page frontmatter, in middleware (by modifying the `Response` after `await next()`), or in endpoints.
2.  **Server islands are different:** a deferred component renders in its own request, so it *can* set response headers for its own response (I verified `Cache-Control: public, max-age=60` set inside a `server:defer` component’s frontmatter appeared on the island response, Chapter 9).

To short-circuit, return a `Response` from a page: `return new Response(null, { status: 404 })` or `return Astro.redirect('/products', 301)`.

## Streaming

On-demand pages stream HTML by default: Astro flushes chunks of markup as components render, so the browser can start parsing before slow data resolves. I measured a page that awaits a 600 ms promise in the middle of the template. With streaming (default), the first chunk (`<!DOCTYPE html><p>first</p>`) arrived at 0.00 s and the slow part together with the following siblings arrived at 0.59 s. Rendering is in document order, so content *after* the slow expression waits behind it.

Practical consequences:

- Put slow fetches as late in the template as possible, or isolate them in server islands so everything else is complete before they resolve.
- Status and headers cannot depend on content rendered after the first flush, which is why they are page-level.
- A late-thrown error cannot change the status code: the 200 header may already be on the wire. Fetch and validate *before* the first output, in frontmatter, when you need to return a 404 or redirect.

### Disabling streaming

Some CDNs can only cache non-streamed HTML. You can disable streaming:

```js
// astro.config.mjs (Node adapter, option available since @astrojs/node 9.3)
adapter: node({ mode: 'standalone', experimentalDisableStreaming: true });
```

With this set, the same slow page was delivered as a single chunk with `content-length: 49` after the delay, instead of `transfer-encoding: chunked` (verified). Custom entrypoints use `createApp({ streaming: false })`. Disabling streaming costs time-to-first-byte on every route, so scope it carefully; the Node adapter option is the documented one and is named experimental.

Since 7.0, queued rendering was promoted and made streaming based, and Node polling was removed (Chapter 17 covers the performance side).

## The adapter API from the user’s side

An adapter is an integration that calls `setAdapter()` in `astro:config:done`. From a project’s perspective it provides:

- a **server entrypoint** (built into `dist/server/entry.mjs` for Node) that turns a host’s request format into a standard `Request` and the `Response` back;
- **supported features** (`supportedAstroFeatures`: `staticOutput`, `hybridOutput`, `serverOutput`, `i18nDomains`, `envGetSecret`, `sharpImageService`) so Astro can warn about unsupported combinations;
- optional **adapter features** that change build output: `middlewareMode` (`'classic'` or `'edge'`), `buildOutput`, `staticHeaders`, `preserveBuildClientDir`, `preserveBuildServerDir`;
- default **session drivers**, image services and a preview entrypoint so `astro preview` works.

Chapter 18 covers authoring adapters; here is the part every user of the platform should understand.

### `createApp()` and the `App` instance

Since Astro 6 the entrypoint API is `createApp()` from `astro/app/entrypoint` (it replaced `NodeApp`, `createExports()` and `start()`; adapters opt into the new flow with `entrypointResolution: 'auto'`, while the old `'explicit'` mode is deprecated):

```ts
// my-adapter/server.ts
import { createApp } from 'astro/app/entrypoint';
import { createRequest, writeResponse } from 'astro/app/node';
import { createServer } from 'node:http';

const app = createApp({ streaming: true });

createServer(async (req, res) => {
  const request = createRequest(req, { allowedDomains: app.getAllowedDomains() });
  if (!app.match(request)) {
    res.statusCode = 404;
    res.end('Not found');
    return;
  }
  const response = await app.render(request, {
    addCookieHeader: true,
    clientAddress: req.socket.remoteAddress,
    locals: { requestId: crypto.randomUUID() },
  });
  await writeResponse(response, res);
}).listen(8080);
```

`App` methods: `render(request, options)`, `match(request, allowPrerenderedRoutes = false)`, `adapterLogger` (6.2), `getAllowedDomains()`, `removeBase(pathname)`, and `setCookieHeaders(response)`. `RenderOptions` are `addCookieHeader`, `clientAddress`, `locals`, `prerenderedErrorPageFetch`, `waitUntil` (6.2; lets cache providers schedule background work) and `routeData`. `createRequest()` and `writeResponse()` from `astro/app/node` convert between Node’s `IncomingMessage`/`ServerResponse` and web `Request`/`Response`.

Two takeaways for application developers:

- `locals` passed to `render()` is how a front proxy or framework injects trusted data into middleware. The Node adapter’s middleware mode forwards an object as the fourth argument, `ssrHandler(req, res, next, locals)`.
- `prerenderedErrorPageFetch` lets you serve prerendered `404.html`/`500.html` from disk instead of an HTTP self-call, which matters where a function cannot call itself.

## Adapter specifics

### Node (`@astrojs/node`)

```js
import node from '@astrojs/node';
export default defineConfig({
  output: 'server',
  adapter: node({
    mode: 'standalone',        // or 'middleware'
    staticHeaders: false,      // 10.0+: serve headers for prerendered pages (e.g. CSP) on the Response
    bodySizeLimit: 10 * 1024 * 1024, // default 1 GB; 0 or Infinity disables
    experimentalDisableStreaming: false,
  }),
});
```

- **`mode: 'standalone'`** produces `dist/server/entry.mjs`, which starts an HTTP server when run and also serves `dist/client`. Control host and port via `HOST` and `PORT` environment variables (default listen address is `localhost`, so containers need `HOST=0.0.0.0`). For HTTPS set `SERVER_CERT_PATH` and `SERVER_KEY_PATH`; usually you terminate TLS at a proxy instead.
- **`mode: 'middleware'`** exports `handler(req, res, next, locals)` for Express, Fastify (with `@fastify/middie`) and similar. It does **not** serve files: mount `dist/client` yourself with the same `base`.
- Assets in `dist/client/_astro/` are hashed, so the adapter sends `Cache-Control: public, max-age=31536000, immutable` for them. Prerendered pages served by the adapter carried `Cache-Control: public, max-age=0` in my test, so put a CDN in front with its own rule for HTML.
- `bodySizeLimit` is the *adapter-level* cap on request bodies; the default 1 GB is generous, so lower it for public forms. Actions and server islands have their own limits (`security.actionBodySizeLimit`, `security.serverIslandBodySizeLimit`, default 1 MB each).
- **Sessions** use filesystem storage by default; for multiple instances configure a shared driver. `session: false` (7.2) tree-shakes the session runtime when unused.
- **Environment variables:** neither Astro nor the adapter loads `.env` at runtime. Inject variables through your process manager, Docker `ENV` or a tool such as `dotenvx`.

### Cloudflare (`@astrojs/cloudflare` 13/14 with Astro 6/7)

- Development and preview run in **`workerd`**, matching production. Pages support was removed; you deploy Workers with static assets.
- `prerenderEnvironment: 'workerd' | 'node'` (default `'workerd'`) chooses the runtime for prerendering. Use `'node'` when a prerendered page needs `node:fs` or an npm package incompatible with `workerd`. On-demand pages always run in `workerd`.
- `Astro.locals.runtime` was removed in v13. Use `import { env } from 'cloudflare:workers'` for bindings, `Astro.locals.cfContext` for the `ExecutionContext` (`waitUntil`), and `Astro.request.cf` for geolocation. `astro:env/server` also works with Cloudflare variables and secrets.
- `imageService` defaults to `'cloudflare-binding'`; since 14.2 it may be `{ build: 'compile' | 'cloudflare-binding', runtime?: 'cloudflare-binding' | 'passthrough' }`. Related options: `imagesBindingName` (`IMAGES`), `sessionKVBindingName` (`SESSION`).
- **Sessions** use Workers KV, automatically provisioned by Wrangler. KV is eventually consistent across regions (up to about 60 seconds), which matters for users who change regions between requests.
- Enable the `nodejs_compat` compatibility flag in `wrangler.jsonc` to use `node:*` imports. Add `vite.build.minify: false` while debugging because Wrangler minifies errors.
- Static `_headers` and `_redirects` files in `public/` apply to static assets only, **not** to Worker responses.
- `@astrojs/cloudflare/fetch` and `@astrojs/cloudflare/cache` (14.0, experimental CDN cache provider) integrate with advanced routing and route caching (Chapters 5 and 12).

### Vercel (`@astrojs/vercel`)

- `isr` (`boolean | { expiration, bypassToken, exclude }`) deploys on-demand pages as ISR functions. ISR requests drop search params, like static requests. By default `Cache-Control` headers are ignored; setting `expiration` makes your headers count. Revalidate with a `HEAD`/`GET` carrying `x-prerender-revalidate: <bypassToken>`; preview with Vercel’s draft mode via the `__prerender_bypass` cookie. `exclude` takes strings and regexes.
- By default middleware is bundled **into** the ISR function, so it only runs on a cache miss or regeneration. Set `middlewareMode: 'edge'` to run it in front of the cache on every request (including cache hits); then `context.locals` is serialized to JSON and sent in a header to the serverless function, which rejects direct requests with 403.
- `skewProtection: true` enables Vercel Skew Protection (Pro and Enterprise). Other options: `includeFiles`, `excludeFiles`, `maxDuration`, `webAnalytics`, `imageService`, `imagesConfig`, `devImageService`, `staticHeaders` (10.0).
- No default session driver: configure one (for example Redis from the Vercel marketplace).

### Netlify (`@astrojs/netlify`)

- `middlewareMode: 'edge'` runs middleware on Netlify Edge Functions for *all* requests, including static assets and prerendered pages, enabling redirects and access control for static content. `Astro.locals.netlify.context` exposes the edge context (not on prerendered pages); type it with `NetlifyLocals`.
- `cacheOnDemandPages: true` caches server-rendered pages up to a year; override per page with `CDN-Cache-Control`.
- Skew protection is automatic since 6.6: the adapter injects the deploy id into Astro’s own internal requests (actions, server islands, view transitions, prefetch). For your own `fetch` calls add `X-Netlify-Deploy-ID: import.meta.env.DEPLOY_ID`.
- Sessions use Netlify Blobs. `devFeatures` (`images`, `environmentVariables`, `edgeFunctions`) emulate the platform in `astro dev`. `imageCDN: false` opts out of the Image CDN; `includeFiles` / `excludeFiles` take globs.
- Netlify’s CDN cache providers (`cacheNetlify()` from `@astrojs/netlify/cache`), like Vercel’s and Cloudflare’s, are **experimental** and must be enabled manually even though core route caching is stable.

### Choosing an adapter

| Constraint | Prefer |
|------------------------------------|------------------------------------|
| Self-hosted, long-lived containers, filesystem sessions | Node |
| Global edge with bindings (KV, R2, D1), strict `workerd` semantics | Cloudflare |
| Serverless functions with ISR-style page caching and skew protection | Vercel |
| Edge middleware on static content plus Blobs and Image CDN | Netlify |

## Conflicts between prerendered routes

Two routes can generate the same prerendered URL, for example `src/pages/a.astro` and a `[x].astro` whose `getStaticPaths()` returns `'a'`. Since 6.0 `prerenderConflictBehavior` (top-level, default `'warn'`) controls this and replaced the experimental `failOnPrerenderConflict`:

| Value              | Behaviour                                            |
|------------------------------------|------------------------------------|
| `'warn'` (default) | Log a warning; build with the highest-priority route |
| `'error'`          | Fail the build                                       |
| `'ignore'`         | Silently build the highest-priority route            |

Verified: with the default, the build logged `Could not render '/a' from route '/[x]' as it conflicts with higher priority route '/a'` and `dist/client/a/index.html` contained the static page; with `'error'` the build failed with `PrerenderRouteConflict`. In CI, set `'error'`: a silently shadowed route is a latent content bug. Priority follows the routing rules from Chapter 5.

## Static versus server hosting

| Aspect | Static hosting (S3, GitHub Pages, any CDN) | Server hosting (adapter) |
|------------------------|------------------------|------------------------|
| Output | `dist/` of files | `dist/client` + server bundle |
| Dynamic routes | None; use client JS or third-party services | Pages, endpoints, actions, sessions, server islands, live collections |
| Scaling | Free with the CDN | Per function/instance |
| Failure modes | Stale content | Cold starts, runtime errors, secrets |
| Deploy | Upload `dist/` | Platform adapter or container |

Many sites are best served by *static output plus an adapter only for a few routes*: the static pages come from the CDN and only the dynamic routes invoke compute. Redirect and header features differ by host: Netlify and Cloudflare read `_redirects`/`_headers`; adapters translate Astro’s `redirects` config for hosts that need it.

Build command and publish directory for static hosts: `astro build` (or your `build` script) and `dist`. With an adapter, follow the adapter docs, because the publish directory and function folders differ per platform.

### Docker

The documented SSR Dockerfile uses the Node adapter in standalone mode:

```docker
FROM node:lts AS base
WORKDIR /app
COPY package.json package-lock.json ./

FROM base AS prod-deps
RUN npm install --omit=dev

FROM base AS build-deps
RUN npm install

FROM build-deps AS build
COPY . .
RUN npm run build

FROM base AS runtime
COPY --from=prod-deps /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
ENV HOST=0.0.0.0
ENV PORT=4321
EXPOSE 4321
CMD ["node", "./dist/server/entry.mjs"]
```

Add a `.dockerignore` with `node_modules`, `dist` and `.DS_Store`. Hardening additions worth making in practice:

- Pin a Node 22 image that satisfies Astro 7’s `>= 22.22.0` requirement rather than floating `lts`.
- Provide `ASTRO_KEY` at *build* time (Chapter 9) so image rebuilds do not invalidate in-flight encrypted server-island props, and provide secrets at *runtime* via `ENV` or orchestrator secrets.
- Run as a non-root user and put a reverse proxy in front for TLS, gzip/brotli and the real client IP.
- For static output, serve `dist/` from nginx with `try_files $uri $uri/index.html =404;` and a `404.html` error page as in the recipe.

## Skew, rolling deploys and encryption keys

**Version skew** is a client running build N while the server (or another instance) runs build N+1. In Astro this surfaces in three places: hashed asset URLs that vanished from the new deployment, internal requests (`/_actions/*`, `/_server-islands/*`, prefetch, ClientRouter fetches) that the new server interprets differently, and **encrypted server-island props**.

Astro encrypts server-island props with a key generated **per build** and embedded in the server bundle. In a rolling deploy two instances hold two different keys; a page rendered by instance A (build N, key A) will request its island from instance B (key B), which cannot decrypt it. I confirmed the failure mode by sending a malformed island request: the server answered `400 Bad request: Encrypted componentExport value is invalid.` The same applies when a CDN keeps serving old HTML after a deploy. The fix is to reuse a stable key:

```bash
astro create-key
# [crypto] Generated a key to encrypt props passed to server islands...
# ASTRO_KEY=Q2m/UBV1QfmjIeEkIvpvlHtNoCXk5r/5ZyQUS8ShlqU=
```

Set `ASTRO_KEY` in the *build* environment (CI/CD or host build settings). Rotate it deliberately: rotation invalidates cached HTML that embeds old encrypted props, as well as incremental-build caches.

Host-level mitigations:

| Host | Mechanism |
|------------------------------------|------------------------------------|
| Netlify | Automatic deploy-id header on Astro’s internal requests (6.6+) |
| Vercel | `skewProtection: true` (Pro/Enterprise) |
| Any | Keep previous deploys’ hashed assets available for a grace period; keep `ASTRO_KEY` stable; make `/_actions` and island endpoints backward compatible for one release |

The adapter API exposes this to adapter authors as `client.internalFetchHeaders` (headers added to Astro’s own fetches: actions, ClientRouter, server islands, prefetch) and `client.assetQueryParams` (query parameters appended to asset URLs). That is how Netlify and Vercel carry a deploy id.

## Preview and background servers

`astro preview` serves the build output locally to catch build errors; the docs state clearly that it is **not designed for production**. With an adapter it uses the adapter’s `previewEntrypoint` (Node, Cloudflare’s `workerd` preview, and so on).

Since 7.2 preview supports the same background mode as dev: `astro preview --background` starts a detached server with JSON logging, and `astro preview status`, `logs [--follow]` and `stop` manage it (`stop` sends `SIGTERM` and escalates to `SIGKILL` after 5 seconds). `--ignore-lock` (7.3 for preview) skips the lock file; it cannot be combined with `--background` or `--force`. Background mode is automatic when an AI coding agent is detected on macOS and Linux; opt out with `ASTRO_PREVIEW_BACKGROUND=0` (and `ASTRO_DEV_BACKGROUND=0` for dev). This is convenient for E2E pipelines: start `astro preview --background`, run Playwright against the printed URL, then `astro preview stop`.

## Caching in production

Layered, from the outside in:

1.  **Hashed static assets**: immutable one-year cache (set by Node, Cloudflare and others automatically).
2.  **Prerendered HTML**: short or revalidated caching at the CDN, purged on deploy.
3.  **On-demand HTML**: `Astro.response.headers.set('Cache-Control', ...)` per page, or platform features (`cacheOnDemandPages` on Netlify, `isr` on Vercel), or Astro’s route caching (`cache`, `routeRules`, `Astro.cache.set`, Chapter 12).
4.  **Server islands**: they are `GET` requests with encrypted query strings and honour `Cache-Control` set by the island component; they fall back to `POST` above 2048 bytes of URL, which breaks caching (Chapter 9).
5.  **Data**: build-time collections (rebuild-bound) versus live collections with cache hints (Chapter 6).

Rules of thumb: never cache a response that depends on cookies or `Authorization` without `Vary` or `private`; remember that cookies set on a cached response are replayed to other users by a naive shared cache; and never let CDNs cache `POST` actions.

## Observability

Production needs more than `console.log`:

- **Logs.** Astro 7 has a stable logger (`logger` config with `logHandlers.json()`, `node()` and `console()` from `astro/config`; `context.logger` is always available since 7.0; `app.adapterLogger` in custom entrypoints). Prefer structured JSON in containers (Chapter 17).
- **Errors.** Middleware is the right place to wrap `await next()` in a try/catch, tag requests with a request id (also pass it from a front proxy via `locals`), and report to your error tracker. Note that a 500 page renders after middleware, and if your middleware itself threw, `Astro.locals` is unavailable on that page.
- **Health.** Add a static `/healthz` endpoint or an on-demand `/readyz` that touches your database. Probe with `HEAD`: Astro answers `HEAD` for endpoints defining `GET` by calling `GET` and stripping the body, but an exported `ALL` takes precedence over that fallback (Chapter 10).
- **Metrics.** Wrap `app.render()` in a custom entrypoint (or middleware) to record latency, status and route pattern (`context.routePattern`), which keeps cardinality low compared to raw paths.
- **Build timings.** `astro build --timings` (7.4) prints where build time went.

> **Senior tip:** The single highest-value production habit is setting `prerenderConflictBehavior: 'error'` in CI together with a pinned `ASTRO_KEY`. Both convert silent, hard-to-reproduce production surprises into build failures.

## Putting it together: a production-ready Node setup

```js
// astro.config.mjs
import { defineConfig, envField } from 'astro/config';
import svelte from '@astrojs/svelte';
import node from '@astrojs/node';

export default defineConfig({
  site: 'https://shop.example.com',
  output: 'static',
  adapter: node({ mode: 'standalone', bodySizeLimit: 2 * 1024 * 1024 }),
  integrations: [svelte()],
  prerenderConflictBehavior: 'error',
  security: { allowedDomains: [{ hostname: 'shop.example.com', protocol: 'https' }] },
  session: false, // no sessions yet; tree-shakes the runtime
  env: {
    schema: {
      DATABASE_URL: envField.string({ context: 'server', access: 'secret' }),
    },
  },
});
```

```ts
// src/pages/healthz.ts
import type { APIRoute } from 'astro';
export const prerender = false;
export const GET: APIRoute = () =>
  Response.json({ ok: true, at: new Date().toISOString() }, { headers: { 'Cache-Control': 'no-store' } });
```

```html
---
// src/pages/products/[id].astro: dynamic page with a Svelte island
export const prerender = false;
import AddToCart from '../../components/AddToCart.svelte';
import { getProduct } from '../../lib/db';

const product = await getProduct(Astro.params.id!);
if (!product) return new Response(null, { status: 404 });
Astro.response.headers.set('Cache-Control', 'public, max-age=30, s-maxage=120');
---
<h1>{product.name}</h1>
<AddToCart client:visible productId={product.id} stock={product.stock} />
```

```html
<!-- src/components/AddToCart.svelte -->
<script lang="ts">
  let { productId, stock }: { productId: string; stock: number } = $props();
  let qty = $state(1);
  let busy = $state(false);
  const max = $derived(Math.min(stock, 10));

  async function add() {
    busy = true;
    try {
      await fetch('/api/cart', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ productId, qty }),
      });
    } finally {
      busy = false;
    }
  }
</script>

<label>Qty <input type="number" min="1" max={max} bind:value={qty} /></label>
<button disabled={busy || stock === 0} onclick={add}>{stock === 0 ? 'Sold out' : 'Add to cart'}</button>
```

The page is on-demand, sets an explicit shared-cache policy, returns a real 404 before streaming begins, and hands only serializable data to the island.

## Key takeaways

- `output` is `'static'` or `'server'`; `export const prerender` flips individual routes. Start static. Any on-demand route, server island or live collection needs an adapter.
- Middleware runs at build time for prerendered pages; guard request-specific logic with `isPrerendered`. `Astro.clientAddress` throws on prerendered routes and is set by the adapter, not by client headers.
- Response status and headers are page-level, because streaming flushes HTML as it renders; validate and decide status before the first output. Server islands can set their own headers.
- Streaming is on by default; `experimentalDisableStreaming` (Node) or `createApp({ streaming: false })` returns a single buffered chunk and trades time-to-first-byte for CDN cacheability.
- Adapters expose `createApp()` from `astro/app/entrypoint` with `render`, `match`, `setCookieHeaders`, `getAllowedDomains`, and `createRequest`/`writeResponse` from `astro/app/node`; pass `clientAddress`, `locals`, `waitUntil` from trusted sources.
- Node: `standalone` versus `middleware` modes, `HOST`/`PORT`, `bodySizeLimit`, `staticHeaders`, no `.env` loading. Cloudflare: `workerd`, `prerenderEnvironment`, bindings via `cloudflare:workers`, KV sessions. Vercel: `isr`, `skewProtection`, edge middleware. Netlify: edge middleware, `cacheOnDemandPages`, automatic skew protection, Blobs.
- `prerenderConflictBehavior` (default `'warn'`) decides what happens when two routes emit the same prerendered URL; use `'error'` in CI.
- Rolling deploys and CDN-cached HTML break encrypted server-island props unless `ASTRO_KEY` (from `astro create-key`) is stable across builds.
- `astro preview` is not for production but supports `--background`, `status`, `logs` and `stop`.
- Cache in layers (assets, prerendered HTML, on-demand HTML, islands, data) and log structurally.

## Review Questions

1.  With `output: 'static'`, what must a page contain to be rendered on demand, and what must exist in the project for the build to succeed?

2.  What is the difference between `output: 'server'` and `output: 'static'` with `prerender = false` on a few routes, in terms of features available?

3.  What does `Astro.isPrerendered` return inside middleware while building a prerendered page, and why does the middleware still run?

4.  What happens when a prerendered page reads `Astro.clientAddress`?

5.  You deploy behind nginx and `Astro.clientAddress` is always `172.18.0.2`. What are two correct ways to get the real client address, and what is the incorrect way?

6.  Which of these can set the response status from a layout component? (a) `Astro.response.status = 404` in the layout (b) `return new Response(...)` in the layout (c) neither, only the page, middleware or an endpoint (d) `Astro.cookies.set()`.

7.  Predict the observable difference on the wire for a page that awaits a slow promise in the middle of its template with (a) default streaming, and (b) `experimentalDisableStreaming: true`.

8.  Find the bug:

    ```html
    ---
    export const prerender = false;
    const product = await getProduct(Astro.params.id);
    ---
    <h1>{product?.name}</h1>
    {Astro.response.status = product ? 200 : 404}
    ```

9.  Why does an endpoint exporting both `GET` and `ALL` behave unexpectedly for `HEAD` requests?

10. In a custom Node entrypoint, why is `app.setCookieHeaders(response)` iterated and each value appended instead of reading the `Set-Cookie` header once?

11. Name the options of `RenderOptions` and say which one is meant to let cache providers do background work.

12. Complete the code so unmatched requests get a custom 404 instead of Astro’s: `ts const app = createApp(); export async function handler(request: Request) { // ??? }`

13. Standalone versus middleware mode of the Node adapter: which serves static files, and which export do you mount in Express?

14. A Docker container for the Node adapter starts but is unreachable from the host. What environment variable is probably missing?

15. Why will `.env` values not be available to a Node build that is run with `node dist/server/entry.mjs`, and what are two ways to provide them?

16. On Cloudflare, a prerendered page imports `node:fs` and the build fails. Which adapter option addresses it, and what does it not affect?

17. Where do you read a KV binding on Cloudflare after v13, given that `Astro.locals.runtime` is gone?

18. Vercel ISR is enabled and your middleware sets a security header. Why might the header be missing on cached responses and how do you fix it?

19. What does `middlewareMode: 'edge'` change for how `context.locals` reaches the serverless function on Vercel and Netlify, and what protects the function from direct calls?

20. A route `src/pages/docs.astro` and `src/pages/[page].astro` (whose `getStaticPaths()` includes `'docs'`) exist. What happens with the default `prerenderConflictBehavior`, and what do you set in CI?

21. Explain why a rolling deployment can produce `400 Bad request: Encrypted componentExport value is invalid`, and the fix.

22. Which environment does `ASTRO_KEY` need to be set in: build, runtime, or both? Why?

23. Multiple choice: Netlify’s skew protection for your own `fetch('/api/x')` calls requires you to (a) nothing, it is automatic for all fetches (b) add the `X-Netlify-Deploy-ID` header using `DEPLOY_ID` (c) set `skewProtection: true` in the adapter (d) use `ClientRouter`.

24. How do you run `astro preview` in the background in CI and stop it afterwards?

25. List the cache layers for an on-demand product page that sets `Cache-Control: public, s-maxage=120` and contains a server island, and say which layer breaks if the island’s props exceed the URL limit.

26. Why shouldn’t you rate-limit on `X-Forwarded-For` read from `Astro.request.headers`?

27. Design: you must serve a mostly static marketing site plus a logged-in dashboard on Cloudflare. Choose `output`, `prerender` settings, adapter options and session approach, and note two platform-specific pitfalls.

28. Design: a team deploys to three Kubernetes pods with rolling updates and a CDN in front of HTML. Outline the configuration needed so server islands and actions keep working during a deploy.
