# Day 3: SvelteKit Foundations: Architecture, Project Structure and Routing

**Goal for today:** describe what SvelteKit is and how a request flows through it, name every route file and when it runs, and build a few routes with parameters, layouts and an endpoint.

## Read (45 min)

1. **Kit 1**, “The three layers”, “Creating a project with `sv`”, “Configuration in SvelteKit 3”, “`#lib`, `$app/*` and TypeScript plumbing” (first half), “Project structure and reserved files”, “Version requirements and the stability map”, “A mental model to carry forward”.
2. **Kit 3**, “The route tree and route IDs”, “Route files, in the order of the request”, “Route parameters”, “Matchers and `src/params.ts`”, “Layouts”, “`$app/paths`”, “Content negotiation between pages and `+server`”.
3. *Skim* **Kit 2**, “The kinds of requests”, “Inside `respond`: the ordered pipeline”, “The client: a navigation, step by step”.

## Core notes (20 min)

### What SvelteKit is, in three layers

1. **Svelte** compiles `.svelte` files to JavaScript.
2. **A Vite plugin** (`sveltekit()` in `vite.config.ts`) scans `src/routes`, generates the route manifest and types (`./$types`), and builds the server and client bundles.
3. **An adapter** turns that platform-neutral build into something deployable (Node, Vercel, Netlify, Cloudflare, static files). It maps the platform onto one function: `server.respond(Request) → Response`.

SvelteKit never owns the HTTP server. Everything is web standards: `Request`, `Response`, `Headers`, `FormData`, `URL`.

**The default experience:** the first request is server-rendered (SSR), the browser then **hydrates**, and further navigations are client-side: the router fetches only the data (`__data.json`) and code it needs. You can change this per route (Day 5).

### SvelteKit 3 versus 2: the visible changes

| SvelteKit 2 | SvelteKit 3 |
|---|---|
| `svelte.config.js` with `kit: {…}` | Options passed to `sveltekit({...})` in `vite.config.ts`; `svelte.config.js` is unsupported |
| `$lib/…` alias | `#lib/…` via `package.json` `"imports"` (Node subpath imports), with file extensions |
| `$app/stores` (`$page`) | `$app/state` (`page`, `navigating`, `updated`) as plain reactive objects |
| `$env/static/private` and friends | Declared in `src/env.ts` with `defineEnvVars`, read from `$app/env/private`/`public` (old modules deprecated) |
| `$app/environment` (`browser`, `dev`, `building`) | `$app/env` (old module deprecated) |
| `base`, `assets`, `resolveRoute` from `$app/paths` | `resolve()`, `match()`, `asset()` |
| `src/params/*.js`, one matcher per file | One `src/params.ts` with `defineParams` |
| `pushState`/`replaceState` | `goto(url, { shallow: true, state })` |
| `invalidateAll()` | `refreshAll()` |
| Node 18+, Vite 5–7 | Node 22.17+, Vite 8, TypeScript 6, Svelte 5.57+ |

Remote functions (Day 7) remain **experimental** in 3.x and need two flags.

### Project structure

```text
src/
  app.html            # HTML shell: %sveltekit.head%, %sveltekit.body%
  app.d.ts            # App.Locals, App.PageData, App.Error, App.PageState
  hooks.server.ts     # handle, handleFetch, handleError, init
  hooks.client.ts     # handleError, init
  hooks.ts            # reroute, transport (universal)
  params.ts           # route matchers
  env.ts              # environment variable declarations
  lib/                # imported as #lib/...
    server/           # server-only: cannot be imported by client code
  routes/             # the filesystem router
static/               # served as-is
vite.config.ts        # sveltekit({ adapter, ... })
```

Only `src/routes` and `src/app.html` are mandatory.

### Route files

A route is a directory under `src/routes`. The files in it:

| File | Runs | Purpose |
|---|---|---|
| `+page.svelte` | Server (SSR) and browser | The page component; receives `data` (and `form`) as props |
| `+page.ts` | Server (SSR) and browser | Universal `load` |
| `+page.server.ts` | Server only | Server `load` and form `actions` |
| `+layout.svelte` | Both | Wraps child routes; renders `{@render children()}` |
| `+layout.ts` / `+layout.server.ts` | As above | Layout `load` |
| `+error.svelte` | Both | Error boundary for this subtree |
| `+server.ts` | Server only | An API endpoint: export `GET`, `POST`, `PUT`, `PATCH`, `DELETE`… returning a `Response` |

Types come from the generated `./$types`: `PageProps`, `PageLoad`, `PageServerLoad`, `Actions`, `LayoutProps`, `RequestHandler`.

```html
<!-- src/routes/blog/[slug]/+page.svelte -->
<script lang="ts">
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
</script>

<h1>{data.post.title}</h1>
```

### Parameters

| Directory | Matches | `params` |
|---|---|---|
| `blog/[slug]` | `/blog/hello` | `{ slug: 'hello' }` |
| `[[lang]]/about` | `/about` and `/en/about` | `{ lang?: string }` |
| `files/[...path]` | `/files/a/b/c` (zero or more segments) | `{ path: 'a/b/c' }` |
| `items/[id=number]` | `/items/12` only if the matcher accepts | `{ id: 12 }` (typed by the matcher) |

```ts
// src/params.ts (SvelteKit 3)
import { defineParams } from '@sveltejs/kit/params';

export const params = defineParams({
	number: (param) => (/^(0|[1-9]\d*)$/.test(param) ? Number(param) : undefined)
});
```

- Matchers return a value, or `undefined` for “no match”. They must be synchronous and they run on both server and client. A failing matcher does not produce a 404 by itself: routing falls through to the next route, and to a 404 if nothing matches.
- **Sorting:** more specific routes win (`/blog/new` beats `/blog/[slug]`), routes with matchers beat routes without, and rest/optional parameters come last.

### Layouts and groups

- Layouts nest by directory. `src/routes/+layout.svelte` wraps everything.
- **Groups** `(app)` and `(marketing)` are directories in parentheses: they share a layout without appearing in the URL.
- `+page@.svelte` or `+page@(app).svelte` “breaks out” to the root or a named ancestor layout.
- Layout `load` is **not** an authorisation mechanism: page loads run in parallel with it (Day 5 and Day 7).

### `+server.ts`

```ts
// src/routes/api/echo/+server.ts
import { error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

export const POST: RequestHandler = async ({ request }) => {
	const body = await request.json().catch(() => null);
	if (!body || typeof body.name !== 'string') error(400, 'name required');
	return Response.json({ hello: body.name });
};
```

- Return a standard `Response`. In SvelteKit 3 the `json()`/`text()` helpers are deprecated in favour of `Response.json()` and `new Response()`.
- A `+server.ts` and `+page.svelte` can live in the same directory. `GET`/`POST`/`HEAD` go to the page when the client’s `Accept` header prefers HTML; `PUT`/`PATCH`/`DELETE` always go to the endpoint.

### Links and navigation

- Plain `<a href>` links are intercepted by the client router. `goto(url)` from `$app/navigation` navigates programmatically.
- `resolve('/blog/[slug]', { slug })` from `$app/paths` builds a typed URL (and prefixes the base path). An unknown route ID is a type error.
- `data-sveltekit-preload-data="hover"` (the scaffold puts it on `<body>`) starts loading data when the user hovers a link.

## Hands-on (40 min)

1. Create `src/routes/blog/+page.svelte` (a list of three hard-coded slugs, linked with `resolve`) and `src/routes/blog/[slug]/+page.svelte` that shows `page.params.slug` (import `page` from `$app/state`).
2. Add `src/params.ts` with a `number` matcher and a route `src/routes/items/[id=number]/+page.svelte`. Visit `/items/12` and `/items/abc`.
3. Add a group `src/routes/(marketing)/about/+page.svelte` with its own `+layout.svelte`. Check that the URL is `/about`.
4. Add the `/api/echo` endpoint above and call it from the browser console with `fetch('/api/echo', { method: 'POST', body: JSON.stringify({ name: 'x' }) })`.
5. Run `npm run check`. Fix any type errors.

## Quiz (15 min)

1. Name the three layers of a SvelteKit app and what each one does.
2. What happens on the first request to a SvelteKit app, and what happens on the next client-side navigation?
3. Where does configuration live in SvelteKit 3? What happened to `$lib`?
4. Which files in a route directory run only on the server?
5. What URL(s) does each match: `[[lang]]/about`, `docs/[...path]`, `(shop)/cart`?
6. Write a matcher that accepts only positive integers and makes `params.id` a number.
7. A `[id=number]` matcher rejects `/items/abc`. Does the user get a 404 immediately? Explain.
8. Both `src/routes/blog/new/+page.svelte` and `src/routes/blog/[slug]/+page.svelte` exist. Which renders for `/blog/new`?
9. What is a layout group, and why would you use one?
10. You have `+page.svelte` and `+server.ts` in the same directory. Where does a browser `GET` go? Where does a `DELETE` go?
11. Multiple choice: in SvelteKit 3, which import gives you the current page’s URL and params in a component?

    a. `import { page } from '$app/stores'`
    b. `import { page } from '$app/state'`
    c. `import { page } from '$app/navigation'`
    d. `import { getPage } from '@sveltejs/kit'`

12. What does `resolve()` from `$app/paths` do, and what two SvelteKit 2 exports did it replace?
13. Name three changes between SvelteKit 2 and 3 that would show up in a code review of old code.
14. Why does SvelteKit generate a `./$types` module per route, and what makes it appear?
15. What does `+page@.svelte` do?
