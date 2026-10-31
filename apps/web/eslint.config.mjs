import next from "eslint-config-next";

const config = [
  { ignores: [".next/**", "out/**", "node_modules/**", "next-env.d.ts"] },
  ...next,
];

export default config;
