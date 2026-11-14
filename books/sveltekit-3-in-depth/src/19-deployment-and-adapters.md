# Chapter 18: Deployment and Adapters

SvelteKit builds an app in two phases. Vite produces a platform-neutral production build of your server code, client code and service worker, running prerendering along the way. An adapter then takes that build and reshapes it for a target: a Node process, a Bun binary, a directory of static files, a Cloudflare Worker, a set of Netlify or Vercel functions. The adapter boundary is why the same `+page.server.ts` can run in a container on Cloud Run today and on Workers tomorrow. It is also where most deployment surprises originate: environment variables, request origin, client IP, file access, runtime limits and cache layers behave differently per target.

This chapter covers the adapter model and the `Adapter` and `Builder` APIs, each official adapter with the SvelteKit 3 changes that matter (Vercel Edge removed, Cloudflare platform changes, adapter-bun made official, `ORIGIN` replaced by `paths.origin`), container deployment with health checks and graceful shutdown, writing your own adapter (I built and ran the one shown below against SvelteKit 3.1.0), and a decision matrix. Package versions at the time of writing, from `npm view`: adapter-node 6.0.0, adapter-bun 1.0.0, adapter-static 4.0.0, adapter-cloudflare 8.0.1, adapter-netlify 7.0.1, adapter-vercel 7.0.1, adapter-auto 8.0.0.

## The adapter model

### Where adapters plug in

You register an adapter in the plugin options in `vite.config.ts`. There is no `svelte.config.js` in SvelteKit 3.

```ts
// vite.config.ts
import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-node';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [sveltekit({ adapter: adapter() })]
});
```

`npx sv add sveltekit-adapter="adapter:node"` (or `:static`, `:cloudflare`, `:netlify`, `:vercel`, `:bun`) installs the package and edits the config.

`vite build` builds the client, the server and the service worker, prerenders using the server build, then calls the adapter’s `adapt(builder)`. Intermediate output lives in `.svelte-kit/output/{client,server,prerendered}`. `vite preview` always runs in Node and does not reproduce adapter-specific behaviour (the docs say so for the `platform` object).

### The `Adapter` interface

```ts
interface Adapter {
    name: string;                                  // required
    adapt(builder: Builder): MaybePromise<void>;   // required
    emulate?(): MaybePromise<Emulator>;
    supports?: {
        read?(opts: { config: any; route: { id: string } }): boolean;
        instrumentation?(): boolean;
    };
    vite?: AdapterViteConfig | ((ctx: { config: ValidatedConfig }) => AdapterViteConfig);
}
```

- `adapt` does the real work.
- `emulate` returns an object whose `platform({ config, prerender })` result becomes `event.platform` during dev, build and preview. This is how Cloudflare bindings work locally. Its shape is what you declare as `App.Platform`.
- `supports.read` tells SvelteKit whether `read(asset)` from `$app/server` works in production for a route. Return `false`, or throw a descriptive error. The “no `fs` here, use `read`” advice on several platforms rests on this.
- `supports.instrumentation` says whether `instrumentation.server.js` can be loaded (Chapter 17). adapter-node returns `true`.
- `vite` (new in 3.0) lets an adapter override how Vite’s dev and preview servers convert `IncomingMessage` to `Request` (`getRequest`) and write a `Response` (`setResponse`), for example to handle WebSockets, and inject Vite plugins `pre` or `post` SvelteKit’s own. In 3.0 `getRequest` and `setResponse` from `@sveltejs/kit/node` became synchronous.

### `adapter-auto`

New projects default to `adapter-auto`, which detects Cloudflare, Netlify or Vercel at build time and installs and runs the matching adapter; the docs also map Cloud Run and Render to `adapter-node`. It takes no options, so `isr` on Vercel, `split` on Netlify or `platformProxy` on Cloudflare need the real adapter. Installing at build time is slower and keeps the adapter out of your lockfile; the docs recommend replacing it once you settle on a target. Treat it as scaffolding.

### Platform context

Adapters may expose data on `event.platform` (Cloudflare context in the older API, Netlify `context`, the Bun server). Type it through `App.Platform` in `src/app.d.ts`. Code touching `event.platform` is non-portable by definition; keep it in one module such as `#lib/server/platform.ts` so a platform change is a one-file change.

## adapter-node

The most general target, and the one most production deployments use.

### Output and what to deploy

With defaults the build lands in `build/`. To run it you need that directory, `package.json` and production dependencies in `node_modules`: copy `package.json` and the lockfile, run `npm ci --omit dev`, then `node build`. Packages in `devDependencies` are bundled into the server by Rolldown; packages in `dependencies` stay external. That is the lever. Put native modules, instrumented libraries (Chapter 17) and anything reading its own files in `dependencies`; keep the rest in `devDependencies` for a smaller runtime image.

I built a project with adapter-node 6.0.0 and SvelteKit 3.1.0. `build/` contains `index.js` (starts the server), `handler.js` (for custom servers), `adapter-node.js`, `client/` and `server/`. With `precompress: true` (the default) every client asset has `.br` and `.gz` siblings. Requesting a hashed entry file with `Accept-Encoding: br` returned:

```text
HTTP/1.1 200 OK
etag: "IKD2pWQb...U6NCQoj0.br"
vary: Accept-Encoding
cache-control: public,max-age=31536000,immutable
content-encoding: br
content-type: text/javascript
```

So assets are served from a table computed at build time (no filesystem probing per request), GET and HEAD only, each encoding has its own ETag, and everything under `_app/immutable/` is immutable for a year.

### Compression

Precompression covers static assets only. Compress dynamic responses at the reverse proxy or load balancer, because Node is single-threaded and compression is CPU work. If you add middleware in a custom server, use `@polka/compression`: SvelteKit streams responses, and the popular `compression` package does not support streaming and may cause errors.

### Environment variables

In `dev` and `preview` Vite loads `.env`, `.env.local` and `.env.[mode]`. In production `.env` files are not loaded; use Node’s flag:

```bash
node --env-file=.env build
```

With the explicit env system (Chapter 13), variables declared in `src/env.ts` are validated at startup, so a missing `DATABASE_URL` kills the process immediately instead of failing on the first request. Combined with a health check, the orchestrator never routes traffic to a misconfigured instance.

| Variable | Default | Purpose |
|------------------------|------------------------|------------------------|
| `PORT` | `3000` | TCP port |
| `HOST` | `0.0.0.0` | Bind address |
| `SOCKET_PATH` | none | Unix socket; `HOST` and `PORT` ignored |
| `PROTOCOL_HEADER`, `HOST_HEADER`, `PORT_HEADER` | none | Trusted-proxy headers carrying public protocol, host, port |
| `ADDRESS_HEADER`, `XFF_DEPTH` | none | Client-IP header; number of trusted proxies for `X-Forwarded-For` |
| `BODY_SIZE_LIMIT` | `512K` | Max body including streaming; `K`/`M`/`G`; `Infinity` disables |
| `SHUTDOWN_TIMEOUT` | `30` | Seconds before connections are force-closed |
| `IDLE_TIMEOUT` | unset | With socket activation, idle seconds before sleeping |
| `KEEP_ALIVE_TIMEOUT`, `HEADERS_TIMEOUT` | Node defaults | Seconds |
| `LISTEN_PID`, `LISTEN_FDS` | set by systemd | Socket activation, never prefixed |

`ORIGIN` no longer exists in 3.x. The adapter’s `envPrefix` option prefixes all of these except the systemd variables: with `envPrefix: 'MY_CUSTOM_'`, `PORT` becomes `MY_CUSTOM_PORT`.

### The origin problem and `paths.origin`

SvelteKit needs the public URL for `url.origin`, redirects, CSRF checks (Chapter 15) and `resolve()`. Behind a proxy HTTP does not tell it reliably. In adapter-node 3.x:

- If `paths.origin` is set, it is the trusted self-origin for CSRF checks on form submissions and remote calls, and the `url.origin` during prerendering.
- Otherwise the origin comes from the request: the `host` header, `https` unless `PROTOCOL_HEADER` says otherwise, and `PORT_HEADER` if set.

Two setups cover nearly everything. A proxy that forwards the host and scheme:

```bash
PROTOCOL_HEADER=x-forwarded-proto HOST_HEADER=x-forwarded-host node build
```

Or pin a canonical origin:

```ts
// vite.config.ts
import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-node';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [
        sveltekit({
            adapter: adapter(),
            paths: { origin: process.env.PUBLIC_ORIGIN }
        })
    ]
});
```

That value is read when the config is evaluated, which for a production image means at build time. If you build one image and promote it across hostnames, do not bake `paths.origin`; use the header variables. The classic symptom of a wrong origin is “Cross-site POST form submissions are forbidden” on every form.

> **Warning:** Set `PROTOCOL_HEADER`, `HOST_HEADER`, `PORT_HEADER` and `ADDRESS_HEADER` only when the server is reachable solely through a proxy you control that overwrites those headers. On a directly reachable server any client can spoof origin and IP, defeating CSRF protection and IP-based limits.

### Client IP and `XFF_DEPTH`

`event.getClientAddress()` returns the socket address by default, which behind a load balancer is the balancer. Set `ADDRESS_HEADER` to a header your edge controls. For `X-Forwarded-For`, a comma-separated chain, set `XFF_DEPTH` to the number of trusted proxies; SvelteKit reads from the right, skipping that many hops, because left-most entries are client-controlled. With three trusted proxies use `XFF_DEPTH=3`. Rate limiting (Chapter 14) is only as trustworthy as this configuration.

### Graceful shutdown

On `SIGTERM` or `SIGINT`, adapter-node (1) stops accepting new connections, (2) lets in-flight requests finish and closes connections as they go idle, (3) after `SHUTDOWN_TIMEOUT` seconds force-closes the rest. Then it emits `sveltekit:shutdown` on `process` with `reason` of `SIGINT`, `SIGTERM` or `IDLE`. Unlike `exit`, listeners may be async, and the event fires once all connections are closed even if you hold dangling resources such as a database pool:

```ts
// src/hooks.server.ts
import { db } from '#lib/server/db.js';
import { jobs } from '#lib/server/jobs.js';

process.on('sveltekit:shutdown', async (reason) => {
    await jobs.stop();
    await db.end();
    console.info(`shutdown complete (${reason})`);
});
```

Align timings with the orchestrator: Kubernetes’ `terminationGracePeriodSeconds` must exceed `SHUTDOWN_TIMEOUT` plus cleanup. Long-lived connections (`query.live`, SSE, streams) count as in flight, so each deploy can wait the full timeout; tune it down if you use them.

### Systemd socket activation

For VMs, systemd passes `LISTEN_PID` and `LISTEN_FDS` and the adapter listens on file descriptor 3. With `IDLE_TIMEOUT=60` the process exits after 60 idle seconds (reason `IDLE`) and systemd restarts it on the next connection: scale to zero on one host. Only a single socket is accepted.

```ini
# /etc/systemd/system/myapp.service
[Service]
Environment=NODE_ENV=production IDLE_TIMEOUT=60
ExecStart=/usr/bin/node /usr/bin/myapp/build
```

```ini
# /etc/systemd/system/myapp.socket
[Socket]
ListenStream=3000

[Install]
WantedBy=sockets.target
```

### Custom server

`build/handler.js` exports a handler for Express, Polka, Connect or `http.createServer`:

```js
// my-server.js
import { handler } from './build/handler.js';
import express from 'express';

const app = express();

// Outside SvelteKit: no `handle`, no tracing, no auth
app.get('/healthz', (_req, res) => res.end('ok'));

// SvelteKit serves everything else, including static assets and prerendered pages
app.use(handler);

app.listen(Number(process.env.PORT ?? 3000), '0.0.0.0');
```

With a custom server only the handler’s variables take effect: `PROTOCOL_HEADER`, `HOST_HEADER`, `PORT_HEADER`, `ADDRESS_HEADER`, `XFF_DEPTH`, `BODY_SIZE_LIMIT`. The lifecycle variables (`PORT`, `HOST`, `SOCKET_PATH`, `SHUTDOWN_TIMEOUT`, `IDLE_TIMEOUT`, keep-alive timeouts, systemd variables) belong to `node build` only, and graceful shutdown is yours to implement. Also, the instrumentation facade wraps the adapter’s `index.js`; with your own entry, load instrumentation yourself, for example `node --import ./instrument.js my-server.js`.

### Health checks

Two designs. A SvelteKit route is easy but passes through `handle`, so auth, rate limits and tracing run on it; exempt it early. A route outside SvelteKit in a custom server proves only that Node is up.

```ts
// src/routes/healthz/+server.ts
import type { RequestHandler } from './$types';
import { db } from '#lib/server/db.js';

export const prerender = false;

export const GET: RequestHandler = async ({ url }) => {
    const headers = { 'cache-control': 'no-store' };

    // Liveness: process up, event loop turning
    if (url.searchParams.get('deep') !== '1') return new Response('ok', { headers });

    // Readiness: dependencies reachable, bounded by a timeout
    try {
        await Promise.race([
            db.ping(),
            new Promise((_, reject) => setTimeout(() => reject(new Error('db timeout')), 1000))
        ]);
        return Response.json({ status: 'ready' }, { headers });
    } catch {
        return Response.json({ status: 'degraded' }, { status: 503, headers });
    }
};
```

```ts
// in your auth handle in src/hooks.server.ts
if (event.url.pathname === '/healthz') return resolve(event);
```

Liveness should not check dependencies (a database outage must not make the orchestrator restart every web instance); readiness should, with a short timeout. This is general operations practice, not SvelteKit-specific (author practice).

### Containers

```dockerfile
# Dockerfile
FROM node:24-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA
RUN npm run build

FROM node:24-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

FROM node:24-slim
ENV NODE_ENV=production
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY --from=build /app/build ./build
COPY package.json ./
USER node
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s \
  CMD node -e "fetch('http://127.0.0.1:3000/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "build"]
```

`GIT_SHA` is meant to feed `version.name` in `vite.config.ts` so skew detection and telemetry share a build identifier. SvelteKit 3 needs Node 22.17+; `node:24-slim` also meets the synchronous loader requirement from Chapter 17. Run as a non-root user. For signal handling and zombie reaping add `--init` (Docker), `init: true` (Compose) or tini if you spawn children. Pass configuration at run time so one image promotes through environments, except variables declared `static: true` in `src/env.ts`, which are inlined at build and must exist in the build stage (Chapter 13).

### Reverse proxy sketch

```nginx
location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;  # overwrite for a single trusted hop
    proxy_buffering off;                             # streaming and live queries
    proxy_read_timeout 1h;
}
```

with `PROTOCOL_HEADER=x-forwarded-proto ADDRESS_HEADER=x-forwarded-for XFF_DEPTH=1`. Buffering would hold streamed `load` promises and `query.live` updates until the end. Nginx’s body limit (1 MB by default) and `BODY_SIZE_LIMIT` (512K) are independent; raise both for uploads. The SvelteKit limit also applies while streaming, protecting against clients that misstate `Content-Length`.

## adapter-bun

Official in SvelteKit 3. It builds a standalone `Bun.serve` server, requires Bun 1.4+, and calls Bun’s build API, so the build itself must run under Bun:

```bash
bun run --bun build   # --bun overrides Vite's Node shebang
bun ./build
```

- Install production dependencies with `bun install --production --frozen-lockfile`; `devDependencies` are bundled, `dependencies` externalised (the same lever as adapter-node).
- Client assets and prerendered output become native Bun routes: GET and HEAD only, build-time ETags, empty `304` for conditional requests, `immutable` files get the one-year header. Filenames containing a literal `*` are rejected, since Bun treats it as a wildcard.
- Options: `out`, `precompress` (ignored with `compile`), `envPrefix` (startup fails on unknown variables with that prefix, catching typos), `serverOptions` (JSON-serialisable `Bun.serve` defaults: `hostname`, `port`, `unix`, `reusePort`, `ipv6Only`, `idleTimeout`, `maxRequestBodySize`, `development`; env vars win) and `buildOptions` for executables.
- `compile: true` writes one executable at `<out>/server` embedding code, assets and the Bun runtime. `compile` may be a target string or an object (`outfile`, `target: 'bun-linux-x64'`). Executables bundle production dependencies; packages that read files relative to themselves, such as `jsdom`, must be in `external` with `compile: { autoloadPackageJson: true }`.
- Variables: `HOST`, `PORT`, `SOCKET_PATH`, `REUSE_PORT`, `IPV6_ONLY`, `BODY_SIZE_LIMIT` (`512K`), `DEVELOPMENT`, `SHUTDOWN_TIMEOUT` (30) and `CONNECTION_IDLE_TIMEOUT` (0 to 255, `0` disables). The idle name differs from adapter-node’s `IDLE_TIMEOUT` on purpose, since that one means shut down when idle. The handler disables the timeout for `text/event-stream` responses and adds `X-Accel-Buffering: no`.
- Stricter origin default: the scheme is assumed `https` unless `PROTOCOL_HEADER` or `paths.origin` says otherwise. Invalid header values produce `400`. `XFF_DEPTH` defaults to `1`, and `getClientAddress()` throws if the configured header is missing or has too few addresses.
- `event.platform.server` is the Bun server (`id`, `pendingRequests`, `pendingWebSockets`).
- Shutdown: `server.stop()`, wait for pending requests, emit `sveltekit:shutdown` with the signal name, force-close after `SHUTDOWN_TIMEOUT`; a second signal exits with status 1.

Chapter 17’s `import-in-the-middle` story is Node-oriented; verify your observability stack on Bun before committing.

## adapter-static

Prerenders the whole site to files (Chapter 11).

```ts
// vite.config.ts
import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-static';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [
        sveltekit({
            adapter: adapter({
                pages: 'build',
                assets: 'build',
                fallback: undefined,
                precompress: false,
                strict: true
            })
        })
    ]
});
```

```ts
// src/routes/+layout.ts
export const prerender = true;
```

- `strict: true` fails the build if any page or endpoint was not prerendered and no `fallback` is set, preventing a site with unreachable routes.
- If your host does not serve `/a.html` for `/a`, set `trailingSlash = 'always'` to emit `/a/index.html`.
- `ssr` must not be `false`, or prerendering writes an empty shell.
- Actions, `url.searchParams` and remote `form`/`command` do not fit a static site (they need a server).
- On Vercel, omit the options so the adapter picks the optimal configuration.
- `precompress` writes `.br` and `.gz`; useful only if your host serves them rather than compressing itself.

### SPA fallback

`fallback: '200.html'` (name depends on the host) emits a page from `app.html` that boots the client router for any non-prerendered URL. It is distinct from `ssr = false`: `ssr` decides how a route renders, `fallback` decides what file answers unknown URLs. To serve most of an app as an SPA, set `export const ssr = false` in the root layout and opt marketing pages back in with `prerender = true; ssr = true`. The fallback always uses absolute asset paths regardless of `paths.relative`. Avoid `index.html` as the name so it does not collide with the prerendered home page. SPA mode has the round-trip and SEO costs described in Chapter 16; accept them for apps in a mobile shell or behind login. On Apache, rewrite unknown paths to the fallback with `static/.htaccess`.

### GitHub Pages

The site lives under `/repo/`, so set `paths.base` (not needed for `user.github.io` repos), generate `404.html`, and add `.nojekyll` to `static/` if publishing from a branch:

```ts
// vite.config.ts
import process from 'node:process';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [
        sveltekit({
            adapter: adapter({ fallback: '404.html' }),
            paths: { base: process.argv.includes('dev') ? '' : process.env.BASE_PATH }
        })
    ]
});
```

Write every internal link with `resolve()` from `$app/paths`; the `base` and `assets` exports are gone in 3.0. The docs’ Actions workflow sets `BASE_PATH` from `actions/configure-pages` and uploads `build/` with `include-hidden-files: true` so `.well-known` survives.

## adapter-cloudflare

Targets Workers (with Static Assets) and Pages and supports all SvelteKit features. `adapter-cloudflare-workers` (Workers Sites) is deprecated: migrate by switching package, removing `site` from the Wrangler config and adding `assets.directory` and `assets.binding`.

```ts
adapter({
    config: undefined,        // Wrangler config path if not wrangler.jsonc/json/toml
    platformProxy: { configPath: undefined, environment: undefined, persist: undefined },
    fallback: 'plaintext',    // 'plaintext' | 'spa'
    routes: { include: ['/*'], exclude: ['<all>'] } // Pages only
})
```

- `platformProxy` configures emulated local bindings (Wrangler’s `getPlatformProxy` options).
- `fallback` governs unmatched asset requests. Use `spa` if you hand-exclude prerendered pages from `routes.exclude` and do not want an unstyled 404. For Workers, Wrangler’s `assets.not_found_handling` takes precedence: `"404-page"` serves that page, `"single-page-application"` forces a SPA fallback regardless.
- `routes` (Pages) customises `_routes.json`. `exclude` routes skip the function, which is faster and cheaper, with special values `<build>`, `<files>`, `<redirects>`, `<prerendered>`, `<all>`. Include plus exclude is capped at 100 rules; if prerendered paths exceed that, write wildcards like `/articles/*`.

Workers configuration:

```json
// wrangler.jsonc
{
    "name": "my-app",
    "main": ".svelte-kit/cloudflare/_worker.js",
    "compatibility_flags": ["nodejs_als"],
    "compatibility_date": "2026-10-01",
    "assets": { "binding": "ASSETS", "directory": ".svelte-kit/cloudflare" }
}
```

`nodejs_als` enables only `AsyncLocalStorage`, which `getRequestEvent()` needs; use `nodejs_compat` for broader Node APIs. Deploy with `npx wrangler deploy` or Git integration. For Pages use build output directory `.svelte-kit/cloudflare`. A Pages `/functions` directory is not deployed; write `+server` routes, which compile into one `_worker.js`.

### Platform changes in 3.0

In 3.x `env` and `waitUntil` come from the `cloudflare:workers` module, `cf` is on `request.cf`, and `caches` is the global. Install `wrangler` (4.x) and run `wrangler types` for binding types.

```ts
// src/routes/api/notes/+server.ts
import { env } from 'cloudflare:workers';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async () => {
    const { results } = await env.DB.prepare('select id, title from notes').all(); // illustrative D1 binding
    return Response.json(results);
};
```

Prefer `$app/env/*` for configuration and `cloudflare:workers` for bindings. Constraints: no `fs` (use `read`, which fetches from deployed static assets, or prerender); Durable Objects and Workflows, which need custom classes exported from the worker, are not supported by the adapter (deploy a separate worker and bind to it); the bundle must fit the Worker size limit after minification; `_headers` and `_redirects` affect only static asset responses, so set dynamic headers in `handle`. Test the real build with `wrangler dev .svelte-kit/cloudflare/_worker.js` (Workers) or `wrangler pages dev .svelte-kit/cloudflare` (Pages).

## adapter-netlify

```ts
adapter({ edge: false, split: false, publish: 'build' })
```

`edge: true` deploys as a Netlify Edge Function (no `fs`, es2022 target); most apps should stay on the default Node function. `split: true` creates several functions instead of one; measure before enabling. `publish` is where static assets and prerendered pages go. The adapter uses the Netlify Frameworks API (CLI 17.31+) and exposes `event.platform.context`. `_headers`, `_redirects` and `[[redirects]]` in `netlify.toml` apply to static responses. Netlify Forms require the form page to be prerendered, because Netlify’s build bot parses output HTML (`prerender = true` on the page, or `prerender.force`). Use `read` for file access.

## adapter-vercel

```ts
adapter({ runtime: 'nodejs24.x', regions: ['iad1'], split: false, memory: 1024, maxDuration: 15 })
```

**The Edge runtime was removed in 3.0.** `runtime` is `'nodejs22.x'`, `'nodejs24.x'` or `'bun1.x'`; by default the adapter uses the build’s runtime, following the project’s Node version in the dashboard. A route that used `runtime: 'edge'` must move to a Node runtime; if latency matters, lean on the CDN, ISR or prerendering. Old projects may default to a Node version too old for SvelteKit 3; change it in project settings.

Settings can go in the adapter call or in `export const config` of `+server`, `+page(.server)` and `+layout(.server)`, inherited down the tree:

```ts
// src/routes/reports/+page.server.ts
import type { Config } from '@sveltejs/adapter-vercel';

export const config: Config = {
    split: true,        // its own function
    memory: 2048,
    maxDuration: 60,
    regions: ['fra1']   // co-locate with the database; multi-region needs Enterprise
};
```

Remember Chapter 11: `config` merges at top level only, and a universal `config` beats a server one.

### ISR

```ts
// src/routes/blog/[slug]/+page.server.ts
import { BYPASS_TOKEN } from '$app/env/private';
import type { Config } from '@sveltejs/adapter-vercel';

export const config: Config = {
    isr: { expiration: 60, bypassToken: BYPASS_TOKEN, allowQuery: ['page'] }
};
```

`expiration` (seconds, or `false` for never) is required. `bypassToken` (at least 32 characters, fixed at build time) enables Draft Mode (cookie `__prerender_bypass=<token>`) and on-demand revalidation (`GET` or `HEAD` with `x-prerender-revalidate: <token>`). `allowQuery` lists query parameters that form the cache key; others are ignored. ISR on a prerendered route has no effect. Use ISR only where every visitor sees identical content; anything driven by a session cookie leaks across users (for example, user A’s name rendered into HTML that is then served to B).

`BYPASS_TOKEN` is imported from `$app/env/private`, so declare it in `src/env.ts`. Vercel system variables describe the deployment, so their build-time values remain correct at run time, and some of them are not available to functions at run time at all. The adapter documentation therefore says to declare them `static: true`, which inlines them (and enables dead-code elimination):

```ts
// src/env.ts
import { defineEnvVars } from '@sveltejs/kit/env';

export const variables = defineEnvVars({
    BYPASS_TOKEN: { static: true, description: 'Vercel ISR bypass token' },
    VERCEL_GIT_COMMIT_SHA: { static: true, description: 'Deployed commit' }
});
```

### Skew protection

SvelteKit detects skew-induced errors and hard-reloads (losing client state); you can get ahead with `updated.current`. Vercel’s skew protection routes a user’s requests to their original deployment via a cookie until they reload; `updated.current` is exempted so it still sees new deployments. With several tabs on different versions, older tabs get routed to the newer deployment and fall back to SvelteKit’s mitigation. Enable it under Advanced project settings. Also: `images` configures Vercel Image Optimization; use `@vercel/functions` for `waitUntil`; a root `api/` directory shadows `/api/*`, so write endpoints as `+server` routes; and use `read` rather than `node:fs`.

## Containers on managed platforms

Cloud Run and Render are adapter-node targets. The following platform behaviours come from the vendors, not the SvelteKit docs; confirm current values.

- **Port.** Both inject `PORT` and expect `0.0.0.0`, which adapter-node does by default.
- **TLS and origin.** TLS terminates at the platform proxy. Set `PROTOCOL_HEADER=x-forwarded-proto` and `HOST_HEADER=x-forwarded-host`, or pin `paths.origin`, or forms fail the CSRF check.
- **Shutdown window.** Cloud Run’s `SIGTERM` grace period is short (about ten seconds when I last checked). Set `SHUTDOWN_TIMEOUT` below it, for example `8`, so `sveltekit:shutdown` cleanup and telemetry flush finish before `SIGKILL`.
- **Statelessness.** Module-level state is per instance (Chapter 12); use shared stores.
- **Cold starts.** `src/env.ts` validation and `init` run at start; keep them cheap.
- **Skew during rollouts.** Old and new versions serve concurrently. Set `version.name` to the commit, keep endpoint and remote-function changes backward compatible across one deploy, and serve hashed assets from a CDN or store that retains old versions, or clients request chunks the new image lacks. On containers this is yours to solve.
- **Health checks.** Readiness at `/healthz?deep=1`, liveness at `/healthz`.

## Writing your own adapter

From the docs, `adapt(builder)` should clear the output directory; write output with `writeClient`, `writeServer` and `writePrerendered`; emit code that imports the server instance from `generateServerInstance`, runs `await server.init({ env, read })`, converts platform requests to `Request`, calls `server.respond(request, { getClientAddress, platform })` and returns the `Response`; bundle if the target cannot install dependencies; and place static files where the platform expects them. Put final output under `build/` and intermediates under `.svelte-kit/[adapter-name]`.

### The Builder API (3.x)

| Member | Purpose |
|------------------------------------|------------------------------------|
| `log` | `info`, `minor`, `warn`, `error`, `success` |
| `config`, `prerendered`, `routes`, `manifest`, `mimeTypes` | Resolved config; prerender info; all routes (replaces removed `createEntries`); the `$app/manifest` value; MIME map |
| `getClientDirectory()`, `getServerDirectory()`, `getAppPath()`, `getBuildDirectory(name)` | Paths |
| `writeClient`, `writeServer`, `writePrerendered` | Copy output, return files written |
| `generateServerInstance(dest, { routes?, serverDirectory? })` | Module exporting a `Server` instance (replaces removed `generateManifest`) |
| `generateEnvModule()`, `generateFallback(dest)`, `findServerAssets(routes)` | Public env module; SPA fallback; assets imported by server files |
| `copy(from, to, { filter, replace })`, `compress(dir)` | Copy with substitutions; write `.gz` and `.br` |
| `hasServerInstrumentationFile()`, `createInstrumentationInitializer`, `instrument` | Instrumentation wiring (Chapter 17) |

`rimraf` and `mkdirp` are deprecated in favour of `fs.rmSync` and `fs.mkdirSync`; the `Server` class export is deprecated in favour of the generated instance.

### A working minimal adapter

This adapter writes client, prerendered and server output and generates an entry exposing `fetch(request)`. I built a 3.1.0 app with it and called it with plain `Request` objects; the page route and a `+server` route both returned correct responses.

```js
// adapters/toy.js
import fs from 'node:fs';

/** @param {{ out?: string }} [options] @returns {import('@sveltejs/kit').Adapter} */
export default function toy({ out = 'build-toy' } = {}) {
    return {
        name: 'adapter-toy',

        async adapt(builder) {
            fs.rmSync(out, { recursive: true, force: true });
            fs.mkdirSync(out, { recursive: true });

            builder.writeClient(`${out}/client${builder.config.paths.base}`);
            builder.writePrerendered(`${out}/prerendered${builder.config.paths.base}`);

            const serverDir = builder.getServerDirectory();
            builder.generateServerInstance(`${serverDir}/server.js`);
            builder.copy(serverDir, `${out}/server`);

            fs.writeFileSync(
                `${out}/entry.js`,
                `import { server } from './server/server.js';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const here = fileURLToPath(new URL('.', import.meta.url));

await server.init({
    env: process.env,
    read: (file) => new Response(readFileSync(here + 'client/' + file)).body
});

export async function fetch(request) {
    return server.respond(request, {
        getClientAddress: () => request.headers.get('x-forwarded-for') ?? '0.0.0.0',
        platform: { adapter: 'toy' }
    });
}
`
            );
        },

        supports: { read: () => true, instrumentation: () => false },

        emulate() {
            return { platform: () => ({ adapter: 'toy' }) };
        }
    };
}
```

```ts
// vite.config.ts
import { sveltekit } from '@sveltejs/kit/vite';
import toy from './adapters/toy.js';
import { defineConfig } from 'vite';

export default defineConfig({ plugins: [sveltekit({ adapter: toy() })] });
```

```js
// try.mjs
const { fetch } = await import('./build-toy/entry.js');
const res = await fetch(new Request('http://localhost/api/ping'));
console.log(res.status, await res.text()); // 200 {"ok":true}
```

What it skips: serving static assets (a platform static host does that), correct `read` locations, a real client address, compression, a `preview` server and the `vite` hooks. A production adapter must also enforce body limits, derive the origin (copy adapter-node’s header logic), implement `emulate` so bindings exist in dev, answer `supports.read` honestly, call `instrument` if the platform can preload an instrumentation file, and be tested against the platform’s emulator. Through the `vite` option an adapter can wrap `getRequest`/`setResponse` (import the originals from `@sveltejs/kit/node`) and add plugins.

## Choosing an adapter

| Constraint | Choice | Why |
|------------------------|------------------------|------------------------|
| Everything prerenderable | `adapter-static` | No server to run or secure |
| Mostly static, some dynamic, managed hosting | Vercel (ISR) or Netlify | Platform handles CDN, TLS, scaling |
| Global low latency, KV/R2/D1 bindings, accepts Workers limits | `adapter-cloudflare` | Close to users, rich bindings, no fs |
| Containers, Kubernetes, Cloud Run, Render, VMs, full Node APIs | `adapter-node` | Fewest constraints, control of shutdown and proxies |
| Bun in production, single binary | `adapter-bun` | `Bun.serve`, `compile` |
| `query.live`, SSE, WebSockets (custom server) | `adapter-node` or `adapter-bun` | Long-lived connections fit servers, not serverless limits |
| Compliance, on-prem, private networks | `adapter-node` | Data residency and network control |
| Scale to zero on one VM | `adapter-node` + socket activation | `IDLE_TIMEOUT` |
| Mobile or desktop wrapper | `adapter-static` with `fallback`, `bundleStrategy: 'single'` | SPA from local disk (Chapter 11) |

Cross-cutting criteria (author practice): put compute next to the database; check whether you need long connections; decide how deploy skew is handled (platform-provided on Vercel, yours on containers); consider cold-start cost of env validation and `init`; verify the observability story; and keep platform-specific code behind one module to keep exit costs low.

## Key takeaways

- An adapter turns the platform-neutral build into a deployable artifact, configured in `sveltekit({ adapter })`. `adapter-auto` is for scaffolding and takes no options.
- The contract: required `name` and `adapt`; optional `emulate`, `supports.read`, `supports.instrumentation` and (3.0) `vite` hooks.
- adapter-node bundles `devDependencies`, externalises `dependencies`, serves assets from a build-time table with brotli/gzip, per-encoding ETags and immutable caching; compress dynamic responses at the proxy.
- `ORIGIN` is gone: use `paths.origin` (build time) or the `*_HEADER` variables (run time) behind a trusted proxy. Never set them on a directly reachable server.
- `ADDRESS_HEADER` with `XFF_DEPTH` reads the client IP from the right of `X-Forwarded-For`.
- Graceful shutdown: close, drain, force after `SHUTDOWN_TIMEOUT`, then `sveltekit:shutdown` for async cleanup. Align with the orchestrator’s grace period; long-lived connections delay it.
- Custom servers get only handler-level variables and own their lifecycle and instrumentation startup.
- adapter-bun is official (Bun 1.4+, Bun-run build, optional single executable). adapter-static needs prerendering everywhere or a `fallback`; `strict` guards against missing pages.
- adapter-cloudflare: `cloudflare:workers` for `env` and `waitUntil`, `request.cf`, global `caches`, Wrangler 4, no `fs`. adapter-vercel: Edge removed, ISR only for identical content, skew protection is a platform feature.
- On containers you own skew handling: `version.name`, retained old assets, backward-compatible APIs.
- A custom adapter writes three outputs, generates the server instance, calls `init` and `respond`.

## Review Questions

1.  Describe the two phases of a SvelteKit build. Which is platform-specific, and where does prerendering run?
2.  Where do you configure the adapter in SvelteKit 3, and which command installs and configures one?
3.  Which `Adapter` members are required? What do `emulate`, `supports.read` and `supports.instrumentation` do?
4.  Why does `adapter-auto` take no options, and why should you replace it once you pick a target?
5.  In adapter-node, how do you decide which packages are bundled and which stay external? Give a reason to keep a package in `dependencies`.
6.  A VM deployment ignores your `.env`. Why, and what is the fix?
7.  **What happens?** A request for a file under `_app/immutable/` with `Accept-Encoding: br` hits adapter-node. Describe `Content-Encoding`, `Vary`, `ETag` and `Cache-Control`.
8.  Why compress dynamic responses at the proxy, and which middleware do the docs recommend for a custom server? Why not the popular one?
9.  Every form on Cloud Run fails with “Cross-site POST form submissions are forbidden”. Give two fixes and their trade-off.
10. When is setting `PROTOCOL_HEADER`, `HOST_HEADER` or `ADDRESS_HEADER` dangerous?
11. Three trusted proxies, `ADDRESS_HEADER=x-forwarded-for`: what `XFF_DEPTH`, which entry is used, and why not the left-most?
12. Why is `paths.origin` a poor fit for promoting one image across hostnames?
13. Order adapter-node’s shutdown steps, say when `sveltekit:shutdown` fires, and list its `reason` values.
14. How does `query.live` affect rolling deploys on adapter-node, and what do you tune?
15. **Find the bug:** a custom Express server imports `handler.js`, listens on `process.env.PORT` and sets `SHUTDOWN_TIMEOUT=10`, expecting graceful shutdown.
16. **Find the bug:** a Dockerfile’s final stage copies `build/` and `package.json` but never installs production dependencies, and `pg` is in `dependencies`. What happens and what is the minimal fix?
17. Which nginx setting prevents streamed `load` promises and live updates from being delayed, and why?
18. What must be true of the build step for adapter-bun, and what does `--bun` do?
19. adapter-bun uses `envPrefix: 'APP_'` and the environment contains `APP_PROT=4000`. What happens at startup and why is it useful?
20. With adapter-static, why must `ssr` not be `false`, and what does `strict` protect against?
21. Distinguish `ssr = false` from adapter-static’s `fallback`. How do you serve most of an app as an SPA while prerendering marketing pages?
22. A site is deployed to `https://user.github.io/blog/`. What must you configure and how do you write internal links?
23. Name three adapter-cloudflare runtime API changes in 3.0.
24. Why can’t SvelteKit code use Durable Objects directly with adapter-cloudflare, and what is the workaround?
25. What was removed from adapter-vercel in 3.0, which `runtime` values remain, and what do you do with a former edge route?
26. Which ISR option is required, which controls the cache key, and what happens with `prerender = true`?
27. Give a concrete example of the leak the ISR warning describes.
28. Why declare Vercel system variables with `static: true`?
29. Which Builder methods replaced `createEntries` and `generateManifest`, and what must the generated entry call at runtime?
30. **Design:** Choose between adapter-node on Cloud Run and adapter-vercel for an app with remote functions, `query.live` dashboards and a Postgres in Frankfurt. Compare long connections, shutdown, skew handling and latency, and recommend one.
