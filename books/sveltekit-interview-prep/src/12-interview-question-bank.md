# Interview Question Bank

Short model answers to the questions most likely to come up. They are written to be **said aloud in under a minute**. Do not memorise them word for word; make sure you could give the same points in your own words, then add an example from your experience.

## Svelte 5

**1. How does reactivity work in Svelte 5?**
Svelte compiles components to JavaScript that uses a small signals runtime. `$state` creates signals (or deep proxies for objects and arrays), `$derived` creates lazily computed values, and template expressions become effects that subscribe to exactly what they read. A component function runs once; later, only the effects whose dependencies changed re-run. No virtual DOM, no component re-render.

**2. What are runes?**
Compiler keywords that start with `$`: `$state`, `$derived`, `$effect`, `$props`, `$bindable`, `$inspect`, `$host`. They only work in `.svelte` and `.svelte.ts`/`.js` files. They replaced Svelte 4’s implicit reactivity (`let`, `$:`, `export let`) with explicit, portable reactivity that also works outside components.

**3. `$derived` versus `$effect`?**
`$derived` computes a value from other state. It is pure, lazy and memoised. `$effect` performs a side effect after the DOM updates, only in the browser. If you are assigning state inside an effect, you almost always wanted a `$derived`. Effects are for talking to the outside world: DOM APIs, timers, subscriptions, logging.

**4. When should you not use `$effect`?**
To derive values (use `$derived`), to respond to user actions (use the event handler), to sync props into state (use `$derived` or a writable derived), or to sync two inputs (use a function binding). Overusing effects causes extra renders, ordering bugs and infinite loops.

**5. How do components communicate?**
Props down; callback props up (`onchange`); `$bindable` props for explicit two-way binding; context for a subtree; shared `.svelte.ts` state for wider sharing, but not per-user state on the server.

**6. What are snippets?**
Reusable chunks of markup declared with `{#snippet name(args)}` and rendered with `{@render name(args)}`. They replace slots: content between component tags becomes the `children` snippet, and named snippets are just props. Because they take arguments, they also replace slot props.

**7. Deep reactivity: what gets proxied?**
Plain objects and arrays in `$state` become deep proxies, so `todo.done = true` and `items.push(x)` are reactive. Class instances, `Map`, `Set` and `Date` are not proxied: use `$state` fields in classes and `SvelteMap`/`SvelteSet`/`SvelteDate`. Use `$state.raw` for large data that you replace rather than mutate.

**8. Why key an each block?**
So Svelte can match DOM nodes and component state to items by identity. Without a key (or with the index), deleting or reordering items reuses nodes by position, so focus, input values, component state and transitions attach to the wrong item.

**9. What runs on the server during SSR?**
The script, `$state` and `$derived`, the markup, and `onDestroy`. Effects, `onMount`, actions, attachments and event handlers do not. Browser APIs therefore belong in effects, `onMount` or event handlers.

**10. What is hydration, and what causes mismatches?**
The browser takes server-rendered HTML and attaches the client-side behaviour to it rather than re-creating it. Mismatches happen when the client renders something different from the server: random values, dates, reading `window` or `localStorage` during render. Text mismatches are repaired; structural ones are re-mounted with a warning.

**11. Context versus a module-level store?**
Context is scoped to a component tree, so it is per request during SSR and per instance on the client. A module-level store is a singleton for the whole process, which on a server is shared by every user. Use context for anything per user or per request; module state only for browser-only global state.

**12. What changed from Svelte 4 to 5, in brief?**
Runes instead of implicit reactivity; callback props instead of `createEventDispatcher`; event attributes (`onclick`) instead of `on:click`; snippets instead of slots; components are functions mounted with `mount`; fine-grained signals instead of compile-time dirty checking; attachments in addition to actions.

## SvelteKit

**13. What is SvelteKit?**
The application framework for Svelte: filesystem routing, data loading, form handling, server endpoints, SSR, prerendering and an adapter system for deployment, all built on Vite and web standards (`Request`/`Response`). The first page load is server-rendered; later navigations are client-side.

**14. Universal versus server `load`?**
Universal `load` (`+page.ts`) runs on the server for SSR and in the browser for navigations; use it for public APIs and non-serialisable values. Server `load` (`+page.server.ts`) only runs on the server; use it for databases, secrets, cookies and `locals`. Its return value is serialised and sent to the browser, so return only what the page needs.

**15. When does a `load` function re-run?**
When something it read changes: params, the pathname, a search param it read, its parent’s data if it awaited `parent()`; when a dependency it declared with `depends()` is invalidated (or, in a universal load, a URL it fetched); or when `refreshAll()` runs (after actions with `use:enhance`, for instance).

**16. How do form actions work?**
A `<form method="POST">` posts to the page; the matching action in `+page.server.ts` runs, then the loads re-run and the page renders with the action’s result in the `form` prop. Validation failures use `return fail(400, data)`. It works without JavaScript; `use:enhance` adds a fetch-based submission without reloading.

**17. What is progressive enhancement?**
Building the feature on plain HTML (links and forms that work without JavaScript), then improving it when JavaScript is available. In SvelteKit: form actions plus `use:enhance`, and links that work with or without the client router. You can prove it with a Playwright test that disables JavaScript.

**18. What are hooks?**
App-wide functions. `handle` wraps every dynamic server request (middleware: auth, headers, logging); `handleFetch` modifies server-side `fetch`; `handleError` logs errors and shapes what users see; `init` runs at startup; `reroute` changes URL-to-route mapping; `transport` serialises custom types.

**19. What is `event.locals`?**
A per-request object on the server, typed by `App.Locals`. Typically `handle` validates the session cookie and sets `locals.user`, and loads, actions and endpoints read it.

**20. How do you protect a route?**
Validate the session in `handle` and set `locals.user`. Redirect anonymous users from protected paths in `handle`, and also check authorisation where the data is read (server loads, actions, endpoints, remote functions). A guard only in a layout load is not enough, because page loads run in parallel with it.

**21. How are errors handled?**
`error(status, message)` throws an expected error whose message is shown; anything else is unexpected and shows a generic message. Both go through `handleError`, where you log and return a safe error object. The nearest `+error.svelte` renders it; errors in the root layout’s load or in `handle` fall back to `error.html`.

**22. SSR, CSR, prerendering, SPA: how do you choose?**
Per route, with page options. Prerender pages that are the same for everyone (marketing, docs). SSR dynamic, personalised or SEO-relevant pages. `ssr = false` (SPA) only for app areas that cannot be server-rendered. `csr = false` for pages that need no JavaScript at all.

**23. Why is module-level state dangerous in SvelteKit?**
The server process handles requests from many users. Anything stored at module level during a request is visible to the next request, possibly from another user. Use `locals`, `getRequestEvent()`, context or the returned `data` instead.

**24. Where should filter or pagination state live?**
In the URL: it survives reloads, can be shared, is available to SSR and loads, and the Back button works. Read it from `url.searchParams` in load (or `page.url`), and update it with links, GET forms or `goto`.

**25. How do environment variables work in SvelteKit 3?**
They are declared in `src/env.ts` with `defineEnvVars`, each marked public or private and static (inlined at build) or dynamic (read at startup), optionally with a validation schema. Read them from `$app/env/private` (server-only) or `$app/env/public`. The `$env/*` modules from SvelteKit 2 still work but are deprecated.

**26. What is an adapter?**
A plugin that turns the build into something a platform can run: a Node server, serverless functions for Vercel or Netlify, a Cloudflare Worker, or static files. It maps the platform’s requests onto SvelteKit’s `server.respond(Request)`.

**27. What is new in SvelteKit 3?**
Configuration in `vite.config.ts` instead of `svelte.config.js`; `#lib` subpath imports instead of `$lib`; `$app/stores` removed in favour of `$app/state`; explicit environment variables in `src/env.ts`; `resolve()` instead of `base`; one `src/params.ts`; shallow routing through `goto`; `refreshAll`; `handleError` sees every error; stable tracing. It requires Node 22.17 or later, Vite 8, TypeScript 6 and Svelte 5.57. Remote functions are still experimental.

**28. What are remote functions?**
Experimental, type-safe server functions defined in `*.remote.ts` files: `query` for reads, `form` for progressively enhanced forms, `command` for programmatic mutations and `prerender` for build-time data. You call them from components like normal functions; SvelteKit generates the HTTP endpoints. Every argument must be validated and every function must do its own authorisation.

**29. How does SvelteKit help with performance?**
SSR for fast first paint, per-route code-splitting, `modulepreload`, preloading data and code on link hover, one batched data request per navigation, inlining fetches from SSR so the client does not refetch, and streaming of promises from server loads. The main thing you can break is creating waterfalls.

**30. What does SvelteKit do against CSRF and XSS?**
In production it rejects cross-origin form-encoded POST/PUT/PATCH/DELETE requests by checking the `Origin` header. Svelte escapes interpolated values, so XSS comes from `{@html}`, unsafe URLs and third-party scripts. A CSP can be configured with automatic nonces or hashes.

## Testing

**31. How do you test a SvelteKit app?**
A pyramid: many fast Vitest unit tests for logic, `.svelte.ts` classes, loads, actions and endpoints (most of them in Node); component tests in Vitest browser mode with `vitest-browser-svelte` for behaviour in a real browser; a few Playwright end-to-end tests of critical journeys against the production build, including a no-JavaScript run for forms. Plus `svelte-check` and a build in CI.

**32. How do you test a component?**
Render it with props, interact like a user (click, type) using role-based locators, and assert what the user sees and which callbacks were called. Avoid testing implementation details or snapshotting markup.

**33. How do you test a load function or action?**
Import it and call it with a partial event: a `Request` with `FormData` for actions, `params` and a fake `fetch` for loads. Assert the return value, `isActionFailure`, or thrown redirects and errors with `isRedirect`/`isHttpError`. Mock `$app/server` if the code uses `getRequestEvent()`.

**34. Why run e2e tests against a production build?**
Because that is what ships: bundling, SSR plus hydration, preload tags and the real server. `vite dev` behaves differently (no bundling, on-demand compilation, no CSRF check).

**35. What makes e2e tests flaky in SvelteKit, and how do you avoid it?**
Acting before hydration, fixed sleeps, non-isolated test data and ambiguous locators. Use web-first assertions that retry, assert on outcomes, use unique role-based locators, isolate data per test, and wait for a hydration marker if needed.

**36. How would you test an `$effect`?**
Ideally, move the logic into a function and test that. Otherwise, create it inside `$effect.root`, call `flushSync()` to run pending effects after each change, assert, and call the cleanup returned by `$effect.root`.

## Working with Claude Code

**37. How do you use an AI assistant on a Svelte 5 codebase?**
Give it the conventions explicitly (a `CLAUDE.md` with runes-only, SvelteKit 3 imports, test naming), work in small steps with acceptance criteria, review every diff for outdated syntax and weak tests, and always run the tests and type check myself. The assistant writes code; I remain responsible for it.

**38. What do you check in AI-generated tests?**
That they test behaviour rather than implementation, would fail if the feature broke (I break it once to check), use role-based locators, await every interaction, avoid sleeps, and are named so the runner picks them up in the right environment.
