<template>
  <section class="page-section narrow-page">
    <div class="form-card onboarding-card">
      <div class="brand-mark mb-4">J</div>
      <p class="eyebrow">Welcome to JoyMedia</p>
      <h1>Create your workspace</h1>
      <p class="subtitle">Set up your brand and business organization profile before creating your first AI video campaign.</p>

      <div class="form-stack">
        <FormControl
          v-model="name"
          label="Business / Brand Name"
          required
          placeholder="e.g. Acme Studio, Urban Cafe"
        />
        <FormControl
          v-model="industry"
          label="Industry Sector"
          placeholder="e.g. E-Commerce, Food & Beverage, Fashion, Tech"
        />
      </div>

      <div class="form-actions flex justify-end">
        <Button variant="solid" :loading="saving" @click="save">
          <span>Get Started</span>
          <template #suffix>
            <span class="lucide-arrow-right size-4" />
          </template>
        </Button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref } from "vue";
import { Button, FormControl, call, toast } from "frappe-ui";

const name = ref("");
const industry = ref("");
const saving = ref(false);

async function save() {
  if (!name.value.trim()) {
    toast({ title: "Business name is required", type: "error" });
    return;
  }
  saving.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.create_business", { organization_name: name.value, industry: industry.value });
    window.location.href = "/joymedia/campaigns";
  } catch (error) {
    toast({ title: "Unable to create workspace", text: error.message || "Please try again.", type: "error" });
  } finally { saving.value = false; }
}
</script>
