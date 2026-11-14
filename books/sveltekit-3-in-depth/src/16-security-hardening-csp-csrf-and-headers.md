# Chapter 15: Security Hardening: CSP, CSRF, and Headers

A framework can remove entire classes of vulnerability by default and still leave your application exposed. Svelte escapes text interpolation; SvelteKit checks request origins, restricts redirects, keeps server-only modules out of bundles and ships safe cookie defaults. None of that stops you from rendering untrusted HTML with `{@html}`, fetching an attacker-chosen URL from your server, returning a whole database row from `load`, or leaving a login endpoint open to brute force. This chapter is a hardening guide organised around what SvelteKit actually does, with precise behaviour verified against the 3.1 sources, and what remains your job.

We start with a threat model for a typical SvelteKit application, then cover Content Security Policy in depth (modes, nonces versus hashes, prerendered pages, Trusted Types, third-party scripts, report-only), the exact mechanics of CSRF protection, security headers and cookies in `handle`, redirect safety, server-side request forgery, data exposure through serialised `load` output, and denial-of-service limits including the 3.x-specific ones (`BODY_SIZE_LIMIT`, `requested(limit)`, batching). Authentication-specific advice is in Chapter 14; deployment details for headers on each platform are in Chapter 18. As in the previous chapter, a callout marks recommendations that are the author’s practice rather than documented framework behaviour.

## A threat model for SvelteKit apps

| Threat | Where it enters | What SvelteKit gives you | What you must do |
|------------------|------------------|------------------|------------------|
| Cross-site scripting (XSS) | `{@html}`, unsafe attribute values (`href="javascript:..."`), third-party scripts, injected template values | Escaping in templates; CSP support with automatic nonces/hashes | Sanitise any HTML you render; set a CSP; avoid dynamic `href`/`src` from user input without scheme checks |
| Cross-site request forgery | Form-style mutating requests, remote function calls | Origin check (production), `sameSite=lax` cookie default | Never mutate on `GET`; configure `paths.origin` behind proxies; keep `trustedOrigins` tight |
| Server-side request forgery (SSRF) | `fetch` in `load`, actions, endpoints with user-supplied URLs | `event.fetch` semantics (relative URLs, credential forwarding rules) | Allow-list destinations; block private ranges; disable redirects |
| Open redirects | `redirect()` with user-supplied targets | External redirects refused unless allowed (3.0) | Validate targets yourself |
| Data exposure | Server `load` return values, `+server` JSON, error messages, serialised fetch responses | Server-only modules, header filtering on serialised fetches | Return only what the page needs; sanitise errors |
| Credential attacks | Login and reset endpoints | Nothing built in | Rate limit, hash passwords, resist enumeration (Chapter 14) |
| Denial of service | Large bodies, expensive remote calls, unbounded batches | `BODY_SIZE_LIMIT` (adapter-node), `requested(limit)` | Validate sizes; bound work per request; rate limit |
| Clickjacking | Your pages framed by others | Nothing automatic | `frame-ancestors` CSP or `X-Frame-Options` header |
| Transport downgrade | HTTP access | `secure` cookie default | HSTS header; HTTPS everywhere |
| Supply chain | npm dependencies, third-party scripts | None | Lockfiles, review, CSP, subresource integrity |

The sections below take these in order of how often they matter.

## Cross-site scripting

Svelte compiles `{value}` interpolation to text-node or escaped-attribute assignment, so ordinary template expressions are safe. The ways to reintroduce XSS in a SvelteKit app are a short, well-known list.

**`{@html}`** inserts raw HTML. Treat every use as a vulnerability until proven otherwise, and sanitise the string with a maintained sanitiser *on the server*, before it reaches the client, ideally at write time or in `load`:

```ts
// src/routes/post/[slug]/+page.server.ts
import type { PageServerLoad } from './$types';
import { renderMarkdown } from '#lib/server/markdown.js'; // markdown -> sanitised HTML
export const load: PageServerLoad = async ({ params }) => {
    const post = await getPost(params.slug);
    return { title: post.title, html: renderMarkdown(post.markdown) };
};
```

```html
<!-- src/routes/post/[slug]/+page.svelte -->
<script lang="ts">
    let { data } = $props();
</script>
<h1>{data.title}</h1>
<!-- html has been sanitised in load; see renderMarkdown -->
{@html data.html}
```

**URL-valued attributes.** `<a href={user.website}>` is safe from HTML injection but not from `javascript:` URLs. Allow only `http:` and `https:` (and perhaps `mailto:`):

```ts
// src/lib/safe-url.ts
export function safeHref(value: string): string | undefined {
    try {
        const u = new URL(value);
        return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : undefined;
    } catch {
        return undefined;
    }
}
```

**Template placeholders.** `app.html` is substituted verbatim. `%sveltekit.env.NAME%` inserts the value of a public variable *without HTML escaping* (Chapter 13); do not use it for values that can contain quotes or markup, and prefer reading `$app/env/public` in a component, where Svelte escapes it. `transformPageChunk` in `handle` operates on raw HTML strings; never interpolate user input into it.

**Third-party scripts** run with full authority in your origin. Every script you add can read any non-`httpOnly` cookie, `localStorage` and the DOM, and can issue authenticated requests. A CSP limits where they can load from and what they can do, but the real control is to include fewer of them.

**Serialised data in the page.** SvelteKit embeds `load` data in the HTML using devalue, with `<` and other dangerous characters escaped, so data containing `</script>` does not break out. The risk is not injection but *exposure*, covered below.

## Content Security Policy

A CSP is a response header (or, where that is impossible, a `<meta>` tag) that tells the browser which sources of scripts, styles, images, frames, connections and so on are legitimate. A strict CSP turns most XSS bugs from “full compromise” into “blocked and reported”. SvelteKit’s contribution is that **it generates the hard part for you**: the framework emits inline `<script>` and `<style>` elements (the hydration bootstrap, inlined CSS), and with a CSP it adds the nonce or hash that lets exactly those elements run.

### Configuration

CSP is configured in `sveltekit({...})` in `vite.config.ts` (there is no `svelte.config.js` in SvelteKit 3):

```ts
// vite.config.ts
import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-node';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [
        sveltekit({
            adapter: adapter(),
            csp: {
                mode: 'auto',
                directives: {
                    'default-src': ['none'],
                    'script-src': ['self'],
                    'style-src': ['self'],
                    'img-src': ['self', 'data:', 'https://images.example.com'],
                    'font-src': ['self'],
                    'connect-src': ['self'],
                    'manifest-src': ['self'],
                    'worker-src': ['self'],
                    'form-action': ['self'],
                    'base-uri': ['self'],
                    'object-src': ['none'],
                    'frame-ancestors': ['none'],
                    'upgrade-insecure-requests': true
                },
                reportOnly: undefined
            }
        })
    ]
});
```

Details of the shape:

- `directives` is an object whose keys are directive names; values are arrays of sources (or `true` for boolean directives like `upgrade-insecure-requests`). **Write keywords without quotes**: `'self'`, `'none'`, `'unsafe-inline'`, `'strict-dynamic'` are written as the strings `self`, `none`, … and SvelteKit adds the quotes the header requires (the list it quotes: `self`, `unsafe-eval`, `unsafe-hashes`, `unsafe-inline`, `none`, `strict-dynamic`, `report-sample`, `report-sha256`, `report-sha384`, `report-sha512`, `wasm-unsafe-eval`, `script`). Nonce and hash sources (`nonce-...`, `sha256-...`) are quoted automatically too. Host sources (`https://images.example.com`) are left alone.
- `reportOnly` takes the same shape and emits `Content-Security-Policy-Report-Only`. SvelteKit **requires** at least one of `report-uri` or `report-to` when `reportOnly` has any directives, because a report-only policy without a reporting endpoint does nothing but cost bytes; it throws a configuration error otherwise.
- You may set both: an enforced baseline policy and a stricter candidate policy in `reportOnly` to evaluate before tightening.

### What SvelteKit adds

For each dynamically rendered response, SvelteKit inspects your `script-src` (or `default-src` when `script-src` is absent) and `style-src` (same fallback), and:

- if the effective script policy does **not** contain `'unsafe-inline'` (or contains `'strict-dynamic'`), it adds a nonce or hash source for each inline script it emits;
- the same for styles it inlines (for example when `inlineStyleThreshold` is set, Chapter 11), and it adds the hash of Svelte’s `/* empty */` style comment to `style-src-elem` when that directive is configured, so that Svelte’s runtime style handling does not break the policy;
- in **development**, it injects `'unsafe-inline'` into the style directives (and removes nonce/hash sources there, since `unsafe-inline` is ignored when a nonce or hash is present), because Vite injects `<style>` tags for HMR. The development policy therefore does not validate your production policy; test with `vite build && vite preview`.

It deliberately does **not** append sources to `default-src`, because Firefox does not ignore nonce sources there consistently; it ensures that `script-src` and `style-src` exist as separate directives carrying the nonces.

### Nonce, hash or auto

| `mode` | Inline element source | Needs per-request randomness | Works with prerendered pages |
|------------------|------------------|------------------|------------------|
| `'nonce'` | `nonce-<random>` per response | Yes | **No**: forbidden (a prerendered page is served identically to everyone, so the nonce would be fixed and guessable) |
| `'hash'` | `sha256-<digest of the element's text>` | No | Yes |
| `'auto'` (default) | Nonce for dynamic pages, hash for prerendered pages | Dynamic only | Yes |

`'auto'` is the right default. Setting `'nonce'` and also prerendering any page is an error during the build (“Cannot use prerendering if `config.csp.mode === 'nonce'`”). Likewise, if `app.html` contains `%sveltekit.nonce%` and a page is prerendered, the build fails, because the placeholder cannot be filled with a safe value.

Hash mode has one trade-off: SvelteKit must compute the SHA-256 of every inline element on every response (cheap for prerendered pages, which do it once at build time, but non-zero for dynamic ones), while a nonce is a single random value per response.

### Prerendered pages: `<meta>` limitations

Prerendered pages are static files; there is no response to attach a header to, so SvelteKit writes the policy as `<meta http-equiv="content-security-policy" content="...">`. Browsers ignore three things in the meta form: `frame-ancestors`, `report-uri` and `sandbox`. SvelteKit omits them from the tag. Consequences:

- **Clickjacking protection** for prerendered pages (`frame-ancestors`) must come from the host: set a `Content-Security-Policy: frame-ancestors 'none'` or `X-Frame-Options: DENY` header at your CDN or static host.
- **Reporting** on prerendered pages cannot use `report-uri` via meta. Configure reporting at the host if you need it.
- The meta tag is parsed after everything that precedes it in the document, so it should be (and is, in SvelteKit’s output) emitted early in `<head>`; a policy cannot restrict resources that were already requested before it was parsed.

Prerendered pages also bypass `handle` entirely, so the security-header logic in the next section does not run for them either. A mixed site therefore needs headers in two places: `handle` for dynamic responses, and the platform (`_headers` on Netlify/Cloudflare Pages, `vercel.json` headers, an nginx `add_header`, and so on) for static ones.

### `%sveltekit.nonce%` and third-party scripts

For scripts and links you add to `src/app.html` manually, use the placeholder:

```html
<!-- src/app.html -->
<!doctype html>
<html lang="en">
    <head>
        <meta charset="utf-8" />
        %sveltekit.head%
        <script nonce="%sveltekit.nonce%">
            window.dataLayer = window.dataLayer || [];
        </script>
    </head>
    <body data-sveltekit-preload-data="hover">
        <div style="display: contents">%sveltekit.body%</div>
    </body>
</html>
```

The placeholder is only valid for dynamically rendered pages; with `mode: 'auto'` and any prerendered page that uses this template, the build fails as described above. If you need a nonce-bearing inline script *and* prerendering, separate them: keep the nonce-dependent snippet out of the shared template, or move the code into your bundled JavaScript (which SvelteKit already loads from `'self'` via the nonce-protected bootstrap).

What about a third-party script (analytics, a chat widget)? Options, from safest to least:

1.  **Self-host it** (or proxy it through a first-party path) and allow only `'self'`.
2.  **Load it from a bundled module** (`import()` from your code), so that the origin is yours.
3.  **Allow the host in `script-src`.** Simple but broad: anything that host serves can run. Be aware that `'strict-dynamic'` makes browsers ignore host allow-lists, so combine them carefully.
4.  **Inject it from a nonced inline snippet in `app.html`** that creates the script element. With `'strict-dynamic'`, scripts created by a trusted (nonced) script are trusted transitively; this is the practical way to add tag managers under a strict policy. Note that this makes the third party able to load anything, which is exactly the trust you are granting it.

> **Warning:** Scripts placed in `<svelte:head>` of a component do not receive SvelteKit’s nonce automatically. SvelteKit adds the nonce/hash to the elements *it* emits. Under a nonce-based policy, route third-party loading through `app.html` or bundled code as above.

### `strict-dynamic`

A strict policy based on nonces typically looks like `script-src 'nonce-abc' 'strict-dynamic'`, which says: trust scripts carrying this nonce, and any scripts those scripts load dynamically; ignore host allow-lists. SvelteKit’s client entry loads further chunks through dynamic `import()`, which `strict-dynamic` permits transitively. Its type definitions list `strict-dynamic` as a valid action source for `script-src` and `default-src`. In dev SvelteKit does not rewrite it (the logic that would drop it is commented out in the source), so verify your production policy against the built output.

### Report-only rollout

Introduce a CSP in stages, because a policy that blocks one forgotten analytics host in production is an outage.

```ts
// vite.config.ts (excerpt): enforce the baseline, observe the stricter candidate
csp: {
    mode: 'auto',
    directives: {
        'script-src': ['self'],
        'object-src': ['none'],
        'base-uri': ['self']
    },
    reportOnly: {
        'default-src': ['self'],
        'script-src': ['self', 'report-sample'],
        'style-src': ['self'],
        'img-src': ['self', 'data:'],
        'report-uri': ['/csp-report']
    }
}
```

```ts
// src/routes/csp-report/+server.ts
import type { RequestHandler } from './$types';

export const POST: RequestHandler = async ({ request }) => {
    // browsers send application/csp-report or application/reports+json; cap the size
    const text = await request.text();
    if (text.length < 10_000) console.warn('[csp-report]', text);
    return new Response(null, { status: 204 });
};
```

The `report-sample` keyword includes the first 40 characters of the blocked inline code in reports, which helps identify offenders. Note the origin-check subtlety: browsers post reports with content type `application/csp-report`, which is not one of the form-style content types the CSRF check applies to, so this endpoint works without `trustedOrigins`. Rate limit and size-limit it: it is an unauthenticated write endpoint that attackers can flood.

Version 3.1 adds support for the CSP hash-reporting keywords `report-sha256`, `report-sha384` and `report-sha512`: they are accepted in `script-src`/`default-src` and quoted correctly in the emitted header. They are part of the evolving *CSP Hash Reporting* feature, where supporting browsers report the hashes of loaded scripts so you can inventory them; check browser support before depending on them.

### Trusted Types

If you enable `require-trusted-types-for: ['script']`, browsers require DOM-injection sinks (`innerHTML`, `eval`, script URLs) to receive `TrustedHTML`/`TrustedScriptURL` objects produced by registered policies. SvelteKit creates two policies and enforces at build time that you allow them:

- `'svelte-trusted-html'` must be in `trusted-types` unless **all** pages have `csr = false`, because Svelte’s runtime uses a policy for `{@html}` and template cloning. A missing entry fails the build.
- `'sveltekit-trusted-url'` must be in `trusted-types` when `serviceWorker.register` is `true`, because the service-worker registration snippet passes its script URL through that policy.

```ts
// vite.config.ts (excerpt)
csp: {
    directives: {
        'require-trusted-types-for': ['script'],
        'trusted-types': ['svelte-trusted-html', 'sveltekit-trusted-url']
    }
}
```

Trusted Types does not make `{@html}` safe: the policy’s `createHTML` passes the string through. It prevents *accidental* sinks in third-party code. Sanitisation is still your job.

### When the config is not enough: CSP in `handle`

`csp` covers a static directive set plus automatic nonces. If you need per-request directives (tenant-specific `frame-ancestors`, a policy that depends on the route), set the header yourself in `handle` and leave the `csp` option off. You lose the automatic nonce injection, so such a policy cannot be nonce-based unless you do the work of finding and nonce-ing inline elements via `transformPageChunk`. In practice, per-request variation is better expressed as a small set of static policies selected by route group, applied through `handle`, with a hash-based or `'self'`-only script policy.

## CSRF: exactly what is checked

The protection is enabled in production and has no off switch in 3.x (`csrf.checkOrigin` was removed). It lives early in request handling, **before the `handle` hook runs**, and is **skipped entirely in development** (so failures appear only after deployment). There are two different checks.

### Non-remote requests (actions, `+server.ts`, form posts)

A request is rejected with `403` (“Cross-site POST form submissions are forbidden”, as text, or JSON if `Accept` is `application/json`) when **all** of the following are true:

1.  the method is `POST`, `PUT`, `PATCH` or `DELETE`;
2.  the content type is one of `application/x-www-form-urlencoded`, `multipart/form-data`, `text/plain`, SvelteKit’s binary form type, **or the request has no content type at all**;
3.  the `Origin` header is **not** equal to the app’s own origin;
4.  the `Origin` header is **not** in `csrf.trustedOrigins`.

Several consequences follow:

- The check targets exactly the requests a malicious *HTML form* on another site can produce. A cross-site `fetch` with `Content-Type: application/json` is not a “simple” request, so browsers preflight it; CORS (not this check) decides whether it runs. SvelteKit therefore does not check JSON requests: a `+server.ts` `POST` handler consuming JSON relies on CORS and `sameSite` cookies.
- **Missing `Origin` header on a form-style mutating request is rejected.** Browsers send `Origin` on cross-site posts; non-browser clients (curl, server-to-server) that post form data without it are blocked. Webhooks that post JSON are unaffected. Webhooks that post form-encoded data from a provider’s servers are a problem: server-to-server requests rarely carry an `Origin` header at all, and `trustedOrigins` cannot help, because it is compared against that header. The practical choices are to have such providers post JSON (or another non-form content type), or to receive these webhooks on a separate service.
- `GET`, `HEAD` and `OPTIONS` are never checked. **State changes on `GET` are your bug**, and no framework feature protects them.

### Remote function requests

For remote function calls the rule is stricter and simpler: **any non-`GET` request** is rejected with `403` (“Cross-site remote requests are forbidden”) unless its `Origin` equals the app’s origin, regardless of content type, and **`trustedOrigins` is not consulted**. Remote function endpoints are an implementation detail rather than a public API, so there is no way to open them to other origins. Cross-origin clients need ordinary `+server.ts` endpoints (Chapter 14). Queries use `GET` and are not origin-checked, which is another reason to keep them free of side effects.

### What “the app’s origin” is

The reference origin is `paths.origin` if you set it, otherwise the origin of `request.url`, which the adapter derives from the platform. With `adapter-node` that is the `Host` header plus `https` (or `PROTOCOL_HEADER`/`HOST_HEADER`/`PORT_HEADER` if set). Getting this wrong is the single most common production CSRF-check problem: behind a TLS-terminating proxy that forwards plain HTTP and drops the original host, every form post fails with 403. Two correct fixes:

```ts
// vite.config.ts: fix the origin in configuration (works on every adapter)
sveltekit({
    paths: { origin: 'https://www.example.com' }
})
```

or, for `adapter-node` behind a *trusted* proxy, tell the adapter which headers carry the original values: `PROTOCOL_HEADER=x-forwarded-proto HOST_HEADER=x-forwarded-host`. Only set these when a proxy you control overwrites them; otherwise clients can spoof the origin the check compares against.

`paths.origin` is a *build-time* config value. If one build is promoted across environments with different origins (staging, production, a preview deployment per branch), no single constant is right for all of them. Either build once per environment, reading the origin from an environment variable when `vite.config.ts` is evaluated, or use the forwarded-header approach, which is evaluated at runtime.

### `csrf.trustedOrigins`

```ts
sveltekit({
    csrf: { trustedOrigins: ['https://checkout.stripe.com', 'https://accounts.google.com'] }
})
```

Each entry is a complete origin including scheme. `'*'` disables the protection for non-remote requests, which is “generally not recommended” (the type documentation’s wording). Treat every entry as a statement that this third party may post forms to your authenticated endpoints with your users’ cookies attached. A form POST from a trusted origin still carries your users’ session cookie if its `SameSite` setting permits, so confine such endpoints to idempotent or token-verified operations (verify a signed payload from the provider rather than trusting the cookie).

### What the origin check does not cover

- **Subdomain takeover and same-site attackers.** An attacker who controls `evil.example.com` can make requests with an `Origin` of `https://evil.example.com`; that does not match, so the check blocks it. But cookies scoped to the registrable domain are readable by sibling subdomains: do not set `Domain=` on session cookies, and use the `__Host-` prefix.
- **XSS.** An XSS payload runs *same-origin*, so every CSRF check passes. CSP and sanitisation are the controls.
- **Old browsers that omit `Origin`.** A request without `Origin` is rejected for form-style mutating requests, which fails closed.

## Security headers in `handle`

A baseline set of response headers is cheap and effective. Put them in a dedicated handle and compose with `sequence` (Chapter 9):

```ts
// src/hooks.server.ts
import type { Handle } from '@sveltejs/kit/hooks';
import { sequence } from '@sveltejs/kit/hooks';
import { dev } from '$app/env';

const securityHeaders: Handle = async ({ event, resolve }) => {
    const response = await resolve(event);

    // Headers on a Response returned by resolve() are mutable for rendered pages,
    // but a Response you did not construct (e.g. from fetch) may have immutable headers.
    const headers = new Headers(response.headers);

    headers.set('x-content-type-options', 'nosniff');
    headers.set('referrer-policy', 'strict-origin-when-cross-origin');
    headers.set('permissions-policy', 'camera=(), microphone=(), geolocation=(), payment=()');
    headers.set('cross-origin-opener-policy', 'same-origin');
    headers.set('cross-origin-resource-policy', 'same-origin');

    if (!dev) {
        // 2 years; add 'preload' only after verifying every subdomain works over HTTPS
        headers.set('strict-transport-security', 'max-age=63072000; includeSubDomains');
    }

    // clickjacking defence for dynamic pages when the CSP (from the csp config) has no frame-ancestors
    if (!headers.get('content-security-policy')?.includes('frame-ancestors')) {
        headers.set('x-frame-options', 'DENY');
    }

    return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers
    });
};

export const handle = sequence(securityHeaders /*, authenticate, guard */);
```

Notes on each header:

- **`X-Content-Type-Options: nosniff`** stops browsers from interpreting a response as a different type than declared. Essential for any endpoint serving user-uploaded content.
- **`Referrer-Policy`**: `strict-origin-when-cross-origin` is a good default, preventing path and query leakage (which may contain tokens) to other origins.
- **`Permissions-Policy`** disables powerful features you do not use.
- **COOP/CORP** isolate your pages from cross-origin windows and block other origins from embedding your resources. Test before enabling: `Cross-Origin-Resource-Policy: same-origin` will break legitimate cross-origin use of your assets (for example images fetched by an embedding partner). Enable `Cross-Origin-Embedder-Policy` only if you need cross-origin isolation (`SharedArrayBuffer`); it is demanding.
- **HSTS** tells browsers to use HTTPS for the host for `max-age` seconds. It is sticky: a mistake outlives your deployment. Roll out with a short `max-age` first. Only send it over HTTPS (browsers ignore it over HTTP).
- **`frame-ancestors` / `X-Frame-Options`** prevent clickjacking. If you configure `csp.directives['frame-ancestors']`, SvelteKit sets it for dynamic pages. `X-Frame-Options: DENY` is the legacy equivalent.

> **Note:** Constructing a new `Response` as above copies the body stream reference but not any streaming trailers, and loses the original object identity. For most applications that is fine; if you rely on `Response` subclasses or are wrapping streaming `+server` responses, mutate `response.headers` only when the headers are mutable and catch the failure, or set the headers at the platform layer instead.

Where to put what:

| Layer | Use for |
|------------------------------------|------------------------------------|
| `handle` | Dynamic responses from SvelteKit; per-request logic (nonces via `csp` config, route-dependent headers) |
| Platform/CDN (`_headers`, `vercel.json`, nginx) | Static assets and **prerendered pages** (which bypass `handle`), HSTS at the edge, `frame-ancestors` for static pages |
| `<meta http-equiv>` | CSP only, as emitted by SvelteKit for prerendered pages; limited directives |

### Cookies

Review the defaults in Chapter 14. A few additional points: never set a cookie without an explicit `path`; avoid `Domain=` unless you need subdomain sharing; set `maxAge`/`expires` deliberately; and remember that `cookies.set` from a server `load` runs on every request that triggers the load, so use actions or `handle` for auth cookies. Cookies set in remote `form` and `command` functions are permitted; setting arbitrary *headers* in remote functions is not.

## Redirect safety

SvelteKit 3 hardens `redirect()`: a location that is not on the current origin throws unless you opt in with `{ external: true }` (any external URL except `javascript:` and `data:`) or an allow-list of origins (the only way to allow `javascript:`/`data:` URLs is to list them, which you should never do). Protocol-relative locations such as `//evil.example` resolve to another origin and are treated as external.

```ts
import { redirect } from '@sveltejs/kit';

// Same-origin: always fine
redirect(303, '/dashboard');

// Specific external hosts: prefer allow-lists
redirect(302, 'https://accounts.example.com/login?...', { external: ['https://accounts.example.com'] });

// Any external URL: only for destinations that are fixed by your code, never user input
redirect(302, PARTNER_URL, { external: true });
```

The allow-list compares **scheme and host** (and port) of the location with each entry. Because it parses with the URL standard rather than string prefixes, tricks such as `https://accounts.example.com.evil.net` or `https://accounts.example.com@evil.net` do not match.

Treat this as defence in depth. User-supplied targets (`?next=`) still need your own validation (Chapter 14’s `safeRedirectTarget`), because an erroring `redirect()` produces a 500, not a safe fallback. Also note that the *client-side* `goto()` rejects external URLs; to leave the app, use `window.location` or a normal link.

## Server-side request forgery

Whenever server code issues a request to a URL influenced by a user, you have an SSRF risk: the attacker aims your server at internal services (cloud metadata endpoints such as `169.254.169.254`, databases, admin panels) or exfiltrates data through callbacks. SvelteKit’s `event.fetch` has two relevant properties, neither of which is a defence:

- Relative URLs are resolved against the app and requests to your own endpoints are handled internally without a network hop.
- It forwards the `cookie` and `authorization` headers on requests to your own origin and to subdomains that are *more specific* than it (credentials are not sent to unrelated hosts). This is intended for same-app calls, and means an attacker-controlled path that points at *your* API is called with the user’s credentials.

The defence is to constrain what is fetched. This is author practice:

```ts
// src/lib/server/safe-fetch.ts
import { error } from '@sveltejs/kit';
import { isIP } from 'node:net';

const ALLOWED_HOSTS = new Set(['api.partner.example', 'images.partner.example']);

export async function fetchAllowed(input: string, init: RequestInit = {}): Promise<Response> {
    let url: URL;
    try {
        url = new URL(input);
    } catch {
        error(400, 'Invalid URL');
    }

    if (url.protocol !== 'https:') error(400, 'Only https is allowed');
    if (url.username || url.password) error(400, 'Credentials in URLs are not allowed');
    if (isIP(url.hostname)) error(400, 'IP literals are not allowed');
    if (!ALLOWED_HOSTS.has(url.hostname)) error(400, 'Host not allowed');

    const res = await fetch(url, {
        ...init,
        redirect: 'manual', // a redirect could point to an internal address
        signal: AbortSignal.timeout(5_000)
    });

    if (res.status >= 300 && res.status < 400) error(502, 'Unexpected redirect');
    return res;
}
```

Allow-lists beat deny-lists. If you truly must fetch arbitrary user-supplied URLs (link previews, webhooks to customer endpoints), do it from an isolated service with no access to internal networks, resolve DNS yourself and reject private, loopback and link-local ranges *at connect time* (DNS rebinding defeats check-then-fetch), cap response size and time, and never return the raw response body to the user.

You can enforce server-wide outbound rules centrally with the `handleFetch` hook (Chapter 9), which sees every `event.fetch` made on the server:

```ts
// src/hooks.server.ts (excerpt)
import type { HandleFetch } from '@sveltejs/kit/hooks';

export const handleFetch: HandleFetch = async ({ request, fetch }) => {
    const url = new URL(request.url);
    // only allow calls to our own API and one partner
    if (url.origin !== 'https://api.example.com' && url.hostname !== 'api.partner.example') {
        // internal (relative) requests reach handleFetch too; adjust to your topology
        if (!request.url.startsWith('http://sveltekit-prerender') && url.hostname !== 'localhost') {
            return new Response('Blocked outbound request', { status: 403 });
        }
    }
    return fetch(request);
};
```

Adapt that example to your topology before using it; it is a starting point and not a complete policy. Plain `fetch` (the global) bypasses `handleFetch`, so enforce by convention (a lint rule banning the global `fetch` in server code) and not only by hook.

## Data exposure

Many “security bugs” in full-stack apps are data bugs: the right user gets *too much* data. SvelteKit’s design makes data flow visible, but also makes over-sharing easy.

### Server `load` output is public

Everything a server `load` returns is serialised into the HTML (for SSR) and into `__data.json` responses, and delivered to the browser. Returning a database row returns every column:

```ts
// BAD: returns passwordHash, internalNotes, stripeCustomerId...
export const load = async ({ locals }) => ({ user: await db.users.findById(locals.user!.id) });

// GOOD: an explicit projection
export const load = async ({ locals }) => {
    const u = await db.users.findById(locals.user!.id);
    return { user: { id: u.id, name: u.name, email: u.email, avatarUrl: u.avatarUrl } };
};
```

Make the projection a habit: define view types (`PublicUser`, `ProjectSummary`) in server modules with mapper functions, so that adding a column to the table never changes what leaves the server. In TypeScript, avoid spreading rows (`{ ...row }`) into returned objects.

Related exposures:

- **`+server.ts` JSON** has the same problem.
- **Streamed promises** from server `load` are serialised too; a rejected promise’s error goes through `handleError`.
- **Custom classes** serialised through your `transport` hook (Chapter 9) expose whatever the `encode` function emits.
- **Layout data** is merged into `page.data` for every page below it; data returned for one page’s benefit is visible to all pages’ components and to anyone reading the document.
- **`page.error` and error messages.** The message you pass to `error(status, message)` is shown to users, and for *unexpected* errors SvelteKit shows a generic message and calls `handleError`, whose return value becomes the user-facing error. Return only safe fields from `handleError`; log the rest.

### Serialised `fetch` responses and header filtering

When a server `load` uses `event.fetch`, SvelteKit inlines the response in the HTML so that the browser does not repeat the request on hydration. Response *headers* are not included by default; `resolve`’s `filterSerializedResponseHeaders(name, value)` option decides which are:

```ts
// src/hooks.server.ts
import type { Handle } from '@sveltejs/kit/hooks';

export const handle: Handle = ({ event, resolve }) =>
    resolve(event, {
        // default is to include none; allow only what the browser needs
        filterSerializedResponseHeaders: (name) => name === 'content-type' || name === 'etag'
    });
```

Never allow-list `set-cookie` (SvelteKit drops it anyway for safety in many paths, but do not rely on that) or `authorization`-like headers. The *body* of an inlined fetch is serialised verbatim: when a server `load` fetches an upstream API and the page only needs two fields, you are shipping the whole upstream JSON to every visitor. Fetch in a server `load` and project, or fetch in universal `load` only from APIs whose full response you are happy to expose.

### Server-only modules protect code, not data

As Chapter 13 explained, importing `#lib/server/...` from the browser is a build error, and importing `$app/env/private` likewise. That keeps *secrets embedded in code* out of bundles. It does nothing for values you return. Review every `return` in a server `load`, action, `+server` handler and remote function as an outbound data flow.

### Source maps and errors

Production source maps are off by default in Vite builds. If you enable them (for error reporting), upload them to your error tracker and do not serve them publicly; they expose your source. SvelteKit hides stack traces for 404s and shows only generic messages for unexpected errors; keep verbose error output out of responses in production, including from custom `handleError` implementations.

### Environment variables in HTML

Public variables are public. `%sveltekit.env.X%`, `$app/env/public` and static public values end up in client-visible output. Chapter 13 covers the declaration discipline.

## Denial of service

Availability is a security property. SvelteKit apps have some documented limits and some places where the limit is yours to set.

**Request body size (adapter-node).** `BODY_SIZE_LIMIT` defaults to 512 kilobytes and applies to the body *including while streaming* (a request that lies about `Content-Length` or uses chunked encoding is cut off at the limit). Raise it deliberately for upload routes, using unit suffixes (`BODY_SIZE_LIMIT=10M`). The value `Infinity` disables the limit and moves responsibility into your own code (a `handle` check). Because the limit is global, apps with a few large upload endpoints often put uploads on a separate service or use pre-signed uploads directly to object storage, keeping the main app’s limit low. Other adapters rely on the platform’s own limits (serverless request size caps, Cloudflare/Netlify body limits).

**Timeouts.** `adapter-node` supports `KEEP_ALIVE_TIMEOUT` and `HEADERS_TIMEOUT` (seconds) to bound idle connections and slow-header attacks (“slowloris”); `SHUTDOWN_TIMEOUT` bounds graceful shutdown. A reverse proxy or load balancer in front should also enforce request timeouts and connection limits.

**Expensive work per request.** Anything that triggers heavy computation, unbounded database queries or external calls on unauthenticated input is a DoS amplifier. Validate and bound inputs: page sizes, maximum string lengths (`v.maxLength`), array sizes (`v.maxLength` on arrays), and nesting. Put sensible `LIMIT`s on queries. Rate limit by principal and address (Chapter 14).

**Remote function amplification.** Remote functions have two features worth bounding:

- **`requested(query, limit)`** (single-flight mutations, Chapter 8): a client can ask the server to refresh arbitrary instances of a query during a mutation. The `limit` argument is **required** for this reason: without it a malicious client could list thousands of query arguments and make one mutation trigger thousands of refreshes. Arguments beyond the limit are recorded as failures for the client instead of being run. Choose the smallest limit that your UI needs (typically one to a handful), and remember that every instance you refresh costs a query execution on the server.
- **`query.batch`** collects calls made within one macrotask into a single request and passes the whole array of arguments to your function. The array size is determined by the client. Validate that your batch function does one bounded query (an `IN (...)` with a maximum on the number of ids, for example) and cap the array length, rather than looping with one query per element.

```ts
// src/routes/projects.remote.ts
import * as v from 'valibot';
import { query } from '$app/server';

export const getProjectTitles = query.batch(v.pipe(v.string(), v.uuid()), async (ids) => {
    if (ids.length > 200) throw new Error('too many ids'); // surfaces as an internal error; tune to your needs
    const rows = await db.projects.findMany({ where: { id: { in: ids } }, select: { id: true, title: true } });
    const byId = new Map(rows.map((r) => [r.id, r.title]));
    return (id) => byId.get(id) ?? null;
});
```

(The exact handling of a thrown error inside a batch is covered in Chapter 7; the point here is that the cap is yours to apply.)

- **`query.live`** holds a connection open per subscriber. Count and bound subscriptions per user, and be aware of proxy buffering and idle timeouts.

**Prerendering as protection.** Pages that can be prerendered are immune to per-request cost: the CDN absorbs traffic. Prefer prerendering and caching for public content, and keep dynamic rendering for what needs it (Chapters 11 and 16).

**Parsing costs.** Server `load` data and form data are parsed with devalue and `formData()`; cap body sizes so that parsing time is bounded. Regular expressions in validators and routes (`params` matchers run on every request; Chapter 3) should avoid catastrophic backtracking: use linear-time constructs and test with long, adversarial inputs.

## Supply chain

SvelteKit’s build pipeline runs your dependencies’ code at build time and ships much of it to browsers. Commit lockfiles, install with `--frozen-lockfile` or `npm ci` in CI, review dependency updates, and run an audit step. Prefer few, well-maintained dependencies in the *browser* bundle, and use Subresource Integrity (`integrity` attributes) for any third-party script you cannot self-host. A CSP with no third-party script hosts is the strongest mitigation against a compromised CDN.

## A hardening checklist

1.  `csp` configured with `mode: 'auto'`, `object-src 'none'`, `base-uri 'self'`, `frame-ancestors` and a script policy without `unsafe-inline`; verified against a production build; rolled out via `reportOnly` first.
2.  Prerendered pages covered by platform-level headers (they bypass `handle`).
3.  `paths.origin` or forwarding headers set so the CSRF check sees the right origin; deployment tested with a real form post (the check is off in dev).
4.  No state changes on `GET`; `csrf.trustedOrigins` empty or minimal exact origins.
5.  Baseline headers set: `nosniff`, `Referrer-Policy`, `Permissions-Policy`, HSTS (after staging), clickjacking protection.
6.  Every `{@html}` fed by sanitised input; URL-valued attributes scheme-checked.
7.  Every server `load`, `+server` handler and remote function returns an explicit projection.
8.  `filterSerializedResponseHeaders` allow-lists specific headers; `handleError` returns only safe fields.
9.  Outbound fetches from user input use an allow-list and `redirect: 'manual'`.
10. `redirect()` targets from user input validated; external redirects allow-listed.
11. `BODY_SIZE_LIMIT` set deliberately; `requested(limit)` small; batch and live query sizes bounded; rate limiting on unauthenticated writes.
12. Secrets only in dynamic private variables with validators; no secret echoes in logs.

## Key takeaways

- Svelte escapes interpolation; XSS comes from `{@html}`, `javascript:` URLs, verbatim template substitution and third-party scripts. Sanitise server-side and constrain URL schemes.
- CSP lives in `sveltekit({ csp })` in `vite.config.ts`. Write keywords unquoted; SvelteKit quotes them and adds nonces or hashes for the inline scripts and styles it emits, but only when your policy does not already allow `'unsafe-inline'`. It does not nonce scripts you place in `<svelte:head>`.
- `mode: 'auto'` uses nonces for dynamic pages and hashes for prerendered pages; nonce mode and `%sveltekit.nonce%` are incompatible with prerendering. Prerendered pages get a `<meta>` CSP, which ignores `frame-ancestors`, `report-uri` and `sandbox`, and they bypass `handle`, so static headers belong on the host.
- `reportOnly` needs `report-uri` or `report-to`. Trusted Types requires `svelte-trusted-html` (unless every page has `csr = false`) and `sveltekit-trusted-url` (when the service worker is registered). The `report-sha*` keywords arrived in 3.1.
- CSRF protection is production-only, runs before `handle`, and rejects form-style mutating requests (`POST/PUT/PATCH/DELETE` with form content types or none) whose `Origin` differs from the app origin and is not in `trustedOrigins`. Remote function non-GET calls require the same origin and ignore `trustedOrigins`. JSON requests are governed by CORS. Fix the origin with `paths.origin` or trusted forwarding headers.
- Add baseline security headers (`nosniff`, `Referrer-Policy`, `Permissions-Policy`, HSTS, clickjacking protection) in a `handle` composed with `sequence`, and mirror them at the platform for static and prerendered responses.
- `redirect()` refuses external targets unless `{ external: true }` or an allow-list is supplied; this is a backstop, not input validation.
- SSRF is yours to prevent: allow-list destinations, use `redirect: 'manual'`, time-limit, and consider `handleFetch` for central policy.
- Server `load` and `+server` outputs are public data. Return explicit projections, filter serialised response headers, and sanitise errors. Server-only modules protect code, not returned values.
- Bound everything an attacker controls: `BODY_SIZE_LIMIT`, timeouts, array and string lengths, `requested(limit)`, `query.batch` input sizes, live-query subscriptions, and unauthenticated write endpoints.

## Review Questions

1.  A SvelteKit 3 project has no `svelte.config.js`. Where do you configure a CSP, and how do you write the `'self'` keyword in the directive arrays?

2.  Under what condition does SvelteKit add a nonce to the inline `<script>` it emits? What happens if your `script-src` contains `'unsafe-inline'` and nothing else relevant?

3.  Compare `mode: 'nonce'`, `'hash'` and `'auto'`. Which one makes a prerender-containing build fail, and why is a nonce unsafe on a prerendered page?

4.  A prerendered page’s CSP is delivered as a `<meta>` tag. List the three directives that are dropped and state a consequence for clickjacking protection of that page.

5.  Your `app.html` includes `<script nonce="%sveltekit.nonce%">...</script>` and one route is prerendered. What happens at build time, and what are two ways to resolve it?

6.  Why does a CSP configured through `csp` not validate your production policy when you run `vite dev`? What do you do about it?

7.  A marketing team adds a tag manager via `<svelte:head><script src="..."></script></svelte:head>` in a layout. Under your nonce-based `script-src`, what happens and why? Give two compliant ways to include it.

8.  What does `reportOnly: { 'script-src': ['self'] }` do on its own, and what does SvelteKit do about it?

9.  Which two `trusted-types` entries can SvelteKit require, and under what conditions is each required? What does Trusted Types not protect against?

10. Explain precisely when SvelteKit’s non-remote CSRF check rejects a request. Evaluate: (a) a cross-site HTML form posting `application/x-www-form-urlencoded`; (b) a cross-site `fetch` with `Content-Type: application/json`; (c) `curl -X POST -d a=b` from a server with no `Origin`; (d) a `GET` that deletes data.

11. Why does the CSRF check not appear in `vite dev`, and what deployment-test do you therefore need?

12. In which order do the CSRF check and the `handle` hook run, and why does that matter for your `handle`-based logic?

13. A payment provider posts a form from `https://pay.example` to your `/webhooks/payment`. Configure the narrowest thing that makes it work, and explain why `'*'` is a bad idea. Would the same configuration allow `pay.example` to call a remote function?

14. After deploying behind an AWS load balancer that terminates TLS and forwards HTTP with the original `Host` removed, all form posts return “Cross-site POST form submissions are forbidden”. Give two fixes and the trust requirement for each.

15. Write a `handle` that sets `X-Content-Type-Options`, `Referrer-Policy` and HSTS only outside development. Why will this not affect a prerendered page, and where do you put its headers instead?

16. What are the risks of `Strict-Transport-Security` with `includeSubDomains; preload` on first deployment? How should the rollout be staged?

17. What happens with `redirect(302, '//evil.example')` in SvelteKit 3? With `redirect(302, 'https://evil.example', { external: true })`? With `redirect(302, 'javascript:alert(1)', { external: true })`? Why is it still wrong to pass `?next=` straight to `redirect`?

18. Why is `fetch(userUrl)` from a server `load` an SSRF risk even when the user is authenticated? List four controls in `fetchAllowed` and what each prevents.

19. DNS rebinding: why does “resolve the hostname, check it is not private, then fetch” fail? What is the robust variant?

20. Find the data exposure: `export const load = async ({ params }) => ({ post: await db.posts.findUnique({ where: { id: params.id } }), author: await db.users.findUnique({ where: { id: ... } }) });`. Name two things that leak and fix the code.

21. What does `filterSerializedResponseHeaders` control? What is the default, and what is leaked by the *body* of an inlined fetch regardless of headers?

22. Server-only modules stop `import { SECRET } from '#lib/server/secrets.js'` in a component. Give an example of a leak they do not stop.

23. `BODY_SIZE_LIMIT` on adapter-node: what is the default, does it apply to chunked bodies, and what does `Infinity` mean? Which design choice lets a single upload route coexist with a low global limit?

24. Why is the `limit` argument of `requested(query, limit)` required? What happens to arguments beyond it? Choose a limit for a table with a filter and sort UI and justify it.

25. A `query.batch` function loops over the client-supplied ids, issuing one SQL query per id. List two problems and the fix.

26. Design: you are given a SvelteKit app with a prerendered marketing site, an authenticated dashboard with remote functions, a public JSON API, and a CSP report endpoint. For each, state where its security headers and CSRF/CORS behaviour come from (platform, `handle`, SvelteKit config, or your code) and one DoS control.
