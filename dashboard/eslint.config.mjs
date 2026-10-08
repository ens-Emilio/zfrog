import { defineConfig, globalIgnores } from "eslint/config"
import eslintReact from "@eslint/js"
import tseslint from "typescript-eslint"
import reactHooks from "eslint-plugin-react-hooks"

const eslintConfig = defineConfig([
  eslintReact.configs.recommended,
  ...tseslint.configs.recommended,
  reactHooks.configs.flat.recommended,
  {
    // Padrão de fetch-em-effect pré-existente em todas as páginas; revisar junto
    // com a adoção futura de TanStack Query.
    rules: { "react-hooks/set-state-in-effect": "warn" },
  },
  globalIgnores(["dist/**", "src/routeTree.gen.ts", "node_modules/**"]),
])

export default eslintConfig
