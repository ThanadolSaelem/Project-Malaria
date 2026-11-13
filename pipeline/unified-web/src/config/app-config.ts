import packageJson from "../../package.json";

const currentYear = new Date().getFullYear();

export const APP_CONFIG = {
  name: "Project-Malaria",
  version: packageJson.version,
  copyright: `© ${currentYear}, ARTEX.`,
  meta: {
    title: "Project-Malaria",
    description: "Unified workspace for the Project-Malaria security systems",
  },
};
