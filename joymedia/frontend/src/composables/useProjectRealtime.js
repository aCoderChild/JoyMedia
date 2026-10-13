import { onBeforeUnmount, onMounted, unref } from "vue";
import { io } from "socket.io-client";

// One socket.io connection per page, to Frappe's realtime server. The namespace is the site name; behind
// nginx the page's own origin proxies it, in developer mode the socket port is used (set by the page).
let socket = null;

function connect() {
  if (socket) return socket;
  const base = window.socket_base || window.location.origin;
  socket = io(`${base}/${window.site_name}`, { withCredentials: true, transports: ["websocket", "polling"] });
  return socket;
}

/**
 * Subscribe to a Media Project's document room and run a handler per event, e.g.
 * useProjectRealtime(projectName, { joymedia_project_updated: reload }).
 * Frappe only delivers these to people who may read the project.
 */
export function useProjectRealtime(projectName, handlers) {
  let subscribed = null;
  const listeners = Object.entries(handlers);

  onMounted(() => {
    const name = unref(projectName);
    if (!name) return;
    const s = connect();
    subscribed = name;
    const subscribe = () => s.emit("doc_subscribe", "Media Project", name);
    s.on("connect", subscribe);
    if (s.connected) subscribe();
    for (const [event, fn] of listeners) s.on(event, fn);
  });

  onBeforeUnmount(() => {
    if (!socket || !subscribed) return;
    socket.emit("doc_unsubscribe", "Media Project", subscribed);
    for (const [event, fn] of listeners) socket.off(event, fn);
  });
}
