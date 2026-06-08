#!/bin/sh
set -eu

corepack enable
pnpm exec vitest run -c vitest.unit.config.ts packages/compiler-core/__tests__/parse.spec.ts
