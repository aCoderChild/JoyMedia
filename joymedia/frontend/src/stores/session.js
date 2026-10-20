import { computed, ref } from "vue";
import { call, createResource } from "frappe-ui";

function sessionUser() {
  const cookies = new URLSearchParams(document.cookie.split("; ").join("&"));
  const value = cookies.get("user_id");
  return value && value !== "Guest" ? value : null;
}

const user = ref(sessionUser());
const access = ref({role:"unassigned",reviewer:false,can_create:false,can_use_library:false,can_use_advanced_editor:false});

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
    access,
    refreshAccess: async (projectName=null) => { access.value=await call("joymedia.services.partners.get_access", {project_name:projectName}); return access.value; },
    isLoggedIn: computed(() => Boolean(user.value)),
    refreshSession: () => {
      user.value = sessionUser();
      return user.value;
    },
    logout,
  };
}
