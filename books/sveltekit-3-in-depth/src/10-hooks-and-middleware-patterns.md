# Chapter 9: Hooks and Middleware Patterns

Hooks are the seams SvelteKit leaves in its request pipeline for your code: functions with fixed names, exported from three optional files, that the framework calls at defined moments. `handle` is the closest thing the framework has to middleware; `handleFetch` intercepts server-side `fetch`; `handleError` (Chapter 10) shapes errors; `init`, `reroute` and `transport` cover start-up, URL-to-route mapping and custom serialisation. This chapter covers each hook precisely, including the `resolve` options and `sequence` semantics that most people use only superficially, how to design `event.locals`, what the SvelteKit 3 type changes mean, and how to build common cross-cutting concerns (request IDs, CORS, rate limiting, locale, headers, maintenance mode) on top of them. The last section is just as important as the first: hooks do not intercept everything, and several security mistakes come from assuming they do.

## 9.1 The three hook files

| File | Runs on | Hooks |
|------------------------|------------------------|------------------------|
| `src/hooks.server.ts` | server only | `handle`, `handleFetch`, `handleError`, `init` |
| `src/hooks.client.ts` | browser only | `handleError`, `init` |
| `src/hooks.ts` | both | `reroute`, `transport` |

All three are optional. The server file is imported when the server instance is created, so top-level code runs once at start-up (and again for each instance on platforms that create many, such as serverless functions). The locations can be changed with the deprecated `files.hooks.*` options, but there is rarely a reason to.

In SvelteKit 3, the **types** for all hooks come from `@sveltejs/kit/hooks`, not `@sveltejs/kit`:

```ts
import type {
    Handle, HandleFetch, HandleServerError, HandleClientError,
    ServerInit, ClientInit, Reroute, Transport, ResolveOptions, CaughtError
} from '@sveltejs/kit/hooks';
import { sequence } from '@sveltejs/kit/hooks';
```

`sequence` is the only runtime export of that module. (`defineEnvVars` used to be exported there; it moved to `@sveltejs/kit/env` and the old export is a stub that throws.) The codemod `npx sv migrate sveltekit-3` rewrites the type imports.

## 9.2 `handle`

`handle` runs for every request that reaches the SvelteKit server, during runtime and during prerendering. Its signature is:

```ts
type Handle = (input: {
    event: RequestEvent;
    resolve: (event: RequestEvent, opts?: ResolveOptions) => Promise<Response>;
}) => MaybePromise<Response>;
```

The default is `({ event, resolve }) => resolve(event)`. In 3.0 `resolve` is typed to always return `Promise<Response>` (previously `MaybePromise<Response>`), so `await` it without type gymnastics.

### Where `handle` sits in the pipeline

Reading the request handler in the server runtime gives the exact order, which Chapter 2 describes in full:

1.  The URL is classified: route-resolution request, data request (`__data.json`), remote function call, or ordinary request. Remote calls from forms and commands have their URL rewritten from the `x-sveltekit-pathname`/`x-sveltekit-search` headers; queries do not, so `event.url` is the endpoint URL and `event.route.id` is `null`.
2.  **In production**, the CSRF origin check runs (remote calls: same-origin required; everything else: the form-content-type check against `csrf.trustedOrigins`). This is *before* `handle`, so `handle` cannot see requests that CSRF rejected and cannot disable the check. The check is skipped in `vite dev`.
3.  Reserved query parameters starting with `x-sveltekit-` are rejected with 400.
4.  The `event` object is built: cookies, `fetch`, `locals` (an empty object), `params`, `platform`, `route`, `setHeaders`, `url` and the flags `isDataRequest`, `isSubRequest`, `isRemoteRequest`.
5.  The universal `reroute` hook runs (not for remote calls).
6.  The route is matched; `event.route` and `event.params` are filled in.
7.  Trailing-slash normalisation may answer with a 308 before `handle` is reached.
8.  **`handle` runs**, wrapped in a `sveltekit.handle.root` tracing span. `resolve(event)` then does the actual work: remote function dispatch, data requests, `+server` endpoints, or page rendering (including actions, Chapter 6).

Consequences:

- **Static assets and prerendered pages never reach `handle`.** They are served by the adapter or platform (adapter-node serves them from its own static handler; Vercel and Cloudflare serve them from their CDN). That includes anything in `static/`, built assets under `/_app/immutable`, and prerendered HTML. A maintenance-mode or auth hook will not affect them.
- Route-resolution requests (used with `router.resolution: 'server'`) and `/_app/env.js` are answered before `handle` too.
- Data requests, actions, `+server` endpoints and remote calls do pass through `handle`; use `event.isDataRequest`, `event.isRemoteRequest` and `event.route.id` to distinguish them.
- Internal sub-requests made with `event.fetch` to your own routes run the whole pipeline again, including `handle` (`event.isSubRequest` is true). A page that `fetch`es three internal endpoints during SSR triggers `handle` four times. Keep `handle` cheap, or skip work for sub-requests when it is redundant (but never skip authorisation on that basis alone: sub-requests inherit the caller’s `cookie` and `authorization` headers, and that is the point).

### Responsibilities

A `handle` function typically does one or more of:

```ts
// src/hooks.server.ts
import type { Handle } from '@sveltejs/kit/hooks';

export const handle: Handle = async ({ event, resolve }) => {
    // 1. before: inspect or short-circuit
    if (event.url.pathname === '/healthz') return new Response('ok');

    // 2. derive request-scoped context
    event.locals.requestId = event.request.headers.get('x-request-id') ?? crypto.randomUUID();

    // 3. delegate
    const response = await resolve(event);

    // 4. after: decorate the response
    response.headers.set('x-request-id', event.locals.requestId);
    return response;
};
```

Details that bite:

- **`resolve` never throws.** Errors during rendering or in endpoints are converted to a `Response` (an error page or a JSON error), after passing through `handleError`. Do not wrap `resolve` in `try/catch` expecting to see them; inspect `response.status` instead.
- **`handle` itself may throw.** An error thrown directly from `handle` is *fatal*: it goes through `handleError`, then SvelteKit answers with a JSON body or the static `src/error.html` depending on the `Accept` header. `+error.svelte` is not used for errors in `handle` or in `+server` handlers, because there is no layout to render it inside. A thrown `redirect(...)` from `handle` works and produces a redirect response (JSON for data and remote requests).
- **Response headers may be immutable.** A `Response` from `Response.redirect()` or a `fetch` result has frozen headers; `response.headers.set` then throws a `TypeError`. When decorating arbitrary responses, clone first: `new Response(response.body, response)`.
- **Mutate `event` freely, but pass the same object to `resolve`.** `resolve(event)` can take a modified event (for example with a different `locals`), and it must be an `event` derived from the one you received.
- **Cookies set on `event.cookies` before or after `resolve` are applied to the final response.** After `resolve` completes the event is sealed: `cookies.set` and `setHeaders` throw (`cookies_set_after_response`, `set_headers_after_response`). Mutate `response.headers` instead, and use `response.headers.append('set-cookie', ...)` only if you manage the serialisation yourself.
- **`event.setHeaders` can set a header once**; setting it twice raises `header_already_set` (except `server-timing`, which is appended).

### `resolve` options

The second argument controls HTML rendering. All options are optional.

```ts
export const handle: Handle = async ({ event, resolve }) =>
    resolve(event, {
        transformPageChunk: ({ html, done }) => html,
        filterSerializedResponseHeaders: (name, value) => false,
        preload: ({ type, path }) => true
    });
```

**`transformPageChunk({ html, done })`** rewrites the HTML stream. Chunks arrive at “sensible boundaries” such as the head placeholder and component boundaries, **not** necessarily at element boundaries: a chunk may contain an opening tag but not its closing tag, and a string you want to replace can straddle two chunks. Therefore:

- Use it for replacements of *placeholders you own*, which sit in one chunk by construction: `app.html` is the place to put `%lang%` or `%theme%`, and `transformPageChunk` the place to fill them.
- Never rewrite arbitrary content with a regex (you will miss matches, or mangle a tag split across chunks).
- `done` is `true` for the last chunk. Return `undefined` to emit an empty string for that chunk.
- In 3.1 the implementation actually calls it once, with the whole document and `done: true` (Chapter 2). Write transforms that are correct either way, so they keep working when chunked flushing arrives.

```html
<!-- src/app.html -->
<html lang="%lang%" data-theme="%theme%">
```

```ts
export const handle: Handle = async ({ event, resolve }) => {
    const { locale, theme } = event.locals;
    return resolve(event, {
        transformPageChunk: ({ html }) => html.replace('%lang%', locale).replace('%theme%', theme)
    });
};
```

Because `app.html` is a single template, the placeholders are emitted in the first chunk (the shell), so a plain `replace` works there. Escape anything user-derived, and prefer a closed set (`'en' | 'de' | 'fr'`) for these values.

**`filterSerializedResponseHeaders(name, value)`**. When a `load` function calls `event.fetch`, the response is inlined into the HTML so the browser’s hydration can reuse it without refetching. By default **no response headers** are included in that serialisation. If your client-side code reads `response.headers.get('content-type')` or a pagination header from a SSR-inlined response, allow it:

```ts
resolve(event, {
    filterSerializedResponseHeaders: (name) => name === 'content-type' || name.startsWith('x-total-')
});
```

Header values are copied into the HTML, so never allow `set-cookie` or anything sensitive.

**`preload({ type, path, filename? })`** decides which build-time assets get `<link rel="modulepreload">`/`preload` tags (or a `Link` header if `output.linkHeaderPreload` is enabled). `type` is `'js'`, `'css'`, `'asset'`, or `'font'` (fonts carry `filename`, the source path relative to the project root, because the hashed `path` is hard to match). The default preloads `js` and `css`, no assets. It is **not called in dev**, since it depends on build output. Typical use is to preload only the fonts you need for first paint:

```ts
resolve(event, {
    preload: ({ type, filename }) =>
        type === 'js' || type === 'css' || (type === 'font' && filename?.includes('inter-var'))
});
```

Over-preloading hurts as much as it helps: every preloaded file competes with the critical path (Chapter 16).

## 9.3 `sequence`

Real apps have several concerns; `sequence(...handles)` composes them like middleware, each calling `resolve` to invoke the next:

```ts
// src/hooks.server.ts
import { sequence } from '@sveltejs/kit/hooks';
import type { Handle } from '@sveltejs/kit/hooks';

const requestId: Handle = async ({ event, resolve }) => { /* ... */ return resolve(event); };
const maintenance: Handle = async ({ event, resolve }) => { /* ... */ return resolve(event); };
const session: Handle = async ({ event, resolve }) => { /* ... */ return resolve(event); };
const locale: Handle = async ({ event, resolve }) => { /* ... */ return resolve(event); };

export const handle = sequence(requestId, maintenance, session, locale);
```

Execution is the onion model. Pre-processing (code before `await resolve`) runs in order `requestId → maintenance → session → locale`; post-processing runs in reverse. Calling `resolve` in handler *n* invokes handler *n+1*; in the last one it invokes SvelteKit itself. Not calling it short-circuits everything after: put cheap rejecting handlers (maintenance, rate limiting, auth checks) before expensive ones.

The merge rules for `resolve` options, from the implementation, are exact and often misremembered:

| Option | Rule |
|------------------------------------|------------------------------------|
| `transformPageChunk` | applied in **reverse** order and **merged**: the innermost handler’s transform runs first on each chunk, then the next one out, up to the first handler |
| `preload` | **first defined wins**: the outermost handler that supplies it decides; later ones are never called |
| `filterSerializedResponseHeaders` | **first defined wins**, same rule |

The documented trace for `sequence(first, second)` where both set `transformPageChunk` and `preload`, and `second` sets `filterSerializedResponseHeaders`, is:

    first pre-processing
    first preload            <- (evaluated while building options; the outermost preload wins)
    second pre-processing
    second filterSerializedResponseHeaders
    second transform
    first transform
    second post-processing
    first post-processing

So if two handlers each define `preload`, only the first one’s function is ever consulted, which makes a handler that wants to *add* to the preload policy silently ineffective when an earlier one defines it. If you need composed policy, define it in exactly one handler and have the others write to `event.locals`.

Practical guidance:

- **Pass data between handlers through `event.locals`**, not module state.
- **Name your handlers**: `sequence` names its tracing spans `sveltekit.handle.sequenced.<function name>` (or the index for anonymous ones), which turns a flat trace into a readable timeline (Chapter 17).
- Build conditional pipelines by composition rather than `if` inside every handler:

```ts
const only = (match: (e: RequestEvent) => boolean, h: Handle): Handle => (input) =>
    match(input.event) ? h(input) : input.resolve(input.event);

export const handle = sequence(
    requestId,
    only((e) => e.url.pathname.startsWith('/api/'), cors),
    only((e) => !e.isRemoteRequest, locale),
    session
);
```

- Keep `sequence` at module top level (it is called once, building the chain), not inside `handle`.

## 9.4 `event.locals`

`locals` is a plain object created empty for each request, passed to `+server` handlers, actions, server `load` functions (and universal loads’ server counterparts), `handle`, `handleError` and remote functions (via `getRequestEvent()`). It never leaves the server: it is not serialised, and the client cannot see it unless you return something derived from it in `load` data.

Type it in `src/app.d.ts`:

```ts
// src/app.d.ts
declare global {
    namespace App {
        interface Locals {
            requestId: string;
            locale: 'en' | 'de' | 'bg';
            user: { id: string; role: 'user' | 'admin' } | null;
        }
        interface Error {
            errorId: string;
        }
    }
}
export {};
```

Design rules that survive real codebases:

1.  **Always assign every property.** `Locals` types are not optional by default; if a handler might not run for some path (because you scoped it with `only`), declare the property optional or ensure a default. A missing assignment is a runtime `undefined` the compiler will not catch.
2.  **Locals are per request; closures over `event` are fine, module variables are not.** Never write to module-level variables from `handle` (Chapter 12’s “avoid shared state on the server”).
3.  **Store identity and capabilities, not data.** `locals.user` (an id and role) is a good fit; the user’s full order history is not. Fetch data in `load` or queries, where it is cached and typed per use.
4.  **Make expensive derivations lazy.** `handle` runs for every dynamic request, including ones that never need the user (an unauthenticated JSON endpoint, a CORS preflight). Expose a memoised getter instead of an eager lookup:

    ```ts
    const session: Handle = async ({ event, resolve }) => {
        let pending: Promise<App.Locals['user']> | undefined;
        Object.defineProperty(event.locals, 'user', {
            configurable: true,
            get: () => (pending ??= lookupUser(event.cookies.get('session'))),
            enumerable: true
        });
        return resolve(event);
    };
    ```

    The catch is that `locals.user` becomes a promise-returning pattern, which changes the type; many teams prefer an explicit `locals.getUser()` function memoised per request. Either way the lookup happens at most once, and only when something asks.

5.  **Locals and remote functions.** Remote functions read `getRequestEvent().locals`, so identity derived in `handle` is available to queries, forms and commands. That is the recommended trust path: identity from *cookies and headers* into `locals` in `handle`; authorisation checks inside each function.
6.  **Locals do not refresh mid-request.** `handle` runs once, before actions and remote calls. If an action or `form`/`command` handler changes the session cookie, it must also update `locals` (Chapter 6, section 6.9) because `load` functions of the same request see the same object.
7.  **Do not copy `locals` into page data wholesale.** `return { ...locals }` from a root layout `load` sends every field to the browser, including `requestId` or internal flags. Return an explicit projection (`{ user: locals.user && { name: locals.user.name } }`).

Where `AsyncLocalStorage` is available, `getRequestEvent()` (Chapter 7) gives deep helper functions access to `locals` without threading the event through every call. Prefer that to your own `AsyncLocalStorage` for request context unless you need data the event does not carry; and know that on runtimes without async local storage it only works synchronously at the start of a function.

## 9.5 `handleFetch`

`event.fetch` is the `fetch` you receive in `load`, actions, endpoints, `handle` and `reroute`. On the server it:

- resolves relative URLs against the incoming request,
- calls your own endpoints **directly** through the server (no network) via `respond`,
- forwards `cookie` and `authorization` headers to same-origin requests (and `cookie` to subdomains of the app’s host), unless `credentials: 'omit'`,
- forwards `accept-language`, sets a default `accept: */*`,
- records `set-cookie` headers of internal responses so they reach the browser,
- inlines responses into SSR HTML (Chapter 4).

`handleFetch` intercepts every one of these calls with `{ event, request, fetch }`, and must return a `Response`. It is the single place to rewrite URLs, attach headers, apply timeouts and observe outbound calls.

### Internal API rewrite

During SSR your `load` can talk to the API over the private network instead of the public gateway, while the browser uses the public URL:

```ts
// src/hooks.server.ts
import type { HandleFetch } from '@sveltejs/kit/hooks';

export const handleFetch: HandleFetch = async ({ request, fetch }) => {
    if (request.url.startsWith('https://api.example.com/')) {
        request = new Request(
            request.url.replace('https://api.example.com/', 'http://api.internal:9999/'),
            request
        );
    }
    return fetch(request);
};
```

`new Request(url, request)` clones the method, headers and body of the original. Remember that a rewritten request to a different origin does not automatically get cookies: the built-in cookie forwarding only applies when the target host is the app’s host or a subdomain of it.

### Credential forwarding

Sibling subdomains (`www.example.com` calling `api.example.com`) do not receive cookies set on the parent domain, because SvelteKit cannot know which domain a cookie belongs to. Forward explicitly, and only to hosts you control:

```ts
export const handleFetch: HandleFetch = async ({ event, request, fetch }) => {
    const url = new URL(request.url);
    if (url.hostname === 'api.example.com') {
        request.headers.set('cookie', event.request.headers.get('cookie') ?? '');
    }
    return fetch(request);
};
```

Never forward the user’s cookies or `authorization` to third-party hosts. The pattern above matches the hostname exactly instead of using a prefix test on the URL string, which `https://api.example.com.evil.test/` would pass.

### Service-to-service headers, timeouts and tracing

```ts
export const handleFetch: HandleFetch = async ({ event, request, fetch }) => {
    const url = new URL(request.url);
    if (url.hostname.endsWith('.internal')) {
        request.headers.set('x-request-id', event.locals.requestId);
        request.headers.set('authorization', `Bearer ${await serviceToken()}`);

        const started = performance.now();
        try {
            return await fetch(new Request(request, { signal: AbortSignal.timeout(5_000) }));
        } finally {
            console.info('upstream', url.pathname, Math.round(performance.now() - started), 'ms');
        }
    }
    return fetch(request);
};
```

Limits to remember: `handleFetch` only sees `event.fetch`. A bare `fetch` imported from the platform bypasses it entirely, including cookie forwarding, URL resolution and the ability to call internal routes. Inside `load` functions always use the provided `fetch`. Inside `handleFetch`, call the `fetch` argument, not the global, to preserve internal routing; the argument is what implements the “call my own endpoint without a network hop” behaviour. Also, `handleFetch` runs for sub-requests triggered inside `reroute`, but there `params` and `route.id` are unavailable because the route is not yet known.

## 9.6 `init`, `reroute` and `transport`

### `init`

```ts
// src/hooks.server.ts
import type { ServerInit } from '@sveltejs/kit/hooks';
import * as db from '#lib/server/db.js';

export const init: ServerInit = async () => {
    await db.connect();
};
```

`init` runs once when the server instance is created, before the first request. It is equivalent to top-level `await` in the hooks module; the hook exists because some environments do not support top-level await. Let it reject loudly if a hard dependency such as the database is missing, rather than swallowing the error and serving broken responses. In the browser, `init` in `hooks.client.ts` runs when the app starts and **delays hydration**; do not put network calls on that path.

### `reroute`

`reroute({ url, fetch })`, exported from the universal `src/hooks.ts`, runs before route matching, on both server and client, and returns the pathname to *match against*. It changes neither the address bar nor `event.url`; it only changes which route is selected and from what string `params` are derived. The classic use is translated pathnames over one set of routes:

```ts
// src/hooks.ts
import type { Reroute } from '@sveltejs/kit/hooks';

const translated: Record<string, string> = {
    '/de/ueber-uns': '/de/about',
    '/fr/a-propos': '/fr/about'
};

export const reroute: Reroute = ({ url }) => translated[url.pathname];
```

(With `src/routes/[[lang]]/about/+page.svelte` in place, `lang` is derived from the returned pathname.) Rules:

- It must be **pure and idempotent**: the same URL must always yield the same result, with no side effects. SvelteKit caches `reroute` results on the client, calling it once per unique URL; if the mapping can change at runtime (a CMS-driven redirect table), the cache will serve stale answers.
- It may be `async` (since 2.18) and receives a special `fetch` with the same benefits as the one passed to `load`. Anything slow here **delays every navigation**, because routing cannot start until it resolves. If you fetch, guard against self-recursion for the endpoint you call (as the docs’ `/api/reroute` example does).
- It is **not** called for remote function calls or for route-resolution requests. For data requests it sees the page URL, with the `__data.json` suffix already stripped.
- If it throws on the server, the response is a plain 500. Keep it total.
- If the rerouted path has a prerendered file, the prerendered response is served.

Do not use `reroute` for redirects (the URL does not change) or for access control (it is not a security boundary).

### `transport`

Also in `src/hooks.ts`. It teaches the serialiser about custom classes so they can cross the server-to-client boundary in `load` data, action results, remote function arguments and results, and snapshots:

```ts
// src/hooks.ts
import type { Transport } from '@sveltejs/kit/hooks';
import { Vector } from '#lib/math.js';

export const transport: Transport = {
    Vector: {
        encode: (value) => value instanceof Vector && [value.x, value.y],
        decode: ([x, y]) => new Vector(x, y)
    }
};
```

`encode` runs on the server (and on the client for remote function arguments); it must return a truthy encoding for instances of the type and `false` for everything else. The encoding itself must be devalue-serialisable. The key (`Vector`) is part of the wire format, so renaming it is a breaking change for stale clients (Chapter 7). Because `encode` is tried on every serialised object, keep `instanceof` checks first and cheap.

## 9.7 What changed in SvelteKit 3

| Area | 2.x | 3.x |
|------------------------|------------------------|------------------------|
| Type imports | `import type { Handle } from '@sveltejs/kit'` | `import type { Handle } from '@sveltejs/kit/hooks'` |
| `resolve` return type | `MaybePromise<Response>` | `Promise<Response>` |
| `handleError` | not called for `error()`-created errors; no `kind` | called for **all** errors, with `kind` (`app`, `framework`, `validation`, `unknown`); may return `status` |
| `handleValidationError` | existed | removed; use `handleError` with `kind: 'validation'` |
| `handleError` default values | you built the whole object | omitted properties are inherited from the caught error |
| Rendering errors | opt-in `experimental.handleRenderingErrors` | always on, routed through `handleError` |
| `defineEnvVars` | `@sveltejs/kit/hooks` | `@sveltejs/kit/env` |
| `getRequest`/`setResponse` | async | synchronous |
| Cookie defaults | `path` required | `path` defaults to `/` |
| CSRF | `csrf.checkOrigin` | always on; `csrf.trustedOrigins`; cross-origin mutating requests without `Content-Type` rejected |

The `handleError` details are Chapter 10’s subject.

## 9.8 Cross-cutting concerns as hooks

The following recipes are deliberately small. Each is a standalone `Handle` that composes with `sequence`.

### Request IDs, logging and `Server-Timing`

```ts
export const observe: Handle = async ({ event, resolve }) => {
    const id = event.request.headers.get('x-request-id') ?? crypto.randomUUID();
    event.locals.requestId = id;
    const started = performance.now();

    const response = await resolve(event);

    const ms = performance.now() - started;
    const out = new Response(response.body, response);        // headers may be immutable
    out.headers.set('x-request-id', id);
    out.headers.append('server-timing', `app;dur=${ms.toFixed(1)}`);

    if (!event.isSubRequest) {
        console.info(JSON.stringify({
            id, method: event.request.method, path: event.url.pathname,
            route: event.route.id, status: out.status, ms: Math.round(ms),
            remote: event.isRemoteRequest || undefined
        }));
    }
    return out;
};
```

Cloning the response with `new Response(response.body, response)` keeps the streaming body (no buffering) and gives mutable headers. Note that duration measured here ends when the headers are available, not when a streamed body completes. Log `event.route.id` rather than the raw URL to keep metric cardinality bounded.

### CORS for endpoints

SvelteKit does not add CORS headers; pages deny preflight implicitly. For a public JSON API under `/api`, handle `OPTIONS` yourself and decorate responses:

```ts
const ALLOWED = new Set(['https://app.example.com', 'https://admin.example.com']);

export const cors: Handle = async ({ event, resolve }) => {
    if (!event.url.pathname.startsWith('/api/')) return resolve(event);

    const origin = event.request.headers.get('origin');
    const allowed = origin !== null && ALLOWED.has(origin);

    if (event.request.method === 'OPTIONS') {
        return new Response(null, {
            status: 204,
            headers: allowed
                ? {
                        'access-control-allow-origin': origin,
                        'access-control-allow-methods': 'GET,POST,PUT,PATCH,DELETE',
                        'access-control-allow-headers': 'content-type,authorization',
                        'access-control-max-age': '86400',
                        vary: 'Origin'
                    }
                : {}
        });
    }

    const response = await resolve(event);
    const out = new Response(response.body, response);
    out.headers.append('vary', 'Origin');
    if (allowed) out.headers.set('access-control-allow-origin', origin);
    return out;
};
```

Always send `Vary: Origin` when the response depends on it, and compare origins against an exact allow-list. Two interactions with CSRF: SvelteKit’s CSRF check (which runs *before* `handle`) rejects cross-origin form-typed `POST`s unless the origin is in `csrf.trustedOrigins`, and a cross-origin `fetch` with `application/json` is not form-typed so it passes that check but still faces your CORS policy. CORS is a browser rule, not authentication: server-to-server callers ignore it.

### Rate limiting

```ts
const buckets = new Map<string, { tokens: number; updated: number }>();

function allow(key: string, capacity = 30, refillPerSec = 0.5): boolean {
    const now = Date.now();
    const b = buckets.get(key) ?? { tokens: capacity, updated: now };
    b.tokens = Math.min(capacity, b.tokens + ((now - b.updated) / 1000) * refillPerSec);
    b.updated = now;
    const ok = b.tokens >= 1;
    if (ok) b.tokens -= 1;
    buckets.set(key, b);
    return ok;
}

export const rateLimit: Handle = async ({ event, resolve }) => {
    const sensitive = event.request.method !== 'GET' || event.isRemoteRequest;
    if (sensitive && !allow(`${event.getClientAddress()}:${event.route.id ?? event.url.pathname}`)) {
        return new Response('Too many requests', { status: 429, headers: { 'retry-after': '10' } });
    }
    return resolve(event);
};
```

This is a per-process token bucket, an exception to the rule against module state because limiter state is *meant* to be shared across requests. It does not coordinate across instances; for more than one server use a shared store (Redis, a platform rate-limit binding). `getClientAddress()` depends on the adapter and, behind proxies, on trusted-header configuration (`ADDRESS_HEADER`/`XFF_DEPTH` for adapter-node, Chapter 18); misconfigured, every client appears as the proxy and one abuser throttles everyone. The map above grows without bound; evict stale entries in production. For remote calls, `event.route.id` is `null` for queries and the calling page’s route for forms and commands, so key on the remote id (parse `event.url.pathname`) if you want per-function limits.

### Locale

```ts
const SUPPORTED = ['en', 'de', 'bg'] as const;

export const locale: Handle = async ({ event, resolve }) => {
    const cookie = event.cookies.get('locale');
    const header = event.request.headers.get('accept-language') ?? '';
    const preferred = header.split(',').map((p) => p.trim().slice(0, 2).toLowerCase());
    const chosen = SUPPORTED.find((l) => l === cookie) ?? SUPPORTED.find((l) => preferred.includes(l)) ?? 'en';

    event.locals.locale = chosen;
    return resolve(event, {
        transformPageChunk: ({ html }) => html.replace('%lang%', chosen)
    });
};
```

If the locale is also encoded in the URL (`/de/...`), derive it from `event.params.lang` or the pathname instead and use `reroute` for translated slugs. Responses that vary by `Accept-Language` or cookie must set `Vary` accordingly or be non-cacheable (Chapter 16).

### Security headers

```ts
export const securityHeaders: Handle = async ({ event, resolve }) => {
    const response = await resolve(event);
    const out = new Response(response.body, response);
    out.headers.set('x-content-type-options', 'nosniff');
    out.headers.set('referrer-policy', 'strict-origin-when-cross-origin');
    out.headers.set('permissions-policy', 'camera=(), microphone=(), geolocation=()');
    return out;
};
```

Content-Security-Policy belongs in `sveltekit({ csp })` configuration, which handles nonces and hashes; a `handle` hook cannot know them (Chapter 15). Also remember that prerendered HTML and static assets bypass `handle`; set their headers at the CDN or in adapter configuration.

### Maintenance mode

```ts
import { building } from '$app/env';

export const maintenance: Handle = async ({ event, resolve }) => {
    if (building) return resolve(event);                  // do not break prerendering
    if (process.env.MAINTENANCE !== '1') return resolve(event);
    if (event.url.pathname === '/healthz') return new Response('ok');

    return new Response(
        '<!doctype html><h1>Back soon</h1>',
        { status: 503, headers: { 'content-type': 'text/html; charset=utf-8', 'retry-after': '600' } }
    );
};
```

Return `503` with `Retry-After`, not 200, so crawlers and monitors understand. Because static and prerendered assets bypass `handle`, a maintenance page implemented here covers only dynamic routes; platform-level maintenance (CDN rules) is the complete solution. Use the `building` flag so that a flag set in the build environment does not turn every prerendered page into the maintenance page.

### An authentication guard

```ts
import { redirect } from '@sveltejs/kit';

const PUBLIC = [/^\/$/, /^\/login/, /^\/blog(\/|$)/];

export const guard: Handle = async ({ event, resolve }) => {
    const isPublic = PUBLIC.some((r) => r.test(event.url.pathname));
    if (!isPublic && !event.locals.user && !event.isRemoteRequest) {
        redirect(303, `/login?redirectTo=${encodeURIComponent(event.url.pathname)}`);
    }
    return resolve(event);
};
```

Guards on URL patterns are a first line of defence, not a substitute for checks in data code: remote queries see the endpoint URL in `handle`, actions run behind the page URL, and a new route added without updating the list is unprotected by default. Prefer default-deny lists and keep per-function checks as discussed in Chapters 7, 8 and 14.

## 9.9 What hooks do not intercept

A short, uncomfortable list:

- **Static files and prerendered pages.** Served before the framework runs; no `handle`, no `locals`, no headers from your hooks.
- **Requests that never reach the server.** Client-side navigations between pages whose `load` functions are universal and only `fetch` from third-party APIs hit your server not at all. (Navigations that need server `load` data issue `__data.json` requests, which do reach `handle`.)
- **Server-side `fetch` that is not `event.fetch`.** A global `fetch` call inside a library bypasses `handleFetch`.
- **Actions after `handle`.** `handle` runs before an action. State it derived (`locals`) is not refreshed afterwards, and your post-`resolve` code sees only the final response, not intermediate action results (Chapter 6).
- **Remote function details.** They do go through `handle`, but (a) for queries the URL is the endpoint and `route.id` is `null`, (b) for forms and commands the URL and route come from client-controlled headers, (c) cookies can only be written in forms and commands, and (d) headers cannot be set from inside them (Chapters 7 and 8). Decorating *responses* in `handle` still works for the remote endpoint’s HTTP response.
- **CSRF rejection** happens before `handle`, and only in production. Do not rely on `vite dev` to reproduce it.
- **Non-HTTP traffic.** WebSocket upgrades, raw TCP and server-sent connections that are not HTTP requests to SvelteKit routes are the adapter’s or platform’s concern (Chapter 18). `query.live` streams *do* pass through `handle`, but `handle` sees the request, not each yielded message; put per-message checks in the generator.
- **Streaming bodies.** `handle` gets the `Response` when headers are ready. Mutating `response.body` is not possible without wrapping the stream; `transformPageChunk` is the supported hook for HTML.
- **Client navigation errors.** `hooks.server.ts` `handle` does not see errors thrown in the browser; `hooks.client.ts` `handleError` does.
- **Hooks are not a security boundary for data.** An authentication guard in `handle` is not equivalent to authorising each data operation (Chapter 14).

## Key takeaways

- Hooks live in `hooks.server.ts` (`handle`, `handleFetch`, `handleError`, `init`), `hooks.client.ts` (`handleError`, `init`) and the universal `hooks.ts` (`reroute`, `transport`). Types come from `@sveltejs/kit/hooks` in SvelteKit 3; `sequence` is its only runtime export.
- `handle` runs after CSRF checks, `reroute` and route matching, for dynamic requests only: static assets and prerendered pages bypass it. Data requests, actions, endpoints, remote calls and internal sub-requests all pass through it.
- `resolve` always returns a `Promise<Response>` and never throws; errors thrown directly in `handle` are fatal and answered with JSON or `error.html`, never `+error.svelte`. Clone responses before mutating headers.
- `transformPageChunk` chunks are not element-aligned: use it only for placeholders you own. `filterSerializedResponseHeaders` defaults to none. `preload` is not called in dev.
- In `sequence`, pre-processing runs in order, post-processing in reverse, `transformPageChunk` composes in reverse, and `preload` and `filterSerializedResponseHeaders` are first-defined-wins.
- `locals` is per-request server-only context: always assign every property, store identities not data, project explicitly into page data, and update it yourself when actions or mutations change what it was derived from.
- `handleFetch` only sees `event.fetch`; use it for internal URL rewrites, scoped credential forwarding (match hostnames exactly), timeouts and tracing.
- `reroute` must be pure and fast and does not change the URL; `transport` extends serialisation; client `init` delays hydration.
- Build CORS, rate limiting, locale, headers and maintenance mode as small named `Handle`s composed with `sequence`, cheap rejecters first.
- Hooks do not cover static files, non-`event.fetch` calls, or per-operation authorisation. Keep data-level checks next to the data.

## Review Questions

1.  List the three hook files and which hooks each may export. Which are universal?

2.  Where do the hook types come from in SvelteKit 3, and what does `@sveltejs/kit/hooks` export at runtime?

3.  Name three kinds of requests that never reach `handle`.

4.  In which order do these happen: `reroute`, `handle`, CSRF origin check, route matching? Why does the order matter for CSRF?

5.  A page’s `load` calls `event.fetch('/api/a')`, `event.fetch('/api/b')` and `event.fetch('/api/c')`. How many times does `handle` run for one SSR request, and what distinguishes the calls?

6.  What does this print?

    ```ts
    const a: Handle = async ({ event, resolve }) => { console.log('a1'); const r = await resolve(event); console.log('a2'); return r; };
    const b: Handle = async ({ event, resolve }) => { console.log('b1'); const r = await resolve(event); console.log('b2'); return r; };
    export const handle = sequence(a, b);
    ```

7.  Two handlers in a `sequence` both pass `preload` options to `resolve`. Which one is used? What if only the second does?

8.  Why is it unsafe to implement `transformPageChunk` as `html.replace(/<title>.*?<\/title>/, ...)`? What is a safe pattern?

9.  A load function inlined an API response and the browser code reads `response.headers.get('x-total-count')` after hydration but gets `null`. What is missing?

10. Find the bug (hint: what response types could cause this to throw?):

    ```ts
    export const handle: Handle = async ({ event, resolve }) => {
      const response = await resolve(event);
      response.headers.set('x-frame-options', 'DENY');
      return response;
    };
    ```

11. An error is thrown directly inside `handle` before `resolve`. What does the user see for a browser navigation, and for a request with `Accept: application/json`? Is `+error.svelte` used?

12. Why can’t a `handle` hook wrap `resolve` in `try/catch` to react to a failing `load`? How would you detect it?

13. Explain what “the event is sealed after `resolve`” means for `cookies.set`.

14. Why should `locals` assignments be exhaustive, and what typing technique makes the compiler help when a handler is conditionally applied?

15. A root layout `load` does `return { ...locals }`. Describe the problem and the fix.

16. Design: you want `locals.user` available but only looked up if a load or remote function actually reads it. Sketch an approach and its trade-off.

17. An action changes the session cookie and a `load` that runs afterwards in the same request shows the old user. Why, and where is the fix?

18. What does `handleFetch` receive and return? Give two things you can do with it that you cannot do with a plain `fetch` wrapper.

19. Spot the security flaw: `if (request.url.startsWith('https://api.example.com')) request.headers.set('cookie', cookie)`.

20. Why does a bare global `fetch` inside a `load` bypass `handleFetch`, and what else do you lose?

21. In `reroute`, why must the function be pure and idempotent? What happens when it returns a different value for the same URL on different calls?

22. Does `reroute` change `event.url` or the browser URL? What does it change?

23. How does the client treat `init` in `hooks.client.ts`, and why is that a performance concern?

24. Multiple choice: which statement about `transport` is correct?

    a.  `encode` runs only in the browser
    b.  `encode` returns the encoded value or `false` for non-matching values; `decode` rebuilds the instance
    c.  the transporter key is irrelevant to clients
    d.  transport is applied only to `load` data

25. Write a `Handle` that returns 503 with `Retry-After` for every dynamic request when `MAINTENANCE=1`, while not breaking `/healthz` or prerendering. What still bypasses it?

26. In the CORS recipe, why is `Vary: Origin` required, and why does SvelteKit’s CSRF check not stop a cross-origin JSON `fetch`?

27. Explain two reasons an in-memory rate limiter keyed by `getClientAddress()` may fail in production.

28. For a remote `query`, what do `event.url.pathname` and `event.route.id` contain inside `handle`? How does that affect a path-based admin guard?

29. Which `resolve` option is not called in `vite dev`, and why?

30. List three SvelteKit 3 changes that affect code in `hooks.server.ts` and say what to change for each.
