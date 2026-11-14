# Chapter 8: Bindings and Forms

`bind:` is the directive that lets data flow *up*: from an element or a child component into the variable you wrote in the parent. Svelte did not invent two-way binding, but its implementation is unusually direct: a binding is a pair of small compiled pieces, an event listener that writes to your state and a render effect that writes your state back to the DOM property. There is no model layer, no change detection loop and no synthetic event system, which makes bindings cheap and predictable, and also means their edge cases (coercion, ordering, form reset, ownership) are worth knowing precisely.

This chapter covers the semantics of two-way binding, every element binding Svelte supports, function bindings (5.9) and why they should be your default tool for validation and formatting, `bind:this`, component bindings and `$bindable` ownership, forms (`defaultValue`, `defaultChecked`, reset behaviour), the compile-time rules, and patterns for controlled and uncontrolled inputs. Props and `$bindable` at the API level were introduced in Chapter 7. Events and delegation are in Chapter 6.

I verified the behaviours below against `svelte@5.57.2` in jsdom (dev mode) and by reading the runtime source in `internal/client/dom/elements/bindings/`. Where the prose docs and the source disagree I say so.

## How a binding works

`bind:property={expression}` requires `expression` to be an lvalue: an identifier or a member expression (`value`, `user.name`, `rows[i].done`), or, since 5.9, a `{get, set}` pair. When the name matches, use the shorthand: `<input bind:value />` equals `<input bind:value={value} />`.

For `<input bind:value={text}>` the compiler wires two things:

1.  **DOM to state.** A listener on the `input` event reads `input.value` and calls the setter. For `bind:checked` the event is `change`; for media it is a mix of media events; for dimensions it is a `ResizeObserver`.
2.  **State to DOM.** A render effect reads the getter and assigns `input.value` when it differs. It skips the assignment if the value is already equal (so `minlength` validation and caret position survive), and for number inputs it skips when `to_number(input.value)` already equals the state (so typing `00` is not “corrected” to `0` under your cursor).

A third piece matters more than it looks. After the `input` event handler runs, Svelte waits one `tick()` and then compares the bound value to what you *meant*. The source (`bind_value`):

```js
await tick();
// Respect any validation in accessors
if (value !== (value = get())) {
  var start = input.selectionStart; var end = input.selectionEnd; var length = input.value.length;
  input.value = value ?? '';
  // restore the caret: stay at the end if it was at the end and the text grew, else clamp
}
```

If your setter rejected or transformed the value, the DOM is rewritten and the caret restored. That is the mechanism behind function bindings that normalise input.

### Ordering relative to event handlers

Two statements exist in the docs and they are about different cases. The `bind:` page says: “If an element already has a listener for the same event, that listener will be fired before the bound value is updated.” The basic markup page says: “event attributes always fire after events from bindings (e.g. `oninput` always fires after an update to `bind:value`).” In a test with `<input bind:value oninput={() => log.push(value)} />` I observed the attribute handler seeing the *new* value, which matches the second statement. Treat the first as covering listeners that are registered before the binding does (for example a native `addEventListener` registered earlier, or legacy `on:input`): those run first and see the old bound value. For code you write with `oninput`, you can rely on the new value.

Bindings and delegated events (Chapter 6) are independent: the `input` listener the binding installs is a direct listener on the element, not a delegated one.

## Input bindings

### `bind:value` on text-like inputs and `<textarea>`

```html
<script lang="ts">
  let message = $state('hello');
</script>

<input bind:value={message} />
<textarea bind:value={message}></textarea>
<p>{message}</p>
```

The state is the DOM value as a string. `$state('')` is the right initial value; if you start with `null` or `undefined` and the element already has a value (a server-rendered `value` or a browser autofill), the element’s value initialises the state: the source condition is `get() == null && input.value`. If both exist, the binding wins.

### Numeric inputs

For `type="number"` and `type="range"` the value is coerced to a number:

```html
<script lang="ts">
  let a = $state<number | null>(1);
</script>
<input type="number" bind:value={a} min="0" max="10" />
<input type="range" bind:value={a} min="0" max="10" />
```

Here the prose docs and the runtime differ. The docs say: “If the input is empty or invalid (in the case of `type="number"`), the value is `undefined`.” The 5.57.2 source is:

```js
function to_number(value) {
  return value === '' ? null : +value;
}
```

and my jsdom run confirmed it: typing `42` gave `42` (a number), clearing the field gave `null`. Type your state as `number | null` (and treat `undefined` as also possible, because initial state may be `undefined` and the property may be absent in older code), and do not write `=== undefined` checks. Browsers report `''` for both an empty field and an unparseable number, so there is no way to distinguish them.

### `bind:checked` and `bind:indeterminate`

```html
<script lang="ts">
  let accepted = $state(false);
  let indeterminate = $state(true);
</script>
<input type="checkbox" bind:checked={accepted} bind:indeterminate />
```

`indeterminate` is independent of `checked`. A common use is a tri-state “select all” box whose `indeterminate` is derived from a selection count; since a binding writes back, derive it as a function binding with a read-only getter (below) or set it in the handler.

`bind:value` on a checkbox is a mistake: the listener would read `input.value` (the static `value` attribute). In dev mode it throws `bind_invalid_checkbox_value` (“Using `bind:value` together with a checkbox input is not allowed. Use `bind:checked` instead”); I reproduced it. Radios use `bind:group`, not `bind:checked`.

### `bind:group`

`bind:group` links inputs that belong together. Radios write the chosen input’s `value` into a scalar; checkboxes keep an array of the checked values:

```html
<script lang="ts">
  let tortilla = $state('Plain');
  let fillings = $state<string[]>([]);
</script>

{#each ['Plain', 'Whole wheat', 'Spinach'] as t}
  <label><input type="radio" bind:group={tortilla} value={t} /> {t}</label>
{/each}

{#each ['Rice', 'Beans', 'Cheese'] as f}
  <label><input type="checkbox" bind:group={fillings} value={f} /> {f}</label>
{/each}

<p>{tortilla}: {fillings.join(', ') || 'none'}</p>
```

In my run, selecting “Spinach” set `tortilla` to `"Spinach"`; checking Rice, checking Beans and unchecking Rice left `["Beans"]`. Rules:

- The inputs must be in the **same component**. Passing a group variable into a child and binding it there will not coordinate across components. (Pass the array down and use callbacks, or use `<input type="checkbox" checked={...} onchange>`.)
- The `value` can be any value, not just strings, if you set it with an expression (`value={obj}`); comparison for radios is identity.
- A group inside an `{#each}` may bind to a member of the item (`bind:group={row.selected}`); the compiler handles the each-context specially.
- The group variable should be `$state`. Svelte keeps the DOM in sync in both directions: assigning `fillings = ['Rice']` checks the matching boxes.

### `bind:files`

On `<input type="file">`, `bind:files` exposes the `FileList`:

```html
<script lang="ts">
  let files = $state<FileList | undefined>();
  const first = $derived(files?.item(0));

  function clear() {
    files = new DataTransfer().files; // null or undefined does NOT clear the input
  }
  function removeAt(i: number) {
    const dt = new DataTransfer();
    [...(files ?? [])].forEach((f, j) => j !== i && dt.items.add(f));
    files = dt.files;
  }
</script>

<input type="file" accept="image/png, image/jpeg" multiple bind:files />
{#if first}<p>{first.name} ({first.size} bytes)</p>{/if}
<button onclick={clear}>clear</button>
```

Constraints (docs and migration guide):

- Allowed values are `null`, `undefined` or a `FileList`. Anything else is an error.
- `FileList` objects are immutable and cannot be constructed directly, so you build one through `new DataTransfer().files`. That is also how you remove a single file: create a `DataTransfer`, add the files to keep, assign its `files`.
- Do not initialise the state with `new DataTransfer().files`; `DataTransfer` does not exist in server-side runtimes. Leave the state uninitialised so server rendering does not touch it.
- Reading `files` in a template is fine, but `FileList` is not a state proxy; if you want reactivity inside it, derive plain data (names, sizes) from it.

### `<select>`

A `<select bind:value>` binds to the selected option’s `value`, which can be any value, not only a string, because Svelte stores the JavaScript value on the option (`option.__value`):

```html
<script lang="ts">
  const a = { id: 1 }, b = { id: 2 };
  let selected = $state<{ id: number } | undefined>();
  let multi = $state<string[]>([]);
</script>

<select bind:value={selected}>
  <option value={a}>a</option>
  <option value={b}>b</option>
</select>

<select multiple bind:value={multi}>
  <option>x</option><option>y</option><option>z</option>
</select>
```

Verified details:

- With `selected` initially `undefined`, the first option is selected by the browser and the state is updated to it (`{ id: 1 }`). If the initial state is defined, the binding wins over any `selected` attribute. If the state matches no option, the runtime sets `selectedIndex = -1` (no selection) once it is not the mounting pass.
- `selected = b` selects the second option; changing the select’s index to 1 set the state to the same object `b` (identity, not a copy, so you can look the choice up in a `Map` or compare with `===`).
- `multiple` binds an array, in option order: choosing the first and third options gave `["x", "z"]`. If the value is `null`/`undefined` the selection is kept; if it is not an array the runtime warns `select_multiple_invalid_value` and keeps the selection.
- When an option’s `value` equals its text, omit the attribute: `<option>Rice</option>`.
- Options generated by `{#each}` are handled by a `MutationObserver` that re-applies the bound value when the option list changes, so an async-loaded list does not lose the selection. The model value is deliberately *not* overwritten when options change; it changes only on user input or assignment.

Svelte 5.47 added support for customizable `<select>` (Chapter 6); bindings keep working with `<selectedcontent>`.

### Defaults and form reset

A form reset restores each control to its *default*: the `value` attribute, `checked` attribute, or `<option selected>`. Svelte 5 makes bindings react to resets (a Svelte 4 binding would go stale because no `input` event fires). Since 5.6 you declare defaults for inputs with `defaultValue` and `defaultChecked`, and since 5.57 for selects:

```html
<script lang="ts">
  let value = $state('');
  let checked = $state(false);
  let size = $state('c');
</script>

<form>
  <input bind:value defaultValue="not the empty string" />
  <input type="checkbox" bind:checked defaultChecked={true} />
  <select bind:value={size} defaultValue="b">
    <option>a</option><option>b</option><option>c</option>
  </select>
  <input type="reset" value="Reset" />
</form>
```

For the initial render, **the binding’s value wins** unless it is `null` or `undefined`. After a reset, the default wins. My test: set `value = 'typed'`, `checked = false`, `sel = 'c'`; the first render showed `typed`, `false`, `c`. After editing and calling `form.reset()`, the state (one microtask later) was `default!`, `true`, `b`.

How it works (source, `shared.js` and `misc.js`): a single capturing `reset` listener is installed on the `document` once, the first time any binding needs it. On a reset it waits a microtask (“or else the dom properties of the form elements have not updated to their reset values yet”), and unless the event was `defaultPrevented`, walks `evt.target.elements` and invokes each bound control’s reset handler, which re-reads the control. Consequences:

- It listens on the **document** in the capture phase, so `stopPropagation` in your own handlers cannot hide a reset from bindings, but `preventDefault()` on the reset event cancels the resynchronisation, as it cancels the reset itself.
- Only controls inside the form’s `elements` list are touched. A control associated via the `form="id"` attribute is part of `elements`; a control outside the form is not.
- The update is asynchronous. After calling `form.reset()` programmatically, `await tick()` (or a microtask) before reading state.

The docs’ caution applies: use reset buttons sparingly.

## Media, image, details, contenteditable

**Media (`<audio>`, `<video>`).** Five two-way bindings: `currentTime`, `playbackRate`, `paused`, `volume`, `muted`. Seven read-only: `duration`, `buffered`, `seekable`, `seeking`, `ended`, `readyState`, `played`. `<video>` adds read-only `videoWidth` and `videoHeight`.

```html
<script lang="ts">
  let { src }: { src: string } = $props();
  let time = $state(0);
  let duration = $state(0);
  let paused = $state(true);
</script>

<video {src} bind:currentTime={time} bind:duration bind:paused></video>
<button onclick={() => (paused = !paused)}>{paused ? 'play' : 'pause'}</button>
<input type="range" min="0" max={duration || 0} step="0.1" bind:value={time} />
```

Binding `currentTime` makes the video seek whenever you assign; the binding updates as the `timeupdate`/animation frame advances. Make `duration` start as `0` because it is `NaN` until metadata loads.

**`<img>`** has read-only `naturalWidth` and `naturalHeight`.

**`<details bind:open>`** binds the `open` property (it listens for the `toggle` event). My test: setting `details.open = true` and dispatching `toggle` updated the state to `true`.

**contenteditable.** Elements with `contenteditable` support `innerHTML`, `innerText` and `textContent` bindings. Verified: editing the element and firing `input` updated `html` to the new markup. Two cautions. `innerHTML` is XSS-prone for the same reasons as `{@html}` (Chapter 6): the user (or pasted content) controls the HTML. And the binding takes complete control of the contents: a template expression inside the editable element, such as `<div contenteditable bind:textContent>count is {count}</div>`, will **not** update when `count` changes (migration guide); the content should only change through the binding.

**Dimensions.** Every visible element supports read-only bindings measured with a `ResizeObserver`: `clientWidth`, `clientHeight`, `offsetWidth`, `offsetHeight`, `contentRect`, `contentBoxSize`, `borderBoxSize`, `devicePixelContentBoxSize`.

```html
<script lang="ts">
  let w = $state(0), h = $state(0);
  let box = $state<readonly ResizeObserverSize[] | undefined>();
</script>

<div bind:offsetWidth={w} bind:offsetHeight={h} bind:contentBoxSize={box}>
  {w} × {h}
</div>
```

Implementation facts from `size.js`: one shared `ResizeObserver` per box type (`content-box`, `border-box`, `device-pixel-content-box`) observes all elements, “because of how Chromium batches” notifications; the four `client*`/`offset*` bindings use the border-box observer and read the property on each notification (and once after mount, untracked). Restrictions: `display: inline` elements have no size and cannot be observed (use `inline-block`, except intrinsically sized ones like `<img>` and `<canvas>`), CSS transforms do not trigger the observer, and `devicePixelContentBoxSize` needs Firefox 93 and is not supported in Safari. They are read-only: assigning has no effect (and you would use a `null` getter with function bindings to run code on each change, shown below). The first value arrives after mount, so initialise state to `0` and do not branch on it during server rendering.

## `bind:this`

`bind:this={ref}` stores the DOM element (or, on a component, its exports object) in a variable.

```html
<script lang="ts">
  let canvas = $state<HTMLCanvasElement>();

  $effect(() => {
    const ctx = canvas?.getContext('2d');
    if (!ctx) return;
    ctx.fillRect(0, 0, 10, 10);
  });
</script>

<canvas bind:this={canvas}></canvas>
```

Lifetime, from `this.js` and my test:

- The value is `undefined` until the element is mounted, set in an effect after mount. Reading it during component initialisation sees `undefined`; use an effect, an attachment (Chapter 9) or an event handler.
- When the element (or component) is destroyed, the variable is set to **`null`** (my effect logged `element`, then `null`, after toggling an `{#if}` off). The teardown is timed as close as possible to the destruction of the *outermost* effect being destroyed, with a code comment that this may be simplified in Svelte 6.
- Declare it as `$state` if an effect or template depends on it; a plain `let` is fine for handlers that read it later. If it is `$state`, an effect that reads it re-runs on mount and on destroy.
- Inside `{#each}`, `bind:this={els[i]}` works; the runtime tracks the “parts” of the each context so the binding at an old index is nulled when the item moves.
- With a function binding the getter is required “to ensure that the correct value is nullified on component or element destruction”: `bind:this={() => el, (v) => (el = v)}`.
- On a component, `bind:this` exposes the instance’s exports only (Chapter 7).

## Function bindings (5.9)

A function binding is `bind:property={get, set}`:

```html
<script lang="ts">
  let value = $state('');
</script>

<input bind:value={() => value, (v) => (value = v.toLowerCase())} />
```

The getter is read whenever the DOM needs updating; the setter is called with the DOM value. They are the right tool for three jobs, and they remove most of the cases that used to be `$effect` or `$:`.

**1. Validation / transformation without effects.**

```html
<script lang="ts">
  let upper = $state('');
</script>
<input bind:value={() => upper, (v) => (upper = v.toUpperCase())} />
```

In my test, typing `shout` left the input showing `SHOUT` and state `"SHOUT"`. That is the `await tick()` rewrite shown earlier: the setter stored the uppercase value, the render effect saw that `input.value` differed and wrote it back, and the caret was restored by the logic in `bind_value`. Compare the effect-based alternative (`$effect(() => { value = value.toUpperCase() })`), which writes state from an effect, runs after DOM updates, causes a transient frame with the wrong value, and risks update loops.

**2. Separate display and model formats.**

```html
<script lang="ts">
  let cents = $state(1999);
  const fmt = (c: number) => (c / 100).toFixed(2);
</script>

<input
  inputmode="decimal"
  bind:value={
    () => fmt(cents),
    (text) => {
      const n = Number.parseFloat(text);
      if (Number.isFinite(n)) cents = Math.round(n * 100);
    }
  }
/>
```

The model is an integer; the field shows a decimal. When the user types something unparseable, the setter leaves `cents` unchanged; after the tick, Svelte rewrites the field to `fmt(cents)` (note that this rewrites the field on every keystroke when the formatted string differs from what the user typed, for example `1.5` becoming `1.50`. For currency fields, it is friendlier to format on `blur`; see the patterns section).

**3. Read-only bindings with a `null` getter.** For bindings that only report (dimensions, media readonly properties), pass `null` as the getter to run a function when the value changes without storing it:

```html
<div bind:clientWidth={null, redraw} bind:clientHeight={null, redraw}>...</div>
```

Function bindings also work on components (`<Keypad bind:value={() => pin, (v) => (pin = v.slice(0, 4))} />`), on `bind:group`, and on `bind:this`. A binding with only a getter (`bind:value={() => w}`) is a compile error (`bind_invalid_expression`: “Can only bind to an Identifier or MemberExpression or a `{get, set}` pair”), which I confirmed. The setter must be a function expression in the template, not a reference built elsewhere.

> **Senior tip:** If you find yourself writing `$effect(() => { a = f(b) })`, ask whether `a` can be `$derived`, whether `a` is really a bound control (function binding), or whether the write belongs in an event handler. Effects that write state are the least predictable of the three.

## Component bindings and ownership

`bind:prop` on a component binds to one of its props, provided the child declared it with `$bindable()`:

```html
<!-- Keypad.svelte -->
<script lang="ts">
  let { value = $bindable('') }: { value?: string } = $props();
</script>
<button onclick={() => (value += '1')}>1</button>
```

```html
<script lang="ts">
  import Keypad from './Keypad.svelte';
  let pin = $state('');
</script>
<Keypad bind:value={pin} />
```

Remember the rules from Chapter 7: bindable is *permission*, not obligation; a bindable with a fallback requires the parent to pass a defined value when binding (`props_invalid_value`, which I reproduced); bindable fallbacks are proxied when they are objects.

### Ownership: `ownership_invalid_binding`

State belongs to the component that declared it. When a mid-level component forwards a prop it received by one-way passing into a child’s `bind:`, the child can mutate state owned by the grandparent through an intermediary that never agreed to be a pass-through. Svelte detects it in dev:

```html
<!-- Child.svelte -->
<script lang="ts">
  let { value = $bindable() }: { value: { n: number } } = $props();
</script>
<button onclick={() => value.n++}>{value.n}</button>
```

```html
<!-- Own.svelte: receives `data` as a normal prop but binds it onward -->
<script lang="ts">
  import Child from './Child.svelte';
  let { data }: { data: { n: number } } = $props();
</script>
<Child bind:value={data} />
```

```html
<!-- Parent: owns the state -->
<script lang="ts">
  import Own from './Own.svelte';
  let d = $state({ n: 0 });
</script>
<Own data={d} />
```

Clicking logs (dev only):

```text
[svelte] ownership_invalid_binding
Own.svelte passed property `data` to Child.svelte with `bind:`, but its parent component Parent.svelte did not declare `data` as a binding. Consider creating a binding between Parent.svelte and Own.svelte (e.g. `bind:data={...}` instead of `data={...}`)
```

(I ran the real thing; the component names in the message are the file names.) The fix is to make the chain explicit: declare `data` with `$bindable()` in `Own` and write `<Own bind:data={d} />` in the parent, or give the child a callback instead. The same ownership machinery produces `ownership_invalid_mutation` when a child mutates a state proxy it received as a plain prop (Chapter 7).

> **Warning:** A binding chain makes the *source of truth* ambiguous. Every `$bindable` you add is a place where the parent’s state can change from somewhere it does not look. Use bindings for leaf controls (inputs, toggles, selections) and callbacks for events and commands.

### Bindings to each-block items

In runes mode you cannot bind to or reassign an each-block variable itself:

```html
{#each todos as todo}
  <input bind:value={todo} />       <!-- compile error each_item_invalid_assignment -->
{/each}
```

The compiler says: “Cannot reassign or bind to each block argument in runes mode. Use the array and index variables instead (e.g. `array[i] = value` instead of `entry = value`, or `bind:value={array[i]}` instead of `bind:value={entry}`)”. Binding to a *property* of the item is fine and is the normal pattern:

```html
{#each todos as todo (todo.id)}
  <input type="checkbox" bind:checked={todo.done} />
  <input bind:value={todo.text} />
{/each}
```

This mutates the `$state` array’s element in place, which updates exactly the places that read `todo.done`. It requires `todos` to be deep state (Chapter 3); with `$state.raw` there is nothing to mutate. Destructured each variables (`{#each todos as { id, text }}` then `bind:value={text}`) trigger the same error, and binding to a rest-destructured object triggers the warning `bind_invalid_each_rest` (“The rest operator (…) will create a new object and binding ‘rest’ with the original object will not work”).

## `<svelte:window>` and `<svelte:document>` bindings

Bindings to global objects use special elements, which must appear at the top level of the component (not inside blocks or elements):

```html
<script lang="ts">
  let y = $state(0);
  let width = $state(0);
  let online = $state(true);
</script>

<svelte:window bind:scrollY={y} bind:innerWidth={width} bind:online />
```

`<svelte:window>` binds `innerWidth`, `innerHeight`, `outerWidth`, `outerHeight`, `scrollX`, `scrollY`, `online` (alias of `navigator.onLine`) and `devicePixelRatio`. Only `scrollX` and `scrollY` are writable. The docs add a detail that prevents surprises: “the page will not be scrolled to the initial value to avoid accessibility issues. Only subsequent changes to the bound variable of `scrollX` and `scrollY` will cause scrolling. If you have a legitimate reason to scroll when the component is rendered, call `scrollTo()` in an `$effect`.”

`<svelte:document>` binds `activeElement`, `fullscreenElement`, `pointerLockElement` and `visibilityState`, all read-only:

```html
<svelte:document bind:visibilityState={visibility} bind:activeElement />
```

For reading these values *without* a template element, for example inside a `.svelte.ts` module, use `svelte/reactivity/window` (Chapter 9). Chapter 9 also covers `<svelte:body>` and `<svelte:head>`.

## Compile-time rules for bindings

| Code | Cause | Notes |
|------------------------|------------------------|------------------------|
| `bind_invalid_expression` | `bind:value={a + 1}`, or a getter without a setter | only identifiers, member expressions or `{get, set}` |
| `constant_binding` | binding to a `const` or an import | “Cannot bind to constant”, “Cannot bind to import” |
| `bind_invalid_name` | unknown binding name, e.g. `bind:foo` on a `<div>` |  |
| `bind_invalid_target` | `bind:value` on a `<div>`, or on `<svelte:element>` | only `<input>`, `<textarea>`, `<select>` |
| `each_item_invalid_assignment` | binding or reassigning an each item (runes) | use `array[i]` or an item property |
| `bind_invalid_each_rest` (warning) | binding to a rest-destructured each object |  |
| `bind_group_invalid_expression` | `bind:group` with an expression that is not bindable |  |
| `bind_invalid_checkbox_value` (runtime, dev) | `bind:value` on a checkbox |  |
| `props_invalid_value` (runtime) | `bind:x={undefined}` with a `$bindable` fallback |  |
| `ownership_invalid_binding` (dev warning) | binding through a non-binding intermediate |  |
| `binding_property_non_reactive` (dev warning) | binding to a property of a non-reactive object |  |
| `bind_not_bindable` (runtime) | binding a prop not declared `$bindable` | declared in the docs; I could not trigger it with 5.57.2 |

The warning `non_reactive_update` also applies to bindings: if you bind to a variable that is *updated* by the binding but not declared with `$state`, Svelte warns that `x` is updated, but not declared with `$state(...)`, because the UI will not react to the change. A binding target that is a plain `let` is almost always a bug. Binding to a property of a plain (non-state) object compiles fine, but in dev mode you get `binding_property_non_reactive`.

Also note: stores can be bound (`bind:value={$name}`) because `$name = x` is an assignment that calls `.set`, which keeps older store-based code working (Chapter 12).

## Patterns

### Controlled versus uncontrolled

React draws a hard line between “controlled” inputs (value supplied by state, every change handled) and “uncontrolled” ones (the DOM holds the truth, read on submit). Svelte offers both, and the choice is yours per field:

- **Controlled/two-way.** `bind:value` (or a function binding). The state is the truth; the DOM follows. Use it when other UI depends on the value while typing (live preview, validation messages, character counters).
- **Uncontrolled.** No binding. Read values on submit with `new FormData(form)` and let the browser own the input. This is the cheapest and most robust approach for large forms and it works without JavaScript when the form posts to a server. Combine with `defaultValue`s derived from state: `<input name="email" value={user.email} />` sets the property from state but nothing writes back.
- **One-way with callback.** `<input value={query} oninput={(e) => (query = e.currentTarget.value)} />` is equivalent to a binding but explicit; useful in a wrapper that wants to intercept.

A hybrid that works well for editing a record: bind inputs to a *draft* (a `$state` copy, or a declaration-tag `{let draft = $state(...)}` from Chapter 6), and commit on submit.

```html
<script lang="ts">
  type User = { name: string; email: string };
  let { user, onsave }: { user: User; onsave: (u: User) => void } = $props();
</script>

{let draft = $state({ ...user })}

<form onsubmit={(e) => { e.preventDefault(); onsave($state.snapshot(draft)); }}>
  <input bind:value={draft.name} />
  <input type="email" bind:value={draft.email} />
  <button>Save</button>
  <button type="button" onclick={() => (draft = { ...user })}>Discard</button>
</form>
```

`$state.snapshot` gives a plain object so you do not leak a proxy to the caller (Chapter 3).

### Debounced and formatted input

A function binding’s setter is a natural place for debouncing the *side effect* while keeping the field responsive:

```html
<script lang="ts">
  let { onsearch }: { onsearch: (q: string) => void } = $props();
  let text = $state('');
  let timer: ReturnType<typeof setTimeout> | undefined;

  function set(v: string) {
    text = v;                       // the field updates immediately
    clearTimeout(timer);
    timer = setTimeout(() => onsearch(v), 250);
  }
  $effect(() => () => clearTimeout(timer)); // cleanup on destroy
</script>

<input type="search" bind:value={() => text, set} />
```

For formatting that should not fight the user’s typing (currency, phone numbers), apply the formatted display on `blur` and keep the model clean:

```html
<script lang="ts">
  let cents = $state(1999);
  let draft = $state<string | null>(null); // non-null only while editing
  const shown = $derived(draft ?? (cents / 100).toFixed(2));
</script>

<input
  inputmode="decimal"
  bind:value={() => shown, (t) => { draft = t; const n = parseFloat(t); if (Number.isFinite(n)) cents = Math.round(n * 100); }}
  onblur={() => (draft = null)}
/>
```

### Avoiding bind-induced effects

Bindings plus effects are the classic recipe for loops. Two examples to refuse in code review:

```html
<!-- Bad: derived state written from an effect -->
<script lang="ts">
  let celsius = $state(0);
  let fahrenheit = $state(32);
  $effect(() => { fahrenheit = celsius * 1.8 + 32; });
  $effect(() => { celsius = (fahrenheit - 32) / 1.8; }); // ping-pong
</script>
<input type="number" bind:value={celsius} />
<input type="number" bind:value={fahrenheit} />
```

```html
<!-- Good: one source of truth, two function bindings -->
<script lang="ts">
  let celsius = $state(0);
</script>
<input type="number" bind:value={celsius} />
<input
  type="number"
  bind:value={() => celsius * 1.8 + 32, (f) => (celsius = (f - 32) / 1.8)}
/>
```

The bad version runs until float rounding stops it, or hits `effect_update_depth_exceeded`. The good version has one piece of state and the two views are pure functions of it. Pair this with `bind:group`/`bind:checked` for derived “select all” states: derive the indeterminate flag and the all-selected flag, and let a single handler write the underlying array.

### Many inputs, one handler

Because `bind:value` accepts member expressions, forms over a record need no per-field code: `bind:value={form[field.name]}` inside `{#each fields as field}` works when `form` is a `$state` object, and `bind:group={form.tags}` works with arrays. For validation, derive errors from the record (`const errors = $derived(validate(form))`) rather than writing them in handlers.

## Key takeaways

- A binding is a listener (DOM to state) plus a render effect (state to DOM), with a post-tick rewrite so setters can normalise input; ordering: bindings update before `oninput` attributes in practice.
- Number and range inputs yield numbers; an empty field gives `null` in 5.57.2 (the docs say `undefined`). Type your state accordingly.
- `bind:group` works only within one component; radios give a scalar, checkboxes an array. Select bindings hold arbitrary JavaScript values by identity; `multiple` gives an array.
- `bind:files` takes `null`, `undefined` or a `FileList`; build new lists with `DataTransfer`, and do not initialise state with it (SSR).
- `defaultValue`, `defaultChecked` (5.6) and select `defaultValue` (5.57) control what a form reset restores. The binding wins on first render, the default wins after a reset; resets propagate through a document-level capturing listener, a microtask later.
- Dimension bindings are read-only, ResizeObserver-based, need non-inline elements, and report after mount.
- `bind:this` is `undefined` before mount and `null` after destroy; use a function binding with a getter when you need correct nulling.
- Function bindings replace most write-state-from-an-effect patterns: validation, format conversion, unit conversion, and `null`-getter observation of read-only bindings.
- Component bindings need `$bindable`; chains of bindings need every intermediary to declare them, or you get `ownership_invalid_binding`.
- In runes mode, bind to a property of an each item (or `array[i]`), never to the each variable itself.

## Review Questions

1.  Describe the two compiled pieces that make up `bind:value` on an `<input>`, and say what the `await tick()` after the input handler is for.

2.  A user clears a `type="number"` input bound to `qty`. What value does `qty` get in Svelte 5.57.2, and how does this differ from the prose docs?

3.  What does this show after the user types `Ab`? Why?

    ```html
    <script lang="ts">let t = $state('');</script>
    <input bind:value={() => t, (v) => (t = v.toLowerCase())} />
    <p>{t}</p>
    ```

4.  In which order do `bind:value` and `oninput={...}` update when both are on the same element? What do the two relevant doc statements each cover?

5.  (Multiple choice) Which of these throws `bind_invalid_checkbox_value` in dev mode?

    a.  `<input type="checkbox" bind:checked={on} />`
    b.  `<input type="checkbox" bind:value={on} />`
    c.  `<input type="checkbox" bind:group={list} value="a" />`
    d.  `<input type="radio" bind:group={choice} value="a" />`

6.  Why can’t two components share one `bind:group` for radio inputs? How would you design a radio group split across components?

7.  Write the code to remove the second file from a `bind:files` selection. Why must you use `DataTransfer`?

8.  Why is `let files = $state(new DataTransfer().files)` a bad idea in a server-rendered app?

9.  A `<select bind:value={choice}>` has options whose values are objects. After the user picks one, what is `choice`’s identity relationship to the object you put in the option?

10. For `<select multiple bind:value={picked}>`, what happens when `picked` is `undefined`? When it is a string?

11. Predict: a `$state('typed')` input with `defaultValue="x"` inside a form. (a) What is shown initially? (b) After the user edits to `abc` and presses reset, what are the field and the state, and when does the state update?

12. Why does Svelte install the reset listener on `document` in the capture phase, and why does it wait a microtask? What cancels the resync?

13. A control is outside the `<form>` but uses the `form="f"` attribute. Is it resynced on reset? What about a control with no association?

14. Which bindings on `<audio>`/`<video>` are two-way and which are read-only? Why initialise `duration` to `0`?

15. Why does `<div contenteditable bind:textContent={t}>count is {count}</div>` not update when `count` changes? Is `bind:innerHTML` safe for user-visible content?

16. Why can’t you bind `clientWidth` on a `<span>` by default, and what are two ways to fix it? Which bindings in this family work in Safari?

17. Find the bug: `let el; $effect(() => { el.focus(); });` with `<input bind:this={el} />` in a component that renders it inside `{#if show}` (initially false).

18. What value does a `bind:this` variable hold (a) before mount, (b) while mounted, (c) after destroy? Why does a function binding on `bind:this` need a getter?

19. Convert this effect-based code to a function binding, and explain why the effect version is worse: `svelte <script lang="ts"> let name = $state(''); $effect(() => { name = name.trim().slice(0, 20); }); </script> <input bind:value={name} />`

20. What does `bind:clientWidth={null, redraw}` mean? When would you use a `null` getter?

21. Explain the output of the `ownership_invalid_binding` warning in the three-component example and give two fixes.

22. Why does `{#each items as item}<input bind:value={item} />{/each}` fail to compile in runes mode, and what are two correct alternatives?

23. What are the writable bindings of `<svelte:window>`, and why does assigning `scrollY` initially not scroll the page? How would you scroll at mount?

24. Compare controlled, uncontrolled and “draft” form strategies. When would you choose each?

25. Why does the temperature-conversion example with two `$effect`s ping-pong, and how does the function-binding version avoid it?

26. A currency field uses a function binding whose getter returns `fmt(cents)`. Users complain that typing `1.5` jumps to `1.50` mid-edit. Why does it happen and how would you fix it?

27. A `Keypad` has `value = $bindable('0')`. The parent renders `<Keypad bind:value={pin} />` with `let pin = $state()`. What happens, and what are two fixes?

28. Which compile errors/warnings would you expect for: (a) `bind:value={x + 1}`, (b) `bind:value` on a `<div>`, (c) binding to an imported variable, (d) `bind:value={() => v}`?
