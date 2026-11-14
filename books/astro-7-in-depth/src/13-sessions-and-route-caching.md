# Chapter 12: Sessions and Route Caching

On-demand rendering gives you per-request state and per-request cost. This chapter covers the two stable Astro APIs that manage each of those: **sessions**, which keep server-side state between requests (the logged-in user, the shopping cart, a flash message), and **route caching**, which lets a rendered response be reused across requests, with tags for targeted invalidation. They are in one chapter because they meet in production in the same place, and that place is where bugs get expensive: a personalized response that is accidentally shared, a session that is not shared when you add a second instance, a cookie that silently disables caching.

Everything below was checked against Astro 7.4.1 with the Node adapter (sessions with the default filesystem driver; the in-memory cache provider; a hand-written CDN provider), plus the local documentation and the 7.x changelog. Where the docs and the behaviour I measured differ, the text says so. Svelte islands appear where they interact with these features: they never touch sessions or the cache directly, but they consume what the server decided.

> **Note:** Both features require an adapter and on-demand rendering. A prerendered route has no per-request session and nothing to cache at runtime; it is already a static file.

## Part 1: Sessions

### What a session is, and what it is not

A session is a server-side key/value store addressed by an opaque ID that travels in a cookie. The cookie contains only the ID (a v4 UUID); data lives in a storage driver. That makes sessions different from the other state mechanisms you have:

| Mechanism | Lives in | Size | Trust | Good for |
|---------------|---------------|---------------|---------------|---------------|
| `Astro.cookies` | Browser | about 4 KB per cookie | Client can read/alter (unless signed) | Preferences, tiny flags |
| Session | Your storage driver | Large | Server-only | Auth state, carts, flash messages, wizard progress |
| Signed JWT cookie | Browser | small | Verifiable, not revocable | Stateless auth between services |
| Database rows | Your DB | Unlimited | Server-only | Durable domain data |

Sessions are the right place for state that is tied to one browser, needs to be large or private, and does not need to outlive its owner. They are the wrong place for durable business data (an order is a database row; the *cart that became the order* can be session state) and for data that must be shared between users.

The feature arrived in Astro 5.7 and became fully stable in 6.x; `session: false` was added in 7.2.

### Choosing and configuring a driver

A session driver is any storage that implements `getItem`, `setItem` and `removeItem`. Astro uses [unstorage](https://unstorage.unjs.io) internally, and the official adapters wire up defaults:

| Adapter | Default session storage |
|------------------------------------|------------------------------------|
| `@astrojs/node` | Filesystem. The adapter logs `Enabling sessions with filesystem storage` and stores files under `<cacheDir>/sessions`, which by default is `./node_modules/.astro/sessions` |
| `@astrojs/cloudflare` | Workers KV, binding `SESSION` (configurable with `sessionKVBindingName`; Wrangler can auto-provision the namespace) |
| `@astrojs/netlify` | Netlify Blobs |
| `@astrojs/vercel` and others | None: you must configure `session.driver` |

Look at the Node default with production eyes. Files in `node_modules/.astro/sessions` live inside the container image’s writable layer. They vanish when the container is replaced and they are not shared between replicas, so a load balancer without sticky sessions will “lose” sessions at random. The default is a development convenience and a fine single-VM choice; for anything horizontally scaled or ephemeral, configure a shared driver (Redis, a database through `db0`, Upstash, S3, and so on).

Drivers are configured with the helpers on `sessionDrivers` from `astro/config`. In 7.4.1 this object is built from unstorage’s built-in drivers, so every unstorage driver whose name has no hyphen is available as `sessionDrivers.<name>(options)`: for example `redis`, `upstash`, `lruCache`, `memory`, `netlifyBlobs`, `cloudflareKVBinding`, `vercelKV`, `s3`, `mongodb`, `db0`, `fsLite`, `null`. The `fs` entry is special-cased to the lighter `fsLite` driver with `base: '.astro/session'` as default.

```js
// astro.config.mjs
import { defineConfig, sessionDrivers } from 'astro/config';
import vercel from '@astrojs/vercel';

export default defineConfig({
  adapter: vercel(),
  session: {
    driver: sessionDrivers.redis({ url: process.env.REDIS_URL }),
    ttl: 60 * 60 * 24 * 7, // default expiry for each stored value, in seconds
    cookie: { name: 'sid', sameSite: 'lax' },
  },
});
```

Two older spellings still work but are deprecated: the string form `driver: 'redis'` with a separate `options` object. Prefer the function form.

> **Warning:** The build-time inlining caveat from the docs matters. By default the driver *configuration* is evaluated at build time and any environment variable you reference with `process.env` is baked into the bundle. A `REDIS_URL` read in `astro.config.mjs` is the URL at build time, not at runtime.

### Runtime configuration through a driver entrypoint

When the connection settings must come from the environment of the running server (twelve-factor deployments, secrets injected at start), write the driver as a module and give Astro its URL as `driver.entrypoint`. The entrypoint’s default export is a function returning a `SessionDriver` object with three methods:

```ts
// src/session-driver.ts
import type { SessionDriver } from 'astro';
import redisDriver from 'unstorage/drivers/redis';
import { REDIS_HOST, REDIS_PORT } from 'astro:env/server';

export default function (): SessionDriver {
  const driver = redisDriver({ host: REDIS_HOST, port: REDIS_PORT, ttl: 60 * 60 * 24 * 7 });
  return {
    async getItem(key) {
      return await driver.getItem(key);
    },
    async setItem(key, value) {
      await driver.setItem?.(key, value, {});
    },
    async removeItem(key) {
      await driver.removeItem?.(key, {});
    },
  };
}
```

```js
// astro.config.mjs
import { defineConfig, envField } from 'astro/config';
import node from '@astrojs/node';

export default defineConfig({
  adapter: node({ mode: 'standalone' }),
  env: {
    schema: {
      REDIS_HOST: envField.string({ context: 'server', access: 'public', default: 'localhost' }),
      REDIS_PORT: envField.number({ context: 'server', access: 'public', default: 6379 }),
    },
  },
  session: { driver: { entrypoint: new URL('./src/session-driver.ts', import.meta.url) } },
});
```

Notes on this design:

- `astro:env/server` (Chapter 16) is how the entrypoint reads runtime configuration in a way that works across adapters; plain `process.env` works on Node only.
- A *driver config* has the shape `{ entrypoint: string | URL, config?: Record<string, any> }`. The entrypoint can be a package specifier such as `'unstorage/drivers/redis'`, in which case `config` is passed to the driver factory. The `config` must be serializable, because it is embedded in the build.
- The driver-level `ttl` above is what actually deletes expired data from Redis. The session-level `ttl` described below only hides expired values; it does not reclaim space.
- Because the session object is created per request and the driver once per process, a driver factory is a good place for connection reuse, but keep it free of request-specific state.

### Disabling sessions, and what `Astro.session` is when it is not configured

Whenever no driver is configured, Astro excludes the session runtime (and `unstorage`) from the server bundle. Setting `session: false` goes one step further and tells adapters not to add their default driver, so a Node or Cloudflare build that does not use sessions does not carry the dependency or provision a KV namespace:

```js
export default defineConfig({ adapter: node({ mode: 'standalone' }), session: false });
```

The type of the property is `AstroSession | undefined`, and here the documentation contradicts the changelog. The API reference says `Astro.session` is `undefined` (and logs) when no storage is configured, sessions are disabled, or the route is prerendered; the 7.0.0 changelog says “the `session` property is now always defined on the context object, and accessing it without configuration logs a helpful message instead of silently returning `undefined`”. I tested both a `session: false` build and a configured one:

```text
// session: false  ->  page code: String(Astro.session)
cart= sess=undefined
[WARN] [session] `Astro.session` was accessed but no session storage is configured. Either configure the storage
manually or use an adapter that provides session storage.
```

So in 7.4.1 the *value* you read is `undefined` and *reading it logs a warning*; the changelog sentence is describing the property existing on the context as an accessor, not the value. In practice the documented usage `Astro.session?.get(...)` is correct, and the warning is how you discover a misconfigured deployment. Treat optional chaining as mandatory in shared code (components, middleware) that runs under unknown configurations; in code that *requires* sessions, assert once at the boundary:

```ts
// src/lib/session.ts
import type { APIContext } from 'astro';

export function requireSession(ctx: Pick<APIContext, 'session'>) {
  if (!ctx.session) throw new Error('Sessions are not configured for this deployment.');
  return ctx.session;
}
```

Sessions are not supported in edge middleware (`adapterFeatures.middlewareMode: 'edge'`, Chapter 10).

### The session API

`Astro.session` in pages, `context.session` in endpoints, middleware and actions (inside actions, `ctx.session`). The documented methods are `get`, `set`, `regenerate`, `destroy` and `load`. The 7.4.1 typings and implementation also include `has`, `keys`, `values`, `entries`, `delete` and a read-only `sessionID`; they are not in the reference pages, so treat them as available but less formally specified. A summary, with what I verified in the source:

| Member | Signature | Notes |
|------------------------|------------------------|------------------------|
| `get(key)` | `Promise<T \| undefined>` | Loads the stored map lazily on first read |
| `set(key, value, { ttl }?)` | `void` (synchronous) | Value is serialized immediately; storage write happens at the end of the request |
| `delete(key)` | `void` | Removes one key |
| `has/keys/values/entries` | `Promise<...>` | Exist in 7.4.1 typings |
| `regenerate()` | `Promise<void>` | New ID, data preserved, old ID removed from storage. The reference says `void`, the typings say `Promise<void>`: always `await` it |
| `destroy()` | `void` | Deletes the cookie and the stored object |
| `load(id)` | `Promise<void>` | Replaces the current session with the one stored under `id` and sets the cookie |
| `sessionID` | `string \| undefined` | Current ID |

#### Lazy by design

Three behaviours make sessions cheap for anonymous traffic, and are worth knowing because they affect caching:

1.  **No cookie and no `set()` means no storage read.** `get()` on a request without a session cookie returns `undefined` without touching the driver.
2.  **The cookie is issued on first `set()`** (or `regenerate()`/`load()`), not on first `get()`. In my test, a cached page that merely read the session returned no `Set-Cookie`; the same page with `?w=1`, which called `set`, did.
3.  **Writes are deferred to the end of the request.** `set()` is synchronous and the new value is visible to later `get()` calls in the same request, but it is persisted by a finalizer after rendering. If persistence fails (driver down) the failure surfaces at the end of the request, not at the `set()` call.

Because the cookie is a response header, session writes should happen before the response starts streaming: in middleware, page frontmatter, actions and endpoints. A `set()` deep inside a component that renders after the first byte has been sent cannot add a header.

#### Values are cloned at `set()` time

This is the most common session bug. The implementation serializes your value with devalue and stores a *clone*, “so later updates are not persisted into the store”:

```ts
const cart = (await session.get('cart')) ?? [];
session.set('cart', cart);
cart.push(sku);            // BUG: not persisted. The stored clone was taken above.
```

Mutate first, then `set()`:

```ts
const cart = (await session.get('cart')) ?? [];
cart.push(sku);
session.set('cart', cart);
```

Cloning has two other consequences. First, values must be devalue-serializable: strings, numbers, booleans, `null`/`undefined`, arrays, plain objects, `Date`, `Map`, `Set`, `URL`, `BigInt`, `RegExp`, typed arrays. Functions and class instances throw a `SessionStorageSaveError` at `set()` time (“could not be serialized”), which is good: you find out at the call site. Second, what you read back is a plain revived structure: a `Map` stays a `Map`, but your own class is not restored. Store ids, not objects with behaviour.

#### Expiry (`ttl`)

`session.ttl` in the config (default: no expiry) and the per-call `{ ttl }` option set an expiry *per value*, in seconds. Astro stores an `expires` timestamp next to each value and ignores expired values when it loads the session; it does not proactively delete them. The docs state this explicitly: values are removed from storage only when accessed after expiry, so for actual reclamation use the driver’s own TTL (Redis `ttl`, S3 lifecycle rules).

The session cookie, by contrast, has no expiry unless you add `maxAge` or `expires` to `session.cookie`. A browser session cookie vanishes when the browser closes, but the server-side data lives on. A realistic policy therefore combines three layers:

```ts
// Idle/absolute timeouts for an authenticated session
session.set('user', { id, name }, { ttl: 60 * 60 * 8 });   // absolute: 8 hours from login
session.set('lastSeen', Date.now(), { ttl: 60 * 30 });      // idle marker, refreshed by middleware
```

with the cookie configured with a matching `maxAge`, and the driver configured to reap.

#### Cookie options

`session.cookie` is either a string (the name) or an object merged over the defaults. The documented default is `{ name: 'astro-session', sameSite: 'lax', httpOnly: true, secure: true }`. The implementation refines this in two ways that matter:

- `httpOnly` is forced to `true`: you cannot turn it off.
- `secure` defaults to `true` only when the runtime mode is production; in `astro dev` it is off so that the cookie works on `http://localhost`. In production you therefore need HTTPS end to end (or `X-Forwarded-Proto` handling in your proxy) or browsers will discard the cookie. Remember that `curl` over `http://localhost` is treated as secure context by recent versions and accepts it, so a curl test will not reveal this mistake.
- The cookie name must match `/^[\w-]+$/`; anything else throws a `SessionStorageSaveError`.

Other `AstroCookieSetOptions` such as `maxAge`, `domain`, `path` (default `/`), and `partitioned` are passed through.

#### Session IDs are server-controlled

Two hardening details, both visible in the code and in the 7.x changelog (“Fixes session ID validation to reject non-UUID cookie values before using them as storage keys”):

- A cookie that is not a v4 UUID is never used as a storage key.
- A well-formed UUID from the cookie that has *no* data in storage is replaced by a freshly generated ID. I confirmed it: a request with the forged cookie `astro-session=11111111-1111-4111-8111-111111111111` got `sid` `48c1e0f3-...` back.

Together these prevent a client from choosing its own session ID (the classic fixation vector) and from using cookie values as path traversal keys against a filesystem driver. They do not remove the need to call `regenerate()` on privilege changes, as the next section shows, because an attacker who *planted a valid existing ID* in a victim’s browser is a different attack.

#### Concurrency

There are no transactions. At persist time Astro loads the stored map, overlays the values this request changed (and drops the keys it deleted), and writes the whole map back. Two concurrent requests changing *different* keys therefore usually both survive, but two requests doing read-modify-write on the *same* key (two “add to cart” calls issued at once) can lose an update: last writer wins. If a value needs atomic updates (counters, inventory), keep it in a database with proper transactions, and let the session hold only the pointer.

Also keep sessions small. Every request that touches a session loads the entire map for that ID from the driver, so store references and let the database hold the payloads.

#### Typing session data

```ts
// src/env.d.ts
/// <reference types="astro/client" />
declare namespace App {
  interface SessionData {
    user: { id: string; name: string };
    cart: string[];
    flash: { name: string; result: unknown };
  }
  interface Locals {
    user?: { id: string };
  }
}
```

With this, `get('cart')` is `Promise<string[] | undefined>` and `set('user', ...)` is checked. In 7.4.1 `get` and `set` also accept a type argument for ad hoc keys (`session.get<number>('visits')`). The types are compile-time only. If you change `SessionData` while users hold old sessions, nothing migrates the stored values; write defensive reads (`?? []`) or version your keys.

### Authentication patterns

The official guide offers no first-party auth: it documents third-party libraries (Better Auth, Clerk, Lucia resources) and says there is no official solution. The Sessions API is a good foundation for a simple, server-side, revocable login, and understanding it clarifies what the libraries do for you.

#### A minimal session login

The flow I verified end to end (anonymous, login, authenticated read, logout, authenticated read again) has four parts: a middleware that projects the session into `locals`, a login that regenerates the ID, route protection, and a logout.

```ts
// src/middleware.ts
import { defineMiddleware, sequence } from 'astro:middleware';

const loadUser = defineMiddleware(async (context, next) => {
  const user = await context.session?.get('user');
  if (user) context.locals.user = { id: user.id };
  return next();
});

export const onRequest = sequence(loadUser);
```

```ts
// src/pages/api/login.ts
import type { APIRoute } from 'astro';

export const prerender = false; // not needed with output: 'server'

export const POST: APIRoute = async ({ request, session, locals }) => {
  const { email, password } = await request.json();
  const user = await verifyCredentials(email, password); // your code: constant-time compare, rate limit
  if (!user) return Response.json({ error: 'Invalid credentials' }, { status: 401 });

  // Privilege change: issue a new ID so a pre-login ID cannot be reused.
  await session?.regenerate();
  session?.set('user', { id: user.id, name: user.name }, { ttl: 60 * 60 * 8 });
  return Response.json({ ok: true });
};
```

```ts
// src/pages/api/logout.ts
import type { APIRoute } from 'astro';
export const POST: APIRoute = async ({ session }) => {
  session?.destroy();
  return Response.json({ ok: true });
};
```

What the test run showed:

```text
anon    -> {"user":null}
login   -> Set-Cookie: astro-session=4e5df039-...; Path=/; HttpOnly; Secure; SameSite=Lax
me      -> {"user":{"id":"u1"},"cart":["pre-login"],"sid":"4e5df039-..."}
logout  -> Set-Cookie: astro-session=deleted; ...Expires=Thu, 01 Jan 1970...
me      -> {"user":null}
```

Note that `regenerate()` preserved the data stored before login (`cart: ['pre-login']`), which is exactly what you want for “log in with a full cart”, while the identifier changed. `destroy()` removes the cookie and the stored object.

Production additions you must supply yourself: password hashing (use a memory-hard function), login throttling, CSRF protection for the login `POST` (an action in form mode gets the framework’s origin check; see Chapter 11), account lockout, and re-authentication for sensitive operations.

#### Protecting routes without matching pathnames

Chapter 5 warned against authorizing on `url.pathname` because the public path and the route Astro matches can differ (a configured `base`, encodings, duplicate slashes). In middleware you have a better key: `context.routePattern` is the pattern of the route that *was matched*, e.g. `/products/[...slug]` or `/account/[section]`. In my test middleware the log showed:

```text
routePattern: /products/[...slug] | pathname: /products
routePattern: /_actions/[...path] | pathname: /_actions/purge
```

(note how `/products` with zero segments still matches the rest route). Gate on the pattern:

```ts
const protectedPatterns = [/^\/account(\/|$)/, /^\/admin(\/|$)/];

const requireLogin = defineMiddleware(async (context, next) => {
  const guarded = protectedPatterns.some((re) => re.test(context.routePattern));
  if (guarded && !context.locals.user) {
    return context.redirect(`/login?next=${encodeURIComponent(context.originPathname)}`, 303);
  }
  return next();
});

export const onRequest = sequence(loadUser, requireLogin);
```

This is safer than the pathname test but is still a coarse perimeter. Defense in depth means each page, endpoint and action also checks `Astro.locals.user` (or the equivalent) for the data it serves. If you need to put a guard in front of the entire pipeline, including rewrites and other routing quirks, the documented option is advanced routing with a router (`src/fetch.ts` with Hono, Chapter 5), which matches routes for you.

#### Server-side tokens with OIDC, the backend-for-frontend pattern

If your identity provider speaks OpenID Connect (Entra External ID and other CIAM products do), sessions give you the *BFF pattern* natively: the Astro server performs the authorization-code flow, keeps the access and refresh tokens in the session, and the browser only ever holds the opaque `astro-session` cookie. No token touches JavaScript in a Svelte island, which removes a large class of XSS-to-token-theft attacks.

```ts
// sketch: after the callback endpoint has exchanged the code for tokens
await session.regenerate();
session.set('tokens', { access, refresh, expiresAt }, { ttl: refreshLifetimeSeconds });
session.set('user', { id: claims.sub, name: claims.name });
```

An outbound-API helper then reads `tokens`, refreshes when `expiresAt` is near, and writes back. Since two concurrent requests may both try to refresh, serialize refreshes per session (a lock in Redis) or tolerate one wasted refresh; refresh tokens with rotation make the race harmful, so check your provider’s rotation rules. This pattern needs sessions backed by a shared store; it is a reason to configure a real driver on day one.

#### Delegating to a library

Libraries such as Better Auth or Clerk bring their own session machinery. The documented Better Auth integration mounts its handler at `src/pages/api/auth/[...all].ts`, reads the session in server code with `auth.api.getSession({ headers: Astro.request.headers })`, and protects `/dashboard` with a Hono router in `src/fetch.ts`. Clerk offers `clerkMiddleware()` and `Astro.locals.auth()`. These do not use `Astro.session`; the two systems are independent and can coexist (a library for identity, `Astro.session` for carts and flash messages). Whichever you use, project the identity into `Astro.locals` in one middleware, type it in `App.Locals`, and let the rest of the application depend on `locals.user`, not on the library.

#### Passing identity to Svelte islands

A Svelte island must not read cookies or call the session directly. Compute what the island needs on the server and pass serializable props:

```html
---
// src/pages/account.astro
import AccountMenu from '../components/AccountMenu.svelte';
const user = Astro.locals.user;
if (!user) return Astro.redirect('/login', 303);
---
<AccountMenu client:load userId={user.id} />
```

Props are serialized into the page HTML, so never pass secrets or whole session objects. Actions called from the island re-check authorization themselves (Chapter 11). If the header must show the user’s name on otherwise cacheable pages, render it in a server island (Chapter 9), covered at the end of this chapter.

## Part 2: Route caching

### Concepts

Route caching is a platform-agnostic API for telling Astro, per response, how long it may be reused. It stabilized in Astro 7.0 (the experimental `cache` and `routeRules` flags were removed and replaced by top-level `cache` and `routeRules`). The mechanism has three layers:

1.  **Directives**: `maxAge`, `swr`, `tags`, `etag`, `lastModified`, set by `Astro.cache.set()` / `context.cache.set()` in code, or declaratively by `routeRules` in config.
2.  **A provider**, configured at `cache.provider`, which turns directives into behaviour.
3.  **A cache store**, either inside your process (runtime providers) or at a CDN (CDN providers).

The two provider kinds are distinguished by what they implement:

- A **runtime provider** implements `onRequest(context, next)`. It intercepts the request before Astro renders, may answer from its own store, and annotates responses with `X-Astro-Cache: HIT | MISS | STALE`. The built-in `memoryCache()` is one.
- A **CDN provider** implements `setHeaders(options, request)`. It only translates directives into response headers (and implements `invalidate()` against the CDN’s API); the CDN does the caching, and cache hits never reach your server.

### The built-in memory provider

```js
// astro.config.mjs
import { defineConfig, memoryCache } from 'astro/config';
import node from '@astrojs/node';

export default defineConfig({
  output: 'server',
  adapter: node({ mode: 'standalone' }),
  cache: { provider: memoryCache({ max: 500 }) },
  routeRules: {
    '/products/[...slug]': { maxAge: 60, swr: 30, tags: ['products'] },
  },
});
```

`memoryCache()` is an in-process LRU map (default `max: 1000` entries) that:

- caches **only `GET`** requests and only responses with a positive `maxAge` (my test: a page with only `tags` and no `maxAge` was never cached, which means tags alone are not a caching directive for this provider);
- builds the key from origin + pathname + a normalized query string (sorted by default, with common tracking parameters such as `utm_*`, `fbclid`, `gclid` excluded; `query.include` allowlists, `query.exclude` replaces the default blocklist with globs, and specifying both throws);
- supports `Vary`: a response with `Vary: Accept-Language` creates one entry per distinct request value;
- ignores the `Cookie` header for Vary, and refuses to cache responses with `Vary: Cookie` or `Vary: *`;
- refuses to cache any response that sets a cookie (via headers or `Astro.cookies`/`Astro.session`) and logs a warning;
- implements stale-while-revalidate: within `maxAge` it serves `HIT`; between `maxAge` and `maxAge + swr` it serves `STALE` immediately and refreshes in the background so the next request is a `HIT`.

I verified each of these. A condensed log from the test server (`maxAge: 2, swr: 5`, `Vary: Accept-Language`):

```text
en  -> MISS   t=...874
en  -> HIT    t=...874
bg  -> MISS   t=...964         (separate Vary entry)
(after 3 s)
en  -> STALE  t=...874         (stale served, refresh started)
en  -> HIT    t=...984         (refreshed)
/c/varycookie -> no X-Astro-Cache; [WARN] Skipping cache ... because response includes Vary: Cookie.
```

Observations to design around:

1.  **The client receives no `Cache-Control`.** The runtime provider’s headers (`CDN-Cache-Control`, `Cache-Tag`) are stripped after the provider reads them, and nothing is added for browsers. Route caching here saves server work, not network round trips. If you want browsers or a downstream CDN to cache too, set `Cache-Control` yourself or use a CDN provider.
2.  **It is per process.** With N instances you have N caches, and `invalidate()` clears only the instance that handled the invalidating request. Memory caching is appropriate for a single process; with multiple replicas, use a CDN provider or accept short `maxAge`s and no reliance on instant invalidation.
3.  **The cache does not know about identity.** A request with a session cookie, an `Authorization` header or any cookie gets the *same cached response* as an anonymous one (I confirmed `Cookie: a=b` returned `HIT`). It never serves a response that sets a cookie, but a page that *reads* the session and personalizes the HTML will be cached for everyone if it declares a `maxAge`. This is the single most important rule of the chapter: **a route that renders per-user content must opt out** (`Astro.cache.set(false)`) or must not be matched by a route rule. Keep personal content in a server island, an endpoint, or a Svelte island fetched after load.

### The cache API

`Astro.cache` (pages) or `context.cache` (endpoints, middleware, actions) offers:

| Member | Behaviour |
|------------------------------------|------------------------------------|
| `enabled` | `true` only in production with a provider; `false` without one and in dev |
| `set(options \| false)` | Merge directives; `false` opts out |
| `options` | Read-only snapshot of the accumulated `{ maxAge, swr, etag, lastModified, tags }` |
| `tags` | Read-only array of accumulated tags |
| `invalidate({ tags } \| { path })` | Purge by tag or exact path; returns a promise |

In the 7.4.1 implementation `set()` and `invalidate()` also accept a *live collection entry* (Chapter 6): `cache.set(entry)` uses `entry.cacheHint`, and `cache.invalidate(entry)` invalidates its `cacheHint.tags`. That is how a live loader’s hints flow into response caching without manual plumbing; the documented forms are the options object and `false`.

```html
---
// src/pages/products/[slug].astro
export const prerender = false;
import { getLiveEntry } from 'astro:content';

const { slug } = Astro.params;
const { entry, error } = await getLiveEntry('inventory', slug!);
if (error || !entry) return Astro.rewrite('/404');

Astro.cache.set(entry);                       // adopt the loader's cacheHint (tags, lastModified)
Astro.cache.set({ maxAge: 300, swr: 60 });    // add freshness; tags from the hint are kept
---
```

#### Merge rules

Multiple calls in one request, from middleware, layouts, loaders and the page, merge as follows (verified in the implementation):

- `maxAge`, `swr`, `etag`: last write wins.
- `lastModified`: the most recent date wins.
- `tags`: accumulate (a set).
- `set(false)` disables caching for the request *and clears everything accumulated so far*; a later `set({...})` re-enables it with a fresh state.
- Config-level `routeRules` are applied first as the initial state, so code can override or extend them. In my test the page had rule tags `['products']` and called `set({ tags: ['p-a'] })`, yielding `options.tags = ['products', 'p-a']`.

#### `cache.enabled` and unconfigured behaviour

Without a provider, `cache.set()`, `cache.tags` and `cache.options` log a warning (once) and `cache.invalidate()` throws a `CacheNotEnabled` error. In development the cache object is a no-op whose `enabled` is `false`, so route code works unchanged. Guard provider-dependent work:

```html
---
if (Astro.cache.enabled) {
  Astro.cache.set({ maxAge: 3600, tags: await getProductTags(Astro.params.id!) });
}
---
```

To test caching you must `astro build` and run the server (or `astro preview`); the dev server never caches.

### Route rules

`routeRules` is a record from route pattern to cache options. Patterns use the file-routing syntax (`/about`, `/blog/[slug]`, `/docs/[...path]`) and the same priority rules, so more specific patterns win; globs (`*`) are not supported.

```js
routeRules: {
  '/api/[...path]': { swr: 600 },
  '/products/[...slug]': { maxAge: 3600, tags: ['products'] },
  '/blog/[...slug]': { maxAge: 300, swr: 60 },
},
```

Rules match on the request pathname (taking `base` and `trailingSlash` into account, as the implementation compiles them against both), and `[...slug]` also matches the bare parent (`/products` hit the `/products/[...slug]` rule in my test). Remember that a rule is a default, not a guarantee: a page may call `Astro.cache.set(false)`, and a rule without `maxAge` caches nothing on the memory provider.

### Invalidation

Tag invalidation removes every entry whose tags include any of the given tags; path invalidation is an exact match (no wildcards).

```ts
// src/actions/index.ts
import { defineAction, ActionError } from 'astro:actions';
import { z } from 'astro/zod';

export const server = {
  updateProduct: defineAction({
    accept: 'json',
    input: z.object({ id: z.string(), price: z.number().positive() }),
    handler: async ({ id, price }, ctx) => {
      if (!ctx.locals.user?.isAdmin) throw new ActionError({ code: 'FORBIDDEN' });
      await db.products.update(id, { price });
      await ctx.cache.invalidate({ tags: [`product:${id}`, 'product-list'] });
    },
  }),
};
```

`ActionAPIContext` retains `cache`, so actions can invalidate directly (verified: a `purge` action invalidated `products`, and the next request to `/products/zz` went from `HIT` to `MISS`). Design the tag vocabulary like a database schema: one tag per entity (`product:123`), one per collection page (`product-list`), and one per cross-cutting dependency (`navigation`, `prices`). Tags accumulate across layout, page and loader code, which means a page that renders a product list *and* the navigation naturally gets both tags if each part declares its own.

Because the memory provider is per process, invalidation by webhook from a CMS only works on the instance that receives it. In multi-instance deployments use a CDN provider whose purge API is global.

### CDN providers from the adapters (experimental)

Netlify, Vercel and Cloudflare each ship an *experimental* provider that must be enabled manually; the core route-caching API is stable, but these providers are explicitly in an experimental phase, and the plan is for adapters to enable them automatically later:

```js
// Netlify
import netlify from '@astrojs/netlify';
import { cacheNetlify } from '@astrojs/netlify/cache';
export default defineConfig({ adapter: netlify(), cache: { provider: cacheNetlify() } });

// Vercel
import vercel from '@astrojs/vercel';
import { cacheVercel } from '@astrojs/vercel/cache';
export default defineConfig({ adapter: vercel(), cache: { provider: cacheVercel() } });

// Cloudflare
import cloudflare from '@astrojs/cloudflare';
import { cacheCloudflare } from '@astrojs/cloudflare/cache';
export default defineConfig({ adapter: cloudflare(), cache: { provider: cacheCloudflare() } });
```

| Provider | Introduced in | Headers | Notes |
|------------------|------------------|------------------|------------------|
| `cacheNetlify()` | `@astrojs/netlify` 8.0 | `Netlify-CDN-Cache-Control`, `Netlify-Cache-Tag` | Uses the durable cache, shared across edge nodes |
| `cacheVercel()` | `@astrojs/vercel` 11.0 | `Vercel-CDN-Cache-Control`, `Vercel-Cache-Tag` | Tag invalidation is soft: entries are marked stale and revalidated in the background |
| `cacheCloudflare()` | `@astrojs/cloudflare` 14.0 | `Cloudflare-CDN-Cache-Control`, `Cache-Tag` | Enables Workers Cache with default settings |

Each provider auto-tags responses with the request path so that `invalidate({ path })` works on platforms with only tag-based purges. Because hits are served at the edge, your Astro code and middleware do not run on a hit. That is the whole point, but it also means logging, auth middleware and session cookies are bypassed for cached responses: the personalization rule above is even more important at a CDN.

### Writing a cache provider

A provider has a **config helper**, called in `astro.config.*`, returning `{ entrypoint, config }`, and a **runtime module** whose default export is a `CacheProviderFactory` receiving the serialized config and returning a `CacheProvider` with a `name`, and any of `setHeaders`, `onRequest` and `invalidate` (the reference documents `name` and `invalidate()` as required). The runtime module is bundled into the SSR output, so keep it runtime-agnostic.

Here is a CDN provider for a hypothetical service that uses `Surrogate-Control` and `Surrogate-Key` headers (the convention used by Fastly and similar CDNs). I built and ran it:

```js
// cdn/config.mjs
export function surrogateCache(options) {
  return { entrypoint: new URL('./runtime.ts', import.meta.url), config: options };
}
```

```ts
// cdn/runtime.ts
import type { CacheProviderFactory } from 'astro';
import {
  buildCacheControlDirectives,
  collectInvalidationTags,
  normalizeTags,
  pathTag,
  setConditionalHeaders,
} from 'astro/cache/provider-utils';

interface Config { serviceId: string; apiToken: string }

const factory: CacheProviderFactory = (config) => {
  const { serviceId, apiToken } = config as Config;
  return {
    name: 'surrogate-cdn',

    setHeaders(options, request) {
      const headers = new Headers();
      const control = buildCacheControlDirectives(options, ['public']);
      if (control) headers.set('Surrogate-Control', control);
      const tags = [...normalizeTags(options.tags), pathTag(new URL(request.url).pathname)];
      headers.set('Surrogate-Key', tags.join(' '));
      setConditionalHeaders(headers, options);
      return headers;
    },

    async invalidate(options) {
      const keys = collectInvalidationTags(options);
      if (keys.length === 0) return;
      const res = await fetch(`https://api.cdn.example/service/${serviceId}/purge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiToken}` },
        body: JSON.stringify({ surrogate_keys: keys }),
      });
      if (!res.ok) throw new Error(`Purge failed: ${res.status}`);
    },
  };
};

export default factory;
```

The response for `/products/a` under this provider, from the test server:

```text
surrogate-control: public, max-age=60, stale-while-revalidate=30
surrogate-key: products p-a astro-path:/products/a
```

The helpers from `astro/cache/provider-utils` (the same ones the first-party providers use):

- `buildCacheControlDirectives(options, extra?)` returns a directive string such as `public, max-age=300, stale-while-revalidate=60`, or `undefined` if there is nothing to say; each provider chooses its own header name.
- `pathTag(path)` returns `astro-path:<path>`.
- `setConditionalHeaders(headers, options)` sets `Last-Modified` and `ETag`.
- `collectInvalidationTags(options)` flattens tags and adds the path tag when `path` is given.
- `normalizeTags(tags)` returns a string array.

Authoring notes:

- When the provider has no `setHeaders`, Astro falls back to default `CDN-Cache-Control` and `Cache-Tag` headers. When it has only `setHeaders`, those headers stay on the response (the CDN consumes them); only runtime providers have `CDN-Cache-Control` and `Cache-Tag` removed after reading them.
- If `lastModified` or `etag` is present and there is no `Cache-Control`/`Expires`, Astro adds `Cache-Control: no-cache` so that clients must revalidate.
- `invalidate()` errors propagate to the caller. My test provider pointed at a non-existent host and the invalidating endpoint returned 500. Decide whether a failed purge should fail the request (usually it should be logged and retried).
- A runtime provider’s `onRequest` receives `{ request, url, waitUntil?, logger }` (the logger since 7.3). Use `waitUntil` for background revalidation on platforms that support it, and the context logger so messages follow the configured log handlers (Chapter 17). A runtime provider must decide for itself to skip responses with `Set-Cookie`; the built-in one does.
- Advanced routing (Chapter 5) exposes caching as a composable handler (`cache` from `astro/fetch` or `astro/hono`); a 7.x fix made it register the provider before rendering so `Astro.cache` is available to downstream handlers. If you reorder the pipeline, keep `cache()` before `pages()`.

### Interactions

**Sessions.** The cache and sessions pull in opposite directions. Reading the session does not set a cookie, but writing it does, and a response that sets a cookie is never stored by the memory provider (it logs `Skipping cache for /cart?w=1 because response includes Set-Cookie.`). Do not rely on that as a safety net: it protects against storing *Set-Cookie* responses, not against storing HTML personalized from a *read*. Rule of thumb: if the code path touches `session` or `locals.user` to decide what to render, do not cache the route; split the personalized part off.

**Cookies.** `Astro.cookies.set()` on a cached route disables storing that response on the memory provider. Cookies on *request* are ignored for the key, as noted, so never vary content on cookies in a cached route.

**Actions and endpoints.** Only `GET` is cached. Actions are `POST`, so they are never cached but are the natural place to invalidate (`ctx.cache.invalidate`).

**Server islands.** A server island is fetched with `GET /_server-islands/<Name>?e=<export>&p=<encrypted props>&s=<encrypted slots>` (note the hyphen in the path; see Chapter 9) and is rendered by the same pipeline, so it has its own `Astro.cache`. I confirmed that a deferred component calling `Astro.cache.set({ maxAge: 30 })` is cached independently of the surrounding page: the second fetch of the island URL returned `HIT` with the same timestamp. The cache key is the island URL, which includes the encrypted props, so identical props share one entry. This gives a powerful composition for personalization:

```html
---
// src/pages/shop.astro  (cacheable shell)
import Header from '../components/Header.astro';
Astro.cache.set({ maxAge: 300, tags: ['shop'] });
---
<html>
  <body>
    <Header server:defer><span slot="fallback">Sign in</span></Header> <!-- personalized, not cached -->
    <!-- ... cached product grid ... -->
  </body>
</html>
```

The shell is cached and the header is a separate, uncached request that reads the session. Because the island request is a normal request to your server (with cookies), `Astro.session` works inside it; the island must not set a `maxAge` or it would share personalized HTML. Two caveats: when the encrypted query exceeds the URL length limit Astro switches to `POST`, which is not cacheable, and `Astro.url` inside the island is the island endpoint (use the `Referer` for the page, Chapter 9).

**Svelte islands.** Hydrated components can only influence caching indirectly: a client-side `fetch()` to a cached endpoint is answered from the cache (and endpoints can set `context.cache` directives like pages can). Remember that cached HTML embeds island props: a prop computed from request data becomes part of the shared response.

**Live collections.** Loaders return `cacheHint` data (tags, `lastModified`); `cache.set(entry)` adopts it, and `cache.invalidate(entry)` invalidates by its tags, so a CMS webhook can purge exactly the pages that rendered that entry.

**Prerendered routes and build output.** Route caching applies only to on-demand routes. A route with `prerender = true` is a static file; use your host’s static caching for it.

### A decision checklist

1.  Is the response identical for every visitor? If not, do not cache it, or split the personalized part into a server island or an endpoint.
2.  Is there more than one server process? If yes, memory cache is per-instance; prefer a CDN provider or short TTLs.
3.  What invalidates it? Name the tags before you write `maxAge`.
4.  Is `swr` acceptable? Stale content is served once; a long `swr` plus slow revalidation hides errors for a while.
5.  Did you test the built server, not `astro dev`? Look for `X-Astro-Cache` (memory provider) or the vendor headers.

## Key takeaways

- Sessions store data server-side under a UUID cookie. Anonymous requests cost nothing: no cookie means no storage read, and the cookie is created on the first `set()`.
- The Node adapter’s default filesystem driver is not shared between instances and lives in `node_modules/.astro/sessions`; Cloudflare uses KV, Netlify uses Blobs, and Vercel needs an explicit driver.
- Configure drivers with `sessionDrivers.*` or `{ entrypoint, config }`; the string-plus-`options` form is deprecated. Use an entrypoint when configuration must come from the runtime environment.
- `session.set()` stores a clone: mutate first, then set. Values must be devalue-serializable. `regenerate()` is async in practice; call it on login and `destroy()` on logout.
- `ttl` hides expired values lazily; reclamation is the driver’s job. Session cookies are `httpOnly`, `Secure` in production, and forged IDs are replaced.
- Without configured storage `Astro.session` is `undefined` and reading it logs a warning (the changelog’s “always defined” wording describes the accessor); `session: false` also removes the runtime from the bundle.
- Protect routes with `context.routePattern`, not `url.pathname`, and still authorize in each handler; the BFF pattern keeps tokens in the session and out of islands.
- Route caching is stable in 7.x: directives (`maxAge`, `swr`, `tags`, `etag`, `lastModified`) are merged (scalars last-write-wins, tags accumulate), `set(false)` opts out, and `routeRules` supply defaults without globs.
- `memoryCache()` is a per-process LRU for GET requests; it ignores cookies in keys, honours `Vary` (except `Cookie` and `*`), refuses `Set-Cookie` responses, serves `STALE` while revalidating, and gives browsers no `Cache-Control`.
- Never cache personalized output. Use server islands, which are separately cacheable requests, for the personal part of an otherwise cacheable page.
- Adapter CDN providers (`cacheNetlify`, `cacheVercel`, `cacheCloudflare`) are experimental and opt-in; custom providers implement `setHeaders`, `onRequest` and `invalidate`, with helpers in `astro/cache/provider-utils`.

## Review Questions

1.  What is stored in the session cookie, and where does the session data live?

2.  Which three Astro adapters configure a default session driver, and what is each driver? What must you do on Vercel?

3.  Why is the Node adapter’s default session driver a poor choice for a containerized, multi-replica deployment?

4.  Find the bug:

    ```ts
    const cart = (await session.get('cart')) ?? [];
    session.set('cart', cart);
    cart.push(sku);
    ```

5.  A project sets `session: false`. A page runs `const c = await Astro.session?.get('cart')`. What is `c`, and what appears in the server log?

6.  The API reference and the 7.0.0 changelog appear to disagree about whether `Astro.session` is “undefined” or “always defined” when sessions are not configured. How do you reconcile them, and how did the behaviour look in a test?

7.  Multiple choice. In Astro 7.4.1, when is the session cookie first set?

    a.  On the first request that has no cookie.
    b.  On the first `session.get()`.
    c.  On the first `session.set()` (or `regenerate()`/`load()`).
    d.  At the end of every request.

8.  Why must a login handler call `await session.regenerate()`, and what does `regenerate()` do to existing data?

9.  You configure `session: { driver: sessionDrivers.redis({ url: process.env.REDIS_URL }) }` and deploy the same build to staging and production with different `REDIS_URL` values. What goes wrong, and how do you fix it?

10. What is the difference between `session.ttl` (or `set(key, value, { ttl })`) and a Redis driver’s own `ttl` option? Which actually frees storage?

11. A browser sends `Cookie: astro-session=11111111-1111-4111-8111-111111111111`, but storage has no such session. What does Astro do?

12. Two concurrent requests from the same browser both run `get('cart')`, push an item and `set('cart', ...)`. Describe the possible outcome and a better design for inventory-like state.

13. Why might `session.set('user', someClassInstance)` throw, and where does the error surface?

14. The default cookie is documented as `secure: true`, yet it works on `http://localhost` in development. Why, and what is the production implication behind a TLS-terminating proxy?

15. What is wrong with this middleware, and what would you use instead?

    ```ts
    if (context.url.pathname.startsWith('/admin') && !context.locals.user) return context.redirect('/login');
    ```

16. In a BFF design, where are the access and refresh tokens stored, and why is that safer than keeping them in a Svelte island’s state?

17. How do route-level `Astro.cache.set()` calls and `routeRules` combine when the rule says `{ maxAge: 3600, tags: ['products'] }` and the page calls `set({ maxAge: 60, tags: ['p-7'] })`? Give the resulting options.

18. What does `Astro.cache.set(false)` do to previously accumulated options and to later calls?

19. Multiple choice. Which request is never stored by `memoryCache()`?

    a.  A GET with a query string.
    b.  A GET whose response sets a cookie.
    c.  A GET with `Vary: Accept-Language`.
    d.  A GET that sends a `Cookie` header.

20. A page calls `Astro.cache.set({ tags: ['news'] })` and nothing else, with the memory provider. Is it cached? Why or why not?

21. Explain what `X-Astro-Cache: STALE` means and when it is returned.

22. A page that reads `Astro.locals.user` to render a greeting has the rule `'/[...path]': { maxAge: 60 }` applied. Describe the failure mode and give two fixes.

23. Your site runs three Node instances behind a load balancer with `memoryCache()`. A CMS webhook calls an endpoint that runs `cache.invalidate({ tags: ['post:5'] })`. What actually happens, and what are your options?

24. Why does `?utm_source=newsletter` not create a separate cache entry with the memory provider, and how would you change that?

25. What does `Astro.cache.enabled` return in `astro dev`, and how do you test caching locally?

26. What is the difference in responsibility between a runtime provider and a CDN provider? Which hook does each implement, and who strips the cache headers?

27. In the surrogate-key provider shown, why is the path tag added in `setHeaders`, and what does `collectInvalidationTags({ path: '/a' })` return?

28. A server island component sets `Astro.cache.set({ maxAge: 30 })` and reads `Astro.session`. What problem is this, and how should the island and the page be arranged?

29. Where would you put session writes relative to streaming (first byte sent) and why?

30. The adapter CDN providers are documented as experimental while route caching is stable. What does that mean for adoption, and what must you do to use one?
