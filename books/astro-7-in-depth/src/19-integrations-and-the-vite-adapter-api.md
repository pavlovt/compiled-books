# Chapter 18: Integrations and the Vite/Adapter API

Almost everything in Astro that is not core is an integration: the Svelte renderer, the Node adapter, the MDX processor, the sitemap generator. An integration is a plain object with a name and a set of lifecycle hooks, and it is the only supported way to extend the build, the dev server, the router, the renderers and the deployment target. Understanding the hook model lets you read official integrations as documentation, write the small project-specific integrations that senior teams end up needing (a health route, a header middleware, an internal client directive), and diagnose why a third-party integration behaves as it does.

This chapter walks the hook lifecycle in order, shows each `astro:config:setup` helper with a working example, covers renderers and client directives, the four Vite environments, dev toolbar apps, adapter authoring (entrypoint resolution, feature maps, `adapterFeatures`, custom prerenderers), and publishing and testing. All examples were assembled into one integration (called `ledger`) and built and run against Astro 7.4.1 with `@astrojs/node` 11; the logged hook order and HTTP results quoted below are real output.

## What an integration is

```ts
import type { AstroIntegration } from 'astro';

export default function myIntegration(options = {}): AstroIntegration {
  return {
    name: 'my-integration',
    hooks: {
      'astro:config:setup'({ updateConfig, logger }) { /* ... */ },
    },
  };
}
```

You register it in `astro.config.mjs` via `integrations: [myIntegration()]`. Integrations may be async, nested in arrays (Astro flattens them) or falsy (ignored), which allows `integrations: [cond && thing()]`. A config file can import TypeScript directly (`import ledger from './integrations/ledger/index.ts'` worked in my test project), because Astro loads the config through Vite.

Every hook receives a `logger` (an `AstroIntegrationLogger`) whose messages are labelled with the integration’s `name`; `logger.fork('name/build')` creates a child with another label, and `info`, `warn`, `error` and `debug` are available. Use it instead of `console.log` so output respects `--silent`, `--verbose` and a custom logger (Chapter 17).

## The lifecycle, in order

Running `astro build` on the test integration with a hook logging at every stage printed:

```text
[ledger] config:setup command=build isRestart=false
[ledger] routes: /_server-islands/[name], /_image, /_ledger/health, / (static)
[ledger] config:done buildOutput=server
[ledger] routes: ... , / (static), /404
[ledger] build:start
[ledger] build:setup pages=3
[ledger] build:generated /.../dist/client/
[ledger] build:done
```

and `astro dev` printed `config:setup command=dev`, `config:done`, `routes`, `server:setup`. The order is:

| Hook | When | Typical use |
|------------------------|------------------------|------------------------|
| `astro:config:setup` | Before Vite and Astro config resolve | Extend config, add renderers, directives, routes, middleware, scripts, toolbar apps |
| `astro:route:setup` | Build: before bundling. Dev: while building the module graph and on every file-route change | Set `route.prerender` per route |
| `astro:routes:resolved` | After routes are known; dev: on every route change | Read the full route table |
| `astro:config:done` | After all `config:setup` hooks ran | Read final config, `setAdapter`, `injectTypes`, read `buildOutput` |
| `astro:server:setup` | Dev: after the Vite server is created, before `listen()` | Vite dev middleware, toolbar messaging, `refreshContent` |
| `astro:server:start` / `astro:server:done` | Dev: after listening / on shutdown | Print addresses, clean up |
| `astro:build:start` | Before the production build | Global clients, `setPrerenderer` |
| `astro:build:setup` | Immediately before the build, Vite config final | Last-chance Vite changes, inspect `pages` |
| `astro:build:ssr` | After the SSR build | `manifest`, edge `middlewareEntryPoint` |
| `astro:build:generated` | After static pages are generated | `routeToHeaders` for host config files |
| `astro:build:done` | End of build | Post-processing, `pages`, `assets` |

Two details from the run deserve attention. `astro:routes:resolved` fired twice during the build: the second list contains `/404`, which Astro adds after the first pass. Treat the hook as idempotent and replace, never append to, what you derived. And `astro:config:done` reported `buildOutput=server` although `output: 'static'` was set: with an on-demand route injected (`prerender: false`) and an adapter present, the project’s effective output is `server`. `buildOutput` is the authoritative value; do not infer it from `config.output`.

> **Note:** `astro:route:setup` fires in dev on every change to a file-based route, and `astro:config:setup` is called again on a dev-server restart (`isRestart: true`). Anything you create in `config:setup` (watchers, timers) must tolerate being invoked more than once.

## `astro:config:setup` helpers

### `updateConfig`

`updateConfig(partial)` deep-merges into the user config, including the work of other integrations that ran before you. The most common payload is Vite plugins:

```ts
updateConfig({ vite: { plugins: [configPlugin(options)] } });
```

`config` (read-only) in this hook is the user-supplied config resolved before any integration; if you need the final merged config, read it in `astro:config:done`. `command` is `'dev' | 'build' | 'preview' | 'sync'`; `isRestart` distinguishes the first dev start from reloads. `addWatchFile(path)` makes the dev server restart when a file Vite does not watch changes.

### `injectRoute`

`injectRoute({ pattern, entrypoint, prerender? })` adds a route from a package. The pattern uses file-routing syntax (`/foo/[bar]`, `/foo/[...rest]`) without extension. The entrypoint is a `.astro` page or `.ts`/`.js` endpoint, either a bare specifier exported from your `package.json` `exports`, a relative path (for local integrations), or a `URL` (`new URL('./health.ts', import.meta.url)`). `prerender` is needed only where Astro cannot detect an `export const prerender`.

```ts
injectRoute({
  pattern: '/_ledger/health',
  entrypoint: new URL('./health.ts', import.meta.url),
  prerender: false,
});
```

```ts
// integrations/ledger/health.ts
import type { APIRoute } from 'astro';
import { header } from 'virtual:ledger/config';
export const prerender = false;
export const GET: APIRoute = () => Response.json({ ok: true, header });
```

I started the built server and requested the route: 200 with `{"ok":true,"header":"x-ledger-demo"}`. Injected routes take part in normal route priority (Chapter 5); the reserved `_astro`, `_server-islands` and `_actions` prefixes cannot be shadowed, which is why the example uses `/_ledger/`, an unreserved namespace.

### `addMiddleware`

`addMiddleware({ entrypoint, order: 'pre' | 'post' })` registers a module exporting `onRequest`. `pre` runs before the user’s middleware, `post` after. It accepts a `URL` entrypoint.

```ts
// integrations/ledger/middleware.ts
import { defineMiddleware } from 'astro:middleware';
import { header } from 'virtual:ledger/config';

export const onRequest = defineMiddleware(async (_ctx, next) => {
  const res = await next();
  res.headers.set(header, '1');
  return res;
});
```

The same response that served `/_ledger/health` carried `x-ledger-demo: 1`. Remember that middleware does not run for prerendered pages at request time (Chapter 10), so the header appeared on on-demand responses only; the prerendered `/` response from the Node server did not carry it.

### `injectScript`

`injectScript(stage, content)` adds JavaScript to every page. The stage decides how it is processed:

| Stage | Behaviour |
|------------------------------------|------------------------------------|
| `head-inline` | Inline `<script>` in `<head>`; not bundled or resolved by Vite |
| `before-hydration` | Imported on the client before any island hydrates; bundled by Vite |
| `page` | Bundled with the page’s other `<script>` tags, emitted as `<script type="module">` |
| `page-ssr` | Imported in the frontmatter of every page component; runs once on first evaluation; no `Astro` global. Used to inject a global CSS import |

In my build, `injectScript('page', ...)` produced `_astro/page.<hash>.js`. Under CSP (Chapter 16), `head-inline` scripts receive hashes like other inline scripts, while `page` and `before-hydration` are external modules covered by `'self'`; prefer the bundled stages.

### `createCodegenDir` and `injectTypes`

`createCodegenDir()` creates `<root>/.astro/integrations/<normalized_name>/` and returns its URL: a sanctioned scratch directory for generated files. `injectTypes({ filename, content })` (in `astro:config:done`) writes a `.d.ts` file into that area so that the user’s TypeScript sees your declarations, for example for a virtual module:

```ts
'astro:config:done'({ injectTypes }) {
  injectTypes({
    filename: 'virtual.d.ts',
    content: `declare module 'virtual:ledger/config' {
      export const healthPath: string;
      export const header: string;
    }`,
  });
}
```

The `filename` must end in `.d.ts`. It returns the URL, so you can rewrite the file later.

### Custom hooks

Integrations may expose their own hooks to other integrations by augmenting the `Astro.IntegrationHook` interface through global declaration merging. Names starting `astro:` are reserved for Astro; use your own prefix (`ledger:ready`). Other integrations can then implement your hook, and your integration is responsible for deciding when to run it (the reference documents the type augmentation, not an invocation helper).

## Virtual modules and the Vite environments

Most integrations that pass build-time data to runtime code do it with a virtual module in a Vite plugin:

```ts
const VIRTUAL = 'virtual:ledger/config';
const RESOLVED = '\0' + VIRTUAL;

function configPlugin(options): Plugin {
  return {
    name: 'ledger:config',
    resolveId(id) { if (id === VIRTUAL) return RESOLVED; },
    load(id) {
      if (id !== RESOLVED) return;
      if (this.environment?.name === 'client') {
        throw new Error('virtual:ledger/config is server-only');
      }
      return `export const healthPath = ${JSON.stringify(options.healthPath)};
export const header = ${JSON.stringify(options.header)};`;
    },
  };
}
```

The `\0` prefix on the resolved ID is the Rollup convention that marks a module as virtual so other plugins skip it. Always serialize values with `JSON.stringify`.

Astro 6 moved to Vite’s Environment API, and Astro 7 builds on Vite 8. There are four environments:

- `client`: browser output (island chunks, bundled scripts).
- `ssr`: the on-demand server bundle.
- `prerender`: used during `astro build` to build static pages. This is why my timings report in Chapter 17 listed “prerender bundle”, “ssr bundle” and “client bundle” as separate phases.
- `astro`: a dev-only secondary SSR environment used when Vite’s `ssr` environment is not a runnable dev environment (for example with the Cloudflare adapter running workerd).

Inside a plugin hook, `this.environment.name` tells you which one is being processed. Use that to forbid server-only modules in the client (as above), to apply transforms to one target, or to provide different implementations per environment. Plugins can also set per-environment configuration through the standard `configEnvironment` hook; the Svelte integration does exactly this: it adds Svelte packages from `node_modules` to `resolve.noExternal` for server environments, and sets `optimizeDeps.exclude: ['svelte']` so that Svelte’s server runtime exists as a single transformed copy (otherwise two copies with separate render-context state crash SSR, the same failure signature I described in Chapter 17).

`astro:build:setup` exposes the final Vite `InlineConfig` and a `pages` map, and `updateConfig` there merges more Vite config at the last moment. Prefer `astro:config:setup` unless you need to see everything first.

## Renderers

A renderer is an integration that teaches Astro to render a component syntax. `@astrojs/svelte` is one. You register it with `addRenderer({ name, serverEntrypoint, clientEntrypoint? })`. The server entrypoint’s default export implements:

- `check(Component, props, slots, metadata)` returning a boolean: Astro asks each registered renderer in turn until one claims the component.
- `renderToStaticMarkup(Component, props, slots, metadata)` returning `{ html, attrs? }`. `slots` is a record of **HTML strings**. `metadata.hydrate` is the client directive in use (undefined when the component is not hydrated), which lets you skip serializing hydration state. `attrs` are added to the `astro-island` element.
- Optional `supportsAstroStaticSlot` and `renderHydrationScript()`.

The client entrypoint default-exports `(element) => async (Component, props, slots, { client }) => void`. Astro dispatches `astro:unmount` on the island element when it is removed, so clean up there.

I built a minimal renderer for components marked `Component.tiny = true`:

```js
// integrations/ledger/tiny-server.js
const renderer = {
  name: 'ledger-tiny',
  async check(Component) { return typeof Component === 'function' && Component.tiny === true; },
  async renderToStaticMarkup(Component, props, slots, metadata) {
    const { tag, text } = Component(props);
    return {
      attrs: metadata?.hydrate ? { 'data-tiny': 'true' } : undefined,
      html: `<${tag}>${text}${slots.default ?? ''}</${tag}>`,
    };
  },
};
export default renderer;
```

```js
// integrations/ledger/tiny-client.js
export default (element) => async (Component, props, slots) => {
  const { tag, text } = Component({ ...props, slots });
  const node = document.createElement(tag);
  node.textContent = text + ' (hydrated)';
  element.replaceChildren(node);
  element.addEventListener('astro:unmount', () => node.remove(), { once: true });
};
```

The output contained `<astro-island ... data-tiny="true" component-export="Greeting" renderer-url="/_astro/tiny-client.<hash>.js" ...>`, showing `attrs` merged onto the island and the client entrypoint emitted as a chunk.

**A pitfall found in testing:** I first passed the entrypoints as `new URL('./tiny-server.js', import.meta.url)` objects. The build failed with `Cannot find the built path for file:///.../tiny-client.js`. For `addRenderer`, pass the entrypoint as a **string** (a package specifier or an absolute path such as `new URL(..., import.meta.url).pathname`). The documentation types say `string | URL`, but for the client entrypoint of a local file in this version the `URL` form did not resolve to a built asset. The same URL form worked for `injectRoute`, `addMiddleware` and `addDevToolbarApp`. For published packages, a bare specifier backed by `exports` avoids the issue entirely.

Compare with the real Svelte integration, which is a good size to read: `@astrojs/svelte` calls `addRenderer(getContainerRenderer())` (the same descriptor is also what the container renderer export returns), crawls `node_modules` for packages with a `svelte` peer dependency so that they go through Vite’s transform instead of being externalized, and installs `@sveltejs/vite-plugin-svelte` together with the environment plugin above. The renderer’s `check` recognizes Svelte components, and its `renderToStaticMarkup` handles the slot-to-snippet interop discussed in Chapter 3.

## Client directives

`addClientDirective({ name, entrypoint })` adds `client:<name>` for use in `.astro` files. The entrypoint’s default export is called per island with `(load, options, element)`; `load()` returns a promise for a `hydrate` function:

```js
// integrations/ledger/click.js
/** @type {import('astro').ClientDirective} */
export default (load, _opts, _el) => {
  window.addEventListener('click', async () => {
    const hydrate = await load();
    await hydrate();
  }, { once: true });
};
```

```html
---
import { Greeting } from '../tiny.js';
---
<Greeting name="Ada" client:click><i>slot</i></Greeting>
```

The build produced `client="click"` on the island and bundled the directive into the page. Entrypoints are bundled with esbuild only and are inlined into the page, so keep them tiny, as the reference warns; every page that uses the directive pays for the bytes. Add TypeScript support to your library by augmenting `AstroClientDirectives`:

```ts
import 'astro';
declare module 'astro' {
  interface AstroClientDirectives { 'client:click'?: boolean }
}
```

The directive must be a string path or a bare specifier. In my test I used `new URL(..., import.meta.url).pathname`; the same caveat as renderers applies.

## Dev toolbar apps

`addDevToolbarApp({ id, name, icon, entrypoint })` adds an app to the dev toolbar. `icon` is a built-in icon name (such as `'astro:logo'`) or SVG markup. The entrypoint default-exports `defineToolbarApp({ init, beforeTogglingOff })` from `astro/toolbar`. `init(canvas, app, server)` is called once, when the browser is idle or the user clicks the app, whichever is first:

- `canvas` is a `ShadowRoot` dedicated to your app, absolutely positioned so it cannot affect page layout. Build UI with the standard DOM and the toolbar’s custom elements (`astro-dev-toolbar-window`, `-button`, `-badge`, `-card`, `-toggle`, `-radio-checkbox`, `-highlight`, `-tooltip`, `-icon`, `-select`).
- `app` is an `EventTarget` with helpers: `onToggled`, `onToolbarPlacementUpdated`, `toggleState`, `toggleNotification`.
- `server` communicates with the dev server: `send(event, data)` and `on(event, cb)` on the client; on the server side, `astro:server:setup` provides `toolbar.on`, `toolbar.send`, `toolbar.onAppInitialized` and `toolbar.onAppToggled`.

```js
// integrations/ledger/toolbar.js
import { defineToolbarApp } from 'astro/toolbar';

export default defineToolbarApp({
  init(canvas, app, server) {
    const win = document.createElement('astro-dev-toolbar-window');
    win.textContent = 'Ledger app';
    canvas.append(win);
    app.onToggled(({ state }) => server.send('ledger:toggled', { state }));
    server.on('ledger:pong', (d) => console.log('pong', d));
  },
});
```

```ts
// in the integration
'astro:server:setup'({ toolbar, logger }) {
  toolbar.on('ledger:toggled', ({ state }) => {
    logger.info(`toolbar app toggled: ${state}`);
    toolbar.send('ledger:pong', { at: Date.now() });
  });
}
```

Use event names namespaced by your integration. `beforeTogglingOff(canvas)` may return `false` (or a promise of it) to veto closing. The toolbar exists only in `astro dev`, so a toolbar app must be inert in production by construction. The server-side half lives in `astro:server:setup` for the same reason. (I verified that the app registers and the dev server starts with the hook; the interactive toolbar UI itself needs a browser and was not exercised.)

## Adapters

An adapter is an integration that calls `setAdapter()` in `astro:config:done`. It does two jobs: supply a server entrypoint that translates the host’s request format to Web `Request`/`Response`, and configure the build for the host.

```js
export default function createIntegration() {
  return {
    name: '@example/my-adapter',
    hooks: {
      'astro:config:done': ({ setAdapter }) => {
        setAdapter({
          name: '@example/my-adapter',
          entrypointResolution: 'auto',
          serverEntrypoint: '@example/my-adapter/server.js',
          supportedAstroFeatures: {
            serverOutput: 'stable',
            staticOutput: 'stable',
            envGetSecret: 'stable',
          },
          adapterFeatures: { middlewareMode: 'classic' },
        });
      },
    },
  };
}
```

### Entrypoint resolution

`entrypointResolution` is `'explicit'` (the legacy default, deprecated) or `'auto'` (recommended; the only behaviour in a future major). With `'explicit'`, the entrypoint exports a `createExports()` function and you list the exported names in `exports`; `args` passes build-time JSON to it. With `'auto'` you own the module: `serverEntrypoint` points at it, or, if you need Vite-level control, you set `vite.build.rollupOptions.input`. New adapters must use `'auto'`; migrate existing ones (Chapter 19).

The auto entrypoint builds on `createApp()` from `astro/app/entrypoint`:

```js
// my-adapter/server.js
import { createApp } from 'astro/app/entrypoint';
import { setGetEnv } from 'astro/env/setup';

setGetEnv((key) => process.env[key]);
const app = createApp();

export async function handler(event, context) {
  // translate the host event to a Request, call app.render(request),
  // translate the Response back
}
```

`astro/app/node` offers `createRequest` and `writeResponse` helpers for Node’s `IncomingMessage`/`ServerResponse`; Chapter 8 covers `createApp` in detail. The deprecated `NodeApp`, `createExports()` and `start()` are the old way.

### Passing build-time config to the entrypoint

The server entrypoint cannot see your integration closure. Use the virtual-module pattern from above: a Vite plugin registered in `astro:config:setup` that serializes values, and a `.d.ts` for typing. The reference example serializes `config.build.assets`. Note the modern plugin form with `filter` objects on `resolveId`/`load`, which Vite 8 prefers for performance.

### `supportedAstroFeatures`

A map from feature name to `AdapterSupport`: `'stable' | 'experimental' | 'limited' | 'deprecated' | 'unsupported'`, or an object `{ support, message, suppress: 'default' | 'all' }` with a custom log message. Astro uses it to validate the user’s project and print contextual warnings or errors. The documented features are `staticOutput`, `hybridOutput`, `serverOutput`, `i18nDomains`, `envGetSecret` and `sharpImageService`. `hybridOutput` is a historical name: `output` has only two values since Astro 5, but the feature key remains in the list.

Declaring `envGetSecret` obliges you to call `setGetEnv()` from `astro/env/setup` before any `getSecret()` call, and where the environment is per-request (Workers), set it inside the request handler:

```js
export default {
  async fetch(request, env) {
    setGetEnv((key) => env[key]);
    return app.render(request);
  },
};
```

### `adapterFeatures`

Features that change the emitted files and therefore carry obligations:

- `middlewareMode: 'classic' | 'edge'`. `classic` bundles middleware into the server and runs it only on on-demand requests. `edge` emits it separately; consume `middlewareEntryPoint` (a `URL`, `undefined` if you did not opt in) in `astro:build:ssr` and wrap it as an edge function.
- `buildOutput: 'static' | 'server'` forces an output shape.
- `staticHeaders: true`: Astro collects headers produced by features for static pages (for example CSP, which then does not emit a `<meta>`) and gives you `routeToHeaders` in `astro:build:generated`, so you can write the host’s headers file. The Node adapter’s own `staticHeaders` option builds on this (Chapter 16).
- `preserveBuildClientDir` and `preserveBuildServerDir` (6.4): keep `dist/client` and `dist/server` even for static output, which hosts with a fixed layout, or static sites with server islands, require.

`client.internalFetchHeaders` and `client.assetQueryParams` let an adapter add headers to Astro’s internal client fetches (actions, view transitions, server islands, prefetch) and query parameters to asset URLs: the hooks used for skew protection (Chapter 8).

### Preview entrypoint

`previewEntrypoint` points to a module whose default export is a `CreatePreviewServer` function taking the server params (host, port, …) and returning a `PreviewServer`. Static-only adapters need none.

### Custom prerenderer

An adapter that must render static pages in a different runtime (the Cloudflare adapter renders in workerd) uses `setPrerenderer` in `astro:build:start`. It accepts either an `AstroPrerenderer` or a factory `(defaultPrerenderer, { outputDirectories }) => AstroPrerenderer`:

```js
'astro:build:start'({ setPrerenderer }) {
  setPrerenderer((defaultPrerenderer, { outputDirectories }) => ({
    name: 'my-prerenderer',
    async setup() { /* start a preview server on outputDirectories.server */ },
    async getStaticPaths() { return defaultPrerenderer.getStaticPaths(); },
    async render(request, { routeData }) {
      const res = await fetch(`http://localhost:4321${new URL(request.url).pathname}`);
      return { response: res };   // PrerenderResult
    },
    async teardown() { /* stop it */ },
  }));
}
```

Facts to keep straight, from the 7.x types: `getStaticPaths` returns `{ paths, metadata }` (a bare array is deprecated), and `render` should return a `PrerenderResult` (`{ response, metadata? }`; a bare `Response` is deprecated since 7.2, and the metadata tells Astro which images to generate). The `collectMetadata` option is deprecated and always true. `outputDirectories` (7.4) holds the `client`, `server` and `prerender` directories as `URL`s resolved by Vite; use them instead of `build.client`/`build.server`, because other integrations can relocate output. Wrapping the default prerenderer rather than replacing it keeps image collection and other built-in behaviour.

### Edge cases for adapter authors

- Sessions: adapters that provide default drivers supply them; with `session: false` (7.2) they must skip the default driver.
- Cache providers (Chapter 12) are separate modules exported by the adapter package (for example `@astrojs/netlify/cache`), not part of `setAdapter`.
- `astro:build:generated` plus `staticHeaders` is where `_headers`-style files come from.

## Testing an integration

Two layers work well:

1.  **Hook-level unit tests.** Call the hooks with fake arguments in Vitest and assert on `updateConfig`/`injectRoute` calls. This catches config-shape mistakes cheaply, but proves nothing about Vite.
2.  **Fixture builds.** Keep a small `fixtures/basic` project that lists your integration, run `astro build` programmatically (`import { build, dev, preview } from 'astro'` are exported from the package), and assert on `dist`: that routes exist, HTML contains your markup, headers are set. For a server adapter, start the built entrypoint and make HTTP requests, as I did with the health route and header. Test both `dev` and `build`, because several hooks differ (`isRestart`, `server:setup`).

Also test with the Svelte integration present, since renderer ordering and Vite plugin interaction are common sources of bugs; and test `astro sync` (the `sync` command) since `config:setup` runs there too and must not require a running server.

## Publishing

Astro components, integrations and adapters publish to npm as ordinary packages. There is no required build step for files Astro or Vite handle natively (`.astro`, `.ts`, `.css`), but integration code that Node must load before Vite exists (the config-time module) must be loadable by Node, so ship compiled JavaScript for it, or document that the config is loaded through Vite as in my TypeScript example. Practical checklist:

- `package.json`: `"type": "module"`, an `exports` map listing every entrypoint used by bare specifier (`./server.js`, `./middleware`, `./dashboard.astro`, `./client.js`, the container-renderer), `peerDependencies` on `astro` with the range you tested, `types`.
- Keywords `astro-integration`, `astro-component` and `withastro` make the package discoverable and list it in the integrations library.
- Export the integration factory as the default export and options types.
- Version against Astro minors, and note the Node floor (Astro 7.4 needs Node 22.22.0 or newer).
- A package that ships a renderer should also export `getContainerRenderer()` from `./container-renderer` so users can test with the Container API (Chapter 17).

## Key takeaways

- An integration is `{ name, hooks }`; hooks run in a fixed order: `config:setup`, `route:setup`, `routes:resolved`, `config:done`, then `server:*` for dev or `build:start`, `build:setup`, `build:ssr`, `build:generated`, `build:done`.
- `routes:resolved` can fire more than once; `buildOutput` in `config:done` is the authoritative output mode.
- `config:setup` is the toolbox: `updateConfig`, `injectRoute`, `addMiddleware` (`pre`/`post`), `injectScript` (four stages), `addRenderer`, `addClientDirective`, `addDevToolbarApp`, `addWatchFile`, `createCodegenDir`.
- Virtual modules are plugins resolving a `\0`-prefixed id; `this.environment.name` distinguishes `client`, `ssr`, `prerender` and the dev-only `astro` environment.
- Pass local renderer and directive entrypoints as strings; `URL` objects failed for a client renderer in my build.
- Adapters call `setAdapter` with `entrypointResolution: 'auto'`, a `serverEntrypoint` built on `createApp()`, a `supportedAstroFeatures` map, and `adapterFeatures` that carry obligations (`middlewareEntryPoint`, `routeToHeaders`).
- A custom prerenderer returns `PrerenderResult`, and receives `outputDirectories` in 7.4.
- Test hooks as units and the integration as a fixture build; publish with an `exports` map and the right keywords.

## Review Questions

1.  List the integration hooks in the order they run during `astro build`, and say which ones run only in dev.
2.  In `astro:config:done`, `buildOutput` is `'server'` although the user wrote `output: 'static'`. Give one realistic cause.
3.  Why should the work in `astro:routes:resolved` be idempotent?
4.  What is the difference between reading `config` in `astro:config:setup` and in `astro:config:done`?
5.  How does `updateConfig` combine your values with the user’s and other integrations’?
6.  Write the `injectRoute` call that mounts an endpoint file shipped in the package `@acme/health` at `/_acme/health`, and the `exports` entry needed in its `package.json`.
7.  When is `prerender` needed in `injectRoute`?
8.  What does `addMiddleware` with `order: 'pre'` guarantee, and why will its header not appear on prerendered pages served by a static host?
9.  Compare the four `injectScript` stages and pick one for each: (a) a global CSS import, (b) code that must run before any island hydrates, (c) a tiny snippet that must be in `<head>` unprocessed, (d) analytics code to be bundled with page scripts.
10. What file does `injectTypes` create and where, and why is it preferable to shipping a manually included `.d.ts`?
11. What does the `\0` prefix on a virtual module id mean?
12. Find the bug: a plugin’s `load` hook for `virtual:app/secrets` returns the secret values, and an island imports that module. Which environment-based guard prevents shipping it to the browser?
13. Name the four Vite environments in Astro and what each is used for.
14. Why does `@astrojs/svelte` set `optimizeDeps.exclude: ['svelte']` for server environments?
15. A renderer’s `check()` returns `true` for every component. What is the consequence for a project that also uses the Svelte renderer?
16. What does `renderToStaticMarkup` receive as `slots`, and what does `metadata.hydrate` allow a renderer to do?
17. What event does Astro dispatch when an island is removed, and who should listen for it?
18. In the test build, passing `new URL('./tiny-client.js', import.meta.url)` as `clientEntrypoint` failed. What was the error and what is the workaround?
19. Why must client directive entrypoints be kept small, and how are they bundled?
20. What are the three arguments to a client directive function and what does `load()` return?
21. What arguments does `init()` of a toolbar app receive, and in which hook do you handle the server side of toolbar messages?
22. Why is a dev toolbar app not a security concern in production?
23. Explain the difference between `entrypointResolution: 'explicit'` and `'auto'`.
24. An adapter declares `supportedAstroFeatures: { envGetSecret: 'stable' }`. What must its server entrypoint do?
25. What is `middlewareMode: 'edge'` and which hook delivers the middleware file?
26. How does `adapterFeatures.staticHeaders` interact with CSP, and which hook gives the adapter the data?
27. Name the three directories in `outputDirectories` and explain why you should use them instead of `build.client`.
28. What should `render()` of a custom prerenderer return in Astro 7, and what is deprecated?
29. Describe a two-layer test strategy for an integration, and one thing each layer cannot detect.
30. Multiple choice: which is NOT a documented keyword for npm discoverability?

    a.  `astro-component`
    b.  `astro-integration`
    c.  `withastro`
    d.  `astro-adapter-svelte`

