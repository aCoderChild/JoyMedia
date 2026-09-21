<template>
  <section class="page-section narrow-page">
    <div class="form-card onboarding-card">
      <p class="eyebrow">Welcome to JoyMedia</p>
      <h1>Create your workspace</h1>
      <p class="subtitle">Tell us about your business before creating a campaign.</p>
      <div class="form-stack">
        <FormControl v-model="name" label="Business name" required />
        <FormControl v-model="industry" label="Industry" placeholder="Real estate, food, retail..." />
      </div>
      <Button label="Create workspace" :loading="saving" @click="save" />
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
  saving.value = true;
  try {
    await call("joymedia.joymedia.doctype.media_project.media_project.create_business", { organization_name: name.value, industry: industry.value });
    window.location.href = "/joymedia/campaigns";
  } catch (error) {
    toast({ title: "Unable to create workspace", text: error.message || "Please try again.", type: "error" });
  } finally { saving.value = false; }
}
</script>
