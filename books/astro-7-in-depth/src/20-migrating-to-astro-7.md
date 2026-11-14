# Chapter 19: Migrating to Astro 7

Two major versions separate a typical Astro 5 project from Astro 7.4, and each changed the platform underneath it: Vite 7 then Vite 8, Zod 4, Shiki 4, a Rust compiler, a new Markdown processor, a new rendering engine. Most of the changes are small in code, but they interact, and the failures show up in different places: at build time (invalid HTML, legacy collections), at first request (secrets, sessions), or only visually (collapsed whitespace, changed CSS serialization). This chapter gives an order of operations, a checklist for each major, the promoted-experimental and relocated config options, the adapter and session changes, what changed in `@astrojs/svelte`, how to approach a SvelteKit-to-Astro migration, and which legacy flags and deprecations to clear before the next major.

The primary sources are the v6 and v7 upgrade guides, the 7.x changelog and the Svelte integration changelog. Where the guides were silent I tested against Astro 7.4.1 and say so.

## Strategy: one major at a time

Do not jump from 5.x to 7.x in one commit. Upgrade to the latest 6.x first, get a green build and tests, then move to 7.x. The reasons are practical: the 6.0 guide’s removals (legacy collections, `<ViewTransitions />`, `Astro.glob()`) produce hard errors that are easiest to fix in isolation, and the 7.0 changes (compiler strictness, whitespace) produce subtle output differences that you want to see against a known-good 6.x baseline.

A reliable sequence:

1.  **Freeze a baseline.** On the old version, build and save the output (`dist/`), or at least the HTML for representative routes, plus screenshots if you have visual testing. Record the build time (Chapter 17’s `--timings` exists only from 7.4, so use wall-clock time on the old version).
2.  **Upgrade the platform.** Node first. Astro 6 requires Node 22.12.0 or newer; Astro 7.4 requires 22.22.0 or newer (and `@astrojs/svelte` 9.1.0 also requires 22.22.0). Update `.nvmrc`/`engines`, CI images and hosting settings before touching Astro. Node 18 and 20 are not supported.
3.  **Run the upgrade tool.** `npx @astrojs/upgrade` upgrades `astro` and the official integrations together. Doing it manually risks a mismatched adapter or integration major (see below).
4.  **Fix build errors**, then **run the tests**, then **diff the output** against the baseline.
5.  **Remove deprecated usage** so the next major is not a surprise (end of this chapter).

> **Senior tip:** make the framework upgrade its own pull request, with no refactors mixed in. When a visual regression appears, you want exactly one suspect.

## From 5.x to 6.x

### Platform changes

- **Node 22.12+.** Astro 6 dropped Node 18 and 20.
- **Vite 7 and the Environment API.** Astro 6 refactored to Vite’s Environment API with `client`, `ssr` and `prerender` environments (a fourth, `astro`, is used for dev). Application code is rarely affected; integration and adapter code is (below). If you use `getViteConfig()` with Vitest, you need Vitest 3.2 or newer.
- **Zod 4.** Custom schemas in `content.config.ts` and actions need updating.
- **Shiki 4.** Affects code that uses Shiki APIs directly.
- **Official adapters all bumped a major version** with Astro 6. The Cloudflare adapter (13) changed the most: it runs workerd in dev, supports `prerenderEnvironment: 'workerd' | 'node'`, uses `@astrojs/cloudflare/entrypoints/server`, removed `Astro.locals.runtime` and dropped Pages support. Read the adapter’s own upgrade notes before upgrading.

### Zod 4 in practice

The changes that most often break builds:

```ts
// string formats moved to the top-level namespace
email: z.string().email()      // before
email: z.email()               // after

// message -> error
z.string().min(5, { message: 'Too short.' })   // before
z.string().min(5, { error: 'Too short.' })     // after

// defaults must match the OUTPUT type and short-circuit parsing
views: z.string().transform(Number).default('0')   // before
views: z.string().transform(Number).default(0)     // after
// for the old behaviour (default is parsed): .prefault('0')
```

The custom `errorMap` is gone; translate error messages through the new error customization API. Import `z` from `astro/zod` (the same Zod instance that Astro uses), not from `astro:content` or `astro:schema`; both of those are deprecated.

### Content collections: legacy removal

Astro 5 let projects keep v2-style collections through a flag and through automatic compatibility that was not behind a flag. Astro 6 removes the `legacy.collections` flag and the automatic compatibility. Symptoms and fixes from the guide:

| Symptom | Fix |
|------------------------------------|------------------------------------|
| No config file | Create `src/content.config.ts` |
| Config at `src/content/config.ts` (`LegacyContentConfigError`) | Move/rename to `src/content.config.ts` |
| Collection without a `loader` | Add `glob({ pattern, base })` from `astro/loaders` |
| `type: 'content'` / `type: 'data'` | Delete; there are no collection types |
| `getEntryBySlug()`, `getDataEntryById()` | Use `getEntry()` |
| `entry.slug` | Use `entry.id` (now slug-like); `filePath` has the old filename |
| `entry.render()` | `import { render } from 'astro:content'; render(entry)` |
| Function-valued `schema` in an object loader | Use `createSchema()` |

If you cannot finish immediately, `legacy.collectionsBackwardsCompat: true` restores `type` without loaders, `entry.slug`, `entry.render()` and path-based IDs (and, per the 6.0 guide, the old `src/content/config.ts`; the reference page in 7.x omits that item, so do not rely on it). It is explicitly temporary.

### Removed in 6.0

- `<ViewTransitions />` (use `<ClientRouter />`), and `handleForms` on `<ClientRouter />` (forms are handled by default).
- `Astro.glob()` (use `import.meta.glob()` or collections).
- `emitESMImage()`.
- Internals exported from `astro:actions` (`ACTION_ERROR_CODES`, `ActionInputError`, `callSafely`, `deserializeActionResult`, `formDataToObject`, `getActionQueryString`, `serializeActionResult` and several types). Use the documented API: `getActionContext()` provides serialize/deserialize helpers (Chapter 11).
- `prefetch({ with })` option.
- `rewrite()` from the actions context.
- The session `test` driver.
- `.cjs`/`.cts` Astro config files (rename to `.mjs`/`.mts` or use ESM).
- `astro:ssr-manifest`, `RouteData.generate()`, `entryPoints` on `astro:build:ssr`, `routes` on `astro:build:done`, the old `app.render()` signature and `app.setManifestData()` (integration and adapter authors).
- Percent-encoded percent signs (`%25`) in route file names.
- Entry `schema` as a function in object loaders.

### Changed defaults in 6.0

These make no noise at build time. Review each against your site:

- **`i18n.routing.redirectToDefaultLocale`** now defaults to `false`, and can be used only with `prefixDefaultLocale: true`. Projects that relied on `/` redirecting to `/en/` must set both explicitly (Chapter 15).
- **Scripts and styles render in source order** (the former `preserveScriptOrder`). Astro 5 reversed their order; CSS that depended on the reversed cascade needs reordering.
- **`import.meta.env` is always inlined and never coerced** (the former `staticImportMetaEnv`). `"true"` stays a string; `import.meta.env.DB_PASSWORD` is no longer rewritten to `process.env`. Convert manually (`=== 'true'`), use `process.env` for runtime values, and prefer `astro:env` (Chapter 16).
- **Markdown heading IDs** follow `github-slugger` (the former `headingIdCompat`): trailing hyphens are no longer stripped, so `## \`\<Picture /\>\`\` yields an ID ending in a hyphen. Update hand-written anchor links.
- **Responsive image styles** are emitted as a hash class and `data-astro-fit`/`data-astro-pos` attributes instead of inline CSS variables, for CSP compatibility.
- **Image service:** crops by default (no `fit` needed), never upscales, and now rasterizes SVG when `format` is set (guard with `src.format === 'svg'`).
- **`getImage()` throws on the client.** Call it on the server and pass `.src`.
- **Endpoints with a file extension** (`sitemap.xml.ts`) are not reachable with a trailing slash.
- **`getStaticPaths()` params must be strings**, and `Astro` inside `getStaticPaths()` is deprecated (use `import.meta.env.SITE`).
- **Pathname decoding:** `Astro.url.pathname` can be partially decoded compared with `new URL(request.url).pathname`.

### Promoted from experimental in 6.0

`csp`, `fonts`, `liveContentCollections` and `failOnPrerenderConflict` (now `prerenderConflictBehavior`, default `'warn'`). Move the options out of `experimental` and delete the flags.

### Deprecated in 6.0

`import.meta.env.ASSETS_PREFIX` (use `build.assetsPrefix` from `astro:config/server`), the session driver string signature with `options` (use `sessionDrivers.*`), `NodeApp`/`loadApp`/`loadManifest` and `createExports()`/`start()` for adapters, `astro:schema` and `z` from `astro:content`.

## From 6.x to 7.x

### Vite 8

For application code, usually nothing. Integration authors and anyone with custom Vite plugins should read the Vite 8 migration guide. Note the plugin-hook `filter` form used in the adapter reference examples.

### The Rust compiler

The Go compiler is gone; `@astrojs/compiler-rs` is the only compiler. It is faster and stricter:

1.  **Unclosed non-void elements and component tags are errors.** The Go compiler silently accepted `<p>Hello world`.
2.  **Invalid HTML is no longer auto-corrected.** `<p><div>..</div></p>` is passed through as written, and the browser will close the `<p>` early. Run the build, fix the errors, then inspect templates for invalid nesting that the old compiler was quietly repairing (block elements in `<p>`, `<a>` in `<a>`, bad table structures, unclosed `<li>`).
3.  **CSS serialization differs cosmetically**: named colours may be written as hex (`rebeccapurple` to `#639`), and `url()` quoting may change. Only exact-string CSS assertions break.

The effective way to review (2): lint your templates in CI with a validator such as the W3C nu checker over the built HTML, comparing the baseline output with the new one.

### `compressHTML: 'jsx'` by default

The default moved from `true` to `'jsx'`. With JSX whitespace rules, whitespace between sibling elements on separate lines is dropped:

```html
<span>hello</span>
<em>world</em>
```

renders `helloworld`. Fix by writing `<span>hello</span>{" "}<em>world</em>`. To restore the old behaviour set `compressHTML: true`, or `false` to preserve everything. Find affected spots by searching for inline elements (`span`, `a`, `em`, `strong`, `code`) on consecutive lines, and by visual diff.

### Sätteri as the Markdown processor

`.md` and `.mdx` now render through Sätteri; `@astrojs/markdown-remark` is no longer installed by default. If you use no remark/rehype plugins, there is nothing to do: GFM and SmartyPants still apply. If you do:

```bash
npm install @astrojs/markdown-remark
```

```js
// astro.config.mjs
import { defineConfig } from 'astro/config';
import { unified } from '@astrojs/markdown-remark';

export default defineConfig({
  markdown: { processor: unified() },
});
```

The old `markdown.remarkPlugins`, `rehypePlugins` and `remarkRehype` options still work but now require `@astrojs/markdown-remark` to be installed. The MDX integration’s processor is independent (`mdx({ processor })`), and recma plugins work only under `unified()` (`@astrojs/mdx` 8). The migration path is incremental: keep `unified()` now, port plugins to Sätteri MDAST/HAST plugins one at a time, and drop `unified()` when the last one is gone. See Chapter 7.

### Advanced routing and `src/fetch.ts`

Advanced routing is stable and on by default, which reserves `src/fetch.ts` (or `.js/.mjs/.mts`) as a special file like `src/middleware.ts`. If you already have an unrelated `src/fetch.ts` (a common name for an HTTP helper), Astro will try to load it as a routing configuration and fail. Rename the file, or set `fetchFile` to another path or to `null` to disable the feature:

```js
export default defineConfig({
  fetchFile: null,
});
```

### Promoted flags and relocated config

Remove these from `experimental` (they no longer exist there):

```diff
 export default defineConfig({
-  experimental: {
-    logger: logHandlers.json({ pretty: true }),
-    queuedRendering: { enabled: true },
-    rustCompiler: true,
-    advancedRouting: true,
-    cache: { provider: memoryCache() },
-    routeRules: { '/blog/[...path]': { maxAge: 300, swr: 60 } },
-  },
+  logger: logHandlers.json({ pretty: true }),
+  cache: { provider: memoryCache() },
+  routeRules: { '/blog/[...path]': { maxAge: 300, swr: 60 } },
 });
```

- `logger` moves to the top-level `logger` field (Chapter 17).
- `queuedRendering`, `rustCompiler` and `advancedRouting` are simply deleted: they are now the only behaviour. The queued renderer was reshaped into a streaming approach, node polling was removed and the content cache was reduced to tag names, so if you tuned `queuedRendering` options there is nothing left to tune.
- `cache` and `routeRules` become top-level, with `memoryCache()` imported from `astro/config` (Chapter 12).

Still experimental in 7.4, so do not remove them: `clientPrerender`, `collectionStorage`, `incrementalBuild`, `parallelPrerender`, `redirectPage`, `svgOptimizer`, `chromeDevtoolsWorkspace`, `contentIntellisense`. Note that `experimental` is where renamed and promoted options flip often; check the changelog at every minor.

### `@astrojs/db` is removed

`@astrojs/db` and the CLI commands `astro db`, `login`, `logout`, `link` and `init` are gone. Replace with Node’s `node:sqlite` (Node 22.5+, a good fit with the Node adapter for local storage), Drizzle ORM directly, or the database client for your platform (Turso, Neon, PlanetScale). Plan this as a data migration, not a rename: schema definitions, seeding scripts and the `astro:db` imports all need replacing.

### `astro:transitions` internals

The `TRANSITION_*` constants, `isTransitionBeforePreparationEvent()`, `isTransitionBeforeSwapEvent()` and `createAnimationScope()` are removed (they were already unexported in 6.0 documentation). Compare event types directly:

```diff
-console.log(isTransitionBeforePreparationEvent(event));
+console.log(event.type === 'astro:before-preparation');
```

### Container renderer import paths

```diff
- import { getContainerRenderer } from '@astrojs/svelte';
+ import { getContainerRenderer } from '@astrojs/svelte/container-renderer';
```

Available for react, preact, solid-js, svelte, vue and mdx. The package-root import still works but is deprecated, and I confirmed that it logs `[@astrojs/svelte] Importing getContainerRenderer from @astrojs/svelte is deprecated` at runtime. If you author a renderer integration, expose the same entry path (Chapter 18).

### Sessions: what changed and what to check

Session support itself is the 5.7 feature; the changes you meet during the 5-to-7 trip are:

- **Driver config (6.0).** `session.driver: 'redis'` with `options` is deprecated. Use `sessionDrivers.redis({...})` from `astro/config`, or `{ entrypoint: URL }` for runtime-configured drivers (Chapter 12).
- **`session: false` (7.2)** disables sessions entirely and tree-shakes unstorage; adapters skip their default driver.
- **The `Astro.session` documentation inconsistency, resolved by test.** The API reference says `Astro.session` is `undefined` when unconfigured; the 7.0.0 changelog says it is always defined and logs a message. On 7.4.1 with the Node adapter: with sessions configured (the adapter’s default filesystem driver, `session` unset) `typeof Astro.session` was `object` (an `AstroSession`); with `session: false` it was `undefined`, and Astro logged `[WARN] [session] Astro.session was accessed but no session storage is configured`. A static project with no adapter behaved like `session: false`. So: always guard `Astro.session?.get(...)` in code that may run without storage, and expect a warning when it does.

### Adapter API changes

Adapter authors: in 6.0 `entrypointResolution: 'auto'` became available and `'explicit'` (`createExports()`, `exports`, `args`, `start()`) is deprecated; `NodeApp`, `loadApp` and `loadManifest` are deprecated in favour of `createApp()` from `astro/app/entrypoint` plus `createRequest()`/`writeResponse()` from `astro/app/node`. In 7.4, `setPrerenderer` factories receive `outputDirectories`, and `AstroPrerenderer.render()` can return a `PrerenderResult`. Adapter users should simply upgrade each adapter to the major that matches the Astro major (Astro 6 required new majors for Node, Vercel, Netlify and Cloudflare; the Netlify 8, Vercel 11 and Cloudflare 14 majors introduced the experimental CDN cache providers).

## `@astrojs/svelte` upgrades

The integration’s version map:

| Integration | With Astro | Notable changes |
|------------------------|------------------------|------------------------|
| 7.x | 5.x | `$props.id()` unique across islands (7.0.6), `client:only` fallback hiding fix (7.0.7), opt-in async SSR (7.2.0) |
| 8.0 | 6.0 | Node 22.12+, Vite 7, `@sveltejs/vite-plugin-svelte` 6; improved `children` prop type |
| 8.1 | 6.x | `HandleSnippetProps` type shims: non-`children` snippet props and `any` props optional in `.astro`; TypeScript 6 in peers |
| 9.0 | 7.0 | Vite 8, `@sveltejs/vite-plugin-svelte` 7, `getContainerRenderer()` moved to `@astrojs/svelte/container-renderer` |
| 9.1 | 7.4 | Node 22.22.0 minimum |

Practical checklist for Svelte projects:

1.  Use Svelte 5 (the current integration targets Svelte 5 only) and install `svelte` and `typescript` explicitly if the peer warnings appear.
2.  `svelte.config.js` must import `vitePreprocess` from `@astrojs/svelte`; the integration stopped adding preprocessing by default long ago (integration 6.0.0).
3.  Options passed in `svelte({...})` override `svelte.config.js`.
4.  Change container renderer imports (above).
5.  Check libraries: Svelte packages in `node_modules` are routed through Vite’s transform. The integration crawls for packages with a `svelte` peer dependency and marks them `noExternal` for server environments, and fixed `.svelte` files in `node_modules` failing in `prerenderEnvironment: 'node'` Cloudflare setups (8.0.5).
6.  Rune modules (`.svelte.ts`) in SSR: fixed for Cloudflare dev in 8.0.3.
7.  `$props.id()` is unique across islands since 7.0.6; `client:only` fallback hiding was fixed in 7.0.7. If you worked around either bug, remove the workaround.
8.  Async SSR (`compilerOptions.experimental.async` in `svelte.config.js`) arrived in integration 7.2.0; it is opt-in.
9.  Run `svelte-check`; `astro check` does not check `.svelte` files.

Interaction with the platform upgrades: nothing in Svelte’s runes syntax changes between these versions, so component code rarely needs edits. The failures you will see are build-environment ones (Node version, Vite plugin versions, two copies of Svelte’s server runtime in odd monorepo layouts as discussed in Chapter 17).

## Migrating from SvelteKit

The official migration page is a short stub that lists similarities and differences. Here is the substantive version, written for a team with an existing SvelteKit 3 app.

### Decide whether Astro is the right target

Astro fits content-driven pages with islands of interactivity. A SvelteKit app that is a highly interactive client application with deep client-side routing, shared stores across all routes and heavy use of `load` + form actions is a poor candidate; a marketing and catalogue site with a few interactive widgets is an excellent one. Migrate incrementally if possible: split the content-heavy surface into an Astro site and keep the app on SvelteKit under a different path or subdomain.

### Concept mapping

| SvelteKit | Astro |
|------------------------------------|------------------------------------|
| `src/routes/**/+page.svelte` | `src/pages/**/*.astro` (or `.md`/`.mdx`), with Svelte components as islands |
| `+layout.svelte` | An Astro layout component with `<slot />` (Chapter 2) |
| `+page.server.ts` `load` | Frontmatter (top-level `await`), content collections or live collections |
| `+server.ts` | Endpoint file `src/pages/api/x.ts` exporting `GET`, `POST`, … |
| Form actions | Astro Actions (Chapter 11) or endpoints |
| `hooks.server.ts` `handle` | `src/middleware.ts` `onRequest` (Chapter 10) |
| `event.locals` | `Astro.locals` / `context.locals`, typed via `App.Locals` |
| `$env/static/private`, `$env/dynamic/private` | `astro:env/server` secrets (Chapter 16) |
| `$env/static/public` | `astro:env/client` public variables |
| `cookies` | `Astro.cookies` |
| `prerender = true` | `export const prerender = true` (same name) |
| `adapter-*` | `@astrojs/node`, `vercel`, `netlify`, `cloudflare` |
| `$app/navigation` `goto`, `invalidate` | Normal links, or `navigate()` from `astro:transitions/client` with `<ClientRouter />` (Chapter 14) |
| `$app/state` `page` | `Astro.url`, `Astro.params`, props passed to islands |
| Stores in `$lib` shared across components | Rune modules or Nano Stores shared across islands (Chapter 4), with SSR caveats |
| `$lib` alias | Configure `tsconfig` `paths` (for example `"@lib/*"`) |
| `<svelte:head>` | `<head>` in the layout, or props to the layout |
| `{@render children()}` in layouts | `<slot />` in `.astro` layouts |

### Practical steps

1.  **Scaffold** with `npm create astro@latest`, add `@astrojs/svelte` (`astro add svelte`) and pick `output` and an adapter matching your current SvelteKit adapter.
2.  **Copy Svelte components** that are UI-only. Components that use `$app/*` or `$env/*` imports, `load` data or `page` state need rewriting: pass data as props, and read environment through `astro:env`. SvelteKit 3 removed `$lib` and `$app/stores`, so you were already updating those imports.
3.  **Convert routes.** Each `+page.svelte` plus its `load` becomes an `.astro` page whose frontmatter fetches the data and renders the Svelte component with props and a client directive only where interactivity is needed. Remember the hydration rules: props are serialized and cannot include functions or class instances, and children arrive as static HTML (Chapter 3).
4.  **Replace `load` waterfalls** with parallel promises or child components to benefit from streaming (Chapter 17).
5.  **Port form actions** to Astro Actions with Zod 4 validation, keeping progressive enhancement.
6.  **Move `handle` logic** to middleware, mapping `sequence()` usage one to one.
7.  **Re-establish SEO/head logic and trailing-slash policy** (`trailingSlash`, `build.format`); SvelteKit’s defaults differ.
8.  **Replace client-side routing assumptions.** If you need SPA-style transitions, add `<ClientRouter />` and persist stateful islands with `transition:persist` (Chapter 14). Do not combine this with CSP (Chapter 16).
9.  **Rebuild tests.** Vitest and Playwright carry over; component tests of Svelte components work unchanged; page-level tests change to container or E2E tests.

The sharpest mental shift: in SvelteKit, the component tree is the application and hydrates as a whole; in Astro, the page is a server-rendered document and each island hydrates alone. State that lived in a layout-level store must be re-homed in a rune module or event bus that islands share explicitly.

## Legacy flags and deprecations to clear before Astro 8

The reference lists a single legacy flag in 7.4: `legacy.collectionsBackwardsCompat`. It is a temporary helper; remove it once your collections use loaders. Beyond that, make a pass for everything that works today but is deprecated:

- `Astro` in `getStaticPaths()`; `Astro.generator`; non-string params.
- `import.meta.env.ASSETS_PREFIX` (use `astro:config/server`).
- `astro:schema` and `z` from `astro:content` (use `astro/zod`).
- Session driver strings and `session.options` (use `sessionDrivers`).
- `markdown.remarkPlugins`/`rehypePlugins`/`remarkRehype` and the `gfm`/`smartypants` options (use processor options; keep `unified()` only as long as needed).
- `getContainerRenderer()` from integration package roots.
- Adapter-side: `entrypointResolution: 'explicit'`, `exports`, `args`, `createExports()`, `start()`, `NodeApp`, `loadApp`, `loadManifest`, bare-array `getStaticPaths()` and bare-`Response` `render()` in prerenderers, `collectStaticImages`.
- Font providers: the 7.4 `init()` context gains `fetch()` and `getFontProperties()`, and the docs state they become required in Astro 8; add them now if you maintain a provider.
- Imports of removed internals: `astro:actions` internals and `astro:transitions` constants.

A search script keeps you honest:

```bash
rg -n "astro:schema|from 'astro:content'.*\bz\b|ASSETS_PREFIX|Astro\.glob|ViewTransitions|createAnimationScope|TRANSITION_|collectionsBackwardsCompat|driver: ['\"]|from '@astrojs/(react|preact|solid-js|svelte|vue|mdx)'.*getContainerRenderer" src astro.config.* tests
```

Set this as a CI check, and read the build log for deprecation warnings after each upgrade.

## A migration checklist

1.  Node 22.22+, CI and hosting updated.
2.  `npx @astrojs/upgrade`; adapters and integrations on matching majors.
3.  6.x: fix collections, Zod 4, removed APIs, i18n redirect defaults, `import.meta.env`, heading anchors, image behaviour, script/style order.
4.  7.x: fix unclosed tags and invalid nesting, whitespace, `src/fetch.ts` collision, Markdown processor decision, relocate `cache`/`routeRules`/`logger`, delete promoted flags, replace `@astrojs/db`.
5.  Update Container imports; run Vitest in `node` with Vitest 3.2 or newer.
6.  Svelte: container renderer path, `vitePreprocess` import, `svelte-check`.
7.  Deprecation sweep; remove `legacy` flags.
8.  Output diff against the baseline; visual regression; E2E on the production build.

## Key takeaways

- Upgrade one major at a time, platform first (Node 22.22 for 7.4), with the upgrade tool, and compare build output with a frozen baseline.
- 6.0 removed legacy collections, `<ViewTransitions />`, `Astro.glob()`, action internals and CJS configs; it moved to Zod 4, Vite 7 and Shiki 4 and changed defaults silently (i18n redirects, `import.meta.env`, script order, heading IDs, images).
- 7.0 adds Vite 8, the strict Rust compiler, `compressHTML: 'jsx'`, Sätteri, a reserved `src/fetch.ts`, and removes `@astrojs/db` and transition internals.
- Promoted flags (`logger`, `queuedRendering`, `rustCompiler`, `advancedRouting`, `cache`, `routeRules`) leave `experimental`; `cache`, `routeRules` and `logger` become top-level.
- Keep remark/rehype with `markdown.processor: unified()` plus `@astrojs/markdown-remark`, and port incrementally.
- `Astro.session` is `undefined` (with a warning) when sessions are disabled or unconfigured, and defined otherwise: guard it.
- `@astrojs/svelte` 8 matches Astro 6, 9 matches Astro 7; update the container-renderer import path and keep `vitePreprocess` imported from the integration.
- A SvelteKit migration is a re-homing of state and data loading, not a file rename: pages become server-rendered documents and components become islands.
- Clear deprecations and `legacy.collectionsBackwardsCompat` before Astro 8.

## Review Questions

1.  Why upgrade from Astro 5 to 7 in two steps rather than one? Give two concrete reasons.
2.  Which Node version does Astro 6 require, which does 7.4 require, and what else must you check beyond your laptop?
3.  What does `npx @astrojs/upgrade` do that `npm install astro@latest` does not?
4.  Rewrite for Zod 4: `z.string().email().min(5, { message: 'Too short' })`.
5.  Why does `z.string().transform(Number).default("0")` break under Zod 4, and what are two fixes?
6.  List four symptoms of unmigrated legacy collections and their fixes.
7.  What does `legacy.collectionsBackwardsCompat` preserve, and why is it not a destination?
8.  After the 6.0 upgrade, `import.meta.env.FEATURE_X` is `"true"` and `if (import.meta.env.FEATURE_X)` is always taken, even for `"false"`. Explain and fix.
9.  A deploy fails silently: `import.meta.env.DB_PASSWORD` is `undefined` at runtime after upgrading to 6. What changed and what are two fixes?
10. What changed about the order of multiple `<style>` tags in one component in 6.0, and how can it alter appearance?
11. A page’s anchor links to `#picture-` stopped (or started) working after the 6.0 upgrade. Explain.
12. What does the default image service do in 6.0 when you provide only `width` and `height`, and what happens with an SVG when `format="avif"` is set?
13. Why does `i18n.routing.redirectToDefaultLocale` default to `false` in 6.0, and what config recreates the Astro 5 behaviour?
14. Name three things removed in 6.0 that affect adapter or integration authors.
15. List the three kinds of failure the Rust compiler can introduce and how each shows up.
16. What does this render in 7.0 and how do you fix it?

```html
<a href="/a">A</a>
<a href="/b">B</a>
```

17. A page contains `<p><div>x</div></p>`. What did the Go compiler do, what does the Rust compiler do, and what does the browser do afterwards?
18. You have an `src/fetch.ts` that exports an HTTP helper. What happens after upgrading to 7 and what are your two options?
19. Which experimental flags were promoted in 7.0, and which of them move to a new top-level location?
20. A team uses `remarkPlugins: [remarkToc]` in `markdown`. Describe the minimal change to keep it working in 7.0 and a longer-term plan.
21. What replaces `@astrojs/db`, and why is this a data migration rather than a rename?
22. Replace `isTransitionBeforeSwapEvent(event)` for 7.0.
23. What are the old and new import lines for the Svelte container renderer, and what happens if you keep the old one?
24. On 7.4.1 with `session: false`, what is `typeof Astro.session`, and what is logged when you access it? What does it tell you about the API reference versus the 7.0.0 changelog?
25. Replace `session: { driver: 'redis', options: { url } }` with the non-deprecated form.
26. Match each `@astrojs/svelte` major to its Astro major and give one change for each.
27. Multiple choice: which statement about `vitePreprocess` is correct for the Svelte integration?

<!-- -->

a.  It is applied by default and cannot be disabled.
b.  It must be imported from `@sveltejs/vite-plugin-svelte` in Astro 7 only.
c.  In `svelte.config.js`, import it from `@astrojs/svelte`; it is not added by default.
d.  It was removed in 6.0.

<!-- -->

28. Map five SvelteKit concepts to their Astro equivalents (route, layout, `load`, `handle`, `$env/static/private`).
29. A SvelteKit app keeps a global cart store in a layout. Describe how you would re-home it in Astro and what to watch for during SSR.
30. Design question: list the order in which you would clean deprecations before Astro 8, and one automated check you would add to CI.
