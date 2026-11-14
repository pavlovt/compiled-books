# Chapter 15: Internationalization

Astro’s i18n support is routing, not translation. It decides which URL belongs to which locale, what happens when a translation is missing, how a visitor lands on the right language, and how you generate links that respect all of that. It does not ship a message catalog, a pluralization engine or a runtime that swaps strings. Those parts you build, or take from a library, and this chapter shows how to build them with Astro pages, content collections and Svelte 5 islands.

That split is the first thing to internalize, because most confusion about Astro i18n comes from expecting a framework like `next-intl` or `vue-i18n` and finding folders and middleware instead. The upside is that everything is plain files and plain functions, so it is statically analyzable, cheap to prerender, and easy to test.

I verified the configuration behaviors and the `astro:i18n` helper outputs in this chapter by building a static test project (Astro 7.4.1, `@astrojs/svelte` 9.1.0, Svelte 5.57.2). Domain routing requires a server build with a host that forwards the right headers; I could not run that against a real multi-domain setup, so those parts come from the documentation, and I mark them.

## The routing model

Astro i18n is file-based. You create one folder per locale under `src/pages/`, and the folder name is the locale’s URL segment. A middleware that Astro adds when you configure `i18n` handles redirects and fallbacks; the `astro:i18n` virtual module gives you helpers to build URLs.

The minimal configuration:

```js
// astro.config.mjs
import { defineConfig } from 'astro/config';
import svelte from '@astrojs/svelte';

export default defineConfig({
  site: 'https://example.com',
  integrations: [svelte()],
  i18n: {
    locales: ['en', 'es', 'fr'],
    defaultLocale: 'en',
  },
});
```

`locales` is the complete list of supported locales, and `defaultLocale` must be one of them. With this configuration and the pages layout

```text
src/pages/
  index.astro          -> /
  about.astro          -> /about/
  es/
    index.astro        -> /es/
    about.astro        -> /es/about/
  fr/
    index.astro        -> /fr/
    about.astro        -> /fr/about/
```

the default locale lives at the root and every other locale is prefixed. That is the default `prefixDefaultLocale: false` behavior. Trailing slashes in the sample URLs come from the default `trailingSlash: 'ignore'` combined with the build format; the helper functions, shown later, emit them in my test project.

### Locale entries: strings and objects

Each item in `locales` is either a string or an object with `path` and `codes`:

```js
i18n: {
  locales: [
    'en',
    'es',
    { path: 'french', codes: ['fr', 'fr-CA'] },
  ],
  defaultLocale: 'en',
}
```

The string form means the URL segment and the locale code are the same thing. The object form separates them. `path` is the folder name and URL segment (`/french/about/`), and `codes` is the list of BCP 47 language tags that map to it. The codes matter in two places: `Astro.currentLocale` returns a code (the first one in the list, as I confirm below), and browser language detection matches the `Accept-Language` header against codes. Use the object form when the URL should not be a language tag at all (`/french/`, `/deutsch/`) or when one section of the site serves several regional tags.

Remember that the path form of a locale is what you use as a key in `fallback`, which is the source of the most common configuration error, described below.

## `prefixDefaultLocale` and redirects

The `routing` object has three keys. The first, `prefixDefaultLocale`, decides whether the default locale gets a folder and a URL prefix like every other locale.

With `prefixDefaultLocale: false` (the default), English pages live at the root: `src/pages/about.astro` serves `/about/`. Non-default locales are prefixed. There is no `src/pages/en/` folder, and creating one would not be an error but it would be served at `/en/about/`, outside the i18n model. Keep the layout consistent.

With `prefixDefaultLocale: true`, every locale including the default has a folder: `src/pages/en/about.astro` serves `/en/about/`. You must still provide a root `src/pages/index.astro`, because Astro does not generate one for you. In my test, building with `prefixDefaultLocale: true` and no root index produced a missing-root problem, so treat the root page as yours to write: a redirect or a language chooser.

```html
---
// src/pages/index.astro  (prefixDefaultLocale: true, static output)
---
<meta http-equiv="refresh" content="0;url=/en/" />
```

On a server build, use `Astro.redirect('/en/')` instead, or let the setting below do it.

The second key, `redirectToDefaultLocale`, controls whether a request for `/` redirects to `/en/` automatically when the default locale is prefixed. Two facts come from the 6.0 upgrade guide and from my build experiments:

- Its default is `false` as of 6.0. Before that it defaulted to `true`, which silently owned your home page.
- It only makes sense with `prefixDefaultLocale: true`. Setting `redirectToDefaultLocale: true` with `prefixDefaultLocale: false` is a configuration error, and Astro rejects it at startup. There is nothing to redirect to when the default locale already lives at the root.

> **Warning:** If you copy an older config with `redirectToDefaultLocale: true`, check that it still validates under 6.0 and later, and that you are not relying on the old default of `true`. If you want the automatic redirect, set it explicitly.

Decide `prefixDefaultLocale` early. Changing it later moves every URL of your default language, which means redirects, broken external links and a drop in search rankings. Hide the default prefix when most of your traffic is in that language and you want short URLs; prefix everything when the languages are peers and you want symmetry, easier link generation, and no special case for the default.

## Fallback

A fallback tells Astro what to serve when a locale lacks a page that another locale has. The third routing key, `fallbackType`, chooses how.

```js
i18n: {
  locales: ['en', 'es', { path: 'french', codes: ['fr', 'fr-CA'] }],
  defaultLocale: 'en',
  fallback: { es: 'en', french: 'en' },
  routing: { prefixDefaultLocale: false, fallbackType: 'rewrite' },
}
```

`fallback` is a map from a locale to the locale that stands in for it. Two details trapped me while building the test project.

First, keys are locale paths, not codes. `fallback: { fr: 'en' }` is rejected when the locale is declared as `{ path: 'french', codes: ['fr'] }`: Astro reports that the key does not match a configured locale. The key must be `french`. The same applies to the fallback value when it names a custom-path locale.

Second, the behavior depends on `fallbackType`:

- `'redirect'` (the default) sends the browser to the fallback locale’s URL. A request for `/es/pricing/` with no Spanish pricing page becomes a redirect to `/pricing/`. The URL in the address bar changes. On a static build Astro generates redirect pages (meta refresh HTML) for each missing route.
- `'rewrite'` serves the fallback page’s content at the requested URL. The address bar stays `/es/pricing/`, but the content is English. On a static build Astro generates the page file at the requested path with the fallback content.

Choose `rewrite` when you want the URL space of every locale to be complete and shareable, and the content gaps to be invisible to links. Choose `redirect` when you prefer URLs to tell the truth about which language the user is reading. In either case set `lang` on the `<html>` element from `Astro.currentLocale` deliberately: with a rewrite, `currentLocale` reports the locale of the URL (`es`), not the language of the content (English). If your layout sets `lang` from `currentLocale`, a rewritten fallback page will claim to be Spanish while being English, which harms screen readers and search engines. To handle that, pass the content language explicitly from the page that knows it.

```html
---
// src/layouts/Base.astro
interface Props { title: string; contentLang?: string }
const { title, contentLang } = Astro.props;
const lang = contentLang ?? Astro.currentLocale ?? 'en';
---
<html lang={lang}>
  <head><title>{title}</title></head>
  <body><slot /></body>
</html>
```

Fallback also applies to dynamic and on-demand routes in the sense that it reacts to a 404 for a locale-prefixed path. It does not know about your data: a dynamic page that exists but renders “no entry found” returns whatever you return. If you want fallback for missing content entries, return a 404 status from the page (or `Astro.rewrite`) rather than rendering an empty page with a 200.

## Custom locale paths in practice

The object form of a locale is more than cosmetic. In the test project the helpers gave these results with `prefixDefaultLocale: false`:

| Call | Result |
|------------------------------------|------------------------------------|
| `getRelativeLocaleUrl('es', 'about')` | `/es/about/` |
| `getRelativeLocaleUrl('fr', 'about')` | `/french/about/` |
| `getRelativeLocaleUrl('fr-CA', 'x')` | `/french/x/` |
| `getRelativeLocaleUrl('en', 'about')` | `/about/` (with prefix `true`: `/en/about/`) |
| `getAbsoluteLocaleUrl('es', 'about')` | `https://example.com/es/about/` |
| `getPathByLocale('fr-CA')` | `french` |
| `getLocaleByPath('french')` | `fr` |
| `getRelativeLocaleUrlList('about')` | `['/about/', '/es/about/', '/french/about/']` |

Two things follow. The helpers accept any code from `codes`, not just the first, so you can call them with whatever the user’s browser or your data says. And `getLocaleByPath` goes the other way and returns the first code, which is what `Astro.currentLocale` also reports for pages under that path. The documentation states the rule: when computing URLs with the module’s functions, use the code; when you need the folder name, use `getPathByLocale`.

The documented limitations of custom paths concern `site`, a server output and no prerendered pages, but that list sits under the domain feature described next. For plain custom paths the only requirement is a consistent folder name. My static build with `path: 'french'` succeeded with prerendered pages, and nothing in the build complained.

## Domains

`domains` maps locales to whole domains rather than path prefixes. It is meant for `output: 'server'` projects with an adapter that supports it (the docs name `@astrojs/node` and `@astrojs/vercel`) and a configured `site`.

```js
// astro.config.mjs
import node from '@astrojs/node';
export default defineConfig({
  site: 'https://example.com',
  output: 'server',
  adapter: node({ mode: 'standalone' }),
  i18n: {
    locales: ['es', 'en', 'fr', 'ja'],
    defaultLocale: 'en',
    routing: { prefixDefaultLocale: false },
    domains: {
      fr: 'https://fr.example.com',
      es: 'https://example.es',
    },
  },
});
```

Files still live in locale folders. `src/pages/fr/about.astro` becomes `https://fr.example.com/about`, `src/pages/es/about.astro` becomes `https://example.es/about`, and unmapped locales (`ja`) keep the path-prefix behavior on the main domain: `https://example.com/ja/about`. `getAbsoluteLocaleUrl()` and `getAbsoluteLocaleUrlList()` return the domain URLs.

Constraints, all from the docs and one confirmed by my test:

- `site` is mandatory.
- `output` must be `'server'`, with no individually prerendered pages. Putting `domains` in a static project fails validation; I confirmed that.
- Astro finds the requested host from `X-Forwarded-Host`, falling back to `Host`, and the protocol from `X-Forwarded-Proto`, falling back to the request URL’s protocol. If your proxy does not forward them, Astro cannot map the host and returns a 404.

The last point is operational. A reverse proxy that rewrites the `Host` header to an internal name will make every domain page a 404, and that failure looks like an Astro bug. Configure the proxy to pass the original host and protocol, and test with a `curl -H 'Host: fr.example.com'` against the running server. Relative links with `getRelativeLocaleUrl` do not cross domains: the relative URL for `fr` is a path on the current host. To link from `example.com` to the French domain use the absolute variant, and I recommend always using absolute URLs for the language switcher in a domains setup.

## Reading the locale in your code

Three properties on the `Astro` global (and on the API context) matter:

- `Astro.currentLocale` is the locale computed from the URL, using the syntax of your `locales` configuration. It is available on every page, prerendered or not. When the URL carries no prefix it returns `defaultLocale`. If the URL does not correspond to any configured locale (a path outside your folders), it is `undefined`.
- `Astro.preferredLocale` is the best match between the visitor’s `Accept-Language` header and your locales (matching against `codes` for object entries), or `undefined` if nothing matches.
- `Astro.preferredLocaleList` is the list of all locales both requested by the browser and supported by your site, `[]` when none match, and your full `locales` list when the browser expresses no preference.

The last two exist only on pages rendered on demand. On a prerendered page there is no request to read headers from, so they are not available. This is the central constraint of browser-language detection: you cannot do it in static HTML. The next section shows the patterns that work.

> **Note:** `currentLocale` is derived from the URL alone, so it is safe to use in prerendered pages and it is cacheable. `preferredLocale` depends on a request header, so any page that reads it varies by `Accept-Language`. If you put such a page behind route caching (Chapter 12), add `Vary: Accept-Language` or you will serve one visitor’s language to another.

## Detecting the browser language

A typical requirement: the first time a visitor reaches `/`, send them to `/es/` if their browser prefers Spanish, and remember a manual choice. Because detection needs the request, the root page must be rendered on demand even when the rest of the site is static.

```html
---
// src/pages/index.astro
export const prerender = false;

const COOKIE = 'lang';
const saved = Astro.cookies.get(COOKIE)?.value;
const target = saved ?? Astro.preferredLocale ?? 'en';

if (target !== 'en') {
  return Astro.redirect(`/${target}/`, 302);
}
---
<h1>Welcome</h1>
```

Points to check in a design like this:

- Use a 302, not a 301. A permanent redirect is cached by browsers and by shared caches keyed on URL alone, and a visitor who later changes their browser language would be stuck.
- Redirect only from `/`, never from deep links. Someone who followed a link to `/pricing/` in English expects English.
- Let the explicit choice win: store the user’s selection in a cookie (set by the language switcher), read it first, and fall back to `preferredLocale` only for first visits.
- `preferredLocale` returns a configured locale value; for an object entry with several codes it matches against any of the codes. Redirect with the path (`getPathByLocale(target)`), not the code, if you use custom paths.

A server-rendered root page with a static rest-of-site is exactly the hybrid shape the static and server modes of Chapter 8 allow: mark that one page `prerender = false` and everything else stays static. If your host cannot run any server code, fall back to a small client script that reads `navigator.languages` on the root page and calls `location.replace`. It cannot be cached by the CDN as a decision, but the page itself is static and the redirect happens client-side. A search engine will not follow it, which is usually what you want: the root URL should be a stable, crawlable language chooser with `hreflang` links, which the next sections build.

## Generating links with `astro:i18n`

Never concatenate locale prefixes by hand. The helpers know about `prefixDefaultLocale`, custom paths, `base` and domains, and they keep working when you change the config.

```html
---
// src/components/Nav.astro
import { getRelativeLocaleUrl } from 'astro:i18n';
const locale = Astro.currentLocale!;
---
<nav>
  <a href={getRelativeLocaleUrl(locale, '')}>Home</a>
  <a href={getRelativeLocaleUrl(locale, 'about')}>About</a>
  <a href={getRelativeLocaleUrl(locale, 'blog')}>Blog</a>
</nav>
```

The module exports these functions (from the 7.4.1 reference):

- `getRelativeLocaleUrl(locale, path?, options?)` and `getAbsoluteLocaleUrl(locale, path?, options?)` return one URL.
- `getRelativeLocaleUrlList(path?, options?)` and `getAbsoluteLocaleUrlList(path?, options?)` return one URL per configured locale, in `locales` order. They are what you use to render `<link rel="alternate" hreflang>` elements.
- `getPathByLocale(code)` and `getLocaleByPath(path)` convert between codes and folder names.
- `normalizeTheLocale`, `toCodes`, `toPaths`, `pathHasLocale`, `requestHasLocale` are utilities for working with locale strings and paths; they are mostly for middleware.
- `redirectToDefaultLocale`, `redirectToFallback`, `notFound` and `middleware` are for manual routing and are described below.

The `path` argument is relative to the locale root and does not take a leading locale. The `options` object accepts `normalizeLocale` (whether to turn `en_US` style values into `en-us` URL segments) and, for the relative and absolute functions, `prependWith` to put something between the base and the path. I verified the common case, leaving options unset, in the table above.

### `hreflang` alternates

Search engines want every translated page to link to all its siblings. Build that in the layout from the current path, using the list helper:

```html
---
// src/layouts/Base.astro (head fragment)
import { getAbsoluteLocaleUrlList, getPathByLocale } from 'astro:i18n';
import { i18n } from 'astro:config/client';

// the path without the locale segment, e.g. "about/"
const current = Astro.currentLocale!;
const prefix = `/${getPathByLocale(current)}/`;
const rest = Astro.url.pathname.startsWith(prefix)
  ? Astro.url.pathname.slice(prefix.length)
  : Astro.url.pathname.slice(1);

const urls = getAbsoluteLocaleUrlList(rest);
const codes = i18n!.locales.map((l) => (typeof l === 'string' ? l : l.codes[0]));
---
<head>
  {urls.map((href, i) => <link rel="alternate" hreflang={codes[i]} href={href} />)}
  <link rel="alternate" hreflang="x-default" href={getAbsoluteLocaleUrlList(rest)[0]} />
</head>
```

This relies on two facts: the list is returned in `locales` order, which my test confirmed for the relative list, and `astro:config/client` exposes the i18n section of the config. If your project does not need that import, define the code list in a small shared module and import it in both the config and the layout, which also keeps a single source of truth.

> **Caution:** The `rest` computation above breaks if the default locale is prefixed and the current page is the root, or if `base` is set. Treat it as a sketch and cover it with a test. A more robust design passes the page’s own route key (`'about'`) down as a prop from each page and never parses `Astro.url`.

The `@astrojs/sitemap` integration understands i18n: give it `i18n: { defaultLocale, locales }` mapping locale to a language tag and it emits `xhtml:link` alternates in the sitemap for pages that exist in several locales. That is the lowest-effort way to give search engines the alternates without touching the layout.

## Manual routing

Setting `routing: 'manual'` turns off Astro’s i18n middleware. No other routing options may accompany it. You then own the redirect rules: what `/` does, what a missing prefix means, and how fallback works.

```js
i18n: {
  locales: ['en', 'es', 'fr'],
  defaultLocale: 'en',
  routing: 'manual',
}
```

Astro gives you the building blocks as functions in `astro:i18n`, available only in manual mode:

- `redirectToDefaultLocale(context, status?)` returns a redirect `Response` to the default locale.
- `redirectToFallback(context, response)` applies your `fallback` config to a response.
- `notFound(context, response?)` returns a 404 when the path is not a root and has no locale; it returns `undefined` otherwise, so you test its result.
- `middleware(options)` creates Astro’s own i18n middleware with options you choose, so you can wrap it.

Writing a middleware from the pieces:

```ts
// src/middleware.ts
import { defineMiddleware, sequence } from 'astro:middleware';
import { middleware, notFound } from 'astro:i18n';

const exceptions = defineMiddleware(async (ctx, next) => {
  // /api and /health are language-neutral
  if (ctx.url.pathname.startsWith('/api') || ctx.url.pathname === '/health') {
    return next();
  }
  const miss = notFound(ctx);
  if (miss) return miss;
  return next();
});

export const onRequest = sequence(
  exceptions,
  middleware({
    prefixDefaultLocale: true,
    redirectToDefaultLocale: false,
    fallbackType: 'rewrite',
  }),
);
```

The ordering is meaningful. Your middleware runs first and may short-circuit; `middleware()` runs after it and applies the standard behavior, including fallback, to the response coming back from the page. If instead your middleware calls `await next()` first, it sees the response that Astro’s i18n middleware produced, which is how you would intercept a fallback 404 and customize it. The documentation’s example does that: it inspects the response after `next()` and returns an exception page for `/about` even though no localized page exists.

When to use manual routing: language neutral routes that must not be 404ed (webhooks, health checks, OAuth callbacks outside the locale tree), a custom language negotiation scheme (cookie, subdomain, `Accept-Language` on every request), or A/B routing. When not to: if all you want is a different fallback rule or to hide the default prefix, the declarative options already cover it, and manual routing means you lose the 404 for unprefixed paths until you re-add it with `notFound`.

### Advanced routing and i18n

The `src/fetch.ts` entrypoint of advanced routing replaces the default request pipeline. The `astro/fetch` module exports an `i18n` handler among its built-ins, which sits after `pages` in the documented built-in order (trailing slash, redirects, sessions, actions, user middleware, pages, i18n, caching). If you compose a custom `fetch`, you decide whether to include that step. Do not authorize by matching `url.pathname` in a hand-rolled prefix check; use a router. Because the surrounding API is still moving, treat advanced routing as the place to look only if middleware cannot express your rule.

## Translating content

Pages are one half of a localized site. The other half is content. Chapter 6 covered content collections; here the question is how to structure them for several languages. The Astro recipe uses one subfolder per locale inside each collection:

```text
src/content/blog/
  en/
    launch.md
    pricing.md
  es/
    launch.md
```

and a collection that loads everything with the `glob` loader:

```ts
// src/content.config.ts
import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

const blog = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/blog' }),
  schema: z.object({
    title: z.string(),
    pubDate: z.coerce.date(),
  }),
});

export const collections = { blog };
```

Entry ids include the folder: `en/launch`, `es/launch`. A page filters by prefix and strips it to build a locale-independent slug:

```html
---
// src/pages/[lang]/blog/[...slug].astro
import { getCollection, render } from 'astro:content';
import { getRelativeLocaleUrl } from 'astro:i18n';
import type { GetStaticPaths } from 'astro';

export const getStaticPaths = (async () => {
  const posts = await getCollection('blog');
  return posts.map((post) => {
    const [lang, ...rest] = post.id.split('/');
    return { params: { lang, slug: rest.join('/') }, props: { post } };
  });
}) satisfies GetStaticPaths;

const { post } = Astro.props;
const { Content } = await render(post);
---
<article>
  <h1>{post.data.title}</h1>
  <Content />
</article>
```

This generates `/en/blog/launch/` and `/es/blog/launch/`, and no `/es/blog/pricing/`, which is where `fallback` earns its keep: with `fallbackType: 'rewrite'`, Astro serves the English pricing post at the Spanish URL.

A caveat on that last sentence. Fallback generation works from the set of routes Astro knows at build time. For dynamic routes it knows the paths `getStaticPaths` returned for each locale folder, and generates fallback pages for those a locale lacks. In my test project, which used plain pages, fallback pages were generated for the missing routes. I did not build a dynamic content route with fallbacks, so if you rely on this for a `[...slug]` route, verify the build output lists the fallback paths you expect. A changelog entry in the 7.x series describes fixes to fallback route generation, so keep your Astro version current.

### Links between translations

Store a shared identifier in the frontmatter or derive it from the filename (`launch`), then build the alternate links from it:

```html
---
const [lang, ...rest] = post.id.split('/');
const slug = rest.join('/');
const all = await getCollection('blog');
const translations = all
  .filter((p) => p.id.endsWith(`/${slug}`) && p.id !== post.id)
  .map((p) => p.id.split('/')[0]);
---
<ul>
  {translations.map((l) => (
    <li><a href={getRelativeLocaleUrl(l, `blog/${slug}`)}>{l}</a></li>
  ))}
</ul>
```

For a larger site, model the relationship explicitly: a `translationKey` field in the schema, validated by a test that every key appears in the default locale. Convention-only linking silently breaks when someone renames one file.

## Translating UI strings

Dictionaries are plain TypeScript, and the pattern needs very little machinery.

```ts
// src/i18n/ui.ts
export const languages = { en: 'English', es: 'Español', fr: 'Français' } as const;
export type Lang = keyof typeof languages;
export const defaultLang: Lang = 'en';

export const ui = {
  en: {
    'nav.home': 'Home',
    'nav.about': 'About',
    'cart.items': 'Items in cart',
    'cart.empty': 'Your cart is empty',
  },
  es: {
    'nav.home': 'Inicio',
    'nav.about': 'Acerca de',
    'cart.items': 'Artículos en el carrito',
    'cart.empty': 'Tu carrito está vacío',
  },
  fr: {
    'nav.home': 'Accueil',
    'nav.about': 'À propos',
    'cart.items': 'Articles dans le panier',
    'cart.empty': 'Votre panier est vide',
  },
} as const satisfies Record<Lang, Record<string, string>>;

export type Key = keyof (typeof ui)[typeof defaultLang];
```

```ts
// src/i18n/utils.ts
import { ui, defaultLang, type Lang, type Key } from './ui';

export function getLangFromUrl(url: URL): Lang {
  const [, seg] = url.pathname.split('/');
  return seg in ui ? (seg as Lang) : defaultLang;
}

export function useTranslations(lang: Lang) {
  return function t(key: Key): string {
    return ui[lang][key] ?? ui[defaultLang][key];
  };
}
```

Note that `Key` is derived from the default language, and the `satisfies` clause checks the shape but not that every locale has every key. To force completeness, type each locale as `Record<Key, string>`:

```ts
type Dict = Record<Key, string>;
export const es: Dict = { /* the compiler now lists any missing keys */ };
```

That is the single most valuable constraint in the whole dictionary design: a missing translation becomes a compile error, instead of a runtime fallback that nobody notices.

`getLangFromUrl` above reads the first path segment, which works for locale folders that equal the locale code. If you use custom paths, prefer `Astro.currentLocale` and map codes yourself. In Astro components use it directly:

```html
---
import { useTranslations } from '../i18n/utils';
const t = useTranslations((Astro.currentLocale ?? 'en') as 'en' | 'es' | 'fr');
---
<a href="/">{t('nav.home')}</a>
```

### Pluralization, numbers and dates

Do not build these. The platform already has them: `Intl.PluralRules`, `Intl.NumberFormat`, `Intl.DateTimeFormat`, `Intl.RelativeTimeFormat`, `Intl.ListFormat`. Pass the locale and they do the work.

```ts
// src/i18n/format.ts
export const money = (locale: string, value: number, currency: string) =>
  new Intl.NumberFormat(locale, { style: 'currency', currency }).format(value);

export const when = (locale: string, d: Date) =>
  new Intl.DateTimeFormat(locale, { dateStyle: 'long' }).format(d);

const rules = new Map<string, Intl.PluralRules>();
export function plural(locale: string, n: number, forms: Partial<Record<Intl.LDMLPluralRule, string>>) {
  let r = rules.get(locale);
  if (!r) rules.set(locale, (r = new Intl.PluralRules(locale)));
  return (forms[r.select(n)] ?? forms.other ?? '').replace('{n}', String(n));
}
```

```html
---
import { plural } from '../i18n/format';
const label = plural('ru', 5, { one: '{n} товар', few: '{n} товара', many: '{n} товаров', other: '{n} товара' });
---
```

Remember to pass a locale tag, not a path: for an object entry with `path: 'french'` the tag is `codes[0]` (`'fr'`), and `Intl` will throw a `RangeError` on a malformed tag like `french`. A one-line helper that resolves the tag from the locale path avoids that class of bug.

Date formatting on a prerendered page uses the build machine’s `Intl` data, which is fixed once built. Time zones are the usual trap: pass `timeZone` explicitly or you format in the build server’s zone. Node ships full ICU data, so non-English locales work, but check that your build environment (a slim container) did not strip it.

## Locale-aware Svelte islands

An island needs two things from i18n: the strings it displays, and the locale it formats with. Astro does not provide a context that crosses the server/client boundary, so the answer is to pass them as props.

### Passing a slice of the dictionary

The simplest design resolves strings on the server and hands the island a small, serializable object:

```html
---
// src/pages/[lang]/shop.astro
import Cart from '../../components/Cart.svelte';
import { useTranslations } from '../../i18n/utils';
const lang = Astro.currentLocale as 'en' | 'es' | 'fr';
const t = useTranslations(lang);
---
<Cart
  client:visible
  locale={lang}
  labels={{ title: t('cart.items'), empty: t('cart.empty') }}
/>
```

```html
<!-- src/components/Cart.svelte -->
<script lang="ts">
  import { money } from '../i18n/format';

  interface Props {
    locale: string;
    labels: { title: string; empty: string };
  }
  let { locale, labels }: Props = $props();

  let total = $state(0);
  const formatted = $derived(money(locale, total, 'EUR'));
</script>

<section>
  <h2>{labels.title}</h2>
  <p>{total === 0 ? labels.empty : formatted}</p>
  <button onclick={() => (total += 9.5)}>+</button>
</section>
```

Only the strings the island needs are serialized into the page, so the client bundle does not carry the whole dictionary. When the island needs a large catalog (a rich editor, a data grid), load it lazily instead: ``const messages = await import(`../i18n/${locale}.json`)`` inside an `$effect` or an event handler, with a loading state. Dynamic import with a variable path is resolved by the bundler to a chunk per locale, so each visitor downloads one language.

### A locale-aware module with runes

If many components need `t()`, a shared module with rune state avoids prop drilling. The rule that matters is where the state lives.

```ts
// src/i18n/client.svelte.ts
import { ui, type Lang, type Key } from './ui';

export const i18n = $state<{ lang: Lang }>({ lang: 'en' });

export function setLang(lang: Lang) {
  i18n.lang = lang;
}

export function t(key: Key): string {
  return ui[i18n.lang][key];
}
```

Because `t` reads the `$state` object, any component that calls `t(...)` in its template re-renders when `setLang` runs. Initialize it once per page, early, from a prop:

```html
<!-- src/components/LangInit.svelte -->
<script lang="ts">
  import { setLang } from '../i18n/client.svelte';
  import type { Lang } from '../i18n/ui';
  let { lang }: { lang: Lang } = $props();
  setLang(lang);
</script>
```

This module is safe in client-only islands (`client:only="svelte"`) and in browser-run code. It is not safe to use on the server. Server-side rendering of islands runs in a long-lived process, and module-level state is shared across all requests. If one request calls `setLang('es')` during SSR and another runs concurrently or after, the second can render with the first’s language, a cross-request state leak. The same hazard applies to any module-level `$state` that holds per-request data.

> **Warning:** Do not hold the current locale in module-level state on the server. Pass it as a prop (or via Svelte `setContext` / `getContext`, which are scoped to a single component tree and so are per-render) and let islands that need it receive it explicitly.

The context-based variant works inside one island tree:

```html
<!-- src/components/I18nProvider.svelte -->
<script lang="ts">
  import { setContext, type Snippet } from 'svelte';
  import { ui, type Lang } from '../i18n/ui';

  let { lang, children }: { lang: Lang; children: Snippet } = $props();
  setContext('i18n', { get lang() { return lang; }, t: (k: keyof typeof ui.en) => ui[lang][k] });
</script>

{@render children()}
```

Context does not cross island boundaries: each `client:*` component is its own root, so a provider in one island does not reach a sibling island. The provider pattern is for the deep tree inside one island, and the props pattern is for the page-to-island hop. Use both: the page passes `lang` and `labels` to each island, and a larger island wraps its internals in a provider.

### Switching language in an island

A language switcher is a link, not a state change. Changing language changes the URL, which changes the page, so a plain `<a>` built with `getRelativeLocaleUrl` is both the simplest and the correct implementation: it works without JavaScript, it is crawlable, and it respects the cookie you set. Resist writing a Svelte switcher that mutates `lang` state, because it would produce a page whose URL says one thing and whose text says another.

```html
---
// src/components/LangSwitch.astro
import { getRelativeLocaleUrl } from 'astro:i18n';
import { languages } from '../i18n/ui';

interface Props { route: string }
const { route } = Astro.props;
const current = Astro.currentLocale;
---
<ul>
  {Object.entries(languages).map(([code, label]) => (
    <li>
      <a
        href={getRelativeLocaleUrl(code, route)}
        hreflang={code}
        lang={code}
        aria-current={code === current ? 'page' : undefined}
      >
        {label}
      </a>
    </li>
  ))}
</ul>
```

Three details raise it from a demo to a component you can ship. The `lang` attribute on each link marks the label as being in its own language, so a screen reader pronounces `Español` correctly regardless of the page language. `hreflang` documents the target language. And the `route` prop is the locale-less route (`'about'`), supplied by the page. Persist the choice on click with a tiny script that sets the `lang` cookie, which the root redirect reads:

```html
<script>
  document.addEventListener('click', (e) => {
    const a = (e.target as Element).closest<HTMLAnchorElement>('a[hreflang]');
    if (a) document.cookie = `lang=${a.hreflang}; path=/; max-age=31536000; samesite=lax`;
  });
</script>
```

With `<ClientRouter />` (Chapter 14), this script is a bundled module that runs once; the delegated listener on `document` survives navigations, which is why the code uses delegation instead of binding to the links.

### Directionality and fonts

Right-to-left languages need `dir="rtl"` on `<html>`. Map locale to direction in one place and use CSS logical properties (`margin-inline-start`, `padding-block`) everywhere so the layout flips without a second stylesheet. For fonts, a language such as Arabic or Japanese needs its own font file; the Fonts API of Chapter 13 lets you declare a family with `subsets` and `unicodeRange` so a locale only downloads the glyph ranges it uses, which keeps a multilingual site from shipping every script to every visitor.

```html
---
const rtl = new Set(['ar', 'he', 'fa', 'ur']);
const locale = Astro.currentLocale ?? 'en';
const dir = rtl.has(locale.split('-')[0]) ? 'rtl' : 'ltr';
---
<html lang={locale} dir={dir}>
```

## Error pages and 404s per locale

A site with several languages needs a 404 page per language, or users in `/es/` get an English error. Astro’s `404.astro` is one file at the root, so the localized-404 pattern is a fallback inside it or a manual routing rule. The 7.x changelog records a fix for localized custom error pages in i18n projects, which tells you that `src/pages/es/404.astro` is something Astro now recognizes. Build the files `src/pages/404.astro` and `src/pages/es/404.astro`, then confirm on your adapter that a request for a missing `/es/...` URL serves the Spanish page. If your host serves only the root 404, have it call the language detector: the root 404 reads `Astro.url.pathname`, derives the locale from the first segment, and renders the right copy from the dictionary.

## Testing an i18n site

Routing bugs in i18n are silent: a missing page falls back, a link points at the wrong prefix, an alternate is absent. Three cheap checks catch most of them.

1.  Compile-time: type every locale dictionary as `Record<Key, string>` so a missing key does not build.
2.  Build-time: after `astro build`, a script walks `dist/` and asserts that every default-locale route exists in every locale directory (or that the fallback you chose produced it). It is thirty lines of Node and catches renamed files.
3.  Link-time: render a page, extract all `<a href>` and `<link rel=alternate>` values and assert each resolves to a file in `dist/`. This is what finds the `prefixDefaultLocale` surprise when someone changes the config.

For the server paths (root redirect, domains), use the adapter’s preview or a container and test with `curl` including `Accept-Language` and `Host` headers; `curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' -H 'Accept-Language: es' http://localhost:4321/` shows the 302 and its target in one line.

## What changed across versions

When you read older tutorials, adjust for the following:

- Before 6.0, `redirectToDefaultLocale` defaulted to `true`. From 6.0 it defaults to `false` and requires `prefixDefaultLocale: true`.
- `routing: 'manual'` and the helper functions (`redirectToDefaultLocale`, `redirectToFallback`, `notFound`, `middleware`, `requestHasLocale`) arrived in 4.6, and `domains` in 4.9. Both are stable.
- `fallbackType: 'rewrite'` arrived in 4.15 and fixed the long-standing complaint that a fallback changed the URL.
- Fallback and domain-routing fixes continue through the 7.x changelog (rewrite fallbacks, localized error pages, domain routing respecting the request host), so keep the Astro version current; an i18n bug report against an old minor is usually fixed already.

## Key takeaways

- Astro i18n is routing and URL generation, not translation: you supply the dictionaries, the formatting and the content.
- `locales` entries are strings or `{ path, codes }`; use the object form to decouple URL segments from language tags. `fallback` keys and values must be locale paths, not codes.
- `prefixDefaultLocale: false` keeps the default language at the root; `true` gives every language a folder and requires you to write the root page. `redirectToDefaultLocale` defaults to `false` since 6.0 and is an error without `prefixDefaultLocale: true`.
- `fallbackType: 'redirect'` changes the URL; `'rewrite'` serves fallback content at the requested URL, so set `lang` from the content language, not blindly from `currentLocale`.
- `domains` needs `site`, `output: 'server'`, no prerendered pages and an adapter and proxy that pass `Host`/`X-Forwarded-Host` and the protocol; static builds reject it.
- `Astro.currentLocale` works everywhere; `preferredLocale` and `preferredLocaleList` exist only on demand-rendered pages and make the response vary by `Accept-Language`.
- Detect browser language only from `/`, with a 302, and let a stored cookie win; keep the rest of the site static.
- Build links with `getRelativeLocaleUrl` and friends, never by string concatenation; absolute variants and `getAbsoluteLocaleUrlList` give `hreflang` alternates.
- `routing: 'manual'` disables Astro’s middleware; `middleware()` lets you compose it with exceptions, and the helpers are available only in manual mode.
- Structure content as per-locale subfolders in a collection and link translations by a shared key; type dictionaries as `Record<Key, string>` so missing translations fail the build.
- Use `Intl` for plurals, numbers and dates. In Svelte islands pass strings and the locale as props; never keep the current locale in module-level state that runs on the server.

## Review Questions

1.  State the difference between what Astro’s i18n feature provides and what you must build yourself. Name three things in each category.
2.  A project has `locales: ['en', 'es']`, `defaultLocale: 'en'` and no `routing` key. Where does `src/pages/about.astro` serve, and where does `src/pages/es/about.astro` serve?
3.  What does `{ path: 'french', codes: ['fr', 'fr-CA'] }` change compared with the string `'fr'`? Give two places where the codes are used.
4.  Multiple choice. With that object entry, which `fallback` configuration is valid?

    a.  `fallback: { fr: 'en' }`
    b.  `fallback: { 'fr-CA': 'en' }`
    c.  `fallback: { french: 'en' }`
    d.  `fallback: { '/french/': 'en' }`
5.  What does `getRelativeLocaleUrl('fr-CA', 'x')` return in that setup, and what does `getPathByLocale('fr-CA')` return?
6.  You set `prefixDefaultLocale: true` and visit `/` on a static build. What do you see unless you write something, and what are two ways to send visitors to `/en/`?
7.  True or false: `redirectToDefaultLocale: true` with `prefixDefaultLocale: false` is a valid combination. Explain.
8.  What was the default of `redirectToDefaultLocale` before 6.0, and what is it now? Why does the change matter when copying old configs?
9.  Compare `fallbackType: 'redirect'` and `'rewrite'` on three points: URL in the address bar, content served, and what a static build generates.
10. On a rewrite fallback page for `/es/pricing/` serving English content, what does `Astro.currentLocale` return? What is the accessibility consequence if the layout sets `<html lang>` from it, and how do you avoid it?
11. Why might a project choose `prefixDefaultLocale: true` even when most traffic is in the default language?
12. List the conditions that `domains` requires. Which one fails validation in a static project?
13. A site using `domains` returns 404 for every page behind a reverse proxy. Name the most likely cause and the headers involved.
14. Given `domains: { fr: 'https://fr.example.com' }` and a file `src/pages/fr/about.astro`, what URL does it serve? What URL does `src/pages/ja/about.astro` serve when `ja` has no domain?
15. When is `Astro.preferredLocale` available? What does it return when the browser’s languages match nothing in your config?
16. What does `Astro.preferredLocaleList` return when the browser sends no `Accept-Language`?
17. Why must a page that reads `preferredLocale` be careful with caching, and what header addresses that?
18. Design the root-page logic for first-visit language detection. State which status code you use, from which paths you redirect, and what takes priority over `Accept-Language`.
19. Why is a 301 the wrong choice for language redirects from `/`?
20. Why should you use `getRelativeLocaleUrl` instead of writing `` `/${lang}/about/` ``? Name two configuration facts the helper accounts for.
21. Which helper returns one URL per configured locale, and what is it used for in the document head?
22. What does `routing: 'manual'` disable, and which other `routing` options may you set with it?
23. Write a middleware that lets `/api/*` bypass Astro’s i18n routing but applies the standard behavior to everything else. State the ordering you use in `sequence()` and why.
24. What does `notFound(context)` return, and under what two conditions does it produce a 404?
25. Describe a content-collection layout for a blog with English and Spanish posts, and how a dynamic route derives `lang` and `slug` from an entry id.
26. How would you make a missing translation key a compile error rather than a runtime fallback?
27. Why should you use `Intl.PluralRules` rather than `count === 1 ? 'item' : 'items'`? Give a language where the two-form rule fails.
28. A Svelte island needs three UI strings and the locale. Show how the Astro page passes them and how the island formats a price.
29. Find the bug: a `.svelte.ts` module exports `$state({ lang: 'en' })` and a `setLang` function that a server-rendered island calls during render. What can go wrong in production, and what do you do instead?
30. Why is a language switcher best implemented as a link rather than as component state in an island? Name two accessibility attributes that belong on its links.
