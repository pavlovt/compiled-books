# Chapter 3: Routing in Depth

Routing is the part of SvelteKit that looks simplest and hides the most design decisions. The surface is a directory tree. Underneath it sits a route grammar (dynamic, optional and rest parameters, matchers, groups and escapes), a deterministic sort that decides which route wins when several match, a layout hierarchy that is deliberately not identical to the URL hierarchy, a typed API (`$app/paths`) for building URLs that round-trip through the same grammar, a content negotiation rule that lets one path be both a page and an API, and two hooks and two options (`reroute`, `router.resolution`, `router.type`, `trailingSlash`) that change how URLs map to routes. This chapter covers all of it at the level you need to design a route tree for a large application, to debug “why did that URL render the wrong page”, and to know exactly what is guaranteed on the server versus the client. It builds on the lifecycle model of Chapter 2: route matching is step 10 of `respond`, normalisation redirects are step 11, and neither is visible to `handle`.

Several behaviours in this chapter were confirmed by building a project against SvelteKit 3.1.0 and requesting URLs with `curl`; where an example shows output, that is real output.

## The route tree and route IDs

Every directory under `src/routes` that contains route files is a route. Its **route ID** is the directory path relative to `src/routes`, with `/` at the root, for example `/`, `/blog/[slug]`, `/(app)/dashboard` or `/docs/[...path]`. Groups appear in the ID; they simply do not appear in the URL. The route ID is the stable identifier you will see in `event.route.id`, `page.route.id`, `$app/types`’ `RouteId` and in `resolve()`.

Three properties of the tree matter for design:

1.  **Route files are `+`-prefixed.** Everything else in a route directory is ignored, so you may colocate components, utilities and tests. Files whose name after the `+` contains `.test.`, `.spec.` or `.stories.` are also ignored (for example `+page.spec.ts`). A non-`+` file that looks like a route file gets a warning with the corrected name; a `+`-prefixed file with an unknown name is an error (`Files prefixed with + are reserved`).
2.  **Only `.js`/`.ts` (the `moduleExtensions` option) and `.svelte` files count as route modules.** Two files of the same kind in one directory (for example `+page.ts` and `+page.js`) are an error.
3.  **A route needs a `+page` or `+server` to be matchable.** A directory with only a `+layout.svelte` is not a route; it is a node in the layout chain of its descendants. This is why `manifest_data.routes` contains entries that never reach `event.route.id`.

The build also detects **route conflicts**. Two routes conflict if, after removing groups and expanding optional parameters, they would match the same set of URLs in the same position, for example `src/routes/[a]/+page.svelte` and `src/routes/[b]/+page.svelte`, or `src/routes/(x)/about/+page.svelte` and `src/routes/(y)/about/+page.svelte`. The error reads `The "/(x)/about" and "/(y)/about" routes conflict with each other`. This is a useful guarantee: if the app builds, no two routes are indistinguishable (matchers do not count; `[a=x]` and `[b=y]` at the same level are still reported as the same *shape*, except that matchers affect the sort, covered below).

> **Note:** If a route has both a `+page` and a `+server`, any page options they export (`prerender`, `trailingSlash`, `config`) must agree, or the build fails with a “Mismatched route config” error. Chapter 11 covers the options themselves; the routing consequence is that a page and an endpoint on the same path are one route with one configuration.

## Route files, in the order of the request

Chapter 1 listed the files. The behaviours that matter when you design routes are these.

### `+page.svelte`, `+page.ts`, `+page.server.ts`

A page component receives `data` (the merged result of all `load` functions in the chain), `form` (the last action result, when the page has actions) and, since 2.24, `params`. Type all of them with `PageProps` from `./$types`:

```html
<!-- src/routes/blog/[slug]/+page.svelte -->
<script lang="ts">
    import type { PageProps } from './$types';

    let { data, params }: PageProps = $props();
</script>

<h1>{data.title}</h1>
<p>Slug from the URL: {params.slug}</p>
```

`+page.ts` exports a universal `load` (runs on the server during SSR and in the browser afterwards) and page options. `+page.server.ts` exports a server `load`, `actions`, and the same options. You can have both; the server load’s result is handed to the universal load as `data`. Chapter 4 covers loading.

When navigating between two pages that share a layout, SvelteKit keeps the shared layout component instances alive and replaces only the part of the tree that differs. If you navigate between two URLs of the *same* route (for example `/blog/a` to `/blog/b`), the page component is **not** recreated either: its `data` and `params` props update. This is the single most common source of “stale state” bugs in routing; derive from props with `$derived`, or key the component:

```html
{#key params.slug}
    <Comments slug={params.slug} />
{/key}
```

### `+layout.svelte` and its loads

A layout must render its children with `{@render children()}`. A layout’s `data` contains only what *its* `+layout(.server).ts` returned plus its ancestors’ layout data (not the page’s). Child layouts and pages see all ancestor layout data, the page can also see sibling-layout merges via `page.data` from `$app/state`. Data merge order is root to leaf, so later keys win.

The compile step warns if a `+layout.svelte` never renders `children`, and warns if a page option such as `export const ssr` is placed inside a `.svelte` file rather than in `+page.ts`.

### `+error.svelte`

`+error.svelte` is a boundary. When a `load` function throws, SvelteKit looks for the nearest `+error.svelte` at or above the directory of the failing page, but for a failing *layout* load, the nearest boundary **above that layout’s directory**, because the layout itself did not render. If none exists up to `src/routes/+error.svelte`, or the error is in the root layout, `src/error.html` is rendered. It is not used for errors in `handle` or `+server`. Chapter 10 treats this in depth.

An important routing subtlety: a nested `+error.svelte` is only reachable if a route *matched*. A URL that matches no route never enters the tree, so it uses the root `+error.svelte` (or the built-in page). The documented remedy is a rest route that always errors:

```ts
// src/routes/marx-brothers/[...path]/+page.ts
import { error } from '@sveltejs/kit';
import type { PageLoad } from './$types';

export const load: PageLoad = () => {
    error(404, 'Not Found');
};
```

With `src/routes/marx-brothers/+error.svelte` present, `/marx-brothers/karl` now renders the nested boundary (with the `marx-brothers/+layout.svelte`, if any, around it). Without a handler like this, an unmatched URL appears in `handleError` with `kind: 'framework'`; with it, the 404 is an `error()` and appears with `kind: 'app'`.

### `+server.ts`

A `+server.ts` exports functions named after HTTP methods: `GET`, `POST`, `PATCH`, `PUT`, `DELETE`, `OPTIONS`, `HEAD`, and (new) `QUERY`; plus `fallback` for any other method. Each handler receives a `RequestEvent` and must return a `Response`:

```ts
// src/routes/api/random-number/+server.ts
import { error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = ({ url }) => {
    const min = Number(url.searchParams.get('min') ?? '0');
    const max = Number(url.searchParams.get('max') ?? '1');
    const d = max - min;

    if (Number.isNaN(d) || d < 0) {
        error(400, 'min and max must be numbers, and min must be less than max');
    }

    return Response.json(min + Math.random() * d);
};
```

Rules worth knowing:

- Returning a plain object is an error; return a `Response`. Prefer `Response.json(...)` and `new Response(...)`; the `json()` and `text()` helpers from `@sveltejs/kit` are deprecated.
- The first argument to `Response` may be a `ReadableStream`, which is how you implement downloads and server-sent events, unless the platform buffers (Lambda-style adapters).
- If a `GET` export exists, a `HEAD` request is answered with the `GET` handler’s `content-length`, and `GET` wins over `fallback` for `HEAD`.
- `fallback` handles everything that has no dedicated export, including custom methods such as `MOVE`.
- Errors thrown from a handler never render `+error.svelte`. You get a JSON error body or the `error.html` page depending on `Accept` (Chapter 10).
- `+layout` files have no effect on `+server` routes. Cross-cutting logic for endpoints belongs in `handle` (Chapter 9).
- `OPTIONS` handlers in development receive Vite’s injected CORS headers, which will not exist in production unless you add them. Kit configures Vite’s CORS middleware with `preflightContinue: true` so your `OPTIONS` handler is reached at all, and warns if your own `server.cors` settings prevent that.

> **Note:** Mutating requests are subject to CSRF protection in production: a cross-origin `PUT`/`PATCH`/`DELETE`/`POST` with a form-like content type (or no `Content-Type`) is rejected with a 403 before any handler runs. In our test, `curl -X PUT` with no `Origin` and no content type against the preview server returned `403 Forbidden` with the text `Cross-site PUT form submissions are forbidden`. For legitimate cross-origin callers, use `csrf.trustedOrigins` or send an explicit `application/json` content type.

## Route parameters

The route grammar is deliberately small. A directory name is one of: a literal, a dynamic segment `[name]`, an optional segment `[[name]]`, a rest segment `[...name]`, a matcher-restricted variant (`[name=matcher]`), or a mixture of literals and parameters within one segment.

### Dynamic, optional and rest

```text
src/routes/
├ blog/[slug]/+page.svelte            # /blog/hello          { slug: 'hello' }
├ [[lang]]/home/+page.svelte          # /home, /en/home      { lang?: 'en' }
├ [org]/[repo]/tree/[branch]/[...file]/+page.svelte
│                                      # /sveltejs/kit/tree/main/docs/a.md
├ a/[...rest]/z/+page.svelte          # /a/z, /a/b/z, /a/b/c/z  { rest: '' | 'b' | 'b/c' }
└ foo-[c]/+page.svelte                # /foo-abc             { c: 'abc' }
```

Details that trip people up:

- A rest segment matches **zero or more** segments. `a/[...rest]/z` matches `/a/z`, with `rest` equal to the empty string. Validate rest values with a matcher if emptiness would be an error.
- An optional parameter cannot follow a rest parameter (`[...rest]/[[opt]]`), because matching is greedy and the optional would never receive a value. `[[...rest]]` is an error as well (“a rest route segment is always optional”). Both are build errors.
- Two parameters must be separated by something. `[a][b]` is rejected (“parameters must be separated”); `[a]-[b]` is fine, and so is `[a].[b]`.
- Parameter and matcher names may contain only alphanumerics, underscores and hyphens, so `[post-id]` is valid and yields `params['post-id']`.
- Literal text may surround a parameter within a segment: `foo-[c]`, `[id].json` and `[year]-[month]` all work. The segment pattern is compiled into a regular expression, so the sort rules below treat such routes as more specific than a bare `[b]`.
- `params` values are always decoded (`decodeURIComponent`), so `%20` arrives as a space. `resolve()` does not re-encode them.

The `params` object is typed from the route ID in `./$types`. For `/[org]/[repo]/tree/[branch]/[...file]`, `RouteParams` is `{ org: string; repo: string; branch: string; file: string }`. Optional parameters become `lang?: string`.

### Groups and escapes

A directory name in parentheses, `(app)`, is a **group**: it contributes to the layout hierarchy and to the route ID, but not to the URL. A `+page` may sit directly in a group (`src/routes/(marketing)/+page.svelte` serves `/`). Groups are how you put different URL regions under different layouts, covered shortly.

Characters that are special in a filesystem, in URLs or in the route grammar are written as hexadecimal escapes, `[x+nn]`, or Unicode escapes, `[u+nnnn]`. Escapes must be lowercase and the hex form must be exactly two digits (`[x+3A]` and `[x+3]` are errors; so is a literal `#` in a directory name, with a message suggesting `[x+23]`). The most common practical uses:

```text
src/routes/smileys/[x+3a]-[x+29]/+page.svelte   # /smileys/:-)
src/routes/[x+2e]well-known/security.txt/+server.ts  # /.well-known/security.txt
```

The second form is worth remembering: TypeScript has trouble with directories that start with a dot, so `.well-known` routes are written with `[x+2e]`.

### A large-tree example

Consider a SaaS product with a marketing site, an authenticated app, a locale prefix and a documentation catch-all:

```text
src/routes/
├ (marketing)/
│ ├ +layout.svelte
│ ├ +page.svelte                     # /
│ ├ pricing/+page.svelte             # /pricing
│ └ blog/[slug]/+page.svelte         # /blog/:slug
├ (app)/
│ ├ +layout.server.ts                # auth guard for this subtree (see warning in Chapter 4)
│ ├ +layout.svelte
│ ├ dashboard/+page.svelte           # /dashboard
│ └ orgs/[org=slug]/
│   ├ +layout.server.ts              # loads org
│   ├ +page.svelte                   # /orgs/acme
│   └ settings/+page.svelte          # /orgs/acme/settings
├ docs/[...path]/+page.svelte        # /docs, /docs/a/b/c
├ api/
│ ├ orgs/[org=slug]/members/+server.ts
│ └ health/+server.ts
├ [x+2e]well-known/security.txt/+server.ts
├ +layout.svelte
└ +error.svelte
```

The route IDs here are `/(marketing)/blog/[slug]`, `/(app)/orgs/[org=slug]/settings`, `/docs/[...path]` and so on. Note that IDs include groups; any code that compares `page.route.id` to a string must include them.

## Matchers and `src/params.ts`

An unconstrained `[page]` matches anything, including strings you do not want. A **matcher** restricts and optionally transforms a parameter. In SvelteKit 3 all matchers live in one file, `src/params.ts`, as named exports of a single `params` object created with `defineParams`:

```ts
// src/params.ts
import { defineParams } from '@sveltejs/kit/params';
import * as v from 'valibot';

export const params = defineParams({
    // 1. A function: return a parsed value, or undefined for "no match"
    fruit: (param) => (['apple', 'orange'].includes(param) ? param : undefined),

    // 2. A function that also transforms
    number: (param) => (/^\d+$/.test(param) ? Number(param) : undefined),

    // 3. Any Standard Schema (valibot, zod, arktype)
    slug: v.pipe(v.string(), v.regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/)),
    uuid: v.pipe(v.string(), v.uuid())
});
```

The export name must be `params`. A directory then references a matcher by `=name`: `src/routes/items/[id=number]/+page.svelte`. The old design, one file per matcher under `src/params/*.js` exporting `match`, is gone; the old truthy/falsy contract (which could not transform) is replaced by “return a value or `undefined`”.

The rules, from the source:

- A matcher is normalised to a Standard Schema. A plain function becomes a schema whose `validate` calls it and treats `undefined` as failure. (The check for a Standard Schema comes first because some libraries, ArkType for example, produce callable schemas.)
- **Matchers must be synchronous.** If `validate` returns a promise, routing throws `param_matcher_async`. There is no way to consult a database in a matcher.
- The output must be a `string`, `number`, `boolean` or `bigint`. Anything else (an object, a `Date`) throws `param_matcher_result_invalid`. The generated `RouteParams` type reflects the output type, so `params.id` in `/items/[id=number]` is typed `number`.
- Matchers run on both server and client, with the same inputs (the decoded segment), so they must be pure and must not import server-only modules. A client bundle includes your `params.ts`; keep it small and dependency-light, particularly if you use a validation library only for matchers.
- A failure means the route does **not match**, and matching continues with the next route by sort order, eventually reaching a 404. It does not mean a 404 with a validation message.

We verified the fallthrough in a test project with `src/routes/items/[id=number]` and `src/routes/[...catchall]`: `/items/12` rendered `/items/[id=number]` with `params.id === 12` (a number), while `/items/abc` fell through to `/[...catchall]` with `{"catchall":"items/abc"}`. If you do not have a catch-all, `/items/abc` would be a plain 404, which is usually what you want.

### Symmetry and `resolve`

Transformation creates a duty: **symmetry**. Whatever the matcher parses must serialise back to the original segment with `String(value)`. `Number('007')` is `7`, and `String(7)` is `'7'`, so `/items/007` parses but `resolve('/items/[id=number]', { id: 7 })` produces `/items/7`: a different URL for the same resource, which is an SEO and caching hazard. Make the matcher strict (`/^(0|[1-9]\d*)$/`) so that every accepted string is canonical. Since `resolve` calls `String(value)` for number, boolean and bigint params, the contract is: for every accepted segment `s`, `String(match(s)) === s`.

### Matchers and optional parameters

When an optional parameter has a matcher (`[[lang=locale]]`) and the first segment fails the matcher, the router treats the parameter as absent and tries to match that segment against what follows. This is how `/[[lang=locale]]/about` serves both `/about` and `/en/about`, while `/zz/about` fails. Combined with a rest segment (`[[lang=locale]]/[...path]`), skipped values are rolled into the rest parameter. This chaining logic is why a locale prefix is best expressed as an optional matched parameter rather than as a rest parameter.

## Route sorting

Several routes can match one URL, so Kit sorts routes and picks the first match. The rules:

1.  More specific routes have higher priority. A route with no parameters beats one with a dynamic parameter, and so on segment by segment.
2.  Parameters with matchers (`[name=type]`) beat parameters without (`[name]`).
3.  `[[optional]]` and `[...rest]` are ignored unless they are the final segment, in which case they have the lowest priority. In other words `x/[[y]]/z` sorts as `x/z`.
4.  Ties are resolved alphabetically.

The documentation example, which we confirmed by request, is five routes that can all match `/foo-abc`:

```text
src/routes/foo-abc/+page.svelte
src/routes/foo-[c]/+page.svelte
src/routes/[[a=x]]/+page.svelte
src/routes/[b]/+page.svelte
src/routes/[...catchall]/+page.svelte
```

With a `params.ts` where `x` accepts only the string `"x"`:

| Request    | Matched route ID | `params`              |
|------------|------------------|-----------------------|
| `/foo-abc` | `/foo-abc`       | `{}`                  |
| `/foo-def` | `/foo-[c]`       | `{ c: 'def' }`        |
| `/x`       | `/[[a=x]]`       | `{ a: 'x' }`          |
| `/zzz`     | `/[b]`           | `{ b: 'zzz' }`        |
| `/a/b`     | `/[...catchall]` | `{ catchall: 'a/b' }` |

Practical consequences. First, specificity is by *shape*, not by what a matcher accepts: `[id=number]` outranks `[slug]` even if a given segment happens to satisfy both. Second, “alphabetical” ties are not a feature to design around; two same-shape sibling routes with different matchers (`[id=number]` and `[slug=slug]`) are ordered by matcher presence first, then name, so keep matchers mutually exclusive to make the behaviour independent of ordering. Third, a catch-all at the root swallows everything unmatched, which also disables the root `+error.svelte` for 404s (your catch-all page renders instead); use the `error(404)` pattern from the previous section in the catch-all’s `load`.

Matching is by route, not by method: the page that wins for a URL is the page that wins even if the request is a `DELETE`. Method handling is in the content negotiation section below.

## Layouts

### Nesting and the layout chain

The layout chain for a page is every `+layout.svelte` from the root down to the page’s directory, in order, and layout *data* is likewise accumulated from root downward. The chain is built from the route’s directory ancestry, including groups, and is what the generated `$types` use to compute `LayoutData`/`PageData` and the `parent()` return type.

### Layout groups and `@` resets

By default the layout hierarchy mirrors the route hierarchy. Two features break that.

**Groups** assign a subtree its own layouts without changing URLs:

```text
src/routes/
├ (app)/
│ ├ dashboard/+page.svelte
│ └ +layout.svelte
├ (marketing)/
│ ├ about/+page.svelte
│ └ +layout.svelte
├ admin/+page.svelte         # inherits only the root layout
└ +layout.svelte
```

**`@` resets** let an individual page or layout choose a different ancestor to inherit from. Appending `@` and the *segment name* of the layout to inherit from, or `@` alone for the root, pulls the page out of intermediate layouts:

```text
src/routes/
├ (app)/
│ ├ item/
│ │ ├ [id]/
│ │ │ ├ embed/
│ │ │ │ └ +page@(app).svelte    # root layout + (app) layout only
│ │ │ └ +layout.svelte
│ │ └ +layout.svelte
│ └ +layout.svelte
└ +layout.svelte
```

For the page above, `+page@[id].svelte` would keep `[id]`’s layout; `@item` keeps `item`; `@(app)` keeps `(app)` and the root; `@` keeps only the root. A `+layout@.svelte` does the same for a layout and applies to everything beneath it:

```text
(app)/item/[id]/embed/+page.svelte   # uses (app)/item/[id]/+layout.svelte
(app)/item/[id]/+layout.svelte       # inherits from (app)/item/+layout@.svelte
(app)/item/[id]/+page.svelte         # uses (app)/item/+layout@.svelte
(app)/item/+layout@.svelte           # inherits from root, skipping (app)/+layout.svelte
```

A few facts:

- The segment name in `@name` must exist among the page’s ancestors, or the build fails with `references missing segment`. Only `.svelte` files can reference named layouts; `+layout@.ts` is an error.
- Reset affects the *component* chain. Layout **data** loading follows the same chain, so a page that resets to the root does not run the skipped layouts’ `load` functions. The generated types account for it, so `PageData` of such a page lacks the skipped layouts’ keys.
- Groups and resets are for visual and loading hierarchy. They are not a permissions mechanism. A page that resets with `@` to avoid an auth layout is not protected by that layout’s guard, and layout loads do not reliably gate child loads anyway (Chapter 4).

### When not to use groups

Groups are not free: deeply nested groups make route IDs long and make it harder to find where a layout is defined. If one page needs a different shell, composition is sometimes simpler: a `+layout@.svelte` that renders a shared component from `#lib` and reuses a shared load function, rather than a new group for a single outlier. Reserve groups for regions that have a distinct layout, distinct data requirements or distinct page options (for example `export const prerender = true` in `(marketing)/+layout.ts` and `ssr = false` in `(admin)/+layout.ts`).

## `$app/paths`: building and matching URLs

In SvelteKit 2, `base` and `assets` were string variables from `$app/paths` that you prefixed manually. In 3.0 they are removed, along with `resolveRoute`. Three functions remain: `resolve`, `match` and `asset`.

### `resolve`

```ts
import { resolve } from '$app/paths';

resolve('/blog/[slug]', { slug: 'hello-world' }); // '/blog/hello-world'
resolve('/about');                                 // no params required
resolve('/search?q=svelte#results');               // query and hash are allowed
resolve('docs/intro');                             // a pathname without a leading slash
```

It has two modes, decided by the first character:

- **Starts with `/`**: a *route ID*. Dynamic segments are filled from the params object, groups are removed, optional segments with no value are dropped, and escapes (`[x+3a]`) are decoded back into the real characters (and percent-encoded where needed). Param values themselves are inserted as given, not percent-encoded, so encode them yourself if they may contain reserved characters. Missing required params throw (`Missing params for dynamic route ID ...`, or `route_param_missing`), and a string value that starts or ends with `/` throws `route_param_slash`. Slashes in the middle are not rejected (`resolve('/blog/[slug]', { slug: 'a/b' })` yields `/blog/a/b`, a URL that would not match the route), so validate non-rest values yourself. A number, boolean or bigint is rendered with `String(value)`.
- **Anything else**: a *pathname* relative to the base. The base path is prefixed.

Typing is the point. `resolve` is generic over `RouteId` from the generated `$app/types`, so an unknown route ID is a type error, and the second argument is required, and typed, exactly when the route has params:

```html
<script lang="ts">
    import { resolve } from '$app/paths';
    let { data } = $props();
</script>

<a href={resolve('/(app)/orgs/[org=slug]/settings', { org: data.org.slug })}>Settings</a>
<!-- type error: Argument of type '{ orgg: string }' is not assignable -->
<a href={resolve('/(app)/orgs/[org=slug]/settings', { orgg: 'x' })}>Typo</a>
```

Because the type of each parameter is the matcher’s *output*, `resolve('/items/[id=number]', { id: '12' })` is a type error (it wants a number). That is the second half of the symmetry contract: the types force you to pass the parsed form, and `String()` brings it back to the URL form.

Two behaviours that matter in production:

- **Base path and relative output.** If you set `paths.base`, `resolve` prefixes it. With `paths.relative` (the default), during SSR the prefix is computed relative to the page being rendered, so the same output works behind a path-rewriting proxy or from a static archive. In hash router mode (`router.type: 'hash'`) the result starts with `#`, so `resolve('/about')` is `#/about`.
- **It is a pure string builder.** It does not check that the target is reachable or authorised.

> **Senior tip:** Wrap `resolve` in a typed helper for your own conventions (adding a locale, tracking parameters) rather than sprinkling string templates through components. Because `RouteId` is a union of literal types, `Parameters<typeof resolve>` gives you everything you need to build a safe wrapper, and TypeScript will flag broken links whenever a route is renamed. This is a major advantage of the “route ID plus params” API over hand-written `href`s.

Raw `<a href="/blog/{slug}">` strings still work and are fine for simple cases, but you give up rename safety and base-path handling.

### `match`

`match(urlOrPath)` is the inverse: it resolves a pathname or `URL` to `{ id, params }` or `null`. It is **asynchronous** (a promise), because on the client it uses the router’s intent resolution, which may consult `reroute`, and with `router.resolution: 'server'` it may require a request:

```ts
import { match } from '$app/paths';
import { preloadCode } from '$app/navigation';

const route = await match('/blog/hello-world');
if (route?.id === '/blog/[slug]') {
    console.log(route.params.slug); // typed as string
    await preloadCode(route.id);    // preloadCode takes a route ID, not a pathname
}
```

The return type is a discriminated union over all route IDs, so narrowing on `route.id` narrows `route.params`. It is available on the server as well (it routes using the manifest). Use it for things like deciding whether an outbound link points into your app, or building breadcrumbs from arbitrary URLs.

### `asset`

`asset('logo.svg')` prefixes a file in `static/` with `paths.assets` if set, otherwise with the base. Its parameter type is `AssetPath`, a union generated from the files actually present in `static/`, so a typo is a compile error. A leading slash is accepted with a dev warning (and will be an error later).

### Generated types in `$app/types`

`svelte-kit sync` generates `node_modules/$app/types/index.d.ts`, from which these are exported: `RouteId`, `PageRouteId`, `EndpointRouteId`, `RouteParams<Id>`, `LayoutParams<Id>`, `Path`, `ResolvedPathname` and `AssetPath`. In the 3.1 minimal template it looks like this:

```ts
// node_modules/$app/types/index.d.ts (abridged)
declare module "$app/types" {
    export interface AppTypes {
        PageRouteId(): "/";
        EndpointRouteId(): never;
        RouteId(): "/";
        RouteParams(): {};
        LayoutParams(): { "/": Record<string, never> };
        Path(): "";
        ResolvedPathname(): `${"/" | `/${string}/`}${ReturnType<AppTypes['Path']>}`;
        AssetPath(): "robots.txt";
    }
}
```

Notice that `Path` is the type of `resolve`’s pathname-mode argument and has **no leading slash** (`Pathname` was renamed to `Path` in 3.0; the leading-slash form is reserved for route IDs). Reaching for these types is useful when you write components that accept a route:

```html
<!-- src/lib/NavLink.svelte -->
<script lang="ts" generics="Id extends import('$app/types').RouteId">
    import { resolve } from '$app/paths';
    import { page } from '$app/state';
    import type { RouteParams } from '$app/types';
    import type { Snippet } from 'svelte';

    let { route, params, children }: {
        route: Id;
        params: RouteParams<Id>;
        children: Snippet;
    } = $props();

    let href = $derived(resolve(...([route, params] as Parameters<typeof resolve>)));
    let active = $derived(page.route.id === route);
</script>

<a {href} aria-current={active ? 'page' : undefined}>{@render children()}</a>
```

(The cast is needed because `resolve`’s argument tuple depends on whether the route has params; the useful part is that callers get full type safety for `route` and `params`.)

## Content negotiation between pages and `+server`

A directory may contain both a `+page` and a `+server`. They then share one route, and per request SvelteKit decides which handles it:

- `PUT`, `PATCH`, `DELETE`, `OPTIONS` and `QUERY` go to `+server`, since pages do not respond to them.
- `GET`, `POST` and `HEAD` go to the page if the `Accept` header prioritises `text/html` (a browser navigation), else to `+server`.
- `GET` and `HEAD` responses get `Vary: Accept` (unless already present), so caches keep page and endpoint variants apart.
- If a route has both, but the endpoint lacks a handler for this `GET`, `HEAD` or `POST` (no matching export, no `fallback`), the page serves it anyway.

A real check, with one route that has a page and a `+server` exporting `GET` and `QUERY`:

```text
$ curl -s -i -H 'accept: text/html' localhost:4174/api-neg
HTTP/1.1 200 OK
vary: Accept
content-type: text/html
x-sveltekit-page: true
...<p id="r">PAGE</p>...

$ curl -s -i -H 'accept: application/json' localhost:4174/api-neg
HTTP/1.1 200 OK
vary: Accept
content-type: application/json
{"via":"server"}

$ curl -s -H 'accept: */*' localhost:4174/api-neg
{"via":"server"}

$ curl -s -X QUERY localhost:4174/api-neg
query ok
```

Two things worth noting. `Accept: */*`, which is what `curl` and many HTTP clients send, does *not* prioritise HTML, so the endpoint answers; browsers send `text/html` first. And `QUERY` is the safe, idempotent method with a request body (the IETF “QUERY” method), which Kit now routes straight to `+server`. It is useful for complex searches that do not fit in a URL, but note that caches and intermediaries may not understand it yet.

Design guidance: mixing is convenient for resources with a human page and a machine representation (`/posts/42` as HTML and JSON), but it doubles the surface of a route, couples their prerender and config options (see the mismatch error above), and invites cache mistakes when a CDN ignores `Vary: Accept`. If you control both sides, a separate `/api/...` route is simpler and more cacheable. Prerendering has an extra rule: a route that is both prerenderable page and `+server` fails early, so do not combine them for static sites.

`+server` does not get `+layout` loads or `+error.svelte`, and `event.route.id` for an endpoint is the same directory ID.

## `reroute`: changing how URLs become routes

`reroute` (in `src/hooks.ts`) lets you translate an incoming URL into a different pathname before routing:

```ts
// src/hooks.ts
import type { Reroute } from '@sveltejs/kit/hooks';

const translated: Record<string, string> = {
    '/de/ueber-uns': '/de/about',
    '/fr/a-propos': '/fr/about'
};

export const reroute: Reroute = ({ url }) => {
    return translated[url.pathname];
};
```

With `src/routes/[[lang]]/about/+page.svelte`, `/de/ueber-uns` now renders the about page with `lang: 'de'`, while the browser’s address bar and `event.url` still show the original URL. The contract of `Reroute` is `(event: { url: URL; fetch: typeof fetch }) => MaybePromise<void | string>`: return a pathname, or nothing to leave the URL unchanged.

What you need to know:

- **It runs before `handle`**, on both server and client (the hook lives in the universal file). In `respond` it is step 7: no `locals`, no `cookies`, no `event` at all, and an exception yields a bare 500 (Chapter 2).
- **It must be pure and idempotent.** The client caches its result per URL string, so the hook runs at most once per distinct URL during the session. Reading time, cookies or random values would produce stale or inconsistent routing between server and client.
- **It may be async** (since 2.18), using the `fetch` argument. That fetch has the benefits of the `load` fetch (relative URLs on the server, in-process dispatch) but `handleFetch` receives no `route.id` or `params`, because routing has not happened. An async `reroute` delays every navigation by its latency on a cold cache, so keep it fast and avoid calling endpoints that themselves trigger rerouting (guard with `if (url.pathname === '/api/reroute') return;`).
- **It affects routing only.** Prerendered files for the rerouted path are served if they exist (on the server, `reroute`d paths that have a prerendered page return that file directly, bypassing `handle`).
- **Hash mode:** in `router.type: 'hash'` the client passes the hash path (without `#`) as the pathname and a returned string replaces the hash.
- **With server-side resolution** (below), `reroute` still applies, and it is the *only* place inside Kit to intercept route-resolution requests, since they never reach `handle`.

A common use is locale-prefixed routing with translated slugs, as above. Another is A/B routing: because `reroute` cannot read cookies, A/B decisions that depend on them should happen in a CDN or in `handle` (with a redirect or internal `fetch`), and `reroute` should be reserved for deterministic URL translation.

## Where routing happens: client vs server resolution

By default (`router.resolution: 'client'`) the route manifest is shipped to the browser, in the form of route IDs compiled to regular expressions and lazy node imports. Navigations resolve synchronously from this table (after `reroute`), so link clicks have zero routing latency. The trade-offs are manifest size, which grows with your route count, and exposing the route list.

With `router.resolution: 'server'`:

- The client does not load the route manifest upfront. For a URL not yet visited it requests `<pathname>/__route.js`, answered by `respond` at step 9, **before** `handle`. The response is a small JavaScript module exporting the route’s node loaders (and CSS imports, since Vite cannot discover them in this mode) and, for pathname requests, the resolved params.
- `preloadCode(routeId)` uses a route-ID-keyed endpoint, `/_app/routes/<id>/__route.js`. Its three possible responses (a module with the route, an `endpoint_only` export for `+server`-only routes, or an empty module for unknown IDs) let the client cache “nothing to preload” decisions.
- Prerendered pages get their resolution module prerendered alongside them.
- The documented benefits are a smaller initial payload, a hidden route list and the chance for infrastructure (a reverse proxy or edge function) to intercept every navigation, for example for A/B testing that is opaque to Kit. The cost is a round trip for each first visit to a new path, mitigated by preloading.

Choose server resolution for very large route trees or when routing decisions must be centralised. Do not choose it just to hide routes: route code chunks are still downloadable.

### The hash router

`router.type: 'hash'` makes `location.hash` the route (`/#/about`). SSR and prerendering are disabled and the server serves only the SPA shell; any other path returns 404 from `respond` (the “hash router guard” in Chapter 2). All internal links must start with `#/` (use `resolve()`, which adds the `#` in this mode), page options other than `load` are meaningless and warn in development, and `url.hash` becomes meaningful on the client. Use it only when you cannot configure the web server to serve the shell for arbitrary paths, such as hosting on a static bucket that has no fallback support.

## Trailing slashes and URL normalisation

By default (`trailingSlash: 'never'`) a request for `/about/` receives a redirect to `/about`. The option can also be `'always'` (redirect `/about` to `/about/`) or `'ignore'` (both serve, as separate URLs; documented as not recommended because it is harmful for SEO and changes how relative links resolve). It is exported from `+layout(.server).ts`, `+page(.server).ts` or `+server.ts` and inherited down the tree.

Observed behaviour: `curl -i localhost:4174/foo-abc/` returned

```text
HTTP/1.1 308 Permanent Redirect
location: ../foo-abc
x-sveltekit-normalize: 1
```

Three details are visible. It is a `308`, preserving the method. The `Location` is **relative** (`../foo-abc`), so that any path prefix added by a proxy that Kit cannot see is preserved. And the `x-sveltekit-normalize: 1` header marks the response as a normalisation redirect, which you can use in observability. This redirect happens before `handle`, as discussed in Chapter 2. The root of a custom `paths.base` always behaves as `always` (the root URL with a base is `/base/`).

Other consequences of `trailingSlash`:

- Prerendering writes `about/index.html` for `always` and `about.html` for the others, mirroring static server conventions (Chapter 11).
- Relative links resolve differently: from `/x`, `./y` is `/y`; from `/x/`, it is `/x/y`. A mismatched mental model produces broken links in components that use relative `href`s. Prefer `resolve()`.
- For data requests, the client sends `x-sveltekit-trailing-slash=1` so the server can reconstruct the exact URL; the server skips the normalisation redirect for them.
- A hash fragment is not seen by the server, so `/about/#x` is normalised for the path only.

### `normalizeUrl`

Server code that wants the “logical” URL, without SvelteKit’s internal suffixes, can use `normalizeUrl` from `@sveltejs/kit`:

```ts
import { normalizeUrl } from '@sveltejs/kit';

const { url, wasNormalized, denormalize } = normalizeUrl('/blog/post/__data.json');
console.log(url.pathname);                // '/blog/post'
console.log(wasNormalized);               // true
console.log(denormalize('/blog/post/a')); // '/blog/post/a/__data.json'
```

It strips `__data.json`-style suffixes and trailing slashes, tells you whether it changed anything, and gives you a function to add the suffix back to a new URL. Its main use is in code that inspects `event.url` early (a `reroute` or a CDN-compatible cache key function) where you want data requests and document requests to compare equal, and where you want to construct a redirect target that is valid for both. (`event.url` in `handle` is already stripped of data suffixes, as Chapter 2 showed, so you rarely need it there.) `url.pathname` in `reroute` is the *logical* pathname, with the suffix removed, for the same reason.

## Debugging checklist

When a URL renders the wrong thing, walk the pipeline in order:

1.  **Is it served before Kit?** Static files and prerendered pages win over routes. Look in `static/` and the build’s prerendered output.
2.  **Did `reroute` change it?** The route ID will differ from what the URL suggests; `event.url` will not.
3.  **Did a matcher reject it?** A failing matcher silently falls through to the next route. Temporarily log in `params.ts` (matchers are called on both sides) or call `match(url)`.
4.  **Which route wins by sort?** List the candidates and apply the four rules. Remember that rest and optional segments in the middle do not count.
5.  **Is the page or the endpoint answering?** Check `Accept` and method; read `Vary`.
6.  **Is the trailing slash policy redirecting?** A 308 with `x-sveltekit-normalize`.
7.  **Is a layout reset or group altering the shell?** Look at the route ID, which includes groups, and the `@` suffix of the page file.

## Key takeaways

- A route is a directory containing a `+page` or `+server`; its ID is the path from `src/routes` and includes `(groups)`. Conflicting routes (same shape after removing groups and optional segments) fail the build; page and endpoint on the same route must export the same page options.
- Parameters: `[x]`, `[[x]]`, `[...x]` (zero or more segments), `[x=matcher]`, mixed with literals in a segment (`foo-[c]`). Params must be separated; optional cannot follow or wrap rest; names allow alphanumerics, `_` and `-`; special characters use lowercase `[x+nn]`/`[u+nnnn]` escapes.
- Matchers live in `src/params.ts` as a `params` export from `defineParams`. They are functions returning a parsed value or `undefined`, or Standard Schemas, must be synchronous, output `string | number | boolean | bigint`, and run on both server and client. A failing matcher makes the route not match; matching falls through to the next route.
- Keep matcher transforms symmetric (`String(match(s)) === s`) so `resolve()` produces canonical URLs; the generated param types use the matcher output type.
- Route sorting: specific over generic, matcher over no matcher, final optional/rest lowest, alphabetical for ties. It is based on route shape, not on what a matcher accepts.
- Layout chains follow directory ancestry. Groups create independent chains without affecting URLs; `+page@name` and `+layout@name` reset to a named ancestor (`@` alone is the root). Resets change which layouts render and load, but are not an authorisation mechanism.
- Nested `+error.svelte` boundaries are only reachable for matched routes; use a `[...path]` route that calls `error(404)` to give a subtree its own 404 page.
- `$app/paths` in 3.x provides `resolve` (typed route IDs plus params, or pathnames), `match` (async, returns `{ id, params } | null`) and `asset`. `base`, `assets` and `resolveRoute` are removed. `$app/types` provides `RouteId`, `RouteParams`, `Path`, `AssetPath` and more.
- A `+server` and a `+page` can share a route: `PUT/PATCH/DELETE/OPTIONS/QUERY` always go to the endpoint; `GET/POST/HEAD` go to the page when `Accept` prefers HTML. `Vary: Accept` is added. `Accept: */*` clients get the endpoint.
- `reroute` (in `src/hooks.ts`) is a pure, idempotent, optionally async function run on both sides before `handle`; it changes routing but not `event.url` or the address bar. Client results are cached per URL.
- Route resolution can be client (manifest in the browser, the default) or server (`__route.js` requests answered before `handle`; `reroute` still applies). The hash router disables SSR and prerendering.
- Trailing slash normalisation is a relative `308` issued before `handle`, with `x-sveltekit-normalize`. `normalizeUrl` strips internal suffixes and slashes and can add the suffix back.

## Review Questions

1.  What is the route ID of the page at `src/routes/(app)/orgs/[org=slug]/settings/+page.svelte`, and which part of it never appears in the URL?

2.  A directory `src/routes/dashboard/` contains only `+layout.svelte`. Can a user visit `/dashboard`? What role does the directory play?

3.  **What does the build do?** You have `src/routes/[a]/+page.svelte` and `src/routes/[b]/+page.svelte`. What happens, and why does the same happen for `src/routes/(x)/about/+page.svelte` plus `src/routes/(y)/about/+page.svelte`?

4.  State what `src/routes/a/[...rest]/z/+page.svelte` matches for `/a/z`, `/a/b/z` and `/a/b/c/z`, and the value of `params.rest` in each case.

5.  Which of these route directory names is invalid, and why? (a) `[[...path]]` (b) `[a]-[b]` (c) `[a][b]` (d) `[x+3A]` (e) `[post-id]`

6.  How do you create a route serving `/.well-known/security.txt`, and why can’t you just name the directory `.well-known`?

7.  **Find the bug.** A developer writes this in `src/params.ts` and uses it as `[user=user]`. Why will it fail at runtime?

    ```ts
    export const params = defineParams({
     user: async (param) => ((await db.exists(param)) ? param : undefined)
    });
    ```

8.  What types may a matcher’s output have? What does the generated type of `params.id` become for `src/routes/items/[id=number]` if `number` returns `Number(param)`?

9.  A matcher is `number: (p) => (/^\d+$/.test(p) ? Number(p) : undefined)`. Explain the problem with `/items/007` and `resolve('/items/[id=number]', { id: 7 })`, and fix the matcher.

10. With a route `src/routes/items/[id=number]/+page.svelte` and a root `src/routes/[...catchall]/+page.svelte`, what renders for `/items/abc`? What if there were no catch-all?

11. Order these routes by priority for the URL `/foo-abc`: `[...catchall]`, `[b]`, `foo-abc`, `[[a=x]]`, `foo-[c]`. Which of them match `/foo-def` if the matcher `x` only accepts `"x"`?

12. **Multiple choice.** Which statement about sorting is correct?

    a.  `[id=number]` and `[slug]` have equal priority; ties are broken by file modification time.
    b.  A matcher gives a parameter higher priority regardless of whether the segment satisfies it.
    c.  `x/[[y]]/z` sorts below `x/z` because it has an optional segment.
    d.  Rest parameters are always lowest priority, wherever they appear.

13. A page at `src/routes/(app)/item/[id]/embed/+page.svelte` should inherit only the root and `(app)` layouts. What file name achieves this? What would the name be to inherit only the root layout?

14. What is wrong with `+layout@.ts` or `+page@(app).ts` as file names?

15. A developer adds a `(admin)` group and a `+layout.server.ts` there that redirects non-admins, and builds a `+page@.svelte` reset for one admin page “to get a plain layout”. Does the reset remove the guard? Explain, and say where the guard should live.

16. Why would `/marx-brothers/karl` not render `src/routes/marx-brothers/+error.svelte` when no route matches it? How do you make it render?

17. **What does this print?** Given the type of `resolve`, what does `resolve('/blog/[slug]', { slug: 'a/b' })` do, and what about `resolve('/docs/[...path]', { path: 'a/b' })`?

18. Name the removed 2.x exports of `$app/paths` and their 3.x replacements.

19. `match` returns a promise. Why isn’t it synchronous? What shape does the resolved value have, and how do you get typed params from it?

20. **Multiple choice.** `preloadCode` in 3.x takes:

    a.  A pathname, such as `/blog/hello`
    b.  A full URL
    c.  A route ID, such as `/blog/[slug]`
    d.  A route file path

21. For a route with `+page.svelte` and a `+server.ts` exporting `GET`, how are these requests handled: (a) browser navigation, (b) `fetch('/x', { headers: { accept: 'application/json' } })`, (c) `curl` with the default `Accept: */*`, (d) `DELETE`, (e) `HEAD` from a browser?

22. Which response header is added when a route has both a page and an endpoint, and what problem does it prevent?

23. List four constraints on `reroute`. Why can’t it read cookies?

24. **Design question.** You have routes `[[lang=locale]]/about` and want `/de/ueber-uns`, `/fr/a-propos` and `/about` to render the same page while keeping the translated URL in the address bar. Write the `reroute` hook and explain what `event.url.pathname` is inside `load` and `handle` for `/de/ueber-uns`.

25. What is the difference in *when* route resolution happens with `router.resolution: 'client'` and `'server'`? Name two benefits and one cost of server resolution, and say whether `handle` sees route-resolution requests.

26. A request for `/about/` returns a redirect. Which status, which headers, and in which pipeline stage (relative to `handle`) is it produced? What is unusual about the `Location` value, and why?

27. **Design question.** Your team is deciding between `trailingSlash: 'ignore'` and `'never'` for a public site with SEO requirements, a prerendered docs section and relative links inside components. Make a recommendation, citing three consequences of the option.

28. A route `src/routes/api/orgs/[org=slug]/members/+server.ts` returns 403 on `PUT` from a form on another origin in production but works in development. Explain.
