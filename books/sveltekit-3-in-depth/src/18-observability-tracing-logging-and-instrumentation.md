# Chapter 17: Observability: Tracing, Logging, and Instrumentation

A server framework is only operable if you can answer three questions about any request after the fact: what did it do, how long did each step take, and why did it fail. SvelteKit answers the first two with built-in OpenTelemetry spans and answers the third through `handleError`, a hook that sees every error. Everything else, from where traces go to how logs correlate with them, is deliberately left to you.

This chapter covers the stable tracing system in SvelteKit 3 (the `tracing.server` option, the span catalogue, `event.tracing`), the special `instrumentation.server` entry point and how adapters load it, the OpenTelemetry Node SDK setup with its module-loader caveats, bundling rules for instrumented libraries, structured logging and request correlation, metrics, client-side error and performance reporting, and debugging with breakpoints. I ran the tracing examples against a real SvelteKit 3.1.0 build on Node 22 with adapter-node while writing this chapter, and the span names, attributes and parent/child structure shown below come from that output and the 3.1 source rather than from memory.

## What changed in 3.0

In SvelteKit 2.x, tracing and instrumentation were behind `experimental.tracing` and `experimental.instrumentation`. In 3.0 both are gone and replaced by one top-level option:

```ts
// vite.config.ts
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [
        sveltekit({
            tracing: { server: true } // default: false
        })
    ]
});
```

If an old config still has `experimental.tracing`, the build fails with a message that the key “has been removed” and that tracing is now configured through `tracing.server`. Remember that in SvelteKit 3 these options go to the plugin in `vite.config`, not to `svelte.config.js` (Chapter 1). The feature is stable; there is no second flag.

The docs carry a sober warning worth repeating: tracing, and more so the auto-instrumentation that usually accompanies it, has nontrivial overhead. The suggested compromise is to enable it in development and preview environments only, or to sample in production. With `tracing.server: false` the span-recording code is a no-op: the internal `record_span` helper calls your function with a noop span and never touches `@opentelemetry/api`, which is also why that package can remain an optional peer dependency.

## The span model

### What is instrumented

SvelteKit emits spans for: the `handle` hook (the root and each handle in a `sequence`), server `load` functions, universal `load` functions while they run on the server, form actions, `+server` handlers (added in 3.1), and remote functions. Client-side code is not traced by this system.

The docs list these categories; the names and attributes below are from the 3.1 source and my test run. They are not a documented contract, so treat them as observable behaviour that may evolve, and pin dashboards and alerts on the stable parts (the root span name and `http.route`).

| Span name | Emitted for | Notable attributes |
|------------------------|------------------------|------------------------|
| `sveltekit.handle.root` | The whole request, wrapping your `handle` | `http.route`, `http.method`, `http.url`, `sveltekit.is_data_request`, `sveltekit.is_sub_request` |
| `sveltekit.handle.sequenced.<name or index>` | Each handle in `sequence(...)`; named after the function if it has a name, else its index | none |
| `sveltekit.resolve` | The call to `resolve(event)` | `http.route`; on completion `http.response.status_code`, `http.response.body.size` |
| `sveltekit.load` | Each server or universal `load` running on the server | `sveltekit.load.node_id` (file path, for example `src/routes/+page.server.ts`), `sveltekit.load.node_type` (`+page.server`, `+layout`, …), `sveltekit.load.environment` (`server`), `http.route` |
| `sveltekit.form_action` | A form action | `sveltekit.form_action.name`, `http.route`; for `fail(...)` results `...result.type = 'failure'` and `...result.status` |
| `sveltekit.endpoint` | A `+server` method handler (3.1) | `http.route`, `http.method` |
| `sveltekit.remote.call` | A remote query/command/prerender call | `sveltekit.remote.call.id` |
| `sveltekit.remote.form.post` | A remote `form` submission | `sveltekit.remote.form.post.id` |

Two details you will not find in the prose docs:

1.  The `sveltekit.handle.sequenced.*` spans nest root, then first handle, then second handle, then `sveltekit.resolve`, then the `load`s. My trace for a page with `sequence(first, second)` produced exactly: `handle.root` \> `sequenced.first` \> `sequenced.second` \> `resolve` \> `load`. The docs say sequenced handles “show up as children of each other and the root”; `resolve` sits under the innermost one.
2.  Static assets and prerendered files bypass `handle` (Chapter 2) and therefore produce no spans. A 404 for an unknown route does go through `handle`, and so produces a root span.

### How spans record errors and control flow

Spans are created with `startActiveSpan`, so the span is the active context for anything your code does inside that callback. When the wrapped function throws, SvelteKit annotates the span by error type:

- `HttpError` thrown by `error(...)`: attributes `<span name>.result.type = 'known_error'`, `.result.status`, `.result.message`. Only statuses of 500 and above also record an exception and set the span status to `ERROR`, so a 404 from `error(404)` does not make your error-rate dashboard light up.
- `Redirect`: `.result.type = 'redirect'`, with `.result.status` and `.result.location`. Redirects are not errors.
- Any other `Error`: `.result.type = 'unknown_error'`, plus `recordException` (with the stack) and `ERROR` status.

This is the semantic you want for SLOs: expected 4xx outcomes are visible as attributes but not counted as failures.

## `event.tracing`: annotating and extending spans

Every request event (and `load`, action, and remote-function event, via `getRequestEvent()`) carries:

```ts
event.tracing.enabled; // boolean: whether tracing is on
event.tracing.root;    // Span for sveltekit.handle.root
event.tracing.current; // Span for the current handle / load / action / endpoint / remote function
```

When tracing is off, these are noop spans, so you can call `setAttribute` unconditionally. A typical use is to stamp the root span with identity, tenant and feature information as soon as you know it, so every trace is searchable by those dimensions:

```ts
// src/hooks.server.ts
import type { Handle } from '@sveltejs/kit/hooks';
import { sequence } from '@sveltejs/kit/hooks';
import { lookupSession } from '#lib/server/session.js';

const auth: Handle = async ({ event, resolve }) => {
    const session = await lookupSession(event.cookies.get('sid'));
    event.locals.user = session?.user ?? null;

    // Searchable on every span tree for this request
    event.tracing.root.setAttributes({
        'app.user.id': session?.user.id ?? 'anonymous',
        'app.tenant.id': session?.tenantId ?? 'none'
    });

    return resolve(event);
};

export const handle = sequence(auth);
```

Keep cardinality and privacy in mind (author practice): user and tenant IDs are fine as span attributes (traces are sampled and stored with lower cardinality constraints than metrics), but never record emails, tokens, request bodies, or raw query strings that may carry secrets. The `http.url` attribute SvelteKit sets on the root span is the full `event.url.href`, including the query string, so if your URLs can contain tokens (password reset links, signed URLs), scrub them in a span processor or exporter rather than hoping nobody puts secrets in query strings.

### Adding your own child spans

`event.tracing.current` is a `Span`, which lets you annotate but not create children. To create a child, use the OpenTelemetry API directly. Because SvelteKit’s spans are *active* spans (it uses `startActiveSpan`), a span you start with `tracer.startActiveSpan(...)` inside a `load` automatically becomes its child, provided a context manager is registered. The `NodeSDK` registers one (backed by `AsyncLocalStorage`), so this works without passing context by hand:

```ts
// src/lib/server/db.ts
import { trace, SpanStatusCode } from '@opentelemetry/api';

const tracer = trace.getTracer('app.db');

export async function listProjects(tenantId: string, limit: number) {
    return tracer.startActiveSpan(
        'db.projects.list',
        { attributes: { 'app.tenant.id': tenantId, 'db.limit': limit } },
        async (span) => {
            try {
                return await runQuery(tenantId, limit);
            } catch (error) {
                span.recordException(error as Error);
                span.setStatus({ code: SpanStatusCode.ERROR });
                throw error;
            } finally {
                span.end();
            }
        }
    );
}

declare function runQuery(tenantId: string, limit: number): Promise<unknown[]>;
```

In my test run, a `db.users.list` span created this way showed up as a child of `sveltekit.load`, with the chain continuing up through `resolve` and the sequenced handles to the root. If you forget `span.end()`, the span is never exported and the trace looks truncated: always end in `finally`.

`@opentelemetry/api` is a peer dependency of SvelteKit and, if you write helpers like the one above, a dependency of *your* app. List it in `dependencies` so it is available at runtime.

## `src/instrumentation.server`

Spans are only useful if something collects them. SvelteKit reserves `src/instrumentation.server.js` (or `.ts`) as the place to initialise your OpenTelemetry SDK. The contract is: this file is loaded *before* your application code, so that instrumentation can intercept module imports. The docs write the filename with both extensions in different places; any extension from `moduleExtensions` (`.js`, `.ts` by default) works.

### How it is loaded

**In development**, the Vite dev server resolves the file on each request and imports it through the module runner before configuring the server for that request, so edits are picked up on new requests. If your adapter does not declare support, development fails with an explicit error naming the file and the adapter. Note that development runs through Vite’s module runner, not Node’s native ESM loader, so loader-hook-based auto-instrumentation has different fidelity in dev than in production. Verify tracing in a production build before trusting it.

**In production**, the adapter is responsible. An adapter advertises support by `supports.instrumentation()` returning `true`, and in `adapt` it asks the build to wrap its entry point. For adapter-node the generated entry is a facade that does three things in order:

1.  imports an environment initialiser (so `$app/env/*` values exist),
2.  imports `instrumentation.server.js`,
3.  *dynamically* imports the real server entry and re-exports its exports (`path`, `host`, `port`, `server`).

That ordering is the whole trick. Because the real application is imported dynamically after the instrumentation file has run, hooks registered by the instrumentation file (module loader hooks, patched globals) are already active when your application’s modules are evaluated. You can see the shape in the build output: `build/index.js` re-exports `./server/adapter-index.js`, which is the facade, while the original entry is copied to `start.js` next to it.

The Builder API methods adapters use for this are `hasServerInstrumentationFile()`, `instrument({ entrypoint, instrumentation, start, initializer, module })` and `createInstrumentationInitializer({ outputDirectory })` (Chapter 18). If you write an adapter, calling `instrument` is how you opt in.

Support among the official adapters varies by platform: adapter-node supports it. For serverless and edge-style platforms the docs defer to each adapter and platform; some platforms perform their own bundling and tracing and do not run an arbitrary preload file, so check the adapter documentation before assuming.

### Environment access and the chicken-and-egg problem

Importing any `$app/env/*` module evaluates `src/env.ts` and its dependency graph. This has an unavoidable consequence from the docs: *instrumentation cannot intercept a module imported (even transitively) by `src/env`*, because those modules run before `instrumentation.server` can start. Keep `src/env.ts` free of imports you want to trace, notably database clients and HTTP libraries. Validation libraries (valibot, zod) are fine.

## A production-shaped setup

The quickstart in the docs uses `NodeSDK`, auto-instrumentations, an OTLP/HTTP exporter, and `import-in-the-middle`. Here is a fuller version. Package versions at the time of writing: `@opentelemetry/sdk-node` 0.223, `@opentelemetry/auto-instrumentations-node` 0.81, `@opentelemetry/exporter-trace-otlp-proto` 0.223, `import-in-the-middle` 3.5 (verified with `npm view`; OpenTelemetry’s JS packages version independently and move quickly, so pin them).

```bash
npm i @opentelemetry/api @opentelemetry/sdk-node \
  @opentelemetry/auto-instrumentations-node \
  @opentelemetry/exporter-trace-otlp-proto \
  @opentelemetry/exporter-metrics-otlp-proto @opentelemetry/sdk-metrics \
  import-in-the-middle
```

```js
// src/instrumentation.server.js
import { NodeSDK } from '@opentelemetry/sdk-node';
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-proto';
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-proto';
import { PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics';
import { register, supportsSyncHooks } from 'import-in-the-middle/register-hooks.mjs';
import { createAddHookMessageChannel } from 'import-in-the-middle';
import { register as registerAsync } from 'node:module';

// 1. Install the module interceptor BEFORE anything else is imported.
if (supportsSyncHooks()) {
    register();
} else {
    const { registerOptions } = createAddHookMessageChannel();
    registerAsync('import-in-the-middle/hook.mjs', import.meta.url, registerOptions);
}

// 2. Configure the SDK. Endpoint, headers, sampler and resource attributes
//    come from the standard OTEL_* environment variables, which keeps this
//    file environment-agnostic.
const sdk = new NodeSDK({
    serviceName: process.env.OTEL_SERVICE_NAME ?? 'dashboard-web',
    traceExporter: new OTLPTraceExporter(),
    metricReader: new PeriodicExportingMetricReader({
        exporter: new OTLPMetricExporter(),
        exportIntervalMillis: 30_000
    }),
    instrumentations: [
        getNodeAutoInstrumentations({
            // fs instrumentation is extremely chatty for a bundled app
            '@opentelemetry/instrumentation-fs': { enabled: false }
        })
    ]
});

sdk.start();

// 3. Flush on shutdown (adapter-node emits this event; see Chapter 18)
process.on('sveltekit:shutdown', async () => {
    await sdk.shutdown();
});
```

Notes on this file:

- **Node version and the loader.** The synchronous `import-in-the-middle/register-hooks.mjs` path uses `module.registerHooks()` and needs Node 22.22.3+, 24.11.1+, 25.1.0+ or 26+. It *throws* on older runtimes. I hit this for real while testing on Node 22.22.2: `register()` raised “synchronous hooks require a Node.js version whose module.registerHooks accepts nullish CommonJS source”. The `supportsSyncHooks()` fallback shown above, taken from the docs, handles it. The asynchronous `module.register()` API was deprecated in Node 25.9.0 and emits a runtime warning from 26.0.0, so aim for the synchronous branch in production by pinning your Docker base image accordingly (Chapter 18).
- **TypeScript.** If you write this file in TypeScript, `import-in-the-middle/register-hooks.mjs` ships without types, so add a small `declare module 'import-in-the-middle/register-hooks.mjs'` or keep the file as `.js`, as the docs do.
- **Sampling.** Tracing every request is rarely appropriate in production. Use the standard environment variables, for example `OTEL_TRACES_SAMPLER=parentbased_traceidratio` and `OTEL_TRACES_SAMPLER_ARG=0.1`. Because the SDK reads them, the sampling policy is deployment configuration rather than code.
- **The shutdown hook.** `sveltekit:shutdown` is emitted by adapter-node on graceful shutdown with the reason (`SIGINT`, `SIGTERM`, `IDLE`). Without flushing, the last batch of spans, usually the ones for the request that triggered a crash or deploy, is lost.
- **Exporter choice.** `@opentelemetry/exporter-trace-otlp-proto` sends OTLP over HTTP to a collector (default `http://localhost:4318`). Pointing the app at an OpenTelemetry Collector sidecar and letting it forward to your vendor keeps vendor credentials out of the app and lets you change backends without redeploying.

### Local development loop

For local work, run Jaeger’s all-in-one container (the docs use it), enable `tracing.server`, and browse `http://localhost:16686`. If you do not want to run a backend, swap in a console exporter from `@opentelemetry/sdk-trace-node` for a quick look. That is what I used to verify the span tree above:

```js
// src/instrumentation.server.js (quick local variant)
import { NodeSDK } from '@opentelemetry/sdk-node';
import { ConsoleSpanExporter } from '@opentelemetry/sdk-trace-node';
// ...register hooks as above...
new NodeSDK({ serviceName: 'dev', traceExporter: new ConsoleSpanExporter() }).start();
```

### The missing-API error

If tracing is on and `@opentelemetry/api` cannot be imported, SvelteKit throws an error that tells you it “will likely resolve itself when you set up your tracing instrumentation in `instrumentation.server.js`”. Installing `@opentelemetry/sdk-node` brings the API in transitively, but under strict package managers (pnpm) a transitive dependency is not resolvable from your app, so install `@opentelemetry/api` explicitly.

## Bundling and `ssr.external`

Auto-instrumentation works by intercepting a module’s *import*, so the module must be a real import at runtime. The bundler can defeat that in two ways, which the docs lay out:

1.  A bundler may put code imported by `instrumentation.server` and application code into the *same chunk*; importing that chunk to initialise instrumentation then evaluates application code before the interceptor exists.
2.  A bundler may inline the library you want to instrument into an application chunk, so no bare import of it remains for the interceptor to observe. Tree-shaking can also change export shapes that instrumentation expects.

SvelteKit automatically externalises `@opentelemetry/api` so your instrumentation and SvelteKit’s runtime share one module instance. For any other library, mark it external in the Vite config so the bare import survives into the server output:

```ts
// vite.config.ts
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [sveltekit({ tracing: { server: true } })],
    ssr: {
        // Packages whose own instrumentation must see the real import
        external: ['pg', 'ioredis']
    }
});
```

Rules of thumb from the docs, with my emphasis on the operational consequence:

- Externalised packages must be installed at runtime: list them in `dependencies`, not `devDependencies`. With adapter-node, packages in `dependencies` (and their deep imports) are kept external from the final bundle automatically. You may still need `ssr.external` to stop Vite from bundling them during the earlier SSR build.
- Do not externalise application source files, and do not externalise indiscriminately; it changes how dependencies resolve and what you must ship.
- On other adapters, `dependencies`-based externalisation is *not* applied by the adapter, and some platforms cannot import runtime packages at all. Whether instrumentation of third-party libraries is possible there is a platform question.

An instrumented library is a trade: you get database spans for free and pay with a `node_modules` that must exist in the runtime image (Chapter 18 shows a multi-stage Dockerfile that installs production dependencies for exactly this reason).

## Logging

OpenTelemetry has a logs signal, but for most SvelteKit apps in 2026 the pragmatic setup is structured JSON logs on stdout, collected by the platform, with the trace ID in each line so that logs and traces join. The SvelteKit-specific parts are where to log and what to include.

### Request IDs and trace IDs

Generate or accept a request ID in `handle`, expose it on `locals`, return it to the client, and stamp the span:

```ts
// src/app.d.ts
declare global {
    namespace App {
        interface Locals {
            requestId: string;
            user: { id: string } | null;
        }
        interface Error {
            requestId?: string;
        }
    }
}

export {};
```

```ts
// src/hooks.server.ts
import type { Handle, HandleServerError } from '@sveltejs/kit/hooks';
import { sequence } from '@sveltejs/kit/hooks';
import { logger } from '#lib/server/logger.js';

const requestContext: Handle = async ({ event, resolve }) => {
    // Trust an inbound ID only if your edge sets/overwrites it; otherwise generate.
    const requestId = event.request.headers.get('x-request-id') ?? crypto.randomUUID();
    event.locals.requestId = requestId;
    event.tracing.root.setAttribute('app.request_id', requestId);

    const start = performance.now();
    const response = await resolve(event);
    const durationMs = performance.now() - start;

    // Page responses from resolve() accept new headers; see Chapter 9 for the cases that do not
    response.headers.set('x-request-id', requestId);

    logger.info(
        {
            requestId,
            traceId: event.tracing.root.spanContext().traceId,
            method: event.request.method,
            route: event.route.id,
            status: response.status,
            durationMs: Math.round(durationMs),
            userId: event.locals.user?.id
        },
        'request'
    );

    return response;
};

export const handle = sequence(requestContext);
```

`spanContext().traceId` is the 32-hex trace ID; when tracing is off, the noop span returns an all-zero ID, so filter that out if you care. Notice that this logs *after* `resolve`, which for a streamed response means after the headers are ready, not after the stream completes. Duration therefore means time to response start. That is the right number for latency SLOs on TTFB and the wrong one for total render time; the span tree covers the latter.

`event.route.id` is the route template (`/projects/[id]`), not the concrete URL. Always log and label by route ID: it has bounded cardinality, and it avoids putting identifiers in your metrics and log indexes.

### Logging errors with `handleError`

Since 3.0, `handleError` runs for every error thrown while loading, rendering or responding, except redirects: app errors from `error(...)`, framework errors such as 404/405/413, validation errors from remote-function argument checks, and unknown errors. It receives `{ kind, error, event }` (plus `issues` for validation errors; the client variant has no `validation` kind) and returns an `App.Error`-shaped object whose `status` and `message` are optional overrides. Never throw from it.

> **Note:** The hook’s input type in 3.1 is `CaughtError & { event }`. You get `kind` and `error` (and `issues` for validation errors); for the `framework` and `validation` kinds, `error` itself carries `status` and `message`. There are no top-level `status`/`message` arguments, so read them from `error`.

The consequence of “all errors” is that you must triage by `kind`, or you will page yourself for every 404 and every validation failure:

```ts
// src/hooks.server.ts (continued)
export const handleError: HandleServerError = ({ kind, error, event }) => {
    const requestId = event.locals?.requestId ?? 'unknown';
    const base = { requestId, route: event.route.id, kind };

    switch (kind) {
        case 'app':
            // Thrown via error(): the app already decided what to say.
            // Log expected 4xx at info/warn; real 5xx via error() deserve error level.
            if (error.status >= 500) logger.error({ ...base, status: error.status, msg: error.message });
            else logger.info({ ...base, status: error.status });
            return { ...error, requestId };

        case 'framework':
            // 404s, 405s, 413s: safe message, usually noise.
            logger.info({ ...base, status: error.status });
            return { ...error, requestId };

        case 'validation':
            // Bad remote-function arguments: client bug or probing, never a server fault.
            logger.warn({ ...base, status: error.status });
            return { ...error, requestId };

        case 'unknown': {
            // The one you page on. Attach the trace for correlation.
            logger.error(
                {
                    ...base,
                    traceId: event.tracing.root.spanContext().traceId,
                    err: error instanceof Error ? { name: error.name, message: error.message, stack: error.stack } : String(error)
                },
                'unhandled error'
            );
            // Do not leak internals: override only the message, status stays 500.
            return { message: 'Something went wrong', requestId };
        }
    }
};
```

Points of care:

- The `requestId` property needs `App.Error` augmented (`requestId?: string` above) so it appears in `page.error` and in your `+error.svelte`, where you can print “Quote this reference: …” for support. Chapter 10 covers designing that taxonomy.
- `event.locals` may not be populated if the error occurred before your `handle` ran (an extremely early failure). Hence `event.locals?.requestId ?? 'unknown'`.
- Because `error()` in `+server` or `handle` does not use `+error.svelte` (Chapter 10), `handleError` is the only place all server errors converge: do your reporting there, not scattered in `load`s.
- The returned `status` can change the HTTP status code, which is how you downgrade a noisy 500 to a 503 for a known dependency outage. Do it deliberately.
- Rendering errors thrown inside components pass through the same hook (3.0 made the former `handleRenderingErrors` behaviour the default).

### A logger that joins traces

A minimal `pino` logger that adds the active trace and span IDs to every line, even for code that does not have `event` in hand (for example, a repository function deep in your data layer):

```ts
// src/lib/server/logger.ts
import pino from 'pino';
import { trace } from '@opentelemetry/api';

export const logger = pino({
    level: process.env.LOG_LEVEL ?? 'info',
    redact: ['req.headers.authorization', 'req.headers.cookie', '*.password', '*.token'],
    mixin() {
        const span = trace.getActiveSpan();
        if (!span) return {};
        const { traceId, spanId } = span.spanContext();
        return { traceId, spanId };
    }
});
```

`trace.getActiveSpan()` works because SvelteKit’s spans are active spans (and the SDK’s context manager is installed), so any log call made while handling a request carries the correct IDs with no plumbing. When tracing is off it returns `undefined` and the mixin adds nothing. `pino` is a runtime dependency; keep it in `dependencies`. If you use auto-instrumentation, `@opentelemetry/instrumentation-pino` can additionally inject trace fields and forward logs, but the explicit mixin has fewer moving parts.

### What not to log

(Author practice.) Do not log `event.request` bodies, `cookies.getAll()`, `Authorization` headers, or the serialised `locals`. Redact at the logger. In `handleError`, `event` may contain everything about the request; pass selected fields, not the event, to third-party reporters, or you will ship session cookies to a vendor.

## Metrics

SvelteKit has no built-in metrics, and the spans above can be turned into metrics by your backend (many vendors compute RED metrics from traces). If you need metrics independent of trace sampling, which you do, because sampled traces undercount, record them yourself in `handle` with the OpenTelemetry metrics API (the SDK from the previous section exports them):

```ts
// src/lib/server/metrics.ts
import { metrics } from '@opentelemetry/api';

const meter = metrics.getMeter('app.http');

export const requestDuration = meter.createHistogram('http.server.request.duration', {
    unit: 'ms',
    description: 'Time from request start to response headers'
});
export const requestErrors = meter.createCounter('http.server.request.errors');
```

```ts
// src/hooks.server.ts (in requestContext, after resolve)
import { requestDuration, requestErrors } from '#lib/server/metrics.js';

// ...
const attrs = {
    'http.route': event.route.id ?? 'unmatched',
    'http.request.method': event.request.method,
    'http.response.status_code': response.status
};
requestDuration.record(durationMs, attrs);
if (response.status >= 500) requestErrors.add(1, attrs);
```

Label by route ID and status, never by URL or user ID. If your platform scrapes Prometheus instead, `prom-client` plus a `+server` endpoint at `/metrics` works the same way. Guard that endpoint: it should be reachable by the scraper and not by the internet (network policy, a shared-secret header checked in `handle`, or a separate internal port).

For health checks, which are not metrics but are adjacent, see Chapter 18.

### Propagation to downstream services

Outgoing `fetch` calls made from server code are instrumented by the auto-instrumentations (undici/http), which inject `traceparent` headers, so downstream services that also speak OpenTelemetry join the same trace without extra code. If you use `handleFetch` to rewrite URLs for internal API calls (Chapter 9), remember that the rewritten request still goes through the instrumented `fetch`. Verify end to end in a staging environment, since SvelteKit’s internal `event.fetch` to your own routes bypasses HTTP (it calls the handler directly) and appears as in-process spans rather than as network spans.

## Client-side observability

The server-side spans stop at the response. The browser is where Core Web Vitals, JavaScript errors and navigation failures occur.

### Client errors

`src/hooks.client.ts` exports its own `handleError`, called for errors during navigation, load, and rendering in the browser. Errors already transformed by the server hook are not passed to it again, and the `validation` kind does not exist on the client. A reporter that mirrors the server one:

```ts
// src/hooks.client.ts
import type { HandleClientError } from '@sveltejs/kit/hooks';

export const handleError: HandleClientError = ({ kind, error, event }) => {
    if (kind === 'unknown') {
        report({
            type: 'client-error',
            route: event.route.id,
            url: event.url.pathname, // not the full URL: query strings may carry tokens
            message: error instanceof Error ? error.message : String(error),
            stack: error instanceof Error ? error.stack : undefined
        });
    }
    return { message: 'Something went wrong' };
};

function report(payload: unknown) {
    const body = JSON.stringify(payload);
    // sendBeacon survives page unloads, unlike fetch without keepalive
    if (!navigator.sendBeacon('/api/telemetry', body)) {
        void fetch('/api/telemetry', { method: 'POST', body, keepalive: true });
    }
}
```

`handleError` does not catch everything. Errors in event handlers (a `click` handler that throws), in `setTimeout` callbacks, and unhandled promise rejections outside SvelteKit’s control are only visible through `window.addEventListener('error')` and `'unhandledrejection'`. Register those in the client `init` hook, which also lets you initialise a vendor SDK before hydration (`init` delays hydration until it settles, so keep it fast):

```ts
// src/hooks.client.ts (continued)
import type { ClientInit } from '@sveltejs/kit/hooks';

export const init: ClientInit = () => {
    addEventListener('unhandledrejection', (e) => report({ type: 'unhandledrejection', reason: String(e.reason) }));
    addEventListener('error', (e) => report({ type: 'window-error', message: e.message, source: e.filename, line: e.lineno }));
};
```

For readable stack traces you need sourcemaps for the production client bundle. Enable them with `build.sourcemap` in the Vite config and upload them to your error tracker (or serve them privately); serving sourcemaps publicly exposes your source. The docs’ Sentry example shows the vendor integration pattern: initialise the SDK in both hooks files, call `captureException` from `handleError`, and return a safe `App.Error`. Vendor SDKs may also provide Vite plugins to upload sourcemaps at build time; follow their SvelteKit 3 guidance, as the vendor packages must support the `vite.config`-based configuration.

### Web vitals

Lab tools predict; field data decides. The `web-vitals` library (6.x at the time of writing) reports LCP, INP and CLS from real sessions. Initialise it once, from the root layout, in the browser only:

```html
<!-- src/routes/+layout.svelte -->
<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/state';

    let { children } = $props();

    onMount(async () => {
        const { onLCP, onINP, onCLS } = await import('web-vitals');

        const send = (metric: { name: string; value: number; id: string; rating: string }) => {
            navigator.sendBeacon(
                '/api/vitals',
                JSON.stringify({
                    name: metric.name,
                    value: metric.value,
                    id: metric.id,
                    rating: metric.rating,
                    // Route template, not URL: bounded cardinality
                    route: page.route.id
                })
            );
        };

        onLCP(send);
        onINP(send);
        onCLS(send);
    });
</script>

{@render children()}
```

Two subtleties for client-routed apps. First, `web-vitals` measures hard (full-page) loads well, but soft navigations are a different problem: the browser’s soft-navigation heuristics are still evolving, so your LCP numbers describe *entry* pages. Capture client navigation timing yourself with `afterNavigate` plus `performance.mark` if soft navigations matter to your product. Second, `page.route.id` at report time is the route at the moment the metric fires (INP and CLS may fire late, after navigation); if accuracy matters, record the route when the observer is registered or use the metric’s attribution build.

The `/api/vitals` endpoint is a `+server.ts` that validates the payload (Chapter 15 on trusting client input), rate limits, and forwards to your metrics pipeline. Do not write raw client payloads to your logs unvalidated.

### Deployment skew as an observability signal

`updated` from `$app/state` flips `current` to `true` when the server reports a new `version.name`. In SvelteKit 3 it also refreshes on focus, on tab visibility, on server-data navigations and after remote calls, in addition to polling (`version.pollInterval`, one hour by default). Beyond showing a “reload for the new version” banner, log it: a spike in sessions with `updated.current === true` immediately after a deploy tells you how long clients linger on stale code, which determines how long you must keep backward-compatible remote function and endpoint shapes. Set a meaningful `version.name` (for instance the git SHA) in `sveltekit({ version: { name: process.env.GIT_SHA } })` so logs, spans and sourcemaps all refer to the same build. Attach it as a resource attribute (`service.version`) in your SDK setup.

## Debugging

Observability is for production; breakpoints are for development. The docs cover three setups:

- **VS Code debug terminal.** Open the command palette, run “Debug: JavaScript Debug Terminal”, start `npm run dev` there, and set breakpoints in server or client source. Alternatively add `.vscode/launch.json` with a `node-terminal` configuration whose `command` is `npm run dev`.
- **Chrome/Edge DevTools for Node.** Start the dev server with `NODE_OPTIONS="--inspect" npm run dev`, open the app, then click the Node.js icon in DevTools (or visit `chrome://inspect`). The docs caution that this works for client-side source maps only in that setup.
- **Other editors**: WebStorm and Neovim have community guides linked from the docs.

A few additions from practice (author practice):

- To debug the *production build*, run it under the inspector: `node --inspect build` (or `--inspect-brk` to pause on startup). Breakpoints land in built chunks, but with `build.sourcemap: true` they map back to source.
- Under Vite 8, the dev server’s SSR runs through the module runner in the same process as Vite, so `--inspect` on the `vite dev` process is the right target. There is no separate server process.
- The Svelte `@debug` tag and `$inspect` rune are cheaper than a debugger for state questions (see the Svelte book); breakpoints win for async server flow.
- `tracing.server: true` in dev with a local Jaeger is often the fastest way to see *why* a page is slow: the span tree shows which `load` and which database call dominates.

## A minimal observability baseline

If you do nothing else (author practice), ship this:

1.  `tracing: { server: true }`, `instrumentation.server.js` with OTLP export to a collector, sampling via environment variables.
2.  A `requestContext` handle that sets a request ID, stamps the root span, and logs one structured line per request with route ID, status and duration.
3.  A `handleError` that switches on `kind`, logs unknowns at error level with trace ID, and returns a request ID to the user.
4.  A client `handleError` and `init` listeners that beacon errors, and `web-vitals` beaconing LCP/INP/CLS tagged by route ID.
5.  A `service.version` taken from `version.name`.
6.  A graceful-shutdown flush via `sveltekit:shutdown`.

## Key takeaways

- 3.0 made tracing stable: one top-level `tracing: { server: boolean }` in `sveltekit({...})`, with `experimental.tracing`/`instrumentation` removed. When off, span recording is a noop.
- Spans cover `handle` (root and each `sequence` member), `resolve`, server and server-run universal `load`, form actions, `+server` handlers (3.1), and remote functions. The observed nesting is root \> sequenced handles \> `resolve` \> `load`. Exact span names and attributes are implementation details, not a documented contract.
- `error()` below 500 and redirects are recorded as attributes, not span errors; unknown errors and 5xx set the span to `ERROR` and record the exception.
- `event.tracing.root`/`current` let you annotate; create child spans with `@opentelemetry/api` `startActiveSpan`, which nest automatically under SvelteKit’s active spans.
- `src/instrumentation.server` is loaded before the app: through the module runner in dev, and in production via an adapter-built facade that imports it, then dynamically imports the real entry. Adapters opt in with `supports.instrumentation`.
- Import-in-the-middle’s synchronous hooks need a recent Node (22.22.3+, 24.11.1+, 25.1.0+, 26+); use the `supportsSyncHooks()` fallback otherwise. Modules imported by `src/env` cannot be instrumented.
- To instrument a library, keep its import visible with `ssr.external`, and keep it in `dependencies`; adapter-node keeps `dependencies` external automatically.
- `handleError` runs for every error except redirects and receives `kind` (`app`, `framework`, `validation`, `unknown`); triage by kind, log unknowns with the trace ID, and return a safe error with a request ID.
- Use route IDs, not URLs, as log and metric labels; scrub query strings from span attributes if they can carry secrets.
- Client observability is your job: client `handleError`, `init` listeners, `web-vitals` beaconing, sourcemaps, and `updated`/`version.name` for skew tracking.
- Debug with a JavaScript debug terminal or `--inspect`; debug production builds with `node --inspect build` plus sourcemaps.

## Review Questions

1.  What two experimental options did the 3.0 `tracing.server` option replace, and what happens if an old config still sets them?
2.  With `tracing.server: false`, does SvelteKit still require `@opentelemetry/api` to be installed? Why or why not?
3.  Name four kinds of operations for which SvelteKit emits spans. Which kind was added in 3.1?
4.  Given `export const handle = sequence(auth, rateLimit)` where `auth` and `rateLimit` are named functions, and one page `load`, list the span names in parent-to-child order for a page request.
5.  Why are static assets and prerendered pages absent from your traces?
6.  A `load` calls `error(404)`, another calls `error(503)`, and a third throws `new Error('boom')`. For each, state how the span is marked and whether an exception is recorded.
7.  How do you add a searchable `tenant` attribute to every span tree for a request? Where in the code, and via which object?
8.  **What happens?** In a server `load` you call `tracer.startActiveSpan('db.query', fn)` from `@opentelemetry/api` and the `NodeSDK` is running. What is the new span’s parent? What would change if you forgot `span.end()`?
9.  In development, when is `instrumentation.server` imported? How does that differ from the production flow with adapter-node?
10. Describe the three steps the adapter-node instrumentation facade performs, in order, and why the order matters.
11. What error do you get if you enable `tracing.server` and the active adapter does not support instrumentation, and when does it surface?
12. Why can’t you instrument a database client that is imported (directly or transitively) from `src/env.ts`?
13. **Find the bug:** an engineer adds `'pg'` to `ssr.external`, keeps `pg` in `devDependencies`, and deploys with adapter-node into a production image that installed only production dependencies. What happens at startup?
14. Name two ways a bundler can prevent auto-instrumentation from working, and the Vite option that addresses the second.
15. Why does the docs’ quickstart `register()` call throw on Node 22.22.2, and what is the fallback?
16. a\. Which environment variables would you use to sample 10% of traces with a parent-based sampler? b) Why prefer this over hard-coding in the SDK constructor?
17. Why should the SDK be flushed from a `sveltekit:shutdown` listener, and which adapter emits that event?
18. In `handleError`, what does `kind: 'framework'` cover? What would be the problem of logging all `kind`s at `error` level?
19. Which properties does `handleError` receive in SvelteKit 3.1 for the `validation` kind that it does not receive for the others? Is `validation` available in the client hook?
20. A user sees “Something went wrong” and contacts support. How do you design the error response so support can find the server logs and trace in seconds? Mention `App.Error`.
21. **What does this print?** `logger.info({ route: event.route.id })` for a request to `/projects/42` where the route file is `src/routes/projects/[id]/+page.svelte`. Why is that preferable to logging the pathname?
22. Why does a pino `mixin` calling `trace.getActiveSpan()` give you trace correlation in a repository function that never receives `event`?
23. Why does the `requestContext` handle measure only time to response start for streamed pages? Where would you look for total render time?
24. Why are sampled traces unsuitable as your only source of request-rate metrics? What should you record instead, and with which labels?
25. Which kinds of client-side error does the client `handleError` hook not see? Name the browser events you use for them.
26. Why does `navigator.sendBeacon` suit error and vitals reporting better than a plain `fetch`?
27. What does `updated.current` become `true` in response to in SvelteKit 3 (beyond hourly polling), and how can you use the signal operationally?
28. How would you debug a production build in Node with breakpoints, and what must you enable to land on source lines?
29. **Multiple choice.** Where must `src/instrumentation.server` initialise the SDK relative to the application’s modules?
    a.  After, so it can wrap already-loaded exports
    b.  Before, so interceptors are in place when libraries are imported
    c.  Concurrently, in a worker thread
    d.  It does not matter when using ESM
30. **Design:** You run three instances of a SvelteKit app behind a load balancer and want error-rate alerts that ignore 404s and validation failures but catch real faults. Which signals and labels do you use for the logs, the span status, and the metric, and where in the code does each get set?
