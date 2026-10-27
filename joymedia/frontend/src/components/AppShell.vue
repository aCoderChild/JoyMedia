<template>
  <div class="app-shell" :class="{ 'is-project-studio': isProjectStudio, 'is-rio-library': isRioLibrary, dark: isRioLibrary }">
    <!-- Left Sidebar (Frappe UI AppShell) -->
    <aside v-if="!isProjectStudio" class="sidebar" :class="{ 'is-collapsed': isCollapsed }">
      <!-- Top Brand Header (JoyMedia Studio) -->
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
              :title="isCollapsed ? 'RIO Studio' : undefined"
            >
              <div class="flex items-center gap-2.5 min-w-0">
                <div class="brand-mark shrink-0">
                  <span class="text-xl font-bold text-white">◇</span>
                </div>
                <div v-if="!isCollapsed" class="flex flex-col text-left min-w-0">
                  <span class="text-xs font-bold uppercase tracking-wider text-rio-400 leading-tight">RIO</span>
                  <span class="text-xs font-semibold text-ink-primary leading-tight truncate">Studio</span>
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
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>
          </template>
        </Dropdown>
      </div>

      <!-- Navigation Links -->
      <nav class="sidebar-nav" :class="{ 'cursor-e-resize': isCollapsed }" aria-label="Main navigation" :title="isCollapsed ? (currentLang === 'vi' ? 'Bấm để mở rộng thanh bên' : 'Click to expand the sidebar') : undefined" @click.self="isCollapsed && toggleSidebar()">
        <!-- Projects -->
        <Tooltip :text="currentLang === 'vi' ? 'Video của bạn' : 'Your videos'" side="right" :disabled="!isCollapsed">
          <RouterLink
            to="/projects"
            class="nav-link relative"
            :class="{ 'justify-center p-2.5 !overflow-visible': isCollapsed }"
            @click="backToTop"
          >
            <span class="nav-link-icon text-base">▦</span>
            <span v-if="!isCollapsed" class="truncate flex-1">{{ currentLang === 'vi' ? 'Video' : 'Videos' }}</span>
            <span
              v-if="waitingCount"
              class="rounded-full bg-amber-400 px-1.5 text-[11px] font-semibold text-amber-950"
              :class="{ 'absolute -right-1 -top-1 min-w-4 px-1 text-[10px] leading-4 shadow': isCollapsed }"
              :title="currentLang === 'vi' ? `${waitingCount} video chờ bạn xem` : `${waitingCount} videos waiting for you`"
              data-test="waiting-badge"
            >
              {{ waitingCount }}
            </span>
            <span
              v-else-if="!isCollapsed && campaignsCount"
              class="sidebar-counter-chip"
            >
              {{ campaignsCount }}
            </span>
          </RouterLink>
        </Tooltip>

        <!-- Media Library -->
        <Tooltip :text="t('sidebar_images')" side="right" :disabled="!isCollapsed">
          <RouterLink
            v-if="access.can_use_library" to="/library"
            class="nav-link"
            :class="{ 'justify-center p-2.5': isCollapsed }"
          >
            <span class="nav-link-icon text-base">🖼️</span>
            <span v-if="!isCollapsed" class="truncate flex-1">{{ t('sidebar_images') }}</span>
            <span
              v-if="!isCollapsed && assetsCount"
              class="sidebar-counter-chip"
            >
              {{ assetsCount }}
            </span>
          </RouterLink>
        </Tooltip>
      </nav>

      <!-- Sidebar Footer: Thu gọn -->
      <div class="sidebar-footer">
        <button
          v-if="!isCollapsed && alertPermission === 'default' && access.can_create"
          type="button"
          class="mb-2 w-full rounded-lg px-2.5 py-2 text-left text-xs text-rio-500 hover:bg-surface-hover"
          data-test="enable-alerts"
          @click="enableBrowserAlerts"
        >
          🔔 {{ currentLang === 'vi' ? 'Bật thông báo video' : 'Enable video alerts' }}
        </button>
        <!-- Thu gọn Toggle -->
        <Tooltip :text="isCollapsed ? (currentLang === 'vi' ? 'Mở rộng' : 'Expand') : (currentLang === 'vi' ? 'Thu gọn' : 'Collapse')" side="right" :disabled="!isCollapsed">
          <button
            type="button"
            class="nav-link w-full text-ink-muted hover:text-ink-primary"
            :class="{ 'justify-center p-2.5': isCollapsed }"
            :aria-label="isCollapsed ? 'Mở rộng thanh bên' : 'Thu gọn thanh bên'"
            @click="toggleSidebar"
          >
            <svg class="nav-link-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <rect x="3" y="4" width="18" height="16" rx="2" /><line x1="9" y1="4" x2="9" y2="20" />
              <polyline :points="isCollapsed ? '13 9 16 12 13 15' : '16 9 13 12 16 15'" />
            </svg>
            <span v-if="!isCollapsed" class="truncate flex-1 text-xs">{{ currentLang === 'vi' ? 'Thu gọn' : 'Collapse' }}</span>
          </button>
        </Tooltip>
      </div>
    </aside>

    <!-- Main Workspace Area -->
    <main class="main-content">
      <!-- Topbar -->
      <header v-if="!isProjectStudio" class="topbar">
        <!-- Left: Home / Project Navigation -->
        <div class="flex items-center gap-3">
          <RouterLink v-if="isRioLibrary" to="/projects" class="rio-library-brand" aria-label="RIO Studio — Videos"><span aria-hidden="true">◇</span><strong>RIO <em>STUDIO</em></strong></RouterLink>
          <button
            v-if="!isRioLibrary"
            type="button"
            class="p-1 rounded text-ink-muted hover:text-ink-primary transition-colors"
            :title="currentLang === 'vi' ? 'Video' : 'Videos'"
            @click="router.push('/campaigns')"
          >
            <svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
              <polyline points="9 22 9 12 15 12 15 22"/>
            </svg>
          </button>

          <div class="flex items-center gap-2">
            <span class="text-xs font-semibold text-ink-primary tracking-tight">{{ currentPageTitle }}</span>
          </div>
        </div>

        <div class="flex-1" />

        <!-- Right: Actions & User -->
        <div class="topbar-right flex items-center gap-2.5">
          <!-- Language Switcher (Compact Globe Menu) -->
          <button
            type="button"
            class="flex items-center gap-1.5 px-2.5 py-1 rounded-xl text-xs font-semibold text-ink-primary bg-surface-card hover:bg-surface-hover border border-outline-border transition-all select-none shadow-xs"
            :title="currentLang === 'vi' ? 'Switch to English' : 'Chuyển sang Tiếng Việt'"
            @click="toggleLang"
          >
            <span class="text-xs">🌐</span>
            <span class="font-mono text-[11px] uppercase tracking-wider font-bold">{{ currentLang }}</span>
          </button>

          <!-- Theme Toggle -->
          <button
            v-if="!isRioLibrary"
            type="button"
            class="p-1.5 rounded-xl text-ink-muted hover:text-ink-primary hover:bg-surface-hover transition-colors border border-transparent hover:border-outline-border"
            :title="isDark ? (currentLang === 'vi' ? 'Chuyển sang Giao diện Sáng' : 'Switch to Light Mode') : (currentLang === 'vi' ? 'Chuyển sang Giao diện Tối' : 'Switch to Dark Mode')"
            @click="toggleTheme"
          >
            <svg v-if="isDark" class="size-4 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="4"/>
              <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>
            </svg>
            <svg v-else class="size-4 text-rio-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>
            </svg>
          </button>

          <RoleBadge v-if="access.administrator" />
          <!-- User Badge -->
          <div class="user-badge" :title="user">
            <span class="user-avatar">{{ userInitial }}</span>
            <span class="user-name hidden lg:inline">{{ user || "Creator" }}</span>
          </div>

          <!-- Log out -->
          <Button
            variant="subtle"
            class="!px-2"
            :loading="logout.loading"
            @click="logout.submit()"
            :title="currentLang === 'vi' ? 'Đăng xuất' : 'Sign out'"
          >
            <template #prefix>
              <svg class="size-4 text-ink-muted hover:text-ink-primary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
                <polyline points="16 17 21 12 16 7"/>
                <line x1="21" x2="9" y1="12" y2="12"/>
              </svg>
            </template>
          </Button>
        </div>
      </header>

      <!-- Slot Content -->
      <div class="page-content flow-page-content" :class="{ 'studio-page-content': isProjectStudio }">
        <slot />
      </div>
    </main>
  </div>
</template>

<script setup>
import RoleBadge from "./RoleBadge.vue";
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Button, Dropdown, Tooltip, createResource } from "frappe-ui";
import { useSession } from "../stores/session";
import { useAttention } from "../composables/useAttention";
import { useI18n } from "../stores/i18n";

const { user, logout, access } = useSession();
const { waitingCount, permission: alertPermission, enableBrowserAlerts } = useAttention();
const { t, currentLang, toggleLang, setLang } = useI18n();
const route = useRoute();
const router = useRouter();
const isProjectStudio = computed(() => route.path.includes("/projects/"));
const isRioLibrary = computed(() => route.path === "/projects");

// Sidebar state
const isCollapsed = ref(localStorage.getItem("joymedia_sidebar_collapsed") === "true");

// Clicking the page you are on takes you back to its start, like most web apps.
function backToTop() {
  if (route.path !== "/projects") return;
  document.querySelector(".main-content")?.scrollTo({ top: 0, behavior: "smooth" });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function toggleSidebar() {
  isCollapsed.value = !isCollapsed.value;
  localStorage.setItem("joymedia_sidebar_collapsed", String(isCollapsed.value));
}

// Theme management
const isDark = ref(false);

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
  if (savedTheme === "light") {
    applyTheme(false);
  } else {
    applyTheme(true);
  }
});

// Dynamic Resource Counts
const sidebarCountsResource = createResource({
  url: "joymedia.api.projects.get_sidebar_counts",
  auto: true,
});

const campaignsCount = computed(() => sidebarCountsResource.data?.projects || 0);
const assetsCount = computed(() => sidebarCountsResource.data?.assets || 0);

const currentPageTitle = computed(() => {
  const path = route.path;
  if(access.value.reviewer) return currentLang.value==='vi'?'Duyệt video đối tác':'Partner review';
  const isEn = currentLang.value === "en";
  if (path === "/campaigns" || path === "/" || path === "/projects") return isEn ? "Projects" : "Dự án";
  if (path.startsWith("/campaigns/")) return isEn ? "Project Workspace" : "Chi tiết dự án";
  if (path.startsWith("/projects/")) return "JoyMedia Studio";
  if (path.startsWith("/assets")) return isEn ? "Media Library" : "Thư viện Media";
  return "JoyMedia Studio";
});

const userInitial = computed(() => {
  if (!user.value) return "J";
  return user.value.charAt(0).toUpperCase();
});

const headerDropdownOptions = computed(() => [
  { label: "JoyMedia Studio", onClick: () => router.push("/campaigns") },
  ...(access.value.can_use_library ? [{ label: currentLang.value === "en" ? "Media Library" : "Thư viện Media", onClick: () => router.push("/assets") }] : []),
  {
    label: currentLang.value === "en" ? "🇻🇳 Tiếng Việt" : "🇬🇧 English",
    onClick: () => toggleLang(),
  },
  { label: currentLang.value === "en" ? "Sign out" : "Đăng xuất", onClick: () => logout.submit() },
]);
</script>
