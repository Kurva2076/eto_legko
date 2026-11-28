<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import Icon from './Icon.vue'
import OfferPicker from './OfferPicker.vue'

const props = defineProps({
  stream: { type: Object, required: true },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits([
  'add',
  'remove',
  'restore',
  'purge',
  'pin',
  'equalize',
  'save-shares',
  'push',
  'cancel',
  'dirty',
])

const drafts = ref({})
const serverShares = {}

watch(
  () => props.stream,
  (stream) => {
    const next = {}
    for (const offer of stream.offers) {
      const keepDraft = serverShares[offer.offer_id] === offer.share && offer.offer_id in drafts.value
      next[offer.offer_id] = keepDraft ? drafts.value[offer.offer_id] : offer.share
      serverShares[offer.offer_id] = offer.share
    }
    drafts.value = next
  },
  { immediate: true },
)

const activeOffers = computed(() => props.stream.offers.filter((offer) => offer.status === 'active'))
const activeIds = computed(() => activeOffers.value.map((offer) => offer.offer_id))

function draftOf(offer) {
  return Number(drafts.value[offer.offer_id]) || 0
}

const total = computed(() => activeOffers.value.reduce((sum, offer) => sum + draftOf(offer), 0))
const dirty = computed(() => activeOffers.value.some((offer) => draftOf(offer) !== offer.share))

watch(dirty, (value) => emit('dirty', value), { immediate: true })
onBeforeUnmount(() => emit('dirty', false))

function saveShares() {
  emit(
    'save-shares',
    activeOffers.value.map((offer) => ({ offer_id: offer.offer_id, share: draftOf(offer) })),
  )
}

function filterText(filter) {
  const mode = filter.mode === 'reject' ? 'отклонять' : 'принимать'
  return `${filter.name}: ${mode} ${(filter.payload || []).join(', ')}`
}

const filtersText = computed(() => {
  const filters = props.stream.filters || []
  return filters.length ? filters.map(filterText).join('; ') : 'None'
})

function rowClass(offer) {
  return {
    removed: offer.status === 'removed',
    changed: offer.status === 'active' && offer.change !== null,
    'pending-removal': offer.status === 'removed' && offer.change === 'removed',
  }
}
</script>

<template>
  <div :class="['stream', { unsynced: stream.has_changes }]">
    <div class="stream-head">
      <div class="stream-title">
        <h3>
          Stream: {{ stream.name }}
          <span class="muted">(#{{ stream.position }})</span>
        </h3>
        <div class="muted">
          filter by {{ filtersText }}, stream_id {{ stream.id }}, {{ stream.type }}/{{ stream.schema }}
        </div>
        <div v-if="!stream.has_offers && stream.action_payload" class="stream-target">
          {{ stream.action_payload }}
        </div>
      </div>

      <div v-if="stream.has_changes" class="stream-actions">
        <span class="badge badge-warn">не отправлено в Keitaro</span>
        <button
          class="primary small"
          :disabled="loading || dirty"
          :title="dirty ? 'Сначала сохраните доли' : ''"
          @click="emit('push')"
        >
          Отправить изменения в Keitaro
        </button>
        <button class="secondary small" :disabled="loading" @click="emit('cancel')">
          Отменить изменения
        </button>
      </div>
    </div>

    <template v-if="stream.has_offers">
      <div class="muted offers-label">Офферы</div>
      <table class="offers">
        <tbody>
          <tr v-for="offer in stream.offers" :key="offer.offer_id" :class="rowClass(offer)">
            <td class="offer-name">
              [{{ offer.offer_id }}] {{ offer.name }}
              <span v-if="offer.status === 'removed'" class="badge badge-removed">REMOVED</span>
              <span v-else-if="offer.change === 'added'" class="badge badge-added">новый</span>
              <span v-else-if="offer.change === 'share'" class="badge badge-share">доля изменена</span>
              <div v-if="offer.status === 'removed' && offer.change === 'removed'" class="muted">
                Удаление ещё не отправлено в Keitaro
              </div>
            </td>

            <template v-if="offer.status === 'active'">
              <td class="share">
                <div class="share-content">
                  <input type="number" min="0" max="100" v-model.number="drafts[offer.offer_id]" /> %
                  <button
                    :class="['pin-btn', { active: offer.pinned }]"
                    :title="offer.pinned ? 'Открепить долю' : 'Закрепить долю'"
                    :disabled="loading"
                    @click="emit('pin', offer.offer_id, !offer.pinned)"
                  >
                    <Icon name="pin" :filled="offer.pinned" />
                  </button>
                </div>
              </td>
              <td class="actions">
                <button
                  class="danger"
                  title="Удалить"
                  :disabled="loading"
                  @click="emit('remove', offer.offer_id)"
                >
                  <Icon name="close" :size="16" color="black" />
                </button>
              </td>
            </template>

            <template v-else>
              <td class="share muted">—</td>
              <td class="actions">
                <button
                  class="icon-btn"
                  title="Восстановить"
                  :disabled="loading"
                  @click="emit('restore', offer.offer_id)"
                >
                  <Icon name="restore" :size="16" color="#54dd4b" />
                </button>
                <button
                  class="icon-btn danger-btn"
                  title="Удалить полностью"
                  :disabled="loading"
                  @click="emit('purge', offer.offer_id)"
                >
                  <Icon name="trash" :size="16" color="red" />
                </button>
              </td>
            </template>
          </tr>
        </tbody>
      </table>

      <div v-if="activeOffers.length" class="toolbar">
        <span :class="['total', total === 100 ? 'ok' : 'bad']">Сумма: {{ total }}%</span>
        <button class="secondary" :disabled="loading" @click="emit('equalize')">Распределить поровну</button>
        <button class="primary" :disabled="loading || !dirty || total !== 100" @click="saveShares">
          Сохранить доли
        </button>
      </div>
    </template>

    <div class="add-offer">
      <div class="muted" style="margin-bottom: 4px">Добавить оффер</div>
      <OfferPicker :exclude="activeIds" @select="(offer) => emit('add', offer)" />
    </div>
  </div>
</template>
