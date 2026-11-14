# Chapter 10: Styling

CSS in a Svelte component is not a runtime feature. It is a compile-time transformation: the compiler parses your `<style>`, walks your template to find out which elements each selector can match, rewrites every selector so that it can only match this component’s elements, drops the rules it can prove are dead, and hands the result to your bundler (or inlines it into the component’s JavaScript). There is no style object at runtime and no CSS-in-JS cost, but the compile-time model has consequences that surprise people: selectors that are “unused” because the compiler cannot see the element, specificity that is deliberately predictable, styles that do not reach into child components, and rules that vanish when markup arrives through `{@html}`.

This chapter explains the scoping mechanics precisely (with real compiler output), the global escape hatches, how to style child components with custom properties and when to fall back to `:global`, how `class` and `style:` produce their values, the compiler options that control where CSS ends up, and how Tailwind and theming fit. All compiler output shown was produced by `svelte@5.57.2` and is illustrative: the hash value, formatting and comments are not public API.

## How scoping works

Given this component:

```html
<p class="a">hello</p>

<style>
  p { color: red; }
  .a { color: blue; }
  p.a { color: green; }
  div p { color: grey; }
</style>
```

the compiler produces (with `css: 'external'`, formatted for reading):

```css
p.svelte-1u2atu7 { color: red; }
.a.svelte-1u2atu7 { color: blue; }
p.a.svelte-1u2atu7 { color: green; }
/* (unused) div p { color: grey; } */
```

and adds `class="svelte-1u2atu7"` (merged with any existing classes) to every element the component’s template renders that *could* be matched by a rule. Four facts follow.

**1. The hash is derived from the CSS, not the file path.** By default the class is `svelte-` plus a hash of the stylesheet’s content (the compiler option `cssHash` receives `{ name, filename, css, hash }` and the default is `svelte-${hash(filename ?? css)}`, as the facts sheet records). The practical result: two components with identical `<style>` content can get identical hashes, harmlessly, and any style edit changes the class name. The migration guide also warns that the hash is no longer guaranteed to be the *last* class on the element; do not write selectors that depend on class order.

**2. Specificity is predictable: +0-1-0.** “Each scoped selector receives a specificity increase of 0-1-0, as a result of the scoping class being added.” So a component’s `p { }` beats a global stylesheet’s `p { }` regardless of load order. The scoping class is added to the *first* compound selector involved; where it must be repeated the compiler uses `:where(.svelte-xyz)`, which has zero specificity, so you never pay twice. Real output for `.a .a { }`:

```css
.a.svelte-1u2atu7 .a:where(.svelte-1u2atu7) { c: d }
```

The first occurrence adds 0-1-0, the second adds nothing. This matters when you compare scoped rules with each other: `.a .b` becomes `.a.svelte-x .b:where(.svelte-x)`, so its specificity is 0-3-0, not 0-4-0.

**3. Unused selectors are removed (and warned about).** In the example, `div p` is not output because the component has no `<div>`, and the compiler emits `css_unused_selector` (“Unused CSS selector”div p”“). The compiler’s analysis is conservative in the safe direction: it keeps a selector if *any* element in the template might match, including through dynamic classes. I verified that a rule `.foo { }` is kept when the template has `class={c}`, `class={{ foo: c }}`, `class:foo={c}` or `{...props}` on the element, because the compiler cannot prove it never matches. It is removed when there is no element or class that could possibly carry it.

Removal cannot be switched off. The FAQ is explicit: “No. Svelte removes the styles from the component and warns you … in order to prevent issues.” The reasoning: if it kept the selector with the scoping class it would not match anything you expect; if it kept it *without* the scoping class, it would silently become a global style. The escape hatch is `:global`, applied deliberately.

**4. Everything is static.** Because scoping is decided at compile time, it cannot see elements that exist only at runtime, which leads straight to the “invisible content” problem.

### Content the compiler cannot see

Three kinds of content never receive the scoping class:

- Markup inserted with `{@html}` (Chapter 6);
- Elements rendered by *child components* (they have their own hash);
- Elements created or classed by a library, an attachment or an action.

For all of them, the rule `article a { color: hotpink }` is treated as unused because the compiler sees no `<a>` inside `<article>`. I compiled:

```html
<article>{@html x}</article>

<style>
  article a { color: red }               /* unused */
  article :global a { color: blue }      /* kept */
  article :global { img { width: 1px } } /* kept (nested form) */
</style>
```

Output: the first is commented out as unused; the second becomes `article.svelte-x a { ... }`; the third `article.svelte-x { img { ... } }` (native CSS nesting, preserved as written). **The scoped part before `:global` still anchors the rule to your component’s `article`.** That is why the partially-global form is the right tool: it limits the blast radius to descendants of an element you own.

## Global styles

### `:global(...)`, partial and total

```html
<style>
  /* the whole selector is global */
  :global(body) { margin: 0; }

  /* only strong is global: descendants of this component's divs */
  div :global(strong) { color: goldenrod; }

  /* a class added by a library or programmatically to this component's p */
  p:global(.big.red) { text-decoration: underline; }
</style>
```

Verified output: `body{margin:0}` (no hash at all), `div.svelte-x strong{...}`. The `p:global(.big.red)` rule is kept only if the template contains a `<p>` the component renders; in my run it was reported unused because my test template had no `<p>`, which shows that the scoped half of a mixed selector is still checked.

Placement rules (compile errors, all documented in the generated error list): `:global(...)` may be at the start or end of a compound selector but not in the middle (`css_global_invalid_placement`, I triggered it with `.a :global(b) .c`), must contain exactly one selector (`css_global_invalid_selector`), must not contain type or universal selectors when combined into a compound selector (`css_global_invalid_selector_list`, triggered by `div:global(span) p`-like forms), and must not be followed by a type selector (`css_type_selector_invalid_placement`).

### `:global { ... }` blocks

For groups of rules:

```html
<style>
  :global {
    /* applies to every div and p in the application */
    div { margin: 0; }
    p { line-height: 1.5; }
  }

  .a :global {
    /* every `.b .c .d` inside this component's `.a` elements, in any component */
    .b .c .d { color: red; }
  }
</style>
```

The docs say the second form “could also be written as an equivalent `.a :global .b .c .d` selector, where everything after the `:global` is unscoped, though the nested form is preferred.” A top-level `:global { color: red }` containing declarations rather than rules is an error (`css_global_block_invalid_declaration`, verified). A `:global` block cannot share a selector list with non-global entries (`css_global_block_invalid_list`): split them into two rules.

The `hasGlobal` flag on `CompileResult.css` (added in 5.26) reports whether the output contains global rules, so tooling can treat such files specially (for example, to avoid tree-shaking their CSS). In my compiles it was `true` for the global cases and `false` for purely scoped output.

> **Senior tip:** `:global` is the escape hatch, not the default. Reach for the partial form, anchor it on an element you own, and add a comment explaining *what* produces the unmatched markup. A bare `:global(.some-class)` in a component is a global style in disguise, and it will leak to every consumer of the page.

### Scoped keyframes

`@keyframes` names are scoped with the same hash, and `animation` references in the same component are rewritten. A name can be made global with the `-global-` prefix, which is stripped in the output. Real output:

For `.b { animation: bounce 1s, -global-spin 2s }` with `@keyframes bounce` and `@keyframes -global-spin` defined, the compiler produced:

```css
.b.svelte-1u2atu7 { animation: svelte-1u2atu7-bounce 1s, -global-spin 2s }
@keyframes svelte-1u2atu7-bounce { ... }
@keyframes spin { ... }
```

The `-global-` prefix is stripped only from the `@keyframes` rule. In my test it was **not** rewritten inside the `animation` value, so `animation: -global-spin 2s` would reference a non-existent animation. Write the declaration with the real name: `animation: spin 2s` (verified: unscoped, matches the global `@keyframes spin`). This agrees with the docs: the keyframe “will then be referenced using just `my-animation-name` elsewhere in your code”.

Scoping keyframes by default means two components can both define `@keyframes fade` without colliding. Use `-global-` for shared animations defined in one component and referenced by name elsewhere.

### `:is()`, `:where()`, `:has()`, `:not()` and nesting

In Svelte 4 selectors inside `:is`, `:where` and `:has` were effectively global. Svelte 5 analyses them in component context, so some selectors that used to work are now reported unused. The migration guide’s remedy is `:global(...)` inside the pseudo-class. My compile of one component with several forms shows how each is handled:

```css
/* input */
:is(.a, .zzz) .b { }    :where(.a) p { }    .a:has(.nope) { }    .a:not(.q) { }

/* output */
:is(.a:where(.svelte-x) /* (unused) .zzz */) .b.svelte-x { }
:where(.a:where(.svelte-x)) p.svelte-x { }
/* (unused) .a:has(.nope) { } */
.a.svelte-x:not(.q) { }
```

Observations: inside `:is(...)`, dead alternatives are pruned individually (`.zzz` is dropped, `.a` kept and scoped); `:has(.nope)` is entirely removed because nothing in the template can match `.nope`; `:not(.q)` is kept because “not q” is satisfiable.

**Native CSS nesting** inside `<style>` is supported and scoped: `.a { color: red; p { color: blue } &:hover { } }` becomes `.a.svelte-x { color: red; p:where(.svelte-x) { color: blue } &:hover { } }` in my run, with a nested rule that cannot match (`.missing`) pruned and flagged. Nested selectors get `:where(.svelte-x)` so that nesting does not inflate specificity. The compile errors `css_nesting_selector_invalid_placement` and friends apply to misplaced `&`.

At-rules work as expected: selectors inside `@media`, `@supports`, `@container` and `@layer` blocks were all scoped in my compile (`@media (min-width:600px){.a.svelte-x{...}}`). Pseudo-elements and pseudo-classes (`::placeholder`, `:first-child`, `:hover`, `::before`) keep their position and the hash class attaches to the compound before them.

Keep in mind that scoping is per component and cascade layers are not scoped: a rule inside `@layer base { }` in a component is the *same* layer `base` as everywhere else. That makes `@layer` a good way to order component styles relative to a global reset and utility CSS.

## Styling child components

Scoped styles stop at the component boundary, which is the point. There are three ways to cross it, in order of preference.

### 1. Custom properties as the styling API

The docs’ recommended approach: expose CSS custom properties from the child and set them from the parent.

```html
<!-- Parent.svelte -->
<script lang="ts">
  import Slider from './Slider.svelte';
  let r = $state(10);
</script>

<Slider --track-color="black" --thumb-color="rgb({r} 0 0)" />
```

```html
<!-- Slider.svelte -->
<div class="track"><span class="thumb"></span></div>

<style>
  .track { background: var(--track-color, #aaa); }
  .thumb { background: var(--thumb-color, blue); }
</style>
```

How the compiler implements `--prop` on a component (illustrative output):

```js
var root = $.from_html(`<svelte-css-wrapper style="display: contents"><!></svelte-css-wrapper>`, 1);
// ...
$.css_props(node, () => ({ '--track-color': 'black', '--thumb-color': `rgb(${$$props.r ?? ''} 0 0)` }));
Slider(node.lastChild, {});
```

and the rendered DOM in my run was:

```html
<svelte-css-wrapper style="display: contents; --track-color: black; --thumb-color: rgb(10 0 0);">
  <div class="track svelte-iwy38o">...</div>
</svelte-css-wrapper>
```

Clicking a button that set `r = 200` updated the wrapper’s style to `rgb(200 0 0)`: custom-property values are reactive, because `css_props` re-runs when its expression’s dependencies change. Inside an SVG, a `<g>` is used instead of a custom element (`$.from_svg('<svg><g><!></g></svg>')`).

Costs and caveats of the wrapper element:

- `display: contents` means it does not generate a box, so layout is unaffected, but it **does** sit in the DOM. Selectors that depend on direct parentage (`parent > .child`, `:first-child`, `+` sibling combinators across the component boundary) see the wrapper. The docs warn: “it will affect any CSS selectors that (for example) use the `>` combinator to target an element directly inside the component’s container.”
- In Svelte 4 this wrapper was a `<div>`; Svelte 5 uses `<svelte-css-wrapper>`, so tests or global CSS that targeted that div must change.
- It only appears when you actually pass `--*` props. A component with no custom props passed has no wrapper.
- You do not have to set properties on the component: any ancestor can define them, and defining them on `:root` is the standard way to provide design tokens.

Design the child’s API deliberately: document each `--token`, always supply a `var(--token, fallback)` default, and prefer semantic names (`--slider-track-color`) so they do not collide with global tokens.

### 2. `style:--x` for passing JS values into your own CSS

Inside a component, the best-practices doc recommends setting a custom property with the `style:` directive when a JavaScript variable must feed your CSS:

```html
<script lang="ts">
  let { columns = 3 }: { columns?: number } = $props();
</script>

<div class="grid" style:--columns={columns}>...</div>

<style>
  .grid { display: grid; grid-template-columns: repeat(var(--columns), 1fr); }
</style>
```

This avoids building style strings and keeps the CSS in the stylesheet. In my compile, `style:--cols={c} style:width|important={w}` produced a single `$.set_style` call with a list of per-property dictionaries, so each directive updates only its own property.

### 3. `:global` overrides, when there is no other way

If a child component belongs to a library and exposes no custom properties, override with a partially global selector anchored on an element you own:

```html
<div class="host">
  <LibraryCard />
</div>

<style>
  .host :global {
    h1 { color: red; }
  }
</style>
```

This is brittle (you depend on the library’s internal markup) and leaks to any other `h1` inside `.host`, so wrap it tightly and keep a comment. Verified: `div h1 { }` is pruned as unused when `h1` comes from a child; `div :global(h1) { }` is kept as `div.svelte-x h1 { }`.

## Classes

### `class` as an attribute

All the rules from Chapter 6 apply (clsx objects and arrays, since 5.16). Here is what I measured at runtime for the same component:

| Template | Resulting `class` attribute (plus scoping class) |
|------------------------------------|------------------------------------|
| `class={[on && 'on', { big: r > 5 }, ['x', r > 0 && 'y']]}` with `r=0, on=false` | `x` |
| the same with `r=10, on=true` | `on big x y` |
| `class={false}` | `false` |
| `class={NaN}` / `class={0}` | `NaN` / `0` |
| `class={undefined}` | (scoping class only) |
| `class={[false, null, undefined]}` | (scoping class only) |
| `class={{}}` | (scoping class only) |
| `class="static" class:dyn={on}` | `static` / `static dyn` |

So the docs’ warning is real: primitive falsy values stringify; arrays and objects are the safe form. In Svelte 6, all falsy values will omit the attribute.

The scoping class is appended to whatever you compute (`"x svelte-1suqzff"`). Note that if you build class lists in JavaScript and *return* them from a function, the compiler cannot see the literal class names, which is why the pruning analysis treats `class={expr}` as “might be anything”: rules are kept, but nothing proves that a typo in a class name matches anything. Prefer literals in the template (`class={{ active: isActive }}`) so unused-selector warnings stay useful.

### Typing and merging `class` props

Components that accept `class` should type it as `ClassValue` (5.19, from `svelte/elements`) and merge it with their own classes using an array. That is the whole API:

```html
<script lang="ts">
  import type { ClassValue } from 'svelte/elements';
  let { class: klass, children }: { class?: ClassValue; children?: import('svelte').Snippet } = $props();
</script>

<div class={['card', klass]}>{@render children?.()}</div>
```

The caller’s classes carry their own scope (or are global/utility classes), and the component’s `.card` rule is scoped to the component. Because scoped rules have +0-1-0 specificity, a caller’s utility class such as `p-4` (also 0-1-0) competes on equal footing with `.card` (0-2-0 after scoping), and the *scoped component rule wins*. If you want utilities to override, use `@layer` (utilities in a later layer) or write the component rule with `:where(.card)`.

### The `class:` directive

`class:active={isActive}` and the shorthand `class:active` still work and are equivalent to a one-key object, but the docs now recommend the attribute form: “the attribute is more powerful and composable.” The directive cannot combine several conditions on one class cleanly, does not nest, and cannot be spread. New code should not use it.

### The `style:` directive

`style:` sets individual properties and beats the `style` attribute, even `!important` declarations in it: `<div style:color="red" style="color: blue !important">` is red. Add `|important` to emit `!important`. A nullish value removes the property, and `style:--name` sets custom properties. Dynamic updates change only the affected property. Use it instead of string-concatenating a `style` attribute.

## `{@html}` and third-party content

Everything in the “content the compiler cannot see” section applies. Two further notes. First, CSS from a Markdown renderer or CMS is typically content-oriented (`.prose a`, `.prose img`); a single `:global` block scoped under a wrapper class is the idiomatic bridge:

```html
<div class="prose">{@html html}</div>

<style>
  .prose :global {
    a { color: var(--link); text-decoration: underline; }
    img { max-inline-size: 100%; block-size: auto; }
    pre { overflow-x: auto; }
  }
</style>
```

Second, sanitise before rendering (Chapter 6): global styles do not protect you from injected `<style>` or `style=` attributes in the HTML.

## Nested `<style>` elements

A component may have only **one top-level `<style>`** (`style_duplicate`, verified). A `<style>` element nested inside another element or a block is different: it is inserted into the DOM *as is*, with no scoping or processing:

```html
<div>
  <style>
    /* applies to every div in the document: this is plain CSS, not scoped */
    div { color: red; }
  </style>
</div>
```

In my compile the top-level stylesheet and the nested one were independent. A nested `<style>` is the right tool for CSS that must depend on runtime values interpolated by the template (for example, an element whose `<style>` is generated per instance), or for markup that is itself content, but it is rarely the right tool for component styling: it is unscoped, not minified and not deduplicated, and each instance inserts its own copy.

## Compiler options

### `css`: `'injected'` or `'external'`

- **`'external'`** (the default the bundler plugins use): the compiler returns the CSS in `result.css` and the plugin emits it as a normal CSS asset. You get extraction, caching, `<link>` tags, source maps. Components contain no CSS in their JavaScript.
- **`'injected'`**: the CSS is carried inside the component’s JavaScript. On the client the component calls `$.append_styles($$anchor, $$css)` at mount, which inserts a `<style id="svelte-hash">` into the document head (or the shadow root) once per hash; during SSR it is emitted into `head`. Real output:

```js
var root = $.from_html(`<p class="svelte-1u2atu7">x</p>`);
const $$css = { hash: 'svelte-1u2atu7', code: 'p.svelte-1u2atu7{color:red}' };

export default function App($$anchor) {
  $.append_styles($$anchor, $$css);
  var p = root();
  $.append($$anchor, p);
}
```

I confirmed at runtime that mounting a component with injected CSS creates `<style id="svelte-1suqzff">` in `document.head` with the compiled rules. Use `'injected'` for libraries that must work with no CSS pipeline, for Shadow DOM and custom elements (where it is always forced to `'injected'`, Chapter 19), and for micro-frontends.

Per component, `<svelte:options css="injected" />` overrides the global option (my compile gave the same output as the global setting). Since 5.54 the compiler option may also be a function `({ filename }) => 'injected' | 'external'`, which lets a bundler config choose per file; I verified a function returning `'injected'` produces the injected output.

### `cssHash`

```js
// compilerOptions
cssHash: ({ hash, css, name, filename }) => `app-${name}-${hash(css)}`
```

With ``` ({ hash, css, name }) => ``my-${name}-${hash(css)}`` I got ```p.my-App-16e8uch{color:red}\`. Use it for readable class names in debugging, for collision avoidance when two Svelte builds share a page (micro-frontends), or for deterministic names in snapshot tests. Make sure the function is deterministic and includes enough entropy (the content hash) to stay unique.

### `hasGlobal`

`compile(...).css.hasGlobal` is `true` when the stylesheet contains global rules (including `:global(...)` and un-prefixed `-global-` keyframes). Tooling that tree-shakes or isolates component CSS can use it to leave such stylesheets alone.

### `preserveWhitespace`, `namespace`

`namespace="svg"` (compiler option or `<svelte:options>`) affects element creation, not CSS, but SVG-specific details leak into styling: the custom-property wrapper becomes a `<g>`, and `display: contents` is not available on it.

## CSS in tests and tooling

- A test that mounts a component sees its styles in the document only if the CSS was injected (`css: 'injected'`) or your test setup processes the extracted CSS. Either way, jsdom does not implement the full cascade or layout, so do not assert on computed styles; assert on classes, attributes and custom-property values on the wrapper instead.
- Linters: `css_unused_selector` is a real signal. Silence one rule with `<!-- svelte-ignore css_unused_selector -->` placed above the `<style>` only when you are sure the markup arrives dynamically; prefer `:global`.
- Preprocessors (`lang="scss"`, PostCSS) run before the Svelte compiler sees the CSS, via `preprocess` in the Svelte config (Chapter 2).

## Tailwind and utility CSS

Utility CSS and scoped CSS are complementary, and their only friction points are mechanical:

- **Utilities in `class` work normally**, including with clsx arrays and objects (`class={['px-4', active && 'bg-blue-600']}`). The scanner that generates utilities needs to *see* the full class names in your source, so write them as literal strings, not assembled fragments.
- **Wrapper components** accept `class` as a `ClassValue` and merge: that is what the docs show with `class={{ 'bg-blue-700 sm:w-1/2': useTailwind }}`, noting that one condition can toggle several utilities at once.
- **`@apply` inside `<style>`** works through your CSS pipeline, but selectors generated by Tailwind that use `:is(...)` become subject to Svelte’s scoping analysis. The migration guide’s fix: “add a `:global` selector to preserve rules that use Tailwind-generated `:is(...)` selectors”:

```html
<style>
  main :global {
    @apply bg-blue-100 dark:bg-blue-900;
  }
</style>
```

- **Specificity**: scoped rules (0-1-0 for a class, plus the hash) beat equal-specificity utilities from a stylesheet that loads earlier, and tie with later ones; if you want utilities to override component styles consistently, put component styles in a lower cascade layer (`@layer components { ... }` inside `<style>`), and utilities in a higher layer.

## Theming and dark mode with custom properties

Custom properties pass through component boundaries without the compiler’s involvement, which makes them the correct tool for themes. A minimal, robust pattern:

```css
/* app.css, imported once */
:root {
  color-scheme: light dark;
  --bg: #fff;
  --fg: #1a1a1a;
  --accent: #2563eb;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme='light']) { --bg: #111; --fg: #eee; --accent: #60a5fa; }
}
:root[data-theme='dark'] { --bg: #111; --fg: #eee; --accent: #60a5fa; }
```

```html
<!-- Card.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  let { children }: { children?: Snippet } = $props();
</script>

<div class="card">{@render children?.()}</div>

<style>
  .card {
    background: var(--card-bg, var(--bg));
    color: var(--fg);
    border: 1px solid color-mix(in srgb, var(--fg) 15%, transparent);
  }
</style>
```

Key ideas:

1.  **Tokens on `:root`, components read tokens with fallbacks.** Components do not know about themes; they know `var(--bg)`.
2.  **Explicit override via an attribute** (`data-theme`) beats the OS preference, and `prefers-color-scheme` is the default. The guard `:root:not([data-theme='light'])` prevents the dark media query from overriding an explicit light choice.
3.  **Persisting the choice** is JavaScript, not CSS: write `data-theme` on `<html>` early (inline script in the HTML shell, to avoid a flash) and keep the toggle in a small shared state object (Chapter 12).
4.  **Scoped overrides:** to theme a subtree, set the tokens on a wrapper element (`<section style:--accent={brand}>`) or on a component via `--accent="..."`; inheritance does the rest.
5.  **JS needs the theme**, for example a canvas chart: read it with `getComputedStyle(el).getPropertyValue('--accent')` inside an attachment, or react to `new MediaQuery('prefers-color-scheme: dark')` (Chapter 9) for the OS preference. Do not use a `MediaQuery` just to switch styles that CSS could switch itself, because the server cannot know the value and the page may flash after hydration.

## Putting it together: a themable, styleable component

```html
<!-- Badge.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { ClassValue } from 'svelte/elements';

  type Tone = 'neutral' | 'success' | 'danger';
  let { tone = 'neutral', class: klass, children }: {
    tone?: Tone;
    class?: ClassValue;
    children: Snippet;
  } = $props();
</script>

<span class={['badge', { success: tone === 'success', danger: tone === 'danger' }, klass]}>
  {@render children()}
</span>

<style>
  .badge {
    display: inline-block;
    padding: var(--badge-padding, 0.1em 0.6em);
    border-radius: var(--badge-radius, 999px);
    background: var(--badge-bg, color-mix(in srgb, var(--fg) 12%, transparent));
    color: var(--badge-fg, var(--fg));
    font-size: 0.85em;
  }
  .success { --badge-bg: color-mix(in srgb, green 20%, transparent); }
  .danger  { --badge-bg: color-mix(in srgb, red 20%, transparent); }
</style>
```

Usage: `<Badge tone="success" --badge-radius="4px" class="ml-2">paid</Badge>`. The scoped rules style the badge; the public styling API is the three `--badge-*` tokens plus `class` for layout utilities; none of it requires `:global`. The wrapper element appears only because `--badge-radius` is passed to the component, so avoid putting `Badge` where a `>` combinator is expected to see the `<span>` directly.

## Key takeaways

- Scoping is compile-time: selectors get a hash class (`svelte-xyz`), adding +0-1-0 specificity once and `:where(...)` thereafter. The hash is content-derived and not guaranteed to be last in the class list.
- Selectors the compiler cannot match to an element are removed and flagged with `css_unused_selector`; this cannot be disabled. Dynamic `class` values and spreads keep selectors alive.
- `{@html}`, child component markup and library-generated DOM are invisible to scoping. Use partial `:global(...)` or `parent :global { ... }` anchored on your own element.
- `@keyframes` are scoped; `-global-` makes them global. `:is/:where/:has/:not` are analysed in component context, and native CSS nesting is supported and scoped.
- Style child components through custom properties first: `--x` on a component creates a `display: contents` `<svelte-css-wrapper>` (a `<g>` in SVG) whose style is reactive, at the cost of an extra DOM node.
- `class` accepts clsx strings, arrays and objects (type: `ClassValue`); `false`/`NaN`/`0` still stringify, `undefined`/`null` and empty arrays/objects do not. Prefer it to `class:`. `style:` directives win over the `style` attribute and update per property.
- Only one top-level `<style>` is allowed; nested `<style>` elements are unscoped and inserted as is.
- `css: 'external'` vs `'injected'` (also per component with `<svelte:options css="injected" />`, and as a function since 5.54); `cssHash` customises class names; `css.hasGlobal` reports global output.
- Tailwind works via literal class strings and `ClassValue` merging; `@apply` with generated `:is()` needs `:global`. Use cascade layers to order components against utilities.
- Theme with custom properties on `:root` plus an explicit attribute override; avoid JS-driven media queries for what CSS can do.

## Review Questions

1.  What exactly does the compiler do to `p.a { color: red }` and to the `<p class="a">` in the template? What is the specificity of the result compared with the source selector?
2.  Why does `.a .a { }` compile to `.a.svelte-x .a:where(.svelte-x)`? What would go wrong with specificity if it were `.a.svelte-x .a.svelte-x`?
3.  A teammate says “unused selector warnings are annoying, can we turn them off?” What is the answer and why does the compiler remove such selectors instead of keeping them?
4.  For each case, say whether the rule `.foo { }` is kept or pruned: (a) `<p class={c}>`, (b) `<p class="bar">`, (c) `<p {...rest}>`, (d) `<p class:foo={x}>`, (e) no `<p>` at all.
5.  Why does `article a { color: red }` fail when the article’s content comes from `{@html}`? Give two working rewrites and say which you prefer.
6.  What is the difference in output between `div :global(strong)`, `:global(div) strong` and `:global(div strong)`? Which of them leaks styles outside your component?
7.  Find the compile error: `.a :global(b) .c { }`, `:global { color: red }`, `:global, x { y { color: red } }`. Name the error code for each.
8.  What happens to `animation: spin 1s` if the same component defines `@keyframes -global-spin`, and what if it defines `@keyframes spin`?
9.  A component defines `@keyframes fade`, another uses `animation: fade 1s` without defining it. What happens and why?
10. Why did Svelte 4 CSS that used `:is(.a, .b) .c` sometimes break when migrating to Svelte 5? How do you fix it?
11. (Multiple choice) In `:is(.a, .zzz) .b`, with `.zzz` appearing nowhere in the template, what does the compiler do?
    a.  removes the whole rule
    b.  keeps the rule unchanged
    c.  prunes only the `.zzz` alternative and keeps the rest
    d.  errors
12. What does `<Slider --track-color="black" />` compile to? List two consequences of the extra element for CSS selectors and layout.
13. How are `--prop` values on components kept reactive, and what is used instead of `<svelte-css-wrapper>` inside an SVG?
14. Why is passing a custom property usually better than overriding a child’s internal selectors with `:global`? When is `:global` the only option?
15. Write a component that accepts `class` and `--accent` from its parent and merges the class with its own. Which type do you use for the `class` prop?
16. Predict the `class` attributes (ignoring the scoping class): `class={false}`, `class={[false, null]}`, `class={{ a: 0, b: 1 }}`, `class={undefined}`, `class={['x', 0]}`.
17. What does `<div style:color="red" style="color: blue !important">` render, and why? What does `style:opacity|important={0.5}` emit?
18. Why does the docs’ advice recommend `style:--columns={columns}` plus `var(--columns)` instead of a `style` string? What is the performance/update advantage?
19. How many `<style>` elements can a component have at top level? What happens to a `<style>` nested in a `<div>`?
20. Compare `css: 'external'` with `css: 'injected'`. Name two situations where `'injected'` is the right choice and where it is forced.
21. How does `<svelte:options css="injected" />` interact with the compiler option, and what is new in 5.54 for the option?
22. Write a `cssHash` function that makes class names look like `acme-Button-1x2y3z`. What must it guarantee?
23. What does `result.css.hasGlobal` tell you and who benefits from it?
24. In a Tailwind project, `main { @apply bg-blue-100 dark:bg-blue-900; }` is reported as an unused selector or loses its dark variant. What is the documented fix?
25. A scoped `.card { padding: 1rem }` in a component and a caller’s `class="p-4"` conflict. Which one wins and why? Give two ways to let the utility win.
26. Design a dark-mode scheme for an app using custom properties, honoring the OS preference but allowing an explicit user override. Why does the media query need `:not([data-theme='light'])`?
27. Why is a `MediaQuery('prefers-color-scheme: dark')` a poor way to switch component colors, and what do you use instead? When is it appropriate?
28. A library component renders `<h1>` and exposes no custom properties. The parent writes `div h1 { color: red }`. What happens, and what is the least invasive fix?
