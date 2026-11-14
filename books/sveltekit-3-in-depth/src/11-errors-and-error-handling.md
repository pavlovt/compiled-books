# Chapter 10: Errors and Error Handling

Error handling in SvelteKit is a pipeline with one mandatory checkpoint: every error, wherever it originates, is converted by the `handleError` hook into an `App.Error` object, and only that object is ever shown to users. Around that checkpoint sit several rendering strategies (an `+error.svelte` page, a `<svelte:boundary>`, a static `error.html`, a JSON body) chosen by where the error happened and what the client asked for. SvelteKit 3 reshaped the checkpoint: it now sees all errors, tells you what kind they are, and lets you choose the status code. This chapter maps the full system: the four error kinds, the `error`/`redirect` control-flow helpers, `handleError` semantics, boundaries and the fallback page, behaviour in `handle`, endpoints, actions, loads and remote functions, validation errors, reporting integrations, and how to design an error taxonomy for a real product.

## 10.1 The four error kinds

Every error that SvelteKit processes is classified into exactly one of four kinds. The classification is made from the thrown value’s class, and is passed to `handleError` as `kind`:

| Kind | Origin | `error` passed to the hook | Default exposed object | Safe to show as-is |
|---------------|---------------|---------------|---------------|---------------|
| `'app'` | your code called `error(status, message, props?)` | the `App.Error` body you created | that body | yes, you wrote it |
| `'framework'` | SvelteKit itself: no route (404), `POST` to a page without actions (405), body too large (413), malformed URI (400), unsupported media type (415) | `{ status, message }` with terse text such as `Not Found` | the same | yes |
| `'validation'` (server only) | a remote function argument failed its Standard Schema | `{ status: 400, message: 'Bad Request' }`, plus `issues` | the generic error; issues are not exposed | the error yes, `issues` no |
| `'unknown'` | anything else thrown: your bug, a library, a database driver | the raw thrown value | `{ status: 500, message: 'Internal Error' }` | never |

`redirect()` is not an error and never reaches `handleError`. The names say who is responsible: `app` errors are intentional outcomes (not found, forbidden), `framework` errors are protocol-level, `validation` errors are hostile or stale input, and `unknown` errors are defects. Keep that mapping in mind, because it determines logging level, alerting and what you tell the user.

The shape of the exposed object is the `App.Error` interface. It always includes `status: number` and `message: string`, and you extend it:

```ts
// src/app.d.ts
declare global {
    namespace App {
        interface Error {
            code: 'NOT_FOUND' | 'FORBIDDEN' | 'RATE_LIMITED' | 'CONFLICT' | 'INTERNAL';
            errorId?: string;
        }
        interface Locals { requestId: string; user: { id: string } | null }
    }
}
export {};
```

Required extra properties (`code` above) are enforced in two places: `error(404, 'x')` must pass them as the third argument, and `handleError` must return them (a `void` return is only a legal type when `App.Error` adds no required properties). Optional properties such as `errorId` are the lower-friction choice. The `status` and `message` are *always* present on `page.error` and the `error` prop; in SvelteKit 2 they were optional in some positions.

## 10.2 Control flow helpers

### `error`

```ts
import { error } from '@sveltejs/kit';

error(404, 'Post not found');
error(409, 'Slug already taken', { code: 'CONFLICT' });   // extra props: third argument
```

`error` has return type `never` and **throws** an `HttpError`. It has been this way since SvelteKit 2: never write `throw error(...)`, and never `return error(...)` (inside an action that raises `action_return_error`). The status must be 400-599; anything else raises an error in development. In SvelteKit 3 the second argument must be a string. The old form `error(404, { message, code })` is deprecated (a dev warning) because `status` and `message` are now managed by SvelteKit; put extra properties in the third argument.

Because `error` throws, a broad `try/catch` swallows it:

```ts
// BUG: the 404 is caught and turned into a 500
try {
    const post = await db.post(slug);
    if (!post) error(404, 'Not found');
    return { post };
} catch (e) {
    throw new Error('database failure');
}
```

The correct pattern is to scope the `try` around the fallible operation only, or to rethrow framework control flow:

```ts
import { error, isHttpError, isRedirect } from '@sveltejs/kit';

try {
    return await doWork();
} catch (e) {
    if (isHttpError(e) || isRedirect(e)) throw e;
    log(e);
    error(502, 'Upstream failed');
}
```

`isHttpError(e, status?)` narrows to `HttpError` (`{ status, body }`) and optionally checks the status. In SvelteKit 3, `error`, `isHttpError`, `redirect` and `isRedirect` refer to **public** types; if you imported the internal `HttpError`/`Redirect` classes from `@sveltejs/kit/internal` or used `instanceof` on them, switch to the predicates.

### `redirect`

```ts
import { redirect } from '@sveltejs/kit';

redirect(303, '/login');
redirect(307, 'https://accounts.example.com/authorize?...', { external: ['https://accounts.example.com'] });
```

Status 300-308; use 303 after `POST`, 307/308 to preserve method. In SvelteKit 3, a location whose origin differs from the current one **throws a developer error unless you opt in** with `{ external: true }` (any external URL except `javascript:` and `data:`) or an allow-list array of permitted origins (the only way to allow `javascript:`/`data:` URLs). The checks, from the implementation: a location is external when it does not resolve to the current origin (when the origin is not determinable it is treated as external); `external: true` rejects `javascript:` and `data:`; an array requires the location to match one entry; anything else for `external` is `redirect_external_option_invalid`. This closes the classic open-redirect hole (`redirect(303, url.searchParams.get('next'))`), but it converts attacker input into a 500, so validate user-supplied targets yourself and fall back (Chapter 6, section 6.10).

Where `redirect` is allowed: `load`, actions, `handle`, `+server` handlers, `form`, `query` and `prerender` remote functions. Not in `command` (return the destination instead). Where it is observed by the client: for data requests and remote calls it is encoded as JSON (`type: 'redirect'`) and the client router `goto`s; for page requests it is a real HTTP redirect.

### Predicates for the other control-flow values

`isActionFailure` (for `fail`), `isValidationError` (for `invalid`), `isRedirect` and `isHttpError` identify thrown or returned framework values in generic `catch` blocks. A reusable guard for wrappers:

```ts
import { isHttpError, isRedirect, isValidationError } from '@sveltejs/kit';

export function isControlFlow(e: unknown): boolean {
    return isHttpError(e) || isRedirect(e) || isValidationError(e);
}
```

## 10.3 `handleError`

`handleError` exists on both sides. Its job, in the docs’ words, is to let you log the error and to produce a representation safe to show users.

### Server signature and contract

```ts
// src/hooks.server.ts
import type { HandleServerError } from '@sveltejs/kit/hooks';

export const handleError: HandleServerError = async ({ kind, error, issues, event }) => {
    /* ... */
};
```

The argument is the discriminated union `CaughtError & { event: RequestEvent }`:

- `kind: 'app'` with `error: App.Error`,
- `kind: 'framework'` with `error: { status, message }`,
- `kind: 'unknown'` with `error: unknown`,
- `kind: 'validation'` with `error: { status: 400, message: 'Bad Request' }` and `issues` (typed through the generic: `HandleServerError<MyIssue>` gives validator-specific issue properties).

The return value is an object matching `App.Error` in which `status` and `message` are optional. **Omitted properties are inherited from the caught error** (the body for app errors, the safe status and message for framework and validation errors, `500 / 'Internal Error'` for unknown). SvelteKit merges `{ ...fallback, ...yourResult }`. Return nothing to keep defaults entirely.

Three SvelteKit 3 changes define the modern semantics:

1.  **All errors reach the hook.** In 2.x, errors created with `error()` (expected errors) skipped `handleError`. Now they arrive with `kind: 'app'`, so one place sees the complete picture. Consequence: if you log everything there, you will now log 404s and 403s. Filter by kind and status.
2.  **The hook can choose the status.** Return `{ status: 404 }` for a thrown `NotFound` class and the response, the `page.status` and `error.status` all follow. This replaces scattered `try/catch` that converted domain errors into `error()` calls.
3.  **`handleValidationError` is gone.** Remote function validation failures arrive with `kind: 'validation'`.

```ts
// src/hooks.server.ts
import type { HandleServerError } from '@sveltejs/kit/hooks';
import { DomainError } from '#lib/server/errors.js';
import { report } from '#lib/server/reporting.js';

export const handleError: HandleServerError = async ({ kind, error, issues, event }) => {
    const errorId = crypto.randomUUID();

    switch (kind) {
        case 'app':
            // intentional, already safe; add correlation id and pass through
            return { errorId };

        case 'framework':
            // routine (404 from crawlers, 405s): do not report, keep status and message
            return { errorId };

        case 'validation':
            // stale client or probing: log structure only
            console.warn('validation', { route: event.route.id, requestId: event.locals.requestId,
                fields: issues.map((i) => i.path?.map((p) => (typeof p === 'object' ? p.key : p)).join('.')) });
            return { errorId };

        case 'unknown': {
            if (error instanceof DomainError) {
                // a typed domain error: choose the status, expose its safe message
                return { status: error.httpStatus, message: error.publicMessage, code: error.code, errorId };
            }
            await report(error, { errorId, requestId: event.locals.requestId, route: event.route.id,
                method: event.request.method, userId: event.locals.user?.id });
            return { message: 'Something went wrong', code: 'INTERNAL', errorId };
        }
    }
};
```

Rules the implementation enforces or assumes:

- **It must never throw.** If it throws or its promise rejects, SvelteKit logs `handle_error_hook_failed` (with the hook’s error as `cause`, then the original), and responds with the original status and a generic `Internal Error` message, discarding your result. So a failure in your reporting service must not break error pages: wrap external calls in `try/catch` (or use fire-and-forget with a catch).
- **It may be async on the server.** During server-side *rendering*, an async hook requires Svelte’s async support: with `compilerOptions.experimental.async` off, an async `handleError` invoked for a render-time error logs a warning and its result is discarded in favour of a generic error. If you have an async `handleError` in `hooks.client.ts`, enable `compilerOptions.experimental.async` in the `sveltekit()` options so it can be awaited during rendering.
- **Be defensive about `error` for `unknown`.** Anything can be thrown: strings, `undefined`, objects without `message`. Check `error instanceof Error` before reading fields.
- **Do not leak.** Anything you return becomes the `error` prop of `+error.svelte`, `page.error`, and for JSON clients the response body. Never return `error.message` or a stack from an `unknown` error.
- **Sourcemaps are applied** to stack traces before the hook sees them in 3.0 (generated by default). For production fidelity, the adapter must not rebundle destructively; first-party adapters are still working on this, so check that your stack traces point at source files.

### Client hook

```ts
// src/hooks.client.ts
import type { HandleClientError } from '@sveltejs/kit/hooks';

export const handleError: HandleClientError = async ({ kind, error, event }) => {
    if (kind === 'app') return;                 // keep defaults
    const errorId = crypto.randomUUID();
    if (kind === 'unknown') reportToBrowserMonitoring(error, { errorId, url: event.url.href });
    return { errorId, ...(kind === 'unknown' ? { message: 'Something went wrong' } : {}) };
};
```

Differences: `event` is a `NavigationEvent` (`params`, `route`, `url`), there is no `'validation'` kind (the browser never validates), and **errors that were already transformed by the server hook are not passed through the client hook again**. An `HttpError` that came from a server `load` over a data request is already an `App.Error`; the client hook only sees client-originated errors: failures in universal `load` running in the browser, rendering errors, failed `fetch`es in the router, `use:enhance` transport failures, and remote function transport errors. So a server-side error is reported once, by the server; the client hook reports what only the browser can see.

In development, a non-`app` error on the client sets a flag that triggers a full reload on the next HMR update, since a failed module state cannot be trusted.

## 10.4 Rendering an error

### `+error.svelte` boundaries

When `load` or rendering throws during a page request, SvelteKit renders the **nearest `+error.svelte`** with props:

```html
<!-- src/routes/+error.svelte -->
<script lang="ts">
    import { page } from '$app/state';
</script>

<h1>{page.status}</h1>
<p>{page.error?.message}</p>
{#if page.error?.errorId}<small>Reference: {page.error.errorId}</small>{/if}
```

(`page.status` and `page.error` from `$app/state`; the `error` prop is also available. `$app/stores` is gone.) Placement rules:

- An error in a page’s `load` renders the nearest `+error.svelte` at or above the page’s directory.
- An error in a **layout’s** `load` renders the nearest `+error.svelte` strictly *above* that layout: a layout’s own sibling `+error.svelte` cannot render because the layout it would sit inside failed.
- An error in the **root** layout’s load (or root server load) has no boundary above it, so SvelteKit falls back to the static `src/error.html`.
- Since 2.54 on the server, and in 3.0 as a default, an automatically created `<svelte:boundary>` wraps each `+error.svelte`’s subtree, so errors **thrown while rendering** (in a component script or template) are caught, routed through `handleError`, and shown by that boundary, on both server and client. The old `experimental.handleRenderingErrors` flag is removed.
- A page that exports a 404-ish status through unmatched URLs can still use a nested `+error.svelte` by adding a catch-all `[...rest]/+page.ts` route that calls `error(404)` (Chapter 3).

Design advice: keep the root `+error.svelte` dependency-light. If it throws, the framework falls back to `error.html`; a root error page that fetches data is a recursive failure waiting to happen. Also keep layout data requirements out of the error page: when rendering an error, only the root layout’s `load` functions run again (with `state.error` set), which is why a root layout `load` that fails will itself end in `error.html`.

### Finer-grained boundaries: `<svelte:boundary>`

Use a Svelte boundary for a part of the page that can fail independently:

```html
<svelte:boundary onerror={(e) => report(e)}>
    <Recommendations />
    {#snippet pending()}<Skeleton />{/snippet}
    {#snippet failed(error: App.Error, reset)}
        <p>Could not load recommendations ({error.message}).</p>
        <button onclick={reset}>Retry</button>
    {/snippet}
</svelte:boundary>
```

The `error` passed to `failed` has been through `handleError` and is an `App.Error`. This is the right tool for remote queries awaited in components (Chapter 7): the boundary shows `pending` while they load and `failed` when they reject. `+error.svelte` pages replace the whole route; boundaries replace a region.

### The static fallback: `error.html`

```html
<!-- src/error.html -->
<!doctype html>
<html lang="en">
<head><meta charset="utf-8" /><title>%sveltekit.error.message%</title></head>
<body>
    <h1>Status %sveltekit.status%</h1>
    <p>%sveltekit.error.message%</p>
</body>
</html>
```

Only `%sveltekit.status%` and `%sveltekit.error.message%` are replaced (the message is HTML-escaped). It is a plain file: no layout, no Svelte, no client JS, and in dev only the Vite client is injected. Use it for the cases where nothing richer exists: errors in `handle`, errors in the root layout, errors while rendering the error page itself, and `x-sveltekit-error` re-entry guards. Make it self-contained (inline CSS) and brand-consistent, because during an outage it may be all users see.

### Content negotiation for non-page failures

Errors in `handle` or in a `+server` handler have no page to render. `handle_fatal_error` checks the request’s `Accept` header against `application/json` and `text/html` (default `text/html`): data requests and JSON-preferring clients receive `Response.json(appError, { status })`; browsers receive `error.html`. So an API client that sends `Accept: application/json` gets `{"status":404,"message":"Not Found","code":"NOT_FOUND"}` and a browser gets HTML for the same route. Two details:

- Non-HTML subresource requests that miss every route (images, scripts, workers, identified via `Sec-Fetch-Dest`) get a plain `404 Not Found` text response with `Vary: Sec-Fetch-Dest` instead of a full HTML page, saving bandwidth when assets 404.
- If a page request fails while the error page itself is being rendered (a sub-request for the error layout), a guard header (`x-sveltekit-error`) makes SvelteKit fall back to the static page instead of recursing.

## 10.5 Errors by origin

| Where thrown | Result |
|------------------------------------|------------------------------------|
| page `load` (server or universal) | nearest `+error.svelte` (above the layout for layout loads), status from error |
| root layout load | `error.html` |
| rendering (component script/template) | nearest boundary: the `+error.svelte`’s automatic boundary or your `<svelte:boundary>`, via `handleError` |
| `handle` (before or after `resolve`) | fatal: `error.html` or JSON; `+error.svelte` is not used |
| `+server.ts` handler | JSON or `error.html` by `Accept`; no `+error.svelte` |
| form action | `error` result: native submission renders nearest `+error.svelte` with the status; enhanced submission gives `result.type === 'error'` and renders the nearest boundary (the action route’s, if the action is on another page) |
| remote `query`/`query.batch`/`prerender` | serialised in the response envelope as an `App.Error`; awaiting consumer’s boundary or `.error`; prerendering turns it into a non-200 so the build fails |
| remote `form` | unexpected errors: nearest `+error.svelte` (or your `enhance` catch); `invalid()` and schema issues are not errors |
| remote `command` | rejects the returned promise; you catch it |
| `query.live` | `error` frame in the stream; terminal after the first value |
| `reroute` | plain 500 text response |
| `init` | server instance fails to initialise |

A few of these merit comment.

**Actions.** A thrown `error(403, 'No')` produces status 403 and an `error` result; `fail(...)` is for validation (Chapter 6) and renders no error page. Because enhanced action responses now carry real status codes in SvelteKit 3, an action error is a real 4xx/5xx in logs. When the action is on a different page than the form, the error boundary used is the *action’s route’s*, matching what the browser would show after a native post. If `handleError` returns a `status` for an action error, it is the status of the result.

**Endpoints.** Because `+error.svelte` is not used, make API endpoints return their own error shapes where clients expect them. Throwing `error(422, 'x')` from a `+server` handler yields `{ status, message, ...props }` JSON for JSON clients; for full control return `Response.json({...}, { status })` yourself, which bypasses `handleError` (it is a normal return, not an error). In 3.1 each `+server` handler also gets a `sveltekit.endpoint` tracing span that records exceptions.

**Remote functions.** The error is converted with `handleError` on the server and sent as data. On the client, `HandledHttpError` carries that body so the client hook does not transform it twice. A `query`’s `.error` is `App.Error | undefined`. Two failure channels exist outside the body: if `handle` itself rejects the request (401 from a guard, 403 from CSRF, 429 from a rate limiter), the client builds an `HttpError` from the **HTTP status** (and from a JSON body shaped like an error envelope if present), instead of reporting a generic 500. That is how a `handle`-level rate limiter surfaces as a 429 in `query.error`.

**Streaming.** After a response has started streaming (for example un-awaited promises in server `load`, Chapter 5), the status and headers cannot change. A rejected streamed promise reaches the client as a rejected promise on `data`; handle it in the component (`{#await}` or boundary). Add a no-op `.catch` on the server to avoid unhandled-rejection crashes.

## 10.6 Validation errors and `issues`

Two different things share the word *validation*:

1.  **User-input validation in forms.** Handled in-band and not an error at all: action `fail(...)`, remote form issues and `invalid(...)` (Chapters 6 and 8). The response succeeds in the HTTP sense, the user sees field messages, `handleError` is not called.
2.  **Contract violations on remote function arguments.** A `query`, `command` or `prerender` argument that fails its schema is `kind: 'validation'`. Its `issues` (Standard Schema issues: `message`, `path`) are available **only** to `handleError`. The client gets the generic 400.

Why the asymmetry: for a form, the user needs to know what to correct; for a function argument, the only senders of invalid data are old clients and attackers, and detailed messages help the latter. If you deliberately want to surface them (an internal tool), return them yourself from the hook as an extra property on `App.Error`, knowing that it exposes schema structure.

For forms, remember the `form` handler’s own schema failure is *not* `kind: 'validation'`; it is converted into issues and returned normally.

## 10.7 Reporting and observability

A practical reporting layer has four properties: correlation, classification, redaction and non-interference.

**Correlation.** Create an `errorId` in `handleError`, return it to the user (“Reference: 4f2c…”), and attach it plus the `requestId` from `locals` to the report. The support conversation then starts with a log line instead of a guess.

**Classification.** Send only `unknown` errors (and `app` errors with status \>= 500 if you use them for server faults) to your error tracker. 404s from crawlers, 405s, `validation` and 4xx `app` errors are metrics, not incidents.

**Sentry-style integration.** The client and server SDKs hook into `handleError` as shown in the docs; the pattern is the same for any vendor:

```ts
// src/hooks.server.ts
import * as Sentry from '@sentry/node';
import type { HandleServerError } from '@sveltejs/kit/hooks';

Sentry.init({ dsn: process.env.SENTRY_DSN, release: process.env.RELEASE });

export const handleError: HandleServerError = async ({ kind, error, event }) => {
    const errorId = crypto.randomUUID();
    if (kind === 'unknown' || (kind === 'app' && error.status >= 500)) {
        try {
            Sentry.captureException(kind === 'unknown' ? error : new Error(error.message), {
                tags: { kind, route: event.route.id ?? 'none' },
                extra: { errorId, requestId: event.locals.requestId }
            });
        } catch {
            /* reporting must never break the error page */
        }
    }
    return kind === 'unknown' ? { message: 'Something went wrong', errorId } : { errorId };
};
```

(Vendor SDK APIs change; consult the vendor’s SvelteKit guide for the current wrapper, and note that an SDK that instruments `handle` itself should be placed first in your `sequence`.) On serverless platforms, make sure the report is flushed before the function freezes, using the platform’s `waitUntil` equivalent from `event.platform`.

**Sourcemaps.** SvelteKit 3 generates sourcemaps by default and applies them to server stack traces. For *client* errors, upload the generated maps to your tracker at deploy time and do not serve them publicly unless you accept that.

**Redaction.** Errors can contain request bodies, SQL and tokens (`error.message` from a driver, `error.config.headers.authorization` on an axios-style error). Report a scrubbed copy, and log `event.route.id` and the HTTP method rather than full URLs with query strings.

**Tracing.** With `tracing.server: true`, spans for `handle`, loads, actions, endpoints and remote calls record exceptions; `event.tracing.current` lets you add the `errorId` attribute in `handleError` (Chapter 17).

**Non-interference.** The hook runs on the request’s critical path for the error response. Await only what you must; fire-and-forget the rest with a `catch`.

## 10.8 Designing an error taxonomy

A taxonomy is the contract between server code, `handleError`, and the UI. A workable one has three layers.

1.  **Domain errors** in server code: classes such as `NotFound`, `Forbidden`, `Conflict`, `RateLimited`, each with a stable `code`, an HTTP status, and a *user-safe* message. They are plain `Error` subclasses that do not depend on SvelteKit, so domain modules stay testable.
2.  **Translation in one place**: `handleError` maps domain errors (kind `unknown`, because SvelteKit does not know the class) to `{ status, message, code }`. Because of the 3.0 status control, no per-route `try/catch` is needed.
3.  **Presentation by `code`**: `+error.svelte` switches on `page.error.code` and `page.status` to choose copy, icon and actions (sign in, retry, go home).

```ts
// src/lib/server/errors.ts  (imported as #lib/server/errors.js)
export class DomainError extends Error {
    constructor(
        readonly code: App.Error['code'],
        readonly httpStatus: number,
        readonly publicMessage: string,
        options?: ErrorOptions
    ) {
        super(publicMessage, options);
    }
}
export const notFound = (what: string) => new DomainError('NOT_FOUND', 404, `${what} not found`);
export const forbidden = () => new DomainError('FORBIDDEN', 403, 'You do not have access');
export const conflict = (msg: string) => new DomainError('CONFLICT', 409, msg);
```

```html
<!-- src/routes/+error.svelte -->
<script lang="ts">
    import { page } from '$app/state';
    const copy = $derived(
        ({
            NOT_FOUND: { title: 'Not found', hint: 'Check the address or go back.' },
            FORBIDDEN: { title: 'No access', hint: 'Sign in with another account?' },
            RATE_LIMITED: { title: 'Slow down', hint: 'Try again in a moment.' }
        } as Record<string, { title: string; hint: string }>)[page.error?.code ?? ''] ??
            (page.status >= 500
                ? { title: 'Something went wrong', hint: 'We have been notified.' }
                : { title: 'Request problem', hint: page.error?.message ?? '' })
    );
</script>

<h1>{copy.title}</h1>
<p>{copy.hint}</p>
{#if page.status >= 500 && page.error?.errorId}<small>Reference {page.error.errorId}</small>{/if}
```

Principles: distinguish *expected, user-actionable* outcomes (4xx with specific copy) from *defects* (5xx with a reference ID); never use 200 for an error page; use 404 rather than 403 where existence itself is sensitive; use `fail`/issues rather than `error()` when the user should stay in context to correct input; keep error codes stable because clients and tests depend on them; and test the taxonomy by calling `handleError` directly with each kind (it is a pure function of its input plus `event`).

## 10.9 Pitfalls checklist

- `try/catch` around `error()`/`redirect()` without rethrow.
- Returning `error.message` for `unknown` errors from `handleError`.
- An async `handleError` without `compilerOptions.experimental.async` when errors occur during rendering.
- A reporting call inside `handleError` that can throw.
- Logging every `kind: 'framework'` error: crawlers will drown your tracker.
- Expecting `+error.svelte` for errors in `handle` or `+server`.
- A root `+error.svelte` or root layout `load` that can itself fail.
- Treating `form` schema failures as `kind: 'validation'` and looking for them in `handleError`.
- Monitoring remote function health through HTTP status only, when errors travel in 200 envelopes.
- Relying on `vite dev` to reproduce CSRF 403s or production sourcemap behaviour.

## Key takeaways

- Every error is classified as `app`, `framework`, `validation` or `unknown`, and passes through `handleError` before display. `App.Error` always has `status` and `message`; extend it in `app.d.ts`.
- `error()` and `redirect()` throw; never wrap them in a catch-all. Use `isHttpError`/`isRedirect` to rethrow. In 3.0 the `error` message is a string with extras as a third argument; external redirects require `{ external }`.
- `handleError` in 3.0 sees all errors, receives `kind`, can return `status`, inherits omitted properties from the caught error, and must never throw (failures are logged and replaced by a generic 500).
- Server-hook errors are not re-run through the client hook. Client hook has no `validation` kind and gets a `NavigationEvent`. Async client hooks need `compilerOptions.experimental.async`.
- Rendering uses the nearest `+error.svelte` (above the layout for layout errors), automatic boundaries catch rendering errors, `<svelte:boundary>` handles regions, and `error.html` is the last resort for the root layout, `handle` and `+server` errors (JSON for `Accept: application/json`).
- Remote function errors travel as serialised `App.Error`s in HTTP 200 envelopes; validation `issues` reach only `handleError`; form validation is in-band, not an error.
- Report from `handleError` with an `errorId`, only for meaningful kinds, with redaction, and without letting the reporter break the response.
- Design a taxonomy: domain errors, one translation point, presentation by `code`.

## Review Questions

1.  Name the four error kinds and give one example of each.

2.  What properties does `App.Error` always have in SvelteKit 3, and what happens if you add a required property?

3.  What is wrong with `throw error(404, 'x')` and with `return error(404, 'x')` in an action?

4.  Find the bug:

    ```ts
    try {
      const u = await db.user(id);
      if (!u) error(404, 'No user');
      return { u };
    } catch (e) {
      console.error(e);
      error(500, 'DB failure');
    }
    ```

5.  How do you call `error` with an extra `code` property in SvelteKit 3? What happened to `error(404, { message, code })`?

6.  What does `redirect(303, 'https://other.example/x')` do in SvelteKit 3? Give two ways to allow it.

7.  Why is `redirect(303, url.searchParams.get('next'))` still a problem after 3.0, even though open redirects are blocked?

8.  In SvelteKit 2, which errors did not reach `handleError`? What changed in 3.0 and what must you do to avoid logging noise?

9.  Fill in: the hook returns `{ message: 'Oops' }` for a `kind: 'unknown'` error. What are the final `status` and `message`? What if it returns `{ status: 404 }` for the same kind?

10. What happens if `handleError` throws? What does the user get?

11. A `handleError` is declared `async` and awaits a network call. Under which condition is its result discarded for render-time errors?

12. Why might the server’s `handleError` not run for an error shown in the browser from a failed server `load`, and which hook reports a failed universal `load` in the browser?

13. Which kind is absent from the client hook, and why?

14. Where is the `+error.svelte` rendered for an error in `src/routes/shop/+layout.server.ts`’s load if `shop/+error.svelte` and root `+error.svelte` both exist?

15. What renders if the root `+layout.server.ts` load throws?

16. Why is it dangerous for the root `+error.svelte` to depend on fetched data?

17. A component throws in its template during SSR. Which mechanism catches it in SvelteKit 3, and does it need a flag?

18. Multiple choice: for a `+server.ts` handler that throws `error(422, 'Bad')`, a client sending `Accept: application/json` receives

    a.  the `+error.svelte` page
    b.  JSON for the error with status 422
    c.  `error.html`
    d.  a redirect

19. What do `%sveltekit.status%` and `%sveltekit.error.message%` do, and when is `error.html` used?

20. A subresource request for `/missing.js` (Sec-Fetch-Dest: script) matches no route. What response is produced and why?

21. An action throws `error(403, 'No')` while the form is on `/a` and the action on `/b?/x`, enhanced with defaults. Which boundary renders, and with `navigate: false`?

22. Why can monitoring by HTTP status miss most remote function failures? Name an exception where HTTP status is used.

23. For a remote query argument failing validation, what does the client receive and where can you see `issues`?

24. Why do form validation errors not go through `handleError`?

25. Design `handleError` so that: 404/405 framework errors are not reported; `unknown` errors are reported with an id and shown generically; domain `Forbidden` errors keep 403 and a safe message.

26. Why should the error report be fire-and-forget or wrapped in `try/catch`, and what is the serverless caveat?

27. Name two ways a stack trace can contain sensitive data and the mitigation.

28. A streamed promise from a server `load` rejects after the response started. Can the status change? What does the client see?

29. Describe the three layers of an error taxonomy and where the HTTP status is decided.

30. Why is `unknown` the kind for a thrown `DomainError`, and what does that imply for `handleError` code?
