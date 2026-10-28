<template>
  <FrappeUIProvider>
    <AppShell>
      <RouterView :key="$route.fullPath" />
    </AppShell>
    <RioToasts />
    <RioDialogHost />
    <UpdateBanner />
  </FrappeUIProvider>
</template>

<script setup>
import { watchEffect } from "vue";
import { FrappeUIProvider } from "frappe-ui";
import AppShell from "./components/AppShell.vue";
import RioDialogHost from "./components/RioDialogHost.vue";
import RioToasts from "./components/RioToasts.vue";
import UpdateBanner from "./components/UpdateBanner.vue";
import { useAttention } from "./composables/useAttention";
import { useSession } from "./stores/session";

// Tell people when a video needs them or is ready, wherever they are in the app.
const { user, isLoggedIn, access } = useSession();
const { start } = useAttention();
watchEffect(() => {
  if (isLoggedIn.value && access.value?.can_create) start(user.value);
});
</script>
