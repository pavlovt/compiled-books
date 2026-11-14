# Chapter 10: Middleware and Endpoints

Pages render HTML. Everything else on the server side of an Astro app, from authentication and request tagging to JSON APIs, webhooks, RSS feeds and generated images, is handled by two features that share one context object: **middleware**, which intercepts every page and endpoint render, and **endpoints**, which are `.ts`/`.js` files in `src/pages` that export HTTP method handlers.

This chapter covers `onRequest`, `defineMiddleware`, `sequence()` and `locals`; the two kinds of rewrite (`next(payload)` versus `context.rewrite()`) and their different semantics; typing `App.Locals`; endpoint methods, `ALL`, `HEAD`, the `APIRoute` type, static versus on-demand endpoints; the low-level `createContext()` and `trySerializeLocals()` helpers; and the caveats of edge middleware mode. Behaviour not pinned down by the docs was verified against `astro@7.4.1` with `@astrojs/node@11.1.9`.

## Middleware basics

Create `src/middleware.ts` (or `src/middleware/index.ts`) and export a named `onRequest`. It must not be a default export.

```ts
// src/middleware.ts
import { defineMiddleware } from 'astro:middleware';

export const onRequest = defineMiddleware(async (context, next) => {
  const started = performance.now();
  context.locals.requestId = crypto.randomUUID();

  const response = await next();

  response.headers.set('x-request-id', context.locals.requestId);
  response.headers.set('server-timing', `app;dur=${(performance.now() - started).toFixed(1)}`);
  return response;
});
```

`onRequest(context, next)` receives an `APIContext` (the same shape as an endpoint’s context: `request`, `url`, `params`, `cookies`, `locals`, `redirect`, `rewrite`, `clientAddress`, `isPrerendered`, `routePattern`, `session`, `cache`, `logger`, …) and `next`. It must return a `Response`, either directly or from `next()`; returning nothing is allowed by the type for handlers that only mutate state, but a handler that neither calls `next()` nor returns a `Response` produces no page.

### When middleware runs

- **On-demand routes:** on every request, before the page or endpoint.
- **Prerendered routes:** **at build time**, once per page, with no real request. `context.isPrerendered` is `true`, `clientAddress` throws, and there are no useful request headers. Whatever you attach to the response is baked into the static file.
- **Error pages:** middleware attempts to run for 404s (even when no route matched, adapter permitting) and before a 500 page, unless the error happened inside middleware itself, in which case `Astro.locals` is not available to the 500 page.
- **Server island requests, actions, image endpoint:** these are requests too and pass through middleware. Chapter 9 explains why pathname-based gates matter here.

I verified the dual behaviour with a middleware that wrote `ctx.isPrerendered` into a response header and into locals: the prerendered page contained `pre=true` and locals set at build time in its HTML; the on-demand responses had `x-a: ...:false`. A prerendered page served from `dist/client` did not run middleware again at request time (the default `middlewareMode: 'classic'`).

> **Warning:** Incremental builds (Chapter 6) do not invalidate cached pages when middleware changes. If your middleware changes prerendered HTML, run `astro build --force` after editing it.

## `locals`

`context.locals` (`Astro.locals` in components) is a per-request object for passing data from middleware to pages and endpoints. It “lives and dies” within one route render. Properties:

- It can hold anything: strings, functions, `Map`s, class instances. Nothing is serialized (except in edge mode, below).
- You can mutate it but **not replace it**. Assigning `context.locals = {}` throws `LocalsReassigned: locals cannot be assigned directly.` (verified: the request returned 500). Add properties instead.
- Integrations and adapters also write to `locals` (Cloudflare’s `cfContext`, Netlify’s `netlify`, Vercel’s `vercel` in edge mode); do not overwrite their keys.
- Information that must survive across requests belongs in a cookie, session (Chapter 12), database or cache.

### Typing `App.Locals`

Declare the shape in `src/env.d.ts` (a global ambient file) so `Astro.locals` and `context.locals` are typed everywhere:

```ts
// src/env.d.ts
/// <reference types="astro/client" />

type User = { id: string; name: string; role: 'admin' | 'member' };

declare namespace App {
  interface Locals {
    requestId: string;
    user: User | null;
    t: (key: string) => string;
  }
}
```

Mark values that middleware sets conditionally as optional or nullable, because the type system cannot see which routes ran which middleware. For adapter-provided locals, extend the adapter type: `interface Locals extends NetlifyLocals { ... }` or `EdgeLocals` for Vercel.

### Gotcha: shared mutable state versus `locals`

Module-level variables in `middleware.ts` live for the whole server process (and are shared across concurrent requests on Node), exactly like the SSR cross-request hazard for rune modules (Chapter 4). Put request data in `locals`, never in module variables.

## `defineMiddleware` and `sequence`

`defineMiddleware(fn)` is an identity function that types `context` and `next` (the JSDoc equivalent is `/** @type {import('astro').MiddlewareHandler} */`). `sequence(...handlers)` composes handlers left to right on the way in and right to left on the way out:

```ts
// src/middleware.ts
import { defineMiddleware, sequence } from 'astro:middleware';

const logging = defineMiddleware(async (ctx, next) => {
  ctx.logger.info(`> ${ctx.request.method} ${ctx.url.pathname}`);
  const res = await next();
  ctx.logger.info(`< ${res.status}`);
  return res;
});

const auth = defineMiddleware(async (ctx, next) => {
  if (ctx.isPrerendered) return next(); // nothing to authenticate at build time
  const sid = ctx.cookies.get('sid')?.value;
  ctx.locals.user = sid ? await loadUser(sid) : null;
  if (ctx.url.pathname.startsWith('/admin') && ctx.locals.user?.role !== 'admin') {
    return ctx.redirect('/login', 302);
  }
  return next();
});

const security = defineMiddleware(async (_ctx, next) => {
  const res = await next();
  res.headers.set('x-content-type-options', 'nosniff');
  res.headers.set('referrer-policy', 'strict-origin-when-cross-origin');
  return res;
});

export const onRequest = sequence(logging, auth, security);
```

Order of output for `sequence(validation, auth, greeting)` is: `validation request`, `auth request`, `greeting request`, then the page, `greeting response`, `auth response`, `validation response`. A handler that returns a `Response` without calling `next()` short-circuits everything after it.

I verified ordering and shared `locals` with two handlers: handler A set `locals.t = ['a']` and, after `await next()`, read the array B had appended to (`ab`) when setting a response header.

### Modifying the response

`next()` returns the page’s `Response`. You can set headers on it directly (above). To change the body you must read it and build a new `Response`:

```ts
export const onRequest = defineMiddleware(async (_ctx, next) => {
  const res = await next();
  const html = await res.text();
  return new Response(html.replaceAll('PRIVATE INFO', 'REDACTED'), {
    status: res.status,
    headers: res.headers,
  });
});
```

Reading the body of a streamed response with `res.text()` **buffers the whole page**, which defeats streaming (Chapter 8). Restrict such transforms to routes that need them or use a `TransformStream`.

## Rewrites in middleware: two different mechanisms

Astro offers two ways to serve a different route’s content without redirecting the browser. Their semantics differ and the difference matters.

|  | `return next(payload)` | `return context.rewrite(payload)` |
|------------------------|------------------------|------------------------|
| Since | 4.13 | 4.13 |
| Re-runs middleware | **No**: rewrites the current request in place | **Yes**: starts a new render phase, middleware executes again |
| What later handlers see | In a `sequence`, the next handler receives the updated context (new `url`) | The whole chain restarts for the new route |
| Request body | New `Request` is created from the old one; **body consumption before or after throws** | Same caveat; prefer `Astro.rewrite()` from templates for form posts |
| Typical use | Cheap path rewrite, A/B routing | Gate to a login page; maps to a full re-render |

`payload` may be a string path, a `URL` or a `Request`.

```ts
const rewrites = defineMiddleware(async (ctx, next) => {
  if (ctx.url.pathname === '/old') return next('/who');            // in place, once
  if (ctx.url.pathname === '/old2') return ctx.rewrite('/who');    // full re-render
  return next();
});
```

I verified the difference with a counter in `locals` incremented by the first middleware: a request that used `next('/who')` finished with the counter at `1`, while a request that used `ctx.rewrite('/who')` finished at `2`, because the middleware chain ran again. Both rendered the `/who` page with `Astro.url.pathname === '/who'` and `Astro.originPathname` equal to the original path with a trailing slash (`/old/` and `/old2/`), so layouts can still know where the visitor came from. `locals` set before the rewrite remained visible after it.

Choose by cost and by whether the target route’s own middleware logic should apply. With `context.rewrite()` you must avoid loops: the rewritten request passes through the same middleware, so guard on the path or on a header you set (`x-redirect-to` in the docs’ login example).

> **Warning:** Do not rewrite requests that carry a body with `next(Request)`. “Calling `next()` with this signature will create a new `Request` object using the old `ctx.request`”, so reading `request.body` either before or after throws. This most often bites Astro Actions submitted from HTML forms; handle those rewrites from templates with `Astro.rewrite()`.

### Redirects, rewrites and `Response` returns compared

| Need | Do |
|------------------------------------|------------------------------------|
| Send browser to another URL | `return context.redirect('/login', 302)` |
| Show another route’s content at the current URL | `next('/path')` or `context.rewrite('/path')` |
| Stop with an error | `return new Response('Forbidden', { status: 403 })` |
| Continue | `return next()` |

## Authorization: where middleware is not enough

Middleware is the natural place for authentication (who is this?), but be careful with authorization by pathname:

- Prerendered pages are not protected by middleware at runtime in `classic` mode: they are static files served by your host. Anything private must be on demand.
- Pathname checks can be bypassed by routes you did not anticipate: server island endpoints (`/_server-islands/*`), actions (`/_actions/*`), the image endpoint, rewrites to protected routes (`next('/admin')` from another middleware), and encoded or differently normalised paths (`Astro.url.pathname` may be partially decoded versus `new URL(request.url).pathname`, Chapter 5). Prefer checking at the **handler** (page frontmatter, endpoint, action) with a shared helper such as `requireUser(context)`, and use middleware to *populate* `locals.user`.
- A rewrite does not bypass a later middleware in the `context.rewrite()` case, but `next(payload)` does not re-run earlier handlers, so order your auth before any rewriting handler.

```ts
// src/lib/guard.ts
import type { APIContext } from 'astro';

// Returns the user, or a Response the caller must return.
export function requireUser(ctx: Pick<APIContext, 'locals' | 'redirect'>) {
  return ctx.locals.user ?? ctx.redirect('/login');
}
```

In a page: `const user = requireUser(Astro); if (user instanceof Response) return user;`. Return the response; throwing a `Response` is not a supported Astro pattern.

## Error handling middleware

Wrap `next()` to convert exceptions into responses and to report them:

```ts
const errors = defineMiddleware(async (ctx, next) => {
  try {
    return await next();
  } catch (error) {
    ctx.logger.error(`unhandled error on ${ctx.url.pathname}: ${String(error)}`);
    return new Response('Something went wrong', { status: 500 });
  }
});
```

Note that errors thrown while HTML is already streaming cannot change the status line. Prefer to fetch and validate in frontmatter, before output begins.

## Endpoints

An endpoint is a `.js`/`.ts` file under `src/pages` that exports functions named after HTTP methods. The file name decides the URL, with the last extension removed: `src/pages/data.json.ts` becomes `/data.json`. Endpoints with a file extension in the URL are served **without** a trailing slash regardless of configuration (6.0).

### Static endpoints (build time)

By default, in `output: 'static'`, an endpoint is called once at build and its response body becomes a file:

```ts
// src/pages/builtwith.json.ts
import type { APIRoute } from 'astro';

export const GET = (() =>
  new Response(JSON.stringify({ name: 'Astro', url: 'https://astro.build/' }), {
    headers: { 'content-type': 'application/json' },
  })) satisfies APIRoute;
```

Only `GET` (and `HEAD`) make sense here; in a prerendered endpoint other methods log a warning that they are unavailable. In static mode, `request` only gives you `request.url`. Dynamic params work with `getStaticPaths()` and can pass props:

```ts
// src/pages/api/products/[sku].json.ts
import type { APIRoute, GetStaticPaths } from 'astro';
import { getCollection } from 'astro:content';

export const getStaticPaths = (async () => {
  const products = await getCollection('products');
  return products.map((p) => ({ params: { sku: p.id }, props: { name: p.data.name, price: p.data.price } }));
}) satisfies GetStaticPaths;

export const GET: APIRoute<{ name: string; price: number }> = ({ props, params }) =>
  Response.json({ sku: params.sku, ...props });
```

In the verified test project a static endpoint `src/pages/api/static.json.ts` was emitted to `dist/client/api/static.json` at build.

### On-demand endpoints (API routes)

Set `export const prerender = false` (not needed with `output: 'server'`). Handlers receive the full request:

```ts
// src/pages/api/cart.ts
import type { APIRoute } from 'astro';
import { z } from 'astro/zod';

export const prerender = false;

const Body = z.object({ productId: z.string(), qty: z.number().int().min(1).max(10) });

export const POST: APIRoute = async ({ request, locals, cookies }) => {
  if (request.headers.get('content-type')?.split(';')[0] !== 'application/json') {
    return Response.json({ error: 'expected json' }, { status: 415 });
  }
  const parsed = Body.safeParse(await request.json().catch(() => null));
  if (!parsed.success) {
    return Response.json({ error: z.flattenError(parsed.error) }, { status: 400 });
  }
  const cartId = cookies.get('cart')?.value ?? crypto.randomUUID();
  cookies.set('cart', cartId, { path: '/', httpOnly: true, sameSite: 'lax', secure: true });
  await addToCart(cartId, parsed.data);
  return Response.json({ ok: true }, { status: 201 });
};
```

I verified in the Node adapter that `context.cookies.set()` in an endpoint produced a `Set-Cookie` header on the returned `Response` without any manual copying, that `request.text()` read a `POST` body, and that `clientAddress` and `isPrerendered` were available on the context.

### Methods, `ALL` and `HEAD`

Export a function per method (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`, `HEAD`) and optionally `ALL` as a catch-all. Resolution, read from the runtime in 7.4.1 and confirmed by test:

1.  The exact method export, if present.
2.  Otherwise `ALL`.
3.  Otherwise, for `HEAD` only, the `GET` handler (the body is then stripped: `new Response(null, response)`).
4.  Otherwise a `404`, logged as `No API Route handler exists for the method "X"`.

Consequences:

- A route with `GET` and **no** `HEAD` or `ALL` handles `HEAD` automatically. (Verified: `curl -I` on a `GET`-only route returned 200 headers with no body.)
- A route with `ALL` and `GET` but no `HEAD`: `HEAD` goes to **`ALL`** because step 2 precedes step 3. That is surprising if `ALL` returns different headers. Define `HEAD` explicitly if you care.
- `PATCH` against a route with only `ALL` returned the `ALL` handler’s output (verified: `ALL PATCH`).
- Export names are case sensitive. Exporting `all` triggers a hint in the log that you probably meant `ALL`; exporting a non-function logs an error and returns 500.
- A handler must return a `Response`; anything else throws `EndpointDidNotReturnAResponse`.
- Responses with 404 or 500 returned from an endpoint are **not** rerouted to `404.astro`/`500.astro`: endpoints that explicitly return those statuses keep their own body.

```ts
// src/pages/api/items/[id].ts
import type { APIRoute } from 'astro';
export const prerender = false;

export const GET: APIRoute = async ({ params }) => {
  const item = await db.items.find(params.id!);
  return item ? Response.json(item) : new Response(null, { status: 404, statusText: 'Not found' });
};

export const PUT: APIRoute = async ({ params, request }) => { /* ... */ return new Response(null, { status: 204 }); };
export const DELETE: APIRoute = async ({ params }) => new Response(null, { status: 204 });

// anything else, including OPTIONS preflight, gets a 405 with an Allow header
export const ALL: APIRoute = () =>
  new Response(null, { status: 405, headers: { allow: 'GET, PUT, DELETE' } });
```

### Typing endpoints: `APIRoute` and `APIContext`

`APIRoute<Props, Params>` types the handler (`export const GET: APIRoute = (ctx) => ...` or `satisfies APIRoute`). `APIContext` is the context type for helpers. Endpoint context members mirror `Astro`: `params`, `props` (static only), `request`, `url`, `site`, `locals`, `cookies`, `redirect()`, `rewrite()`, `clientAddress`, `isPrerendered`, `routePattern`, `session`, `cache`, `logger`, `generator`, `preferredLocale` and friends. In `redirect()` the endpoint form is `return redirect('/to', 307)`.

### Content negotiation and binary responses

Binary and non-JSON responses need explicit `Content-Type` in SSR on some hosts:

```ts
// src/pages/og/[slug].png.ts
export const prerender = false;
export const GET: APIRoute = async ({ params }) => {
  const png = await renderOgImage(params.slug!);
  return new Response(png, { headers: { 'content-type': 'image/png', 'cache-control': 'public, max-age=86400' } });
};
```

### Endpoints that call each other

To call your own on-demand endpoint from page frontmatter use an absolute URL derived from the request, `new URL('/api/x', Astro.url)`, but prefer extracting the logic into a shared function. An internal HTTP hop costs a request and bypasses types.

## Endpoints versus actions versus middleware

| Need | Tool |
|------------------------------------|------------------------------------|
| Typed RPC from islands and forms with validation and progressive enhancement | Actions (Chapter 11) |
| A public, stable HTTP API (webhooks, third-party callers, non-JS clients, REST) | Endpoint |
| Generated files (RSS, sitemap, JSON feeds, images) at build | Static endpoint |
| Cross-cutting concerns for many routes (headers, auth population, logging) | Middleware |
| A response specific to one route | Page frontmatter or endpoint |

For a Svelte island posting data, an endpoint is fine for simple cases but you lose input validation plumbing, serialization of rich types and the origin check that actions include. Note that `security.checkOrigin` (default `true`) rejects cross-origin form-style POSTs (such as `application/x-www-form-urlencoded`) to on-demand routes, but a JSON API consumed from other origins needs explicit CORS handling and its own CSRF thinking (Chapter 16).

### CORS example

```ts
// src/pages/api/public/prices.ts
export const prerender = false;

const cors = {
  'access-control-allow-origin': 'https://partner.example.com',
  'access-control-allow-methods': 'GET, OPTIONS',
  'access-control-allow-headers': 'content-type',
  vary: 'origin',
};

export const OPTIONS: APIRoute = () => new Response(null, { status: 204, headers: cors });
export const GET: APIRoute = async () =>
  Response.json(await loadPrices(), { headers: { ...cors, 'cache-control': 'public, max-age=60' } });
```

## Low-level helpers: `createContext` and `trySerializeLocals`

`astro/middleware` (a regular module, not the virtual one) exports helpers meant for integrations, adapters and tests:

```ts
import { createContext, trySerializeLocals, sequence } from 'astro/middleware';
```

**`createContext({ request, params?, userDefinedLocales?, defaultLocale, locals, clientAddress? })`** builds an `APIContext` you can pass to a middleware function, so you can unit-test middleware without a server. I verified:

```ts
const ctx = createContext({
  request: new Request('http://x.test/a?b=1'),
  defaultLocale: 'en',
  locals: {},
  clientAddress: '1.2.3.4',
});
const handler = sequence(authMiddleware, tagMiddleware);
const res = await handler(ctx, async () => new Response('ok'));
// ctx.url.pathname === '/a'; ctx.locals reflects mutations; res.headers set by middleware
```

`clientAddress` must come from a trusted source (socket address or platform header). If you omit it, reading `ctx.clientAddress` throws. The `next` you pass is your own function standing in for the page.

**`trySerializeLocals(value)`** returns `JSON.stringify(value)` if the value is serializable and throws `The passed value can't be serialized.` otherwise. The check accepts plain objects, arrays, strings, numbers, booleans and `null`, and rejects functions, `Map`, `Set`, `Date`, class instances and similar. I verified that a plain object with a `Date` throws. This is what adapters use in **edge** middleware mode, where `locals` crosses a process boundary as JSON.

## Edge middleware mode

By default (`adapterFeatures.middlewareMode: 'classic'`) middleware is part of the server bundle: prerendered pages get it at build time only, and on-demand pages get it per request. Adapters may offer `middlewareMode: 'edge'`, which deploys the middleware **independently**, as an edge function in front of your pages. Vercel and Netlify expose it as the `middlewareMode: 'edge'` adapter option.

What changes:

|  | Classic | Edge |
|------------------------|------------------------|------------------------|
| Runs for prerendered pages at runtime | No (only at build) | Netlify: yes, all requests including static assets. Vercel: on-demand routes, including ISR cache hits; static assets and prerendered pages are not invoked |
| Runs on ISR cache hits (Vercel) | No (bundled in the function) | Yes |
| `locals` to the renderer | In-process object | **Serialized as JSON** into a header for the serverless function |
| Direct calls to the function | Normal | Rejected with 403 unless they come from the generated edge function |
| Runtime | Your server’s | Edge runtime with restricted APIs |

Caveats:

1.  **`locals` must be JSON-serializable.** Functions, `Map`s, `Date`s and class instances will fail (`trySerializeLocals` throws). Do not put a `t()` translation function or a DB handle in `locals` if you plan to use edge mode; put plain data and rebuild helpers in the page.
2.  **Edge runtime limits.** Node built-ins and many npm packages are unavailable, bundle size is limited, and there is no filesystem. Sessions are **not supported** in edge middleware, so `context.session` cannot be used there.
3.  **Adapter-provided locals.** Vercel edge exposes `ctx.locals.vercel.edge` (type via `EdgeLocals`); Netlify exposes `Astro.locals.netlify.context` (type `NetlifyLocals`), not on prerendered pages.
4.  **Cost.** Each request to a covered route invokes an edge function; on Vercel every cache hit on an ISR route does too.
5.  **Build-time and runtime double execution.** In edge mode you are responsible for deciding what runs at build (for prerendered pages middleware still runs at build) and what runs at the edge; keep handlers idempotent and guard on `isPrerendered`.
6.  **Incremental builds** ignore middleware changes (above).

Use edge mode when you need redirects, A/B rewrites, geo or access control on *static* content, or when middleware must run in front of an ISR cache. Otherwise stay on classic.

## Advanced routing and middleware

Since Astro 7, `src/fetch.ts` can replace the built-in pipeline (Chapter 5). User middleware then becomes one stage (`middleware()` from `astro/fetch`, or `astro/hono`’s equivalent) in a pipeline you control, with trailing slash, redirects, sessions, actions, pages, i18n and caching around it. Everything in this chapter still applies to the `onRequest` you export; with advanced routing you decide where in the pipeline it runs, and the warning stands: do not authorize by matching `url.pathname` in pre-processing, use a router or the handler itself.

## A complete example: auth, locale, security headers and an API

```ts
// src/middleware.ts
import { defineMiddleware, sequence } from 'astro:middleware';

const requestId = defineMiddleware(async (ctx, next) => {
  ctx.locals.requestId = ctx.request.headers.get('x-request-id') ?? crypto.randomUUID();
  const res = await next();
  res.headers.set('x-request-id', ctx.locals.requestId);
  return res;
});

const user = defineMiddleware(async (ctx, next) => {
  ctx.locals.user = null;
  if (!ctx.isPrerendered) {
    const sid = ctx.cookies.get('sid')?.value;
    if (sid) ctx.locals.user = await findUserBySession(sid);
  }
  return next();
});

const headers = defineMiddleware(async (_ctx, next) => {
  const res = await next();
  if (!res.headers.has('cache-control') && res.headers.get('content-type')?.includes('text/html')) {
    res.headers.set('cache-control', 'private, no-cache');
  }
  res.headers.set('x-content-type-options', 'nosniff');
  return res;
});

export const onRequest = sequence(requestId, user, headers);
```

```ts
// src/pages/api/me.ts
import type { APIRoute } from 'astro';
export const prerender = false;

export const GET: APIRoute = ({ locals }) =>
  locals.user
    ? Response.json({ id: locals.user.id, name: locals.user.name })
    : Response.json({ error: 'unauthenticated' }, { status: 401 });
```

```html
<!-- src/components/Me.svelte: island that uses the endpoint -->
<script lang="ts">
  let me = $state<{ name: string } | null | undefined>(undefined);

  $effect(() => {
    let cancelled = false;
    fetch('/api/me').then(async (r) => {
      if (!cancelled) me = r.ok ? await r.json() : null;
    });
    return () => (cancelled = true);
  });
</script>

{#if me === undefined}
  <span aria-busy="true">...</span>
{:else if me}
  <span>Hi {me.name}</span>
{:else}
  <a href="/login">Sign in</a>
{/if}
```

And a unit test for the middleware using `createContext`:

```ts
// src/middleware.test.ts
import { describe, it, expect } from 'vitest';
import { createContext } from 'astro/middleware';
import { onRequest } from './middleware';

describe('middleware', () => {
  it('adds a request id header', async () => {
    const ctx = createContext({
      request: new Request('http://localhost/api/me'),
      defaultLocale: 'en',
      locals: {},
      clientAddress: '127.0.0.1',
    });
    const res = await onRequest(ctx, async () => new Response('ok'));
    expect(res.headers.get('x-request-id')).toBe(ctx.locals.requestId);
  });
});
```

## Key takeaways

- `src/middleware.ts` exports a named `onRequest(context, next)`; `defineMiddleware` types it and `sequence()` composes handlers (in on the way in, reverse on the way out). A handler returns a `Response`, directly or from `next()`.
- Middleware runs per request for on-demand routes and at **build time** for prerendered pages (`isPrerendered` is `true`, no real request). Prerendered files are not protected by middleware at runtime in classic mode.
- `locals` is per-request, mutable but not reassignable (`LocalsReassigned`). Type it with `App.Locals` in `src/env.d.ts`. Never store request data in module variables.
- `next(payload)` rewrites in place without re-running middleware (and breaks request-body consumption); `context.rewrite(payload)` restarts the pipeline, re-running middleware (verified: counter 1 versus 2). `originPathname` preserves the original path.
- Do not authorize by `url.pathname` alone: actions, server islands and rewrites bypass naive path gates. Populate `locals` in middleware and enforce in handlers.
- Endpoints export method handlers; resolution is exact method, then `ALL`, then `GET` for `HEAD` (so `ALL` shadows the `HEAD`-from-`GET` fallback), else 404. Handlers must return a `Response`. Static endpoints build files; extension URLs have no trailing slash.
- `createContext()` builds an `APIContext` for testing or integrations; `trySerializeLocals()` throws for non-JSON-safe values (functions, `Map`, `Set`, `Date`, class instances).
- Edge middleware mode serializes `locals` to JSON, runs in an edge runtime without sessions, and changes when middleware runs for static and cached content; stay on classic unless you need it.
- Use actions for typed form/RPC flows, endpoints for public HTTP APIs and generated files, middleware for cross-cutting concerns.

## Review Questions

1.  What is the required export from `src/middleware.ts`, and what two return forms satisfy it?

2.  Predict the console order for `sequence(a, b, c)` where each logs “x in” before `await next()` and “x out” after.

3.  A prerendered page’s middleware reads `ctx.request.headers.get('cookie')`. What does it see, and why is that a problem?

4.  Why does editing middleware not update pages when `experimental.incrementalBuild` is on?

5.  What happens when middleware does `ctx.locals = { user }`? Show the correct code.

6.  Give the `App.Locals` declaration for a `user` that may be null and a `requestId` string, and name the file it goes in.

7.  What is the difference between `next('/who')` and `context.rewrite('/who')` regarding middleware re-execution? What would a shared counter in `locals` show after each?

8.  Why is `next(new Request('/x'))` dangerous for a form submitted by an Astro Action?

9.  Find the bug:

    ```ts
    export const onRequest = defineMiddleware(async (ctx, next) => {
      if (ctx.url.pathname.startsWith('/account')) {
        if (!ctx.cookies.has('sid')) return ctx.redirect('/login');
      }
      return next();
    });
    ```

    in a project that also uses server islands and actions that return account data.

10. Why can `res.text()` in middleware hurt performance on a streamed page?

11. List the order in which Astro picks a handler for a `HEAD` request and say what happens if you export `GET` and `ALL`.

12. What does Astro return for `PATCH` on a route that exports only `GET` and `POST`?

13. Why is this endpoint wrong? `ts export const GET = () => ({ ok: true });`

14. Multiple choice: A static endpoint file `src/pages/feed.xml.ts` is requested as `/feed.xml/`. (a) works (b) 404 because extension endpoints have no trailing slash (c) redirects to `/feed.xml` always (d) depends on `build.format`.

15. In `output: 'static'`, which line makes `src/pages/api/cart.ts` handle a `POST` at runtime, and what is needed in the project?

16. How do you pass per-path props to a static endpoint, and why are props not available to on-demand endpoints?

17. A returned `new Response(null, { status: 404 })` from an endpoint: is it rerouted to `404.astro`? Why does it matter?

18. What does `createContext()` need to be given to be able to read `ctx.clientAddress`, and what happens otherwise?

19. Which of these locals values pass `trySerializeLocals`? (a) `{ id: 1 }` (b) `{ at: new Date() }` (c) `{ fn() {} }` (d) `new Map()` (e) `[1, 'a', null]`.

20. In Vercel edge middleware mode, how does `locals` reach the rendering function and what stops someone calling that function directly?

21. Name three restrictions or costs of edge middleware mode.

22. Why does a Vercel ISR route run middleware only on cache misses by default, and how do you change that?

23. Explain why middleware cannot protect a prerendered `/admin` page in classic mode and what you should do.

24. Write a middleware unit test outline using `createContext` for a handler that sets `x-request-id`.

25. Design: you need an authenticated JSON API used by a Svelte island and by a partner’s server. Choose endpoint versus action, describe CSRF/CORS handling and where authentication is populated versus enforced.

26. Design: you want a global `Content-Security-Policy`-like header and request-id logging for all pages without breaking streaming. Describe the middleware and what to avoid.
