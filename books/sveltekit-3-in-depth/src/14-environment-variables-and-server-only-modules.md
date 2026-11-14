# Chapter 13: Environment Variables and Server-Only Modules

Configuration and secrets are where full-stack frameworks most often leak. A bundler that happily follows an import from a component to a database module will bundle the database credentials into a JavaScript file that every visitor downloads. SvelteKit attacks this problem from two directions. First, an *explicit environment variable system* (stable in 3.x): you declare every variable in one file, say whether it is public or private, static or dynamic, and attach a validator, and the framework generates typed modules from the declaration. Second, *server-only modules*: files and directories whose import into browser-reachable code is a build error, checked across the whole import chain.

This chapter covers the `src/env.ts` file and `defineEnvVars`, the generated `$app/env/private` and `$app/env/public` modules, the build-time versus runtime distinction and when validation runs, `.env` loading, the legacy `$env/*` and `$app/environment` modules and how to migrate off them, the server-only rules (filename, directory, import-chain analysis, the Vitest exemption, and packages), and practical secret hygiene including platform environment quirks. As everywhere in this book, configuration goes in `sveltekit({...})` inside `vite.config.ts`, and project-local imports use `#lib/...`.

## Declaring variables: `src/env.ts`

Create `src/env.ts` (or `src/env.js`) and export a `variables` object built with `defineEnvVars` from `@sveltejs/kit/env`:

```ts
// src/env.ts
import { defineEnvVars } from '@sveltejs/kit/env';
import * as v from 'valibot';

export const variables = defineEnvVars({
    DATABASE_URL: {
        description: 'Postgres connection string',
        schema: v.pipe(v.string(), v.url())
    },
    SESSION_SECRET: {
        description: 'HMAC key for session cookies (>= 32 chars)',
        schema: v.pipe(v.string(), v.minLength(32))
    },
    STRIPE_SECRET_KEY: {},
    PUBLIC_API_BASE: {
        public: true,
        static: true,
        schema: v.pipe(v.string(), v.url())
    },
    FEATURE_BETA: {
        public: true,
        static: true,
        schema: v.pipe(
            v.optional(v.string(), ''),
            v.transform((s) => s !== '')
        )
    }
});
```

`defineEnvVars` returns its argument unaltered. It exists only so that TypeScript can infer the output type of each schema. Each entry is an `EnvVarConfig`:

| Option | Meaning | Default |
|------------------------|------------------------|------------------------|
| `public` | Accessible to client code via `$app/env/public` (and `%sveltekit.env.NAME%` in `app.html`) | `false` (private) |
| `static` | Value is determined at build time and inlined into the bundle | `false` (dynamic: read when the app starts) |
| `schema` | A [Standard Schema](https://standardschema.dev) validator, or a plain function returning the (transformed) value or throwing | none |
| `description` | Shown on hover in your editor (generated into the type declarations) | none |

Everything is private and dynamic unless you say otherwise. Three observations follow from the implementation:

1.  **No naming convention is required.** The old `PUBLIC_` prefix rule is gone from the explicit system: exposure is decided by `public: true`, not by a prefix. Keeping a `PUBLIC_` prefix by convention remains a useful human signal (and eases migration), but the framework does not enforce it. The names must be valid JavaScript identifiers and not reserved words (`delete`, `class`, `default`, …); `API-KEY` is rejected at config time.
2.  **An empty object is valid.** `STRIPE_SECRET_KEY: {}` declares a required private dynamic variable with no validator. Without a `schema`, the variable must be *set*, but may be an empty string. A missing value is an error.
3.  **Validators must be synchronous.** An async validator is reported as an error. Plain functions are normalised to Standard Schema internally, and a function may return `undefined`, which is how you declare an optional variable.

### Plain-function validators

If you do not want a schema library:

```ts
// src/env.ts
import { defineEnvVars } from '@sveltejs/kit/env';

export const variables = defineEnvVars({
    PORT_OVERRIDE: {
        schema: (value) => {
            if (value === undefined) return 3000;          // optional with default
            const n = Number(value);
            if (!Number.isInteger(n) || n < 1 || n > 65535) throw new Error('must be a valid port');
            return n;                                       // output type: number
        }
    },
    LOG_LEVEL: {
        schema: (value) => {
            const allowed = ['debug', 'info', 'warn', 'error'] as const;
            const v = value ?? 'info';
            if (!(allowed as readonly string[]).includes(v)) throw new Error(`expected one of ${allowed.join(', ')}`);
            return v as (typeof allowed)[number];
        }
    }
});
```

The type of `import { PORT_OVERRIDE } from '$app/env/private'` is inferred from the return type (`number`), not `string`. The generated declaration lives at `node_modules/$app/types/env.d.ts` and is regenerated by `svelte-kit sync` (which `vite dev` and `vite build` run for you).

> **Note:** A public, *dynamic* variable has to travel to the browser, so its validated output must be serialisable with devalue. A schema may output a `Date` or a `Map`, but not a function or a class instance. Static values are inlined as source code (via `devalue.uneval`) and have the same restriction.

## Consuming variables

```ts
// src/lib/server/db.ts
import { DATABASE_URL } from '$app/env/private';
import { createPool } from './pool.js';

export const pool = createPool(DATABASE_URL);
```

```html
<!-- src/routes/+layout.svelte -->
<script lang="ts">
    import { PUBLIC_API_BASE, FEATURE_BETA } from '$app/env/public';
    import BetaBanner from '#lib/BetaBanner.svelte';
    let { children } = $props();
</script>

{#if FEATURE_BETA}
    <BetaBanner />
{/if}
{@render children()}
```

The two modules differ in who may import them:

- `$app/env/private` is a **server-only module** (see below). Importing it into any code reachable from the browser is a build error.
- `$app/env/public` can be imported anywhere: server code, components, universal `load`, the service worker.

In `app.html`, public variables are available as `%sveltekit.env.NAME%`:

```html
<!-- src/app.html -->
<!doctype html>
<html lang="en">
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        %sveltekit.head%
        <script async src="https://www.googletagmanager.com/gtag/js?id=%sveltekit.env.GA_ID%"></script>
    </head>
    <body data-sveltekit-preload-data="hover">
        <div style="display: contents">%sveltekit.body%</div>
    </body>
</html>
```

(This assumes `GA_ID` is declared with `public: true`.) The template is filled from the public variables only. A placeholder naming an undeclared or private variable does not fail: it renders as an **empty string** (the generated template code is `env[NAME] ?? ""`), which makes typos easy to miss, so check the rendered HTML. The values are also substituted *verbatim*, without HTML escaping, so never put a value containing quotes or angle brackets into an attribute this way; validate such variables with a strict schema.

## Static versus dynamic

This is the distinction that most often confuses people, because it spans three dimensions: *when the value is read*, *where the value ends up*, and *when it is validated*.

|  | `static: false` (default) | `static: true` |
|------------------------|------------------------|------------------------|
| When read | Process start (from the environment the adapter hands to the server, e.g. `process.env`) | `vite build` (from `.env*` files and the build process’s environment) |
| In the bundle | Not present; read at runtime | Inlined as a literal |
| Dead-code elimination | No | Yes: `{#if FEATURE_BETA}` can drop the branch and its imports |
| Changing it requires | Restart | Rebuild |
| Validated | At startup (and during build analysis, see below) | At build time, once |
| Fit | Secrets, per-environment URLs, anything that differs between deployments of the *same build* | Feature flags, build metadata, values that never change between environments |

Dynamic public variables deserve a note, because the browser cannot read your server’s environment. SvelteKit delivers them in two ways: for server-rendered pages the values are embedded in the page’s hydration payload; for **prerendered** pages (which are static files with no per-request step) the client loads a prerendered `_app/env.js` module before any application code runs. The same applies to the service worker, which imports `env.js` in production. The consequence is subtle: a prerendered page with dynamic public variables carries a tiny extra module request, and the value it sees is the one the server had *at runtime*, not at build. If you do not need that, prefer `static: true` for public variables on prerendered sites.

> **Senior tip:** The “build once, deploy many” promotion model (build a container image once, run it in staging and production with different env) requires that *everything that differs between environments is dynamic*. Any `static: true` variable bakes its value into the image. Mark only genuinely environment-independent values static, and keep the production-affecting ones dynamic.

### Validation timing and `building`

An invalid value makes the app fail to start, or the build fail; the failure message lists each offending variable with its validator issues. Concretely:

- **Static** variables are validated while the build generates its modules.
- **Dynamic** variables are validated when the server initialises (the adapter calls `server.init({ env })`, which sets the dynamic environment). During `vite build`, SvelteKit loads your server modules for analysis and prerendering, and the same module evaluation happens with `building === true`.

That creates a classic problem: a CI build job does not have production secrets, so a required `DATABASE_URL` fails the build even though the build never connects to anything. The supported solution is to make the validator lenient during the build only, using `building` from `$app/env`:

```ts
// src/env.ts
import { defineEnvVars } from '@sveltejs/kit/env';
import { building } from '$app/env';
import * as v from 'valibot';

export const variables = defineEnvVars({
    DATABASE_URL: {
        // optional while building, required when the server starts
        schema: building ? v.optional(v.pipe(v.string(), v.url())) : v.pipe(v.string(), v.url())
    },
    SESSION_SECRET: {
        schema: building
            ? v.optional(v.string())
            : v.pipe(v.string(), v.minLength(32))
    }
});
```

You can invert the relationship to opt out of start-time failure in tools that evaluate your config without running the server. Whichever you pick, `building` is the switch. Note that `$app/env` is the *only* `$app` module `src/env.ts` may import; importing `$app/env/private` or `$app/env/public` from `src/env.ts` is a circular import and fails with a dedicated error, and so does importing other `$app/*` modules. Instrumentation cannot intercept modules imported by `src/env` either, because the file is loaded in a separate pass (Chapter 17).

### Where the values come from

During `vite dev` and `vite build`, SvelteKit loads values using Vite’s `loadEnv` with an **empty prefix**: every variable in `.env`, `.env.local`, `.env.[mode]` and `.env.[mode].local`, *plus* the build process’s `process.env`, is a candidate. Only variables *declared in `src/env.ts`* are exposed to your code. In dev, the dynamic variables are read from this same set (so `.env.local` works for dynamic variables in development).

In production, **no `.env` file is loaded for dynamic variables by default**. The runtime environment is whatever the adapter provides:

- `adapter-node`: `process.env`. To load a file, use Node’s built-in flag: `node --env-file=.env build`, or have your orchestrator inject real environment variables (recommended).
- `adapter-bun`: Bun’s environment (Bun loads `.env` files itself).
- Cloudflare, Netlify, Vercel: the platform’s environment mechanism, which the adapter maps into the `env` it passes to `server.init`. For runtimes without `process.env`, the adapter supplies the object.

`sveltekit({ env: { dir } })` changes the directory searched for `.env` files (default: the project root). Use it in monorepos where the env files live above the app.

```ts
// vite.config.ts
import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-node';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [
        sveltekit({
            adapter: adapter(),
            env: { dir: '../..' } // monorepo root
        })
    ]
});
```

`.env.local` is conventionally git-ignored; commit an `.env.example` listing the names (your `description` fields make a good source for it). A neat practice is a tiny script that reads `src/env.ts` and generates `.env.example`, so documentation cannot drift from the declaration.

### Missing declarations are your most common bug

Because only declared variables are exposed, forgetting to declare is the typical failure:

```ts
import { SMTP_HOST } from '$app/env/private'; // TypeScript error: not exported, until declared in src/env.ts
```

That is a feature: the set of environment inputs to your application is now a reviewable list in one file, typed and validated. The flip side is that libraries which read `process.env.X` directly (a database driver reading `PGHOST`) bypass the system entirely; they keep working on Node, but their configuration is not validated by you. Declare such variables anyway for validation if you want a fast failure, even if you never import them.

## Server-only modules

The environment system relies on the other half: guaranteeing that private values cannot reach the browser. The mechanism is general and you can apply it to your own modules.

### What is server-only

A module is server-only if any of these hold:

1.  It is `$app/env/private` or `$app/server` (which contains `read`, `getRequestEvent`, and the remote function builders).
2.  Its filename contains a `server` segment: `server.ts`, `db.server.ts`, `secrets.server.js`. This works for any file in the project.
3.  It lives in a directory named `server` **anywhere** in the project: `src/lib/server/db.ts`, `src/lib/data/server/users.ts`. The directories `src/routes` and `static` are excluded from this rule. (In SvelteKit 2 only `src/lib/server` counted. A 3.1 fix stopped treating *every* module as server-only when the whole project itself lives under a directory named `server`.)

```text
src/
  env.ts
  hooks.server.ts            # server-only: by the .server segment
  lib/
    server/
      db.ts                  # server-only: in a server directory
      auth/
        sessions.ts          # server-only (nested inside server/)
    mailer.server.ts         # server-only: .server filename
    format.ts                # universal
  routes/
    +page.server.ts          # server-only by the filename rule
    +page.svelte
```

Route files named `+page.server.ts`, `+layout.server.ts`, `+server.ts` and `hooks.server.ts` are server-only by their nature. They are the *entry points*; what the rule protects is your *other* modules.

### How the check works: import chains

The check is not “does this file import a server-only file”, but “can a browser-reachable entry point reach a server-only file *transitively*”. SvelteKit builds the import graph for the client environment and starts from the browser entry points: every `+page.svelte` and `+layout.svelte` component, universal `+page.ts`/`+layout.ts`, client and universal hooks, and the service worker. If a server-only module is reachable from any of them, the build fails with the chain:

```text
Cannot import #lib/server/secrets.ts into code that runs in the browser, as this
could leak sensitive information.

 src/routes/+page.svelte imports
  src/routes/utils.js imports
   #lib/server/secrets.ts

If you're only using the import as a type, change it to `import type`.
```

Notice that the *use* does not matter. If `utils.js` has `export { atlantisCoordinates } from '#lib/server/secrets.js'` and the page imports only `add` from `utils.js`, the chain is still rejected, because the secret module *could* end up in the shipped JavaScript (bundlers cannot always tree-shake side effects). The check also covers dynamic imports, including interpolated ones like `` await import(`./${name}.js`) ``.

The practical repair patterns:

- **Split by environment.** Put server logic in `*.server.ts` and shared pure logic in plain modules. A `format.ts` imported by components must not import `db.server.ts`.
- **Use `import type`.** Type-only imports are erased and do not count.
- **Return data from server `load`** instead of importing server code into the component.

```ts
// src/lib/server/users.ts   (server-only)
import { pool } from './db.js';
export async function getUser(id: string) { /* ... */ }
```

```ts
// src/routes/users/[id]/+page.server.ts   (allowed: server-only file imports server-only module)
import { getUser } from '#lib/server/users.js';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => ({ user: await getUser(params.id) });
```

```ts
// src/routes/users/[id]/+page.ts   (universal: would FAIL if it imported #lib/server/users.js)
```

### Exemptions and limits

- **Tests.** Vitest and other test runners do not separate server-only from browser code, so the check is disabled when `process.env.TEST === 'true'`, which Vitest sets. In unit tests you can import `#lib/server/users.js` freely. The cost: your tests will not catch a leak; the build is the enforcement point. Run `vite build` in CI.
- **`node_modules` and files outside the project root** are not subject to the rules. A published library that wants server-only enforcement for its own files must add `import '$app/server'` at the top of such a file: importing `$app/server` taints that module.
- **The check is import-based.** It cannot see data you *return* from a server `load`. If `load` returns `{ user }` and `user` includes `passwordHash`, the browser gets it. Server-only modules protect code and constants, not data flow. Chapter 15 covers data exposure in serialised `load` output.

## Legacy modules and migration

SvelteKit 2 had `$env/static/private`, `$env/static/public`, `$env/dynamic/private`, `$env/dynamic/public` and `$app/environment`. In SvelteKit 3 they are **deprecated** (they warn in development) and **removed in SvelteKit 4**. They remain as *aliases onto the explicit modules*, and this has an important consequence:

| Deprecated | Replacement | Notes |
|------------------------|------------------------|------------------------|
| `$env/static/private` | `$app/env/private` with `static: true` | Named imports |
| `$env/dynamic/private` | `$app/env/private` | `env.FOO` becomes `import { FOO }` |
| `$env/static/public` | `$app/env/public` with `static: true` |  |
| `$env/dynamic/public` | `$app/env/public` |  |
| `$app/environment` | `$app/env` | `browser`, `dev`, `building`, `version` |

Because the legacy modules re-export the explicit ones, **they only expose variables you declare in `src/env.ts`**. The old behaviour, where *every* variable in `process.env` was reachable through `$env/dynamic/private`’s `env` object and every `PUBLIC_*` variable through the public ones, is gone. A mechanical migration therefore has two steps: (1) create `src/env.ts` declaring every variable your app reads, choosing `public` and `static` to match the module you were using, and (2) rewrite imports.

```ts
// before
import { env } from '$env/dynamic/private';
import { PUBLIC_API_BASE } from '$env/static/public';
const url = env.DATABASE_URL;

// after
import { DATABASE_URL } from '$app/env/private';
import { PUBLIC_API_BASE } from '$app/env/public';
const url = DATABASE_URL;
```

`$app/env` exports `browser`, `dev`, `building` and `version` (a `prerendering` flag exists internally on the server, but it is not part of the public module; use `building`). It can be imported in the service worker, which replaces the removed `$service-worker` module’s `version`.

One difference from `$env/dynamic/private` that matters for code organisation: with dynamic access you could look up names at runtime (`env[name]`). The explicit modules are static named exports. If you need a map, build it explicitly:

```ts
// src/lib/server/flags.ts
import * as priv from '$app/env/private';

export function getPrivate(name: keyof typeof priv) {
    return priv[name];
}
```

This keeps type safety but note that namespace imports of `$app/env/private` retain *all* variables in scope, which is acceptable only in server-only modules (as here, under `server/`).

The `sv migrate` tool does not generate your `src/env.ts` declaration list for you; treat the migration of env as a manual, reviewed step during the 2→3 upgrade (Chapter 20).

## Secrets hygiene

The type system and the build checks protect against accidents. A senior review of secret handling adds the following practices (these are author recommendations; the framework does not enforce them).

**Principle of least exposure.** Every `public: true` variable is a statement that the value is safe to print on a billboard. Review the public set in code review as you would an API surface. Typical legitimate public values: analytics ids, public API base URLs, feature flags, publishable keys (a Stripe *publishable* key; never the secret key).

**Never interpolate private values into universal code paths.** A common leak is passing a secret through `load` data (`return { apiKey: API_KEY }` “just to use it in the component”). Use the secret on the server (in `load`, an action, or a remote function), and return only the *result*.

**Don’t log values.** Validation errors list variable *names* and validator messages, not the values; keep it that way in your custom validators. A validator that throws ``new Error(`bad value ${value}`)`` prints a secret into your build log.

```ts
// bad
schema: (value) => { if (!value?.startsWith('sk_')) throw new Error(`bad key: ${value}`); return value; }
// good
schema: (value) => { if (!value?.startsWith('sk_')) throw new Error('expected a key starting with sk_'); return value; }
```

**Prefer injected environment to committed files.** Secrets belong in your platform’s secret store (Kubernetes Secrets, Cloud Run secret references, Vercel/Netlify/Cloudflare environment settings), injected as real environment variables. If you use `--env-file`, keep the file out of the image and out of version control.

**Rotate by restart, not by rebuild.** With dynamic private variables, rotating a database password means restarting the processes with the new value. With a static one, it means rebuilding and redeploying. This is a strong argument for keeping secrets dynamic.

**Separate build-time and run-time secrets.** The build seldom needs secrets (a CMS read token for prerendering is the usual exception). Give the build job the minimum, and use the `building` pattern above so that the build can run without runtime-only secrets.

**Be careful with the `server` directory convention.** `src/lib/server/` is only *enforcement*; it is not encryption. Anything under it that you export from a `+server.ts` response or return from server `load` is public. Treat `server/` as “never bundled to the browser”, not “private”.

### Platform notes

- **Vercel**: Vercel injects system environment variables (such as `VERCEL_GIT_COMMIT_SHA`, `VERCEL_URL`). To use them, declare them in `src/env.ts`; for build-time ones that are not available at runtime, declare them `static: true`. The adapter documentation states that Vercel system environment variables used this way need `static: true`.
- **Cloudflare**: in SvelteKit 3 the Workers `env` bindings (KV, D1, R2) are no longer on `platform.env`; import `env` and `waitUntil` from `cloudflare:workers` (Chapter 18). Bindings are objects, not strings, so they are not environment variables in the `src/env.ts` sense; consult the adapter documentation for how string variables from your wrangler configuration reach the explicit system.
- **Containers**: pass variables with `docker run -e` or your orchestrator; Node’s `--env-file` flag (available since Node 20.6) also works inside the container command (`node --env-file=/run/secrets/app.env build`).

### A complete example

```ts
// src/env.ts
import { defineEnvVars } from '@sveltejs/kit/env';
import { building } from '$app/env';
import * as v from 'valibot';

const url = v.pipe(v.string(), v.url());

export const variables = defineEnvVars({
    // runtime secrets: required at start, optional while building
    DATABASE_URL: { description: 'Postgres URL', schema: building ? v.optional(url) : url },
    SESSION_SECRET: {
        description: 'Cookie signing key',
        schema: building ? v.optional(v.string()) : v.pipe(v.string(), v.minLength(32))
    },

    // runtime public (dynamic): same image, different API host per environment
    PUBLIC_API_BASE: { public: true, description: 'Base URL for the public API', schema: url },

    // build-time public (static): inlined, enables dead-code elimination
    PUBLIC_RELEASE: { public: true, static: true, schema: v.optional(v.string(), 'dev') },
    PUBLIC_ENABLE_DEBUG: {
        public: true,
        static: true,
        schema: v.pipe(v.optional(v.string(), ''), v.transform((s) => s === '1'))
    }
});
```

```ts
// src/lib/server/db.ts
import { DATABASE_URL } from '$app/env/private';
import { building } from '$app/env';
import { Pool } from 'pg';

export const pool = building ? (undefined as unknown as Pool) : new Pool({ connectionString: DATABASE_URL });
```

```html
<!-- src/routes/+layout.svelte -->
<script lang="ts">
    import { PUBLIC_ENABLE_DEBUG, PUBLIC_RELEASE } from '$app/env/public';
    import DebugOverlay from '#lib/DebugOverlay.svelte';
    let { children } = $props();
</script>

{#if PUBLIC_ENABLE_DEBUG}<DebugOverlay release={PUBLIC_RELEASE} />{/if}
{@render children()}
```

Build with `PUBLIC_ENABLE_DEBUG=1 vite build` and the `DebugOverlay` is included; without it, the component and its dependencies are removed from the bundle.

## Working with the env system in practice

### Testing code that imports env modules

`$app/env/private` is generated by the Vite plugin, so a unit test that imports a module which imports it needs either the SvelteKit plugin in the Vitest config (the `sv add vitest` templates include it through your `vite.config.ts`) or a mock. The mock route is the most predictable, and it also lets you vary the values per test. This is the author’s practice; the official docs have no testing page (Chapter 19). In this first version, `mailer.ts` reads `SMTP_HOST` and `SMTP_PORT` from `$app/env/private` itself:

```ts
// src/lib/server/mailer.spec.ts
import { describe, expect, it, vi } from 'vitest';

vi.mock('$app/env/private', () => ({
    SMTP_HOST: 'smtp.test',
    SMTP_PORT: 2525
}));

import { buildTransportOptions } from './mailer.js';

describe('buildTransportOptions', () => {
    it('uses the validated env values', () => {
        expect(buildTransportOptions()).toEqual({ host: 'smtp.test', port: 2525 });
    });
});
```

Because the server-only check is disabled when `TEST === 'true'`, the test can import the `server/` module directly. For logic that is purely a function of configuration, a better design is to make the function *take* the configuration as a parameter and have a single thin module read the environment and pass it in. Then most tests never touch the env system.

```ts
// src/lib/server/mailer.ts
export interface MailerConfig { host: string; port: number }

export function buildTransportOptions(config: MailerConfig) {
    return { host: config.host, port: config.port, secure: config.port === 465 };
}
```

```ts
// src/lib/server/mail.ts: the only place that reads env
import { SMTP_HOST, SMTP_PORT } from '$app/env/private';
import { buildTransportOptions } from './mailer.js';

export const transport = buildTransportOptions({ host: SMTP_HOST, port: SMTP_PORT });
```

### Testing the declaration itself

Your `src/env.ts` validators are code and deserve tests: a `PORT` validator that accepts `"80abc"` is a production incident. Because `defineEnvVars` returns the entries unchanged, you can run them directly: call a Standard Schema validator (such as the valibot schema below) through its `~standard.validate` method, or simply call a plain-function validator with the raw value. (The normalisation of plain functions into Standard Schema happens later, inside SvelteKit, not in `defineEnvVars`.)

```ts
// src/env.spec.ts
import { expect, it } from 'vitest';
import { variables } from './env.js';

function run(name: keyof typeof variables, value: string | undefined) {
    const schema = variables[name].schema as {
        '~standard': { validate: (v: unknown) => { value?: unknown; issues?: unknown[] } };
    };
    return schema['~standard'].validate(value);
}

it('rejects a short session secret', () => {
    expect(run('SESSION_SECRET', 'short').issues).toBeDefined();
});

it('accepts a long session secret', () => {
    expect(run('SESSION_SECRET', 'x'.repeat(40)).issues).toBeUndefined();
});
```

Be aware that `src/env.ts` imports `building` from `$app/env`; in a test this resolves through the SvelteKit plugin (where `building` is `false`) or needs a `vi.mock('$app/env', () => ({ building: false }))`.

### A preflight script for deployments

Because dynamic variables are validated when the server starts, a bad value fails the *rollout*, not the build. Teams that prefer to fail earlier in the pipeline can start the built server in a smoke test with the real configuration and no traffic (for adapter-node, `node --env-file=.env.staging build` and a request to a health endpoint). A deployment that cannot pass validation then never reaches the load balancer. Container orchestrators that wait for readiness probes give you this behaviour for free: the process exits during startup, the probe never passes, and the old revision keeps serving.

### Per-environment configuration that is not an environment variable

Not every runtime setting should be a flat string. Feature-flag payloads, per-tenant configuration and rate-limit tables are better kept in a datastore or a configuration service, read at startup or cached with a TTL, with *only the location and credentials* of that service in the environment. That keeps `src/env.ts` short and stable, and lets you change behaviour without a restart. Whatever you choose, give the application a single module through which configuration is read, so that its shape and validation live in one place.

### Environment variables in the browser and in the service worker

Public variables may be imported from the service worker (`src/service-worker/index.ts`) as well as from components. Static values are inlined into the worker bundle. Dynamic public values cannot be known at build time, so in production the generated worker script imports the prerendered `env.js` module at start; in dev, the current values are inlined. Remember that a service worker has its own lifecycle: it keeps the values it was started with until it is replaced (Chapter 16), so a dynamic public value that changes on the server does not instantly change inside an already installed worker. If correctness depends on promptly picking up a changed value, treat it as data fetched from an endpoint instead.

## Key takeaways

- Declare every environment input in `src/env.ts` with `defineEnvVars`: `public`, `static`, `schema`, `description`. Only declared variables are exposed through `$app/env/private` and `$app/env/public`; exposure is explicit, not prefix-based.
- Validators are synchronous Standard Schemas or plain functions; returning `undefined` makes a variable optional. Invalid values fail the build (static) or the server start (dynamic).
- Dynamic variables are read at startup and need no rebuild; static variables are inlined at build and allow dead-code elimination. Keep per-environment values and secrets dynamic so one build can be promoted across environments.
- Use `building` from `$app/env` to relax validation during build analysis and prerendering. `src/env.ts` may import `$app/env` but not the generated env modules.
- Dynamic public variables reach the browser through the hydration payload, and through a prerendered `env.js` module for prerendered pages and the service worker.
- `.env`, `.env.local` and mode variants are loaded in dev and build, via Vite’s `loadEnv` with an empty prefix; production reads the real environment (`node --env-file=.env build` if you must use a file). `env.dir` relocates the search directory.
- Server-only modules are: `$app/env/private`, `$app/server`, files with a `server` filename segment, and anything in any `server` directory (except `src/routes` and `static`). The check follows import chains from every browser entry point, including dynamic imports; use `import type` for types and `load` for data.
- The check is disabled under `process.env.TEST === 'true'`, so enforce with a real build in CI. Packages and `node_modules` are exempt; add `import '$app/server'` to publish a server-only file.
- `$env/*` and `$app/environment` are deprecated (removal in 4) and are aliases over the explicit modules, so they expose only declared variables; migrate by declaring variables first.
- Never put secrets in data returned from `load`, never echo values in validator errors, and prefer injected platform secrets over committed files.

## Review Questions

1.  In SvelteKit 3, what decides whether an environment variable can be read by browser code? Name the config key and the module you import it from.

2.  What is the type of `LOG_LEVEL` imported from `$app/env/private` here, and why?

    ```ts
    LOG_LEVEL: { schema: (v) => (['debug', 'info'].includes(v ?? '') ? (v as 'debug' | 'info') : (() => { throw new Error('bad'); })()) }
    ```

3.  Why does `STRIPE_SECRET_KEY: {}` count as “required”? What if the deployment sets it to an empty string?

4.  List three characteristics that differ between a `static: true` and a default (dynamic) variable.

5.  Your CI builds a Docker image with no secrets. The build fails with “DATABASE_URL: Value is missing”. Describe two ways to fix it, and state which you prefer and why.

6.  You mark `PUBLIC_API_BASE` as `public: true` (dynamic) and prerender the whole site. How does the browser obtain the value, and what extra request exists as a result? What would change with `static: true`?

7.  Multiple choice: which file is **not** server-only?

    a.  `src/lib/db.server.ts`
    b.  `src/lib/server/db.ts`
    c.  `src/lib/data/server/users/profile.ts`
    d.  `src/routes/server/page-helpers.ts`

8.  Given this import graph, will the build succeed? Explain the chain rule.

    ```text
    src/routes/+page.svelte  -> imports { add } from './utils.js'
    src/routes/utils.js      -> re-exports * from '#lib/server/secrets.js'
    ```

9.  What does the build error message tell you to do if you only use the import as a type? Show the corrected import.

10. Find the bug:

    ```ts
    // src/routes/dashboard/+page.server.ts
    import { API_KEY } from '$app/env/private';
    export const load = async () => ({ apiKey: API_KEY, items: await fetchItems(API_KEY) });
    ```

    What is leaked and how do you fix it?

11. Why are server-only checks disabled when `process.env.TEST === 'true'`? What practice do you adopt to compensate?

12. You publish an npm package containing `src/internal/credentials.js` that must never be bundled for the browser by consumers. What do you add to the file, and why is the directory name rule not enough?

13. Explain what “legacy modules are aliases over the explicit modules” means for `$env/dynamic/private`’s `env` object. What previously-working code breaks?

14. Convert to the SvelteKit 3 system, including the `src/env.ts` entry:

    ```ts
    import { env } from '$env/dynamic/private';
    import { PUBLIC_SENTRY_DSN } from '$env/static/public';
    const dsn = PUBLIC_SENTRY_DSN;
    const secret = env.WEBHOOK_SECRET;
    ```

15. What does `building` equal while prerendering, while serving requests in production, and in `vite dev`? Name a piece of code that should be guarded by it.

16. Why may `src/env.ts` import `building` from `$app/env` but not `DATABASE_URL` from `$app/env/private`?

17. A validator is `schema: async (v) => await check(v)`. What happens, and why?

18. In production on `adapter-node`, a `.env` file sits next to `build/`, but dynamic variables are empty. Why, and what are two fixes?

19. Which of these should be `static: true`, and which dynamic, for a build-once/deploy-many pipeline? (a) `DATABASE_URL`, (b) `PUBLIC_RELEASE` (git SHA stamped at build), (c) `PUBLIC_API_BASE` that differs per environment, (d) `PUBLIC_ENABLE_DEBUG` used to remove a dev overlay from production bundles.

20. Name three kinds of variable that are fine to mark `public: true`, and one that never is.

21. A validator throws ``new Error(`invalid: ${value}`)`` for a secret. Why is this a problem and how do you rewrite it?

22. Design: a monorepo keeps `.env` at the repository root while the SvelteKit app is in `apps/web`. How do you make dev and build pick it up?

23. A team argues “everything under `src/lib/server` is private, so we can export from it to our `+server.ts` JSON endpoint freely.” What is the flaw in this reasoning?

24. What is `description` for, and where does it show up?

25. Scenario: a Vercel build uses `VERCEL_GIT_COMMIT_SHA` to stamp the release. At runtime the variable is unavailable. How do you declare it, and why?

26. You see `%sveltekit.env.SECRET_KEY%` in `app.html` for a variable declared without `public: true`. What do you expect to happen and why is that the right behaviour?
