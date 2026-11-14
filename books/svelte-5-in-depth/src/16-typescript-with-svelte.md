# Chapter 15: TypeScript with Svelte

Svelte’s TypeScript story changed fundamentally with runes. In Svelte 4, types lived in a mix of `export let` annotations, `createEventDispatcher<...>()` generics, `$$Props` interfaces and a class-based `SvelteComponent<Props, Events, Slots>`. In Svelte 5 components are plain functions, props are an ordinary destructured object, events are callback props, slots are snippets, and the types are the ordinary types of ordinary values. Almost everything you need is `interface Props`, `Snippet`, `Component` and the attribute interfaces in `svelte/elements`.

The other half of the story is the toolchain. The Svelte compiler understands only the *type-only* subset of TypeScript (it parses it and erases it); type *checking* is done by `svelte-check` and the editor tooling; and anything that needs real transpilation needs a preprocessor. Knowing which layer is responsible for which behaviour is what lets you diagnose the otherwise confusing situations: an error that the editor shows but the build ignores, a build error that the editor does not show, or a `.ts` file that cannot see exports from a `.svelte` file.

This chapter covers configuration, typing props, generics, snippets, the `Component` family of types, `$state` and `$derived`, wrapper components, augmenting DOM types, typing actions, attachments, transitions and stores, `.svelte.ts` modules, and JSDoc for JavaScript projects. I verified type behaviour with `svelte-check` against `svelte@5.57.2`; error messages quoted below are real output.

## What the compiler supports, and what it does not

With `<script lang="ts">`, Svelte parses TypeScript and *removes* it. Per the docs you may use TypeScript’s “*type-only* features. That is, all features that just disappear when transpiling to JavaScript, such as type annotations or interface declarations.” Type annotations, `interface`/`type`, generics, `as`, `satisfies`, `!` non-null assertions and `import type` all work. Features that require the TypeScript compiler to *emit code* do not:

- `enum` (non-`const`),
- constructor parameter properties (`constructor(private x: number)`),
- non-standard syntax not yet implemented by the parser (old-style decorators, namespaces).

Using them yields the compile error `typescript_invalid_feature`: “TypeScript language features like enums are not natively supported … For use within `<script>` tags, you will need to use a preprocessor”. I verified it for `enum` and for a constructor parameter property; `satisfies`, `as` and `generics` compiled fine.

The remedy is a script preprocessor. With Vite:

```js
// svelte.config.js
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

export default {
    // Note the additional `{ script: true }`
    preprocess: vitePreprocess({ script: true })
};
```

(`vitePreprocess` without `script: true` preprocesses styles only; the error message even reminds you of this.) For other bundlers the docs point to `svelte-preprocess` plus the `typescript` package.

> **Senior tip:** Prefer the erasable subset anyway. Replace `enum` with a `const` object plus a union type (`const Level = { Low: 0, High: 1 } as const; type Level = (typeof Level)[keyof typeof Level]`), replace parameter properties with explicit fields, and consider enabling TypeScript’s `erasableSyntaxOnly` compiler option in your tsconfig so the editor flags non-erasable syntax in `.ts` files too. This keeps `.svelte` and `.ts` files under the same rules and removes the need for a script preprocessor. (The docs mention “erasable syntax only” specifically for the custom element `extend` function, where code outside the `<script>` is not preprocessed.)

Two more limits: TypeScript syntax is accepted only inside `<script lang="ts">` and in expressions *when the component declares a TS script*. In the template, annotations like `onclick={(e: MouseEvent) => ...}` only parse if some `<script lang="ts">` exists in the file (an empty one suffices): without it, I got `js_parse_error` at the colon. And the `.svelte.ts`/`.svelte.js` module files that hold runes are compiled by the Svelte compiler with the same type-erasure rule, after Vite’s own TypeScript transform has had its chance.

## `tsconfig.json`

The docs list three requirements:

- `target` of at least `ES2015`, “so classes are not compiled to functions” (class fields with runes depend on real classes);
- `verbatimModuleSyntax: true`, “so that imports are left as-is”. This matters because Svelte decides which imports are used in the *template* after the TS tooling has run; if TypeScript dropped an import that only the template uses, the component would break. With `verbatimModuleSyntax` you must write `import type` for type-only imports, which is also what keeps component imports alive;
- `isolatedModules: true`, “so that each file is looked at in isolation”, because neither the Svelte compiler nor Vite does cross-file analysis.

A working baseline, which is what I used in the checks:

```json
{
    "compilerOptions": {
        "target": "ESNext",
        "module": "ESNext",
        "moduleResolution": "bundler",
        "verbatimModuleSyntax": true,
        "isolatedModules": true,
        "strict": true,
        "skipLibCheck": true,
        "noEmit": true
    },
    "include": ["src/**/*"]
}
```

Add `"allowImportingTsExtensions": true` if you import `./x.svelte.ts` with the extension, and your bundler’s types (`vite/client`) as needed. Create-vite/`sv create` templates set all of this up.

### Checking: `svelte-check`, `sv check`, the editor

`tsc` cannot read `.svelte` files. Type checking is performed by **`svelte-check`** (CLI, suitable for CI: `npx sv check` or `npx svelte-check --tsconfig ./tsconfig.json`), by the **Svelte for VS Code** extension in the editor, and by equivalent plugins in other editors. They share one engine (the Svelte language tools), which transforms each component into TypeScript that `tsc`’s language service can analyse. Notes:

- `svelte-check` also reports Svelte compiler warnings, including accessibility checks (`a11y_*`). In my run an empty button was reported as `a11y_consider_explicit_label` alongside the type errors, and it can be filtered with its `--threshold` option.
- The build (Vite) does **not** type-check. A green build and a red `svelte-check` is normal; run both in CI.
- TypeScript files that import from `.svelte` files rely on the `*.svelte` ambient module declaration shipped with Svelte, which types default exports loosely (as `LegacyComponentType`); the editor plugin (`typescript-svelte-plugin`, bundled in the VS Code extension) provides precise types, including for `<script module>` exports, in `.ts` files. Plain `tsc` on a `.ts` file importing a `.svelte` component sees the loose type. Run `svelte-check` for the real result, or generate `.d.ts` for libraries with `svelte-package`.

## Typing `$props`

Props are a destructured object; type that object like any other. From the docs:

```html
<script lang="ts">
    import type { Snippet } from 'svelte';

    interface Props {
        requiredProperty: number;
        optionalProperty?: boolean;
        snippetWithStringArgument: Snippet<[string]>;
        eventHandler: (arg: string) => void;
        [key: string]: unknown;
    }

    let {
        requiredProperty,
        optionalProperty,
        snippetWithStringArgument,
        eventHandler,
        ...everythingElse
    }: Props = $props();
</script>
```

Points that matter in real code:

- **Required vs. optional** is just `?` in the interface. A default in the destructuring (`optionalProperty = false`) supplies a fallback for `undefined`; with a default you can keep the type `boolean` while marking the prop optional (`optionalProperty?: boolean` and a default means the local variable is `boolean`).
- **`$bindable`**. Mark bindable props in the destructuring: `let { value = $bindable('') }: { value?: string } = $props();`. The parent’s `bind:value` is then checked: binding to a prop that is not bindable is a type error, with a helpful message. In my check: `Cannot use 'bind:' with this property. It is declared as non-bindable inside the component. To mark a property as bindable: 'let { other = $bindable() } = $props()'`. Binding a `string` variable to a `number` prop is a regular assignability error on the same line.
- **Rest props.** `...rest` takes the type of the remaining properties of the annotated object. With an index signature (`[key: string]: unknown`) the rest collapses to `unknown` values; prefer extending a native attribute interface instead (see wrappers).
- **Callback props instead of events.** `eventHandler: (arg: string) => void` replaces `createEventDispatcher`. Name callbacks `onsomething` (lowercase, matching DOM conventions) and give them real signatures: `onselect?: (item: Item) => void`. For a type-safe emit pattern in a child call them optionally: `onselect?.(item)`.
- **Inline vs. named.** `let { a, b }: { a: number; b: string } = $props()` is fine for small components; use `interface Props` when the type is exported, extended or documented. Export it from a `<script module>` if other files need it: `<script lang="ts" module> export interface Props { ... } </script>`.
- **`children` is a prop.** It is a `Snippet`, and is optional unless you require content.
- **Do not annotate `$props.id()`:** `const uid = $props.id();` is inferred as `string`.

In JavaScript with JSDoc the same shape is written `/** @type {{ requiredProperty: number, optionalProperty?: boolean }} */ let { requiredProperty, optionalProperty } = $props();`.

## Generic components

A component can declare type parameters with the `generics` attribute on the instance script:

```html
<script lang="ts" generics="Item extends { id: string; text: string }">
    import type { Snippet } from 'svelte';

    interface Props {
        items: Item[];
        select?(item: Item): void;
        row: Snippet<[Item, number]>;
        empty?: Snippet;
        selected?: Item | undefined;
    }

    let { items, select, row, empty, selected = $bindable() }: Props = $props();
</script>

{#each items as item, i (item.id)}
    <button onclick={() => { selected = item; select?.(item); }}>
        {@render row(item, i)}
    </button>
{:else}
    {@render empty?.()}
{/each}
```

“The content of `generics` is what you would put between the `<...>` tags of a generic function. In other words, you can use multiple generics, `extends` and fallback types.” (`generics="T, K extends keyof T = keyof T"` works.) Svelte infers the type arguments from usage, and relationships are enforced across props and snippets. In my test the consumer below inferred `Item` as `{ id: string; text: string; n: number }`:

```html
<List {items} bind:selected={sel} select={(i) => i.n.toFixed()}>
    {#snippet row(item, idx)}{item.text}{idx}{/snippet}
</List>
```

- `select={(i) => i.n.toFixed()}`: `i` is inferred as the item type, so `.n` is known;
- the snippet parameters `item` and `idx` are inferred from `Snippet<[Item, number]>`;
- passing `row={(x: number) => x}` (a plain function with the wrong parameter) produced the error `Type '(x: number) => number' is not assignable to type 'Snippet<[{ id: string; ...}, number]>'`, which also shows that snippets are *not* ordinary functions in the type system.

Practical notes:

- **Constraints are your friend.** `generics="T"` accepts anything; `T extends { id: string }` lets the component read `item.id` for keys.
- **Binding and variance.** A `$bindable` generic prop is invariant: `bind:selected` requires the parent’s variable to have the same (or compatible) type as `Item | undefined`. If the parent’s variable is declared with a narrower type than the items, you get an assignability error on the `bind:`.
- **Instance type of a generic component** is awkward to name; `ReturnType<typeof List<{ id: string; text: string }>>` (an instantiation expression) works for `bind:this` variables.
- Snippets can themselves be generic since Svelte 5.30: `{#snippet row<T>(item: T)}...{/snippet}`.
- Module-level exports in `<script module>` cannot see instance generics.

## Typing snippets

`Snippet<Parameters>` takes a **tuple** of parameter types, because snippets can have several:

```ts
interface Props {
    data: any[];
    children: Snippet;           // no parameters
    row: Snippet<[any]>;         // one parameter
    cell: Snippet<[string, number]>;
}
```

`Snippet` is an interface with a call signature declared with `this: void`, and the type explicitly rejects arrays (`number extends Parameters['length'] ? never : Parameters`), meaning rest parameters are not supported. Remember also that you can only *invoke* a snippet through `{@render}`: calling `row(x)` in script is not valid, and rendering a `null`/`undefined` snippet throws `invalid_snippet` at runtime unless you use optional chaining (`{@render children?.()}`), which is why optional snippet props are typed with `?` and rendered with `?.`.

Typing patterns:

```html
<script lang="ts" generics="T">
    import type { Snippet } from 'svelte';

    let {
        data,
        children,
        row
    }: {
        data: T[];
        children: Snippet;
        row: Snippet<[T]>;
    } = $props();
</script>
```

- **Implicit snippet props.** A `{#snippet row(item)}` declared inside a component’s tag is passed as the `row` prop, and its parameter types are inferred from `Snippet<[T]>`; no annotations are needed at the call site.
- **Snippet that accepts a union of parameter lists** is a design smell; split into two snippet props.
- **Snippets as values.** You can store a snippet in a variable or pass it down: `<Inner {row} />`, with types preserved. `createRawSnippet` produces a `Snippet<Params>` from a function that returns HTML for a single element; its parameters arrive as getters (`Getters<Params>`).
- **Exported snippets** from `<script module>` have their parameter types inferred from the snippet declaration.

## `Component`, `ComponentProps` and friends

A Svelte 5 component is a function, typed as:

```ts
interface Component<
    Props extends Record<string, any> = {},
    Exports extends Record<string, any> = {},
    Bindings extends keyof Props | '' = string
> {
    (this: void, internals: ComponentInternals, props: Props): { /* exports */ } & ...;
    element?: typeof HTMLElement;   // present when compiled as a custom element
    z_$$bindings?: Bindings;
}
```

- `Props`: the props object.
- `Exports`: the shape of `export function`/`export const` members (what `bind:this` and `mount` return).
- `Bindings`: which props are `$bindable`.

Uses:

```html
<script lang="ts">
    import type { Component } from 'svelte';

    interface Props {
        // only components whose required props are a subset of { prop: string } fit
        DynamicComponent: Component<{ prop: string }>;
    }

    let { DynamicComponent }: Props = $props();
</script>

<DynamicComponent prop="foo" />
```

Because `<svelte:component>` is unnecessary in runes mode (a component-valued variable is dynamic by itself), the `Component` type is how you write a “slot for a component” prop. Assignability works like function parameters: a component that requires *more* props than `{ prop: string }` is rejected, because the caller would not supply them.

**`ComponentProps<typeof X>`** extracts the props type:

```ts
import type { Component, ComponentProps } from 'svelte';
import MyComponent from './MyComponent.svelte';

function withProps<TComponent extends Component<any>>(
    component: TComponent,
    props: ComponentProps<TComponent>
) {}

withProps(MyComponent, { foo: 'bar' });   // error if `foo` is not what MyComponent expects
```

In my check `type P = ComponentProps<typeof Btn>; const bad: P = { variant: 'nope' }` failed with `Type '"nope"' is not assignable to type '"primary" | "ghost" | undefined'`. That is the standard technique for building prop-forwarding helpers and for Storybook-style argument types.

**`bind:this` typing.** “To declare that a variable expects the constructor or instance type of a component”: `typeof MyComponent` is the component (constructor-like function) type; `MyComponent` itself, used as a type, is the instance type (the exports). So:

```html
<script lang="ts">
    import Ex from './Ex.svelte';       // exports focus() and version
    let r: Ex | undefined = $state();
    $effect(() => { r?.focus(); });
</script>

<Ex bind:this={r} />
```

and `r?.nope()` gives `Property 'nope' does not exist on type '... & { focus: () => void; version: 3; }'`. As the migration guide says, `bind:this` on a component “only returns the instance exports (`export function/const`)”, no `$set`/`$on`/`$destroy`.

**Declaring a component in a `.d.ts`** (for untyped assets or hand-written wrappers):

```ts
import type { Component } from 'svelte';
export declare const MyComponent: Component<{ foo: string }>;
```

**Deprecated types.** `SvelteComponent` (the class), `SvelteComponentTyped`, `ComponentType` and `ComponentEvents` are deprecated. `ComponentType<SvelteComponent<{ prop: string }>>` is equivalent to `Component<{ prop: string }>`; `ComponentEvents` is obsolete because events are callback props. The ambient `declare module '*.svelte'` that ships with Svelte still types default imports as `LegacyComponentType`, which is why editor/`svelte-check` support matters for exact types. The migration replacement is:

```ts
// before
let C: typeof SvelteComponent<{ foo: string }> = $state(Math.random() ? ComponentA : ComponentB);
// after
let C: Component<{ foo: string }> = $state(Math.random() ? ComponentA : ComponentB);
```

And, as always with `$state` holding functions: a component in `$state` is a function value, not proxied; assign a new component to re-render.

## Typing `$state`, `$derived` and friends

```ts
let count: number = $state(0);              // annotation on the variable
let maybe = $state<number>();               // number | undefined
let mustBeSetLater: number = $state();      // ERROR: 'number | undefined' is not assignable to 'number'
```

Without an initial value, `$state()` is typed `T | undefined`. The docs’ recommendation: pass the generic (`$state<number>()`) when it may remain `undefined`, or use an `as` cast “if you know that the variable *will* be defined before you first use it. This is especially useful in the context of classes”:

```ts
class Counter {
    count = $state() as number;
    constructor(initial: number) {
        this.count = initial;
    }
}
```

More points:

- **`$state.raw<T>(initial)`** has the same typing as `$state` but without the deep reactive proxy; use it for large immutable values (API responses). Its readonly-ish nature is a runtime/semantic one; the type is still `T`. If you want the compiler to prevent mutation, type it as `readonly string[]` (`$state.raw<readonly string[]>([])`), which then rejects `.push`.
- **Proxy types are the same as the source types.** `$state({ a: 1 })` has type `{ a: number }`. The reactivity is invisible to the type system, which is both convenient and a trap: nothing marks a value as a proxy, so `===` comparisons with the original can be surprising (`state_proxy_equality_mismatch` warns at runtime).
- **`$derived<T>`**: infers from the expression. `$derived.by(() => ...)` infers from the function’s return type. Writable deriveds have the same type as the expression.
- **`$state.snapshot(value)`** returns a `Snapshot<T>` that maps `SvelteDate`/`SvelteMap`/`SvelteSet` to their non-reactive `Date`/`Map`/`Set`, and removes methods from class instances etc. The alias `Snapshot` is declared inside the rune’s ambient namespace and is **not exported by name**: in my check both `import type { Snapshot } from 'svelte'` and `$state.Snapshot<T>` failed (`Module '"svelte"' has no exported member 'Snapshot'` and `'$state' has no exported member named 'Snapshot'`). Let inference carry it, or define your own plain DTO type and assign the snapshot to it.
- **`$bindable<T>(fallback?)`**, **`$props.id()`**, **`$host<El>()`**, **`$effect.root`** are all typed in the global ambient declarations that `svelte` ships; they are visible in any file the Svelte tooling treats as a runes context (`.svelte`, `.svelte.ts`, `.svelte.js`).
- **Class field inference.** In a class, `total = $derived(this.items.length + this.count)` is inferred as `number`; `new Counter(1).total` assigned to a `string` fails as expected.

## Wrapper components and DOM types

To expose the full attribute surface of a native element, extend the corresponding interface from `svelte/elements`:

```html
<script lang="ts">
    import type { HTMLButtonAttributes, ClassValue } from 'svelte/elements';

    interface Props extends HTMLButtonAttributes {
        variant?: 'primary' | 'ghost';
        class?: ClassValue;
    }

    let { variant = 'primary', class: klass, children, ...rest }: Props = $props();
</script>

<button class={['btn', variant, klass]} {...rest}>
    {@render children?.()}
</button>
```

What this buys you, confirmed with `svelte-check`:

- `<Btn type="submit" onclick={(e) => e.currentTarget.form}>`: `e` is a `MouseEvent & { currentTarget: EventTarget & HTMLButtonElement }`, so `currentTarget.form` is typed;
- unknown attributes are rejected: `<Btn nonexistent="1">` gives `Object literal may only specify known properties, and '"nonexistent"' does not exist in type 'Props'`;
- `children` is already in `HTMLAttributes` as a `Snippet | undefined`, so you do not declare it.

Details:

- **`ClassValue`** (exported from `svelte/elements` since 5.19) is `string | ClassArray | ClassDictionary` from `clsx`, `HTMLAttributes` declares `class?: ClassValue | undefined | null`, so a wrapper can accept arrays and objects and forward them straight to `class={...}`.
- **Elements without a dedicated interface** use `SvelteHTMLElements['div']`: `let { children, ...rest }: SvelteHTMLElements['div'] = $props();`. `SvelteHTMLElements` is the map from tag name to attribute type; it also contains the `svelte:*` special elements (`svelte:window`, `svelte:document`, `svelte:body`, `svelte:head`, `svelte:fragment`, `svelte:options`, `svelte:boundary` with `onerror`, `failed: Snippet<[error: unknown, reset: () => void]>`, `pending: Snippet`).
- **Event handler types** follow `EventHandler<E, T>` and named aliases such as `MouseEventHandler<T>`, `KeyboardEventHandler<T>`, `FormEventHandler<T>`. Use them for callback props that forward DOM events: `onclick?: MouseEventHandler<HTMLButtonElement>`. In markup, inline handlers get contextual types automatically (`oninput={(e) => e.currentTarget.value}`; `e.currentTarget.value.toFixed()` failed with `Property 'toFixed' does not exist on type 'string'`).
- **Rest ordering.** `{...rest}` after your own attributes lets callers override; before them lets your attributes win. For a handler you want to *combine* with the caller’s, do not rely on spreading: attributes and events from spreads are overwritten by later ones, so wrap explicitly (`onclick={(e) => { rest.onclick?.(e); track(); }}` and spread `rest` before).
- **Data attributes.** `HTMLAttributes` contains ``[key: `data-${string}`]: any``, so any `data-*` attribute type-checks.

### Augmenting the DOM types

Experimental attributes, custom events from actions and custom elements are not in the shipped typings. Augment the `svelte/elements` module in a `.d.ts` file (“make sure that the `d.ts` file is referenced in your `tsconfig.json`”):

```ts
// src/additional-svelte-typings.d.ts
import type { HTMLButtonAttributes } from 'svelte/elements';

declare module 'svelte/elements' {
    // a new element
    export interface SvelteHTMLElements {
        'custom-button': HTMLButtonAttributes & { size?: 'sm' | 'lg' };
    }

    // a new global attribute available on all HTML elements
    export interface HTMLAttributes<T> {
        'data-track'?: string;
    }

    // a new attribute for button elements
    export interface HTMLButtonAttributes {
        veryexperimentalattribute?: string;
    }
}

export {}; // ensure this is not an ambient module, else types will be overridden instead of augmented
```

The trailing `export {}` is essential, as the comment says: without it the file is an *ambient* module declaration, which replaces rather than merges. With the augmentation in place, my check reported `<custom-button size="xl">` as `Type '"xl"' is not assignable to type '"sm" | "lg" | undefined'` and `<custom-button bogus="x">` as an excess property, while `size="sm"` passed. Declaration merging works because these are `interface`s; type aliases cannot be augmented.

## Typing actions, attachments, transitions and stores

**Attachments** (`svelte/attachments`) are the simplest to type:

```ts
interface Attachment<T extends EventTarget = Element> {
    (element: T): void | (() => void);
}

const tooltip = (text: string): Attachment<HTMLElement> =>
    (el) => {
        el.title = text;
        return () => { el.title = ''; };
    };
```

Use it as `<div {@attach tooltip('hello')}>`. The element type parameter restricts where it may be attached (an `Attachment<HTMLInputElement>` on a `<div>` is an error). Create reusable attachment *factories* returning `Attachment<T>`; `fromAction` adapts an existing action (`fromAction<E, T>(action, fn: () => T): Attachment<E>`), and `createAttachmentKey()` yields a symbol for spreading attachments through props.

**Actions** (`svelte/action`) take three type arguments: the node type, the parameter type, and “any custom event handlers created by the action”:

```ts
import type { Action } from 'svelte/action';

export const longpress: Action<
    HTMLElement,
    number,                                          // the `ms` parameter
    { onlongpress: (e: CustomEvent) => void }        // typed custom event attribute
> = (node, ms) => {
    // ...
    return { update(v) { ms = v; }, destroy() {} };
};
```

and then `<div use:longpress={200} onlongpress={(e) => e.detail}>` type-checks the parameter and gives `onlongpress` a type on that element. `ActionReturn<Parameter, Attributes>` describes the returned `{ update?, destroy? }`; `$$_attributes` on it exists solely for the checker and must not be used. Remember the parameter is *not reactive* unless you implement `update`, which is a good reason to prefer attachments in new code.

**Transitions and animations.** The config types are `TransitionConfig` (`svelte/transition`) and `AnimationConfig` (`svelte/animate`), both `{ delay?, duration?, easing?, css?, tick? }`. A custom transition is a function `(node: Element, params: P, options: { direction: 'in' | 'out' | 'both' }) => TransitionConfig`; annotate the return type so that typos in `css`/`tick` are caught. Built-in parameter interfaces (`FadeParams`, `FlyParams`, `BlurParams`, `SlideParams`, `ScaleParams`, `DrawParams`, `CrossfadeParams`) are exported for wrappers (Chapter 11).

**Stores.** `Readable<T>`, `Writable<T>`, `StartStopNotifier<T>`, `Updater<T>`, `Subscriber<T>`, `Unsubscriber` are exported from `svelte/store`. `$store` auto-subscriptions infer `T` from the store’s type. `derived` has overloads whose `fn` receives `StoresValues<S>`, a tuple/array of the store values; for tuples use `as const` or declare an array literal of stores directly so that the tuple structure is preserved.

## `.svelte.ts` modules, `<script module>` and the language service

Runes are compiled in `.svelte`, `.svelte.js` and `.svelte.ts`. Plain `.ts` files that use `$state` fail at runtime (`rune_outside_svelte`) and are not understood by the Svelte-aware tooling. Keep logic in `.svelte.ts` when it needs reactivity and in `.ts` when it does not; type imports between them are ordinary.

**Importing `<script module>` exports from a `.ts` file** is the classic trap: a `.ts` file importing `{ type Row } from './List.svelte'` needs the language service plugin to know `List.svelte`’s module exports. VS Code’s Svelte extension includes `typescript-svelte-plugin` for exactly this, and `svelte-check` handles it; a bare `tsc` does not. For libraries, emit declarations with `svelte-package`. A practical rule: put shared types in a `.ts` file (`types.ts`) and have components `import type` from it, rather than exporting types from `<script module>` for others to consume.

Other strictness traps:

- **`strict` and generics inference.** With `strictNullChecks` off, many optional-prop errors disappear and the types lie. Keep `strict: true`.
- **`$props()` destructuring defaults and `exactOptionalPropertyTypes`.** With the option on, `optional?: string` does not accept an explicit `undefined`; a parent that passes `prop={undefined}` is flagged. Decide on one policy per project.
- **Event-handler `this`.** Callback props are called without a `this`; type them with arrow functions, and do not declare them as methods if you intend to pass unbound references.
- **Snippet parameter inference in `{#snippet}` outside component tags** (declared standalone) has no contextual type: annotate parameters yourself (`{#snippet row(item: Item)}`).
- **Class instances and `$state`.** A class instance with `$state` fields type-checks like any class; the transformed property getters/setters are invisible to types. Private `#fields` created by the compiler are not observable.

## JavaScript projects with JSDoc

TypeScript checking applies to plain JS too: in `.svelte` files without `lang="ts"` and in `.js`/`.svelte.js` files, use JSDoc and enable `"checkJs": true` (or `// @ts-check`). Props:

```html
<script>
    /** @type {{ requiredProperty: number, optionalProperty?: boolean, children?: import('svelte').Snippet }} */
    let { requiredProperty, optionalProperty = false, children } = $props();

    /** @type {number | undefined} */
    let count = $state();
</script>
```

Generics are declared with `@template`:

```html
<script>
    /**
     * @template T
     * @type {{ items: T[], select: (item: T) => void }}
     */
    let { items, select } = $props();
</script>
```

JSDoc types are *not* erased by a preprocessor, so there is nothing to configure; the checker reads the comments. The same `svelte-check` run covers them. JSDoc is also the format the Svelte docs use throughout, so the reference signatures translate directly.

## Putting it together: a typed design-system button

```html
<!-- Button.svelte -->
<script lang="ts" module>
    export type Variant = 'primary' | 'ghost' | 'danger';
</script>

<script lang="ts">
    import type { HTMLAnchorAttributes, HTMLButtonAttributes, ClassValue } from 'svelte/elements';
    import type { Snippet } from 'svelte';

    type Common = {
        variant?: Variant;
        class?: ClassValue;
        icon?: Snippet;
    };

    type Props =
        | (Common & HTMLButtonAttributes & { href?: undefined })
        | (Common & HTMLAnchorAttributes & { href: string });

    let { variant = 'primary', class: klass, icon, children, ...rest }: Props = $props();
</script>

{#if rest.href !== undefined}
    <a class={['btn', variant, klass]} {...rest as HTMLAnchorAttributes}>
        {@render icon?.()}{@render children?.()}
    </a>
{:else}
    <button class={['btn', variant, klass]} {...rest as HTMLButtonAttributes}>
        {@render icon?.()}{@render children?.()}
    </button>
{/if}
```

A discriminated union on `href` makes `<Button href="/x">` accept anchor attributes and `<Button type="submit">` accept button attributes, and rejects mixtures. The casts on `rest` are a known limitation: destructuring a union collapses the discrimination, so narrow with a cast (or split into two components and a thin dispatcher). It is also the kind of component where the checking costs are real: unions of large attribute interfaces make the language service slower, so profile before adopting this in every wrapper.

## Key takeaways

- The compiler erases type-only TypeScript; `enum` and constructor parameter properties raise `typescript_invalid_feature` unless you add `vitePreprocess({ script: true })` (or avoid them; `erasableSyntaxOnly` helps). Type annotations in the template require a `lang="ts"` script in the file.
- tsconfig essentials: `target >= ES2015`, `verbatimModuleSyntax: true`, `isolatedModules: true`. The build does not type-check; run `svelte-check` (`sv check`) in CI.
- Type props with an `interface Props` and `$props()`: callbacks replace events, `Snippet<[...]>` (a tuple) types snippets, `$bindable` makes `bind:` checkable, rest props type from the remainder.
- Generic components use `generics="Item extends { ... }"`; inference flows through props, callbacks and snippet parameters; snippets can be generic since 5.30.
- `Component<Props, Exports, Bindings>` is the component type; `ComponentProps<typeof X>` extracts props; `typeof X` is the constructor-like type and `X` the instance type for `bind:this`. `SvelteComponent`, `ComponentType`, `ComponentEvents` are deprecated.
- `$state<T>()` yields `T | undefined`; use `as T` in class fields; use `readonly` arrays with `$state.raw` to forbid mutation. `Snapshot<T>` is not importable by name.
- Wrapper components extend `HTMLButtonAttributes` and friends, or `SvelteHTMLElements['tag']`; `ClassValue` types `class`. Augment `svelte/elements` (with a trailing `export {}`) for custom attributes, events and elements.
- Attachments are typed `Attachment<T>`; actions use `Action<Node, Param, Attributes>`; transitions return `TransitionConfig`; stores have `Readable`/`Writable`.
- Keep reactive logic in `.svelte.ts`, share types from plain `.ts`, and rely on the language service (or `svelte-package`) for types of `<script module>` exports. JSDoc with `@type`/`@template` gives the same checking in JavaScript.

## Review Questions

1.  Which TypeScript features does Svelte support natively in `<script lang="ts">`, and which require a preprocessor? Give two examples of each and the compile error you get for the second group.

2.  You use `enum Level { Low, High }` in a component and the build fails. Give two fixes, one with configuration and one without.

3.  Why does `verbatimModuleSyntax` matter for Svelte components? What breaks if TypeScript is allowed to elide imports?

4.  (Multiple choice) Which of these is *not* one of the tsconfig settings recommended by the docs?

    a.  `target` of at least `ES2015`
    b.  `verbatimModuleSyntax: true`
    c.  `isolatedModules: true`
    d.  `experimentalDecorators: true`

5.  Your CI build passes but `svelte-check` reports errors. Explain why this can happen, and what you should add to CI.

6.  A template contains `onclick={(e: MouseEvent) => handle(e)}` and the build fails with `js_parse_error`. What is missing?

7.  Write the `$props()` declaration for a component with a required `label: string`, an optional `disabled`, a callback `onselect(id: number)`, an optional `children` snippet, and a bindable `value: string`.

8.  What error do you get in the parent when you write `bind:other={v}` for a prop that is not declared with `$bindable`? What about binding a `string` variable to a `number` bindable prop?

9.  Give the interface and component script for a generic `Select` component where `options: T[]`, `value: T | undefined` (bindable), `label: (o: T) => string` and `onchange?: (o: T) => void` all share a type parameter `T`.

10. In this usage, what type does `item` have, and why?

    ```html
    <List items={[{ id: 'a', text: 'A', n: 1 }]}>
      {#snippet row(item)}{item.n}{/snippet}
    </List>
    ```

11. What does `Snippet<[string, number]>` mean, and why is `Snippet<string[]>` rejected? Which runtime error occurs if a `Snippet` prop is `undefined` and rendered without optional chaining?

12. Explain the three type parameters of `Component<Props, Exports, Bindings>` and give a use case for a prop typed `Component<{ prop: string }>`.

13. What is the difference between `typeof MyComponent` and `MyComponent` as a type in a script? Which one do you use for the variable bound with `bind:this`?

14. Which of these types are deprecated in Svelte 5, and what replaces them: `SvelteComponent`, `ComponentType`, `ComponentEvents`, `Component`, `ComponentProps`?

15. Why does `let count: number = $state();` fail to compile under `strict`? Give two fixes, and say which is better inside a class.

16. You hold a large API response in `$state.raw<Item[]>(...)`. How do you make the type system prevent `.push`?

17. A colleague tries `import type { Snapshot } from 'svelte'` to type the result of `$state.snapshot(x)`. What happens and what do you do instead?

18. Write a `Card` wrapper component for `<div>` that forwards every native div attribute, accepts `class` as `ClassValue`, and renders `children`.

19. Where does the `children` prop’s type come from in a wrapper that extends `HTMLButtonAttributes`? Why do you not need to declare it?

20. What does `export {}` at the end of an augmentation `.d.ts` do, and what happens if you omit it?

21. Augment the DOM typings so that `<div data-track="x">` is accepted and `<fancy-input kind="text">` is a valid custom element whose `kind` attribute accepts `"text"` or `"number"`. Show the `.d.ts`.

22. How do you type an action that takes a `number` parameter and dispatches a custom `longpress` event handled with `onlongpress`? Why would you choose an attachment instead?

23. What is the type of an attachment factory returned by `tooltip(text: string)` for use on any HTML element? What happens when you attach an `Attachment<HTMLInputElement>` to a `<div>`?

24. A `.ts` file imports `{ type Row } from './List.svelte'` (declared in `<script module>`). It works in the editor and `svelte-check` but not under plain `tsc`. Why, and what would you restructure?

25. A module `cart.ts` uses `$state`. What goes wrong, and what is the fix?

26. How do you declare generics and type props in a JavaScript component using JSDoc? Write a typed version of the generic list in JSDoc.

27. Explain why destructuring a discriminated-union `Props` in a polymorphic Button collapses the discrimination, and give two approaches to handle it.

28. What is the relation between `Component` and the `*.svelte` ambient module declaration that Svelte ships? Why do editors still give you precise types?

29. With `exactOptionalPropertyTypes`, a parent passes `prop={undefined}` to an optional `prop?: string` and gets an error. What are the options?

30. For a stricter team policy: list three TypeScript compiler options you would enable beyond the three the docs recommend, and what each protects against in a Svelte codebase.
