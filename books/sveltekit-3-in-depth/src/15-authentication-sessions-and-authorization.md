# Chapter 14: Authentication, Sessions, and Authorization

SvelteKit does not ship an authentication system. The official documentation page on auth is deliberately short: it contrasts session IDs with signed tokens, says that auth cookies can be checked in the `handle` hook with the user placed on `locals`, points to the Svelte CLI add-on for Better Auth (`sv add`), and refers to the Lucia guide for people who want to build their own. Everything else in this chapter is built from SvelteKit primitives the framework documents in other places: cookies, `handle`, `locals`, `getRequestEvent`, form actions, remote functions, `redirect` and CSRF protection.

That has a consequence for how you should read the chapter. The *mechanisms* (what `cookies.set` defaults to, how `handle` runs, what remote functions can and cannot do) are documented framework behaviour and are verified against the 3.1 sources. The *architecture* (session table layout, token hashing, rotation policy, rate limiting, OAuth flow structure) is **author practice**: sound, conventional and tested here, but not an official SvelteKit recommendation. Where that distinction matters, a callout says so. When in doubt, prefer a maintained library over hand-written crypto and protocol code; the examples below hand-roll the *glue*, and call out where a library should take over.

We cover sessions versus JWT, cookie design, session creation, validation, rotation and revocation in `handle`, why layout-only guards are broken and what to use instead, login and logout with both form actions and remote forms, password hashing, rate limiting and enumeration resistance, OAuth/OIDC in `+server` endpoints, authorization (including inside remote functions), and the CSRF/CORS interactions. Chapter 15 goes deeper into CSRF, CSP and headers; Chapter 9 covers `handle` and `sequence` mechanics.

## Sessions versus tokens

After credentials are verified, you must recognise the user on later requests. The two mainstream designs:

|  | Server-side session (opaque ID) | Signed token (JWT) |
|------------------------|------------------------|------------------------|
| Cookie contains | Random identifier | Claims plus signature |
| Verification | Look up in a datastore on each request | Verify signature and expiry; no lookup |
| Revocation | Immediate (delete the row) | Hard: wait for expiry or maintain a denylist (which is a datastore lookup again) |
| Latency / load | One datastore read per request (cacheable) | None |
| Size | Small | Grows with claims |
| Typical failure | Datastore outage = nobody can authenticate | Stolen token valid until expiry; stale claims (role changes) |

The SvelteKit documentation states exactly this trade-off: session IDs can be revoked immediately but need a query on each request; JWTs avoid the query but cannot be immediately revoked.

For first-party browser applications, **author practice** is server-side sessions: a revoked session (password change, “sign out everywhere”, compromised account) takes effect on the next request, claims never go stale, and the per-request lookup is cheap against a primary key. JWTs earn their place when a *separate service* must verify identity without calling back (service-to-service calls, mobile API tokens, third-party OIDC ID tokens that you verify and then convert into your own session). A common and sound hybrid: verify the upstream provider’s token once at login, then mint your own opaque session.

## Cookie design

Where does the session identifier live in a browser app? In a cookie that JavaScript cannot read. SvelteKit’s `cookies` API (on `RequestEvent`) has secure defaults, but you should know them rather than rely on them:

| Attribute | SvelteKit default (`cookies.set`) | Recommendation |
|------------------------|------------------------|------------------------|
| `httpOnly` | `true` | Keep `true`: script cannot read the session via XSS |
| `secure` | `true` (false during development on localhost) | Keep `true` in production |
| `path` | `'/'` (since 3.0; in 2.x it was required) | Pass it explicitly anyway, and use the same `path` in `set` and `delete`, so the code reads unambiguously |
| `sameSite` | `'lax'` | `'lax'` suits most apps; `'strict'` breaks arriving via links from other sites while logged in |
| `maxAge`/`expires` | none (session cookie) | Set an expiry that matches your session lifetime |

Use `__Host-` name prefix in production for extra browser-enforced guarantees: a cookie named `__Host-session` must be `Secure`, have `Path=/`, and have no `Domain`, so it cannot be set by a sibling subdomain. It requires HTTPS, which includes `localhost` in modern browsers but not plain HTTP dev servers over LAN IPs, so a common pattern is to use the prefix only when not in development.

The cookie value should be an unguessable random identifier of at least 128 bits (author practice: 24 random bytes, base64url) and nothing else: no user id, no role. You then store only a *hash* of it server-side. If your session table leaks, the hashes cannot be used as cookies.

> **Warning:** `sameSite: 'lax'` is not a CSRF defence by itself for `GET` requests with side effects, and it does not protect against attacks from *subdomains* (same-site but cross-origin). SvelteKit’s origin check (Chapter 15) is the primary CSRF protection for state-changing requests; do not make state changes on `GET`.

## Session creation, validation and rotation

The following module is the core of a typical session system. It is written against a minimal `db` interface (replace with your database client; the SQL is straightforward); every function is a plain async function with no SvelteKit imports except types, so it is trivial to unit test.

```ts
// src/lib/server/session.ts
import { createHash, randomBytes } from 'node:crypto';
import { db } from './db.js';

const DAY = 24 * 60 * 60 * 1000;
export const SESSION_LIFETIME = 30 * DAY;
const RENEW_WHEN_LESS_THAN = 15 * DAY; // sliding expiration

export interface SessionUser {
    id: string;
    email: string;
    role: 'user' | 'admin';
}

export interface Session {
    id: string; // sha256 of the cookie token
    userId: string;
    expiresAt: Date;
}

function hashToken(token: string): string {
    return createHash('sha256').update(token).digest('hex');
}

export function generateToken(): string {
    return randomBytes(24).toString('base64url');
}

export async function createSession(userId: string): Promise<{ token: string; session: Session }> {
    const token = generateToken();
    const session: Session = {
        id: hashToken(token),
        userId,
        expiresAt: new Date(Date.now() + SESSION_LIFETIME)
    };
    await db.sessions.insert(session);
    return { token, session };
}

export type ValidationResult =
    | { session: Session; user: SessionUser; refreshed: boolean }
    | { session: null; user: null; refreshed: false };

export async function validateSessionToken(token: string): Promise<ValidationResult> {
    const id = hashToken(token);
    const row = await db.sessions.findWithUser(id); // joins users; returns { session, user } | null

    if (!row) return { session: null, user: null, refreshed: false };

    const { session, user } = row;
    const now = Date.now();

    if (session.expiresAt.getTime() <= now) {
        await db.sessions.delete(id);
        return { session: null, user: null, refreshed: false };
    }

    let refreshed = false;
    if (session.expiresAt.getTime() - now < RENEW_WHEN_LESS_THAN) {
        session.expiresAt = new Date(now + SESSION_LIFETIME);
        await db.sessions.updateExpiry(id, session.expiresAt);
        refreshed = true;
    }

    return { session, user, refreshed };
}

export async function invalidateSession(sessionId: string): Promise<void> {
    await db.sessions.delete(sessionId);
}

/** Call on password change, role change, or "sign out everywhere". */
export async function invalidateAllSessions(userId: string): Promise<void> {
    await db.sessions.deleteForUser(userId);
}
```

Design points (all author practice):

- **Hash the token at rest.** The cookie holds the token; the database holds `sha256(token)`. SHA-256 is appropriate here (not a password hash) because the token is high-entropy random data, so there is nothing to brute-force.
- **Rotate on privilege change.** Always create a *new* session at login (never reuse an anonymous session ID: this is the session-fixation defence) and invalidate others when the password changes.
- **Sliding expiry with a throttle.** Writing on every request is wasteful. Renew only when less than half the lifetime remains, as above.
- **Absolute lifetime.** If your threat model demands it, add a hard cap (`createdAt + 90 days`) so that a stolen cookie cannot be kept alive forever by renewal.
- **Cache with care.** If the lookup becomes a bottleneck, cache `validateSessionToken` results for seconds, not minutes, and clear the cache entry on invalidation.

The cookie helpers keep cookie handling in one place, with explicit attributes:

```ts
// src/lib/server/session-cookie.ts
import type { Cookies } from '@sveltejs/kit';
import { dev } from '$app/env';

const NAME = dev ? 'session' : '__Host-session';

export function setSessionCookie(cookies: Cookies, token: string, expiresAt: Date) {
    cookies.set(NAME, token, {
        path: '/',
        httpOnly: true,
        secure: !dev,
        sameSite: 'lax',
        expires: expiresAt
    });
}

export function deleteSessionCookie(cookies: Cookies) {
    cookies.delete(NAME, { path: '/' });
}

export function readSessionCookie(cookies: Cookies): string | undefined {
    return cookies.get(NAME);
}
```

## Validating in `handle`

`handle` runs for every dynamic request: page documents, data requests (`__data.json`), actions, `+server` endpoints and remote function calls. It does **not** run for static assets or already-prerendered pages. It is the single place where a session cookie is turned into `event.locals`.

```ts
// src/app.d.ts
import type { Session, SessionUser } from '#lib/server/session.js';

declare global {
    namespace App {
        interface Locals {
            user: SessionUser | null;
            session: Session | null;
        }
    }
}

export {};
```

```ts
// src/hooks.server.ts
import type { Handle } from '@sveltejs/kit/hooks';
import { sequence } from '@sveltejs/kit/hooks';
import { validateSessionToken } from '#lib/server/session.js';
import {
    deleteSessionCookie,
    readSessionCookie,
    setSessionCookie
} from '#lib/server/session-cookie.js';

const authenticate: Handle = async ({ event, resolve }) => {
    const token = readSessionCookie(event.cookies);

    if (!token) {
        event.locals.user = null;
        event.locals.session = null;
        return resolve(event);
    }

    const { session, user, refreshed } = await validateSessionToken(token);

    if (session) {
        event.locals.user = user;
        event.locals.session = session;
        if (refreshed) setSessionCookie(event.cookies, token, session.expiresAt);
    } else {
        event.locals.user = null;
        event.locals.session = null;
        deleteSessionCookie(event.cookies);
    }

    return resolve(event);
};

export const handle = sequence(authenticate /*, other handles */);
```

Remember the types import from `@sveltejs/kit/hooks` in SvelteKit 3 (`Handle`, `HandleServerError`, `sequence`…), not from `@sveltejs/kit`.

Three subtleties:

1.  **Static and prerendered requests bypass `handle`.** A prerendered page is served as a file by the platform before SvelteKit sees the request. Never put anything that requires authentication in a prerendered page: it is public by construction (Chapter 11).
2.  **Form actions do not rerun `handle` after they execute.** If an action logs the user in or out, it must update `event.locals` itself, or the `load` functions that rerun after the action in the same request will see stale `locals`.
3.  **`handle` performs a datastore lookup for every dynamic request, including requests that do not need a user.** If this matters, only read the cookie and look up the session lazily: define `locals.getUser()` as a memoised function instead of eagerly populating `locals.user`. The eager form is simpler and is the right default for most applications.

## Guarding: why layout-only guards fail

A common first attempt: put the check in a layout load, assuming that everything below is therefore protected.

```ts
// src/routes/(app)/+layout.server.ts   <- NOT SUFFICIENT ON ITS OWN
import { redirect } from '@sveltejs/kit';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ locals }) => {
    if (!locals.user) redirect(303, '/login');
    return { user: locals.user };
};
```

This is documented as an anti-pattern: layout `load` functions do not necessarily rerun on every navigation (a layout is reused when navigating between its child pages and its dependencies have not changed), and layout and page `load` functions run **in parallel**, not sequentially. A page `load` below the layout can therefore execute and fetch protected data before the layout’s redirect takes effect, and on later client-side navigations between child pages the layout check may not run at all. In addition, the layout check does not protect `+server.ts` endpoints, form actions, or remote functions: none of them go through the layout.

The framework documentation’s advice is to guard in `handle` or in each `+page.server` `load`. Combine two layers:

**Layer 1: coarse route guard in `handle`.** Cheap and centralised; rejects whole URL prefixes before any `load` runs.

```ts
// src/hooks.server.ts (continued)
const PROTECTED_PREFIXES = ['/app', '/admin', '/account'];

const guard: Handle = async ({ event, resolve }) => {
    const { pathname } = event.url;
    const needsAuth = PROTECTED_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + '/'));

    if (needsAuth && !event.locals.user) {
        const next = encodeURIComponent(pathname + event.url.search);
        return new Response(null, { status: 303, headers: { location: `/login?next=${next}` } });
    }

    if (pathname.startsWith('/admin') && event.locals.user?.role !== 'admin') {
        return new Response('Forbidden', { status: 403 });
    }

    return resolve(event);
};

export const handle = sequence(authenticate, guard);
```

**Layer 2: authorization where data is touched.** Each server `load`, action, endpoint and remote function asserts what *it* needs. A helper makes this one line:

```ts
// src/lib/server/auth.ts
import { error, redirect } from '@sveltejs/kit';
import { getRequestEvent } from '$app/server';
import type { SessionUser } from './session.js';

export function requireUser(): SessionUser {
    const event = getRequestEvent();
    const { user } = event.locals;

    if (user) return user;

    // Remote functions (especially `command`) cannot redirect; a client-side handler
    // decides what to do with a 401.
    if (event.isRemoteRequest) error(401, 'Sign in required');

    const next = encodeURIComponent(event.url.pathname + event.url.search);
    redirect(303, `/login?next=${next}`);
}

export function requireRole(role: SessionUser['role']): SessionUser {
    const user = requireUser();
    if (user.role !== role) error(403, 'Forbidden');
    return user;
}
```

`getRequestEvent()` (from `$app/server`) returns the current `RequestEvent` anywhere in `handle`, `load`, actions, `+server` handlers and remote functions, so `requireUser()` needs no parameters and cannot be called with the wrong event. It throws outside a request.

> **Warning:** In the redirect branch above, `event.url` is trustworthy in `load` and actions (it is the URL actually requested). It is *not* trustworthy inside `form` and `command` remote functions, where `url`, `params` and `route` describe the page that the *client claims* to be calling from. That is why the remote branch above uses `error(401)` and does not build a redirect from `event.url`.

Use it in a page load:

```ts
// src/routes/(app)/projects/+page.server.ts
import type { PageServerLoad } from './$types';
import { requireUser } from '#lib/server/auth.js';
import { listProjects } from '#lib/server/projects.js';

export const load: PageServerLoad = async () => {
    const user = requireUser();
    return { projects: await listProjects(user.id) };
};
```

Layer 1 is a convenience and a safety net; layer 2 is the control. If you only have time for one, have layer 2.

### The remote-function blind spot

The path-prefix guard in `handle` does not cover remote functions, for a reason worth pausing on. Remote function calls go through `handle`, but what `event.url` contains depends on the kind of call:

- For **queries**, `handle` sees the URL of the internal remote endpoint (under `/_app/remote/...`), not of your page. A `startsWith('/app')` check never matches.
- For **forms and commands**, `url`, `params` and `route` reflect the page the *client reports*, taken from request headers. An attacker can claim to be calling from `/public`.

Therefore **authorize inside every remote function** using `requireUser()`/`requireRole()` and checks against `locals`, never against the URL. Remote functions require two experimental flags (Chapter 7): `experimental: { remoteFunctions: true }` in `sveltekit({...})` and `compilerOptions: { experimental: { async: true } }`.

```ts
// src/routes/(app)/projects/projects.remote.ts
import * as v from 'valibot';
import { error } from '@sveltejs/kit';
import { query, command } from '$app/server';
import { requireUser } from '#lib/server/auth.js';
import { getProject, deleteProject } from '#lib/server/projects.js';

export const getMyProject = query(v.string(), async (id) => {
    const user = requireUser();
    const project = await getProject(id);
    // authorization on the resource, not just on "being logged in"
    if (!project || project.ownerId !== user.id) error(404, 'Not found');
    return project;
});

export const removeProject = command(v.string(), async (id) => {
    const user = requireUser();
    const project = await getProject(id);
    if (!project || project.ownerId !== user.id) error(404, 'Not found');
    await deleteProject(id);
});
```

Two details: returning `404` rather than `403` for resources the user may not see avoids confirming that the id exists, and ownership is compared against `locals.user.id`, a value derived from the cookie, never against a client-supplied user id.

## Login and logout with form actions

Form actions are the traditional route and work without JavaScript. A login action must: validate input, find the user, verify the password in constant-ish time even if the user does not exist, create a *new* session, set the cookie, update `locals`, and redirect.

```ts
// src/routes/login/+page.server.ts
import { fail, redirect } from '@sveltejs/kit';
import type { Actions, PageServerLoad } from './$types';
import { verifyPassword } from '#lib/server/password.js';
import { createSession } from '#lib/server/session.js';
import { setSessionCookie } from '#lib/server/session-cookie.js';
import { findUserByEmail } from '#lib/server/users.js';
import { loginLimiter } from '#lib/server/rate-limit.js';
import { safeRedirectTarget } from '#lib/server/redirect.js';

export const load: PageServerLoad = ({ locals, url }) => {
    if (locals.user) redirect(303, safeRedirectTarget(url.searchParams.get('next')));
    return {};
};

export const actions: Actions = {
    default: async (event) => {
        const { request, cookies, locals, url, getClientAddress } = event;
        const form = await request.formData();
        const email = String(form.get('email') ?? '').trim().toLowerCase();
        const password = String(form.get('password') ?? '');

        if (!email || !password || email.length > 254 || password.length > 1024) {
            return fail(400, { email, message: 'Enter your email and password.' });
        }

        const ip = getClientAddress();
        if (!loginLimiter.consume(`${ip}:${email}`) || !loginLimiter.consume(`ip:${ip}`)) {
            return fail(429, { email, message: 'Too many attempts. Try again later.' });
        }

        const user = await findUserByEmail(email);
        // verifyPassword runs the full hash even when `user` is undefined (see below)
        const ok = await verifyPassword(password, user?.passwordHash);

        if (!user || !ok) {
            // identical message and status whether the email exists or not
            return fail(400, { email, message: 'Incorrect email or password.' });
        }

        const { token, session } = await createSession(user.id);
        setSessionCookie(cookies, token, session.expiresAt);

        // actions don't rerun `handle`: keep locals consistent for anything that runs later
        locals.user = { id: user.id, email: user.email, role: user.role };
        locals.session = session;

        redirect(303, safeRedirectTarget(url.searchParams.get('next')));
    }
};
```

```html
<!-- src/routes/login/+page.svelte -->
<script lang="ts">
    import { enhance } from '$app/forms';
    import type { PageProps } from './$types';

    let { form }: PageProps = $props();
</script>

<form method="POST" use:enhance>
    <label>Email <input name="email" type="email" autocomplete="username" value={form?.email ?? ''} required /></label>
    <label>Password <input name="password" type="password" autocomplete="current-password" required /></label>
    {#if form?.message}<p role="alert">{form.message}</p>{/if}
    <button>Sign in</button>
</form>
```

In SvelteKit 3, `use:enhance` responds with the fail status code and, for redirects to another page, navigates to the location; the 303 above works for both enhanced and non-enhanced submissions (Chapter 6).

Logout is a `POST` (never a `GET` link: a cross-site `<img src="/logout">` would sign users out):

```ts
// src/routes/logout/+page.server.ts  (or any route with an action)
import { redirect } from '@sveltejs/kit';
import type { Actions } from './$types';
import { invalidateSession } from '#lib/server/session.js';
import { deleteSessionCookie } from '#lib/server/session-cookie.js';

export const actions: Actions = {
    default: async ({ locals, cookies }) => {
        if (locals.session) await invalidateSession(locals.session.id);
        deleteSessionCookie(cookies);
        locals.user = null;
        locals.session = null;
        redirect(303, '/');
    }
};
```

```html
<form method="POST" action="/logout"><button>Sign out</button></form>
```

### Open-redirect-safe `next` parameters

The `?next=` pattern is an open-redirect vector. SvelteKit 3’s `redirect()` already refuses external locations unless you pass `{ external: true }` or an allow-list, and refuses `javascript:`/`data:` even with `external: true`; that turns a would-be open redirect into a 500 error rather than a silent bounce to an attacker site. Do not rely on a 500 as validation. Normalise yourself:

```ts
// src/lib/server/redirect.ts
export function safeRedirectTarget(next: string | null, fallback = '/app'): string {
    if (!next) return fallback;
    // must be a same-site absolute path: starts with one "/", not "//" or "/\"
    if (!next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) return fallback;
    try {
        const url = new URL(next, 'http://internal.invalid');
        if (url.origin !== 'http://internal.invalid') return fallback;
        return url.pathname + url.search + url.hash;
    } catch {
        return fallback;
    }
}
```

## Login with remote forms

With remote functions (experimental), a login form is a `form` function. The same security properties apply; the differences are the validation API, how to signal a failed login, and that cookies may be written in `form` (and `command`) but headers may not be set.

```ts
// src/routes/login/login.remote.ts
import * as v from 'valibot';
import { invalid, redirect } from '@sveltejs/kit';
import { form, getRequestEvent } from '$app/server';
import { verifyPassword } from '#lib/server/password.js';
import { createSession } from '#lib/server/session.js';
import { setSessionCookie } from '#lib/server/session-cookie.js';
import { findUserByEmail } from '#lib/server/users.js';
import { loginLimiter } from '#lib/server/rate-limit.js';

export const login = form(
    v.object({
        email: v.pipe(v.string(), v.trim(), v.toLowerCase(), v.email(), v.maxLength(254)),
        _password: v.pipe(v.string(), v.minLength(1), v.maxLength(1024))
    }),
    async ({ email, _password }) => {
        const { cookies, locals, getClientAddress } = getRequestEvent();

        if (!loginLimiter.consume(`${getClientAddress()}:${email}`)) {
            invalid('Too many attempts. Try again later.');
        }

        const user = await findUserByEmail(email);
        const ok = await verifyPassword(_password, user?.passwordHash);
        if (!user || !ok) invalid('Incorrect email or password.');

        const { token, session } = await createSession(user.id);
        setSessionCookie(cookies, token, session.expiresAt);
        locals.user = { id: user.id, email: user.email, role: user.role };
        locals.session = session;

        redirect(303, '/app');
    }
);
```

```html
<!-- src/routes/login/+page.svelte -->
<script lang="ts">
    import { login } from './login.remote.js';
</script>

<form {...login}>
    <label>Email <input {...login.fields.email.as('email')} autocomplete="username" /></label>
    <label>Password <input {...login.fields._password.as('password')} autocomplete="current-password" /></label>

    {#each login.fields.allIssues() ?? [] as issue}
        <p role="alert">{issue.message}</p>
    {/each}

    <button>Sign in</button>
</form>
```

Notes: the `_password` name prefix tells SvelteKit never to echo the value back after a failed submission, which matters for credentials; `invalid('message')` throws a form-level issue; `redirect` is allowed in `form` and `query` but **not** in `command`; and the redirect target here is a constant (if you want a `next` parameter, derive it from a hidden field you validate with `safeRedirectTarget`, *not* from `getRequestEvent().url`).

### Logout as a command or a form

Prefer a `form` (progressive enhancement) for logout. A `command` also works for an SPA button, but cannot redirect, so the client navigates after it resolves:

```ts
// src/lib/auth.remote.ts
import { command, form, getRequestEvent } from '$app/server';
import { redirect } from '@sveltejs/kit';
import { invalidateSession } from '#lib/server/session.js';
import { deleteSessionCookie } from '#lib/server/session-cookie.js';

export const logout = form(async () => {
    const { locals, cookies } = getRequestEvent();
    if (locals.session) await invalidateSession(locals.session.id);
    deleteSessionCookie(cookies);
    locals.user = null;
    locals.session = null;
    redirect(303, '/');
});

// SPA variant: no redirect allowed, so the caller navigates afterwards
export const signOut = command(async () => {
    const { locals, cookies } = getRequestEvent();
    if (locals.session) await invalidateSession(locals.session.id);
    deleteSessionCookie(cookies);
    locals.user = null;
    locals.session = null;
});
```

(A `form` with no schema takes no fields.) Use the form as `<form {...logout}><button>Sign out</button></form>`; call the command from a button handler with `await signOut(); await goto('/');` (`goto` from `$app/navigation`), so the navigation reruns the loads with the cookie already gone.

## Passwords: hashing, rate limiting, enumeration

> **Author practice.** None of this section is documented SvelteKit behaviour. It is general guidance for the credentials path of a self-hosted auth system. If you can use an identity provider (OIDC, Better Auth, Entra External ID, Auth0, etc.) and avoid storing passwords at all, that is generally the better engineering decision.

### Hashing

Use a memory-hard password hashing function with a per-password random salt: Argon2id is the current recommendation; scrypt and bcrypt are acceptable. Node’s built-in `crypto.scrypt` needs no dependency, which makes it a good illustration (use `@node-rs/argon2` or similar if you want Argon2id; the shape of the code is identical):

```ts
// src/lib/server/password.ts
import { randomBytes, scrypt, timingSafeEqual } from 'node:crypto';
import { promisify } from 'node:util';

const scryptAsync = promisify(scrypt) as (
    password: string,
    salt: Buffer,
    keylen: number,
    options: { N: number; r: number; p: number; maxmem: number }
) => Promise<Buffer>;

const N = 2 ** 15; // tune so that one hash takes roughly 50-100 ms on your hardware
const R = 8;
const P = 1;
const KEYLEN = 64;
const maxmem = 128 * N * R * 2;

export async function hashPassword(password: string): Promise<string> {
    const salt = randomBytes(16);
    const key = await scryptAsync(password.normalize('NFKC'), salt, KEYLEN, { N, r: R, p: P, maxmem });
    return `scrypt$${N}$${R}$${P}$${salt.toString('base64url')}$${key.toString('base64url')}`;
}

// A fixed, valid-looking hash used when the user does not exist, so that the
// "unknown user" path costs the same as the "wrong password" path.
const DUMMY_HASH = await hashPassword('dummy-password-for-timing-equalisation');

export async function verifyPassword(password: string, stored: string | undefined): Promise<boolean> {
    const hash = stored ?? DUMMY_HASH;
    const [alg, n, r, p, salt, key] = hash.split('$');
    if (alg !== 'scrypt') return false;

    const expected = Buffer.from(key, 'base64url');
    const actual = await scryptAsync(password.normalize('NFKC'), Buffer.from(salt, 'base64url'), expected.length, {
        N: Number(n),
        r: Number(r),
        p: Number(p),
        maxmem: 128 * Number(n) * Number(r) * 2
    });

    // always compare, but a missing user can never succeed
    return timingSafeEqual(actual, expected) && stored !== undefined;
}
```

Practical notes: store the parameters inside the hash string so that you can raise the cost later and re-hash on successful login; cap the password length (a 10 MB password is a denial-of-service request, not a password); normalise Unicode consistently; check new passwords against a breach corpus (k-anonymity range APIs exist) rather than imposing composition rules; and keep the hash function off the hot path of unauthenticated endpoints without rate limiting, since each call burns tens of milliseconds of CPU and tens of megabytes of memory.

### Rate limiting

Throttle credential endpoints by *both* client address and account identifier: per-IP alone is bypassed by botnets; per-account alone lets an attacker lock a victim out. A minimal in-process token bucket illustrates the logic; in production with more than one instance you need a shared store (Redis or your database), because an in-memory limiter is per process.

```ts
// src/lib/server/rate-limit.ts
export class TokenBucket {
    #buckets = new Map<string, { tokens: number; updated: number }>();

    constructor(
        private capacity: number,
        private refillPerSecond: number,
        private maxKeys = 50_000
    ) {}

    consume(key: string, cost = 1): boolean {
        const now = Date.now();
        let b = this.#buckets.get(key);

        if (!b) {
            if (this.#buckets.size >= this.maxKeys) this.#buckets.delete(this.#buckets.keys().next().value!);
            b = { tokens: this.capacity, updated: now };
        }

        b.tokens = Math.min(this.capacity, b.tokens + ((now - b.updated) / 1000) * this.refillPerSecond);
        b.updated = now;

        const allowed = b.tokens >= cost;
        if (allowed) b.tokens -= cost;

        this.#buckets.delete(key); // re-insert to keep Map in least-recently-used order
        this.#buckets.set(key, b);
        return allowed;
    }
}

// 5 attempts, refilling one every 12 seconds
export const loginLimiter = new TokenBucket(5, 1 / 12);
```

Two operational notes that are specific to SvelteKit. `getClientAddress()` reads the connecting peer address by default; behind a load balancer that is the *proxy’s* address, so every user would share one bucket. With `adapter-node` set `ADDRESS_HEADER` (and `XFF_DEPTH` for `X-Forwarded-For`) to the trusted header (Chapter 18). Do that only when a trusted proxy overwrites the header, otherwise clients can spoof their address. And the limiter above is *module-level state* in the server process, deliberately: it holds no per-user *data*, only counters (Chapter 12 explains why that is a different category from leaking user data).

### Enumeration resistance

An attacker who can distinguish “no such account” from “wrong password” can harvest your user list. The examples above avoid the main leaks:

- the same message and status for unknown user and wrong password;
- the same *work* in both paths (`verifyPassword` hashes against a dummy when the user is absent), so response time does not reveal existence;
- rate limiting that applies equally to existing and non-existing identifiers.

Registration and password reset leak existence too (“that email is already registered”). The usual pattern is to respond identically (“If that address is registered, we have sent an email”) and do the account-specific work asynchronously. Be consistent about timing there as well.

## OAuth and OIDC in `+server` endpoints

Delegating authentication to an identity provider removes passwords from your system. The authorization-code flow with PKCE needs two endpoints: one that starts the flow and one that handles the callback. Both are plain `+server.ts` files; they are GET handlers because the browser is *navigating* to them.

> **Author practice.** The structure below (state, PKCE verifier in short-lived cookies; code exchange; mapping to a local user; minting your own session) is the standard OAuth 2.0 / OIDC web-app pattern. In production use a maintained client library for token validation (signature verification, `iss`, `aud`, `exp`, nonce) rather than hand-rolling it; the example uses the provider’s **userinfo endpoint** to avoid parsing ID tokens manually, which is acceptable when the userinfo call is made over TLS with the access token you just obtained.

```ts
// src/lib/server/oidc.ts
import { createHash, randomBytes } from 'node:crypto';
import { OIDC_AUTHORIZE_URL, OIDC_TOKEN_URL, OIDC_USERINFO_URL, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET } from '$app/env/private';

export function randomString(bytes = 32) {
    return randomBytes(bytes).toString('base64url');
}

export function pkceChallenge(verifier: string) {
    return createHash('sha256').update(verifier).digest('base64url');
}

export function authorizeUrl(redirectUri: string, state: string, challenge: string) {
    const u = new URL(OIDC_AUTHORIZE_URL);
    u.search = new URLSearchParams({
        response_type: 'code',
        client_id: OIDC_CLIENT_ID,
        redirect_uri: redirectUri,
        scope: 'openid email profile',
        state,
        code_challenge: challenge,
        code_challenge_method: 'S256'
    }).toString();
    return u;
}

export async function exchangeCode(code: string, redirectUri: string, verifier: string) {
    const res = await fetch(OIDC_TOKEN_URL, {
        method: 'POST',
        headers: { 'content-type': 'application/x-www-form-urlencoded', accept: 'application/json' },
        body: new URLSearchParams({
            grant_type: 'authorization_code',
            code,
            redirect_uri: redirectUri,
            client_id: OIDC_CLIENT_ID,
            client_secret: OIDC_CLIENT_SECRET,
            code_verifier: verifier
        })
    });
    if (!res.ok) throw new Error(`token endpoint returned ${res.status}`);
    return (await res.json()) as { access_token: string };
}

export async function fetchUserinfo(accessToken: string) {
    const res = await fetch(OIDC_USERINFO_URL, { headers: { authorization: `Bearer ${accessToken}` } });
    if (!res.ok) throw new Error(`userinfo returned ${res.status}`);
    return (await res.json()) as { sub: string; email?: string; email_verified?: boolean; name?: string };
}
```

The endpoint that starts the flow stores `state` and the PKCE verifier in short-lived, `httpOnly` cookies:

```ts
// src/routes/auth/login/+server.ts
import { redirect } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { authorizeUrl, pkceChallenge, randomString } from '#lib/server/oidc.js';
import { safeRedirectTarget } from '#lib/server/redirect.js';

export const GET: RequestHandler = ({ url, cookies }) => {
    const state = randomString();
    const verifier = randomString(48);
    const opts = { path: '/auth', httpOnly: true, sameSite: 'lax', maxAge: 600 } as const;

    cookies.set('oidc_state', state, opts);
    cookies.set('oidc_verifier', verifier, opts);
    cookies.set('oidc_next', safeRedirectTarget(url.searchParams.get('next')), opts);

    const redirectUri = new URL('/auth/callback', url.origin).toString();
    // the provider is an external origin, so redirect() must be told so explicitly (SvelteKit 3)
    redirect(302, authorizeUrl(redirectUri, state, pkceChallenge(verifier)), { external: true });
};
```

Note `sameSite: 'lax'` is **required** here, not just a preference: the callback is a top-level cross-site navigation from the provider back to you, and `strict` cookies would not be sent. Passing `{ external: true }` (or better, an allow-list such as `{ external: ['https://login.example.com'] }`) is required in SvelteKit 3 for redirects away from your origin.

The callback verifies `state`, exchanges the code, maps the identity to a local user and creates the session:

```ts
// src/routes/auth/callback/+server.ts
import { error, redirect } from '@sveltejs/kit';
import { timingSafeEqual } from 'node:crypto';
import type { RequestHandler } from './$types';
import { exchangeCode, fetchUserinfo } from '#lib/server/oidc.js';
import { createSession } from '#lib/server/session.js';
import { setSessionCookie } from '#lib/server/session-cookie.js';
import { findOrCreateUserFromIdentity } from '#lib/server/users.js';

function safeEqual(a: string, b: string) {
    const x = Buffer.from(a);
    const y = Buffer.from(b);
    return x.length === y.length && timingSafeEqual(x, y);
}

export const GET: RequestHandler = async ({ url, cookies, locals }) => {
    const state = cookies.get('oidc_state');
    const verifier = cookies.get('oidc_verifier');
    const next = cookies.get('oidc_next') ?? '/app';
    const code = url.searchParams.get('code');
    const returnedState = url.searchParams.get('state');

    // single use: clear regardless of outcome
    for (const name of ['oidc_state', 'oidc_verifier', 'oidc_next']) cookies.delete(name, { path: '/auth' });

    if (url.searchParams.has('error')) error(400, 'Sign-in was cancelled or failed');
    if (!state || !verifier || !code || !returnedState || !safeEqual(state, returnedState)) {
        error(400, 'Invalid sign-in response');
    }

    const redirectUri = new URL('/auth/callback', url.origin).toString();
    const { access_token } = await exchangeCode(code, redirectUri, verifier);
    const profile = await fetchUserinfo(access_token);

    if (!profile.email || profile.email_verified === false) error(403, 'A verified email is required');

    // key identities by (provider, sub), NOT by email, to avoid account takeover via email reuse
    const user = await findOrCreateUserFromIdentity({ provider: 'oidc', subject: profile.sub, email: profile.email, name: profile.name });

    const { token, session } = await createSession(user.id); // new session: fixation defence
    setSessionCookie(cookies, token, session.expiresAt);
    locals.user = { id: user.id, email: user.email, role: user.role };
    locals.session = session;

    redirect(303, next);
};
```

Points that routinely go wrong:

- **`url.origin` behind a proxy.** The redirect URI you send must match, byte for byte, what is registered at the provider. If `url.origin` is wrong because the proxy does not forward the host header, set `paths.origin` (3.0+) or `HOST_HEADER`/`PROTOCOL_HEADER` for adapter-node, and build the redirect URI from your configured origin rather than the request.
- **Account linking by email.** Matching an incoming identity to an existing account by email alone lets an attacker who controls an unverified email at some provider take over the account. Key on `(provider, subject)`, require `email_verified`, and require an authenticated confirmation step before linking.
- **No session reuse.** Always mint a new session at the callback.
- **The callback is a GET with side effects**, which is inherent to OAuth; its protection is `state` and PKCE, not the origin check, since the CSRF check applies to form-style *mutating* methods and this is a `GET`.

If you use an enterprise identity product (Entra External ID, Auth0, Keycloak), the endpoints and claim names differ but the structure is the same.

### Better Auth

The Svelte CLI can scaffold Better Auth, either for a new project or for an existing one: `npx sv add better-auth`. The official auth page recommends it as the library route. What you get is generated code in your repository (a server-side auth instance, an endpoint that handles `/api/auth/*`, a client helper, and a hook integration that populates `locals`), so you can read and change it. I will not reproduce its generated code here, because it evolves with the add-on and the library; treat the CLI’s output as the source of truth. Three review points when you adopt any auth library in SvelteKit 3:

1.  **Where does it read the session?** It should populate `event.locals` in `handle`, exactly as in this chapter; confirm that it uses `sequence` rather than replacing your `handle`.
2.  **Does it need `csrf.trustedOrigins`?** Only if cross-origin form-style POSTs are expected (some provider callbacks use POST). Add the specific origin, never `'*'`.
3.  **Secrets in `src/env.ts`.** The library’s secret and provider credentials should be declared as private dynamic variables with validators (Chapter 13).

## Authorization

Authentication answers “who is this?”; authorization answers “may they do this to *that*?”. Two levels are needed.

**Coarse (role) checks** gate features: `requireRole('admin')`. These belong in the coarse guard and in server entry points.

**Fine-grained (resource) checks** are where real vulnerabilities live: an authenticated user fetching `/projects/123` for a project they do not own (an *insecure direct object reference*, IDOR). The fix is structural: **scope every query by the authenticated principal** rather than fetching by id and checking afterwards.

```ts
// src/lib/server/projects.ts
export async function getProjectForUser(userId: string, projectId: string) {
    // the WHERE clause includes the owner (or a membership join), so a foreign id returns nothing
    return db.projects.findFirst({ where: { id: projectId, members: { some: { userId } } } });
}
```

```ts
// src/routes/(app)/projects/[id]/+page.server.ts
import { error } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';
import { requireUser } from '#lib/server/auth.js';
import { getProjectForUser } from '#lib/server/projects.js';

export const load: PageServerLoad = async ({ params }) => {
    const user = requireUser();
    const project = await getProjectForUser(user.id, params.id);
    if (!project) error(404, 'Not found');
    return { project };
};
```

For richer models (roles per organisation, permissions), centralise policy in one module with functions such as `can(user, 'project:delete', project)` and call it from loads, actions, endpoints and remote functions alike. A policy function that every entry point calls is far easier to audit than checks scattered across routes. Remember that **a UI that hides a button is not authorization**; every mutation entry point must enforce the policy independently.

### Authorization in remote functions, summarised

- Every `query`, `form` and `command` is a public HTTP endpoint. Treat each as an API route.
- Call `requireUser()`/policy checks inside the function body; they have `locals` available through `getRequestEvent()`.
- Do not use `url`, `params` or `route` for authorization: for `form`/`command` they describe the caller’s claimed page, and in `query` they are not accessible at all (accessing them throws in 3.0).
- Validate arguments with a Standard Schema. The `'unchecked'` escape hatch is for cases where you validate yourself; never combine it with authorization based on client-supplied identifiers.
- Cookies can be written in `form` and `command`; you cannot set response headers.

## CSRF and CORS around auth

SvelteKit’s CSRF protection is on in production: form-style submissions (`POST`/`PUT`/`PATCH`/`DELETE` with `application/x-www-form-urlencoded`, `multipart/form-data`, `text/plain` or no content type) whose `Origin` header does not match the app’s origin are rejected with 403, and remote-function calls other than `GET` are rejected when the `Origin` does not match. Together with `sameSite: 'lax'` cookies, this covers the standard cross-site forgery cases for your actions, form posts to `+server.ts` and remote functions (details and limits in Chapter 15).

Auth-specific consequences:

- **Behind a proxy**, a wrong self-origin makes *every* login post fail with “Cross-site POST form submissions are forbidden”. Fix the origin (`paths.origin`, or the trusted forwarding headers), not the check. The check is skipped in development, so this failure appears only in production.
- **`csrf.trustedOrigins`** allows listed origins to make cross-origin form-style submissions to your non-remote endpoints (a payment gateway posting back, an identity provider using `response_mode=form_post`). It does *not* apply to remote function calls, which are always same-origin-only. Prefer exact origins over `'*'`.
- **JSON APIs called from another origin** (a mobile app, a separate SPA) are not form-style requests, so the origin check does not apply to `application/json` requests; those are governed by CORS. Browsers send a preflight for non-simple requests, and *you* implement the response (`OPTIONS` handler plus `Access-Control-*` headers) in `+server.ts` or `handle`. Never reflect arbitrary `Origin` values together with `Access-Control-Allow-Credentials: true`. For token-authenticated APIs (bearer tokens in `Authorization`, no cookies), CSRF is not a concern, and a permissive CORS policy is safe; for cookie-authenticated endpoints it is not.

```ts
// src/routes/api/[...path]/+server.ts (excerpt) -- allow one known origin, with cookies
const ALLOWED = new Set(['https://app.example.com']);

export const OPTIONS: RequestHandler = ({ request }) => {
    const origin = request.headers.get('origin') ?? '';
    const headers = new Headers({ vary: 'Origin' });
    if (ALLOWED.has(origin)) {
        headers.set('access-control-allow-origin', origin);
        headers.set('access-control-allow-credentials', 'true');
        headers.set('access-control-allow-methods', 'GET,POST,PUT,PATCH,DELETE');
        headers.set('access-control-allow-headers', 'content-type,authorization');
        headers.set('access-control-max-age', '600');
    }
    return new Response(null, { status: 204, headers });
};
```

## Testing the auth path

Auth bugs are logic bugs, and logic is easy to test if you kept it out of SvelteKit-specific code. The session module and password module above have no framework imports; unit-test them directly (expiry, renewal, invalidation, timing-equalised unknown-user path). For the integration layer, call `handle` with constructed `Request` objects, or run Playwright against `vite preview` and assert: unauthenticated access to protected URLs redirects; a user cannot read another user’s resource through the page, the endpoint *and* the remote function; logout invalidates the session server-side (replay the old cookie and expect 401/redirect). Chapter 19 covers the testing setup.

## Key takeaways

- SvelteKit gives you the primitives (cookies, `handle`, `locals`, `getRequestEvent`, `redirect`, CSRF protection) but no auth system; the official page is minimal. Architecture advice in this chapter is author practice, clearly separate from framework behaviour.
- Prefer opaque server-side sessions for first-party apps (immediate revocation, no stale claims); use JWTs when a separate service must verify identity without a lookup. Store only a hash of the session token.
- Cookie attributes: `httpOnly`, `secure`, an explicit `path`, `sameSite: 'lax'`, and an expiry. SvelteKit defaults to `httpOnly`, `secure` (off on localhost in dev) and `sameSite: 'lax'`. Consider the `__Host-` prefix in production.
- Validate the session in `handle` and set `locals.user`/`locals.session`. Actions do not rerun `handle`, so update `locals` yourself after login/logout. Prerendered and static responses bypass `handle`.
- Never rely on a layout `load` for access control: it may not rerun and runs in parallel with page loads. Use a coarse guard in `handle` plus per-entry-point checks (`requireUser()` built on `getRequestEvent()`).
- A path-prefix guard in `handle` does not protect remote functions: query requests carry the remote endpoint URL and `form`/`command` carry a client-reported page URL. Authorize inside every remote function against `locals`; return 404 for foreign resources; use `error(401)` rather than redirect in commands.
- Create a new session at every login (fixation defence), invalidate on password change, log out via POST, and validate `next` parameters before redirecting. SvelteKit 3’s `redirect()` rejects external targets unless allowed, but that is a backstop, not validation.
- Hash passwords with a memory-hard function, equalise the unknown-user path, throttle by IP and by account (with a shared store in multi-instance deployments, and `ADDRESS_HEADER`/`XFF_DEPTH` configured correctly), and answer identically for unknown and wrong credentials.
- OAuth/OIDC is two `+server` endpoints: start (state, PKCE, short-lived `sameSite=lax` cookies, `redirect(..., { external })`) and callback (verify state, exchange code, key identity by `(provider, subject)`, mint your own session). Use a library for token validation.
- Fine-grained authorization means scoping every query by the authenticated principal and centralising policy so loads, actions, endpoints and remote functions all use it.
- CSRF protection is production-only and origin-based; fix the self-origin behind proxies, keep `csrf.trustedOrigins` exact, and implement CORS yourself for cross-origin cookie-authenticated APIs.

## Review Questions

1.  State two advantages and two disadvantages of server-side sessions versus JWTs. Which does the SvelteKit documentation say can be revoked immediately?

2.  Why should the database store `sha256(token)` rather than the token the browser holds? Why is plain SHA-256 acceptable here but not for passwords?

3.  What are SvelteKit’s defaults for `httpOnly`, `secure`, `sameSite` and `path` when you call `cookies.set`? Which of these differs in development?

4.  Find the bug and explain the exploit:

    ```ts
    // src/routes/(app)/+layout.server.ts
    export const load = ({ locals }) => {
     if (!locals.user) redirect(303, '/login');
     return {};
    };
    // src/routes/(app)/billing/+page.server.ts
    export const load = async () => ({ invoices: await allInvoices() });
    ```

5.  Give two independent reasons layout-only guards are insufficient. Then list three kinds of entry point they do not cover at all.

6.  Your login action sets the session cookie and returns `{ success: true }` instead of redirecting. A `load` function that runs after the action reads `locals.user`. What does it see, and why? How do you fix it?

7.  Which requests bypass `handle`? What does that imply about where authenticated content may appear?

8.  Explain why `if (pathname.startsWith('/app') && !locals.user)` in `handle` does not protect `getInvoices = query(...)` in `src/routes/(app)/billing/data.remote.ts`. What does protect it?

9.  Write `requireUser()` such that it redirects in `load`/actions but returns a 401 error in remote functions. Which property of the request event distinguishes the two, and why can `command` not simply redirect?

10. Multiple choice: inside a remote `form` function, which value is **not** safe to use for an authorization decision?

    a.  `getRequestEvent().locals.user.role`
    b.  `getRequestEvent().cookies.get('session')` validated against the database
    c.  `getRequestEvent().url.pathname`
    d.  the schema-validated argument compared against `locals.user.id`

11. Why must a new session be created at login rather than upgrading the existing anonymous session? Name the attack.

12. What is the purpose of `DUMMY_HASH` in `verifyPassword`? What would an attacker observe without it?

13. Why is a per-IP-only login rate limit insufficient, and a per-account-only limit risky? What combination does the chapter use?

14. An in-process token bucket works in development but fails to limit attackers in production on three replicas. Why? What replaces it? And why does it also fail if all clients appear to share one IP?

15. Find the bug:

    ```ts
    export const GET = ({ url }) => {
        redirect(302, url.searchParams.get('next') ?? '/');
    };
    ```

    What happens in SvelteKit 3 for `?next=https://evil.example`? Why is that still not a sufficient fix?

16. Write a `safeRedirectTarget` test table: for each of `/app`, `//evil.com`, `/\\evil.com`, `https://evil.com`, `javascript:alert(1)`, `/a?b=c#d`, state the expected output (fallback `/app`).

17. In the OIDC start endpoint, why must the state/verifier cookies use `sameSite: 'lax'` and not `'strict'`? Why is `{ external: true }` (or an allow-list) passed to `redirect`?

18. In the callback, why compare `state` with `timingSafeEqual` and delete the three cookies unconditionally?

19. An attacker creates an account at a lenient identity provider with the victim’s email address (unverified). Your callback links identities by email. What happens and what are two mitigations?

20. Your app is behind a reverse proxy that does not forward the `Host` header, and every login POST returns “Cross-site POST form submissions are forbidden” in production but works in dev. Why does it only fail in production, and what do you configure?

21. Multiple choice: a payment gateway posts a form back to `/checkout/return` from `https://pay.example`. What is the narrowest correct configuration?

    a.  `csrf: { trustedOrigins: ['*'] }`
    b.  `csrf: { trustedOrigins: ['https://pay.example'] }`
    c.  Set `sameSite: 'none'` on the session cookie
    d.  Disable the origin check with `checkOrigin: false`

22. Does `csrf.trustedOrigins` apply to remote function calls from another origin? What does that mean for cross-origin clients wanting to call them?

23. Your mobile app calls `POST /api/orders` with `Content-Type: application/json` and a bearer token. Is SvelteKit’s origin check relevant? What governs browser cross-origin access, and who implements it?

24. Design: an `/admin` area, a public marketing site (prerendered), and a customer dashboard with remote functions. Sketch where each guard lives (prerender, `handle`, loads, remote functions) and which of them would be bypassed if you only relied on `handle` prefix checks.

25. A user changes their password. List every session-related action your system must take, referencing the functions in the chapter.

26. IDOR: `getProject(id)` loads by id and then compares `ownerId`. Another developer writes `deleteProject(id)` and forgets the comparison. Describe a structural change that makes the mistake impossible rather than merely unlikely.
