<script setup>
import pin from '../images/pin.svg'
import restore from '../images/restore.svg'
import trash from '../images/trashcan.svg'
import close from '../images/close.svg'

defineProps({
  name: { type: String, required: true },
  size: { type: Number, default: 16 },
  filled: { type: Boolean, default: false },
  color: { type: String, default: 'currentColor' },
})

const icons = {
  pin,
  restore,
  trash,
  close,
}
</script>

<template>
  <component
    :is="icons[name]"
    :width="size"
    :height="size"
    :fill="filled ? color : 'none'"
    :stroke="color"
    aria-hidden="true"
  />
</template>