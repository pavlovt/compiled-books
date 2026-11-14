# Chapter 20: Migrating from Svelte 4 (and Living with Legacy Mode)

Svelte 5 did not break the world. The compiler still accepts Svelte 3 and 4 syntax, and a component that uses none of the new rune syntax is compiled in “legacy mode” with the semantics it always had. That is both the good news and the trap: you can upgrade the package in an afternoon, but the codebase will continue to carry two programming models until you move it. This chapter is a migration manual for senior engineers: how mixed codebases behave, how the compiler decides which mode a file is in, what the automatic tooling does (we ran it and show its real output, including where it gives up), the syntax map from Svelte 4 to 5, the component API change from classes to functions, the full list of behaviour changes that bite in runes mode, the legacy APIs you will keep meeting in old code, and how to upgrade within 5.x and prepare for Svelte 6. It ends with a short look back at the v3 to v4 changes that still matter in very old codebases.

## Strategy: mixed codebases are the plan

The migration guide opens with the key fact: “You don’t have to migrate to the new syntax right away — Svelte 5 still supports the old Svelte 4 syntax, and you can mix and match components using the new syntax with components using the old and vice versa.” Plan the migration around that:

1.  **Upgrade the dependency first, change no syntax.** Get CI green on Svelte 5 with legacy components (fix the handful of true breaking changes listed below).
2.  **Migrate leaf components and shared logic first.** Leaves have no dependants to break; shared logic (stores, helpers) benefits most from rune modules.
3.  **Migrate component by component**, because each file is its own mode. A runes component can render a legacy one and vice versa; props, events (callback props versus `createEventDispatcher`) and snippets versus slots are the seams to watch.
4.  **Turn on runes enforcement last**, once nothing legacy remains, so regressions into old syntax are compile errors.

### How legacy mode is detected

Mode is decided per component. From the legacy overview: “Once a component is in runes mode (which you can opt into by using runes, or by explicitly setting the `runes: true` compiler option), legacy mode features are no longer available.”

- A component that uses any rune (`$state`, `$props`, …) is in runes mode. We compiled `let a = 0` with no options and `metadata.runes` was `false`; with `runes: true` it was `true`.
- `<svelte:options runes />` opts one component in (and `runes={false}` opts one out).
- `.svelte.js` and `.svelte.ts` modules (and any plain JS/TS module compiled with `compileModule`) are always runes mode.
- The compile option `runes` (boolean, `undefined` to infer, or `({ filename }) => boolean | undefined` since 5.54). “Will be `true` by default in Svelte 6.”

Mixing syntaxes inside one component is a compile error, with specific codes:

| You wrote (in a runes-mode component) | Compile error |
|------------------------------------|------------------------------------|
| `export let b` next to `$props()` | `legacy_export_invalid`: “Cannot use `export let` in runes mode — use `$props()` instead” |
| `$: b = a` next to `$state` | `legacy_reactive_statement_invalid` |
| `$$props` | `legacy_props_invalid`; `$$restProps` gives `legacy_rest_props_invalid` |
| `import { beforeUpdate } from 'svelte'` | `runes_mode_invalid_import`: “beforeUpdate cannot be used in runes mode” |
| `await` in markup without runes | `legacy_await_invalid` |

We reproduced the first, second and fourth. (At runtime, calling `beforeUpdate`/`afterUpdate` in runes mode would throw `lifecycle_legacy_only`.)

**A trap for project-wide enforcement.** Setting `compilerOptions.runes: true` in `svelte.config.js` forces runes mode “for your entire project, including components in `node_modules`”, which breaks any dependency still written in legacy syntax. Use the function form to exclude dependencies, or `dynamicCompileOptions` in `@sveltejs/vite-plugin-svelte`:

```js
// svelte.config.js
export default {
  compilerOptions: {
    runes: ({ filename }) => (filename.includes('node_modules') ? undefined : true)
  }
};
```

Returning `undefined` means “infer”, which keeps libraries working.

### Library authors

If you publish a component library, consider the consumers’ mode: a library compiled by the *consumer’s* build (the usual `svelte` export condition ships `.svelte` sources) is compiled in whatever mode each file declares, so legacy library components keep working in a runes application and the reverse. What can break is the interface: consumers using `on:event` against your `createEventDispatcher` events keep working as long as you keep dispatching; once you move to callback props, `on:` consumers must change. Slots versus snippets is asymmetric: “you can pass snippets to a component that uses slots… The reverse is not true — you cannot pass slotted content to a component that uses `{@render ...}` tags.” So a library moving to snippets is a breaking change for slot users, but a library that stays on slots keeps accepting both. Declare your supported range in `peerDependencies`, and publish a major when you change the public API shape, not merely the internal syntax. Components that must be class-instantiable by old consumers need `compatibility.componentApi: 4`, described below, and note that the consumer’s build, not yours, applies compile options to shipped sources.

## The tooling

### `npx sv migrate svelte-5`

The official script (“migrate script”) does the following, per the guide: bump core dependencies in `package.json`; migrate to runes (`let` to `$state`, and so on); migrate event directives to event attributes (`on:click` to `onclick`); migrate slot creations to render tags (`<slot />` to `{@render children()}`); migrate slot usages to snippets; migrate obvious component creations (`new Component(...)` to `mount(Component, ...)`). Two other entry points exist: the VS Code command “Migrate Component to Svelte 5 Syntax” and the Playground’s “Migrate” button, and the compiler exposes the same engine as `migrate(source, { filename, use_ts })` from `svelte/compiler`, which returns `{ code }`.

Run the migration on a clean git state, review the diff, and treat it as a first pass. To show what it does, we ran `migrate()` from 5.57.2 on a realistic Svelte 4 component:

```html
<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  export let items: string[] = [];
  export let title = 'List';
  let selected = '';
  let count = 0;
  $: total = items.length;
  $: if (total > 3) console.log('big');
  $: document.title = title + total;
  const dispatch = createEventDispatcher<{ pick: string }>();
</script>

<h1 class={title}>{title} ({total})</h1>
<ul>
  {#each items as entry}
    <li on:click|preventDefault={() => { selected = entry; dispatch("pick", entry); }}>
      <slot name="item" item={entry}>{entry}</slot>
    </li>
  {/each}
</ul>
<button on:click>go</button>
<input bind:value={selected} />
<svelte:component this={Foo} />
<slot />
```

Output (formatting as produced):

```html
<script lang="ts">
  import { run, preventDefault, createBubbler } from 'svelte/legacy';

  const bubble = createBubbler();
  import { createEventDispatcher } from 'svelte';
  interface Props {
    items?: string[];
    title?: string;
    item?: import('svelte').Snippet<[any]>;
    children?: import('svelte').Snippet;
  }

  let {
    items = [],
    title = 'List',
    item,
    children
  }: Props = $props();
  let selected = $state('');
  let count = 0;
  let total = $derived(items.length);
  run(() => {
    if (total > 3) console.log('big');
  });
  run(() => {
    document.title = title + total;
  });
  const dispatch = createEventDispatcher<{ pick: string }>();
</script>

<h1 class={title}>{title} ({total})</h1>
<ul>
  {#each items as entry}
    <li onclick={preventDefault(() => { selected = entry; dispatch("pick", entry); })}>
      {#if item}{@render item({ item: entry, })}{:else}{entry}{/if}
    </li>
  {/each}
</ul>
<button onclick={bubble('click')}>go</button>
<input bind:value={selected} />
<Foo />
{@render children?.()}
```

Read this carefully, because it shows the tool’s judgement calls:

- `export let` became a typed `$props()` destructuring with an inferred `Props` interface; default values and optionality are preserved. Slots became optional snippet props (`item`, `children`) with a conditional fallback (`{#if item}...{:else}{entry}{/if}`).
- `let selected = ''` became `$state('')` because it is bound and reassigned; `let count = 0` was left alone since it is never used reactively: dead variables are not turned into state.
- `$: total = items.length` became `$derived`. The other two `$:` statements became `run(...)` from `svelte/legacy`. The guide explains: “This happens if the migration script couldn’t reliably migrate the statement to a `$derived` and concluded this is a side effect instead… since `$:` statements also ran on the server but `$effect` does not, it isn’t safe to transform it as such. Instead, `run` is used as a stopgap solution. `run` mimics most of the characteristics of `$:`, in that it runs on the server once, and runs as `$effect.pre` on the client.” You need to decide, case by case: `document.title = ...` belongs in a client-only `$effect`; the `console.log` guard probably should be deleted.
- `on:click|preventDefault` became `onclick={preventDefault(...)}` using the `svelte/legacy` helper, and the forwarding `<button on:click>` became `createBubbler()`. Both are scaffolding to be removed by hand: call `event.preventDefault()` in the handler, and accept an `onclick` prop and pass it on.
- `<svelte:component this={Foo} />` became `<Foo />`.
- `createEventDispatcher` was left untouched, as were `import` placement oddities (the new import landed above the old one). The guide says why: “it’s too risky because it could result in breakage for users of the component, which the migration script cannot find out.”

### Where the tool gives up

Three runs of the same component showed the refusals, which appear as an `@migration-task` comment at the top of the file and a message that “one or more `@migration-task` comments were added… please check them and complete the migration manually”. The script leaves the *whole file* unmigrated in these cases:

1.  `beforeUpdate` present: `Can't migrate code with beforeUpdate. Please migrate by hand.` (`beforeUpdate`/`afterUpdate` are “not automigrated”; as a rule of thumb “you can often go with a combination of `$effect.pre` (runs at the same time as `beforeUpdate` did) and `tick`”.)
2.  `$$props` used together with named `export let` props: “`$$props` is used together with named props in a way that cannot be automatically migrated.”
3.  A slot whose name collides with a variable it would have to become a prop name: in our component, `<slot name="item" {item}>` inside `{#each items as item}` gave “This migration would change the name of a slot (item to item_1) making the component unusable.” (Renaming the loop variable to `entry`, as in the version we showed, let the migration succeed.)

Lesson: the tool is conservative when a rename would change a public API (slot names, props). Resolve those by hand first, then re-run.

### Review checklist after running the tool

- Search for `svelte/legacy` imports (`run`, `preventDefault`, `createBubbler`, `handlers`, …): each is a TODO.
- Search for `createEventDispatcher`: convert to callback props (and bump your component’s API version).
- Search for `beforeUpdate`, `afterUpdate`, `$$props`, `$$restProps`, `<slot`, `let:`, `<svelte:fragment`, `on:`, `use:`.
- Run `svelte-check` (`npx sv check`): the migration can leave type holes (`Snippet<[any]>` in our output).
- Run your tests and exercise forms (bindings changed behaviour, see below).

## The syntax map

| Svelte 4 | Svelte 5 (runes) | Notes |
|------------------------|------------------------|------------------------|
| `let x = 0` (top level, reactive) | `let x = $state(0)` | Only variables that must be reactive; mutations of objects/arrays are deep by default |
| `$: y = f(x)` | `let y = $derived(f(x))` | Always current; no ordering problems |
| `$: { sideEffect(x) }` | `$effect(() => { sideEffect(x) })` | Runs in the browser only, after DOM updates. Use `$effect.pre` for “before DOM update” |
| `export let a = 1` | `let { a = 1 } = $props()` | Rename: `let { class: klass } = $props()` |
| `$$props` / `$$restProps` | `let props = $props()` / `let { a, ...rest } = $props()` |  |
| `export function f() {}` | unchanged | Instance exports remain the component API |
| `bind:` to an `export let` | `let { v = $bindable() } = $props()` | Bindings must be declared |
| `on:click={h}` | `onclick={h}` | Attribute; no modifiers |
| `on:click` (forward) | `let { onclick } = $props()` then `{onclick}`, or spread `{...rest}` |  |
| `createEventDispatcher` | callback props | Payload no longer wrapped in `.detail` |
| `<slot />` | `{@render children?.()}` | `children` prop is reserved |
| `<slot name="x" a={b}>` / `let:a` | `{@render x?.(b)}` / `{#snippet x(a)}...{/snippet}` |  |
| `<svelte:fragment slot="x">` | `{#snippet x()}...{/snippet}` |  |
| `<svelte:component this={C} />` | `<C />` | Capitalised variable, or dot notation (`<item.component />`) |
| `<svelte:self />` | import the component itself: `import Self from './Self.svelte'` | Warning `svelte_self_deprecated` |
| `class:active={x}` | `class={['base', { active: x }]}` | clsx-style arrays/objects (5.16) |
| `use:action={arg}` | `{@attach fn}` | Attachments (5.29) are reactive: they re-run when state they read changes; actions run once |
| `{@const x = ...}` | `{const x = ...}` / `{let ...}` (5.56) | `{@const}` is documented as legacy syntax |
| `beforeUpdate` / `afterUpdate` | `$effect.pre` / `$effect` (+ `tick`) | Compile error to import them in runes mode |
| `writable` stores in components | `$state` in `.svelte.ts` classes/functions | Stores remain supported and sometimes appropriate |
| `new App({...})` | `mount(App, {...})` | See below |
| `<script context="module">` | `<script module>` | Warning `script_context_deprecated` |

Some of these deserve a paragraph.

**Reactive statements to deriveds and effects.** The migration guide’s rationale is worth internalising because it changes how you write: `$:` “only updated directly before rendering” (stale reads in between), “only ran once per tick”, used *static* dependency analysis (breaking when logic moved into a function) and static ordering. `$derived` and `$effect` track dependencies at runtime and always return the latest value. Roughly 90% of `$:` statements become `$derived`; for the rest, decide whether each is a real side effect, and remember `$:` also ran on the server, while `$effect` never does. A migrated `$:` block that reads and writes the same value is flagged at runtime with `legacy_recursive_reactive_block` (“Detected a migrated `$:` reactive block in `%filename%` that both accesses and updates the same reactive value. This may cause recursive updates when converted to an `$effect`”).

**Events.** `on:` and `createEventDispatcher` were two mechanisms; callback props unify them. The guide lists the benefits: no `CustomEvent` allocation for events nobody listens to, the ability to spread handlers, to know which handlers were provided, to mark them required or optional, and real type safety. The costs: modifiers are gone (`once`, `preventDefault`, `self`, `trusted`, `stopPropagation` become wrapper functions or code in the handler; `capture` becomes `onclickcapture`; `passive`/`nonpassive` need an action/attachment using `on` from `svelte/events`); duplicate handlers on one element are an error (combine them in one function); and when spreading, put local handlers *after* the spread so they are not overwritten.

**Slots.** `children` replaces the default slot; each named slot becomes a prop holding a snippet; `let:` becomes snippet parameters. Because named slots ceased to be special elements, “sometimes you didn’t want to create an element, so we had to add the `<svelte:fragment>` API” disappears.

**Dynamic components.** In Svelte 4 `<Thing />` was static: if `Thing` changed, nothing happened. In Svelte 5 it is dynamic, so `<svelte:component>` is unnecessary (warning `svelte_component_deprecated`). Keep the component variable capitalised, or use dot notation (`<item.component {...item.props} />`, which in Svelte 4 would have created an element named `item.component`). For complex resolution, a capitalised `$derived` works: `const Component = $derived(condition ? Y : Z)`.

## Components are functions

In Svelte 3 and 4 components were classes; in Svelte 5 they are functions. Code that instantiates components must change, and the runtime error you meet first is `component_api_invalid_new` (“Attempted to instantiate %component% with `new %name%`, which is no longer valid in Svelte 5. If this component is not under your control, set the `compatibility.componentApi` compiler option to `4` to keep it working.”), or its sibling `component_api_changed` for calling `$set`/`$on`/`$destroy` on an instance.

```ts
// Svelte 4
import App from './App.svelte';
const app = new App({ target: document.getElementById('app')!, props: { foo: 'bar' } });
app.$set({ foo: 'baz' });
app.$on('event', callback);
app.$destroy();

// Svelte 5
import { mount, unmount } from 'svelte';
import App from './App.svelte';

const props = $state({ foo: 'bar' });          // in a .svelte.ts file
const app = mount(App, {
  target: document.getElementById('app')!,
  props,
  events: { event: callback }                  // discouraged: use callback props
});
props.foo = 'baz';                              // replaces $set
await unmount(app);                             // replaces $destroy
```

| Svelte 4 | Svelte 5 replacement |
|------------------------------------|------------------------------------|
| `new C({ target, props })` | `mount(C, { target, props })` |
| `hydrate: true` option | `hydrate(C, { target, props })` |
| `$set(props)` | mutate a `$state` props object passed as `props` |
| `$on(ev, cb)` | callback props; or `events` option (discouraged) |
| `$destroy()` | `unmount(component, { outro?: boolean })` (`outro` since 5.13) |
| `app.prop` accessors (`accessors: true`) | component exports, or `$state` props object |
| `intro: false` by default | `mount` plays transitions by default; pass `intro: false` |
| `C.render(props)` on the server | `render(C, { props })` from `svelte/server` |
| `{ html, head, css }` result | `{ body, head }`; `html` deprecated; no CSS unless `css: 'injected'` |

`mount` and `hydrate` take the same options and “are *not* synchronous”: effects, `onMount` and `#await` pending blocks have not run when they return, so call `flushSync()` if you need that guarantee (Chapter 16 uses this constantly). `mount` returns the component’s exports, not an instance with methods. With `bind:this` the same applies: you get the exports (`export function`/`export const`), plus accessors if `accessors` is set, and no `$set`/`$on`/`$destroy`.

### Stopgaps: `createClassComponent`, `asClassComponent`, `componentApi: 4`

Three escape hatches keep old call sites alive, all deprecated:

- `createClassComponent({ component, target, ... })` from `svelte/legacy`: wraps a component and returns an object with the Svelte 4 API. Use it where *you* instantiate components and cannot yet rewrite the call.
- `asClassComponent(Component)`: converts a component function into a class, for passing to third-party code that does `new`.
- The compile option `compatibility: { componentApi: 4 }`: applies the wrapper to every compiled component, so `new Component(...)` keeps working without changes. We compiled with it and the output imports the legacy class wrapper. The guide notes it “adds a bit of overhead to each component” and “will also add `$set` and `$on` methods for all component instances you get through `bind:this`”. It is meant for components “not under your control”, for example a dependency.

```js
// svelte.config.js : only while migrating
export default {
  compilerOptions: { compatibility: { componentApi: 4 } }
};
```

The compile warning `legacy_component_creation` (“Svelte 5 components are no longer classes. Instantiate them using `mount` or `hydrate`”) flags `new` usage statically.

### Typing the change

`SvelteComponent` (the base class), `SvelteComponentTyped`, `ComponentType` and `ComponentEvents` are deprecated. Use `Component<Props, Exports, Bindings>` for the function shape and `ComponentProps<typeof C>` to extract props:

```ts
import type { Component } from 'svelte';
import { ComponentA, ComponentB } from 'component-library';

// Svelte 4: let C: typeof SvelteComponent<{ foo: string }> = ...
let C: Component<{ foo: string }> = $state(Math.random() ? ComponentA : ComponentB);
```

`ComponentEvents` is obsolete because events are callback props; `ComponentType<SvelteComponent<{ prop: string }>>` is equivalent to `Component<{ prop: string }>`. In `.d.ts` files, `export declare const MyComponent: Component<{ foo: string }>`.

## Behaviour changes that bite

Most of the following are either enforced in runes mode or apply to all modes. Treat them as a regression-test checklist.

**Bindings and exports** - `export const foo` in a runes component cannot be bound (`<A bind:foo />` is an error); use `bind:this={a}` and `a.foo`. Props, not exports, are bindable. - A prop is bindable only if declared `$bindable()`. If a bindable prop has a fallback (`$bindable('bar')`), a parent that binds must pass a non-`undefined` value (`props_invalid_value` otherwise). In Svelte 4 the default flowed back to the parent, causing extra renders. - `accessors` and `immutable` options are ignored in runes mode (warnings `options_deprecated_accessors`/`options_deprecated_immutable`); `$state` replaces immutability concerns. - `bind:files` is two-way and accepts only `null`, `undefined` or a `FileList`. Bindings react to `form.reset()`. - `contenteditable` with a binding and reactive content inside: the binding takes full control and the content is not updated by other state.

**Reactivity model** - Classes are not “auto-reactive”. Mutating `foo.value` on a `new Foo()` no longer triggers updates, because reactivity is runtime now. Declare `$state` fields in the class; wrapping `new Foo()` in `$state(...)` does nothing (only plain objects and arrays are proxied). - Array mutation methods now work on `$state` arrays; the `numbers = numbers` self-assignment idiom is unnecessary.

**Template and HTML** - Attribute syntax is stricter: concatenations must be quoted (`prop="this{is}valid"`); a single quoted expression (`answer="{42}"`) warns (`attribute_quoted`) because in Svelte 6 it will become a string. - HTML structure is stricter: markup the browser would repair (a `<table><tr>` without `<tbody>`) is a compile error; `node_invalid_placement_ssr` is the warning variant. - Whitespace: collapsed to one space between nodes and trimmed at tag starts and ends, so `<p>foo<span> - bar</span></p>` renders `foo- bar`. Opt out with `preserveWhitespace`. - `null` and `undefined` render as the empty string (previously the literal text). - `oneventname` attributes no longer accept strings (`onclick="alert('hello')"` is gone). - `<svelte:element this="div">` must use an expression (`this={"div"}`), and bind applicability is no longer inferred from a literal tag. - Content inside `<svelte:options>` is a compile error; `<slot>` inside `<template shadowrootmode>` is preserved. - `{@const}` assignments to destructured parts are disallowed.

**Events** - Touch events `ontouchstart`/`ontouchmove` are passive. To prevent defaults, use `on` from `svelte/events` (for example in an attachment). - Many event attributes are *delegated* (`click`, `input`, `keydown`, `pointerdown`, … see Chapter 6). Manually stopping propagation, or dispatching non-bubbling events, can prevent delivery. Event attributes fire after events from bindings. - No multiple `on:click` on one element; duplicates are an error.

**CSS** - `:is(...)`, `:has(...)`, `:where(...)` are now analysed in component scope; selectors relying on the old global treatment become unused (`css_unused_selector`); wrap them in `:global(...)` (Tailwind `@apply` needs a `:global` block). - Scoped selectors use `:where(.svelte-xyz)`, so specificity is lower and more predictable; the hash position is no longer guaranteed. - `--style-props` on components wrap in `<svelte-css-wrapper>` (display `contents`) instead of a `<div>`, which affects child combinators.

**Runtime and compiler** - `mount` plays transitions by default (`intro` defaults to `true`), unlike manually instantiated classes. - Hydration: Svelte 5 uses comment markers in server output; do not strip comments from HTML you intend to hydrate. `<img src>` and `{@html}` hydration mismatches are no longer repaired (`hydration_attribute_changed`, `hydration_html_changed` warnings; use the stash/unset/restore effect from the guide to force it). - `beforeUpdate`/`afterUpdate`: legacy-only; child `afterUpdate` runs before the parent’s; no longer run when slot content updates. - `onDestroy` runs child-first. - Compiler options removed or changed: `css` no longer accepts `true`/`false`/`'none'`; `legacy` repurposed; `hydratable`, `enableSourcemap`, `tag`, `loopGuardTimeout`, `format`, `sveltePath`, `errorMode`, `varsReport` removed (each yields a specific `options_removed_*` warning or an `options_removed` error); `generate: 'dom'|'ssr'` became `'client'|'server'` (`options_renamed_ssr_dom`); `namespace` is now only `html`, `svg` or `mathml` (`foreign` removed). - Error and warning codes were renamed from dashes to underscores (`foo-bar` to `foo_bar`): update any `svelte-ignore` comments and `warningFilter` code that used the old names; unknown codes warn with `unknown_code` and a “did you mean” suggestion, and legacy dashed codes warn with `legacy_code`. - `walk` is no longer re-exported from `svelte/compiler`; import `estree-walker` directly. - The runtime needs a modern browser (Proxy, `ResizeObserver`), and `<input type="range" bind:value>` listens only to `input`. - Stricter library rules: `children` is a reserved prop name when a component has content; the `$store` auto-subscription still works, with `store_rune_conflict` if a local binding collides with a rune name.

## Legacy API reference

You will read and maintain legacy code for a long time. This is a compact reference to what you will meet (all of it still compiles in legacy mode).

**`$$props` and `$$restProps`.** `$$props` holds all props including undeclared ones; `$$restProps` holds those not declared with `export let`. Typical use was forwarding: `<button {...$$restProps} class="variant-{variant} {$$props.class ?? ''}">`. They carry “a modest performance penalty”. Runes equivalent: destructure with `...rest`.

**`$$slots`.** An object telling which slots the parent provided (`{#if $$slots.footer}`). Runes equivalent: check whether the snippet prop is defined (`{#if footer}`).

**`on:` directive and modifiers.** `|preventDefault`, `|stopPropagation`, `|stopImmediatePropagation`, `|passive` (Svelte adds it automatically where safe), `|nonpassive`, `|capture`, `|once`, `|self`, `|trusted`, chainable (`on:click|once|capture`). A bare `on:click` forwards the event. Multiple `on:click` on one element are allowed in legacy mode. The `svelte/legacy` helpers exist to ease migration only: `handlers(...)`, `createBubbler()`, `once`, `preventDefault`, `stopPropagation`, `stopImmediatePropagation`, `self`, `trusted`, `passive(node, [event, handler])`, `nonpassive(node, [event, handler])`, and `run(fn)`. All are deprecated.

**Reactive declarations.** `$:` statements are ordered topologically by static analysis of their dependencies and assignments; the dependencies are “whichever variables are referenced (but not assigned to) inside the statement”. Calling a function that reads state hides the dependency (`$: doubled = double()` never updates when `count` changes inside `double`). They also run during SSR, so browser-only code needs an `if (browser)`-style guard. The compiler warns `reactive_declaration_invalid_placement` for `$:` below the top level and `reactive_declaration_module_script_dependency` for dependencies on reassigned module-level variables.

**Props.** `export let foo` (required unless it has a default; the warning for a missing required prop can be silenced with `= undefined`), unused exports warn `export_let_unused`, renaming with `export { className as class }`, `export const`/`export function` as component API. If a parent changes a prop from a defined value to `undefined`, it does *not* revert to the default in legacy mode (it does in runes mode).

**Slots and fragments.** `<slot name="x" prop={v}>` with fallback content, `let:prop` on the consumer, `slot="x"` on elements or components, `<svelte:fragment slot="x">` to fill a slot without a wrapper element, `$$slots`. Warning `slot_element_deprecated`. Mixing is checked at runtime: `{@render children(...)}` in a child used by a parent that passes `let:` directives is the shared error `invalid_default_snippet` (“Cannot use `{@render children(...)}` if the parent component uses `let:` directives. Consider using a named snippet instead”).

**`<svelte:self>` and `<svelte:component>`.** `<svelte:self>` lets a component render itself recursively; the modern replacement is importing the file into itself (`svelte_self_deprecated`). `<svelte:component this={X}>` for dynamic components (`svelte_component_deprecated`).

**Legacy component API (class-based).** Options for `new Component(options)`: `target` (required), `anchor`, `props`, `context` (`Map`), `hydrate`, `intro` (default `false` here, unlike `mount`). Methods: `$set(props)` (update scheduled for the next microtask), `$on(event, callback)` (returns an unsubscribe function), `$destroy()`. For server rendering, `Component.render(props, options)` returned `{ html, css, head }`. These apply to Svelte 3/4 and to legacy-compatible components under `componentApi: 4`; the docs state that the page “does *not* apply to legacy mode components in a Svelte 5 application” in the general case.

**Legacy-mode runtime notes.** `beforeUpdate`/`afterUpdate`, `$$props`, `$:` and `export let` only exist here. Reactivity is assignment-based: `numbers.push(4)` needs a follow-up `numbers = numbers`, and top-level `let` is implicitly reactive. Legacy mode compiles with extra compatibility imports (we saw `import 'svelte/internal/flags/legacy'` in compiled output), which is a small bundle cost that disappears once nothing needs it.

## Tooling migration

- **Vite plugin.** Use a `@sveltejs/vite-plugin-svelte` release that supports Svelte 5 and your Vite version. As of October 2026, `@sveltejs/vite-plugin-svelte` 7.3.1 declares peer dependencies `vite ^8.0.0` and `svelte ^5.46.4`, so it pairs with Svelte 5.57 on Vite 8; check the plugin’s release notes when you upgrade either.
- **Vitest.** Add the `browser` resolve condition and rename test files that use runes to `*.svelte.test.ts`; replace `new Component` tests with `mount`/`flushSync`/`unmount`, or `@testing-library/svelte` (Chapter 16). `component.$set` in tests becomes a `$state` props object.
- **ESLint.** `eslint-plugin-svelte3` is deprecated (since v4); use `eslint-plugin-svelte`.
- **Prettier.** `prettier-plugin-svelte`.
- **svelte-check.** `npx sv check`. Run it after every migration step; the migration output commonly has `any` types in snippet parameters.
- **TypeScript.** Svelte 4 required TypeScript 5; in Svelte 5, only type-only syntax is supported inside `<script lang="ts">` without a preprocessor (Chapter 15). Replace `svelte.JSX` namespace usage with `svelte/elements` and `svelteHTML`.
- **Preprocessors.** Each must have a `name` today (and `PreprocessorGroup.name` becomes required in the next major); order is group by group, with markup, script, style within a group (since Svelte 4).
- **Storybook.** Use the Svelte CSF addon (`@storybook/addon-svelte-csf`) with `defineMeta` (Chapter 16).

## Upgrading within 5.x

New minor versions are additive, but they also add warnings, tighten validation, and promote some features. A short history helps decide when to adopt things:

| Version | Notable additions |
|------------------------------------|------------------------------------|
| 5.3 | `<svelte:boundary>` |
| 5.4 | `{#each}` without `as` |
| 5.5 | export snippets from `<script module>` |
| 5.6 | `defaultValue`/`defaultChecked` |
| 5.7 | `createSubscriber`, `MediaQuery`, `prefersReducedMotion` |
| 5.8 | `Spring` and `Tween` classes |
| 5.9 | function bindings |
| 5.11 | `svelte/reactivity/window` |
| 5.13 | `unmount(..., { outro })` |
| 5.14 | `$inspect.trace` |
| 5.16 | `class` accepts objects/arrays |
| 5.20 | `$props.id()` |
| 5.25 | writable `$derived` |
| 5.29 | attachments |
| 5.30 | generics on snippets |
| 5.35 / 5.36 | `getAbortSignal`; experimental `await` and `settled` |
| 5.40 | `createContext` (5.57 added `has`, so it is a `[get, set, has]` triplet) |
| 5.41, 5.42, 5.44 | `$state.eager`, `fork`, `hydratable` (the last two require `experimental.async`) |
| 5.47 | customizable `<select>` |
| 5.49 | `ShadowRootInit`; context wrapper pattern for `mount` |
| 5.54 | function forms of `css`, `runes`, `customElement` |
| 5.56 | declaration tags `{const}`/`{let}` |
| 5.57 | `createContext` `has`; `<select defaultValue>`; `SvelteMap.getOrInsert*`; server render types exported |

Checklist for a minor/patch upgrade:

1.  Read the changelog entries between your version and the target, scanning for “breaking”, “deprecate” and new warnings.
2.  Upgrade `svelte`, the Vite plugin and `svelte-check` together.
3.  Run the compile (build) and look at *new warnings*: they are often real bugs (`state_referenced_locally`, a11y checks).
4.  Run unit, component, SSR/hydration and E2E layers (Chapter 16).
5.  If you use `experimental.async` and everything that depends on it, re-test those paths specifically; they can change outside semver.
6.  Do not rely on compiled output shape, `svelte/internal/*` (a compile error to import) or hydration comment formats.

## Looking ahead to Svelte 6

The documentation names these planned changes. Prepare now:

- **`runes` defaults to `true`.** Legacy components will need `<svelte:options runes={false} />` or migration. Start with the function form of the `runes` option to make new directories runes-only.
- **Quoted single expressions become strings.** `answer="{42}"` will pass `"42"`. Remove needless quotes (warning `attribute_quoted` already tells you).
- **All falsy `class` values will omit the attribute** (today `false`/`NaN` stringify while `undefined`/`null` omit it).
- **The `experimental.async` flag is removed**, and async becomes the default, with `flush_sync_in_effect` and `set_context_after_init` restrictions applying everywhere (the docs say the flag “will be removed in Svelte 6”). Avoid calling `flushSync` inside effects and `setContext` after an `await` now.
- **`parse()` returns the modern AST by default** (the `modern` option is removed in Svelte 7); `PreprocessorGroup.name` is required; the `flushSync` callback argument may be removed (a source comment suggests this).

## A brief look back: v3 to v4

Old codebases may still carry v3-era assumptions. The v4 migration guide items that remain relevant:

- **Tooling floors**: Node 16+, TypeScript 5+, Vite plugin 2.4.1+, webpack 5 with `svelte-loader` 3.1.8+, Rollup plugin 7.1.5+.
- **Browser condition.** Bundlers must specify the `browser` condition for frontend bundles, or lifecycle callbacks such as `onMount` do not run (the same condition Vitest needs in Chapter 16).
- **CJS removed.** No CommonJS compiler output, no `svelte/register`.
- **Stricter types** for `createEventDispatcher`, `Action`/`ActionReturn` (default parameter type `undefined`), and `onMount` (returning a cleanup function asynchronously is flagged as a bug: only synchronous returns are used for cleanup).
- **`tag` to `customElement`** for custom elements (Chapter 19).
- **`SvelteComponentTyped` deprecated** in favour of `SvelteComponent`, itself deprecated in Svelte 5.
- **Transitions are local by default**: they do not play when an ancestor block, not their own parent block, toggles; add `|global`.
- **Default slot bindings** are no longer exposed to named slots, and vice versa.
- **Preprocessor order** (group by group, markup, script, style) and mandatory preprocessor names; put MDsveX before script/style preprocessors.
- **`eslint-plugin-svelte3` deprecated** in favour of `eslint-plugin-svelte`.
- **Other**: `inert` applied to outroing elements; `classList.toggle(name, boolean)` and `CustomEvent` constructor usage (polyfills for ancient browsers); custom stores implementing `StartStopNotifier` must accept an `update` function; `derived` throws on falsy store arguments; `svelte/internal` typings removed; `svelte.JSX` namespace replaced by `svelte/elements` and `svelteHTML`.

## A migration runbook

1.  Create a branch; upgrade `svelte`, plugin, Vite, `svelte-check`, Prettier/ESLint plugins; run the build with legacy components untouched; fix hard breaks (class instantiation, options removed, HTML structure errors, `svelte/internal` imports, code renames in `svelte-ignore`).
2.  Add `compatibility.componentApi: 4` temporarily only if third-party components are still instantiated with `new`.
3.  Convert shared logic to `.svelte.ts` modules; keep store-based APIs for consumers that need them, or expose both.
4.  Run `npx sv migrate svelte-5` per directory; resolve `@migration-task` comments; remove `svelte/legacy` helpers; convert `createEventDispatcher` to callback props; replace `beforeUpdate`/`afterUpdate`.
5.  After each batch: `npx sv check`, tests, a manual pass on forms (bindings and reset), transitions (`mount` intro default), and SSR hydration.
6.  When no legacy file remains, set `runes: true` (function form to exclude `node_modules`), delete `compatibility`, and add a lint rule against `svelte/legacy` imports.

## Key takeaways

- Legacy and runes components interoperate; mode is decided per file (runes if any rune or `runes: true`/`<svelte:options runes>`; `.svelte.ts` always runes). Mixing syntaxes in one component is a compile error with specific codes.
- Use `npx sv migrate svelte-5`, the VS Code command or `migrate()` from `svelte/compiler` as a first pass. It leaves `createEventDispatcher` and `beforeUpdate`/`afterUpdate` alone, emits `run()` and other `svelte/legacy` helpers as stopgaps, and refuses files with `$$props` plus named props, `beforeUpdate`, or slot-name collisions.
- Core syntax map: `let` to `$state`, `$:` to `$derived`/`$effect`, `export let` to `$props`, `on:` to attributes, slots to snippets, `<svelte:component>` and `<svelte:self>` to direct usage, `use:` to `{@attach}`, `class:` to class arrays/objects.
- Components are functions: use `mount`/`hydrate`/`unmount`; `$set` becomes a `$state` props object; `$on` becomes callback props; server `render` returns `{ body, head }`. Stopgaps: `createClassComponent`, `asClassComponent`, `compatibility.componentApi: 4`.
- Runes-mode behaviour changes to test: bindings require `$bindable`, classes need `$state` fields, strict attribute and HTML rules, whitespace, `null` renders empty, passive touch events, delegated events, scoped `:is/:where/:has`, `mount` plays intros, stricter hydration.
- Typing: `Component` replaces `SvelteComponent`, `ComponentType` and `ComponentEvents`.
- Setting `runes: true` globally forces runes into `node_modules`; use the function form.
- Within 5.x, read the changelog, treat new warnings as work, and isolate experimental features. Prepare for Svelte 6: runes by default, quoted expressions become strings, falsy `class` omission, async flag removal, modern AST.

## Review Questions

1.  How does the compiler decide whether a component is in legacy mode or runes mode? Give three ways a component enters runes mode.
2.  What happens when a component contains both `$props()` and `export let`? Which error code?
3.  Why is setting `compilerOptions.runes: true` in `svelte.config.js` dangerous for an app with legacy dependencies, and what are two safer alternatives?
4.  A library you publish ships `.svelte` sources written in legacy syntax. Will they work in a runes-mode consumer? What is asymmetric about passing slots and snippets between old and new components?
5.  List five things `npx sv migrate svelte-5` does and three things it does not do automatically.
6.  After migration, you see `import { run } from 'svelte/legacy'` and `run(() => { document.title = title })`. Explain what `run` does on the server and on the client, and what you would replace it with.
7.  Why does the migration tool leave `createEventDispatcher` alone?
8.  Name three situations in which `migrate()` refuses to migrate a file, as observed in the chapter.
9.  Convert to Svelte 5 syntax:

```html
<script>
  export let value = 0;
  $: doubled = value * 2;
  $: if (doubled > 10) console.log('big');
</script>
<button on:click={() => (value += 1)}>{doubled}</button>
```

10. Convert a Svelte 4 component that dispatches `dispatch('save', { id })` and is used as `<Form on:save={(e) => handle(e.detail)} />`.
11. How do you replace `<slot name="item" {entry} />` with `let:entry` on the consumer side, in Svelte 5?
12. Why is `<svelte:component this={X} />` no longer needed, and how do you handle a conditional component choice?
13. What does `$set`, `$on`, `$destroy` become in Svelte 5? Show code for each.
14. What does `mount` return, and why must you call `flushSync` after it if you need `onMount` to have run?
15. What is `compatibility.componentApi: 4`, when would you use it, and what does it cost?
16. When would you choose `createClassComponent` over `componentApi: 4`?
17. What changed in `render` on the server (function shape, result fields, CSS)?
18. Which types replace `SvelteComponent`, `ComponentType` and `ComponentEvents`, and why is `ComponentEvents` obsolete?
19. Explain why `<A bind:foo />` fails when `foo` is `export const foo` in a runes-mode component A, and what to do instead.
20. A parent binds `<Child bind:value={undefined} />` and Child declares `let { value = $bindable('x') } = $props()`. What happens?
21. In Svelte 4, `foo.value = 1` on `let foo = new Foo()` updated the UI. Why does it not in Svelte 5, and what is the fix?
22. What whitespace change could alter the rendering of `<p>foo<span> - bar</span></p>`? What does it render?
23. Why would a Tailwind `@apply` rule using `:is(...)` suddenly be reported as an unused selector, and what is the fix?
24. A touch handler calls `event.preventDefault()` in `ontouchstart` and scrolling is no longer prevented. Why, and how do you fix it?
25. Which compile-time warning/error tells you a Svelte 4 `new App()` call remains, and which runtime error do you see for it?
26. After upgrading, `svelte-ignore a11y-click-events-have-key-events` comments stop working. Why?
27. List four items from the Svelte 6 outlook that you can prepare for today.
28. Multiple choice: which statement about `mount` is true?

<!-- -->

a.  It returns a component instance with `$set` and `$destroy`.
b.  It runs effects synchronously before returning.
c.  It plays intro transitions by default.
d.  It hydrates existing server-rendered HTML.

<!-- -->

29. Which v4-era rule explains why `onMount` callbacks do not run when a bundler is misconfigured, and how does the same condition appear in Vitest?
30. Why might you keep a `writable` store in a migrated codebase?
