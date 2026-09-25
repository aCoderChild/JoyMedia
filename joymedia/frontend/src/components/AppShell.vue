<template>
  <div class="app-shell">
    <aside class="sidebar" :class="{ 'is-collapsed': isCollapsed }">
      <!-- Top Brand & Workspace Switcher (Frappe LMS Style) -->
      <div class="sidebar-header">
        <Dropdown :options="headerDropdownOptions" :side="'bottom'" :align="'start'">
          <template v-slot="{ open }">
            <button
              type="button"
              class="workspace-header-btn group"
              :class="{
                'is-open': open,
                'justify-center p-1.5': isCollapsed,
                'justify-between p-2': !isCollapsed,
              }"
              :title="isCollapsed ? 'JoyMedia Studio (Click for menu)' : undefined"
            >
              <div class="flex items-center gap-2.5 min-w-0">
                <div class="brand-mark shrink-0">
                  <svg class="size-5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5"/>
                    <rect x="2" y="6" width="14" height="12" rx="2"/>
                  </svg>
                </div>
                <div v-if="!isCollapsed" class="flex flex-col text-left min-w-0">
                  <span class="text-sm font-semibold text-ink-primary leading-tight truncate">JoyMedia</span>
                  <span class="text-xs text-ink-secondary truncate">{{ user || "Production Studio" }}</span>
                </div>
              </div>
              <svg
                v-if="!isCollapsed"
                class="size-4 text-ink-muted group-hover:text-ink-primary transition-transform duration-200 shrink-0"
                :class="{ 'rotate-180': open }"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>
          </template>
        </Dropdown>
      </div>

      <!-- Navigation Links (Frappe LMS Core Structure) -->
      <nav class="sidebar-nav" aria-label="Main navigation">
        <!-- Campaigns (Courses equivalent in LMS) -->
        <Tooltip text="Campaigns" side="right" :disabled="!isCollapsed">
          <RouterLink
            to="/campaigns"
            class="nav-link"
            :class="{ 'justify-center p-2.5': isCollapsed }"
          >
            <span class="nav-link-icon">
              <svg class="size-4.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
                <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
                <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
              </svg>
            </span>
            <span v-if="!isCollapsed" class="truncate flex-1">Campaigns</span>
            <span
              v-if="!isCollapsed && campaignsCount"
              class="sidebar-counter-chip"
            >
              {{ campaignsCount }}
            </span>
          </RouterLink>
        </Tooltip>

        <!-- Review Videos (Batches equivalent in LMS) -->
        <Tooltip text="Review Videos" side="right" :disabled="!isCollapsed">
          <RouterLink
            to="/reviews"
            class="nav-link"
            :class="{ 'justify-center p-2.5': isCollapsed }"
          >
            <span class="nav-link-icon relative">
              <svg class="size-4.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
                <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>
                <circle cx="9" cy="7" r="4"/>
                <polyline points="16 11 18 13 22 9"/>
              </svg>
              <!-- Notification Dot when collapsed -->
              <span
                v-if="isCollapsed && pendingReviewsCount > 0"
                class="absolute -top-1 -right-1 size-2 rounded-full bg-amber-500 animate-pulse"
              />
            </span>
            <span v-if="!isCollapsed" class="truncate flex-1">Review Videos</span>
            <span
              v-if="!isCollapsed && pendingReviewsCount > 0"
              class="sidebar-counter-badge"
            >
              {{ pendingReviewsCount }}
            </span>
          </RouterLink>
        </Tooltip>

        <!-- Assets (Jobs/Library equivalent in LMS) -->
        <Tooltip text="Assets" side="right" :disabled="!isCollapsed">
          <RouterLink
            to="/assets"
            class="nav-link"
            :class="{ 'justify-center p-2.5': isCollapsed }"
          >
            <span class="nav-link-icon">
              <svg class="size-4.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
                <rect width="20" height="14" x="2" y="7" rx="2" ry="2"/>
                <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>
              </svg>
            </span>
            <span v-if="!isCollapsed" class="truncate flex-1">Assets</span>
            <span
              v-if="!isCollapsed && assetsCount"
              class="sidebar-counter-chip"
            >
              {{ assetsCount }}
            </span>
          </RouterLink>
        </Tooltip>

        <!-- Workspace & Statistics (Statistics equivalent in LMS) -->
        <Tooltip text="Workspace Setup" side="right" :disabled="!isCollapsed">
          <RouterLink
            to="/onboarding"
            class="nav-link"
            :class="{ 'justify-center p-2.5': isCollapsed }"
          >
            <span class="nav-link-icon">
              <svg class="size-4.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/>
                <polyline points="16 7 22 7 22 13"/>
              </svg>
            </span>
            <span v-if="!isCollapsed" class="truncate flex-1">Workspace</span>
          </RouterLink>
        </Tooltip>
      </nav>

      <!-- Sidebar Footer (Frappe LMS Bottom Bar: ⚡ Quick Action & [←|] Collapse Toggle) -->
      <div class="sidebar-footer">
        <!-- ⚡ Quick Actions Dropdown (Frappe LMS Lightning Bolt) -->
        <Tooltip text="Quick Actions (⚡)" :side="isCollapsed ? 'right' : 'top'">
          <Dropdown :options="quickActionOptions" :side="'top'" :align="'start'">
            <template v-slot="{ open }">
              <button
                type="button"
                class="sidebar-icon-btn group"
                :class="{ 'is-active': open }"
                aria-label="Quick Actions"
              >
                <svg class="size-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
                </svg>
              </button>
            </template>
          </Dropdown>
        </Tooltip>

        <!-- [←|] / [|→] Collapse / Expand Sidebar Toggle -->
        <Tooltip :text="isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'" :side="isCollapsed ? 'right' : 'top'">
          <button
            type="button"
            class="sidebar-icon-btn"
            :aria-label="isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'"
            @click="toggleSidebar"
          >
            <!-- Expanded Icon: Collapse to left -->
            <svg v-if="!isCollapsed" class="size-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
              <rect width="18" height="18" x="3" y="3" rx="2" ry="2"/>
              <path d="M9 3v18"/>
              <path d="m14 9-3 3 3 3"/>
            </svg>
            <!-- Collapsed Icon: Expand to right -->
            <svg v-else class="size-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
              <rect width="18" height="18" x="3" y="3" rx="2" ry="2"/>
              <path d="M9 3v18"/>
              <path d="m13 15 3-3-3-3"/>
            </svg>
          </button>
        </Tooltip>
      </div>
    </aside>

    <main class="main-content">
      <header class="topbar">
        <div class="breadcrumbs-container">
          <RouterLink to="/campaigns" class="breadcrumb-item">JoyMedia</RouterLink>
          <svg class="size-3.5 text-ink-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="9 18 15 12 9 6" />
          </svg>
          <span class="breadcrumb-item active">{{ currentPageTitle }}</span>
        </div>

        <div class="topbar-right">
          <!-- Quick Theme Toggle in Topbar -->
          <button
            type="button"
            class="p-1.5 rounded-lg text-ink-secondary hover:text-ink-primary hover:bg-surface-hover transition-colors"
            :title="isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode'"
            @click="toggleTheme"
          >
            <!-- Sun Icon (when dark) -->
            <svg v-if="isDark" class="size-4 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="4"/>
              <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>
            </svg>
            <!-- Moon Icon (when light) -->
            <svg v-else class="size-4 text-indigo-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>
            </svg>
          </button>

          <!-- User Badge with Initial -->
          <div class="user-badge" :title="user">
            <span class="user-avatar">{{ userInitial }}</span>
            <span class="user-name">{{ user || "Creator" }}</span>
          </div>

          <Button
            appearance="subtle"
            :loading="logout.loading"
            @click="logout.submit()"
            title="Log out"
          >
            <template #prefix>
              <svg class="size-4 text-ink-secondary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
                <polyline points="16 17 21 12 16 7"/>
                <line x1="21" x2="9" y1="12" y2="12"/>
              </svg>
            </template>
            Log out
          </Button>
        </div>
      </header>

      <div class="page-content">
        <slot />
      </div>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Button, Dropdown, Tooltip, createResource } from "frappe-ui";
import { useSession } from "../stores/session";

const { user, logout } = useSession();
const route = useRoute();
const router = useRouter();

// Sidebar state (persist to localStorage like LMS)
const isCollapsed = ref(localStorage.getItem("joymedia_sidebar_collapsed") === "true");

function toggleSidebar() {
  isCollapsed.value = !isCollapsed.value;
  localStorage.setItem("joymedia_sidebar_collapsed", String(isCollapsed.value));
}

// Theme management (Frappe LMS standard)
const isDark = ref(localStorage.getItem("joymedia_theme") === "dark");

function applyTheme(dark) {
  isDark.value = dark;
  localStorage.setItem("joymedia_theme", dark ? "dark" : "light");
  if (dark) {
    document.documentElement.setAttribute("data-theme", "dark");
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.setAttribute("data-theme", "light");
    document.documentElement.classList.remove("dark");
  }
}

function toggleTheme() {
  applyTheme(!isDark.value);
}

onMounted(() => {
  const savedTheme = localStorage.getItem("joymedia_theme");
  if (savedTheme) {
    applyTheme(savedTheme === "dark");
  } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
    applyTheme(true);
  }
});

// Dynamic Resource Counts for Sidebar
const campaignsResource = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_campaign_cards",
  auto: true,
});

const reviewsResource = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_pending_review_cards",
  auto: true,
});

const assetsResource = createResource({
  url: "frappe.client.get_list",
  params: {
    doctype: "Media Asset",
    fields: ["name"],
    limit_page_length: 500,
  },
  auto: true,
});

const campaignsCount = computed(() => campaignsResource.data?.length || 0);
const pendingReviewsCount = computed(() => reviewsResource.data?.length || 0);
const assetsCount = computed(() => assetsResource.data?.length || 0);

// Top Workspace Header Dropdown Options (Frappe LMS Inspired)
const headerDropdownOptions = computed(() => [
  {
    label: "All Campaigns",
    onClick: () => router.push("/campaigns"),
  },
  {
    label: "+ Create Campaign",
    onClick: () => router.push("/campaigns/new"),
  },
  {
    label: isDark.value ? "Switch to Light Theme" : "Switch to Dark Theme",
    onClick: toggleTheme,
  },
  {
    label: "Frappe Desk Admin (/app)",
    onClick: () => {
      window.location.href = "/app";
    },
  },
  {
    label: "Workspace Setup",
    onClick: () => router.push("/onboarding"),
  },
  {
    label: "Log Out",
    onClick: () => logout.submit(),
  },
]);

// ⚡ Quick Action Dropdown Options (Frappe LMS Lightning Bolt)
const quickActionOptions = computed(() => [
  {
    label: "+ New Campaign",
    onClick: () => router.push("/campaigns/new"),
  },
  {
    label: pendingReviewsCount.value > 0
      ? `Review Videos (${pendingReviewsCount.value} pending)`
      : "Review Videos",
    onClick: () => router.push("/reviews"),
  },
  {
    label: assetsCount.value > 0
      ? `Media Assets (${assetsCount.value} assets)`
      : "Media Assets",
    onClick: () => router.push("/assets"),
  },
  {
    label: isDark.value ? "Light Mode" : "Dark Mode",
    onClick: toggleTheme,
  },
  {
    label: "Frappe Desk (/app)",
    onClick: () => {
      window.location.href = "/app";
    },
  },
]);

const userInitial = computed(() => {
  if (!user.value) return "U";
  return user.value.trim().charAt(0).toUpperCase();
});

const currentPageTitle = computed(() => {
  const path = route.path;
  if (path.startsWith("/campaigns/new")) return "New Campaign";
  if (path.startsWith("/campaigns/")) return "Campaign Detail";
  if (path.startsWith("/campaigns")) return "Campaigns";
  if (path.startsWith("/assets")) return "Assets";
  if (path.startsWith("/reviews")) return "Review Videos";
  if (path.startsWith("/onboarding")) return "Workspace Onboarding";
  return "Workspace";
});
</script>
