# Final Tests

Six tests of 26 to 29 questions each, progressively harder. Test 1 checks the foundations (Chapters 1 to 4); Test 6 is expert level and spans the whole book. Questions mix multiple choice, code reading, short answer and design scenarios. Work without the chapters open, then check yourself against the next chapter, “Final Tests: Answer Key”. Unless a question says otherwise, assume Astro 7.4, `@astrojs/svelte` 9.1 and Svelte 5 with runes.

## Test 1: Islands, Astro Components and Svelte Islands

**1.** Which of the following adds JavaScript to the delivered page?

a.  A `.astro` layout with 200 lines of frontmatter
b.  A Svelte component rendered without any `client:*` directive
c.  A Svelte component rendered with `client:visible`
d.  A component with a scoped `<style>` block

**2.** What is the minimum Node.js version for Astro 7.4 and `@astrojs/svelte` 9.1?

a.  18.20.0
b.  20.19.0
c.  22.12.0
d.  22.22.0

**3.** Which of these is NOT one of the four Vite environments used by Astro 7?

a.  `client`
b.  `ssr`
c.  `prerender`
d.  `edge`

**4.** (Code reading) The project uses the Astro 7 defaults. What exact markup is produced for the last two lines, and how would you restore a space between the elements?

```html
---
const items = ['a', 'b'];
---
<ul>
  {items.map((i) => <li>{i}</li>)}
</ul>
<span>x</span>
<em>y</em>
```

**5.** A page contains `export const prerender = false;` but the project has no adapter and `output: 'static'`. What happens when you run `astro build`?

a.  The page is rendered at build time anyway
b.  The build fails because on-demand rendering requires an adapter
c.  The page is silently skipped
d.  The build succeeds with a warning and the page is served statically

**6.** (Code reading) The component below is rendered as `<Counter client:load start={3} />`.

```html
<script lang="ts">
  let { start = 0 }: { start?: number } = $props();
  let count = $state(start);
  const doubled = $derived(count * 2);
  $effect(() => {
    document.title = `Count ${count}`;
  });
</script>

<button onclick={() => count++}>{count} / {doubled}</button>
```

What text is in the server-rendered button, does the server crash because of `document`, and when does the title change for the first time?

**7.** Which prop value can be passed to a hydrated Svelte island without breaking serialization?

a.  An arrow function
b.  A `Map` of strings to numbers
c.  An instance of your own `class Money`
d.  A Svelte snippet

**8.** In an `.astro` file you write `<Card client:load><span slot="card-footer">Hi</span></Card>`, where `Card` is a Svelte component. Under which key does the Svelte renderer receive this slot, and which declaration in `Card` matches it?

a.  `cardFooter`, matched by `let { cardFooter } = $props()`
b.  `card-footer`, matched by `<slot name="card-footer" />`
c.  `footer`, matched by `<slot name="footer" />`
d.  `default`, matched by `<slot />`

**9.** Which usage does NOT produce a hydrated island?

a.  A Svelte component imported in an `.astro` file with `client:idle`
b.  A Svelte component imported inside the source of an `.mdx` file with `client:visible`
c.  A Svelte component supplied through the `components` prop of an MDX `<Content />` and marked `client:load` in the page
d.  A Svelte island placed in the default slot of another Svelte island in an `.astro` file, each with its own directive

**10.** Name two ways of sharing state between sibling islands on one page, and explain why Svelte context is not one of them.

**11.** (Code reading) What is wrong with this module, and how would you fix it?

```ts
// counter.svelte.ts
export let count = $state(0);

export function increment() {
  count++;
}
```

**12.** An on-demand page renders a Svelte island whose script mutates a module-level `$state` object defined in `.svelte.ts` during render. What is the consequence on a long-running Node server?

a.  Every request starts with fresh state
b.  The state is shared by all requests handled by that process
c.  The state is cleared when the response finishes
d.  The mutation only matters in `astro dev`

**13.** Which event fires both after the initial load and after every navigation made by `<ClientRouter />`?

a.  `DOMContentLoaded`
b.  `astro:after-swap`
c.  `astro:page-load`
d.  `astro:hydrate`

**14.** Why does the Astro documentation recommend custom elements for scripts that interact with framework-rendered DOM?

**15.** Which command type-checks the `.svelte` files in an Astro project?

a.  `astro check`
b.  `svelte-check`
c.  `astro sync`
d.  `astro build`

**16.** (Code reading) What is rendered for `<Heading level={1} title="Hi" />`?

```html
---
const { title, level = 2 } = Astro.props;
const Tag = `h${level}`;
---
<Tag class:list={['t', { big: level === 1 }]}>{title}</Tag>
```

**17.** What does `define:vars` on a `<script>` tag imply, and what do you lose?

**18.** Which call is valid in a `.astro` file in Astro 7?

a.  `` import.meta.glob(`./${dir}/*.md`) ``
b.  `import.meta.glob('./posts/*.md', { eager: true })`
c.  `Astro.glob('./posts/*.md')`
d.  `import.meta.glob(pattern)` where `pattern` is a variable

**19.** A `<Field>` Svelte island is rendered three times on a page and needs `id`/`for` pairs that are unique across islands and identical between server HTML and hydration. Which API do you use?

a.  `crypto.randomUUID()` at the top of the script
b.  `Math.random().toString(36)`
c.  `$props.id()` declared at the top level of the script
d.  A module-level counter

**20.** To use `<style lang="scss">` in a Svelte component, what must you do?

a.  Nothing; the integration adds the preprocessor
b.  Create `svelte.config.js` with `preprocess: vitePreprocess()` imported from `@astrojs/svelte`, and install `sass`
c.  Set `compressHTML: false`
d.  Import the stylesheet in the `.astro` page

**21.** What exactly does Astro hand to a Svelte renderer for children and named slots, and what is the practical limitation for a Svelte island that expects a snippet with arguments?

**22.** (Scenario) A product page has: a static image gallery; a sticky buy box with a quantity stepper and “Add to cart”; a reviews list far below the fold with client-side filtering; a newsletter form in the footer that works with plain form posting; and a header greeting “Hi, Ana” that depends on the logged-in user. Assign a rendering or hydration strategy to each, with one sentence of justification.

**23.** Which statement about `client:only="svelte"` is correct?

a.  The component is server-rendered and then hydrated
b.  The framework name can be omitted because `check` detects it
c.  The component is never rendered on the server and `slot="fallback"` content is shown until it mounts
d.  It is the cheapest directive for above-the-fold content that matters for SEO

**24.** An island with `client:visible` is nested inside the slot of an island with `client:load`. In which order do they hydrate?

a.  Child first, because it is smaller
b.  Parent first; the child waits for its closest ancestor island to hydrate
c.  Whichever script loads first
d.  They hydrate together in one task

**25.** (Code reading) The component below is in a project with `output: 'static'` and no `prerender` export. A second copy lives in a project where the page has `export const prerender = false` and an adapter. One hour after deployment, what timestamp does a visitor see in each?

```html
---
const now = new Date().toISOString();
---
<p>{now}</p>
```

**26.** In one or two sentences, explain why Astro components cannot be imported into a `.svelte` file and what to do when a Svelte island needs content Astro has computed.

## Test 2: Routing, Content Collections and Markdown

**1.** A project contains `src/pages/blog/new.astro`, `src/pages/blog/[slug].astro` and `src/pages/blog/[...rest].astro`. Which file serves `/blog/new`?

a.  `[slug].astro`
b.  `[...rest].astro`
c.  `new.astro`
d.  The build fails because of the conflict

**2.** (Code reading) What happens when this prerendered route is built on Astro 7.4?

```html
---
export async function getStaticPaths() {
  return [
    { params: { id: 1 }, props: { label: 'one' } },
    { params: { id: 2 }, props: { label: 'two' } },
  ];
}
const { label } = Astro.props;
---
<h1>{label}</h1>
```

**3.** (Code reading) The file is `src/pages/posts/[page].astro`. How many pages are generated, what are their URLs, and how many items does `page.data` hold on the last page?

```html
---
export async function getStaticPaths({ paginate }) {
  const posts = Array.from({ length: 23 }, (_, i) => ({ n: i }));
  return paginate(posts, { pageSize: 10 });
}
const { page } = Astro.props;
---
<p>{page.data.length}</p>
```

How would the URLs change if the file were renamed `[...page].astro`?

**4.** A redirect `'/old': '/new'` is configured with no explicit status. Which statuses does a `GET` and a `POST` to `/old` receive?

a.  301 and 301
b.  301 and 308
c.  302 and 307
d.  308 and 308

**5.** A configured redirect `'/about-us': '/about'` exists and you also create `src/pages/about-us.astro`. Which wins?

a.  The redirect, because redirects run first
b.  The file route; file routes take precedence over redirects
c.  Whichever is alphabetically first
d.  The build fails

**6.** Why is `if (url.pathname.startsWith('/admin'))` a weak authorization check in a pre-processing handler of `src/fetch.ts`? Give two request paths that illustrate the problem.

**7.** (Code reading) This is `src/fetch.ts`. Is `/dash` protected when a visitor has no session? Explain.

```ts
import { Hono } from 'hono';
import { actions, middleware, pages, sessions, getFetchState } from 'astro/hono';

const app = new Hono();

app.use('/dash', requireAuth);
app.use('/dash/*', requireAuth);

app.use(sessions());
app.use(actions());
app.use(middleware());
app.use(pages());

export default app;

async function requireAuth(c: any, next: () => Promise<void>) {
  const state = getFetchState(c);
  if (!state.locals.user) return c.redirect('/login');
  await next();
}
```

**8.** In what order does the built-in pipeline run, and where must `sessions()` and `actions()` be placed relative to `middleware()` and `pages()` when you compose handlers yourself?

**9.** After upgrading to Astro 7, a project that had an unrelated `src/fetch.ts` exporting a helper function starts failing. Why, and what are the two fixes?

a.  Astro 7 deletes unknown files in `src/`
b.  The file is loaded as the advanced routing entrypoint; rename it or change `fetchFile` (or set it to `null`)
c.  `src/fetch.ts` is only valid in `output: 'server'`
d.  It needs a `.mjs` extension

**10.** (Code reading) Given this configuration, what is the runtime type of `entry.data.author`, and how do you obtain the author’s name for a post `entry`?

```ts
import { defineCollection, reference } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

const authors = defineCollection({
  loader: glob({ pattern: '**/*.json', base: './src/data/authors' }),
  schema: z.object({ name: z.string() }),
});

const posts = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/posts' }),
  schema: ({ image }) =>
    z.object({
      title: z.string(),
      cover: image(),
      author: reference('authors'),
      tags: z.array(z.string()).prefault([]),
      draft: z.boolean().default(false),
    }),
});

export const collections = { authors, posts };
```

**11.** In Zod 4, what is the difference between `.default()` and `.prefault()`?

**12.** (Code reading) A custom loader syncs products from an API. Which purpose does `meta` serve here, and what bug appears when a product is removed upstream?

```ts
export function productsLoader() {
  return {
    name: 'products-api',
    async load({ store, meta, parseData, generateDigest, renderMarkdown }) {
      const since = meta.get('lastSync');
      const res = await fetch(`https://api.example.com/products?since=${since ?? ''}`);
      const items = await res.json();
      for (const item of items) {
        const data = await parseData({ id: item.id, data: item });
        store.set({
          id: item.id,
          data,
          digest: generateDigest(item),
          rendered: await renderMarkdown(item.body),
        });
      }
      meta.set('lastSync', new Date().toISOString());
    },
  };
}
```

**13.** Where do you import `LiveEntryNotFoundError` from?

a.  `astro:content`
b.  `astro/content/runtime`
c.  `astro/loaders`
d.  `astro/zod`

**14.** Which statement about live collections is true?

a.  They are queried with `getCollection()` and cached in the data store
b.  They support MDX rendering and image optimization
c.  Queries return `{ entry | entries, error, cacheHint }` and run on every request, so they need an adapter
d.  A `cacheHint` automatically sets `Cache-Control` headers

**15.** What is `glob({ deferRender: true })` (7.1) for, and what do you give up?

**16.** After upgrading to Astro 7, a site using `remark-math` and `rehype-katex` renders formulas as plain text. What is the minimal fix?

a.  Replace Shiki with Prism
b.  Install `@astrojs/markdown-remark` and set `markdown.processor: unified({ remarkPlugins: [...], rehypePlugins: [...] })`
c.  Set `compressHTML: false`
d.  Move the plugins into `mdx({ recmaPlugins })`

**17.** (Code reading) What happens to a fenced ```` ```mermaid ```` block and to the text `a -- b` in Markdown with this configuration?

```js
import { satteri } from '@astrojs/markdown-satteri';

export default defineConfig({
  markdown: {
    processor: satteri({ features: { smartPunctuation: false } }),
    syntaxHighlight: { type: 'shiki', excludeLangs: ['math', 'mermaid'] },
  },
});
```

**18.** A remark plugin writes `readingTime` into the document’s frontmatter data. Where do you read it for a content collection entry, and why is it not in `entry.data`?

**19.** In MDX, you map `h2` to your own component through the `components` prop of `<Content />`, and the component renders `<h2 {...props}>` without a slot. What is missing?

**20.** A page uses `<Poll client:load />` where `Poll` is provided through `components={{ Poll }}` on `<Content />`. What does the browser receive?

**21.** Which statement about `src/pages/500.astro` is correct?

a.  It is used for prerendered pages
b.  It is used for on-demand routes and receives an `error` prop of type `unknown`
c.  It receives a typed `Error` and should print `error.stack`
d.  It replaces `404.astro`

**22.** A page inside `src/pages/` must be returned as an HTML fragment with no `<!DOCTYPE html>`, `<head>` or hoisted styles for an HTMX-style swap. What do you write?

a.  `export const fragment = true`
b.  `export const partial = true`
c.  Name the file `_partial.astro`
d.  `Astro.response.headers.set('x-partial', '1')`

**23.** (Code reading) What does this page do for an unknown SKU, and why is `error instanceof` used instead of `try/catch`?

```html
---
export const prerender = false;
import { getLiveEntry } from 'astro:content';
import { LiveEntryNotFoundError } from 'astro/content/runtime';

const { entry, error, cacheHint } = await getLiveEntry('inventory', { sku: Astro.params.sku! });

if (error instanceof LiveEntryNotFoundError) return Astro.rewrite('/404');
if (error) throw error;
Astro.cache.set(cacheHint);
---
<p>{entry.data.name}: {entry.data.stock} in stock</p>
```

**24.** `experimental.incrementalBuild` is enabled. List two conditions under which a page is NOT reused from the cache, or the feature is disabled.

**25.** (Scenario) Choose build-time loader, live collection, endpoint, or client fetch for each, and justify briefly: (a) blog posts edited in a headless CMS several times a week; (b) stock levels that must be fresh within seconds and shared by all visitors; (c) a signed-in user’s recently viewed items.

**26.** (Scenario) You are migrating a blog from legacy content collections (`src/content/config.ts`, `type: 'content'`, `entry.slug`, `entry.render()`) to Astro 7. List the concrete code changes in order, and one behavior that may break silently.

## Test 3: On-Demand Rendering, Server Islands, Middleware and Actions

**1.** Which statement about the `output` option is correct in Astro 7.4?

a.  It accepts `'static'`, `'server'` and `'hybrid'`
b.  It accepts only `'static'` and `'server'`; per-route `prerender` flips individual routes
c.  `'server'` unlocks features that `'static'` with `prerender = false` cannot use
d.  It must be `'server'` whenever any route uses `prerender = false`

**2.** A prerendered page reads `Astro.clientAddress`. What happens?

a.  It returns `127.0.0.1`
b.  It returns `undefined`
c.  The build fails with `PrerenderClientAddressNotAvailable`
d.  It returns the address of the build machine

**3.** (Code reading) The page streams on demand. Why is the 404 status unreliable here, and where should it be set?

```html
---
import Layout from '../layouts/Layout.astro';
import Product from '../components/Product.astro';
---
<Layout>
  <Product sku={Astro.params.sku} />
</Layout>
```

```html
---
// Product.astro
const { sku } = Astro.props;
const product = await getProduct(sku);
if (!product) Astro.response.status = 404;
---
{product && <h1>{product.name}</h1>}
```

**4.** (Code reading) Two middleware functions are combined as `sequence(a, b)`. `a` logs `a-in`, awaits `next()`, logs `a-out`. `b` logs `b-in`, returns `new Response('ok')` immediately without calling `next()` when the path is `/health`, and otherwise awaits `next()` and logs `b-out`. Give the log lines for a request to `/health` and for a request to `/`.

**5.** What happens when middleware executes `ctx.locals = { user }`?

a.  The new object replaces `locals` for later handlers
b.  Astro throws `LocalsReassigned`; mutate `ctx.locals.user = user` instead
c.  The assignment is ignored silently
d.  It only works inside `sequence()`

**6.** (Code reading) On a freshly started server, a visitor requests `/a`, and later another requests `/b`. The page `/who` prints `Astro.locals.n`. What do the two visitors see, and why?

```ts
let n = 0;
export const onRequest = defineMiddleware((ctx, next) => {
  n++;
  ctx.locals.n = n;
  if (ctx.url.pathname === '/a') return next('/who');
  if (ctx.url.pathname === '/b') return ctx.rewrite('/who');
  return next();
});
```

**7.** An endpoint file exports both `GET` and `ALL`. Which handler answers a `HEAD` request?

a.  `GET` with the body stripped
b.  `ALL`
c.  None; the response is 405
d.  Astro synthesizes an empty 200

**8.** An endpoint handler returns `{ ok: true }` (a plain object). What happens, and what is the fix?

**9.** On Vercel with ISR, your auth middleware never seems to run for cached pages. Why, and what is the fix?

a.  ISR disables all middleware globally; remove ISR
b.  Middleware is bundled into the ISR function and only runs on a cache miss or regeneration; set `middlewareMode: 'edge'` or exclude the routes from ISR
c.  Middleware runs only for POST requests under ISR
d.  You must rename the file `middleware.edge.ts`

**10.** Why can middleware never protect a page that has `prerender = true`, and what are your options?

**11.** A Node `standalone` build runs in Docker but is unreachable from outside the container. Which setting is the first suspect?

a.  `PORT=80`
b.  `HOST=0.0.0.0`
c.  `mode: 'middleware'`
d.  `bodySizeLimit`

**12.** A teammate relies on a `.env` file being picked up by the Node adapter in production. Why does it not work, and what are the correct options?

**13.** A teammate says that because server island props are encrypted, it is fine to pass `userId` and `isAdmin` as props to a deferred component and trust them there. Explain the flaw.

**14.** (Code reading) A middleware protects `/account` by checking `ctx.url.pathname.startsWith('/account')` and requires a session. The page `/account/index.astro` embeds `<OrderSummary server:defer />`. Describe what `Astro.url.pathname` is inside `OrderSummary` and what this implies for the middleware and for the island.

**15.** What happens when you put `server:defer` directly on a Svelte component, as in `<Cart server:defer />`?

a.  It is deferred and hydrated
b.  It is deferred but not hydrated
c.  The directive is ignored; the component renders inline as plain server HTML
d.  The build fails

**16.** After each deploy, some visitors see the fallback of a server island forever, and requests to `/_server-islands/...` return 400. Which is the most likely cause?

a.  The CDN strips query strings
b.  Cached pages from an older build were encrypted with a key that differs from the one embedded in the new build; set a stable `ASTRO_KEY` (from `astro create-key`) at build
c.  `server:defer` is incompatible with `trailingSlash`
d.  The fallback slot is empty

**17.** When does a server island request use `POST` instead of `GET`, and what is the cost?

**18.** How do you prevent a layout shift when the island response replaces its fallback?

**19.** (Code reading) The form posts `address.city` empty. What does `isInputError(error)` say, and under which key of `error.fields` does the issue appear?

```ts
// src/actions/index.ts
export const server = {
  saveAddress: defineAction({
    accept: 'form',
    input: z.object({
      address: z.object({ city: z.string().min(1) }),
    }),
    handler: async ({ address }) => ({ saved: address.city }),
  }),
};
```

```html
<form method="POST" action={actions.saveAddress}>
  <input name="address.city" />
  <button>Save</button>
</form>
```

**20.** What is the RPC URL for `actions.cart.add()`?

a.  `/api/cart/add`
b.  `/_actions/cart/add`
c.  `/_actions/cart.add`
d.  `/cart/add?_action=1`

**21.** How must you call an action from `.astro` frontmatter?

a.  `await actions.cart.add(input)` directly
b.  `await Astro.callAction(actions.cart.add, input)`
c.  `fetch('/_actions/cart.add')` with `credentials: 'omit'`
d.  You cannot call actions on the server

**22.** Which cross-site request does `security.checkOrigin` reject with 403 by default?

a.  `POST` with `Content-Type: application/json`
b.  `POST` with `Content-Type: application/x-www-form-urlencoded`
c.  `GET` with query parameters
d.  A same-origin `POST` using `multipart/form-data`

**23.** (Code reading) A form submits `createPost`. State the response status when validation fails, what `result` is if a different action was submitted, and why the redirect uses 303.

```html
---
import { actions } from 'astro:actions';

const result = Astro.getActionResult(actions.createPost);
if (result && !result.error) {
  return Astro.redirect(`/posts/${result.data.id}`, 303);
}
const err = result?.error;
---
{err && <p role="alert">{err.message}</p>}
<form method="POST" action={actions.createPost}>...</form>
```

**24.** A handler throws `new Error('db password rejected')`. What does the client see, and how do you fix it?

**25.** Which of these is the WORST fit for an action?

a.  Saving a profile form submitted from a Svelte island
b.  Adding a product to a cart from an island and a no-JS form
c.  Receiving a payment provider’s signed webhook
d.  A newsletter signup with progressive enhancement

**26.** (Scenario) You deploy a Node app to three containers behind a load balancer. Symptoms: visitors are randomly logged out; some server islands never replace their fallbacks; the cart badge shows different counts on refresh. List the three causes and fixes.

**27.** (Scenario) Design an “apply coupon” flow on a checkout page. Requirements: works without JavaScript, only for signed-in users, resists double submissions, and never leaks internal errors. Name the pieces (action definition, validation, authorization, form wiring, error handling, idempotency).

## Test 4: Sessions, Route Caching, Assets, Navigation and i18n

**1.** When does Astro first set the session cookie?

a.  On every request that reads `Astro.session`
b.  On the first `get()`
c.  On the first `set()` (or `regenerate()` or `load()`)
d.  Only after `ttl` elapses

**2.** (Code reading) A user adds items to the cart and, after a reload, the newest item is missing. Why?

```ts
const cart = (await Astro.session?.get('cart')) ?? [];
await Astro.session?.set('cart', cart);
cart.push(sku);
```

**3.** Which adapters configure a default session driver in Astro 7.4?

a.  Node, Cloudflare and Netlify
b.  Node and Vercel
c.  Every adapter
d.  None; `session.driver` is always required

**4.** You configure `session: { driver: sessionDrivers.redis({ url: process.env.REDIS_URL }) }` and deploy the same build to staging and production with different `REDIS_URL` values. Both use the same Redis. Why, and what is the fix?

**5.** What is the difference between Astro’s session `ttl` and a driver-level TTL such as Redis expiry?

**6.** Why must you call `Astro.session.regenerate()` after a successful login?

**7.** (Code reading) A `routeRules` entry and a page both configure caching. What are the effective `maxAge` and tags for `/products/p-7`, and what changes if the page later calls `Astro.cache.set(false)`?

```js
// astro.config.mjs
export default defineConfig({
  cache: { provider: memoryCache() },
  routeRules: {
    '/products/[slug]': { maxAge: 300, swr: 60, tags: ['products'] },
  },
});
```

```html
---
Astro.cache.set({ maxAge: 60, tags: ['p-7'] });
---
```

**8.** With the memory route-cache provider, which response is NOT cached?

a.  A response with `Vary: Accept-Language`
b.  A response to a request that carries cookies
c.  A response that itself sets a cookie
d.  A response for a URL with a query string

**9.** A route rule has `tags: ['products']` and no `maxAge`. What does the memory provider do?

a.  Caches for the default 5 minutes
b.  Caches indefinitely until invalidated by tag
c.  Does not cache; it needs a positive `maxAge`
d.  Throws at startup

**10.** Three Node instances run behind a load balancer with the memory cache provider. A CMS webhook calls `Astro.cache.invalidate({ tags: ['products'] })`. What goes wrong, and what are the options?

**11.** Which `routeRules` key is valid?

a.  `'/blog/**'`
b.  `'/products/*'`
c.  `'/products/[slug]'`
d.  `/^\/p\//`

**12.** (Code reading) What is wrong with the first line, and what are the displayed dimensions if `hero.png` is 2000 by 1000 pixels?

```html
---
import { Image } from 'astro:assets';
import hero from '../assets/hero.png';
---
<img src={hero} alt="Hero" />
<Image src={hero} width={800} alt="Hero" />
```

**13.** Which `remotePatterns` hostname matches both `a.cdn.example.com` and `a.b.cdn.example.com`?

a.  `*.cdn.example.com`
b.  `**.cdn.example.com`
c.  `cdn.example.com`
d.  `*.example.com`

**14.** A Svelte product card needs an optimized, resized image. It cannot use `<Image>`. Describe two approaches.

**15.** (Code reading) How many font files are downloaded for this configuration, and what does `<Font cssVariable="--font-inter" preload />` add?

```js
fonts: [
  {
    provider: fontProviders.google(),
    name: 'Inter',
    cssVariable: '--font-inter',
    weights: [400, 700],
  },
],
```

**16.** (Code reading) The `<h2>` elements inside `<slot />` are not red. Why, and how do you fix it without leaving the component?

```html
<article><slot /></article>

<style>
  article h2 { color: red; }
</style>
```

**17.** Which event is the right place to set `data-theme` on the incoming document so that the new page does not flash?

a.  `astro:before-preparation`
b.  `astro:before-swap`
c.  `astro:after-swap`
d.  `astro:page-load`

**18.** (Code reading) With `<ClientRouter />` in the layout, the menu toggle works on the first page and stops working after navigating. Why, and what are three fixes?

```html
<button id="menu">Menu</button>
<script>
  document.getElementById('menu')?.addEventListener('click', toggleMenu);
</script>
```

**19.** A persisted Svelte island (`transition:persist`) shows `label` from props. On the next page the same island appears with a different `label`. What does the visitor see with and without `transition:persist-props`, and does `onMount` run again?

**20.** (Code reading) Where does this component leak, and how do you fix it?

```html
<script lang="ts">
  let width = $state(0);
  $effect(() => {
    const onResize = () => (width = window.innerWidth);
    window.addEventListener('resize', onResize);
    onResize();
  });
</script>
<p>{width}px</p>
```

**21.** With `<ClientRouter />`, a `POST` form is submitted. How is it handled by default, and how do you opt a form out?

**22.** Which statement about prefetching is correct?

a.  The default strategy is `viewport`
b.  `prefetchAll` defaults to true when `<ClientRouter />` is used
c.  Prefetching issues `POST` requests
d.  Prefetching is unaffected by data-saver mode

**23.** Which configuration is rejected by Astro 7.4?

a.  `{ defaultLocale: 'en', locales: ['en', 'es'], routing: { prefixDefaultLocale: true, redirectToDefaultLocale: true } }`
b.  `{ defaultLocale: 'en', locales: ['en', 'es'], routing: { prefixDefaultLocale: false, redirectToDefaultLocale: true } }`
c.  `{ defaultLocale: 'en', locales: ['en', 'es'], routing: 'manual' }`
d.  `{ defaultLocale: 'en', locales: ['en', 'es'], fallback: { es: 'en' } }`

**24.** (Code reading) Is this i18n configuration valid? If not, fix it.

```js
i18n: {
  defaultLocale: 'en',
  locales: ['en', { path: 'french', codes: ['fr', 'fr-CA'] }],
  fallback: { fr: 'en' },
}
```

**25.** What is the effect of `fallbackType: 'rewrite'` compared with `'redirect'` for a page that exists only in the default locale?

**26.** Why is `<html lang={Astro.currentLocale}>` risky on a fallback page rendered with `fallbackType: 'rewrite'`, and what is the better approach?

**27.** (Scenario) A product page is cached with `routeRules: { '/products/[slug]': { maxAge: 300 } }`. The marketing team adds “Welcome back, Ana” to the header, read from the session. Users begin to see other people’s names. Explain why, and give two fixes. Then say what happens to caching if a response sets a cookie.

## Test 5: Environment, Security, Performance, Testing, Integrations and Migration

**1.** A teammate reads `import.meta.env.API_URL` in a server module and deploys one build artifact to staging and production with different `API_URL` values. What do both environments see?

a.  Their own runtime value
b.  The value present at build time, because Vite inlines it
c.  `undefined` in production
d.  A build error

**2.** Which `envField` declaration is invalid?

a.  `envField.string({ context: 'client', access: 'public' })`
b.  `envField.string({ context: 'server', access: 'secret' })`
c.  `envField.string({ context: 'client', access: 'secret' })`
d.  `envField.number({ context: 'server', access: 'public', default: 3000 })`

**3.** (Code reading) When is `STRIPE_KEY` validated, what happens if it is missing, and what should CI do?

```js
env: {
  schema: {
    PUBLIC_API: envField.string({ context: 'client', access: 'public' }),
    STRIPE_KEY: envField.string({ context: 'server', access: 'secret' }),
  },
  validateSecrets: false,
},
```

**4.** You need a variable from `.env` inside `astro.config.mjs`. `import.meta.env` is empty there. What do you use, and why does the problem exist?

**5.** Does `security.checkOrigin` protect a cross-site `POST` with `Content-Type: application/json` against CSRF? Explain what does protect it.

**6.** What risk does `security.allowedDomains` mitigate, and how does `*.example.com` differ from `**.example.com`?

**7.** A CSP directive lists `'unsafe-inline'` in `script-src` together with generated hashes. What does Astro do, and why?

**8.** (Code reading) Where does `'unsafe-inline'` end up, and which problem does the second entry solve?

```js
security: {
  csp: {
    scriptDirective: {
      resources: ["'self'", { resource: 'https://cdn.example.com', kind: 'element' }],
    },
    styleDirective: {
      resources: ["'self'", { resource: "'unsafe-inline'", kind: 'attribute' }],
    },
  },
},
```

**9.** Which combination does Astro 7.4’s CSP support NOT work with?

a.  CSP with static output and Node `staticHeaders`
b.  CSP with `<ClientRouter />`
c.  CSP with Prism highlighting
d.  CSP with Svelte islands

**10.** The checkout page needs a payment script and an iframe that no other page should allow. How do you widen the policy only for that page?

**11.** After you move the CDN script into `{ resource, kind: 'element' }`, a teammate’s `<script src="https://cdn.example.com/x.js">` stops loading on pages where the CDN stays in the default `resources`. Explain.

**12.** Which directive choice is the cheapest in first-load JavaScript for an interactive widget far below the fold?

a.  `client:load`
b.  `client:idle`
c.  `client:visible`
d.  `client:only="svelte"`

**13.** When does `experimental.parallelPrerender` help?

a.  For I/O-bound rendering dominated by slow API calls
b.  For CPU-bound rendering of many static pages; workers do not share module-level state, and it is ignored by adapters that supply their own prerenderer such as Cloudflare
c.  Only in `astro dev`
d.  For on-demand routes at runtime

**14.** (Code reading) The test renders `Counter.svelte` through the Container API, but `Count: 0` is missing from the output. What is wrong, and what is the correct setup? Which Vitest environment must be used?

```ts
import { experimental_AstroContainer as AstroContainer } from 'astro/container';
import { expect, test } from 'vitest';
import Page from '../src/components/Page.astro';

test('renders the counter', async () => {
  const container = await AstroContainer.create();
  const html = await container.renderToString(Page);
  expect(html).toContain('Count: 0');
});
```

**15.** Why does Vitest with `getViteConfig()` need `environment: 'node'` for Astro component tests?

**16.** (Code reading) This end-to-end test is flaky on a production build when the island uses `client:visible`. Why, and how do you stabilize it?

```ts
await page.goto('/products/lamp');
await page.getByRole('button', { name: 'Add to cart' }).click();
await expect(page.getByText('1 in cart')).toBeVisible();
```

**17.** A custom logger destination implements only `write()`. What do you notice in the build output, and why?

**18.** An AI agent starts `astro dev` in your project. What happens by default, how do you inspect and stop the server, and how do you opt out?

**19.** Which hooks run only in dev?

a.  `astro:build:start`, `astro:build:setup`
b.  `astro:server:setup`, `astro:server:start`, `astro:server:done`
c.  `astro:config:setup`, `astro:config:done`
d.  `astro:routes:resolved`

**20.** (Code reading) What does each registration do, and which of them affects prerendered pages in a static build?

```ts
'astro:config:setup': ({ injectRoute, addMiddleware, injectScript }) => {
  injectRoute({ pattern: '/_acme/health', entrypoint: '@acme/kit/health.ts', prerender: false });
  addMiddleware({ entrypoint: '@acme/kit/mw.ts', order: 'pre' });
  injectScript('page', `import '@acme/kit/analytics';`);
},
```

**21.** What is the signature of a custom client directive function?

a.  `(element, options)`
b.  `(load, options, element)`, where `load()` resolves to a `hydrate` function
c.  `(hydrate)`
d.  `(Component, props)`

**22.** In a Vite plugin inside an integration, how do you make a virtual module fail the build when it is imported from client code?

a.  Check `this.environment.name === 'client'` in `load` and throw
b.  Check `typeof window`
c.  Set `ssr: false`
d.  It cannot be done

**23.** What is the difference between adapter `entrypointResolution: 'auto'` and `'explicit'`?

**24.** What is the recommended upgrade order for a site on Astro 5, and why?

a.  Jump straight to 7 and fix errors
b.  Go to 6 first, get a green build, then go to 7
c.  Go to 7 first, then downgrade to 6 if needed
d.  Upgrade adapters first, Astro last

**25.** (Code reading) Which snippet fails the build under the Rust compiler, and what happens with the others?

```html
<!-- A -->
<ul><li>one<li>two</ul>

<!-- B -->
<p><div>x</div></p>

<!-- C -->
<table><tr><td>1</td></tr></table>
```

**26.** (Code reading) `PUBLIC_FEATURE_X=false` is set. What renders, and what is the fix?

```html
{import.meta.env.PUBLIC_FEATURE_X && <BetaBanner />}
```

**27.** Which statements about replacements in Astro 6 and 7 are correct? Choose all that apply.

a.  `z.string().email()` is preferred over `z.email()` in Zod 4
b.  `session.driver: 'redis'` strings are deprecated in favour of `sessionDrivers.redis(...)`
c.  `getContainerRenderer` is imported from `@astrojs/svelte/container-renderer`
d.  `event.type === 'astro:before-swap'` replaces `isTransitionBeforeSwapEvent(event)`

**28.** (Scenario) A Svelte 5 site on Astro 5 uses legacy content collections, remark plugins with `smartypants` options, `@astrojs/db`, `ViewTransitions`, `Astro.glob()` and `experimental.advancedRouting`. Produce an ordered upgrade plan to Astro 7.4 and name the main risk at each step.

**29.** (Scenario) A shop uses `<ClientRouter />` to persist a cart island. Security asks for a strict CSP. Explain the conflict and present two viable options, including what each costs.

## Test 6: Expert Level, Cross-Cutting Design and Debugging

**1.** A catalogue page is cached by route rules (`maxAge: 300`). It contains `<MiniCart server:defer />`, and `MiniCart.astro` reads the session cookie to print the visitor’s items. A teammate adds `Astro.cache.set({ maxAge: 60 })` inside `MiniCart.astro` “to reduce load”. What can go wrong, and what do you do instead?

**2.** (Code reading) Find at least three defects in this middleware, given that the app has account pages, an `<OrderList server:defer />` island, an `orders.list` action and an `/account` page that is partly prerendered.

```ts
export const onRequest = defineMiddleware(async (ctx, next) => {
  if (ctx.url.pathname.startsWith('/account') && !ctx.cookies.has('sid')) {
    return ctx.redirect('/login');
  }
  return next();
});
```

**3.** (Code reading) This `src/fetch.ts` replaces the default pipeline. Name four behaviors that silently stop working.

```ts
import { FetchState, actions, middleware, pages, trailingSlash } from 'astro/fetch';

export default {
  async fetch(request: Request): Promise<Response> {
    const state = new FetchState(request);
    const slash = trailingSlash(state);
    if (slash) return slash;
    const action = await actions(state);
    if (action) return action;
    return middleware(state, () => pages(state));
  },
};
```

**4.** (Code reading) `getLiveCollection('inventory', { inStock: true })` returns a collection hint with `tags: ['inventory']` and `lastModified: D1`. Two returned entries carry hints `{ tags: ['sku:a'], lastModified: D3 }` and `{ tags: ['sku:b'], lastModified: D2 }`, where D1 \< D2 \< D3. What is the merged hint, and what must you do for it to affect caching?

**5.** (Code reading) Identify two defects and one environment assumption in this action.

```ts
add: defineAction({
  accept: 'json',
  input: z.object({ sku: z.string(), qty: z.number().int().min(1) }),
  handler: async (input, ctx) => {
    const cart = (await ctx.session?.get('cart')) ?? {};
    cart[input.sku] = (cart[input.sku] ?? 0) + input.qty;
    await ctx.session?.set('cart', cart);
    return cart;
  },
}),
```

**6.** (Code reading) Why is `ready` needed, and why is `transition:persist` not required for the count to survive navigation?

```html
<script lang="ts">
  import { onMount } from 'svelte';
  import { cart } from './cart.svelte.ts';

  let ready = $state(false);
  onMount(() => {
    cart.load();
    ready = true;
  });
</script>

<span aria-live="polite">{ready ? cart.count : '…'}</span>
```

**7.** What is `Astro.session` at runtime when no session storage is configured (verified on 7.4.1)?

a.  An object whose methods throw
b.  `undefined`, with a `[WARN] [session]` message logged on access
c.  An in-memory session
d.  The build fails

**8.** An image service is configured as `{ build: { entrypoint: 'astro/assets/services/sharp' }, runtime: { entrypoint: 'my-image-cdn-service' } }`. Which images use which?

a.  `build` handles prerendered pages (and dev); `runtime` handles on-demand pages and `/_image`
b.  `build` handles remote images; `runtime` handles local ones
c.  `build` handles AVIF; `runtime` handles WebP
d.  Both are used for every image

**9.** On Cloudflare, a prerendered page imports a Node-only dependency and the build breaks in the prerender step. Which option applies, and does it change on-demand pages?

a.  `prerenderEnvironment: 'node'`; on-demand pages still run in `workerd`
b.  `prerenderEnvironment: 'node'`; on-demand pages run in Node too
c.  `output: 'hybrid'`
d.  `session: false`

**10.** You set `scriptDirective.strictDynamic: true` and also scope your CDN with `kind: 'element'`. Which statement is true?

a.  Host allow-lists keep working under `strict-dynamic`
b.  `strict-dynamic` is inherited by `script-src-elem`, and host-based allow-lists are ignored
c.  `strict-dynamic` removes all hashes
d.  CSP is disabled in production

**11.** Describe the difference between a runtime route-cache provider and a CDN provider, including who stores responses and what hits reach the Astro server.

**12.** `i18n.domains` is configured and the build now fails validation. List the requirements and the most likely cause for a static project.

**13.** Why is a rate limiter keyed on `Astro.clientAddress` read from a client-supplied `X-Forwarded-For` header unsafe, and what is the correct approach?

**14.** With `experimental.incrementalBuild` on, pages that embed a server island are rebuilt on every build. Why, and what is the fix?

a.  The island script is not hashed; add CSP
b.  The per-build key embedded in the page changes; pin `ASTRO_KEY`
c.  Server islands disable `build.concurrency`
d.  `cacheKey` must be a number

**15.** When is `experimental.collectionStorage: 'chunked'` the right tool?

a.  To speed up dev reloads
b.  When the single data-store file becomes too large for the host’s per-asset limits; it splits the store into chunks (20 MB default)
c.  To enable live collections
d.  To store session data

**16.** How do you enable `await` expressions in Svelte components during SSR, and where must the setting live for the editor and build to agree?

**17.** A Vitest test (environment `node`) for a `.svelte.ts` module asserts that an `$effect` pushed values into an array. The array stays empty even after `flushSync()`. Why?

a.  `$state` is not supported under Vitest
b.  Vitest transforms modules through the SSR path where Svelte compiles in server mode, and effect callbacks do not run there
c.  `flushSync` is removed in Svelte 5
d.  Effects need `$effect.pre`

**18.** The Container API renders a cart page and shows the guest greeting. Name what this test cannot prove about the shop.

**19.** What is the consequence of `return next(new Request(request, { body }))` in middleware, and which alternative avoids it?

a.  The body can be read before and after; nothing changes
b.  A rewrite creates a new `Request`, so reading the body before or after throws; use `Astro.rewrite()` from the template instead
c.  Middleware runs twice
d.  The response is cached forever

**20.** A loader defines `schema` as a function in 7 and the build warns. What replaces it, what does it return, and which schema wins when the user also defines one in `content.config.ts`?

**21.** Your Sätteri-based site adds a plugin that generates its own heading ids. What controls whether Astro’s `headings` match the ids in the HTML?

**22.** (Scenario) A site with 20,000 prerendered pages builds in 40 minutes. Describe a measurement-first plan, naming at least four levers with their trade-offs.

**23.** (Scenario) The shop of Chapter 20 enters three markets (`bg`, `de`, `fr`) that have different prices and availability but share product text. How do you model the data, the live inventory, the cache tags and the invalidation webhook?

**24.** (Scenario) A CMS webhook invalidates product pages. Production runs five Node instances with the memory provider; the CDN also caches HTML. Users still see stale prices for minutes. Explain each layer’s role and give a redesign.

**25.** (Scenario) Design the authorization for `/admin` in an app that uses pages, actions, a server island and a JSON endpoint. List the layers, where each check lives, and the tests that prove it.

**26.** (Code writing) Implement a `client:hover` directive that hydrates an island on first `pointerenter`: write the integration registration, the directive module and the TypeScript augmentation.

**27.** The book flags several places where the documentation and the verified behaviour disagree or are silent. Name two and say what the book recommends.

**28.** Tailwind utilities do not override an image’s styles after you set `image.responsiveStyles: true`. Why, and what are the options?
