<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import OfferPicker from './OfferPicker.vue'

const props = defineProps({ initialId: { type: Number, default: null } })

const campaigns = ref([])
const selectedId = ref(props.initialId)
const campaign = ref(null)
const shares = ref({}) // offer_id -> number
const loading = ref(false)
const error = ref('')

const offersStream = computed(
  () => campaign.value?.streams.find((s) => s.id === campaign.value.offers_stream_id) || null,
)
const offers = computed(() => offersStream.value?.offers || [])
const total = computed(() => offers.value.reduce((s, o) => s + (Number(shares.value[o.offer_id]) || 0), 0))
const dirty = computed(() => offers.value.some((o) => Number(shares.value[o.offer_id]) !== o.share))

async function loadList() {
  try {
    campaigns.value = await api.listCampaigns()
  } catch (e) {
    error.value = e.message
  }
}

function apply(data) {
  campaign.value = data
  const s = {}
  const st = data.streams.find((x) => x.id === data.offers_stream_id)
  for (const o of st?.offers || []) s[o.offer_id] = o.share
  shares.value = s
}

async function load() {
  if (!selectedId.value) {
    campaign.value = null
    return
  }
  await run(async () => apply(await api.getCampaign(selectedId.value)))
}

async function run(fn) {
  error.value = ''
  loading.value = true
  try {
    await fn()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

const addOffer = (o) => run(async () => apply(await api.addOffer(campaign.value.id, o.id)))
const removeOffer = (o) => run(async () => apply(await api.removeOffer(campaign.value.id, o.offer_id)))
const equalize = () => run(async () => apply(await api.equalize(campaign.value.id)))
const saveShares = () =>
  run(async () =>
    apply(
      await api.setShares(
        campaign.value.id,
        offers.value.map((o) => ({ offer_id: o.offer_id, share: Number(shares.value[o.offer_id]) || 0 })),
      ),
    ),
  )

function filterText(f) {
  const mode = f.mode === 'reject' ? 'отклонять' : 'принимать'
  return `${f.name}: ${mode} ${(f.payload || []).join(', ')}`
}

onMounted(loadList)
watch(selectedId, load, { immediate: true })
watch(() => props.initialId, (v) => v && (selectedId.value = v))
defineExpose({ loadList })
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
      <button class="secondary" @click="loadList">Обновить</button>
    </div>
  </div>

  <div v-if="campaign" class="card">
    <div style="display: flex; justify-content: space-between">
      <h1 style="margin: 0">{{ campaign.name }}</h1>
      <a :href="campaign.admin_url" target="_blank">Открыть в Keitaro</a>
    </div>

    <div v-for="s in campaign.streams" :key="s.id" class="stream">
      <h3>{{ s.name }} <span class="muted">({{ s.type }})</span></h3>

      <template v-if="s.id !== campaign.offers_stream_id">
        <div v-if="s.action_payload">{{ s.action_payload }}</div>
        <div v-for="(f, i) in s.filters" :key="i" class="muted">{{ filterText(f) }}</div>
      </template>

      <template v-else>
        <div v-if="!offers.length" class="muted">В потоке нет офферов</div>
        <table v-else>
          <tbody>
            <tr v-for="o in offers" :key="o.offer_id">
              <td>[{{ o.offer_id }}] {{ o.name }}</td>
              <td class="share">
                <input type="number" min="0" max="100" v-model.number="shares[o.offer_id]" /> %
              </td>
              <td style="width: 30px">
                <button class="danger" title="Удалить" :disabled="loading" @click="removeOffer(o)">×</button>
              </td>
            </tr>
          </tbody>
        </table>

        <div v-if="offers.length" class="toolbar">
          <span :class="['total', total === 100 ? 'ok' : 'bad']">Сумма: {{ total }}%</span>
          <button class="secondary" :disabled="loading" @click="equalize">Распределить поровну</button>
          <button class="primary" :disabled="loading || !dirty || total !== 100" @click="saveShares">
            Сохранить доли
          </button>
        </div>

        <div style="margin-top: 14px">
          <div class="muted" style="margin-bottom: 4px">Добавить оффер</div>
          <OfferPicker :exclude="offers.map((o) => o.offer_id)" @select="addOffer" />
        </div>
      </template>
    </div>

    <div v-if="!campaign.offers_stream_id" class="stream">
      <div class="muted">В кампании нет потока с офферами — он будет создан при добавлении оффера.</div>
      <OfferPicker @select="addOffer" />
    </div>
  </div>
</template>
