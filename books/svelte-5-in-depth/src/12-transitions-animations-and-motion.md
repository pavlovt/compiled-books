# Chapter 11: Transitions, Animations and Motion

Motion in a component framework is a scheduling problem disguised as a visual one. An element that leaves the DOM must stay in the DOM until its exit animation ends, but the framework also has to decide *which* elements deserve that grace period, what happens when the user reverses the state change halfway through, how a list reorder can be animated without the application measuring anything, and how all of this survives users who have asked their operating system for less motion. Svelte answers these questions with three cooperating subsystems: **transitions** (`transition:`, `in:`, `out:`) for elements entering and leaving, **animations** (`animate:`) for elements that move inside a keyed `{#each}`, and **motion primitives** (`Tween` and `Spring` in `svelte/motion`) for values that should approach a target over time instead of jumping.

This chapter treats all three at senior depth. We read the runtime that implements transitions (it is short, and it explains nearly every surprising behaviour), enumerate every built-in transition, animation and easing function with its defaults, write custom transitions with `css` and `tick`, build deferred transitions in the style of `crossfade`, and cover the imperative side (`mount`/`unmount` with intros and outros) and the accessibility trap that the documentation calls out explicitly: transitions run through the Web Animations API, so a blanket `prefers-reduced-motion` CSS rule does not disable them.

Everything here assumes runes mode and Svelte 5.57. Runtime internals quoted below (for instance `$.transition(...)`) are private and version-specific; they are shown to explain behaviour, never as an API to call.

## The transition model

A transition is triggered by an element entering or leaving the DOM *as a result of a state change* — specifically, because a block (`{#if}`, `{#each}`, `{#key}`, `{#await}`, a component’s own `{#if}` etc.) created or destroyed it. A bare element with `transition:fade` that is simply present when its component mounts is also an intro candidate (we return to this under “Mount and unmount”).

```html
<script lang="ts">
    import { fade } from 'svelte/transition';

    let visible = $state(false);
</script>

<button onclick={() => (visible = !visible)}>toggle</button>

{#if visible}
    <div transition:fade>fades in and out</div>
{/if}
```

Three directives exist, and they differ only in direction handling:

| Directive       | Plays on intro | Plays on outro | Reversible mid-flight |
|-----------------|----------------|----------------|-----------------------|
| `transition:fn` | yes            | yes            | yes                   |
| `in:fn`         | yes            | no             | no                    |
| `out:fn`        | no             | yes            | no                    |

An element may have at most one `transition:`, and it cannot be combined with `in:` or `out:` on the same element. The compiler enforces this with `transition_conflict` (“Cannot use `transition:` alongside existing `in:` directive”) and `transition_duplicate`. You may have one `in:` and one `out:` together, which is how you get an asymmetric pair:

```html
{#if visible}
    <div in:fly={{ y: 200 }} out:fade>flies in, fades out</div>
{/if}
```

### Keeping content alive during the outro

The first rule of the model, quoted from the docs: when a block is transitioning out, *all* elements inside it — including those without transitions of their own — stay in the DOM until every transition in the block has finished. This is why you can put `transition:fade` on a single child and the whole subtree fades out with correct layout instead of vanishing. While an outro plays, Svelte sets the `inert` property on the element, so the exiting element cannot be focused or clicked. If the outro is aborted (the state flips back), the original `inert` value is restored.

### Bidirectional vs. non-bidirectional

With `transition:`, if the user toggles `visible` back to `true` while the outro is half done, the element does not restart from `t = 0`: it reverses from its current position. With `in:`/`out:`, the docs say the intro “will continue to ‘play’ alongside the `out` transition, rather than reversing”, and if an outro is aborted, transitions restart from scratch. Choose `transition:` for toggles that the user may flip quickly (menus, disclosure widgets) and `in:`/`out:` when the two directions are conceptually different animations (a toast that flies in from the right and fades out in place).

### Local versus global

Transitions are **local by default**: they play only when the block they *directly* belong to is created or destroyed, not when an ancestor block is.

```html
{#if x}
    {#if y}
        <p transition:fade>fades in and out only when y changes</p>

        <p transition:fade|global>fades in and out when x or y change</p>
    {/if}
{/if}
```

The default exists because it is almost always what you want: when a whole page section disappears, you do not want every list row inside it to run its own exit animation and delay the removal. The `|global` modifier opts back in. Note that `|global` is a *modifier on the directive*, not a parameter, so it comes before the parameter expression: `transition:fade|global={{ duration: 200 }}`.

How does the runtime decide? Compiling a small component shows what the directive becomes (output from `svelte@5.57.2`, illustrative):

```html
{#if show}
    <p transition:fade|global={{ duration: 200 }}>hi</p>
{/if}
```

```js
$.transition(7, p, () => fade, () => ({ duration: 200 }));
```

The first argument is a bit mask: `TRANSITION_IN` (1) \| `TRANSITION_OUT` (2) \| `TRANSITION_GLOBAL` (4) = 7. A plain `in:fade` compiles to `$.transition(1, ...)`, a local `out:` to `2`, a local `transition:` to `3`. Note the two getters: the function and its parameters are passed as thunks. The transition function is therefore looked up and the parameters object is built *when the transition starts*, not when the component renders, which is why parameters can read current state:

```html
<div transition:fly={{ y: prefersReducedMotion.current ? 0 : 200 }}>...</div>
```

For the local/global decision the runtime walks from the element’s effect to the nearest enclosing *block* effect (skipping “transparent” blocks such as snippets and `else if` branches) and checks whether that block has already run. If the block effect is the thing that is currently initialising — meaning *this* block was just created by the state change — the transition plays. If the block was created earlier and some ancestor is what changed, a local transition is skipped.

> **Note:** “Local” is about *which block changed*, not about which element is closest in the DOM. A transition inside a component’s `{#if}` is local to that `{#if}`; passing the component itself through an outer `{#if}` does not trigger it unless you add `|global`.

### Events

An element with a transition dispatches four additional `CustomEvent`s in addition to ordinary DOM events: `introstart`, `introend`, `outrostart`, `outroend`. In runes mode you listen with event attributes:

```html
{#if visible}
    <p
        transition:fly={{ y: 200, duration: 2000 }}
        onintrostart={() => (status = 'intro started')}
        onoutrostart={() => (status = 'outro started')}
        onintroend={() => (status = 'intro ended')}
        onoutroend={() => (status = 'outro ended')}
    >
        Flies in and out
    </p>
{/if}
```

The events do not bubble (they are plain `new CustomEvent(type)`), and they are dispatched outside any reactive context, so reading state inside the handler does not subscribe anything. `outroend` is the point at which the element is actually removed; it is the right hook for “after the thing is gone” work such as restoring focus.

> **Warning:** `introend`/`outroend` are dispatched even when a transition has a zero duration and zero delay. In that case the runtime short-circuits and calls start and finish synchronously without creating a Web Animation. Do not assume an `*end` event implies that any pixels moved.

## What the runtime actually does

The pieces of `transitions.js` are small enough to describe exactly. This is the model you should hold when debugging.

1.  **Resolution.** When the element’s block is destroyed (outro) or created (intro), the runtime calls your transition function with `(node, params, { direction })` where `direction` is `'in'`, `'out'` or `'both'` (`both` for `transition:`). The returned config is *cached* while the transition is in progress. This is deliberate: when a bidirectional transition reverses, the same config is reused so that a `duration` computed from the node’s size on the first call does not jump.

2.  **Zero-duration shortcut.** If the config has neither `duration` nor `delay`, there is nothing to schedule: start and finish callbacks run immediately.

3.  **Dummy animation.** Otherwise the runtime waits one microtask (so that sibling transitions started in the same batch all measure the DOM *before* any of them applies styles), then creates a dummy `element.animate([], { duration: delay, fill: 'forwards' })`. For an intro with no counterpart, the dummy carries the `t = 0` styles so the element is never painted in its final state while it waits out the delay.

4.  **Keyframe sampling.** When the dummy finishes, the real animation begins. If you supplied `css`, Svelte calls `css(t, u)` *ahead of time*, `Math.ceil(duration / (1000 / 60))` times plus one, and applies **your easing function itself** to each sample: `t = t1 + delta * easing(i / n)`. The resulting list of keyframes is handed to `element.animate(keyframes, { duration, fill: 'forwards' })` with the browser’s default (linear) timing. Two consequences follow. First, a 400 ms transition produces 25 keyframes, so an expensive `css` function is called 25 times up-front, not per frame. Second, `css` must be a *pure function of `t`*; it will never be called again during playback, and it is called before the transition begins.

5.  **`tick`.** If you supplied `tick`, a `loop` (driven by `requestAnimationFrame`) calls `tick(t, u)` every frame while the animation’s `playState` is `'running'`, and once more with the final `t` when it ends.

6.  **Reversal.** For a bidirectional transition the new animation starts from the counterpart’s current `t` (read from the in-flight animation’s `currentTime` via the easing) and runs for `duration * |delta|`. A reversal 25% of the way through an intro takes 25% of the duration.

7.  **Cleanup.** On finish the runtime dispatches `introend`/`outroend`, cancels the animation (to avoid leaking it) and, for an outro, invokes the callback that lets the block effect finally destroy the DOM.

You can verify the sampling behaviour in a test by stubbing `Element.prototype.animate` (jsdom has none) and recording the keyframes. For `fly` with `duration: 100` the runtime requested a 100 ms animation with 7 keyframes (`ceil(100/16.67) + 1`), starting at `translate(0px, 20px)` with opacity 0 and ending at `translate(0px, 0px)` with opacity 1.

```ts
// test setup (jsdom): record Web Animations instead of playing them
const created: { keyframes: Keyframe[]; options: KeyframeAnimationOptions }[] = [];

Element.prototype.animate = function (keyframes: any, options: any) {
    const anim: any = { keyframes, options, onfinish: null, cancel() {}, playState: 'running', currentTime: 0 };
    created.push({ keyframes, options });
    setTimeout(() => anim.onfinish?.(), options.duration);
    return anim;
};
```

Because the runtime schedules the dummy animation and the real one separately, every transition produces *two* `animate()` calls: one of length `delay` (often 0) and one of the real duration. Tests that count animations should expect that.

### Why `css` beats `tick`

The docs state it plainly: “If it’s possible to use `css` instead of `tick`, do so — web animations can run off the main thread, preventing jank on slower devices.” Pre-computed keyframes let the compositor animate `transform` and `opacity` without involving JavaScript each frame. `tick` runs on the main thread, mutates the DOM from a rAF callback, and competes with your own scripts. Reserve `tick` for effects CSS cannot express: changing text content (the typewriter), animating non-CSS state, drawing to a canvas.

A subtle `tick` detail: for an intro without a counterpart, `tick(0, 1)` is called synchronously at setup so the initial frame is correct, and `tick(t2, 1 - t2)` is called when the animation finishes so you always see the exact terminal state regardless of frame timing.

## Built-in transitions (`svelte/transition`)

All built-ins return a `TransitionConfig` and read the element’s *computed* style when they start, so they compose with whatever CSS the element already has. Types, from `svelte/transition`:

```ts
interface TransitionConfig {
    delay?: number;
    duration?: number;
    easing?: EasingFunction;           // (t: number) => number
    css?: (t: number, u: number) => string;
    tick?: (t: number, u: number) => void;
}
```

| Function | Parameters (defaults) | What it animates |
|------------------------|------------------------|------------------------|
| `fade` | `delay = 0`, `duration = 400`, `easing = linear` | `opacity` from 0 to the element’s current opacity |
| `blur` | `delay = 0`, `duration = 400`, `easing = cubicInOut`, `amount = 5`, `opacity = 0` | `filter: blur()` plus opacity; `amount` may be a number (px) or a string with a unit |
| `fly` | `delay = 0`, `duration = 400`, `easing = cubicOut`, `x = 0`, `y = 0`, `opacity = 0` | `transform: translate()` and opacity; `x`/`y` may be numbers (px) or strings with units |
| `slide` | `delay = 0`, `duration = 400`, `easing = cubicOut`, `axis = 'y'` | height (or width for `'x'`), padding, margin and border widths of that axis, with `overflow: hidden` |
| `scale` | `delay = 0`, `duration = 400`, `easing = cubicOut`, `start = 0`, `opacity = 0` | `transform: scale()` plus opacity |
| `draw` | `delay = 0`, `speed`, `duration`, `easing = cubicInOut` | `stroke-dasharray`/`stroke-dashoffset` on an SVG shape with `getTotalLength()` |
| `crossfade` | see below | pair of `send`/`receive` transitions |

A few details that are easy to miss, all confirmed in the source:

- `fade`, `fly`, `scale`, `blur` multiply by the element’s *existing* opacity (`+getComputedStyle(node).opacity`), so an element styled with `opacity: 0.5` fades to 0.5, not 1. `fly` and `scale` prepend the element’s existing `transform` rather than replacing it.
- `fly` interprets `x`/`y` values with `split_css_unit`: `y: 200` becomes `200px`, `y: '50%'` stays percent, `y: '-2rem'` keeps `rem`. Because it is a *translate relative to the element’s own size* for percentages, `x: '100%'` slides in from one element-width away.
- `slide` measures `height`/`width`, paddings, margins and border widths from computed style. In development it emits the `transition_slide_display` warning for elements whose `display` contains `contents`, `inline` or `table` (the docs list `inline`, `inline-block`, `inline-flex`, `inline-grid`, `contents` and table displays), because an inline box has no `height` to animate. Make the element `display: block`, `flex` or `grid`. Unresolved (`NaN`) dimensions are omitted rather than emitted as invalid CSS.
- `draw` adds the stroke width to the path length when `stroke-linecap` is not `butt`, so rounded caps are fully drawn. If neither `speed` nor `duration` is given it uses 800 ms; if `speed` is given, `duration = length / speed`; `duration` may be a function of the length.
- None of the built-ins read your reduced-motion preference. See “Accessibility” below.

A practical composition: apply `fly` to an element whose layout is managed by flex gap, and `slide` to its wrapper when you need the space to collapse smoothly:

```html
<script lang="ts">
    import { slide, fly } from 'svelte/transition';

    let toasts = $state<{ id: number; text: string }[]>([]);
    let nextId = 0;

    function push(text: string) {
        const id = nextId++;
        toasts.push({ id, text });
        setTimeout(() => (toasts = toasts.filter((t) => t.id !== id)), 3000);
    }
</script>

<button onclick={() => push('Saved')}>Save</button>

<ul class="stack">
    {#each toasts as toast (toast.id)}
        <li transition:slide={{ duration: 200 }}>
            <div in:fly={{ x: '100%', duration: 250 }} out:fly={{ x: '100%', duration: 150 }}>
                {toast.text}
            </div>
        </li>
    {/each}
</ul>

<style>
    .stack { display: grid; gap: 0.5rem; list-style: none; padding: 0; }
    li { display: block; }
</style>
```

Here the `<li>` collapses the space while the inner `<div>` flies. Both transitions are local to the keyed `{#each}` block, so they play when toasts are added or removed.

## Custom transitions

A transition is any function with this shape (from the docs):

```ts
type TransitionFn = (
    node: HTMLElement,
    params: any,
    options: { direction: 'in' | 'out' | 'both' }
) => {
    delay?: number;
    duration?: number;
    easing?: (t: number) => number;
    css?: (t: number, u: number) => string;
    tick?: (t: number, u: number) => void;
};
```

The contract for `t`: *in* transitions run from `0` to `1`, *out* transitions run from `1` to `0`, and `1` is always the element’s natural state “as though no transition had been applied.” `u` equals `1 - t`. Because `css` is sampled, the string it returns must be a list of declarations (`opacity: 0.5; transform: scale(0.9)`), which the runtime parses by splitting on `;` and `:`. Complex values containing a colon or semicolon (for instance a `url(data:...)`) will break that parser; keep `css` output to simple declarations.

### A typed `css` transition

```ts
// src/lib/transitions.ts
import { cubicOut } from 'svelte/easing';
import type { TransitionConfig } from 'svelte/transition';

interface WhooshParams {
    delay?: number;
    duration?: number;
    easing?: (t: number) => number;
}

export function whoosh(node: Element, params: WhooshParams = {}): TransitionConfig {
    const existing = getComputedStyle(node).transform.replace('none', '');

    return {
        delay: params.delay ?? 0,
        duration: params.duration ?? 400,
        easing: params.easing ?? cubicOut,
        css: (t) => `transform: ${existing} scale(${t}); opacity: ${t}`
    };
}
```

Rules worth internalising:

- Read layout and computed style at the *top* of the function, not inside `css`. The function runs once per transition, `css` runs \~25 times.
- Always fold the element’s existing `transform`, `opacity` and `filter` into the generated string, as the built-ins do. Otherwise your transition will stomp styles the element legitimately has. Beware the string `none`: `getComputedStyle(node).transform` returns `'none'` when there is no transform, and `none scale(0.5)` is invalid CSS, hence the `.replace('none', '')`.
- Honour `direction` when intro and outro should differ in a `transition:` (they share one function):

```ts
export function pop(node: Element, { distance = 12 }: { distance?: number } = {}, { direction }: { direction: 'in' | 'out' | 'both' } = { direction: 'both' }): TransitionConfig {
    return {
        duration: direction === 'out' ? 120 : 220,
        css: (t, u) => `opacity: ${t}; transform: translateY(${u * distance}px)`
    };
}
```

> **Note:** Svelte always passes the third argument. The default value in the signature above only matters if you also call the function manually.

### A `tick` transition

The documentation’s typewriter is the canonical case for `tick`: the visual effect is a change in text content, which no CSS keyframe can express.

```ts
export function typewriter(node: HTMLElement, { speed = 1 }: { speed?: number } = {}): TransitionConfig {
    const valid = node.childNodes.length === 1 && node.childNodes[0].nodeType === Node.TEXT_NODE;
    if (!valid) throw new Error('typewriter only works on elements with a single text child');

    const text = node.textContent ?? '';
    const duration = text.length / (speed * 0.01);

    return {
        duration,
        tick: (t) => {
            node.textContent = text.slice(0, ~~(text.length * t));
        }
    };
}
```

Because `tick` mutates text imperatively, the reactive text node Svelte created is now out of sync with its template expression. That is harmless during an intro that ends in the full text, but for an element whose text can change *during* the transition it is a source of confusing output. Keep tick-based transitions for static content.

### Transitions that depend on state

Parameters are re-evaluated whenever a transition starts, so reading `$state` in the parameter expression is fine, but changing state *while* a transition is running does not alter the running transition (the config is cached for the duration). To react to the user’s motion preference mid-session, make the decision at start time.

### Deferred transitions

If a transition function returns a *function* instead of a config object, the runtime calls that function in the next microtask and uses its return value as the config. The one-microtask delay lets several independent transitions register themselves first so that they can look at each other. This is how `crossfade` works, and the source is the best tutorial for the technique.

```ts
// condensed from svelte/transition: crossfade
export function crossfade({ fallback, ...defaults }) {
    const to_receive = new Map<any, Element>();
    const to_send = new Map<any, Element>();

    function transition(items: Map<any, Element>, counterparts: Map<any, Element>, intro: boolean) {
        return (node: Element, params: { key: any }) => {
            items.set(params.key, node);       // 1. register myself under my key
            return () => {                     // 2. deferred: runs next microtask
                if (counterparts.has(params.key)) {
                    const other = counterparts.get(params.key)!;
                    counterparts.delete(params.key);
                    return crossfadeBetween(other, node, params);  // 3. found a partner
                }
                items.delete(params.key);      // 4. nobody claimed it
                return fallback && fallback(node, params, intro);
            };
        };
    }
    return [transition(to_send, to_receive, false), transition(to_receive, to_send, true)];
}
```

When an element leaves one list (`send`) and its counterpart enters another (`receive`) in the same flush, each registers under the same `key`; in the microtask each finds the other, computes the delta between their bounding rectangles, and animates translate + scale + opacity so that the outgoing element appears to travel to the incoming element’s position. The unpaired case uses the `fallback` transition you supplied (typically `fade` or `scale`).

Public signature, from the types:

```ts
crossfade(params: CrossfadeParams & {
    fallback?: (node: Element, params: CrossfadeParams, intro: boolean) => TransitionConfig;
}): [send, receive]  // each: (node, params: CrossfadeParams & { key: any }) => () => TransitionConfig

interface CrossfadeParams { delay?: number; duration?: number | ((len: number) => number); easing?: EasingFunction }
```

The default `duration` is `Math.sqrt(distance) * 30` (the distance between the two rectangles), and the default easing is `cubicOut`. Here is the todo-list pattern that the docs and tutorials use, in full, with `animate:flip` closing the gap in the remaining items:

```html
<!-- src/lib/TodoBoard.svelte -->
<script lang="ts">
    import { crossfade, fade } from 'svelte/transition';
    import { flip } from 'svelte/animate';
    import { cubicOut } from 'svelte/easing';

    interface Todo { id: number; text: string; done: boolean }

    let todos = $state<Todo[]>([
        { id: 1, text: 'write chapter', done: false },
        { id: 2, text: 'run examples', done: false },
        { id: 3, text: 'ship', done: true }
    ]);

    const open = $derived(todos.filter((t) => !t.done));
    const done = $derived(todos.filter((t) => t.done));

    const [send, receive] = crossfade({
        duration: (d) => Math.sqrt(d * 200),
        fallback: (node) => fade(node, { duration: 200, easing: cubicOut })
    });
</script>

<div class="board">
    {#each [['open', open], ['done', done]] as const as [name, list] (name)}
        <ul>
            <h2>{name}</h2>
            {#each list as todo (todo.id)}
                <li
                    in:receive={{ key: todo.id }}
                    out:send={{ key: todo.id }}
                    animate:flip={{ duration: 250 }}
                >
                    <label>
                        <input type="checkbox" bind:checked={todo.done} />
                        {todo.text}
                    </label>
                </li>
            {/each}
        </ul>
    {/each}
</div>
```

Walk through what happens when you tick “write chapter”: the `$derived` lists update, the item is removed from the `open` each block (its `out:send` registers key 1 in `to_send`) and added to `done` (its `in:receive` registers key 1 in `to_receive`). In the next microtask each deferred function finds its partner and the two elements are animated toward/away from each other. Meanwhile the items remaining in `open` are re-ordered by position, and `animate:flip` slides them up.

> **Senior tip:** `in:`/`out:` (rather than `transition:`) is correct for crossfade: the two halves are different functions with different counterparts. Also note the transitions are used inside *nested* each blocks. They are local to the inner keyed each, and that is exactly what fires here because the inner block’s items change.

## Animations: `animate:` and `flip`

An animation is for elements that **move**, not ones that appear or disappear. Per the docs, it is triggered when the contents of a keyed each block are re-ordered; it does not run when an item is added or removed, only “when the index of an existing data item within the each block changes”. Two compile-time requirements, both checked by the compiler:

- the element must be an **immediate child** of the each block, and the only child (`animation_invalid_placement`);
- the each block must be **keyed** (`animation_missing_key`), and only one `animate:` is allowed per element (`animation_duplicate`).

```html
{#each list as item (item.id)}
    <li animate:flip={{ delay: 500 }}>{item.label}</li>
{/each}
```

Compiled, the directive becomes `$.animation(li, () => flip, () => ({ delay: 500 }))` registering an *animation manager* on the block’s item. During reconciliation the manager’s `measure()` captures `from = getBoundingClientRect()` before the DOM is rearranged; after the rearrangement `apply()` captures `to`, and — only if left/right/top/bottom changed — calls your animation function with `(node, { from, to }, params)` and plays the returned config exactly as a transition config is played (same keyframe sampling, same `css`/`tick` rules).

### `flip`

```ts
flip(node: Element, { from, to }: { from: DOMRect; to: DOMRect }, params?: {
    delay?: number;                               // default 0
    duration?: number | ((len: number) => number); // default (d) => Math.sqrt(d) * 120
    easing?: (t: number) => number;                // default cubicOut
}): AnimationConfig
```

`flip` is First-Last-Invert-Play: it computes the pixel translation between the first and last positions of the transform origin, plus the relative scale if the size changed, then animates from the inverted state back to identity. The implementation compensates for parent transforms and CSS zoom (`currentCSSZoom` where available) and prepends the element’s existing transform. The default duration scales with the square root of the travel distance, so short hops are quick and long jumps do not take forever. Browser support note from the docs: `flip` appears in the browser support “exceptions” table as requiring Firefox 126.

A second piece of machinery makes list animations look right: when an item is *removed* with an outro and siblings are animating, the runtime calls `fix()` on exiting siblings, temporarily setting `position: absolute` with the measured width/height and a compensating translate so that the exiting element does not occupy flow space while the others slide into place, then `unfix()` restores the original inline styles. The comment in the source also records one caveat: if an animation is already running on the element (for instance a `crossfade` transform), `fix()` bails out, because applying another `translate(...)` would be overridden by the running animation. Practically: do not give list items `position` rules that conflict with this, and prefer `transform`-based entrance effects.

### Custom animation functions

```ts
import { cubicOut } from 'svelte/easing';
import type { AnimationConfig } from 'svelte/animate';

export function whizz(node: Element, { from, to }: { from: DOMRect; to: DOMRect }): AnimationConfig {
    const dx = from.left - to.left;
    const dy = from.top - to.top;
    const d = Math.sqrt(dx * dx + dy * dy);

    return {
        delay: 0,
        duration: Math.sqrt(d) * 120,
        easing: cubicOut,
        css: (t, u) => `transform: translate(${u * dx}px, ${u * dy}px) rotate(${t * 360}deg);`
    };
}
```

`AnimationConfig` has the same five optional fields as `TransitionConfig`. As with transitions, a `tick` alternative exists and carries the same performance warning.

> **Warning:** A reorder in which an element’s position is unchanged (same rectangle) produces no animation at all, because `apply()` compares the four edges before calling your function. Resizing-only changes are therefore not animated by `animate:`; you would need a transition or CSS.

## Easing functions (`svelte/easing`)

Every easing is a pure function `(t: number) => number` mapping `[0, 1]` to (roughly) `[0, 1]`; the “back”, “elastic” and “bounce” families overshoot. The full list in `svelte/easing`:

| Family  | In          | Out          | InOut          |
|---------|-------------|--------------|----------------|
| (none)  | `linear`    |              |                |
| back    | `backIn`    | `backOut`    | `backInOut`    |
| bounce  | `bounceIn`  | `bounceOut`  | `bounceInOut`  |
| circ    | `circIn`    | `circOut`    | `circInOut`    |
| cubic   | `cubicIn`   | `cubicOut`   | `cubicInOut`   |
| elastic | `elasticIn` | `elasticOut` | `elasticInOut` |
| expo    | `expoIn`    | `expoOut`    | `expoInOut`    |
| quad    | `quadIn`    | `quadOut`    | `quadInOut`    |
| quart   | `quartIn`   | `quartOut`   | `quartInOut`   |
| quint   | `quintIn`   | `quintOut`   | `quintInOut`   |
| sine    | `sineIn`    | `sineOut`    | `sineInOut`    |

“In” accelerates from rest, “Out” decelerates to rest, “InOut” does both. `cubicOut` is the most common default (used by `fly`, `slide`, `scale`, `flip`, `crossfade`); `linear` is the default for `fade` and for `Tween`.

Since easings are plain functions you can write your own — or adapt a CSS cubic-bezier — and pass it anywhere an `easing` is accepted:

```ts
// y = x^1.7, a custom power curve
export const power = (t: number) => Math.pow(t, 1.7);
```

Remember where the easing is applied. For `css` transitions Svelte applies it while generating keyframes, so the browser sees pre-eased linear-timed keyframes. For `tick` transitions it is applied to the elapsed fraction before calling `tick`. In both cases the `t` your function receives is *already* eased, which means an overshooting easing (`backOut`, `elasticOut`) can hand your `css` a `t > 1`. A `css` function that does `opacity: ${t}` will then produce an invalid opacity above 1 for a moment; clamp when it matters (`Math.min(1, t)`).

## Motion primitives (`svelte/motion`)

Transitions animate *elements in and out of the DOM*. `Tween` and `Spring` animate *values*: they hold a `current` that chases a `target`, and since both are reactive, anything reading `current` re-renders as it moves. Both arrived in Svelte 5.8 as classes and replace the older `tweened`/`spring` stores, which are deprecated.

### `Tween`

```ts
class Tween<T> {
    constructor(value: T, options?: TweenOptions<T>);
    static of<U>(fn: () => U, options?: TweenOptions<U>): Tween<U>;
    set(value: T, options?: TweenOptions<T>): Promise<void>;
    get current(): T;
    get target(): T;
    set target(v: T);
}

interface TweenOptions<T> {
    delay?: number;                                  // default 0
    duration?: number | ((from: T, to: T) => number); // default 400
    easing?: (t: number) => number;                  // default linear
    interpolate?: (a: T, b: T) => (t: number) => T;
}
```

```html
<script lang="ts">
    import { Tween } from 'svelte/motion';
    import { cubicOut } from 'svelte/easing';

    const progress = new Tween(0, { duration: 600, easing: cubicOut });
</script>

<progress value={progress.current} max="1"></progress>
<button onclick={() => progress.set(0.25)}>25%</button>
<button onclick={() => (progress.target = 1)}>100%</button>
```

Assigning `target` is the same as calling `set(value)` with the constructor defaults; `set` lets you override options per call. Reading `current` inside a template, `$derived` or `$effect` tracks it like any `$state`.

Behaviours verified in the source:

- **Interpolation of structured values.** The default interpolator handles numbers, arrays (element-wise), plain objects (per key of the *target*), and `Date`s. A `Tween<{ x: number; y: number }>` works out of the box. Values of a type it cannot interpolate (strings, booleans) **snap** to the final value immediately (Svelte 5.17); previously this threw. Type mismatches (`number` → `string`) or `null` objects still throw (`Cannot interpolate values of different type`).
- **`duration: 0`** aborts any running tween and assigns directly.
- **A function `duration`** receives `(from, to)` and is called when the tween actually starts (after `delay`), so you can make duration proportional to distance.
- **Superseding.** Calling `set` again aborts the previous run and starts from wherever `current` is *now*. The earlier call’s promise **never settles** — the loop task is simply deleted from the scheduler, and nothing resolves or rejects the promise it returned. `await tween.set(...)` in code that can be pre-empted is therefore a leak risk; only await the promise whose completion you will act on and treat it as “resolved if it finishes”.
- **`Tween.of`** creates a tween bound to an expression: `Tween.of(() => value)` constructs it from the current value and calls `set` inside a render effect whenever the expression changes. It must run inside an effect root (typically component initialisation).

```html
<script lang="ts">
    import { Tween } from 'svelte/motion';
    import { cubicOut } from 'svelte/easing';

    let { value }: { value: number } = $props();

    // animates whenever the parent changes `value`
    const shown = Tween.of(() => value, { duration: 300, easing: cubicOut });
</script>

<span>{Math.round(shown.current)}</span>
```

A custom `interpolate` is the escape hatch for colors, angles that should take the short way around, or anything else:

```ts
import { Tween } from 'svelte/motion';

type RGB = [number, number, number];

const lerpRGB = (a: RGB, b: RGB) => (t: number): RGB =>
    [0, 1, 2].map((i) => Math.round(a[i] + (b[i] - a[i]) * t)) as RGB;

const color = new Tween<RGB>([255, 0, 0], { duration: 500, interpolate: lerpRGB });
```

### `Spring`

```ts
class Spring<T> {
    constructor(value: T, options?: SpringOptions);
    static of<U>(fn: () => U, options?: SpringOptions): Spring<U>;
    set(value: T, options?: SpringUpdateOptions): Promise<void>;
    damping: number;       // default 0.8
    precision: number;     // default 0.01
    stiffness: number;     // default 0.15
    target: T;
    get current(): T;
}

interface SpringUpdateOptions {
    instant?: boolean;          // Spring class only
    preserveMomentum?: number;  // Spring class only, milliseconds
    hard?: any;                 // deprecated, store only
    soft?: string | number | boolean; // deprecated, store only
}
```

A spring has no duration. Each frame it applies a spring force toward the target and a damping force against velocity, and it settles when both the velocity step and the remaining distance fall below `precision`. Higher `stiffness` means a stronger pull (snappier); higher `damping` means less oscillation. In the implementation `stiffness` and `damping` are clamped to `[0, 1]` both in the constructor and on assignment, and they are reactive properties, so you can retune a spring live:

```html
<script lang="ts">
    import { Spring } from 'svelte/motion';

    const pos = new Spring({ x: 0, y: 0 }, { stiffness: 0.1, damping: 0.25 });
</script>

<svelte:window onpointermove={(e) => pos.set({ x: e.clientX, y: e.clientY })} />

<div class="dot" style:transform="translate({pos.current.x}px, {pos.current.y}px)"></div>
```

Springs accept numbers, `Date`s, arrays and plain objects of them (anything else throws `Cannot spring <type> values`). Further notes:

- **Time step clamp.** The per-frame elapsed time is clamped to 1/30 s, so a backgrounded tab or a long main-thread block does not make the integration explode.
- **`instant: true`** sets `current` and `target` immediately and cancels the running task. This is how you “teleport” (for example, on window resize) without a visible chase.
- **`preserveMomentum: ms`** makes the spring behave as though it had infinite mass for roughly that many milliseconds, so it continues along its current trajectory before the spring force takes over. It is aimed at fling gestures: release a drag with a velocity and let it coast.
- **Interrupted promises reject.** Unlike `Tween`, calling `set` again on a `Spring` rejects the earlier call’s promise with `Error('Aborted')` (the class attaches a no-op catch internally to avoid unhandled-rejection noise for fire-and-forget uses, but if *you* `await` an interrupted `set`, it throws). Wrap awaited calls in `try/catch` or do not await.
- The first `set` on a spring created with an `undefined` value assigns immediately.

> **Senior tip:** Prefer `Spring` for anything driven by pointer input (drag, follow-cursor, pull-to-refresh) because springs maintain velocity across target changes and look natural when retargeted mid-flight; prefer `Tween` for deterministic, timed transitions of a value (progress bars, counters, color changes) where you want to say exactly how long it takes.

### Deprecated stores

`spring()` and `tweened()` remain, marked `@deprecated`, returning stores (`$spring`, `$tweened`) with `.set`/`.update`. They are covered by the store contract of Chapter 12; migrate by replacing `$store` reads with `.current` and `store.set(v)` with `instance.set(v)` or `instance.target = v`. Note the option split in `SpringUpdateOptions`: `hard` and `soft` only work on the store; `instant` and `preserveMomentum` only on the class.

### Exported option types

Since 5.55 the module also exports the types `TweenOptions`, `SpringOptions`, `SpringUpdateOptions` and `Updater`, which you need when writing wrappers that accept the same options.

## Mount and unmount: intros and outros at the edges

Transitions are not only for blocks. Two imperative APIs from `svelte` interact with them:

```ts
mount(component, { target, props?, intro?: boolean /* default true */ });
unmount(component, { outro?: boolean }): Promise<void>;  // outro since 5.13
```

- **`mount` plays intro transitions by default.** The docs: “Transitions will play during the initial render unless the `intro` option is set to `false`.” So the first render of `App` with `{#if}`-wrapped `in:fade` content fades in at page load. Pass `intro: false` if you want the page to appear instantly. (In the runtime source, `hydrate` defaults `intro` to `false`, because the DOM already exists on screen; pass `intro: true` to force it.)
- **`unmount` does not play outros unless you ask.** `unmount(app)` removes the DOM immediately. `unmount(app, { outro: true })` plays the outros of the transitions in the tree and returns a promise that resolves when they have finished. This is the right tool for closing imperatively-mounted dialogs or toasts:

```ts
import { mount, unmount } from 'svelte';
import Toast from './Toast.svelte';

export function showToast(text: string, ms = 3000) {
    const toast = mount(Toast, { target: document.body, props: { text } });
    setTimeout(() => unmount(toast, { outro: true }), ms);
}
```

- **Effects are deferred.** As with all `mount` calls, effects (including transition setup in the intro case) are scheduled, not run synchronously; call `flushSync()` in tests.

`{#key}` blocks interact naturally: when the key expression changes, the old block outros and the new one intros, which is the idiom for “animate a value change” such as a counter whose digit flips:

```html
{#key count}
    <span in:fly={{ y: -12, duration: 200 }} out:fly={{ y: 12, duration: 200 }}>{count}</span>
{/key}
```

> **Warning:** The old and new `<span>` coexist in the DOM during the overlap. Style the container (`display: inline-grid` with both children in the same grid cell, or a fixed width) or you will see a layout jump.

## Accessibility: `prefers-reduced-motion`

This is the single most common production mistake with Svelte transitions. The docs are explicit: transitions are driven by the Web Animations API, not CSS, “A global `@media (prefers-reduced-motion: reduce)` rule that zeroes `transition-duration` and `animation-duration` therefore has no effect on them.” The same is true of `animate:`. The CSS reset many teams ship does nothing here.

`svelte/motion` exports a reactive `MediaQuery`, `prefersReducedMotion`, whose `.current` is `true` when the user prefers reduced motion:

```html
<script lang="ts">
    import { prefersReducedMotion } from 'svelte/motion';
    import { fly } from 'svelte/transition';

    let visible = $state(false);
</script>

<button onclick={() => (visible = !visible)}>toggle</button>

{#if visible}
    <p transition:fly={{ y: prefersReducedMotion.current ? 0 : 200 }}>
        flies in, unless the user prefers reduced motion
    </p>
{/if}
```

Setting `y: 0` keeps the fade but removes the movement, which is usually the right “reduced” behaviour: reduced motion does not mean *no feedback*, it means no large-scale movement, parallax, zooming or spinning. To centralise the policy, wrap the built-ins:

```ts
// src/lib/motion.ts
import { prefersReducedMotion } from 'svelte/motion';
import { fade, fly, type FlyParams, type TransitionConfig } from 'svelte/transition';

export function safeFly(node: Element, params: FlyParams = {}): TransitionConfig {
    if (prefersReducedMotion.current) return fade(node, { duration: params.duration ?? 150 });
    return fly(node, params);
}
```

Because the transition function runs at the start of each transition, `prefersReducedMotion.current` is read fresh every time, so a user who changes their OS setting mid-session is respected from the next transition.

For value motion, branch at construction and at `set` time:

```ts
const x = new Tween(0, { duration: prefersReducedMotion.current ? 0 : 400 });
```

A `duration` of `0` takes the instant path. For springs use `set(value, { instant: prefersReducedMotion.current })`.

`prefersReducedMotion` uses `window.matchMedia`, so it is browser-only. During server rendering, treat it as unknown (see Chapter 9 on `MediaQuery` and its server fallback); since transitions never run on the server, the only SSR exposure is markup that *branches on* the value, which should be avoided.

## Debugging and testing animation timing

Transitions are asynchronous and tied to real time and the layout engine, which makes them awkward to test. A pragmatic strategy:

1.  **Test the logic, not the pixels.** The parts that matter to correctness are: which elements exist when, that `outroend` eventually removes DOM, and that focus ends up in the right place. Assert on those with events (`onoutroend`) and `await` a short wait.
2.  **Make durations injectable.** Accept a `duration` prop or read it from a context so tests can pass `0`. With zero duration and zero delay the runtime completes synchronously (the shortcut described above), so DOM assertions need no timers.
3.  **Stub `Element.prototype.animate`** (jsdom does not implement it) to capture keyframes, as shown earlier, when you want to assert that a custom `css` function returns what you expect. Better still, unit-test your transition function directly: it is a plain function of `(node, params)`; call it with a fake node and check `css(0, 1)` and `css(1, 0)`. The contract that `t = 1` is the natural state gives you an immediate invariant: `css(1, 0)` should produce styles equivalent to “no transition”.
4.  **Use the browser’s tools.** Chrome DevTools’ Animations panel can slow all Web Animations. The `transition_slide_display` warning and the `animation_*` compile errors surface most structural mistakes before you see anything on screen.
5.  **For unmount tests**, `await unmount(app, { outro: true })` and then assert the container is empty; use `flushSync()` after `mount` to run effects first.

A representative component test with Vitest in jsdom (see Chapter 16 for the full setup) might look like this:

```ts
import { flushSync, mount, unmount } from 'svelte';
import { expect, test } from 'vitest';
import Disclosure from './Disclosure.svelte';

test('panel is removed after outro', async () => {
    const app = mount(Disclosure, { target: document.body, props: { duration: 0, open: true } });
    flushSync();
    expect(document.querySelector('[data-panel]')).not.toBeNull();

    // the component toggles `open` to false internally
    document.querySelector('button')!.click();
    flushSync();
    expect(document.querySelector('[data-panel]')).toBeNull();

    await unmount(app, { outro: true });
});
```

## Design guidance and pitfalls

- **Animate `transform` and `opacity`.** `slide` animates `height`, padding and margin, which triggers layout every frame. It is convenient and fine for small lists; for large or frequently toggled regions prefer transform-based effects, or the CSS `grid-template-rows: 0fr → 1fr` technique with a plain class change.
- **Local is a feature.** Resist sprinkling `|global`. If an entire route disappears, each local transition inside it is correctly skipped; marking list items global would delay the route’s removal by the longest outro and, worse, run N animations at once.
- **Do not put transitions on elements whose parent is `display: contents`** or on inline elements if the transition depends on box geometry (`slide`).
- **Inert during outro.** If an exiting element contains a focused control, focus is lost to `body` when the element becomes inert. Move focus deliberately (in `onoutrostart` or before changing state).
- **Outros hold the DOM.** Any assertion or script that counts children right after a state change will still see the exiting elements until `outroend`. Components that use `bind:this` on an exiting element may see it for the whole outro.
- **Keys matter for lists.** Without a key, Svelte updates items in place and no element leaves or enters, so no transitions play where you expected. With a key, items that stay put are not disturbed, and `animate:` becomes available.
- **Budget the main thread.** `tick`-based transitions and large numbers of simultaneous springs run in rAF callbacks. Dozens are fine; thousands are not.
- **Respect motion preferences** as described, and never rely on motion as the only carrier of meaning.

## Key takeaways

- Transitions play when a *block* creates or destroys an element; elements stay in the DOM, inert, until all outros in the block end. `transition:` reverses smoothly; `in:`/`out:` do not; one `transition:` cannot coexist with `in:`/`out:`.
- Transitions are **local by default**. Use `|global` to play on ancestor block changes. The directive compiles to a bit mask (in = 1, out = 2, global = 4) plus lazily evaluated function and parameter thunks.
- The runtime samples your `css(t, u)` function about once per 16.7 ms of duration up front, applies the easing itself, and hands the browser pre-eased keyframes through `element.animate`. `css` must be pure and returns simple declarations; `tick` runs on the main thread and should be a last resort.
- A transition function returning a function is *deferred* to the next microtask; this is the mechanism behind `crossfade`’s `send`/`receive` pairing.
- Built-ins: `fade`, `blur`, `fly`, `slide` (warns on inline/contents/table display), `scale`, `draw` (SVG paths), `crossfade`; all multiply existing opacity and compose with existing transforms. Defaults: duration 400 (`draw`: 800 or length/speed; `crossfade`: `sqrt(distance) * 30`).
- `animate:` works only on the sole immediate child of a **keyed** each block and only on reorders that change position; `flip` has default duration `sqrt(distance) * 120` and `cubicOut`.
- `svelte/easing` provides `linear` plus In/Out/InOut for back, bounce, circ, cubic, elastic, expo, quad, quart, quint, sine; overshooting easings can give `css` a `t` outside `[0, 1]`.
- `Tween` (linear, 400 ms by default) interpolates numbers, arrays, objects and dates; non-interpolable values snap; a superseded `Tween.set` promise never settles. `Spring` (stiffness 0.15, damping 0.8, precision 0.01) has no duration, supports `instant` and `preserveMomentum`, and rejects a superseded `set` promise with `Error('Aborted')`. `Tween.of`/`Spring.of` bind to an expression and require an effect root.
- `mount` plays intros by default (`intro: false` disables); `hydrate` defaults to no intro; `unmount(app, { outro: true })` (5.13) plays outros and returns a promise.
- Web Animations ignore a global reduced-motion CSS rule. Branch on `prefersReducedMotion.current` from `svelte/motion` inside transition functions, parameters and motion options.

## Review Questions

1.  A component contains `{#if open}<ul><li transition:fade>one</li><li>two</li></ul>{/if}`. When `open` becomes `false`, how long does the `<li>two</li>` element remain in the DOM, and why?

2.  Explain the difference in behaviour between `transition:fly` and the pair `in:fly out:fly` when the user toggles a boolean twice in quick succession (once during the intro, again while the outro runs).

3.  What compile error do you get for `<div transition:fade in:fly>`? Is `<div in:fly out:fade>` allowed?

4.  Given the code below, which paragraphs fade when `x` flips from `false` to `true` while `y` is already `true`?

    ```html
    {#if x}
     {#if y}
         <p transition:fade>A</p>
         <p transition:fade|global>B</p>
     {/if}
    {/if}
    ```

5.  Why does Svelte pass the transition function and its parameters to the runtime as thunks (`() => fade`, `() => ({ duration: 200 })`) rather than values? Give one practical consequence for parameters.

6.  (Multiple choice) The `css` function of a custom transition is called:

    a.  Once per animation frame while the transition plays
    b.  Once, with `t = 1`
    c.  Repeatedly before the transition begins, roughly once per 16.7 ms of its duration, to build keyframes
    d.  Only when `tick` is absent and the browser lacks Web Animations support

7.  A teammate writes ``css: (t) => `opacity: ${t}` `` with `easing: backOut`. What problem can occur at the end of an intro, and how do you fix it?

8.  Why is `css` preferred over `tick`? Name a legitimate use case where only `tick` works.

9.  What does the following print in the browser console, and in which order do the events fire? Assume the element is added by a state change and has a 300 ms duration.

    ```html
    <p transition:fade={{ duration: 300 }}
       onintrostart={() => console.log('is')}
       onintroend={() => console.log('ie')}
       onoutrostart={() => console.log('os')}
       onoutroend={() => console.log('oe')}>x</p>
    ```

    (State is toggled on, waited 500 ms, then toggled off.)

10. Find the bug: a custom transition returns ``css: (t) => `transform: scale(${t})` `` for an element that already has `transform: rotate(10deg)` in its stylesheet. What happens during the transition, and how do the built-in `fly` and `scale` avoid it?

11. What is a deferred transition, and when does the runtime evaluate the returned function? Describe in three sentences how `crossfade` uses this to pair elements.

12. In the todo-board example, what happens if a todo’s `out:send` registers a key but no `in:receive` with the same key appears in the same flush? What does the `fallback` receive as its third argument?

13. (Multiple choice) Which of these will make the Svelte compiler reject `animate:flip`?

    a.  The `{#each}` block has no key
    b.  The `<li>` is the only child of the each block
    c.  The same list is reordered
    d.  Parameters are passed with `animate:flip={{ delay: 500 }}`

14. A list item is added to the end of a keyed each block with `animate:flip` on its `<li>`. Does the new item animate? Do existing items? Explain.

15. Describe what `flip` computes (first, last, invert, play) and why its default duration is a function of distance.

16. What is the default easing and default duration for each of: `fade`, `fly`, `slide`, `blur`, `draw`, `Tween`? Which of them have no fixed default duration, and what are they derived from?

17. Why does `slide` emit the `transition_slide_display` warning for `<span transition:slide>`? What display values fix it?

18. A `Tween<string>` is set from `'red'` to `'blue'`. What does `current` do over time? What happens if you call `set('x')` on a `Tween<number>` (a type mismatch)?

19. What does `await tween.set(1)` do if another `tween.set(2)` is called 100 ms later while the first is still running? Contrast this with the same scenario for `Spring`.

20. Write a component using `Tween.of` that animates a displayed score when the `score` prop changes. Why must `Tween.of` be called during component initialisation (or in an effect root)?

21. A spring feels too wobbly. Which of `stiffness` and `damping` do you raise, and within what numeric range are these values clamped?

22. You are implementing a “drag and release” interaction. Which `Spring.set` option helps the element keep coasting after release, and in what unit is its value?

23. (Multiple choice) A page contains `* { transition-duration: 0s !important; animation-duration: 0s !important }` inside `@media (prefers-reduced-motion: reduce)`. A user with that preference loads a page with `transition:fly={{ y: 300 }}`. What happens?

    a.  The fly transition is skipped because the CSS zeroes durations
    b.  The fly transition plays normally because it uses the Web Animations API
    c.  Svelte detects the media query and disables all transitions automatically
    d.  The transition plays but without the opacity part

24. Implement `safeSlide` that falls back to a 100 ms `fade` when `prefersReducedMotion.current` is true. Give the TypeScript.

25. What is the default value of `intro` for `mount`? For `hydrate`? Which API do you use to play outros when removing a root, and what does it return?

26. You render a counter with `{#key count}<span in:fly out:fly>{count}</span>{/key}` and see the number jump sideways during the animation. Why, and what CSS change fixes it?

27. How would you write a unit test for a component with `out:fade` so that it needs no timers? Which two runtime facts make this possible?

28. Explain why every transition results in two `element.animate()` calls and what the first one is for.
