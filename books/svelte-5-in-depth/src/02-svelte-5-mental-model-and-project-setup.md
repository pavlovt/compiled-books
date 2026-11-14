# Chapter 1: Svelte 5 Mental Model and Project Setup

Svelte is two things that are easy to conflate: a compiler that turns `.svelte` files into JavaScript modules, and a small runtime (a signals-based reactivity graph plus DOM helpers) that this generated code calls into. Almost every question you will have about Svelte 5 — why `count++` updates the screen, why a rune cannot be passed to a function, why some code only works in a file called `*.svelte.ts` — is answered by remembering that split. The compiler sees your source, rewrites it, and leaves behind code that talks to the runtime. This chapter builds that mental model, shows how to set up a project with the tools current in October 2026 (Svelte 5.57), and walks through the anatomy of a component, the module system around it, the mounting API and the tooling you will live in. Later chapters go deep on each piece: the compiler in Chapter 2, `$state` in Chapter 3, effects in Chapter 4, and the runtime in Chapter 5.

All examples in this book use runes mode and TypeScript unless stated otherwise. Legacy (Svelte 3/4) syntax appears only in migration contexts, mainly Chapter 20.

## What Svelte is today

Svelte’s pitch has not changed since version 1: write declarative components in a superset of HTML, and let a compiler turn them into “lean, tightly optimized JavaScript”. What changed in version 5 is *how the output keeps the DOM up to date*.

In Svelte 3 and 4, the compiler analysed each component and generated an `$$invalidate(...)` call after every assignment to a top-level `let`. A component instance was a class with a generated `update` method that diffed a bitmask of dirty variables. Reactivity was a compile-time property of one component file; it stopped at the file boundary, which is why sharing reactive logic required stores.

In Svelte 5, reactivity is a runtime property built on **signals**. A `$state` value is a source; a `$derived` is a computation that tracks the sources it reads; templates compile into small effects that read sources and write to specific DOM nodes. A component is no longer a class with an update method: it is a plain function that runs once, creates its DOM, and registers those effects. There is no component-level re-render and no virtual DOM. Because the dependency graph lives at runtime, the same reactive primitives work inside components, inside plain modules, and across files.

You do not interact with the signals API directly. You write `let count = $state(0)` and `count++`, and the compiler rewrites reads and writes into calls on the runtime. The syntax is the contract; the runtime is private. In fact the generated code imports from `svelte/internal/client`, and importing anything from `svelte/internal/*` in a runes-mode component is a compile error (`import_svelte_internal_forbidden`). Internals are free to change in any patch release, and this book labels every look at them as illustrative.

### Svelte 4 to Svelte 5 on one page

If you know Svelte 4, this table is the whole delta at the syntax level. Chapter 20 covers the migration in detail.

| Concern | Svelte 4 | Svelte 5 (runes mode) |
|------------------------|------------------------|------------------------|
| Local state | `let count = 0` (implicitly reactive) | `let count = $state(0)` |
| Derived values | `$: doubled = count * 2` | `let doubled = $derived(count * 2)` |
| Side effects | `$: console.log(count)` | `$effect(() => { console.log(count) })` |
| Props | `export let name` | `let { name } = $props()` |
| DOM events | `on:click={handler}` | `onclick={handler}` |
| Component events | `createEventDispatcher` | callback props |
| Content projection | `<slot>`, `let:` | snippets and `{@render}` |
| Component instantiation | `new App({ target })` | `mount(App, { target })` |
| Shared reactive logic | stores | `$state` in `.svelte.ts` modules, classes |
| Lifecycle | `beforeUpdate`, `afterUpdate`, `onMount`, `onDestroy` | `$effect.pre`, `$effect`, `onMount`, `onDestroy` |
| Actions | `use:action` | `{@attach ...}` (5.29+; `use:` still works) |

A few more facts are worth having in your head from the start. Components are functions, not classes. Events are ordinary attributes (`onclick`), which means they can be spread and passed as props. State is a variable, not a store object, so `count` is a number and not something you `.get()`. And nothing in a `.svelte` file re-executes when state changes: the `<script>` runs once per instance, and *reactive constructs* (`$derived`, `$effect`, template expressions) are the only parts that re-run.

## Creating a project

Svelte on its own is a compiler and a runtime; you still need a bundler to turn `.svelte` files into something a browser loads. Everything in the Svelte ecosystem targets **Vite**, via `@sveltejs/vite-plugin-svelte`. There are two supported ways to get a project.

### `npx sv create`

`sv` is the official Svelte CLI. The docs lead with it:

```bash
npx sv create myapp
cd myapp
npm install
npm run dev
```

`sv create` accepts `--template` (choices at the time of writing: `minimal`, `demo`, `library`, `addon`), `--types ts|jsdoc`, `--add <addon...>` and `--install <package-manager>`. Official add-ons include `prettier`, `eslint`, `vitest`, `playwright`, `tailwindcss` and others. The docs recommend this route because it scaffolds SvelteKit, the application framework. This book is about Svelte itself, and SvelteKit is mentioned only in passing: a framework such as SvelteKit calls `mount`, `hydrate` and `render` for you, adds routing, data loading and server integration, and owns the Vite configuration. If you want a framework, start there. If you want to understand Svelte, use the second route.

The other `sv` commands you will meet are `sv add` (apply an add-on to an existing project), `sv migrate` (for example `npx sv migrate svelte-5`, Chapter 20) and `sv check` (the CLI type and diagnostics checker, covered below).

### Vite with the `svelte` template

For a framework-less project, which is what this book assumes:

```bash
npm create vite@latest myapp -- --template svelte-ts
cd myapp
npm install
npm run dev
```

The `svelte` and `svelte-ts` templates are plain Vite projects. At the time of writing, the TypeScript template pins `svelte ^5.57.2`, `@sveltejs/vite-plugin-svelte ^7.3.1`, `vite ^8.3.4`, `svelte-check`, `@tsconfig/svelte` and TypeScript 6. The layout is:

```text
myapp/
  index.html
  package.json
  svelte.config.js
  tsconfig.json
  tsconfig.app.json
  tsconfig.node.json
  vite.config.ts
  public/
  src/
    main.ts
    app.css
    App.svelte
    lib/Counter.svelte
```

I built this template and ran `npm run build` and `npm run check` against it; both succeed with no warnings. Three files matter for the mental model.

```ts
// vite.config.ts
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [svelte()],
})
```

The plugin is the only integration point. It registers a transform for `.svelte` files (and for `.svelte.js`/`.svelte.ts` modules), calls the compiler with the right options for dev or build, handles CSS and HMR, and reads `svelte.config.js`.

```js
// svelte.config.js
/** @type {import("@sveltejs/vite-plugin-svelte").SvelteConfig} */
export default {}
```

The scaffolded config is empty. Notice there is no preprocessor: since Svelte 5, `<script lang="ts">` supports type-only TypeScript syntax natively, so `vitePreprocess` is no longer needed for ordinary type annotations. You add it back when you need TypeScript features that require code generation (enums, constructor parameter properties) or when you use `<style lang="scss">`:

```js
// svelte.config.js
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte'

export default {
  preprocess: vitePreprocess({ script: true }),
  compilerOptions: {
    // passed to svelte/compiler `compile`; see Chapter 2 for every option
    runes: undefined,
  },
}
```

`SvelteConfig` has these top-level keys, as declared by the plugin’s types: `extensions` (default `['.svelte']`), `preprocess`, `compilerOptions`, `onwarn`, and `vitePlugin` (plugin options). `compilerOptions` is typed as the compiler’s `CompileOptions` minus `filename`, `format` and `generate`, which the plugin controls itself. The same `compilerOptions` can be passed inline as `svelte({ compilerOptions: {...} })` in `vite.config.ts`.

```ts
// src/main.ts
import { mount } from 'svelte'
import './app.css'
import App from './App.svelte'

const app = mount(App, {
  target: document.getElementById('app')!,
})

export default app
```

Nothing else bootstraps the app. `index.html` has a `<div id="app">` and a module script pointing at `main.ts`. We return to `mount` below.

> **Note:** Vite is also used in standalone mode to build single page apps. `npm run build` produces `dist/` with HTML, JS and CSS. In most cases you will pick a routing library as well, because Svelte itself has no router.

## Anatomy of a `.svelte` file

A component is a file with up to four top-level sections, all optional:

```html
<!-- Anatomy.svelte -->
<script module lang="ts">
  // runs once, when the module is first evaluated
</script>

<script lang="ts">
  // runs once per component instance
</script>

<!-- markup: zero or more nodes -->

<style>
  /* scoped CSS */
</style>
```

### The instance `<script>`

Code in the instance script runs when a component instance is created. Top-level declarations (and imports) can be referenced from the markup. That is the entire execution model of the script: **it runs once per instance, top to bottom, synchronously**. Nothing re-runs it.

This is the source of the most common beginner error in Svelte 5, which the best-practices page spells out for props:

```html
<script lang="ts">
  let { type }: { type: 'danger' | 'ok' } = $props()

  // Runs once. `color` will NOT update if `type` changes.
  let color = type === 'danger' ? 'red' : 'green'

  // Correct: re-evaluated when `type` changes.
  let color2 = $derived(type === 'danger' ? 'red' : 'green')
</script>
```

The compiler warns about the first form (`state_referenced_locally`: “This reference only captures the initial value of `type`. Did you mean to reference it inside a closure instead?”). I saw exactly this warning in a Vitest run for `let count = $state(start)` where `start` was a prop. Sometimes capturing the initial value is exactly what you want, such as seeding local state from a prop, and in that case you rename the prop (`initialCount`) and ignore the warning with a comment, as we will see in Chapter 2.

The `lang="ts"` attribute switches the parser to TypeScript. Only syntax that erases to JavaScript is allowed by default; the details are in Chapter 15.

### `<script module>`

A `<script>` with the `module` attribute runs once when the module first evaluates, not per instance. Bindings declared there are visible to the instance script and the markup, but not vice versa. You can `export` from it and the exports become exports of the compiled module (for example, a helper function or a type). You cannot `export default`, since the default export is the component.

I confirmed the semantics with a component that increments a module-level counter in the instance script and mounted it twice: the instance script logged `instance 1` and `instance 2` while the module script logged once, at import time.

```html
<!-- Inst.svelte -->
<script module lang="ts">
  let total = 0
  export function getTotal() {
    return total
  }
</script>

<script lang="ts">
  total += 1
  console.log(`instantiated ${total} times`)
  let n = $state(0)
</script>

<p>{n}</p>
```

Two caveats. First, module-level variables are shared by every instance *and, in server rendering, by every request handled by the same process*. That makes `<script module>` the wrong home for per-user state (Chapters 12 and 14). Second, if you import such an export into a `.ts` file, the TypeScript language service must know about it. The Svelte VS Code extension and the IntelliJ plugin do; elsewhere you may need `typescript-svelte-plugin`. In Svelte 4 this block was `<script context="module">`; in runes mode the old spelling produces the `script_context_deprecated` warning.

### Markup

Markup is HTML with expressions in braces, plus blocks (`{#if}`, `{#each}`), directives and special elements. Chapter 6 covers it completely. For this chapter only one fact matters: markup is not re-run either. The compiler turns each reactive expression into a small effect, and each effect updates exactly one DOM node or attribute (Chapter 5 shows how).

### `<style>`

CSS in a top-level `<style>` is scoped to the component by adding a generated class to the selectors and to the elements. Chapter 10 covers scoping, `:global` and the CSS-related compiler options. There can be only one top-level `<style>` per component.

## `.svelte.js` and `.svelte.ts` modules

Besides `.svelte` files, Svelte also processes files named `*.svelte.js` and `*.svelte.ts`. They behave like normal modules except that runes are available. This is how you build reusable reactive logic outside components:

```ts
// src/lib/counter.svelte.ts
export function createCounter(initial = 0) {
  let count = $state(initial)
  let doubled = $derived(count * 2)

  return {
    get count() {
      return count
    },
    get doubled() {
      return doubled
    },
    increment() {
      count += 1
    },
  }
}
```

```html
<!-- src/App.svelte -->
<script lang="ts">
  import { createCounter } from './lib/counter.svelte'

  const counter = createCounter(10)
</script>

<button onclick={counter.increment}>
  {counter.count} / {counter.doubled}
</button>
```

Note the import path: you write `./lib/counter.svelte`, without the `.ts`. Note too that the returned object exposes *getters*, not values: `return { count }` would capture the number once, and the caller would see a constant. This is the practical consequence of “runes are not values”, and Chapter 3 spends a whole section on it.

### The compiler sees one file at a time

The single most important rule for working with runes outside components is that **the compiler processes one file at a time**, and a rune is meaningful only in a file the compiler processes. Two things follow, both of which I verified by compiling and running small modules against Svelte 5.57.2.

First, a rune in an ordinary `.ts` file is not rewritten. The TypeScript types declare `$state` globally, so the editor is happy, but at runtime the call hits a stub and throws `rune_outside_svelte`:

```ts
// src/lib/plain.ts  (note: no .svelte in the name)
export function make() {
  return $state(0) // type-checks; throws rune_outside_svelte when called
}
```

Second, the compiler cannot know how another file uses a binding. A reference to reassigned `$state` is rewritten to `$.get(count)` and `$.set(count, ...)`. If another module imported that variable, its importer would see the underlying signal object, not a number. So exporting reassigned state is rejected at compile time:

```ts
// src/lib/bad.svelte.ts
export let count = $state(0)      // error: state_invalid_export
export function inc() { count++ }
```

The actual message is “Cannot export state from a module if it is reassigned. Either export a function returning the state value or only mutate the state value’s properties”. The two legal alternatives are an exported `const` object that you mutate (`export const counter = $state({ count: 0 })`), or an exported accessor function. Chapter 3 covers both, and Chapter 2 shows the compiler output that makes the reason obvious.

Where should this logic live? A useful rule: put the logic that is not about DOM in `.svelte.ts` modules (testable without a component, Chapter 16), keep components thin, and prefer classes or factory functions over exporting naked state.

## Runes: what they are and where they are valid

Runes are the compiler-level keywords of Svelte 5. The docs state three differences from functions: you do not import them; they are not values (you cannot assign one to a variable or pass it as an argument); and, like keywords, they are valid only in certain positions, and the compiler tells you when you misplace one. The full set at 5.57 is:

| Rune        | Variants                                 |
|-------------|------------------------------------------|
| `$state`    | `.raw`, `.snapshot`, `.eager`            |
| `$derived`  | `.by`                                    |
| `$effect`   | `.pre`, `.tracking`, `.pending`, `.root` |
| `$props`    | `.id`                                    |
| `$bindable` |                                          |
| `$inspect`  | `.with`, `.trace`                        |
| `$host`     |                                          |

Chapters 3 and 4 cover `$state`, `$derived`, `$effect` and `$inspect`; `$props` and `$bindable` are in Chapters 7 and 8, `$host` in Chapter 19. A few historical names no longer exist and are worth recognising when you read old posts: `$state.frozen` became `$state.raw`, `$derived.call` became `$derived.by`, `$effect.active` became `$effect.tracking`, and `$state.link` and `$state.is` were removed.

Runes are valid in `.svelte`, `.svelte.js` and `.svelte.ts` files. Using one anywhere else compiles (it is just a function call) and fails at runtime with `rune_outside_svelte`, as above.

## Runes mode versus legacy mode

Svelte 5 still compiles Svelte 3/4 components. The compiler therefore operates in one of two modes per component, **runes mode** or **legacy mode**, and the mode changes which syntax is legal. In runes mode, `export let`, `$:`, `$$props`, `beforeUpdate` and implicit reactivity are unavailable (or an error: I confirmed that `export let a` next to a `$state` produces `legacy_export_invalid`, “Cannot use `export let` in runes mode — use `$props()` instead”). In legacy mode, runes are not recognised.

### How the compiler decides

Reading `phases/2-analyze/index.js` in the 5.57.2 package gives the decision procedure:

1.  If the `runes` compiler option is a function, it is called with `{ filename }` and may return `true`, `false` or `undefined`. A boolean option is used as-is.
2.  A `<svelte:options runes />` (or `runes={false}`) in the component overrides the option.
3.  If the result is still `undefined`, the compiler infers runes mode when the component references any rune (a `$state`, `$derived`, …) or contains an `await` in its top-level script or markup (the latter is the experimental async feature).
4.  JavaScript and TypeScript modules (`compileModule`) are always runes mode.

I checked inference with `compile(...)` and `result.metadata.runes`:

```js
import { compile } from 'svelte/compiler'

const cases = {
  legacy:       `<script>let n = 0</script><button on:click={() => n++}>{n}</button>`,
  runes:        `<script>let n = $state(0)</script><button onclick={() => n++}>{n}</button>`,
  forcedRunes:  `<svelte:options runes /><script>let n = 0</script><p>{n}</p>`,
  noScript:     `<p>hi</p>`,
}
for (const [name, src] of Object.entries(cases)) {
  console.log(name, compile(src, { filename: 'A.svelte' }).metadata.runes)
}
// legacy false / runes true / forcedRunes true / noScript false
```

The last line is the subtle one: a component with no script at all is compiled in legacy mode, which is harmless: with no state and no props there is nothing that would behave differently in runes mode.

Why does this matter in practice? Because inference is per file and silent. A component whose only reactive declaration is `let count = 0` and that you *intended* to be runes mode compiles in legacy mode, where `count++` is implicitly reactive. It happens to work, which hides the mistake until you add `$derived` somewhere and get a mixed-mode error. The remedy is to make the mode explicit for the whole project.

### Forcing runes mode

Svelte 6 will default `runes` to `true`. Until then you can opt in today. There are two scopes:

```html
<svelte:options runes />
```

per component, and the compiler option for everything:

```js
// svelte.config.js
export default {
  compilerOptions: { runes: true },
}
```

Be careful with the second form. The docs warn that setting `runes: true` in `svelte.config.js` forces runes mode for your entire project, **including components in `node_modules`**, which will break libraries that still ship legacy-mode components. The safe form uses the plugin’s `dynamicCompileOptions` hook, which receives the filename and the current options, and lets you scope the setting:

```ts
// vite.config.ts
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [
    svelte({
      dynamicCompileOptions({ filename }) {
        if (!filename.includes('node_modules')) {
          return { runes: true }
        }
      },
    }),
  ],
})
```

Since 5.54 the `runes` compile option itself also accepts a function, `({ filename }) => boolean | undefined`, which can do the same filtering in `svelte.config.js`. Returning `undefined` means “infer”. Chapter 2 lists every compiler option.

Legacy and runes components interoperate: a runes-mode parent can render a legacy child and vice versa, which is what makes incremental migration possible (Chapter 20). The rest of this book assumes runes mode.

## The entry point: `mount`, `hydrate`, `unmount`

Svelte 4 instantiated components with `new App({ target })`. In Svelte 5 components are functions, and the entry points are imperative functions imported from `svelte`:

```ts
import { mount, hydrate, unmount, flushSync } from 'svelte'
```

### `mount`

```ts
import { mount } from 'svelte'
import App from './App.svelte'

const app = mount(App, {
  target: document.querySelector('#app')!,
  props: { some: 'property' },
})
```

The `MountOptions` type has `target` (a `Document`, `Element` or `ShadowRoot`), an optional `anchor` node to insert before, `props` (required when the component has required props), `context` (a `Map` readable through `getContext`), `intro` (default `true`: transitions play on the initial render, so pass `intro: false` to suppress them), `transformError` (Chapter 13/14), and a deprecated `events` map. The return value is the component’s **exports** object (what the component exposes with `export function`/`export const`), which doubles as the handle you pass to `unmount`. You can mount several components per page, and mount from inside your app, for example to attach a tooltip to the hovered element.

The most surprising property of `mount` is what it does *not* do. The DOM is built synchronously, but **effects do not run during `mount`**: neither `$effect`, nor `onMount` callbacks, nor action functions. They run in a microtask. I verified this in a Vitest/jsdom test with a counter that logs from `onMount` and `$effect`:

```ts
// lab/mount.test.ts
import { test } from 'vitest'
import { mount, unmount, flushSync } from 'svelte'
import Counter from './Counter.svelte'

test('mount', async () => {
  const app = mount(Counter, { target: document.body, props: { start: 2 } })
  console.log(document.body.innerHTML) // <button>2 / 4</button>   DOM exists
  // effects have NOT run yet: the log array is still empty
  flushSync()
  // now: onMount and the initial $effect have run
  document.querySelector('button')!.click()
  console.log(document.body.innerHTML) // still 2 / 4: the update is batched
  flushSync()
  console.log(document.body.innerHTML) // 3 / 6
  await unmount(app)
  console.log(JSON.stringify(document.body.innerHTML)) // ""
})
```

The output confirmed three things: the markup is in the document immediately after `mount`; the `onMount` callback and first `$effect` ran only after `flushSync()`; and a state change from a click handler is not reflected in the DOM until the pending batch is flushed, either by the microtask or by `flushSync()`.

`flushSync(fn?)` synchronously flushes all pending updates and effects. Use it in tests, and when you must read layout immediately after a change (for example to measure an element). It is not a tool for ordinary application code: it defeats batching, and calling it inside an effect is an error under the experimental async flag. The optional callback form runs `fn` and then flushes. In 5.57.2 the changelog notes that anything pending is flushed before the callback is invoked. The source carries a TODO about removing the callback argument in Svelte 6, so prefer calling `flushSync()` without arguments. Its asynchronous sibling `tick()` returns a promise that resolves once pending state changes have been applied; Chapter 5 explains both in terms of the scheduler.

### `unmount`

```ts
import { mount, unmount } from 'svelte'

const app = mount(App, { target: document.body })
await unmount(app, { outro: true })
```

`unmount` destroys the component, runs teardown functions and `onDestroy` callbacks, and removes its DOM. With `outro: true` (5.13+) it waits for outro transitions and the returned promise resolves afterwards; without it, the promise resolves immediately and DOM removal is synchronous.

### `hydrate`

`hydrate` takes the same kind of arguments as `mount`, but instead of creating nodes it adopts server-rendered HTML in the target and makes it interactive. As with `mount`, effects do not run synchronously. Its `recover` option controls hydration mismatch recovery. Hydration and the matching server `render` function are Chapter 14.

### One root or many

There is no global “app” object. A page can host any number of independent roots, each with its own effect tree. That makes Svelte suitable for sprinkling components into an existing server-rendered page, and it also means that context set in one root is invisible in another unless you pass `context` to `mount`. You can also run `mount` for a component inside a `ShadowRoot` target.

## Tooling

### Editor support

The Svelte team maintains the **Svelte for VS Code** extension (syntax highlighting, diagnostics from the compiler, type checking through the Svelte language server, and component documentation on hover). Integrations exist for other editors. A comment starting with `@component` documents a component for the language server:

````html
<!--
@component
A badge that shows a count.

- Usage:
  ```svelte
  <Badge count={3} />
  ```
-->
````

### Type checking: `svelte-check` and `sv check`

TypeScript’s compiler does not understand `.svelte` files, so the project needs a separate checker. `svelte-check` runs the same language-server logic from the command line and is what the Vite template’s `check` script uses (`svelte-check --tsconfig ./tsconfig.app.json`). The CLI also exposes it as `npx sv check`. Run it in CI: it reports TypeScript errors in `<script lang="ts">`, compiler warnings (including accessibility warnings), and unused CSS selectors, so it catches real problems that `vite build` ignores.

### Formatting and linting

Formatting is done with Prettier and `prettier-plugin-svelte`. Linting uses `eslint-plugin-svelte`; the older `eslint-plugin-svelte3` is deprecated. `sv add prettier` and `sv add eslint` configure both for you.

### Debugging, briefly

Dev builds (`dev: true`, which the Vite plugin sets in serve mode) add runtime checks and richer warnings, such as `ownership_invalid_mutation` and `state_proxy_equality_mismatch`. `$inspect` is dev-only and is a no-op in production builds. Chapter 4 introduces the debugging helpers and Chapter 16 collects them.

## Browser support

The docs give a baseline for Svelte’s own runtime, derived from the browser APIs it uses:

| Browser | Minimum version |
| --- | --- |
| Chrome / Edge | 87 |
| Firefox | 83 |
| Safari | 14 |
| Opera | 73 |
| Opera (Android) | 62 |
| Samsung Internet | 14.0 |
| Android WebView | 87 |
| Internet Explorer | not supported |

This is equivalent to a Baseline 2020 target, and it covers Svelte only: your own code, your libraries, and your bundler’s output may need more. Three features need newer browsers:

| Feature | Chrome/Edge | Firefox | Safari |
| --- | --- | --- | --- |
| `$state.snapshot` | 98 | 94 | 15.4 |
| `bind:devicePixelContentBoxSize` | — | 93 | not supported |
| `flip` from `svelte/animate` | — | 126 | — |

The snapshot requirement comes from its use of `structuredClone`. If you must support older browsers and need snapshots, a `structuredClone` polyfill is the simplest fix; Chapter 3 shows what snapshot does with values it cannot clone.

## Project layout for a framework-less app

Svelte does not impose a structure. These conventions keep a Vite-based SPA easy to reason about, and they are the ones the book’s examples follow.

```text
src/
  main.ts                  entry: mounts <App>
  App.svelte               root component
  app.css                  global styles
  lib/
    components/            presentational components
      Button.svelte
    features/              feature folders: components + logic together
      todos/
        TodoList.svelte
        todos.svelte.ts    reactive domain logic (class or factory)
        todos.test.ts
    shared/                framework-agnostic helpers (plain .ts)
```

Four guidelines go with it.

1.  **Domain logic in `.svelte.ts` modules, UI in `.svelte` files.** A class with `$state` fields can be unit-tested without a DOM (Chapter 16) and reused by several components.
2.  **Plain `.ts` for anything that does not need runes.** Parsing, formatting and API clients stay free of the compiler’s constraints.
3.  **Co-locate by feature, not by file type.** A `components/`, `stores/`, `utils/` split forces you to touch three directories per change.
4.  **Avoid module-level mutable state** unless the app is strictly client-side and single-user. Prefer context (Chapter 12) so the same code is safe if you server-render it later.

TypeScript projects scaffolded by the Vite template have `tsconfig.app.json` extending `@tsconfig/svelte/tsconfig.json`, with `"types": ["svelte", "vite/client"]`. The docs say a Svelte TypeScript setup needs `target` of at least ES2015, `verbatimModuleSyntax: true` and `isolatedModules: true`; `@tsconfig/svelte` provides those. Chapter 15 expands on the options.

### How this book’s examples are organised

Every example is a real file with its path in the first line, as in `// src/lib/counter.svelte.ts`. Examples assume the Vite project above. Two conventions apply throughout:

- “I ran this” statements mean the code was executed against `svelte@5.57.2` under Vitest with jsdom. The reusable lab setup is a few lines:

  ```ts
  // vitest.config.ts
  import { defineConfig } from 'vitest/config'
  import { svelte } from '@sveltejs/vite-plugin-svelte'

  export default defineConfig({
    plugins: [svelte()],
    resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined,
    test: { environment: 'jsdom', include: ['lab/**/*.test.ts'] },
  })
  ```

  The `browser` condition makes Svelte resolve to its client build instead of its server build, which would otherwise ignore effects and throw on `mount`. Chapter 16 explains.

- Compiler output shown in Chapters 2 and 5 comes from `compile()` in 5.57.2. It is illustrative and version-specific: function names such as `$.template_effect` are private.

## A complete first example

To pull the threads together, here is a small but realistic app: a reactive module, a component that uses it, and the entry point.

```ts
// src/lib/todos.svelte.ts
export class Todo {
  text: string
  done = $state(false)

  constructor(text: string) {
    this.text = text
  }

  toggle = () => {
    this.done = !this.done
  }
}

export class TodoList {
  items = $state<Todo[]>([])
  remaining = $derived(this.items.filter((t) => !t.done).length)

  add(text: string) {
    this.items.push(new Todo(text))
  }
}
```

`done` is reactive because it is a `$state` class field; `toggle` is an arrow-function field so `this` is bound when it is passed straight to `onclick`. `items` is a deep proxy, but its elements are class instances, which are not proxied: each `Todo` manages its own reactivity. All of this is explained in Chapter 3.

```html
<!-- src/App.svelte -->
<script lang="ts">
  import { TodoList } from './lib/todos.svelte'

  const list = new TodoList()
  let draft = $state('')

  function submit(event: SubmitEvent) {
    event.preventDefault()
    if (!draft.trim()) return
    list.add(draft.trim())
    draft = ''
  }
</script>

<form onsubmit={submit}>
  <input bind:value={draft} placeholder="What needs doing?" />
  <button>Add</button>
</form>

<ul>
  {#each list.items as todo (todo)}
    <li>
      <label>
        <input type="checkbox" checked={todo.done} onchange={todo.toggle} />
        {todo.text}
      </label>
    </li>
  {/each}
</ul>

<p>{list.remaining} remaining</p>
```

```ts
// src/main.ts
import { mount } from 'svelte'
import App from './App.svelte'

export default mount(App, { target: document.getElementById('app')! })
```

Walk through what executes. When `main.ts` calls `mount`, the `App` function runs once: the script creates the `TodoList` and the `draft` source, then the template creates the DOM. `{list.remaining}` becomes a tiny effect reading the derived value, `{#each}` becomes a block effect keyed by the `Todo` instance, and the checkboxes’ `checked` attributes are effects reading `todo.done`. Clicking a checkbox calls `todo.toggle`, which writes to one source, which marks one derived dirty and one attribute effect dirty, and both update in the next microtask. `App` never runs again. This is the mental model in one trace: **a component is setup code that wires sources to DOM effects, and the wiring is what lives on.**

## Mental model checklist

Before going on, make sure the following are second nature, because everything later builds on them.

1.  A component is a function that runs once. Only `$derived`, `$effect` and template expressions re-run.
2.  Runes are compiler syntax, not values. They cannot be passed around, and they only work in `.svelte`, `.svelte.js` and `.svelte.ts` files.
3.  The compiler processes one file at a time. Cross-file reactivity is achieved by exporting objects (that you mutate) or functions/getters, never reassigned state.
4.  Updates are batched into a microtask. DOM and effects lag behind writes until the flush; `flushSync` and `tick` exist to wait for it.
5.  Runes mode is a per-component decision with inference rules; make it explicit in new projects.
6.  `mount`/`hydrate`/`unmount` are how every Svelte app starts and stops; effects run after them, not during.

## Key takeaways

- Svelte 5 is a compiler plus a small signals runtime. Reactivity is a runtime graph, not a per-component compile-time bitmask, which is why it works across files.
- A component is a function that runs once. State changes update DOM through fine-grained effects; there is no component re-render and no virtual DOM.
- Create a project with `npx sv create` (SvelteKit-oriented) or `npm create vite@latest -- --template svelte-ts` (framework-less). Configure Vite with `svelte()` from `@sveltejs/vite-plugin-svelte` and `compilerOptions`/`preprocess` in `svelte.config.js`. `vitePreprocess` is needed only for non-erasable TypeScript syntax or `<style lang>` preprocessors.
- A `.svelte` file has an instance `<script>` (once per instance), a `<script module>` (once per module), markup and a scoped `<style>`.
- `.svelte.ts` modules enable runes outside components. The compiler works file by file: runes in plain `.ts` files throw `rune_outside_svelte`, and reassigned `$state` cannot be exported (`state_invalid_export`).
- Runes mode versus legacy mode is decided per component by the `runes` option, `<svelte:options runes />`, or inference from rune use or top-level `await`. Force runes mode via `dynamicCompileOptions` or a function-valued `runes` option rather than a blanket `runes: true`, which also affects `node_modules`.
- `mount`, `hydrate` and `unmount` replace `new App()`. Effects do not run synchronously during `mount`; use `flushSync()` in tests and rarely elsewhere.
- Use `svelte-check` / `sv check` in CI, the Svelte VS Code extension in the editor, and Prettier and ESLint plugins for style.
- Svelte’s browser baseline is Baseline 2020, with exceptions for `$state.snapshot`, `bind:devicePixelContentBoxSize` and `flip`.

## Review Questions

1.  In one or two sentences each, explain what the compiler does and what the runtime does in a Svelte 5 application. Why does that split allow reactive state to be shared across files?

2.  What is the difference between how Svelte 4 and Svelte 5 propagate a change in `count` to the DOM? Name the construct that replaced `$$invalidate`.

3.  What does this component print to the console if `{x}` is clicked three times? When does the `console.log` run?

    ```html
    <script lang="ts">
      let x = $state(0)
      console.log('setup', x)
    </script>

    <button onclick={() => x++}>{x}</button>
    ```

4.  List four syntax changes between Svelte 4 and Svelte 5 for (a) local state, (b) props, (c) DOM events and (d) component instantiation.

5.  Which of the following is the framework-less way to create a Svelte 5 project?

    a.  `npx sv create` and ignore the SvelteKit parts
    b.  `npm create vite@latest myapp -- --template svelte-ts`
    c.  `npm install svelte && node build.js`
    d.  `npx create-svelte`

6.  The Vite `svelte-ts` template ships `svelte.config.js` with `export default {}` and no `preprocess`. Why does TypeScript in `<script lang="ts">` still work? Name two situations in which you would add `vitePreprocess`.

7.  Name three top-level keys of the object exported from `svelte.config.js` and say what each does. Which `CompileOptions` keys can you *not* set there, and why?

8.  What is the difference between `<script>` and `<script module>` with respect to (a) when the code runs, (b) what can reference what, (c) whether `export default` is allowed?

9.  A colleague stores `let sessionUser: User | null = null` in a `<script module>` and sets it when a request is handled during server rendering. Explain what can go wrong.

10. Find the bug. The component compiles with a warning. What is the warning and how would you fix it so the label tracks `kind`?

    ```html
    <script lang="ts">
      let { kind }: { kind: 'error' | 'info' } = $props()
      let label = kind === 'error' ? 'Error!' : 'Note'
    </script>

    <strong>{label}</strong>
    ```

11. What happens at runtime if you call this function, and why does the editor not complain?

    ```ts
    // src/lib/util.ts
    export function makeCounter() {
      let n = $state(0)
      return { inc: () => n++ }
    }
    ```

12. What is the minimal change to make the previous module valid? Give the new filename.

13. Why is this module rejected by the compiler, and which two patterns does the documentation offer instead?

    ```ts
    // state.svelte.ts
    export let user = $state<{ name: string } | null>(null)
    export function login(name: string) {
      user = { name }
    }
    ```

14. What does “the compiler sees one file at a time” imply for a function that takes a `$state` variable as an argument, such as `track(count)`? What do you pass instead?

15. Why are runes described as “not values”? Give one thing the compiler would reject because of that.

16. Describe the order of checks the compiler uses to decide between runes and legacy mode. Which of these components is compiled in runes mode when no option is set?

    a.  `<script>let n = 0</script><p>{n}</p>`
    b.  `<p>hello</p>`
    c.  `<script>let n = $state(0)</script><p>{n}</p>`
    d.  `<script>export let a</script><p>{a}</p>`

17. Why is setting `compilerOptions: { runes: true }` in `svelte.config.js` risky, and what two safer mechanisms exist?

18. What does `mount` return, and what type of argument does `unmount` accept?

19. Predict the contents of `log` at each marked point.

    ```ts
    const log: string[] = []
    // Component calls log.push('effect') in $effect and log.push('mount') in onMount
    const app = mount(Comp, { target: document.body })
    // (A)
    flushSync()
    // (B)
    await unmount(app)
    ```

20. When do you use `unmount(app, { outro: true })` and how does the returned promise differ from the default?

21. What is the default of `intro` in `mount`’s options, and what does that mean for a component with a `transition:` on its root element?

22. A user complains that after `button.click()` in a test the DOM still shows the old count. What are two ways to make the test see the update, and how do they differ?

23. Why does the compiled form of your app import from `svelte/internal/client`, yet you may not import that path yourself?

24. Design question: you are structuring a framework-less SPA with five features. Where do you put reactive domain logic, DOM-free helpers and presentational components? What would you change if you later had to server-render the app?

25. Which statement about browser support is correct?

    a.  Svelte’s runtime requires Chrome 98 because of `$state.snapshot`.
    b.  The baseline is Chrome/Edge 87, Firefox 83, Safari 14; `$state.snapshot` needs Chrome 98 / Firefox 94 / Safari 15.4.
    c.  `flip` needs Safari 126.
    d.  Internet Explorer 11 is supported with a polyfill.

26. Why does a Vitest configuration for component tests include `resolve: { conditions: ['browser'] }`? What would happen without it?
