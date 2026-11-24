# Final Tests

Three cumulative tests, 25 questions each. Take each one closed book in **30 minutes**, then check “Final Tests: Answer Key”. A score of 20 or more is a good sign for the interview; under 15, re-read the core notes of the days listed for that test below, then retry the questions you missed.

- **Test 1:** Svelte 5 (Days 1–2)
- **Test 2:** SvelteKit (Days 3–5)
- **Test 3:** Testing, SvelteKit 3 and the live-coding workflow (Days 6–7 and the playbook)

## Test 1: Svelte 5

1. Multiple choice: in Svelte 5, when the value of a `$state` variable changes…

   a. the whole component function runs again
   b. a virtual DOM diff decides what to patch
   c. only the effects and template expressions that read it are updated
   d. nothing happens until `tick()` is called

2. Which of these files can use `$state`? (Choose all that apply.)

   a. `Button.svelte`  b. `cart.svelte.ts`  c. `cart.ts`  d. `cart.svelte.spec.ts`

3. **What does this log after the button is clicked once?**

   ```html
   <script lang="ts">
   	let count = $state(1);
   	let double = $derived(count * 2);
   	function click() {
   		count++;
   		console.log(double);
   	}
   </script>
   <button onclick={click}>+</button>
   ```

4. **Find the bug:**

   ```html
   <script lang="ts">
   	let { items } = $props();
   	let total = $state(0);
   	$effect(() => {
   		total = items.reduce((s, i) => s + i.price, 0);
   	});
   </script>
   <p>Total: {total}</p>
   ```

5. Why is `$state.raw` a better choice than `$state` for a list of 10,000 rows that you replace after every fetch?
6. A class has `count = $state(0)` and `inc() { this.count++; }`. The template uses `<button onclick={counter.inc}>`. What goes wrong, and what is the fix?
7. Write the Svelte 5 equivalent of a Svelte 4 component with `export let label;` and `dispatch('select', id)`.
8. What does `$bindable()` mean for a prop, and how does a parent use it?
9. Show how a `List` component can let its parent decide how each item is rendered.
10. Multiple choice: which is **not** a valid reason to use `$effect`?

    a. Drawing on a `<canvas>` when data changes
    b. Computing a filtered list from a search query
    c. Subscribing to a WebSocket and unsubscribing on destroy
    d. Sending an analytics event when a value changes

11. What does the function returned from an `$effect` callback do, and when does it run?
12. **What is wrong?** `{#each todos as todo, i (i)}`
13. A child component does `props.user.name = 'x'` on an object passed by the parent. What does Svelte do in development, and what is the right pattern?
14. Which of these run during SSR? `onMount`, `$derived`, `$effect`, `onDestroy`, an `onclick` handler, the `<script>` body.
15. Give two causes of a hydration mismatch.
16. Why can a module `export let theme = $state('light')` that is reassigned elsewhere not work, and what are two alternatives?
17. You put a `$state` object in context in a layout and later reassign the variable to a new object. Children keep showing the old values. Why?
18. Why is `{@html userBio}` dangerous, and what would you do instead or in addition?
19. You want to wrap a chart library around a `<canvas>` and redraw the chart when its data prop changes. Write the attachment.
20. With `bind:group`, what do radio buttons and checkboxes produce?
21. In runes mode, why should you bind to `todo.done` rather than to the each-block variable itself?
22. What does `$props.id()` give you, and why is it useful for accessibility?
23. Multiple choice: which replaces `<slot name="footer" {title} />`?

    a. `{@render footer?.(title)}`
    b. `<svelte:slot name="footer" />`
    c. `{#slot footer}`
    d. `{@html footer(title)}`

24. What is the `effect_update_depth_exceeded` error, and what typically causes it?
25. **Design:** you need a “shopping cart” shared by the header and the product pages in a SvelteKit app with SSR. Where does the state live, and why not in a plain module singleton?

## Test 2: SvelteKit

1. Multiple choice: what happens on the first request to a page in a default SvelteKit app?

   a. The server renders HTML, the browser hydrates it, and later navigations are client-side
   b. An empty shell is sent and the browser renders everything
   c. The page is always prerendered at build time
   d. Every navigation is a full server round trip

2. Name each file’s role: `+page.ts`, `+page.server.ts`, `+layout.svelte`, `+server.ts`, `+error.svelte`.
3. Which URL does `src/routes/(app)/docs/[...path]/+page.svelte` serve, and what is `params.path` for `/docs/a/b`?
4. A matcher rejects a segment. What happens next in the routing?
5. Give the rule for choosing between a server and a universal `load`, with one example of each.
6. **Find the bug:**

   ```ts
   // +page.server.ts
   export const load = async ({ params }) => {
   	const user = await db.users.find(params.id);
   	return { user };
   };
   ```

7. A route has `+page.server.ts` returning `{ a: 1 }` and `+page.ts` returning `{ b: 2 }`. What is `data` in the page?
8. When does a `load` function that reads `url.searchParams.get('page')` re-run?
9. What is a waterfall in `load`, and how do you avoid one when you need `parent()`?
10. **What is wrong?** A layout server load redirects anonymous users, and the page server load returns private data without any check.
11. Write a form action that validates a required `email` field and returns a 400 failure with the submitted value.
12. List what `use:enhance` does by default after a successful submission.
13. In which order do action, loads and render happen when a form is posted to a page?
14. What does `fail()` return versus what `error()` does?
15. Which requests pass through `handle`? Which do not?
16. **Write** a `handle` that sets `event.locals.user` from a `sid` cookie using a function `getUser(sid)`.
17. With `sequence(a, b, c)`, what is the order of the code after `await resolve(event)`?
18. Where is `+error.svelte` not used, and what is shown instead?
19. What do `prerender`, `ssr = false` and `csr = false` each do? Give a use case for each.
20. Why can’t a page with actions be prerendered?
21. **Find the bug** (Node server, many users): `// src/lib/server/state.ts  export let lastSearch = '';` written in a load and read in the page.
22. Where should the current sort order of a product table live, and how do you update it?
23. How do you show a loading indicator during client-side navigation in SvelteKit 3?
24. Why can’t `src/routes/+page.svelte` import `#lib/server/db.js`, and when is that detected?
25. **Design:** a product page needs the product (essential, SEO-relevant) and reviews (slow, secondary). Sketch the `load` and the markup.

## Test 3: Testing, SvelteKit 3 and Live Coding

1. Name the three test levels, a tool for each, and what each one proves.
2. In the scaffolded Vitest config, which project runs `src/lib/Foo.svelte.spec.ts`, and in what environment? And `src/lib/foo.spec.ts`?
3. What error do you get if a test file without `.svelte` in its name uses `$state`?
4. Write a component test for a `Toggle.svelte` that renders a button labelled by its `label` prop, with `aria-pressed` that flips on click and an `onchange(pressed)` callback.
5. What is the difference between `expect(...)` and `await expect.element(...)` in Vitest browser mode?
6. How do you pass a `children` snippet to a component from a test?
7. How do you test a component that imports `page` from `$app/state`?
8. Write the assertion that an async `load` threw `error(404)`.
9. How do you call a form action from a unit test? Sketch the code.
10. How do you unit test a helper that calls `getRequestEvent()`?
11. **What is wrong with this e2e test?**

    ```ts
    await page.goto('/todos');
    await page.waitForTimeout(1000);
    await page.locator('.btn-primary').click();
    expect(await page.locator('li').count()).toBe(1);
    ```

12. Why does Playwright run against `npm run build && npm run preview`?
13. Write a Playwright test (or describe block) that proves the guestbook form works without JavaScript.
14. What is the hydration race, and what are two ways to deal with it?
15. Why might `page.route()` not affect the data shown on a server-rendered page?
16. Name five things you check when reviewing code generated by Claude Code for a Svelte 5 / SvelteKit 3 project.
17. What would you put in a `CLAUDE.md` before the live-coding exercise, and why?
18. How do you show the interviewer that a test is meaningful?
19. Name five SvelteKit 2 → 3 changes that appear directly in code.
20. In SvelteKit 3, how do you declare a public, build-time environment variable and read it in a component?
21. What are remote functions, what is their status in SvelteKit 3, and which two flags enable them?
22. Why doesn’t a path guard in `handle` protect a remote `query`?
23. What changed about the HTTP status of enhanced form failures in SvelteKit 3, and why might a test break?
24. Multiple choice: which is the SvelteKit 3 way to open a modal that closes on Back?

    a. `pushState('', { showModal: true })`
    b. `history.pushState({ showModal: true }, '')`
    c. `goto('', { shallow: true, state: { showModal: true } })`
    d. `replaceState('', { showModal: true })`

25. **Live-coding plan:** you are asked for a `Tabs` component with a unit test and an e2e test in 45 minutes. List your steps with rough timings and name the acceptance criteria you would write.
