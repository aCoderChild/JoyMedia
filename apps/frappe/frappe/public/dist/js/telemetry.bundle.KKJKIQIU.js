(() => {
  // frappe/public/js/telemetry/pulse.js
  var DEFAULT_PULSE_CLIENT_URL = "https://pulse.m.frappe.cloud/assets/pulse/js/pulse_client.js";
  var PulseProvider = class {
    constructor() {
      this.enabled = false;
      this.client = null;
      this.pending = [];
    }
    is_enabled() {
      var _a;
      return ((_a = frappe.boot.telemetry_provider) == null ? void 0 : _a.includes("pulse")) && frappe.boot.enable_telemetry;
    }
    async init() {
      if (!this.is_enabled())
        return;
      this.enabled = true;
      this.register_pageview_handler();
      try {
        this.client = await this.load_client();
        this.client.init();
        this.flush_pending();
      } catch (error) {
        this.enabled = false;
        this.pending = [];
      }
    }
    async load_client() {
      const t = frappe.boot.telemetry || {};
      const url = t.client_url || DEFAULT_PULSE_CLIENT_URL;
      const mod = await import(url);
      return new mod.PulseClient({
        host: t.host,
        apiKey: t.key,
        site: t.site,
        enabled: t.enabled,
        user: t.user,
        team: t.team
      });
    }
    flush_pending() {
      this.pending.forEach(([event, app, props]) => this.client.capture(event, app, props));
      this.pending = [];
    }
    register_pageview_handler() {
      const site_age = frappe.boot.telemetry_site_age;
      if (site_age && site_age > 15) {
        return;
      }
      frappe.router.on("change", () => {
        this.capture("pageview", "frappe", { route: this.scrub_route(frappe.get_route()) });
      });
    }
    scrub_route(route) {
      if (!(route == null ? void 0 : route.length))
        return "";
      if (route[0] === "Form" && route.length >= 3 && route[2] !== route[1]) {
        route = [...route];
        route[2] = "*";
      }
      return route.join("/");
    }
    capture(event, app, props) {
      if (!this.enabled)
        return;
      if (this.client) {
        this.client.capture(event, app, props);
      } else {
        this.pending.push([event, app, props]);
      }
    }
  };
  var pulse_provider = new PulseProvider();

  // frappe/public/js/telemetry/index.js
  var TelemetryManager = class {
    constructor() {
      var _a;
      this.enabled = frappe.boot.enable_telemetry || false;
      this.pulse_available = Boolean((_a = frappe.boot.telemetry_provider) == null ? void 0 : _a.includes("pulse"));
      this.init_providers();
    }
    init_providers() {
      this.providers = [];
      pulse_provider.init();
      if (pulse_provider.enabled) {
        this.providers.push(pulse_provider);
      }
    }
    capture(event, app, props) {
      if (!this.enabled)
        return;
      for (let provider of this.providers) {
        provider.capture(event, app, props);
      }
    }
    disable() {
      this.enabled = false;
      this.providers = [];
    }
    can_enable() {
      let sentry_available = Boolean(frappe.boot.sentry_dsn);
      return this.pulse_available || sentry_available;
    }
  };
  frappe.telemetry = new TelemetryManager();
})();
//# sourceMappingURL=telemetry.bundle.KKJKIQIU.js.map
