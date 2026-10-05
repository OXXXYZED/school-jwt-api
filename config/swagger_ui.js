// Swagger UI settings: drf-spectacular inserts this object literal into its init script.
// After a successful login or token refresh the access token is applied to jwtAuth, so testers
// don't have to copy it by hand.
{
  deepLinking: true,
  displayRequestDuration: true,
  responseInterceptor: (response) => {
    try {
      const body = response.body || response.obj;
      const path = new URL(response.url, window.location.href).pathname;
      if (response.ok && body && body.access && /\/api\/auth\/(login|refresh)\/$/.test(path)) {
        ui.preauthorizeApiKey("jwtAuth", body.access);
      }
    } catch (error) {
      console.warn("Could not apply the access token automatically", error);
    }
    // Keep drf-spectacular's own interceptor (it handles schema authentication).
    return typeof responseInterceptor === "function" ? responseInterceptor(response) : response;
  },
}
