# Chapter 16: Environment, Security and CSP

Every production Astro site eventually has to answer three questions: where do configuration values and secrets come from, who is allowed to talk to the server, and what is the browser allowed to execute. Astro answers each with a distinct subsystem. Environment variables are handled by Vite’s `import.meta.env` and, since Astro 5, by the typed `astro:env` module. Request integrity is handled by the origin check, host validation and body-size limits under `security`. Script and style containment is handled by the built-in Content Security Policy (CSP) feature, stable since Astro 6.

These subsystems share a common property that makes them tricky: each one works at a different moment. Vite variables are replaced at build time. `astro:env` secrets are resolved at request time through the adapter. CSP hashes are computed at build time (for static content) and merged at render time (for dynamic content). A senior engineer needs to know which moment applies, because the failure modes (a leaked secret, a 500 on first request, a blocked island) all come from mixing them up.

This chapter uses a small test project built against Astro 7.4.1, `@astrojs/svelte` 9.1.0, Svelte 5.57.2 and `@astrojs/node` 11.x. Where the documentation is ambiguous, I report what the build and the running server actually did.

## Two environment systems

### Vite’s `import.meta.env`

Astro inherits Vite’s mechanism. Variables come from the process environment and from `.env`, `.env.local`, `.env.[mode]` and `.env.[mode].local` files in the project root. Only variables prefixed with `PUBLIC_` are exposed to client code; everything else is available on the server only. The built-ins are `MODE`, `PROD`, `DEV`, `BASE_URL` and `SITE`.

The word to focus on is *replaced*. Since Astro 6 the `staticImportMetaEnv` behaviour is baked in: `import.meta.env.X` is statically inlined into the bundle at build time and is not coerced to another type. For a server-rendered application this has an important consequence: the value that ends up in your server bundle is the value that was present when you ran `astro build`. If you build once in CI and promote the same artifact through staging and production, `import.meta.env.API_URL` will be the CI value in every environment. This is the main reason to prefer `astro:env` for anything that varies per deployment.

There are two configuration-time caveats:

- `.env` files are **not** loaded while `astro.config.mjs` is evaluated, so `import.meta.env` is not usable there. Use `process.env`, or Vite’s `loadEnv`:

```js
// astro.config.mjs
import { defineConfig } from 'astro/config';
import { loadEnv } from 'vite';

const { SITE_URL } = loadEnv(process.env.NODE_ENV ?? 'production', process.cwd(), '');

export default defineConfig({
  site: SITE_URL,
});
```

- Under pnpm, `vite` must be a direct dependency for that import to resolve.

You can type user-defined `PUBLIC_` variables by extending `ImportMetaEnv` in `src/env.d.ts`. That is a type-level promise only; nothing validates the value.

The `--mode` flag selects which `.env.[mode]` file to load (`astro build --mode staging`). Mode does not change `import.meta.env.PROD`: a `--mode staging` build is still a production build.

> **Warning:** `import.meta.env.SECRET_KEY` in server code compiles into the server bundle as a string literal. The bundle is not public, but it is an artifact: it lands in container layers, CI caches and sourcemaps. If a value must be rotatable without rebuilding, or must never be written to disk by the build, it does not belong in `import.meta.env`.

### `astro:env`: a schema for configuration

`astro:env` addresses four weaknesses of raw env access: no validation, no type information beyond `string | undefined`, no explicit client/server boundary, and no runtime resolution for adapters whose environment is not `process.env`.

You declare a schema in `astro.config.mjs` with `envField`:

```js
// astro.config.mjs
import { defineConfig, envField } from 'astro/config';
import svelte from '@astrojs/svelte';
import node from '@astrojs/node';

export default defineConfig({
  output: 'server',
  adapter: node({ mode: 'standalone' }),
  integrations: [svelte()],
  env: {
    schema: {
      PUBLIC_SHOP_NAME: envField.string({ context: 'client', access: 'public', default: 'Shop' }),
      PAYMENT_URL: envField.string({ context: 'server', access: 'public', url: true, optional: true }),
      PAYMENT_KEY: envField.string({ context: 'server', access: 'secret', min: 8 }),
      MAX_ITEMS: envField.number({ context: 'server', access: 'public', default: 5, int: true, gt: 0 }),
      TIER: envField.enum({ context: 'server', access: 'public', values: ['dev', 'prod'], default: 'dev' }),
    },
  },
});
```

Every field has a `context` (`'client'` or `'server'`) and an `access` (`'public'` or `'secret'`). The valid combinations produce three kinds of variable:

| Context | Access | Importable from | Where the value lives |
|------------------|------------------|------------------|------------------|
| `client` | `public` | `astro:env/client` (client and server) | Inlined into client and server bundles |
| `server` | `public` | `astro:env/server` | Inlined into the server bundle |
| `server` | `secret` | `astro:env/server` | Never in a bundle; read at runtime |

`client` + `secret` is rejected because there is no safe way to deliver a secret to a browser.

The remaining options are `optional` (default `false`), `default`, and type-specific validators. Reading `node_modules/astro/dist/env/schema.d.ts` for 7.4.1, strings accept `max`, `min`, `length`, `url`, `includes`, `startsWith`, `endsWith`; numbers accept `gt`, `min`, `lt`, `max`, `int`; enums need `values`. Booleans take only `optional` and `default`. Validation is Zod-based and reports every failing field at once.

Types are generated into `.astro/` when you run `astro dev`, `astro build` or `astro sync`.

Usage is a normal import:

```html
---
// src/pages/index.astro
import { PAYMENT_KEY, MAX_ITEMS, TIER, getSecret } from 'astro:env/server';
---
<h1>{MAX_ITEMS} {TIER} {PAYMENT_KEY.length} {getSecret('OTHER')}</h1>
```

```html
<!-- src/components/Hello.svelte -->
<script lang="ts">
  import { PUBLIC_SHOP_NAME } from 'astro:env/client';
  let n = $state(0);
</script>

<button onclick={() => n++}>{PUBLIC_SHOP_NAME} {n}</button>
```

Importing `astro:env/server` from a `.svelte` file that is hydrated on the client fails the build, which is exactly the guarantee you want: the client/server split is enforced by module resolution, not by convention.

### Where `astro:env` can and cannot be used

The documentation lists the supported places (middleware, routes, endpoints, `.astro` components, framework components, ordinary modules) and two unsupported ones: `astro.config.mjs` and scripts. Testing the boundary on 7.4.1 refines the second item:

- A bundled `<script>` in an `.astro` file that imports a **client public** variable works. The value was found inlined in the client chunk.
- A bundled `<script>` that imports from `astro:env/server` **fails the build**.

So “scripts” in the doc’s limitation list really means “scripts, for server variables”. In configuration files you must fall back to `process.env` or `loadEnv`, because the virtual module does not exist until the config has been evaluated.

### Secrets: build time versus request time

The secret path has the most surprising semantics, and the docs are in tension with themselves. The guide says that “by default, all secrets are validated whenever anything is imported from the `astro:env/server` module” and suggests passing dummy values for the build. The configuration reference says that by default only *public* variables are validated at dev/build start and secrets are validated at runtime; `validateSecrets: true` adds validation of secrets on start.

I tested both on a server-rendered project in which the page imports `PAYMENT_KEY`:

| Scenario | Result |
|------------------------------------|------------------------------------|
| `validateSecrets` unset, `PAYMENT_KEY` absent at build | Build succeeds |
| Same bundle started without `PAYMENT_KEY`, first request | HTTP 500, `EnvInvalidVariables: PAYMENT_KEY is missing` |
| Started with `PAYMENT_KEY=short` (schema says `min: 8`) | HTTP 500, “constraints for PAYMENT_KEY are not met: min” |
| `validateSecrets: true`, key absent at build | Build fails with `EnvInvalidVariables` |
| Started correctly | 200; secret value was *not* found in `dist/` |

The behaviour matches the configuration reference. Two practical conclusions:

1.  Failure is lazy. A server that starts with a missing secret will report “listening” and only fail when a request first touches the module. Put a health-check route that imports `astro:env/server` into your deployment checks, or set `validateSecrets: true` in CI builds so a broken pipeline fails before release.
2.  A *prerendered* page that reads a secret at build time obviously needs the value during the build. The “dummy values” advice in the guide applies in that case, and also whenever `validateSecrets: true` is set.

### `getSecret()`

`getSecret(key)` returns the raw string (or `undefined`) for any key, including keys not in your schema. Its implementation is supplied by the adapter, which is why you should prefer it over `process.env` in code that might run on Cloudflare Workers, where the environment is a binding object rather than a global. In dev and build it falls back to `process.env`. Use it for dynamic names (per-tenant keys) and for reading a boolean as its original string. Values obtained this way are not validated.

Adapter authors wire this up with `setGetEnv` from `astro/env/setup`; see Chapter 18.

### Choosing between the systems

| Need | Use |
|------------------------------------|------------------------------------|
| Build-time constant identical in all environments (`PUBLIC_` flag, analytics ID) | `import.meta.env.PUBLIC_*` or `astro:env/client` |
| Per-deployment value, same artifact promoted | `astro:env/server` (public or secret) |
| Anything sensitive | `astro:env/server` secret, never `import.meta.env` |
| Config-file time | `process.env` / `loadEnv` |
| Third-party code that reads `process.env` | Leave it; Astro does not rewrite it |

> **Senior tip:** declare the schema even for variables you only use on the server and never validate with `getSecret`. A schema is documentation, an inventory for the operations team, and a startup-time contract (with `validateSecrets: true`) all at once.

## The `security` configuration

### `checkOrigin`: CSRF protection for forms

`security.checkOrigin` defaults to `true`. It applies only to on-demand rendered routes and only to “unsafe” requests (`POST`, `PUT`, `PATCH`, `DELETE`) whose `content-type` is absent or one of `application/x-www-form-urlencoded`, `multipart/form-data`, `text/plain`. These are exactly the content types a cross-site HTML form can send without a CORS preflight. The check uses the `Sec-Fetch-Site` header when the browser sends it and falls back to `Origin`. A cross-origin request receives a 403 and the page never renders.

Measured against the test server:

```bash
# cross-site form post: blocked
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  -H "Origin: https://evil.example" \
  -H 'content-type: application/x-www-form-urlencoded' -d a=1 localhost:4396/
# 403

# same-origin: allowed
curl ... -H "Origin: http://localhost:4396" ...      # 200
curl ... -H "Sec-Fetch-Site: cross-site" ...         # 403

# JSON content type is not covered by the check
curl ... -H "Origin: https://evil.example" -H 'content-type: application/json' ...   # 200
```

The last case is deliberate: a cross-site page cannot send `application/json` without a preflight, so CORS (which you control) is the defence. But it means that **your JSON endpoints must not enable permissive CORS**, and that `checkOrigin` is not a substitute for authentication. If you disable `checkOrigin`, you take responsibility for CSRF tokens or `SameSite` cookie discipline yourself. Actions (Chapter 11) rely on this check for their form flavour.

### `allowedDomains`: host-header injection

Behind a reverse proxy, the server often derives its public URL from `X-Forwarded-Host`. If the proxy forwards a client-supplied header unchecked, an attacker can poison `Astro.url`, which then ends up in canonical links, password-reset emails, redirects and absolute URLs.

`security.allowedDomains` is an allow-list of `{ protocol, hostname, port }` patterns. When it is configured, `X-Forwarded-Host` is honoured only if it matches; otherwise it is ignored and the request’s own host is used. Without any configuration, the header is not trusted at all.

```js
security: {
  allowedDomains: [
    { hostname: '**.example.com', protocol: 'https' },
    { hostname: 'staging.myapp.com', protocol: 'https', port: '443' },
  ],
},
```

`*.example.com` matches exactly one subdomain level; `**.example.com` matches any depth. Using `allowedDomains: [{}]` trusts every domain; the documentation reserves it for deployments behind a trusted proxy with dynamic domains. I confirmed that a request with `X-Forwarded-Host: evil.com` to the unconfigured test server was served normally (200) and not redirected: the header is simply not used for URL construction.

### Body size limits

Two knobs cap request bodies for built-in endpoints, both defaulting to 1 MB (1048576 bytes):

- `security.actionBodySizeLimit` (since 5.18) for `/_actions/*`.
- `security.serverIslandBodySizeLimit` (since 6.0) for `/_server-islands/*` POST requests, whose bodies carry encrypted props and slot HTML.

Raise them deliberately and only as far as needed (for example, `actionBodySizeLimit: 10 * 1024 * 1024` for an upload action). The Node adapter has its own `bodySizeLimit` (default 1 GB) for the server as a whole (Chapter 8); treat that 1 GB figure as a ceiling that you should lower for public deployments.

### Server island encryption

Server island props are encrypted with a key that Astro generates at build time. In a single-instance deployment this is invisible. In a rolling or multi-instance deployment, instances built separately would have different keys and could not decrypt each other’s URLs, so generate one key with `astro create-key` and provide it as `ASTRO_KEY` to every build. A leaked `ASTRO_KEY` lets an attacker forge island props, so it is a secret in the same class as a session signing key. Chapter 9 covers the mechanics.

## Content Security Policy

CSP tells the browser which origins may supply scripts, styles, images, frames and so on. Its main value is limiting the damage from XSS. Astro’s implementation (stable since 6.0, `security.csp`) automates the hardest part: hashing the inline scripts and styles that Astro itself emits so that you do not need `'unsafe-inline'`.

### Enabling it

```js
export default defineConfig({
  security: { csp: true },
});
```

`csp: true` accepts all defaults. With an object, you can tune it:

```js
security: {
  csp: {
    algorithm: 'SHA-256',                  // or 'SHA-384' | 'SHA-512'
    directives: [
      "default-src 'self'",
      "img-src 'self' data: https://images.example.com",
    ],
    scriptDirective: { resources: ["'self'"], hashes: [], strictDynamic: false },
    styleDirective:  { resources: ["'self'"], hashes: [] },
  },
},
```

### What is emitted

By default Astro emits a `<meta http-equiv="content-security-policy">` element in each page’s `<head>`, with `script-src` and `style-src` populated from the scripts and styles that page uses: `'self'` plus a hash for every inline script and style. A meta CSP has limits (it cannot carry `frame-ancestors`, `report-uri` or `sandbox`), which is why the header form matters (see “Headers instead of meta” below).

In my test project (server-rendered, Node adapter with `staticHeaders: true`) the response carried:

```text
content-security-policy: img-src 'self' data:;frame-ancestors 'none'; script-src 'self' 'sha256-3hc9...' 'sha256-xIb/...' ...; style-src 'self' 'sha256-KJ/E...' 'sha256-vv9I...';
```

The eight script hashes are not eight scripts you wrote. Astro’s own island bootstrap (the `astro-island` custom element, the directive scripts, the deserializer) is inlined into the page as `<script>` elements, and each one must be allowed. The page also contains a style rule for `astro-island` and your component styles. Two observations follow:

1.  You do not hand-maintain these hashes. They change whenever Astro or your code changes, which is precisely why the feature exists.
2.  Your own `<script is:inline>` blocks are hashed too, like any other inline script; the hash changes whenever their content changes, which is harmless because it is recomputed on every build. Dynamic content in an inline script (`define:vars`, interpolated JSON) produces a per-request hash on server-rendered pages; this works because the hash is computed at render time, not only at build time.

### Per-page and runtime configuration

The `Astro` global (and `APIContext` in endpoints and middleware) exposes `csp`:

```html
---
// src/pages/checkout.astro
Astro.csp?.insertDirective("frame-ancestors 'none'");
Astro.csp?.insertScriptResource('https://js.payments.example.com');
Astro.csp?.insertStyleResource('https://fonts.example.com');
Astro.csp?.insertScriptHash('sha512-...');
Astro.csp?.insertStyleHash('sha512-...');
---
```

The methods are `insertDirective`, `insertStyleResource`, `insertStyleHash`, `insertScriptResource` and `insertScriptHash`. Use `Astro.csp?.` with optional chaining because `csp` is `undefined` when the feature is off. In the test above, `insertDirective("frame-ancestors 'none'")` from the page appeared in the final header alongside the configured `img-src` directive. Resources and hashes inserted from config and from runtime are merged and deduplicated.

A middleware that sets the same baseline for every route is usually cleaner than per-page calls:

```ts
// src/middleware.ts
import { defineMiddleware } from 'astro:middleware';

export const onRequest = defineMiddleware((context, next) => {
  context.csp?.insertDirective("frame-ancestors 'none'");
  context.csp?.insertDirective("form-action 'self'");
  return next();
});
```

### Overriding `resources`

Supplying `scriptDirective.resources` or `styleDirective.resources` **replaces** Astro’s default sources for that directive. It does not add to them, so include `'self'` yourself if you want it. Hashes Astro generates are added either way. This is an easy mistake: `resources: ['https://cdn.example.com']` without `'self'` blocks your own bundled scripts.

If any directive includes `'unsafe-inline'`, Astro suppresses its hashes on that directive, because browsers ignore `'unsafe-inline'` whenever a hash or nonce is present in the same directive. You then have the security level of `'unsafe-inline'`, i.e. almost none for scripts. Use it only for styles, and only as a conscious trade.

### `kind`: element versus attribute scoping (7.1)

Browsers support finer directives: `script-src-elem` / `script-src-attr` and `style-src-elem` / `style-src-attr`. The most common need is to allow inline `style="..."` attributes (produced by `define:vars`, Shiki, or a Svelte `style:` directive compiled to inline styles) without opening up `<style>` elements. Since 7.1, each entry in `resources` and `hashes` may be an object with a `kind`:

```js
security: {
  csp: {
    styleDirective: {
      resources: [
        "'self'",
        { resource: "'unsafe-inline'", kind: 'attribute' },
      ],
    },
    scriptDirective: {
      hashes: [{ hash: 'sha256-abc...', kind: 'element' }],
    },
  },
},
```

Rules from the reference:

- `'default'` goes to `script-src` / `style-src`; `'element'` to `-elem`; `'attribute'` to `-attr`.
- Attribute sources must be one of `'none'`, `'unsafe-hashes'`, `'unsafe-inline'`, `'report-sample'`; `'unsafe-hashes'` cannot be used with `'element'`.
- When you use `'element'`, Astro moves **its own generated hashes** to the `-elem` directive so they keep working.
- It does **not** move your `'default'` resources. Browsers do not fall back from `-elem` to the generic directive once `-elem` exists, so a default resource such as a CDN host would silently stop applying to `<script>` elements. Astro logs a warning when it sees this mix. Put everything in the specific directive.

The same `kind` object form works in the runtime methods: `Astro.csp?.insertStyleResource({ resource: "'unsafe-inline'", kind: 'attribute' })`.

### `strictDynamic`

`scriptDirective.strictDynamic: true` adds `'strict-dynamic'` to `script-src`. Under `strict-dynamic`, a script that is trusted by hash may load further scripts dynamically, and host-based allow-lists are ignored. It is useful when third-party loaders inject their own scripts. If you also scope scripts with `kind: 'element'`, `strict-dynamic` is inherited by `script-src-elem` so dynamically injected `<script>` elements keep working.

### Svelte islands under CSP

Island hydration does not use `eval` or inline event handlers, so a Svelte 5 island works under the default policy. Points to check:

- The island’s own JavaScript is a same-origin module (`/_astro/Hello.*.js`), covered by `'self'`. If you serve assets from a CDN via `build.assetsPrefix`, add that origin to `scriptDirective.resources`.
- Svelte `style:` directives and `style="..."` on elements produce inline style *attributes* when rendered or applied by script. If your policy forbids them, you will see violations at runtime. Prefer classes, or allow `{ resource: "'unsafe-inline'", kind: 'attribute' }` knowingly.
- Component `<style>` blocks compile to CSS files or `<style>` elements that Astro hashes. They are fine.
- `client:only` islands render entirely in the browser; their styling follows the same rules.

### Limitations you must plan around

1.  **`<ClientRouter />` is incompatible.** The router swaps documents by fetching and parsing HTML, then re-applies scripts and styles. That is incompatible with hash-based enforcement. If you need CSP, either use the native View Transition API for page transitions or accept full page navigations. (This is a principal reason Chapter 20 uses a `<ClientRouter />` build *without* CSP and a CSP build *without* the router, and says so.)
2.  **Shiki is unsupported.** Shiki writes inline `style` attributes on every token. The build prints a warning when CSP is on with default Shiki highlighting: “Shiki syntax highlighting uses inline styles that are not compatible with Content Security Policy (CSP). Consider using Prism…” (this warning appeared in my build). Use `markdown.syntaxHighlight: 'prism'` (and the `<Prism />` component), or allow style attributes via `kind: 'attribute'` knowingly.
3.  **External scripts and styles are not hashed automatically.** A `<script src="https://...">` needs a `resources` entry, or you must supply an integrity hash yourself.
4.  **No dev-mode support.** The Vite dev server injects scripts that cannot be hashed. Test with `astro build && astro preview` (or your adapter’s server).
5.  **`'unsafe-inline'` disables hashes** on that directive, as noted above.

### Headers instead of meta

A `<meta>` policy is the default because it works for static files on any host. It is the weaker form. With on-demand rendering, you can set the `content-security-policy` header yourself in middleware, but then you must duplicate Astro’s hash computation. The supported route is adapter support: the Node adapter’s `staticHeaders: true` (adapter v10+) makes the adapter serve the headers that Astro features produce (CSP being the documented example) on the `Response` instead of a `<meta>` element.

```js
export default defineConfig({
  security: { csp: true },
  adapter: node({ mode: 'standalone', staticHeaders: true }),
});
```

In my test the policy appeared as a response header with a `frame-ancestors 'none'` directive, which a `<meta>` element could not have honoured. Other adapters expose equivalent options; Chapter 8 lists them. Check that your CDN does not strip or override the header.

### Rolling out CSP safely

1.  Enable `csp: true` in a build-and-preview environment first. Open every page type and watch the console for violations.
2.  Fix legitimate violations by adding specific resources, preferring `kind` scoping.
3.  Add baseline directives (`default-src 'self'`, `object-src 'none'`, `base-uri 'self'`, `frame-ancestors 'none'`, `form-action 'self'`). Remember that `default-src` is the fallback for fetch directives you did not list, so adding `default-src 'self'` will break any third-party images or fonts you were not tracking.
4.  Ship it. Astro’s `csp` currently has no report-only mode of its own; if you need one, deliver a separate `Content-Security-Policy-Report-Only` header from your CDN or middleware while iterating. Check the current configuration reference before relying on that gap.

## Cookie, session and authentication hardening

Astro does not ship an authentication system. The guide points to Better Auth, Clerk, Lucia (as a learning resource) and Scalekit, and community integrations. Whatever you pick, the Astro-specific hardening checklist is:

- **Cookies.** `Astro.cookies.set(name, value, { httpOnly: true, secure: true, sameSite: 'lax', path: '/', maxAge })`. `Astro.cookies` defaults to no `httpOnly` and no `secure`; you must ask. The session cookie, by contrast, defaults to `{ name: 'astro-session', sameSite: 'lax', httpOnly: true, secure: true }`. `secure: true` means local HTTP development needs care: browsers treat `localhost` as secure, which is why it generally works.
- **Sessions.** Prefer `Astro.session` (Chapter 12) for server-side state: only an opaque ID is in the cookie. Call `session.regenerate()` on privilege change (login) to prevent session fixation, and `session.destroy()` on logout.
- **Authenticate in middleware, authorize at the handler.** Populate `context.locals.user` in `onRequest`; a coarse redirect there for whole protected sections is a useful outer gate, but each page, endpoint and action still checks what it serves (Chapter 10). Chapter 5 explains why gating by `url.pathname` string matching in advanced-routing pre-processing is unsafe: encoded paths, trailing slashes and rewrites can bypass it. Gate on route patterns or on the resolved resource, not on a pathname you matched yourself.
- **Check at the data layer.** Every action handler and endpoint must authorize independently. `/_actions/*` is a public HTTP surface regardless of where your UI calls it from.
- **Server islands and personalization.** Props to a server island are encrypted but the island URL is a GET endpoint. Do not assume the island request carries the page’s authorization context unless you read cookies inside the island (which you can; they are sent with the request).
- **Error pages.** The `error` prop on `500.astro` is `unknown`; never print its stack in production.
- **Open redirects.** Validate any `next=` parameter before `Astro.redirect(next)`: allow only same-origin relative paths.

## A hardened baseline

Putting the chapter together, a starting point for a server-rendered site:

```js
// astro.config.mjs
import { defineConfig, envField } from 'astro/config';
import node from '@astrojs/node';
import svelte from '@astrojs/svelte';

export default defineConfig({
  site: 'https://shop.example.com',
  output: 'server',
  adapter: node({ mode: 'standalone', staticHeaders: true }),
  integrations: [svelte()],
  security: {
    checkOrigin: true,
    allowedDomains: [{ hostname: 'shop.example.com', protocol: 'https' }],
    actionBodySizeLimit: 256 * 1024,
    serverIslandBodySizeLimit: 256 * 1024,
    csp: {
      directives: [
        "default-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "img-src 'self' data: https://images.example.com",
      ],
      scriptDirective: { resources: ["'self'"] },
      styleDirective: { resources: ["'self'"] },
    },
  },
  markdown: { syntaxHighlight: 'prism' },
  env: {
    validateSecrets: true,
    schema: {
      PUBLIC_SHOP_NAME: envField.string({ context: 'client', access: 'public', default: 'Shop' }),
      PAYMENT_KEY: envField.string({ context: 'server', access: 'secret', min: 8 }),
      PAYMENT_URL: envField.string({ context: 'server', access: 'public', url: true }),
    },
  },
});
```

Verify it with a script that runs in CI against the built server:

```bash
#!/usr/bin/env bash
set -euo pipefail
PAYMENT_KEY=ci-dummy-key PAYMENT_URL=https://pay.test npx astro build
PAYMENT_KEY=ci-dummy-key PAYMENT_URL=https://pay.test PORT=4400 node dist/server/entry.mjs &
PID=$!
sleep 2
curl -sI localhost:4400/ | grep -i '^content-security-policy' | grep -q "frame-ancestors 'none'"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Origin: https://evil.example' \
  -H 'content-type: application/x-www-form-urlencoded' -d a=1 localhost:4400/)
[ "$code" = 403 ]
kill $PID
```

## Key takeaways

- Vite’s `import.meta.env` is replaced at build time; `PUBLIC_` marks client exposure. `.env` files are not loaded in the config file.
- `astro:env` gives a typed, validated schema with `context` (client/server) and `access` (public/secret). `client` + `secret` is invalid.
- Secrets are not bundled and are validated lazily at runtime unless `validateSecrets: true`, in which case the build or start fails fast.
- Server variables cannot be imported into bundled scripts or the config file; client public variables can be imported in scripts.
- `getSecret()` is adapter-aware and unvalidated; use it for dynamic keys.
- `checkOrigin` stops cross-site form-style POSTs with 403, but does not cover JSON requests and is not authentication.
- Configure `allowedDomains` behind proxies; without it `X-Forwarded-Host` is ignored.
- Cap action and server-island bodies deliberately; share one `ASTRO_KEY` across instances.
- CSP hashes Astro’s inline scripts and styles automatically; overriding `resources` replaces defaults, so re-add `'self'`.
- `kind` (7.1) targets `-elem` and `-attr` directives; default resources are not copied into them.
- CSP does not work with `<ClientRouter />`, Shiki or the dev server; prefer headers (Node `staticHeaders`) over meta.
- Populate identity in middleware and authorize again at the handler and data layer; never rely on pathname matching.

## Review Questions

1.  Explain the difference between when `import.meta.env.API_URL` and a `server`/`secret` field from `astro:env/server` receive their values in a server-rendered build.
2.  Why can you not read `.env` values through `import.meta.env` inside `astro.config.mjs`? Name two workarounds.
3.  Which of the following `envField` definitions is invalid, and why?

    a.  `envField.string({ context: 'server', access: 'secret' })`
    b.  `envField.string({ context: 'client', access: 'public', default: 'x' })`
    c.  `envField.string({ context: 'client', access: 'secret' })`
    d.  `envField.number({ context: 'server', access: 'public', int: true })`
4.  A secret declared in the schema is missing in production. With `validateSecrets` unset, at what moment will you find out, and what will the user see?
5.  What does `validateSecrets: true` change, and why is it useful in CI?
6.  Given a bundled `<script>` in an `.astro` file that imports `PUBLIC_SHOP_NAME` from `astro:env/client` and another that imports `PAYMENT_KEY` from `astro:env/server`, what happens to each in `astro build`?
7.  Why does `getSecret()` exist when `process.env` is available on Node?
8.  Find the bug: a developer writes `export const API = import.meta.env.STRIPE_SECRET` in a server module and builds once in CI, then deploys the same image to staging and production with different environment variables. What goes wrong?
9.  Which requests does `security.checkOrigin` inspect? Which header does it prefer, and what is the fallback?
10. A cross-site page sends `fetch('/api/cart', { method: 'POST', headers: {'content-type': 'application/json'}, credentials: 'include', body })`. Does `checkOrigin` block it? What does protect you?
11. What does `security.allowedDomains` protect against, and what happens to `X-Forwarded-Host` when it is not configured?
12. Which does `**.example.com` match: `a.example.com`, `a.b.example.com`, both, or neither? What about `*.example.com`?
13. What are the default values of `actionBodySizeLimit` and `serverIslandBodySizeLimit`, and what do server island request bodies contain?
14. Why must every build of a multi-instance deployment share the same `ASTRO_KEY`?
15. A page has an inline `<script is:inline>` whose content never changes. When does Astro compute its CSP hash, and what if the script interpolates per-request data?
16. What is the effect of `scriptDirective: { resources: ['https://cdn.example.com'] }` on a site whose scripts are served from the same origin?
17. What happens to Astro’s generated hashes on a directive that contains `'unsafe-inline'`? Why?
18. Write the configuration that allows inline `style="..."` attributes but not inline `<style>` elements beyond Astro’s hashes.
19. After setting `scriptDirective.hashes: [{ hash: 'sha256-xyz', kind: 'element' }]` and `resources: ['https://cdn.example.com']`, the CDN script stops loading. Explain.
20. Name three limitations of Astro’s CSP support and one way to deal with each.
21. Why does Svelte’s `style:color={c}` directive matter for a CSP-enabled site?
22. What is the benefit of `staticHeaders: true` on the Node adapter when CSP is enabled? Give one directive that only works in a header.
23. Explain why testing CSP in `astro dev` is not meaningful.
24. Design question: you must add third-party payment scripts (an external `<script src>` and an iframe) to the checkout page only. Which configuration or API calls do you use, and where do you put them?
25. A teammate proposes gating `/admin/*` by testing `new URL(request.url).pathname.startsWith('/admin')` in a pre-processing handler in `src/fetch.ts`. Give two reasons this is unsafe and a safer approach.
26. Multiple choice: which statement about the session cookie defaults is correct?

    a.  `httpOnly: false`, `secure: false`
    b.  `httpOnly: true`, `secure: true`, `sameSite: 'lax'`
    c.  `httpOnly: true`, `sameSite: 'none'`
    d.  No defaults; you must set all options

27. Why should `session.regenerate()` be called after login?
