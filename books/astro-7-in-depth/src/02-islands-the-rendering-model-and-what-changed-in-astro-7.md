# Chapter 1: Islands, the Rendering Model and What Changed in Astro 7

Astro is a server-first web framework: every page is rendered to HTML on the server (at build time or on request), and JavaScript is shipped to the browser only for the small regions of the page that you explicitly mark as interactive. That sentence hides a lot of machinery: a compiler that turns `.astro` files into render functions, a streaming renderer, four Vite environments that build the same source for different runtimes, an integration layer that decides how a `.svelte` file becomes both server HTML and a client entrypoint, and a hydration runtime that is a single custom element. This book is about using all of it deliberately.

This chapter lays the foundation. We cover the islands architecture and why Astro rejects the single-page-application default; the render pipeline and where your code runs; the `output` modes and per-route `prerender`; the Vite environments; the Rust compiler and the 7.0 whitespace and HTML-strictness changes that bite during upgrades; the stable and experimental feature surface in Astro 7.4; the platform baselines; and a project setup with `@astrojs/svelte` that we reuse throughout the book. Every later chapter assumes you can reason about “what runs where, and when”, so this chapter is the one to internalize.

> **Note:** Version targets for this book are Astro 7.4.1, `@astrojs/svelte` 9.1.0 and Svelte 5.57.2. All Svelte code uses runes (`$state`, `$props`, `$derived`, `onclick`). Several claims below were verified by building a minimal project against exactly those versions; where the official documentation is silent, the text says so.

## Server-first rendering

A conventional client-rendered framework starts from the opposite assumption: the browser receives a nearly empty document and a JavaScript bundle, the bundle renders the UI, and server rendering (SSR) is a later optimization whose output must be “hydrated” by re-executing the whole component tree in the browser. The cost model follows from that: the amount of JavaScript the user downloads, parses and executes grows with the size of the *page*, not with the amount of *interactivity* on it.

Astro inverts the default. An Astro component renders to a string of HTML and CSS on the server and has no client-side runtime at all. Consider:

```html
---
// src/pages/index.astro
const posts = await fetch('https://example.com/api/posts').then((r) => r.json());
---
<html lang="en">
  <body>
    <h1>Posts</h1>
    <ul>
      {posts.map((p: { title: string }) => <li>{p.title}</li>)}
    </ul>
  </body>
</html>
```

The output of this page contains an `<h1>`, a `<ul>` and the list items. There is no script, no framework, no hydration markers. The frontmatter ran once, at build time (or per request, depending on the output mode discussed later), and is not in any bundle. Anything the browser needs beyond HTML is something you ask for.

This has three consequences that shape the way senior engineers should design Astro sites.

**Content-heavy sites are the sweet spot, not the only target.** The unit of cost is the island, not the page. A 200-component page with two interactive widgets ships two widgets’ worth of JavaScript (plus the shared runtime of the framework they use).

**The server/client boundary is explicit and syntactic.** In Next.js or SvelteKit the boundary is conceptual (server components, load functions, `+page.server.ts`). In Astro the boundary is a directive on a component: `client:load`, `client:visible`, `server:defer`. You can see, in the template, what ships.

**Data fetching is plain `await`.** The frontmatter is an async function body. There is no loader convention to learn for pages (there are for content collections, see Chapter 6). Top-level `await` in the frontmatter, `fetch`, database calls, filesystem reads: all just work in the server environment.

### Why not an SPA

The honest comparison is not “islands good, SPA bad”. An SPA is a reasonable choice for an application behind a login, where the bundle is cached after the first visit, SEO is irrelevant, and every screen is highly interactive. It is a poor default for pages whose primary job is to be *read*: marketing sites, documentation, blogs, catalogues, the product-detail pages of a shop. For these, the cost of a client-side router, a framework runtime, and a hydration pass over a mostly static tree buys little.

The islands pattern keeps what SPAs do well where it matters (rich components) and refuses to pay for it where it does not. Astro does not forbid you from building a whole page as a single island: `<App client:only="svelte" />` is a legitimate SPA embedded in an Astro page, and the docs say as much. What Astro forbids is *accidental* JavaScript.

## Islands architecture

The term “component island” was coined by Etsy’s Katie Sylor-Miller in 2019 and expanded by Jason Miller in 2020: render pages on the server, inject placeholders around highly dynamic regions, and hydrate those regions into independent widgets that reuse the server-rendered HTML. In Astro there are two kinds of island.

- A **client island** is an interactive UI-framework component (Svelte, React, Vue, Solid, Preact, Alpine) that is hydrated in the browser. You create one by adding a `client:*` directive.
- A **server island** is an Astro component whose *content* is rendered on the server separately from the rest of the page, via `server:defer`. It is an island of dynamic server-rendered HTML, not of JavaScript. Server islands get their own chapter (Chapter 9).

The properties of a client island matter for design:

1.  **Isolation.** Each island is mounted with its own call to the framework’s mount function. There is no shared component tree, so there is no context propagation between islands, no shared parent state, no cross-island `bind:`. State sharing is something you build (Chapter 4).
2.  **Independent timing.** A `client:load` island hydrates immediately; a `client:visible` island does not even download its JavaScript until it scrolls into view; a `client:idle` island waits for `requestIdleCallback`. Islands load in parallel and hydrate independently.
3.  **Static surroundings.** Everything outside an island is HTML. Astro components never re-render in the browser. If you want a piece of the page to change at runtime, it must be inside an island, inside a `<script>`, or fetched as HTML.
4.  **Framework mixing.** Because islands are independent, one page may contain Svelte, React and Vue islands. Only `.astro` files can contain components from multiple frameworks.

### The hydration unit: `<astro-island>`

When you write:

```html
---
import Counter from '../components/Counter.svelte';
---
<Counter client:load initial={3} />
```

Astro renders the component on the server and wraps the output in a custom element. From a build of this book’s test project, the relevant markup for a component with a title prop looks like this (attributes abridged):

```html
<astro-island
  uid="1ODz0J"
  component-url="/_astro/Box.BjnOE2lr.js"
  component-export="default"
  renderer-url="/_astro/client.svelte.DOW8nnPa.js"
  props="{&quot;title&quot;:[0,&quot;A&quot;]}"
  ssr
  client="load"
  opts="{&quot;name&quot;:&quot;Box&quot;,&quot;value&quot;:true}"
  await-children>
  <!--[--> ...server-rendered Svelte HTML... <!--]-->
  <!--astro:end-->
</astro-island>
```

Everything the browser needs to hydrate is declared in attributes: the URL of the component module, which export to use, the URL of the framework’s client entrypoint (the “renderer”), the serialized props, the directive name and its options. The `<astro-island>` class itself is a few kilobytes of inline script that is emitted once per page, together with one tiny script per directive type used on the page (`Astro.load`, `Astro.idle`, `Astro.visible`, …). It imports the component and renderer with retry logic, deserializes the props, collects slots, calls the renderer’s hydrate function, and removes the `ssr` attribute. This mechanism, and what it implies for props and children, is the subject of Chapter 3.

> **Senior tip:** View source on a production build early and often. The `<astro-island>` attributes are a complete, honest accounting of what you are shipping and what data you are leaking into HTML. The `props` attribute is world-readable; never pass secrets as island props.

### Client directives at a glance

| Directive | When the component’s JS is fetched and hydrated |
|------------------------------------|------------------------------------|
| `client:load` | Immediately on page load |
| `client:idle` | When the browser is idle (`requestIdleCallback`); accepts `{ timeout }` |
| `client:visible` | When the element enters the viewport; accepts `{ rootMargin }` |
| `client:media="(query)"` | When a CSS media query matches |
| `client:only="svelte"` | Skips server rendering; renders on the client only. The framework name is mandatory |

Details, custom directives and failure modes are in Chapter 3. For now, the design rule: *choose the laziest directive that still satisfies the interaction*. A hamburger menu button above the fold is `client:load`; a comment form at the bottom is `client:visible`; a chart that only matters on desktop is `client:media`.

## The render pipeline

It helps to see, in order, what happens when Astro handles a request for a page. This is simplified, but each stage is a place where behaviour in later chapters is decided.

1.  **Routing.** The request URL is matched against the routes derived from `src/pages` (Chapter 5). Reserved routes (`/_astro/`, `/_server_islands/`, `/_actions/`) win first.
2.  **Built-in handlers.** In the default pipeline, in this order: trailing-slash normalization, redirects, sessions, actions, your middleware, page rendering, i18n, and caching. In 7.x this pipeline is itself replaceable through `src/fetch.ts` (“advanced routing”, Chapter 5).
3.  **Page rendering.** The `.astro` page is a compiled module whose default export is a render function. Astro runs the frontmatter, then walks the template. Components are rendered recursively; framework components are handed to their renderer (`@astrojs/svelte`’s server entrypoint); `client:*` components are wrapped in `<astro-island>`.
4.  **Response.** The result is a `Response` whose body is a stream.

### Frontmatter runs once per render

The code between the `---` fences is the body of an async function that runs *every time the page is rendered*. In a prerendered page that is once per build (once per path for dynamic routes). In an on-demand page it is once per request. This is the single most useful rule for deciding where code belongs:

```html
---
// Runs at build time for prerendered pages; per request for on-demand pages.
const started = Date.now();
const data = await getData();
---
<p>Rendered at {started}</p>
```

The same page file therefore has two behaviours, controlled by a single export (`prerender`), and you must write frontmatter that is correct under both. Reading per-request data such as `Astro.cookies`, `Astro.clientAddress` or the incoming headers in a prerendered page is meaningless, because there is no visitor at build time; those APIs belong in on-demand routes.

### Top-level await and streaming

Frontmatter supports top-level `await`. In on-demand rendering, Astro streams HTML: it begins sending the document as the template is walked, and it awaits asynchronous components as it reaches them. Two consequences:

- **Waterfalls are your problem.** If a parent awaits a slow fetch before rendering children that start their own fetches, the work is sequential. Start independent fetches early (`const a = fetch(...)`, `const b = fetch(...)`, then `await Promise.all`), or move slow data into a component further down so the stream can flush the head first.
- **Status and headers are decided before the body streams.** Once the first chunk is flushed, you cannot change the status code or set headers. This is why `Astro.redirect()` must be called at the page level (before output starts), not from inside a child component. The routing guide states this directly: redirects must be done at the page level because on-demand rendering uses HTML streaming.

Astro 7.0 made the streaming-based queued renderer the only renderer (the earlier `experimental.queuedRendering` flag was promoted and removed). You do not configure it; Chapter 17 discusses its performance implications.

### What does not run in the browser

Nothing in an `.astro` file’s frontmatter or template expression ever runs in the browser. A `<script>` tag in an `.astro` file does, but it is a separate, bundled module (Chapter 2 and Chapter 4). A `.svelte` component runs in *both* places if it has a client directive: once on the server to produce HTML, and once in the browser to hydrate. Code inside a Svelte component’s `<script>` is therefore isomorphic; browser-only globals (`window`, `localStorage`) must be guarded with `onMount`, `$effect`, or `typeof window` checks, because the server render executes the top level of the script.

## Output modes and per-route `prerender`

Astro 7 has exactly two values for `output`: `'static'` (the default) and `'server'`. The historical `'hybrid'` value no longer exists; its behaviour is expressed by choosing a default and overriding per route.

| `output` | Default for every page and endpoint | Override |
|------------------------|------------------------|------------------------|
| `'static'` | Prerendered (built to HTML at build time) | `export const prerender = false` opts one route into on-demand rendering |
| `'server'` | Rendered on demand | `export const prerender = true` prerenders one route |

```html
---
// src/pages/account.astro — in a default (static) project
export const prerender = false;
const user = Astro.locals.user;
---
<h1>Hello, {user?.name}</h1>
```

Any on-demand route requires an adapter. Without one the build stops. This is the error I got building a project with a single `prerender = false` page and no adapter:

```text
[NoAdapterInstalled] Cannot use server-rendered pages without an adapter.
Please install and configure the appropriate server adapter for your final deployment.
```

The rule of thumb for choosing a mode: pick the output whose default fits *most* routes. A documentation site with one login-gated area stays `'static'` and marks that area `prerender = false`. A dashboard with a public landing page uses `'server'` and marks the landing page `prerender = true`. `Astro.isPrerendered` tells a component which kind of render it is in, which is useful for shared layouts.

> **Note:** The documentation’s adapter feature tables still list a `hybridOutput` capability even though `output` has only two values. This is a leftover name for “an adapter that supports mixing prerendered and on-demand routes”. Nothing in your config refers to it.

Chapter 8 treats on-demand rendering, adapters and deployment in depth; the prerender conflict behaviour (`prerenderConflictBehavior`, which replaced the experimental `failOnPrerenderConflict` flag) is covered there as well.

### Prerendered pages and dynamic routes

A prerendered dynamic route (`[slug].astro`) must tell Astro which paths to build via `getStaticPaths()`; an on-demand dynamic route must not. This asymmetry, and the string-only rule for `params` (verified below in Chapter 5), is a frequent source of confusion when a route is switched between modes.

## The Vite environments

Since Astro 6, the build is organized around Vite’s Environment API; Astro 7 runs on Vite 8. Understanding the environments pays off the first time you write a Vite plugin, debug “this module works in dev but not in build”, or use a Cloudflare adapter.

| Environment | Where it runs | What it builds |
|------------------------|------------------------|------------------------|
| `client` | Browser | Island components, hydration entrypoints, bundled `<script>` tags, CSS |
| `ssr` | The server runtime (Node, workerd, …) | The on-demand renderer: pages, endpoints, middleware, actions |
| `prerender` | Node (by default), during `astro build` | The code that renders static pages at build time |
| `astro` | Dev server only | A secondary SSR environment used when the `ssr` environment is not a runnable dev environment (adapters such as Cloudflare’s workerd) |

You can see the `prerender` environment’s output in a static build: `dist/.prerender/chunks/*.mjs` holds the server-side bundle that rendered your pages, and it is discarded from the deployable output. That detail explains a class of surprises: the same `.svelte` file is compiled *three times* with different compiler options (client hydration build, SSR build, prerender build), and a module-level side effect in it executes in whichever environment imports it.

A Vite plugin can branch on `this.environment.name`:

```js
// A virtual module that must never reach the browser
resolveId(id) {
  if (id === '\0virtual:secrets') {
    if (this.environment.name === 'client') {
      throw new Error('This is a server-only module');
    }
    return id;
  }
}
```

Chapter 18 covers the integration and adapter APIs where this matters most. For application code the practical takeaways are: environment-specific code belongs behind imports that only the right environment reaches (a `.server.ts` convention is yours to adopt, Astro does not enforce it); and the Cloudflare adapter’s `prerenderEnvironment: 'node' | 'workerd'` option exists precisely because the `prerender` environment can run somewhere other than the production runtime.

## The Rust compiler and strict HTML

Astro 7.0 replaced the Go-based compiler with a Rust compiler (`@astrojs/compiler-rs`). It is the default and only compiler; the `experimental.rustCompiler` flag was removed. It is faster, and it is **stricter about invalid HTML**. Two behaviours change, and both matter when you migrate (Chapter 19) or when you have ever relied on the compiler to “fix” a template.

### Unclosed tags are errors

The old compiler silently accepted unclosed non-void elements and component tags. The Rust compiler requires a matching close for every non-void element. I confirmed this with a page containing:

```html
<div><p>hi
```

The build fails with a compiler error pointing at the end of the file:

```text
[CompilerError] Unexpected token
  Location: src/pages/x/bad.astro:2:0
```

The error location is where the parser *gave up*, usually the end of the file, not where you forgot to close the tag. When you see “Unexpected token” at the last line, look for unclosed elements above it. Void elements (`<br>`, `<img>`, `<input>`, `<hr>`, `<meta>`, `<link>`) need no closing tag.

### Invalid nesting is passed through, not repaired

The Go compiler restructured markup the way an HTML parser would: a `<div>` inside a `<p>` was moved out, a stray `<table>` child was hoisted. The Rust compiler emits what you wrote and leaves the browser to apply the HTML parsing algorithm. Compiling:

```html
<p>one<div>two</div></p>
<table><div>x</div></table>
```

produces, byte for byte, `<p>one<div>two</div></p><table><div>x</div></table>` (no error, no repair). The browser will then close the `<p>` early and foster-parent the `<div>` out of the table, producing a DOM that differs from your template. The server output is no longer “what the browser will see”, which affects hydration of framework components placed in invalid positions: if Svelte server-renders a `<div>` inside a `<p>` and the browser’s parser rewrites the structure, hydration mismatches follow. Fix invalid nesting at the source.

> **Warning:** Because invalid HTML is no longer normalized, a build that passed on Astro 6 can render differently on Astro 7 *without any error*. Visually diff your pages after the upgrade, and run an HTML validator in CI for template-heavy projects.

### CSS serialization differences

CSS processed by the Rust compiler may serialize differently: named colours become hex (`rebeccapurple` becomes `#639`) and `url()` quoting may change. These are cosmetic, but they break snapshot tests that string-match CSS.

## Whitespace: `compressHTML: 'jsx'`

Astro 7.0 changed the default of `compressHTML` from `true` to `'jsx'`. The option’s type is now `boolean | 'jsx'`:

- `'jsx'` (default): whitespace is handled by JSX rules. Whitespace-only text between sibling elements that are on separate lines is dropped.
- `true`: the previous HTML-aware compression, which preserved a single space between inline elements.
- `false`: preserve all whitespace.

I built this template under both settings:

```html
<span>hello</span>
<em>world</em>
```

With the default it emits `<span>hello</span><em>world</em>`, which renders as `helloworld`. With `compressHTML: true` it emits `<span>hello</span> <em>world</em>`, which renders as `hello world`. The fix that works under every setting is an explicit expression:

```html
<span>hello</span>{" "}<em>world</em>
```

Where this bites: navigation links in a `<nav>` where `<a>` elements are inline and separated only by newlines; inline icons next to text; a sentence broken across lines with `<strong>` or `<a>` in the middle. Where it does not bite: block-level elements and flex/grid children, whose whitespace is not rendered anyway. Pick `'jsx'` for new projects (smaller HTML, consistent with how you think about JSX in Svelte-free templates); set `compressHTML: true` during a large migration if you want the 6.x behaviour while you audit.

```js
// astro.config.mjs
import { defineConfig } from 'astro/config';

export default defineConfig({
  compressHTML: true, // keep Astro 6 whitespace behaviour during migration
});
```

Note that `compressHTML` applies to Astro-rendered HTML; Svelte renders its own markup (and its own whitespace rules, `preserveWhitespace` compiler option aside) inside islands. Svelte’s output above shows exactly this: in the island markup, spaces between `</h2>` and `<div>` were preserved by Svelte’s collapse-to-one-space behaviour.

## Platform baselines in Astro 7.4

| Component | Version / requirement |
|------------------------------------|------------------------------------|
| Node.js | `>= 22.22.0` (raised in 7.4.0; Astro 6.0 required 22.12) |
| Vite | 8 (Vite 7 in Astro 6.x) |
| Zod | 4 (since 6.0; import `z` from `astro/zod`) |
| Shiki | 4 (since 6.0) |
| Compiler | `@astrojs/compiler-rs` (Rust), only compiler |
| Markdown | Sätteri by default (7.0); `unified()` opt-in (Chapter 7) |
| `@astrojs/svelte` | 9.1.0; Svelte 5 only (integration v5 was for Svelte 3/4) |
| `@sveltejs/vite-plugin-svelte` | v7 |
| TypeScript | 6 supported; TypeScript 7 is not supported by `astro check` yet (the CLI explains how to try it experimentally) |

A few items deserve a sentence each.

- Config files can no longer be `.cjs` or `.cts` (removed in 6.0). Use `.mjs`, `.js`, `.ts` or `.mts`.
- `.env` files are not loaded inside `astro.config.*`; use `process.env` or `loadEnv` from `vite`. Application code should use `astro:env` (Chapter 16).
- `@astrojs/db` and the `astro db`, `login`, `logout`, `link` and `init` commands were removed in 7.0. Alternatives are `node:sqlite` or Drizzle.
- `src/fetch.ts` became a *reserved file name* in 7.0: Astro imports it automatically as the advanced-routing entrypoint. If you already have a `src/fetch.ts` for another purpose, either rename it or set `fetchFile` in the config (`fetchFile: null` disables the feature).

## Stable versus experimental in 7.4

Astro’s experimental flags live in `experimental` in the config, may change in patch releases, and are documented only for the current version. Knowing which features have graduated saves you from cargo-culting old blog posts.

### Promoted and stable

- **Advanced routing** (`src/fetch.ts`, `astro/fetch`, `astro/hono`), stable and on by default in 7.0. Chapter 5.
- **Rust compiler** (above).
- **Logger** (`logger` config, `logHandlers`), stable since 7.0. Chapter 17.
- **Queued/streaming rendering**, now the only renderer.
- **Route caching** (`cache`, `routeRules`, `memoryCache()`), top-level config since 7.0. Chapter 12.
- **Content Security Policy** (`security.csp`), **fonts**, **live content collections** and `prerenderConflictBehavior`, stable since 6.0.
- **Sessions**, stable since 6.x; `session: false` added in 7.2.

### Still experimental in 7.4

| Flag (`experimental.`) | Purpose | Chapter |
|------------------------|------------------------|------------------------|
| `clientPrerender` | Prerender pages on the client for faster navigation | 14 |
| `collectionStorage` | `'single-file'`, `'chunked'` or `{ type: 'chunked', chunkSize }` data-store storage (7.1) | 6 |
| `incrementalBuild` | Reuse prior build output (7.2) | 6, 17 |
| `parallelPrerender` | `boolean | { workers }` parallel prerendering (7.4) | 17 |
| `redirectPage` | Custom `src/pages/3xx.astro` for static redirects (7.4) | 5 |
| `svgOptimizer` | SVG optimization (`svgoOptimizer()`) | 13 |
| `chromeDevtoolsWorkspace`, `contentIntellisense` | Tooling integrations | 17 |

Two more things are experimental *without* being behind `experimental`: the **Container API** (`experimental_AstroContainer` from `astro/container`, Chapter 17) and the **adapter CDN cache providers** (`cacheNetlify()`, `cacheVercel()`, `cacheCloudflare()`, which “need to be manually enabled” during their experimental phase, Chapter 12). It is slightly awkward that core route caching is stable while the CDN providers that make it useful on a given host are not; plan around it.

> **Senior tip:** Treat experimental flags as a dependency-pinning decision. If you enable one, pin Astro to an exact version in `package.json` (no caret) and read the CHANGELOG on every bump. The documentation explicitly reserves the right to break them in patch releases.

## Project setup with `@astrojs/svelte`

The fastest path is `npm create astro@latest` followed by `npx astro add svelte`, which edits `astro.config.mjs`, installs dependencies and creates `svelte.config.js`. Doing it by hand once is instructive, because every file is load-bearing.

```bash
mkdir shop && cd shop
npm init -y
npm install astro@7.4.1 @astrojs/svelte@9.1.0 svelte@5.57.2 typescript
```

Set `"type": "module"` and scripts in `package.json`:

```json
{
  "name": "shop",
  "type": "module",
  "private": true,
  "scripts": {
    "dev": "astro dev",
    "build": "astro check && astro build",
    "preview": "astro preview"
  },
  "dependencies": {
    "@astrojs/svelte": "9.1.0",
    "astro": "7.4.1",
    "svelte": "5.57.2",
    "typescript": "^6.0.0"
  }
}
```

Install `svelte` and `typescript` yourself if your package manager does not install peers; the docs say a `Cannot find package 'svelte'` warning means exactly that.

```js
// astro.config.mjs
import { defineConfig } from 'astro/config';
import svelte from '@astrojs/svelte';

export default defineConfig({
  integrations: [svelte()],
});
```

```js
// svelte.config.js
import { vitePreprocess } from '@astrojs/svelte';

export default {
  preprocess: vitePreprocess(),
};
```

`vitePreprocess()` is re-exported from `@astrojs/svelte` (originally from `@sveltejs/vite-plugin-svelte`). It lets TypeScript-only features and `<style lang="scss">` blocks be preprocessed through Vite. Since integration 6.0.0 it is *not* added by default, so a project that never creates `svelte.config.js` has no preprocessing; `lang="ts"` still works because Svelte 5 itself strips type annotations, but SCSS and Stylus do not. Options passed to `svelte({...})` in `astro.config.mjs` take precedence over `svelte.config.js` (Chapter 3).

```json
{
  "extends": "astro/tsconfigs/strict",
  "include": [".astro/types.d.ts", "**/*"],
  "exclude": ["dist"]
}
```

Astro ships three tsconfig templates, `base`, `strict` and `strictest`. Using `strict` or `strictest` is recommended for TypeScript projects; the presets enable `verbatimModuleSyntax`, which forces `import type` for type-only imports. This matters under Astro’s bundler: a type-only import that is not marked `type` may be treated as a runtime import.

A first end-to-end page that proves the whole chain:

```html
<!-- src/components/Counter.svelte -->
<script lang="ts">
  let { initial = 0 }: { initial?: number } = $props();
  let count = $state(initial);
  const doubled = $derived(count * 2);
</script>

<button onclick={() => count++}>
  {count} (×2 = {doubled})
</button>
```

```html
---
// src/pages/index.astro
import Counter from '../components/Counter.svelte';
---
<html lang="en">
  <head><meta charset="utf-8" /><title>Shop</title></head>
  <body>
    <h1>Static heading, zero JS</h1>
    <Counter initial={2} />
    <Counter client:visible initial={10} />
  </body>
</html>
```

The first `<Counter />` has no directive: it is server-rendered HTML with a dead button. The second hydrates when it scrolls into view. Run `astro build` and inspect `dist/index.html`: you will find exactly one `<astro-island>`, the island runtime script, the `visible` directive script, and a `_astro/Counter.*.js` file plus a shared `client.svelte.*.js` renderer and a Svelte runtime chunk. The total JavaScript is the cost of one island, not of the page.

### Editor and type checking

`astro dev` and `astro build` do not type-check. `astro check` checks `.astro` and `.ts` files but **does not check `.svelte` files**; run `svelte-check` for those. A robust CI script runs both:

```json
{
  "scripts": {
    "check": "astro check && svelte-check --tsconfig ./tsconfig.json"
  }
}
```

Chapter 2 covers TypeScript setup, and Chapter 3 covers the `svelte-shims.d.ts` that makes Svelte components usable (with `client:*` directive typings and optional snippet props) inside `.astro` files.

## Dev server, preview and agents

`astro dev` starts the dev server on port 4321 (`server.port`). Since 7.0 it can run in the background: `astro dev --background`, then `astro dev status`, `astro dev logs [-f]`, `astro dev stop`, with a lock file at `.astro/dev.json`. Background mode starts automatically when Astro detects that it is being launched by an AI agent (not on Windows); `ASTRO_DEV_BACKGROUND=0` opts out, and `--ignore-lock` (7.1) starts an additional untracked foreground instance. `astro preview` gained the same `--background` family in 7.2 (`ASTRO_PREVIEW_BACKGROUND=0` opts out; `--ignore-lock` since 7.3). `astro build --timings` (7.4) prints per-phase timings. Details are in Chapter 17.

## A mental model to carry forward

When something surprising happens in an Astro project, ask four questions in order.

1.  **Which environment is this code running in?** (`client`, `ssr`, `prerender`, or dev’s `astro`.) Many “works in dev, fails in build” issues are an import reaching the wrong environment.
2.  **At what time does it run?** Build time, request time, or browser time? Frontmatter is never browser time.
3.  **Is this an island, and has it hydrated yet?** A `client:visible` island is plain HTML until it scrolls into view. State lives only after hydration; before that you have the server-rendered snapshot.
4.  **What crossed the boundary, and how was it serialized?** Props cross as JSON-like data in an HTML attribute; children cross as static HTML strings; functions do not cross at all.

The rest of the book elaborates these four questions.

## Key takeaways

- Astro renders HTML on the server and ships no JavaScript unless you add a `client:*` directive. The cost of a page scales with its islands, not its size.
- A client island is an `<astro-island>` custom element whose attributes declare the component URL, renderer URL, serialized props, directive and options. A server island (`server:defer`) is dynamic server-rendered HTML, not JavaScript.
- Frontmatter runs once per render: at build time for prerendered routes, per request for on-demand ones. It never runs in the browser.
- `output` is `'static'` (default) or `'server'`; individual routes override with `export const prerender`. On-demand routes require an adapter, otherwise the build fails with `NoAdapterInstalled`.
- Astro builds with four Vite environments: `client`, `ssr`, `prerender` and (dev only) `astro`. The same `.svelte` file is compiled for each.
- The Rust compiler (7.0) errors on unclosed tags and no longer repairs invalid nesting; a template that built before may now render differently without an error.
- `compressHTML` defaults to `'jsx'` in 7.0; `<span>a</span>\n<em>b</em>` renders `ab`. Use `{" "}` or set `compressHTML: true`.
- Baselines in 7.4: Node 22.22.0+, Vite 8, Zod 4, Shiki 4, Sätteri, `@astrojs/svelte` 9.1 with Svelte 5 only.
- Advanced routing, logger, route caching, CSP, fonts, live collections and sessions are stable. `clientPrerender`, `collectionStorage`, `incrementalBuild`, `parallelPrerender`, `redirectPage` and `svgOptimizer` are still experimental, as are the Container API and the adapter CDN cache providers.
- `astro check` does not check `.svelte` files; add `svelte-check`.

## Review Questions

1.  Explain why the cost of an Astro page scales with the number of islands rather than the number of components. Which of the following does *not* add client JavaScript: (a) an `.astro` component with 500 nested children, (b) a Svelte component without a `client:*` directive, (c) a Svelte component with `client:visible`, (d) a `<script>` tag in an `.astro` file?

2.  In which situations is an SPA still a better choice than islands? Name two concrete characteristics of a site that argue for it, and describe how to embed an SPA inside an Astro page when you need one.

3.  What is the difference between a client island and a server island? Give one example use case of each from an e-commerce page.

4.  Look at the following snippet. When does the `console.log` execute for a prerendered route, and when for an on-demand route?

    ```html
    ---
    console.log('rendering', Astro.url.pathname);
    ---
    <h1>Hi</h1>
    ```

5.  Your project has `output: 'static'` and a page exports `prerender = false`, but no adapter is configured. What happens, and what error name appears?

6.  Why can’t you call `Astro.redirect()` from a child component of an on-demand page? What property of the renderer causes this?

7.  A teammate puts `localStorage.getItem('cart')` at the top level of a Svelte component’s `<script>` and uses it with `client:load`. What goes wrong, and which two mechanisms in Svelte 5 would you use to fix it?

8.  List the four Vite environments in an Astro 7 project and say which of them exists only in development.

9.  After a static build, you find `dist/.prerender/chunks/`. What is it, and why is it not shipped?

10. Find the bug. The page below builds on Astro 6 but fails on Astro 7. Why, and what is the minimal fix?

    ```html
    <Layout>
      <p>Welcome
    </Layout>
    ```

11. What does the following render under Astro 7 defaults, and what does it render with `compressHTML: true`? Give a fix that is correct under both.

    ```html
    <a href="/a">Home</a>
    <a href="/b">Blog</a>
    ```

12. Multiple choice. Under the Rust compiler, `<p><div>text</div></p>` in an `.astro` template: (a) fails to build; (b) is rewritten to `<div>text</div>` by the compiler; (c) is emitted as written and the browser then repairs the DOM; (d) is wrapped in a Fragment automatically.

13. Why might hydration of a Svelte component fail after upgrading to Astro 7 if that component is placed inside an invalid HTML parent, even though the build succeeds?

14. What are the permitted values of `output` in Astro 7.4? What happened to `'hybrid'`, and how do you now get hybrid behaviour?

15. Which Node version is required by Astro 7.4, and which Vite, Zod and Shiki major versions does it use?

16. Name three features that were experimental in Astro 6 and are stable (no `experimental` key) in 7.4. Name three that are still behind `experimental`.

17. True or false, with justification: “Because route caching is stable, `cacheVercel()` from `@astrojs/vercel/cache` is also stable.”

18. What does `src/fetch.ts` do in Astro 7, and what are two ways to deal with a pre-existing `src/fetch.ts` that is unrelated?

19. You run `astro check` in CI and it passes, but a type error exists in a `.svelte` file. Why, and how do you close the gap?

20. Which attributes on `<astro-island>` tell the browser what to import, and which tell it how to start? Which attribute leaks data into the page source, and what policy follows from that?

21. Design question. A product page has a static description, an image gallery that should be interactive only on desktop, an “add to cart” button that must work immediately, and reviews at the bottom of the page. Choose a client directive for each interactive piece and justify the choices.

22. Why is `vitePreprocess()` imported from `@astrojs/svelte` and what stops working in a project that has no `svelte.config.js`? What still works?

23. What does the following do, and why is it a reasonable choice during a migration?

    ```js
    export default defineConfig({ compressHTML: true });
    ```

24. Multiple choice. Which statement about the `prerender` Vite environment is correct? (a) It runs in the browser during development; (b) it builds the code that renders static pages at build time; (c) it replaces the `ssr` environment in production; (d) it only exists with the Cloudflare adapter.

25. In the `<astro-island>` runtime, what happens to an island whose `client:visible` element is never scrolled into view? What does the user have in the meantime?

26. Explain the sentence “State lives only after hydration” with respect to a `client:idle` Svelte counter that the user clicks 50 ms after page load, before the browser has become idle.
