import * as api from "./api.js";

export function createSessionController(onChange) {
  let authenticated = false;
  let viewer = null;

  return {
    get authenticated() {
      return authenticated;
    },
    get viewer() {
      return viewer;
    },
    async login(email, password) {
      const result = await api.login(email, password);
      authenticated = true;
      viewer = result.viewer || null;
      onChange();
    },
    async logout() {
      await api.logout();
      authenticated = false;
      viewer = null;
      onChange();
    },
    async restore() {
      try {
        await api.loadResource("overview");
        authenticated = true;
        onChange();
        return true;
      } catch {
        authenticated = false;
        viewer = null;
        onChange();
        return false;
      }
    },
  };
}
