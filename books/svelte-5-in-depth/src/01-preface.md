# Preface

This book is for senior engineers who want to understand Svelte 5 well enough to design, debug and optimise production applications with it, not just to write components. It covers the whole current API surface, and spends most of its time on how the compiler and the signal-based runtime work underneath, where the sharp edges are, and what the trade-offs mean in production.

**Versions.** Everything targets **Svelte 5.57** (October 2026) with Vite 8 and `@sveltejs/vite-plugin-svelte` 7.3. Examples use runes and TypeScript. Legacy (Svelte 4) syntax appears only in the migration chapter and where interop requires it. Experimental features, most importantly `await` in components (`compilerOptions.experimental.async`), are marked as such wherever they appear.

**How the book was checked.** Facts were taken from the official documentation and changelog, and the published `svelte@5.57.2` package was treated as the final authority. Where the two disagreed, the chapter says so. Many behaviours were confirmed by compiling and running small programs.

**How to use it.** Chapters 1–5 build the mental model and the reactivity internals; later chapters can be read in any order. Each chapter ends with key takeaways and 20–30 review questions. Answers to all review questions are at the back of the book, followed by six final tests of increasing difficulty and their answer key.

SvelteKit has its own companion volume, *SvelteKit 3 in Depth*.
