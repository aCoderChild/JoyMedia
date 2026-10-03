<template>
  <FrappeUIProvider>
    <AppShell>
      <RouterView :key="$route.fullPath" />
    </AppShell>
  </FrappeUIProvider>
</template>

<script setup>
import { FrappeUIProvider } from "frappe-ui";
import AppShell from "./components/AppShell.vue";
</script>
