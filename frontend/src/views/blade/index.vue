<template>
  <section class="page" data-module="blade">
    <header class="page-head">
      <div>
        <h2>叶片管理</h2>
        <p class="page-desc">检查结论按「叶片长度、裂纹数量、雷击次数」统一判定：裂纹超长度档上限即存在裂纹；雷击达阈值须补充说明才能保存。</p>
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
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            {{ row[column] ?? '—' }}
            <span v-if="column === '叶片状态' && row['雷击待说明']" class="warn-tag" title="雷击达阈值，检查时须补充说明">雷击待说明</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openInspect(row)">提交检查</button>
            <button class="link" type="button" @click="openHistory(row)">检查记录</button>
            <button class="link" type="button" @click="runAction('登记缺陷', row)">登记缺陷</button>
            <button class="link" type="button" @click="runAction('更换叶片', row)">更换叶片</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无叶片数据，可先登记叶片</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条叶片记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 提交检查 -->
    <div v-if="inspectOpen" class="modal-mask" @click.self="inspectOpen = false">
      <div class="modal">
        <h3>提交叶片检查 · {{ inspectForm.叶片编号 }}</h3>
        <p class="modal-tip">叶片长度 {{ inspectForm.叶片长度 }} 米，结论由三项口径自动判定，无需手填。</p>
        <form class="modal-form" @submit.prevent="submitInspection">
          <label>
            <span>裂纹数量（条）</span>
            <input v-model="inspectForm.裂纹数量" type="number" min="0" step="1" required />
          </label>
          <label>
            <span>雷击次数（次，≥{{ lightningLimit }} 须补充说明）</span>
            <input v-model="inspectForm.雷击次数" type="number" min="0" step="1" required />
          </label>
          <label>
            <span>检查日期</span>
            <input v-model="inspectForm.上次检查日" type="date" />
          </label>
          <label>
            <span>补充说明（雷击达阈值时必填）</span>
            <textarea v-model="inspectForm.补充说明" rows="3" placeholder="雷击部位、损伤情况与处理措施"></textarea>
          </label>
          <p v-if="inspectError" class="error-text">{{ inspectError }}</p>
          <div class="modal-actions">
            <button class="btn ghost" type="button" @click="inspectOpen = false">取消</button>
            <button class="btn primary" type="submit">保存并判定</button>
          </div>
        </form>
      </div>
    </div>

    <!-- 检查记录：只展示最新结论 + 历次判定依据 -->
    <div v-if="historyOpen" class="modal-mask" @click.self="historyOpen = false">
      <div class="modal wide">
        <h3>检查记录 · {{ historyTarget?.['叶片编号'] }}</h3>
        <p class="modal-tip">
          最新结论：<strong>{{ historyTarget?.['检查结论'] || '尚无检查结论' }}</strong>，
          共 {{ historyRecords.length }} 次提交，历次判定依据均保留如下。
        </p>
        <div class="history-list">
          <article v-for="rec in [...historyRecords].reverse()" :key="rec.序号" class="history-item">
            <header>
              <strong>第{{ rec.序号 }}次 · {{ rec.结论 }}</strong>
              <span>{{ rec.提交时间 }} · {{ rec.来源 }}</span>
            </header>
            <p class="history-basis">{{ rec.判定依据?.判定说明 }}</p>
            <p v-if="rec.补充说明" class="history-note">补充说明：{{ rec.补充说明 }}</p>
          </article>
          <p v-if="!historyRecords.length" class="empty-state">该叶片还没有提交过检查</p>
        </div>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="historyOpen = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 批量补录 -->
    <div v-if="backfillOpen" class="modal-mask" @click.self="backfillOpen = false">
      <div class="modal wide">
        <h3>批量补录历史检查记录</h3>
        <p class="modal-tip">
          粘贴 JSON 数组，字段：叶片编号、叶片长度、裂纹数量、雷击次数、补充说明、上次检查日（可选）、检查结论（原结论，可选）。
          系统按同一套口径重算；长度与台账对不上的记录不会写入，会逐条列出原因。
        </p>
        <textarea v-model="backfillText" class="backfill-input" rows="10" placeholder='[{"叶片编号":"BLAD-0001","叶片长度":"48","裂纹数量":1,"雷击次数":0,"检查结论":"完好"}]'></textarea>
        <p v-if="backfillError" class="error-text">{{ backfillError }}</p>
        <div v-if="backfillResult" class="backfill-result">
          <p>共 {{ backfillResult.total }} 条：重算写入 {{ backfillResult.applied_count }} 条，挑出 {{ backfillResult.rejected_count }} 条。</p>
          <table class="data-table">
            <thead>
              <tr><th>序号</th><th>叶片编号</th><th>原结论</th><th>重算结论</th><th>情况</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in backfillResult.applied" :key="`a-${item.序号}`">
                <td>{{ item.序号 }}</td><td>{{ item.叶片编号 }}</td>
                <td>{{ item.原结论 ?? '—' }}</td><td>{{ item.重算结论 }}</td>
                <td>{{ item.结论有调整 ? '结论已按口径更正' : '一致，已写入' }}</td>
              </tr>
              <tr v-for="item in backfillResult.rejected" :key="`r-${item.序号}`" class="reject-row">
                <td>{{ item.序号 }}</td><td>{{ item.叶片编号 }}</td>
                <td>{{ item.原结论 ?? '—' }}</td><td>—</td>
                <td class="error-text">{{ item.原因 }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="backfillOpen = false">关闭</button>
          <button class="btn primary" type="button" @click="submitBackfill">按口径重算并补录</button>
        </div>
      </div>
    </div>

    <!-- 登记叶片 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal">
        <h3>登记叶片</h3>
        <form class="modal-form" @submit.prevent="submitCreate">
          <label v-for="field in createFields" :key="field">
            <span>{{ field }}</span>
            <input v-model="createForm[field]" :placeholder="field === '叶片长度' ? '按米填写，如 68' : `请输入${field}`" />
          </label>
          <p v-if="createError" class="error-text">{{ createError }}</p>
          <div class="modal-actions">
            <button class="btn ghost" type="button" @click="createOpen = false">取消</button>
            <button class="btn primary" type="submit">登记</button>
          </div>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null | InspectionRecord[]>
type InspectionRecord = {
  序号: number
  提交时间: string
  来源: string
  结论: string
  补充说明: string
  判定依据?: Record<string, string | number | boolean>
}

const ENDPOINT = '/api/blade'
const lightningLimit = 2
const columns = ["叶片编号", "所属机组", "叶片长度", "制造厂商", "上次检查日", "裂纹数量", "雷击次数", "叶片状态"]
const createFields = ["叶片编号", "所属机组", "叶片长度", "制造厂商"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const stats = computed(() => {
  const cracked = rows.value.filter((row) => row['检查结论'] === '存在裂纹' || row['status'] === '存在裂纹').length
  const waiting = rows.value.filter((row) => (row['status'] ?? '待检查') === '待检查').length
  const lightning = rows.value.filter((row) => Number(row['雷击次数'] ?? 0) >= lightningLimit).length
  return [
    { label: '待检查叶片', value: waiting },
    { label: '存在裂纹叶片', value: cracked },
    { label: '雷击达阈值叶片', value: lightning },
  ]
})

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
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
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '叶片列表读取失败'
  }
}

// ---- 提交检查 -------------------------------------------------------

const inspectOpen = ref(false)
const inspectError = ref('')
const inspectTarget = ref<Row | null>(null)
const inspectForm = reactive<Record<string, string | number>>({
  id: 0,
  叶片编号: '',
  叶片长度: '',
  裂纹数量: 0,
  雷击次数: 0,
  上次检查日: '',
  补充说明: '',
})

function openInspect(row: Row) {
  inspectTarget.value = row
  inspectError.value = ''
  Object.assign(inspectForm, {
    id: row.id,
    叶片编号: row['叶片编号'],
    叶片长度: row['叶片长度'],
    裂纹数量: Number(row['裂纹数量'] ?? 0),
    雷击次数: Number(row['雷击次数'] ?? 0),
    上次检查日: '',
    补充说明: '',
  })
  inspectOpen.value = true
}

async function submitInspection() {
  inspectError.value = ''
  try {
    const response = await request(`${ENDPOINT}/${inspectForm.id}/inspections`, {
      method: 'POST',
      body: JSON.stringify({
        裂纹数量: inspectForm.裂纹数量,
        雷击次数: inspectForm.雷击次数,
        上次检查日: inspectForm.上次检查日,
        补充说明: inspectForm.补充说明,
      }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '检查未保存')
    }
    inspectOpen.value = false
    await reload()
  } catch (error) {
    inspectError.value = error instanceof Error ? error.message : '检查提交失败'
  }
}

// ---- 检查记录 -------------------------------------------------------

const historyOpen = ref(false)
const historyTarget = ref<Row | null>(null)
const historyRecords = computed<InspectionRecord[]>(() => {
  const value = historyTarget.value?.['检查记录']
  return Array.isArray(value) ? (value as InspectionRecord[]) : []
})

function openHistory(row: Row) {
  historyTarget.value = row
  historyOpen.value = true
}

// ---- 批量补录 -------------------------------------------------------

const backfillOpen = ref(false)
const backfillText = ref('')
const backfillError = ref('')
const backfillResult = ref<{
  total: number
  applied_count: number
  rejected_count: number
  applied: Array<Record<string, string | number | boolean>>
  rejected: Array<Record<string, string | number>>
} | null>(null)

function openBackfill() {
  backfillError.value = ''
  backfillResult.value = null
  backfillText.value = ''
  backfillOpen.value = true
}

async function submitBackfill() {
  backfillError.value = ''
  backfillResult.value = null
  let parsed: unknown
  try {
    parsed = JSON.parse(backfillText.value || '[]')
  } catch {
    backfillError.value = 'JSON 格式无法解析，请核对括号与引号'
    return
  }
  const records = Array.isArray(parsed) ? parsed : (parsed as { records?: unknown })?.records
  if (!Array.isArray(records)) {
    backfillError.value = '内容需为记录数组，或包含 records 数组的对象'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/inspections/backfill`, {
      method: 'POST',
      body: JSON.stringify({ records }),
    })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail || '补录未完成')
    }
    backfillResult.value = payload
    await reload()
  } catch (error) {
    backfillError.value = error instanceof Error ? error.message : '批量补录失败'
  }
}

// ---- 登记叶片 -------------------------------------------------------

const createOpen = ref(false)
const createError = ref('')
const createForm = reactive<Record<string, string>>({
  叶片编号: '',
  所属机组: '',
  叶片长度: '',
  制造厂商: '',
})

function openCreate() {
  createError.value = ''
  createFields.forEach((field) => { createForm[field] = '' })
  createOpen.value = true
}

async function submitCreate() {
  createError.value = ''
  const values: Record<string, string> = {}
  createFields.forEach((field) => { values[field] = createForm[field] })
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '叶片未登记')
    }
    createOpen.value = false
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '叶片登记失败'
  }
}

// ---- 其余动作：登记缺陷 / 更换叶片 ----------------------------------

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '叶片动作未生效')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '叶片操作失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }
.warn-tag {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  font-size: 11px;
  color: #b54708;
  background: #fef3c7;
  border: 1px solid #f59e0b;
  border-radius: 4px;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  width: 420px;
  max-height: 86vh;
  overflow-y: auto;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.2);
}
.modal.wide { width: 720px; }
.modal h3 { margin: 0 0 8px; font-size: 16px; }
.modal-tip { margin: 0 0 12px; font-size: 12px; color: var(--muted); line-height: 1.6; }
.modal-form { display: flex; flex-direction: column; gap: 10px; }
.modal-form label span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.modal-form input, .modal-form textarea {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font: inherit;
}
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }
.history-list { display: flex; flex-direction: column; gap: 8px; }
.history-item { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.history-item header { display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 6px; }
.history-item header span { color: var(--muted); font-size: 12px; }
.history-basis { margin: 0 0 4px; font-size: 12px; line-height: 1.6; }
.history-note { margin: 0; font-size: 12px; color: #b54708; }
.backfill-input {
  width: 100%;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-family: ui-monospace, monospace;
  font-size: 12px;
}
.backfill-result { margin-top: 12px; }
.backfill-result .data-table { margin-top: 8px; }
.reject-row { background: #fef2f2; }
</style>
