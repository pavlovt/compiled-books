# Chapter 11: Actions

Astro Actions are the framework’s answer to a question every server-rendered application eventually asks: how do I let the browser call my backend without hand-writing an endpoint, a `fetch()` wrapper, a validator and an error format for every mutation? An action is a typed server function that you define once in `src/actions/index.ts` and call from anywhere: a Svelte 5 island, a `<script>` tag, a plain HTML `<form>` with JavaScript disabled, or other server code. Astro generates the route, parses the body, validates it with Zod, serializes the result with devalue and gives you back a discriminated `{ data, error }` result.

This chapter treats actions as what they really are: a thin, opinionated RPC layer over ordinary HTTP `POST` requests. That framing matters for senior work, because the places actions go wrong in production (authorization, CSRF, body limits, error leakage, double submits, results that vanish on refresh) are all places where the HTTP reality shows through the abstraction. We will define actions, call them from Svelte islands and forms, handle errors, intercept them in middleware with `getActionContext()`, implement a post/redirect/get flow backed by sessions, and finish with the security model. Everything here was verified against Astro 7.4.1 with `@astrojs/svelte` 9.1.0 and the Node adapter; where the documentation is silent and I tested behaviour, I say so.

> **Note:** Actions require an adapter for anything that runs at request time. The RPC endpoint `/_actions/*` is on-demand, and HTML form submission additionally requires the *page that receives the form* to be on-demand rendered. Sessions (used in several examples) are covered in Chapter 12; middleware in Chapter 10.

## The mental model

An action definition is three things: an optional `accept` (`'json'` by default, or `'form'`), an optional Zod `input` schema, and a `handler(input, context)`. Astro collects every action reachable from the `server` object exported by `src/actions/index.ts` and exposes it in two ways.

1.  **RPC.** A `POST` to `/_actions/<name>` (with dots for nested names, for example `/_actions/user.create`). The generated client in `astro:actions` builds this request for you, sends JSON (or `FormData` if you pass one), and deserializes the response.
2.  **Form.** A `POST` to *any page route* with `?_action=<name>` in the query string. This is what `<form method="POST" action={actions.subscribe}>` produces. The action runs on the server, its result is stashed on the request, and the page renders with that result available through `Astro.getActionResult()`.

Two constants name the form-mode query parameters: `ACTION_QUERY_PARAMS.actionName` (`_action`) and `ACTION_QUERY_PARAMS.actionPayload` (`_astroActionPayload`). You rarely touch them, except when cleaning URLs after a redirect.

The call sequence for an RPC request, as implemented in 7.4.1:

1.  The request reaches the built-in pipeline. Actions run *after* your middleware (your `onRequest` sees action requests) and *before* page dispatch (see Chapter 5 for the built-in order).
2.  The handler rejects invalid percent-encoding, skips prerendered routes, and applies the origin check (described later) if `security.checkOrigin` is enabled.
3.  The body is parsed, with a size limit, as JSON or `FormData` depending on `Content-Type`.
4.  The action is looked up by name; unknown names produce a `NOT_FOUND` action error.
5.  The input is validated, the handler runs with a *clone* of the request context, and the result is serialized: `application/json+devalue` for data, plain JSON for errors, an empty body for `undefined`.

Because the serialization is devalue, a handler may return `Date`, `Map`, `Set`, `URL` and friends. A real response from the test project, for an action that returns `{ count: 1, at: new Date() }`:

```text
HTTP/1.1 200 OK
content-type: application/json+devalue

[{"count":1,"at":2},1,["Date","2026-10-19T20:40:19.676Z"]]
```

That is why you cannot casually `curl` and read an action response as JSON, and why the client function, not `fetch()`, is the supported way to call actions (we will see the escape hatch, `getActionPath()`, later).

## Defining actions

### The basic shape

```ts
// src/actions/index.ts
import { defineAction, ActionError } from 'astro:actions';
import { z } from 'astro/zod';

export const server = {
  addToCart: defineAction({
    input: z.object({
      sku: z.string().min(1),
      qty: z.number().int().positive().default(1),
    }),
    handler: async (input, ctx) => {
      const cart = (await ctx.session?.get('cart')) ?? [];
      for (let i = 0; i < input.qty; i++) cart.push(input.sku);
      ctx.session?.set('cart', cart);
      return { count: cart.length, at: new Date() };
    },
  }),
};
```

Import `z` from `astro/zod`. Importing it from `astro:content` or `astro:schema` is deprecated since 6.0 (Zod 4 is the baseline; see Chapter 6). The input type of the handler is `z.output` of the schema, so `qty` is `number` (not `number | undefined`) because of `.default(1)`.

`handler` receives two arguments: the validated input and an `ActionAPIContext`. That context is a clone of the request’s `APIContext` with four properties removed: `props`, `getActionResult`, `callAction` and `redirect`. Everything else is there: `request`, `url`, `params`, `cookies`, `locals`, `session`, `clientAddress`, `site`, `cache`, `logger`, and so on. Two consequences worth internalizing:

- There is no `redirect()` in an action. An action returns data, and the *caller* decides to navigate. On the server side (form mode) that happens in the page or middleware; in an island it happens with `navigate()` or a router. If you return a `Response` from a handler, Astro throws an `ActionsReturnedInvalidDataError` and hints that you want an endpoint instead.
- Because the context is a clone, assignments like `ctx.someProperty = x` do not leak back to the request. Mutate shared state through `locals` objects, `cookies` and `session`, which are references.

### Organizing actions

Every action must be reachable from the `server` export of `src/actions/index.ts`, but the definitions can live anywhere. Nesting objects creates namespaces:

```ts
// src/actions/cart.ts
import { defineAction } from 'astro:actions';
import { z } from 'astro/zod';

export const cart = {
  add: defineAction({ input: z.object({ sku: z.string() }), handler: async ({ sku }, ctx) => { /* ... */ } }),
  clear: defineAction({ handler: async (_, ctx) => { ctx.session?.delete('cart'); } }),
};
```

```ts
// src/actions/index.ts
import { cart } from './cart';
import { account } from './account';

export const server = { cart, account };
```

You call `actions.cart.add(...)`, and the wire name is `cart.add`, so the endpoint is `/_actions/cart.add`. The client proxy encodes literal dots inside a key as `%2E`, so an action keyed `'v1.2'` does not get confused with nesting.

After adding or renaming actions, types come from `astro sync` (the dev server runs it for you); if `actions` has stale types, restart the dev server or press `s` + Enter.

### `accept: 'json'` versus `accept: 'form'`

`accept` is strict in both directions, which is a feature: an action built for form data rejects a JSON body and vice versa.

```text
POST /_actions/subscribe  Content-Type: application/json   (subscribe has accept: 'form')
-> 415 {"type":"AstroActionError","code":"UNSUPPORTED_MEDIA_TYPE","status":415,
        "message":"This action only accepts FormData."}
```

Choose `'form'` when the action is the target of an HTML form, or when an island hands over a `FormData`. Choose `'json'` for everything else, because JSON input can carry numbers, nested objects and arrays without the `FormData` coercion rules.

### Form input parsing in detail

When `accept: 'form'` and `input` is a `z.object(...)` (possibly wrapped in `.refine()`, `.transform()`, `.pipe()` or a discriminated union), Astro does not hand `FormData` to Zod directly. It first converts the `FormData` to an object by walking the schema, which is why a checkbox can validate as a boolean. Reading the implementation and testing it gives the following precise rules:

| Schema leaf | What Astro does with the form field |
|------------------------------------|------------------------------------|
| `z.number()` | `Number(value)`; empty becomes `null` |
| `z.boolean()` / `z.coerce.boolean()` | field present gives `true`, absent gives `false`; the literal strings `"true"`/`"false"` are honoured |
| `z.array(...)` | `formData.getAll(name)`; numeric or boolean element schemas map each entry |
| `z.instanceof(File)` | passes the `File` through (use `enctype="multipart/form-data"`) |
| nested `z.object(...)` | looks for keys with a `parent.` prefix, so `<input name="address.city">` fills `{ address: { city } }` |
| `.default(v)` | used when the field is absent |
| optional field, empty input | `undefined` |
| any other field, empty input | `null` (not `""`) |
| everything else | the raw string |

That last row is the usual source of confusing errors: an empty required text input arrives as `null`, so `z.string()` reports “expected string, received null”. It is correct, but if you want a friendly message, supply it:

```ts
z.object({
  name: z.string({ error: 'Name is required' }).min(1, { error: 'Name is required' }),
})
```

(Zod 4 uses `{ error }` where Zod 3 used `{ message }`.) And remember `z.coerce.boolean()` is mostly redundant here because Astro already special-cases booleans; it is harmless.

A discriminated union is resolved by reading the discriminator field out of the form first, so one action can accept several shapes:

```ts
changeUser: defineAction({
  accept: 'form',
  input: z.discriminatedUnion('type', [
    z.object({ type: z.literal('create'), name: z.string(), email: z.email() }),
    z.object({ type: z.literal('update'), id: z.number(), name: z.string(), email: z.email() }),
  ]),
  handler: async (input) => {
    if (input.type === 'create') { /* input.id does not exist here */ }
  },
}),
```

If you omit `input` entirely on a form action, the handler receives the raw `FormData`. In the test project an action `raw` doing `[...fd.keys()]` returned `["a","b"]` for `a=1&b=2`. Use that when you need repeated keys with custom semantics, or when you want to stream a large upload yourself (although see the body limit below).

### Input errors and `fields`

A failed validation does not call the handler. It produces an `ActionInputError` whose `code` is `BAD_REQUEST`, carrying the raw Zod `issues` and a `fields` map:

```json
{"type":"AstroActionInputError",
 "issues":[{"origin":"string","code":"too_small","minimum":1,"path":["sku"],"message":"Too small: expected string to have >=1 characters"}],
 "fields":{"sku":["Too small: expected string to have >=1 characters"]}}
```

Be careful with `fields`: it is keyed by `issue.path[0]` only. An error on `address.city` appears under `fields.address`, together with any other issue below `address`. If you need the full path, read `error.issues` (each has a `path` array). Also note that issues for object-level refinements (`.refine()` on the whole object) have an empty path and therefore appear in `issues` but not in `fields`.

## Calling actions

### From a `<script>` tag

In an `.astro` file, a processed `<script>` can import `actions` directly and attach listeners (see Chapter 4 for script bundling and its interaction with `<ClientRouter />`):

```html
---
// src/pages/post.astro
---
<button id="like">Like</button>
<script>
  import { actions } from 'astro:actions';
  document.querySelector('#like')?.addEventListener('click', async () => {
    const { data, error } = await actions.cart.add({ sku: 'sku-1' });
    if (error) console.error(error.code);
  });
</script>
```

### From a Svelte 5 island

Svelte islands import `actions` from `astro:actions` exactly like any other module. Keep the calls inside event handlers (or `$effect`s, which only run in the browser); never at component top level, because the component also renders on the server, where the browser-style client is not what you get. On the server, `actions.x()` throws `ActionCalledFromServerError` unless it is invoked through `Astro.callAction()` (see below).

```html
<!-- src/components/AddToCart.svelte -->
<script lang="ts">
  import { actions, isInputError } from 'astro:actions';

  let { sku }: { sku: string } = $props();

  let pending = $state(false);
  let count = $state<number | null>(null);
  let message = $state('');

  async function add() {
    pending = true;
    message = '';
    const { data, error } = await actions.addToCart({ sku, qty: 1 });
    pending = false;
    if (error) {
      message = isInputError(error)
        ? Object.values(error.fields).flat().join(', ')
        : error.message;
      return;
    }
    count = data.count; // typed: number, because `error` was excluded
  }
</script>

<button onclick={add} disabled={pending}>Add {sku}</button>
{#if count !== null}<span>in cart: {count}</span>{/if}
{#if message}<p role="alert">{message}</p>{/if}
```

```html
---
// src/pages/island.astro
import AddToCart from '../components/AddToCart.svelte';
---
<AddToCart client:load sku="sku-1" />
```

The narrowing works because `SafeResult` is a discriminated union (`{ data, error: undefined } | { data: undefined, error: ActionError }`): after `if (error) return;`, `data` is the handler’s return type. `error` is an `ActionError` instance on the client, with `code`, `status` and `message`. The `isInputError()` type guard narrows it further so `fields` is typed; `isActionError()` narrows an `unknown` to an `ActionError` when you catch an exception from `.orThrow()`.

A form-submitting island follows the same pattern with `FormData`. This component *progressively enhances*: it renders a real `<form method="POST">` pointing at the action, so before hydration (or without JavaScript) a submit goes through the server-side form path; after hydration the `onsubmit` handler intercepts and calls the RPC.

```html
<!-- src/components/Subscribe.svelte -->
<script lang="ts">
  import { actions, isInputError } from 'astro:actions';
  import { navigate } from 'astro:transitions/client';

  let errors = $state<Record<string, string[] | undefined>>({});
  let formError = $state('');

  async function onsubmit(e: SubmitEvent & { currentTarget: HTMLFormElement }) {
    e.preventDefault();
    errors = {};
    formError = '';
    const { error } = await actions.subscribe(new FormData(e.currentTarget));
    if (!error) return navigate('/thanks');
    if (isInputError(error)) errors = error.fields;
    else formError = error.code;
  }
</script>

<form method="POST" action={actions.subscribe.queryString} {onsubmit}>
  <input name="email" type="email" aria-invalid={!!errors.email} />
  {#each errors.email ?? [] as m}<small>{m}</small>{/each}
  <button>Sign up</button>
  {#if formError}<p>{formError}</p>{/if}
</form>
```

I use `actions.subscribe.queryString` (a string, `?_action=subscribe`) for the attribute rather than passing the function. In `.astro` templates `action={actions.subscribe}` works because the function’s `toString()` returns the same string; the explicit property is clearer in a Svelte template and avoids relying on how a framework stringifies a function-valued attribute. I verified that the server-rendered island emits `<form method="POST" action="?_action=subscribe">`.

`navigate()` comes from `astro:transitions/client` and is only meaningful if the page uses `<ClientRouter />`; without it, it falls back to a full navigation (Chapter 14). In a plain island you could equally set `window.location.href`.

**Double submits and pending state.** Actions give you nothing for idempotency. Disable the button while pending (as above) *and* make the handler tolerant: use an idempotency key from the client (`crypto.randomUUID()` generated when the form mounts, sent as an input) and check it server-side, or rely on database unique constraints. The framework will happily run two concurrent handlers.

### `.orThrow()`

Every action also exposes `orThrow()`, which resolves to `data` directly and throws the `ActionError` otherwise. It integrates well with libraries that already manage errors (TanStack Query style, or a Svelte `{#await}` block with `{:catch}`):

```html
<script lang="ts">
  import { actions } from 'astro:actions';
  let promise = $state<Promise<{ count: number }> | null>(null);
</script>

<button onclick={() => (promise = actions.addToCart.orThrow({ sku: 'x' }))}>Add</button>
{#if promise}
  {#await promise}
    <p>Saving...</p>
  {:then r}
    <p>{r.count} items</p>
  {:catch e}
    <p>Failed: {e.code}</p>
  {/await}
{/if}
```

Note a detail from the implementation: `orThrow` is attached as a property of the action function, and the client implementation says explicitly that `orThrow` carries no progressive-enhancement information. It is therefore not something you can put in a form `action` attribute and expect to work without JavaScript.

### Custom `fetch` with `getActionPath()`

`getActionPath(action)` returns the RPC URL (taking `base` and `trailingSlash` into account). Use it when you need something the generated client does not offer: custom headers, `keepalive`, `sendBeacon`, an `AbortSignal`, or a request issued from a service worker.

The helper returns only the URL. `deserializeActionResult` is not exported from `astro:actions`; it is returned by `getActionContext()` on the server. On the client you would parse the devalue payload yourself (with the `devalue` package), so the cleanest use is the fire-and-forget pattern from the reference, where the response is not needed:

```ts
// analytics.ts (client)
import { actions, getActionPath } from 'astro:actions';

export function trackLeave(sku: string) {
  navigator.sendBeacon(
    getActionPath(actions.track),
    new Blob([JSON.stringify({ sku })], { type: 'application/json' }),
  );
}
```

`sendBeacon` ignores the response, so no deserialization is needed. For calls where you need the result *and* custom control, I recommend wrapping the generated client instead of re-implementing the protocol: the wire format (devalue for success, JSON for errors) is an implementation detail that has changed across versions before.

## Errors

### `ActionError` and status codes

Throw `ActionError` from a handler for expected failures. The `code` is an uppercase human-readable HTTP status (`BAD_REQUEST`, `UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `CONTENT_TOO_LARGE`, `TOO_MANY_REQUESTS`, `INTERNAL_SERVER_ERROR`, and the rest of the IANA registry) and determines the HTTP status of the response; `ActionError.codeToStatus(code)` and `ActionError.statusToCode(status)` convert both ways.

```ts
import { defineAction, ActionError } from 'astro:actions';
import { z } from 'astro/zod';

export const server = {
  placeOrder: defineAction({
    input: z.object({ cartId: z.string().uuid() }),
    handler: async ({ cartId }, ctx) => {
      if (!ctx.locals.user) {
        throw new ActionError({ code: 'UNAUTHORIZED', message: 'Sign in to check out.' });
      }
      const order = await db.orders.create(cartId, ctx.locals.user.id);
      if (!order) throw new ActionError({ code: 'CONFLICT', message: 'Cart already ordered.' });
      return order.id;
    },
  }),
};
```

What happens to errors that are *not* `ActionError`s? This is a sharp edge worth testing in your own project. `callSafely` in the runtime wraps *every* exception thrown by the handler: an `ActionError` is returned as is, and any other `Error` is converted into a new `ActionError` with code `INTERNAL_SERVER_ERROR` **and the original `error.message`**. I verified it with a handler that does `throw new Error('db password rejected')`:

```text
HTTP/1.1 500 Internal Server Error
{"type":"AstroActionError","code":"INTERNAL_SERVER_ERROR","status":500,"message":"db password rejected"}
```

The server log showed nothing for this request, so the failure was neither logged nor hidden. The consequences are practical: never let driver or ORM exceptions escape a handler. Catch them, log the details with `ctx.logger`, and throw an `ActionError` with a stable, user-safe message:

```ts
handler: async (input, ctx) => {
  try {
    return await db.orders.create(input);
  } catch (err) {
    ctx.logger.error(`placeOrder failed: ${err instanceof Error ? err.message : String(err)}`);
    throw new ActionError({ code: 'INTERNAL_SERVER_ERROR', message: 'Could not place the order.' });
  }
},
```

A reusable wrapper that applies this to every action is a worthwhile five lines in any serious project.

### Status codes on form-mode responses

In form mode the *page* is re-rendered with the result, and in 7.4.1 the page response carries the error’s status. Posting an invalid email to `/?_action=subscribe` returned `HTTP/1.1 400 AstroActionInputError`, and a thrown `CONFLICT` returned `409 AstroActionError`, both with the full HTML of the page. Proxies, CDNs and monitoring will count them as errors, which is usually what you want, but be aware if you build a form flow in which validation failures are routine: you may prefer to catch them in middleware and redirect (next section) so that the user ends on a `200`.

## Form actions and progressive enhancement

An HTML form posting to an action needs no client JavaScript. The page that contains the form must be on-demand rendered; on a prerendered page the `?_action` query is simply ignored by the static host.

```html
---
// src/pages/subscribe.astro
export const prerender = false; // not needed with output: 'server'
import { actions, isInputError } from 'astro:actions';

const result = Astro.getActionResult(actions.subscribe);
const fieldErrors = isInputError(result?.error) ? result.error.fields : {};
---
<form method="POST" action={actions.subscribe}>
  <label>
    E-mail
    <input name="email" type="email" required aria-describedby="email-err" />
  </label>
  {fieldErrors.email && <p id="email-err">{fieldErrors.email.join(', ')}</p>}
  <button>Sign up</button>
</form>
{result?.data && <p>Subscribed {result.data.email}</p>}
```

`Astro.getActionResult(action)` returns `undefined` unless *that specific action* was submitted in this request. Under the hood it compares the action’s `queryString` with the stored payload name, so forms for different actions on the same page do not see each other’s results. It returns the same `{ data, error }` shape, with errors reconstructed as `ActionError`/`ActionInputError` instances.

Two honest limitations of this basic flow:

1.  **Refresh resubmits.** The result is the response to a `POST`. If the user refreshes, the browser asks to resubmit the form, and once they navigate away and back the result is gone.
2.  **Inputs reset.** The re-rendered page has empty inputs. You can re-populate them from `Astro.request.formData()` (careful: the body is consumed by the action path, so clone discipline matters) or, when `<ClientRouter />` is on, use `transition:persist` on the inputs (Chapter 14).

Both are solved by the standard remedy, post/redirect/get, which Astro does not do for you but gives you the tools to implement.

### Redirect on success (page-level)

For “create then show it”, handle the result in the page frontmatter and return a redirect:

```html
---
// src/pages/products/create.astro
import { actions } from 'astro:actions';

const result = Astro.getActionResult(actions.createProduct);
if (result && !result.error) {
  return Astro.redirect(`/products/${result.data.id}`, 303);
}
---
<form method="POST" action={actions.createProduct}><!-- ... --></form>
```

Pass `303 See Other` explicitly: the default redirect status is `302`, which most browsers also convert to `GET` after a `POST`, but `303` states the intent unambiguously.

### Post/redirect/get with session-backed results

To persist results across the redirect, intercept form-mode actions in middleware with `getActionContext()`. It returns `{ action, setActionResult, serializeActionResult, deserializeActionResult }`:

- `action` is `undefined` unless this request is a `POST` calling an action (either `rpc` or `form`) *and* nobody has already set a result. It has `calledFrom` (`'rpc' | 'form'`), `name`, and `handler()`, which runs the action and returns a `SafeResult`.
- `serializeActionResult(result)` converts a `SafeResult` (including `Date`/`Map` payloads and error instances) into JSON-safe form.
- `setActionResult(name, serialized)` stores the result so that a later `Astro.getActionResult()` returns it. Calling it also disables Astro’s own handling of the action for this request.

The official guide demonstrates this with Netlify Blobs. Since you already have sessions (Chapter 12), the same flow is simpler: use the session as a “flash” store. This is the version I tested end to end:

```ts
// src/middleware.ts
import { defineMiddleware } from 'astro:middleware';
import { getActionContext } from 'astro:actions';

export const onRequest = defineMiddleware(async (context, next) => {
  if (context.isPrerendered) return next();
  const { action, setActionResult, serializeActionResult } = getActionContext(context);

  // 1. Second leg of PRG: replay the stored result once.
  const flash = await context.session?.get('flash');
  if (flash) {
    context.session?.delete('flash');
    setActionResult(flash.name, flash.result);
    return next();
  }

  // 2. First leg: run the action, store the result, redirect.
  if (action?.calledFrom === 'form') {
    const result = await action.handler();
    context.session?.set('flash', {
      name: action.name,
      result: serializeActionResult(result),
    });
    if (result.error) {
      return context.redirect(context.request.headers.get('Referer') ?? context.originPathname, 303);
    }
    return context.redirect('/?done=1', 303);
  }

  return next();
});
```

With `App.SessionData` extended with `flash: { name: string; result: unknown }`, this type-checks. Observed behaviour: the bad form post returned `303` with `Location: /`; the following `GET /` rendered the page with the validation error and the result was consumed (a third request showed an empty `<pre>`). Three caveats from the test:

- The error result still renders with the error’s HTTP status (400) on the replay `GET`, because the page response status follows the action result. If that matters, set `Astro.response.status = 200` in the page when the flash replay is in effect.
- `RPC` requests are untouched: `calledFrom === 'rpc'` skips the block. Only `form` is converted.
- The flash lookup does a session read on *every* request, including assets served through SSR. Guard it by method (`context.request.method === 'GET'`), or by route, to avoid needless storage reads. Better still, read the flash only where forms live.

Also guard against using the session when it is `undefined` (no driver, `session: false`, or a prerendered route): optional chaining, as shown, degrades to “no flash”.

### Gating actions in middleware

`getActionContext()` is also the right hook for cross-cutting checks (authentication, maintenance mode, rate limiting):

```ts
import { defineMiddleware } from 'astro:middleware';
import { getActionContext } from 'astro:actions';

export const onRequest = defineMiddleware(async (context, next) => {
  const { action } = getActionContext(context);
  if (action?.calledFrom === 'rpc' && action.name.startsWith('admin.')) {
    if (!context.locals.user?.isAdmin) {
      return new Response('Forbidden', { status: 403 });
    }
  }
  return next();
});
```

Treat this as a coarse outer gate. The official guidance, which I endorse, is to authorize inside the handler as well, because per-action permission and per-action rate limits belong with the action, and because a rename or a new action can silently bypass a prefix rule. The doc caution on `url.pathname` matching (Chapter 5) applies here too: `action.name` is parsed from the path with a percent-decoding step; compare against the *known set* of action names, not clever string patterns, and prefer deny-by-default.

Cookies set through `context.cookies`, including the session cookie, are applied to RPC responses just as to page responses; in the test project the first `addToCart` call returned a `Set-Cookie: astro-session=...` header.

## Calling actions from server code

Pages, endpoints and middleware can reuse an action’s logic through `callAction`, which binds the current context so session, locals and cookies work:

```html
---
import { actions } from 'astro:actions';

const q = Astro.url.searchParams.get('q');
if (q) {
  const { data, error } = await Astro.callAction(actions.findProduct, { query: q });
}
---
```

In endpoints and middleware it is `context.callAction(...)`. Calling `actions.findProduct(...)` directly from server code, without the wrapper, throws `ActionCalledFromServerError` (“Action called from a server-rendered page or endpoint without using `Astro.callAction()`”). Remember `ActionAPIContext` itself has no `callAction`, so one action cannot call another through `ctx`; extract the shared logic into a plain function that both handlers import.

The inverse also matters. Since actions are defined with validation and authorization inside the handler, *calling them from server code runs the same checks*. That is a good property when you want one code path, and a performance cost if you only need an unchecked internal read. For internal data access, call your data layer directly.

## Security model

An action is a public HTTP endpoint. The documentation says so in its first line of the security section, and everything else follows.

### Authorization

Every action that touches private data or mutates state must authorize in the handler. `ctx.locals` is where middleware puts the authenticated user (typed via `App.Locals` in `src/env.d.ts`, Chapter 10). Return `UNAUTHORIZED` (not authenticated) or `FORBIDDEN` (authenticated but not allowed) as appropriate, and apply *object-level* checks too: “the user is logged in” does not mean “the user owns order 17”.

### Same-origin protection

Astro’s `security.checkOrigin` (default `true`, Chapter 16) rejects cross-site form-like submissions. Reading the 7.4.1 implementation clarifies exactly what it covers, which is narrower than “all unsafe requests”:

- Safe methods (`GET`, `HEAD`, `OPTIONS`) and prerendered routes are never checked.
- Only requests whose `Content-Type` is form-like (`application/x-www-form-urlencoded`, `multipart/form-data`, `text/plain`), or which have *no* content type, are checked. A JSON request is not checked by this code (the source comments that browsers send a CORS preflight for `application/json`, and carries a `TODO: remove in Astro 8` so that every unsafe request will be checked).
- For checked requests, `Sec-Fetch-Site: same-origin|none` passes, any other value fails; without that header the `Origin` header must equal the request URL’s origin. A missing `Origin` passes.

I confirmed the consequences. A form-mode action posted with `Origin: http://evil.example` returned `403 Cross-site POST form submissions are forbidden`, while a JSON RPC call with a foreign `Origin` header executed (it is the *browser’s* CORS policy that stops a malicious page from reading or even sending that request, because you do not send CORS headers). Server-to-server and `curl` callers are never stopped by either mechanism: the origin check is CSRF defence for browsers, not authentication. Two corollaries:

- If you deploy behind a proxy that rewrites the `Host`, the computed `url.origin` may differ from the browser’s `Origin`, and legitimate form posts will be 403s. Set `security.allowedDomains` so Astro trusts the forwarded host (Chapter 16).
- Never loosen your cookies. `SameSite=Lax` (the default for the session cookie) is your second line of defence against CSRF; do not set `SameSite=None` on authentication cookies without a deliberate CSRF token scheme.

### Body size and abuse

`security.actionBodySizeLimit` defaults to 1 MB (`1024 * 1024`). Oversized requests, judged by `Content-Length` and, when absent (chunked), by counting streamed bytes, fail with `CONTENT_TOO_LARGE` (HTTP 413) before the handler runs. Raise it for upload actions, lower it for chatty ones. For real file uploads, prefer presigned URLs to object storage over pushing bytes through an action.

The framework does not rate-limit. Do it in your edge, in a middleware keyed on `clientAddress` plus the action name, or inside the handler for expensive operations, and return `TOO_MANY_REQUESTS`.

### Information disclosure

- `ActionError.message` goes to the browser, including the message of unexpected exceptions (see above). The stack trace is only surfaced to the client in development.
- The `/_actions/<name>` URL space reveals which actions exist (an unknown name returns `404` with `code: "NOT_FOUND"`, which is also what a `GET` to an action URL returns). Do not rely on obscurity.
- Validation errors echo schema details. That is fine for form fields and noisy for security-sensitive endpoints, where you might catch the input error in middleware and return a generic failure.

## Actions versus endpoints

Prefer actions when the caller is *your own front end* and you want validation, typing, a uniform error shape and form support for free. Prefer endpoints (Chapter 10) when you need any of:

- A non-JSON/devalue response: file downloads, redirects with specific status, streaming, `Set-Cookie` with custom headers on the response, webhooks with signature verification over the raw body.
- A stable public contract consumed by third parties: action wire format is not a documented API.
- Non-`POST` verbs or cacheable `GET` responses: actions are `POST` only, so they are not cacheable by CDNs and not suitable for reads that should be cached (see route caching in Chapter 12).
- Cross-origin consumption with CORS.

A pragmatic split: reads go through pages, server islands (Chapter 9) or live collections (Chapter 6); writes go through actions.

## Testing actions

Because the transport is plain HTTP, you can test an action by running the server and posting to it, and by asserting on the devalue/JSON response. For logic-level tests, extract the handler body into a function (as suggested for reuse above) and unit test that with Vitest. For integration tests, the Container API and Playwright are covered in Chapter 17; with Playwright, drive the real form with JavaScript disabled (`javaScriptEnabled: false` in the context options) to prove the progressive enhancement path works, and once enabled to prove the island path.

## Key takeaways

- Actions are `POST`-only RPC: `/_actions/<name>` for generated-client calls, and `?_action=<name>` on page routes for HTML forms. Both are public endpoints.
- Define actions in the `server` export of `src/actions/index.ts`; nesting creates dotted names; use `z` from `astro/zod`.
- `accept` is enforced: a `json` action rejects `FormData` and a `form` action rejects JSON with `415`.
- Form input is coerced by schema walking: numbers, booleans (present means `true`), arrays via `getAll`, files, nested objects through `parent.child` field names; empty required text arrives as `null`.
- Results are `{ data, error }` with devalue serialization (`Date`, `Map`, `Set`, `URL` survive); `.orThrow()` trades the union for exceptions; `isInputError().fields` is keyed only by the first path segment.
- In Svelte 5 islands, call actions from event handlers only; the server-side `actions` throws unless invoked through `Astro.callAction()` or `context.callAction()`.
- Render a real `<form method="POST" action={actions.x.queryString}>` and add an `onsubmit` enhancement; this provides a working no-JS path.
- `getActionContext()` gives middleware the action name, caller type and handler, and lets you persist results (flash through sessions) for post/redirect/get; `setActionResult` disables Astro’s own handling.
- Authorize in each handler. The origin check covers only form-like content types; JSON relies on browser CORS. Body size defaults to 1 MB (`security.actionBodySizeLimit`); rate limiting and idempotency are yours to build.
- Choose endpoints over actions for non-devalue responses, public contracts, cacheable reads and webhooks.

## Review Questions

1.  Name the two transports by which an action can be invoked, and give the URL shape of each.

2.  A project defines `export const server = { cart: { add: defineAction({...}) } }`. What is the client call expression and what is the RPC URL path?

3.  Why does `ActionAPIContext` omit `redirect`? Where should a redirect after a successful action be issued in (a) an island and (b) a form flow?

4.  What is the status code and error `code` when a JSON request is sent to an action defined with `accept: 'form'`?

5.  Given the following schema on an `accept: 'form'` action, what does the handler receive when the form is submitted with `email=a@b.co`, no `terms` field, and `tags=x&tags=y`?

    ```ts
    z.object({ email: z.email(), terms: z.boolean(), tags: z.array(z.string()).default([]) })
    ```

6.  A required text input is submitted empty, and the schema field is `z.string()`. What value does Zod see, and why can that surprise you?

7.  Which input name would you use to populate `{ address: { city } }` from an HTML form?

8.  An action has `input: z.object({ address: z.object({ city: z.string().min(2) }) })`. The user submits a one-letter city. Which key in `error.fields` contains the message, and how would you read the full path?

9.  Find the bug: a Svelte island does this at the top level of its `<script>`:

    ```html
    <script lang="ts">
      import { actions } from 'astro:actions';
      const { data } = await actions.getGreeting({ name: 'x' });
    </script>
    ```

    Give at least two reasons it is wrong and the corrected approach.

10. What does `isInputError(error)` narrow, and how does it differ from `isActionError(error)`?

11. When would you choose `.orThrow()` over destructuring `{ data, error }`? What does the implementation say about its progressive-enhancement support?

12. What does the following frontmatter do on a page that renders a form for `actions.createProduct`, and what status is the recommended redirect? `` astro --- const result = Astro.getActionResult(actions.createProduct); if (result && !result.error) return Astro.redirect(`/products/${result.data.id}`); --- ``

13. Why can `Astro.getActionResult(actions.a)` be `undefined` even though the page just handled a form submission?

14. Describe the effect of calling `setActionResult()` inside middleware on Astro’s built-in action handling.

15. In the session-backed PRG middleware, why is the flash lookup placed *before* the `action?.calledFrom === 'form'` branch, and what would go wrong if it ran after?

16. Multiple choice. Which statement about `security.checkOrigin` and actions in 7.4.1 is correct?

    a.  It rejects every cross-origin unsafe request, whatever the content type.
    b.  It inspects only form-like content types (and requests with no content type); JSON relies on CORS preflight.
    c.  It checks only requests that carry a session cookie.
    d.  It applies only to prerendered routes.

17. A form-mode action posted from another origin returns what HTTP status? Does the handler run?

18. What is the default `actionBodySizeLimit`, and which error code is returned when it is exceeded?

19. A colleague says “the action is only called from the admin page, so it doesn’t need an auth check.” Explain why this is wrong.

20. Multiple choice. Calling `actions.findProduct({ query })` directly in an `.astro` frontmatter results in:

    a.  A normal result, because actions are plain functions.
    b.  A redirect to `/_actions/findProduct`.
    c.  An `ActionCalledFromServerError`; use `Astro.callAction()`.
    d.  A silent `undefined`.

21. An action handler throws `new Error('db password rejected')` (not an `ActionError`). What status, code and message does the browser receive, and what should you do instead?

22. Design: you need a webhook receiver that verifies an HMAC over the raw body and answers `202`. Should it be an action? Justify.

23. Design: a checkout action must be safe against a double click and a network retry. Describe two complementary measures, one client-side and one server-side.

24. What does `getActionPath(actions.like)` return and name two use cases for it.

25. Find the bug: the page is prerendered (`export const prerender = true`) and contains `<form method="POST" action={actions.subscribe}>`. Users report that submitting does nothing useful. Explain.

26. Why might form-mode validation failures show up as `4xx` responses in your monitoring even though the user simply saw an error message, and how would you avoid that?

27. An action reads `ctx.session?.get('cart')` but returns an empty cart for everyone in production while working locally. List the configuration facts you would check (Chapter 12 has details).

28. What is the interaction between `<ClientRouter />` and form-mode actions with respect to input values after a failed submission?
