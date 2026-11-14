# Chapter 16: Testing and Debugging

Svelte is a compiler, which changes what “testing a component” means. There is no runtime interpreter of your template; there is JavaScript that a build step produced, and that JavaScript talks to a DOM. Everything you already know about testing applies, but three Svelte-specific facts decide whether your test suite is fast and trustworthy or slow and brittle: runes only exist after compilation (so test files that use them must be compiled too), effects run in a microtask (so tests must flush them deliberately), and components are plain functions that you mount into a target (so there is no component “instance” to poke at beyond what you export). This chapter builds a testing strategy around those facts, shows how to configure Vitest correctly, walks through unit, component, SSR, async and end-to-end tests, and then turns to the debugging toolbox: `$inspect`, `$inspect.trace`, `{@debug}`, `$state.snapshot`, and the catalogue of dev-time errors and warnings that Svelte emits when you break its rules.

All examples were run against Svelte 5.57.2 with Vitest, jsdom and `@testing-library/svelte` 5.x; outputs shown are real unless stated otherwise.

## A testing strategy that fits the framework

The official FAQ describes three kinds of tests: unit, component and end-to-end. The framework-specific twist is where you draw the first line.

```text
     few, slow, high confidence
          /  E2E (Playwright)  \
         /----------------------\
        /  component tests       \
       /  (mount + DOM assertions)\
      /----------------------------\
     /  unit tests of .svelte.ts    \
    /  modules (no DOM, no components)\
     many, fast, precise
```

The docs say it plainly: “not all logic belongs within a component — this includes concerns such as data transformation, cross-component state management, and logging”. With runes this advice becomes cheap to follow, because reactive state can live in `.svelte.ts` files. A class with `$state` fields or a function returning getters is testable without mounting anything. Components then become thin: they bind that logic to markup. Your component tests only need to verify the binding, not re-verify the logic.

A practical split for a typical application:

| Layer | What is tested | Tooling | Runs in |
|------------------|------------------|------------------|------------------|
| Unit | Reactive modules, pure helpers, stores, attachments as functions | Vitest | Node or jsdom |
| Component | Rendering, events, props, bindings, snippets, context | Vitest + jsdom or browser mode, optionally Testing Library | jsdom / real browser |
| Component (visual) | States and interactions of presentational components | Storybook + Vitest browser mode | real browser |
| SSR | Server output of a component | Vitest in a Node environment | Node |
| E2E | Whole application through a browser | Playwright | real browser |

Also heed the docs’ reminder: “the Svelte library has its own test suite, so you do not need to write tests to validate implementation details provided by Svelte.” Do not test that `$derived` recomputes; test that your price calculator produces the right total.

## Configuring Vitest

If you use Vite, Vitest reuses your Vite config and therefore your Svelte plugin. The documented manual setup is:

```bash
npm install -D vitest jsdom
```

```ts
// vite.config.ts
import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  // Use the `browser` entry points of packages, even though Vitest runs in Node
  resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined,
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts']
  }
});
```

Each piece matters:

- **`defineConfig` from `vitest/config`** types the `test` key. (If you keep the import from `vite`, the `test` property is a type error.)
- **`resolve.conditions: ['browser']`** is the subtle one. The `svelte` package has separate entry points for server and client. In Node, without the `browser` condition, `import { mount } from 'svelte'` resolves to the server build, where `mount` throws because it is not available on the server. Setting the condition only when `process.env.VITEST` is set (Vitest sets it) keeps your production build unaffected. The docs add a caveat: if loading the browser build of every package is undesirable (for instance you also test backend libraries in the same project), you may need aliases or separate Vitest projects instead.
- **`environment: 'jsdom'`** supplies `document`, `window`, and friends, which `mount` needs. If only some files need a DOM, leave the global environment alone and put `// @vitest-environment jsdom` at the top of those files.
- **The Svelte plugin** compiles `.svelte` files and, crucially, `.svelte.ts`/`.svelte.js` modules (which is where runes are enabled).

The Svelte CLI can set all of this up for you: `npx sv add vitest` during or after project creation, and `npx sv add playwright` and `npx sv add storybook` for the other layers.

### TypeScript and the `.svelte` infix

Runes are compiler syntax. `$state` in a plain `.ts` file is just an undeclared identifier, and at runtime it fails with the `rune_outside_svelte` error (“The `%rune%` rune is only available inside `.svelte` and `.svelte.js/ts` files”). Hence the rule: any file in which you want to use runes, including test files, must have `.svelte` in its name before the extension. Conventionally that is `thing.svelte.test.ts`. Plain `thing.test.ts` is fine as long as it does not itself use runes (it can still import runes-using modules, which are compiled in their own right).

### Browser mode as an alternative

jsdom is a simulation. It has no layout engine, no real focus handling edge cases, and, as we will see, no Web Animations API. Storybook’s testing integration runs components in Vitest’s browser mode, which uses a real browser, and you can configure Vitest browser mode yourself for plain component tests. The trade-off is speed and setup complexity versus fidelity. A common arrangement is jsdom for most component tests (fast feedback) and browser mode or Playwright for anything involving layout, focus order, real events or animation.

## Unit-testing reactive modules

Take a small helper in a `.svelte.ts` module. It takes a getter, so it works with whatever reactive state the caller passes in:

```ts
// src/lib/multiplier.svelte.ts
export function multiplier(getCount: () => number, k: number) {
  return {
    get value() {
      return getCount() * k;
    }
  };
}
```

The test file also ends in `.svelte.test.ts`, so it may use runes directly:

```ts
// src/lib/multiplier.svelte.test.ts
import { expect, test } from 'vitest';
import { multiplier } from './multiplier.svelte';

test('multiplier follows its source', () => {
  let count = $state(0);
  const double = multiplier(() => count, 2);

  expect(double.value).toBe(0);

  count = 5;
  expect(double.value).toBe(10);
});
```

No flush is needed here. Reading `double.value` re-reads `count` synchronously; nothing in this path is an effect. This is the key distinction to internalize for tests:

- **State and deriveds are synchronous and pull-based.** Write state, read the derived, get the new value.
- **Effects are asynchronous and push-based.** They run after a microtask. In tests you flush them manually with `flushSync()`.

Passing `() => count` rather than `count` is not a testing quirk; it is the normal rule for passing reactive values into functions (a plain number would capture the value at call time, and the compiler would warn with `state_referenced_locally`).

### Testing effects: `$effect.root` and `flushSync`

An `$effect` can only be created while a parent effect is running (inside a component or an effect root). A test function is neither, so creating an effect directly in it throws `effect_orphan`. The documented approach is to wrap the test body in `$effect.root`, flush with `flushSync`, and call the returned cleanup function at the end.

```ts
// src/lib/logger.svelte.ts
export function logger(getValue: () => unknown) {
  const log: unknown[] = [];
  $effect(() => {
    log.push(getValue());
  });
  return log;
}
```

```ts
// src/lib/logger.svelte.test.ts
import { flushSync } from 'svelte';
import { expect, test } from 'vitest';
import { logger } from './logger.svelte';

test('logger records every value', () => {
  const cleanup = $effect.root(() => {
    let count = $state(0);
    const log = logger(() => count);

    flushSync();
    expect(log).toEqual([0]);

    count = 1;
    flushSync();
    expect(log).toEqual([0, 1]);
  });

  cleanup();
});
```

Three details deserve emphasis.

1.  **The first `flushSync()` is what runs the effect initially.** Effects created in a root are scheduled, not executed inline. Without the flush, `log` is empty.
2.  **`cleanup()` matters.** An effect root has no parent to destroy it. If you skip the cleanup, effects created in one test stay alive, keep subscriptions, and can run again when a later test touches shared state. Use `try/finally` or `afterEach` if the body can throw before it reaches the cleanup, because an assertion failure inside the `$effect.root` callback will otherwise skip it.
3.  **Assertions inside `$effect.root` run synchronously within the callback.** That is fine, and a failing `expect` throws out of `$effect.root` normally.

A helper keeps this tidy:

```ts
// src/test/with-root.svelte.ts
export function withRoot(fn: () => void | Promise<void>) {
  return async () => {
    let result: void | Promise<void> = undefined;
    const cleanup = $effect.root(() => {
      result = fn();
    });
    try {
      await result;
    } finally {
      cleanup();
    }
  };
}
```

```ts
test('logger records every value', withRoot(() => { /* ... */ }));
```

Be aware that after an `await` inside the callback, you are outside the synchronous root context; the effects that were created before the `await` stay owned by the root, but any `$effect` you create afterwards would be orphaned. In practice, create all state and effects first, then await.

### `flushSync` semantics

`flushSync(fn?)` synchronously flushes pending updates. When you pass a callback, it runs it and then flushes. In 5.57.2 the changelog notes that anything pending is flushed before the callback is invoked. Two restrictions apply: it cannot be called inside an effect (error `flush_sync_in_effect`, enforced when the experimental async option is enabled and planned to be the default in Svelte 6), and calling it excessively defeats batching, so use it in tests, not in application code.

Compare with the other two scheduling helpers:

| Function | Resolves when | Use in tests for |
|------------------------|------------------------|------------------------|
| `flushSync()` | now (synchronously) | sync assertions after a state change or DOM event |
| `await tick()` | pending state changes have been applied (or on the next microtask) | when you are already in an async test and just need updates applied |
| `await settled()` (5.36+) | state changes and pending async work have resolved and the DOM is updated | testing components that use `await` expressions (experimental) or boundaries |

## Component tests with `mount`

A component is a function; `mount` calls it with an anchor inside the target and returns the component’s exports. Here is a small component with a callback prop and an effect:

```html
<!-- src/lib/Counter.svelte -->
<script lang="ts">
  let { initial = 0, onchange }: { initial?: number; onchange?: (n: number) => void } = $props();

  let count = $state(initial);

  $effect(() => {
    onchange?.(count);
  });
</script>

<button onclick={() => count++}>{count}</button>
```

(The compiler warns `state_referenced_locally` for `$state(initial)`: it captures the initial value deliberately here. Use `// svelte-ignore state_referenced_locally` if you want the warning gone.)

```ts
// src/lib/Counter.test.ts
import { flushSync, mount, unmount } from 'svelte';
import { expect, test } from 'vitest';
import Counter from './Counter.svelte';

test('Counter increments and reports changes', () => {
  const calls: number[] = [];

  const component = mount(Counter, {
    target: document.body,
    props: { initial: 3, onchange: (n) => calls.push(n) }
  });

  // Effects do not run during mount().
  expect(calls).toEqual([]);
  flushSync();
  expect(calls).toEqual([3]);

  document.body.querySelector('button')!.click();
  flushSync();

  expect(document.body.innerHTML).toBe('<button>4</button>');
  expect(calls).toEqual([3, 4]);

  unmount(component);
  expect(document.body.innerHTML).toBe('');
});
```

What happened:

- `mount` inserted DOM synchronously, so `document.body.innerHTML` is already `<button>3</button>` before any flush. The docs are explicit that “effects (including `onMount` callbacks, and action functions) will not run during `mount`”. Hence the `calls` array being empty until `flushSync()`.
- `button.click()` runs the event handler synchronously. Svelte delegates `click`, but jsdom’s `click()` dispatches a bubbling event, so delegation works. State changed, but the DOM update is scheduled in a microtask; `flushSync()` applies it.
- `unmount` removed the DOM and ran teardown functions. Because `unmount` returns a promise (it resolves after outros if `{ outro: true }`), in a test that does not use outros you can ignore it.

### Cleanup is your job

Without `@testing-library/svelte` there is no automatic cleanup. If you mount into `document.body` and forget to `unmount`, the next test sees leftovers. Options: create a fresh target per test, use `afterEach` to unmount everything you tracked, or reset `document.body.innerHTML = ''` (this removes DOM but not effects and listeners, so prefer `unmount`).

```ts
import { mount, unmount } from 'svelte';
import { afterEach } from 'vitest';

const mounted: Array<ReturnType<typeof mount>> = [];
export function mountTracked(...args: Parameters<typeof mount>) {
  const instance = mount(...args);
  mounted.push(instance);
  return instance;
}
afterEach(() => {
  while (mounted.length) unmount(mounted.pop()!);
  document.body.innerHTML = '';
});
```

### Reactive props in tests

`mount` takes a plain `props` object. If you want to change props after mounting, make the props object itself reactive: it is read through the same machinery as parent-supplied props.

```ts
const props = $state({ show: true });
const component = mount(Panel, { target: document.body, props });
flushSync();

props.show = false;   // behaves like the parent re-rendering with a new value
flushSync();
```

This works because `mount` treats `props` as an object whose properties are read lazily, which is the same mechanism `$props()` uses. The file needs `.svelte` in its name so that `$state` compiles. Testing Library’s `rerender` exists for the same purpose, but with direct `mount` this pattern is simpler and gives you actual reactive propagation rather than remounting.

## `@testing-library/svelte`

The docs show the same test written with Testing Library and `user-event`:

```ts
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { expect, test } from 'vitest';
import Counter from './Counter.svelte';

test('Counter, the user way', async () => {
  const user = userEvent.setup();
  render(Counter, { initial: 1 });

  const button = screen.getByRole('button');
  expect(button.textContent).toBe('1');

  await user.click(button);
  expect(button.textContent).toBe('2');
});
```

We ran this with `@testing-library/svelte` 5.4.2: it passes. Three points set it apart from raw `mount`:

1.  **Automatic cleanup** after each test, when your test runner exposes global `afterEach` (Vitest only does with `globals: true`; otherwise import and register the cleanup, or use the package’s Vitest setup entry per its README).
2.  **Queries by role, label and text** that mirror how users and assistive technology perceive the page. This pays double for Svelte because the compiler’s a11y checks and Testing Library queries push toward the same semantic markup (Chapter 17).
3.  **`user-event` is asynchronous and realistic.** It dispatches the full sequence (pointerdown, mousedown, focus, pointerup, click) with awaits between steps. The `await user.click()` gives Svelte’s microtask a chance to apply the update before the assertion, so you rarely need `flushSync` or `tick` explicitly. `fireEvent` from the library is also available; the library’s Svelte flavour awaits `tick()` for you.

If you assert text content on a node reference you obtained earlier (`button` above), that reference stays valid across updates: Svelte updates text in place rather than replacing nodes. This is a Svelte-specific advantage over frameworks that may remount.

### Wrapper components for context, bindings and snippets

The docs give one piece of advice about difficult cases: “When writing component tests that involve two-way bindings, context or snippet props, it’s best to create a wrapper component for your specific test and interact with that.” The reason is simple. Bindings (`bind:value`), snippets and context are template-level features; from JavaScript you cannot express `bind:` or a `{#snippet}`. A tiny `.svelte` file can.

**Snippets.** Given a component taking a `children` and an optional `footer` snippet:

```html
<!-- src/lib/Card.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    title,
    children,
    footer
  }: { title: string; children: Snippet; footer?: Snippet<[string]> } = $props();
</script>

<section>
  <h2>{title}</h2>
  {@render children()}
  {@render footer?.(title.toUpperCase())}
</section>
```

write a harness that supplies them:

```html
<!-- src/lib/Card.harness.svelte -->
<script lang="ts">
  import Card from './Card.svelte';
</script>

<Card title="hi">
  <p>body</p>
  {#snippet footer(t)}<em>{t}</em>{/snippet}
</Card>
```

```ts
test('Card renders both snippets', () => {
  const c = mount(CardHarness, { target: document.body });
  expect(document.body.innerHTML).toContain('<em>HI</em>');
  unmount(c);
});
```

For simple cases, you can build snippets in JavaScript with `createRawSnippet`, which returns a `Snippet` from a function that produces an HTML string for a single element:

```ts
import { createRawSnippet } from 'svelte';

const children = createRawSnippet(() => ({ render: () => '<p>body</p>' }));
mount(Card, { target: document.body, props: { title: 'hi', children } });
```

Use harnesses for anything with parameters that must be reactive or contain components; use `createRawSnippet` for quick static content.

**Bindings.** A harness can own the state and expose it to the test through a callback:

```html
<!-- src/lib/Input.svelte -->
<script lang="ts">
  let { value = $bindable('') }: { value?: string } = $props();
</script>

<input bind:value />
```

```html
<!-- src/lib/Input.harness.svelte -->
<script lang="ts">
  import Input from './Input.svelte';

  let { onvalue }: { onvalue: (v: string) => void } = $props();
  let value = $state('a');

  $effect(() => onvalue(value));
</script>

<Input bind:value />
<output>{value}</output>
```

```ts
test('bind:value flows up to the parent', () => {
  const seen: string[] = [];
  const c = mount(InputHarness, { target: document.body, props: { onvalue: (v) => seen.push(v) } });
  flushSync();

  const input = document.querySelector('input')!;
  input.value = 'xyz';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();

  expect(seen).toEqual(['a', 'xyz']);
  expect(document.querySelector('output')!.textContent).toBe('xyz');
  unmount(c);
});
```

Note that we dispatched `input` with `bubbles: true`. The listener that `bind:value` installs sits directly on the element (Chapter 8), so this particular test would pass without it, but an `oninput` attribute is delegated to the root and only fires for events that bubble. Make it a habit: hand-built events without `bubbles: true` are a common reason for “my handler never fires in the test”; `click()` and Testing Library take care of this for you.

**Context.** Since 5.49 you can mount a component with context by wrapping it in a function that sets context and then calls the component. A component is just a function, so the wrapper can be too:

```ts
// src/lib/context.ts
import { createContext } from 'svelte';

export interface User { name: string }
export const [getUser, setUser, hasUser] = createContext<User>();
```

```html
<!-- src/lib/Greeting.svelte -->
<script lang="ts">
  import { getUser } from './context';
  const user = getUser();
</script>

<h1>Hello {user.name}!</h1>
```

```ts
import { mount, unmount } from 'svelte';
import { expect, test } from 'vitest';
import { setUser } from './context';
import Greeting from './Greeting.svelte';

test('Greeting reads the user from context', () => {
  function Wrapper(...args: Parameters<typeof Greeting>) {
    setUser({ name: 'Bob' });
    return Greeting(...args);
  }

  const component = mount(Wrapper, { target: document.body });
  expect(document.body.innerHTML).toContain('Hello Bob!');
  unmount(component);
});
```

This passed in our run. The docs state that this approach “also works with `hydrate` and `render`”, and that the context set by the wrapper applies only to that mounted tree: each call creates a separate wrapper instance. There is also a `context` option on `mount` taking a `Map` for the older `setContext/getContext` keys. The `createContext` triplet returns `[get, set, has]` (the `has` element arrived in 5.57), and `get` throws `missing_context` when nothing was set, which is a useful failure to assert on:

```ts
expect(() => mount(Greeting, { target: document.body })).toThrow(/missing_context|Context was not set/);
```

The error text is produced by Svelte in dev mode, so assert on the code or message loosely.

## Testing asynchronous behaviour

### Promises and fake timers

Components that fetch in `{#await}` blocks or effects need the test to control time. Take a loader component:

```html
<!-- src/lib/Loader.svelte -->
<script lang="ts">
  let { load }: { load: () => Promise<string> } = $props();
  let promise = $derived(load());
</script>

{#await promise}
  <p>loading</p>
{:then value}
  <p>{value}</p>
{:catch error}
  <p role="alert">{error.message}</p>
{/await}
```

With Vitest’s fake timers:

```ts
import { flushSync, mount, tick, unmount } from 'svelte';
import { expect, test, vi } from 'vitest';
import Loader from './Loader.svelte';

test('Loader shows the result after the promise resolves', async () => {
  vi.useFakeTimers();
  try {
    const load = () => new Promise<string>((r) => setTimeout(() => r('done'), 1000));
    const c = mount(Loader, { target: document.body, props: { load } });

    flushSync();
    expect(document.body.textContent).toContain('loading');

    await vi.advanceTimersByTimeAsync(1000);
    await tick();
    expect(document.body.textContent).toContain('done');

    unmount(c);
  } finally {
    vi.useRealTimers();
  }
});
```

Use the async variant `advanceTimersByTimeAsync`: it lets promise continuations run between timers, and then `await tick()` lets Svelte apply the resulting DOM update. If you only use the synchronous `advanceTimersByTime`, the promise’s `then` callbacks have not run when you assert.

### Components using `await` expressions (experimental)

If you enable `compilerOptions.experimental.async` (see Chapter 13) and put `await` in markup or `$derived`, rendering becomes asynchronous in a deeper way: the DOM may not exist until promises resolve, pending UI shows in `<svelte:boundary>`’s `pending` snippet, and updates are batched until async work settles. In tests, `await settled()` (5.36+) is the right synchronisation point because it waits for both state changes and async work. The flag must be set in the config your tests use, which for Vitest is the same Svelte plugin config. Remember that `fork()` and `hydratable()` throw `experimental_async_required` at runtime when the app was not compiled with the flag, so tests of code using them will fail with that error in a project that forgot to enable it in the Vitest-facing config.

### Transitions in jsdom

Svelte drives transitions through the Web Animations API (`element.animate`), which jsdom does not implement. This is not merely “unreliable”: the first time a transition runs, the flush throws. In our run, toggling an `{#if}` that contained `transition:fade` failed inside `flushSync()` with `TypeError: element.animate is not a function`, raised from the runtime’s transition code. Your options:

1.  **Stub `Element.prototype.animate`** in a Vitest setup file. A minimal fake that finishes on the next microtask is enough for tests about logic:

```ts
// src/test/setup.ts (register under test.setupFiles)
import { beforeAll } from 'vitest';

beforeAll(() => {
  Element.prototype.animate = function () {
    const animation: any = {
      onfinish: null, oncancel: null, currentTime: 0, finished: Promise.resolve(),
      cancel() {}, pause() {}, play() {}, reverse() {}
    };
    queueMicrotask(() => animation.onfinish?.());
    return animation;
  } as any;
});
```

With this stub, hiding the block left the element in the DOM right after `flushSync()` (the outro is “running”) and removed it after a couple of microtasks (the fake animation finished), which is exactly the sequence you would assert on. Assert on both phases if the outro matters: present while the outro runs, gone afterwards.

2.  **Use browser mode or Playwright**, where `element.animate` is real, and assert on end states.
3.  **Make the component testable**: pass `duration` through props, or choose a zero-duration path with `prefersReducedMotion` (Chapter 11), so tests do not depend on timing.

Test the *state logic* that triggers a transition (the `{#if}` condition, the `show` prop) rather than animation frames. One more subtlety: local transitions (the default) play only when their own block is toggled, not when an ancestor is torn down. In our run, `unmount(component, { outro: true })` of a component whose only transition was a local `transition:fade` removed the element immediately. Use `|global` if you want it to play on teardown (Chapter 11).

### Actions, attachments, stores

Attachments and actions are functions of an element, so test them as such, or through a one-line harness:

```ts
// src/lib/attachments.svelte.ts
import type { Attachment } from 'svelte/attachments';

export const focusOnMount: Attachment<HTMLElement> = (el) => {
  el.focus();
  return () => {
    el.dataset.cleaned = '1';
  };
};
```

```html
<!-- src/lib/Focus.harness.svelte -->
<script lang="ts">
  import { focusOnMount } from './attachments.svelte';
</script>

<input {@attach focusOnMount} />
```

```ts
test('focusOnMount focuses the element', () => {
  const c = mount(FocusHarness, { target: document.body });
  flushSync();
  expect(document.activeElement).toBe(document.querySelector('input'));
  unmount(c);
});
```

The `flushSync()` matters: attachments run inside an effect, so they do not execute during `mount`. One caveat for jsdom: `focus()` only works when the element is attached to the document, which it is here because the target is `document.body`.

Stores need no special tooling: `get(store)` from `svelte/store` reads the current value; or subscribe in the test. Test custom stores against the contract: `subscribe` calls the callback synchronously with the current value, and returns an unsubscribe function. For a `writable` with a start function, test that the start function runs on the first subscription and the stop function on the last unsubscription.

```ts
import { get, writable } from 'svelte/store';

test('start/stop notifier lifecycle', () => {
  const events: string[] = [];
  const store = writable(0, () => {
    events.push('start');
    return () => events.push('stop');
  });

  const unsubA = store.subscribe(() => {});
  const unsubB = store.subscribe(() => {});
  expect(events).toEqual(['start']);
  unsubA();
  expect(events).toEqual(['start']);
  unsubB();
  expect(events).toEqual(['start', 'stop']);
  expect(get(store)).toBe(0);   // subscribes and unsubscribes again
  expect(events).toEqual(['start', 'stop', 'start', 'stop']);
});
```

## Testing server-side rendering

SSR output is testable without a DOM using `render` from `svelte/server`:

```ts
// src/lib/Counter.ssr.test.ts
// @vitest-environment node
import { render } from 'svelte/server';
import { expect, test } from 'vitest';
import Counter from './Counter.svelte';

test('Counter renders its initial value on the server', () => {
  const { body, head } = render(Counter, { props: { initial: 7 } });
  expect(body).toContain('>7</button>');
});
```

The actual `body` in our run was `<!--[--><button>7</button><!--]-->` and `head` was empty. The hydration marker comments are part of the contract (do not strip them if you will hydrate), so match with `toContain` or a regex rather than strict equality, since markers are an implementation detail.

The `// @vitest-environment node` line is essential, and the reason is a trap worth understanding. With the global jsdom environment and `resolve.conditions: ['browser']`, the Svelte plugin compiles `Counter.svelte` for the **client**, because Vitest treats a jsdom environment as a browser-like (web) transform target. Calling `render()` on a client-compiled component runs client code on the server renderer. In our run, the same test without the pragma failed with:

    Svelte error: effect_orphan
    `$effect` can only be used inside an effect (e.g. during component initialisation)

because `Counter` contains an `$effect` and the client runtime’s effect machinery was invoked outside a client component context. Components without effects may appear to work and then hide the mismatch. With the node environment the plugin compiles for the server and the test passes. If you have many SSR tests, use a separate Vitest project (or `workspace`/`projects` configuration) for them, so the client and server compilation targets are never mixed.

`render` returns an object that is both synchronous (`head`, `body`) and `PromiseLike`; synchronous access works unless the component has async work. A synchronous `render` of a component containing `await` throws `await_invalid`; use `await render(...)` in that case (and note that async SSR requires `AsyncLocalStorage`). The `html` property is deprecated in favour of `body`.

For hydration tests, render on the server, put `body` into the document, and call `hydrate`; mismatches show up as the `hydration_mismatch` warning (see below). This is the most reliable way to catch “works on the client, breaks after SSR” bugs such as the browser-repaired HTML that the compiler warns about with `node_invalid_placement_ssr`.

## Storybook component tests

Storybook runs stories through Vitest’s browser mode, so the tests run in a real browser. Install with `npx sv add storybook` and pick the recommended configuration that includes testing. Stories are written with `@storybook/addon-svelte-csf`, in a Svelte syntax: `defineMeta` in the module script, and `<Story>` components. The `play` function simulates user interaction and asserts:

```html
<!-- src/lib/LoginForm.stories.svelte -->
<script module>
  import { defineMeta } from '@storybook/addon-svelte-csf';
  import { expect, fn } from 'storybook/test';

  import LoginForm from './LoginForm.svelte';

  const { Story } = defineMeta({
    component: LoginForm,
    args: {
      // Pass a mock function to the `onSubmit` prop
      onSubmit: fn()
    }
  });
</script>

<Story name="Empty Form" />

<Story
  name="Filled Form"
  play={async ({ args, canvas, userEvent }) => {
    await userEvent.type(canvas.getByTestId('email'), 'email@provider.com');
    await userEvent.type(canvas.getByTestId('password'), 'a-random-password');
    await userEvent.click(canvas.getByRole('button'));

    await expect(args.onSubmit).toHaveBeenCalledTimes(1);
    await expect(canvas.getByText('You’re in!')).toBeInTheDocument();
  }}
/>
```

This is the docs’ example. Stories double as documentation and as a visual catalogue, and the fact that the stories are real components means the “wrapper for snippets and context” problem is solved by writing the wrapper once as a story (decorators supply context). The cost is another toolchain to maintain; it pays off for design-system style libraries and less so for application glue.

## End-to-end tests with Playwright

E2E tests are, in the docs’ words, “totally unaware of Svelte as a framework”. They load the built app and drive it through the DOM. Configure Playwright to build and serve the app before running:

```ts
// playwright.config.ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  webServer: {
    command: 'npm run build && npm run preview',
    port: 4173
  },
  testDir: 'tests',
  testMatch: /(.+\.)?(test|spec)\.[jt]s/
});
```

```ts
// tests/home.spec.ts
import { expect, test } from '@playwright/test';

test('home page has expected h1', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('h1')).toBeVisible();
});
```

Svelte-specific advice for E2E:

- **Test the production build.** `npm run build && npm run preview` exercises minification, tree-shaking and the production runtime (where `$inspect` is a no-op, dev warnings are gone and `dev`-only checks do not exist). A dev server hides a class of bugs.
- **Prefer role- and label-based locators** (`page.getByRole('button', { name: 'Save' })`), for the same reasons as Testing Library. Never select on Svelte’s scoped class names (`svelte-1abc23`): the hash is derived from the file name or CSS and will change.
- **Wait for hydration when relevant.** If the page is server-rendered, the markup exists before event handlers are attached. A test that clicks immediately can race the hydration. Gate interaction on something your app sets after mount (for example a `data-hydrated` attribute set from an `$effect` or `onMount`), or use Playwright’s auto-waiting on an element that only becomes enabled after hydration.
- **Accessibility checks belong here too**: `@axe-core/playwright` can run axe against the rendered page (Chapter 17).

## The debugging toolbox

### `$inspect`

`$inspect(...values)` logs its arguments initially and whenever any of them change, tracking *deeply*: mutating a nested property of a `$state` object re-fires it. It only works in development; in a production build it is a no-op. On updates it prints a stack trace, so you can see which code changed the value.

```html
<script lang="ts">
  let count = $state(0);
  let obj = $state({ a: { b: 1 } });

  $inspect(count, obj);
</script>
```

`.with(callback)` replaces `console.log`. The callback receives `'init'` or `'update'` followed by the values, which makes conditional breakpoints easy:

```html
<script lang="ts">
  let count = $state(0);

  $inspect(count).with((type, value) => {
    if (type === 'update' && value > 3) {
      debugger;
    }
  });
</script>
```

We verified the call sequence with a component that does `$inspect(count, obj).with(...)` and a test that increments `count` and then `obj.a.b`: the callback saw `init` with `(0, {a:{b:1}})`, then `update` with `(1, {a:{b:1}})`, then `update` with `(1, {a:{b:2}})`. The nested mutation re-fired, as documented.

Because `$inspect` is deep, inspecting a huge structure is expensive: it traverses everything on every change. Treat it as a scalpel. Also remember it cannot change state: updating state inside `$inspect(...)` is forbidden (`state_unsafe_mutation`).

### `$inspect.trace`

Added in 5.14. `$inspect.trace(label?)` must be the first statement in a function body. Whenever that function re-runs as part of an effect or a derived, Svelte logs which pieces of reactive state caused the re-run (5.34 added logging of source names). It answers the question “why did this effect run?”, which `$inspect` cannot.

```html
<script lang="ts">
  let { items, filter }: { items: string[]; filter: string } = $props();

  let visible = $derived.by(() => {
    $inspect.trace('visible');
    return items.filter((i) => i.includes(filter));
  });

  $effect(() => {
    $inspect.trace('sync visible count');
    document.title = `${visible.length} items`;
  });
</script>
```

The placement rule is enforced by the compiler (`inspect_trace_invalid_placement`), and it cannot be used in generator functions (`inspect_trace_generator`). It is dev-only like `$inspect`. Use it to diagnose over-firing effects and to confirm that a `$state.raw` or derived equality cut-off works as you expect (Chapter 18 builds on this).

### `{@debug}`

```html
{@debug user}
{@debug user1, user2}
```

`{@debug ...}` logs the listed variables whenever they change and pauses execution if devtools are open. It accepts only identifiers: `{@debug user.firstname}` and `{@debug !isReady}` do not compile. A bare `{@debug}` inserts a `debugger` statement that triggers whenever *any* state in the component changes, which is a crude but effective way to find out which component re-renders. `{@debug}` sits in the template, which makes it useful for “what is this snippet seeing?” questions that script-level `$inspect` cannot easily answer.

### Logging state: `$state.snapshot` and `console_log_state`

`console.log(someState)` in the browser shows a `Proxy`, and the proxy’s target may not resemble the current value (Svelte keeps signals for the properties separately). Svelte warns in dev: in our run, logging a `$state` array produced

    [svelte] console_log_state
    Your `console.log` contained `$state` proxies. Consider using `$inspect(...)` or `$state.snapshot(...)` instead

Either use `$inspect` to log over time, or `console.log($state.snapshot(items))` for a one-off, which produces a plain deep clone. `$state.snapshot` uses `structuredClone` semantics, honours `toJSON`, and returns uncloneable parts as-is with a `state_snapshot_uncloneable` warning. It is also the right tool before sending state to APIs that do not like proxies (`structuredClone`, `postMessage`, IndexedDB).

### The dev-only checks

Compiling with `dev: true` (Vite’s dev server does this) adds runtime validation. These checks are the second half of the debugging toolbox because they turn silent logic errors into named, linkable messages. A message looks like `Svelte error: effect_orphan` or `[svelte] console_log_state` and ends with a URL, `https://svelte.dev/e/<code>`, which opens the documentation page for that exact code. The code names use underscores. In production builds the checks are stripped, so never rely on an error being thrown for control flow.

## Reading Svelte’s error and warning catalogue

Svelte has four families, distinguished by where they are raised:

- **Compile errors and warnings**: emitted by the compiler (`compile()` returns `warnings`; errors throw). They show in the editor via `svelte-check` and in Vite’s console. Examples: `state_referenced_locally`, `a11y_*`, `css_unused_selector`.
- **Client errors/warnings**: thrown or logged by the client runtime in the browser: `effect_orphan`, `state_unsafe_mutation`, `hydration_mismatch`.
- **Server errors/warnings**: from `svelte/server` rendering: `await_invalid`, `invalid_csp`, `dynamic_element_invalid_tag`.
- **Shared**: raised on both sides: `lifecycle_outside_component`, `missing_context`, `snippet_without_render_tag`, `state_snapshot_uncloneable`.

Here are the failures you will meet most, with causes and cures.

### `effect_orphan`

“`$effect` can only be used inside an effect (e.g. during component initialisation)”. Effects must be created while a parent effect is running. Cases: calling `$effect` inside an event handler; after an `await` inside an async function (a top-level `await` in the component script is exempt); in a unit test without `$effect.root` (as we saw above); or in a module called outside component initialisation. Fix: move the call to component init, use `$effect.root` for intentionally unowned effects, or restructure so that the effect is created up front.

### `state_unsafe_mutation`

“Updating state inside `$derived(...)`, `$inspect(...)` or a template expression is forbidden.” The docs’ canonical example computes two pieces of state in one derived:

```html
<script lang="ts">
  let count = $state(0);
  let even = $state(true);

  // throws state_unsafe_mutation when the derived is evaluated
  let odd = $derived.by(() => {
    even = count % 2 === 0;
    return !even;
  });
</script>
```

We reproduced it: mounting this component and flushing throws `state_unsafe_mutation`. The remedy is to derive everything: `let even = $derived(count % 2 === 0); let odd = $derived(!even);`. If a side effect is truly needed, use `$effect`.

### `effect_update_depth_exceeded`

“Maximum update depth exceeded. This typically indicates that an effect reads and writes the same piece of state.” The classic is `$effect(() => { count += 1 })`. Array mutations such as `array.push(...)` both read and write. An effect that re-runs but settles is fine (sorting an already-sorted array). Usually the fix is that the value should not be `$state` at all (a log array pushed to in an effect), or that the read should be wrapped in `untrack`. The runtime gives up after a fixed number of flush iterations (about a thousand in the source we inspected; an internal detail).

### `ownership_invalid_mutation` and `ownership_invalid_binding`

A child that mutates an object it received as a prop, when the owning parent did not mark it `bind:`/`$bindable`, triggers the warning “Mutating unbound props … is strongly discouraged”. The cure is a callback prop or an explicit `$bindable`. `ownership_invalid_binding` is the sibling: a grandparent passes a value to a parent as a plain prop (no `bind:`), and the parent binds it onward into a child with `bind:`. Make the chain explicit (`$bindable` in the parent and `bind:` in the grandparent), or use a callback. These are dev-only and based on tracking which component created a `$state` proxy.

### `hydration_mismatch` and friends

“Hydration failed because the initial UI does not match what was rendered on the server.” Svelte walks the server HTML expecting the same structure the client would build. Causes: HTML that the browser repaired (a `<div>` inside `<p>`, `<table>` without `<tbody>`), conditional rendering based on `typeof window`, `Date.now()`/`Math.random()` in markup, browser extensions injecting nodes, or stripping the hydration comments from the HTML. In development a preceding `console.error` shows the offending HTML. Related: `hydration_attribute_changed` (for attributes such as `src` that are deliberately not repaired) and `hydration_html_changed` (for `{@html}`). Both are fixed by making server and client values identical, or by the “stash, unset, restore in `$effect`” trick that the docs show. Also note that the compiler’s `node_invalid_placement_ssr` warning exists precisely to catch repaired-HTML structures statically.

### The lifecycle and snippet errors

- `lifecycle_outside_component`: “`onMount(...)` can only be used during component initialisation”. Call it at the top level of the script, not in a handler.
- `lifecycle_legacy_only`: `beforeUpdate`/`afterUpdate` cannot be used in runes mode. Use `$effect.pre`/`$effect`/`tick`.
- `invalid_snippet`: `{@render snippet()}` when the snippet is `null`/`undefined`; write `{@render snippet?.()}` for optional snippets.
- `snippet_without_render_tag`: you wrote `{children}` instead of `{@render children()}`.
- `missing_context`: `get` from `createContext` ran with no matching `set` in an ancestor.
- `props_invalid_value`: `bind:value={undefined}` against a prop with a `$bindable` fallback.
- `props_rest_readonly`, `bind_not_bindable`, `bind_invalid_export`: binding mistakes (Chapters 7 and 8).
- `each_key_duplicate` and `each_key_volatile`: keyed `{#each}` problems (Chapter 6).
- `derived_references_self`: a derived that reads itself.
- `rune_outside_svelte`: runes in a plain `.ts`/`.js` file (rename to `.svelte.ts`).
- `state_proxy_equality_mismatch`: comparing a `$state` proxy with `===` against the raw object it was created from.
- `svelte_boundary_reset_noop` / `svelte_boundary_reset_onerror`: misuse of `reset` in boundaries.

A habit that pays off: when you see a Svelte error in the console, click the link. The docs for each code include the fix, and several (for example `state_unsafe_mutation` and `effect_update_depth_exceeded`) are essentially short tutorials.

### Silencing warnings responsibly

`<!-- svelte-ignore code (reason) -->` before the next block of markup disables the named warnings for it; in `<script>` use a `// svelte-ignore code` comment before the statement. Multiple codes are comma-separated, and the explanation in parentheses is accepted by the parser as a documented reason (the docs’ “unknown_code” check also validates that the code exists, with a “did you mean” suggestion for typos). Use it with a reason and sparingly; it is an assertion that you understand why the warning is wrong in this one place. To filter warnings globally in a build, use the `warningFilter` compiler option (return `true` to keep a warning). Chapter 17 discusses this for accessibility warnings.

## Source maps, HMR and DevTools

**Source maps.** Svelte always generates source maps (the old `enableSourcemap` option was removed), and `compile()` returns `js.map` and `css.map`. Vite chains them, so browser devtools and Vitest stack traces show the original `.svelte` lines (the stack traces we saw above referenced `Counter src/Counter.svelte:4:3`). TypeScript-in-Svelte goes through the preprocessor first, so make sure the preprocessor emits a map too; the standard `vitePreprocess` does.

**HMR.** The compiler has an `hmr` option (default `false`) that makes components hot-swappable by wrapping them so that the module can be replaced without a full reload. In a Vite setup, `@sveltejs/vite-plugin-svelte` turns this on for the dev server; you do not set it by hand. State inside a hot-replaced component is reset to its initial values, while module-level state in `.svelte.ts` files follows normal module HMR rules, so if you experience “stale” state after an edit, a full reload is the quick test for whether HMR is involved.

**DevTools.** There is a community browser extension for inspecting Svelte component trees, but with Svelte 5 the most reliable tools are the ones in this chapter. Rely on `$inspect`, `$inspect.trace` and `window.__svelte` (the compiler option `discloseVersion`, default `true`, adds the Svelte major version to a `Set` at `window.__svelte.v`, which is handy for confirming which Svelte majors are loaded on a page, for example when two copies end up in a bundle).

## Debugging recipes

**“Why is this component re-rendering?”** Put `{@debug}` (bare) at the top of the template: it breaks whenever any state of that component changes. Or put `$inspect.trace()` inside the suspicious effect or derived.

**“The UI did not update.”** Check in this order: (1) Is the variable declared with `$state`? The compiler warns `non_reactive_update` for reassigned, non-state variables read in the template. (2) Did you destructure reactive values (`let { a } = obj` copies; use `obj.a` or `$derived`)? (3) Did you reassign a state object that was shared through context or an export, breaking the link (Chapter 12)? (4) Is a raw value (`$state.raw`) being mutated instead of reassigned? (5) Did the mutation happen on a non-proxied class instance without `$state` fields?

**“My effect runs too often / not at all.”** `$inspect.trace()` tells you the first; for the second, remember dependencies are only those *read synchronously in the last run*: reads after an `await` or inside `setTimeout` are not tracked, and a conditionally-skipped read is not a dependency on that run.

**“Works in dev, breaks in production.”** Run the production preview (`vite build && vite preview`). Differences include `$inspect` being a no-op, dev warnings absent, and minifier-related issues with code that depends on function names.

**“Works on the client, breaks after SSR.”** Write a hydration test (render, insert, hydrate) and read the `hydration_mismatch` console output. Look for `window`-dependent initial state in `$state(...)` and for non-deterministic values in markup.

## Putting it together: a testing checklist

1.  Extract logic into `.svelte.ts` modules; test them with plain Vitest, using runes in `.svelte.test.ts` files.
2.  Use `$effect.root` + `flushSync` + cleanup for anything that creates effects outside a component.
3.  Test components through `mount` or Testing Library; query by role.
4.  Use harness components for bindings, snippets and context; use the `Wrapper` function for context only.
5.  Use `await tick()`/`await settled()` and fake timers for asynchronous flows; do not assert on animations in jsdom.
6.  Run SSR tests in a Node environment with `render`; add a hydration test for pages that matter.
7.  Put a handful of E2E tests against the production build in Playwright.
8.  Make warnings fail CI: run `svelte-check` (via `npx sv check`) in your pipeline so compiler warnings are visible, and consider treating specific warnings as errors through your build’s warning handling.

## Key takeaways

- Put logic into `.svelte.ts` modules so most tests are pure unit tests; components should be thin bindings.
- Runes only compile in files with `.svelte` in the name, including test files (`*.svelte.test.ts`); otherwise you get `rune_outside_svelte`.
- Vitest needs `vitest/config`, `resolve.conditions: ['browser']` (only under `process.env.VITEST`) and `environment: 'jsdom'` for client tests.
- State and deriveds update synchronously; effects need `flushSync()`. Effects in tests require `$effect.root` and a call to the returned cleanup.
- `mount` does not run effects, `onMount` or attachments; call `flushSync()`. Always `unmount` (or use Testing Library’s automatic cleanup).
- Use a reactive `$state` props object to change props after mounting; use harness components for bindings, snippets and context; use a wrapper function for context via `mount`.
- SSR tests need a Node environment, otherwise the component is compiled for the client and fails (for instance with `effect_orphan`).
- jsdom has no Web Animations API; test transition logic, not animation frames, or move to browser mode/Playwright.
- `$inspect` is deep and dev-only; `$inspect.trace` explains why an effect or derived re-ran; `{@debug}` is the template-level equivalent; `$state.snapshot` makes proxies loggable.
- Svelte error and warning codes link to `https://svelte.dev/e/<code>`; learn the common ones: `effect_orphan`, `state_unsafe_mutation`, `effect_update_depth_exceeded`, `ownership_invalid_mutation`, `hydration_mismatch`.

## Review Questions

1.  Why must a test file that uses `$state` have `.svelte` in its filename? What error appears if it does not?
2.  Explain why `resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined` is written conditionally rather than unconditionally.
3.  Which of these needs `flushSync()` before you can assert on it: (a) reading a `$derived` after writing its source state, (b) the text content of a DOM node after writing state, (c) the value pushed by an `$effect`? Justify each.
4.  What does this test print, and why?

    ```ts
    test('x', () => {
      const calls: number[] = [];
      const c = mount(Counter, { target: document.body, props: { initial: 3, onchange: (n) => calls.push(n) } });
      console.log(calls.length);
      flushSync();
      console.log(calls.length);
      unmount(c);
    });
    ```

5.  Find the bug in this test and fix it:

    ```ts
    test('logs', () => {
      let count = $state(0);
      const log = logger(() => count);   // logger uses $effect internally
      count = 1;
      flushSync();
      expect(log).toEqual([0, 1]);
    });
    ```

6.  Why must the callback in `$effect.root` be followed by a call to the returned function, and what can go wrong if an assertion inside the root throws before cleanup?
7.  A colleague mounts a component in `beforeEach` without unmounting. Describe two kinds of cross-test contamination this can cause.
8.  How do you change a prop after mounting a component with `mount`? Show the code, and say what must be true of the test file.
9.  Multiple choice: which statement about `await user.click(button)` from `@testing-library/user-event` is true?
    a.  It runs synchronously, so a following assertion needs `flushSync`.
    b.  It awaits long enough for Svelte’s microtask update to complete before your next assertion.
    c.  It bypasses event delegation.
    d.  It requires `fake timers` to be enabled.
10. Why does a hand-written `new Event('input')` dispatched on an `<input>` sometimes fail to trigger a Svelte handler, while `input.click()` for a click works?
11. Describe the wrapper-function technique for providing context to a component under test. What did Svelte 5.49 add, and what is the lifetime of the context?
12. You need to test a component that takes a `footer` snippet with a parameter. Give two ways of supplying it from a test and say when you prefer each.
13. What does `get(store)` do under the hood, and why can it be a problem in hot paths?
14. A test of `render(Component)` from `svelte/server` fails with `effect_orphan` under a jsdom + browser-conditions Vitest config. Explain the cause and give two fixes.
15. Why is it risky to assert `expect(body).toBe('<button>7</button>')` on the output of `render`?
16. What does `vi.advanceTimersByTimeAsync` give you over `advanceTimersByTime` when testing a promise-based loader, and why do you still need `await tick()`?
17. In jsdom, what happens when a Svelte transition first runs, and why? Give two strategies for dealing with it in a test suite.
18. A local `transition:fade` is on an element inside an `{#if}`. You call `unmount(component, { outro: true })`. Does the outro play? How would you change that?
19. Multiple choice: `$inspect(items)` where `items` is a `$state` array and you call `items.push(4)`. Which is correct?

    a.  `$inspect` does not re-run because the array identity is unchanged.
    b.  `$inspect` re-runs, because it tracks state deeply.
    c.  It re-runs only when you pass `.with(...)`.
    d.  It throws `state_unsafe_mutation`.

20. What does `$inspect(x).with((type, v) => ...)` receive as `type` values, and how can you use that for debugging?
21. What are the placement rules for `$inspect.trace()`, and what question does it answer that `$inspect` does not?
22. Which of these compile: `{@debug user}`, `{@debug user.name}`, `{@debug a, b}`, `{@debug !ok}`, `{@debug}`? What does the last one do?
23. Why does `console.log(state)` of a `$state` object produce a warning, and what are the two recommended alternatives?
24. Find the bug and explain the resulting error:

    ```html
    <script lang="ts">
      let count = $state(0);
      let even = $state(true);
      let odd = $derived.by(() => { even = count % 2 === 0; return !even; });
    </script>
    ```

25. A child component does `<input bind:value={person.name}>` on a `person` prop passed as `<Child {person} />`. Which warning appears and what are two ways to fix it?
26. List three common causes of `hydration_mismatch` and one way to find the offending markup in development.
27. Why should E2E tests run against `npm run build && npm run preview` rather than the dev server?
28. What is the purpose of the parenthesised text in `<!-- svelte-ignore a11y_autofocus (focus is moved intentionally into the dialog) -->`, and which compiler option filters warnings globally?
