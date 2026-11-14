# Preface

This book is for senior engineers building production applications with SvelteKit. It assumes you already know Svelte 5 and runes (see the companion volume *Svelte 5 in Depth*) and concentrates on the application framework: the request lifecycle, routing, data loading, mutations, security, performance, observability and deployment.

**Versions.** Everything targets **SvelteKit 3.1** (October 2026) with Svelte 5.57, Vite 8, Node 22+ and TypeScript 6+. SvelteKit 3 changed a lot. `svelte.config.js` is gone, and configuration lives in the `sveltekit({...})` call in `vite.config.ts`. The `$lib` alias was replaced by `#lib` subpath imports, `$app/stores` was removed, environment variables are declared in `src/env.ts`, and remote functions became a central (still experimental) feature. Every example uses the SvelteKit 3 conventions, and Chapter 20 maps the old ones to the new.

**How the book was checked.** Facts were taken from the official documentation and changelog and checked against the published `@sveltejs/kit@3.1.0` source and types. Where the docs and types disagree, the chapters follow the types and say so. Recommendations that go beyond the official docs (for example on authentication and testing) are labelled as the author’s practice.

**How to use it.** Read Chapters 1–5 first. They describe the architecture that everything else relies on. Each chapter ends with key takeaways and 20–30 review questions. Answers are at the back, followed by six final tests of increasing difficulty and their answer key.
