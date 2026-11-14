# Chapter 2: The Compiler — From `.svelte` to JavaScript

Svelte’s compiler is the part of the framework you never import in application code and yet the part that defines the language you write. It decides which variables become signals, which template expressions become effects, which event listeners are delegated, which CSS selectors survive, and which mistakes are rejected before the code ever runs. This chapter opens the box. You will see the pipeline, read real compiler output for the same counter on the client and the server, learn the optimisations that make Svelte’s generated code small, and then go through the complete public API of `svelte/compiler` and every `CompileOptions` field. We finish with preprocessors, the diagnostic system, and a small tool built directly on the parser.

> **Warning:** Everything shown as “compiler output” in this book was produced by `compile()` from `svelte@5.57.2`. It is illustrative. The helper names (`$.state`, `$.template_effect`, `$.from_html`, …) belong to a private runtime contract between the compiler and `svelte/internal/client`. They can and do change in minor and patch releases, and you must not write code that depends on them. The public contract is the source language, the options, and the exports of `svelte/compiler`.

## The pipeline

`compile(source, options)` runs four stages in one synchronous call.

1.  **Parse.** The source string is split into the instance script, the module script, the `<style>` element and the markup. JavaScript inside scripts and expressions is parsed with Acorn (with TypeScript support when `lang="ts"` is present; type-only syntax is removed in this stage). Markup is parsed into a Svelte AST: `Root` with a `fragment` of `Text`, `RegularElement`, `Component`, `IfBlock`, `EachBlock`, `ExpressionTag`, and so on. CSS is parsed into its own tree.
2.  **Analyze.** The compiler builds scopes and bindings, decides whether the component is in runes or legacy mode, validates rune placement, determines for each declaration whether it is ever reassigned or mutated, analyses which CSS selectors can match which elements (this is where `css_unused_selector` comes from), and collects warnings (accessibility, `state_referenced_locally`, and so on).
3.  **Transform.** One of two transforms runs depending on `generate`: the *client* transform (DOM creation, signals, effects) or the *server* transform (string concatenation for SSR). A separate CSS transform scopes selectors and prints the stylesheet.
4.  **Print.** The resulting ESTree is printed to a string with a source map.

The directory layout of the package mirrors this: `src/compiler/phases/1-parse`, `2-analyze`, and `3-transform/{client,server,css}`. If you ever need to know *why* a diagnostic is raised, grep `phases/2-analyze` in `node_modules/svelte`; the code is readable.

Two consequences are worth stating up front. First, analysis is *per file*: it sees your component and the modules it imports only as opaque identifiers. This is the root of the cross-module rules we examine at the end of the chapter. Second, the output is not a class. A compiled client component is an ordinary function taking an anchor node (and, if it needs them, the props), and a compiled server component is a function taking a renderer.

## Reading real compiler output

We will use the following component, saved as `Counter.svelte`:

```html
<script lang="ts">
  let count = $state(0);
  let doubled = $derived(count * 2);
</script>

<button onclick={() => count++}>
  {count} / {doubled}
</button>

<style>
  button { color: tomato; }
</style>
```

The following script compiles it for both targets. You can run it in any Node 18+ project that has `svelte@5.57.2` installed:

```js
// compile-demo.mjs
import { readFileSync } from 'node:fs';
import { compile } from 'svelte/compiler';

const source = readFileSync('Counter.svelte', 'utf8');

const client = compile(source, { filename: 'Counter.svelte', generate: 'client' });
console.log(client.js.code);
console.log(client.css?.code);

const server = compile(source, { filename: 'Counter.svelte', generate: 'server' });
console.log(server.js.code);
```

### The client output

```js
import 'svelte/internal/disclose-version';
import * as $ from 'svelte/internal/client';

var root = $.from_html(`<button class="svelte-xo0eto"> </button>`);

export default function Counter($$anchor) {
    let count = $.state(0);
    let doubled = $.derived(() => $.get(count) * 2);
    var button = root();
    var text = $.only_child(button);

    $.template_effect(() => $.set_text(text, `${$.get(count) ?? ''} / ${$.get(doubled) ?? ''}`));
    $.delegated('click', button, () => $.update(count));
    $.append($$anchor, button);
}

$.delegate(['click']);
```

Read it top to bottom; there are only seven ideas.

1.  **`import 'svelte/internal/disclose-version'`** registers the Svelte major version in a global `Set` (`window.__svelte.v`), which is what the `discloseVersion` option controls.
2.  **`var root = $.from_html(...)`** runs *once per module*. It holds the static HTML of the template as a string and lazily creates a `<template>` element from it. Every component instance gets its DOM by cloning that template (`root()`), which is a single native `cloneNode(true)` call. The text node placeholder inside the button is a single space (`<button> </button>`) because the text content will be filled in at runtime. The scoped class `svelte-xo0eto` is baked into the static markup.
3.  **The function `Counter($$anchor)`** is the component. It is called once per instance. The parameter `$$anchor` is the DOM node (or comment) before which this component’s DOM will be inserted. Notice what is *not* there: no props parameter, no `$.push`/`$.pop`, because this component takes no props and uses no context or lifecycle. Add a prop and the signature becomes `Counter($$anchor, $$props)`.
4.  **`$.state(0)` and `$.derived(() => ...)`** create a source and a derived. Every read of a reassigned or mutated state variable has been rewritten to `$.get(count)`, and `count++` has become `$.update(count)`. These two rewrites are what make `let count = $state(0)` look like a plain variable in your code.
5.  **`var text = $.only_child(button)`** walks to the DOM node that will receive the text. Walking is done once at creation time by direct property access (`firstChild`, `nextSibling`), not by querying.
6.  **`$.template_effect(() => $.set_text(text, ...))`** is the heart of fine-grained updates. The arrow function reads `count` and `doubled`; the runtime runs it once immediately, records those reads as dependencies, and re-runs it when either changes. `set_text` only touches the DOM when the string actually differs from the previous one. This single call is the replacement of the “update” method of a Svelte 4 component. Chapter 5 dissects how it executes.
7.  **`$.delegated('click', button, handler)` plus `$.delegate(['click'])`** registers an event handler without calling `addEventListener` on the button. More on this below.

The final call, `$.append($$anchor, button)`, inserts the cloned DOM. When `mount` calls this function, the DOM is created and inserted synchronously, and the effects are queued, which is why the DOM is present right after `mount(...)` while `onMount` and `$effect` callbacks wait for the flush (Chapter 1).

### The CSS output

```css
button.svelte-xo0eto { color: tomato; }
```

Every selector gets the hash class appended, and the same class was added to the `<button>` in the template. `result.css.hasGlobal` is `false` here (added in 5.26); it is `true` if any rule was wrapped in `:global`, which bundler plugins use to decide how to treat the stylesheet.

### The server output

```js
import * as $ from 'svelte/internal/server';

export default function Counter($$renderer) {
    let count = 0;
    let doubled = $.derived(() => count * 2);

    $$renderer.push(`<button class="svelte-xo0eto">${$.escape(count)} / ${$.escape(doubled())}</button>`);
}
```

The server transform is far simpler, and the differences are instructive:

- `$state(0)` became a plain `let count = 0`. There is no reactivity on the server: one render, one pass.
- `$derived` is kept as a memoised function, called as `doubled()`.
- The event handler is gone (the server never runs it), and there is no hydration code. The markup is a template string with `$.escape(...)` around dynamic values, which is where HTML escaping happens.
- Effects, `onMount` and actions do not appear at all; `onDestroy` is the only lifecycle function that runs on the server.

When a component has hydration-relevant structure, the server output also emits comment markers (Chapter 14), which is why you must not strip comments from server-rendered HTML.

### The dev build

Compile with `dev: true` and the same component grows by roughly 50% (828 versus 537 characters in my run), because the compiler adds checks and names:

```js
Counter[$.FILENAME] = 'Counter.svelte';
var root = $.add_locations($.from_html(`<button class="svelte-xo0eto"> </button>`), Counter[$.FILENAME], [[6, 0]]);

export default function Counter($$anchor, $$props) {
    $.check_target(new.target);
    $.push($$props, true, Counter);

    let count = $.tag($.state(0), 'count');
    let doubled = $.tag($.derived(() => $.get(count) * 2), 'doubled');
    var $$exports = { ...$.legacy_api() };
    ...
    return $.pop($$exports);
}
```

`$.tag` attaches the *source variable name* to each signal so `$inspect.trace` and the devtools can print `count` instead of an anonymous signal; `$.add_locations` records source locations of template nodes for dev-time diagnostics; `$.check_target` makes `new Counter()` throw a helpful error; `$.push`/`$.pop` maintain the component context used for ownership checks (Chapter 3). None of this exists in production output. When you benchmark, always benchmark a production build.

## What the compiler optimises

The generated code is small because the compiler does as much as it can at build time. Here are the main techniques, each verified with `compile()`.

### State that never changes is not a signal

```html
<script>
  let n = $state(1);
  let o = $state({ a: 1 });
</script>
<p>{n} {o.a}</p>
```

compiles to:

```js
let n = 1;
let o = $.proxy({ a: 1 });
...
$.template_effect(() => $.set_text(text, `1 ${o.a ?? ''}`));
```

The compiler knows `n` is never reassigned in this file, so it is not a source at all: it is a plain variable, and its value was even inlined into the template string. The object state remains a `$.proxy(...)` (proxies are created for any `$state` holding an object or array, because the compiler cannot prove nobody mutates a property), but the proxy itself is not wrapped in a signal because `o` is never reassigned.

This is the optimisation behind the guidance in the best-practices page: “Only use the `$state` rune for variables that should be reactive… Everything else can be a normal variable”. Using `$state` for something you never reassign costs nothing for primitives but is also useless; the compiler will warn when you do the opposite and forget it (`non_reactive_update`: “`%name%` is updated, but is not declared with `$state(...)`”).

### Static attributes and partial evaluation

```html
<script>
  const w = 3;
  const cls = 'big';
</script>
<div class="box {cls}" data-x={w * 2} title="a{'b'}c">{w + 1} items</div>
```

compiles to:

```js
var root = $.from_html(`<div></div>`);

export default function A($$anchor) {
    const w = 3;
    const cls = 'big';
    var div = root();

    $.set_class(div, 1, 'box big');
    $.set_attribute(div, 'data-x', w * 2);
    $.set_attribute(div, 'title', 'abc');
    div.textContent = '4 items';
    $.append($$anchor, div);
}
```

Three things happened. The class value `'box big'` and the title `'abc'` were *partially evaluated*: the compiler resolved `{cls}` and `{'b'}` to their known constant values and concatenated them, so there is no template effect at all. The text content `{w + 1} items` was evaluated to the string `'4 items'` and assigned once. And `w * 2` in the attribute was left as an expression (it is still assigned once, not in an effect, because nothing reactive is involved). Partial evaluation was introduced in 5.27 and extended in 5.28; the precise set of expressions it can fold grows over time, which is why you should not rely on any particular expression being folded. What you can rely on is the principle: *an expression that reads no reactive value costs no effect*.

Compare that with the `{count}` in our counter, where the reads of `$.get(count)` force a `$.template_effect`.

### Template cloning: `fragments: 'html' | 'tree'`

By default (`fragments: 'html'`) the static structure of a template is stored as an HTML string and cloned from a `<template>` element:

```js
var root = $.from_html(`<div class="a"><span>hi</span></div>`);
```

Creating the `<template>` from `innerHTML` once and cloning it per instance is the fastest way browsers offer to build a static subtree. The cost is compatibility: it does not work under a Content Security Policy that includes `require-trusted-types-for 'script'`, because assigning a string to `innerHTML` is a Trusted Types sink. The alternative `fragments: 'tree'` (5.33) builds the structure with `createElement` calls and then clones:

```js
var root = $.from_tree([['div', { class: 'a' }, ['span', null, 'hi']]]);
```

It is slower to create the first instance and larger in the bundle, but works under strict policies. Chapter 14 returns to CSP and Trusted Types.

### Dynamic parts: blocks and attributes

Blocks compile into calls that receive an anchor and a callback that renders the branch. For `{#if show}{#each items as i (i)}<li>{i}</li>{/each}{/if}` the output (trimmed) is:

```js
$.if(node, ($$render) => {
    if (show) $$render(consequent);
});
...
$.each(node_1, 16, () => items, (i) => i, ($$anchor, i) => {
    var li = root();
    var text = $.only_child(li, true);
    $.template_effect(() => $.set_text(text, i));
    $.append($$anchor, li);
});
```

The numeric `16` is a bit flag describing the each block (keyed, whether the item is reactive, whether an index is needed, …). Here `show` is never reassigned in this component, so the condition is a plain variable read, not `$.get(show)`. Chapter 5 explains how `$.if` and `$.each` own the effects of their branches.

Props are read lazily, as the third example shows (`let { a, ...rest } = $props()`):

```js
var rest_excludes = new Set(['$$slots', '$$events', '$$legacy', 'a']);

export default function C($$anchor, $$props) {
    let rest = $.rest_props($$props, rest_excludes);
    var p = root();

    $.attribute_effect(p, () => ({ ...rest }));
    var text = $.only_child(p, true);
    $.template_effect(() => $.set_text(text, $$props.a));
    $.append($$anchor, p);
}
```

The destructured `a` does not exist as a variable. Each use in the template becomes `$$props.a`, read inside the effect, so a changed prop re-runs only that one text effect. The spread attribute becomes `$.attribute_effect`, which re-applies all attributes of the object when it changes. Because reading `$$props.a` goes through a getter defined by the parent, “a prop is always the current value of whatever the parent passed”, which is the reason `let color = type === 'danger' ? ...` captured at the top of the script goes stale.

### Event delegation in generated code

Look again at how three handlers on one element compile:

```html
<button onclick={a} onfocus={b} onmouseenter={c}>x</button>
```

```js
$.delegated('click', button, a);
$.event('focus', button, b);
$.event('mouseenter', button, c);
...
$.delegate(['click']);
```

`click` is a *delegated* event: instead of calling `button.addEventListener('click', ...)`, the runtime stores the handler on the element under a private property, and a single listener per event type sits on the root of the mount target (and `document`). When a click bubbles up, the runtime walks the composed path and invokes the stored handlers in order. `focus` and `mouseenter` do not bubble, so they use a normal `$.event` listener. The module-level `$.delegate(['click'])` records which event types this module needs delegated, so the root listener is installed on first use.

The set of delegated events is fixed (from the docs): `beforeinput`, `click`, `change`, `dblclick`, `contextmenu`, `focusin`, `focusout`, `input`, `keydown`, `keyup`, `mousedown`, `mousemove`, `mouseout`, `mouseover`, `mouseup`, `pointerdown`, `pointermove`, `pointerout`, `pointerover`, `pointerup`, `touchend`, `touchmove`, `touchstart`. The benefits are fewer listeners and cheaper element creation, which pays off in long lists. The costs are behavioural, and Chapter 6 covers them: a manual `addEventListener` that calls `stopPropagation` can prevent delegated handlers from running, manually dispatched events need `bubbles: true`, and relative order against handlers added with `addEventListener` differs (use `on` from `svelte/events` to preserve it).

### Reading `$state` across effects: the async variant

When `experimental.async` is enabled, derived expressions containing `await` compile to a different shape. This is a taste (details in Chapter 13):

```html
<script>
  let id = $state(1);
  let user = $derived(await fetch('/u/' + id));
</script>
<p>{await user}</p>
```

```js
import 'svelte/internal/flags/async';
...
var $$promises = $.run([
    async () => user = await $.async_derived(() => fetch('/u/' + id))
]);
...
$.template_effect(($0) => $.set_text(text, $0), void 0, [() => $.get(user)], [$$promises[0]]);
```

The compiler turns the `await` into an `async_derived` and sequences the dependent template effect after the promise. Note that `id` appears as a plain `id` here: it was never reassigned in this file, so it is not even a signal. Without the flag, the same source is a compile error (`experimental_async`).

## The public API of `svelte/compiler`

The module exports a handful of functions and types. The declarations below are taken from `types/index.d.ts` in the package.

| Export | Signature | Since |
|------------------------|------------------------|------------------------|
| `compile` | `(source: string, options: CompileOptions) => CompileResult` | 3 |
| `compileModule` | `(source: string, options: ModuleCompileOptions) => CompileResult` | 5 |
| `parse` | `(source, { filename?, modern?, loose? }) => AST.Root` (modern) or `Record<string, any>` (legacy) | 3 |
| `parseCss` | `(source: string) => AST.CSS.StyleSheetFile` | 5.48 |
| `print` | `(ast: AST.SvelteNode, options?) => { code: string; map: any }` | 5.45 |
| `preprocess` | `(source, group \| group[], { filename? }) => Promise<Processed>` | 3 |
| `migrate` | `(source, { filename?, use_ts? }) => { code: string }` | 5 |
| `VERSION` | `string` | 3 |
| `walk` | deprecated stub that throws; import from `estree-walker` | removed |

### `compile`

`compile` takes a component’s source and returns a `CompileResult`:

```ts
interface CompileResult {
  js:   { code: string; map: SourceMap };
  css:  null | { code: string; map: SourceMap; hasGlobal: boolean };
  warnings: Warning[];
  metadata: { runes: boolean };
  ast: any;
}
```

`css` is `null` when there is no `<style>` or when styles are injected through JavaScript (`css: 'injected'`). `metadata.runes` tells you which mode the component ended up in. `ast` is the parsed tree (legacy shape unless `modernAst: true`). `generate: false` skips code generation entirely: in my run `js` was `null` and the warnings array was still populated, which is what linters and editors use.

### `compileModule`

`compileModule` compiles `.svelte.js`/`.svelte.ts` content (JavaScript with runes). The module is always in runes mode. Since 5.37 it ignores component-only options. Using the earlier example:

```js
compileModule(`export const c = $state({ n: 0 }); export function inc() { c.n++ }`,
  { filename: 'x.svelte.js' }).js.code
```

```js
import * as $ from 'svelte/internal/client';

export const c = $.proxy({ n: 0 });

export function inc() {
    c.n++;
}
```

And a private reassigned state with an exported accessor:

```js
let n = $.state(0);

export const get = () => $.get(n);
export const inc = () => $.update(n);
```

Compare these two outputs with the documentation’s explanation of why `export let count = $state(0)` is forbidden. In the second, `n` is a signal object and every reference is wrapped. If another module imported `n` directly, it would receive the signal object, and `n + 1` would be `[object Object]1`. The compiler cannot see the importing file, so the only safe rule is to refuse. The first form is allowed because `c` is never reassigned: it is a proxy, the importer receives the proxy, and property accesses on it are reactive by themselves.

### `parse`

```ts
import { parse } from 'svelte/compiler';

const ast = parse(source, { modern: true, filename: 'A.svelte' });
```

With `modern: true` you get an `AST.Root` with these keys (in my run): `type: 'Root'`, `start`, `end`, `fragment` (a `Fragment` whose `nodes` hold the template), `options` (inline `<svelte:options>`), `css`, `instance`, `module` and `comments`. For the example component, `ast.fragment.nodes.map(n => n.type)` returned `['Text', 'RegularElement', 'Text', 'IfBlock', 'Text']`. The default (legacy) AST has different keys (`html`, `instance`, `module`, `css`); `modern` becomes the default in Svelte 6 and the option is removed in Svelte 7, so new tools should always pass `modern: true`. The `loose` option makes the parser tolerant of unclosed tags and incomplete expressions, which is what language servers need while you type.

### `parseCss`

`parseCss(source)` parses a plain stylesheet into an `AST.CSS.StyleSheetFile` with `children` made of `Rule` and `Atrule` nodes (including nested rules). For `'a { color: red; &:hover { color: blue } } @media (min-width:1px){ b{x:y} }'` the top-level children were `Rule` and `Atrule` (`media`).

### `print`

`print(node, options?)` converts a *modern* AST node back to Svelte source and returns `{ code, map }`. The output is valid Svelte but formatting may change (whitespace, quoting): in my run it re-indented the script with tabs and reformatted `<style>` as a multi-line rule. `print` accepts any sub-node of a modern tree, so codemods can parse, mutate nodes and print without a custom serializer. Pair it with `parse(..., { modern: true })`; legacy ASTs are not supported.

### `preprocess`

`preprocess` runs preprocessors over a source string, returning a `Processed` object (`code`, optional `map`, `dependencies`). It is described in its own section below.

### `migrate`

`migrate(source, { filename?, use_ts? })` performs the best-effort conversion to runes, event attributes and render tags that `npx sv migrate svelte-5` applies. On this input:

```html
<script>
 export let a = 1;
 let b = 2;
 $: c = a + b;
</script>
<button on:click={() => b++}>{c}</button>
```

it returned (whitespace as emitted):

```html
<script>
    /**
     * @typedef {Object} Props
     * @property {number} [a]
     */

    /** @type {Props} */
    let { a = 1 } = $props();
 let b = $state(2);
 let c = $derived(a + b);
</script>
<button onclick={() => b++}>{c}</button>
```

It may throw for code that is too complex to migrate automatically. Chapter 20 discusses what it leaves for you.

### `VERSION`

`VERSION` is the string from `package.json` (here `5.57.2`). Tooling uses it to branch on features.

### `walk`

`walk` used to be re-exported from the compiler and now throws, with a deprecation note: replace it with `import { walk } from 'estree-walker'`. The estree-walker package visits nodes by their `type` property, so it works on Svelte’s modern AST as well as on ESTree nodes embedded in it. We use it in the toy tool below.

## `CompileOptions` in full

`CompileOptions` extends `ModuleCompileOptions`. The tables mark what I verified by compiling with the option.

### Options shared with `compileModule`

| Option | Type | Default | Behaviour |
|------------------|------------------|------------------|------------------|
| `dev` | `boolean` | `false` | Adds runtime checks and debugging information (the dev build above). Bundler plugins set it for dev servers. |
| `generate` | `'client' \| 'server' \| false` | `'client'` | Target. `false` produces no code (warnings only). |
| `filename` | `string` |  | Used for debugging hints, source maps, the CSS hash and `$.FILENAME`. The plugin sets it. |
| `rootDir` | `string` | `process.cwd()` on Node-like environments | Used so file names in output do not leak filesystem paths. |
| `warningFilter` | `(warning) => boolean` |  | Return `true` to keep a warning, `false` to discard it. |
| `experimental.async` | `boolean` | `false` | Allows `await` in deriveds, template expressions and at the top level of components (since 5.36). Chapter 13. |

Note `generate`: Svelte 4 used `'dom'` and `'ssr'`; the 5.x names are `'client'` and `'server'`, and there is a warning (`options_renamed_ssr_dom`) for the old values.

### Component options

| Option | Type | Default | Behaviour |
|------------------|------------------|------------------|------------------|
| `name` | `string` | inferred from `filename` | Name of the generated function. In my run `name: 'Foo'` produced `export default function Foo(...)`. Renamed if it collides with a variable in scope. |
| `customElement` | `boolean \| ({ filename }) => boolean` | `false` | Generate a custom element constructor. The function form (5.54) lets you decide per file. With `true`, the output contained `$.create_custom_element(A, {}, [], [], { mode: 'open' })`. Chapter 19. |
| `namespace` | `'html' \| 'svg' \| 'mathml'` | `'html'` | The namespace of the root elements. `<svelte:options namespace>` overrides it per component. (`foreign` was removed in 5.) |
| `css` | `'injected' \| 'external' \| ({ filename }) => ...` | see below | `'injected'` bakes the CSS into the JS: SSR emits a `<style>` in `head`, the client injects it when the component mounts (output contained `const $$css = ...` and `$.append_styles($$anchor, $$css)`). `'external'` returns the CSS in `result.css` for the bundler to emit as a file. Always `'injected'` for custom elements. The function form arrived in 5.54. The old `true`, `false` and `'none'` are gone. |
| `cssHash` | `({ hash, css, name, filename }) => string` | `svelte-${hash(filename ?? css)}` | Produces the scoping class. In my run, a function returning `` `x-${name}-${hash(filename)}` `` produced `.a.x-A-11xo9hp{...}`. |
| `preserveComments` | `boolean` | `false` | Keep HTML comments in the generated template. |
| `preserveWhitespace` | `boolean` | `false` | Keep whitespace as typed, instead of collapsing it. Without it, my test’s `<div class="a"> hello <b>x</b>\n </div>` became `<div class="a svelte-...">hello <b>x</b></div>`. |
| `fragments` | `'html' \| 'tree'` | `'html'` | Template cloning strategy (5.33); see above. |
| `runes` | `boolean \| undefined \| ({ filename }) => boolean \| undefined` | `undefined` | Force or infer runes mode; function form 5.54. |
| `discloseVersion` | `boolean` | `true` | Adds the Svelte major version to `window.__svelte.v`. With `false` the `svelte/internal/disclose-version` import disappears. |
| `hmr` | `boolean` | `false` | Emit hot module replacement support (the output referenced `import.meta.hot`). Normally set by the plugin in dev. |
| `modernAst` | `boolean` | `false` | Return the modern AST in `result.ast`. |
| `sourcemap` | `object \| string` |  | An initial source map (usually from preprocessors) merged into the output map. |
| `outputFilename`, `cssOutputFilename` | `string` |  | Used for the JS and CSS source maps. |

The `css` default needs a remark. The types document `'injected'` and `'external'` without stating a default, and say that most bundler plugins set `'external'`. When I called `compile()` with no `css` option, `result.css` was populated, i.e. external behaviour. Chapter 10 discusses the trade-offs of injected CSS.

### Deprecated options

| Option | Notes |
|------------------------------------|------------------------------------|
| `accessors` | No effect in runes mode. Defaults to `true` for custom elements. |
| `immutable` | No effect in runes mode. |
| `compatibility.componentApi` | `4` makes the default export instantiable as `new Component({ target })` (client; uses `createClassComponent` from `svelte/legacy`, plus `$set` and `$on`) or as an object with `.render()` (server). Default `5`. |

Options that were *removed* in version 5 and produce errors or warnings when passed: `hydratable` (components are always hydratable), `enableSourcemap` (maps are always generated), `tag` (use `<svelte:options customElement="tag-name" />`), `loopGuardTimeout`, `format`, `sveltePath`, `errorMode`, `varsReport`; and `legacy` was repurposed.

### Component-level overrides

A component can override some options for itself with `<svelte:options>`: `runes`, `namespace`, `customElement`, `css="injected"`, `preserveWhitespace`, and the deprecated `immutable` and `accessors`. They win over the options passed to `compile`. Content inside `<svelte:options>` is an error.

### Setting options through Vite

In a Vite project the options reach the compiler through the plugin:

```js
// svelte.config.js
export default {
  compilerOptions: {
    discloseVersion: false,
    experimental: { async: true },
  },
  onwarn(warning, defaultHandler) {
    if (warning.code === 'a11y_autofocus') return;
    defaultHandler(warning);
  },
};
```

`compilerOptions` is typed as `CompileOptions` minus `filename`, `format` and `generate`. Warnings can also be filtered with `warningFilter` or per component with `<!-- svelte-ignore ... -->`, discussed below. Per-file decisions (such as forcing runes mode only for your own source) go in the plugin’s `dynamicCompileOptions`.

## Preprocessors

A preprocessor is a function that transforms the *source text* of a `.svelte` file before the compiler sees it. Think of them as build-time macros: `<style lang="scss">` to CSS, `<script lang="ts">` to JavaScript (for the non-erasable features), markdown or i18n replacement in markup.

```ts
interface PreprocessorGroup {
  name?: string;       // required in the next major
  markup?: MarkupPreprocessor;   // ({ content, filename }) => Processed | void | Promise<...>
  style?:  Preprocessor;         // ({ content, attributes, markup, filename }) => ...
  script?: Preprocessor;         // same shape
}

interface Processed {
  code: string;
  map?: string | object;
  dependencies?: string[];       // files to watch
  attributes?: Record<string, string | boolean>;  // script/style only
}
```

`markup` receives the whole file. `script` and `style` receive the contents of every `<script>`/`<style>` tag (instance and module scripts) along with the tag’s attributes and the whole markup.

### Ordering rules

Preprocess runs the groups in the array order, and within each group in the order **markup, script, style**. I logged calls from two groups to confirm:

```text
one:markup, one:script, one:style {"lang":"x"},
two:markup, two:script, two:style {}
```

So the second group’s `style` preprocessor sees the output of the first group’s style step (here: `attributes` had been reset by the first group). Because later groups see earlier output, order matters when one transformation produces input for another: for instance, a markup preprocessor that injects `<style lang="scss">` blocks must come before the SCSS group.

`name` is optional today but will be required in the next major version; give every group a name now, since the name shows up in error messages.

### Attributes: a trap

`Processed.attributes` replaces the attributes written on the tag. If you return the same object with a key set to `undefined` hoping to remove `lang`, the compiler writes `lang="undefined"`; I hit this in testing. To drop an attribute, return a new object without it (an empty object `{}` removed `lang="x"` in my test).

```ts
// A tiny style preprocessor
import { preprocess } from 'svelte/compiler';

const out = await preprocess(
  `<script>let a = 1</script><style lang="x">p{B}</style><p>{a}</p>`,
  [{
    name: 'b-to-c',
    style: ({ content }) => ({
      code: content.replace('B', 'C'),
      attributes: {},          // removes lang="x"
    }),
  }],
  { filename: 'A.svelte' }
);
console.log(out.code);
// <script>let a=1</script><style>p{C}</style><p>{a}</p>
```

### `vitePreprocess`

`vitePreprocess` from `@sveltejs/vite-plugin-svelte` is a ready-made group (`vitePreprocess(opts?)`) that delegates `<style lang="...">` to Vite’s CSS pipeline (so Sass, Less, PostCSS and others work with Vite’s own config) and, with `{ script: true }`, transpiles TypeScript with Vite’s esbuild-based transform. As covered in Chapter 1, you do not need it for type-only TypeScript. With non-Vite bundlers, the docs point to `svelte-preprocess`.

> **Senior tip:** Preprocessors operate on text and lose context: a TypeScript preprocessor sees only the script, not the markup’s use of the variables. That is one reason Svelte 5 parses TypeScript natively. Prefer native syntax over preprocessors whenever the language allows it, and keep any markup preprocessor to mechanical rewrites.

## Diagnostics: errors and warnings

The compiler reports problems in two forms. **Errors** are thrown as `CompileError` exceptions; compilation stops. **Warnings** are collected in `result.warnings` and compilation continues. Both share the shape of `ICompileDiagnostic`:

```ts
{
  code: string;                // e.g. 'state_referenced_locally'
  message: string;             // includes a https://svelte.dev/e/<code> link
  stack?: string;
  filename?: string;
  start?: { line: number; column: number; character: number };
  end?: { line: number; column: number; character: number };
  position?: [number, number];
  frame?: string;              // a code excerpt with a caret
}
```

A real error from `<script>$effect(() => {}); const a = $effect(() => {});</script>`:

```json
{
  "name": "CompileError",
  "code": "effect_invalid_placement",
  "message": "`$effect()` can only be used as an expression statement\nhttps://svelte.dev/e/effect_invalid_placement",
  "start": { "line": 1, "column": 37, "character": 37 },
  "end":   { "line": 1, "column": 54, "character": 54 },
  "position": [37, 54],
  "filename": "A.svelte",
  "frame": "1: <script>$effect(() => {}); const a = $effect(() => {});</script>\n                                                         ^"
}
```

Codes are lower-case with underscores (Svelte 4 used dashes) and every code has a page at `https://svelte.dev/e/<code>`.

### Rune placement errors

The compiler enforces where each rune can appear. The ones you will meet most often:

| Code | Message (abridged) | Cause |
|------------------------|------------------------|------------------------|
| `state_invalid_placement` | `$state(...)` can only be used as a variable declaration initializer, a class field declaration, or the first assignment to a class field at the top level of the constructor | `$state` inside an expression or call argument |
| `effect_invalid_placement` | `$effect()` can only be used as an expression statement | `const x = $effect(...)` |
| `rune_missing_parentheses` | Cannot use rune without parentheses | `let a = $state;` |
| `rune_invalid_arguments_length` | `$state` must be called with zero or one arguments | `$state(1, 2)` |
| `rune_invalid_arguments` | `%rune%` cannot be called with arguments | e.g. `$effect.tracking(1)` |
| `rune_invalid_computed_property` | Cannot access a computed property of a rune | `$state['raw']` |
| `rune_invalid_spread` | `%rune%` cannot be called with a spread argument | `$state(...xs)` |
| `rune_invalid_usage` | Cannot use `%rune%` rune in non-runes mode | a rune used where runes mode is not active |
| `rune_removed` / `rune_renamed` | The `%name%` rune has been removed / `%name%` is now `%replacement%` | `$state.frozen` gave `rune_renamed` in my run |
| `rune_invalid_name` | `%name%` is not a valid rune | `$derived.call(...)` (the old name of `$derived.by`) |
| `props_invalid_placement`, `props_id_invalid_placement`, `bindable_invalid_location`, `host_invalid_placement`, `inspect_trace_invalid_placement` | placement rules for the other runes |  |
| `state_invalid_export`, `derived_invalid_export` | reassigned `$state` or any `$derived` cannot be exported from a module |  |
| `state_field_invalid_assignment`, `state_field_duplicate` | class field problems | assigning a state field before its declaration |
| `experimental_async` | `await` without the flag |  |
| `import_svelte_internal_forbidden` | Imports of `svelte/internal/*` are forbidden | importing internals from a runes-mode component |

In my test, `import { x } from 'svelte/internal/client'` compiled silently in a component with no runes: the check lives in the runes-mode `ImportDeclaration` visitor. Do not read that as permission; the point stands that these modules are private.

The reason placement rules are so strict is that the compiler rewrites each rune *statically*. `$state(0)` must be a declaration initializer because the compiler needs to know the variable that will be wrapped in `$.get`/`$.set`. `$effect(...)` must be a statement because its return value is not a value at all.

### Ignoring and filtering warnings

Three mechanisms, from narrow to broad.

```html
<script lang="ts">
  let { initial } = $props();

  // svelte-ignore state_referenced_locally (we only want the initial value)
  let count = $state(initial);
</script>
```

The comment form `<!-- svelte-ignore code1, code2 (reason) -->` (or `// svelte-ignore ...` inside script) silences the listed codes for the next node. I confirmed it suppressed `state_referenced_locally`. Next, the `warningFilter` option (return `true` to keep) applies per `compile` call and also works from the plugin config; I confirmed it removed the same warning. Finally, the plugin’s `onwarn(warning, defaultHandler)` processes warnings emitted during builds, where you can log, filter, or turn them into errors in CI. A policy that works well: fail the build on all warnings, and require `svelte-ignore` comments to carry a reason.

### The warnings you will see most

- `state_referenced_locally`: “This reference only captures the initial value of `%name%`. Did you mean to reference it inside a %type% instead?” Reading reactive state (or a prop) at the top level of the script captures one value.
- `non_reactive_update`: a variable that is reassigned but not declared with `$state` and is used in the template.
- `css_unused_selector`: the selector matches nothing in the template. In my test `.y{color:red}` with no `.y` element produced `Unused CSS selector ".y"`, with position information. The selector is removed from the output (it cannot be kept: the FAQ explains that the alternatives are “keep it without scoping” and “keep it scoped but never match”).
- `perf_avoid_inline_class` and `perf_avoid_nested_class`: declaring a class with `new class {...}` or below the top level of a script. They hint at repeatedly creating class definitions.
- `attribute_quoted`: quoted single-expression attributes on components/custom elements will be stringified in a future version.
- The `a11y_*` family (Chapter 17), and `legacy_*`/`*_deprecated` warnings for old syntax (Chapter 20).

## What the compiler cannot know

The compiler’s view is one file at a time. This has four practical consequences.

**Cross-module state.** As the `compileModule` outputs showed, whether a variable is a signal is a property of the file that declares it. A variable that is reassigned becomes a signal; that decision cannot be seen by importers, so reassigned state cannot be exported. A variable that is only mutated is a proxy with no wrapping signal, so exporting it is fine. By the same logic exported `$derived` is rejected (`derived_invalid_export`), because the derived value is accessed by calling a function internally.

**Passing runes through functions.** `track(count)` passes a number, not the variable. At the call site the compiler can see `count` is a state variable and rewrites it to `$.get(count)`, yielding a value. If `track` wanted to observe the signal itself, it would need a getter:

```ts
function track(read: () => number) { /* call read() inside an effect */ }
track(() => count);
```

**Dynamic access.** The compiler cannot see through `obj[name]` or through values returned from functions, so it cannot tell whether a prop or an element is used. This is why unused-selector analysis stops at component boundaries (use `:global` for content you cannot see) and why you cannot rely on the compiler to eliminate unused props.

**Other files’ components.** When `<Child />` appears, the compiler knows only that `Child` is an imported binding. It does not know what props `Child` declares or whether `Child` uses runes. That is why runes-mode and legacy-mode components interoperate: the contract is the props object at runtime. Type checking across components is done by `svelte-check` (Chapter 15), not by the compiler.

### Beyond application code

Because a single file is the unit, tools can compile files independently and in parallel. It also means a codemod that touches several files must do its own cross-file reasoning. The next section builds a small one-file tool on the real parser.

## A toy tool: auditing components with the AST

Here is a script that walks a directory of `.svelte` files and reports rune usage, template expressions, unkeyed `{#each}` blocks, `{@html}` use and legacy `on:` directives. It uses `parse` with `modern: true` and `estree-walker`, because `walk` is no longer exported by `svelte/compiler`.

```js
// audit.mjs   usage: node audit.mjs src
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, extname } from 'node:path';
import { parse } from 'svelte/compiler';
import { walk } from 'estree-walker';

function* files(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* files(p);
    else if (extname(p) === '.svelte') yield p;
  }
}

function audit(file) {
  const source = readFileSync(file, 'utf8');
  const ast = parse(source, { modern: true, filename: file });
  const report = { file, runes: {}, templateExpressions: 0, unkeyedEach: [], html: 0, legacyEvents: 0 };
  const line = (offset) => source.slice(0, offset).split('\n').length;

  walk(ast, {
    enter(node) {
      switch (node.type) {
        case 'CallExpression': {
          const c = node.callee;
          const name =
            c.type === 'Identifier' ? c.name
            : c.type === 'MemberExpression' && c.object.type === 'Identifier' && !c.computed
              ? `${c.object.name}.${c.property.name}` : null;
          if (name?.startsWith('$')) report.runes[name] = (report.runes[name] ?? 0) + 1;
          break;
        }
        case 'ExpressionTag': report.templateExpressions++; break;
        case 'EachBlock': if (!node.key) report.unkeyedEach.push(line(node.start)); break;
        case 'HtmlTag': report.html++; break;
        case 'OnDirective': report.legacyEvents++; break;
      }
    },
  });
  return report;
}

for (const file of files(process.argv[2])) console.log(JSON.stringify(audit(file)));
```

On a sample project with two components it printed:

```text
{"file":"src/A.svelte","runes":{"$state":1,"$derived":1,"$effect":1},"templateExpressions":2,"unkeyedEach":[6],"html":1,"legacyEvents":1}
{"file":"src/B.svelte","runes":{"$state.raw":1},"templateExpressions":2,"unkeyedEach":[],"html":0,"legacyEvents":0}
```

Several details are worth noting. One walk covers script and template, since the modern AST embeds ESTree nodes for JavaScript and Svelte nodes for markup in the same tree. Rune calls are ordinary `CallExpression` nodes; the compiler has no special AST for them, and distinguishing `$state.raw` requires looking at a `MemberExpression` callee. Template node type names (`ExpressionTag`, `EachBlock` with a `key`, `HtmlTag`, `OnDirective`, `RegularElement`, `IfBlock`) come from the `AST` namespace in the types: read that namespace when you write a tool.

To go from reporting to rewriting, mutate nodes and call `print(ast)`. Because `print` can output any node and returns a source map, you can build a codemod such as “add a key to every each block” in a few dozen lines. Be aware, however, that printing normalises formatting, so run Prettier afterwards.

You can also make the compiler itself your linter: compile each file with `generate: false` (no output, only warnings) and promote chosen warning codes to failures. That is the cheapest way to enforce project rules such as “no `a11y_autofocus`” in CI, and it is what `svelte-check` does with more editor integration.

## Key takeaways

- `compile` is parse, analyze, transform (client or server), print. It works on one file at a time, so everything it knows about other modules comes from syntax alone.
- Client output is a function `Component($$anchor, $$props?)`: a cloned static template (`$.from_html`), sources and deriveds, one `$.template_effect` per group of reactive expressions, and delegated events. Server output is string concatenation with `$.escape`, plain variables for state and no event or effect code.
- Compile-time optimisations: unchanged `$state` becomes a plain variable (even inlined), expressions with no reactive reads are evaluated at creation or at compile time (5.27/5.28), static attributes are baked into the template, templates are cloned (`fragments: 'html'` or CSP-friendly `'tree'`), props are read lazily as `$$props.x`, and `click`-style events are delegated through a single root listener.
- The public compiler API: `compile`, `compileModule`, `parse` (use `modern: true`), `parseCss`, `print`, `preprocess`, `migrate`, `VERSION`. `walk` now comes from `estree-walker`.
- `CompileOptions` covers target and diagnostics (`dev`, `generate`, `warningFilter`), output (`css`, `cssHash`, `fragments`, `preserveComments`, `preserveWhitespace`, `discloseVersion`, `hmr`, `sourcemap`), mode (`runes`, `customElement`, `namespace`) and the experimental `experimental.async`; `accessors`, `immutable` and `compatibility.componentApi` are deprecated; components override some options with `<svelte:options>`.
- Preprocessors run group by group, and inside each group markup then script then style. Give them names. Return a fresh `attributes` object to remove an attribute, never `undefined` values.
- Errors are thrown `CompileError`s, warnings are collected; both carry `code`, `message`, `start`/`end`, `frame`. Silence with `svelte-ignore`, `warningFilter` or `onwarn`, and give a reason.
- Rune placement is strict because the compiler rewrites runes statically. A rune is not a value, so it cannot be exported as reassigned state, passed to a function, or stored.
- The “one file at a time” rule explains why reassigned `$state` and any `$derived` cannot be exported and why getters or objects are the way to share reactivity across modules.

## Review Questions

1.  Name the four stages of `compile` in order and say what each produces. In which stage does the compiler decide that a `$state` variable is never reassigned?

2.  In the compiled client counter, what do `$.from_html`, `$.template_effect` and `$.delegated` each do, and how many times does each run per component instance?

3.  Why does the server output of the counter contain `let count = 0` and no event handler?

4.  What does this component compile to in terms of signals? Which variables are signals, which are plain, and which is a proxy?

```html
<script>
  let a = $state(1);
  let b = $state(2);
  let o = $state({ x: 1 });
  function bump() { b++; }
</script>
<p>{a} {b} {o.x}</p>
<button onclick={bump}>+</button>
```

5.  What does “partial evaluation” mean, and which of these expressions can be folded at compile time given `const w = 3`: `{w + 1}`, `class="a {'b'}"`, `{count}` where `count` is `$state`?

6.  What difference between `fragments: 'html'` and `fragments: 'tree'` affects the choice under a strict Content Security Policy? Which is the default and why?

7.  Which of these events are delegated? `click`, `focus`, `keydown`, `mouseenter`, `input`, `scroll`, `touchstart`, `pointerdown`.

8.  A third-party widget calls `event.stopPropagation()` in a native `click` listener on its container, and your handler `onclick` inside the container never fires. Explain why and give two fixes.

9.  Why does the compiled code read `$$props.a` inside the template effect rather than destructuring `a` once at the top?

10. Write the call that compiles a `.svelte.ts` source containing runes, and say in which mode it always compiles.

11. What does `generate: false` return? Name a tool that benefits from it.

12. When is `result.css` `null`, and what does `hasGlobal` tell a bundler?

13. Find the bug. The compile fails; what is the error code and why?

```ts
// store.svelte.ts
export let theme = $state<'light' | 'dark'>('light');
export function toggle() { theme = theme === 'light' ? 'dark' : 'light'; }
```

14. Why is `export const settings = $state({ compact: false })` accepted while the previous example is not?

15. Why would exporting a `$derived` from a module be rejected (`derived_invalid_export`) even when it is declared with `const`?

16. Given `parse(source, { modern: true })`, which top-level keys does the result have, and how would you list the element names used in the template?

17. What is `walk` in `svelte/compiler` today? Write the import you should use instead.

18. What does `print` need as input, and what does it not guarantee about the output?

19. Predict the order of the calls, and the attributes seen by the second group’s style preprocessor:

```ts
const order: string[] = [];
const g = (n: string) => ({
  name: n,
  markup: ({ content }) => { order.push(n + ':markup'); return { code: content }; },
  script: ({ content }) => { order.push(n + ':script'); return { code: content }; },
  style: ({ content }) => { order.push(n + ':style'); return { code: content, attributes: {} }; },
});
await preprocess(src, [g('a'), g('b')]);
```

20. A style preprocessor returns `{ code, attributes: { ...attributes, lang: undefined } }`. What ends up in the output and what is the fix?

21. Which of these is *not* a way to silence `state_referenced_locally` for one declaration?

    a.  `// svelte-ignore state_referenced_locally` above it
    b.  A `warningFilter` returning `false` for that code
    c.  `onwarn` in `svelte.config.js` that ignores the code
    d.  Wrapping the declaration in `$effect.pre`

22. Explain why the compiler removes an unused CSS selector rather than keeping it, citing the two bad alternatives.

23. What does `css: 'injected'` change in the compiler output, in SSR and on the client, and what is the default behaviour of `compile()` when `css` is omitted?

24. `cssHash` receives `{ hash, css, name, filename }`. Write a `cssHash` that returns `app-<hash of the file name>` and explain one reason a team might want a custom hash.

25. What does `runes: ({ filename }) => filename.includes('node_modules') ? false : true` do, and what happens if you return `undefined` for some files?

26. Which statement about the compiler output is correct?

    a.  `$.template_effect` runs again every time the component’s props object changes identity.
    b.  Generated code is a public API you can import from `svelte/internal/client`.
    c.  The helper names in generated code may change between patch releases.
    d.  Server output keeps `$effect` bodies but never runs them.

27. Design question: you want CI to fail on any new use of `on:` directives and `{@html}`. Describe two implementations, one based on `warningFilter`/`onwarn` and one on `parse` plus `estree-walker`, and compare their trade-offs.

28. Why is it a bad idea to depend on the exact shape of compiler output in production tooling, such as a custom bundler plugin that regex-matches `$.template_effect`?
