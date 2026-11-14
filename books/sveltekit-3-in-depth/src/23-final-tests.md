# Final Tests

Six cumulative tests for the whole book. Each test has 27 questions and spans several chapters. Difficulty rises from Test 1 (core concepts) to Test 6 (expert level: internals, failure modes and architecture). Answer without looking things up first, then check `tests-answers.md`. Unless a question says otherwise, assume SvelteKit 3.1 with Svelte 5.57, `#lib` imports, config in `sveltekit({...})`, and the experimental flags for remote functions enabled where they are used.

## Test 1: Foundations: Toolchain, Routing, and Data Loading

1.  Where does project configuration live in SvelteKit 3?

    - a\. In the `kit` key of `svelte.config.js`
    - b\. In options passed to `sveltekit({...})` in `vite.config`
    - c\. In a `sveltekit` key in `package.json`
    - d\. In `.svelte-kit/config.json`

2.  Which of these is **not** a minimum version required by SvelteKit 3.x?

    - a\. Node 22.17
    - b\. TypeScript 6
    - c\. Vite 8.0.12
    - d\. Svelte 6.0

3.  A SvelteKit 2 file contains `import { fmt } from '$lib/util/format';`. Write the SvelteKit 3 import, and the `package.json` entry that makes it resolve.

4.  A teammate shortens `tsconfig.json` to `{ "extends": "$app/tsconfig" }` and the editor suddenly type-checks `node_modules` and the service worker. What did they forget, and what is the service worker’s configuration supposed to look like?

5.  A CI job fails on a fresh clone with `Cannot find module './$types'`, but works on developers’ machines. What is the cause and the fix?

6.  Which of these requests goes through the `handle` hook?

    - a\. A prerendered page served by the adapter
    - b\. A file from `static/`
    - c\. A client navigation’s `__data.json` request
    - d\. A hashed file under `/_app/immutable/`

7.  Put these steps of `server.respond` in the order they occur, and say what happens if the one marked with an asterisk throws: `handle`, CSRF origin check, `reroute`\*, route matching, trailing-slash normalisation.

8.  Given this route tree, which route renders for `/blog/2024`, `/blog/hello` and `/blog/2024/comments`? Assume `src/params.ts` defines `integer` so that it matches digits only.

    ```text
    src/routes/blog/[slug]/+page.svelte
    src/routes/blog/[year=integer]/+page.svelte
    src/routes/blog/[...rest]/+page.svelte
    ```

9.  Why does the book recommend that a param matcher transform be symmetric (`String(match(s)) === s`)? Name the API that suffers when it is not.

10. What may a `src/params.ts` matcher return, and what is not allowed of it?

    - a\. Any object, and it may be async
    - b\. A `string | number | boolean | bigint` (or `undefined` for no match); it must be synchronous
    - c\. A `Promise` of a string, so it can query a database
    - d\. Only a boolean

11. What does this do for a visit to `/de/ueber-uns`? State what `event.url.pathname` is inside `load` and what the address bar shows. `ts // src/hooks.ts import type { Reroute } from '@sveltejs/kit/hooks'; export const reroute: Reroute = ({ url }) => { if (url.pathname === '/de/ueber-uns') return '/de/about'; };`

12. A route directory contains both `+page.svelte` and `+server.ts` (exporting `GET` and `PUT`). Which one answers a `fetch` with method `PUT`? Which answers a `GET` with `Accept: text/html,*/*;q=0.8`, and which a `GET` with `Accept: */*`? What response header is added?

13. A server `load` returns `{ a: 1, b: 2 }`. The same node’s universal `load` is `({ data }) => ({ c: data.a + 1 })`. What does the page receive as `data`?

14. Which of these can only a universal `load` do?

    - a\. Read a secret from the environment
    - b\. Return a class instance or a function
    - c\. Read `cookies`
    - d\. Read `locals`

15. Identify the waterfalls and rewrite the page load to remove them. `ts // src/routes/posts/[slug]/+page.server.ts export const load = async ({ parent, params }) => { const { user } = await parent(); const post = await db.post(params.slug); const comments = await db.comments(params.slug); return { post, comments, mine: post.authorId === user.id }; };`

16. Load A reads `url.searchParams.get('q')`. Load B (a different node) reads `new URL(request.url).searchParams.get('q')`. The user navigates from `?q=a` to `?q=b` on the same page. Which load reruns, and what is the consequence for the other?

17. For the load below, say which of the four events rerun it: (i) navigating from `?page=1&sort=asc` to `?page=1&sort=desc`; (ii) `invalidate('app:cart')`; (iii) clicking a link to `?page=2`; (iv) `invalidate('/api/items')`. `` ts export const load = async ({ url, depends, fetch }) => { depends('app:cart'); const page = Number(url.searchParams.get('page') ?? 1); return { items: await (await fetch(`/api/items?page=${page}`)).json() }; }; `` (This is a server `load`.)

18. Which statement about streaming is correct?

    - a\. A streamed promise may still change the status code after it resolves
    - b\. Promises returned from a universal `load` are streamed too
    - c\. Only server `load` streams; attach a no-op `.catch` to avoid process-level unhandled rejections; status, headers and cookies must be decided before streaming starts
    - d\. Streamed responses receive an HTML-hash `ETag`

19. `preloadData(href)` has three result types in SvelteKit 3. Name them and say which one is new in 3.0.

20. Explain the difference between `refreshAll()` and the deprecated `invalidateAll()`.

21. What is the default of `version.pollInterval` in SvelteKit 3?

    - a\. `0` (no polling)
    - b\. `60000`
    - c\. `3600000`
    - d\. `86400000`

22. A page navigates from `/posts/a` to `/posts/b` and keeps showing the title of post a. Why, and give two fixes? `svelte <script lang="ts"> let { data } = $props(); let title = $state(data.post.title); </script> <h1>{title}</h1>`

23. A universal `load` calls `fetch('/api/items')`. Explain why the browser does not issue that request again while hydrating, and what controls which response headers are available to the browser code.

24. In `load`, `fetch('/api/items')` is called with a relative URL on the server. Describe how it is dispatched, and what happens to `Set-Cookie` headers in the sub-response.

25. Scenario: a product page needs (1) the product row and price from Postgres, (2) inventory from an internal API, (3) a recommendations list from a third-party API that takes about 800 ms and appears below the fold. Design the loading strategy: which kind of `load`, what is awaited, what is streamed, and what must you take care of for SEO and for error handling.

26. Scenario: a team puts `if (!locals.user) redirect(303, '/login')` in `src/routes/admin/+layout.server.ts` and considers the admin area protected. Explain why this is insufficient, and where the guard should live.

27. Write a `+server.ts` `GET` handler that returns `{ ok: true }` as JSON the SvelteKit 3 way (without the deprecated helper). What does a handler that returns `new Response(null, { status: 204 })` send to the client in SvelteKit 3?

## Test 2: Mutations, Remote Functions, Hooks, and Errors

1.  A page exports `actions = { default: ..., login: ... }`. Is this valid? If you remove `default`, which URL does a form post to in order to call `login`, and how do you target it from a `<button>` inside a form that has no `action`?

2.  With SvelteKit 3, an enhanced form (`use:enhance` without arguments) submits to an action that does `return fail(422, { errors })`. What HTTP status does the enhanced request receive, what ends up in the `form` prop, and how did this differ in SvelteKit 2?

3.  Find and fix the bugs in this action.

    ```ts
    import { fail, redirect } from '@sveltejs/kit';
    export const actions = {
     default: async ({ request }) => {
         const data = await request.formData();
         if (!data.get('email')) throw fail(400, { missing: true });
         return redirect(303, '/done');
     }
    };
    ```

4.  A form on `/items?page=2&sort=name` has `<form method="POST" action="?/archive">`. Which URL is posted to? How do you preserve the query string?

5.  An action logs the user in by setting the session cookie. The page’s `load`, which runs after the action in the same request, still sees `locals.user === null`. Explain why and give two ways to fix it.

6.  What happens in the browser after a successful submit with this `use:enhance` callback?

    ```html
    <form method="POST" use:enhance={() => {
     return async ({ result }) => {
         console.log(result.type);
     };
    }}>
    ```

    Which three default behaviours are lost, and how do you get them back selectively?

7.  Which two flags enable remote functions, where do they go, and what happens if a `*.remote.ts` file exists while `experimental.remoteFunctions` is off?

8.  Which of these filenames are treated as remote modules in SvelteKit 3?

    - a\. `posts.remote.ts`
    - b\. `posts.remote.test.ts`
    - c\. `remote.ts`
    - d\. All of the above

9.  What happens when a browser calls this function with `getPost('hello')`, and what are the two correct ways to fix it?

    ```ts
    // src/routes/posts.remote.ts
    import { query } from '$app/server';
    export const getPost = query(async (slug: string) => db.post(slug));
    ```

10. A client calls a validated remote function with an argument that fails the schema. Trace what happens: HTTP status, what `handleError` receives, and what the calling component can see.

11. Are `getPost({ a: 1, b: 2 })` and `getPost({ b: 2, a: 1 })` the same query on the client? How is the cache key built, and how many instances exist per key on the client versus on the server during one request?

12. A list renders 50 rows, each awaiting `getUser(row.userId)`, a plain `query`. Explain what `query.batch` changes: how many network requests, what the handler’s signature looks like, and what happens if one lookup fails.

13. Which statement about `query.live` is correct?

    - a\. It supports `.refresh()` to rerun the generator
    - b\. During SSR it yields its first value and closes; on the client it keeps one shared connection per key and exposes `.current` and `.connected`
    - c\. It delivers every intermediate value, even if the client is slow
    - d\. It should be cached in a service worker so it works offline

14. Inside a remote `query`, what happens when code reads `event.url`, `event.params` or `event.route`? What do those properties contain inside a `form` or `command`, why must they not be used for authorisation, and can a `command` call `redirect()`?

15. A remote function throws an unexpected error. What HTTP status does the response have, and what does this imply for monitoring?

16. Which statement about the remote `prerender` function is correct?

    - a\. It runs on every request and caches in memory
    - b\. It runs at build time, is excluded from the server bundle unless `dynamic: true`, and is the only remote read usable on fully prerendered pages
    - c\. It cannot take arguments
    - d\. It requires a service worker

17. Find the two bugs in this remote form. `ts // schema const schema = v.object({ title: v.string(), published: v.boolean() }); export const createPost = form(schema, async (data) => { /* ... */ });` `svelte <form {...createPost}> <input name="title" /> <input type="checkbox" name="published" /> <button>Save</button> </form>`

18. According to the published types, what options does a remote form’s `validate()` accept, and how does the documentation’s wording differ?

    - a\. `{ all?: boolean, preflightOnly?: boolean }`; the docs say `includeUntouched`
    - b\. `{ includeUntouched?: boolean }`; the docs agree
    - c\. `{ strict?: boolean }`; the docs say `all`
    - d\. No options at all

19. In a remote form handler, how do you report that an email is already registered, so that it shows up next to the right field? Why is `fail()` the wrong tool here?

20. After a remote form succeeds, which queries and loads are refreshed in each case: (a) the handler does nothing special; (b) the handler calls `void getPosts().refresh()`; (c) the handler is a `command` that does nothing special?

21. A client calls `await rename(data).updates(getViews)`. What must the server do for that to work, why is a number required, and what happens in SvelteKit 3 if a requested entry is neither refreshed, set, reconnected nor ignored?

22. In `sequence(a, b, c)`, handle `b` returns a 503 response without calling `resolve`. Which handles run, and does `a`’s post-processing code run? Does a request for `/static/logo.png` reach any of them?

23. After deploying behind a TLS-terminating load balancer, form POSTs fail with a 403 CSRF error in production only. Explain the cause, name two correct fixes for an adapter-node deployment, and say which “fix” to avoid.

24. In SvelteKit 3, which statement about `handleError` is correct?

    - a\. It is not called for errors you create with `error(404)`
    - b\. It is called for all errors with a `kind`, may return a `status`, and must never throw
    - c\. `handleValidationError` still handles validation failures of remote functions
    - d\. It replaces `+error.svelte`

25. Given `src/routes/+error.svelte`, `src/routes/app/+error.svelte` and `src/routes/app/+layout.server.ts` that calls `error(500, 'boom')`, which component renders? What renders if `src/routes/+layout.server.ts` throws? What renders for an error thrown inside `handle` before `resolve`?

26. Scenario: you run a SaaS app and must design error handling. Requirements: users see a short message and a request ID; unexpected errors alert the on-call engineer, expected 4xx do not; validation issues must never reach the user as raw schema output; the reporter (Sentry-style) must never break a response. Describe your `handleError`, the `App.Error` shape and the rules you apply.

27. Scenario: a regulated team may not use experimental APIs but wants typed, validated, progressively enhanced forms and expects to adopt remote forms in a year. What do you recommend now, and which boundary do you draw so the later migration touches wrappers only?

## Test 3: Rendering Modes, State, Environment, and Authentication

1.  A root layout exports `prerender = true`. One page below it has a `+page.server.ts` with `actions`. What happens at build time, and what are your options?

2.  A layout exports `ssr = false` and `prerender = false`; a nested page exports `ssr = true`. Which value applies to that page, and which rule decides it? Separately: what is the consequence of writing `export const prerender = process.env.PRERENDER === '1'` instead of a literal?

3.  A prerendered page reads `url.searchParams.get('q')` in `load`. What happens during the build, and what do you do if the page must react to `?q=`?

4.  The build fails with an HTTP 404 for `/legal`, which the footer links to but that does not exist yet. Name three distinct ways to resolve it and say which one you would pick for a typo and which for a deliberately external route.

5.  What does a page render when both `ssr = false` and `csr = false` are set?

    - a\. A blank shell with client-side hydration
    - b\. The prerendered markup without JavaScript
    - c\. Nothing useful: no server-rendered markup and no client-side JavaScript
    - d\. A 404

6.  You must ship a pure SPA to static hosting with `adapter-static`. What two things do you need, and why does the book recommend a hybrid (prerender public routes, SPA only the rest) when the app has public pages?

7.  A prerendered marketing page and a dynamic dashboard share a domain. Where do security headers (HSTS, `X-Content-Type-Options`, CSP for `frame-ancestors`) have to be set for the marketing page, and why does your `handle` not cover it? What does a prerendered page’s CSP look like and which directives does it ignore?

8.  The app is deployed under `https://example.org/app/` on a static host. Which options change, and what do you use instead of the removed `base` and `assets` exports to build a link and an asset URL?

9.  A shared module does this and is imported by the root layout, which is server-rendered.

    ```ts
    // src/lib/cart.svelte.ts
    export const cart = $state({ items: [] as { id: string }[] });
    ```

    A `load` pushes the current user’s items into it. Describe what goes wrong in production and give two safe designs.

10. Where should state live if it must survive a reload, be shareable via link and influence server rendering?

    - a\. A `.svelte.ts` singleton
    - b\. `sessionStorage`
    - c\. The URL (path or search params), validated on read
    - d\. A cookie set with JavaScript

11. A photo gallery opens a modal using `goto(href, { shallow: true, state: { photoId } })`. What does `page.state` contain during SSR and after a hard reload (without `persistState`)? What do `beforeNavigate` and friends do for such a navigation? What should the page offer so shared links work?

12. Convert this SvelteKit 2 snippet to SvelteKit 3, and say what changed about `page.url`. `svelte <script> import { page, navigating } from '$app/stores'; </script> {#if $navigating}<Spinner />{/if} <p>{$page.url.pathname}</p>`

13. Which statement about `snapshot()` is true?

    - a\. It persists to `localStorage` as JSON
    - b\. It is called during component initialisation, captures and restores ephemeral UI state per history entry via devalue-serialised `sessionStorage`
    - c\. It only works in `+page.svelte`
    - d\. It is the recommended way to store the authenticated user

14. Write the `src/env.ts` declaration for: a private `DATABASE_URL` that must be a URL; a public `PUBLIC_API_BASE` fixed at build time; and a public `PUBLIC_FEATURE_BANNER` that may change per deployment without a rebuild. Show how server code imports the first one.

15. Which of these modules are protected as server-only in SvelteKit 3?

    - a\. `src/lib/db.server.ts`
    - b\. `src/lib/auth/server/hash.ts`
    - c\. `src/lib/serverless.ts`
    - d\. a and b only

16. All unit tests pass, but a production build fails because a component imports `#lib/server/db.js`. Why did Vitest not catch it, and how do you enforce the rule in CI?

17. `DATABASE_URL` is required at runtime but is absent in the CI build, and the build fails while analysing a prerendered route. What is the right fix, and what must `src/env.ts` not import?

18. When are invalid values detected for (a) a static variable and (b) a dynamic variable? Which kind would you use for a secret that differs between staging and production when you want to promote one build?

19. In production on adapter-node there is no `.env` loading. How do you supply a file, and what does SvelteKit’s `.env` loading apply to?

20. A project uses `$env/static/private` in 140 files. Describe a safe, incremental migration path to SvelteKit 3’s model and why it is “declare first”.

21. For a first-party web app with server-rendered pages, argue for opaque server-side sessions rather than JWTs, and say what the database should store.

22. What is wrong with this cookie, and what are SvelteKit 3’s defaults? `ts cookies.set('session', token, { httpOnly: false, sameSite: 'none' });`

23. A `handle` hook redirects anonymous users away from paths starting with `/admin`. A team adds an admin-only remote function and considers it protected. Is it? Explain, and show the fix. `ts // src/routes/admin/invoices.remote.ts export const getInvoices = query(async () => db.invoices());`

24. Write a rule for validating a `next` query parameter before redirecting after login. Why is SvelteKit 3’s refusal of external `redirect()` targets not a substitute?

25. In an OAuth/OIDC login implemented with two `+server` endpoints, what do you store in short-lived cookies at the start endpoint, what do you verify in the callback, and why should the local user be keyed by `(provider, subject)` instead of by email?

26. Scenario: you are building a site with public marketing pages, a documentation section generated from content files, a logged-in dashboard and an embeddable widget for partners. For each part choose rendering options (`prerender`, `ssr`, `csr`, `embedded`), say where the options are exported, and name two pitfalls of mixing them.

27. Scenario: users occasionally see another user’s name in the header in production, and it never reproduces in dev. List the three most likely causes you would check in this codebase, and the fix for each.

## Test 4: Security, Performance, Observability, and Adapters

1.  Under which condition does SvelteKit add a nonce or hash source for the inline scripts it emits?

    - a\. Always, whatever your policy says
    - b\. When your effective script policy does not contain `'unsafe-inline'` (or contains `'strict-dynamic'`)
    - c\. Only for prerendered pages
    - d\. Only in development

2.  Your `app.html` contains an inline analytics bootstrap with `nonce="%sveltekit.nonce%"`, and several routes are prerendered. What goes wrong, and what are your options?

3.  A developer configures `csp: { reportOnly: { 'script-src': ['self'] } }` and nothing else. What happens, and what must be added?

4.  Which two source names must appear in `trusted-types` when you enable Trusted Types, and under which conditions is each one required?

5.  Production app, `csrf` left at defaults, app origin `https://app.example.com`. For each request, say whether SvelteKit’s built-in CSRF check rejects it, and what else protects (or fails to protect) you:

    - a\. A form-encoded `POST /settings` from `https://evil.example` with the user’s cookies
    - b\. A cross-origin `fetch` with `Content-Type: application/json` to a `+server` `POST` endpoint
    - c\. A cross-origin `POST` with no `Content-Type` header
    - d\. A cross-origin remote function call from an origin listed in `csrf.trustedOrigins`

6.  An endpoint `GET /api/preview?url=` fetches the given URL server-side and returns its title. List four controls that make it safe against SSRF, and say where in SvelteKit you could centralise one of them.

7.  What is wrong with this load, and why do server-only modules not save you?

    ```ts
    // src/routes/account/+page.server.ts
    import { db } from '#lib/server/db.js';
    export const load = async ({ locals }) => {
     return { user: await db.user.findUnique({ where: { id: locals.user!.id } }) };
    };
    ```

8.  Name four inputs an attacker controls in a SvelteKit 3 app using remote functions and `adapter-node`, together with the bound you apply to each.

9.  What does `output.linkHeaderPreload: true` do, and why is it `false` by default in SvelteKit 3?

    - a\. It preloads fonts automatically through `Link` headers on every response
    - b\. It sends preload hints for JS and CSS as a `Link` header on dynamically rendered pages instead of `<link>` elements, at the risk of oversized headers
    - c\. It re-enables the removed `preloadStrategy` option
    - d\. It prefetches all routes

10. A category page lists 100 product links, each with a database-backed `load`. Hover preloading is hammering the database. How do you reduce the cost without losing code preloading, and which condition disables preloading entirely?

11. What is wrong here, and what two limits of `setHeaders` apply? `ts export const load = async ({ setHeaders, locals }) => { setHeaders({ 'cache-control': 'public, max-age=300' }); return { user: locals.user, items: await listItems() }; };`

12. Which statement about HTML `ETag`s is correct?

    - a\. Streamed pages get a strong `ETag` computed incrementally
    - b\. Non-streamed SSR pages get an HTML-hash `ETag` and `If-None-Match` yields `304`, which saves bandwidth but not render CPU
    - c\. `ETag`s are only generated for prerendered pages
    - d\. `__data.json` responses are cached for a day by default

13. A universal `load` calls `fetch('/api/prices')`, and the endpoint answers with `Cache-Control: max-age=30`. After hydration the user triggers `invalidate` several times in 10 seconds. What does the browser do, and what should you not rely on this for?

14. Pick an image strategy for each: (a) the logo in the repository; (b) forty editorial photos that live in the repository; (c) user-uploaded avatars stored in object storage.

15. In SvelteKit 3, where does a service worker import each of these from: `version`, the list of immutable build files, the list of static files, a base-aware path, and the typed `self`? Which kinds of request should it never cache?

16. With `tracing: { server: true }` and `export const handle = sequence(first, second)`, what is the observed span chain from the root down to a server `load`? What do `event.tracing.root` and `event.tracing.current` let you do, and what must you use to create a child span?

17. `NodeSDK` is configured with the `pg` instrumentation but no database spans appear. Name the three things you check.

18. Why should log lines and metrics use `event.route.id` instead of the URL as a label, and what should you scrub from span attributes?

19. Name three pieces of client-side observability that SvelteKit does not provide by itself, and the primitives you use for each.

20. adapter-node sits behind three trusted proxies and `ADDRESS_HEADER=x-forwarded-for`. The header reads `1.2.3.4, 198.51.100.9, 203.0.113.7, 10.0.0.5`. Which `XFF_DEPTH` do you set, which address is the client, and why is reading the left-most address wrong?

21. Scenario: after moving to Cloud Run, deploys sometimes lose the last few seconds of traces and database connections are closed uncleanly. The app uses `query.live`. Diagnose using adapter-node’s shutdown model and propose settings.

22. Choose an adapter for each, with one sentence of justification: (a) SSR app with Postgres, `query.live` and background workers on Cloud Run; (b) a documentation site; (c) an app that must use KV and run at the edge on Cloudflare; (d) an existing app that used the `edge` runtime on Vercel.

23. Port this SvelteKit 2 adapter-cloudflare code to SvelteKit 3, and say what must be installed and run to get types. `ts export async function GET({ platform, request }) { const value = await platform!.env.KV.get('k'); platform!.context.waitUntil(log(value)); const country = platform!.cf.country; const cached = await platform!.caches.default.match(request); return new Response(value); }`

24. Which statement about ISR with `adapter-vercel` is correct?

    - a\. It is safe for routes that render the logged-in user’s name
    - b\. It requires the `edge` runtime
    - c\. It has no effect on prerendered routes, needs a `bypassToken` of at least 32 characters for on-demand revalidation and Draft Mode, and is only safe where all visitors see identical content
    - d\. It ignores `allowQuery`

25. What does a custom adapter’s `adapt(builder)` have to produce, how does the generated server instance get used at runtime, and what are `emulate()` and `supports` for?

26. Scenario: a news site wants article pages cached at a CDN for five minutes, but logged-in readers see a personalised “recommended for you” strip. Design the page so the HTML stays cacheable and the personalised part cannot leak between users.

27. Scenario: you run containers with rolling deploys. A remote function’s argument shape changes, and users with open tabs get errors during the rollout. Design the skew strategy: detection, asset retention, compatibility rules and user experience. What caveat applies if you were on Vercel with skew protection?

## Test 5: Libraries, Testing, Migration, and Cross-Cutting Design

1.  Write the `package.json` fields a SvelteKit component library needs so that consumers get types and Svelte components, that CSS is not tree-shaken away, and that spec files are not published. Assume one entry point and a `dist` output folder.

2.  A library source file contains `import { fmt } from '#lib/util/format.js';` and another contains `import { helper } from './helpers';` (a `helpers.ts` file). What does `svelte-package` do with each, and which one is a bug?

    - a\. It rewrites the `#lib` import to a relative path and the extensionless import breaks consumers; the second is the bug
    - b\. It rewrites neither, and both break
    - c\. It rewrites the extensionless import and leaves `#lib`
    - d\. It bundles both into one file

3.  A UI library’s `Breadcrumbs.svelte` imports `page` from `$app/state` and calls `goto` from `$app/navigation`. Name two problems and a redesign that keeps the component usable in plain Svelte and in SvelteKit apps.

4.  You want a library to ship a remote function and a server-only helper. What must the library’s `package.json` declare, where must the remote file not live, and why does a published server-only file need an explicit import?

5.  After enabling `declarationMap`, editors still jump to `.d.ts` files rather than your sources. What did you forget?

6.  Write a Vitest test (server project) for `requireUser()`, a helper built on `getRequestEvent()` that redirects anonymous users. Show the mock and the assertion for the redirect.

    ```ts
    // src/lib/server/auth/guards.ts
    import { getRequestEvent } from '$app/server';
    import { redirect } from '@sveltejs/kit';
    export function requireUser() {
     const { locals, url } = getRequestEvent();
     if (!locals.user) redirect(303, `/login?next=${encodeURIComponent(url.pathname)}`);
     return locals.user;
    }
    ```

7.  Write an integration test for this `Handle` that does not start a server. State what you must construct and what you stub.

    ```ts
    export const security: Handle = async ({ event, resolve }) => {
     const response = await resolve(event);
     response.headers.set('x-content-type-options', 'nosniff');
     return response;
    };
    ```

8.  A `load` calls `error(404, 'Not found')` for unknown slugs. Show a robust unit-test assertion, and say why `expect(...).rejects.toThrow('Not found')` is a poor choice.

9.  Playwright tests click a form button immediately after `page.goto`, and sometimes the form does a full-page POST instead of an enhanced submission, sometimes passing for the wrong reason. Explain the race and give two remedies.

10. Why does the book run E2E against `vite preview` of a production build rather than `vite dev`? Name two further practices for the E2E suite (authentication, no-JS, upstreams, console).

11. Which sequence is the recommended upgrade path from SvelteKit 2?

    - a\. Run the codemod first, then upgrade Node and fix whatever breaks
    - b\. Latest 2.x and fix deprecation warnings, raise Node/TypeScript/Svelte/Vite/plugin versions, run the codemod, resolve the manual checklist, test against a production build and staging, then deploy with the 2.x deployment available for rollback
    - c\. Switch to the 3.x adapters first, then change config
    - d\. Upgrade only `@sveltejs/kit` and let the CLI migrate everything at first build

12. Match each `sv migrate sveltekit-3` task to its purpose: consolidating `src/params/*`; replacing `$lib`; `$app/stores` to `$app/state`; writing a list of things that could not be automated; opting existing external redirects in.

13. Port this SvelteKit 2 configuration to SvelteKit 3. Which line has no equivalent, and what replaces it? `js // svelte.config.js import adapter from '@sveltejs/adapter-node'; import { vitePreprocess } from '@sveltejs/vite-plugin-svelte'; export default { preprocess: vitePreprocess(), kit: { adapter: adapter(), csrf: { checkOrigin: false }, prerender: { origin: 'https://shop.example' }, files: { lib: 'src/lib' }, experimental: { tracing: { server: true }, instrumentation: { server: true } } } };`

14. Name four changes in SvelteKit 3 that compile and type-check but change runtime behaviour, and say how you would detect each in a staging environment.

15. After the upgrade, the on-call channel is flooded with alerts from this hook. What changed, and how do you fix it? `ts export const handleError: HandleServerError = ({ error, event }) => { Sentry.captureException(error); return { message: 'Something went wrong' }; };`

16. How does a remote `form` still work with JavaScript disabled? What do the spread attributes provide, and what does the browser do on submit when JavaScript is available?

17. A client does `await save(data).updates(getPosts({ page: 1 }), getPosts({ page: 2 }), getPosts({ page: 3 }), getPosts({ page: 4 }))`. The server loop is `for (const entry of requested(getPosts, 3)) entry.refreshAll();`. What happens to the fourth entry? What is the correct value for the limit, and why is it mandatory?

18. Order these client-side navigation events: `afterNavigate`, DOM update, `beforeNavigate`, the batched `__data.json` request, `onNavigate`. Where do view transitions plug in?

19. A teammate suggests caching `__data.json` at the CDN for ten minutes. Why does SvelteKit send it as `private, no-store`, and what header tells the server which loads the client already has?

20. What is true of `router.resolution: 'server'`?

    - a\. Route lookups go through your `handle` hook
    - b\. Route lookups are answered on the server before `handle` (the manifest is not shipped to the browser), and `reroute` still applies
    - c\. It disables client-side navigation
    - d\. It requires the hash router

21. `goto('/downloads/report.pdf')` rejects, although the file exists under `static/`. Why, and what do you do instead?

22. Rewrite for SvelteKit 3: `import { base, assets, resolveRoute } from '$app/paths'; const href = base + resolveRoute('/blog/[slug]', { slug }); const img = assets + '/logo.png';`. Note the leading-slash rule.

23. List five features deprecated in 3.x that will disappear in v4, and one enforcement mechanism to keep new code from using them.

24. Scenario: migrate a 300-route SvelteKit 2.x application (adapter-vercel with an edge function, `$app/stores` everywhere, per-file param matchers, `ORIGIN`-based CSRF behind Cloudflare, an experimental remote-functions feature, Sentry) to 3.x. Give an ordered plan with checkpoints, what you test beyond CI, and the rollback strategy.

25. Scenario: design the test strategy for a multi-tenant SaaS app that uses actions, remote functions and `handle`-based auth. Name the levels, what each covers, what you mock, how you treat the experimental remote functions, and which suite guards tenant isolation.

26. Scenario: you maintain a design-system library that currently imports `$app/state` and `$lib` inside components. Describe the refactor to make it publishable, including package layout, public API for navigation-aware components, and release checks.

27. Review this `+page.server.ts` and list every problem. `ts import { redirect } from '@sveltejs/kit'; import { SESSION_SECRET } from '$env/static/private'; export const prerender = true; export const actions = { default: async ({ request, cookies }) => { const d = await request.formData(); cookies.set('theme', String(d.get('theme'))); cookies.set('sig', sign(String(d.get('theme')), SESSION_SECRET)); throw redirect(303, String(d.get('next'))); } };`

## Test 6: Expert Level: Internals, Failure Modes, and Architecture

1.  An in-memory rate limiter in `handle` counts requests per client IP. After a page with three `event.fetch('/api/...')` calls in its `load` ships, legitimate users hit the limit after a quarter of the expected traffic. Explain the cause in terms of the request pipeline and give the precise fix.

2.  A developer writes `reroute` to run an A/B experiment: `return Math.random() < 0.5 ? '/pricing-b' : undefined;`. Give two independent reasons why this is wrong.

3.  Given the following, which `preload`, which `filterSerializedResponseHeaders` and what `transformPageChunk` order apply to the rendered page?

    ```ts
    export const handle = sequence(
     ({ event, resolve }) => resolve(event, { filterSerializedResponseHeaders: (n) => n === 'etag', transformPageChunk: ({ html }) => html.replace('%A%', 'a') }),
     ({ event, resolve }) => resolve(event, { preload: ({ type }) => type === 'js', transformPageChunk: ({ html }) => html.replace('%B%', 'b') }),
     ({ event, resolve }) => resolve(event, { preload: () => true, filterSerializedResponseHeaders: () => true, transformPageChunk: ({ html }) => html.replace('%C%', 'c') })
    );
    ```

4.  `handle` calls `error(403, 'Nope')` before `resolve` for a path under `/internal`. What does a browser navigation (`Accept: text/html`) see, what does `fetch` with `Accept: application/json` receive, and is `+error.svelte` involved in either?

5.  A server `load` returns `{ stats: compute().then((s) => { cookies.set('seen', '1', { path: '/' }); return s; }) }`. What happens to the cookie, and what is the general rule?

6.  Which of the four changes rerun this load: (i) `?sort=asc` to `?sort=desc` with `q` unchanged; (ii) `?q=a` to `?q=b`; (iii) a navigation that only changes the hash; (iv) a navigation from `/p/1` to `/p/2` (same route)? Also say what is not tracked in the `.then` callback.

    ```ts
    // src/routes/p/[id]/+page.server.ts
    export const load = async ({ url, params, untrack }) => {
     const q = url.searchParams.get('q');
     const sort = untrack(() => url.searchParams.get('sort'));
     const rows = search(params.id, q, sort);
     return { rows, later: rows.then(() => url.pathname) };
    };
    ```

7.  A remote form handler must make an active `query.live` ticker deliver a fresh value immediately in the same response. Which approach is right?

    - a\. `ticker().refresh()`
    - b\. `ticker().reconnect()`, because live queries have no `.refresh()`
    - c\. `invalidate('ticker')`
    - d\. Nothing: live queries ignore mutations

8.  A server `load` returns a `Money` class instance. Write the `src/hooks.ts` `transport` entry that lets it cross the wire, and name two other places that use the same transport.

9.  A fully prerendered marketing page calls a plain remote `query` for a price list. What happens, and which alternatives would you use?

10. Find the authorisation hole and fix it. `ts // src/routes/[tenant]/members/members.remote.ts export const removeMember = command(v.string(), async (memberId) => { const { params, locals } = getRequestEvent(); if (locals.user?.tenant !== params.tenant) error(403); await db.members.delete({ where: { id: memberId } }); });`

11. One image is built once and promoted from staging (`https://staging.example`) to production (`https://app.example.com`) behind a TLS-terminating proxy, and form POSTs fail CSRF on one of them. Why is `paths.origin` a poor fit, and what do you set instead on adapter-node?

12. Why are results of a remote `prerender` function stored in the browser cache per deployment version, and what would go wrong without that?

13. After a deploy, the container writes `robots.txt` into the `build/client` directory at start-up, but it returns 404; a monitoring agent `POST`s to a static asset path and gets 405. Explain both using adapter-node’s static-asset model, and the supported alternative for runtime configuration.

14. `fs.readFile('static/data.json')` works with adapter-node but fails on Cloudflare. What do you use instead, which module provides it, and which adapter capability flag declares support for it?

15. In which order must a custom adapter that supports server instrumentation call `builder.createInstrumentationInitializer`, the bundling step and `builder.instrument`, and what is passed to `instrument`?

16. A cart page has `<form method="POST" action="/checkout?/pay" use:enhance>`. In SvelteKit 3, what happens after a successful result, what happens when the action returns `fail(402, ...)`, and how do you keep the old “stay on the page” behaviour?

17. A helper in `src/lib/seo.ts` imports `page` from `$app/state` and is called from a `+page.server.ts` load. What goes wrong, and what do you use?

18. Which of these are build errors when imported from browser code?

    - a\. `src/lib/server/db.ts`
    - b\. `src/lib/ui/server/Chart.svelte`
    - c\. `src/routes/server/helpers.ts`
    - d\. a and b, but not c

19. Find the bug and describe its symptom. `ts export const actions = { default: async ({ request }) => { try { const form = await request.formData(); await save(parse(form)); redirect(303, '/done'); } catch (e) { logger.error(e); return fail(500, { message: 'Could not save' }); } } };`

20. Why does the capstone’s tenant resolution answer `404`, not `403`, for a tenant the user is not a member of? Where does that check run, and why is it a safe authorisation boundary for remote function calls too?

21. Scenario: in a multi-tenant app, a single forgotten `where tenant_id = ...` has leaked data before. Design the defence in depth: data access API, database, remote function arguments, destructive commands and tests.

22. Write a concise architecture decision record (context, decision, consequences) for “Where authentication and authorisation run” in a SvelteKit 3 app that uses `handle`, layouts, actions, `+server` endpoints and remote functions.

23. Scenario: you are the release owner. Name the signals that gate promotion of a canary revision on Cloud Run and the alerts you keep afterwards, and say which commonly used signal is misleading for remote functions and why.

24. Scenario: after a deploy, p95 latency doubled on all pages and the database shows four session lookups per page view. Tracing shows `sveltekit.handle.root` spans nested with `sveltekit.is_sub_request`. Diagnose and give two fixes.

25. Synthesis: trace a remote `form` submission with JavaScript enabled from click to updated UI, naming every SvelteKit mechanism it passes through (CSP, CSRF, `handle`, validation, authorisation, handler, single-flight, errors, tracing).

26. Scenario: on staging, streamed `load` promises and a `query.live` ticker appear to arrive all at once at the end of the response. Explain the likely causes along the path and how you verify and fix each.

27. Review this hooks file and list every defect. `ts // src/hooks.server.ts let requestCount = 0; export const handle: Handle = async ({ event, resolve }) => { requestCount++; event.locals.user = await getUser(event.cookies.get('session')); if (event.url.pathname.startsWith('/admin') && !event.locals.user?.admin) { return new Response('Forbidden', { status: 403 }); } const response = await resolve(event); response.headers.set('cache-control', 'public, max-age=60'); return response; }; export const handleFetch: HandleFetch = ({ request, fetch }) => fetch(new Request(request, { headers: { ...request.headers, authorization: TOKEN } }));`
