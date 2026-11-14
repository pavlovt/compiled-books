# Chapter 1: What SvelteKit 3 Is: Architecture and Toolchain

SvelteKit is often described as “the Svelte framework”, which is accurate but tells you very little about what you are actually deploying. In production, a SvelteKit 3 application is a Vite build that produces three artifacts: a set of immutable client chunks, a server module that turns a web-standard `Request` into a `Response`, and (optionally) a set of prerendered files. Everything else in this book, from the request lifecycle to remote functions, is a detail of how those three artifacts cooperate. This chapter builds the mental model that the rest of the book relies on. It covers the three layers (compiler, Vite plugin, adapter), what a freshly scaffolded project contains, how configuration works now that `svelte.config.js` is gone, how `#lib` and `$app/tsconfig` fit into TypeScript and Vite resolution, what every reserved file does, which web standards the framework is built on, and which parts of the API are stable, deprecated or experimental as of SvelteKit 3.1.

This book targets SvelteKit 3.1 with Svelte 5.57, Vite 8 (which uses Rolldown), Node 22.17 or newer, and TypeScript 6. It assumes you know Svelte 5 component syntax; that is covered in the companion Svelte book and is not repeated here.

## The three layers

It is useful to separate SvelteKit into three layers with distinct responsibilities. Most confusion in debugging (“is this a Svelte bug, a Kit bug, or a Vite bug?”) disappears once you know which layer owns which behaviour.

### Layer 1: Svelte, the compiler

Svelte compiles `.svelte` files (and `.svelte.ts` modules) into JavaScript. It produces two flavours of output from the same source: a client build that creates and updates DOM, and a server build whose `render()` function returns strings. Svelte knows nothing about URLs, routes, `fetch`, cookies or deployment. What it provides to Kit is:

- `render` from `svelte/server`, which Kit calls to produce the HTML `head` and `body` for a page, plus CSP script hashes when requested;
- `hydrate` and `mount` on the client, which Kit uses to attach to server-rendered markup;
- `<svelte:boundary>`, which Kit wraps around each `+error.svelte` so rendering errors reach `handleError`;
- (when `compilerOptions.experimental.async` is enabled) `await` in components and the `fork` API, which matter for remote functions and the experimental `forkPreloads` option.

### Layer 2: Vite, with the SvelteKit plugin

Everything between your files and a runnable server is done by Vite 8 and the plugin you import from `@sveltejs/kit/vite`. The plugin is where the framework actually lives at build time. It:

1.  Reads your options (the argument to `sveltekit({...})`) and splits them into options Kit understands and options forwarded to `@sveltejs/vite-plugin-svelte`.
2.  Scans `src/routes` and generates a manifest: which route IDs exist, which nodes (layouts, pages, error pages) each one is composed of, and which of those nodes have server `load` functions.
3.  Writes generated code under `.svelte-kit/` (type declarations, the client and server app manifests) and the `$app/tsconfig` module.
4.  In dev, installs a middleware that calls the same `respond` function a production server uses, so your dev server does not have a separate code path for routing.
5.  In build, runs several Vite builds: one for the server, one for the client (and a service worker if you have one), then hands the result to the adapter.
6.  Enforces rules at module-graph level: server-only modules may not be imported by client code, `$lib` and `$service-worker` imports produce a descriptive error because they were removed, and remote function files are checked.

Because the plugin is just a Vite plugin, anything Vite supports (CSS preprocessors, asset imports, `define`, `resolve.alias`, other plugins, Vitest sharing the same config file) works the same way. Since Vite 8, the bundler underneath is Rolldown rather than Rollup and esbuild. This matters in two places: plugin authors need to be Rolldown-compatible, and `@sveltejs/adapter-node` itself bundles with Rolldown.

### Layer 3: Adapters

An adapter takes the Kit build output and converts it into something a specific platform can run. It is invoked at the end of `vite build` through the `adapter` option. The official set is `adapter-auto` (detects Vercel, Cloudflare and Netlify at build time, with no options), `adapter-node`, `adapter-bun` (official as of 3.0), `adapter-static`, `adapter-cloudflare`, `adapter-netlify` and `adapter-vercel`. `adapter-cloudflare-workers` is deprecated in favour of `adapter-cloudflare`.

An adapter’s contract is small, and it is worth knowing it because it describes the boundary of the framework. Conceptually it implements:

```ts
// Adapter, simplified from @sveltejs/kit
interface Adapter {
    name: string;
    adapt(builder: Builder): MaybePromise<void>;
    emulate?(): MaybePromise<Emulator>;       // provides `platform` in dev/preview/prerender
    supports?: {
        read?: (details: { config: any; route: { id: string } }) => boolean;
        instrumentation?: () => boolean;
    };
    vite?: { /* getRequest, setResponse, plugins */ };
}
```

The `builder` gives the adapter `writeClient`, `writeServer`, `writePrerendered`, `generateServerInstance` and friends. The output of `generateServerInstance` is a tiny generated module that exposes a `server` object with exactly two methods that matter at runtime: `server.init({ env, read })` and `server.respond(request, { getClientAddress })`. The adapter’s entry point is therefore “translate platform request to `Request`, call `server.respond`, translate the `Response` back”. Chapter 2 follows `respond` in detail, and the adapter chapter later in the book covers writing one. The older `Server` class export is deprecated in favour of the generated `server` instance.

The consequence for architecture is that a SvelteKit app never “owns” the HTTP server. Whatever listens on the port, be it Node’s `http`, Bun, a Cloudflare Worker or a Lambda handler, belongs to the adapter. Kit owns `Request` in, `Response` out.

### How the layers interact at runtime

At build time the plugin produces a server bundle and a client bundle from the same route tree. At runtime the server bundle imports the Svelte server renderer plus your load functions and hooks. In the browser the client bundle contains the router, the navigation machinery, and lazily loaded route chunks. The two halves share a handful of pure modules (URL and route-matching utilities, devalue for serialization, the matchers from `src/params.ts`) so that “which route matches this URL” gives the same answer on both sides.

## Creating a project with `sv`

Projects are scaffolded with `sv`, the Svelte CLI:

```bash
npx sv create my-app
cd my-app
npm run dev
```

`sv create` is interactive, but everything can be passed as flags, which is what you want in scripts and CI:

```bash
npx sv create --template minimal --types ts --no-add-ons --install npm my-app
```

The templates are `minimal`, `demo`, `library` and `addon`. Add-ons (`--add`) are official integrations: `prettier`, `eslint`, `vitest`, `playwright`, `tailwindcss`, `enhanced-img`, `sveltekit-adapter`, `drizzle` and others. The add-on mechanism edits your project files (for example `sveltekit-adapter` rewrites the `adapter` import in `vite.config.ts`), so it is best used at creation time or on a clean working tree where you can review the diff.

The `minimal` TypeScript template, generated with `sv` 1.1.1 against SvelteKit 3.1.0, looks like this:

```text
my-app/
├ src/
│ ├ lib/
│ │ ├ assets/favicon.svg
│ │ └ index.ts
│ ├ routes/
│ │ ├ +layout.svelte
│ │ └ +page.svelte
│ ├ app.d.ts
│ └ app.html
├ static/
├ package.json
├ tsconfig.json
└ vite.config.ts
```

Note what is absent: there is no `svelte.config.js`. The generated `package.json` shows the other two notable v3 differences.

```json
{
    "name": "my-app",
    "private": true,
    "type": "module",
    "scripts": {
        "dev": "vite dev",
        "build": "vite build",
        "preview": "vite preview",
        "prepare": "svelte-kit sync || echo ''",
        "check": "svelte-kit sync && svelte-check --tsconfig ./tsconfig.json"
    },
    "devDependencies": {
        "@sveltejs/adapter-auto": "^8.0.0",
        "@sveltejs/kit": "^3.0.0",
        "@sveltejs/vite-plugin-svelte": "^7.2.0",
        "svelte": "^5.57.1",
        "svelte-check": "^4.6.0",
        "typescript": "^6.0.3",
        "vite": "^8.3.0"
    },
    "imports": {
        "#lib": "./src/lib/index.js",
        "#lib/*": "./src/lib/*"
    }
}
```

Three details deserve attention. First, the scripts are plain Vite commands; SvelteKit does not ship its own `dev` or `build` CLI. Second, `prepare` runs `svelte-kit sync`, so a fresh `npm install` generates the types before your editor opens a file. Third, the `imports` field is where the `src/lib` alias now lives (more on that below).

### Project types

SvelteKit does not have “modes” in the way some frameworks do. What you deploy is determined by the adapter plus rendering options on routes, and these are orthogonal. The documented project shapes are:

| Shape | How you get it |
|------------------------------------|------------------------------------|
| Default hybrid app | SSR for the first request, client-side routing afterwards. Any dynamic adapter. |
| Static site (SSG) | `adapter-static` with `prerender = true` in the root layout; or prerender only some routes and keep a server adapter for the rest. |
| Single-page app | `ssr = false` in the root layout, usually with `adapter-static` and a `fallback` page. |
| “Multi-page” app | Default SSR plus `data-sveltekit-reload` on links, or `csr = false` per page for zero-JS pages. The client router still exists. |
| Separate backend | SvelteKit as a frontend (`adapter-node` or serverless) in front of another language’s API; skip the `+server` and `.server` files. |
| Serverless / container / VPS | `adapter-vercel`, `-netlify`, `-cloudflare`, or `adapter-node` in a container. |
| Library | The `library` template with `@sveltejs/package`; there is no app at all. |
| Offline / PWA | Service worker in `src/service-worker/`. |
| Mobile / desktop / extension | An SPA build wrapped by Tauri, Capacitor, Wails, Electron, or an extension packager. `output.bundleStrategy: 'single'` reduces request count for HTTP/1 local servers. |

The routing and project structure are the same in all of them. The senior-level implication is that you should decide per route, not per application: a marketing site with prerendered pages, an SSR dashboard and an SPA-style admin area can all live in the same project. Chapter 11 develops this matrix.

## Configuration in SvelteKit 3

### The big change: `vite.config`, not `svelte.config.js`

In SvelteKit 1 and 2, configuration lived in `svelte.config.js` under a `kit` key. SvelteKit 2.62 added the ability to pass options to the Vite plugin; SvelteKit 3.0 removed `svelte.config.js` support entirely. Everything is now an argument to `sveltekit()`:

```ts
// vite.config.ts
import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [
        sveltekit({
            // --- SvelteKit's own options (formerly under `kit`) ---
            adapter: adapter({ precompress: true }),
            prerender: { handleHttpError: 'warn' },
            csrf: { trustedOrigins: ['https://checkout.example.com'] },
            version: { pollInterval: 5 * 60_000 },
            tracing: { server: true },
            experimental: { remoteFunctions: true },

            // --- Svelte compiler and vite-plugin-svelte options ---
            preprocess: vitePreprocess(),
            compilerOptions: {
                runes: ({ filename }) =>
                    filename.split(/[/\\]/).includes('node_modules') ? undefined : true,
                experimental: { async: true }
            }
        })
    ]
});
```

There are two flattening rules to internalize:

1.  The `kit.` prefix is gone. `kit.adapter` is now `adapter`, `kit.paths.base` is `paths.base`, `kit.prerender.entries` is `prerender.entries`, and so on.
2.  SvelteKit’s options live side by side with the options of `vite-plugin-svelte` (`preprocess`, `compilerOptions`, `inspector`, `extensions`, …). The plugin’s `Config` type literally extends the `vite-plugin-svelte` options, minus its `experimental` key.

How does Kit know which is which? It has a fixed list of its own option names. Anything not on the list is forwarded verbatim to `vite-plugin-svelte`, which validates it. The `experimental` key is a shared namespace: Kit plucks out the flags it recognises (`remoteFunctions`, `forkPreloads`) and passes the rest to `vite-plugin-svelte`. That is why `compilerOptions: { experimental: { async: true } }` (a Svelte compiler flag) and `experimental: { remoteFunctions: true }` (a Kit flag) appear at different levels in the example above.

> **Warning:** A typo in a Kit option name no longer fails Kit’s validation; it is forwarded to `vite-plugin-svelte`. Rely on the `Config` type from `@sveltejs/kit/vite` for completeness rather than waiting for a runtime error.

A practical consequence of putting config in `vite.config` is that the same file is read by Vitest, by Vite-based tools, and by the SvelteKit CLI (`svelte-kit sync` resolves the Vite config to find the plugin options). A single source of truth is good; the cost is that the file now executes inside Vite’s config loader, so keep it free of heavy side effects.

The `codemod` for the migration is `npx sv migrate sveltekit-3`.

### Option reference

The options and defaults below are the ones you will touch in practice (all top-level arguments to `sveltekit()`):

| Option | Default | Notes |
|------------------------|------------------------|------------------------|
| `adapter` | `undefined` | Run at the end of `vite build`. |
| `appDir` | `"_app"` | Prefix for immutable assets and internal routes. `/_app` is reserved. |
| `csp` | none | `mode: 'hash' \| 'nonce' \| 'auto'`, `directives`, `reportOnly`. 3.1 adds `report-sha256/384/512` keywords. |
| `csrf.trustedOrigins` | `[]` | Replaces `csrf.checkOrigin`. Production only; `'*'` allowed. |
| `embedded` | `false` | Listeners attach to the parent of `%sveltekit.body%`. |
| `env.dir` | `"."` | Where `.env` files are read from. |
| `experimental.remoteFunctions` | `false` | Plus Svelte’s `compilerOptions.experimental.async`. |
| `experimental.forkPreloads` | `false` | Uses Svelte’s fork API when preloading. |
| `inlineStyleThreshold` | `0` | Inline CSS files smaller than this many characters. |
| `moduleExtensions` | `['.js', '.ts']` | Extensions treated as route modules. |
| `outDir` | `.svelte-kit` | Generated files. |
| `output.bundleStrategy` | `'split'` | `'single'` and `'inline'` for constrained hosts. |
| `output.linkHeaderPreload` | `false` | New in 3.0: send preload hints as a `Link` header. |
| `paths` | `base: ''`, `relative: true` | `origin` is new in 3.0. |
| `prerender` | `crawl: true`, `entries: ['*']`, `concurrency: 1` | All `handle*` options default to `'fail'`. |
| `router.type` | `'pathname'` | `'hash'` disables SSR. |
| `router.resolution` | `'client'` | `'server'` resolves routes on the server. |
| `serviceWorker.register` | `true` |  |
| `tracing.server` | `false` | Stable top-level option in 3.0. |
| `version.pollInterval` | `3600000` | `0` disables polling. `version.name` identifies the build. |

Removed in 3.0: `preloadStrategy` (modulepreload is now always used), `csrf.checkOrigin`, `prerender.origin` (use `paths.origin`), `files.lib`, `experimental.instrumentation`, `experimental.tracing` and `experimental.handleRenderingErrors` (now default behaviour). Deprecated and slated for removal in 4: `files.*` (custom locations for `src`, `routes`, `hooks`, `params`, `serviceWorker`, `appTemplate`, `errorTemplate`), `alias`, and `typescript.config`. Treat deprecation notices as design signals: Kit wants conventional file locations and platform-standard aliasing.

Two options are worth singling out for their effect on the runtime rather than the build.

`paths.origin` solves a problem that previously required three separate mechanisms (the `ORIGIN` environment variable of `adapter-node`, `prerender.origin`, and ad-hoc header handling). Server-side code derives `event.url` from the incoming request, which behind a proxy may be wrong. Setting `paths.origin` pins the origin used for the CSRF check and for prerendering (during prerendering it defaults to `http://sveltekit-prerender`). Only the `adapter-node` `ORIGIN` variable is removed; the header-based variables (`PROTOCOL_HEADER`, `HOST_HEADER`, `PORT_HEADER`) remain.

`router.resolution: 'server'` changes where route matching happens on the client. With the default (`'client'`), the client bundle ships the whole route manifest, so link clicks resolve instantly. With `'server'`, the client asks the server (a `__route.js` module request) which route a URL belongs to, so the client bundle no longer contains the manifest. That is useful for very large route trees and for apps that rewrite URLs with `reroute`. Chapter 3 covers it, and it is the first place in this book where you will see the server answer a request that never reaches `handle`.

### Dev, build and preview

`vite dev` starts the dev server. The Kit plugin serves pages through the same request pipeline as production, but modules are loaded lazily through Vite’s module graph with HMR. `vite build` runs the build pipeline and the adapter. `vite preview` serves the *built* output using Kit’s preview plugin; it is closest to production but is not the production server, so do not benchmark or load-test it. For anything that depends on the adapter’s runtime behaviour (precompression, env var names, platform bindings) test against the adapter’s real output: `node build` for `adapter-node`, `wrangler dev` for Cloudflare.

One more tool is `svelte-kit sync`. It is the only command in the Kit CLI that matters day to day, and it exists to produce the generated TypeScript surface, described next.

## `#lib`, `$app/*` and TypeScript plumbing

### Why `$lib` became `#lib`

For years, `$lib` was a SvelteKit-specific alias: Kit configured Vite’s `resolve.alias` and wrote `paths` into the generated tsconfig. In 3.0 it is replaced by Node’s standard [subpath imports](https://nodejs.org/api/packages.html#subpath-imports): a field in `package.json`.

```json
{
    "imports": {
        "#lib": "./src/lib/index.js",
        "#lib/*": "./src/lib/*"
    }
}
```

```html
<!-- src/routes/+page.svelte -->
<script lang="ts">
    import Component from '#lib/Component.svelte';
    import { slugify } from '#lib/utils/slug.js';
</script>

<Component title={slugify('Hello world')} />
```

Details that matter:

- The `#` prefix is reserved by Node for package-internal aliases, so Vite, TypeScript (with `moduleResolution: "bundler"`), Node itself, Vitest and every other tool resolve it natively. Kit no longer has to teach each tool about its alias.
- File extensions are required: `#lib/foo.js`, not `#lib/foo`. For TypeScript sources you still write `.js` in the specifier (the target in `imports` is `./src/lib/index.js` even though the file is `index.ts`), exactly as in ESM TypeScript generally. The scaffold’s `#lib` entry maps to `index.js`, and TypeScript maps `.js` specifiers to `.ts` sources.
- `files.lib` is removed. If you want a different directory, change the `imports` target. The “server” directory rule (any directory named `server` is server-only) is independent of the alias.
- `@sveltejs/package` (`svelte-package`) rewrites `#` imports to relative paths when producing a library, so published packages do not depend on your `imports` field.
- Using `$lib` produces a descriptive build error rather than a silent failure. The same applies to the removed `$service-worker` module.

> **Senior tip:** You are not limited to `#lib`. Subpath imports are a general feature, so `"#server/*": "./src/server/*"` or `"#components/*": "./src/components/*"` work with zero Kit configuration. The deprecated `alias` option is only for cases where you cannot edit `package.json`.

### `$app/*`: virtual modules

Imports such as `$app/state`, `$app/navigation`, `$app/paths`, `$app/server`, `$app/forms` and `$app/env/*` are not files in your project. They are modules provided by the Kit plugin and resolved by Vite, with different implementations for server and browser: for example `$app/navigation` is the real router in the browser and a set of stubs that throw or no-op during SSR. The package’s own `imports` map (`#app/navigation`, `#app/state`, and so on) selects the implementation by condition (`browser`, `workerd`, `default`), which is how one import specifier gets two behaviours without Vite aliasing. You will meet the details of individual modules in the chapters where they matter. The ones that exist in 3.1 are:

| Module | Purpose |
|------------------------------------|------------------------------------|
| `$app/state` | `page`, `navigating`, `updated` (runes-based; replaces removed `$app/stores`) |
| `$app/navigation` | `goto`, `invalidate`, `refreshAll`, `preloadData`, `preloadCode`, navigation hooks, `snapshot` |
| `$app/paths` | `resolve`, `match`, `asset` (the old `base`, `assets` and `resolveRoute` are removed) |
| `$app/server` | `getRequestEvent`, `read`, remote function builders |
| `$app/forms` | `enhance`, `applyAction`, `deserialize` |
| `$app/env`, `$app/env/private`, `$app/env/public` | `browser`, `dev`, `building`, `version` and explicit env vars (see Chapter 13) |
| `$app/manifest`, `$app/service-worker` | service worker support |
| `$app/types` | generated route types: `RouteId`, `RouteParams`, `Path`, `AssetPath` and more |
| `$app/tsconfig` | not code: the base TypeScript configuration |

### `$app/tsconfig` and the generated TypeScript surface

Your `tsconfig.json` no longer extends `./.svelte-kit/tsconfig.json`. Instead:

```json
{
    "extends": "$app/tsconfig",
    "compilerOptions": { "strict": true },
    "include": ["src", "vite.config.ts"],
    "exclude": ["src/service-worker"]
}
```

`$app/tsconfig` resolves to a file that `svelte-kit sync` writes into `node_modules/$app/tsconfig.json` (together with `node_modules/$app/types/*.d.ts`). Reading the generated one in a 3.1 project shows the choices Kit makes for you:

```json
{
    "compilerOptions": {
        "paths": {},
        "rootDirs": ["../..", "../../.svelte-kit/types"],
        "types": ["$app/types"],
        "lib": ["ESNext", "DOM", "DOM.Iterable"],
        "verbatimModuleSyntax": true,
        "isolatedModules": true,
        "allowJs": true,
        "checkJs": true,
        "moduleResolution": "bundler",
        "allowImportingTsExtensions": true,
        "module": "esnext",
        "target": "esnext",
        "skipLibCheck": true,
        "noEmit": true
    }
}
```

Four properties are load-bearing, and Kit warns if you override them:

- `isolatedModules: true`, because Vite transpiles one file at a time.
- `verbatimModuleSyntax: true`, so type-only imports are explicit and `.svelte` files are safe.
- `types` must include `"$app/types"`, which is how the ambient declarations for env vars, route IDs and link-option attributes become visible.
- `paths` is derived from the deprecated `alias` option and from your `package.json` subpath imports. Prefer subpath imports and leave `paths` alone.

`rootDirs` is the trick behind `./$types`. The tsconfig tells TypeScript that `src/routes/blog/[slug]` and `.svelte-kit/types/src/routes/blog/[slug]` are the same directory, so `import type { PageProps } from './$types'` resolves to a generated declaration file that lives elsewhere. The generated file for the root route in the minimal project is:

```ts
// .svelte-kit/types/src/routes/$types.d.ts (abridged)
import type * as Kit from '@sveltejs/kit';
type RouteParams = {};
type RouteId = '/';
export type PageServerData = null;
export type PageData = Expand<PageParentData>;
export type PageProps = { params: RouteParams; data: PageData };
export type LayoutProps = { params: LayoutParams; data: LayoutData; children: import('svelte').Snippet };
```

Every route directory with a `+page`, `+layout` or `+server` gets such a file. Types it exports include `PageProps`, `LayoutProps`, `PageData`, `LayoutData`, `PageLoad`, `PageServerLoad`, `LayoutLoad`, `LayoutServerLoad`, `RequestHandler`, `Actions`, `ActionData`, `EntryGenerator` and `RouteParams`. The generated types are what make `params.slug` typed as `string` and make `data` reflect the actual return type of the `load` function next to the component. They regenerate when `vite dev` runs or when you run `svelte-kit sync`; CI type-check jobs must run `svelte-kit sync` first, which is why the scaffold’s `check` script does it.

A service worker needs its own TypeScript project because it has different globals (`ServiceWorkerGlobalScope`, no DOM):

```json
// src/service-worker/tsconfig.json
{ "extends": "$app/tsconfig/service-worker" }
```

### `app.d.ts`

`src/app.d.ts` is the one hand-written ambient file. It declares the `App` namespace that parameterises Kit’s types:

```ts
// src/app.d.ts
declare global {
    namespace App {
        interface Error {
            code?: string;      // status and message are always present
            requestId?: string;
        }
        interface Locals {
            user?: { id: string; role: 'admin' | 'member' };
        }
        interface PageData {
            title?: string;     // common shape for page.data
        }
        interface PageState {
            selected?: string;  // shallow routing state
        }
        interface Platform {
            // e.g. Cloudflare bindings
        }
    }
}

export {};
```

`App.Error` always includes `status` and `message`; `App.Locals` types `event.locals`; `App.PageData` types `page.data` for code that cannot see a specific route’s load return type (such as the root layout); `App.PageState` types `page.state`; `App.Platform` types `event.platform`. These are contracts between your hooks and your components, so treat them like a public API of your own app.

## Project structure and reserved files

Here is the full 3.x layout, with every reserved file:

```text
my-project/
├ src/
│ ├ lib/                      # '#lib' alias; any 'server' directory is server-only
│ ├ routes/                   # the route tree
│ ├ service-worker/index.ts   # or src/service-worker.ts
│ ├ app.html
│ ├ app.d.ts
│ ├ error.html
│ ├ env.ts                    # explicit env var declarations (Chapter 13)
│ ├ hooks.client.ts
│ ├ hooks.server.ts
│ ├ hooks.ts                  # universal hooks: reroute, transport
│ ├ instrumentation.server.ts # OpenTelemetry setup (Chapter 17)
│ └ params.ts                 # param matchers (Chapter 3)
├ static/
├ tests/
├ package.json
├ tsconfig.json
└ vite.config.ts
```

Everything except `src/routes` and `src/app.html` is optional.

### Route files

Inside `src/routes`, files starting with `+` are special. All of them are detailed in Chapter 3; here is the map:

| File | Runs on | Role |
|------------------------|------------------------|------------------------|
| `+page.svelte` | server + browser | The page component. |
| `+page.ts` | server + browser | Universal `load` and page options. |
| `+page.server.ts` | server | Server `load`, form `actions`, page options. |
| `+layout.svelte` | server + browser | Wraps child routes; must render `children`. |
| `+layout.ts` / `+layout.server.ts` | as above | Layout `load` and options. |
| `+error.svelte` | server + browser | Error boundary for the subtree. |
| `+server.ts` | server | HTTP handlers: `GET`, `POST`, `PATCH`, `PUT`, `DELETE`, `OPTIONS`, `HEAD`, `QUERY`, `fallback`. |

Files after the `+` that contain `test`, `spec` or `stories` are ignored by the route scanner, so `+page.spec.ts` or `+layout.stories.svelte` can sit beside the route. Colocating non-`+` files (components used only by one route) is encouraged and harmless.

### Hook files

`hooks.server.ts` holds `handle`, `handleFetch`, `handleError` and `init`. `hooks.client.ts` holds the client `handleError` and `init`. `hooks.ts` is the universal file, running on both sides, with `reroute` and `transport`. Their types are imported from `@sveltejs/kit/hooks` in 3.0 (`Handle`, `HandleServerError`, `Reroute`, `Transport`, and so on); the old exports from `@sveltejs/kit` were removed. The only runtime export of that sub-path is `sequence`.

### `app.html` and `error.html`

`app.html` is the document template. It must contain `%sveltekit.head%` and `%sveltekit.body%`; the build fails otherwise (the check is done by `load_template` when the config is processed). The full placeholder set is:

| Placeholder | Replaced with |
|------------------------------------|------------------------------------|
| `%sveltekit.head%` | Link and script tags the app needs, plus `<svelte:head>` content |
| `%sveltekit.body%` | The rendered page markup |
| `%sveltekit.assets%` | `paths.assets` if set, otherwise a relative path to `paths.base` |
| `%sveltekit.nonce%` | The CSP nonce, for hand-written scripts and links |
| `%sveltekit.version%` | The app version (`version.name`) |
| `%sveltekit.env.[NAME]%` | A public env var declared in `src/env.ts`; `''` if not found |

The body placeholder should live inside a wrapper element, not directly in `<body>`:

```html
<!-- src/app.html -->
<!doctype html>
<html lang="en">
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="%sveltekit.assets%/favicon.png" />
        %sveltekit.head%
    </head>
    <body data-sveltekit-preload-data="hover">
        <div style="display: contents">%sveltekit.body%</div>
    </body>
</html>
```

The reason is practical: browser extensions routinely inject nodes into `<body>`, and hydration then removes or mismatches them. Kit warns in development if `%sveltekit.body%` is a direct child of `body`. The wrapper uses `display: contents` so it does not affect layout. The scaffold also puts `data-sveltekit-preload-data="hover"` on `<body>`, which is how links preload data on hover by default.

`error.html` is the last-resort page, rendered when even the root layout cannot render (an error in the root layout’s `load`, or in `handle` after a response cannot be produced). It supports `%sveltekit.status%` and `%sveltekit.error.message%`. If you do not provide one, Kit uses a built-in default. It is static, so it cannot use your components or CSS imports, and it must be self-contained. Chapter 10 covers when it is used.

### `static/` and `tests/`

`static/` files are served as-is at the root with unhashed names (`robots.txt`, `favicon.png`). Prefer importing assets from `src/` so Vite hashes them and they are cacheable immutably. Static files are served by the adapter or platform and, importantly, never pass through the `handle` hook (Chapter 2). `tests/` is where the Playwright add-on puts end-to-end tests; unit tests with Vitest live next to the code in `src/`.

### `.svelte-kit/`

The `outDir` holds generated code and build intermediates. Ignore it in version control and never edit it. You can delete it at any time; it regenerates.

### Reserved names

Two reservations catch people: query parameters beginning with `x-sveltekit-` (Kit uses them internally for data requests and returns 400 for external use), and the `/_app` path prefix (from `appDir`), under which immutable build output, `version.json`, `env.js` and route resolution modules live. Requests under `/_app` that do not match an asset get a 404 with `cache-control: public, max-age=0, must-revalidate`, so a stale CDN cannot cache a miss.

## Web standards SvelteKit builds on

The framework deliberately uses platform APIs rather than inventing its own, and this is what makes it portable across Node, Bun, Cloudflare Workers, Vercel Functions and Deno. If you know `fetch`, you know most of the server API.

- **`Request` and `Response`.** `event.request` is a `Request`. Every handler (`handle`, `+server` verbs, and in a sense the whole framework) ultimately produces a `Response`. The documentation puts it well: a SvelteKit app is a machine for turning a `Request` into a `Response`.
- **`fetch`.** The same `fetch` name is available in the browser, in hooks, in `+server` routes and in `load`. The `fetch` you receive in `load`, hooks and remote functions is a wrapped version with extra behaviour (relative URLs, credential forwarding, in-process dispatch for internal routes, response inlining); Chapter 4 details it. A plain global `fetch` in server code lacks those features and, during SSR, produces a development warning in `load`.
- **`Headers`.** For `request.headers` and response headers. `Set-Cookie` is the one header that needs `getSetCookie()`; Kit’s `cookies` API manages it for you.
- **`FormData`.** For native form posts. `await event.request.formData()` is what form actions and `+server` form handlers use; files arrive as `File` objects.
- **Streams.** `ReadableStream`, `WritableStream` and `TransformStream` for large or chunked bodies. Streaming `load` promises and the data protocol are built on them.
- **`URL` and `URLSearchParams`.** `event.url`, `page.url`, `navigation.to.url`. Kit instruments `url` in `load` to track which parts you read (Chapter 5).
- **Web Crypto.** `crypto` is global; Kit uses it for CSP nonces and you can use `crypto.randomUUID()`.

A minimal `+server` that exercises most of them:

```ts
// src/routes/echo/+server.ts
import type { RequestHandler } from './$types';

export const POST: RequestHandler = async ({ request, url }) => {
    const form = await request.formData();

    return Response.json(
        {
            name: form.get('name') ?? 'world',
            ua: request.headers.get('user-agent'),
            search: Object.fromEntries(url.searchParams),
            id: crypto.randomUUID()
        },
        { headers: { 'x-echo': '1' } }
    );
};
```

Note `Response.json(...)`. The `json()` and `text()` helpers exported from `@sveltejs/kit` are deprecated in 3.x in favour of the platform’s `Response.json` and `new Response(...)`. A related detail: a `204` response must not carry a body, and Kit will not add one.

Because Kit is built on these standards, testing strategies and deployment portability follow. You can invoke a `+server` handler in a unit test by constructing a `Request`, and you can reason about adapters by asking only “how does the platform’s native request type map to `Request`?” Node, which predates these APIs, is handled by `getRequest` and `setResponse` from `@sveltejs/kit/node`; in 3.0 those became synchronous and the `@sveltejs/kit/node/polyfills` module was removed, because Node 22 has everything natively.

## Version requirements and the stability map

As of SvelteKit 3.1:

| Requirement                    | Version                          |
|--------------------------------|----------------------------------|
| Node.js                        | 22.17 or newer                   |
| Svelte                         | 5.57 or newer (peer `^5.57.1`)   |
| Vite                           | 8 (peer `^8.0.12`)               |
| `@sveltejs/vite-plugin-svelte` | 7                                |
| TypeScript                     | 6                                |
| Optional                       | `@opentelemetry/api` for tracing |

Runtime dependencies are deliberately few: `cookie` v2 (cookie names are ASCII-only, and its `SerializeOptions`/`ParseOptions` types were renamed), `devalue` 5.x, `esm-env`, `sirv`, `mrmime` and `@standard-schema/spec`.

It helps to classify every API you adopt as **stable**, **deprecated** or **experimental**, because the migration cost differs.

**Stable and recommended in 3.x**

- Filesystem routing, `load`, form actions, hooks, page options, the adapters, `$app/state`, `$app/paths` (`resolve`, `match`, `asset`), `src/params.ts` with `defineParams`, `src/env.ts` with `defineEnvVars` and `$app/env/*`, tracing (`tracing: { server: true }` plus `src/instrumentation.server.ts`), `refreshAll`, the function-style `snapshot()`, and shallow routing through `goto(url, { shallow: true, state })`.

**Deprecated (still work, removal planned for 4)**

- `$env/static/*`, `$env/dynamic/*` and `$app/environment` (replace with `src/env.ts` and `$app/env/*`).
- `invalidateAll` (use `refreshAll`, which also does not reset `page.state`), `pushState` and `replaceState` (use `goto` with `shallow`), `export const snapshot` in components (use `snapshot()`).
- `json()` and `text()` helpers, the `Server` class, `files.*`, `alias`, `typescript.config`, the `cloudflare-workers` adapter.

**Removed in 3.0 (breaking)**

- `svelte.config.js`, `$lib`, `$service-worker`, `$app/stores`, `base`/`assets`/`resolveRoute` from `$app/paths`, per-file `src/params/*.js` matchers, `csrf.checkOrigin`, `preloadStrategy`, `prerender.origin`, adapter-node’s `ORIGIN` variable, the `noScroll`/`keepFocus` options of `goto`, `data-sveltekit-preload-data="off"` (use `false`), Vercel’s edge runtime, `handleValidationError`, the `.run()` method of remote queries (removed in 2.61), the `buttonProps` of remote forms (removed in 2.50).

**Experimental**

- Remote functions (`query`, `query.batch`, `query.live`, `form`, `command`, `prerender`). Still experimental in 3.1, and enabling them requires both `experimental: { remoteFunctions: true }` in the `sveltekit()` options and `compilerOptions: { experimental: { async: true } }`. With the flag off, `*.remote.*` files fail the build.
- `experimental.forkPreloads`, off by default.
- Async `handleError` in `hooks.client` depends on the Svelte `async` compiler flag.

> **Senior tip:** “Experimental” in Kit means “the API may change in a minor release”. Treat the flag as the unit of risk: isolate experimental usage behind a thin wrapper module in your app so a future signature change touches one file.

The first thing to do when upgrading is to run the codemod, then re-run `svelte-kit sync`, then fix type errors in that order. Most migration work is mechanical (`$lib` to `#lib`, `$app/stores` to `$app/state`, moving config), and the compiler tells you what you missed because removed modules fail loudly.

## Reading the reference docs (and where signatures actually live)

The official documentation tree has a quirk that costs people time: the pages under the reference section (`@sveltejs/kit`, `$app/navigation`, `$app/state`, `$app/server`, and so on) are mostly generated from the types and JSDoc in the source. In the markdown source they appear as stubs that contain directives such as an exported-snippets marker, not prose. On the published website those are expanded into full signatures. That has two consequences for how you work:

1.  For an exact signature, the authority is the shipped type definitions, not a hand-written doc page. In your own `node_modules/@sveltejs/kit` the public types are in `types/index.d.ts` (a bundled `.d.ts` generated at publish time), and runtime modules such as `src/runtime/app/navigation/client.js` carry the JSDoc that the website renders. Reading the source is a legitimate, fast way to settle a doubt, and it is why `go to definition` in your editor on `invalidate` is so useful.
2.  When docs prose and types disagree, types win for compile-time behaviour and the source wins for runtime behaviour. A known example in 3.1 is the remote form `validate()` method, where prose describes an `includeUntouched` option while the type file declares `all` and `preflightOnly` (Chapter 8 returns to this). Always check which one you are reading.

The conceptual docs (core concepts, advanced, build and deploy, best practices) are hand-written and are the right place for behaviour. The appendix holds the migration guides, which are better than release notes for understanding why something changed, and the FAQ, which contains several answers that are surprisingly deep (for example how to use a different backend, and why `window` is not defined). The `CHANGELOG.md` in the repository is the source of truth for when something changed: the 3.1.0 entry, for example, added the `report-sha256/384/512` CSP keywords and a `sveltekit.endpoint` OpenTelemetry span for `+server` handlers, while 3.0.1 fixed generated types under `nodenext`.

Two other aids: the module `@sveltejs/kit` exports a `VERSION` constant (useful for diagnostics), and `svelte-kit sync` output under `.svelte-kit/types` is the quickest way to see exactly what types Kit infers for a route.

## A mental model to carry forward

To close the architecture overview, here is a one-page model of what happens from `vite build` to a request:

1.  **Build.** The plugin scans routes, generates manifests, and builds server and client bundles. If prerendering is configured, the build starts the server code in-process and requests each prerenderable page, saving the responses (and `__data.json` for the data of those pages when appropriate). Then `adapter.adapt(builder)` runs and writes platform output.
2.  **Boot.** The adapter’s entry imports the generated `server`, calls `server.init({ env, read })` once, and begins listening.
3.  **Request.** For each request the adapter builds a `Request` and calls `server.respond(request, ...)`. The response flows back out.
4.  **Browser.** The HTML response includes a script that imports the client entry, which calls the app’s `start`, runs the client `init` hook, then hydrates.

The following chapters elaborate step 3 (Chapter 2) and the pieces that plug into it: routing (3), loading (4, 5), actions and remote functions (6, 7, 8), hooks (9), errors (10), and page options (11).

## Key takeaways

- SvelteKit 3 is three layers: Svelte compiles components, a Vite 8 plugin generates the route manifest, types and builds, and an adapter maps a platform onto `server.respond(Request) -> Response`. The framework never owns the HTTP listener.
- Configuration is passed to `sveltekit({...})` in `vite.config`. `svelte.config.js` is unsupported; `kit.*` options are flattened to the top level next to `compilerOptions`, `preprocess` and other `vite-plugin-svelte` options. Unknown keys go to `vite-plugin-svelte`; `experimental` is a shared namespace split between both.
- `$lib` is gone. `#lib` comes from `package.json` `imports`, requires file extensions, and is resolved natively by Vite, TypeScript and Node. Any subpath import works the same way.
- `tsconfig.json` extends `$app/tsconfig`, generated by `svelte-kit sync` into `node_modules/$app`. `isolatedModules`, `verbatimModuleSyntax` and `types: ["$app/types"]` must stay set. `rootDirs` is what makes `./$types` imports work.
- `svelte-kit sync` must run before type checking in CI; the scaffold wires it into `prepare` and `check`.
- Only `src/routes` and `src/app.html` are mandatory. `error.html` is the static last-resort page; `%sveltekit.body%` belongs inside a wrapper element.
- The `fetch` in `load`, hooks and remote functions is a wrapped version of the platform `fetch`; the platform standards (`Request`, `Response`, `Headers`, `FormData`, streams, `URL`) are the whole server API.
- Classify APIs as stable, deprecated or experimental before adopting them. Remote functions remain experimental in 3.1 and need two flags; `$env/*`, `$app/environment`, `invalidateAll` and the `pushState`/`replaceState` functions are deprecated.
- For exact signatures, read the shipped types and source; reference doc pages are generated stubs, and docs prose can lag behind types.

## Review Questions

1.  Name the three layers of a SvelteKit 3 application and state which layer is responsible for each: (a) turning `.svelte` files into JavaScript, (b) generating the route manifest, (c) producing Netlify-specific function output.

2.  What are the two methods of the generated `server` object that an adapter’s runtime entry uses, and what does each do?

3.  Why does the fact that SvelteKit “never owns the HTTP server” matter when you debug a deployment problem such as a wrong `event.url.origin`?

4.  A teammate migrating from SvelteKit 2 says: “I’ll just keep `svelte.config.js` and add the new options in `vite.config.ts`.” What actually happens to `svelte.config.js` in 3.x, and what do they need to do?

5.  Given this configuration, which options does SvelteKit consume and which are forwarded to `vite-plugin-svelte`?

    ```ts
    sveltekit({
     adapter: adapter(),
     preprocess: vitePreprocess(),
     experimental: { remoteFunctions: true },
     inspector: true,
     compilerOptions: { experimental: { async: true } }
    })
    ```

6.  **Multiple choice.** What is the correct way to express in 3.x what used to be `kit: { paths: { base: '/docs' } }`?

    a.  `sveltekit({ kit: { paths: { base: '/docs' } } })`
    b.  `sveltekit({ paths: { base: '/docs' } })`
    c.  A `base` field in `package.json`
    d.  `defineConfig({ base: '/docs' })` only; Kit reads Vite’s `base`

7.  Find the bug: after migrating, a developer’s build fails in a file containing `import { formatDate } from '#lib/format';`, while `package.json` contains the standard `#lib` imports entries. What is wrong?

8.  Explain why `#lib` works in Vitest and in plain Node scripts without any Kit-specific configuration, whereas `$lib` needed plugin support.

9.  In the `package.json` `imports` entry `"#lib": "./src/lib/index.js"`, the source file is `src/lib/index.ts`. Why does it point to `.js`, and what resolves it?

10. List the four `compilerOptions` in the base `$app/tsconfig` that Kit warns about if you override, and give a one-line reason for two of them.

11. What does `rootDirs` accomplish in the generated tsconfig, and what would break in your editor if `svelte-kit sync` had never been run?

12. **Multiple choice.** Which of the following is NOT a file that `svelte-kit sync` writes or updates?

    a.  `.svelte-kit/types/src/routes/$types.d.ts`
    b.  `node_modules/$app/tsconfig.json`
    c.  `src/app.d.ts`
    d.  `node_modules/$app/types/index.d.ts`

13. What does the following file layout produce, and why is `+page.spec.ts` safe there?

    ```text
    src/routes/blog/
    ├ +page.svelte
    ├ +page.server.ts
    ├ +page.spec.ts
    └ PostCard.svelte
    ```

14. Why should `%sveltekit.body%` be wrapped in an element in `app.html`, and what does the wrapper in the scaffold do so it does not disturb layout?

15. Which two placeholders are mandatory in `app.html`? What happens if one is missing?

16. When is `error.html` rendered rather than a `+error.svelte`, and why can it not use your Svelte components?

17. Which reserved URL query parameter prefix and which path prefix are reserved by SvelteKit, and what status does a request using the reserved query prefix receive?

18. A colleague writes `return json({ ok: true })` using the helper from `@sveltejs/kit` in a new 3.1 route. Is this broken? What do you recommend instead, and why?

19. What does the following endpoint return, and which web-standard APIs does it use?

    ```ts
    export const POST = async ({ request }) => {
        const body = await request.formData();
        return Response.json({ name: body.get('name') ?? 'world' });
    };
    ```

    What is the returned `name` if the form has no `name` field?

20. Classify each as stable, deprecated, removed or experimental in 3.1: (a) `$app/stores`, (b) `$env/static/private`, (c) `query.live`, (d) `refreshAll`, (e) `files.routes`, (f) `defineParams`.

21. List the two flags needed to enable remote functions. What happens to a `*.remote.ts` file when the Kit flag is off?

22. Why is it a good idea to wrap experimental features in a thin module in your own codebase?

23. A reference page on the website shows a rich signature for `preloadCode`, but the markdown source in the docs repository shows only a one-line stub. Where does the website content come from, and where would you look in an installed project to check the exact signature?

24. **Design question.** You are building one product with a prerendered marketing site, a logged-in SSR dashboard and an internal SPA-style admin tool. Explain, using the “project types” model, how you would structure this in a single SvelteKit project, and which two kinds of configuration decide each area’s behaviour.

25. **Design question.** Your team proposes pinning `@sveltejs/kit` to `^3.0.0` and enabling `experimental.remoteFunctions` across the app because “it’s been experimental since 2.27, so it must be stable”. Give two arguments against treating it as stable and one mitigation.
