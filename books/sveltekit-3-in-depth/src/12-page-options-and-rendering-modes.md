# Chapter 11: Page Options and Rendering Modes

SvelteKit’s defining design decision is that rendering strategy is a per-route property, not a per-application one. The same codebase can serve a prerendered marketing site, a server-rendered dashboard, a client-only admin console and a zero-JavaScript legal page, each with different caching, SEO and failure characteristics. The mechanism is a small set of exported constants called *page options* (`prerender`, `entries`, `ssr`, `csr`, `trailingSlash`, `config`) plus a handful of build-level options in `sveltekit({...})` that shape what the prerenderer and the bundler do.

This chapter covers each option precisely, including how they are inherited and how SvelteKit reads them (statically or by importing your module), the mechanics of the prerenderer, the real behaviour of SPA mode and the hash router, how to ship a `csr = false` page, the bundle strategies (`split`, `single`, `inline`), inline styles, and the options for embedding an app or serving it from a sub-path. Remember that in SvelteKit 3 all build options live in the `sveltekit()` plugin call in `vite.config.ts`; there is no `svelte.config.js`. All examples use `#lib` rather than `$lib` (see Chapter 1).

## The model: four independent switches

Every request that matches a page route is evaluated against four independent decisions:

| Option | Question it answers | Default |
|------------------------|------------------------|------------------------|
| `prerender` | Is the HTML produced at build time, or at request time? | `false` |
| `ssr` | Is the component tree rendered on the server at all? | `true` |
| `csr` | Is JavaScript shipped to hydrate and take over navigation? | `true` |
| `trailingSlash` | What is the canonical URL shape? | `'never'` |

Plus `entries` (which dynamic URLs the prerenderer should visit) and `config` (an opaque bag read by the adapter).

You export them from `+page.ts`, `+page.server.ts`, `+layout.ts` or `+layout.server.ts`. A value exported from a layout applies to every page below it; child layouts and pages override parents. The root layout is therefore the “app-wide” setting:

```ts
// src/routes/+layout.ts
export const prerender = true;       // prerender everything...
```

```ts
// src/routes/(app)/dashboard/+page.ts
export const prerender = false;      // ...except this route
export const ssr = true;
```

Resolution is straightforward: SvelteKit walks the layout chain from the root down to the page and takes the last defined value. Universal and server files can both export options; for `config`, the universal file takes precedence over the server file as of 3.0, and `config` objects are merged at the top level only.

### Static analysis versus importing your module

SvelteKit needs to know the page options *before* it renders the page, at build time (for the manifest and for deciding which routes are prerenderable) and at runtime (for deciding whether to render on the server, and which scripts to include). There are two ways it can learn them:

1.  **Static analysis.** If every page option in a file is a boolean or string *literal*, SvelteKit reads it from the source without executing anything.
2.  **Importing the module.** If any option is computed (`export const csr = dev;`), SvelteKit has to import the file on the server, both at build time and, if the app is not fully static, at request time.

The consequence is a rule you need to internalise: **a file whose options are non-literal is executed on the server, so browser-only code must not run at module load.** A `+page.ts` that does `import mapboxgl from 'mapbox-gl'` at the top and exports `export const csr = dev` will crash during analysis, because `window` does not exist. Import browser-only dependencies in `+page.svelte` (or lazily inside `load` guarded by `browser`) instead.

> **Senior tip:** Prefer literal options. They keep route metadata cheap to compute, make the build deterministic, and let tooling (and your colleagues) read a route’s rendering mode with grep. Reserve computed options for the one or two places (such as `csr = dev`) where you need them.

## Choosing a rendering mode per route

The four switches combine into the familiar named modes:

| Mode | `prerender` | `ssr` | `csr` | HTML source | JS shipped | Typical use |
|----------|----------|----------|----------|----------|----------|----------|
| SSR + hydration (default) | false | true | true | server, per request | yes | Dynamic, personalised, SEO-relevant pages |
| Prerendered + hydration | true | true | true | build time | yes | Marketing, docs, blog with interactive widgets |
| Prerendered, no JS | true | true | false | build time | none | Legal pages, simple articles |
| SSR, no JS | false | true | false | server | none | Server-driven pages with plain forms and links |
| SPA shell | false | false | true | static fallback | yes | Authenticated admin tools, wrapped apps |
| Nothing | any | false | false | empty shell | none | Pointless; SvelteKit warns that nothing will render |

The trade-offs are the standard web ones, but it is worth being explicit about what *failure* looks like for each, since seniors choose modes by failure mode:

- **SSR** fails when your server or database is down; every request depends on them. It scales with traffic and gives fresh data.
- **Prerender** moves failures to build time. Runtime is a static file server; the CDN can absorb any traffic spike. The cost is staleness: content changes require a rebuild and deploy, and the build can fail because *one* of ten thousand pages errors.
- **SPA** fails when JavaScript fails (network, extensions, enterprise proxies) and shows a blank page until the bundle, the manifest and the data have loaded: three sequential round trips. It does not require a server, which is its only real advantage.
- **`csr = false`** fails least: it is HTML and CSS. It cannot use `use:enhance`, client-side navigation or any component `<script>` logic.

The framework documentation is blunt about SPA mode: it has a large negative effect on performance and SEO and should be used only in limited circumstances, such as an app wrapped in a mobile shell served from the local filesystem. A hybrid, in which public pages are prerendered or server-rendered and a private area is `ssr = false`, captures most of the benefit without the drawbacks on pages that matter.

A realistic layout that mixes all of these:

```text
src/routes/
  +layout.ts                  # export const trailingSlash = 'always';
  (marketing)/
    +layout.ts                # export const prerender = true;
    +page.svelte              # /
    pricing/+page.svelte      # /pricing
    legal/
      +layout.ts              # export const csr = false;
      terms/+page.svelte
  blog/
    +layout.ts                # export const prerender = 'auto';
    [slug]/
      +page.server.ts         # entries() for the top posts
  (app)/
    +layout.ts                # export const ssr = false;  (SPA area)
    dashboard/+page.svelte
  api/
    health/+server.ts
```

Note that the route group `(marketing)` carries no URL segment but gives you a layout boundary to attach options to (see Chapter 3).

## `prerender`

`prerender` accepts `true`, `false` or `'auto'`.

```ts
// src/routes/about/+page.ts
export const prerender = true;
```

With `true`, the route is rendered at build time and written to disk. It is also **excluded from the manifest used for dynamic SSR**, which makes the server (or serverless bundle) smaller. The flip side is that if a request arrives for a route marked `true` that the prerenderer never produced, there is no runtime fallback: the route does not exist at runtime. That is the origin of the most common prerendering build error, discussed below.

With `'auto'`, the route is prerendered *and* kept in the manifest. This is the right choice for something like `/blog/[slug]`, where you want your most popular posts prerendered but the long tail rendered on demand:

```ts
// src/routes/blog/[slug]/+page.server.ts
import type { EntryGenerator, PageServerLoad } from './$types';
import { getTopPosts, getPost } from '#lib/server/posts.js';
import { error } from '@sveltejs/kit';

export const prerender = 'auto';

export const entries: EntryGenerator = async () => {
    const posts = await getTopPosts(100);
    return posts.map((p) => ({ slug: p.slug }));
};

export const load: PageServerLoad = async ({ params }) => {
    const post = await getPost(params.slug);
    if (!post) error(404, 'Post not found');
    return { post };
};
```

`EntryGenerator` is a type generated into `./$types` for each route (it is `() => Promise<Array<RouteParams>> | Array<RouteParams>`). Its return value is checked against the route’s parameters.

### The golden rule, and what it excludes

The rule from the docs: for a page to be prerenderable, **any two users hitting it directly must get the same content from the server.** A page that renders `locals.user.name` cannot be prerendered. A page whose *shell* is identical for everyone and which fetches personalised data in `onMount` or via a client-side query can be, at the cost of the loading state a SPA would have shown for that region.

Hard restrictions enforced by SvelteKit:

- **Pages with form actions cannot be prerendered.** Actions are `POST` handlers, and a static host cannot serve them. SvelteKit throws if a route that is marked prerenderable exports `actions`.
- **Reading `url.searchParams` while prerendering is an error.** There is no query string at build time. Use it only in the browser.
- **`getClientAddress()` throws during prerendering**, for the same reason.
- A route cannot have both a `+page` and a `+server` that are both marked prerenderable: this fails early since the two would write the same file.

### Prerendering server routes

`prerender` also applies to `+server.ts`. Unlike the other options, endpoints are *not* affected by layouts. They inherit a default from the *pages that fetch them*:

```ts
// src/routes/+page.ts
export const prerender = true;

export const load = async ({ fetch }) => {
    const res = await fetch('/stats.json');
    return await res.json();
};
```

Here `src/routes/stats.json/+server.ts` is treated as prerenderable because a prerendered page fetched it, unless it contains `export const prerender = false`. During the prerender crawl, the endpoint’s response is saved as a dependency of the page, so a fully static deployment works. If you want the endpoint to stay dynamic, say so explicitly.

### Route and filename conflicts

Prerendering writes files. A directory and a file cannot have the same name, so `src/routes/foo/+server.ts` and `src/routes/foo/bar/+server.ts` would both need to create `foo` (once as a file, once as a directory). Give endpoints an extension (`foo.json`, `foo/bar.json`). Pages avoid the problem because they are written as `foo/index.html` (with `trailingSlash: 'always'`) or `foo.html` (otherwise).

### The prerender cache-control meta tag

One subtle behaviour: if a prerendered page’s `load` calls `setHeaders({ 'cache-control': ... })`, SvelteKit converts that into a `<meta http-equiv="cache-control">` tag in the generated HTML, because a static file has no headers of its own. Other headers set in `setHeaders` are not converted. Static hosts decide response headers for the file; configure them there (see Chapter 16).

## `entries` and how the crawler discovers pages

The prerenderer starts from *entry points* and crawls. By default every route without required parameters is an entry point. For:

```text
/             # static
/blog         # static
/blog/[slug]  # dynamic
```

`/` and `/blog` are prerendered, and while rendering them the crawler extracts `<a href>` values pointing at other prerenderable pages, discovering `/blog/hello-world` as it goes. Two limits matter:

1.  **Only links in pages that were themselves prerendered (and have SSR on) are followed.** Pages not marked prerenderable are ignored and their links are not crawled, even if some targets would have been prerenderable.
2.  **Links generated by client-side code are invisible.** The crawler sees HTML, not behaviour.

When links do not reach every dynamic URL, you declare entries:

- Per route, by exporting `entries` (shown above). It can be `async`, so it can query a CMS or database.
- Globally, through the `prerender.entries` option in `sveltekit({...})`.

```ts
// vite.config.ts
import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-static';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [
        sveltekit({
            adapter: adapter(),
            prerender: {
                entries: ['*', '/sitemap.xml', '/feed.xml', '/blog/legacy-post'],
                concurrency: 4,
                crawl: true
            }
        })
    ]
});
```

`entries` here is an array of `'*'` or absolute paths. `'*'` means “all routes without required parameters” (optional parameters are included as if empty). `concurrency` defaults to 1; raise it when generation is network-bound, for instance when each page pulls data from a remote CMS. JavaScript is single-threaded, so more concurrency helps only while pages wait on I/O. Setting `crawl: false` makes the prerenderer visit *only* the listed entries, which is useful for fully explicit builds.

### Failure handlers

The prerenderer is strict by default. Five `handle*` options control what happens when something is suspicious. Each defaults to `'fail'` and accepts `'fail'`, `'warn'`, `'ignore'` or a function:

| Option | Triggers when | Details object |
|------------------------|------------------------|------------------------|
| `handleHttpError` | A crawled URL returned an error status (a broken link, or a 404 path outside `paths.base`) | `status`, `path`, `referrer`, `referenceType`, `message` |
| `handleMissingId` | `<a href="/x#foo">` where `/x` has no element with `id="foo"` | `path`, `id`, `referrers`, `message` |
| `handleEntryGeneratorMismatch` | A URL from `entries()` resolved to a different route than the one that generated it | `generatedFromId`, `entry`, `matchedId`, `message` |
| `handleUnseenRoutes` | A route marked `prerender = true` was never reached | `routes`, `message` |
| `handleInvalidUrl` | The crawler found an `href` it cannot parse (an `at://` URL, for example) | `href`, `referrer`, `message` |

A function handler should `throw` to fail the build; returning normally means “tolerated”. Here is a handler set suited to a docs site where a known set of links is deliberately dead:

```ts
// vite.config.ts (excerpt)
sveltekit({
    prerender: {
        handleHttpError: ({ path, referrer, message, status }) => {
            // a deliberately linked custom 404 demo page
            if (path === '/not-found' && referrer === '/blog/how-we-built-our-404-page') return;
            // on a docs site, treat broken external-looking internal paths as warnings
            if (status === 404 && path.startsWith('/archive/')) {
                console.warn(`[prerender] ${status} ${path} (from ${referrer})`);
                return;
            }
            throw new Error(message);
        },
        handleMissingId: 'warn',
        handleUnseenRoutes: ({ routes }) => {
            // CMS may legitimately have no content for some sections
            const unexpected = routes.filter((r) => !r.startsWith('/docs/optional'));
            if (unexpected.length) throw new Error(`Unreached routes:\n${unexpected.join('\n')}`);
        },
        handleInvalidUrl: 'ignore'
    }
})
```

### Troubleshooting “routes were marked as prerenderable, but were not prerendered”

This error means a route (or a parent layout) has `prerender = true` but the crawler never reached it. Because such a route is not in the runtime manifest, it would 404 in production, so SvelteKit fails the build. Your options:

1.  Make it reachable: link to it from a prerendered page, add it to `prerender.entries`, or export `entries()` for a dynamic route.
2.  Change `true` to `'auto'` so that it can also be rendered dynamically.
3.  If the route is legitimately sometimes unreachable, relax `handleUnseenRoutes`.

### `building` and side effects at build time

SvelteKit loads your `+page`/`+layout` modules (and everything they import) for analysis during `vite build`, and renders prerendered pages by running the real server. Code that must not run in either phase (opening database pools, starting schedulers) must check `building`, imported from `$app/env` in SvelteKit 3:

```ts
// src/hooks.server.ts
import { building } from '$app/env';
import { connectPool } from '#lib/server/db.js';

if (!building) {
    connectPool();
}
```

`building` is `true` for analysis *and* while prerendering. This is the supported way to distinguish “the app is running” from “the build is inspecting the app”. (`$app/environment` is the deprecated 2.x name, removed in 4; see Chapter 13.)

## `ssr`

```ts
// src/routes/(app)/+layout.ts
export const ssr = false;
```

When `ssr` is `false`, SvelteKit renders an *empty shell* (your `app.html` with an empty body and the bootstrapping script) and the entire tree, including every `load` function, runs in the browser. Server `load` functions (`+page.server.ts`) still run on the server and are fetched through `__data.json` requests on the client, so `ssr = false` is not the same as “no server code”.

Consequences you should plan for:

- **No server-rendered content**: crawlers that do not execute JavaScript see nothing, and first paint waits for JS.
- **Browser globals become safe** in component initialisation and universal `load`. That is the legitimate reason to use it: a charting, map or canvas-heavy page whose libraries cannot run on Node.
- **Form posts without JS are lost.** A non-enhanced form `POST` to an `ssr = false` page returns the shell, and the action result has nowhere to render (SvelteKit warns about this in development).
- **Set at the root, it makes the whole app an SPA.** Do that only deliberately and never when you want a static site: a static site needs prerendered HTML, which requires SSR at build time.

Disabling SSR for one page is better than for the whole app. Many teams use `ssr = false` on a single leaf route that embeds a canvas editor, and keep the rest of the app server-rendered.

### `ssr = false` combined with prerender

You can set both `ssr = false` *and* `prerender = true`. If the page has no server data to serialise, the result is a prerendered empty shell (equivalent to an SPA fallback for that URL, useful for hosts that need a real file at each path). Nothing about this gives you pre-rendered content.

## `csr`

```ts
// src/routes/legal/terms/+page.ts
export const csr = false;
```

With `csr = false`, SvelteKit ships **no JavaScript** for the page: no router, no hydration. This implies:

- The page must work with HTML and CSS alone.
- `<script>` blocks in all components on that page are removed.
- Forms cannot be progressively enhanced (`use:enhance` does nothing); they perform full-page POSTs.
- Links trigger browser full-page navigations.
- HMR is disabled for it.

Because `csr` is evaluated with the same rules as the other options, you can keep it on during development to retain HMR:

```ts
// src/routes/legal/+layout.ts
import { dev } from '$app/env';

export const csr = dev;
```

Note that this is a *non-literal* option, so the file is imported on the server at analysis time. `dev` is safe to import there.

### Design implications of zero-JS pages

When `csr = false`, anything your layout does in `onMount` or via `$effect` simply does not happen on that page: no analytics beacon, no theme toggle, no cookie banner logic. Put critical behaviour (analytics via a server-side beacon or a `<noscript>` image, theme via `prefers-color-scheme` and CSS) into plain HTML and CSS. If the root layout contains navigation that depends on JavaScript (a hamburger menu implemented with state), nest your zero-JS pages under a layout that does not use it, via a layout reset (`+page@.svelte`, Chapter 3), or implement the menu with `<details>` so that it works anyway.

Pairing `csr = false` with `prerender = true` gives you the closest thing to a hand-written static HTML page: a file per route with inlined or linked CSS and nothing else.

### Hydration concerns on the default path

On the default path (`ssr` and `csr` both true), the server HTML is hydrated: Svelte attaches to the existing DOM and expects it to match what it would render. Things that break hydration are deterministic-render violations: reading `Date.now()`, `Math.random()`, `window.innerWidth`, or locale-dependent formatting differences between server and browser. Svelte 5 handles some mismatches by repairing the DOM and warning in development; do not rely on that. Seed anything non-deterministic from data that is serialised from the server (a timestamp returned by `load`, an id generated in `load`), or defer it to after mount (`$effect`, `onMount`).

## `trailingSlash`

```ts
// src/routes/+layout.ts
export const trailingSlash = 'always';
```

Values: `'never'` (default), `'always'`, `'ignore'`. With `'never'`, a request for `/about/` receives a redirect to `/about`; `'always'` redirects the other way. `'ignore'` serves both and is discouraged because `/x` and `/x/` are different URLs to search engines and relative links resolve differently (`./y` from `/x` is `/y`, from `/x/` is `/x/y`).

`trailingSlash` also controls prerender filenames: `'always'` produces `about/index.html`, otherwise `about.html`. Choose to match the static host you deploy to. Some hosts (GitHub Pages, S3 website endpoints) serve `about/index.html` for `/about/` but not `about.html` for `/about`, which is why `'always'` is the usual choice for static hosting without rewrite rules. It can be exported from `+server` files too. Chapter 3 covers `normalizeUrl` for dealing with the inconsistency in your own code.

## `config`

`config` is an adapter-defined object exported from a page, layout or endpoint. Its shape is not defined by SvelteKit; each adapter publishes a `Config` type. The merge rule is the only thing SvelteKit contributes: top-level keys are merged, deeper levels are replaced.

```ts
// src/routes/+layout.ts
export const config = {
    runtime: 'nodejs22.x',
    regions: 'all',
    foo: { bar: true }
};
```

```ts
// src/routes/reports/+page.ts
export const config = {
    regions: ['iad1', 'fra1'],
    foo: { baz: true }
};
```

For `/reports` the effective config is `{ runtime: 'nodejs22.x', regions: ['iad1', 'fra1'], foo: { baz: true } }`: `regions` replaced, `foo` replaced as a whole (not deep-merged), `runtime` inherited. Edge runtimes are gone from the Vercel adapter in 3.0; consult Chapter 18 for each adapter’s actual keys and do not copy examples from SvelteKit 2 era blog posts.

## SPA mode and the fallback page

An SPA in SvelteKit is the combination of `ssr = false` (so no HTML is rendered for those routes) and a *fallback page*: a single HTML file the host serves for any URL it does not otherwise recognise. The fallback is generated from your `app.html` template and contains the bootstrapping script that loads the app and navigates to the current URL.

```ts
// src/routes/+layout.ts
export const ssr = false;
```

```ts
// vite.config.ts
import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-static';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [
        sveltekit({
            adapter: adapter({
                fallback: '200.html'  // host-specific name
            })
        })
    ]
});
```

Details worth knowing:

- Avoid naming the fallback `index.html`: it may collide with the prerendered root page.
- The fallback always uses **absolute** asset paths (`/_app/...`), regardless of `paths.relative`, because it answers requests for arbitrary paths.
- `adapter-static` only works if you have no server logic: no `+page.server.ts`, `+layout.server.ts` or `+server.ts` that would be needed at runtime. If you do have server code, use an adapter that runs a server and set `ssr = false` only on the pages that need it. In that setup the “fallback” is produced at runtime by the server.
- The host must be configured to serve the fallback for unknown routes. For Apache, a `static/.htaccess` with rewrite rules pointing to `/200.html`; for Nginx, `try_files $uri $uri.html /200.html`; most static platforms have an SPA toggle.

### Hybrid: opt specific routes back into prerendering

```ts
// src/routes/(marketing)/+layout.ts
export const prerender = true;
export const ssr = true;
```

With the root `ssr = false`, this re-enables SSR (at build time, for output) for the marketing group. Your deployment is still entirely static, yet the homepage ships real HTML. This hybrid is the single best mitigation for SPA drawbacks: prerender everything public, SPA the authenticated area.

### Hash router

When you do not control the web server at all (a `file://` page, a static bucket with no rewrite capability), you can configure client routing by hash:

```ts
// vite.config.ts (excerpt)
sveltekit({
    router: { type: 'hash' }
})
```

With `router.type: 'hash'` the route is derived from `location.hash` (`/#/settings`), SSR and prerendering are disabled, and you cannot use server logic. Every internal link must start with `#/`:

```html
<a href="#/settings">Settings</a>
```

Beyond those caveats, everything else (layouts, `load`, `$app/state`) works as in a normal app. In that mode SvelteKit only emits a fallback `index.html`. The hash router is the only option when `pathname` routing cannot work; if you can configure a rewrite rule, prefer the SPA fallback because hash URLs are worse for analytics, sharing and accessibility (in-page anchors collide with route hashes).

### Mobile and desktop wrappers: `bundleStrategy`

A Capacitor, Tauri or Electron wrapper loads your app from local files. Network round trips are free, but many small files are not: each chunk is a filesystem read through the webview’s custom scheme, and some wrappers handle ES module loading poorly. For such targets, change the bundle strategy:

```ts
// vite.config.ts
import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-static';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [
        sveltekit({
            adapter: adapter({ fallback: 'index.html' }),
            output: { bundleStrategy: 'single' },
            router: { type: 'hash' }
        })
    ],
    build: { assetsInlineLimit: Infinity }
});
```

Pair it with `export const ssr = false` and `export const prerender = false` at the root layout.

## `output.bundleStrategy` and `inlineStyleThreshold`

`output.bundleStrategy` controls how the client JavaScript and CSS are packaged:

| Value | Output | When |
|------------------------|------------------------|------------------------|
| `'split'` (default) | Many `.js`/`.css` files, loaded lazily as the user navigates | Almost always; best cache granularity and initial load |
| `'single'` | One `.js` and one `.css` for the entire app | Wrappers, hosts with high per-request cost, HTTP/1.1 constraints |
| `'inline'` | All JS and CSS inlined into the HTML | Files opened without a server; single-file distributions |

With `'split'`, you can fine-tune chunking via Vite’s `build.rolldownOptions.output.codeSplitting` (Vite 8 uses Rolldown). If you want to inline imported assets too, set Vite’s `build.assetsInlineLimit` and import the assets through Vite so that they are processed:

```ts
// vite.config.ts
export default defineConfig({
    plugins: [sveltekit({ output: { bundleStrategy: 'inline' } })],
    build: { assetsInlineLimit: Infinity }
});
```

```html
<!-- src/routes/+layout.svelte -->
<script lang="ts">
    import favicon from './favicon.png'; // imported through Vite so that it can be inlined
    let { children } = $props();
</script>

<svelte:head>
    <link rel="icon" href={favicon} />
</svelte:head>

{@render children()}
```

Assets referenced by string path from `static/` are not processed and so are not inlined.

`inlineStyleThreshold` (default `0`) is a number: the maximum length, in UTF-16 code units, of a CSS file to be inlined into a `<style>` block in the document head. All CSS files needed by the page that are *individually* under the threshold are merged and inlined. This avoids render-blocking stylesheet requests and can improve First Contentful Paint, at the cost of larger HTML, no browser caching of the inlined CSS between pages, and (on dynamic pages) more bytes per response. A threshold around `4000`–`10000` is common for small apps; for large apps with shared global CSS, inlining defeats caching and usually loses. Measure.

Also note `output.linkHeaderPreload` (new in 3.0, default `false`): when enabled, dynamically rendered pages announce preloads via a `Link` response header instead of `<link>` elements. Some proxies (nginx, Apache defaults) limit header size, so leave it off unless you have verified yours. Preload strategy options (`preloadStrategy`) are gone; `modulepreload` is always used.

## Embedding and sub-path deployment

### `embedded`

```ts
// vite.config.ts (excerpt)
sveltekit({ embedded: true })
```

When your app is mounted inside a larger page (a widget in someone else’s site, a micro-frontend), set `embedded: true`. SvelteKit then attaches its navigation listeners to the *parent of `%sveltekit.body%`* rather than `window`, and passes `params` from the server instead of deducing them from `location.pathname`, which would be the host page’s path. Be aware of the limitation the docs state: embedding **multiple** SvelteKit apps on one page and using client-side SvelteKit features in each is not supported, since features like history `pushState` assume a single instance.

### `paths.base`, `paths.assets` and `paths.relative`

To serve the app from a sub-path (`https://example.com/tools/`), set `paths.base`:

```ts
// vite.config.ts (excerpt)
sveltekit({
    paths: {
        base: '/tools',            // must start with '/', must not end with '/'
        assets: '',                // or 'https://cdn.example.com/tools-assets' (absolute)
        relative: true
    }
})
```

In SvelteKit 3, the `base` and `assets` exports of `$app/paths` are removed. Build links with `resolve()` and static asset URLs with `asset()`:

```html
<script lang="ts">
    import { resolve, asset } from '$app/paths';
</script>

<a href={resolve('/pricing')}>Pricing</a>
<a href={resolve('/blog/[slug]', { slug: 'hello' })}>Hello</a>
<img src={asset('logo.svg')} alt="Logo" />
```

`paths.assets` must be an absolute `http(s)` URL (or empty) and is used when your build artefacts live on a CDN or bucket. `paths.relative` (default `true`) makes server-rendered HTML use relative asset URLs, which makes prerendered output portable: you can serve the same files from `/`, `/preview/pr-123/` or a `file://` path. Set it to `false` if the page uses a `<base>` element, because relative URLs would then resolve against the base URL. The SPA fallback ignores this option and always uses absolute paths.

`paths.origin` (new in 3.0) sets the app’s canonical origin. It is used as `url.origin` during prerendering (default `http://sveltekit-prerender`, which is why absolute links to your own domain in prerendered output look wrong until you set it) and as the trusted origin for CSRF checks (Chapter 15). It replaces `prerender.origin` and, for `adapter-node`, the `ORIGIN` environment variable.

> **Warning:** A prerendered page that renders `page.url.origin` into canonical tags or Open Graph metadata will emit `http://sveltekit-prerender` unless `paths.origin` is set. Set it from an environment variable at build time for production builds.

```ts
// vite.config.ts (excerpt)
sveltekit({
    paths: { origin: process.env.PUBLIC_SITE_ORIGIN } // e.g. 'https://www.example.com'
})
```

## Putting it together: a rendering plan

Consider an e-commerce site with a public catalogue, a checkout, an account area and a static help centre. A defensible plan:

| Route group | Options | Why |
|------------------------|------------------------|------------------------|
| `/help/**` | `prerender = true`, `csr = false` | Identical for all users, rarely changes, needs no JS |
| `/` and `/category/**` | `prerender = 'auto'`, `entries` for top categories | Fresh long tail, fast head |
| `/product/[id]` | default SSR (`prerender = false`) | Inventory and price change per request |
| `/checkout/**` | SSR, actions | Needs POST handling and session state |
| `/account/**` | `ssr = false` only if the page embeds a client-only widget; otherwise SSR | Authenticated; SEO irrelevant but SSR still gives resilience |
| `/api/**` | `+server.ts`, `prerender = false` | Dynamic JSON |

Notice that the decision for `/account/**` is not “SPA because it is behind a login”. SSR still gives a faster first paint than an SPA shell and keeps working when scripts fail; use `ssr = false` only where a technical constraint (browser-only library) forces it.

## Verifying what you built

Three habits catch most rendering-mode mistakes:

1.  **Read the build output.** For the node and static adapters, `vite build` logs prerendered routes. Check that the files you expect exist and that routes you *did not* expect to be static are absent.
2.  **`curl` the production preview.** `vite preview` serves the production build. `curl -s http://localhost:4173/pricing | head` shows whether real content is in the HTML. For an `ssr = false` route you will see an empty shell.
3.  **Disable JavaScript in the browser** for `csr = false` pages and check that every interaction on them still works.

## Key takeaways

- Rendering is per route: `prerender`, `ssr`, `csr`, `trailingSlash` and `config` are exported constants inherited down the layout chain, with the nearest definition winning.
- Literal option values are read statically. Non-literal values force SvelteKit to import the module on the server, so browser-only code must not run at module load.
- `prerender = true` removes a route from the runtime manifest; `'auto'` keeps it. The prerender golden rule is that all users must get the same HTML. Pages with actions cannot be prerendered, `url.searchParams` is forbidden while prerendering.
- The crawler follows links in prerendered pages. Use `entries()` or `prerender.entries` for unlinked URLs, and tune strictness with the `handle*` options; each defaults to failing the build.
- Guard build-time side effects with `building` from `$app/env`.
- `ssr = false` yields an empty shell and client-only execution; `csr = false` ships no JavaScript and disables enhancement and client navigation. Both false renders nothing.
- SPA mode is `ssr = false` plus a host-served fallback page. Prefer a hybrid: prerender public pages, SPA only what must be one. The hash router disables SSR and server logic entirely.
- `output.bundleStrategy` (`split`, `single`, `inline`) and `inlineStyleThreshold` trade request count against cache efficiency.
- `embedded`, `paths.base`, `paths.assets`, `paths.relative` and `paths.origin` handle embedding and sub-path deployment; in 3.x use `resolve()` and `asset()` instead of the removed `base`/`assets` exports, and set `paths.origin` so prerendered output has the right origin.

## Review Questions

1.  A root `+layout.ts` exports `prerender = true`. A page below it exports `prerender = false`. Which wins for that page, and why does this make `export const prerender = true` at the root a reasonable app-wide default?

2.  What is the difference between `prerender = true` and `prerender = 'auto'` with respect to the runtime manifest? Give a route where `'auto'` is clearly the better choice.

3.  Your build fails with “The following routes were marked as prerenderable, but were not prerendered”. List three distinct ways to fix it and the trade-off of each.

4.  Find the problem:

    ```ts
    // src/routes/map/+page.ts
    import mapboxgl from 'mapbox-gl';
    import { dev } from '$app/env';

    export const csr = dev;
    ```

    Why does the build or server fail, and how do you fix it without changing the option?

5.  True or false: setting `ssr = false` means no code in `+page.server.ts` runs on the server. Explain.

6.  Which of the following pages can be prerendered? (a) a blog post using `params.slug`; (b) a page using `url.searchParams.get('q')` in `load`; (c) a page with `export const actions`; (d) a page rendering `locals.user.name`.

7.  A prerendered page’s `load` calls `setHeaders({ 'cache-control': 'max-age=600', 'x-foo': 'bar' })`. What ends up in the generated HTML?

8.  What does this configuration do, and what does it not do?

    ```ts
    sveltekit({ prerender: { crawl: false, entries: ['/', '/pricing'] } })
    ```

9.  Multiple choice: what is the default value of `prerender.concurrency`?

    a.  0
    b.  1
    c.  The number of CPU cores
    d.  10

10. Explain why raising `prerender.concurrency` speeds up a CMS-backed build but not a build that is CPU-bound in rendering.

11. You have `export const csr = false` on a page. List four things that stop working on that page.

12. What is printed/rendered, and why?

    ```ts
    // +layout.ts
    export const ssr = false;
    export const csr = false;
    ```

13. A layout exports `config = { runtime: 'a', regions: 'all', foo: { bar: true } }` and a page under it exports `config = { regions: ['x'], foo: { baz: true } }`. What is the effective config for the page?

14. Why does the SPA fallback page always use absolute asset paths even when `paths.relative` is `true`?

15. Multiple choice: you must deploy a static SPA to a bucket where you cannot configure any rewrite rule. Which option is the correct last resort?

    a.  `trailingSlash: 'ignore'`
    b.  `router: { type: 'hash' }`
    c.  `output.bundleStrategy: 'inline'`
    d.  `embedded: true`

16. With the hash router enabled, what happens to SSR and prerendering, and what must every internal link look like?

17. Design question: your SPA admin area is 600 KB of JavaScript. The product team asks for “SPA everywhere because the whole app is behind a login”. Give three arguments for a hybrid instead, and describe the layout/options structure.

18. Compare `bundleStrategy` `'split'`, `'single'` and `'inline'`. Which would you choose for a Capacitor-wrapped app, and which Vite option must accompany `'inline'` if you also want images inlined?

19. What are the performance costs and benefits of `inlineStyleThreshold`? When does raising it hurt?

20. Why might a prerendered page contain `http://sveltekit-prerender` in a canonical link, and how do you fix it?

21. Find the bug:

    ```html
    <script lang="ts">
        import { base } from '$app/paths';
    </script>
    <a href="{base}/pricing">Pricing</a>
    ```

    What is wrong in SvelteKit 3 and what is the replacement?

22. A route `/foo/+server.ts` and `/foo/bar/+server.ts` are both prerendered. What goes wrong, and what is the convention that avoids it?

23. What does `embedded: true` change about where SvelteKit attaches navigation listeners and where it gets `params`? Why can you not embed two SvelteKit apps on one page?

24. A page has `prerender = true` and `ssr = false`. Describe the output and who should use that combination.

25. Scenario: an `/events/[id]` page shows 5,000 events. 200 are popular, the rest are long-tail. Write the page options and `entries` function you would use, and explain what happens for an unlisted id at runtime. Would your answer change if you deploy with `adapter-static`?

26. Code: how would you make `csr = dev` while ensuring a literal option elsewhere in the same file stays statically analysable? Is that possible, and what is the cost?
