# Day 7: Remote Functions and Production Breadth: Auth, Security, Performance, Deployment, Migration

**Goal for today:** talk confidently about what is new in SvelteKit 3 and answer “senior” questions on auth, security, caching and deployment. Today is about breadth: skim, and make sure you can answer the quiz.

## Read (45 min, all skims)

1. **Kit 7**, the chapter introduction, “7.1 Remote modules”, “7.3 Validation”, “7.4 `query`” (to “Consuming a query”).
2. **Kit 8**, “8.1 `form`: the model”, “8.6 `command`”, “8.7 Default invalidation versus explicit refreshes”, “8.10 Security checklist for mutations”.
3. **Kit 14**, “Sessions versus tokens”, “Cookie design”, “Validating in `handle`”, “Guarding: why layout-only guards fail”.
4. **Kit 15**, “Cross-site scripting”, “CSRF: exactly what is checked”, “A hardening checklist”.
5. **Kit 16**, “What you get for free, and how it works”, “Link preloading”, “Waterfalls”, “Caching” (first page).
6. **Kit 18**, “The adapter model”, “Choosing an adapter”.
7. **Kit 20**, Part 1, the first two pages and the migration task list.

## Core notes (20 min)

### Remote functions (experimental)

Type-safe server functions you call from components, defined in `*.remote.ts` files. Enable with two flags:

```ts
// vite.config.ts
sveltekit({
	experimental: { remoteFunctions: true },
	compilerOptions: { experimental: { async: true } }
});
```

```ts
// src/routes/todos/todos.remote.ts
import * as v from 'valibot';
import { form, query, command } from '$app/server';

export const getTodos = query(async () => db.todosFor(requireUser().id));

export const addTodo = form(
	v.object({ text: v.pipe(v.string(), v.trim(), v.minLength(1, 'Write something')) }),
	async ({ text }) => {
		await db.insertTodo(requireUser().id, text);
	}
);
```

```html
<script lang="ts">
	import { addTodo, getTodos } from './todos.remote';
	const { text } = addTodo.fields;
</script>

<form {...addTodo}>
	<input {...text.as('text')} />
	{#each text.issues() ?? [] as issue}<p>{issue.message}</p>{/each}
	<button>Add</button>
</form>

<ul>
	{#each await getTodos() as todo (todo.id)}<li>{todo.text}</li>{/each}
</ul>
```

| Kind | Purpose |
|---|---|
| `query` | Read data. Cached per argument; `refresh()`, `set()`. `query.batch` merges calls; `query.live` streams updates |
| `form` | A progressively enhanced form: spread it on `<form>`, works without JavaScript |
| `command` | A mutation called from code (not a form). No automatic invalidation |
| `prerender` | Data computed at build time |

Points interviewers like:

- Every argument is **public HTTP input**: validate it with a Standard Schema (Valibot, Zod, ArkType).
- **Authorise inside each remote function.** A path-based guard in `handle` does not protect them, because query requests go to the remote endpoint URL.
- After a successful `form`, all queries and loads refresh by default; explicit `refresh()`/`set()` calls in the handler replace that and ride back in the same response (“single-flight mutation”).
- They are still **experimental** in 3.x: say so, and say you would isolate them behind thin wrappers over plain functions (which also makes them testable).
- Form actions versus remote forms: actions are stable and page-bound; remote forms are reusable anywhere, typed, and avoid wiring `form` props.

### Authentication

- SvelteKit gives primitives, not an auth system: cookies, `handle`, `locals`, `redirect`, CSRF protection.
- Pattern: an opaque session id in an `httpOnly`, `secure`, `sameSite: 'lax'` cookie; validate it in `handle`; set `locals.user`; check it in every load, action, endpoint and remote function (a `requireUser()` helper built on `getRequestEvent()`).
- **Layout-only guards fail**: page loads run in parallel with layout loads, and a client navigation may not re-run the layout load. Guard in `handle` (coarse) and at every data entry point (fine).
- Create a new session at login, log out with a POST, validate any `?next=` redirect target.

### Security

- **XSS:** Svelte escapes `{expressions}`; the risks are `{@html}`, `javascript:` URLs and third-party scripts. Sanitise server-side.
- **CSRF:** in production, SvelteKit rejects form-encoded POST/PUT/PATCH/DELETE requests whose `Origin` is not your origin (configure `csrf.trustedOrigins` for exceptions).
- **CSP:** configured in `sveltekit({ csp })`; SvelteKit adds nonces or hashes for its own inline scripts.
- **Data exposure:** anything returned from a server load is public. Project explicitly.
- Security headers: add them in a `handle` (and at the CDN for static and prerendered files, which bypass `handle`).

### Performance

- Free by default: SSR, code-splitting per route, `modulepreload` of route chunks, link preloading on hover (`data-sveltekit-preload-data`), inlining of universal-load fetches, one batched `__data.json` per navigation.
- Main enemy: **waterfalls** (`await parent()` before independent work, sequential awaits). Start promises first, then await.
- Caching: data requests are `private, no-store`. Cache pages with `setHeaders({ 'cache-control': … })` in load, never publicly cache personalised HTML.
- Images: `@sveltejs/enhanced-img` for build-time images.

### Deployment

| Adapter | Use for |
|---|---|
| `adapter-auto` | Scaffolding only; detects Vercel, Netlify, Cloudflare |
| `adapter-node` | Your own server or container. Behind a proxy, set `paths.origin` or the `*_HEADER` variables (the `ORIGIN` variable is gone in 3) |
| `adapter-static` | Fully prerendered sites, or an SPA with a `fallback` page |
| `adapter-vercel`, `-netlify`, `-cloudflare`, `-bun` | Those platforms |

### Migrating from SvelteKit 2

1. Upgrade to the latest 2.x and fix deprecation warnings.
2. Raise Node (22.17+), TypeScript 6, Svelte 5.57, Vite 8.
3. Run `npx sv migrate sveltekit-3`. It moves config into `vite.config.ts`, rewrites `$lib` to `#lib`, `$app/stores` to `$app/state`, environment imports, paths, matchers and shallow routing, and writes the rest into `MIGRATION_TASKS.md`.
4. Review behavioural changes by hand: `handleError` sees all errors, enhanced forms return real status codes and navigate cross-page, external redirects need `{ external: true }`, CSRF is always on in production.

## Hands-on (40 min)

Choose one:

- **A.** Enable the two experimental flags in your practice project and rebuild the guestbook with a remote `query` and `form` (install `valibot`). Keep the action version on another route so you can compare.
- **B.** If remote functions feel risky for the interview, instead add a fake login: a `/login` action that sets a `sid` cookie, a `handle` that sets `locals.user`, a `/dashboard` page whose **server load** checks `locals.user` and redirects, and an e2e test for the redirect.

## Quiz (15 min)

1. What are remote functions, and what four kinds are there?
2. Why must every remote function validate its argument?
3. A `handle` hook redirects anonymous users away from `/admin/*`. Is an `admin.remote.ts` query called from `/admin/users` protected? Why?
4. What flags do remote functions need in SvelteKit 3?
5. Why is a guard in `+layout.server.ts` not enough to protect a page’s data?
6. Which cookie attributes would you use for a session cookie, and why?
7. What does SvelteKit check to block CSRF, and in which environments?
8. Name three sources of XSS in a Svelte app.
9. What is a waterfall in a SvelteKit app, and how do you fix one?
10. Why are `__data.json` responses not cached, and how do you cache a public page?
11. Which adapter would you use for a Docker deployment, and what must you configure behind a reverse proxy in SvelteKit 3?
12. What does `npx sv migrate sveltekit-3` do, and what does it leave for you?
13. Multiple choice: which statement is true?

    a. Remote functions are stable in SvelteKit 3
    b. `command` refreshes all queries automatically after it runs
    c. A remote `form` works without JavaScript
    d. Remote functions can be defined in `src/lib/server/`

14. Name two SvelteKit 3 behaviour changes the migration codemod cannot fix for you.
15. When would you choose form actions over remote forms today?
