/**
 * Public Salesforce install config (safe to commit).
 * Edit netlify/functions/_lib/sfInstallConfig.json (source of truth).
 *
 * No client secrets on Netlify. Salesforce hosts the login.
 */
import cfg from "../netlify/functions/_lib/sfInstallConfig.json";

export const SF_PACKAGE_VERSION_ID = cfg.SF_PACKAGE_VERSION_ID || "";
export const SF_OAUTH_CLIENT_ID = cfg.SF_OAUTH_CLIENT_ID || "";
