# Chapter 17: Performance, Testing and Observability

An Astro site is fast by construction, because the default output is HTML with no JavaScript. It stays fast only if you keep the hydration budget under control, keep builds tractable as page counts grow, test the seams between server-rendered markup and client islands, and can see what the server is doing in production. This chapter covers four areas: how to spend (and measure) the client JavaScript budget; how to make large builds faster with `--timings`, `build.concurrency`, incremental builds and parallel prerendering; how to test Astro and Svelte code with Vitest, the Container API and Playwright; and how to observe running servers through the Logger API, `Astro.logger`, the dev toolbar and background dev servers.

Everything here was run against Astro 7.4.1, `@astrojs/svelte` 9.1.0, Svelte 5.57.2, Vitest 3.2 and `@astrojs/node` 11. Outputs that appear in this chapter (build timing reports, JSON log lines, status output) come from a real test project.

## The hydration budget

### What costs what

An island has four costs: the HTML it produces on the server (cheap, and indexable), the JavaScript module for the component and its imports, the renderer runtime (for Svelte, a small client module; the Svelte runtime itself is tree-shaken into the component chunk), and the work to hydrate. The Astro “island” bootstrap itself is shared: one `astro-island` custom element definition inlined per page, plus one small script per directive type in use (`client:load`, `client:visible` and so on each add their own tiny inline script).

You can see these in any rendered page. In the test project, a page containing a single `client:visible` Svelte counter emitted: the `astro-island,astro-slot{display:contents}` style, a script defining `Astro.visible` (an `IntersectionObserver` wrapper), the large script defining the `astro-island` element (which includes Astro’s prop deserializer for the supported types: object, array, `RegExp`, `Date`, `Map`, `Set`, `BigInt`, `URL`, typed arrays, `Infinity`), and then the island element:

```html
<astro-island uid="Z1fMx9h" component-url="/_astro/Counter.xxxx.js"
  component-export="default" renderer-url="/_astro/client.svelte.xxxx.js"
  props="{&quot;start&quot;:[0,2]}" ssr client="visible"
  opts="{&quot;name&quot;:&quot;Counter&quot;,&quot;value&quot;:true}" await-children>
  <!--[--><button>Count: 2</button><!--]-->
</astro-island>
```

The `props` attribute is part of your HTML payload: `[0, 2]` is the serializer’s tagged representation of the number 2. Large props (a 500-item product list passed to a cart island) are shipped twice, once as rendered HTML and once as JSON in the attribute. Pass IDs and fetch details on demand, or pass the minimal fields the island renders.

### Choosing a directive

Directives differ in when the JavaScript is downloaded and executed:

| Directive | Downloads when | Use for |
|------------------------|------------------------|------------------------|
| none | never | Anything that does not need client state. The default and the best option. |
| `client:load` | immediately | Above-the-fold interactivity that must work on first paint (a nav menu on mobile, the cart button) |
| `client:idle` | after the page `load` event and `requestIdleCallback` (optional `{ timeout }`) | Secondary controls that should be ready soon but not compete with LCP |
| `client:visible` | when the element enters the viewport (optional `{ rootMargin }`) | Below-the-fold widgets: reviews, carousels, comment boxes |
| `client:media="(query)"` | when the media query matches | Components used only at certain breakpoints |
| `client:only="svelte"` | immediately, skips SSR | Components that cannot render on the server (depend on `window`); you lose SSR HTML and need a `slot="fallback"` |

Three decision rules I use in reviews:

1.  **Default to no directive and ask what breaks.** A Svelte component with a directive-less usage renders to static HTML; it is a template. A surprising amount of UI (product cards, tabs implemented with CSS or `<details>`) never needs hydration.
2.  **Prefer `visible` over `idle` for anything below the fold,** and give it a generous `rootMargin` (for example `client:visible={{ rootMargin: '200px' }}`) so the code is ready by the time the user scrolls.
3.  **`client:only` is a smell.** It defeats the Astro model for that subtree and shifts layout. Use it for third-party widgets that touch `window` at import time, not for convenience.

Nested islands (an island inside slot content of another island) hydrate parent first, because each `astro-island` waits on its closest ancestor `astro-island[ssr]`. A `client:visible` child of a `client:load` parent pays the parent cost immediately.

### Measure the bundle

The documented recipe uses `rollup-plugin-visualizer` through Vite config:

```js
// astro.config.mjs
import { defineConfig } from 'astro/config';
import { visualizer } from 'rollup-plugin-visualizer';

export default defineConfig({
  vite: {
    plugins: [visualizer({ emitFile: true, filename: 'stats.html' })],
  },
});
```

Run `astro build`; the plugin emits `stats.html`. For an app with an `output: 'server'` build, the plugin runs for each Vite environment build, so decide which stats you want (the client bundle is the one that matters for the budget). Look for: a single heavy dependency pulled into the shared chunk by one island; accidental imports of server-only code; and duplicated Svelte runtime copies (rare; they indicate multiple `svelte` versions in the tree).

Complement bundle stats with the dev toolbar’s Inspect app (later in this chapter) and with a plain `ls -S dist/client/_astro | head` in CI, failing the build when a chunk exceeds a budget.

```bash
#!/usr/bin/env bash
# scripts/check-budget.sh
set -euo pipefail
limit=$((60 * 1024))   # 60 KiB per JS chunk, uncompressed
for f in dist/client/_astro/*.js; do
  size=$(wc -c < "$f")
  if [ "$size" -gt "$limit" ]; then
    echo "budget exceeded: $f ($size bytes)"; exit 1
  fi
done
```

(For static output the directory is `dist/_astro/`.)

## Faster builds

### Read the timings first

Since 7.4, `astro build --timings` prints a report of where the time went. Here is the real output for the test project (trimmed):

```text
 build timings
total 1.67s · 0 pages · output "server"

Build phases
  resolve config                       356ms  21.4%
  setup                                196ms  11.8%
    route discovery                      4ms   0.3%
    vite config                         12ms   0.7%
    content sync                        69ms   4.1%
  prerender bundle                     270ms  16.2%
  ssr bundle                           509ms  30.6%
  client bundle                        211ms  12.7%
  manifest injection                     9ms   0.6%
  generate pages                         1ms   0.1%

Vite plugins (276ms of the build)
  vite-plugin-svelte:compile            54ms   2 calls · transform 54ms
  astro:markdown                        34ms   2,130 calls · resolveId 34ms
  ...
Slowest files to bundle (130ms in load/transform)
  src/components/Counter.svelte         54ms   vite-plugin-svelte:compile
  ...
Integrations (102ms in hooks)
  @astrojs/svelte                       99ms   astro:config:setup 99ms
```

The report covers build phases, Vite plugins, Markdown processing and syntax highlighting, page rendering, image optimization and integration hooks. Read it top-down:

- **“generate pages”** dominating: you have many prerendered pages, and per-page work (data fetching, Markdown, image transforms) matters. This is where concurrency, caching and incremental builds apply.
- **A bundle phase dominating:** a Vite plugin or a heavy dependency. The plugin table names the culprit.
- **Integration hooks dominating:** an integration doing synchronous work in `astro:config:setup` or `astro:build:done`.

One practical observation: for an on-demand site, 0 pages are generated at build and the cost is bundling for three environments (prerender, SSR, client). Build time then scales with code, not content.

### `build.concurrency`

`build.concurrency` (default `1`) is the number of pages rendered in parallel within one process. The documentation is blunt: in most cases do not change it. Use it only when rendering is dominated by awaiting I/O (many `fetch` calls) and caching or batching the I/O is not possible. JavaScript is single-threaded, so CPU-bound rendering gains nothing and memory use rises. It is stable but flagged as subject to change in minors.

```js
export default defineConfig({
  build: { concurrency: 4 },
});
```

Before reaching for concurrency, fix the I/O: fetch once at module level or in a shared loader (content collections, Chapter 6) instead of once per page.

### `experimental.parallelPrerender` (7.4)

`parallelPrerender` is the CPU-bound answer: it renders static pages across worker threads.

```js
export default defineConfig({
  experimental: {
    parallelPrerender: true,            // all cores but one
    // parallelPrerender: { workers: 4 },
  },
});
```

The documented limitations are important:

- Pages rendered in parallel **do not share module-level variables.** A cache you populate in a module variable while rendering page A will not exist in the worker rendering page B. Anything memoized at module level becomes per-worker.
- `getStaticPaths()` props must be serializable (they cross a thread boundary). Functions and class instances fail.
- The flag does nothing when the adapter has its own prerenderer (among official adapters, `@astrojs/cloudflare`), and Astro warns.
- Each worker costs memory; reduce `workers` if the build runs out of memory.

It is still experimental, so pin your Astro minor when using it.

### `experimental.incrementalBuild` (7.2)

Incremental builds skip pages whose inputs did not change. The cache lives in `node_modules/.astro/` (so it must be persisted by your CI cache) and decisions rely on the `cacheKey` you return from `getStaticPaths()` and on a content entry’s `digest` (Chapter 6). `astro build --force` bypasses the cache. Use it on content-heavy sites where most pages are unaffected by most commits; it also moves correctness responsibility to you: a page whose output depends on data not reflected in its cache key will be stale.

### Static versus on-demand as a performance decision

Prerender what you can (`export const prerender = true` in a server project). The build pays once; the CDN serves for free. Move to on-demand only for pages that need request data, and then recover performance with route caching (Chapter 12) and server islands (Chapter 9) rather than making the entire page dynamic.

## Streaming and the 7.0 rendering engine

On-demand pages stream: Astro flushes HTML as components render rather than waiting for the whole page. In 7.0 the experimental `queuedRendering` flag was removed and the new engine became the only one. Per the changelog: construction of the render queue was dropped in favour of “a streaming approach where components are rendered and flushed as they are encountered”; the experimental node polling feature was removed; and the content cache was descoped to cache only tag names. If you had `experimental: { queuedRendering: {} }`, delete it.

The practical consequence for application design is that **`await` placement determines time to first byte.** A top-level `await` in a page’s frontmatter blocks the entire page. An `await` in a child component only blocks the output after that component, and sibling components start rendering their data in parallel. The streaming recipe makes the same point:

```html
---
// src/pages/index.astro: nothing is sent until both fetches complete
const person = await fetch('https://randomuser.me/api/').then((r) => r.json());
const fact = await fetch('https://catfact.ninja/fact').then((r) => r.json());
---
```

versus moving each fetch into its own component:

```html
---
// src/pages/index.astro: <head> and the h2s stream immediately
import RandomName from '../components/RandomName.astro';
import RandomFact from '../components/RandomFact.astro';
---
<html>
  <head><title>A name and a fact</title></head>
  <body>
    <h2>A name</h2><RandomName />
    <h2>A fact</h2><RandomFact />
  </body>
</html>
```

You can also put promises directly in the template: `<p>{namePromise}</p>` resolves in parallel and blocks only the markup after it. Note two interactions:

- Streaming sends the status code and headers first. A component that discovers deep in the page that it must redirect or set a cookie cannot do so once the body has started; decisions that affect headers belong in middleware or at the top of the page, before any output.
- The Node adapter has `experimentalDisableStreaming` and the Container API has a `streaming` option (default `false`). Some hosts and proxies buffer responses, which defeats streaming; test through your real edge.

Slow, non-critical regions are better served by server islands with a fallback (Chapter 9), which also keeps the main response cacheable.

## Testing

### The test pyramid for Astro

| Layer | Tool | What it proves |
|------------------------|------------------------|------------------------|
| Pure logic (cart reducers, price formatting, `.svelte.ts` rune modules) | Vitest, `node` | Code correctness, fast |
| Astro component output | Vitest + Container API | Markup, slots, props, Svelte island SSR output |
| Svelte component behaviour (clicks, DOM updates) | Vitest with a DOM environment (jsdom or happy-dom) in a separate project, or a browser runner | Client behaviour in isolation |
| Whole-site behaviour (hydration, routing, actions, CSP) | Playwright against `astro build && astro preview` or the production server | Everything wired together |

### Vitest with `getViteConfig()`

Use the Astro helper so that Vitest runs with your Astro and Vite configuration (aliases, the Svelte plugin, virtual modules such as `astro:content`, `astro:container`):

```ts
// vitest.config.ts
/// <reference types="vitest/config" />
import { getViteConfig } from 'astro/config';

export default getViteConfig({
  test: {
    environment: 'node',
    include: ['tests/**/*.test.ts'],
  },
});
```

`getViteConfig(userViteConfig, inlineAstroConfig?)` also takes a second argument to override Astro config for tests, such as `{ site: 'https://example.com/', trailingSlash: 'always' }`.

> **Warning:** Astro components cannot be rendered in a Vitest environment that simulates a browser (jsdom, happy-dom). Use `environment: 'node'` for any test that renders `.astro` files. If you also test Svelte components in a DOM environment, use a separate Vitest project (workspace/`projects`) with its own environment and keep Astro-rendering tests in the node project.

### A caveat observed with linked `node_modules`

When I first ran this suite in a scratch directory whose `node_modules` was a symlink to a directory outside the project, SSR of a Svelte component inside the container failed with `TypeError: Cannot read properties of null (reading 'function')` from `svelte/src/internal/server/dev.js`. That error is the signature of two copies of Svelte’s server runtime being loaded (one externalized, one transformed by Vite), so Svelte’s internal “current render context” variable is set in one copy and read in the other. With a normal install (dependencies physically in the project’s `node_modules`) the same test passed without any special configuration. If you hit this in a monorepo with unusual linking, `test.server.deps.inline: [/svelte/]` forces a single transformed copy, and fixed it in my reproduction. Treat that as a workaround for a broken layout, not as standard configuration.

### The Container API

The Container API renders a component in isolation, without a router or server. It is still prefixed `experimental_` and, per the reference, “subject to breaking changes, even in minor or patch releases” despite being used widely in tests.

```ts
// tests/card.test.ts
import { experimental_AstroContainer as AstroContainer } from 'astro/container';
import { getContainerRenderer as svelteRenderer } from '@astrojs/svelte/container-renderer';
import { loadRenderers } from 'astro:container';
import { expect, test } from 'vitest';
import Card from '../src/components/Card.astro';

test('Card renders title, slot and a Svelte island', async () => {
  const renderers = await loadRenderers([svelteRenderer()]);
  const container = await AstroContainer.create({ renderers });

  const html = await container.renderToString(Card, {
    props: { title: 'Hello' },
    slots: { default: 'Slot text' },
  });

  expect(html).toContain('<h2>Hello</h2>');
  expect(html).toContain('Slot text');
  expect(html).toContain('<astro-island');
  expect(html).toContain('Count: 2');   // the island was server-rendered
});
```

with:

```html
---
// src/components/Card.astro
import Counter from './Counter.svelte';
interface Props { title: string }
const { title } = Astro.props;
---
<section><h2>{title}</h2><slot /><Counter client:visible start={2} /></section>
```

```html
<!-- src/components/Counter.svelte -->
<script lang="ts">
  let { start = 0, label = 'Count' }: { start?: number; label?: string } = $props();
  // svelte-ignore state_referenced_locally
  let n = $state(start);
</script>

<button onclick={() => n++}>{label}: {n}</button>
```

Key points about the API:

- **`create(options?)`** takes `renderers` (framework renderers needed for `client:*` components or MDX) and `streaming` (default `false`).
- **Renderers.** Each official framework package exposes `getContainerRenderer()` from its `container-renderer` entrypoint (`@astrojs/react`, `preact`, `solid-js`, `svelte`, `vue`, `mdx`). Inside Vite (Vitest, integrations) use `loadRenderers()` from the virtual module `astro:container` to load them. Outside Vite, for example when you call the container at runtime in an on-demand app or from a non-JS shell, `astro:container` does not exist and you must import renderers yourself and register them with `addServerRenderer({ renderer })` followed by `addClientRenderer({ name, entrypoint })`; server renderers must be added before client renderers. Since Astro 7 the `getContainerRenderer()` import path is `@astrojs/<pkg>/container-renderer`; the package-root import is deprecated (Chapter 19).
- **`renderToString(Component, options)`** returns HTML; **`renderToResponse`** returns a `Response` (use it to check status and headers, and with `routeType: 'endpoint'` to test endpoints, passing `request: new Request(url, { method: 'POST' })` for non-GET methods).
- **Options:** `slots` (values are strings; render nested containers to strings first), `props`, `request` (for `Astro.url`, headers, cookies), `params` (for `Astro.params`), `locals` (for `Astro.locals`), `routeType`, and `partial` (default `true`, so no `<!DOCTYPE html>`; pass `partial: false` to render a full page).
- **`renderComponent(Component, options)`** (7.3.5) returns the component’s HTML *including its scripts and styles*. The component must be imported with the `?container` query: `import Card from '../src/components/Card.astro?container'`. Without the query it behaves like `renderToString`. Only *inlined* scripts and styles are included; assets imported through `@import` or `import ... from` are not. I ran this against `Card.astro?container` and it passed and included the `astro-island` markup.

**Testing a Svelte island through the container tests SSR only.** The assertion `Count: 2` proves that the server-render path and prop passing work. It does not click the button. For hydrated behaviour either test the Svelte component directly with a DOM environment, or use Playwright.

What to assert in container tests: structure and content, conditional branches (via `locals`, `request` and `props`), and accessibility attributes. Avoid snapshotting the whole HTML string: it includes Astro’s inlined island scripts, whose contents change between Astro releases, so snapshot tests become noisy. Select the substrings you care about, or parse the HTML.

### Testing rune modules and Svelte components

Rune modules in `.svelte.ts` files are compiled by the Svelte plugin, which `getViteConfig()` includes, so you can test them as ordinary modules:

```ts
// src/lib/cart.svelte.ts
export class Cart {
  items = $state<{ sku: string; qty: number }[]>([]);
  count = $derived(this.items.reduce((n, i) => n + i.qty, 0));
  add(sku: string) {
    const found = this.items.find((i) => i.sku === sku);
    if (found) found.qty++;
    else this.items.push({ sku, qty: 1 });
  }
}
```

```ts
// tests/cart.test.ts
import { expect, test } from 'vitest';
import { Cart } from '../src/lib/cart.svelte';

test('count derives from items', () => {
  const cart = new Cart();
  cart.add('a'); cart.add('a'); cart.add('b');
  expect(cart.count).toBe(3);
});

test('mutations through the class are reactive', () => {
  const cart = new Cart();
  cart.add('a');
  cart.add('a');
  expect(cart.items).toEqual([{ sku: 'a', qty: 2 }]);
  expect(cart.count).toBe(2);
});
```

Two limits I measured. First, a test file that uses a rune itself (for example `$effect.root`) must be named `*.svelte.test.ts` or the compiler never sees it and you get `ReferenceError: $effect is not defined`; testing through an exported class, as above, avoids that. Second, Vitest runs your modules through Vite’s SSR transform, so Svelte compiles them in server mode: `$state` and `$derived` behave, but **`$effect` callbacks do not run** (an effect that pushed into an array left it empty even after `flushSync()` and with `resolve.conditions: ['browser']`). Test effect-driven behaviour either by extracting the logic into plain functions, or in a browser-like setup (Vitest browser mode, or Playwright) where the client build of Svelte is used.

As with any module-level state, a *shared singleton* instance leaks between tests in the same file; export a class or factory, as above, and instantiate per test (Chapter 4 explains why the same discipline protects you from cross-request leaks on the server).

### Playwright for islands

Playwright tests the integrated site. The documentation recommends running tests against production output, which for Astro means a build:

```ts
// playwright.config.ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  webServer: {
    command: 'npm run build && npm run preview',
    url: 'http://localhost:4321/',
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
  },
  use: { baseURL: 'http://localhost:4321/' },
});
```

For on-demand projects, `astro preview` uses the adapter’s preview entrypoint (the Node adapter supports it); alternatively start the built server directly (`node dist/server/entry.mjs` with `PORT`) as the `webServer.command`.

The most common island-testing bug is asserting before hydration. A `client:visible` island is plain server HTML until it scrolls into view; clicking its button before hydration does nothing. Astro removes the `ssr` attribute from the `astro-island` element after hydration completes (visible in the island bootstrap: `this.removeAttribute('ssr')` followed by an `astro:hydrate` event). Use that as the synchronization point:

```ts
// e2e/counter.spec.ts
import { test, expect } from '@playwright/test';

test('counter island hydrates and increments', async ({ page }) => {
  await page.goto('/');
  const island = page.locator('astro-island', { has: page.getByRole('button') });
  await island.scrollIntoViewIfNeeded();          // triggers client:visible
  await expect(island).not.toHaveAttribute('ssr'); // hydrated
  const button = island.getByRole('button');
  await expect(button).toHaveText('Count: 2');
  await button.click();
  await expect(button).toHaveText('Count: 3');
});

test('no JS needed for static content', async ({ browser }) => {
  const ctx = await browser.newContext({ javaScriptEnabled: false });
  const page = await ctx.newPage();
  await page.goto('http://localhost:4321/');
  await expect(page.getByRole('heading', { name: 'Hi' })).toBeVisible();
  await ctx.close();
});
```

(I verified the island lifecycle by reading the emitted bootstrap script and the container output; the Playwright files here follow the documented configuration and were not run in this environment, which has no browsers installed.)

E2E tests worth having in every Astro project: a no-JS smoke test for content pages; one test per directive type you rely on; actions and forms with JavaScript disabled when you promise progressive enhancement; the security headers (CSP, Chapter 16); and, with `<ClientRouter />`, navigation tests that assert persisted island state (Chapter 14).

## Observability

### The Logger API

Since 7.0 logging is a stable, replaceable subsystem. By default Astro uses `logHandlers.node()` (stdout for info and warn, stderr for errors). Three levels exist for filtering, highest first: `error`, `warn`, `info`. The level type also includes `debug` and `silent`, which are equivalent to the `--debug`/`--verbose` and `--silent` CLI flags.

Ready-made handlers come from `astro/config`:

```js
// astro.config.mjs
import { defineConfig, logHandlers } from 'astro/config';

export default defineConfig({
  logger: logHandlers.json({ level: 'info' }),            // structured
  // logger: logHandlers.compose(logHandlers.console(), logHandlers.json()),
});
```

- `logHandlers.node({ level })`: stdout/stderr; the default.
- `logHandlers.console({ level })`: `console.error/warn/info`, appropriate for platforms such as Workers where `console` is the log sink.
- `logHandlers.json({ pretty, level })`: one JSON object per log line with `message`, `label`, `level` and `time`.
- `logHandlers.compose(a, b, ...)`: broadcast each message to several handlers.

A custom logger is a module whose default export takes the `config` and returns an `AstroLoggerDestination`: a required `write(message)` and optional `flush()` (called at the end of each request) and `close()` (called before the server shuts down, for example by `@astrojs/node`). The message is `{ label, level, message, newLine }`. The `matchesLevel(messageLevel, configuredLevel)` helper is exported from `astro/logger`. Register it with `logger: { entrypoint, config }`; relative paths and URLs are accepted for `entrypoint` (URL since 7.1, relative path since 7.2).

```ts
// logger/ndjson.ts
import type { AstroLoggerDestination, AstroLoggerLevel } from 'astro';
import { matchesLevel } from 'astro/logger';
import { appendFileSync } from 'node:fs';

export default function ndjson(
  { level = 'info' as AstroLoggerLevel } = {},
): AstroLoggerDestination {
  const buffer: string[] = [];
  return {
    write(m) {
      if (!matchesLevel(m.level, level)) return;
      buffer.push(JSON.stringify({ t: Date.now(), level: m.level, label: m.label, msg: m.message }));
    },
    flush() {
      if (buffer.length) appendFileSync('app.log.ndjson', buffer.splice(0).join('\n') + '\n');
    },
    close() { this.flush?.(); },
  };
}
```

```js
// astro.config.mjs
export default defineConfig({
  logger: { entrypoint: './logger/ndjson.ts', config: { level: 'info' } },
});
```

I ran this against the Node adapter. The server’s own “listening” line and the application’s `Astro.logger.info('rendering home')` call both ended up in `app.log.ndjson`, and the process’s stdout stayed empty. The corollary matters: **when you register a custom logger you are in charge of all logs, including Astro’s own.** In my test, `astro build` with this logger printed nothing at all to the terminal and never wrote the file (the build never calls `flush()`), so a CI failure would have been silent. If you want terminal output during builds, `compose` your destination with `logHandlers.node()`, or have your logger fall back to the console when not serving requests.

For log aggregation (Loki, Datadog, an OpenTelemetry collector), the usual design is `logHandlers.json()` to stdout and a platform agent that ships container logs. Write a custom destination only when you must batch and push yourself, and then use `flush()` for per-request batches and `close()` for graceful drain.

### Application logs: `Astro.logger` and `context.logger`

`Astro.logger` in components and `context.logger` in endpoints and middleware expose `info`, `warn` and `error` (type `AstroRuntimeLogger`, `(message: string) => void`). They are always available since 7.0 and go to the configured logger:

```ts
// src/middleware.ts
import { defineMiddleware } from 'astro:middleware';

export const onRequest = defineMiddleware(async (context, next) => {
  const start = performance.now();
  const response = await next();
  const ms = Math.round(performance.now() - start);
  context.logger.info(`${context.request.method} ${context.url.pathname} ${response.status} ${ms}ms`);
  return response;
});
```

Because messages are plain strings, put the structure you need in the message (or in your own JSON string) and parse it downstream; there is no field bag on the runtime logger. Never log secrets, session identifiers or full cookie headers. Remember also that with streaming, a middleware that logs `response.status` logs the status sent at the start of the stream; a later failure inside a streamed component does not change it.

### Request-level metrics

Astro does not ship tracing. A middleware like the one above, an adapter-level hook (the Node adapter in `middleware` mode lets you wrap the handler in your own server), or the platform’s native tracing (Vercel, Cloudflare, Netlify) are the places to add it. Cache hit rates come from the route-cache headers described in Chapter 12.

### The dev toolbar

During `astro dev`, a toolbar appears at the bottom of each page. Built-in apps: the Astro menu (docs links and “Copy debug info”, which runs `astro info`), **Inspect** (lists every island on the page with its props and client directive, which is the quickest way to audit your hydration budget), **Audit** (basic performance and accessibility checks; a red dot signals a finding, and the docs say it is no replacement for Lighthouse or Pa11y), and **Settings**. It never ships to production. Disable it per project with `devToolbar: { enabled: false }`, per user with `astro preferences disable devToolbar` (add `--global` for all projects), and re-enable with `astro preferences enable devToolbar`. You can add your own apps; Chapter 18 builds one.

### Background dev and preview servers

Since 7.0, `astro dev --background` starts the dev server as a detached process with JSON logging, and records its URL, port and PID in `.astro/dev.json`. `astro preview --background` works the same since 7.2 (lock file `.astro/preview.json`). Subcommands manage it: `astro dev status`, `astro dev logs [--follow]` and `astro dev stop` (SIGTERM, then SIGKILL after 5 seconds). Real output from my run:

```text
$ astro dev --background --port 4411
{"message":"Dev server running at http://localhost:4411 (pid 12400)\n  Stop:   astro dev stop\n  Status: astro dev status\n  Logs:   astro dev logs","label":"SKIP_FORMAT","level":"info"}
$ astro dev status
{"message":"Dev server running at http://localhost:4411 (pid 12400, uptime 4s, background)", ...}
$ curl -s localhost:4411/_astro/status
{"ok":true}
$ astro dev stop
{"message":"Stopped dev server (pid 12400).", ...}
```

Notes:

- The dev server exposes `/_astro/status`, returning `{"ok": true}`, as a health endpoint. It exists in dev only, not in production builds.
- Backgrounding is automatic on macOS and Linux when Astro detects an AI coding agent, so that the server does not block the agent’s terminal; on Windows it does not happen automatically. Opt out with `ASTRO_DEV_BACKGROUND=0` (or `ASTRO_PREVIEW_BACKGROUND=0`).
- A second `astro dev --background` in the same project prints the existing server’s info and exits; `--force` replaces it. `--ignore-lock` (dev 7.1, preview 7.3) starts an additional server without reading or writing the lock file, and cannot be combined with `--background` or `--force`. The additional server is not tracked by `status`/`stop`/`logs`.
- `--json` on any command enables JSON logging, which is what `--background` implies.

These features matter for your test automation too: a Playwright global setup can run `astro preview --background` and `astro preview stop`, with `--ignore-lock` for parallel CI jobs sharing a checkout.

## A performance and quality checklist

- Every island justified; every directive the lowest-cost one that works; props minimal.
- `astro build --timings` output stored from CI; regression alerts on total and on `generate pages`.
- Chunk-size budget script in CI.
- No top-level `await` for non-critical data in page frontmatter; heavy regions in components or server islands.
- Container tests for components with branching; Vitest project in `node` environment; per-test instances of rune-module state.
- Playwright smoke tests against the production build, including a no-JS pass.
- JSON logs to stdout in production, structured per-request logging via middleware, no secrets in messages.

## Key takeaways

- The hydration budget is the main performance lever: default to no directive, use `visible` below the fold, treat `client:only` as an exception, and keep island props small because they ship as JSON in the HTML.
- `astro build --timings` (7.4) reports phases, plugins, slow files, Markdown/image work and integration hooks; use it before tuning anything.
- `build.concurrency` helps only I/O-bound rendering; `experimental.parallelPrerender` uses worker threads but breaks module-level caching assumptions; `incrementalBuild` depends on correct cache keys and digests.
- In 7.0 `queuedRendering` was folded into a stable streaming renderer; where you place `await` decides time to first byte.
- Use `getViteConfig()` and the `node` environment for Vitest; render `.astro` components with the Container API and `getContainerRenderer()` from `@astrojs/svelte/container-renderer` plus `loadRenderers()`.
- `renderComponent()` (7.3.5, `?container` import) includes scripts and styles; `renderToString()` does not.
- Container tests exercise SSR only; use Playwright, waiting for the `ssr` attribute to disappear, for hydrated behaviour.
- A custom logger replaces all of Astro’s logging, including build output; `flush()` is per request and `close()` at shutdown.
- `Astro.logger` and `context.logger` accept plain strings only.
- `astro dev|preview --background` plus `status`, `logs`, `stop` and `/_astro/status` make servers scriptable.

## Review Questions

1.  A page renders one Svelte counter with `client:visible`. List the kinds of inline assets Astro adds to the HTML in addition to the island element, and explain which are shared across islands.
2.  Why can large props passed to an island double the cost of that data in the HTML?
3.  Rank `client:load`, `client:idle`, `client:visible` and no directive by JavaScript cost on first load, and state when you would pick each.
4.  Why is `client:only="svelte"` usually a poor default, and what must you provide with it?
5.  A `client:visible` Svelte island is nested in the slot of a `client:load` island. In what order do they hydrate and why?
6.  Which section of the `--timings` report would you read first if a build with 20,000 prerendered pages takes 25 minutes, and which for a build with no prerendered pages that takes 90 seconds?
7.  When is raising `build.concurrency` useful, and when is it harmful?
8.  A teammate enables `experimental.parallelPrerender` and a module-level `Map` used as a memo cache for expensive Markdown transforms stops helping. Explain why and propose a fix.
9.  Name two other limitations of `parallelPrerender`, and one situation where the flag is ignored.
10. What does `incrementalBuild` use to decide that a page can be skipped, and what is the risk if your `cacheKey` omits an input?
11. What did the 7.0 changelog remove from the experimental `queuedRendering` feature, and what replaced the queue?
12. Explain how the following page behaves in terms of time to first byte, and rewrite it to improve it:

```html
---
const a = await fetch(urlA).then((r) => r.json());
const b = await fetch(urlB).then((r) => r.json());
---
<html><body><h1>Shop</h1><Reviews data={a} /><Stock data={b} /></body></html>
```

13. Why can a component not redirect after a streamed body has started?
14. Why does `getViteConfig()` exist, and what does it load by default?
15. Which Vitest environment must you use to render `.astro` components, and why?
16. Multiple choice: which import loads Svelte’s renderer for the Container API in a Vitest test?

<!-- -->

a.  `import { getContainerRenderer } from '@astrojs/svelte'`
b.  `import { getContainerRenderer } from '@astrojs/svelte/container-renderer'`
c.  `import { loadRenderers } from 'astro/container'`
d.  `import svelte from '@astrojs/svelte/server.js'`

<!-- -->

17. Find the bug:

```ts
const container = await AstroContainer.create();
const html = await container.renderToString(Card);  // Card.astro renders <Counter client:load />
expect(html).toContain('Count: 0');
```

18. What is the difference between `renderToString()` and `renderComponent()`, and how do you import a component for the latter?
19. What does `partial: true` (the default) mean for container output?
20. How do you test a `POST` endpoint with the Container API?
21. A snapshot test of `renderToString()` output breaks after a minor Astro upgrade although your components did not change. Why, and how would you write the assertions instead?
22. A `.svelte.ts` module exports a `Cart` class with `$state` items and a `$derived` count. Why can a Vitest node test assert on `count` but not rely on a `$effect` inside the module running?
23. Which DOM signal can a Playwright test use to know that an Astro island has finished hydrating? Where does that signal come from?
24. Design question: you must prove in CI that a product page works without JavaScript and that its cart island works with it. Describe the Playwright setup.
25. After registering a custom logger, `astro build` prints nothing. Why, and give two fixes.
26. What is the difference between `write()`, `flush()` and `close()` on an `AstroLoggerDestination`?
27. What types can `Astro.logger.info()` accept, and what does that imply for structured logging?
28. Which commands manage a background dev server, where is its state recorded, and what does `--ignore-lock` do?
29. Why does Astro background the dev server automatically for AI agents, and how do you opt out?
30. Where would you get a machine-readable readiness probe for the dev server, and why can you not use it in production?
