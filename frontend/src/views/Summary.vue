<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const s = ref<any>(null)
onMounted(async () => { s.value = await api('/refills/summary?location_id=1') })
</script>
<template>
  <h1>汇总</h1>
  <p class="sub">按点位对账 · 各分册之和必须等于本次整机总补件数，对不齐即废</p>
  <template v-if="s">
    <div class="card grid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem">
      <div><div class="muted">整机总补件数</div><div class="stat">{{ s.total_fill }}</div></div>
      <div><div class="muted">分册数</div><div class="stat">{{ s.sheets.length }}</div></div>
      <div><div class="muted">待补货道</div><div class="stat">{{ s.need_fill_count }}</div></div>
      <div><div class="muted">满仓货道</div><div class="stat">{{ s.full_count }}</div></div>
      <div><div class="muted">超占货道</div><div class="stat">{{ s.overbooked_count }}</div></div>
    </div>
    <div class="card">
      <div class="muted" style="font-size:0.78rem;margin-bottom:0.4rem">字母台账（补量为 0 的字母也保留键，不静默丢弃）</div>
      <table>
        <thead><tr><th>字母组</th><th>补量（件）</th><th>分册</th></tr></thead>
        <tbody>
          <tr v-for="(qty, letter) in s.letters" :key="letter">
            <td>{{ letter }} 组</td>
            <td :class="{ muted: qty === 0 }">{{ qty }}</td>
            <td>{{ qty > 0 ? '#' + (s.sheets.find((x: any) => x.letter === letter) || {}).id : '无（无需补货，不建空单）' }}</td>
          </tr>
          <tr style="font-weight:700">
            <td>Σ 字母台账</td><td>{{ s.letters_total }}</td><td></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="card">
      <div class="muted" style="font-size:0.78rem;margin-bottom:0.4rem">分册对账（批次 #{{ s.order_id }} · {{ s.created_at }}）</div>
      <table>
        <thead><tr><th>分册</th><th>行数</th><th>合计（件）</th></tr></thead>
        <tbody>
          <tr v-for="sh in s.sheets" :key="sh.id">
            <td>#{{ sh.id }} · {{ sh.letter }} 组</td>
            <td>{{ sh.line_count }}</td>
            <td>{{ sh.total_fill }}</td>
          </tr>
          <tr style="font-weight:700">
            <td>Σ 各分册</td><td></td><td>{{ s.sheets_total }}</td>
          </tr>
        </tbody>
      </table>
      <p style="margin:0.6rem 0 0;font-size:0.82rem">
        Σ分册 {{ s.sheets_total }} 件 = Σ字母 {{ s.letters_total }} 件 = 整机 {{ s.total_fill }} 件
        <span class="badge" :class="s.balanced ? 'badge-ok' : 'badge-bad'">
          {{ s.balanced ? '平账' : '对不齐 · 本批作废' }}
        </span>
      </p>
    </div>
  </template>
</template>
