<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

interface ColStat {
  column_key: string
  order_id: number | null
  total_fill: number
  need_fill_count: number
  full_count: number
  overbooked_count: number
  has_pending: boolean
}
interface Summary {
  run_id: number
  created_at: string
  total_fill: number
  need_fill_count: number
  full_count: number
  overbooked_count: number
  columns: ColStat[]
}

const s = ref<Summary | null>(null)
const runs = ref<{ id: number; created_at: string; total_fill: number }[]>([])

const sumOfBooklets = computed(() =>
  s.value ? s.value.columns.reduce((n, c) => n + c.total_fill, 0) : 0)
const reconciled = computed(() => s.value !== null && sumOfBooklets.value === s.value.total_fill)

async function loadRuns() {
  runs.value = await api('/refills/runs?location_id=1')
}
async function loadSummary(runId?: number) {
  const qs = new URLSearchParams({ location_id: '1' })
  if (runId) qs.set('run_id', String(runId))
  s.value = await api(`/refills/summary?${qs}`)
}
async function onPick(e: Event) {
  const id = Number((e.target as HTMLSelectElement).value)
  await loadSummary(id)
}

onMounted(async () => {
  await loadSummary()
  await loadRuns()
})
</script>
<template>
  <h1>汇总 · 分册对账</h1>
  <p class="sub">按点位展示整机与各立柱字母分册的总补件数 · 分册之和必须等于整机总量，无漏无重</p>

  <div class="card" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem">
    <div><div class="muted">建议补货总量</div><div class="stat">{{ s?.total_fill }}</div></div>
    <div><div class="muted">待补货道</div><div class="stat">{{ s?.need_fill_count }}</div></div>
    <div><div class="muted">满仓货道</div><div class="stat">{{ s?.full_count }}</div></div>
    <div><div class="muted">超占货道</div><div class="stat">{{ s?.overbooked_count }}</div></div>
  </div>

  <div class="card" style="margin-top:1rem" v-if="s">
    <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:.5rem;align-items:center">
      <div class="muted">点位 VM-01 · 批次 #{{ s.run_id }} · {{ new Date(s.created_at).toLocaleString() }}</div>
      <label class="muted" style="font-size:.8rem" v-if="runs.length">
        历史批次：
        <select :value="s.run_id" @change="onPick">
          <option v-for="r in runs" :key="r.id" :value="r.id">
            #{{ r.id }} · {{ new Date(r.created_at).toLocaleString() }} · 总补 {{ r.total_fill }}
          </option>
        </select>
      </label>
    </div>

    <table style="margin-top:.75rem">
      <thead>
        <tr><th>立柱字母（分册）</th><th>分册单号</th><th>总补件数</th><th>待补</th><th>满仓</th><th>超占</th><th>说明</th></tr>
      </thead>
      <tbody>
        <tr v-for="c in s.columns" :key="c.column_key">
          <td style="font-weight:700">{{ c.column_key }}</td>
          <td>{{ c.order_id ? '#' + c.order_id : '—' }}</td>
          <td class="stat" style="font-size:1.1rem">{{ c.total_fill }}</td>
          <td>{{ c.need_fill_count }}</td>
          <td>{{ c.full_count }}</td>
          <td>{{ c.overbooked_count }}</td>
          <td class="muted">{{ c.has_pending ? '已建分册' : '无待补货道 · 补量 0 · 未建空单（字母键保留）' }}</td>
        </tr>
      </tbody>
      <tfoot>
        <tr style="font-weight:700;border-top:2px solid var(--vf-line,#8a7e64)">
          <td>各分册之和</td><td></td>
          <td :class="{ 'vf-warn-text': !reconciled }">{{ sumOfBooklets }}</td>
          <td colspan="3"></td>
          <td v-if="reconciled" class="muted" style="font-weight:600">= 整机 {{ s.total_fill }} · 对账一致</td>
          <td v-else class="vf-warn">≠ 整机 {{ s.total_fill }}，对不齐即废</td>
        </tr>
      </tfoot>
    </table>
  </div>
</template>
