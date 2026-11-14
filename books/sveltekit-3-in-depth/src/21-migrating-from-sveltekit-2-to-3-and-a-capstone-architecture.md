# Chapter 20: Migrating from SvelteKit 2 to 3, and a Capstone Architecture

This final chapter does two jobs. The first half is a migration guide: how to upgrade an existing SvelteKit 2 application to 3.x in a controlled order, what each breaking change looks like before and after, which parts of `npx sv migrate sveltekit-3` are automated, and what you must do by hand. The second half is a capstone: a reference architecture for a multi-tenant dashboard that applies the material of the previous nineteen chapters, with decision records for state, caching, errors and security headers, followed by a rollout and test plan and a recap of the mental model.

The migration material comes from the official migration guide, the 3.0.0 changelog and the `sv migrate` tool itself (I listed its tasks from `sv` 1.1.1). The capstone is a design, not an official recipe; where I choose between valid options I say so and label it author practice.

## Part 1: Migrating to SvelteKit 3

### Strategy

SvelteKit 3.0 is a cleanup release: it removes things deprecated during 2.x, moves configuration into Vite, raises toolchain minimums and changes a handful of defaults. Most apps need mechanical changes, but the *ordering* matters because the toolchain upgrade is a prerequisite for everything else.

My recommended sequence (author practice, built on the official advice):

1.  **Land on the latest 2.x first.** The guide recommends this so that you see targeted deprecation warnings. Fix every warning on 2.x; each one is a change you then do not mix with the major upgrade. Make sure CI is green.
2.  **Upgrade the platform.** Node 22.17 or newer everywhere: laptops, CI, Docker base images, hosting runtime settings (Vercel project Node version, Netlify). This is independent of SvelteKit and can ship first.
3.  **Run the codemod on a clean branch.** `npx sv migrate sveltekit-3` (it checks for a dirty git tree unless told not to).
4.  **Resolve the manual checklist** (below).
5.  **Build, test against a production build, deploy to staging, compare.**
6.  **Schedule the follow-ups**: deprecations that still work in 3.x but disappear in 4.

Minimum versions in 3.x:

| Dependency | Minimum |
|------------------------------------|------------------------------------|
| Node | 22.17 |
| TypeScript | 6 |
| Svelte | 5.57.1 |
| Vite | 8.0.12 (first Vite 8 with stable Rolldown 1.0) |
| `@sveltejs/vite-plugin-svelte` | 7 |
| First-party adapters | their 3.x-compatible majors (all require SvelteKit 3) |

The versions I verified in October 2026 are SvelteKit 3.1.0, Svelte 5.57.2, Vite 8.3.x and vite-plugin-svelte 7.3.1. Third-party Vite plugins and adapters must support Vite 8; check each one before you begin, because Vite 8 replaces Rollup with Rolldown and plugins that reach into Rollup internals can break.

### What the codemod does

`npx sv migrate sveltekit-3` is a task-based migration. Running it with `--tasks` and no names lists the tasks. This is the list from `sv` 1.1.1:

| Task | What it does |
|------------------------------------|------------------------------------|
| `package-json` (prerequisite) | Updates `package.json` for SvelteKit 3 |
| `tsconfig` (prerequisite) | Switches to extending `$app/tsconfig` instead of `.svelte-kit/tsconfig.json` |
| `svelte-config` | Migrates `svelte.config.*` into `vite.config.*` |
| `environment` | Migrates to explicit env vars (`$app/env`) |
| `paths` | Migrates deprecated `$app/paths` APIs and path types |
| `external-redirects` | Opts existing external redirects into the new behaviour |
| `shallow-routing` | Migrates `pushState`/`replaceState` to `goto()` |
| `params` | Consolidates `src/params/*` matchers into `src/params.ts` or `.js` |
| `imports` | Moves APIs to their new modules (hook types, params, env, remote types) |
| `lib-alias` | Replaces `$lib` with `#lib` subpath imports |
| `app-state` | Migrates `$app/stores` to `$app/state` |
| `collect-migration-instructions` | Writes `MIGRATION_TASKS.md` listing what could not be automated |

Use `--tasks all` to run everything, or name the tasks you want. `--files <glob>` restricts the files touched, `--no-install` skips the package-manager step, `--confirm` skips the final prompt, and `--cwd` points at a project. For a large app I run tasks one at a time and commit between them so each diff is reviewable:

```bash
git switch -c sveltekit-3
npx sv migrate sveltekit-3 --tasks package-json tsconfig --no-install
npm install
npx sv migrate sveltekit-3 --tasks svelte-config lib-alias imports params paths
git add -A && git commit -m "mechanical migration"
npx sv migrate sveltekit-3 --tasks collect-migration-instructions
# follow MIGRATION_TASKS.md
```

(Task names are exactly as listed by the tool; I did not run the codemod against a real SvelteKit 2 application while writing this, so treat the per-task commands as the documented interface and review every diff.) The `collect-migration-instructions` task is the honest part of the design: it acknowledges that some changes are semantic and generates a checklist rather than guessing.

**Codemod limits.** It rewrites syntax it can recognise. It cannot decide whether your `handleError` should now triage by `kind`, whether a `resolve()` call needs symmetric matchers, whether your adapter-node deployment needs `paths.origin`, or whether a test asserted on a status that changed. Anything about *runtime behaviour* is yours.

### The breaking changes, with before and after

I group them by the part of the system they touch. All of this is from the official migration guide unless marked.

#### Configuration moves into Vite

`svelte.config.js` is no longer read. Everything is an option of the `sveltekit()` plugin, and the former `kit.*` options are top-level:

```js
// svelte.config.js (SvelteKit 2)
import adapter from '@sveltejs/adapter-auto';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

export default {
    preprocess: vitePreprocess(),
    compilerOptions: { experimental: { async: true } },
    kit: {
        adapter: adapter(),
        experimental: { remoteFunctions: true }
    }
};
```

```ts
// vite.config.ts (SvelteKit 3)
import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-auto';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [
        sveltekit({
            adapter: adapter(),
            preprocess: vitePreprocess(),
            compilerOptions: { experimental: { async: true } },
            experimental: { remoteFunctions: true }
        })
    ]
});
```

Removed options: `files.lib`, `experimental.handleRenderingErrors` (now default behaviour), `experimental.instrumentation` (automatic when `src/instrumentation.server.*` exists), `experimental.tracing` (now `tracing: { server: true }`), `vitePlugin` (pass vite-plugin-svelte options such as `inspector` straight to `sveltekit()`), `preloadStrategy` (always `modulepreload`), `prerender.origin` (use `paths.origin`) and `csrf.checkOrigin` (use `csrf.trustedOrigins`). New: `output.linkHeaderPreload` (opt-in `Link` headers), `csrf.trustedOrigins`, `paths.origin`. Changed default: `version.pollInterval` is now one hour.

Deprecated but still working, scheduled for removal in 4: `files.*` (except the removed `lib`), `alias` (prefer `imports` or Vite `resolve.alias`) and `typescript.config`. Tools that read `svelte.config.js` directly (older ESLint plugins, editor extensions, Storybook setups) need updates; `svelte-check` and the Svelte language server must be recent enough to understand the new location.

#### `$lib` becomes `#lib`

SvelteKit no longer generates the alias. Declare it in `package.json` using Node subpath imports, which Vite and TypeScript resolve natively:

```json
{
    "imports": {
        "#lib": "./src/lib/index.js",
        "#lib/*": "./src/lib/*"
    }
}
```

and replace usages **with extensions**:

```ts
// before
import { foo } from '$lib/foo';
// after
import { foo } from '#lib/foo.js';
```

Two practical notes. First, for a TypeScript source file `foo.ts` the specifier is still `#lib/foo.js`. Second, the `imports` entries are exact: `#lib` maps to the index file, `#lib/*` to the directory. If your `src/lib/index` is a `.ts` file, the first mapping should point at `./src/lib/index.ts` (the sv scaffold I generated used `./src/lib/index.js` with a TypeScript project and worked for type-resolution because the scaffold’s `index.ts` was resolved through TypeScript; verify your own mapping by building). Libraries get `#` imports rewritten to relative paths by `svelte-package` (Chapter 19).

#### Modules and APIs

**`$app/environment` becomes `$app/env`** (`browser`, `dev`, `building`, `version`) and can now be imported in service workers. The old module still exists but is deprecated, as are all `$env/*` modules; see the environment section below.

**`$app/stores` is removed.** Use `$app/state` and drop the `$`:

```html
<script lang="ts">
    // before: import { page } from '$app/stores';  ... {$page.url.pathname}
    import { page } from '$app/state';
</script>

<p>current pathname: {page.url.pathname}</p>
```

There is a dedicated codemod task (`app-state`, also runnable as `npx sv migrate app-state`). Watch for two follow-ups: `page.url` is now a `ReadonlyURL`, so `page.url.searchParams.set(...)` is a type error (copy with `new URL(page.url.href)`), and derived store usage (`$derived($page...)` patterns, `get(page)` in non-component code) needs manual rewriting.

**`$app/paths`.** `base`, `assets` and `resolveRoute` are removed. Use `resolve()` and `asset()`:

```ts
// before
const pathname = base + resolveRoute('/blog/[slug]', { slug });
const file = assets + '/foo.png';
// after
const pathname = resolve('/blog/[slug]', { slug });
const file = asset('foo.png');
```

The types `Pathname` and `Asset` are now `Path` and `AssetPath`, and they have **no leading slash**: `asset('/foo.png')` becomes `asset('foo.png')`, and pathnames passed to `resolve` such as `resolve('blog/hello-world')` no longer start with `/`. Only route IDs do. This is a quiet source of bugs in string-built URLs.

**`$service-worker` is removed.** The mapping: `version` from `$app/env`; `immutable`, `assets`, `prerendered` from `$app/manifest`; `resolve()` from `$app/paths` replaces `base` handling. (The migration guide’s sentence says `resolved` from `$app/paths`; the service worker example in the docs and the module’s API use `resolve`, so I treat `resolved` as a typo.) Add `src/service-worker/tsconfig.json` extending `$app/tsconfig/service-worker` and exclude `src/service-worker` from the root tsconfig. The service worker is now registered as a module (`type: 'module'`), so any `importScripts` usage must go.

**`$app/navigation`.**

```ts
// shallow routing, before
pushState('/foo', state);
replaceState('/bar', state);
// after
goto('/foo', { shallow: true, state });
goto('/bar', { shallow: true, replace: true, state });
```

`persistState: true` reapplies `page.state` after reload. Shallow navigations now fire `beforeNavigate`, `onNavigate` and `afterNavigate`; filter with the `shallow` property if you do not want to react. `invalidateAll` is deprecated in favour of `refreshAll`, which does not reset `page.state`; calling `invalidate`/`invalidateAll` during an in-flight navigation no longer aborts it. `goto` options: `invalidateAll` is now `refreshAll`, `keepFocus: true` plus `noScroll: true` is `reset: false`, `replaceState` is `replace`. `goto` rejects for URLs that do not resolve to a route (use `window.location.href` for externals). `navigation.delta` exists only for `popstate`. `preloadData` can return `{ type: 'error', status, error }`: add that branch.

**`$app/forms`.** An enhanced form whose `action` targets a different page now navigates to that page after submission, matching native behaviour. Enhanced responses also use the HTTP status you pass to `fail(...)` rather than always 200: update `use:enhance` callbacks and tests that inspected statuses.

**`@sveltejs/kit` and subpaths.**

- `error`, `isHttpError`, `redirect`, `isRedirect` now refer to public types. Stop importing internal `HttpError`/`Redirect` classes or using `instanceof`; use the guards.
- `json()` and `text()` are deprecated: `Response.json(...)` and `new Response(text)`.
- Hook types move: `Handle`, `HandleFetch`, `HandleServerError`, `HandleClientError`, `Reroute`, `Transport`, `ServerInit`, `ClientInit`, `ResolveOptions` come from `@sveltejs/kit/hooks`. `defineParams` lives in `@sveltejs/kit/params`; `defineEnvVars` and `EnvVarConfig` in `@sveltejs/kit/env` (and `defineEnvVars` is no longer exported from `@sveltejs/kit/hooks`). Remote function types (`RemoteQuery`, `RemoteForm`, `RemoteCommand`) come from `$app/server`.
- `@sveltejs/kit/node`: `getRequest` and `setResponse` are synchronous; remove `await`. `@sveltejs/kit/node/polyfills` is gone; delete those imports from custom servers.

The `imports` codemod task handles the module moves.

#### Security and cookies

- `csrf.checkOrigin: false` is gone. CSRF protection is always on; allow other origins with `csrf.trustedOrigins`. Cross-origin mutating requests with no `Content-Type` header are now rejected, so non-browser clients (webhooks, `curl`) that POST without a content type to form endpoints will start failing.
- In dev, SvelteKit no longer adds `access-control-allow-origin: *` to static assets; set Vite `server.cors` if you need it.
- Cookies use `cookie` v2: names must be ASCII only; types renamed to `SerializeOptions` and `ParseOptions`; and when `path` is omitted it defaults to `'/'` (it was previously required in 2.x).
- External redirects must be opted in: `redirect(307, 'https://example.com', { external: true })`, or an allow-list array. `javascript:` URLs stay blocked unless listed explicitly in the array form. The `external-redirects` task finds existing ones.

#### Errors and hooks

This is the area with the largest semantic change:

- `App.Error` always has `status` and `message`.
- `error(status, message, props)`: the second argument must now be a string; extra properties go in a third argument.
- `handleValidationError` is removed; validation errors arrive in `handleError` with `kind: 'validation'` and `issues`.
- **`handleError` receives all errors**, including expected `error(...)` ones, and can return a `status` to control the response code. A 2.x `handleError` that logged everything as a failure will now log every 404. Add a `kind` switch (Chapter 17).
- Rendering errors always flow through `handleError` and into an automatically created boundary per `+error.svelte`. An async `handleError` in `hooks.client` needs `compilerOptions.experimental.async`.
- Sourcemaps are applied to stack traces by default, subject to adapters not rebundling destructively; first-party adapters are still being refined here.
- `resolve` in `handle` is typed as always returning `Promise<Response>`.

#### Params

`src/params/*.js` matcher files are replaced with a single `src/params.ts`:

```ts
// src/params.ts
import { defineParams } from '@sveltejs/kit/params';
import * as v from 'valibot';

export const params = defineParams({
    integer: v.pipe(v.string(), v.toNumber()),
    fruit: (param) => (param === 'apple' || param === 'orange' ? param : undefined)
});
```

Matchers return a parsed value or `undefined`, or are Standard Schemas. If a matcher transforms (`toNumber`), the parsed value reaches `params` in your load functions as a number, and `resolve()` must be able to turn it back into a path segment; keep transforms symmetric (Chapter 3).

#### Server-only and remote modules

- Server-only filenames use a `server` segment rather than an infix: `stuff.server.ts`, `stuff.server.test.ts` and plain `server.ts` all count (previously `server.ts` did not). Any directory named `server` anywhere in the project (except `src/routes` and `static`) now counts, not only `src/lib/server`. Audit for modules that happen to live in a `server` directory but are meant to be shared with the browser: they now fail the import-chain check, or conversely a `server.ts` you imported on the client now errors.
- Likewise `remote` segments mark remote modules. Without `experimental.remoteFunctions`, such files error.
- Remote functions: `event.url`, `event.params` and `event.route` throw inside queries; `error` on remote resources is `App.Error | undefined`; form controls must use `field.as(...)`, and a hand-written `name` is rejected.

#### Observability

Instrumentation is automatic if `src/instrumentation.server.*` exists and the adapter supports it; tracing is `tracing: { server: true }` (Chapter 17).

#### Adapters

- **node**: bundling with Rolldown; `ORIGIN` removed (use `paths.origin`); static assets are served from a list recorded at build time (files added to the output afterwards are not served, replaced files keep old size and ETag, so use environment variables for runtime configuration, not files); static ETags are content hashes and `Last-Modified` is no longer sent; static assets accept only GET and HEAD, others get 405.
- **cloudflare**: `env`, `waitUntil` and other `ctx` members from `cloudflare:workers`; `cf` on the request; `caches` global; Wrangler `^4.67.0`; run `wrangler types`.
- **netlify**: Frameworks API output, CLI 17.31.0+, es2022 edge target, `publish` as an adapter option rather than from `netlify.toml`.
- **vercel**: edge runtime removed.
- **Adapter authors**: adapters can add Vite plugins; `builder.config.kit` is gone (config is top-level); `createEntries` and `generateManifest` removed; `compress` returns a list; `mkdirp`/`rimraf` deprecated; `Server` class deprecated in favour of the generated instance; `instrument` now needs an initializer from `createInstrumentationInitializer` (Chapters 17 and 18).

#### Responses and miscellany

- A `204` (or any empty `2xx`) from `+server` now has no body.
- Clicking a link to the current location runs `refreshAll()`.
- `data-sveltekit-preload-data="off"` becomes `"false"` (and similarly for the other `data-sveltekit-*` attributes).
- A universal `config` takes precedence over a server `config`. If you export both, consolidate.
- Environment: the `$env/*` modules and `$app/environment` are deprecated in favour of `src/env.ts` with `defineEnvVars` and `$app/env/private`/`$app/env/public`. They still work, so you may defer this to a second pass, but the `environment` codemod task exists, and new code should use the new system (Chapter 13).

### Manual checklist and testing the migration

My ordered checklist (author practice):

1.  Toolchain: Node 22.17+ in CI, Docker, hosting; TypeScript 6; remove `@sveltejs/vite-plugin-svelte` pins below 7.
2.  `vite.config.ts` contains all configuration; `svelte.config.js` deleted; editor/lint tooling updated.
3.  `tsconfig.json` extends `$app/tsconfig` and has `include`/`exclude`; service worker has its own tsconfig; `paths`/`baseUrl` in tsconfig replaced by `imports` (they now produce a warning).
4.  `#lib` imports with extensions; `package.json` `imports` defined.
5.  Hook types from `@sveltejs/kit/hooks`; `handleError` triages by `kind`; `error()` calls use string messages.
6.  No `$app/stores`; `ReadonlyURL` fixes; `resolve()`/`asset()` replace `base`, `assets`, `resolveRoute`; no leading slashes.
7.  `goto`, shallow routing, `refreshAll` updates.
8.  Origin: `paths.origin` or proxy-header variables replace `ORIGIN`; forms tested behind your real proxy.
9.  CSRF: any intentional cross-origin form POST added to `csrf.trustedOrigins`; webhook callers send `Content-Type`.
10. Cookies: ASCII names, explicit `path` where you relied on the old default semantics.
11. External redirects opted in where intended.
12. Remote functions: both flags present; no `url`/`params`/`route` use inside queries; `field.as()` everywhere.
13. `server`-directory and filename audit.
14. Adapter-specific changes applied and the adapter’s own major upgraded.
15. Service worker: module registration, new imports.

**Test the migration like a release.** Run the unit suite, then the E2E suite against `vite build && vite preview`. Then deploy to staging and check things tests rarely cover: form POSTs through the real proxy (origin), `Set-Cookie` attributes, a deploy-skew scenario (open a tab, deploy, navigate), response status for enhanced form failures, error pages and logs (`handleError` volume will change), prerender output diff (compare file lists and a few HTML files before and after), bundle sizes, and the observability pipeline (traces still arriving, `service.version` right). Keep the 2.x deployment available for rollback until the new one has soaked.

### Deprecations to schedule for v4

These work in 3.x and are removal candidates: `$env/static/*` and `$env/dynamic/*`, `$app/environment`, `invalidateAll`, `pushState`/`replaceState`, `json()`/`text()` helpers, `files.*`, `alias`, `typescript.config`, `export const snapshot` (use `snapshot()`), `builder.mkdirp`/`rimraf`, the `Server` class, and the `adapter-cloudflare-workers` package. I keep a tracking issue with one checkbox per item and enforce progress with lint rules that ban the deprecated imports in new code.

## Part 2: Capstone architecture

The system: **Meridian**, a multi-tenant analytics dashboard. Organisations have members with roles. Users see tenant-scoped dashboards with live metrics, edit saved views, and administer members. It is deployed as containers on Cloud Run behind a load balancer, with Postgres in the same region. Requirements: tenant isolation (a bug must not leak data across tenants), sub-second navigation, resilient deploys, and operability by a small team.

This is a design. I describe the code that matters and the reasons; I do not present it as a runnable template. Everything uses SvelteKit 3 conventions: config in `vite.config.ts`, `#lib` imports, `$app/env/*`, `$app/state`. Remote functions are experimental, so the design isolates them behind a thin layer (decision record 1).

### Repository layout

```text
src/
  app.d.ts                 App.Locals, App.Error, App.PageState
  env.ts                   defineEnvVars: DATABASE_URL, SESSION_SECRET, PUBLIC_ORIGIN...
  params.ts                matchers: tenant slug, uuid
  hooks.server.ts          sequence(requestContext, security, session, tenant, guard)
  hooks.client.ts          client error reporting, init
  instrumentation.server.js
  lib/
    server/                server-only (any `server` dir is protected in 3.x)
      db/                  pool, tenant-scoped repositories
      auth/                session store, password hashing, requireUser/requireRole
      domain/              plain functions: the business logic
      logger.ts, metrics.ts
    ui/                    components (props in, events out)
    shared/                types, schemas (valibot), pure utilities
  routes/
    (public)/login, logout, healthz
    (app)/[tenant=slug]/
      +layout.server.ts    (does not guard; see ADR)
      dashboard/ , views/ , members/ , settings/
      *.remote.ts          thin wrappers over lib/server/domain
    api/webhooks/billing/+server.ts
  service-worker/          optional static-asset precache only
```

The `(app)` group and `[tenant=slug]` param make tenant a first-class part of the URL, so every route has `params.tenant`, the matcher validates its shape in one place (`src/params.ts`) and `resolve('/[tenant=slug]/dashboard', { tenant })` builds links type-safely.

### Request pipeline (hooks)

```ts
// src/hooks.server.ts
import type { Handle, HandleServerError } from '@sveltejs/kit/hooks';
import { sequence } from '@sveltejs/kit/hooks';
import { redirect, error } from '@sveltejs/kit';
import { logger } from '#lib/server/logger.js';
import { loadSession } from '#lib/server/auth/session.js';
import { resolveMembership } from '#lib/server/auth/membership.js';

const requestContext: Handle = async ({ event, resolve }) => {
    const requestId = crypto.randomUUID(); // never trust inbound IDs here: the LB sets none we rely on
    event.locals.requestId = requestId;
    event.tracing.root.setAttribute('app.request_id', requestId);

    const start = performance.now();
    const response = await resolve(event);
    response.headers.set('x-request-id', requestId);

    logger.info({
        requestId,
        route: event.route.id,
        status: response.status,
        ms: Math.round(performance.now() - start),
        tenant: event.locals.tenant?.id,
        user: event.locals.user?.id
    }, 'request');
    return response;
};

const security: Handle = async ({ event, resolve }) => {
    const response = await resolve(event);
    response.headers.set('x-content-type-options', 'nosniff');
    response.headers.set('referrer-policy', 'strict-origin-when-cross-origin');
    response.headers.set('permissions-policy', 'camera=(), microphone=(), geolocation=()');
    response.headers.set('strict-transport-security', 'max-age=31536000; includeSubDomains');
    response.headers.set('x-frame-options', 'DENY'); // CSP frame-ancestors is ignored on prerendered meta; keep the header
    return response;
};

const session: Handle = async ({ event, resolve }) => {
    if (event.url.pathname === '/healthz') return resolve(event);
    event.locals.user = await loadSession(event.cookies);
    event.tracing.root.setAttribute('app.user.id', event.locals.user?.id ?? 'anonymous');
    return resolve(event);
};

const tenant: Handle = async ({ event, resolve }) => {
    const slug = event.params.tenant;
    if (slug && event.locals.user) {
        const membership = await resolveMembership(event.locals.user.id, slug);
        if (!membership) error(404, 'Not found'); // 404, not 403: do not reveal that the tenant exists
        event.locals.tenant = membership.tenant;
        event.locals.role = membership.role;
        event.tracing.root.setAttribute('app.tenant.id', membership.tenant.id);
    }
    return resolve(event);
};

const guard: Handle = async ({ event, resolve }) => {
    const isPrivate = event.route.id?.startsWith('/(app)');
    if (isPrivate && !event.locals.user) {
        redirect(303, `/login?next=${encodeURIComponent(event.url.pathname)}`);
    }
    return resolve(event);
};

export const handle = sequence(requestContext, security, session, tenant, guard);

export const handleError: HandleServerError = ({ kind, error, event }) => {
    const requestId = event.locals?.requestId ?? 'unknown';
    if (kind === 'unknown') {
        logger.error({ requestId, route: event.route.id, err: error }, 'unhandled');
        return { message: 'Something went wrong', requestId };
    }
    if (kind === 'app' || kind === 'framework' || kind === 'validation') {
        return { ...error, requestId };
    }
};
```

Design points:

- **Named handles in a `sequence`** give readable span names (`sveltekit.handle.sequenced.session`) and an explicit order. Session before tenant before guard.
- **Guards live in `handle`, not only in layouts** (Chapter 14), because layout loads do not rerun on every navigation and run in parallel with page loads. The `tenant` handle is the authorization boundary for tenant membership: it runs on every request, including data requests and remote function calls, because those go through `handle`.
- **Remote function calls pass through `handle`** too, so session and tenant resolve for them. But inside a remote `form` or `command`, `event.params`/`event.url` describe the *calling page*; and in a `query`, accessing them throws. So the tenant for a remote call must be **an explicit argument that the server re-verifies**, never trusted from the URL (ADR 5).
- The security handle shows a conscious trade: headers set after `resolve` on every response. CSP is configured declaratively in `sveltekit({ csp })`, not here (Chapter 15).
- `handleError` triages by `kind` and never throws. (The final `return` for the other kinds is covered by the three explicit cases; for the type system’s benefit return the error object in all non-unknown cases.)

### Data layer: tenant isolation by construction

The riskiest bug class in a multi-tenant app is forgetting a tenant filter. The defence is structural (author practice):

```ts
// src/lib/server/db/scoped.ts
import { pool } from './pool.js';

export interface TenantScope { tenantId: string }

/** All data access goes through a repository bound to a tenant. There is no unscoped query API in app code. */
export function scoped(scope: TenantScope) {
    return {
        views: {
            list: () => pool.query('select * from views where tenant_id = $1 order by name', [scope.tenantId]),
            get: (id: string) =>
                pool.query('select * from views where tenant_id = $1 and id = $2', [scope.tenantId, id])
        }
        // ...
    };
}
```

Combine it with Postgres row-level security keyed on a per-transaction setting, so that even a repository bug cannot cross tenants. Application code obtains the scope only from `locals.tenant`, set by the `tenant` handle, or in remote functions from a helper that re-derives it (ADR 5).

### Auth helper

```ts
// src/lib/server/auth/guards.ts
import { getRequestEvent } from '$app/server';
import { error, redirect } from '@sveltejs/kit';

export function requireUser() {
    const { locals, url } = getRequestEvent();
    if (!locals.user) redirect(303, `/login?next=${encodeURIComponent(url.pathname)}`);
    return locals.user;
}

export function requireRole(min: 'viewer' | 'editor' | 'admin') {
    const { locals } = getRequestEvent();
    requireUser();
    const rank = { viewer: 0, editor: 1, admin: 2 } as const;
    if (!locals.tenant || rank[locals.role!] < rank[min]) error(403, 'Forbidden');
    return { user: locals.user!, tenant: locals.tenant, role: locals.role! };
}
```

`requireUser` uses `getRequestEvent()`, so it works in loads, actions and remote functions. It reads `url.pathname` only for the redirect target, which is safe, but see below for tenant trust inside remote functions.

### Remote functions with single-flight updates

Remote functions are experimental (Chapters 7 and 8): they need `experimental.remoteFunctions` and `compilerOptions.experimental.async` in `sveltekit({...})`. I use them for the interactive parts (saved views, member management) and keep classic `load` for page-level data.

```ts
// src/routes/(app)/[tenant=slug]/views/views.remote.ts
import * as v from 'valibot';
import { query, form, requested } from '$app/server';
import { requireRole } from '#lib/server/auth/guards.js';
import { scoped } from '#lib/server/db/scoped.js';
import { renameView, listViews } from '#lib/server/domain/views.js';

// The tenant comes from the verified membership resolved in `handle`; the client passes nothing for it.
export const getViews = query(async () => {
    const { tenant } = requireRole('viewer'); // reads locals, not url/params (those throw in queries)
    return listViews(scoped({ tenantId: tenant.id }));
});

export const rename = form(
    v.object({ id: v.pipe(v.string(), v.uuid()), name: v.pipe(v.string(), v.minLength(1), v.maxLength(80)) }),
    async ({ id, name }) => {
        const { tenant } = requireRole('editor');
        await renameView(scoped({ tenantId: tenant.id }), id, name);

        // Single-flight: refresh what the client asked for, bounded.
        for (const entry of requested(getViews, 5)) entry.refreshAll();
    }
);
```

Two cautions I apply in review. First, whether a no-argument `query` signature and the exact `requested` iteration API match your installed 3.x types must be checked against `$app/server`’s declarations (Chapter 8); I describe the pattern from the documented behaviour: a mutation can refresh specific queries in the same round trip, the server opts in by calling `requested(query, limit)`, and every requested update must be refreshed, set or ignored or that query errors on the client. Second, the tenant: because `event.locals` is populated by `handle` from the session and the tenant *slug of the page that initiated the call*, a remote call made from the wrong tenant’s page would resolve a different membership. That is correct behaviour only if the slug is the tenant the user intends. For anything destructive I pass the tenant ID as an explicit validated argument and assert it equals `locals.tenant.id`, so a stale tab on another tenant cannot write into the wrong one:

```ts
export const deleteView = command(
    v.object({ tenantId: v.pipe(v.string(), v.uuid()), id: v.pipe(v.string(), v.uuid()) }),
    async ({ tenantId, id }) => {
        const { tenant } = requireRole('admin');
        if (tenant.id !== tenantId) error(409, 'Tenant mismatch');
        // ...
    }
);
```

Live metrics use `query.live` (Chapter 7) for the dashboard tiles. This drives two operational decisions: adapter-node on a long-lived-connection-friendly platform with `proxy_buffering off` equivalents, and a short `SHUTDOWN_TIMEOUT` (below).

### Environment

```ts
// src/env.ts
import { defineEnvVars } from '@sveltejs/kit/env';
import * as v from 'valibot';

export const variables = defineEnvVars({
    DATABASE_URL: { schema: v.pipe(v.string(), v.url()), description: 'Postgres connection string' },
    SESSION_SECRET: { schema: v.pipe(v.string(), v.minLength(32)), description: 'HMAC key for session cookies' },
    OTEL_SERVICE_NAME: { schema: v.optional(v.string(), 'meridian-web'), description: 'Tracing service name' },
    PUBLIC_APP_NAME: { public: true, static: true, description: 'Product name' }
});
```

Invalid or missing values fail at start, so a bad rollout never reaches readiness. Per Chapter 17, nothing the instrumentation must wrap (the database driver) is imported by `src/env.ts`.

### Adapter and container

`adapter-node`, `paths.origin` left unset, and the proxy header variables set at runtime so one image promotes through environments:

```ts
// vite.config.ts
import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-node';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [
        sveltekit({
            adapter: adapter(),
            tracing: { server: true },
            version: { name: process.env.GIT_SHA },
            experimental: { remoteFunctions: true },
            compilerOptions: { experimental: { async: true } },
            csp: {
                mode: 'auto',
                directives: {
                    'default-src': ['self'],
                    'script-src': ['self'],
                    'style-src': ['self'],
                    'img-src': ['self', 'data:'],
                    'connect-src': ['self'],
                    'object-src': ['none'],
                    'base-uri': ['self'],
                    'frame-ancestors': ['none']
                }
            }
        })
    ],
    ssr: { external: ['pg'] }
});
```

(`version.name` from the build environment ties logs, traces and skew detection to one build. `ssr.external: ['pg']` with `pg` in `dependencies` keeps the driver instrumentable, Chapter 17. Check each CSP directive against what your components load; `style-src 'self'` may require nonces or hashes for Svelte’s inlined styles depending on `inlineStyleThreshold`, which I leave at its default.)

Runtime environment on Cloud Run: `PROTOCOL_HEADER=x-forwarded-proto`, `HOST_HEADER=x-forwarded-host`, `ADDRESS_HEADER=x-forwarded-for`, `XFF_DEPTH=1`, `SHUTDOWN_TIMEOUT=8` (below Cloud Run’s grace period, which you should confirm for your configuration), `BODY_SIZE_LIMIT=1M`. Health: liveness `/healthz`, readiness `/healthz?deep=1` (Chapter 18). A `sveltekit:shutdown` listener stops the metrics reader, ends the pool and flushes the tracing SDK.

### Observability

`instrumentation.server.js` as in Chapter 17: OTLP to a collector, sampling through `OTEL_TRACES_SAMPLER=parentbased_traceidratio`, `OTEL_TRACES_SAMPLER_ARG=0.1`, auto-instrumentations for `pg` and `fetch`, resource attribute `service.version` from `GIT_SHA`. Logs are one structured line per request with `requestId`, `traceId`, route ID, status. Metrics come from the `requestContext` handle (duration histogram and 5xx counter by route and status), not from sampled traces.

### Decision records

**ADR 1: Where logic lives, and how we contain experimental remote functions.** *Context:* remote functions are experimental and their API has changed across minors. *Decision:* all business logic lives in plain functions in `lib/server/domain`; `*.remote.ts` files contain only schema, authorization call and a delegation. *Consequences:* unit tests target the domain; if remote functions change or we abandon them, only wrappers change; actions and `+server` handlers can reuse the same domain functions.

**ADR 2: State.** *Context:* server state hazards (module singletons leaking across requests), client state, URL state. *Decision:* server request state only in `event.locals`; no module-level mutable per-request data; pools and caches keyed by tenant ID where shared. Filters, sort order and selected time range live in the URL search parameters (shareable, back-button friendly, tracked per key by `load`). Remote `query` caches serve as the client data cache for interactive widgets; shallow routing (`goto(..., { shallow: true, state })`) for dialogs with `page.state`. Component-local UI state uses runes. Form drafts use `snapshot()`. *Consequences:* no global stores for server data; deep links reproduce views.

**ADR 3: Caching.** *Context:* the HTML is personalised and tenant-specific. *Decision:* pages and data requests `private, no-store` (data requests already are); static assets immutable and long-cached (default); the marketing and login pages are prerendered and cached at the CDN; expensive aggregates are cached in Postgres materialised views or Redis keyed by tenant, never in module memory; no public `s-maxage` on any `(app)` route; no service worker caching of HTML or data, only static asset precache. *Consequences:* correctness over edge cache hit rate; perceived speed comes from preloading (`data-sveltekit-preload-data="hover"` on app navigation links), streaming slow tiles after the shell, and parallel loads that avoid `parent()` by reading `locals`.

**ADR 4: Error taxonomy.** *Decision:* four user-facing classes: *not found* (404, also used for unauthorised tenant access), *forbidden* (403, role too low), *invalid input* (400 or form issues, never logged above info), *unexpected* (500 with request ID shown). `handleError` triages by `kind`; only `unknown` and 5xx `app` errors alert. `+error.svelte` at the `(app)` level shows the request ID and a retry link; `error.html` is the static fallback. Webhook endpoints return plain status codes and never HTML. *Consequences:* alert noise stays low; support can find any failure from the ID.

**ADR 5: Authorization in remote functions.** *Decision:* every remote function begins with `requireRole(...)`, which reads `locals` set by `handle`. For destructive commands the tenant ID is an explicit argument verified against `locals.tenant.id`. Never use `event.url`, `params` or `route` for authorization in forms/commands (they describe the calling page), and they throw in queries. *Consequences:* a stale or manipulated page cannot target another tenant; reviewers grep for functions lacking a guard.

**ADR 6: Security headers and CSRF.** *Decision:* CSP configured in `sveltekit({ csp })` with `mode: 'auto'` (nonces on dynamic pages) and reporting enabled; HSTS, `nosniff`, referrer and permissions policies, `X-Frame-Options` set in `handle`; CSRF left at its always-on default; `csrf.trustedOrigins` includes only the billing provider’s origin if it posts forms (it uses a JSON webhook with a signature, so empty); webhook verification by HMAC signature on the raw body and a `Content-Type` check; session cookie `httpOnly`, `secure`, `sameSite: 'lax'`, explicit `path: '/'`; `redirect` to external URLs forbidden except an allow-list for the identity provider. *Consequences:* defence in depth; the login redirect uses a validated same-origin `next` path.

**ADR 7: Deployment and skew.** *Decision:* adapter-node containers, rolling deploys, `version.name` = Git SHA, old hashed assets served from a CDN bucket that retains the previous two releases, backward-compatible remote function and endpoint shapes across one deploy, `updated.current` banner. *Consequences:* users on a stale tab keep working through a rollout; incompatible changes need a two-step deploy.

### Rollout, observability and test plan

**Test plan** (Chapter 19):

| Level | Scope |
|------------------------------------|------------------------------------|
| Unit (Vitest, Node) | domain functions; `requireRole` with mocked `$app/server`; matchers in `params.ts`; valibot schemas; `handleError` by kind |
| Integration (Vitest, `Request`) | each `handle` in the sequence and the composed `handle`; webhook handler (valid and invalid signatures, replay); actions that remain |
| Component (Vitest browser) | `ui` components with props; no `$app/state` dependencies inside shared components |
| Tenant isolation | a dedicated suite that, for every repository method, runs as tenant A against tenant B’s rows and expects nothing; plus RLS tests against a real Postgres |
| E2E (Playwright, preview build) | login (storage state), dashboard render, saved-view rename through the remote form with single-flight update, member invite as admin, 403 as viewer, 404 for foreign tenant, no-JS login, console-error fixture |
| Non-functional | k6 or similar against staging for a baseline; deploy-skew drill (open tab, deploy, navigate) |

**Rollout:**

1.  Feature flags for new tenants and for `query.live` tiles (ship the shell first).
2.  Staging deployment with production-like proxy headers; run E2E there.
3.  Canary: 5% of traffic by revision on Cloud Run for an hour; watch the 5xx counter, p95 latency by route, `handleError` unknown-kind rate, and trace sampling.
4.  Promote progressively; keep the previous revision for fast rollback.
5.  Post-deploy: skew drill and a check that the retained assets bucket contains both versions.

**Alerts** (from the signals above): 5xx ratio per route, readiness failures, `unknown` error rate, p95 latency regressions, database pool saturation, shutdown timeouts (forced closes in logs), and a tenant-mismatch (409) rate that should be near zero.

## Recap: the mental model of SvelteKit 3

If you keep only a page of this book, keep this:

1.  **A request is a web `Request` entering `handle`, and a `Response` leaving it.** Static assets and prerendered pages bypass it; page documents, `__data.json`, actions, `+server` handlers and remote calls all go through it. Cross-cutting concerns belong there (Chapters 2 and 9).
2.  **Routes are files; data is functions.** `load` (universal or server) produces serialisable data; invalidation is dependency-tracked and conservative; server loads run in parallel unless you create a `parent()` waterfall (Chapters 3 to 5).
3.  **Mutations have three idioms.** Form actions for progressive enhancement, remote `form` and `command` for typed RPC with single-flight refresh (experimental), and `+server` endpoints for non-browser clients (Chapters 6 to 8).
4.  **Errors converge on `handleError`**, with a `kind`; users see a safe `App.Error`; logs carry request and trace IDs (Chapters 10 and 17).
5.  **Rendering is a per-route policy**: SSR, prerender, SPA, or CSR-off, decided with page options and enforced by the adapter (Chapter 11).
6.  **State has a home**: server request state in `locals`, URL for shareable state, runes for UI state, remote caches for server data on the client (Chapter 12).
7.  **Configuration is explicit and validated**: `sveltekit({...})` in Vite for build, `src/env.ts` for runtime variables, server-only modules enforced by name and directory (Chapters 1 and 13).
8.  **Trust boundaries are explicit**: sessions in `handle`, guards in hooks or per-route, CSRF always on, CSP declared, origins pinned (Chapters 14 and 15).
9.  **Performance is design**: parallel data, cacheable pages where safe, preload on intent, correct cache headers (Chapter 16).
10. **Adapters are the last mile**, and each has its own contract for origin, shutdown, files and runtime limits (Chapter 18). Test the build you ship (Chapter 19), and migrate by upgrading the toolchain first, then running the codemod, then fixing the semantic changes by hand (this chapter).

## Key takeaways

- Upgrade to the latest 2.x first, fix deprecation warnings, raise Node (22.17+), TypeScript 6, Svelte 5.57.1, Vite 8.0.12+ and plugin-svelte 7, then run `npx sv migrate sveltekit-3`.
- The codemod has tasks for `package-json`, `tsconfig`, `svelte-config`, `environment`, `paths`, `external-redirects`, `shallow-routing`, `params`, `imports`, `lib-alias`, `app-state`, and `collect-migration-instructions` (which writes `MIGRATION_TASKS.md`). Run them in small, reviewable commits.
- Config moves to `sveltekit({...})`; `$lib` becomes `#lib` with extensions; `$app/stores`, `$service-worker`, `base`/`assets`/`resolveRoute` are removed; `$app/environment` and `$env/*` are deprecated.
- Behavioural changes need human review: `handleError` sees all errors, enhanced forms use `fail` status codes and navigate cross-page, `ORIGIN` is gone, CSRF always on with `trustedOrigins`, cookie path defaults and ASCII names, external redirects need opting in, server-only rules apply to any `server` directory, 204 has no body, universal `config` wins.
- Test the migration against a production build and staging behind the real proxy; keep the 2.x deployment for rollback.
- Schedule v4 removals: `$env/*`, `$app/environment`, `invalidateAll`, `pushState`/`replaceState`, `json`/`text`, `files.*`, `alias`, `typescript.config`, `snapshot` export, deprecated builder methods.
- The capstone applies the book: guards in `handle`, tenant resolution as an authorization boundary, tenant-scoped repositories plus RLS, thin remote function wrappers over plain domain functions, explicit tenant arguments for destructive commands, validated env, adapter-node with proxy headers and short shutdown, tracing with request IDs, and explicit decision records.

## Review Questions

1.  List the minimum versions SvelteKit 3 requires for Node, TypeScript, Svelte, Vite and `@sveltejs/vite-plugin-svelte`.
2.  Which codemod tasks are prerequisites, and what does `collect-migration-instructions` produce?
3.  Why can the codemod not complete the migration on its own? Give three changes that need human judgement.
4.  Convert this config to SvelteKit 3: `kit: { adapter, prerender: { origin: 'https://x.dev' }, csrf: { checkOrigin: false } }`.
5.  Rewrite `import { foo } from '$lib/util/foo'` for SvelteKit 3 and give the `package.json` entries required.
6.  **What does this print / error?** `import { page } from '$app/stores'; ... {$page.url.pathname}` in SvelteKit 3. What is the replacement, and what type change might break `page.url.searchParams.set('q', 'x')`?
7.  Rewrite `base + resolveRoute('/blog/[slug]', { slug })` and `assets + '/img/a.png'` for 3.x. What changed about leading slashes?
8.  A service worker imports `build`, `files` and `version` from `$service-worker`. Map each to its 3.x source.
9.  Convert `pushState('/foo', { open: true })` and `replaceState('', { open: false })` to the 3.x API. What new option restores `page.state` after reload, and what do shallow navigations now trigger?
10. What are the differences between `invalidateAll` and `refreshAll`?
11. What new branch must code consuming `preloadData` add?
12. An enhanced form posts to an `action` on another page. How does 3.x behave differently from 2.x? Which option opts out (see Chapter 6)?
13. A test asserts that a failed enhanced form returns status 200. What changed and how do you update it?
14. Which changes to `handleError` in 3.x require rethinking logging and alerting? Explain how to adapt.
15. `error(404, { message: 'x', code: 'E1' })` is used throughout the code. What is the 3.x form?
16. What replaced `handleValidationError`?
17. What changed about `redirect()` to external URLs, and how does `javascript:` fit in?
18. Describe two changes to cookie handling in 3.x.
19. Why might a webhook sender that worked in 2.x start failing with CSRF errors in 3.x, and what are two fixes?
20. What do `csrf.trustedOrigins` and `paths.origin` each do, and which replaces what?
21. Where do hook types such as `Handle` come from now, and where do `defineParams` and `defineEnvVars` live?
22. Describe how `src/params.ts` replaces `src/params/*.js`, and why transforms should be symmetric.
23. A module `src/lib/helpers/server/format.ts` is imported in a component. What changed in 3.x about server-only directories, and what happens?
24. Name four adapter-node changes in 3.x that affect deployment.
25. For Cloudflare, where do you now get `env`, `waitUntil`, `cf` and `caches`?
26. List five APIs deprecated in 3.x that you should schedule for removal before v4.
27. In the capstone, why is the `tenant` handle placed after `session` and before `guard`, and why return 404 rather than 403 for a foreign tenant?
28. In the capstone, why must destructive remote commands take an explicit tenant ID, and why is `event.params` not used for authorization?
29. **Design:** In the capstone, list three layers that jointly prevent cross-tenant data access, and give one test for each.
30. **Design:** Choose caching policies for: the login page, a tenant dashboard page, `/_app/immutable/*`, a `query.live` stream, and the billing webhook. Justify each.
