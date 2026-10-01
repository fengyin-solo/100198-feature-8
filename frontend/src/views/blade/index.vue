<template>
  <section class="page" data-module="blade">
    <header class="page-head">
      <div>
        <h2>叶片管理</h2>
        <p class="page-desc">
          检查结论按口径自动判定：叶片长度对应裂纹允许上限，裂纹数量超限判定为「存在裂纹」；
          雷击次数达到 {{ lightningThreshold }} 次须填写补充说明。同片叶片重复检查只保留最新结论，历次依据可追溯。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记叶片</button>
        <button class="btn" type="button" @click="openBackfill">批量补录历史检查</button>
        <button class="btn" type="button" @click="exportRows">导出叶片清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>判定依据（最新一次）</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="basis-cell">
            <ol v-if="latestBasis(row).length" class="basis-list">
              <li v-for="(line, idx) in latestBasis(row)" :key="idx">{{ line }}</li>
            </ol>
            <span v-else class="muted">尚未提交检查</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openInspect(row)">提交检查</button>
            <button class="link" type="button" @click="openHistory(row)">检查记录</button>
            <button class="link" type="button" @click="runAction('登记缺陷', row)">登记缺陷</button>
            <button class="link" type="button" @click="runAction('更换叶片', row)">更换叶片</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无叶片数据，可先登记叶片</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条叶片记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 提交检查弹窗 -->
    <div v-if="inspectVisible" class="blade-mask" @click.self="closeInspect">
      <div class="blade-dialog">
        <h3>提交检查 · {{ inspectForm.叶片编号 }}</h3>
        <p class="rule-hint">{{ ruleHint }}</p>
        <form class="blade-form" @submit.prevent="submitInspection">
          <label>
            <span>叶片长度（台账）</span>
            <input :value="inspectForm.叶片长度" disabled />
          </label>
          <label>
            <span>检查日期</span>
            <input v-model="inspectForm.检查日期" type="date" />
          </label>
          <label>
            <span>裂纹数量（条）</span>
            <input v-model.number="inspectForm.裂纹数量" type="number" min="0" required />
          </label>
          <label>
            <span>雷击次数（次）</span>
            <input v-model.number="inspectForm.雷击次数" type="number" min="0" required />
          </label>
          <label class="full-row" :class="{ required: needsRemark }">
            <span>补充说明 <em v-if="needsRemark">（雷击达到 {{ lightningThreshold }} 次，必填）</em></span>
            <textarea v-model="inspectForm.补充说明" rows="3" placeholder="如：雷击部位、损伤情况、处置措施"></textarea>
          </label>
          <p v-if="inspectError" class="error-text">{{ inspectError }}</p>
          <div class="dialog-foot">
            <button class="btn ghost" type="button" @click="closeInspect">取消</button>
            <button class="btn primary" type="submit">保存并判定</button>
          </div>
        </form>
      </div>
    </div>

    <!-- 历史检查记录弹窗 -->
    <div v-if="historyVisible" class="blade-mask" @click.self="closeHistory">
      <div class="blade-dialog wide">
        <h3>检查记录 · {{ historyTarget?.['叶片编号'] }}</h3>
        <p class="rule-hint">同片叶片重复提交只保留最新结论，以下为历次判定依据，最新一次在最后。</p>
        <div v-if="!historyItems.length" class="muted">该叶片暂无检查记录</div>
        <article v-for="record in historyItems" :key="String(record['序号'])" class="history-card">
          <header>
            <strong>第 {{ record['序号'] }} 次 · {{ record['检查日期'] }} ·
              <span :class="record['检查结论'] === '存在裂纹' ? 'tag-bad' : 'tag-ok'">{{ record['检查结论'] }}</span>
            </strong>
            <span class="muted">{{ record['来源'] }}</span>
          </header>
          <p class="history-meta">
            长度 {{ record['叶片长度'] }}（上限 {{ record['裂纹允许上限'] }} 条）·
            裂纹 {{ record['裂纹数量'] }} 条 · 雷击 {{ record['雷击次数'] }} 次
          </p>
          <ol class="basis-list">
            <li v-for="(line, idx) in record['判定依据']" :key="idx">{{ line }}</li>
          </ol>
          <p v-if="record['补充说明']" class="history-remark">补充说明：{{ record['补充说明'] }}</p>
        </article>
        <div class="dialog-foot">
          <button class="btn primary" type="button" @click="closeHistory">关闭</button>
        </div>
      </div>
    </div>

    <!-- 批量补录弹窗 -->
    <div v-if="backfillVisible" class="blade-mask" @click.self="closeBackfill">
      <div class="blade-dialog wide">
        <h3>批量补录历史检查记录</h3>
        <p class="rule-hint">
          粘贴 JSON 数组，按同一套口径重算结论。支持字段：叶片编号、叶片长度、裂纹数量、雷击次数、
          检查日期、补充说明、原检查结论。与长度对不上或结论不一致的记录会被挑出来说明原因。
        </p>
        <textarea
          v-model="backfillText"
          class="backfill-input"
          rows="10"
          spellcheck="false"
          placeholder='[&#10;  {"叶片编号":"BLAD-0001","叶片长度":"68米","裂纹数量":3,"雷击次数":0,"检查日期":"2026-08-01","原检查结论":"完好"}&#10;]'
        ></textarea>
        <p v-if="backfillError" class="error-text">{{ backfillError }}</p>

        <div v-if="backfillReport" class="backfill-report">
          <p>
            共 {{ backfillReport['总数'] }} 条，成功补录 {{ backfillReport['补录条数'] }} 条，
            挑出问题记录 {{ backfillReport['异常条数'] }} 条
          </p>
          <table v-if="backfillReport['问题记录']?.length" class="data-table issue-table">
            <thead>
              <tr><th>行号</th><th>叶片编号</th><th>原结论</th><th>重算结论</th><th>是否补录</th><th>问题原因</th></tr>
            </thead>
            <tbody>
              <tr v-for="issue in backfillReport['问题记录']" :key="String(issue['行号'])">
                <td>{{ issue['行号'] }}</td>
                <td>{{ issue['叶片编号'] ?? '—' }}</td>
                <td>{{ issue['原检查结论'] ?? '—' }}</td>
                <td>{{ issue['重算结论'] ?? '无法判定' }}</td>
                <td>{{ issue['已补录'] ? '已补录（以重算为准）' : '未保存' }}</td>
                <td>
                  <ul class="reason-list">
                    <li v-for="(reason, idx) in issue['问题原因']" :key="idx">{{ reason }}</li>
                  </ul>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="dialog-foot">
          <button class="btn ghost" type="button" @click="closeBackfill">关闭</button>
          <button class="btn primary" type="button" :disabled="backfillLoading" @click="submitBackfill">
            {{ backfillLoading ? '重算中…' : '按口径重算并补录' }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type InspectionRecord = Record<string, unknown>
type Row = Record<string, string | number | null | InspectionRecord[]>
type BackfillReport = {
  总数: number
  补录条数: number
  异常条数: number
  问题记录: Array<Record<string, unknown>>
}

const ENDPOINT = '/api/blade'
const columns = ["叶片编号", "所属机组", "叶片长度", "制造厂商", "上次检查日", "裂纹数量", "雷击次数", "检查结论", "叶片状态"]
const lightningThreshold = 3
const stats = ref([
  { label: "待检查叶片", value: 0 },
  { label: "存在裂纹叶片", value: 0 },
  { label: "雷击待补充说明", value: 0 },
])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = ["叶片编号", "所属机组", "叶片状态"]

function latestRecord(row: Row): InspectionRecord | null {
  const list = row['检查记录']
  return Array.isArray(list) && list.length ? list[list.length - 1] : null
}

function latestBasis(row: Row): string[] {
  const record = latestRecord(row)
  return (record?.['判定依据'] as string[] | undefined) ?? []
}

function refreshStats() {
  stats.value[0].value = rows.value.filter((row) => row['叶片状态'] === '待检查' || row['status'] === '待检查').length
  stats.value[1].value = rows.value.filter((row) => row['检查结论'] === '存在裂纹').length
  stats.value[2].value = rows.value.filter((row) => Number(row['雷击次数'] ?? 0) >= lightningThreshold).length
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '叶片登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message ?? '叶片动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '叶片操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('叶片列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    refreshStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '叶片列表读取失败'
  }
}

// ---- 提交检查 ----
const inspectVisible = ref(false)
const inspectError = ref('')
const inspectTarget = ref<Row | null>(null)
const inspectForm = ref<Record<string, string | number>>({})

const needsRemark = computed(() => Number(inspectForm.value['雷击次数'] ?? 0) >= lightningThreshold)
const ruleHint = computed(() => {
  const latest = inspectTarget.value ? latestRecord(inspectTarget.value) : null
  const limit = (latest?.['裂纹允许上限'] ?? inspectTarget.value?.['裂纹允许上限'])
  const limitText = limit === undefined || limit === null ? '按长度分档自动匹配' : `${limit} 条`
  return `裂纹数量超过该长度允许上限（${limitText}）判定为「存在裂纹」，否则为「完好」；雷击次数达到 ${lightningThreshold} 次（含）须填写补充说明。`
})

function openInspect(row: Row) {
  inspectTarget.value = row
  inspectError.value = ''
  inspectForm.value = {
    叶片编号: String(row['叶片编号'] ?? ''),
    叶片长度: String(row['叶片长度'] ?? ''),
    检查日期: new Date().toISOString().slice(0, 10),
    裂纹数量: Number(row['裂纹数量'] ?? 0),
    雷击次数: 0,
    补充说明: '',
  }
  inspectVisible.value = true
}

function closeInspect() {
  inspectVisible.value = false
  inspectTarget.value = null
}

async function submitInspection() {
  inspectError.value = ''
  if (needsRemark.value && !String(inspectForm.value['补充说明'] ?? '').trim()) {
    inspectError.value = `雷击次数达到 ${lightningThreshold} 次，必须填写补充说明后才能保存`
    return
  }
  const target = inspectTarget.value
  if (!target) return
  try {
    const response = await request(`${ENDPOINT}/${target.id}/inspections`, {
      method: 'POST',
      body: JSON.stringify({ values: inspectForm.value }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message ?? '检查提交失败')
    }
    closeInspect()
    await reload()
  } catch (error) {
    inspectError.value = error instanceof Error ? error.message : '检查提交失败'
  }
}

// ---- 历史检查记录 ----
const historyVisible = ref(false)
const historyTarget = ref<Row | null>(null)
const historyItems = ref<InspectionRecord[]>([])

async function openHistory(row: Row) {
  historyTarget.value = row
  historyItems.value = []
  historyVisible.value = true
  try {
    const response = await request(`${ENDPOINT}/${row.id}/inspections`)
    if (!response.ok) {
      throw new Error('检查记录读取失败')
    }
    const payload = await response.json()
    historyItems.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检查记录读取失败'
  }
}

function closeHistory() {
  historyVisible.value = false
  historyTarget.value = null
  historyItems.value = []
}

// ---- 批量补录 ----
const backfillVisible = ref(false)
const backfillText = ref('')
const backfillError = ref('')
const backfillLoading = ref(false)
const backfillReport = ref<BackfillReport | null>(null)

function openBackfill() {
  backfillError.value = ''
  backfillReport.value = null
  backfillText.value = ''
  backfillVisible.value = true
}

function closeBackfill() {
  backfillVisible.value = false
}

async function submitBackfill() {
  backfillError.value = ''
  backfillReport.value = null
  let records: unknown
  try {
    records = JSON.parse(backfillText.value || '[]')
  } catch {
    backfillError.value = 'JSON 格式有误，请检查后再提交'
    return
  }
  if (!Array.isArray(records) || !records.length) {
    backfillError.value = '请粘贴至少一条检查记录的 JSON 数组'
    return
  }
  backfillLoading.value = true
  try {
    const response = await request(`${ENDPOINT}/inspections/backfill`, {
      method: 'POST',
      body: JSON.stringify({ records }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === undefined) {
      throw new Error(payload?.message ?? payload?.detail ?? '批量补录失败')
    }
    backfillReport.value = payload.data as BackfillReport
    await reload()
  } catch (error) {
    backfillError.value = error instanceof Error ? error.message : '批量补录失败'
  } finally {
    backfillLoading.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.basis-cell {
  max-width: 360px;
  font-size: 12px;
  color: #5b6472;
  vertical-align: top;
}
.basis-list {
  margin: 0;
  padding-left: 18px;
}
.basis-list li {
  margin: 2px 0;
}
.muted {
  color: #9aa2af;
}
.blade-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.blade-dialog {
  width: 520px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 64px);
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 20px 24px;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.18);
}
.blade-dialog.wide {
  width: 820px;
}
.blade-dialog h3 {
  margin: 0 0 8px;
}
.rule-hint {
  font-size: 12px;
  color: #5b6472;
  background: #f4f7fb;
  border-radius: 6px;
  padding: 8px 10px;
  margin: 0 0 16px;
}
.blade-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 16px;
}
.blade-form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: #333c48;
}
.blade-form label.full-row {
  grid-column: 1 / -1;
}
.blade-form label.required span {
  color: #c2410c;
}
.blade-form input,
.blade-form textarea,
.backfill-input {
  border: 1px solid var(--border, #d8dde6);
  border-radius: 6px;
  padding: 6px 10px;
  font: inherit;
}
.backfill-input {
  width: 100%;
  box-sizing: border-box;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}
.dialog-foot {
  grid-column: 1 / -1;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.wide .dialog-foot {
  margin-top: 16px;
}
.history-card {
  border: 1px solid #e4e8ef;
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 10px;
}
.history-card header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.history-meta {
  font-size: 12px;
  color: #5b6472;
  margin: 4px 0;
}
.history-remark {
  font-size: 12px;
  margin: 6px 0 0;
  color: #92400e;
}
.tag-ok {
  color: #15803d;
}
.tag-bad {
  color: #c2410c;
}
.issue-table {
  margin-top: 8px;
  font-size: 12px;
}
.reason-list {
  margin: 0;
  padding-left: 16px;
}
</style>
