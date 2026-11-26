<script setup>
import { ref } from 'vue'
import CreateCampaign from './components/CreateCampaign.vue'
import CampaignEditor from './components/CampaignEditor.vue'

const tab = ref('create')
const editId = ref(null)

function onCreated(c) {
  editId.value = c.id
}
</script>

<template>
  <div class="container">
    <div class="tabs">
      <button :class="{ active: tab === 'create' }" @click="tab = 'create'">Создать кампанию</button>
      <button :class="{ active: tab === 'edit' }" @click="tab = 'edit'">Редактор</button>
    </div>
    <CreateCampaign v-show="tab === 'create'" @created="onCreated" />
    <CampaignEditor v-if="tab === 'edit'" :initial-id="editId" />
  </div>
</template>
