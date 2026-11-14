# Chapter 9: Server Islands

Client islands (Chapter 3) let a static page hydrate interactive pieces. **Server islands** solve the opposite problem: a mostly static, aggressively cacheable page that contains a few fragments which must be rendered on the server per request: an avatar, a cart badge, a personalised recommendation, a stock indicator. Instead of making the whole page dynamic, you mark the component with `server:defer`; the page ships immediately with fallback content, and the browser fetches the island’s HTML from a special endpoint and swaps it in.

This chapter covers how the directive works on the wire, the fallback slot, how props are encrypted and what that means for deployments (`ASTRO_KEY`, `astro create-key`), what `Astro.url` and the request look like inside an island, how to combine server islands with Svelte client islands, caching and body-size limits, and when to prefer a server island over a client fetch, a live collection or a plain on-demand page. Everything below marked “verified” was observed in a test project (`astro@7.4.1`, `@astrojs/node@11.1.9`, `@astrojs/svelte@9.1.0`, `svelte@5.57.2`).

## The directive

`server:defer` goes on an **Astro component** and requires an adapter:

```html
---
// src/pages/index.astro
import Layout from '../layouts/Layout.astro';
import Avatar from '../components/Avatar.astro';
import GenericAvatar from '../components/GenericAvatar.astro';
---
<Layout title="Home">
  <h1>Welcome</h1>
  <Avatar server:defer>
    <GenericAvatar slot="fallback" />
  </Avatar>
</Layout>
```

```html
---
// src/components/Avatar.astro
const session = Astro.cookies.get('session')?.value;
const user = session ? await lookupUser(session) : null;
---
{user ? <img alt={user.name} src={user.avatar} width="32" height="32" /> : <a href="/login">Sign in</a>}
```

The page can be **prerendered**: the island’s content is not part of the static HTML. Inside the island you can do anything an on-demand page can: read cookies and headers, query a database, set its own response headers. The rest of the page stays a static file.

### `server:defer` is for Astro components, not Svelte

The docs describe `server:defer` on “any component”, and the implied pattern is an Astro component. I tested putting it directly on a Svelte component:

```html
<Counter server:defer start={2}><p slot="fallback">fb</p></Counter>
```

Verified result on 7.4.1: the build succeeded, no `/_server-islands/` request was generated, and the page rendered the Svelte component’s server HTML inline (`<button>n=2</button>`), with no deferral, no fallback and no hydration. The directive is silently ignored for framework components. Do not rely on it. The correct pattern is to wrap the Svelte component in an Astro component and defer that wrapper (see “Combining with Svelte islands”).

## How it works on the wire

At build time (or request time for on-demand pages) each deferred component is replaced by a small block of markup. Here is the shape from my test page (abridged and verified):

```html
<link rel="preload" as="fetch" href="/_server-islands/Who?e=...&p=...&s=" crossorigin="anonymous">
<script>async function replaceServerIsland(id, r) { ... }</script>
<!--[if astro]>server-island-start<![endif]-->
<span>loading</span>   <!-- the fallback slot -->
<script type="module" data-astro-rerun data-island-id="5c8d118f-...">
  const headers = new Headers({});
  let response = await fetch("/_server-islands/Who?e=...&p=...&s=", { headers });
  replaceServerIsland("5c8d118f-...", response);
</script>
```

Key mechanics:

1.  **A dedicated route.** Each deferred component becomes an entry under the reserved path `/_server-islands/<ComponentName>`. Reserved routes win route priority over everything (Chapter 5), so you cannot shadow it with a page.
2.  **Query parameters.** `e` encodes the component export, `p` the encrypted props, `s` the encrypted slots. All are encrypted with the project key.
3.  **GET by default.** Props travel in the encrypted query string so the response can be cached with ordinary `Cache-Control` semantics.
4.  **POST fallback.** Browsers limit practical URL length, so when the URL would exceed **2048 bytes**, the generated script sends a `POST` with the props in a JSON body instead. I verified this by giving a component a 3000-character prop: the emitted script for that island was `fetch("/_server-islands/Panel", { method: "POST", body: JSON.stringify(data) ... })` while the small-prop island used GET.
5.  **Swap.** `replaceServerIsland()` deletes the fallback nodes between the start comment and the script and inserts the returned HTML. It only replaces when the response is `200` with `content-type: text/html`. A non-200 (a 404, a 500, a redirect) leaves the fallback in place, so **an island that fails degrades to its fallback** rather than breaking the page.
6.  **Independence.** Each island is a separate request. A slow island does not delay the others. Islands execute as soon as the script runs, so they all fire in parallel on page load.
7.  **`x-robots-tag: noindex`** is set on island responses, so crawlers do not index fragments.

> **Note:** The inline script uses `data-astro-rerun`, so under `<ClientRouter />` it re-executes after each navigation. Islands therefore re-fetch on every page transition to a page containing them (Chapter 14).

### Why it needs an adapter

The island endpoint is an on-demand route. A static site with no adapter has no runtime to answer it. That is why the docs list server islands among the reasons to install an adapter even for fully static output. In a static build with the Node adapter, my test project built the island routes into the server bundle, while prerendered pages remained files in `dist/client`.

## Fallback content

The named slot `fallback` is rendered with the page and replaced when the island resolves:

```html
<CartBadge server:defer>
  <span slot="fallback" class="badge badge--skeleton" aria-hidden="true">0</span>
</CartBadge>
```

Design guidelines:

- **Reserve the space.** A fallback with a different size causes layout shift when the island swaps in. Match dimensions with CSS (`min-width`, fixed `aspect-ratio`) or render an invisible placeholder of the same size.
- **Make the fallback correct for the common case.** A generic avatar or a “Sign in” link is fine; a skeleton shimmer for content that appears 50 ms later is noise.
- **Fallbacks are static HTML.** The fallback is part of the cached page, so it must not depend on the user.
- **Accessibility.** If the swapped-in content is announced information (a cart count), consider an `aria-live="polite"` wrapper around the island so assistive technology notices the change. The island replaces nodes without announcing them.
- **No fallback, no placeholder.** Without `slot="fallback"` the region is empty until the response arrives.

The fallback is also the content users see when JavaScript is disabled: server islands require JavaScript (the loader is a module script), so the fallback must be an acceptable degraded experience.

## Props, slots and serialization

Props to a deferred component must be serializable by the same mechanism as client-island props (Chapter 3): plain objects, `number`, `string`, `Array`, `Map`, `Set`, `RegExp`, `Date`, `BigInt`, `URL`, `Uint8Array`, `Uint16Array`, `Uint32Array` and `Infinity`. Functions, class instances, render props and circular structures fail.

```html
---
const filters = new Map([['category', 'shoes'], ['size', 42]]);
---
<Recommendations server:defer userId={user.id} since={new Date()} filters={filters} />
```

Slots other than `fallback` are also passed through the encrypted payload, as pre-rendered HTML strings. That means slot content is rendered **when the page renders** and then shipped in the island request. Heavy slot content inflates the URL and pushes you toward the POST fallback; keep slots small or render them inside the island instead.

### Props are encrypted, not authenticated user input

Encryption protects props from being read in the HTML or the URL, and prevents tampering: an attacker cannot craft arbitrary props for your island. It does **not** make the props secret from the *page author*: they are decrypted on the server. Two practical consequences:

- Do not pass raw secrets as props “because they are encrypted”; derive them inside the island from server-side context.
- Do not treat a prop like `userId` as proof of identity. Anyone who can load a cached page can replay the encrypted blob and obtain the island’s HTML for that `userId`. The blob is bound to the page’s build key, not to the viewer. **Personalisation must come from the request (cookies, sessions), not from props baked into a shared page.** The prop `userId` is valid only when the *island itself* verifies the session.

## The encryption key

Astro generates a random key at every build and embeds it in the server bundle; the HTML (or the server rendering the page) encrypts props with it, and the island endpoint decrypts them with the same key. This works trivially for a single deployment unit. It breaks when the encrypting side and the decrypting side are different builds:

| Scenario | Failure |
|------------------------------------|------------------------------------|
| Rolling deploy (Kubernetes, blue/green) | HTML from build N hits a pod on build N+1 |
| Multi-region with staggered rollout | Same |
| CDN caches pages for hours/days | Cached HTML references an old key after you deploy |
| Incremental builds reuse cached pages | Cached output has the old key embedded |

The decrypting server answers invalid payloads with `400`. I verified the message: `400 Bad request: Encrypted componentExport value is invalid.` The client then leaves the fallback in place, so users see the fallback forever, silently.

### `astro create-key` and `ASTRO_KEY`

```bash
$ astro create-key
[crypto] Generated a key to encrypt props passed to server islands. To reuse the same key across builds, set this value as ASTRO_KEY in an environment variable on your build server.

ASTRO_KEY=Q2m/UBV1QfmjIeEkIvpvlHtNoCXk5r/5ZyQUS8ShlqU=
```

(The key above is an example; generate your own.) The key is an encoded symmetric key. Store it as a secret in your CI/CD and host build settings and expose it as `ASTRO_KEY` in the **build** environment. Then every build embeds the same key, so any combination of old HTML and new servers (or the reverse) decrypts correctly.

Operational notes:

- **Rotation** invalidates every cached page embedding old ciphertext. Rotate deliberately, purging CDN HTML at the same time. Incremental builds (Chapter 6) also invalidate pages that render server islands when the key changes, and re-render them every build if the key is not stable.
- **Local development** does not need a pinned key; dev generates one.
- **Do not commit the key** to the repository. Treat it like any signing key.
- Some hosts “handle keeping your front end and back end in sync automatically”, as the docs put it, for simple single-unit deployments. That does not extend to a CDN you operate yourself.
- Adapters that implement skew protection (Netlify, Vercel with `skewProtection`) additionally pin the island request to the deploy that rendered the page, via the deploy id header injected into Astro’s internal fetches.

## Inside the island: request context

A server island runs in “its own isolated context outside of the page request”. The request seen by the component is the island fetch, not the navigation:

```html
---
// src/components/Who.astro
const info = `${Astro.url.pathname} | ${Astro.request.headers.get('referer') ?? 'none'}`;
---
<em>{info}</em>
```

Verified outputs from my test project:

- With the browser’s `Referer` header: `/_server-islands/Who | http://localhost:4400/si?x=1`.
- Without a `Referer`: `/_server-islands/Who | none`.

So `Astro.url` and `Astro.request.url` are always `/_server-islands/<Name>`. To learn what page the island belongs to, you have three options in descending order of preference:

1.  **Pass it as a prop** from the parent: `<Related server:defer path={Astro.url.pathname} />`. For prerendered pages this is the page’s static path, but query parameters are not available at build time.

2.  **Read the `Referer`** header. It carries the full URL including the query string for same-origin fetches. It can be absent or trimmed (privacy settings, `Referrer-Policy: no-referrer`, or `origin` policies strip the path), so treat it as a hint and handle `null`:

    ```html
    ---
    const referer = Astro.request.headers.get('referer');
    const productId = referer ? new URL(referer).searchParams.get('product') : null;
    ---
    ```

    Never make a security decision from the Referer.

3.  **Have the client send what is needed.** Cookies are sent automatically (same-origin). That is the right channel for identity.

### What carries over from the page request

Cookies and headers the browser sends with the island fetch are available through `Astro.cookies` and `Astro.request.headers`; **middleware also runs** for the island request (the verified `x-a` header set by my middleware appeared on the island response), with `Astro.url` showing the island path. Consequently:

- A middleware that gates by `url.pathname` (for example “only `/account/*` requires login”) does not see the page path for island requests. Authentication middleware must either apply to `/_server-islands/*` or the island must check the session itself. The safest design: each island that returns private data verifies the session on its own.
- `locals` populated by middleware are available inside the island, because the island request goes through the pipeline; nothing from the *page’s* `locals` object is carried over, because it is a different request.
- Values set in `Astro.locals` during the page render cannot be read by the island; pass them as props.
- Island responses can set their own headers (verified: `Astro.response.headers.set('Cache-Control', 'public, max-age=60')` in a deferred component’s frontmatter appeared on the island response). The page’s headers are unaffected.

## Combining with Svelte client islands

A deferred Astro component may contain Svelte client islands. The island response is HTML; the `client:*` directives inside it hydrate after the swap:

```html
---
// src/components/Recommendations.astro
import ProductCarousel from './ProductCarousel.svelte';
import { getRecommendations } from '../lib/recs';

interface Props { userId: string }
const { userId } = Astro.props;
const items = await getRecommendations(userId);
Astro.response.headers.set('Cache-Control', 'private, max-age=60');
---
<section aria-labelledby="recs">
  <h2 id="recs">Picked for you</h2>
  <ProductCarousel client:visible items={items} />
</section>
```

```html
<!-- src/components/ProductCarousel.svelte -->
<script lang="ts">
  let { items }: { items: { id: string; name: string; price: number }[] } = $props();
  let index = $state(0);
  const current = $derived(items[index]);
</script>

<div class="carousel">
  <button onclick={() => (index = (index - 1 + items.length) % items.length)} aria-label="Previous">‹</button>
  <article>
    <h3>{current.name}</h3>
    <p>{current.price.toFixed(2)}</p>
  </article>
  <button onclick={() => (index = (index + 1) % items.length)} aria-label="Next">›</button>
</div>
```

I verified a deferred Astro component containing `<Counter client:load start={5} />`: the island response contained the Svelte server HTML plus the `<astro-island>` element and its hydration script. Points to know:

- **The loader is delivered inside the fragment.** The `astro-island` custom element definition and the `Astro.load` bootstrap are inlined in the island’s HTML response (a few kilobytes of script). Astro deduplicates them per page render, but each island response is rendered in isolation, so every island response carries its own copy of the bootstrap; the custom element definition guards with `customElements.get('astro-island')`, so duplicates are harmless but not free. Prefer fewer, larger islands to many tiny ones when they hydrate framework components.
- **Hydration timing.** The directive’s timer starts when the swapped-in fragment executes, not at page load. `client:visible` therefore observes the element after it exists, which is what you want.
- **Props to the Svelte island** travel in the HTML `props` attribute and must be serializable; the server-island encryption only protects the deferred component’s *own* props on the way in.
- **Shared state.** Nano Stores or rune modules loaded by a Svelte island inside a deferred component initialise when that island hydrates, possibly long after other islands on the page; Chapter 4 explains why shared module state must tolerate late joiners.
- **View transitions.** When `<ClientRouter />` navigates, islands are re-requested; use `transition:persist` on stable islands that should survive (Chapter 14).

## Caching

Server islands exist partly to enable **aggressive page caching**: the shell is the same for every visitor, and the personalised parts are fetched separately. There are two cache dimensions.

**The page shell.** A prerendered page is a static file: cache it at the CDN for as long as your deploy cadence allows. If the page itself is on demand, set `Cache-Control` or route caching on it (Chapter 12) knowing that **the page response must not contain user-specific data**; that is the whole point of deferring.

**The island response.** Because the default transport is GET with an encrypted, deterministic query string, the response is cacheable with standard `Cache-Control`:

- Shared across users when the content is not personal, and the props are identical: `public, s-maxage=60, stale-while-revalidate=300`. For example, a “popular items” island with `category` as a prop.
- Per-user when the content is personal: `private, max-age=30`, or `no-store`. Because the URL does not contain a user identifier (identity is in a cookie), a CDN that ignores `Vary: Cookie` would serve one user’s island to another. **Always mark personalised islands `private` or `no-store`.**
- Remember the encrypted URL changes when the key changes or when props change, so cached entries are naturally partitioned by prop values.

**The POST cliff.** Above 2048 bytes of URL, the island switches to POST, and browsers, CDNs and proxies do not cache POST. The docs recommend passing only necessary props: pass an id, not an entire product object; pass a handful of filter values, not an array of 200 ids. My 3000-character prop test confirmed the switch to a JSON body. If an island regularly crosses that threshold, either shrink the props or accept uncached behaviour and cache upstream data instead.

Under the **route caching** feature (Chapter 12) the island request is a request like any other, so `Astro.cache.set({ maxAge, swr, tags })` inside the island applies to that response; tags let you invalidate all cached copies of an island when its data changes.

### Body size limits

POST island requests are bounded by `security.serverIslandBodySizeLimit` (default 1 MB), configured next to `security.actionBodySizeLimit` (Chapter 11):

```js
export default defineConfig({
  security: { serverIslandBodySizeLimit: 256 * 1024 },
});
```

Lower it. A legitimate island payload is small, and the endpoint is publicly reachable. Remember also the adapter-level request body cap (Node `bodySizeLimit`, Chapter 8). Because props are encrypted, an attacker cannot supply arbitrary props, but they can still send large bodies to consume resources; the limit is a defence-in-depth measure.

## Security model summary

- The island endpoint (`/_server-islands/*`) is **publicly reachable** by anyone. Authorisation must be enforced inside the island using the request’s cookies/session, never by the page that embeds it.
- Props are encrypted and tamper-proof, but replayable by anyone holding the page HTML (same key, same ciphertext). They are not an identity.
- A wrong or stale blob returns 400; a thrown error in the island returns an error response; in both cases the fallback stays.
- Content security policy (Chapter 16) must allow the inline module script and `fetch` to same origin; Astro’s CSP support injects hashes for its own scripts.
- Do not put secrets in slots or props to be “protected by encryption”; the island has direct access to server environment anyway.

## Choosing between server islands, client fetch and live collections

| Situation | Best tool | Why |
|------------------------|------------------------|------------------------|
| Personalised fragment on an otherwise static, cacheable page, content is HTML | Server island | No client framework, server secrets, one cached shell |
| Interactive widget that fetches after load and updates repeatedly (search box, live feed) | Svelte island with client `fetch` | Updates need client state; round trips are the feature |
| Data needed at request time for the *whole* page (everything depends on the user) | On-demand page | An island adds a second round trip with no benefit |
| Shared, frequently changing data (inventory, prices) used in many pages | Live collection (+ route cache) | Typed queries, cache hints; render in page or island |
| Fragment depends on a secret API key | Server island or endpoint | The client must never hold the key |
| Slow, non-critical data blocking an on-demand page | Server island | Unblocks the document stream; page stays fast |
| Must work without JavaScript | On-demand page | Islands require JS; the fallback is all that remains |

Server islands and live collections combine naturally: a prerendered product page with a `<Stock sku={sku} server:defer />` whose frontmatter calls `getLiveEntry('inventory', { sku })` and sets `Astro.cache.set(cacheHint)` gives you static product HTML, a fresh stock badge and tag-based invalidation (Chapter 20 builds this).

A rule of thumb for senior reviews: **if the island is going to be rendered on every request anyway, make the page on demand and skip the island.** Islands pay off when the shell is cached and the fragment is small, or when the fragment is slow enough that streaming it separately improves perceived performance.

## A complete example: personalised header

```html
---
// src/layouts/Layout.astro
import SiteHeader from '../components/SiteHeader.astro';
const { title } = Astro.props;
---
<html lang="en">
  <head><meta charset="utf-8" /><title>{title}</title></head>
  <body>
    <SiteHeader server:defer>
      <header slot="fallback" class="site-header" style="min-height:56px">
        <a href="/">Shop</a> <a href="/login">Sign in</a>
      </header>
    </SiteHeader>
    <main><slot /></main>
  </body>
</html>
```

```html
---
// src/components/SiteHeader.astro
import CartButton from './CartButton.svelte';
import { getUser, getCartCount } from '../lib/session';

const sid = Astro.cookies.get('sid')?.value;
const user = sid ? await getUser(sid) : null;
const count = user ? await getCartCount(user.id) : 0;

Astro.response.headers.set('Cache-Control', 'private, no-store');
---
<header class="site-header" style="min-height:56px">
  <a href="/">Shop</a>
  {user ? <span>Hi, {user.name}</span> : <a href="/login">Sign in</a>}
  <CartButton client:idle initial={count} />
</header>
```

```html
<!-- src/components/CartButton.svelte -->
<script lang="ts">
  let { initial = 0 }: { initial?: number } = $props();
  let count = $state(initial);

  $effect(() => {
    const onAdd = (e: Event) => (count += (e as CustomEvent<{ qty: number }>).detail.qty);
    window.addEventListener('cart:add', onAdd);
    return () => window.removeEventListener('cart:add', onAdd);
  });
</script>

<a href="/cart" aria-label="Cart, {count} items">Cart ({count})</a>
```

Properties of this design: the layout is cacheable for everyone; the header is one extra request; the island carries `private, no-store`; identity comes from the `sid` cookie, not from props; the fallback has a fixed `min-height` so the swap causes no shift; and the cart badge stays live through a window event (Chapter 4) after hydration.

## Testing and debugging

- **Inspect the loader.** View source and look for `/_server-islands/`. Open the URL in a new tab to see the raw HTML the island returns (the encrypted URL is valid for the current build).
- **Simulate failure.** Return a non-200 from the island and confirm the fallback survives.
- **Check the Referer path.** Test with `Referrer-Policy: no-referrer` to ensure your island handles a missing header.
- **Playwright/E2E.** Wait for the island’s content (`await expect(page.getByText('Hi, Ann')).toBeVisible()`) rather than for `load`, since the swap happens after the initial render.
- **Container API.** Server islands rely on the router; unit-test the *component* by rendering it directly as an Astro component (Chapter 17) and cover the wiring in E2E.

## Key takeaways

- `server:defer` works on Astro components and needs an adapter; on Svelte components it is silently ignored (verified), so wrap the Svelte component in an Astro one.
- The page ships with the `fallback` slot; a script fetches `/_server-islands/<Name>` and swaps the HTML in only on a 200 `text/html` response, so failures degrade to the fallback.
- Props and slots are encrypted into the URL (GET, cacheable). Above 2048 bytes of URL the request becomes a POST with a JSON body, which breaks caching: pass ids, not objects.
- Encryption uses a per-build random key. Rolling deploys, multi-region rollouts and CDN-cached HTML need a stable `ASTRO_KEY` created with `astro create-key` and set in the build environment; otherwise islands return 400 and stay on their fallback.
- Inside an island `Astro.url` is `/_server-islands/<Name>`; get the page from props or the `Referer` header (may be missing). Cookies and headers are available; middleware runs for the island request with the island path.
- Authorise inside the island using cookies/sessions. Props are replayable by anyone with the page HTML and are not identity.
- Mark personalised island responses `private` or `no-store`; share only non-personal islands.
- Svelte islands inside a deferred Astro component hydrate after the swap; each island response carries its own bootstrap script.
- Choose server islands for small personalised or slow fragments on cached pages; choose on-demand pages when everything is dynamic, client fetch for continuously updating widgets, live collections for shared fresh data.
- `security.serverIslandBodySizeLimit` bounds the POST body (default 1 MB); lower it.

## Review Questions

1.  What are the two requirements to use `server:defer`, and what happens if you put it on a Svelte component?

2.  Describe the request flow from page load to the island’s HTML appearing, naming the route prefix and the query parameters.

3.  When does the island request use POST instead of GET, and what is the practical consequence?

4.  What does the browser show if the island endpoint returns 500? What if it returns 200 with `application/json`?

5.  Find the problem:

    ```html
    <Greeting server:defer userId={Astro.locals.user.id} />
    ```

    where `Greeting.astro` renders private account data based only on the `userId` prop.

6.  What value does `Astro.url.pathname` have inside a server island, and how can the island learn the page’s query string?

7.  Give two reasons not to rely solely on the `Referer` header.

8.  An auth middleware protects only paths starting with `/account`. A page `/account/orders` embeds a deferred island that returns the orders. Why is that unsafe, and how do you fix it?

9.  Why does a rolling Kubernetes deploy sometimes leave pages stuck on their fallback content? How do you diagnose it and what is the fix?

10. Where must `ASTRO_KEY` be set: build, runtime or both? What happens on rotation?

11. Which of these props can be passed to a server island? (a) `new Map()` (b) `() => 1` (c) a class instance (d) `new Date()` (e) an object with a circular reference.

12. Multiple choice: which Cache-Control is appropriate for an island showing the signed-in user’s cart? (a) `public, s-maxage=3600` (b) `private, no-store` (c) `public, immutable` (d) none, caching is automatic.

13. Why should a fallback reserve the island’s dimensions?

14. An island has `slot="fallback"` content that shows the user’s name from a cookie, rendered in the page frontmatter. What is wrong?

15. A deferred Astro component contains `<Chart client:visible data={data} />`. When does the `client:visible` observer start, and where does the hydration script come from?

16. How can you set a cache policy for the island response without affecting the page response?

17. A server island’s URL exceeds the limit because you pass a 300-element array of ids. List two ways to fix it.

18. What does `security.serverIslandBodySizeLimit` bound, and what is its default?

19. A page is prerendered with 40 server islands, each hydrating a Svelte component. What cost do you incur and how can you reduce it?

20. Incremental builds are enabled and pages contain server islands but `ASTRO_KEY` is not set. What happens to caching of those pages?

21. Which route-priority category is `/_server-islands/*` in, and what does that mean for your pages?

22. Explain why `<ClientRouter />` makes islands re-fetch on every navigation, and which directive keeps a Svelte island alive across navigations.

23. Design: choose among server island, on-demand page and client fetch for (a) a logged-in header on a static marketing site, (b) a typeahead search, (c) a dashboard where all content is user-specific, (d) a “recently viewed” list that is slow to compute. Justify each.

24. Design: sketch a prerendered product page that shows a live stock badge. Which APIs combine, what is cached where, and how is it invalidated?

25. What does the swap script do to the fallback nodes, and why can this cause layout shift?

26. Why is it risky to rely on encryption of props for secrecy of a value that the page author passes?

27. How would you test that an island’s fallback survives failure in Playwright?
