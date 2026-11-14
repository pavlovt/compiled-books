# Chapter 7: Markdown and MDX

Markdown is the default authoring format for content-heavy Astro sites, and MDX is its component-capable sibling. Astro 7 changed the plumbing under both: the default Markdown processor is now **Sätteri**, a Rust-based processor, and the old remark/rehype pipeline (**unified**) became an explicit opt-in. That single change touches heading ids, plugin APIs, MDX configuration, `render()` output and every project that depends on a remark or rehype plugin.

This chapter explains how Markdown reaches the page (collections, imports and `src/pages`), how the two processors are configured and where they differ in observable output, how heading ids and frontmatter work, how to highlight code with Shiki 4 or Prism, how MDX integrates components (and where client directives stop working), how to render Svelte inside MDX, and how to migrate a remark/rehype stack. Every behaviour that the docs left ambiguous was checked in a test project with `astro@7.4.1`, `@astrojs/mdx@8.1.0`, `@astrojs/markdown-satteri@0.4.4`, `@astrojs/markdown-remark@7.3.3` and `@astrojs/svelte@9.1.0`.

## Three ways Markdown becomes HTML

1.  **Content collections** (recommended). A `glob()` loader loads `.md`/`.mdx`; `render(entry)` returns `<Content />`, `headings` and `remarkPluginFrontmatter`. See Chapter 6.
2.  **Imports.** `import * as post from './post.md'` or `import.meta.glob('./posts/*.md', { eager: true })` gives you `file`, `url`, `frontmatter`, `<Content />`, `rawContent()`, `compiledContent()` and `getHeadings()`.
3.  **Pages.** Any `.md` or `.mdx` file inside `src/pages/` becomes a route, optionally wrapped by a layout declared in frontmatter.

Collections add schema validation, typed access and loader flexibility; imports are fine for a handful of files; pages are convenient but the docs call them a limited option.

```html
---
// src/pages/archive.astro: imports
const posts = Object.values(
  import.meta.glob<{ frontmatter: { title: string }; url: string }>('./posts/*.md', { eager: true }),
);
const first = await import('./posts/great-post.md');
const html = await first.compiledContent();
---
<ul>{posts.map((p) => <li><a href={p.url}>{p.frontmatter.title}</a></li>)}</ul>
<Fragment set:html={html} />
```

`getHeadings()` returns `{ depth: number; slug: string; text: string }[]`. For MDX, headings from imported MDX files are not included.

### Markdown pages and the `layout` frontmatter property

A file at `src/pages/page-1.md` creates `/page-1/`. A special `layout` frontmatter key points to an Astro layout; the layout receives `Astro.props.frontmatter`, `headings`, `file`, `url` and the rendered content in its default slot:

```markdown
---
layout: ../../layouts/PostLayout.astro
title: Astro in brief
---
This is a post written in Markdown.
```

```html
---
// src/layouts/PostLayout.astro
const { frontmatter } = Astro.props;
---
<html lang="en">
  <head><meta charset="utf-8" /><title>{frontmatter.title}</title></head>
  <body><h1>{frontmatter.title}</h1><slot /></body>
</html>
```

When using this property you must include `<meta charset="utf-8">` yourself; Astro no longer adds it. The docs also state that `layout` is not special in collections and “is not guaranteed to be supported outside of its intended use case”. For collection entries, build the layout in your `[...slug].astro` page instead.

## Processors: Sätteri and unified

A **Markdown processor** parses Markdown and emits HTML. Since Astro 6.4 you can choose one; since Astro 7 the default is Sätteri, with no installation required. Both official processors provide the same built-in features: GitHub-Flavored Markdown (tables, task lists, strikethrough, footnotes, autolinks) and smart punctuation.

|  | Sätteri | unified |
|------------------------|------------------------|------------------------|
| Package | `@astrojs/markdown-satteri` (optional) | `@astrojs/markdown-remark` (opt-in) |
| Factory | `satteri(options)` | `unified(options)` |
| Implementation | Rust-based Markdown and MDX compiler | remark + rehype (JS) |
| Plugin model | mdast plugins, hast plugins (Sätteri’s own API) | remark plugins, rehype plugins, recma plugins (MDX only) |
| Ecosystem | Young; write your own or use `satteri-*` packages | Very large |
| Default in 7.x | Yes | No |

> **Note:** Sätteri works with no configuration. Install `@astrojs/markdown-satteri` only to configure its features or add plugins. `unified` is *not* bundled: install `@astrojs/markdown-remark` to use it.

### Selecting and configuring a processor

```js
// astro.config.mjs
import { defineConfig } from 'astro/config';
import { satteri } from '@astrojs/markdown-satteri';

export default defineConfig({
  markdown: {
    processor: satteri({
      features: {
        gfm: { footnotes: { label: 'Notes', backLabel: 'Back to reference {reference}' } },
        smartPunctuation: { quotes: true, dashes: false, ellipses: false },
      },
    }),
  },
});
```

```js
// astro.config.mjs: unified, the Astro 5 behavior
import { unified } from '@astrojs/markdown-remark';
import remarkToc from 'remark-toc';

export default defineConfig({
  markdown: {
    processor: unified({
      remarkPlugins: [[remarkToc, { heading: 'contents' }]],
      rehypePlugins: [],
      remarkRehype: { footnoteLabel: 'Notes' },
      gfm: true,
      smartypants: { quotes: true, dashes: false, ellipses: false },
    }),
  },
});
```

The option names are not symmetric, which causes real mistakes:

| Concern | Sätteri | unified |
|------------------------|------------------------|------------------------|
| Disable GFM | `features: { gfm: false }` | `gfm: false` |
| Disable smart punctuation | `features: { smartPunctuation: false }` | `smartypants: false` |
| Footnote text | `features.gfm.footnotes` | `remarkRehype: { footnoteLabel, ... }` |
| Tree plugins | `mdastPlugins`, `hastPlugins` | `remarkPlugins`, `rehypePlugins` |
| ESTree plugins (MDX) | not available | `recmaPlugins` |

**Doc discrepancy, resolved by test.** The Sätteri API reference page shows a top-level `satteri({ smartPunctuation: false })` example, but the Markdown guide and the package’s type definitions (`SatteriMarkdownProcessorOptions` has `mdastPlugins`, `hastPlugins` and `features`) use `features: { smartPunctuation: ... }`. I built with `satteri({ features: { smartPunctuation: false } })` and verified that straight quotes and `--` were left untouched in `.md` output. Use the `features` form.

The older `markdown.gfm`, `markdown.smartypants`, `markdown.remarkPlugins`, `markdown.rehypePlugins` and `markdown.remarkRehype` options are deprecated in favor of processor options. They still function but need `@astrojs/markdown-remark` installed.

### The processors are not byte-identical

Both produce the same *semantics* but differ in serialization and edge cases. I rendered the same sample through `createSatteriMarkdownProcessor()` and `createMarkdownProcessor()` (the standalone renderers exported by each package, which are handy for exactly this kind of comparison):

```js
// diff.mjs
import { createSatteriMarkdownProcessor } from '@astrojs/markdown-satteri';
import { createMarkdownProcessor } from '@astrojs/markdown-remark';

const md = '## What\'s `<Picture />`?\n\n"Quoted" -- text...\n';
const s = await (await createSatteriMarkdownProcessor()).render(md);
const u = await (await createMarkdownProcessor()).render(md);
console.log(s.code, u.code);
```

Observed differences, all on Astro 7.4.1 packages:

| Input | Sätteri | unified |
|------------------------|------------------------|------------------------|
| `--` with smart punctuation | `–` (en dash) | `—` (em dash) |
| `` `<Picture />` `` inside `<code>` | `&lt;Picture /&gt;` | `&#x3C;Picture />` |
| Inter-element whitespace around tables | Newlines between rows and cells | Table on one line, with blank-line padding after paragraphs |
| Boolean attributes | `data-footnote-ref` | `data-footnote-ref=""` |

These are cosmetic for browsers but not for snapshot tests, content hashes, RSS bodies or anything that parses the HTML as text. Headings, `id` values, table structure, footnote anchors and code highlighting markup matched. If you have golden-file tests over rendered Markdown, regenerate them after switching processors, and prefer DOM-level assertions in new tests.

> **Warning:** A different dash character is a visible content change on every post that used `--`. If typographic fidelity matters, set the smart-punctuation option explicitly rather than depending on the default of whichever processor you are using.

### Mixing processors: `.md` versus `.mdx`

The MDX integration inherits your `markdown` config by default, but accepts its own `processor`, independent of `markdown.processor`. You can keep Sätteri for `.md` and render `.mdx` with remark/rehype:

```js
import mdx from '@astrojs/mdx';
import { unified } from '@astrojs/markdown-remark';

export default defineConfig({
  integrations: [mdx({ processor: unified({ recmaPlugins: [myRecmaPlugin] }) })],
});
```

I verified a config with `markdown.processor: satteri({ features: { smartPunctuation: false } })` and `mdx({ processor: unified() })`: the `.md` file kept straight quotes while the `.mdx` file’s heading came out as `Hello “world” — it’s…` (unified’s em dash and curly quotes). That is both a feature, since you can migrate incrementally, and a trap, since the two content types now differ.

`recmaPlugins` are only meaningful with `unified()` and only affect MDX. The older top-level `recmaPlugins` option on `mdx()` is deprecated; pass them to `unified({ recmaPlugins })` instead. `extendMarkdownConfig` (default `true`) controls inheritance: when `false`, MDX ignores the `markdown` block entirely and uses the default processor. `optimize` (default `false`) turns on an internal rehype plugin that pre-renders static MDX output to strings for faster builds; it can break components passed through the `components` prop unless excluded with `optimize: { ignoreElementNames: ['h1'] }`. Components exported from the MDX file’s own `export const components` are detected automatically.

## Frontmatter

YAML (and TOML) frontmatter at the top of a Markdown or MDX file is parsed into an object. Where it surfaces depends on the access path:

| Access path      | Where frontmatter lives                       |
|------------------|-----------------------------------------------|
| Collection entry | `entry.data` (validated by schema)            |
| `render(entry)`  | `remarkPluginFrontmatter` (after plugins ran) |
| Import / glob    | `frontmatter` export                          |
| Layout prop      | `Astro.props.frontmatter`                     |
| Inside MDX body  | `{frontmatter.title}`                         |

### Computed frontmatter via plugins

Both processors let a plugin add to a `data.astro.frontmatter` object, which then appears in `remarkPluginFrontmatter`, in imports and layouts. A unified plugin:

```js
// src/plugins/reading-time.mjs
export function remarkReadingTime() {
  return function (tree, file) {
    // `tree` is the mdast root; derive text however you like
    file.data.astro.frontmatter.minutes = 7;
  };
}
```

and the equivalent for Sätteri, following the docs’ API:

```ts
// src/plugins/example-mdast-plugin.ts
import { defineMdastPlugin } from 'satteri';

export const exampleMdastPlugin = defineMdastPlugin({
  name: 'example-mdast-plugin',
  text(node, ctx) {
    if (ctx.data.astro !== undefined) {
      ctx.data.astro.frontmatter.computed = `${ctx.data.astro.frontmatter.title} | My Site`;
    }
  },
});
```

Registered with `satteri({ mdastPlugins: [exampleMdastPlugin()] })`. Note the shape: Sätteri plugins are objects with node visitors (`text`, `heading`, …) receiving `(node, ctx)`, not the unified `(tree, file) => void` transformer, so remark plugins cannot be dropped in. `ctx.data.astro` has type `SatteriAstroData`: `{ frontmatter, headings, localImagePaths, remoteImagePaths }`.

I verified the unified variant end to end: with the plugin above, `render(entry)` returned `remarkPluginFrontmatter` equal to the entry’s own frontmatter plus `minutes: 7`, and the schema-validated `entry.data` did **not** contain `minutes`. Plugin-injected values live only on `remarkPluginFrontmatter`, so a schema cannot validate them.

## Heading ids

Astro injects an `id` on every `h1` to `h6` in Markdown and MDX, using `github-slugger`, and returns the list of `{ depth, slug, text }` via `headings`, `getHeadings()` or `render()`.

Astro 6 made GitHub-compatible ids the default (the former `experimental.headingIdCompat` flag was removed). The consequence is that trailing hyphens from headings ending in punctuation are preserved:

```markdown
## What's `<Picture />`?
```

renders (verified with both processors) as `<h2 id="whats-picture-">`, and a link to it must be `#whats-picture-`. Also note the slug is computed from the raw heading text, while `text` in `headings` reflects smart punctuation: for `Hello "world" -- it's...` I observed `slug: "hello-world--its"` and `text: "Hello “world” – it’s…"`. If you built anchors by hand-slugifying heading text with your own function, expect mismatches.

Plugin ordering is the subtle part. Astro injects ids *after* your custom plugins, so an id set by a plugin such as `rehype-slug` wins and is what `headings` reports. If your plugin needs to read Astro’s ids, include Astro’s id plugin before it:

```js
import { satteri, satteriHeadingIdsPlugin } from '@astrojs/markdown-satteri';

processor: satteri({ hastPlugins: [satteriHeadingIdsPlugin(), pluginThatReadsIds] });
```

```js
import { unified, rehypeHeadingIds } from '@astrojs/markdown-remark';

processor: unified({ rehypePlugins: [rehypeHeadingIds, pluginThatReadsIds] });
```

To keep Astro 5’s trailing-hyphen stripping, the upgrade guide suggests writing your own plugin; there is no flag for it any more.

## Syntax highlighting

Astro highlights fenced code blocks and the `<Code />` component with **Shiki 4** by default (theme `github-dark`), outputting inline styles with no client JS or stylesheet. **Prism** is the alternative, which emits CSS classes and requires you to supply a stylesheet.

```js
export default defineConfig({
  markdown: {
    syntaxHighlight: { type: 'shiki', excludeLangs: ['math', 'mermaid'] },
    shikiConfig: {
      themes: { light: 'github-light', dark: 'github-dark' },
      wrap: true,
      // transformers: [...], langs: [...], langAlias: { svelte5: 'svelte' }
    },
  },
});
```

- `syntaxHighlight` accepts `'shiki'`, `'prism'`, `false`, or `{ type, excludeLangs }`. The default is `{ type: 'shiki', excludeLangs: ['math'] }`. Fences whose language is in `excludeLangs` are left unhighlighted, which is how you keep client-side renderers such as Mermaid or KaTeX in control of those blocks. I verified `excludeLangs: ['math', 'ts']` produced a bare `<pre>` for a `ts` fence while other languages were highlighted.
- Setting `syntaxHighlight: 'prism'` makes class-based markup: you add a stylesheet from Prism themes to `public/` and link it in the layout.
- For dual themes, Shiki emits CSS variables (`--shiki-dark`, `--shiki-dark-bg`). Astro’s blocks use the class `astro-code`, so Shiki’s documented dark-mode CSS must be adapted:

```css
@media (prefers-color-scheme: dark) {
  .astro-code, .astro-code span {
    color: var(--shiki-dark) !important;
    background-color: var(--shiki-dark-bg) !important;
  }
}
```

With the `css-variables` theme, variables are prefixed `--astro-code-` rather than `--shiki-`.

The verified default output for ```` ```ts ```` is `<pre class="astro-code github-dark" style="background-color:#24292e;color:#e1e4e8;overflow-x:auto" tabindex="0" data-language="ts">` with per-token `<span style="color:...">`.

### `<Code />` and `<Prism />`

`<Code />` from `astro:components` works in `.astro` and `.mdx`, **does not inherit** `shikiConfig`, and takes its own `theme`, `lang`, `embeddedLangs`, `transformers`, `defaultColor`, `wrap`, `inline` and `meta` props. A `lang="svelte"` already includes embedded TypeScript support; use `embeddedLangs` for unusual combinations. `<Prism />` comes from `@astrojs/prism`, takes `lang` and `code`, and also supports `lang="astro"`.

```html
---
import { Code } from 'astro:components';
const source = `<script lang="ts">\n  let n = $state(0);\n</script>\n<button onclick={() => n++}>{n}</button>`;
---
<Code code={source} lang="svelte" theme="github-dark" wrap />
```

> **Warning:** Shiki’s inline styles are incompatible with Astro’s CSP support (Chapter 16): the docs list Shiki as unsupported under `security.csp`, so a CSP-enabled site should use Prism with an external stylesheet.

Transformers (from `@shikijs/transformers`) only add classes; you must provide CSS for them. For richer annotations (diff, titles, line markers), the docs point to community integrations such as Expressive Code.

## MDX

`@astrojs/mdx` (8.x for Astro 7) adds `.mdx` support: `import`/`export` statements, JSX expressions and components inside Markdown. Install with `npx astro add mdx` or manually: `integrations: [mdx()]`. MDX files use MDX syntax, **not** Astro’s HTML-like template syntax: `{expression}` is JavaScript, `<br>` must be `<br />`, and comments are `{/* */}`.

### Exports, frontmatter and imports

```markdown
---
title: One
date: 2026-01-01
---
import Callout from '../../components/Callout.astro';
export const readingMinutes = 4;

# {frontmatter.title}

Read time: {readingMinutes} min

<Callout kind="tip">Components work in MDX.</Callout>
```

When imported, an MDX module exposes `file`, `url`, `frontmatter`, `getHeadings()`, `<Content />` and any `export`ed value (so `post.readingMinutes` above). In a **collection**, the documented surface is `render()`’s `Content`, `headings` and `remarkPluginFrontmatter`; arbitrary MDX exports are not part of the documented entry shape, so do not rely on them there. Put values you need as data into frontmatter and the schema.

### The `components` prop

MDX lets you map HTML elements to components in two ways:

1.  Inside the file: `export const components = { blockquote: Blockquote }`. Note that the exported object takes effect only when rendered through `<Content components={...}>` with the module’s own `components` spread in, as the docs state; they must “always be imported and then passed back to the `<Content />` component via the `components` property”.
2.  At render time:

```html
---
import { getEntry, render } from 'astro:content';
import Heading from '../../components/Heading.astro';

const entry = await getEntry('posts', 'one');
const { Content } = await render(entry!);
---
<Content components={{ h1: Heading, a: SmartLink }} />
```

For a directly imported file, import both pieces: `import { Content, components } from '../post.mdx'` and spread `{...components, h1: Heading}`.

An element-mapping component must render a `<slot />` for children and forward its props:

```html
---
// src/components/Blockquote.astro
const props = Astro.props;
---
<blockquote {...props} class="callout"><slot /></blockquote>
```

### Where client directives stop working

This is the sharpest edge in the MDX story, and it is a direct consequence of how hydration works (Chapter 3): client directives are applied by the compiler to components imported directly in a template. Components supplied through the `components` prop are resolved at render time, dynamically, so:

- `<Counter client:load />` written **in the MDX source**, with `Counter` imported in that same file, **works**. In my test the output contained an `astro-island` with `component-url`, `renderer-url` pointing at the Svelte client entry, and props `{"start":[0,3]}`.
- A Svelte component mapped in `components={{ h2: Counter }}` renders **statically**: it never hydrates, receives none of the MDX element’s children, and cannot take `client:*`. I verified the output was only the server-rendered `<button>n=0</button>`, and the heading text was dropped because the Svelte component ignores children.
- Hydrating an `.astro` component with `client:*` is an error in any context.

The practical rule: use `components` to swap *HTML elements* for **Astro** components (static, slot-based); put interactive Svelte islands directly in the MDX source with explicit directives.

### Svelte components inside MDX

Svelte 5 rune components behave exactly as they do in `.astro`: imported, given a directive, with serializable props.

```html
<!-- src/components/Poll.svelte -->
<script lang="ts">
  let { question, options }: { question: string; options: string[] } = $props();
  let votes = $state<Record<string, number>>(Object.fromEntries(options.map((o) => [o, 0])));
  const total = $derived(Object.values(votes).reduce((a, b) => a + b, 0));
</script>

<fieldset>
  <legend>{question}</legend>
  {#each options as o}
    <button onclick={() => votes[o]++}>{o} ({votes[o]})</button>
  {/each}
  <p>{total} votes</p>
</fieldset>
```

```markdown
---
title: Opinion
date: 2026-03-01
---
import Poll from '../../components/Poll.svelte';

## What do you think?

<Poll client:visible question="Runes or stores?" options={['Runes', 'Stores']} />
```

MDX children passed to a framework component arrive as static HTML strings via Astro’s slot mechanism; Chapter 3 covers how Svelte consumes them. Remember that the island is a sibling in the rendered prose: styles from your article layout apply to its DOM, but Svelte’s scoped styles apply only inside it.

### MDX in collections

`glob({ pattern: '**/*.{md,mdx}' })` loads both. `retainBody: false` dramatically shrinks the store for MDX: MDX entries store no pre-rendered HTML, so the raw body is most of what they occupy, and rendering does not need it, because MDX is compiled from the source file when `render()` runs (like `deferRender`). If the MDX integration is missing, the loader warns `No entry type found for <file>.mdx` and skips the file rather than failing.

MDX is never available from live collections, since it cannot be compiled at request time.

## Rendering Markdown from loaders and remote sources

- A **custom build-time loader** gets `renderMarkdown()`, which uses the configured processor. Assign the result to `entry.rendered`. See Chapter 6.
- A **live loader** may return `rendered: { html }`, already HTML.
- **Directly fetched** Markdown in frontmatter does *not* pass through Astro’s processor and inherits none of your settings. You must bring a parser such as `marked`. The docs advise a collection loader instead.
- For a standalone render outside the build pipeline (a CLI, a test), use `createSatteriMarkdownProcessor()` or `createMarkdownProcessor()` and call `.render(content, { fileURL, frontmatter })`, which returns `{ code, metadata: { headings, localImagePaths, remoteImagePaths, frontmatter } }`.

## Styling rendered Markdown

Rendered Markdown has no Astro scope attribute, so component-scoped `<style>` does not reach it. Use `:global()` inside a wrapper or `is:global` in the layout:

```html
<article class="prose"><Content /></article>

<style>
  .prose :global(h2) { margin-block: 2rem 0.5rem; }
  .prose :global(pre) { border-radius: 8px; }
</style>
```

## Migrating a remark/rehype stack to Astro 7

Astro 7 makes this a deliberate choice rather than something that silently happens:

1.  **Do nothing clever first.** To preserve Astro 6 behaviour exactly, install `@astrojs/markdown-remark` and set `markdown.processor: unified({...})`, moving the contents of `markdown.remarkPlugins`, `rehypePlugins`, `remarkRehype`, `gfm` and `smartypants` into the factory options. Do the same in `mdx({ processor })` if you configured MDX separately.
2.  **Move `recmaPlugins`** into `unified({ recmaPlugins })` (the standalone MDX option is deprecated).
3.  **Rebuild and diff.** Even with the same plugins you may see serialization differences from the rendering pipeline; run your snapshot tests.
4.  **Port plugins one at a time.** Classify each: (a) cosmetic or trivial (heading anchors, external-link attributes, image attributes), which are usually replaceable by a small Sätteri plugin or a `satteri-*` package; (b) structural (table of contents, admonitions), where you check the Sätteri ecosystem first; (c) ecosystem-specific (math, directives), where you may stay on unified.
5.  **Switch per content type.** Because `mdx({ processor })` is independent of `markdown.processor`, you can move `.md` first (usually simpler) and `.mdx` later, or the reverse.
6.  **Check anchors.** If you use Astro 5 heading ids with stripped trailing hyphens, links such as `#picture` now need `#picture-` (Astro 6 change; unaffected by the processor choice).
7.  **Pin and test visual typography.** Smart punctuation differences (`--`) are content-visible.

A small decision table:

| Situation | Choice |
|------------------------------------|------------------------------------|
| No plugins, build speed matters | Sätteri (default) |
| A few simple custom transforms | Sätteri with your own mdast/hast plugins |
| Heavy use of remark-math, remark-directive, rehype-pretty-code, etc. | `unified()` |
| MDX that needs recma plugins | `mdx({ processor: unified({ recmaPlugins }) })` |
| Mixed: fast `.md`, flexible `.mdx` | Sätteri for `markdown.processor`, `unified` in `mdx()` |

## A complete worked example

Collection, schema, page and island together:

```ts
// src/content.config.ts
import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

export const collections = {
  articles: defineCollection({
    loader: glob({ pattern: '**/*.{md,mdx}', base: './src/content/articles' }),
    schema: z.object({
      title: z.string(),
      date: z.coerce.date(),
      toc: z.boolean().default(true),
    }),
  }),
};
```

```html
---
// src/pages/articles/[...id].astro
import { getCollection, render } from 'astro:content';
import Toc from '../../components/Toc.svelte';
import Heading from '../../components/Heading.astro';

export async function getStaticPaths() {
  return (await getCollection('articles')).map((entry) => ({
    params: { id: entry.id },
    props: { entry },
  }));
}

const { entry } = Astro.props;
const { Content, headings } = await render(entry);
const toc = headings.filter((h) => h.depth === 2 || h.depth === 3);
---
<article>
  <h1>{entry.data.title}</h1>
  {entry.data.toc && <Toc client:idle items={toc} />}
  <Content components={{ h2: Heading }} />
</article>
```

```html
<!-- src/components/Toc.svelte -->
<script lang="ts">
  import { onMount } from 'svelte';
  let { items }: { items: { depth: number; slug: string; text: string }[] } = $props();
  let active = $state('');

  onMount(() => {
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) active = e.target.id;
      },
      { rootMargin: '0px 0px -70% 0px' },
    );
    for (const { slug } of items) {
      const el = document.getElementById(slug);
      if (el) io.observe(el);
    }
    return () => io.disconnect();
  });
</script>

<nav aria-label="Table of contents">
  <ul>
    {#each items as item (item.slug)}
      <li style:margin-inline-start="{(item.depth - 2) * 1}rem">
        <a href="#{item.slug}" aria-current={active === item.slug ? 'true' : undefined}>{item.text}</a>
      </li>
    {/each}
  </ul>
</nav>
```

```html
---
// src/components/Heading.astro: replaces <h2> in rendered content
const props = Astro.props;
---
<h2 {...props}><slot /> <a class="anchor" href={`#${props.id}`} aria-hidden="true">#</a></h2>
```

The island receives only `{ depth, slug, text }` objects. The `Content` component, which is not serializable, stays in the Astro template. The `id` on each heading comes from Astro’s id plugin, so the observer finds them.

## Key takeaways

- Markdown arrives via collections (preferred), imports (`frontmatter`, `Content`, `getHeadings()`, `compiledContent()`) or `src/pages`. In collections, use `render(entry)` for `Content`, `headings` and `remarkPluginFrontmatter`.
- Astro 7’s default processor is Sätteri (Rust, no install); `unified()` from `@astrojs/markdown-remark` is opt-in. Select via `markdown.processor`; MDX has its own independent `mdx({ processor })`.
- Option names differ: Sätteri uses `features: { gfm, smartPunctuation }`, `mdastPlugins`, `hastPlugins`; unified uses `gfm`, `smartypants`, `remarkPlugins`, `rehypePlugins`, `remarkRehype`, `recmaPlugins`. The Sätteri reference page’s top-level `smartPunctuation` example is wrong; `features` is the typed and working form.
- The processors differ in output serialization and typography (`--` becomes an en dash in Sätteri, an em dash in unified); regenerate snapshots after switching.
- Heading ids use github-slugger with GitHub-compatible trailing hyphens since Astro 6; custom id plugins win over Astro’s ids, and Astro’s id plugin must be placed before plugins that read ids.
- Plugin-added frontmatter lives in `remarkPluginFrontmatter`, not in schema-validated `entry.data`.
- Shiki 4 is the default highlighter (`astro-code` class, inline styles); Prism needs a stylesheet; `excludeLangs` bypasses highlighting; `<Code />` does not inherit `shikiConfig`; Shiki is incompatible with Astro CSP.
- In MDX, a client directive works on components imported in the MDX source; components passed through the `components` prop are rendered statically and cannot hydrate. Use `components` to replace elements with Astro components.
- `recmaPlugins` need `unified()`. `mdx({ optimize })` can break dynamically mapped components unless you list them in `ignoreElementNames`.
- Migration path: opt into `unified()` to preserve behaviour, move `recmaPlugins`, diff output, then port plugins to Sätteri incrementally per content type.

## Review Questions

1.  Which processor is the default in Astro 7, and which package must you install to use the other one?

2.  Rewrite this Astro 6 config for Astro 7 with unified, preserving behaviour:

    ```js
    export default defineConfig({
      markdown: { remarkPlugins: [remarkToc], smartypants: false },
    });
    ```

3.  What is the Sätteri equivalent of `smartypants: false` and `gfm: false`?

4.  A Sätteri reference example shows `satteri({ smartPunctuation: false })`. Is that the form that type definitions and the guide use? What should you write?

5.  After switching from unified to Sätteri a teammate’s snapshot tests of rendered Markdown fail although the pages look identical. Give two causes.

6.  `Hello -- world` is rendered with smart punctuation by both processors. What difference might readers see?

7.  What `id` does the heading `## What's <Picture />?` (with the component name in backticks) receive in Astro 6+/7, and what changed from Astro 5?

8.  A plugin sets `id` attributes on headings. Whose ids does `headings` report, and why?

9.  You add a rehype plugin that must read Astro’s generated heading ids. Where must Astro’s heading-id plugin appear in the list?

10. A remark plugin adds `minutes` to `file.data.astro.frontmatter`. Where can your page read it for a collection entry, and why will a Zod schema not validate it?

11. Why can’t a unified remark plugin be pasted into `satteri({ mdastPlugins })`?

12. List three values valid for `markdown.syntaxHighlight` and what `excludeLangs` does.

13. Multiple choice: Which statement about `<Code />` is correct? (a) It inherits `markdown.shikiConfig`. (b) It takes its own `theme` and `lang` props and ignores `shikiConfig`. (c) It requires `@astrojs/prism`. (d) It only works in `.md` files.

14. Your dual-theme Shiki config emits `--shiki-dark` variables but the dark colors never apply. What selector must you target in your CSS?

15. Why would a CSP-enabled site avoid Shiki?

16. What does this MDX do?

    ```markdown
    import Counter from '../components/Counter.svelte';

    <Counter client:load start={3} />
    ```

    (a) Errors because Svelte is unsupported in MDX; (b) renders and hydrates an island; (c) renders statically without hydration; (d) requires `export const components`.

17. What is the output of mapping a Svelte component with `<Content components={{ h2: Counter }} />`? Can you put `client:load` on it?

18. Fix the bug: an `Astro` component `Blockquote.astro` assigned in MDX renders blockquotes without their text.

19. Which MDX options belong to `unified()` rather than the MDX integration in Astro 7, and why?

20. What does `extendMarkdownConfig: false` do?

21. Explain `mdx({ optimize: true })` and when it breaks `components` overrides.

22. Why can `.mdx` files in a `glob()` collection be silently skipped, and what warning tells you?

23. In a collection, can you read an MDX file’s `export const readingMinutes` from the entry? What about via import?

24. You need Mermaid fences to render client-side. Which config keeps Shiki off them?

25. What do `compiledContent()`, `rawContent()` and `getHeadings()` return on an imported Markdown file?

26. A Markdown file lives in `src/pages/` with frontmatter `layout: ../layouts/Post.astro` but the page lacks a charset. Why?

27. Design: a site has 600 posts, uses `remark-math`, `rehype-katex` and two small custom remark plugins. Propose a migration plan to Astro 7 that minimizes risk.

28. Design: you want an interactive poll inside long-form articles authored in MDX, and heading anchors with a copy-link button on every `h2`. Which pieces use `client:*` directives and which use the `components` prop, and why?
