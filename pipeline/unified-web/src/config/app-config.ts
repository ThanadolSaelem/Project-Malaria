import packageJson from "../../package.json";

const currentYear = new Date().getFullYear();

export const APP_CONFIG = {
  name: "Malaria",
  version: packageJson.version,
  copyright: `© ${currentYear}, Malaria.`,
  meta: {
    title: "Malaria",
    description: "Malaria Autonomous Security & Intelligence Platform",
  },
};
