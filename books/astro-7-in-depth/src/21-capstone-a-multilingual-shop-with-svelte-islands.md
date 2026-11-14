# Chapter 20: Capstone: A Multilingual Shop with Svelte Islands

This chapter assembles the book’s threads into one buildable project: a small bilingual (English and Bulgarian) online shop. It has a build-time product catalogue, live inventory from an external system, a cart that lives in the server-side session and is mirrored in a Svelte 5 rune module, a personalised header delivered as a server island, route caching with tag-based invalidation from a webhook, i18n routing, a `<ClientRouter />` with a persisted cart island, a typed environment schema and security hardening, and a test suite spanning Vitest, the Container API and Playwright. Every file below is the real file from a project I built and ran against Astro 7.4.1, `@astrojs/svelte` 9.1.0, Svelte 5.57.2 and `@astrojs/node` 11.1.9. The HTTP transcripts quoted in the chapter are real output from the built server. The Playwright spec could not be executed in my environment because no browsers are installed; it is clearly marked and follows the patterns from Chapter 17.

The point of the exercise is the decisions: where each piece of state lives, which route is prerendered, cached or personalised, and what each feature costs in complexity. Read it as a design review with code attached.

## Architecture and rendering decisions

| Concern | Decision | Why |
|------------------------|------------------------|------------------------|
| Output | `output: 'server'` with the Node adapter | Actions, sessions, live collections, route caching and server islands all need on-demand rendering |
| Product catalogue | Build-time collection (`glob` over JSON) | Rarely changes; validated by Zod; no runtime cost |
| Stock levels | Live collection with a custom loader | Must be current; changes without a rebuild |
| Catalogue and product pages | On-demand, cached 60 s with `swr: 300`, tags from the live loader’s cache hints | Mostly static for all users; stock changes invalidate only the affected page |
| Cart page | On-demand, `cache.set(false)` | Per-user |
| Personalised greeting | Server island (`server:defer`) | Keeps the surrounding page cacheable |
| Cart badge | Svelte island, `client:load`, `transition:persist` | Needs client state across navigations |
| Cart source of truth | Server-side session | Survives reloads, usable without JavaScript, validated server-side |
| Cart client mirror | `.svelte.ts` rune module (`CartStore`) | Shared by several islands on a page; updated only from browser events |
| Mutations | Astro Actions with `accept: 'form'` | One handler serves HTML forms and JS calls |
| i18n | Prefixed routes (`/en/`, `/bg/`), `[locale]` dynamic segment, UI strings in a typed module, product text in the collection | Explicit, cache-friendly URLs |
| CSP | Not enabled in this build | `<ClientRouter />` is incompatible with CSP (Chapter 16); see “Hardening” |

Notice that none of the pages is prerendered. In a real shop you would prerender marketing pages (`export const prerender = true`) and keep only stock-sensitive routes on-demand. I made the catalogue on-demand to demonstrate live stock plus tag invalidation; a stricter design would prerender the catalogue and render stock as a server island.

### Project layout

```text
astro.config.mjs
src/
  env.d.ts
  content.config.ts            build-time collection
  live.config.ts               live collection
  content/products/*.json
  actions/index.ts             cart and profile actions
  middleware.ts                request logging
  i18n/ui.ts                   strings and money formatting
  lib/cart-logic.ts            pure cart functions
  lib/cart.svelte.ts           client-side rune store
  lib/inventory-store.ts       stand-in for a warehouse API
  lib/inventory-loader.ts      live loader
  components/                  Header, Greeting (server island), CartBadge, AddToCart
  layouts/Layout.astro
  pages/index.astro            redirect to /en/
  pages/[locale]/index.astro, cart.astro, products/[slug].astro
  pages/api/inventory-webhook.ts
tests/                         Vitest (logic, container)
e2e/shop.spec.ts               Playwright
```

## Configuration

```js
// astro.config.mjs
import { defineConfig, envField, memoryCache } from 'astro/config';
import node from '@astrojs/node';
import svelte from '@astrojs/svelte';

export default defineConfig({
  site: 'https://shop.example.com',
  output: 'server',
  adapter: node({ mode: 'standalone' }),
  integrations: [svelte()],
  i18n: {
    locales: ['en', 'bg'],
    defaultLocale: 'en',
    routing: { prefixDefaultLocale: true, redirectToDefaultLocale: true },
  },
  cache: { provider: memoryCache() },
  routeRules: {
    '/[locale]': { maxAge: 60, swr: 300, tags: ['catalog'] },
    '/[locale]/products/[slug]': { maxAge: 60, swr: 300, tags: ['catalog'] },
  },
  security: {
    checkOrigin: true,
    actionBodySizeLimit: 64 * 1024,
    serverIslandBodySizeLimit: 64 * 1024,
  },
  env: {
    validateSecrets: false,
    schema: {
      PUBLIC_CURRENCY: envField.string({ context: 'client', access: 'public', default: 'EUR' }),
      WEBHOOK_SECRET: envField.string({ context: 'server', access: 'secret', min: 8 }),
      MAX_QTY_PER_LINE: envField.number({ context: 'server', access: 'public', default: 10, int: true, gt: 0 }),
    },
  },
});
```

Points worth defending in review:

- `i18n.routing: { prefixDefaultLocale: true, redirectToDefaultLocale: true }` recreates the pre-6.0 behaviour of redirecting the root to the default locale (Chapter 19). With `prefixDefaultLocale: true` Astro requires a root `src/pages/index.astro`; omitting it fails the build with `MissingIndexForInternationalization`, which I hit on my first build. The root index here just redirects to `/en/`.
- `routeRules` patterns use the same syntax as routing: `/[locale]` and `/[locale]/products/[slug]`. Glob wildcards are not supported. The cart route has no rule and additionally calls `cache.set(false)`.
- `memoryCache()` is an in-process cache: correct for a single Node instance, wrong for several (each has its own cache, and invalidation reaches only the instance that received the webhook). In production on a CDN-backed host, switch to the adapter’s CDN provider (experimental, Chapter 12) or put a shared cache in front.
- The environment schema separates a client-public value (`PUBLIC_CURRENCY`), a server secret (`WEBHOOK_SECRET`, with `min: 8`) and a server-public tunable (`MAX_QTY_PER_LINE`). `validateSecrets` is off here so that a build does not require the secret; set it to `true` in CI to fail fast (Chapter 16).
- Body-size limits for actions and server islands are lowered from the 1 MB default.

```ts
// src/env.d.ts
/// <reference types="astro/client" />
declare namespace App {
  interface SessionData {
    cart: { sku: string; qty: number }[];
    name?: string;
  }
}
```

`App.SessionData` types `Astro.session.get('cart')` and friends.

## Content: build-time catalogue and live inventory

```ts
// src/content.config.ts
import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

const localized = z.object({ en: z.string(), bg: z.string() });

const products = defineCollection({
  loader: glob({ pattern: '*.json', base: './src/content/products' }),
  schema: z.object({
    sku: z.string(),
    price: z.number().int().positive(), // cents
    name: localized,
    description: localized,
  }),
});

export const collections = { products };
```

Localised text lives inside each entry (`name.en`, `name.bg`), validated by Zod. The alternative, one entry per locale, is better when translators work on separate files or when locales have different content; the single-entry shape is better when every product exists in every locale and you want the type system to enforce that.

The inventory is an external system, modelled here by an in-memory store that stands in for a warehouse API:

```ts
// src/lib/inventory-store.ts
// Stand-in for a warehouse API. Module state is fine here because it models an
// EXTERNAL system; real code would call fetch() against the backend.
const stock = new Map<string, number>([
  ['mug', 12],
  ['lamp', 3],
  ['notebook', 0],
]);

export async function readStock(sku: string): Promise<number | undefined> {
  return stock.get(sku);
}
export async function readAllStock(): Promise<Array<{ sku: string; qty: number }>> {
  return [...stock].map(([sku, qty]) => ({ sku, qty }));
}
export function setStock(sku: string, qty: number) {
  stock.set(sku, qty);
}
```

The live loader wraps it:

```ts
// src/lib/inventory-loader.ts
import type { LiveLoader } from 'astro/loaders';
import { readAllStock, readStock } from './inventory-store';

export interface Stock { id: string; qty: number }

export function inventoryLoader(): LiveLoader<Stock, { id: string }, Record<string, never>> {
  return {
    name: 'inventory-loader',
    async loadCollection() {
      const rows = await readAllStock();
      return {
        entries: rows.map((r) => ({
          id: r.sku,
          data: { id: r.sku, qty: r.qty },
          cacheHint: { tags: [`sku:${r.sku}`] },
        })),
        // The list depends on every SKU, so it carries every per-SKU tag.
        cacheHint: { tags: ['inventory', ...rows.map((r) => `sku:${r.sku}`)] },
      };
    },
    async loadEntry({ filter }) {
      const qty = await readStock(filter.id);
      if (qty === undefined) return undefined as never; // -> LiveEntryNotFoundError
      return {
        id: filter.id,
        data: { id: filter.id, qty },
        cacheHint: { tags: [`sku:${filter.id}`] },
      };
    },
  };
}
```

```ts
// src/live.config.ts
import { defineLiveCollection } from 'astro:content';
import { inventoryLoader } from './lib/inventory-loader';

export const collections = { inventory: defineLiveCollection({ loader: inventoryLoader() }) };
```

Two details matter. First, each entry carries a `cacheHint` with `tags: ['sku:<id>']`, while the collection-level hint carries `inventory` plus every per-SKU tag, because the list depends on all of them. A route that calls `Astro.cache.set(cacheHint)` adopts those tags, which is what lets the webhook later invalidate exactly the pages that displayed that SKU. Second, when a SKU is unknown, `loadEntry` returns `undefined`, and Astro turns that into a `LiveEntryNotFoundError` for the caller (the cast in the loader is only there to satisfy the return type; in a typed loader you would model “not found” with the error classes from `astro/content/runtime`).

> **Note:** Live collections require an adapter, do not support MDX and do not optimise images (Chapter 6). They suit stock, prices and availability, not product descriptions.

## Internationalisation

```ts
// src/i18n/ui.ts
export const locales = ['en', 'bg'] as const;
export type Locale = (typeof locales)[number];

export const ui = {
  en: { shop: 'Shop', cart: 'Cart', add: 'Add to cart', soldOut: 'Sold out', inStock: (n: number) => `${n} in stock`,
        empty: 'Your cart is empty', remove: 'Remove', total: 'Total', hello: (n: string) => `Hello, ${n}`, guest: 'Welcome, guest' },
  bg: { shop: 'Магазин', cart: 'Количка', add: 'Добави в количката', soldOut: 'Изчерпан', inStock: (n: number) => `${n} налични`,
        empty: 'Количката е празна', remove: 'Премахни', total: 'Общо', hello: (n: string) => `Здравей, ${n}`, guest: 'Добре дошли' },
} satisfies Record<Locale, Record<string, string | ((x: never) => string)>>;

export function t(locale: string | undefined) {
  return ui[(locale as Locale) in ui ? (locale as Locale) : 'en'];
}

export function formatMoney(cents: number, locale: string, currency = 'EUR') {
  return new Intl.NumberFormat(locale === 'bg' ? 'bg-BG' : 'en-GB', { style: 'currency', currency }).format(cents / 100);
}
```

UI strings are a plain typed module: server components and Svelte islands import the same object, so there is no second translation system on the client. `formatMoney` uses `Intl.NumberFormat`, so `1200` cents is `€12.00` in English and `12,00 €` in Bulgarian (verified in a test and in the HTTP transcript: `Общо: 36,00 €`).

The routing is a `[locale]` dynamic segment, validated at the top of each page. A route parameter that is not a known locale returns 404 explicitly, because `[locale]` would otherwise match any first path segment. An alternative is to create real `en/` and `bg/` directories, which avoids the check and works better with Astro’s fallback logic but duplicates page files; helpers such as `getRelativeLocaleUrl()` work with both.

> **Warning:** islands receive translated strings as props. Do not import `ui.ts` and call `t()` on the client based on `document.documentElement.lang` to avoid prop passing: the first render would then differ between server and client. Resolve the locale on the server and pass strings, as `Header.astro` does.

## Pages

The catalogue page combines the build-time collection with live stock:

```html
---
// src/pages/[locale]/index.astro
import { getCollection, getLiveCollection } from 'astro:content';
import { getRelativeLocaleUrl } from 'astro:i18n';
import Layout from '../../layouts/Layout.astro';
import { formatMoney, locales, t } from '../../i18n/ui';
import { PUBLIC_CURRENCY } from 'astro:env/client';
import { actions } from 'astro:actions';

export const prerender = false;
const { locale } = Astro.params;
if (!locale || !(locales as readonly string[]).includes(locale)) return new Response(null, { status: 404 });
const strings = t(locale);

const products = await getCollection('products');
const { entries: stock, cacheHint } = await getLiveCollection('inventory');
if (Astro.cache.enabled && cacheHint) Astro.cache.set(cacheHint);
const qtyOf = new Map(stock?.map((s) => [s.id, s.data.qty]));
const nameResult = Astro.getActionResult(actions.profile.setName);
---
<Layout title={strings.shop}>
  <h1>{strings.shop}</h1>
  <ul>
    {products.map((p) => (
      <li>
        <a href={getRelativeLocaleUrl(locale, `products/${p.id}`)}>{p.data.name[locale as 'en' | 'bg']}</a>
        — {formatMoney(p.data.price, locale, PUBLIC_CURRENCY)}
        — {(qtyOf.get(p.id) ?? 0) > 0 ? strings.inStock(qtyOf.get(p.id)!) : strings.soldOut}
      </li>
    ))}
  </ul>
  <form method="POST" action={actions.profile.setName} data-astro-reload>
    <input name="name" required placeholder="name" />
    <button>OK</button>
    {nameResult?.error && <p role="alert">{nameResult.error.message}</p>}
  </form>
</Layout>
```

`getLiveCollection('inventory')` returns `{ entries, cacheHint }`. The page passes the collection-level hint to `Astro.cache.set`, adding the `inventory` and per-SKU tags to the route rule’s `catalog` tag (tags accumulate; scalars like `maxAge` come from the rule). The `Astro.cache.enabled` guard keeps the page working in `astro dev`, where caching is a no-op.

The product page:

```html
---
// src/pages/[locale]/products/[slug].astro
import { getEntry, getLiveEntry } from 'astro:content';
import { getRelativeLocaleUrl } from 'astro:i18n';
import Layout from '../../../layouts/Layout.astro';
import AddToCart from '../../../components/AddToCart.svelte';
import { formatMoney, locales, t } from '../../../i18n/ui';
import { PUBLIC_CURRENCY } from 'astro:env/client';
import { actions } from 'astro:actions';

export const prerender = false;
const { locale, slug } = Astro.params;
if (!locale || !slug || !(locales as readonly string[]).includes(locale)) return new Response(null, { status: 404 });
const l = locale as 'en' | 'bg';
const strings = t(l);

const product = await getEntry('products', slug);
if (!product) return new Response(null, { status: 404 });

const { entry: stock, cacheHint } = await getLiveEntry('inventory', { id: slug });
if (Astro.cache.enabled && cacheHint) Astro.cache.set(cacheHint); // tags: inventory, sku:<slug>
const qty = stock?.data.qty ?? 0;
---
<Layout title={product.data.name[l]}>
  <h1>{product.data.name[l]}</h1>
  <p>{product.data.description[l]}</p>
  <p>{formatMoney(product.data.price, locale, PUBLIC_CURRENCY)} — <span data-testid="stock">{qty > 0 ? strings.inStock(qty) : strings.soldOut}</span></p>

  <!-- Progressive enhancement: a plain form POST works without JavaScript. -->
  <form method="POST" action={getRelativeLocaleUrl(l, 'cart') + actions.cart.add} id="add-form">
    <input type="hidden" name="sku" value={product.id} />
    <button type="submit" disabled={qty < 1}>{strings.add}</button>
  </form>
  <AddToCart client:visible sku={product.id} label={strings.add} disabled={qty < 1} />
</Layout>
```

Here the entry-level hint contributes `sku:<slug>`, the same tag the list page carries. The page contains a plain HTML form that posts to the cart route with the action’s query string appended (`getRelativeLocaleUrl(l, 'cart') + actions.cart.add` evaluates to `/en/cart/?_action=cart.add`), plus the Svelte island that does the same through `fetch`. Without JavaScript the form works; with JavaScript the island is `client:visible`, so it costs nothing until scrolled into view. Both are rendered; in a polished UI you would hide the plain form once the island hydrates.

The cart page:

```html
---
// src/pages/[locale]/cart.astro
import { getEntry } from 'astro:content';
import { getRelativeLocaleUrl } from 'astro:i18n';
import { actions } from 'astro:actions';
import Layout from '../../layouts/Layout.astro';
import { formatMoney, locales, t } from '../../i18n/ui';
import { PUBLIC_CURRENCY } from 'astro:env/client';
import { total } from '../../lib/cart-logic';

export const prerender = false;
const { locale } = Astro.params;
if (!locale || !(locales as readonly string[]).includes(locale)) return new Response(null, { status: 404 });
const l = locale as 'en' | 'bg';
const strings = t(l);

Astro.cache.set(false); // per-user page: never cache
const result = Astro.getActionResult(actions.cart.add) ?? Astro.getActionResult(actions.cart.remove);
const lines = (await Astro.session?.get('cart')) ?? [];
const products = new Map(
  (await Promise.all(lines.map((x) => getEntry('products', x.sku)))).filter(Boolean).map((p) => [p!.id, p!]),
);
const sum = total(lines, (sku) => products.get(sku)?.data.price ?? 0);
---
<Layout title={strings.cart}>
  <h1>{strings.cart}</h1>
  <div hidden data-cart-lines={JSON.stringify(lines)}></div>
  {result?.error && <p role="alert">{result.error.message}</p>}
  {lines.length === 0 ? <p>{strings.empty}</p> : (
    <ul>
      {lines.map((x) => (
        <li data-testid="line">
          {products.get(x.sku)?.data.name[l] ?? x.sku} × {x.qty}
          <form method="POST" action={getRelativeLocaleUrl(l, 'cart') + actions.cart.remove} style="display:inline">
            <input type="hidden" name="sku" value={x.sku} />
            <button>{strings.remove}</button>
          </form>
        </li>
      ))}
    </ul>
  )}
  <p>{strings.total}: {formatMoney(sum, l, PUBLIC_CURRENCY)}</p>
</Layout>
```

`Astro.cache.set(false)` opts out of caching explicitly. The hidden `data-cart-lines` element is how the server hands the authoritative cart to the client after a full-document or router navigation (see the store below). The page reads `Astro.getActionResult()` to show errors from a no-JS form post.

The root redirect:

```html
---
// src/pages/index.astro: the root index required by i18n; redirects to the default locale.
return Astro.redirect('/en/');
---
```

## Cart: actions, sessions and a rune store

All cart arithmetic is pure and shared, so it is testable without Astro:

```ts
// src/lib/cart-logic.ts: pure functions shared by actions, islands and tests.
export interface CartLine { sku: string; qty: number }

export function addLine(lines: CartLine[], sku: string, qty: number, max: number): CartLine[] {
  const next = lines.map((l) => ({ ...l }));
  const found = next.find((l) => l.sku === sku);
  if (found) found.qty = Math.min(found.qty + qty, max);
  else next.push({ sku, qty: Math.min(qty, max) });
  return next;
}

export function removeLine(lines: CartLine[], sku: string): CartLine[] {
  return lines.filter((l) => l.sku !== sku);
}

export function count(lines: CartLine[]): number {
  return lines.reduce((n, l) => n + l.qty, 0);
}

export function total(lines: CartLine[], priceOf: (sku: string) => number): number {
  return lines.reduce((sum, l) => sum + priceOf(l.sku) * l.qty, 0);
}
```

The actions are the only writers of the cart:

```ts
// src/actions/index.ts
import { defineAction, ActionError } from 'astro:actions';
import { z } from 'astro/zod';
import { getEntry, getLiveEntry } from 'astro:content';
import { MAX_QTY_PER_LINE } from 'astro:env/server';
import { addLine, removeLine, type CartLine } from '../lib/cart-logic';

async function readCart(session: { get(k: 'cart'): Promise<CartLine[] | undefined> } | undefined) {
  if (!session) throw new ActionError({ code: 'INTERNAL_SERVER_ERROR', message: 'Sessions are not configured' });
  return (await session.get('cart')) ?? [];
}

export const server = {
  cart: {
    get: defineAction({
      handler: async (_input, ctx) => ({ lines: await readCart(ctx.session) }),
    }),
    add: defineAction({
      accept: 'form',
      input: z.object({ sku: z.string().min(1), qty: z.coerce.number().int().min(1).max(99).default(1) }),
      handler: async ({ sku, qty }, ctx) => {
        const product = await getEntry('products', sku);
        if (!product) throw new ActionError({ code: 'NOT_FOUND', message: `Unknown product ${sku}` });
        const { entry: stock } = await getLiveEntry('inventory', { id: sku });
        if (!stock || stock.data.qty < 1) throw new ActionError({ code: 'CONFLICT', message: 'Sold out' });
        const lines = addLine(await readCart(ctx.session), sku, qty, Math.min(MAX_QTY_PER_LINE, stock.data.qty));
        ctx.session!.set('cart', lines);
        return { lines };
      },
    }),
    remove: defineAction({
      accept: 'form',
      input: z.object({ sku: z.string().min(1) }),
      handler: async ({ sku }, ctx) => {
        const lines = removeLine(await readCart(ctx.session), sku);
        ctx.session!.set('cart', lines);
        return { lines };
      },
    }),
  },
  profile: {
    setName: defineAction({
      accept: 'form',
      input: z.object({ name: z.string().trim().min(1).max(40) }),
      handler: async ({ name }, ctx) => {
        // A real login would verify credentials, then rotate the session id:
        ctx.session?.regenerate();
        ctx.session?.set('name', name);
        return { name };
      },
    }),
  },
};
```

Security properties of this file:

- Every handler validates input with Zod and re-checks reality: product existence from the collection, stock from the live collection, and a per-line maximum of `min(MAX_QTY_PER_LINE, stock)`. The client is never trusted for price or quantity limits. Prices are not stored in the cart at all; the cart page computes totals from the collection.
- `accept: 'form'` means the HTTP surface is a form POST subject to `checkOrigin` (the cross-origin test below returns 403), while JavaScript callers pass a `FormData` through the same typed client.
- `profile.setName` calls `session.regenerate()` before writing, the fixation defence from Chapter 16. A real login would verify credentials first; the example stands in for it.
- The session cookie is `httpOnly`, `secure`, `sameSite: lax` by default; session storage is the Node adapter’s filesystem default here and must be replaced by a shared driver (Redis) for multiple instances (Chapter 12).

The client mirror is a rune module:

```ts
// src/lib/cart.svelte.ts: client-side mirror of the server-side (session) cart.
// IMPORTANT: this module is also evaluated during SSR. It must never be written
// to on the server; every mutation below is reached only from browser events.
import { actions } from 'astro:actions';
import { count, type CartLine } from './cart-logic';

class CartStore {
  lines = $state<CartLine[]>([]);
  ready = $state(false);
  pending = $state(false);
  error = $state<string | null>(null);
  count = $derived(count(this.lines));

  async load() {
    if (this.ready) return;
    const { data } = await actions.cart.get();
    if (data) this.lines = data.lines;
    this.ready = true;
  }

  async add(sku: string, qty = 1) {
    this.pending = true;
    this.error = null;
    const form = new FormData();
    form.set('sku', sku);
    form.set('qty', String(qty));
    const { data, error } = await actions.cart.add(form);
    if (error) this.error = error.message;
    else if (data) { this.lines = data.lines; this.ready = true; }
    this.pending = false;
  }

  /** Called after every navigation: the cart page embeds the server-side lines. */
  syncFromDom() {
    const el = document.querySelector<HTMLElement>('[data-cart-lines]');
    if (!el) return;
    try {
      this.lines = JSON.parse(el.dataset.cartLines ?? '[]');
      this.ready = true;
    } catch { /* ignore malformed markup */ }
  }
}

export const cart = new CartStore();

if (typeof document !== 'undefined') {
  // Fires after every ClientRouter navigation (and on first load).
  document.addEventListener('astro:page-load', () => cart.syncFromDom());
}
```

This file is the one place where the book’s earlier warnings about module state collide, so it is worth reading slowly:

- Module-level state is shared by every island on the page (they import the same module instance in the browser). That is exactly what we want: `CartBadge` and `AddToCart` read and write the same `cart` object, and no wiring is needed.
- The same module is evaluated during SSR, where a module-level object is shared by **all requests** (Chapter 4). So the rule is: nothing on the server may write to `cart`. Every mutation (`load`, `add`, `syncFromDom`) is reached only from browser events or `onMount`. Server rendering sees the initial empty state, and the badge shows an ellipsis until `ready`. That makes the SSR output identical for all users, which is a prerequisite for caching the page.
- `actions` from `astro:actions` works on the client; calls go to `/_actions/cart.add`, and errors come back as values (`{ data, error }`), not exceptions.
- The `astro:page-load` listener runs after each router navigation. After a form post to the cart page via `<ClientRouter />`, the swapped-in page contains the authoritative lines, and the store re-syncs from the DOM. This covers the case in which the cart is changed by the no-JS form path, which the island otherwise would not know about. A guard `typeof document` keeps the SSR evaluation inert.

The islands:

```html
<!-- src/components/CartBadge.svelte -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { cart } from '../lib/cart.svelte';

  let { label, href }: { label: string; href: string } = $props();

  onMount(() => { cart.load(); });
</script>

<a {href} class="badge" aria-label={`${label}: ${cart.count}`}>
  {label}
  <span class="n" data-testid="cart-count">{cart.ready ? cart.count : '…'}</span>
</a>

<style>
  .badge { display: inline-flex; gap: .4rem; align-items: center; text-decoration: none; }
  .n { background: #222; color: #fff; border-radius: 999px; padding: 0 .5rem; min-width: 1.4rem; text-align: center; }
</style>
```

```html
<!-- src/components/AddToCart.svelte -->
<script lang="ts">
  import { cart } from '../lib/cart.svelte';

  let { sku, label, disabled = false }: { sku: string; label: string; disabled?: boolean } = $props();
</script>

<button type="button" disabled={disabled || cart.pending} onclick={() => cart.add(sku)} data-testid="add">
  {label}
</button>
{#if cart.error}<p role="alert">{cart.error}</p>{/if}
```

`CartBadge` calls `cart.load()` in `onMount`, which fetches the session cart once. Because the island is persisted across navigations (next section), that happens once per browser session, not once per page. Both components use runes only (`$props`, no legacy syntax).

## Personalisation with a server island

```html
---
// src/components/Greeting.astro: rendered as a server island (see Header).
import { t } from '../i18n/ui';
interface Props { locale: string }
const { locale } = Astro.props;
const name = await Astro.session?.get('name');
const strings = t(locale);
---
<span data-testid="greeting">{name ? strings.hello(name) : strings.guest}</span>
```

```html
---
// src/components/Header.astro
import { getRelativeLocaleUrl } from 'astro:i18n';
import CartBadge from './CartBadge.svelte';
import Greeting from './Greeting.astro';
import { t, locales } from '../i18n/ui';

const locale = Astro.currentLocale ?? 'en';
const strings = t(locale);
const rest = Astro.url.pathname.replace(new RegExp(`^/(${locales.join('|')})/?`), '');
---
<header>
  <a href={getRelativeLocaleUrl(locale, '')}>{strings.shop}</a>
  <nav aria-label="language">
    {locales.map((l) => (
      <a href={getRelativeLocaleUrl(l, rest)} hreflang={l} aria-current={l === locale ? 'true' : undefined}>{l.toUpperCase()}</a>
    ))}
  </nav>
  <Greeting server:defer locale={locale}>
    <span slot="fallback">…</span>
  </Greeting>
  <CartBadge client:load transition:persist="cart-badge" label={strings.cart} href={getRelativeLocaleUrl(locale, 'cart')} />
</header>
```

`Greeting` reads the session, which makes its output per-user. The surrounding page is cached for all users, so the greeting is deferred: the page carries a small script that fetches `/_server-islands/Greeting?e=...&p=...` and swaps the result in. The props (here only `locale`) are encrypted in the URL. I confirmed the behaviour with `curl`:

```bash
# cookie jar with a session in which name = "Ada"
curl -s -b cj.txt "$BASE/_server-islands/Greeting?e=...&p=...&s=" | grep -o 'data-testid="greeting">[^<]*'
# data-testid="greeting">Hello, Ada
# the same URL without the cookie:
# data-testid="greeting">Welcome, guest
```

Two things to note. The locale is passed as a prop, because inside a server island `Astro.url` is the island endpoint, not the page (Chapter 9). And the island URL is a GET: if CDN caching is in front, make sure the greeting response is not shared (`Cache-Control: private, no-store`); a CDN in front may cache GET island requests unless the response says otherwise.

The language switcher builds each link from the current pathname minus its locale prefix, so `/en/products/lamp/` links to `/bg/products/lamp/`.

## Layout with `<ClientRouter />` and a persisted island

```html
---
// src/layouts/Layout.astro
import { ClientRouter } from 'astro:transitions';
import Header from '../components/Header.astro';
interface Props { title: string }
const { title } = Astro.props;
const locale = Astro.currentLocale ?? 'en';
---
<!doctype html>
<html lang={locale}>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width" />
    <title>{title}</title>
    <ClientRouter />
    <style is:global>
      body { font-family: system-ui, sans-serif; max-width: 48rem; margin: 0 auto; padding: 1rem; }
      header { display: flex; gap: 1rem; align-items: center; justify-content: space-between; border-bottom: 1px solid #ddd; padding-bottom: .5rem; }
    </style>
  </head>
  <body>
    <Header />
    <main><slot /></main>
  </body>
</html>
```

`transition:persist="cart-badge"` in `Header.astro` keeps the `CartBadge` island, including its state, across router navigations; the island’s server-rendered props are re-sent but the instance is retained (Chapter 14: use `transition:persist-props` if you need to prevent prop updates). That is why the store’s `ready` flag stays true after navigation and the badge does not flicker back to an ellipsis. The persisted element carries the matching `data-astro-transition-persist="cart-badge"` attribute in the rendered HTML, which I observed in the server output.

A design caveat: persisting an island that sits next to a server island is safe here because the two are independent elements. I did not try to persist the server island itself; its replacement content arrives after the swap, and persistence matches elements present at swap time. For per-user data inside the persisted region, use the store, not a server island.

## Webhook and cache invalidation

```ts
// src/pages/api/inventory-webhook.ts
import type { APIRoute } from 'astro';
import { z } from 'astro/zod';
import { WEBHOOK_SECRET } from 'astro:env/server';
import { setStock } from '../../lib/inventory-store';
import { timingSafeEqual } from 'node:crypto';

export const prerender = false;

const body = z.object({ sku: z.string().min(1), qty: z.number().int().min(0) });

function safeEqual(a: string, b: string) {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

export const POST: APIRoute = async (ctx) => {
  const provided = ctx.request.headers.get('x-webhook-secret') ?? '';
  if (!safeEqual(provided, WEBHOOK_SECRET)) return new Response('forbidden', { status: 403 });

  const parsed = body.safeParse(await ctx.request.json().catch(() => null));
  if (!parsed.success) return Response.json({ error: 'bad request' }, { status: 400 });

  setStock(parsed.data.sku, parsed.data.qty);
  ctx.logger.info(`stock ${parsed.data.sku} -> ${parsed.data.qty}`);
  if (ctx.cache.enabled) await ctx.cache.invalidate({ tags: [`sku:${parsed.data.sku}`] });
  return Response.json({ ok: true });
};
```

The warehouse calls this endpoint when stock changes. Authentication is a shared secret in a header compared in constant time; the body is validated with Zod; the cache is invalidated by the tag the product page adopted from the live loader’s hint. The secret comes from `astro:env/server`, so it is typed, validated and never bundled.

Observed behaviour with the built server (caching enabled, memory provider):

```text
GET /en/products/lamp  -> x-astro-cache: MISS     (stock: 3 in stock)
GET /en/products/lamp  -> x-astro-cache: HIT
POST /api/inventory-webhook (no secret)         -> 403
POST /api/inventory-webhook {"sku":"lamp","qty":1} + secret -> {"ok":true}
GET /en/products/lamp  -> "1 in stock"          (cache entry purged by tag sku:lamp)
```

(The first request after a purge is a miss; with `swr` configured, a CDN provider would serve stale content while revalidating, as described in Chapter 12.) Because the collection-level hint includes every per-SKU tag, one invalidation of `sku:lamp` purges exactly two cached pages: the lamp page and the catalogue list. I verified it: after warming `/en/`, `/en/products/lamp` and `/en/products/mug`, posting a stock change for `lamp` made `/en/` and the lamp page MISS (and show `2 in stock`) while `/en/products/mug` stayed a HIT. Choose tag granularity deliberately: coarse tags (`inventory`) are simple and over-purge; fine tags are precise and require every reader to carry every tag it depends on. Add `inventory` to the invalidation for bulk imports.

## Middleware

```ts
// src/middleware.ts
import { defineMiddleware } from 'astro:middleware';

export const onRequest = defineMiddleware(async (context, next) => {
  const start = performance.now();
  const res = await next();
  context.logger.info(`${context.request.method} ${context.url.pathname} ${res.status} ${Math.round(performance.now() - start)}ms`);
  return res;
});
```

Per-request timing goes through `context.logger` and therefore through whatever logger is configured (Chapter 17). The output from the test run:

```text
19:42:32 POST /bg/cart 200 5ms
19:42:32 GET /bg/cart 200 2ms
```

Note that on-demand middleware runs for these routes; the i18n routing runs in the built-in pipeline order (Chapter 5), so the middleware sees the final locale from `context.currentLocale`.

## Hardening: security and environment

What the configuration and code already give you:

- **Origin check on, body limits lowered, secrets typed.** I verified that a cross-origin form post to an action URL (`Origin: https://evil.example`) returns 403.
- **Authorisation at the data layer.** The cart actions use the session, not anything the client says about identity. There is no authenticated role in this demo; if you add accounts, check them inside each action handler (Chapter 16).
- **Validation everywhere.** Query, form and JSON inputs go through Zod; unknown SKUs and oversized quantities are rejected.
- **No secrets in bundles.** `WEBHOOK_SECRET` lives only in the server environment. With `validateSecrets: false`, a missing secret surfaces at first use, so the webhook would 500 until it is set; production deployments should set `validateSecrets: true` in CI or add a health check that imports `astro:env/server`.

What it deliberately does not have: a Content Security Policy. Chapter 16 states that `security.csp` is incompatible with `<ClientRouter />`. This shop chooses the router (persistent cart badge, smooth navigation). You have two honest options. Keep the router and compensate with the other controls above plus a conservative header set from the CDN or middleware (`X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors` via `X-Frame-Options`/header-level CSP without script restrictions). Or drop the router, use the browser’s native view transitions, enable `security.csp`, set Node’s `staticHeaders: true` and keep the persisted cart in the session only: the badge then re-fetches on each page. The decision is a product trade-off, not a technical default.

## Tests

### Unit tests (Vitest, `node` environment)

```ts
/// <reference types="vitest/config" />
import { getViteConfig } from 'astro/config';

export default getViteConfig({
  test: { environment: 'node', include: ['tests/**/*.test.ts'] },
});
```

```ts
import { describe, expect, test } from 'vitest';
import { addLine, count, removeLine, total } from '../src/lib/cart-logic';

describe('cart-logic', () => {
  test('addLine merges and clamps to max', () => {
    let lines = addLine([], 'mug', 4, 5);
    lines = addLine(lines, 'mug', 4, 5);
    expect(lines).toEqual([{ sku: 'mug', qty: 5 }]);
  });
  test('addLine does not mutate its input', () => {
    const input = [{ sku: 'a', qty: 1 }];
    addLine(input, 'a', 1, 10);
    expect(input[0].qty).toBe(1);
  });
  test('removeLine, count, total', () => {
    const lines = [{ sku: 'a', qty: 2 }, { sku: 'b', qty: 1 }];
    expect(count(lines)).toBe(3);
    expect(total(lines, (s) => (s === 'a' ? 100 : 50))).toBe(250);
    expect(removeLine(lines, 'a')).toEqual([{ sku: 'b', qty: 1 }]);
  });
});
```

```ts
import { expect, test } from 'vitest';
import { formatMoney, t } from '../src/i18n/ui';

test('unknown locales fall back to English', () => {
  expect(t('fr').cart).toBe('Cart');
  expect(t(undefined).cart).toBe('Cart');
});
test('money is formatted per locale', () => {
  expect(formatMoney(1200, 'en')).toBe('€12.00');
  expect(formatMoney(1200, 'bg')).toContain('12,00');
});
```

Pure modules need no Astro at all, which is the reason the cart arithmetic lives in `cart-logic.ts` rather than inside the action handlers.

### Container test

```ts
import { experimental_AstroContainer as AstroContainer } from 'astro/container';
import { expect, test } from 'vitest';
import Greeting from '../src/components/Greeting.astro';

test('Greeting falls back to the guest text in each locale', async () => {
  const container = await AstroContainer.create();
  const en = await container.renderToString(Greeting, { props: { locale: 'en' } });
  const bg = await container.renderToString(Greeting, { props: { locale: 'bg' } });
  expect(en).toContain('Welcome, guest');
  expect(bg).toContain('Добре дошли');
});
```

This renders `Greeting.astro` outside any server. Without a session in the container, the optional-chained `Astro.session?.get('name')` yields `undefined` and the guest text appears, in both locales. (The container cannot give a component a real session; test session-dependent branches by extracting the lookup into a function or through E2E.)

My run:

```text
 ✓ tests/cart-logic.test.ts (3 tests)
 ✓ tests/greeting.test.ts (1 test)
 ✓ tests/ui.test.ts (2 tests)
 Test Files  3 passed (3)
      Tests  6 passed (6)
```

### End-to-end tests (Playwright)

```ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  webServer: {
    command: 'npm run build && npm run start',
    url: 'http://localhost:4321/en/',
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
    env: { PORT: '4321', WEBHOOK_SECRET: 'ci-dummy-secret' },
  },
  use: { baseURL: 'http://localhost:4321' },
});
```

```ts
import { test, expect } from '@playwright/test';

test('cart badge survives client-side navigation and counts adds', async ({ page }) => {
  await page.goto('/en/products/mug');
  const badge = page.getByTestId('cart-count');
  await expect(badge).toHaveText('0');                      // hydrated and loaded from the session
  const island = page.locator('astro-island', { has: page.getByTestId('add') });
  await island.scrollIntoViewIfNeeded();
  await expect(island).not.toHaveAttribute('ssr');          // hydrated
  await page.getByTestId('add').click();
  await expect(badge).toHaveText('1');

  await page.getByRole('link', { name: 'Shop' }).click();   // ClientRouter navigation
  await expect(page).toHaveURL(/\/en\/$/);
  await expect(page.getByTestId('cart-count')).toHaveText('1'); // persisted island kept its state
});

test('locale switch keeps the path', async ({ page }) => {
  await page.goto('/en/products/lamp');
  await page.getByRole('link', { name: 'BG' }).click();
  await expect(page).toHaveURL(/\/bg\/products\/lamp\/?$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Настолна лампа');
});

test('add-to-cart works without JavaScript', async ({ browser }) => {
  const ctx = await browser.newContext({ javaScriptEnabled: false });
  const page = await ctx.newPage();
  await page.goto('http://localhost:4321/en/products/mug');
  await page.locator('#add-form button').click();
  await expect(page.getByTestId('line')).toContainText('Enamel mug');
  await ctx.close();
});
```

These specs follow the synchronisation rule from Chapter 17: wait for the `ssr` attribute to disappear from the `astro-island` before clicking, because `client:visible` islands are inert server HTML until they hydrate. The first test asserts the capstone’s headline behaviour: the badge keeps its count through a router navigation because the island is persisted. **I could not execute this file here** (no browsers installed); I did verify the server-side halves it depends on with `curl`, namely the no-JS form flow, the cart contents, the locale rendering and the cache behaviour:

```text
GET  /                      -> 302 /en/
GET  /bg/products/lamp      -> <h1>Настолна лампа</h1>, 3 налични
POST /en/cart/?_action=cart.add  (sku=mug, no JS)  -> 200, cart shows "Enamel mug × 1"
POST ... sku=notebook (stock 0)  -> 409, "Sold out" alert
POST /_actions/cart.get          -> devalue-encoded cart (JSON content type)
POST (Origin: https://evil.example) -> 403
POST /bg/cart?_action=cart.add sku=mug&qty=3  -> cart: "Емайлирана чаша × 3", "Общо: 36,00 €"
```

## Build, run and deploy

```bash
npm install
WEBHOOK_SECRET=change-me-please npm run build     # a secret is needed only if validateSecrets is true or a prerendered page reads it
WEBHOOK_SECRET=change-me-please PORT=4321 HOST=0.0.0.0 npm start
```

Deployment checklist for this project:

1.  **Node 22.22+** in the image; `node dist/server/entry.mjs` is the entrypoint (Node adapter, `standalone`).
2.  **`ASTRO_KEY`** generated with `astro create-key` and provided to every build if you run more than one instance, so server island URLs decrypt everywhere (Chapter 9).
3.  **Shared session storage.** Replace the default filesystem driver with Redis through `sessionDrivers.redis(...)` or an entrypoint (Chapter 12), and pick sticky or shared storage deliberately.
4.  **Shared cache.** `memoryCache()` is per-process. Use a CDN provider or accept per-instance caches and webhook fan-out to every instance.
5.  **Inventory** is a module here; replace `inventory-store.ts` with an HTTP client to the real system, with timeouts and a fallback result, because the live loader runs inside request handling.
6.  **`security.allowedDomains`** configured for the public hostname when behind a proxy.
7.  **CI**: `astro check` (add `@astrojs/check`), `svelte-check`, Vitest, `astro build` followed by Playwright against the built server, and a smoke check of the webhook.
8.  **Logs**: switch to `logHandlers.json()` and ship stdout (Chapter 17).

## What to take from the design

- State has one authority (the session) and one cache per audience: a shared mirror in the browser, a shared page cache on the server, and a private server island for personal data. The three never mix.
- Cache correctness is a data-flow property: tags are the edges between a write (the webhook) and the pages that read the data.
- Progressive enhancement costs one extra form and pays for itself in resilience and testability.
- The ClientRouter and CSP trade-off is real and belongs in your architecture decision record.

## Key takeaways

- Choose rendering per route: on-demand for stock-sensitive and per-user pages, cache the shared ones, defer the personal fragments with server islands.
- Combine a build-time collection (stable catalogue) with a live collection (stock) and carry the live loader’s `cacheHint` into `Astro.cache.set()` so invalidation by tag reaches exactly the dependent pages.
- Keep the cart’s source of truth in the session, mutate it only through validated actions, and mirror it on the client in a rune module that is never written during SSR.
- Make actions `accept: 'form'` so one handler serves no-JS forms and typed island calls; `checkOrigin` protects the form surface.
- `transition:persist` keeps the badge island and its store alive across `<ClientRouter />` navigations; re-sync from authoritative DOM after full-page form posts.
- With `prefixDefaultLocale: true`, you need a root `index.astro` that redirects; validate `[locale]` explicitly.
- Memory cache and filesystem sessions are single-instance conveniences; production needs shared providers.
- `<ClientRouter />` and `security.csp` are mutually exclusive; decide consciously and document it.
- Test pure logic with Vitest, components with the Container API, and the whole shop with Playwright against the built server.

## Review Questions

1.  Why is `output: 'server'` required for this project even though the catalogue changes rarely? List four features that force it.
2.  Which routes would you prerender in a production version of this shop, and how would you keep stock correct on them?
3.  Explain which cache tags a product page and the list page carry, and why invalidating a single `sku:<id>` tag refreshes both.
4.  What would happen if `cart.svelte.ts` called `cart.load()` at module top level without a browser guard?
5.  Why does the cart store avoid writing during SSR, and what does the rendered badge show on the server?
6.  In `actions/index.ts`, which checks protect against a malicious client? Name three, and say why prices are not stored in the cart.
7.  What does `accept: 'form'` change about the action’s HTTP surface compared with `accept: 'json'`, and which security setting applies?
8.  The `profile.setName` action calls `session.regenerate()`. What attack does this prevent and when must it be called in a real application?
9.  Write the URL a browser posts to when the no-JS form on `/bg/products/mug` is submitted. How does `Astro.getActionResult()` on the cart page relate to it?
10. Why is `Astro.cache.set(false)` used on the cart page even though no route rule matches it?
11. A route rule says `maxAge: 60` and the page calls `Astro.cache.set(cacheHint)`. What is the final `maxAge` and what are the final tags?
12. What is `x-astro-cache: HIT` evidence of, and why did the page show the new stock after the webhook?
13. Why is `memoryCache()` insufficient for a deployment with three Node instances behind a load balancer?
14. Why is the greeting a server island rather than part of the cached page? What would happen if it were rendered in the page?
15. `Astro.url` inside `Greeting.astro` is not the page URL. How does the component learn the locale?
16. What does `transition:persist="cart-badge"` preserve, and what must match between the old and new pages for it to work?
17. Why is the `astro:page-load` listener in `cart.svelte.ts` needed, given that the island persists?
18. Why can the server island itself not be reliably persisted across navigations?
19. The build fails with `MissingIndexForInternationalization`. Why, and how is it fixed?
20. Explain why `[locale]` pages must validate the locale and what a request to `/fr/` should return here.
21. Which of the three cart responses in the transcript demonstrates server-side stock enforcement, and with what status code?
22. Why is a cross-origin POST to `?_action=cart.add` rejected, and would the same be true of a JSON POST from another origin? Why?
23. Why does the project not enable `security.csp`? Give two alternative strategies.
24. Why does `validateSecrets: false` mean a missing `WEBHOOK_SECRET` is discovered late, and what two measures catch it earlier?
25. What does the Container test prove and what can it not prove about `Greeting.astro`?
26. In the Playwright test, why wait for `not.toHaveAttribute('ssr')` before clicking?
27. Multiple choice: which statement about `getLiveEntry` results is correct?

<!-- -->

a.  They are stored in the data store and refreshed at build time.
b.  They are fetched on each request and may carry a `cacheHint` with tags.
c.  They support MDX rendering and image optimisation.
d.  They require `prerender = true`.

<!-- -->

28. Find the bug: a developer changes `CartBadge.svelte` to initialise `cart.lines` from a prop on the server (`cart.lines = initial`) at the top of the script. What goes wrong in production?
29. Design question: the shop must support three locales where product descriptions differ by market. Describe how you would change the collection schema and routes, and what happens to cache tags.
30. Design question: the warehouse API is slow (800 ms). Describe two changes (one in the loader or page, one in caching) that keep the catalogue page fast.
