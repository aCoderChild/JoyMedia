<template>
  <div class="app-shell">
    <!-- Left Sidebar (Frappe UI AppShell) -->
    <aside class="sidebar" :class="{ 'is-collapsed': isCollapsed }">
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
              :title="isCollapsed ? 'JoyMedia Studio' : undefined"
            >
              <div class="flex items-center gap-2.5 min-w-0">
                <div class="brand-mark shrink-0">
                  <span class="text-base font-bold text-white">✦</span>
                </div>
                <div v-if="!isCollapsed" class="flex flex-col text-left min-w-0">
                  <span class="text-xs font-bold uppercase tracking-wider text-indigo-400 leading-tight">JoyMedia</span>
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
      <nav class="sidebar-nav" aria-label="Main navigation">
        <!-- 1. Tất cả nội dung nghệ... -->
        <Tooltip :text="t('sidebar_all_art_full')" side="right" :disabled="!isCollapsed">
          <RouterLink
            to="/campaigns"
            class="nav-link"
            :class="{ 'justify-center p-2.5': isCollapsed }"
          >
            <span class="nav-link-icon text-base">▦</span>
            <span v-if="!isCollapsed" class="truncate flex-1">{{ t('sidebar_all_art') }}</span>
            <span
              v-if="!isCollapsed && campaignsCount"
              class="sidebar-counter-chip"
            >
              {{ campaignsCount }}
            </span>
          </RouterLink>
        </Tooltip>

        <!-- 2. Hình ảnh -->
        <Tooltip :text="t('sidebar_images')" side="right" :disabled="!isCollapsed">
          <RouterLink
            to="/assets"
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

        <!-- 3. Nhân vật -->
        <Tooltip :text="t('sidebar_characters')" side="right" :disabled="!isCollapsed">
          <RouterLink
            to="/assets?category=Character"
            class="nav-link"
            :class="{ 'justify-center p-2.5': isCollapsed }"
          >
            <span class="nav-link-icon text-base">👤</span>
            <span v-if="!isCollapsed" class="truncate flex-1">{{ t('sidebar_characters') }}</span>
          </RouterLink>
        </Tooltip>

        <!-- 4. Cảnh -->
        <Tooltip :text="t('sidebar_scenes')" side="right" :disabled="!isCollapsed">
          <RouterLink
            to="/reviews"
            class="nav-link"
            :class="{ 'justify-center p-2.5': isCollapsed }"
          >
            <span class="nav-link-icon relative text-base">
              🎬
              <span
                v-if="isCollapsed && pendingReviewsCount > 0"
                class="absolute -top-1 -right-1 size-2 rounded-full bg-amber-500 animate-pulse"
              />
            </span>
            <span v-if="!isCollapsed" class="truncate flex-1">{{ t('sidebar_scenes') }}</span>
            <span
              v-if="!isCollapsed && pendingReviewsCount > 0"
              class="sidebar-counter-badge"
            >
              {{ pendingReviewsCount }}
            </span>
          </RouterLink>
        </Tooltip>

        <!-- 5. Công cụ -->
        <Tooltip :text="t('sidebar_tools')" side="right" :disabled="!isCollapsed">
          <RouterLink
            to="/onboarding"
            class="nav-link"
            :class="{ 'justify-center p-2.5': isCollapsed }"
          >
            <span class="nav-link-icon text-base">✨</span>
            <span v-if="!isCollapsed" class="truncate flex-1">{{ t('sidebar_tools') }}</span>
          </RouterLink>
        </Tooltip>
      </nav>

      <!-- Sidebar Footer: Thùng rác + Thu gọn -->
      <div class="sidebar-footer">
        <!-- Thùng rác -->
        <Tooltip text="Thùng rác" side="right" :disabled="!isCollapsed">
          <button
            type="button"
            class="nav-link w-full text-ink-muted hover:text-ink-primary"
            :class="{ 'justify-center p-2.5': isCollapsed }"
            @click="router.push('/assets')"
          >
            <span class="nav-link-icon text-sm">🗑️</span>
            <span v-if="!isCollapsed" class="truncate flex-1 text-xs">{{ currentLang === 'vi' ? 'Thùng rác' : 'Trash' }}</span>
          </button>
        </Tooltip>

        <!-- Thu gọn Toggle -->
        <Tooltip :text="isCollapsed ? (currentLang === 'vi' ? 'Mở rộng' : 'Expand') : (currentLang === 'vi' ? 'Thu gọn' : 'Collapse')" side="right" :disabled="!isCollapsed">
          <button
            type="button"
            class="nav-link w-full text-ink-muted hover:text-ink-primary"
            :class="{ 'justify-center p-2.5': isCollapsed }"
            :aria-label="isCollapsed ? 'Mở rộng thanh bên' : 'Thu gọn thanh bên'"
            @click="toggleSidebar"
          >
            <span class="nav-link-icon text-xs font-mono">
              {{ isCollapsed ? '▶|' : '◀|' }}
            </span>
            <span v-if="!isCollapsed" class="truncate flex-1 text-xs">{{ currentLang === 'vi' ? 'Thu gọn' : 'Collapse' }}</span>
          </button>
        </Tooltip>
      </div>
    </aside>

    <!-- Main Workspace Area -->
    <main class="main-content">
      <!-- Topbar -->
      <header class="topbar">
        <!-- Left: Home / Project Navigation -->
        <div class="flex items-center gap-3">
          <button
            type="button"
            class="p-1 rounded text-ink-muted hover:text-ink-primary transition-colors"
            title="Trang chủ chiến dịch"
            @click="router.push('/campaigns')"
          >
            <svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
              <polyline points="9 22 9 12 15 12 15 22"/>
            </svg>
          </button>

          <div class="flex items-center gap-2">
            <span class="text-xs font-semibold text-ink-primary tracking-tight">{{ currentPageTitle }}</span>
            <span class="text-ink-muted hover:text-ink-primary cursor-pointer p-0.5" title="Tùy chọn">⋮</span>
          </div>
        </div>

        <!-- Center: Search Pill -->
        <div class="hidden md:flex items-center justify-center flex-1 max-w-sm mx-4">
          <div class="flex items-center gap-2 w-full px-3.5 py-1.5 rounded-full bg-surface-card border border-outline-border text-xs text-ink-primary focus-within:border-indigo-500 focus-within:ring-1 focus-within:ring-indigo-500 shadow-xs transition-all">
            <svg class="size-3.5 text-ink-muted shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="8"/>
              <path d="m21 21-4.3-4.3"/>
            </svg>
            <input
              type="text"
              :placeholder="currentLang === 'vi' ? 'Tìm kiếm dự án, kịch bản, cảnh...' : 'Search projects, scripts, scenes...'"
              class="bg-transparent border-none outline-none text-xs text-ink-primary placeholder:text-ink-muted w-full"
            />
          </div>
        </div>

        <!-- Right: Actions & User -->
        <div class="topbar-right flex items-center gap-2.5">
          <!-- Language Switcher (EN / VI) -->
          <button
            type="button"
            class="flex items-center gap-1.5 px-2.5 py-1 rounded-xl text-xs font-semibold text-ink-primary bg-surface-card hover:bg-surface-hover border border-outline-border transition-all select-none shadow-xs"
            :title="currentLang === 'vi' ? 'Switch to English' : 'Chuyển sang Tiếng Việt'"
            @click="toggleLang"
          >
            <span class="text-xs">🌐</span>
            <span class="font-mono text-[11px] uppercase tracking-wider font-bold">{{ currentLang }}</span>
            <span class="text-[10px] text-ink-muted font-normal">({{ currentLang === 'vi' ? 'VIE' : 'ENG' }})</span>
          </button>

          <!-- Quick New Project Button -->
          <button
            type="button"
            class="hidden sm:flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-500 text-white transition-all shadow-sm shadow-indigo-600/20 cursor-pointer"
            @click="router.push('/campaigns/new')"
          >
            <span class="text-sm font-bold leading-none">+</span>
            <span>{{ currentLang === 'vi' ? 'Tạo dự án' : 'New Project' }}</span>
          </button>

          <!-- Theme Toggle -->
          <button
            type="button"
            class="p-1.5 rounded-xl text-ink-muted hover:text-ink-primary hover:bg-surface-hover transition-colors border border-transparent hover:border-outline-border"
            :title="isDark ? (currentLang === 'vi' ? 'Chuyển sang Giao diện Sáng' : 'Switch to Light Mode') : (currentLang === 'vi' ? 'Chuyển sang Giao diện Tối' : 'Switch to Dark Mode')"
            @click="toggleTheme"
          >
            <svg v-if="isDark" class="size-4 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="4"/>
              <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>
            </svg>
            <svg v-else class="size-4 text-indigo-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>
            </svg>
          </button>

          <!-- PRO Tag -->
          <span class="text-[11px] font-bold px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            PRO
          </span>

          <!-- User Badge -->
          <div class="user-badge" :title="user">
            <span class="user-avatar">{{ userInitial }}</span>
            <span class="user-name hidden lg:inline">{{ user || "Creator" }}</span>
          </div>

          <!-- Log out -->
          <Button
            appearance="subtle"
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
      <div class="page-content flow-page-content">
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
import { useI18n } from "../stores/i18n";

const { user, logout } = useSession();
const { t, currentLang, toggleLang, setLang } = useI18n();
const route = useRoute();
const router = useRouter();

// Sidebar state
const isCollapsed = ref(localStorage.getItem("joymedia_sidebar_collapsed") === "true");

function toggleSidebar() {
  isCollapsed.value = !isCollapsed.value;
  localStorage.setItem("joymedia_sidebar_collapsed", String(isCollapsed.value));
}

// Theme management (Google Flow obsidian dark)
const isDark = ref(true);

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
const campaignsResource = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_campaign_cards",
  auto: true,
});

const reviewsResource = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_reviews_summary",
  auto: true,
});

const campaignsCount = computed(() => campaignsResource.data?.length || 0);
const assetsCount = computed(() => {
  const campaigns = campaignsResource.data || [];
  return campaigns.reduce((total, c) => total + (c.asset_count || 0), 0);
});
const pendingReviewsCount = computed(() => reviewsResource.data?.pending_count || 0);

const currentPageTitle = computed(() => {
  const path = route.path;
  const isEn = currentLang.value === "en";
  if (path === "/campaigns" || path === "/") return isEn ? "Marketing Campaigns" : "Chiến dịch Video";
  if (path.startsWith("/campaigns/new")) return isEn ? "Create New Project" : "Tạo dự án mới";
  if (path.startsWith("/campaigns/")) return isEn ? "Campaign Workspace" : "Chi tiết chiến dịch";
  if (path.startsWith("/projects/")) return "JoyMedia Studio";
  if (path.startsWith("/reviews")) return isEn ? "Review Videos" : "Đánh giá video";
  if (path.startsWith("/assets")) return isEn ? "Asset Library" : "Thư viện Media";
  if (path.startsWith("/onboarding")) return isEn ? "Studio Settings" : "Cài đặt Studio";
  return "JoyMedia Studio";
});

const userInitial = computed(() => {
  if (!user.value) return "J";
  return user.value.charAt(0).toUpperCase();
});

const headerDropdownOptions = computed(() => [
  { label: "JoyMedia Studio", onClick: () => router.push("/campaigns") },
  { label: currentLang.value === "en" ? "Asset Library" : "Thư viện Media", onClick: () => router.push("/assets") },
  { label: currentLang.value === "en" ? "Review Videos" : "Đánh giá Video", onClick: () => router.push("/reviews") },
  {
    label: currentLang.value === "en" ? "🇻🇳 Tiếng Việt" : "🇬🇧 English",
    onClick: () => toggleLang(),
  },
  { label: currentLang.value === "en" ? "Studio Settings" : "Cài đặt Studio", onClick: () => router.push("/onboarding") },
  { label: currentLang.value === "en" ? "Sign out" : "Đăng xuất", onClick: () => logout.submit() },
]);
</script>
