# Chapter 17: Accessibility and the A11y Warnings

Most frameworks leave accessibility to linters and good intentions. Svelte puts a substantial part of it into the compiler: roughly forty `a11y_*` warnings are raised while your template is being compiled, with the offending line, the rule and a link to its documentation. That is a real advantage, and also a trap, because a compiler can only see markup. It cannot know whether your focus order makes sense, whether a live region announces the right thing, or whether the dialog you built traps and restores focus. This chapter covers both halves: how to read, group and responsibly silence the compiler’s checks, and what you still have to design and test yourself, including focus management, motion preferences, live regions, error and loading states, and accessible widgets (dialogs, tabs, comboboxes) built with snippets, context and `$props.id()`.

All compiler outputs below were produced by running `compile()` from Svelte 5.57.2 on the shown snippets.

## How the compile-time checks work

The compiler analyses each element in the template: its tag name, its static attributes, the roles it has (explicit via `role` or implicit from the element), which event attributes it carries, and its ARIA attributes. It then checks these against tables derived from the WAI-ARIA specification. Three properties shape how you work with the results:

1.  **They are warnings, not errors.** The component still compiles. They appear in the Vite console, in the editor via the language server, and in `svelte-check` / `npx sv check` output, where they can fail CI.
2.  **They are static.** An attribute whose value is a dynamic expression often cannot be evaluated; the checks that need a literal skip it. In our runs, `aria-hidden={open}` produced no warning, while `aria-expanded="yes"` produced `a11y_incorrect_aria_attribute_type_boolean`. Spread attributes (`{...props}`) silence the attribute-presence checks entirely, since the compiler cannot know what the spread contains (a 5.x fix “silence a11y attribute warnings when spread attributes present”).
3.  **They stop at component boundaries.** `<Button onclick={...}>` is a component; the compiler does not know that it renders a `<div>`. A11y checks apply to the elements written in *this* file. Component authors therefore carry the burden for the elements they render, and consumers get no help (more on this at the end of the chapter).

### The families of warnings

The complete list is in the compiler warnings reference. Grouping them by what they protect makes them easier to remember:

**ARIA validity** (the attribute or role does not exist or has the wrong value type):

- `a11y_unknown_aria_attribute` (with a “did you mean” suggestion), `a11y_unknown_role`, `a11y_no_abstract_role`
- `a11y_incorrect_aria_attribute_type` and its variants `_boolean`, `_id`, `_idlist`, `_integer`, `_token`, `_tokenlist`, `_tristate`
- `a11y_aria_attributes` and `a11y_misplaced_role` (ARIA on elements such as `meta`, `script`, `style` that are never exposed)
- `a11y_autocomplete_valid`

**Roles and their requirements**:

- `a11y_role_has_required_aria_props` (a `checkbox` needs `aria-checked`; a `combobox` needs `aria-controls` and `aria-expanded`; an `option` needs `aria-selected`)
- `a11y_role_supports_aria_props` and `a11y_role_supports_aria_props_implicit` (an attribute that the role, explicit or implicit, does not support)
- `a11y_no_redundant_roles` (`<button role="button">`)
- `a11y_no_interactive_element_to_noninteractive_role` and `a11y_no_noninteractive_element_to_interactive_role` (do not turn a `<textarea>` into a `listitem` or an `<h3>` into a `searchbox`)

**Interactive semantics**:

- `a11y_click_events_have_key_events`, `a11y_no_static_element_interactions`, `a11y_no_noninteractive_element_interactions`, `a11y_interactive_supports_focus`, `a11y_mouse_events_have_key_events`

**Labels, names and content**:

- `a11y_label_has_associated_control`, `a11y_consider_explicit_label` (buttons and links need text or `aria-label`/`aria-labelledby`/`title`), `a11y_missing_content` (empty headings and anchors), `a11y_missing_attribute` (`<a href>`, `<img alt>`, `<html lang>`, `<iframe title>`, `<area>`, `<object>`, `<input type="image">`)
- `a11y_img_redundant_alt` (the words “image”, “picture”, “photo” in `alt`), `a11y_media_has_caption`, `a11y_invalid_attribute` (`href=""`, `#`, `javascript:`)

**Keyboard and focus**:

- `a11y_positive_tabindex`, `a11y_no_noninteractive_tabindex`, `a11y_aria_activedescendant_has_tabindex`, `a11y_autofocus`, `a11y_accesskey`

**Document structure and distractions**:

- `a11y_figcaption_parent`, `a11y_figcaption_index`, `a11y_misplaced_scope`, `a11y_hidden` (do not hide headings), `a11y_distracting_elements` (`<marquee>`, `<blink>`)

### What the warnings look like in practice

Rather than paraphrase, here are real results. Each line shows the code and the compiler’s message (shortened):

| Markup | Warnings |
|------------------------------------|------------------------------------|
| `<div onclick={...}>x</div>` | `a11y_click_events_have_key_events`, `a11y_no_static_element_interactions` |
| `<div onclick={...} onkeydown={...}>x</div>` | `a11y_no_static_element_interactions` (“with a click or keydown handler must have an ARIA role”) |
| `<div role="button" onclick onkeydown>` | `a11y_interactive_supports_focus` (“must have a tabindex value”) |
| `<div role="button" tabindex="0" onclick onkeydown>` | none |
| `<li onclick={...}>` | `a11y_click_events_have_key_events`, `a11y_no_noninteractive_element_interactions` |
| `<label>Name</label><input id="a">` | `a11y_label_has_associated_control` |
| `<label for="a">Name</label><input id="a">` | none |
| `<img src="a.png">` | `a11y_missing_attribute` (`alt`) |
| `<img src="a.png" alt="Photo of dog">` | `a11y_img_redundant_alt` |
| `<button></button>` | `a11y_consider_explicit_label` |
| `<a href="#">x</a>` | `a11y_invalid_attribute` |
| `<div tabindex="1">` | `a11y_positive_tabindex`, `a11y_no_noninteractive_tabindex` |
| `<div tabindex="0">x</div>` | `a11y_no_noninteractive_tabindex` |
| `<span role="checkbox" tabindex="0">` | `a11y_role_has_required_aria_props` (needs `aria-checked`) |
| `<input role="combobox" aria-expanded="false">` | `a11y_role_has_required_aria_props` (`aria-controls` and `aria-expanded`) |
| `<div role="presentation" onclick={...}>` | none |
| `<label>Name <input></label>` | none |

Notice the progression in the first four rows. The compiler walks you from “a click handler on a `div`” toward “this should be a `<button>`”. Each fix you apply (add a key handler, then a role, then a tabindex) satisfies one warning and exposes the next, which is the rule engine telling you that you are rebuilding a button by hand.

## Semantic HTML first

The warnings are a safety net. The strategy is to avoid needing them: use native elements, which come with focusability, keyboard activation, roles and states for free.

```html
<!-- Warns twice, and is still not accessible -->
<div class="btn" onclick={save}>Save</div>

<!-- A "fixed" version that silences the warnings and reimplements <button> badly -->
<div
  class="btn"
  role="button"
  tabindex="0"
  onclick={save}
  onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && save()}
>
  Save
</div>

<!-- The right fix -->
<button type="button" class="btn" onclick={save}>Save</button>
```

The second version is worse than it looks. It misses the `Space` key’s default scroll prevention, does not support `disabled`, does not participate in forms, and screen reader virtual cursors treat it differently. Prefer, in order: native interactive elements (`button`, `a href`, `input`, `select`, `details`, `dialog`); then native elements with landmark and structure semantics (`nav`, `main`, `ul`, `table`); then ARIA only to fill genuine gaps (tabs, comboboxes, live regions).

A few mappings to keep in mind:

| You want | Use | Instead of |
|------------------------|------------------------|------------------------|
| An action | `<button type="button">` | `div` + `onclick` |
| Navigation | `<a href="/path">` | `span` + `onclick` + router call |
| A toggle | `<button aria-pressed={on}>` or `<input type="checkbox">` | `div` + `class:active` |
| A disclosure | `<details><summary>` | `div` + `bind:` state |
| A modal | `<dialog>` + `showModal()` | `div` with `position: fixed` and manual focus trap |
| A group of options | `<fieldset><legend>` + radios | divs with `role="radio"` |

### Legitimate non-native handlers

Sometimes a handler on a non-interactive element is correct, for example a click handler on a wrapper that dismisses a popup (a pointer convenience, with the keyboard path handled elsewhere) or a delegated listener around a list. Then:

```html
<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions (backdrop click is a pointer convenience; Escape closes the dialog via the keydown handler on the window) -->
<div class="backdrop" onclick={close}></div>
<svelte:window onkeydown={(e) => e.key === 'Escape' && close()} />
```

The syntax is documented: a `svelte-ignore` comment disables the warnings named in it for the *next block of markup*. List multiple codes separated by commas, and add an explanation in parentheses. That explanation is the important part: it records the review decision in the code. Also, `role="presentation"` on an element with a mouse handler is an accepted way of declaring “this is not interactive semantics” (no warning in our run), but use it only when that is true.

In `<script>`, a `// svelte-ignore code` comment on the preceding line silences warnings such as `state_referenced_locally` for the next statement.

## Filtering globally with `warningFilter`

The `warningFilter` compile option takes a function `(warning) => boolean`; returning `true` keeps the warning. It is useful for two opposite things: silencing a code across a legacy area while it is being cleaned up, and the reverse, elevating selected codes in your own build tooling.

```js
// svelte.config.js
export default {
  compilerOptions: {
    warningFilter: (warning) => {
      // Not reviewed yet in the legacy admin area
      if (warning.filename?.includes('/legacy-admin/') && warning.code.startsWith('a11y_')) {
        return false;
      }
      return true;
    }
  }
};
```

`@sveltejs/vite-plugin-svelte` additionally exposes an `onwarn(warning, defaultHandler)` option, which is the place to throw on selected warnings so that they fail the build:

```ts
// vite.config.ts
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [
    svelte({
      onwarn(warning, defaultHandler) {
        // Treat these as build failures in CI
        if (process.env.CI && /^(a11y_missing_attribute|a11y_label_has_associated_control)$/.test(warning.code)) {
          throw new Error(`${warning.filename}: ${warning.message}`);
        }
        defaultHandler(warning);
      }
    })
  ]
});
```

A governance rule that works in practice: no global filters for `a11y_*` in new code; `svelte-ignore` only with a parenthesised reason; and code review treats an ignore comment as a claim that needs justification.

## Labels and IDs: `$props.id()`

Form controls need accessible names. The three standard ways are a wrapping `<label>`, `<label for>` plus matching `id`, and `aria-labelledby`/`aria-label`. The wrapping label needs no IDs at all (`<label>Name <input></label>` warns about nothing). `for`/`id` and ARIA references need IDs that are unique per component instance, and that is a problem for reusable components: a hard-coded `id="name"` breaks as soon as two instances exist on a page.

Hand-rolled counters (``let n = 0; const id = `field-${n++}` ``) break server rendering: the server and the client number components in different orders, causing a mismatch between server HTML and client output. Svelte’s answer is `$props.id()` (since 5.20): “generates an ID that is unique to the current component instance. When hydrating a server-rendered component, the value will be consistent between server and client.”

```html
<!-- TextField.svelte -->
<script lang="ts">
  let {
    label,
    value = $bindable(''),
    hint,
    error
  }: { label: string; value?: string; hint?: string; error?: string } = $props();

  const uid = $props.id();
</script>

<div class="field">
  <label for="{uid}-input">{label}</label>
  <input
    id="{uid}-input"
    bind:value
    aria-describedby={[hint && `${uid}-hint`, error && `${uid}-error`].filter(Boolean).join(' ') || undefined}
    aria-invalid={error ? 'true' : undefined}
  />
  {#if hint}<p id="{uid}-hint" class="hint">{hint}</p>{/if}
  {#if error}<p id="{uid}-error" class="error" role="alert">{error}</p>{/if}
</div>
```

Things to note:

- `$props.id()` is only valid at the top level of the instance script as a variable declaration initializer (otherwise the compiler reports `props_id_invalid_placement`). One call per component; derive more IDs with suffixes.
- The `for="{uid}-input"` attribute is a concatenation, which in runes mode must be quoted. The compiler’s label check (`a11y_label_has_associated_control`) accepted `for="{id}-n"` against an `id="{id}-n"` in our run: it validates that a `for` exists and is associated, not that the target matches (it cannot know).
- The error message uses `role="alert"`, which announces immediately. Use it for errors that appear after user action, not for static hints.
- `aria-invalid="true"`/`undefined`: a boolean `false` would render `aria-invalid="false"`, which is valid but noisy. Svelte omits attributes whose value is `undefined` or `null`.

For custom elements and ARIA relationships across shadow boundaries, ID references do not cross shadow roots, a point we return to in Chapter 19.

## Focus management

Focus is state that lives in the browser. Svelte gives you four tools to work with it.

### Moving focus: `bind:this` and `tick`

After a state change, the DOM has not yet been updated, so focusing an element that was just rendered requires waiting. `tick()` resolves once pending state changes have been applied:

```html
<script lang="ts">
  import { tick } from 'svelte';

  let editing = $state(false);
  let input: HTMLInputElement | undefined = $state();
  let button: HTMLButtonElement | undefined = $state();
  let title = $state('Untitled');

  async function startEditing() {
    editing = true;
    await tick();
    input?.select();
  }

  async function finish() {
    editing = false;
    await tick();
    button?.focus();   // return focus to where the user was
  }
</script>

{#if editing}
  <input
    bind:this={input}
    bind:value={title}
    aria-label="Title"
    onkeydown={(e) => e.key === 'Enter' && finish()}
    onblur={finish}
  />
{:else}
  <button bind:this={button} type="button" onclick={startEditing}>{title} (edit)</button>
{/if}
```

The rule that makes this accessible is **focus must never be lost**. When the focused element is removed (the button above disappears when editing starts; the input disappears when editing ends), focus falls back to `<body>`, and keyboard and screen reader users lose their place. Always move focus explicitly to a logical successor.

An alternative to `tick`: an attachment (Chapter 9), which runs when the element is mounted:

```html
<script lang="ts">
  import type { Attachment } from 'svelte/attachments';
  const focus: Attachment<HTMLElement> = (el) => { el.focus(); };
</script>

{#if editing}
  <input {@attach focus} aria-label="Title" />
{/if}
```

We verified that a similar attachment focuses an `<input>` after `flushSync()` in a jsdom test. This is usually cleaner than `bind:this` + `tick` for “focus when it appears”.

### `autofocus` and its warning

`autofocus` triggers `a11y_autofocus` (“Avoid using autofocus”) because moving focus on page load disorients screen reader users and skips content. The compiler does not warn inside a `<dialog>` (a 5.x fix: “silence autofocus a11y warning inside `<dialog>`”; we confirmed `<dialog><input autofocus></dialog>` compiles clean), because focusing the first control in a modal is expected. Elsewhere, treat the warning as a prompt to ask whether focus should move at all.

### Observing focus: `<svelte:document bind:activeElement>`

`<svelte:document>` supports a read-only binding to `activeElement` (also `fullscreenElement`, `pointerLockElement`, `visibilityState`). It must appear at the top level of the component.

```html
<script lang="ts">
  let active: Element | null = $state(null);
  const inToolbar = $derived(active?.closest('[role="toolbar"]') !== null && active !== null);
</script>

<svelte:document bind:activeElement={active} />

<p aria-live="off">Focus is {inToolbar ? 'in' : 'outside'} the toolbar</p>
```

Use it for focus-dependent UI such as showing a floating toolbar while focus is inside an editor. For routine cases prefer `:focus-within` in CSS.

### Trapping and restoring focus: use `<dialog>`

A modal must trap focus, make the rest of the page inert and restore focus on close. The native `<dialog>` element does all three when opened with `showModal()`. Here is a Svelte wrapper that keeps a `bind:open` interface:

```html
<!-- Dialog.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    open = $bindable(false),
    title,
    children
  }: { open?: boolean; title: string; children: Snippet } = $props();

  const uid = $props.id();
  let dialog: HTMLDialogElement | undefined = $state();

  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  });
</script>

<dialog bind:this={dialog} aria-labelledby="{uid}-title" onclose={() => (open = false)}>
  <h2 id="{uid}-title">{title}</h2>
  {@render children()}
  <form method="dialog">
    <button>Close</button>
  </form>
</dialog>
```

This compiles without any a11y warnings. The effect synchronises the `open` state with the element’s imperative API (a legitimate use of `$effect`: it bridges to a browser API). The `close` event covers every way of closing: the Close button, `Escape`, and `dialog.close()` from elsewhere; it feeds back into `open`. On close, the browser returns focus to the element that was focused before `showModal()`. The `aria-labelledby` points at an ID made with `$props.id()`.

jsdom does not implement `showModal()`, so test dialogs in a real browser (Playwright or Vitest browser mode).

A non-modal popup (a menu or popover) also needs focus rules: move focus in on open, return it on close, close on `Escape` and on focus leaving. For popovers, the native `popover` attribute plus `popovertarget` provide light dismiss and top-layer rendering without scripts.

### `inert` and outroing elements

Svelte sets the `inert` attribute on elements while they are playing an outro transition. This is a v4 change that carries over: from the v4 migration guide, “the `inert` attribute is now applied to outroing elements to make them invisible to assistive technology and prevent interaction”. You get it for free: a fading-out dialog cannot be tabbed into or read while it disappears. You can also use `inert` yourself to disable regions (for instance, the page behind a custom non-`<dialog>` overlay): `<main inert={modalOpen}>`. `inert` is treated as a boolean attribute by Svelte.

## Motion and reduced-motion preferences

Users with vestibular disorders set `prefers-reduced-motion: reduce`. Svelte has a trap here, spelled out in the transition docs: “Transitions are driven by the Web Animations API rather than by CSS. A global `@media (prefers-reduced-motion: reduce)` rule that zeroes `transition-duration` and `animation-duration` therefore has no effect on them.” Your global CSS reset does not stop `transition:fly`.

`prefersReducedMotion` from `svelte/motion` is a `MediaQuery` (a reactive object with `.current`, added in 5.7). Use it to shorten or disable transitions:

```html
<script lang="ts">
  import { fly, fade } from 'svelte/transition';
  import { prefersReducedMotion } from 'svelte/motion';

  let open = $state(false);
</script>

<button onclick={() => (open = !open)} aria-expanded={open} aria-controls="panel">Details</button>

{#if open}
  <div
    id="panel"
    transition:fly={{ y: prefersReducedMotion.current ? 0 : 200, duration: prefersReducedMotion.current ? 0 : 300 }}
  >
    Panel content
  </div>
{/if}
```

A reusable wrapper avoids repeating this:

```ts
// src/lib/motion.ts
import { fade, fly, type FlyParams } from 'svelte/transition';
import { prefersReducedMotion } from 'svelte/motion';

export function accessibleFly(node: Element, params: FlyParams = {}) {
  return prefersReducedMotion.current
    ? fade(node, { duration: 0 })
    : fly(node, params);
}
```

`<div transition:accessibleFly={{ y: 200 }}>` then works everywhere. `prefersReducedMotion.current` is evaluated when the transition starts, which is what you want. The same applies to `Spring`/`Tween` (set `duration: 0` or `instant: true` when the preference is on) and to CSS animations, which can use the media query as usual.

Reduced motion does not mean no motion: opacity fades are generally acceptable; large translations, parallax and zooms are the problem.

## Announcing changes: live regions

Visual changes that happen away from the focus (a toast, a validation summary, a search result count) are invisible to screen reader users unless announced. ARIA live regions do that. The pattern with Svelte is simple because state changes become DOM text changes:

```html
<script lang="ts">
  let results = $state<string[]>([]);
  let query = $state('');
  const status = $derived(query ? `${results.length} results for "${query}"` : '');
</script>

<input type="search" aria-label="Search" bind:value={query} />

<!-- The region must exist before its content changes -->
<p role="status" class="visually-hidden">{status}</p>
```

Rules that matter:

- **The live region element must be in the DOM before the text changes.** Putting `role="status"` inside an `{#if}` that renders it together with the message often means the message is not announced. Keep the container always rendered and change its contents.
- `role="status"` (polite, `aria-live="polite"`) is the default choice; `role="alert"` (assertive) interrupts, so reserve it for errors and urgent messages.
- Debounce frequent updates (a result count updating on every keystroke) or derive the text from settled state.
- You can verify structure in tests with `screen.getByRole('status')` and assert its text.

A helper component for app-wide announcements via `createContext` gives every part of the app a `say()` function:

```ts
// src/lib/announce.svelte.ts
import { createContext } from 'svelte';

export class Announcer {
  message = $state('');
  say(text: string) {
    // Clear first so repeating the same message is announced again
    this.message = '';
    queueMicrotask(() => (this.message = text));
  }
}
export const [getAnnouncer, setAnnouncer] = createContext<Announcer>();
```

```html
<!-- AnnouncerRoot.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import { Announcer, setAnnouncer } from './announce.svelte';

  let { children }: { children: Snippet } = $props();
  const announcer = new Announcer();
  setAnnouncer(announcer);
</script>

{@render children()}
<div role="status" aria-live="polite" class="visually-hidden">{announcer.message}</div>
```

Any descendant calls `getAnnouncer().say('Saved')`.

### Errors and boundaries

`<svelte:boundary>` catches errors thrown while rendering its content and shows the `failed` snippet. That snippet is UI like any other and has accessibility responsibilities: tell the user, with an alert role, and give a way forward.

```html
<svelte:boundary onerror={(e) => reportError(e)}>
  <Chart {data} />

  {#snippet failed(error, reset)}
    <div role="alert">
      <p>The chart could not be displayed.</p>
      <button type="button" onclick={reset}>Try again</button>
    </div>
  {/snippet}
</svelte:boundary>
```

Because the failed content replaces the original, focus that was inside the boundary is lost; if `reset` re-renders the contents, move focus to a sensible place. Also remember what boundaries do not catch: “Errors occurring outside the rendering process (for example, in event handlers or after a `setTimeout` or async work) are not caught”, so failed async work in handlers needs its own announcement (an alert region fed by state).

### Loading states

For asynchronous UI (Chapter 13), make the pending state perceivable. `<svelte:boundary>` accepts a `pending` snippet, and `$effect.pending()` returns the count of pending promises in the current boundary. A polite status region or `aria-busy` on the region being updated communicates it:

```html
<svelte:boundary>
  <section aria-labelledby="results-h" aria-busy={false}>
    <h2 id="results-h">Results</h2>
    <ul>{#each await loadResults(query) as r}<li>{r.title}</li>{/each}</ul>
  </section>

  {#snippet pending()}
    <p role="status">Loading results…</p>
  {/snippet}
</svelte:boundary>
```

(This example uses `await` in the template, which is experimental and requires `compilerOptions.experimental.async: true`; see Chapter 13.) Do not spin forever silently: a `role="status"` message gives non-visual users the same information a spinner gives sighted users. For navigation-like updates where the old UI stays visible while new data loads, `$state.eager(pathname)` is documented as the way to give immediate feedback such as `aria-current={$state.eager(pathname) === '/' ? 'page' : null}` while the rest of the UI is still suspended (use it sparingly).

## Accessible components: patterns with snippets and context

The ARIA Authoring Practices describe keyboard and role contracts for widgets. Svelte’s component model maps well onto them: snippets provide the content slots, `createContext` shares state between the parts of a composite widget, `$props.id()` produces the relationships, and class-based state objects keep the logic testable.

### Tabs

A tab list has a roving tabindex: only the selected tab is in the tab order, arrow keys move between tabs. The parts share a `selected` value and an ID prefix through context.

```ts
// tabs-context.svelte.ts
import { createContext } from 'svelte';

export class TabsState {
  selected = $state('');
  id: string;
  constructor(id: string, initial: string) {
    this.id = id;
    this.selected = initial;
  }
}

export const [getTabs, setTabs] = createContext<TabsState>();
```

```html
<!-- Tabs.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import { TabsState, setTabs } from './tabs-context.svelte';

  let { initial, label, list, panels }: { initial: string; label: string; list: Snippet; panels: Snippet } = $props();

  const uid = $props.id();
  // svelte-ignore state_referenced_locally (initial value is intentionally captured once)
  setTabs(new TabsState(uid, initial));
</script>

<div role="tablist" aria-label={label}>
  {@render list()}
</div>
{@render panels()}
```

```html
<!-- Tab.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import { getTabs } from './tabs-context.svelte';

  let { name, children }: { name: string; children: Snippet } = $props();

  const tabs = getTabs();
  const selected = $derived(tabs.selected === name);

  function onkeydown(e: KeyboardEvent) {
    const current = e.currentTarget as HTMLElement;
    const all = [...current.parentElement!.querySelectorAll<HTMLElement>('[role="tab"]')];
    const i = all.indexOf(current);
    let next = -1;
    if (e.key === 'ArrowRight') next = (i + 1) % all.length;
    else if (e.key === 'ArrowLeft') next = (i - 1 + all.length) % all.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = all.length - 1;
    if (next >= 0) {
      e.preventDefault();
      all[next].focus();
      all[next].click();   // automatic activation: selecting follows focus
    }
  }
</script>

<button
  role="tab"
  id="{tabs.id}-tab-{name}"
  aria-selected={selected}
  aria-controls="{tabs.id}-panel-{name}"
  tabindex={selected ? 0 : -1}
  onclick={() => (tabs.selected = name)}
  {onkeydown}
>
  {@render children()}
</button>
```

```html
<!-- TabPanel.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import { getTabs } from './tabs-context.svelte';

  let { name, children }: { name: string; children: Snippet } = $props();
  const tabs = getTabs();
</script>

<div
  role="tabpanel"
  id="{tabs.id}-panel-{name}"
  aria-labelledby="{tabs.id}-tab-{name}"
  tabindex="0"
  hidden={tabs.selected !== name}
>
  {@render children()}
</div>
```

Usage:

```html
<Tabs initial="profile" label="Settings">
  {#snippet list()}
    <Tab name="profile">Profile</Tab>
    <Tab name="security">Security</Tab>
  {/snippet}
  {#snippet panels()}
    <TabPanel name="profile">Profile content</TabPanel>
    <TabPanel name="security">Security content</TabPanel>
  {/snippet}
</Tabs>
```

All four files compile without a11y warnings (the one `state_referenced_locally` is ignored with a reason). We tested the behaviour with Testing Library: the first tab starts with `aria-selected="true"`, the second has `tabindex="-1"`, pressing `ArrowRight` moves focus to the second tab and selects it, and `getByRole('tabpanel', { name: 'Security' })` finds the panel through its `aria-labelledby`. That last assertion is the payoff: if the role-based query works, a screen reader’s accessible name computation works too.

Design notes: the roving-tabindex logic queries sibling tabs from the DOM, which is simple and works with any content order; a registry in the context would be the alternative if tabs could be disabled or reordered. `hidden` on inactive panels removes them from the accessibility tree; an `{#if}` would also unmount their state, which may or may not be wanted.

### Combobox

A combobox keeps DOM focus on the input and signals the “active” option with `aria-activedescendant`.

```html
<!-- Combobox.svelte -->
<script lang="ts">
  let { options, label, value = $bindable('') }: { options: string[]; label: string; value?: string } = $props();

  const uid = $props.id();
  let query = $state('');
  let open = $state(false);
  let active = $state(0);

  const filtered = $derived(options.filter((o) => o.toLowerCase().includes(query.toLowerCase())));

  function choose(option: string) {
    value = option;
    query = option;
    open = false;
  }

  function onkeydown(e: KeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      open = true;
      active = Math.min(active + 1, filtered.length - 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      active = Math.max(active - 1, 0);
    } else if (e.key === 'Enter' && open && filtered[active]) {
      e.preventDefault();
      choose(filtered[active]);
    } else if (e.key === 'Escape') {
      open = false;
    }
  }
</script>

<label for="{uid}-input">{label}</label>
<input
  id="{uid}-input"
  role="combobox"
  aria-expanded={open}
  aria-controls="{uid}-list"
  aria-autocomplete="list"
  aria-activedescendant={open && filtered[active] ? `${uid}-opt-${active}` : undefined}
  bind:value={query}
  oninput={() => { open = true; active = 0; }}
  {onkeydown}
/>

<ul id="{uid}-list" role="listbox" aria-label={label} hidden={!open}>
  {#each filtered as option, i (option)}
    <!-- svelte-ignore a11y_click_events_have_key_events (keyboard is handled by the input through aria-activedescendant) -->
    <li
      id="{uid}-opt-{i}"
      role="option"
      aria-selected={i === active}
      onclick={() => choose(option)}
      onpointerenter={() => (active = i)}
    >
      {option}
    </li>
  {/each}
</ul>

<p class="visually-hidden" role="status">{open ? `${filtered.length} results available` : ''}</p>
```

Compiler perspective: `role="combobox"` forces `aria-controls` and `aria-expanded` (the `a11y_role_has_required_aria_props` we saw earlier is the rule that tells you), `role="option"` forces `aria-selected`. The `svelte-ignore` is legitimate because the option is not a tab stop; keyboard users operate it through the input. Testing result: typing `ap` produced two options; `ArrowDown` then `Enter` selected the second (“Apricot”) and set `aria-expanded` back to `false`.

Where this pattern is incomplete (to be honest about the limits of a book example): focus-visible styling for the active option, scrolling the active option into view, `Home`/`End`, and a mobile-friendly touch story are all missing. For production, wrap a well-tested headless library or write the above carefully and test it with real assistive technology.

### Menus

Menu buttons (`aria-haspopup`, `aria-expanded`, `role="menu"` with `menuitem`s) follow the same recipe: a context object holding `open` and the ID prefix; a trigger that toggles and handles `ArrowDown`; items with roving focus; `Escape` closes and returns focus to the trigger; focus leaving the menu closes it. Two Svelte-specific notes. First, rendering the menu content with `{#if open}` means items are created on open, so focusing the first item needs an attachment or `tick()`. Second, use `{@attach}` for the “click outside” behaviour, using `on` from `svelte/events` so your listener order relative to Svelte’s delegated handlers is predictable:

```ts
// src/lib/click-outside.ts
import { on } from 'svelte/events';
import type { Attachment } from 'svelte/attachments';

export function clickOutside(callback: () => void): Attachment<HTMLElement> {
  return (node) => {
    const off = on(document, 'pointerdown', (e) => {
      if (!node.contains(e.target as Node)) callback();
    });
    return off;
  };
}
```

`<div role="menu" {@attach clickOutside(close)}>`: the attachment re-runs if `close` is a reactive dependency of the expression, and the returned cleanup removes the listener.

## Customizable `<select>` and form semantics

Since 5.47, Svelte supports the browser feature of customizable `<select>` elements: `<option>`s may contain richer markup, and the new `<selectedcontent>` element mirrors the selected option’s content inside a `<button>` child of the select. In our compile run `<select><option><b>x</b></option></select>` produced no warnings or errors. Svelte keeps `selectedcontent` reactive (several later patches in the changelog fix reactivity and mutation edge cases), and the runtime tests whether the browser supports customizable selects before relying on it.

```html
<script lang="ts">
  let flavour = $state('vanilla');
</script>

<label>
  Flavour
  <select bind:value={flavour}>
    <button><selectedcontent></selectedcontent></button>
    <option value="vanilla">Vanilla</option>
    <option value="mint">Mint</option>
  </select>
</label>
```

Treat this as progressive enhancement: the native `<select>` carries the accessibility semantics (role `combobox`/`listbox` depending on rendering, keyboard operation, form participation), which is why it beats a hand-built dropdown for most forms. Other form semantics Svelte helps with: `bind:group` for radio and checkbox sets (use `<fieldset>`/`<legend>` for the group name), `defaultValue`/`defaultChecked` for forms that can be reset (5.6), and since 5.57 `defaultValue` on `<select>`. Bindings react to `form.reset()` in Svelte 5, so “Reset” buttons behave as users expect. Group related inputs, associate error messages with `aria-describedby`, and mark required fields with `required` (not just an asterisk).

## Testing accessibility

Compiler warnings are the first layer. Add three more.

**1. Role-based queries in component tests.** `@testing-library/svelte` queries mirror what assistive technology exposes. `getByRole('button', { name: 'Save' })` only succeeds if there is an element with the button role *and* an accessible name. A test suite written with role queries gets a free accessibility smoke test. Use `getByTestId` as the last resort. (Chapter 16 sets up the tooling.)

```ts
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';

test('tabs are operable with the keyboard', async () => {
  const user = userEvent.setup();
  render(TabsDemo);
  const [first, second] = screen.getAllByRole('tab');

  first.focus();
  await user.keyboard('{ArrowRight}');

  expect(second).toHaveFocus();
  expect(second).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByRole('tabpanel', { name: 'Security' })).toBeVisible();
});
```

(`toHaveFocus` and friends come from `@testing-library/jest-dom`; the earlier plain-DOM assertions work without it.)

**2. axe in unit tests.** `axe-core` runs a rule engine over a DOM. In jsdom it can check structure (names, roles, ARIA validity, duplicated IDs) but not colour contrast or layout-dependent rules, which need a real browser.

```ts
import axe from 'axe-core';

test('TextField has no detectable violations', async () => {
  const { container } = render(TextField, { label: 'Email' });
  const results = await axe.run(container);
  expect(results.violations).toEqual([]);
});
```

**3. axe in Playwright.** Against the real page and real CSS:

```ts
// tests/a11y.spec.ts
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('home page has no automatically detectable accessibility issues', async ({ page }) => {
  await page.goto('/');
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});
```

Automated tools find a minority of real problems (a commonly quoted order of magnitude is a third of them). They cannot judge whether alt text is meaningful or whether the focus order is sensible. Schedule manual checks: keyboard-only passes, a screen reader pass (NVDA/VoiceOver) on critical flows, 200% zoom, forced-colors mode and reduced-motion.

## What the compiler cannot check

Make a list and put it in your review checklist:

- **Component boundaries.** `<Button onclick>` and `<Card>` are opaque. Whatever element they render is checked in their own file. But a prop like `role` passed through, or a `<Clickable>` component rendering a `div`, can silently create inaccessible UI.
- **Dynamic values.** `aria-expanded={x}` where `x` is `"yes"` at runtime is unchecked. TypeScript helps: `svelte/elements` types ARIA attributes (`AriaAttributes`) so a union like `'true' | 'false'` is enforced where you type your own props.
- **Spread attributes.** `{...rest}` suppresses attribute checks, and the spread might contain `onclick`.
- **Focus order and focus loss.** Whether DOM order matches visual order, whether removed elements drop focus to `<body>`, whether modals restore focus.
- **Names and descriptions that are present but wrong.** `alt="image"` is caught; `alt="img_2043"` is not. `aria-label="button"` is not.
- **Contrast, target size, zoom and reflow, text spacing.** CSS concerns; the compiler’s `css_unused_selector` has nothing to say about them.
- **Live region behaviour, timing, and announcements.**
- **Semantics of dynamic structure.** Heading levels that skip, landmarks missing, lists built from divs; only a few structure rules exist (`figcaption` placement, `scope` misuse).
- **Content from `{@html}`**, which is opaque markup (and a security concern as well; Chapter 6).
- **Third-party components and web components.**

## Key takeaways

- The Svelte compiler emits about forty `a11y_*` warnings that fall into groups: ARIA validity, roles and required properties, interactive semantics, labels and content, keyboard and focus, and document structure. They are static: dynamic values, spreads and component boundaries are not analysed.
- Prefer native elements. The warnings walk you from `div` + `onclick` towards `<button>`; follow them there rather than adding roles, tabindex and key handlers by hand.
- Silence with `<!-- svelte-ignore code (reason) -->` only with a reason; use `warningFilter` or the Vite plugin’s `onwarn` for policy, including failing CI on chosen warnings.
- Use `$props.id()` (5.20+) for `for`, `aria-labelledby`, `aria-describedby` and `aria-controls` IDs; it is unique per instance and stable between server and client.
- Focus must never be lost: after state changes that remove the focused element, move focus explicitly using `bind:this` and `await tick()`, or an attachment. Use `<dialog>` + `showModal()` for modals.
- Transitions run on the Web Animations API, so a global `prefers-reduced-motion` CSS rule does not affect them; use `prefersReducedMotion.current` from `svelte/motion`.
- Keep live-region containers in the DOM and change their text; use `role="status"` for polite messages and `role="alert"` for errors, including in `failed` boundary snippets and loading (`pending`) states.
- Widgets are built from snippets (content), `createContext` (shared state), `$props.id()` (relationships) and native keyboard handling; ARIA role requirements show up as compiler warnings.
- Test with role-based queries, run axe in unit tests and Playwright, and do manual keyboard and screen reader checks; the compiler catches only static markup mistakes.

## Review Questions

1.  List the six groups of `a11y_*` warnings used in this chapter and give one warning code from each.
2.  Why does `<div onclick={f}>` produce two warnings, and why does adding `onkeydown` not make them all disappear? What is the end state the rule engine is steering you towards?
3.  What does `a11y_interactive_supports_focus` check, and which attribute satisfies it?
4.  Multiple choice: which markup compiles without any a11y warning?
    a.  `<div role="button" onclick={f} onkeydown={g}></div>`
    b.  `<div role="button" tabindex="0" onclick={f} onkeydown={g}></div>`
    c.  `<li onclick={f}></li>`
    d.  `<img src="a.png" alt="Photo of a cat">`
5.  Why does `<button role="button">` warn, and which warning is it?
6.  Explain why a spread attribute (`<img {...props}>`) silences some a11y warnings. What does that mean for how you should type `props`?
7.  Write the comment that silences both `a11y_click_events_have_key_events` and `a11y_no_static_element_interactions` for a backdrop `<div>` with an explanation, and explain what the explanation is for.
8.  A teammate adds `warningFilter: (w) => !w.code.startsWith('a11y_')` to the project config to “get rid of noise”. Describe two better approaches.
9.  What is the contract of `warningFilter`: what does returning `true` mean?
10. Why are hand-rolled incrementing IDs (`let n = 0; const id = 'f' + n++`) a problem for SSR, and how does `$props.id()` solve it? Where is it allowed to be called?
11. Find the bug:

    ```html
    <script lang="ts">
      let { label } = $props();
      function make() {
        return $props.id();
      }
      const id = make();
    </script>
    <label for={id}>{label}</label><input {id} />
    ```

12. Why is `<label>Name <input></label>` accepted without any `id`?
13. The `{#if editing}<input />{:else}<button>…</button>{/if}` toggle loses keyboard users’ place. Explain why, and give two ways to fix it.
14. When does Svelte not warn about `autofocus`, and why is that exception reasonable?
15. What does `<svelte:document bind:activeElement={el} />` give you? Which constraints apply to its placement and to writing to the binding?
16. List what `<dialog>` + `showModal()` provides for free compared with a `div`-based modal. Why does the test for it need a real browser?
17. What does the `onclose` handler in the chapter’s `Dialog` component accomplish, and why is it better than handling only the Close button?
18. Explain the reduced-motion trap with Svelte transitions. Give a code fragment that makes a `fly` transition respect the user’s preference.
19. In `accessibleFly`, why is reading `prefersReducedMotion.current` inside the function (rather than once at module load) the right choice?
20. A toast component renders `{#if message}<div role="status">{message}</div>{/if}`. Why might screen readers not announce it, and how do you fix it?
21. When should you use `role="alert"` rather than `role="status"`? Give one example of each from a form.
22. What does a `failed` snippet need to be accessible, and what kinds of errors does a `<svelte:boundary>` not catch?
23. In the Tabs implementation, which pieces of state are shared through context, and what is the role of `$props.id()` in the `aria-controls`/`aria-labelledby` relationships?
24. Why does `Tab` use `tabindex={selected ? 0 : -1}`? What keyboard behaviour should users get, and where in the code does it come from?
25. For the Combobox: which two attributes does `role="combobox"` require, according to the compiler, and what is the purpose of `aria-activedescendant` compared with moving DOM focus to each option?
26. Why is the `svelte-ignore a11y_click_events_have_key_events` on the combobox `<li>` defensible, and what would make it indefensible?
27. What is customizable `<select>` support (5.47), and why is a native `<select>` still preferable to a custom dropdown for accessibility?
28. Name five things the compiler’s accessibility checks cannot detect.
29. What can `axe-core` detect in jsdom, and what do you need a real browser for? Write the Playwright snippet that runs axe on a page.
30. Multiple choice: which statement about role-based queries (`getByRole`) is true?

    a.  They only work for elements with an explicit `role` attribute.
    b.  They match implicit roles and accessible names, so a passing query is evidence the element is exposed correctly.
    c.  They are slower than test IDs, so should be avoided.
    d.  They require Playwright.

