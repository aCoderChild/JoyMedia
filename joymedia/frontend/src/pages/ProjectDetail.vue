<template>
  <section class="flow-studio-container">
    <!-- 1. Google Flow Top Studio Header Bar -->
    <header class="flow-header-bar">
      <!-- Left: Back button & Project Title -->
      <div class="flex items-center gap-3 min-w-0">
        <Button appearance="subtle" class="!px-2.5 !py-1.5 shrink-0" @click="goBack" title="Back to campaign">
          <template #prefix>
            <span class="lucide-arrow-left size-4" />
          </template>
          <span class="hidden sm:inline">Campaigns</span>
        </Button>

        <div class="h-5 w-px bg-outline-border shrink-0" />

        <div class="min-w-0">
          <div class="flex items-center gap-2">
            <h1 class="text-base font-bold text-ink-primary truncate tracking-tight">
              {{ workspace?.campaign?.project_name || "Video Studio" }}
            </h1>
            <span
              v-if="workspace?.campaign"
              class="status-badge text-[11px] px-2 py-0.5 rounded-full font-semibold border shadow-2xs shrink-0"
              :class="statusBadgeClass(workspace.campaign.status)"
            >
              <span class="status-dot" :class="statusDotClass(workspace.campaign.status)" />
              <span>{{ workspace.campaign.status }}</span>
            </span>
          </div>
          <p class="text-xs text-ink-muted truncate hidden md:block">
            {{ workspace?.campaign?.product_name ? `${workspace.campaign.product_name} · ${settings?.video_style_name || 'AI Video'}` : "AI Video Production Studio" }}
          </p>
        </div>
      </div>

      <!-- Middle: Google Flow Quick Controls (Aspect Ratio & Duration) -->
      <div class="flex items-center gap-2">
        <!-- Aspect Ratio Switcher (16:9 / 9:16 / 1:1) -->
        <div class="flow-pill-group" title="Aspect Ratio">
          <button
            type="button"
            class="flow-pill-btn"
            :class="{ 'is-active': settingsForm.format === 'Landscape' }"
            @click="quickSelectAspect('Landscape')"
          >
            <svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="2" y="6" width="20" height="12" rx="2"/>
            </svg>
            <span class="hidden sm:inline">16:9</span>
          </button>
          <button
            type="button"
            class="flow-pill-btn"
            :class="{ 'is-active': settingsForm.format === 'Portrait' }"
            @click="quickSelectAspect('Portrait')"
          >
            <svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="6" y="2" width="12" height="20" rx="2"/>
            </svg>
            <span class="hidden sm:inline">9:16</span>
          </button>
          <button
            type="button"
            class="flow-pill-btn"
            :class="{ 'is-active': settingsForm.format === 'Square' }"
            @click="quickSelectAspect('Square')"
          >
            <svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="3" width="18" height="18" rx="2"/>
            </svg>
            <span class="hidden sm:inline">1:1</span>
          </button>
        </div>

        <!-- Duration Selector Chips -->
        <div class="flow-pill-group hidden lg:inline-flex" title="Video Duration">
          <button
            v-for="dur in [5, 10, 15, 30]"
            :key="dur"
            type="button"
            class="flow-pill-btn !px-2"
            :class="{ 'is-active': Number(settingsForm.duration) === dur }"
            @click="quickSelectDuration(dur)"
          >
            {{ dur }}s
          </button>
        </div>

        <!-- Continuity Mode Pill -->
        <button
          type="button"
          class="flow-pill-btn !px-2.5 !py-1 bg-surface-hover hover:bg-surface-active border border-outline-border hidden xl:inline-flex"
          :title="`Current continuity mode: ${currentContinuityMode}. Click to toggle.`"
          @click="toggleContinuityMode"
        >
          <span v-if="currentContinuityMode === 'Continuous'" class="text-indigo-500 font-bold">✦ Continuous</span>
          <span v-else class="text-indigo-500 font-bold">◫ Multi-shot</span>
        </button>
      </div>

      <!-- Right: Settings & Primary Magic Generate Button -->
      <div class="flex items-center gap-2">
        <Button
          appearance="subtle"
          class="!px-2.5"
          :loading="campaign.loading"
          @click="refresh"
          title="Refresh studio state"
        >
          <template #prefix>
            <span class="lucide-refresh-cw size-3.5" :class="{ 'animate-spin': campaign.loading }" />
          </template>
        </Button>

        <Button
          appearance="subtle"
          class="!px-3"
          @click="showSettings = !showSettings"
          title="Studio settings"
        >
          <template #prefix>
            <span class="lucide-settings size-3.5" />
          </template>
          <span class="hidden sm:inline">Settings</span>
        </Button>

        <!-- Google Flow Magic One-Click Generate Button -->
        <button
          type="button"
          class="flow-magic-btn"
          :class="{ 'is-active': isProductionActive || isAutoGenerating || generatingVideo }"
          :disabled="isAutoGenerating || generatingVideo || (production?.status === 'Running' && !isProductionActive)"
          @click="handleMagicGenerateClick"
        >
          <span v-if="isAutoGenerating" class="lucide-refresh-cw size-4 animate-spin" />
          <span v-else-if="isProductionActive" class="lucide-play size-4 animate-pulse" />
          <span v-else class="lucide-sparkles size-4" />

          <span v-if="isAutoGenerating">
            {{ autoGenerateStep || "Generating..." }}
          </span>
          <span v-else-if="isProductionActive">
            {{ production?.progress ? `${production.progress}% Generating...` : "Rendering Video..." }}
          </span>
          <span v-else-if="canRetryProduction">
            Retry Failed Shots
          </span>
          <span v-else-if="hasStoryboard">
            Generate Video
          </span>
          <span v-else>
            🪄 Generate Video
          </span>
        </button>
      </div>
    </header>

    <!-- Settings Dropdown Drawer (Collapsible) -->
    <div v-if="showSettings" class="p-4 rounded-2xl bg-surface-card border border-outline-border shadow-md animate-in fade-in duration-150">
      <div class="flex items-center justify-between pb-3 mb-3 border-b border-outline-border">
        <div>
          <h3 class="text-sm font-bold text-ink-primary">Studio Settings</h3>
          <p class="text-xs text-ink-secondary">Configure video duration, aspect ratio, motion style, and continuity model.</p>
        </div>
        <button type="button" class="text-ink-muted hover:text-ink-primary p-1 rounded-md" @click="showSettings = false">
          <span class="lucide-x size-4" />
        </button>
      </div>

      <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
        <div>
          <label class="block text-xs font-semibold text-ink-muted uppercase tracking-wider mb-1.5">Total Duration</label>
          <div class="flex items-center gap-2">
            <FormControl v-model="settingsForm.duration" type="number" min="2" max="60" class="w-full" />
            <span class="text-xs text-ink-muted shrink-0 font-medium">sec</span>
          </div>
        </div>

        <div>
          <label class="block text-xs font-semibold text-ink-muted uppercase tracking-wider mb-1.5">Delivery Format</label>
          <FormControl v-model="settingsForm.format" type="select" :options="['Landscape', 'Portrait', 'Square']" class="w-full" />
        </div>

        <div>
          <label class="block text-xs font-semibold text-ink-muted uppercase tracking-wider mb-1.5">Continuity Mode</label>
          <FormControl v-model="settingsForm.continuity_mode" type="select" :options="['Multi-shot', 'Continuous']" class="w-full" />
        </div>

        <div>
          <label class="block text-xs font-semibold text-ink-muted uppercase tracking-wider mb-1.5">Video Style</label>
          <FormControl
            v-model="settingsForm.video_style"
            type="select"
            :options="(videoStyles.data || []).map(s => ({ label: s.client_name, value: s.workflow_key }))"
            class="w-full"
          />
        </div>
      </div>

      <div class="flex items-center justify-end gap-2 mt-4 pt-3 border-t border-outline-border">
        <Button appearance="subtle" @click="showSettings = false">Cancel</Button>
        <Button variant="solid" :loading="savingSettings" @click="saveSettings">Save Settings</Button>
      </div>
    </div>

    <!-- Market Seller Friendly Helper Banner (Can be dismissed) -->
    <div v-if="!dismissSellerHelper && !finalVideo?.file && (!production || production.status === 'Draft' || production.status === 'Queued')" class="flow-seller-helper">
      <div class="flex items-center gap-3">
        <div class="p-2 rounded-xl bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 shrink-0">
          <svg class="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <path d="m9 12 2 2 4-4"/>
          </svg>
        </div>
        <div>
          <h4 class="text-xs font-bold text-ink-primary flex items-center gap-2">
            <span>Easy Video Generation for Sellers</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-600 font-semibold uppercase">3 Simple Steps</span>
          </h4>
          <p class="text-[11px] text-ink-secondary mt-0.5">
            <strong>1.</strong> Pick or upload product photos on the left →
            <strong>2.</strong> Choose your preferred length & format →
            <strong>3.</strong> Click the glowing <strong>"🪄 Generate Video"</strong> button. The AI handles storyboard, camera motion, and rendering automatically!
          </p>
        </div>
      </div>
      <button
        type="button"
        class="text-ink-muted hover:text-ink-primary text-xs shrink-0 p-1"
        title="Dismiss guide"
        @click="dismissSellerHelper = true"
      >
        ✕
      </button>
    </div>

    <!-- Main Google Flow 3-Zone Studio Grid -->
    <div class="flow-studio-grid">
      <!-- ==================================================================== -->
      <!-- ZONE A (LEFT): Media & Assets ("Ingredients")                         -->
      <!-- ==================================================================== -->
      <aside class="flex flex-col gap-3">
        <div class="p-4 rounded-2xl bg-surface-card border border-outline-border shadow-xs">
          <!-- Assets Header & Mode Switcher -->
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
              <span class="text-xs font-bold text-ink-primary uppercase tracking-wider">Media & Assets</span>
              <span class="text-[11px] px-1.5 py-0.5 rounded-full bg-surface-hover border border-outline-border text-ink-muted font-mono">
                {{ activeMediaTab === 'references' ? (filteredAssets.length) : (filteredOutputs.length) }}
              </span>
            </div>

            <!-- Tab switch: References vs Generated Outputs -->
            <div class="flex items-center gap-1 p-0.5 rounded-lg bg-surface-hover border border-outline-border text-[11px] font-semibold">
              <button
                type="button"
                class="px-2 py-0.5 rounded-md transition-all"
                :class="activeMediaTab === 'references' ? 'bg-surface-card text-ink-primary shadow-2xs font-bold' : 'text-ink-muted hover:text-ink-primary'"
                @click="activeMediaTab = 'references'"
              >
                Inputs
              </button>
              <button
                type="button"
                class="px-2 py-0.5 rounded-md transition-all"
                :class="activeMediaTab === 'outputs' ? 'bg-surface-card text-ink-primary shadow-2xs font-bold' : 'text-ink-muted hover:text-ink-primary'"
                @click="activeMediaTab = 'outputs'"
              >
                Outputs
              </button>
            </div>
          </div>

          <!-- Quick Upload Dropzone & Category Picker -->
          <div v-if="activeMediaTab === 'references'" class="mb-3 space-y-2">
            <div class="flex items-center gap-2">
              <FormControl
                v-model="selectedUploadCategory"
                type="select"
                :options="categoryUploadOptions"
                class="w-28 text-xs shrink-0"
              />
              <label class="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-xl border border-dashed border-indigo-300 dark:border-indigo-800 bg-indigo-50/50 dark:bg-indigo-950/20 text-indigo-700 dark:text-indigo-300 text-xs font-semibold cursor-pointer hover:bg-indigo-50 dark:hover:bg-indigo-950/40 transition-colors" :class="{ 'opacity-50 pointer-events-none': uploadingImages }">
                <span class="lucide-upload-cloud size-3.5" />
                <span>{{ uploadingImages ? `${uploadProgress}/${uploadTotal}...` : "+ Upload Media" }}</span>
                <input
                  ref="fileInput"
                  class="file-input-hidden"
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  multiple
                  :disabled="uploadingImages"
                  @change="uploadSelectedImages"
                />
              </label>
            </div>

            <Button
              appearance="subtle"
              class="w-full !py-1 text-xs justify-center"
              @click="openReferencePicker"
            >
              <template #prefix><span class="lucide-plus size-3.5" /></template>
              Choose from Campaign Assets
            </Button>
          </div>

          <!-- Category filter tabs -->
          <div v-if="activeMediaTab === 'references' && assetCategoryTabs.length > 1" class="flex items-center gap-1 overflow-x-auto pb-2 mb-2">
            <button
              v-for="tab in assetCategoryTabs"
              :key="tab.value"
              type="button"
              class="px-2 py-0.5 rounded-md text-[11px] font-semibold shrink-0 transition-all"
              :class="activeAssetCategory === tab.value ? 'bg-indigo-600 text-white' : 'bg-surface-hover text-ink-secondary hover:text-ink-primary border border-outline-border'"
              @click="activeAssetCategory = tab.value"
            >
              {{ tab.label }}
            </button>
          </div>

          <!-- Reference Assets List -->
          <div v-if="activeMediaTab === 'references'" class="space-y-2 max-h-[520px] overflow-y-auto pr-1">
            <div
              v-for="asset in filteredAssets"
              :key="asset.name"
              class="group relative flex items-center gap-2.5 p-2 rounded-xl bg-surface-hover border border-outline-border hover:border-indigo-400 transition-all cursor-pointer"
              @click="previewAssetOnCanvas(asset)"
            >
              <div class="w-12 h-12 rounded-lg overflow-hidden bg-black/10 shrink-0 border border-outline-border flex items-center justify-center">
                <img v-if="asset.file" :src="asset.file" :alt="asset.asset_name" class="w-full h-full object-cover" />
                <span v-else class="lucide-image size-4 text-ink-muted" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center justify-between gap-1 mb-0.5">
                  <span class="text-[10px] px-1.5 py-0.2 rounded font-bold uppercase tracking-wider" :class="categoryBadgeClass(asset.asset_category)">
                    {{ asset.asset_category || 'Reference' }}
                  </span>
                </div>
                <p class="text-xs font-semibold text-ink-primary truncate" :title="asset.asset_name">
                  {{ asset.asset_name }}
                </p>
                <span class="text-[10px] text-ink-muted">Click to preview</span>
              </div>
            </div>

            <div v-if="!filteredAssets.length" class="text-center py-8 text-xs text-ink-muted">
              <span class="lucide-image size-6 mx-auto mb-1 opacity-50 block" />
              <p>No reference images uploaded yet.</p>
              <span class="text-[11px] text-indigo-600 font-semibold cursor-pointer" @click="$refs.fileInput?.click()">
                + Upload your product photo
              </span>
            </div>
          </div>

          <!-- Machine Generated Outputs List -->
          <div v-else class="space-y-2 max-h-[520px] overflow-y-auto pr-1">
            <div
              v-for="output in filteredOutputs"
              :key="output.name"
              class="group relative flex items-center gap-2.5 p-2 rounded-xl bg-surface-hover border border-outline-border hover:border-purple-400 transition-all cursor-pointer"
              @click="previewOutputOnCanvas(output)"
            >
              <div class="w-12 h-12 rounded-lg overflow-hidden bg-black/10 shrink-0 border border-outline-border flex items-center justify-center relative">
                <video
                  v-if="output.file && (output.media_type === 'Video' || isVideoUrl(output.file))"
                  :src="output.file"
                  class="w-full h-full object-cover"
                />
                <img v-else-if="output.file" :src="output.file" class="w-full h-full object-cover" />
                <span v-else class="lucide-film size-4 text-ink-muted" />

                <div v-if="output.media_type === 'Video' || isVideoUrl(output.file)" class="absolute inset-0 flex items-center justify-center bg-black/30">
                  <span class="lucide-play size-3 text-white fill-current" />
                </div>
              </div>
              <div class="min-w-0 flex-1">
                <span class="text-[10px] px-1.5 py-0.2 rounded font-bold uppercase tracking-wider bg-purple-500/15 text-purple-700 dark:text-purple-300">
                  {{ output.asset_category || 'Generated' }}
                </span>
                <p class="text-xs font-semibold text-ink-primary truncate mt-0.5" :title="output.asset_name">
                  {{ output.asset_name }}
                </p>
                <div class="flex items-center gap-2 text-[10px] text-ink-muted">
                  <span>{{ formatDate(output.modified) }}</span>
                  <a v-if="output.file" :href="output.file" download class="text-indigo-600 hover:underline">Download</a>
                </div>
              </div>
            </div>

            <div v-if="!filteredOutputs.length" class="text-center py-8 text-xs text-ink-muted">
              <span class="lucide-film size-6 mx-auto mb-1 opacity-50 block" />
              <p>No generated clips yet.</p>
              <span class="text-[11px]">Rendered shots will appear here once video is generated.</span>
            </div>
          </div>
        </div>

        <!-- Creative Brief Pill Card (Customer Intent) -->
        <div class="p-3.5 rounded-2xl bg-surface-card border border-outline-border shadow-xs text-xs">
          <div class="flex items-center justify-between mb-2">
            <span class="font-bold uppercase tracking-wider text-[11px] text-indigo-600 dark:text-indigo-400">Creative Brief</span>
            <span class="text-[10px] text-ink-muted">Intent</span>
          </div>
          <div class="space-y-1.5">
            <div>
              <span class="text-[10px] text-ink-muted uppercase">Product:</span>
              <p class="font-semibold text-ink-primary truncate">{{ workspace?.campaign?.product_name || "Featured Item" }}</p>
            </div>
            <div v-if="workspace?.campaign?.target_audience">
              <span class="text-[10px] text-ink-muted uppercase">Audience:</span>
              <p class="text-ink-secondary line-clamp-2">{{ workspace.campaign.target_audience }}</p>
            </div>
          </div>
        </div>
      </aside>

      <!-- ==================================================================== -->
      <!-- ZONE B (CENTER): Interactive Canvas Player & Google Flow Scene Builder-->
      <!-- ==================================================================== -->
      <main class="flex flex-col gap-4 min-w-0">
        <!-- Interactive Preview Canvas -->
        <div class="flow-canvas-wrap">
          <!-- Canvas Top Pill Badge (Mode & Details) -->
          <div class="absolute top-3 left-3 z-20 flex items-center gap-2">
            <span class="text-[11px] px-2.5 py-1 rounded-full font-bold uppercase tracking-wider backdrop-blur-md bg-black/60 text-white shadow-xs flex items-center gap-1.5">
              <span class="size-2 rounded-full" :class="activeCanvasMedia?.isVideo ? 'bg-emerald-400 animate-pulse' : 'bg-indigo-400'" />
              <span>{{ activeCanvasMedia?.title || (finalVideo?.file ? 'Master Deliverable' : 'Canvas Preview') }}</span>
            </span>
            <span v-if="activeCanvasMedia?.duration" class="text-[10px] px-2 py-0.5 rounded-md font-mono bg-black/40 backdrop-blur-xs text-white/90">
              {{ activeCanvasMedia.duration }}s
            </span>
          </div>

          <!-- Canvas Top Right: Aspect Ratio & Download Actions -->
          <div class="absolute top-3 right-3 z-20 flex items-center gap-2">
            <a
              v-if="activeCanvasMedia?.url"
              :href="activeCanvasMedia.url"
              download
              class="p-1.5 rounded-lg bg-black/50 hover:bg-black/70 text-white backdrop-blur-md transition-colors"
              title="Download preview video/image"
            >
              <span class="lucide-download size-4" />
            </a>
            <span class="text-[11px] px-2 py-1 rounded-md font-mono font-bold bg-black/50 text-white/90 backdrop-blur-md">
              {{ settingsForm.format === 'Portrait' ? '9:16' : settingsForm.format === 'Square' ? '1:1' : '16:9' }}
            </span>
          </div>

          <!-- Video / Image Preview Screen Frame -->
          <div
            class="flow-canvas-inner"
            :class="{
              'ratio-landscape': settingsForm.format === 'Landscape',
              'ratio-portrait': settingsForm.format === 'Portrait',
              'ratio-square': settingsForm.format === 'Square'
            }"
          >
            <!-- 1. Video Playing State -->
            <video
              v-if="activeCanvasMedia?.isVideo && activeCanvasMedia?.url"
              :key="activeCanvasMedia.url"
              :src="activeCanvasMedia.url"
              class="flow-video-player"
              controls
              autoplay
              loop
              preload="metadata"
            />

            <!-- 2. Master Final Video -->
            <video
              v-else-if="finalVideo?.file && (!activeCanvasMedia || activeCanvasMedia.isMaster)"
              :key="finalVideo.file"
              :src="finalVideo.file"
              class="flow-video-player"
              controls
              autoplay
              loop
              preload="metadata"
            />

            <!-- 3. Image Reference / Frame Preview -->
            <img
              v-else-if="activeCanvasMedia?.url"
              :key="activeCanvasMedia.url"
              :src="activeCanvasMedia.url"
              :alt="activeCanvasMedia.title"
              class="flow-video-player object-contain"
            />

            <!-- 4. Selected Shot Frame Fallback -->
            <img
              v-else-if="selectedShotFrame?.file"
              :src="selectedShotFrame.file"
              :alt="selectedShotFrame.name"
              class="flow-video-player object-contain"
            />

            <!-- 5. Generating Live Progress Overlay on Canvas -->
            <div v-else-if="isProductionActive || isAutoGenerating" class="flex flex-col items-center justify-center text-center p-6 text-white max-w-sm">
              <div class="relative size-16 mb-3 flex items-center justify-center">
                <span class="lucide-refresh-cw size-10 animate-spin text-indigo-400" />
                <span class="absolute text-xs font-bold font-mono">{{ production?.progress || 0 }}%</span>
              </div>
              <h3 class="text-sm font-bold">{{ isAutoGenerating ? autoGenerateStep : "Rendering Video Shots..." }}</h3>
              <p class="text-xs text-slate-300 mt-1">
                {{ production?.completed_jobs || 0 }} of {{ production?.total_jobs || expectedShotCount }} shots finished
              </p>
              <div class="flex items-center gap-3 mt-3 text-[11px] font-mono text-slate-400">
                <span>Elapsed: {{ formatElapsed(productionElapsedSeconds) }}</span>
                <span>·</span>
                <span>ETA: {{ estimatedFinishLabel }}</span>
              </div>
            </div>

            <!-- 6. Empty State: No Video Yet -->
            <div v-else class="flex flex-col items-center justify-center text-center p-6 text-slate-400">
              <div class="size-14 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center text-indigo-400 mb-3 shadow-lg">
                <span class="lucide-clapperboard size-7" />
              </div>
              <h3 class="text-sm font-semibold text-white">Google Flow Cinema Canvas</h3>
              <p class="text-xs text-slate-400 mt-1 max-w-xs">
                Select a shot in the Scene Builder to preview, or click <strong>Generate Video</strong> to produce your commercial.
              </p>
            </div>
          </div>

          <!-- Quality Review Notice on Canvas (if review pending for this shot) -->
          <div v-if="activeShotReview" class="absolute bottom-3 left-3 right-3 z-20 flex items-center justify-between gap-3 p-2.5 rounded-xl bg-slate-900/90 backdrop-blur-md border border-indigo-500/40 text-white shadow-xl">
            <div class="flex items-center gap-2">
              <span class="size-2 rounded-full bg-amber-400 animate-ping" />
              <span class="text-xs font-semibold">Shot {{ activeShotReview.shot_number || '?' }} Review:</span>
              <span class="text-xs text-slate-300 truncate max-w-[200px]">{{ activeShotReview.title }}</span>
            </div>
            <div class="flex items-center gap-2">
              <Button
                size="sm"
                variant="solid"
                class="!bg-emerald-600 hover:!bg-emerald-700 !text-white text-xs !py-1 !px-2.5"
                :loading="reviewingMap[activeShotReview.name] === 'approve'"
                @click="reviewAction('approve', activeShotReview)"
              >
                Approve
              </Button>
              <Button
                size="sm"
                appearance="subtle"
                class="!text-rose-400 hover:!bg-rose-950/40 text-xs !py-1 !px-2.5"
                :loading="reviewingMap[activeShotReview.name] === 'reject'"
                @click="reviewAction('reject', activeShotReview)"
              >
                Reject
              </Button>
            </div>
          </div>
        </div>

        <!-- ================================================================== -->
        <!-- GOOGLE FLOW SCENE BUILDER & TIMELINE STRIP                         -->
        <!-- ================================================================== -->
        <section class="flow-scene-builder">
          <div class="flex items-center justify-between mb-3">
            <div>
              <div class="flex items-center gap-2">
                <span class="text-xs font-bold text-ink-primary uppercase tracking-wider">Scene Builder</span>
                <span class="text-[11px] px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 font-semibold font-mono">
                  {{ allShotsList.length }} Shots · {{ settingsForm.duration }}s Total
                </span>
                <span class="text-[11px] text-ink-muted hidden sm:inline">· Trim & arrange sequence</span>
              </div>
            </div>

            <div class="flex items-center gap-2">
              <Button
                v-if="!hasStoryboard"
                variant="solid"
                class="!py-1 !px-3 text-xs"
                :loading="generatingPlan"
                :disabled="!settings || settings.status !== 'Draft'"
                @click="generatePlan"
              >
                <template #prefix><span class="lucide-sparkles size-3.5" /></template>
                Auto-Draft Storyboard
              </Button>
              <Button
                v-else-if="plan?.shots?.length"
                variant="solid"
                class="!py-1 !px-3 text-xs !bg-emerald-600 hover:!bg-emerald-700 !text-white"
                :loading="applyingPlan"
                @click="applyPlan"
              >
                <template #prefix><span class="lucide-check size-3.5" /></template>
                Apply Storyboard
              </Button>
              <Button
                v-else
                appearance="subtle"
                class="!py-1 !px-2.5 text-xs"
                :loading="revisingStoryboard"
                @click="createAnotherVersion"
                title="Create another version"
              >
                New Version
              </Button>
            </div>
          </div>

          <!-- Visual Shots Timeline Track -->
          <div v-if="allShotsList.length" class="flow-timeline-scroll">
            <template v-for="(shot, index) in allShotsList" :key="shot.name || shot.shot_number">
              <!-- Shot Card in Timeline -->
              <div
                class="flow-shot-tile"
                :class="{ 'is-selected': isShotSelected(shot, index) }"
                @click="selectShot(shot, index)"
              >
                <!-- Shot Header -->
                <div class="flex items-center justify-between mb-1.5">
                  <span class="text-[11px] font-bold text-ink-primary flex items-center gap-1">
                    <span class="lucide-film size-3 text-indigo-500" />
                    <span>Shot {{ shot.shot_number }}</span>
                  </span>
                  <span
                    class="text-[9.5px] px-1.5 py-0.2 rounded font-semibold uppercase"
                    :class="getShotStatusClass(shot)"
                  >
                    {{ getShotStatusLabel(shot) }}
                  </span>
                </div>

                <!-- Shot Thumbnail -->
                <div class="flow-shot-thumb">
                  <!-- Video if review preview exists -->
                  <video
                    v-if="getShotReview(shot)?.preview_url"
                    :src="getShotReview(shot).preview_url"
                    class="w-full h-full object-cover"
                    muted
                    preload="metadata"
                  />
                  <!-- Image thumbnail -->
                  <img
                    v-else-if="getShotFirstFrame(shot, Boolean(plan?.shots?.length)).file"
                    :src="getShotFirstFrame(shot, Boolean(plan?.shots?.length)).file"
                    class="w-full h-full object-cover"
                  />
                  <div v-else class="text-ink-muted text-[10px] flex flex-col items-center">
                    <span class="lucide-film size-4 mb-0.5 opacity-60" />
                    <span>Shot {{ shot.shot_number }}</span>
                  </div>
                </div>

                <!-- Shot Direction Snippet -->
                <p class="text-[11px] text-ink-secondary truncate mt-1.5 font-medium" :title="shot.subject || shot.subject_identity">
                  {{ shot.subject || shot.subject_identity || shot.action || shot.action_plot || 'Scene action' }}
                </p>

                <!-- Trimming & Duration Handle -->
                <div class="flow-trim-control">
                  <span class="text-[10px] text-ink-muted font-mono">
                    {{ estimateShotDuration(shot) }}s
                  </span>
                  <div class="flex items-center gap-1">
                    <button
                      type="button"
                      class="text-ink-muted hover:text-indigo-600 px-1 font-bold"
                      title="Trim shot duration (-0.5s)"
                      @click.stop="quickTrimShot(shot, -0.5)"
                    >
                      -
                    </button>
                    <button
                      type="button"
                      class="text-ink-muted hover:text-indigo-600 px-1 font-bold"
                      title="Extend shot duration (+0.5s)"
                      @click.stop="quickTrimShot(shot, 0.5)"
                    >
                      +
                    </button>
                  </div>
                </div>
              </div>

              <!-- Connecting Transition Arrow Between Shots -->
              <div v-if="index < allShotsList.length - 1" class="flex flex-col items-center justify-center shrink-0 text-indigo-400">
                <span class="text-[9px] font-mono text-ink-muted mb-0.5">
                  {{ currentContinuityMode === 'Continuous' ? '✦ Auto' : '◫ Cut' }}
                </span>
                <div class="flex items-center">
                  <div class="w-6 h-0.5 bg-indigo-200 dark:bg-indigo-900" />
                  <span class="lucide-chevron-right size-3.5 -ml-1 text-indigo-500 font-bold" />
                </div>
              </div>
            </template>
          </div>

          <!-- Empty Timeline state -->
          <div v-else class="text-center py-8 rounded-xl border border-dashed border-outline-border">
            <span class="lucide-clapperboard size-8 mx-auto mb-2 text-ink-muted opacity-60 block" />
            <h4 class="text-xs font-bold text-ink-primary">No shots planned yet</h4>
            <p class="text-xs text-ink-muted mt-0.5">
              Click <strong>"🪄 Generate Video"</strong> to let AI automatically generate the storyboard sequence, or click below to draft it.
            </p>
            <Button
              variant="solid"
              class="mt-3 !py-1 !px-3 text-xs"
              :loading="generatingPlan"
              :disabled="!settings || settings.status !== 'Draft'"
              @click="generatePlan"
            >
              <template #prefix><span class="lucide-sparkles size-3.5" /></template>
              Draft Storyboard Now
            </Button>
          </div>
        </section>
      </main>

      <!-- ==================================================================== -->
      <!-- ZONE C (RIGHT): Shot Inspector & Scene Director                      -->
      <!-- ==================================================================== -->
      <aside class="flow-inspector-col flex flex-col gap-3">
        <!-- If a Shot is selected: Shot Inspector -->
        <div v-if="activeSelectedShot" class="p-4 rounded-2xl bg-surface-card border border-outline-border shadow-xs">
          <div class="flex items-center justify-between pb-3 mb-3 border-b border-outline-border">
            <div class="flex items-center gap-2">
              <span class="text-xs font-bold text-ink-primary uppercase tracking-wider">
                Shot {{ activeSelectedShot.shot_number }} Director
              </span>
              <span class="text-[10px] px-1.5 py-0.5 rounded font-mono bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600">
                {{ estimateShotDuration(activeSelectedShot) }}s
              </span>
            </div>
            <button
              type="button"
              class="text-xs text-indigo-600 font-medium hover:underline"
              @click="selectedShotIndex = null"
            >
              Overview
            </button>
          </div>

          <!-- Human-Friendly Form Fields for Market Sellers -->
          <div class="space-y-3">
            <div>
              <label class="flex items-center gap-1.5 text-xs font-bold text-ink-primary mb-1">
                <span>🎯</span>
                <span>Product & Subject (Chủ thể)</span>
              </label>
              <FormControl
                v-if="plan?.shots?.length"
                v-model="activeSelectedShot.subject"
                type="textarea"
                rows="2"
                placeholder="Product focus, appearance, brand elements..."
              />
              <FormControl
                v-else
                v-model="activeSelectedShot.subject_identity"
                type="textarea"
                rows="2"
                placeholder="Product focus, appearance, brand elements..."
              />
            </div>

            <div>
              <label class="flex items-center gap-1.5 text-xs font-bold text-ink-primary mb-1">
                <span>🎬</span>
                <span>Action & Motion (Hành động)</span>
              </label>
              <FormControl
                v-if="plan?.shots?.length"
                v-model="activeSelectedShot.motion"
                type="textarea"
                rows="2"
                placeholder="What happens in this shot? Pouring, spinning, smiling..."
              />
              <FormControl
                v-else
                v-model="activeSelectedShot.action_plot"
                type="textarea"
                rows="2"
                placeholder="What happens in this shot? Pouring, spinning, smiling..."
              />
            </div>

            <div>
              <label class="flex items-center gap-1.5 text-xs font-bold text-ink-primary mb-1">
                <span>🎥</span>
                <span>Camera Direction (Góc máy)</span>
              </label>
              <FormControl
                v-if="plan?.shots?.length"
                v-model="activeSelectedShot.camera"
                type="textarea"
                rows="2"
                placeholder="Slow pan, zoom-in, orbital rotation, static eye-level..."
              />
              <FormControl
                v-else
                v-model="activeSelectedShot.camera_direction"
                type="textarea"
                rows="2"
                placeholder="Slow pan, zoom-in, orbital rotation, static eye-level..."
              />
            </div>

            <div>
              <label class="flex items-center gap-1.5 text-xs font-bold text-ink-primary mb-1">
                <span>💡</span>
                <span>Setting & Lighting (Bối cảnh)</span>
              </label>
              <FormControl
                v-if="plan?.shots?.length"
                v-model="activeSelectedShot.lighting"
                type="textarea"
                rows="2"
                placeholder="Studio backdrop, sunlit cafe, warm soft shadows..."
              />
              <FormControl
                v-else
                v-model="activeSelectedShot.environment"
                type="textarea"
                rows="2"
                placeholder="Studio backdrop, sunlit cafe, warm soft shadows..."
              />
            </div>

            <div>
              <label class="flex items-center gap-1.5 text-xs font-bold text-ink-primary mb-1">
                <span>🎵</span>
                <span>Audio & Voiceover (Âm thanh)</span>
              </label>
              <FormControl
                v-if="plan?.shots?.length"
                v-model="activeSelectedShot.audio"
                type="textarea"
                rows="2"
                placeholder="Sound effect: fizz, voiceover hook, upbeat rhythm..."
              />
              <FormControl
                v-else
                v-model="activeSelectedShot.audio_direction"
                type="textarea"
                rows="2"
                placeholder="Sound effect: fizz, voiceover hook, upbeat rhythm..."
              />
            </div>
          </div>

          <!-- Action Buttons for Selected Shot -->
          <div class="flex items-center justify-between gap-2 mt-4 pt-3 border-t border-outline-border">
            <Button
              v-if="!plan?.shots?.length && activeSelectedShot.name"
              type="button"
              variant="solid"
              class="flex-1 justify-center text-xs"
              :loading="Boolean(savingShotMap[activeSelectedShot.name])"
              :disabled="settings?.status !== 'Draft'"
              @click="saveShot(activeSelectedShot)"
            >
              <template #prefix><span class="lucide-check size-3.5" /></template>
              Save Shot
            </Button>

            <Button
              v-if="!plan?.shots?.length && activeSelectedShot.name"
              type="button"
              appearance="subtle"
              class="text-xs"
              :loading="Boolean(regeneratingShotMap[activeSelectedShot.name])"
              title="Regenerate this specific shot"
              @click="regenerateSingleShot(activeSelectedShot)"
            >
              <template #prefix><span class="lucide-refresh-cw size-3.5" /></template>
              Regenerate
            </Button>
          </div>

          <!-- Advanced MiniMax Model Prompt (Power Users Only) -->
          <details class="mt-4 pt-2 border-t border-outline-border text-xs group">
            <summary class="cursor-pointer text-ink-muted hover:text-ink-primary font-mono text-[11px] flex items-center justify-between select-none py-1">
              <span>⋯ Advanced AI Prompt</span>
              <span class="text-[9.5px] uppercase tracking-wider bg-surface-hover px-1 py-0.5 rounded border border-outline-border">MiniMax H3</span>
            </summary>
            <div class="mt-2 p-2.5 bg-surface-hover/60 rounded-lg border border-outline-border space-y-1">
              <p class="text-[10.5px] text-ink-muted">
                Compiled model prompt stored in DB for exact reproducible generation.
              </p>
              <FormControl v-model="activeSelectedShot.generation_prompt" type="textarea" rows="3" />
            </div>
          </details>
        </div>

        <!-- If No Shot is Selected: Project Overview & Reviews -->
        <div v-else class="space-y-3">
          <!-- Quality Review Card -->
          <div v-if="reviews?.length" class="p-4 rounded-2xl bg-surface-card border border-outline-border shadow-xs">
            <div class="flex items-center justify-between mb-3">
              <span class="text-xs font-bold text-ink-primary uppercase tracking-wider">Quality Review</span>
              <span class="text-xs px-2 py-0.5 rounded-full font-bold" :class="pendingReviewsCount > 0 ? 'bg-amber-500/15 text-amber-600' : 'bg-emerald-500/15 text-emerald-600'">
                {{ pendingReviewsCount }} Pending
              </span>
            </div>

            <div class="space-y-2 max-h-56 overflow-y-auto pr-1">
              <div
                v-for="rev in reviews"
                :key="rev.name"
                class="flex items-center justify-between p-2 rounded-xl bg-surface-hover border border-outline-border"
              >
                <div class="flex items-center gap-2 min-w-0">
                  <div class="w-8 h-8 rounded bg-black/20 shrink-0 overflow-hidden flex items-center justify-center">
                    <video v-if="rev.preview_url" :src="rev.preview_url" class="w-full h-full object-cover" />
                    <img v-else-if="rev.image_url" :src="rev.image_url" class="w-full h-full object-cover" />
                    <span v-else class="lucide-film size-3.5 text-ink-muted" />
                  </div>
                  <div class="min-w-0">
                    <span class="text-xs font-bold text-ink-primary block truncate">Shot {{ rev.shot_number || '?' }}</span>
                    <span class="text-[10px] text-ink-muted">{{ rev.status }}</span>
                  </div>
                </div>

                <div class="flex items-center gap-1">
                  <button
                    v-if="rev.status === 'Pending'"
                    type="button"
                    class="p-1 rounded bg-emerald-600 text-white hover:bg-emerald-700"
                    title="Approve shot"
                    @click="reviewAction('approve', rev)"
                  >
                    <span class="lucide-check size-3" />
                  </button>
                  <button
                    v-if="rev.status === 'Pending'"
                    type="button"
                    class="p-1 rounded bg-rose-100 text-rose-600 hover:bg-rose-200"
                    title="Reject shot"
                    @click="reviewAction('reject', rev)"
                  >
                    <span class="lucide-x size-3" />
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- Video Specs Overview -->
          <div class="p-4 rounded-2xl bg-surface-card border border-outline-border shadow-xs text-xs space-y-2.5">
            <span class="font-bold uppercase tracking-wider text-[11px] text-ink-muted block">Production Specs</span>
            <div class="flex items-center justify-between py-1 border-b border-outline-subtle">
              <span class="text-ink-secondary">Length:</span>
              <strong class="text-ink-primary">{{ settingsForm.duration }} seconds</strong>
            </div>
            <div class="flex items-center justify-between py-1 border-b border-outline-subtle">
              <span class="text-ink-secondary">Format:</span>
              <strong class="text-ink-primary">{{ settingsForm.format }} ({{ settingsForm.format === 'Portrait' ? '9:16' : settingsForm.format === 'Square' ? '1:1' : '16:9' }})</strong>
            </div>
            <div class="flex items-center justify-between py-1 border-b border-outline-subtle">
              <span class="text-ink-secondary">Style:</span>
              <strong class="text-ink-primary">{{ settings?.video_style_name || 'Commercial Default' }}</strong>
            </div>
            <div class="flex items-center justify-between py-1">
              <span class="text-ink-secondary">Continuity:</span>
              <strong class="text-indigo-600">{{ currentContinuityMode }}</strong>
            </div>
          </div>
        </div>
      </aside>
    </div>

    <!-- Reference Picker Backdrop Modal -->
    <div v-if="showReferencePicker" class="reference-picker-backdrop" @click.self="showReferencePicker = false">
      <div class="reference-picker-panel">
        <div class="flex items-center justify-between mb-4">
          <div>
            <p class="eyebrow">Campaign Library</p>
            <h2 class="text-base font-bold text-ink-primary">Select Project References</h2>
          </div>
          <button type="button" class="text-ink-muted text-lg hover:text-ink-primary" @click="showReferencePicker = false">×</button>
        </div>

        <div v-if="referenceCandidates.length" class="asset-grid">
          <button
            v-for="asset in referenceCandidates"
            :key="asset.name"
            type="button"
            class="asset-tile text-left"
            :disabled="asset.selected || selectingReference"
            @click="selectReference(asset)"
          >
            <img v-if="asset.file" :src="asset.file" :alt="asset.asset_name" />
            <div v-else class="asset-placeholder"><span>Image</span></div>
            <span class="asset-name-label">{{ asset.asset_name }}</span>
            <span v-if="asset.selected" class="text-xs text-indigo-600 font-semibold">Selected</span>
          </button>
        </div>
        <div v-else class="empty-panel">
          <p>No campaign assets available.</p>
          <span class="text-xs text-ink-muted">Upload an image to add it directly to this project.</span>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { Button, FormControl, call, createResource, toast, upload as uploadFile } from "frappe-ui";
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();
const projectName = computed(() => route.params.name);

// Frappe UI Backend Resources
const campaign = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_project_workspace",
  params: { name: projectName.value },
  auto: true,
});
const productionResource = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_campaign_production",
  params: { name: projectName.value },
  auto: true,
});
const reviewResource = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_campaign_reviews",
  params: { name: projectName.value },
  auto: true,
});
const videoStyles = createResource({
  url: "joymedia.joymedia.doctype.media_project.media_project.get_video_styles",
  auto: true,
});

// UI State
const plan = ref(null);
const showSettings = ref(false);
const savingSettings = ref(false);
const generatingPlan = ref(false);
const applyingPlan = ref(false);
const applyError = ref("");
const applySuccess = ref(false);
const generatingVideo = ref(false);
const retryingFailedScenes = ref(false);
const revisingStoryboard = ref(false);
const uploadingImages = ref(false);
const uploadProgress = ref(0);
const uploadTotal = ref(0);
const uploadError = ref("");
const fileInput = ref(null);
const showReferencePicker = ref(false);
const selectingReference = ref(false);
const referenceCandidates = ref([]);
const dismissSellerHelper = ref(false);

// Google Flow Selection & Studio State
const selectedShotIndex = ref(null);
const activeMediaTab = ref("references"); // 'references' | 'outputs'
const activeAssetCategory = ref("All");
const selectedUploadCategory = ref("Product");
const categoryUploadOptions = ["Product", "Character", "Background", "Brand", "Style", "Reference"];
const activeOutputCategory = ref("All");
const activeCanvasPreview = ref(null); // Explicit media clicked by user

// One-Click Magic Generate Flow State for Beginners
const isAutoGenerating = ref(false);
const autoGenerateStep = ref("");

// Shot editing & action maps
const savingShotMap = reactive({});
const regeneratingShotMap = reactive({});
const reviewingMap = reactive({});

const settingsForm = reactive({ duration: 8, format: "Landscape", video_style: "", continuity_mode: "Multi-shot" });
const workspace = computed(() => campaign.data);
const settings = computed(() => workspace.value?.video_settings);
const production = computed(() => productionResource.data || workspace.value?.production);
const reviews = computed(() => reviewResource.data || workspace.value?.reviews || []);
const finalVideo = computed(() => production.value?.final_video || workspace.value?.final_video);
const expectedShotCount = computed(() => Number(production.value?.total_jobs || workspace.value?.storyboard?.length || 0));

const hasStoryboard = computed(() => Boolean(workspace.value?.storyboard?.length));

const allShotsList = computed(() => {
  if (plan.value?.shots?.length) return plan.value.shots;
  return workspace.value?.storyboard || [];
});

const activeSelectedShot = computed(() => {
  const list = allShotsList.value;
  if (!list.length) return null;
  if (selectedShotIndex.value !== null && list[selectedShotIndex.value]) {
    return list[selectedShotIndex.value];
  }
  return list[0];
});

const selectedShotFrame = computed(() => {
  if (!activeSelectedShot.value) return null;
  return getShotFirstFrame(activeSelectedShot.value, Boolean(plan.value?.shots?.length));
});

// Canvas Media Active Selection
const activeCanvasMedia = computed(() => {
  if (activeCanvasPreview.value) {
    return activeCanvasPreview.value;
  }
  // If master final video is ready, show it by default
  if (finalVideo.value?.file) {
    return {
      title: "Master Deliverable",
      url: finalVideo.value.file,
      isVideo: true,
      isMaster: true,
      duration: settingsForm.duration,
    };
  }
  // If selected shot has a rendered preview video in reviews, show that!
  if (activeSelectedShot.value) {
    const rev = getShotReview(activeSelectedShot.value);
    if (rev?.preview_url) {
      return {
        title: `Shot ${activeSelectedShot.value.shot_number} Preview`,
        url: rev.preview_url,
        isVideo: true,
        duration: rev.duration_seconds || estimateShotDuration(activeSelectedShot.value),
      };
    }
    const frame = selectedShotFrame.value;
    if (frame?.file) {
      return {
        title: `Shot ${activeSelectedShot.value.shot_number} Starting Frame`,
        url: frame.file,
        isVideo: false,
        duration: estimateShotDuration(activeSelectedShot.value),
      };
    }
  }
  return null;
});

const activeShotReview = computed(() => {
  if (!activeSelectedShot.value) return null;
  return getShotReview(activeSelectedShot.value);
});

// Categories & Filtering
const assetCategoryTabs = computed(() => {
  const assets = workspace.value?.assets || [];
  const tabs = [{ label: `All (${assets.length})`, value: "All" }];
  const counts = {};
  for (const a of assets) {
    const cat = a.asset_category || "Reference";
    counts[cat] = (counts[cat] || 0) + 1;
  }
  for (const cat of Object.keys(counts).sort()) {
    tabs.push({ label: `${cat} (${counts[cat]})`, value: cat });
  }
  return tabs;
});

const filteredAssets = computed(() => {
  const assets = workspace.value?.assets || [];
  if (activeAssetCategory.value === "All") return assets;
  return assets.filter((a) => (a.asset_category || "Reference") === activeAssetCategory.value);
});

const filteredOutputs = computed(() => {
  const outputs = workspace.value?.outputs || [];
  if (activeOutputCategory.value === "All") return outputs;
  return outputs.filter((o) => (o.asset_category || "Shot Output") === activeOutputCategory.value);
});

function isVideoUrl(url) {
  if (!url) return false;
  return /\.(mp4|webm|mov|m4v)(\?.*)?$/i.test(url);
}

function formatDate(dateStr) {
  if (!dateStr) return "";
  try {
    const d = new Date(dateStr.replace(" ", "T"));
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return dateStr;
  }
}

function categoryBadgeClass(category) {
  const cat = String(category || "reference").toLowerCase().replace(/\s+/g, "-");
  return `category-${cat}`;
}

function statusBadgeClass(status) {
  const s = String(status || "draft").toLowerCase();
  if (s === "completed") return "bg-emerald-500/10 text-emerald-600 border-emerald-300 dark:border-emerald-800";
  if (s === "generating" || s === "running") return "bg-indigo-500/10 text-indigo-600 border-indigo-300 dark:border-indigo-800";
  if (s === "review") return "bg-amber-500/10 text-amber-600 border-amber-300 dark:border-amber-800";
  return "bg-surface-card border-outline-border text-ink-primary";
}

function statusDotClass(status) {
  const s = String(status || "draft").toLowerCase();
  if (s === "completed") return "text-emerald-500 bg-emerald-500";
  if (s === "generating" || s === "running") return "text-indigo-500 bg-indigo-500 animate-pulse";
  if (s === "review") return "text-amber-500 bg-amber-500";
  return "text-slate-400 bg-slate-400";
}

function getShotStatusClass(shot) {
  const rev = getShotReview(shot);
  if (rev?.status === "Approved") return "bg-emerald-500/15 text-emerald-600";
  if (rev?.status === "Pending") return "bg-amber-500/15 text-amber-600";
  if (rev?.status === "Rejected") return "bg-rose-500/15 text-rose-600";
  if (isProductionActive.value) return "bg-indigo-500/15 text-indigo-600";
  return "bg-surface-card border border-outline-border text-ink-muted";
}

function getShotStatusLabel(shot) {
  const rev = getShotReview(shot);
  if (rev?.status) return rev.status;
  if (isProductionActive.value) return "Rendering";
  return "Planned";
}

function getShotReview(shot) {
  const num = shot.shot_number;
  const revs = reviews.value || [];
  return revs.find((r) => r.shot_number === num || r.shot_name === shot.name);
}

function isShotSelected(shot, index) {
  if (selectedShotIndex.value !== null) {
    return selectedShotIndex.value === index;
  }
  return index === 0;
}

function selectShot(shot, index) {
  selectedShotIndex.value = index;
  activeCanvasPreview.value = null; // Auto-focus canvas on this shot
}

function previewAssetOnCanvas(asset) {
  activeCanvasPreview.value = {
    title: asset.asset_name,
    url: asset.file,
    isVideo: asset.media_type === "Video" || isVideoUrl(asset.file),
    duration: null,
  };
}

function previewOutputOnCanvas(output) {
  activeCanvasPreview.value = {
    title: output.asset_name,
    url: output.file,
    isVideo: output.media_type === "Video" || isVideoUrl(output.file),
    duration: null,
  };
}

function estimateShotDuration(shot) {
  const rev = getShotReview(shot);
  if (rev?.duration_seconds) return rev.duration_seconds;
  const count = allShotsList.value.length || 1;
  const total = Number(settingsForm.duration) || 15;
  return (total / count).toFixed(1);
}

function quickTrimShot(shot, delta) {
  const currentTotal = Number(settingsForm.duration) || 15;
  const newTotal = Math.max(3, Math.min(60, Math.round(currentTotal + delta)));
  settingsForm.duration = newTotal;
  saveSettings();
  toast({ title: "Trim updated", text: `Total video duration trimmed to ${newTotal}s.`, type: "success" });
}

function quickSelectAspect(aspect) {
  settingsForm.format = aspect;
  saveSettings();
}

function quickSelectDuration(dur) {
  settingsForm.duration = dur;
  saveSettings();
}

function toggleContinuityMode() {
  settingsForm.continuity_mode = currentContinuityMode.value === "Continuous" ? "Multi-shot" : "Continuous";
  saveSettings();
}

// Review helpers
const pendingReviewsCount = computed(() => reviews.value.filter((r) => r.status === "Pending").length);
const canRetryProduction = computed(() => (
  production.value &&
  production.value.failed_jobs > 0 &&
  ["Failed", "Partially Completed"].includes(production.value.status) &&
  !workflowSetupInvalid.value
));
const workflowSetupInvalid = computed(() => production.value?.error_summary?.startsWith("Invalid Workflow Binding"));

const currentContinuityMode = computed(() => {
  return settingsForm.continuity_mode || settings.value?.continuity_mode || "Multi-shot";
});

// Watch settings updates
watch(settings, (value) => {
  if (!value) return;
  settingsForm.duration = value.duration;
  settingsForm.format = value.delivery_preset;
  settingsForm.video_style = value.video_style || settingsForm.video_style;
  settingsForm.continuity_mode = value.continuity_mode || "Multi-shot";
}, { immediate: true });

// Production Polling Logic
const ACTIVE_PRODUCTION_STATUSES = new Set(["Queued", "Running", "Awaiting Review", "Finalizing", "Ready for Composition"]);
let pollTimer = null;
let reviewPollTimer = null;
let clockTimer = null;
const nowTick = ref(Date.now());
const isProductionActive = computed(() => ACTIVE_PRODUCTION_STATUSES.has(production.value?.status));
const productionElapsedSeconds = computed(() => {
  if (!production.value) return 0;
  const startedAt = production.value.started_at || production.value.queued_at;
  if (!startedAt) return 0;
  const start = parseServerDate(startedAt);
  const end = production.value.completed_at && !isProductionActive.value
    ? parseServerDate(production.value.completed_at)
    : nowTick.value;
  return Math.max(0, Math.floor((end - start) / 1000));
});

const estimatedFinishLabel = computed(() => {
  const completed = Number(production.value?.completed_jobs || 0);
  const total = Number(production.value?.total_jobs || 0);
  const remaining = total - completed;
  if (!remaining) return "complete";
  if (!completed || !productionElapsedSeconds.value) return "estimating";
  return `~${formatElapsed(Math.ceil((productionElapsedSeconds.value / completed) * remaining))}`;
});

watch(() => production.value?.status, (status) => {
  if (pollTimer) clearInterval(pollTimer);
  if (reviewPollTimer) clearInterval(reviewPollTimer);
  if (clockTimer) clearInterval(clockTimer);
  pollTimer = null;
  reviewPollTimer = null;
  clockTimer = null;
  if (ACTIVE_PRODUCTION_STATUSES.has(status)) {
    pollTimer = setInterval(() => productionResource.reload(), 4000);
    reviewPollTimer = setInterval(() => reviewResource.reload(), 4000);
    clockTimer = setInterval(() => { nowTick.value = Date.now(); }, 1000);
  }
}, { immediate: true });

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer);
  if (reviewPollTimer) clearInterval(reviewPollTimer);
  if (clockTimer) clearInterval(clockTimer);
});

async function refresh() {
  plan.value = null;
  activeCanvasPreview.value = null;
  await campaign.reload();
  await productionResource.reload();
  await reviewResource.reload();
}

function parseServerDate(value) {
  const text = String(value || "").replace(" ", "T");
  const date = new Date(text.endsWith("Z") ? text : `${text}Z`);
  return Number.isNaN(date.getTime()) ? nowTick.value : date.getTime();
}

function formatElapsed(seconds) {
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  return minutes ? `${minutes}m ${remainder}s` : `${remainder}s`;
}

function assetNameFromFile(fileName) {
  return fileName.replace(/\.[^/.]+$/, "");
}

async function uploadSelectedImages(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (!files.length) return;

  uploadingImages.value = true;
  uploadError.value = "";
  uploadProgress.value = 0;
  uploadTotal.value = files.length;
  try {
    for (const file of files) {
      const uploadedFile = await uploadFile(file, { private: true });
      if (!uploadedFile?.file_url) throw new Error(`Upload did not return a file URL for ${file.name}.`);
      await call("joymedia.joymedia.doctype.media_project.media_project.create_campaign_asset", {
        media_project: projectName.value,
        asset_name: assetNameFromFile(file.name),
        asset_category: selectedUploadCategory.value || "Product",
        file_url: uploadedFile.file_url,
      });
      uploadProgress.value += 1;
    }
    await refresh();
    toast({ title: "Media uploaded", text: `${files.length} image(s) attached to project references.`, type: "success" });
  } catch (error) {
    uploadError.value = error?.messages?.join(" ") || error?.message || "The reference could not be uploaded.";
    toast({ title: "Upload failed", text: uploadError.value, type: "error" });
  } finally {
    uploadingImages.value = false;
  }
}

async function openReferencePicker() {
  try {
    referenceCandidates.value = await call("joymedia.joymedia.doctype.media_project.media_project.get_project_reference_candidates", {
      media_project: projectName.value,
    });
    showReferencePicker.value = true;
  } catch (error) {
    toast({ title: "Unable to load campaign assets", text: error.message || "Please try again.", type: "error" });
  }
}

async function selectReference(asset) {
  selectingReference.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.select_project_reference", {
      media_project: projectName.value,
      asset_name: asset.name,
    });
    asset.selected = true;
    await refresh();
    toast({ title: "Reference selected", text: `${asset.asset_name} is now available in this video project.`, type: "success" });
  } catch (error) {
    toast({ title: "Unable to select reference", text: error.message || "Please try again.", type: "error" });
  } finally {
    selectingReference.value = false;
  }
}

async function saveSettings() {
  savingSettings.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.save_campaign_video_settings", {
      campaign_name: projectName.value,
      total_duration_seconds: settingsForm.duration,
      delivery_preset: settingsForm.format,
      video_style: settingsForm.video_style,
      continuity_mode: settingsForm.continuity_mode,
    });
    showSettings.value = false;
    await refresh();
  } catch (error) {
    toast({ title: "Unable to save settings", text: error.message || "Please try again.", type: "error" });
  } finally {
    savingSettings.value = false;
  }
}

// ============================================================================
// ONE-CLICK MAGIC GENERATE FLOW (SIMPLIFIED FOR MARKET SELLERS & BEGINNERS)
// ============================================================================
async function handleMagicGenerateClick() {
  if (canRetryProduction.value) {
    await retryFailedScenes();
    return;
  }
  // Run the unified 1-click generation pipeline!
  await oneClickGenerateVideo();
}

async function oneClickGenerateVideo() {
  isAutoGenerating.value = true;
  autoGenerateStep.value = "Saving studio settings...";
  try {
    // 1. Ensure settings exist & are saved
    if (!settings.value) {
      await call("joymedia.joymedia.doctype.media_project.media_project.save_campaign_video_settings", {
        campaign_name: projectName.value,
        total_duration_seconds: settingsForm.duration,
        delivery_preset: settingsForm.format,
        video_style: settingsForm.video_style || (videoStyles.data?.[0]?.workflow_key || ""),
        continuity_mode: settingsForm.continuity_mode,
      });
      await refresh();
    }

    // 2. If storyboard does NOT exist yet, auto-plan and apply it!
    const storyboardAlreadyExists = Boolean(workspace.value?.storyboard?.length);
    if (!storyboardAlreadyExists) {
      autoGenerateStep.value = "AI is drafting storyboard shots...";
      const generatedPlan = await call("joymedia.joymedia.doctype.media_project.media_project.generate_campaign_video_plan", {
        campaign_name: projectName.value,
      });
      const normalized = normalizePlanForEditor(generatedPlan);

      autoGenerateStep.value = "Applying scenes to timeline...";
      const payload = {
        ...normalized,
        shots: normalized.shots.map((shot) => ({
          ...shot,
          ...(shot.reference_image_index != null ? { reference_image_index: Number(shot.reference_image_index) } : {}),
          ...(shot.first_frame_reference_image_index != null ? { first_frame_reference_image_index: Number(shot.first_frame_reference_image_index) } : {}),
          ...(shot.last_frame_reference_image_index != null ? { last_frame_reference_image_index: Number(shot.last_frame_reference_image_index) } : {}),
        })),
      };
      await call("joymedia.joymedia.doctype.media_project.media_project.apply_campaign_video_plan", {
        campaign_name: projectName.value,
        plan_json: JSON.stringify(payload),
      });
      await refresh();
    }

    // 3. Initiate Video Generation!
    autoGenerateStep.value = "Starting AI Video Engine...";
    await call("joymedia.joymedia.doctype.media_project.media_project.generate_campaign_video", {
      campaign_name: projectName.value,
    });
    await refresh();
    toast({ title: "Video generation started!", text: "Your video is now being created. Track live progress here.", type: "success" });
  } catch (error) {
    toast({ title: "Generation failed", text: error.message || "Please check inputs and try again.", type: "error" });
  } finally {
    isAutoGenerating.value = false;
    autoGenerateStep.value = "";
  }
}

// Standard Storyboard Flow
async function generatePlan() {
  generatingPlan.value = true;
  plan.value = null;
  try {
    const generatedPlan = await call("joymedia.joymedia.doctype.media_project.media_project.generate_campaign_video_plan", {
      campaign_name: projectName.value,
    });
    plan.value = normalizePlanForEditor(generatedPlan);
    toast({ title: "Storyboard drafted", text: `${plan.value.shots.length} shots planned. Review and click Apply Storyboard.`, type: "success" });
  } catch (error) {
    toast({ title: "Unable to generate storyboard", text: error.message || "Please try again.", type: "error" });
  } finally {
    generatingPlan.value = false;
  }
}

async function applyPlan() {
  if (!plan.value?.shots?.length) return;
  applyingPlan.value = true;
  applyError.value = "";
  applySuccess.value = false;
  try {
    const payload = {
      ...plan.value,
      shots: plan.value.shots.map((shot) => ({
        ...shot,
        ...(shot.reference_image_index != null ? { reference_image_index: Number(shot.reference_image_index) } : {}),
        ...(shot.first_frame_reference_image_index != null ? { first_frame_reference_image_index: Number(shot.first_frame_reference_image_index) } : {}),
        ...(shot.last_frame_reference_image_index != null ? { last_frame_reference_image_index: Number(shot.last_frame_reference_image_index) } : {}),
      })),
    };
    const result = await call("joymedia.joymedia.doctype.media_project.media_project.apply_campaign_video_plan", {
      campaign_name: projectName.value,
      plan_json: JSON.stringify(payload),
    });
    if (!result?.shots?.length) throw new Error("No shots were created.");
    applySuccess.value = true;
    await refresh();
    plan.value = null;
    toast({ title: "Storyboard applied", text: `${result.shots.length} shots ready for video generation.`, type: "success" });
  } catch (error) {
    applyError.value = error.message || "The storyboard could not be applied.";
    toast({ title: "Unable to apply storyboard", text: applyError.value, type: "error" });
  } finally {
    applyingPlan.value = false;
  }
}

async function retryFailedScenes() {
  retryingFailedScenes.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.retry_campaign_failed_jobs", {
      campaign_name: projectName.value,
    });
    await refresh();
    toast({ title: "Retrying failed shots", text: "Production jobs queued.", type: "success" });
  } catch (error) {
    toast({ title: "Unable to retry video", text: error.message || "Please try again.", type: "error" });
  } finally {
    retryingFailedScenes.value = false;
  }
}

async function createAnotherVersion() {
  revisingStoryboard.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.revise_campaign_storyboard", {
      campaign_name: projectName.value,
    });
    await refresh();
    toast({ title: "New version ready", text: "You can now edit shots and generate another version.", type: "success" });
  } catch (error) {
    toast({ title: "Unable to create version", text: error.message || "Please try again.", type: "error" });
  } finally {
    revisingStoryboard.value = false;
  }
}

async function saveShot(shot) {
  savingShotMap[shot.name] = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.update_campaign_shot", {
      campaign_name: projectName.value,
      shot_name: shot.name,
      values: {
        subject_identity: shot.subject_identity,
        action_plot: shot.action_plot,
        camera_direction: shot.camera_direction,
        environment: shot.environment,
        audio_direction: shot.audio_direction,
      },
    });
    toast({ title: "Shot saved", text: `Shot ${shot.shot_number} updated.`, type: "success" });
    await refresh();
  } catch (error) {
    toast({ title: "Unable to save shot", text: error.message || "Please try again.", type: "error" });
  } finally {
    savingShotMap[shot.name] = false;
  }
}

async function regenerateSingleShot(shot) {
  regeneratingShotMap[shot.name] = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.regenerate_campaign_shot", {
      campaign_name: projectName.value,
      shot_name: shot.name,
    });
    toast({ title: "Regenerating shot", text: `Shot ${shot.shot_number} queued.`, type: "success" });
    await refresh();
  } catch (error) {
    toast({ title: "Unable to regenerate shot", text: error.message || "Please try again.", type: "error" });
  } finally {
    regeneratingShotMap[shot.name] = false;
  }
}

async function reviewAction(action, review) {
  const method = action === "approve" ? "approve_campaign_review" : action === "regenerate" ? "regenerate_campaign_review" : "reject_campaign_review";
  reviewingMap[review.name] = action;
  try {
    await call(`joymedia.joymedia.doctype.media_project.media_project.${method}`, {
      campaign_name: projectName.value,
      review_name: review.name,
    });
    await refresh();
    toast({ title: "Review updated", text: `Shot marked as ${action}d.`, type: "success" });
  } catch (error) {
    toast({ title: "Unable to update review", text: error.message || "Please try again.", type: "error" });
  } finally {
    delete reviewingMap[review.name];
  }
}

// Helpers for Shot Frames
function firstFrameAssetForShot(shot) {
  const index = Number(shot.first_frame_reference_image_index ?? shot.reference_image_index);
  return index > 0 ? workspace.value?.assets?.[index - 1] : null;
}

function getShotFirstFrame(shot, isPlan = false) {
  if (isPlan) {
    const asset = firstFrameAssetForShot(shot);
    return {
      file: asset?.file || null,
      name: asset?.asset_name || (shot.first_frame_reference_image_index ? `Reference #${shot.first_frame_reference_image_index}` : null),
    };
  }
  return {
    file: shot.reference_image || null,
    name: shot.reference_asset_name || (shot.reference_image ? `Scene ${shot.shot_number}` : null),
  };
}

function readablePlanValue(value) {
  if (value == null) return "";
  if (typeof value !== "string") {
    return Object.entries(value).map(([key, item]) => `${humanizeKey(key)}: ${item}`).join(". ");
  }
  const text = value.trim();
  if (!text.startsWith("{") || !text.endsWith("}")) return value;
  try {
    return readablePlanValue(JSON.parse(text));
  } catch {
    return text.slice(1, -1).replace(/[\'"]([^\'"]+)[\'"]\s*:\s*[\'"]([^\'"]*)[\'"]/g, (_, key, item) => `${humanizeKey(key)}: ${item}`).replace(/,\s*/g, ". ");
  }
}

function humanizeKey(key) {
  return key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function normalizePlanForEditor(value) {
  return {
    ...value,
    shots: (value?.shots || []).map((shot) => ({
      ...shot,
      camera: readablePlanValue(shot.camera),
      subject: readablePlanValue(shot.subject),
      motion: readablePlanValue(shot.motion),
      lighting: readablePlanValue(shot.lighting),
      audio: readablePlanValue(shot.audio),
    })),
  };
}

function goBack() {
  const campaignName = workspace.value?.campaign_parent?.name || workspace.value?.campaign?.campaign;
  if (campaignName) {
    window.location.href = `/joymedia/campaigns/${encodeURIComponent(campaignName)}`;
  } else {
    window.location.href = "/joymedia/campaigns";
  }
}
</script>
