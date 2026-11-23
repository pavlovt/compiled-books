# Day 5: Hooks, Errors, Rendering Modes, State and Environment

**Goal for today:** write a `handle` hook that sets `locals`, explain how errors are rendered, choose SSR/CSR/prerendering per route, and avoid the shared-server-state trap.

## Read (45 min)

1. **Kit 9**, “9.1 The three hook files”, “9.2 `handle`” (to “Responsibilities”), “9.3 `sequence`”, “9.4 `event.locals`”, “9.9 What hooks do not intercept”.
2. **Kit 10**, “10.1 The four error kinds”, “10.2 Control flow helpers”, “10.3 `handleError`” (first page), “10.4 Rendering an error”.
3. **Kit 11**, “The model: four independent switches”, “Choosing a rendering mode per route”, “`prerender`” (first page), “`ssr`”, “`csr`”, “SPA mode and the fallback page” (first page).
4. **Kit 12**, “Server state: the shared-process hazard”, “Client state: runes, modules and context”, “URL state”, “`$app/state`”, “Navigation lifecycle”.
5. **Kit 13**, “Declaring variables: `src/env.ts`”, “Consuming variables”, “Static versus dynamic” (first page), “Server-only modules”.

## Core notes (20 min)

### Hooks

| File | Hooks |
|---|---|
| `src/hooks.server.ts` | `handle`, `handleFetch`, `handleError`, `init` |
| `src/hooks.client.ts` | `handleError`, `init` |
| `src/hooks.ts` (universal) | `reroute`, `transport` |

```ts
// src/hooks.server.ts
import type { Handle } from '@sveltejs/kit/hooks';   // SvelteKit 3; was '@sveltejs/kit' in 2
import { sequence } from '@sveltejs/kit/hooks';

const auth: Handle = async ({ event, resolve }) => {
	const sid = event.cookies.get('sid');
	event.locals.user = sid ? await getUserBySession(sid) : null;
	return resolve(event);
};

const headers: Handle = async ({ event, resolve }) => {
	const response = await resolve(event);
	response.headers.set('x-content-type-options', 'nosniff');
	return response;
};

export const handle = sequence(auth, headers);
```

- `handle` is **middleware** around every dynamic request: pages, `__data.json` data requests, actions, `+server` endpoints, remote calls. Code before `resolve(event)` runs on the way in; code after it can change the response.
- It does **not** see static files or prerendered pages, which the adapter or CDN serves directly.
- `event.locals` is per-request, server-only context (type it in `app.d.ts` as `App.Locals`). The usual pattern: authenticate in `handle`, set `locals.user`, read it in loads, actions and endpoints.
- `sequence(a, b, c)`: the “before” parts run a → b → c, the “after” parts run c → b → a.
- `handleFetch` intercepts `event.fetch` calls on the server (rewrite URLs, add credentials). `reroute` maps a URL to a different route without changing the address bar.
- `handle` does **not** re-run after an action. If an action logs the user in, update `event.locals` yourself or redirect.

### Errors

- **Expected errors**: `error(404, 'Not found')`. The message is shown to the user.
- **Unexpected errors**: anything else thrown. The user sees a generic message (“Internal Error”); the details go to `handleError` only. Never leak stack traces.
- `handleError({ kind, error, issues, event })` is where you log and report, and it returns the safe `App.Error` the user sees. In SvelteKit 3 it sees **all** errors (in 2.x, `error()` errors skipped it), with a `kind` of `'app'`, `'framework'`, `'validation'` or `'unknown'`, and it may return a custom `status`. It must never throw.
- Rendering: the nearest `+error.svelte` **above** the failing node renders, reading `page.error` and `page.status` from `$app/state`. An error in the root layout, in `handle` or in a `+server` endpoint cannot use `+error.svelte`: the static `src/error.html` (or JSON for API clients) is used instead.
- Shape your errors with `App.Error` in `app.d.ts` (for example add `errorId`).
- Inside a component, `<svelte:boundary>` with a `failed` snippet catches rendering errors for a region.

### Page options: rendering per route

Export these from `+page.ts`/`+layout.ts` (or the `.server` versions). They inherit down the tree; the nearest definition wins.

| Option | Effect |
|---|---|
| `export const prerender = true` | Render to static HTML at build time. All users must get the same HTML. Pages with actions cannot be prerendered. `'auto'` prerenders but keeps the route dynamic too |
| `export const ssr = false` | No server rendering: an empty shell, everything runs in the browser (SPA) |
| `export const csr = false` | No JavaScript shipped: no hydration, no client router, no `use:enhance` |
| `export const trailingSlash = 'always'` | URL normalisation |

- **SPA mode:** `ssr = false` in the root layout, plus `adapter-static` with a `fallback` page.
- **Static site:** `adapter-static` and `prerender = true` in the root layout.
- The senior answer: decide per route. Prerender marketing pages, SSR the dashboard, SPA only what must be.
- Browser-only code at module level (`window.x` at the top of a module) breaks SSR. Move it to `onMount`/`$effect`, or guard with `browser` from `$app/env`.

### State: the shared-server trap

- A Node server process serves **many users**. Module-level variables are shared by all of them. `export const user = $state(...)` in a module, written during SSR, **leaks one user’s data to another**.
- Keep `load` functions pure: return data, never write to globals or stores.
- Per-request server state: `event.locals`, or `getRequestEvent()` from `$app/server`. Per-tree client state: context. Browser-only singletons: a module, but only if it is written exclusively in the browser.
- **URL state:** filters, sorting and pagination belong in the URL (`?q=…&page=2`). It survives reloads, can be shared, and is available to SSR. Update it with a GET form, or with `goto(url, { replace: true, reset: false })` in SvelteKit 3: `replace` swaps the history entry (so Back does not step through every keystroke) and `reset: false` keeps scroll and focus. The SvelteKit 2 options `replaceState`, `noScroll` and `keepFocus` were changed or removed in 3.0.
- **Page state / shallow routing:** `goto('', { shallow: true, state: { showModal: true } })` and `page.state.showModal`, for modals that close on Back. It replaces `pushState`/`replaceState`.
- `$app/state` exports `page` (url, params, route, data, form, status, error, state), `navigating` (`navigating.to` during a navigation) and `updated`. Use them as plain objects: `page.url.pathname`, no `$`.
- `beforeNavigate` (can cancel), `onNavigate` (view transitions), `afterNavigate`.

### Environment variables (SvelteKit 3)

```ts
// src/env.ts
import { defineEnvVars } from '@sveltejs/kit/env';

export const variables = defineEnvVars({
	DATABASE_URL: { description: 'Postgres connection string' },          // private, dynamic
	PUBLIC_API_BASE: { public: true, static: true }                         // public, inlined at build
});
```

```ts
import { DATABASE_URL } from '$app/env/private';  // server-only module
import { PUBLIC_API_BASE } from '$app/env/public'; // usable anywhere
```

- Exposure is explicit (`public: true`), not decided by a `PUBLIC_` prefix.
- **Static** values are inlined at build time; **dynamic** values are read when the server starts (one build, many environments). Secrets should be dynamic.
- Invalid values fail the build (static) or startup (dynamic) when you add a `schema`.
- SvelteKit 2 equivalents (`$env/static/private`, `$env/dynamic/public`…) still work in 3 but are deprecated.

### Server-only modules

`$app/env/private`, `$app/server`, any file named `*.server.ts`, and anything inside a `server/` directory (such as `src/lib/server/`) cannot be imported by code that reaches the browser. The **build fails** if they are. Note: Vitest disables this check, so only a build catches a violation.

## Hands-on (40 min)

1. Add `src/hooks.server.ts` with a `handle` that reads a `name` cookie and sets `event.locals.name` (type it in `app.d.ts`), plus a second handle that adds an `x-request-id` response header. Combine them with `sequence`.
2. Show `locals.name` on a page through a `+layout.server.ts` load.
3. Throw `error(404, 'No such item')` from a load and add a `+error.svelte` that shows `page.status` and `page.error?.message`. Then throw a plain `new Error('boom')` and compare what the user sees.
4. Add `export const prerender = true` to the `/about` page and run `npm run build`. Find the HTML file in the build output.
5. Make the todo filter from Day 2 URL-driven: read `page.url.searchParams.get('filter')` and switch filters with links (`?filter=done`).

## Quiz (15 min)

1. Which requests pass through `handle`, and which never do?
2. What is `event.locals`, where is it typed, and what is the standard auth pattern built on it?
3. With `sequence(a, b)`, in what order do the parts before and after `resolve` run?
4. What is the difference between an expected and an unexpected error from the user’s point of view?
5. A `+layout.server.ts` at the root throws. Which error page renders?
6. What changed about `handleError` in SvelteKit 3?
7. Explain `prerender`, `ssr` and `csr`. What does a route with `csr = false` lose?
8. Why can’t a page with form actions be prerendered?
9. **Find the bug** (adapter-node, many users):

   ```ts
   // src/lib/server/current-user.ts
   let currentUser: User | null = null;
   export const setUser = (u: User | null) => (currentUser = u);
   export const getUser = () => currentUser;
   // hooks.server.ts calls setUser(...) on every request
   ```

10. Where should the state of a product list’s filters and sort order live, and why?
11. How do you open a modal that closes when the user presses Back, in SvelteKit 3?
12. Multiple choice: in a SvelteKit 3 component, how do you show a spinner during navigation?

    a. `{#if $navigating}`
    b. `{#if navigating.to}` with `navigating` from `$app/state`
    c. `{#if page.loading}`
    d. `{#if $page.navigating}`

13. What is the difference between a static and a dynamic environment variable, and which should a database password be?
14. You import `#lib/server/db.js` from a `+page.svelte`. What happens, and why might your unit tests not notice?
15. In SvelteKit 3, how do you declare a public environment variable, and how is that different from SvelteKit 2?
