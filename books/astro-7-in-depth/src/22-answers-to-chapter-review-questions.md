# Answers to Chapter Review Questions

## Chapter 1: Islands, the Rendering Model and What Changed in Astro 7

1.  Astro components and un-directived framework components are rendered to HTML on the server and add no client runtime; only `client:*` islands (and bundled `<script>` tags) ship JavaScript, so cost scales with interactive regions. Answer: (a), (b). (c) ships the component, the renderer and the framework runtime, and (d) ships the script.
2.  An SPA is better for an authenticated, highly interactive application where the bundle is cached after first load and SEO is irrelevant, such as an internal dashboard or editor. Embed one in Astro with a single island using `client:only="svelte"` (or `client:load`) that hosts the whole app.
3.  A client island is a UI-framework component hydrated in the browser (the “add to cart” Svelte button). A server island (`server:defer`) is an Astro component whose server-rendered content is fetched separately after the page shell (the personalized header showing the user’s name or a price/stock block). The first ships JavaScript, the second ships HTML.
4.  For a prerendered route it runs at build time, once per generated path. For an on-demand route it runs on every request. It never runs in the browser.
5.  The build fails with the `NoAdapterInstalled` error (“Cannot use server-rendered pages without an adapter”). Install and configure an adapter (for example `@astrojs/node`) or remove `prerender = false`.
6.  On-demand rendering streams HTML; once the first chunk is flushed the status code and headers can no longer change. A redirect must therefore be issued by the page itself before any output begins, not from a child component rendered later in the stream.
7.  The server render executes the top level of the script, where `localStorage` does not exist, so it throws `ReferenceError`. Read it inside `onMount` or an `$effect` (browser-only), or guard with `typeof localStorage !== 'undefined'`/`browser`-style checks, and initialize `$state` with a default.
8.  `client`, `ssr`, `prerender` and `astro`. The `astro` environment exists only during development, as a secondary SSR environment when `ssr` is not a runnable dev environment.
9.  It is the output of the `prerender` Vite environment: the server-side bundle that rendered the static pages during the build. It is a build intermediate and is not deployed because the final output is already the HTML files.
10. The `<p>` is never closed. The Rust compiler errors on unclosed tags (“Unexpected token”), whereas the Go compiler silently accepted them. Fix: `<p>Welcome</p>`.
11. With `'jsx'` (default) it emits `<a href="/a">Home</a><a href="/b">Blog</a>` and renders `HomeBlog` with no space. With `compressHTML: true` a single space is kept between them. A fix that works for both is `<a href="/a">Home</a>{" "}<a href="/b">Blog</a>` (or use CSS gap in a flex container).
12. (c). The compiler passes the markup through unchanged; the browser then closes the `<p>` before the `<div>`.
13. The server HTML is emitted as authored (`<div>` inside `<p>`), but the browser’s parser rewrites the DOM, so the DOM no longer matches what Svelte expects during `hydrate()`, causing hydration mismatches. Fix the nesting in the template.
14. `'static'` (default) and `'server'`. `'hybrid'` was folded into this model: choose the default that suits most routes and override individual routes with `export const prerender = true|false`. (The docs still list a `hybridOutput` adapter feature name.)
15. Node 22.22.0 or newer (raised in 7.4.0), Vite 8, Zod 4 and Shiki 4 (the latter two since 6.0).
16. Experimental in 6.x and promoted in 7.0: advanced routing, the Rust compiler, the logger, queued/streaming rendering, route caching (`cache`/`routeRules`). (CSP, fonts and live collections were promoted earlier, in 6.0.) Still experimental: `clientPrerender`, `collectionStorage`, `incrementalBuild`, `parallelPrerender`, `redirectPage`, `svgOptimizer`.
17. False. Route caching is stable, but the adapter CDN cache providers (`cacheNetlify()`, `cacheVercel()`, `cacheCloudflare()`) are documented as experimental and must be manually enabled.
18. It is the reserved advanced-routing entrypoint that replaces the built-in request pipeline with a default-exported `{ fetch(request) }`. For an unrelated `src/fetch.ts`, rename the file (and its imports), or set `fetchFile` to another filename or `null` to disable advanced routing.
19. `astro check` does not check `.svelte` files. Run `svelte-check --tsconfig ./tsconfig.json` as well, for example `astro check && svelte-check`.
20. `component-url`, `component-export` and `renderer-url` say what to import. `client` and `opts` say when/how to start, and `props` carries the data. `props` is plain readable HTML, so never pass secrets (tokens, internal IDs you do not want exposed) as island props.
21. Description: static, no island. Gallery: `client:media="(min-width: 64em)"` (desktop only) or `client:visible` if below the fold. Add-to-cart button: `client:load` (must work immediately). Reviews: `client:visible`, or a server island if they are dynamic, server-rendered content, so JavaScript is deferred until needed.
22. `vitePreprocess()` is re-exported by `@astrojs/svelte`. Without `svelte.config.js` (not created by default since integration 6.0) no preprocessing is configured, so `<style lang="scss">` and similar preprocessed languages stop working. Plain Svelte 5 with `lang="ts"` type annotations and CSS still works.
23. It restores the Astro 6 HTML-aware whitespace compression (a single space is preserved between inline elements). That lets you migrate without visual regressions and audit missing spaces afterwards.
24. (b). It is a build-time environment that builds the code used to render static pages.
25. Nothing is fetched: the directive script observes the element with an `IntersectionObserver` and does not import the component or renderer. The user sees the server-rendered HTML snapshot, which is not interactive.
26. Before hydration there is no Svelte code running on the island, so the click hits server-rendered DOM with no handlers and nothing happens (the state does not exist yet). The click is not queued or replayed; after hydration the counter starts from the props’ initial value.

## Chapter 2: Project Anatomy and the .astro Language

1.  `src/pages` is the only reserved directory. Reserved filenames include `src/content.config.ts`, `src/live.config.ts`, `src/middleware.ts`, `src/fetch.ts` (reserved in 7.0) and `src/actions/index.ts`. Everything else (`components`, `layouts`, `styles`, `lib`) is convention.

2.  Right: files whose URL must be stable and that need no processing, such as `robots.txt`, a verification file, a PDF, or a third-party script loaded with `is:inline`. Wrong: your own CSS or JavaScript, which would miss bundling, fingerprinting and optimization; put it in `src/`.

3.  `<p style="color:red" data-y="true">z</p>`. The style object becomes inline CSS, `undefined` omits `data-x`, `false` omits `hidden`, and `true` on a `data-*` attribute renders the string `"true"`.

4.  Astro template attributes are rendered as strings; a function never reaches the browser, so the handler is not attached. Either add a `<script>` that does `document.querySelector(...).addEventListener('click', ...)` (or use a custom element), or make the button part of a Svelte island with a `client:*` directive and an `onclick` handler.

5.  `false` omits the attribute altogether, so `[data-active="false"]` never matches. Write `data-active={String(isActive)}` (or a ternary yielding the string) to emit `"false"`.

6.  `<head><title>…</title><meta name="robots" content="noindex"></head>`. Each intermediate layout must forward the slot with `<slot name="head" slot="head" />` inside the nested component, and the page must put `slot="head"` on the element.

7.  Fallback content renders only when no matching slot content is passed. If an element with the slot name is passed (even if it is empty), the slot is considered provided and the fallback is suppressed. An expression that evaluates to nothing, like `{}`, passes no node, so the fallback is shown.

8.  ```html
    ---
    // src/components/Callout.astro
    ---
    <div class="callout">
      <slot />
      {Astro.slots.has('footer') && <footer><slot name="footer" /></footer>}
    </div>
    ```

9.  It returns a `Promise<string>` of the slot’s rendered HTML, calling any function children with the given arguments (here `[message]`). Function children are invoked on the server while Astro renders, which only works between Astro components. A hydrated Svelte component receives children as static HTML strings, never functions.

10. `set:html` inserts the string unescaped, so a comment containing `<script>` or an `onerror` attribute would execute (XSS). Mitigate by sanitizing with a trusted HTML sanitizer before injection, or by rendering as text with `{userComment}` or `set:text`; also avoid accepting HTML at all, and use CSP as defense in depth.

11. (b). `define:vars` on a `<script>` implies `is:inline`; it is not bundled or deduplicated.

12. An inline script is emitted once per instance, so 40 copies appear in the HTML, and it loses bundling and TypeScript. Put values in `data-*` attributes (or a custom element) and use one bundled `<script>` that reads them via `dataset`.

13. A lowercase variable is rendered as a literal `<tag>` element, not as the variable’s value. Hydration directives such as `client:load` do not work on dynamic tags, because the bundler cannot know statically which component to ship; import the component directly in the template instead.

14. The glob pattern is a template literal containing a variable. Patterns must be static string literals starting with `./`, `../` or `/`. Use a literal pattern (for example `'../content/**/*.md'`) and filter by key, or use a content collection.

15. A string literal (no variables), starting with `./`, `../` or `/`, and valid picomatch glob syntax; results are keyed by path (lazy loaders unless `eager: true`). `import.meta.glob()` replaced `Astro.glob()`, which was removed in 6.0.

16. `getCollection` provides schema validation (Zod) and typed data, references between collections, loaders (remote data), `render()`, and incremental/cached updates; a glob provides none of that and `eager: true` bundles all matches. Any two of these are acceptable.

17. In `tsconfig.json` `compilerOptions.paths`; Astro and Vite pick it up and the dev server restarts. There is no built-in `$lib` alias in Astro; you define your own.

18. (a) and (b). `astro check` does not check `.svelte` files, so (c) and (d) require `svelte-check`.

19. ```json
    {
      "scripts": {
        "build": "astro check && svelte-check --tsconfig ./tsconfig.json && astro build"
      }
    }
    ```

    The `&&` chain stops the build on the first failure.

20. With `verbatimModuleSyntax` TypeScript requires `import type` for type-only imports, which avoids Astro’s bundler treating a type as a runtime import. Violation: `import { CollectionEntry } from 'astro:content';` (should be `import type`).

21. Look upward for the last element or component tag that was opened and never closed. The parser fails where it runs out of input, so the reported location is the end of the file, not the position of the missing closing tag.

22. Per the upgrade guide, (b) fails: the unclosed `<li>` is an unclosed non-void tag. (a) and (c) compile with no error and are emitted unchanged, but the browser reparses them into a different DOM (the `<p>` closes early; the `<div>` is foster-parented out of the table). (d) compiles and is identical, since `<br>` is a void element.

23. A layout is an Astro component, and hydrating an Astro component with `client:*` is an error because it has no client runtime. Place Svelte islands (cart badge, language switcher) inside the layout’s template and give those islands the directives.

24. A `Base.astro` layout holds the shared `<head>` (charset, viewport, generator, title, description, canonical via `new URL(Astro.url.pathname, Astro.site)`, an `SEO` component) and exposes `<slot name="head" />` plus a default slot; a page injects `<link slot="head" rel="preload" …>` and a `<script slot="head" type="application/ld+json" set:html={JSON.stringify(data)} />`. `site` must be set in `astro.config.mjs` so `Astro.site` is defined.

25. A route that does `export const partial = true`. It renders without `<!DOCTYPE html>`, `<head>`, or hoisted scoped styles and bundled scripts. The export must be statically identifiable: the literal `true` or an `import.meta.env.X` expression. `.md` pages cannot be partials.

26. `500.astro` is used only for on-demand rendered routes (it is not available for prerendered pages) and receives an `error` prop of type `unknown`. Avoid rendering `error.stack` or raw messages, which leak server code structure; show generic content or evaluate the error first.

## Chapter 3: Svelte 5 Islands in Depth

1.  The `astro.config.mjs` value (`runes: true`) wins. The editor and `svelte-check` read only `svelte.config.js`, so they analyze the component under `runes: false` while the build uses `true`; keep each option in one place.
2.  Without `svelte.config.js` no preprocessor is configured (not added by default since integration 6.0.0), so the SCSS block is not processed and the build fails or the styles are broken. Fix: create `svelte.config.js` with `preprocess: vitePreprocess()` imported from `@astrojs/svelte` (and install `sass`).
3.  (1) Server render: renderer `check` + `renderToStaticMarkup`; (2) wrap in `<astro-island>` with `component-url`, `renderer-url`, `props`, `client`, `opts`; (3) the directive script (`Astro.load/idle/...`) decides when to start; (4) the island imports component and renderer, parses `props`, collects `<astro-slot>`/templates, hydrates, removes `ssr`, dispatches `astro:hydrate`.
4.  During streaming the island’s children may still be arriving; `await-children` makes it wait until the `<!--astro:end-->` comment (or DOMContentLoaded/interactive state) before starting, so hydration never sees partial markup.
5.  Outer first, then inner. `hydrate` looks for a parent `astro-island[ssr]` and, if found, waits for that parent’s `astro:hydrate` event once.
6.  Never, in practice. `client:visible` observes the island’s element children; with `open = false` it renders only comment nodes, so there is nothing to observe. Give it a real root element.
7.  Create an integration whose `astro:config:setup` hook calls `addClientDirective({ name: 'hover', entrypoint: './directives/hover.js' })`; `hover.js` default-exports `(load, opts, el) => el.addEventListener('pointerenter', async () => { (await load())() }, { once: true })`. Type it by augmenting `AstroClientDirectives` in module `'astro'` with `'client:hover'?: boolean`.
8.  (a) a `Date`; (b) a `RegExp` `/ab/` with flags lost; (c) `null`; (d) a `Map`; (e) a plain object with the own enumerable properties, no prototype or methods.
9.  Functions are not serializable: the serializer emits `null` without error, so the server render (which received the real function) works but the client gets `null`. Alternatives: dispatch a `CustomEvent`/use a shared rune module; or move the logic into the island and pass only data.
10. `Cyclic reference detected while serializing props…`. For a prerendered page the build fails; for an on-demand page the request fails with a 500 at render time.
11. The whole payload is embedded in the HTML `props` attribute regardless of when the island hydrates, bloating every response and leaking data. Pass an id and fetch lazily or pass only the fields the island shows.
12. Supported: (a), (c), (e). Not: (b) Float32Array, (d) Symbol, (f) Promise.
13. ```html
    <script lang="ts">
      import type { Snippet } from 'svelte';
      let { children, footer }: { children?: Snippet; footer?: Snippet } = $props();
    </script>

    <div>{@render children?.()}</div>
    {#if footer}<footer>{@render footer()}</footer>{/if}
    ```

    An absent slot leaves the `footer` prop `undefined`, so `{#if footer}` is false.
14. Both receive it. `slot="my-slot"` is preserved as the key `'my-slot'`, so `<slot name="my-slot" />` and `{ 'my-slot': mySlot }` match. `slot="mySlot"` provides key `mySlot`, which matches neither (it would match `let { mySlot } = $props()`).
15. The slot is static HTML rendered on the server; there is no function to call with `item`. Workaround: wrap the generic component in a Svelte component that supplies the snippet, import that wrapper, or pass data and render inside Svelte.
16. `$props.id()` may only be used as the initializer of a top-level declaration (`const uid = $props.id();`). Here it is called inside a template literal and inline in the template, and both placements are `props_id_invalid_placement` compile errors (two calls would also yield two different ids, so `id` and `label` would not match). Fix: declare `const uid = $props.id();` once and use `uid` in both places.

17. It is visible until the island mounts, then removed. For `client:only` the client entrypoint empties `innerHTML` and calls `mount()`, not `hydrate()`, because there is no server-rendered markup to hydrate.
18. With `client:only` the component is never run on the server, so Astro cannot detect which renderer owns it via `check`; the hint selects the renderer. `client:load` renders on the server and `check` identifies it.
19. The server render executes the script top level where `localStorage` is undefined, so it throws `ReferenceError` and the build/request fails. Fixes: read it in `onMount`/`$effect`; or use `client:only="svelte"`; or guard with `typeof localStorage !== 'undefined'`.
20. On the server the module is a process-wide singleton, so state set during one request is visible to later requests (cross-request leakage of one visitor’s data). In the browser each page load is a fresh module, and both islands share one instance, which is the desired sharing.
21. Set `compilerOptions: { experimental: { async: true } }` in `svelte.config.js` (so editor and build agree). The integration (7.2+) awaits Svelte’s `render()` from `svelte/server`, so async work completes before the HTML is returned.
22. `.astro` imports `.svelte`; the reverse is impossible. Hydrating an Astro component with `client:*` is an error. Astro markup enters an island through slots, and Astro-computed values enter as serializable props.
23. Render `<Image>` in the `.astro` page and pass it as a slot, or call `getImage()` in frontmatter and pass `src`/`width`/`height`/`srcset` as props. `<Image>` and `getImage()` are Astro server features (`getImage()` throws in the browser).
24. It checks the function’s source string for `$$renderer` or `$$payload`. This is a heuristic that relies on the SSR build not being minified; with `client:only` the component is never server compiled/checked, so the framework name is required.
25. A new `setProps` call assigns the new props into the `$state` proxy that was passed to `hydrate()`/`mount()` and deletes keys no longer present; Svelte’s reactivity updates the running component without remounting.
26. It is dispatched on the island root when the island is removed from the document (e.g. client-router swap). The renderer calls Svelte `unmount()` through `component.destroy()`. Snippet: `document.querySelector('astro-island[component-url*="Cart"]')?.addEventListener('astro:unmount', () => console.log('removed'), { once: true })`.
27. (b).
28. Map: the library touches `window`, so use `client:only="svelte"` with a fallback sized like the map. Because it is below the fold, you can defer the cost further with a small `client:visible` wrapper that imports the map library dynamically in `onMount`. Either way it costs the map’s JavaScript, and search engines and no-JS users see only the fallback. Search box: `client:load`, because it must work immediately; it costs its JavaScript, but the server-rendered input is still in the HTML. Recently viewed: a server island (`server:defer`) with a fallback: personalized server HTML with no framework JavaScript, deferred so the rest of the page can stay cacheable. A `client:visible` island that fetches the data would also work, but it costs JavaScript and shows nothing without JS.


## Chapter 4: State, Events and Scripts Across Islands

1.  (1) A shared module instance (or global channel) in the browser; (2) late subscribers must see current state; (3) server-render consistency with the first client render. Plain `CustomEvent`s fail (2): an event dispatched before a listener hydrates is lost.

2.  Islands have no common component tree, so Svelte context (which requires an ancestor) cannot span them. Nano Stores are plain modules that work across frameworks and `.astro` scripts.

3.  ```html
    <script lang="ts">
      import { fromStore } from 'svelte/store';
      import { isOpen } from '../store';
      const open = fromStore(isOpen);
    </script>
    <button onclick={() => isOpen.set(!open.current)}>Toggle</button>
    ```

4.  (a) Writes from frontmatter or non-hydrated components change only the server’s module instance, not the browser’s. (b) A store cannot be a prop because it is not serializable. (c) `.astro` frontmatter cannot subscribe because Astro components render once and never re-render.

5.  It increments a module-level `$state` during render. In a Node server the module is evaluated once per process, so the counter accumulates across requests (1, 2, 3, …) and shows other visitors’ effects.

6.  A static build renders each page once at build time in a fresh process, so the accumulated state is never observed; it appears only when the route is rendered on demand repeatedly.

7.  (a) Move the write into an event handler or `onMount` (client only); (b) make state per-component or per-render with `$state` local to the component or a factory/`setContext`; (c) pass the value from the server as a prop (e.g. from `Astro.locals`/session) instead of a module singleton.

8.  Svelte forbids exporting state that is reassigned, because importers hold a binding they cannot update. Alternatives: export a `$state` object and mutate its properties, or export a class instance with `$state` fields, or getter/setter functions.

9.  ```ts
    class Counter {
      n = $state(0);
      double = $derived(this.n * 2);
      increment() { this.n++; }
    }
    export const counter = new Counter();
    ```

    A class allows reactive fields, derived values and methods behind one exported, never-reassigned binding.

10. When creating effects outside a component (module level), since there is no component lifecycle to own them. `$effect.root(fn)` returns a cleanup function; the caller must invoke it to dispose of the effects.

11. (b).

12. The event is lost; the badge never counts it. Make state the source of truth (a rune module/store that the badge reads on hydration), or hydrate the listener island earlier (`client:load`) and use events only for reactions.

13. Event listeners must run in the browser only (`onMount` does not run on the server), and removing them avoids leaks. Islands are created and destroyed repeatedly under client-router navigation and when conditionally rendered (`{#if}`), or when a slot is removed.

14. Augment `WindowEventMap` in `src/env.d.ts`: `interface WindowEventMap { 'cart:add': CustomEvent<{ sku: string }> }`.

15. It does not deliver to the same channel object that posted (only to other channel objects/contexts of the same origin). Prefer the `storage` event when the data is already in `localStorage`. Echo: tab B applies a received value, its effect posts it back, tab A applies and re-posts, ping-ponging; guard with version numbers or equality checks.

16. Problems: the script runs once per page, so it must bind all instances; and it may run before framework-rendered elements are hydrated/exist or miss later insertions. Fix: a custom element (`connectedCallback` per instance) or event delegation on a stable ancestor.

17. ```ts
    class Tabs extends HTMLElement {
      #abort?: AbortController;

      connectedCallback() {
        this.#abort = new AbortController();
        const { signal } = this.#abort;
        this.querySelectorAll('button').forEach((b) =>
          b.addEventListener('click', () => this.select(b), { signal })
        );
      }

      disconnectedCallback() {
        this.#abort?.abort();
      }

      select(b: Element) {}
    }

    if (!customElements.get('x-tabs')) customElements.define('x-tabs', Tabs);
    ```

18. `define` throws if the name is already registered, which can happen if the script is evaluated twice or bundled twice.

19. Once: bundled module scripts execute only the first time. Use `astro:page-load`, which fires on initial load and after each navigation. `data-astro-rerun` applies to inline scripts (`is:inline`) to re-execute them each navigation.

20. The internal `$state` is kept. By default `title` is updated to the new page’s value (the renderer’s `setProps` updates the running component). With `transition:persist-props` the old props are kept too.

21. On the island’s root element when it is removed from the document; the Svelte renderer listens and calls `unmount()`. `onMount` cleanups run as part of that teardown.

22. No. Module state survives client-router navigations because the page is not reloaded; the badge remounts and reads the current count. Persist is needed for component-internal state (open dropdown, video, form draft) that is not in a module.

23. Render the same initial value on both (the server’s prop) and apply stored state in `onMount`; or render the storage-dependent part with `client:only`; or use a `ready` flag showing a placeholder until mounted.

24. Wait until the `<astro-island>` no longer has the `ssr` attribute (e.g. `expect(island).not.toHaveAttribute('ssr', '')`). Otherwise the click hits the inert server-rendered button before hydration and does nothing.

25. Build and start the server, request the same on-demand page twice (or many times) and assert the responses are identical (e.g. `expect(b).toBe(a)`); a module-level counter would make them differ.

26. Use Nano Stores (or a plain shared module with listener API) so both the Svelte island and the `.astro` `<script>` can read and subscribe. Initialize from server data (prop or `data-*`) in `onMount`/an init function, not at module load. The header script subscribes once at module level (state survives navigations) and updates the element on `astro:page-load` because the swapped-in header DOM is new each navigation (or mark the header `transition:persist`).

## Chapter 5: Routing and Advanced Routing (`src/fetch.ts`, `astro/fetch`, Hono)

1.  Files and directories whose names start with `_` (for example `_components/`, `_utils.ts`). Use them to colocate components, tests and helpers with pages, and to temporarily disable a page.
2.  `src/pages/docs/[...slug].astro` with `export function getStaticPaths() { return [{ params: { slug: undefined } }, { params: { slug: 'a/b' } }]; }`. `undefined` matches `/docs`.
3.  Param values must be strings (or `undefined` for rest params) since 6.0; numbers fail with `GetStaticPathsInvalidRouteParam`. Fix: `id: '1'`, `id: '2'`.
4.  On-demand dynamic routes must not use `getStaticPaths` (it is for prerendered routes) and cannot receive props. Read `Astro.params.id` and fetch the data in the frontmatter.
5.  `/[...locale]/[files]/[slug]` (the original dynamic definition; the docs show it without the leading slash, 7.4 printed it with one). It is more useful than `params` when generating params generically for many segments, because `params` are only the explicit values of one page.
6.  `[...page].astro`: `/blog`, `/blog/2`, `/blog/3` (`dist/blog/index.html`, `blog/2/index.html`, `blog/3/index.html`). `[page].astro`: `/blog/1`, `/blog/2`, `/blog/3`.
7.  `format` is a function that transforms each computed URL before it is rendered, for example ``(url) => `${url}.html` ``. It was added in 7.1.0.
8.  `/posts/create` -\> `posts/create.astro`; `/posts/7` -\> `posts/[page].astro`; `/posts/a/b` -\> `posts/[...slug].astro`; `/about` and `/` -\> `[...slug].astro` (`/` with `slug` undefined).
9.  Both are the same pattern; the endpoint wins (“endpoints beat pages”). The build warns that a dynamic SSR route cannot be defined more than once and that a collision will become a hard error in a following version.
10. When a file-based route with the same pattern exists (for example `src/pages/old-page.astro`): file routes take precedence over configured redirects.
11. GET: 301; POST: 308. With `{ status: 302, ... }`: 302 for both.
12. As an HTML page with a meta refresh (supported adapters emit native host redirect config instead). `experimental.redirectPage` with `src/pages/3xx.astro`; props: `from`, `to`, `status`, `delay`.
13. On-demand rendering streams HTML; once output begins the status and headers cannot change, and child components render after the page has started. The redirect must be returned by the page (or middleware) before any output.
14. A rewrite renders the target’s content (here the 404 page) while the browser URL stays unchanged and status follows the rendered route (a 404 for `/404`). A redirect sends a Location response, the browser requests the new URL and the URL bar changes.
15. It contains whatever was thrown during rendering (page, middleware), typed `unknown`. It is used for on-demand rendered routes only. Do not display `error.stack` or detailed messages.
16. `build.format: 'file'`. `trailingSlash: 'always'` and `'never'` redirect non-conforming requests (`'ignore'` does not). Decide `trailingSlash`, `build.format` and `base` (and `site`) together with the host’s URL mapping.
17. Astro partially decodes pathnames during normalization, so `Astro.url.pathname` is the decoded/normalized path while `request.url` keeps the raw one. Security checks on the raw string can disagree with the route actually matched.
18. (b).
19. Rename the file (and fix imports), or set `fetchFile` to another filename. `fetchFile: null` disables advanced routing.
20. ```ts
    import { FetchState, astro } from 'astro/fetch';

    export default {
      async fetch(request: Request) {
        const state = new FetchState(request);
        const res = await astro(state);
        res.headers.set('x-request-id', crypto.randomUUID());
        return res;
      },
    };
    ```
21. Trailing-slash normalization, redirects, sessions, actions, user middleware, page rendering, i18n, with caching around rendering. Call `sessions(state)` before middleware, and `i18n(state, response)` after rendering.
22. RPC action: a `Response`. HTML form submission and non-action requests: `undefined` (so you continue to page rendering).
23. 7.4 added `notFound()` which renders the custom 404 (including a prerendered `404.astro`) when no route matches; it returns `undefined` for a matching route and an empty 400 response for an over-encoded path.
24. The guard is registered before `middleware()`, so Astro middleware has not run and `locals.user` is not set yet. Populate `locals` earlier (own Hono middleware) or move the check after `middleware()`/into Astro middleware or the page.
25. The router and the guard can disagree about the path. `/%64ash` and `//dash` reached the `/dash` page while the raw `startsWith('/dash')` check did not match.
26. Astro middleware (normalized path, matched route), inside the page/endpoint, in actions and data-access code (and a router guard as defence in depth). It can never apply to prerendered output served directly by the host, since no Astro code runs.
27. `state.provide()`, `state.resolve()`, `state.finalizeAll()` and `App.Providers` were removed from the public API; the handlers (`sessions()`, `cache()`, etc.) and `FetchState` properties like `locals` replace them.
28. Hono app: request-id/timing middleware first; rate limiter for `/_actions/*`; `trailingSlash()`, `redirects()`, `sessions()`, `actions()`, `middleware()`, `notFound()`, `pages()`, `i18n()`. Authorization for `/admin` belongs in Astro middleware (after sessions, using the matched route) and in the admin pages/actions themselves, with an optional Hono guard as an extra layer; test `//admin` and encoded variants.

## Chapter 6: Content Collections, Loaders and Data Fetching

1.  Any three of: build-time collections run at build/sync and persist to a data store while live collections run per request and persist nothing; loader contract differs (`load()` writing to a `DataStore` versus `loadCollection()`/`loadEntry()` returning data); query functions differ (`getCollection`/`getEntry` versus `getLiveCollection`/`getLiveEntry`); live queries return `{ entry|entries, error, cacheHint }` while build-time queries return values directly; live collections need an adapter and on-demand rendering; live collections cannot render MDX or optimize images.
2.  It prints `hello-world`: the default id is a `github-slugger` kebab-case slug, so case and spaces are lost. Keep the casing with `generateId: ({ entry }) => entry.replace(/\.md$/, '')` (or set `slug` in frontmatter).
3.  The order is non-deterministic and platform dependent. Sort explicitly, for example by `b.data.date.valueOf() - a.data.date.valueOf()`.
4.  `image` is not defined. Image fields require the function form of the schema, `schema: ({ image }) => z.object({ cover: image(), ... })`, because `image()` comes from `SchemaContext`.
5.  (b). In Zod 4 `.default()` must match the output type (so `'[]'` and `null` are wrong), and `.prefault([])` supplies a pre-parse default. (c) does not give an empty array.
6.  Only that the value is a string (transformed into `{ collection, id }`). Existence is checked when you call `getEntry()` or `getEntries()`; a dangling reference yields `undefined` (in an array from `getEntries()`).
7.  Every entry has an undefined digest, so `cacheKey` is the string `'undefined'` for every page and never changes. Incremental builds then skip those pages whenever their code is unchanged, even when their content changed, so content updates are never rendered: the pages are frozen. Loaders must set a digest, for example with `generateDigest(data)`.

8.  It returns `false` (and does not update the entry). That lets loaders re-set every item cheaply and detect which entries actually changed.
9.  `schema` is a static Zod schema. `createSchema()` is an async function that builds the schema at build time and returns `{ schema, types }`. The `types` string is written to a TypeScript file and must export an `Entry` type or interface. `createSchema()` replaced function-valued `schema` in 6.0.
10. The user’s collection-level schema. A schema defined in `content.config.ts` overrides the loader’s `schema`/`createSchema()`, which lets users extend or transform your shape.
11. The entries are stored unvalidated and untransformed: no coercion (for example dates stay strings) and no type guarantees. `parseData()` is the opt-in validation step.
12. `rendered: await renderMarkdown(item.body)` (optionally with `body: item.body`). Assigning a `RenderedContent` object to `rendered` makes `render(entry)` return a working `<Content />`.
13. In `node_modules/.astro/data-store.json` (the default `cacheDir`; the experimental flag docs describe it as `.astro/data-store.json`). `'chunked'` splits it across files under `.astro/data-store/`, starting a new chunk above 20 MB by default or a custom `chunkSize`, useful for hosts with per-asset size limits.
14. For very large Markdown collections where eagerly rendered HTML in the store exhausts memory. You give up cross-build caching of rendered HTML, because rendering happens when pages call `render()`. It does not apply to MDX, Markdoc or data entries.
15. It is disabled when `build.concurrency > 1`; pages with server islands re-render every build unless `ASTRO_KEY` is pinned (the embedded props key is regenerated per build); middleware changes do not invalidate cached pages (use `astro build --force`).
16. The incremental cache (build manifest and reusable output) is stored in `cacheDir`, `node_modules/.astro/` by default. If it is missing, every page re-renders, so nothing is skipped. The output directory is emptied each build and skipped pages are restored from `cacheDir`.
17. `LiveEntryNotFoundError` is not exported from `astro:content`; the build fails. Import it from `astro/content/runtime`: `import { LiveEntryNotFoundError } from 'astro/content/runtime';`. Also the page needs `export const prerender = false` unless `output: 'server'`, and it should check `error`.
18. A `LiveEntryNotFoundError` in the returned `error` field.
19. Tags accumulate: `['all', 'a', 'b']` (order not significant) and `lastModified` is the most recent of the collection and entry values, `D2`.
20. False. Cache hints are advisory data. You must pass them to `Astro.cache.set(cacheHint)` (with a configured provider) or turn them into headers yourself.
21. MDX needs a compile step that cannot run at request time in the live path, and image optimization is a build pipeline concern. Live loaders return data and optional pre-rendered HTML only.
22. (c). It must be fresh within seconds, shared across users and invalidatable by tags, which is live collection plus route caching.
23. (b). Infrequent publishes and static HTML fit a build-time loader that is re-run on a rebuild webhook.
24. The part of the document before the slow expression is streamed first, then the slow part after about 600 ms, with later siblings held behind it because rendering is in document order. Avoid blocking by moving the slow, non-critical fragment into a server island (`server:defer`), or by starting the fetch early (not awaiting) and awaiting late, or by caching.
25. Props to a hydrated island are serialized into the HTML (the `props` attribute of `astro-island`), so the secret is exposed to every visitor. Keep secrets on the server, and give the island only data it may publish, or route calls through an endpoint.
26. `astro:env/server` secrets are validated whenever the module is imported unless `validateSecrets` is disabled; CI therefore needs values. Provide dummy/placeholder values in the CI environment, or disable `validateSecrets` (and validate at runtime).
27. Add `loader: glob({ pattern: '**/*.{md,mdx}', base: './src/content/<name>' })` to each collection and drop `type`; replace `entry.slug` with `entry.id`; replace `entry.render()` with `render(entry)` imported from `astro:content`; re-check ids because loader ids are slugified rather than path-based; finally remove the flag.
28. In order: (1) `glob({ deferRender: true })` so rendered HTML is not held in the store (loses rendered-HTML caching across builds); (2) if you did not use (1), `retainBody: false` when the raw bodies are not needed (smaller store, `entry.body` undefined; it does not combine with `deferRender`, which renders from the body); (3) `experimental.collectionStorage: 'chunked'` if store size is the problem (experimental); (4) `experimental.incrementalBuild` with `cacheKey: entry.digest` to skip unchanged pages (experimental, needs `build.concurrency` 1 and CI cache restore); (5) split the collection or raise the Node heap as a last resort.

## Chapter 7: Markdown and MDX

1.  Sätteri is the default (no install needed). To use unified you install `@astrojs/markdown-remark` and set `markdown.processor: unified()`. (Installing `@astrojs/markdown-satteri` is optional, for configuring Sätteri.)

2.  ```js
    import { unified } from '@astrojs/markdown-remark';
    export default defineConfig({
      markdown: { processor: unified({ remarkPlugins: [remarkToc], smartypants: false }) },
    });
    ```

    The old top-level options are deprecated; they still work but require `@astrojs/markdown-remark`.

3.  `satteri({ features: { smartPunctuation: false, gfm: false } })`.

4.  No. The typed options (`mdastPlugins`, `hastPlugins`, `features`) and the Markdown guide use `features: { smartPunctuation: ... }`; the top-level form in the reference page is wrong. Write `satteri({ features: { smartPunctuation: false } })`, which was verified to leave straight quotes and `--` untouched.

5.  Serialization differences (whitespace and newlines between elements, `&#x3C;` versus `&lt;` entity forms, boolean attributes such as `data-footnote-ref` versus `data-footnote-ref=""`) and typography differences such as the dash character. Regenerate snapshots or assert on the DOM instead of strings.

6.  Sätteri renders `--` as an en dash (`–`), unified as an em dash (`—`).

7.  `id="whats-picture-"` with a trailing hyphen. In Astro 5 trailing hyphens were stripped; Astro 6 made GitHub-compatible ids the default, so links must now be `#whats-picture-`.

8.  The plugin’s ids. Astro injects ids after your custom plugins, so an id already present is preserved and is what `headings` reports.

9.  Before that plugin: `satteriHeadingIdsPlugin()` first in `hastPlugins`, or `rehypeHeadingIds` first in `rehypePlugins`.

10. In `remarkPluginFrontmatter` from `render(entry)`. The schema validates the loader’s parsed frontmatter into `entry.data` before plugins run, so plugin-injected values are not in `entry.data`.

11. Sätteri has its own plugin model: objects built with `defineMdastPlugin`/`defineHastPlugin` with node visitors receiving `(node, ctx)` and data under `ctx.data.astro`. Unified transformers are `(tree, file) => void` functions over a different tree implementation and API.

12. `'shiki'`, `'prism'`, `false`, or an object `{ type: 'shiki' | 'prism', excludeLangs?: string[] }` (default `{ type: 'shiki', excludeLangs: ['math'] }`). `excludeLangs` lists fence languages that are left unhighlighted, so client-side renderers can handle them.

13. (b). `<Code />` does not inherit `shikiConfig`; it uses its own props. It is built in (`astro:components`), works in `.astro` and `.mdx`.

14. `.astro-code` and `.astro-code span` (not `.shiki`), inside a `prefers-color-scheme: dark` media query or a class-based selector.

15. Shiki emits inline styles, which Astro’s CSP support does not accommodate; the docs list Shiki as unsupported with CSP. Use Prism with an external stylesheet.

16. (b). A directive on a component imported in the MDX source hydrates an island, verified to emit `astro-island` with the Svelte renderer and props.

17. It renders statically as server HTML only (for example `<button>n=0</button>`); it receives none of the heading’s children and never hydrates. No, `client:*` cannot be applied to components supplied through `components`.

18. The component must render `<slot />` for children and should forward props: `<blockquote {...props}><slot /></blockquote>`. Without `<slot />` the content is dropped.

19. `recmaPlugins`. They modify the ESTree output of MDX and only work with the unified processor; the standalone `mdx({ recmaPlugins })` option is deprecated in favor of `unified({ recmaPlugins })`.

20. MDX ignores the `markdown` configuration entirely and uses only its own options (and the default processor).

21. `optimize` enables an internal rehype plugin that converts static MDX output to strings for faster builds. It breaks dynamically rendered replacements (components passed via the `components` prop), so list those element names in `optimize.ignoreElementNames`; components from `export const components` are auto-detected.

22. If the MDX integration is not installed the loader cannot handle `.mdx`; it logs `[WARN] [glob-loader] No entry type found for <file>.mdx` and produces no entry for it.

23. Not as documented: collection entries expose `render()`’s `Content`, `headings`, `remarkPluginFrontmatter` (put needed values in frontmatter). Via a direct `import` or `import.meta.glob`, any exported value is available as a named export.

24. `markdown.syntaxHighlight: { type: 'shiki', excludeLangs: ['math', 'mermaid'] }`.

25. `compiledContent()` returns (async) the document compiled to an HTML string; `rawContent()` returns the raw Markdown string; `getHeadings()` returns (async) `{ depth, slug, text }[]`.

26. Astro no longer adds `<meta charset="utf-8">` for pages using the frontmatter `layout` property; you must include it in the layout.

27. Keep behaviour first: install `@astrojs/markdown-remark`, move the plugins and `smartypants` into `unified()`, and run the build and snapshot tests. Because `remark-math` and `rehype-katex` are ecosystem plugins, stay on unified for those; port the two small custom plugins to Sätteri only if you later want it. Optionally split: Sätteri for `.md` without math and unified in `mdx({ processor })` or the reverse. Recheck heading anchors, dash typography and regenerate golden files.

28. The poll is a Svelte island imported in the MDX source with a directive (for example `<Poll client:visible ... />`); it needs hydration. The anchor-and-copy-link `h2` is an Astro component supplied via `components={{ h2: Heading }}` on `<Content />` (static, slot-based); a copy button inside it would need a small script or a custom element, not a Svelte island, because mapped components cannot hydrate.

## Chapter 8: On-Demand Rendering, Adapters and Deployment

1.  The page needs `export const prerender = false` (a literal), and an adapter must be installed and configured; otherwise the build fails because there is no runtime to render it.
2.  None in terms of features: `'server'` only flips the default so every route is on demand unless `prerender = true`. Both modes support the same on-demand features; static plus opt-outs keeps most pages as static files.
3.  `true`. Middleware runs at build time for prerendered pages (in classic mode) so that it can set `locals` and transform the output that is baked into the HTML; request-specific logic in it must therefore be guarded with `isPrerendered`.

4.  The build fails with `PrerenderClientAddressNotAvailable`: `clientAddress` is only available on demand.
5.  Correct: have the adapter/custom entrypoint map a trusted header (for example pass `clientAddress` to `app.render()` from the proxy’s header), or configure the proxy and trusted-header handling at the platform layer. Incorrect: reading a client-supplied `X-Forwarded-For` directly from `Astro.request.headers` without a trusted proxy that overwrites it.
6.  (c). Status and headers are page-level (plus middleware and endpoints); components and layouts run after headers may be sent.
7.  (a) chunked transfer: the early markup arrives first, the slow part and following siblings arrive after the delay. (b) one buffered response with a `content-length` after the delay.
8.  Setting status in the template is too late: components render while streaming, headers may already be sent. Set `Astro.response.status = 404` (or return a `Response`) in the frontmatter before any output.
9.  Astro uses the exact method handler first, then `ALL`, and only falls back to `GET` for `HEAD` when neither exists. With `ALL` defined, `HEAD` hits `ALL`.
10. Multiple cookies would be folded into one comma-joined header; the generator yields each `Set-Cookie` value so each is appended as a separate header. (Alternatively use `addCookieHeader: true`.)
11. `addCookieHeader`, `clientAddress`, `locals`, `prerenderedErrorPageFetch`, `waitUntil`, `routeData`. `waitUntil` is for background work.
12. ```ts
    const route = app.match(request);
    if (!route) return new Response('Custom 404', { status: 404 });
    return app.render(request, { routeData: route });
    ```
13. Standalone starts a server and serves static files; middleware mode does not serve files. In Express you mount the exported `handler` from `dist/server/entry.mjs` (and serve `dist/client` yourself).
14. `HOST=0.0.0.0` (the default listens on localhost); usually with `PORT`.
15. Neither Astro nor the adapter loads `.env` at runtime. Provide variables via the process environment: inline, Docker `ENV`/orchestrator secrets, or a loader such as `dotenvx`.
16. `prerenderEnvironment: 'node'`. It does not affect on-demand pages, which always run in `workerd`.
17. `import { env } from 'cloudflare:workers'` (or `astro:env/server`).
18. Middleware is bundled into the ISR function and only runs on a miss or regeneration. Set `middlewareMode: 'edge'` or exclude the routes from ISR, or set the header at the CDN.
19. `locals` is serialized as JSON and sent in a header to the function that renders. The function refuses requests not coming from the generated edge function with 403.
20. The static `docs.astro` wins; a warning is logged and the `[page]` path is skipped. Set `prerenderConflictBehavior: 'error'` in CI.
21. Props are encrypted with a per-build key. Instances or cached HTML from different builds use different keys, so decryption fails. Fix with a stable `ASTRO_KEY` from `astro create-key`.
22. Build. The key is embedded in the bundle at build time (and encrypts props in rendered HTML); runtime uses the embedded key.
23. (b).
24. `astro preview --background`, run tests against the URL, then `astro preview stop` (`status`/`logs` available).
25. Hashed assets (immutable), the page’s `s-maxage` in a CDN/shared cache, and the island’s own GET response caching. Over about 2048 bytes of URL the island uses POST, which breaks island caching.
26. The header is client-controlled; unless a trusted proxy overwrites it, an attacker can set arbitrary values to evade limits or impersonate IPs.
27. `output: 'static'`, `prerender = false` on dashboard routes and endpoints, Cloudflare adapter (workerd preview), sessions on the default KV (or `session: false` if unused); pitfalls: KV eventual consistency across regions, `_headers`/`_redirects` not applying to Worker responses, `prerenderEnvironment` for Node-only prerender deps, `nodejs_compat` flag.
28. Stable `ASTRO_KEY` set at build for all pods; shared session driver (not filesystem); keep previous hashed assets available during the rollout; make `/_actions` and island endpoints backward compatible for a release; CDN rules short-lived for HTML or purge on deploy; readiness probes before traffic shift.

## Chapter 9: Server Islands

1.  An adapter and an Astro component. On a Svelte component the directive is silently ignored (verified on 7.4.1): the component renders inline as plain server HTML, with no deferral, fallback or hydration. Wrap it in an Astro component and defer that.
2.  The page ships with the fallback and a module script; the script fetches `/_server-islands/<Name>` with encrypted query parameters (`e` component export, `p` props, `s` slots), and `replaceServerIsland()` swaps the returned HTML in for the fallback nodes.
3.  When the encoded URL would exceed 2048 bytes; the script POSTs the props as a JSON body. POST responses are not cached by browsers/CDNs, so island caching breaks.
4.  The fallback stays in both cases: the swap only happens for status 200 with `content-type` `text/html`.
5.  Props are not identity: the encrypted blob can be replayed by anyone with the page HTML, so any visitor can obtain that user’s private data. Also `Astro.locals.user` would be user-specific data on a shared page. Read the session cookie inside the island and verify it there.
6.  `/_server-islands/<Name>`. Read the `Referer` header (parse the URL’s search params), or pass what you need as props from the page (query strings are unavailable at build time for prerendered pages).
7.  It can be absent or trimmed (privacy settings, `Referrer-Policy: no-referrer`, origin-only policies), and it is client-controlled so it must not drive security decisions.
8.  Middleware sees the island path `/_server-islands/...`, not `/account/orders`, so the pathname gate does not apply. Fix: have the island verify the session itself (and/or apply auth middleware to `/_server-islands/*`).
9.  Pages rendered by build N encrypt props with key N, but requests land on build N+1 with a different key (or CDN-cached HTML has an old key); decryption fails with 400 (`Encrypted componentExport value is invalid`) and the fallback remains. Diagnose by requesting the island URL and checking for 400s. Fix with a stable `ASTRO_KEY` from `astro create-key` set at build.
10. Build (it is embedded in the bundle and used to encrypt/decrypt). Rotation invalidates cached HTML embedding old ciphertext (and incremental-build caches), so purge the CDN with the rotation.
11. (a), (d). Functions, class instances and circular objects are not serializable.
12. (b).
13. The swap replaces the fallback nodes with the island HTML; differing size shifts surrounding content (layout shift). Reserve space with fixed dimensions.
14. The fallback is part of the shared, cacheable page shell, so it must not be user-specific. It would also bake or leak one user’s data into a cached page.
15. After the swap, when the fragment executes in the browser; `client:visible` observes the newly inserted element. The hydration bootstrap (`astro-island` definition and `Astro.load`) is inlined in the island’s HTML response.
16. Set headers inside the island component’s frontmatter (`Astro.response.headers.set('Cache-Control', ...)`); they apply to the island response only (verified).
17. Pass fewer/smaller props (an id or a query key and let the island load the list), or fetch the data inside the island, or pass a short hash/cache key and look it up server-side.
18. The request body size of POST island requests; default 1 MB.
19. Each island is a separate request with its own bootstrap script and render, which adds load and bytes. Reduce by merging into fewer islands, deferring only what is truly dynamic, hydrating lazily (`client:visible`/`idle`) and caching island responses.
20. Pages with server islands embed a per-build key, so they are re-rendered every build and not reused from the incremental cache until a stable `ASTRO_KEY` is set.
21. Reserved routes (`_astro`, `_server-islands`, `_actions`) win priority over everything, so no page can shadow it.
22. The island script has `data-astro-rerun`, so it re-executes on each swap to a page containing the island. `transition:persist` keeps an island (and its state) across navigations.
23. (a) server island with a generic fallback (cacheable shell); (b) client fetch from a Svelte island (continuous interaction); (c) on-demand page (everything is dynamic, an island adds only a round trip); (d) server island (slow, non-critical fragment; page streams or caches without it).
24. Prerendered product page with `<Stock sku={sku} server:defer>` whose frontmatter calls `getLiveEntry('inventory', { sku })` and `Astro.cache.set(cacheHint)` plus `maxAge/swr`. The page shell is cached at the CDN; the island response is cached per its policy; invalidate with tags via `Astro.cache.invalidate` (route caching provider required).
25. It removes the fallback nodes between the start marker and the script and inserts the response HTML. If sizes differ, content below moves, causing layout shift.
26. The page author’s value is decrypted in the server render and the ciphertext is replayable; encryption stops tampering and casual reading, not misuse by anyone holding the page. Never treat it as a secret store.
27. Intercept the island route (`page.route('**/_server-islands/**', r => r.fulfill({ status: 500 }))`), load the page, and assert the fallback text remains visible and no island content appears.

## Chapter 10: Middleware and Endpoints

1.  A named export `onRequest` (not default). It must return a `Response`, either directly or by returning/awaiting `next()`.
2.  `a in, b in, c in`, then the page, then `c out, b out, a out`.
3.  At build time there is no real request, so the header is empty or absent. Logic keyed on it bakes a constant result into the static HTML; guard with `isPrerendered`.
4.  Incremental builds only track page data (`cacheKey`) and the page’s module graph; middleware changes do not invalidate cached pages. Run `astro build --force`.
5.  It throws `LocalsReassigned` (500). Mutate instead: `ctx.locals.user = user`.
6.  In `src/env.d.ts`: `declare namespace App { interface Locals { requestId: string; user: User | null } }`.
7.  `next('/who')` rewrites in place without re-running middleware (counter 1); `context.rewrite('/who')` starts a new render and re-runs middleware (counter 2).
8.  It creates a new `Request` from the old one, so reading the body before or after throws. Use `Astro.rewrite()` from the template instead.
9.  The path gate doesn’t cover `/_server-islands/*` or `/_actions/*`, which return account data without passing the `/account` check. Verify the session inside islands/actions (or populate `locals.user` and enforce in handlers). Also `has('sid')` checks presence, not validity.
10. Reading the body buffers the whole response, defeating streaming and delaying first byte.
11. Exact method export, then `ALL`, then `GET` (stripping the body) for `HEAD`, else 404. With `GET` and `ALL`, `HEAD` goes to `ALL`.
12. A 404 (with a logged warning that no handler exists for `PATCH`).
13. Handlers must return a `Response`; returning an object throws `EndpointDidNotReturnAResponse`. Use `Response.json({ ok: true })`.
14. (b).
15. `export const prerender = false`, with an adapter installed.
16. Return `props` from `getStaticPaths()` and read them from the context. On-demand endpoints are plain functions with no `getStaticPaths`, so props are not supported.
17. No: endpoints that explicitly return 404/500 skip rerouting to `404.astro`/`500.astro`. The body you return is what the client gets.
18. A `clientAddress` option from a trusted source; otherwise reading `ctx.clientAddress` throws.
19. (a) and (e). Date, functions and Map fail.
20. It is JSON-serialized into a header to the serverless function; the function rejects requests not coming from the generated edge function with 403.
21. Any three: `locals` must be JSON-serializable; restricted edge runtime (no Node built-ins/filesystem, bundle limits); no sessions in edge middleware; extra invocations (every ISR cache hit on Vercel); different execution rules for static content; changes not invalidating incremental builds.
22. The middleware is bundled into the ISR function, which only runs on a miss or regeneration. Set `middlewareMode: 'edge'` or exclude routes from ISR.
23. Prerendered pages are static files served by the host; middleware only ran at build. Make the route on demand (`prerender = false`) and enforce auth there, or use edge middleware on hosts that support it.
24. Build a context with `createContext({ request, defaultLocale: 'en', locals: {}, clientAddress })`, call `onRequest(ctx, async () => new Response('ok'))`, and assert on response headers and `ctx.locals`.
25. A plain endpoint (public HTTP API, non-JS partner clients), with CORS headers/OPTIONS for the partner origin and token auth for them; for the island same-origin cookie auth with SameSite and `checkOrigin`. Middleware populates `locals.user` from cookie or token; the endpoint enforces it and returns 401/403. (Actions suit the island-only case.)
26. A sequence handler that sets `locals.requestId`, awaits `next()` and sets headers on the returned response without reading the body; avoid `res.text()` and buffering, and don’t set headers from components.

## Chapter 11: Actions

1.  RPC: a `POST` to `/_actions/<name>` (dots for nesting), made by the generated `actions` client. Form: a `POST` to any on-demand page with `?_action=<name>`, produced by `<form method="POST" action={actions.x}>`. Both are public HTTP endpoints.
2.  `actions.cart.add(...)`; the RPC URL is `/_actions/cart.add`.
3.  An action returns data; navigation is the caller’s decision. In an island, redirect after success with `navigate()` (or a router, or `location`). In a form flow, redirect on the server in the page frontmatter (`Astro.redirect(url, 303)`) or in middleware using `getActionContext()`.
4.  `415 Unsupported Media Type`, error code `UNSUPPORTED_MEDIA_TYPE`, message “This action only accepts FormData.”
5.  `{ email: 'a@b.co', terms: false, tags: ['x', 'y'] }`. A missing checkbox/boolean field becomes `false` and repeated names go through `getAll` for the array.
6.  `null`, not `""`. Empty non-optional fields are converted to `null`, so `z.string()` reports “expected string, received null” rather than a min-length message; supply a custom `{ error }` message or make the field `.nullable()` and handle it.
7.  `address.city`. Astro builds nested objects from `parent.child` keys.
8.  `error.fields.address` (only the first path segment is used as key, so all nested issues are grouped there). The full path is in `error.issues[i].path`, e.g. `['address', 'city']`.
9.  (1) Top-level `await` on an action in a component’s script runs during SSR, where `actions.x()` called outside `Astro.callAction()` throws `ActionCalledFromServerError`; (2) even if it ran, a Svelte component script is not an async context unless experimental async is enabled, and issuing an RPC at render time couples render to the network. Fix: call actions inside event handlers or `$effect`, or fetch the data in the `.astro` parent (via `Astro.callAction()` or the data layer) and pass it as a prop.
10. `isInputError` narrows to `ActionInputError` (validation failure, with `fields` and `issues`). `isActionError` narrows to the general `ActionError` (anything produced by the handler or runtime, including input errors since they extend it). Input errors are the more specific case.
11. When another layer handles errors (a data-fetching library, `{#await}`/`{:catch}`) or while prototyping. `orThrow` carries no progressive-enhancement information, so it cannot back a no-JS form `action`.
12. It reads the result of `createProduct` for this request (`undefined` if that action was not submitted); on success it redirects to the new product page. The recommended status is `303 See Other` (the default is 302).
13. Because `getActionResult` is specific to the action passed: it compares that action’s query string with the stored payload name. If a different action was submitted, or no action, it returns `undefined`.
14. Calling `setActionResult()` records the result on the request’s locals, so Astro treats the action as already handled; `getActionContext()` afterwards returns `action: undefined`, and Astro’s own action execution is skipped for the request.
15. On the redirected `GET` the flash must be replayed so the page sees the result; that request is not an action request. If the flash check ran after the form branch it would still work for `GET`, but on a stale-flash edge (flash exists and a new form `POST` arrives) the new submission would run first and overwrite the pending flash. Reading first also guarantees one-shot semantics: delete then replay.
16. **b.** Only form-like (and missing) content types are checked; JSON is protected by browser CORS preflight (and the source marks this as a TODO for Astro 8).
17. `403` (“Cross-site POST form submissions are forbidden”). The handler does not run.
18. 1 MB (`1024 * 1024` bytes), configurable with `security.actionBodySizeLimit`; the error code is `CONTENT_TOO_LARGE` (413).
19. Actions are public endpoints at `/_actions/<name>`; anyone can POST to them directly with curl, bypassing the admin page. Authorization must be in the handler (and optionally duplicated in middleware).
20. **c.** Server-side calls must go through `Astro.callAction()` (or `context.callAction()`), otherwise `ActionCalledFromServerError` is thrown.
21. `500`, code `INTERNAL_SERVER_ERROR`, and the original message `db password rejected` (verified in 7.4.1), which leaks internals. Catch exceptions inside the handler, log with `ctx.logger`, and throw an `ActionError` with a safe message.
22. No. A webhook needs the raw body for HMAC verification, a specific status (202) and is a third-party contract. Actions parse and re-serialize bodies, use a devalue/JSON envelope and are not a documented public API. Use an endpoint.
23. Client: disable the control while pending and send an idempotency key (e.g. `crypto.randomUUID()` created when the form mounts). Server: store the key (or rely on a unique constraint) and return the previous result for a repeated key.
24. It returns the RPC URL (respecting `base` and `trailingSlash`). Uses: `fetch` with custom headers (e.g. `Authorization`) or `keepalive`; `navigator.sendBeacon` for analytics on page unload.
25. Form-mode actions need an on-demand page. On a prerendered page there is no server to process `?_action=...`; the static host handles the POST (usually 405/404) or ignores the query. Remove `prerender = true` for that page (or submit via an island using RPC).
26. In form mode the re-rendered page carries the action error’s status (400 for input errors, 409 for conflicts, and so on). To avoid it, use post/redirect/get in middleware so the final response is a `200` (or set `Astro.response.status` on the replay).
27. Check that a session driver is configured for the production adapter (only Node, Cloudflare and Netlify configure defaults; others need `session.driver`), that `session: false` is not set, that the route is not prerendered, that the driver’s storage is shared across instances (memory/LRU drivers are per process), and that the cookie is sent (the default cookie is `Secure`, so plain HTTP drops it in production). Chapter 12 covers each.
28. Without a router the re-rendered page clears inputs. With `<ClientRouter />` you can add `transition:persist` to the inputs so their values survive the swap after a failed submission.

## Chapter 12: Sessions and Route Caching

1.  Only the session ID (a v4 UUID) is in the cookie. The data lives server-side in the configured storage driver.
2.  Node (filesystem), Cloudflare (Workers KV, binding `SESSION`) and Netlify (Netlify Blobs). On Vercel (and other adapters) you must configure `session.driver` yourself, for example `sessionDrivers.redis(...)`.
3.  It writes files under `node_modules/.astro/sessions` inside the container: they disappear when the container is replaced and are not shared between replicas, so sessions get lost or differ per instance. Use a shared driver such as Redis.
4.  `cart.push(sku)` happens after `set()`. `set()` stores a serialized clone, so the push is not persisted. Mutate first, then call `session.set('cart', cart)`.
5.  `c` is `undefined`. The server log shows a warning that `Astro.session` was accessed but no session storage is configured.
6.  The runtime value is `undefined` (matching the type `AstroSession | undefined` and the API reference), while the changelog describes the property as always present on the context, with access logging a message. In the test, `String(Astro.session)` gave `undefined` and a `[WARN] [session]` line was logged on access.
7.  **c.** The cookie is set on the first `set()` (also `regenerate()` or `load()`); `get()` alone does not create one.
8.  To prevent session fixation: after authentication the identifier must change so an ID known before login is useless. `regenerate()` creates a new ID and preserves the existing data (the old ID is removed from storage).
9.  The driver config is evaluated at build time, so `process.env.REDIS_URL` is inlined with the build-time value; both environments use the same URL. Fix: move the driver into an entrypoint module (`session.driver: { entrypoint: new URL(...) }`) that reads runtime configuration (for example via `astro:env/server`).
10. Astro’s `ttl` stores an expiry timestamp per value and ignores expired values on load; it does not delete them until accessed. Redis’s `ttl` makes the server delete the key. Only the driver’s TTL frees storage.
11. It does not trust the ID: since the ID has no stored data, it generates a new server-side ID (and sets a new cookie when the session is written). Non-UUID values are never used as storage keys at all.
12. Both read the same cart and each writes a cart containing only its own item, so one update can be lost (last writer wins; there are no transactions). For inventory-like or counter state use a database with atomic updates and keep only references in the session.
13. Values are cloned with devalue at `set()` time, and class instances or functions are not serializable. A `SessionStorageSaveError` (“could not be serialized”) is thrown synchronously at the `set()` call.
14. The implementation sets `secure` only when the runtime mode is production, so dev over plain HTTP works. In production behind a TLS-terminating proxy, the cookie is `Secure`; the browser must see HTTPS, and the proxy must be configured so the site is served over HTTPS end to end or browsers drop the cookie.
15. It matches on `url.pathname`, which can differ from the route Astro matches (base, encoding, duplicate slashes), allowing bypass. Use `context.routePattern` (the matched route’s pattern), authorize again inside each handler, or use a router in `src/fetch.ts` (Hono).
16. In the server-side session (the browser holds only the opaque session cookie). That keeps tokens out of JavaScript, so XSS in an island cannot steal them.
17. Rule applied first, code merged on top: `maxAge` is last-write-wins so 60; tags accumulate in order: `['products', 'p-7']`.
18. It disables caching for the request and clears accumulated options and tags. A later `set({...})` re-enables caching starting from a clean state.
19. **b.** A response that sets a cookie is skipped (and a warning logged). Query strings and `Vary: Accept-Language` are supported; request cookies are ignored for the key (so d is still cached).
20. No. The memory provider needs a positive `maxAge`; tags alone do not cause caching (tested: it never produced `X-Astro-Cache` headers).
21. The entry is past `maxAge` but within the `swr` window: the stale response is served immediately and a background refresh updates the entry, so the next request is a `HIT`.
22. The first visitor’s greeting is cached and served to everyone (the cache ignores cookies). Fixes: exclude the route from rules and/or call `Astro.cache.set(false)`; or move the greeting into a server island (uncached) or a client-fetched Svelte island, keeping the shell cacheable.
23. Only the instance that handled the webhook purges its own memory cache; the other two keep serving stale content until `maxAge` expires. Options: use a CDN provider with global purge, short `maxAge` values, run a single instance, or fan the invalidation out to every instance.
24. Tracking parameters (`utm_*`, `fbclid`, `gclid` and others) are excluded from the key by default. Use `query: { exclude: [] }` to include everything, or `query.include` to allowlist specific parameters (you cannot use both).
25. `false`. In dev the cache object is a no-op. Run `astro build` then start the server (or `astro preview`) and inspect `X-Astro-Cache` or the provider’s headers.
26. A runtime provider implements `onRequest()` and stores responses in-process, adding `X-Astro-Cache`; Astro strips `CDN-Cache-Control` and `Cache-Tag` after the provider reads them. A CDN provider implements `setHeaders()` (and `invalidate()`) and relies on the CDN to cache and to consume the headers; hits never reach the server.
27. Path invalidation on tag-only CDNs needs every response tagged with its path; `setHeaders` receives the request, so it can add `pathTag(pathname)`. `collectInvalidationTags({ path: '/a' })` returns `['astro-path:/a']` (plus any tags, none here).
28. The island would cache personalized HTML (cache key is the island URL + props, not the cookie) and share it across users. Keep the shell cacheable, leave the island uncached (no `maxAge`, or `set(false)`), and let it read the session.
29. Before the first byte is sent: in middleware, page frontmatter, endpoints and actions. A cookie is a response header and cannot be added once streaming has begun.
30. The cache API and `routeRules` are stable, but the adapter providers (`cacheNetlify`, `cacheVercel`, `cacheCloudflare`) are experimental and may change; they are opt-in. You must import the provider from the adapter’s `/cache` subpath and set it as `cache.provider` in the config.

## Chapter 13: Images, Fonts, SVG and Styling

1.  An imported image is an `ImageMetadata` object, not a string. `<img>` needs a URL string, so use `hero.src`; `<Image>` accepts the metadata object directly and reads its dimensions and source path.
2.  `src` (a URL path), `width` and `height`. Files in `public/` are never analyzed or processed, so Astro cannot read their dimensions.
3.  `450`; the aspect ratio is preserved.
4.  `loading="eager"`, `decoding="sync"` and `fetchpriority="high"`. Use it only for the above-the-fold (LCP) image.
5.  **b.** `<source>` elements follow the `formats` order and the fallback `<img>` defaults to the source format (PNG for PNG, JPEG for JPEG).
6.  It points at the image endpoint (`/_image?href=...&w=...&f=webp`), and the transform runs on demand at request time. Put an HTTP cache or CDN in front, since each variant is computed per request.
7.  `image.responsiveStyles: true`. Without it the `max-width: 100%` / `width: 100%` styles are not added.
8.  The generated `sizes` assumes the image spans roughly the viewport on small screens and its max width on large ones; in a column layout it overestimates. Provide `widths` together with a matching `sizes` string (or `densities` for fixed layouts).
9.  `domains` lists exact hostnames only; `remotePatterns` matches protocol, hostname, port and pathname with wildcards. `**.amazonaws.com` matches all subdomain depths; `*.amazonaws.com` matches exactly one subdomain level.
10. Redirects are followed, but the final destination must also match an allowed pattern, so the image is not processed (an internal target is refused). This prevents bouncing through an allowed host.
11. It downloads the image to read its width and height so you need not supply them. It costs a request per image and only works for authorized remote hosts (since 5.17.3). Alternatively call `inferRemoteSize()`.
12. Astro components cannot be imported into a framework component, because a client island must contain only its own framework’s code. Fixes: compute `getImage()` in the parent `.astro` file and pass `src` as a prop; or pass `<Image />` as slotted children rendered by Astro.
13. A `GetImageResult` (`src`, `srcSet`, `attributes`, `options`, `rawOptions`). It relies on server-only APIs (image service, filesystem), so on the client it throws since 6.0; call it in frontmatter and pass the resulting URL.
14. `const opt = await getImage({ src: hero, width: 400, format: 'avif' });` then `<Card client:load src={opt.src} />`. Props must be serializable (a string is); functions and class instances are not.
15. An `<astro-slot>` element. The slot is static server-rendered HTML: the island cannot re-render it, read its props or make it reactive.
16. Astro’s scope attribute for scoped styles is forwarded to components in a scoped-style file as a prop. If the Svelte component spreads rest props onto its root, the attribute lands on the DOM element and the island joins the parent’s style scope; otherwise it is ignored.
17. Use different services for prerendered and on-demand pages: `build` runs in Node at build time (and in dev), `runtime` handles on-demand pages and `/_image`. Example: `service: { build: { entrypoint: 'astro/assets/services/sharp' }, runtime: { entrypoint: 'my-image-cdn-service' } }`.
18. SVGs can be crafted to be extremely expensive to process, enabling denial of service; enable only for trusted sources.
19. Astro components render on the server in the `.astro` pipeline and cannot be imported into other frameworks. Inline SVG in Svelte with `import icon from './x.svg?raw'` and `{@html icon}` (own file, trusted), or use a Svelte icon component, or pass the SVG as a slot.
20. Four (400 and 700, each normal and italic) because `styles` defaults to both. Set `styles: ['normal']` to download two.
21. Preload `<link>` tags for the family’s font files (or the filtered subset), plus the CSS variable definition. Preloaded fonts are fetched even if unused on the page and compete with critical resources.
22. They generate a size-adjusted fallback font face from the last generic family in `fallbacks` (e.g. `sans-serif`) so the swap from fallback to web font causes minimal layout shift; set `optimizedFallbacks: false` to disable.
23. Because scoping only tags elements in this component’s own template; elements rendered inside the child belong to the child. Either use `:global()` (`article :global(h2)` or a wrapper) or let the child accept a `class`/expose CSS variables.
24. `article[data-astro-cid-x] h1 { }`: the `article` is scoped and `h1` is unscoped.
25. Astro adds a `data-astro-cid-*` attribute to the component’s elements and rewrites selectors (`h1[data-astro-cid-x]`); Svelte adds a hash class (`.t.svelte-1s7zazm`) to matching elements. Independent mechanisms.
26. Add `svelte.config.js` with `import { vitePreprocess } from '@astrojs/svelte'; export default { preprocess: vitePreprocess() };` and install `sass`.
27. `<link>` tags in head (lowest), then imported styles, then scoped styles (highest, for equal specificity). Imported CSS is bundled with the module graph, so importing the component loads its CSS regardless of rendering.
28. When many pages share large stylesheets that benefit from long-lived browser caching, avoiding the same CSS being inlined into each page.
29. Inline `is:inline` script in `<head>` sets `document.documentElement.dataset.theme` from `localStorage` (try/catch) or `prefers-color-scheme` before paint; CSS keys off `:root[data-theme]` and `color-scheme`. The Svelte toggle reads state in `$effect` (browser only, no mismatch) and writes `dataset`/`localStorage`. With `<ClientRouter />`, re-apply the theme in `astro:before-swap` to the incoming document, since the inline script does not re-run. Inline scripts need a hash/nonce under CSP, and CSP does not support ClientRouter.
30. Astro’s responsive styles win: Tailwind lives in cascade layers, and unlayered CSS (Astro’s `:where()` rules included) beats layered rules regardless of specificity. To let Tailwind win, leave `responsiveStyles` off.

## Chapter 14: ClientRouter, View Transitions and Prefetch

1.  Plain navigation plus prefetch: bundled scripts keep running on every page (no re-initialization bugs), and it is compatible with CSP and has no accumulating global state. Router: persisted state (players, islands, inputs) across pages, and shared-element animations/lifecycle control.
2.  A full browser navigation. Both source and destination must include the router for the swap to happen.
3.  `astro:before-preparation` (spinner, replace `loader`, set `direction`), `astro:after-preparation` (hide spinner), `astro:before-swap` (mutate `newDocument`, replace `swap`), `astro:after-swap` (re-apply DOM state, scroll reset), `astro:page-load` (initialize behavior).
4.  `astro:before-swap`. Setting e.g. `data-theme` on `event.newDocument` means the new page is already themed when it replaces the old one, so there is no flash.
5.  **c.** It cannot be canceled, fires after fetching and parsing, and fires for all navigation types.
6.  A bundled module script executes once; after the body is replaced the element is new and has no listener. Fixes: bind inside an `astro:page-load` handler; use a custom element with `connectedCallback`; use an inline script with `data-astro-rerun` (idempotent); or an island.
7.  It fires on the first load and after every client navigation, so one handler covers both. `DOMContentLoaded` fires only on the real document load.
8.  With plain `transition:persist` the instance is kept and receives the new props, so it shows the new label (reactively). With `transition:persist-props` it keeps the old label. `onMount` does not run again in either case, because the instance is not remounted.
9.  By the persist key: the value of `transition:persist="key"`, otherwise the `transition:name`, otherwise an automatically assigned identity based on type and position.
10. It is not carried over; the old element is dropped with the old body.
11. CSS animations restart and iframes reload even when persisted (documented limitations); non-focused scroll positions inside containers are also not restored by the router.
12. Yes, it survives every client navigation because the JavaScript realm persists; `transition:persist` is irrelevant for it (it is about DOM nodes and component instances). The hazard is state leaking between pages.
13. Without the router the page unload discards the listener. With the router, non-persisted islands are destroyed when the body is replaced, but the effect returned no cleanup, so the `window` listener leaks and accumulates; persisted islands are never destroyed, so the listener lives on (which may be intended). Return a cleanup function from `$effect`.
14. Link: `data-astro-reload`. Form: `data-astro-reload` on the `<form>`.
15. The value is user-controlled and unsanitized: `javascript:` URLs or external origins could execute code or redirect away. Resolve against `location.origin`, require same origin (or an allowlist), and use only path + search + hash.
16. `animate` (default): simulate transitions with attributes and CSS then swap; `swap`: swap immediately with no animation; `none`: do a full-page navigation in unsupported browsers.
17. The `main` slides; the root crossfade is disabled by `none` on `<html>`, and elements without their own animation (header, footer) do not animate.
18. Keyframes are looked up by name in the document; scoped styles would rename them (hash/scoping) so the name in the animation object would not match.
19. `deselectScripts`, `swapRootAttributes`, `swapHeadElements`, `saveFocus`, `swapBodyElement`. A custom swap must always call `swapRootAttributes`, because it also swaps Astro’s internal root attributes (`data-astro-transition`) that the animation CSS needs.
20. Forms are intercepted: GET navigates with the query string, POST sends the data via fetch and swaps the result. Default POST encoding is `multipart/form-data`; set `enctype="application/x-www-form-urlencoded"` for the browser default.
21. Add `transition:persist` to the inputs (the old elements with typed values move into the new DOM). Pitfall: persisted elements keep their old attributes, so server-rendered error attributes like `aria-invalid` will be stale; render error state outside the persisted element.
22. Astro adds an `aria-live="assertive"` route announcer reading the title (else first `h1`, else pathname) and disables transition animations under `prefers-reduced-motion`. You must provide a `<title>` on every page (and manage focus).
23. `hover`: hover or focus; `tap`: pointer down just before click; `viewport`: link enters viewport; `load`: after page load. On data-saver or slow connections all fall back to `tap`.
24. When `<ClientRouter />` is used on the page. Disable prefetching with `prefetch: false` in config (or `{ prefetchAll: false }` to restrict to annotated links).
25. Firefox (errors without Cache-Control/Expires, though an ETag lets the response be reused) and Safari (no link prefetch; fetch fallback needs cache headers; ETags fail in private windows). The prefetched response cannot be reused from the HTTP cache without headers.
26. Hover/viewport prefetching issues the GET, triggering the side effect (logout, mark as read). Use POST actions or forms for mutations, and `data-astro-prefetch="false"` on any unavoidable link.
27. It appends `<script type="speculationrules">` instead of a `<link>` or `fetch()`, so supporting browsers prerender the page. `eagerness` (`immediate`, `eager`, `moderate`, `conservative`, default `immediate`) hints how aggressively the browser should speculate.
28. The target page runs before the user visits it, so analytics, side effects and personalized renders execute early; gate them on `document.prerendering`/`prerenderingchange`.
29. Three of them were removed in 7.0: `TRANSITION_AFTER_SWAP` (use the string `'astro:after-swap'`), `isTransitionBeforeSwapEvent` (compare `event.type === 'astro:before-swap'`) and `createAnimationScope` (remove it; no replacement is needed). The other two were removed earlier, in 6.0: `<ViewTransitions />` (use `<ClientRouter />`) and `handleForms` (form handling is always on; opt out with `data-astro-reload`).

30. Put the player and cart badge islands in the shared layout with `transition:persist` (named keys), so instances survive. Share state through a `.svelte.ts` rune module (survives navigation) and pass page-specific props with default prop updating. The nav island keeps `path` state initialized from a server prop and updated on `astro:page-load`, setting `aria-current`. Clean up listeners with `$effect` returns, apply theme in `before-swap`, and provide `<title>` per page.

## Chapter 15: Internationalization

1.  Astro provides locale-aware routing (folders, prefixes, redirects), fallback behavior, URL helpers (`astro:i18n`), `currentLocale`/`preferredLocale`, and optional domain mapping. You build the message dictionaries, pluralization/number/date formatting (use `Intl`), translated content structure, language switcher UI, `hreflang` markup and browser-language redirect policy.
2.  `src/pages/about.astro` serves `/about/` (default locale unprefixed); `src/pages/es/about.astro` serves `/es/about/`.
3.  The URL segment becomes `french` while the language tags are `fr` and `fr-CA`. Codes are used by `Astro.currentLocale` (first code) and by `Accept-Language` matching for `preferredLocale`/`preferredLocaleList`. The helpers also accept any code.
4.  **c.** Fallback keys (and values naming this locale) are locale paths, not codes; `fr` is rejected.
5.  `/french/x/` and `french`.
6.  The root URL has no page, so you get a 404 unless you write `src/pages/index.astro`. Options: a static meta refresh to `/en/`, `Astro.redirect('/en/')` on a server build, or `redirectToDefaultLocale: true`.
7.  False. `redirectToDefaultLocale: true` requires `prefixDefaultLocale: true`; with the default at the root there is nothing to redirect to, and Astro rejects the config.
8.  It defaulted to `true`; since 6.0 it is `false`. An old config that relied on the implicit redirect silently stops redirecting, and one that sets it to `true` without a prefixed default now fails validation.
9.  Redirect: address bar changes to the fallback URL, content of the fallback page, static build emits redirect (meta refresh) pages. Rewrite: address bar stays, fallback content is served at the requested URL, static build emits a page at that path with the fallback content.
10. It returns the URL’s locale, `es`. The page would be declared Spanish while in English, which misleads screen readers and search engines. Pass an explicit content language to the layout and set `lang` from it.
11. Symmetry: all languages are peers, link generation has no special case, URLs do not change if the default later changes, and no unprefixed root content competes with the language chooser.
12. `site` set, `output: 'server'`, no prerendered pages, a supporting adapter (Node, Vercel per the docs), and a proxy forwarding host and protocol. A static project fails validation on `domains` (output must be server).
13. The proxy does not forward the original `Host`/`X-Forwarded-Host` and `X-Forwarded-Proto`, so Astro cannot map the host and returns 404. Configure the proxy to pass them.
14. `https://fr.example.com/about`; `https://example.com/ja/about`.
15. Only on routes rendered on demand (not prerendered). It returns `undefined` when nothing matches.
16. All of your configured `locales` (no preference means all are equally preferred).
17. Output varies by `Accept-Language`; a cache keyed on URL alone could serve one visitor’s language to others. Send `Vary: Accept-Language` (or avoid caching those responses).
18. Make `/` the only on-demand page; read a `lang` cookie first, then `preferredLocale`, then the default; redirect with 302 and only from `/`, never from deep links. An explicit user choice (cookie) outranks `Accept-Language`.
19. A 301 is cached by browsers and shared caches, so a visitor whose language changes is stuck on the old target and your root becomes uncrawlable as a chooser.
20. The helper accounts for `prefixDefaultLocale`, custom paths, `base`, `trailingSlash` formatting and (absolute variants) `site`/domains, so config changes do not break links.
21. `getRelativeLocaleUrlList` / `getAbsoluteLocaleUrlList`; used to render `<link rel="alternate" hreflang>` entries.
22. It disables Astro’s own i18n middleware. No other `routing` option may be set alongside it.
23. `sequence(exceptions, middleware({...}))` where `exceptions` calls `next()` directly for `/api` paths (otherwise, `notFound`). Your middleware runs first so it can short-circuit before the standard behavior; `middleware()` after it applies the standard redirect/fallback logic.
24. A `Response` or `undefined` (test the result). It returns a 404 when the path is not a root (`/` or `/<base>`) and the URL contains no locale.
25. `src/content/blog/en/*.md` and `es/*.md`, one collection with `glob`. Entry ids are `en/launch`; split on `/` to get `lang` and the remaining slug, and return them as params from `getStaticPaths`.
26. Derive `Key` from the default dictionary and type every locale as `Record<Key, string>` so the compiler lists missing keys.
27. Plural categories vary by language; `Intl.PluralRules` selects `one/few/many/other`. Russian (and Polish, Arabic) has more than two forms, so `count === 1` fails.
28. The page computes `t(...)` strings on the server and passes `locale` and a `labels` object as props; the island formats with `new Intl.NumberFormat(locale, { style: 'currency', currency })`, optionally in a `$derived`.
29. Module-level state is shared across requests in the long-lived server process, so one request’s language can leak into another’s render. Pass `lang` as a prop (or use Svelte context per render) and keep module-level locale state to client-only code.
30. Changing language changes the URL, so a link works without JavaScript, is crawlable, and keeps URL and text consistent. Put `lang` (label in its own language), `hreflang`, and `aria-current="page"` on the current one.

## Chapter 16: Environment, Security and CSP

1.  `import.meta.env.API_URL` is statically replaced during `astro build`, so the value is baked into the bundle. A `server`/`secret` field from `astro:env/server` is not bundled; the adapter resolves it at runtime on each process, so the same artifact can run with different values.
2.  Astro evaluates the config before Vite loads `.env` files, so `import.meta.env` has no values there. Use `process.env` (for variables set by the shell or CI) or Vite’s `loadEnv(mode, process.cwd(), '')` to read `.env` files manually.
3.  **c.** `client` with `secret` is invalid because there is no safe way to deliver a secret to the browser. The others are valid.
4.  At the first request that imports `astro:env/server` (lazy validation). The server starts normally, then the request fails with HTTP 500 and an `EnvInvalidVariables` error stating the variable is missing.
5.  It validates secrets when dev or build starts, so a missing or malformed secret fails the build immediately. In CI this converts a runtime 500 into a failed pipeline.
6.  The client-public import works and the value is inlined into the client chunk. The `astro:env/server` import in a bundled script fails the build.
7.  `getSecret()` is implemented by the adapter, so it works on runtimes where the environment is not `process.env` (for example Cloudflare bindings). It also lets you read keys that are not in the schema, at the cost of no validation.
8.  Vite inlines the value at build time, so both environments get the CI-time value (or `undefined`). Use `astro:env/server` with `access: 'secret'`, which is resolved at runtime.
9.  Unsafe methods (POST, PUT, PATCH, DELETE) on on-demand routes whose content type is missing, `application/x-www-form-urlencoded`, `multipart/form-data` or `text/plain`. It prefers `Sec-Fetch-Site` and falls back to `Origin`; cross-origin gets 403.
10. No: `application/json` is not in the checked list. Browsers require a CORS preflight for that request, so your CORS policy (do not allow that origin or credentials) and authentication/CSRF tokens protect you.
11. Host-header injection through `X-Forwarded-Host`, which could poison `Astro.url`. Without configuration the header is not trusted and is ignored.
12. `**.example.com` matches both `a.example.com` and `a.b.example.com`. `*.example.com` matches exactly one subdomain level, so only `a.example.com`.
13. Both default to 1 MB (1048576 bytes). Server island request bodies carry the encrypted props and slot HTML.
14. Island props are encrypted with a build-time key. If instances have different keys, one cannot decrypt URLs produced by another during rolling deploys. `astro create-key` generates one key to share as `ASTRO_KEY`.
15. At build time for static content, and at render time on on-demand pages. Interpolated per-request data gives a per-request hash computed during rendering, so it is still allowed.
16. It replaces Astro’s default sources for `script-src`, which do not include `'self'` once overridden, so the site’s own scripts are blocked unless `'self'` is listed too.
17. Astro stops emitting hashes on that directive, because a browser ignores `'unsafe-inline'` when a hash or nonce is present. The directive is then only as strong as `'unsafe-inline'`.
18. `security.csp.styleDirective.resources: ["'self'", { resource: "'unsafe-inline'", kind: 'attribute' }]` puts `'unsafe-inline'` only in `style-src-attr`.
19. Using `kind: 'element'` creates `script-src-elem`, which browsers do not fall back from to `script-src`. The CDN in the default (`script-src`) resources therefore no longer applies to `<script>` elements. Move the CDN to `{ resource, kind: 'element' }`.
20. (1) `<ClientRouter />`: use native view transitions or skip CSP. (2) Shiki’s inline styles: switch to Prism or allow `style-src-attr`. (3) No dev mode support: test with build and preview. Also: external scripts need explicit resources or hashes.
21. It compiles to inline style attributes/updates, which `style-src` (without `'unsafe-inline'`) blocks. You need classes or a `kind: 'attribute'` allowance.
22. Headers can express directives meta cannot (and do not depend on parsing the HTML), and prerendered responses get them too. `frame-ancestors` (also `report-uri`, `sandbox`) only works in a header.
23. The dev server injects unhashable scripts and Astro disables CSP there; you would not see the real policy or violations.
24. In the checkout page frontmatter (or checkout-specific middleware) call `Astro.csp?.insertScriptResource('https://js.pay.example')` and `insertDirective("frame-src https://pay.example")`, so only that route’s policy is widened.
25. Encoded or differently normalized paths, trailing slashes and rewrites can make the matched string differ from the route that ultimately renders, bypassing the check. Authorize in middleware using the resolved route/locals or use a router such as Hono with proper route patterns, plus data-layer checks.
26. **b.** The session cookie defaults to `{ name: 'astro-session', sameSite: 'lax', httpOnly: true, secure: true }` (Astro relaxes `secure` in `astro dev`, and `httpOnly` cannot be turned off; Chapter 12).

27. To prevent session fixation: an attacker who planted a known session ID before login would otherwise share the authenticated session.

## Chapter 17: Performance, Testing and Observability

1.  A style rule for `astro-island, astro-slot, astro-static-slot { display: contents }`, a small script registering the directive (`Astro.visible`), and the larger script defining the `astro-island` custom element with the prop deserializer. The island element definition is shared by all islands on the page; each distinct directive type adds one small script, not one per island.
2.  The island is server-rendered to HTML, and the same data is serialized into the `props` attribute as JSON for hydration. Pass identifiers or only the fields rendered, and load the rest on demand.
3.  Cheapest to most expensive on first load: no directive (zero JS), `client:visible` (loaded only if scrolled into view), `client:idle` (loaded after load/idle), `client:load` (immediately). Use none for static UI, `visible` below the fold, `idle` for secondary controls, `load` for above-the-fold interactivity needed at first paint.
4.  It skips server rendering, so there is no HTML for SEO or first paint and layout shifts on hydration, and it moves the whole subtree to the client. You must name the framework (`client:only="svelte"`) and supply `slot="fallback"` content for the placeholder.
5.  Parent first. Each `astro-island` waits for its closest ancestor `astro-island[ssr]` to hydrate (it listens for `astro:hydrate` on it), so the child’s visibility trigger fires only after the `client:load` parent hydrated.
6.  For 20,000 pages: “generate pages” and the Markdown/image/plugin sections. For no prerendered pages: the bundle phases (prerender/ssr/client bundle), Vite plugins and slow files, since cost scales with code.
7.  When rendering is dominated by awaiting I/O that cannot be cached or batched. It is harmful for CPU-bound rendering: JavaScript is single-threaded, so you gain nothing and use more memory.
8.  Pages are rendered in worker threads that do not share module-level variables, so each worker has its own empty Map. Fix by persisting the cache outside memory (a disk cache keyed by input hash, or a content-collection loader that stores results), or by not enabling the flag.
9.  `getStaticPaths()` props must be serializable (no functions or class instances); each worker adds memory use. The flag is ignored with adapters that supply their own prerenderer, such as `@astrojs/cloudflare`, and Astro warns.
10. The `cacheKey` from `getStaticPaths()` and the content entry `digest`. If the key omits an input, the page is not rebuilt when that input changes and stays stale; `astro build --force` bypasses the cache.
11. It removed the construction of the render queue, the node polling feature, and reduced the content cache to tag names. A streaming approach replaced the queue: components are rendered and flushed as they are encountered.
12. Nothing is sent until both fetches complete, and they run sequentially. Move each fetch into its own component (`Reviews` and `Stock` fetch their own data) or use promises in the template, so the shell streams first and the fetches run in parallel.
13. The status code and headers are sent with the first chunk. Once the body has started streaming, a component can no longer change them. Redirects and cookies belong in middleware or at the top of the page before output.
14. It applies your Astro configuration and plugins (aliases, Svelte plugin, virtual modules) to Vitest’s Vite config. By default it loads the project’s Astro config; a second argument overrides it.
15. `environment: 'node'`. Astro components cannot be rendered in client-like environments such as jsdom or happy-dom.
16. **b.** Since Astro 7, `getContainerRenderer()` is imported from the package’s `container-renderer` entrypoint (the package-root import in (a) is deprecated); `loadRenderers()` comes from the virtual module `astro:container`, not `astro/container`, and (d) is not a public entrypoint.

17. The container was created without renderers, so the Svelte island cannot be server-rendered and rendering fails or lacks `Count: 0`. Create it with `renderers: await loadRenderers([getContainerRenderer()])`.
18. `renderToString()` returns the markup; `renderComponent()` (7.3.5) also includes the component’s inlined scripts and styles. Import the component with the `?container` query, e.g. `Card.astro?container`; without it the result equals `renderToString()`.
19. The component renders as a page partial: no `<!DOCTYPE html>` or page shell. Pass `partial: false` to render a full page.
20. Use `renderToResponse(Endpoint, { routeType: 'endpoint', request: new Request(url, { method: 'POST', body }) })` and read the `Response`.
21. The output contains Astro’s inlined island scripts, which change between Astro releases. Assert on specific substrings or parsed DOM nodes (title, slot text, `Count: 2`) instead of the whole string.
22. `$state` and `$derived` work in the node test, so `count` can be asserted. Vitest transforms modules through Vite’s SSR path where Svelte compiles in server mode, and effect callbacks do not run there (observed: an effect that pushed values stayed empty even after `flushSync()`). Test effect-driven behaviour in a browser-like setup or extract the logic.
23. The `ssr` attribute is removed from the `astro-island` element once hydration completes (and an `astro:hydrate` event fires). It comes from the island bootstrap script, which calls `removeAttribute('ssr')` after the hydrator finishes. Assert `not.toHaveAttribute('ssr')` before clicking.
24. Run against the production build (`webServer` with build plus preview or the built server). One test uses a context with `javaScriptEnabled: false` and checks the product content; another uses a normal context, scrolls the island into view for `client:visible`, waits for `ssr` to disappear, clicks add-to-cart and asserts the count.
25. A custom logger replaces all logging, including Astro’s build output, and nothing prints unless your `write()` outputs it. `flush()` is also not called by the build. Fix by composing with `logHandlers.node()` (or `console()`), or writing to `console` from the destination when not in request context.
26. `write()` receives every message and is required. `flush()` is called at the end of each request (batch/ship buffered messages). `close()` is called before the server shuts down (drain and close connections).
27. Strings only (`message: string`). Structured logging therefore requires encoding fields into the string (e.g. JSON) and parsing downstream, or using a custom destination.
28. `astro dev stop`, `astro dev status`, `astro dev logs [--follow]` (and `astro preview ...` since 7.2). State is in `.astro/dev.json` (`.astro/preview.json`). `--ignore-lock` starts another server without checking or writing the lock file; it cannot be combined with `--background` or `--force`, and the extra server is untracked.
29. So the long-running server does not block the agent’s terminal. It applies on macOS and Linux when an agent is detected; opt out with `ASTRO_DEV_BACKGROUND=0` (`ASTRO_PREVIEW_BACKGROUND=0` for preview).
30. `/_astro/status` returns `{"ok": true}`. It exists only on the dev server, not in production builds, so production needs its own health route.

## Chapter 18: Integrations and the Vite/Adapter API

1.  `astro:config:setup`, `astro:route:setup`, `astro:routes:resolved`, `astro:config:done`, `astro:build:start`, `astro:build:setup`, `astro:build:ssr`, `astro:build:generated`, `astro:build:done`. `astro:server:setup`, `astro:server:start` and `astro:server:done` run only in dev (after `config:done`).
2.  An on-demand route exists (for example an injected route with `prerender: false`, or `export const prerender = false`) and an adapter is present, so the effective build output is `server`. Never infer it from `config.output`.
3.  It can fire more than once (in the build the second call added `/404`; in dev it fires on every route change). Replace derived state rather than append.
4.  In `config:setup`, `config` is the user config resolved before any integration ran. In `config:done` it is the final config after all integrations’ `updateConfig` calls.
5.  It deep-merges the partial object into the user config plus earlier integrations’ updates, so you may omit keys.
6.  `injectRoute({ pattern: '/_acme/health', entrypoint: '@acme/health/health.ts', prerender: false })` with `"exports": { "./health.ts": "./health.ts" }`.
7.  When Astro cannot detect an `export const prerender` in the entrypoint.
8.  `pre` runs before the user’s middleware (`post` after). Middleware runs at request time only for on-demand pages; prerendered pages are static files, so the header is not added by the middleware (in classic mode it ran at build time only).
9.  (a) `page-ssr` (import in every page’s frontmatter); (b) `before-hydration`; (c) `head-inline`; (d) `page`.
10. It writes `.astro/integrations/<normalized_integration_name>/<normalized_filename>.d.ts` (filename must end in `.d.ts`) and returns its URL. Astro includes it for the user automatically, so users need no manual `tsconfig` edits.
11. It marks the module as virtual (Rollup convention) so other plugins do not try to resolve it from disk.
12. Check `this.environment.name === 'client'` in `load` (or `resolveId`) and throw, so the build fails rather than bundling the secrets.
13. `client` (browser output), `ssr` (server bundle), `prerender` (building static pages during build), `astro` (dev-only secondary SSR environment used when Vite’s `ssr` is not runnable).
14. So Svelte’s server runtime is not pre-bundled separately from the copy used by `@astrojs/svelte/server.js`; otherwise two copies with separate `ssr_context` state crash dev SSR.
15. It would claim Svelte components (renderers are tried in order until one returns true), breaking rendering if registered first. `check` must be precise.
16. A record of slot names to static HTML strings. `metadata.hydrate` is the client directive (undefined if not hydrated), letting the renderer skip serializing hydration state.
17. `astro:unmount`, dispatched on the island root; the client entrypoint should listen to clean up mounted state.
18. `Cannot find the built path for file:///.../tiny-client.js`. Pass a string: a package specifier or an absolute path (`new URL(..., import.meta.url).pathname`).
19. Entrypoints are bundled only with esbuild and inlined into pages that use the directive, so their size is paid on each such page and delays hydration.
20. `(load, options, element)`. `load()` returns a promise for a `hydrate` function that you call to hydrate the island.
21. `init(canvas, app, server)`: a ShadowRoot, an event target with helpers, and server communication helpers. The server side is handled in `astro:server:setup` through `toolbar.on/send`.
22. The toolbar exists only in `astro dev` and never ships to production builds.
23. `'explicit'` (deprecated legacy default) requires `createExports()` in the entrypoint and an `exports` list. `'auto'` lets you own the module via `serverEntrypoint` or `rollupOptions.input`, built on `createApp()`.
24. Call `setGetEnv()` from `astro/env/setup` before `getSecret()` is used (per request where the environment is request-bound, as on Workers).
25. Middleware emitted separately from the server bundle so it can deploy as an edge function. `astro:build:ssr` provides `middlewareEntryPoint` (a URL, undefined if not opted in).
26. With `staticHeaders: true` Astro collects headers for static pages; with CSP the policy goes into headers and no `<meta>` is added. `astro:build:generated` provides `routeToHeaders`.
27. `client`, `server`, `prerender` (URLs). Integrations and plugins may relocate output, so the resolved directories are authoritative.
28. A `PrerenderResult` (`{ response, metadata? }`); returning a bare `Response`, returning a bare array from `getStaticPaths`, and the `collectMetadata` option are deprecated.
29. Hook unit tests with fake arguments (cheap; cannot detect Vite behaviour) and fixture builds that run `build`/`dev` and request output (realistic; slower and cannot easily cover every hook edge case). Test both dev and build.
30. **d.** The documented discoverability keywords are `astro-integration`, `astro-component` and `withastro`; `astro-adapter-svelte` is made up.


## Chapter 19: Migrating to Astro 7

1.  Hard errors from 6.0 removals (legacy collections, `<ViewTransitions />`, `Astro.glob()`) are easiest to fix against a build you can still run, and 7.0’s subtle output changes (compiler strictness, whitespace) need a known-good 6.x baseline to diff against. Each step also has a smaller set of suspects when something breaks.
2.  Astro 6 requires Node 22.12.0+; Astro 7.4 (and `@astrojs/svelte` 9.1.0) requires 22.22.0+. Check CI images, hosting runtime settings and `.nvmrc`/`engines`, not just local Node.
3.  It upgrades Astro and the official integrations (adapters, Svelte, MDX) together to compatible versions, avoiding mismatched majors.
4.  `z.email().min(5, { error: 'Too short' })`.
5.  In Zod 4 defaults must match the output type and short-circuit parsing, so the string `"0"` is wrong for a number output. Use `.default(0)`, or `.prefault("0")` to keep the old behaviour where the default is parsed.
6.  No config file: create `src/content.config.ts`. Config at `src/content/config.ts`: move it. No `loader`: add `glob()`. `type: 'content'|'data'`: delete. `getEntryBySlug`/`getDataEntryById`: `getEntry()`. `entry.slug`: `entry.id`. `entry.render()`: `render(entry)`.
7.  `type` without loaders, `entry.slug` and `entry.render()`, path-based IDs (the 6.0 guide also lists the legacy config file). It is a temporary migration helper that is in maintenance mode and should be removed once collections use loaders.
8.  `import.meta.env` values are inlined and never coerced, so the value is the string `"false"`, which is truthy. Compare explicitly: `import.meta.env.FEATURE_X === 'true'`.
9.  `import.meta.env` is now inlined at build and non-public variables are no longer rewritten to `process.env`. Fix by reading `process.env.DB_PASSWORD` at runtime or, better, declaring it with `astro:env` as a server secret.
10. They now render in the order defined (Astro 5 reversed them). Rules that depended on the reversed cascade, such as overriding `body` background, may produce different results and need reordering.
11. Heading IDs now follow `github-slugger`: trailing hyphens are no longer stripped for headings ending in special characters (so ``## `<Picture />` `` ends with a hyphen). Hand-written anchors must be updated.
12. It crops to the given dimensions by default (no `fit` needed) and never upscales. An SVG with `format="avif"` is now rasterized, so guard with `src.format === 'svg' ? 'svg' : 'avif'`.
13. With `prefixDefaultLocale: false` the old default of `true` could produce redirect loops. Set `prefixDefaultLocale: true` and `redirectToDefaultLocale: true` to recreate it (manual routing middleware options likewise).
14. Any three of: `astro:ssr-manifest`, `RouteData.generate()`, `entryPoints` on `astro:build:ssr`, `routes` on `astro:build:done`, the old `app.render()` signature, `app.setManifestData()`.
15. Unclosed tags (build errors), invalid HTML no longer auto-corrected (different rendered output in the browser), and cosmetic CSS serialization differences (colour/`url()` strings changed, only affecting exact-match tests).
16. `AB` with no space, because `compressHTML: 'jsx'` drops whitespace between sibling elements on separate lines. Use `<a href="/a">A</a>{" "}<a href="/b">B</a>` or set `compressHTML: true`.
17. The Go compiler moved the `<div>` out of the `<p>` to match the HTML spec; the Rust compiler passes it through as written, and the browser then closes the `<p>` early, which can change layout. Fix the markup (use a `<div>` container).
18. Astro tries to load it as an advanced routing configuration, causing errors. Either rename the file (and update imports) or set `fetchFile` to another path or `null`.
19. `logger`, `queuedRendering`, `rustCompiler`, `advancedRouting`, `cache` (with `routeRules`). `logger`, `cache` and `routeRules` move to top-level config; the others are deleted.
20. Minimal: install `@astrojs/markdown-remark` and set `markdown.processor: unified()` (deprecated `markdown.remarkPlugins` also still works if the package is installed). Long term: port plugins to Sätteri MDAST/HAST plugins, then remove `unified()`.
21. `node:sqlite` (Node 22.5+), Drizzle ORM directly, or another database library/service. It is a data migration because schema, seed scripts, queries and `astro:db` imports must be replaced.
22. `event.type === 'astro:before-swap'`.
23. Old: `import { getContainerRenderer } from '@astrojs/svelte'`; new: `import { getContainerRenderer } from '@astrojs/svelte/container-renderer'`. The old import still works but logs a deprecation warning.
24. `undefined`, with a `[WARN] [session]` message that `Astro.session` was accessed with no session storage configured. The API reference is right for the unconfigured/disabled case; the changelog’s “always defined” holds when storage exists (e.g. an adapter default driver). Guard with `Astro.session?.`.
25. `session: { driver: sessionDrivers.redis({ url }) }` with `sessionDrivers` imported from `astro/config`.
26. 7.x with Astro 5 (e.g. `$props.id()` fix), 8.x with Astro 6 (Vite 7, plugin-svelte 6), 9.x with Astro 7 (Vite 8, plugin-svelte 7, container-renderer path); 9.1 raises Node to 22.22.0.
27. **c.** Since integration 6.0.0 `vitePreprocess()` is no longer added by default; import it from `@astrojs/svelte` in `svelte.config.js` (the editor tooling reads that file too). It can be omitted entirely, and it was not removed.

28. `+page.svelte` to `src/pages/*.astro`; `+layout.svelte` to an Astro layout with `<slot />`; `load` to frontmatter/collections; `handle` to middleware `onRequest`; `$env/static/private` to `astro:env/server` secrets.
29. Put the cart in a rune module or Nano Store that all cart islands import (and persist with `transition:persist` if using `<ClientRouter />`). On the server avoid module-level singletons that leak across requests, and remember Astro (non-island) components cannot subscribe.
30. For example: remove `legacy` flags and legacy collection usage; update config deprecations (session drivers, markdown options); update imports (`z`, container renderers); then adapter/integration author APIs. Add a CI `rg` check for deprecated patterns.

## Chapter 20: Capstone: A Multilingual Shop with Svelte Islands

1.  Actions, sessions, live collections and route caching (also server islands and the webhook endpoint) all require on-demand rendering and an adapter. Prerendered catalogue data would be a build-time snapshot.
2.  Marketing and static content pages (`prerender = true`). For catalogue and product pages you could prerender the shell and render stock through a server island or a client fetch, or keep them on-demand with route caching and tag invalidation as built here.
3.  The route rule contributes `catalog`; the live loader’s hints contribute `sku:<id>` (entry hint, product page) and `inventory` plus all `sku:` tags (collection hint, list page). Tags accumulate, and because both pages carry `sku:lamp`, invalidating that one tag purges the lamp page and the list while other products stay cached.
4.  During SSR it would run on the server at import time, touching a store shared by all requests, and call `actions` without a browser. Module-level writes on the server leak across requests; calls need a browser (`document`, relative fetch).
5.  Server module state is shared by all requests, so writing per-user data would leak between users and make cached HTML user-specific. The server renders the empty state; the badge shows an ellipsis until `ready`.
6.  Zod validation of input, product existence checked against the collection, stock checked against the live collection, a per-line maximum `min(MAX_QTY_PER_LINE, stock)`, and the cart read/written only via the session. Prices are not stored so the client cannot tamper with them; totals are computed from the collection.
7.  `accept: 'form'` accepts form-encoded/multipart bodies (a cross-site form can send them), so `security.checkOrigin` applies and returns 403 for cross-origin requests. `accept: 'json'` requires a JSON content type that browsers cannot send cross-site without a preflight, which `checkOrigin` does not inspect.
8.  Session fixation: an attacker who planted a known session ID before login would otherwise share the authenticated session. Call it whenever privilege changes, e.g. after successful login.
9.  `POST /bg/cart/?_action=cart.add` (`getRelativeLocaleUrl('bg','cart') + actions.cart.add`). Astro runs the action before rendering the cart page; `Astro.getActionResult(actions.cart.add)` there returns that result so the page can show the error.
10. A per-user page must never be cached; the explicit opt-out guards against a future broad route rule (and documents intent), since rules also merge with `cache.set`.
11. `maxAge` stays 60 (the hint carries tags/lastModified, not `maxAge`); tags are `catalog` plus the hint’s tags (accumulated).
12. `HIT` shows the response came from the route cache without rendering. After the webhook invalidated tag `sku:lamp`, the next request missed, re-rendered and read the new live stock.
13. Each instance has its own in-process cache, and invalidation reaches only the instance that received the webhook, so instances serve stale or inconsistent content. Use a CDN/shared provider or fan the webhook out.
14. The greeting depends on the session, so putting it in the shared cached page would either show one user’s name to others or force the whole page uncacheable. The server island fetches it per user.
15. It receives `locale` as a (encrypted) prop passed from the page, because `Astro.url` there is the island endpoint.
16. It keeps the DOM element and the island instance with its state (props are updated unless `transition:persist-props`). The old and new pages must have an element with the same `transition:persist` name (and the same component).
17. The persisted island does not re-run; the cart can change through a plain form post (no-JS path) or another tab. The listener re-syncs the store from the `data-cart-lines` element rendered by the cart page after each navigation.
18. Its replacement HTML arrives asynchronously after the swap, while persistence matches elements present at swap time. Per-user data should live in the persisted island’s store instead.
19. With `prefixDefaultLocale: true` Astro needs a root index page to create the redirect to the default locale. Add `src/pages/index.astro` that redirects to `/en/`.
20. `[locale]` matches any first segment, so unknown values would render pages with fallback text. The page checks `locales` and returns a 404 `Response` for `/fr/`.
21. The sold-out `notebook` POST returned 409 (`ActionError` code `CONFLICT`) with the “Sold out” alert.
22. `checkOrigin` rejects unsafe form-type requests whose `Sec-Fetch-Site`/`Origin` is cross-origin (403, verified). A JSON POST is not covered by `checkOrigin`; a cross-site page cannot send `application/json` without a CORS preflight, so CORS policy protects it.
23. `security.csp` is incompatible with `<ClientRouter />`, which the shop uses for the persisted badge. Alternatives: keep the router and add other header protections, or drop the router, use native view transitions and enable CSP (with `staticHeaders`).
24. With `validateSecrets: false` secrets are validated at runtime on first import, so the server starts but the webhook fails on first call. Catch it with `validateSecrets: true` in CI builds and a health check route that imports `astro:env/server`.
25. It proves the component renders and picks the localized guest text without a server. It cannot prove session-dependent behaviour (the container has no real session), hydration, or the server island fetch.
26. A `client:visible` island is plain server HTML until it hydrates; clicking earlier does nothing. Astro removes the `ssr` attribute after hydration, so it is the reliable synchronization signal.
27. **b.** Live entries are fetched on each request (no data store), may carry a `cacheHint` with tags for route caching, do not support MDX or image optimisation, and need on-demand rendering rather than `prerender = true`.

28. The server would write per-user data into a module-level store shared by all requests, leaking one user’s cart into others’ renders (and cached HTML). Initialization must happen only in the browser (`onMount`) or from request-scoped data.
29. Make description (and possibly price/availability) per-market, either one entry per locale/market or a market-keyed field validated with Zod, with `[market]` routes; give tags market-scoped names (`sku:<id>:<market>` or add `market:` tags) so invalidation targets the right pages, and extend the webhook accordingly.
30. In the loader/page: set a timeout and fallback (`error` or last-known value) and fetch stock in parallel with other work, or move stock to a server island with a fallback so the page streams immediately. In caching: raise `maxAge`/`swr` with tag invalidation from the webhook so most requests never hit the slow API (or use `loadCollection` batching/memoization with a short TTL).
