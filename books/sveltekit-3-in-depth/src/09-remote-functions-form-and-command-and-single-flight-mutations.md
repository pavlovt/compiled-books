# Chapter 8: Remote Functions: form and command, and Single-Flight Mutations

Chapter 7 covered reading data. This chapter covers changing it: the `form` remote function (progressively enhanced, schema-validated, redirect-capable), the `command` remote function (callable from anywhere, no native fallback), and the machinery that makes mutations efficient: **single-flight mutations**, where the response to a mutation carries the fresh results of the queries it invalidated, so the client needs one round trip instead of two. We also cover optimistic UI with `withOverride`, the SvelteKit 3 strictness rules for client-requested updates, and a migration path from form actions (Chapter 6).

Everything here is experimental in SvelteKit 3.1 and requires the two flags shown at the start of Chapter 7. As in that chapter, where the published TypeScript types and the prose documentation disagree, we follow the types, and the source at the 3.1 line when behaviour is the question.

## 8.1 `form`: the model

A remote `form` pairs a schema with a handler:

```ts
// src/routes/todos/todos.remote.ts
import * as v from 'valibot';
import { form, query } from '$app/server';
import * as db from '#lib/server/db.js';
import { requireUser } from '#lib/server/auth.js';

export const getTodos = query(async () => db.todosFor(requireUser().id));

export const addTodo = form(
    v.object({ text: v.pipe(v.string(), v.trim(), v.minLength(1, 'Write something')) }),
    async ({ text }) => {
        const user = requireUser();
        await db.insertTodo(user.id, text);
        // no explicit refresh: every query and load function refreshes (section 8.7)
    }
);
```

```html
<!-- src/routes/todos/+page.svelte -->
<script lang="ts">
    import { addTodo, getTodos } from './todos.remote';
    const { text } = addTodo.fields;
</script>

<form {...addTodo}>
    <input {...text.as('text')} />
    {#each text.issues() ?? [] as issue}<p class="error">{issue.message}</p>{/each}
    <button disabled={!!addTodo.pending}>Add</button>
</form>

<ul>
    {#each await getTodos() as todo (todo.id)}<li>{todo.text}</li>{/each}
</ul>
```

`{...addTodo}` spreads three things onto the `<form>`: `method="POST"`, an `action` attribute, and an **attachment** (a Svelte `{@attach}` under a symbol key) that wires up client-side behaviour. Without JavaScript, the browser posts to the `action`, which is the current URL’s query string plus `/remote=<id>`:

    ?/remote=a1b2c3d4/addTodo

The page renderer recognises `?/remote=...` on a `POST` and routes it to the form instead of to `actions` (compare Chapter 6: this is the same page-POST mechanism). The form handler runs, its output (result, issues and the non-sensitive input) is stored in the request-scoped cache, and the page is rendered as with an action: `addTodo.result`, `addTodo.fields.*.issues()` and `addTodo.fields.*.value()` read from that cache during SSR and are serialised for hydration. Existing query parameters on the current URL are preserved in the action URL, so a form on `/items?sort=price` posts back to the same URL.

With JavaScript, the attachment intercepts `submit`, and the request goes to the remote endpoint with a **binary form encoding** rather than ordinary `multipart/form-data`: the converted data (typed, nested) and metadata (validate-only flag, requested refreshes) are encoded together so that **file uploads can be streamed** and the handler can see the data before large files finish arriving. You do not need `enctype` for enhanced submission of files to work, but you do need it for the no-JS fallback; set `enctype="multipart/form-data"` on any form with a file input.

The client-side steps on submit, in order:

1.  `preventDefault`, mark the form `submitted`, increment `pending`.
2.  Run **preflight** validation if a preflight schema was supplied; if it fails, issues are populated and nothing is sent.
3.  Call the `enhance` callback (default: `await form.submit()`, then reset the DOM form if it succeeded).
4.  `submit()` sends the request. The response contains `{ issues, result }` plus any single-flight query data.
5.  If there was a redirect, `goto` it (and wait for navigation). Otherwise, on success, either apply the explicit single-flight data or call `refreshAll()` (section 8.7). On validation failure, populate `issues()`.

An unexpected error (thrown out of the handler, a network failure, a 5xx from `handle`) is caught by the attachment, passed through the client `handleError`, and rendered by the **nearest `+error.svelte`**. A form handler that wants to keep the user on the page and show a message should use `invalid(...)` or return a result instead of throwing.

## 8.2 Fields

The schema defines the fields. `form.fields` mirrors its shape; each leaf has `.as(type, ...)`, which returns the attributes to spread on the input:

```html
<input {...f.fields.title.as('text')} />
<input {...f.fields.qty.as('number')} />
<input {...f.fields.published.as('checkbox')} />
<textarea {...f.fields.body.as('text')}></textarea>
```

`as()` produces `name`, `type`, `aria-invalid`, and value/checked accessors. **The `name` is not what you wrote in the schema.** It encodes the path, the coercion type, whether it is an array, and the form id:

    n:qty/a1b2c3d4/addItem        (number field)
    b:published/a1b2c3d4/addItem  (single checkbox)
    tags[]/a1b2c3d4/addItem       (array field)

That is why, since 3.0, **hand-written names are rejected**: `<input name="title">` is not part of any form and the submission fails validation. Always spread from `.as()`. The path uses JavaScript object notation (`nested.array[0].value`); quoted keys such as `a['b-c']` are not supported, and a top-level name beginning with `$` is reserved (`$` collects all issues) and raises `remote_form_reserved_field`.

### Types and coercion

Every value arrives from the browser as a string (or a `File`). The prefix tells the server how to coerce before validation:

| `as(...)` type | Schema type | Notes |
|------------------------|------------------------|------------------------|
| `'text'`, `'email'`, `'password'`, `'url'`, `'tel'`, `'search'`, `'date'`, `'time'`, `'color'`, … | `string` | `textarea` also uses `'text'` |
| `'number'`, `'range'` | `number` | `n:` prefix; an empty string becomes `undefined` |
| `'checkbox'` (single) | `boolean` | `b:` prefix; checked is `true` |
| `'checkbox'` + value (several share a field) | `string[]` | second argument is the option value |
| `'radio'` + value | `string` | second argument is the option value |
| `'select'` / `'select multiple'` | `string` / `string[]` |  |
| `'file'` / `'file multiple'` | `File` / `File[]` | needs `enctype` for no-JS |
| `'hidden'`, `'submit'` + value | the value’s type | value mandatory; the type of the value picks the prefix |
| `'image'` | `{ x: number, y: number }` | coordinates from an image input |

Rules that follow from how HTML forms work, and which the types enforce:

- **Booleans must be optional with a default.** An unchecked checkbox sends nothing. A non-optional boolean in the schema produces a type error on the `form(...)` call (the message tells you to use `v.optional(v.boolean(), false)` or Zod’s `.default(false)`).
- **Arrays default to empty.** A `select multiple` or checkbox group with nothing selected sends nothing, so declare `v.optional(v.array(...), [])`.
- Empty file inputs are omitted from the submitted data.
- Radio and checkbox-array inputs take the option as the second argument and whether it is checked as a third: `.as('radio', option, settings.visibility === option)`.
- The second argument on other types sets the initial `value` and the value restored on `reset`: `.as('text', todo.description)`. `value()` does not reflect that initial value until the field has been edited or the form submitted. Since 3.x, the default applies only until the field is edited.

```ts
// src/routes/survey/survey.remote.ts
import * as v from 'valibot';
import { form } from '$app/server';

const os = ['windows', 'mac', 'linux'] as const;
const langs = ['html', 'css', 'js'] as const;

export const survey = form(
    v.object({
        name: v.pipe(v.string(), v.minLength(2)),
        age: v.pipe(v.number(), v.integer(), v.minValue(13)),
        newsletter: v.optional(v.boolean(), false),
        os: v.picklist(os),
        langs: v.optional(v.array(v.picklist(langs)), []),
        cv: v.optional(v.file())
    }),
    async (data) => {
        // data.age is a number, data.newsletter a boolean, data.cv a File | undefined
    }
);
```

```html
<form {...survey} enctype="multipart/form-data">
    <input {...survey.fields.name.as('text')} />
    <input {...survey.fields.age.as('number')} />
    <label><input {...survey.fields.newsletter.as('checkbox')} /> Newsletter</label>

    {#each ['windows', 'mac', 'linux'] as o}
        <label><input {...survey.fields.os.as('radio', o)} /> {o}</label>
    {/each}

    {#each ['html', 'css', 'js'] as l}
        <label><input {...survey.fields.langs.as('checkbox', l)} /> {l}</label>
    {/each}

    <input {...survey.fields.cv.as('file')} />
    <button>Send</button>
</form>
```

Nested objects and arrays work as you would expect (`survey.fields.address.city.as('text')`, `fields.items[0].name`). Arrays of objects require indices; the form does not add or remove rows by itself, you render `fields.items[i]` for the indices you want, and use `.set(...)` on the array to add a row.

Two development-time diagnostics deserve mention. A form control that is not created from the form’s own `as()` produces a warning or error; and if a submission fails validation but your UI never calls `issues()`/`allIssues()`, SvelteKit logs `remote_form_issues_ignored` with the unread issues, because a form that fails silently is the most common bug in this area.

### Sensitive fields

After a failed *no-JS* submission the page is re-rendered from the server, and the form’s `value()`s are echoed back so the user does not retype everything. A top-level or nested path segment that starts with an underscore is **never echoed**:

```html
<input {...register.fields.username.as('text')} />
<input {...register.fields._password.as('password')} />
```

If validation fails natively, `username` is repopulated and `_password` is empty. Use underscore names for passwords, card numbers, tokens and anything you would not want in an HTML response. Redaction is by name only, so a field called `pin` is echoed.

### Multiple submit buttons and multiple instances

Add a field for the button, and bind it with `as('submit', value)`:

```html
<button {...auth.fields.action.as('submit', 'login')}>Log in</button>
<button {...auth.fields.action.as('submit', 'register')}>Register</button>
```

The schema holds `action: v.picklist(['login', 'register'])`, and the handler branches on it. (`buttonProps`, which older experimental versions had for the same purpose, was removed in 2.50.)

When the same form is rendered for each item of a list, give each its own state with `.for(id)`:

```html
{#each await getTodos() as todo (todo.id)}
    {@const edit = updateTodo.for(todo.id)}
    <form {...edit}>
        <input {...edit.fields.text.as('text', todo.text)} />
        {#each edit.fields.text.issues() ?? [] as issue}<small>{issue.message}</small>{/each}
        <button disabled={!!edit.pending}>Save</button>
    </form>
{/each}
```

`for(id)` stringifies the id and reuses instances with the same id, so `pending`, `result` and issues are isolated per row. If the schema has an `id` property of a string or number type, `for()` is typed to accept that type, and the id is **injected into the submitted data** when the schema’s `id` field is not otherwise present: the server-side handler receives `data.id` without you adding a hidden input. Each instance may be attached to only one `<form>`; attaching the same instance (or the same key, including `0`, `false` or `''`) to two elements raises `remote_form_multiple_elements`. Client instances are released shortly after their last use.

## 8.3 The field and form API

Field-level methods (available on leaves and, where meaningful, on containers):

| Method | Meaning |
|------------------------------------|------------------------------------|
| `value()` | current value of the field (a deep partial for containers); `fields.value()` returns the whole object |
| `set(v)` | set the value programmatically (marks touched and dirty); `fields.set({...})` sets many |
| `issues()` | issues belonging to this field, or `undefined` if valid or not yet validated |
| `allIssues()` | (containers and root) issues for this field and everything under it; `fields.allIssues()` is every issue, including form-level string issues |
| `touched()` | the field or any nested field has been interacted with (focused out) |
| `dirty()` | the field or any nested field has been edited |

Form-level members:

| Member | Meaning |
|------------------------------------|------------------------------------|
| `result` | the handler’s return value from the latest successful submission; ephemeral |
| `pending` | number of submissions in flight (a number, not a boolean: use `!!f.pending`) |
| `submitted` | submitted at least once since mount or reset |
| `element` | the attached `<form>` or `null` |
| `submit()` | submit programmatically; returns `Promise<boolean>` (valid or not) with `.updates(...)` |
| `enhance(cb)` | replace the default submit behaviour (section 8.5) |
| `preflight(schema)` | client-side validation schema |
| `validate(options?)` | run validation now |
| `for(id)` | per-id instance |
| `fields` | the field tree |

### `validate` and its option names: docs versus types

The documentation page for remote functions says to pass `validate({ includeUntouched: true })` to show issues for fields the user has not touched. That is stale. `includeUntouched` was renamed to `all` in a 2.x release (the changelog records “experimental remote form `validate({ includeUntouched })` option is now `all`”), and the published type is:

```ts
validate(options?: {
    /** also show issues of fields not yet edited and blurred; ignored once submitted */
    all?: boolean;
    /** run only the preflight schema; skip the server round trip */
    preflightOnly?: boolean;
}): Promise<void>
```

So write `await myForm.validate({ all: true })`. Behaviour to know:

- By default `validate()` hides issues for fields that have not been both edited and blurred (`touched` and `dirty`), so a live `oninput={() => form.validate()}` does not shout at users about fields they have not reached. After the first submit, or with `all: true`, everything is shown. Resetting the form makes it pristine again.
- Without `preflightOnly`, `validate()` makes a **server round trip** with a `validate_only` flag: the server runs the schema (not the handler) and returns the issues. With a preflight schema, client-side issues are computed first; only if they pass does it ask the server. Debounce calls on `input` events; the implementation discards out-of-order responses but cannot make the server cheaper.
- It waits one tick before reading the DOM, so calling `set()` and then `validate()` works.

### Preflight

```html
<script lang="ts">
    import { createPost } from './posts.remote';
    import { postSchema } from './schemas';   // shared module; never exported from a .remote file
</script>

<form {...createPost.preflight(postSchema)}>...</form>
```

A preflight schema is checked in the browser before anything is sent, which saves the round trip for obviously invalid input and populates `issues()` immediately. It is a convenience, not a guarantee: the server always validates. It is typed `StandardSchemaV1<Input, any>`, so reusing the server schema is allowed. Server-side issues (those from the server schema or `invalid()`) survive client validation runs unless a client issue exists for the same path, in which case the client one replaces it; the merged list is ordered by field order in the form. A schema that depends on server-only things (database uniqueness) cannot live in preflight; model those as `invalid(...)` in the handler.

## 8.4 Server-side validation errors: `invalid` and `issue`

The schema covers format rules. Rules you can only evaluate by doing the work (uniqueness, balance, a payment decline) are raised imperatively with `invalid`, from `@sveltejs/kit`. It throws, like `redirect` and `error`, so never swallow it in a `try/catch` without rethrowing (`isValidationError(e)`).

The handler’s second parameter, `issue`, is a typed builder mirroring the input shape:

```ts
// src/routes/signup/signup.remote.ts
import * as v from 'valibot';
import { invalid, redirect } from '@sveltejs/kit';
import { form, getRequestEvent } from '$app/server';
import { createUser, EmailTaken, WeakPassword } from '#lib/server/users.js';

export const signup = form(
    v.object({
        email: v.pipe(v.string(), v.email()),
        _password: v.pipe(v.string(), v.minLength(12)),
        address: v.object({ postcode: v.string() })
    }),
    async ({ email, _password, address }, issue) => {
        try {
            const user = await createUser(email, _password, address.postcode);
            const { cookies, locals } = getRequestEvent();
            cookies.set('session', user.sessionId, { path: '/', maxAge: 60 * 60 * 24 * 7 });
            locals.user = user;
        } catch (e) {
            if (e instanceof EmailTaken) invalid(issue.email('That email is already registered'));
            if (e instanceof WeakPassword) invalid(issue._password('Too easy to guess'));
            throw e;
        }
        redirect(303, '/welcome');
    }
);
```

`invalid` accepts any number of arguments: strings (form-level messages, visible through `fields.allIssues()` only) and Standard Schema issues, produced by `issue.field(msg)`, `issue.address.postcode(msg)`, or `issue.items[2].name(msg)`. A field called as a function creates the issue; a property access descends a level. Issues thrown this way flow to the client exactly like schema issues, and the submission counts as unsuccessful: `submit()` resolves to `false`, `result` stays unset, and nothing is refreshed.

Do not return `fail(...)` from a remote form handler. In development it raises `remote_form_fail`, pointing you to `invalid`. The remote form has no equivalent of `fail`’s arbitrary data payload; the supported channels are issues (for validation) and the handler’s return value (for successful results). If you need to send structured information after a business-rule failure, return it as the result and render it from `form.result`.

### Reading issues in the UI

```html
<script lang="ts">
    import { signup } from './signup.remote';
    const { email, _password, address } = signup.fields;
</script>

<form {...signup}>
    <label>Email <input {...email.as('email')} /></label>
    {#each email.issues() ?? [] as issue}<p role="alert">{issue.message}</p>{/each}

    <label>Password <input {..._password.as('password')} /></label>
    {#each _password.issues() ?? [] as issue}<p role="alert">{issue.message}</p>{/each}

    <label>Postcode <input {...address.postcode.as('text')} /></label>

    {#each signup.fields.allIssues() ?? [] as issue}
        {#if issue.path.length === 0}<p role="alert">{issue.message}</p>{/if}
    {/each}
    <button>Sign up</button>
</form>
```

`RemoteFormIssue` is `{ message: string; path: Array<string | number> }`; form-level issues have an empty `path`. Note `aria-invalid` is already set by `as()`, and you should associate messages with inputs (`aria-describedby`) for accessibility.

## 8.5 Results, `enhance` and errors

A handler may return a value. It is available on the client as `form.result` after a successful submission and, after a no-JS submission, during the re-rendered page. It is typed from the handler, and ephemeral: it disappears on resubmission, navigation and reload.

```ts
export const subscribe = form(v.object({ email: v.pipe(v.string(), v.email()) }), async ({ email }) => {
    const outcome = await mailing.subscribe(email);
    return { outcome } as const; // 'subscribed' | 'already-subscribed'
});
```

```html
{#if subscribe.result?.outcome === 'already-subscribed'}<p>You were already on the list.</p>{/if}
```

The default client behaviour after success is: reset the DOM form (`HTMLFormElement.prototype.reset`, called from the prototype to avoid DOM clobbering by an input named `reset`). When you override the behaviour with `enhance`, **nothing is reset automatically**; you call `form.element.reset()` yourself. The callback receives a copy of the form instance (type `RemoteFormEnhanceInstance`) with every property except `enhance`, `element` is always defined, and `submit()` performs the submission without re-entering your callback:

```html
<form
    {...addTodo.enhance(async (form) => {
        try {
            const ok = await form.submit();          // false means validation issues
            if (ok) {
                form.element.reset();
                toast('Added');
            }
        } catch (e) {
            toast('Could not reach the server');     // transport/unexpected failures throw
        }
    })}
>
```

Exceptions thrown from `submit()` are the unexpected-error channel (network failure, 5xx, handler throws). If you catch them in your callback, the nearest-`+error.svelte` rendering does not happen; if you let them escape, the attachment routes them to the client `handleError` and shows the error page. Choose deliberately: for a comment box, a toast is friendlier than replacing the page.

Redirects work in forms. `redirect(303, '/blog/new-post')` in the handler produces a redirect envelope; the client calls `goto(location)` and **waits for the navigation to finish before `submit()` resolves** (with `true`). If the handler also called `refresh()`/`set()` before redirecting, those query updates are applied when the redirect arrives, so the destination page renders with them warm. Cookie writes in the handler are applied to the same response.

## 8.6 `command`

A command is a mutation with no form element and no no-JS fallback: a function you call from an event handler, effect, timer or another remote function.

```ts
// src/routes/items/likes.remote.ts
import * as v from 'valibot';
import { command, query } from '$app/server';
import * as db from '#lib/server/db.js';
import { requireUser } from '#lib/server/auth.js';

export const getLikes = query(v.string(), async (id) => db.likeCount(id));

export const toggleLike = command(v.string(), async (id) => {
    const user = requireUser();
    return db.toggleLike(user.id, id); // returns { liked: boolean, count: number }
});
```

```html
<script lang="ts">
    import { getLikes, toggleLike } from './likes.remote';
    let { id }: { id: string } = $props();
    let failed = $state(false);

    async function onclick() {
        failed = false;
        try {
            const { count } = await toggleLike(id).updates(getLikes(id).withOverride((n) => n + 1));
            // count is authoritative
        } catch {
            failed = true;
        }
    }
</script>

<button {onclick} disabled={!!toggleLike.pending}>Like ({await getLikes(id)})</button>
```

What commands are, and are not:

- **Method.** Commands are `POST`s with a JSON body `{ payload, refreshes }`. Calling one from a read-only HTTP context (a `GET` handler, a `load` function) raises `remote_command_method`; from inside a query or prerender, `remote_command_readonly`; during SSR rendering, `remote_command_render`. Commands are strictly for user-initiated or event-driven mutation.
- **No redirects.** A `redirect()` inside a command raises `remote_command_redirect` on the client. Return the destination in the result and `goto` it yourself after the `await`.
- **No automatic invalidation.** Unlike `form`, a command does nothing to your data unless you tell it to (section 8.7). This is the main way commands under-invalidate and leave stale UI.
- **Files.** Commands accept `File` arguments (since 2.64), not only forms.
- **Cookies** can be written; headers cannot.
- **`pending`** is a count on the command function (`toggleLike.pending`).
- **Validation.** Arguments need a schema exactly as for queries.

The docs’ guidance is to prefer `form` whenever the interaction is a submission, because only forms degrade gracefully. Use `command` for toggles (like/follow), drag-and-drop reordering, “mark as read” on scroll, buttons in menus, and anywhere there is no natural `<form>`. If you find yourself wrapping an `<input>` and a button to call a command with their values, you have recreated a form without validation display, preflight or the no-JS path.

A command is also an HTTP endpoint without CSRF tokens. The protection is the `Origin` check (same-origin only, `trustedOrigins` not honoured) and your authorisation inside the handler. Make commands that can be repeated by accident (double-clicks, retries after a network blip) **idempotent** or guard them with the `pending` count.

## 8.7 Default invalidation versus explicit refreshes

What happens to the rest of the page after a mutation succeeds is decided like this:

| Mutation | Default |
|------------------------------------|------------------------------------|
| `form`, success | `refreshAll()`: every active query is refetched and every load function that can rerun does so (a full page-reload emulation) |
| `form`, validation failure | nothing |
| `command` | nothing |
| either, handler called `refresh()`, `set()` or `reconnect()` | only those queries, delivered in the same response |
| either, caller used `.updates(...)` (even with no arguments) | only what was requested, subject to the handler’s `requested()` |

The server-driven form lets the handler name what changed:

```ts
export const addTodo = form(schema, async ({ text }) => {
    const user = requireUser();
    const todo = await db.insertTodo(user.id, text);

    void getTodos().refresh();       // refetch on the server, ship the result with this response
    getTodo(todo.id).set(todo);      // we already have the row: seed the cache, no refetch
});
```

Semantics, taken from the implementation:

- `refresh()` and `set()` on the server return immediately; `void` the promise. The framework awaits all of them before sending the response, and forwards their errors to the client as per-query errors.
- The refresh is **deferred**: the query function is stored and executed at the end of the request, after the handler body, so it observes your writes regardless of the order in which you called `refresh()`. If you await the same query in the handler after refreshing, the existing cache entry is reused rather than running it twice.
- The key is the function id plus the serialised argument, so `getTodo(todo.id).set(...)` updates exactly the client instance with that argument. Instances with other arguments are not touched; this is the origin of the next section.
- Any explicit `refresh`, `set` or `reconnect` call **replaces** the default `refreshAll`. If you refresh one query, no other query or load function is invalidated. Load functions are not queries, so a page that mixes `load` data and queries must either refresh both explicitly or accept stale `load` data. Where you also need a load function to rerun, call `refreshAll()` on the client after the submission.
- Live queries use `reconnect()` for the same purpose (Chapter 7), for example after a command changes a cookie the generator closed over.
- For native (no-JS) submissions there is no client cache to patch, so explicit `refresh()` is a no-op there and the page simply re-renders.

## 8.8 Client-requested single-flight updates

Server-driven refreshes break down when the server cannot know *which instances* are on screen. If the client shows `getPosts({ filter: 'author:santa' })` and `getPosts({ filter: 'recent' })`, what should `createPost` refresh? Enumerating filters on the server is impossible in general, so the **client** names the instances in the same request:

```ts
await createPost.submit().updates(                // or toggleLike(id).updates(...)
    getPosts,                                      // all active instances of getPosts
    getPosts({ filter: 'author:santa' }),          // one specific instance
    getPosts({ filter: 'recent' }).withOverride((posts) => [draft, ...posts]) // optimistic
);
```

`.updates(...)` accepts query functions (all active instances), query resources (one instance), live queries and their functions, and override release functions. Anything else raises `remote_updates_invalid_argument`. Calling `.updates()` more than once per invocation logs a warning and the extras are ignored. Passing **no arguments** is meaningful: it opts out of automatic invalidation entirely (“update nothing”).

The request carries the requested keys (`refreshes`) to the server, which accepts them only if the handler asks:

```ts
import { requested } from '$app/server';

export const createPost = form(postSchema, async (data) => {
    const post = await db.insertPost(data);

    // refresh up to 10 requested instances of getPosts, ignoring the rest
    for (const { arg, query, ignore } of requested(getPosts, 10)) {
        if (arg.filter === 'recent' || arg.filter === `author:${post.author}`) {
            void query.refresh();
        } else {
            ignore();
        }
    }

    await requested(getStats, 1).refreshAll(); // shorthand: refresh everything requested
});
```

`requested(queryFn, limit)` returns an iterable of entries:

- `arg` is the **validated** argument (the schema output), so with a transforming schema it differs from what the client passed.
- `query` is a query resource **bound to the client’s original cache key**, so `refresh()` or `set()` updates the right client instance even when the schema transforms the input.
- `ignore()` declares that you deliberately do not update this one.

The result also has `refreshAll()` (refresh every selected entry; use `reconnectAll()` for live queries; `refreshAll` on a live query throws `remote_requested_wrong_method`) and `ignoreAll()`. `requested` is only available inside `form` and `command` handlers (`remote_requested_context` otherwise), and the first argument must be a query *function* created by `query`, `query.batch` or `query.live`, not a resource.

### The `limit` and why it is mandatory

The list of requested keys is attacker-controlled. Each entry costs a validation and usually a database query, so an unbounded list is a denial-of-service vector: one POST could ask the server to refresh ten thousand argument combinations. `limit` caps the work: entries beyond it are skipped, and their client instances fail with an error. Pick the worst case you are willing to serve per mutation; `Infinity` is allowed and discouraged. `ignoreAll()` only ignores entries within the limit, so excess ones still fail. Non-integer or negative limits throw `remote_requested_invalid_limit`.

This is also why `requested` is opt-in per query. The docs give two reasons: a command that could implicitly refresh any query would drag every query’s code into its server bundle, and the only defence against a client asking for arbitrary refreshes is that the handler names the queries it is willing to refresh, with a limit.

### SvelteKit 3 strictness

In SvelteKit 3, **every requested update must be accounted for**. For each entry the client asked for, the handler must call `refresh()`, `set()`, `reconnect()` (live), or `ignore()`. If it does not, that query enters an error state on the client: the unhandled keys are collected after the response, and any left unconsumed fail with a 400-status error, “Requested update was not handled by the remote function”. Entries that fail validation also error individually, and do not fail the whole mutation. Entries beyond the limit fail the same way. In practice:

- A client that asks for `getPosts` while a handler never calls `requested(getPosts, n)` leaves its `getPosts` instances **in the failed state**, even though the mutation succeeded. Mismatched `.updates(...)` and `requested(...)` calls show up quickly as query errors in development, which is the intent: silent staleness became a loud failure.
- Because validation is asynchronous for many schema libraries, iterate with `for await (const entry of requested(...))` when your schema is async; the synchronous `for...of` throws `remote_requested_async_validator` in that case.

Keep client and server in step. A pragmatic convention: put each mutation’s `requested` calls next to the mutation, and list the query functions in `.updates(...)` at the call site from a small helper so they stay together.

## 8.9 Optimistic UI

`withOverride(fn)` (Chapter 7) layers a temporary transformation over a query’s value. Combined with `.updates(...)`, the override is applied immediately and **released automatically when the mutation settles**, whether it succeeds or fails, at which point the real data (refreshed in the same response) takes over:

```html
<script lang="ts">
    import { getTodos, toggleTodo } from './todos.remote';
    const todos = getTodos();
</script>

{#each await todos as todo (todo.id)}
    <label class:pending={toggleTodo.pending}>
        <input
            type="checkbox"
            checked={todo.done}
            onchange={async (e) => {
                const done = e.currentTarget.checked;
                try {
                    await toggleTodo({ id: todo.id, done }).updates(
                        todos.withOverride((list) =>
                            list.map((t) => (t.id === todo.id ? { ...t, done } : t))
                        )
                    );
                } catch {
                    toast('Could not update');   // override already released: UI snaps back
                }
            }}
        />
        {todo.text}
    </label>
{/each}
```

```ts
// todos.remote.ts
export const toggleTodo = command(v.object({ id: v.string(), done: v.boolean() }), async ({ id, done }) => {
    await db.setDone(requireUser().id, id, done);
    await requested(getTodos, 1).refreshAll();
});
```

Points that matter:

- At most one override per query instance per `updates()` call; two raise `remote_updates_duplicate_override`. Fold changes into one function. Different arguments are different instances and may each have an override.
- An override must be pure and cheap: it is re-reduced whenever the underlying value or the override stack changes.
- Because the real data arrives in the **same response** as the mutation result, there is no flicker between releasing the override and showing the server’s value.
- On failure the override is released in a `finally`, so the UI reverts on its own; your job is only to tell the user.
- For a form, the same works through `enhance`: `await form.submit().updates(todos.withOverride((l) => [...l, { text: form.fields.text.value() }]))`.

## 8.10 Security checklist for mutations

- **Authenticate and authorise inside the handler**, not by route. For forms and commands, `event.url`, `route` and `params` come from client headers; never base permissions on them (Chapter 14). Re-check ownership of the resource named by an id argument.
- Validation is your input boundary: use real schemas, bound string lengths and array sizes, and cap file sizes (`v.pipe(v.file(), v.maxSize(...))`). Streaming uploads mean the handler can reject early, but the platform body limit still applies (Chapter 18).
- Same-origin enforcement for non-`GET` remote calls is automatic and cannot be relaxed with `trustedOrigins`; do not expose remote functions as a public API (use `+server.ts` for that).
- `requested()` limits bound client-controlled work. Treat `Infinity` as a code-review flag.
- Rate-limit by user or IP in `handle` or in the handler; remote endpoints are normal requests through `handle` (Chapter 9).
- Do not return secrets in results: results go to the client. Use `_`-prefixed field names for sensitive inputs.
- Cookie writes require an absolute `path`; relative paths raise `remote_cookie_path_relative`.

## 8.11 From actions to remote forms

A step-by-step migration for one page, keeping the app shippable at each step:

1.  **Enable the flags** and move on only after the app builds; mixed pages are fine.
2.  **Extract the schema** from the action into a shared module (`schemas.ts`), since a `.remote` file cannot export it.
3.  **Create the remote form** next to the data: `form(schema, handler)`. The handler receives *validated, typed* data instead of `FormData`; delete the manual narrowing.
4.  **Translate outcomes.**

| Action | Remote form |
|------------------------------------|------------------------------------|
| `return fail(422, { errors })` | `invalid(issue.field('...'))`, or let the schema produce issues |
| `return { success: true }` | return a value; read `form.result` |
| `redirect(303, ...)` | same |
| `error(...)` / throw | same: nearest `+error.svelte` |
| `form` prop / `page.form` | `myForm.result`, `myForm.fields.*.issues()`, `.value()` |
| `use:enhance` callback with `update()` | `myForm.enhance(async (form) => {...})` and `form.submit()` |
| `update({ reset: false })` | simply do not call `form.element.reset()` |
| `update({ refreshAll: false })` | `refresh()`/`set()` in the handler, or `.updates()` |
| `name="email"` | `{...f.fields.email.as('email')}` (names are generated) |
| multiple buttons with `formaction` | a field with `as('submit', value)` |
| `locals` update after cookie change | same requirement; do both in the handler |

5.  **Redo the markup**: `<form {...myForm}>`, controls from `.as(...)`, issues from `.issues()`. Remove `method`/`action` attributes (they come from the spread).
6.  **Decide invalidation.** Where the action relied on `load` re-running, the default `refreshAll()` still does that for forms. If you narrow it with explicit refreshes, remember that load functions are not covered.
7.  **Delete the action** once the page uses only the remote form. Tests that posted `?/name` with `FormData` must now post through the browser or the generated endpoint; end-to-end tests with Playwright are the least brittle option.

Pitfalls specific to this migration: the action’s `fail` data payload has no analogue, so redesign messages as issues; `FormData` keys no longer match markup names; and a remote form’s `result` is typed from the handler, so returning different shapes in different branches produces a union you must narrow. Actions and remote forms can coexist on one page indefinitely; the main cost of keeping both is cognitive, not technical.

### Choosing between the pieces

| Situation | Use |
|------------------------------------|------------------------------------|
| User submits a set of fields, with validation and a no-JS fallback | `form` |
| Toggle, drag, menu item, programmatic mutation | `command` |
| Stable, battle-tested, page-scoped flow, or you cannot enable experimental flags | form actions (Chapter 6) |
| A mutation that should refresh a known set of queries | server-driven `refresh()`/`set()` |
| A mutation whose affected query instances depend on what is on screen | `.updates(...)` + `requested(...)` |
| Instant feedback before the server answers | `withOverride` in `.updates(...)` |
| A public, versioned HTTP API for third parties | `+server.ts`, not remote functions |

## Key takeaways

- `form(schema, handler)` returns an object to spread on `<form>`: `method`, `action` (`?/remote=<id>`), and an attachment for progressive enhancement. Without JS it posts to the page and re-renders; with JS it posts to the remote endpoint using a streaming binary encoding.
- Field names are generated by `.as(...)` and encode path, coercion type and form id; hand-written names are rejected in SvelteKit 3. Booleans and arrays need defaults in the schema; hidden/submit/radio values are mandatory arguments; `_`-prefixed fields are never echoed.
- `validate` takes `{ all?, preflightOnly? }` in the published types; the docs’ `includeUntouched` is outdated. `validate()` hits the server unless `preflightOnly`.
- Server-only validation uses `invalid(...)` with the typed `issue` builder; `fail` is wrong in remote forms. Unexpected errors render the nearest `+error.svelte` unless you catch them in `enhance`.
- `enhance(cb)` replaces default submit behaviour: no automatic reset, `form.submit()` returns whether the data was valid, and redirects wait for navigation.
- `command` is a mutation without a form: no redirects, no render-time calls, no automatic invalidation, accepts `File`s. Prefer `form` for submissions.
- Default after a successful form: `refreshAll()`. Any explicit `refresh`/`set`/`reconnect` in the handler replaces that. Refreshes run deferred at the end of the request and ride the same response.
- Client-requested updates (`.updates(...)`) need the server to opt in with `requested(query, limit)`; the limit bounds client-controlled work. In 3.x every requested entry must be refreshed, set, reconnected or ignored or that query errors on the client.
- `withOverride` in `.updates(...)` gives optimistic UI that is released automatically when the mutation settles, success or failure.
- Authorise in the handler; `url`, `route`, `params` in forms and commands are client-supplied. Same-origin enforcement for remote calls ignores `csrf.trustedOrigins`.

## Review Questions

1.  List the three things `{...myForm}` contributes to a `<form>` element and what each does with and without JavaScript.
2.  What is the `action` URL of a remote form, and which server component handles a native `POST` to it?
3.  Why does `<input name="title">` fail in a remote form in SvelteKit 3? What does the generated name for a number field look like?
4.  Find the bug: a schema contains `agree: v.boolean()` and the form renders `<input {...f.fields.agree.as('checkbox')} />`. What happens at the type level and at runtime if it compiled?
5.  How do you make a `select multiple` field that may be empty work with the schema?
6.  What does the leading underscore in `_password` do, and when does it matter?
7.  The docs show `validate({ includeUntouched: true })`; the types declare something else. What is the correct option and what does it do? What does `preflightOnly` do?
8.  A form calls `form.validate()` on every `oninput`. List two costs and two mitigations.
9.  Write the line that fails the submission with a message on the `address.postcode` field, from inside a handler whose second parameter is named `issue`.
10. What happens in development if a remote form handler `return fail(400, ...)`? What should it do instead?
11. What is the difference between `fields.allIssues()` and `fields.email.issues()`? Which one shows string arguments passed to `invalid`?
12. In an `enhance` callback, what does `await form.submit()` resolve to when the server found validation issues? Does an exception get thrown?
13. After overriding behaviour with `enhance`, the form no longer clears itself after success. Why, and what do you call?
14. A handler calls `redirect(303, '/done')` after `void getTodos().refresh()`. What does the client do, and when does `submit()` resolve?
15. Why can a command not redirect, and how do you navigate after one?
16. Multiple choice: which is **not** true of `command`?

    a.  it accepts `File` arguments
    b.  it automatically refreshes all queries on success
    c.  it can set cookies
    d.  it cannot be called during server-side rendering
17. What does a successful `form` submission invalidate by default? What does a successful `command` invalidate?
18. A form handler calls `getPosts().refresh()` only. A `load` function on the same page provides `user`. Is the `load` function re-run after the submission? Why or why not?
19. Why is the query refresh deferred to the end of the request on the server, and what does that guarantee?
20. `getTodo(id).set(todo)` in a handler: which client instances does it update? Which does it not?
21. Write the client call that refreshes all active `getPosts` instances and one specific `getStats({ range: '7d' })` instance in the same request as `createPost`.
22. The handler for that call never invokes `requested(getPosts, ...)`. What happens to the client’s `getPosts` instances in SvelteKit 3?
23. Explain why `requested` requires a `limit`. What happens to entries beyond it? What does `ignoreAll()` do about excess entries?
24. What is `arg` in a `requested` entry when the query’s schema is `v.pipe(v.string(), v.transform(Number))`, and why does `query` remain bound to the client’s original key?
25. Predict the result: `await submit().updates()` (no arguments). How does it differ from `await submit()`?
26. Two `withOverride` results for the same query instance are passed to one `.updates(...)` call. What happens?
27. In an optimistic toggle, the command throws. What is the state of the UI afterwards, and who put it there?
28. Design: a kanban board shows `getCards({ board, column })` for four columns. Moving a card is a command. Sketch the client `updates` call and the server `requested` loop, including limit choice and the optimistic move.
29. Why must authorisation not use `event.url.pathname` inside a `form` handler?
30. List five rows of an actions-to-remote-form translation table.
