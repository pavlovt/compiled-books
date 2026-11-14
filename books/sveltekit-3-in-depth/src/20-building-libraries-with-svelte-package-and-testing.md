# Chapter 19: Building Libraries with svelte-package and Testing

This chapter covers two topics that share a theme: code that has to work outside the exact app that wrote it. The first half is about publishing: how `@sveltejs/package` (`svelte-package`) turns `src/lib` into an npm package, what a correct `package.json` looks like, and which SvelteKit features you must not use in library code. The second half is about testing SvelteKit applications: unit, component, integration and end-to-end.

One honest caveat first. The official SvelteKit documentation has a page on packaging but no page on testing. What it does give you is `sv add vitest` and `sv add playwright`, a few changelog entries about Vitest compatibility, and the `process.env.TEST` switch in the server-only module check. Everything else in the testing half is my practice, assembled from those tools, and I label it as such. I ran the commands and tests in this chapter against SvelteKit 3.1.0, `@sveltejs/package` 3.0.1, `sv` 1.1.1, Vitest 4.1 (the version the `sv` templates install; `npm view vitest` shows 5.0.5 as latest, so check what your template pins), `publint` 0.3.25 and Node 22.

## Part 1: Libraries

### The model

An app and a library have the same layout. In an app `src/routes` is public-facing and `src/lib` is internal; in a library `src/lib` is the public surface, the root `package.json` is the published manifest, and `src/routes` is a demo or docs site (or a sandbox). Running `svelte-package` reads `src/lib` and writes `dist/`:

- every file from `src/lib`, with Svelte components preprocessed and TypeScript transpiled to JavaScript;
- `.d.ts` files for Svelte, JS and TS files, placed next to their implementations (hand-written `.d.ts` files are copied as is). This needs `typescript` installed; in 3.0 it is an optional peer dependency so that strict node-linkers work;
- everything else copied untouched.

Since version 2 the tool no longer generates a `package.json`. It uses yours and validates it. Version 3.0 requires Node 22+.

CLI options:

| Option | Meaning | Default |
|------------------------|------------------------|------------------------|
| `-w`, `--watch` | rebuild on changes in `src/lib` | off |
| `-i`, `--input` | input directory | `src/lib` |
| `-o`, `--output` | output directory; `exports` and `files` must point there | `dist` |
| `-p`, `--preserve-output` | do not empty the output directory first | `false` |
| `-t`, `--types` | generate `.d.ts` files | `true` |
| `--tsconfig` | tsconfig or jsconfig path; otherwise the nearest one upward | auto |

### What I observed

I took a scaffolded 3.1 project, added a component and a helper, and ran `svelte-package`. The source:

```html
<!-- src/lib/ui/Counter.svelte -->
<script lang="ts">
    import { BROWSER } from 'esm-env';
    import { clamp } from '#lib/math.js';

    let { start = 0 }: { start?: number } = $props();
    let n = $state(start);
</script>

<button onclick={() => (n = clamp(n + 1, 0, 10))}>{n} {BROWSER ? 'b' : 's'}</button>
```

```ts
// src/lib/index.ts
export { default as Counter } from './ui/Counter.svelte';
export * from './math.js';
```

The output `dist/ui/Counter.svelte` kept the `<script lang="ts">` (Svelte 5 handles TypeScript natively) but its import became `import { clamp } from '../math.js';`. That is the 3.0 feature “transform import aliases into relative imports”: `#lib/math.js`, defined by `imports` in `package.json`, is rewritten for the published artifact because `imports` mappings in a consumer’s resolution would point into your package’s source layout, which does not exist in `dist`. `dist/index.d.ts` came out as the re-exports, `dist/math.d.ts` and `dist/ui/Counter.svelte.d.ts` were generated, and static assets were copied.

Two other things showed up that you should expect on your first run.

First, **test files are published unless you exclude them**. `src/lib/vitest-examples/*.spec.ts` and my `src/lib/server/auth.spec.ts` were compiled into `dist/`. The fix is in `files`:

```json
{
    "files": ["dist", "!dist/**/*.test.*", "!dist/**/*.spec.*"]
}
```

(or an `.npmignore`). Better still, keep tests next to their code but outside the packaged tree when you can, or accept the exclusion rule.

Second, **a server-only warning**: `svelte-package` 3.0 warns when a file named `.server.` or inside a `server` directory does not import a server-only module:

```text
The following server-only files do not import `$app/server` or `$app/env/private`:
- server/auth.spec.ts
These files will not be blocked from being imported on the client. If you intend to use this package within a SvelteKit application and want to prevent this, add `import '$app/server'` ...
```

The reasoning ties to Chapter 13: the import-chain check that blocks server-only code from reaching the browser exempts `node_modules`, so published packages are not checked by file name. A library that has a server-only file must say so by importing `$app/server` (or `$app/env/private`) in it, which throws if it ends up on the client.

### An accurate `package.json`

```json
{
    "name": "@acme/ui",
    "version": "1.0.0",
    "license": "MIT",
    "type": "module",
    "files": ["dist", "!dist/**/*.spec.*"],
    "sideEffects": ["**/*.css"],
    "svelte": "./dist/index.js",
    "types": "./dist/index.d.ts",
    "exports": {
        ".": {
            "types": "./dist/index.d.ts",
            "svelte": "./dist/index.js"
        }
    },
    "peerDependencies": {
        "svelte": "^5.0.0"
    },
    "imports": {
        "#lib": "./src/lib/index.ts",
        "#lib/*": "./src/lib/*"
    }
}
```

Field by field:

- **`files`** lists what npm packs. Include the output directory. `package.json`, README and LICENSE are always included.
- **`exports`** defines entry points. The `types` condition feeds TypeScript, and `svelte` identifies Svelte-aware tooling. A library with no Svelte components that also works elsewhere (a store library) should use `default` instead of `svelte`. Order matters: put `types` first.
- **`svelte`** (top level) is a legacy field for tooling that predates export conditions; keep it pointing at the root entry for compatibility.
- **`sideEffects`**: marks files bundlers may drop when unused. Newly created projects declare `["**/*.css"]` so CSS is retained (webpack compatibility; Vite does not need it). If any script in your library has side effects (patching a global), list it or tree-shaking will break your library. Incorrectly marking a side-effectful file is a functional bug that only appears in consumers’ production builds.
- **`peerDependencies`**: Svelte itself must be a peer, never a regular dependency, or consumers get two copies and runes break in confusing ways.
- **`imports`** (`#lib`) is how you alias inside library code. The docs recommend subpath imports and note `svelte-package` rewrites them.

### Multiple entry points and TypeScript resolution

Adding `./Foo.svelte` to `exports` is straightforward:

```json
{
    "exports": {
        "./Foo.svelte": {
            "types": "./dist/Foo.svelte.d.ts",
            "svelte": "./dist/Foo.svelte"
        }
    }
}
```

The catch is types for sub-paths. With the legacy `moduleResolution: node`, TypeScript does not read `exports`, so `your-library/foo` looks for `foo.d.ts` at the package root. Either require consumers to use `moduleResolution` of `bundler`, `node16` or `nodenext`, which is the future-proof route (SvelteKit 3’s generated tsconfig requires modern settings anyway, so SvelteKit 3 consumers are fine), or add `typesVersions`:

```json
{
    "typesVersions": {
        ">4.0": { "foo": ["./dist/foo.d.ts"] }
    }
}
```

If you adopt `typesVersions` you must declare *all* type imports through it, root included (`"index.d.ts": [...]`). Since the audience of a SvelteKit 3 library is on TypeScript 6 and bundler resolution, I skip `typesVersions` for new libraries and state the requirement in the README.

### Source maps for go-to-definition

`"declarationMap": true` in your `tsconfig.json` emits `.d.ts.map` files so editors jump to your original `.ts` or `.svelte`. The maps contain relative paths, so the sources must be published: add `src/lib` to `files` (with the same test exclusions). It increases package size; I do it for libraries that people read and debug, and skip it for tiny ones.

### Caveats that bite

- **Relative imports need full extensions** following Node ESM: `./something/index.js`, even when the source is `index.ts`. In TypeScript you write `.js`, not `.ts`, because that is what the emitted file is called. Setting `moduleResolution` to `NodeNext` in your tsconfig makes the compiler enforce this. The docs state the rule for `index.js` files explicitly; it applies to every relative import. A related 3.0.0 fix handles `.ts` extensions in `import.meta.glob` patterns when `rewriteRelativeImportExtensions` is on.
- Everything except Svelte and TypeScript files is copied as is. A `.scss` file stays `.scss`; preprocess it yourself or import compiled CSS.
- Svelte component types are generated for the installed Svelte version (3.0.1 fixed an issue where they targeted the oldest version in your peer range).

### What not to do in library code

The docs’ guidance, with the reasoning:

1.  **Avoid SvelteKit modules unless the library is explicitly SvelteKit-only.** `$app/state`, `$app/navigation`, `$app/paths`, `$app/env` do not exist outside a SvelteKit build; a Vite-only or Astro consumer fails to resolve them. Use `esm-env` (`BROWSER`, `DEV`) instead of `$app/env`’s `browser` and `dev`. Pass the current URL or a navigation callback as a prop rather than reading `page.url` inside a shared component. This also makes the component testable in isolation and usable in a UI workshop.
2.  **SSR safety.** Library code runs on the server during SSR. No module-scope access to `window`, `document` or `localStorage`. Guard with `BROWSER` or run in `onMount`/an `$effect`. Module-level mutable state is shared across all requests on the server (Chapter 12); libraries that hold per-user state at module scope leak it between users. Prefer context or instances created per use.
3.  **Treat `exports` as API.** Removing a path, or changing a condition from `svelte` to `default`, is a breaking change; adding a new path is fine.
4.  **Runes.** A library compiled with the consumer’s settings: the sv template sets `compilerOptions.runes` to true except for files under `node_modules`, so libraries can keep legacy syntax without forcing the app. For library code, use runes anyway and declare the Svelte peer range accordingly.

### Shipping remote functions

Libraries that list `@sveltejs/kit` as a peer dependency may ship `*.remote.ts` files (Chapter 7). Constraints from earlier chapters apply: they need both experimental flags in the consuming app, a remote file cannot live in a server-only directory, and since a package is outside the import-chain check, the file does the server-only declaration through the `$app/server` imports it already needs. Mark the requirement in your README, because an app without the flags gets an error from the remote file rather than a friendly message. Version it conservatively: remote functions are experimental, so your package’s compatibility range is bounded by theirs.

### Publishing checklist

My checklist (author practice, using only tools I ran):

1.  `svelte-package` with a clean `dist` (the default empties it).
2.  `npx publint`: it packs with `npm pack` and checks `exports`, `types`, `files` and the like. On my sample package it reported “All good!” after the `exports`/`files` fields above were set; before them it would flag missing fields.
3.  `npm pack --dry-run` and read the file list: no `.spec` files, no secrets, `dist` and (if you want declaration maps) `src/lib` present.
4.  Install the tarball into a throwaway SvelteKit app and import every entry point, including in SSR and in a Vite-only (non-SvelteKit) app if you claim support.
5.  Type-check the consumer with `moduleResolution: bundler`.
6.  Bump the version by semver rules: removals from `exports` are breaking.
7.  `npm publish` (with provenance and 2FA in CI).

Run `svelte-package -w` during development alongside a consumer app that depends on the package through a workspace or `npm link`; the `src/routes` sandbox is the quickest feedback loop.

## Part 2: Testing

### Strategy

The most important design decision for testability in SvelteKit is the same as for any server framework: keep logic out of framework entry points. A `load`, an action, a `+server` handler, a `handle` and a remote function should be thin shells that translate between the web (Request, cookies, params) and plain functions in `#lib`. Test those functions directly and cheaply. Then test the shells with a small number of focused tests, and test the assembled app end to end.

The pyramid I use (author practice):

| Level | Tool | What it proves | Share |
|------------------|------------------|------------------|------------------|
| Unit | Vitest, Node project | Pure logic, validators, mappers, `requireUser`-style helpers with mocks | Most |
| Component | Vitest browser mode + `vitest-browser-svelte` | A component renders and behaves in a real browser | Some |
| Integration | Vitest, Node project, with `Request` objects | `handle`, `+server` handlers, actions, hooks composed | Some |
| End to end | Playwright against `vite preview` | Routing, SSR plus hydration, forms, auth, the real build | Few, critical paths |

### `sv add vitest` and `sv add playwright`

Both are add-ons (`sv` is the CLI; it is the supported way to set up testing):

```bash
npx sv add vitest="usages:unit,component" --no-install
npx sv add playwright=demo:yes --no-install
```

(In the interactive flow they ask what to use Vitest for and whether to include a Playwright demo; the non-interactive syntax above was the form that `sv` 1.1.1 accepted when I ran it. Check `npx sv add --help` for your version.)

The Vitest add-on changed my `vite.config.ts` to this (trimmed to the test section; the SvelteKit options are as scaffolded):

```ts
// vite.config.ts
import { defineConfig } from 'vitest/config';
import { playwright } from '@vitest/browser-playwright';
import adapter from '@sveltejs/adapter-auto';
import { sveltekit } from '@sveltejs/kit/vite';

export default defineConfig({
    plugins: [sveltekit({ adapter: adapter() })],
    test: {
        expect: { requireAssertions: true },
        projects: [
            {
                extends: './vite.config.ts',
                test: {
                    name: 'client',
                    browser: {
                        enabled: true,
                        provider: playwright(),
                        instances: [{ browser: 'chromium', headless: true }]
                    },
                    include: ['src/**/*.svelte.{test,spec}.{js,ts}'],
                    exclude: ['src/lib/server/**']
                }
            },
            {
                extends: './vite.config.ts',
                test: {
                    name: 'server',
                    environment: 'node',
                    include: ['src/**/*.{test,spec}.{js,ts}'],
                    exclude: ['src/**/*.svelte.{test,spec}.{js,ts}']
                }
            }
        ]
    }
});
```

Notes:

- The config imports `defineConfig` from `vitest/config` so the `test` key is typed, and the SvelteKit plugin runs inside Vitest, which is why `$app/*`, `#lib/*`, and `$types` resolve in tests.
- Two **projects**: `client` runs `*.svelte.spec.ts` in a real Chromium via Playwright (browser mode); `server` runs everything else in Node. The naming convention decides where a test runs, which gives you a place to put each kind of test without extra configuration.
- `expect.requireAssertions: true` fails tests that assert nothing, a cheap guard against vacuous tests.
- Scripts added: `test:unit` (`vitest`) and `test` (`npm run test:unit -- --run`, plus `test:e2e` once Playwright is added).
- The template’s component test uses `vitest-browser-svelte`:

```ts
// src/lib/vitest-examples/Welcome.svelte.spec.ts
import { page } from 'vitest/browser';
import { describe, expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import Welcome from './Welcome.svelte';

describe('Welcome.svelte', () => {
    it('renders greetings for host and guest', async () => {
        render(Welcome, { host: 'SvelteKit', guest: 'Vitest' });

        await expect.element(page.getByRole('heading', { level: 1 })).toHaveTextContent('Hello, SvelteKit!');
        await expect.element(page.getByText('Hello, Vitest!')).toBeInTheDocument();
    });
});
```

Locators are role-based and `expect.element` retries until the assertion passes or times out, which removes most timing flakiness inside component tests. Component tests in a real browser have a significant advantage over jsdom: real layout, real events, real CSS. The cost is the browser startup and the need for `npx playwright install` in CI.

The Playwright add-on adds `playwright.config.ts`:

```ts
// playwright.config.ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
    webServer: { command: 'npm run build && npm run preview', port: 4173 },
    testMatch: '**/*.e2e.{ts,js}'
});
```

and a `test:e2e` script (`playwright install && playwright test`). Note what it does: E2E runs against the **production build** served by `vite preview`, not `vite dev`. That is the right default because it tests what ships (preload tags, hydration, bundled code). Note the caveat from Chapter 18: preview runs in Node and does not apply adapter-specific behaviour.

One version point: at the time I ran it, `sv` pinned `vitest` `^4.1.8` and `vitest-browser-svelte` `^2.1.1`, whereas `npm view` reports Vitest 5.0.5 and `vitest-browser-svelte` 3.1.0 as latest. The scaffold is conservative; upgrade deliberately and run the suite.

### Unit tests: pure logic and framework helpers

Plain functions test exactly as anywhere else. The interesting cases are code that touches SvelteKit APIs.

**Redirects and errors are exceptions.** In SvelteKit 2 and 3, `redirect()` and `error()` throw themselves, so a test asserts on the thrown value and identifies it with `isRedirect` or `isHttpError`:

```ts
// src/lib/server/auth.ts
import { getRequestEvent } from '$app/server';
import { redirect } from '@sveltejs/kit';

export function requireUser() {
    const { locals, url } = getRequestEvent();
    if (!locals.user) redirect(303, `/login?next=${encodeURIComponent(url.pathname)}`);
    return locals.user;
}
```

**Mock `$app/server`.** `getRequestEvent()` only works inside a request, so mock the module and hand the test an event stub. This test ran and passed:

```ts
// src/lib/server/auth.spec.ts
import { describe, it, expect, vi } from 'vitest';
import { isRedirect } from '@sveltejs/kit';

const event = { locals: {} as App.Locals, url: new URL('http://x/dash') };
vi.mock('$app/server', () => ({ getRequestEvent: () => event }));

import { requireUser } from './auth';

describe('requireUser', () => {
    it('redirects anonymous users', () => {
        try {
            requireUser();
            expect.unreachable();
        } catch (e) {
            expect(isRedirect(e)).toBe(true);
            expect((e as { location: string }).location).toBe('/login?next=%2Fdash');
        }
    });

    it('returns the user', () => {
        event.locals = { user: { id: 'u1' } };
        expect(requireUser()).toEqual({ id: 'u1' });
    });
});
```

`vi.mock` is hoisted above imports; the factory refers to `event`, which works because the factory runs lazily when the module is first imported (after the `const` line has executed in this file layout). If you hit a “cannot access before initialization” error, use `vi.hoisted`.

**Server-only modules in tests.** The import-chain check that blocks server-only modules from the client would otherwise reject a test importing `#lib/server/db.js` from a component test. It is disabled under Vitest: `process.env.TEST === 'true'` (Vitest sets it) turns off the check, which is why the `server` project can import server modules freely. The corollary is that a test cannot detect an accidental client import of server code; catch that with a build (`vite build` fails) or an E2E run.

**Module state and `building`.** Anything that checks `building` from `$app/env` sees `false` in tests. Initialisation code that must not run during build is unaffected.

### Integration tests with `Request` objects

SvelteKit’s web-standard handlers are simple to call directly.

**`+server` handlers** take an event and return a `Response`. You only need to supply the properties your handler reads; cast the partial event:

```ts
// src/routes/api/echo/+server.ts
import type { RequestHandler } from './$types';
import { error } from '@sveltejs/kit';

export const POST: RequestHandler = async ({ request }) => {
    const body = await request.json().catch(() => null);
    if (!body || typeof body.name !== 'string') error(400, 'name required');
    return Response.json({ hello: body.name });
};
```

```ts
// src/routes/api/echo/server.spec.ts
import { describe, it, expect } from 'vitest';
import { isHttpError } from '@sveltejs/kit';
import { POST } from './+server';

const call = (body: unknown) =>
    POST({
        request: new Request('http://x/api/echo', { method: 'POST', body: JSON.stringify(body) })
    } as Parameters<typeof POST>[0]);

describe('POST /api/echo', () => {
    it('echoes', async () => {
        const res = await call({ name: 'a' });
        expect(await res.json()).toEqual({ hello: 'a' });
    });

    it('400s on bad input', async () => {
        await expect(call({})).rejects.toSatisfy((e) => isHttpError(e, 400));
    });
});
```

The file is named `server.spec.ts` rather than `+server.spec.ts`. Since 3.x, files beginning with `+` that contain `test`, `spec` or `stories` in a routes directory are ignored by the router (changelog: “ignore files with + prefix if they contain test/spec/stories”), so a `+server.spec.ts` would also be safe, but a name without the plus avoids confusion. Both ran in my `server` project (`Tests 5 passed (5)` across three files).

**Actions** are plain functions on the `actions` object. Call them with a partial event containing `request` (a `Request` with `FormData`), `cookies`, `locals`. Assert on the returned `ActionFailure` (`isActionFailure`) or on thrown redirects. Because actions are plain objects, no framework harness is needed.

**`load` functions** likewise: `await load({ params, locals, fetch, ... } as Parameters<typeof load>[0])`. Supply a fake `fetch` to simulate upstreams and assert on the output. For `setHeaders`, pass a `vi.fn()` and assert the call.

**`handle` hooks** are functions of `{ event, resolve }`. Provide a stub `resolve` that returns a `Response` and test the hook in isolation:

```ts
// src/hooks.server.spec.ts
import { describe, it, expect, vi } from 'vitest';
import { handle } from './hooks.server';

function makeEvent(path: string, cookie?: string) {
    return {
        url: new URL('http://x' + path),
        request: new Request('http://x' + path, cookie ? { headers: { cookie } } : undefined),
        cookies: { get: (n: string) => (n === 'sid' ? cookie?.split('=')[1] : undefined) },
        locals: {} as App.Locals,
        route: { id: path },
        tracing: { enabled: false, root: { setAttribute() {}, setAttributes() {} }, current: {} }
    };
}

describe('handle', () => {
    it('attaches the user to locals', async () => {
        const event = makeEvent('/dash', 'sid=abc');
        const resolve = vi.fn(async () => new Response('ok'));
        await handle({ event: event as never, resolve });
        expect(resolve).toHaveBeenCalledOnce();
        // assert on event.locals.user according to your session lookup mock
    });
});
```

When a hook is composed with `sequence`, test the composed export (`handle`) so the ordering is covered, and give each constituent hook a name, because named functions also give you readable span names in traces (Chapter 17).

**What the stubs cannot tell you.** A partial event proves your handler’s logic but not the framework’s behaviour: whether the CSRF check passes, whether `setHeaders` conflicts across layouts, whether a cookie option is valid in a real response. For those, use the real server.

### Testing against the real `Server`

For true integration without a browser, you can boot the built app and send requests to it. The adapter-agnostic way is to build and use `vite preview`, or `node build` with adapter-node, and use `fetch`. In my adapter exercise (Chapter 18) I also invoked a generated `Server` instance directly with `Request` objects (`server.respond(request, { getClientAddress })`) and got correct page and endpoint responses, which is a fast way to test the whole request pipeline including `handle`, routing and rendering with no browser and no port. Because the `Server` class is deprecated for public use in 3.x and the generated instance comes from an adapter, I treat that as a technique for adapter authors and for suites that already build with a known adapter, not a general recommendation. For most teams the answer is `vite preview` plus HTTP requests or Playwright’s `request` fixture:

```ts
// tests/api.e2e.ts
import { expect, test } from '@playwright/test';

test('echo endpoint validates input', async ({ request }) => {
    const bad = await request.post('/api/echo', { data: {} });
    expect(bad.status()).toBe(400);
    const ok = await request.post('/api/echo', { data: { name: 'z' } });
    expect(await ok.json()).toEqual({ hello: 'z' });
});
```

Playwright’s default `testMatch` from the add-on is `**/*.e2e.{ts,js}`, so name it accordingly.

### Remote functions

Remote functions are experimental and not designed to be called from a unit test as is: `query`, `form` and `command` wrap your function with validation and request context, and they are built by SvelteKit’s compiler transform for `*.remote.ts` files. My approach (author practice):

1.  Put the business logic in plain functions (`#lib/server/posts.ts`) and keep the `*.remote.ts` file as a thin wrapper: schema plus a call.
2.  Unit test the plain function and the schema (Standard Schema validators are plain objects: `schema['~standard'].validate(input)`).
3.  Test the wrapper end to end: either through a component test that calls the remote function against the running dev/preview server, or through Playwright, where the real transform, serialisation and CSRF logic apply.
4.  If you must unit test a wrapper, mock `$app/server` to a pass-through (`query: (_schema, fn) => fn`) and be aware you are no longer testing validation, serialisation or `getRequestEvent` behaviour. I do this only for trivial wrappers.

For single-flight mutations (Chapter 8) the interesting bugs are in client updates, `requested` limits and refresh semantics; these are E2E concerns.

### Component tests in practice

Components that depend on `$app/state` (`page`), `$app/navigation` or `$app/paths` need those modules to resolve. They resolve in the `client` project because the SvelteKit plugin is present, but `page` has no real navigation behind it. Two options: pass the data as props (which is the structure I recommend, and is also what library guidance says), or mock the module with `vi.mock('$app/state', ...)` in a test of a component that must read it. A 3.0 changelog item (`ensure importing from $app/navigation works in test files`) addresses imports in test files specifically, so importing `goto` and mocking it with `vi.mock('$app/navigation')` is supported.

Keep component tests behavioural: render with props, interact with role-based locators, assert on visible output. Avoid snapshotting markup that mirrors implementation.

### Playwright end to end

What belongs here: the critical user journeys: sign-in, the purchase or create flow, an enhanced form with validation, a deep link rendered with JavaScript disabled, and a navigation that exercises `load` and caching.

**The preview server.** The add-on’s `webServer` config builds and previews on port 4173 and waits for it. Locally add `reuseExistingServer: !process.env.CI` to avoid rebuilding while iterating.

**Hydration races.** The most common flake in SvelteKit E2E is acting on a server-rendered element before hydration has attached handlers: a click that fires before `use:enhance` is attached triggers a normal form POST and full navigation, which can pass the assertion for the wrong reason or fail intermittently. Strategies:

- Wait for an explicit “app is interactive” signal you control: set `data-hydrated` on `<html>` from an `onMount` in the root layout, and have a Playwright fixture `await page.waitForSelector('html[data-hydrated]')` after `goto`.
- Use Playwright’s auto-waiting locators and web-first assertions (`await expect(locator).toHaveText(...)`) rather than reading text immediately.
- Never `waitForTimeout`.
- For client-side navigations, assert on the destination content or `await page.waitForURL(...)`, not on the click completing.

```html
<!-- src/routes/+layout.svelte -->
<script lang="ts">
    import { onMount } from 'svelte';
    let { children } = $props();
    onMount(() => document.documentElement.setAttribute('data-hydrated', ''));
</script>

{@render children()}
```

```ts
// tests/fixtures.ts
import { test as base, expect } from '@playwright/test';

export const test = base.extend({
    page: async ({ page }, use) => {
        const goto = page.goto.bind(page);
        page.goto = async (url, options) => {
            const response = await goto(url, options);
            await page.waitForSelector('html[data-hydrated]');
            return response;
        };
        await use(page);
    }
});
export { expect };
```

**Auth fixtures.** Logging in through the UI in every test is slow and flaky. Playwright’s pattern is to log in once in a setup project, save `storageState`, and reuse it:

```ts
// playwright.config.ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
    webServer: { command: 'npm run build && npm run preview', port: 4173, reuseExistingServer: !process.env.CI },
    testMatch: '**/*.e2e.{ts,js}',
    projects: [
        { name: 'setup', testMatch: /auth\.setup\.ts/ },
        {
            name: 'app',
            dependencies: ['setup'],
            use: { storageState: 'playwright/.auth/user.json' }
        }
    ]
});
```

```ts
// tests/auth.setup.ts
import { test as setup, expect } from '@playwright/test';

setup('sign in', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Email').fill('e2e@example.com');
    await page.getByLabel('Password').fill(process.env.E2E_PASSWORD!);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL('/dashboard');
    await page.context().storageState({ path: 'playwright/.auth/user.json' });
});
```

(Keep `playwright/.auth` out of version control.) Use a seeded test account or, better, a test-only endpoint guarded by an environment flag that mints a session, so E2E does not depend on a mail or OAuth provider. Never expose such an endpoint in production builds; gate it on a variable declared in `src/env.ts` and absent in production.

**Test the no-JS path where you promise it.** Forms with progressive enhancement should work without JavaScript. `test.use({ javaScriptEnabled: false })` in a spec file runs it with scripting off and verifies the plain POST/redirect flow, which unit tests cannot cover.

**Network control.** For deterministic tests, point the app’s upstream (the API your `load` calls) at a stub server or a test database, set via environment variables read at start. SvelteKit’s `handleFetch` (Chapter 9) is a good seam: rewrite the base URL to a mock in the test environment. Mocking inside the browser with `page.route` only affects browser-originated requests, not server-side `fetch` during SSR.

### CI patterns

A pipeline (author practice):

```yaml
# .github/workflows/ci.yml (essentials)
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 24, cache: npm }
      - run: npm ci
      - run: npx svelte-kit sync
      - run: npm run check          # svelte-check + types
      - run: npm run lint
      - run: npx vitest --run       # server + client projects
      - run: npx playwright install --with-deps chromium
      - run: npm run build
      - run: npx playwright test
        env: { CI: 'true', E2E_PASSWORD: '${{ secrets.E2E_PASSWORD }}' }
      - uses: actions/upload-artifact@v4
        if: failure()
        with: { name: playwright-report, path: playwright-report/ }
```

Points: run `svelte-kit sync` before type-checking so `$types` exist (the `prepare` script does it after install); cache the Playwright browser download; run the build once and reuse it; retry E2E at most once in CI (`retries: process.env.CI ? 1 : 0`) and treat any test that needs the retry as a bug to fix; capture traces on first retry (`use: { trace: 'on-first-retry' }`); run component tests in the same job only if the browser is installed; fail on console errors in E2E with a fixture that listens to `page.on('pageerror')`, which catches hydration mismatches that otherwise pass quietly. Pin action versions to current majors in your own pipeline; the ones above are illustrative.

### What to test, concretely

A short list to calibrate effort (author practice):

- Every `handle` hook branch: auth success, auth failure, health-check exemption, header policy.
- Every action’s failure shapes (`fail(400, ...)`) and its success redirect.
- `load` error paths: `error(404)` for missing records, authorisation failures.
- `reroute`/`params.ts` matchers: they are pure functions; test accepted and rejected inputs and round-tripping (`resolve()` symmetry, Chapter 3).
- Cache header policy for pages that set `Cache-Control` (Chapter 16): assert on the `setHeaders` call.
- The error taxonomy in `handleError` by `kind` (Chapter 17), including that unknown errors return a safe message and never throw.
- E2E: one test per business-critical journey, plus a no-JS test for each progressively-enhanced form.

## Key takeaways

- `svelte-package` turns `src/lib` into `dist`, preprocessing Svelte and TypeScript and generating `.d.ts`; it validates your own `package.json` rather than generating one. 3.0 requires Node 22, rewrites `#` subpath imports to relative paths, and warns about server-only files that lack a server-only import.
- Correct `package.json`: `files` (exclude specs), `exports` with `types` then `svelte`, legacy `svelte` field, `sideEffects` listing CSS and any side-effectful script, and Svelte as a peer dependency.
- Relative imports need full extensions (`./x/index.js` even for TypeScript). Sub-path exports need modern `moduleResolution` or `typesVersions` for types.
- Library code avoids `$app/*` (use `esm-env`, props), must be SSR-safe, and must not hold per-user module-level state. Removing an export is a breaking change.
- Run `publint` and inspect `npm pack --dry-run` before publishing; test the tarball in a consumer.
- Official docs have no testing guide: the supported path is `sv add vitest` and `sv add playwright`, plus the `process.env.TEST` exemption from the server-only check. Everything else here is author practice.
- The Vitest template has a `client` project (browser mode, `*.svelte.spec.ts`) and a `server` project (Node, other specs). Run E2E against `vite preview` of a real build.
- `redirect()` and `error()` throw; assert with `isRedirect` and `isHttpError`. Mock `$app/server` to unit test `getRequestEvent` helpers. Call handlers, actions, loads and hooks with partial event objects and `Request`s.
- Remote functions: keep logic in plain functions behind thin `*.remote.ts` wrappers; test wrappers end to end.
- Playwright: wait for hydration with an explicit signal, reuse `storageState` for auth, test the no-JS path where promised, stub upstreams server-side, and fail on page errors.

## Review Questions

1.  What does `svelte-package` read and write by default, and which of its inputs does it validate rather than generate?
2.  List the CLI options of `svelte-package` and what `-p` changes.
3.  In a library, `Counter.svelte` imports `#lib/math.js`. What does the published `dist/ui/Counter.svelte` import, and why is this rewrite necessary?
4.  Why should `svelte` be a peer dependency rather than a dependency of a component library?
5.  Explain the order and purpose of the `types` and `svelte` conditions in `exports`. When would you use `default` instead of `svelte`?
6.  A consumer on `moduleResolution: node` cannot find types for `your-lib/foo`. Give two fixes, and one drawback of `typesVersions`.
7.  What does `sideEffects: ["**/*.css"]` tell bundlers, and what can go wrong if a library file with side effects is not listed?
8.  Why must relative imports in library source use `./x/index.js` even when the file is `index.ts`?
9.  Why does `declarationMap: true` also require publishing `src/lib`?
10. A library component uses `import { browser } from '$app/env'`. Why is that a problem, and what is the replacement? What is the alternative for reading the current URL?
11. Why is module-scope state in a library dangerous during SSR?
12. Which changes to `exports` are breaking, and which are not?
13. What does the 3.0 warning about server-only files mean, and what do you add to silence it correctly?
14. What constraints apply when a library ships a `*.remote.ts` file?
15. What does `publint` do, and what should you check manually in `npm pack --dry-run`?
16. State the one fact about testing in the SvelteKit documentation that determines how a book chapter must label its testing advice.
17. What do the `client` and `server` projects in the scaffolded Vitest config run, and how does Vitest decide which project a test belongs to?
18. What does `expect.requireAssertions: true` do, and why is it useful?
19. **What does this test do?** `expect(() => requireUser()).toThrow()` where `requireUser` calls `redirect(303, '/login')`. What is a better assertion and why?
20. Why does a test of a helper that calls `getRequestEvent()` need `vi.mock('$app/server', ...)`?
21. What does `process.env.TEST === 'true'` disable, and what bug can that hide?
22. Why does the chapter name the file `server.spec.ts` rather than `+server.spec.ts`, and is the other choice harmful?
23. Show how to call a `POST` handler with a JSON body in a Vitest test, and how to assert that it threw `error(400)`.
24. What can a stubbed `{ event, resolve }` test of `handle` not verify? Give two examples.
25. How would you structure a remote function so most of its logic is unit-testable?
26. Why does the Playwright add-on run tests against `npm run build && npm run preview` instead of `vite dev`, and what does preview still not reproduce?
27. Describe the hydration race that makes clicks flaky in SvelteKit E2E tests and two ways to avoid it.
28. How does the `storageState` pattern speed up authenticated E2E tests? Where must the saved file not live?
29. **Multiple choice.** Which is the best signal to fail an E2E test on hydration problems?
    a.  A `waitForTimeout(2000)` after navigation
    b.  A `pageerror`/console error listener fixture
    c.  Checking only the HTTP status
    d.  Running tests with `retries: 5`
30. **Design:** Write a testing plan for a SvelteKit app with cookie auth, form actions, two remote functions and a `+server` webhook endpoint: which test at which level for each, and what runs in CI.
