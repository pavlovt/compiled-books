# Quiz Answer Keys

Answers to the daily quizzes. The reference in brackets points to the companion book chapter where the topic is explained in full.

## Day 1: Svelte 5 Core

1. At compile time, Svelte turns each component into JavaScript that creates the DOM and wires reactive expressions to signals. At run time, a small signals runtime tracks dependencies and re-runs only the effects whose dependencies changed. (Svelte 1, 2)
2. `$state([])` creates a deep proxy: mutations such as `push` or `arr[0].x = 1` are reactive. `$state.raw([])` is not proxied: only reassignment (`arr = [...]`) triggers updates. Choose `raw` for large data that you replace wholesale, such as API responses. (Svelte 3)
3. `false`. `$state` wraps a plain object in a proxy; the proxy is a different object from the original. (Svelte 3)
4. `$state(count * 2)` captures the initial value only. Use `let doubled = $derived(count * 2);`. (Svelte 7)
5. Computing values from state → `$derived`. Reacting to a click or submit → the event handler. Syncing a prop into local state → `$derived` (or a writable derived). Synchronising two inputs → a function binding. (Svelte 4)
6. After the DOM has been updated, batched in a microtask. Never during SSR. (Svelte 4)
7. It is the teardown: it runs before the effect re-runs and when the component is destroyed. Use it to clear timers and remove listeners. (Svelte 4)
8. The effect reads and writes `n`, so it re-triggers itself until Svelte throws `effect_update_depth_exceeded`. (Svelte 4)
9. Accept a callback prop, for example `onchange`, and call it: `onchange?.(value)`. (Svelte 7)
10. `state_invalid_export`: a reassigned `$state` cannot be exported. Fixes: export an object and mutate a property (`export const counter = $state({ count: 0 })`), export getter/setter functions, or use a class instance. (Svelte 3)
11. d. Only `.svelte` and `.svelte.js`/`.svelte.ts` files can use runes. (Svelte 1)
12. `$derived(expr)` takes an expression; `$derived.by(fn)` takes a function, for logic that needs statements. They are otherwise the same. (Svelte 4)
13. Lazy: it recomputes only when read after a dependency changed. Equality cut-off: if the recomputed value is identical (`===`) to the previous one, dependents are not updated. (Svelte 4, 5)
14. The method is detached from the instance, so `this` is `undefined`. Define it as an arrow-function field (`add = () => {…}`) or use `onclick={() => cart.add()}`. (Svelte 3)
15.
    ```html
    <script lang="ts">
    	let { name, ongreet }: { name: string; ongreet?: (g: string) => void } = $props();
    	let greeting = $derived('Hi ' + name);
    </script>
    <button onclick={() => ongreet?.(greeting)}>Greet</button>
    ```

## Day 2: Svelte 5 Components

1. Keys let Svelte match DOM nodes and state to items by identity. With the index (or no key), deleting or reordering items makes nodes, input values and component state stay at a position and attach to the wrong item. (Svelte 6, 18)
2. Snippets. `{@render footer?.(title)}` in the child, with `footer?: Snippet<[string]>` in the props; the parent writes `{#snippet footer(t)}…{/snippet}` inside the component tags. (Svelte 7)
3. It marks the prop as two-way bindable, so the parent can write `bind:value`. Binding to a prop that was not declared with `$bindable` is an error: Svelte refuses to bind to a non-bindable prop. (Svelte 7, 8)
4. Context stores the value that was passed; reassigning the local variable creates a new value that context never sees (for primitives, a copy was passed). Put an object in context and mutate it: `const theme = $state({ current: 'light' }); setContext('theme', theme); theme.current = 'dark';`. (Svelte 12)
5. Any four of: `$effect`, `onMount`, actions, attachments, event handlers, transitions. (Svelte 14)
6. Module-level state is shared by every request on the server, so one user’s data can be rendered for another user. Use context set in the layout (or `data`), not a module singleton. (Svelte 12, 14; Kit 12)
7. The client renders different markup from the server: `Date.now()`, `Math.random()`, reading `window`/`localStorage` during render, or invalid HTML that the browser repairs. (Svelte 14)
8. It inserts raw HTML without sanitising: stored user content can run scripts (XSS). Sanitise on the server with an allow-list sanitiser, or render text instead. (Svelte 6; Kit 15)
9. b. Svelte 5 has no event modifiers. (Svelte 6)
10. An action runs once after mount, untracked; its parameter is not reactive by default; it cannot be used on components. An attachment runs in an effect, re-runs when the state it reads changes, and can be passed through components as a prop. (Svelte 9)
11. Radios: the single selected value. Checkboxes: an array of the checked values. (Svelte 8)
12. When the state is per component tree or per request (SSR), or when you want different instances in different subtrees (and easy test injection). A singleton is acceptable only for browser-only global state. (Svelte 12)
13. A `[get, set]` pair (plus `has` since 5.57) bound to a private key. Calling `get` with no value set throws `missing_context`. (Svelte 12)
14. Put the logic in a `.svelte.ts` module (a class with `$state`/`$derived` fields, or functions taking getters) and unit test it directly; deriveds can be read synchronously. (Svelte 16)
15. It destroys and recreates its content whenever the value changes. Use it to reset a component’s internal state (for example an editor when the selected id changes) or to replay a transition. (Svelte 6)

## Day 3: SvelteKit Foundations and Routing

1. Svelte compiles components; the Vite plugin generates the route manifest and types and builds the bundles; the adapter turns the build into a deployable artifact for a platform. (Kit 1)
2. The server runs the loads, renders HTML and sends it with the data; the browser hydrates it. On the next navigation the client router fetches only the code and data (`__data.json`) and updates the page without a full reload. (Kit 1, 2)
3. In the options passed to `sveltekit({...})` in `vite.config.ts`. `$lib` became `#lib`, a Node subpath import declared in `package.json` `"imports"`, used with file extensions. (Kit 1)
4. `+page.server.ts`, `+layout.server.ts`, `+server.ts` (and hooks). (Kit 3)
5. `[[lang]]/about`: `/about`, and `/<anything>/about` with one extra segment, such as `/en/about`. `docs/[...path]`: `/docs`, `/docs/a`, `/docs/a/b/c`. `(shop)/cart`: `/cart`; the group does not appear in the URL. (Kit 3)
6. In `src/params.ts`: `export const params = defineParams({ positive: (p) => (/^[1-9]\d*$/.test(p) ? Number(p) : undefined) });`, and name the route directory `[id=positive]`. (Kit 3)
7. No: the route simply does not match, and the router tries the next route. Only if nothing matches is it a 404. (Kit 3)
8. `blog/new`: static segments are more specific than parameters. (Kit 3)
9. A directory in parentheses: routes inside share a layout without the group name appearing in the URL. For example `(marketing)` and `(app)` areas with different layouts. (Kit 3)
10. A browser `GET` (with `Accept: text/html`) goes to the page; `DELETE` always goes to the endpoint. (Kit 3)
11. a. (Kit 12)
12. It builds a URL from a typed route ID and params (prefixing the base path), and the type checker rejects unknown routes or wrong params. It replaced `resolveRoute` and the manual use of `base`; `assets` was replaced by the separate `asset()` function. (Kit 3)
13. Any three of: `$lib` → `#lib`; `$app/stores`/`$page` → `$app/state`/`page`; `svelte.config.js` gone; `$env/*` → `src/env.ts` and `$app/env/*`; `invalidateAll` → `refreshAll`; `pushState`/`replaceState` → `goto` with `shallow`; `base` → `resolve()`; `src/params/*.js` → `src/params.ts`. (Kit 1, 20)
14. It types `params`, `data`, `form` and the load/action signatures for that specific route. It is generated by `svelte-kit sync` (run by `prepare`, `check`, `dev` and `build`). (Kit 1)
15. It makes the page break out of its intermediate layouts and use only the root layout. (Kit 3)

## Day 4: Data Loading and Form Actions

1. Server: database or filesystem access, secrets/private env, cookies and `locals`, batching several dependencies into one request. Universal: calling a public API directly from the browser on navigation; returning non-serialisable values (components, class instances). (Kit 4)
2. Everything it returns is serialised into the page and visible in the browser. Return an explicit projection: `return { user: { id: u.id, name: u.name } }`. (Kit 4, 15)
3. Only what the universal load returned. The server result is available to it as `event.data`, and it must forward any fields it wants to keep. (Kit 4)
4. The component is reused between `/blog/a` and `/blog/b`, and `$state(data.post.title)` only captured the first value. Use `let title = $derived(data.post.title);`. (Kit 4, 12)
5. Any four of: a param it read changed; the pathname or a search param it read changed; it awaited `parent()` and the parent re-ran; a dependency it declared or fetched was invalidated; `refreshAll()` was called (including by `use:enhance`). (Kit 5)
6. It forwards cookies and authorisation headers same-origin; it accepts relative URLs on the server; internal requests skip HTTP; responses from universal loads are inlined into the HTML and not refetched during hydration; it goes through `handleFetch`. (Kit 4)
7. No. Loads run in parallel and a client navigation may not re-run the layout load, so the page load can run and return data. Check `locals.user` in the page load (and/or in `handle`). (Kit 4, 14)
8. `redirect()` throws, and the catch-all swallows it and turns it into a 500. Rethrow with `if (isRedirect(e)) throw e;` or move the redirect outside the `try`. (Kit 4, 10)
9. Return an un-awaited promise from a **server** load and render it with `{#await}`. After streaming starts, the status code, headers, cookies and redirects can no longer change. (Kit 5)
10. The action runs first, then the load functions, then the page renders with the action’s result as `form`. (Kit 6)
11. `fail` returns data to the page with a status, and the form re-renders with `form` populated (a validation error). `error` throws and renders the error page (`+error.svelte`). (Kit 6)
12. It submits with `fetch` without reloading; updates `form` and `page.status`; resets the form on success; calls `refreshAll()` to re-run loads; follows redirects; renders the error boundary on errors. (Kit 6)
13. c. (Kit 6)
14. For read-only operations whose result should be in the URL: search, filters, pagination. (Kit 6)
15. The feature works with plain HTML (a form that posts and a server that renders the result), and JavaScript only improves it. Prove it with a Playwright test using `test.use({ javaScriptEnabled: false })`. (Kit 6, 19)

## Day 5: Hooks, Errors, Rendering, State and Environment

1. All dynamic requests: page renders, `__data.json` data requests, actions, `+server` endpoints, remote calls and internal `event.fetch` sub-requests. Not: static files, built assets and prerendered pages (served before SvelteKit runs). (Kit 9)
2. A per-request, server-only object, typed as `App.Locals` in `app.d.ts`. Pattern: `handle` validates the session cookie and sets `locals.user`; loads, actions and endpoints read it. (Kit 9, 14)
3. Before `resolve`: a then b. After `resolve`: b then a. (Kit 9)
4. An expected error (`error(404, 'Not found')`) shows its message to the user. An unexpected error shows a generic message; details are only logged through `handleError`. (Kit 10)
5. The static `src/error.html` page (the root layout cannot render `+error.svelte`, which lives inside it). (Kit 10)
6. It receives every error, including `error()` ones, with a `kind`; it can return a status; omitted properties are inherited; it must not throw. (Kit 10)
7. `prerender`: build-time static HTML. `ssr = false`: no server rendering, the page renders only in the browser. `csr = false`: no JavaScript is shipped. With `csr = false` you lose hydration, interactivity, client-side navigation and `use:enhance`. (Kit 11)
8. Prerendered pages are static files; a POST to them cannot run an action at request time. (Kit 11)
9. Module-level variable on a shared server: concurrent requests overwrite each other, so one user can see another’s identity. Use `event.locals` (and `getRequestEvent()`). (Kit 12)
10. In the URL search params: shareable, reload-safe, visible to SSR and loads, and Back works. (Kit 12)
11. `goto('', { shallow: true, state: { showModal: true } })` and render on `page.state.showModal`; close with `history.back()`. (Kit 12)
12. d. (Kit 12)
13. Static values are inlined into the build; dynamic ones are read when the server starts. A database password should be private and dynamic. (Kit 13)
14. The build fails, because server-only modules cannot be imported from client code. Vitest disables this check (`process.env.TEST`), so unit tests do not notice. (Kit 13, 19)
15. In `src/env.ts` with `public: true` (and `static: true` for build-time), then import it from `$app/env/public`. In SvelteKit 2, exposure was decided by the `PUBLIC_` prefix and read from `$env/static/public` or `$env/dynamic/public`. (Kit 13)

## Day 6: Testing

1. Unit (Vitest in Node): logic, loads, actions, endpoints. Component (Vitest browser mode with `vitest-browser-svelte`): a component renders and behaves correctly in a real browser. End to end (Playwright on the production build): the whole app works for a user, including routing, SSR, hydration and forms. (Kit 19)
2. By file name: `*.svelte.spec.ts` runs in the `client` project (browser); other `*.spec.ts` files run in the `server` project (Node). (Kit 19)
3. Runes are compiled only in files with `.svelte` in the name; otherwise `$state` throws `rune_outside_svelte`. (Svelte 16)
4. Tests that never assert anything (for example an `expect` in a callback that never runs) would pass silently; with the option they fail. (Kit 19)
5. `expect(value)` checks a value once. `await expect.element(locator)` retries the assertion against the page until it passes or times out, which absorbs rendering timing. (Kit 19)
6. Pass `onchange: vi.fn()` as a prop, interact, then `expect(onchange).toHaveBeenCalledWith(newValue)`. (Kit 19)
7. `createRawSnippet(() => ({ render: () => '<span>text</span>' }))`, or a small harness component that renders the component with real snippet markup. (Svelte 16)
8. Mock the module: `vi.mock('$app/state', () => ({ page: { url: new URL('http://localhost/x') } }))`, or refactor the component to take the value as a prop. (Kit 19)
9. Create the effect inside `$effect.root(...)`, call `flushSync()` after each change, assert, then call the returned cleanup. (Svelte 16)
10. `load` is async, so it returns a rejected promise instead of throwing synchronously; `toThrow` on the function does not see it. Use `await expect(load(event)).rejects.toSatisfy((e) => isHttpError(e, 404))`. (Kit 19)
11. To test what ships: the bundled build, real SSR and hydration, production behaviour (CSRF, preloading). The dev server differs. (Kit 19)
12. The locator matched more than one element, and Playwright requires exactly one for actions and many assertions. Scope it (a parent locator, an accessible name) or use a more specific role. (Playwright docs; playbook)
13. Server HTML can be interactive-looking before JavaScript attaches handlers; an early click does a native submit or nothing. Use retrying assertions on outcomes, or wait for a hydration marker set in `onMount`. (Kit 19)
14. A Playwright test with `test.use({ javaScriptEnabled: false })` that submits the form and checks the result. (Kit 19)
15. `page.route` only intercepts requests made by the browser. The data was fetched on the server during SSR. Stub the upstream on the server side (environment variable, `handleFetch`). (Kit 19)

## Day 7: Remote Functions and Production Breadth

1. Type-safe server functions in `*.remote.ts` files that you call from components; SvelteKit generates the endpoints. Kinds: `query`, `form`, `command`, `prerender` (plus `query.batch` and `query.live`). (Kit 7, 8)
2. Every argument arrives over HTTP and can be forged; a Standard Schema validates and types it. (Kit 7)
3. No. A query request goes to the remote endpoint URL, not `/admin/users`, so a path-prefix guard does not see it. Authorise inside the function. (Kit 14)
4. `experimental: { remoteFunctions: true }` and `compilerOptions: { experimental: { async: true } }`, both inside `sveltekit({...})`. (Kit 7)
5. Page loads run in parallel with layout loads and a navigation may not re-run the layout load; the page’s data can be returned anyway. (Kit 14)
6. `httpOnly` (no JavaScript access), `secure` (HTTPS only), `sameSite: 'lax'` (CSRF protection), an explicit `path: '/'`, and an expiry. (Kit 14)
7. The `Origin` header of form-encoded POST/PUT/PATCH/DELETE requests must match the app’s origin (or `trustedOrigins`). Production only; not in `vite dev`. (Kit 15)
8. `{@html}` with untrusted content, `javascript:` URLs in `href`, third-party scripts (and verbatim template substitution). (Kit 15)
9. Requests that wait on each other unnecessarily, for example awaiting `parent()` before starting independent work. Start independent promises first, then await; move work to the server and batch. (Kit 16)
10. They are private and depend on the user; SvelteKit marks them `private, no-store`. Cache a public page with `setHeaders({ 'cache-control': 'public, max-age=…' })` in its load, or prerender it. (Kit 16)
11. `adapter-node`. Behind a proxy, set `paths.origin` or the `PROTOCOL_HEADER`/`HOST_HEADER` (and `ADDRESS_HEADER`) variables; `ORIGIN` was removed in 3. (Kit 18)
12. It runs migration tasks (config, `#lib`, `$app/state`, env, paths, params, shallow routing, imports) and writes what it cannot do to `MIGRATION_TASKS.md`. Behavioural changes remain for you. (Kit 20)
13. c. (Kit 8)
14. Any two of: `handleError` now sees all errors; enhanced form failures return real status codes; enhanced cross-page forms navigate; external redirects need `{ external: true }`; CSRF always on in production; `ORIGIN` removed. (Kit 20)
15. When you want stable APIs (remote functions are experimental), or page-bound forms that are already working; or when a team policy avoids experimental features. (Kit 6)
