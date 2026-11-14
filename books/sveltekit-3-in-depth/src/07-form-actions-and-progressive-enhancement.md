# Chapter 6: Form Actions and Progressive Enhancement

Form actions are SvelteKit’s oldest mutation primitive and, despite the attention now going to remote functions, still its most battle-tested one. An action is a function exported from `+page.server.ts` that receives a `POST` from a `<form>`, does its work on the server, and hands a result back to the page that submitted it. They work without a line of client-side JavaScript, and when JavaScript is present, `use:enhance` upgrades them into fetch-based submissions that preserve scroll, focus and component state.

This chapter covers the full action surface: default and named actions, the `fail` and `redirect` control flow, the `form` prop and `page.form`, the exact behaviour of `use:enhance` including the SvelteKit 3 changes to status codes and cross-page navigation, writing your own enhancement without `use:enhance`, file uploads, GET forms, the interaction with `handle` and `event.locals`, and CSRF. It ends with a decision table for choosing between actions and the remote `form` function covered in Chapters 7 and 8. The experimental flags for remote functions are not needed for anything in this chapter; actions are stable.

## 6.1 The mental model

An action request is an ordinary HTTP `POST` to a page URL. It travels the same path as every other request (Chapter 2): `handle` runs, the route is resolved, and because the matched route is a page and the method is `POST`, the page renderer takes over. What happens next is specific to actions:

1.  The request must carry a form content type (`application/x-www-form-urlencoded`, `multipart/form-data` or `text/plain`) or SvelteKit answers `415 Unsupported Media Type`.
2.  The action name is taken from the first query parameter whose key starts with `/` (`?/login`). With none, the name is `default`. An unknown name answers `404`.
3.  If the page has no `actions` export at all, the answer is `405` with an `Allow: GET` header.
4.  The action runs with the `RequestEvent`. Its outcome is one of: returned data (`success`), a returned `fail(...)` (`failure`), a thrown `redirect(...)` (`redirect`), or any other thrown value (`error`).
5.  For a redirect, a redirect response is sent. Otherwise the page is rendered as if the user had issued a `GET`: layout and page `load` functions run, **after** the action, and the action’s result becomes the `form` prop. The response status is `200`, the `fail` status, or the error’s status.

Two properties follow from this flow and shape most design decisions:

- Actions and loads belong to the same request. When a native submission succeeds, the user sees fresh `load` data in the same response; no second round-trip, no cache to invalidate.
- The result in `form` is *ephemeral*. It exists because the page was rendered in response to a `POST`. A reload issues a `GET` (browsers ask first), and the result is gone. Anything that must survive a reload belongs in the database, a cookie, or the URL.

> **Note:** Actions cannot coexist with prerendering. A page that exports `actions` and is prerendered fails the build (`prerender_actions`). If you need an action on an otherwise static site, mark that one route `prerender = false`.

## 6.2 Default and named actions

The simplest page declares a `default` action:

```ts
// src/routes/newsletter/+page.server.ts
import type { Actions } from './$types';

export const actions = {
    default: async ({ request }) => {
        const data = await request.formData();
        const email = String(data.get('email') ?? '');
        // persist ...
        return { subscribed: email };
    }
} satisfies Actions;
```

```html
<!-- src/routes/newsletter/+page.svelte -->
<script lang="ts">
    import type { PageProps } from './$types';
    let { form }: PageProps = $props();
</script>

<form method="POST">
    <input name="email" type="email" required />
    <button>Subscribe</button>
</form>

{#if form?.subscribed}
    <p>Thanks, {form.subscribed}!</p>
{/if}
```

The form needs no `action` attribute: it posts to the current URL. Add `action="/newsletter"` to post to this page from elsewhere, for example from a form in the root layout.

When a page needs more than one operation, it exports named actions instead:

```ts
// src/routes/account/+page.server.ts
import type { Actions } from './$types';

export const actions = {
    rename: async (event) => { /* ... */ },
    changePassword: async (event) => { /* ... */ },
    deleteAccount: async (event) => { /* ... */ }
} satisfies Actions;
```

A named action is selected with a query parameter whose key is the name prefixed by `/`:

```html
<form method="POST" action="?/rename">...</form>
<form method="POST" action="/account?/deleteAccount">...</form>
```

A single form can also offer several outcomes with `formaction` on its buttons, which overrides the form’s `action` for that submission:

```html
<form method="POST" action="?/login">
    <input name="email" type="email" />
    <input name="password" type="password" />
    <button>Log in</button>
    <button formaction="?/register">Register</button>
</form>
```

### Why default and named actions cannot be mixed

SvelteKit throws if a page has `default` alongside any other action (`action_default_with_named`), and it also rejects `?/default` as an explicit name (`action_name_reserved`). The reason is URL persistence. A named action posted without a redirect leaves `?/name` in the address bar when the browser renders the response. If a `default` action existed, the next default `POST` from that page would go to the same URL and silently hit the named action again. Keeping the two disjoint removes the ambiguity. The pragmatic habit: always use named actions for anything beyond a throwaway page, even when there is only one.

### Typing actions

`./$types` is generated per route (see Chapter 1) and exports `Actions` and the page-side types. Two typing styles exist:

```ts
import type { Actions } from './$types';

// 1. satisfies: keeps the precise inferred return types per action
export const actions = {
    save: async () => ({ ok: true as const })
} satisfies Actions;

// 2. annotation: widens everything to the generic Actions signature
export const actions2: Actions = {
    save: async () => ({ ok: true })
};
```

Prefer `satisfies`. The generated `PageProps['form']` type is built from the union of what your actions actually return, so the page gets a discriminated `form` without any manual typing. With the annotation style, `form` collapses to a loose record. TypeScript also needs the return types to be distinguishable: if every failure returns `{ error: string }` and every success returns `{ ok: true }`, narrowing with `'ok' in form` or an explicit `kind` field works; if both return the same shape, you will fight the compiler.

## 6.3 Anatomy of an action

Each action receives the full `RequestEvent`: `request`, `cookies`, `locals`, `url`, `params`, `fetch`, `getClientAddress()`, `platform`, `setHeaders`, and so on. Read the body with the standard Web API:

```ts
const data = await request.formData();
const email = data.get('email'); // FormDataEntryValue | null (string | File | null)
```

`formData.get` returns `string | File | null`, so you must narrow before use; there is no type-level link between your markup and your handler. This is the central weakness of actions compared with remote forms, and the reason every serious action begins with schema validation.

### Return values

| Action does | Result type | HTTP status (native) | HTTP status (enhanced, JSON) | `form` prop |
|---------------|---------------|---------------|---------------|---------------|
| returns an object | `success` | 200 | 200 | the object |
| returns `undefined` | `success` | 200 | 204 | `null`/`undefined` |
| returns `fail(n, data)` | `failure` | `n` | `n` | `data` |
| throws `redirect(...)` | `redirect` | the redirect status | `type: 'redirect'` in JSON body | n/a |
| throws `error(n, ...)` | `error` | `n` | `n` | nearest `+error.svelte` rendered |
| throws anything else | `error` | 500 | 500 | nearest `+error.svelte` rendered |

Because the enhanced request uses `accept: application/json`, SvelteKit answers it with an `ActionResult` encoded with devalue rather than rendering HTML. The returned data must therefore be serialisable by devalue: plain objects, arrays, primitives, `Date`, `Map`, `Set`, `BigInt`, plus anything registered through the `transport` hook (Chapter 9). Returning a `Response` (for instance from the deprecated `json()` helper) raises `action_response_not_serializable`; class instances without a transport encoder raise `action_data_not_serializable` naming the offending path.

Three mistakes are caught for you, in development:

- `throw fail(...)` raises `action_throw_fail`. `fail` returns a value; you must `return` it.
- `return redirect(...)` raises `action_return_redirect`. `redirect` throws.
- `return error(...)` raises `action_return_error`. Same reason.

The deeper rule, covered in Chapter 10: `redirect()` and `error()` *throw*, so never wrap them in a `try/catch` that swallows everything. If you must catch, rethrow with `isRedirect(e)` / `isHttpError(e)`.

### Validation with `fail`

`fail(status, data)` carries the status code and any data the page needs to redisplay the form. Pair it with a Standard Schema library; the same Valibot schema can then validate in actions, in remote functions and in client-side preflight:

```ts
// src/routes/register/schema.ts
import * as v from 'valibot';

export const registerSchema = v.object({
    email: v.pipe(v.string(), v.trim(), v.email('Enter a valid email')),
    password: v.pipe(v.string(), v.minLength(12, 'At least 12 characters')),
    terms: v.optional(v.literal('on'), undefined)
});
```

```ts
// src/routes/register/+page.server.ts
import { fail, redirect } from '@sveltejs/kit';
import * as v from 'valibot';
import type { Actions } from './$types';
import { registerSchema } from './schema';
import { createUser, EmailTakenError } from '#lib/server/users.js';

export const actions = {
    default: async ({ request, cookies, locals }) => {
        const raw = Object.fromEntries(await request.formData());
        const parsed = v.safeParse(registerSchema, raw);

        if (!parsed.success) {
            return fail(422, {
                // never echo secrets back
                values: { email: typeof raw.email === 'string' ? raw.email : '' },
                errors: v.flatten<typeof registerSchema>(parsed.issues).nested ?? {}
            });
        }

        if (parsed.output.terms !== 'on') {
            return fail(422, {
                values: { email: parsed.output.email },
                errors: { terms: ['You must accept the terms'] }
            });
        }

        try {
            const user = await createUser(parsed.output.email, parsed.output.password);
            cookies.set('session', user.sessionId, { path: '/', maxAge: 60 * 60 * 24 * 7 });
            locals.user = user; // see section 6.9
        } catch (e) {
            if (e instanceof EmailTakenError) {
                return fail(409, {
                    values: { email: parsed.output.email },
                    errors: { email: ['That email is already registered'] }
                });
            }
            throw e; // unexpected: becomes a 500 via handleError
        }

        redirect(303, '/welcome');
    }
} satisfies Actions;
```

Note the design choices. `Object.fromEntries(formData)` collapses repeated keys, which is wrong for checkbox groups and `<select multiple>`; for those use `formData.getAll(name)`. The returned `values` object deliberately excludes the password. `fail` statuses are meaningful HTTP codes (`422` for validation, `409` for conflicts), and since 3.0 these codes reach enhanced requests unchanged (section 6.5).

On the page side:

```html
<!-- src/routes/register/+page.svelte -->
<script lang="ts">
    import { enhance } from '$app/forms';
    import type { PageProps } from './$types';

    let { form }: PageProps = $props();
    let submitting = $state(false);
</script>

<form
    method="POST"
    use:enhance={() => {
        submitting = true;
        return async ({ update }) => {
            await update({ reset: false });
            submitting = false;
        };
    }}
>
    <label>
        Email
        <input name="email" type="email" value={form?.values?.email ?? ''} aria-invalid={!!form?.errors?.email} />
    </label>
    {#each form?.errors?.email ?? [] as message}<p class="error">{message}</p>{/each}

    <label>
        Password
        <input name="password" type="password" aria-invalid={!!form?.errors?.password} />
    </label>
    {#each form?.errors?.password ?? [] as message}<p class="error">{message}</p>{/each}

    <label><input name="terms" type="checkbox" /> I accept the terms</label>
    {#each form?.errors?.terms ?? [] as message}<p class="error">{message}</p>{/each}

    <button disabled={submitting}>Create account</button>
</form>
```

`form` is `undefined` until a submission has happened, hence the optional chaining everywhere. If the page hosts several forms, put a discriminator in each result (`{ form: 'rename', ... }`) and test it before reading fields; otherwise one form’s failure renders into the other.

### `form` prop versus `page.form`

The submitted page receives the result as its `form` prop. The same value is on `page.form` from `$app/state` (read from any component, for instance a toast in the root layout), alongside `page.status`, which carries the action’s status code. Both reset on the next navigation or submission. Remember that `$app/stores` no longer exists in SvelteKit 3; use `page` from `$app/state` without a `$` prefix.

```html
<script lang="ts">
    import { page } from '$app/state';
</script>

{#if page.form?.flash}
    <p role="status">{page.form.flash}</p>
{/if}
```

## 6.4 Progressive enhancement with `use:enhance`

Without JavaScript, a successful `POST` yields a full page load of the response, `form` is populated, and the URL may still contain `?/name`. Add `use:enhance` from `$app/forms` and, with no argument, SvelteKit emulates that behaviour without reloading:

- It intercepts `submit`, ignores forms whose method is not `post`, and `fetch`es the action URL with `accept: application/json`, the header `x-sveltekit-action: true`, and `cache: 'no-store'`. For `urlencoded` forms it sets the content type itself; for `multipart/form-data` it deliberately does not, so the browser can add the boundary.
- It deserialises the response into an `ActionResult`.
- On `success` it resets the form element and calls `refreshAll()` (re-running load functions that need it; see Chapter 5).
- It applies the result: sets `form`, `page.form` and `page.status` for a same-page submission, calls `goto` for a redirect, and renders the nearest `+error.svelte` for an error.
- It resets focus to a sensible element (Chapter 12).

`use:enhance` can only be used on `method="POST"` forms that target a page action. In development, putting it on a GET form raises `enhance_invalid_method`, and it throws for forms posting to a `+server` endpoint. If a `+server.ts` sits next to your `+page.server.ts`, a plain `fetch` goes to the endpoint; `use:enhance` always includes `x-sveltekit-action`, which routes to the page action.

### The `SubmitFunction`

Pass a function to hook into both ends of the request:

The type lives in `$app/forms`:

```ts
import type { SubmitFunction } from '$app/forms';

const onSubmit: SubmitFunction = ({ action, formData, formElement, controller, submitter, cancel }) => {
    // runs immediately before the request
    return async ({ action, formData, formElement, result, update }) => {
        // runs with the ActionResult
    };
};
```

The input fields:

| Field | Meaning |
|------------------------------------|------------------------------------|
| `action` | `URL` the form will post to (after `formaction` resolution) |
| `formData` | the `FormData` about to be sent; mutate it to add or alter fields |
| `formElement` | the `<form>` |
| `submitter` | the button that triggered the submit, or `null` |
| `controller` | the `AbortController` bound to this request’s `fetch` |
| `cancel()` | prevents submission |

The returned callback overrides the default post-submission behaviour entirely. To get the default back, call `update()`, or handle the result yourself with `applyAction`. A common pattern is a pessimistic pending state plus “keep the user’s input on failure”:

```html
<script lang="ts">
    import { enhance } from '$app/forms';
    let pending = $state(false);
</script>

<form
    method="POST"
    action="?/comment"
    use:enhance={({ formData, cancel }) => {
        const body = String(formData.get('body') ?? '').trim();
        if (!body) return cancel();
        formData.set('body', body);

        pending = true;
        return async ({ result, update }) => {
            pending = false;
            // keep what the user typed if validation failed; clear on success
            await update({ reset: result.type === 'success' });
        };
    }}
>
    <textarea name="body"></textarea>
    <button disabled={pending}>Post</button>
</form>
```

Beware of a subtlety: `update()` resets the form only on `success` anyway. Passing `reset: false` is for success cases where you want to keep values (an edit form, a settings page). Failures never reset.

The `controller` is how you implement “latest submission wins”, for instance a search-as-you-type form that is submitted on every `input` event: keep a module-level variable with the previous controller and `abort()` it at the start of the next submission. An aborted request resolves silently (SvelteKit swallows `AbortError` and does not call your callback).

### The `update` options

`update({ reset, refreshAll, navigate })`:

- `reset` (default `true`): reset the `<form>` element on a `success`.
- `refreshAll` (default `true` on success, `false` on failure): whether to re-run all load functions and remote queries afterwards. `invalidateAll` is the deprecated alias. Set it to `false` when the action’s result already carries everything that changed, for example a toggle that returns the new state and the page renders from `form`. When the submission navigates elsewhere (below), `refreshAll: false` does not prevent the destination’s own loads from running; it only lets shared layout data be reused.
- `navigate` (default `true`): see the next section.

### `applyAction` and manual control

If you return your own callback and skip `update`, you own the semantics. `applyAction(result)` does the following depending on `result.type`:

- `success`, `failure`: set `page.status` to `result.status` and update `form`/`page.form` with `result.data`.
- `redirect`: `goto(result.location, { refreshAll: true })`.
- `error`: render the nearest `+error.svelte` with `result.error`.

It resets focus in all cases. It does **not** refresh data and does **not** navigate to the `location` of a non-redirect result. That is the job of `update`, which is why `update` is almost always what you want after custom pre- and post-processing, and `applyAction` is for the cases where you want the result applied but have decided (for instance) to leave the form values and data alone:

```ts
use:enhance={() => async ({ result, update }) => {
    if (result.type === 'failure' && result.status === 429) {
        showToast('Slow down');   // handle one case specially
        return;                   // and skip default handling
    }
    await update();               // everything else: default behaviour
}}
```

## 6.5 SvelteKit 3 behaviour changes

Two changes in 3.0 affect every codebase that uses `use:enhance`. Both are called out in the migration guide, and neither is caught by the type checker.

### Failure status codes now reach the client

In SvelteKit 2, an enhanced action response was always HTTP 200 and the real status was inside the JSON body. In 3.0 the response status equals the `fail` status (and the error’s status for errors). The client code that parses the response also copies the HTTP status onto `result.status` for `failure` and `error` results. What this changes in practice:

- `result.status` in your callback and `page.status` after `applyAction` are the `fail` code, as before for native submissions.
- Observability tools, CDNs and proxies see 4xx/5xx for rejected submissions, so alerting on error rate will now include validation failures unless you exclude 422 or whatever status you use for them.
- Tests that asserted `200` on an enhanced failure must be updated.
- Anything between browser and server that rewrites 4xx bodies (some WAFs, some CDN custom error pages) can now damage the JSON. The client handles this explicitly: if the body is not a recognisable `ActionResult` and the status is not OK, it throws an `HttpError` (when the body looks like an `App.Error`) or a `SvelteKitError`, which goes through the client `handleError`. If the response was an HTTP redirect that `fetch` followed, it is reported as a `redirect` result to the final URL.

### Cross-page enhanced submissions navigate

In SvelteKit 2, `<form action="/other?/subscribe" use:enhance>` posted in the background and applied the result to the *current* page. That differs from what the browser does without JavaScript, which is to navigate to `/other` and render it with that result as `form`. In 3.0 enhancement matches the browser:

- If the destination (the form’s action with `?/name` removed) is on another page, `update()` navigates there with a pushed history entry, populating that page’s `form` and `page.status`.
- The landing URL keeps other query parameters. `action="/login?redirectTo=/dashboard&/do-login"` lands on `/login?redirectTo=/dashboard`.
- Redirect results are always followed. Errors render the boundary nearest the *action’s* route.

The opt-out restores v2 behaviour for widgets (a newsletter box in the footer that posts to a signup page):

```html
<form
    method="POST"
    action="/newsletter?/subscribe"
    use:enhance={() => async ({ update }) => {
        await update({ navigate: false });
    }}
>
```

With `navigate: false` the result is applied to the page you are on: `form`, `page.form`, `page.status`, and error results render the current route’s nearest boundary. Note that this applies the result to a page that did not define the action, so its `form` prop type does not include the action’s return type; read it from `page.form` and cast, or handle `result.data` in your callback.

One URL detail trips people up. A **relative** action replaces the whole query string by URL resolution: `action="?/delete"` on `/items?page=2` resolves to `/items?/delete`, losing `page=2` for both native and enhanced submissions. To keep it, write `action="?page=2&/delete"`. Also, without JavaScript the browser cannot strip the `?/delete` part, so a native submission lands on `/items?/delete`. Reloading is a harmless `GET`, but a `load` function reading `url.search` can observe different values with and without JavaScript, so avoid depending on it.

## 6.6 Enhancing without `use:enhance`

`use:enhance` is about forty lines of orchestration around `fetch`. When you need something it does not offer (progress events for uploads, optimistic UI keyed to your own store, integration with a form library), implement the protocol yourself:

```html
<script lang="ts">
    import { applyAction, deserialize } from '$app/forms';
    import { goto, refreshAll } from '$app/navigation';
    import type { ActionResult } from '$app/forms';

    async function onsubmit(event: SubmitEvent & { currentTarget: HTMLFormElement }) {
        event.preventDefault();
        const form = event.currentTarget;
        const body = new FormData(form, event.submitter);

        const response = await fetch(form.action, {
            method: 'POST',
            body,
            headers: { 'x-sveltekit-action': 'true' } // route to the page action, not a sibling +server
        });

        // not JSON.parse: devalue handles Date, BigInt, Map, custom transport types
        const result: ActionResult = deserialize(await response.text());

        if (result.type === 'success') await refreshAll();
        await applyAction(result);
    }
</script>

<form method="POST" {onsubmit}>...</form>
```

Three details matter. `new FormData(form, event.submitter)` includes the submitter’s name/value, which is how `formaction`-less multi-button forms distinguish themselves. The `x-sveltekit-action` header is what makes the server treat the request as an action call even when a `+server` handler exists. And `deserialize` is mandatory: the body is not JSON. Note that this hand-rolled version intentionally omits cross-page navigation; replicate `result.location` handling (see `update`’s source in `$app/forms`) if you need it.

## 6.7 File uploads

Add `enctype="multipart/form-data"` and file inputs and the entries arrive as `File` objects:

```html
<form method="POST" action="?/upload" enctype="multipart/form-data" use:enhance>
    <input type="file" name="avatar" accept="image/png,image/jpeg" required />
    <button>Upload</button>
</form>
```

```ts
// src/routes/settings/+page.server.ts
import { fail } from '@sveltejs/kit';
import { createWriteStream } from 'node:fs';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import type { Actions } from './$types';

const MAX_BYTES = 2 * 1024 * 1024;
const ALLOWED = new Set(['image/png', 'image/jpeg']);

export const actions = {
    upload: async ({ request, locals }) => {
        if (!locals.user) return fail(401, { message: 'Sign in first' });

        const data = await request.formData();
        const avatar = data.get('avatar');

        if (!(avatar instanceof File) || avatar.size === 0) {
            return fail(400, { message: 'Choose a file' });
        }
        if (avatar.size > MAX_BYTES) return fail(413, { message: 'File too large' });
        if (!ALLOWED.has(avatar.type)) return fail(415, { message: 'PNG or JPEG only' });

        // Stream to disk rather than avatar.arrayBuffer(); the client-declared type is untrusted,
        // so sniff the magic bytes in real code
        const target = `uploads/${locals.user.id}.${avatar.type === 'image/png' ? 'png' : 'jpg'}`;
        await pipeline(Readable.fromWeb(avatar.stream() as any), createWriteStream(target));

        return { saved: true };
    }
} satisfies Actions;
```

Operational notes:

- **Missing `enctype`.** An enhanced submission with a `File` value but without `multipart/form-data` would silently send the file’s name; SvelteKit logs `enhance_file_without_enctype` in development. Without JavaScript the browser does the same. Always set `enctype`.
- **Body limits are enforced outside actions.** `request.formData()` buffers the body. The adapter or platform limit applies first: adapter-node’s `BODY_SIZE_LIMIT` defaults to 512K (Chapter 18). Raise it for upload routes, or move large uploads to presigned object-store URLs. Checking `avatar.size` in the action only helps after the body has been read.
- **`File.type` is client-supplied.** Treat it as a hint.
- **Empty file inputs** still produce a `File` with `size === 0` and an empty name, which is why the check above tests `size`.
- Remote `form` functions (Chapter 8) stream multipart uploads and validate `File` fields with schemas such as `v.file()`, which removes most of this boilerplate.

## 6.8 GET forms

Not every form is a mutation. Search boxes and filters belong in the URL:

```html
<form action="/search" data-sveltekit-replacestate>
    <input name="q" value={page.url.searchParams.get('q') ?? ''} />
    <button>Search</button>
</form>
```

A form with no `method` (or `method="GET"`) is handled by the client router like an `<a>`: it navigates to `/search?q=...`, runs load functions, and honours the `data-sveltekit-*` options (`data-sveltekit-reload`, `data-sveltekit-replacestate`, `data-sveltekit-reset="false"` to keep scroll and focus; see Chapter 3 and Chapter 16 for preloading). No action runs. This is the right tool for anything idempotent, since the result is shareable, bookmarkable, cacheable and back-button friendly, none of which is true of an action result. `use:enhance` must not be combined with it.

## 6.9 Actions, `handle` and `locals`

`handle` runs once per request, **before** the action. It does not run again between the action and the `load` functions that render the response. So if `handle` derives `event.locals.user` from a cookie and your action changes that cookie, the `load` functions that run in the same request will see the stale `locals`:

```ts
// src/hooks.server.ts
import type { Handle } from '@sveltejs/kit/hooks';
import { getUserFromSession } from '#lib/server/session.js';

export const handle: Handle = async ({ event, resolve }) => {
    event.locals.user = await getUserFromSession(event.cookies.get('session'));
    return resolve(event);
};
```

```ts
// src/routes/account/+page.server.ts
import type { Actions, PageServerLoad } from './$types';
import { destroySession } from '#lib/server/session.js';

export const load: PageServerLoad = ({ locals }) => ({ user: locals.user });

export const actions = {
    logout: async ({ cookies, locals }) => {
        await destroySession(cookies.get('session'));
        cookies.delete('session', { path: '/' });
        locals.user = null; // required: load runs next, in the same request, with the same locals
    }
} satisfies Actions;
```

Forget `locals.user = null` and the page re-renders showing the user still logged in until the next request. The symmetrical bug appears on login. This is not specific to authentication: any per-request derivation (feature flags from a cookie, a locale cookie, a selected tenant) has the same staleness window. Two defensive designs:

- Centralise the cookie-plus-locals pair in a helper (`setSession(event, user)`), used by every action that changes it. This is the pattern Chapter 14 builds on.
- Redirect after state-changing actions (`redirect(303, ...)`). The next request is a fresh `GET` which runs `handle` again, making staleness impossible at the price of losing the ephemeral `form` data.

Also remember what `handle` does not do. Actions are reached through `handle` (so a `handle` that checks authentication guards them) but an action does not see anything you computed *after* `resolve` was called, and a guard written only in a layout `load` does not protect actions at all: loads of other nodes and actions are separate code paths, and for an action request, the page’s layout loads are not a precondition for running the action. Always authorise inside the action itself or in `handle`.

## 6.10 Redirects, cookies and CSRF

### Redirects

After a successful mutation, redirect with `303 See Other` so the browser follows with a `GET`; a `307`/`308` would repeat the `POST` against the new URL. In an enhanced submission the redirect arrives as a `redirect` result and `update`/`applyAction` call `goto` with `refreshAll: true`.

Redirect targets that come from user input need care. The official login example reads `url.searchParams.get('redirectTo')` and passes it straight to `redirect`. In SvelteKit 3 `redirect()` refuses any location whose origin differs from the current one unless you pass `{ external: true }` or an allow-list array, so `//evil.example` and `https://evil.example` raise an error instead of redirecting (the error is a developer error, so it becomes a 500). That turns an open-redirect vulnerability into a server error. Make it a clean fallback instead:

```ts
function safeRedirectTarget(raw: string | null, fallback = '/'): string {
    if (!raw || !raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) return fallback;
    return raw;
}

// in the action:
redirect(303, safeRedirectTarget(url.searchParams.get('redirectTo'), '/dashboard'));
```

If you genuinely need to leave the site (an OAuth provider, a payment page), pass the allow-list form: `redirect(303, url, { external: ['https://accounts.example.com'] })`.

### Cookies

`cookies.set` requires you to think about options: in 3.0 the `path` defaults to `/` (in 2.x it had to be set explicitly). Defaults are `httpOnly: true`, `secure: true` (relaxed on localhost in dev) and `sameSite: 'lax'`. Cookies set in an action are applied to whichever response the action produces, including a redirect response. They are not visible through `cookies.get` in a *different* request until the browser sends them back, but they are visible through `cookies.get` in `load` functions running later in the same request.

### CSRF

SvelteKit checks the `Origin` header on `POST`, `PUT`, `PATCH` and `DELETE` requests with a form content type (or no content type at all) and rejects those from another origin with 403. It is always on in production. Origin is compared with `paths.origin` when configured, otherwise with `request.url`’s origin, so behind a TLS-terminating proxy that does not forward the protocol/host correctly, every form post will be rejected (Chapter 18). Cross-origin posts that you actually want, such as a webhook-ish form from a partner domain, must be listed in `csrf.trustedOrigins`; `checkOrigin: false` no longer exists. In 3.0, cross-origin mutating requests that omit `Content-Type` are rejected too. CSRF details and CSP are covered in Chapter 15.

An action’s CSRF protection is origin-based, not token-based. It relies on browsers sending an accurate `Origin` header for cross-site form posts, and on `sameSite: 'lax'` cookies not being attached to such posts. It does not substitute for authorisation.

## 6.11 Errors inside actions

Unexpected exceptions (anything other than `redirect`, `error`, `fail`) are passed to `handleError`, produce a 500 and, for enhanced submissions, an `error` result: the client renders the nearest `+error.svelte` and your callback gets `result.type === 'error'` with `result.error` typed as `App.Error`. A thrown `error(404, 'Not found')` is an *expected* error; with SvelteKit 3 it still passes through `handleError` (Chapter 10) but carries the status you gave. For validation-style problems, prefer `fail`: it leaves the page in place with `form` populated, while `error` swaps in an error page. If the action’s page has no `actions` export or the name does not exist, 405 and 404 errors respectively are generated by the framework; `+error.svelte` renders those only for native submissions.

## 6.12 Actions or remote functions?

Remote functions (Chapters 7 and 8) are experimental and gated behind two flags; actions are stable. The remote `form` solves the typing, validation and single-flight problems actions leave to you. The decision is mostly about risk tolerance and about where the code lives:

| Concern | Form actions | Remote `form` / `command` |
|------------------------|------------------------|------------------------|
| Stability | stable, no flags | experimental, two flags, may change |
| Location | page-bound (`+page.server.ts`), URL is the endpoint | anywhere in `src`, callable from any page or component |
| Input typing | `FormData`, manual narrowing | schema-derived types for handler, fields and issues |
| Validation errors | hand-rolled (`fail` + shape) | schema issues per field, `invalid()` for server-only rules |
| Client validation | custom | `preflight(schema)` |
| After success | `load` re-runs; enhanced: `refreshAll()` | all queries refreshed, or targeted single-flight refresh |
| Redirects | yes | `form`: yes; `command`: no |
| Native (no-JS) fallback | yes, full | `form` yes; `command` no |
| Result lifetime | `form` prop, ephemeral | `.result`, ephemeral |
| Multiple instances per page | manual (discriminator) | `form.for(id)` |
| Prerendered pages | not allowed | the form markup can be prerendered, but submitting needs a running server |
| Pre-existing code and libraries | huge ecosystem (superforms-style helpers) | small |

Keep using actions when the app is already built on them, when stability matters more than ergonomics, when the interaction is naturally page-scoped and URL-addressed (login, checkout steps), or when you rely on tooling that targets actions. Start new greenfield code with remote forms only if you accept the experimental label. Mixed apps are fine: both mechanisms run on the same server, share `handle`, and a page may use an action form and a remote form side by side. Chapter 8 ends with a migration path.

## Key takeaways

- An action is a `POST` to a page URL. The action runs first, then loads run, then the page renders with the result as `form`. Use named actions (`?/name`, `formaction`); default and named cannot coexist.
- `return` data or `fail(status, data)`; `throw` `redirect`/`error`. Dev-mode checks catch `throw fail`, `return redirect`, and non-serialisable data. Returned data is devalue-serialised and ephemeral.
- Use `satisfies Actions` so `form` is typed from what you return. Validate every action with a schema; `FormData` gives you no types.
- `use:enhance` with no argument emulates the native flow: reset on success, `refreshAll`, apply result, follow redirects, render error boundaries. A callback overrides all of it unless you call `update()`.
- SvelteKit 3: `fail` statuses become real HTTP statuses on enhanced requests; enhanced submissions to another page navigate there. Use `update({ navigate: false })` for widget-style posts.
- A relative `action="?/x"` drops the existing query string; write `?page=2&/x` to keep it.
- `handle` does not rerun after an action. Update `event.locals` when you change what it was derived from, or redirect.
- File uploads need `enctype="multipart/form-data"`; body limits are enforced before your code; `File.type` is untrusted.
- GET forms are router navigations, not actions. Use them for search and filters.
- External `redirect` targets throw in SvelteKit 3 unless allow-listed; validate `redirectTo` values yourself.
- CSRF protection is Origin-based and always on in production; configure `csrf.trustedOrigins` and `paths.origin` for proxies and legitimate cross-origin posts.

## Review Questions

1.  A page exports `actions = { default, rename }`. What happens, and why does SvelteKit disallow the combination?

2.  Describe, in order, what the server does with a `POST` to a page route that has no `actions` export. Which status and header does it produce?

3.  What is the difference in observable HTTP status between a native form submission and an enhanced one when the action returns `undefined`?

4.  Find the bug:

    ```ts
    export const actions = {
      save: async ({ request }) => {
        const data = await request.formData();
        if (!data.get('title')) throw fail(400, { missing: true });
        return { ok: true };
      }
    };
    ```

5.  Why should you prefer `satisfies Actions` over annotating `actions: Actions`?

6.  What does `Object.fromEntries(await request.formData())` lose, and what do you use instead for a group of checkboxes sharing one name?

7.  A form posts `action="?/delete"` from `/items?page=2` and uses `use:enhance`. Where does the user land after a success (assume no redirect), and how would you preserve `page=2`?

8.  In SvelteKit 3, an enhanced action returns `fail(422, { errors })`. What is (a) the HTTP response status, (b) `result.status` in the `use:enhance` callback, (c) `page.status` after `update()`?

9.  Multiple choice: which statement about `applyAction(result)` is true?

    a.  It refreshes all data and navigates to `result.location`.
    b.  For `success` and `failure` it updates `form`, `page.form` and `page.status`; it does not refresh data.
    c.  It resets the `<form>` element on success.
    d.  It only works for `redirect` results.

10. What does `use:enhance={() => async ({ update }) => { await update({ navigate: false }); }}` change for a form with `action="/other?/subscribe"` in SvelteKit 3?

11. Why is the `controller` in `SubmitFunction` useful? Describe a case where you would call `controller.abort()`.

12. What happens to a successful enhanced submission when you return a callback that never calls `update` or `applyAction`?

13. Design question: a newsletter widget lives in the root layout and posts to `/newsletter?/subscribe`. Show the markup and explain where its result is read.

14. Why must you `deserialize` the response in a hand-written enhancement instead of calling `response.json()`?

15. What is the purpose of the `x-sveltekit-action` header, and when does omitting it change which handler runs?

16. What does this print/render for an enhanced submission to a route whose action returns `{ ok: true, at: new Date() }`: `typeof form.at` on the client?

17. A file upload works natively but the enhanced version loses the file. What is the most likely cause?

18. Why does checking `file.size > MAX` in the action not protect you against huge request bodies?

19. Explain the `locals` staleness bug in a `logout` action that only deletes the cookie. Give two different fixes.

20. A teammate says “our layout `load` redirects unauthenticated users, so actions on child pages are protected.” Explain why this is wrong and where the check belongs.

21. Multiple choice: after a successful login action, which redirect status is most appropriate?

    a.  200
    b.  301
    c.  303
    d.  307

22. In SvelteKit 3, what happens when an action calls `redirect(303, url.searchParams.get('redirectTo'))` and the parameter is `//evil.example/path`? Write a safer version.

23. Which header checks does SvelteKit’s CSRF protection perform for a form `POST`, and what must you configure behind a reverse proxy that terminates TLS?

24. Why might error-rate dashboards change after upgrading to SvelteKit 3 without any code change?

25. An action throws `new Error('db down')`. Trace what the user sees (a) without JavaScript, (b) with `use:enhance`, and what is passed to `handleError`.

26. Compare actions and remote `form` along: typing, validation, redirect support, prerendering, and stability. When would you still choose actions for a new feature?

27. Why can’t a page that exports `actions` be prerendered, and what are your options for a mostly static site with one form?

28. A search box is implemented as an action returning results in `form`. List three user-visible problems and the better design.
