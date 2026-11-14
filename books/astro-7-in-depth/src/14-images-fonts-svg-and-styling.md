# Chapter 13: Images, Fonts, SVG and Styling

Assets are where most Astro sites win or lose their Core Web Vitals: an unsized hero image shifts the layout, a blocking web font delays text, an over-eager stylesheet bundle delays first paint. Astro’s `astro:assets` module and its Fonts API move those concerns from conventions you must remember into build-time and request-time machinery you configure once. This chapter covers the image components and the services behind them, remote image authorization, responsive layouts, the Fonts API, SVG components and the experimental optimizer, and then the CSS side: Astro’s scoped styles, how they interact with Svelte’s own scoping, the cascade order Astro guarantees, bundling and inlining, Tailwind, and theming without a flash of the wrong color scheme.

The recurring theme for a Svelte-based project is a boundary rule from Chapter 3: Astro components (`<Image />`, `<Picture />`, SVG components) cannot be imported into a `.svelte` file. A Svelte island receives *the result* of Astro’s asset pipeline, either as rendered children or as plain strings and numbers. I built a small project (Astro 7.4.1, `@astrojs/svelte` 9.1.0, Svelte 5.57.2) to verify the integration points below, and quote its output where the docs are silent.

## Where images live

Astro distinguishes three sources, and which one you choose decides whether anything is optimized.

| Location | Processed? | `src` value | Dimensions |
|------------------|------------------|------------------|------------------|
| `src/` (any folder, imported) | Yes: resized, re-encoded, hashed, cached | the import (`ImageMetadata`) | inferred from the file |
| `public/` | Never | URL path (`/images/a.jpg`) | you must supply `width` and `height` |
| Remote URL | Only if the host is authorized | full URL | supply them, or use `inferSize` |

An imported image is an `ImageMetadata` object: `{ src, width, height, format, fsPath? }`. This is why an `<img>` tag needs `hero.src`, whereas `<Image src={hero}>` takes the whole object. Prefer `src/` for anything you control; it gets content hashes (immutable caching), format conversion, and layout-shift-free dimensions for free. Use `public/` only for files that need a stable URL (favicons, `robots.txt`, files referenced externally).

## The `<Image />` and `<Picture />` components

```html
---
// src/pages/index.astro
import { Image, Picture } from 'astro:assets';
import hero from '../assets/hero.png'; // 1600x900

---
<Image src={hero} alt="A green field" width={800} />
<Picture src={hero} formats={['avif', 'webp']} alt="A green field" />
```

Real output from the test build (prerendered):

```html
<img src="/_astro/hero.4P1X1SD5_ZO2IX1.webp" alt="hero" loading="lazy" decoding="async" width="800" height="450">
<picture>
  <source srcset="/_astro/hero.4P1X1SD5_2lIhxy.avif" type="image/avif">
  <source srcset="/_astro/hero.4P1X1SD5_247apd.webp" type="image/webp">
  <img src="/_astro/hero.4P1X1SD5_20FVzn.png" alt="p" loading="lazy" decoding="async" width="1600" height="900">
</picture>
```

Points worth noting:

- The aspect ratio is preserved: asking for `width={800}` on a 1600x900 image produces `height="450"` without you computing it.
- `alt` is required. For decorative images pass `alt=""` explicitly; omitting it is a build error.
- The default output format of `<Image />` is WebP; `<Picture />` defaults to `['webp']` plus a fallback `<img>` in the original format (PNG here; JPEG for JPEG, GIF for animated, SVG for SVG). The `formats` order is the order of `<source>` elements, so list the best-compressing format first.
- `quality` accepts a number (0 to 100, interpreted per format) or a preset `low | mid | high | max`.
- Cropping: when you change the aspect ratio, `fit` (CSS `object-fit` values) and `position` control the crop. Since 6.0 the default service crops instead of stretching and never upscales: widths larger than the source are ignored.
- `background` is the flatten color when converting a transparent image to a format without alpha (JPEG), otherwise Sharp flattens onto black.
- `priority` is a shorthand for the above-the-fold image: `loading="eager"`, `decoding="sync"`, `fetchpriority="high"`. Use it for exactly the LCP image and nothing else.
- Extra attributes (`class`, `id`, `data-*`) pass through to the `<img>`. For `<Picture />`, use `pictureAttributes` to target the outer `<picture>`.

### Static versus on-demand rendering

The same component behaves differently depending on the route’s rendering mode:

- On a **prerendered** page, images are generated during the build into `/_astro/` with hashed names (13 variants for my test page, each logged by the build with before/after sizes).
- On an **on-demand** page, the `src` points at the image endpoint, `/_image?href=...&w=...&f=webp`, and the transform runs on the first request. The endpoint is configurable with `image.endpoint` (`route` and `entrypoint`). Because every distinct combination is a separate transform, add HTTP caching in front of `/_image` (a CDN, or the route cache of Chapter 12; the endpoint’s response is immutable for a given URL).

Responsive images multiply this: one image with a `constrained` layout produced seven width variants in my build. On prerendered pages that is build time; on on-demand pages it is request-time CPU and, with a paid image service, money.

### Responsive layouts

Setting `layout` (per component or globally with `image.layout`) makes Astro generate `srcset` and `sizes` for you:

```html
<Image src={hero} alt="Field" layout="constrained" width={800} height={450} />
```

```html
<img src="/_astro/hero..._ZwChTI.webp"
     srcset="/_astro/..._Zwpe83.webp 640w, /_astro/..._AqL2W.webp 750w, /_astro/..._ZwChTI.webp 800w,
             /_astro/..._Z9I9cN.webp 828w, /_astro/..._Z2lf7oz.webp 1080w, /_astro/..._1KQx5K.webp 1280w,
             /_astro/..._xx31x.webp 1600w"
     sizes="(min-width: 800px) 800px, 100vw"
     data-astro-image="constrained" data-astro-image-fit="cover" data-astro-image-pos="center"
     width="800" height="450" loading="lazy" decoding="async">
```

Layout values:

- `constrained`: shrinks to fit the container, never exceeds its requested (or intrinsic) size. The sensible default.
- `full-width`: fills the container width. Hero images.
- `fixed`: keeps its size and only generates density variants (`1x`, `2x`). Logos and icons.
- `none`: opt out when a global default is set.

Two precise points. First, the layout attributes in 7.4.1 are emitted as `data-astro-image`, `data-astro-image-fit` and `data-astro-image-pos` (the docs’ older examples show `style="--fit: cover"`; the facts for this book note that responsive styles now use a hash class plus these `data-` attributes, which matches what I saw). Second, the styles that make `constrained` and `full-width` images actually resize (`max-width: 100%` and `width: 100%`, wrapped in `:where()` so specificity is zero) are *not* added unless you set `image.responsiveStyles: true`. The default is `false`. Enable it unless you style the images yourself; with Tailwind 4 the docs recommend leaving it off because Tailwind’s cascade layers lose to unlayered CSS.

The generated `sizes` assumes the image spans nearly the viewport on small screens. In a two-column grid that is wrong, and the browser will download images that are too large. Override with `sizes` and `widths` manually (both together: `widths` requires `sizes`), or `densities` for fixed-size images. `densities` and `widths` are mutually exclusive, and both are ignored when a layout is set.

Global configuration:

```js
// astro.config.mjs
export default defineConfig({
  image: {
    layout: 'constrained',
    responsiveStyles: true,
    objectFit: 'cover',
    objectPosition: 'center',
    breakpoints: [640, 750, 828, 1080, 1280, 1668, 2048],
  },
});
```

Setting `image.layout` also applies to Markdown `![]()` images (Chapter 7).

### Remote images

```html
<Image src="https://cdn.example.com/cat.jpg" alt="Cat" inferSize />
```

A remote image is only *processed* if its host is authorized; otherwise it is rendered as a plain `<img>` (still with dimensions, which prevents layout shift). Authorization is a security control: the optimizer fetches arbitrary URLs on your server’s behalf, so an open policy is an SSRF and cost vector.

```js
image: {
  domains: ['images.example.com'],            // exact hostnames only, no wildcards
  remotePatterns: [
    { protocol: 'https', hostname: '**.amazonaws.com', pathname: '/my-bucket/**' },
  ],
}
```

`hostname: '**.x'` matches all subdomains and `'*.x'` exactly one level; `pathname: '/a/**'` matches all sub-routes and `'/a/*'` one level. Redirects are followed, and the *final* URL must also match, so an allowed host cannot be used to bounce to an internal address. `inferSize` (or `inferRemoteSize(url)` from `astro:assets`) downloads the image header to get its dimensions, and since 5.17.3 only does so for authorized hosts. In a build with many remote images, `inferSize` costs a request per image; prefer storing dimensions in your CMS.

Remote images in the build cache respect the origin’s `Cache-Control`, with revalidation through `ETag`/`Last-Modified` (5.1+). The cache lives in `cacheDir` (`./node_modules/.astro` by default), so persist it between CI runs to avoid re-downloading and re-encoding.

### Content collection images

The `image()` schema helper turns a relative path in frontmatter into `ImageMetadata`:

```ts
// src/content.config.ts
import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

const blog = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/blog' }),
  schema: ({ image }) => z.object({
    title: z.string(),
    cover: image().refine((img) => img.width >= 1200, { error: 'Cover must be at least 1200px wide' }),
    coverAlt: z.string(),
  }),
});
export const collections = { blog };
```

Because validation runs on the metadata, you can enforce minimum dimensions at build time, a cheap guard against low-resolution covers. Live collections do not support image optimization (Chapter 6).

## `getImage()`, and images in Svelte islands

`getImage(options)` returns `{ src, srcSet, attributes, options, rawOptions }` and is the building block the components use. It runs on the server only, and throws if called in client code (since 6.0). Use it when the destination is not an `<img>`: a CSS background, an Open Graph URL, a JSON response, or a prop for a Svelte island.

```html
---
import { getImage } from 'astro:assets';
import hero from '../assets/hero.png';
const optimized = await getImage({ src: hero, width: 400, format: 'avif' });
---
<div style={`background-image: url(${optimized.src})`}></div>
```

### Two ways to get optimized images into Svelte

A Svelte island cannot import `<Image />`. There are two approaches, both verified in my build.

**1. Pass a string prop computed by `getImage()`.**

```html
<!-- src/components/Card.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  let { title, src, children }: { title: string; src: string; children?: Snippet } = $props();
  let n = $state(0);
</script>

<article>
  <img {src} alt={title} />
  <h2 class="t">{title}</h2>
  <button onclick={() => n++}>{n} likes</button>
  {@render children?.()}
</article>
```

```html
---
import Card from '../components/Card.svelte';
import { getImage } from 'astro:assets';
import hero from '../assets/hero.png';
const opt = await getImage({ src: hero, width: 400, format: 'avif' });
---
<Card client:load title="Field" src={opt.src} />
```

The `src` is a plain string, so it serializes into the island’s `props` attribute. This is the right choice when the island *needs the URL* (a gallery that swaps images, a lightbox). Pass `srcSet` and dimensions too if the island renders its own `<img>`; `getImage()` gives you `srcSet.attribute` and `attributes` (`width`, `height`, `loading`, `decoding`).

**2. Pass the rendered component as a child.** Astro renders `<Image />` to static HTML and hands the string to the Svelte renderer as the default slot:

```html
<Card client:load title="Field" src={opt.src}>
  <Image src={hero} alt="Slotted" width={200} />
</Card>
```

Server-rendered output in my test:

```html
<article class="svelte-1s7zazm"> ... <button>0 likes</button>
<astro-slot><img src="/_astro/hero..._Z16Yh0a.webp" alt="slotted" data-astro-cid-w3uenvhf="true"
  loading="lazy" decoding="async" width="200" height="113"></astro-slot></article>
```

Finding: `{@render children?.()}` works with the slot string Astro passes (the content is wrapped in `<astro-slot>`), so the children-as-snippet style works in Svelte 5 for the default slot. Use child slots when the island does not need the URL, because the HTML is already optimized and costs no JavaScript, but remember the slot content is static: the island cannot re-render it or read its props. (Chapter 3 covers named slots and the hydration lifecycle.)

A second finding, which matters when you mix scoped Astro styles and islands: the island’s serialized props contained `"data-astro-cid-w3uenvhf": true`. That is Astro’s scoped-style attribute being forwarded as a prop to a component in a scoped-style file. A Svelte component that spreads `...rest` onto its root element will emit that attribute and thereby *join the parent’s style scope*. If you do not spread props, it is harmless but noisy.

## Image services

Astro’s image pipeline is a pluggable *service*: an object that knows how to build a URL, parse it back, produce HTML attributes, and (for local services) transform bytes. The default is Sharp:

```js
// astro.config.mjs
import { defineConfig } from 'astro/config';

export default defineConfig({
  image: {
    service: {
      entrypoint: 'astro/assets/services/sharp',
      config: {
        limitInputPixels: false,   // default true: refuse huge images (decompression-bomb guard)
        kernel: 'lanczos3',        // resize kernel (5.17+)
        webp: { effort: 6, alphaQuality: 80 },     // per-format encoder defaults (6.1+)
        jpeg: { mozjpeg: true },
        avif: { effort: 4 },
        png: { compressionLevel: 9 },
      },
    },
  },
});
```

The per-format blocks are passed to `sharp().webp()` and friends, and a per-image `quality` still wins. Other service helpers exported from `astro/config`: `sharpImageService(config)` and `passthroughImageService()`. The passthrough service performs no processing; use it on platforms where Sharp cannot run (historically Cloudflare Workers) to keep the benefits of the components: enforced `alt`, dimensions without layout shift and a consistent API.

### Build and runtime services (7.4)

Astro 7.4 lets you split the service in two:

```js
image: {
  service: {
    build:   { entrypoint: 'astro/assets/services/sharp' },
    runtime: { entrypoint: 'my-image-cdn-service' },
  },
}
```

The `build` service handles prerendered pages (always in Node during the build, even if your adapter prerenders elsewhere, for example Cloudflare’s workerd) and is also what `astro dev` uses. The `runtime` service handles on-demand pages and the `/_image` endpoint of the deployed site. The use case is exactly the mixed site: Sharp for the static catalog at build time, an image CDN for dynamic pages at request time. Cloudflare’s adapter also has its own `imageService` option object (adapter 14.2).

### Writing a service

A service module default-exports an object. The required hooks are `getURL(options, imageConfig)` and `getHTMLAttributes(options, imageConfig)`; optional ones include `validateOptions`, `getSrcSet`, `parseURL` and `transform` (the last two make it a *local* service handled by the built-in endpoint). A hosted-CDN service only needs the first two, and can extend `baseService` from `astro/assets` (`baseService` omits `transform`). Since 7.3 the hooks receive a `logger` argument. The helpers in `astro/assets/utils` (`isRemoteAllowed`, `matchPattern`, `imageMetadata`, `propsToFilename`, `hashTransform`…) are what the built-in services use.

```ts
// src/cdn-image-service.ts
import type { ExternalImageService } from 'astro';

const service: ExternalImageService = {
  validateOptions(options) {
    if (options.width && options.width > 3000) options.width = 3000;
    return options;
  },
  getURL(options) {
    const params = new URLSearchParams({ url: String(options.src) });
    if (options.width) params.set('w', String(options.width));
    if (options.format) params.set('f', String(options.format));
    return `https://img.example.com/?${params}`;
  },
  getHTMLAttributes(options) {
    const { src, format, quality, ...rest } = options;
    return rest;
  },
};
export default service;
```

Two security notes on any custom service: it must validate options (a user-controlled `w` is a denial-of-service lever), and a *local* service that fetches remote sources must call `isRemoteAllowed` itself.

SVG sources are not rasterized or resized by default: `image.dangerouslyProcessSVG` (6.3, default `false`) must be enabled to process SVGs through the pipeline, because crafted SVGs can be very expensive to render and are a denial-of-service vector. With `format` set, the 6.0 service rasterizes SVG input.

## SVG components

Importing a local `.svg` file in an `.astro` file gives you a component that inlines the markup:

```html
---
import Logo from '../assets/logo.svg';
---
<Logo width={20} />
```

Output: `<svg width="20" height="40" viewBox="0 0 40 40" data-astro-cid-...>...</svg>`. Props override the attributes in the file (note the original `height="40"` was kept because only `width` was passed, so pass both or none, or remove the intrinsic dimensions from the source and rely on `viewBox`). Props such as `fill="currentColor"` work for icon recoloring if the source paths do not hard-code their own fill.

Properties of SVG components to remember:

- They are Astro components, so they are not usable inside a Svelte file. Either pass them as slot children, or for Svelte-owned icons import the raw markup with Vite’s `?raw` suffix (`import icon from './x.svg?raw'` then `{@html icon}`, with `{@html}` safe here because the content is your own source file) or use a Svelte icon library.
- The `SvgComponent` type (from `astro/types`, since 5.14) types props that accept an SVG.
- Note that the XML comment in my source (`<!-- c -->`) survived in the output. Astro does not minify SVG by default.

### Experimental SVG optimization

```js
// astro.config.mjs
import { defineConfig, svgoOptimizer } from 'astro/config';

export default defineConfig({
  experimental: {
    svgOptimizer: svgoOptimizer({
      multipass: true,
      plugins: [{ name: 'preset-default', params: { overrides: { removeViewBox: false } } }],
    }),
  },
});
```

`experimental.svgOptimizer` (since 5.16, still experimental in 7.4) runs SVGO over every imported SVG component at build time. It is global: there is no per-file opt-out. Keep `viewBox` (SVGO’s default preset removes it in some versions, which breaks scaling) and be careful with `cleanupIds`/`prefixIds` when several inlined SVGs on one page define the same gradient ids.

## The Fonts API

Since 6.0 (stable) Astro has a first-class font pipeline. You declare families in config; Astro downloads and caches the font files at build time (and in dev), self-hosts them from your own origin, generates `@font-face` rules, preload links and size-adjusted fallbacks, and exposes the result as a CSS variable. The privacy and performance benefits come from self-hosting: no third-party requests, one connection, and cacheable immutable files.

```js
// astro.config.mjs
import { defineConfig, fontProviders } from 'astro/config';

export default defineConfig({
  fonts: [
    {
      provider: fontProviders.fontsource(),
      name: 'Inter',
      cssVariable: '--font-inter',
      weights: ['100 900'],        // variable range
      styles: ['normal'],
      subsets: ['latin', 'cyrillic'],
      fallbacks: ['system-ui', 'sans-serif'],
    },
    {
      provider: fontProviders.local(),
      name: 'Display',
      cssVariable: '--font-display',
      options: {
        variants: [{ src: ['./src/assets/fonts/Display.woff2'], weight: 'normal', style: 'normal' }],
      },
    },
  ],
});
```

Every family needs a `provider`, a `name` (the family as the provider knows it) and a `cssVariable` that you will reference. Built-in providers, from `fontProviders`: `adobe({ id })`, `bunny()`, `fontshare()`, `fontsource()`, `google()`, `googleicons()`, `npm()` and `local()`. Defaults per family: `weights: [400]`, `styles: ['normal', 'italic']`, `subsets: ['latin']`, `formats: ['woff2']`, `display: 'swap'`, `fallbacks: ['sans-serif']`, `optimizedFallbacks: true`. A note on cost: the default `styles` includes italic, so `weights: [400, 700]` downloads four files unless you restrict `styles`. For a variable font, give a range string (`'100 900'`) instead of individual weights; with the local provider put the range in the variant’s `weight`.

To use a family, render `<Font />` in the `<head>` and reference the variable:

```html
---
// src/layouts/Base.astro
import { Font } from 'astro:assets';
---
<html lang="en">
  <head>
    <Font cssVariable="--font-inter" preload={[{ subset: 'latin', style: 'normal' }]} />
    <Font cssVariable="--font-display" />
    <style is:global>
      body { font-family: var(--font-inter); }
      h1 { font-family: var(--font-display), var(--font-inter); }
    </style>
  </head>
  <body><slot /></body>
</html>
```

`<Font />` emits the `@font-face` declarations plus the variable definition (which includes the fallback chain) and, with `preload`, `<link rel="preload">` tags. `preload` is `false` by default; `true` preloads every file for the family and an array filters by `weight`, `style` and `subset`. Preload only what is needed for first paint; a preloaded font is downloaded even when the page never uses it. Because you choose where `<Font />` appears, you also choose *per page* which families load; a family not rendered on a page is not referenced there.

**Fallbacks.** When the last entry in `fallbacks` is a generic family (`sans-serif`, `serif`, `monospace`), Astro synthesizes an adjusted fallback face (size and metric overrides computed from the font) so that the swap from fallback to web font changes layout as little as possible. Set `optimizedFallbacks: false` to disable and use your list verbatim. This is the main reason to prefer the Fonts API over hand-written `@font-face`: it removes the CLS from font swapping without manual metric tuning.

**Granular downloads.** The same family (same `name`, `cssVariable` and `provider`) may be listed several times with different `weights`/`styles` combinations; Astro merges them and downloads only the requested combinations. This is how you get “400 normal and 700 normal only, plus 400 italic” without downloading all four combinations.

**Tailwind.** Register the variable in your theme rather than writing `font-family`: with Tailwind 4, `@theme inline { --font-sans: var(--font-inter); }` in your CSS entry.

**Programmatic access.** `fontData` (keyed by CSS variable) and `experimental_getFontFileURL(url, requestUrl?)` expose the downloaded file URLs, mainly for generating Open Graph images with Satori in an endpoint. On on-demand routes pass `context.url` as the second argument. `FontData` includes `subset` since 7.0.

**Custom providers.** The provider API (Font Provider reference) is a set of hooks: `init(context)` (in 7.4 the context gains `fetch()` and `getFontProperties()`, which will be required in Astro 8), `resolveFont(...)` and `listFonts(...)`. Use it if your company hosts fonts behind an internal service; otherwise the built-ins and `npm()` (fonts from an installed package) cover most cases.

> **Warning:** Providers that download from the network (Google, Bunny, Fontsource) need connectivity at build time, and the files land in the build cache. In CI with a restricted network, either allow the host or commit the files and use `local()`. I could not exercise remote providers in my sandbox, so verify the first CI run.

## Styling: Astro’s model

### Scoped styles

A `<style>` in an `.astro` file is scoped to that component by default. The compiler adds an attribute to the elements of the component and rewrites each selector accordingly. From the test build: `h1[data-astro-cid-w3uenvhf]{color:#00f}` and the attribute appears on every element, including `<html>`.

The strategy is `scopedStyleStrategy`:

| Value                   | Rewritten selector     | Specificity effect |
|-------------------------|------------------------|--------------------|
| `'attribute'` (default) | `h1[data-astro-cid-x]` | +1 (attribute)     |
| `'class'`               | `h1.astro-x`           | +1 (class)         |
| `'where'`               | `h1:where(.astro-x)`   | 0                  |

Per the configuration reference: `'where'` adds no specificity, so your component CSS loses to any author override (useful for design-system components); `'class'` helps when component element selectors must beat global defaults; `'attribute'` is useful when you manipulate `class` attributes dynamically and want to avoid conflicts with Astro’s own scoping. Keep the default unless you have a specificity problem.

Rules you need to internalize:

- Scoping applies to markup *in this component’s template*. Elements rendered by a child component, or injected via `set:html`, or produced by a slot from a *different* component, do not receive this component’s scope attribute. Style them with `:global()`: `article :global(h2) { ... }` scopes the `article` and leaves `h2` unscoped.
- `is:global` on the `<style>` tag disables scoping for the whole block. Use sparingly, ideally for a single base stylesheet.
- Passing `class` to a child works only if the child applies it to its root, and, with the default strategy, forwards `...rest` so the scope attribute follows. This is also what makes parent-scope styles able to reach a child’s root element.
- `define:vars={{ x }}` on `<style>` serializes frontmatter values to CSS custom properties (and, as the directive reference notes, applies them as inline style on the elements), so they are request-time values on on-demand pages. It makes the style block inline rather than bundled, so use it for a few values, not a stylesheet.
- Interpolated or computed class strings need `class:list` (it accepts strings, arrays, objects and `Set`s, and de-duplicates).

### Svelte styles live next to Astro’s, not under them

A Svelte component has its *own* scoping: Svelte compiles `.t { color: tomato }` to `.t.svelte-1s7zazm` and adds that class to matching elements. From my test build the page `<head>` contained:

```css
.t.svelte-1s7zazm{color:tomato}
article.svelte-1s7zazm figure{margin:0}
h1[data-astro-cid-w3uenvhf]{color:#00f}
```

Two independent systems, two different mechanisms (hash class versus `data-` attribute), no interaction. Consequences:

- Astro scoped styles in a page never reach into an island’s markup, and Svelte styles never reach out; to restyle an island from the page, either expose CSS custom properties from the island (the robust approach: `color: var(--card-accent, tomato)`), or use `:global()` on the Astro side, or pass `class`/props.
- The Svelte escape hatch is Svelte’s own `:global(...)` inside the component’s `<style>` (as in `article :global(figure)` above), which is how a Svelte component styles the slotted Astro output it receives as children.
- Both systems append to the same cascade. Order of appearance still applies, so equal-specificity conflicts are resolved by CSS order, which Astro controls (below).
- Svelte’s `<style>` is extracted into CSS like any other; with `build.inlineStylesheets: 'auto'` small stylesheets are inlined into the page, as seen above.

**Preprocessors in Svelte.** Setting `lang="scss"` (or `lang="ts"` with preprocessing features beyond type stripping) requires a Svelte preprocessor. Without one, my build failed:

```text
Card.svelte:13:2 Expected a valid CSS identifier
- Did you forget to add a scss preprocessor?
```

The fix is `svelte.config.js` with `vitePreprocess()` imported from `@astrojs/svelte` (it is no longer added by default since integration 6.0.0), plus the `sass` package:

```js
// svelte.config.js
import { vitePreprocess } from '@astrojs/svelte';
export default { preprocess: vitePreprocess() };
```

After installing `sass`, `<style lang="scss">` with `$c: tomato;` compiled to `.t.svelte-1s7zazm{color:tomato}`. Options passed to `svelte({ ... })` in `astro.config` take precedence over `svelte.config.js` (Chapter 3). `.astro` files, by contrast, process `lang="scss"` styles natively through Vite once `sass` is installed.

### Cascade order and imports

Astro documents the order of appearance, lowest to highest precedence: `<link>` tags in the head, then imported stylesheets, then scoped styles. Scoped styles come last, so with equal specificity a component’s `<style>` beats an imported global stylesheet; a more specific selector (an id) in an import still wins. Among imports, the order of import statements decides, and, importantly, CSS imported by a component applies *whenever that component is imported*, even if it is never rendered, because imported CSS is bundled with the module graph, not with the render. Import your global layout CSS first in a layout, so everything after it overrides.

Since 6.0 scripts and styles keep source order (`preserveScriptOrder` is the baked-in behavior), which makes this ordering stable between dev and build.

Imports available:

- `import '../styles/global.css'` in frontmatter: bundled, hashed, optimized. Works in any JS file, including Svelte components, and for `.scss`, `.styl`, and so on given the preprocessor package.
- Packages: `import 'pkg/styles.css'` works directly; for an extension-less specifier (`pkg/normalize`) add the package to `vite.ssr.noExternal`.
- `<link rel="stylesheet" href="/x.css">` for files in `public/` or external URLs: unprocessed, lowest precedence, and relative hrefs are not supported.

### Bundling and inlining

`build.inlineStylesheets` controls whether CSS ships as files or `<style>` tags:

- `'auto'` (default): stylesheets under Vite’s `build.assetsInlineLimit` (4 kB) are inlined; larger ones are external.
- `'always'`: everything inline; fewer requests, no cross-page caching of CSS. Good for small sites and for CSP setups using hashes (Chapter 16).
- `'never'`: every stylesheet external and cacheable; best for sites where users view many pages and the CSS is shared.

On many-page sites `'auto'` can produce the awkward result that the same small shared CSS is inlined into every page; if CSS dominates your HTML weight, `'never'` plus long-lived caching wins. Under `<ClientRouter />` (Chapter 14), navigation swaps `<head>` styles and Astro merges them, so inlined versus linked affects only the first load.

Cross-checking the Rust compiler (Chapter 1): CSS serialization is a little different than before (the 7.0 changelog notes colors like `rebeccapurple` may be emitted as `#639`; my `blue` became `#00f`). Do not diff built CSS textually.

## Tailwind and utility CSS

Tailwind 4 is a Vite plugin, not an Astro integration. `npx astro add tailwind` installs `@tailwindcss/vite` and registers it:

```js
// astro.config.mjs
import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({ vite: { plugins: [tailwindcss()] } });
```

```css
/* src/styles/global.css */
@import 'tailwindcss';
@theme inline { --font-sans: var(--font-inter); }
```

Import `global.css` in your layout. Tailwind scans files for class names, so Svelte templates work (`class="..."` and `class:` directives with literal names) but dynamically assembled class strings (`` `bg-${color}-500` ``) are not seen. Use complete class names. Tailwind 3 via `@astrojs/tailwind` is legacy; the upgrade path is: add the Vite plugin, remove the integration, and move `tailwind.config` content to CSS `@theme` and `@source`. Tailwind’s utilities live in CSS layers, so unlayered CSS (including Astro’s responsive image styles) beats them.

With scoped styles and Tailwind side by side, the usual division is: utilities for layout and spacing in templates, scoped `<style>` for component-specific details and anything awkward as utilities. `@apply` inside a scoped `<style>` needs `@reference "../styles/global.css"` in Tailwind 4 so the scoped block knows the theme.

## Dark mode and theming without a flash

The “flash of wrong theme” (FOWT) occurs because the stored preference lives in `localStorage`, available only to JavaScript, which usually runs after first paint. The cure is a tiny blocking inline script in `<head>`, before any CSS paints, that sets the theme on `<html>`. With Astro this means an `is:inline` script (bundled `<script>` tags are module scripts and deferred):

```html
---
// src/layouts/Base.astro
---
<html lang="en">
  <head>
    <meta name="color-scheme" content="light dark" />
    <script is:inline>
      (() => {
        let stored = null;
        try { stored = localStorage.getItem('theme'); } catch {}
        const theme = stored ?? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        document.documentElement.dataset.theme = theme;
      })();
    </script>
    <style is:global>
      :root { --bg: #fff; --fg: #111; color-scheme: light; }
      :root[data-theme='dark'] { --bg: #0b0b0f; --fg: #eee; color-scheme: dark; }
      body { background: var(--bg); color: var(--fg); }
    </style>
  </head>
  <body><slot /></body>
</html>
```

Considerations:

- Wrap `localStorage` access in `try/catch`: it can throw in private modes and sandboxed frames.
- `is:inline` scripts are not bundled or processed, so write plain JavaScript and keep it tiny. Under a strict CSP the inline script needs a hash or nonce, and CSP does not work with `<ClientRouter />` anyway (Chapter 16).
- With `<ClientRouter />`, the new page’s `<html>` attributes are swapped from the incoming document, and the incoming document ran the same blocking script only on the initial full load, not on client navigations. Re-apply the theme in an `astro:before-swap` handler (`event.newDocument.documentElement.dataset.theme = ...`) so the incoming document gets the stored theme before it replaces the current one (Chapter 14).
- A Svelte theme toggle is a normal island. Keep the *source of truth* in `document.documentElement.dataset.theme` and `localStorage`, not in component state, so multiple toggles and navigations agree:

```html
<!-- src/components/ThemeToggle.svelte -->
<script lang="ts">
  let theme = $state<'light' | 'dark'>('light');

  $effect(() => {
    theme = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
  });

  function toggle() {
    theme = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('theme', theme); } catch {}
  }
</script>

<button onclick={toggle} aria-pressed={theme === 'dark'}>
  {theme === 'dark' ? 'Dark' : 'Light'}
</button>
```

On the server the button renders as “Light” with `aria-pressed="false"`, then `$effect` corrects the state after hydration: no hydration mismatch because the effect runs only in the browser. If a visible label flip bothers you, render both icons and let CSS (`:root[data-theme='dark'] .sun { display: none }`) choose, so the markup is identical for both themes and no JavaScript is needed to look right.

Using `color-scheme` on `:root` also themes native controls and scrollbars, and `prefers-color-scheme` media queries remain a no-JS fallback if you prefer to skip the stored override entirely.

## Practical checklist

1.  Put images in `src/`, import them, and use `<Image />`; reserve `priority` for the LCP image.
2.  Set `image.layout` and `image.responsiveStyles` once; review `sizes` for multi-column layouts.
3.  Authorize remote hosts with `remotePatterns` and keep `dangerouslyProcessSVG` off.
4.  For Svelte islands, pass `getImage().src` strings or slot the rendered `<Image />`.
5.  Declare fonts in config, render `<Font />` once in the layout, preload only above-the-fold files.
6.  Keep Svelte CSS in Svelte, Astro CSS in Astro, and bridge with custom properties.
7.  Add `vitePreprocess()` and `sass` before using `lang="scss"` in Svelte.
8.  Theme with an `is:inline` head script and `data-theme`, not component state.

## Key takeaways

- Images in `src/` are optimized, hashed and dimensioned; `public/` is never processed; remote images are processed only when authorized by `image.domains` or `image.remotePatterns`.
- `<Image />` outputs WebP by default, requires `alt`, infers dimensions, and never upscales; `<Picture />` adds `<source>` per format with a fallback; `priority` sets eager, sync and high fetch priority.
- Responsive layouts (`constrained`, `full-width`, `fixed`, `none`) generate `srcset` and `sizes`; the resize styles require `image.responsiveStyles: true`, and the generated `sizes` may be wrong for multi-column layouts.
- Prerendered pages generate images at build time; on-demand pages transform through `/_image` at request time, so cache it. Astro 7.4 can use different `build` and `runtime` services.
- Svelte islands cannot use Astro components: pass `getImage()` strings as props, or pass rendered `<Image />` as children (works with `{@render children?.()}`, content wrapped in `<astro-slot>`).
- The Fonts API self-hosts fonts, generates `@font-face`, preload links and optimized fallbacks; declare families in `fonts`, render `<Font cssVariable />` in the head, and restrict `weights`, `styles` and `subsets` to avoid downloading unused files.
- SVG imports are inlined Astro components (not usable inside Svelte); the SVGO optimizer is experimental and global.
- Astro scopes with `data-astro-cid` attributes (`attribute`, `class` or `where` strategy); Svelte scopes with hash classes; the systems do not interact, so bridge with CSS custom properties and `:global()`.
- Svelte `lang="scss"` needs `vitePreprocess()` from `@astrojs/svelte` and `sass`; otherwise the build fails.
- Cascade order: link tags, then imports, then scoped styles; imported CSS applies even if the importing component is unused.
- Avoid theme flash with a blocking `is:inline` head script setting `data-theme`; re-apply it on `astro:before-swap` under `<ClientRouter />`.

## Review Questions

1.  Why does `<img src={hero}>` fail while `<img src={hero.src}>` works, but `<Image src={hero}>` is correct?
2.  What three properties must you provide for an image in `public/`, and why can Astro not infer them?
3.  Given a 1600x900 import, what `height` does `<Image src={hero} width={800} alt="" />` produce?
4.  What does `priority` set, and when is it appropriate to use it?
5.  Multiple choice. Which statement about `<Picture formats={['avif','webp']} />` is correct?
    a.  The `<img>` fallback is always WebP.
    b.  `<source>` elements are emitted in the order of `formats`; the fallback `<img>` uses the original format by default.
    c.  Only the first format is generated.
    d.  It requires `layout` to be set.
6.  A page is on-demand rendered. What does the `src` of an `<Image />` look like, and where does the transformation happen? What would you put in front of it?
7.  You enable `image.layout: 'constrained'` but images overflow narrow containers. What setting did you probably forget?
8.  A `constrained` image sits in a three-column grid on desktop, but the browser downloads very large variants. Why, and how do you fix it?
9.  Explain `domains` versus `remotePatterns`. What does `hostname: '**.amazonaws.com'` match versus `'*.amazonaws.com'`?
10. An allowed host redirects an image request to an internal URL. What happens and why?
11. What does `inferSize` do, what does it cost, and which images does it apply to?
12. Find the bug: a Svelte component contains `import { Image } from 'astro:assets'` and uses `<Image ... />`. Explain and give two fixes.
13. What does `getImage()` return, and why does calling it from a client-side script throw?
14. Show how to give a Svelte island an optimized AVIF URL as a prop. What serialization constraint applies to the prop?
15. In the slot approach, what element wraps the slotted HTML in the island’s server output, and what can the island not do with that content?
16. Why did the island’s props include `data-astro-cid-...` in the test build, and what is the consequence if the Svelte component spreads rest props onto its root?
17. What is the purpose of the 7.4 `{ build, runtime }` image service form? Give a realistic configuration.
18. Why is `image.dangerouslyProcessSVG` off by default?
19. Why are `<Image />` and SVG components unavailable in a `.svelte` file? Give one way to inline an SVG into a Svelte component.
20. With the Fonts API, how many files are downloaded for `weights: [400, 700]` with default styles? How do you reduce it?
21. What does `<Font cssVariable="--font-inter" preload />` output beyond `@font-face`, and why must you be selective with `preload`?
22. What do optimized fallbacks do, and when are they generated?
23. A page’s scoped `h2 { color: red }` does not affect `h2`s inside an `<Article />` child component. Why, and what are two ways to style them?
24. What does `article :global(h1) { }` compile to conceptually?
25. What is the difference between how Svelte and Astro scope styles? Show how both appear in compiled CSS.
26. A `.svelte` file has `<style lang="scss">` and the build fails with “Did you forget to add a scss preprocessor?” Give the complete fix.
27. State Astro’s cascade order for CSS sources, and explain why a component’s imported CSS can affect a page even if the component is never rendered.
28. When is `build.inlineStylesheets: 'never'` the better choice than `'auto'`?
29. Design: implement a dark mode with no flash and no hydration mismatch, including behavior under `<ClientRouter />`.
30. In a Tailwind 4 project with `image.responsiveStyles: true`, which wins, Astro’s responsive image styles or Tailwind utilities on the same `<img>`, and why?
