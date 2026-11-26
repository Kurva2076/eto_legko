<script setup>
import { onMounted, ref, computed } from 'vue'
import { api } from '../api'
import OfferPicker from './OfferPicker.vue'

const emit = defineEmits(['created'])

const name = ref('')
const geo = ref('')
const offer = ref(null)
const meta = ref(null)
const loading = ref(false)
const error = ref('')
const created = ref(null)

const canSubmit = computed(() => name.value.trim() && geo.value.trim() && offer.value && !loading.value)

onMounted(async () => {
  try {
    meta.value = await api.meta()
  } catch (e) {
    error.value = e.message
  }
})

async function submit() {
  error.value = ''
  created.value = null
  loading.value = true
  try {
    created.value = await api.createCampaign({
      name: name.value,
      geo: geo.value,
      offer_id: offer.value.id,
    })
    name.value = ''
    geo.value = ''
    offer.value = null
    emit('created', created.value)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="card">
    <h1>Новая кампания</h1>
    <div v-if="error" class="error">{{ error }}</div>
    <div v-if="created" class="success">
      Кампания «{{ created.name }}» создана (ID {{ created.id }}).
      <a :href="created.admin_url" target="_blank">Открыть в Keitaro</a>
    </div>

    <div class="row">
      <label>Name</label>
      <div class="field"><input type="text" v-model="name" placeholder="имя кампании" /></div>
    </div>
    <div class="row">
      <label>Geo</label>
      <div class="field">
        <input type="text" v-model="geo" placeholder="MX,AU,RO,..." />
        <div class="hint">Коды стран ISO-2, через запятую</div>
      </div>
    </div>
    <div class="row">
      <label>Offer</label>
      <div class="field">
        <OfferPicker @select="(o) => (offer = o)" />
        <div v-if="offer" class="chosen">Выбран: [{{ offer.id }}] {{ offer.name }}</div>
      </div>
    </div>

    <div v-if="meta" class="muted" style="margin-bottom: 12px">
      Домен: {{ meta.domain.name }} · Группа: {{ meta.group.name }} · Источник: {{ meta.source.name }}
    </div>

    <button class="primary" :disabled="!canSubmit" @click="submit">
      {{ loading ? 'Создаю…' : 'Create' }}
    </button>
  </div>
</template>
