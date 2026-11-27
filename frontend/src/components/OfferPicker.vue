<script setup>
import { ref, watch } from 'vue'
import { api } from '../api'

const props = defineProps({ exclude: { type: Array, default: () => [] }, placeholder: String })
const emit = defineEmits(['select'])

const query = ref('')
const items = ref([])
const open = ref(false)
let timer = null
let seq = 0

async function search() {
  const my = ++seq
  try {
    const res = await api.searchOffers(query.value)
    if (my === seq) items.value = res.filter((o) => !props.exclude.includes(o.id))
  } catch {
    if (my === seq) items.value = []
  }
}

watch(query, () => {
  clearTimeout(timer)
  timer = setTimeout(search, 250)
})

function onFocus() {
  open.value = true
  search()
}

function pick(o) {
  emit('select', o)
  query.value = ''
  open.value = false
}

function onBlur() {
  setTimeout(() => (open.value = false), 150)
}
</script>

<template>
  <div class="offer-picker">
    <input
      type="text"
      v-model="query"
      :placeholder="placeholder || 'Поиск по названию или ID оффера'"
      @focus="onFocus"
      @blur="onBlur"
    />
    <div v-if="open && items.length" class="dropdown">
      <div v-for="o in items" :key="o.id" @mousedown.prevent="pick(o)">[{{ o.id }}] {{ o.name }}</div>
    </div>
  </div>
</template>
