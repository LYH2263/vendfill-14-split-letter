<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

interface ColLine {
  slot_no: string; sku_name: string; fill_qty: number; gap: number; status: string; column_key: string
}
interface Column {
  column_key: string
  order_id: number | null
  total_fill: number
  need_fill_count: number
  full_count: number
  overbooked_count: number
  has_pending: boolean
  lines: ColLine[]
}
interface Run {
  id: number
  created_at: string
  total_fill: number
  columns: Column[]
}

const data = ref<Run | null>(null)
const runs = ref<{ id: number; created_at: string; total_fill: number }[]>([])
const loading = ref(false)
const error = ref('')

// 前端独立再加一遍：各分册补量之和必须等于整机总补件数，对不齐即废。
const sumOfBooklets = computed(() =>
  data.value ? data.value.columns.reduce((n, c) => n + c.total_fill, 0) : 0)
const reconciled = computed(() => data.value !== null && sumOfBooklets.value === data.value.total_fill)

async function loadRuns() {
  runs.value = await api('/refills/runs?location_id=1')
}
async function openRun(id: number) {
  error.value = ''
  data.value = await api(`/refills/runs/${id}`)
}
async function run() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api('/refills/run?location_id=1', { method: 'POST' })
    await loadRuns()
  } catch (e: any) {
    error.value = e?.message || '生成失败'
  } finally {
    loading.value = false
  }
}

const statusText = (s: string) => s === 'need_fill' ? '待补' : s === 'full' ? '满仓' : '超占'

onMounted(async () => {
  await loadRuns()
  // latest 在该点位尚无批次时会原子生成一批；有批次则只读最新历史快照
  try {
    data.value = await api('/refills/latest?location_id=1')
    await loadRuns()
  } catch (e: any) {
    error.value = e?.message || ''
  }
})
</script>
<template>
  <h1>补货小票 · 立柱分册</h1>
  <p class="sub">按货道编号首字母拆单：一个字母一册，单上只含该组货道 · 各册之和须等于整机总量</p>
  <div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">
    <button class="btn" :disabled="loading" @click="run">
      {{ loading ? '生成中…' : '生成本次整机补货单' }}
    </button>
    <label class="muted" style="font-size:.8rem" v-if="runs.length">
      历史批次：
      <select :value="data?.id" @change="openRun(Number(($event.target as HTMLSelectElement).value))">
        <option v-for="r in runs" :key="r.id" :value="r.id">
          #{{ r.id }} · {{ new Date(r.created_at).toLocaleString() }} · 总补 {{ r.total_fill }}
        </option>
      </select>
    </label>
  </div>

  <p v-if="error" class="vf-warn">拆单失败，未生成任何分册（整批已回滚）：{{ error }}</p>

  <div v-if="data" style="margin-top:1rem">
    <div class="vf-booklet-row">
      <div class="vf-receipt" v-for="c in data.columns" :key="c.column_key">
        <h2>*** {{ c.column_key }} 立柱分册 ***</h2>
        <div class="vf-receipt-line" style="font-weight:700;border-bottom:2px dashed #8a7e64">
          <span>货道 / 商品</span><span>补量</span>
        </div>
        <template v-if="c.order_id">
          <div class="vf-receipt-line" v-for="l in c.lines" :key="l.slot_no">
            <span>{{ l.slot_no }} {{ l.sku_name }} <small>({{ statusText(l.status) }})</small></span>
            <span>{{ l.fill_qty }} / 缺{{ l.gap }}</span>
          </div>
          <div class="vf-receipt-line" style="font-weight:700;border-top:2px dashed #8a7e64">
            <span>{{ c.column_key }} 册小计</span><span>{{ c.total_fill }}</span>
          </div>
          <p style="text-align:center;margin:.6rem 0 0;font-size:.68rem;color:#6a5e48">
            分册单号 #{{ c.order_id }} · 批次 #{{ data.id }}
          </p>
        </template>
        <p v-else class="muted" style="margin:.8rem 0 .4rem;font-size:.74rem;text-align:center">
          本批 {{ c.column_key }} 立柱无待补货道，补量 0，未建空单
        </p>
      </div>
    </div>

    <div class="card" style="margin-top:1rem">
      <div style="display:flex;gap:1.5rem;flex-wrap:wrap;align-items:baseline">
        <div><span class="muted">批次 #{{ data.id }} 整机总补件数：</span>
          <span class="stat">{{ data.total_fill }}</span></div>
        <div><span class="muted">各分册之和：</span>
          <span class="stat" :class="{ 'vf-warn-text': !reconciled }">{{ sumOfBooklets }}</span></div>
        <div v-if="reconciled" class="muted" style="font-size:.85rem">
          Σ({{ data.columns.map(c => c.column_key + '=' + c.total_fill).join(' + ') }})
          = {{ data.total_fill }} · 对账一致
        </div>
        <div v-else class="vf-warn">对不齐即废：分册之和 {{ sumOfBooklets }} ≠ 整机 {{ data.total_fill }}</div>
      </div>
    </div>
    <p style="text-align:center;margin:.8rem 0 0;font-size:.72rem;color:#6a5e48">历史分册按生成时快照展示 · 事后改动货道编号不会改口</p>
  </div>
</template>
