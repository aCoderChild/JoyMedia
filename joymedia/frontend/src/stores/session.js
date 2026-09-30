import { computed, ref } from "vue";
import { createResource } from "frappe-ui";

function sessionUser() {
  const cookies = new URLSearchParams(document.cookie.split("; ").join("&"));
  const value = cookies.get("user_id");
  return value && value !== "Guest" ? value : null;
}

const user = ref(sessionUser());

export function useSession() {
  const logout = createResource({
    url: "logout",
    auto: false,
    onSuccess() {
      user.value = null;
      window.location.href = "/login?redirect-to=%2Fjoymedia%2Fcampaigns";
    },
  });

  return {
    user,
    isLoggedIn: computed(() => Boolean(user.value)),
    logout,
  };
}
