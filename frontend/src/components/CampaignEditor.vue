<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import StreamBlock from './StreamBlock.vue'

const props = defineProps({ initialId: { type: Number, default: null } })

const campaigns = ref([])
const selectedId = ref(props.initialId)
const campaign = ref(null)
const loading = ref(false)
const error = ref('')
const dirtyMap = ref({})

const changedCount = computed(() => campaign.value?.streams.filter((s) => s.has_changes).length ?? 0)
const anyDirty = computed(() => Object.values(dirtyMap.value).some(Boolean))
const syncedText = computed(() => {
  const value = campaign.value?.synced_at
  if (!value) return 'Потоки ещё не стягивались с Keitaro'
  return `Стянуто с Keitaro: ${new Date(value).toLocaleString('ru-RU')}`
})

async function loadList() {
  try {
    campaigns.value = await api.listCampaigns()
  } catch (e) {
    error.value = e.message
  }
}

async function run(action, { reloadOnError = false } = {}) {
  error.value = ''
  loading.value = true
  try {
    campaign.value = await action()
  } catch (e) {
    error.value = e.message
    if (reloadOnError && selectedId.value) {
      try {
        campaign.value = await api.getCampaign(selectedId.value)
      } catch {}
    }
  } finally {
    loading.value = false
  }
}

async function syncList() {
  error.value = ''
  loading.value = true
  try {
    campaigns.value = await api.syncCampaigns()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function load() {
  dirtyMap.value = {}
  if (!selectedId.value) {
    campaign.value = null
    return
  }
  return run(() => api.getCampaign(selectedId.value))
}

function pull() {
  if (
    changedCount.value &&
    !confirm('В кампании есть незафиксированные изменения. При стягивании с Keitaro они будут потеряны. Продолжить?')
  ) {
    return
  }
  run(() => api.pullCampaign(campaign.value.id))
}

const pushAll = () => run(() => api.pushCampaign(campaign.value.id), { reloadOnError: true })
const pushStream = (stream) => run(() => api.pushStream(stream.id), { reloadOnError: true })
const cancelStream = (stream) => run(() => api.cancelStream(stream.id))
const addOffer = (stream, offer) => run(() => api.addOffer(stream.id, offer.id))
const removeOffer = (stream, offerId) => run(() => api.removeOffer(stream.id, offerId))
const restoreOffer = (stream, offerId) => run(() => api.restoreOffer(stream.id, offerId))
const pinOffer = (stream, offerId, pinned) => run(() => api.pinOffer(stream.id, offerId, pinned))
const equalize = (stream) => run(() => api.equalize(stream.id))
const saveShares = (stream, shares) => run(() => api.setShares(stream.id, shares))

function purgeOffer(stream, offerId) {
  if (!confirm('Удалить оффер из БД полностью? Восстановить его потом будет нельзя.')) return
  run(() => api.purgeOffer(stream.id, offerId))
}

function setDirty(streamId, value) {
  dirtyMap.value = { ...dirtyMap.value, [streamId]: value }
}

onMounted(loadList)
watch(selectedId, load, { immediate: true })
watch(
  () => props.initialId,
  async (value) => {
    if (!value) return
    await loadList()
    selectedId.value = value
  },
)
</script>

<template>
  <div class="card">
    <h1>Редактор кампании</h1>
    <div v-if="error" class="error">{{ error }}</div>

    <div class="row">
      <label>Кампания</label>
      <div class="field">
        <select v-model.number="selectedId">
          <option :value="null" disabled>Выберите кампанию</option>
          <option v-for="c in campaigns" :key="c.id" :value="c.id">[{{ c.id }}] {{ c.name }}</option>
        </select>
      </div>
      <button
        class="secondary"
        :disabled="loading"
        title="Загрузить список кампаний из Keitaro в БД"
        @click="syncList"
      >
        Обновить список
      </button>
    </div>
    <div v-if="!campaigns.length" class="muted">
      В БД пока нет кампаний. Нажмите «Обновить список», чтобы загрузить их из Keitaro.
    </div>
  </div>

  <div v-if="campaign" class="card">
    <div class="editor-head">
      <h1>{{ campaign.name }}</h1>
      <a :href="campaign.admin_url" target="_blank">Открыть в Keitaro</a>
    </div>

    <div class="editor-toolbar">
      <button class="secondary" :disabled="loading" @click="pull">Стянуть потоки (streams) с Keitaro</button>
      <button
        class="primary"
        :disabled="loading || !changedCount || anyDirty"
        :title="anyDirty ? 'Сначала сохраните доли во всех потоках' : ''"
        @click="pushAll"
      >
        Отправить изменения со всех потоков<span v-if="changedCount"> ({{ changedCount }})</span>
      </button>
      <span class="muted">{{ syncedText }}</span>
    </div>

    <div v-if="!campaign.streams.length" class="muted" style="margin-top: 12px">
      В БД нет потоков этой кампании. Нажмите «Стянуть потоки (streams) с Keitaro».
    </div>

    <StreamBlock
      v-for="stream in campaign.streams"
      :key="stream.id"
      :stream="stream"
      :loading="loading"
      @add="(offer) => addOffer(stream, offer)"
      @remove="(offerId) => removeOffer(stream, offerId)"
      @restore="(offerId) => restoreOffer(stream, offerId)"
      @purge="(offerId) => purgeOffer(stream, offerId)"
      @pin="(offerId, pinned) => pinOffer(stream, offerId, pinned)"
      @equalize="equalize(stream)"
      @save-shares="(shares) => saveShares(stream, shares)"
      @push="pushStream(stream)"
      @cancel="cancelStream(stream)"
      @dirty="(value) => setDirty(stream.id, value)"
    />
  </div>
</template>
