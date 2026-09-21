<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">J</div>
        <span>JoyMedia</span>
      </div>

      <nav class="sidebar-nav" aria-label="Main navigation">
        <RouterLink to="/campaigns" class="nav-link">Campaigns</RouterLink>
        <RouterLink to="/assets" class="nav-link">Assets</RouterLink>
        <RouterLink to="/reviews" class="nav-link">Review Videos</RouterLink>
      </nav>

      <div class="sidebar-footer">Create product videos with AI</div>
    </aside>

    <main class="main-content">
      <header class="topbar">
        <span class="breadcrumb">JoyMedia</span>
        <span class="account-name">{{ user }}</span>
        <Button appearance="minimal" label="Log out" :loading="logout.loading" @click="logout.submit()" />
      </header>
      <div class="page-content"><slot /></div>
    </main>
  </div>
</template>

<script setup>
import { Button } from "frappe-ui";
import { useSession } from "../stores/session";

const { user, logout } = useSession();
</script>
