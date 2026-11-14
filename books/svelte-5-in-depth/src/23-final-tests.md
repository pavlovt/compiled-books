# Final Tests

Six tests, each covering several chapters and growing harder: Test 1 checks the foundations, Test 6 goes into the reactivity internals, async Svelte and SSR/hydration. The answers are in the next chapter, “Final Tests: Answer Key”; try each test with the chapters closed before you look.

Conventions used in the code-reading questions:

- Unless a question says otherwise, snippets run in a `.svelte.js` module under Svelte 5.57.2 (runes mode, client build, no `experimental.async` flag, no `dev` flag).
- `flushSync` is imported from `'svelte'`. `$effect.root(...)` is used so that effects can exist outside a component. Effects run asynchronously in a microtask unless `flushSync()` runs them first.
- “Logs” means the exact lines printed to the console, in order.

## Test 1: Foundations of Svelte 5 and Core Reactivity

Covers Chapters 1 to 4: the mental model, the compiler, `$state`, `$derived` and `$effect`.

### Multiple choice

**1.** Which statement about a Svelte 5 component at runtime is accurate?

a.  The `<script>` block re-runs every time a piece of state it reads changes.
b.  The component is a function that runs once; fine-grained effects created during that run update the DOM later.
c.  Svelte keeps a virtual DOM and diffs it after every state change.
d.  The compiler generates a per-component bitmask and re-invokes a single `$$invalidate` function on every write.

**2.** In which files can runes such as `$state` be used?

a.  Any `.js` or `.ts` file that imports from `svelte`.
b.  `.svelte`, `.svelte.js` and `.svelte.ts` files.
c.  Only `.svelte` files.
d.  Any file, but only when bundled by Vite.

**3.** What does the compiler emit for a `$state` variable in a component that is never reassigned and never mutated?

a.  A `$.state(...)` signal, so that it is ready if it changes later.
b.  A deep proxy created with `$.proxy(...)`.
c.  A plain variable, because nothing can ever change it.
d.  A compile error telling you to use `const`.

**4.** Which of the following does *not* put a component into runes mode?

a.  Using `$state` anywhere in the instance script.
b.  Writing `<svelte:options runes />`.
c.  Using `await` at the top level of the instance script.
d.  Importing `onMount` from `'svelte'`.

**5.** You call `const app = mount(App, { target })` and App contains an `$effect` that writes to `document.title`. Immediately after the call returns, in the same synchronous run, what is true?

a.  The effect has already run.
b.  The effect has not run yet; `flushSync()` would run it.
c.  The effect will never run, because `mount` skips user effects.
d.  The effect runs, but its cleanup does not.

**6.** Which argument to `$state(...)` is *not* wrapped in a deep reactive proxy?

a.  `{ a: 1 }`
b.  `[1, 2, 3]`
c.  `new Map()`
d.  `{ nested: { list: [1] } }`

**7.** Which description of `$state.snapshot(x)` is correct?

a.  It returns the same proxy, frozen against further mutation.
b.  It returns a static deep copy using `structuredClone` semantics (honouring `toJSON`); parts that cannot be cloned are returned as-is with the warning `state_snapshot_uncloneable`.
c.  It returns a shallow copy; nested objects are still proxies.
d.  It throws if `x` contains a class instance.

**8.** A `$derived` expression assigns to a `$state` variable declared outside the expression. What happens?

a.  The assignment works; the derived re-runs when the state changes.
b.  The assignment is silently ignored.
c.  Svelte throws `state_unsafe_mutation`.
d.  Svelte compiles the derived as an `$effect` instead.

**9.** Given `let n = $state(1); let d = $derived(n * 2);` in Svelte 5.57, which statement about `d = 100` is true?

a.  It is a compile error, because deriveds are always read-only.
b.  It is allowed; `d` reads 100 until `n` changes, after which it is recomputed from `n`.
c.  It is allowed and permanently detaches `d` from `n`.
d.  It changes the value of `n` to 50.

**10.** Which statement about `$effect` is true?

a.  It runs during server-side rendering, before the HTML is produced.
b.  It runs in the browser after the DOM has been updated, batched in a microtask, and may return a teardown function.
c.  It runs synchronously at every state write.
d.  It is the recommended way to compute a value from other state.

**11.** `let a = $state(false); let b = $state(0); $effect(() => { if (a) console.log(b); });`. Which writes re-run this effect right after its first run?

a.  Writes to `a` only.
b.  Writes to `b` only.
c.  Writes to either `a` or `b`.
d.  Neither; effects only re-run when they return a teardown.

**12.** Which lifecycle function also runs on the server during `render`?

a.  `onMount`
b.  `onDestroy`
c.  `tick`
d.  `$effect.pre`

### Code reading: what does this log?

**13.**

```js
let count = $state(0);
let doubled = $derived(count * 2);

count = 5;
console.log(doubled);
count++;
console.log(doubled);
```

a.  `0` then `0`
b.  `10` then `12`
c.  `10` then `10`
d.  `0` then `12`

**14.**

```js
let user = $state({ name: 'Ada', age: 36 });
let { name } = user;
user.name = 'Grace';
console.log(name, user.name);
```

a.  `Grace Grace`
b.  `Ada Ada`
c.  `Ada Grace`
d.  `undefined Grace`

**15.**

```js
let a = $state(1);

console.log('start');
const stop = $effect.root(() => {
  $effect(() => console.log('effect', a));
});
console.log('after root');
a = 2;
a = 3;
flushSync();
console.log('end');
stop();
```

a.  `start`, `after root`, `effect 3`, `end`
b.  `start`, `effect 1`, `after root`, `effect 3`, `end`
c.  `start`, `after root`, `effect 2`, `effect 3`, `end`
d.  `start`, `effect 1`, `after root`, `effect 2`, `effect 3`, `end`

**16.**

```js
let items = $state.raw([1, 2]);
const stop = $effect.root(() => {
  $effect(() => console.log('len', items.length));
});
flushSync();
items.push(3);
flushSync();
console.log(items.length);
items = [...items, 4];
flushSync();
stop();
```

a.  `len 2`, `3`, `len 4`
b.  `len 2`, `len 3`, `3`, `len 4`
c.  `len 2`, `len 3`, `len 4`
d.  `len 2`, `2`, `len 4`

**17.**

```js
let n = $state(1);
let parity = $derived(n % 2);
const stop = $effect.root(() => {
  $effect(() => console.log('parity', parity));
});
flushSync();
n = 3;
flushSync();
n = 4;
flushSync();
stop();
```

a.  `parity 1`, `parity 1`, `parity 0`
b.  `parity 1`, `parity 0`
c.  `parity 1`, `parity 3`, `parity 0`
d.  `parity 1`, `parity 1`

**18.**

```js
let a = $state(1);
const stop = $effect.root(() => {
  $effect(() => {
    const v = a;
    console.log('run', a);
    return () => console.log('cleanup', a, v);
  });
});
flushSync();
a = 2;
flushSync();
stop();
flushSync();
```

a.  `run 1`, `cleanup 2 1`, `run 2`, `cleanup 2 2`
b.  `run 1`, `cleanup 1 1`, `run 2`, `cleanup 2 2`
c.  `run 1`, `run 2`, `cleanup 2 2`
d.  `run 1`, `cleanup 2 2`, `run 2`, `cleanup 2 2`

**19.**

```js
let list = $state([{ id: 1 }]);
const added = { id: 2 };
list.push(added);
console.log(list.includes(added), list[1] === added, list.indexOf(added));
```

a.  `true true 1`
b.  `false false -1`
c.  `true false 1`
d.  `false true -1`

**20.**

```js
class Todo {
  done = $state(false);
  text;
  constructor(text) { this.text = text; }
}
console.log(JSON.stringify(new Todo('milk')));
```

a.  `{"done":false,"text":"milk"}`
b.  `{"text":"milk"}`
c.  `{"done":false}`
d.  `{}`

### Find the bug

**21.** A child component computes a value from a prop. The label never changes when the parent passes a new `count`. Name the diagnostic the compiler shows and fix the code.

```html
<script>
  let { count } = $props();
  let label = `Items: ${count * 2}`;
</script>

<p>{label}</p>
```

**22.** This effect tries to log every value `count` has had. Running it throws a runtime error. Which error, why, and what is the minimal fix?

```js
let history = $state([]);
let count = $state(0);

$effect(() => {
  history.push(count);
});
```

**23.** A developer expects the interval below to stop when the component is destroyed, but it keeps ticking after the component is gone. Why, and what is the fix?

```html
<script>
  import { onMount } from 'svelte';
  let ticks = $state(0);

  onMount(async () => {
    await Promise.resolve();
    const id = setInterval(() => ticks++, 1000);
    return () => clearInterval(id);
  });
</script>
```

**24.** The author expects the message to be logged again whenever `count` changes. It is logged once with the first value only. Explain why.

```html
<script>
  let count = $state(0);
  $effect(() => {
    setTimeout(() => {
      console.log('count is', count);
    }, 100);
  });
</script>
```

### Short answer

**25.** Give two reasons why `$derived` is the right tool, and `$effect` the wrong one, for a `fullName` built from `first` and `last`.

**26.** When should you choose `$state.raw` over `$state`, and what do you give up?

**27.** Explain the equality cut-off of `$derived` in one paragraph, and say why a derived that returns a freshly built array does not benefit from it.

### Scenario / design

**28.** A search box filters a list of 5,000 products that are loaded once and replaced wholesale on refresh. The query is typed by the user, and results must be shown with a count. Say which rune you use for the product list, the query, the filtered list and the count, and say whether any `$effect` is needed.

**29.** Your team shares a shopping cart through a module `cart.svelte.ts`. A colleague wrote `export let cart = $state<Item[]>([]);` and a `clear()` function that does `cart = []`. The compiler rejects the file. Explain why, and show two ways to restructure it so that `clear()` and `add()` still work and importers stay reactive.

## Test 2: Templates, Components, Bindings and Browser Integration

Covers Chapters 6 to 9. Code-reading questions that show markup ask for the resulting DOM; whitespace between elements is not significant unless stated.

### Multiple choice

**1.** In a runes-mode component with `import Card from './Card.svelte'`, which markup renders the component?

a.  `<card />`
b.  `<Card />`
c.  `<svelte:card />`
d.  `<component this="Card" />`

**2.** `let View = $state(Home);` holds a component. What is the idiomatic way to render it in Svelte 5.57 runes mode?

a.  `<svelte:component this={View} />`, because plain `<View />` cannot be dynamic.
b.  `<View />`, because a capitalised variable holding a component is enough.
c.  `{@render View()}`
d.  `<svelte:element this={View} />`

**3.** How do you listen to the capture phase of a click on an element in Svelte 5?

a.  `onclick|capture={handler}`
b.  `onclickcapture={handler}`
c.  `capture:onclick={handler}`
d.  `onclick={{ capture: true, handler }}`

**4.** Which of these events is *not* delegated to the application root?

a.  `click`
b.  `keydown`
c.  `mouseenter`
d.  `pointerdown`

**5.** Which key gives the best behaviour for `{#each rows as row (...)}` when rows can be reordered, inserted and removed, and each row has its own input state?

a.  The loop index `i`.
b.  `row.id`, a stable unique primitive.
c.  `{ id: row.id }`, a fresh object per render.
d.  `Math.random()`

**6.** What does a component containing `{#await load()} ...pending... {:then v} ...{v}... {/await}` render on the server?

a.  The `:then` branch, after the server awaits the promise.
b.  Only the pending branch.
c.  Nothing, the block is skipped.
d.  The pending branch for 50 ms, then the `:then` branch.

**7.** Which snippet declaration does not compile?

a.  `{#snippet a(x, y = 1)}`
b.  `{#snippet a({ id, label })}`
c.  `{#snippet a(...args)}`
d.  `{#snippet a()}`

**8.** A component does `{@render footer()}` but the parent did not pass a `footer` snippet. What happens?

a.  Nothing is rendered.
b.  A runtime error `invalid_snippet` is thrown.
c.  An empty default snippet is rendered.
d.  A compile-time error is reported in the parent.

**9.** A child declares `let { value = $bindable('x') } = $props();`. The parent writes `<Child bind:value={name} />` where `let name = $state();` is `undefined`. What happens?

a.  The child shows `x` and writes the user’s edits back to `name`.
b.  A runtime error `props_invalid_value`: you cannot bind `undefined` to a prop that has a fallback.
c.  A compile error in the parent.
d.  A warning `ownership_invalid_binding` and the binding is skipped.

**10.** A set of checkboxes uses `bind:group={selected}`. What does `selected` hold?

a.  A boolean for each checkbox.
b.  An array of the `value`s of the checked inputs.
c.  A `Set` of the checked input elements.
d.  The `value` of the last checkbox clicked.

**11.** In Svelte 5.57.2, what value does `bind:value` give for an `<input type="number">` that the user has cleared?

a.  `0`
b.  `NaN`
c.  `null`
d.  `''`

**12.** Which `<svelte:window>` bindings are writable?

a.  All of them.
b.  `scrollX` and `scrollY` only.
c.  `innerWidth` and `innerHeight` only.
d.  None; window bindings are read-only.

### Code reading: what does this render, log or print?

**13.** What DOM does the `<input>` in this markup get?

```html
<input aria-hidden={false} hidden={false} disabled={0} data-x={null} data-y={undefined} data-z="">
```

a.  `<input aria-hidden="false" data-z="">`
b.  `<input data-z="">`
c.  `<input aria-hidden="false" hidden="false" disabled="0" data-z="">`
d.  `<input aria-hidden="false" data-x="null" data-y="undefined" data-z="">`

**14.** What is the text content of this paragraph?

```html
<p>{null}|{undefined}|{0}|{false}|{NaN}</p>
```

a.  `null|undefined|0|false|NaN`
b.  `||0|false|NaN`
c.  `||||`
d.  `|undefined|0||NaN`

**15.** What are the `class` and `style` attributes of the five divs?

```html
<script>
  let n = $state(1);
</script>

<div class={['a', false && 'b', n > 1 && 'c', null, 0]}></div>
<div class={{ a: true, b: false }} style:color="red" style="color: blue"></div>
<div class={false}></div>
<div class={undefined}></div>
<div class={[]}></div>
```

a.  `class="a"`; `class="a" style="color: red;"`; `class="false"`; no class; no class
b.  `class="a 0"`; `class="a" style="color: blue;"`; no class; no class; `class=""`
c.  `class="a"`; `class="a" style="color: blue;"`; `class="false"`; `class="undefined"`; no class
d.  `class="a c"`; `class="a b" style="color: red;"`; no class; no class; no class

**16.** What does the paragraph render?

```html
<!-- A3.svelte -->
<script>
  let { a = 1, b = 2, ...rest } = $props();
</script>
<p>{a}|{b}|{JSON.stringify(rest)}</p>

<!-- Parent.svelte -->
<A3 a={undefined} b={null} c="z" />
```

a.  `1|2|{"c":"z"}`
b.  `1||{"c":"z"}`
c.  `||{"c":"z"}`
d.  `1|null|{"c":"z"}`

**17.** A user clicks the button. In which order are the lines logged? (The manual listener is added from script after mount.)

```html
<div id="outer" onclick={() => console.log('outer')}>
  <button id="b" onclick={() => console.log('button')}>x</button>
</div>

<script>
  import { onMount } from 'svelte';
  onMount(() => {
    document.querySelector('#b').addEventListener('click', () => console.log('manual'));
  });
</script>
```

a.  `button`, `outer`, `manual`
b.  `manual`, `button`, `outer`
c.  `button`, `manual`, `outer`
d.  `manual`, `outer`, `button`

**18.** The user types `hi` into the input. What is logged, in order, once effects have flushed?

```html
<!-- Child.svelte -->
<script>
  let { v = $bindable('') } = $props();
</script>
<input bind:value={v} oninput={() => console.log('oninput', v)} />

<!-- Parent.svelte -->
<script>
  import Child from './Child.svelte';
  let text = $state('');
  $effect(() => console.log('effect', JSON.stringify(text)));
</script>
<Child bind:v={text} />
```

(The initial `effect ""` line is already logged.)

a.  `oninput ""`, `effect "hi"`
b.  `effect "hi"`, `oninput "hi"`
c.  `oninput "hi"`, `effect "hi"`
d.  `oninput "hi"` only; the effect does not re-run

**19.** What is logged, in order, when `setLabel('b')` is called and flushed, then `bump()` is called and flushed? (`log` is `console.log`; `other` is `$state(0)`.)

```html
<script>
  let { log } = $props();
  let label = $state('a');
  let other = $state(0);

  function att(l) {
    return (el) => {
      log('attach ' + l + ' other=' + other);
      return () => log('detach ' + l);
    };
  }
  export function setLabel(v) { label = v; }
  export function bump() { other++; }
</script>

<div {@attach att(label)}></div>
```

a.  After `setLabel`: `attach b other=0`. After `bump`: nothing.
b.  After `setLabel`: `detach a`, `attach b other=0`. After `bump`: `detach b`, `attach b other=1`.
c.  After `setLabel`: `detach a`, `attach b other=0`. After `bump`: nothing.
d.  After `setLabel`: nothing. After `bump`: `detach a`, `attach a other=1`.

**20.** What is the markup produced?

```html
{#snippet row(item, i = 0)}<li>{i}:{item}</li>{/snippet}
<ul>{@render row('a')}{@render row('b', 5)}</ul>
```

a.  `<ul><li>0:a</li><li>5:b</li></ul>`
b.  `<ul><li>:a</li><li>5:b</li></ul>`
c.  `<ul><li>a:0</li><li>b:5</li></ul>`
d.  A compile error: snippet parameters cannot have defaults.

### Find the bug

**21.** The following does not compile. Quote the error code and explain how to fix it.

```html
<script>
  let names = $state(['Ada', 'Grace']);
</script>

{#each names as name}
  <input bind:value={name} />
{/each}
```

**22.** A design-system `Button` accepts any button attribute. Users report that handlers passed as `onclick` by the parent never fire. Find the bug and fix it so both the internal and the external handler run.

```html
<script>
  let { children, ...rest } = $props();
  let clicks = $state(0);
</script>

<button {...rest} onclick={() => clicks++}>
  {@render children?.()} ({clicks})
</button>
```

**23.** The parent writes `<Tooltip use:tip={'Save'} />`. What is wrong, and what is the Svelte 5.57 way to attach DOM behaviour to a child component’s element? State the condition the child must meet.

**24.** The component compiles but throws as soon as it is mounted in the browser. Which error and why?

```html
<script>
  let agreed = $state(false);
</script>

<input type="checkbox" bind:value={agreed} />
```

### Short answer

**25.** A third-party library calls `event.stopPropagation()` in a manually added `click` listener on a wrapper inside your app. Some of your `onclick` handlers inside that wrapper stop working. Explain why, and give the Svelte-recommended alternative for adding listeners imperatively.

**26.** List three behavioural differences between an action (`use:`) and an attachment (`{@attach}`).

**27.** Give three advantages of snippets over the legacy slot system for passing markup into a component.

### Scenario / design

**28.** Design the public API of a reusable `Dialog` component for a design system: which props, which snippets, which callbacks, what is `$bindable`, how the parent can focus the close button, and how you make it accessible. Justify each decision briefly.

**29.** A form has a phone number input that must store digits only in state (for example `5551234567`) but display `555-123-4567`. It must also restore the original value when the form is reset. Which Svelte 5 features do you combine, and what would you avoid?

## Test 3: Styling, Motion and Shared State

Covers Chapters 10 to 12, with questions that reach back to Chapters 3, 4, 6 and 9.

### Multiple choice

**1.** Which statement about the specificity of scoped selectors is true?

a.  Scoping adds a `#id` selector, making every selector much more specific.
b.  Each scoped selector gains +0-1-0 from the hash class once; further occurrences within the same selector use `:where(.svelte-xyz)` and add nothing.
c.  Scoping never changes specificity because it uses attribute selectors with `:where`.
d.  Scoped selectors get an `!important` flag.

**2.** What is the preferred way for a parent to restyle internals of a child component that you own?

a.  A `:global` rule in the parent that reaches into the child’s markup.
b.  Passing CSS custom properties, such as `<Slider --track-color="black" />`, which the child reads with `var(--track-color)`.
c.  Using `{@html}` to inject a `<style>` element.
d.  Passing a `style` string through every layer of props.

**3.** What does `<Slider --track-color="black" />` cost at runtime?

a.  Nothing; it is a compile-time substitution.
b.  An extra wrapper element, `<svelte-css-wrapper style="display: contents; ...">`, whose style is reactive (a `<g>` in SVG).
c.  A global stylesheet rule.
d.  A `MutationObserver` on the child’s root.

**4.** How do you make an `@keyframes` rule available globally from a component’s `<style>`?

a.  Wrap it in `:global { }`.
b.  Prefix its name with `-global-`.
c.  Declare it in `<svelte:head>`.
d.  It is always global; keyframes are never scoped.

**5.** Which `css` compiler option value returns the CSS in `result.css` instead of injecting it with JavaScript, and is the default of the bundler plugins?

a.  `'injected'`
b.  `'external'`
c.  `'none'`
d.  `true`

**6.** An element with `transition:fade` sits inside an inner `{#if}` that itself sits inside an outer `{#if}`. Only the outer block toggles. By default, does the fade play?

a.  Yes, transitions always play when any ancestor block changes.
b.  No, transitions are local by default; add `|global` to make it play on ancestor changes.
c.  Only on the first toggle.
d.  Only if the element has a `key`.

**7.** Which combination is rejected by the compiler?

a.  `in:fly` together with `out:fade` on one element.
b.  `transition:fade` together with `in:fly` on one element.
c.  `transition:fade` together with `animate:flip` on one element.
d.  `in:fly|global` together with `out:fade|global`.

**8.** Why should a custom transition return `css` rather than `tick` when possible?

a.  `tick` is deprecated and ignored.
b.  The runtime samples `css(t, u)` up front and hands pre-eased keyframes to the Web Animations API, so the animation does not depend on main-thread work; `tick` runs on the main thread each frame.
c.  `css` allows the transition to run on the server.
d.  `css` lets the transition coexist with `in:` and `out:`.

**9.** Which statement about `animate:flip` is correct?

a.  It animates elements as they are added to and removed from a list.
b.  It must be on the sole immediate child of a keyed `{#each}` block and runs when items are reordered.
c.  It works on any element that is a child of an `{#if}`.
d.  It requires the `|global` modifier.

**10.** A global CSS rule `@media (prefers-reduced-motion: reduce) { * { transition-duration: 0s !important; animation-duration: 0s !important; } }` is in place. What is its effect on Svelte’s built-in `fade` and `fly` transitions?

a.  They are disabled.
b.  None; Svelte transitions are driven by the Web Animations API, so you must branch on `prefersReducedMotion.current` from `svelte/motion`.
c.  They are shortened to one frame.
d.  They throw `reduced_motion_violation`.

**11.** What are the defaults of the `Tween` and `Spring` classes?

a.  `Tween`: 400 ms duration, linear easing. `Spring`: stiffness 0.15, damping 0.8, precision 0.01.
b.  `Tween`: 1000 ms, `cubicOut`. `Spring`: stiffness 1, damping 1.
c.  `Tween`: 400 ms, `cubicOut`. `Spring`: stiffness 0.5, damping 0.5.
d.  Both default to a duration of 400 ms.

**12.** A child calls `const [getTheme] = createContext<Theme>(); getTheme()` (using its own, unrelated key) when no ancestor ever called the matching setter. What happens?

a.  It returns `undefined`.
b.  It throws `missing_context`.
c.  It returns an empty object.
d.  It logs a warning and returns the nearest context of the same type.

**13.** Where may `$store` auto-subscription syntax be used?

a.  Anywhere, including `.svelte.ts` modules.
b.  At the top level of `.svelte` files for stores declared at the top level of the component script (or imported).
c.  Only inside `$effect`.
d.  Only in the template, never in the script.

### Code reading: what does this log or render?

**14.** A parent provides context and a child displays it. What is the child’s paragraph initially, and after `inc()` has been called and flushed?

```html
<!-- Parent.svelte -->
<script module>
  import { createContext } from 'svelte';
  export const [getCtx, setCtx] = createContext();
</script>
<script>
  import Kid from './Kid.svelte';
  let count = $state(0);
  let state = $state({ n: 0 });
  setCtx({ count, state, get live() { return count; } });
  export function inc() { count++; state.n++; }
</script>
<Kid />

<!-- Kid.svelte -->
<script>
  import { getCtx } from './Parent.svelte';
  const ctx = getCtx();
</script>
<p>{ctx.count} {ctx.state.n} {ctx.live}</p>
```

a.  `0 0 0`, then `1 1 1`
b.  `0 0 0`, then `0 1 1`
c.  `0 0 0`, then `0 0 0`
d.  `0 0 0`, then `1 1 0`

**15.** What is logged?

```js
import { writable } from 'svelte/store';

const w = writable(0, () => {
  console.log('start');
  return () => console.log('stop');
});
const u1 = w.subscribe((v) => console.log('s1', v));
const u2 = w.subscribe((v) => console.log('s2', v));
w.set(1);
u1();
console.log('u1 off');
u2();
console.log('u2 off');
```

a.  `start`, `s1 0`, `s2 0`, `s1 1`, `s2 1`, `u1 off`, `stop`, `u2 off`
b.  `start`, `s1 0`, `start`, `s2 0`, `s1 1`, `s2 1`, `u1 off`, `stop`, `u2 off`, `stop`
c.  `s1 0`, `s2 0`, `s1 1`, `s2 1`, `u1 off`, `u2 off`
d.  `start`, `s1 0`, `s2 0`, `s1 1`, `s2 1`, `stop`, `u1 off`, `stop`, `u2 off`

**16.** Two stores are subscribed and `set` is called with the same value twice. How many times does each subscriber callback run in total, including the initial call?

```js
const o = { a: 1 };
const objStore = writable(o);
let objCalls = 0;
objStore.subscribe(() => objCalls++);
objStore.set(o);
objStore.set(o);

const numStore = writable(1);
let numCalls = 0;
numStore.subscribe(() => numCalls++);
numStore.set(1);
numStore.set(1);

console.log(objCalls, numCalls);
```

a.  `1 1`
b.  `3 3`
c.  `3 1`
d.  `1 3`

**17.** What does `logs.join(' | ')` print?

```js
import { SvelteMap } from 'svelte/reactivity';

const m = new SvelteMap([['a', 1]]);
const logs = [];
const stop = $effect.root(() => {
  $effect(() => { logs.push('a=' + m.get('a')); });
  $effect(() => { logs.push('size=' + m.size); });
});
flushSync();
m.set('b', 2);
flushSync();
m.set('a', 5);
flushSync();
m.set('a', 5);
flushSync();
console.log(logs.join(' | '));
```

a.  `a=1 | size=1 | a=1 | size=2 | a=5 | size=2 | a=5 | size=2`
b.  `a=1 | size=1 | size=2 | a=5`
c.  `a=1 | size=1 | size=2 | a=5 | a=5`
d.  `a=1 | size=1 | size=2 | a=1 | a=5`

**18.** How many times does the effect run?

```js
import { SvelteSet } from 'svelte/reactivity';

const s = new SvelteSet();
const o = { n: 1 };
s.add(o);
let runs = 0;
const stop = $effect.root(() => {
  $effect(() => {
    runs++;
    for (const x of s) x.n;
  });
});
flushSync();
o.n = 2;
flushSync();
console.log('runs', runs);
```

a.  `runs 1`
b.  `runs 2`
c.  `runs 3`
d.  The code throws, because `o` is not reactive.

**19.** What are the values printed?

```js
import { createSubscriber } from 'svelte/reactivity';

let started = 0, stopped = 0, update;
const subscribe = createSubscriber((u) => {
  started++;
  update = u;
  return () => stopped++;
});
let ext = 0;
const read = () => { subscribe(); return ext; };

const stopA = $effect.root(() => { $effect(() => { read(); }); });
const stopB = $effect.root(() => { $effect(() => { read(); }); });
flushSync();
console.log(started, stopped);
stopA();
flushSync();
console.log(started, stopped);
stopB();
flushSync();
console.log(started, stopped);
```

a.  `2 0`, then `2 1`, then `2 2`
b.  `1 0`, then `1 0`, then `1 1`
c.  `1 0`, then `1 1`, then `1 1`
d.  `1 1`, then `1 1`, then `1 1`

### Find the bug

**20.** The app is server-rendered. QA reports that a user briefly saw another user’s name in the header. Identify the bug and the Svelte-level fix.

```ts
// session.svelte.ts
export const session = $state({ user: null as User | null });
```

```html
<!-- +layout.svelte (rendered per request on the server) -->
<script>
  import { session } from './session.svelte.ts';
  let { data } = $props();
  session.user = data.user;
</script>
<Header />
```

**21.** A dark/light toggle is implemented with context. The header toggles `theme`, but children never update. Explain why and fix it.

```html
<!-- Layout.svelte -->
<script>
  import { setContext } from 'svelte';
  let theme = $state('dark');
  setContext('theme', theme);
</script>

<button onclick={() => (theme = theme === 'dark' ? 'light' : 'dark')}>toggle</button>
<Page />
```

**22.** This component renders markdown returned by a server. The paragraph colour never changes and the build prints a warning. Name it, explain it and give two fixes.

```html
<script>
  let { html } = $props();
</script>

<div class="md">{@html html}</div>

<style>
  .md p { color: rebeccapurple; }
</style>
```

**23.** The compiler rejects this list. Quote the error code and fix it.

```html
<script>
  import { flip } from 'svelte/animate';
  let todos = $state([{ id: 1, text: 'a' }, { id: 2, text: 'b' }]);
</script>

{#each todos as todo}
  <li animate:flip>{todo.text}</li>
{/each}
```

### Short answer

**24.** Explain why a transition like `fade` on an element is not silenced by a CSS reduced-motion media query, and show how you would honour the user’s preference in a custom setup.

**25.** When would you still choose a store (or a store-compatible object) over a class with `$state` fields for shared state in Svelte 5.57?

**26.** Outline how you would persist a preference to `localStorage` and keep several tabs in sync using `createSubscriber`, and name the SSR consequence for the initial render.

### Scenario / design

**27.** You maintain a themable component library. Consumers need light/dark, a brand palette, and per-instance overrides (for example a wider track on one slider). Describe your styling architecture: what lives in global custom properties, what in component styles, how consumers override, how dark mode is chosen without a flash on SSR pages, and how you keep CSS specificity predictable when users also use Tailwind.

**28.** A SvelteKit-style app renders a multi-tenant dashboard on the server and hydrates on the client. You are adding a shared `FiltersState` used by 15 components. Compare three designs (module singleton, context-provided class instance, store in context), pick one, and say how services are injected so that unit tests can replace them.

## Test 4: Types, Testing, Accessibility and Performance

Covers Chapters 15 to 18, with reach-backs to Chapters 2, 3, 4, 6, 9 and 12. Where a question mentions warnings, it means compiler warnings from Svelte 5.57.2.

### Multiple choice

**1.** Which TypeScript feature in a `<script lang="ts">` block makes the compiler fail with `typescript_invalid_feature` unless you configure `vitePreprocess({ script: true })`?

a.  `interface Props { ... }`
b.  `enum Mode { Light, Dark }`
c.  `const x = value as Item`
d.  `satisfies`

**2.** Which `tsconfig` options does the Svelte documentation require for a Svelte project?

a.  `target` of ES2015 or later, `verbatimModuleSyntax: true` and `isolatedModules: true`.
b.  `experimentalDecorators: true` and `target: ES5`.
c.  `module: commonjs` and `esModuleInterop: false`.
d.  `strict: false` and `skipLibCheck: false`.

**3.** Which type correctly describes a snippet prop that is rendered with `{@render row(item, index)}`, where `item` is an `Item` and `index` a `number`?

a.  `Snippet<Item | number>`
b.  `Snippet<[Item, number]>`
c.  `Snippet<(Item | number)[]>`
d.  `Snippet<{ item: Item; index: number }>`

**4.** In `let r: Dialog | undefined; ... <Dialog bind:this={r} />`, what does the type `Dialog` denote?

a.  The constructor-like type of the component.
b.  The instance type: the component’s exports, which is what `bind:this` provides.
c.  The type of its props.
d.  The type of the rendered root element.

**5.** `let count = $state<number>();` has which type?

a.  `number`
b.  `number | undefined`
c.  `number | null`
d.  `unknown`

**6.** Which Vitest setup lets `mount` from `svelte` work in tests without changing how the app resolves modules for `vite build`?

a.  `resolve: { conditions: ['browser'] }` unconditionally.
b.  `resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined`, plus `test.environment: 'jsdom'`.
c.  `resolve: { alias: { svelte: 'svelte/server' } }`
d.  `test.environment: 'node'` only.

**7.** Why does a test file containing `let n = $state(0)` fail with `rune_outside_svelte` when named `counter.test.ts`?

a.  Vitest forbids runes.
b.  Runes are only compiled in files whose names include `.svelte` (`.svelte.js`, `.svelte.ts`, `counter.svelte.test.ts`); a plain `.test.ts` is not compiled by the Svelte plugin.
c.  `$state` is only valid inside `describe` blocks.
d.  Runes require `// @vitest-environment jsdom`.

**8.** You test server rendering with `render(Component)` in a test file that has `environment: 'jsdom'` and the `browser` condition. It fails with `effect_orphan`. What is the cause?

a.  The component uses an effect outside `$effect.root`, which is never allowed.
b.  The component was compiled for the client, so `render` executes client code (including `$effect`) in the server renderer; SSR tests need a node environment and no `browser` condition.
c.  jsdom does not implement `$effect`.
d.  `render` must be called after `mount`.

**9.** Which compiler warnings does `<div onclick={f}>text</div>` produce?

a.  None; `div` with a click handler is allowed.
b.  `a11y_click_events_have_key_events` and `a11y_no_static_element_interactions`.
c.  `a11y_img_redundant_alt`
d.  `a11y_interactive_supports_focus` only.

**10.** Which is a valid use of `$props.id()`?

a.  `function make() { return $props.id(); }`
b.  `const id = $props.id();` at the top level of the instance script.
c.  Inside `$derived.by(() => $props.id())`.
d.  Inside `onMount`.

**11.** A form shows “Saved” after submit. Which markup lets a screen reader announce it reliably, politely, without interrupting?

a.  `{#if saved}<div role="status">Saved</div>{/if}`
b.  `<div role="status">{saved ? 'Saved' : ''}</div>`, rendered all the time
c.  `{#if saved}<div role="alert">Saved</div>{/if}`
d.  `<div aria-hidden="true">{saved ? 'Saved' : ''}</div>`

**12.** `items` is a `$state` array of 5,000 products and `evens` is derived. Which derived value lets a downstream effect skip re-running when an unrelated item is pushed?

a.  `let evens = $derived(items.filter(isEven));` read by the effect.
b.  `let evenCount = $derived(items.filter(isEven).length);` read by the effect.
c.  Neither; effects always re-run when the array changes.
d.  Both; deriveds are always compared deeply.

**13.** Your site enforces CSP with `require-trusted-types-for 'script'`. Which compile option avoids the `innerHTML`-based template cloning that violates it?

a.  `fragments: 'tree'`
b.  `css: 'external'`
c.  `preserveWhitespace: true`
d.  `generate: 'server'`

### Code reading: what does this log or print?

**14.** Logs, in order, when `App` is mounted, flushed, and then unmounted with `unmount(app)`:

```html
<!-- Parent.svelte -->
<script>
  import { onMount, onDestroy } from 'svelte';
  import Kid from './Kid.svelte';
  $effect(() => { console.log('parent effect'); return () => console.log('parent cleanup'); });
  onMount(() => { console.log('parent mount'); });
  onDestroy(() => console.log('parent destroy'));
</script>
<Kid />

<!-- Kid.svelte -->
<script>
  import { onMount, onDestroy } from 'svelte';
  $effect(() => { console.log('child effect'); return () => console.log('child cleanup'); });
  onMount(() => { console.log('child mount'); return () => console.log('child unmount'); });
  onDestroy(() => console.log('child destroy'));
</script>
```

a.  Mount: `parent effect`, `parent mount`, `child effect`, `child mount`. Unmount: `parent cleanup`, `parent destroy`, `child cleanup`, `child unmount`, `child destroy`.
b.  Mount: `child effect`, `child mount`, `parent effect`, `parent mount`. Unmount: `child cleanup`, `child unmount`, `child destroy`, `parent cleanup`, `parent destroy`.
c.  Mount: `child effect`, `child mount`, `parent effect`, `parent mount`. Unmount: `parent cleanup`, `parent destroy`, `child cleanup`, `child unmount`, `child destroy`.
d.  Mount: `parent effect`, `child effect`, `parent mount`, `child mount`. Unmount: no output.

**15.** In a jsdom test, `C` is `<script>let { onchange } = $props(); $effect(() => onchange(3));</script>`. What is printed?

```js
const seen = [];
const app = mount(C, { target: document.body, props: { onchange: (v) => seen.push(v) } });
console.log(seen.length);
flushSync();
console.log(seen.length);
```

a.  `1`, then `1`
b.  `0`, then `1`
c.  `0`, then `0`
d.  `1`, then `2`

**16.** `Counter.svelte` is `<script>let n = $state(0);</script><button onclick={() => n++}>{n}</button>`, mounted and flushed. What is printed?

```js
const b = document.querySelector('button');
b.click();
console.log(b.textContent);
await tick();
console.log(b.textContent);
```

a.  `1`, then `1`
b.  `0`, then `1`
c.  `0`, then `0`
d.  `1`, then `2`

**17.** After the two `push` calls and flushes, how many times has each effect run in total?

```js
let items = $state([1, 2, 3]);
let evens = $derived(items.filter((x) => x % 2 === 0));
let evenCount = $derived(items.filter((x) => x % 2 === 0).length);

const stop = $effect.root(() => {
  $effect(() => { evens; });       // effect A
  $effect(() => { evenCount; });   // effect B
});
flushSync();
items.push(5);
flushSync();
items.push(6);
flushSync();
```

a.  A: 3, B: 2
b.  A: 3, B: 3
c.  A: 2, B: 2
d.  A: 2, B: 3

**18.** What does this print?

```js
class Point { x = $state(1); toJSON() { return { px: this.x }; } }

const s = $state({ p: new Point(), d: new Date(0), arr: [1, { a: 2 }] });
const snap = $state.snapshot(s);

console.log(JSON.stringify(snap), snap.d instanceof Date, snap.arr !== s.arr);
```

a.  `{"p":{"px":1},"d":"1970-01-01T00:00:00.000Z","arr":[1,{"a":2}]} true true`
b.  `{"p":{"x":1},"d":"1970-01-01T00:00:00.000Z","arr":[1,{"a":2}]} true true`
c.  `{"p":{"px":1},"d":"1970-01-01T00:00:00.000Z","arr":[1,{"a":2}]} false false`
d.  The call throws because `Point` cannot be cloned.

**19.** Which warnings does the compiler report for the following element?

```html
<img src="/cat.png" alt="Photo of my cat" />
<button role="button">Save</button>
<div tabindex="3">hello</div>
```

a.  None.
b.  `a11y_img_redundant_alt`, `a11y_no_redundant_roles`, `a11y_positive_tabindex` (and `a11y_no_noninteractive_tabindex`).
c.  Only `a11y_missing_attribute`.
d.  `a11y_media_has_caption` and `a11y_distracting_elements`.

### Find the bug

**20.** This component works in the browser, but a type-check by the CI job (`svelte-check`) is the only thing that reports a problem, and the build itself passes. Explain why the build did not fail, and what the problem is.

```html
<script lang="ts">
  interface Props { size: number; onselect?: (id: number) => void }
  let { size, onselect }: Props = $props();
</script>

<Child size="large" {onselect} />
```

**21.** The compiler warns about this modal’s backdrop. List the warnings, explain why they matter, and give a better structure.

```html
<div class="backdrop" onclick={close}>
  <div class="panel">{@render children?.()}</div>
</div>
```

**22.** This code makes the page slower every time the user navigates to a page that uses the component. Find the leak and fix it twice (two idiomatic ways).

```html
<script>
  let width = $state(window.innerWidth);
  window.addEventListener('resize', () => (width = window.innerWidth));
</script>

<p>{width}</p>
```

**23.** A unit test of a `.svelte.ts` store passes locally but occasionally fails in CI after other tests in the same file ran. The helper below is used in every test. Find the flaw.

```ts
function track<T>(fn: () => T) {
  const values: T[] = [];
  $effect.root(() => {
    $effect(() => { values.push(fn()); });
  });
  flushSync();
  return values;
}
```

### Short answer

**24.** The build passes with a type error in a component. Explain the division of labour between the compiler/bundler and `svelte-check`, and what you put in CI.

**25.** Explain why a live region that is added to the DOM at the same moment as its message is unreliable, and what to do instead.

**26.** Why is a derived that returns `items.filter(...)` a weaker optimisation boundary than one that returns a count, and how would you decide which to use for a table with sortable columns?

### Scenario / design

**27.** You must define the testing strategy for a design system of 40 Svelte 5 components plus a `.svelte.ts` state layer. Describe what you test at which level (unit, component in jsdom, browser mode, Playwright), how you test snippets and context, which assertions use role-based queries, where axe runs, and what you explicitly do not test in jsdom.

**28.** A 5,000-row editable table lags when a single cell is edited. Give a step-by-step diagnosis plan and the fixes you would try in order, naming the Svelte features involved.

## Test 5: Interop, Migration and System Design

Covers Chapters 19 and 20 together with architecture questions that draw on Chapters 9, 12, 14 and 18. Several questions describe a team situation; answer them as a senior engineer would, with trade-offs.

### Multiple choice

**1.** A component has `<svelte:options customElement="x-rating" />` but the project compiles with the default `customElement` option (`false`). What does the compiler report?

a.  A compile error, `custom_element_invalid_tag`.
b.  The warning `options_missing_custom_element`.
c.  Nothing; the options tag alone is enough.
d.  A runtime error when the element is defined.

**2.** The element should expose a numeric `value` that is read from the attribute `value="3"` and written back to the attribute when the component changes it. Which `props` entry does that?

a.  `value: { type: 'Number', reflect: true }`
b.  `value: { attribute: false }`
c.  `value: { type: 'String' }`
d.  `value: 'Number'`

**3.** When is the inner Svelte component of a custom element created?

a.  In the constructor.
b.  In the next tick after `connectedCallback`.
c.  In `attributeChangedCallback`, before `connectedCallback`.
d.  Synchronously during `customElements.define`.

**4.** From inside a custom element’s shadow root you want a `change` event that a listener on `document` can receive. Which is correct?

a.  `$host().dispatchEvent(new CustomEvent('change', { detail }))`
b.  `$host().dispatchEvent(new CustomEvent('change', { detail, bubbles: true, composed: true }))`
c.  `dispatch('change', detail)` from `createEventDispatcher`
d.  `$host().onchange(detail)`

**5.** What are the consequences of `shadow: 'none'` in the custom element options?

a.  Styles remain encapsulated, slots still work.
b.  No shadow root: no style encapsulation and no slots.
c.  The element can no longer have props.
d.  The element is rendered on the server.

**6.** Two custom elements on a page were built from Svelte components. The outer one calls `setContext('theme', ...)`; the inner one calls `getContext('theme')`. What does the inner one get?

a.  The outer element’s value, because the DOM tree is the context tree.
b.  Nothing: each custom element is its own Svelte root, so context is not shared across element boundaries.
c.  A copy made through `window.__svelte`.
d.  The value, but only when `shadow: 'none'`.

**7.** Which tool or step does *not* come out of `npx sv migrate svelte-5` automatically?

a.  `let` to `$state` conversion and `on:click` to `onclick`.
b.  `<slot>` to `{@render children()}`.
c.  Converting `createEventDispatcher` to callback props and rewriting `beforeUpdate` / `afterUpdate`.
d.  `new App({ target })` to `mount(App, { target })`.

**8.** A runes-mode parent passes a snippet to a legacy child that declares `<slot />`, and in another place a legacy parent passes slot content to a runes child that does `{@render children?.()}`. Which statement is true?

a.  Both work: snippets and slots are fully interchangeable.
b.  Snippets can be passed to a component that uses slots, but slotted content cannot be passed to a component that renders snippets with `{@render}`.
c.  Neither works; the mix is a compile error.
d.  Only the second works.

**9.** Why is `compilerOptions: { runes: true }` in `svelte.config.js` risky for a Svelte 4 to 5 migration?

a.  It disables `$state`.
b.  It forces runes mode for every compiled component, including those in `node_modules`, which breaks legacy dependencies; use the function form or `dynamicCompileOptions` instead.
c.  It makes the build slower.
d.  It turns off the `a11y_*` warnings.

**10.** After migrating a component to runes, existing code does `const app = new App({ target: document.body, props })`. What is the result?

a.  It works exactly as in Svelte 4.
b.  A compile warning only.
c.  The compiler flags `legacy_component_creation`, and at runtime `component_api_invalid_new` is thrown unless `compatibility.componentApi: 4` is set; use `mount` instead.
d.  The component is mounted but loses reactivity.

**11.** What is true of intro transitions for the two entry points in Svelte 5.57?

a.  `mount` plays intros by default (`intro: true`); `hydrate` does not play them by default.
b.  Neither plays intros by default.
c.  Both play them by default.
d.  `mount` never plays intros.

**12.** A Svelte 4 component uses `<div on:touchstart={handler}>` and calls `event.preventDefault()` inside to stop scrolling. After migration to `ontouchstart`, scrolling is no longer prevented. Why, and what is the fix?

a.  Delegation breaks `preventDefault`; use `stopPropagation`.
b.  `ontouchstart` and `ontouchmove` attributes are registered as passive, so `preventDefault` is ignored; add the listener with `on(node, 'touchstart', handler, { passive: false })` from `svelte/events` (in an attachment).
c.  `touchstart` is no longer supported.
d.  Use `onTouchStart` with a capital T.

**13.** Which of the following changes prepares an app for Svelte 6 and can be done today?

a.  Removing all uses of `$derived`.
b.  Fixing `attribute_quoted` warnings by unquoting single expressions on component props, and replacing falsy `class` values so that attributes are omitted deliberately.
c.  Enabling `compatibility.componentApi: 4`.
d.  Pinning `svelte` to `^4`.

### Code reading: what does this log, print or render?

**14.** In a jsdom test, the element below is compiled with `customElement: true`. What is printed?

```html
<!-- x-counter.svelte -->
<svelte:options customElement={{ tag: 'x-counter', props: { count: { reflect: true, type: 'Number' } } }} />
<script>
  let { count = 0 } = $props();
  const host = $host();
</script>
<button onclick={() => { count++; host.dispatchEvent(new CustomEvent('bump', { detail: count })); }}>{count}</button>
```

```js
const el = document.createElement('x-counter');
el.setAttribute('count', '3');
document.body.appendChild(el);
console.log(el.shadowRoot.children.length);
await tick();
console.log(el.shadowRoot.querySelector('button').textContent, el.count, typeof el.count);
let detail;
el.addEventListener('bump', (e) => (detail = e.detail));
el.shadowRoot.querySelector('button').click();
await tick(); await tick();
console.log(el.shadowRoot.querySelector('button').textContent, el.getAttribute('count'), detail);
```

a.  `1`; `3 3 number`; `4 4 4`
b.  `0`; `3 3 number`; `4 4 4`
c.  `0`; `3 3 string`; `4 3 4`
d.  `0`; `3 undefined undefined`; `3 3 undefined`

**15.** Which of these sources compile in runes mode (`metadata.runes === true`) with default options?

```text
A: <script>let x = 0</script>{x}
B: <script>let x = $state(0)</script>{x}
C: <svelte:options runes /><script>let x = 0</script>{x}
D: <script module>export const x = 1</script><p>hi</p>
```

a.  A and D
b.  B and C
c.  B only
d.  A, B, C and D

**16.** What is logged during `render(S1)` on the server, and what is `body`?

```html
<!-- S1.svelte -->
<script>
  import { onMount, onDestroy } from 'svelte';
  let n = $state(1);
  let d = $derived(n * 2);
  console.log('script runs');
  $effect(() => { console.log('effect'); });
  $effect.pre(() => { console.log('pre'); });
  onMount(() => console.log('mount'));
  onDestroy(() => console.log('destroy'));
</script>
<button onclick={() => n++}>{n} {d}</button>
```

```js
const { body } = render(S1);
```

a.  Logs `script runs`, `pre`, `effect`, `mount`; body contains `<button>1 2</button>`.
b.  Logs `script runs`, `destroy`; body contains `<button>1 2</button>` without any event code.
c.  Logs `script runs`, `effect`, `destroy`; body is empty until hydration.
d.  Logs nothing; the server skips the whole script.

**17.** The server rendered `Hy` with `v = 7`, and the client hydrates the same markup with `v = 1`. In dev, what does the final DOM contain?

```html
<script>
  let { v } = $props();
</script>
<p>{v}</p>
<img src={'/' + v} alt="">
<div>{@html '<i>' + v + '</i>'}</div>
{#if v === 1}<b>one</b>{:else}<b>other</b>{/if}
```

a.  `<p>1</p>`, `src="/1"`, `<i>1</i>`, `<b>one</b>`: everything is repaired.
b.  `<p>1</p>`, `src="/7"`, `<i>7</i>`, `<b>one</b>`: text and the `{#if}` branch are repaired, the `<img src>` and `{@html}` are not.
c.  `<p>7</p>`, `src="/7"`, `<i>7</i>`, `<b>other</b>`: nothing is repaired.
d.  Hydration fails with `hydration_failed` and the app is rebuilt from scratch.

**18.** What is the text content of the paragraph?

```html
<p>foo<span> - bar</span></p>
```

a.  `foo - bar`
b.  `foo- bar`
c.  `foo -bar`
d.  `foo-bar`

### Find the bug

**19.** A team ships the following custom element, but the host page can never change `max` or `label`; the compiler printed a warning during the build. Name the warning and fix the component.

```html
<svelte:options customElement="x-meter" />
<script>
  let props = $props();
</script>
<meter max={props.max} aria-label={props.label}></meter>
```

**20.** The team also gave the element a prop called `onselect` so hosts could pass a callback with `el.onselect = fn`, but it never fires. Explain why and give the supported way to emit the event.

**21.** The marketing site is server-rendered. Search engines see an empty `<time>` tag, but users see the date after load. Find the bug and fix it so that the server HTML contains the date.

```html
<script>
  let { date } = $props();
  let formatted = $state('');
  $effect(() => {
    formatted = new Intl.DateTimeFormat('en-GB').format(date);
  });
</script>

<time>{formatted}</time>
```

**22.** After hydration the console shows `hydration_mismatch` warnings, and the page flickers. The template contains the following. Explain the cause and give two ways to fix it.

```html
<p>Rendered at {new Date().toLocaleTimeString()}</p>
<p>Your ticket: {Math.random().toString(36).slice(2, 8)}</p>
```

### Short answer

**23.** Explain, in three or four sentences, what `hydrate` does with the server markup and why the comment nodes inside the target must not be stripped by an HTML minifier.

**24.** A colleague wants to ship a Svelte web component library that works in Angular, React and plain HTML. Name the three biggest limitations of Svelte custom elements that you would document for consumers.

**25.** Give two valid reasons to keep using Svelte stores in a new Svelte 5.57 codebase, and the bridge functions that connect them to runes.

### Scenario / design

**26.** You inherit a Svelte 4 SvelteKit application with about 300 components, many `createEventDispatcher` calls, slots, a handful of global writable stores, vitest tests with the Svelte 4 API (`new Component`), and a dependency on two third-party Svelte 4 component libraries. Write a migration runbook: the order of work, what you automate, what you do by hand, how mixed mode helps, how tests are migrated, and what risks you track.

**27.** Design a public `<x-rating>` custom element that must (a) work inside a native HTML `<form>`, (b) be themable by the host page, (c) be usable from React and Angular, and (d) not break when two different versions of your library appear on one page. Describe the Svelte features you use for each requirement and the trade-offs you accept.

## Test 6: Expert Level — Reactivity Internals, Async Svelte and SSR/Hydration

Covers Chapters 5, 13 and 14, with reach-backs to Chapters 3, 4, 12 and 18. Questions about the runtime describe `svelte@5.57.2` internals, which are private and version-specific; the book (and this test) treats them as a mental model for debugging, not as API. Questions marked “(async flag)” assume `compilerOptions.experimental.async: true`; the others assume the default (unflagged) compiler.

### Multiple choice

**1.** A reaction is `MAYBE_DIRTY` rather than `DIRTY`. What does that mean?

a.  One of its direct sources was written with a different value.
b.  A *derived* it depends on was marked, and nobody yet knows whether that derived’s value will actually change.
c.  It was created but has never run.
d.  It is paused by an outro transition.

**2.** A `$state` source `s` is read by a `$derived` `d`, which is read by a user effect `e`. A write to `s` leaves the *value* of `d` unchanged. Which mechanism stops `e` from re-running?

a.  `mark_reactions` compares values before scheduling `e`.
b.  `e` is scheduled, but `update_derived(d)` bumps `d`’s write version only if its value changed; the dirty check on `e` finds `d.wv <= e.wv`, resets `e` to `CLEAN` and skips it.
c.  Svelte deep-compares `d`’s old and new values with `structuredClone`.
d.  The derived is read inside `untrack`, so `e` never depended on it.

**3.** What is the rule behind `state_unsafe_mutation`, as implemented in `$.set`?

a.  State may never be written outside event handlers.
b.  In dev and runes mode, writing a source throws when the active reaction is a derived, block effect, async derived or eager effect, unless the source was created in that same reaction.
c.  State written twice in one flush throws.
d.  Writing state inside `$effect` always throws.

**4.** Why does code placed directly in a component’s `<script>` read state without creating dependencies?

a.  The compiler wraps the script in `untrack(...)` at build time.
b.  The component body runs inside a branch effect with `active_reaction = null`, so reads are not registered anywhere; only the effects created inside it (template effects, `$effect`) track.
c.  Reads in the script are served from a snapshot.
d.  State is only readable inside templates.

**5.** Which mapping of runtime effect kinds is correct?

a.  `mount(App)`: root effect; a component body: branch effect; `{#if}`: block effect; `{count}` in markup: render effect; `$effect(...)`: user effect; `$state.eager`: eager effect.
b.  `mount(App)`: branch effect; a component body: root effect; `{#if}`: render effect; `{count}`: block effect; `$effect(...)`: eager effect.
c.  Every construct is a plain `EFFECT`; the kinds only differ in flags used by `$inspect`.
d.  `{#if}` and `$effect(...)` are both user effects.

**6.** Why does the runtime disconnect a derived that no effect depends on?

a.  To make it writable.
b.  So that the derived is no longer listed in its dependencies’ `reactions` arrays; otherwise long-lived sources would keep unobserved deriveds (and their closures) alive and notified, and they could never be garbage-collected. It revalidates through version checks when read again.
c.  To avoid the equality cut-off.
d.  To run its teardown on the next microtask.

**7.** (async flag) A module `store.svelte.ts` contains `export const user = $derived(await fetchUser(id))` at the top level. What happens when it runs?

a.  The derived is created lazily on first read.
b.  It throws `async_derived_orphan`: an async derived starts its work proactively through an effect, and a module top level has no effect tree to own it. Create it in a component’s initialisation.
c.  It compiles to a normal derived and the promise is unwrapped.
d.  It throws `illegal_await_expression` at compile time.

**8.** (async flag) Which statements about `$effect.pending()` and the `pending` snippet are correct?

a.  The `pending` snippet is shown on every update; `$effect.pending()` is for the first render.
b.  The `pending` snippet is for the first render of the boundary only; `$effect.pending()` returns the number of pending promises in the current boundary (excluding child boundaries) and must be read inside an effect or derived or template.
c.  `$effect.pending()` counts promises in all nested boundaries and can be read anywhere.
d.  Both are identical; one is the older name of the other.

**9.** (async flag) What does `await tick()` do compared with Svelte without the flag?

a.  The same: one microtask, then `flushSync()`.
b.  It races `requestAnimationFrame` against `setTimeout`, so it can resolve before in-flight async work completes; it does not mean “all async work is done”.
c.  It waits for every pending promise in the app.
d.  It is removed; calling it throws `tick_removed`.

**10.** (async flag, server) A `<svelte:boundary>` with a `pending` snippet contains `{await load('inside')}`. What does `await render(App)` do with it?

a.  Awaits `load('inside')` and renders the content.
b.  Renders only the `pending` snippet; the boundary’s content is skipped and `load('inside')` is never called on the server. The client fills the boundary after hydration.
c.  Renders the pending snippet first, then streams the content in the same response.
d.  Throws `await_invalid`.

**11.** (async flag) Which statement about `hydratable(key, fn)` is correct?

a.  It works without the async flag and without a render context.
b.  On the server it runs `fn`, serialises the value (with `devalue`, including Promises) into an inline script in `head`; during hydration it returns the stored value without calling `fn`. It needs the flag (`experimental_async_required`) and a render context (`server_context_required`).
c.  It stores values in cookies.
d.  It only serialises JSON, so a `Date` is returned as a string.

### Code reading: what does this log, print or render?

**12.** What is logged?

```js
let x = $state(1);
let a = $derived(x % 2);
let b = $derived(a + 1);
let c = $derived(a + 2);
let runs = 0;
const stop = $effect.root(() => {
  $effect(() => { runs++; console.log('eff', b, c); });
});
flushSync();
x = 3;
flushSync();
console.log('runs', runs);
x = 2;
flushSync();
console.log('runs', runs);
```

a.  `eff 2 3`, `runs 1`, `eff 1 2`, `runs 2`
b.  `eff 2 3`, `eff 2 3`, `runs 2`, `eff 1 2`, `runs 3`
c.  `eff 2 3`, `runs 2`, `eff 1 2`, `runs 3`
d.  `eff 2 3`, `runs 1`, `runs 1`

**13.** What does the last line print, and how many times was the derived’s function called?

```js
let n = $state(1);
let calls = 0;
let d = $derived.by(() => { calls++; return n * 2; });

console.log(d, d, d, calls);
n = 2;
console.log(calls);
console.log(d, d, calls);
```

a.  `2 2 2 1`, `1`, `4 4 2`
b.  `2 2 2 3`, `3`, `4 4 5`
c.  `2 2 2 1`, `2`, `4 4 2`
d.  `2 2 2 1`, `1`, `4 4 3`

**14.** Two effects write state that the other reads. After the first `flushSync` and after the second, what are the logs?

```js
let a = $state(1);
let b = $state(0), c = $state(0);
const stop = $effect.root(() => {
  $effect(() => { console.log('A'); b = a * 2; });
  $effect(() => { console.log('B'); c = b + 1; });
});
flushSync();
console.log(b, c);
a = 5;
flushSync();
console.log(b, c);
```

a.  `A`, `B`, `2 3`, `A`, `B`, `10 11`
b.  `A`, `B`, `0 0`, `A`, `B`, `0 0`
c.  `A`, `B`, `A`, `B`, `2 3`, then `A`, `B`, `A`, `B`, `10 11`
d.  `A`, `B`, `2 1`, `A`, `B`, `10 3`

**15.** How many times has the effect run at each `console.log`?

```js
let a = $state(0);
let runs = 0;
const stop = $effect.root(() => { $effect(() => { a; runs++; }); });
flushSync();
console.log('init', runs);
a++; a++; a++;
console.log('sync', runs);
await Promise.resolve();
console.log('micro', runs);
await tick();
console.log('tick', runs);
```

a.  `init 1`, `sync 1`, `micro 2`, `tick 2`
b.  `init 1`, `sync 4`, `micro 4`, `tick 4`
c.  `init 1`, `sync 1`, `micro 4`, `tick 4`
d.  `init 1`, `sync 1`, `micro 1`, `tick 2`

**16.** What are the effect log lines, in order?

```js
let a = $state(0), b = $state(0);
const stop = $effect.root(() => {
  $effect(() => {
    console.log('outer', a);
    $effect(() => {
      console.log('inner', b);
      return () => console.log('inner cleanup');
    });
    return () => console.log('outer cleanup');
  });
});
flushSync();
b = 1;
flushSync();
a = 1;
flushSync();
stop();
```

a.  `outer 0`, `inner 0`, `inner cleanup`, `inner 1`, `inner cleanup`, `outer cleanup`, `outer 1`, `inner 1`, `inner cleanup`, `outer cleanup`
b.  `outer 0`, `inner 0`, `inner cleanup`, `inner 1`, `outer 1`, `outer cleanup`, `inner cleanup`
c.  `outer 0`, `inner 0`, `outer cleanup`, `outer 0`, `inner 0`, …
d.  `outer 0`, `inner 0`, `inner 1`, `outer 1`, `inner 1`

**17.** What is logged?

```js
let a = $state(0);
const d = $derived(a * 10);
const stop = $effect.root(() => {
  $effect(() => {
    console.log('run', d);
    return () => console.log('teardown', d, a);
  });
});
flushSync();
a = 1;
flushSync();
stop();
```

a.  `run 0`, `teardown 0 0`, `run 10`, `teardown 10 1`
b.  `run 0`, `teardown 10 1`, `run 10`, `teardown 10 1`
c.  `run 0`, `run 10`, `teardown 10 1`
d.  `run 0`, `teardown 0 1`, `run 10`, `teardown 10 1`

**18.** (async flag) The component below stays mounted. `log` is `console.log`. After the first value settles, the script calls `set('slow')`, `flushSync()` and waits 1 ms; then `set('fast')`, `flushSync()`, waits 1 ms; then waits 200 ms. Which timeline is right?

```html
<script>
  import { getAbortSignal } from 'svelte';
  let { log } = $props();
  let q = $state('a');
  const delays = { a: 5, slow: 100, fast: 10 };

  function load(q, signal) {
    log('start ' + q);
    return new Promise((res) => {
      const t = setTimeout(() => res(q.toUpperCase()), delays[q]);
      signal.addEventListener('abort', () => { clearTimeout(t); log('abort ' + q); });
    });
  }

  const result = $derived(await load(q, getAbortSignal()));
  export function set(v) { q = v; }
</script>

<svelte:boundary>
  <p id="r">{result}</p>
  <p id="e">{$state.eager(q)}</p>
  {#snippet pending()}<p>loading</p>{/snippet}
</svelte:boundary>
```

a.  Logs: `start a`, `abort a`, `start slow`, `abort slow`, `start fast`. After `set('slow')`: result `A`, eager `slow`. After `set('fast')`: result `A`, eager `fast`. At the end: result `FAST`; `SLOW` was never shown.
b.  Logs: `start a`, `start slow`, `start fast`. After `set('slow')`: result `SLOW` once its timer ends; the end state is `SLOW`.
c.  Logs: `start a`, `abort a`, `start slow`, `abort slow`, `start fast`. After `set('slow')`: result `SLOW`, eager `slow`. The end state is `FAST`.
d.  Logs: `start a`, `start slow`, `abort slow`, `start fast`. The eager text stays `a` until the result is ready.

**19.** (async flag) `inc()` increments `n`. The markup is `<p id="v">{await slow(n)}</p><p id="n">{n}</p>` where `slow(n)` resolves `n * 10` after 50 ms. After the initial render settles, `v` is `10` and `n` is `1`. What do the two snippets print for the text of `#v` and `#n`, read immediately after each `await` chain?

```js
const text = (sel) => document.querySelector(sel).textContent;

// Snippet A
c.inc();
await settled();
console.log(text('#v'), text('#n'));

// Snippet B (a fresh start, same initial state)
c.inc();
await tick();
await settled();
console.log(text('#v'), text('#n'));
```

a.  A: `20 2`; B: `20 2` (stale, the new value `30` is still in flight)
b.  A: `20 2`; B: `30 3`
c.  A: `10 1`; B: `20 2`
d.  A: `20 2`; B: `20 2`, and the value `30` never arrives

**20.** (async flag) A menu component `Menu` has a top-level `await` that logs `menu loader start` and resolves after 30 ms. The parent does `const f = fork(() => { open = true; })` on pointer enter (with `{#if open}<Menu />{/if}` inside a boundary). What can you observe 100 ms later, and after `await f.commit()`?

a.  Immediately after `fork`: `menu loader start` is logged but `#menu` is not in the DOM; 100 ms later still not in the DOM; after `commit()` it is in the DOM and the loader ran exactly once.
b.  Immediately after `fork`: `#menu` is in the DOM; `commit()` only reveals it.
c.  Nothing is logged until `commit()`; the loader runs on commit.
d.  The loader runs twice: once speculatively and once on commit.

**21.** (async flag, server build) What does this print for the logs and for the body? Then what happens if the caller writes `render(App).body` without `await`?

```html
<script>
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function load(name) { console.log('load ' + name); await sleep(5); return name; }
  const a = await load('outside');
</script>
<h1>{a}</h1>
<svelte:boundary>
  <p>{await load('inside')}</p>
  {#snippet pending()}<p>loading</p>{/snippet}
</svelte:boundary>
```

a.  Logs `load outside`, `load inside`; body contains `<h1>outside</h1><p>inside</p>`; sync access returns an empty body.
b.  Logs `load outside` only; body contains `<h1>outside</h1>` and `<p>loading</p>`; sync access throws `await_invalid`.
c.  Logs `load outside` only; body contains only `<p>loading</p>`; sync access returns the same body.
d.  Logs nothing; the server skips all `await` expressions and hydrates them on the client; sync access works.

### Find the bug

**22.** (async flag) `total` is correct on first render, but never updates when `b` changes. Why, and what are two fixes?

```html
<script>
  let a = $state(1);
  let b = $state(2);

  async function sum() {
    return (await Promise.resolve(a)) + b;
  }

  const total = $derived(await sum());
</script>

<p>{total}</p>
```

**23.** (async flag) A speculative-preload handler throws `fork_timing`. Why, and how do you fix it?

```html
<script>
  import { fork } from 'svelte';
  let open = $state(false);
  let hover = $state(false);

  function onenter() {
    hover = true;
    fork(() => { open = true; });
  }
</script>
```

**24.** A boundary should retry after a failure, but the content never comes back and the console shows `svelte_boundary_reset_onerror`. Fix it.

```html
<svelte:boundary onerror={(error, reset) => { report(error); reset(); }}>
  <Report id={id} />
</svelte:boundary>
```

**25.** (async flag) A server entry point is intermittently throwing a server error `await_invalid`. Explain and fix the code.

```ts
import { render } from 'svelte/server';
import App from './App.svelte';   // contains `await` in a $derived

export function handle(url: string) {
  const { head, body } = render(App, { props: { url } });
  return `<html><head>${head}</head><body>${body}</body></html>`;
}
```

### Short answer

**26.** Explain “push-pull” reactivity as implemented by `mark_reactions`, `is_dirty` and `update_derived`, and say why checking equality in the pull phase (rather than at mark time) is what makes the cut-off work.

**27.** Explain how the same batch mechanism (`batch_values`) can serve both `fork()` and synchronised async updates, and why `$state.eager` must bypass it.

**28.** A page renders fine on the server but a security review flags the inline `hydratable` script. State the two CSP strategies that Svelte’s `render` supports, when to use each, what happens if you set both, and which compile option you need if `require-trusted-types-for 'script'` is enforced.

### Scenario / design

**29.** Design the data layer of a product search page using async Svelte (flag on): live query input with instant feedback, cancellation of stale requests, a loading state that distinguishes first load from refresh, error handling with retry, optimistic “favourite” toggles, and SSR with no duplicated server work on hydration. Name each API and the failure modes you accept because the feature is experimental.

**30.** Production incident: after a release, (a) some users see the previous user’s name for a second after load, (b) the console shows `hydration_mismatch`, (c) the CSP report endpoint receives blocked inline script reports, and (d) an admin page occasionally freezes with `effect_update_depth_exceeded`. Give a diagnosis plan that maps each symptom to the likeliest Svelte-level cause and fix, and how you would verify each with the tools the book describes.
