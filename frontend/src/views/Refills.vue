<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const data = ref<any>(null)
const history = ref<any[]>([])
const opened = ref<any>(null)
async function run() {
  opened.value = null
  data.value = await api('/refills/run?location_id=1', { method: 'POST' })
  history.value = await api('/refills/sheets?location_id=1')
}
async function openSheet(id: number) {
  opened.value = await api('/refills/sheets/' + id)
}
onMounted(run)
</script>
<template>
  <h1>补货小票</h1>
  <p class="sub">按货道编号首字母拆单 · 一个字母落一张分册 · gap = 容量 − 库存 − 在途</p>
  <button class="btn" @click="run">生成补货单</button>
  <div style="margin-top:1rem" v-if="data">
    <div class="vf-sheet-row">
      <div class="vf-receipt" v-for="s in data.sheets" :key="s.id">
        <h2>*** {{ s.letter }} 组补货单 ***</h2>
        <div class="vf-receipt-line" style="font-weight:700;border-bottom:2px dashed #8a7e64">
          <span>货道 / 商品</span><span>补量</span>
        </div>
        <div class="vf-receipt-line" v-for="l in s.lines" :key="l.lane_id">
          <span>{{ l.slot_no }} {{ l.sku_name }}
            <small>({{ l.status === 'need_fill' ? '待补' : l.status === 'full' ? '满仓' : '超占' }})</small>
          </span>
          <span>{{ l.fill_qty }} / 缺{{ l.gap }}</span>
        </div>
        <div class="vf-receipt-line" style="font-weight:800;border-top:2px dashed #8a7e64">
          <span>{{ s.letter }} 组合计</span><span>{{ s.total_fill }} 件</span>
        </div>
        <p style="text-align:center;margin:0.75rem 0 0;font-size:0.72rem;color:#6a5e48">仅含 {{ s.letter }} 组货道 · 请核对后装机</p>
      </div>
    </div>
    <p class="muted" style="font-size:0.8rem">
      整机合计 {{ data.total_fill }} 件 = Σ各分册 {{ data.sheets_total }} 件
      <span class="badge" :class="data.sheets_total === data.total_fill ? 'badge-ok' : 'badge-bad'">
        {{ data.sheets_total === data.total_fill ? '平账' : '对不齐' }}
      </span>
    </p>
  </div>
  <div class="card" v-if="history.length" style="margin-top:1rem">
    <div class="muted" style="font-size:0.78rem;margin-bottom:0.5rem">本批次历史分册（点开为生成时快照，改货道编号不改口）</div>
    <button v-for="h in history" :key="h.id" class="vf-sheet-chip" @click="openSheet(h.id)">
      #{{ h.id }} · {{ h.letter }} 组 · {{ h.total_fill }} 件
    </button>
    <div class="vf-receipt" v-if="opened" style="margin-top:0.85rem">
      <h2>*** 历史分册 #{{ opened.id }} · {{ opened.letter }} 组 ***</h2>
      <div class="vf-receipt-line" v-for="l in opened.lines" :key="l.lane_id">
        <span>{{ l.slot_no }} {{ l.sku_name }}</span>
        <span>{{ l.fill_qty }} 件</span>
      </div>
      <div class="vf-receipt-line" style="font-weight:800;border-top:2px dashed #8a7e64">
        <span>合计</span><span>{{ opened.total_fill }} 件</span>
      </div>
      <p style="text-align:center;margin:0.75rem 0 0;font-size:0.72rem;color:#6a5e48">
        生成于 {{ opened.created_at }} · 快照归属 {{ opened.letter }} 组
      </p>
    </div>
  </div>
</template>
