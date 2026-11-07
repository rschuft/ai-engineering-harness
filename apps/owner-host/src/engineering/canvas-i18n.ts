import { createInstance, type i18n as I18nInstance } from "i18next";
import { OPENHANDS_I18N_NAMESPACE, translationResources } from "@openhands/agent-canvas";

/**
 * An i18next instance for Agent Canvas built from the translations Canvas
 * itself exports (`translationResources`), initialised synchronously.
 *
 * Canvas's own default instance (`createAgentServerI18n`, used when the host
 * passes none) loads translations over HTTP from `/locales/{lng}/openhands.json`
 * on the host's origin. The Owner host serves no such files and makes no
 * network requests, so it supplies this instance and registers it with
 * `setI18n` before Canvas mounts. i18next is pinned to 26.5.11, the version
 * Canvas 1.36.0 locks.
 */
export function createCanvasI18n(lng = "en"): I18nInstance {
  const resources = Object.fromEntries(
    Object.entries(translationResources as Record<string, Record<string, string>>).map(([language, keys]) => [
      language,
      { [OPENHANDS_I18N_NAMESPACE]: keys },
    ]),
  );
  const instance = createInstance();
  void instance.init({
    lng,
    fallbackLng: "en",
    ns: [OPENHANDS_I18N_NAMESPACE],
    defaultNS: OPENHANDS_I18N_NAMESPACE,
    resources,
    initAsync: false,
    interpolation: { escapeValue: false },
  });
  return instance;
}
