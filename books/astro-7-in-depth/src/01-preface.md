# Preface

This book is for senior engineers who build content-heavy and hybrid sites with Astro and want to know exactly how its islands architecture, rendering pipeline and server features behave. Every interactive example uses **Svelte 5** (runes) components as islands, so the book also documents the Astro–Svelte boundary in detail: how props are serialized, how slots reach a Svelte component, how hydration directives work, and how state is shared between islands.

**Versions.** Everything targets **Astro 7.4** (October 2026) with `@astrojs/svelte` 9.1 and Svelte 5.57, on Node 22.22+. Astro 7 brought major changes: a Rust compiler, the Sätteri Markdown processor, stable advanced routing via `src/fetch.ts`, and stable route caching. Experimental features and their flags are marked wherever they appear, and Chapter 19 covers migrating from earlier versions.

**How the book was checked.** Facts were taken from the official documentation and changelogs. Where the docs were silent, ambiguous or wrong, the behaviour was confirmed by building and running real test projects with the published packages, and the chapters report what actually happened. The capstone project in Chapter 20 was built and exercised end to end.

**How to use it.** Chapters 1–4 explain the rendering model and the Svelte integration; later chapters can be read as needed. Each chapter ends with key takeaways and 20–30 review questions. Answers are at the back, followed by six final tests of increasing difficulty and their answer key.
