# Chapter 2: Project Anatomy and the .astro Language

An Astro project is small enough that you can hold its entire structure in your head, and the `.astro` file format is small enough that you can learn all of it in an afternoon. That is deliberate, and it is also why senior engineers sometimes underestimate it: the format has sharp edges (what counts as “content” for a slot, when attributes disappear, which directives imply `is:inline`, what the compiler no longer fixes for you) that only show up in production. This chapter walks through the project layout, the `.astro` syntax in full, props and slots, template directives, layouts and head management, imports and globs, the TypeScript toolchain (including the gap that `astro check` leaves for Svelte files), and the failures you should expect from the Rust compiler.

Examples in this chapter are runnable in a fresh Astro 7.4 project. Where a behaviour is easy to get wrong, I verified it by building the snippet and reading the HTML output, and I report the output rather than paraphrasing the documentation.

## Project anatomy

Astro reserves exactly one directory: `src/pages`. Everything else is convention.

```text
my-project/
├── public/                 # copied to the output verbatim, never processed
│   ├── robots.txt
│   └── favicon.svg
├── src/
│   ├── components/         # .astro and .svelte components (convention)
│   ├── layouts/            # layout components (convention)
│   ├── lib/                # plain TS, rune modules (convention)
│   ├── pages/              # REQUIRED: file-based routes
│   │   ├── index.astro
│   │   └── blog/[slug].astro
│   ├── styles/
│   ├── content.config.ts   # content collections (Chapter 6)
│   ├── middleware.ts       # onRequest (Chapter 10)
│   ├── fetch.ts            # advanced routing, RESERVED in 7.x (Chapter 5)
│   └── env.d.ts            # global type declarations
├── astro.config.mjs
├── svelte.config.js
├── tsconfig.json
└── package.json
```

A few of these deserve more than a line.

**`src/pages`** is required. A project without it has no routes. Files here become routes: `.astro` pages, Markdown (`.md`), MDX (`.mdx`, with the integration), `.html` pages, and TypeScript/JavaScript *endpoints* (`.ts`, `.js`). Files and directories prefixed with `_` are excluded from routing, which lets you colocate components, tests and helpers next to the pages that use them (Chapter 5).

**`public/`** is the escape hatch. Files here are copied untouched; you reference them by absolute URL path (`/robots.txt`, `/assets/cats/ginger.jpg`). Because nothing is bundled, hashed or optimized, a CSS or JS file in `public/` is shipped as-is. The rule: code you write belongs in `src/`, where Astro can bundle and fingerprint it; `public/` is for files whose URL must be stable and whose content Astro should not touch (`robots.txt`, verification files, PDFs, third-party scripts you load with `is:inline`).

**`astro.config.*`** may be `.js`, `.mjs` or `.ts` (and `.mts`). Since Astro 6.0, `.cjs` and `.cts` are no longer supported. Config files cannot read `.env` files directly: use `process.env` or `loadEnv` from `vite` there, and use `astro:env` in application code (Chapter 16).

**`.astro/`** is generated. `astro dev`, `astro build` and `astro sync` write type declarations into it (`.astro/types.d.ts`, `.astro/content.d.ts`, collection data). Add `.astro/` to `.gitignore`, but do reference its `types.d.ts` from your `tsconfig.json` `include`, as shown below.

**`src/env.d.ts`** is where you extend global types. A freshly generated `.astro/types.d.ts` contains:

```ts
/// <reference types="astro/client" />
/// <reference path="content.d.ts" />
```

so a project with a `tsconfig.json` that includes `.astro/types.d.ts` does not need a triple-slash reference in `env.d.ts`. You still use `src/env.d.ts` for your own augmentations (`App.Locals`, `App.SessionData`, `Window` additions) as we do in later chapters.

> **Note:** The folder names `components`, `layouts` and `styles` are community conventions. If your team prefers feature folders (`src/features/cart/Cart.svelte`, `src/features/cart/cart.svelte.ts`), Astro does not care. Only `src/pages` and the reserved filenames (`content.config.ts`, `live.config.ts`, `middleware.ts`, `fetch.ts`, `actions/index.ts`) are special.

## The shape of an `.astro` file

An Astro component has two parts separated by a code fence of three dashes:

```html
---
// Component script (frontmatter): runs on the server, never in the browser
import Card from './Card.astro';
const title = 'Hello';
---
<!-- Component template: HTML plus JSX-like expressions -->
<Card title={title}>
  <p>Welcome</p>
</Card>
<style>
  p { color: tomato; }
</style>
<script>
  console.log('runs in the browser, bundled');
</script>
```

- The **frontmatter** is TypeScript. It is the body of an async function: top-level `await`, `return Astro.redirect(...)` (only in pages), and any import are allowed. Imports are hoisted to module scope; the rest runs per render (Chapter 1).
- The **template** is HTML extended with expressions in `{}`, components, and directives. A template may have multiple root elements and needs no wrapper.
- `<style>` blocks are scoped by default (Chapter 13). `<script>` blocks are bundled and executed in the browser (Chapter 4).

An `.astro` file with no fence is legal; the frontmatter is optional. A page that returns a bare fragment of HTML gets `<!DOCTYPE html>` prepended automatically: building `<span>hello</span>` as a page yields `<!DOCTYPE html><span>hello</span>`. Files under `src/pages` that are marked as partials do not (see below).

### Expressions

Curly braces evaluate JavaScript and insert the result. Strings are HTML-escaped; arrays are flattened; `false`, `null`, `undefined` render nothing.

```html
---
const user = { name: 'Ana', admin: true };
const items = ['Dog', 'Cat', 'Platypus'];
const html = '<b>bold</b>';
---
<p>{user.name}</p>                      <!-- Ana -->
<p>{html}</p>                           <!-- &lt;b&gt;bold&lt;/b&gt; (escaped) -->
{user.admin && <p>Admin tools</p>}
{user.admin ? <p>Admin</p> : <p>User</p>}
<ul>{items.map((item) => <li>{item}</li>)}</ul>
{/* a JavaScript comment: not emitted */}
<!-- an HTML comment: emitted into the output -->
```

Conditional rendering uses `&&` and ternaries; lists use `.map()`. There is no `{#if}`; that is Svelte syntax and only valid inside `.svelte` files. Remember the difference when you move markup between the two.

### Differences from JSX

Astro’s template is “a superset of HTML”, and the divergences from JSX are mostly relaxations:

| Concern | JSX | `.astro` |
|------------------------|------------------------|------------------------|
| Attribute names | `className`, `htmlFor`, `dataValue` | `class`, `for`, `data-value` (standard HTML kebab-case) |
| Root element | exactly one (or `<>`) | any number |
| Comments | `{/* */}` | `{/* */}` or `<!-- -->` (the latter is emitted) |
| Event handlers | `onClick={fn}` | **not supported** on HTML elements; use a `<script>` |
| Whitespace | JSX rules | JSX rules by default since 7.0 (`compressHTML: 'jsx'`) |

The event-handler row is the one that trips people coming from React or Svelte. In an `.astro` template, `<button onclick={handleClick}>` renders the attribute as a string (or nothing useful); the function never reaches the browser. Event wiring is done with `addEventListener` in a `<script>`, or with an island. The docs’ own caution on this point is worth quoting: HTML attributes “will be converted to strings, so it is not possible to pass functions and objects to HTML elements”.

### How attributes are rendered

I verified the following by building a template. Given:

```html
<p style={{ color: 'red' }} data-x={undefined} hidden={false} data-y={true}>z</p>
```

the output is:

```html
<p style="color:red" data-y="true">z</p>
```

- Object values for `style` are converted to inline CSS.
- `undefined` (and `null`) attributes are omitted entirely.
- `false` omits the attribute; `true` on a *known boolean attribute* (`hidden`, `disabled`) renders the bare attribute, while on a `data-*` attribute it renders the string `"true"`.

So `data-active={isActive}` with `isActive === false` renders no attribute at all, not `data-active="false"`. If your CSS or script depends on the string `"false"`, write `data-active={String(isActive)}`.

### Fragments and dynamic tags

`<Fragment>` (or `<>…</>`) groups nodes without a wrapper element. Its main use in Astro is to attach `set:html` or a `slot` name without adding DOM:

```html
<Fragment set:html={htmlString} />
<Card><Fragment slot="actions"><button>A</button><button>B</button></Fragment></Card>
```

A variable holding a tag name or component can be rendered dynamically, provided its name is **capitalized**, otherwise Astro emits it as a literal tag name:

```html
---
import Heading from './Heading.astro';
const Tag = Astro.props.level === 1 ? 'h1' : 'h2';
const Wrapper = Astro.props.fancy ? Heading : 'div';
---
<Tag>Title</Tag>
<Wrapper><slot /></Wrapper>
```

Two documented limits of dynamic tags: `client:*` directives do not work (the bundler must know statically which component to bundle for the browser), and `define:vars` is not supported.

## Props

Props arrive on `Astro.props`. Annotate them with a `Props` interface or type in the frontmatter, and the editor tooling and `astro check` use it for every call site:

```html
---
// src/components/Price.astro
interface Props {
  amount: number;
  currency?: 'EUR' | 'BGN' | 'USD';
  locale?: string;
}

const { amount, currency = 'EUR', locale = 'en' } = Astro.props;
const formatted = new Intl.NumberFormat(locale, { style: 'currency', currency }).format(amount);
---
<span class="price">{formatted}</span>
```

The interface may be exported but need not be. Two patterns from the TypeScript guide are worth memorizing:

```ts
type Props = Record<string, never>;      // component takes no props or slotted content
type Props = { children: any };         // children are required
```

Reuse HTML attribute types so wrapper components do not re-declare `href`, `target` and friends. The spread then forwards unknown attributes:

```html
---
// src/components/Link.astro
import type { HTMLAttributes } from 'astro/types';

interface Props extends HTMLAttributes<'a'> {
  external?: boolean;
}

const { external = false, href, ...attrs } = Astro.props;
const extra = external ? { target: '_blank', rel: 'noopener noreferrer' } : {};
---
<a href={href} {...attrs} {...extra}><slot /></a>
```

`astro/types` also exports `ComponentProps<typeof Button>` to extract another component’s props, `HTMLTag`, and `Polymorphic` for `as`-style components:

```html
---
import type { HTMLTag, Polymorphic } from 'astro/types';
type Props<Tag extends HTMLTag> = Polymorphic<{ as: Tag }>;
const { as: Tag, ...props } = Astro.props;
---
<Tag {...props} />
```

> **Warning:** Props to an `.astro` component are passed by reference *within a render*, so functions and class instances are fine between Astro components. This freedom ends at the framework boundary: props to a *hydrated* Svelte component are serialized into an HTML attribute (Chapter 3). A prop that is fine for `Price.astro` may be silently broken for `Price.svelte client:load`.

## Slots

Slots are how Astro components compose. A `<slot />` in a component marks where its children are rendered.

```html
---
// src/components/Panel.astro
const { title } = Astro.props;
---
<section class="panel">
  <header><slot name="header"><h2>{title}</h2></slot></header>
  <div class="body"><slot /></div>
  {Astro.slots.has('footer') && <footer><slot name="footer" /></footer>}
</section>
```

```html
---
import Panel from '../components/Panel.astro';
---
<Panel title="Cart">
  <p>2 items</p>
  <Fragment slot="footer"><a href="/checkout">Checkout</a></Fragment>
</Panel>
```

Rules worth knowing precisely:

- Unnamed children go to the default `<slot />`. A child with `slot="name"` goes to `<slot name="name" />`. The `slot` attribute must be on a direct child of the component tag; use `<Fragment slot="x">` (or any wrapper element) to place several nodes in a slot.
- **Fallback content** inside `<slot>…</slot>` renders only when *no matching element was passed*. Passing an empty slot (an element that exists but has no content) suppresses the fallback. The docs state this: “Fallback content is only displayed when no slot element can be found.” In my test, `<Base>{}</Base>` (an expression that evaluates to nothing) still showed the fallback, because an empty expression passes no node. Do not rely on this distinction; if “empty means fallback” matters, check emptiness explicitly with `Astro.slots.has()` and render yourself.
- **Transferring slots** forwards a slot through an intermediate component by using both `name` and `slot` on a `<slot>` element. This is the pattern for nested layouts.

```html
---
// src/layouts/Home.astro
import Base from './Base.astro';
---
<Base title="Home">
  <slot name="head" slot="head" />
  <slot />
</Base>
```

With `Base.astro` placing `<slot name="head" />` inside `<head>`, a page that writes `<meta slot="head" name="x" content="y" />` inside `<Home>` gets that `<meta>` in the document head. I built exactly this and the output was `<head><title>Home</title><meta name="x" content="y"></head>`.

### `Astro.slots`

`Astro.slots.has(name)` answers “did the caller provide this slot?”, which is what you want for conditional wrappers like the footer above. `Astro.slots.render(name, args?)` renders a slot to an HTML string, optionally passing arguments to function children. It is for advanced use: post-processing slot HTML, or building “render prop” style components.

```html
---
// src/components/Shout.astro
const message = Astro.props.message.toUpperCase();
const html = await Astro.slots.render('default', [message]);
---
<Fragment set:html={html} />
```

```html
<Shout message="slots!">{(m: string) => <div>{m}</div>}</Shout>
```

This renders `<div>SLOTS!</div>` (verified). The child is a *function*, which only works between Astro components, because the function is called on the server while rendering. Remember the boundary: you cannot pass such a function child to a hydrated Svelte component (Chapter 3).

### `Astro.self` and recursion

`<Astro.self>` renders the current component recursively, which suits trees and nested lists:

```html
---
// src/components/NestedList.astro
type Item = string | Item[];
interface Props { items: Item[] }
const { items } = Astro.props;
---
<ul>
  {items.map((item) => (
    <li>{Array.isArray(item) ? <Astro.self items={item} /> : item}</li>
  ))}
</ul>
```

`<NestedList items={['A', ['B', 'C'], 'D']} />` renders `<ul><li>A</li><li><ul><li>B</li><li>C</li></ul></li><li>D</li></ul>`.

## Template directives

Directives are `name:value` attributes that instruct the compiler or renderer. The ones that belong to `.astro` templates are below; client and server directives (`client:*`, `server:defer`) are covered in Chapters 3 and 9.

### `class:list`

`class:list` (powered by `clsx`) builds a class string from strings, objects (truthy keys are kept) and arrays (flattened); `false`, `null` and `undefined` are skipped.

```html
---
const cls = ['a', { b: true, c: false }, ['d']];
---
<p class:list={cls} />        <!-- class="a b d" (verified) -->
<button class:list={['btn', { 'btn-primary': primary }, className]}><slot /></button>
```

### `set:html` and `set:text`

`set:html` injects an unescaped HTML string as the element’s children; `set:text` injects a string that is escaped. Both work on any element and on `<Fragment>`:

```html
---
const raw = '<b>bold</b>';
---
<p set:html={raw} />    <!-- <p><b>bold</b></p> -->
<p set:text={raw} />    <!-- <p>&lt;b&gt;bold&lt;/b&gt;</p> -->
<p>{raw}</p>            <!-- the same escaped output as set:text -->
```

`set:html` is the XSS surface of `.astro` templates. Never pass user-controlled strings to it unless they have been sanitized by a library you trust. It is especially useful on a `<Fragment>` for HTML fetched from a CMS.

### `is:raw`

`is:raw` tells the compiler to treat the children as literal text, so braces and component-like tags are not interpreted. It is how you document template syntax or pass pseudo-syntax to a component:

```html
<code is:raw>{not} {evaluated}</code>    <!-- <code>{not} {evaluated}</code> (verified) -->
```

### `define:vars`

`define:vars` passes frontmatter values into a `<style>` (as CSS custom properties) or a `<script>` (as variables), serialized with `JSON.stringify`:

```html
---
const accent = '#639';
const productId = 'sku-123';
---
<style define:vars={{ accent }}>
  a { color: var(--accent); }
</style>
<script define:vars={{ productId }}>
  console.log(productId);
</script>
```

On a `<style>` it does not change scoping behaviour. On a `<script>` it **implies `is:inline`**: the script is no longer bundled, and the output wraps it in an IIFE with the variables declared at its top. I built the example and got `<script>(function(){const productId = "sku-123";\nconsole.log(productId);})();</script>`. An inline script is duplicated for every use of the component on a page; for repeated components prefer `data-*` attributes read by a bundled script (Chapter 4).

> **Warning:** `define:vars` values are JSON in the HTML, therefore public. And because it makes the script inline, it forfeits TypeScript, imports and deduplication.

### `is:inline`, `is:global`, `transition:*`

`is:inline` opts a `<script>` or `<style>` out of Astro’s processing (no bundling, no TypeScript, no scoping); `is:global` opts a style block or selector out of scoping (Chapter 13). `transition:name|animate|persist|persist-props` and `data-astro-rerun`/`data-astro-reload` belong to the client router (Chapter 14).

A summary of what Astro does to a `<script>` tag by default, because the rules drive many bugs: a `<script>` with no attributes other than `src` is processed (TypeScript, import bundling, `type="module"`, deduplication, and inlining when small). Any other attribute makes it unprocessed (`is:inline` makes this explicit). `define:vars` and `is:inline` both mean “emitted as written”.

## Layouts and composition

A layout is a component that supplies the document shell and a `<slot />` for page content. There is nothing magic about it:

```html
---
// src/layouts/Base.astro
import '../styles/global.css';

interface Props {
  title: string;
  description?: string;
}

const { title, description = 'A shop built with Astro' } = Astro.props;
const canonical = new URL(Astro.url.pathname, Astro.site);
---
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width" />
    <meta name="generator" content={Astro.generator} />
    <title>{title}</title>
    <meta name="description" content={description} />
    <link rel="canonical" href={canonical} />
    <slot name="head" />
  </head>
  <body>
    <slot name="header"><header><a href="/">Home</a></header></slot>
    <main><slot /></main>
    <slot name="footer" />
  </body>
</html>
```

```html
---
// src/pages/index.astro
import Base from '../layouts/Base.astro';
---
<Base title="Home">
  <link slot="head" rel="preload" href="/hero.avif" as="image" />
  <h1>Welcome</h1>
</Base>
```

A few things about composition deserve attention.

**Head management is explicit.** There is no `<svelte:head>` equivalent and no head manager: whatever you write in the layout’s `<head>`, and whatever callers inject through a named `head` slot, is what ships. Astro hoists scoped styles and processed scripts into the head for you, but metadata is your responsibility. Build a small `SEO.astro` component that takes `title`, `description`, `image` and renders the `<meta>` set, and place it inside the layout. Note that `Astro.site` is `undefined` unless you set `site` in the config, which makes `new URL(path, Astro.site)` throw; set `site` if you build canonical URLs, sitemaps or RSS.

**Layouts nest by transferring slots**, as shown earlier: `PostLayout` wraps `Base`, forwarding `head` with `<slot name="head" slot="head" />`.

**Markdown layouts.** Markdown pages can set a `layout` frontmatter field naming a layout component that receives `frontmatter` and `headings` as props. We cover this in Chapter 7; with content collections you will usually render entries inside a normal `.astro` page instead, which is more flexible.

**Layouts do not hydrate.** A layout is an Astro component, and Astro components cannot have `client:*` directives. Interactive pieces inside a layout (a cart badge, a language switcher) are Svelte islands placed in the layout’s template. They hydrate independently, and with the client router they can persist across navigations (Chapter 14).

**`.html` components.** Plain `.html` files can be imported as components or served as pages. They have no frontmatter, no expressions and no imports; their scripts are unbundled (as if `is:inline`), and they may only reference assets in `public/`. They exist for migrating legacy markup.

### Page files and special pages

`src/pages` accepts `.astro`, `.md`, `.mdx`, `.html`, and `.js`/`.ts` endpoints. Two special pages exist beyond routing: `404.astro` (builds to `404.html`) and `500.astro`, which is used only for on-demand rendered routes and receives an `error` prop (type `unknown`) for the error thrown during rendering. Do not render `error.stack` to visitors. Both are covered in Chapter 5.

A **partial** is a page that should render as a fragment, without `<!DOCTYPE html>`, `<head>` or hoisted scoped styles and scripts, to be fetched by a library such as htmx:

```html
---
// src/pages/partials/cart-count.astro
export const partial = true;
---
<li>3 items</li>
```

The `partial` export must be statically analyzable: the literal `true` or an `import.meta.env.X` reference. Partials with scoped `<style>` or bundled `<script>` lose them, since there is no head to hoist them into. I verified that a server-rendered partial returns just its `<li>` element, with no doctype. `.md` pages cannot be partials; `.astro` and `.mdx` can.

## Imports, aliases and globs

### What can be imported

Astro (through Vite) resolves `.astro`, Markdown, `.js`/`.mjs`, `.ts`, npm packages, `.json`, `.css`, `.module.css`, and assets (images, fonts, SVG) out of the box. Framework components (`.svelte`) and MDX come with integrations. Imported assets resolve to a URL or, for images processed by Astro, an `ImageMetadata` object (Chapter 13); the `?url`, `?raw` and `?inline` suffixes are Vite’s:

```html
---
import logoUrl from '../assets/logo.png?url';
import sql from '../db/schema.sql?raw';
import '../styles/global.css';
---
```

### Aliases

Aliases are configured in `tsconfig.json` and picked up automatically by Astro; the dev server restarts when the file changes:

```json
{
  "extends": "astro/tsconfigs/strict",
  "include": [".astro/types.d.ts", "**/*"],
  "exclude": ["dist"],
  "compilerOptions": {
    "paths": {
      "@components/*": ["./src/components/*"],
      "@layouts/*": ["./src/layouts/*"],
      "@lib/*": ["./src/lib/*"]
    }
  }
}
```

```html
---
import Base from '@layouts/Base.astro';
import { formatPrice } from '@lib/format';
---
```

Aliases from `tsconfig.json` work for `.astro` files, `.ts` files and, with the Svelte integration, `.svelte` files, since Vite resolves them all. Note that this differs from SvelteKit, where `$lib` is a built-in alias; there is no `$lib` in Astro unless you define one.

### `import.meta.glob()`

`import.meta.glob()` is Vite’s bulk-import primitive and replaces `Astro.glob()`, which was removed in 6.0. It takes a glob pattern and returns an object mapping paths to either lazy loader functions or, with `eager: true`, the modules themselves.

```html
---
// Lazy: values are () => Promise<module>
const lazy = import.meta.glob('../components/*.astro');

// Eager, with a named import to avoid loading whole modules
const raws = import.meta.glob('../data/*.txt', { eager: true, query: '?raw', import: 'default' });
const jsons = import.meta.glob('../data/*.json', { eager: true, import: 'default' });
---
<pre>{JSON.stringify(jsons)} {JSON.stringify(raws)}</pre>
```

Building this against two data files printed `{"../data/a.json":{"a":1}} {"../data/b.txt":"hello\n"}`. The constraints are those of Vite’s static analysis:

- The pattern must be a **string literal**; it cannot contain variables or be computed.
- It must start with `./`, `../` or `/` (project root).
- The keys of the result are the matched paths, relative to the importing file as written in the pattern.
- Markdown results have the `MarkdownInstance` shape (`frontmatter`, `file`, `url`, `Content`, `getHeadings()`, …); `.astro` results have `AstroInstance`. Pass a generic for typing: `import.meta.glob<MarkdownInstance<Frontmatter>>('./posts/**/*.md', { eager: true })`.

> **Senior tip:** Use `import.meta.glob` for files that are *code or assets* (a directory of Svelte components keyed by name, icon SVGs, JSON fixtures). Use content collections (Chapter 6) for *content*: they give you schema validation, typed queries, references and incremental updates, which a glob never will. A glob with `eager: true` pulls every match into the same bundle.

A pattern worth knowing for Svelte projects is a component registry resolved at build time, which also demonstrates the boundary between glob and islands:

```html
---
import type { Component } from 'svelte';

const registry = import.meta.glob<{ default: Component }>('../components/widgets/*.svelte', {
  eager: true,
});
const Widget = registry[`../components/widgets/${Astro.props.kind}.svelte`]?.default;
---
{Widget ? <Widget /> : <p>Unknown widget</p>}
```

This renders widgets statically. Remember that a dynamic tag such as `<Widget client:load />` is not supported, because the bundler cannot know which component to ship to the browser; hydrating a registry-selected component requires listing explicit, directly imported components in the template.

## TypeScript

Astro always treats frontmatter as TypeScript, and strips types without checking them. Checking is a separate step.

### Configuration

Extend one of the three templates, `astro/tsconfigs/base`, `strict` or `strictest`:

```json
{
  "extends": "astro/tsconfigs/strict",
  "include": [".astro/types.d.ts", "**/*"],
  "exclude": ["dist"]
}
```

`strict` and `strictest` enable `verbatimModuleSyntax`, which makes TypeScript demand `import type` for type-only imports. Follow it: a bare `import { SomeType }` of a type may cause the bundler to try to bundle it as JavaScript.

```ts
import type { CollectionEntry } from 'astro:content';   // good
import { type APIRoute } from 'astro';                    // also fine
```

For Svelte projects on TypeScript 6, the combination `astro/tsconfigs/strict` plus `svelte-check` works; Svelte 5 handles `lang="ts"` natively (type annotations are stripped without a preprocessor), but if you use `<style lang="scss">` or TypeScript features that need transformation, keep `vitePreprocess()` in `svelte.config.js`.

### Global types

Put declarations in `src/env.d.ts`:

```ts
// src/env.d.ts
declare namespace App {
  interface Locals {
    user?: { id: string; name: string };
  }
  interface SessionData {
    cartId?: string;
  }
}

interface Window {
  dataLayer: unknown[];
}
```

`App.Locals` and `App.SessionData` come back in Chapters 10 and 12.

### Typing `getStaticPaths`

The inference helpers keep `Astro.params` and `Astro.props` in sync with the function that produces them:

```html
---
import type { GetStaticPaths, InferGetStaticParamsType, InferGetStaticPropsType } from 'astro';

export const getStaticPaths = (() => {
  return [{ params: { id: 'a' }, props: { title: 'A' } }];
}) satisfies GetStaticPaths;

type Params = InferGetStaticParamsType<typeof getStaticPaths>;
type Props = InferGetStaticPropsType<typeof getStaticPaths>;

const { id } = Astro.params;
const { title } = Astro.props;
---
```

### Checking: `astro check` and `svelte-check`

The dev server and build **do not type-check**. Add a gate:

```json
{
  "scripts": {
    "build": "astro check && astro build",
    "check": "astro check && svelte-check --tsconfig ./tsconfig.json"
  }
}
```

`astro check` checks `.astro` and `.ts` files (options include `--watch`, `--tsconfig`, `--minimumSeverity`, `--minimumFailingSeverity`, `--noSync` and `--preserveWatchOutput`). It does **not** check `.svelte` files. Run `svelte-check` for those. This gap is the single most common reason that a Svelte-based Astro project has a type error in CI that never surfaced locally. For Svelte components used from `.astro` files, `@astrojs/svelte` ships a `svelte-shims.d.ts` so that `client:*` directives type-check on Svelte components and snippet props like `children` become optional at the call site (we look at it in Chapter 3).

TypeScript 7 is not supported by `astro check` at 7.4; the CLI prints instructions for experimenting with it. Stay on TypeScript 6 for now.

## Rust compiler failure modes, catalogued

Chapter 1 introduced the strictness change. Here is what to look for in an `.astro` file when a build breaks or the output changes after an upgrade.

**1. Unclosed element or component tags** raise `[CompilerError] Unexpected token`, typically located at the end of the file. The location is where the parser ran out of input, not where the omission is. Search upward for the last element you opened. A repeated variant is a component used as `<Card>` and never closed because the author thought of it as self-closing; use `<Card />` for empty components.

**2. Invalid nesting passes through.** `<p>` containing `<div>`, block content in `<a>` inside `<p>`, `<div>` directly in `<table>` or `<ul>`: none of these error. The server HTML is emitted as authored and the browser reparses it, producing a different DOM. This is the dangerous case because the build is green. Add an HTML validity check for template-heavy sites.

**3. Slots.** The `slot="x"` attribute is only meaningful on a direct child of a component tag. When migrating, grep for `slot=` and confirm that each one sits directly under a component tag and that the named slot exists in the target component.

**4. Whitespace.** `compressHTML: 'jsx'` removes whitespace-only text between sibling elements on separate lines. Use `{" "}` for a significant space.

**5. CSS output.** Hex and quote serialization differences are cosmetic.

A defensive practice: after any compiler or Astro upgrade, build and diff `dist/` against the previous build. Because Astro output is plain HTML, the diff is the most reliable regression test you have.

## Svelte components in `.astro` files

Svelte components behave like any import:

```html
---
import Counter from '../components/Counter.svelte';
---
<Counter initial={3} />                 <!-- server-rendered only -->
<Counter client:load initial={3} />     <!-- hydrated -->
```

Three rules to bank now, with details in Chapter 3: props passed to a hydrated component must be serializable; children and named slots reach the component as static HTML; and a `.svelte` file can never import an `.astro` file. When you need Astro-rendered markup inside a Svelte island, pass it from the `.astro` side as a slot.

## Key takeaways

- `src/pages` is the only required directory. `public/` is copied verbatim; everything you write belongs in `src/`. `.astro/` is generated and holds types.
- An `.astro` file is a frontmatter fence (async TypeScript, server only) plus an HTML template with JSX-like expressions, multiple roots allowed, standard kebab-case attributes.
- Attributes with `undefined`/`null`/`false` values are omitted; `data-x={true}` renders `"true"`; event-handler attributes on HTML elements do not work. Use a `<script>` or an island.
- Props use `Astro.props` with a `Props` interface; reuse `HTMLAttributes` and `ComponentProps` from `astro/types`.
- Slots: default and named, fallback content only when no matching content is passed, transfer with `name` plus `slot`, `Astro.slots.has()` and `render()` for advanced cases, `Astro.self` for recursion.
- `set:html` is unescaped and an XSS surface. `define:vars` on `<script>` implies `is:inline`. `is:raw` disables expression parsing.
- Layouts are ordinary components; head management is explicit through a layout plus a named `head` slot. Set `site` if you build absolute URLs.
- `import.meta.glob` replaces `Astro.glob()`: string-literal pattern starting with `./`, `../` or `/`; lazy by default, `eager: true` for immediate modules. Prefer content collections for content.
- Aliases come from `tsconfig.json` `paths`; Astro has no built-in `$lib`.
- Build and dev do not type-check. `astro check` handles `.astro` and `.ts` but not `.svelte`; add `svelte-check`. Use `import type` (`verbatimModuleSyntax`).
- The Rust compiler errors on unclosed tags (reported at the end of the file) and passes invalid HTML through unrepaired; diff `dist/` after upgrades.

## Review Questions

1.  Which directory is the only one Astro reserves, and which filenames are reserved in addition to it? Name at least four.

2.  When is a file in `public/` the right place and when is it the wrong place? Give one example of each.

3.  What does this render?

    ```html
    <p style={{ color: 'red' }} data-x={undefined} hidden={false} data-y={true}>z</p>
    ```

4.  A colleague writes `<button onclick={handleClick}>Add</button>` in an `.astro` file where `handleClick` is defined in the frontmatter. Why does clicking do nothing, and what are two correct approaches?

5.  Why can `data-active={false}` be a bug for CSS such as `[data-active="false"] { ... }`? How do you write it to get the string `"false"`?

6.  Given the layout below, what ends up in `<head>` for a page that passes `<meta slot="head" name="robots" content="noindex" />`? What is required in the intermediate layout for it to work through two levels of nesting?

    ```html
    <!-- Base.astro -->
    <head><title>{Astro.props.title}</title><slot name="head" /></head>
    ```

7.  Explain when slot fallback content is shown. What is the difference between “no content passed” and “an empty element passed”?

8.  Write a component `Callout.astro` that renders a `<footer>` containing the `footer` slot only when the caller provides one.

9.  What does `Astro.slots.render('default', [message])` return, and why does the example `<Shout>{(m: string) => <div>{m}</div>}</Shout>` work for Astro components but not for a hydrated Svelte component?

10. Why does `set:html={userComment}` constitute a vulnerability, and what are two mitigations?

11. Multiple choice. Which of these is true of `<script define:vars={{ id }}>`? (a) It is bundled and deduplicated; (b) it implies `is:inline`; (c) it is only allowed in layouts; (d) it passes `id` as a prop to the Svelte renderer.

12. Why is `define:vars` a poor choice for a component that appears 40 times on a page? What is the alternative that keeps a single bundled script?

13. What happens when a dynamic tag variable is lowercase (`const tag = 'h2'; <tag>x</tag>`)? Can you attach `client:load` to a capitalized dynamic component variable?

14. Find the bug:

    ```html
    ---
    const posts = import.meta.glob(`../content/${Astro.props.section}/*.md`);
    ---
    ```

15. What are the three things an `import.meta.glob` pattern must satisfy in Astro, and what replaced `Astro.glob()`?

16. Compare `import.meta.glob('./posts/*.md', { eager: true })` and `getCollection('posts')`. Name two capabilities that only the collection approach has.

17. Where are import aliases configured, and does a `$lib` alias exist by default in Astro as it does in SvelteKit?

18. Which of the following does `astro check` verify? (a) `.astro` frontmatter types; (b) `.ts` files; (c) the `<script lang="ts">` of `.svelte` files; (d) Svelte template expressions. Which tool covers the rest?

19. Write the `package.json` scripts that make `npm run build` fail on any type error in `.astro`, `.ts` or `.svelte` files.

20. Why does `verbatimModuleSyntax` matter in an Astro project? Give an example import that violates it.

21. The Rust compiler gives `[CompilerError] Unexpected token` at the last line of a file. Where should you look, and why is the reported line misleading?

22. Which of the following compile without error under Astro 7, and which of those produce HTML that differs from the template after the browser parses it? (a) `<p><div>x</div></p>`; (b) `<ul><li>a</ul>`; (c) `<table><div>x</div></table>`; (d) `<br>`.

23. Explain why `<Layout>` should not receive a `client:load` directive. What is the correct way to add interactivity in a layout?

24. Design: your site needs the same `<head>` metadata on 200 pages plus per-page extras (a preload link, JSON-LD). Sketch the layout and slot structure, and say where `Astro.site` must be configured.

25. What makes a page a partial, what is lost when a page is a partial, and what is the constraint on how `partial` is exported?

26. For which routes is `500.astro` used, what type is its `error` prop, and what should you avoid rendering from it?
