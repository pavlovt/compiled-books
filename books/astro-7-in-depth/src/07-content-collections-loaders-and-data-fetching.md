# Chapter 6: Content Collections, Loaders and Data Fetching

Every non-trivial Astro site has a data problem before it has a UI problem: where does content live, how is it validated, when is it fetched, and how does it reach the page and, eventually, a Svelte island? Content collections are Astro’s answer. They give you a typed, queryable, cacheable layer between “some source of structured data” and your templates, and since Astro 6 that layer has two halves: **build-time collections** that sync into a persistent data store, and **live collections** that fetch on every request.

This chapter covers both halves in depth: the `glob()` and `file()` loaders, inline and object loaders (with the `DataStore`, `meta`, digests and `renderMarkdown()`), Zod 4 schemas, `reference()` and the image schema, the query and render APIs, the experimental storage and incremental-build flags, live collections with cache hints and error handling, plain `fetch()` in frontmatter, and a decision framework for choosing between loaders, live collections, endpoints and client-side fetching. We close with secrets handling through `astro:env`, CMS patterns and the `legacy.collectionsBackwardsCompat` escape hatch.

Everything in this chapter was checked against the 7.4 docs and, where the docs were silent or inconsistent, against a test project built with `astro@7.4.1`, `@astrojs/svelte@9.1.0`, `svelte@5.57.2`, `@astrojs/node` and `@astrojs/mdx` 8.1. Verified behaviours are marked as such.

## The mental model: a content layer with two halves

A *collection* is a set of structurally identical entries. An *entry* has an `id`, a `data` object validated by an optional Zod schema, and optionally a raw `body`, pre-rendered HTML in `rendered`, a `filePath` and a `digest`.

|  | Build-time collection | Live collection |
|------------------------|------------------------|------------------------|
| Config file | `src/content.config.ts` | `src/live.config.ts` |
| Define with | `defineCollection()` | `defineLiveCollection()` |
| Loader contract | `load(context)` writes to a `DataStore` | `loadCollection()` / `loadEntry()` return data |
| Query with | `getCollection()` / `getEntry()` / `getEntries()` | `getLiveCollection()` / `getLiveEntry()` |
| Runs | During `astro build` / dev sync | On every request |
| Persisted | Yes (data store, reused across builds) | No |
| Return shape | Entries, or `undefined` | `{ entry \| entries, error, cacheHint }` |
| MDX and image optimization | Supported | Not supported |
| Needs an adapter | No (static output works) | Yes |

Both can coexist in one project, and the docs’ own example is the split you will use in practice: product descriptions in a build-time collection, stock levels in a live one. Chapter 20 builds exactly that.

> **Senior tip:** The two APIs are deliberately *not* interchangeable. `getLiveCollection()` returns a result object you must check for `error`, while `getCollection()` throws or returns arrays. That asymmetry is the type system telling you which collection is network-bound and can fail per request.

## Defining build-time collections

All build-time collections live in `src/content.config.ts` (`.js` and `.mjs` also work) as a single exported `collections` object. Each collection needs a `loader` and, optionally but strongly recommended, a `schema`.

```ts
// src/content.config.ts
import { defineCollection, reference } from 'astro:content';
import { glob, file } from 'astro/loaders';
import { z } from 'astro/zod';

const posts = defineCollection({
  loader: glob({ pattern: '**/*.{md,mdx}', base: './src/content/posts' }),
  schema: ({ image }) =>
    z.object({
      title: z.string(),
      date: z.coerce.date(),
      cover: image().optional(),
      author: reference('authors'),
      related: z.array(reference('posts')).default([]),
      draft: z.boolean().default(false),
    }),
});

const authors = defineCollection({
  loader: file('./src/content/authors.json'),
  schema: z.object({ name: z.string(), url: z.url().optional() }),
});

export const collections = { posts, authors };
```

Three details deserve attention.

1.  `z` comes from `astro/zod`. Importing `z` from `astro:content` or `astro:schema` still works in 7.4 but is deprecated. `astro/zod` re-exports Zod 4.
2.  The `schema` may be a function receiving a `SchemaContext`, whose only member is the `image()` helper. You need the function form when the schema contains images; otherwise a plain Zod object is fine.
3.  The key in `collections` is the collection name used by every query function and by the generated `CollectionKey` union.

### The `glob()` loader

`glob()` creates one entry per matching file and understands Markdown, MDX, Markdoc, JSON, YAML and TOML. Options:

| Option | Meaning |
|------------------------------------|------------------------------------|
| `pattern` | `string \| string[]`, micromatch syntax, relative to `base` |
| `base` | Directory (`string \| URL`), default `"."` |
| `generateId({ entry, base, data })` | Custom id function. Default: `github-slugger` kebab-case of the file path |
| `retainBody` | Default `true`. `false` drops `entry.body` from the store (5.17+), shrinking it dramatically for MDX |
| `deferRender` | Default `false` (7.1+). Defer Markdown rendering until a page renders the entry |

IDs deserve care. The default generator slugifies, so `Hello World.md` becomes `hello-world`, and uppercase is lost. A `slug` property in frontmatter (or in a JSON entry) overrides the id and may contain slashes, in which case the route that consumes it must use a rest parameter (`[...id].astro`). When migrating from a path-based id scheme, use `generateId`:

```ts
const authors = defineCollection({
  loader: glob({
    pattern: '**/*.json',
    base: './src/data/authors',
    generateId: ({ entry }) => entry.replace(/\.json$/, ''), // keep case, keep path
  }),
});
```

A warning that bit me during verification: if your pattern matches `.mdx` files and the MDX integration is not installed, the loader logs `[WARN] [glob-loader] No entry type found for one.mdx` and silently produces no entry for that file. Pattern breadth is not a substitute for installing the integration.

### The `file()` loader

`file()` reads a single file containing either an array of objects with an `id` field, or an object keyed by id. JSON, YAML and TOML are built in. It does *not* generate ids; every entry needs one.

```ts
const dogs = defineCollection({ loader: file('src/data/dogs.json') });

// Other formats and nested documents go through `parser`:
const cats = defineCollection({
  loader: file('src/data/cats.csv', {
    parser: (text) => parseCsv(text, { columns: true, skipEmptyLines: true }),
  }),
});

// One file, several collections:
const pets = (key: 'dogs' | 'cats') =>
  file('src/data/pets.json', { parser: (text) => JSON.parse(text)[key] });
```

`parser` may be async and must return an array of `{ id, ... }` objects or a record of id to object.

### Inline loaders: a function that returns entries

For simple remote data, the loader can be a plain async function. Astro clears the collection and reloads everything on every sync:

```ts
const countries = defineCollection({
  loader: async () => {
    const res = await fetch('https://restcountries.com/v3.1/all');
    const data = await res.json();
    return data.map((c: any) => ({ id: c.cca3, ...c }));
  },
  schema: z.object({ name: z.object({ common: z.string() }) }),
});
```

The function can return an array (each element with a unique `id`) or an object whose keys are ids. This is the cheapest loader to write and the most expensive to run on large sources, because it has no incremental story: every build refetches everything. Reach for the object form when the source is big or slow.

## Zod 4 schemas

Astro 6 moved to Zod 4, and `astro/zod` is the only import path you should use. The behaviour changes that matter in schemas:

- Top-level string formats: `z.email()`, `z.url()`, `z.uuid()` instead of `z.string().email()`.
- Error customization uses `{ error: '...' }` rather than `{ message: '...' }`.
- `.default()` must match the *output* type, so `z.string().transform(Number).default('1')` no longer typechecks; use `.prefault()` to supply a pre-parse value.
- `z.coerce.date()` remains the idiom for frontmatter dates, because YAML dates arrive as strings or `Date` depending on syntax.

```ts
const events = defineCollection({
  loader: glob({ pattern: '*.yaml', base: './src/events' }),
  schema: z.object({
    title: z.string().min(3, { error: 'Title too short' }),
    contact: z.email(),
    starts: z.coerce.date(),
    capacity: z.number().int().positive().default(50),
    tags: z.array(z.string()).prefault([]),
  }),
});
```

All Zod methods (`.transform()`, `.refine()`, `.pipe()`) work, with one documented exception: `image().refine()` is unsupported.

### The `image()` helper

Inside the function-form schema, `image()` validates that a frontmatter string points at a local image and replaces it with an `ImageMetadata` object (src, width, height, format) that you can hand to `<Image>`. Paths are resolved relative to the entry’s `filePath`. For entries written into the store by a custom loader without a `filePath`, `image()` fields are treated as public paths and *not* transformed. That detail matters in section “Object loaders” below.

### `reference()`

`reference('authors')` validates that the value is a string and transforms it into `{ collection: 'authors', id: '...' }`. It does **not** check that the target exists at validation time: that happens when you call `getEntry()` or `getEntries()`. A dangling reference in `getEntries()` yields `undefined` in the result array, so filter:

```html
---
import { getEntry, getEntries } from 'astro:content';
const post = await getEntry('posts', 'one');
if (!post) throw new Error('missing post');
const author = await getEntry(post.data.author);
const related = (await getEntries(post.data.related)).filter(Boolean);
---
```

## Querying and rendering

### `getCollection`, `getEntry`, `getEntries`

```html
---
import { getCollection, getEntry } from 'astro:content';

const published = (await getCollection('posts', ({ data }) => !data.draft))
  .sort((a, b) => b.data.date.valueOf() - a.data.date.valueOf());

const ann = await getEntry('authors', 'ann');
const sameThing = await getEntry({ collection: 'authors', id: 'ann' });
---
```

The sort order of `getCollection()` is non-deterministic and platform dependent, so sort explicitly. The filter callback receives the full entry, so you can filter on `id` prefixes (`id.startsWith('en/')`) or on `data`. The production-only draft filter is a well-known idiom:

```ts
await getCollection('posts', ({ data }) => (import.meta.env.PROD ? !data.draft : true));
```

Entries are typed from your schema. The `CollectionEntry<'posts'>` type and the `CollectionKey` union are generated into `.astro/types.d.ts` and `.astro/content.d.ts`. These files are produced by `astro sync`, which also runs during `astro dev` and `astro build`; press `s` + Enter in the dev server to re-sync. If the types seem stale after editing `content.config.ts`, that is the first thing to try.

A reusable typed wrapper:

```ts
// src/lib/collections.ts
import { getCollection, type CollectionKey } from 'astro:content';

export function getPublished<C extends CollectionKey>(name: C) {
  return getCollection(name, (e: any) => e.data?.draft !== true);
}
```

### `render()`

For Markdown and MDX entries, `render(entry)` returns `{ Content, headings, remarkPluginFrontmatter }`.

```html
---
// src/pages/blog/[id].astro
import { getCollection, getEntry, render } from 'astro:content';

export async function getStaticPaths() {
  const posts = await getCollection('posts');
  return posts.map((post) => ({ params: { id: post.id }, props: { post } }));
}

const { post } = Astro.props;
const { Content, headings } = await render(post);
const author = await getEntry(post.data.author);
---
<h1>{post.data.title} by {author?.data.name}</h1>
<nav>{headings.filter((h) => h.depth === 2).map((h) => <a href={`#${h.slug}`}>{h.text}</a>)}</nav>
<Content />
```

In my test project this page produced, for an MDX entry containing a Svelte `<Counter client:load start={3} />`, a correctly hydrating `astro-island` inside the rendered output; Chapter 7 covers what is and is not possible with components inside MDX.

`remarkPluginFrontmatter` is the frontmatter *after* processor plugins ran. Verified on 7.4.1 with a `unified()` processor and a plugin that sets `file.data.astro.frontmatter.minutes = 7`: the result was the entry’s whole frontmatter (title, date, author, as parsed) plus `minutes: 7`. Use it for computed values such as reading time.

### Static versus on-demand routes from entries

For prerendered routes you generate paths in `getStaticPaths()`. For on-demand routes you look the entry up from `Astro.params`:

```html
---
export const prerender = false; // not needed with output: 'server'
import { getEntry, render } from 'astro:content';

const post = await getEntry('posts', Astro.params.id!);
if (!post) return new Response(null, { status: 404 });
const { Content } = await render(post);
---
<Content />
```

Note the build-time collection is still *build-time data*: the on-demand page reads from the store that was bundled at build. New content requires a rebuild. If you need request-time freshness, that is what live collections are for.

## Object loaders in depth

When `glob()` and a function loader are not enough, write a loader object:

```ts
interface Loader {
  name: string;
  load: (context: LoaderContext) => Promise<void>;
  schema?: ZodSchema;
  createSchema?: () => Promise<{ schema: ZodSchema; types: string }>;
}
```

The `LoaderContext` gives you:

| Member | Purpose |
|------------------------------------|------------------------------------|
| `collection` | The collection name |
| `store` | The `DataStore` for this collection |
| `meta` | A per-collection key/value store persisted between builds, invisible to consumers |
| `logger` | `AstroIntegrationLogger` with the loader name prefixed |
| `config` | Resolved `AstroConfig` |
| `parseData({ id, data, filePath? })` | Validate and transform against the collection schema |
| `renderMarkdown(md, { fileURL? })` | Render Markdown with the project’s configured processor |
| `generateDigest(data)` | Non-cryptographic digest of a string or object |
| `watcher` | Vite `FSWatcher` in dev, `undefined` in builds |
| `refreshContextData` | Data from an integration-triggered refresh (`astro:server:setup` `refreshContent`) |

The `DataStore` API is `get(id)`, `set(entry)`, `entries()`, `keys()`, `values()`, `delete(id)`, `clear()`, `has(id)`.

### A complete incremental loader

The most important pattern is the *incremental* loader: remember where you left off in `meta`, fetch only what changed, and use digests so unchanged entries are not rewritten.

```ts
// src/loaders/cms-loader.ts
import type { Loader } from 'astro/loaders';
import { z } from 'astro/zod';

interface Options {
  endpoint: string;
  token: string;
}

const articleSchema = z.object({
  title: z.string(),
  slug: z.string(),
  updatedAt: z.coerce.date(),
  body: z.string(),
});

export function cmsLoader({ endpoint, token }: Options): Loader {
  return {
    name: 'cms-loader',
    schema: articleSchema,
    async load({ store, meta, logger, parseData, generateDigest, renderMarkdown }) {
      const since = meta.get('lastSync');
      const url = new URL('/articles', endpoint);
      if (since) url.searchParams.set('updatedSince', since);

      logger.info(since ? `Syncing changes since ${since}` : 'Full sync');
      const res = await fetch(url, { headers: { authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error(`CMS responded ${res.status}`);
      const items: Array<Record<string, unknown> & { id: string; deleted?: boolean }> =
        await res.json();

      for (const item of items) {
        if (item.deleted) {
          store.delete(item.id);
          continue;
        }
        const data = await parseData({ id: item.id, data: item });
        const changed = store.set({
          id: item.id,
          data,
          body: data.body,
          digest: generateDigest(data),
          rendered: await renderMarkdown(data.body),
        });
        if (!changed) logger.debug(`unchanged: ${item.id}`);
      }
      meta.set('lastSync', new Date().toISOString());
    },
  };
}
```

Key behaviours:

- `store.set()` returns `true` if the entry was written and `false` when the `digest` matches the stored entry with the same id. That makes unchanged entries free to “re-set”. Without a digest every `set` overwrites.
- The inline function loader and a loader that begins with `store.clear()` both rebuild everything; the incremental variant above does not clear. The trade-off is that deletions must be handled explicitly, either with a deletion feed or by comparing `store.keys()` with the remote id list and deleting the difference.
- `parseData()` runs the *collection’s* schema when one is defined in `content.config.ts`, otherwise the loader’s own `schema`. A collection-level schema always wins, so users of your loader can extend or transform it.
- Entries you set directly are **not** validated. `parseData()` is how you opt in.

I verified in the test project that a loader which calls `meta.get('runs')` gets `undefined` on the first sync, and that digests written with `generateDigest()` are stable 16-character hex strings that appear on `entry.digest` at query time. (The data store itself, verified, lives in `node_modules/.astro/data-store.json` under the default `cacheDir`; the experimental storage docs describe it as `.astro/data-store.json`. Either way it is generated and should not be committed.)

### `renderMarkdown()` and images

`renderMarkdown()` uses the same processor as `glob()` (Sätteri by default in Astro 7; see Chapter 7), so output, heading ids and plugin behaviour match local Markdown. The result is a `RenderedContent` object:

```ts
{
  html: string,
  metadata?: { headings, imagePaths, frontmatter, ... }
}
```

Assign it to `entry.rendered` and `render()` will give you a working `<Content />`. Verified: an entry with `rendered: await renderMarkdown('## Hi *1*')` rendered as `<h2 id="hi-1">Hi <em>1</em></h2>` and its `headings` array was `[{ depth: 2, slug: 'hi-1', text: 'Hi 1' }]`.

When Markdown contains relative images, pass `fileURL` so they resolve against a real directory, and set `filePath` on the entry so schema `image()` fields work:

```ts
rendered: await renderMarkdown(content, { fileURL: new URL(file.path, config.root) }),
```

### `createSchema()`: dynamic schemas

When the shape is only knowable at build time (introspecting a GraphQL endpoint, a database table, a CMS content model), use `createSchema()` in place of `schema`:

```ts
createSchema: async () => {
  const model = await fetchContentModel(endpoint);
  return {
    schema: buildZodFromModel(model),
    types: `export type Entry = ${modelToTsType(model)}`,
  };
},
```

The returned `types` string is written to a TypeScript file and **must export an `Entry` type or interface**. `createSchema()` replaced the function-valued `schema` of Astro 5 loaders in 6.0, so any loader that returned a function for `schema` has to migrate. As with static schemas, a collection-level `schema` overrides it.

### Dev-time reloads

`watcher` is present only in `astro dev`. The built-in `file()` loader uses it to reload when the source file changes. If your source is remote, you can poll or subscribe from `load()`, but remember `load()` is also what runs in the build; guard dev-only behaviour with `if (watcher)`.

An integration can also trigger a refresh with the `refreshContent()` option of the `astro:server:setup` hook (for example from a CMS webhook); the payload arrives as `refreshContextData`. That is how “preview my draft” workflows are built without restarting the dev server.

## Scale: `deferRender`, storage and incremental builds

Build-time collections are designed for tens of thousands of entries, but three knobs exist for when memory or platform limits bite.

### `glob({ deferRender: true })` (7.1)

By default `glob()` renders each Markdown entry during sync and stores the HTML in the data store, so rendering is cached across builds. For huge collections where the rendered output dwarfs the source, that store can become the memory bottleneck. `deferRender: true` stores only the source and renders each entry when a page calls `render()`, the same path MDX already takes. It does not apply to MDX, Markdoc or data entries. The cost is that rendered HTML is no longer cached between builds.

```ts
const docs = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/data/docs', deferRender: true }),
});
```

Pair it with `retainBody: false` only when you do not need `entry.body`; with `deferRender` the body is the source of rendering, so check what your pages read.

### `experimental.collectionStorage` (7.1, experimental)

```js
// astro.config.mjs
export default defineConfig({
  experimental: {
    collectionStorage: { type: 'chunked', chunkSize: 1024 * 1024 },
  },
});
```

The default `'single-file'` writes one JSON data store. `'chunked'` splits it across files in `.astro/data-store/`, starting a new chunk when the current one exceeds 20 MB, or your `chunkSize`. Use it when the deployment target has per-asset size limits, which is the case for several serverless and edge platforms bundling the store into server output. It is experimental: pin your Astro version and test the output on your host.

### `experimental.incrementalBuild` (7.2, experimental)

```js
export default defineConfig({ experimental: { incrementalBuild: true } });
```

Incremental builds skip rendering static pages whose data and code are unchanged. Only pages from `getStaticPaths()` that return a `cacheKey` can be skipped, and `entry.digest` is the natural key:

```html
---
export async function getStaticPaths() {
  const entries = await getCollection('docs');
  return entries.map((entry) => ({
    params: { slug: entry.id },
    props: { entry },
    cacheKey: String(entry.digest),
  }));
}
---
```

How invalidation works: a matching `cacheKey` is still re-rendered if the page’s module dependency graph changed (layouts, components, imported files); changing the Astro config or dependencies invalidates everything. The cache lives in `cacheDir` (default `node_modules/.astro/`), which must be restored in CI before `astro build` or every page re-renders. `astro build --force` bypasses the cache but writes a fresh one.

Limitations from the docs worth internalizing:

- Disabled when `build.concurrency > 1` (a warning is logged).
- Pages containing server islands embed props encrypted with a per-build key, so they re-render every time unless you pin `ASTRO_KEY` (Chapter 9).
- Middleware changes do **not** invalidate cached pages. If middleware alters prerendered HTML, run `astro build --force` after editing it.

The digest contract matters: the loader is responsible for changing `digest` whenever the data changes. A loader that never sets `digest` gives `cacheKey: 'undefined'` for every entry, which would freeze your pages. Always `generateDigest()` your data.

## Live collections

Live collections fetch at request time. They need an adapter and on-demand rendering of the route that queries them.

### Writing a live loader

A live loader is a pure query interface; there is no store.

```ts
// src/loaders/inventory.ts
import type { LiveLoader } from 'astro/loaders';

export interface Product { sku: string; name: string; stock: number }
interface EntryFilter { sku: string }
interface CollectionFilter { inStock?: boolean }

export class InventoryError extends Error {
  constructor(message: string, public code = 'INVENTORY') {
    super(message);
    this.name = 'InventoryError';
  }
}

export function inventoryLoader(config: { endpoint: string; apiKey: string }):
  LiveLoader<Product, EntryFilter, CollectionFilter, InventoryError> {
  const call = async (path: string) => {
    const res = await fetch(new URL(path, config.endpoint), {
      headers: { authorization: `Bearer ${config.apiKey}` },
    });
    if (res.status === 404) return undefined;
    if (!res.ok) throw new InventoryError(`Upstream ${res.status}`);
    return res.json();
  };

  return {
    name: 'inventory',
    async loadCollection({ filter }) {
      try {
        const qs = filter?.inStock === undefined ? '' : `?inStock=${filter.inStock}`;
        const products: Product[] = await call(`/products${qs}`);
        return {
          entries: products.map((p) => ({
            id: p.sku,
            data: p,
            cacheHint: { tags: [`sku:${p.sku}`] },
          })),
          cacheHint: { tags: ['inventory'], lastModified: new Date() },
        };
      } catch (e) {
        return { error: e instanceof InventoryError ? e : new InventoryError(String(e)) };
      }
    },
    async loadEntry({ filter }) {
      try {
        const p: Product | undefined = await call(`/products/${filter.sku}`);
        if (!p) return undefined; // Astro turns this into LiveEntryNotFoundError
        return { id: p.sku, data: p, cacheHint: { tags: [`sku:${p.sku}`] } };
      } catch (e) {
        return { error: e instanceof InventoryError ? e : new InventoryError(String(e)) };
      }
    },
  };
}
```

The `LiveLoader<TData, TEntryFilter, TCollectionFilter, TError>` generics define the type-safe filters accepted by `getLiveCollection()` and `getLiveEntry()` and the custom error class. `loadEntry` receives `{ id }` when the caller passes a string; define `EntryFilter` with an `id` alias if you want both calling styles. JSDoc comments on filter fields show up in editors.

Register it:

```ts
// src/live.config.ts
import { defineLiveCollection } from 'astro:content';
import { inventoryLoader } from './loaders/inventory';

export const collections = {
  inventory: defineLiveCollection({
    loader: inventoryLoader({ endpoint: process.env.INVENTORY_URL!, apiKey: process.env.INVENTORY_KEY! }),
  }),
};
```

A Zod `schema` on the live collection overrides the loader’s generic type, and validation failures become `LiveCollectionValidationError`. Unlike build-time loaders there is no `parseData()`: *you* are responsible for returning valid data when no schema is set.

### Querying and handling errors

```html
---
export const prerender = false;
import { getLiveCollection, getLiveEntry } from 'astro:content';
import { LiveEntryNotFoundError } from 'astro/content/runtime';
import { InventoryError } from '../loaders/inventory';

const { entry, error, cacheHint } = await getLiveEntry('inventory', { sku: Astro.params.sku! });

if (error instanceof LiveEntryNotFoundError) {
  return Astro.rewrite('/404');
}
if (error instanceof InventoryError) {
  console.error(error.code, error.message);
  return new Response('Inventory unavailable', { status: 503 });
}
if (error) throw error;

if (cacheHint) Astro.cache.set(cacheHint);
Astro.cache.set({ maxAge: 30, swr: 120 });
---
<h1>{entry.data.name}</h1>
<p>{entry.data.stock > 0 ? 'In stock' : 'Sold out'}</p>
```

**Doc discrepancy, verified:** the content-collections guide imports `LiveEntryNotFoundError` and `LiveCollectionValidationError` from `astro/content/runtime`, while the `astro:content` reference lists no error classes among its exports. I confirmed on 7.4.1 that `import { LiveEntryNotFoundError } from 'astro:content'` fails the build with `"LiveEntryNotFoundError" is not exported by "\0astro:content"`. Import the classes from `astro/content/runtime`.

The error taxonomy:

| Error | Raised when |
|------------------------------------|------------------------------------|
| Loader’s own error type | Loader returned `{ error }` |
| `LiveEntryNotFoundError` | `loadEntry()` returned `undefined` |
| `LiveCollectionValidationError` | Schema validation failed |
| `LiveCollectionCacheHintError` | Loader returned an invalid cache hint (just omit `cacheHint` if you have none) |
| `LiveCollectionError` | Any uncaught exception inside the loader |

Because a thrown exception inside a loader is caught and wrapped, a live page never crashes with a stack trace from the loader; it hands you a value. That is excellent for resilience and a trap for observability: log every `error` you branch on, or failures silently degrade into “not found”.

I ran the inventory example above against `astro build` with the Node adapter. Results, verified: a known SKU rendered its name; an unknown SKU produced `LiveEntryNotFoundError` (and setting `Astro.response.status = 404` yielded a 404 response); a `boom` SKU surfaced the custom `InventoryError` with its `code`; and `getLiveCollection('inventory', { inStock: true })` returned a merged `cacheHint` of `{ tags: ['inventory', 'sku:a1'], lastModified }`, confirming that tags accumulate across collection and entries while the latest `lastModified` wins.

### Cache hints and route caching

`cacheHint` is `{ tags?: string[]; lastModified?: Date }`. Hints do **nothing by themselves**; they are inputs you give to route caching (`Astro.cache.set(cacheHint)`, Chapter 12) or to your own headers:

```ts
if (cacheHint?.tags) Astro.response.headers.set('Cache-Tag', cacheHint.tags.join(','));
if (cacheHint?.lastModified) Astro.response.headers.set('Last-Modified', cacheHint.lastModified.toUTCString());
```

With a cache provider configured, a webhook endpoint can invalidate by entry, which uses the entry’s tags:

```ts
// src/pages/api/revalidate.ts
import type { APIRoute } from 'astro';
import { getLiveEntry } from 'astro:content';

export const prerender = false;
export const POST: APIRoute = async (context) => {
  const { sku } = await context.request.json();
  const { entry } = await getLiveEntry('inventory', { sku });
  if (entry) await context.cache.invalidate(entry);
  return Response.json({ ok: true });
};
```

Remember that `cache.invalidate()` throws when no provider is configured, and that path invalidation is exact-match (Chapter 12).

### Limitations to plan around

- No MDX (it cannot be compiled at request time) and no `image()` optimization.
- Per-request network cost unless cached.
- No data store, so no `getCollection()`-style filter callbacks: filtering is whatever your loader’s filter type supports, executed by the upstream.
- `render()` works only if the loader returns `rendered: { html }`; otherwise `<Content />` renders nothing.

## `fetch()` in frontmatter and top-level await

Astro component frontmatter runs on the server, at build time for prerendered pages and per request for on-demand pages, and top-level `await` is allowed:

```html
---
const res = await fetch('https://api.example.com/rates');
if (!res.ok) throw new Error(`rates failed: ${res.status}`);
const rates: Record<string, number> = await res.json();
---
<Ticker client:visible rates={rates} />
```

Three consequences that senior developers should hold in their head:

1.  **Where it runs depends on `prerender`.** The same line is a build-time call on a static page and a per-request call on an on-demand page. Dev mode refetches on every refresh, so do not infer production behaviour from dev.
2.  **Fetches inside a component are blocking for that component’s output.** With streaming, the HTML before the component is flushed while the awaited content waits (I measured chunks arriving at 0.00s and 0.59s for a 600 ms await, with later siblings held behind the slow one because rendering is in document order). Slow, non-critical data belongs in a server island (Chapter 9), or should be started early and awaited late.
3.  **Framework components fetch too**, but with a twist: a top-level `await` in a Svelte component’s script is not the same as Astro’s; with Svelte async SSR (experimental, Chapter 3) you can `await` in expressions. Prefer fetching in the `.astro` parent and passing serializable props.

To call your own on-demand endpoints from frontmatter, build the URL from `Astro.url`: `new URL('/api/x', Astro.url)`.

Passing fetched data to a Svelte island works with any of the serializable types (Chapter 3): objects, arrays, `Date`, `Map`, `Set`, `URL`, `BigInt`, typed arrays. Collection entries are plain objects with a `Date` here and there, so `data` crosses the island boundary cleanly. Do not pass whole entries if you only need two fields; the props are inlined into the HTML.

```html
---
import PriceList from '../components/PriceList.svelte';
import { getCollection } from 'astro:content';
const items = (await getCollection('products')).map(({ id, data }) => ({
  id,
  name: data.name,
  price: data.price,
}));
---
<PriceList client:visible items={items} />
```

```html
<!-- src/components/PriceList.svelte -->
<script lang="ts">
  let { items }: { items: { id: string; name: string; price: number }[] } = $props();
  let sortAsc = $state(true);
  const sorted = $derived([...items].sort((a, b) => (sortAsc ? a.price - b.price : b.price - a.price)));
</script>

<button onclick={() => (sortAsc = !sortAsc)}>Sort {sortAsc ? '↑' : '↓'}</button>
<ul>
  {#each sorted as item (item.id)}
    <li>{item.name}: {item.price.toFixed(2)}</li>
  {/each}
</ul>
```

## Choosing the data path

Four tools overlap, and mixing them up is the most common architectural mistake in Astro projects.

| Need | Use | Why |
|------------------------|------------------------|------------------------|
| Content edited by developers in the repo | `glob()` / `file()` | Versioned, typed, zero infrastructure |
| Remote data that changes at the speed of a deploy (CMS pages, docs, catalog descriptions) | Object loader or inline loader, build-time | Cached in the store, MDX and images supported, static HTML |
| Remote data that must be fresh per request, filterable by user input | Live collection | Typed API, cache hints, rendered on the server |
| Per-user or per-request data with custom auth, mutations, non-collection shapes | Endpoint (`src/pages/api/*.ts`) or action | Not collection-shaped; you control methods and status codes |
| Data that changes *while the page is open* (live price, notifications) | Client fetch from a Svelte island | Server render cannot help after load |
| Slow, personalized fragment on an otherwise static page | Server island | Chapter 9 |

Decision heuristics I apply in reviews:

- If the data is public, shared by all users and tolerates minutes of staleness, prefer a **build-time loader plus a rebuild webhook** over live collections. You get static HTML and an edge cache for free.
- If staleness tolerance is seconds but the data is still shared, **live collection plus route caching** (`maxAge`, `swr`, tags) gives you near-static speed with invalidation.
- If the data is per-user, no shared cache is safe; use a live collection or endpoint **without** caching hints, or a server island.
- Never fetch third-party APIs directly from an island with a secret. Client code is public. Go through an endpoint or server-rendered props.
- A build-time loader that runs `store.clear()` and refetches everything is simple but makes build time proportional to source size; switch to incremental loading with `meta` and digests once it hurts.

## Secrets and backends with `astro:env`

Loaders and live loaders usually need credentials. There are two safe routes and one trap.

**Safe route 1: `process.env` / `loadEnv` in the config and loader.** `.env` files are *not* loaded into `process.env` inside `astro.config.*`; use `loadEnv` from `vite` there. Inside `content.config.ts` and `live.config.ts`, which are modules processed by Vite, `import.meta.env` works for `VITE_`-prefixed variables only, and `process.env` works at runtime on Node. Be explicit about where each runs, since live configs execute on the server at request time while build-time configs run during the build.

**Safe route 2: `astro:env`.** Declare the variable once in the config schema:

```js
// astro.config.mjs
import { defineConfig, envField } from 'astro/config';

export default defineConfig({
  env: {
    schema: {
      CMS_ENDPOINT: envField.string({ context: 'server', access: 'public' }),
      CMS_TOKEN: envField.string({ context: 'server', access: 'secret' }),
    },
  },
});
```

```ts
// src/content.config.ts
import { CMS_ENDPOINT, CMS_TOKEN } from 'astro:env/server';
```

Secrets validated through `astro:env/server` are checked whenever the module is imported unless `validateSecrets` is disabled, which means CI builds need dummy values; Chapter 16 covers the limitations (including that the schema cannot be used inside `astro.config.mjs` itself).

**The trap:** passing a secret to a client directive component as a prop, or reading `import.meta.env.SECRET` in a Svelte island. Anything that reaches a hydrated island is serialized into the HTML. Treat island props as published data.

### CMS patterns

The docs’ CMS guides (Storyblok, Contentful, WordPress and others) follow two shapes. Prefer the first:

1.  **Loader per content type.** One object loader per CMS model, `meta`-based incremental sync, webhook-driven refresh in dev via `refreshContent`, and a CI rebuild webhook in production. Pages stay static.
2.  **Live collection for drafts.** A second live collection pointing at the CMS *preview* API, used only on `/preview/*` on-demand routes protected by a cookie. Editors see unpublished content immediately; published pages remain static.

A backend-as-a-service (Supabase, Firebase, Turso and so on) is a *data source*, not a content layer. Wrap read-only, mostly-static tables in a loader; keep transactional data behind endpoints or actions.

## `legacy.collectionsBackwardsCompat`

Astro 6 removed the pre-5.0 collections implementation. Projects that cannot migrate immediately can set:

```js
export default defineConfig({ legacy: { collectionsBackwardsCompat: true } });
```

It restores `type: 'content'` / `type: 'data'` collections without loaders, `entry.slug` and `entry.render()`, and path-based entry IDs. It is explicitly temporary. The migration is mechanical: add `loader: glob({ pattern: '**/*.{md,mdx}', base: './src/content/<name>' })`, replace `entry.slug` with `entry.id`, replace `entry.render()` with `render(entry)` from `astro:content`, and re-check ids because loader ids are slugified. Chapter 19 sequences this with the rest of the upgrade.

## Putting it together: a typed content module

A pattern that scales: wrap queries in a module so pages never repeat filtering and sorting.

```ts
// src/lib/blog.ts
import { getCollection, getEntry, getEntries, render, type CollectionEntry } from 'astro:content';

export type Post = CollectionEntry<'posts'>;

export async function listPosts(): Promise<Post[]> {
  const posts = await getCollection('posts', ({ data }) => import.meta.env.DEV || !data.draft);
  return posts.sort((a, b) => b.data.date.valueOf() - a.data.date.valueOf());
}

export async function postWithRelations(id: string) {
  const post = await getEntry('posts', id);
  if (!post) return undefined;
  const [author, related, { Content, headings }] = await Promise.all([
    getEntry(post.data.author),
    getEntries(post.data.related),
    render(post),
  ]);
  return { post, author, related: related.filter(Boolean) as Post[], Content, headings };
}
```

`Content` is a component; it cannot be passed to a Svelte island, but it can be rendered in the Astro page that hosts the island. Keep that boundary clear: collections produce **data for Astro to render** and **serializable props for islands**.

## Key takeaways

- Build-time collections sync into a persistent data store at build and are queried with `getCollection`/`getEntry`; live collections are request-time, adapter-only, return `{ entry|entries, error, cacheHint }` and have no store.
- Define collections in `src/content.config.ts` (`src/live.config.ts` for live). Import `z` from `astro/zod` (Zod 4); use `z.email()`, `{ error }`, `.prefault()`.
- `glob()` slugifies ids, supports `generateId`, `retainBody`, and 7.1’s `deferRender`; `file()` needs explicit ids and a `parser` for non-JSON/YAML/TOML formats.
- `reference()` validates shape only; missing targets show up as `undefined` from `getEntry`/`getEntries`.
- Object loaders get `store`, `meta`, `parseData`, `generateDigest`, `renderMarkdown`, `watcher`. `store.set()` returns `false` for an unchanged digest, which is the basis of incremental loaders and incremental builds.
- `parseData()` is how entries get validated; directly set entries are not validated. A collection schema overrides a loader’s schema. `createSchema()` must return types exporting `Entry`.
- Scale knobs: `deferRender`, experimental `collectionStorage: 'chunked'`, experimental `incrementalBuild` with `cacheKey` (disabled with `build.concurrency > 1`; middleware changes do not invalidate).
- Live loaders return errors as values. Import `LiveEntryNotFoundError` and friends from `astro/content/runtime`, not `astro:content`. Cache hints are inputs to route caching or headers and do nothing alone.
- Choose the data path by freshness and audience: repo files, build-time loader plus rebuild hook, live collection plus cache, endpoint or action, island fetch, or server island.
- Secrets belong on the server: `astro:env/server` or `process.env`; anything passed to an island prop is public.

## Review Questions

1.  Name three differences between a build-time collection and a live collection beyond the config file name.

2.  What does the following print for a file `src/posts/Hello World.md` loaded with a default `glob()` loader, and how would you keep the original casing?

    ```ts
    const posts = await getCollection('posts');
    console.log(posts[0].id);
    ```

3.  Why is `getCollection()` output not safe to render in array order, and what is the fix?

4.  Find the bug:

    ```ts
    import { defineCollection } from 'astro:content';
    import { glob } from 'astro/loaders';
    import { z } from 'astro/zod';
    const blog = defineCollection({
      loader: glob({ pattern: '**/*.md', base: './src/blog' }),
      schema: z.object({ cover: image(), title: z.string() }),
    });
    ```

5.  In a Zod 4 schema, which is correct for “list of tags, default empty array, input may be omitted”? (a) `z.array(z.string()).default('[]')` (b) `z.array(z.string()).prefault([])` (c) `z.array(z.string()).optional().default(undefined)` (d) `z.string().array().default(null)`.

6.  What does `reference('authors')` validate at schema-validation time, and when does a dangling reference surface?

7.  A loader calls `store.set({ id, data })` without a `digest` for every entry on every build. What does that imply for incremental builds that use `cacheKey: String(entry.digest)`?

8.  What does `store.set()` return when the entry’s digest matches what is already stored, and why is that useful?

9.  Explain the difference between `schema` and `createSchema()` on a loader object, including what extra requirement the `types` string has.

10. A user of your published loader defines their own `schema` in `content.config.ts`. Whose schema validates the data passed through `parseData()`?

11. What happens if you write entries directly with `store.set()` and never call `parseData()`?

12. Complete the code so that rendered Markdown from a CMS can be shown with `render()`: `ts store.set({ id: item.id, data, /* ??? */ });`

13. Where is the collection data store written in 7.4.1 under default settings, and what does `experimental.collectionStorage: 'chunked'` change?

14. When would you choose `deferRender: true` on a `glob()` loader, and what do you give up?

15. List the three documented limitations of `experimental.incrementalBuild`.

16. Why must a CI pipeline restore `node_modules/.astro/` before `astro build` when incremental builds are enabled?

17. What is wrong with this live-collection page and how do you fix it? `astro --- import { getLiveEntry, LiveEntryNotFoundError } from 'astro:content'; const { entry, error } = await getLiveEntry('products', Astro.params.id!); ---`

18. What does a live loader’s `loadEntry()` returning `undefined` become at the call site?

19. Given a live collection where entry A has `cacheHint.tags = ['a']`, entry B has `['b']`, and the collection hint is `{ tags: ['all'], lastModified: D1 }` while A’s `lastModified` is `D2 > D1`, what is the merged hint from `getLiveCollection()`?

20. True or false: returning a `cacheHint` from a live loader causes Astro to cache the response. Explain.

21. Why can’t live collections render MDX or optimize images?

22. Multiple choice: which is the most appropriate tool for a product’s stock level that must be accurate within a few seconds for all visitors, with a cache and tag-based invalidation? (a) `glob()` loader (b) build-time object loader (c) live collection with route caching (d) `fetch()` inside a Svelte island.

23. Multiple choice: you need a price table whose values come from a CMS that publishes a few times per day and must render as static HTML. Best fit? (a) live collection (b) object loader with a rebuild webhook (c) server island (d) endpoint called from `onMount`.

24. A frontmatter `await fetch(...)` takes 600 ms in an on-demand page. What do users see, and in what order does the HTML arrive for the markup before and after it? How would you avoid blocking?

25. A teammate passes `{ apiKey }` from `astro:env/server` as a prop to a `client:load` Svelte component “because the component runs on the server first”. What is the problem?

26. Why do CI builds sometimes fail on `astro:env/server` secrets, and what are two ways to handle that?

27. Describe the migration steps for a project using `legacy.collectionsBackwardsCompat` with `type: 'content'` collections.

28. Design question: you have 40 000 Markdown docs and builds run out of memory during `astro build`. List the options from this chapter in the order you would try them, with the trade-off of each.
